"""
Выбор протокола VPN перед покупкой ключа.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.utils.text import safe_edit_or_send
from bot.keyboards.user import protocol_select_kb

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "buy_key")
async def buy_key_handler(callback: CallbackQuery, state: FSMContext):
    """Показывает выбор протокола VPN вместо прямого выбора оплаты."""
    await state.clear()
    await safe_edit_or_send(
        callback.message,
        "🔐 <b>Выберите протокол VPN</b>\n\n"
        "🔵 <b>VLESS + Reality</b> — самый современный, обходит блокировки\n"
        "🟠 <b>AmneziaWG</b> — обходит DPI и блокировки\n"
        "🟣 <b>Xray (VLESS+WS+TLS)</b> — маскировка под HTTPS",
        reply_markup=protocol_select_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "protocol_vless")
async def protocol_vless_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал VLESS — показываем стандартную страницу покупки."""
    from database.requests import (
        is_crypto_configured, is_stars_enabled, is_cards_enabled,
        is_yookassa_qr_configured, is_wata_configured, is_platega_configured,
        is_cardlink_configured, is_demo_payment_enabled,
        get_user_internal_id, create_pending_order,
    )
    from bot.utils.page_renderer import render_page
    from bot.keyboards.admin import home_only_kb

    telegram_id = callback.from_user.id
    crypto_configured = is_crypto_configured()
    stars_enabled = is_stars_enabled()
    cards_enabled = is_cards_enabled()
    yookassa_qr = is_yookassa_qr_configured()
    wata_enabled = is_wata_configured()
    platega_enabled = is_platega_configured()
    cardlink_enabled = is_cardlink_configured()
    demo_enabled = is_demo_payment_enabled()

    if not any([crypto_configured, stars_enabled, cards_enabled, yookassa_qr,
                wata_enabled, platega_enabled, cardlink_enabled, demo_enabled]):
        await safe_edit_or_send(
            callback.message,
            '💳 <b>Купить ключ</b>\n\n😔 К сожалению, сейчас оплата недоступна.\n\nПопробуйте позже или обратитесь в поддержку.',
            reply_markup=home_only_kb()
        )
        await callback.answer()
        return

    user_id = get_user_internal_id(telegram_id)
    order_id = None
    if user_id:
        (_, order_id) = create_pending_order(user_id=user_id, tariff_id=None,
                                              payment_type=None, vpn_key_id=None)

    await state.update_data(protocol="vless")

    context = {
        'order_id': order_id,
        'telegram_id': telegram_id,
    }
    await render_page(callback, page_key='prepayment', context=context)
    await callback.answer()


@router.callback_query(F.data == "protocol_amnezia")
async def protocol_amnezia_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал AmneziaWG — показываем тарифы."""
    await _show_wg_tariffs(callback, state, amnezia=True)


@router.callback_query(F.data == "protocol_xray")
async def protocol_xray_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал Xray — показываем стандартную страницу покупки."""
    # Xray использует тот же flow что и VLESS
    await protocol_vless_handler(callback, state)


async def _show_wg_tariffs(callback: CallbackQuery, state: FSMContext, amnezia: bool):
    """Показывает тарифы для WireGuard/AmneziaWG."""
    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb

    tariffs = get_all_tariffs()
    if not tariffs:
        await safe_edit_or_send(
            callback.message,
            "😔 К сожалению, тарифы пока не настроены.\nОбратитесь в поддержку.",
            reply_markup=protocol_select_kb()
        )
        await callback.answer()
        return

    protocol = "amnezia" if amnezia else "wireguard"
    await state.update_data(protocol=protocol)

    emoji = "🟠" if amnezia else "🟢"
    name = "AmneziaWG" if amnezia else "WireGuard"

    await safe_edit_or_send(
        callback.message,
        f"{emoji} <b>{name}</b>\n\nВыберите тариф:",
        reply_markup=tariff_select_kb(
            tariffs,
            back_callback="buy_key",
            is_wireguard=True
        )
    )
    await callback.answer()
