import os
import asyncio
import json # Добавлено для обработки данных из формы
from google import genai
from google.genai import types
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# 1. Настройки окружения
TOKEN = os.environ.get('TELEGRAM_TOKEN')
GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
OWNER_ID = os.environ.get('OWNER_ID') 
URL = os.environ.get('RENDER_EXTERNAL_URL')

# 2. Настройка Soffi
client = genai.Client(api_key=GOOGLE_API_KEY)
MODEL_ID = "gemini-2.0-flash"

SYSTEM_PROMPT = """
Ты — Soffi, экспертный ассистент awm os. Твоя цель: прогреть локальный бизнес, 
узнать их бюджет на подписку и обещать уведомить о запуске. 
Стиль: строгий, но вдохновляющий. Используй данные из Mini App (имя, ниша), если они доступны.
"""

# --- НОВАЯ КОМАНДА /START С КНОПКОЙ MINI APP ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Ссылка на ваше приложение
    web_app_info = WebAppInfo(url="https://min-app-tawny.vercel.app")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🚀 Войти в awm os", web_app=web_app_info)]
    ])
    
    await update.message.reply_text(
        "Добро пожаловать в будущее. Я — Соффи, ваш интерфейс к системе awm os.\n\n"
        "Нажмите кнопку ниже, чтобы активировать 10 ИИ-агентов и начать трансформацию вашего бизнеса.",
        reply_markup=keyboard
    )

# --- ОБРАБОТЧИК ДАННЫХ ИЗ ФОРМЫ MINI APP ---
async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Получаем данные, отправленные через tg.sendData()
    data_json = update.effective_message.web_app_data.data
    data = json.loads(data_json)
    
    name = data.get('name', 'Пользователь')
    niche = data.get('niche', 'Не указана')
    contact = data.get('contact', 'Не указан')

    # Ответ пользователю от лица Соффи
    await update.message.reply_text(
        f"Принято, {name}! 🦾\n\n"
        f"Я зафиксировала ваш интерес к системе для ниши '{niche}'. "
        "Мои алгоритмы уже начали предварительный анализ вашего сегмента рынка. "
        "Я уведомлю вас лично, как только модули будут полностью развернуты!"
    )

    # Уведомление владельцу (вам)
    if OWNER_ID:
        report = (
            f"🚀 **НОВАЯ ЗАЯВКА ИЗ MINI APP!**\n\n"
            f"👤 Имя: {name}\n"
            f"🏢 Ниша: {niche}\n"
            f"📞 Контакт: {contact}\n"
            f"🆔 ID: {update.effective_user.id}"
        )
        await context.bot.send_message(chat_id=OWNER_ID, text=report)

# Команда /check
async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) == str(OWNER_ID):
        await update.message.reply_text("✅ Связь с владельцем установлена! Отчеты будут приходить сюда.")
    else:
        await update.message.reply_text("Доступ ограничен.")

# Обычные сообщения (ИИ-чат)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=text,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT)
        )
        await update.message.reply_text(response.text)

        if OWNER_ID and str(user.id) != str(OWNER_ID):
            report = f"📈 **Новое сообщение!**\n👤: {user.first_name} (@{user.username})\n💬: {text}"
            await context.bot.send_message(chat_id=OWNER_ID, text=report)

    except Exception as e:
        print(f"Ошибка: {e}")
        await update.message.reply_text("Я провожу техническое обновление систем. Попробуйте через минуту.")

def main():
    application = Application.builder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check))
    
    # Регистрация обработчика данных из Mini App (ВАЖНО!)
    application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    port = int(os.environ.get('PORT', 8443))
    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        url_path=TOKEN,
        webhook_url=f"{URL}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
