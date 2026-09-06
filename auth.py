import sqlite3
import bcrypt
import jwt
import os
import secrets
from datetime import datetime, timedelta, timezone

DB_PATH         = os.path.join(os.path.dirname(__file__), "users.db")
SECRET_FILE     = os.path.join(os.path.dirname(__file__), ".jwt_secret")
ACCESS_EXPIRE   = timedelta(hours=1)
REFRESH_EXPIRE  = timedelta(hours=24)


def _load_secret() -> str:
    """
    JWT signing key, from $JWT_SECRET or a locally generated file.

    This used to be a literal in this file. server.py is published on a
    fixed ngrok domain, so a signing key committed to the repo let anyone
    holding it mint a valid admin token against the live UI. The key now
    never enters version control: .jwt_secret is gitignored, and setting
    $JWT_SECRET overrides it for a managed deployment.
    """
    env = (os.getenv("JWT_SECRET") or "").strip()
    if env:
        return env

    try:
        with open(SECRET_FILE) as f:
            saved = f.read().strip()
        if saved:
            return saved
    except OSError:
        pass

    generated = secrets.token_urlsafe(48)
    with open(SECRET_FILE, "w") as f:
        f.write(generated)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except OSError:
        pass          # best effort; Windows ACLs don't map cleanly
    print("🔑 New JWT signing key written to .jwt_secret — existing logins are invalidated.")
    return generated


SECRET_KEY = _load_secret()


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create users table and seed admin user if not exists."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            created  TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    # Seed admin if not exists
    existing = conn.execute(
        "SELECT id FROM users WHERE username = ?", ("shubhamagarwal25",)
    ).fetchone()

    if not existing:
        # The seed password used to be a literal here, which put a working
        # admin credential for the public UI into the repo. It now comes
        # from $ADMIN_PASSWORD, or is generated and shown once.
        password = (os.getenv("ADMIN_PASSWORD") or "").strip()
        shown    = None
        if not password:
            password = secrets.token_urlsafe(12)
            shown    = password
        hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ("shubhamagarwal25", hashed.decode())
        )
        conn.commit()
        print("✅ Admin user created: shubhamagarwal25")
        if shown:
            print(f"🔑 One-time admin password: {shown}  — change it after first login.")

    conn.close()


def verify_user(username: str, password: str) -> bool:
    conn = get_db()
    row  = conn.execute(
        "SELECT password FROM users WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    return bcrypt.checkpw(password.encode(), row["password"].encode())


def generate_tokens(username: str) -> dict:
    now = datetime.now(timezone.utc)

    access_payload = {
        "sub":  username,
        "type": "access",
        "iat":  now,
        "exp":  now + ACCESS_EXPIRE
    }
    refresh_payload = {
        "sub":  username,
        "type": "refresh",
        "iat":  now,
        "exp":  now + REFRESH_EXPIRE
    }

    access_token  = jwt.encode(access_payload,  SECRET_KEY, algorithm="HS256")
    refresh_token = jwt.encode(refresh_payload, SECRET_KEY, algorithm="HS256")

    return {
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "access_expires_in":  int(ACCESS_EXPIRE.total_seconds()),
        "refresh_expires_in": int(REFRESH_EXPIRE.total_seconds()),
    }


def verify_access_token(token: str) -> str | None:
    """Returns username if valid, None otherwise."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            return None
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def verify_refresh_token(token: str) -> str | None:
    """Returns username if valid, None otherwise."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "refresh":
            return None
        return payload["sub"]
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
