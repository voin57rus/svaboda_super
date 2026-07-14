"""Middleware: блокировка админ-доступа к страницам оплаты."""
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from config import ADMIN_IDS

# Callback префиксы, которые ведут на страницы оплаты/тарифов
_PAYMENT_CALLBACK_PREFIXES = (
    "pay_stars", "pay_crypto", "pay_cards", "pay_qr", "pay_wata",
    "pay_platega", "pay_cardlink", "pay_demo", "pay_use_balance",
    "demo_tariffs", "wg_pay:",
    "renew_stars_tariff:", "renew_crypto_tariff:", "renew_cards_tariff:",
    "renew_qr_tariff:", "renew_wata_tariff:", "renew_platega_tariff:",
    "renew_cardlink_tariff:", "renew_demo_tariffs:",
    "renew_pay_stars:", "renew_pay_crypto:", "renew_pay_cards:",
    "renew_pay_qr:", "renew_pay_wata:", "renew_pay_platega:",
    "renew_pay_cardlink:", "renew_pay_demo:",
    "stars_pay:", "crypto_pay:", "cards_pay:", "qr_pay:",
    "wata_pay:", "platega_pay:", "cardlink_pay:", "demo_pay:",
    "pay_with_balance", "pay_card_balance:", "pay_qr_balance:",
)

# Страницы оплаты, куда админ не должен попадать
_PAYMENT_PAGE_KEYS = frozenset({
    "prepayment",
    "renew_payment",
    "renew_payment_unavailable",
})


class AdminPaymentBlockMiddleware(BaseMiddleware):
    """
    Блокирует админу доступ к страницам оплаты и тарифов.

    Если админ нажимает кнопку оплаты или попадает на страницу оплаты —
    перенаправляет его на выбор протocolа (buy_key_handler).
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Проверяем только CallbackQuery
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)

        user = data.get('event_from_user')
        if not user or user.id not in ADMIN_IDS:
            return await handler(event, data)

        callback_data = event.data or ""

        # Проверяем callback_data — если это платёжная кнопка, блокируем
        if callback_data.startswith(_PAYMENT_CALLBACK_PREFIXES):
            # Отвечаем на callback чтобы не было ошибки
            await event.answer("⛔ Для админа оплата не требуется — используйте «Купить ключ»", show_alert=False)
            return None

        return await handler(event, data)
