import sqlite3
import bcrypt
import jwt
import os
from datetime import datetime, timedelta, timezone

DB_PATH         = os.path.join(os.path.dirname(__file__), "users.db")
SECRET_KEY      = "SRT_LABEL_BOT_SECRET_2026_XK92"
ACCESS_EXPIRE   = timedelta(hours=1)
REFRESH_EXPIRE  = timedelta(hours=24)


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
        hashed = bcrypt.hashpw("SRTsticker@2026".encode(), bcrypt.gensalt())
        conn.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            ("shubhamagarwal25", hashed.decode())
        )
        conn.commit()
        print("✅ Admin user created: shubhamagarwal25")

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
