from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.db_settings import get_admin_ids, set_admin_ids
import logging

router = Router()
logger = logging.getLogger(__name__)

class AdminManageStates(StatesGroup):
    waiting_for_admin_id = State()

MAIN_ADMIN_ID = 7166305746

def get_admin_list_kb():
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add_new"))
    admin_ids = get_admin_ids()
    for aid in admin_ids:
        if aid != MAIN_ADMIN_ID:
            builder.row(InlineKeyboardButton(text=f"🗑️ Удалить {aid}", callback_data=f"admin_del:{aid}"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel"))
    return builder.as_markup()

def get_admin_list_text():
    text = "🛡️ <b>Список админов:</b>\n\n"
    admin_ids = get_admin_ids()
    for aid in admin_ids:
        status = " (Главный)" if aid == MAIN_ADMIN_ID else ""
        text += f"• <code>{aid}</code>{status}\n"
    return text

@router.callback_query(F.data == "admin_admins_list")
async def show_admins_list(callback: CallbackQuery):
    if callback.from_user.id != MAIN_ADMIN_ID:
        await callback.answer("⛔ Только главный админ может управлять списком", show_alert=True)
        return
    await callback.message.edit_text(get_admin_list_text(), reply_markup=get_admin_list_kb(), parse_mode="HTML")

@router.callback_query(F.data == "admin_manage_admins")
async def handle_admin_manage(callback: CallbackQuery):
    await show_admins_list(callback)

@router.callback_query(F.data == "admin_add_new")
async def ask_admin_id(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != MAIN_ADMIN_ID:
        return
    await callback.message.edit_text("✏️ <b>Отправьте Telegram ID нового админа (числом):</b>", reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="❌ Отмена", callback_data="admin_admins_list")).as_markup(), parse_mode="HTML")
    await state.set_state(AdminManageStates.waiting_for_admin_id)

@router.message(AdminManageStates.waiting_for_admin_id)
async def process_new_admin_id(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите корректный числовой ID.")
        return
    
    new_admin_id = int(message.text)
    admin_ids = get_admin_ids()
    if new_admin_id not in admin_ids:
        admin_ids.append(new_admin_id)
        set_admin_ids(admin_ids)
        await message.answer(f"✅ Админ {new_admin_id} добавлен.")
    else:
        await message.answer("⚠️ Этот ID уже в списке.")
    
    await state.clear()
    await message.answer(get_admin_list_text(), reply_markup=get_admin_list_kb(), parse_mode="HTML")

@router.callback_query(F.data.startswith("admin_del:"))
async def delete_admin(callback: CallbackQuery):
    if callback.from_user.id != MAIN_ADMIN_ID:
        return
    aid = int(callback.data.split(":")[1])
    admin_ids = get_admin_ids()
    if aid in admin_ids and aid != MAIN_ADMIN_ID:
        admin_ids.remove(aid)
        set_admin_ids(admin_ids)
        await callback.answer(f"🗑️ Админ {aid} удален.")
    await callback.message.edit_text(get_admin_list_text(), reply_markup=get_admin_list_kb(), parse_mode="HTML")
