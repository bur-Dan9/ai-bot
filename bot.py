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

# ============================================================
# ✅ BUILD TAG (check deploy via /version)
# ============================================================
BUILD_TAG = "MINIAPP_V21_REELS_AUTOPILOT_PDF_300_200"
print(f"### BUILD: {BUILD_TAG} ###", flush=True)

# ============================================================
# ✅ ENV (Render -> Environment)
# ============================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
DATABASE_URL = os.environ.get("DATABASE_URL")

BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ai-bot-a3aj.onrender.com").rstrip("/")

# PDF file must be committed next to bot.py in the repo (or set DEMO_PDF_PATH env)
DEMO_PDF_PATH = os.environ.get("DEMO_PDF_PATH", "awmos_report_premium_24h_200usd_boosted.pdf")

# ============================================================
# ✅ CORS
# ============================================================
ALLOWED_ORIGINS = {
    "https://min-iapp.vercel.app",
    "https://awm-os.vercel.app",
}

# ============================================================
# ✅ LIMITS
# ============================================================
MAX_REQUESTS_PER_DAY = 200
GLOBAL_LIMIT = {"date": None, "count": 0, "blocked_date": None}

tg_app: Application | None = None
DB_POOL: asyncpg.Pool | None = None

WELCOME_TEXT = (
    "Здравствуйте! Я Soffi 🦾\n"
    "Я помогу Вам подключиться к AWM OS — AI-системе маркетинга в Telegram, которая работает 24/7.\n\n"
    "Откройте Mini App (AWM OS) — там Вы сможете оставить заявку\n"
    "⬇️"
)

IG_WELCOME_TEXT = (
    "Здравствуйте! Я Soffi 🦾\n"
    "Вижу, Вы пришли из Instagram.\n\n"
    "Откройте Mini App (AWM OS) — там Вы сможете оставить заявку\n"
    "⬇️"
)

POST_MINIAPP_TEXT = (
    "Отлично! ✅ Я зафиксировала Вашу нишу.\n\n"
    "Чтобы предложить самое подходящее решение, выберите, что Вам ближе (можно цифрой):\n"
    "1) AI-Маркетинг Автопилот — ведение Instagram под ключ + реклама\n"
    "2) Content & Ads Turbo — только реклама/трафик/креативы (без ведения Instagram)\n"
    "3) Разработка экосистемы — сайт + Telegram Mini App + интеграции под ключ\n"
    "4) Глубокий AI-аудит — разбор воронки и точек роста\n\n"
    "Если не уверены — напишите коротко цель, и я подберу сама."
)

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


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _is_yes(text: str) -> bool:
    t = _norm(text)
    return t in ("да", "ага", "ок", "окей", "yes", "y", "угу", "запускай", "запускайте")


# ============================================================
# ✅ DB helpers
# ============================================================
async def db_get_latest_miniapp_profile(tg_id: int) -> tuple[str | None, str | None]:
    """
    last miniapp lead (name,niche). Requires leads table existing in your DB.
    """
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


# ============================================================
# ✅ Send PDF
# ============================================================
async def send_demo_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not os.path.exists(DEMO_PDF_PATH):
            await update.message.reply_text(
                "⚠️ PDF не найден. Добавьте файл awmos_report_premium_24h_200usd_boosted.pdf рядом с bot.py в репозиторий "
                "или задайте переменную окружения DEMO_PDF_PATH."
            )
            return

        with open(DEMO_PDF_PATH, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename="Report_Batumi_24h.pdf",
                caption="PDF-отчёт • 24h"
            )
    except Exception as e:
        print("send_demo_pdf failed:", e)
        await update.message.reply_text("⚠️ Не удалось отправить PDF. Проверьте файл и деплой.")


# ============================================================
# ✅ Reels script state machine (Autopilot flow)
# ============================================================
async def reels_autopilot_flow(update: Update, context: ContextTypes.DEFAULT_TYPE, name: str, niche: str, text: str) -> bool:
    """
    Scripted flow for Reels. Works only if niche exists (Mini App submitted).
    Returns True if handled.
    """
    if not niche:
        return False

    state = context.user_data.get("reels_state", None)
    t = text.strip()

    # waiting service choice
    if state is None:
        if _norm(t) in ("1", "автопилот", "ведение", "ведение инстаграм", "instagram", "ai маркетинг"):
            context.user_data["reels_state"] = "confirm_budget_goal"
            await update.message.reply_text(
                f"Отлично, {name} ✅\n"
                "Подтвердите, пожалуйста: бюджет $300/мес, из них $200 — на рекламу?\n"
                "И какая главная цель: больше клиентов, узнаваемость или продажи?"
            )
            return True
        return False

    if state == "confirm_budget_goal":
        context.user_data["budget_goal"] = t
        context.user_data["reels_state"] = "channel_product"
        await update.message.reply_text(
            "Отлично ✅\n"
            "Уточню 2 момента:\n"
            "1) Куда ведём людей: в директ или по ссылке?\n"
            "2) Что продвигаем первым: кофе с собой / завтраки / десерты?"
        )
        return True

    if state == "channel_product":
        context.user_data["channel_product"] = t
        context.user_data["reels_state"] = "hit"
        await update.message.reply_text("Принято ✅ Есть “хит” (фирменный напиток/позиция), который пушим в рекламе?")
        return True

    if state == "hit":
        context.user_data["hit"] = t
        context.user_data["reels_state"] = "avg_check"
        await update.message.reply_text("Супер ✅ Средний чек примерно какой?")
        return True

    if state == "avg_check":
        context.user_data["avg_check"] = t
        context.user_data["reels_state"] = "audience"
        await update.message.reply_text("Поняла ✅ Аудитория: локальные / туристы / 50 на 50?")
        return True

    if state == "audience":
        context.user_data["audience"] = t
        context.user_data["reels_state"] = "confirm_launch"
        await update.message.reply_text(
            "Отлично ✅ Тогда стартовый план на 24 часа:\n"
            "— 4 креатива (хит/кофе рядом/утро/маршрут)\n"
            "— 2 аудитории (локальные/туристы)\n"
            "— цель: сообщения в директ\n"
            "— оптимизация 24/7 на данных\n"
            "Отчёт пришлю в PDF сюда в чат.\n\n"
            "Запускать?"
        )
        return True

    if state == "confirm_launch":
        if _is_yes(t):
            context.user_data["reels_state"] = "post_launch_ok"
            await update.message.reply_text("Запускаю ✅\nSoffi печатает…")
            await asyncio.sleep(1.1)
            await update.message.reply_text(
                "Готово ✅ Кампании запущены, креативы загружены, аудитории разделены.\n"
                "Первый PDF-отчёт пришлю сюда. Ок?"
            )
            return True
        await update.message.reply_text("Ок ✅ Напишите «Да», когда будем запускать.")
        return True

    if state == "post_launch_ok":
        if _is_yes(t):
            context.user_data["reels_state"] = "done"
            await send_demo_pdf(update, context)
            await update.message.reply_text(
                "Коротко по итогам ✅\n"
                "— выключила слабое, усилила лучшее, добавила новый тест.\n\n"
                "Продолжаем? Что важнее: больше обращений или более «горячие» (выше чек)?"
            )
            return True
        await update.message.reply_text("Ок ✅ Напишите «Ок», и я отправлю PDF-отчёт.")
        return True

    return False


# ============================================================
# ✅ Telegram handlers
# ============================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["history"] = []
    context.user_data["reels_state"] = None

    user = update.effective_user
    args = context.args or []

    # if miniapp already submitted -> show services; else welcome
    name_form, niche_form = await db_get_latest_miniapp_profile(int(user.id))
    if niche_form:
        final_name = (name_form or user.first_name or "друг").strip()
        await update.message.reply_text(
            f"Спасибо, {final_name}! ✅\n"
            f"Зафиксировала: ниша — {niche_form}.\n\n"
            f"{POST_MINIAPP_TEXT}"
        )
        return

    # instagram start
    if args and args[0].lower() in ("ig", "insta", "instagram"):
        await update.message.reply_text(IG_WELCOME_TEXT)
        return

    await update.message.reply_text(WELCOME_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    allowed, reason = _check_and_update_global_limit()
    if not allowed:
        await update.message.reply_text(reason)
        return

    # load miniapp profile
    name_form, niche_form = await db_get_latest_miniapp_profile(int(user.id))
    final_name = (name_form or user.first_name or "друг").strip()
    final_niche = (niche_form or "").strip()

    await db_log_message(int(user.id), "in", text)

    # scripted reels flow
    handled = await reels_autopilot_flow(update, context, final_name, final_niche, text)
    if handled:
        return

    # If user has miniapp but didn't choose yet -> repeat service list once
    if final_niche and context.user_data.get("reels_state") is None and _norm(text) not in ("1", "2", "3", "4"):
        await update.message.reply_text(POST_MINIAPP_TEXT)
        return

    # fallback minimal response (no Gemini here — to keep behavior stable for reels)
    await update.message.reply_text("Приняла ✅ Напишите, пожалуйста, цифрой: 1 / 2 / 3 / 4.")


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
    """
    Receives initData + form{name,niche,contact} from Mini App.
    Stores into your existing DB schema (users/leads).
    Sends message with 4 services list to user.
    """
    if not DB_POOL or tg_app is None:
        return web.json_response({"ok": False, "error": "DB/Bot not ready"}, status=500)

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

    tg_user = parsed.get("user") or {}
    tg_id = tg_user.get("id")
    first_name = tg_user.get("first_name") or ""
    username = tg_user.get("username") or ""

    name = (form.get("name") or "").strip()
    niche = (form.get("niche") or "").strip()
    contact = (form.get("contact") or "").strip()

    if not tg_id:
        return web.json_response({"ok": False, "error": "No tg_id"}, status=400)

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

        await conn.fetchval("""
            INSERT INTO leads (tg_id, source, name_from_form, niche_from_form, contact_from_form, payload)
            VALUES ($1, 'miniapp', NULLIF($2,''), NULLIF($3,''), NULLIF($4,''), $5)
            RETURNING id
        """, int(tg_id), name, niche, contact, json.dumps(form))

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

    return web.json_response({"ok": True})


# ============================================================
# ✅ MAIN
# ============================================================
async def main_async():
    global tg_app, DB_POOL

    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not DATABASE_URL:
        raise RuntimeError("Missing DATABASE_URL")

    DB_POOL = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    print("✅ DB pool ready", flush=True)

    # optional messages table
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

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    webhook_url = f"{BASE_URL}/webhook"
    await tg_app.bot.delete_webhook(drop_pending_updates=True)
    await tg_app.bot.set_webhook(url=webhook_url)

    print(f"✅ Bot started (WEBHOOK) on {webhook_url}", flush=True)
    print(f"✅ DEMO_PDF_PATH={DEMO_PDF_PATH}", flush=True)

    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
