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
