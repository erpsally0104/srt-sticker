"""
Daily snapshot of users.db.

users.db is the only copy of three things that cannot be reconstructed:
the batch counter, the print_logs rows that are the FSSAI recall trace,
and the web logins. It is gitignored (*.db), so nothing else copies it.

VACUUM INTO is used rather than a file copy because it takes a consistent
snapshot of a database that may be open and mid-write in another process.

Called from run.bat at startup. Safe to run by hand at any time.
"""

import os
import sqlite3
from datetime import date

HERE    = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "users.db")
BAK_DIR = os.path.join(HERE, "backups")
KEEP    = 30          # days of snapshots to retain


def main():
    if not os.path.exists(DB_PATH):
        print("[backup] users.db not found — nothing to do.")
        return

    os.makedirs(BAK_DIR, exist_ok=True)
    dst = os.path.join(BAK_DIR, "users-%s.db" % date.today().isoformat())

    # VACUUM INTO refuses to overwrite, so clear today's snapshot first.
    if os.path.exists(dst):
        os.remove(dst)

    try:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        try:
            conn.execute("VACUUM INTO ?", (dst,))
        finally:
            conn.close()
        print("[backup] wrote %s (%d bytes)" % (dst, os.path.getsize(dst)))
    except Exception as e:
        # A failed backup must never stop the shop from printing.
        print("[backup] FAILED: %s" % e)
        return

    _prune()


def _prune():
    """Keep the newest KEEP snapshots; drop the rest."""
    try:
        snaps = sorted(
            f for f in os.listdir(BAK_DIR)
            if f.startswith("users-") and f.endswith(".db")
        )
        for old in snaps[:-KEEP]:
            os.remove(os.path.join(BAK_DIR, old))
    except OSError as e:
        print("[backup] prune skipped: %s" % e)


if __name__ == "__main__":
    main()
