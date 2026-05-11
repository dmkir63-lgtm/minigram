from flask import jsonify, redirect, render_template, request, session

from core import *
from extensions import app, limiter


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
