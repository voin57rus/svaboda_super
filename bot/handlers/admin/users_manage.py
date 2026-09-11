import logging
import uuid
from datetime import datetime
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, KeyboardButtonRequestUsers, UsersShared, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from config import ADMIN_IDS
from database.requests import get_users_stats, get_all_users_paginated, get_user_by_telegram_id, toggle_user_ban, get_user_vpn_keys, get_user_payments_stats, get_vpn_key_by_id, extend_vpn_key, create_vpn_key_admin, get_active_servers, get_all_tariffs, get_user_balance, get_user_referral_coefficient, add_to_balance, deduct_from_balance, set_user_referral_coefficient
from bot.utils.admin import is_admin
from bot.utils.text import escape_html, safe_edit_or_send
from bot.utils.panel_email import get_panel_email_prefix
from bot.states.admin_states import AdminStates
from bot.keyboards.admin import users_menu_kb, users_list_kb, user_view_kb, user_ban_confirm_kb, key_view_kb, add_key_server_kb, add_key_inbound_kb, add_key_step_kb, add_key_confirm_kb, users_input_cancel_kb, key_action_cancel_kb, back_and_home_kb, home_only_kb
from bot.services.vpn_api import get_client_from_server_data, VPNAPIError, format_traffic

logger = logging.getLogger(__name__)

router = Router()
USERS_PER_PAGE = 20

def format_user_display(user: dict) -> str:
    if user.get('username'): return f"@{user['username']}"
    return f"ID: {user['telegram_id']}"

@router.callback_query(F.data.startswith('admin_user_view:'))
async def show_user_view_callback(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    await _show_user_view_edit(callback, state, int(callback.data.split(':')[1]))

async def _show_user_view(message: Message, state: FSMContext, telegram_id: int):
    user = get_user_by_telegram_id(telegram_id)
    if not user: return
    await state.set_state(AdminStates.user_view)
    await state.update_data(current_user_telegram_id=telegram_id)
    (text, keyboard) = _format_user_card(user)
    await safe_edit_or_send(message, text, reply_markup=keyboard, force_new=True)

async def _show_user_view_edit(callback: CallbackQuery, state: FSMContext, telegram_id: int):
    user = get_user_by_telegram_id(telegram_id)
    if not user: return
    await state.set_state(AdminStates.user_view)
    await state.update_data(current_user_telegram_id=telegram_id)
    (text, keyboard) = _format_user_card(user)
    await safe_edit_or_send(callback.message, text, reply_markup=keyboard)
    await callback.answer()

def _format_user_card(user: dict) -> tuple[str, any]:
    telegram_id = user['telegram_id']
    username = user.get('username')
    is_banned = bool(user.get('is_banned'))
    created_at = user.get('created_at', 'неизвестно')
    balance_cents = get_user_balance(user['id'])
    referral_coefficient = get_user_referral_coefficient(user['id'])
    vpn_keys = get_user_vpn_keys(user['id'])
    lines = [('🚫 <b>ПОЛЬЗОВАТЕЛЬ ЗАБАНЕН</b>' if is_banned else ''), f'👤 Username: @{escape_html(username)}' if username else '👤 Username: _не указан_', f'📱 Telegram ID: <code>{telegram_id}</code>', f'📧 E-mail: <code>{get_panel_email_prefix(user)}</code>', f'📅 Зарегистрирован: {created_at}', f'💰 Баланс: <b>{int(balance_cents)/100:.2f} ₽</b>', f'📊 Реф. коэф: <b>{referral_coefficient}x</b>']
    lines.append('\n🔑 <b>VPN-ключи:</b>')
    if vpn_keys:
        for k in vpn_keys: lines.append(f'  🔑 {k.get("custom_name") or "Ключ"}')
    else: lines.append('  _Нет ключей_')
    keyboard = user_view_kb(telegram_id, vpn_keys, is_banned, balance_cents, referral_coefficient)
    keyboard.inline_keyboard.insert(0, [InlineKeyboardButton(text='🗑️ Удалить навсегда', callback_data=f'admin_user_delete_ask:{telegram_id}')])
    return ('\n'.join(lines), keyboard)

@router.callback_query(F.data.startswith('admin_user_toggle_ban:'))
async def request_ban_confirmation(callback: CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split(':')[1])
    user = get_user_by_telegram_id(telegram_id)
    if not user: return
    await safe_edit_or_send(callback.message, "⚠️ Подтвердите действие", reply_markup=user_ban_confirm_kb(telegram_id, bool(user.get('is_banned'))))
    await callback.answer()

@router.callback_query(F.data.startswith('admin_user_ban_confirm:'))
async def confirm_ban_toggle(callback: CallbackQuery, state: FSMContext):
    telegram_id = int(callback.data.split(':')[1])
    toggle_user_ban(telegram_id)
    await _show_user_view_edit(callback, state, telegram_id)

@router.callback_query(F.data.startswith('admin_user_delete_ask:'))
async def ask_delete_user(callback: CallbackQuery):
    tid = int(callback.data.split(':')[1])
    await safe_edit_or_send(callback.message, f"⚠️ <b>ВНИМАНИЕ!</b> Удалить пользователя {tid} навсегда?", reply_markup=InlineKeyboardBuilder().row(InlineKeyboardButton(text="🗑️ УДАЛИТЬ", callback_data=f"admin_user_delete_confirm:{tid}"), InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_user_view:{tid}")).as_markup())
    await callback.answer()

@router.callback_query(F.data.startswith('admin_user_delete_confirm:'))
async def confirm_delete_user(callback: CallbackQuery):
    tid = int(callback.data.split(':')[1])
    try:
        from database.requests import get_user_by_telegram_id, get_user_vpn_keys
        from bot.services.panels.wireguard_service import delete_peer
        import sqlite3
        import os
        user = get_user_by_telegram_id(tid)
        if user:
            for key in get_user_vpn_keys(user['id']): await delete_peer(key.get('public_key', ''))
            conn = sqlite3.connect('database/vpn_bot.db')
            conn.execute('DELETE FROM users WHERE id = ?', (user['id'],))
            conn.commit()
            conn.close()
        await callback.answer("✅ Пользователь удален", show_alert=True)
        await callback.message.delete()
    except Exception as e:
        await callback.answer(f"❌ Ошибка: {str(e)}", show_alert=True)
        logger.error(f"Error deleting user {tid}: {e}")
