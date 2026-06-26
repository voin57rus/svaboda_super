"""
Точка входа VPN Telegram бота.

Инициализирует бота, диспетчер, применяет миграции и запускает polling.
"""
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import os
import signal
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.migrations import run_migrations

from bot.services.vpn_api import close_all_clients
from bot.services.scheduler import run_daily_tasks, run_update_check_scheduler, run_traffic_sync_scheduler

# Импорт роутеров
from bot.handlers.user import router as user_router
from bot.handlers.admin import admin_router


# Создаём папку для логов если её нет (важно сделать до basicConfig)
os.makedirs("logs", exist_ok=True)


# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] - %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(
            "logs/bot.log", 
            maxBytes=1024 * 1024,  # 1 мегабайт
            backupCount=3, 
            encoding="utf-8"
        )
    ]
)

# Уменьшаем шум от aiohttp
logging.getLogger("aiohttp").setLevel(logging.WARNING)
logging.getLogger("DEBUG").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


from aiogram import BaseMiddleware as _BM

class _DebugMW(_BM):
    async def __call__(self, handler, event, data):
        from aiogram.types import CallbackQuery as _CQ
        if isinstance(event, _CQ):
            logging.getLogger("DEBUG").info(f"CB: {event.data} u={event.from_user.id}")
        try:
            return await handler(event, data)
        except Exception as e:
            if isinstance(event, _CQ):
                logging.getLogger("DEBUG").error(f"CB_ERR: {event.data} u={event.from_user.id} {type(e).__name__}: {e}", exc_info=True)
            raise





async def on_startup(bot: Bot):
    """Действия при запуске бота."""
    logger.info("🚀 Бот запускается...")
    
    # Применяем миграции БД
    run_migrations()
    
    # Гарантируем существование тарифа с id=0 для админ-ключей
    from database.db_keys import _ensure_admin_tariff
    from database.connection import get_db
    with get_db() as conn:
        _ensure_admin_tariff(conn)
    logger.info("✅ Admin tariff (id=0) ensured")
    
    # Информация о боте
    bot_info = await bot.get_me()
    bot.my_username = bot_info.username
    logger.info(f"✅ Бот запущен: @{bot_info.username}")
    
    # Если обновления заблокированы — сразу уведомляем админов
    from bot.utils.update_block import is_update_blocked, get_blocked_message
    if is_update_blocked():
        from config import ADMIN_IDS
        from aiogram.types import InlineKeyboardButton
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        
        msg = get_blocked_message()
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="✅ OK", callback_data="dismiss_msg"))
        kb = builder.as_markup()
        
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    chat_id=admin_id,
                    text=msg,
                    reply_markup=kb,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Не удалось отправить уведомление о блокировке админу {admin_id}: {e}")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота."""
    logger.info("🛑 Бот останавливается...")
    
    # Закрываем все VPN API сессии
    await close_all_clients()
    
    logger.info("✅ Бот остановлен")


async def main():
    """Главная функция запуска бота."""
    # Импортируем кастомную сессию с fallback для ошибок Markdown
    from bot.middlewares.parse_mode_fallback import SafeParseSession
    
    # Создаём бота с кастомной сессией и диспетчер
    session = SafeParseSession()
    bot = Bot(token=BOT_TOKEN, session=session)
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)
    
    # Регистрируем роутеры
    # Порядок важен: сначала более специфичные, потом общие
    dp.include_router(admin_router)           # Админ-панель (общая)
    dp.include_router(user_router)            # Пользователь (имеет строгий внутренний порядок)

    # Debug middleware
    dp.callback_query.middleware(_DebugMW())

    # Log all incoming messages via middleware (non-blocking)
    import logging as _logging
    _msg_logger = _logging.getLogger("bot.messages")

    class _LogMessagesMiddleware(_BM):
        async def __call__(self, handler, event, data):
            from aiogram.types import Message as _Msg
            if isinstance(event, _Msg):
                _msg_logger.info(f"MSG: user={event.from_user.id} text={event.text!r}")
            return await handler(event, data)

    dp.message.middleware(_LogMessagesMiddleware())
    
    # Глобальный обработчик ошибок сети
    from aiogram.exceptions import TelegramNetworkError
    from aiogram.types import ErrorEvent
    
    @dp.errors()
    async def global_error_handler(event: ErrorEvent):
        """Перехватывает сетевые ошибки Telegram API и пишет короткий warning."""
        exception = event.exception
        if isinstance(exception, TelegramNetworkError):
            logger.warning(f"⚠️ Нет связи с Telegram API: {exception}")
            return True  # Ошибка обработана, не пробрасываем дальше
        # Остальные ошибки логируем как обычно
        logger.error(f"Необработанная ошибка: {exception}", exc_info=True)
        return True
    
    # Регистрируем startup/shutdown
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    
    # Удаляем старые обновления и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    

    
    # Запускаем планировщик ежедневных задач (статистика + бэкапы)
    daily_tasks = asyncio.create_task(run_daily_tasks(bot))
    # Запускаем планировщик проверки обновлений
    update_tasks = asyncio.create_task(run_update_check_scheduler(bot))
    # Запускаем планировщик синхронизации трафика (каждые 5 мин)
    traffic_tasks = asyncio.create_task(run_traffic_sync_scheduler(bot))
    
    try:
        await dp.start_polling(bot)
    finally:
        daily_tasks.cancel()
        update_tasks.cancel()
        traffic_tasks.cancel()
        await bot.session.close()


if __name__ == "__main__":
    # Запускаем бота
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Получен сигнал остановки")
