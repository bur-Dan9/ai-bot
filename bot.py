import os
import asyncio
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Настройки окружения
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER_ID = os.environ.get('OWNER_ID') 
URL = os.environ.get('RENDER_EXTERNAL_URL')

# 2. Настройка Soffi
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    system_instruction="Ты — Soffi, экспертный ассистент awm os. Твоя цель: прогреть локальный бизнес, узнать их бюджет на подписку и обещать уведомить о запуске."
)

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Здравствуйте! Я Soffi, лицо awm os. 🦾\n"
        "Мы создаем ИИ-организм для полной автоматизации вашего маркетинга. "
        "Интересно узнать, как это изменит ваш бизнес?"
    )

# Секретная команда для тебя, чтобы проверить связь
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) == str(OWNER_ID):
        await update.message.reply_text("✅ Связь установлена! Я буду присылать отчеты о клиентах сюда.")
    else:
        await update.message.reply_text("Извините, эта команда только для администратора.")

# Обработка сообщений и отправка отчетов
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    try:
        # Ответ клиенту от лица Soffi
        response = model.generate_content(text)
        await update.message.reply_text(response.text)

        # Отправка отчета тебе в личку (если это пишет НЕ админ)
        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = (
                f"📈 **Новый лид!**\n"
                f"👤: {user.first_name} (@{user.username})\n"
                f"💬: {text}"
            )
            await context.bot.send_message(chat_id=OWNER_ID, text=report)

    except Exception as e:
        print(f"Ошибка: {e}")

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("проверка", check))
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
