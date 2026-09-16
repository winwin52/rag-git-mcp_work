"""
业务逻辑层 —— 与 MCP 完全解耦

这一层只干一件事：把「学习进度数据」读出来，按条件筛选。
它不知道 MCP 的存在，也不知道 LLM 的存在，可以独立单元测试。

三层职责划分（作业要求解释的关系）：
    模型 LLM    → 决策者：决定调哪个工具、传什么参数
    MCP 服务    → 传令兵：协议层，校验参数、路由到业务函数、返回结构化结果
    业务函数    → 执行者：真正读数据、算进度（本文件）

为什么这样分层？
    · 解耦   —— 换 LLM 不用改业务代码；换数据源不用改 MCP
    · 复用   —— 同一个 MCP 能被 Cursor / Claude / DSH 共用
    · 安全   —— 校验放在服务层，不依赖 LLM「自觉」
    · 可测   —— 本文件能单独跑 unittest，不用起 MCP、不用调 LLM
"""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ================================================================
#  数据源
# ================================================================

DEFAULT_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "progress.json"


class ProgressStore:
    """
    学习进度数据仓库。

    当前用 JSON 文件实现。若要换成 SQLite / 数据库，
    只需改这个类，MCP 层和上层的调用代码完全不用动
    —— 这就是分层的好处。
    """

    def __init__(self, data_file: Optional[Path] = None):
        self.data_file = Path(data_file) if data_file else DEFAULT_DATA_FILE

    def load(self) -> Dict[str, Any]:
        """读取全部数据"""
        if not self.data_file.exists():
            raise FileNotFoundError(
                f"进度数据文件不存在：{self.data_file}\n"
                f"请创建该文件（参考 data/progress.example.json）"
            )
        with self.data_file.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_courses(self) -> List[str]:
        """所有课程名"""
        data = self.load()
        return [c["course"] for c in data.get("courses", [])]

    def get_course(self, course: str) -> Optional[Dict[str, Any]]:
        """按课程名取数据（大小写不敏感、支持中英文别名）"""
        data = self.load()
        key = course.strip().lower()
        for c in data.get("courses", []):
            names = [c["course"].lower()] + [a.lower() for a in c.get("aliases", [])]
            if key in names:
                return c
        return None


_store = ProgressStore()


# ================================================================
#  业务函数
#
#  约定：永远返回结构化 dict，绝不抛异常给上层。
#       错误也作为数据返回，这样 LLM 能看到错误信息并自我修正。
# ================================================================

def _err(code: str, message: str, **extra) -> Dict[str, Any]:
    """统一的错误返回格式"""
    out = {"ok": False, "error_code": code, "message": message}
    out.update(extra)
    return out


def _ok(**payload) -> Dict[str, Any]:
    out = {"ok": True}
    out.update(payload)
    return out


# ---------------------------------------------------------------- 工具 1

def query_progress(course: str, chapter: Optional[str] = None) -> Dict[str, Any]:
    """
    查询某门课程（或某章）的学习进度。

    Args:
        course:  课程名，如 "rag"、"git"、"mcp"、"C语言"。必填。
        chapter: 章节名或编号，如 "1"、"第三章"。可选；不传则返回整门课程汇总。

    Returns:
        成功：
            {
              "ok": True,
              "course": "rag",
              "title": "检索增强生成",
              "overall_percent": 85.0,
              "total_chapters": 10,
              "completed_chapters": 8,
              "chapters": [ {name, status, percent, updated_at}, ... ]
            }
        失败：
            {"ok": False, "error_code": "...", "message": "...", "hint": "..."}
    """
    # ---------- 参数校验 ----------
    if not isinstance(course, str) or not course.strip():
        return _err(
            "INVALID_COURSE",
            "course 参数必须是非空字符串",
            hint="例如 course='rag'。可用课程见 list_courses()",
        )

    if chapter is not None and not isinstance(chapter, (str, int)):
        return _err(
            "INVALID_CHAPTER",
            "chapter 参数必须是字符串或整数（可选）",
            hint="例如 chapter='3' 或 chapter=3；不传则返回整门课汇总",
        )

    # ---------- 业务逻辑 ----------
    try:
        data = _store.get_course(course)
    except FileNotFoundError as e:
        return _err("DATA_UNAVAILABLE", str(e))

    if data is None:
        available = _store.list_courses()
        return _err(
            "COURSE_NOT_FOUND",
            f"未找到课程 '{course}'",
            available_courses=available,
            hint=f"可用课程：{', '.join(available)}",
        )

    chapters = data.get("chapters", [])
    total = len(chapters)
    done = sum(1 for c in chapters if c.get("status") == "completed")
    percent = round(done / total * 100, 1) if total else 0.0

    result = _ok(
        course=data["course"],
        title=data.get("title", ""),
        overall_percent=percent,
        total_chapters=total,
        completed_chapters=done,
    )

    # 指定章节 → 只返回该章
    if chapter is not None:
        target = str(chapter).strip()
        matched = [
            c for c in chapters
            if target in (str(c.get("index", "")), c.get("name", ""))
            or target in c.get("name", "")
        ]
        if not matched:
            return _err(
                "CHAPTER_NOT_FOUND",
                f"课程 '{data['course']}' 中未找到章节 '{chapter}'",
                available_chapters=[c.get("name") for c in chapters],
                hint="请用 available_chapters 中的名称",
            )
        result["chapters"] = matched
        result["returned"] = len(matched)
    else:
        result["chapters"] = [
            {
                "index": c.get("index"),
                "name": c.get("name"),
                "status": c.get("status"),
                "percent": c.get("percent", 0),
                "updated_at": c.get("updated_at"),
                "note": c.get("note", ""),
            }
            for c in chapters
        ]
        result["returned"] = total

    return result


# ---------------------------------------------------------------- 工具 2

def list_courses() -> Dict[str, Any]:
    """
    列出所有可查询的课程及总进度。

    Returns:
        {"ok": True, "count": 3, "courses": [{course, title, overall_percent}, ...]}
    """
    try:
        data = _store.load()
    except FileNotFoundError as e:
        return _err("DATA_UNAVAILABLE", str(e))

    out = []
    for c in data.get("courses", []):
        chapters = c.get("chapters", [])
        total = len(chapters)
        done = sum(1 for ch in chapters if ch.get("status") == "completed")
        out.append({
            "course": c["course"],
            "title": c.get("title", ""),
            "overall_percent": round(done / total * 100, 1) if total else 0.0,
            "total_chapters": total,
            "completed_chapters": done,
        })

    return _ok(count=len(out), courses=out)


# ---------------------------------------------------------------- 工具 3

def get_next_task(course: str) -> Dict[str, Any]:
    """
    获取某门课程下一个待完成的任务（第一个未完成的章节）。

    Args:
        course: 课程名，必填。

    Returns:
        成功：
            {"ok": True, "course": "rag", "next": {index, name, note},
             "remaining": 2}
        全部完成：
            {"ok": True, "course": "rag", "next": None,
             "message": "该课程已全部完成"}
    """
    if not isinstance(course, str) or not course.strip():
        return _err("INVALID_COURSE", "course 参数必须是非空字符串")

    try:
        data = _store.get_course(course)
    except FileNotFoundError as e:
        return _err("DATA_UNAVAILABLE", str(e))

    if data is None:
        return _err(
            "COURSE_NOT_FOUND",
            f"未找到课程 '{course}'",
            available_courses=_store.list_courses(),
        )

    chapters = data.get("chapters", [])
    pending = [c for c in chapters if c.get("status") != "completed"]

    if not pending:
        return _ok(
            course=data["course"],
            next=None,
            message="该课程已全部完成 🎉",
            remaining=0,
        )

    nxt = pending[0]
    return _ok(
        course=data["course"],
        next={
            "index": nxt.get("index"),
            "name": nxt.get("name"),
            "note": nxt.get("note", ""),
            "status": nxt.get("status"),
        },
        remaining=len(pending),
    )


# ================================================================
#  单元测试（证明业务层可独立测试 —— 这是分层的价值之一）
# ================================================================

if __name__ == "__main__":
    import sys

    print("=" * 66)
    print("  业务层自测（无需 MCP、无需 LLM）")
    print("=" * 66)

    cases = [
        ("列出课程", lambda: list_courses()),
        ("查 rag 进度", lambda: query_progress("rag")),
        ("查 rag 第3章", lambda: query_progress("rag", "3")),
        ("查 C语言（别名）", lambda: query_progress("c语言")),
        ("查下一任务", lambda: get_next_task("mcp")),
        ("★ 空参数", lambda: query_progress("")),
        ("★ 不存在的课程", lambda: query_progress("python")),
        ("★ 不存在的章节", lambda: query_progress("rag", "99")),
        ("★ 参数类型错误", lambda: query_progress(123)),
        ("★ 错误类型 chapter", lambda: query_progress("rag", ["1"])),
    ]

    for name, fn in cases:
        print(f"\n[{name}]")
        try:
            result = fn()
            print(json.dumps(result, ensure_ascii=False, indent=2)[:500])
        except Exception as e:
            print(f"  ❌ 业务层抛出了异常（不应该）：{type(e).__name__}: {e}")
            sys.exit(1)

    print("\n" + "=" * 66)
    print("  自测完成：所有非法输入都返回了结构化错误，未抛异常")
    print("=" * 66)
