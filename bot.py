import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")
URL = os.environ.get("RENDER_EXTERNAL_URL")

MODEL = "gemini-2.0-flash"

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
            {"parts": [{"text": f"{SYSTEM_PROMPT}\n\nПользователь: {user_text}"}]}
        ],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800},
    }

    r = requests.post(endpoint, params=params, json=payload, timeout=20)

    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text}")

    data = r.json()

    # Иногда кандидатов нет (safety/blocked/прочее)
    candidates = data.get("candidates") or []
    if not candidates:
        raise RuntimeError(f"No candidates returned: {data}")

    content = (candidates[0].get("content") or {})
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
        "Интересно узнать, как это изменит ваш бизнес?"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    # Быстрый ответ, чтобы Telegram не получил timeout
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

        # Отправим владельцу полный текст ошибки, чтобы не гадать
        if OWNER_ID:
            try:
                await context.bot.send_message(chat_id=int(OWNER_ID), text=f"❌ Gemini error:\n{err}")
            except:
                pass

        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


def main():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not URL:
        raise RuntimeError("Missing RENDER_EXTERNAL_URL")
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

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
    main()        raise RuntimeError("Missing GOOGLE_API_KEY")

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
    main()
