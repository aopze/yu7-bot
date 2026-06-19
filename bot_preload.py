#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_preload.py - 贴纸/Emoji/图片预加载
from bot_config import (logger, config, _all_sticker_sets, _init_queue, _load_json, _save_json, save_config, _save_hand,
                        sticker_cache, sticker_queue, sticker_discard, inline_cache, inline_queue, inline_hand, inline_discard, inline_kept,
                        _build_trigger_index, _load_img_kept, _filter_blocked_stickers,
                        _load_shared_state, inline_shared_queue, inline_shared_discard,
                        img_queue, img_discard,
                        emoji_cache, emoji_queue, emoji_discard,
                        QUEUE_FILE, INLINE_QUEUE_FILE, DISCARD_FILE, HAND_FILE, EMOJI_QUEUE_FILE, EMOJI_DISCARD_FILE, STICKER_DISCARD_FILE,
                        IMG_QUEUE_FILE, IMG_DISCARD_FILE,
                        _get_extra_pack_name, _load_kept)

async def preload_sticker_sets(context=None, app=None):
    bot = (app.bot if app else context.bot) if (app or context) else None
    if not bot: return

    all_sets = _all_sticker_sets()
    sq = _load_json(QUEUE_FILE)
    for sn in all_sets:
        try:
            ss = await bot.get_sticker_set(name=sn)
            stickers = [s.file_id for s in ss.stickers]
            sticker_cache[sn] = stickers
            # Filter ⛔ stickers from inline pool
            allowed = _filter_blocked_stickers(sn, ss.stickers)
            inline_cache[sn] = allowed
            if sn in sq:
                valid = [f for f in sq[sn] if f in set(stickers)]
                sticker_queue[sn] = valid if valid else None
            if sn not in sticker_queue or not sticker_queue[sn]:
                _init_queue(sn, sticker_cache, sticker_queue)
            logger.info(f"'{sn}': {len(stickers)}, queue={len(sticker_queue.get(sn,[]))}")
        except Exception as e:
            logger.error(f"Preload fail '{sn}': {e}")

    # Inline queues and hands
    iq = _load_json(INLINE_QUEUE_FILE)
    inline_hand.clear(); inline_hand.update(_load_json(HAND_FILE))
    # Fix: JSON converts int keys to strings; convert back
    for sn in list(inline_hand.keys()):
        inline_hand[sn] = {int(uid): cards for uid, cards in inline_hand[sn].items()}
    # Load kept state
    _load_kept()
    _load_img_kept()
    _load_shared_state()
    # Load sticker discard
    sd = _load_json(STICKER_DISCARD_FILE)
    sticker_discard.clear(); sticker_discard.update(sd)
    for sn in list(sticker_discard.keys()):
        sticker_discard[sn] = {int(uid): cards for uid, cards in sticker_discard[sn].items()}
    # Load image keyword state
    iq = _load_json(IMG_QUEUE_FILE)
    img_queue.clear(); img_queue.update(iq)
    idd = _load_json(IMG_DISCARD_FILE)
    img_discard.clear(); img_discard.update(idd)
    for key in list(img_discard.keys()):
        img_discard[key] = {int(uid): cards for uid, cards in img_discard[key].items()}
    # Build sticker trigger index
    _build_trigger_index()
    for gid, kws in config.get('inline_sticker_keywords', {}).items():
        for kw, v in kws.items():
            sn = v.get('set', '') if isinstance(v, dict) else v
            if not sn: continue
            if sn not in inline_cache:
                try:
                    ss = await bot.get_sticker_set(name=sn)
                    allowed = _filter_blocked_stickers(sn, ss.stickers)
                    inline_cache[sn] = allowed
                except Exception:
                    logger.warning(f"Preload: cannot fetch sticker set '{sn}', hands preserved")
                    continue
            # Merge keyword extra stickers into cache
            if sn in inline_cache:
                extras = config.get('keyword_extra_stickers', {}).get(gid, {}).get(kw, [])
                for fid in extras:
                    if fid not in inline_cache[sn]:
                        inline_cache[sn].append(fid)
            # Only validate hands if we have a cache (preserve if fetch failed)
            if sn in inline_cache and inline_cache[sn]:
                if sn in iq:
                    valid = [f for f in iq[sn] if f in set(inline_cache[sn])]
                    inline_queue[sn] = valid if valid else None
                if sn not in inline_queue or not inline_queue[sn]:
                    _init_queue(sn, inline_cache, inline_queue)
                if sn in inline_hand:
                    for uid in list(inline_hand[sn]):
                        inline_hand[sn][uid] = [f for f in inline_hand[sn][uid]
                                                 if f in set(inline_cache[sn])]
                        if not inline_hand[sn][uid]: del inline_hand[sn][uid]
                logger.info(f"Inline '{sn}': {len(inline_cache[sn])}, queue={len(inline_queue.get(sn,[]))}, hand_users={len(inline_hand.get(sn,{}))}")
            else:
                logger.warning(f"Inline '{sn}': cache empty, skipping hand validation (hands preserved)")

    # Load discard piles for limited mode
    dc = _load_json(DISCARD_FILE)
    inline_discard.clear(); inline_discard.update(dc)
    # Fix JSON string keys → int
    for sn in list(inline_discard.keys()):
        inline_discard[sn] = {int(uid): cards for uid, cards in inline_discard[sn].items()}
    # Validate discard stickers still exist (per-user)
    for sn in list(inline_discard.keys()):
        if sn in inline_cache and inline_cache[sn]:
            users = inline_discard[sn]
            for uid in list(users.keys()):
                users[uid] = [f for f in users[uid] if f in set(inline_cache[sn])]
                if not users[uid]:
                    del users[uid]
            if users:
                total = sum(len(v) for v in users.values())
                logger.info(f"Discard '{sn}': {total} cards across {len(users)} users")
            else:
                del inline_discard[sn]
        else:
            logger.warning(f"Discard '{sn}': cache empty, preserving discard data")

    # Load extra sticker pack (for d-command additions)
    extra_pack = _get_extra_pack_name()
    if extra_pack:
        try:
            ss = await bot.get_sticker_set(name=extra_pack)
            allowed = _filter_blocked_stickers(extra_pack, ss.stickers)
            inline_cache[extra_pack] = allowed
            logger.info(f"Extra pack '{extra_pack}': {len(inline_cache[extra_pack])} stickers")
        except Exception:
            logger.warning(f"Extra pack '{extra_pack}' not found, will recreate on demand")

    config.setdefault('_runtime', {})['inline_hand'] = inline_hand
    _save_hand()

    # === Emoji preloading ===
    eq = _load_json(EMOJI_QUEUE_FILE)
    for gid, kws in config.get('emoji_keywords', {}).items():
        for v in kws.values():
            sn = v.get('set', '') if isinstance(v, dict) else v
            if not sn or sn in emoji_cache: continue
            try:
                ss = await bot.get_sticker_set(name=sn)
                emoji_cache[sn] = {s.custom_emoji_id: s.emoji for s in ss.stickers if s.type == 'custom_emoji' and s.custom_emoji_id and s.emoji}
                logger.info(f"Emoji '{sn}': {len(emoji_cache[sn])} emojis")
            except Exception as e:
                logger.error(f"Emoji preload fail '{sn}': {e}")
    for sn in list(emoji_cache.keys()):
        if sn in eq:
            valid = [f for f in eq[sn] if f in set(emoji_cache.get(sn, []))]
            emoji_queue[sn] = valid if valid else None
        if sn not in emoji_queue or not emoji_queue[sn]:
            _init_queue(sn, emoji_cache, emoji_queue)

    # Load emoji discard piles for limited mode
    ed = _load_json(EMOJI_DISCARD_FILE)
    emoji_discard.clear(); emoji_discard.update(ed)
    # Fix JSON string keys → int, then validate
    for sn in list(emoji_discard.keys()):
        emoji_discard[sn] = {int(uid): cards for uid, cards in emoji_discard[sn].items()}
        if sn in emoji_cache and emoji_cache[sn]:
            users = emoji_discard[sn]
            for uid in list(users.keys()):
                users[uid] = [f for f in users[uid] if f in set(emoji_cache[sn])]
                if not users[uid]: del users[uid]
            if not users: del emoji_discard[sn]
        else:
            logger.warning(f"Emoji discard '{sn}': cache empty, preserving")

    try: save_config(config)
    except Exception: pass

