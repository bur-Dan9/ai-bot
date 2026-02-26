import os
import asyncio
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Логирование для Render
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройки
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER_ID = os.environ.get('OWNER_ID')
URL = os.environ.get('RENDER_EXTERNAL_URL')

# Gemini
genai.configure(api_key=GOOGLE_API_KEY)
MODEL_ID = "gemini-1.5-flash"
SYSTEM_PROMPT = """
Ты — Soffi, лицо AI-агентства "awm os".
Твой стиль: баланс строгости и вдохновения.
Цель: прогреть локальный бизнес, узнать их бюджет на подписку и пообещать уведомление о запуске.
В проекте более 10 ИИ-ассистентов, ты — единая точка входа.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я Soffi, лицо awm os. 🦾\n"
        "Мы создаем ИИ-организм для полной автоматизации вашего маркетинга. "
        "Интересно узнать, как это изменит ваш бизнес?"
    )

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) == str(OWNER_ID):
        await update.message.reply_text("✅ Связь с владельцем установлена!")
    else:
        await update.message.reply_text("Доступ только для администрации.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_message = update.message.text
    try:
        model = genai.GenerativeModel(model_name=MODEL_ID, system_instruction=SYSTEM_PROMPT)
        response = model.generate_content(user_message)
        ai_reply = response.text
        await update.message.reply_text(ai_reply)
        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = f"📈 **Новый лид!**\n👤: {user.first_name} (@{user.username})\n💬: {user_message}"
            await context.bot.send_message(chat_id=OWNER_ID, text=report)
    except Exception as e:
        logger.error(f"Error in handle_message: {str(e)}")
        await update.message.reply_text("Извините, произошла ошибка. Попробуйте позже.")

async def main():
    # Создаем приложение для бота
    application = Application.builder().token(TOKEN).build()

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Получаем порт из переменных окружения или по умолчанию 8443
    port = int(os.environ.get('PORT', 8443))

    # Запуск вебхука
    await application.run_webhook(
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
