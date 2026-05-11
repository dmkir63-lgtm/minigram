from flask import request, session
from flask_socketio import emit, join_room

from core import *
from extensions import socketio


@socketio.on("connect")
def socket_connect(auth=None):
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
