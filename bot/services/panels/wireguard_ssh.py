"""
Сервис для управления WireGuard / AmneziaWG.
Все команды выполняются напрямую через subprocess (не через SSH).
"""
import asyncio
import logging
import subprocess
from typing import Dict, Any

logger = logging.getLogger(__name__)

WG_INTERFACE = "wg0"
SERVER_ENDPOINT = "87.120.165.232:32672"
DNS = "77.88.8.8"
SERVER_PUBLIC_KEY = "05jVes6ap3a7O6NJwTVU1PS/R8/tr39XLRURs+ahMRk="
SERVER_PSK = "94IM6kjj4pv4JB77c0v7aml2UPw8+MH9fFZo7NNcuXs="
DOCKER_CONTAINER = "amnezia-awg"


def _docker(cmd: str) -> str:
    """Выполняет команду в контейнере Docker."""
    full_cmd = f"docker exec {DOCKER_CONTAINER} {cmd}"
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30)
    return (result.stdout or "").strip()


def _clean(s: str) -> str:
    """Очищает строку от пробелов и переносов."""
    return s.strip().replace('\n', '').replace('\r', '').replace(' ', '')


async def generate_keypair():
    """Генерирует пару ключей."""
    priv = _docker("wg genkey")
    private_key = _clean(priv)
    if len(private_key) != 44:
        raise RuntimeError(f"Invalid key length: {len(private_key)}")
    pub = _docker(f"echo '{private_key}' | wg pubkey")
    public_key = _clean(pub)
    if len(public_key) != 44:
        raise RuntimeError(f"Invalid pubkey length: {len(public_key)}")
    return {"private_key": private_key, "public_key": public_key}


async def get_used_ips() -> set:
    """Возвращает использованные IP."""
    out = _docker(f"wg show {WG_INTERFACE} allowed-ips")
    ips = set()
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            ips.add(parts[1].split("/")[0])
    return ips


async def get_next_ip() -> str:
    """Находим свободный IP, начиная с 10.8.1.2."""
    used = await get_used_ips()
    for i in range(2, 254):
        ip = f"10.8.1.{i}"
        if ip not in used:
            return ip
    raise RuntimeError("No free IP")


async def add_peer(public_key: str, allowed_ip: str) -> bool:
    """Добавляет пир через wg set в контейнер."""
    psk_file = f"/tmp/psk_{public_key[:8]}"
    _docker(f"echo '{SERVER_PSK}' > {psk_file}")
    _docker(f"wg set {WG_INTERFACE} peer {public_key} allowed-ips {allowed_ip}/32 preshared-key {psk_file}")
    _docker(f"rm -f {psk_file}")
    _docker(f"wg-quick save {WG_INTERFACE}")
    logger.info(f"Peer added: {public_key[:20]}... IP={allowed_ip}")
    return True


async def remove_peer(public_key: str) -> bool:
    """Удаляет пир."""
    _docker(f"wg set {WG_INTERFACE} peer {public_key} remove")
    _docker(f"wg-quick save {WG_INTERFACE}")
    logger.info(f"Peer removed: {public_key[:20]}...")
    return True


async def create_wg_peer() -> Dict[str, Any]:
    """Полный цикл создания обычного WireGuard пира."""
    kp = await generate_keypair()
    ip = await get_next_ip()
    await add_peer(kp["public_key"], ip)

    return {
        "private_key": kp["private_key"],
        "public_key": kp["public_key"],
        "preshared_key": SERVER_PSK,
        "allowed_ip": ip,
        "endpoint": SERVER_ENDPOINT,
        "dns": DNS,
        "is_amnezia": False,
        "server_public_key": SERVER_PUBLIC_KEY,
    }


async def delete_wg_peer(public_key: str) -> bool:
    """Удаляет WireGuard пир."""
    return await remove_peer(public_key)


async def get_server_public_key() -> str:
    """Возвращает публичный ключ сервера."""
    return SERVER_PUBLIC_KEY


async def generate_preshared_key() -> str:
    """Генерирует PSK."""
    return SERVER_PSK
