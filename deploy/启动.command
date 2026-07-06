#!/bin/bash
# 门窗报价助手 - macOS 一键启动
# 双击此文件即可运行

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "首次运行，正在安装..."
    bash setup.sh
fi

source venv/bin/activate
echo ""
echo "服务启动中..."
python app.py &
sleep 2
open http://localhost:8080
wait
