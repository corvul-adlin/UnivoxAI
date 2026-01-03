import os
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from google import genai 
from aiohttp import web

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

current_model = "gemini-3-flash-preview"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Клиент Google
client = genai.Client(api_key=GEMINI_KEY)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ КОМАНДЫ ] ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer(f"🚀 **UnivoxAI v4.6 Ready**\nModel: `{current_model}`")

@dp.message(Command("change"))
async def change_model(message: types.Message):
    global current_model
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("❌ Формат: `/change gemini-2.0-flash`")
        return
    current_model = args[1].strip()
    await message.answer(f"✅ Переключено на: `{current_model}`")

@dp.message()
async def chat_handler(message: types.Message):
    if not message.text: return
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        response = client.models.generate_content(model=current_model, contents=message.text)
        await message.answer(response.text if response.text else "⚠️ Пустой ответ.")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {str(e)[:100]}")

# --- [ СЕРВЕР ДЛЯ ПИНГЕРА ] ---
async def handle_ping(request):
    # Пингер получит этот ответ мгновенно, не мешая боту
    return web.Response(text="I AM ALIVE", status=200)

async def main():
    # 1. Сначала настраиваем веб-сервер
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # 2. Запускаем порт (Render увидит, что бот "жив", и перестанет его рестартить)
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Веб-сервер запущен на порту {PORT}")

    # 3. И только ПОТОМ запускаем Telegram бота
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info(f"Бот запущен на модели {current_model}")
    
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен")