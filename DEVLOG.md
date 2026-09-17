# 开发日志

> 记录开发过程：做了什么、为什么这么做、踩了什么坑、怎么解决的。
>
> **与 README 的分工：**
> - `README.md` —— 项目是什么、怎么用（面向使用者，稳定）
> - `DEVLOG.md` —— 我怎么做的、遇到什么问题（面向过程，持续增长）
> - `eval/failure_cases.md` —— 检索失败案例专项分析（作业要求）

---

## 2026-09-16 · 项目初始化

### 完成内容

搭建 RAG 项目骨架，共 9 个 Python 文件 + 配套文档。

**目录结构：**

```
rag-git-mcp_work/
├── config.py            配置中心
├── preprocess.py        ① PPT → Markdown
├── build_index.py       ② 分块 + 向量化 + FAISS
├── rag_engine.py        核心：检索 + 生成 + 有/无答案判定
├── main.py              交互式问答
├── eval.py              评测脚本
├── mcp_server/          MCP 封装
│   ├── business.py      业务层
│   └── server.py        服务层
├── data/c-course/       5 个 PPTX 原始素材
├── data_processed/      预处理产出的 Markdown
├── eval/failure_cases.md 失败案例分析模板
└── docs/
```

### 关键决策

**1. 为什么把配置抽到 `config.py`？**

参考 all-in-rag C8 的做法。调 `chunk_size`、`top_k` 不用改业务代码，
便于后续做失败案例的「改进 → 对比」实验。

**2. 为什么 `preprocess.py` 单独一步，不在建索引时顺手做？**

因为 PPT 抽取质量**决定了整个系统的上限**。
独立成一步，可以单独查看、人工校对中间产物，
出问题时能快速判断是「预处理丢内容」还是「分块切碎了」。

**3. 为什么 MCP 拆成 `business.py` + `server.py` 两层？**

作业要求「解释模型、MCP 服务和业务函数之间的关系」。
物理分离后，`python -m mcp_server.business` 能独立跑测试，
直接证明业务逻辑不依赖 MCP 和 LLM —— 这是分层价值最有力的证据。

**4. 为什么拒答用「四层机制」而不是单一阈值？**

绝对相似度阈值跨数据集不可移植（换一批资料就失效）。
所以主用 Prompt 约束（让 LLM 判断），阈值作为可选项默认关闭。

### 已完成验证

| 项目 | 结果 |
|---|---|
| PPT 预处理 | ✅ 5 个文件 → 11,884 字符 |
| 全部 Python 文件语法 | ✅ 9/9 通过 |
| 配置参数校验 | ✅ 通过 |
| MCP 业务层非法参数 | ✅ 8/8 通过，零异常抛出 |
| 别名/大小写容错 | ✅ 6/6 命中 |

**未验证**（缺环境依赖）：建索引、检索、LLM 生成。

### 踩过的坑

**坑 1：Codespaces 磁盘爆满**

在 GitHub Codespaces 装依赖时报：
```
ERROR: Could not install packages due to an OSError:
[Errno 28] No space left on device
```

**原因**：`torch` 默认装 CUDA 版，会带入 10 个 `nvidia-*` 包，占 4-6 GB。
Codespaces 免费版只有 32 GB，同时存在多个 conda 环境时必然爆盘。

**解决**：先装 CPU 版 torch，再装其余依赖：
```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```
CPU 版仅约 200 MB，省下 90% 空间。

**坑 2：Codespaces 拉不到 Docker 镜像**

尝试用 `docker compose up -d` 起 Milvus 时报：
```
Error pull access denied for minio/minio,
repository does not exist or may require 'docker login'
```

**原因**：Codespaces 网络访问 Docker Hub 受限。`minio/minio` 是热门官方镜像，
不可能不存在 —— 这是网络问题，不是配置问题。

**解决**：**改用 FAISS**。它是算法库不是数据库服务，不需要 Docker，
完美契合本项目（数据量小，几万个块以内 FAISS 完全够用）。
这也符合 all-in-rag 教程第三章的选择建议。

### 下一步

- [x] 在 Codespaces 安装依赖
- [x] 跑通 `build_index.py`，建索引
- [x] 跑 `eval.py --retrieval-only` 验证检索质量
- [x] 配 API Key，跑完整问答
- [x] 记录失败案例到 `eval/failure_cases.md`

### Codespaces 实操踩坑

**坑 3：`conda init c-rag` 参数写错**

```
CondaError: Run 'conda init' before 'conda activate'
$ conda init c-rag
conda init: error: argument SHELLS: invalid choice: 'c-rag'
```

**原因**：`conda init` 后面要跟 **shell 名**（bash/zsh/…），不是环境名。

**解决**：
```bash
conda init bash
source ~/.bashrc
conda activate c-rag
```

**坑 4：`.env` 配了却不生效**

现象：明明有 `.env` 文件，仍报「未找到 API Key」，每次都要手动 `export`。

**原因**：`config.py` 装了 `python-dotenv` 但**从未调用 `load_dotenv()`** —— 这是本项目的真实 bug，已在 v2 修复。

**坑 5：把 UUID 误当 API Key**

DeepSeek 的 Key 是 `sk-` 开头；UUID 格式（`32d8f90d-...`）通常是账号/组织 ID，
拿去调用会返回 `401 Authentication Fails`。

**教训**：报错信息本身就够定位问题（`401` = 认证失败，`404 model not found` = 模型名错），
**不需要把密钥贴出来**。

---

## 2026-09-17 · v2 检索质量改进（feature/retrieval-improve 分支）

### 背景

v1 跑通后发现三类真实问题，详见 `eval/failure_cases.md`：

1. **检索层**：文档头「万能块」霸榜，含答案的页面没被召回
2. **生成层**：有答案却拒答（Prompt 约束过紧 → 假阴性）
3. **评估层**：L2 距离指标完全无法区分有/无答案

### 完成内容（5 个 commit）

| commit | 类型 | 内容 |
|---|---|---|
| `dd8591c` | fix | 加载 `.env`，免去手动 export |
| `6614e72` | fix | 区分「LLM 调用失败」与「资料无答案」 |
| `0b6ce3d` | fix | 过滤文档头万能块 |
| `397fe01` | tune | 放宽 Prompt，缓解假阴性 |
| `434ea59` | tune | chunk_size 500→300、启用 BGE 查询前缀、top_k 3→5 |

### 关键决策

**1. 为什么把「调用失败」单独拎出来？**

原代码里，401 / 网络异常也走「无答案」分支，输出
「检索到的片段均与问题不相关」—— **把系统故障误报成知识库缺内容**，
严重误导排查方向。

新增 `outcome` 字段区分五种结局：
`answered` / `refused` / `error` / `filtered` / `empty`。
`error` 时明确提示「这不代表资料里没有答案」。

**2. 为什么用「过滤」而不是「调权重」处理文档头块？**

理论上可以给这类块降低权重，但：
- FAISS 的 `IndexFlatL2` 不支持按元数据调权
- 文档头块**本身没有检索价值**（就是标题+封面+目录），直接丢弃最干净

**3. 为什么放宽 Prompt 而不担心幻觉？**

两者是权衡关系：
- 约束太紧 → 假阴性（有答案说没有）← **当前的主要问题**
- 约束太松 → 幻觉（编造内容）

选择放宽，但**保留底线**：仍禁止编造，且要求**引用片段编号**，
方便人工核对出处。等于用「可追溯性」对冲「宽容度」。

**4. 为什么没启用 score_threshold？**

因为实测发现**该指标本身失效**（见失败案例 3）。
先验证指标的区分能力，再决定是否使用 —— 不能盲目设阈值。

### 验证结果（本地，模拟分块）

```
分块：74 个（chunk_size=300）
过滤后保留：64 个，丢弃 10 个（5 文档头 + 5 封面页）
过滤后仍含封面特征：0
含 '86400' 的答案块：1 个  ← ✅ 未被误删
```

### 待 Codespaces 实测确认

- [x] `build_index.py --force` 重建索引
- [x] `eval.py --retrieval-only` 与 `eval_baseline.txt` 对比
- [x] `main.py` 实际问答（重点看假阴性是否缓解）
- [ ] 若合格 → 合并回 master

### 实测结果（Codespaces）

**核心改进全部生效：**

| 指标 | 改进前 | 改进后 |
|---|---|---|
| 文档头霸榜 | 每个查询 top-1 | **0** |
| 「一天多少秒」 | 依据全是文档头，答案来自 LLM 自身知识 | **top-1 命中含 86400 的页**（距离 0.8722） |
| 「变量类型」 | 直接拒答 | **部分作答 + 标注未涵盖部分** |
| 引用片段编号 | 无 | **有**（新 Prompt 生效） |

**但新暴露一个问题**：见下。

### 新发现：跨章节重复块「抱团」（已修复）

问「C语言是什么」时，top-4 是 4 个不同章节的**同一个「本章任务」页**：

```
[1] 第3章 块#32  距离 0.7771
[2] 第4章 块#43  距离 0.7782
[3] 第2章 块#23  距离 0.7816
[4] 第5章 块#53  距离 0.7831
```

**距离几乎相同** → 向量高度相似，互相「抱团」抬高排名。

**归因**：与「文档头块」同类（跨章节重复 + 信息量低），
但根源不同 —— 文档头是**分块产物**，任务页是**素材本身**重复
（系列讲义每章都有相同的任务页）。

**修复**：`filter_header_chunks()` 增加规则 3，识别章节任务页。

**★ 关键取舍**：**习题页不过滤**。
「5.本章习题」看似同类，但含知识点问句（如「为什么要使用函数？」），
**本身就有检索价值**。所以规则只针对「本章任务」。

**本地验证**（74 块 → 保留 60）：
```
丢弃 14 个 = 文档头 5 + 封面页 5 + 任务页 4
残留重复任务句块：0        ← 清理干净
含「本章习题」保留块：10   ← 未被误杀
关键答案块全在：86400 ✓ / 枚举定义 ✓ / 函数讲解 ✓
```

### 附带确认：「C语言是什么」拒答是**正确的**

```
【回答】抱歉，我无法从提供的资料中找到相关信息来回答此问题。
说明：提供的上下文片段主要涉及各章任务描述...，
但没有任何片段对"C语言是什么"这一概念本身进行定义或说明。
```

讲义第1章是「开发环境」，确实没有概念定义。
**这不是失败** —— 且新 Prompt 让它**说清了拒答理由**，比单纯说"找不到"有用得多。

### 未做的事（留待 v3）

- **Rerank**：召回 top_k=10 → 交叉编码器精排出 3，效果提升最明显
- **余弦相似度**：替代 L2 距离，让分数可解释
- **跨页聚合**：用例 12（「第4章三个函数叫什么」）需跨页信息，单次检索难覆盖
- **扩大语料**：55 个块仍然偏少，检索区分度天然受限

---

## 模板（后续照此记录）

```markdown
## YYYY-MM-DD · <本次主题>

### 完成内容
### 关键决策（做了什么选择，为什么）
### 验证结果
### 踩过的坑（现象 → 原因 → 解决）
### 下一步
```
