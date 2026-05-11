from flask import jsonify, redirect, render_template, request, session

from core import *
from extensions import app, limiter


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
