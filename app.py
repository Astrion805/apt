from flask import Flask, render_template, request, redirect, session
import sqlite3, datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "apt-secret"
DB = "apt.db"

def db():
    return sqlite3.connect(DB)

def init_db():
    with db() as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password TEXT,
            status TEXT,
            last_seen TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS posts(
            id INTEGER PRIMARY KEY,
            user TEXT,
            content TEXT,
            time TEXT
        )""")
        conn.commit()

init_db()

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        c = db().cursor()
        c.execute("SELECT * FROM users WHERE username=?", (u,))
        user = c.fetchone()
        if user and check_password_hash(user[2], p):
            session["user"] = u
            c.execute("UPDATE users SET status='online' WHERE username=?", (u,))
            db().commit()
            return redirect("/feed")
    return render_template("login.html")

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method == "POST":
        u = request.form["username"]
        p = generate_password_hash(request.form["password"])
        with db() as conn:
            conn.execute("INSERT INTO users(username,password,status) VALUES(?,?,?)",
                         (u,p,"offline"))
        return redirect("/")
    return render_template("register.html")

@app.route("/feed", methods=["GET","POST"])
def feed():
    if "user" not in session:
        return redirect("/")
    if request.method == "POST":
        with db() as conn:
            conn.execute("INSERT INTO posts(user,content,time) VALUES(?,?,?)",
                         (session["user"], request.form["post"],
                          datetime.datetime.now().strftime("%H:%M")))
    posts = db().cursor().execute("SELECT * FROM posts ORDER BY id DESC").fetchall()
    users = db().cursor().execute("SELECT username,status,last_seen FROM users").fetchall()
    return render_template("feed.html", posts=posts, users=users)

@app.route("/logout")
def logout():
    if "user" in session:
        with db() as conn:
            conn.execute("UPDATE users SET status='offline', last_seen=? WHERE username=?",
                         (datetime.datetime.now().strftime("%H:%M"), session["user"]))
    session.clear()
    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)