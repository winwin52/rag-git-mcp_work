"""
评测脚本 —— 你作业的核心交付物之一

作业要求：
  · 能测试有答案的问题
  · 能测试无答案的问题
  · 定位至少一个失败案例

用法：
    python eval.py                  # 跑全部用例
    python eval.py --retrieval-only # 只测检索（不需要 API Key）
    python eval.py --case 3         # 只跑第 3 个用例
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from config import DEFAULT_CONFIG
from rag_engine import RAGEngine


# ================================================================
#  测试用例
#  expect_found: 期望能否从资料中找到答案
# ================================================================

TEST_CASES = [
    # ---------- 有答案 ----------
    {
        "id": 1,
        "question": "为什么要使用函数？",
        "expect_found": True,
        "note": "第4章 2.1 节有明确讲解",
    },
    {
        "id": 2,
        "question": "函数的定义格式是什么样的？",
        "expect_found": True,
        "note": "第4章 2.2 节有完整格式说明",
    },
    {
        "id": 3,
        "question": "一天总共有多少秒？",
        "expect_found": True,
        "note": "第2章第3页明确写了 86400 秒",
    },
    {
        "id": 4,
        "question": "秒值的取值范围是多少？",
        "expect_found": True,
        "note": "第2/3/4章都提到 0~86399",
    },
    {
        "id": 5,
        "question": "什么是枚举？",
        "expect_found": True,
        "note": "第5章主题",
    },
    {
        "id": 6,
        "question": "数组和函数有什么关系？",
        "expect_found": True,
        "note": "跨章节：第3章数组 + 第4章函数",
    },

    # ---------- 无答案 ----------
    {
        "id": 7,
        "question": "Python 的装饰器怎么用？",
        "expect_found": False,
        "note": "资料是 C 语言，完全不涉及 Python",
    },
    {
        "id": 8,
        "question": "如何配置 MySQL 数据库连接池？",
        "expect_found": False,
        "note": "资料不涉及数据库",
    },
    {
        "id": 9,
        "question": "React 的 useEffect 依赖数组怎么写？",
        "expect_found": False,
        "note": "前端话题，资料无关",
    },
    {
        "id": 10,
        "question": "指针和数组的区别是什么？",
        "expect_found": None,   # ⚠️ 边界用例：资料可能部分涉及
        "note": "边界案例：资料是入门讲义，可能没讲指针",
    },

    # ---------- 故意刁难（暴露失败）----------
    {
        "id": 11,
        "question": "CalcHour 函数的完整实现代码是什么？",
        "expect_found": None,
        "note": "刁难：PPT 可能只给函数说明不给完整代码",
    },
    {
        "id": 12,
        "question": "第4章提到的三个函数分别叫什么名字？",
        "expect_found": True,
        "note": "刁难：需要跨页聚合信息",
    },
]


# ================================================================

def run_retrieval_only(engine, cases):
    """只测检索层，不需要 API Key —— 先看检索命中情况"""
    print("=" * 70)
    print("  检索层测试（不调用 LLM）")
    print("=" * 70)

    for case in cases:
        chunks = engine.retrieve(case["question"])
        print(f"\n[用例 {case['id']}] {case['question']}")
        print(f"  期望找到答案：{case['expect_found']}")
        print(f"  备注：{case['note']}")
        print(f"  检索到 {len(chunks)} 个片段：")
        for i, c in enumerate(chunks, 1):
            print(f"    [{i}] 距离={c.score:.4f}  {c.source[:30]} / {c.chapter}")
            print(f"        {c.brief(90)}")


def run_full(engine, cases, only=None):
    """完整测试：检索 + 生成 + 判定"""
    print("=" * 70)
    print("  完整 RAG 测试（检索 + 生成）")
    print("=" * 70)

    records = []
    passed = failed = 0

    for case in cases:
        if only is not None and case["id"] != only:
            continue

        result = engine.ask(case["question"])
        expect = case["expect_found"]

        if expect is None:
            verdict = "边界"
        elif result.found == expect:
            verdict = "✅ 通过"
            passed += 1
        else:
            verdict = "❌ 失败"
            failed += 1

        print(f"\n{'-' * 70}")
        print(f"[用例 {case['id']}] {verdict}")
        print(result.format())

        records.append({
            "id": case["id"],
            "question": case["question"],
            "expect_found": expect,
            "actual_found": result.found,
            "verdict": verdict,
            "note": case["note"],
            "answer": result.answer,
            "refusal_reason": result.refusal_reason,
            "chunks": [
                {"source": c.source, "chapter": c.chapter,
                 "score": c.score, "preview": c.brief(80)}
                for c in result.chunks
            ],
        })

    print("\n" + "=" * 70)
    print(f"  汇总：通过 {passed}，失败 {failed}")
    print("=" * 70)

    # 保存结果，便于写失败案例分析
    out_dir = Path(__file__).parent / "eval"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "last_run.json"
    out_file.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n结果已保存：{out_file}")
    print("请据此填写 eval/failure_cases.md 中的失败案例。")

    return records


def main():
    parser = argparse.ArgumentParser(description="RAG 评测")
    parser.add_argument("--retrieval-only", action="store_true",
                        help="只测检索层，不需要 API Key")
    parser.add_argument("--case", type=int, default=None,
                        help="只跑指定 id 的用例")
    args = parser.parse_args()

    engine = RAGEngine(DEFAULT_CONFIG)
    try:
        engine.load()
    except FileNotFoundError as e:
        print(f"[错误] {e}")
        print("请先运行：python preprocess.py && python build_index.py")
        return 1

    if args.retrieval_only:
        run_retrieval_only(engine, TEST_CASES)
    else:
        run_full(engine, TEST_CASES, only=args.case)

    return 0


if __name__ == "__main__":
    sys.exit(main())
