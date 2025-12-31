import os
import asyncio
import logging
import io
import aiohttp # Библиотека для работы с сетью и деплоем
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import google.generativeai as genai
from aiohttp import web
from PIL import Image

# --- [ КОНФИГУРАЦИЯ СИСТЕМЫ ] ---

# Токены и ключи из переменных окружения Render
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
DEPLOY_HOOK_URL = os.getenv("DEPLOY_HOOK_URL")

# Обработка ADMIN_ID (превращаем строку из переменной в число)
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except (ValueError, TypeError):
    ADMIN_ID = 0

# Порт для Render (обязательно 10000)
PORT = int(os.getenv("PORT", 10000))

# Настройка логирования (чтобы ты видел ошибки в панели Render)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Проверка наличия ключей перед запуском
if not TG_TOKEN or not GEMINI_KEY:
    logger.critical("❌ КРИТИЧЕСКАЯ ОШИБКА: Токены не найдены в настройках Render!")

# Настройка ИИ: Gemini 2.0 Flash + Google Search
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash-exp', 
    tools=[{"google_search": {}}] # Тот самый живой поиск
)

# Оперативная память для сессий
user_data = {}
WARNING_THRESHOLD = 15 # Лимит контекста

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ СЛУЖЕБНЫЕ ФУНКЦИИ ] ---

def init_chat(uid):
    """Инициализация новой сессии с поддержкой поиска"""
    user_data[uid] = {
        'chat': model.start_chat(history=[], enable_automatic_function_calling=True),
        'count': 0
    }

# --- [ ОБРАБОТЧИКИ КОМАНД ] ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    """Команда /start — начало работы"""
    init_chat(message.from_user.id)
    await message.answer(
        "🚀 **UnivoxAI v3.2: Система запущена!**\n\n"
        "Я работаю на Render.com и готов к общению.\n"
        "• Текст, фото, голос — я понимаю всё.\n"
        "• Поиск в Google включен автоматически."
    )

@dp.message(Command("newchat"))
async def reset_handler(message: types.Message):
    """Команда /newchat — очистка памяти"""
    init_chat(message.from_user.id)
    await message.answer("🔄 **Контекст обнулен.** О чем поговорим теперь?")

@dp.message(Command("deploy"))
async def deploy_handler(message: types.Message):
    """Команда /deploy — Магическое обновление (только для админа)"""
    if message.from_user.id != ADMIN_ID:
        logger.warning(f"Попытка доступа к деплою от {message.from_user.id}")
        return

    if not DEPLOY_HOOK_URL:
        return await message.answer("❌ Ссылка для деплоя не установлена!")

    await message.answer("🛠 **Отправляю запрос на обновление сервера...**")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DEPLOY_HOOK_URL) as resp:
                if resp.status == 200:
                    await message.answer("✅ **Успех!** Render начал пересборку бота.")
                else:
                    await message.answer(f"⚠️ Ошибка Render: {resp.status}")
    except Exception as e:
        await message.answer(f"❌ Ошибка связи: {e}")

@dp.callback_query(F.data == "reset_session")
async def callback_reset(callback: types.CallbackQuery):
    """Обработка кнопки сброса"""
    init_chat(callback.from_user.id)
    await callback.message.edit_text("🔄 **История диалога стерта.**")
    await callback.answer()

# --- [ ОБРАБОТКА КОНТЕНТА ] ---

@dp.message(F.text)
async def text_handler(message: types.Message):
    """Обработка текстовых сообщений"""
    uid = message.from_user.id
    if uid not in user_data: init_chat(uid)
    await bot.send_chat_action(message.chat.id, "typing")
    
    try:
        chat_data = user_data[uid]
        response = chat_data['chat'].send_message(message.text)
        chat_data['count'] += 1
        
        if chat_data['count'] >= WARNING_THRESHOLD:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="🔄 Сбросить чат", callback_data="reset_session"))
            await message.answer(f"{response.text}\n\n───\n⚠️ Чат стал длинным.", reply_markup=builder.as_markup(), parse_mode="Markdown")
        else:
            await message.answer(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Text Error: {e}")
        await message.answer("❌ Ошибка ИИ. Используйте /newchat")

@dp.message(F.voice)
async def voice_handler(message: types.Message):
    """Обработка голосовых сообщений"""
    uid = message.from_user.id
    if uid not in user_data: init_chat(uid)
    await bot.send_chat_action(message.chat.id, "record_voice")
    try:
        file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(file.file_path, voice_io)
        response = user_data[uid]['chat'].send_message([{"mime_type": "audio/ogg", "data": voice_io.getvalue()}, "Ответь на голос."])
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Voice Error: {e}"); await message.reply("🎙 Ошибка голоса.")

@dp.message(F.photo)
async def photo_handler(message: types.Message):
    """Обработка фотографий (Vision)"""
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        photo_io = io.BytesIO()
        await bot.download(message.photo[-1], photo_io)
        img = Image.open(photo_io)
        response = model.generate_content([message.caption or "Что на фото?", img])
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Photo Error: {e}"); await message.reply("📸 Ошибка фото.")

# --- [ ЗАПУСК И HEALTH CHECK ] ---

async def handle_ping(request):
    """Ответ для Render, чтобы он знал, что бот жив"""
    return web.Response(text="UnivoxAI v3.2: Alive and Running")

async def main():
    # Настройка сервера для пинга
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"✅ Сервер проверки запущен на порту {PORT}")

    # СБРОС СТАРЫХ НАСТРОЕК (Чтобы бот заговорил!)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запуск опроса Telegram
    logger.info("🚀 Polling запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")