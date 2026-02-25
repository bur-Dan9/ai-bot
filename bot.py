import os
import asyncio
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Настройки окружения
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER_ID = os.environ.get('OWNER_ID') 
URL = os.environ.get('RENDER_EXTERNAL_URL')

# 2. Настройка Soffi через новый клиент Google GenAI
client = genai.Client(api_key=GOOGLE_API_KEY)
MODEL_ID = "gemini-2.0-flash" # Используем самую актуальную модель

SYSTEM_PROMPT = """
Ты — Soffi, экспертный ассистент awm os. Твоя цель: прогреть локальный бизнес, 
узнать их бюджет на подписку и обещать уведомить о запуске. 
Стиль: строгий, но вдохновляющий.
"""

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я Soffi, лицо awm os. 🦾\n"
        "Мы создаем ИИ-организм для полной автоматизации вашего маркетинга. "
        "Интересно узнать, как это изменит ваш бизнес?"
    )

# Исправленная команда /check (только латиница!)
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) == str(OWNER_ID):
        await update.message.reply_text("✅ Связь с владельцем установлена! Отчеты будут приходить сюда.")
    else:
        await update.message.reply_text("Доступ ограничен.")

# Обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    try:
        # Новый способ генерации контента
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=text,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
        )
        
        await update.message.reply_text(response.text)

        # Отправка отчета владельцу
        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = f"📈 **Новый лид!**\n👤: {user.first_name} (@{user.username})\n💬: {text}"
            await context.bot.send_message(chat_id=OWNER_ID, text=report)

    except Exception as e:
        print(f"Ошибка: {e}")
        await update.message.reply_text("Я провожу техническое обновление систем. Попробуйте через минуту.")

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check)) # Команда изменена на /check
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get('PORT', 8443))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{URL}/{TOKEN}"
    )

if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        if "no current event loop" in str(e):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            main()
        else:
            raise e
if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        if "no current event loop" in str(e):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            main()
        else:
            raise e
