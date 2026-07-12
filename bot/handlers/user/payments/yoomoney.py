import logging
import aiohttp
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton

from bot.utils.text import escape_html, safe_edit_or_send
from bot.keyboards.admin import home_only_kb
from database.db_settings import get_yoomoney_credentials as _get_yoomoney_creds

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == 'pay_yoomoney')
async def pay_yoomoney_select_tariff(callback: CallbackQuery):
    """Выбор тарифа для оплаты через ЮMoney (новый ключ)."""
    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb

    tariffs = get_all_tariffs(include_hidden=False)
    rub_tariffs = [t for t in tariffs if t.get('price_rub') and t['price_rub'] >= 1]
    if not rub_tariffs:
        await safe_edit_or_send(
            callback.message,
            '🟡 <b>Оплата ЮMoney</b>\n\n😔 Нет тарифов с ценой в рублях.\nОбратитесь к администратору.',
            reply_markup=home_only_kb()
        )
        await callback.answer()
        return

    await safe_edit_or_send(
        callback.message,
        '🟡 <b>Оплата ЮMoney</b>\n\nВыберите тариф:\n\n<i>Оплата через ЮMoney — поддерживает банковские карты.</i>',
        reply_markup=tariff_select_kb(rub_tariffs, is_yoomoney=True)
    )
    await callback.answer()


@router.callback_query(F.data.startswith('yoomoney_pay:'))
async def yoomoney_pay_create(callback: CallbackQuery, state: FSMContext):
    """Создаёт ссылку ЮMoney для оплаты нового ключа."""
    from database.requests import (
        get_tariff_by_id, get_user_internal_id, create_pending_order, save_yoomoney_label
    )

    tariff_id = int(callback.data.split(':')[1])
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.answer('❌ Тариф не найден', show_alert=True)
        return

    price_rub = float(tariff.get('price_rub') or 0)
    if price_rub < 1:
        await callback.answer('❌ Минимальная сумма для ЮMoney — 1 ₽', show_alert=True)
        return

    user_id = get_user_internal_id(callback.from_user.id)
    if not user_id:
        await callback.answer('❌ Пользователь не найден', show_alert=True)
        return

    (_, order_id) = create_pending_order(
        user_id=user_id, tariff_id=tariff_id, payment_type='yoomoney', vpn_key_id=None
    )

    label = order_id
    save_yoomoney_label(order_id, label)

    client_id, _ = get_yoomoney_credentials()

    yoomoney_url = (
        f"https://yoomoney.ru/quickpay/button.xml?"
        f"receiver={client_id}&sum={price_rub}&label={label}"
        f"&targets=VPN%20Subscription&comment=Order%20{label}&coin=₽"
    )

    text = (
        f"🟡 <b>Оплата ЮMoney</b>\n\n"
        f"💳 <b>Тариф:</b> {escape_html(tariff['name'])}\n"
        f"💰 <b>Сумма:</b> {int(price_rub)} ₽\n\n"
        f"Нажмите кнопку «💳 Оплатить» ниже — откроется форма оплаты ЮMoney.\n\n"
        f"<i>После оплаты нажмите «✅ Я оплатил».</i>"
    )

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text='💳 Оплатить', url=yoomoney_url))
    builder.row(InlineKeyboardButton(text='✅ Я оплатил', callback_data=f'check_yoomoney:{order_id}'))
    builder.row(InlineKeyboardButton(text='📋 На главную', callback_data='start'))

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=builder.as_markup(),
        force_new=True
    )
    await callback.answer()


@router.callback_query(F.data.startswith('check_yoomoney:'))
async def check_yoomoney_payment(callback: CallbackQuery, state: FSMContext):
    """Автоматическая проверка оплаты через API ЮMoney."""
    from database.requests import (
        is_order_already_paid, find_order_by_order_id, complete_order, get_tariff_by_id
    )
    from database.db_settings import get_yoomoney_api_token
    from bot.handlers.user.payments.base import finalize_payment_ui

    order_id = callback.data.split(':', 1)[1]

    if is_order_already_paid(order_id):
        await safe_edit_or_send(
            callback.message,
            '✅ Оплата уже обработана!',
            reply_markup=home_only_kb(),
            force_new=True
        )
        await callback.answer()
        return

    order = find_order_by_order_id(order_id)
    if not order:
        await callback.answer('❌ Ордер не найден', show_alert=True)
        return

    label = order.get('yoomoney_label')
    if not label:
        await callback.answer('❌ Label не найден', show_alert=True)
        return

    expected_amount = float(order.get('price_rub') or 0)

    api_token = get_yoomoney_api_token()
    if not api_token:
        await safe_edit_or_send(
            callback.message,
            '⚠️ API токен ЮMoney не настроен. Обратитесь к администратору.',
            reply_markup=home_only_kb(),
            force_new=True
        )
        await callback.answer()
        return

    try:
        headers = {'Authorization': f'Bearer {api_token}', 'Content-Type': 'application/x-www-form-urlencoded'}
        async with aiohttp.ClientSession() as session:
            data = {'label': label, 'limit': 10}
            async with session.post('https://yoomoney.ru/api/operation-history', headers=headers, data=data) as resp:
                result = await resp.json()

        if result.get('status') != 'success':
            raise Exception(f"API error: {result}")

        operations = result.get('operations', [])
        found_payment = None
        for op in operations:
            if op.get('label') == label:
                found_payment = op
                break

        if not found_payment:
            await safe_edit_or_send(
                callback.message,
                f'🟡 <b>Оплата ЮMoney</b>\n\n'
                f'Платёж пока не найден.\n\n'
                f'Убедитесь, что вы действительно оплатили. Попробуйте нажать «✅ Я оплатил» через минуту.',
                reply_markup=None,
                force_new=True
            )
            await callback.answer()
            return

        if found_payment.get('status') != 'success':
            await safe_edit_or_send(
                callback.message,
                f'🟡 <b>Оплата ЮMoney</b>\n\n'
                f'Статус платежа: {found_payment.get("status", "неизвестен")}\n\n'
                f'Дождитесь завершения оплаты и попробуйте снова.',
                reply_markup=home_only_kb(),
                force_new=True
            )
            await callback.answer()
            return

        amount_rub = float(found_payment.get('amount', 0))
        if abs(amount_rub - expected_amount) > 1:
            await safe_edit_or_send(
                callback.message,
                f'🟡 <b>Оплата ЮMoney</b>\n\n'
                f'❌ Сумма оплаты ({amount_rub} ₽) не совпадает с тарифом ({expected_amount} ₽).\n\n'
                f'Обратитесь к администратору.',
                reply_markup=home_only_kb(),
                force_new=True
            )
            await callback.answer()
            return

        complete_order(order_id)

        tariff = get_tariff_by_id(order['tariff_id'])
        await finalize_payment_ui(
            callback.message,
            user_id=callback.from_user.id,
            order_id=order_id,
            tariff=tariff,
            payment_type='yoomoney'
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка проверки ЮMoney оплаты: {e}")
        await callback.answer(f'⚠️ Ошибка проверки оплаты: {str(e)[:100]}', show_alert=True)


def get_yoomoney_credentials():
    """Получает client_id для формы оплаты."""
    return _get_yoomoney_creds()