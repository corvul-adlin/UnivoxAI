import os
import asyncio
import logging
import traceback
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from google import genai # ИСПОЛЬЗУЕМ НОВЫЙ SDK
from aiohttp import web

# --- [ КОНФИГУРАЦИЯ ] ---
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация нового клиента (он работает через стабильный API v1)
client = genai.Client(api_key=GEMINI_KEY)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ ЛОГИКА ] ---

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.answer("💎 **UnivoxAI v4.4 СТАБИЛЬНАЯ**\nПривет! Теперь всё будет работать!")

@dp.message()
async def chat_handler(message: types.Message):
    if not message.text: return
    await bot.send_chat_action(message.chat.id, "typing")
    
    try:
        # Прямой вызов модели без лишних префиксов
        response = client.models.generate_content(
            model="gemini-2.5-flash", 
            contents=message.text
        )
        
        if response.text:
            await message.answer(response.text)
        else:
            await message.answer("⚠️ ИИ промолчал (цензура или пустой ответ).")
            
    except Exception as e:
        error_trace = traceback.format_exc()
        logger.error(f"Ошибка: {error_trace}")
        await message.answer("❌ Ошибка соединения. Отчет отправлен.")
        
        if ADMIN_ID:
            await bot.send_message(ADMIN_ID, f"🚨 **FINAL DEBUG** 🚨\n\n```\n{error_trace[:3500]}\n```")

# --- [ СЕРВЕР ] ---
async def handle_ping(request):
    return web.Response(text="WORK")

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Бот v4.4 запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())