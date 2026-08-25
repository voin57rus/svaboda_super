from database.db_settings import get_admin_ids

def is_admin(user_id: int) -> bool:
    """Проверяет, является ли пользователь администратором (из БД)."""
    return user_id in get_admin_ids()
