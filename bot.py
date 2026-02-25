import os
import json
import logging
import sys

# 1. Настройка логирования (чтобы видеть ошибки в панели Render)
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

# 2. УНИВЕРСАЛЬНЫЙ ИМПОРТ (код не упадет, даже если библиотеки нет)
try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    logger.error("ОШИБКА: Библиотека python-telegram-bot не установлена!")

try:
    from google import genai
    from google.genai import types
    AI_SUPPORT = True
except ImportError:
    logger.warning("ПРЕДУПРЕЖДЕНИЕ: google-genai не найден. ИИ отключен.")
    AI_SUPPORT = False

# 3. ПЕРЕМЕННЫЕ (Берем из настроек Render)
TOKEN = os.environ.get('TELEGRAM_TOKEN')
URL = os.environ.get('RENDER_EXTERNAL_URL')
AI_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER = os.environ.get('OWNER_ID')

# 4. ИНИЦИАЛИЗАЦИЯ ИИ
client = None
if AI_SUPPORT and AI_KEY:
    try:
        client = genai.Client(api_key=AI_KEY)
    except Exception as e:
        logger.error(f"Ошибка ИИ: {e}")

# --- ФУНКЦИИ БОТА ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет кнопку Mini App"""
    # Ссылка на твой Vercel
    web_app = WebAppInfo(url="https://min-app-tawny.vercel.app")
    # Кнопка вместо клавиатуры (самый стабильный вариант для передачи данных)
    kb = [[KeyboardButton(text="🚀 Запустить awm os", web_app=web_app)]]
    await update.message.reply_text(
        "Система awm os активирована. Нажми кнопку ниже для входа в интерфейс.",
        reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True)
    )

async def handle_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимает данные из формы Mini App"""
    try:
        raw_data = update.effective_message.web_app_data.data
        data = json.loads(raw_data)
        
        name = data.get('name', 'Пользователь')
        niche = data.get('niche', 'Не указана')
        
        await update.message.reply_text(f"Данные получены, {name}! 🦾\nСоффи начала анализ ниши: {niche}")
        
        if OWNER:
            report = f"🚀 **НОВЫЙ ЛИД:**\n👤 Имя: {name}\n🏢 Ниша: {niche}\n📞 Контакт: {data.get('contact')}"
            await context.bot.send_message(chat_id=OWNER, text=report)
    except Exception as e:
        logger.error(f"Ошибка обработки формы: {e}")

async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Общение с ИИ Соффи"""
    if not client:
        await update.message.reply_text("Соффи сейчас на техобслуживании. Используйте Mini App.")
        return
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=update.message.text,
            config=types.GenerateContentConfig(
                system_instruction="Ты — Soffi, ассистент awm os. Будь краткой и профессиональной."
            )
        )
        await update.message.reply_text(response.text)
    except Exception as e:
        logger.error(f"Ошибка чата: {e}")
        await update.message.reply_text("Я немного задумалась. Попробуй через минуту.")

# --- ЗАПУСК ---

def main():
    if not TOKEN or not URL:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: Проверь TELEGRAM_TOKEN и RENDER_EXTERNAL_URL!")
        return

    # Настройка Webhook
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    port = int(os.environ.get('PORT', 8443))
    # Убираем лишний слэш из URL если он есть
    clean_url = URL.rstrip('/')
    
    logger.info(f"Запуск на порту {port}")
    app.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{clean_url}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
