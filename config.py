"""
配置中心 —— 所有可调参数集中在这里，改参数不用动业务代码。

参考 all-in-rag C8 的 config.py 设计。
"""

import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict

# 项目根目录（本文件所在目录）
ROOT = Path(__file__).resolve().parent

# ============================================================
#  加载 .env
#
#  必须在读取任何环境变量之前执行。
#  否则 .env 文件里的密钥不会被 os.getenv() 读到，
#  用户每次开新终端都得手动 export，很容易忘。
# ============================================================
try:
    from dotenv import load_dotenv

    # override=False：已存在的环境变量优先，不覆盖
    #   —— 方便临时用 export 覆盖 .env 做调试
    load_dotenv(ROOT / ".env", override=False)
except ImportError:
    # python-dotenv 未安装时降级：只依赖系统环境变量
    pass


@dataclass
class RAGConfig:
    """RAG 系统配置"""

    # ---------- 路径 ----------
    # 原始素材（PPT）
    data_dir: str = str(ROOT / "data" / "c-course")
    # 预处理后的 Markdown
    processed_dir: str = str(ROOT / "data_processed")
    # 向量索引持久化位置
    index_dir: str = str(ROOT / "vector_index")

    # ---------- 嵌入模型 ----------
    # 教程同款，512 维，CPU 可跑
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"
    # BGE 中文模型的官方用法：给「查询」加指令前缀，文档不加。
    # 这是非对称检索的标准做法 —— 短查询 vs 长文档的问法不同，
    # 加前缀能让查询向量更贴近「找相关文档」的语义。
    query_instruction: str = "为这个句子生成表示以用于检索相关文章："

    # ---------- 分块 ----------
    # 字符数。500 会让相邻小节被塞进同一个块（实测「2.1 为什么要用函数」
    # 和「2.2 函数的定义」同块），削弱检索区分度，故调小到 300。
    chunk_size: int = 300
    chunk_overlap: int = 60        # 重叠，减少边界语义丢失

    # ---------- 检索 ----------
    top_k: int = 5                 # 召回数量（3 -> 5，提高召回率）
    # L2 距离阈值：越小越相似。超过该值视为「不相关」
    # ⚠️ 实测发现该指标在本文档上区分度很差：
    #    「有答案」的距离（1.14）反而大于「无答案」的距离（0.80），
    #    故保持 None（不启用）。改进方向见 eval/failure_cases.md
    score_threshold: float = None

    # ---------- 生成 ----------
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    temperature: float = 0.1       # 问答任务要确定性
    max_tokens: int = 1024

    # 拒答标记：LLM 说「不知道」时会包含这些词，用于程序化检测
    refusal_markers: tuple = (
        "无法从提供的资料",
        "无法根据提供的上下文",
        "没有相关信息",
        "资料中没有",
        "未找到相关",
        "无法回答",
    )

    # ---------- 方法 ----------
    def ensure_dirs(self) -> None:
        """确保输出目录存在"""
        for d in (self.processed_dir, self.index_dir):
            Path(d).mkdir(parents=True, exist_ok=True)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RAGConfig":
        return cls(**d)


DEFAULT_CONFIG = RAGConfig()


def get_api_key() -> str:
    """
    从环境变量读取 LLM API Key。

    ⚠️ 永远不要硬编码密钥 —— 一旦 push 到 GitHub 就等于泄露。
    """
    key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("MOONSHOT_API_KEY")
    if not key:
        raise ValueError(
            "未找到 API Key。请设置环境变量 DEEPSEEK_API_KEY，\n"
            "或在项目根目录创建 .env 文件（可复制 .env.example）。"
        )
    return key


if __name__ == "__main__":
    cfg = DEFAULT_CONFIG
    cfg.ensure_dirs()
    print("当前配置：")
    for k, v in cfg.to_dict().items():
        print(f"  {k:20} = {v}")
