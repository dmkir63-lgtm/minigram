from flask import jsonify, redirect, render_template, request, session

from core import *
from extensions import app, limiter


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
        payload = attach_message_reactions(conn, reversed(messages), uid)

    return jsonify(payload)


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
        payload = attach_message_reactions(conn, reversed(messages), uid)

    return jsonify(payload)


@app.route("/messages/<int:message_id>", methods=["DELETE"])
@limiter.limit("60 per minute")
def delete_message(message_id):
    err = require_login_json()
    if err:
        return err

    uid = session["user_id"]
    with get_db() as conn:
        message, role, reason = message_access(conn, message_id, uid)
        if reason:
            status = 404 if "найдено" in reason else 403
            return jsonify({"error": reason}), status

        can_delete = message["sender_id"] == uid
        if message["chat_type"] == "channel" and role in ("owner", "admin"):
            can_delete = True
        if not can_delete:
            return jsonify({"error": "Удалить можно только своё сообщение"}), 403

        targets = message_emit_targets(message)
        conn.execute("DELETE FROM message_reactions WHERE message_id=?", (message_id,))
        conn.execute("DELETE FROM messages WHERE id=?", (message_id,))

    payload = {
        "message_id": message_id,
        "chat_type": message["chat_type"],
        "channel_id": message["channel_id"],
        "sender_id": message["sender_id"],
        "receiver_id": message["receiver_id"],
    }
    for target in targets:
        socketio.emit("message_deleted", payload, to=target)
    return jsonify({"ok": True})


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
