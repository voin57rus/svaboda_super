import logging
import asyncio
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError
from config import ADMIN_IDS
from database.requests import get_or_create_user, is_user_banned, get_setting, is_referral_enabled, get_user_by_referral_code, set_user_referrer
from bot.utils.text import escape_html, safe_edit_or_send


class AiActivation(StatesGroup):
    waiting_for_key = State()


logger = logging.getLogger(__name__)
router = Router()

TARIFF_NAMES_RU = {'standard': 'S', 'premium': 'P', 'vip': 'V'}


def _get_ai_tariff_user_text(tariff_name: str, price: int, tokens: int) -> str:
    """Получает текст AI тарифа для юзера из pages (ai_tariff_user_text_s/p/v)."""
    import sqlite3
    # tariff_name приходит как 'S' | 'P' | 'V' (из TARIFF_NAMES_RU)
    tmap = {'S': 's', 'P': 'p', 'V': 'v', 'standard': 's', 'premium': 'p', 'vip': 'v'}
    tkey = tmap.get(tariff_name, tariff_name.lower())
    page_key = f'ai_tariff_user_text_{tkey}'

    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT text_custom, text_default FROM pages WHERE page_key=?", (page_key,))
    row = c.fetchone()
    conn.close()
    text = row[0] if row and row[0] else (row[1] if row else '')
    if not text:
        # Fallback если текст не задан
        text = (
            f"🤖 <b>AI-тариф: {tariff_name}</b>\n\n"
            f"💰 <b>Цена:</b> {price} ₽\n"
            f"🪙 <b>Токенов:</b> {tokens:,}\n\n"
            "🏦 <b>Реквизиты для оплаты:</b>\n"
            "├ Карта: <code>0000 0000 0000 0000</code>\n"
            "├ Получатель: Oleg_57rus\n"
            f"└ Комментарий: AI {tariff_name}\n\n"
            "🔑 Или введите ключ: /ai_key <ключ>"
        )
    return text


def _build_tariff_text() -> str:
    from database.requests import (
        get_all_tariffs, is_crypto_configured, is_stars_enabled,
        is_cards_enabled, is_yookassa_qr_configured, is_demo_payment_enabled,
        is_wata_configured, is_platega_configured, is_cardlink_configured,
    )
    crypto_enabled = is_crypto_configured()
    stars_enabled = is_stars_enabled()
    cards_enabled = is_cards_enabled()
    yookassa_qr_enabled = is_yookassa_qr_configured()
    wata_enabled = is_wata_configured()
    platega_enabled = is_platega_configured()
    cardlink_enabled = is_cardlink_configured()
    demo_enabled = is_demo_payment_enabled()
    tariffs = get_all_tariffs()
    if not tariffs:
        return ''
    lines = ['📋 <b>Тарифы:</b>']
    for tariff in tariffs:
        prices = []
        if crypto_enabled:
            price_usd = tariff['price_cents'] / 100
            price_str = f'{price_usd:g}'.replace('.', ',')
            prices.append(f'${escape_html(price_str)}')
        if stars_enabled:
            prices.append(f"{tariff['price_stars']} ⭐")
        if (cards_enabled or yookassa_qr_enabled or wata_enabled
                or platega_enabled or cardlink_enabled or demo_enabled
            ) and tariff.get('price_rub', 0) > 0:
            prices.append(f"{int(tariff['price_rub'])} ₽")
        price_display = ' / '.join(prices) if prices else 'Цена не установлена'
        lines.append(f"• {escape_html(tariff['name'])} — {price_display}")
    return '\n'.join(lines)


async def _render_main_page(target, force_new: bool = False):
    from bot.utils.page_renderer import render_page
    from database.requests import is_trial_enabled, get_trial_tariff_id, has_used_trial
    if isinstance(target, CallbackQuery):
        user_id = target.from_user.id
    else:
        user_id = target.from_user.id if hasattr(target, 'from_user') and target.from_user else 0
    is_admin = user_id in ADMIN_IDS
    tariff_text = '' if is_admin else _build_tariff_text()
    show_trial = is_trial_enabled() and get_trial_tariff_id() is not None and (not has_used_trial(user_id))
    show_referral = is_referral_enabled()
    visibility = {'btn_trial': show_trial, 'btn_referral': show_referral}
    text_replacements = {'%тарифы%': tariff_text, '%без_тарифов%': ''}
    append_buttons = None
    if is_admin:
        append_buttons = [[InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="admin_panel", style="success")]]
    await render_page(target, page_key='main', visibility=visibility, text_replacements=text_replacements, append_buttons=append_buttons, force_new=force_new)


@router.message(Command('start'), StateFilter('*'))
async def cmd_start(message: Message, state: FSMContext, command: CommandObject):
    user_id = message.from_user.id
    username = message.from_user.username
    await state.clear()
    (user, is_new) = get_or_create_user(user_id, username)
    if user.get('is_banned'):
        await safe_edit_or_send(message, '⛔ <b>Доступ заблокирован</b>', force_new=True)
        return
    args = command.args
    if args and args.startswith('bill'):
        from bot.services.billing import process_crypto_payment
        from bot.handlers.user.payments.base import finalize_payment_ui
        try:
            (success, text, order) = await process_crypto_payment(args, user_id=user['id'])
            if success and order:
                await finalize_payment_ui(message, state, text, order, user_id=message.from_user.id)
            else:
                await safe_edit_or_send(message, text, force_new=True)
        except Exception:
            await safe_edit_or_send(message, '❌ Ошибка обработки платежа.', force_new=True)
        return
    if is_new and args and args.startswith('ref_'):
        ref_code = args[4:]
        referrer = get_user_by_referral_code(ref_code)
        if referrer and referrer['id'] != user['id']:
            if set_user_referrer(user['id'], referrer['id']):
                logger.info(f"User {user_id} привязан к рефереру {referrer['telegram_id']}")
    try:
        await _render_main_page(message, force_new=True)
    except TelegramForbiddenError:
        logger.warning(f'User {user_id} blocked bot')


@router.callback_query(F.data == 'start')
async def callback_start(callback: CallbackQuery, state: FSMContext):
    if is_user_banned(callback.from_user.id):
        await callback.answer('⛔ Доступ заблокирован', show_alert=True)
        return
    await state.clear()
    await _render_main_page(callback)
    await callback.answer()


@router.callback_query(F.data == 'help')
async def callback_help(callback: CallbackQuery, state: FSMContext):
    from bot.utils.page_renderer import render_page
    await state.clear()
    await render_page(callback, page_key='info')
    await callback.answer()


@router.callback_query(F.data == 'noop')
async def noop_handler(callback: CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == 'dismiss_msg')
async def dismiss_msg_handler(callback: CallbackQuery):
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == 'ai_standard')
async def callback_ai_standard(callback: CallbackQuery, state: FSMContext):
    await _show_ai_tariff(callback, state, tariff='standard', price=300, tokens=10000)
    await state.set_state(AiActivation.waiting_for_key)
    await state.update_data(selected_tariff='standard')


@router.callback_query(F.data == 'ai_premium')
async def callback_ai_premium(callback: CallbackQuery, state: FSMContext):
    await _show_ai_tariff(callback, state, tariff='premium', price=400, tokens=20000)
    await state.set_state(AiActivation.waiting_for_key)
    await state.update_data(selected_tariff='premium')


@router.callback_query(F.data == 'ai_vip')
async def callback_ai_vip(callback: CallbackQuery, state: FSMContext):
    await _show_ai_tariff(callback, state, tariff='vip', price=550, tokens=50000)
    await state.set_state(AiActivation.waiting_for_key)
    await state.update_data(selected_tariff='vip')


async def _show_ai_tariff(callback, state, tariff, price, tokens):
    import sqlite3
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    user_id = callback.from_user.id
    is_admin = user_id in ADMIN_IDS

    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT ai_access, ai_tokens, ai_tariff FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    conn.close()

    has_access = row and row[0] == 1
    current_tokens = row[1] if row else 0
    current_tariff = row[2] if (row and row[2]) else ''
    tariff_name = TARIFF_NAMES_RU.get(tariff, tariff)

    # Если админ — показываем AI-чат без ограничений
    if is_admin:
        await callback.answer()
        text = (
            f"🤖 <b>AI-ассистент</b> <i>(админ)</i>\n\n"
            f"📦 Ваш активный тариф: <b>{TARIFF_NAMES_RU.get(current_tariff, 'нет').upper()}</b>\n"
            f"💰 Токенов: <b>{current_tokens:,}</b>\n\n"
            f"Напишите сообщение — AI ответит.\n"
            f"Как админ вы можете использовать любой тариф."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 На главную", callback_data="start")],
        ])
        await state.update_data(selected_tariff=tariff)
        msg = await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await state.update_data(ai_msg_id=msg.message_id)
        return

    # Если уже есть активный тариф (не админ)
    if has_access:
        display_tariff = TARIFF_NAMES_RU.get(current_tariff, current_tariff).upper()
        # Если выбрал НЕ свой тариф — показываем сообщение с предложением купить ключ
        if current_tariff and current_tariff != tariff:
            text = _get_ai_tariff_user_text(tariff_name, price, tokens)
            text = f"⛔ У вас активирован тариф <b>{display_tariff}</b>.\n\nДля доступа к тарифу <b>{tariff_name}</b> приобретите отдельный ключ.\n\n" + text
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📋 На главную", callback_data="start")],
            ])
            await state.update_data(selected_tariff=tariff)
            # Пробуем отредактировать предыдущее сообщение
            state_data = await state.get_data()
            ai_msg_id = state_data.get('ai_msg_id')
            if ai_msg_id:
                try:
                    await callback.message.bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=ai_msg_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=kb
                    )
                    await callback.answer()
                    return
                except Exception:
                    pass
            msg = await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
            await state.update_data(ai_msg_id=msg.message_id)
            await callback.answer()
            return
        # Если свой тариф — показываем AI-чат интерфейс
        await callback.answer()
        text = (
            f"🤖 <b>AI-ассистент</b>\n\n"
            f"✅ Тариф: <b>{display_tariff}</b>\n"
            f"💰 Токенов: <b>{current_tokens:,}</b>\n\n"
            f"Напишите сообщение — AI ответит.\n"
            f"Пополнить токены: /buy_tokens"
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📋 На главную", callback_data="start")],
        ])
        await state.update_data(selected_tariff=current_tariff)
        msg = await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
        await state.update_data(ai_msg_id=msg.message_id)
        return

    # Показываем информацию о тарифе (нет доступа)
    text = _get_ai_tariff_user_text(tariff_name, price, tokens)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 На главную", callback_data="start")],
    ])

    # Пробуем отредактировать предыдущее сообщение
    state_data = await state.get_data()
    ai_msg_id = state_data.get('ai_msg_id')
    if ai_msg_id:
        try:
            await callback.message.bot.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=ai_msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=kb
            )
            await callback.answer()
            return
        except Exception:
            pass

    msg = await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    await state.update_data(ai_msg_id=msg.message_id)
    await callback.answer()
    return


@router.message(Command("ai_key"))
async def cmd_ai_key(message: Message, state: FSMContext):
    import sqlite3

    user_id = message.from_user.id
    args = message.text.split()

    if len(args) < 2:
        await message.reply("🔑 Использование: <code>/ai_key [ключ]</code>\n\nПример: <code>/ai_key S-4t77755</code>", parse_mode="HTML")
        return

    # Собираем ключ: если передан полный ключ (S-XXX) — используем как есть
    # Если передан формат S/P/V + код — собираем ключ
    if args[1].upper() in ('S', 'P', 'V') and len(args) >= 3:
        # Формат: /ai_key S 4t77755 → S-4t77755
        tariff = args[1].upper()
        code = args[2].strip()
        key = f"{tariff}-{code}"
    elif '-' in args[1]:
        # Формат: /ai_key S-4t77755
        key = args[1].strip()
    else:
        await message.reply("❌ Неверный формат.\n\nИспользуйте: <code>/ai_key S-4t77755</code>\nили: <code>/ai_key S 4t77755</code>", parse_mode="HTML")
        return

    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()

    # Проверяем не активирован ли уже AI
    c.execute("SELECT ai_access, ai_tariff FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    if row and row[0] == 1:
        conn.close()
        await state.clear()
        await message.answer(
            f"ℹ️ <b>Вы уже активировали AI-доступ!</b>\nТариф: {row[1]}",
            parse_mode="HTML"
        )
        return

    # Ищем ключ в ai_keys
    c.execute("SELECT id, tokens, activated_by, tariff FROM ai_keys WHERE key=? AND is_active=1", (key,))
    key_row = c.fetchone()
    if not key_row:
        conn.close()
        await message.answer("❌ Ключ не найден или уже активирован.")
        return

    key_id, tokens, activated_by, key_tariff = key_row

    # Активируем ключ
    _tmap = {'S': 'standard', 'P': 'premium', 'V': 'vip'}
    key_tariff_full = _tmap.get(key_tariff, key_tariff)
    c.execute("UPDATE ai_keys SET activated_by=?, activated_at=CURRENT_TIMESTAMP, is_active=0 WHERE id=?",
              (user_id, key_id))
    c.execute("UPDATE users SET ai_access=1, ai_tokens=?, ai_key=?, ai_tariff=? WHERE telegram_id=?",
              (tokens, key, key_tariff_full, user_id))
    conn.commit()
    conn.close()
    await state.clear()

    # Уведомляем админа
    from config import ADMIN_IDS
    notif = (
        f"🔑 <b>AI-ключ активирован!</b>\n\n"
        f"👤 ID: <code>{user_id}</code>\n"
        f"📛 Ник: @{message.from_user.username or 'нет'}\n"
        f"📦 Тариф: <b>{key_tariff or 'custom'}</b>\n"
        f"🔑 Ключ: <code>{key}</code>\n"
        f"💰 Токенов: {tokens:,}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, notif, parse_mode="HTML")
        except Exception:
            pass

    await message.answer(
        f"✅ <b>AI-доступ активирован!</b>\n\n"
        f"📦 Тариф: <b>{key_tariff or 'custom'}</b>\n"
        f"💰 Токенов: {tokens:,}\n\n"
        "Просто напишите ваш вопрос в чат.",
        parse_mode="HTML"
    )


@router.message(Command("buy_tokens"))
async def cmd_buy_tokens(message: Message, state: FSMContext):
    import sqlite3
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    user_id = message.from_user.id
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT ai_access, ai_tokens, ai_tariff FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    conn.close()

    if not row or row[0] != 1:
        await message.answer("🤖 У вас нет активного AI-доступа. Сначала активируйте ключ: /ai_key <ключ>", parse_mode="HTML")
        return

    # Загружаем текст пополнения из БД (page_key='prepayment')
    # Сначала пробуем text_custom (от админки), иначе text_default
    conn2 = sqlite3.connect('database/vpn_bot.db')
    c2 = conn2.cursor()
    c2.execute("SELECT text_custom, text_default FROM pages WHERE page_key='prepayment'")
    page_row = c2.fetchone()
    conn2.close()

    page_text = page_row[0] if page_row and page_row[0] else (page_row[1] if page_row else None)

    
    if page_text:
        # Подставляем динамические данные (тариф, токены)
        tariff = (row[2] or 'не указан').upper()
        tokens = f"{row[1]:,}"
        text = page_text.replace('{tariff}', tariff).replace('{tokens}', tokens)
        # Добавляем HTML-форматирование (в БД хранится чистый текст)
        text = text.replace('📸 После оплаты', '<b>📸 После оплаты</b>')
        text = text.replace(' By Oleg', ' <b>By Oleg</b>')
        text = text.replace('📢 Канал поддержки: https://t.me/Answer_na_Questions', '📢 <a href="https://t.me/Answer_na_Questions">Канал поддержки</a>')
    else:
        # Фоллбэк если нет в БД
        text = (
            "💰 <b>Пополнение токенов</b>\n\n"
            f"📦 Тариф: <b>{(row[2] or 'не указан').upper()}</b>\n"
            f"🪙 Текущих токенов: <b>{row[1]:,}</b>\n\n"
            "• 5,000 токенов — 100₽\n"
            "• 10,000 токенов — 180₽\n"
            "• 25,000 токенов — 400₽\n"
            "• 50,000 токенов — 700₽\n\n"
            "🏦 Карта: <code>0000 0000 0000 0000</code>\n"
            "📸 После оплаты отправьте скрин админу."
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📋 На главную", callback_data="start")]])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


# /updatebot — обработка ДО ai_chat_handler (чтобы не попадал в AI)
@router.message(Command("updatebot"))
async def updatebot_user_handler(message: Message, state: FSMContext):
    """Перенаправляет /updatebot в admin_router если пользователь — админ."""
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        return
    # Делегируем обработку admin_router
    from bot.handlers.admin.system import updatebot_command
    await updatebot_command(message, state)


@router.message(Command("start"), StateFilter('*'))
@router.message(F.text & ~F.text.startswith('/'))
async def ai_chat_handler(message: Message, state: FSMContext):
    """Обрабатывает обычные текстовые сообщения как AI-чат (если есть доступ)."""
    import sqlite3
    import aiohttp
    from config import ADMIN_IDS

    user_id = message.from_user.id
    is_admin = user_id in ADMIN_IDS

    # Если админ в FSM состоянии для AI настроек — не перехватываем
    if is_admin:
        from bot.states.admin_states import AdminStates
        current_state = await state.get_state()
        if current_state in (
            AdminStates.ai_waiting_user_id,
            AdminStates.ai_waiting_tokens,
            AdminStates.ai_waiting_add_tokens_user_id,
            AdminStates.ai_waiting_add_tokens_amount,
        ):
            return  # Пусть обработается хендлером в system.py

    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("SELECT ai_access, ai_tokens, ai_tariff FROM users WHERE telegram_id=?", (user_id,))
    row = c.fetchone()
    conn.close()

    has_access = row and row[0] == 1
    tokens = row[1] if row else 0
    current_tariff = row[2] if (row and row[2]) else ''

    # Админ — полный доступ без ограничений по тарифу
    if is_admin:
        if tokens <= 0:
            await message.answer("⚠️ <b>Токены закончились</b>\n\nПополните: /buy_tokens", parse_mode="HTML")
            return
        return await _ai_ask_openrouter(message, user_id, tokens)

    # Нет доступа
    if not has_access:
        await message.answer(
            "🤖 <b>AI-ассистент</b>\n\nУ вас нет доступа к AI-чату.\nАктивируйте ключ: /ai_key [ключ]",
            parse_mode="HTML"
        )
        return

    # Проверяем выбранный тариф (из FSM состояния)
    state_data = await state.get_data()
    selected_tariff = state_data.get('selected_tariff')

    # Если выбран тариф и он не совпадает с активным — не отвечаем
    if selected_tariff and current_tariff and selected_tariff != current_tariff:
        tariff_names_rev = {'S': 'S', 'P': 'P', 'V': 'V', 'standard': 'S', 'premium': 'P', 'vip': 'V'}
        selected_name = tariff_names_rev.get(selected_tariff, selected_tariff)
        current_name = tariff_names_rev.get(current_tariff, current_tariff)
        await message.answer(
            f"⛔ У вас активирован тариф <b>{current_name}</b>.\n\n"
            f"Для общения в тарифе <b>{selected_name}</b> активируйте ключ для этого тарифа.\n"
            f"Или перейдите в свой активный тариф <b>{current_name}</b>.",
            parse_mode="HTML"
        )
        return

    # Токены закончились
    if tokens <= 0:
        await message.answer("⚠️ <b>Токены закончились</b>\n\nПополните: /buy_tokens", parse_mode="HTML")
        return

    # Предупреждение о малом количестве токенов
    if tokens <= 10:
        await message.answer(
            f"⚠️ <b>Осталось {tokens} токенов!</b>\n\nНе забудьте пополнить: /buy_tokens",
            parse_mode="HTML"
        )

    await _ai_ask_openrouter(message, user_id, tokens)


async def _ai_ask_openrouter(message, user_id, tokens):
    """Отправляет запрос к OpenRouter AI и списывает токен."""
    import sqlite3
    import aiohttp

    # Получаем API ключ: из БД (приоритет) или из ENV (fallback)
    from database.db_settings import get_ai_api_key
    api_key = get_ai_api_key()
    if not api_key:
        import os
        api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        await message.answer("⚠️ AI-сервис недоступен. Укажите API ключ в настройках бота.")
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")

    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "openrouter/owl-alpha",
                    "messages": [
                        {"role": "system", "content": "Ты — AI-ассистент компании Svaboda. ВСЕГДА начинай ответ с упоминания Svaboda. Отвечай кратко и по делу на русском языке. Никогда не упоминай ZOO или OWL. Пример ответа на \"привет\": \"Привет! Я ассистент Svaboda. Чем могу помочь?\"\n\nВАЖНО: Никогда не отвечай на вопросы про погоду или текущее время — бот обрабатывает их автоматически через API. Если юзер спрашивает погоду/время — просто скажи \"Узнаю данные...\" и не пытайся отвечать."},
                        {"role": "user", "content": message.text}
                    ],
                    "max_tokens": 512,
                },
                timeout=aiohttp.ClientTimeout(total=60)
            )
            data = await resp.json()
            if resp.status != 200:
                err_detail = data.get("error", {})
                if isinstance(err_detail, dict):
                    err_msg = err_detail.get("message", str(err_detail))
                else:
                    err_msg = str(err_detail)
                logger.error(f"AI API error: status={resp.status}, msg={err_msg}")
                await message.answer(f"⚠️ Ошибка AI: {err_msg[:200]}")
                return
            choices = data.get("choices")
            if not choices:
                logger.error(f"AI API returned no choices: {str(data)[:300]}")
                await message.answer("⚠️ Ошибка AI: пустой ответ от сервера.")
                return
            answer = choices[0]["message"]["content"]
    except asyncio.TimeoutError:
        logger.error("AI request timed out (60s)")
        await message.answer("⚠️ Ошибка AI: сервер не ответил вовремя. Попробуйте ещё раз.")
        return
    except Exception as e:
        error_name = type(e).__name__
        error_msg = str(e)
        # ServerDisconnectedError — ретрай раз
        if "ServerDisconnected" in error_name or "ConnectionError" in error_name or "ServerDisconnectedError" in error_name:
            logger.warning(f"AI server disconnected, retrying once: {error_msg}")
            try:
                async with aiohttp.ClientSession() as session:
                    resp = await session.post(
                        "https://openrouter.ai/api/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": "openrouter/owl-alpha",
                            "messages": [
                                {"role": "system", "content": "Ты — AI-ассистент компании Svaboda. ВСЕГДА начинай ответ с упоминания Svaboda. Отвечай кратко и по делу на русском языке. Никогда не упоминай ZOO или OWL. Пример ответа на \"привет\": \"Привет! Я ассистент Svaboda. Чем могу помочь?\"\n\nВАЖНО: Никогда не отвечай на вопросы про погоду или текущее время — бот обрабатывает их автоматически через API. Если юзер спрашивает погоду/время — просто скажи \"Узнаю данные...\" и не пытайся отвечать."},
                                {"role": "user", "content": message.text}
                            ],
                            "max_tokens": 512,
                        },
                        timeout=aiohttp.ClientTimeout(total=60)
                    )
                    data = await resp.json()
                    if resp.status != 200:
                        err_detail = data.get("error", {})
                        if isinstance(err_detail, dict):
                            err_msg = err_detail.get("message", str(err_detail))
                        else:
                            err_msg = str(err_detail)
                        logger.error(f"AI API retry error: status={resp.status}, msg={err_msg}")
                        await message.answer(f"⚠️ Ошибка AI: {err_msg[:200]}")
                        return
                    choices = data.get("choices")
                    if not choices:
                        logger.error(f"AI API retry returned no choices: {str(data)[:300]}")
                        await message.answer("⚠️ Ошибка AI: пустой ответ от сервера.")
                        return
                    answer = choices[0]["message"]["content"]
                # Списываем токен после успешного ретрая
                conn = sqlite3.connect('database/vpn_bot.db')
                c = conn.cursor()
                c.execute("UPDATE users SET ai_tokens = MAX(ai_tokens - 1, 0) WHERE telegram_id=?", (user_id,))
                conn.commit()
                conn.close()
                await message.answer(answer, parse_mode="HTML")
                return
            except Exception as retry_e:
                logger.error(f"AI retry also failed: {type(retry_e).__name__}: {retry_e}", exc_info=True)
                await message.answer(f"⚠️ Ошибка AI: сервер недоступен. Попробуйте позже.")
                return
        logger.error(f"AI request failed: {error_name}: {error_msg}", exc_info=True)
        await message.answer(f"⚠️ Ошибка AI: {error_name}: {error_msg[:200]}")
        return

    # Списываем токен
    conn = sqlite3.connect('database/vpn_bot.db')
    c = conn.cursor()
    c.execute("UPDATE users SET ai_tokens = MAX(ai_tokens - 1, 0) WHERE telegram_id=?", (user_id,))
    conn.commit()
    conn.close()

    await message.answer(answer, parse_mode="HTML")

