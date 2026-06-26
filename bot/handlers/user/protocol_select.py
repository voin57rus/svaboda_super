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
        "🟢 <b>WireGuard</b> — быстрый и надёжный VPN\n"
        "🟠 <b>AmneziaWG</b> — обходит DPI и блокировки\n"
        "🟣 <b>Xray (Vless+WS+TLS)</b> — маскировка под HTTPS",
        reply_markup=protocol_select_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "protocol_vless")
async def protocol_vless_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал VLESS."""
    from config import ADMIN_IDS
    is_admin_user = callback.from_user.id in ADMIN_IDS

    if is_admin_user:
        await state.update_data(protocol="vless")
        await _admin_instant_key(callback, state, callback.from_user.id, "vless")
        return

    # Обычный пользователь — показываем тарифы только для VLESS
    await state.update_data(protocol="vless")

    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb
    tariffs = get_all_tariffs(include_hidden=False, protocol="vless")
    rub_tariffs = [t for t in tariffs if t.get('price_rub') and t['price_rub'] > 0]
    if not rub_tariffs:
        await safe_edit_or_send(callback.message, '😔 <b>Нет доступных тарифов для VLESS.</b>', reply_markup=home_only_kb())
        await callback.answer()
        return
    await safe_edit_or_send(callback.message, '💳 <b>Купить ключ (VLESS)</b>\\n\\nВыберите тариф:', reply_markup=tariff_select_kb(rub_tariffs, back_callback='buy_key', is_platega=True))
    await callback.answer()


@router.callback_query(F.data == "protocol_wireguard")
async def protocol_wireguard_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал WireGuard."""
    from config import ADMIN_IDS
    is_admin_user = callback.from_user.id in ADMIN_IDS
    if is_admin_user:
        await state.update_data(protocol="wireguard")
        await _admin_instant_key(callback, state, callback.from_user.id, "wireguard")
        return
    await _show_wg_tariffs(callback, state, amnezia=False)


@router.callback_query(F.data == "protocol_amnezia")
async def protocol_amnezia_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал AmneziaWG."""
    from config import ADMIN_IDS
    is_admin_user = callback.from_user.id in ADMIN_IDS
    if is_admin_user:
        await state.update_data(protocol="amnezia")
        await _admin_instant_key(callback, state, callback.from_user.id, "amnezia")
        return
    await _show_wg_tariffs(callback, state, amnezia=True)


@router.callback_query(F.data == "protocol_xray")
async def protocol_xray_handler(callback: CallbackQuery, state: FSMContext):
    """Пользователь выбрал Xray — тот же flow что и VLESS."""
    await protocol_vless_handler(callback, state)


async def _admin_instant_key(callback: CallbackQuery, state: FSMContext, telegram_id: int, protocol: str):
    """Сразу создаёт ключ для админа на 365 дней, без оплаты и без тарифов."""
    from database.requests import get_user_by_telegram_id, get_or_create_user
    from bot.services.panels.wireguard_service import create_peer
    from bot.utils.key_generator import generate_amnezia_wg_config_text, generate_wg_config_text
    from config import ADMIN_IDS

    logger.info(f"Admin {telegram_id} instant key: protocol={protocol}")

    # Получаем / создаём пользователя
    user = get_user_by_telegram_id(telegram_id)
    if not user:
        user, _ = get_or_create_user(telegram_id, callback.from_user.username or "")
    user_id = user["id"]

    days = 365

    try:
        await callback.message.edit_text("⏳ Создаём ключ...")
    except Exception:
        pass

    if protocol in ("wireguard", "amnezia"):
        # WG / AmneziaWG — создаём пир на сервере
        is_amnezia = protocol == "amnezia"
        peer_data = await create_peer(amnezia=is_amnezia)

        from database.requests import create_wg_key
        key_id = create_wg_key(
            user_id=user_id,
            tariff_id=0,
            private_key=peer_data["private_key"],
            public_key=peer_data["public_key"],
            preshared_key=peer_data["preshared_key"],
            allowed_ip=peer_data["allowed_ip"],
            protocol=protocol,
            duration_days=days,
        )

        # Получаем server public key
        server_pubkey = peer_data.get("server_public_key", "")
        if not server_pubkey:
            from bot.services.panels.wireguard_ssh import get_server_public_key
            server_pubkey = await get_server_public_key()

        if is_amnezia:
            from bot.services.panels.wireguard_service import (
                AMNEZIA_JC, AMNEZIA_JMIN, AMNEZIA_JMAX,
                AMNEZIA_S1, AMNEZIA_S2, AMNEZIA_H1, AMNEZIA_H2, AMNEZIA_H3, AMNEZIA_H4,
            )
            wg_config = generate_amnezia_wg_config_text(
                client_private_key=peer_data["private_key"],
                client_ip=peer_data["allowed_ip"],
                server_public_key=server_pubkey,
                preshared_key=peer_data["preshared_key"],
                endpoint="87.120.165.232:31497",
                dns="77.88.8.8",
                jc=AMNEZIA_JC, jmin=AMNEZIA_JMIN, jmax=AMNEZIA_JMAX,
                s1=AMNEZIA_S1, s2=AMNEZIA_S2,
                h1=AMNEZIA_H1, h2=AMNEZIA_H2, h3=AMNEZIA_H3, h4=AMNEZIA_H4,
            )
        else:
            wg_config = generate_wg_config_text(
                client_private_key=peer_data["private_key"],
                client_ip=peer_data["allowed_ip"],
                server_public_key=server_pubkey,
                preshared_key=peer_data["preshared_key"],
                endpoint="87.120.165.232:31497",
                dns="77.88.8.8",
            )

        await callback.message.edit_text(
            f"{'🟠' if is_amnezia else '🟢'} <b>{'AmneziaWG' if is_amnezia else 'WireGuard'} ключ создан!</b>\n\n"
            f"🔑 ID: <code>{key_id}</code>\n"
            f"🌐 IP: <code>{peer_data['allowed_ip']}</code>\n"
            f"📅 Срок: {days} дней\n\n"
            f"👇 Конфигурация отправлена ниже.",
            parse_mode="HTML",
        )

        # Отправляем конфиг
        import qrcode as qr_module
        from aiogram.types import BufferedInputFile
        import io

        qr = qr_module.make(wg_config)
        qr_bytes = io.BytesIO()
        qr.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)

        await callback.message.answer_photo(
            photo=BufferedInputFile(qr_bytes.read(), filename="wg_qr.png"),
            caption=f"{'🟠' if is_amnezia else '🟢'} <b>Ваш {'AmneziaWG' if is_amnezia else 'WireGuard'} ключ!</b>\n\n📸 Отсканируйте QR-код.",
            parse_mode="HTML",
        )

        config_bytes = wg_config.encode("utf-8")
        await callback.message.answer_document(
            document=BufferedInputFile(config_bytes, filename=f"wireguard_config_{key_id}.conf"),
            caption="📂 <b>Файл конфигурации</b>",
            parse_mode="HTML",
        )

    else:
        # VLESS / Xray — создаём черновик ключа и сразу показываем
        from database.requests import create_initial_vpn_key
        key_id = create_initial_vpn_key(user_id, 0, days, traffic_limit=0)

        await callback.message.edit_text(
            f"🔵 <b>VLESS ключ создан!</b>\n\n"
            f"🔑 ID: <code>{key_id}</code>\n"
            f"📅 Срок: {days} дней\n"
            f"📊 Трафик: безлимит\n\n"
            f"Перейдите к настройке для получения конфигурации.",
            parse_mode="HTML",
        )

        # Сразу показываем детали ключа
        from bot.handlers.user.keys import show_key_details
        await show_key_details(
            telegram_id=telegram_id,
            key_id=key_id,
            message=callback.message,
            is_callback=False,
            prepend_text=f"🔵 <b>VLESS ключ создан!</b>\n\n",
        )

    await callback.answer()


async def _show_wg_tariffs(callback: CallbackQuery, state: FSMContext, amnezia: bool):
    """Показывает тарифы для WireGuard/AmneziaWG (только для обычных пользователей)."""
    from database.requests import get_all_tariffs, get_user_internal_id, create_pending_order

    protocol = "amnezia" if amnezia else "wireguard"
    proto_label = "AmneziaWG" if amnezia else "WireGuard"
    await state.update_data(protocol=protocol)

    # Показываем тарифы только для выбранного протокола
    from bot.keyboards.user import tariff_select_kb
    tariffs = get_all_tariffs(include_hidden=False, protocol=protocol)
    rub_tariffs = [t for t in tariffs if t.get('price_rub') and t['price_rub'] > 0]
    if not rub_tariffs:
        await safe_edit_or_send(callback.message, f'😔 <b>Нет доступных тарифов для {proto_label}.</b>', reply_markup=home_only_kb())
        await callback.answer()
        return
    await safe_edit_or_send(callback.message, f'💳 <b>Купить ключ ({proto_label})</b>\n\nВыберите тариф:', reply_markup=tariff_select_kb(rub_tariffs, back_callback='buy_key', is_platega=True))
    await callback.answer()
