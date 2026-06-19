#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Group Sticker Management Bot (python-telegram-bot v22.7)

模块拆分:
  bot_config.py   — 全局状态、配置、持久化、辅助函数、菜单建造器
  bot_preload.py  — 贴纸/Emoji/图片预加载
  bot_handlers.py — 消息/命令处理器
  bot_callback.py — 内联按钮回调处理器
  bot_game.py     — 阵列模式 (五子棋)
  bot.py          — 入口 + main()
"""
import json, logging, os, random, re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, InlineQueryHandler,
    ChosenInlineResultHandler, filters, CallbackQueryHandler,
    ChatMemberHandler,
)

# 全局配置与状态
from bot_config import (
    config, logger,
    load_config, save_config,
    _migrate_config,
    CONFIG_FILE,
)
# 预加载
from bot_preload import preload_sticker_sets
# 处理器
from bot_handlers import (
    start, help_command, show_sticker_keywords, add_sticker_keyword,
    cancel, cmd_gap, cmd_merge, cmd_addemoji, cmd_addimg, cmd_delyu,
    cmd_counter, cmd_refresh, cmd_delemo, cmd_keep,
    handle_keyword, handle_sticker_sent, handle_photo, handle_return_card,
    inline_query, chosen_inline,
    my_chat_member_handler,
)
from bot_callback import button_callback
from bot_game import (
    handle_array_move, cmd_array_join, cmd_array_game, cmd_array_stop,
    error_handler,
)
from bot_text_game import (
    cmd_addtext, cmd_deltext, cmd_listtext, cmd_jointext, cmd_showyu, cmd_stoptext,
)


async def main():
    global config
    token = os.getenv('BOT_TOKEN', config.get('bot_token', ''))
    if not token or token == 'YOUR_BOT_TOKEN_HERE': return print("请在 .env 文件中设置 BOT_TOKEN")
    app = Application.builder().token(token) \
        .connect_timeout(30).read_timeout(30).write_timeout(30) \
        .pool_timeout(30).build()
    app.add_handler(CommandHandler("yu", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("liststicker", show_sticker_keywords))
    app.add_handler(CommandHandler("addsticker", add_sticker_keyword))
    app.add_handler(CommandHandler("emo", cmd_addemoji))
    app.add_handler(CommandHandler("delyu", cmd_delyu))
    app.add_handler(CommandHandler("counter", cmd_counter))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("gap", cmd_gap))
    app.add_handler(CommandHandler("join", cmd_array_join))
    app.add_handler(CommandHandler("game", cmd_array_game))
    app.add_handler(CommandHandler("stop", cmd_array_stop))
    app.add_handler(CommandHandler("addimg", cmd_addimg))
    app.add_handler(CommandHandler("addtext", cmd_addtext))
    app.add_handler(CommandHandler("deltext", cmd_deltext))
    app.add_handler(CommandHandler("listtext", cmd_listtext))
    app.add_handler(CommandHandler("jointext", cmd_jointext))
    app.add_handler(CommandHandler("showyu", cmd_showyu))
    app.add_handler(CommandHandler("stoptext", cmd_stoptext))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("del", cmd_delemo))
    app.add_handler(CommandHandler("keep", cmd_keep))
    app.add_handler(CommandHandler("merge", cmd_merge))
    app.add_handler(ChatMemberHandler(my_chat_member_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(ChosenInlineResultHandler(chosen_inline))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^[dfk]$'), handle_return_card))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker_sent))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.Regex(r'^[a-iA-I][1-9]$') & filters.TEXT & ~filters.COMMAND, handle_array_move))
    app.add_handler(MessageHandler(filters.TEXT, handle_keyword))
    app.add_error_handler(error_handler)

    # Set bot commands menu
    async def set_cmds(app):
        commands = [
            BotCommand("yu", "打开管理菜单"),
            BotCommand("help", "查看全部指令说明"),
            BotCommand("addsticker", "添加贴纸关键词"),
            BotCommand("emo", "添加 Emoji 关键词"),
            BotCommand("addimg", "添加图片关键词"),
            BotCommand("addtext", "添加文本卡牌池"),
            BotCommand("deltext", "删除文本卡牌池"),
            BotCommand("delyu", "删除关键词(全类型)"),
            BotCommand("counter", "开关计数器"),
            BotCommand("cancel", "取消当前操作"),
            BotCommand("jointext", "加入文本卡牌局"),
            BotCommand("showyu", "查看场上卡牌"),
            BotCommand("stoptext", "结束文本卡牌局"),
            BotCommand("liststicker", "查看关键词列表"),
            BotCommand("listtext", "查看文本卡牌池列表"),
            BotCommand("refresh", "刷新内联贴纸包"),
            BotCommand("del", "删除emoji关键词的emoji"),
            BotCommand("keep", "查看内联包保留区"),
            BotCommand("merge", "内联包合并/单包切换"),
            BotCommand("gap", "拼接图片分隔符"),
            BotCommand("join", "加入阵列房间"),
            BotCommand("game", "阵列出牌"),
            BotCommand("stop", "离开阵列房间"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("Commands set")

    app.post_init = set_cmds

    import asyncio
    async def preload(): await preload_sticker_sets(app=app)
    try: asyncio.get_event_loop().run_until_complete(preload())
    except Exception as e: logger.warning(f"Preload: {e}")
    logger.info("Bot starting..."); print("[OK] Bot 已启动! Ctrl+C 停止")
    try:
        # Railway / cloud: use webhook; local: use polling
        webhook_url = os.getenv('WEBHOOK_URL', '')
        port = int(os.getenv('PORT', '8080'))
        if webhook_url:
            logger.info(f"Webhook mode: {webhook_url}")
            await app.bot.set_webhook(url=webhook_url)
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                webhook_url=webhook_url,
                allowed_updates=Update.ALL_TYPES,
            )
        else:
            app.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        import traceback
        logger.critical(f"Bot polling crashed: {e}\n{traceback.format_exc()}")
        raise

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
