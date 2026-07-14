"""
Обработчик оплаты WireGuard / AmneziaWG через Telegram Stars.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, LabeledPrice, PreCheckoutQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext

from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

# Курс USD → Stars (примерно 1 USD = 100 Stars)
USD_TO_STARS = 100


@router.callback_query(F.data.startswith("wg_pay:"))
async def wg_pay_handler(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик нажатия кнопки оплаты WG тарифа.
    Формат callback: wg_pay:{tariff_id}:{order_id}
    """
    from database.requests import (
        get_tariff_by_id, get_user_internal_id, create_pending_order
    )

    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer("❌ Ошибка формата данных", show_alert=True)
        return

    tariff_id = int(parts[1])
    order_id = parts[2] if len(parts) > 2 else None

    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer("❌ Тариф не найден", show_alert=True)
        return

    # Получаем протокол из FSM state
    state_data = await state.get_data()
    protocol = state_data.get("protocol", "wireguard")

    days = tariff['duration_days']
    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer("❌ Ошибка пользователя", show_alert=True)
        return

    if order_id:
        from database.requests import update_order_tariff, update_payment_type
        update_order_tariff(order_id, tariff_id, payment_type='stars')
    else:
        (_, order_id) = create_pending_order(
            user_id=user_id, tariff_id=tariff_id,
            payment_type='stars', vpn_key_id=None, protocol=protocol
        )

    try:
        bot_info = await callback.bot.get_me()
        bot_name = bot_info.first_name
        price_stars = tariff['price_stars']
        await callback.message.answer_invoice(
            title=bot_name,
            description=f"Оплата тарифа «{tariff['name']}» ({days} дн.).",
            payload=order_id,
            currency='XTR',
            prices=[LabeledPrice(label=f"Тариф {tariff['name']}", amount=price_stars)],
            reply_markup=InlineKeyboardBuilder().row(
                InlineKeyboardButton(text=f'⭐️ Оплатить {price_stars} XTR', pay=True)
            ).row(
                InlineKeyboardButton(text='❌ Отмена', callback_data='buy_key')
            ).as_markup()
        )
    except Exception as e:
        logger.error(f'Ошибка при выставлении счета Stars (WG): {e}')
        await callback.answer('❌ Произошла ошибка при создании счета', show_alert=True)
        return
    await callback.message.delete()
    await callback.answer()
