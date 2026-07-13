"""
Админ-хендлер: бесплатное создание ключей (VLESS / WireGuard / AmneziaWP / Xray).
"""
import logging
import uuid
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from config import ADMIN_IDS
from database.requests import (
    get_vpn_key_by_id, create_vpn_key_admin, create_wg_key,
    get_all_tariffs, get_tariff_by_id, create_initial_vpn_key,
)
from bot.utils.admin import is_admin
from bot.utils.text import safe_edit_or_send
from bot.states.admin_states import AdminStates
from bot.keyboards.admin import back_and_home_kb, home_only_kb
from bot.services.panels.wireguard_service import (
    create_peer,
    AMNEZIA_JC, AMNEZIA_JMIN, AMNEZIA_JMAX,
    AMNEZIA_S1, AMNEZIA_S2,
    AMNEZIA_H1, AMNEZIA_H2, AMNEZIA_H3, AMNEZIA_H4,
)
from bot.utils.key_generator import generate_amnezia_wg_config_text, generate_wg_config_text, generate_wg_link
from bot.utils.key_sender import send_wg_key
from bot.utils.panel_email import get_panel_email_prefix
from bot.services.vpn_api import get_client_from_server_data

logger = logging.getLogger(__name__)

router = Router()


# ─── Точка входа: выбор протокола ────────────────────────────────────

@router.callback_query(F.data == "admin_free_key")
async def free_key_start(callback: CallbackQuery, state: FSMContext):
    """Кнопка '🔑 Бесплатный ключ' — выбор протокола."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔵 VLESS+Reality", callback_data="free_key_proto:vless"),
    )
    builder.row(
        InlineKeyboardButton(text="🟢 WireGuard", callback_data="free_key_proto:wireguard"),
        InlineKeyboardButton(text="🟠 AmneziaWG", callback_data="free_key_proto:amnezia"),
    )
    builder.row(
        InlineKeyboardButton(text="🟣 Xray", callback_data="free_key_proto:xray"),
    )
    builder.row(back_button())

    await callback.message.edit_text(
        "🔑 <b>Бесплатное создание ключа</b>\n\nВыберите протокол:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )
    await state.set_state(AdminStates.free_key_protocol)


def back_button():
    from aiogram.types import InlineKeyboardButton
    return InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_panel")


# ─── Выбор протокола → показ тарифов ─────────────────────────────────

@router.callback_query(F.data.startswith("free_key_proto:"))
async def free_key_select_protocol(callback: CallbackQuery, state: FSMContext):
    """Сохраняем протокол и показываем тарифы."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    proto = callback.data.split(":")[1]  # vless / wireguard / amnezia / xray
    await state.update_data(free_key_protocol=proto)

    tariffs = get_all_tariffs()
    if not tariffs:
        await callback.message.edit_text(
            "⚠️ Нет активных тарифов. Сначала создайте тарифы.",
            reply_markup=back_and_home_kb("admin_panel"),
        )
        return

    from aiogram.utils.keyboard import InlineKeyboardBuilder
    from aiogram.types import InlineKeyboardButton

    builder = InlineKeyboardBuilder()
    proto_name = {"vless": "VLESS+Reality", "wireguard": "WireGuard", "xray": "Xray", "amnezia": "AmneziaWG"}.get(proto, proto)

    for t in tariffs:
        builder.row(
            InlineKeyboardButton(
                text=f"📋 {t['name']} ({t['duration_days']} дн.)",
                callback_data=f"free_key_tariff:{proto}:{t['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_free_key"))

    await callback.message.edit_text(
        f"🔑 <b>Бесплатный ключ — {proto_name}</b>\n\nВыберите тариф:",
        reply_markup=builder.as_markup(),
        parse_mode="HTML",
    )


# ─── Выбор тарифа → выбор сервера (для VLESS/Xray) или создание (WG) ──

@router.callback_query(F.data.startswith("free_key_tariff:"))
async def free_key_select_tariff(callback: CallbackQuery, state: FSMContext):
    """Выбран тариф — для VLESS/Xray просим выбрать сервер, для WG создаём сразу."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    parts = callback.data.split(":")
    proto = parts[1]
    tariff_id = int(parts[2])

    await state.update_data(free_key_tariff_id=tariff_id)

    if proto in ("wireguard", "amnezia"):
        # WG/AWG — создаём сразу без выбора сервера
        await _create_wg_free_key(callback, state, proto, tariff_id)
    else:
        # VLESS / Xray — нужен выбор сервера
        from database.requests import get_active_servers
        servers = get_active_servers()
        if not servers:
            await callback.message.edit_text(
                "⚠️ Нет активных серверов.",
                reply_markup=back_and_home_kb("admin_panel"),
            )
            return

        from aiogram.utils.keyboard import InlineKeyboardBuilder
        from aiogram.types import InlineKeyboardButton

        builder = InlineKeyboardBuilder()
        for s in servers:
            builder.row(
                InlineKeyboardButton(
                    text=f"🖥️ {s['name']}",
                    callback_data=f"free_key_server:{proto}:{tariff_id}:{s['id']}",
                )
            )
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"free_key_proto:{proto}"))

        proto_name = {"vless": "VLESS+Reality", "xray": "Xray", "amnezia": "AmneziaWG"}.get(proto, proto)
        await callback.message.edit_text(
            f"🔑 <b>Бесплатный ключ — {proto_name}</b>\n\nВыберите сервер:",
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
        await state.set_state(AdminStates.free_key_server)


# ─── Выбор сервера для VLESS/Xray → создание ключа ─────────────────

@router.callback_query(F.data.startswith("free_key_server:"))
async def free_key_select_server(callback: CallbackQuery, state: FSMContext):
    """Для VLESS/Xray — выбран сервер, создаём ключ через API панели."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    parts = callback.data.split(":")
    proto = parts[1]
    tariff_id = int(parts[2])
    server_id = int(parts[3])

    await state.update_data(free_key_server_id=server_id)

    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.message.edit_text(
            "❌ Тариф не найден.", reply_markup=back_and_home_kb("admin_panel")
        )
        return

    # Для VLESS/Xray через панель 3X-UI — нужно знать админа-получателя
    # Используем telegram_id админа как получателя
    admin_tg_id = callback.from_user.id

    from database.requests import get_user_by_telegram_id, get_or_create_user
    user = get_user_by_telegram_id(admin_tg_id)
    if not user:
        user, _ = get_or_create_user(admin_tg_id, callback.from_user.username or "")

    from database.requests import get_server_by_id
    server = get_server_by_id(server_id)
    traffic_limit_bytes = (tariff.get("traffic_limit_gb", 0) or 0) * (1024**3)
    days = tariff.get("duration_days", 30)

    try:
        # Создаём черновик ключа
        key_id = create_initial_vpn_key(user["id"], tariff_id, days, traffic_limit=traffic_limit_bytes)

        # Создаём клиента на панели
        client = get_client_from_server_data(server)
        email = f"{get_panel_email_prefix(user)}{uuid.uuid4().hex[:5]}"
        # Определяем VLESS inbound на сервере для создания клиента
        from bot.services.panels.xui import XUIClient
        inbounds = await client.get_inbounds()
        vless_inbound = None
        for ib in inbounds:
            if ib.get('protocol') == 'vless':
                vless_inbound = ib['id']
                break
        if not vless_inbound:
            raise Exception("На сервере нет VLESS inbound")
        res = await client.add_client(
            inbound_id=vless_inbound,
            email=email,
            total_gb=traffic_limit_bytes // (1024**3) if traffic_limit_bytes else 0,
            expire_days=days if days > 0 else 365,
        )
        client_uuid = res.get('uuid', str(uuid.uuid4()))

        # Обновляем ключ в БД
        from database.requests import update_vpn_key_connection
        update_vpn_key_connection(key_id, server_id, 0, email, client_uuid)

        await callback.message.edit_text(
            f"✅ <b>Ключ создан!</b>\n\n"
            f"🔑 ID: <code>{key_id}</code>\n"
            f"📧 Email: <code>{email}</code>\n"
            f"🖥️ Сервер: {server['name']}\n"
            f"📅 Срок: {days} дней\n"
            f"📊 Трафик: {tariff.get('traffic_limit_gb', 0) or '∞'} ГБ",
            reply_markup=back_and_home_kb("admin_panel"),
            parse_mode="HTML",
        )
        logger.info(f"Admin {admin_tg_id} created free {proto} key {key_id} on server {server_id}")

    except Exception as e:
        logger.error(f"Free VLESS key creation failed: {e}")
        await callback.message.edit_text(
            f"❌ Ошибка создания ключа:\n<code>{e}</code>",
            reply_markup=back_and_home_kb("admin_panel"),
            parse_mode="HTML",
        )


# ─── Создание WG/AWG ключа ──────────────────────────────────────────

async def _create_wg_free_key(callback: CallbackQuery, state: FSMContext, proto: str, tariff_id: int):
    """Создаёт WG/AWG ключ для админа."""
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        await callback.message.edit_text(
            "❌ Тариф не найден.", reply_markup=back_and_home_kb("admin_panel")
        )
        return

    admin_tg_id = callback.from_user.id
    from database.requests import get_user_by_telegram_id
    user = get_user_by_telegram_id(admin_tg_id)
    if not user:
        from database.requests import get_or_create_user
        user, _ = get_or_create_user(admin_tg_id, callback.from_user.username or "")

    days = tariff.get("duration_days", 30)

    try:
        await callback.message.edit_text(
            "⏳ Создаётся WireGuard ключ...",
            parse_mode="HTML",
        )

        # 1. Создаём пир на сервере
        is_amnezia = proto == "amnezia"
        peer_data = await create_peer(amnezia=is_amnezia)

        # 2. Сохраняем в БД
        key_id = create_wg_key(
            user_id=user["id"],
            tariff_id=tariff_id,
            private_key=peer_data["private_key"],
            public_key=peer_data["public_key"],
            preshared_key=peer_data["preshared_key"],
            allowed_ip=peer_data["allowed_ip"],
            protocol=proto,
            duration_days=days,
        )

        # 3. Генерируем конфиг
        server_pubkey = peer_data.get("server_public_key", "")
        if not server_pubkey:
            from bot.services.panels.wireguard_ssh import get_server_public_key
            server_pubkey = await get_server_public_key()

        if is_amnezia:
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

        # 4. Отправляем конфиг админу
        import qrcode as qr_module
        from aiogram.types import BufferedInputFile
        import io

        qr = qr_module.make(wg_config)
        qr_bytes = io.BytesIO()
        qr.save(qr_bytes, format="PNG")
        qr_bytes.seek(0)

        await callback.message.answer_photo(
            photo=BufferedInputFile(qr_bytes.read(), filename="wg_qr.png"),
            caption="🟢 <b>Ваш WireGuard ключ!</b>\n\n📸 Отсканируйте QR-код.",
            parse_mode="HTML",
        )

        config_bytes = wg_config.encode("utf-8")
        await callback.message.answer_document(
            document=BufferedInputFile(
                config_bytes,
                filename=f"wireguard_config_{key_id}.conf"
            ),
            caption="📂 <b>Файл конфигурации WireGuard</b>",
            parse_mode="HTML",
        )

        logger.info(f"Admin {admin_tg_id} created free {proto} key {key_id}")

    except Exception as e:
        logger.error(f"Free WG key creation failed: {e}", exc_info=True)
        await callback.message.edit_text(
            f"❌ Ошибка создания WireGuard ключа:\n<code>{e}</code>",
            reply_markup=back_and_home_kb("admin_panel"),
            parse_mode="HTML",
        )
