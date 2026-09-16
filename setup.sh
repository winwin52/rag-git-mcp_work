#!/usr/bin/env bash
# ============================================================
#  一键环境搭建 + 建索引
#
#  在 GitHub Codespaces / 全新 Linux 环境里跑这一个脚本即可。
#
#  用法：
#      bash setup.sh              # 完整流程（推荐）
#      bash setup.sh --deps       # 只装依赖
#      bash setup.sh --index      # 只建索引
#      bash setup.sh --check      # 只检查环境
# ============================================================

set -e   # 遇错即停

# ---------- 颜色 ----------
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[0;34m'; N='\033[0m'
info()  { echo -e "${B}[INFO]${N} $*"; }
ok()    { echo -e "${G}[ OK ]${N} $*"; }
warn()  { echo -e "${Y}[WARN]${N} $*"; }
err()   { echo -e "${R}[FAIL]${N} $*"; }

# 切到脚本所在目录
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
info "项目目录：$PROJECT_DIR"

MODE="${1:-all}"

# ============================================================
#  环境检查
# ============================================================
check_env() {
    echo
    echo "=========================================="
    echo "  环境检查"
    echo "=========================================="

    # Python 版本
    if command -v python3 >/dev/null 2>&1; then
        PY=python3
    elif command -v python >/dev/null 2>&1; then
        PY=python
    else
        err "未找到 Python"
        return 1
    fi
    PYVER=$($PY --version 2>&1 | awk '{print $2}')
    ok "Python: $PYVER"

    # 版本需 >= 3.10
    $PY -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" \
        || { err "需要 Python 3.10+（当前 $PYVER）"; return 1; }

    # 磁盘
    AVAIL=$(df -h . | awk 'NR==2 {print $4}')
    info "可用磁盘：$AVAIL"

    # 网络（可选）
    if curl -sI --max-time 8 https://pypi.org >/dev/null 2>&1; then
        ok "可访问 PyPI"
    else
        warn "无法访问 PyPI，pip 可能失败"
    fi

    echo
    echo "已安装的核心包："
    $PY - <<'PYEOF'
import importlib
for m in ["langchain","langchain_huggingface","sentence_transformers",
          "faiss","pptx","dotenv","langchain_deepseek"]:
    try:
        importlib.import_module(m)
        print(f"  OK    {m}")
    except Exception:
        print(f"  MISS  {m}")
PYEOF
}

# ============================================================
#  安装依赖
# ============================================================
install_deps() {
    echo
    echo "=========================================="
    echo "  安装依赖"
    echo "=========================================="

    $PY -m pip install --upgrade pip -q

    # ★ 先装 CPU 版 torch
    #   否则 pip 会拉 CUDA 版，多占 4-6 GB（Codespaces 爆盘的元凶）
    info "安装 CPU 版 torch（避免拉入 CUDA 包）……"
    $PY -m pip install torch --index-url https://download.pytorch.org/whl/cpu \
        || warn "CPU 版 torch 安装失败，回退到默认源"

    info "安装其余依赖（可能需要几分钟）……"
    $PY -m pip install -r requirements.txt

    info "安装 MCP SDK……"
    $PY -m pip install "mcp[cli]" || warn "MCP SDK 安装失败，不影响 RAG 部分"

    ok "依赖安装完成"
}

# ============================================================
#  准备数据与密钥
# ============================================================
prepare() {
    echo
    echo "=========================================="
    echo "  准备数据与密钥"
    echo "=========================================="

    # 进度数据
    if [ ! -f data/progress.json ]; then
        cp data/progress.example.json data/progress.json
        ok "已创建 data/progress.json"
    else
        ok "data/progress.json 已存在"
    fi

    # .env
    if [ ! -f .env ]; then
        cp .env.example .env
        warn "已创建 .env —— 请填入你的 DEEPSEEK_API_KEY"
        warn "编辑命令： nano .env     （Ctrl+O 保存，Ctrl+X 退出）"
    else
        ok ".env 已存在"
    fi

    # 检查 Key 是否已配置
    if grep -q "sk-xxxx" .env 2>/dev/null; then
        warn "检测到 .env 中仍是占位符，请替换为真实密钥"
        warn "没有密钥仍可运行：python eval.py --retrieval-only"
    fi
}

# ============================================================
#  建索引
# ============================================================
build_index() {
    echo
    echo "=========================================="
    echo "  构建向量索引"
    echo "=========================================="

    # 模型下载加速（国内网络可取消注释）
    # export HF_ENDPOINT=https://hf-mirror.com

    # 预处理（若尚未生成）
    if [ ! -d data_processed ] || [ -z "$(ls -A data_processed 2>/dev/null)" ]; then
        info "运行预处理：PPTX → Markdown"
        $PY preprocess.py
    else
        ok "data_processed/ 已存在，跳过预处理"
    fi

    # 建索引
    if [ -d vector_index ] && [ -n "$(ls -A vector_index 2>/dev/null)" ]; then
        ok "vector_index/ 已存在，跳过"
        $PY build_index.py --stats
    else
        info "首次建索引会下载嵌入模型（约 100MB），请耐心等待……"
        $PY build_index.py
    fi
}

# ============================================================
#  自检
# ============================================================
self_test() {
    echo
    echo "=========================================="
    echo "  自检"
    echo "=========================================="

    # 业务层（不需要 LLM）
    info "MCP 业务层测试……"
    $PY -m mcp_server.business >/dev/null 2>&1 \
        && ok "业务层正常" \
        || warn "业务层测试失败"

    # 检索层（不需要 API Key）
    if [ -d vector_index ] && [ -n "$(ls -A vector_index 2>/dev/null)" ]; then
        info "检索层测试（不需要 API Key）……"
        $PY eval.py --retrieval-only 2>&1 | tail -20
    fi

    echo
    echo "=========================================="
    echo "  全部完成"
    echo "=========================================="
    echo
    echo "接下来可以运行："
    echo "  python main.py                    # 交互式问答（需 API Key）"
    echo "  python eval.py                    # 完整评测"
    echo "  python eval.py --retrieval-only   # 只测检索"
    echo "  mcp dev mcp_server/server.py      # MCP 调试界面"
    echo
}

# ============================================================
#  主流程
# ============================================================
case "$MODE" in
    --check)
        check_env
        ;;
    --deps)
        check_env
        install_deps
        ;;
    --index)
        build_index
        ;;
    all|*)
        check_env
        install_deps
        prepare
        build_index
        self_test
        ;;
esac
