import sqlite3
import logging
import secrets
import string
import datetime
from typing import Optional, List, Dict, Any, Tuple
from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'get_setting',
    'set_setting',
    'delete_setting',
    'get_svaboda_admin_api_key',
    'set_svaboda_admin_api_key',
    'delete_svaboda_admin_api_key',
    'get_svaboda_admin_server_ip',
    'set_svaboda_admin_server_ip',
    'delete_svaboda_admin_server_ip',
    'get_ai_api_key',
    'set_ai_api_key',
    'delete_ai_api_key',
    'is_crypto_enabled',
    'is_stars_enabled',
    'is_crypto_configured',
    'is_cards_enabled',
    'is_cards_configured',
    'is_yookassa_qr_enabled',
    'is_yookassa_qr_configured',
    'get_yookassa_credentials',
    'is_wata_enabled',
    'is_wata_configured',
    'get_wata_token',
    'is_platega_enabled',
    'is_platega_configured',
    'get_platega_credentials',
    'is_cardlink_enabled',
    'is_cardlink_configured',
    'get_cardlink_credentials',
    'is_yoomoney_enabled',
    'is_yoomoney_configured',
    'get_yoomoney_credentials',
    'is_trial_enabled',
    'get_trial_tariff_id',
    'is_demo_payment_enabled',
    'get_admin_ids',
    'set_admin_ids',
    'is_ai_tariffs_enabled',
    'is_ai_standard_enabled',
    'is_ai_premium_enabled',
    'is_ai_vip_enabled',
]

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        )
        row = cursor.fetchone()
        return row['value'] if row else default

def set_setting(key: str, value: str) -> None:
    with get_db() as conn:
        conn.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        logger.info(f"Настройка обновлена: {key}")

def delete_setting(key: str) -> bool:
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        return cursor.rowcount > 0

SVABODA_ADMIN_API_KEY_SETTING = 'svaboda_admin_api_key'
SVABODA_ADMIN_SERVER_IP_SETTING = 'svaboda_admin_server_ip'

def get_svaboda_admin_api_key() -> Optional[str]:
    return get_setting(SVABODA_ADMIN_API_KEY_SETTING)

def set_svaboda_admin_api_key(api_key: str) -> None:
    set_setting(SVABODA_ADMIN_API_KEY_SETTING, api_key)

def delete_svaboda_admin_api_key() -> bool:
    return delete_setting(SVABODA_ADMIN_API_KEY_SETTING)

def get_svaboda_admin_server_ip() -> str:
    return get_setting(SVABODA_ADMIN_SERVER_IP_SETTING, '') or ''

def set_svaboda_admin_server_ip(server_ip: str) -> None:
    set_setting(SVABODA_ADMIN_SERVER_IP_SETTING, server_ip.strip())

def delete_svaboda_admin_server_ip() -> bool:
    return delete_setting(SVABODA_ADMIN_SERVER_IP_SETTING)

AI_API_KEY_SETTING = 'ai_openrouter_api_key'

def get_ai_api_key() -> Optional[str]:
    return get_setting(AI_API_KEY_SETTING)

def set_ai_api_key(api_key: str) -> None:
    set_setting(AI_API_KEY_SETTING, api_key)

def delete_ai_api_key() -> bool:
    return delete_setting(AI_API_KEY_SETTING)

def is_crypto_enabled() -> bool:
    return get_setting('crypto_enabled', '0') == '1'

def is_stars_enabled() -> bool:
    return get_setting('stars_enabled', '0') == '1'

def is_crypto_configured() -> bool:
    if not is_crypto_enabled():
        return False
    crypto_item_url = get_setting('crypto_item_url')
    return bool(crypto_item_url and crypto_item_url.strip())

def is_cards_enabled() -> bool:
    return get_setting('cards_enabled', '0') == '1'

def is_cards_configured() -> bool:
    if not is_cards_enabled():
        return False
    token = get_setting('cards_provider_token')
    return bool(token and token.strip())

def is_yookassa_qr_enabled() -> bool:
    return get_setting('yookassa_qr_enabled', '0') == '1'

def is_yookassa_qr_configured() -> bool:
    if not is_yookassa_qr_enabled():
        return False
    shop_id = get_setting('yookassa_shop_id', '')
    secret_key = get_setting('yookassa_secret_key', '')
    return bool(shop_id and shop_id.strip() and secret_key and secret_key.strip())

def get_yookassa_credentials() -> tuple[str, str]:
    shop_id = get_setting('yookassa_shop_id', '')
    secret_key = get_setting('yookassa_secret_key', '')
    return shop_id, secret_key

def is_wata_enabled() -> bool:
    return get_setting('wata_enabled', '0') == '1'

def is_wata_configured() -> bool:
    if not is_wata_enabled():
        return False
    token = get_setting('wata_jwt_token', '')
    return bool(token and token.strip())

def get_wata_token() -> str:
    return get_setting('wata_jwt_token', '') or ''

def is_platega_enabled() -> bool:
    return get_setting('platega_enabled', '0') == '1'

def is_platega_configured() -> bool:
    if not is_platega_enabled():
        return False
    merchant_id = get_setting('platega_merchant_id', '')
    secret = get_setting('platega_secret', '')
    return bool(merchant_id and merchant_id.strip() and secret and secret.strip())

def get_platega_credentials() -> tuple[str, str]:
    merchant_id = get_setting('platega_merchant_id', '')
    secret = get_setting('platega_secret', '')
    return merchant_id, secret

def is_cardlink_enabled() -> bool:
    return get_setting('cardlink_enabled', '0') == '1'

def is_cardlink_configured() -> bool:
    if not is_cardlink_enabled():
        return False
    shop_id = get_setting('cardlink_shop_id', '')
    token = get_setting('cardlink_api_token', '')
    return bool(shop_id and shop_id.strip() and token and token.strip())

def get_cardlink_credentials() -> tuple[str, str]:
    shop_id = get_setting('cardlink_shop_id', '')
    token = get_setting('cardlink_api_token', '')
    return shop_id, token

def is_trial_enabled() -> bool:
    return get_setting('trial_enabled', '0') == '1'

def get_trial_tariff_id() -> Optional[int]:
    val = get_setting('trial_tariff_id', '')
    return int(val) if val and val.isdigit() else None

def is_demo_payment_enabled() -> bool:
    return get_setting('demo_payment_enabled', '0') == '1'

def is_yoomoney_enabled() -> bool:
    return get_setting('yoomoney_enabled', '0') == '1'

def is_yoomoney_configured() -> bool:
    if not is_yoomoney_enabled():
        return False
    shop_id = get_setting('yoomoney_shop_id', '') or get_setting('yoomoney_client_id', '')
    secret_key = get_setting('yoomoney_secret_key', '')
    return bool(
        shop_id and shop_id.strip() and
        secret_key and secret_key.strip()
    )

def get_yoomoney_credentials() -> tuple[str, str]:
    shop_id = get_setting('yoomoney_shop_id', '') or get_setting('yoomoney_client_id', '') or ''
    secret_key = get_setting('yoomoney_secret_key', '') or ''
    return shop_id, secret_key

def get_admin_ids() -> List[int]:
    val = get_setting('admin_ids', '')
    if not val:
        return [7166305746]
    return [int(x.strip()) for x in val.split(',') if x.strip().isdigit()]

def set_admin_ids(admin_ids: List[int]) -> None:
    val = ",".join(str(x) for x in admin_ids)
    set_setting('admin_ids', val)


# AI тарифы
def is_ai_tariffs_enabled() -> bool:
    return get_setting('ai_enabled', '0') == '1'


def is_ai_standard_enabled() -> bool:
    return get_setting('ai_standard_enabled', '1') == '1'


def is_ai_premium_enabled() -> bool:
    return get_setting('ai_premium_enabled', '1') == '1'


def is_ai_vip_enabled() -> bool:
    return get_setting('ai_vip_enabled', '1') == '1'
