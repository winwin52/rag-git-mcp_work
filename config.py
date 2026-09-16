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
    # BGE 中文模型建议给「查询」加指令前缀（文档不加）
    # v1.5 已弱化该要求，置空即可关闭
    query_instruction: str = ""

    # ---------- 分块 ----------
    chunk_size: int = 500          # 字符数（PPT 内容碎，比教程默认 4000 小）
    chunk_overlap: int = 80        # 重叠，减少边界语义丢失

    # ---------- 检索 ----------
    top_k: int = 3                 # 召回数量
    # L2 距离阈值：越小越相似。超过该值视为「不相关」
    # ⚠️ 需按你的实际数据实测校准，None 表示不启用阈值过滤
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
