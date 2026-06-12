"""
Обработчик оплаты WireGuard / AmneziaWG через Telegram Stars.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, LabeledPrice, PreCheckoutQuery
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

    telegram_id = callback.from_user.id
    user_id = get_user_internal_id(telegram_id)

    if not user_id:
        await callback.answer("❌ Пользователь не найден", show_alert=True)
        return

    # Получаем протокол из FSM state
    state_data = await state.get_data()
    protocol = state_data.get("protocol", "wireguard")

    # Создаём/обновляем ордер
    if not order_id:
        (_, order_id) = create_pending_order(
            user_id=user_id,
            tariff_id=tariff_id,
            payment_type="stars",
            vpn_key_id=None,
            protocol=protocol
        )

    # Рассчитываем цену в Stars
    price_usd = tariff['price_cents'] / 100
    stars_amount = max(1, int(price_usd * USD_TO_STARS))

    protocol_name = "AmneziaWG" if protocol == "amnezia" else "WireGuard"
    emoji = "🟠" if protocol == "amnezia" else "🟢"

    # Отправляем инвойс Stars
    prices = [LabeledPrice(label=f"{protocol_name} — {tariff['name']}", amount=stars_amount)]

    await callback.message.answer_invoice(
        title=f"🔑 {protocol_name} — {tariff['name']}",
        description=(
            f"VPN ключ {protocol_name}\n"
            f"Тариф: {tariff['name']}\n"
            f"Срок: {tariff.get('duration_days', 30)} дней"
        ),
        payload=f"wg:{tariff_id}:{order_id}",
        currency="XTR",  # Telegram Stars
        prices=prices,
    )
    await callback.answer()


@router.pre_checkout_query()
async def wg_pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    """Подтверждаем pre-checkout для WG платежей."""
    try:
        await pre_checkout_query.answer(ok=True)
    except Exception as e:
        logger.error(f"Pre-checkout error: {e}")
        await pre_checkout_query.answer(ok=False, error_message="Ошибка обработки платежа")


@router.callback_query(F.data.startswith("wg_stars_pay:"))
async def wg_stars_pay_handler(callback: CallbackQuery, state: FSMContext):
    """
    Альтернативный обработчик — оплата Stars напрямую (без инвойса).
    Формат: wg_stars_pay:{tariff_id}
    """
    tariff_id = int(callback.data.split(":")[1])
    await wg_pay_handler(callback, state)
