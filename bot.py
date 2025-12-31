import os
import asyncio
import logging
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from google import genai # Официальный новый SDK
from google.genai import types as ai_types
from aiohttp import web
from PIL import Image

# --- [ КОНФИГУРАЦИЯ ] ---
VERSION = "v4.0 beta"
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 10000))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Инициализация клиента Google AI (Новый стандарт)
client = genai.Client(api_key=GEMINI_KEY)
MODEL_ID = "gemini-1.5-flash"

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ ОБРАБОТЧИКИ ] ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.reply(f"🚀 **UnivoxAI {VERSION}**\nСистема запущена на новом движке Google GenAI.\n\nПиши текст или кидай фото!")

@dp.message(F.text)
async def handle_text(message: types.Message):
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        # Генерация ответа с поддержкой поиска Google
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
        await message.reply("❌ Ошибка ИИ. Возможно, стоит проверить API ключ.")

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
        await message.reply("📸 Не удалось проанализировать фото.")

# --- [ СИСТЕМА ЖИЗНЕОБЕСПЕЧЕНИЯ (RENDER) ] ---

async def handle_ping(request):
    return web.Response(text=f"UnivoxAI {VERSION}: Статус OK", status=200)

async def main():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    
    logger.info(f"Запуск {VERSION} на порту {PORT}")
    # Запускаем сервер и бота одновременно
    await asyncio.gather(
        site.start(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"Критический сбой: {e}")