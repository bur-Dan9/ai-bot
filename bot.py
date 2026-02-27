import os
import asyncio
import re
import requests
from aiohttp import web

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ===== ENV =====
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")

# ===== Gemini =====
MODEL = "gemini-2.5-flash"

# Важно: системный промпт НЕ должен заставлять представляться каждый раз
SYSTEM_PROMPT = (
    "Ты — Soffi, AI-ассистент агентства 'awm os'.\n"
    "Правила:\n"
    "1) НЕ представляйся заново в каждом ответе.\n"
    "2) Будь краткой и по делу.\n"
    "3) Запоминай имя пользователя, если он его сказал.\n"
    "4) Если пользователь спрашивает 'как меня зовут?' — отвечай именем, если оно уже было.\n"
    "5) Цель: помогать, мягко вести к обсуждению задач бизнеса и бюджета на подписку.\n"
)

WELCOME_TEXT = (
    "Привет! Я Soffi 🦾\n"
    "Я помогу понять, как ИИ может ускорить маркетинг и продажи.\n"
    "Для начала: чем занимаетесь и в каком городе/нише?"
)

MAX_TURNS = 12  # сколько последних обменов (user+assistant) хранить на пользователя


def _extract_name(text: str) -> str | None:
    """Простая попытка вытащить имя из фраз типа 'меня зовут Даниил'."""
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
    """contents: список сообщений формата Gemini: {role: 'user'|'model', parts:[{text:...}]}"""
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 800,
        },
    }

    r = requests.post(endpoint, params={"key": GOOGLE_API_KEY}, json=payload, timeout=20)

    if r.status_code == 429:
        raise RuntimeError("429: rate limit / quota exceeded")
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
    # Приветствие один раз + очистка памяти на /start
    context.user_data["introduced"] = True
    context.user_data["history"] = []
    await update.message.reply_text(WELCOME_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()
    if not text:
        return

    # Если пользователь ещё не запускал /start — поздороваемся один раз
    if not context.user_data.get("introduced"):
        context.user_data["introduced"] = True
        context.user_data["history"] = []
        await update.message.reply_text(WELCOME_TEXT)

    # Вместо отдельного сообщения "Думаю..." покажем "печатает..."
    try:
        await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
    except:
        pass

    # Поймаем имя
    name = _extract_name(text)
    if name:
        context.user_data["user_name"] = name

    # История диалога (память)
    history = context.user_data.get("history", [])

    # Добавляем сообщение пользователя
    history.append({"role": "user", "parts": [{"text": text}]})

    # Подмешаем имя (если есть) как дополнительный контекст в последний user-message
    user_name = context.user_data.get("user_name")
    if user_name and len(history) >= 1 and history[-1]["role"] == "user":
        history[-1]["parts"][0]["text"] = f"(Имя пользователя: {user_name})\n{text}"

    # Обрезаем историю
    history = history[-(MAX_TURNS * 2):]

    try:
        answer = ask_gemini(history)
        await update.message.reply_text(answer)

        # Сохраняем ответ в историю
        history.append({"role": "model", "parts": [{"text": answer}]})
        history = history[-(MAX_TURNS * 2):]
        context.user_data["history"] = history

        # Репорт владельцу
        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = f"📈 Новый лид!\n👤 {user.first_name} (@{user.username})\n💬 {text}"
            await context.bot.send_message(chat_id=int(OWNER_ID), text=report)

    except Exception as e:
        err = str(e)
        print("Gemini error:", err)

        if OWNER_ID:
            try:
                await context.bot.send_message(chat_id=int(OWNER_ID), text=f"❌ Gemini error:\n{err}")
            except:
                pass

        if "429" in err:
            await update.message.reply_text("⚠️ Слишком много запросов/лимит. Попробуйте через минуту.")
        else:
            await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


# ===== /health for Render + UptimeRobot =====
async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def main_async():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    # Telegram polling
    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)

    # HTTP server for Render
    port = int(os.environ.get("PORT", "10000"))
    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print("✅ Bot started (polling) + /health ok")
    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
