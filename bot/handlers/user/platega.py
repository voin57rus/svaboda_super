import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from bot.utils.text import escape_html, safe_edit_or_send
from bot.handlers.user.payments.base import finalize_payment_ui

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == 'pay_platega')
async def pay_platega_select_tariff(callback: CallbackQuery):
    """Выбор тарифа для оплаты через Platega (новый ключ)."""
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
            '💸 <b>Оплата Platega</b>\n\n😔 Нет тарифов с ценой в рублях (от 10 ₽).\nОбратитесь к администратору.',
            reply_markup=home_only_kb()
        )
        await callback.answer()
        return
    await safe_edit_or_send(
        callback.message,
        '💸 <b>Оплата Platega (СБП)</b>\n\nВыберите тариф:\n\n<i>Оплата через Platega по Системе Быстрых Платежей.</i>',
        reply_markup=tariff_select_kb(rub_tariffs, is_platega=True)
    )
    await callback.answer()


@router.callback_query(F.data.startswith('platega_pay:'))
async def platega_pay_create(callback: CallbackQuery):
    """Создаёт транзакцию Platega для нового ключа и отправляет QR-фото."""
    from database.requests import (
        get_tariff_by_id, get_user_internal_id, create_pending_order,
        save_platega_transaction_id
    )
    from bot.services.billing import create_platega_payment
    from bot.keyboards.user import platega_qr_kb
    from bot.keyboards.admin import home_only_kb

    tariff_id = int(callback.data.split(':')[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return
