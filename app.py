"""
Nova — P2P video chat with strangers (Omegle-style).

Security layers:
  1. Google OAuth — verified identity (Google ID + email)
  2. IP Logging — every connection logged with IP + timestamp
  3. Activity Audit Log — matches, skips, disconnects all logged
  4. Data Retention — configurable, auto-cleanup of old logs

Server handles: auth, matching, WebRTC signaling, logging.
Video/audio flows peer-to-peer via WebRTC media streams.
"""

import json
import os
import re
import secrets
import sqlite3
import urllib.request
from collections import deque, defaultdict
from datetime import datetime, timedelta
from functools import wraps
from time import monotonic

from flask import Flask, render_template, request, session, jsonify
from flask_socketio import SocketIO, emit
from werkzeug.security import generate_password_hash, check_password_hash

# ── Config ───────────────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "730"))  # 2 years default
ADSENSE_ID = os.environ.get("ADSENSE_ID", "")  # e.g. ca-pub-1234567890123456
ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "")  # comma-separated, e.g. https://nova.example.com

# ── App Setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)

# SECRET_KEY: use env var, or auto-generate and persist a strong one
_key_file = os.path.join(os.path.dirname(__file__), ".secret_key")
def _get_secret_key():
    env_key = os.environ.get("SECRET_KEY", "")
    if env_key and env_key != "talktome-dev-key-change-me":
        return env_key
    # Auto-generate and persist so sessions survive restarts
    if os.path.exists(_key_file):
        with open(_key_file) as f:
            return f.read().strip()
    key = secrets.token_hex(32)
    try:
        with open(_key_file, "w") as f:
            f.write(key)
        os.chmod(_key_file, 0o600)  # owner-only read/write
    except OSError:
        pass
    return key

app.config["SECRET_KEY"] = _get_secret_key()

# Session cookie security
app.config["SESSION_COOKIE_HTTPONLY"] = True       # JS can't read session cookie
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"     # CSRF protection
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") != "development"  # HTTPS only in prod
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1MB max request body

# CORS: restrict to allowed origins in production
_cors_origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()] if ALLOWED_ORIGINS else "*"

socketio = SocketIO(
    app,
    cors_allowed_origins=_cors_origins,
    ping_interval=30,
    ping_timeout=120,       # 2 min timeout for slow connections
    max_http_buffer_size=16384,
)


# ── Security Headers ─────────────────────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
    # CSP: allow Google OAuth, SocketIO, AdSense, and own scripts
    csp_parts = [
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline' https://accounts.google.com https://apis.google.com https://cdnjs.cloudflare.com https://pagead2.googlesyndication.com https://www.googletagservices.com https://partner.googleadservices.com",
        "style-src 'self' 'unsafe-inline' https://accounts.google.com",
        "img-src 'self' data: https: blob:",
        "connect-src 'self' wss: ws: https://accounts.google.com https://oauth2.googleapis.com",
        "frame-src https://accounts.google.com https://googleads.g.doubleclick.net https://tpc.googlesyndication.com",
        "media-src 'self' blob:",
        "font-src 'self'",
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
    return response


# ── Rate Limiting (in-memory) ────────────────────────────────────────────────
_rate_buckets: dict[str, list] = defaultdict(list)

def rate_limit(max_requests=10, window_seconds=60):
    """Decorator: limit requests per IP within a time window."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            ip = get_client_ip()
            key = f"{f.__name__}:{ip}"
            now = monotonic()
            # Clean old entries
            _rate_buckets[key] = [t for t in _rate_buckets[key] if now - t < window_seconds]
            if len(_rate_buckets[key]) >= max_requests:
                return jsonify({"ok": False, "err": "Too many requests. Try again later."}), 429
            _rate_buckets[key].append(now)
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── SocketIO rate limiting ───────────────────────────────────────────────────
_socket_rate: dict[str, float] = {}  # sid -> last event time
_SOCKET_MIN_INTERVAL = 0.5  # min seconds between queue/skip events

def socket_rate_ok(sid: str) -> bool:
    """Returns True if the socket event is within rate limits."""
    now = monotonic()
    last = _socket_rate.get(sid, 0)
    if now - last < _SOCKET_MIN_INTERVAL:
        return False
    _socket_rate[sid] = now
    return True

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
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                google_id       TEXT    UNIQUE,
                email           TEXT    NOT NULL,
                name            TEXT,
                avatar          TEXT,
                username        TEXT    UNIQUE,
                password        TEXT,
                auth_method     TEXT    NOT NULL DEFAULT 'google',
                tos_accepted_at TIMESTAMP,
                tos_accepted_ip TEXT,
                tos_version     TEXT,
                created         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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

            CREATE TABLE IF NOT EXISTS reports (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                reporter_id     INTEGER NOT NULL,
                reported_id     INTEGER NOT NULL,
                reason          TEXT NOT NULL,
                details         TEXT,
                reporter_ip     TEXT,
                status          TEXT NOT NULL DEFAULT 'pending',
                admin_note      TEXT,
                created         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at     TIMESTAMP,
                FOREIGN KEY (reporter_id) REFERENCES users(id),
                FOREIGN KEY (reported_id) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status);
            CREATE INDEX IF NOT EXISTS idx_reports_reported ON reports(reported_id);

            CREATE TABLE IF NOT EXISTS bans (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL UNIQUE,
                reason          TEXT,
                banned_by       INTEGER,
                created         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at      TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (banned_by) REFERENCES users(id)
            );

            CREATE INDEX IF NOT EXISTS idx_bans_user ON bans(user_id);
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


TOS_VERSION = "1.1"  # bump this when TOS changes — users must re-accept

init_db()
cleanup_old_logs()

# Migrate: add columns if missing (safe for existing DBs)
try:
    with get_db() as db:
        cols = [r[1] for r in db.execute("PRAGMA table_info(users)").fetchall()]
        if "tos_accepted_at" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN tos_accepted_at TIMESTAMP")
            db.execute("ALTER TABLE users ADD COLUMN tos_accepted_ip TEXT")
            db.execute("ALTER TABLE users ADD COLUMN tos_version TEXT")
        if "nickname" not in cols:
            db.execute("ALTER TABLE users ADD COLUMN nickname TEXT")
        db.commit()
except Exception:
    pass


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


def _leave_partner(sid: str, auto_requeue=True):
    partner = partners.pop(sid, None)
    if partner:
        partners.pop(partner, None)
        # Log the disconnection for both users
        uid = sid_to_uid.get(sid)
        p_uid = sid_to_uid.get(partner)
        if uid:
            log_action(uid, "chat_end", partner_user_id=p_uid, ip=get_client_ip())
        emit("pd", to=partner)
        # Auto re-queue the remaining partner so they find someone new immediately
        if auto_requeue and partner in online and partner not in waiting_set:
            waiting_queue.append(partner)
            waiting_set.add(partner)
            emit("w", to=partner)


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
            # Send partner's nickname to each user
            sid_nick = session.get("user_nickname", "") if sid == request.sid else ""
            cand_nick = ""
            # Look up nicknames from DB for both
            try:
                _db = get_db()
                if uid:
                    _r = _db.execute("SELECT nickname FROM users WHERE id = ?", (uid,)).fetchone()
                    sid_nick = (_r["nickname"] or "") if _r else ""
                if p_uid:
                    _r = _db.execute("SELECT nickname FROM users WHERE id = ?", (p_uid,)).fetchone()
                    cand_nick = (_r["nickname"] or "") if _r else ""
                _db.close()
            except Exception:
                pass
            emit("m", {"init": True, "partner_nick": cand_nick}, to=sid)
            emit("m", {"init": False, "partner_nick": sid_nick}, to=candidate)
            return True
    return False


# ── Ban check helper ─────────────────────────────────────────────────────────
def is_banned(user_id):
    """Check if a user is currently banned."""
    try:
        db = get_db()
        row = db.execute(
            "SELECT * FROM bans WHERE user_id = ? AND (expires_at IS NULL OR expires_at > datetime('now'))",
            (user_id,),
        ).fetchone()
        db.close()
        return row is not None
    except Exception:
        return False


# ── Auth Routes ──────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", google_client_id=GOOGLE_CLIENT_ID, retention_days=RETENTION_DAYS, tos_version=TOS_VERSION, adsense_id=ADSENSE_ID)


@app.route("/tos")
def tos_page():
    return render_template("tos.html")


@app.route("/privacy")
def privacy_page():
    return render_template("privacy.html")


@app.route("/api/auth/google", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
def auth_google():
    """Verify Google ID token and create/login user."""
    if not GOOGLE_CLIENT_ID:
        return jsonify({"ok": False, "err": "Google OAuth not configured."}), 500

    data = request.get_json(silent=True) or {}
    token = data.get("credential", "")
    if not token:
        return jsonify({"ok": False, "err": "No credential provided."}), 400

    if not data.get("tos_accepted"):
        return jsonify({"ok": False, "err": "You must accept the Terms of Service."}), 400

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
        # Check if banned
        if is_banned(row["id"]):
            db.close()
            return jsonify({"ok": False, "err": "Your account has been suspended. Contact rahul@simpleintelligence.com for details."}), 403
        # Existing user — update last login + TOS acceptance
        db.execute(
            "UPDATE users SET last_login = CURRENT_TIMESTAMP, name = ?, avatar = ?, email = ?, "
            "tos_accepted_at = CURRENT_TIMESTAMP, tos_accepted_ip = ?, tos_version = ? WHERE id = ?",
            (name, avatar, email, get_client_ip(), TOS_VERSION, row["id"]),
        )
        db.commit()
        uid = row["id"]
        nickname = row["nickname"] or ""
    else:
        # New user
        cur = db.execute(
            "INSERT INTO users (google_id, email, name, avatar, auth_method, tos_accepted_at, tos_accepted_ip, tos_version) "
            "VALUES (?, ?, ?, ?, 'google', CURRENT_TIMESTAMP, ?, ?)",
            (google_id, email, name, avatar, get_client_ip(), TOS_VERSION),
        )
        db.commit()
        uid = cur.lastrowid
        nickname = ""

    db.close()

    session["user_id"] = uid
    session["user_name"] = name or email.split("@")[0]
    session["user_email"] = email
    session["user_avatar"] = avatar
    session["user_nickname"] = nickname

    # Log the login
    log_action(uid, "login", ip=get_client_ip(), user_agent=get_user_agent(),
               details=f"google:{google_id}")

    return jsonify({
        "ok": True,
        "user": {"name": session["user_name"], "email": email, "avatar": avatar, "nickname": nickname},
    })


@app.route("/api/auth/email", methods=["POST"])
@rate_limit(max_requests=5, window_seconds=60)
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
        if not data.get("tos_accepted"):
            return jsonify({"ok": False, "err": "You must accept the Terms of Service."}), 400
        try:
            with get_db() as db:
                cur = db.execute(
                    "INSERT INTO users (email, password, auth_method, username, tos_accepted_at, tos_accepted_ip, tos_version) "
                    "VALUES (?, ?, 'email', ?, CURRENT_TIMESTAMP, ?, ?)",
                    (email, generate_password_hash(password), email, get_client_ip(), TOS_VERSION),
                )
                db.commit()
                uid = cur.lastrowid
        except sqlite3.IntegrityError:
            return jsonify({"ok": False, "err": "Email already registered."}), 409

        session["user_id"] = uid
        session["user_name"] = email.split("@")[0]
        session["user_email"] = email
        session["user_avatar"] = ""

        log_action(uid, "signup", ip=get_client_ip(), user_agent=get_user_agent(),
                   details=f"tos_v{TOS_VERSION}")
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
                "nickname": session.get("user_nickname", ""),
            },
        })
    return jsonify({"ok": False}), 401


@app.route("/api/profile", methods=["POST"])
@rate_limit(max_requests=10, window_seconds=60)
def set_profile():
    """Set nickname for the current user."""
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "err": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    nickname = data.get("nickname", "").strip()

    if not nickname:
        return jsonify({"ok": False, "err": "Nickname is required"}), 400
    # Sanitize: strip HTML tags
    nickname = re.sub(r"<[^>]*>", "", nickname).strip()
    # Only allow letters, numbers, spaces, underscores, hyphens
    if not re.match(r"^[\w\s\-]+$", nickname, re.UNICODE):
        return jsonify({"ok": False, "err": "Nickname can only contain letters, numbers, spaces, underscores, and hyphens"}), 400
    if len(nickname) < 2:
        return jsonify({"ok": False, "err": "Nickname must be at least 2 characters"}), 400
    if len(nickname) > 20:
        return jsonify({"ok": False, "err": "Nickname must be 20 characters or less"}), 400

    db = get_db()
    db.execute("UPDATE users SET nickname = ? WHERE id = ?", (nickname, uid))
    db.commit()
    db.close()

    session["user_nickname"] = nickname
    return jsonify({"ok": True, "nickname": nickname})


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


@app.route("/api/admin/users")
def admin_users():
    """List all users with pagination and search."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    q = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset = (page - 1) * per_page

    db = get_db()

    if q:
        like = f"%{q}%"
        total = db.execute(
            "SELECT COUNT(*) FROM users WHERE email LIKE ? OR name LIKE ? OR nickname LIKE ? OR google_id LIKE ?",
            (like, like, like, like),
        ).fetchone()[0]
        rows = db.execute(
            "SELECT id, email, name, nickname, avatar, auth_method, created, last_login FROM users "
            "WHERE email LIKE ? OR name LIKE ? OR nickname LIKE ? OR google_id LIKE ? "
            "ORDER BY created DESC LIMIT ? OFFSET ?",
            (like, like, like, like, per_page, offset),
        ).fetchall()
    else:
        total = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        rows = db.execute(
            "SELECT id, email, name, nickname, avatar, auth_method, created, last_login FROM users "
            "ORDER BY created DESC LIMIT ? OFFSET ?",
            (per_page, offset),
        ).fetchall()

    db.close()

    users = [
        {
            "id": r["id"],
            "email": r["email"],
            "name": r["name"] or "",
            "nickname": r["nickname"] or "",
            "avatar": r["avatar"] or "",
            "auth": r["auth_method"],
            "created": r["created"],
            "last_login": r["last_login"],
        }
        for r in rows
    ]

    return jsonify({"users": users, "total": total, "page": page, "per_page": per_page})


@app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
def admin_delete_user(user_id):
    """Delete a user and their logs."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    db = get_db()
    user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user:
        db.close()
        return jsonify({"error": "User not found"}), 404

    # Don't allow deleting admin accounts
    if user["email"].lower() in ADMIN_EMAILS:
        db.close()
        return jsonify({"error": "Cannot delete admin accounts"}), 403

    # Disconnect user if online
    for sid, uid in list(sid_to_uid.items()):
        if uid == user_id:
            _leave_partner(sid, auto_requeue=False)
            _remove_from_queue(sid)
            online.discard(sid)
            sid_to_uid.pop(sid, None)
            socketio.emit("force_logout", to=sid)

    db.execute("DELETE FROM logs WHERE user_id = ?", (user_id,))
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    db.close()

    log_action(session.get("user_id"), "admin_delete_user", ip=get_client_ip(),
               details=f"deleted user {user_id} ({user['email']})")

    return jsonify({"ok": True})


# ── Report / Block ────────────────────────────────────────────────────────────
@app.route("/api/report", methods=["POST"])
@rate_limit(max_requests=5, window_seconds=300)  # 5 reports per 5 minutes
def report_user():
    """Report the current chat partner."""
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "err": "Not logged in"}), 401

    data = request.get_json(silent=True) or {}
    reason = data.get("reason", "").strip()
    details = data.get("details", "").strip()[:500]

    if not reason:
        return jsonify({"ok": False, "err": "Reason is required"}), 400

    valid_reasons = ["harassment", "inappropriate", "underage", "spam", "illegal", "other"]
    if reason not in valid_reasons:
        return jsonify({"ok": False, "err": "Invalid reason"}), 400

    # Find current partner
    reported_uid = None
    for sid, u in sid_to_uid.items():
        if u == uid:
            partner_sid = partners.get(sid)
            if partner_sid:
                reported_uid = sid_to_uid.get(partner_sid)
            break

    if not reported_uid:
        return jsonify({"ok": False, "err": "No active chat partner to report"}), 400

    if reported_uid == uid:
        return jsonify({"ok": False, "err": "Cannot report yourself"}), 400

    db = get_db()
    db.execute(
        "INSERT INTO reports (reporter_id, reported_id, reason, details, reporter_ip) VALUES (?, ?, ?, ?, ?)",
        (uid, reported_uid, reason, details, get_client_ip()),
    )
    db.commit()

    # Check auto-ban: if 3+ reports from different users, auto-ban
    report_count = db.execute(
        "SELECT COUNT(DISTINCT reporter_id) FROM reports WHERE reported_id = ? AND status = 'pending'",
        (reported_uid,),
    ).fetchone()[0]
    db.close()

    if report_count >= 3:
        try:
            ban_db = get_db()
            ban_db.execute(
                "INSERT OR IGNORE INTO bans (user_id, reason, banned_by) VALUES (?, ?, NULL)",
                (reported_uid, f"Auto-banned: {report_count} reports from different users"),
            )
            ban_db.commit()
            ban_db.close()
            # Force disconnect the banned user
            for sid, u in list(sid_to_uid.items()):
                if u == reported_uid:
                    _leave_partner(sid, auto_requeue=False)
                    _remove_from_queue(sid)
                    online.discard(sid)
                    sid_to_uid.pop(sid, None)
                    socketio.emit("force_logout", to=sid)
        except Exception:
            pass

    log_action(uid, "report", partner_user_id=reported_uid, ip=get_client_ip(),
               details=f"reason:{reason}")
    return jsonify({"ok": True, "msg": "Report submitted. Thank you for keeping Nova safe."})


# ── Admin: Reports & Bans ────────────────────────────────────────────────────
@app.route("/api/admin/reports")
def admin_reports():
    """List all reports with pagination."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    status_filter = request.args.get("status", "pending")
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset = (page - 1) * per_page

    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM reports WHERE status = ?", (status_filter,)).fetchone()[0]
    rows = db.execute("""
        SELECT r.*, 
               reporter.email AS reporter_email, reporter.nickname AS reporter_nick,
               reported.email AS reported_email, reported.nickname AS reported_nick
        FROM reports r
        LEFT JOIN users reporter ON reporter.id = r.reporter_id
        LEFT JOIN users reported ON reported.id = r.reported_id
        WHERE r.status = ?
        ORDER BY r.created DESC LIMIT ? OFFSET ?
    """, (status_filter, per_page, offset)).fetchall()
    db.close()

    reports = [
        {
            "id": r["id"],
            "reporter": r["reporter_email"] or "—",
            "reporter_nick": r["reporter_nick"] or "",
            "reported": r["reported_email"] or "—",
            "reported_nick": r["reported_nick"] or "",
            "reported_id": r["reported_id"],
            "reason": r["reason"],
            "details": r["details"] or "",
            "status": r["status"],
            "created": r["created"],
        }
        for r in rows
    ]

    return jsonify({"reports": reports, "total": total, "page": page, "per_page": per_page})


@app.route("/api/admin/reports/<int:report_id>/resolve", methods=["POST"])
def admin_resolve_report(report_id):
    """Resolve a report (dismiss or ban)."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json(silent=True) or {}
    action = data.get("action", "dismiss")  # "dismiss" or "ban"
    note = data.get("note", "").strip()[:500]

    db = get_db()
    report = db.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
    if not report:
        db.close()
        return jsonify({"error": "Report not found"}), 404

    db.execute(
        "UPDATE reports SET status = ?, admin_note = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
        (action + "ed", note, report_id),
    )

    if action == "ban":
        # Ban the reported user
        db.execute(
            "INSERT OR IGNORE INTO bans (user_id, reason, banned_by) VALUES (?, ?, ?)",
            (report["reported_id"], f"Banned by admin: {report['reason']}. {note}", session.get("user_id")),
        )
        # Force disconnect
        for sid, uid in list(sid_to_uid.items()):
            if uid == report["reported_id"]:
                _leave_partner(sid, auto_requeue=False)
                _remove_from_queue(sid)
                online.discard(sid)
                sid_to_uid.pop(sid, None)
                socketio.emit("force_logout", to=sid)

    db.commit()
    db.close()

    log_action(session.get("user_id"), f"admin_report_{action}", ip=get_client_ip(),
               details=f"report #{report_id}, user {report['reported_id']}")
    return jsonify({"ok": True})


@app.route("/api/admin/bans")
def admin_bans():
    """List all active bans."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    db = get_db()
    rows = db.execute("""
        SELECT b.*, u.email, u.nickname
        FROM bans b LEFT JOIN users u ON u.id = b.user_id
        WHERE b.expires_at IS NULL OR b.expires_at > datetime('now')
        ORDER BY b.created DESC
    """).fetchall()
    db.close()

    bans = [
        {"id": r["id"], "user_id": r["user_id"], "email": r["email"] or "—",
         "nickname": r["nickname"] or "", "reason": r["reason"] or "",
         "created": r["created"]}
        for r in rows
    ]
    return jsonify({"bans": bans})


@app.route("/api/admin/bans/<int:ban_id>/unban", methods=["POST"])
def admin_unban(ban_id):
    """Remove a ban."""
    if not is_admin():
        return jsonify({"error": "Unauthorized"}), 403

    db = get_db()
    db.execute("DELETE FROM bans WHERE id = ?", (ban_id,))
    db.commit()
    db.close()

    log_action(session.get("user_id"), "admin_unban", ip=get_client_ip(),
               details=f"ban #{ban_id}")
    return jsonify({"ok": True})


# ── GDPR: Data Export & Self-Delete ──────────────────────────────────────────
@app.route("/api/my-data")
@rate_limit(max_requests=3, window_seconds=3600)  # 3 per hour
def export_my_data():
    """GDPR: Let users download all their data."""
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "err": "Not logged in"}), 401

    db = get_db()
    user = db.execute("SELECT id, email, name, nickname, auth_method, created, last_login, tos_accepted_at, tos_version FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        db.close()
        return jsonify({"ok": False, "err": "User not found"}), 404

    logs = db.execute(
        "SELECT action, ip, user_agent, details, timestamp FROM logs WHERE user_id = ? ORDER BY timestamp DESC",
        (uid,),
    ).fetchall()

    reports_made = db.execute(
        "SELECT reason, details, created, status FROM reports WHERE reporter_id = ? ORDER BY created DESC",
        (uid,),
    ).fetchall()

    reports_against = db.execute(
        "SELECT reason, created, status FROM reports WHERE reported_id = ? ORDER BY created DESC",
        (uid,),
    ).fetchall()
    db.close()

    return jsonify({
        "ok": True,
        "data": {
            "account": {
                "email": user["email"],
                "name": user["name"],
                "nickname": user["nickname"],
                "auth_method": user["auth_method"],
                "created": user["created"],
                "last_login": user["last_login"],
                "tos_accepted_at": user["tos_accepted_at"],
                "tos_version": user["tos_version"],
            },
            "activity_log": [
                {"action": l["action"], "ip": l["ip"], "timestamp": l["timestamp"], "details": l["details"]}
                for l in logs
            ],
            "reports_filed": [
                {"reason": r["reason"], "details": r["details"], "created": r["created"], "status": r["status"]}
                for r in reports_made
            ],
            "reports_against_you": [
                {"reason": r["reason"], "created": r["created"], "status": r["status"]}
                for r in reports_against
            ],
        },
    })


@app.route("/api/delete-account", methods=["POST"])
@rate_limit(max_requests=1, window_seconds=3600)
def delete_my_account():
    """GDPR: Let users delete their own account and data."""
    uid = session.get("user_id")
    if not uid:
        return jsonify({"ok": False, "err": "Not logged in"}), 401

    email = session.get("user_email", "")

    # Don't let admins accidentally delete themselves
    if email.lower() in ADMIN_EMAILS:
        return jsonify({"ok": False, "err": "Admin accounts cannot be self-deleted. Contact another admin."}), 403

    # Disconnect if online
    for sid, u in list(sid_to_uid.items()):
        if u == uid:
            _leave_partner(sid, auto_requeue=False)
            _remove_from_queue(sid)
            online.discard(sid)
            sid_to_uid.pop(sid, None)

    db = get_db()
    # Keep audit log for legal compliance (anonymize it)
    db.execute("UPDATE logs SET user_id = NULL, details = 'account_deleted' WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM reports WHERE reporter_id = ?", (uid,))
    db.execute("DELETE FROM bans WHERE user_id = ?", (uid,))
    db.execute("DELETE FROM users WHERE id = ?", (uid,))
    db.commit()
    db.close()

    log_action(None, "account_self_delete", ip=get_client_ip(),
               details=f"former user {uid}")

    session.clear()
    return jsonify({"ok": True, "msg": "Your account and personal data have been deleted."})


# ── Socket Events ────────────────────────────────────────────────────────────
@socketio.on("connect")
def on_connect():
    uid = session.get("user_id")
    if not uid:
        return False  # reject unauthenticated
    # Check if banned
    if is_banned(uid):
        return False
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
    _leave_partner(sid, auto_requeue=True)  # re-queue the partner who's still online
    if uid:
        log_action(uid, "disconnect", ip=get_client_ip())
    _broadcast_online()


@socketio.on("q")  # join queue
def on_queue():
    sid = request.sid
    if not socket_rate_ok(sid):
        return
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
    if not socket_rate_ok(sid):
        return
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
    port = int(os.environ.get("PORT", 5000))

    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║       Nova (P2P) — running on :{port}         ║")
    print(f"  ╚══════════════════════════════════════════════╝\n")

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

    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
