# app.py
from flask import Flask, render_template_string, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3, os, traceback
from datetime import timedelta

app = Flask(__name__)
app.secret_key = "supersecret-apt-key"
DB = "apt.db"

# Keep sessions persistent (so users stay logged in)
app.permanent_session_lifetime = timedelta(days=30)
@app.before_request
def make_session_permanent():
    session.permanent = True

# ---------------- DB helpers and migration ----------------
def connect_db():
    return sqlite3.connect(DB, check_same_thread=False)

def query_db(query, args=(), one=False):
    with connect_db() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(query, args)
        rv = cur.fetchall()
        conn.commit()
        return (rv[0] if rv else None) if one else rv

def init_db():
    """Create tables if missing (compatible with original schema)."""
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    # original tables plus provision for email and loom (non-breaking)
    c.execute("""CREATE TABLE IF NOT EXISTS users (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 username TEXT UNIQUE NOT NULL,
                 email TEXT UNIQUE,
                 password TEXT NOT NULL,
                 bio TEXT DEFAULT '',
                 loom TEXT DEFAULT 'none'
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS posts (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user TEXT NOT NULL,
                 caption TEXT,
                 image TEXT,
                 likes INTEGER DEFAULT 0
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS likes (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 post_id INTEGER,
                 user TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS comments (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 post_id INTEGER,
                 user TEXT,
                 text TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS reels (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user TEXT,
                 video TEXT
                 )""")
    c.execute("""CREATE TABLE IF NOT EXISTS messages (
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 sender TEXT NOT NULL,
                 receiver TEXT,
                 text TEXT NOT NULL,
                 timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                 )""")
    conn.commit()
    conn.close()

# ensure old DB gets new columns if needed (safe migration)
def ensure_columns():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    try:
        c.execute("PRAGMA table_info(users)")
        cols = [r[1] for r in c.fetchall()]
        if 'email' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN email TEXT")
        if 'bio' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN bio TEXT DEFAULT ''")
        if 'loom' not in cols:
            c.execute("ALTER TABLE users ADD COLUMN loom TEXT DEFAULT 'none'")
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

init_db()
ensure_columns()

# ---------------- Seed sample data ----------------
def seed_data():
    if not query_db("SELECT * FROM users LIMIT 1"):
        query_db("INSERT INTO users(username,email,password,loom,bio) VALUES(?,?,?,?,?)",
                 ["Alice","alice@example.com", generate_password_hash("password"), "study", "Alice — student"])
        query_db("INSERT INTO users(username,email,password,loom,bio) VALUES(?,?,?,?,?)",
                 ["Bob","bob@example.com", generate_password_hash("password"), "gym", "Bob — gym & code"])
    if not query_db("SELECT * FROM posts LIMIT 1"):
        query_db("INSERT INTO posts(user,caption,image) VALUES(?,?,?)",
                 ["Alice","Welcome to Apt — first post!","https://picsum.photos/720/480?random=1"])
        query_db("INSERT INTO posts(user,caption,image) VALUES(?,?,?)",
                 ["Bob","Evening vibes","https://picsum.photos/720/480?random=2"])
    if not query_db("SELECT * FROM reels LIMIT 1"):
        query_db("INSERT INTO reels(user,video) VALUES(?,?)",
                 ["Alice","https://www.w3schools.com/html/mov_bbb.mp4"])
        query_db("INSERT INTO reels(user,video) VALUES(?,?)",
                 ["Bob","https://www.w3schools.com/html/movie.mp4"])

seed_data()

# ---------------- Context processor ----------------
@app.context_processor
def inject_user_and_theme():
    user = session.get("user")
    loom = session.get("loom", "none")
    # load loom from DB if user logged in but session missing loom
    if user and session.get("loom") is None:
        row = query_db("SELECT loom FROM users WHERE username=?", [user], one=True)
        if row:
            loom = row["loom"] or "none"
            session["loom"] = loom
    return dict(current_user=user, current_loom=loom)

# ---------------- Theme & UI (Instagram-like, green/dark) ----------------
BASE_CSS = """
<style>
/* Fonts: using system sans for portability */
:root{
  --bg:#000000;
  --surface:#07110a;
  --card:#0b0f0b;
  --muted:#9fbf9e;
  --accent:#1f7a3f; /* deep emerald */
  --accent-2:#2ea86e;
  --text:#e7f6ed;
  --shadow: 0 8px 30px rgba(0,0,0,0.7);
}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Inter,Arial,sans-serif;background:var(--bg);color:var(--text);-webkit-font-smoothing:antialiased}
.topbar{position:fixed;top:0;left:0;right:0;height:64px;background:linear-gradient(180deg, rgba(0,0,0,0.5), rgba(0,0,0,0.2));display:flex;align-items:center;justify-content:center;z-index:60}
.topbar .nav{display:flex;gap:14px;align-items:center}
.nav-btn{padding:8px 12px;border-radius:10px;background:transparent;border:1px solid rgba(255,255,255,0.03);color:var(--muted);font-weight:600;cursor:pointer}
.container{max-width:980px;margin:86px auto 110px;padding:12px}
.story-row{display:flex;gap:12px;overflow-x:auto;padding:8px;margin-bottom:12px}
.story{min-width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg, rgba(31,122,63,0.12), rgba(46,168,110,0.06));display:flex;align-items:center;justify-content:center;border:2px solid rgba(255,255,255,0.03)}
.card{background:var(--card);border-radius:14px;padding:16px;margin:12px 0;box-shadow:var(--shadow);border:1px solid rgba(255,255,255,0.02)}
.feed-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.post-img, .reel-video{width:100%;border-radius:12px;display:block}
.post-header{display:flex;align-items:center;gap:12px;margin-bottom:8px}
.avatar{width:44px;height:44px;border-radius:50%;background:linear-gradient(180deg,var(--accent),var(--accent-2));display:flex;align-items:center;justify-content:center;color:#022;font-weight:700}
.caption{margin:10px 0;color:var(--muted)}
.actions{display:flex;gap:10px;align-items:center}
.button{background:transparent;border:1px solid rgba(255,255,255,0.04);padding:8px 12px;border-radius:10px;color:var(--text);cursor:pointer}
.like-btn{background:linear-gradient(90deg,var(--accent),var(--accent-2));border:none;color:#042;padding:8px 12px;border-radius:10px;cursor:pointer}
.input, textarea, select{width:100%;padding:10px;border-radius:10px;border:1px solid rgba(255,255,255,0.04);background:transparent;color:var(--text)}
.bottom-nav{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);background:linear-gradient(180deg, rgba(0,0,0,0.6), rgba(0,0,0,0.4));padding:10px 18px;border-radius:999px;display:flex;gap:18px;z-index:70;box-shadow:0 10px 30px rgba(0,0,0,0.6)}
.bottom-nav a{color:var(--muted);font-size:22px;text-decoration:none}
.small{font-size:13px;color:var(--muted)}
.badge{background:var(--accent);color:#031006;padding:4px 8px;border-radius:999px;font-weight:700}
.form-row{display:flex;gap:8px}
@media (max-width:720px){
  .container{margin-top:74px;padding:10px}
  .topbar{height:56px}
}
</style>
"""

NAVBAR = """
<div class="topbar">
  <div class="nav">
    <a class="nav-btn" href="{{ url_for('home') }}">Apt</a>
    <a class="nav-btn" href="{{ url_for('home') }}">Feed</a>
    <a class="nav-btn" href="{{ url_for('show_reels') }}">Reels</a>
    <a class="nav-btn" href="{{ url_for('upload') }}">Upload</a>
    <a class="nav-btn" href="{{ url_for('chat') }}">Chat</a>
    {% if current_user %}
      <a class="nav-btn" href="{{ url_for('profile', username=current_user) }}">Profile</a>
    {% else %}
      <a class="nav-btn" href="{{ url_for('login') }}">Login</a>
    {% endif %}
  </div>
</div>
"""

BOTTOM_NAV = """
<div style="height:120px"></div>
<div class="bottom-nav">
  <a href="{{ url_for('home') }}">🏠</a>
  <a href="{{ url_for('show_reels') }}">🎬</a>
  <a href="{{ url_for('upload') }}">➕</a>
  <a href="{{ url_for('chat') }}">💬</a>
  <a href="{{ url_for('users') }}">👥</a>
</div>
"""

# ---------------- Templates (fresh, inline, Jinja-friendly) ----------------

LOGIN_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <div class="card" style="max-width:560px;margin:0 auto">
    <h2 style="margin-top:0">🔐 Welcome back to Apt</h2>
    {% with messages = get_flashed_messages() %}{% for m in messages %}<p class="small" style="color:#ff8a8a">{{ m }}</p>{% endfor %}{% endwith %}
    <form method="POST">
      <label class="small">Username or Email</label>
      <input class="input" name="login_id" placeholder="username or email" required>
      <label class="small">Password</label>
      <input class="input" name="password" type="password" placeholder="Password" required>
      <div style="margin-top:12px;display:flex;gap:8px;align-items:center">
        <button class="button" type="submit">Login</button>
        <a href="{{ url_for('signup') }}" class="small" style="margin-left:auto">Create account</a>
      </div>
    </form>
  </div>
</div>
""" + BOTTOM_NAV

SIGNUP_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <div class="card" style="max-width:640px;margin:0 auto">
    <h2 style="margin-top:0">🆕 Create your Apt account</h2>
    {% with messages = get_flashed_messages() %}{% for m in messages %}<p class="small" style="color:#ff8a8a">{{ m }}</p>{% endfor %}{% endwith %}
    <form method="POST">
      <label class="small">Username</label>
      <input class="input" name="username" placeholder="Choose a username" required>
      <label class="small">Email</label>
      <input class="input" name="email" type="email" placeholder="you@example.com" required>
      <div class="form-row">
        <div style="flex:1">
          <label class="small">Password</label>
          <input class="input" name="password" type="password" placeholder="Password" required>
        </div>
        <div style="flex:1">
          <label class="small">Re-type Password</label>
          <input class="input" name="confirm" type="password" placeholder="Re-type password" required>
        </div>
      </div>
      <div style="margin-top:12px">
        <button class="button" type="submit">Sign up</button>
      </div>
    </form>
  </div>
</div>
""" + BOTTOM_NAV

FEED_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  {% with messages = get_flashed_messages() %}{% for m in messages %}<p class="small" style="color:#ff8a8a">{{ m }}</p>{% endfor %}{% endwith %}
  <div class="story-row">
    <!-- simple stories placeholder -->
    {% for u in story_users %}
      <div class="story"><span class="small">{{ u }}</span></div>
    {% endfor %}
  </div>

  <div class="feed-row">
    {% for post in posts %}
      <div class="card">
        <div class="post-header">
          <div class="avatar">{{ post.user[0]|upper }}</div>
          <div>
            <div style="font-weight:700">{{ post.user }}</div>
            <div class="small">Apt user</div>
          </div>
        </div>
        <img class="post-img" src="{{ post.image }}" alt="post image">
        <div class="caption small">{{ post.caption }}</div>
        <div class="actions">
          <form method="POST" action="{{ url_for('toggle_like', post_id=post['id']) }}" style="display:inline">
            <button class="like-btn" type="submit">❤️ {{ post.likes }}</button>
          </form>
          <form method="POST" action="{{ url_for('add_comment', post_id=post['id']) }}" style="flex:1;display:flex;gap:8px">
            <input class="input" name="comment" placeholder="Add a comment...">
            <button class="button" type="submit">Post</button>
          </form>
        </div>
        {% if post.comments %}
          <div style="margin-top:8px">
            {% for c in post.comments %}
              <div class="small"><b>{{ c['user'] }}</b> {{ c['text'] }}</div>
            {% endfor %}
          </div>
        {% endif %}
      </div>
    {% endfor %}
  </div>
</div>
""" + BOTTOM_NAV

UPLOAD_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <div class="card" style="max-width:720px;margin:0 auto">
    <h3 style="margin-top:0">➕ New Post</h3>
    {% with messages = get_flashed_messages() %}{% for m in messages %}<p class="small" style="color:#ff8a8a">{{ m }}</p>{% endfor %}{% endwith %}
    <form method="POST">
      <label class="small">Media URL (image)</label>
      <input class="input" name="image" placeholder="https://...">
      <label class="small">Caption</label>
      <textarea class="input" name="caption" rows="3"></textarea>
      <div style="margin-top:12px">
        <button class="button" type="submit">Upload</button>
      </div>
    </form>
  </div>
</div>
""" + BOTTOM_NAV

REELS_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <h2 style="margin-top:0">🎬 Reels</h2>
  <div class="feed-row">
    {% for r in reels %}
      <div class="card">
        <div style="font-weight:700">{{ r.user }}</div>
        <video class="reel-video" controls autoplay muted loop src="{{ r.video }}"></video>
      </div>
    {% endfor %}
  </div>
</div>
""" + BOTTOM_NAV

PROFILE_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <div style="max-width:720px;margin:0 auto">
    <div class="card">
      <div style="display:flex;align-items:center;gap:16px">
        <div class="avatar">{{ user_row['username'][0]|upper }}</div>
        <div>
          <h2 style="margin:0">{{ user_row['username'] }}</h2>
          <div class="small">Email: {{ user_row.get('email','(none)') }}</div>
        </div>
      </div>
      {% if can_edit %}
        <div style="margin-top:12px">
          <form method="POST">
            <label class="small">Bio</label>
            <textarea class="input" name="bio" rows="2">{{ user_row.get('bio','') }}</textarea>
            <label class="small">Loom (theme)</label>
            <select class="input" name="loom">
              <option value="none" {% if user_row.get('loom','none')=='none' %}selected{% endif %}>Default</option>
              <option value="study" {% if user_row.get('loom','none')=='study' %}selected{% endif %}>Study</option>
              <option value="gym" {% if user_row.get('loom','none')=='gym' %}selected{% endif %}>Gym</option>
              <option value="chill" {% if user_row.get('loom','none')=='chill' %}selected{% endif %}>Chill</option>
              <option value="creative" {% if user_row.get('loom','none')=='creative' %}selected{% endif %}>Creative</option>
              <option value="focus" {% if user_row.get('loom','none')=='focus' %}selected{% endif %}>Focus</option>
            </select>
            <div style="margin-top:8px">
              <button class="button" type="submit">Save profile</button>
            </div>
          </form>
        </div>
      {% else %}
        <div style="margin-top:12px" class="small">{{ user_row.get('bio','') }}</div>
      {% endif %}
    </div>

    <h3>Posts</h3>
    {% for p in posts %}
      <div class="card">
        <img src="{{ p['image'] }}" style="width:100%;border-radius:8px">
        <div class="small">{{ p['caption'] }}</div>
      </div>
    {% endfor %}
  </div>
</div>
""" + BOTTOM_NAV

CHAT_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <div style="max-width:720px;margin:0 auto">
    <div class="card">
      <h3 style="margin-top:0">💬 Public Chat</h3>
      <div style="max-height:360px;overflow-y:auto;border-radius:8px;padding:8px;background:rgba(255,255,255,0.01)">
        {% for m in msgs %}
          <div style="margin-bottom:6px"><b>{{ m['sender'] }}</b>: {{ m['text'] }}</div>
        {% endfor %}
      </div>
      <form method="POST" style="margin-top:8px;display:flex;gap:8px">
        <input class="input" name="message" placeholder="Say something...">
        <button class="button" type="submit">Send</button>
      </form>
    </div>
  </div>
</div>
""" + BOTTOM_NAV

USERS_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <div class="card" style="max-width:720px;margin:0 auto">
    <h3 style="margin-top:0">👥 Users</h3>
    {% for u in users %}
      <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid rgba(255,255,255,0.02)">
        <div><b>{{ u['username'] }}</b> <div class="small">Loom: {{ u.get('loom','none') }}</div></div>
        <div style="display:flex;gap:8px">
          <a class="button" href="{{ url_for('private_chat', username=u['username']) }}">Chat</a>
          <a class="button" href="{{ url_for('call', peer=u['username']) }}">Call</a>
          <a class="button" href="{{ url_for('profile', username=u['username']) }}">Profile</a>
        </div>
      </div>
    {% endfor %}
  </div>
</div>
""" + BOTTOM_NAV

CALL_TMPL = BASE_CSS + NAVBAR + """
<div class="container">
  <div class="card" style="max-width:720px;margin:0 auto">
    <h3 style="margin-top:0">📹 Calling {{ peer }}</h3>
    <p class="small">This is a prototype/preview. Full WebRTC call requires signaling (Socket.IO or similar).</p>
    <video id="localVideo" autoplay muted style="width:300px;border-radius:8px"></video>
    <script>
      (async ()=> {
        try {
          const s = await navigator.mediaDevices.getUserMedia({video:true,audio:true});
          document.getElementById('localVideo').srcObject = s;
        } catch(e){ console.log(e) }
      })();
    </script>
  </div>
</div>
""" + BOTTOM_NAV

# ---------------- Routes (logic preserved, improved safety) ----------------

@app.route("/signup", methods=["GET","POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username","").strip()
        email = request.form.get("email","").strip()
        password = request.form.get("password","")
        confirm = request.form.get("confirm","")
        # validation
        if not username or not email or not password:
            flash("Please fill all fields")
            return redirect(url_for("signup"))
        if password != confirm:
            flash("Passwords do not match")
            return redirect(url_for("signup"))
        # check existing username or email
        if query_db("SELECT * FROM users WHERE username=? OR email=?", [username, email], one=True):
            flash("Username or email already exists")
            return redirect(url_for("signup"))
        hashed = generate_password_hash(password)
        query_db("INSERT INTO users(username,email,password,loom) VALUES(?,?,?,?)", [username, email, hashed, "none"])
        session["user"] = username
        session["loom"] = "none"
        flash("Account created — welcome to Apt!")
        return redirect(url_for("home"))
    return render_template_string(SIGNUP_TMPL)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        login_id = request.form.get("login_id","").strip()
        password = request.form.get("password","")
        # allow login via username OR email
        row = query_db("SELECT * FROM users WHERE username=? OR email=?", [login_id, login_id], one=True)
        if not row or not check_password_hash(row["password"], password):
            flash("Invalid username/email or password")
            return redirect(url_for("login"))
        session["user"] = row["username"]
        session["loom"] = row["loom"] or "none"
        flash("Logged in")
        return redirect(url_for("home"))
    return render_template_string(LOGIN_TMPL)

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out")
    return redirect(url_for("login"))

@app.route("/")
@app.route("/home")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    try:
        raw_posts = query_db("SELECT * FROM posts ORDER BY id DESC")
        posts = []
        for r in raw_posts:
            p = dict(r)
            raw_comments = query_db("SELECT * FROM comments WHERE post_id=? ORDER BY id ASC", [p['id']])
            p['comments'] = [dict(c) for c in raw_comments]
            posts.append(p)
        # story users: get up to 8 usernames for story row
        story_rows = [u['username'] for u in query_db("SELECT username FROM users LIMIT 8")]
        return render_template_string(FEED_TMPL, posts=posts, story_users=story_rows)
    except Exception:
        traceback.print_exc()
        flash("An error occurred rendering feed")
        return redirect(url_for("login"))

@app.route("/toggle_like/<int:post_id>", methods=["POST"])
def toggle_like(post_id):
    if "user" not in session:
        return redirect(url_for("login"))
    user = session.get("user")
    try:
        liked = query_db("SELECT * FROM likes WHERE post_id=? AND user=?", [post_id, user], one=True)
        if liked:
            # unlike
            query_db("DELETE FROM likes WHERE id=?", [liked["id"]])
            # ensure not negative
            query_db("UPDATE posts SET likes = CASE WHEN likes>0 THEN likes-1 ELSE 0 END WHERE id=?", [post_id])
        else:
            query_db("INSERT INTO likes(post_id,user) VALUES(?,?)", [post_id, user])
            query_db("UPDATE posts SET likes = likes+1 WHERE id=?", [post_id])
    except Exception:
        traceback.print_exc()
        flash("Could not update like")
    return redirect(request.referrer or url_for("home"))

@app.route("/add_comment/<int:post_id>", methods=["POST"])
def add_comment(post_id):
    if "user" not in session:
        return redirect(url_for("login"))
    text = request.form.get("comment","").strip()
    if text:
        query_db("INSERT INTO comments(post_id,user,text) VALUES(?,?,?)", [post_id, session.get("user"), text])
    return redirect(request.referrer or url_for("home"))

@app.route("/upload", methods=["GET","POST"])
def upload():
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        image = request.form.get("image","").strip()
        caption = request.form.get("caption","").strip()
        if not image:
            flash("Media URL required")
            return redirect(url_for("upload"))
        query_db("INSERT INTO posts(user,caption,image) VALUES(?,?,?)", [session.get("user"), caption, image])
        flash("Post uploaded")
        return redirect(url_for("home"))
    return render_template_string(UPLOAD_TMPL)

@app.route("/show_reels")
@app.route("/reels")
def show_reels():
    if "user" not in session:
        return redirect(url_for("login"))
    raw_reels = query_db("SELECT * FROM reels ORDER BY id DESC")
    reels = [dict(r) for r in raw_reels]
    return render_template_string(REELS_TMPL, reels=reels)

@app.route("/profile/<username>", methods=["GET","POST"])
def profile(username):
    if "user" not in session:
        return redirect(url_for("login"))
    row = query_db("SELECT * FROM users WHERE username=?", [username], one=True)
    if not row:
        flash("User not found")
        return redirect(url_for("users"))
    user_row = dict(row)
    can_edit = session.get("user") == username
    if request.method == "POST" and can_edit:
        bio = request.form.get("bio","").strip()
        loom = request.form.get("loom","none")
        if loom not in ["none","study","gym","chill","creative","focus"]:
            loom = "none"
        query_db("UPDATE users SET bio=?, loom=? WHERE username=?", [bio, loom, username])
        session["loom"] = loom
        flash("Profile updated")
        return redirect(url_for("profile", username=username))
    raw_posts = query_db("SELECT * FROM posts WHERE user=? ORDER BY id DESC", [username])
    posts = [dict(p) for p in raw_posts]
    return render_template_string(PROFILE_TMPL, user_row=user_row, posts=posts, can_edit=can_edit)

@app.route("/set_loom", methods=["POST"])
def set_loom():
    if "user" not in session:
        return redirect(url_for("login"))
    new = request.form.get("loom","none")
    if new not in ["none","study","gym","chill","creative","focus"]:
        new = "none"
    query_db("UPDATE users SET loom=? WHERE username=?", [new, session.get("user")])
    session["loom"] = new
    flash("Loom updated")
    return redirect(request.referrer or url_for("profile", username=session.get("user")))

# ---------------- Chat ----------------
@app.route("/chat", methods=["GET","POST"])
def chat():
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        text = request.form.get("message","").strip()
        if text:
            query_db("INSERT INTO messages(sender,receiver,text) VALUES(?,?,?)", [session.get("user"), None, text])
            return redirect(url_for("chat"))
    raw_msgs = query_db("SELECT * FROM messages WHERE receiver IS NULL ORDER BY id ASC")
    msgs = [dict(m) for m in raw_msgs]
    return render_template_string(CHAT_TMPL, msgs=msgs)

@app.route("/users")
def users():
    if "user" not in session:
        return redirect(url_for("login"))
    raw_users = query_db("SELECT username,loom FROM users WHERE username!=?", [session.get("user")])
    users_list = [dict(r) for r in raw_users]
    return render_template_string(USERS_TMPL, users=users_list)

@app.route("/chat/<username>", methods=["GET","POST"])
def private_chat(username):
    if "user" not in session:
        return redirect(url_for("login"))
    if request.method == "POST":
        text = request.form.get("message","").strip()
        if text:
            query_db("INSERT INTO messages(sender,receiver,text) VALUES(?,?,?)", [session.get("user"), username, text])
            return redirect(url_for("private_chat", username=username))
    raw_msgs = query_db("SELECT * FROM messages WHERE (sender=? AND receiver=?) OR (sender=? AND receiver=?) ORDER BY id ASC",
                        [session.get("user"), username, username, session.get("user")])
    msgs = [dict(m) for m in raw_msgs]
    return render_template_string(CHAT_TMPL, msgs=msgs)

# ---------------- Video Call (preview) ----------------
@app.route("/call/<peer>")
def call(peer):
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template_string(CALL_TMPL, peer=peer)

@app.route("/signal/<peer>", methods=["POST"])
def signal(peer):
    data = request.get_json(force=True)
    return jsonify({"sdp": data.get("sdp")})

# ---------------- Error handling helper (prints traceback) ----------------
@app.errorhandler(Exception)
def handle_exception(e):
    traceback.print_exc()
    return f"Server error: {type(e).__name__}: {str(e)} (see server console)", 500

# ---------------- Run ----------------
if __name__ == "__main__":
    init_db()
    ensure_columns()
    seed_data()
    # run on all interfaces so accessible from other devices / hosting
    app.run(host="0.0.0.0", port=5000, debug=True)