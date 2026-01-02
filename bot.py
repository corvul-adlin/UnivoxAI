import os
import asyncio
import logging
import io
import traceback
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
import google.generativeai as genai
from aiohttp import web
from PIL import Image

# --- [ НАСТРОЙКИ ] ---
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0
PORT = int(os.getenv("PORT", 10000))

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация Gemini (Библиотека google-generativeai==0.8.3)
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash') # Стабильная модель

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ СИСТЕМА ОТЛАДКИ ] ---
async def send_debug(error_message):
    """Отправляет отчет об ошибке админу в Telegram"""
    if ADMIN_ID:
        try:
            # Обрезаем, если ошибка слишком длинная
            text = f"🚨 **DEBUG REPORT** 🚨\n\n```\n{error_message[:3500]}\n```"
            await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
        except:
            logger.error("Не удалось отправить дебаг админу")

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("✅ Бот v4.2 запущен на старом аккаунте!\nПиши запрос, я готов.")

@dp.message()
async def chat_handler(message: types.Message):
    # Если это фото или голос, aiogram может тупить без фильтров, 
    # поэтому этот хендлер только для текста.
    if not message.text: return

    await bot.send_chat_action(message.chat.id, "typing")
    
    # Попытка запроса к ИИ с отловом ошибок
    try:
        response = model.generate_content(message.text)
        if response.text:
            await message.answer(response.text)
        else:
            await message.answer("⚠️ ИИ вернул пустой ответ (возможно, цензура).")
            
    except Exception as e:
        full_error = traceback.format_exc()
        logger.error(f"Ошибка: {full_error}")
        
        # Красивое уведомление пользователю
        await message.answer("❌ Произошла ошибка. Отчет отправлен разработчику.")
        
        # СУПЕР-ОТЛАДКА ДЛЯ ТЕБЯ
        await send_debug(f"User: {message.from_user.id}\nInput: {message.text}\n\nError:\n{full_error}")

# --- [ SERVER ] ---
async def handle_ping(request):
    return web.Response(text="БОТ РАБОТАЕТ")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    # Сброс вебхуков (ОБЯЗАТЕЛЬНО)
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот вышел на связь...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())