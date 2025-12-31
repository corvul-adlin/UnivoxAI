import os
import asyncio
import logging
import io
import aiohttp  # Библиотека для выполнения HTTP-запросов (нужна для /deploy)
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import google.generativeai as genai
from aiohttp import web
from PIL import Image

# --- [ КОНФИГУРАЦИЯ СИСТЕМЫ ] ---

# Загружаем ключи из переменных окружения Render
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
DEPLOY_HOOK_URL = os.getenv("DEPLOY_HOOK_URL")
# Преобразуем ADMIN_ID в число, по умолчанию 0
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except (ValueError, TypeError):
    ADMIN_ID = 0

# Порт для веб-сервера (Render использует 10000 по умолчанию)
PORT = int(os.getenv("PORT", 10000))

# Настройка логирования для отслеживания работы бота в реальном времени
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Настройка ИИ модели Gemini 2.0 Flash
genai.configure(api_key=GEMINI_KEY)
# Подключаем инструмент Google Search для актуальных ответов
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash-exp', 
    tools=[{"google_search": {}}]
)

# Оперативная память для хранения контекста диалогов
user_data = {}
WARNING_THRESHOLD = 15  # Лимит сообщений до предложения очистить чат

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ СЛУЖЕБНЫЕ ФУНКЦИИ ] ---

def init_chat(uid):
    """Создает новую сессию чата с поддержкой инструментов (Google Search)"""
    user_data[uid] = {
        'chat': model.start_chat(history=[], enable_automatic_function_calling=True),
        'count': 0
    }

# --- [ ОБРАБОТЧИКИ КОМАНД ] ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    """Приветствие и инициализация пользователя"""
    init_chat(message.from_user.id)
    welcome_text = (
        "🚀 **UnivoxAI v3.2: Полная сборка**\n\n"
        "Я запущен и готов к работе на Render!\n\n"
        "**Мои возможности:**\n"
        "• 🔍 Поиск в Google в реальном времени\n"
        "• 🎙 Понимание голосовых сообщений\n"
        "• 📸 Анализ любых изображений\n"
        "• 🧠 Долгая память (до 15 сообщений)\n\n"
        "Пиши /newchat, если хочешь начать новую тему."
    )
    await message.answer(welcome_text, parse_mode="Markdown")

@dp.message(Command("newchat"))
async def reset_handler(message: types.Message):
    """Ручной сброс истории диалога"""
    init_chat(message.from_user.id)
    await message.answer("🔄 **Память очищена.** Я всё забыл, давай начнем заново!")

@dp.message(Command("deploy"))
async def deploy_handler(message: types.Message):
    """Секретная команда для принудительного обновления (только для админа)"""
    if message.from_user.id != ADMIN_ID:
        logger.warning(f"Попытка доступа к деплою от ID {message.from_user.id}")
        return # Просто игнорируем чужих пользователей

    if not DEPLOY_HOOK_URL:
        return await message.answer("❌ Ошибка: DEPLOY_HOOK_URL не настроен в Render.")

    await message.answer("🛠 **Инициирую пересборку проекта на Render...**")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(DEPLOY_HOOK_URL) as resp:
                if resp.status == 200:
                    await message.answer("✅ **Запрос отправлен!** Бот скоро уйдет на перезагрузку и обновится.")
                else:
                    await message.answer(f"⚠️ Render ответил кодом: {resp.status}")
    except Exception as e:
        await message.answer(f"❌ Ошибка связи с Render: {e}")

@dp.callback_query(F.data == "reset_session")
async def callback_reset(callback: types.CallbackQuery):
    """Обработка нажатия на инлайн-кнопку 'Обновить чат'"""
    init_chat(callback.from_user.id)
    await callback.message.edit_text("🔄 **История диалога обнулена.** О чем пообщаемся?")
    await callback.answer()

# --- [ ОБРАБОТКА КОНТЕНТА ] ---

@dp.message(F.text)
async def text_handler(message: types.Message):
    """Обработка текстовых запросов с поиском в Google"""
    uid = message.from_user.id
    if uid not in user_data: init_chat(uid)
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    try:
        chat_data = user_data[uid]
        response = chat_data['chat'].send_message(message.text)
        chat_data['count'] += 1
        
        # Проверка на длинный диалог
        if chat_data['count'] >= WARNING_THRESHOLD:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(text="🔄 Начать новый чат", callback_data="reset_session"))
            text = f"{response.text}\n\n───\n⚠️ **Контекст переполнен.** Рекомендую очистить чат для точности ответов."
            await message.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        else:
            await message.answer(response.text, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Text Error: {e}")
        await message.answer("❌ Произошла ошибка ИИ. Попробуй /newchat")

@dp.message(F.voice)
async def voice_handler(message: types.Message):
    """Обработка голосовых сообщений (Gemini Audio)"""
    uid = message.from_user.id
    if uid not in user_data: init_chat(uid)
    
    await bot.send_chat_action(message.chat.id, "record_voice")
    
    try:
        # Скачиваем аудио во временную память
        file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(file.file_path, voice_io)
        
        audio_content = {"mime_type": "audio/ogg", "data": voice_io.getvalue()}
        chat_data = user_data[uid]
        
        # Отправляем аудио в чат Gemini
        response = chat_data['chat'].send_message([audio_content, "Прослушай это сообщение и ответь пользователю."])
        chat_data['count'] += 1
        
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Voice Error: {e}")
        await message.reply("🎙 Не удалось распознать голосовое сообщение.")

@dp.message(F.photo)
async def photo_handler(message: types.Message):
    """Анализ изображений (Gemini Vision)"""
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        photo_io = io.BytesIO()
        await bot.download(message.photo[-1], photo_io)
        img = Image.open(photo_io)
        
        prompt = message.caption if message.caption else "Что на этом изображении? Опиши подробно."
        # Генерация контента по фото (без истории чата для экономии токенов)
        response = model.generate_content([prompt, img])
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Photo Error: {e}")
        await message.reply("📸 Ошибка при анализе фотографии.")

# --- [ ВЕБ-СЕРВЕР ДЛЯ RENDER ] ---

async def handle_ping(request):
    """Эндпоинт для проверки работоспособности (Health Check)"""
    return web.Response(text="UnivoxAI v3.2: Online on Render")

async def main():
    # Инициализация веб-сервера
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Запуск сервера на указанном порту
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    logger.info(f"Health-сервер запущен на порту {PORT}")
    
    # Запуск бота в режиме опроса (polling)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот выключен пользователем.")