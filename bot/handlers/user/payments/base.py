import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from bot.utils.text import escape_html, safe_edit_or_send
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

def _format_price_compact(cents: int) -> str:
    """Форматирование цены в компактном виде."""
    if cents >= 10000:
        return f'{cents // 100} ₽'
    else:
        return f'{cents / 100:.2f} ₽'.replace('.', ',')

def _is_cards_via_yookassa_direct() -> bool:
    """
    Проверяет, используется ли оплата картами через ЮKassa напрямую (webhook).
    
    Returns:
        True если карты через ЮKassa напрямую (минимум 1₽),
        False если через Telegram Payments API (минимум ~100₽)
    """
    from database.requests import get_setting
    return get_setting('cards_via_yookassa_direct', '0') == '1'

@router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout: PreCheckoutQuery):
    """Подтверждение pre-checkout для Telegram Stars."""
    await pre_checkout.answer(ok=True)

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message, state: FSMContext):
    """
    Обработка успешной оплаты Stars или Cards.
    
    Делегирует общую post-payment логику в complete_payment_flow().
    """
    from bot.services.billing import complete_payment_flow
    payment = message.successful_payment
    payload = payment.invoice_payload
    currency = payment.currency
    payment_type = 'stars' if currency == 'XTR' else 'cards'
    logger.info(f'Успешная оплата {payment_type}: {payload}, charge_id={payment.telegram_payment_charge_id}')
    
    if payload.startswith('renew:'):
        order_id = payload.split(':')[1]
    elif payload.startswith('vpn_key:'):
        order_id = payload.split(':')[1]
    else:
        order_id = payload
    
    await complete_payment_flow(
        order_id=order_id,
        message=message,
        state=state,
        telegram_id=message.from_user.id,
        payment_type=payment_type,
        referral_amount=payment.total_amount
    )

async def finalize_payment_ui(message: Message, state: FSMContext, text: str, order: dict, user_id: int):
    """
    Завершает UI после успешной оплаты.
    Показывает сообщение и либо перекидывает на настройку (draft), либо на главную.
    """
    from bot.keyboards.admin import home_only_kb
    from database.requests import get_key_details_for_user
    import logging
    logger = logging.getLogger(__name__)

    key_id = order.get('vpn_key_id')
    logger.info(f"finalize_payment_ui: Order={order.get('order_id')}, Key={key_id}, User={user_id}")

    # Проверяем протокол из ордера
    protocol = order.get('protocol', '')

    # WireGuard / AmneziaWG — особый путь (ключ уже создан полностью)
    if protocol in ('wireguard', 'amnezia') and key_id:
        await _finalize_wg_payment(message, state, order, key_id, user_id, protocol)
        return

    # Стандартный путь для VLESS/Trojan/Xray
    from bot.handlers.user.payments.keys_config import start_new_key_config
    is_draft = False
    if key_id:
        key = get_key_details_for_user(key_id, user_id)
        if key:
            logger.info(f"Key details found: ID={key['id']}, ServerID={key.get('server_id')}")
            if not key.get('server_id'):
                is_draft = True
        else:
            logger.warning(f'Key {key_id} not found for user {user_id} via details check!')
    else:
        logger.info('No key_id in order object.')
    logger.info(f'Result: is_draft={is_draft}')
    if is_draft:
        await safe_edit_or_send(message, text, force_new=True)
        await start_new_key_config(message, state, order['order_id'], key_id)
    else:
        from bot.handlers.user.keys import show_key_details
        await show_key_details(telegram_id=user_id, key_id=key_id, message=message, is_callback=False, prepend_text=text)


async def _finalize_wg_payment(message, state, order, key_id, telegram_id, protocol):
    """
    Финализация оплаты WireGuard.
    Создаёт пир на сервере, генерирует конфиг и отправляет пользователю.
    """
    from database.requests import get_vpn_key_by_id
    from bot.utils.key_sender import send_wg_key
    from bot.utils.key_generator import generate_wg_config_text
    from bot.services.panels.wireguard_ssh import get_server_public_key
    from bot.keyboards.user import key_manage_kb

    try:
        # Получаем данные ключа из БД
        key_data = get_vpn_key_by_id(key_id)
        if not key_data:
            await safe_edit_or_send(message, f"❌ Ключ #{key_id} не найден. Обратитесь в поддержку.")
            return

        # Получаем публичный ключ сервера
        server_pubkey = await get_server_public_key()

        # Генерируем конфиг (обычный WireGuard)
        wg_config = generate_wg_config_text(
            client_private_key=key_data['private_key'],
            client_ip=key_data['allowed_ip'],
            server_public_key=server_pubkey,
            preshared_key=key_data['preshared_key'],
            endpoint=key_data.get('endpoint', '87.120.165.232:39623'),
        )

        # Управляющая клавиатура
        markup = key_manage_kb(
            key_id=key_id,
            is_active=True,
            include_navigation=True
        )

        # Отправляем конфиг + QR
        await send_wg_key(
            messageable=message,
            wg_config=wg_config,
            key_id=key_id,
            key_manage_markup=markup,
        )

    except Exception as e:
        logger.error(f"WG finalize error: {e}")
        await safe_edit_or_send(
            message,
            f"✅ Оплата прошла успешно!\n\n"
            f"⚠️ Ошибка создания WireGuard конфигурации: {e}\n"
            f"Обратитесь в поддержку — мы решим проблему."
        )

@router.callback_query(F.data.startswith('renew_invoice_cancel:'))
async def renew_invoice_cancel_handler(callback: CallbackQuery):
    """Отмена инвойса и возврат к выбору способа оплаты."""
    from database.requests import get_key_details_for_user
    from bot.handlers.user.keys import show_renew_payment_page
    parts = callback.data.split(':')
    key_id = int(parts[1])
    telegram_id = callback.from_user.id

    key = get_key_details_for_user(key_id, telegram_id)
    if not key:
        await callback.answer('❌ Ключ не найден', show_alert=True)
        return

    await show_renew_payment_page(callback, key, key_id, force_new=True)
    await callback.answer()
