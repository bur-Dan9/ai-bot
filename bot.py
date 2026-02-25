import os
import asyncio
import json
from google import genai
from google.genai import types
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Загрузка настроек
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER_ID = os.environ.get('OWNER_ID') 
URL = os.environ.get('RENDER_EXTERNAL_URL')

# 2. Инициализация Soffi
client = genai.Client(api_key=GOOGLE_API_KEY)
MODEL_ID = "gemini-2.0-flash" 

SYSTEM_PROMPT = """
Ты — Soffi, лицо AI-агентства "awm os". Твой стиль: баланс строгости и вдохновения. 
Цель: прогреть локальный бизнес. Ты — единая точка входа.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ссылка на твой Vercel
    web_app_info = WebAppInfo(url="https://min-app-tawny.vercel.app")
    
    # Твоя новая кнопка (ReplyKeyboard), чтобы работала отправка данных
    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton(text="🚀 Запустить awm os", web_app=web_app_info)]
    ], resize_keyboard=True)

    await update.message.reply_text(
        "Здравствуйте! Я Soffi, лицо awm os. 🦾\n"
        "Нажмите кнопку ниже, чтобы открыть систему.",
        reply_markup=keyboard
    )

async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) == str(OWNER_ID):
        await update.message.reply_text("✅ Связь с владельцем установлена!")
    else:
        await update.message.reply_text("Доступ только для администрации.")

# НОВАЯ ФУНКЦИЯ: Прием данных из твоей формы
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        name = data.get('name', 'Пользователь')
        niche = data.get('niche', 'Не указана')
        
        await update.message.reply_text(f"Принято, {name}! 🦾\nНиша '{niche}' уже в анализе.")

        if OWNER_ID:
            report = f"📈 **НОВЫЙ ЛИД!**\n👤: {name}\n🏢: {niche}\n📞: {data.get('contact')}"
            await context.bot.send_message(chat_id=OWNER_ID, text=report)
    except Exception as e:
        print(f"Ошибка данных: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
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
        print(f"Error: {e}")

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_status))
    
    # ВАЖНО: сначала ловим данные из формы, потом обычный текст
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get('PORT', 8443))
    # Чистим URL от возможных лишних пробелов или слэшей
    clean_url = URL.strip().rstrip('/')
    
    application.run_webhook(
        listen="0.0.0.0", 
        port=port, 
        url_path=TOKEN, 
        webhook_url=f"{clean_url}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
