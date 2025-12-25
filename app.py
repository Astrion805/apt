from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "apt_secret_key"
DB = "apt.db"

# ---------- DB ----------
def get_db():
    return sqlite3.connect(DB)

def init_db():
    db = get_db()
    c = db.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        content TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT,
        receiver TEXT,
        content TEXT
    )""")
    db.commit()

init_db()

# ---------- AUTH ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=?", (u,)
        ).fetchone()

        if user and check_password_hash(user[2], p):
            session["user"] = u
            return redirect("/feed")

    return render_template("login.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        u = request.form["username"]
        p = generate_password_hash(request.form["password"])

        db = get_db()
        try:
            db.execute(
                "INSERT INTO users(username,password) VALUES(?,?)", (u, p)
            )
            db.commit()
            return redirect("/")
        except:
            pass

    return render_template("register.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect("/")

# ---------- FEED ----------
@app.route("/feed", methods=["GET", "POST"])
def feed():
    if "user" not in session:
        return redirect("/")

    db = get_db()

    if request.method == "POST":
        db.execute(
            "INSERT INTO posts(user,content) VALUES(?,?)",
            (session["user"], request.form["post"])
        )
        db.commit()

    posts = db.execute("SELECT * FROM posts ORDER BY id DESC").fetchall()
    return render_template("feed.html", posts=posts)

# ---------- CHAT ----------
@app.route("/chat/<user>", methods=["GET", "POST"])
def chat(user):
    if "user" not in session:
        return redirect("/")

    db = get_db()

    if request.method == "POST":
        db.execute(
            "INSERT INTO messages(sender,receiver,content) VALUES(?,?,?)",
            (session["user"], user, request.form["msg"])
        )
        db.commit()

    msgs = db.execute("""
        SELECT * FROM messages
        WHERE (sender=? AND receiver=?)
        OR (sender=? AND receiver=?)
    """, (session["user"], user, user, session["user"])).fetchall()

    return render_template("chat.html", msgs=msgs, peer=user)

if __name__ == "__main__":
    app.run(debug=True)