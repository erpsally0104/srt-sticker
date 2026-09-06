import json
import os
import sqlite3
from datetime import datetime

DB_PATH    = os.path.join(os.path.dirname(__file__), "users.db")
BATCH_FILE = os.path.join(os.path.dirname(__file__), "batch.json")   # legacy, migrated once


def _connect():
    # timeout lets a concurrent writer wait for the lock rather than fail
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.isolation_level = None      # transactions are managed explicitly below
    return conn


def init_batch_table():
    """
    Create the counter table and carry over whatever batch.json held.

    The migration matters: if today's sequence is already at 47, starting
    the new counter at 0 would reissue numbers that are on printed stock.
    """
    conn = _connect()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS batch_counter (
                id      INTEGER PRIMARY KEY CHECK (id = 1),
                date    TEXT    NOT NULL,
                counter INTEGER NOT NULL
            )
        """)
        date, counter = datetime.now().strftime("%d%m%y"), 0
        try:
            with open(BATCH_FILE) as f:
                data = json.load(f)
            date    = str(data.get("date", date))
            counter = int(data.get("counter", 0))
        except (OSError, ValueError, TypeError, KeyError):
            pass
        # OR IGNORE: two processes may reach this at once on first start
        conn.execute(
            "INSERT OR IGNORE INTO batch_counter (id, date, counter) VALUES (1, ?, ?)",
            (date, counter),
        )
    finally:
        conn.close()


def get_next_batch_number() -> str:
    """
    Generates the next batch number in format SRT{DDMMYY}{3-digit sequence}.
    Resets counter every day.
    Example: SRT020426001, SRT020426002, ...

    The counter lives in SQLite rather than a JSON file because run.bat
    starts bot.py and server.py as two separate processes. An unlocked
    read-modify-write handed the same number to both, and a lot number
    that identifies two different products defeats the recall trace it
    exists for (Reg 10(1)(e)). BEGIN IMMEDIATE takes the write lock up
    front, so concurrent callers queue instead of racing.
    """
    today = datetime.now().strftime("%d%m%y")
    conn  = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT date, counter FROM batch_counter WHERE id = 1"
            ).fetchone()
            if row is None or row[0] != today:
                counter = 1          # new day, or first ever run
                conn.execute(
                    "INSERT OR REPLACE INTO batch_counter (id, date, counter) "
                    "VALUES (1, ?, ?)",
                    (today, counter),
                )
            else:
                counter = row[1] + 1
                conn.execute(
                    "UPDATE batch_counter SET counter = ? WHERE id = 1", (counter,)
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    return f"SRT{today}{counter:03d}"


init_batch_table()
