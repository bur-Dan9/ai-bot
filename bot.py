import os
import asyncio
import re
import requests
import json
import hmac
import hashlib
from datetime import datetime, timezone
from aiohttp import web

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===== ENV =====
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")

# твой Render URL (можно оставить так)
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://ai-bot-a3aj.onrender.com").rstrip("/")

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

# ===== MEMORY =====
MAX_TURNS = 12  # хранить последние 12 обменов (user+assistant) на пользователя

# ===== GLOBAL LIMIT (2-layer) =====
MAX_REQUESTS_PER_DAY = 200
GLOBAL_LIMIT = {
    "date": None,          # "YYYY-MM-DD"
    "count": 0,
    "blocked_date": None,  # если словили квоту/429 — блокируем до конца дня (UTC)
}

# глобальный объект приложения (нужен webhook handler)
tg_app: Application | None = None


def _extract_name(text: str) -> str | None:
    """Очень простая попытка извлечь имя из фраз."""
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
    """
    contents: список сообщений формата Gemini:
    {"role": "user"|"model", "parts":[{"text":"..."}]}
    """
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # приветствие 1 раз + сброс памяти по /start
    context.user_data["introduced"] = True
    context.user_data["history"] = []
    await update.message.reply_text(WELCOME_TEXT)


def _check_and_update_global_limit() -> tuple[bool, str | None]:
    """
    Возвращает (allowed, reason)
    reason: текст для пользователя если запрещено
    """
    today = datetime.now(timezone.utc).date()
    today_s = str(today)

    # если уже заблокировали на сегодня из-за квоты — закрыто
    if GLOBAL_LIMIT.get("blocked_date") == today_s:
        return False, "⚠️ Лимит на сегодня исчерпан. Попробуйте завтра."

    # новый день — сброс
    if GLOBAL_LIMIT.get("date") != today_s:
        GLOBAL_LIMIT["date"] = today_s
        GLOBAL_LIMIT["count"] = 0
        GLOBAL_LIMIT["blocked_date"] = None

    # достигли лимита
    if GLOBAL_LIMIT["count"] >= MAX_REQUESTS_PER_DAY:
        GLOBAL_LIMIT["blocked_date"] = today_s
        return False, "⚠️ Лимит на сегодня исчерпан. Попробуйте завтра."

    # считаем попытку заранее (защита от спама)
    GLOBAL_LIMIT["count"] += 1
    return True, None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    # Глобальный лимит (2 слоя)
    allowed, reason = _check_and_update_global_limit()
    if not allowed:
        await update.message.reply_text(reason)
        return

    # приветствие только 1 раз (если пользователь не нажимал /start)
    if not context.user_data.get("introduced"):
        context.user_data["introduced"] = True
        context.user_data["history"] = []
        await update.message.reply_text(WELCOME_TEXT)

    # typing...
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except:
        pass

    # имя пользователя
    name = _extract_name(text)
    if name:
        context.user_data["user_name"] = name

    # память (история)
    history = context.user_data.get("history", [])

    # сообщение пользователя
    user_name = context.user_data.get("user_name")
    if user_name:
        user_text_for_model = f"(Имя пользователя: {user_name})\n{text}"
    else:
        user_text_for_model = text

    history.append({"role": "user", "parts": [{"text": user_text_for_model}]})
    history = history[-(MAX_TURNS * 2):]

    try:
        answer = ask_gemini(history)
        await update.message.reply_text(answer)

        # сохраняем ответ в историю
        history.append({"role": "model", "parts": [{"text": answer}]})
        history = history[-(MAX_TURNS * 2):]
        context.user_data["history"] = history

        # репорт владельцу о лидах (не владельцу)
        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = (
                f"📈 Новый лид!\n"
                f"👤 {user.first_name} (@{user.username})\n"
                f"💬 {text}"
            )
            await context.bot.send_message(chat_id=int(OWNER_ID), text=report)

    except Exception as e:
        err = str(e)
        low = err.lower()
        print("Gemini error:", err)

        # 2-я защита: словили квоту/429 => блокируем до конца дня (UTC)
        if "429" in err or "resource_exhausted" in low or "quota" in low or "rate limit" in low:
            GLOBAL_LIMIT["blocked_date"] = str(datetime.now(timezone.utc).date())
            await update.message.reply_text("⚠️ Бесплатный лимит на сегодня исчерпан. Попробуйте завтра.")
            return

        # отправим владельцу точную ошибку
        if OWNER_ID:
            try:
                await context.bot.send_message(chat_id=int(OWNER_ID), text=f"❌ Gemini error:\n{err}")
            except:
                pass

        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


# ===== /health for Render + UptimeRobot =====
async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def webhook_handler(request: web.Request) -> web.Response:
    """
    Telegram будет слать сюда апдейты. Мы прокидываем их в python-telegram-bot.
    """
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


async def main_async():
    global tg_app

    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    # 1) Telegram Application (без polling)
    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await tg_app.initialize()
    await tg_app.start()

    # 2) HTTP server for Render (webhook + health)
    port = int(os.environ.get("PORT", "10000"))
    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)
    web_app.router.add_post("/webhook", webhook_handler)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    # 3) Устанавливаем webhook на Render URL
    webhook_url = f"{BASE_URL}/webhook"
    await tg_app.bot.delete_webhook(drop_pending_updates=True)
    ok = await tg_app.bot.set_webhook(url=webhook_url)

    print(f"✅ Bot started (webhook) on {webhook_url}, set_webhook={ok}")
    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
