from datetime import datetime, timedelta
from email.mime.text import MIMEText
import hashlib
import random
import re
import smtplib
import string
import time
import os

from flask import jsonify, session
from flask_socketio import emit

from config import (
    DB_ENCRYPTION_ENABLED,
    DB_ENCRYPTION_KEY,
    DB_PATH,
    SMTP_HOST,
    SMTP_PASS,
    SMTP_PORT,
    SMTP_USER,
    sqlite3,
)
from extensions import socketio

online_users = {}
socket_rate_events = {}
TAG_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sql_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def ensure_db_storage():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)


def get_db():
    ensure_db_storage()
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
    seed_fake_data()


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

def seed_fake_data(conn):
    if os.environ.get("SEED_FAKE_DATA", "1") != "1":
        return

    created_at = now_str()

    users = [
        ("alice", "Алиса", "alice@minigram.demo", "123456", "everyone"),
        ("bob", "Боб", "bob@minigram.demo", "123456", "everyone"),
        ("carol", "Карина", "carol@minigram.demo", "123456", "friends"),
        ("dima", "Дима", "dima@minigram.demo", "123456", "everyone"),
        ("eva", "Ева", "eva@minigram.demo", "123456", "friends"),
    ]

    for username, display_name, email, password, pm_privacy in users:
        conn.execute(
            """INSERT OR IGNORE INTO users
               (username, display_name, email, password_hash, pm_privacy, created_at)
               VALUES (?,?,?,?,?,?)""",
            (
                username,
                display_name,
                email,
                hash_password(password),
                pm_privacy,
                created_at,
            ),
        )

    usernames = [user[0] for user in users]
    placeholders = ",".join("?" for _ in usernames)
    user_rows = conn.execute(
        f"SELECT id, username FROM users WHERE username IN ({placeholders})",
        usernames,
    ).fetchall()
    user_ids = {row["username"]: row["id"] for row in user_rows}

    if len(user_ids) != len(users):
        return

    friendships = [
        ("alice", "bob"),
        ("alice", "carol"),
        ("bob", "dima"),
        ("carol", "eva"),
    ]

    for from_username, to_username in friendships:
        conn.execute(
            """INSERT OR IGNORE INTO friend_requests
               (from_id, to_id, status, created_at)
               VALUES (?,?,?,?)""",
            (
                user_ids[from_username],
                user_ids[to_username],
                "accepted",
                created_at,
            ),
        )

    channels = [
        (
            "Общий чат",
            "general",
            "Публичный канал для общения и тестирования MiniGram.",
            "alice",
            "demo_general_invite",
            0,
        ),
        (
            "Новости проекта",
            "project_news",
            "Канал с новостями учебного проекта.",
            "bob",
            "demo_project_news",
            0,
        ),
        (
            "Закрытый клуб",
            "private_club",
            "Приватный канал, куда можно попасть только после одобрения заявки.",
            "alice",
            "demo_private_club",
            1,
        ),
    ]

    for name, username, description, owner_username, invite_code, is_private in channels:
        conn.execute(
            """INSERT OR IGNORE INTO channels
               (name, username, description, owner_id, invite_code, is_private, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                name,
                username,
                description,
                user_ids[owner_username],
                invite_code,
                is_private,
                created_at,
            ),
        )

    channel_usernames = [channel[1] for channel in channels]
    placeholders = ",".join("?" for _ in channel_usernames)
    channel_rows = conn.execute(
        f"SELECT id, username FROM channels WHERE username IN ({placeholders})",
        channel_usernames,
    ).fetchall()
    channel_ids = {row["username"]: row["id"] for row in channel_rows}

    members = {
        "general": [
            ("alice", "owner"),
            ("bob", "admin"),
            ("carol", "subscriber"),
            ("dima", "subscriber"),
            ("eva", "subscriber"),
        ],
        "project_news": [
            ("bob", "owner"),
            ("alice", "admin"),
            ("dima", "subscriber"),
        ],
        "private_club": [
            ("alice", "owner"),
            ("carol", "admin"),
        ],
    }

    for channel_username, channel_members in members.items():
        channel_id = channel_ids.get(channel_username)
        if not channel_id:
            continue
        for member_username, role in channel_members:
            conn.execute(
                """INSERT OR IGNORE INTO channel_members
                   (channel_id, user_id, role, joined_at)
                   VALUES (?,?,?,?)""",
                (
                    channel_id,
                    user_ids[member_username],
                    role,
                    created_at,
                ),
            )

    private_channel_id = channel_ids.get("private_club")
    if private_channel_id:
        conn.execute(
            """INSERT OR IGNORE INTO channel_join_requests
               (channel_id, user_id, status, created_at)
               VALUES (?,?,?,?)""",
            (
                private_channel_id,
                user_ids["eva"],
                "pending",
                created_at,
            ),
        )

    channel_messages = {
        "general": [
            ("alice", "Добро пожаловать в MiniGram! Это демо-канал."),
            ("bob", "Сообщения в каналах приходят через Socket.IO."),
            ("dima", "Можно проверить роли, подписчиков и историю сообщений."),
        ],
        "project_news": [
            ("bob", "Сегодня добавили автоматическое создание тестовых данных."),
            ("alice", "Теперь после перезапуска база сама наполняется демо-контентом."),
        ],
        "private_club": [
            ("alice", "Это пример закрытого канала."),
            ("carol", "Новые участники попадают сюда только после одобрения."),
        ],
    }

    for channel_username, messages in channel_messages.items():
        channel_id = channel_ids.get(channel_username)
        if not channel_id:
            continue
        has_messages = conn.execute(
            "SELECT 1 FROM messages WHERE chat_type='channel' AND channel_id=? LIMIT 1",
            (channel_id,),
        ).fetchone()
        if has_messages:
            continue
        for sender_username, text in messages:
            conn.execute(
                """INSERT INTO messages
                   (chat_type, channel_id, sender_id, username, text, delivery_status, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    "channel",
                    channel_id,
                    user_ids[sender_username],
                    sender_username,
                    text,
                    "sent",
                    created_at,
                ),
            )

    private_pairs = [
        (
            "alice",
            "bob",
            [
                ("alice", "Привет! Это тестовая личная переписка."),
                ("bob", "Да, можно проверить статус доставки и историю."),
                ("alice", "Отлично, значит демо-данные работают."),
            ],
        ),
        (
            "carol",
            "eva",
            [
                ("carol", "Привет, я добавила тебя в друзья."),
                ("eva", "Супер, теперь можно тестировать приватные сообщения."),
            ],
        ),
    ]

    for first_username, second_username, messages in private_pairs:
        first_id = user_ids[first_username]
        second_id = user_ids[second_username]
        has_messages = conn.execute(
            """SELECT 1 FROM messages
               WHERE chat_type='private'
                 AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))
               LIMIT 1""",
            (first_id, second_id, second_id, first_id),
        ).fetchone()
        if has_messages:
            continue

        for sender_username, text in messages:
            sender_id = user_ids[sender_username]
            receiver_username = second_username if sender_username == first_username else first_username
            receiver_id = user_ids[receiver_username]
            conn.execute(
                """INSERT INTO messages
                   (chat_type, sender_id, receiver_id, username, text,
                    delivery_status, delivered_at, read_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    "private",
                    sender_id,
                    receiver_id,
                    sender_username,
                    text,
                    "read",
                    created_at,
                    created_at,
                    created_at,
                ),
            )