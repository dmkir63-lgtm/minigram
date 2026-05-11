from flask import jsonify, redirect, render_template, request, session

from core import *
from extensions import app, limiter


@app.route("/register", methods=["POST"])
@limiter.limit("3 per hour;10 per day")
def register():
    data = request.get_json(silent=True) or {}
    username = clean_tag(data.get("username", ""))
    display_name = data.get("display_name", "").strip()
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not username or not display_name or not email or not password:
        return jsonify({"error": "Заполните все поля"}), 400
    tag_error = validate_tag(username, "Тег пользователя")
    if tag_error:
        return jsonify({"error": tag_error}), 400
    if len(display_name) > 40:
        return jsonify({"error": "Ник максимум 40 символов"}), 400
    if "@" not in email or "." not in email:
        return jsonify({"error": "Неверный формат email"}), 400
    if len(password) < 6:
        return jsonify({"error": "Пароль минимум 6 символов"}), 400

    with get_db() as conn:
        if conn.execute(
            "SELECT 1 FROM users WHERE lower(username)=lower(?)", (username,)
        ).fetchone():
            return jsonify({"error": "Такой тег уже занят"}), 409
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            return jsonify({"error": "Email уже зарегистрирован"}), 409

        code = gen_code()
        expires_at = (datetime.now() + timedelta(minutes=10)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn.execute("DELETE FROM email_codes WHERE email=?", (email,))
        conn.execute(
            """INSERT INTO email_codes (email, code, username, display_name, password_hash, expires_at)
               VALUES (?,?,?,?,?,?)""",
            (email, code, username, display_name, hash_password(password), expires_at),
        )

    ok = send_email(
        email,
        "MiniGram — код подтверждения",
        f"Привет, {display_name}!\n\nВаш код подтверждения: {code}\nКод действует 10 минут.",
    )
    if not ok:
        return jsonify({"error": "Не получилось отправить письмо"}), 500
    return jsonify({"ok": True})


@app.route("/verify", methods=["POST"])
@limiter.limit("5 per minute;20 per hour")
def verify():
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip().lower()
    code = data.get("code", "").strip()

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM email_codes WHERE email=? AND code=?", (email, code)
        ).fetchone()
        if not row:
            return jsonify({"error": "Неверный код"}), 400
        if datetime.now() > datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S"):
            conn.execute("DELETE FROM email_codes WHERE email=?", (email,))
            return jsonify({"error": "Код истёк, зарегистрируйтесь снова"}), 400

        display_name = row["display_name"] or row["username"]
        try:
            cur = conn.execute(
                """INSERT INTO users (username, display_name, email, password_hash, pm_privacy, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    row["username"],
                    display_name,
                    email,
                    row["password_hash"],
                    "everyone",
                    now_str(),
                ),
            )
        except sqlite3.IntegrityError:
            return jsonify({"error": "Тег или email уже заняты"}), 409

        conn.execute("DELETE FROM email_codes WHERE email=?", (email,))
        session["user_id"] = cur.lastrowid
        session["username"] = row["username"]
        session["display_name"] = display_name

    return jsonify({"ok": True})


@app.route("/login", methods=["POST"])
@limiter.limit("5 per minute;30 per hour")
def login():
    data = request.get_json(silent=True) or {}
    login_value = data.get("login", "").strip().lstrip("@")
    password = data.get("password", "").strip()

    with get_db() as conn:
        user = conn.execute(
            """SELECT *, COALESCE(display_name, username) AS display_name_fixed
               FROM users
               WHERE (email=? OR lower(username)=lower(?)) AND password_hash=?""",
            (login_value.lower(), login_value, hash_password(password)),
        ).fetchone()

    if not user:
        return jsonify({"error": "Неверный логин или пароль"}), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["display_name"] = user["display_name_fixed"]
    return jsonify({"ok": True})


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")
