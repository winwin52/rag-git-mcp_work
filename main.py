"""
交互式问答入口

用法：
    python main.py              # 交互式
    python main.py -q "函数的定义是什么？"   # 单次提问
"""

import argparse
import sys

from config import DEFAULT_CONFIG
from rag_engine import RAGEngine


BANNER = """
╔══════════════════════════════════════════════════════════╗
║        C 语言课程 RAG 问答系统                            ║
║        输入问题开始，输入 q / quit / 退出 结束              ║
╚══════════════════════════════════════════════════════════╝
"""

EXIT_WORDS = {"q", "quit", "exit", "退出"}


def build_engine():
    """初始化引擎（加载索引）"""
    print("正在加载索引……")
    engine = RAGEngine(DEFAULT_CONFIG)
    try:
        engine.load()
    except FileNotFoundError as e:
        print(f"\n[错误] {e}")
        print("\n请先按顺序执行：")
        print("  1. python preprocess.py       # PPT → Markdown")
        print("  2. python build_index.py      # 建向量索引")
        return None
    print("索引加载完成。\n")
    return engine


def main():
    parser = argparse.ArgumentParser(description="C 语言课程 RAG 问答")
    parser.add_argument("-q", "--question", help="单次提问后退出")
    parser.add_argument("-k", "--top-k", type=int, default=None,
                        help="检索片段数量（覆盖配置）")
    args = parser.parse_args()

    engine = build_engine()
    if engine is None:
        return 1

    # 单次提问模式
    if args.question:
        result = engine.ask(args.question, k=args.top_k)
        print(result.format())
        return 0

    # 交互模式
    print(BANNER)
    while True:
        try:
            question = input("请输入问题 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break

        if not question:
            continue
        if question.lower() in EXIT_WORDS:
            print("再见。")
            break

        try:
            result = engine.ask(question, k=args.top_k)
        except Exception as e:
            print(f"\n[出错] {e}\n")
            continue

        print()
        print(result.format())

    return 0


if __name__ == "__main__":
    sys.exit(main())
