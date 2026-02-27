import os
import asyncio
import requests
from aiohttp import web

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")

MODEL = "gemini-2.5-flash"

SYSTEM_PROMPT = (
    "Ты — Soffi, лицо AI-агентства 'awm os'.\n"
    "Твой стиль: баланс строгости и вдохновения.\n"
    "Цель: прогреть локальный бизнес, узнать их бюджет на подписку и пообещать уведомление о запуске.\n"
    "В проекте более 10 ИИ-ассистентов, ты — единая точка входа.\n"
)

def ask_gemini(user_text: str) -> str:
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY env var")

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
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")

    data = r.json()
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates returned: {data}")

    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    if not parts:
        raise RuntimeError(f"No parts returned: {data}")

    text = parts[0].get("text")
    if not text:
        raise RuntimeError(f"No text returned: {data}")

    return text


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я Soffi 🦾\n"
        "Мы создаем ИИ-организм для автоматизации маркетинга.\n"
        "Напишите, чем занимается ваш бизнес — подскажу, где можно ускорить."
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
        err = str(e)
        print("Gemini error:", err)

        if OWNER_ID:
            try:
                await context.bot.send_message(chat_id=int(OWNER_ID), text=f"❌ Gemini error:\n{err}")
            except:
                pass

        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def main_async():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    # Telegram bot (polling)
    tg_app = Application.builder().token(TOKEN).build()
    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    await tg_app.initialize()
    await tg_app.start()
    await tg_app.updater.start_polling(drop_pending_updates=True)

    # HTTP server for Render (/health)
    port = int(os.environ.get("PORT", "10000"))
    web_app = web.Application()
    web_app.router.add_get("/", health)
    web_app.router.add_get("/health", health)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print("✅ Bot + health started")
    await asyncio.Event().wait()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
