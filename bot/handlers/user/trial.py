import logging
import sys
import os

# Добавляем корневую директорию, чтобы импорты работали железно
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from bot.utils.text import safe_edit_or_send
from database.requests import (
    get_all_tariffs, get_trial_tariff_id, is_trial_enabled, has_used_trial, 
    get_or_create_user, mark_trial_used, create_initial_vpn_key, 
    create_pending_order, complete_order, get_tariff_by_id, 
    create_wg_key, get_vpn_key_by_id
)
from bot.services.panels.wireguard_service import create_peer, get_server_info
from bot.utils.key_sender import send_wg_key, send_key_with_qr, format_key_copy_value
from bot.keyboards.user import key_issued_kb
from bot.utils.key_generator import generate_wg_config_text, generate_amnezia_wg_config_text

logger = logging.getLogger(__name__)

router = Router()

async def _get_trial_tariffs():
    tariffs = get_all_tariffs()
    return [t for t in tariffs if t.get('is_active')]

@router.callback_query(F.data == 'trial_subscription')
async def show_trial_subscription(callback: CallbackQuery, state: FSMContext):
    try:
        from database.requests import get_trial_tariff_ids
        selected_ids = get_trial_tariff_ids()
        if not selected_ids:
            await callback.answer('❌ Не настроено', show_alert=True)
            return
        await state.update_data(trial_selected=selected_ids)
        await trial_get_keys(callback, state)
    except Exception as e:
        logger.error(f"Error: {e}")
        await callback.message.answer(f"Ошибка: {e}")

@router.callback_query(F.data == 'trial_get_keys')
async def trial_get_keys(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get('trial_selected', [])
    if not selected: return
    user_id = callback.from_user.id
    if has_used_trial(user_id): return
    (user, _) = get_or_create_user(user_id, callback.from_user.username)
    internal_user_id = user['id']
    mark_trial_used(internal_user_id)
    
    for tariff_id in selected:
        tariff = get_tariff_by_id(tariff_id)
        if not tariff: continue
        proto = str(tariff.get('protocol', 'vless')).lower()
        if proto in ('wireguard', 'amnezia'):
            peer_data = await create_peer(amnezia=(proto == 'amnezia'))
            key_id = create_wg_key(
                user_id=internal_user_id, tariff_id=tariff_id,
                private_key=peer_data['private_key'], public_key=peer_data['public_key'],
                preshared_key=peer_data['preshared_key'], allowed_ip=peer_data['allowed_ip'],
                protocol=proto, duration_days=tariff.get('duration_days', 30),
            )
            from database.requests import update_vpn_key_sub_id
            update_vpn_key_sub_id(key_id, None)
            wg_key = get_vpn_key_by_id(key_id)
            if proto == 'amnezia':
                server_info = await get_server_info()
                wg_config = generate_amnezia_wg_config_text(
                    client_private_key=wg_key['private_key'], client_ip=wg_key['allowed_ip'],
                    server_public_key=server_info['public_key'], preshared_key=wg_key['preshared_key'],
                    endpoint=wg_key['endpoint'], dns=server_info['dns'], mtu=1420,
                    jc=server_info['amnezia_jc'], jmin=server_info['amnezia_jmin'], jmax=server_info['amnezia_jmax'],
                    s1=server_info['amnezia_s1'], s2=server_info['amnezia_s2'], h1=server_info['amnezia_h1'],
                    h2=server_info['amnezia_h2'], h3=server_info['amnezia_h3'], h4=server_info['amnezia_h4']
                )
            else:
                wg_config = generate_wg_config_text(
                    wg_key['private_key'], wg_key['allowed_ip'], wg_key['public_key'],
                    wg_key['preshared_key'], wg_key['endpoint']
                )
            await send_wg_key(callback.message, wg_config, key_id, key_issued_kb(), protocol_name=proto.capitalize())
        else:
            duration_days = tariff.get('duration_days', 1)
            traffic_limit_bytes = (tariff.get('traffic_limit_gb', 0) or 0) * 1024 ** 3
            key_id = create_initial_vpn_key(internal_user_id, tariff_id, duration_days, traffic_limit=traffic_limit_bytes)
            complete_order(create_pending_order(user_id=internal_user_id, tariff_id=tariff_id, payment_type='trial', vpn_key_id=key_id)[1])
            from database.requests import update_vpn_key_sub_id
            update_vpn_key_sub_id(key_id, None)
            new_key = get_vpn_key_by_id(key_id)
            text = f'📋 Ваш VPN-ключ ({proto.upper()})\n\n{format_key_copy_value(new_key.get("client_uuid", ""))}'
            await safe_edit_or_send(callback.message, text, reply_markup=key_issued_kb())
            try: await send_key_with_qr(callback.message, new_key, key_issued_kb(), is_new=True)
            except: pass
    await callback.answer()
