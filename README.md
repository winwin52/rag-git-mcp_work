# C 语言课程 RAG 问答系统

基于 RAG（检索增强生成）技术，对《C语言程序设计与应用》课程讲义做智能问答，
**每条回答都附带检索依据**，资料不足时明确拒答。

本项目同时承载三个学习任务：

| 任务 | 在本项目中的体现 |
|---|---|
| **RAG** | 完整检索问答流程，带引用溯源、有/无答案判定、失败案例分析 |
| **Git** | 全程版本管理，含分支开发、合并、错误提交回退演示 |
| **MCP** | 把检索能力封装为 MCP 工具，供 Agent 调用（见 `mcp_server/`） |

---

## 素材

`data/c-course/` 下 5 个 PPTX（第 1~5 章），预处理后约 1.2 万字符。

---

## 快速开始

> **在 GitHub Codespaces 里运行？** 见 **[CODESPACES.md](CODESPACES.md)** —— 从零开始的完整指令。
> 一键搭建：`bash setup.sh`

### 1. 安装依赖

```bash
# ★ 先装 CPU 版 torch（避免拉入 4-6 GB 的 CUDA 包）
pip install torch --index-url https://download.pytorch.org/whl/cpu

# 再装其余
pip install -r requirements.txt
```

> 跳过第一步会导致 pip 拉入 CUDA 版 torch + 10 个 `nvidia-*` 包，
> 在 Codespaces 里足以撑爆磁盘（`Errno 28`）。
> 本项目用 `bge-small-zh`，**CPU 完全够用**。

### 2. 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

或直接设环境变量：

```bash
export DEEPSEEK_API_KEY=sk-你的密钥
```

### 3. 按顺序执行

```bash
python preprocess.py        # ① PPT → Markdown（一次性）
python build_index.py       # ② 建向量索引（一次性，会下载嵌入模型）
python main.py              # ③ 交互式问答
```

---

## 目录结构

```
rag-git-mcp_work/
├── config.py             # 配置中心（所有可调参数）
├── preprocess.py         # ① PPT → Markdown
├── build_index.py        # ② 分块 + 向量化 + FAISS 持久化
├── rag_engine.py         # 核心：检索 + 生成 + 有/无答案判定
├── main.py               # 交互式问答入口
├── eval.py               # 评测：有答案 / 无答案 / 失败案例
├── setup.sh              # ★ 一键环境搭建 + 建索引（Codespaces 用）
├── requirements.txt
├── CODESPACES.md         # ★ Codespaces 完整操作指南
├── DEVLOG.md             # 开发日志（过程记录）
├── .env.example          # 密钥示例（.env 已被 gitignore）
├── .gitignore
├── data/
│   └── c-course/         # 原始 PPT
├── data_processed/       # 预处理产出的 Markdown
├── vector_index/         # FAISS 索引（gitignore，可重建）
├── eval/
│   ├── failure_cases.md  # ★ 失败案例分析（作业交付物）
│   └── last_run.json     # 最近一次评测结果
└── mcp_server/           # MCP 封装（任务 3）
    ├── business.py       # 业务层（不依赖 MCP / LLM，可独立测试）
    ├── server.py         # MCP 服务层（工具声明 + 参数校验）
    ├── mcp.example.json  # 客户端配置模板
    └── README.md         # 三层关系说明
```

---

## 工作流程

```
【离线 · 跑一次】
  PPTX ──preprocess.py──> Markdown ──build_index.py──> FAISS 索引
                                        │
【在线 · 每次提问】                      │ 加载（秒级）
  问题 ──向量化──> 检索 top-k ──────────┘
                    ↓
              片段 + 元数据（来源/章节）
                    ↓
              拼 context + Prompt 约束
                    ↓
                  LLM 生成
                    ↓
         回答 + 依据（有答案）
         拒答 + 展示片段（无答案）
```

**关键认知**：向量只负责「找」，原文负责「答」。
检索返回的已经是 `Document` 对象（含原文和元数据），LLM 全程只看到文本。

---

## 有答案 vs 无答案

系统对两种情况都有明确输出：

**有答案**
```
【回答】指针和数组的主要区别是...
【依据】检索到 3 个相关片段：
  [1] 第4章.md / 第4章 / 块#12 （距离 0.4213）
      指针是一个变量...
```

**无答案**
```
【回答】抱歉，我无法从提供的资料中找到相关信息来回答此问题。
（判定原因：LLM 判定资料不足以回答）
【检索到的片段】共 3 个，但均与问题不相关：
  [1] 第5章.md / 第5章 / 块#40 （距离 1.2831）
      ...
```

**为什么无答案时还要展示片段？** 为了**自证清白** ——
让用户看到"我确实检索了，但这些东西跟问题无关，所以我不编"。

### 判定机制（四层）

| 层 | 机制 | 说明 |
|---|---|---|
| ① | 相似度阈值 | `config.score_threshold`，需按实际数据校准 |
| ② | **Prompt 约束** | 让 LLM 自己判断资料够不够（最实用） |
| ③ | 程序化检测 | 匹配 `config.refusal_markers` 中的拒答话术 |
| ④ | 统一输出 | 无论有/无答案都展示检索片段 |

---

## 评测

```bash
python eval.py                  # 完整测试（需 API Key）
python eval.py --retrieval-only # 只测检索层（不需要 Key）
python eval.py --case 10        # 单跑某个用例
```

内置 12 个用例：6 个有答案、3 个无答案、3 个边界/刁难。
结果存到 `eval/last_run.json`，据此填写 `eval/failure_cases.md`。

---

## MCP 工具（任务 3）

把检索能力和学习进度封装成 MCP，供 Agent 调用：

```bash
pip install "mcp[cli]"

cp data/progress.example.json data/progress.json   # 进度数据

python -m mcp_server.business      # 业务层自测（不需要 MCP / Key）
mcp dev mcp_server/server.py       # MCP Inspector 交互调试
```

配置到客户端参考 `mcp_server/mcp.example.json`。

**三层关系**：LLM（决策者）→ MCP 服务（传令兵）→ 业务函数（执行者）
详见 `mcp_server/README.md`。

---

## 调参指南

所有参数在 `config.py`：

| 参数 | 作用 | 调大 | 调小 |
|---|---|---|---|
| `chunk_size` | 分块大小 | 上下文更完整，检索精度下降 | 检索更精确，上下文易断裂 |
| `chunk_overlap` | 块间重叠 | 减少边界丢失，索引变大 | 反之 |
| `top_k` | 召回数量 | 召回率高，噪音多 | 精准，可能漏掉 |
| `score_threshold` | 相似度阈值 | 更宽容，易幻觉 | 更严格，易假阴性 |

> ⚠️ **改了 `embedding_model` / `chunk_size` / `chunk_overlap` 必须重建索引**：
> ```bash
> python build_index.py --force
> ```

---

## 常见问题

**Q: 报错「未找到 API Key」**
A: 建 `.env` 文件，或 `export DEEPSEEK_API_KEY=sk-xxx`。

**Q: 报错「索引不存在」**
A: 按顺序先跑 `preprocess.py` 再跑 `build_index.py`。

**Q: 首次建索引很慢**
A: 在下载嵌入模型（几百 MB）。可设镜像加速：
```bash
export HF_ENDPOINT=https://hf-mirror.com
```

**Q: 换了嵌入模型后检索结果全是垃圾**
A: 索引没重建。旧索引是旧模型语义空间的坐标，与新模型不可比。
```bash
python build_index.py --force
```

---

## 许可证

仅用于学习目的。课程讲义版权归原作者所有。
