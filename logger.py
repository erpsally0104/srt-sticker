import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_logs_table():
    """Create print_logs table if not exists."""
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS print_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            username    TEXT    NOT NULL,
            source      TEXT    NOT NULL DEFAULT 'ui',
            product     TEXT    NOT NULL,
            weight      TEXT    NOT NULL,
            quantity    INTEGER NOT NULL,
            batch_no    TEXT    NOT NULL,
            packed_on   TEXT    NOT NULL,
            best_before TEXT    NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def log_print(username: str, source: str, product: str, weight: str,
              quantity: int, batch_no: str, packed_on: str, best_before: str):
    """Log a print job."""
    conn = get_db()
    conn.execute("""
        INSERT INTO print_logs
            (timestamp, username, source, product, weight, quantity, batch_no, packed_on, best_before)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        username,
        source,
        product,
        weight,
        quantity,
        batch_no,
        packed_on,
        best_before
    ))
    conn.commit()
    conn.close()


def get_logs(username: str, is_admin: bool, limit: int = 100,
             filter_user: str = None, filter_product: str = None) -> list:
    """
    Fetch logs.
    Admin sees all, others see only their own.
    """
    conn   = get_db()
    query  = "SELECT * FROM print_logs"
    params = []
    where  = []

    if not is_admin:
        where.append("username = ?")
        params.append(username)
    elif filter_user:
        where.append("username LIKE ?")
        params.append(f"%{filter_user}%")

    if filter_product:
        where.append("product LIKE ?")
        params.append(f"%{filter_product.upper()}%")

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_usernames() -> list:
    """Returns all usernames who have print logs (for admin filter)."""
    conn  = get_db()
    rows  = conn.execute(
        "SELECT DISTINCT username FROM print_logs ORDER BY username"
    ).fetchall()
    conn.close()
    return [r["username"] for r in rows]


# Init table on import
init_logs_table()
