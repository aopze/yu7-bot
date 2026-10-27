#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Group Sticker Management Bot (python-telegram-bot v22.7)

模块拆分:
  bot_config.py   — 全局状态、配置、持久化、辅助函数、菜单建造器
  bot_preload.py  — 贴纸/Emoji/图片预加载
  bot_handlers.py — 消息/命令处理器
  bot_callback.py — 内联按钮回调处理器
  bot.py          — 入口 + main()
"""
import json, logging, os, random, re
from pathlib import Path

# 尝试加载 .env，失败则跳过
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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
    start, cmd_yu, help_command, show_sticker_keywords,     add_sticker_keyword, cmd_addin,
    cancel, cmd_gap, cmd_merge, cmd_addemoji, cmd_addimg, cmd_delyu,
    cmd_counter, cmd_refresh, cmd_delemo, cmd_keep, cmd_restart,
    handle_keyword, handle_sticker_sent, handle_photo, handle_return_card,
    inline_query, chosen_inline,
    my_chat_member_handler,
)
from bot_callback import button_callback
from bot_text_game import (
    cmd_addtext, cmd_deltext, cmd_listtext, cmd_jointext, cmd_showyu, cmd_stoptext,
)
from bot_uno import cmd_unoyu
from bot_makepack import cmd_makeyu, cmd_makemoji, cmd_done, cmd_cancel_pack, handle_making_sticker
from bot_rank import (play_command, rank_command, handle_web_app_data,
                      setup_menu_button, minidata_command,
                      make_report_app)


async def error_handler(update, context):
    """全局错误处理器（原 bot_game 模块已删除，保留基础异常记录以免丢失报错）。"""
    import traceback
    logger.error(f"未处理异常: {context.error}\n{traceback.format_exc()}")


async def main():
    global config
    token = os.getenv('BOT_TOKEN', config.get('bot_token', ''))
    if not token or token == 'YOUR_BOT_TOKEN_HERE': return print("请在 .env 文件中设置 BOT_TOKEN")
    app = Application.builder().token(token) \
        .connect_timeout(30).read_timeout(30).write_timeout(30) \
        .pool_timeout(30).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("yu", cmd_yu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("liststicker", show_sticker_keywords))
    app.add_handler(CommandHandler("addsticker", add_sticker_keyword))
    app.add_handler(CommandHandler("addin", cmd_addin))
    app.add_handler(CommandHandler("emo", cmd_addemoji))
    app.add_handler(CommandHandler("delyu", cmd_delyu))
    app.add_handler(CommandHandler("counter", cmd_counter))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("gap", cmd_gap))
    app.add_handler(CommandHandler("addimg", cmd_addimg))
    app.add_handler(CommandHandler("addtext", cmd_addtext))
    app.add_handler(CommandHandler("deltext", cmd_deltext))
    app.add_handler(CommandHandler("listtext", cmd_listtext))
    app.add_handler(CommandHandler("jointext", cmd_jointext))
    app.add_handler(CommandHandler("unoyu", cmd_unoyu))
    app.add_handler(CommandHandler("makeyu", cmd_makeyu))
    app.add_handler(CommandHandler("makemoji", cmd_makemoji))
    app.add_handler(CommandHandler("done", cmd_done))
    app.add_handler(CommandHandler("cancelpack", cmd_cancel_pack))
    app.add_handler(CommandHandler("showyu", cmd_showyu))
    app.add_handler(CommandHandler("stoptext", cmd_stoptext))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("del", cmd_delemo))
    app.add_handler(CommandHandler("keep", cmd_keep))
    app.add_handler(CommandHandler("merge", cmd_merge))
    app.add_handler(CommandHandler("restart", cmd_restart))
    # 方舟战棋 Mini App + 排行榜
    app.add_handler(CommandHandler("play", play_command))
    app.add_handler(CommandHandler("rank", rank_command))
    app.add_handler(CommandHandler("minidata", minidata_command))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    app.add_handler(ChatMemberHandler(my_chat_member_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(InlineQueryHandler(inline_query))
    app.add_handler(ChosenInlineResultHandler(chosen_inline))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^([dfk]|d\d+|d\s*\d+%)$'), handle_return_card))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO | filters.ANIMATION) & filters.CaptionRegex(r'^([dfk]|d\d+|d\s*\d+%)$'), handle_return_card))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_making_sticker), group=0)
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker_sent), group=1)
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT, handle_keyword))
    app.add_error_handler(error_handler)

    # Combine set_cmds and preload into single post_init
    async def post_init(app_inst):
        commands = [
            BotCommand("start", "打开管理菜单"),
            BotCommand("yu", "快速跳转关键词管理"),
            BotCommand("help", "查看全部指令说明"),
            BotCommand("addsticker", "添加贴纸关键词"),
            BotCommand("addin", "添加内联关键词"),
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
            BotCommand("play", "打开方舟战棋"),
            BotCommand("rank", "查看战棋排行榜"),
            BotCommand("minidata", "诊断成绩上报链路"),
        ]
        await app_inst.bot.set_my_commands(commands)
        logger.info("Commands set")
        await setup_menu_button(app_inst)
        try: await preload_sticker_sets(app=app_inst)
        except Exception as e: logger.warning(f"Preload: {e}")

    app.post_init = post_init

    logger.info("Bot starting..."); print("[OK] Bot 已启动! Ctrl+C 停止")
    return app


if __name__ == '__main__':
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        app = loop.run_until_complete(main())
    finally:
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()
        asyncio.set_event_loop(None)

    try:
        webhook_url = os.getenv('WEBHOOK_URL', '')
        port = int(os.getenv('PORT', '8080'))
        report_app = make_report_app()
        if webhook_url:
            logger.info(f"Webhook mode: {webhook_url}")
            # 把 Mini App 上报端点挂到同一个 aiohttp 应用上（web=），与 webhook 共用端口
            from urllib.parse import urlparse
            webhook_path = urlparse(webhook_url).path or '/webhook'
            app.run_webhook(
                listen="0.0.0.0",
                port=port,
                webhook_url=webhook_url,
                web=report_app,
                webhook_path=webhook_path,
                allowed_updates=Update.ALL_TYPES,
            )
        else:
            # Polling 模式：PTB 不占用端口，单独起一个 aiohttp 服务监听 $PORT，
            # 既提供 /api/score 上报端点，也满足 Railway 的健康检查（GET / 返回 200）。
            if report_app is not None:
                import threading
                def _run_report():
                    try:
                        from aiohttp import web as _w
                        _w.run_app(report_app, host="0.0.0.0", port=port)
                    except Exception as e:
                        logger.critical(f"上报服务启动失败: {e}")
                t = threading.Thread(target=_run_report, daemon=True)
                t.start()
                logger.info(f"Polling mode: 上报服务已起在端口 {port}")
            app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)
    except Exception as e:
        import traceback
        logger.critical(f"Bot polling crashed: {e}\n{traceback.format_exc()}")
        raise
