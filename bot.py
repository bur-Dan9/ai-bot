import os
import asyncio
import requests
from aiohttp import web

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")

MODEL = "gemini-2.0-flash"

SYSTEM_PROMPT = (
    "Ты — Soffi, лицо AI-агентства 'awm os'.\n"
    "Твой стиль: баланс строгости и вдохновения.\n"
    "Цель: прогреть локальный бизнес, узнать их бюджет на подписку.\n"
)

def ask_gemini(user_text: str) -> str:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"

    r = requests.post(
        endpoint,
        params={"key": GOOGLE_API_KEY},
        json={
            "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nПользователь: {user_text}"}]}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800},
        },
        timeout=20,
    )

    if r.status_code != 200:
        raise RuntimeError(r.text)

    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я Soffi 🦾\nНапишите, чем занимается ваш бизнес."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    await update.message.reply_text("⌛️ Думаю…")

    try:
        answer = ask_gemini(text)
        await update.message.reply_text(answer)

        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = f"📈 Новый лид!\n👤 {user.first_name} (@{user.username})\n💬 {text}"
            await context.bot.send_message(chat_id=int(OWNER_ID), text=report)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка. Попробуйте позже.")


# ---------- HTTP сервер для Render ----------

async def health(request):
    return web.Response(text="ok")


async def main_async():

    # Telegram bot (polling)
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    # HTTP сервер
    port = int(os.environ.get("PORT", "10000"))

    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print("Bot started")

    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
