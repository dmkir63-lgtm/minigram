from flask import jsonify, request, session

from config import TELEGRAM_BOT_USERNAME, TELEGRAM_WEBHOOK_SECRET
from core import *
from extensions import app, limiter


def telegram_link_status(conn, user_id):
    row = conn.execute(
        """SELECT telegram_chat_id, telegram_user_id, telegram_username,
                  notifications_mode, linked_at
           FROM telegram_links WHERE user_id=?""",
        (user_id,),
    ).fetchone()
    if not row:
        return {"linked": False, "notifications_mode": "offline"}
    item = dict(row)
    item["linked"] = True
    return item


@app.route("/me/telegram/link-token", methods=["POST"])
@limiter.limit("10 per hour")
def create_telegram_link_token():
    err = require_login_json()
    if err:
        return err

    token = gen_link_token()
    created_at = now_str()
    expires_at = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

    with get_db() as conn:
        conn.execute("DELETE FROM telegram_link_tokens WHERE user_id=?", (session["user_id"],))
        conn.execute(
            """INSERT INTO telegram_link_tokens (user_id, token, created_at, expires_at)
               VALUES (?,?,?,?)""",
            (session["user_id"], token, created_at, expires_at),
        )

    deep_link = None
    if TELEGRAM_BOT_USERNAME:
        deep_link = f"https://t.me/{TELEGRAM_BOT_USERNAME}?start={token}"

    return jsonify(
        {
            "token": token,
            "bot_username": TELEGRAM_BOT_USERNAME,
            "deep_link": deep_link,
            "expires_at": expires_at,
        }
    )


@app.route("/me/telegram", methods=["PATCH"])
@limiter.limit("20 per minute")
def update_telegram_settings():
    err = require_login_json()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    mode = data.get("notifications_mode")
    if mode not in ("disabled", "offline", "all"):
        return jsonify({"error": "Неизвестный режим Telegram-уведомлений"}), 400

    with get_db() as conn:
        link = conn.execute(
            "SELECT 1 FROM telegram_links WHERE user_id=?", (session["user_id"],)
        ).fetchone()
        if not link:
            return jsonify({"error": "Telegram ещё не подключён"}), 400
        conn.execute(
            "UPDATE telegram_links SET notifications_mode=?, updated_at=? WHERE user_id=?",
            (mode, now_str(), session["user_id"]),
        )
        return jsonify({"ok": True, "telegram": telegram_link_status(conn, session["user_id"])})


@app.route("/me/telegram", methods=["DELETE"])
@limiter.limit("10 per hour")
def unlink_telegram():
    err = require_login_json()
    if err:
        return err

    with get_db() as conn:
        conn.execute("DELETE FROM telegram_links WHERE user_id=?", (session["user_id"],))
        conn.execute("DELETE FROM telegram_link_tokens WHERE user_id=?", (session["user_id"],))

    return jsonify({"ok": True, "telegram": {"linked": False, "notifications_mode": "offline"}})


def link_telegram_account(chat_id, tg_user, token):
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM telegram_link_tokens
               WHERE token=? AND expires_at >= ?""",
            (token, now_str()),
        ).fetchone()
        if not row:
            send_telegram_message(chat_id, "Код привязки не найден или истёк. Создайте новый в настройках MiniGram.")
            return

        existing = conn.execute(
            """SELECT user_id FROM telegram_links
               WHERE telegram_chat_id=? AND user_id!=?""",
            (str(chat_id), row["user_id"]),
        ).fetchone()
        if existing:
            send_telegram_message(chat_id, "Этот Telegram уже привязан к другому аккаунту MiniGram.")
            return

        conn.execute(
            """INSERT INTO telegram_links
               (user_id, telegram_chat_id, telegram_user_id, telegram_username,
                notifications_mode, linked_at, updated_at)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(user_id) DO UPDATE SET
                 telegram_chat_id=excluded.telegram_chat_id,
                 telegram_user_id=excluded.telegram_user_id,
                 telegram_username=excluded.telegram_username,
                 updated_at=excluded.updated_at""",
            (
                row["user_id"],
                str(chat_id),
                str(tg_user.get("id", "")),
                tg_user.get("username", ""),
                "offline",
                now_str(),
                now_str(),
            ),
        )
        conn.execute("DELETE FROM telegram_link_tokens WHERE user_id=?", (row["user_id"],))

    send_telegram_message(
        chat_id,
        "Telegram подключён к MiniGram. Используйте /to username текст, чтобы написать пользователю.",
    )


def send_private_from_telegram(chat_id, link, receiver, text):
    sender_id = link["user_id"]
    receiver_id = receiver["id"]
    if sender_id == receiver_id:
        send_telegram_message(chat_id, "Нельзя отправить сообщение самому себе.")
        return

    if not check_socket_rate(sender_id, "telegram_private_message", 30, 60):
        send_telegram_message(chat_id, "Слишком много сообщений. Попробуйте позже.")
        return

    with get_db() as conn:
        can_send, reason = can_send_private_message(conn, sender_id, receiver_id)
        if not can_send:
            send_telegram_message(chat_id, reason)
            return

        sender = conn.execute(
            """SELECT username, COALESCE(display_name, username) AS display_name
               FROM users WHERE id=?""",
            (sender_id,),
        ).fetchone()
        receiver_online = receiver_id in online_users.values()
        payload = insert_private_message(
            conn,
            sender_id,
            receiver_id,
            sender["username"],
            sender["display_name"],
            text,
            receiver_online,
        )
        conn.execute(
            "UPDATE telegram_links SET last_peer_id=?, updated_at=? WHERE user_id=?",
            (receiver_id, now_str(), sender_id),
        )

    emit_private_message(payload)
    notify_telegram_private_message(receiver_id, sender_id, payload, receiver_online)
    notify_email_private_message(receiver_id, sender_id, payload, receiver_online)
    send_telegram_message(chat_id, f"Отправлено @{receiver['username']}.")


def handle_telegram_text(chat_id, tg_user, text):
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2:
            link_telegram_account(chat_id, tg_user, parts[1].strip())
            return
        send_telegram_message(chat_id, "Создайте код привязки в настройках MiniGram и откройте ссылку ещё раз.")
        return

    with get_db() as conn:
        link = conn.execute(
            """SELECT tl.*, u.username, COALESCE(u.display_name, u.username) AS display_name
               FROM telegram_links tl
               JOIN users u ON u.id=tl.user_id
               WHERE tl.telegram_chat_id=?""",
            (str(chat_id),),
        ).fetchone()

        if not link:
            send_telegram_message(chat_id, "Telegram не подключён. Сначала привяжите его в настройках MiniGram.")
            return
        link = dict(link)

        if text == "/help":
            send_telegram_message(
                chat_id,
                "Команды:\n/to username текст — написать пользователю\n/unlink — отвязать Telegram\n\n"
                "Если вам пришло сообщение из MiniGram, можно ответить обычным текстом.",
            )
            return

        if text == "/unlink":
            conn.execute("DELETE FROM telegram_links WHERE user_id=?", (link["user_id"],))
            send_telegram_message(chat_id, "Telegram отвязан от MiniGram.")
            return

        receiver = None
        body = text
        if text.startswith("/to "):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                send_telegram_message(chat_id, "Формат: /to username текст")
                return
            username = clean_tag(parts[1])
            body = parts[2].strip()
            receiver = conn.execute(
                """SELECT id, username, COALESCE(display_name, username) AS display_name
                   FROM users WHERE lower(username)=lower(?)""",
                (username,),
            ).fetchone()
            if not receiver:
                send_telegram_message(chat_id, f"Пользователь @{username} не найден.")
                return
            receiver = dict(receiver)
        elif link["last_peer_id"]:
            receiver = conn.execute(
                """SELECT id, username, COALESCE(display_name, username) AS display_name
                   FROM users WHERE id=?""",
                (link["last_peer_id"],),
            ).fetchone()
            if receiver:
                receiver = dict(receiver)

    if not body:
        send_telegram_message(chat_id, "Пустое сообщение не отправлено.")
        return
    if not receiver:
        send_telegram_message(chat_id, "Не выбран получатель. Используйте /to username текст.")
        return

    send_private_from_telegram(chat_id, link, receiver, body)


@app.route("/telegram/webhook", methods=["POST"])
@limiter.exempt
def telegram_webhook():
    if TELEGRAM_WEBHOOK_SECRET:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != TELEGRAM_WEBHOOK_SECRET:
            return jsonify({"error": "Forbidden"}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message")
    if not message:
        return jsonify({"ok": True})

    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    tg_user = message.get("from") or {}
    chat_id = chat.get("id")

    if chat_id and text:
        handle_telegram_text(str(chat_id), tg_user, text)

    return jsonify({"ok": True})
