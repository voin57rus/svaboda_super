from aiogram import Router, F
from aiogram.types import Message
import sqlite3
import aiohttp
import logging
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

@router.message(F.text & ~F.text.startswith('/'))
async def ai_chat_handler(message: Message):
    # Если это админ — пусть пишет, если нет — молчим (кроме режима AI)
    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS
    
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT ai_chat_active, ai_tokens FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    
    # Реакция только если ai_chat_active == 1 (пользователь вошел в тариф)
    # ИЛИ если это админ
    if not is_admin and (not row or row[0] != 1):
        return
        
    await _ai_ask_openrouter(message, user_id, row[1] if row else 999999)

async def _ai_ask_openrouter(message: Message, user_id: int, tokens: int):
    from database.db_settings import get_ai_api_key
    api_key = get_ai_api_key()
    if not api_key:
        return
        
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "qwen/qwen-2.5-7b-instruct",
                    "messages": [{"role": "user", "content": message.text}],
                    "max_tokens": 512,
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                if 'choices' in data:
                    answer = data['choices'][0]['message']['content']
                    await message.answer(answer)
                    conn = sqlite3.connect('database/vpn_bot.db')
                    conn.execute("UPDATE users SET ai_tokens = MAX(ai_tokens - 1, 0) WHERE telegram_id=?", (user_id,))
                    conn.commit()
                    conn.close()
                else:
                    await message.answer("⚠️ AI не ответил.")
    except Exception as e:
        logger.error(f"AI Error: {e}")
        await message.answer("⚠️ Ошибка связи с AI.")
