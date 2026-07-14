import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.utils.text import escape_html, safe_edit_or_send
from database.requests import get_all_tariffs, get_tariff_by_id, get_key_details_for_user
from bot.keyboards.user import tariff_select_kb, renew_tariff_select_kb
from bot.keyboards.admin import home_only_kb

logger = logging.getLogger(__name__)

router = Router()

@router.callback_query(F.data.startswith('demo_tariffs'))
async def demo_tariffs_handler(callback: CallbackQuery):
    """Выбор тарифа для демонстрационной оплаты (Новый ключ)."""
    from config import ADMIN_IDS
    if callback.from_user.id in ADMIN_IDS:
        from bot.handlers.user.protocol_select import _admin_instant_key
        await callback.message.delete()
        await _admin_instant_key(callback, None, callback.from_user.id, "vless")
        await callback.answer()
        return

    order_id = None
    if ':' in callback.data:
        order_id = callback.data.split(':')[1]
        
    tariffs = get_all_tariffs(include_hidden=False)
    
    await safe_edit_or_send(
        callback.message, 
        '🏦 <b>Демо оплата (РФ карта)</b>\n\nВыберите тариф:\n\n<i>Этот способ используется только для демонстрации интерфейса оплаты.</i>', 
        reply_markup=tariff_select_kb(tariffs, order_id=order_id, is_demo=True)
    )
    await callback.answer()


@router.callback_query(F.data.startswith('renew_demo_tariffs:'))
async def renew_demo_tariffs_handler(callback: CallbackQuery):
    """Выбор тарифа для демонстрационной оплаты (Продление)."""
    parts = callback.data.split(':')
    key_id = int(parts[1])
    order_id = parts[2] if len(parts) > 2 else None
    
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer('❌ Ключ не найден', show_alert=True)
        return
        
    from bot.utils.groups import get_tariffs_for_renewal
    tariffs = get_tariffs_for_renewal(key.get('tariff_id', 0))
    if not tariffs:
        await callback.answer('Нет доступных тарифов', show_alert=True)
        return
        
    await safe_edit_or_send(
        callback.message, 
        f"🏦 <b>Демо оплата (РФ карта)</b>\n\n🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n\nВыберите тариф для продления:", 
        reply_markup=renew_tariff_select_kb(tariffs, key_id, order_id=order_id, is_demo=True)
    )
    await callback.answer()


@router.callback_query(F.data.startswith('demo_pay:'))
async def demo_pay_handler(callback: CallbackQuery):
    """Показ демонстрационного экрана оплаты (Новый ключ)."""
    parts = callback.data.split(':')
    tariff_id = int(parts[1])
    
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return
