import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


# ==================================================
# GitHub обновления бота
# ==================================================
#
# Здесь указывается ссылка на GitHub-репозиторий,
# откуда бот получает обновления.
#
# Если ссылка указана:
# ✅ бот сможет проверять новые версии
# ✅ показывать список коммитов
# ✅ выполнять обновление файлов
#
# Если оставить пустым:
# GITHUB_REPO_URL = ""
#
# 🔒 обновления через GitHub будут отключены
# Пользователь увидит сообщение:
# "❌ GitHub не настроен"
#
# Пример:
# GITHUB_REPO_URL = "https://github.com/user/repo.git"
#
# ==================================================

GITHUB_REPO_URL = "https://github.com/voin57rus/svaboda_super.git"
#GITHUB_REPO_URL = ""

# ==================================================
# Обновление бота с сервера (локальный скрипт)
# ==================================================
#
# Путь к bash-скрипту, который выполняется при нажатии
# кнопки "🔄 Обновить с сервера" в админке.
#
# Если путь указан — бот выполнит "bash /путь/к/скрипту"
# и покажет результат в чат.
#
# Если оставить пустым — используется значение по умолчанию
# (см. обработчик admin_server_update).
#
# Пример:
# UPDATE_SCRIPT_PATH = "/root/svaboda_super/updatebot.sh"
#
# ==================================================

UPDATE_SCRIPT_PATH = "/root/svaboda_super/updatebot.sh"


RETRY_CONFIG = {
    "max_attempts": 3,
    "delays": [1, 3, 9],
}
