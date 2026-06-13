"""
Сервис для управления WireGuard / AmneziaWG через SSH.
Обновлён: правильные ключи сервера, порт 32672, AmneziaWG параметры.
"""
import asyncio
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger(__name__)

WG_INTERFACE = "wg0"
WG_CONFIG_PATH = "/etc/wireguard/wg0.conf"

# Рабочие параметры сервера
SERVER_ENDPOINT = "87.120.165.232:32672"
DNS = "77.88.8.8"

# Публичный ключ сервера (AmneziaWG)
SERVER_PUBLIC_KEY = "05jVes6ap3a7O6NJwTVU1PS/R8/tr39XLRURs+ahMRk="

# Единый PSK для всех пиров
SERVER_PSK = "94IM6kjj4pv4JB77c0v7aml2UPw8+MH9fFZo7NNcuXs="

# SSH доступ
SSH_HOST = "87.120.165.232"
SSH_USER = "root"
SSH_PASSWORD = "pavi17lion98A6"


async def _ssh(cmd: str, timeout: int = 30) -> Tuple[str, str]:
    """Выполняет команду на сервере через asyncssh."""
    import asyncssh
    async with asyncssh.connect(
        SSH_HOST, username=SSH_USER,
        password=SSH_PASSWORD, known_hosts=None,
        connect_timeout=15
    ) as conn:
        result = await asyncio.wait_for(
            conn.run(cmd, check=False), timeout=timeout
        )
        return (result.stdout or "").strip(), (result.stderr or "").strip()


def _clean(s: str) -> str:
    """Очищает строку от пробелов и переносов."""
    return s.strip().replace('\n', '').replace('\r', '').replace(' ', '')


async def generate_keypair():
    """Генерирует пару ключей на сервере."""
    priv, _ = await _ssh(f"docker exec amnezia-awg wg genkey")
    private_key = _clean(priv)
    if len(private_key) != 44:
        raise RuntimeError(f"Invalid key length: {len(private_key)}")
    pub, _ = await _ssh(f"echo '{private_key}' | docker exec amnezia-awg wg pubkey")
    public_key = _clean(pub)
    if len(public_key) != 44:
        raise RuntimeError(f"Invalid pubkey length: {len(public_key)}")
    return {"private_key": private_key, "public_key": public_key}


async def get_used_ips() -> set:
    """Возвращает использованные IP."""
    out, _ = await _ssh(f"docker exec amnezia-awg wg show {WG_INTERFACE} allowed-ips")
    ips = set()
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            ips.add(parts[1].split("/")[0])
    return ips


async def get_next_ip() -> str:
    """Находим свободный IP, начиная с 10.8.1.2 (10.8.1.1 — сам сервер)."""
    used = await get_used_ips()
    for i in range(2, 254):
        ip = f"10.8.1.{i}"
        if ip not in used:
            return ip
    raise RuntimeError("No free IP")


async def add_peer(public_key: str, allowed_ip: str) -> bool:
    """Добавляет пир через wg set в контейнер."""
    psk_file = f"/tmp/psk_{public_key[:8]}"
    await _ssh(f"echo '{SERVER_PSK}' > {psk_file}")
    await _ssh(
        f"docker exec amnezia-awg wg set {WG_INTERFACE} peer {public_key} "
        f"allowed-ips {allowed_ip}/32 preshared-key {psk_file}"
    )
    await _ssh(f"rm -f {psk_file}")
    await _ssh(f"docker exec amnezia-awg wg-quick save {WG_INTERFACE}")
    logger.info(f"Peer added: {public_key[:20]}... IP={allowed_ip}")
    return True


async def remove_peer(public_key: str) -> bool:
    """Удаляет пир."""
    await _ssh(f"docker exec amnezia-awg wg set {WG_INTERFACE} peer {public_key} remove")
    await _ssh(f"docker exec amnezia-awg wg-quick save {WG_INTERFACE}")
    logger.info(f"Peer removed: {public_key[:20]}...")
    return True


async def create_wg_peer() -> Dict[str, Any]:
    """
    Полный цикл создания обычного WireGuard пира.
    """
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
    # Возвращаем закешированный ключ
    return SERVER_PUBLIC_KEY


async def generate_preshared_key() -> str:
    """Генерирует PSK."""
    return SERVER_PSK
