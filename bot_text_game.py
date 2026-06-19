#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_text_game.py - 文本卡牌池 (发牌/加入/查看)
import random, logging
from bot_config import (
    config, text_game_state,
    _get_tk, _save_text_game_state, _load_text_game_state,
    _get_group_name, _resolve_group,
    waiting_for_input, user_selected_group,
    save_config,
    logger,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

logger_text = logging.getLogger(__name__)


# ========== 工具函数 ==========
def _text_game_key(gid, pools):
    """Generate text_game_state key from group_id and pool names (sorted)."""
    return f"{gid}:{','.join(sorted(pools))}"


def _find_game(gid):
    """Find active text game in a group by group_id prefix."""
    prefix = f"{gid}:"
    for key in text_game_state:
        if key.startswith(prefix):
            return key, text_game_state[key]
    return None, None


def _get_thread(update):
    """Get message_thread_id from update (forum topic support)."""
    msg = update.message if hasattr(update, 'message') and update.message else None
    if msg:
        return getattr(msg, 'message_thread_id', None)
    q = getattr(update, 'callback_query', None)
    if q and q.message:
        return getattr(q.message, 'message_thread_id', None)
    return None


# ========== 加入消息渲染 ==========
def _render_text_game_join(game):
    """Render the join-waiting message text."""
    pools = game['pools']
    lines = []
    for kw in pools:
        pool = game.get('pool_configs', {}).get(kw, {})
        per = pool.get('per_player', '?')
        total = len(pool.get('pool', []))
        lines.append(f"🎴 {kw} · 每人{per}张 · 牌库{total}张")
    lines.append("")
    lines.append("已加入玩家：")
    for uid, pdata in game.get('players', {}).items():
        lines.append(f"· {pdata['name']}")
    if not game.get('players'):
        lines.append("（暂无）")
    return "\n".join(lines)


def _render_text_game_deal(game):
    """Render the deal result message text."""
    pools = game['pools']
    lines = ["🎴 发牌完成", ""]
    for uid, pdata in game.get('players', {}).items():
        lines.append(pdata['name'])
        for kw in pools:
            cards = pdata.get('cards', {}).get(kw, [])
            lines.append(f"【{kw}】")
            lines.append(" ".join(f"[{c}]" for c in cards))
        lines.append("")
    return "\n".join(lines)


# ========== 发牌逻辑 ==========
def _deal_text_cards(game):
    """Deal cards from all pools to all players. Returns (success, error_msg)."""
    players = game.get('players', {})
    if not players:
        return False, "至少需要 1 名玩家"
    
    player_list = list(players.items())
    num_players = len(player_list)
    pool_configs = game.get('pool_configs', {})
    
    # Check each pool has enough cards
    for kw, pool_info in pool_configs.items():
        per = pool_info['per_player']
        total = len(pool_info['pool'])
        need = num_players * per
        if total < need:
            return False, f"「{kw}」牌库不足！需要 {need} 张，只有 {total} 张"
    
    # Deal from each pool
    for kw, pool_info in pool_configs.items():
        per = pool_info['per_player']
        shuffled = pool_info['pool'][:]  # Copy
        random.shuffle(shuffled)
        
        for i, (uid, pdata) in enumerate(player_list):
            pdata.setdefault('cards', {})[kw] = shuffled[i * per : (i + 1) * per]
    
    return True, None


# ========== 命令处理器 ==========
async def cmd_addtext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """添加文本卡牌池: /addtext 关键词 每人张数 卡牌1 卡牌2 ..."""
    user = update.effective_user
    user_id = user.id
    gid = _resolve_group(update, user_id)
    
    # Parse: /addtext 开局 4 剑圣 魔法师 ...
    text = (update.message.text or '').strip()
    parts = text.split(None, 2)  # ["/addtext", "开局", "4 剑圣 魔法师 ..."]
    if len(parts) < 3:
        await update.message.reply_text(
            "格式: /addtext 关键词 每人张数 卡牌1 卡牌2 ...\n"
            "例如: /addtext 职业 4 剑圣 魔法师 刺客 弓箭手"
        )
        return
    
    kw = parts[1]
    rest = parts[2].split()
    if len(rest) < 2:
        await update.message.reply_text("至少需要 2 张卡牌。\n格式: /addtext 关键词 每人张数 卡牌1 卡牌2 ...")
        return
    
    try:
        per_player = int(rest[0])
    except ValueError:
        await update.message.reply_text("每人张数必须是数字。\n格式: /addtext 关键词 每人张数 卡牌1 ...")
        return
    
    if per_player < 1:
        await update.message.reply_text("每人张数至少为 1。")
        return
    
    cards = rest[1:]
    if len(cards) < 2:
        await update.message.reply_text("至少需要 2 张卡牌。")
        return
    
    if per_player > len(cards):
        await update.message.reply_text(f"每人张数({per_player})不能超过卡牌总数({len(cards)})。")
        return
    
    gid_str = str(gid) if gid else '_global'
    config.setdefault('text_keywords', {}).setdefault(gid_str, {})[kw] = {
        'per_player': per_player,
        'pool': cards
    }
    save_config(config)
    waiting_for_input.pop(user_id, None)
    gname = _get_group_name(gid)
    await update.message.reply_text(
        f"✅ [{gname}] 文本卡牌池已添加\n"
        f"关键词: {kw}\n"
        f"每人: {per_player}张\n"
        f"牌库: {' '.join(f'[{c}]' for c in cards)} ({len(cards)}张)\n\n"
        f"使用 /jointext {kw} 加入牌局"
    )


async def cmd_deltext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """删除文本卡牌池: /deltext 关键词"""
    user = update.effective_user
    user_id = user.id
    gid = _resolve_group(update, user_id)
    gid_str = str(gid) if gid else '_global'
    
    args = (update.message.text or '').split()
    if len(args) < 2:
        await update.message.reply_text("格式: /deltext 关键词")
        return
    
    kw = args[1]
    tk = config.get('text_keywords', {}).get(gid_str, {})
    if kw not in tk:
        await update.message.reply_text(f"关键词「{kw}」不存在。")
        return
    
    config['text_keywords'][gid_str].pop(kw, None)
    if not config['text_keywords'][gid_str]:
        config['text_keywords'].pop(gid_str, None)
    save_config(config)
    await update.message.reply_text(f"✅ 已删除文本卡牌池「{kw}」")


async def cmd_listtext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看文本卡牌池列表: /listtext"""
    user = update.effective_user
    user_id = user.id
    gid = _resolve_group(update, user_id)
    gid_str = str(gid) if gid else '_global'
    gname = _get_group_name(gid)
    
    tk = config.get('text_keywords', {}).get(gid_str, {})
    if not tk:
        await update.message.reply_text(f"[{gname}] 暂无文本卡牌池。\n使用 /addtext 添加。")
        return
    
    lines = [f"[{gname}] 文本卡牌池：", ""]
    for kw, info in tk.items():
        per = info.get('per_player', '?')
        total = len(info.get('pool', []))
        lines.append(f"🎴 {kw} · 每人{per}张 · 牌库{total}张")
        lines.append(f"   牌库: {' '.join(f'[{c}]' for c in info.get('pool', []))}")
        lines.append("")
    
    await update.message.reply_text("\n".join(lines))


async def cmd_jointext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """加入牌局: /jointext 职业 道具"""
    user = update.effective_user
    user_id = user.id
    user_name = user.full_name
    
    # Only works in group chats
    chat = update.effective_chat
    if not chat or chat.type not in ('group', 'supergroup'):
        await update.message.reply_text("文本卡牌池只能在群组中使用。")
        return
    
    gid = str(chat.id)
    gid_str = gid
    tid = _get_thread(update)
    
    tk = config.get('text_keywords', {}).get(gid_str, {})
    if not tk:
        await update.message.reply_text("本群还没有文本卡牌池。\n先用 /addtext 添加。")
        return
    
    args = (update.message.text or '').split()[1:]
    if not args:
        # Default: 线索 + 手段 (if both exist)
        if '线索' in tk and '手段' in tk:
            pools = ['线索', '手段']
        else:
            # List available pools
            avail = "\n".join(f"  /jointext {kw}" for kw in tk)
            await update.message.reply_text(f"请指定要加入的牌库：\n{avail}")
            return
    else:
        pools = args
    for kw in pools:
        if kw not in tk:
            await update.message.reply_text(f"牌库「{kw}」不存在。用 /listtext 查看可用牌库。")
            return
    
    # Check if there's an existing game in this group
    existing_key, existing_game = _find_game(gid_str)
    if existing_game:
        if existing_game.get('status') == 'started':
            await update.message.reply_text("牌局已开始，无法加入。")
            return
        # Reuse existing game if same pools, otherwise start fresh
        ex_pools = set(existing_game.get('pools', []))
        if ex_pools != set(pools):
            # Different pools - delete old game message, start fresh
            try:
                old_msg_id = existing_game.get('join_msg_id')
                if old_msg_id:
                    chat_id = int(gid_str)
                    kwargs = {"chat_id": chat_id, "message_id": old_msg_id}
                    old_tid = existing_game.get('join_msg_thread_id')
                    if old_tid:
                        kwargs["message_thread_id"] = old_tid
                    try:
                        await context.bot.delete_message(**kwargs)
                    except Exception:
                        pass
            except Exception:
                pass
            text_game_state.pop(existing_key, None)
            existing_game = None
    
    if not existing_game:
        # Create new game
        game_key = _text_game_key(gid_str, pools)
        game = {
            'status': 'waiting',
            'pools': pools,
            'pool_configs': {kw: dict(tk[kw]) for kw in pools},
            'players': {},
            'join_msg_id': None,
            'join_msg_thread_id': tid,
            'deal_msg_id': None,
            'deal_msg_thread_id': tid,
        }
        text_game_state[game_key] = game
    else:
        game_key = existing_key
        game = existing_game
    
    # Add player
    if str(user_id) in game.get('players', {}):
        # Already joined, just refresh message
        pass
    else:
        game.setdefault('players', {})[str(user_id)] = {
            'name': user_name,
            'cards': {},
        }
    
    _save_text_game_state()
    
    # Send or edit join message
    text = _render_text_game_join(game)
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🙋 加入游戏", callback_data=f'text_join:{game_key}'),
            InlineKeyboardButton("🎲 开始游戏", callback_data=f'text_start:{game_key}'),
        ]
    ])
    
    try:
        old_msg_id = game.get('join_msg_id')
        if old_msg_id:
            chat_id = int(gid_str)
            kwargs = {"chat_id": chat_id, "message_id": old_msg_id, "text": text, "reply_markup": markup}
            if game.get('join_msg_thread_id'):
                kwargs["message_thread_id"] = game['join_msg_thread_id']
            await context.bot.edit_message_text(**kwargs)
        else:
            kwargs = {"chat_id": int(gid_str), "text": text, "reply_markup": markup}
            if tid:
                kwargs["message_thread_id"] = tid
            msg = await context.bot.send_message(**kwargs)
            game['join_msg_id'] = msg.message_id
            game['join_msg_thread_id'] = getattr(msg, 'message_thread_id', None)
            _save_text_game_state()
    except Exception as e:
        logger_text.warning(f"Error sending join message: {e}")
        # Try sending new instead
        kwargs = {"chat_id": int(gid_str), "text": text, "reply_markup": markup}
        if tid:
            kwargs["message_thread_id"] = tid
        msg = await context.bot.send_message(**kwargs)
        game['join_msg_id'] = msg.message_id
        game['join_msg_thread_id'] = getattr(msg, 'message_thread_id', None)
        _save_text_game_state()


async def cmd_showyu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """查看场上卡牌: /showyu"""
    user = update.effective_user
    user_id = user.id
    
    chat = update.effective_chat
    if not chat or chat.type not in ('group', 'supergroup'):
        await update.message.reply_text("/showyu 只能在群组中使用。")
        return
    
    gid_str = str(chat.id)
    tid = _get_thread(update)
    
    game_key, game = _find_game(gid_str)
    if not game:
        await update.message.reply_text("当前没有进行中的牌局。")
        return
    
    if game.get('status') != 'started':
        await update.message.reply_text("牌局尚未开始。")
        return
    
    text = _render_text_game_deal(game)
    kwargs = {"text": text}
    if tid:
        kwargs["message_thread_id"] = tid
    await update.message.reply_text(**kwargs)


async def cmd_stoptext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """结束当前牌局: /stoptext"""
    chat = update.effective_chat
    if not chat or chat.type not in ('group', 'supergroup'):
        await update.message.reply_text("/stoptext 只能在群组中使用。")
        return
    
    gid_str = str(chat.id)
    game_key, game = _find_game(gid_str)
    if not game:
        await update.message.reply_text("当前没有进行中的牌局。")
        return
    
    pools = game.get('pools', [])
    text_game_state.pop(game_key, None)
    _save_text_game_state()
    await update.message.reply_text(f"✅ 牌局已结束 ({', '.join(pools)})。")



# ========== 回调处理器 ==========
async def handle_text_join(query, game_key, game, gid_str, context):
    """处理 [加入游戏] 按钮点击"""
    user = query.from_user
    user_id = user.id
    user_name = user.full_name
    
    if game.get('status') == 'started':
        await query.answer(text="牌局已开始，无法加入", show_alert=True)
        return
    
    players = game.get('players', {})
    if str(user_id) in players:
        await query.answer(text="你已加入", show_alert=True)
        return
    
    players[str(user_id)] = {
        'name': user_name,
        'cards': {},
    }
    _save_text_game_state()
    
    await query.answer(text=f"✅ {user_name} 加入了牌局")
    
    # Refresh join message
    text = _render_text_game_join(game)
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🙋 加入游戏", callback_data=f'text_join:{game_key}'),
            InlineKeyboardButton("🎲 开始游戏", callback_data=f'text_start:{game_key}'),
        ]
    ])
    try:
        await query.edit_message_text(text=text, reply_markup=markup)
    except Exception as e:
        logger_text.warning(f"Error updating join message: {e}")


async def handle_text_start(query, game_key, game, gid_str, context):
    """处理 [开始游戏] 按钮点击 — 发牌"""
    if game.get('status') == 'started':
        await query.answer(text="牌局已开始", show_alert=True)
        return
    
    players = game.get('players', {})
    if not players:
        await query.answer(text="至少需要 1 名玩家加入", show_alert=True)
        return
    
    success, error = _deal_text_cards(game)
    if not success:
        await query.answer(text=error, show_alert=True)
        return
    
    game['status'] = 'started'
    _save_text_game_state()
    
    if not query.message:
        await query.answer(text="消息已失效", show_alert=True)
        return
    
    chat_id = query.message.chat_id
    tid = getattr(query.message, 'message_thread_id', None)
    
    # Edit join message (final state, remove buttons)
    text = _render_text_game_join(game)
    text = text.replace("已加入玩家：", "参与玩家：")
    try:
        await query.edit_message_text(text=text)
    except Exception as e:
        logger_text.warning(f"Error editing join message: {e}")
    
    # Send deal result as new message
    deal_text = _render_text_game_deal(game)
    kwargs = {"chat_id": chat_id, "text": deal_text}
    if tid:
        kwargs["message_thread_id"] = tid
    try:
        msg = await context.bot.send_message(**kwargs)
        game['deal_msg_id'] = msg.message_id
        game['deal_msg_thread_id'] = getattr(msg, 'message_thread_id', None)
        _save_text_game_state()
    except Exception as e:
        logger_text.warning(f"Error sending deal message: {e}")
    
    await query.answer(text="✅ 发牌完成！")


# ========== 初始化 ==========
_load_text_game_state()
