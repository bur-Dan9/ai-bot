import os
import asyncio
import json
import logging
from google import genai
from google.genai import types
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Настройка логирования (чтобы видеть реальные причины ошибок в логах Render)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# 1. Настройки окружения
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER_ID = os.environ.get('OWNER_ID')
URL = os.environ.get('RENDER_EXTERNAL_URL')

# 2. Безопасная настройка Soffi
client = None
if GOOGLE_API_KEY:
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        MODEL_ID = "gemini-2.0-flash"
    except Exception as e:
        logger.error(f"Ошибка инициализации Gemini: {e}")

SYSTEM_PROMPT = """
Ты — Soffi, экспертный ассистент awm os. Твоя цель: прогреть локальный бизнес, 
узнать их бюджет на подписку и обещать уведомить о запуске. 
Стиль: строгий, но вдохновляющий.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Убеждаемся, что URL не пустой
    app_url = "https://min-app-tawny.vercel.app"
    web_app_info = WebAppInfo(url=app_url)
    
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton(text="🚀 Запустить awm os", web_app=web_app_info)]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        "Добро пожаловать в будущее. Я — Соффи.\n\n"
        "Нажмите кнопку внизу, чтобы открыть систему.",
        reply_markup=keyboard
    )

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data_json = update.effective_message.web_app_data.data
        data = json.loads(data_json)
        
        name = data.get('name', 'Пользователь')
        niche = data.get('niche', 'Не указана')
        contact = data.get('contact', 'Не указан')

        await update.message.reply_text(f"Система приняла данные, {name}! 🦾\nНиша '{niche}' анализируется.")

        if OWNER_ID:
            report = f"🚀 **НОВАЯ ЗАЯВКА!**\n👤: {name}\n🏢: {niche}\n📞: {contact}"
            await context.bot.send_message(chat_id=OWNER_ID, text=report)
    except Exception as e:
        logger.error(f"Ошибка в handle_web_app_data: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not client:
        await update.message.reply_text("ИИ временно недоступен. Проверьте API ключ.")
        return

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=update.message.text,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        logger.error(f"Ошибка Gemini: {e}")
        await update.message.reply_text("Я провожу обновление. Попробуйте через минуту.")

def main():
    # ПРОВЕРКА КРИТИЧЕСКИХ ДАННЫХ ПЕРЕД ЗАПУСКОМ
    if not TOKEN:
        logger.error("ОШИБКА: TELEGRAM_TOKEN не найден в переменных окружения!")
        return
    if not URL:
        logger.error("ОШИБКА: RENDER_EXTERNAL_URL не найден! Бот не может запустить Webhook.")
        return

    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get('PORT', 8443))
    
    # Очищаем URL от лишних слэшей в конце, если они есть
    webhook_base_url = URL.rstrip('/')
    
    logger.info(f"Запуск Webhook на порту {port}...")
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{webhook_base_url}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
