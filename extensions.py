from flask import Flask, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO

from config import RATELIMIT_STORAGE_URI, SECRET_KEY

app = Flask(__name__)
app.secret_key = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*")


def rate_limit_key():
    if "user_id" in session:
        return f'user:{session["user_id"]}'
    return get_remote_address()


limiter = Limiter(
    key_func=rate_limit_key,
    app=app,
    default_limits=["300 per minute"],
    storage_uri=RATELIMIT_STORAGE_URI,
)
