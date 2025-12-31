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

# --- КОНФИГУРАЦИЯ СИСТЕМЫ ---
# Загрузка токенов из переменных окружения (Environment Variables)
TG_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
PORT = int(os.getenv("PORT", 8000))

# Настройка логирования для отслеживания состояния сервера
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Инициализация ИИ-ядра Gemini 2.0 Flash
genai.configure(api_key=GEMINI_KEY)

# Подключение инструментов поиска (Grounding) для актуальных ответов
tools = [{"google_search": {}}]
model = genai.GenerativeModel(
    model_name='gemini-2.0-flash-exp', 
    tools=tools
)

# Оперативное хранилище сессий {user_id: {'chat': session, 'count': int}}
user_data = {}
WARNING_THRESHOLD = 15 # Порог предупреждения о длине контекста

bot = Bot(token=TG_TOKEN)
dp = Dispatcher()

# --- ВСПОМОГАТЕЛЬНАЯ ЛОГИКА ---

def init_chat(uid):
    """
    Инициализирует новую сессию чата для пользователя.
    Автоматически включает вызов функций (поиск в Google).
    """
    user_data[uid] = {
        'chat': model.start_chat(history=[], enable_automatic_function_calling=True),
        'count': 0
    }

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    """Команда запуска бота и приветствия"""
    init_chat(message.from_user.id)
    await message.answer(
        "🚀 **UnivoxAI v3.1 [Gemini 2.0 Flash]**\n\n"
        "Я готов к работе в мультимодальном режиме:\n"
        "• Отправляй текст или голосовые сообщения\n"
        "• Присылай фото для анализа\n"
        "• Я умею искать свежую информацию в Google\n\n"
        "Команда для сброса памяти: /newchat"
    )

@dp.message(Command("newchat"))
async def reset_handler(message: types.Message):
    """Ручной сброс контекста диалога"""
    init_chat(message.from_user.id)
    await message.answer("🔄 **Память очищена.** Я готов к новым вопросам с чистого листа!")

@dp.callback_query(F.data == "reset_session")
async def callback_reset(callback: types.CallbackQuery):
    """Обработка нажатия на инлайн-кнопку сброса"""
    init_chat(callback.from_user.id)
    await callback.message.edit_text("🔄 **Контекст обнулен.** Начинай новый диалог!")
    await callback.answer()

# --- ОБРАБОТЧИКИ КОНТЕНТА ---

@dp.message(F.text)
async def text_handler(message: types.Message):
    """Обработка текстовых запросов и поисковых задач"""
    uid = message.from_user.id
    if uid not in user_data:
        init_chat(uid)
    
    await bot.send_chat_action(message.chat.id, "typing")
    
    try:
        chat_data = user_data[uid]
        response = chat_data['chat'].send_message(message.text)
        chat_data['count'] += 1
        
        # Логика предупреждения о длине диалога
        if chat_data['count'] == WARNING_THRESHOLD:
            builder = InlineKeyboardBuilder()
            builder.row(types.InlineKeyboardButton(
                text="🔄 Начать новый чат", 
                callback_data="reset_session")
            )
            
            warning_text = (
                f"{response.text}\n\n───\n"
                "⚠️ **Внимание:** Диалог стал длинным. Для точности ответов рекомендую обновить сессию:"
            )
            await message.answer(warning_text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        else:
            await message.answer(response.text, parse_mode="Markdown")
            
    except Exception as e:
        logger.error(f"Text processing error: {e}")
        await message.answer("❌ Произошла ошибка. Попробуй /newchat")

@dp.message(F.voice)
async def voice_handler(message: types.Message):
    """Обработка и анализ голосовых сообщений (Audio-to-Text/Intent)"""
    uid = message.from_user.id
    if uid not in user_data:
        init_chat(uid)
    
    await bot.send_chat_action(message.chat.id, "record_voice")
    
    try:
        # Скачивание аудио в буфер памяти
        file_id = message.voice.file_id
        file = await bot.get_file(file_id)
        voice_io = io.BytesIO()
        await bot.download_file(file.file_path, voice_io)
        
        # Подготовка аудио-данных для Gemini
        audio_payload = {
            "mime_type": "audio/ogg", 
            "data": voice_io.getvalue()
        }
        
        chat_data = user_data[uid]
        response = chat_data['chat'].send_message([audio_payload, "Прослушай сообщение и ответь на него."])
        chat_data['count'] += 1
        
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        await message.reply("🎙 Не удалось распознать голосовое сообщение.")

@dp.message(F.photo)
async def photo_handler(message: types.Message):
    """Анализ изображений (Computer Vision)"""
    await bot.send_chat_action(message.chat.id, "typing")
    try:
        # Загрузка фото в буфер
        photo = message.photo[-1]
        photo_io = io.BytesIO()
        await bot.download(photo, photo_io)
        img = Image.open(photo_io)
        
        prompt = message.caption if message.caption else "Что изображено на этом фото?"
        
        # Разовый запрос без сохранения в историю для экономии токенов и точности Vision
        response = model.generate_content([prompt, img])
        await message.reply(response.text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Vision processing error: {e}")
        await message.reply("📸 Не удалось проанализировать изображение.")

# --- ВЕБ-ИНТЕРФЕЙС ДЛЯ ПИНГА (HEALTH CHECK) ---

async def handle_ping(request):
    """Обработчик для поддержания жизни сервера на Koyeb"""
    return web.Response(text="UnivoxAI v3.0 [Gemini 2.0 Flash] is Online")

async def main():
    # Настройка веб-сервера aiohttp
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    
    # Запуск веб-сервера на указанном порту
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    logger.info(f"Health check server started on port {PORT}")
    
    # Запуск бота в режиме опроса (polling)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")