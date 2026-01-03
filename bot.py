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

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Настройка Gemini
genai.configure(api_key=GEMINI_KEY)

# Список моделей для проверки (от самой новой к самой стабильной)
MODEL_NAMES = [
    'gemini-2.5-flash-latest', 
    'models/gemini-2.5-flash', 
    'gemini-2.5-flash',
]

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ СИСТЕМА ОТЛАДКИ ] ---
async def send_debug(error_message):
    if ADMIN_ID:
        try:
            text = f"🚨 **DEBUG REPORT** 🚨\n\n```\n{error_message[:3500]}\n```"
            await bot.send_message(ADMIN_ID, text, parse_mode="Markdown")
        except:
            logger.error("Не удалось отправить дебаг")

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("🚀 **UnivoxAI v4.3 Online**\nСистема готова к работе!")

@dp.message()
async def chat_handler(message: types.Message):
    if not message.text: return
    await bot.send_chat_action(message.chat.id, "typing")
    
    # Пытаемся по очереди использовать разные имена моделей
    success = False
    last_error = ""

    for m_name in MODEL_NAMES:
        try:
            current_model = genai.GenerativeModel(m_name)
            response = current_model.generate_content(message.text)
            if response.text:
                await message.answer(response.text)
                success = True
                break
        except Exception as e:
            last_error = str(e)
            logger.warning(f"Модель {m_name} не сработала: {e}")
            continue # Пробуем следующую модель из списка

    if not success:
        full_error = traceback.format_exc()
        await message.answer("❌ Ошибка связи с ИИ. Отчет отправлен.")
        await send_debug(f"User: {message.from_user.id}\nInput: {message.text}\n\nПоследняя ошибка:\n{last_error}\n\nFull Traceback:\n{full_error}")

# --- [ СЕРВЕР ] ---
async def handle_ping(request):
    return web.Response(text="ALIVE")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())