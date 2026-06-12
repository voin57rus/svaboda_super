"""
config.py — загрузка переменных окружения из .env
"""
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

GITHUB_REPO_URL = os.getenv("GITHUB_REPO_URL", "")

RETRY_CONFIG = {
    "max_attempts": int(os.getenv("RETRY_MAX_ATTEMPTS", "3")),
    "delays": [int(x) for x in os.getenv("RETRY_DELAYS", "1,3,9").split(",")],
}
