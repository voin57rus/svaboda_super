import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from bot.states.admin_states import AdminStates
from bot.utils.admin import is_admin
from bot.utils.text import escape_html, safe_edit_or_send
from database.requests import get_trial_tariff_id, get_all_tariffs, is_trial_enabled, get_trial_tariff_ids
from bot.keyboards.admin import trial_settings_kb

logger = logging.getLogger(__name__)
router = Router()

async def show_trial_menu(callback: CallbackQuery):
    enabled = is_trial_enabled()
    selected_ids = get_trial_tariff_ids()
    
    # АВТО-ОЧИСТКА: если ID в базе есть, а тарифа больше нет - удаляем этот ID из базы
    all_existing_ids = [t.get('id') for t in get_all_tariffs(include_hidden=True) if isinstance(t, dict)]
    if any(tid not in all_existing_ids for tid in selected_ids):
        selected_ids = [tid for tid in selected_ids if tid in all_existing_ids]
        from database.requests import set_setting
        set_setting('trial_tariff_ids', ','.join(map(str, selected_ids)))

    # Получаем список тарифов (исключая Admin Tariff)
    tariffs = [t for t in get_all_tariffs(include_hidden=True) if isinstance(t, dict) and t.get('name') != 'Admin Tariff']
    
    lines = []
    protocol_emoji = {'vless': '🔵', 'wireguard': '🟢', 'amnezia': '🟠', 'xray': '🟣'}
    
    for t in tariffs:
        proto = t.get('protocol', 'vless').lower()
        emoji = protocol_emoji.get(proto, '🔵')
        status = '🟢' if t.get('is_active') else '🔴'
        checkbox = '☑️' if t.get('id') in selected_ids else '☐'
        lines.append(f"{emoji} {status} {checkbox} {t.get('name')} ({t.get('duration_days')} дн.)")

    status_text = "✅ Включена" if enabled else "❌ Выключена"
    text = (
        "🎁 <b>Пробная подписка</b>\n\n"
        "Управление функцией пробного доступа для новых пользователей.\n\n"
        f"📌 <b>Статус:</b> {status_text}\n\n"
        "Выберите тарифы для пробного периода:\n" + ("\n".join(lines) if lines else "Нет тарифов") + "\n\n"
        "❓ <b>Как работает:</b>\n"
        "• Кнопка появляется на главной у новых пользователей.\n"
        "• При активации выдаются ключи по выбранным тарифам."
    )
    # Показываем меню настроек пробной подписки
    await safe_edit_or_send(callback.message, text, reply_markup=trial_settings_kb(enabled, selected_ids, tariffs))
    await callback.answer()

@router.callback_query(F.data == "admin_trial")
async def admin_trial_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    await show_trial_menu(callback)

@router.callback_query(F.data == "admin_trial_toggle")
async def admin_trial_toggle(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    from database.requests import set_setting, is_trial_enabled
    set_setting('trial_enabled', '0' if is_trial_enabled() else '1')
    await show_trial_menu(callback)

@router.callback_query(F.data == "admin_trial_edit_text")
async def admin_trial_edit_text_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return
    from bot.handlers.admin.message_editor import show_message_editor
    await show_message_editor(callback.message, state, key='trial', back_callback='admin_trial', allowed_types=['text', 'photo'])
    await callback.answer()

@router.callback_query(F.data == "admin_trial_select_tariff")
async def admin_trial_select_tariff(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    from bot.keyboards.admin import trial_tariff_select_kb
    all_tariffs = [t for t in get_all_tariffs(include_hidden=True) if isinstance(t, dict) and t.get('name') != 'Admin Tariff']
    await safe_edit_or_send(callback.message, "📋 <b>Выбор тарифов</b>\n\nВыберите:", reply_markup=trial_tariff_select_kb(all_tariffs, get_trial_tariff_ids()))
    await callback.answer()

@router.callback_query(F.data.startswith("admin_trial_set_tariff:"))
async def admin_trial_set_tariff(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return
    from database.requests import set_setting, get_trial_tariff_ids
    tariff_id = int(callback.data.split(":")[1])
    selected = get_trial_tariff_ids()
    # Очистка от удаленных тарифов
    from database.requests import get_tariff_by_id
    selected = [tid for tid in selected if get_tariff_by_id(tid)]
    if tariff_id in selected: selected.remove(tariff_id)
    else: selected.append(tariff_id)
    set_setting('trial_tariff_ids', ','.join(map(str, selected)))
    await show_trial_menu(callback)
