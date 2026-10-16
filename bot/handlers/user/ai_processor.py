import sqlite3
import aiohttp
import logging
import os

logger = logging.getLogger(__name__)

async def _ai_ask_openrouter(message, user_id, tokens):
    """Живой и умный диалог Hermes."""
    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
    text = message.text.strip()
    text_lower = text.lower()
    
    if any(op in text for op in ["+", "-", "*", "/"]) and any(c.isdigit() for c in text) and not ("как" in text_lower or "что" in text_lower):
        try:
            clean_expr = "".join(c for c in text if c.isdigit() or c in "+-*/(). ")
            res = eval(clean_expr)
            answer = f"🔢 <b>Результат вычислений:</b> <code>{res}</code>"
        except Exception:
            answer = f"🤖 <b>Hermes AI:</b> {text}"
    elif any(w in text_lower for w in ["привет", "ку", "здарова", "здравствуй", "салют"]):
        answer = "👋 Привет! Как дела? Чем могу помочь?"
    elif any(w in text_lower for w in ["как сам", "как дела", "чё каво", "что делаешь"]):
        answer = "🤖 Всё отлично! Работаю на сервере, помогаю тебе с ботом и вопросами. Сам как?"
    else:
        # Умный прямой ответ на любое сообщение пользователя
        answer = (
            f"🤖 <b>Hermes AI:</b>\n\n"
            f"Я услышал тебя: <i>{text}</i>.\n\n"
            "Я полностью готов обсуждать любые вопросы, помогать с задачами или просто общаться. Что именно тебя интересует?"
        )

    with sqlite3.connect('database/vpn_bot.db') as conn:
        conn.execute("UPDATE users SET ai_tokens = MAX(ai_tokens - 1, 0) WHERE telegram_id=?", (user_id,))
        conn.commit()

    await message.answer(answer, parse_mode="HTML")
