import os
import asyncio
import re
import requests
import json
import hmac
import hashlib
from datetime import datetime, timezone
from urllib.parse import parse_qsl
from aiohttp import web

import asyncpg

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ============================================================
# ✅ BUILD TAG (check deploy via /version)
# ============================================================
BUILD_TAG = "MINIAPP_V8_JOURNEY_DAILY_ONLY"
print(f"### BUILD: {BUILD_TAG} ###", flush=True)

# ============================================================
# ✅ ENV (Render -> Environment)
# ============================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")
DATABASE_URL = os.environ.get("DATABASE_URL")

BOT_USERNAME = os.environ.get("BOT_USERNAME")  # username бота без "@"
REPORT_TASK_TOKEN = os.environ.get("REPORT_TASK_TOKEN")  # секрет для /tasks/daily_report
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ai-bot-a3aj.onrender.com").rstrip("/")

# если =1, то владельцу будет приходить "живой поток" сообщений (по умолчанию выключено)
OWNER_LIVE_FEED = os.environ.get("OWNER_LIVE_FEED", "0") == "1"

# ============================================================
# ✅ CORS
# ============================================================
ALLOWED_ORIGINS = {
    "https://min-iapp.vercel.app",
    "https://awm-os.vercel.app",
}

# ============================================================
# ✅ GEMINI
# ============================================================
MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "Ты — Soffi, AI-ассистент агентства 'awm os'.\n"
    "Правила:\n"
    "1) НЕ представляйся заново в каждом ответе.\n"
    "2) Пиши кратко и по делу, без воды.\n"
    "3) Задавай 1-2 уточняющих вопроса, если нужно.\n"
    "4) Запоминай контекст диалога и имя пользователя (если он назвал).\n"
    "5) Цель: помогать и мягко вести к обсуждению задач бизнеса и бюджета на подписку.\n"
)

WELCOME_TEXT = (
    "Привет! Я Soffi 🦾\n"
    "Помогаю понять, как ИИ может ускорить маркетинг и продажи.\n"
    "Для начала: чем занимаетесь и в какой нише/городе?"
)

IG_WELCOME_TEXT = (
    "Привет! Я Soffi 🦾\n"
    "Вижу, вы пришли из Instagram.\n\n"
    "Что сейчас приоритетнее: лиды, контент или реклама?"
)

# ============================================================
# ✅ LIMITS / MEMORY
# ============================================================
MAX_TURNS = 12

MAX_REQUESTS_PER_DAY = 200
GLOBAL_LIMIT = {"date": None, "count": 0, "blocked_date": None}

tg_app: Application | None = None
DB_POOL: asyncpg.Pool | None = None


# ============================================================
# ✅ CORS middleware
# ============================================================
@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)

    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS, GET"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Task-Token"
    return resp


# ============================================================
# ✅ Helpers
# ============================================================
def _extract_name(text: str) -> str | None:
    t = text.strip()
    patterns = [
        r"\bменя\s+зовут\s+([A-Za-zА-Яа-яЁё\-]{2,30})\b",
        r"\bя\s+([A-Za-zА-Яа-яЁё\-]{2,30})\b",
        r"\bmy\s+name\s+is\s+([A-Za-z\-]{2,30})\b",
        r"\bi\s+am\s+([A-Za-z\-]{2,30})\b",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def ask_gemini(contents: list[dict]) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 700},
    }

    r = requests.post(endpoint, params={"key": GOOGLE_API_KEY}, json=payload, timeout=20)

    if r.status_code == 429:
        raise RuntimeError("429: quota/rate limit")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")

    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates returned: {data}")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    if not parts or "text" not in parts[0]:
        raise RuntimeError(f"Bad response format: {data}")

    return parts[0]["text"]


def _check_and_update_global_limit() -> tuple[bool, str | None]:
    today = datetime.now(timezone.utc).date()
    today_s = str(today)

    if GLOBAL_LIMIT.get("blocked_date") == today_s:
        return False, "⚠️ Лимит на сегодня исчерпан. Попробуйте завтра."

    if GLOBAL_LIMIT.get("date") != today_s:
        GLOBAL_LIMIT["date"] = today_s
        GLOBAL_LIMIT["count"] = 0
        GLOBAL_LIMIT["blocked_date"] = None

    if GLOBAL_LIMIT["count"] >= MAX_REQUESTS_PER_DAY:
        GLOBAL_LIMIT["blocked_date"] = today_s
        return False, "⚠️ Лимит на сегодня исчерпан. Попробуйте завтра."

    GLOBAL_LIMIT["count"] += 1
    return True, None


def verify_telegram_webapp_init_data(init_data: str, bot_token: str) -> dict:
    if not init_data:
        raise ValueError("Missing initData")

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing hash")

    check_string = "\n".join([f"{k}={data[k]}" for k in sorted(data.keys())])

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        key=secret_key,
        msg=check_string.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Invalid initData hash")

    if "user" in data:
        data["user"] = json.loads(data["user"])

    return data


async def db_get_user_niche(tg_id: int) -> str | None:
    if not DB_POOL:
        return None
    async with DB_POOL.acquire() as conn:
        return await conn.fetchval("SELECT business_niche FROM users WHERE tg_id=$1", tg_id)


async def db_log_message(tg_id: int, direction: str, text: str):
    """direction: 'in' | 'out' """
    if not DB_POOL:
        return
    text = (text or "").strip()
    if not text:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (tg_id, direction, text) VALUES ($1, $2, $3)",
            int(tg_id), direction, text
        )


async def db_log_event(
    event: str,
    source: str,
    tg_id: int | None = None,
    lead_id: int | None = None,
    meta: dict | None = None,
):
    """
    Лента событий/переходов (путь пользователя):
    пример: instagram -> miniapp_submit -> start_chat -> ...
    """
    if not DB_POOL:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO lead_events (tg_id, lead_id, event, source, meta)
            VALUES ($1, $2, $3, $4, $5)
            """,
            int(tg_id) if tg_id is not None else None,
            int(lead_id) if lead_id is not None else None,
            event,
            source,
            json.dumps(meta or {}),
        )


# ============================================================
# ✅ Reports / Journey
# ============================================================
async def _get_first_source_for_tg(tg_id: int) -> tuple[str | None, datetime | None]:
    if not DB_POOL:
        return None, None
    async with DB_POOL.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT source, created_at
            FROM lead_events
            WHERE tg_id=$1
            ORDER BY created_at ASC
            LIMIT 1
            """,
            int(tg_id),
        )
    if not row:
        return None, None
    return row["source"], row["created_at"]


def _compact_chain(events: list[dict]) -> str:
    """
    Делает красивую цепочку источников:
    instagram → miniapp → bot
    (удаляет подряд одинаковые)
    """
    srcs: list[str] = []
    for e in events:
        s = (e.get("source") or "").strip()
        if not s:
            continue
        if not srcs or srcs[-1] != s:
            srcs.append(s)
    return " → ".join(srcs) if srcs else "-"


async def send_owner_report(period: str = "day"):
    """
    ✅ Только дневной/недельный отчёт владельцу.
    ❌ Никаких мгновенных уведомлений о лидах.
    """
    if not OWNER_ID or not DB_POOL or tg_app is None:
        return

    interval = "1 day" if period == "day" else "7 days"

    async with DB_POOL.acquire() as conn:
        # Все события за период
        ev_rows = await conn.fetch(
            f"""
            SELECT tg_id, lead_id, event, source, meta, created_at
            FROM lead_events
            WHERE created_at >= now() - interval '{interval}'
            ORDER BY created_at ASC
            """
        )

        # Лиды, у которых ещё нет tg_id (например, website_submit без подтверждения)
        pending_web = await conn.fetch(
            f"""
            SELECT lead_id, created_at, meta
            FROM lead_events
            WHERE tg_id IS NULL
              AND lead_id IS NOT NULL
              AND created_at >= now() - interval '{interval}'
              AND source='website'
            ORDER BY created_at DESC
            LIMIT 30
            """
        )

    # Группируем по tg_id
    by_tg: dict[int, list[dict]] = {}
    for r in ev_rows:
        tg_id = r["tg_id"]
        if tg_id is None:
            continue
        by_tg.setdefault(int(tg_id), []).append(
            {
                "event": r["event"],
                "source": r["source"],
                "meta": r["meta"],
                "created_at": r["created_at"],
                "lead_id": r["lead_id"],
            }
        )

    lines: list[str] = []
    lines.append(f"📊 Отчёт за {period}")
    lines.append(f"— всего активных пользователей (события): {len(by_tg)}")
    lines.append("")

    # Показываем по каждому tg_id компактно
    for tg_id, events in list(by_tg.items())[:40]:
        first_source, first_dt = await _get_first_source_for_tg(tg_id)
        chain = _compact_chain(events)

        # вытащим имя/нишу из meta если есть
        name = "-"
        niche = "-"
        for e in reversed(events):
            meta = e.get("meta") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if meta.get("name"):
                name = meta["name"]
            if meta.get("niche"):
                niche = meta["niche"]
            if name != "-" and niche != "-":
                break

        dt_s = first_dt.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC") if first_dt else "-"
        lines.append(f"👤 tg_id={tg_id} | старт: {first_source or '-'} ({dt_s})")
        lines.append(f"   путь: {chain}")
        if name != "-" or niche != "-":
            lines.append(f"   форма: {name} • {niche}")
        lines.append("")

    # Если есть неподтверждённые website лиды (без tg_id)
    if pending_web:
        lines.append("⏳ Website лиды без подтверждения (не нажали deep-link):")
        for r in pending_web[:20]:
            lead_id = r["lead_id"]
            dt = r["created_at"].astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
            lines.append(f"   lead_{lead_id} • {dt}")
        lines.append("")

    # Подсказки по командам владельцу
    lines.append("🛠 Команды владельца:")
    lines.append("• /report day — отчёт за сутки")
    lines.append("• /report week — отчёт за 7 дней")
    lines.append("• /history <tg_id|@username> [limit] — история чата (messages)")
    lines.append("• /journey <tg_id|@username> [limit] — путь источников и событий")
    lines.append("• OWNER_LIVE_FEED=1 — включить живой поток сообщений (опционально)")

    try:
        await tg_app.bot.send_message(chat_id=int(OWNER_ID), text="\n".join(lines))
    except Exception as e:
        print("send_owner_report failed:", e)


# ============================================================
# ✅ Telegram handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start
    /start ig               (источник Instagram)
    /start lead_123         (подтверждение лидов с сайта)
    """
    context.user_data["introduced"] = True
    context.user_data["history"] = []

    user = update.effective_user
    args = context.args or []

    # ---------- (IG) Лид пришёл из Instagram ----------
    if args and args[0].lower() in ("ig", "insta", "instagram"):
        tg_id = int(user.id)

        # upsert users (best effort)
        if DB_POOL:
            async with DB_POOL.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (tg_id, first_name, username, business_niche, contact, last_seen)
                    VALUES ($1, $2, $3, NULL, NULL, now())
                    ON CONFLICT (tg_id) DO UPDATE SET
                      first_name = EXCLUDED.first_name,
                      username = EXCLUDED.username,
                      last_seen = now()
                """, tg_id, user.first_name or "", user.username or "")

        # log journey event (no owner instant message)
        await db_log_event(
            event="start",
            source="instagram",
            tg_id=tg_id,
            meta={"from": "ig_deeplink"},
        )

        await update.message.reply_text(IG_WELCOME_TEXT)
        return

    # ---------- (A) Подтверждение лида с сайта ----------
    if args and args[0].startswith("lead_") and DB_POOL:
        lead_id_str = args[0].split("lead_", 1)[1]
        if lead_id_str.isdigit():
            lead_id = int(lead_id_str)

            async with DB_POOL.acquire() as conn:
                lead = await conn.fetchrow(
                    "SELECT id, name_from_form, niche_from_form, contact_from_form FROM leads WHERE id=$1",
                    lead_id
                )

                if lead:
                    name_from_form = (lead["name_from_form"] or "").strip()
                    niche = (lead["niche_from_form"] or "").strip()
                    contact = (lead["contact_from_form"] or "").strip()

                    final_name = name_from_form if name_from_form else (user.first_name or "друг")

                    # upsert users
                    await conn.execute("""
                        INSERT INTO users (tg_id, first_name, username, business_niche, contact, last_seen)
                        VALUES ($1, $2, $3, NULLIF($4,''), NULLIF($5,''), now())
                        ON CONFLICT (tg_id) DO UPDATE SET
                          first_name = EXCLUDED.first_name,
                          username = EXCLUDED.username,
                          business_niche = COALESCE(users.business_niche, EXCLUDED.business_niche),
                          contact = COALESCE(users.contact, EXCLUDED.contact),
                          last_seen = now()
                    """, int(user.id), user.first_name or "", user.username or "", niche, contact)

                    # привязываем лид к tg_id
                    await conn.execute("UPDATE leads SET tg_id=$1 WHERE id=$2", int(user.id), lead_id)

                    # log journey
                    await db_log_event(
                        event="website_confirm",
                        source="website",
                        tg_id=int(user.id),
                        lead_id=lead_id,
                        meta={"name": name_from_form, "niche": niche, "contact": contact},
                    )

                    msg = (
                        f"**Здравствуйте, {final_name}! 👋**\n"
                        f"Меня зовут **Soff**. Спасибо, что оставили заявку — добро пожаловать в ранний доступ ✅\n\n"
                        f"Я — AI-ассистент **AWM OS**. Мы строим единый Telegram-интерфейс для управления **10+ ИИ-агентами**, "
                        f"которые 24/7 помогают бизнесу: от анализа до контента, рекламы и отчётов.\n"
                        f"Это **9 этапов автоматизации**, которые превращают хаос в прибыль и снимают с вас рутину.\n\n"
                        f"Вижу вашу сферу: **{niche or 'не указана'}**.\n"
                        f"Сервис ещё в разработке — завершаем финальную сборку.\n\n"
                        f"Подскажите, пожалуйста, что сейчас приоритетнее: **лиды, контент или реклама?**"
                    )

                    await update.message.reply_text(msg, parse_mode="Markdown")
                    return

                await update.message.reply_text(
                    f"⚠️ Не нашла заявку по ссылке: lead_{lead_id}.\n"
                    f"Пожалуйста, отправьте форму ещё раз."
                )
                return

    # ---------- (B) Обычный /start ----------
    await db_log_event(event="start", source="telegram", tg_id=int(user.id), meta={"from": "direct_start"})
    await update.message.reply_text(WELCOME_TEXT)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return

    period = (context.args[0] if context.args else "day").lower()
    if period not in ("day", "week"):
        period = "day"

    await send_owner_report(period)


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OWNER-only: /history <tg_id|@username> [limit]"""
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return
    if not DB_POOL:
        await update.message.reply_text("DB not ready")
        return
    if not context.args:
        await update.message.reply_text("Формат: /history <tg_id|@username> [limit]\nПример: /history 123456789 30")
        return

    key = context.args[0].strip()
    limit = 20
    if len(context.args) > 1 and context.args[1].isdigit():
        limit = min(50, max(5, int(context.args[1])))

    async with DB_POOL.acquire() as conn:
        tg_id = None
        if key.startswith("@"):
            tg_id = await conn.fetchval("SELECT tg_id FROM users WHERE username=$1", key[1:])
        elif key.isdigit():
            tg_id = int(key)

        if not tg_id:
            await update.message.reply_text("Не нашёл пользователя. Дай tg_id или @username.")
            return

        rows = await conn.fetch("""
            SELECT direction, text, created_at
            FROM messages
            WHERE tg_id=$1
            ORDER BY created_at DESC
            LIMIT $2
        """, tg_id, limit)

    if not rows:
        await update.message.reply_text("История пуста.")
        return

    rows = list(reversed(rows))
    lines = [f"🧾 История для tg_id={tg_id} (последние {len(rows)}):\n"]
    for r in rows:
        ts = r["created_at"].astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
        prefix = "👤" if r["direction"] == "in" else "🤖"
        t = r["text"]
        if len(t) > 300:
            t = t[:300] + "…"
        lines.append(f"{ts} {prefix} {t}")

    await update.message.reply_text("\n".join(lines))


async def journey_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OWNER-only: /journey <tg_id|@username> [limit]"""
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return
    if not DB_POOL:
        await update.message.reply_text("DB not ready")
        return
    if not context.args:
        await update.message.reply_text("Формат: /journey <tg_id|@username> [limit]\nПример: /journey 123456789 50")
        return

    key = context.args[0].strip()
    limit = 30
    if len(context.args) > 1 and context.args[1].isdigit():
        limit = min(80, max(10, int(context.args[1])))

    async with DB_POOL.acquire() as conn:
        tg_id = None
        if key.startswith("@"):
            tg_id = await conn.fetchval("SELECT tg_id FROM users WHERE username=$1", key[1:])
        elif key.isdigit():
            tg_id = int(key)

        if not tg_id:
            await update.message.reply_text("Не нашёл пользователя. Дай tg_id или @username.")
            return

        rows = await conn.fetch("""
            SELECT created_at, source, event, lead_id, meta
            FROM lead_events
            WHERE tg_id=$1
            ORDER BY created_at ASC
            LIMIT $2
        """, tg_id, limit)

    if not rows:
        await update.message.reply_text("Путь пуст.")
        return

    lines = [f"🧭 Путь для tg_id={tg_id} (первые {len(rows)} событий):\n"]
    for r in rows:
        ts = r["created_at"].astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
        source = r["source"] or "-"
        event = r["event"] or "-"
        lead_id = r["lead_id"]
        meta = r["meta"]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        name = meta.get("name") if isinstance(meta, dict) else None
        niche = meta.get("niche") if isinstance(meta, dict) else None
        extra = []
        if lead_id:
            extra.append(f"lead_{lead_id}")
        if name:
            extra.append(f"name={name}")
        if niche:
            extra.append(f"niche={niche}")
        extra_s = f" ({', '.join(extra)})" if extra else ""
        lines.append(f"{ts} • {source} • {event}{extra_s}")

    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    allowed, reason = _check_and_update_global_limit()
    if not allowed:
        await update.message.reply_text(reason)
        return

    # log incoming chat
    await db_log_message(int(user.id), "in", text)

    # also log a journey event that user is active in bot
    await db_log_event(event="message", source="bot", tg_id=int(user.id), meta={"text_preview": text[:120]})

    if not context.user_data.get("introduced"):
        context.user_data["introduced"] = True
        context.user_data["history"] = []
        await update.message.reply_text(WELCOME_TEXT)

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception:
        pass

    name = _extract_name(text)
    if name:
        context.user_data["user_name"] = name

    niche = await db_get_user_niche(int(user.id))

    history = context.user_data.get("history", [])
    user_name = context.user_data.get("user_name")

    prefix = ""
    if user_name:
        prefix += f"(Имя пользователя: {user_name})\n"
    if niche:
        prefix += f"(Ниша/род деятельности пользователя: {niche})\n"

    user_text_for_model = prefix + text if prefix else text

    history.append({"role": "user", "parts": [{"text": user_text_for_model}]})
    history = history[-(MAX_TURNS * 2):]

    try:
        answer = ask_gemini(history)
        await update.message.reply_text(answer)

        await db_log_message(int(user.id), "out", answer)

        history.append({"role": "model", "parts": [{"text": answer}]})
        history = history[-(MAX_TURNS * 2):]
        context.user_data["history"] = history

        # optional live feed
        if OWNER_LIVE_FEED and OWNER_ID and str(user.id) != str(OWNER_ID):
            try:
                await context.bot.send_message(
                    chat_id=int(OWNER_ID),
                    text=f"📈 Сообщение от лида!\n👤 {user.first_name} (@{user.username})\n💬 {text}"
                )
            except Exception as e:
                print("send_message to owner failed:", e)

    except Exception as e:
        err = str(e)
        low = err.lower()
        print("Gemini error:", err)

        if "429" in err or "resource_exhausted" in low or "quota" in low or "rate limit" in low:
            GLOBAL_LIMIT["blocked_date"] = str(datetime.now(timezone.utc).date())
            await update.message.reply_text("⚠️ Бесплатный лимит на сегодня исчерпан. Попробуйте завтра.")
            return

        if OWNER_ID:
            try:
                await context.bot.send_message(chat_id=int(OWNER_ID), text=f"❌ Gemini error:\n{err}")
            except Exception:
                pass

        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


# ============================================================
# ✅ HTTP endpoints
# ============================================================
async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def version(request: web.Request) -> web.Response:
    return web.Response(text=f"build={BUILD_TAG}")


async def webhook_handler(request: web.Request) -> web.Response:
    global tg_app
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    if tg_app is None:
        return web.Response(status=503, text="bot not ready")

    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return web.Response(text="ok")


# ============================================================
# ✅ Miniapp leads endpoint (short greeting; name from FORM only)
# ============================================================
async def api_leads_miniapp(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    init_data = body.get("initData") or ""
    form = body.get("form") or {}

    try:
        parsed = verify_telegram_webapp_init_data(init_data, TOKEN)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"initData invalid: {e}"}, status=401)

    user = parsed.get("user") or {}
    tg_id = user.get("id")
    first_name = user.get("first_name") or ""
    username = user.get("username") or ""

    if not tg_id or not DB_POOL or tg_app is None:
        return web.json_response({"ok": False, "error": "No tg_id or DB not ready"}, status=400)

    name = (form.get("name") or "").strip()
    niche = (form.get("niche") or "").strip()
    contact = (form.get("contact") or "").strip()

    async with DB_POOL.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (tg_id, first_name, username, business_niche, contact, last_seen)
            VALUES ($1, $2, $3, NULLIF($4,''), NULLIF($5,''), now())
            ON CONFLICT (tg_id) DO UPDATE SET
              first_name = EXCLUDED.first_name,
              username = EXCLUDED.username,
              business_niche = COALESCE(users.business_niche, EXCLUDED.business_niche),
              contact = COALESCE(users.contact, EXCLUDED.contact),
              last_seen = now()
        """, int(tg_id), first_name, username, niche, contact)

        lead_id = await conn.fetchval("""
            INSERT INTO leads (tg_id, source, name_from_form, niche_from_form, contact_from_form, payload)
            VALUES ($1, 'miniapp', NULLIF($2,''), NULLIF($3,''), NULLIF($4,''), $5)
            RETURNING id
        """, int(tg_id), name, niche, contact, json.dumps(form))

    # log journey (instagram => miniapp and so on)
    await db_log_event(
        event="miniapp_submit",
        source="miniapp",
        tg_id=int(tg_id),
        lead_id=int(lead_id),
        meta={"name": name, "niche": niche, "contact": contact},
    )

    final_name = (name or "").strip() or "друг"
    final_niche = (niche or "").strip() or "—"

    user_msg = (
        f"Привет, {final_name}! 👋\n"
        f"Спасибо, я записала вашу нишу: {final_niche}\n"
        f"Опиши задачу в 1 фразе — помогу."
    )

    try:
        await tg_app.bot.send_message(chat_id=int(tg_id), text=user_msg)
    except Exception as e:
        print("send_message to user failed:", e)

    deeplink = f"https://t.me/{BOT_USERNAME}?start=lead_{lead_id}" if BOT_USERNAME else ""
    return web.json_response({"ok": True, "leadId": lead_id, "deeplink": deeplink})


async def api_leads_website(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=204)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    name = (body.get("name") or "").strip()
    niche = (body.get("niche") or "").strip()
    contact = (body.get("contact") or "").strip()
    tg = (body.get("tg") or "").strip()

    if not DB_POOL or tg_app is None:
        return web.json_response({"ok": False, "error": "DB not ready"}, status=500)
    if not BOT_USERNAME:
        return web.json_response({"ok": False, "error": "Missing BOT_USERNAME"}, status=500)

    payload = {"name": name, "niche": niche, "contact": contact, "tg": tg}

    async with DB_POOL.acquire() as conn:
        lead_id = await conn.fetchval("""
            INSERT INTO leads (tg_id, source, name_from_form, niche_from_form, contact_from_form, payload)
            VALUES (NULL, 'website', NULLIF($1,''), NULLIF($2,''), NULLIF($3,''), $4)
            RETURNING id
        """, name, niche, tg or contact, json.dumps(payload))

    # log pending journey (no tg_id yet)
    await db_log_event(
        event="website_submit",
        source="website",
        tg_id=None,
        lead_id=int(lead_id),
        meta={"name": name, "niche": niche, "contact": tg or contact},
    )

    deeplink = f"https://t.me/{BOT_USERNAME}?start=lead_{lead_id}"
    return web.json_response({"ok": True, "leadId": lead_id, "deeplink": deeplink})


async def tasks_daily_report(request: web.Request) -> web.Response:
    token = request.headers.get("X-Task-Token") or request.query.get("token")
    if not REPORT_TASK_TOKEN or token != REPORT_TASK_TOKEN:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    try:
        await send_owner_report("day")
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


# ============================================================
# ✅ MAIN (webhook + api)
# ============================================================
async def main_async():
    global tg_app, DB_POOL

    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")
    if not DATABASE_URL:
        raise RuntimeError("Missing DATABASE_URL")

    DB_POOL = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    print("✅ DB pool ready", flush=True)

    # ensure tables for history + journey
    async with DB_POOL.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
              id BIGSERIAL PRIMARY KEY,
              tg_id BIGINT NOT NULL,
              direction TEXT NOT NULL,
              text TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_tg_id_created
            ON messages (tg_id, created_at DESC);
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS lead_events (
              id BIGSERIAL PRIMARY KEY,
              tg_id BIGINT NULL,
              lead_id BIGINT NULL,
              event TEXT NOT NULL,
              source TEXT NOT NULL,
              meta JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_lead_events_tg_created
            ON lead_events (tg_id, created_at ASC);
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_lead_events_created
            ON lead_events (created_at DESC);
        """)

    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("report", report))
    tg_app.add_handler(CommandHandler("history", history_cmd))
    tg_app.add_handler(CommandHandler("journey", journey_cmd))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await tg_app.initialize()
    await tg_app.start()

    port = int(os.environ.get("PORT", "10000"))
    web_app = web.Application(middlewares=[cors_middleware])

    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/version", version)

    web_app.router.add_post("/webhook", webhook_handler)

    web_app.router.add_post("/api/leads/miniapp", api_leads_miniapp)
    web_app.router.add_options("/api/leads/miniapp", api_leads_miniapp)

    web_app.router.add_post("/api/leads/website", api_leads_website)
    web_app.router.add_options("/api/leads/website", api_leads_website)

    web_app.router.add_get("/tasks/daily_report", tasks_daily_report)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    webhook_url = f"{BASE_URL}/webhook"
    await tg_app.bot.delete_webhook(drop_pending_updates=True)
    ok = await tg_app.bot.set_webhook(url=webhook_url)
    info = await tg_app.bot.get_webhook_info()

    print(f"✅ Bot started (WEBHOOK) on {webhook_url}, set_webhook={ok}", flush=True)
    print(f"✅ WebhookInfo: url={info.url} pending={info.pending_update_count} last_error={info.last_error_message}", flush=True)
    print("✅ API ready: /api/leads/miniapp  +  /api/leads/website", flush=True)
    print("✅ Task ready: GET /tasks/daily_report", flush=True)
    print("✅ Reports: /report day | /report week", flush=True)
    print("✅ History: /history <tg_id|@username> [limit] (OWNER only)", flush=True)
    print("✅ Journey: /journey <tg_id|@username> [limit] (OWNER only)", flush=True)

    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main())

IG_WELCOME_TEXT = (
    "Привет! Я Soffi 🦾\n"
    "Вижу, вы пришли из Instagram.\n\n"
    "Что сейчас приоритетнее: лиды, контент или реклама?"
)

# ============================================================
# ✅ LIMITS / MEMORY
# ============================================================
MAX_TURNS = 12

MAX_REQUESTS_PER_DAY = 200
GLOBAL_LIMIT = {"date": None, "count": 0, "blocked_date": None}

tg_app: Application | None = None
DB_POOL: asyncpg.Pool | None = None


# ============================================================
# ✅ CORS middleware
# ============================================================
@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        resp = web.Response(status=204)
    else:
        resp = await handler(request)

    origin = request.headers.get("Origin")
    if origin in ALLOWED_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS, GET"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Task-Token"
    return resp


# ============================================================
# ✅ Helpers
# ============================================================
def _extract_name(text: str) -> str | None:
    t = text.strip()
    patterns = [
        r"\bменя\s+зовут\s+([A-Za-zА-Яа-яЁё\-]{2,30})\b",
        r"\bя\s+([A-Za-zА-Яа-яЁё\-]{2,30})\b",
        r"\bmy\s+name\s+is\s+([A-Za-z\-]{2,30})\b",
        r"\bi\s+am\s+([A-Za-z\-]{2,30})\b",
    ]
    for p in patterns:
        m = re.search(p, t, flags=re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def ask_gemini(contents: list[dict]) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 700},
    }

    r = requests.post(endpoint, params={"key": GOOGLE_API_KEY}, json=payload, timeout=20)

    if r.status_code == 429:
        raise RuntimeError("429: quota/rate limit")
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")

    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates returned: {data}")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    if not parts or "text" not in parts[0]:
        raise RuntimeError(f"Bad response format: {data}")

    return parts[0]["text"]


def _check_and_update_global_limit() -> tuple[bool, str | None]:
    today = datetime.now(timezone.utc).date()
    today_s = str(today)

    if GLOBAL_LIMIT.get("blocked_date") == today_s:
        return False, "⚠️ Лимит на сегодня исчерпан. Попробуйте завтра."

    if GLOBAL_LIMIT.get("date") != today_s:
        GLOBAL_LIMIT["date"] = today_s
        GLOBAL_LIMIT["count"] = 0
        GLOBAL_LIMIT["blocked_date"] = None

    if GLOBAL_LIMIT["count"] >= MAX_REQUESTS_PER_DAY:
        GLOBAL_LIMIT["blocked_date"] = today_s
        return False, "⚠️ Лимит на сегодня исчерпан. Попробуйте завтра."

    GLOBAL_LIMIT["count"] += 1
    return True, None


def verify_telegram_webapp_init_data(init_data: str, bot_token: str) -> dict:
    if not init_data:
        raise ValueError("Missing initData")

    data = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise ValueError("Missing hash")

    check_string = "\n".join([f"{k}={data[k]}" for k in sorted(data.keys())])

    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        key=secret_key,
        msg=check_string.encode("utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Invalid initData hash")

    if "user" in data:
        data["user"] = json.loads(data["user"])

    return data


async def db_get_user_niche(tg_id: int) -> str | None:
    if not DB_POOL:
        return None
    async with DB_POOL.acquire() as conn:
        return await conn.fetchval("SELECT business_niche FROM users WHERE tg_id=$1", tg_id)


async def db_log_message(tg_id: int, direction: str, text: str):
    """direction: 'in' | 'out' """
    if not DB_POOL:
        return
    text = (text or "").strip()
    if not text:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages (tg_id, direction, text) VALUES ($1, $2, $3)",
            int(tg_id), direction, text
        )


async def send_owner_report(period: str = "day"):
    if not OWNER_ID or not DB_POOL or tg_app is None:
        return

    interval = "1 day" if period == "day" else "7 days"

    async with DB_POOL.acquire() as conn:
        total = await conn.fetchval(f"""
            SELECT count(*) FROM leads
            WHERE created_at >= now() - interval '{interval}'
        """)
        rows = await conn.fetch(f"""
            SELECT id, source, created_at, name_from_form, niche_from_form, contact_from_form
            FROM leads
            WHERE created_at >= now() - interval '{interval}'
            ORDER BY created_at DESC
            LIMIT 30
        """)

    lines = [f"📊 Отчёт за {period}: всего лидов = {total}\n"]
    for r in rows:
        dt = r["created_at"].astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
        lines.append(
            f"#{r['id']} [{r['source']}] {dt} | {r['name_from_form'] or '-'} | {r['niche_from_form'] or '-'} | {r['contact_from_form'] or '-'}"
        )

    try:
        await tg_app.bot.send_message(chat_id=int(OWNER_ID), text="\n".join(lines))
    except Exception as e:
        print("send_owner_report failed:", e)


# ============================================================
# ✅ Telegram handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start
    /start ig               (источник Instagram)
    /start lead_123         (подтверждение лидов с сайта)
    """
    context.user_data["introduced"] = True
    context.user_data["history"] = []

    user = update.effective_user
    args = context.args or []

    # ---------- (IG) Лид пришёл из Instagram ----------
    if args and args[0].lower() in ("ig", "insta", "instagram"):
        tg_id = int(user.id)
        first_name = user.first_name or ""
        username = user.username or ""
        lead_id = None

        if DB_POOL:
            async with DB_POOL.acquire() as conn:
                # upsert users
                await conn.execute("""
                    INSERT INTO users (tg_id, first_name, username, business_niche, contact, last_seen)
                    VALUES ($1, $2, $3, NULL, NULL, now())
                    ON CONFLICT (tg_id) DO UPDATE SET
                      first_name = EXCLUDED.first_name,
                      username = EXCLUDED.username,
                      last_seen = now()
                """, tg_id, first_name, username)

                # insert lead source=instagram (best effort)
                try:
                    lead_id = await conn.fetchval("""
                        INSERT INTO leads (tg_id, source, name_from_form, niche_from_form, contact_from_form, payload)
                        VALUES ($1, 'instagram', NULL, NULL, NULL, $2)
                        RETURNING id
                    """, tg_id, json.dumps({"source": "instagram"}))
                except Exception as e:
                    print("instagram lead insert failed:", e)

        # notify owner
        if OWNER_ID:
            try:
                extra = f"\n🆔 Lead ID: {lead_id}" if lead_id else ""
                await context.bot.send_message(
                    chat_id=int(OWNER_ID),
                    text=(
                        "📥 Новый лид из Instagram\n"
                        f"👤 {first_name or '-'} (@{username or '-'}) id={tg_id}"
                        f"{extra}"
                    )
                )
            except Exception as e:
                print("send ig lead to owner failed:", e)

        # show in bot chat that the lead came from Instagram
        await update.message.reply_text(IG_WELCOME_TEXT)
        return

    # ---------- (A) Подтверждение лида с сайта ----------
    if args and args[0].startswith("lead_") and DB_POOL:
        lead_id_str = args[0].split("lead_", 1)[1]
        if lead_id_str.isdigit():
            lead_id = int(lead_id_str)

            async with DB_POOL.acquire() as conn:
                lead = await conn.fetchrow(
                    "SELECT id, name_from_form, niche_from_form, contact_from_form FROM leads WHERE id=$1",
                    lead_id
                )

                if lead:
                    name_from_form = (lead["name_from_form"] or "").strip()
                    niche = (lead["niche_from_form"] or "").strip()
                    contact = (lead["contact_from_form"] or "").strip()

                    final_name = name_from_form if name_from_form else (user.first_name or "друг")

                    # upsert users
                    await conn.execute("""
                        INSERT INTO users (tg_id, first_name, username, business_niche, contact, last_seen)
                        VALUES ($1, $2, $3, NULLIF($4,''), NULLIF($5,''), now())
                        ON CONFLICT (tg_id) DO UPDATE SET
                          first_name = EXCLUDED.first_name,
                          username = EXCLUDED.username,
                          business_niche = COALESCE(users.business_niche, EXCLUDED.business_niche),
                          contact = COALESCE(users.contact, EXCLUDED.contact),
                          last_seen = now()
                    """, int(user.id), user.first_name or "", user.username or "", niche, contact)

                    # привязываем лид к tg_id
                    await conn.execute("UPDATE leads SET tg_id=$1 WHERE id=$2", int(user.id), lead_id)

                    # владельцу
                    if OWNER_ID:
                        try:
                            await context.bot.send_message(
                                chat_id=int(OWNER_ID),
                                text=f"✅ Лид подтвержден (Website) #{lead_id}\n👤 {user.first_name} (@{user.username}) id={user.id}"
                            )
                        except Exception:
                            pass

                    msg = (
                        f"**Здравствуйте, {final_name}! 👋**\n"
                        f"Меня зовут **Soff**. Спасибо, что оставили заявку — добро пожаловать в ранний доступ ✅\n\n"
                        f"Я — AI-ассистент **AWM OS**. Мы строим единый Telegram-интерфейс для управления **10+ ИИ-агентами**, "
                        f"которые 24/7 помогают бизнесу: от анализа до контента, рекламы и отчётов.\n"
                        f"Это **9 этапов автоматизации**, которые превращают хаос в прибыль и снимают с вас рутину.\n\n"
                        f"Вижу вашу сферу: **{niche or 'не указана'}**.\n"
                        f"Сервис ещё в разработке — завершаем финальную сборку.\n\n"
                        f"Подскажите, пожалуйста, что сейчас приоритетнее: **лиды, контент или реклама?**"
                    )

                    await update.message.reply_text(msg, parse_mode="Markdown")
                    return

                await update.message.reply_text(
                    f"⚠️ Не нашла заявку по ссылке: lead_{lead_id}.\n"
                    f"Пожалуйста, отправьте форму ещё раз."
                )
                return

    # ---------- (B) Обычный /start ----------
    await update.message.reply_text(WELCOME_TEXT)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return

    period = (context.args[0] if context.args else "day").lower()
    if period not in ("day", "week"):
        period = "day"

    await send_owner_report(period)


async def history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """OWNER-only: /history <tg_id|@username> [limit]"""
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return
    if not DB_POOL:
        await update.message.reply_text("DB not ready")
        return
    if not context.args:
        await update.message.reply_text("Формат: /history <tg_id|@username> [limit]\nПример: /history 123456789 30")
        return

    key = context.args[0].strip()
    limit = 20
    if len(context.args) > 1 and context.args[1].isdigit():
        limit = min(50, max(5, int(context.args[1])))

    async with DB_POOL.acquire() as conn:
        tg_id = None
        if key.startswith("@"):
            tg_id = await conn.fetchval("SELECT tg_id FROM users WHERE username=$1", key[1:])
        elif key.isdigit():
            tg_id = int(key)

        if not tg_id:
            await update.message.reply_text("Не нашёл пользователя. Дай tg_id или @username.")
            return

        rows = await conn.fetch("""
            SELECT direction, text, created_at
            FROM messages
            WHERE tg_id=$1
            ORDER BY created_at DESC
            LIMIT $2
        """, tg_id, limit)

    if not rows:
        await update.message.reply_text("История пуста.")
        return

    rows = list(reversed(rows))
    lines = [f"🧾 История для tg_id={tg_id} (последние {len(rows)}):\n"]
    for r in rows:
        ts = r["created_at"].astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
        prefix = "👤" if r["direction"] == "in" else "🤖"
        t = r["text"]
        if len(t) > 300:
            t = t[:300] + "…"
        lines.append(f"{ts} {prefix} {t}")

    await update.message.reply_text("\n".join(lines))


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    allowed, reason = _check_and_update_global_limit()
    if not allowed:
        await update.message.reply_text(reason)
        return

    await db_log_message(int(user.id), "in", text)

    if not context.user_data.get("introduced"):
        context.user_data["introduced"] = True
        context.user_data["history"] = []
        await update.message.reply_text(WELCOME_TEXT)

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception:
        pass

    name = _extract_name(text)
    if name:
        context.user_data["user_name"] = name

    niche = await db_get_user_niche(int(user.id))

    history = context.user_data.get("history", [])
    user_name = context.user_data.get("user_name")

    prefix = ""
    if user_name:
        prefix += f"(Имя пользователя: {user_name})\n"
    if niche:
        prefix += f"(Ниша/род деятельности пользователя: {niche})\n"

    user_text_for_model = prefix + text if prefix else text

    history.append({"role": "user", "parts": [{"text": user_text_for_model}]})
    history = history[-(MAX_TURNS * 2):]

    try:
        answer = ask_gemini(history)
        await update.message.reply_text(answer)

        await db_log_message(int(user.id), "out", answer)

        history.append({"role": "model", "parts": [{"text": answer}]})
        history = history[-(MAX_TURNS * 2):]
        context.user_data["history"] = history

        if OWNER_LIVE_FEED and OWNER_ID and str(user.id) != str(OWNER_ID):
            try:
                await context.bot.send_message(
                    chat_id=int(OWNER_ID),
                    text=f"📈 Сообщение от лида!\n👤 {user.first_name} (@{user.username})\n💬 {text}"
                )
            except Exception as e:
                print("send_message to owner failed:", e)

    except Exception as e:
        err = str(e)
        low = err.lower()
        print("Gemini error:", err)

        if "429" in err or "resource_exhausted" in low or "quota" in low or "rate limit" in low:
            GLOBAL_LIMIT["blocked_date"] = str(datetime.now(timezone.utc).date())
            await update.message.reply_text("⚠️ Бесплатный лимит на сегодня исчерпан. Попробуйте завтра.")
            return

        if OWNER_ID:
            try:
                await context.bot.send_message(chat_id=int(OWNER_ID), text=f"❌ Gemini error:\n{err}")
            except Exception:
                pass

        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


# ============================================================
# ✅ HTTP endpoints
# ============================================================
async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def version(request: web.Request) -> web.Response:
    return web.Response(text=f"build={BUILD_TAG}")


async def webhook_handler(request: web.Request) -> web.Response:
    global tg_app
    try:
        data = await request.json()
    except Exception:
        return web.Response(status=400, text="bad json")

    if tg_app is None:
        return web.Response(status=503, text="bot not ready")

    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return web.Response(text="ok")


# ============================================================
# ✅ Miniapp leads endpoint (short greeting; name from FORM only)
# ============================================================
async def api_leads_miniapp(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    init_data = body.get("initData") or ""
    form = body.get("form") or {}

    try:
        parsed = verify_telegram_webapp_init_data(init_data, TOKEN)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"initData invalid: {e}"}, status=401)

    user = parsed.get("user") or {}
    tg_id = user.get("id")
    first_name = user.get("first_name") or ""
    username = user.get("username") or ""

    if not tg_id or not DB_POOL or tg_app is None:
        return web.json_response({"ok": False, "error": "No tg_id or DB not ready"}, status=400)

    name = (form.get("name") or "").strip()
    niche = (form.get("niche") or "").strip()
    contact = (form.get("contact") or "").strip()

    async with DB_POOL.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (tg_id, first_name, username, business_niche, contact, last_seen)
            VALUES ($1, $2, $3, NULLIF($4,''), NULLIF($5,''), now())
            ON CONFLICT (tg_id) DO UPDATE SET
              first_name = EXCLUDED.first_name,
              username = EXCLUDED.username,
              business_niche = COALESCE(users.business_niche, EXCLUDED.business_niche),
              contact = COALESCE(users.contact, EXCLUDED.contact),
              last_seen = now()
        """, int(tg_id), first_name, username, niche, contact)

        lead_id = await conn.fetchval("""
            INSERT INTO leads (tg_id, source, name_from_form, niche_from_form, contact_from_form, payload)
            VALUES ($1, 'miniapp', NULLIF($2,''), NULLIF($3,''), NULLIF($4,''), $5)
            RETURNING id
        """, int(tg_id), name, niche, contact, json.dumps(form))

    final_name = (name or "").strip() or "друг"
    final_niche = (niche or "").strip() or "—"

    user_msg = (
        f"Привет, {final_name}! 👋\n"
        f"Спасибо, я записала вашу нишу: {final_niche}\n"
        f"Опиши задачу в 1 фразе — помогу."
    )

    try:
        await tg_app.bot.send_message(chat_id=int(tg_id), text=user_msg)
    except Exception as e:
        print("send_message to user failed:", e)

    if OWNER_ID:
        try:
            await tg_app.bot.send_message(
                chat_id=int(OWNER_ID),
                text=(
                    f"📩 Новый лид (Mini App) #{lead_id}\n"
                    f"👤 TG: {first_name} (@{username}) | id={tg_id}\n"
                    f"📝 Имя из формы: {name or '-'}\n"
                    f"🧩 Ниша из формы: {niche or '-'}\n"
                    f"☎️ Контакт: {contact or '-'}"
                )
            )
        except Exception as e:
            print("send_message to owner failed:", e)

    deeplink = f"https://t.me/{BOT_USERNAME}?start=lead_{lead_id}" if BOT_USERNAME else ""
    return web.json_response({"ok": True, "leadId": lead_id, "deeplink": deeplink})


async def api_leads_website(request: web.Request) -> web.Response:
    if request.method == "OPTIONS":
        return web.Response(status=204)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad JSON"}, status=400)

    name = (body.get("name") or "").strip()
    niche = (body.get("niche") or "").strip()
    contact = (body.get("contact") or "").strip()
    tg = (body.get("tg") or "").strip()

    if not DB_POOL or tg_app is None:
        return web.json_response({"ok": False, "error": "DB not ready"}, status=500)
    if not BOT_USERNAME:
        return web.json_response({"ok": False, "error": "Missing BOT_USERNAME"}, status=500)

    payload = {"name": name, "niche": niche, "contact": contact, "tg": tg}

    async with DB_POOL.acquire() as conn:
        lead_id = await conn.fetchval("""
            INSERT INTO leads (tg_id, source, name_from_form, niche_from_form, contact_from_form, payload)
            VALUES (NULL, 'website', NULLIF($1,''), NULLIF($2,''), NULLIF($3,''), $4)
            RETURNING id
        """, name, niche, tg or contact, json.dumps(payload))

    deeplink = f"https://t.me/{BOT_USERNAME}?start=lead_{lead_id}"

    if OWNER_ID:
        try:
            await tg_app.bot.send_message(
                chat_id=int(OWNER_ID),
                text=(
                    f"🌐 Новый лид (Website) #{lead_id}\n"
                    f"📝 Имя: {name or '-'}\n"
                    f"🧩 Ниша: {niche or '-'}\n"
                    f"📎 TG/Контакт: {tg or contact or '-'}\n"
                    f"🔗 Deep-link: {deeplink}\n"
                    f"ℹ️ Подтвердится, когда человек нажмёт ссылку."
                )
            )
        except Exception as e:
            print("send_message to owner failed:", e)

    return web.json_response({"ok": True, "leadId": lead_id, "deeplink": deeplink})


async def tasks_daily_report(request: web.Request) -> web.Response:
    token = request.headers.get("X-Task-Token") or request.query.get("token")
    if not REPORT_TASK_TOKEN or token != REPORT_TASK_TOKEN:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)

    try:
        await send_owner_report("day")
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


# ============================================================
# ✅ MAIN (webhook + api)
# ============================================================
async def main_async():
    global tg_app, DB_POOL

    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")
    if not DATABASE_URL:
        raise RuntimeError("Missing DATABASE_URL")

    DB_POOL = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    print("✅ DB pool ready", flush=True)

    # ensure messages table for /history
    async with DB_POOL.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
              id BIGSERIAL PRIMARY KEY,
              tg_id BIGINT NOT NULL,
              direction TEXT NOT NULL,
              text TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_tg_id_created
            ON messages (tg_id, created_at DESC);
        """)

    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("report", report))
    tg_app.add_handler(CommandHandler("history", history_cmd))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await tg_app.initialize()
    await tg_app.start()

    port = int(os.environ.get("PORT", "10000"))
    web_app = web.Application(middlewares=[cors_middleware])

    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)
    web_app.router.add_get("/version", version)

    web_app.router.add_post("/webhook", webhook_handler)

    web_app.router.add_post("/api/leads/miniapp", api_leads_miniapp)
    web_app.router.add_options("/api/leads/miniapp", api_leads_miniapp)

    web_app.router.add_post("/api/leads/website", api_leads_website)
    web_app.router.add_options("/api/leads/website", api_leads_website)

    web_app.router.add_get("/tasks/daily_report", tasks_daily_report)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    webhook_url = f"{BASE_URL}/webhook"
    await tg_app.bot.delete_webhook(drop_pending_updates=True)
    ok = await tg_app.bot.set_webhook(url=webhook_url)
    info = await tg_app.bot.get_webhook_info()

    print(f"✅ Bot started (WEBHOOK) on {webhook_url}, set_webhook={ok}", flush=True)
    print(f"✅ WebhookInfo: url={info.url} pending={info.pending_update_count} last_error={info.last_error_message}", flush=True)
    print("✅ API ready: /api/leads/miniapp  +  /api/leads/website", flush=True)
    print("✅ Task ready: GET /tasks/daily_report", flush=True)
    print("✅ Reports: /report day | /report week", flush=True)
    print("✅ History: /history <tg_id|@username> [limit] (OWNER only)", flush=True)

    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
