import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")
URL = os.environ.get("RENDER_EXTERNAL_URL")

MODEL = "gemini-1.5-flash"

SYSTEM_PROMPT = (
    "Ты — Soffi, лицо AI-агентства 'awm os'.\n"
    "Твой стиль: баланс строгости и вдохновения.\n"
    "Цель: прогреть локальный бизнес, узнать их бюджет на подписку и пообещать уведомление о запуске.\n"
    "В проекте более 10 ИИ-ассистентов, ты — единая точка входа.\n"
)

def ask_gemini(user_text: str) -> str:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    params = {"key": GOOGLE_API_KEY}

    payload = {
        "contents": [
            {"parts": [{"text": f"{SYSTEM_PROMPT}\n\nСообщение пользователя: {user_text}"}]}
        ],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800},
    }

    r = requests.post(endpoint, params=params, json=payload, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"Gemini API error {r.status_code}: {r.text}")

    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я Soffi 🦾\n"
        "Мы создаем ИИ-организм для автоматизации маркетинга.\n"
        "Интересно узнать, как это изменит ваш бизнес?"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    try:
        answer = ask_gemini(text)
        await update.message.reply_text(answer)

        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = f"📈 Новый лид!\n👤 {user.first_name} (@{user.username})\n💬 {text}"
            await context.bot.send_message(chat_id=int(OWNER_ID), text=report)

    except Exception as e:
        print("Error:", e)
        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")

def main():
    if not TOKEN or not URL:
        raise RuntimeError("Missing TELEGRAM_TOKEN or RENDER_EXTERNAL_URL env vars")

    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get("PORT", "10000"))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{URL}/{TOKEN}",
    )

if __name__ == "__main__":
    main()    await application.run_webhook(
        listen="0.0.0.0",  # Слушаем все адреса
        port=port,  # Порт, на котором будет работать сервер
        url_path=TOKEN,  # Путь для вебхука
        webhook_url=f"{URL}/{TOKEN}",  # Полный URL для вебхука
        close_loop=False  # Останавливать цикл не нужно
    )

if __name__ == '__main__':
    try:
        asyncio.run(main())  # Запуск основной асинхронной функции
    except Exception as e:
        logger.error(f"Ошибка при запуске: {e}")
