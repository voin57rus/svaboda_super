"""
Выбор протокола VPN перед покупкой ключа.
"""

import logging
import io
import qrcode

from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext

from bot.utils.text import safe_edit_or_send
from bot.keyboards.user import (
    protocol_select_kb,
    home_only_kb
)


logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == "buy_key")
async def buy_key_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    """
    Показывает выбор протокола VPN.
    """

    await state.clear()

    await safe_edit_or_send(
        callback.message,
        "🔐 <b>Выберите протокол VPN</b>\n\n"
        "🔵 <b>VLESS + Reality</b> — современный протокол\n"
        "🟢 <b>WireGuard</b> — быстрый и стабильный VPN\n"
        "🟠 <b>AmneziaWG</b> — обход DPI блокировок\n"
        "🟣 <b>Xray (VLESS+WS+TLS)</b> — маскировка под HTTPS",
        reply_markup=protocol_select_kb()
    )

    await callback.answer()


@router.callback_query(F.data == "protocol_vless")
async def protocol_vless_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    """
    Выбор VLESS.
    """

    from config import ADMIN_IDS

    if callback.from_user.id in ADMIN_IDS:

        await state.update_data(
            protocol="vless"
        )

        await _admin_instant_key(
            callback,
            state,
            callback.from_user.id,
            "vless"
        )

        return


    data = await state.get_data()

    title = data.get(
        "protocol_title",
        "VLESS Reality"
    )

    await state.update_data(
        protocol="vless",
        protocol_title=title
    )


    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb


    tariffs = get_all_tariffs(
        include_hidden=False,
        protocol="vless"
    )


    rub_tariffs = [
        t for t in tariffs
        if t.get("price_rub")
        and t["price_rub"] > 0
    ]


    if not rub_tariffs:

        await safe_edit_or_send(
            callback.message,
            "😔 <b>Нет доступных тарифов для VLESS.</b>",
            reply_markup=home_only_kb()
        )

        await callback.answer()
        return


    await safe_edit_or_send(
        callback.message,
        f"💳 <b>Купить ключ ({title})</b>\n\n"
        "Выберите тариф:",
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key",
            is_platega=True
        )
    )

    await callback.answer()



@router.callback_query(F.data == "protocol_xray")
async def protocol_xray_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    """
    Выбор Xray.
    """

    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb


    await state.update_data(
        protocol="xray",
        protocol_title="Xray WS + TLS"
    )


    tariffs = get_all_tariffs(
        include_hidden=False,
        protocol="xray"
    )


    rub_tariffs = [
        t for t in tariffs
        if t.get("price_rub")
        and t["price_rub"] > 0
    ]


    if not rub_tariffs:

        await safe_edit_or_send(
            callback.message,
            "😔 <b>Нет доступных тарифов для Xray.</b>",
            reply_markup=home_only_kb()
        )

        await callback.answer()
        return



    await safe_edit_or_send(
        callback.message,
        "💳 <b>Купить ключ (Xray WS + TLS)</b>\n\n"
        "Выберите тариф:",
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key",
            is_platega=True
        )
    )


    await callback.answer()



@router.callback_query(F.data == "protocol_wireguard")
async def protocol_wireguard_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    """
    Выбор WireGuard.
    """

    from config import ADMIN_IDS


    if callback.from_user.id in ADMIN_IDS:

    data = await state.get_data()

    protocol = data.get(
        "protocol",
        "wireguard"
    )

    await _admin_instant_key(
        callback,
        state,
        callback.from_user.id,
        protocol
    )

    return

    await _admin_instant_key(
        callback,
        state,
        callback.from_user.id,
        protocol
    )

    return


    await _show_wg_tariffs(
        callback,
        state,
        False
    )



@router.callback_query(F.data == "protocol_amnezia")
async def protocol_amnezia_handler(
    callback: CallbackQuery,
    state: FSMContext
):
    """
    Выбор AmneziaWG.
    """

    from config import ADMIN_IDS


    if callback.from_user.id in ADMIN_IDS:

        await state.update_data(
            protocol="amnezia"
        )

        await _admin_instant_key(
            callback,
            state,
            callback.from_user.id,
            "amnezia"
        )

        return


    await _show_wg_tariffs(
        callback,
        state,
        True
    )


async def _admin_instant_key(
    callback: CallbackQuery,
    state: FSMContext,
    telegram_id: int,
    protocol: str
):
    """
    Создание ключа администратору без оплаты.
    """

    from database.requests import (
        get_user_by_telegram_id,
        get_or_create_user,
        create_wg_key,
        create_initial_vpn_key
    )


    logger.info(
        f"Admin instant key: {telegram_id}, protocol={protocol}"
    )


    user = get_user_by_telegram_id(
        telegram_id
    )


    if not user:

        user, _ = get_or_create_user(
            telegram_id,
            callback.from_user.username or ""
        )


    user_id = user["id"]

    days = 365


    try:
        await callback.message.edit_text(
            "⏳ Создаём ключ..."
        )
    except Exception:
        pass



    if protocol in (
        "wireguard",
        "amnezia"
    ):

        from bot.services.panels.wireguard_service import (
            create_peer
        )


        is_amnezia = (
            protocol == "amnezia"
        )


        peer_data = await create_peer(
            amnezia=is_amnezia
        )


        key_id = create_wg_key(
            user_id=user_id,
            tariff_id=0,
            private_key=peer_data["private_key"],
            public_key=peer_data["public_key"],
            preshared_key=peer_data["preshared_key"],
            allowed_ip=peer_data["allowed_ip"],
            protocol=protocol,
            duration_days=days
        )


        server_pubkey = peer_data.get(
            "server_public_key",
            ""
        )


        if not server_pubkey:

            from bot.services.panels.wireguard_ssh import (
                get_server_public_key
            )

            server_pubkey = await get_server_public_key()



        if is_amnezia:

            from bot.services.panels.wireguard_service import (
                AMNEZIA_JC,
                AMNEZIA_JMIN,
                AMNEZIA_JMAX,
                AMNEZIA_S1,
                AMNEZIA_S2,
                AMNEZIA_H1,
                AMNEZIA_H2,
                AMNEZIA_H3,
                AMNEZIA_H4
            )


            from bot.utils.key_generator import (
                generate_amnezia_wg_config_text
            )


            config = generate_amnezia_wg_config_text(
                client_private_key=peer_data["private_key"],
                client_ip=peer_data["allowed_ip"],
                server_public_key=server_pubkey,
                preshared_key=peer_data["preshared_key"],
                endpoint="87.120.165.232:31497",
                dns="77.88.8.8",

                jc=AMNEZIA_JC,
                jmin=AMNEZIA_JMIN,
                jmax=AMNEZIA_JMAX,

                s1=AMNEZIA_S1,
                s2=AMNEZIA_S2,

                h1=AMNEZIA_H1,
                h2=AMNEZIA_H2,
                h3=AMNEZIA_H3,
                h4=AMNEZIA_H4
            )


        else:

            from bot.utils.key_generator import (
                generate_wg_config_text
            )


            config = generate_wg_config_text(
                client_private_key=peer_data["private_key"],
                client_ip=peer_data["allowed_ip"],
                server_public_key=server_pubkey,
                preshared_key=peer_data["preshared_key"],
                endpoint="87.120.165.232:31497",
                dns="77.88.8.8"
            )



        name = (
            "AmneziaWG"
            if is_amnezia
            else "WireGuard"
        )



        await callback.message.edit_text(
            f"🟢 <b>{name} ключ создан!</b>\n\n"
            f"🔑 ID: <code>{key_id}</code>\n"
            f"🌐 IP: <code>{peer_data['allowed_ip']}</code>\n"
            f"📅 Срок: {days} дней",
            parse_mode="HTML"
        )



        qr = qrcode.make(
            config
        )


        qr_bytes = io.BytesIO()


        qr.save(
            qr_bytes,
            format="PNG"
        )


        qr_bytes.seek(0)



        await callback.message.answer_photo(
            BufferedInputFile(
                qr_bytes.read(),
                filename="vpn_qr.png"
            ),
            caption=(
                f"📸 QR код {name}\n\n"
                "Отсканируйте его в приложении VPN."
            )
        )



        await callback.message.answer_document(
            BufferedInputFile(
                config.encode(),
                filename=f"{name}_{key_id}.conf"
            ),
            caption="📂 Конфигурация VPN"
        )



    else:

        key_id = create_initial_vpn_key(
            user_id,
            0,
            days,
            traffic_limit=0
        )


        title = (
            "Xray"
            if protocol == "xray"
            else "VLESS"
        )


        await callback.message.edit_text(
            f"🔵 <b>{title} ключ создан!</b>\n\n"
            f"🔑 ID: <code>{key_id}</code>\n"
            f"📅 Срок: {days} дней\n"
            f"📊 Трафик: безлимит",
            parse_mode="HTML"
        )


        from bot.handlers.user.keys import (
            show_key_details
        )


        await show_key_details(
            telegram_id=telegram_id,
            key_id=key_id,
            message=callback.message,
            is_callback=False,
            prepend_text=(
                f"🔵 <b>{title} ключ создан!</b>\n\n"
            )
        )


    
    await callback.answer()

async def _show_wg_tariffs(
    callback: CallbackQuery,
    state: FSMContext,
    amnezia: bool
):
    """
    Показывает тарифы WireGuard / AmneziaWG.
    """

    from database.requests import get_all_tariffs
    from bot.keyboards.user import tariff_select_kb


    protocol = (
        "amnezia"
        if amnezia
        else "wireguard"
    )


    proto_label = (
        "AmneziaWG"
        if amnezia
        else "WireGuard"
    )


    await state.update_data(
        protocol=protocol
    )


    tariffs = get_all_tariffs(
        include_hidden=False,
        protocol=protocol
    )


    rub_tariffs = [
        t for t in tariffs
        if t.get("price_rub")
        and t["price_rub"] > 0
    ]


    if not rub_tariffs:

        await safe_edit_or_send(
            callback.message,
            f"😔 <b>Нет доступных тарифов для {proto_label}.</b>",
            reply_markup=home_only_kb()
        )

        await callback.answer()
        return



    await safe_edit_or_send(
        callback.message,
        f"💳 <b>Купить ключ ({proto_label})</b>\n\n"
        "Выберите тариф:",
        reply_markup=tariff_select_kb(
            rub_tariffs,
            back_callback="buy_key",
            is_platega=True
        )
    )


    await callback.answer()
