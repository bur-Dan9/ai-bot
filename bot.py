import os
import asyncio
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
from telegram import InputFile

# ============================================================
# ✅ BUILD TAG (check deploy via /version)
# ============================================================
BUILD_TAG = "MINIAPP_V20_REELS_SITE_FLOW_WITH_REF_IMAGES"
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

OWNER_LIVE_FEED = os.environ.get("OWNER_LIVE_FEED", "0") == "1"

# ============================================================
# ✅ CORS
# ============================================================
ALLOWED_ORIGINS = {
    "https://min-iapp.vercel.app",
    "https://awm-os.vercel.app",
}

# ============================================================
# ✅ GEMINI (fallback for non-scripted)
# ============================================================
MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "Ты — Soffi, дружелюбный и общительный AI-ассистент AWM OS.\n"
    "Говори естественно, уверенно и уважительно, всегда на «Вы».\n"
    "Ты отвечаешь на вопросы по теме и на отвлечённые вопросы, но мягко возвращаешь к воронке.\n"
    "НЕ называй цены/тарифы/диапазоны/примеры сумм. Только спрашивай: «на какую сумму Вы рассчитываете».\n\n"
    "Контекст продукта:\n"
    "AWM OS — AI-система маркетинга в Telegram без человеческого фактора. 24/7 принимает задачи и сразу приступает.\n"
    "Отчёты — в Telegram: текст, таблица или PDF.\n\n"
    "Услуги (ровно 4):\n"
    "1) AI-Маркетинг Автопилот — подписка: ведение Instagram под ключ (контент/сторис/постинг) + реклама при необходимости.\n"
    "2) Content & Ads Turbo — подписка: только реклама/трафик/креативы и оптимизация на данных (без ведения Instagram).\n"
    "3) Разработка экосистемы — разово: сайт + Telegram Mini App + интеграции.\n"
    "4) Глубокий AI-аудит — разово: диагностика воронок и точки роста.\n\n"
    "КЛЮЧЕВОЕ ПРАВИЛО:\n"
    "Если в контексте есть «Mini App уже заполнен: ДА» — НИКОГДА больше не проси заполнить Mini App.\n\n"
    "Формат ответов:\n"
    "— 1–8 строк, без воды.\n"
    "— максимум 1–2 вопроса за раз.\n"
)

WELCOME_TEXT = (
    "Здравствуйте! Я Soffi 🦾\n"
    "Я помогу Вам подключиться к AWM OS — AI-системе маркетинга в Telegram, которая работает 24/7.\n\n"
    "Откройте Mini App (AWM OS) — там Вы сможете оставить заявку на ранний доступ\n"
    "⬇️"
)

IG_WELCOME_TEXT = (
    "Здравствуйте! Я Soffi 🦾\n"
    "Вижу, Вы пришли из Instagram.\n\n"
    "Откройте Mini App (AWM OS) — там Вы сможете оставить заявку на ранний доступ\n"
    "⬇️"
)

POST_MINIAPP_TEXT = (
    "Отлично! ✅ Я зафиксировала Вашу нишу.\n\n"
    "Чтобы предложить самое подходящее решение, выберите, что Вам ближе (можно цифрой):\n"
    "1) AI-Маркетинг Автопилот — ведение Instagram под ключ + реклама при необходимости\n"
    "2) Content & Ads Turbo — только реклама/трафик/креативы (без ведения Instagram)\n"
    "3) Разработка экосистемы — сайт + Telegram Mini App + интеграции под ключ\n"
    "4) Глубокий AI-аудит — разбор воронки и точек роста\n\n"
    "Если не уверены — напишите коротко цель, и я подберу сама."
)

# ============================================================
# ✅ REELS SITE FLOW SETTINGS
# ============================================================
SITE_PUBLISH_URL = "https://coffe-topaz.vercel.app/"

REF_IMAGES = ["ref-1.png", "ref-2.png", "ref-3.png"]  # must be next to bot.py

OK_WORDS = {"ок", "окей", "okay", "ok", "отлично", "супер", "хорошо", "подходит"}

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


def _is_ok(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return t in OK_WORDS


def _looks_like_link(text: str) -> bool:
    t = (text or "").strip().lower()
    return ("http://" in t) or ("https://" in t) or ("dribbble.com" in t)

# ============================================================
# ✅ DB helpers
# ============================================================
async def db_get_user_niche(tg_id: int) -> str | None:
    if not DB_POOL:
        return None
    async with DB_POOL.acquire() as conn:
        return await conn.fetchval("SELECT business_niche FROM users WHERE tg_id=$1", int(tg_id))


async def db_get_latest_miniapp_profile(tg_id: int) -> tuple[str | None, str | None]:
    if not DB_POOL:
        return None, None
    async with DB_POOL.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT name_from_form, niche_from_form
            FROM leads
            WHERE tg_id=$1 AND source='miniapp'
            ORDER BY id DESC
            LIMIT 1
            """,
            int(tg_id),
        )
    if not row:
        return None, None
    return (row["name_from_form"], row["niche_from_form"])


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
# ✅ Owner report (unchanged)
# ============================================================
async def send_owner_report(period: str = "day"):
    if not OWNER_ID or not DB_POOL or tg_app is None:
        return

    interval = "1 day" if period == "day" else "7 days"
    async with DB_POOL.acquire() as conn:
        ev_rows = await conn.fetch(
            f"""
            SELECT tg_id, source, created_at
            FROM lead_events
            WHERE created_at >= now() - interval '{interval}'
            ORDER BY created_at ASC
            """
        )

    by_tg: dict[int, list[str]] = {}
    for r in ev_rows:
        if r["tg_id"] is None:
            continue
        by_tg.setdefault(int(r["tg_id"]), []).append(r["source"] or "-")

    lines = [f"📊 Отчёт за {period}", f"— пользователей с событиями: {len(by_tg)}", ""]
    for tg_id, chain in list(by_tg.items())[:60]:
        lines.append(f"👤 tg_id={tg_id}")
        lines.append(f"   путь: {' → '.join(chain)}")
        lines.append("")

    lines += [
        "🛠 Команды владельца:",
        "• /report day — отчёт за сутки",
        "• /report week — отчёт за 7 дней",
        "• /forget <tg_id> — забыть пользователя (БД + память)",
    ]

    try:
        await tg_app.bot.send_message(chat_id=int(OWNER_ID), text="\n".join(lines))
    except Exception as e:
        print("send_owner_report failed:", e)

# ============================================================
# ✅ OWNER: /forget <tg_id>
# ============================================================
async def forget_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return

    if not context.args:
        await update.message.reply_text("Формат: /forget <tg_id>\nПример: /forget 6624060143")
        return

    tg_id_str = context.args[0].strip()
    if not tg_id_str.isdigit():
        await update.message.reply_text("Нужен tg_id числом. Пример: /forget 6624060143")
        return

    tg_id = int(tg_id_str)

    if not DB_POOL:
        await update.message.reply_text("DB not ready")
        return

    async with DB_POOL.acquire() as conn:
        await conn.execute("DELETE FROM messages WHERE tg_id=$1", tg_id)
        await conn.execute("DELETE FROM lead_events WHERE tg_id=$1", tg_id)
        await conn.execute("DELETE FROM leads WHERE tg_id=$1", tg_id)
        await conn.execute("DELETE FROM users WHERE tg_id=$1", tg_id)

    try:
        ud = context.application.user_data.get(tg_id)
        if ud is not None:
            ud.clear()
    except Exception:
        pass

    await update.message.reply_text(f"✅ Готово. Пользователь {tg_id} полностью «забыт».")

# ============================================================
# ✅ Scripted Reels Site Flow
# ============================================================
async def _send_ref_images(bot, chat_id: int):
    for i, fname in enumerate(REF_IMAGES, start=1):
        if os.path.exists(fname):
            with open(fname, "rb") as f:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=InputFile(f, filename=fname),
                    caption=f"✅ Эскиз {i}/3 — {fname}"
                )
        else:
            await bot.send_message(chat_id=chat_id, text=f"⚠️ Не нашёл файл {fname} рядом с bot.py")


async def handle_site_flow(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Returns True if handled by scripted flow.
    """
    text = (update.message.text or "").strip()
    if not text:
        return False

    flow = context.user_data.get("site_flow") or {}
    step = flow.get("step", 0)

    # Step 0: waiting for service choice "3"
    if step == 0:
        if text == "3":
            flow["step"] = 1
            context.user_data["site_flow"] = flow
            reply = "Отлично ✅ Начнём с сайта.\nПодскажите, пожалуйста, название проекта/кофейни (как должно быть на сайте)?"
            await update.message.reply_text(reply)
            await db_log_message(int(update.effective_user.id), "out", reply)
            return True
        return False  # not in site flow

    # Step 1: name
    if step == 1:
        flow["name"] = text
        flow["step"] = 2
        context.user_data["site_flow"] = flow
        reply = "Приняла ✅\nУточните, пожалуйста, город и адрес (для блока «Расположение»)."
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 2: address
    if step == 2:
        flow["address"] = text
        flow["step"] = 3
        context.user_data["site_flow"] = flow
        reply = (
            "Отлично ✅\n"
            "Сайт нужен в каком формате:\n"
            "1) простой сайт-визитка (меню/контакты)\n"
            "2) сайт с заявками (форма/кнопки)\n"
            "3) сайт с онлайн-заказом (каталог + корзина)"
        )
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 3: site type
    if step == 3:
        if text not in {"1", "2", "3"}:
            reply = "Пожалуйста, ответьте цифрой: 1 / 2 / 3."
            await update.message.reply_text(reply)
            await db_log_message(int(update.effective_user.id), "out", reply)
            return True
        flow["site_type"] = text
        flow["step"] = 4
        context.user_data["site_flow"] = flow
        reply = "Поняла ✅\nФормат получения: самовывоз / доставка / оба?"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 4: fulfillment
    if step == 4:
        flow["fulfillment"] = text
        flow["step"] = 5
        context.user_data["site_flow"] = flow
        reply = "Приняла ✅\nОплата: картой / при получении / оба?"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 5: payment
    if step == 5:
        flow["payment"] = text
        flow["step"] = 6
        context.user_data["site_flow"] = flow
        reply = "Супер ✅\nСколько позиций в меню планируется на старте: до 10 / 10–25 / 25–50 / больше?"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 6: menu size
    if step == 6:
        flow["menu_size"] = text
        flow["step"] = 7
        context.user_data["site_flow"] = flow
        reply = "Отлично ✅\nКакие категории будут в каталоге? (перечислите через запятую)"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 7: categories
    if step == 7:
        flow["categories"] = text
        flow["step"] = 8
        context.user_data["site_flow"] = flow
        reply = "Приняла ✅\nДля кофе нужны варианты объёма (например 250/350/450 мл) — да/нет?"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 8: volumes yes/no
    if step == 8:
        flow["volumes"] = text
        flow["step"] = 9
        context.user_data["site_flow"] = flow
        reply = "Ок ✅\nНужны ли добавки (сироп/альт-молоко/extra shot) — да/нет?"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 9: addons yes/no
    if step == 9:
        flow["addons"] = text
        flow["step"] = 10
        context.user_data["site_flow"] = flow
        reply = "Приняла ✅\nВ какой валюте показывать цены: ₾ / $ / € ?"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 10: currency
    if step == 10:
        flow["currency"] = text
        flow["step"] = 11
        context.user_data["site_flow"] = flow
        reply = (
            "Отлично ✅\n"
            "Чтобы точно попасть в стиль — пришлите пример дизайна (ссылку), который Вам нравится.\n"
            "К примеру, можете зайти на https://dribbble.com/ и выбрать вариант по запросу:\n"
            "coffee to go / coffee shop / online ordering\n"
            "Пришлите ссылку сюда."
        )
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)
        return True

    # Step 11: waiting for reference link
    if step == 11:
        if not _looks_like_link(text):
            reply = "Пришлите, пожалуйста, ссылку на пример дизайна (например Dribbble)."
            await update.message.reply_text(reply)
            await db_log_message(int(update.effective_user.id), "out", reply)
            return True
        flow["ref_link"] = text
        flow["step"] = 12
        context.user_data["site_flow"] = flow
        reply = "Приняла ✅ Спасибо!\nСейчас подготовлю эскизы макета в выбранном стиле и пришлю на согласование ✅"
        await update.message.reply_text(reply)
        await db_log_message(int(update.effective_user.id), "out", reply)

        await _send_ref_images(context.bot, update.effective_chat.id)

        follow = "Подтвердите, пожалуйста: ОК — и я собираю финальную версию.\nЕсли нужно — напишите, что поменять (цвета/шрифты/порядок блоков)."
        await update.message.reply_text(follow)
        await db_log_message(int(update.effective_user.id), "out", follow)
        return True

    # Step 12: waiting OK/changes
    if step == 12:
        if _is_ok(text):
            flow["step"] = 13
            context.user_data["site_flow"] = flow
            msg1 = "Приняла ✅ Собираю финальную версию сайта по утверждённому эскизу.\nСкоро вернусь с ссылкой."
            await update.message.reply_text(msg1)
            await db_log_message(int(update.effective_user.id), "out", msg1)

            # emulate "typing" + publish
            msg2 = f"Готово ✅ Сайт опубликован.\nСсылка: {SITE_PUBLISH_URL}\n\nЧто делаем следующим шагом?\n1) добавить фото товаров\n2) усилить первый экран (оффер + CTA)\n3) подключить интеграцию (CRM/таблица), чтобы заказы уходили автоматически"
            await update.message.reply_text(msg2)
            await db_log_message(int(update.effective_user.id), "out", msg2)
            return True
        else:
            # if user sends changes, acknowledge and ask OK again
            msg = "Приняла ✅ Учту правки и обновлю эскиз. Подтвердите, пожалуйста: ОК — и я собираю финальную версию."
            await update.message.reply_text(msg)
            await db_log_message(int(update.effective_user.id), "out", msg)
            return True

    # Step 13: next step selection after publish
    if step == 13:
        if text == "3":
            flow["step"] = 14
            context.user_data["site_flow"] = flow
            msg = (
                "Приняла ✅ Тогда подключаю сайт к CRM как модуль интеграции, чтобы каждый заказ автоматически уходил в вашу систему.\n\n"
                "Куда отправлять заказы? (выберите вариант):\n"
                "1) Google Sheets\n"
                "2) Notion\n"
                "3) amoCRM / Bitrix24\n"
                "4) Webhook URL"
            )
            await update.message.reply_text(msg)
            await db_log_message(int(update.effective_user.id), "out", msg)
            return True
        else:
            # If user picks 1 or 2, accept and finish
            msg = "Приняла ✅ Сделаю этот шаг следующим. Хотите продолжить (1/2/3) или вернуться позже?"
            await update.message.reply_text(msg)
            await db_log_message(int(update.effective_user.id), "out", msg)
            return True

    # Step 14: CRM destination - finish
    if step == 14:
        msg = "Приняла ✅ Зафиксировала. Подключу и пришлю подтверждение после настройки."
        await update.message.reply_text(msg)
        await db_log_message(int(update.effective_user.id), "out", msg)
        return True

    return False

# ============================================================
# ✅ Telegram handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["introduced"] = True
    context.user_data["history"] = []
    context.user_data["site_flow"] = {"step": 0}  # reset reels flow each /start

    user = update.effective_user
    args = context.args or []

    if args and args[0].lower() in ("ig", "insta", "instagram"):
        await db_log_event(event="start", source="instagram", tg_id=int(user.id), meta={"from": "ig_deeplink"})
        name_form, niche_form = await db_get_latest_miniapp_profile(int(user.id))
        if niche_form:
            final_name = (name_form or user.first_name or "друг").strip()
            await update.message.reply_text(
                f"Спасибо, {final_name}! ✅\n"
                f"Зафиксировала: ниша — {niche_form}.\n\n"
                f"{POST_MINIAPP_TEXT}"
            )
        else:
            await update.message.reply_text(IG_WELCOME_TEXT)
        return

    await db_log_event(event="start", source="telegram", tg_id=int(user.id), meta={"from": "direct_start"})

    name_form, niche_form = await db_get_latest_miniapp_profile(int(user.id))
    if niche_form:
        final_name = (name_form or user.first_name or "друг").strip()
        await update.message.reply_text(
            f"Спасибо, {final_name}! ✅\n"
            f"Зафиксировала: ниша — {niche_form}.\n\n"
            f"{POST_MINIAPP_TEXT}"
        )
    else:
        await update.message.reply_text(WELCOME_TEXT)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return
    period = (context.args[0] if context.args else "day").lower()
    if period not in ("day", "week"):
        period = "day"
    await send_owner_report(period)


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

    # --- Scripted reel site flow (if user already filled miniapp and chose 3) ---
    handled = await handle_site_flow(update, context)
    if handled:
        return

    # first-ever message behavior
    if not context.user_data.get("introduced"):
        context.user_data["introduced"] = True
        context.user_data["history"] = []
        name_form, niche_form = await db_get_latest_miniapp_profile(int(user.id))
        if niche_form:
            final_name = (name_form or user.first_name or "друг").strip()
            msg = (
                f"Спасибо, {final_name}! ✅\n"
                f"Зафиксировала: ниша — {niche_form}.\n\n"
                f"{POST_MINIAPP_TEXT}"
            )
            await update.message.reply_text(msg)
            await db_log_message(int(user.id), "out", msg)
        else:
            await update.message.reply_text(WELCOME_TEXT)
            await db_log_message(int(user.id), "out", WELCOME_TEXT)
        return

    # ===== Gemini fallback =====
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except Exception:
        pass

    name_form, niche_form = await db_get_latest_miniapp_profile(int(user.id))
    niche_db = await db_get_user_niche(int(user.id))

    prefix = ""
    if niche_form:
        prefix += f"(Mini App уже заполнен: ДА. Имя из формы: {name_form or '-'}, Ниша из формы: {niche_form})\n"
    else:
        prefix += "(Mini App уже заполнен: НЕТ)\n"

    if niche_db:
        prefix += f"(Ниша/род деятельности пользователя: {niche_db})\n"

    history = context.user_data.get("history", [])
    history.append({"role": "user", "parts": [{"text": prefix + text}]})
    history = history[-(MAX_TURNS * 2):]

    try:
        answer = ask_gemini(history)
    except Exception as e:
        err = str(e).lower()
        if "429" in err or "quota" in err or "rate limit" in err:
            GLOBAL_LIMIT["blocked_date"] = str(datetime.now(timezone.utc).date())
            await update.message.reply_text("⚠️ Бесплатный лимит на сегодня исчерпан. Попробуйте завтра.")
            return
        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")
        return

    await update.message.reply_text(answer)
    await db_log_message(int(user.id), "out", answer)
    history.append({"role": "model", "parts": [{"text": answer}]})
    context.user_data["history"] = history[-(MAX_TURNS * 2):]

# ============================================================
# ✅ HTTP endpoints
# ============================================================
async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def version(request: web.Request) -> web.Response:
    return web.Response(text=f"build={BUILD_TAG}")


async def webhook_handler(request: web.Request) -> web.Response:
    global tg_app
    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return web.Response(text="ok")


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

    name = (form.get("name") or "").strip()
    niche = (form.get("niche") or "").strip()
    contact = (form.get("contact") or "").strip()

    if not tg_id or not DB_POOL or tg_app is None:
        return web.json_response({"ok": False, "error": "No tg_id or DB/Bot not ready"}, status=500)

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

    final_name = (name or first_name or "друг").strip()
    final_niche = (niche or "—").strip()

    msg = (
        f"Спасибо, {final_name}! ✅\n"
        f"Зафиксировала: ниша — {final_niche}.\n\n"
        f"{POST_MINIAPP_TEXT}"
    )

    try:
        await tg_app.bot.send_message(chat_id=int(tg_id), text=msg)
    except Exception as e:
        print("send_message to user failed:", e)

    return web.json_response({"ok": True, "leadId": lead_id})


async def tasks_daily_report(request: web.Request) -> web.Response:
    token = request.headers.get("X-Task-Token") or request.query.get("token")
    if not REPORT_TASK_TOKEN or token != REPORT_TASK_TOKEN:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    await send_owner_report("day")
    return web.json_response({"ok": True})

# ============================================================
# ✅ MAIN
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
    tg_app.add_handler(CommandHandler("forget", forget_cmd))
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
    web_app.router.add_get("/tasks/daily_report", tasks_daily_report)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    webhook_url = f"{BASE_URL}/webhook"
    await tg_app.bot.delete_webhook(drop_pending_updates=True)
    await tg_app.bot.set_webhook(url=webhook_url)

    print(f"✅ Bot started (WEBHOOK) on {webhook_url}", flush=True)
    print("✅ /version ready", flush=True)
    print("✅ /api/leads/miniapp ready", flush=True)
    print("✅ /tasks/daily_report ready", flush=True)

    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
