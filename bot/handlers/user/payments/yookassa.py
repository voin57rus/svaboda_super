import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from bot.utils.text import escape_html, safe_edit_or_send
from bot.handlers.user.payments.base import finalize_payment_ui

logger = logging.getLogger(__name__)

router = Router()

@router.callback_query(F.data == 'pay_qr')
async def pay_qr_select_tariff(callback: CallbackQuery):
    """Выбор тарифа для QR-оплаты (ЮКасса)."""
    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb
    from bot.keyboards.admin import home_only_kb

    order_id = None
    tariffs = get_all_tariffs(include_hidden=False)
    if not tariffs:
        await safe_edit_or_send(callback.message, '📱 <b>QR-оплата</b>\n\n😔 Нет доступных тарифов.\n\nПопробуйте позже или обратитесь в поддержку.', reply_markup=home_only_kb())
        await callback.answer()
        return
    await safe_edit_or_send(callback.message, '📱 <b>QR-оплата (Карта/СБП)</b>\n\nВыберите тариф:', reply_markup=tariff_select_kb(tariffs, order_id=order_id, is_qr=True))
    await callback.answer()


@router.callback_query(F.data.startswith('qr_pay:'))
async def pay_qr_invoice(callback: CallbackQuery):
    """Создание QR-платежа через ЮКасса для нового ключа."""
    from database.requests import get_tariff_by_id, get_user_internal_id, create_pending_order
    from bot.services.billing import create_yookassa_qr_payment, get_bot_username
    from bot.keyboards.user import qr_qr_kb
    from bot.keyboards.admin import home_only_kb

    try:
        parts = callback.data.split(':')
        tariff_id = int(parts[1])
        order_id = parts[2] if len(parts) > 2 else None

        tariff = get_tariff_by_id(tariff_id)
        if not tariff:
            await callback.answer('❌ Тариф не найден', show_alert=True)
            return

        telegram_id = callback.from_user.id
        user_id = get_user_internal_id(telegram_id)
        if not user_id:
            await callback.answer('❌ Пользователь не найден', show_alert=True)
            return

        if not order_id:
            (_, order_id) = create_pending_order(user_id=user_id, tariff_id=tariff_id, payment_type='yookassa_qr', vpn_key_id=None)

        amount_rub = tariff.get('price_rub', 0)
        if not amount_rub or amount_rub <= 0:
            await callback.answer('❌ Цена не установлена', show_alert=True)
            return

        description = f"VPN ключ: {tariff['name']} ({tariff['duration_days']} дней)"
        bot_name = get_bot_username()

        result = await create_yookassa_qr_payment(
            amount_rub=amount_rub,
            order_id=order_id,
            description=description,
            bot_name=bot_name
        )

        if not result or not result.get('qr_image_url'):
            await safe_edit_or_send(callback.message, '❌ Ошибка создания QR-платежа. Попробуйте позже.', reply_markup=home_only_kb())
            await callback.answer()
            return

        from aiogram.types import BufferedInputFile
        import io
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(result['qr_image_url']) as resp:
                qr_data = await resp.read()

        qr_bytes = io.BytesIO(qr_data)
        await callback.message.answer_photo(
            photo=BufferedInputFile(qr_bytes.read(), filename="yookassa_qr.png"),
            caption=f'📱 <b>QR-оплата ЮКасса</b>\n\nСумма: <b>{amount_rub} ₽</b>\nОписание: {description}\n\nОтсканируйте QR-код для оплаты.',
            reply_markup=qr_qr_kb(order_id=order_id)
        )
        await callback.answer()

    except Exception as e:
        logger.exception(f"QR payment error: {e}")
        await callback.answer('❌ Ошибка создания платежа', show_alert=True)


@router.callback_query(F.data.startswith('pay_cards'))
async def pay_cards_select_tariff(callback: CallbackQuery):
    """Выбор тарифа для оплаты Картой (новый ключ)."""
    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb
    from bot.keyboards.admin import home_only_kb

    order_id = None
    if ':' in callback.data:
        order_id = callback.data.split(':')[1]
    tariffs = get_all_tariffs(include_hidden=False)
    if not tariffs:
        await safe_edit_or_send(callback.message, '💳 <b>Оплата картой</b>\n\n😔 Нет доступных тарифов.\n\nПопробуйте позже или обратитесь в поддержку.', reply_markup=home_only_kb())
        await callback.answer()
        return
    await safe_edit_or_send(callback.message, '💳 <b>Оплата картой</b>\n\nВыберите тариф:', reply_markup=tariff_select_kb(tariffs, order_id=order_id, is_cards=True))
    await callback.answer()


@router.callback_query(F.data.startswith('cards_pay:'))
async def pay_cards_invoice(callback: CallbackQuery, state: FSMContext):
    """Создание инвойса для оплаты Картой (новый ключ)."""
    from aiogram.types import LabeledPrice
    from database.requests import get_tariff_by_id, get_user_internal_id, create_pending_order, update_order_tariff, get_setting
    parts = callback.data.split(':')
    tariff_id = int(parts[1])
    order_id = parts[2] if len(parts) > 2 else None
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return
