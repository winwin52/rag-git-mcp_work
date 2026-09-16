# GitHub Codespaces 运行指南

从零开始（全新环境）到跑通问答的完整指令。

> **前提**：已在 GitHub 上 Fork 或拥有本项目仓库。
> **仓库地址**：https://github.com/winwin52/rag-git-mcp_work

---

## 为什么不用 Docker / Milvus

本项目用 **FAISS**——它是**算法库，不是数据库服务**：
- 不需要 Docker
- 不需要起服务、不需要端口
- 索引就是一个本地文件

在 Codespaces 里，Docker Hub 经常拉不到镜像（`minio/minio` 报 `denied` 就是这么来的）。
**用 FAISS 完全绕开这个坑。**

---

## 步骤总览

| 步骤 | 内容 | 耗时 |
|---|---|---|
| 1 | 创建 Codespace | 2-3 分钟 |
| 2 | 系统初始化（apt） | 1-2 分钟 |
| 3 | 建 Python 环境 | 1 分钟 |
| 4 | 装依赖 | **5-15 分钟** |
| 5 | 配 API Key | 1 分钟 |
| 6 | 建索引 | 1-2 分钟 |
| 7 | 跑起来 | — |

> **想省事**：步骤 2-6 可以直接跑 `bash setup.sh` 一键完成。
> 下面仍然逐步拆解，便于排查问题。

---

## 步骤 1 · 创建 Codespace

1. 打开仓库页面
2. 点右上角 **Code** → **Codespaces** 标签 → **Create codespace on master**
3. 等待环境初始化（首次约 2-3 分钟）

**建议**：在 GitHub 账户设置的 Codespaces 页面，把 **Idle timeout 调到 30 分钟**，
避免短暂离开就挂起（免费额度：120 核时/月）。

---

## 步骤 2 · 系统初始化

打开终端（`` Ctrl+` ``），依次执行：

```bash
# 更新软件包索引
sudo apt update

# 升级已安装的包（可选，但建议做）
sudo apt upgrade -y

# 常用工具（wget 一般已自带，缺了才需要）
sudo apt install -y wget curl git build-essential
```

**说明**：
- `sudo apt update` 只更新索引，很快
- `apt upgrade -y` 会实际升级软件，1-2 分钟
- Codespaces 默认就是 `ubuntu` 用户，**不需要** `su ubuntu`

**验证**：
```bash
python3 --version    # 应显示 3.10 或更高
```

---

## 步骤 3 · 创建 Python 环境

Codespaces 自带 conda（在 `/opt/conda`）。直接用它建环境：

```bash
# 确认 conda 可用
conda --version

# 创建环境
conda create -n c-rag python=3.12.7 -y

# 激活
conda activate c-rag

# 验证
which python
# 应显示 /opt/conda/envs/c-rag/bin/python
```

> **如果你偏好 venv**（更轻量）：
> ```bash
> python3 -m venv .venv
> source .venv/bin/activate
> ```

---

## 步骤 4 · 安装依赖

**⚠️ 顺序很重要**：先装 CPU 版 torch，再装其余。

```bash
# 进入项目目录
cd /workspaces/rag-git-mcp_work

# ① 升级 pip
pip install --upgrade pip

# ② 先装 CPU 版 torch（关键！）
pip install torch --index-url https://download.pytorch.org/whl/cpu

# ③ 装其余依赖
pip install -r requirements.txt

# ④ MCP SDK（做 MCP 任务时才需要）
pip install "mcp[cli]"
```

### 为什么必须先装 CPU 版 torch

`requirements.txt` 里写了 `torch>=2.2.0`。如果直接装，pip 会拉**默认版本 = CUDA 版**，
它会带入 10 个 `nvidia-*` 包，**多占 4-6 GB**。

```
CUDA 版 torch  ≈ 2-3 GB  +  nvidia-* 约 2-3 GB
CPU  版 torch  ≈ 200 MB
```

**先装 CPU 版后，pip 看到 torch 已满足要求就不会重装。**

> 本项目用 `bge-small-zh`（512 维小模型），**CPU 完全够用**，
> 而且 all-in-rag 教程本身就是用 `device='cpu'`。

### 加速模型下载（可选）

```bash
export HF_ENDPOINT=https://hf-mirror.com
```

建议追加到 `~/.bashrc` 永久生效：

```bash
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.bashrc
source ~/.bashrc
```

---

## 步骤 5 · 配置 API Key

```bash
cd /workspaces/rag-git-mcp_work

# 从模板创建
cp .env.example .env

# 编辑（Codespaces 里用 nano 最简单）
nano .env
```

把这一行的占位符替换成真实密钥：

```
DEEPSEEK_API_KEY=sk-你的真实密钥
```

保存退出：`Ctrl+O` → `Enter` → `Ctrl+X`

**验证**：

```bash
python -c "from dotenv import load_dotenv; import os; load_dotenv(); \
k=os.getenv('DEEPSEEK_API_KEY'); print('已配置，前缀:', k[:8] if k else '未配置')"
```

> ⚠️ `.env` 已被 `.gitignore` 忽略，**不会 push 到 GitHub**。
> 但请仍保持好习惯：**永远不要硬编码密钥到代码里**。

### 也可以直接用环境变量

```bash
export DEEPSEEK_API_KEY="sk-你的密钥"
```

（仅当前终端有效；写进 `~/.bashrc` 才能持久）

---

## 步骤 6 · 建索引

```bash
cd /workspaces/rag-git-mcp_work

# ① 预处理：PPTX → Markdown（很快，几秒）
python preprocess.py

# ② 建向量索引（首次会下载嵌入模型约 100MB）
python build_index.py
```

**预期输出**：

```
加载 5 个文档，共 5 篇
分块完成：5 篇 → 约 40 个块 (chunk_size=500, overlap=80)
加载嵌入模型：BAAI/bge-small-zh-v1.5（首次会下载……）
正在向量化并构建 FAISS 索引……
索引已保存：/workspaces/rag-git-mcp_work/vector_index
```

**检查索引信息**：

```bash
python build_index.py --stats
```

---

## 步骤 7 · 运行

### ① 先测检索（不需要 API Key）★ 推荐先跑这个

```bash
python eval.py --retrieval-only
```

这会打印每个测试问题的检索片段、来源、相似度距离。
**不用 Key 就能看出检索质量好不好**，是定位失败最快的入口。

### ② 交互式问答

```bash
python main.py
```

```
请输入问题 > 函数的定义格式是什么样的？

【回答】函数的定义格式为：返回值类型名 函数名(参数列表) { 函数体; }
【依据】检索到 3 个相关片段：
  [1] ...第4章....md / 第4章 / 块#12 （距离 0.4213）
      ### 2.2 函数的定义 与变量、数组一样，在使用函数前需要先定义函数...
```

输入 `q` 退出。

### ③ 完整评测

```bash
python eval.py
```

跑 12 个用例（6 有答案 / 3 无答案 / 3 边界），结果存到 `eval/last_run.json`。

### ④ MCP 调试

```bash
mcp dev mcp_server/server.py
```

会打开一个网页面板，可以手动调用工具、查看 schema。
Codespaces 会自动转发端口，点弹出的提示即可打开。

### ⑤ MCP 业务层自测（不需要 MCP、不需要 Key）

```bash
python -m mcp_server.business
```

---

## 一键脚本

嫌上面步骤多？直接：

```bash
cd /workspaces/rag-git-mcp_work
bash setup.sh
```

它会依次完成：环境检查 → 装依赖 → 准备配置 → 建索引 → 自检。

**分步执行**：

```bash
bash setup.sh --check    # 只看环境
bash setup.sh --deps     # 只装依赖
bash setup.sh --index    # 只建索引
```

---

## 常见问题

### Q: `conda: command not found`

Codespaces 里 conda 在 `/opt/conda`，如果没自动加载：

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate c-rag
```

或永久生效：

```bash
/opt/conda/bin/conda init bash
source ~/.bashrc
```

### Q: `CondaError: Run 'conda init' before 'conda activate'`

```bash
conda init bash
source ~/.bashrc     # 或关掉终端标签页重开
conda activate c-rag
```

### Q: `No space left on device` (`Errno 28`)

**说明装了 CUDA 版 torch**。清理后重装：

```bash
pip uninstall -y torch torchvision torchaudio
pip cache purge
conda clean --all -y

# 检查还有多少空间
df -h

# 重装 CPU 版
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

**根治**：提高 Codespaces 磁盘配额。在仓库根目录建
`.devcontainer/devcontainer.json`：

```json
{
  "image": "mcr.microsoft.com/devcontainers/universal:2",
  "hostRequirements": { "cpus": 4, "memory": "8gb", "storage": "32gb" }
}
```

然后 **重建 Codespace** 才会生效。

### Q: 下载嵌入模型卡住

```bash
export HF_ENDPOINT=https://hf-mirror.com
python build_index.py
```

### Q: `未找到 API Key`

```bash
# 确认 .env 存在且有内容
cat .env | head -3

# 或在当前终端直接导出
export DEEPSEEK_API_KEY="sk-你的密钥"
```

### Q: `索引不存在`

```bash
python preprocess.py && python build_index.py
```

### Q: `git push` 报错 / 作者信息不对

Codespaces 是全新环境，需要配身份：

```bash
git config --global user.name "winwin52"
git config --global user.email "2711025616@qq.com"
```

Codespaces 默认已通过 GitHub token 认证，**push 一般不需要额外配置**。

### Q: 检索结果不相关

按顺序排查：

```bash
# ① 看预处理有没有丢内容
python preprocess.py --inspect

# ② 看检索命中了什么（不需要 Key）
python eval.py --retrieval-only

# ③ 看索引块数和参数
python build_index.py --stats
```

常见原因：
- **分块太碎** → 调大 `config.py` 里的 `chunk_size`
- **top_k 太小** → 调大 `top_k`
- **换了嵌入模型没重建索引** → `python build_index.py --force`

---

## 常用命令速查

```bash
# 环境
conda activate c-rag

# 全流程
python preprocess.py                       # PPT → Markdown
python build_index.py                      # 建索引
python build_index.py --force              # 强制重建
python build_index.py --stats              # 看索引信息

# 使用
python main.py                             # 交互问答
python main.py -q "函数的定义是什么"        # 单次提问
python eval.py --retrieval-only            # 只测检索（无需 Key）
python eval.py                             # 完整评测
python eval.py --case 10                   # 单跑用例

# MCP
python -m mcp_server.business              # 业务层自测
mcp dev mcp_server/server.py               # 调试界面

# 调试
python preprocess.py --inspect             # 预览预处理效果
```

---

## ⚠️ Codespaces 使用提醒

| 事项 | 说明 |
|---|---|
| **免费额度** | 120 核时/月，用完要等或付费 |
| **自动挂起** | 默认 30 分钟无操作挂起，可调 |
| **30 天不访问** | **会被自动删除**，代码要从 GitHub 重新拉 |
| **环境不持久** | 重建后 conda 环境、装的包、下的模型**全都没了**，要重跑 `setup.sh` |
| **向量索引** | 在 `.gitignore` 里，**不会推到 GitHub**，重建后要重新 `build_index.py` |

**所以**：
- 代码和文档 → **GitHub 是唯一真相**（git push 保存）
- 环境和索引 → **可以随时重建**（跑 setup.sh）
