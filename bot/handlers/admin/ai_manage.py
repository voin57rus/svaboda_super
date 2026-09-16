from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database.requests import get_setting, set_setting
import logging

router = Router()
logger = logging.getLogger(__name__)

def get_ai_menu_kb(ai_enabled: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    status_text = "✅ AI Включен" if ai_enabled else "❌ AI Выключен"
    builder.row(InlineKeyboardButton(text=status_text, callback_data="ai_toggle"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

@router.callback_query(F.data == "admin_manage_ai")
async def show_ai_manage(callback: CallbackQuery):
    ai_enabled = get_setting('ai_enabled', '0') == '1'
    await callback.message.edit_text("🤖 <b>Управление AI доступом:</b>", reply_markup=get_ai_menu_kb(ai_enabled), parse_mode="HTML")

@router.callback_query(F.data == "ai_toggle")
async def toggle_ai(callback: CallbackQuery):
    current = get_setting('ai_enabled', '0') == '1'
    new_val = '0' if current else '1'
    set_setting('ai_enabled', new_val)
    ai_enabled = new_val == '1'
    await callback.answer(f"AI {'включен' if ai_enabled else 'выключен'}")
    await callback.message.edit_reply_markup(reply_markup=get_ai_menu_kb(ai_enabled))
