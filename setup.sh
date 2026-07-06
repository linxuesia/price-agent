#!/bin/bash
# 门窗报价助手 - 一键安装脚本
# 适用：macOS / Windows(WSL) / Linux

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "========================================"
echo "  门窗报价助手 - 安装脚本"
echo "========================================"
echo ""

# ---------- 检查 Python ----------
PYTHON=""
for cmd in python3.11 python3.10 python3.9 python3.8 python3; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ 未找到 Python 3.8+，请先安装 Python："
    echo "   macOS: brew install python@3.11"
    echo "   Windows: https://www.python.org/downloads/"
    echo "   安装时勾选 'Add Python to PATH'"
    exit 1
fi

echo "✓ 找到 $PYTHON ($($PYTHON --version))"

# ---------- 创建虚拟环境 ----------
if [ ! -d "venv" ]; then
    echo ""
    echo "创建虚拟环境..."
    $PYTHON -m venv venv
fi

source venv/bin/activate

# ---------- 安装依赖 ----------
echo ""
echo "安装依赖..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

# ---------- 安装 Chromium（Playwright 截图用）----------
echo ""
echo "安装 Chromium 浏览器（用于生成报价单图片）..."
python -m playwright install chromium 2>&1 | grep -v "^$" || true

# ---------- 完成 ----------
echo ""
echo "========================================"
echo "  ✓ 安装完成！"
echo "========================================"
echo ""
echo "启动服务："
echo "  source venv/bin/activate"
echo "  python app.py"
echo ""
echo "浏览器打开：http://localhost:8080"
echo ""
