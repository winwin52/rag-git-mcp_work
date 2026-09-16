"""
MCP 服务层 —— 把业务能力暴露给 Agent

这一层只做三件事：
    1. 声明工具（名称、参数、docstring）—— 供 LLM 理解
    2. 校验与路由 —— 调用 business.py 的函数
    3. 返回结构化结果

它不含业务逻辑，也不直接碰数据源。

⚠️ 关键约束：MCP 用 stdout 传协议，绝不能 print() 调试！
   要输出日志请用 sys.stderr 或 logging（本项目用 logging 到 stderr）。

运行：
    python mcp_server/server.py          # stdio 模式（给客户端启动）
"""

import logging
import sys
from pathlib import Path

# 让 `python mcp_server/server.py` 也能 import 到项目根的模块
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

from mcp_server import business

# ★ 日志必须走 stderr —— stdout 是 MCP 协议通道
logging.basicConfig(
    level=logging.INFO,
    stream=sys.stderr,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("learning-progress-mcp")

mcp = FastMCP("learning-progress")


# ================================================================
#  工具 1：查询学习进度
# ================================================================

@mcp.tool()
def query_progress(course: str, chapter: str = "") -> dict:
    """查询某门课程的学习进度。

    用于回答"我 RAG 学到哪了""第3章完成了没"这类问题。

    Args:
        course: 课程名，如 rag、git、mcp、C语言。必填。
        chapter: 章节名或编号（如 "3" 或 "第三章"）。可选，留空则返回整门课汇总。

    Returns:
        含 ok 字段的结果字典。
        成功时包含 overall_percent、chapters 等；
        失败时包含 error_code 和 message。
    """
    result = business.query_progress(course, chapter or None)
    if not result.get("ok"):
        logger.warning("query_progress 失败: %s", result.get("error_code"))
    return result


# ================================================================
#  工具 2：列出所有课程
# ================================================================

@mcp.tool()
def list_courses() -> dict:
    """列出所有可查询的课程及其总进度。

    在不确定课程名时先调用它。

    Returns:
        {"ok": True, "count": N, "courses": [...]}
    """
    return business.list_courses()


# ================================================================
#  工具 3：下一个待完成任务
# ================================================================

@mcp.tool()
def get_next_task(course: str) -> dict:
    """获取某门课程下一个待完成的任务。

    用于回答"我下一步该学什么"。

    Args:
        course: 课程名，如 rag、git、mcp。必填。

    Returns:
        成功时 next 为待完成章节信息；全部完成时 next 为 None。
    """
    result = business.get_next_task(course)
    if not result.get("ok"):
        logger.warning("get_next_task 失败: %s", result.get("error_code"))
    return result


# ================================================================
#  工具 4：检索 C 语言课程知识库（把任务 1 的 RAG 暴露出来）
#
#  这个工具是三个任务的交汇点：
#      RAG 项目的检索能力 → 封装成 MCP 工具 → 供 Agent 调用
# ================================================================

@mcp.tool()
def search_c_course(question: str, top_k: int = 3) -> dict:
    """检索 C 语言课程讲义，返回相关片段及其出处。

    用于回答关于《C语言程序设计与应用》课程内容的问题。
    注意：本工具只返回检索到的原文片段，不生成答案。
    若片段为空或明显不相关，应如实告知资料中没有相关内容。

    Args:
        question: 要检索的问题，如"函数的定义格式是什么"。
        top_k: 返回片段数量，默认 3，范围 1~10。

    Returns:
        {"ok": True, "question": ..., "chunks": [{content, source, chapter, score}],
         "found": bool}
        出错时返回 {"ok": False, "error_code": ..., "message": ...}
    """
    # ---------- 参数校验 ----------
    if not isinstance(question, str) or not question.strip():
        return {
            "ok": False,
            "error_code": "INVALID_QUESTION",
            "message": "question 参数必须是非空字符串",
            "hint": "例如 question='函数的定义格式是什么'",
        }

    # LLM 可能传来字符串，容错处理
    try:
        k = int(top_k)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error_code": "INVALID_TOP_K",
            "message": f"top_k 必须是整数，收到 {top_k!r}",
            "hint": "例如 top_k=3",
        }

    if not 1 <= k <= 10:
        return {
            "ok": False,
            "error_code": "TOP_K_OUT_OF_RANGE",
            "message": f"top_k 必须在 1~10 之间，收到 {k}",
        }

    # ---------- 业务：检索 ----------
    try:
        from config import DEFAULT_CONFIG
        from rag_engine import RAGEngine

        engine = _get_engine(DEFAULT_CONFIG)
        chunks = engine.retrieve(question, k=k)

        payload = [
            {
                "content": c.content,
                "source": c.source,
                "chapter": c.chapter,
                "score": round(c.score, 4) if c.score is not None else None,
            }
            for c in chunks
        ]

        return {
            "ok": True,
            "question": question,
            "found": len(payload) > 0,
            "count": len(payload),
            "chunks": payload,
            "note": "以上为检索到的原始片段，请据此判断是否足以回答问题。",
        }
    except FileNotFoundError as e:
        return {
            "ok": False,
            "error_code": "INDEX_NOT_BUILT",
            "message": str(e),
            "hint": "请先运行 python build_index.py 构建索引",
        }
    except Exception as e:
        logger.exception("search_c_course 异常")
        return {
            "ok": False,
            "error_code": "RETRIEVAL_FAILED",
            "message": f"检索失败：{type(e).__name__}: {e}",
        }


# 引擎单例：避免每次调用都重新加载索引
_engine_cache = {}


def _get_engine(cfg):
    """懒加载并缓存 RAG 引擎"""
    if "engine" not in _engine_cache:
        from rag_engine import RAGEngine
        logger.info("首次调用，加载 RAG 索引……")
        engine = RAGEngine(cfg)
        engine.load()
        _engine_cache["engine"] = engine
        logger.info("索引加载完成")
    return _engine_cache["engine"]


# ================================================================
#  入口
# ================================================================

if __name__ == "__main__":
    logger.info("启动 learning-progress MCP Server（stdio 模式）")
    mcp.run()
