from config import (
    APP_HOST,
    APP_PORT,
    DB_ENCRYPTION_ENABLED,
    DB_PATH,
    FLASK_DEBUG,
    MAILJET_API_KEY,
    MAILJET_SECRET_KEY,
    RESEND_API_KEY,
    SMTP_PASS,
    SMTP_USER,
    TELEGRAM_BOT_TOKEN,
)
from core import init_db
from extensions import app, socketio

# Import modules for route/socket registration.
from routes import auth, channels, errors, friends, messages, pages, profile, search, telegram  # noqa: F401
from sockets import chat_socket  # noqa: F401

init_db()

if __name__ == "__main__":
    print("MiniGram: http://127.0.0.1:5000")
    print(f"База данных: {DB_PATH}")
    if DB_ENCRYPTION_ENABLED:
        print("Серверное шифрование базы включено: SQLCipher.")
    else:
        print("Серверное шифрование базы выключено: задайте DB_ENCRYPTION_KEY для SQLCipher.")
    if MAILJET_API_KEY and MAILJET_SECRET_KEY:
        print("Email: используется Mailjet API.")
    elif RESEND_API_KEY:
        print("Email: используется Resend API.")
    elif SMTP_USER and SMTP_PASS:
        print("Email: используется SMTP.")
    else:
        print("Email API/SMTP не заданы: коды подтверждения будут печататься в консоль.")
    if TELEGRAM_BOT_TOKEN:
        print("Telegram: Bot API включён.")
    else:
        print("Telegram: TELEGRAM_BOT_TOKEN не задан.")
    socketio.run(app, host=APP_HOST, port=APP_PORT, debug=FLASK_DEBUG, allow_unsafe_werkzeug=True)
