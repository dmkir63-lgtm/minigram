from flask import jsonify, redirect, render_template, request, session

from core import *
from extensions import app, limiter


@app.route("/me/settings")
def me_settings():
    err = require_login_json()
    if err:
        return err

    user = get_user(session["user_id"])
    with get_db() as conn:
        telegram = conn.execute(
            """SELECT telegram_username, notifications_mode, linked_at
               FROM telegram_links WHERE user_id=?""",
            (session["user_id"],),
        ).fetchone()
    return jsonify(
        {
            "id": user["id"],
            "username": user["username"],
            "display_name": user["display_name"],
            "email": user["email"],
            "pm_privacy": user["pm_privacy"],
            "telegram": (
                {
                    "linked": True,
                    "telegram_username": telegram["telegram_username"],
                    "notifications_mode": telegram["notifications_mode"],
                    "linked_at": telegram["linked_at"],
                }
                if telegram
                else {"linked": False, "notifications_mode": "offline"}
            ),
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
