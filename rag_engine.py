"""
RAG 引擎：检索 → 生成 → 判定有/无答案 → 附带依据

这是系统的核心，回答你关心的两个问题：
  1. 检索到答案时，回复长什么样
  2. 检索不到时，回复长什么样，怎么判断

四层「无答案」判定机制：
  ① 相似度阈值（可选，需实测校准）
  ② Prompt 约束 —— 让 LLM 自己判断资料够不够（最实用）
  ③ 程序化检测 —— 匹配拒答话术
  ④ 统一输出 —— 无论有答案与否，都展示检索片段
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional

from config import DEFAULT_CONFIG


# ---------------------------------------------------------------- 数据结构

@dataclass
class RetrievedChunk:
    """一个检索结果"""
    content: str
    source: str
    chapter: str
    chunk_id: int
    score: Optional[float] = None      # L2 距离，越小越相似

    def brief(self, n: int = 100) -> str:
        text = self.content.replace("\n", " ").strip()
        return text[:n] + ("..." if len(text) > n else "")


@dataclass
class RAGResult:
    """一次问答的完整结果"""
    question: str
    answer: str
    found: bool                        # 是否从资料中找到了答案
    chunks: List[RetrievedChunk] = field(default_factory=list)
    refusal_reason: str = ""           # found=False 时的原因
    # 结局类型，用于精确区分「无答案」和「调用失败」
    #   answered  —— 成功生成回答
    #   refused   —— LLM 判定资料不足以回答
    #   error     —— LLM 调用失败（认证/网络/额度等），与资料无关
    #   filtered  —— 阈值过滤掉了全部片段
    #   empty     —— 检索结果为空
    outcome: str = "answered"

    def format(self) -> str:
        """格式化为面向用户的输出"""
        lines = []
        lines.append("=" * 66)
        lines.append(f"问题：{self.question}")
        lines.append("=" * 66)
        lines.append("")

        # ---------- 调用失败：明确指出是系统问题，不是资料问题 ----------
        if self.outcome == "error":
            lines.append("【回答】")
            lines.append(self.answer.strip())
            lines.append("")
            lines.append("⚠️  这是大模型调用失败，**不代表资料里没有答案**。")
            lines.append("    请检查 API Key、网络或账户额度后重试。")
            lines.append("")
            if self.chunks:
                lines.append(f"【检索结果】共 {len(self.chunks)} 个片段"
                             "（未参与判断，仅供参考）：")
                self._append_chunks(lines)
            return "\n".join(lines)

        # ---------- 正常有答案 ----------
        if self.found:
            lines.append("【回答】")
            lines.append(self.answer.strip())
            lines.append("")
            lines.append(f"【依据】检索到 {len(self.chunks)} 个相关片段：")
            self._append_chunks(lines)
            return "\n".join(lines)

        # ---------- 无答案（LLM 判定 / 阈值过滤 / 检索为空）----------
        lines.append("【回答】")
        lines.append(self.answer.strip())
        lines.append("")
        if self.refusal_reason:
            lines.append(f"（判定原因：{self.refusal_reason}）")
        lines.append("")

        if self.outcome == "empty":
            lines.append("【检索结果】知识库中没有检索到任何内容。")
        elif self.outcome == "filtered":
            lines.append(f"【检索结果】共 {len(self.chunks)} 个片段，"
                         "但相似度均未达到阈值：")
            self._append_chunks(lines)
        else:
            lines.append(f"【检索到的片段】共 {len(self.chunks)} 个，"
                         "但均与问题不相关：")
            self._append_chunks(lines)

        return "\n".join(lines)

    def _append_chunks(self, lines: List[str]) -> None:
        """统一输出检索片段"""
        for i, c in enumerate(self.chunks, 1):
            score_str = f"距离 {c.score:.4f}" if c.score is not None else "—"
            lines.append("")
            lines.append(f"  [{i}] {c.source} / {c.chapter} "
                         f"/ 块#{c.chunk_id} （{score_str}）")
            lines.append(f"      {c.brief(160)}")
        lines.append("")


# ---------------------------------------------------------------- Prompt

PROMPT_TEMPLATE = """请根据下面提供的上下文信息来回答问题。

要求：
1. 优先使用上下文中的信息作答，不要编造上下文中不存在的内容。
2. 如果上下文提供了**部分**相关信息，请基于这些信息作答，
   并明确指出资料中未涵盖的部分 —— 不要因为信息不完整就拒绝回答。
3. 只有当上下文**完全不涉及**该问题时，才回答：
   "抱歉，我无法从提供的资料中找到相关信息来回答此问题。"
4. 回答时尽量引用片段编号（如 [片段1]），便于用户核对出处。

上下文:
{context}

问题: {question}

回答:"""


# ---------------------------------------------------------------- 引擎

class RAGEngine:
    """RAG 问答引擎"""

    def __init__(self, cfg=None, vectorstore=None):
        self.cfg = cfg or DEFAULT_CONFIG
        self.vectorstore = vectorstore
        self.llm = None

    # ---------------- 索引 ----------------

    def load(self):
        """加载索引"""
        if self.vectorstore is None:
            from build_index import load_index
            self.vectorstore = load_index(self.cfg)
        return self

    # ---------------- LLM ----------------

    def _get_llm(self):
        """懒加载 LLM"""
        if self.llm is not None:
            return self.llm

        from config import get_api_key

        try:
            from langchain_deepseek import ChatDeepSeek
            self.llm = ChatDeepSeek(
                model=self.cfg.llm_model,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                api_key=get_api_key(),
            )
        except ImportError:
            # 退路：用 OpenAI 兼容接口
            from langchain_openai import ChatOpenAI
            self.llm = ChatOpenAI(
                model=self.cfg.llm_model,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                api_key=get_api_key(),
                base_url=self.cfg.llm_base_url,
            )
        return self.llm

    # ---------------- 检索 ----------------

    def retrieve(self, question: str, k: int = None) -> List[RetrievedChunk]:
        """
        检索相关片段，带相似度分数。

        注意：BGE 中文模型是非对称检索训练的 ——
        「查询」需要加指令前缀，「文档」不加。
        前缀只作用于检索时的查询编码，不影响文档向量。
        """
        k = k or self.cfg.top_k

        # 加查询指令前缀（配置为空则不改动）
        prefix = getattr(self.cfg, "query_instruction", "") or ""
        search_query = f"{prefix}{question}" if prefix else question

        pairs = self.vectorstore.similarity_search_with_score(search_query, k=k)

        chunks = []
        for doc, score in pairs:
            chunks.append(RetrievedChunk(
                content=doc.page_content,
                source=doc.metadata.get("source", "未知来源"),
                chapter=doc.metadata.get("chapter", "未知章节"),
                chunk_id=doc.metadata.get("chunk_id", -1),
                score=float(score),
            ))
        return chunks

    # ---------------- 判定 ----------------

    def _is_refusal(self, answer: str) -> bool:
        """机制③：程序化检测 LLM 是否拒答"""
        return any(m in answer for m in self.cfg.refusal_markers)

    def _filter_by_threshold(self, chunks: List[RetrievedChunk]):
        """机制①：按 L2 距离阈值过滤（距离越小越相似）"""
        th = self.cfg.score_threshold
        if th is None:
            return chunks, None
        kept = [c for c in chunks if c.score is not None and c.score <= th]
        if not kept:
            return [], f"全部片段距离 > {th}（阈值）"
        return kept, None

    # ---------------- 问答 ----------------

    def ask(self, question: str, k: int = None) -> RAGResult:
        """完整问答流程"""
        question = question.strip()
        if not question:
            return RAGResult(question="", answer="问题为空。",
                             found=False, refusal_reason="空输入",
                             outcome="empty")

        # ① 检索
        chunks = self.retrieve(question, k=k)
        if not chunks:
            return RAGResult(question=question,
                             answer="抱歉，知识库中没有检索到任何内容。",
                             found=False, refusal_reason="检索结果为空",
                             outcome="empty")

        # ① 阈值过滤（可选）
        usable, filter_reason = self._filter_by_threshold(chunks)
        if not usable:
            return RAGResult(
                question=question,
                answer="抱歉，我无法从提供的资料中找到相关信息来回答此问题。",
                found=False, chunks=chunks, refusal_reason=filter_reason,
                outcome="filtered",
            )

        # ② 拼上下文 + Prompt 约束
        context = "\n\n".join(
            f"[片段{i}] 来源：{c.source}\n{c.content}"
            for i, c in enumerate(usable, 1)
        )
        prompt = PROMPT_TEMPLATE.format(context=context, question=question)

        # ③ 生成
        try:
            answer = self._get_llm().invoke(prompt)
            answer_text = getattr(answer, "content", str(answer))
        except Exception as e:
            # ⚠️ 调用失败 ≠ 资料里没有答案
            #    必须区分开，否则会误导用户以为知识库没内容
            return RAGResult(
                question=question,
                answer=f"调用大模型失败：{e}",
                found=False, chunks=chunks,
                refusal_reason="LLM 调用异常（非资料问题）",
                outcome="error",
            )

        # ④ 判定有/无答案
        found = not self._is_refusal(answer_text)

        return RAGResult(
            question=question,
            answer=answer_text,
            found=found,
            chunks=chunks,
            refusal_reason="" if found else "LLM 判定资料不足以回答",
            outcome="answered" if found else "refused",
        )


# ---------------------------------------------------------------- 自测

if __name__ == "__main__":
    print("RAGEngine 模块。请通过 main.py 使用。")
