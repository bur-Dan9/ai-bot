import os
import asyncio
import openai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Загрузка настроек из переменных окружения Render
TOKEN = os.environ.get('TELEGRAM_TOKEN')
OPENAI_KEY = os.environ.get('OPENAI_API_KEY')
URL = os.environ.get('RENDER_EXTERNAL_URL')

# Инициализация клиента OpenAI
client = openai.AsyncOpenAI(api_key=OPENAI_KEY)

# Функция для команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Я твой AI-ассистент. Просто напиши мне что-нибудь.')

# Функция для обработки текстовых сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Отправляем запрос в OpenAI
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": update.message.text}]
        )
        # Отвечаем пользователю
        await update.message.reply_text(response.choices[0].message.content)
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка в OpenAI: {e}")

def main():
    # Создаем приложение бота
    application = Application.builder().token(TOKEN).build()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Настройка Webhook для работы на Render
    # Render автоматически передает PORT, на котором должен висеть бот
    port = int(os.environ.get('PORT', 8443))
    
    print(f"Запуск бота на порту {port} через Webhook...")
    
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{URL}/{TOKEN}"
    )

# 2. Блок защиты от ошибок "RuntimeError: There is no current event loop"
if __name__ == '__main__':
    try:
        # Пробуем запустить стандартно
        main()
    except RuntimeError as e:
        # Если Python 3.14 ругается на отсутствие цикла событий (Event Loop),
        # мы создаем его принудительно и запускаем заново.
        if "no current event loop" in str(e):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            main()
        else:
            raise e
