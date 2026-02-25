import os
import asyncio
import openai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Загрузка ключей
TOKEN = os.environ['TELEGRAM_TOKEN']
OPENAI_KEY = os.environ['OPENAI_API_KEY']
URL = os.environ['RENDER_EXTERNAL_URL']

client = openai.AsyncOpenAI(api_key=OPENAI_KEY)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Я AI-ассистент на связи.')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Асинхронный запрос к OpenAI (не блокирует бота)
    response = await client.chat.completions.create(
        model="gpt-4o-mini", # Самая дешевая и быстрая модель
        messages=[{"role": "user", "content": update.message.text}]
    )
    await update.message.reply_text(response.choices[0].message.content)

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Настройка Webhook для Render
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get('PORT', 8443)),
        url_path=TOKEN,
        webhook_url=f"{URL}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
