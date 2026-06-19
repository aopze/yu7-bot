#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram 贴纸关键词管理 Bot 安装脚本
自动安装依赖并创建配置文件 (.env + config.json)
"""

import sys
import subprocess
import json
from pathlib import Path


def print_step(step: str):
    """打印步骤信息"""
    print(f"\n{'='*50}")
    print(f"步骤 {step}")
    print('='*50)


def check_python_version():
    """检查 Python 版本"""
    print_step("1. 检查 Python 版本")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"\u274c Python 版本过低，需要 Python 3.8+，当前 {version.major}.{version.minor}.{version.micro}")
        sys.exit(1)
    print(f"\u2705 Python {version.major}.{version.minor}.{version.micro}")


def install_dependencies():
    """安装依赖包"""
    print_step("2. 安装依赖包")
    requirements_file = Path(__file__).parent / "requirements.txt"
    if not requirements_file.exists():
        print("\u274c 找不到 requirements.txt")
        sys.exit(1)
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(requirements_file)])
        print("\u2705 依赖安装成功")
    except subprocess.CalledProcessError as e:
        print(f"\u274c 依赖安装失败：{e}")
        sys.exit(1)


def create_env():
    """创建 .env 文件"""
    print_step("3. 设置 Bot Token")
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        print("\u26a0\ufe0f  .env 已存在")
        choice = input("是否覆盖？(y/n): ").lower()
        if choice != 'y':
            print("\u2705 保留现有 .env")
            return
    print("\n获取 Bot Token 方法：")
    print("   1. Telegram 搜索 @BotFather")
    print("   2. 发送 /newbot")
    print("   3. 按提示设置，复制 Token\n")
    token = input("请输入 Bot Token: ").strip()
    if not token:
        print("\u274c Token 不能为空")
        sys.exit(1)
    env_file.write_text(f"BOT_TOKEN={token}\n", encoding='utf-8')
    print(f"\u2705 .env 已创建")


def create_config():
    """创建配置文件（不含 token）"""
    print_step("4. 配置文件设置")
    config_file = Path(__file__).parent / "config.json"
    if config_file.exists():
        print("\u26a0\ufe0f  config.json 已存在，跳过")
        return
    admin_id = input("管理员用户 ID (可选，回车跳过): ").strip()
    config = {
        "welcome_message": "欢迎 {user} 加入群组！",
        "keywords": {},
        "sticker_keywords": {"_global": {}},
        "inline_sticker_keywords": {"_global": {}},
        "known_groups": {},
        "admin_ids": [int(admin_id)] if admin_id.isdigit() else [],
        "enabled_features": {
            "keyword_reply": True,
            "welcome_message": True,
            "anti_spam": False,
            "log_messages": False,
            "sticker_random": True,
        }
    }
    with open(config_file, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False)
    print(f"\u2705 config.json 已创建")


def print_next_steps():
    """打印后续步骤"""
    print_step("\u2705 安装完成")
    print("""
后续步骤：
  1. 运行 python bot.py 启动 Bot
  2. 或将 Bot 加入群组并给管理员权限
  3. 私聊 @你的Bot 发送 /start 管理关键词
  4. 在群聊中触发关键词测试自动回复
""")


def main():
    print(f"\n{'='*50}")
    print("Telegram 贴纸关键词 Bot 安装向导")
    print(f"{'='*50}")
    try:
        check_python_version()
        install_dependencies()
        create_env()
        create_config()
        print_next_steps()
    except KeyboardInterrupt:
        print("\n\n\u274c 安装已取消")
        sys.exit(1)
    except Exception as e:
        print(f"\n\u274c 安装失败：{e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
