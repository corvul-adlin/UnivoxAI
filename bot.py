import os
import asyncio
import logging
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from google import genai 
from google.genai import types as ai_types
from aiohttp import web
from PIL import Image

# --- [ КОНФИГУРАЦИЯ ] ---
VERSION = "v4.0 beta (Debug Mode)"
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))
MODEL_ID = "gemini-1.5-flash"  # Используем самую стабильную модель

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Инициализация клиента Google AI
client = genai.Client(api_key=GEMINI_KEY)

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(f"🚀 **UnivoxAI {VERSION}**\n\nЯ готов к работе. Напиши мне что-нибудь!")

@dp.message(F.text)
async def handle_text(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        # Попытка генерации ответа
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=message.text,
            config=ai_types.GenerateContentConfig(
                tools=[ai_types.Tool(google_search=ai_types.GoogleSearchRetrieval())]
            )
        )
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"AI Error: {e}")
        
        # --- БЛОК СУПЕР-ОТЛАДКИ ---
        error_str = str(e)
        debug_info = (
            f"❌ **ОШИБКА ИИ**\n\n"
            f"🔍 **Тип ошибки:** `{type(e).__name__}`\n"
            f"📝 **Сообщение:** `{error_str[:400]}`\n\n"
            f"💡 *Инструкция: Скопируй это сообщение и отправь инженеру (мне в чат).* "
        )
        await message.reply(debug_info, parse_mode="Markdown")

@dp.message(F.photo)
async def handle_photo(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        photo_io = io.BytesIO()
        file = await bot.get_file(message.photo[-1].file_id)
        await bot.download_file(file.file_path, photo_io)
        img = Image.open(photo_io)
        
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=[message.caption or "Что на фото?", img]
        )
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Photo Error: {e}")
        await message.reply(f"📸 Ошибка фото: `{str(e)[:100]}`")

# --- [ СИСТЕМА ЖИЗНЕОБЕСПЕЧЕНИЯ ] ---

async def handle_ping(request):
    return web.Response(text="ALIVE", status=200)

async def main():
    # Очистка старых вебхуков, чтобы избежать Conflict
    await bot.delete_webhook(drop_pending_updates=True)
    
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    
    logger.info(f"Старт {VERSION} на порту {PORT}")
    await asyncio.gather(
        site.start(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    asyncio.run(main())