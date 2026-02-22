"""
Nova — P2P anonymous chat with full legal compliance.

Security layers:
  1. Google OAuth — verified identity (Google ID + email)
  2. IP Logging — every connection logged with IP + timestamp
  3. Activity Audit Log — matches, skips, disconnects all logged
  4. Data Retention — configurable, auto-cleanup of old logs

Server handles: auth, matching, WebRTC signaling, logging.
All chat messages flow peer-to-peer via WebRTC DataChannel.
"""

import json
import os
import sqlite3
import urllib.request
from collections import deque
from datetime import datetime, timedelta
from time import monotonic

from flask import Flask, render_template, request, session, jsonify
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

# ── Config ───────────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "730"))  # 2 years default

# ── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "talktome-dev-key-change-me")

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=60,
    max_http_buffer_size=16384,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "talktome.db")


# ── Database ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # better concurrent read/write
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                google_id   TEXT    UNIQUE,
                email       TEXT    NOT NULL,
                name        TEXT,
                avatar      TEXT,
                username    TEXT    UNIQUE,
                password    TEXT,
                auth_method TEXT    NOT NULL DEFAULT 'google',
                created     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER,
                action          TEXT NOT NULL,
                partner_user_id INTEGER,
                ip              TEXT,
                user_agent      TEXT,
                details         TEXT,
                timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (partner_user_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_logs_user    ON logs(user_id);
            CREATE INDEX IF NOT EXISTS idx_logs_time    ON logs(timestamp);
            CREATE INDEX IF NOT EXISTS idx_logs_ip      ON logs(ip);
            CREATE INDEX IF NOT EXISTS idx_users_google ON users(google_id);
        """)
        db.commit()


def cleanup_old_logs():
    """Delete logs older than RETENTION_DAYS."""
    cutoff = (datetime.utcnow() - timedelta(days=RETENTION_DAYS)).isoformat()
    with get_db() as db:
        cur = db.execute("DELETE FROM logs WHERE timestamp < ?", (cutoff,))
        db.commit()
        if cur.rowcount > 0:
            print(f"  Cleaned up {cur.rowcount} logs older than {RETENTION_DAYS} days")


def log_action(user_id, action, partner_user_id=None, ip=None, user_agent=None, details=None):
    """Write an entry to the audit log."""
    try:
        with get_db() as db:
            db.execute(
                "INSERT INTO logs (user_id, action, partner_user_id, ip, user_agent, details) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, action, partner_user_id, ip, user_agent, details),
            )
            db.commit()
    except Exception:
        pass  # logging should never crash the app


init_db()
cleanup_old_logs()


# ── Helpers ──────────────────────────────────────────────────────────────────
def get_client_ip():
    """Get the real client IP, handling proxies."""
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def get_user_agent():
    return request.headers.get("User-Agent", "")[:500]


def verify_google_token(token):
    """Verify a Google ID token via Google's tokeninfo endpoint. No extra deps."""
    try:
        url = f"https://oauth2.googleapis.com/tokeninfo?id_token={token}"
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read().decode())
        # Verify the token was issued for our app
        if data.get("aud") != GOOGLE_CLIENT_ID:
            return None
        return data
    except Exception:
        return None


# ── Chat State ───────────────────────────────────────────────────────────────
partners: dict[str, str] = {}
waiting_queue: deque[str] = deque()
waiting_set: set[str] = set()
online: set[str] = set()
sid_to_uid: dict[str, int] = {}   # sid -> user DB id

_last_broadcast: float = 0.0
_BROADCAST_INTERVAL: float = 1.0


def _broadcast_online():
    global _last_broadcast
    now = monotonic()
    if now - _last_broadcast >= _BROADCAST_INTERVAL:
        _last_broadcast = now
        socketio.emit("oc", len(online))


def _remove_from_queue(sid: str):
    waiting_set.discard(sid)
    try:
        waiting_queue.remove(sid)
    except ValueError:
        pass


def _leave_partner(sid: str):
    partner = partners.pop(sid, None)
    if partner:
        partners.pop(partner, None)
        # Log the disconnection for both users
        uid = sid_to_uid.get(sid)
        p_uid = sid_to_uid.get(partner)
        if uid:
            log_action(uid, "chat_end", partner_user_id=p_uid, ip=get_client_ip())
        emit("pd", to=partner)


def _try_match(sid: str):
    while waiting_queue:
        candidate = waiting_queue.popleft()
        waiting_set.discard(candidate)
        if candidate in online and candidate != sid and candidate not in partners:
            partners[sid] = candidate
            partners[candidate] = sid
            # Log the match for both users
            uid = sid_to_uid.get(sid)
            p_uid = sid_to_uid.get(candidate)
            if uid:
                log_action(uid, "match", partner_user_id=p_uid, ip=get_client_ip())
            if p_uid:
                log_action(p_uid, "match", partner_user_id=uid, ip=get_client_ip())
            emit("m", {"init": True}, to=sid)
            emit("m", {"init": False}, to=candidate)
            return True
    return False


# ── Auth Routes ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", google_client_id=GOOGLE_CLIENT_ID, retention_days=RETENTION_DAYS)


@app.route("/api/auth/google", methods=["POST"])
def auth_google():
    """Verify Google ID token and create/login user."""
    if not GOOGLE_CLIENT_ID:
        return jsonify({"ok": False, "err": "Google OAuth not configured."}), 500

    data = request.get_json(silent=True) or {}
    token = data.get("credential", "")
    if not token:
        return jsonify({"ok": False, "err": "No credential provided."}), 400

    info = verify_google_token(token)
    if not info:
        return jsonify({"ok": False, "err": "Invalid Google token."}), 401

    google_id = info.get("sub")
    email = info.get("email", "")
    name = info.get("name", "")
    avatar = info.get("picture", "")

    if not google_id or not email:
        return jsonify({"ok": False, "err": "Could not get Google account info."}), 400

    db = get_db()
    row = db.execute("SELECT * FROM users WHERE google_id = ?", (google_id,)).fetchone()

    if row:
        # Existing user — update last login
        db.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP, name = ?, avatar = ?, email = ? WHERE id = ?",
            (name, avatar, email, row["id"]),
        )
        db.commit()
        uid = row["id"]
    else:
        # New user
        cur = db.execute(
            "INSERT INTO users (google_id, email, name, avatar, auth_method) VALUES (?, ?, ?, ?, 'google')",
            (google_id, email, name, avatar),
        )
        db.commit()
        uid = cur.lastrowid

    db.close()

    session["user_id"] = uid
    session["user_name"] = name or email.split("@")[0]
    session["user_email"] = email
    session["user_avatar"] = avatar

    # Log the login
    log_action(uid, "login", ip=get_client_ip(), user_agent=get_user_agent(),
               details=f"google:{google_id}")

    return jsonify({
        "ok": True,
        "user": {"name": session["user_name"], "email": email, "avatar": avatar},
    })


@app.route("/api/auth/email", methods=["POST"])
def auth_email():
    """Fallback email/password signup+login (if Google OAuth not set up)."""
    data = request.get_json(silent=True) or {}
    action = data.get("action", "login")  # "login" or "signup"
    email = data.get("email", "").strip().lower()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"ok": False, "err": "Email and password required."}), 400

    if action == "signup":
        if len(email) < 5 or "@" not in email:
            return jsonify({"ok": False, "err": "Valid email required."}), 400
        if len(password) < 6:
            return jsonify({"ok": False, "err": "Password must be 6+ characters."}), 400
        try:
            with get_db() as db:
                cur = db.execute(
                    "INSERT INTO users (email, password, auth_method, username) VALUES (?, ?, 'email', ?)",
                    (email, generate_password_hash(password), email),
                )
                db.commit()
                uid = cur.lastrowid
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "err": "Email already registered."}), 409

        session["user_id"] = uid
        session["user_name"] = email.split("@")[0]
        session["user_email"] = email
        session["user_avatar"] = ""

        log_action(uid, "signup", ip=get_client_ip(), user_agent=get_user_agent())
        return jsonify({"ok": True, "user": {"name": session["user_name"], "email": email, "avatar": ""}})

    else:  # login
        db = get_db()
        row = db.execute("SELECT * FROM users WHERE email = ? AND auth_method = 'email'", (email,)).fetchone()
        db.close()
        if not row or not row["password"] or not check_password_hash(row["password"], password):
            return jsonify({"ok": False, "err": "Invalid email or password."}), 401

        session["user_id"] = row["id"]
        session["user_name"] = row["name"] or email.split("@")[0]
        session["user_email"] = email
        session["user_avatar"] = row["avatar"] or ""

        log_action(row["id"], "login", ip=get_client_ip(), user_agent=get_user_agent(),
                   details="email")
        return jsonify({
            "ok": True,
            "user": {"name": session["user_name"], "email": email, "avatar": session["user_avatar"]},
        })


@app.route("/api/logout", methods=["POST"])
def logout():
    uid = session.get("user_id")
    if uid:
        log_action(uid, "logout", ip=get_client_ip())
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    uid = session.get("user_id")
    if uid:
        return jsonify({
            "ok": True,
            "user": {
                "name": session.get("user_name", ""),
                "email": session.get("user_email", ""),
                "avatar": session.get("user_avatar", ""),
            },
        })
    return jsonify({"ok": False}), 401


# ── Admin Dashboard ──────────────────────────────────────────────────────────
ADMIN_EMAILS = set(
    e.strip().lower()
    for e in os.environ.get("ADMIN_EMAILS", "rahul@simpleintelligence.com").split(",")
    if e.strip()
)


def is_admin():
    return session.get("user_email", "").lower() in ADMIN_EMAILS


@app.route("/admin")
def admin_page():
    if not is_admin():
        return "Unauthorized. Please log in as an admin account first.", 403
    return render_template("admin.html")


@app.route("/api/admin/stats")
def admin_stats():
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    db = get_db()

    total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    google_users = db.execute("SELECT COUNT(*) FROM users WHERE auth_method='google'").fetchone()[0]
    email_users = db.execute("SELECT COUNT(*) FROM users WHERE auth_method='email'").fetchone()[0]

    # Signups in last 24h
    day_ago = (datetime.utcnow() - timedelta(hours=24)).isoformat()
    signups_24h = db.execute("SELECT COUNT(*) FROM users WHERE created > ?", (day_ago,)).fetchone()[0]

    # Recent activity (last 50 log entries)
    recent_logs = db.execute("""
        SELECT l.timestamp, l.action, l.ip, l.details,
               u.email AS user_email, u.auth_method
        FROM logs l
        LEFT JOIN users u ON u.id = l.user_id
        ORDER BY l.timestamp DESC LIMIT 50
    """).fetchall()

    logs_list = [
        {
            "time": row["timestamp"],
            "action": row["action"],
            "ip": row["ip"],
            "email": row["user_email"] or "—",
            "auth": row["auth_method"] or "—",
            "details": row["details"] or "",
        }
        for row in recent_logs
    ]

    # Unique IPs in last 24h
    unique_ips_24h = db.execute(
        "SELECT COUNT(DISTINCT ip) FROM logs WHERE timestamp > ?", (day_ago,)
    ).fetchone()[0]

    db.close()

    return jsonify({
        "online": len(online),
        "in_queue": len(waiting_set),
        "in_chat": len(partners) // 2,
        "total_users": total_users,
        "google_users": google_users,
        "email_users": email_users,
        "signups_24h": signups_24h,
        "unique_ips_24h": unique_ips_24h,
        "recent_logs": logs_list,
    })


# ── Socket Events ────────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    uid = session.get("user_id")
    if not uid:
        return False  # reject unauthenticated
    sid = request.sid
    online.add(sid)
    sid_to_uid[sid] = uid
    log_action(uid, "connect", ip=get_client_ip(), user_agent=get_user_agent())
    _broadcast_online()


@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    uid = sid_to_uid.pop(sid, None)
    online.discard(sid)
    _remove_from_queue(sid)
    _leave_partner(sid)
    if uid:
        log_action(uid, "disconnect", ip=get_client_ip())
    _broadcast_online()


@socketio.on("q")  # join queue
def on_queue():
    sid = request.sid
    if sid in waiting_set:
        return
    _leave_partner(sid)
    uid = sid_to_uid.get(sid)
    if uid:
        log_action(uid, "queue", ip=get_client_ip())
    if not _try_match(sid):
        waiting_queue.append(sid)
        waiting_set.add(sid)
        emit("w")


@socketio.on("s")  # skip
def on_skip():
    sid = request.sid
    uid = sid_to_uid.get(sid)
    if uid:
        log_action(uid, "skip", ip=get_client_ip())
    _leave_partner(sid)
    _remove_from_queue(sid)
    on_queue()


# ── WebRTC Signaling ─────────────────────────────────────────────────────────
@socketio.on("offer")
def on_offer(data):
    partner = partners.get(request.sid)
    if partner:
        emit("offer", data, to=partner)


@socketio.on("answer")
def on_answer(data):
    partner = partners.get(request.sid)
    if partner:
        emit("answer", data, to=partner)


@socketio.on("ice")
def on_ice(data):
    partner = partners.get(request.sid)
    if partner:
        emit("ice", data, to=partner)


# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║         Nova (P2P) — running on :5000         ║")
    print("  ╚══════════════════════════════════════════════╝\n")

    if GOOGLE_CLIENT_ID:
        print(f"  ✓ Google OAuth enabled")
    else:
        print("  ⚠ GOOGLE_CLIENT_ID not set — using email/password fallback")
        print("  To enable Google OAuth:")
        print("    1. Go to https://console.cloud.google.com")
        print("    2. Create a project → APIs & Services → Credentials")
        print("    3. Create OAuth 2.0 Client ID (Web application)")
        print("    4. Add http://localhost:5000 to Authorized JavaScript Origins")
        print("    5. Run: export GOOGLE_CLIENT_ID=your-client-id-here")
        print()

    print(f"  ✓ IP logging enabled")
    print(f"  ✓ Audit log enabled")
    print(f"  ✓ Data retention: {RETENTION_DAYS} days")
    print(f"  ✓ Database: {DB_PATH}")
    print()

    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
