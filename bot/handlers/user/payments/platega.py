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

    try:
        tariff_id = int(callback.data.split(':')[1])
        tariff = get_tariff_by_id(tariff_id)
        if not tariff:
            await callback.answer('❌ Тариф не найден', show_alert=True)
            return

        telegram_id = callback.from_user.id
        user_id = get_user_internal_id(telegram_id)
        if not user_id:
            await callback.answer('❌ Пользователь не найден', show_alert=True)
            return

        order_id = None
        if user_id:
            (_, order_id) = create_pending_order(
                user_id=user_id, tariff_id=tariff_id,
                payment_type='platega', vpn_key_id=None
            )

        amount_rub = tariff['price_rub']
        description = f"VPN ключ: {tariff['name']} ({tariff['duration_days']} дней)"

        from bot.services.billing import get_bot_username
        bot_name = get_bot_username()

        result = await create_platega_payment(
            amount_rub=amount_rub,
            order_id=order_id or '',
            description=description,
            bot_name=bot_name
        )

        if not result or not result.get('qr_image_data'):
            await safe_edit_or_send(
                callback.message,
                '❌ Ошибка создания платежа Platega.\nПопробуйте позже.',
                reply_markup=home_only_kb()
            )
            await callback.answer()
            return

        await save_platega_transaction_id(order_id, result['platega_transaction_id'])

        from aiogram.types import BufferedInputFile
        import io

        qr_bytes = io.BytesIO(result['qr_image_data'])
        await callback.message.answer_photo(
            photo=BufferedInputFile(qr_bytes.read(), filename="platega_qr.png"),
            caption=f'💸 <b>Оплата Platega</b>\n\nСумма: <b>{amount_rub} ₽</b>\nОписание: {description}\n\nОтсканируйте QR-код для оплаты через СБП.',
            reply_markup=platega_qr_kb(order_id=order_id or '')
        )
        await callback.answer()

    except ValueError as e:
        logger.error(f"Platega payment error: {e}")
        await callback.answer('❌ Ошибка создания платежа', show_alert=True)
    except Exception as e:
        logger.exception(f"Platega unexpected error: {e}")
        await callback.answer('❌ Произошла ошибка', show_alert=True)
