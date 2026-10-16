"""
Модуль интеграции AI-ассистента (Gemini через OpenRouter) с авто-созданием пользователя в БД и устранением ошибки User not found.
"""
from aiogram import Router, F
from aiogram.types import Message
import aiohttp
import logging
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

logger = logging.getLogger(__name__)
router = Router()

GEMINI_MODELS = [
    "google/gemini-2.5-flash",
    "google/gemini-flash-1.5",
    "google/gemini-pro-1.5",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3.5-super-vl:free"
]

user_ai_modes = {}

def ensure_user_in_db(user_id: int, username: str | None = None):
    try:
        conn = sqlite3.connect('database/vpn_bot.db')
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE telegram_id=?", (user_id,))
        row = c.fetchone()
        uname = username if username else f"user_{user_id}"
        if not row:
            c.execute(
                "INSERT INTO users (telegram_id, username, ai_tokens, ai_chat_active) VALUES (?, ?, 999999, 0)",
                (user_id, uname)
            )
        else:
            c.execute("UPDATE users SET ai_tokens = 999999 WHERE telegram_id=?", (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"DB ensure user error: {e}")

@router.message(F.text.in_({"🤖 AI Стандарт", "🤖 Стандарт", "🤖 AI Стандарт ✓"}))
async def set_std(message: Message):
    if not message.from_user:
        return
    ensure_user_in_db(message.from_user.id, message.from_user.username)
    user_ai_modes[message.from_user.id] = "Стандарт"
    await message.answer(
        "🤖 <b>AI-ассистент</b>\n\n"
        "✅ Режим: <b>Стандарт</b> (Gemini)\n"
        "💰 Токенов: 999,999\n\n"
        "Напишите сообщение — AI ответит.",
        parse_mode="HTML"
    )

@router.message(F.text.in_({"🤖 AI Премиум", "💎 Премиум", "🤖 AI Премиум ✓"}))
async def set_prem(message: Message):
    if not message.from_user:
        return
    ensure_user_in_db(message.from_user.id, message.from_user.username)
    user_ai_modes[message.from_user.id] = "Премиум"
    await message.answer(
        "🤖 <b>AI-ассистент</b>\n\n"
        "✅ Режим: <b>Премиум</b> (Gemini)\n"
        "💰 Токенов: 999,999\n\n"
        "Напишите сообщение — AI ответит.",
        parse_mode="HTML"
    )

@router.message(F.text.in_({"🤖 AI VIP", "👑 VIP", "🤖 AI VIP ✓"}))
async def set_vip(message: Message):
    if not message.from_user:
        return
    ensure_user_in_db(message.from_user.id, message.from_user.username)
    user_ai_modes[message.from_user.id] = "VIP"
    await message.answer(
        "🤖 <b>AI-ассистент</b>\n\n"
        "✅ Режим: <b>VIP</b> (Gemini)\n"
        "💰 Токенов: 999,999\n\n"
        "Напишите сообщение — AI ответит.",
        parse_mode="HTML"
    )

@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_({
    "🤖 AI Стандарт", "🤖 AI Премиум", "🤖 AI VIP",
    "🤖 Стандарт", "💎 Премиум", "👑 VIP",
    "🔑 Мои ключи", "💳 Купить ключ", "🎁 Пробная подписка", "📢 мой канал", 
    "❓ Справка", "🔍 Смотреть ID", "⚙️ Админ-панель", "🏡 Главное меню"
}))
async def handle_ai_query(message: Message):
    if not message.from_user or not message.text or not message.bot:
        return
    user_id = message.from_user.id
    ensure_user_in_db(user_id, message.from_user.username)
    mode = user_ai_modes.get(user_id, "Стандарт")
    
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    processing_msg = await message.answer(f"⏳ Думаю над ответом (Gemini {mode})...")
    
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "HTTP-Referer": "https://t.me/ai_bot",
        "X-Title": "AI Telegram Bot",
        "Content-Type": "application/json"
    }
    
    answer = None
    async with aiohttp.ClientSession() as session:
        for model in GEMINI_MODELS:
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are Svaboda, an intelligent AI assistant powered by Gemini. You are helpful, knowledgeable, and direct. You assist users with answering questions, writing and editing code, analyzing information, creative work, and executing actions. Communicate clearly, admit uncertainty when appropriate, and prioritize being genuinely useful over being verbose."
                    },
                    {
                        "role": "user",
                        "content": message.text
                    }
                ]
            }
            try:
                async with session.post(url, json=payload, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "choices" in data and len(data["choices"]) > 0:
                            answer = data["choices"][0]["message"]["content"]
                            break
                    else:
                        resp_text = await resp.text()
                        logger.warning(f"Model {model} failed with status {resp.status}: {resp_text}")
            except Exception as e:
                logger.warning(f"Exception with model {model}: {e}")
                continue
                
    if answer:
        try:
            await processing_msg.edit_text(answer, parse_mode="Markdown")
        except Exception:
            await processing_msg.edit_text(answer)
    else:
        await processing_msg.edit_text("❌ Модели Gemini временно заняты. Повторите попытку через пару секунд.")
