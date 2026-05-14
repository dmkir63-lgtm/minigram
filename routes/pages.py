from flask import jsonify, redirect, render_template, request, session

from core import *
from extensions import app, limiter


@app.route("/")
def index():
    if "user_id" not in session:
        return render_template("landing.html")
    user = get_user(session["user_id"])
    if not user:
        session.clear()
        return redirect("/")
    session["username"] = user["username"]
    session["display_name"] = user["display_name"]
    return render_template("chat.html", user=user)

@app.route("/landing")
def index():
    return render_template("landing.html", user=user)

@app.route("/auth")
@app.route("/login", methods=["GET"])
def login_page():
    if "user_id" in session:
        return redirect("/")
    default_tab = request.args.get("tab", "login")
    if default_tab not in ("login", "register"):
        default_tab = "login"
    next_url = request.args.get("next", "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    return render_template("auth.html", default_tab=default_tab, next_url=next_url)


@app.route("/register", methods=["GET"])
def register_page():
    if "user_id" in session:
        return redirect("/")
    next_url = request.args.get("next", "/")
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/"
    return render_template("auth.html", default_tab="register", next_url=next_url)
