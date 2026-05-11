import os

from dotenv import load_dotenv

load_dotenv()

DB_ENCRYPTION_KEY = os.environ.get("DB_ENCRYPTION_KEY", "").strip()
DB_ENCRYPTION_ENABLED = bool(DB_ENCRYPTION_KEY)

if DB_ENCRYPTION_ENABLED:
    try:
        import sqlcipher3 as sqlite3
    except ImportError as exc:
        raise RuntimeError(
            "DB_ENCRYPTION_KEY задан, но пакет sqlcipher3-binary не установлен. "
            "Установите его командой: pip install -r requirements-encrypted.txt"
        ) from exc
else:
    import sqlite3

SECRET_KEY = os.environ.get("SECRET_KEY", "minigram_secret_key_2026")
DEFAULT_DB_PATH = "minigram_encrypted.db" if DB_ENCRYPTION_ENABLED else "minigram.db"
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "5000"))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
