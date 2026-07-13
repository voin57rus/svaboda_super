"""
Общие операции жизненного цикла VPN-ключей.
"""
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def renew_key_access(
    key_id: int,
    days: int,
    reset_traffic: bool = True,
) -> Dict[str, Any]:
    """
    Универсально продлевает или уменьшает срок ключа и синхронизирует панель.

    БД остаётся источником истины. Если панель недоступна или обновилась
    частично, изменение в БД не откатывается: повторная синхронизация сможет
    дожать состояние позже.
    """
    from database.requests import extend_vpn_key
    from bot.services.vpn_api import restore_traffic_limit_in_db, sync_key_to_panel_state

    result: Dict[str, Any] = {
        'db_updated': False,
        'traffic_restored': False,
        'panel_synced': False,
        'sync_stats': {},
    }

    if not key_id or not days:
        return result

    if not extend_vpn_key(key_id, days):
        logger.error(f"renew_key_access: не удалось обновить срок ключа {key_id}")
        return result

    result['db_updated'] = True
    result['traffic_restored'] = restore_traffic_limit_in_db(key_id)

    try:
        sync_stats = await sync_key_to_panel_state(key_id, reset_traffic=reset_traffic)
        result['sync_stats'] = sync_stats
        result['panel_synced'] = bool(sync_stats.get('ok')) and sync_stats.get('errors', 0) == 0
    except Exception as e:
        logger.warning(f"renew_key_access: панель не синхронизирована для ключа {key_id}: {e}")
        result['sync_stats'] = {'errors': 1, 'ok': 0}

    return result
