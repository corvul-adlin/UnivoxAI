import os
import asyncio
import logging
import io
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
import google.generativeai as genai
from aiohttp import web
from PIL import Image

# --- [ КОНФИГУРАЦИЯ СИСТЕМЫ ] ---

# Токены берем из Environment Variables на Render
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
# Render дает порт автоматически, если нет — используем 10000
PORT = int(os.getenv("PORT", 10000))

# Настройка логирования (чтобы видеть в консоли Render, что происходит)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Настройка ИИ: Модель Gemini 2.0 Flash с поиском в Google
genai.configure(api_key=GEMINI_KEY)
tools = [{"google_search": {}}]
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash-exp', 
    tools=tools
)

# Память бота (хранится в RAM, пока процесс запущен)
user_data = {}
WARNING_THRESHOLD = 15 # Лимит сообщений до предупреждения

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- [ СЛУЖЕБНЫЕ ФУНКЦИИ ] ---

def init_chat(uid):
    """Создает новую чистую сессию для пользователя"""
    user_data[uid] = {
        # enable_automatic_function_calling позволяет боту самому юзать гугл-поиск
        'chat': model.start_chat(history=[], enable_automatic_function_calling=True),
        'count': 0
    }

# --- [ ОБРАБОТЧИКИ КОМАНД ] ---

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    """Приветствие при первом запуске"""
    init_chat(message.from_user.id)
    await message.answer(
        "🚀 **UnivoxAI v3.1 [Gemini 2.0 Flash]**\n\n"
        "Бот успешно запущен на Render!\n"
        "• Принимаю текст, фото и голосовые.\n"
        "• Ищу инфу в Google в реальном времени.\n\n"
        "Чтобы начать всё заново, пиши /newchat"
    )

@dp.message(Command("newchat"))
async def reset_handler(message: types.Message):
    """Ручной сброс контекста через команду"""
    init_chat(message.from_user.id)
    await message.answer("🔄 **Память очищена.** Я готов к новым вопросам!")

@dp.callback_query(F.data == "reset_session")
async def callback_reset(callback: types.CallbackQuery):
    """Сброс контекста при нажатии на кнопку под варнингом"""
    init_chat(callback.from_user.id)
    # Редактируем старое сообщение, чтобы подтвердить сброс
    await callback.message.edit_text("🔄 **История диалога обнулена.** О чем теперь поболтаем?")
    await callback.answer()

# --- [ ОБРАБОТКА КОНТЕНТА ] ---

@dp.message(F.text)
async def text_handler(message: types.Message):
    """Обработка текста и поисковых запросов"""
    uid = message.from_user.id
    if uid not in user_data: init_chat(uid)
    
    # Показываем статус "печатает"
    await bot.send_chat_action(message.chat.id, "typing")
    
    try:
        chat_data = user_data[uid]
        response = chat_data['chat'].send_message(message.text)
        chat_data['count'] += 1
        
        # Если достигнут порог сообщений, добавляем кнопку сброса
        if chat_data['count'] == WARNING_THRESHOLD:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(
                text="🔄 Начать новый чат", 
                callback_data="reset_session")
            )
            
            warning_text = (
                f"{response.text}\n\n───\n"
                "⚠️ **Диалог стал длинным.** Чтобы я не начал ошибаться, советую обновить сессию:"
            )
            await message.answer(warning_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        else:
            await message.answer(response.text, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Ошибка текста: {e}")
        await message.answer("❌ Произошла ошибка. Попробуй /newchat")

@dp.message(F.voice)
async def voice_handler(message: types.Message):
    """Обработка голосовых сообщений (Gemini слышит голос)"""
    uid = message.from_user.id
    if uid not in user_data: init_chat(uid)
    
    await bot.send_chat_action(message.chat.id, "record_voice")
    
    try:
        # Скачиваем голос во временный буфер (не засоряем диск)
        file = await bot.get_file(message.voice.file_id)
        voice_io = io.BytesIO()
        await bot.download_file(file.file_path, voice_io)
        
        audio_data = {"mime_type": "audio/ogg", "data": voice_io.getvalue()}
        
        chat_data = user_data[uid]
        response = chat_data['chat'].send_message([audio_data, "Прослушай и ответь максимально точно."])
        chat_data['count'] += 1
        
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка голоса: {e}")
        await message.reply("🎙 Не удалось разобрать голосовое сообщение.")

@dp.message(F.photo)
async def photo_handler(message: types.Message):
    """Анализ изображений"""
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        photo_io = io.BytesIO()
        await bot.download(message.photo[-1], photo_io)
        img = Image.open(photo_io)
        
        prompt = message.caption if message.caption else "Что на фото?"
        # Запрос к Vision без истории для экономии ресурсов
        response = model.generate_content([prompt, img])
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка фото: {e}")
        await message.reply("📸 Не удалось проанализировать картинку.")

# --- [ ВЕБ-СЕРВЕР ДЛЯ RENDER HEALTH CHECK ] ---

async def handle_ping(request):
    """То, что ты увидишь при открытии ссылки в браузере"""
    return web.Response(text="UnivoxAI v3.1: Online on Render")

async def main():
    # Настройка веб-сервера aiohttp
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Запуск Health Check сервера
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    logger.info(f"Сервер проверки запущен на порту {PORT}")
    
    # Запуск самого бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")