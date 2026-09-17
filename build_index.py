"""
建索引：Markdown → 分块 → 向量化 → FAISS 持久化

离线阶段，只需跑一次。之后 main.py 直接加载索引即可。

关键点：
  1. 分块时保留「来源」元数据 —— 这是回答「依据」的基础
  2. 用同一个嵌入模型编码（换模型必须重建）
  3. 存成文件，避免每次重复编码

用法：
    python build_index.py           # 建索引（已存在则提示）
    python build_index.py --force   # 强制重建
    python build_index.py --stats   # 只看现有索引信息
"""

import argparse
import shutil
import sys
from pathlib import Path

from config import DEFAULT_CONFIG


# ---------------------------------------------------------------- 嵌入模型

def get_embeddings(cfg):
    """
    加载嵌入模型。

    ⚠️ 换模型 = 必须重建索引。
       旧索引是旧模型语义空间里的坐标，与新模型不可比。
    """
    from langchain_huggingface import HuggingFaceEmbeddings

    print(f"加载嵌入模型：{cfg.embedding_model}（首次会下载，请耐心等待）")
    return HuggingFaceEmbeddings(
        model_name=cfg.embedding_model,
        model_kwargs={"device": cfg.embedding_device},
        encode_kwargs={"normalize_embeddings": True},  # 归一化 → 余弦≡内积
    )


# ---------------------------------------------------------------- 加载与分块

def load_documents(cfg):
    """读取 data_processed 下所有 Markdown"""
    from langchain_community.document_loaders import TextLoader

    processed = Path(cfg.processed_dir)
    if not processed.exists():
        raise FileNotFoundError(
            f"未找到预处理目录：{processed}\n"
            f"请先运行：python preprocess.py"
        )

    md_files = sorted(processed.glob("*.md"))
    if not md_files:
        raise FileNotFoundError(
            f"{processed} 下没有 .md 文件，请先运行 python preprocess.py"
        )

    docs = []
    for f in md_files:
        loaded = TextLoader(str(f), encoding="utf-8").load()
        for d in loaded:
            # 补上来源元数据 —— 检索结果要靠它标注「依据」
            d.metadata["source"] = f.name
            d.metadata["chapter"] = _extract_chapter(f.name)
        docs.extend(loaded)

    print(f"加载 {len(md_files)} 个文档，共 {len(docs)} 篇")
    return docs


def _extract_chapter(filename: str) -> str:
    """从文件名提取章节号，如 '第4章'"""
    import re
    m = re.search(r"第\s*(\d+)\s*章", filename)
    return f"第{m.group(1)}章" if m else "未知章节"


def split_documents(cfg, docs):
    """按字符递归分块"""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=cfg.chunk_size,
        chunk_overlap=cfg.chunk_overlap,
        # 中文场景补上中文标点作为分隔符，切得更自然
        separators=["\n## ", "\n### ", "\n\n", "\n", "。", "；", "，", " ", ""],
        keep_separator=True,
    )
    chunks = splitter.split_documents(docs)

    # 过滤「文档头万能块」
    chunks = filter_header_chunks(chunks)

    # 给每个块编号，便于调试与引用
    for i, c in enumerate(chunks):
        c.metadata["chunk_id"] = i

    print(f"分块完成：{len(docs)} 篇 → {len(chunks)} 个块 "
          f"(chunk_size={cfg.chunk_size}, overlap={cfg.chunk_overlap})")

    if chunks:
        lens = [len(c.page_content) for c in chunks]
        print(f"块长度：最小 {min(lens)}，最大 {max(lens)}，"
              f"平均 {sum(lens)//len(lens)} 字符")

    return chunks


def filter_header_chunks(chunks):
    """
    过滤「低信息量的模板化块」。

    问题背景：
        5 份讲义是同一门课的系列 PPT，存在两类跨章节重复的模板化内容。
        它们的向量高度相似、且几乎不含知识点，会抱团霸占检索排名，
        把真正含答案的块挤出去。

    类型一：文档头万能块
        每个文档的第 0 块总是「文件名 + source 注释 + 封面页 + 目录」。
        实测：问「一天有多少秒」，top-3 全是各章文档头，
        而含 86400 的那一页根本没被召回。

    类型二：本章任务块（v2 新增）
        每章都有「4.本章任务 任务1：2020年总共有366天…」这一页，
        5 章内容几乎逐字相同。
        实测：问「C语言是什么」，top-4 被 4 个不同章节的
        本章任务块占满（距离 0.7771 / 0.7782 / 0.7816 / 0.7831），
        它们互相"抱团"挤掉了真正相关的块。

    过滤规则（满足任一即丢弃）：
        1. 含 source 注释、且几乎没有实质内容（短）
        2. 封面页特征明显（含邮箱/讲解/编制等署名信息）
        3. 章节任务页（编号小标题 + 重复的任务模板句）

    注意：
        · 只过滤，不修改原文。data_processed/ 下仍保留完整 Markdown。
        · 习题页（5.本章习题）**不过滤** —— 它含知识点问句
          （如「为什么要使用函数？」），有检索价值。
    """
    import re

    # 封面/署名的典型特征
    COVER_PATTERNS = [
        r"<!--\s*source:",
        r"@\w+\.(com|cn|net|org)",
        r"讲解[:：]", r"编制[:：]",
        r"——.*系列——",
    ]
    cover_re = re.compile("|".join(COVER_PATTERNS))

    # 章节任务页特征（跨章节重复的模板内容）
    TASK_PATTERNS = [
        r"###\s*\d+\.\s*本章任务",          # 编号小标题「4.本章任务」
        r"本章任务\s*任务\d",                # 正文「本章任务 任务1」
        r"任务1[:：]\s*2020年总共有366天",   # 逐字重复的模板句
    ]
    task_re = re.compile("|".join(TASK_PATTERNS))

    kept, dropped = [], []
    for c in chunks:
        text = c.page_content.strip()

        # 规则 1：短块 + 含 source 注释 → 文档头
        if len(text) < 200 and "<!-- source:" in text:
            dropped.append(("文档头", text[:40]))
            continue

        # 规则 2：封面特征密集（命中 2 个以上）
        if len(cover_re.findall(text)) >= 2 and len(text) < 300:
            dropped.append(("封面页", text[:40]))
            continue

        # 规则 3：章节任务页
        if task_re.search(text):
            dropped.append(("任务页", text[:40]))
            continue

        kept.append(c)

    if dropped:
        # 按类型统计
        from collections import Counter
        counts = Counter(t for t, _ in dropped)
        detail = "、".join(f"{k} {v} 个" for k, v in counts.items())
        print(f"过滤低信息量块：丢弃 {len(dropped)} 个（{detail}），"
              f"保留 {len(kept)} 个")
        for typ, d in dropped[:6]:
            print(f"    - [{typ}] {d}...")
        if len(dropped) > 6:
            print(f"    - 其余 {len(dropped) - 6} 个省略")

    return kept


# ---------------------------------------------------------------- 建索引

def build_index(cfg, force: bool = False):
    """完整建索引流程"""
    from langchain_community.vectorstores import FAISS

    index_dir = Path(cfg.index_dir)

    if index_dir.exists() and any(index_dir.iterdir()) and not force:
        print(f"索引已存在：{index_dir}")
        print("如需重建，请加 --force")
        return None

    if force and index_dir.exists():
        print(f"清除旧索引：{index_dir}")
        shutil.rmtree(index_dir)

    cfg.ensure_dirs()

    docs = load_documents(cfg)
    chunks = split_documents(cfg, docs)
    embeddings = get_embeddings(cfg)

    print("正在向量化并构建 FAISS 索引……")
    vectorstore = FAISS.from_documents(chunks, embeddings)

    vectorstore.save_local(str(index_dir))

    # 记录建索引时用的模型，防止「换了模型忘了重建」
    meta_file = index_dir / "BUILD_INFO.txt"
    meta_file.write_text(
        f"embedding_model = {cfg.embedding_model}\n"
        f"chunk_size = {cfg.chunk_size}\n"
        f"chunk_overlap = {cfg.chunk_overlap}\n"
        f"num_chunks = {len(chunks)}\n"
        f"num_docs = {len(docs)}\n",
        encoding="utf-8",
    )

    print(f"\n索引已保存：{index_dir}")
    print(f"（{len(chunks)} 个块，模型 {cfg.embedding_model}）")
    return vectorstore


def load_index(cfg):
    """
    加载已有索引。main.py / eval.py 用这个。
    """
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings

    index_dir = Path(cfg.index_dir)
    if not index_dir.exists():
        raise FileNotFoundError(
            f"索引不存在：{index_dir}\n请先运行：python build_index.py"
        )

    # 一致性检查：模型换了但索引没重建，是最隐蔽的坑
    info = index_dir / "BUILD_INFO.txt"
    if info.exists():
        recorded = info.read_text(encoding="utf-8")
        if cfg.embedding_model not in recorded:
            print("=" * 60)
            print("⚠️  警告：索引是用别的嵌入模型建的！")
            print(f"    当前配置：{cfg.embedding_model}")
            for line in recorded.splitlines():
                if line.startswith("embedding_model"):
                    print(f"    索引记录：{line.split('=', 1)[1].strip()}")
            print("    两个语义空间不可比，检索结果会失效。")
            print("    请运行：python build_index.py --force")
            print("=" * 60)

    embeddings = HuggingFaceEmbeddings(
        model_name=cfg.embedding_model,
        model_kwargs={"device": cfg.embedding_device},
        encode_kwargs={"normalize_embeddings": True},
    )
    return FAISS.load_local(
        str(index_dir),
        embeddings,
        allow_dangerous_deserialization=True,  # 本地自建索引，可信
    )


def show_stats(cfg):
    """展示现有索引信息"""
    index_dir = Path(cfg.index_dir)
    if not index_dir.exists():
        print(f"索引不存在：{index_dir}")
        return
    info = index_dir / "BUILD_INFO.txt"
    print(f"索引目录：{index_dir}")
    if info.exists():
        print(info.read_text(encoding="utf-8"))
    else:
        print("(无 BUILD_INFO.txt)")
    for f in sorted(index_dir.iterdir()):
        print(f"  {f.name:30} {f.stat().st_size:>10,} bytes")


def main():
    parser = argparse.ArgumentParser(description="构建 FAISS 向量索引")
    parser.add_argument("--force", action="store_true", help="强制重建")
    parser.add_argument("--stats", action="store_true", help="只看索引信息")
    args = parser.parse_args()

    cfg = DEFAULT_CONFIG

    if args.stats:
        show_stats(cfg)
        return 0

    try:
        build_index(cfg, force=args.force)
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        return 1
    except ImportError as e:
        print(f"[错误] 缺少依赖：{e}")
        print("请先安装：pip install -r requirements.txt")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
