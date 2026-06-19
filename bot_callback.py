#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_callback.py - 内联按钮回调处理器
from bot_config import (
    config, sticker_cache, sticker_queue, inline_cache, inline_queue,
    inline_hand, inline_discard, emoji_cache, emoji_queue, emoji_discard,
    img_cache, img_queue, img_discard,
    waiting_for_input, user_selected_group, user_common_groups, pending_copy,
    _get_sk, _get_ik, _get_ek, _get_set, _get_mode, _set_mode,
    _get_mode_label, _next_mode,
    _get_exact, _set_exact,
    _inline_get_set, _inline_get_mode, _inline_set_mode,
    _emoji_get_set, _emoji_get_mode, _emoji_set_mode,
    _inline_get_sort, _inline_set_sort,
    _inline_is_shared, _inline_set_shared,
    _get_img_kw, _img_kw_key, _img_get_files, _img_get_mode, _img_set_mode,
    _img_get_stitch, _img_set_stitch,
    _get_comp_kw, _comp_get_groups,
    img_collect, img_collect_kw, img_collect_composite,
    _is_limited_set, _get_group_name, _resolve_group,
    _init_queue,
    _save_json, _save_hand,
    save_config,
    DISCARD_FILE, INLINE_QUEUE_FILE,
    _show_main_menu_text,
    _build_copy_target_keyboard, _build_group_select_keyboard, _build_list_keyboard,
    _get_tk, text_game_state,
    logger,
)
from bot_game import _do_array_join, _array_show_board
from bot_text_game import (
    handle_text_join, handle_text_start,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    user = query.from_user; user_id = user.id; adm = user_id in config.get('admin_ids',[])

    # Resolve management group
    gid = str(query.message.chat.id) if query.message.chat and query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')

    if query.data == 'select_group':
        common = user_common_groups.get(user_id, {})
        if common:
            count_text = f"共 {len(common)} 个共同群组"
        else:
            count_text = "暂未找到共同群组（请先将 Bot 加入群组）"
        await query.edit_message_text(
            f"选择要管理的群组\n(当前: {_get_group_name(gid)})\n{count_text}:",
            reply_markup=_build_group_select_keyboard(user_id, common)
        )

    elif query.data == 'manage_keywords':
        """关键词管理子菜单"""
        gname = _get_group_name(gid)
        await query.edit_message_text(
            f"[{gname}] 关键词管理\n\n管理贴纸、符号、内联、图片、文本关键词。",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("贴纸", callback_data='list_sticker'),
                 InlineKeyboardButton("符号", callback_data='list_emoji')],
                [InlineKeyboardButton("图片", callback_data='list_image'),
                 InlineKeyboardButton("拼接图片", callback_data='list_composite')],
                [InlineKeyboardButton("内联模式", callback_data='list_inline'),
                 InlineKeyboardButton("文本", callback_data='list_text')],
                [InlineKeyboardButton("返回主菜单", callback_data='back_to_start')],
            ])
        )

    elif query.data.startswith('setgroup_'):
        new_gid = query.data.replace('setgroup_', '', 1)
        user_selected_group[user_id] = new_gid
        # Back to main menu
        text, markup = _show_main_menu_text(user, new_gid)
        await query.edit_message_text(text, reply_markup=markup)

    elif query.data.startswith('group_page_'):
        page = int(query.data.replace('group_page_', '', 1))
        common = user_common_groups.get(user_id, {})
        if common:
            count_text = f"共 {len(common)} 个共同群组"
        else:
            count_text = "暂未找到共同群组"
        await query.edit_message_text(
            f"选择要管理的群组\n(当前: {_get_group_name(gid)})\n{count_text}:",
            reply_markup=_build_group_select_keyboard(user_id, common, page)
        )

    elif query.data == 'list_inline':
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        sk = _get_ik(gid)
        gname = _get_group_name(gid)
        if not sk:
            return await query.edit_message_text(
                f"[{gname}] 还没有内联关键词.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("添加内联关键词", callback_data='add_inline'),
                     InlineKeyboardButton("返回", callback_data='manage_keywords')]
                ]))
        kb = _build_list_keyboard(inline=True, group_id=gid)
        kb.append([InlineKeyboardButton("添加内联关键词", callback_data='add_inline'),
                    InlineKeyboardButton("返回", callback_data='manage_keywords')])
        await query.edit_message_text(f"[{gname}] 内联模式关键词:\n抽牌加入手牌, inline打出手牌.",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == 'add_inline':
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        waiting_for_input[user_id] = "add_inline"
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] 发送 <关键词> <链接>\n例如: 抽卡 https://t.me/addstickers/Pack\n/cancel 取消.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("取消返回", callback_data='cancel_replace')]]))

    elif query.data.startswith('replace_inline_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('replace_inline_','',1); waiting_for_input[user_id] = f"replace_inline:{kw}"
        sn = _inline_get_set(kw, gid); mode = _inline_get_mode(kw, gid); sort_on = _inline_get_sort(kw, gid)
        exact = _get_exact('inline_sticker_keywords', kw, gid); cur_shared = _inline_is_shared(kw, gid)
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] *{kw}* -> {sn}\n发送关键词改名，或发送链接替换.\n/cancel 取消.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_inline_per_{kw}')],
                [InlineKeyboardButton(f"排序: {'是' if sort_on else '否'} (切换)", callback_data=f'toggle_inline_sort_{kw}')],
                [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_inline_{kw}')],
                [InlineKeyboardButton(f"共享: {'🔀' if cur_shared else '📌'} (切换)", callback_data=f'toggle_shared_{kw}')],
                [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
            ]))

    elif query.data.startswith('toggle_inline_per_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_inline_per_','',1)
        cur = _inline_get_mode(kw, gid); nm = _next_mode(cur)
        _inline_set_mode(kw, nm, gid)
        await query.answer(text=f"'{kw}' {_get_mode_label(nm)}")
        sn = _inline_get_set(kw, gid); sort_on = _inline_get_sort(kw, gid)
        exact = _get_exact('inline_sticker_keywords', kw, gid); cur_shared = _inline_is_shared(kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(nm)} (切换)", callback_data=f'toggle_inline_per_{kw}')],
            [InlineKeyboardButton(f"排序: {'是' if sort_on else '否'} (切换)", callback_data=f'toggle_inline_sort_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_inline_{kw}')],
            [InlineKeyboardButton(f"共享: {'🔀' if cur_shared else '📌'} (切换)", callback_data=f'toggle_shared_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('toggle_inline_sort_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_inline_sort_','',1)
        cur = _inline_get_sort(kw, gid); nm = not cur
        _inline_set_sort(kw, nm, gid)
        await query.answer(text=f"'{kw}' 排序: {'是' if nm else '否'}")
        mode = _inline_get_mode(kw, gid); sort_on = _inline_get_sort(kw, gid)
        exact = _get_exact('inline_sticker_keywords', kw, gid); cur_shared = _inline_is_shared(kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_inline_per_{kw}')],
            [InlineKeyboardButton(f"排序: {'是' if sort_on else '否'} (切换)", callback_data=f'toggle_inline_sort_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_inline_{kw}')],
            [InlineKeyboardButton(f"共享: {'🔀' if cur_shared else '📌'} (切换)", callback_data=f'toggle_shared_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('toggle_exact_inline_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_exact_inline_', '', 1)
        cur = _get_exact('inline_sticker_keywords', kw, gid); nm = not cur
        _set_exact('inline_sticker_keywords', kw, nm, gid)
        await query.answer(text=f"'{kw}' 精准: {'✔' if nm else '✘'}")
        mode = _inline_get_mode(kw, gid); sort_on = _inline_get_sort(kw, gid)
        cur_shared = _inline_is_shared(kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_inline_per_{kw}')],
            [InlineKeyboardButton(f"排序: {'是' if sort_on else '否'} (切换)", callback_data=f'toggle_inline_sort_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if nm else '✘'} (切换)", callback_data=f'toggle_exact_inline_{kw}')],
            [InlineKeyboardButton(f"共享: {'🔀' if cur_shared else '📌'} (切换)", callback_data=f'toggle_shared_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('toggle_shared_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_shared_', '', 1)
        cur = _inline_is_shared(kw, gid); nm = not cur
        _inline_set_shared(kw, nm, gid)
        label = '🔀 共享模式' if nm else '📌 关闭共享'
        await query.answer(text=f"'{kw}' → {label}")
        # Refresh the replace_inline_ menu
        sn = _inline_get_set(kw, gid); mode = _inline_get_mode(kw, gid); sort_on = _inline_get_sort(kw, gid)
        exact = _get_exact('inline_sticker_keywords', kw, gid); cur_shared = nm
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_inline_per_{kw}')],
            [InlineKeyboardButton(f"排序: {'是' if sort_on else '否'} (切换)", callback_data=f'toggle_inline_sort_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_inline_{kw}')],
            [InlineKeyboardButton(f"共享: {'🔀' if cur_shared else '📌'} (切换)", callback_data=f'toggle_shared_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('delete_inline_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('delete_inline_','',1)
        gid_str = str(gid)
        # Try current group, then _global
        ik = config.get('inline_sticker_keywords',{}).get(gid_str,{})
        if kw not in ik and gid_str != '_global':
            ik = config.get('inline_sticker_keywords',{}).get('_global',{})
            if kw in ik:
                gid_str = '_global'
            else:
                await query.answer(text="关键词不存在", show_alert=True)
                return
        old = ik.pop(kw, {}).get('set','') if isinstance(ik.get(kw,{}), dict) else ik.pop(kw, '')
        config.setdefault('inline_sticker_keywords',{})[gid_str] = ik; save_config(config)
        # Clean up cache if no other group uses this set
        all_ik_sets = set()
        for gid2, kws in config.get('inline_sticker_keywords',{}).items():
            for v in kws.values(): all_ik_sets.add(v.get('set','') if isinstance(v,dict) else v)
        if old and old not in all_ik_sets:
            inline_cache.pop(old,None); inline_queue.pop(old,None); inline_hand.pop(old,None); inline_discard.pop(old,None)
        waiting_for_input.pop(user_id, None)
        await query.answer(text=f"已删除 '{kw}'", show_alert=True)
        sk = _get_ik(gid_str); gname = _get_group_name(gid_str)
        if not sk:
            await query.edit_message_text(
                f"[{gname}] 没有内联关键词了.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("添加内联关键词", callback_data='add_inline'),
                     InlineKeyboardButton("返回", callback_data='manage_keywords')]
                ]))
        else:
            kb = _build_list_keyboard(inline=True, group_id=gid_str)
            kb.append([InlineKeyboardButton("添加内联关键词", callback_data='add_inline'),
                        InlineKeyboardButton("返回", callback_data='manage_keywords')])
            await query.edit_message_text(f"[{gname}] 内联模式关键词:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == 'list_sticker':
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        gname = _get_group_name(gid)
        kb = _build_list_keyboard(group_id=gid)
        kb.append([InlineKeyboardButton("添加贴纸关键词", callback_data='add_sticker'),
                    InlineKeyboardButton("返回", callback_data='manage_keywords')])
        await query.edit_message_text(f"[{gname}] 贴纸关键词:\n点击替换.",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif query.data.startswith('replace_') and not query.data.startswith(('replace_inline_','replace_emoji_','replace_image_',)):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('replace_','',1); waiting_for_input[user_id] = f"replace:{kw}"
        mode = _get_mode(kw, gid); exact = _get_exact('sticker_keywords', kw, gid)
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] *{kw}* -> {_get_set(kw, gid)}\n发送关键词改名，或发送链接替换.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_per_{kw}')],
                [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_sticker_{kw}')],
                [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
            ]))

    elif query.data.startswith('toggle_per_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_per_','',1)
        cur = _get_mode(kw, gid); nm = _next_mode(cur)
        _set_mode(kw, nm, gid)
        await query.answer(text=f"'{kw}' {_get_mode_label(nm)}")
        exact = _get_exact('sticker_keywords', kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(nm)} (切换)", callback_data=f'toggle_per_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_sticker_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('toggle_exact_sticker_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_exact_sticker_', '', 1)
        cur = _get_exact('sticker_keywords', kw, gid); nm = not cur
        _set_exact('sticker_keywords', kw, nm, gid)
        await query.answer(text=f"'{kw}' 精准: {'✔' if nm else '✘'}")
        mode = _get_mode(kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_per_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if nm else '✘'} (切换)", callback_data=f'toggle_exact_sticker_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('attach_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('attach_', '', 1)
        waiting_for_input[user_id] = f"attach:{kw}"
        await query.answer(text="请发送一条贴纸或emoji")
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] *{kw}* — 发送一条贴纸来绑定触发器\n/cancel 取消",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("取消", callback_data='cancel_replace')]]))

    elif query.data.startswith('delete_') and not query.data.startswith(('delete_inline_','delete_emoji_','delete_image_','delete_text_')):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('delete_','',1)
        gid_str = str(gid)
        # Try current group, then _global fallback
        sk = config.get('sticker_keywords',{}).get(gid_str,{})
        old = _get_set(kw, gid) if kw in sk else None
        if kw not in sk and gid_str != '_global':
            sk = config.get('sticker_keywords',{}).get('_global',{})
            if kw in sk:
                gid_str = '_global'
                old = _get_set(kw, '_global')
            else:
                await query.answer(text="关键词不存在", show_alert=True)
                return
        sk.pop(kw, None)
        config.setdefault('sticker_keywords',{})[gid_str] = sk; save_config(config)
        # Clean cache
        all_sk_sets = set()
        for gid2, kws in config.get('sticker_keywords',{}).items():
            for v in kws.values(): all_sk_sets.add(v.get('set','') if isinstance(v,dict) else v)
        if old and old not in all_sk_sets:
            sticker_cache.pop(old,None); sticker_queue.pop(old,None)
        await query.answer(text=f"已删除 '{kw}'", show_alert=True)
        sk = _get_sk(gid_str); gname = _get_group_name(gid_str)
        if not sk:
            await query.edit_message_text(f"[{gname}] 没有关键词了.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("返回", callback_data='manage_keywords')]
                ]))
        else:
            kb = _build_list_keyboard(group_id=gid_str)
            kb.append([InlineKeyboardButton("添加贴纸关键词", callback_data='add_sticker'),
                        InlineKeyboardButton("返回", callback_data='manage_keywords')])
            await query.edit_message_text(f"[{gname}] 贴纸关键词:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == 'cancel_replace':
        mode = waiting_for_input.pop(user_id, None); pending_copy.pop(user_id, None)
        await query.answer(text="已取消")
        is_inline = mode and ('inline' in str(mode))
        is_emoji = mode and ('emoji' in str(mode))
        is_image = mode and ('image' in str(mode))
        is_text = mode and ('text' in str(mode))
        gname = _get_group_name(gid)
        if is_image:
            ik = _get_img_kw(gid)
            if not ik:
                await query.edit_message_text(f"[{gname}] 没有图片关键词了.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("添加图片关键词", callback_data='add_image'), InlineKeyboardButton("返回", callback_data='manage_keywords')]]))
            else:
                kb = _build_list_keyboard(image=True, group_id=gid)
                kb.append([InlineKeyboardButton("添加图片关键词", callback_data='add_image'),
                            InlineKeyboardButton("返回", callback_data='manage_keywords')])
                await query.edit_message_text(f"[{gname}] 图片关键词:", reply_markup=InlineKeyboardMarkup(kb))
        elif is_emoji:
            ek = _get_ek(gid)
            if not ek:
                await query.edit_message_text(f"[{gname}] 没有 Emoji 关键词了.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("添加 Emoji 关键词", callback_data='add_emoji'), InlineKeyboardButton("返回", callback_data='manage_keywords')]]))
            else:
                kb = _build_list_keyboard(emoji=True, group_id=gid)
                kb.append([InlineKeyboardButton("添加 Emoji 关键词", callback_data='add_emoji'),
                            InlineKeyboardButton("返回", callback_data='manage_keywords')])
                await query.edit_message_text(f"[{gname}] Emoji 关键词:", reply_markup=InlineKeyboardMarkup(kb))
        elif is_inline:
            sk = _get_ik(gid)
            if not sk:
                await query.edit_message_text(f"[{gname}] 没有内联关键词了.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("添加内联关键词", callback_data='add_inline'), InlineKeyboardButton("返回", callback_data='manage_keywords')]]))
            else:
                kb = _build_list_keyboard(inline=True, group_id=gid)
                kb.append([InlineKeyboardButton("添加内联关键词", callback_data='add_inline'),
                            InlineKeyboardButton("返回", callback_data='manage_keywords')])
                await query.edit_message_text(f"[{gname}] 内联模式关键词:", reply_markup=InlineKeyboardMarkup(kb))
        elif is_text:
            gid_str = str(gid)
            tk = _get_tk(gid)
            if not tk:
                await query.edit_message_text(
                    f"[{gname}] 暂无文本卡牌池。",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("➕ 添加", callback_data='add_text'),
                         InlineKeyboardButton("🔙 返回", callback_data='manage_keywords')],
                    ]))
            else:
                keyboard = []
                for kw2, info2 in tk.items():
                    per2 = info2.get('per_player', '?')
                    total2 = len(info2.get('pool', []))
                    keyboard.append([
                        InlineKeyboardButton(
                            f"{kw2} · 每人{per2}张 · {total2}张",
                            callback_data=f'edit_text_{kw2}'
                        ),
                        InlineKeyboardButton("❌", callback_data=f'delete_text_{kw2}')
                    ])
                keyboard.append([
                    InlineKeyboardButton("➕ 添加", callback_data='add_text'),
                    InlineKeyboardButton("🔙 返回", callback_data='manage_keywords'),
                ])
                await query.edit_message_text(
                    f"[{_get_group_name(gid)}] 文本卡牌池：",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            kb = _build_list_keyboard(group_id=gid)
            kb.append([InlineKeyboardButton("添加贴纸关键词", callback_data='add_sticker'),
                        InlineKeyboardButton("返回", callback_data='manage_keywords')])
            await query.edit_message_text(f"[{gname}] 贴纸关键词:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data.startswith('copykw_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('copykw_', '', 1)
        common = user_common_groups.get(user_id, {})
        # Exclude current group
        targets = {tgid: tname for tgid, tname in common.items() if tgid != gid and tgid != '_global'}
        if not targets:
            return await query.answer(text="没有其他可用的群组", show_alert=True)
        pending_copy[user_id] = {'kw': kw, 'is_inline': False, 'source_gid': gid}
        await query.edit_message_text(
            f"将关键词 '{kw}' 添加到哪个群组?",
            reply_markup=_build_copy_target_keyboard(user_id, targets)
        )

    elif query.data.startswith('copyinline_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('copyinline_', '', 1)
        common = user_common_groups.get(user_id, {})
        targets = {tgid: tname for tgid, tname in common.items() if tgid != gid and tgid != '_global'}
        if not targets:
            return await query.answer(text="没有其他可用的群组", show_alert=True)
        pending_copy[user_id] = {'kw': kw, 'is_inline': True, 'source_gid': gid}
        await query.edit_message_text(
            f"将内联关键词 '{kw}' 添加到哪个群组?",
            reply_markup=_build_copy_target_keyboard(user_id, targets, is_inline=True)
        )

    elif query.data.startswith('docopy_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        target_gid = query.data.replace('docopy_', '', 1)
        pc = pending_copy.pop(user_id, None)
        if not pc: return await query.answer(text="操作已过期", show_alert=True)
        kw = pc['kw']; source_gid = pc['source_gid']
        src_sk = _get_sk(source_gid); src_data = src_sk.get(kw, {})
        if not src_data: return await query.answer(text="关键词已不存在", show_alert=True)
        sn = src_data['set'] if isinstance(src_data, dict) else src_data
        mode_val = _get_mode(kw, source_gid)
        # Copy to target group
        config.setdefault('sticker_keywords', {}).setdefault(target_gid, {})[kw] = {"set": sn, "mode": mode_val}
        save_config(config)
        # Preload if not in cache
        if sn not in sticker_cache:
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                sticker_cache[sn] = [s.file_id for s in ss.stickers]
                _init_queue(sn, sticker_cache, sticker_queue)
            except Exception: pass
        tname = _get_group_name(target_gid)
        await query.answer(text=f"已添加到 [{tname}]", show_alert=True)
        # Return to the list view
        sk = _get_sk(gid); gname = _get_group_name(gid)
        kb = _build_list_keyboard(group_id=gid)
        kb.append([InlineKeyboardButton("添加贴纸关键词", callback_data='add_sticker'),
                    InlineKeyboardButton("返回", callback_data='manage_keywords')])
        await query.edit_message_text(f"[{gname}] 贴纸关键词:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data.startswith('docopyi_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        target_gid = query.data.replace('docopyi_', '', 1)
        pc = pending_copy.pop(user_id, None)
        if not pc: return await query.answer(text="操作已过期", show_alert=True)
        kw = pc['kw']; source_gid = pc['source_gid']
        src_ik = _get_ik(source_gid); src_data = src_ik.get(kw, {})
        if not src_data: return await query.answer(text="关键词已不存在", show_alert=True)
        sn = src_data['set'] if isinstance(src_data, dict) else src_data
        mode_val = _inline_get_mode(kw, source_gid)
        config.setdefault('inline_sticker_keywords', {}).setdefault(target_gid, {})[kw] = {"set": sn, "mode": mode_val}
        save_config(config)
        if sn not in inline_cache:
            try:
                ss = await context.bot.get_sticker_set(name=sn)
                inline_cache[sn] = [s.file_id for s in ss.stickers]
                _init_queue(sn, inline_cache, inline_queue)
            except Exception: pass
        inline_hand[sn] = {}
        _save_hand()
        tname = _get_group_name(target_gid)
        await query.answer(text=f"已添加到 [{tname}]", show_alert=True)
        sk = _get_ik(gid); gname = _get_group_name(gid)
        if not sk:
            await query.edit_message_text(f"[{gname}] 没有内联关键词了.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("添加内联关键词", callback_data='add_inline'), InlineKeyboardButton("返回", callback_data='manage_keywords')]]))
        else:
            kb = _build_list_keyboard(inline=True, group_id=gid)
            kb.append([InlineKeyboardButton("添加内联关键词", callback_data='add_inline'),
                        InlineKeyboardButton("返回", callback_data='manage_keywords')])
            await query.edit_message_text(f"[{gname}] 内联模式关键词:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == 'list_emoji':
        # Group chat: manage current group; private chat: use selected group
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        ek = _get_ek(gid); gname = _get_group_name(gid)
        if not ek:
            return await query.edit_message_text(
                f"[{gname}] 还没有 Emoji 关键词.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("添加 Emoji 关键词", callback_data='add_emoji'),
                     InlineKeyboardButton("返回", callback_data='manage_keywords')]
                ]))
        kb = _build_list_keyboard(emoji=True, group_id=gid)
        kb.append([InlineKeyboardButton("添加 Emoji 关键词", callback_data='add_emoji'),
                    InlineKeyboardButton("返回", callback_data='manage_keywords')])
        await query.edit_message_text(f"[{gname}] Emoji 关键词:\n点击替换.",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == 'add_emoji':
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        waiting_for_input[user_id] = f"add_emoji:"
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] 发送 <关键词> <emoji包链接>\n例如: 抽牌 https://t.me/addemoji/MyPack\n/cancel 取消.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("取消返回", callback_data='cancel_replace')]]))

    elif query.data.startswith('replace_emoji_'):
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('replace_emoji_', '', 1)
        waiting_for_input[user_id] = f"replace_emoji:{kw}"
        sn = _emoji_get_set(kw, gid); mode = _emoji_get_mode(kw, gid)
        exact = _get_exact('emoji_keywords', kw, gid)
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] *{kw}* -> {sn}\n发送新emoji包链接替换.\n/cancel 取消.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_emoji_per_{kw}')],
                [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_emoji_{kw}')],
                [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
            ]))

    elif query.data.startswith('toggle_emoji_per_'):
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_emoji_per_', '', 1)
        cur = _emoji_get_mode(kw, gid); nm = _next_mode(cur)
        _emoji_set_mode(kw, nm, gid)
        await query.answer(text=f"'{kw}' {_get_mode_label(nm)}")
        sn = _emoji_get_set(kw, gid); exact = _get_exact('emoji_keywords', kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(nm)} (切换)", callback_data=f'toggle_emoji_per_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_emoji_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('toggle_exact_emoji_'):
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_exact_emoji_', '', 1)
        cur = _get_exact('emoji_keywords', kw, gid); nm = not cur
        _set_exact('emoji_keywords', kw, nm, gid)
        await query.answer(text=f"'{kw}' 精准: {'✔' if nm else '✘'}")
        mode = _emoji_get_mode(kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_emoji_per_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if nm else '✘'} (切换)", callback_data=f'toggle_exact_emoji_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('delete_emoji_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('delete_emoji_', '', 1)
        gid_str = str(gid)
        # Try current group, then _global
        ek = config.get('emoji_keywords', {}).get(gid_str, {})
        if kw not in ek and gid_str != '_global':
            ek = config.get('emoji_keywords', {}).get('_global', {})
            if kw in ek:
                gid_str = '_global'
            else:
                await query.answer(text="关键词不存在", show_alert=True)
                return
        old = ek.pop(kw, {}).get('set','') if isinstance(ek.get(kw,{}), dict) else ek.pop(kw, '')
        config.setdefault('emoji_keywords', {})[gid_str] = ek
        save_config(config)
        # Clean up cache if no other group uses this pack
        all_emo_sets = set()
        for gid2, kws in config.get('emoji_keywords', {}).items():
            for v in kws.values(): all_emo_sets.add(v.get('set', '') if isinstance(v, dict) else v)
        if old and old not in all_emo_sets:
            emoji_cache.pop(old, None); emoji_queue.pop(old, None); emoji_discard.pop(old, None)
        await query.answer(text=f"已删除 '{kw}'", show_alert=True)
        ek = _get_ek(gid_str); gname = _get_group_name(gid_str)
        if not ek:
            await query.edit_message_text(f"[{gname}] 没有 Emoji 关键词了.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("添加 Emoji 关键词", callback_data='add_emoji'),
                     InlineKeyboardButton("返回", callback_data='manage_keywords')]
                ]))
        else:
            kb = _build_list_keyboard(emoji=True, group_id=gid_str)
            kb.append([InlineKeyboardButton("添加 Emoji 关键词", callback_data='add_emoji'),
                        InlineKeyboardButton("返回", callback_data='manage_keywords')])
            await query.edit_message_text(f"[{gname}] Emoji 关键词:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == 'list_image':
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        ik = _get_img_kw(gid); gname = _get_group_name(gid)
        if not ik:
            return await query.edit_message_text(
                f"[{gname}] 还没有图片关键词.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("添加图片关键词", callback_data='add_image'),
                     InlineKeyboardButton("返回", callback_data='manage_keywords')]
                ]))
        kb = _build_list_keyboard(image=True, group_id=gid)
        kb.append([InlineKeyboardButton("添加图片关键词", callback_data='add_image'),
                    InlineKeyboardButton("返回", callback_data='manage_keywords')])
        await query.edit_message_text(f"[{gname}] 图片关键词:\n点击替换.",
                                       reply_markup=InlineKeyboardMarkup(kb))

    elif query.data == 'add_image':
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        if query.message.chat.type in ('group', 'supergroup'):
            # In group: link to private chat
            bot_name = context.bot.username
            await query.edit_message_text(
                f"请私聊 @{bot_name} 然后发送 /addimg 来添加图片关键词。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("前往私聊", url=f"https://t.me/{bot_name}")],
                    [InlineKeyboardButton("返回", callback_data='manage_keywords')],
                ]))
        else:
            waiting_for_input[user_id] = "collect_image_kw"
            await query.edit_message_text(
                "发送图片关键词名称:\n/cancel 取消.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("取消", callback_data='cancel_replace')]]))

    elif query.data.startswith('replace_image_'):
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('replace_image_', '', 1)
        cnt = len(_img_get_files(kw, gid)); mode = _img_get_mode(kw, gid)
        stitch = _img_get_stitch(kw, gid); exact = _get_exact('image_keywords', kw, gid)
        bot_name = context.bot.username
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] {kw} ({cnt}张)\n私聊 @{bot_name} 发送 /addimg 重新收集.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_image_per_{kw}')],
                [InlineKeyboardButton(f"拼接: {'是' if stitch else '否'} (切换)", callback_data=f'toggle_image_stitch_{kw}')],
                [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_image_{kw}')],
                [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
            ]))

    elif query.data.startswith('toggle_image_per_'):
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_image_per_', '', 1)
        cur = _img_get_mode(kw, gid); nm = _next_mode(cur)
        _img_set_mode(kw, nm, gid)
        stitch = _img_get_stitch(kw, gid); exact = _get_exact('image_keywords', kw, gid)
        await query.answer(text=f"'{kw}' {_get_mode_label(nm)}")
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(nm)} (切换)", callback_data=f'toggle_image_per_{kw}')],
            [InlineKeyboardButton(f"拼接: {'是' if stitch else '否'} (切换)", callback_data=f'toggle_image_stitch_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if exact else '✘'} (切换)", callback_data=f'toggle_exact_image_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('toggle_image_stitch_'):
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_image_stitch_', '', 1)
        cur = _img_get_stitch(kw, gid); nm = not cur
        _img_set_stitch(kw, nm, gid)
        await query.answer(text=f"拼接: {'是' if nm else '否'}")
        # 刷新整个图片列表
        gname = _get_group_name(gid)
        kb = _build_list_keyboard(image=True, group_id=gid)
        kb.append([InlineKeyboardButton("添加图片关键词", callback_data='add_image'),
                    InlineKeyboardButton("返回", callback_data='manage_keywords')])
        await query.edit_message_text(f"[{gname}] 图片关键词:", reply_markup=InlineKeyboardMarkup(kb))

    elif query.data.startswith('toggle_exact_image_'):
        gid = str(query.message.chat.id) if query.message.chat.type in ('group', 'supergroup') else user_selected_group.get(user_id, '_global')
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('toggle_exact_image_', '', 1)
        cur = _get_exact('image_keywords', kw, gid); nm = not cur
        _set_exact('image_keywords', kw, nm, gid)
        await query.answer(text=f"'{kw}' 精准: {'✔' if nm else '✘'}")
        mode = _img_get_mode(kw, gid); stitch = _img_get_stitch(kw, gid)
        await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"模式: {_get_mode_label(mode)} (切换)", callback_data=f'toggle_image_per_{kw}')],
            [InlineKeyboardButton(f"拼接: {'是' if stitch else '否'} (切换)", callback_data=f'toggle_image_stitch_{kw}')],
            [InlineKeyboardButton(f"精准: {'✔' if nm else '✘'} (切换)", callback_data=f'toggle_exact_image_{kw}')],
            [InlineKeyboardButton("附加 (贴纸触发)", callback_data=f'attach_{kw}')],
            [InlineKeyboardButton("取消返回", callback_data='cancel_replace')]
        ]))

    elif query.data.startswith('delete_image_'):
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        kw = query.data.replace('delete_image_', '', 1)
        gid_str = str(gid)
        # Try current group, then _global
        ik_cfg = config.get('image_keywords', {}).get(gid_str, {})
        if kw not in ik_cfg and gid_str != '_global':
            ik_cfg = config.get('image_keywords', {}).get('_global', {})
            if kw in ik_cfg:
                gid_str = '_global'
            else:
                await query.answer(text="关键词不存在", show_alert=True)
                return
        key = _img_kw_key(gid_str, kw)
        config.setdefault('image_keywords', {}).setdefault(gid_str, {}).pop(kw, None)
        save_config(config)
        img_cache.pop(key, None); img_queue.pop(key, None); img_discard.pop(key, None)
        await query.answer(text=f"已删除 '{kw}'", show_alert=True)
        ik = _get_img_kw(gid_str); gname = _get_group_name(gid_str)
        if not ik:
            await query.edit_message_text(f"[{gname}] 没有图片关键词了.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("添加图片关键词", callback_data='add_image'),
                     InlineKeyboardButton("返回", callback_data='manage_keywords')]
                ]))
        else:
            kb = _build_list_keyboard(image=True, group_id=gid_str)
            kb.append([InlineKeyboardButton("添加图片关键词", callback_data='add_image'),
                        InlineKeyboardButton("返回", callback_data='manage_keywords')])
            await query.edit_message_text(f"[{gname}] 图片关键词:", reply_markup=InlineKeyboardMarkup(kb))

    # ========== 拼接图片关键词管理 ==========
    elif query.data == 'list_composite':
        gid_str = str(gid)
        ck = _get_comp_kw(gid)
        gname = _get_group_name(gid)
        if not ck:
            await query.edit_message_text(
                f"[{gname}] 暂无拼接图片关键词。\n使用 /addimg 然后 /gap 分隔组来添加。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ 添加", callback_data='add_image'),
                     InlineKeyboardButton("🔙 返回", callback_data='manage_keywords')],
                ]))
            return
        keyboard = []
        for kw, info in ck.items():
            groups = info.get('groups', [])
            total = sum(len(g) for g in groups) if groups else 0
            keyboard.append([
                InlineKeyboardButton(
                    f"{kw} · {len(groups)}组{total}张",
                    callback_data=f'edit_composite_{kw}'
                ),
                InlineKeyboardButton("❌", callback_data=f'delete_composite_{kw}')
            ])
        keyboard.append([
            InlineKeyboardButton("➕ 添加", callback_data='add_image'),
            InlineKeyboardButton("🔙 返回", callback_data='manage_keywords'),
        ])
        await query.edit_message_text(
            f"[{gname}] 拼接图片关键词：",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith('edit_composite_'):
        kw = query.data.replace('edit_composite_', '', 1)
        ck = _get_comp_kw(gid)
        info = ck.get(kw, {})
        if not info:
            await query.answer(text="关键词不存在", show_alert=True)
            return
        groups = info.get('groups', [])
        total = sum(len(g) for g in groups)
        lines = [f"[{_get_group_name(gid)}] 🧩 {kw}"]
        for i, g in enumerate(groups, 1):
            lines.append(f"  第{i}组: {len(g)}张")
        lines.append(f"  共{len(groups)}组, {total}张, 每次抽{len(groups)}张拼接")
        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回列表", callback_data='list_composite')],
            ])
        )

    elif query.data.startswith('delete_composite_'):
        kw = query.data.replace('delete_composite_', '', 1)
        gid_str = str(gid)
        # Try current group, then _global
        ck_cfg = config.get('composite_keywords', {}).get(gid_str, {})
        if kw not in ck_cfg and gid_str != '_global':
            ck_cfg = config.get('composite_keywords', {}).get('_global', {})
            if kw in ck_cfg:
                gid_str = '_global'
            else:
                await query.answer(text="关键词不存在", show_alert=True)
                return
        config.setdefault('composite_keywords', {}).setdefault(gid_str, {}).pop(kw, None)
        if not config['composite_keywords'].get(gid_str):
            config['composite_keywords'].pop(gid_str, None)
        save_config(config)
        await query.answer(text=f"✅ 已删除「{kw}」", show_alert=True)
        # Refresh list
        ck = _get_comp_kw(gid_str)
        gname = _get_group_name(gid_str)
        if not ck:
            await query.edit_message_text(
                f"[{gname}] 暂无拼接图片关键词。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ 添加", callback_data='add_image'),
                     InlineKeyboardButton("🔙 返回", callback_data='manage_keywords')],
                ]))
        else:
            keyboard = []
            for kw2, info2 in ck.items():
                groups2 = info2.get('groups', [])
                total2 = sum(len(g) for g in groups2) if groups2 else 0
                keyboard.append([
                    InlineKeyboardButton(
                        f"{kw2} · {len(groups2)}组{total2}张",
                        callback_data=f'edit_composite_{kw2}'
                    ),
                    InlineKeyboardButton("❌", callback_data=f'delete_composite_{kw2}')
                ])
            keyboard.append([
                InlineKeyboardButton("➕ 添加", callback_data='add_image'),
                InlineKeyboardButton("🔙 返回", callback_data='manage_keywords'),
            ])
            await query.edit_message_text(
                f"[{_get_group_name(gid)}] 拼接图片关键词：",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    elif query.data == 'add_sticker':
        if not adm: return await query.answer(text="仅管理员", show_alert=True)
        waiting_for_input[user_id] = "add"
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] 发送 <关键词> <链接>\n/cancel 取消.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("取消返回", callback_data='cancel_replace')]]))

    elif query.data == 'back_to_start':
        pending_copy.pop(user_id, None)
        text, markup = _show_main_menu_text(user, gid)
        await query.edit_message_text(text, reply_markup=markup)

    # ========== 文本卡牌池管理 ==========
    elif query.data == 'list_text':
        gid_str = str(gid)
        tk = _get_tk(gid)
        gname = _get_group_name(gid)
        if not tk:
            await query.edit_message_text(
                f"[{gname}] 暂无文本卡牌池。\n使用 /addtext 添加。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ 添加", callback_data='add_text'),
                     InlineKeyboardButton("🔙 返回", callback_data='manage_keywords')],
                ]))
            return
        keyboard = []
        for kw, info in tk.items():
            per = info.get('per_player', '?')
            total = len(info.get('pool', []))
            keyboard.append([
                InlineKeyboardButton(
                    f"{kw} · 每人{per}张 · {total}张",
                    callback_data=f'edit_text_{kw}'
                ),
                InlineKeyboardButton("❌", callback_data=f'delete_text_{kw}')
            ])
        keyboard.append([
            InlineKeyboardButton("➕ 添加", callback_data='add_text'),
            InlineKeyboardButton("🔙 返回", callback_data='manage_keywords'),
        ])
        await query.edit_message_text(
            f"[{gname}] 文本卡牌池：",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data == 'add_text':
        gid_str = str(gid)
        waiting_for_input[user_id] = "add_text"
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] 发送 /addtext 关键词 每人张数 卡牌1 卡牌2 ...\n"
            f"例如: /addtext 职业 4 剑圣 魔法师 刺客 弓箭手\n"
            f"/cancel 取消。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("取消返回", callback_data='cancel_replace')]])
        )

    elif query.data.startswith('edit_text_'):
        kw = query.data.replace('edit_text_', '', 1)
        tk = _get_tk(gid)
        info = tk.get(kw, {})
        if not info:
            await query.answer(text="关键词不存在", show_alert=True)
            return
        per = info.get('per_player', '?')
        cards = info.get('pool', [])
        pool_text = ' '.join(f'[{c}]' for c in cards)
        await query.edit_message_text(
            f"[{_get_group_name(gid)}] 🎴 {kw}\n"
            f"每人: {per}张\n"
            f"牌库: {pool_text} ({len(cards)}张)\n\n"
            f"发送 /addtext {kw} {per} 卡牌1 ... 替换\n"
            f"或 /deltext {kw} 删除",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 返回列表", callback_data='list_text')],
            ])
        )

    elif query.data.startswith('delete_text_'):
        kw = query.data.replace('delete_text_', '', 1)
        gid_str = str(gid)
        tk_config = config.get('text_keywords', {}).get(gid_str, {})
        if kw not in tk_config and gid_str != '_global':
            tk_config = config.get('text_keywords', {}).get('_global', {})
            if kw in tk_config:
                gid_str = '_global'
            else:
                await query.answer(text="关键词不存在", show_alert=True)
                return
        elif kw not in tk_config:
            await query.answer(text="关键词不存在", show_alert=True)
            return
        config['text_keywords'][gid_str].pop(kw, None)
        if not config['text_keywords'][gid_str]:
            config['text_keywords'].pop(gid_str, None)
        save_config(config)
        await query.answer(text=f"✅ 已删除「{kw}」", show_alert=True)
        # Refresh list
        tk = _get_tk(gid_str)
        gname = _get_group_name(gid_str)
        if not tk:
            await query.edit_message_text(
                f"[{gname}] 暂无文本卡牌池。",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ 添加", callback_data='add_text'),
                     InlineKeyboardButton("🔙 返回", callback_data='manage_keywords')],
                ]))
        else:
            keyboard = []
            for kw2, info2 in tk.items():
                per2 = info2.get('per_player', '?')
                total2 = len(info2.get('pool', []))
                keyboard.append([
                    InlineKeyboardButton(
                        f"{kw2} · 每人{per2}张 · {total2}张",
                        callback_data=f'edit_text_{kw2}'
                    ),
                    InlineKeyboardButton("❌", callback_data=f'delete_text_{kw2}')
                ])
            keyboard.append([
                InlineKeyboardButton("➕ 添加", callback_data='add_text'),
                InlineKeyboardButton("🔙 返回", callback_data='manage_keywords'),
            ])
            await query.edit_message_text(
                f"[{_get_group_name(gid)}] 文本卡牌池：",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    # ========== 文本卡牌池 — 游戏交互 ==========
    elif query.data.startswith('text_join:'):
        game_key = query.data.replace('text_join:', '', 1)
        game = text_game_state.get(game_key)
        if not game:
            await query.answer(text="牌局已结束", show_alert=True)
            return
        await handle_text_join(query, game_key, game, str(gid), context)

    elif query.data.startswith('text_start:'):
        game_key = query.data.replace('text_start:', '', 1)
        game = text_game_state.get(game_key)
        if not game:
            await query.answer(text="牌局已结束", show_alert=True)
            return
        await handle_text_start(query, game_key, game, str(gid), context)

    # ========== 阵列模式 ==========
    elif query.data == 'array_mode':
        """主菜单进入阵列模式"""
        await query.edit_message_text(
            "🎮 阵列模式\n\n"
            "9×9 Emoji 五子棋盘。\n"
            "发送 /join 加入房间（❌ / ⭕），\n"
            "然后发送坐标（如 a1、e5、i9）即可落子。\n"
            "五子连珠即获胜。\n\n"
            "坐标：字母行(a-i)+数列(1-9)，如 a2=第一行第二列",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("返回主菜单", callback_data='back_to_start')],
            ])
        )

    elif query.data == 'array_join':
        # kept for backward compat but /join is the main way
        await _do_array_join(update, update.effective_user.id, update.effective_chat.id)

    elif query.data == 'array_spectate':
        await _array_show_board(query, None)

    elif query.data == 'array_reset':
        array_board[:] = [['⬜'] * 9 for _ in range(9)]
        array_players.clear()
        await query.answer(text="棋盘已重置，玩家已清空", show_alert=True)
        await _array_show_board(query, update.effective_user.id)

    elif query.data == 'array_leave':
        uid = update.effective_user.id
        array_players.pop(uid, None)
        await query.answer(text="已离开房间", show_alert=True)
        await _array_show_board(query, update.effective_user.id)



