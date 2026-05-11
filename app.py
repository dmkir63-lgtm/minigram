from config import APP_HOST, APP_PORT, DB_ENCRYPTION_ENABLED, DB_PATH, FLASK_DEBUG, SMTP_PASS, SMTP_USER
from core import init_db
from extensions import app, socketio

# Import modules for route/socket registration.
from routes import auth, channels, errors, friends, messages, pages, profile, search  # noqa: F401
from sockets import chat_socket  # noqa: F401

init_db()

if __name__ == "__main__":
    print("MiniGram: http://127.0.0.1:5000")
    print(f"База данных: {DB_PATH}")
    if DB_ENCRYPTION_ENABLED:
        print("Серверное шифрование базы включено: SQLCipher.")
    else:
        print("Серверное шифрование базы выключено: задайте DB_ENCRYPTION_KEY для SQLCipher.")
    if not SMTP_USER or not SMTP_PASS:
        print("SMTP не задан: коды подтверждения будут печататься в консоль.")
    socketio.run(app, host=APP_HOST, port=APP_PORT, debug=FLASK_DEBUG, allow_unsafe_werkzeug=True)
