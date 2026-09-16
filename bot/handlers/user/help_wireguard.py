"""
Помощник по настройке WireGuard / AmneziaWG.
Показывает инструкции по подключению для разных платформ.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InputFile
from aiogram.fsm.context import FSMContext

from bot.utils.text import safe_edit_or_send

logger = logging.getLogger(__name__)

router = Router()

# ============================================================================
# Тексты инструкций
# ============================================================================

HELP_HEADER = """
🔐 <b>Настройка VPN — пошаговая инструкция</b>

Выберите устройство для подключения:
"""

HELP_ANDROID = """
📱 <b>Android — AmneziaWG</b>

1️⃣ Скачайте приложение <b>AmneziaWG</b> из Google Play
   👉 <a href="https://play.google.com/store/apps/details?id=org.amnezia.awg">Скачать</a>

2️⃣ Откройте приложение → <b>+</b> → <b>Импорт из файла</b>

3️⃣ Выберите файл конфигурации (полученный от бота)

4️⃣ Нажмите <b>Подключить</b> ▶️

✅ Готово! Интернет защищён.
"""

HELP_IPHONE = """
🍎 <b>iPhone — AmneziaWG / WireGuard</b>

<b>Вариант 1: AmneziaWG (рекомендуется)</b>
1️⃣ Скачайте <b>AmneziaWG</b> из App Store
   👉 <a href="https://apps.apple.com/app/amneziawg/id1600597050">Скачать</a>

2️⃣ Откройте → <b>+</b> → <b>Импорт из файла</b>

3️⃣ Выберите файл конфигурации

4️⃣ Подключитесь ▶️

<b>Вариант 2: WireGuard (Keenetic)</b>
1️⃣ Скачайте <b>WireGuard</b> из App Store

2️⃣ Импортируйте конфиг из файла
"""

HELP_WINDOWS = """
💻 <b>Windows — AmneziaWG</b>

1️⃣ Скачайте <b>AmneziaVPN</b> для Windows
   👉 <a href="https://amnezia.org/ru/downloads">Скачать</a>

2️⃣ Установите и запустите программу

3️⃣ Нажмите <b>Импорт конфигурации</b>

4️⃣ Выберите .conf файл

5️⃣ Подключитесь ▶️
"""

HELP_KEENETIC = """
🏠 <b>Keenetic роутер — WireGuard</b>

1️⃣ Откройте веб-интерфейс: <b>http://my.keenetic.net</b>

2️⃣ Перейдите: <b>Интернет → Другие подключения → WireGuard</b>

3️⃣ Нажмите <b>Добавить подключение</b>

4️⃣ Загрузите файл конфигурации (.conf)

5️⃣ Включите подключение ✅

6️⃣ Для маршрутизации: <b>Домашняя сеть → Приоритеты</b>
   выберите WireGuard как основной канал

💡 <i>Примечание: Keenetic поддерживает только обычный WireGuard (не AmneziaWG)</i>
"""

HELP_MACOS = """
🖥 <b>macOS — AmneziaWG</b>

1️⃣ Скачайте <b>AmneziaVPN</b> для Mac
   👉 <a href="https://amnezia.org/ru/downloads">Скачать</a>

2️⃣ Установите и запустите

3️⃣ Импортируйте .conf файл

4️⃣ Подключитесь ▶️
"""

HELP_LINUX = """
🐧 <b>Linux — WireGuard</b>

<b>Установка:</b>
<code>sudo apt install wireguard</b>  # Debian/Ubuntu
<code>sudo dnf install wireguard-tools</b>  # Fedora

<b>Подключение:</b>
<code>sudo cp config.conf /etc/wireguard/wg0.conf</code>
<code>sudo systemctl start wg-quick@wg0</code>
<code>sudo systemctl enable wg-quick@wg0</code>

<b>Проверка:</b>
<code>sudo wg show</code>
"""


def _get_help_text(device: str) -> str:
    """Возвращает текст инструкции для устройства."""
    texts = {
        "android": HELP_ANDROID,
        "iphone": HELP_IPHONE,
        "windows": HELP_WINDOWS,
        "macos": HELP_MACOS,
        "linux": HELP_LINUX,
        "keenetic": HELP_KEENETIC,
    }
    return texts.get(device, HELP_HEADER)


# ============================================================================
# Обработчики
# ============================================================================

@router.callback_query(F.data == "help_wg")
async def help_wg_main(callback: CallbackQuery, state: FSMContext):
    """Показывает выбор устройства для инструкции."""
    from bot.keyboards.user import help_wg_kb

    await safe_edit_or_send(
        callback.message,
        HELP_HEADER,
        reply_markup=help_wg_kb()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("help_wg:"))
async def help_wg_device(callback: CallbackQuery, state: FSMContext):
    """Показывает инструкцию для выбранного устройства."""
    from bot.keyboards.user import help_wg_device_kb

    device = callback.data.split(":")[1]
    text = _get_help_text(device)

    await safe_edit_or_send(
        callback.message,
        text,
        reply_markup=help_wg_device_kb(device)
    )
    await callback.answer()


@router.callback_query(F.data == "help_wg_back")
async def help_wg_back(callback: CallbackQuery, state: FSMContext):
    """Возврат к выбору устройства."""
    from bot.keyboards.user import help_wg_kb

    await safe_edit_or_send(
        callback.message,
        HELP_HEADER,
        reply_markup=help_wg_kb()
    )
    await callback.answer()
