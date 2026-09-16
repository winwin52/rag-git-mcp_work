# 学习进度 MCP Server

把「学习进度查询」和「C 语言课程检索」封装成 MCP 工具，供 Agent 调用。

---

## 三层关系（作业要求解释的重点）

```
┌──────────────────────────────────────────────────┐
│  ① 模型 LLM                                       │
│     决策者：决定要不要调工具、调哪个、传什么参数     │
│     它只看到工具的 name / description / 参数 schema │
└────────────────────┬─────────────────────────────┘
                     │ JSON-RPC（工具调用请求）
                     ▼
┌──────────────────────────────────────────────────┐
│  ② MCP 服务         mcp_server/server.py          │
│     传令兵：声明工具、校验参数、路由到业务函数、     │
│             把返回值序列化成结构化数据               │
│     ★ 不含任何业务逻辑                            │
└────────────────────┬─────────────────────────────┘
                     │ 普通 Python 函数调用
                     ▼
┌──────────────────────────────────────────────────┐
│  ③ 业务函数         mcp_server/business.py        │
│     执行者：读 data/progress.json、算进度、         │
│             检索 FAISS 索引                        │
│     ★ 不知道 MCP 存在，也不知道 LLM 存在           │
└──────────────────────────────────────────────────┘
```

### 为什么要这样分层？

| 好处 | 说明 |
|---|---|
| **解耦** | 换 LLM 不用改业务代码；换数据源不用改 MCP |
| **复用** | 同一个 MCP 能被 Cursor / Claude / DSH 共用 |
| **安全** | 参数校验放在服务层，不依赖 LLM「自觉」 |
| **可测** | 业务层能单独跑，不用起 MCP、不用调 LLM |

**验证方式**：`python -m mcp_server.business` 可以直接跑，
证明业务逻辑完全独立于 MCP 与 LLM。

---

## 提供的工具

| 工具 | 参数 | 作用 |
|---|---|---|
| `query_progress` | `course`（必填）、`chapter`（可选） | 查询课程/章节进度 |
| `list_courses` | 无 | 列出所有课程及总进度 |
| `get_next_task` | `course`（必填） | 下一个待完成任务 |
| `search_c_course` | `question`、`top_k` | 检索 C 语言课程讲义 |

> `search_c_course` 是**三个任务的交汇点**：
> 把 RAG 项目的检索能力封装成 MCP 工具，供 Agent 调用。

---

## 非法参数处理

**核心原则：永远返回结构化错误，绝不抛异常。**

因为抛异常会中断 Agent 循环，而返回结构化错误能让 **LLM 看到错误信息并自我修正**。

| 输入 | 返回 |
|---|---|
| `course=""` | `INVALID_COURSE` |
| `course=123` | `INVALID_COURSE` |
| `course="python"` | `COURSE_NOT_FOUND` + `available_courses` |
| `chapter="99"` | `CHAPTER_NOT_FOUND` + `available_chapters` |
| `top_k="abc"` | `INVALID_TOP_K` |
| `top_k=99` | `TOP_K_OUT_OF_RANGE` |

**注意 `hint` 字段和 `available_*` 字段** —— 这些是给 LLM 的线索，
让它知道"下一步该传什么"，比单纯报错有用得多。

---

## 数据源

`data/progress.json`（已被 gitignore，从示例复制）：

```bash
cp data/progress.example.json data/progress.json
```

**换成数据库只需改 `business.ProgressStore` 一个类**，
MCP 层和调用方完全不用动 —— 这就是分层的价值。

---

## 运行

### 1. 装依赖

```bash
pip install "mcp[cli]"
```

### 2. 先自测业务层（不需要 MCP、不需要 Key）

```bash
python -m mcp_server.business
```

### 3. 用 MCP Inspector 调试（推荐）

```bash
mcp dev mcp_server/server.py
```

会打开一个网页界面，可以手动调用每个工具、看返回值和 schema。

### 4. 配置到客户端

参考 `mcp.example.json`，把 `mcpServers` 整块合并进客户端配置。

**Windows 注意**：路径用正斜杠或双反斜杠。

---

## ⚠️ 开发 MCP 的两条铁律

### 1. 绝不用 `print()` 调试

**stdout 是 MCP 的协议通道。** 打印任何东西都会破坏 JSON-RPC 消息，
导致客户端报解析错误（而且错误信息通常很难懂）。

```python
# ❌ 错误
print("debug:", value)

# ✅ 正确
logging.info("debug: %s", value)      # 本项目已配置到 stderr
sys.stderr.write("debug\n")
```

### 2. docstring 就是给 LLM 的说明书

**LLM 唯一的判断依据就是工具的 name + description + 参数 schema。**

写得含糊，模型就会乱调或漏调：

```python
# ❌ 差：模型不知道该什么时候用
@mcp.tool()
def q(c): ...

# ✅ 好：说明用途、参数含义、返回值结构
@mcp.tool()
def query_progress(course: str, chapter: str = "") -> dict:
    """查询某门课程的学习进度。

    用于回答"我 RAG 学到哪了""第3章完成了没"这类问题。

    Args:
        course: 课程名，如 rag、git、mcp。必填。
        chapter: 章节名或编号。可选，留空返回整门课汇总。
    """
```

---

## 测试

```bash
python -m mcp_server.business    # 业务层自测（含非法参数用例）
mcp dev mcp_server/server.py     # 交互式调试
```
