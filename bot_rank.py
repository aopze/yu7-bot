#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bot_rank.py — 方舟战棋 Mini App 排行榜（接 bot.py）

职责:
  1. /play        —— 发送 Telegram Web App 按钮，打开方舟战棋
  2. 接收游戏 sendData 回来的成绩（filters.StatusUpdate.WEB_APP_DATA）
  3. 用 initData 做 HMAC-SHA256 验签（仿冒直接丢弃）+ auth_date 新鲜度校验
  4. 成绩落盘 rank_state.json（每个用户只保留最佳，列表有界）
  5. /rank        —— 展示 Top 20 排行榜

接入（在 bot.py）:
  from bot_rank import play_command, rank_command, handle_web_app_data
  app.add_handler(CommandHandler("play", play_command))
  app.add_handler(CommandHandler("rank", rank_command))
  app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
  BotCommand("play", "打开方舟战棋"),
  BotCommand("rank", "查看战棋排行榜"),
"""
import os, json, time, hmac, hashlib, logging, base64, subprocess, ssl, asyncio
import urllib.request, urllib.error, urllib.parse
from pathlib import Path

# aiohttp 由 python-telegram-bot 间接依赖，用于给 Mini App 提供上报端点（菜单/内联入口记成绩用）。
try:
    from aiohttp import web as _aio_web
except Exception:  # pragma: no cover
    _aio_web = None

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ===== 配置（按需修改）=====
# Mini App 必须是「绑定域名上的直接 HTML 文件地址」，不要用 WorkBuddy 的 ?sharecode= 预览页。
# 可在 .env 里写 WEBAPP_URL=... 覆盖。
WEBAPP_URL = os.getenv(
    "WEBAPP_URL",
    "https://aopze.github.io/ark-rogue-chess/",
)

RANK_FILE = Path(__file__).parent / "rank_state.json"
MAX_DAILY_STALE = 86400  # initData 超过 24h 视为重放攻击，拒绝

# 诊断用：记录最近一次收到的 Mini App 数据（/minidata 查看）
_LAST_DATA = {"count": 0, "last_raw": "", "last_ts": 0, "last_stage": "尚未收到任何 Mini App 数据"}


def _mark(stage, raw=""):
    _LAST_DATA["count"] += 1
    _LAST_DATA["last_raw"] = raw[:300]
    _LAST_DATA["last_ts"] = int(time.time())
    _LAST_DATA["last_stage"] = stage


# ========== Mini App 上报端点（菜单 / 内联入口也能记成绩）==========
# 背景：Telegram 规定 sendData 只在 keyboard button 入口生效；菜单按钮 / 内联按钮
# 打开的 Mini App 没有回传通道。这些入口虽然没有 sendData，但带「签名过的 initData」。
# 于是 Mini App 用 fetch POST 一个 JSON 到本 bot 的 /api/score，bot 端用 initData 验签
# 确认身份（id 不能被伪造），再落库。这样「主页按钮」也能记录成绩，且支持中文玩家名。
_APP = None          # PTB Application（用于后台调度排行榜同步）
_LOOP = None         # PTB 事件循环
BOT_USERNAME = ""    # bot 的 @username（写入 leaderboard.json 供前端读取）
REPORT_URL = ""      # 上报端点公网地址（写入 leaderboard.json 供前端读取）

CORS_ORIGIN = os.getenv("MINIAPP_CORS_ORIGIN", "https://aopze.github.io")


def set_application(app):
    """由 bot.py 在启动后注入 PTB Application 与事件循环。"""
    global _APP, _LOOP
    _APP = app
    try:
        _LOOP = asyncio.get_running_loop()
    except Exception:
        try:
            _LOOP = asyncio.get_event_loop()
        except Exception:
            _LOOP = None


def _schedule_sync():
    """把排行榜同步调度到 PTB 事件循环（跨线程安全）。"""
    try:
        users = _load_rank().get("users", {})
        if _APP is not None and _LOOP is not None and _LOOP.is_running():
            coro = _sync_leaderboard_task(build_leaderboard_entries(users))
            if _LOOP is asyncio.get_event_loop():
                _APP.create_task(coro)
            else:
                asyncio.run_coroutine_threadsafe(coro, _LOOP)
        else:
            publish_leaderboard(build_leaderboard_entries(users))
    except Exception as e:
        logger.warning(f"[榜单] 调度同步失败: {e}")


async def fetch_bot_profile(app):
    """启动时拿 bot 自身信息，推导上报端点地址，并写进排行榜数据。"""
    global BOT_USERNAME, REPORT_URL
    try:
        me = await app.bot.get_me()
        BOT_USERNAME = me.username or ""
    except Exception as e:
        logger.warning(f"获取 bot 信息失败: {e}")
    # 推导上报公网地址
    url = os.getenv("MINIAPP_REPORT_URL", "").strip()
    if not url:
        wh = os.getenv("WEBHOOK_URL", "").strip()
        if wh:
            url = urllib.parse.urljoin(wh, "/api/score")
        else:
            dom = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip() or os.getenv("FLY_APP_NAME", "").strip()
            if dom:
                host = dom if dom.startswith("http") else f"https://{dom}"
                url = urllib.parse.urljoin(host.rstrip("/") + "/", "/api/score")
    REPORT_URL = url
    logger.info(f"[上报] bot_username={BOT_USERNAME} report_url={REPORT_URL}")
    # 立即把 bot_username / report_url 写进 GitHub Pages，前端才能读到
    try:
        publish_leaderboard(build_leaderboard_entries(_load_rank().get("users", {})))
    except Exception as e:
        logger.warning(f"[上报] 初次写入排行榜元数据失败: {e}")


def _extract_user_from_init(init_data: str):
    """从 initData 解析出 (user_id, first_name, username)。无则返回 (0,'','')。"""
    if not init_data:
        return 0, "", ""
    try:
        params = {}
        for kv in init_data.split("&"):
            k, _, v = kv.partition("=")
            params[k] = urllib.parse.unquote(v)
        raw = params.get("user", "")
        if raw:
            u = json.loads(raw)
            return int(u.get("id", 0) or 0), (u.get("first_name") or ""), (u.get("username") or "")
    except Exception:
        pass
    return 0, "", ""


# ========== 共享的写入逻辑（sendData 路径与 HTTP 路径都调用）==========
def record_score(uid, name, level, kills):
    """写入/更新某用户的成绩（仅保留最佳）。返回该用户记录。"""
    uid = str(uid)
    data = _load_rank()
    users = data.setdefault("users", {})
    prev = users.get(uid, {"name": name, "best_level": 0, "best_kills": 0, "runs": 0, "last_ts": 0})
    prev["name"] = name or prev.get("name") or "匿名"
    prev["best_level"] = max(prev.get("best_level", 0), int(level or 0))
    prev["best_kills"] = max(prev.get("best_kills", 0), int(kills or 0))
    prev["runs"] = prev.get("runs", 0) + 1
    prev["last_ts"] = int(time.time())
    users[uid] = prev
    _save_rank(data)
    logger.info(f"[成绩] id={uid} name={prev['name']} level={level} kills={kills} 累计={prev['runs']}")
    return prev


def rename_user(uid, name):
    """修改某用户的展示名。返回该用户记录。"""
    uid = str(uid)
    name = (name or "").strip()[:24]
    if not name:
        return None
    data = _load_rank()
    users = data.setdefault("users", {})
    prev = users.get(uid)
    if prev is None:
        prev = {"name": name, "best_level": 0, "best_kills": 0, "runs": 0, "last_ts": int(time.time())}
    else:
        prev["name"] = name
    users[uid] = prev
    _save_rank(data)
    logger.info(f"[改名] id={uid} -> name={name}")
    return prev


# ========== aiohttp 上报端点 ==========
def _cors_headers():
    return {
        "Access-Control-Allow-Origin": CORS_ORIGIN,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }


async def _handle_report(request):
    """POST /api/score —— Mini App 上报成绩/改名（菜单、内联、带 initData 的入口）。"""
    if request.method == "OPTIONS":
        return _aio_web.Response(text="", headers=_cors_headers())
    try:
        payload = await request.json()
    except Exception:
        return _aio_web.json_response({"ok": False, "error": "bad_json"}, status=400,
                                      headers=_cors_headers())
    kind = payload.get("kind") or payload.get("type") or ""
    init_data = payload.get("initData") or ""
    bot_token = os.getenv("BOT_TOKEN", "")
    if not _verify_init_data(init_data, bot_token):
        logger.warning("[上报] initData 验签失败，拒绝")
        return _aio_web.json_response({"ok": False, "error": "bad_init"}, status=403,
                                      headers=_cors_headers())
    uid, tg_first, tg_user = _extract_user_from_init(init_data)
    if not uid:
        return _aio_web.json_response({"ok": False, "error": "no_user"}, status=400,
                                      headers=_cors_headers())

    if kind == "score":
        level = int(payload.get("level", 0) or 0)
        kills = int(payload.get("kills", 0) or 0)
        name = payload.get("name") or tg_first or tg_user or f"玩家{str(uid)[-4:]}"
        rec = record_score(uid, name, level, kills)
        _mark("上报端点收到成绩")
        _schedule_sync()
        return _aio_web.json_response(
            {"ok": True, "level": rec["best_level"], "kills": rec["best_kills"], "runs": rec["runs"]},
            headers=_cors_headers())
    elif kind == "rename":
        name = payload.get("name") or ""
        rec = rename_user(uid, name)
        _schedule_sync()
        return _aio_web.json_response({"ok": True, "name": rec["name"] if rec else name},
                                      headers=_cors_headers())
    return _aio_web.json_response({"ok": False, "error": "unknown_kind"}, status=400,
                                  headers=_cors_headers())


async def _handle_health(request):
    return _aio_web.Response(text="ok", headers={"Content-Type": "text/plain"})


def make_report_app():
    """构造供 Mini App 上报用的 aiohttp 应用（webhook 模式下作为 web= 传入；polling 模式下独立运行）。"""
    if _aio_web is None:
        logger.warning("[上报] aiohttp 不可用，/api/score 端点不会启动")
        return None
    app = _aio_web.Application()
    app.router.add_post("/api/score", _handle_report)
    app.router.add_route("OPTIONS", "/api/score", _handle_report)
    app.router.add_get("/", _handle_health)
    return app


# ===== 榜单同步到 GitHub Pages（供游戏内嵌的排行榜模块读取）=====
# 游戏内的 leaderboard.html 会 fetch 同域的 leaderboard.json；
# bot 每收到一条成绩就把最新榜单写回去（带 60 秒防抖，避免频繁提交）。
GH_REPO = "aopze/ark-rogue-chess"
GH_BRANCH = "main"
GH_LEADERBOARD = "leaderboard.json"
_last_publish_ts = 0.0


def _gh_token():
    """从 git credential manager 取 GitHub 凭据（系统级 helper，用户本机可用）。"""
    try:
        out = subprocess.run(
            ["git", "credential", "fill"],
            input="protocol=https\nhost=github.com\n\n",
            capture_output=True, text=True, timeout=30,
            encoding="mbcs" if os.name == "nt" else "utf-8",
            errors="replace",
        ).stdout
        for line in out.splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception as e:
        logger.warning(f"取 GitHub 凭据失败: {e}")
    return None


def _gh_api(method, path, token, data=None):
    url = f"https://api.github.com/repos/{GH_REPO}{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45, context=ssl.create_default_context()) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return -1, str(e)


def publish_leaderboard(entries):
    """把榜单写入 GitHub Pages 的 leaderboard.json（失败不影响主流程）。"""
    global _last_publish_ts
    now = time.time()
    if now - _last_publish_ts < 60:
        return False
    _last_publish_ts = now
    token = _gh_token()
    if not token:
        logger.warning("[榜单] 拿不到 GitHub 凭据，跳过同步（游戏内排行榜会显示旧数据）")
        return False
    payload = {
        "updated_at": int(now),
        "entries": entries,
        "bot_username": BOT_USERNAME,
        "report_url": REPORT_URL,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")
    # 已存在则要带 sha（GitHub 的更新接口要求）
    s, b = _gh_api("GET", f"/contents/{GH_LEADERBOARD}?ref={GH_BRANCH}", token)
    sha = b.get("sha") if isinstance(b, dict) else None
    data = {
        "message": f"更新排行榜 {len(entries)} 条",
        "content": base64.b64encode(content).decode(),
        "branch": GH_BRANCH,
    }
    if sha:
        data["sha"] = sha
    s, b = _gh_api("PUT", f"/contents/{GH_LEADERBOARD}", token, data)
    if s in (200, 201):
        logger.info(f"[榜单] 已同步到 GitHub Pages（{len(entries)} 条）")
        return True
    logger.warning(f"[榜单] 同步失败 HTTP {s}: {str(b)[:200]}")
    return False


def build_leaderboard_entries(users):
    """把 rank_state.json 的 users 转成榜单条目（按层数→击杀排序）。"""
    entries = []
    for key, u in users.items():
        entries.append({
            "id": key,
            "name": u.get("name", "匿名"),
            "level": u.get("best_level", 0),
            "kills": u.get("best_kills", 0),
            "runs": u.get("runs", 0),
        })
    entries.sort(key=lambda e: (e["level"], e["kills"]), reverse=True)
    return entries[:100]


async def _sync_leaderboard_task(entries):
    """后台同步榜单（网络操作放线程池，不阻塞事件循环）。"""
    try:
        await asyncio.to_thread(publish_leaderboard, entries)
    except Exception as e:
        logger.warning(f"[榜单] 同步异常: {e}")


def schedule_leaderboard_sync(context, users):
    """把榜单同步丢到后台跑。"""
    try:
        entries = build_leaderboard_entries(users)
        app = getattr(context, "application", None)
        if app is not None:
            app.create_task(_sync_leaderboard_task(entries))
        else:
            publish_leaderboard(entries)
    except Exception as e:
        logger.warning(f"[榜单] 调度失败: {e}")


# ========== 持久化 ==========
def _load_rank():
    if RANK_FILE.exists():
        try:
            return json.loads(RANK_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("rank_state.json 损坏，重建")
    return {"users": {}}


def _save_rank(data):
    tmp = RANK_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(RANK_FILE)
    except Exception as e:
        logger.warning(f"保存排行榜失败: {e}")


def _verify_init_data(init_data: str, bot_token: str) -> bool:
    """Telegram WebApp 数据验签。空 initData（本地浏览器直开）放行但不作信任证明。"""
    if not init_data:
        return True  # 本地试玩，无签名
    try:
        params = {}
        for kv in init_data.split("&"):
            k, _, v = kv.partition("=")
            params[k] = v
    except Exception:
        return False
    hash_ = params.pop("hash", None)
    if not hash_:
        return False
    # data_check_string: 除 hash 外按 key 字母序，key=value 用 \n 连接
    data_check = "\n".join(f"{k}={params[k]}" for k in sorted(params))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    computed = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(computed, hash_):
        return False
    # 新鲜度校验（防重放）
    try:
        auth_date = int(params.get("auth_date", "0"))
        if auth_date and (time.time() - auth_date) > MAX_DAILY_STALE:
            logger.warning("initData 过期，疑似重放，拒绝")
            return False
    except Exception:
        pass
    return True


# ========== 菜单按钮（bot 主页/聊天常驻入口）==========
async def setup_menu_button(application):
    """把 Mini App 挂到 bot 的菜单按钮（聊天输入框旁的常驻按钮 + 主页「打开」入口）。"""
    # 注入 Application / 循环，并拉取 bot 元数据（username + 上报端点地址）
    set_application(application)
    try:
        await fetch_bot_profile(application)
    except Exception as e:
        logger.warning(f"获取 bot 元数据失败: {e}")
    try:
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="▶️ 方舟战棋",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        )
        logger.info("Menu button 已挂接 Mini App")
    except Exception as e:
        logger.warning(f"设置菜单按钮失败: {e}")


# ========== 命令 ==========
async def play_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """发送打开方舟战棋的 Web App 按钮。

    ★ 必须用「回复键盘上的 web_app 按钮」(KeyboardButton)，不能用内联按钮/菜单按钮。
    Telegram 官方规定：Telegram.WebApp.sendData **只在 keyboard button 入口下可用**；
    inline button / menu button 打开的 Mini App 调 sendData 不会产生任何 web_app_data 更新
    （那两个入口只有 initData，没有回传通道）。
    代价：keyboard button 入口的 initData 为空 → 没有签名身份，改用 chat_id 标识用户
    （私聊里 chat_id == user_id，web_app_data 是 Telegram 服务端投递的，可信）。
    """
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("▶️ 方舟战棋", web_app=WebAppInfo(url=WEBAPP_URL))]],
        resize_keyboard=True,
        one_time_keyboard=True,      # 用一次就自动收起，不长期占用户的输入框
    )
    text = (
        "点击下方键盘上的「▶️ 方舟战棋」开始游戏。\n\n"
        "📌 怎么记录成绩：在游戏里打到 **Game Over（阵亡或通关）** 时，"
        "会自动把「第几层 / 击杀数」发回给我，我会回一条「✅ 成绩已记录」，"
        "之后用 /rank 看排行榜。\n\n"
        "✅ **所有入口都能记成绩**：\n"
        "· 点这个键盘按钮进入 → 成绩就地直接回传（最顺滑）\n"
        "· 点 bot 主页的菜单按钮进入 → 也会记录（走上报服务）\n"
        "· 在游戏主页可改玩家名，改名会同步到排行榜\n\n"
        f"（在浏览器直接打开只预览、不记成绩：{WEBAPP_URL}）"
    )
    try:
        await update.message.reply_text(text, reply_markup=kb)
    except Exception as e:
        logger.exception("play_command 发送失败")
        await update.message.reply_text(f"⚠️ 打开游戏失败：{e}")


async def minidata_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """诊断：Mini App 成绩上报链路状态。"""
    d = _LAST_DATA
    data = _load_rank()
    n = len(data.get("users", {}))
    lines = [
        "🔧 Mini App 上报链路诊断",
        "",
        f"入口地址：{WEBAPP_URL}",
        f"收到数据次数：{d['count']}",
        f"最后阶段：{d['last_stage']}",
    ]
    if d["last_ts"]:
        lines.append(f"最后收到时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(d['last_ts']))}")
        lines.append(f"原始数据：{d['last_raw']}")
    lines += [
        "",
        f"排行榜人数：{n}",
        "",
    ]
    if d["count"] == 0:
        lines.append("⚠️ 一次都没收到过数据 → 说明 sendData 没发出来或被 Telegram 拦了。")
        lines.append("请确认：① 在 Telegram 里打开（不是浏览器）② 游戏真的打到了 Game Over。")
    elif n == 0:
        lines.append("⚠️ 收到过数据但没入库 → 看上面的「最后阶段」。")
    else:
        lines.append("✅ 链路正常，排行榜有数据。")
    await update.message.reply_text("\n".join(lines))


async def rank_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """展示排行榜 Top 20。"""
    data = _load_rank()
    users = data.get("users", {})
    if not users:
        await update.message.reply_text(
            "还没有任何成绩。\n\n"
            "去 /play 打一局，打到 Game Over 就会自动记录。\n"
            "如果打完还是空的，用 /minidata 看是哪一环断了。"
        )
        return
    board = sorted(
        users.values(),
        key=lambda u: (u.get("best_level", 0), u.get("best_kills", 0)),
        reverse=True,
    )[:20]
    lines = ["🏆 方舟战棋排行榜（按最深层数）", ""]
    for i, u in enumerate(board, 1):
        name = u.get("name", "匿名")
        lvl = u.get("best_level", 0)
        kills = u.get("best_kills", 0)
        lines.append(f"{i:>2}. {name} — 第 {lvl} 层 / 击杀 {kills}")
    await update.message.reply_text("\n".join(lines))
    # 顺便把榜单同步到 GitHub Pages，游戏内排行榜模块就能看到最新数据
    schedule_leaderboard_sync(context, users)


async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """接收 Mini App 通过 sendData 回传的数据（成绩 rogue_score / 改名 rename）。

    仅 keyboard button 入口走这条路（initData 为空，用 chat_id 认身份）。
    菜单/内联入口改走 HTTP 上报端点 /api/score（见 _handle_report）。
    """
    wad = update.effective_message.web_app_data
    if not wad:
        return
    raw = wad.data or ""
    logger.info(f"[MiniApp] 收到 web_app_data: {raw[:300]}")
    _mark("收到 web_app_data", raw)
    try:
        payload = json.loads(raw)
    except Exception:
        logger.warning(f"[MiniApp] web_app_data 不是合法 JSON，忽略: {raw[:200]}")
        _mark("JSON 解析失败")
        return
    kind = payload.get("type") or payload.get("kind") or ""
    chat = update.effective_chat
    is_private = (chat.type == "private")
    tg_id = chat.id  # keyboard 入口没有签名身份，用 chat_id（私聊里 == user_id）

    if kind == "rename":
        name = (payload.get("name") or "").strip()[:24]
        if not name:
            return
        rename_user(tg_id, name)
        _mark("改名已入库")
        _schedule_sync()
        await update.effective_message.reply_text(f"✅ 名字已更新为：{name}\n排行榜马上同步。")
        return

    if kind != "rogue_score":
        logger.info(f"[MiniApp] 收到但类型不是 rogue_score，忽略: {kind}")
        _mark(f"类型不是 rogue_score（{kind}）")
        return  # 非本游戏的数据

    name = payload.get("tg_name") or ""
    level = int(payload.get("level", 0) or 0)
    kills = int(payload.get("kills", 0) or 0)

    if not name or name == "匿名":
        name = f"玩家{str(tg_id)[-4:]}"
    logger.info(f"[MiniApp] keyboard 入口，chat_id={tg_id}（私聊={is_private}）")
    if not is_private:
        await update.effective_message.reply_text(
            "⚠️ 排行榜建议在**私聊**里玩，才能区分是谁的成绩。"
            "本次成绩已按本群记录。\n"
            f"（成绩：第 {level} 层 / 击杀 {kills}）"
        )

    rec = record_score(tg_id, name, level, kills)
    _mark("已入库")
    _schedule_sync()
    await update.effective_message.reply_text(
        f"✅ 成绩已记录：第 {level} 层 / 击杀 {kills}（累计 {rec['runs']} 局）\n"
        f"用 /rank 查看排行榜"
    )
