from flask import jsonify, redirect, render_template, request, session

from core import *
from extensions import app, limiter


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
