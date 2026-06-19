#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取自定义 Emoji ID 的工具

用法:
    python get_emoji_ids.py <emoji_pack_name>
    
示例:
    python get_emoji_ids.py my_bot_emojis
"""

import os, sys, json, asyncio
from dotenv import load_dotenv
from telegram import Bot
from telegram.error import TelegramError

load_dotenv()


async def get_emoji_ids(pack_name: str):
    token = os.getenv("BOT_TOKEN")
    if not token:
        print("请在 .env 中设置 BOT_TOKEN")
        return

    bot = Bot(token)
    try:
        ss = await bot.get_sticker_set(pack_name)
    except TelegramError as e:
        print(f"获取贴纸包失败: {e}")
        return

    print(f"\n表情包: {ss.title} ({pack_name})")
    print(f"共 {len(ss.stickers)} 个表情\n")
    print("=" * 70)

    emoji_map = {}
    for i, sticker in enumerate(ss.stickers):
        if sticker.type == "custom_emoji" and sticker.custom_emoji_id:
            emoji_map[sticker.emoji or f"#{i}"] = sticker.custom_emoji_id
            print(f"  [{i:2d}] {sticker.emoji or '(无)'}  →  custom_emoji_id: {sticker.custom_emoji_id}")
        else:
            print(f"  [{i:2d}] {sticker.emoji or '(无)'}  →  (非 custom_emoji 类型: {sticker.type})")

    print("=" * 70)
    print(f"\n==> 共提取 {len(emoji_map)} 个 custom_emoji_id")
    print("\nJSON 格式 (可直接粘贴到 config.json):")
    print(json.dumps(emoji_map, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python get_emoji_ids.py <emoji_pack_name>")
        print("示例: python get_emoji_ids.py my_bot_emojis")
        sys.exit(1)
    asyncio.run(get_emoji_ids(sys.argv[1]))
