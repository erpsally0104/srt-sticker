"""
Rebuild products.json after it was lost or truncated.

Run it in the label-bot folder on the print machine:

    python recover_products.py            # show what it would do, change nothing
    python recover_products.py --apply    # write the rebuilt file

It pulls from three sources, best first:

  1. the current products.json, if it still parses  (your live edits)
  2. the copy committed in git                      (139 curated products)
  3. the print_logs table in users.db               (what was actually printed)

Source 3 is what recovers products added after the last commit: every print
job records the product and the weight it went out with. Products seen only
in the log are listed separately and are added only when they were printed
at least MIN_PRINTS times, so a one-off typo does not re-enter the catalogue.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys

HERE          = os.path.dirname(os.path.abspath(__file__))
PRODUCTS_FILE = os.path.join(HERE, "products.json")
DB_PATH       = os.path.join(HERE, "users.db")
DEFAULT_HOTEL = "general"
MIN_PRINTS    = 2          # log-only products need this many prints to return

APPLY = "--apply" in sys.argv


def read_json(path):
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def from_git():
    """The committed copy, read without touching the working tree."""
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:products.json"],
            cwd=HERE, capture_output=True, text=True, timeout=20,
        )
        if out.returncode != 0:
            return None
        data = json.loads(out.stdout)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def from_print_logs():
    """
    {PRODUCT: (weight, times_printed)} from the print history.

    The most recent weight wins, because that is what the last physical
    label actually carried. print_logs has no hotel column, so everything
    recovered here lands in the default hotel.
    """
    if not os.path.exists(DB_PATH):
        return {}
    try:
        conn = sqlite3.connect(DB_PATH)
        rows = conn.execute("""
            SELECT product, weight, COUNT(*) AS n, MAX(id) AS last_id
            FROM print_logs
            WHERE product <> '' AND weight <> '' AND product <> 'INGREDIENTS'
            GROUP BY UPPER(product)
        """).fetchall()
        latest = {}
        for product, _, n, last_id in rows:
            weight = conn.execute(
                "SELECT weight FROM print_logs WHERE id = ?", (last_id,)
            ).fetchone()[0]
            latest[product.upper().strip()] = (weight.strip(), n)
        conn.close()
        return latest
    except sqlite3.Error as e:
        print("   ! could not read print_logs: %s" % e)
        return {}


def si(weight):
    """Normalise a logged weight to the SI symbols the label now prints."""
    w = weight.strip().upper()
    for unit, out in (("KGS", "kg"), ("KG", "kg"),
                      ("GMS", "g"), ("GM", "g"), ("GRAMS", "g"), ("G", "g")):
        if unit in w:
            num = w.replace(unit, "").strip()
            return "%s %s" % (num, out) if num else weight.strip()
    return weight.strip()


def main():
    print("Rebuilding products.json")
    print("=" * 58)

    merged, origin = {}, {}

    live = read_json(PRODUCTS_FILE)
    if live is None:
        size = os.path.getsize(PRODUCTS_FILE) if os.path.exists(PRODUCTS_FILE) else 0
        print("1. current products.json : UNREADABLE (%d bytes)" % size)
    else:
        n = sum(len(v) for v in live.values() if isinstance(v, dict))
        print("1. current products.json : %d products" % n)
        for hotel, prods in live.items():
            if isinstance(prods, dict):
                for k, v in prods.items():
                    merged.setdefault(hotel, {})[k.upper()] = v
                    origin[(hotel, k.upper())] = "kept"

    committed = from_git()
    if committed is None:
        print("2. git HEAD              : not available")
    else:
        n = sum(len(v) for v in committed.values() if isinstance(v, dict))
        print("2. git HEAD              : %d products" % n)
        for hotel, prods in committed.items():
            if isinstance(prods, dict):
                for k, v in prods.items():
                    key = (hotel, k.upper())
                    if key not in origin:
                        merged.setdefault(hotel, {})[k.upper()] = v
                        origin[key] = "from git"

    logged = from_print_logs()
    print("3. print_logs            : %d distinct products printed" % len(logged))

    restored, skipped = [], []
    for product, (weight, times) in sorted(logged.items()):
        if (DEFAULT_HOTEL, product) in origin:
            continue
        if times >= MIN_PRINTS:
            merged.setdefault(DEFAULT_HOTEL, {})[product] = si(weight)
            origin[(DEFAULT_HOTEL, product)] = "from log"
            restored.append((product, si(weight), times))
        else:
            skipped.append((product, si(weight), times))

    merged = {h: p for h, p in merged.items() if p}
    total  = sum(len(v) for v in merged.values())

    print("=" * 58)
    print("Rebuilt catalogue: %d products across %s" % (total, list(merged)))

    if restored:
        print("\nRecovered from the print log (printed >= %d times, not in git):" % MIN_PRINTS)
        for p, w, n in restored:
            print("   %-26s %-9s %3d prints" % (p, w, n))

    if skipped:
        print("\nSeen only once in the log — NOT added, check for typos:")
        for p, w, n in skipped[:40]:
            print("   %-26s %-9s %3d print" % (p, w, n))
        if len(skipped) > 40:
            print("   ... and %d more" % (len(skipped) - 40))

    if not APPLY:
        print("\nDry run. Nothing written. Re-run with --apply to save:")
        print("    python recover_products.py --apply")
        return

    if os.path.exists(PRODUCTS_FILE):
        shutil.copyfile(PRODUCTS_FILE, PRODUCTS_FILE + ".before-recovery")
        print("\nOld file kept as products.json.before-recovery")

    tmp = PRODUCTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(merged, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PRODUCTS_FILE)
    print("Wrote %d products to products.json" % total)
    print("Restart bot.py and server.py to pick it up.")


if __name__ == "__main__":
    main()
