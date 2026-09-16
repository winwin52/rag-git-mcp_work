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

    def format(self) -> str:
        """格式化为面向用户的输出"""
        lines = []
        lines.append("=" * 66)
        lines.append(f"问题：{self.question}")
        lines.append("=" * 66)

        if self.found:
            lines.append("")
            lines.append("【回答】")
            lines.append(self.answer.strip())
            lines.append("")
            lines.append(f"【依据】检索到 {len(self.chunks)} 个相关片段：")
        else:
            lines.append("")
            lines.append("【回答】")
            lines.append(self.answer.strip())
            lines.append("")
            if self.refusal_reason:
                lines.append(f"（判定原因：{self.refusal_reason}）")
            lines.append("")
            lines.append(f"【检索到的片段】共 {len(self.chunks)} 个，"
                         "但均与问题不相关：")

        for i, c in enumerate(self.chunks, 1):
            score_str = f"距离 {c.score:.4f}" if c.score is not None else "—"
            lines.append("")
            lines.append(f"  [{i}] {c.source} / {c.chapter} "
                         f"/ 块#{c.chunk_id} （{score_str}）")
            lines.append(f"      {c.brief(160)}")

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------- Prompt

PROMPT_TEMPLATE = """请根据下面提供的上下文信息来回答问题。
请确保你的回答完全基于这些上下文，不要使用上下文之外的知识。
如果上下文中没有足够的信息来回答问题，请直接告知：
"抱歉，我无法从提供的资料中找到相关信息来回答此问题。"

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
        """检索相关片段，带相似度分数"""
        k = k or self.cfg.top_k
        pairs = self.vectorstore.similarity_search_with_score(question, k=k)

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
                             found=False, refusal_reason="空输入")

        # ① 检索
        chunks = self.retrieve(question, k=k)
        if not chunks:
            return RAGResult(question=question,
                             answer="抱歉，知识库中没有检索到任何内容。",
                             found=False, refusal_reason="检索结果为空")

        # ① 阈值过滤（可选）
        usable, filter_reason = self._filter_by_threshold(chunks)
        if not usable:
            return RAGResult(
                question=question,
                answer="抱歉，我无法从提供的资料中找到相关信息来回答此问题。",
                found=False, chunks=chunks, refusal_reason=filter_reason,
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
            return RAGResult(
                question=question,
                answer=f"调用大模型失败：{e}",
                found=False, chunks=chunks, refusal_reason="LLM 调用异常",
            )

        # ④ 判定有/无答案
        found = not self._is_refusal(answer_text)

        return RAGResult(
            question=question,
            answer=answer_text,
            found=found,
            chunks=chunks,
            refusal_reason="" if found else "LLM 判定资料不足以回答",
        )


# ---------------------------------------------------------------- 自测

if __name__ == "__main__":
    print("RAGEngine 模块。请通过 main.py 使用。")
