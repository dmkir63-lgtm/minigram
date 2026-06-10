import hashlib
import secrets
from functools import wraps

from flask import g, jsonify, request

from core import *
from extensions import app, limiter, socketio


API_PREFIX = "/api/v1"
MAX_MESSAGE_LEN = 4000


def api_error(message, status):
    return jsonify({"error": message}), status


def token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def make_api_token():
    return "mg_" + secrets.token_urlsafe(32)


def row_to_dict(row):
    return dict(row) if row else None


def int_arg(name, default, minimum, maximum):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return min(max(value, minimum), maximum)


def require_api_token(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = request.headers.get("X-API-Token", "").strip()
        if not token:
            return api_error("API token is required", 401)

        hashed = token_hash(token)
        with get_db() as conn:
            row = conn.execute(
                """SELECT t.id AS token_id, u.id, u.username,
                          COALESCE(u.display_name, u.username) AS display_name,
                          u.email, u.pm_privacy, u.email_notifications_mode, u.created_at
                   FROM api_tokens t
                   JOIN users u ON u.id=t.user_id
                   WHERE t.token_hash=?""",
                (hashed,),
            ).fetchone()
            if not row:
                return api_error("Invalid API token", 401)
            conn.execute(
                "UPDATE api_tokens SET last_used_at=? WHERE id=?",
                (now_str(), row["token_id"]),
            )

        g.api_user = row
        g.api_token_id = row["token_id"]
        return view(*args, **kwargs)

    return wrapper


def current_user_id():
    return int(g.api_user["id"])


def user_payload(row):
    item = dict(row)
    item.pop("token_id", None)
    item.pop("password_hash", None)
    return item


def channel_message_payload(row):
    return row_to_dict(row)


@app.route(f"{API_PREFIX}/tokens", methods=["POST"])
@limiter.limit("10 per minute;60 per hour")
def api_create_token():
    data = request.get_json(silent=True) or {}
    login_value = data.get("login", "").strip().lstrip("@")
    password = data.get("password", "").strip()
    name = data.get("name", "").strip()[:80] or "API token"

    if not login_value or not password:
        return api_error("login and password are required", 400)

    with get_db() as conn:
        user = conn.execute(
            """SELECT id, username, COALESCE(display_name, username) AS display_name,
                      email, pm_privacy, email_notifications_mode, created_at
               FROM users
               WHERE (email=? OR lower(username)=lower(?)) AND password_hash=?""",
            (login_value.lower(), login_value, hash_password(password)),
        ).fetchone()
        if not user:
            return api_error("Invalid login or password", 401)

        token = make_api_token()
        created_at = now_str()
        conn.execute(
            """INSERT INTO api_tokens (user_id, name, token_hash, created_at)
               VALUES (?,?,?,?)""",
            (user["id"], name, token_hash(token), created_at),
        )

    return jsonify(
        {
            "ok": True,
            "token": token,
            "token_type": "Bearer",
            "user": user_payload(user),
        }
    ), 201


@app.route(f"{API_PREFIX}/tokens/current", methods=["DELETE"])
@require_api_token
def api_revoke_current_token():
    with get_db() as conn:
        conn.execute("DELETE FROM api_tokens WHERE id=?", (g.api_token_id,))
    return jsonify({"ok": True})


@app.route(f"{API_PREFIX}/me")
@require_api_token
def api_me():
    return jsonify(user_payload(g.api_user))


@app.route(f"{API_PREFIX}/users")
@require_api_token
@limiter.limit("60 per minute")
def api_users():
    q = request.args.get("q", "").strip().lstrip("@")
    limit = int_arg("limit", 20, 1, 50)
    if len(q) < 2:
        return jsonify({"users": []})

    uid = current_user_id()
    pattern = f"%{q}%"
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, username, COALESCE(display_name, username) AS display_name,
                      pm_privacy, created_at
               FROM users
               WHERE id!=? AND (username LIKE ? OR display_name LIKE ?)
               ORDER BY LOWER(COALESCE(display_name, username)), LOWER(username)
               LIMIT ?""",
            (uid, pattern, pattern, limit),
        ).fetchall()
        users = []
        for row in rows:
            item = dict(row)
            state = private_chat_state(conn, uid, row["id"])
            if state:
                item.update(state)
            users.append(item)

    return jsonify({"users": users})


@app.route(f"{API_PREFIX}/users/<int:user_id>")
@require_api_token
def api_user(user_id):
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, username, COALESCE(display_name, username) AS display_name,
                      pm_privacy, created_at
               FROM users WHERE id=?""",
            (user_id,),
        ).fetchone()
        if not row:
            return api_error("User not found", 404)
        payload = dict(row)
        if user_id != current_user_id():
            state = private_chat_state(conn, current_user_id(), user_id)
            if state:
                payload.update(state)
    return jsonify(payload)


@app.route(f"{API_PREFIX}/private/chats")
@require_api_token
def api_private_chats():
    uid = current_user_id()
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
            (uid, uid, uid, uid, uid, uid, uid, uid, uid, uid),
        ).fetchall()

        online = set(online_users.values())
        chats = []
        for row in rows:
            state = private_chat_state(conn, uid, row["id"])
            item = dict(row)
            if state:
                item.update(state)
            item["online"] = row["id"] in online
            chats.append(item)

    return jsonify({"chats": chats})


@app.route(f"{API_PREFIX}/private/messages/<int:other_id>")
@require_api_token
def api_private_messages(other_id):
    uid = current_user_id()
    limit = int_arg("limit", 80, 1, 200)
    before_id = int_arg("before_id", 0, 0, 2**31 - 1)

    with get_db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE id=?", (other_id,)).fetchone():
            return api_error("User not found", 404)
        params = [uid, other_id, other_id, uid]
        before_sql = ""
        if before_id:
            before_sql = " AND m.id<?"
            params.append(before_id)
        params.append(limit)
        rows = conn.execute(
            f"""SELECT m.id, m.chat_type, m.sender_id, m.receiver_id,
                       u.username, COALESCE(u.display_name, m.username) AS display_name,
                       m.text, m.delivery_status, m.delivered_at, m.read_at, m.created_at
                FROM messages m
                LEFT JOIN users u ON u.id=m.sender_id
                WHERE m.chat_type='private'
                  AND ((m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?))
                  {before_sql}
                ORDER BY m.id DESC
                LIMIT ?""",
            params,
        ).fetchall()

    return jsonify({"messages": [dict(row) for row in reversed(rows)]})


@app.route(f"{API_PREFIX}/private/messages", methods=["POST"])
@require_api_token
@limiter.limit("30 per minute")
def api_send_private_message():
    data = request.get_json(silent=True) or {}
    try:
        receiver_id = int(data.get("receiver_id", 0))
    except (TypeError, ValueError):
        receiver_id = 0
    text = data.get("text", "").strip()

    if not receiver_id:
        return api_error("receiver_id is required", 400)
    if not text:
        return api_error("text is required", 400)
    if len(text) > MAX_MESSAGE_LEN:
        return api_error(f"text is too long, max {MAX_MESSAGE_LEN} characters", 400)

    uid = current_user_id()
    with get_db() as conn:
        can_send, reason = can_send_private_message(conn, uid, receiver_id)
        if not can_send:
            return api_error(reason or "Cannot send message", 403)

        receiver_online = receiver_id in online_users.values()
        payload = insert_private_message(
            conn,
            uid,
            receiver_id,
            g.api_user["username"],
            g.api_user["display_name"],
            text,
            receiver_online,
        )

    emit_private_message(payload)
    notify_telegram_private_message(receiver_id, uid, payload, receiver_online)
    notify_email_private_message(receiver_id, uid, payload, receiver_online)
    return jsonify({"ok": True, "message": payload}), 201


@app.route(f"{API_PREFIX}/channels")
@require_api_token
def api_channels():
    uid = current_user_id()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.id, c.name, c.username, c.description, c.owner_id, c.invite_code,
                      c.is_private, c.created_at,
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

    channels = []
    for row in rows:
        item = dict(row)
        item["is_private"] = bool(item["is_private"])
        if item["owner_id"] == uid:
            item["role"] = "owner"
        channels.append(item)
    return jsonify({"channels": channels})


@app.route(f"{API_PREFIX}/channels/<int:channel_id>/messages")
@require_api_token
def api_channel_messages(channel_id):
    uid = current_user_id()
    limit = int_arg("limit", 80, 1, 200)
    before_id = int_arg("before_id", 0, 0, 2**31 - 1)

    with get_db() as conn:
        member = conn.execute(
            "SELECT 1 FROM channel_members WHERE channel_id=? AND user_id=?",
            (channel_id, uid),
        ).fetchone()
        if not member:
            return api_error("No access to channel", 403)
        params = [channel_id]
        before_sql = ""
        if before_id:
            before_sql = " AND m.id<?"
            params.append(before_id)
        params.append(limit)
        rows = conn.execute(
            f"""SELECT m.id, m.chat_type, m.channel_id, m.sender_id,
                       u.username, COALESCE(u.display_name, m.username) AS display_name,
                       m.text, m.created_at
                FROM messages m
                LEFT JOIN users u ON u.id=m.sender_id
                WHERE m.chat_type='channel' AND m.channel_id=?
                  {before_sql}
                ORDER BY m.id DESC
                LIMIT ?""",
            params,
        ).fetchall()

    return jsonify({"messages": [channel_message_payload(row) for row in reversed(rows)]})


@app.route(f"{API_PREFIX}/channels/<int:channel_id>/messages", methods=["POST"])
@require_api_token
@limiter.limit("20 per minute")
def api_send_channel_message(channel_id):
    data = request.get_json(silent=True) or {}
    text = data.get("text", "").strip()
    if not text:
        return api_error("text is required", 400)
    if len(text) > MAX_MESSAGE_LEN:
        return api_error(f"text is too long, max {MAX_MESSAGE_LEN} characters", 400)

    uid = current_user_id()
    with get_db() as conn:
        role = get_channel_role(conn, channel_id, uid)
        if role is None:
            return api_error("Channel not found", 404)
        if role not in ("owner", "admin"):
            return api_error("Only owner or admin can post to channel", 403)

        created_at = now_str()
        cur = conn.execute(
            """INSERT INTO messages (chat_type, channel_id, sender_id, username, text, created_at)
               VALUES (?,?,?,?,?,?)""",
            ("channel", channel_id, uid, g.api_user["username"], text, created_at),
        )
        payload = {
            "id": cur.lastrowid,
            "chat_type": "channel",
            "channel_id": channel_id,
            "sender_id": uid,
            "username": g.api_user["username"],
            "display_name": g.api_user["display_name"],
            "text": text,
            "created_at": created_at,
        }

    socketio.emit("new_channel_message", payload, to=f"channel_{channel_id}")
    return jsonify({"ok": True, "message": payload}), 201
