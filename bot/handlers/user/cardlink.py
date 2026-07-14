import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.utils.text import escape_html, safe_edit_or_send
from bot.handlers.user.payments.base import finalize_payment_ui

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == 'pay_cardlink')
async def pay_cardlink_select_tariff(callback: CallbackQuery):
    """Выбор тарифа для оплаты через Cardlink (новый ключ)."""
    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb
    from bot.keyboards.admin import home_only_kb

    from config import ADMIN_IDS
    if callback.from_user.id in ADMIN_IDS:
        from bot.handlers.user.protocol_select import _admin_instant_key
        await callback.message.delete()
        await _admin_instant_key(callback, None, callback.from_user.id, "vless")
        await callback.answer()
        return

    tariffs = get_all_tariffs(include_hidden=False)
    rub_tariffs = [t for t in tariffs if t.get('price_rub') and t['price_rub'] >= 10]
    if not rub_tariffs:
        await safe_edit_or_send(
            callback.message,
            '🔗 <b>Оплата Cardlink</b>\n\n😔 Нет тарифов с ценой в рублях (от 10 ₽).\nОбратитесь к администратору.',
            reply_markup=home_only_kb()
        )
        await callback.answer()
        return
    await safe_edit_or_send(
        callback.message,
        '🔗 <b>Оплата Cardlink (Карта/СБП)</b>\n\nВыберите тариф:\n\n'
        '<i>Оплата банковской картой или СБП через сервис Cardlink.</i>',
        reply_markup=tariff_select_kb(rub_tariffs, is_cardlink=True)
    )
    await callback.answer()


@router.callback_query(F.data.startswith('cardlink_pay:'))
async def cardlink_pay_create(callback: CallbackQuery):
    """Создаёт счёт Cardlink для нового ключа и отправляет QR-фото."""
    from database.requests import (
        get_tariff_by_id, get_user_internal_id, create_pending_order,
        save_cardlink_bill_id
    )
    from bot.services.billing import create_cardlink_payment
    from bot.keyboards.user import cardlink_qr_kb
    from bot.keyboards.admin import home_only_kb

    tariff_id = int(callback.data.split(':')[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return
