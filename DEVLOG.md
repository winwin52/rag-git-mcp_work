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

- [ ] 在本机/Codespaces 安装依赖
- [ ] 跑通 `build_index.py`，建索引
- [ ] 跑 `eval.py --retrieval-only` 验证检索质量
- [ ] 配 API Key，跑完整问答
- [ ] 记录失败案例到 `eval/failure_cases.md`

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
