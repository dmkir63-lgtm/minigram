from datetime import datetime, timedelta
from email.mime.text import MIMEText
import hashlib
import os
import random
import re
import smtplib
import string
import time

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

from flask import Flask, jsonify, redirect, render_template, request, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_socketio import SocketIO, emit, join_room

from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "minigram_secret_key_2026")
socketio = SocketIO(app, cors_allowed_origins="*")


def rate_limit_key():
    if "user_id" in session:
        return f'user:{session["user_id"]}'
    return get_remote_address()


limiter = Limiter(
    key_func=rate_limit_key,
    app=app,
    default_limits=["300 per minute"],
    storage_uri=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
)


@app.errorhandler(429)
def handle_rate_limit(error):
    retry_after = getattr(error, "retry_after", None)
    message = "Слишком много запросов. Попробуйте позже."
    response = jsonify(
        {
            "ok": False,
            "error": message,
            "retry_after": retry_after,
        }
    )
    response.status_code = 429
    if retry_after is not None:
        response.headers["Retry-After"] = str(retry_after)
    return response


DEFAULT_DB_PATH = "minigram_encrypted.db" if DB_ENCRYPTION_ENABLED else "minigram.db"
DB_PATH = os.environ.get("DB_PATH", DEFAULT_DB_PATH)
online_users = {}
socket_rate_events = {}

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
TAG_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sql_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if DB_ENCRYPTION_ENABLED:
        conn.execute(f"PRAGMA key = {sql_quote(DB_ENCRYPTION_KEY)}")
        try:
            conn.execute("PRAGMA cipher_memory_security = ON")
        except sqlite3.DatabaseError:
            pass
        conn.execute("SELECT count(*) FROM sqlite_master")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def add_column_if_missing(conn, table_name, column_name, column_sql):
    if column_name not in table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                display_name TEXT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                pm_privacy TEXT NOT NULL DEFAULT 'everyone',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS email_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                code TEXT NOT NULL,
                username TEXT NOT NULL,
                display_name TEXT,
                password_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS friend_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_id INTEGER NOT NULL,
                to_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                UNIQUE(from_id, to_id)
            );

            CREATE TABLE IF NOT EXISTS user_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                blocker_id INTEGER NOT NULL,
                blocked_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(blocker_id, blocked_id)
            );

            CREATE TABLE IF NOT EXISTS hidden_private_chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                peer_id INTEGER NOT NULL,
                hidden_at TEXT NOT NULL,
                UNIQUE(user_id, peer_id)
            );

            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                username TEXT,
                description TEXT,
                owner_id INTEGER NOT NULL,
                invite_code TEXT UNIQUE NOT NULL,
                is_private INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS channel_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'subscriber',
                joined_at TEXT NOT NULL,
                UNIQUE(channel_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS channel_join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                responded_at TEXT,
                responded_by INTEGER,
                UNIQUE(channel_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_type TEXT NOT NULL,
                channel_id INTEGER,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER,
                username TEXT NOT NULL,
                text TEXT NOT NULL,
                delivery_status TEXT NOT NULL DEFAULT 'sent',
                delivered_at TEXT,
                read_at TEXT,
                created_at TEXT NOT NULL
            );
        """)

        add_column_if_missing(conn, "users", "display_name", "display_name TEXT")
        add_column_if_missing(
            conn, "users", "pm_privacy", "pm_privacy TEXT NOT NULL DEFAULT 'everyone'"
        )
        add_column_if_missing(conn, "email_codes", "display_name", "display_name TEXT")
        add_column_if_missing(conn, "channels", "username", "username TEXT")
        add_column_if_missing(
            conn, "channels", "is_private", "is_private INTEGER NOT NULL DEFAULT 0"
        )
        add_column_if_missing(
            conn, "channel_members", "role", "role TEXT NOT NULL DEFAULT 'subscriber'"
        )
        add_column_if_missing(
            conn,
            "messages",
            "delivery_status",
            "delivery_status TEXT NOT NULL DEFAULT 'sent'",
        )
        add_column_if_missing(conn, "messages", "delivered_at", "delivered_at TEXT")
        add_column_if_missing(conn, "messages", "read_at", "read_at TEXT")

        conn.execute(
            "UPDATE users SET display_name=username WHERE display_name IS NULL OR TRIM(display_name)='' "
        )
        conn.execute(
            "UPDATE users SET pm_privacy='everyone' WHERE pm_privacy IS NULL OR pm_privacy NOT IN ('everyone', 'friends')"
        )
        conn.execute(
            "UPDATE messages SET delivery_status='sent' WHERE delivery_status IS NULL OR delivery_status NOT IN ('sent', 'delivered', 'read')"
        )

        old_channels = conn.execute(
            "SELECT id FROM channels WHERE username IS NULL OR TRIM(username)='' ORDER BY id"
        ).fetchall()
        for row in old_channels:
            conn.execute(
                "UPDATE channels SET username=? WHERE id=?",
                (f'channel{row["id"]}', row["id"]),
            )

        conn.execute("""
            UPDATE channel_members
            SET role='owner'
            WHERE EXISTS (
                SELECT 1 FROM channels c
                WHERE c.id=channel_members.channel_id AND c.owner_id=channel_members.user_id
            )
        """)

        conn.executescript("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_channels_username_unique ON channels(username);
            CREATE INDEX IF NOT EXISTS idx_messages_private ON messages(chat_type, sender_id, receiver_id, id);
            CREATE INDEX IF NOT EXISTS idx_messages_private_receiver ON messages(chat_type, receiver_id, sender_id, id);
            CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages(chat_type, channel_id, id);
            CREATE INDEX IF NOT EXISTS idx_messages_delivery ON messages(chat_type, receiver_id, delivery_status);
            CREATE INDEX IF NOT EXISTS idx_friend_to ON friend_requests(to_id, status);
            CREATE INDEX IF NOT EXISTS idx_user_blocks_blocker ON user_blocks(blocker_id, blocked_id);
            CREATE INDEX IF NOT EXISTS idx_user_blocks_blocked ON user_blocks(blocked_id, blocker_id);
            CREATE INDEX IF NOT EXISTS idx_hidden_private_chats_user ON hidden_private_chats(user_id, peer_id);
            CREATE INDEX IF NOT EXISTS idx_channel_members_channel_role ON channel_members(channel_id, role);
            CREATE INDEX IF NOT EXISTS idx_channel_join_requests_channel_status ON channel_join_requests(channel_id, status);
            CREATE INDEX IF NOT EXISTS idx_channel_join_requests_user_status ON channel_join_requests(user_id, status);
        """)


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def clean_tag(value):
    return value.strip().lstrip("@")


def validate_tag(value, label):
    if not TAG_RE.fullmatch(value):
        return f"{label}: используйте 3–32 символа: латиница, цифры и _"
    return None


def gen_code():
    return "".join(random.choices(string.digits, k=6))


def gen_invite():
    return "".join(random.choices(string.ascii_letters + string.digits, k=12))


def get_user(user_id):
    with get_db() as conn:
        return conn.execute(
            """SELECT id, username, COALESCE(display_name, username) AS display_name,
                      email, pm_privacy, created_at
               FROM users WHERE id=?""",
            (user_id,),
        ).fetchone()


def require_login_json():
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    return None


def check_socket_rate(user_id, action, limit, window_seconds):
    now = time.time()
    key = (int(user_id), action)
    events = socket_rate_events.get(key, [])
    events = [stamp for stamp in events if now - stamp < window_seconds]
    if len(events) >= limit:
        socket_rate_events[key] = events
        return False
    events.append(now)
    socket_rate_events[key] = events
    return True


def emit_rate_limit_error():
    emit("app_error", {"error": "Слишком много действий. Попробуйте позже."})


def pm_room(a, b):
    x, y = sorted([int(a), int(b)])
    return f"pm_{x}_{y}"


def get_channel_role(conn, channel_id, user_id):
    row = conn.execute(
        """SELECT c.owner_id, cm.role
           FROM channels c
           LEFT JOIN channel_members cm ON cm.channel_id=c.id AND cm.user_id=?
           WHERE c.id=?""",
        (user_id, channel_id),
    ).fetchone()
    if not row:
        return None
    if row["owner_id"] == user_id:
        return "owner"
    return row["role"]


def are_friends(conn, user_a, user_b):
    return (
        conn.execute(
            """SELECT 1 FROM friend_requests
           WHERE ((from_id=? AND to_id=?) OR (from_id=? AND to_id=?))
             AND status='accepted' """,
            (user_a, user_b, user_b, user_a),
        ).fetchone()
        is not None
    )


def block_status(conn, user_id, other_id):
    row = conn.execute(
        """SELECT
              EXISTS(SELECT 1 FROM user_blocks WHERE blocker_id=? AND blocked_id=?) AS is_blocked_by_me,
              EXISTS(SELECT 1 FROM user_blocks WHERE blocker_id=? AND blocked_id=?) AS has_blocked_me""",
        (user_id, other_id, other_id, user_id),
    ).fetchone()
    return bool(row["is_blocked_by_me"]), bool(row["has_blocked_me"])


def private_history_exists(conn, user_id, other_id):
    return (
        conn.execute(
            """SELECT 1 FROM messages
           WHERE chat_type='private'
             AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))
           LIMIT 1""",
            (user_id, other_id, other_id, user_id),
        ).fetchone()
        is not None
    )


def group_ids_by_sender(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["sender_id"], []).append(row["id"])
    return grouped


def mark_messages_delivered_for_receiver(conn, receiver_id):
    rows = conn.execute(
        """SELECT id, sender_id FROM messages
           WHERE chat_type='private' AND receiver_id=? AND delivery_status='sent' """,
        (receiver_id,),
    ).fetchall()
    if rows:
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        stamp = now_str()
        conn.execute(
            f"""UPDATE messages
                SET delivery_status='delivered', delivered_at=COALESCE(delivered_at, ?)
                WHERE id IN ({placeholders})""",
            (stamp, *ids),
        )
    return group_ids_by_sender(rows)


def mark_private_messages_read(conn, reader_id, other_id):
    rows = conn.execute(
        """SELECT id, sender_id FROM messages
           WHERE chat_type='private'
             AND sender_id=? AND receiver_id=?
             AND delivery_status!='read' """,
        (other_id, reader_id),
    ).fetchall()
    if rows:
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        stamp = now_str()
        conn.execute(
            f"""UPDATE messages
                SET delivery_status='read',
                    delivered_at=COALESCE(delivered_at, ?),
                    read_at=COALESCE(read_at, ?)
                WHERE id IN ({placeholders})""",
            (stamp, stamp, *ids),
        )
    return group_ids_by_sender(rows)


def emit_private_status_updates(grouped, status):
    for sender_id, ids in grouped.items():
        socketio.emit(
            "private_messages_status",
            {"message_ids": ids, "status": status},
            to=f"user_{sender_id}",
        )


def private_chat_state(conn, user_id, other_id):
    target = conn.execute(
        """SELECT id, username, COALESCE(display_name, username) AS display_name, pm_privacy
           FROM users WHERE id=?""",
        (other_id,),
    ).fetchone()
    if not target:
        return None

    is_friend = are_friends(conn, user_id, other_id)
    is_blocked_by_me, has_blocked_me = block_status(conn, user_id, other_id)
    has_history = private_history_exists(conn, user_id, other_id)

    can_message = True
    reason = ""
    if is_blocked_by_me:
        can_message = False
        reason = "Вы заблокировали пользователя. Разблокируйте, чтобы написать."
    elif has_blocked_me:
        can_message = False
        reason = "Пользователь вас заблокировал. Писать нельзя."
    elif target["pm_privacy"] == "friends" and not is_friend:
        can_message = False
        reason = "Пользователь принимает сообщения только от друзей"

    return {
        "id": target["id"],
        "username": target["username"],
        "display_name": target["display_name"],
        "pm_privacy": target["pm_privacy"],
        "is_friend": is_friend,
        "is_blocked_by_me": is_blocked_by_me,
        "has_blocked_me": has_blocked_me,
        "is_blocked": is_blocked_by_me or has_blocked_me,
        "has_history": has_history,
        "can_message": can_message,
        "block_reason": reason,
    }


def can_send_private_message(conn, sender_id, receiver_id):
    state = private_chat_state(conn, sender_id, receiver_id)
    if not state:
        return False, "Пользователь не найден"
    return bool(state["can_message"]), state["block_reason"]


def channel_payload(conn, channel_id, user_id):
    row = conn.execute(
        """SELECT c.id, c.name, c.username, c.description, c.owner_id, c.invite_code,
                  c.is_private, c.created_at,
                  COALESCE(cm.role, 'subscriber') AS role,
                  (SELECT COUNT(*) FROM channel_members WHERE channel_id=c.id) AS subscriber_count
           FROM channels c
           JOIN channel_members cm ON cm.channel_id=c.id AND cm.user_id=?
           WHERE c.id=?""",
        (user_id, channel_id),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    item["is_private"] = bool(item["is_private"])
    if item["owner_id"] == user_id:
        item["role"] = "owner"
    return item


def join_or_request_channel(conn, channel, user_id):
    member = conn.execute(
        "SELECT role FROM channel_members WHERE channel_id=? AND user_id=?",
        (channel["id"], user_id),
    ).fetchone()
    if member:
        return {
            "ok": True,
            "pending": False,
            "already_member": True,
            "channel": channel_payload(conn, channel["id"], user_id),
        }

    if channel["is_private"]:
        existing = conn.execute(
            "SELECT * FROM channel_join_requests WHERE channel_id=? AND user_id=?",
            (channel["id"], user_id),
        ).fetchone()
        if existing and existing["status"] == "pending":
            return {
                "ok": True,
                "pending": True,
                "message": "Заявка уже отправлена. Дождитесь одобрения.",
            }
        if existing:
            conn.execute(
                """UPDATE channel_join_requests
                   SET status='pending', created_at=?, responded_at=NULL, responded_by=NULL
                   WHERE channel_id=? AND user_id=?""",
                (now_str(), channel["id"], user_id),
            )
        else:
            conn.execute(
                """INSERT INTO channel_join_requests (channel_id, user_id, status, created_at)
                   VALUES (?,?,?,?)""",
                (channel["id"], user_id, "pending", now_str()),
            )
        return {
            "ok": True,
            "pending": True,
            "message": "Заявка отправлена. Владелец или админ должен её одобрить.",
        }

    conn.execute(
        "INSERT INTO channel_members (channel_id, user_id, role, joined_at) VALUES (?,?,?,?)",
        (channel["id"], user_id, "subscriber", now_str()),
    )
    conn.execute(
        """UPDATE channel_join_requests
           SET status='accepted', responded_at=?, responded_by=?
           WHERE channel_id=? AND user_id=? AND status='pending' """,
        (now_str(), user_id, channel["id"], user_id),
    )
    return {
        "ok": True,
        "pending": False,
        "channel": channel_payload(conn, channel["id"], user_id),
    }


def send_email(to, subject, body):
    if not SMTP_USER or not SMTP_PASS:
        print("\n[MiniGram email fallback]")
        print(f"To: {to}")
        print(f"Subject: {subject}")
        print(body)
        print()
        return True

    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = to
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.sendmail(SMTP_USER, [to], msg.as_string())
        return True
    except Exception as exc:
        print(f"[EMAIL ERROR] {exc}")
        return False


@app.route("/")
def index():
    if "user_id" not in session:
        return render_template("landing.html")
    user = get_user(session["user_id"])
    if not user:
        session.clear()
        return redirect("/")
    session["username"] = user["username"]
    session["display_name"] = user["display_name"]
    return render_template("chat.html", user=user)


@app.route("/auth")
@app.route("/login", methods=["GET"])
def login_page():
    if "user_id" in session:
        return redirect("/")
    default_tab = request.args.get("tab", "login")
    if default_tab not in ("login", "register"):
        default_tab = "login"
    next_url = request.args.get("next", "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    return render_template("auth.html", default_tab=default_tab, next_url=next_url)


@app.route("/register", methods=["GET"])
def register_page():
    if "user_id" in session:
        return redirect("/")
    next_url = request.args.get("next", "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    return render_template("auth.html", default_tab="register", next_url=next_url)


@app.route("/register", methods=["POST"])
@limiter.limit("3 per hour;10 per day")
def register():
    data = request.get_json(silent=True) or {}
    username = clean_tag(data.get("username", ""))
    display_name = data.get("display_name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not username or not display_name or not email or not password:
        return jsonify({"error": "Заполните все поля"}), 400
    tag_error = validate_tag(username, "Тег пользователя")
    if tag_error:
        return jsonify({"error": tag_error}), 400
    if len(display_name) > 40:
        return jsonify({"error": "Ник максимум 40 символов"}), 400
    if "@" not in email or "." not in email:
        return jsonify({"error": "Неверный формат email"}), 400
    if len(password) < 6:
        return jsonify({"error": "Пароль минимум 6 символов"}), 400

    with get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)
        ).fetchone():
            return jsonify({"error": "Такой тег уже занят"}), 409
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return jsonify({"error": "Email уже зарегистрирован"}), 409

        code = gen_code()
        expires_at = (datetime.now() + timedelta(minutes=10)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn.execute("DELETE FROM email_codes WHERE email=?", (email,))
        conn.execute(
            """INSERT INTO email_codes (email, code, username, display_name, password_hash, expires_at)
               VALUES (?,?,?,?,?,?)""",
            (email, code, username, display_name, hash_password(password), expires_at),
        )

    ok = send_email(
        email,
        "MiniGram — код подтверждения",
        f"Привет, {display_name}!\n\nВаш код подтверждения: {code}\nКод действует 10 минут.",
    )
    if not ok:
        return jsonify({"error": "Не получилось отправить письмо"}), 500
    return jsonify({"ok": True})


@app.route("/verify", methods=["POST"])
@limiter.limit("5 per minute;20 per hour")
def verify():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM email_codes WHERE email=? AND code=?", (email, code)
        ).fetchone()
        if not row:
            return jsonify({"error": "Неверный код"}), 400
        if datetime.now() > datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S"):
            conn.execute("DELETE FROM email_codes WHERE email=?", (email,))
            return jsonify({"error": "Код истёк, зарегистрируйтесь снова"}), 400

        display_name = row["display_name"] or row["username"]
        try:
            cur = conn.execute(
                """INSERT INTO users (username, display_name, email, password_hash, pm_privacy, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    row["username"],
                    display_name,
                    email,
                    row["password_hash"],
                    "everyone",
                    now_str(),
                ),
            )
        except sqlite3.IntegrityError:
            return jsonify({"error": "Тег или email уже заняты"}), 409

        conn.execute("DELETE FROM email_codes WHERE email=?", (email,))
        session["user_id"] = cur.lastrowid
        session["username"] = row["username"]
        session["display_name"] = display_name

    return jsonify({"ok": True})


@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute;30 per hour")
def login():
    data = request.get_json(silent=True) or {}
    login_value = data.get("login", "").strip().lstrip("@")
    password = data.get("password", "").strip()

    with get_db() as conn:
        user = conn.execute(
            """SELECT *, COALESCE(display_name, username) AS display_name_fixed
               FROM users
               WHERE (email=? OR lower(username)=lower(?)) AND password_hash=?""",
            (login_value.lower(), login_value, hash_password(password)),
        ).fetchone()

    if not user:
        return jsonify({"error": "Неверный логин или пароль"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user["display_name_fixed"]
    return jsonify({"ok": True})


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/me/settings")
def me_settings():
    err = require_login_json()
    if err:
        return err

    user = get_user(session["user_id"])
    return jsonify(
        {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "pm_privacy": user["pm_privacy"],
        }
    )


@app.route("/me/settings", methods=["PATCH"])
@limiter.limit("20 per minute")
def update_me_settings():
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    display_name = data.get("display_name", "").strip()
    pm_privacy = data.get("pm_privacy")

    if not display_name:
        return jsonify({"error": "Введите ник"}), 400
    if len(display_name) > 40:
        return jsonify({"error": "Ник максимум 40 символов"}), 400
    if pm_privacy not in ("everyone", "friends"):
        return jsonify({"error": "Неизвестный режим личных сообщений"}), 400

    with get_db() as conn:
        conn.execute(
            "UPDATE users SET display_name=?, pm_privacy=? WHERE id=?",
            (display_name, pm_privacy, session["user_id"]),
        )

    session["display_name"] = display_name
    return jsonify({"ok": True, "display_name": display_name, "pm_privacy": pm_privacy})


@app.route("/search")
@limiter.limit("60 per minute")
def search():
    if "user_id" not in session:
        return jsonify({"users": [], "channels": []})

    q = request.args.get("q", "").strip().lstrip("@")
    if not q:
        return jsonify({"users": [], "channels": []})

    uid = session["user_id"]
    pattern = f"%{q}%"
    with get_db() as conn:
        users = conn.execute(
            """SELECT u.id, u.username, COALESCE(u.display_name, u.username) AS display_name,
                      u.pm_privacy,
                      CASE WHEN fr.status='accepted' THEN 1 ELSE 0 END AS is_friend,
                      CASE WHEN fr.status='pending' AND fr.from_id=? THEN 1 ELSE 0 END AS request_sent,
                      CASE WHEN fr.status='pending' AND fr.to_id=? THEN 1 ELSE 0 END AS request_in
               FROM users u
               LEFT JOIN friend_requests fr
                 ON ((fr.from_id=? AND fr.to_id=u.id) OR (fr.to_id=? AND fr.from_id=u.id))
               WHERE (u.username LIKE ? OR u.display_name LIKE ? OR u.email LIKE ?) AND u.id!=?
               ORDER BY u.display_name
               LIMIT 8""",
            (uid, uid, uid, uid, pattern, pattern, pattern, uid),
        ).fetchall()

        channels = conn.execute(
            """SELECT c.id, c.name, c.username, c.description, c.invite_code, c.owner_id, c.is_private,
                      CASE WHEN cm.user_id IS NULL THEN 0 ELSE 1 END AS is_member,
                      COALESCE(cm.role, 'subscriber') AS role,
                      CASE WHEN cjr.status='pending' THEN 1 ELSE 0 END AS request_pending,
                      (SELECT COUNT(*) FROM channel_members WHERE channel_id=c.id) AS subscriber_count
               FROM channels c
               LEFT JOIN channel_members cm ON cm.channel_id=c.id AND cm.user_id=?
               LEFT JOIN channel_join_requests cjr ON cjr.channel_id=c.id AND cjr.user_id=? AND cjr.status='pending'
               WHERE c.name LIKE ? OR c.username LIKE ? OR c.description LIKE ?
               ORDER BY c.id DESC
               LIMIT 8""",
            (uid, uid, pattern, pattern, pattern),
        ).fetchall()

    channel_result = []
    for row in channels:
        item = dict(row)
        item["is_private"] = bool(item.get("is_private"))
        item["request_pending"] = bool(item.get("request_pending"))
        if item["owner_id"] == uid:
            item["role"] = "owner"
        channel_result.append(item)

    user_result = []
    with get_db() as conn:
        for row in users:
            item = dict(row)
            state = private_chat_state(conn, uid, item["id"])
            if state:
                item.update(
                    {
                        "is_friend": state["is_friend"],
                        "is_blocked_by_me": state["is_blocked_by_me"],
                        "has_blocked_me": state["has_blocked_me"],
                        "is_blocked": state["is_blocked"],
                        "has_history": state["has_history"],
                        "can_message": state["can_message"],
                        "block_reason": state["block_reason"],
                    }
                )
            user_result.append(item)

    return jsonify(
        {
            "users": user_result,
            "channels": channel_result,
        }
    )


@app.route("/friends")
def friends():
    if "user_id" not in session:
        return jsonify([])

    uid = session["user_id"]
    with get_db() as conn:
        rows = conn.execute(
            """WITH peers AS (
                   SELECT CASE WHEN fr.from_id=? THEN fr.to_id ELSE fr.from_id END AS user_id
                   FROM friend_requests fr
                   WHERE (fr.from_id=? OR fr.to_id=?) AND fr.status='accepted'
                   UNION
                   SELECT CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END AS user_id
                   FROM messages m
                   WHERE m.chat_type='private'
                     AND (m.sender_id=? OR m.receiver_id=?)
                     AND CASE WHEN m.sender_id=? THEN m.receiver_id ELSE m.sender_id END IS NOT NULL
                   UNION
                   SELECT blocked_id AS user_id FROM user_blocks WHERE blocker_id=?
                   UNION
                   SELECT blocker_id AS user_id FROM user_blocks WHERE blocked_id=?
               )
               SELECT u.id, u.username, COALESCE(u.display_name, u.username) AS display_name,
                      u.pm_privacy,
                      lm.text AS last_message,
                      lm.created_at AS last_message_at,
                      lm.sender_id AS last_message_sender_id,
                      lm.delivery_status AS last_message_status
               FROM peers p
               JOIN users u ON u.id=p.user_id
               LEFT JOIN messages lm ON lm.id = (
                   SELECT m2.id FROM messages m2
                   WHERE m2.chat_type='private'
                     AND ((m2.sender_id=? AND m2.receiver_id=u.id) OR (m2.sender_id=u.id AND m2.receiver_id=?))
                   ORDER BY m2.id DESC LIMIT 1
               )
               WHERE NOT EXISTS (
                   SELECT 1 FROM hidden_private_chats h
                   WHERE h.user_id=? AND h.peer_id=u.id
               )
               ORDER BY COALESCE(lm.created_at, '') DESC, u.display_name""",
            (uid, uid, uid, uid, uid, uid, uid, uid, uid, uid, uid, uid),
        ).fetchall()

        online = set(online_users.values())
        result = []
        for row in rows:
            state = private_chat_state(conn, uid, row["id"])
            if not state:
                continue
            result.append(
                {
                    "id": row["id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "pm_privacy": row["pm_privacy"],
                    "is_friend": state["is_friend"],
                    "is_blocked_by_me": state["is_blocked_by_me"],
                    "has_blocked_me": state["has_blocked_me"],
                    "is_blocked": state["is_blocked"],
                    "has_history": state["has_history"],
                    "can_message": state["can_message"],
                    "block_reason": state["block_reason"],
                    "online": row["id"] in online,
                    "last_message": row["last_message"],
                    "last_message_at": row["last_message_at"],
                    "last_message_sender_id": row["last_message_sender_id"],
                    "last_message_status": row["last_message_status"],
                }
            )

    return jsonify(result)


@app.route("/private/status/<int:other_id>")
def private_status(other_id):
    err = require_login_json()
    if err:
        return err

    with get_db() as conn:
        state = private_chat_state(conn, session["user_id"], other_id)
        if not state:
            return jsonify({"error": "Пользователь не найден"}), 404
    return jsonify(state)


@app.route("/friends/<int:target_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
def remove_friend(target_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    if target_id == uid:
        return jsonify({"error": "Нельзя удалить себя"}), 400

    with get_db() as conn:
        target = conn.execute(
            "SELECT id FROM users WHERE id=?", (target_id,)
        ).fetchone()
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404
        cur = conn.execute(
            """DELETE FROM friend_requests
               WHERE status='accepted'
                 AND ((from_id=? AND to_id=?) OR (from_id=? AND to_id=?))""",
            (uid, target_id, target_id, uid),
        )

    socketio.emit(
        "relationship_changed",
        {"user_id": uid, "reason": "friend_removed"},
        to=f"user_{target_id}",
    )
    socketio.emit(
        "relationship_changed",
        {"user_id": target_id, "reason": "friend_removed"},
        to=f"user_{uid}",
    )
    return jsonify({"ok": True, "removed": cur.rowcount > 0})


@app.route("/blocks")
def blocked_users():
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        rows = conn.execute(
            """SELECT u.id, u.username, COALESCE(u.display_name, u.username) AS display_name, ub.created_at
               FROM user_blocks ub
               JOIN users u ON u.id=ub.blocked_id
               WHERE ub.blocker_id=?
               ORDER BY ub.created_at DESC, u.display_name""",
            (uid,),
        ).fetchall()

    return jsonify([dict(row) for row in rows])


@app.route("/blocks/<int:target_id>", methods=["POST"])
@limiter.limit("30 per minute")
def block_user(target_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    if target_id == uid:
        return jsonify({"error": "Нельзя заблокировать себя"}), 400

    with get_db() as conn:
        target = conn.execute(
            "SELECT id FROM users WHERE id=?", (target_id,)
        ).fetchone()
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404
        conn.execute(
            """INSERT OR IGNORE INTO user_blocks (blocker_id, blocked_id, created_at)
               VALUES (?,?,?)""",
            (uid, target_id, now_str()),
        )

    socketio.emit(
        "relationship_changed",
        {"user_id": uid, "reason": "blocked"},
        to=f"user_{target_id}",
    )
    socketio.emit(
        "relationship_changed",
        {"user_id": target_id, "reason": "blocked"},
        to=f"user_{uid}",
    )
    return jsonify({"ok": True})


@app.route("/blocks/<int:target_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
def unblock_user(target_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        conn.execute(
            "DELETE FROM user_blocks WHERE blocker_id=? AND blocked_id=?",
            (uid, target_id),
        )

    socketio.emit(
        "relationship_changed",
        {"user_id": uid, "reason": "unblocked"},
        to=f"user_{target_id}",
    )
    socketio.emit(
        "relationship_changed",
        {"user_id": target_id, "reason": "unblocked"},
        to=f"user_{uid}",
    )
    return jsonify({"ok": True})


@app.route("/friends/requests")
def friend_requests():
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        rows = conn.execute(
            """SELECT fr.id, u.id AS from_id, u.username, COALESCE(u.display_name, u.username) AS display_name
               FROM friend_requests fr
               JOIN users u ON u.id=fr.from_id
               WHERE fr.to_id=? AND fr.status='pending'
               ORDER BY fr.id DESC""",
            (uid,),
        ).fetchall()

    return jsonify([dict(row) for row in rows])


@app.route("/friends/send", methods=["POST"])
@limiter.limit("20 per hour")
def send_friend_request():
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    to_id = int(data.get("to_id", 0))
    uid = session["user_id"]

    if to_id == uid:
        return jsonify({"error": "Нельзя добавить себя"}), 400

    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id=?", (to_id,)).fetchone()
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404

        is_blocked_by_me, has_blocked_me = block_status(conn, uid, to_id)
        if is_blocked_by_me:
            return (
                jsonify(
                    {
                        "error": "Вы заблокировали пользователя. Сначала разблокируйте его."
                    }
                ),
                409,
            )
        if has_blocked_me:
            return jsonify({"error": "Пользователь вас заблокировал"}), 403

        existing = conn.execute(
            """SELECT * FROM friend_requests
               WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)""",
            (uid, to_id, to_id, uid),
        ).fetchone()

        if existing:
            if existing["status"] == "accepted":
                return jsonify({"error": "Вы уже друзья"}), 409
            return jsonify({"error": "Заявка уже есть"}), 409

        conn.execute(
            "INSERT INTO friend_requests (from_id, to_id, status, created_at) VALUES (?,?,?,?)",
            (uid, to_id, "pending", now_str()),
        )

    socketio.emit(
        "friend_request_in",
        {
            "from_id": uid,
            "username": session["username"],
            "display_name": session.get("display_name", session["username"]),
        },
        to=f"user_{to_id}",
    )
    return jsonify({"ok": True})


@app.route("/friends/respond", methods=["POST"])
@limiter.limit("60 per minute")
def respond_friend_request():
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    request_id = int(data.get("request_id", 0))
    action = data.get("action")
    uid = session["user_id"]

    with get_db() as conn:
        req = conn.execute(
            'SELECT * FROM friend_requests WHERE id=? AND to_id=? AND status="pending"',
            (request_id, uid),
        ).fetchone()
        if not req:
            return jsonify({"error": "Заявка не найдена"}), 404

        if action == "accept":
            conn.execute(
                'UPDATE friend_requests SET status="accepted" WHERE id=?', (request_id,)
            )
            socketio.emit(
                "friend_accepted",
                {
                    "id": uid,
                    "username": session["username"],
                    "display_name": session.get("display_name", session["username"]),
                },
                to=f'user_{req["from_id"]}',
            )
        else:
            conn.execute("DELETE FROM friend_requests WHERE id=?", (request_id,))

    return jsonify({"ok": True})


@app.route("/channels")
def channels():
    if "user_id" not in session:
        return jsonify([])

    uid = session["user_id"]
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.id, c.name, c.username, c.description, c.owner_id, c.invite_code, c.is_private, c.created_at,
                      COALESCE(cm.role, 'subscriber') AS role,
                      (SELECT COUNT(*) FROM channel_members WHERE channel_id=c.id) AS subscriber_count,
                      lm.text AS last_message,
                      lm.created_at AS last_message_at,
                      lm.sender_id AS last_message_sender_id,
                      COALESCE(lu.display_name, lm.username) AS last_message_author
               FROM channels c
               JOIN channel_members cm ON cm.channel_id=c.id
               LEFT JOIN messages lm ON lm.id = (
                   SELECT m2.id FROM messages m2
                   WHERE m2.chat_type='channel' AND m2.channel_id=c.id
                   ORDER BY m2.id DESC LIMIT 1
               )
               LEFT JOIN users lu ON lu.id=lm.sender_id
               WHERE cm.user_id=?
               ORDER BY COALESCE(lm.created_at, c.created_at) DESC, c.id DESC""",
            (uid,),
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["is_private"] = bool(item.get("is_private"))
        if item["owner_id"] == uid:
            item["role"] = "owner"
        result.append(item)
    return jsonify(result)


@app.route("/channels/create", methods=["POST"])
@limiter.limit("10 per hour")
def create_channel():
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    username = clean_tag(data.get("username", ""))
    description = data.get("description", "").strip()
    is_private = 1 if data.get("is_private") else 0

    if not name or not username:
        return jsonify({"error": "Введите название и тег канала"}), 400
    tag_error = validate_tag(username, "Тег канала")
    if tag_error:
        return jsonify({"error": tag_error}), 400
    if len(name) > 60:
        return jsonify({"error": "Название канала максимум 60 символов"}), 400

    uid = session["user_id"]
    invite_code = gen_invite()
    created_at = now_str()

    with get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM channels WHERE lower(username)=lower(?)", (username,)
        ).fetchone():
            return jsonify({"error": "Такой тег канала уже занят"}), 409
        cur = conn.execute(
            """INSERT INTO channels (name, username, description, owner_id, invite_code, is_private, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (name, username, description, uid, invite_code, is_private, created_at),
        )
        channel_id = cur.lastrowid
        conn.execute(
            "INSERT INTO channel_members (channel_id, user_id, role, joined_at) VALUES (?,?,?,?)",
            (channel_id, uid, "owner", created_at),
        )
        channel = conn.execute(
            """SELECT c.id, c.name, c.username, c.description, c.owner_id, c.invite_code, c.is_private, c.created_at,
                      1 AS subscriber_count, 'owner' AS role
               FROM channels c WHERE c.id=?""",
            (channel_id,),
        ).fetchone()

    result = dict(channel)
    result["is_private"] = bool(result.get("is_private"))
    return jsonify({"ok": True, "channel": result})


@app.route("/channels/join", methods=["POST"])
@limiter.limit("30 per minute")
def join_channel_by_invite():
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    invite_code = data.get("invite_code", "").strip().split("/")[-1]
    uid = session["user_id"]

    if not invite_code:
        return jsonify({"error": "Введите инвайт-код"}), 400

    with get_db() as conn:
        channel = conn.execute(
            "SELECT * FROM channels WHERE invite_code=?", (invite_code,)
        ).fetchone()
        if not channel:
            return jsonify({"error": "Канал по такой ссылке не найден"}), 404
        result = join_or_request_channel(conn, channel, uid)
        if result.get("pending"):
            manager_ids = [
                row["user_id"]
                for row in conn.execute(
                    "SELECT user_id FROM channel_members WHERE channel_id=? AND role IN ('owner', 'admin')",
                    (channel["id"],),
                ).fetchall()
            ]
        else:
            manager_ids = []

    if result.get("pending"):
        for manager_id in manager_ids:
            socketio.emit(
                "channel_join_request",
                {
                    "channel_id": channel["id"],
                    "channel_name": channel["name"],
                    "user_id": uid,
                    "display_name": session.get("display_name", session["username"]),
                    "username": session["username"],
                },
                to=f"user_{manager_id}",
            )
    return jsonify(result)


@app.route("/channels/<int:channel_id>/join", methods=["POST"])
@limiter.limit("30 per minute")
def join_channel_public(channel_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        channel = conn.execute(
            "SELECT * FROM channels WHERE id=?", (channel_id,)
        ).fetchone()
        if not channel:
            return jsonify({"error": "Канал не найден"}), 404
        result = join_or_request_channel(conn, channel, uid)
        if result.get("pending"):
            manager_ids = [
                row["user_id"]
                for row in conn.execute(
                    "SELECT user_id FROM channel_members WHERE channel_id=? AND role IN ('owner', 'admin')",
                    (channel_id,),
                ).fetchall()
            ]
        else:
            manager_ids = []

    if result.get("pending"):
        for manager_id in manager_ids:
            socketio.emit(
                "channel_join_request",
                {
                    "channel_id": channel_id,
                    "channel_name": channel["name"],
                    "user_id": uid,
                    "display_name": session.get("display_name", session["username"]),
                    "username": session["username"],
                },
                to=f"user_{manager_id}",
            )
    return jsonify(result)


@app.route("/channels/<int:channel_id>/join-requests")
def channel_join_requests(channel_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role not in ("owner", "admin"):
            return (
                jsonify({"error": "Заявки могут смотреть только владелец и админы"}),
                403,
            )

        rows = conn.execute(
            """SELECT cjr.id, cjr.user_id, cjr.created_at,
                      u.username, COALESCE(u.display_name, u.username) AS display_name
               FROM channel_join_requests cjr
               JOIN users u ON u.id=cjr.user_id
               WHERE cjr.channel_id=? AND cjr.status='pending'
               ORDER BY cjr.id DESC""",
            (channel_id,),
        ).fetchall()

    return jsonify([dict(row) for row in rows])


@app.route(
    "/channels/<int:channel_id>/join-requests/<int:request_id>", methods=["POST"]
)
@limiter.limit("60 per minute")
def respond_channel_join_request(channel_id, request_id):
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    action = data.get("action")
    uid = session["user_id"]

    if action not in ("accept", "decline"):
        return jsonify({"error": "Неизвестное действие"}), 400

    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role not in ("owner", "admin"):
            return (
                jsonify({"error": "Одобрять заявки могут только владелец и админы"}),
                403,
            )

        req = conn.execute(
            """SELECT cjr.*, c.name AS channel_name, c.username AS channel_username, c.invite_code,
                      c.description, c.owner_id, c.is_private, c.created_at AS channel_created_at
               FROM channel_join_requests cjr
               JOIN channels c ON c.id=cjr.channel_id
               WHERE cjr.id=? AND cjr.channel_id=? AND cjr.status='pending' """,
            (request_id, channel_id),
        ).fetchone()
        if not req:
            return jsonify({"error": "Заявка не найдена"}), 404

        if action == "accept":
            conn.execute(
                "INSERT OR IGNORE INTO channel_members (channel_id, user_id, role, joined_at) VALUES (?,?,?,?)",
                (channel_id, req["user_id"], "subscriber", now_str()),
            )
            conn.execute(
                """UPDATE channel_join_requests
                   SET status='accepted', responded_at=?, responded_by=?
                   WHERE id=?""",
                (now_str(), uid, request_id),
            )
            payload = channel_payload(conn, channel_id, req["user_id"])
        else:
            conn.execute(
                """UPDATE channel_join_requests
                   SET status='declined', responded_at=?, responded_by=?
                   WHERE id=?""",
                (now_str(), uid, request_id),
            )
            payload = None

    if action == "accept":
        socketio.emit(
            "channel_join_approved",
            {
                "channel": payload,
                "channel_name": req["channel_name"],
            },
            to=f'user_{req["user_id"]}',
        )
    else:
        socketio.emit(
            "channel_join_declined",
            {
                "channel_id": channel_id,
                "channel_name": req["channel_name"],
            },
            to=f'user_{req["user_id"]}',
        )

    return jsonify({"ok": True})


@app.route("/channels/<int:channel_id>/leave", methods=["POST"])
@limiter.limit("30 per minute")
def leave_channel(channel_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        channel = conn.execute(
            "SELECT * FROM channels WHERE id=?", (channel_id,)
        ).fetchone()
        if not channel:
            return jsonify({"error": "Канал не найден"}), 404
        if channel["owner_id"] == uid:
            return jsonify({"error": "Владелец не может выйти из своего канала"}), 400
        member = conn.execute(
            "SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",
            (channel_id, uid),
        ).fetchone()
        if not member:
            return jsonify({"error": "Вы не состоите в этом канале"}), 404
        conn.execute(
            "DELETE FROM channel_members WHERE channel_id=? AND user_id=?",
            (channel_id, uid),
        )

    return jsonify({"ok": True})


@app.route("/channels/<int:channel_id>/settings")
def channel_settings(channel_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role != "owner":
            return jsonify({"error": "Настройки канала доступны только владельцу"}), 403
        channel = channel_payload(conn, channel_id, uid)
        if not channel:
            return jsonify({"error": "Канал не найден"}), 404

    return jsonify({"channel": channel})


@app.route("/channels/<int:channel_id>/settings", methods=["PATCH"])
@limiter.limit("30 per minute")
def update_channel_settings(channel_id):
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    uid = session["user_id"]
    name = data.get("name")

    if name is not None:
        name = name.strip()
        if not name:
            return jsonify({"error": "Введите название канала"}), 400
        if len(name) > 60:
            return jsonify({"error": "Название канала максимум 60 символов"}), 400

    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role != "owner":
            return (
                jsonify({"error": "Менять настройки канала может только владелец"}),
                403,
            )

        if name is not None:
            conn.execute("UPDATE channels SET name=? WHERE id=?", (name, channel_id))
        if "is_private" in data:
            conn.execute(
                "UPDATE channels SET is_private=? WHERE id=?",
                (1 if data.get("is_private") else 0, channel_id),
            )
        channel = channel_payload(conn, channel_id, uid)
        if not channel:
            return jsonify({"error": "Канал не найден"}), 404

    return jsonify({"ok": True, "channel": channel})


@app.route("/channels/<int:channel_id>/admins")
def channel_admins(channel_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    q = request.args.get("q", "").strip()
    limit = min(max(int(request.args.get("limit", 30)), 1), 50)

    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role != "owner":
            return jsonify({"error": "Управлять админами может только владелец"}), 403

        admins = conn.execute(
            """SELECT u.id, u.username, COALESCE(u.display_name, u.username) AS display_name,
                      CASE WHEN c.owner_id=u.id THEN 'owner' ELSE cm.role END AS role
               FROM channel_members cm
               JOIN users u ON u.id=cm.user_id
               JOIN channels c ON c.id=cm.channel_id
               WHERE cm.channel_id=? AND (cm.role IN ('owner', 'admin') OR c.owner_id=u.id)
               ORDER BY CASE WHEN c.owner_id=u.id THEN 0 ELSE 1 END, LOWER(COALESCE(u.display_name, u.username))""",
            (channel_id,),
        ).fetchall()

        candidates = []
        candidates_more = False
        if len(q) >= 2:
            like = f"%{q}%"
            candidate_rows = conn.execute(
                """SELECT u.id, u.username, COALESCE(u.display_name, u.username) AS display_name, cm.role
                   FROM channel_members cm
                   JOIN users u ON u.id=cm.user_id
                   JOIN channels c ON c.id=cm.channel_id
                   WHERE cm.channel_id=?
                     AND cm.user_id!=c.owner_id
                     AND cm.role!='admin'
                     AND (u.username LIKE ? OR COALESCE(u.display_name, u.username) LIKE ?)
                   ORDER BY LOWER(COALESCE(u.display_name, u.username)), LOWER(u.username)
                   LIMIT ?""",
                (channel_id, like, like, limit + 1),
            ).fetchall()
            candidates_more = len(candidate_rows) > limit
            candidates = candidate_rows[:limit]

    return jsonify(
        {
            "admins": [dict(row) for row in admins],
            "candidates": [dict(row) for row in candidates],
            "candidates_more": candidates_more,
        }
    )


@app.route("/channels/<int:channel_id>/admins", methods=["POST"])
@limiter.limit("30 per minute")
def add_channel_admin(channel_id):
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    target_id = int(data.get("user_id", 0))
    uid = session["user_id"]

    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role != "owner":
            return jsonify({"error": "Добавлять админов может только владелец"}), 403
        channel = conn.execute(
            "SELECT * FROM channels WHERE id=?", (channel_id,)
        ).fetchone()
        if not channel:
            return jsonify({"error": "Канал не найден"}), 404
        if target_id == channel["owner_id"]:
            return jsonify({"error": "Владелец уже главный админ"}), 400
        member = conn.execute(
            "SELECT * FROM channel_members WHERE channel_id=? AND user_id=?",
            (channel_id, target_id),
        ).fetchone()
        if not member:
            return (
                jsonify({"error": "Сначала пользователь должен вступить в канал"}),
                404,
            )
        conn.execute(
            'UPDATE channel_members SET role="admin" WHERE channel_id=? AND user_id=?',
            (channel_id, target_id),
        )

    return jsonify({"ok": True})


@app.route("/channels/<int:channel_id>/admins/<int:target_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
def remove_channel_admin(channel_id, target_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role != "owner":
            return jsonify({"error": "Снимать админов может только владелец"}), 403
        channel = conn.execute(
            "SELECT * FROM channels WHERE id=?", (channel_id,)
        ).fetchone()
        if not channel:
            return jsonify({"error": "Канал не найден"}), 404
        if target_id == channel["owner_id"]:
            return jsonify({"error": "Нельзя снять владельца"}), 400
        conn.execute(
            'UPDATE channel_members SET role="subscriber" WHERE channel_id=? AND user_id=? AND role="admin"',
            (channel_id, target_id),
        )

    return jsonify({"ok": True})


@app.route("/channels/<int:channel_id>", methods=["DELETE"])
@limiter.limit("10 per hour")
def delete_channel(channel_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        channel = conn.execute(
            "SELECT * FROM channels WHERE id=?", (channel_id,)
        ).fetchone()
        if not channel:
            return jsonify({"error": "Канал не найден"}), 404
        if channel["owner_id"] != uid:
            return jsonify({"error": "Удалить канал может только владелец"}), 403

        member_ids = [
            row["user_id"]
            for row in conn.execute(
                "SELECT user_id FROM channel_members WHERE channel_id=?",
                (channel_id,),
            ).fetchall()
        ]

        conn.execute(
            "DELETE FROM messages WHERE chat_type='channel' AND channel_id=?",
            (channel_id,),
        )
        conn.execute(
            "DELETE FROM channel_join_requests WHERE channel_id=?", (channel_id,)
        )
        conn.execute("DELETE FROM channel_members WHERE channel_id=?", (channel_id,))
        conn.execute("DELETE FROM channels WHERE id=?", (channel_id,))

    for member_id in member_ids:
        socketio.emit(
            "channel_deleted",
            {"channel_id": channel_id, "name": channel["name"]},
            to=f"user_{member_id}",
        )

    return jsonify({"ok": True})


@app.route("/channels/<int:channel_id>/messages")
def channel_messages(channel_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    uid = session["user_id"]
    with get_db() as conn:
        member = conn.execute(
            "SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",
            (channel_id, uid),
        ).fetchone()
        if not member:
            return jsonify({"error": "Нет доступа к каналу"}), 403

        messages = conn.execute(
            """SELECT m.id, m.chat_type, m.channel_id, m.sender_id,
                      u.username, COALESCE(u.display_name, m.username) AS display_name,
                      m.text, m.created_at
               FROM messages m
               LEFT JOIN users u ON u.id=m.sender_id
               WHERE m.chat_type='channel' AND m.channel_id=?
               ORDER BY m.id DESC
               LIMIT 80""",
            (channel_id,),
        ).fetchall()

    return jsonify([dict(row) for row in reversed(messages)])


@app.route("/private/messages/<int:other_id>")
def private_messages(other_id):
    if "user_id" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    uid = session["user_id"]
    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id=?", (other_id,)).fetchone()
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404

        messages = conn.execute(
            """SELECT m.id, m.chat_type, m.sender_id, m.receiver_id,
                      u.username, COALESCE(u.display_name, m.username) AS display_name,
                      m.text, m.delivery_status, m.delivered_at, m.read_at, m.created_at
               FROM messages m
               LEFT JOIN users u ON u.id=m.sender_id
               WHERE m.chat_type='private'
                 AND ((m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?))
               ORDER BY m.id DESC
               LIMIT 80""",
            (uid, other_id, other_id, uid),
        ).fetchall()

    return jsonify([dict(row) for row in reversed(messages)])


@app.route("/private/chats/<int:other_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
def delete_private_chat(other_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    if other_id == uid:
        return jsonify({"error": "Нельзя удалить чат с самим собой"}), 400

    with get_db() as conn:
        target = conn.execute("SELECT id FROM users WHERE id=?", (other_id,)).fetchone()
        if not target:
            return jsonify({"error": "Пользователь не найден"}), 404

        conn.execute(
            """DELETE FROM messages
               WHERE chat_type='private'
                 AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))""",
            (uid, other_id, other_id, uid),
        )
        conn.execute(
            """INSERT INTO hidden_private_chats (user_id, peer_id, hidden_at)
               VALUES (?,?,?)
               ON CONFLICT(user_id, peer_id) DO UPDATE SET hidden_at=excluded.hidden_at""",
            (uid, other_id, now_str()),
        )

    socketio.emit("private_chat_deleted", {"peer_id": other_id}, to=f"user_{uid}")
    socketio.emit("private_chat_deleted", {"peer_id": uid}, to=f"user_{other_id}")
    return jsonify({"ok": True})


@socketio.on("connect")
def socket_connect():
    if "user_id" not in session:
        return False
    uid = session["user_id"]
    online_users[request.sid] = uid
    join_room(f"user_{uid}")
    with get_db() as conn:
        delivered = mark_messages_delivered_for_receiver(conn, uid)
    emit_private_status_updates(delivered, "delivered")
    emit("online_update", list(set(online_users.values())), broadcast=True)


@socketio.on("disconnect")
def socket_disconnect():
    online_users.pop(request.sid, None)
    emit("online_update", list(set(online_users.values())), broadcast=True)


@socketio.on("join_private")
def socket_join_private(data):
    if "user_id" not in session:
        return
    other_id = int(data.get("other_id", 0))
    join_room(pm_room(session["user_id"], other_id))


@socketio.on("mark_private_read")
def socket_mark_private_read(data):
    if "user_id" not in session:
        return
    other_id = int(data.get("other_id", 0))
    if not other_id:
        return
    uid = session["user_id"]
    with get_db() as conn:
        read_grouped = mark_private_messages_read(conn, uid, other_id)
    emit_private_status_updates(read_grouped, "read")


@socketio.on("join_channel")
def socket_join_channel(data):
    if "user_id" not in session:
        return
    channel_id = int(data.get("channel_id", 0))
    uid = session["user_id"]
    with get_db() as conn:
        member = conn.execute(
            "SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",
            (channel_id, uid),
        ).fetchone()
    if member:
        join_room(f"channel_{channel_id}")


@socketio.on("send_private_message")
def socket_send_private_message(data):
    if "user_id" not in session:
        return

    other_id = int(data.get("other_id", 0))
    text = data.get("text", "").strip()
    if not other_id or not text:
        return

    uid = session["user_id"]
    if not check_socket_rate(uid, "send_private_message", 30, 60):
        emit_rate_limit_error()
        return

    with get_db() as conn:
        can_send, reason = can_send_private_message(conn, uid, other_id)
        if not can_send:
            emit("app_error", {"error": reason})
            return

        created_at = now_str()
        receiver_online = other_id in online_users.values()
        delivery_status = "delivered" if receiver_online else "sent"
        delivered_at = created_at if receiver_online else None
        cur = conn.execute(
            """INSERT INTO messages (chat_type, sender_id, receiver_id, username, text, delivery_status, delivered_at, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                "private",
                uid,
                other_id,
                session["username"],
                text,
                delivery_status,
                delivered_at,
                created_at,
            ),
        )
        message_id = cur.lastrowid
        conn.execute(
            """DELETE FROM hidden_private_chats
               WHERE (user_id=? AND peer_id=?) OR (user_id=? AND peer_id=?)""",
            (uid, other_id, other_id, uid),
        )

    payload = {
        "id": message_id,
        "chat_type": "private",
        "sender_id": uid,
        "receiver_id": other_id,
        "username": session["username"],
        "display_name": session.get("display_name", session["username"]),
        "text": text,
        "delivery_status": delivery_status,
        "delivered_at": delivered_at,
        "read_at": None,
        "created_at": created_at,
    }
    emit("new_private_message", payload, to=f"user_{uid}")
    emit("new_private_message", payload, to=f"user_{other_id}")


@socketio.on("send_channel_message")
def socket_send_channel_message(data):
    if "user_id" not in session:
        return

    channel_id = int(data.get("channel_id", 0))
    text = data.get("text", "").strip()
    if not channel_id or not text:
        return

    uid = session["user_id"]
    if not check_socket_rate(uid, "send_channel_message", 20, 60):
        emit_rate_limit_error()
        return

    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role is None:
            emit("app_error", {"error": "Канал не найден"})
            return
        if role not in ("owner", "admin"):
            emit(
                "app_error", {"error": "Писать в канал может только владелец или админ"}
            )
            return

        created_at = now_str()
        conn.execute(
            """INSERT INTO messages (chat_type, channel_id, sender_id, username, text, created_at)
               VALUES (?,?,?,?,?,?)""",
            ("channel", channel_id, uid, session["username"], text, created_at),
        )

    emit(
        "new_channel_message",
        {
            "chat_type": "channel",
            "channel_id": channel_id,
            "sender_id": uid,
            "username": session["username"],
            "display_name": session.get("display_name", session["username"]),
            "text": text,
            "created_at": created_at,
        },
        to=f"channel_{channel_id}",
    )


init_db()


if __name__ == "__main__":
    print("MiniGram: http://127.0.0.1:5000")
    print(f"База данных: {DB_PATH}")
    if DB_ENCRYPTION_ENABLED:
        print("Серверное шифрование базы включено: SQLCipher.")
    else:
        print(
            "Серверное шифрование базы выключено: задайте DB_ENCRYPTION_KEY для SQLCipher."
        )
    if not SMTP_USER or not SMTP_PASS:
        print("SMTP не задан: коды подтверждения будут печататься в консоль.")
    host = os.environ.get("APP_HOST", "0.0.0.0")
    port = int(os.environ.get("APP_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)
