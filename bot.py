import os
import json
import logging
import asyncio
import sys

# 1. Настройка логирования (чтобы видеть всё в панели Render)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

# 2. УНИВЕРСАЛЬНЫЙ ИМПОРТ (защита от краша при запуске)
try:
    from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
    from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
except ImportError:
    logger.error("КРИТИЧЕСКАЯ ОШИБКА: Библиотека python-telegram-bot не установлена!")

try:
    from google import genai
    from google.genai import types
    AI_AVAILABLE = True
except ImportError:
    logger.warning("ПРЕДУПРЕЖДЕНИЕ: google-genai не найден. ИИ будет отключен.")
    AI_AVAILABLE = False

# 3. Настройки
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER_ID = os.environ.get('OWNER_ID')
URL = os.environ.get('RENDER_EXTERNAL_URL')

# 4. Инициализация ИИ (только если есть ключ)
client = None
if AI_AVAILABLE and GOOGLE_API_KEY:
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
    except Exception as e:
        logger.error(f"Ошибка ИИ: {e}")

MODEL_ID = "gemini-2.0-flash"
SYSTEM_PROMPT = """
Ты — Soffi, лицо AI-агентства "awm os". 
Твой стиль: баланс строгости и вдохновения. 
Цель: прогреть локальный бизнес и узнать их нишу.
"""

# --- ОБРАБОТЧИКИ КОМАНД ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Кнопка Mini App (самый стабильный вариант для работы sendData)
    web_app_info = WebAppInfo(url="https://min-app-tawny.vercel.app")
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton(text="🚀 Запустить awm os", web_app=web_app_info)]
    ], resize_keyboard=True)
    
    await update.message.reply_text(
        "Здравствуйте! Я Soffi, лицо awm os. 🦾\n"
        "Нажмите кнопку ниже, чтобы открыть интерфейс управления ИИ-агентами.",
        reply_markup=keyboard
    )

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) == str(OWNER_ID):
        await update.message.reply_text("✅ Связь с владельцем установлена! Система стабильна.")
    else:
        await update.message.reply_text("Доступ только для администрации.")

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Прием данных из твоей формы на Vercel"""
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        name = data.get('name', 'Пользователь')
        niche = data.get('niche', 'Не указана')
        
        await update.message.reply_text(f"Принято, {name}! 🦾\nНиша '{niche}' уже анализируется Соффи.")

        if OWNER_ID:
            report = f"📈 **НОВЫЙ ЛИД!**\n👤: {name}\n🏢: {niche}\n📞: {data.get('contact')}"
            await context.bot.send_message(chat_id=OWNER_ID, text=report)
    except Exception as e:
        logger.error(f"Ошибка данных Mini App: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not client:
        await update.message.reply_text("Соффи обновляет нейронные связи. Попробуйте позже.")
        return

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=update.message.text,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
        )
        await update.message.reply_text(response.text)

        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = f"📈 **Новое сообщение!**\n👤: {user.first_name} (@{user.username})\n💬: {update.message.text}"
            await context.bot.send_message(chat_id=OWNER_ID, text=report)
    except Exception as e:
        logger.error(f"AI Error: {e}")

# --- ЗАПУСК ---

def main():
    if not TOKEN or not URL:
        logger.error("КРИТИЧЕСКАЯ ОШИБКА: TOKEN или URL не заданы в настройках Render!")
        return

    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_status))
    
    # Сначала проверяем данные из Mini App, потом обычный текст
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get('PORT', 8443))
    clean_url = URL.rstrip('/')
    
    logger.info(f"Запуск Webhook на порту {port}...")
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{clean_url}/{TOKEN}"
    )

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal Error: {e}")

def main():
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get("PORT", 10000))

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{URL}/{TOKEN}",
    )


if __name__ == "__main__":
    main()
