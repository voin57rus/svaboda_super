import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()


@router.callback_query(F.data == 'buy_key')
async def buy_key_handler(callback: CallbackQuery):
    """Страница «Купить ключ» — теперь показывает выбор протокола VPN."""
    from bot.keyboards.user import protocol_select_kb

    await safe_edit_or_send(
        callback.message,
        "🔐 <b>Выберите протокол VPN</b>\n\n"
        "🔵 <b>VLESS + Reality</b> — самый современный, обходит блокировки\n"
        "🟢 <b>WireGuard</b> — быстрый и стабильный\n"
        "🟠 <b>AmneziaWG</b> — WireGuard с обфускацией (обходит DPI)\n"
        "🟣 <b>Xray (VLESS+WS+TLS)</b> — маскировка под HTTPS",
        reply_markup=protocol_select_kb()
    )
    await callback.answer()