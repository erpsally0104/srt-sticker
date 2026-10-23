import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def get_db():
    # timeout matches batch_manager: bot.py and server.py are separate
    # processes contending for this file, and the 5s default was short
    # enough to surface as OperationalError on the print worker thread.
    conn = sqlite3.connect(DB_PATH, timeout=15)
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
    # Added later, so a reprint from History matches the original:
    #   as_typed  — 1 when the name printed exactly as typed, not in English
    #   roll_type — the label type it printed on ("" for older rows)
    added = {"as_typed": "INTEGER NOT NULL DEFAULT 0", "roll_type": "TEXT NOT NULL DEFAULT ''"}
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(print_logs)")}
    for name, decl in added.items():
        if name not in cols:
            try:
                conn.execute(f"ALTER TABLE print_logs ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                pass   # bot.py and server.py both start this; the other one got there first
    conn.commit()
    conn.close()


def log_print(username: str, source: str, product: str, weight: str,
              quantity: int, batch_no: str, packed_on: str, best_before: str,
              as_typed: bool = False, roll_type: str = ""):
    """Log a print job."""
    conn = get_db()
    conn.execute("""
        INSERT INTO print_logs
            (timestamp, username, source, product, weight, quantity, batch_no, packed_on, best_before,
             as_typed, roll_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        username,
        source,
        product,
        weight,
        quantity,
        batch_no,
        packed_on,
        best_before,
        int(bool(as_typed)),
        roll_type or "",
    ))
    conn.commit()
    conn.close()


def get_logs(username: str, is_admin: bool, limit: int = 100,
             filter_user: str = None, filter_product: str = None,
             since_utc: str = None, until_utc: str = None, offset: int = 0,
             also_products: list = None) -> list:
    """
    Fetch logs, newest first.
    Admin sees all, others see only their own.
    since_utc / until_utc ("YYYY-MM-DD HH:MM:SS", UTC like the timestamps
    themselves) bound the time range: since inclusive, until exclusive.
    also_products widens filter_product with exact product names, so a
    search finds a product under every name it has printed as.
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
        clause = "product LIKE ?"
        params.append(f"%{filter_product.upper()}%")
        if also_products:
            clause += " OR product IN (%s)" % ",".join("?" * len(also_products))
            params.extend(p.upper() for p in also_products)
        where.append(f"({clause})")

    if since_utc:
        where.append("timestamp >= ?")
        params.append(since_utc)
    if until_utc:
        where.append("timestamp < ?")
        params.append(until_utc)

    if where:
        query += " WHERE " + " AND ".join(where)

    query += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

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
