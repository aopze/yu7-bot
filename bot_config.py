#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# bot_config.py - 全局配置、状态、辅助函数、菜单建造器
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Group Sticker Management Bot (python-telegram-bot v22.7)
Features:
1. Sticker keyword auto-reply (per-keyword random/non-repeat, queue persisted)
2. Per-group keyword isolation: each group can have its own keyword list
3. Inline mode: keyword draw adds to hand, inline send removes from hand (card-game)
4. Per-keyword management via buttons with group selection
"""
import json, logging, os, random, re
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultCachedSticker, MessageEntity
from telegram import BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, InlineQueryHandler,
    ChosenInlineResultHandler, filters, ContextTypes, CallbackQueryHandler,
    ChatMemberHandler,
)

from logging.handlers import RotatingFileHandler

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# File-based log for crash forensics
LOG_FILE = Path(__file__).parent / "bot.log"
try:
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8')
    fh.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s'))
    logging.getLogger().addHandler(fh)
except Exception:
    pass

CONFIG_FILE = Path(__file__).parent / "config.json"
QUEUE_FILE = Path(__file__).parent / "queue_state.json"
INLINE_QUEUE_FILE = Path(__file__).parent / "inline_queue_state.json"
DISCARD_FILE = Path(__file__).parent / "discard_state.json"
HAND_FILE = Path(__file__).parent / "hand_state.json"
SHARED_QUEUE_FILE = Path(__file__).parent / "shared_queue_state.json"
SHARED_DISCARD_FILE = Path(__file__).parent / "shared_discard_state.json"
KEPT_FILE = Path(__file__).parent / "kept_state.json"
EMOJI_QUEUE_FILE = Path(__file__).parent / "emoji_queue_state.json"
EMOJI_DISCARD_FILE = Path(__file__).parent / "emoji_discard_state.json"
IMG_QUEUE_FILE = Path(__file__).parent / "img_queue_state.json"
IMG_DISCARD_FILE = Path(__file__).parent / "img_discard_state.json"
IMG_KEPT_FILE = Path(__file__).parent / "img_kept_state.json"
STICKER_DISCARD_FILE = Path(__file__).parent / "sticker_discard_state.json"

# Main (sticker)
sticker_cache: Dict[str, List[str]] = {}
sticker_queue: Dict[str, List[str]] = {}
sticker_discard: Dict[str, Dict[int, List[str]]] = {}  # {sn: {uid: [fids]}}
# Inline (card game)
inline_cache: Dict[str, List[str]] = {}
sticker_emoji_map: Dict[str, str] = {}  # {file_id: emoji_char} for ⛔ filtering
inline_queue: Dict[str, List[str]] = {}
inline_hand: Dict[str, Dict[int, List[str]]] = {}
inline_discard: Dict[str, Dict[int, List[str]]] = {}  # {"set_name": {user_id: [file_ids]}}
inline_shared_queue: Dict[str, Dict[int, List[str]]] = {}  # {sn: {uid: [fids]}} for shared mode
inline_shared_discard: Dict[str, Dict[int, List[str]]] = {}  # {sn: {uid: [fids]}} for shared mode
inline_kept: Dict[str, Dict[int, List[str]]] = {}     # {"set_name": {user_id: [file_ids]}} 保留区
# Keyword sticker trigger index: {file_id: (gid, keyword)} for O(1) lookup
keyword_trigger_index: Dict[str, tuple] = {}
# Emoji (custom emoji pack, same as sticker but replies with emoji)
emoji_cache: Dict[str, Dict[str, str]] = {}   # pack_name → {custom_emoji_id: emoji_char}
emoji_queue: Dict[str, List[str]] = {}       # pack_name → shuffled
emoji_discard: Dict[str, Dict[int, List[str]]] = {}  # pack_name → {user_id: [ids]}
# Image (Telegram photo file_ids, same as sticker but sends photos)
img_cache: Dict[str, List[str]] = {}           # kw_key → [file_id, ...]
img_queue: Dict[str, List[str]] = {}           # kw_key → shuffled
img_discard: Dict[str, Dict[int, List[str]]] = {}  # kw_key → {user_id: [file_ids]}
img_kept: Dict[str, Dict[int, List[str]]] = {}     # kw_key → {user_id: [file_ids]} 保留区
img_collect: Dict[int, List[str]] = {}         # {user_id: [file_id, ...]} — adding
img_collect_kw: Dict[int, str] = {}            # {user_id: keyword} — adding
img_collect_composite: Dict[int, List[List[str]]] = {}  # {user_id: [[g1], [g2], ...]} — composite adding
# 计数器模式
counter_enabled: Dict[str, bool] = {}          # {chat_tid_key: True}
counter_data: Dict[str, Dict[int, Dict[str, int]]] = {}   # {chat_tid_key: {user_id: {kw: val}}}
counter_msg: Dict[str, Dict[int, int]] = {}    # {chat_tid_key: {user_id: msg_id}}
# 阵列模式全局状态
array_board = [['⬜'] * 9 for _ in range(9)]   # 9x9 五子棋盘
array_players = {}                                 # {user_id: 'X'|'O'}
array_board_msg: Dict[int, tuple] = {}                     # {chat_id: (msg_id, thread_id)}

# 文本卡牌池全局状态
# text_game_state = { "group_id:kw1,kw2": { status, pools, players, join_msg_id, deal_msg_id } }
text_game_state: Dict[str, dict] = {}
TEXT_GAME_FILE = Path(__file__).parent / "text_game_state.json"

waiting_for_input: Dict[int, str] = {}
user_selected_group: Dict[int, str] = {}  # {user_id: group_id} - which group user manages in private chat
user_common_groups: Dict[int, Dict[str, str]] = {}  # {user_id: {group_id: group_name}} - cached common groups
pending_copy: Dict[int, dict] = {}  # {user_id: {kw, is_inline, source_gid}} - pending copy operation

# ========== Persist helpers ==========
def _save_json(file, data):
    """Atomic JSON save: write to .tmp, then rename (crash-safe)."""
    tmp = Path(str(file) + '.tmp')
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        tmp.replace(file)
    except Exception as e:
        logger.warning(f"Save json failed {file.name if hasattr(file, 'name') else file}: {e}")
        try: tmp.unlink(missing_ok=True)
        except Exception: pass

def _save_hand():
    """Save inline hand state to separate file (lightweight, frequent writes)."""
    _save_json(HAND_FILE, inline_hand)

def _save_inline_state():
    """Save all inline state (hand, queue, discard) atomically together."""
    _save_json(HAND_FILE, inline_hand)
    _save_json(INLINE_QUEUE_FILE, inline_queue)
    _save_json(DISCARD_FILE, inline_discard)
    _save_json(SHARED_QUEUE_FILE, inline_shared_queue)
    _save_json(SHARED_DISCARD_FILE, inline_shared_discard)

def _save_img_state():
    """Save image keyword state (queue, discard) atomically."""
    _save_json(IMG_QUEUE_FILE, img_queue)
    _save_json(IMG_DISCARD_FILE, img_discard)

def _save_kept():
    _save_json(KEPT_FILE, inline_kept)

def _load_kept():
    d = _load_json(KEPT_FILE)
    inline_kept.clear(); inline_kept.update(d)
    # Fix JSON string keys → int
    for sn in list(inline_kept.keys()):
        inline_kept[sn] = {int(uid): cards for uid, cards in inline_kept[sn].items()}

def _save_img_kept():
    _save_json(IMG_KEPT_FILE, img_kept)

def _load_img_kept():
    d = _load_json(IMG_KEPT_FILE)
    img_kept.clear(); img_kept.update(d)
    for key in list(img_kept.keys()):
        img_kept[key] = {int(uid): cards for uid, cards in img_kept[key].items()}

def _build_trigger_index():
    """Rebuild keyword_trigger_index from keyword_sticker_triggers config."""
    keyword_trigger_index.clear()
    for gid, kws in config.get('keyword_sticker_triggers', {}).items():
        for kw, fids in kws.items():
            for fid in fids:
                keyword_trigger_index[fid] = (gid, kw)

def _add_keyword_trigger(gid, kw, fid):
    """Add a sticker trigger and update index."""
    config.setdefault('keyword_sticker_triggers', {}).setdefault(gid, {}).setdefault(kw, [])
    if fid not in config['keyword_sticker_triggers'][gid][kw]:
        config['keyword_sticker_triggers'][gid][kw].append(fid)
        keyword_trigger_index[fid] = (gid, kw)

def _get_trigger_kw(fid):
    """O(1) lookup: get (gid, keyword) or None."""
    return keyword_trigger_index.get(fid)

def _remove_keyword_trigger(fid):
    """Remove a trigger from config and index."""
    entry = keyword_trigger_index.get(fid)
    if not entry: return
    gid, kw = entry
    kws = config.get('keyword_sticker_triggers', {}).get(gid, {})
    if kw in kws and fid in kws[kw]:
        kws[kw].remove(fid)
        if not kws[kw]:
            del kws[kw]
        if not kws:
            del config['keyword_sticker_triggers'][gid]
    keyword_trigger_index.pop(fid, None)

def _load_json(file):
    if file.exists():
        try:
            with open(file, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: pass
    return {}

# ========== Migration ==========
def _migrate_config():
    """Migrate old flat keyword structure to group-based structure."""
    sk = config.get('sticker_keywords', {})
    if not sk:
        return
    first_val = next(iter(sk.values()))
    # Old format: values are dicts with 'set' key (keyword entries)
    if isinstance(first_val, dict) and 'set' in first_val:
        logger.info("Migrating config to group-based structure...")
        config['sticker_keywords'] = {'_global': sk}
        ik = config.get('inline_sticker_keywords', {})
        if ik:
            first_ik = next(iter(ik.values()))
            if isinstance(first_ik, dict) and 'set' in first_ik:
                config['inline_sticker_keywords'] = {'_global': ik}
            else:
                config['inline_sticker_keywords'] = {'_global': ik}
        else:
            config['inline_sticker_keywords'] = {'_global': {}}
        if 'known_groups' not in config:
            config['known_groups'] = {}
        if 'emoji_keywords' not in config:
            config['emoji_keywords'] = {'_global': {}}
        save_config(config)
        logger.info("Migration complete!")

    # Migrate random:bool to mode:str for all keywords
    migrated = False
    for section in ['sticker_keywords', 'inline_sticker_keywords']:
        for gid, kws in config.get(section, {}).items():
            if not isinstance(kws, dict): continue
            for kw, v in list(kws.items()):
                if isinstance(v, dict) and 'mode' not in v:
                    v['mode'] = 'random' if v.pop('random', False) else 'sequential'
                    migrated = True
    if migrated:
        logger.info("Migrated random→mode for keywords")
        save_config(config)

# ========== Config helpers (group-aware) ==========
def _get_sk(group_id='_global'):
    return config.get('sticker_keywords', {}).get(str(group_id) if group_id else '_global', {})

def _get_ik(group_id='_global'):
    return config.get('inline_sticker_keywords', {}).get(str(group_id) if group_id else '_global', {})

def _get_set(kw, group_id='_global'):
    sk = _get_sk(group_id)
    return sk.get(kw, {}).get('set', '') if isinstance(sk.get(kw), dict) else sk.get(kw, '')

def _get_random(kw, group_id='_global'):
    sk = _get_sk(group_id)
    v = sk.get(kw, {})
    if isinstance(v, dict) and 'mode' in v:
        return v['mode'] == 'random'
    return v.get('random', False)

def _get_mode(kw, group_id='_global'):
    """Get keyword mode: 'random', 'sequential', or 'limited'."""
    sk = _get_sk(group_id)
    v = sk.get(kw, {})
    if isinstance(v, dict):
        mode = v.get('mode', '')
        if mode: return mode
        return 'random' if v.get('random', False) else 'sequential'
    return 'sequential'

def _set_mode(kw, mode, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('sticker_keywords',{}).setdefault(gid,{}).setdefault(kw,{})['mode'] = mode
    config['sticker_keywords'][gid][kw].pop('random', None)
    save_config(config)

# ========== 精准模式 (Exact match) helpers ==========
def _get_exact(section, kw, group_id='_global'):
    """Get exact-match flag for any keyword type. section: 'sticker_keywords', 'inline_sticker_keywords', etc."""
    sk = config.get(section, {}).get(str(group_id) if group_id else '_global', {})
    v = sk.get(kw, {})
    return v.get('exact', False) if isinstance(v, dict) else False

def _set_exact(section, kw, val, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault(section, {}).setdefault(gid, {}).setdefault(kw, {})['exact'] = val
    save_config(config)

def _get_mode_label(mode):
    return {'random': '重复', 'sequential': '不重复', 'limited': '有限'}.get(mode, mode)

def _next_mode(current):
    order = ['random', 'sequential', 'limited']
    idx = order.index(current) if current in order else 0
    return order[(idx + 1) % 3]

def _inline_get_set(kw, group_id='_global'):
    ik = _get_ik(group_id)
    return ik.get(kw, {}).get('set', '') if isinstance(ik.get(kw), dict) else ik.get(kw, '')

def _inline_get_mode(kw, group_id='_global'):
    """Get inline keyword mode: 'random', 'sequential', or 'limited'."""
    ik = _get_ik(group_id)
    v = ik.get(kw, {})
    if isinstance(v, dict):
        mode = v.get('mode', '')
        if mode: return mode
        return 'random' if v.get('random', False) else 'sequential'
    return 'sequential'

def _inline_set_mode(kw, mode, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{}).setdefault(kw,{})['mode'] = mode
    config['inline_sticker_keywords'][gid][kw].pop('random', None)
    save_config(config)

def _get_ek(group_id='_global'):
    """Get emoji_keywords for a group."""
    return config.get('emoji_keywords', {}).get(str(group_id) if group_id else '_global', {})

def _emoji_get_set(kw, group_id='_global'):
    ek = _get_ek(group_id)
    return ek.get(kw, {}).get('set', '') if isinstance(ek.get(kw), dict) else ek.get(kw, '')

def _emoji_get_mode(kw, group_id='_global'):
    ek = _get_ek(group_id)
    v = ek.get(kw, {})
    if isinstance(v, dict):
        mode = v.get('mode', '')
        if mode: return mode
        return 'random' if v.get('random', False) else 'sequential'
    return 'sequential'

def _emoji_set_mode(kw, mode, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('emoji_keywords',{}).setdefault(gid,{}).setdefault(kw,{})['mode'] = mode
    config['emoji_keywords'][gid][kw].pop('random', None)
    save_config(config)

def _inline_get_sort(kw, group_id='_global'):
    ik = _get_ik(group_id)
    v = ik.get(kw, {})
    return v.get('sort', True) if isinstance(v, dict) else True

def _get_img_kw(group_id='_global'):
    return config.get('image_keywords', {}).get(str(group_id) if group_id else '_global', {})

def _img_kw_key(gid, kw):
    return f"{gid}:{kw}"

def _img_get_files(kw, group_id='_global'):
    ik = _get_img_kw(group_id)
    v = ik.get(kw, {})
    return v.get('files', []) if isinstance(v, dict) else []

def _img_get_mode(kw, group_id='_global'):
    ik = _get_img_kw(group_id)
    v = ik.get(kw, {})
    return v.get('mode', 'random') if isinstance(v, dict) else 'random'

def _img_set_mode(kw, mode, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('image_keywords',{}).setdefault(gid,{}).setdefault(kw,{})['mode'] = mode
    save_config(config)

# ========== 拼接图片关键字 (Composite Image Keywords) ==========
def _get_comp_kw(group_id='_global'):
    """Get composite_image_keywords for a group."""
    return config.get('composite_keywords', {}).get(str(group_id) if group_id else '_global', {})

def _comp_get_groups(kw, group_id='_global'):
    """Get groups list for a composite keyword."""
    ck = _get_comp_kw(group_id)
    v = ck.get(kw, {})
    return v.get('groups', []) if isinstance(v, dict) else []

def _comp_get_mode(kw, group_id='_global'):
    """Get composite keyword mode."""
    ck = _get_comp_kw(group_id)
    v = ck.get(kw, {})
    return v.get('mode', 'random') if isinstance(v, dict) else 'random'

def _comp_set_mode(kw, mode, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('composite_keywords',{}).setdefault(gid,{}).setdefault(kw,{})['mode'] = mode
    save_config(config)

# ========== 内联关键词扩展贴纸 (d 指令添加) ==========
def _get_keyword_extras(kw, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    return config.get('keyword_extra_stickers', {}).get(gid, {}).get(kw, [])

def _add_keyword_extra(kw, fid, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('keyword_extra_stickers', {}).setdefault(gid, {}).setdefault(kw, [])
    if fid not in config['keyword_extra_stickers'][gid][kw]:
        config['keyword_extra_stickers'][gid][kw].append(fid)
    save_config(config)

def _get_extra_pack_name():
    """Get or return the name of the bot's extra sticker pack."""
    packs = config.get('extra_pack_names', [])
    if packs:
        return packs[0]
    return None

def _set_extra_pack_name(name):
    config['extra_pack_names'] = [name]
    save_config(config)

def _img_get_stitch(kw, group_id='_global'):
    ik = _get_img_kw(group_id)
    v = ik.get(kw, {})
    return v.get('stitch', False) if isinstance(v, dict) else False

def _img_set_stitch(kw, val, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('image_keywords',{}).setdefault(gid,{}).setdefault(kw,{})['stitch'] = val
    save_config(config)

def _inline_set_sort(kw, val, group_id='_global'):
    gid = str(group_id) if group_id else '_global'
    config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{})[kw]['sort'] = val
    save_config(config)

def _inline_is_shared(kw, group_id='_global'):
    """Check if inline keyword is in shared mode."""
    ik = _get_ik(group_id)
    v = ik.get(kw, {})
    return v.get('shared', False) if isinstance(v, dict) else False

def _inline_set_shared(kw, val, group_id='_global'):
    """Set shared mode for inline keyword. If turning on, initialize per-user queues."""
    gid = str(group_id) if group_id else '_global'
    config.setdefault('inline_sticker_keywords',{}).setdefault(gid,{}).setdefault(kw,{})['shared'] = val
    save_config(config)

def _get_inline_queue(sn, uid=None):
    """Get the queue for a pack. If shared mode, use per-user queue."""
    if uid is not None and inline_shared_queue.get(sn, {}).get(uid):
        return inline_shared_queue[sn][uid]
    return inline_queue.get(sn, [])

def _get_inline_discard(sn, uid=None):
    """Get discard dict for a pack. If shared mode, use per-user discard."""
    if uid is not None and inline_shared_discard.get(sn):
        return inline_shared_discard[sn]
    return inline_discard.get(sn, {})

def _set_inline_queue(sn, val, uid=None):
    """Set the queue for a pack."""
    if uid is not None:
        inline_shared_queue.setdefault(sn, {})[uid] = val
        _save_json(SHARED_QUEUE_FILE, inline_shared_queue)
    else:
        inline_queue[sn] = val
        _save_json(INLINE_QUEUE_FILE, inline_queue)

def _save_shared_state():
    _save_json(SHARED_QUEUE_FILE, inline_shared_queue)
    _save_json(SHARED_DISCARD_FILE, inline_shared_discard)

def _load_shared_state():
    global inline_shared_queue, inline_shared_discard
    q = _load_json(SHARED_QUEUE_FILE)
    inline_shared_queue.clear(); inline_shared_queue.update(q)
    for sn in list(inline_shared_queue.keys()):
        inline_shared_queue[sn] = {int(uid): cards for uid, cards in inline_shared_queue[sn].items()}
    d = _load_json(SHARED_DISCARD_FILE)
    inline_shared_discard.clear(); inline_shared_discard.update(d)
    for sn in list(inline_shared_discard.keys()):
        inline_shared_discard[sn] = {int(uid): cards for uid, cards in inline_shared_discard[sn].items()}

def _init_shared_pool(sn, uid):
    """Initialize per-user shared pool from main cache."""
    from random import shuffle
    pool = list(inline_cache.get(sn, []))
    shuffle(pool)
    inline_shared_queue.setdefault(sn, {})[uid] = pool
    inline_shared_discard.setdefault(sn, {}).setdefault(uid, [])
    _save_shared_state()

def _is_limited_set(sn):
    """Check if any inline keyword points to this set in limited mode."""
    for gid, kws in config.get('inline_sticker_keywords', {}).items():
        for kw, v in kws.items():
            s = v.get('set', '') if isinstance(v, dict) else v
            if s == sn:
                mode = v.get('mode', '') if isinstance(v, dict) else ''
                if mode == 'limited':
                    return True
                if not mode and v.get('random'):
                    return False  # Old format without mode
    return False

# ========== 文本卡牌池 (Text Card Pools) ==========
def _get_tk(group_id='_global'):
    """Get text_keywords for a group."""
    return config.get('text_keywords', {}).get(str(group_id) if group_id else '_global', {})

def _save_text_game_state():
    """Persist text_game_state to disk for crash recovery."""
    _save_json(TEXT_GAME_FILE, text_game_state)

def _load_text_game_state():
    """Load text_game_state from disk."""
    loaded = _load_json(TEXT_GAME_FILE)
    if loaded:
        text_game_state.update(loaded)
    return text_game_state

def _get_group_name(gid):
    if str(gid) == '_global':
        return '全局默认'
    return config.get('known_groups', {}).get(str(gid), f'群组 {gid}')

def _resolve_group(update, user_id):
    """Resolve group context: in group chat use chat_id, in private use user_selected_group."""
    chat = update.effective_chat
    if chat and chat.type in ['group', 'supergroup']:
        gid = str(chat.id)
        # Auto-register group in known_groups
        known = config.setdefault('known_groups', {})
        if gid not in known:
            known[gid] = chat.title or f"群组{gid}"
            save_config(config)
        # Auto-set as user's selected group for management
        user_selected_group[user_id] = gid
        return gid
    return user_selected_group.get(user_id, '_global')

async def _refresh_common_groups(bot, user_id):
    """Check which known groups the user is a member of. Cache the result."""
    known = config.get('known_groups', {})
    common = {}
    for group_id, group_name in known.items():
        try:
            member = await bot.get_chat_member(int(group_id), user_id)
            if member.status in ['member', 'administrator', 'creator', 'restricted']:
                common[group_id] = group_name
        except Exception:
            pass
    user_common_groups[user_id] = common
    logger.info(f"Common groups for user {user_id}: {len(common)} groups")
    return common

def _all_sticker_sets():
    """Get all unique sticker/emoji set names across all groups."""
    sets = set()
    for gid, kws in config.get('sticker_keywords', {}).items():
        for v in kws.values():
            sn = v.get('set', '') if isinstance(v, dict) else v
            if sn: sets.add(sn)
    for gid, kws in config.get('inline_sticker_keywords', {}).items():
        for v in kws.values():
            sn = v.get('set', '') if isinstance(v, dict) else v
            if sn: sets.add(sn)
    for gid, kws in config.get('emoji_keywords', {}).items():
        for v in kws.values():
            sn = v.get('set', '') if isinstance(v, dict) else v
            if sn: sets.add(sn)
    return sets

def _init_queue(sn, cache, queue):
    if sn in cache:
        stickers = list(cache[sn]); random.shuffle(stickers); queue[sn] = stickers


def _filter_blocked_stickers(sn, stickers_full):
    """Filter out ⛔ stickers from a pack and store them in kept.
    Returns list of allowed file_ids."""
    allowed = []
    blocked = []
    for s in stickers_full:
        fid = s.file_id
        emoji_val = getattr(s, 'emoji', None)
        sticker_emoji_map[fid] = str(emoji_val) if emoji_val else ''
        if emoji_val and str(emoji_val).strip() == '⛔':
            blocked.append(fid)
        else:
            allowed.append(fid)
    if blocked:
        # Replace blocked list (avoid dupes on restart)
        inline_kept.setdefault(sn, {})[0] = blocked
        _save_kept()
        logger.info(f"Blocked {len(blocked)} ⛔ stickers from '{sn}', stored in kept")
    elif 0 in inline_kept.get(sn, {}):
        # Pack no longer has any ⛔ stickers, clean up
        del inline_kept[sn][0]
        if not inline_kept[sn]:
            del inline_kept[sn]
        _save_kept()
    return allowed

def load_config():
    if not CONFIG_FILE.exists():
        return {"keywords": {}, "sticker_keywords": {"_global": {}},
                "inline_sticker_keywords": {"_global": {}},
                "emoji_keywords": {"_global": {}},
                "image_keywords": {"_global": {}}, "known_groups": {},
                "admin_ids": [], "enabled_features": {"keyword_reply": True}}
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f: return json.load(f)

def save_config(cfg): _save_json(CONFIG_FILE, cfg)

config = load_config()
_migrate_config()  # Auto-migrate old format


def _show_main_menu_text(user, group_id='_global'):
    """Build the main menu text and keyboard."""
    gname = _get_group_name(group_id)
    text = (
        f"你好 {user.first_name}!\n"
        f"管理群组: {gname}\n\n"
        f"/help 查看命令"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("选择群组", callback_data='select_group')],
        [InlineKeyboardButton("关键词管理", callback_data='manage_keywords')],
    ])
    return text, keyboard

def _build_list_keyboard(inline=False, emoji=False, image=False, group_id='_global'):
    if image:
        sk = _get_img_kw(group_id); cache = img_cache; get_mode = _img_get_mode
        prefix = 'replace_image_'; delete_prefix = 'delete_image_'
    elif emoji:
        sk = _get_ek(group_id); cache = emoji_cache; get_mode = _emoji_get_mode
        prefix = 'replace_emoji_'; delete_prefix = 'delete_emoji_'
    elif inline:
        sk = _get_ik(group_id); cache = inline_cache; get_mode = _inline_get_mode
        prefix = 'replace_inline_'; delete_prefix = 'delete_inline_'
    else:
        sk = _get_sk(group_id); cache = sticker_cache; get_mode = _get_mode
        prefix = 'replace_'; delete_prefix = 'delete_'
    copy_prefix = 'copyinline_' if inline else 'copykw_'
    keyboard = []
    for kw in sk:
        v = sk[kw]
        if image:
            files = v.get('files', []) if isinstance(v, dict) else []
            cnt = len(files); sn_display = f"{cnt}张"
            dc_count = sum(len(v) for v in img_discard.get(_img_kw_key(group_id, kw), {}).values())
            dcount = f" 弃牌{dc_count}" if dc_count > 0 else ""
            mode = get_mode(kw, group_id)
            stitch = _img_get_stitch(kw, group_id)
            stitch_label = "拼" if stitch else "—"
            keyboard.append([
                InlineKeyboardButton(
                    f"{kw} ({sn_display})[{_get_mode_label(mode)}]{stitch_label}{dcount}",
                    callback_data=f'{prefix}{kw}'
                ),
                InlineKeyboardButton(
                    f"拼接{'✔' if stitch else '✘'}",
                    callback_data=f'toggle_image_stitch_{kw}'
                ),
                InlineKeyboardButton("删除", callback_data=f'{delete_prefix}{kw}')
            ])
            continue
        sn = v.get('set', '') if isinstance(v, dict) else v
        cnt = len(cache.get(sn, []))
        total_hand = sum(len(v) for v in inline_hand.get(sn, {}).values()) if inline else 0
        hcnt = f" 手牌{total_hand}" if inline and total_hand else ""
        if image:
            total_dc = sum(len(v) for v in img_discard.get(sn, {}).values())
            dcount = f" 弃牌{total_dc}" if total_dc > 0 else ""
        elif emoji:
            total_dc = sum(len(v) for v in emoji_discard.get(sn, {}).values())
            dcount = f" 弃牌{total_dc}" if total_dc > 0 else ""
        elif inline:
            total_dc = sum(len(v) for v in inline_discard.get(sn, {}).values())
            dc_users = len(inline_discard.get(sn, {}))
            if total_dc > 0:
                dcount = f" 弃牌{total_dc}" if dc_users == 1 else f" 弃牌{total_dc}({dc_users}人)"
            else:
                dcount = ""
        else:
            dcount = ""
        mode = get_mode(kw, group_id)
        keyboard.append([
            InlineKeyboardButton(
                f"{kw} -> {sn} ({cnt}张)[{_get_mode_label(mode)}]{hcnt}{dcount} [替换]",
                callback_data=f'{prefix}{kw}'
            ),
            InlineKeyboardButton(
                "添加到其他群组",
                callback_data=f'{copy_prefix}{kw}'
            ) if not image else InlineKeyboardButton(
                "删除",
                callback_data=f'{delete_prefix}{kw}'
            ),
            InlineKeyboardButton(
                "删除",
                callback_data=f'{delete_prefix}{kw}'
            ) if not image else None,
        ])
        # Remove None entries from image rows
        keyboard[-1] = [b for b in keyboard[-1] if b is not None]
    return keyboard

def _build_group_select_keyboard(user_id, groups=None, page=0):
    """Build a paginated group selection keyboard.
    If groups is a dict, use it directly. Otherwise read from known_groups.
    """
    if groups is None:
        known = config.get('known_groups', {})
        groups = {'_global': '全局默认', **known}
    else:
        groups = {'_global': '全局默认', **groups}

    groups_list = list(groups.items())
    selected = user_selected_group.get(user_id, '_global')

    per_page = 6; start = page * per_page; end = start + per_page
    page_groups = groups_list[start:end]

    keyboard = []
    for gid, name in page_groups:
        label = f"✓ {name}" if str(gid) == str(selected) else name
        keyboard.append([InlineKeyboardButton(label, callback_data=f'setgroup_{gid}')])

    # Pagination
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ 上一页", callback_data=f'group_page_{page-1}'))
    if end < len(groups_list):
        nav.append(InlineKeyboardButton("下一页 ▶", callback_data=f'group_page_{page+1}'))
    if nav:
        keyboard.append(nav)

    keyboard.append([InlineKeyboardButton("返回主菜单", callback_data='back_to_start')])
    return InlineKeyboardMarkup(keyboard)

def _build_copy_target_keyboard(user_id, targets, is_inline=False):
    """Build keyboard for selecting a target group to copy keyword to."""
    prefix = 'docopyi_' if is_inline else 'docopy_'
    keyboard = []
    for tgid, tname in targets.items():
        keyboard.append([InlineKeyboardButton(
            tname,
            callback_data=f'{prefix}{tgid}'
        )])
    keyboard.append([InlineKeyboardButton("取消返回", callback_data='cancel_replace')])
    return InlineKeyboardMarkup(keyboard)

