import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
OWNER_ID = os.environ.get("OWNER_ID")

MODEL = "gemini-2.0-flash"

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

    payload = {
        "contents": [{"parts": [{"text": f"{SYSTEM_PROMPT}\n\nПользователь: {user_text}"}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 800},
    }

    r = requests.post(
        endpoint,
        params={"key": GOOGLE_API_KEY},
        json=payload,
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
        "Напишите, чем занимаетесь — подскажу, где можно ускорить маркетинг."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    await update.message.reply_text("⌛️ Думаю…")

    try:
        answer = ask_gemini(text)
        await update.message.reply_text(answer)

        # лид-репорт владельцу
        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = (
                f"📈 Новый лид!\n"
                f"👤 {user.first_name} (@{user.username})\n"
                f"💬 {text}"
            )
            await context.bot.send_message(chat_id=int(OWNER_ID), text=report)

    except Exception as e:
        err = str(e)
        print("Gemini error:", err)

        # отправим владельцу точную ошибку
        if OWNER_ID:
            try:
                await context.bot.send_message(chat_id=int(OWNER_ID), text=f"❌ Gemini error:\n{err}")
            except:
                pass

        await update.message.reply_text("⚠️ Ошибка. Попробуйте ещё раз через минуту.")


def main():
    if not TOKEN:
        raise RuntimeError("Missing TELEGRAM_TOKEN")
    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # polling — самый стабильный вариант на Render Free
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
