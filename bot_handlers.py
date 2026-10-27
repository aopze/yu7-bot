#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_handlers.py - 消息/命令处理器 (keyword, sticker, emoji, image, inline, counter, return-card)
import html, json, logging, os, random, re, asyncio, subprocess, tempfile, shutil
from io import BytesIO
from PIL import Image
from bot_config import (
    config, sticker_cache, sticker_queue, sticker_discard, inline_cache, inline_queue,
    inline_hand, inline_discard, inline_kept, emoji_cache, emoji_queue, emoji_discard,
    inline_shared_queue, inline_shared_discard,
    img_cache, img_queue, img_discard, img_kept, img_collect, img_collect_kw, img_collect_composite,
    counter_enabled, counter_data, counter_msg,
    waiting_for_input, user_selected_group, user_common_groups, pending_copy,
    _get_sk, _get_ik, _get_ek, _get_set, _get_mode, _set_mode,
    _get_mode_label, _next_mode, _get_random,
    _get_exact,
    _inline_get_set, _inline_get_mode, _inline_set_mode,
    _emoji_get_set, _emoji_get_mode, _emoji_set_mode,
    _inline_get_sort, _inline_set_sort,
    _get_img_kw, _img_kw_key, _img_get_files, _img_get_mode, _img_set_mode, _img_set_stitch,
    _get_comp_kw, _comp_get_groups, _comp_get_mode, _comp_set_mode,
    _img_get_stitch,
    _get_keyword_extras, _add_keyword_extra, _get_extra_pack_name, _set_extra_pack_name,
    _get_extra_pack_video_name, _set_extra_pack_video_name,
    _is_limited_set, _get_group_name, _resolve_group, _refresh_common_groups,
    _filter_blocked_stickers, _pack_emoji, _norm_emoji,
    _inline_is_shared, _inline_set_shared, _get_inline_queue, _get_inline_discard,
    _set_inline_queue, _init_shared_pool, _save_shared_state,
    _build_kw_edit_markup,
    _init_queue, _all_sticker_sets,
    _save_json, _save_hand, _save_inline_state, _save_img_state, _load_json,
    _save_kept, _load_kept,
    _add_keyword_trigger, _remove_keyword_trigger, _get_trigger_kw,
    _save_img_kept, _load_img_kept,
    load_config, save_config,
    CONFIG_FILE, QUEUE_FILE, INLINE_QUEUE_FILE, DISCARD_FILE, HAND_FILE, KEPT_FILE, IMG_KEPT_FILE,
    EMOJI_QUEUE_FILE, EMOJI_DISCARD_FILE, SHARED_QUEUE_FILE, SHARED_DISCARD_FILE, STICKER_DISCARD_FILE,
    IMG_QUEUE_FILE, IMG_DISCARD_FILE,
    _show_main_menu_text, _build_keyword_manage_menu,
    logger,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultCachedSticker, MessageEntity, InputSticker
from telegram import BotCommand
from telegram.ext import ContextTypes

logger_handlers = logging.getLogger(__name__)


def _stitch_images_h(images_data: list) -> BytesIO:
    """Horizontal stitch (thread-safe, runs in executor)."""
    images = [Image.open(BytesIO(d)) for d in images_data]
    total_w = sum(img.width for img in images)
    max_h = max(img.height for img in images)
    stitched = Image.new('RGBA', (total_w, max_h))
    x = 0
    for img in images:
        y = (max_h - img.height) // 2
        stitched.paste(img, (x, y))
        x += img.width
    output = BytesIO()
    stitched.save(output, format='PNG')
    output.seek(0)
    return output


def _stitch_images_v(images_data: list) -> BytesIO:
    """Vertical stitch (thread-safe, runs in executor)."""
    images = [Image.open(BytesIO(d)) for d in images_data]
    total_h = sum(img.height for img in images)
    max_w = max(img.width for img in images)
    stitched = Image.new('RGB', (max_w, total_h))
    y = 0
    for img in images:
        x = (max_w - img.width) // 2
        stitched.paste(img, (x, y))
        y += img.height
    output = BytesIO()
    stitched.save(output, format='JPEG', quality=85)
    output.seek(0)
    return output

async def start(update, context):
    """Handle /start — show main admin menu."""
    # 方舟战棋深链回传（/start score:层_杀）交给 bot_rank 处理，不展示管理菜单
    if context.args and (context.args[0].startswith("score:") or context.args[0].startswith("name:")):
        from bot_rank import handle_start_param
        await handle_start_param(update, context, context.args[0])
        return
    user = update.effective_user; user_id = user.id
    group_id = _resolve_group(update, user_id)
    chat = update.effective_chat
    if chat and chat.type == 'private' and user_id not in user_common_groups:
        await _refresh_common_groups(context.bot, user_id)
    text, markup = _show_main_menu_text(user, group_id)
    await update.message.reply_text(text, reply_markup=markup)

async def cmd_yu(update, context):
    """Handle /yu — quick jump to keyword edit or show main menu."""
    user = update.effective_user; user_id = user.id
    group_id = _resolve_group(update, user_id)

    chat = update.effective_chat
    if chat and chat.type == 'private' and user_id not in user_common_groups:
        await _refresh_common_groups(context.bot, user_id)

    # Quick jump: /yu 关键词 → show keyword edit page
    if update.message and update.message.text:
        parts = update.message.text.strip().split(None, 1)
        if len(parts) >= 2:
            kw = parts[1].strip()
            gid_str = str(group_id)
            ik = config.get('inline_sticker_keywords', {}).get(gid_str, {})
            sk = config.get('sticker_keywords', {}).get(gid_str, {})
            ek = config.get('emoji_keywords', {}).get(gid_str, {})
            img_kws = config.get('image_keywords', {}).get(gid_str, {})
            comp_kws = config.get('composite_keywords', {}).get(gid_str, {})

            if kw in ik:
                sn = ik[kw].get('set', '') if isinstance(ik[kw], dict) else ik[kw]
                waiting_for_input[user_id] = f"replace_inline:{kw}"
                await update.message.reply_text(
                    f"[{html.escape(_get_group_name(group_id))}] <b>{html.escape(kw)}</b> -> {html.escape(sn)}\n发送关键词改名，或发送链接替换.\n/cancel 取消.",
                    reply_markup=_build_kw_edit_markup(kw, 'inline', group_id), parse_mode='HTML'); return
            elif kw in sk:
                waiting_for_input[user_id] = f"replace:{kw}"
                await update.message.reply_text(
                    f"[{html.escape(_get_group_name(group_id))}] <b>{html.escape(kw)}</b> -> {html.escape(_get_set(kw, group_id))}\n发送关键词改名，或发送链接替换.",
                    reply_markup=_build_kw_edit_markup(kw, 'sticker', group_id), parse_mode='HTML'); return
            elif kw in ek:
                sn = ek[kw].get('set', '') if isinstance(ek[kw], dict) else ek[kw]
                waiting_for_input[user_id] = f"replace_emoji:{kw}"
                await update.message.reply_text(
                    f"[{html.escape(_get_group_name(group_id))}] <b>{html.escape(kw)}</b> -> {html.escape(sn)}\n发送关键词改名，或发送链接替换.\n/cancel 取消.",
                    reply_markup=_build_kw_edit_markup(kw, 'emoji', group_id), parse_mode='HTML'); return
            elif kw in img_kws:
                waiting_for_input[user_id] = f"replace_image:{kw}"
                await update.message.reply_text(
                    f"[{html.escape(_get_group_name(group_id))}] <b>{html.escape(kw)}</b> ({len(_img_get_files(kw, group_id))}张)\n发送关键词改名，/cancel 取消.",
                    reply_markup=_build_kw_edit_markup(kw, 'image', group_id), parse_mode='HTML'); return
            elif kw in comp_kws:
                waiting_for_input[user_id] = f"replace_composite:{kw}"
                groups = _comp_get_groups(kw, group_id); total = sum(len(g) for g in groups)
                await update.message.reply_text(
                    f"[{html.escape(_get_group_name(group_id))}] <b>{html.escape(kw)}</b> ({total}张/{len(groups)}组)\n发送关键词改名，/cancel 取消.",
                    reply_markup=_build_kw_edit_markup(kw, 'composite', group_id), parse_mode='HTML'); return
            else:
                await update.message.reply_text(f"未找到关键词 '{kw}'"); return

    text, markup = _build_keyword_manage_menu(group_id)
    await update.message.reply_text(text, reply_markup=markup)


async def cmd_delemo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """从 emoji 关键词删除一个 emoji: /del 关键词 😓"""
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    parts = text.split(None, 2)
    if len(parts) < 2:
        await update.message.reply_text("用法: /del 关键词 😓\n删除牌库中的一个指定emoji。")
        return
    kw = parts[1].strip().lower()
    # Extract custom emoji entities
    entities = update.message.entities or []
    target_eids = []
    for ent in entities:
        if ent.type == "custom_emoji" and ent.custom_emoji_id:
            target_eids.append(ent.custom_emoji_id)
    if not target_eids:
        await update.message.reply_text("请在命令中带上要删除的自定义emoji。\n用法: /del 关键词 😓")
        return
    # Search emoji keywords
    for gid_k, kws in config.get('emoji_keywords', {}).items():
        for keyword, v in kws.items():
            if keyword.lower() not in kw: continue
            sn = v.get('set', '') if isinstance(v, dict) else v
            if not sn: continue
            # Remove one instance of each specified emoji from queue
            removed = 0
            queue = emoji_queue.get(sn, [])
            for eid in target_eids:
                if eid in queue:
                    queue.remove(eid)  # removes first occurrence
                    removed += 1
            if removed:
                emoji_queue[sn] = queue
                # Clean cache if no more instances anywhere
                for eid in target_eids:
                    in_queue = eid in queue
                    in_discard = any(eid in cards for cards in emoji_discard.get(sn, {}).values())
                    if eid in emoji_cache.get(sn, {}) and not in_queue and not in_discard:
                        del emoji_cache[sn][eid]
                _save_json(EMOJI_QUEUE_FILE, emoji_queue)
                await update.message.reply_text(
                    f"✅ 已从「{keyword}」删除 {removed} 个emoji\n剩余牌库 {len(queue)} 张"
                )
            else:
                await update.message.reply_text(f"「{keyword}」牌库中没有找到指定的emoji。")
            return
    await update.message.reply_text(f"未找到emoji关键词「{kw}」")


async def cmd_keep(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """展示内联包保留的贴纸: 回复内联贴纸发送 /keep"""
    user_id = update.effective_user.id
    reply = update.message.reply_to_message
    if not reply or not reply.sticker or not reply.sticker.file_id:
        await update.message.reply_text("请回复一条内联贴纸消息来查看保留区。\n用法: 回复内联贴纸 + /keep")
        return
    fid = reply.sticker.file_id
    # Find which pack this sticker belongs to
    target_sn = None
    for sn, stickers in inline_cache.items():
        if fid in stickers:
            target_sn = sn; break
    if not target_sn:
        for sn, users in inline_kept.items():
            if (user_id in users and fid in users[user_id]) or (0 in users and fid in users[0]):
                target_sn = sn; break
    if not target_sn:
        await update.message.reply_text("该贴纸不在任何内联牌库中。")
        return
    kept = inline_kept.get(target_sn, {}).get(user_id, [])
    blocked = inline_kept.get(target_sn, {}).get(0, [])
    all_kept = kept + blocked
    if not all_kept:
        await update.message.reply_text(f"该内联包没有保留的贴纸。")
        return
    # Send kept stickers one by one
    for fid_item in all_kept:
        try:
            kwargs = {"chat_id": update.effective_chat.id, "sticker": fid_item}
            tid = getattr(update.message, 'message_thread_id', None)
            if tid: kwargs["message_thread_id"] = tid
            await context.bot.send_sticker(**kwargs)
        except Exception as se:
            logger.warning(f"Keep display fail: {se}")
    label = f"保留 {len(kept)} 张" + (f" + ⛔屏蔽 {len(blocked)} 张" if blocked else "")
    await update.message.reply_text(f"📌 {label}")


_HELP_PLAIN = (
    "关键词使用方式:\n"
    "关键词 N: 抽取N张卡牌\n"
    "关键词 N-: 从弃牌堆回收N张入牌库(内联/Emoji)\n"
    "关键词 0: 全部弃牌洗入牌库\n"
    "关键词 0d: 牌库完全重置为初始状态\n"
    "/refresh 关键词: 从贴纸包/Emoji包同步最新内容\n"
    "关键词 Nd: 明牌抽取N张卡牌\n"
    "关键词 Nw: 展示牌堆顶N张卡牌\n"
    "关键词 Nf / N! / N！: 弃置牌堆顶N张卡牌入弃牌区\n"
    "d / dN: 回复贴纸 d 加1张手牌，dN 加N张相同的牌（在关键词里入对应包，否则入手牌）；回复图片 d 回收至牌库\n"
    "d N%: 回复贴纸/图片/视频/GIF，按百分比缩放后入库（如 d 72%、d 112%）\n"
    "回复图片/视频/GIF + d: 先转成贴纸再加入手牌\n"
    "f: 回复图片 f 弃置（跳过后再抽）\n"
    "数字-数字-数字: 连续打出多张卡牌\n"
    "数字-数字-数字/: 连续明牌打出多张卡牌\n"
    "数字~数字: 打出序号连贯的卡牌"
)

_HELP_RICH = """## 🎴 卡牌机器人 · 用法速查

### 抽牌
- `关键词 N` — 抽取 N 张卡牌
- `关键词 Nd` — 明牌抽取 N 张卡牌
- `关键词 Nw` — 展示牌堆顶 N 张卡牌

### 回收 / 弃置
- `关键词 N-` — 从弃牌堆回收 N 张入牌库（内联 / Emoji）
- `关键词 0` — 全部弃牌洗入牌库
- `关键词 0d` — 牌库完全重置为初始状态
- `关键词 Nf` / `N!` / `N！` — 弃置牌堆顶 N 张卡牌入弃牌区

### 出牌
- `数字-数字-数字` — 连续打出多张卡牌
- `数字-数字-数字/` — 连续明牌打出多张卡牌
- `数字~数字` — 打出序号连贯的卡牌

### 回复用法
- 回复贴纸 + `d` / `dN` — 加 1 / N 张到手牌（在关键词里则入对应包）
- 回复图片 + `d` — 回收这张图至牌库
- 回复图片 + `f` — 弃置这张图（跳过后再抽）
- 回复图片 / 视频 / GIF + `d` — 先做成贴纸再加入手牌
- 回复贴纸 / 图片 / 视频 / GIF + `d N%` — 按百分比缩放后入库（如 `d 72%`、`d 112%`）

### 管理
- `/refresh 关键词` — 从贴纸包 / Emoji 包同步最新内容
- `/keep`（回复内联贴纸） — 查看保留区

> 百分比 ≤100% 用透明背景补齐，>100% 从中心裁剪。动态 tgs 贴纸不支持缩放。"""


async def help_command(update, context):
    """/help：优先 Rich Message（标题+列表+引用），失败自动降级普通文本。"""
    try:
        from bot_rich import send_rich
        if await send_rich(context.bot, update.effective_chat.id, _HELP_RICH,
                           thread_id=getattr(update.effective_message, 'message_thread_id', None)):
            return
    except Exception as e:
        logger.warning(f"rich help failed: {e}")
    await update.message.reply_text(_HELP_PLAIN)


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """刷新内联关键词缓存: /refresh 关键词"""
    if not update.message or not update.message.text: return
    text = update.message.text.strip()
    parts = text.split(None, 1)
    if len(parts) < 2:
        await update.message.reply_text("用法: /refresh 关键词\n如 /refresh 抽牌")
        return
    kw = parts[1].strip().lower()
    # Search inline keywords
    found = False
    for gid_k, kws in config.get('inline_sticker_keywords', {}).items():
        for keyword, v in kws.items():
            if keyword.lower() != kw: continue
            sn = v.get('set', '') if isinstance(v, dict) else v
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                new_stickers = _filter_blocked_stickers(sn, ss.stickers)
                old_count = len(inline_cache.get(sn, []))
                inline_cache[sn] = new_stickers
                # Merge extras
                extra_stickers = _get_keyword_extras(keyword, gid_k)
                for f in extra_stickers:
                    if f not in inline_cache[sn]:
                        inline_cache[sn].append(f)
                new_count = len(inline_cache[sn])
                from telegram import error as tg_error
                found = True
                # Append new stickers to existing queue
                old_ids = set(inline_queue.get(sn, []))
                new_only = [f for f in new_stickers if f not in old_ids]
                if new_only:
                    random.shuffle(new_only)
                    inline_queue.setdefault(sn, []).extend(new_only)
                added = len(new_only)
                await update.message.reply_text(
                    f"已刷新「{keyword}」\n"
                    f"贴纸包: {old_count}→{new_count}张  |  新增 {added}张入牌库"
                    + (f"  |  收录 {len(extra_stickers)}张" if extra_stickers else "")
                )
            except tg_error.TelegramError as e:
                await update.message.reply_text(f"刷新失败: {e}")
            except Exception as e:
                logger.warning(f"Refresh error: {e}")
                await update.message.reply_text(f"刷新出错: {e}")
            return
    if not found:
        # Try emoji keywords
        for gid_k, kws in config.get('emoji_keywords', {}).items():
            for keyword, v in kws.items():
                if keyword.lower() != kw: continue
                sn = v.get('set', '') if isinstance(v, dict) else v
                try:
                    ss = await context.bot.get_sticker_set(name=sn)
                    emoji_map = {s.custom_emoji_id: s.emoji for s in ss.stickers
                                 if s.type == 'custom_emoji' and s.custom_emoji_id and s.emoji}
                    old_count = len(emoji_cache.get(sn, {}))
                    emoji_cache[sn] = emoji_map
                    new_count = len(emoji_map)
                    emoji_queue[sn] = list(emoji_map.keys())
                    random.shuffle(emoji_queue[sn])
                    found = True
                    await update.message.reply_text(
                        f"已刷新 Emoji「{keyword}」\n"
                        f"表情包: {old_count}→{new_count}个"
                    )
                except Exception as e:
                    await update.message.reply_text(f"刷新 Emoji 失败: {e}")
                return
    if not found:
        await update.message.reply_text(f"未找到关键词「{kw}」")
async def show_sticker_keywords(update, context):
    """/liststicker：优先 Rich Message 表格，失败降级纯文本列表。"""
    user_id = update.effective_user.id
    group_id = _resolve_group(update, user_id)
    sk = _get_sk(group_id)
    if not sk: return await update.message.reply_text('无关键词')
    plain = "\n".join(f"  {k} -> {_get_set(k, group_id)}" for k in sk)
    try:
        from bot_rich import send_rich, md_table
        gname = _get_group_name(group_id)
        rows = [[f"`{k}`", f"`{_get_set(k, group_id)}`"] for k in sk]
        markdown = f"## 📚 关键词列表 · {gname}\n\n" + md_table(['关键词', '贴纸包'], rows)
        if await send_rich(context.bot, update.effective_chat.id, markdown,
                           thread_id=getattr(update.effective_message, 'message_thread_id', None)):
            return
    except Exception as e:
        logger.warning(f"rich liststicker failed: {e}")
    await update.message.reply_text(plain)

async def add_sticker_keyword(update, context):
    user_id = update.effective_user.id
    if user_id not in config.get('admin_ids',[]): return await update.message.reply_text('仅管理员')
    if len(context.args) < 2: return await update.message.reply_text('/addsticker <关键词> <包名> [emoji]')
    kw, sn = context.args[0], context.args[1]
    emoji_filter = _norm_emoji(context.args[2]) if len(context.args) >= 3 else None
    group_id = user_selected_group.get(user_id, '_global')
    gid = str(group_id)
    try:
        ss = await context.bot.get_sticker_set(name=sn)
        allowed = _filter_blocked_stickers(sn, ss.stickers)
        if emoji_filter:
            from bot_config import _filtered_sn, _pack_emoji
            cache_sn = _filtered_sn(sn, emoji_filter)
            em = _pack_emoji.get(sn, {})
            filtered = [fid for fid in allowed if em.get(fid, '') == emoji_filter]
            logger.info(f"EMOJI_ADDSTICKER_DEBUG: sn={sn} filter={repr(emoji_filter)} total={len(allowed)} matched={len(filtered)} emojis={list(set(em.values()))}")
            sticker_cache[cache_sn] = filtered; _init_queue(cache_sn, sticker_cache, sticker_queue)
            cfg = {"set": sn, "mode": "sequential", "exact": True, "emoji_filter": emoji_filter}
        else:
            sticker_cache[sn] = allowed; _init_queue(sn, sticker_cache, sticker_queue)
            cfg = {"set": sn, "mode": "sequential", "exact": True}
        config.setdefault('sticker_keywords',{}).setdefault(gid,{})[kw] = cfg
        save_config(config)
        gname = _get_group_name(group_id)
        actual = len(filtered) if emoji_filter else len(allowed)
        extra = f" (只看{emoji_filter} → {actual}/{len(allowed)}张)" if emoji_filter else ""
        await update.message.reply_text(f"添加成功! [{gname}] {kw} -> {sn} ({actual}张){extra}")
    except Exception as e: await update.message.reply_text(f"失败: {e}")


async def cmd_addin(update, context):
    """Add inline keyword from group: /addin 关键词 [emoji] 链接"""
    user_id = update.effective_user.id
    if user_id not in config.get("admin_ids",[]): return await update.message.reply_text("仅管理员")
    if len(context.args) < 2: return await update.message.reply_text("/addin <关键词> [emoji] <链接>")
    chat = update.effective_chat
    gid = str(chat.id) if chat and chat.type in ("group","supergroup") else str(user_selected_group.get(user_id, "_global"))
    text = " ".join(context.args)
    parts = text.split(maxsplit=1)
    if len(parts) < 2: return await update.message.reply_text("/addin <关键词> [emoji] <链接>")
    kw, rest = parts[0], parts[1]
    emoji_filter = None
    first_char = rest[0] if rest else ""
    after = rest[1:].strip()
    if first_char and ord(first_char) > 127 and after:
        emoji_filter = _norm_emoji(first_char)
        rest = after
    m = re.search(r"add(?:stickers|emoji)/([a-zA-Z0-9_]+)", rest)
    sn = m.group(1) if m else rest.strip().split("/")[-1].split("?")[0]
    if not sn: return await update.message.reply_text("无法提取包名")
    try:
        ss = await context.bot.get_sticker_set(name=sn)
        allowed = _filter_blocked_stickers(sn, ss.stickers)
        if emoji_filter:
            from bot_config import _filtered_sn, _pack_emoji
            cache_sn = _filtered_sn(sn, emoji_filter)
            em = _pack_emoji.get(sn, {})
            filtered = [fid for fid in allowed if em.get(fid, "") == emoji_filter]
            logger.info(f"EMOJI_ADDIN_DEBUG: sn={sn} filter={repr(emoji_filter)} total={len(allowed)} matched={len(filtered)} emojis={list(set(em.values()))}")
            inline_cache[cache_sn] = filtered; _init_queue(cache_sn, inline_cache, inline_queue)
            inline_hand[cache_sn] = {}; _save_hand()
            cfg = {"set": sn, "mode": "limited", "exact": True, "sort": False, "emoji_filter": emoji_filter}
            actual, total = len(filtered), len(allowed)
        else:
            inline_cache[sn] = allowed; _init_queue(sn, inline_cache, inline_queue)
            inline_hand[sn] = {}; _save_hand()
            cfg = {"set": sn, "mode": "limited", "exact": True, "sort": False}
            actual, total = len(allowed), len(allowed)
        config.setdefault("inline_sticker_keywords",{}).setdefault(gid,{})[kw] = cfg
        save_config(config)
        gname = _get_group_name(gid)
        extra = f" (只看{emoji_filter} -> {actual}/{total}张)" if emoji_filter else ""
        await update.message.reply_text(f"内联添加成功! [{gname}] {kw} -> {sn} ({actual}张){extra}")
    except Exception as e: await update.message.reply_text(f"失败: {e}")

async def cancel(update, context):
    uid = update.effective_user.id
    if uid in waiting_for_input:
        # If collecting images, save them
        if waiting_for_input[uid] == "collect_image" and uid in img_collect_kw:
            kw = img_collect_kw.pop(uid)
            files = img_collect.pop(uid, [])
            composite = img_collect_composite.pop(uid, [])
            gid = str(user_selected_group.get(uid, '_global'))
            if composite:
                # Composite mode: append current group if not empty
                if files:
                    composite.append(files)
                config.setdefault('composite_keywords', {}).setdefault(gid, {})[kw] = {
                    "groups": composite, "mode": "limited", "exact": True
                }
                save_config(config)
                total = sum(len(g) for g in composite)
                gname = _get_group_name(gid)
                await update.message.reply_text(
                    f"拼接图片添加完成! [{gname}] {kw}\n"
                    f"共 {len(composite)} 组, {total} 张\n"
                    f"每次抽取: 每组1张 → 拼接为1张图"
                )
            elif files:
                key = _img_kw_key(gid, kw)
                config.setdefault('image_keywords', {}).setdefault(gid, {})[kw] = {"files": files, "mode": "limited", "exact": True}
                save_config(config)
                img_cache[key] = list(files); _init_queue(key, img_cache, img_queue)
                gname = _get_group_name(gid)
                await update.message.reply_text(f"图片添加完成! [{gname}] {kw} ({len(files)}张)")
            else:
                img_collect_kw.pop(uid, None)
                await update.message.reply_text(f"未收到图片，已取消 '{kw}'")
        elif waiting_for_input[uid] == "collect_image_kw":
            img_collect.pop(uid, None); img_collect_kw.pop(uid, None)
            await update.message.reply_text('已取消')
        waiting_for_input.pop(uid, None)
    else:
        await update.message.reply_text('无操作')


async def cmd_merge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle inline merge mode: /merge → 切换@bot内联包显示模式"""
    uid = update.effective_user.id
    cur = _inline_merge_mode.get(uid, True)
    new = not cur
    _inline_merge_mode[uid] = new
    if new:
        await update.message.reply_text("🔀 合并模式：@bot 显示所有内联包的手牌")
    else:
        await update.message.reply_text("📌 单包模式：@bot 只显示最常用内联包的手牌")


async def cmd_restart(update, context):
    """重启 bot: /restart (仅管理员)"""
    uid = update.effective_user.id
    if uid not in config.get('admin_ids', []):
        await update.message.reply_text("仅管理员可操作")
        return
    await update.message.reply_text("🔄 正在重启...")
    import os, asyncio
    # Give the message time to send, then exit
    await asyncio.sleep(0.5)
    os._exit(0)


async def cmd_gap(update, context):
    """拼接模式分隔符: /gap"""
    uid = update.effective_user.id
    if uid not in waiting_for_input or waiting_for_input[uid] != "collect_image":
        await update.message.reply_text("/gap 仅在添加拼接图片时使用（/addimg 收集图片后）。")
        return
    current = img_collect.get(uid, [])
    if current:
        img_collect_composite.setdefault(uid, []).append(current)
        img_collect[uid] = []
        total_groups = len(img_collect_composite[uid])
        total_imgs = sum(len(g) for g in img_collect_composite[uid])
        await update.message.reply_text(
            f"已保存第 {total_groups} 组 ({len(current)} 张)。 "
            f"共 {total_groups} 组 {total_imgs} 张。\n"
            f"继续发送下一组图片，或 /cancel 完成。"
        )
    else:
        await update.message.reply_text("当前组没有图片。请先发送图片再输入 /gap。")

async def cmd_addemoji(update, context):
    """Add emoji keyword via pack link: /emo <keyword> <pack_link>"""
    text = update.message.text
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return await update.message.reply_text("用法: /emo <关键词> <emoji包链接>\n例如: /emo 抽牌 https://t.me/addemoji/MyPack")
    remaining = parts[1].strip().split(maxsplit=1)
    if len(remaining) < 2:
        return await update.message.reply_text("用法: /emo <关键词> <emoji包链接>")
    kw, link = remaining[0], remaining[1]
    m = re.search(r'addemoji/([a-zA-Z0-9_]+)', link)
    sn = m.group(1) if m else link.strip().split('/')[-1].split('?')[0]
    if not sn: return await update.message.reply_text('无法提取 emoji 包名')
    user_id = update.effective_user.id
    chat = update.effective_chat
    gid = str(chat.id) if chat and chat.type in ('group', 'supergroup') else str(user_selected_group.get(user_id, '_global'))
    try:
        ss = await context.bot.get_sticker_set(name=sn)
        emoji_map = {s.custom_emoji_id: s.emoji for s in ss.stickers if s.type == 'custom_emoji' and s.custom_emoji_id and s.emoji}
        if not emoji_map:
            return await update.message.reply_text(f"包 '{sn}' 中没有自定义 Emoji")
        config.setdefault('emoji_keywords', {}).setdefault(gid, {})[kw] = {"set": sn, "mode": "random", "exact": True}
        save_config(config)
        emoji_cache[sn] = emoji_map; _init_queue(sn, emoji_cache, emoji_queue)
        gname = _get_group_name(gid)
        await update.message.reply_text(f"Emoji添加成功! [{gname}] {kw} -> {sn} ({len(emoji_map)}个)")
    except Exception as e: await update.message.reply_text(f"失败: {e}")

async def cmd_addimg(update, context):
    """Start image keyword collection: /addimg"""
    uid = update.effective_user.id
    if update.effective_chat.type in ('group', 'supergroup'):
        return await update.message.reply_text("请在私聊中使用 /addimg")
    waiting_for_input[uid] = "collect_image_kw"
    await update.message.reply_text("发送图片关键词名称:\n/cancel 取消")

async def cmd_delyu(update, context):
    """Universal keyword deletion: /delyu <关键词> — works for all keyword types."""
    parts = update.message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return await update.message.reply_text("用法: /delyu <关键词>")
    kw = parts[1].strip()
    chat = update.effective_chat
    gid = str(chat.id) if chat and chat.type in ('group', 'supergroup') else str(user_selected_group.get(update.effective_user.id, '_global'))
    search_gids = [gid] if gid == '_global' else [gid, '_global']

    types = [
        ('贴纸', 'sticker_keywords', None),
        ('内联', 'inline_sticker_keywords', None),
        ('Emoji', 'emoji_keywords', None),
        ('图片', 'image_keywords', None),
        ('拼接', 'composite_keywords', None),
        ('文本', 'text_keywords', None),
    ]
    for label, conf_key, _ in types:
        for sgid in search_gids:
            kws = config.get(conf_key, {}).get(sgid, {})
            if kw in kws:
                v = kws.pop(kw)
                config.setdefault(conf_key, {})[sgid] = kws
                save_config(config)
                gname = _get_group_name(sgid)
                await update.message.reply_text(f"已删除 {label} 关键词 '{kw}' [{gname}]")
                return
    await update.message.reply_text(f"关键词 '{kw}' 不存在")

async def cmd_counter(update, context):
    """启用/禁用计数器模式: /counter"""
    chat = update.effective_chat
    tid = getattr(update.message, 'message_thread_id', None)
    key = f"{chat.id}:{tid or 0}"
    if counter_enabled.get(key):
        counter_enabled.pop(key)
        counter_data.pop(key, None); counter_msg.pop(key, None)
        await update.message.reply_text("计数器已关闭")
    else:
        counter_enabled[key] = True
        await update.message.reply_text("计数器已启用\n格式: #关键词 [±]数字\n#生命 4  设值\n#生命 +2  加2\n#生命 -3  减3")

async def handle_counter(update, context):
    """处理计数器: #关键词 [±]数字  — 有±则加减，无则设值"""
    msg = update.message
    if not msg or not msg.text: return
    chat = update.effective_chat
    tid = getattr(msg, 'message_thread_id', None)
    key = f"{chat.id}:{tid or 0}"
    if not counter_enabled.get(key): return

    text = msg.text.strip()
    m = re.match(r'^#(\S+)\s+([+-]?\d+)$', text)
    if not m: return
    kw, num = m.group(1), m.group(2)
    uid = update.effective_user.id
    data = counter_data.setdefault(key, {}).setdefault(uid, {})

    # 加减 / 设值
    if num.startswith('+') or num.startswith('-'):
        data[kw] = data.get(kw, 0) + int(num)
    else:
        data[kw] = int(num)

    parts = [f"[{k} {v}]" for k, v in data.items()]
    display = " ".join(parts)

    # 构建显示
    parts = [f"[{k} {v}]" for k, v in data.items()]
    display = " ".join(parts)

    # 编辑或发送
    prev_msg = counter_msg.get(key, {}).get(uid)
    if prev_msg:
        try:
            await context.bot.edit_message_text(
                chat_id=chat.id, message_id=prev_msg, text=display)
            return
        except Exception:
            pass
    sent = await msg.reply_text(display)
    counter_msg.setdefault(key, {})[uid] = sent.message_id

# ========== Bot group membership tracker ==========
async def my_chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track Bot being added to / removed from groups."""
    chat = update.effective_chat
    if chat.type not in ['group', 'supergroup']:
        return

    new = update.my_chat_member.new_chat_member
    gid = str(chat.id)
    known = config.setdefault('known_groups', {})

    if new.status in ['member', 'administrator']:
        known[gid] = chat.title or f"群组{gid}"
        logger.info(f"Bot added to group: {chat.title} ({gid})")
        save_config(config)
    elif new.status in ['left', 'kicked'] and gid in known:
        del known[gid]
        logger.info(f"Bot removed from group: {chat.title} ({gid})")
        save_config(config)

# ========== Keyword handler (group-aware) ==========
async def handle_keyword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user = update.effective_user; text = update.message.text; user_id = user.id
    # Skip bot commands (handled by CommandHandlers)
    if text.startswith('/'): return

    # === 计数器模式优先 ===
    chat = update.effective_chat
    tid = getattr(update.message, 'message_thread_id', None)
    key = f"{chat.id}:{tid or 0}"
    if counter_enabled.get(key):
        try:
            data = counter_data.get(key, {}).get(user_id, {})
            if data:
                # 多个 #关键词 → 排序置顶
                multi_match = re.match(r'^#\S+(?:\s+#\S+)+$', text.strip())
                if multi_match:
                    kws = re.findall(r'#(\S+)', text.strip())
                    seen = set()
                    ordered = [(kw, data[kw]) for kw in kws if kw in data and not (seen.add(kw) or False)]
                    rest = [(k, v) for k, v in data.items() if k not in seen]
                    parts = [f"[{k} {v}]" for k, v in ordered + rest]
                    await context.bot.send_message(chat_id=chat.id, text=" ".join(parts), message_thread_id=tid)
                    return

                # 仅 #关键词 无数字 → 查看计数表
                view_match = re.match(r'^#(\S+)$', text.strip())
                if view_match:
                    kw = view_match.group(1)
                    if kw in data:
                        parts = [f"[{k} {v}]" for k, v in data.items()]
                        await context.bot.send_message(chat_id=chat.id, text=" ".join(parts), message_thread_id=tid)
                        return

            m = re.match(r'^#(\S+)\s+([+-]?\d+)$', text.strip())
            if m:
                kw, num = m.group(1), m.group(2)
                data = counter_data.setdefault(key, {}).setdefault(user_id, {})
                if num.startswith('+') or num.startswith('-'):
                    data[kw] = data.get(kw, 0) + int(num)
                else:
                    data[kw] = int(num)
                parts = [f"[{k} {v}]" for k, v in data.items()]
                display = " ".join(parts)
                # 删除旧计数表
                prev_msg = counter_msg.get(key, {}).get(user_id)
                if prev_msg:
                    try: await context.bot.delete_message(chat_id=chat.id, message_id=prev_msg)
                    except Exception: pass
                # 发送新计数表（非回复）
                sent = await context.bot.send_message(chat_id=chat.id, text=display, message_thread_id=tid)
                counter_msg.setdefault(key, {})[user_id] = sent.message_id
                return
        except Exception as e:
            logger.warning(f"Counter error: {e}")
        # Non-counter text in counter mode: fall through to keyword handling

    # Input interception (same as before)
    if user_id in waiting_for_input:
        mode = waiting_for_input.pop(user_id)

        # Emoji keyword add via pack link
        if mode.startswith("add_emoji:"):
            chat = update.effective_chat
            gid = str(chat.id) if chat and chat.type in ('group', 'supergroup') else str(user_selected_group.get(user_id, '_global'))
            kw = mode.split(":", 1)[1]
            text = text.strip()
            # If no keyword yet (first prompt), parse both keyword and link
            if not kw:
                parts = text.strip().split(maxsplit=1)
                if len(parts) < 2:
                    waiting_for_input[user_id] = mode
                    return await update.message.reply_text('格式: <关键词> <emoji包链接>\n例如: 抽牌 https://t.me/addemoji/MyPack\n/cancel 取消')
                kw, link = parts[0], parts[1]
                m = re.search(r'addemoji/([a-zA-Z0-9_]+)', link)
                sn = m.group(1) if m else link.strip().split('/')[-1].split('?')[0]
            else:
                m = re.search(r'addemoji/([a-zA-Z0-9_]+)', text)
                sn = m.group(1) if m else text.strip().split('/')[-1].split('?')[0]
            if not sn:
                waiting_for_input[user_id] = mode
                return await update.message.reply_text('请发送 emoji 包链接 (如 https://t.me/addemoji/PackName)\n/cancel 取消')
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                emoji_map = {s.custom_emoji_id: s.emoji for s in ss.stickers if s.type == 'custom_emoji' and s.custom_emoji_id and s.emoji}
                if not emoji_map:
                    return await update.message.reply_text(f"包 '{sn}' 中没有自定义 Emoji")
                config.setdefault('emoji_keywords', {}).setdefault(gid, {})[kw] = {"set": sn, "mode": "random", "exact": True}
                save_config(config)
                emoji_cache[sn] = emoji_map; _init_queue(sn, emoji_cache, emoji_queue)
                gname = _get_group_name(gid)
                await update.message.reply_text(f"Emoji添加成功! [{gname}] {kw} -> {sn} ({len(emoji_map)}个)")
            except Exception as e: await update.message.reply_text(f"失败: {e}")
            return

        gid = str(user_selected_group.get(user_id, '_global'))

        if mode.startswith("replace:"):
            tk = mode.split(":",1)[1]
            # Smart detect: link → replace sticker set; keyword → replace keyword name
            if re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', text) or text.strip().startswith('https://t.me/'):
                m = re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', text)
                sn = m.group(1) if m else text.strip().split('/')[-1].split('?')[0]
                if not sn: return await update.message.reply_text('无法提取包名')
                try:
                    ss = await context.bot.get_sticker_set(name=sn); sticks = [s.file_id for s in ss.stickers]
                    old = _get_set(tk, gid)
                    config['sticker_keywords'].setdefault(gid,{})[tk]['set'] = sn; save_config(config)
                    sticker_cache[sn] = sticks; _init_queue(sn, sticker_cache, sticker_queue)
                    if old and old not in {v.get('set','') if isinstance(v,dict) else v for v in config.get('sticker_keywords',{}).get(gid,{}).values()}:
                        all_sets = set()
                        for gid2, kws in config.get('sticker_keywords',{}).items():
                            for v in kws.values():
                                all_sets.add(v.get('set','') if isinstance(v,dict) else v)
                        if old not in all_sets:
                            sticker_cache.pop(old,None); sticker_queue.pop(old,None)
                    await update.message.reply_text(f"替换成功! {tk} -> {sn} ({len(sticks)}张)")
                except Exception as e: await update.message.reply_text(f"失败: {e}")
            else:
                # Replace keyword name
                new_kw = text.strip().split()[0]
                if not new_kw or len(new_kw) > 20: return await update.message.reply_text('关键词不合法')
                sk = config.setdefault('sticker_keywords',{}).setdefault(gid,{})
                if new_kw in sk and new_kw != tk:
                    return await update.message.reply_text(f'关键词 "{new_kw}" 已存在')
                sk[new_kw] = sk.pop(tk); save_config(config)
                await update.message.reply_text(f"关键词已改名! {tk} → {new_kw}")
            return

        elif mode == "add":
            # Parse: kw [emoji] link
            text = text.strip()
            parts = text.split(maxsplit=1)
            if len(parts) < 2: return await update.message.reply_text('格式: <关键词> [emoji] <链接>')
            kw, rest = parts[0], parts[1]
            emoji_filter = None
            first_char = rest[0] if rest else ''
            after = rest[1:].strip()
            if first_char and ord(first_char) > 127 and after:
                emoji_filter = _norm_emoji(first_char)
                rest = after
            m = re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', rest)
            sn = m.group(1) if m else rest.split('/')[-1].split('?')[0]
            if not sn: return await update.message.reply_text('无法提取包名')
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                allowed = _filter_blocked_stickers(sn, ss.stickers)
                if emoji_filter:
                    from bot_config import _filtered_sn, _pack_emoji
                    cache_sn = _filtered_sn(sn, emoji_filter)
                    em = _pack_emoji.get(sn, {})
                    filtered = [fid for fid in allowed if em.get(fid, '') == emoji_filter]
                    logger.info(f"EMOJI_ADD_DEBUG: sn={sn} filter={repr(emoji_filter)} total={len(allowed)} matched={len(filtered)} sample_em={list(set(em.values()))[:10] if em else '[EMPTY]'}")
                    sticker_cache[cache_sn] = filtered
                    _init_queue(cache_sn, sticker_cache, sticker_queue)
                    config.setdefault('sticker_keywords',{}).setdefault(gid,{})[kw] = {
                        "set": sn, "mode": "sequential", "exact": True, "emoji_filter": emoji_filter}
                else:
                    sticker_cache[sn] = allowed; _init_queue(sn, sticker_cache, sticker_queue)
                    config.setdefault('sticker_keywords',{}).setdefault(gid,{})[kw] = {"set": sn, "mode": "sequential", "exact": True}
                save_config(config)
                gname = _get_group_name(gid)
                actual_count = len(filtered) if emoji_filter else len(allowed)
                total_count = len(allowed)
                extra = f" (只看{emoji_filter} → {actual_count}/{total_count}张)" if emoji_filter else ""
                await update.message.reply_text(f"添加成功! [{gname}] {kw} -> {sn} ({actual_count}张){extra}")
            except Exception as e: await update.message.reply_text(f"失败: {e}")
            return

        elif mode.startswith("replace_inline:"):
            tk = mode.split(":",1)[1]
            if re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', text) or text.strip().startswith('https://t.me/'):
                m = re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', text)
                sn = m.group(1) if m else text.strip().split('/')[-1].split('?')[0]
                if not sn: return await update.message.reply_text('无法提取包名')
                try:
                    ss = await context.bot.get_sticker_set(name=sn); sticks = [s.file_id for s in ss.stickers]
                    old = _inline_get_set(tk, gid)
                    config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{})[tk]['set'] = sn; save_config(config)
                    inline_cache[sn] = sticks; _init_queue(sn, inline_cache, inline_queue)
                    inline_hand[sn] = {}
                    _save_hand()
                    await update.message.reply_text(f"内联替换成功! {tk} -> {sn} ({len(sticks)}张)")
                except Exception as e: await update.message.reply_text(f"失败: {e}")
            else:
                new_kw = text.strip().split()[0]
                if not new_kw or len(new_kw) > 20: return await update.message.reply_text('关键词不合法')
                ik = config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{})
                if new_kw in ik and new_kw != tk:
                    return await update.message.reply_text(f'关键词 "{new_kw}" 已存在')
                ik[new_kw] = ik.pop(tk); save_config(config)
                await update.message.reply_text(f"关键词已改名! {tk} → {new_kw}")
            return

        elif mode.startswith("replace_emoji:"):
            tk = mode.split(":", 1)[1]
            chat = update.effective_chat
            em_gid = str(chat.id) if chat and chat.type in ('group', 'supergroup') else str(user_selected_group.get(user_id, '_global'))
            m = re.search(r'addemoji/([a-zA-Z0-9_]+)', text)
            sn = m.group(1) if m else text.strip().split('/')[-1].split('?')[0]
            if not sn: return await update.message.reply_text('无法提取包名')
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                emoji_map = {s.custom_emoji_id: s.emoji for s in ss.stickers if s.type == 'custom_emoji' and s.custom_emoji_id and s.emoji}
                if not emoji_map:
                    return await update.message.reply_text(f"包 '{sn}' 中没有自定义 Emoji")
                old = _emoji_get_set(tk, em_gid)
                config.setdefault('emoji_keywords', {}).setdefault(em_gid, {})[tk]['set'] = sn; save_config(config)
                emoji_cache[sn] = emoji_map; _init_queue(sn, emoji_cache, emoji_queue)
                if old and old not in {v.get('set', '') if isinstance(v, dict) else v for v in config.get('emoji_keywords', {}).get(em_gid, {}).values()}:
                    all_es = set()
                    for gid2, kws in config.get('emoji_keywords', {}).items():
                        for v in kws.values():
                            all_es.add(v.get('set', '') if isinstance(v, dict) else v)
                    if old not in all_es:
                        emoji_cache.pop(old, None); emoji_queue.pop(old, None)
                await update.message.reply_text(f"Emoji替换成功! {tk} -> {sn} ({len(emoji_map)}个)")
            except Exception as e: await update.message.reply_text(f"失败: {e}")
            return

        elif mode == "collect_image_kw":
            kw = text.strip()
            if not kw or len(kw) > 20:
                waiting_for_input[user_id] = mode
                return await update.message.reply_text('关键词不合法, 1-20字。重试或 /cancel')
            waiting_for_input[user_id] = "collect_image"
            img_collect_kw[user_id] = kw
            img_collect.setdefault(user_id, [])
            await update.message.reply_text(
                f"关键词: {kw}\n"
                f"发送图片添加到 '{kw}'。\n"
                f"拼接模式: 发送 /gap 分隔组 → 每组抽1张拼接。\n"
                f"普通模式: 直接 /cancel 完成。"
            )

        elif mode == "collect_image":
            # /gap: start a new group (composite mode)
            if text.strip() == '/gap':
                current = img_collect.get(user_id, [])
                if current:
                    img_collect_composite.setdefault(user_id, []).append(current)
                    img_collect[user_id] = []
                    total_groups = len(img_collect_composite[user_id])
                    await update.message.reply_text(
                        f"已保存第 {total_groups} 组 ({len(current)} 张)。\n"
                        f"继续发送下一组图片, 或 /cancel 完成。"
                    )
                else:
                    await update.message.reply_text("当前组没有图片。请先发送图片再输入 /gap。")
            # Other text during collection is ignored; photos handled by photo handler

        elif mode.startswith("add_image:"):
            # Legacy: kept for backward compat
            return

        elif mode.startswith("replace_image:"):
            return  # Legacy, no longer supported

        elif mode == "add_inline":
            text2 = text.strip()
            parts2 = text2.split(maxsplit=1)
            if len(parts2) < 2: return await update.message.reply_text('格式: <关键词> [emoji] <链接>')
            kw, rest = parts2[0], parts2[1]
            emoji_filter = None
            first_char = rest[0] if rest else ''
            after = rest[1:].strip()
            if first_char and ord(first_char) > 127 and after:
                emoji_filter = _norm_emoji(first_char)
                rest = after
            m = re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', rest); sn = m.group(1) if m else rest.split('/')[-1].split('?')[0]
            if not sn: return await update.message.reply_text('无法提取包名')
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                allowed = _filter_blocked_stickers(sn, ss.stickers)
                # If emoji filter: use filtered cache key and only store matching stickers
                if emoji_filter:
                    from bot_config import _filtered_sn, _pack_emoji
                    cache_sn = _filtered_sn(sn, emoji_filter)
                    em = _pack_emoji.get(sn, {})
                    filtered = [fid for fid in allowed if em.get(fid, '') == emoji_filter]
                    logger.info(f"EMOJI_ADDINLINE_DEBUG: sn={sn} filter={repr(emoji_filter)} total={len(allowed)} matched={len(filtered)} emojis={list(set(em.values()))}")
                    inline_cache[cache_sn] = filtered
                    _init_queue(cache_sn, inline_cache, inline_queue)
                    config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{})[kw] = {
                        "set": sn, "mode": "limited", "exact": True, "sort": False,
                        "emoji_filter": emoji_filter}
                    save_config(config)
                    inline_hand[cache_sn] = {}
                    _save_hand()
                    gname = _get_group_name(gid)
                    await update.message.reply_text(
                        f"内联添加成功! [{gname}] {kw} -> {sn} (只看{emoji_filter}) ({len(filtered)}/{len(allowed)}张)")
                else:
                    config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{})[kw] = {
                        "set": sn, "mode": "limited", "exact": True, "sort": False}
                    save_config(config)
                    inline_cache[sn] = allowed; _init_queue(sn, inline_cache, inline_queue)
                    inline_hand[sn] = {}
                    _save_hand()
                    gname = _get_group_name(gid)
                    await update.message.reply_text(f"内联添加成功! [{gname}] {kw} -> {sn} ({len(allowed)}张)")
            except Exception as e: await update.message.reply_text(f"失败: {e}")
            return

    # -- Index send: 1-2-3/  or  1~3/ (play cards from hand by position, across ALL packs)
    idx_match = re.match(r'^(\d+(?:-\d+)+)(/?)$', text.strip())
    range_match = re.match(r'^(\d+)~(\d+)(/?)$', text.strip())
    if idx_match or range_match:
        uid = user_id
        # Build a flat combined hand list across ALL packs the user holds: [(sn, fid), ...]
        sn_order = []
        last = _last_inline_kw.get(uid)
        target_sn = last['sn'] if last else None
        if target_sn:
            sn_order.append(target_sn)
        sn_order += [sn for sn in inline_hand if sn != target_sn]
        combined = []  # (sn, fid)
        for sn in sn_order:
            users = inline_hand.get(sn, {})
            if uid in users:
                for fid in users[uid]:
                    combined.append((sn, fid))
        if not combined:
            await update.message.reply_text("手牌为空。")
            return
        # Parse requested indices
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            if start > end: start, end = end, start
            indices = list(range(start, end + 1))
            send_s = (range_match.group(3) == '/')
        else:
            indices = [int(x) for x in idx_match.group(1).split('-')]
            send_s = (idx_match.group(2) == '/')
        # Pop requested positions from the flat list (highest first to keep indices valid)
        played = []  # [(sn, fid), ...]
        for idx in sorted(set(indices), reverse=True):
            i = idx - 1
            if 0 <= i < len(combined):
                played.insert(0, combined.pop(i))
        if not played:
            await update.message.reply_text("没有可打出的对应手牌。")
            return
        # Remove each played card from its own pack's hand and collect discards
        discard_map = {}  # sn -> [fid, ...]
        for sn, fid in played:
            users = inline_hand.get(sn, {})
            hand = users.get(uid)
            if hand and fid in hand:
                hand.remove(fid)
            if _is_limited_set(sn):
                discard_map.setdefault(sn, []).append(fid)
            # 手动收藏包：同步从内联缓存移除，保持"内联包"与手牌一致
            if sn == _MANUAL_SN and fid in inline_cache.get(sn, []):
                inline_cache[sn].remove(fid)
        # Persist discards (crash-safe, before sending)
        for sn, fids in discard_map.items():
            if sn in inline_shared_discard and uid in inline_shared_discard[sn]:
                dc = inline_shared_discard[sn].setdefault(uid, [])
            else:
                dc = inline_discard.setdefault(sn, {}).setdefault(uid, [])
            dc.extend(fids)
        _save_json(DISCARD_FILE, inline_discard)
        _save_json(SHARED_DISCARD_FILE, inline_shared_discard)
        # Drop empty hands
        for sn, fid in played:
            users = inline_hand.get(sn, {})
            if uid in users and not users[uid]:
                del users[uid]
        _save_hand()
        # Send stickers if trailing slash present
        if send_s:
            for sn, fid in played:
                kwargs = {"chat_id": update.effective_chat.id, "sticker": fid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                try: await context.bot.send_sticker(**kwargs)
                except Exception as se: logger.warning(f"Play fail: {se}")
        await update.message.reply_text(f"已打出 {len(played)} 张  |  手牌 {len(combined)} 张")
        return

    # -- Group-aware keyword detection --
    if not config.get('enabled_features',{}).get('keyword_reply', True): return

    for keyword, reply in config.get('keywords',{}).items():
        if keyword in text.lower():
            await update.message.reply_text(reply); return

    msg_lower = text.lower()

    # Resolve group context for keyword matching
    chat = update.effective_chat
    chat_group_id = None
    if chat and chat.type in ['group', 'supergroup']:
        chat_group_id = str(chat.id)
        # Auto-register
        known = config.setdefault('known_groups', {})
        if chat_group_id not in known:
            known[chat_group_id] = chat.title or f"群组{chat_group_id}"
            save_config(config)

    def _match_inline_keywords(check_gid):
        """Match inline keywords for a specific group, returns (keyword, count, sn, silent, has_slash, peek, discard, full_reset, recycle) or None."""
        ik = _get_ik(check_gid)
        for keyword, v in ik.items():
            if keyword not in msg_lower: continue
            count = 1; silent = True; has_slash = False; peek = False; discard = False; full_reset = False; recycle = False; parts = text.strip().split()
            if len(parts) >= 2 and parts[0].lower() == keyword.lower():
                last_part = parts[-1]
                if last_part.endswith('-'):
                    silent = False; recycle = True
                    num_str = last_part.rstrip('-')
                    try: count = max(1, min(int(num_str), 50))
                    except ValueError: count = 1
                elif last_part.endswith('d'):
                    if last_part == '0d':
                        # 关键词 0d: full reset
                        silent = False; count = 0; full_reset = True
                    else:
                        silent = False; has_slash = True
                        num_str = last_part.rstrip('d')
                        try: count = max(0, min(int(num_str), 50))
                        except ValueError: count = 1
                elif last_part.endswith('w'):
                    silent = False; has_slash = True; peek = True
                    num_str = last_part.rstrip('w')
                    try: count = max(1, min(int(num_str), 50))
                    except ValueError: count = 1
                elif last_part.endswith('f'):
                    silent = False; has_slash = True; discard = True
                    num_str = last_part.rstrip('f')
                    try: count = max(1, min(int(num_str), 50))
                    except ValueError: count = 1
                elif last_part.endswith('!') or last_part.endswith('！'):
                    silent = False; has_slash = True; discard = True
                    num_str = last_part.rstrip('!').rstrip('！')
                    if num_str:
                        try: count = max(1, min(int(num_str), 50))
                        except ValueError: count = 1
                elif last_part == '/':
                    silent = False; has_slash = True; count = 1
                else:
                    try: count = max(0, min(int(parts[-1]), 50))
                    except ValueError: count = 1
            sn = v.get('set', '') if isinstance(v, dict) else v
            return keyword, count, sn, silent, has_slash, peek, discard, full_reset, recycle
        return None

    def _match_sticker_keywords(check_gid):
        """Match sticker keywords for a specific group, returns (keyword, count, sn, peek, recycle, discard) or None."""
        sk = _get_sk(check_gid)
        for keyword, v in sk.items():
            if keyword not in msg_lower: continue
            count = 1; peek = False; recycle = False; discard = False; parts = text.strip().split()
            if len(parts) >= 2 and parts[0].lower() == keyword.lower():
                if parts[1].endswith('-'):
                    recycle = True
                    try: count = max(1, min(int(parts[1][:-1]), 50))
                    except ValueError: pass
                elif parts[1].endswith('w'):
                    try: count = max(1, min(int(parts[1][:-1]), 50)); peek = True
                    except ValueError: pass
                elif parts[1].endswith('!') or parts[1].endswith('！'):
                    discard = True
                    num_str = parts[1].rstrip('!').rstrip('！')
                    if num_str:
                        try: count = max(1, min(int(num_str), 50))
                        except ValueError: pass
                else:
                    try: count = max(0, min(int(parts[-1]), 50))
                    except ValueError: count = 1
            sn = v.get('set', '') if isinstance(v, dict) else v
            return keyword, count, sn, peek, recycle, discard
        return None

    # Priority: chat group first, then _global
    search_groups = [chat_group_id, '_global'] if chat_group_id else ['_global']

    # === Image keywords (Telegram file_ids, queue-based like sticker) ===
    def _match_image_keywords(check_gid):
        ik = _get_img_kw(check_gid)
        for keyword, v in ik.items():
            if keyword.lower() not in msg_lower: continue
            count = 1; peek = False; parts = text.strip().split()
            if len(parts) >= 2 and parts[0].lower() == keyword.lower():
                if parts[1].endswith('w'):
                    try: count = max(1, min(int(parts[1][:-1]), 50)); peek = True
                    except ValueError: pass
                else:
                    try: count = max(0, min(int(parts[-1]), 50))
                    except ValueError: count = 1
            return keyword, count, peek
        return None

    # === 拼接图片关键字 (Composite Image Keywords) ===
    def _match_composite_keywords(check_gid):
        ck = _get_comp_kw(check_gid)
        for keyword, v in ck.items():
            if keyword.lower() not in msg_lower: continue
            return keyword
        return None

    for gid in search_groups:
        result = _match_composite_keywords(gid)
        if result:
            keyword = result
            if _get_exact('composite_keywords', keyword, gid):
                parts = text.strip().split()
                if not parts or parts[0].lower() != keyword.lower(): continue
            groups = _comp_get_groups(keyword, gid)
            mode = _comp_get_mode(keyword, gid)
            if not groups or len(groups) < 1:
                await update.message.reply_text(f"'{keyword}' 没有图片组, 请重新添加"); return
            # Pick 1 random from each group
            picked = []
            for group in groups:
                if not group:
                    await update.message.reply_text(f"'{keyword}' 某组为空, 请重新添加"); return
                picked.append(random.choice(group))
            # Download and stitch
            try:
                image_data = []
                for fid in picked:
                    f = await context.bot.get_file(fid)
                    buf = await f.download_as_bytearray()
                    image_data.append(bytes(buf))
                output = await asyncio.to_thread(_stitch_images_h, image_data)
                kwargs = {"chat_id": update.effective_chat.id, "photo": output}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                await context.bot.send_photo(**kwargs)
                await update.message.reply_text(
                    f"拼接抽取 {keyword}: 每组1张 → {len(picked)} 张拼接"
                )
            except Exception as se:
                logger.warning(f"Composite stitch fail: {se}")
                await update.message.reply_text(f"拼接失败: {se}")
            return

    for gid in search_groups:
        result = _match_image_keywords(gid)
        if not result: continue
        keyword, count, peek = result
        if _get_exact('image_keywords', keyword, gid):
            parts = text.strip().split()
            if not parts or parts[0].lower() != keyword.lower(): continue
        key = _img_kw_key(gid, keyword)
        img_mode = _img_get_mode(keyword, gid)
        img_files = _img_get_files(keyword, gid)
        if not img_files:
            await update.message.reply_text(f"'{keyword}' 没有图片, 请重新添加"); return

        if peek:
            sample = random.sample(img_files, min(count, len(img_files)))
            for fid in sample:
                kwargs = {"chat_id": update.effective_chat.id, "photo": fid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                try: await context.bot.send_photo(**kwargs)
                except Exception as se: logger.warning(f"Image peek fail: {se}")
            await update.message.reply_text(f"预览 {len(sample)} 张  |  牌库 {len(img_files)} 张")
            return

        # Ensure cache has latest from config
        img_cache[key] = list(img_files)
        if key not in img_queue or not img_queue.get(key):
            pool = [f for f in img_files
                    if f not in img_kept.get(key, {}).get(user_id, [])]
            random.shuffle(pool)
            img_queue[key] = pool
            _save_img_state()

        if count == 0:
            if img_mode == 'limited':
                # Limited: recycle all discard from all users
                all_discard = []
                for uid2, cards in img_discard.get(key, {}).items():
                    all_discard.extend(cards)
                random.shuffle(all_discard)
                if all_discard:
                    img_queue[key] = all_discard
                    await update.message.reply_text(
                        f"全部图片弃牌 {len(all_discard)} 张洗入牌库  |  牌库 {len(all_discard)} 张"
                    )
                else:
                    _init_queue(key, img_cache, img_queue)
                    await update.message.reply_text(f"图片牌库已重置  |  牌库 {len(img_files)} 张")
                img_discard[key] = {}
                _save_img_state()
            else:
                # Non-limited: recycle current user's discard, re-shuffle
                my_discard = img_discard.get(key, {}).pop(user_id, [])
                if my_discard:
                    # Put discard back into cache set
                    new_cache = list(img_files) + my_discard
                    img_cache[key] = new_cache
                    _init_queue(key, img_cache, img_queue)
                    await update.message.reply_text(
                        f"弃牌 {len(my_discard)} 张已洗入  |  牌库 {len(new_cache)} 张"
                    )
                else:
                    _init_queue(key, img_cache, img_queue)
                    await update.message.reply_text(f"图片牌库已重新洗混! {keyword} ({len(img_files)}张)")
                _save_img_state()
            return

        drawn = 0
        # 拼接模式: 收集 file_ids → 下载 → 拼图 → 发送一张
        stitch = _img_get_stitch(keyword, gid)
        if stitch and count >= 2:
            fids = []
            queue = img_queue.get(key)
            my_dc = img_discard.get(key, {}).get(user_id, [])
            for _ in range(count):
                if not queue:
                    remaining = [f for f in img_files if f not in my_dc]
                    if not remaining: break
                    img_queue[key] = random.sample(remaining, len(remaining))
                    _save_img_state()
                    queue = img_queue.get(key)
                if not queue: break
                candidate = queue.pop()
                if candidate not in my_dc:
                    fids.append(candidate)
                else:
                    queue.insert(0, candidate)
            if fids:
                try:
                    image_data = []
                    for fid in fids:
                        f = await context.bot.get_file(fid)
                        buf = await f.download_as_bytearray()
                        image_data.append(bytes(buf))
                    output = await asyncio.to_thread(_stitch_images_v, image_data)
                    kwargs = {"chat_id": update.effective_chat.id, "photo": output}
                    tid = getattr(update.message, 'message_thread_id', None)
                    if tid: kwargs["message_thread_id"] = tid
                    await context.bot.send_photo(**kwargs)
                    drawn = len(fids)
                    if img_mode == 'limited':
                        dc = img_discard.setdefault(key, {}).setdefault(user_id, [])
                        dc.extend(fids)
                except Exception as se:
                    logger.warning(f"Stitch fail, fallback: {se}")
                    for fid in fids:
                        try:
                            kwargs = {"chat_id": update.effective_chat.id, "photo": fid}
                            tid = getattr(update.message, 'message_thread_id', None)
                            if tid: kwargs["message_thread_id"] = tid
                            sent_msg = await context.bot.send_photo(**kwargs)
                            _img_msg_map[sent_msg.message_id] = (key, fid)
                            drawn += 1
                        except Exception as e2: logger.warning(f"Img fail: {e2}")
            if drawn:
                remain = len(img_queue.get(key, []))
                total = len(img_cache.get(key, []))
                parts = [f"图片抽牌({len(fids)}拼{drawn}张)", f"牌库 {remain}/{total} 张"]
                if img_mode == 'limited' and remain == 0:
                    parts.append(f"→ 发送 {keyword} 0 洗回弃牌")
                await update.message.reply_text("  |  ".join(parts))
            elif img_mode == 'limited':
                await update.message.reply_text(f"图片牌库已空  →  发送 {keyword} 0 洗回弃牌")
            _save_img_state()
            return

        for i in range(count):
            queue = img_queue.get(key)
            my_dc = img_discard.get(key, {}).get(user_id, [])
            if not queue:
                if img_mode == 'limited': break
                # Re-init from cache minus user's discard and kept
                remaining = [f for f in img_files
                             if f not in my_dc
                             and f not in img_kept.get(key, {}).get(user_id, [])]
                if not remaining:
                    await update.message.reply_text("牌库已空, 所有图片都在弃牌堆。发送 关键词 0 洗入。")
                    break
                img_cache[key] = list(img_files)  # Keep original for total count
                img_queue[key] = random.sample(remaining, len(remaining))
                _save_img_state()
                queue = img_queue.get(key)
            if not queue: break
            # Skip discarded images
            fid = None
            while queue:
                candidate = queue.pop()
                if candidate not in my_dc:
                    fid = candidate; break
                # Discarded: put back at end
                queue.insert(0, candidate)
                # Check if all remaining are discarded
                if all(q in my_dc for q in queue):
                    queue.clear()
                    break
            if fid is None:
                await update.message.reply_text("牌库已空, 所有图片都在弃牌堆。发送 关键词 0 洗入。")
                break
            try:
                kwargs = {"chat_id": update.effective_chat.id, "photo": fid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                sent_msg = await context.bot.send_photo(**kwargs)
                _img_msg_map[sent_msg.message_id] = (key, fid)
                drawn += 1
            except Exception as se: logger.warning(f"Image send fail: {se}")
        if drawn:
            remain = len(img_queue.get(key, []))
            total = len(img_cache.get(key, []))
            parts = [f"图片抽牌 {drawn} 张", f"牌库 {remain}/{total} 张"]
            if img_mode == 'limited' and remain == 0:
                parts.append(f"→ 发送 {keyword} 0 洗回弃牌")
            await update.message.reply_text("  |  ".join(parts))
        elif img_mode == 'limited':
            await update.message.reply_text(f"图片牌库已空  →  发送 {keyword} 0 洗回弃牌")
        _save_img_state()
        return

    # === Emoji keywords (pack-based, same as sticker) ===
    def _match_emoji_keywords(check_gid):
        ek = _get_ek(check_gid)
        for keyword, v in ek.items():
            if keyword not in msg_lower: continue
            count = 1; peek = False; recycle = False; discard = False; parts = text.strip().split()
            if len(parts) >= 2 and parts[0].lower() == keyword.lower():
                if parts[1].endswith('-'):
                    recycle = True
                    try: count = max(1, min(int(parts[1][:-1]), 50))
                    except ValueError: pass
                elif parts[1].endswith('w'):
                    try: count = max(1, min(int(parts[1][:-1]), 50)); peek = True
                    except ValueError: pass
                elif parts[1].endswith('!') or parts[1].endswith('！'):
                    discard = True
                    num_str = parts[1].rstrip('!').rstrip('！')
                    if num_str:
                        try: count = max(1, min(int(num_str), 50))
                        except ValueError: pass
                else:
                    try: count = max(0, min(int(parts[-1]), 50))
                    except ValueError: count = 1
            sn = v.get('set', '') if isinstance(v, dict) else v
            return keyword, count, sn, peek, recycle, discard
        return None

    for gid in search_groups:
        result = _match_emoji_keywords(gid)
        if not result: continue
        keyword, count, sn, peek, recycle, discard = result
        if _get_exact('emoji_keywords', keyword, gid):
            parts = text.strip().split()
            if not parts or parts[0].lower() != keyword.lower(): continue
        emoji_mode = _emoji_get_mode(keyword, gid)

        if discard:
            queue_pool = emoji_queue.get(sn)
            if not queue_pool:
                _init_queue(sn, emoji_cache, emoji_queue)
                queue_pool = emoji_queue.get(sn)
            nd = min(count, len(queue_pool))
            folded = []
            for i in range(nd):
                eid = queue_pool.pop()
                folded.append(eid)
                if emoji_mode == 'limited':
                    emoji_discard.setdefault(sn, {}).setdefault(user_id, []).append(eid)
            _save_json(EMOJI_QUEUE_FILE, emoji_queue)
            _save_json(EMOJI_DISCARD_FILE, emoji_discard)
            await update.message.reply_text(
                f"弃牌 {nd} 个Emoji  |  弃牌堆 {len(folded)} 个  |  牌库 {len(queue_pool)} 个"
            )
            return

        if recycle:
            all_discard = []
            for uid2, cards in emoji_discard.get(sn, {}).items():
                all_discard.extend(cards)
            n = min(count, len(all_discard))
            if n == 0:
                await update.message.reply_text(f"弃牌堆为空, 无法回收。")
                return
            chosen = random.sample(all_discard, n)
            for uid_d, cards in list(emoji_discard.get(sn, {}).items()):
                for c in chosen:
                    if c in cards:
                        cards.remove(c)
                if not cards:
                    del emoji_discard[sn][uid_d]
            queue_now = emoji_queue.get(sn, [])
            queue_now.extend(chosen)
            random.shuffle(queue_now)
            emoji_queue[sn] = queue_now
            _save_json(EMOJI_QUEUE_FILE, emoji_queue)
            _save_json(EMOJI_DISCARD_FILE, emoji_discard)
            await update.message.reply_text(
                f"♻️ 已回收 {n} 个Emoji  |  牌库 {len(queue_now)} 个  |  弃牌 {len(all_discard)-n} 个"
            )
            return

        if count == 0:
            if emoji_mode == 'limited':
                all_discard = []
                for uid, cards in emoji_discard.get(sn, {}).items():
                    all_discard.extend(cards)
                random.shuffle(all_discard)
                if all_discard:
                    emoji_queue[sn] = all_discard
                    user_count = len(emoji_discard.get(sn, {}))
                    await update.message.reply_text(
                        f"全部Emoji弃牌 {len(all_discard)} 张洗入牌库  |  "
                        f"牌库 {len(all_discard)} 张  |  "
                        f"已清空 {user_count} 人的手牌"
                    )
                else:
                    _init_queue(sn, emoji_cache, emoji_queue)
                    await update.message.reply_text(f"Emoji牌库已重置  |  牌库 {len(emoji_cache[sn])} 张")
                emoji_discard[sn] = {}
                _save_json(EMOJI_QUEUE_FILE, emoji_queue)
                _save_json(EMOJI_DISCARD_FILE, emoji_discard)
            else:
                _init_queue(sn, emoji_cache, emoji_queue)
                _save_json(EMOJI_QUEUE_FILE, emoji_queue)
                await update.message.reply_text(f"Emoji牌库已重新洗混! {keyword} -> {sn} ({len(emoji_cache.get(sn,[]))}张)")
            return

        emoji_map = emoji_cache.get(sn)
        if not emoji_map:
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                emoji_map = {s.custom_emoji_id: s.emoji for s in ss.stickers if s.type == 'custom_emoji' and s.custom_emoji_id and s.emoji}
                emoji_cache[sn] = emoji_map
            except Exception: continue
        if not emoji_map: break

        if peek:
            eids = list(emoji_map.keys())
            sample = random.sample(eids, min(count, len(eids)))
            chars = []; entities = []; offset = 0
            for eid in sample:
                ch = emoji_map.get(eid, '\u2764')
                char_len = len(ch.encode('utf-16-le')) // 2
                chars.append(ch)
                entities.append(MessageEntity(type='custom_emoji', offset=offset, length=char_len, custom_emoji_id=eid))
                offset += char_len
            try:
                kwargs = {"chat_id": update.effective_chat.id, "text": ''.join(chars), "entities": entities}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                await context.bot.send_message(**kwargs)
            except Exception as se: logger.warning(f"Emoji peek fail: {se}")
            await update.message.reply_text(f"预览 {len(sample)} 张  |  牌库 {len(eids)} 张")
            return

        drawn = 0
        chars = []; entities = []
        for i in range(count):
            if emoji_mode == 'random':
                # With replacement: pick randomly from all emojis
                if not emoji_map: break
                eid = random.choice(list(emoji_map.keys()))
            else:
                queue = emoji_queue.get(sn)
                if not queue:
                    if emoji_mode == 'limited':
                        break
                    try:
                        ss = await context.bot.get_sticker_set(name=sn)
                        emoji_cache[sn] = {s.custom_emoji_id: s.emoji for s in ss.stickers if s.type == 'custom_emoji' and s.custom_emoji_id and s.emoji}
                    except Exception: break
                    _init_queue(sn, emoji_cache, emoji_queue); queue = emoji_queue.get(sn)
                if not queue: break
                eid = queue.pop()
                if emoji_mode == 'limited':
                    emoji_discard.setdefault(sn, {}).setdefault(user_id, []).append(eid)
            emoji_char = emoji_map.get(eid, '\u2764')
            offset = sum(len(c.encode('utf-16-le')) // 2 for c in chars)
            char_len = len(emoji_char.encode('utf-16-le')) // 2
            chars.append(emoji_char)
            entities.append(MessageEntity(type='custom_emoji', offset=offset, length=char_len, custom_emoji_id=eid))
            drawn += 1
        if drawn:
            try:
                kwargs = {"chat_id": update.effective_chat.id, "text": ''.join(chars), "entities": entities}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                await context.bot.send_message(**kwargs)
            except Exception as se:
                logger.warning(f"Emoji batch send fail: {se}")
            _save_json(EMOJI_QUEUE_FILE, emoji_queue)
            if emoji_mode == 'limited':
                _save_json(EMOJI_DISCARD_FILE, emoji_discard)
        return

    for gid in search_groups:
        result = _match_inline_keywords(gid)
        if not result: continue
        keyword, count, sn, silent, has_slash, peek, discard, full_reset, recycle = result
        if _get_exact('inline_sticker_keywords', keyword, gid):
            parts = text.strip().split()
            if not parts or parts[0].lower() != keyword.lower(): continue
        inline_mode = _inline_get_mode(keyword, gid)
        shared = _inline_is_shared(keyword, gid)
        uid = user_id
        # Get emoji filter for inline keywords
        ik_cfg = config.get('inline_sticker_keywords', {}).get(gid, {}).get(keyword, {})
        inline_emoji_filter = ik_cfg.get('emoji_filter') if isinstance(ik_cfg, dict) else None
        # Use filtered cache key for emoji-filtered inline keywords
        if inline_emoji_filter:
            from bot_config import _filtered_sn
            sn = _filtered_sn(sn, inline_emoji_filter)

        if shared and (sn not in inline_shared_queue or uid not in inline_shared_queue.get(sn, {})):
            _init_shared_pool(sn, uid)

        def _iq_get(): return inline_shared_queue[sn][uid] if shared else inline_queue.get(sn, [])
        def _iq_set(v): 
            if shared: inline_shared_queue[sn][uid] = v; _save_shared_state()
            else: inline_queue[sn] = v; _save_json(INLINE_QUEUE_FILE, inline_queue)
        def _id_get(): return inline_shared_discard.get(sn, {}) if shared else inline_discard.get(sn, {})
        def _id_clear(): 
            if shared: inline_shared_discard[sn] = {}; _save_shared_state()
            else: inline_discard[sn] = {}; _save_json(DISCARD_FILE, inline_discard)
        def _id_save():
            if shared: _save_shared_state()
            else: _save_json(DISCARD_FILE, inline_discard)

        if peek:
            stickers = _iq_get()
            if not stickers:
                (_init_shared_pool(sn, uid) if shared else _init_queue(sn, inline_cache, inline_queue))
                stickers = _iq_get()
            if not stickers: continue
            sample = random.sample(stickers, min(count, len(stickers)))
            for fid in sample:
                kwargs = {"chat_id": update.effective_chat.id, "sticker": fid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                try: await context.bot.send_sticker(**kwargs)
                except Exception as se: logger.warning(f"Inline peek fail: {se}")
            await update.message.reply_text(f"预览 {len(sample)} 张  |  剩余 {len(stickers)} 张  |  手牌 {len(inline_hand.get(sn,{}).get(user_id,[]))} 张")
            return

        if discard:
            # Discard N cards from top of deck into discard pile
            stickers = inline_cache.get(sn)
            if not stickers:
                try:
                    ss = await context.bot.get_sticker_set(name=sn); stickers = _filter_blocked_stickers(sn, ss.stickers); inline_cache[sn] = stickers
                except Exception: continue
            if not stickers: break
            queue = _iq_get()
            if not queue:
                (_init_shared_pool(sn, uid) if shared else _init_queue(sn, inline_cache, inline_queue)); queue = _iq_get()
            if not queue: break
            nd = min(count, len(queue))
            folded = []
            for i in range(nd):
                fid = queue.pop()
                folded.append(fid)
                kwargs = {"chat_id": update.effective_chat.id, "sticker": fid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                try: await context.bot.send_sticker(**kwargs)
                except Exception as se: logger.warning(f"Discard send fail: {se}")
            dc_src = _id_get()
            dc = dc_src.setdefault(user_id, [])
            dc.extend(folded)
            _id_save()
            remain = len(queue)
            await update.message.reply_text(
                f"弃牌 {nd} 张  |  弃牌堆 {len(dc)} 张  |  牌库 {remain} 张"
            )
            return

        if recycle:
            # 关键词 N- : recycle N random cards from discard back to queue
            all_discard = []
            for uid2, cards in _id_get().items():
                all_discard.extend(cards)
            n = min(count, len(all_discard))
            if n == 0:
                await update.message.reply_text(f"弃牌堆为空, 无法回收。")
                return
            chosen = random.sample(all_discard, n)
            # Remove chosen from discard
            dc_dict = _id_get()
            for uid_d, cards in list(dc_dict.items()):
                for c in chosen:
                    if c in cards:
                        cards.remove(c)
                if not cards:
                    del dc_dict[uid_d]
            # Add to queue and shuffle
            queue_now = _iq_get()
            queue_now.extend(chosen)
            random.shuffle(queue_now)
            _iq_set(queue_now)
            _id_save()
            await update.message.reply_text(
                f"♻️ 已回收 {n} 张牌  |  牌库 {len(queue_now)} 张  |  弃牌 {len(all_discard)-n} 张"
            )
            return

        if count == 0:
            if inline_mode == 'limited':
                if full_reset:
                    # 关键词 0d — 完全重置: 先重置牌库, 再把⛔移入保留区
                    try:
                        ss = await context.bot.get_sticker_set(name=sn)
                        inline_cache[sn] = [s.file_id for s in ss.stickers]
                        (_init_shared_pool(sn, uid) if shared else _init_queue(sn, inline_cache, inline_queue))
                        # Now filter ⛔ out of cache and queue
                        _filter_blocked_stickers(sn, ss.stickers)
                        blocked = set(inline_kept.get(sn, {}).get(0, []))
                        if blocked:
                            inline_cache[sn] = [f for f in inline_cache[sn] if f not in blocked]
                            _iq_set([f for f in _iq_get() if f not in blocked])
                    except Exception as e:
                        logger.warning(f"0d refresh fail for {sn}: {e}")
                    _id_clear()
                    inline_hand[sn] = {}
                    _id_save()
                    _save_hand()
                    total_cards = len(inline_cache.get(sn, []))
                    await update.message.reply_text(
                        f"牌库已完全重置  |  牌库 {total_cards} 张  |  弃牌和手牌已清空"
                    )
                else:
                    # 关键词 0 — 全部弃牌洗入牌库 (追加,不替换), 手牌不动
                    all_discard = []
                    for uid2, cards in _id_get().items():
                        all_discard.extend(cards)
                    random.shuffle(all_discard)
                    if all_discard:
                        queue_now = _iq_get()
                        queue_now.extend(all_discard)
                        _iq_set(queue_now)
                        user_count = len(_id_get())
                        await update.message.reply_text(
                            f"全部弃牌 {len(all_discard)} 张洗入牌库  |  "
                            f"牌库 {len(queue_now)} 张  |  "
                            f"来自 {user_count} 人  |  手牌未动"
                        )
                    else:
                        remain = len(_iq_get())
                        await update.message.reply_text(
                            f"弃牌堆为空  |  牌库 {remain} 张  |  手牌未动"
                        )
                    _id_clear()
                    _id_save()
            else:
                (_init_shared_pool(sn, uid) if shared else _init_queue(sn, inline_cache, inline_queue));
                inline_hand[sn] = {}
                _save_hand()
                await update.message.reply_text(f"手牌已清空  |  牌库 {len(inline_cache[sn])} 张已恢复")
            return

        stickers = inline_cache.get(sn, [])
        # Merge keyword extra stickers into pool
        extra_stickers = _get_keyword_extras(keyword, gid)
        if extra_stickers:
            stickers = list(stickers) + [f for f in extra_stickers if f not in stickers]
        if not stickers:
            try:
                ss = await context.bot.get_sticker_set(name=sn); stickers = _filter_blocked_stickers(sn, ss.stickers); inline_cache[sn] = stickers
            except Exception: continue
            # Re-merge extras after cache refresh
            extra_stickers = _get_keyword_extras(keyword, gid)
            if extra_stickers:
                stickers = list(stickers) + [f for f in extra_stickers if f not in stickers]
        if not stickers: break

        drawn = []
        uid = user_id
        for i in range(count):
            queue = _iq_get()
            if not queue:
                if inline_mode == 'limited':
                    break  # Deck exhausted, stop
                try:
                    ss = await context.bot.get_sticker_set(name=sn); stickers = _filter_blocked_stickers(sn, ss.stickers); inline_cache[sn] = stickers
                except Exception: break
                # Re-merge extras after cache refresh
                extra_stickers2 = _get_keyword_extras(keyword, gid)
                if extra_stickers2:
                    for f in extra_stickers2:
                        if f not in inline_cache[sn]:
                            inline_cache[sn].append(f)
                (_init_shared_pool(sn, uid) if shared else _init_queue(sn, inline_cache, inline_queue)); queue = _iq_get()
            if not queue: break
            sid = queue.pop(); drawn.append(sid)
            inline_hand.setdefault(sn, {}).setdefault(uid, []).append(sid)
            if inline_mode == 'limited':
                dc = _id_get().setdefault(uid, [])
                dc.append(sid)
            if not silent:
                kwargs = {"chat_id": update.effective_chat.id, "sticker": sid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                try: await context.bot.send_sticker(**kwargs)
                except Exception as se: logger.warning(f"Inline send fail: {se}")
        # Save state AFTER all draws (crash-safe via atomic write)
        _save_inline_state()
        # Sort hand by original sticker pack order (only if sort is enabled)
        if drawn and sn in inline_hand and uid in inline_hand[sn]:
            if _inline_get_sort(keyword, gid):
                order_map = {fid: idx for idx, fid in enumerate(inline_cache.get(sn, []))}
                inline_hand[sn][uid].sort(key=lambda fid: order_map.get(fid, 999999))
            _save_hand()  # Save after sort
        remain = len(_iq_get())
        if drawn:
            my_hand = len(inline_hand.get(sn, {}).get(uid, []))
            parts = [f"抽牌 {len(drawn)} 张", f"手牌 {my_hand} 张"]
            if not silent:
                parts.append("发送")
            if inline_mode == 'limited':
                my_dc = len(_id_get().get(uid, []))
                total_dc = sum(len(v) for v in _id_get().values())
                parts.append(f"牌库 {remain} 张")
                if my_dc > 0:
                    dc_text = f"弃牌 {my_dc} 张" if total_dc == my_dc else f"弃牌 {my_dc}/{total_dc} 张"
                    parts.append(dc_text)
                if remain == 0:
                    parts.append(f"→ 发送 {keyword} 0 洗回弃牌")
            else:
                total = len(inline_cache.get(sn, []))
                parts.append(f"牌库 {remain}/{total} 张")
            await update.message.reply_text("  |  ".join(parts))
        elif inline_mode == 'limited':
            my_dc = len(_id_get().get(uid, []))
            total_dc = sum(len(v) for v in _id_get().values())
            dc_text = f"弃牌 {my_dc} 张" if total_dc == my_dc else f"弃牌 {my_dc}/{total_dc} 张"
            await update.message.reply_text(
                f"牌库已空  |  手牌 {len(inline_hand.get(sn, {}).get(uid, []))} 张  |  "
                f"{dc_text}  →  发送 {keyword} 0 洗回弃牌 (发送 {keyword} 0/ 全局重置)"
            )
        return

    # === Main sticker keywords ===
    for gid in search_groups:
        result = _match_sticker_keywords(gid)
        if not result: continue
        keyword, count, sn, peek, recycle, discard = result
        if _get_exact('sticker_keywords', keyword, gid):
            parts = text.strip().split()
            if not parts or parts[0].lower() != keyword.lower(): continue

        # Use filtered cache key if keyword has emoji_filter
        kw_cfg = config.get('sticker_keywords', {}).get(gid, {}).get(keyword, {})
        emoji_filter = kw_cfg.get('emoji_filter') if isinstance(kw_cfg, dict) else None
        if emoji_filter:
            from bot_config import _filtered_sn
            sn = _filtered_sn(sn, emoji_filter)

        if recycle:
            await update.message.reply_text(f"贴纸关键词不支持 N- 回收。请使用内联或Emoji关键词。")
            return

        if discard:
            queue_pool = sticker_queue.get(sn)
            if not queue_pool:
                _init_queue(sn, sticker_cache, sticker_queue)
                queue_pool = sticker_queue.get(sn)
            nd = min(count, len(queue_pool))
            folded = []
            for i in range(nd):
                fid = queue_pool.pop()
                folded.append(fid)
                if _get_mode(keyword, gid) == 'limited':
                    sticker_discard.setdefault(sn, {}).setdefault(user_id, []).append(fid)
            _save_json(QUEUE_FILE, sticker_queue)
            _save_json(STICKER_DISCARD_FILE, sticker_discard)
            await update.message.reply_text(
                f"弃牌 {nd} 张  |  弃牌堆 {len(folded)} 张  |  牌库 {len(queue_pool)} 张"
            )
            return

        if count == 0:
            mode_s = _get_mode(keyword, gid)
            if mode_s == 'limited':
                all_discard = []
                for uid2, cards in sticker_discard.get(sn, {}).items():
                    all_discard.extend(cards)
                random.shuffle(all_discard)
                if all_discard:
                    queue_now = sticker_queue.get(sn, [])
                    queue_now.extend(all_discard)
                    sticker_queue[sn] = queue_now
                    sticker_discard[sn] = {}
                    _save_json(QUEUE_FILE, sticker_queue)
                    _save_json(STICKER_DISCARD_FILE, sticker_discard)
                    await update.message.reply_text(
                        f"全部弃牌 {len(all_discard)} 张洗入牌库  |  牌库 {len(queue_now)} 张"
                    )
                else:
                    await update.message.reply_text(f"弃牌堆为空  |  牌库 {len(sticker_queue.get(sn, []))} 张")
            else:
                _init_queue(sn, sticker_cache, sticker_queue); _save_json(QUEUE_FILE, sticker_queue)
                await update.message.reply_text(f"牌库已重新洗混! {keyword} -> {sn} ({len(sticker_cache.get(sn,[]))}张)")
            return

        stickers = sticker_cache.get(sn)
        if not stickers:
            try:
                ss = await context.bot.get_sticker_set(name=sn); stickers = [s.file_id for s in ss.stickers]; sticker_cache[sn] = stickers
            except Exception: continue
        if not stickers: break

        if peek:
            queue_pool = sticker_queue.get(sn)
            if not queue_pool:
                _init_queue(sn, sticker_cache, sticker_queue)
                queue_pool = sticker_queue.get(sn)
            if not queue_pool: continue
            sample = random.sample(queue_pool, min(count, len(queue_pool)))
            for sid in sample:
                kwargs = {"chat_id": update.effective_chat.id, "sticker": sid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                try: await context.bot.send_sticker(**kwargs)
                except Exception as se: logger.warning(f"Peek fail: {se}")
            await update.message.reply_text(f"预览 {len(sample)} 张  |  剩余 {len(queue_pool)} 张  |  总牌库 {len(stickers)} 张")
            return

        mode_s = _get_mode(keyword, gid)
        for i in range(count):
            use_random = mode_s == 'random'
            if use_random:
                # Filter by emoji if needed
                if emoji_filter and sn in _pack_emoji:
                    em = _pack_emoji[sn]
                    pool = [fid for fid in stickers if em.get(fid, '') == emoji_filter]
                else:
                    pool = stickers
                if not pool: break
                sid = random.choice(pool)
            else:
                queue = sticker_queue.get(sn)
                if not queue:
                    if mode_s == 'limited': break
                    try:
                        ss = await context.bot.get_sticker_set(name=sn); stickers = _filter_blocked_stickers(sn, ss.stickers); sticker_cache[sn] = stickers
                    except Exception: break
                    _init_queue(sn, sticker_cache, sticker_queue, emoji_filter); queue = sticker_queue.get(sn)
                if not queue: break
                sid = queue.pop(); _save_json(QUEUE_FILE, sticker_queue)
            if mode_s == 'limited':
                sticker_discard.setdefault(sn, {}).setdefault(user_id, []).append(sid)
                _save_json(STICKER_DISCARD_FILE, sticker_discard)
            kwargs = {"chat_id": update.effective_chat.id, "sticker": sid}
            tid = getattr(update.message, 'message_thread_id', None)
            if tid: kwargs["message_thread_id"] = tid
            try: await context.bot.send_sticker(**kwargs)
            except Exception as se: logger.warning(f"Send fail: {se}")
        return

# ========== Inline query ==========
# Track last used inline keyword per user (for empty query context)
_last_inline_kw: dict = {}  # {user_id: {sn: set_name, kw: keyword}}
# Track card usage count per pack per user (for default pack selection)
_user_pack_usage: dict = {}  # {user_id: {sn: count}}
# Track merge mode: True=merge all packs, False=single pack
_inline_merge_mode: dict = {}  # {user_id: bool}  default True
_img_msg_map: dict = {}  # {message_id: (img_key, pool_file_id)} track sent photos

# 回复贴纸 d 直接收藏的「手动手牌」包标识（不属于任何关键词，独立成包）
_MANUAL_SN = "__manual_hand__"

async def inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.inline_query.query.strip().lower()
    uid = update.inline_query.from_user.id

    # Empty query: show hands based on merge mode
    if not q:
        merge_on = _inline_merge_mode.get(uid, True)  # default: merge all
        valid_packs = set()
        for gid, kws in config.get('inline_sticker_keywords', {}).items():
            for v in kws.values():
                valid_packs.add(v.get('set', '') if isinstance(v, dict) else v)
        # 手动收藏包也纳入手牌展示
        valid_packs.add(_MANUAL_SN)

        if merge_on:
            # Mode 1: merge all packs
            merged = []
            for sn, users in inline_hand.items():
                if sn not in valid_packs or uid not in users: continue
                for fid in users[uid]:
                    merged.append((sn, fid))
            if merged:
                results = [InlineQueryResultCachedSticker(
                    id=f"h|{sn}|{i:03d}", sticker_file_id=fid
                ) for i, (sn, fid) in enumerate(merged[:50])]
                try:
                    await update.inline_query.answer(results, cache_time=1)
                    return
                except Exception as e:
                    logger.warning(f"Inline full merge fail: {e}")
            # Merge failed → fall through to single pack

        # Mode 2 (or merge failed): single pack
        best_sn = None
        usage = _user_pack_usage.get(uid, {})
        best_sn = max(usage, key=usage.get) if usage else None
        if not best_sn or best_sn not in inline_hand or uid not in inline_hand.get(best_sn, {}):
            last = _last_inline_kw.get(uid)
            best_sn = last['sn'] if last else None
        if not best_sn or best_sn not in inline_hand or uid not in inline_hand.get(best_sn, {}):
            for sn in inline_hand:
                if sn in valid_packs and uid in inline_hand[sn]:
                    best_sn = sn; break
        if best_sn and best_sn in inline_hand and uid in inline_hand[best_sn]:
            hand = inline_hand[best_sn][uid]
            results = [InlineQueryResultCachedSticker(id=f"h|{best_sn}|{i:03d}", sticker_file_id=fid)
                       for i, fid in enumerate(hand[:50])]
            try:
                await update.inline_query.answer(results, cache_time=1)
            except Exception as e:
                logger.warning(f"Inline best-single fail: {e}")
        return

    # Search all groups for inline keywords
    for gid, kws in config.get('inline_sticker_keywords', {}).items():
        for keyword, v in kws.items():
            if keyword.lower() not in q: continue
            sn = v.get('set', '') if isinstance(v, dict) else v
            # Use filtered cache key if keyword has emoji_filter
            em_filter = v.get('emoji_filter') if isinstance(v, dict) else None
            if em_filter:
                from bot_config import _filtered_sn
                sn = _filtered_sn(sn, em_filter)
            # Track last used
            _last_inline_kw[uid] = {'sn': sn, 'kw': keyword}
            hand = inline_hand.get(sn, {}).get(uid, [])
            if not hand:
                try:
                    await update.inline_query.answer([], cache_time=1,
                        switch_pm_text="你的手牌为空", switch_pm_parameter="empty")
                except Exception: pass
                return
            results = [InlineQueryResultCachedSticker(id=f"h|{sn}|{i:03d}", sticker_file_id=fid)
                       for i, fid in enumerate(hand[:50])]
            try:
                await update.inline_query.answer(results, cache_time=1)
            except Exception as e:
                logger.warning(f"Inline answer expired: {e}")
            return

# ========== Chosen inline result ==========
async def chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result_id = update.chosen_inline_result.result_id
    uid = update.chosen_inline_result.from_user.id
    logger.info(f"chosen_inline: uid={uid} rid={result_id}")

    parts = result_id.split('|', 2)
    if len(parts) < 3: return
    sn = parts[1]
    user_hand = inline_hand.get(sn, {}).get(uid, [])
    if not user_hand: return
    try:
        idx = int(parts[2])
        if idx < len(user_hand):
            played = user_hand.pop(idx)
            # UNO: detect function cards by sticker position in unoame pack
            from bot_uno import handle_uno_play
            await handle_uno_play(uid, played, context)
            if _is_limited_set(sn):
                if sn in inline_shared_discard and uid in inline_shared_discard[sn]:
                    inline_shared_discard[sn].setdefault(uid, []).append(played)
                    _save_json(SHARED_DISCARD_FILE, inline_shared_discard)
                else:
                    inline_discard.setdefault(sn, {}).setdefault(uid, []).append(played)
                    _save_json(DISCARD_FILE, inline_discard)
                discard_len = len(inline_shared_discard[sn][uid]) if sn in inline_shared_discard and uid in inline_shared_discard[sn] else len(inline_discard.get(sn, {}).get(uid, []))
                logger.info(f"Card discarded by {uid} to '{sn}': {discard_len} in discard")
            # 手动收藏包：同步从内联缓存移除，保持"内联包"与手牌一致
            if sn == _MANUAL_SN and played in inline_cache.get(sn, []):
                inline_cache[sn].remove(played)
    except Exception as e:
        logger.warning(f"chosen_inline discard error for {sn}/{uid}: {e}")
    inline_hand.setdefault(sn, {})[uid] = user_hand
    _save_hand()
    # Track pack usage for default pack selection
    _user_pack_usage.setdefault(uid, {})[sn] = _user_pack_usage.setdefault(uid, {}).get(sn, 0) + 1
    _save_hand()
    logger.info(f"Inline played from '{sn}' by {uid}: hand now {len(user_hand)}")

# ========== Sticker sent handler ==========
async def handle_sticker_sent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sticker = update.message.sticker
    if not sticker or not sticker.file_id: return
    fid = sticker.file_id
    uid = update.message.from_user.id

    # --- Keyword trigger via sticker ---
    trigger = _get_trigger_kw(fid)
    if trigger:
        gid_k, kw = trigger
        # Check inline keywords
        ik = config.get('inline_sticker_keywords', {}).get(gid_k, {})
        if kw in ik:
            sn = ik[kw].get('set', '') if isinstance(ik[kw], dict) else ik[kw]
            q = inline_queue.get(sn)
            if not q: _init_queue(sn, inline_cache, inline_queue); q = inline_queue.get(sn)
            if q:
                sid = q.pop()
                inline_hand.setdefault(sn, {}).setdefault(uid, []).append(sid)
                mode_kw = _inline_get_mode(kw, gid_k)
                if mode_kw == 'limited':
                    if _inline_is_shared(kw, gid_k) and sn in inline_shared_discard:
                        inline_shared_discard[sn].setdefault(uid, []).append(sid)
                    else:
                        inline_discard.setdefault(sn, {}).setdefault(uid, []).append(sid)
                _save_inline_state()
                kwargs_s = {"chat_id": update.effective_chat.id, "sticker": sid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs_s["message_thread_id"] = tid
                try: await context.bot.send_sticker(**kwargs_s)
                except Exception as e: logger.warning(f"Trigger inline fail: {e}")
            return
        # Check sticker keywords
        sk = config.get('sticker_keywords', {}).get(gid_k, {})
        if kw in sk:
            sn = sk[kw].get('set', '') if isinstance(sk[kw], dict) else sk[kw]
            q = sticker_queue.get(sn)
            if not q: _init_queue(sn, sticker_cache, sticker_queue); q = sticker_queue.get(sn)
            if q:
                sid = q.pop()
                _save_json(QUEUE_FILE, sticker_queue)
                kwargs_s = {"chat_id": update.effective_chat.id, "sticker": sid}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs_s["message_thread_id"] = tid
                try: await context.bot.send_sticker(**kwargs_s)
                except Exception as e: logger.warning(f"Trigger sticker fail: {e}")
            return
        # Check emoji keywords → react with custom emoji
        ek = config.get('emoji_keywords', {}).get(gid_k, {})
        if kw in ek:
            sn = ek[kw].get('set', '') if isinstance(ek[kw], dict) else ek[kw]
            q = emoji_queue.get(sn)
            if not q: _init_queue(sn, emoji_cache, emoji_queue); q = emoji_queue.get(sn)
            if q:
                eid = q.pop()
                ch = emoji_cache.get(sn, {}).get(eid, '❤')
                cl = len(ch.encode('utf-16-le')) // 2
                kwargs_s = {"chat_id": update.effective_chat.id, "text": ch,
                            "entities": [MessageEntity(type='custom_emoji', offset=0, length=cl, custom_emoji_id=eid)]}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs_s["message_thread_id"] = tid
                _save_json(EMOJI_QUEUE_FILE, emoji_queue)
                try: await context.bot.send_message(**kwargs_s)
                except Exception as e: logger.warning(f"Trigger emoji fail: {e}")
            return
        # Check image keywords
        imgk = config.get('image_keywords', {}).get(gid_k, {})
        if kw in imgk:
            key = _img_kw_key(gid_k, kw)
            q = img_queue.get(key)
            if not q: _init_queue(key, img_cache, img_queue); q = img_queue.get(key)
            if q:
                fid_img = q.pop()
                kwargs_s = {"chat_id": update.effective_chat.id, "photo": fid_img}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs_s["message_thread_id"] = tid
                try: await context.bot.send_photo(**kwargs_s)
                except Exception as e: logger.warning(f"Trigger image fail: {e}")
            return
        return

    # --- Attach trigger collection ---
    wait = waiting_for_input.get(uid, '')
    if wait.startswith('attach:'):
        kw = wait.split(':', 1)[1]
        # Find group for this keyword
        target_gid = '_global'
        chat = update.effective_chat
        if chat and chat.type in ('group', 'supergroup'):
            target_gid = str(chat.id)
        else:
            target_gid = user_selected_group.get(uid, '_global')
        _add_keyword_trigger(target_gid, kw, fid)
        save_config(config)
        waiting_for_input.pop(uid, None)
        await update.message.reply_text(f"✅ 已绑定贴纸触发器 → 「{kw}」")
        return

    for sn, users in inline_hand.items():
        if uid in users and fid in users[uid]:
            users[uid].remove(fid)
            if not users[uid]: del users[uid]
            # Track pack usage for default pack selection
            _user_pack_usage.setdefault(uid, {})[sn] = _user_pack_usage.setdefault(uid, {}).get(sn, 0) + 1
            if _is_limited_set(sn):
                if sn in inline_shared_discard and uid in inline_shared_discard[sn]:
                    inline_shared_discard[sn].setdefault(uid, []).append(fid)
                    _save_json(SHARED_DISCARD_FILE, inline_shared_discard)
                else:
                    inline_discard.setdefault(sn, {}).setdefault(uid, []).append(fid)
                    _save_json(DISCARD_FILE, inline_discard)
                logger.info(f"Sticker discarded by {uid} to '{sn}': {len(inline_discard.get(sn,{}).get(uid,[]))} in discard")
            _save_hand()
            logger.info(f"Sticker played from {uid}'s hand '{sn}': {len(users.get(uid,[]))} remaining")
            if sn == 'unoame':
                from bot_uno import handle_uno_play
                await handle_uno_play(uid, fid, context)
            return

# ========== Photo handler for image keyword collection ==========
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle photo messages during image keyword collection."""
    uid = update.effective_user.id
    if uid not in waiting_for_input or waiting_for_input[uid] != "collect_image":
        return
    # Get largest photo (best quality)
    photo = update.message.photo[-1]
    img_collect.setdefault(uid, []).append(photo.file_id)
    total = len(img_collect[uid])
    kw = img_collect_kw.get(uid, '?')
    await update.message.reply_text(f"'{kw}': 已收集 {total} 张, 继续发送或 /cancel")

# ========== Return / discard handler (回复 d / f) ==========
async def handle_return_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """d: 贴纸回收至手牌 / 图片回收至牌库；f: 图片弃置；k: 保留"""
    msg = update.message
    if not msg:
        return
    text = (msg.text or msg.caption or '').strip().lower()
    if not text:
        return
    # 支持 dN 形式（如 d3 / d6）：回复贴纸向手牌添加 N 张相同的牌
    # 支持 d 50% / d50% 形式：按百分比缩放贴纸（<=100% 透明补齐，>100% 居中裁剪）
    add_n = 1
    scale_pct = None
    m_scale = re.fullmatch(r'd\s*(\d+)%', text)
    if m_scale:
        action = 'd'
        add_n = 1
        scale_pct = max(1, min(500, int(m_scale.group(1))))
    else:
        m_dn = re.fullmatch(r'd(\d+)', text)
        if m_dn:
            action = 'd'
            add_n = int(m_dn.group(1))
            if add_n < 1:
                add_n = 1
        elif text in ('d', 'f', 'k'):
            action = text
        else:
            return
    uid = update.effective_user.id
    reply = msg.reply_to_message
    logger.info(f"Return card: action={action}, uid={uid}, has_reply={reply is not None}, reply_has_photo={getattr(reply, 'photo', None) is not None}, reply_is_bot={getattr(getattr(reply, 'from_user', None), 'is_bot', None)}")
    if not reply:
        return

    # === 回复图片/视频/GIF + d：转成贴纸加入手牌（扩充功能）===
    if action == 'd' and (reply.photo or reply.video or reply.animation):
        mid = reply.message_id
        # 图片牌库采集图（bot 发出、在 _img_msg_map 中）走下方原有回收逻辑，不在此处理
        if not (reply.photo and mid in _img_msg_map):
            await _reply_media_to_sticker(update, context, reply, uid, add_n, msg, scale_pct)
            return

    # === Photo ===
    if reply.photo and reply.photo:
        if not (getattr(reply, 'via_bot', None) or (reply.from_user and reply.from_user.is_bot)):
            return
        mid = reply.message_id
        if mid not in _img_msg_map:
            await msg.reply_text("该图片不在任何图片牌库中（可能是重启前发的）。")
            return
        key, pool_fid = _img_msg_map[mid]
        if action == 'k':
            # Keep: move to img_kept (excluded from shuffle/draw)
            img_kept.setdefault(key, {}).setdefault(uid, []).append(pool_fid)
            _save_img_kept()
            # Remove from discard if present
            dc = img_discard.get(key, {}).get(uid, [])
            if pool_fid in dc:
                dc.remove(pool_fid)
                if not dc: del img_discard[key][uid]
                _save_img_state()
            kc = len(img_kept.get(key, {}).get(uid, []))
            await msg.reply_text(f"📌 已保留  |  保留区 {kc} 张")
        elif action == 'f':
            # Discard: move to discard pile
            img_discard.setdefault(key, {}).setdefault(uid, []).append(pool_fid)
            _save_img_state()
            # Remove from kept if present
            kc = img_kept.get(key, {}).get(uid, [])
            if pool_fid in kc:
                kc.remove(pool_fid)
                if not kc: del img_kept[key][uid]
                _save_img_kept()
            dc = img_discard[key][uid]
            await msg.reply_text(f"已弃置  |  弃牌堆 {len(dc)} 张")
        else:  # d → recycle to queue
            queue = img_queue.setdefault(key, [])
            queue.append(pool_fid)
            # Remove from discard if present
            dc = img_discard.get(key, {}).get(uid, [])
            if pool_fid in dc:
                dc.remove(pool_fid)
                if not dc: del img_discard[key][uid]
                _save_img_state()
            # Remove from kept if present
            kc = img_kept.get(key, {}).get(uid, [])
            if pool_fid in kc:
                kc.remove(pool_fid)
                if not kc: del img_kept[key][uid]
                _save_img_kept()
            remain = len(queue)
            total = len(img_cache.get(key, []))
            await msg.reply_text(f"已回收至牌库  |  牌库 {remain}/{total} 张")
        return

    # === Sticker: d/k reply actions ===
    if action not in ('d', 'k'):
        return
    if not reply.sticker or not reply.sticker.file_id:
        await msg.reply_text("请回复一条贴纸消息。")
        return

    fid = reply.sticker.file_id

    # --- d N%: 已存在的贴纸按百分比缩放后加入手牌（透明补齐 / 居中裁剪）---
    if action == 'd' and scale_pct:
        if reply.sticker.is_animated:
            await msg.reply_text("❌ 动态（tgs）贴纸暂不支持缩放")
            return
        try:
            r = await _sticker_to_scaled_fid(context.bot, reply.sticker,
                                             _extra_pack_admin_id(uid), scale_pct)
        except Exception as e:
            logger.warning(f"scale sticker failed: {e}")
            r = None
        if not r:
            await msg.reply_text("❌ 缩放贴纸失败")
            return
        new_fid, kind = r
        await _add_fid_to_manual_hand(uid, new_fid, kind, 1, msg, f" / 缩放{scale_pct}%")
        return

    # --- d: unblock ⛔ sticker back to hand ---
    if action == 'd':
        for sn, users in inline_kept.items():
            if 0 in users and fid in users[0]:
                users[0].remove(fid)
                if not users[0]: del users[0]
                if not users: del inline_kept[sn]
                _save_kept()
                # Add back to pool so it can be drawn again
                if fid not in inline_cache.get(sn, []):
                    inline_cache.setdefault(sn, []).append(fid)
                hl = inline_hand.setdefault(sn, {}).setdefault(uid, [])
                hl.extend([fid] * add_n)
                _save_hand()
                await msg.reply_text(f"♻️ ⛔已解除  |  手牌 {len(hl)} 张")
                return

    # --- k: keep card from hand/discard into permanent kept area ---
    if action == 'k':
        # Check if in hand
        for sn, users in inline_hand.items():
            if uid in users and fid in users[uid]:
                users[uid].remove(fid)
                if not users[uid]: del users[uid]
                _save_hand()
                inline_kept.setdefault(sn, {}).setdefault(uid, []).append(fid)
                _save_kept()
                await msg.reply_text(f"📌 已保留  |  保留区 {len(inline_kept[sn][uid])} 张")
                return
        # Check if in discard
        for sn, users in inline_discard.items():
            if uid in users and fid in users[uid]:
                users[uid].remove(fid)
                if not users[uid]: del users[uid]
                _save_json(DISCARD_FILE, inline_discard)
                inline_kept.setdefault(sn, {}).setdefault(uid, []).append(fid)
                _save_kept()
                await msg.reply_text(f"📌 已保留  |  保留区 {len(inline_kept[sn][uid])} 张")
                return
        # Check if sticker is in pack pool (just played / sent by bot)
        for sn, stickers in inline_cache.items():
            if fid in stickers:
                # Remove from queue if present (prevent Nw peeked cards from being in both)
                if sn in inline_queue and fid in inline_queue[sn]:
                    inline_queue[sn].remove(fid)
                    _save_json(INLINE_QUEUE_FILE, inline_queue)
                inline_kept.setdefault(sn, {}).setdefault(uid, []).append(fid)
                _save_kept()
                await msg.reply_text(f"📌 已保留  |  保留区 {len(inline_kept[sn][uid])} 张")
                return
        await msg.reply_text("该贴纸不在任何内联牌库中。")
        return

    # --- Existing inline discard/cache check ---
    for sn, users in inline_discard.items():
        if uid in users and fid in users[uid]:
            users[uid].remove(fid)
            if not users[uid]: del users[uid]
            hl = inline_hand.setdefault(sn, {}).setdefault(uid, [])
            hl.extend([fid] * add_n)
            _save_hand()
            _save_json(DISCARD_FILE, inline_discard)
            await msg.reply_text(f"♻️ 已回收  |  手牌 {len(hl)} 张")
            return

    for sn, stickers in inline_cache.items():
        if fid in stickers:
            # Remove from queue if present (prevent Nw peeked cards from being in both)
            if sn in inline_queue and fid in inline_queue[sn]:
                inline_queue[sn].remove(fid)
                _save_json(INLINE_QUEUE_FILE, inline_queue)
            hl = inline_hand.setdefault(sn, {}).setdefault(uid, [])
            hl.extend([fid] * add_n)
            _save_hand()
            await msg.reply_text(f"♻️ 已回收  |  手牌 {len(hl)} 张")
            return

    # --- 回复贴纸 d，直接加入「手牌」，无论是否在关键词里 ---
    man = inline_hand.setdefault(_MANUAL_SN, {}).setdefault(uid, [])
    if add_n == 1 and fid in man:
        await msg.reply_text(f"ℹ️ 该贴纸已在手牌中  |  手牌 {len(man)} 张")
        return
    man.extend([fid] * add_n)
    # 同步到 inline_cache，便于系统识别为合法包（仅内存态，重启不持久）
    ic = inline_cache.setdefault(_MANUAL_SN, [])
    if fid not in ic:
        ic.append(fid)
    _save_hand()
    await msg.reply_text(f"✅ 已加入手牌  |  手牌 {len(man)} 张")
    return


async def _add_to_extra_pack(bot, admin_id: int, sticker_bytes: bytes, fmt: str):
    """把一张贴纸加入 bot 自有额外包；包不存在则用这张图作为首张建包。返回包名或 None。

    关键：Telegram 静态贴纸必须恰好 512x512，不能用 1px 占位图建包，
    否则 createNewStickerSet 会报尺寸错误。因此直接用真实贴纸建包。
    """
    name = _get_extra_pack_name()
    if name:
        try:
            await bot.get_sticker_set(name=name)
            await bot.add_sticker_to_set(
                user_id=admin_id, name=name,
                sticker=InputSticker(sticker=sticker_bytes, emoji_list=["⭐"], format=fmt))
            return name
        except Exception as e:
            logger.warning(f"add to extra pack failed, will recreate: {e}")
            # 包可能已失效，落到下方重建
    # 包不存在或失效：用这张真实贴纸建包（首张即它）
    for i in range(1, 50):
        candidate = f"Extra{i}_by_{bot.username}"
        try:
            await bot.get_sticker_set(name=candidate)
        except Exception:
            name = candidate
            break
    if not name:
        return None
    try:
        await bot.create_new_sticker_set(
            user_id=admin_id, name=name,
            title=f"收录贴纸 {name.split('_by_')[0]}",
            stickers=[InputSticker(sticker=sticker_bytes, emoji_list=["⭐"], format=fmt)],
        )
        _set_extra_pack_name(name)
        logger.info(f"Created extra sticker pack: {name}")
        return name
    except Exception as e:
        logger.warning(f"Failed to create extra pack: {e}")
        return None


# ========== Reply media -> sticker helpers ==========
def _extra_pack_admin_id(uid):
    """贴纸包归属 bot 管理员（共享收录包）。"""
    aids = config.get('admin_ids') or []
    return aids[0] if aids else uid


def _ffmpeg_path():
    p = shutil.which('ffmpeg')
    if p:
        return p
    cand = r'C:\Users\Admin\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe'
    if os.path.exists(cand):
        return cand
    return 'ffmpeg'


def _scale_vf(pct: int | None) -> str:
    """生成视频贴纸缩放滤镜链（先适配 512，再按百分比缩放）。

    - pct 为 None/100：只做等比适配 + 透明补齐；
    - pct <  100：等比适配后缩小，pad 用透明补齐回 512；
    - pct >  100：等比适配后放大，先 pad 到 max(512, iw/ih) 再 crop 512 居中裁剪。
      （pad 与 crop 串联是为了同时覆盖"某一边超出、另一边不足"的混合情况）
    """
    fit = 'format=rgba,scale=512:512:force_original_aspect_ratio=decrease'
    tail = 'setsar=1'
    if not pct or pct == 100:
        return (f'{fit},'
                'pad=512:512:(ow-iw)/2:(oh-ih)/2:color=0x00000000,'
                f'{tail}')
    return (f'{fit},'
            f'scale=trunc(iw*{pct}/100/2)*2:trunc(ih*{pct}/100/2)*2,'
            r'pad=max(512\,iw):max(512\,ih):(ow-iw)/2:(oh-ih)/2:color=0x00000000,'
            f'crop=512:512,{tail}')


def _ffmpeg_input_decoder(src: str) -> list:
    """WebM 源必须显式指定输入解码器，否则透明背景会变成不透明黑。

    坑：ffmpeg 默认的（native）vp9 解码器**不合并 alpha 层**，解码带透明背景的
    WebM 得到的是 (0,0,0,255) 纯黑，再怎么 pad 透明都救不回来。必须用
    `-c:v libvpx-vp9` 作为输入解码器才能读出 alpha（得到 (0,0,0,0)）。
    反过来，普通 mp4(h264) 指定 libvpx-vp9 解码会直接失败，所以只对 EBML 头生效。
    """
    try:
        with open(src, 'rb') as fh:
            if fh.read(4) == b'\x1a\x45\xdf\xa3':  # EBML magic -> WebM/VP9
                return ['-c:v', 'libvpx-vp9']
    except Exception:
        pass
    return []


def _convert_video_to_webm(src: str, out: str, pct: int | None = None) -> bool:
    """用 ffmpeg 把视频/GIF 转成 Telegram 视频贴纸要求的 WEBM（512x512, <=3s, 无声、透明背景）。
    pct 不为 None 时按百分比缩放内容（<=100% 透明补齐，>100% 居中裁剪）。

    Telegram 视频贴纸规范要求 yuva420p（VP9 + alpha 通道），非正方形素材的补齐区域
    必须是透明的而不是黑边：先用 format=rgba 保证有 alpha，再 pad 用 0x00000000 透明填充，
    最后 -pix_fmt yuva420p 让 VP9 把 alpha 层写进 BlockAdditional（容器里表现为 alpha_mode=1）。
    """

    def _args(dec):
        return ([_ffmpeg_path(), '-y'] + dec + ['-i', src, '-t', '3', '-an',
                '-vf', _scale_vf(pct),
                '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-b:v', '0', '-crf', '32',
                out])

    dec = _ffmpeg_input_decoder(src)
    try:
        subprocess.run(_args(dec), check=True, capture_output=True, timeout=120)
        return os.path.getsize(out) > 0
    except Exception as e:
        if dec:  # 万一源是 VP8 等非 VP9 的 WebM，退回默认解码器再试一次
            logger.warning(f"video->webm (forced decoder) failed, retry: {e}")
            try:
                subprocess.run(_args([]), check=True, capture_output=True, timeout=120)
                return os.path.getsize(out) > 0
            except Exception as e2:
                logger.warning(f"video->webm failed: {e2}")
                return False
        logger.warning(f"video->webm failed: {e}")
        return False


def _extract_first_frame(src: str, out: str) -> bool:
    """用 ffmpeg 抽取视频/GIF 首帧为 PNG（512x512，补齐区域透明）。"""
    dec = _ffmpeg_input_decoder(src)
    try:
        subprocess.run(
            [_ffmpeg_path(), '-y'] + dec + ['-i', src, '-vframes', '1',
             '-vf', 'format=rgba,scale=512:512:force_original_aspect_ratio=decrease,'
                    'pad=512:512:(ow-iw)/2:(oh-ih)/2:color=0x00000000,setsar=1',
             out],
            check=True, capture_output=True, timeout=60)
        return os.path.getsize(out) > 0
    except Exception as e:
        if dec:
            logger.warning(f"frame extract (forced decoder) failed, retry: {e}")
            try:
                subprocess.run(
                    [_ffmpeg_path(), '-y', '-i', src, '-vframes', '1',
                     '-vf', 'format=rgba,scale=512:512:force_original_aspect_ratio=decrease,'
                            'pad=512:512:(ow-iw)/2:(oh-ih)/2:color=0x00000000,setsar=1',
                     out],
                    check=True, capture_output=True, timeout=60)
                return os.path.getsize(out) > 0
            except Exception as e2:
                logger.warning(f"frame extract failed: {e2}")
                return False
        logger.warning(f"frame extract failed: {e}")
        return False


async def _ensure_extra_pack_video(bot, admin_id: int):
    """确保 bot 自有额外视频贴纸包存在，返回包名（不存在则返回 None，需先建）。"""
    name = _get_extra_pack_video_name()
    if name:
        try:
            await bot.get_sticker_set(name=name)
            return name
        except Exception:
            pass
    return None


async def _create_video_pack(bot, admin_id: int, webm: bytes):
    """用首个视频贴纸创建视频贴纸包，返回包名。"""
    for i in range(1, 50):
        candidate = f"ExtraV{i}_by_{bot.username}"
        try:
            await bot.get_sticker_set(name=candidate)
        except Exception:
            name = candidate
            break
    else:
        return None
    try:
        await bot.create_new_sticker_set(
            user_id=admin_id, name=name, title=f"收录视频 {name.split('_by_')[0]}",
            stickers=[InputSticker(sticker=webm, emoji_list=["⭐"], format="video")],
        )
        _set_extra_pack_video_name(name)
        logger.info(f"Created extra video sticker pack: {name}")
        return name
    except Exception as e:
        logger.warning(f"Failed to create video pack: {e}")
        return None


async def _push_static_sticker(bot, admin_id: int, png: bytes):
    """512 PNG 静态贴纸入库（额外包），返回 (file_id, 'static') 或 None。"""
    name = await _add_to_extra_pack(bot, admin_id, png, "static")
    if not name:
        return None
    ss = await bot.get_sticker_set(name=name)
    return ss.stickers[-1].file_id, 'static'


async def _push_video_sticker(bot, admin_id: int, webm: bytes):
    """WEBM 视频贴纸入库（额外视频包），返回 (file_id, 'video') 或 None。"""
    existing = await _ensure_extra_pack_video(bot, admin_id)
    if existing:
        try:
            await bot.add_sticker_to_set(user_id=admin_id, name=existing,
                sticker=InputSticker(sticker=webm, emoji_list=["⭐"], format="video"))
            ss = await bot.get_sticker_set(name=existing)
            return ss.stickers[-1].file_id, 'video'
        except Exception as e:
            logger.warning(f"add video sticker failed, try new pack: {e}")
    name = await _create_video_pack(bot, admin_id, webm)
    if name:
        ss = await bot.get_sticker_set(name=name)
        return ss.stickers[-1].file_id, 'video'
    return None


async def _photo_to_sticker_fid(bot, reply, admin_id: int, scale_pct: int | None = None):
    """图片 -> 512 PNG 静态贴纸 -> 额外包，返回 (file_id, 'static')。

    scale_pct 不为 None 时按百分比缩放（先适配 512，再按百分比缩放 + 透明补齐/居中裁剪）。
    """
    from bot_makepack import _resize_sticker, _scale_sticker_pct
    photo = reply.photo[-1]
    f = await bot.get_file(photo.file_id)
    data = await f.download_as_bytearray()
    png = _resize_sticker(bytes(data), 512)
    if scale_pct:
        png = _scale_sticker_pct(png, scale_pct, 512)
    return await _push_static_sticker(bot, admin_id, png)


async def _video_to_sticker_fid(bot, reply, admin_id: int, scale_pct: int | None = None):
    """视频/GIF -> 优先动态贴纸(WEBM)，失败回退静态首帧。返回 (file_id, 'video'|'static') 或 None。"""
    from bot_makepack import _resize_sticker, _scale_sticker_pct
    src_file_id = reply.video.file_id if reply.video else reply.animation.file_id
    f = await bot.get_file(src_file_id)
    data = await f.download_as_bytearray()
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, 'in.mp4')
    out_webm = os.path.join(tmp, 'out.webm')
    out_png = os.path.join(tmp, 'frame.png')
    try:
        with open(src, 'wb') as fh:
            fh.write(data)
        # --- 优先：动态视频贴纸 ---
        if _convert_video_to_webm(src, out_webm, scale_pct):
            webm = open(out_webm, 'rb').read()
            r = await _push_video_sticker(bot, admin_id, webm)
            if r:
                return r
        # --- 回退：首帧 -> 静态贴纸 ---
        if _extract_first_frame(src, out_png):
            png = _resize_sticker(open(out_png, 'rb').read(), 512)
            if scale_pct:
                png = _scale_sticker_pct(png, scale_pct, 512)
            return await _push_static_sticker(bot, admin_id, png)
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


async def _sticker_to_scaled_fid(bot, sticker, admin_id: int, pct: int):
    """已有贴纸按百分比缩放后重新入库，返回 (file_id, 'video'|'static') 或 None。"""
    from bot_makepack import _resize_sticker, _scale_sticker_pct
    f = await bot.get_file(sticker.file_id)
    data = await f.download_as_bytearray()
    if getattr(sticker, 'is_video', False):
        tmp = tempfile.mkdtemp()
        src = os.path.join(tmp, 'in.webm')
        out_webm = os.path.join(tmp, 'out.webm')
        try:
            with open(src, 'wb') as fh:
                fh.write(data)
            if not _convert_video_to_webm(src, out_webm, pct):
                return None
            return await _push_video_sticker(bot, admin_id, open(out_webm, 'rb').read())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    png = _resize_sticker(bytes(data), 512)
    png = _scale_sticker_pct(png, pct, 512)
    return await _push_static_sticker(bot, admin_id, png)


async def _add_fid_to_manual_hand(uid, fid, kind, add_n, msg, extra=""):
    """把贴纸 file_id 加入手动手牌并回复。"""
    man = inline_hand.setdefault(_MANUAL_SN, {}).setdefault(uid, [])
    if add_n == 1 and fid in man:
        await msg.reply_text(f"ℹ️ 该贴纸已在手牌中  |  手牌 {len(man)} 张")
        return
    man.extend([fid] * add_n)
    ic = inline_cache.setdefault(_MANUAL_SN, [])
    if fid not in ic:
        ic.append(fid)
    _save_hand()
    label = "视频贴纸" if kind == 'video' else "贴纸"
    await msg.reply_text(f"✅ 已加入手牌（{label}{extra}）  |  手牌 {len(man)} 张")


async def _reply_media_to_sticker(update, context, reply, uid, add_n, msg, scale_pct=None):
    """回复图片/视频/GIF + d（可带 N% 缩放）：转成贴纸后加入手动手牌。"""
    bot = context.bot
    try:
        admin = _extra_pack_admin_id(uid)
        if reply.video or reply.animation:
            result = await _video_to_sticker_fid(bot, reply, admin, scale_pct)
        else:
            result = await _photo_to_sticker_fid(bot, reply, admin, scale_pct)
        if not result:
            await msg.reply_text("❌ 转换贴纸失败（图片/视频无法处理）")
            return
        fid, kind = result
        extra = f" / 缩放{scale_pct}%" if scale_pct else ""
        await _add_fid_to_manual_hand(uid, fid, kind, add_n, msg, extra)
    except Exception as e:
        logger.warning(f"reply media to sticker error: {e}")
        await msg.reply_text(f"❌ 转换失败: {e}")
