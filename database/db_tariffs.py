import sqlite3
import logging
import secrets
import string
import datetime
from typing import Optional, List, Dict, Any, Tuple
from .connection import get_db

logger = logging.getLogger(__name__)

__all__ = [
    'get_all_tariffs',
    'get_tariff_by_id',
    'add_tariff',
    'update_tariff',
    'update_tariff_field',
    'toggle_tariff_active',
    'get_tariffs_count',
    'get_admin_tariff',
    'delete_tariffs_by_protocol',
]

def get_all_tariffs(include_hidden: bool = False, protocol: str = None) -> List[Dict[str, Any]]:
    """
    Получает список всех тарифов.
    
    Args:
        include_hidden: Включать скрытые тарифы (is_active = 0)
        protocol: Фильтр по протоколу ('vless', 'wireguard', 'amnezia', 'xray')
        
    Returns:
        Список словарей с данными тарифов
    """
    with get_db() as conn:
        query = """
            SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                   display_order, is_active, traffic_limit_gb, group_id, max_ips, protocol
            FROM tariffs
            WHERE 1=1
        """
        params = []
        if not include_hidden:
            query += " AND is_active = 1"
        if protocol:
            query += " AND protocol = ?"
            params.append(protocol)
        query += " ORDER BY display_order, id"
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]

def get_tariff_by_id(tariff_id: int) -> Optional[Dict[str, Any]]:
    """
    Получает тариф по ID.
    
    Args:
        tariff_id: ID тарифа
        
    Returns:
        Словарь с данными тарифа или None
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                   display_order, is_active, traffic_limit_gb, group_id, max_ips, protocol
            FROM tariffs
            WHERE id = ?
        """, (tariff_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def add_tariff(
    name: str,
    duration_days: int,
    price_cents: int,
    price_stars: int,
    price_rub: int = 0,
    display_order: int = 0,
    traffic_limit_gb: int = 0,
    group_id: int = 1,
    max_ips: int = 1,
    protocol: str = 'vless'
) -> int:
    """
    Добавляет новый тариф.
    
    Args:
        name: Название тарифа
        duration_days: Длительность в днях
        price_cents: Цена в центах (USDT * 100)
        price_stars: Цена в Telegram Stars
        price_rub: Цена в рублях
        display_order: Порядок отображения
        traffic_limit_gb: Лимит трафика в ГБ (0 = безлимит)
        group_id: ID группы тарифов (по умолчанию 1 — «Основная»)
        max_ips: Лимит устройств (IP-адресов) (по умолчанию 1)
        protocol: Протокол VPN ('vless', 'wireguard', 'amnezia', 'xray')
        
    Returns:
        ID созданного тарифа
    """
    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO tariffs (name, duration_days, price_cents, price_stars, price_rub, 
                                display_order, is_active, traffic_limit_gb, group_id, max_ips, protocol)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
        """, (name, duration_days, price_cents, price_stars, price_rub, display_order, traffic_limit_gb, group_id, max_ips, protocol))
        tariff_id = cursor.lastrowid
        logger.info(f"Добавлен тариф: {name} (ID: {tariff_id}, протокол: {protocol}, трафик: {traffic_limit_gb} ГБ)")
        return tariff_id

def update_tariff(tariff_id: int, **fields) -> bool:
    """
    Обновляет поля тарифа.
    
    Args:
        tariff_id: ID тарифа
        **fields: Поля для обновления
        
    Returns:
        True если обновление успешно
    """
    allowed_fields = {'name', 'duration_days', 'price_cents', 'price_stars', 'price_rub',
                      'display_order', 'is_active', 'group_id', 'traffic_limit_gb', 'max_ips', 'protocol'}
    fields = {k: v for k, v in fields.items() if k in allowed_fields}
    
    if not fields:
        return False
    
    set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
    values = list(fields.values()) + [tariff_id]
    
    with get_db() as conn:
        cursor = conn.execute(f"""
            UPDATE tariffs
            SET {set_clause}
            WHERE id = ?
        """, values)
        success = cursor.rowcount > 0
        if success:
            logger.info(f"Обновлён тариф ID {tariff_id}: {list(fields.keys())}")
        return success

def update_tariff_field(tariff_id: int, field: str, value: Any) -> bool:
    """
    Обновляет одно поле тарифа.
    
    Args:
        tariff_id: ID тарифа
        field: Название поля
        value: Новое значение
        
    Returns:
        True если обновление успешно
    """
    return update_tariff(tariff_id, **{field: value})

def toggle_tariff_active(tariff_id: int) -> Optional[bool]:
    """
    Переключает активность тарифа (скрыть/показать).
    
    Args:
        tariff_id: ID тарифа
        
    Returns:
        Новый статус (True = активен) или None если тариф не найден
    """
    tariff = get_tariff_by_id(tariff_id)
    if not tariff:
        return None
    
    new_status = 0 if tariff['is_active'] else 1
    
    with get_db() as conn:
        conn.execute("""
            UPDATE tariffs
            SET is_active = ?
            WHERE id = ?
        """, (new_status, tariff_id))
        status_text = "активирован" if new_status else "скрыт"
        logger.info(f"Тариф ID {tariff_id}: {status_text}")
        return bool(new_status)

def get_tariffs_count() -> int:
    """
    Возвращает количество активных тарифов.
    
    Returns:
        Количество активных тарифов
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) as cnt FROM tariffs WHERE is_active = 1")
        row = cursor.fetchone()
        return row['cnt'] if row else 0

def get_admin_tariff() -> Optional[Dict[str, Any]]:
    """
    Получает скрытый Admin Tariff для админского добавления ключей.
    
    Если тариф не существует, создаёт его автоматически.
    
    Returns:
        Словарь с данными тарифа
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT id, name, duration_days, price_cents, price_stars, price_rub, 
                   display_order, is_active, max_ips
            FROM tariffs
            WHERE name = 'Admin Tariff'
            LIMIT 1
        """)
        row = cursor.fetchone()
        
        if row:
            return dict(row)
        
        # Если тариф не найден, создаём его
        cursor = conn.execute("""
            INSERT INTO tariffs (name, duration_days, price_cents, price_stars, price_rub, display_order, is_active, max_ips)
            VALUES ('Admin Tariff', 30, 0, 0, 0, 999, 0, 1)
        """)
        logger.info("Создан Admin Tariff")
        
        return {
            'id': cursor.lastrowid,
            'name': 'Admin Tariff',
            'duration_days': 30,
            'price_cents': 0,
            'price_stars': 0,
            'price_rub': 0,
            'display_order': 999,
            'is_active': 0,
            'max_ips': 1
        }


def delete_tariffs_by_protocol(protocol: str) -> int:
    """
    Удаляет тарифы для протокола, если на них нет ссылок.
    Иначе скрывает (is_active = 0).
    
    Args:
        protocol: Протокол ('vless', 'wireguard', 'amnezia', 'xray')
        
    Returns:
        Количество удалённых/скрытых тарифов
    """
    with get_db() as conn:
        # Находим тарифы для протокола
        cursor = conn.execute("SELECT id FROM tariffs WHERE protocol = ?", (protocol,))
        tariff_ids = [row[0] for row in cursor.fetchall()]
        
        deleted = 0
        hidden = 0
        for tid in tariff_ids:
            # Проверяем есть ли ссылки на этот тариф
            ref_cursor = conn.execute("SELECT COUNT(*) FROM vpn_keys WHERE tariff_id = ?", (tid,))
            ref_count = ref_cursor.fetchone()[0]
            
            if ref_count == 0:
                # Нет ссылок — удаляем
                conn.execute("DELETE FROM tariffs WHERE id = ?", (tid,))
                deleted += 1
            else:
                # Есть ссылки — скрываем
                conn.execute("UPDATE tariffs SET is_active = 0 WHERE id = ?", (tid,))
                hidden += 1
        
        logger.info(f"Протокол {protocol}: удалено {deleted}, скрыто {hidden}")
        return deleted + hidden


