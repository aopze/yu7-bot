#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_game.py - 阵列模式 (9x9 五子棋) + 错误处理
import re
from bot_config import (
    logger,
    array_board, array_players, array_board_msg,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

def _array_get_thread(update):
    """获取话题 ID（论坛群组需要，普通群返回 None）"""
    msg = update.message if hasattr(update, 'message') and update.message else None
    if msg:
        return getattr(msg, 'message_thread_id', None)
    q = getattr(update, 'callback_query', None)
    if q and q.message:
        return getattr(q.message, 'message_thread_id', None)
    return None

# ========== 阵列模式 — 发送坐标指令 ==========
async def handle_array_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    uid = update.effective_user.id

    # 仅处理 a1-i9（字母=行，数字=列）
    if not re.fullmatch(r'[a-iA-I][1-9]', text):
        return  # 不处理，留给 handle_keyword

    # 检查该群是否有棋盘消息（如被删则自动重建）
    thread_id = _array_get_thread(update)
    if chat_id not in array_board_msg:
        if uid not in array_players:
            await update.message.reply_text("当前没有激活的棋盘，发送 /join 加入房间。")
            return
        board_str = _array_board_to_text()
        status = _array_status_text(update.effective_user)
        msg = await context.bot.send_message(chat_id=chat_id, text=f"{board_str}\n\n{status}", message_thread_id=thread_id)
        array_board_msg[chat_id] = (msg.message_id, thread_id)

    # 检查是否在房间中
    if uid not in array_players:
        await update.message.reply_text("你不在房间中。请发送 /join 加入房间。")
        return

    # 解析坐标（字母=行号，数字=列号，a2=第一行第二列）
    pos = text.lower()
    row = ord(pos[0]) - ord('a')
    col = int(pos[1]) - 1

    if array_board[row][col] != '⬜':
        await update.message.reply_text("这个位置已经有棋子了。")
        return

    # 落子
    my_sym = '❌' if array_players[uid] == 'X' else '⭕'
    array_board[row][col] = my_sym

    # 检查胜负
    winner = _array_check_winner()
    board_str = _array_board_to_text()
    status = _array_status_text(update.effective_user)
    msg_id, t_id = array_board_msg.get(chat_id, (None, None))

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=f"{board_str}\n\n{status}",
        )
    except Exception:
        msg = await context.bot.send_message(chat_id=chat_id, text=f"{board_str}\n\n{status}", message_thread_id=t_id)
        array_board_msg[chat_id] = (msg.message_id, t_id)

    # 胜负判定
    if winner:
        await update.message.reply_text(f"🎉 {my_sym} 获胜！")
        return

    # 删除用户输入的坐标消息（保持聊天整洁）
    try:
        await update.message.delete()
    except Exception:
        pass


async def _do_array_join(update, uid, chat_id):
    """执行加入房间操作 — 首次 join 时自动激活棋盘"""
    target = update.message if hasattr(update, 'message') and update.message else update.effective_message
    if not target:
        target = update.effective_chat  # fallback

    if uid not in array_players:
        x_count = sum(1 for p in array_players.values() if p == 'X')
        o_count = sum(1 for p in array_players.values() if p == 'O')
        assigned = 'X' if x_count <= o_count else 'O'
        array_players[uid] = assigned
        symbol = '❌' if assigned == 'X' else '⭕'
        await target.reply_text(f"加入成功！你的阵营是 {symbol}")
    else:
        symbol = '❌' if array_players[uid] == 'X' else '⭕'
        await target.reply_text(f"你已在房间中，阵营：{symbol}")

    # 如无棋盘消息则自动创建
    thread_id = _array_get_thread(update)
    if chat_id not in array_board_msg:
        board_str = _array_board_to_text()
        status = _array_status_text(uid)
        bot = target.get_bot() if hasattr(target, 'get_bot') else target.bot
        # 删旧棋盘
        if chat_id in array_board_msg:
            msg_id, _ = array_board_msg[chat_id]
            try: await bot.delete_message(chat_id=chat_id, message_id=msg_id)
            except Exception: pass
        msg = await bot.send_message(chat_id=chat_id, text=f"{board_str}\n\n{status}", message_thread_id=thread_id)
        array_board_msg[chat_id] = (msg.message_id, thread_id)
    else:
        await _array_show_board(target, uid)



async def cmd_array_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """指令 /join 加入阵列房间"""
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    await _do_array_join(update, uid, chat_id)


async def cmd_array_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """指令 /game 显示棋盘（删旧显示新）"""
    chat_id = update.effective_chat.id
    thread_id = _array_get_thread(update)
    # 删旧棋盘
    if chat_id in array_board_msg:
        msg_id, _ = array_board_msg[chat_id]
        try: await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception: pass
    board_str = _array_board_to_text()
    status = _array_status_text(update.effective_user)
    msg = await context.bot.send_message(chat_id=chat_id, text=f"{board_str}\n\n{status}", message_thread_id=thread_id)
    array_board_msg[chat_id] = (msg.message_id, thread_id)


async def cmd_array_stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """指令 /stop 结束游戏"""
    chat_id = update.effective_chat.id
    if chat_id in array_board_msg:
        msg_id, _ = array_board_msg[chat_id]
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
        del array_board_msg[chat_id]
    array_board[:] = [['⬜'] * 9 for _ in range(9)]
    array_players.clear()
    await update.message.reply_text("游戏已结束，棋盘已清除。")


async def _array_show_board(target, uid):
    """更新棋盘消息（编辑已有的，或新建）"""
    board_str = _array_board_to_text()
    status = _array_status_text(uid)
    text = f"{board_str}\n\n{status}"

    # 获取 chat_id
    if hasattr(target, 'message') and target.message:
        chat_id = target.message.chat.id
    elif hasattr(target, 'chat') and target.chat:
        chat_id = target.chat.id
    else:
        return

    thread_id = None
    if hasattr(target, 'message') and target.message:
        thread_id = getattr(target.message, 'message_thread_id', None)

    # 优先编辑现有棋盘消息
    if chat_id in array_board_msg:
        msg_id, _ = array_board_msg[chat_id]
        try:
            await target.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
            return
        except Exception:
            pass

    # 删旧棋盘（编辑失败后残留），再发新棋盘
    if chat_id in array_board_msg:
        old_msg_id, _ = array_board_msg[chat_id]
        try: await target.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
        except Exception: pass
        del array_board_msg[chat_id]
    msg = await target.bot.send_message(chat_id=chat_id, text=text, message_thread_id=thread_id)
    array_board_msg[chat_id] = (msg.message_id, thread_id)


def _array_board_to_text():
    lines = [' 1\uFE0F\u20E3 2\uFE0F\u20E3 3\uFE0F\u20E3 4\uFE0F\u20E3 5\uFE0F\u20E3 6\uFE0F\u20E3 7\uFE0F\u20E3 8\uFE0F\u20E3 9\uFE0F\u20E3']
    row_labels = 'ABCDEFGHI'
    for r in range(9):
        lines.append(row_labels[r] + ''.join(array_board[r]))
    return '\n'.join(lines)


def _array_status_text(uid):
    if not array_players:
        return "房间空，点击「加入房间」开始！点击「旁观模式」查看棋盘。"
    parts = []
    for pid, sym in array_players.items():
        label = '❌' if sym == 'X' else '⭕'
        parts.append(f"{label}")
    status = "  |  ".join(parts)
    if uid is not None and uid in array_players:
        my_sym = '❌' if array_players[uid] == 'X' else '⭕'
        return f"你的阵营：{my_sym}\n{status}"
    return f"旁观中\n{status}"


def _array_check_winner():
    """五子棋胜负判定：任意方向连续 5 子即获胜"""
    directions = [(0, 1), (1, 0), (1, 1), (1, -1)]
    for sym in ('X', 'O'):
        emoji = '❌' if sym == 'X' else '⭕'
        for r in range(9):
            for c in range(9):
                if array_board[r][c] != emoji:
                    continue
                for dr, dc in directions:
                    count = 1
                    rr, cc = r + dr, c + dc
                    while 0 <= rr < 9 and 0 <= cc < 9 and array_board[rr][cc] == emoji:
                        count += 1
                        rr += dr; cc += dc
                    if count >= 5:
                        return sym
    return None



async def error_handler(update, context):
    import traceback; logger.error(f"Error: {context.error}\n{traceback.format_exc()}")
