#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_handlers.py - 消息/命令处理器 (keyword, sticker, emoji, image, inline, counter, return-card)
import json, logging, os, random, re, asyncio
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
    _get_img_kw, _img_kw_key, _img_get_files, _img_get_mode, _img_set_mode,
    _get_comp_kw, _comp_get_groups, _comp_get_mode, _comp_set_mode,
    _img_get_stitch,
    _get_keyword_extras, _add_keyword_extra, _get_extra_pack_name, _set_extra_pack_name,
    _is_limited_set, _get_group_name, _resolve_group, _refresh_common_groups,
    _filter_blocked_stickers,
    _inline_is_shared, _inline_set_shared, _get_inline_queue, _get_inline_discard,
    _set_inline_queue, _init_shared_pool, _save_shared_state,
    _init_queue, _all_sticker_sets,
    _save_json, _save_hand, _save_inline_state, _save_img_state, _load_json,
    _save_kept, _load_kept,
    _add_keyword_trigger, _remove_keyword_trigger, _get_trigger_kw,
    _save_img_kept, _load_img_kept,
    load_config, save_config,
    CONFIG_FILE, QUEUE_FILE, INLINE_QUEUE_FILE, DISCARD_FILE, HAND_FILE, KEPT_FILE, IMG_KEPT_FILE,
    EMOJI_QUEUE_FILE, EMOJI_DISCARD_FILE, SHARED_QUEUE_FILE, SHARED_DISCARD_FILE, STICKER_DISCARD_FILE,
    IMG_QUEUE_FILE, IMG_DISCARD_FILE,
    _show_main_menu_text,
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
    user = update.effective_user; user_id = user.id
    group_id = _resolve_group(update, user_id)

    # On first /yu in private chat, check common groups once
    chat = update.effective_chat
    if chat and chat.type == 'private' and user_id not in user_common_groups:
        await _refresh_common_groups(context.bot, user_id)

    text, markup = _show_main_menu_text(user, group_id)
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


async def help_command(update, context):
    await update.message.reply_text(
        "关键词使用方式:\n"
        "关键词 N: 抽取N张卡牌\n"
        "关键词 N-: 从弃牌堆回收N张入牌库(内联/Emoji)\n"
        "关键词 0: 全部弃牌洗入牌库\n"
        "关键词 0d: 牌库完全重置为初始状态\n"
        "/refresh 关键词: 从贴纸包/Emoji包同步最新内容\n"
        "关键词 Nd: 明牌抽取N张卡牌\n"
        "关键词 Nw: 展示牌堆顶N张卡牌\n"
        "关键词 Nf / N! / N！: 弃置牌堆顶N张卡牌入弃牌区\n"
        "d: 回复贴纸 d 回收至手牌；回复图片 d 回收至牌库\n"
        "f: 回复图片 f 弃置（跳过后再抽）\n"
        "数字-数字-数字: 连续打出多张卡牌\n"
        "数字-数字-数字/: 连续明牌打出多张卡牌\n"
        "数字~数字: 打出序号连贯的卡牌"
    )


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
    user_id = update.effective_user.id
    group_id = _resolve_group(update, user_id)
    sk = _get_sk(group_id)
    if not sk: return await update.message.reply_text('无关键词')
    await update.message.reply_text("\n".join(f"  {k} -> {_get_set(k, group_id)}" for k in sk))

async def add_sticker_keyword(update, context):
    user_id = update.effective_user.id
    if user_id not in config.get('admin_ids',[]): return await update.message.reply_text('仅管理员')
    if len(context.args) < 2: return await update.message.reply_text('/addsticker <关键词> <包名>')
    kw, sn = context.args[0], context.args[1]
    group_id = user_selected_group.get(user_id, '_global')
    gid = str(group_id)
    try:
        ss = await context.bot.get_sticker_set(name=sn); stickers = [s.file_id for s in ss.stickers]
        sticker_cache[sn] = stickers; _init_queue(sn, sticker_cache, sticker_queue)
        config.setdefault('sticker_keywords',{}).setdefault(gid,{})[kw] = {"set": sn, "mode": "sequential"}
        save_config(config)
        gname = _get_group_name(group_id)
        await update.message.reply_text(f"添加成功! [{gname}] {kw} -> {sn} ({len(stickers)}张)")
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
        config.setdefault('emoji_keywords', {}).setdefault(gid, {})[kw] = {"set": sn, "mode": "random"}
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
                config.setdefault('emoji_keywords', {}).setdefault(gid, {})[kw] = {"set": sn, "mode": "random"}
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
            parts = text.strip().split(maxsplit=1)
            if len(parts) < 2: return await update.message.reply_text('格式: <关键词> <链接>')
            kw, link = parts[0], parts[1]
            m = re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', link); sn = m.group(1) if m else link.strip().split('/')[-1].split('?')[0]
            if not sn: return await update.message.reply_text('无法提取包名')
            try:
                ss = await context.bot.get_sticker_set(name=sn); sticks = [s.file_id for s in ss.stickers]
                config.setdefault('sticker_keywords',{}).setdefault(gid,{})[kw] = {"set": sn, "mode": "sequential"}
                save_config(config)
                sticker_cache[sn] = sticks; _init_queue(sn, sticker_cache, sticker_queue)
                gname = _get_group_name(gid)
                await update.message.reply_text(f"添加成功! [{gname}] {kw} -> {sn} ({len(sticks)}张)")
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
            parts = text.strip().split(maxsplit=1)
            if len(parts) < 2: return await update.message.reply_text('格式: <关键词> <链接>')
            kw, link = parts[0], parts[1]
            m = re.search(r'add(?:stickers|emoji)/([a-zA-Z0-9_]+)', link); sn = m.group(1) if m else link.strip().split('/')[-1].split('?')[0]
            if not sn: return await update.message.reply_text('无法提取包名')
            try:
                ss = await context.bot.get_sticker_set(name=sn); sticks = _filter_blocked_stickers(sn, ss.stickers)
                config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{})[kw] = {"set": sn, "mode": "limited"}
                save_config(config)
                inline_cache[sn] = sticks; _init_queue(sn, inline_cache, inline_queue)
                inline_hand[sn] = {}
                _save_hand()
                gname = _get_group_name(gid)
                await update.message.reply_text(f"内联添加成功! [{gname}] {kw} -> {sn} ({len(sticks)}张)")
            except Exception as e: await update.message.reply_text(f"失败: {e}")
            return

    # -- Index send: 1-2-3/  or  1-2-3 (play cards from hand by position)
    idx_match = re.match(r'^(\d+(?:-\d+)+)(/?)$', text.strip())
    range_match = re.match(r'^(\d+)~(\d+)(/?)$', text.strip())
    if idx_match or range_match:
        uid = user_id
        # Prefer last-used inline pack
        last = _last_inline_kw.get(uid)
        target_sn = last['sn'] if last else None
        sn_order = [target_sn] if target_sn else []
        sn_order += [sn for sn in inline_hand if sn != target_sn]
        for sn in sn_order:
            users = inline_hand.get(sn, {})
            if uid in users and users[uid]:
                hand = users[uid]
                if range_match:
                    start, end = int(range_match.group(1)), int(range_match.group(2))
                    if start > end: start, end = end, start
                    indices = list(range(start, end + 1))
                    send_s = (range_match.group(3) == '/')
                else:
                    indices = [int(x) for x in idx_match.group(1).split('-')]
                    send_s = (idx_match.group(2) == '/')
                played = []
                for idx in sorted(set(indices), reverse=True):
                    i = idx - 1
                    if 0 <= i < len(hand):
                        played.insert(0, hand.pop(i))
                # Save state BEFORE sending (crash-safe)
                if _is_limited_set(sn):
                    if sn in inline_shared_discard and uid in inline_shared_discard[sn]:
                        dc = inline_shared_discard[sn].setdefault(uid, [])
                    else:
                        dc = inline_discard.setdefault(sn, {}).setdefault(uid, [])
                    dc.extend(played)
                    _save_json(DISCARD_FILE, inline_discard)
                    _save_json(SHARED_DISCARD_FILE, inline_shared_discard)
                if not hand:
                    del users[uid]
                _save_hand()
                if send_s:
                    for fid in played:
                        kwargs = {"chat_id": update.effective_chat.id, "sticker": fid}
                        tid = getattr(update.message, 'message_thread_id', None)
                        if tid: kwargs["message_thread_id"] = tid
                        try: await context.bot.send_sticker(**kwargs)
                        except Exception as se: logger.warning(f"Play fail: {se}")
                await update.message.reply_text(f"已打出 {len(played)} 张  |  手牌 {len(hand)} 张")
                return
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
        chars = []    # 拼接的 emoji 字符
        entities = [] # 对应的 MessageEntity 列表
        for i in range(count):
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
            emoji_char = emoji_map.get(eid, '\u2764')  # fallback to ❤ if not found
            if emoji_mode == 'limited':
                emoji_discard.setdefault(sn, {}).setdefault(user_id, []).append(eid)
            # 记录 offset（UTF-16 编码下的偏移量）
            offset = sum(len(c.encode('utf-16-le')) // 2 for c in chars)
            char_len = len(emoji_char.encode('utf-16-le')) // 2
            chars.append(emoji_char)
            entities.append(MessageEntity(type='custom_emoji', offset=offset, length=char_len, custom_emoji_id=eid))
            drawn += 1
        # 一次性发送所有 emoji
        if drawn:
            try:
                kwargs = {"chat_id": update.effective_chat.id, "text": ''.join(chars), "entities": entities}
                tid = getattr(update.message, 'message_thread_id', None)
                if tid: kwargs["message_thread_id"] = tid
                await context.bot.send_message(**kwargs)
            except Exception as se:
                logger.warning(f"Emoji batch send fail: {se}")
        if drawn:
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

        if shared and (sn not in inline_shared_queue or uid not in inline_shared_queue.get(sn, {})):
            _init_shared_pool(sn, uid)

        def _iq_get(): return inline_shared_queue[sn][uid] if shared else _iq_get()
        def _iq_set(v): 
            if shared: inline_shared_queue[sn][uid] = v; _save_shared_state()
            else: _iq_set(v);
        def _id_get(): return inline_shared_discard.get(sn, {}) if shared else _id_get()
        def _id_clear(): 
            if shared: inline_shared_discard[sn] = {}; _save_shared_state()
            else: _id_clear(); _id_save()
        def _id_save():
            if shared: _save_shared_state()
            else: _id_save()

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
                sid = random.choice(stickers)
            else:
                queue = sticker_queue.get(sn)
                if not queue:
                    if mode_s == 'limited': break
                    try:
                        ss = await context.bot.get_sticker_set(name=sn); stickers = [s.file_id for s in ss.stickers]; sticker_cache[sn] = stickers
                    except Exception: break
                    _init_queue(sn, sticker_cache, sticker_queue); queue = sticker_queue.get(sn)
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

        if merge_on:
            # Mode 1: merge all packs
            merged = []
            for sn, users in inline_hand.items():
                if sn not in valid_packs or uid not in users: continue
                for fid in users[uid]:
                    merged.append((sn, fid))
            if merged:
                results = [InlineQueryResultCachedSticker(
                    id=f"h_{sn}_{i:03d}", sticker_file_id=fid
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
            results = [InlineQueryResultCachedSticker(id=f"h_{best_sn}_{i:03d}", sticker_file_id=fid)
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
            # Track last used
            _last_inline_kw[uid] = {'sn': sn, 'kw': keyword}
            hand = inline_hand.get(sn, {}).get(uid, [])
            if not hand:
                try:
                    await update.inline_query.answer([], cache_time=1,
                        switch_pm_text="你的手牌为空", switch_pm_parameter="empty")
                except Exception: pass
                return
            results = [InlineQueryResultCachedSticker(id=f"h_{sn}_{i:03d}", sticker_file_id=fid)
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
    parts = result_id.split('_', 2)
    if len(parts) < 3: return
    sn = parts[1]
    user_hand = inline_hand.get(sn, {}).get(uid, [])
    if not user_hand: return
    try:
        idx = int(parts[2])
        if idx < len(user_hand):
            played = user_hand.pop(idx)
            if _is_limited_set(sn):
                if sn in inline_shared_discard and uid in inline_shared_discard[sn]:
                    inline_shared_discard[sn].setdefault(uid, []).append(played)
                    _save_json(SHARED_DISCARD_FILE, inline_shared_discard)
                else:
                    inline_discard.setdefault(sn, {}).setdefault(uid, []).append(played)
                    _save_json(DISCARD_FILE, inline_discard)
                logger.info(f"Card discarded by {uid} to '{sn}': {len(inline_discard[sn][uid])} in discard")
    except: pass
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
        # Check emoji keywords
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
    if not msg or msg.text is None:
        return
    action = msg.text.strip().lower()
    if action not in ('d', 'f', 'k'):
        return
    uid = update.effective_user.id
    reply = msg.reply_to_message
    logger.info(f"Return card: action={action}, uid={uid}, has_reply={reply is not None}, reply_has_photo={getattr(reply, 'photo', None) is not None}, reply_is_bot={getattr(getattr(reply, 'from_user', None), 'is_bot', None)}")
    if not reply:
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
                inline_hand.setdefault(sn, {}).setdefault(uid, []).append(fid)
                _save_hand()
                await msg.reply_text(f"♻️ ⛔已解除  |  手牌 {len(inline_hand[sn][uid])} 张")
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
            inline_hand.setdefault(sn, {}).setdefault(uid, []).append(fid)
            _save_hand()
            _save_json(DISCARD_FILE, inline_discard)
            await msg.reply_text(f"♻️ 已回收  |  手牌 {len(inline_hand[sn][uid])} 张")
            return

    for sn, stickers in inline_cache.items():
        if fid in stickers:
            # Remove from queue if present (prevent Nw peeked cards from being in both)
            if sn in inline_queue and fid in inline_queue[sn]:
                inline_queue[sn].remove(fid)
                _save_json(INLINE_QUEUE_FILE, inline_queue)
            inline_hand.setdefault(sn, {}).setdefault(uid, []).append(fid)
            _save_hand()
            await msg.reply_text(f"♻️ 已回收  |  手牌 {len(inline_hand[sn][uid])} 张")
            return

    # --- NEW: sticker not in any existing pack → add to last-used inline keyword ---
    last = _last_inline_kw.get(uid)
    if not last:
        await msg.reply_text("该贴纸不在任何内联牌库中。\n请先使用一次内联关键词（如「抽牌」），再回复 d。")
        return
    kw, target_sn = last['kw'], last['sn']

    # Find group_id for this keyword
    target_gid = '_global'
    for gid_k, kws in config.get('inline_sticker_keywords', {}).items():
        if kw in kws:
            target_gid = gid_k
            break

    # Get extra pack name
    pack_name = await _ensure_extra_pack(context.bot, config.get('admin_ids', [uid])[0] if config.get('admin_ids') else uid)
    if not pack_name:
        await msg.reply_text("贴纸上传失败：无法创建额外贴纸包。")
        return

    # Download the sticker
    try:
        sticker_file = await context.bot.get_file(fid)
        sticker_data = await sticker_file.download_as_bytearray()
    except Exception as e:
        await msg.reply_text(f"下载贴纸失败: {e}")
        return

    # Upload to extra pack
    try:
        await context.bot.add_sticker_to_set(
            user_id=config.get('admin_ids', [uid])[0] if config.get('admin_ids') else uid,
            name=pack_name,
            sticker=InputSticker(sticker=bytes(sticker_data), emoji_list=["⭐"], format="static"),
        )
        # Refresh sticker pack cache
        ss = await context.bot.get_sticker_set(name=pack_name)
        new_file_ids = [s.file_id for s in ss.stickers]
        # The newly added sticker is the last one
        new_fid = new_file_ids[-1] if new_file_ids else None
        if not new_fid:
            await msg.reply_text("上传成功但无法获取贴纸ID。")
            return
    except Exception as e:
        await msg.reply_text(f"上传贴纸失败: {e}")
        return

    # Add to keyword extras + inline cache
    _add_keyword_extra(kw, new_fid, target_gid)
    # Update inline cache
    inline_cache.setdefault(target_sn, [])
    if new_fid not in inline_cache[target_sn]:
        inline_cache[target_sn].append(new_fid)
    # Also add extra pack stickers to cache
    if pack_name not in inline_cache:
        inline_cache[pack_name] = new_file_ids
    else:
        inline_cache[pack_name] = list(set(inline_cache[pack_name] + new_file_ids))

    # Add to user's hand
    inline_hand.setdefault(target_sn, {}).setdefault(uid, []).append(new_fid)
    _save_hand()

    extra_count = len(_get_keyword_extras(kw, target_gid))
    hand_count = len(inline_hand[target_sn][uid])
    total_in_pool = len(inline_cache.get(target_sn, []))
    await msg.reply_text(
        f"✅ 已收录到「{kw}」牌库\n"
        f"手牌 +1 ({hand_count}张)  |  牌库 +1 ({total_in_pool}张)  |  累计收录 {extra_count}张"
    )
    return


async def _ensure_extra_pack(bot, admin_id: int):
    """确保 bot 自有额外贴纸包存在，返回包名。"""
    name = _get_extra_pack_name()
    if name:
        try:
            await bot.get_sticker_set(name=name)
            return name
        except Exception:
            pass  # Pack doesn't exist anymore, recreate
    # Create new pack
    for i in range(1, 50):
        candidate = f"Extra_by_yu{i}_bot"
        try:
            await bot.get_sticker_set(name=candidate)
        except Exception:
            name = candidate
            break
    if not name:
        return None
    # Need an initial sticker to create the pack — use a 1-pixel transparent PNG
    import struct, zlib
    def _make_1px_png():
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
        ihdr_crc = zlib.crc32(b'IHDR' + ihdr)
        ihdr_chunk = struct.pack('>I', 13) + b'IHDR' + ihdr + struct.pack('>I', ihdr_crc)
        raw = b'\x00' * 1
        compressed = zlib.compress(raw)
        idat_crc = zlib.crc32(b'IDAT' + compressed)
        idat_chunk = struct.pack('>I', len(compressed)) + b'IDAT' + compressed + struct.pack('>I', idat_crc)
        iend_crc = zlib.crc32(b'IEND')
        iend_chunk = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', iend_crc)
        return sig + ihdr_chunk + idat_chunk + iend_chunk
    try:
        await bot.create_new_sticker_set(
            user_id=admin_id, name=name,
            title=f"收录贴纸 {name.split('_by_')[0]}",
            stickers=[InputSticker(sticker=_make_1px_png(), emoji_list=["⭐"], format="static")],
            sticker_type="static",
        )
        _set_extra_pack_name(name)
        logger.info(f"Created extra sticker pack: {name}")
        return name
    except Exception as e:
        logger.warning(f"Failed to create extra pack: {e}")
        return None
