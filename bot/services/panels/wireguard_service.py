"""
Высокоуровневый сервис для управления AmneziaWG (и обычным WireGuard).

Обёртка над wireguard_ssh.py — предоставляет простой API для:
- Создания нового пира (генерация ключей + добавление на сервер)
- Удаления пира
- Генерации клиентского конфига (AmneziaWG или WireGuard)
- Получения информации о сервере
"""
import logging
from typing import Optional, Dict, Any

from bot.services.panels.wireguard_ssh import (
    create_wg_peer,
    delete_wg_peer,
    get_server_public_key,
    generate_keypair,
    add_peer,
    remove_peer,
    get_next_ip,
    SERVER_ENDPOINT,
    DNS,
)

logger = logging.getLogger(__name__)

# ============================================================================
# AmneziaWG параметры (for Keenetic compatibility — standard WG fields only)
# ============================================================================

# Рабочие параметры AmneziaWG сервера
AMNEZIA_ENABLED = True

# AmneziaWG параметры для генерации конфига клиента
# (Keenetic игнорирует неизвестные поля, но Amnezia-клиент их использует)
AMNEZIA_JC = 4
AMNEZIA_JMIN = 10
AMNEZIA_JMAX = 50
AMNEZIA_S1 = 45
AMNEZIA_S2 = 147
AMNEZIA_H1 = 2001988525
AMNEZIA_H2 = 531776540
AMNEZIA_H3 = 686258694
AMNEZIA_H4 = 1487611350

# Публичный ключ сервера (для AmneziaWG клиентов)
AMNEZIA_SERVER_PUBLIC_KEY = "05jVes6aр3a7O6NJwTVU1PS/R8/tr39XLRURs+ahMRk="


async def create_peer(amnezia: bool = False) -> Dict[str, Any]:
    """
    Создаёт новый WireGuard / AmneziaWG пир на сервере.

    Args:
        amnezia: True для AmneziaWG (добавляет параметры обфускации)

    Returns:
        dict: {
            'private_key': str,
            'public_key': str,
            'preshared_key': str,
            'allowed_ip': str,
            'endpoint': str,
            'dns': str,
            'is_amnezia': bool,
            'amnezia_jc': int (если amnezia=True),
            'amnezia_jmin': int,
            'amnezia_jmax': int,
            'amnezia_s1': int,
            'amnezia_s2': int,
            'server_public_key': str,
        }
    """
    try:
        if amnezia:
            peer_data = await _create_amnezia_peer()
        else:
            peer_data = await create_wg_peer()
        logger.info(f"WG peer created: IP={peer_data['allowed_ip']}, amnezia={amnezia}")
        return peer_data
    except Exception as e:
        logger.error(f"create_peer error: {e}")
        raise


async def _create_amnezia_peer() -> Dict[str, Any]:
    """
    Создаёт AmneziaWG пир на сервере.
    Использует параметры реального AmneziaWG сервера.
    """
    from bot.services.panels.wireguard_ssh import (
        generate_keypair, add_peer, get_next_ip, SERVER_PSK,
    )
    from bot.utils.key_generator import generate_amnezia_wg_config_text

    # Генерируем ключи клиента
    kp = await generate_keypair()
    ip = await get_next_ip()

    # Добавляем пир на сервер
    await add_peer(kp["public_key"], ip)

    return {
        "private_key": kp["private_key"],
        "public_key": kp["public_key"],
        "preshared_key": SERVER_PSK,
        "allowed_ip": ip,
        "endpoint": SERVER_ENDPOINT,
        "dns": DNS,
        "is_amnezia": True,
        "amnezia_jc": AMNEZIA_JC,
        "amnezia_jmin": AMNEZIA_JMIN,
        "amnezia_jmax": AMNEZIA_JMAX,
        "amnezia_s1": AMNEZIA_S1,
        "amnezia_s2": AMNEZIA_S2,
        "server_public_key": await get_server_public_key(),
    }


async def delete_peer(public_key: str) -> bool:
    """
    Удаляет WireGuard / AmneziaWG пир с сервера.

    Args:
        public_key: Публичный ключ пира

    Returns:
        True если успешно
    """
    try:
        result = await delete_wg_peer(public_key)
        logger.info(f"Peer deleted: {public_key[:20]}...")
        return result
    except Exception as e:
        logger.error(f"delete_peer error: {e}")
        raise


async def get_server_info() -> Dict[str, Any]:
    """
    Возвращает информацию о сервере для генерации конфигов.

    Returns:
        dict с ключами сервера
    """
    pubkey = await get_server_public_key()
    return {
        "public_key": pubkey,
        "endpoint": SERVER_ENDPOINT,
        "dns": DNS,
        "amnezia": AMNEZIA_ENABLED,
        "amnezia_jc": AMNEZIA_JC,
        "amnezia_jmin": AMNEZIA_JMIN,
        "amnezia_jmax": AMNEZIA_JMAX,
        "amnezia_s1": AMNEZIA_S1,
        "amnezia_s2": AMNEZIA_S2,
        "amnezia_h1": AMNEZIA_H1,
        "amnezia_h2": AMNEZIA_H2,
        "amnezia_h3": AMNEZIA_H3,
        "amnezia_h4": AMNEZIA_H4,
    }
