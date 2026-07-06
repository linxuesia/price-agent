#!/bin/bash
# 打包为独立可执行文件（无需安装 Python）
# 使用 PyInstaller 打包为 macOS .app / Windows .exe

set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "========================================"
echo "  打包门窗报价助手"
echo "========================================"

source venv/bin/activate

# 确保依赖完整
pip install pyinstaller -q 2>/dev/null

# 查找 Playwright Chromium 路径
CHROMIUM_PATH=$(python -c "
from playwright.sync_api import sync_playwright
import os
# Playwright 通常在这里
paths = [
    os.path.expanduser('~/Library/Caches/ms-playwright'),
    os.path.expanduser('~/AppData/Local/ms-playwright'),
    os.path.expanduser('~/.cache/ms-playwright'),
]
for p in paths:
    if os.path.exists(p):
        print(p)
        break
" 2>/dev/null)

echo "Chromium 路径: $CHROMIUM_PATH"

# ---------- PyInstaller 打包 ----------
echo ""
echo "开始打包..."

pyinstaller \
    --name "门窗报价助手" \
    --onefile \
    --windowed \
    --add-data "chat.html:." \
    --add-data "calc.py:." \
    --add-data "pricing.json:." \
    --add-data "$CHROMIUM_PATH:playwright_browsers" 2>/dev/null || true \
    --hidden-import "playwright" \
    --hidden-import "pypdfium2" \
    --hidden-import "httpx" \
    --hidden-import "fastapi" \
    --hidden-import "uvicorn" \
    --hidden-import "pillow" \
    --collect-all "playwright" \
    app.py 2>&1

echo ""
echo "========================================"
echo "  打包完成"
echo "========================================"
echo "输出目录: dist/"
ls -la dist/ 2>/dev/null

# 注意：PyInstaller 打包后仍需手动复制 playwright browsers 到正确路径
# 因为 playwright 运行时通过环境变量 PLAYWRIGHT_BROWSERS_PATH 查找浏览器
echo ""
echo "⚠️  首次运行需要设置 Playwright 浏览器路径："
echo "   export PLAYWRIGHT_BROWSERS_PATH=./browsers"
echo "   或将 Chromium 复制到 ~/.cache/ms-playwright/"
