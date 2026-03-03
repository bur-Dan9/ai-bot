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
BUILD_TAG = "MINIAPP_V11_SINGLE_WELCOME_NO_DOUBLE_REPLY"
print(f"### BUILD: {BUILD_TAG} ###", flush=True)

# ============================================================
# ✅ ENV (Render -> Environment)
# ============================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")
DATABASE_URL = os.environ.get("DATABASE_URL")

BOT_USERNAME = os.environ.get("BOT_USERNAME")  # bot username without "@"
REPORT_TASK_TOKEN = os.environ.get("REPORT_TASK_TOKEN")
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ai-bot-a3aj.onrender.com").rstrip("/")

# Optional: if =1 then owner receives live feed of user messages (default OFF)
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
    "Ты — Soffi, дружелюбный и общительный AI-ассистент AWM OS.\n"
    "Ты говоришь естественно и тепло, как умный помощник, без канцелярита и без давления.\n"
    "Ты можешь отвечать на отвлечённые вопросы и поддерживать лёгкий диалог, но всегда мягко возвращаешь разговор к воронке.\n"
    "ВСЕГДА общайся уважительно и обращайся к пользователю на «Вы».\n\n"

    "Контекст продукта:\n"
    "AWM OS — AI-система маркетинга в Telegram без человеческого фактора. Работает 24/7: принимает задачи и сразу приступает.\n"
    "Есть два направления:\n"
    "1) AI Маркетинг (9 этапов): старт цели → аудит → аудитория → конкуренты → креативы → SMM → реклама → аналитика → масштаб.\n"
    "Отчёты в Telegram: текст, таблица или PDF.\n"
    "2) AI Разработка: сайт/лендинг + Telegram Mini App + интеграция с ботом (лиды/отчёты).\n"
    "Сервис скоро запускается: мы на финальной стадии разработки.\n\n"

    "Услуги (ровно 4):\n"
    "A) AI-Маркетинг Автопилот — подписка (ежемесячно), полное сопровождение 24/7.\n"
    "B) Разработка экосистемы — разово: сайт + Telegram Mini App под ключ.\n"
    "C) Глубокий AI-аудит — разово: диагностика воронки и точек роста.\n"
    "D) Content & Ads Turbo — подписка (ежемесячно): запуск и контроль трафика без человеческого фактора, "
    "24/7 анализ креативов и оптимизация на данных (слабое выключаем, сильное усиливаем).\n\n"

    "Главная цель диалога:\n"
    "Собрать максимум данных и довести до заявки.\n"
    "Данные, которые нужно собрать:\n"
    "- Имя и ниша (если НЕ сайт — через Mini App; если сайт lead_123 — уже есть, Mini App не нужен)\n"
    "- Что человек хочет получить (1–2 предложения)\n"
    "- Какая услуга лучше подходит (ты предлагаешь сама)\n"
    "- Комфортный бюджет (после согласования услуги):\n"
    "  • для подписки (Автопилот, Turbo) — диапазон в месяц\n"
    "  • для разовой услуги (Экосистема, Аудит) — диапазон разово\n\n"

    "Правила воронки:\n"
    "1) Если лид НЕ с сайта: сначала направь в Mini App (имя+ниша). После Mini App сделай ОДНО подтверждение: имя/ниша верно?\n"
    "   Если нет — попроси исправить одним сообщением и продолжай дальше.\n"
    "2) Если лид с сайта (lead_123): Mini App пропускаем.\n"
    "3) Ты НЕ называешь цены и НЕ говоришь тарифы. Никогда.\n"
    "4) Ты НЕ обещаешь конкретные финансовые результаты.\n"
    "5) Ты анализируешь текст пользователя и сама предлагаешь 1 наиболее подходящую услугу.\n"
    "   Затем один раз уточняешь: «Ок фиксирую X или выбрать другой?»\n"
    "6) Бюджет спрашиваешь ТОЛЬКО после того, как услуга согласована.\n"
    "7) После бюджета: говоришь, что мы завершаем разработку и уведомим о старте/условиях в этом чате.\n\n"

    "Как предлагать услугу (по смыслу):\n"
    "- Если хотят системно ‘под ключ’, контент+реклама+ведение, регулярность → Автопилот.\n"
    "- Если хотят сайт/лендинг, mini app, интеграцию, инфраструктуру → Экосистема.\n"
    "- Если не понимают ‘почему не работает’, хотят разбор/диагностику → Глубокий AI-аудит.\n"
    "- Если нужно усилить рекламу/креативы/трафик, фокус на данных и оптимизация → Turbo.\n\n"

    "Поведение на отвлечённые вопросы:\n"
    "- Сначала коротко и по делу ответь.\n"
    "- Потом мягко вернись к шагу воронки одной фразой.\n"
    "Пример: «Да, могу объяснить. Чтобы зафиксировать заявку на запуск — скажите, что сейчас важнее…»\n\n"

    "Обязательные формулировки (используй по смыслу):\n"
    "- «Сервис скоро запускается, мы на финальном этапе разработки.»\n"
    "- «Без человеческого фактора: меньше субъективности, больше решений на данных.»\n"
    "- «Работаем 24/7: принимаем задачи и сразу приступаем.»\n"
    "- «Отчёты в Telegram: текст, таблица или PDF.»\n\n"

    "Формат ответа:\n"
    "- 1–4 строки\n"
    "- максимум 1–2 вопроса за раз\n"
    "- дружелюбно, уверенно, без давления\n"
)

WELCOME_TEXT = (
    "Здравствуйте! Я Soffi 🦾\n"
    "AWM OS — AI-система маркетинга в Telegram без человеческого фактора: 24/7 принимаем задачи и сразу приступаем.\n"
    "Отчёты — текстом, таблицей или PDF.\n\n"
    "Чтобы зафиксировать ранний доступ, заполните Mini App (имя + ниша)."
)

IG_WELCOME_TEXT = (
    "Здравствуйте! Я Soffi 🦾\n"
    "Вижу, Вы пришли из Instagram.\n"
    "AWM OS скоро запускается: AI-маркетинг в Telegram без человеческого фактора, 24/7.\n\n"
    "Чтобы зафиксировать ранний доступ, заполните Mini App (имя + ниша)."
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


def is_decline(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    patterns = [
        "не надо", "ничего", "ничем", "пока", "позже", "не сейчас", "нет", "не хочу", "неинтересно",
        "сам разберусь", "потом", "ок", "ясно", "спасибо", "спс", "всё", "хватит"
    ]
    return any(p in t for p in patterns)


def ask_gemini(contents: list[dict]) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.75, "maxOutputTokens": 700},
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
        return await conn.fetchval("SELECT business_niche FROM users WHERE tg_id=$1", int(tg_id))


async def db_set_user_niche(tg_id: int, niche: str):
    if not DB_POOL:
        return
    niche = (niche or "").strip()
    if not niche:
        return
    async with DB_POOL.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO users (tg_id, first_name, username, business_niche, contact, last_seen)
            VALUES ($1, '', '', NULLIF($2,''), NULL, now())
            ON CONFLICT (tg_id) DO UPDATE SET
              business_niche = COALESCE(NULLIF(users.business_niche,''), EXCLUDED.business_niche),
              last_seen = now()
            """,
            int(tg_id), niche
        )


async def db_log_message(tg_id: int, direction: str, text: str):
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


async def db_log_event(event: str, source: str, tg_id: int | None = None, lead_id: int | None = None, meta: dict | None = None):
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
    srcs: list[str] = []
    for e in events:
        s = (e.get("source") or "").strip()
        if not s:
            continue
        if not srcs or srcs[-1] != s:
            srcs.append(s)
    return " → ".join(srcs) if srcs else "-"


async def send_owner_report(period: str = "day"):
    if not OWNER_ID or not DB_POOL or tg_app is None:
        return

    interval = "1 day" if period == "day" else "7 days"

    async with DB_POOL.acquire() as conn:
        ev_rows = await conn.fetch(
            f"""
            SELECT tg_id, lead_id, event, source, meta, created_at
            FROM lead_events
            WHERE created_at >= now() - interval '{interval}'
            ORDER BY created_at ASC
            """
        )

        pending_web = await conn.fetch(
            f"""
            SELECT lead_id, created_at
            FROM lead_events
            WHERE tg_id IS NULL
              AND lead_id IS NOT NULL
              AND created_at >= now() - interval '{interval}'
              AND source='website'
            ORDER BY created_at DESC
            LIMIT 30
            """
        )

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
    lines.append(f"— пользователей с событиями: {len(by_tg)}")
    lines.append("")

    for tg_id, events in list(by_tg.items())[:60]:
        first_source, first_dt = await _get_first_source_for_tg(tg_id)
        chain = _compact_chain(events)

        name = "-"
        niche = "-"
        service = "-"
        budget = "-"

        for e in reversed(events):
            meta = e.get("meta") or {}
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if isinstance(meta, dict):
                if meta.get("name"):
                    name = meta["name"]
                if meta.get("niche"):
                    niche = meta["niche"]
                if meta.get("service"):
                    service = meta["service"]
                if meta.get("budget"):
                    budget = meta["budget"]
            if name != "-" and niche != "-" and service != "-" and budget != "-":
                break

        dt_s = first_dt.astimezone(timezone.utc).strftime("%d.%m %H:%M UTC") if first_dt else "-"
        lines.append(f"👤 tg_id={tg_id} | старт: {first_source or '-'} ({dt_s})")
        lines.append(f"   путь: {chain}")
        if name != "-" or niche != "-":
            lines.append(f"   профиль: {name} • {niche}")
        if service != "-" or budget != "-":
            lines.append(f"   запрос: {service} • бюджет: {budget}")
        lines.append("")

    if pending_web:
        lines.append("⏳ Website лиды без подтверждения (не нажали deep-link):")
        for r in pending_web[:30]:
            lead_id = r["lead_id"]
            dt = r["created_at"].astimezone(timezone.utc).strftime("%d.%m %H:%M UTC")
            lines.append(f"   lead_{lead_id} • {dt}")
        lines.append("")

    lines.append("🛠 Команды владельца:")
    lines.append("• /report day — отчёт за сутки")
    lines.append("• /report week — отчёт за 7 дней")
    lines.append("• /history <tg_id|@username> [limit] — история сообщений")
    lines.append("• /journey <tg_id|@username> [limit] — путь источников/событий")
    lines.append("• OWNER_LIVE_FEED=1 — включить живой поток (опционально)")

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
    /start ig               (Instagram source)
    /start lead_123         (website lead confirmation)
    """
    context.user_data["introduced"] = True
    context.user_data["history"] = []

    user = update.effective_user
    args = context.args or []

    # Instagram start
    if args and args[0].lower() in ("ig", "insta", "instagram"):
        await db_log_event(event="start", source="instagram", tg_id=int(user.id), meta={"from": "ig_deeplink"})
        await update.message.reply_text(IG_WELCOME_TEXT)
        return

    # Website confirm start
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
                        f"Здравствуйте, {final_name}! 👋\n"
                        f"Спасибо за заявку — Вы в списке раннего доступа ✅\n\n"
                        f"AWM OS скоро запускается: AI-маркетинг в Telegram без человеческого фактора, 24/7.\n"
                        f"Отчёты — текстом, таблицей или PDF.\n\n"
                        f"Чем ещё могу быть полезна?"
                    )

                    await update.message.reply_text(msg)
                    return

                await update.message.reply_text(
                    f"⚠️ Не нашла заявку по ссылке: lead_{lead_id}.\n"
                    f"Пожалуйста, отправьте форму ещё раз."
                )
                return

    # Default start
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
        limit = min(60, max(5, int(context.args[1])))

    async with DB_POOL.acquire() as conn:
        tg_id = None
        if key.startswith("@"):
            tg_id = await conn.fetchval("SELECT tg_id FROM users WHERE username=$1", key[1:])
        elif key.isdigit():
            tg_id = int(key)

        if not tg_id:
            await update.message.reply_text("Не нашла пользователя. Дайте tg_id или @username.")
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
        if len(t) > 350:
            t = t[:350] + "…"
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
        await update.message.reply_text("Формат: /journey <tg_id|@username> [limit]\nПример: /journey 123456789 60")
        return

    key = context.args[0].strip()
    limit = 40
    if len(context.args) > 1 and context.args[1].isdigit():
        limit = min(120, max(10, int(context.args[1])))

    async with DB_POOL.acquire() as conn:
        tg_id = None
        if key.startswith("@"):
            tg_id = await conn.fetchval("SELECT tg_id FROM users WHERE username=$1", key[1:])
        elif key.isdigit():
            tg_id = int(key)

        if not tg_id:
            await update.message.reply_text("Не нашла пользователя. Дайте tg_id или @username.")
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

    lines = [f"🧭 Путь для tg_id={tg_id} (событий: {len(rows)}):\n"]
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
        extra = []
        if lead_id:
            extra.append(f"lead_{lead_id}")
        if isinstance(meta, dict):
            if meta.get("name"):
                extra.append(f"name={meta['name']}")
            if meta.get("niche"):
                extra.append(f"niche={meta['niche']}")
            if meta.get("service"):
                extra.append(f"service={meta['service']}")
            if meta.get("budget"):
                extra.append(f"budget={meta['budget']}")
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

    await db_log_message(int(user.id), "in", text)
    await db_log_event(event="message", source="bot", tg_id=int(user.id), meta={"text_preview": text[:160]})

    # ✅ Prevent double greeting: first-ever message -> send welcome and STOP
    if not context.user_data.get("introduced"):
        context.user_data["introduced"] = True
        context.user_data["history"] = []
        await update.message.reply_text(WELCOME_TEXT)
        return

    # If user declines after form — ask name/niche politely
    if is_decline(text):
        if not context.user_data.get("name_confirmed"):
            tg_first = (user.first_name or "").strip()
            if tg_first:
                await update.message.reply_text(
                    f"Поняла. Подскажите, пожалуйста: корректно обращаться к Вам как **{tg_first}**? (да/нет)",
                    parse_mode="Markdown"
                )
                context.user_data["awaiting_name_confirm"] = True
                return

        current_niche = await db_get_user_niche(int(user.id))
        if not current_niche:
            await update.message.reply_text("Хорошо. Тогда уточню один момент: в какой отрасли Вы работаете? (1–2 слова)")
            context.user_data["awaiting_niche"] = True
            return

        await update.message.reply_text("Хорошо, спасибо! Если появятся вопросы — напишите в любой момент 😊")
        return

    # waiting name confirm (да/нет)
    if context.user_data.get("awaiting_name_confirm"):
        low = text.lower()
        if low in ("да", "ага", "ок", "yes", "y"):
            context.user_data["name_confirmed"] = True
            context.user_data["awaiting_name_confirm"] = False
            current_niche = await db_get_user_niche(int(user.id))
            if not current_niche:
                await update.message.reply_text("Спасибо! И ещё один вопрос: в какой отрасли Вы работаете? (1–2 слова)")
                context.user_data["awaiting_niche"] = True
                return
            await update.message.reply_text("Спасибо! Чем ещё могу быть полезна?")
            return
        if low in ("нет", "неа", "no", "n"):
            context.user_data["awaiting_name_confirm"] = False
            await update.message.reply_text("Как правильно к Вам обращаться? Напишите, пожалуйста, имя.")
            context.user_data["awaiting_name_manual"] = True
            return
        await update.message.reply_text("Подскажите, пожалуйста, просто «да» или «нет».")
        return

    # waiting name manual
    if context.user_data.get("awaiting_name_manual"):
        nm = text.strip()
        if len(nm) >= 2:
            context.user_data["name_confirmed"] = True
            context.user_data["awaiting_name_manual"] = False
            context.user_data["user_name"] = nm
            current_niche = await db_get_user_niche(int(user.id))
            if not current_niche:
                await update.message.reply_text("Спасибо. И ещё один вопрос: в какой отрасли Вы работаете? (1–2 слова)")
                context.user_data["awaiting_niche"] = True
                return
            await update.message.reply_text("Спасибо! Чем ещё могу быть полезна?")
            return
        await update.message.reply_text("Напишите, пожалуйста, имя (минимум 2 символа).")
        return

    # waiting niche
    if context.user_data.get("awaiting_niche"):
        n = text.strip()
        if len(n) >= 2:
            await db_set_user_niche(int(user.id), n)
            context.user_data["awaiting_niche"] = False
            await db_log_event(event="niche_set", source="bot", tg_id=int(user.id), meta={"niche": n})
            await update.message.reply_text("Спасибо! Чем ещё могу быть полезна?")
            return
        await update.message.reply_text("Напишите, пожалуйста, отрасль/нишу (1–2 слова).")
        return

    # Gemini normal flow
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
# ✅ Miniapp leads endpoint (Mini App = name+niche)
# After submit: asks "Чем ещё могу быть полезна?"
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

    await db_log_event(
        event="miniapp_submit",
        source="miniapp",
        tg_id=int(tg_id),
        lead_id=int(lead_id),
        meta={"name": name, "niche": niche},
    )

    final_name = (name or "").strip() or (first_name or "друг")
    final_niche = (niche or "").strip() or "—"

    user_msg = (
        f"Спасибо, {final_name}! ✅\n"
        f"Зафиксировала: ниша — {final_niche}.\n"
        f"Если нужно исправить — просто напишите как правильно (имя и ниша одним сообщением).\n\n"
        f"Чем ещё могу быть полезна?"
    )

    try:
        await tg_app.bot.send_message(chat_id=int(tg_id), text=user_msg)
    except Exception as e:
        print("send_message to user failed:", e)

    deeplink = f"https://t.me/{BOT_USERNAME}?start=lead_{lead_id}" if BOT_USERNAME else ""
    return web.json_response({"ok": True, "leadId": lead_id, "deeplink": deeplink})


# Website leads endpoint (optional)
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

    await db_log_event(
        event="website_submit",
        source="website",
        tg_id=None,
        lead_id=int(lead_id),
        meta={"name": name, "niche": niche},
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
    main()
