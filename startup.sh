#!/bin/bash
echo "========================================"
echo "正在启动 Telegram Bot..."
echo "========================================"

cd /home/container/bot 2>/dev/null || cd /bot 2>/dev/null || cd ./bot 2>/dev/null
echo "目录: $(pwd)"

if [ ! -f "bot.py" ]; then
    echo "错误: 未找到 bot.py"
    while true; do sleep 30; done
fi

echo "安装依赖..."
pip install -r requirements.txt -q 2>/dev/null || \
python3 -m pip install -r requirements.txt -q 2>/dev/null || \
mise exec python -- pip install -r requirements.txt -q 2>/dev/null || \
echo "依赖安装跳过，直接尝试启动"

echo "启动 Bot..."
exec python3 bot.py
