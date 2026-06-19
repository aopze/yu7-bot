#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速测试 Bot Token 是否有效（Windows 兼容版）
"""

import json
import os
import requests
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


def test_bot_token():
    """测试 Bot Token"""
    # 优先从 .env 读取
    token = os.getenv('BOT_TOKEN')

    if not token:
        # 兼容旧 config.json
        config_file = Path(__file__).parent / "config.json"
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        token = config.get('bot_token', '')

    if not token or token == "YOUR_BOT_TOKEN_HERE":
        print("[x] 请在 .env 文件中设置 BOT_TOKEN")
        return False
    
    print("正在测试 Bot Token...\n")
    
    # 测试 getMe
    url = f"https://api.telegram.org/bot{token}/getMe"
    
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('ok'):
            result = data.get('result', {})
            print("[√] Bot Token 有效！\n")
            print(f"Bot 名称：{result.get('first_name')}")
            print(f"Bot 用户名：@{result.get('username')}")
            print(f"Bot ID：{result.get('id')}")
            print(f"\n在 Telegram 中搜索：@{result.get('username')}")
            return True
        else:
            print(f"[x] Token 无效：{data.get('description')}")
            return False
            
    except Exception as e:
        print(f"[x] 测试失败：{e}")
        return False


def test_bot_commands():
    """测试 Bot 基本命令（需要 bot 正在运行）"""
    token = os.getenv('BOT_TOKEN')
    if not token:
        config_file = Path(__file__).parent / "config.json"
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
        token = config.get('bot_token', '')

    # Read admin_id from config
    config_file = Path(__file__).parent / "config.json"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = json.load(f)
    admin_id = config.get('admin_ids', [])[0] if config.get('admin_ids') else None
    
    if not admin_id:
        print("\n[!] 未配置管理员 ID，跳过命令测试")
        return
    
    print(f"\n正在测试发送消息到管理员...\n")
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = {
        "chat_id": admin_id,
        "text": "Bot 配置成功！\n\n现在你可以：\n1. 将 bot 添加到群组\n2. 发送 /start 测试\n3. 发送包含关键词的消息测试自动回复"
    }
    
    try:
        response = requests.post(url, json=data, timeout=10)
        result = response.json()
        
        if result.get('ok'):
            print(f"[√] 消息已发送到你的 Telegram（ID: {admin_id}）")
            print(f"请检查 Telegram 是否收到消息")
        else:
            print(f"[x] 发送失败：{result.get('description')}")
            
    except Exception as e:
        print(f"[x] 发送失败：{e}")


if __name__ == '__main__':
    print("=" * 50)
    print("Telegram Bot 测试工具")
    print("=" * 50 + "\n")
    
    if test_bot_token():
        test_bot_commands()
    
    print("\n" + "=" * 50)
    print("测试完成！")
    print("=" * 50)
