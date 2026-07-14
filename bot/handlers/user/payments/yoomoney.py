"""
Обработчик оплаты через YooMoney QuickPay.

Создание QuickPay ссылки, отправка пользователю, проверка статуса.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.utils.text import escape_html, safe_edit_or_send
from bot.handlers.user.payments.base import finalize_payment_ui

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == 'pay_yoomoney')
async def pay_yoomoney_select_tariff(callback: CallbackQuery):
    """Выбор тарифа для оплаты через YooMoney (новый ключ)."""
    from database.requests import get_all_tariffs, get_user_internal_id
    from bot.keyboards.user import tariff_select_kb
    from bot.keyboards.admin import home_only_kb

    tariffs = get_all_tariffs(include_hidden=False)
    # YooMoney: минимум 1 ₽
    rub_tariffs = [t for t in tariffs if t.get('price_rub') and t['price_rub'] >= 1]
    if not rub_tariffs:
        await safe_edit_or_send(
            callback.message,
            '💰 <b>Оплата YooMoney</b>\n\n😔 Нет доступных тарифов.\nОбратитесь к администратору.',
            reply_markup=home_only_kb()
        )
        await callback.answer()
        return
    user_internal_id = get_user_internal_id(callback.from_user.id)
    await safe_edit_or_send(
        callback.message,
        '💰 <b>Оплата YooMoney</b>\n\nВыберите тариф:\n\n<i>Оплата через YooMoney — поддерживает карты, СБП и другие способы.</i>',
        reply_markup=tariff_select_kb(rub_tariffs, is_yoomoney=True, user_id=user_internal_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith('yoomoney_pay:'))
async def yoomoney_pay_create(callback: CallbackQuery):
    """Создаёт платёж через YooMoney и отправляет ссылку пользователю."""
    from database.requests import (
        get_tariff_by_id, get_user_internal_id, create_pending_order
    )
    from bot.services.billing import create_yoomoney_payment, get_bot_username, calculate_loyalty_discount
    from bot.keyboards.user import yoomoney_pay_kb
    from bot.keyboards.admin import home_only_kb

    try:
        parts = callback.data.split(':')
        tariff_id = int(parts[1])
        order_id = parts[2] if len(parts) > 2 else None

        tariff = get_tariff_by_id(tariff_id)
        if not tariff:
            await callback.answer('❌ Тариф не найден', show_alert=True)
            return

        price_rub = float(tariff.get('price_rub') or 0)
        if price_rub < 1:
            await callback.answer('❌ Цена не установлена', show_alert=True)
            return

        user_id = get_user_internal_id(callback.from_user.id)
        if not user_id:
            await callback.answer('❌ Пользователь не найден', show_alert=True)
            return

        # Скидка лояльности
        price_rub, _discount_pct = calculate_loyalty_discount(user_id, price_rub)

        # Создаём pending order если не передан
        if not order_id:
            (_, order_id) = create_pending_order(
                user_id=user_id, tariff_id=tariff_id, payment_type='yoomoney', vpn_key_id=None
            )

        await safe_edit_or_send(callback.message, '⏳ Создаём платёж YooMoney...')

        bot_name = get_bot_username()
        description = f"Покупка «{tariff['name']}» — {tariff['duration_days']} дней"

        result = await create_yoomoney_payment(
            amount_rub=price_rub,
            order_id=order_id,
            description=description,
            bot_name=bot_name
        )

        if not result or not result.get('qr_url'):
            await safe_edit_or_send(
                callback.message,
                '❌ Ошибка создания платежа YooMoney. Попробуйте позже.',
                reply_markup=home_only_kb()
            )
            return

        # Сохраняем yoomoney_label в заказ (= order_id)
        yoomoney_label = result.get('yoomoney_label')
        if yoomoney_label:
            from database.requests import save_yoomoney_label
            save_yoomoney_label(order_id, yoomoney_label)

        confirmation_url = result['qr_url']

        text = (
            f"💰 <b>Оплата YooMoney</b>\n\n"
            f"💳 <b>Тариф:</b> {escape_html(tariff['name'])}\n"
            f"💰 <b>Сумма:</b> {int(price_rub)} ₽\n"
            f"⏳ <b>Срок:</b> {tariff['duration_days']} дней\n\n"
            f"Нажмите кнопку «💳 Оплатить YooMoney» для перехода к оплате.\n\n"
            f"<i>После оплаты вернитесь в бот и нажмите «✅ Я оплатил».</i>"
        )

        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=yoomoney_pay_kb(order_id, back_callback='pay_yoomoney', confirmation_url=confirmation_url),
            force_new=True
        )
        await callback.answer()

    except Exception as e:
        logger.exception(f"YooMoney payment creation error: {e}")
        await callback.answer('❌ Ошибка создания платежа', show_alert=True)


@router.callback_query(F.data.startswith('renew_yoomoney_tariff:'))
async def renew_yoomoney_select_tariff(callback: CallbackQuery):
    """Выбор тарифа для оплаты через YooMoney при продлении ключа."""
    from database.requests import get_key_details_for_user, get_user_internal_id
    from bot.keyboards.user import renew_tariff_select_kb
    from bot.utils.groups import get_tariffs_for_renewal
    from bot.keyboards.admin import home_only_kb

    key_id = int(callback.data.split(':')[1])
    key = get_key_details_for_user(key_id, callback.from_user.id)
    if not key:
        await callback.answer('❌ Ключ не найден', show_alert=True)
        return

    tariffs = get_tariffs_for_renewal(key.get('tariff_id', 0))
    # YooMoney: минимум 1 ₽
    rub_tariffs = [t for t in tariffs if t.get('price_rub') and t['price_rub'] >= 1]
    if not rub_tariffs:
        await callback.answer('😔 Нет тарифов для продления через YooMoney', show_alert=True)
        return

    user_internal_id = get_user_internal_id(callback.from_user.id)
    await safe_edit_or_send(
        callback.message,
        f"💰 <b>Оплата YooMoney (продление)</b>\n\n"
        f"🔑 Ключ: <b>{escape_html(key['display_name'])}</b>\n\n"
        f"Выберите тариф для продления:",
        reply_markup=renew_tariff_select_kb(rub_tariffs, key_id, is_yoomoney=True, user_id=user_internal_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith('renew_pay_yoomoney:'))
async def renew_yoomoney_create(callback: CallbackQuery):
    """Создаёт платёж YooMoney для продления ключа."""
    from database.requests import (
        get_tariff_by_id, get_user_internal_id, create_pending_order,
        get_key_details_for_user
    )
    from bot.services.billing import create_yoomoney_payment, get_bot_username, calculate_loyalty_discount
    from bot.keyboards.user import yoomoney_pay_kb
    from bot.keyboards.admin import home_only_kb

    try:
        parts = callback.data.split(':')
        key_id = int(parts[1])
        tariff_id = int(parts[2])

        tariff = get_tariff_by_id(tariff_id)
        key = get_key_details_for_user(key_id, callback.from_user.id)
        if not tariff or not key:
            await callback.answer('❌ Ошибка тарифа или ключа', show_alert=True)
            return

        price_rub = float(tariff.get('price_rub') or 0)
        if price_rub < 1:
            await callback.answer('❌ Цена не установлена', show_alert=True)
            return

        user_id = get_user_internal_id(callback.from_user.id)
        if not user_id:
            await callback.answer('❌ Пользователь не найден', show_alert=True)
            return

        # Скидка лояльности
        price_rub, _discount_pct = calculate_loyalty_discount(user_id, price_rub)

        # Создаём pending order для продления
        (_, order_id) = create_pending_order(
            user_id=user_id, tariff_id=tariff_id, payment_type='yoomoney', vpn_key_id=key_id
        )

        await safe_edit_or_send(callback.message, '⏳ Создаём платёж YooMoney...')

        bot_name = get_bot_username()
        description = f"Продление ключа «{key['display_name']}»: «{tariff['name']}» ({tariff['duration_days']} дн.)"

        result = await create_yoomoney_payment(
            amount_rub=price_rub,
            order_id=order_id,
            description=description,
            bot_name=bot_name
        )

        if not result or not result.get('qr_url'):
            await safe_edit_or_send(
                callback.message,
                '❌ Ошибка создания платежа YooMoney. Попробуйте позже.',
                reply_markup=home_only_kb()
            )
            return

        # Сохраняем yoomoney_label в заказ (= order_id)
        yoomoney_label = result.get('yoomoney_label')
        if yoomoney_label:
            from database.requests import save_yoomoney_label
            save_yoomoney_label(order_id, yoomoney_label)

        confirmation_url = result['qr_url']

        text = (
            f"💰 <b>Оплата YooMoney (продление)</b>\n\n"
            f"🔑 <b>Ключ:</b> {escape_html(key['display_name'])}\n"
            f"💳 <b>Тариф:</b> {escape_html(tariff['name'])}\n"
            f"💰 <b>Сумма:</b> {int(price_rub)} ₽\n"
            f"⏳ <b>Продление:</b> +{tariff['duration_days']} дней\n\n"
            f"Нажмите кнопку «💳 Оплатить YooMoney» для перехода к оплате.\n\n"
            f"<i>После оплаты вернитесь в бот и нажмите «✅ Я оплатил».</i>"
        )

        await safe_edit_or_send(
            callback.message,
            text,
            reply_markup=yoomoney_pay_kb(order_id, back_callback=f'renew_yoomoney_tariff:{key_id}', confirmation_url=confirmation_url),
            force_new=True
        )
        await callback.answer()

    except Exception as e:
        logger.exception(f"YooMoney renew payment creation error: {e}")
        await callback.answer('❌ Ошибка создания платежа', show_alert=True)


@router.callback_query(F.data.startswith('check_yoomoney:'))
async def check_yoomoney_payment(callback: CallbackQuery, state: FSMContext):
    """Проверяет статус YooMoney QuickPay-платежа по нажатию «✅ Я оплатил».

    Проверяет статус через operation-history API (Bearer = YOOMONEY_SECRET_KEY
    должен быть OAuth-токеном). Ключ выдаётся ТОЛЬКО при подтверждённом
    статусе 'succeeded'. Если API недоступен — показывает ошибку.
    """
    import time
    from database.requests import (
        find_order_by_order_id, is_order_already_paid, update_payment_type,
        get_tariff_by_id
    )
    from bot.services.billing import check_yoomoney_payment_status, process_payment_order
    from bot.keyboards.admin import home_only_kb

    try:
        parts = callback.data.split(':')
        order_id = parts[1]

        # Проверяем, не оплачен ли уже
        if is_order_already_paid(order_id):
            order = find_order_by_order_id(order_id)
            if order:
                await finalize_payment_ui(
                    callback.message,
                    state,
                    "✅ Этот платёж уже был обработан ранее.",
                    order,
                    callback.from_user.id
                )
            else:
                await callback.answer("✅ Платёж уже обработан", show_alert=True)
            return

        order = find_order_by_order_id(order_id)
        if not order:
            await callback.answer("❌ Заказ не найден", show_alert=True)
            return

        # Rate-limiting: не чаще 1 раза в 5 секунд
        state_data = await state.get_data()
        last_check_key = f'yoomoney_last_check_{order_id}'
        last_check = state_data.get(last_check_key, 0)
        now = time.time()
        elapsed = now - last_check
        if last_check and elapsed < 5:
            wait = int(5 - elapsed)
            await callback.answer(
                f'⏳ Подождите {wait} сек. перед повторной проверкой.',
                show_alert=True
            )
            return
        await state.update_data({last_check_key: now})

        await callback.answer('🔍 Проверяем платёж...')

        # Проверяем статус через YooMoney API
        try:
            status = await check_yoomoney_payment_status(order_id)
            logger.info(f"YooMoney API check: order_id={order_id}, status={status}")
        except Exception as e:
            logger.error(f'YooMoney API check failed for {order_id}: {e}')
            await safe_edit_or_send(
                callback.message,
                '⚠️ <b>Не удалось проверить платёж</b>\n\n'
                'Система временно не может подтвердить оплату.\n'
                'Попробуйте нажать «✅ Я оплатил» через 1-2 минуты.\n\n'
                '<i>Если проблема сохраняется — обратитесь в поддержку.</i>',
                reply_markup=home_only_kb(), force_new=True
            )
            return

        if status == 'succeeded':
            # API подтверждает оплату — выдаём ключ
            update_payment_type(order_id, 'yoomoney')
            _tariff = get_tariff_by_id(order.get('tariff_id'))
            referral_amount = int((_tariff.get('price_rub', 0) or 0) * 100) if _tariff else 0
            logger.info(f"YooMoney payment confirmed: order={order_id}")
            try:
                await callback.message.delete()
            except Exception:
                pass
            success, msg, order_data = await process_payment_order(order_id)
            if success:
                await finalize_payment_ui(
                    callback.message, state, msg, order_data,
                    callback.from_user.id
                )
            else:
                await callback.answer(msg, show_alert=True)

        elif status == 'canceled':
            await safe_edit_or_send(
                callback.message,
                '❌ <b>Платёж отменён</b>\n\nПохоже, платёж был отменён.\n'
                'Попробуйте снова выбрать тариф.',
                reply_markup=home_only_kb(), force_new=True
            )

        else:
            # pending — платёж ещё не поступил
            await safe_edit_or_send(
                callback.message,
                '⏳ <b>Платёж ещё не поступил</b>\n\n'
                'Оплатите по ссылке и нажмите «✅ Я оплатил» снова.\n\n'
                '<i>Если вы уже оплатили — подождите 1-2 минуты и попробуйте снова.</i>',
                force_new=True
            )

    except Exception as e:
        logger.exception(f"YooMoney payment check error: {e}")
        await callback.answer('❌ Ошибка проверки платежа', show_alert=True)
