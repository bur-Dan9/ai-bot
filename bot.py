import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ENV
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")
URL = os.environ.get("RENDER_EXTERNAL_URL")

MODEL = "gemini-1.5-flash"

SYSTEM_PROMPT = """
Ты — Soffi, лицо AI-агентства "awm os".
Твой стиль: баланс строгости и вдохновения.
Цель: прогреть локальный бизнес, узнать их бюджет на подписку и пообещать уведомление о запуске.
"""

def ask_gemini(user_text):
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={GOOGLE_API_KEY}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT + "\n\nСообщение пользователя: " + user_text}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 800
        }
    }

    response = requests.post(endpoint, json=payload, timeout=30)

    if response.status_code != 200:
        raise Exception(response.text)

    data = response.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я Soffi 🦾\n"
        "Мы создаем ИИ-организм для автоматизации маркетинга.\n"
        "Интересно узнать, как это изменит ваш бизнес?"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    try:
        answer = ask_gemini(update.message.text)
        await update.message.reply_text(answer)

        # Отчет владельцу
        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = (
                f"📈 Новый лид!\n"
                f"👤 {user.first_name} (@{user.username})\n"
                f"💬 {update.message.text}"
            )
            await context.bot.send_message(chat_id=OWNER_ID, text=report)

    except Exception as e:
        await update.message.reply_text("⚠️ Ошибка Gemini API")
        print("Gemini error:", e)


def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get("PORT", 10000))

application.run_webhook(
    listen="0.0.0.0",
    port=port,
    url_path=TOKEN,
    webhook_url=f"{URL}/{TOKEN}"
)


if __name__ == "__main__":
    main()
