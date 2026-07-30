"""
Сервис для управления WireGuard / AmneziaWG.
Все команды выполняются напрямую через subprocess (не через SSH).
"""
import asyncio
import json
import logging
import subprocess
from datetime import datetime
from typing import Dict, Any

logger = logging.getLogger(__name__)

WG_INTERFACE = "wg0"
SERVER_ENDPOINT = "87.120.165.232:47981"
DNS = "77.88.8.8"
SERVER_PUBLIC_KEY = "T/OjcoQddUk3x+rilRh7/R3h90n7zc+izXX49ivwvRU="
SERVER_PSK = "VWStyuYRXZu6dwmrS7FkmYDNGX8MuY8ze7DoinYuiLs="
DOCKER_CONTAINER = "amnezia-awg"


def _docker(cmd: str) -> str:
    """Выполняет команду в контейнере Docker."""
    full_cmd = f"docker exec {DOCKER_CONTAINER} {cmd}"
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30)
    if result.stderr:
       logger.error(f"docker error: {result.stderr}")
    if result.returncode != 0:
       logger.error(f"docker return code: {result.returncode}")

    return (result.stdout or "").strip()


def _docker_write_file(path: str, content: str) -> None:
    """Записывает текст в файл внутри контейнера через docker cp."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write(content)
        tmp_path = f.name
    try:
        full_cmd = f"docker cp {tmp_path} {DOCKER_CONTAINER}:{path}"
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30)
        if result.stderr:
            logger.error(f"docker cp error: {result.stderr}")
        if result.returncode != 0:
            logger.error(f"docker cp return code: {result.returncode}")
    finally:
        os.unlink(tmp_path)


def _clean(s: str) -> str:
    """Очищает строку от пробелов и переносов."""
    return s.strip().replace("\n", "").replace("\r", "").replace(" ", "")


async def generate_keypair():
    """Генерирует пару ключей."""
    priv = _docker("wg genkey")
    private_key = _clean(priv)
    if len(private_key) != 44:
        raise RuntimeError(f"Invalid key length: {len(private_key)}")
    pub = _docker(f"echo \"{private_key}\" | wg pubkey")
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


async def add_peer(client_name: str) -> dict:
    """Добавляет пир через bandju-panel API."""
    logger.info(f"ADD_PEER START name={client_name}")

    import subprocess
    script = f"""
import sys, json
sys.path.insert(0, "/app")
from modules import amneziawg
result = amneziawg.add_client("{client_name}", "{DOCKER_CONTAINER}")
print(json.dumps(result))
"""
    # Write script to temp file and execute in panel container
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        tmp_path = f.name
    try:
        full_cmd = f"docker cp {tmp_path} bandju-panel:/tmp/wg_add.py && docker exec bandju-panel python3 /tmp/wg_add.py"
        result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=30)
        os.unlink(tmp_path)
    except Exception as e:
        os.unlink(tmp_path)
        raise RuntimeError(f"Panel API error: {e}")

    if result.returncode != 0:
        raise RuntimeError(f"Panel API failed: {result.stderr}")

    data = json.loads(result.stdout)
    if not data.get("ok"):
        raise RuntimeError(data.get("error", "Unknown panel error"))

    client = data["client"]
    config = data["config"]

    return {
        "private_key": None,  # In config text
        "public_key": client["public_key"],
        "preshared_key": client["preshared_key"],
        "allowed_ip": client["ip"],
        "config": config,
        "client_name": client["name"],
    }

    logger.info(f"Peer added: {public_key[:20]}... IP={allowed_ip}")
    return True

async def remove_peer(public_key: str) -> bool:
    """Удаляет пир из интерфейса и из конфига."""
    _docker(f"wg set {WG_INTERFACE} peer {public_key} remove")
    # Удаляем блок [Peer] с этим ключом из конфига (делаем на хосте, python3 нет в контейнере)
    wg_conf = _docker(f"cat /opt/amnezia/awg/wg0.conf")
    import re
    # Удаляем блок [Peer]... до следующего [Peer] или конца файла
    pattern = r'\n?\[Peer\]\nPublicKey = ' + re.escape(public_key) + r'.*?(?=\n\[Peer\]|\Z)'
    new_conf = re.sub(pattern, '', wg_conf, flags=re.DOTALL)
    _docker_write_file("/opt/amnezia/awg/wg0.conf", new_conf)
    logger.info(f"Peer removed: {public_key[:20]}...")
    return True


async def create_wg_peer() -> Dict[str, Any]:
    """Полный цикл создания AmneziaWG пира."""
    logger.info("CREATE_WG_PEER START")
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
        "is_amnezia": True,
        "server_public_key": SERVER_PUBLIC_KEY,
    }


async def delete_wg_peer(public_key: str) -> bool:
    """Удаляет AmneziaWG пир."""
    return await remove_peer(public_key)


async def get_server_public_key() -> str:
    """Возвращает публичный ключ сервера."""
    return SERVER_PUBLIC_KEY


async def generate_preshared_key() -> str:
    """Генерирует PSK."""
    return SERVER_PSK
