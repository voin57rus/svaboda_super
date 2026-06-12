"""
Сервис для управления обычным WireGuard через SSH.
Сервер работает на обычном WireGuard (не AmneziaWG).
"""
import asyncio
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

WG_INTERFACE = "wg0"
WG_CONFIG_PATH = "/etc/wireguard/wg0.conf"
SERVER_ENDPOINT = "87.120.165.232:39623"
DNS = "1.1.1.1, 8.8.8.8"

# Публичный ключ сервера
SERVER_PUBLIC_KEY = "EgiubAEPrNuIC311qKGo583ZjreK8ZgT6aEHYxT5zQs="

# Единый PSK для всех пиров
SERVER_PSK = "Nr6Yz9eQC2i2J1sTcGfJ5p+lDOEJNAJAmhmwZ1oz/sU="


async def _ssh(cmd: str, timeout: int = 30) -> Tuple[str, str]:
    import asyncssh
    async with asyncssh.connect("87.120.165.232", username="root",
                                password="pavi17lion98A6", known_hosts=None,
                                connect_timeout=10) as conn:
        result = await asyncio.wait_for(conn.run(cmd, check=False), timeout=timeout)
        return (result.stdout or "").strip(), (result.stderr or "").strip()


def _clean(s: str) -> str:
    return s.strip().replace('\n', '').replace('\r', '').replace(' ', '')


async def generate_keypair():
    """Генерирует пару ключей на сервере."""
    priv, _ = await _ssh(f"wg genkey")
    private_key = _clean(priv)
    if len(private_key) != 44:
        raise RuntimeError(f"Invalid key length: {len(private_key)}")
    pub, _ = await _ssh(f"echo '{private_key}' | wg pubkey")
    public_key = _clean(pub)
    if len(public_key) != 44:
        raise RuntimeError(f"Invalid pubkey length: {len(public_key)}")
    return {"private_key": private_key, "public_key": public_key}


async def get_used_ips() -> set:
    """Возвращает использованные IP."""
    out, _ = await _ssh(f"wg show {WG_INTERFACE} allowed-ips")
    ips = set()
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            ips.add(parts[1].split("/")[0])
    return ips


async def get_next_ip() -> str:
    """Находим свободный IP, начиная с 10.8.1.2 (10.8.1.1 — сам сервер)."""
    used = await get_used_ips()
    # Пропускаем 10.8.1.1 (сервер), начинаем с 10.8.1.2
    for i in range(2, 254):
        ip = f"10.8.1.{i}"
        if ip not in used:
            return ip
    raise RuntimeError("No free IP")


async def add_peer(public_key: str, allowed_ip: str) -> bool:
    """Добавляет пир через wg set."""
    # Добавляем пир с PSK
    psk_file = f"/tmp/psk_{public_key[:8]}"
    await _ssh(f"echo '{SERVER_PSK}' > {psk_file}")
    await _ssh(f"wg set {WG_INTERFACE} peer {public_key} allowed-ips {allowed_ip}/32 preshared-key {psk_file}")
    await _ssh(f"rm -f {psk_file}")

    # Сохраняем в конфиг
    await _ssh(f"wg-quick save {WG_INTERFACE}")

    logger.info(f"Peer added: {public_key[:20]}... IP={allowed_ip}")
    return True


async def remove_peer(public_key: str) -> bool:
    """Удаляет пир."""
    await _ssh(f"wg set {WG_INTERFACE} peer {public_key} remove")
    await _ssh(f"wg-quick save {WG_INTERFACE}")
    logger.info(f"Peer removed: {public_key[:20]}...")
    return True


async def create_wg_peer() -> Dict[str, Any]:
    """Полный цикл создания пира. Без AmneziaWG — обычный WireGuard."""
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
    return await remove_peer(public_key)


async def get_server_public_key() -> str:
    return SERVER_PUBLIC_KEY
