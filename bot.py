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

print("### SUPABASE BUILD ACTIVE ###", flush=True)

# ===== ENV =====
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")
DATABASE_URL = os.environ.get("DATABASE_URL")

BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ai-bot-a3aj.onrender.com").rstrip("/")
ALLOWED_ORIGINS = {"https://min-iapp.vercel.app"}

# ===== GEMINI =====
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

MAX_TURNS = 12

MAX_REQUESTS_PER_DAY = 200
GLOBAL_LIMIT = {"date": None, "count": 0, "blocked_date": None}

tg_app: Application | None = None
DB_POOL: asyncpg.Pool | None = None


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
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["introduced"] = True
    context.user_data["history"] = []
    await update.message.reply_text(WELCOME_TEXT)


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not OWNER_ID or str(update.effective_user.id) != str(OWNER_ID):
        return

    period = (context.args[0] if context.args else "day").lower()
    interval = "1 day" if period == "day" else "7 days"

    if not DB_POOL:
        await update.message.reply_text("DB not ready")
        return

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

    if not context.user_data.get("introduced"):
        context.user_data["introduced"] = True
        context.user_data["history"] = []
        await update.message.reply_text(WELCOME_TEXT)

    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except:
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

        history.append({"role": "model", "parts": [{"text": answer}]})
        history = history[-(MAX_TURNS * 2):]
        context.user_data["history"] = history

        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report_msg = f"📈 Сообщение от лида!\n👤 {user.first_name} (@{user.username})\n💬 {text}"
            await context.bot.send_message(chat_id=int(OWNER_ID), text=report_msg)

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
            except:
                pass

        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def webhook_handler(request: web.Request) -> web.Response:
    global tg_app
    try:
        data = await request.json()
    except:
        return web.Response(status=400, text="bad json")

    if tg_app is None:
        return web.Response(status=503, text="bot not ready")

    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)
    return web.Response(text="ok")


async def api_leads_miniapp(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except:
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

    if not tg_id:
        return web.json_response({"ok": False, "error": "No tg_id"}, status=400)

    name = (form.get("name") or "").strip()
    niche = (form.get("niche") or "").strip()
    contact = (form.get("contact") or "").strip()

    if not DB_POOL:
        return web.json_response({"ok": False, "error": "DB not ready"}, status=500)

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

    greet_name = first_name or name or "друг"
    niche_txt = niche or "вашу нишу"
    text_user = (
        f"Привет, {greet_name}! 👋\n"
        f"Спасибо, я записала {niche_txt}.\n"
        f"Можешь в 1 фразе описать задачу — и я подскажу, чем помочь."
    )
    try:
        await tg_app.bot.send_message(chat_id=int(tg_id), text=text_user)
    except Exception as e:
        print("send_message to user failed:", e)

    if OWNER_ID:
        owner_text = (
            f"📩 Новый лид (Mini App) #{lead_id}\n"
            f"👤 {first_name} (@{username}) | id={tg_id}\n"
            f"🧩 Ниша: {niche or '-'}\n"
            f"☎️ Контакт: {contact or '-'}\n"
            f"📝 Имя из формы: {name or '-'}"
        )
        try:
            await tg_app.bot.send_message(chat_id=int(OWNER_ID), text=owner_text)
        except Exception as e:
            print("send_message to owner failed:", e)

    return web.json_response({"ok": True, "leadId": lead_id})


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

    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(CommandHandler("report", report))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await tg_app.initialize()
    await tg_app.start()

    port = int(os.environ.get("PORT", "10000"))
    web_app = web.Application(middlewares=[cors_middleware])

    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)

    web_app.router.add_post("/webhook", webhook_handler)
    web_app.router.add_post("/api/leads/miniapp", api_leads_miniapp)
    web_app.router.add_options("/api/leads/miniapp", api_leads_miniapp)

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
    print("✅ API ready: POST /api/leads/miniapp", flush=True)
    print("✅ Reports: /report day | /report week", flush=True)

    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
