from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
import openai
import os

TELEGRAM_TOKEN = os.environ['TELEGRAM_TOKEN']
OPENAI_API_KEY = os.environ['OPENAI_API_KEY']
openai.api_key = OPENAI_API_KEY

async def start(update: Update, context: CallbackContext):
    await update.message.reply_text('Привет! Я AI-ассистент. Задай вопрос.')

async def handle_message(update: Update, context: CallbackContext):
    user_message = update.message.text
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": user_message}]
    )
    ai_reply = response.choices[0].message.content
    await update.message.reply_text(ai_reply)

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get('PORT', 8443)),
        url_path=TELEGRAM_TOKEN,
        webhook_url=os.environ['RENDER_EXTERNAL_URL'] + '/' + TELEGRAM_TOKEN
    )

if __name__ == '__main__':
    main()
