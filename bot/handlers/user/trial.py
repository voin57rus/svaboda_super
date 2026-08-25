import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from bot.utils.text import safe_edit_or_send
from database.requests import get_all_tariffs, get_trial_tariff_id, is_trial_enabled, has_used_trial, get_or_create_user, mark_trial_used, create_initial_vpn_key, create_pending_order, complete_order, get_tariff_by_id
from bot.handlers.user.payments.keys_config import start_new_key_config
from bot.utils.page_renderer import render_page

logger = logging.getLogger(__name__)

router = Router()


async def _get_trial_tariffs():
    """Получает тариф для пробной подписки."""
    tariff_id = get_trial_tariff_id()
    if not tariff_id:
        return []
    tariff = get_tariff_by_id(tariff_id)
    if not tariff or not tariff.get('is_active'):
        return []
    return [tariff]


def _build_trial_tariff_text(tariffs):
    """Строит текст со списком тарифов для пробного периода."""
    from bot.utils.text import escape_html
    protocol_emoji = {
        'vless': '🔵',
        'wireguard': '🟢',
        'amnezia': '🟠',
        'xray': '🟣',
    }
    protocol_names = {
        'vless': 'VLESS',
        'wireguard': 'WireGuard',
        'amnezia': 'AmneziaWG',
        'xray': 'Xray (Vless+WS+TLS)',
    }
    protocol_descriptions = {
        'vless': 'быстрый и надёжный VPN',
        'wireguard': 'быстрый и надёжный VPN',
        'amnezia': 'обходит DPI и блокировки',
        'xray': 'маскировка под HTTPS',
    }
    
    lines = ['🎁 <b>Пробная подписка</b>\n\nВыберите протокол для пробного периода:']
    for tariff in tariffs:
        protocol = tariff.get('protocol', 'vless').lower()
        proto_emoji = protocol_emoji.get(protocol, '🔵')
        proto_name = protocol_names.get(protocol, protocol.upper())
        proto_desc = protocol_descriptions.get(protocol, '')
        lines.append(f"• {proto_emoji} <b>{escape_html(tariff['name'])}</b> — {proto_name} — {proto_desc}")
    return '\n'.join(lines)


def _build_trial_tariff_kb(tariffs):
    """Строит клавиатуру выбора тарифа для пробной подписки."""
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton
    
    builder = InlineKeyboardBuilder()
    for tariff in tariffs:
        protocol = tariff.get('protocol', 'vless').lower()
        proto_emoji = {'vless': '🔵', 'wireguard': '🟢', 'amnezia': '🟠', 'xray': '🟣'}.get(protocol, '🔵')
        proto_name = {'vless': 'VLESS', 'wireguard': 'WireGuard', 'amnezia': 'AmneziaWG', 'xray': 'Xray'}.get(protocol, protocol.upper())
        
        builder.row(InlineKeyboardButton(
            text=f"{proto_emoji} {tariff['name']} — {proto_name}",
            callback_data=f"trial_select:{tariff['id']}"
        ))
    builder.row(InlineKeyboardButton(text="⬅️ На главную", callback_data="start"))
    return builder.as_markup()


@router.callback_query(F.data == 'trial_subscription')
async def show_trial_subscription(callback: CallbackQuery):
    """Показывает выбор тарифов для пробной подписки."""
    if not is_trial_enabled():
        await callback.answer('❌ Пробная подписка недоступна', show_alert=True)
        return
    
    user_id = callback.from_user.id
    if has_used_trial(user_id):
        await callback.answer('ℹ️ Вы уже использовали пробный период', show_alert=True)
        return
    
    tariffs = await _get_trial_tariffs()
    
    if not tariffs:
        await callback.answer('❌ Нет доступных тарифов для пробного периода', show_alert=True)
        return
    
    text = _build_trial_tariff_text(tariffs)
    kb = _build_trial_tariff_kb(tariffs)
    
    await safe_edit_or_send(callback.message, text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith('trial_select:'))
async def select_trial_tariff(callback: CallbackQuery, state: FSMContext):
    """Обрабатывает выбор тарифа для пробной подписки и активирует её."""
    tariff_id = int(callback.data.split(':')[1])
    user_id = callback.from_user.id
    
    if has_used_trial(user_id):
        await callback.answer('ℹ️ Вы уже использовали пробный период', show_alert=True)
        return
    
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return
    
    # Создаём пользователя если нет
    (user, _) = get_or_create_user(user_id, callback.from_user.username)
    internal_user_id = user['id']
    
    # Помечаем пробный период как использованный
    mark_trial_used(internal_user_id)
    logger.info(f'Пользователь {user_id} активировал пробный период (тариф ID={tariff_id})')
    
    # Создаём VPN ключ
    duration_days = tariff['duration_days']
    traffic_limit_bytes = (tariff.get('traffic_limit_gb', 0) or 0) * 1024 ** 3
    key_id = create_initial_vpn_key(internal_user_id, tariff_id, duration_days, traffic_limit=traffic_limit_bytes)
    
    # Создаём заказ
    (_, order_id) = create_pending_order(
        user_id=internal_user_id, 
        tariff_id=tariff_id, 
        payment_type='trial', 
        vpn_key_id=key_id
    )
    complete_order(order_id)
    
    await state.update_data(new_key_order_id=order_id, new_key_id=key_id)
    
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    
    # Переходим к конфигурации нового ключа
    await start_new_key_config(callback.message, state, order_id, key_id)


@router.callback_query(F.data == 'trial_activate')
async def activate_trial_subscription(callback: CallbackQuery, state: FSMContext):
    """Старый обработчик - оставляем для совместимости, но перенаправляем на выбор."""
    # Если тариф уже выбран в настройках - активируем его
    tariff_id = get_trial_tariff_id()
    if tariff_id:
        # Эмулируем выбор тарифа
        callback.data = f"trial_select:{tariff_id}"
        await select_trial_tariff(callback, state)
    else:
        await callback.answer('❌ Тариф не настроен', show_alert=True)