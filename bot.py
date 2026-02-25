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
# Добавили проверку ключа, чтобы бот не падал при запуске
client = None
if GOOGLE_API_KEY:
    client = genai.Client(api_key=GOOGLE_API_KEY) 

MODEL_ID = "gemini-2.0-flash"  
SYSTEM_PROMPT = "Ты — Soffi, лицо awm os. Твой стиль: баланс строгости и вдохновения." 

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    web_app_info = WebAppInfo(url="https://min-app-tawny.vercel.app")
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

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        data = json.loads(update.effective_message.web_app_data.data)
        await update.message.reply_text(f"Принято! Ниша '{data.get('niche')}' уже в анализе.")
        if OWNER_ID:
            await context.bot.send_message(chat_id=OWNER_ID, text=f"🚀 ЗАЯВКА: {data}")
    except Exception as e:
        await update.message.reply_text(f"Ошибка данных: {e}")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE): 
    user = update.effective_user 
    
    # Если ИИ не инициализирован
    if not client:
        await update.message.reply_text("Ошибка: API ключ Gemini не установлен.")
        return

    try: 
        # Пытаемся получить ответ от ИИ
        response = client.models.generate_content( 
            model=MODEL_ID, 
            contents=update.message.text, 
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT) 
        ) 
        
        if response and response.text:
            await update.message.reply_text(response.text) 
        else:
            await update.message.reply_text("ИИ прислал пустой ответ.")

        # Отчет владельцу
        if OWNER_ID and str(user.id) != str(OWNER_ID): 
            report = f"📈 **Лид!**\n👤: {user.first_name}\n💬: {update.message.text}" 
            await context.bot.send_message(chat_id=OWNER_ID, text=report)
            
    except Exception as e: 
        # Если ошибка — пишем её в чат, чтобы понять причину!
        await update.message.reply_text(f"Ошибка ИИ: {str(e)}") 

def main(): 
    application = Application.builder().token(TOKEN).build() 
    
    application.add_handler(CommandHandler("start", start)) 
    application.add_handler(CommandHandler("check", check_status)) 
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)) 

    port = int(os.environ.get('PORT', 8443)) 
    clean_url = URL.strip().rstrip('/')
    
    application.run_webhook(
        listen="0.0.0.0", 
        port=port, 
        url_path=TOKEN, 
        webhook_url=f"{clean_url}/{TOKEN}"
    ) 

if __name__ == '__main__': 
    main()
