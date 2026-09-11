import json
import os
import re
import shutil

PRODUCTS_FILE = os.path.join(os.path.dirname(__file__), "products.json")
BACKUP_FILE   = PRODUCTS_FILE + ".bak"

DEFAULT_HOTEL  = "general"

# Use By = Packed + this many months, unless the product sets its own.
DEFAULT_SHELF_MONTHS = 3
SHELF_MONTHS_RANGE   = (1, 60)

# Hotel names travel as one bare word: the 6th comma field of a Telegram
# print line, and the last argument of /removeproduct.
HOTEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")

# A product's entry is its weight string ("2 kg") or, once a shelf life has
# been set, {"weight": "2 kg", "shelf_months": 6}. Plain strings stay the
# norm so older files, recover_products.py and hand edits keep working.
_KEEP = object()   # add_product(): leave the product's shelf life as it is


def _entry_weight(val) -> str:
    return str(val.get("weight", "")) if isinstance(val, dict) else str(val)


def _entry_shelf(val):
    return val.get("shelf_months") if isinstance(val, dict) else None


def _make_entry(weight: str, shelf_months):
    return {"weight": weight, "shelf_months": shelf_months} if shelf_months else weight


def _find_key(hotel_products: dict, product: str):
    product = product.upper()
    return next((k for k in hotel_products if k.upper() == product), None)


def validate_shelf_months(raw):
    """Returns (months or None, error or None). Blank means 'use the default'."""
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        months = int(str(raw).strip())
    except ValueError:
        return None, "Shelf life must be a whole number of months"
    lo, hi = SHELF_MONTHS_RANGE
    if not lo <= months <= hi:
        return None, f"Shelf life must be between {lo} and {hi} months"
    return months, None


def _read_json(path):
    """Parse a JSON file, or return None if it is missing or unreadable."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _load() -> dict:
    data = _read_json(PRODUCTS_FILE)

    if data is None:
        # A truncated products.json takes down every endpoint that lists
        # products, so fall back to the last good copy rather than 500.
        data = _read_json(BACKUP_FILE)
        if data is None:
            raise ValueError(
                f"{PRODUCTS_FILE} is unreadable and there is no usable backup. "
                "Restore it with:  git checkout -- products.json"
            )
        print(f"⚠️  {PRODUCTS_FILE} was unreadable — recovered from {BACKUP_FILE}")
        _save(data)

    # Auto-migrate flat format → hotel-grouped format
    if data and not any(isinstance(v, dict) for v in data.values()):
        data = {DEFAULT_HOTEL: data}
        _save(data)
    return data


def _save(data: dict):
    """
    Write atomically, keeping the previous good copy as products.json.bak.

    open(..., "w") truncates the file before a single byte is written, so
    an interrupted or concurrent write leaves a partial document that
    _load() can no longer parse — and run.bat starts bot.py and server.py
    as two processes that both write here. Writing to a temp file and
    renaming means the live file is only ever a complete document.
    """
    tmp = PRODUCTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(PRODUCTS_FILE):
        try:
            shutil.copyfile(PRODUCTS_FILE, BACKUP_FILE)
        except OSError:
            pass          # a missing backup must never block the write
    os.replace(tmp, PRODUCTS_FILE)      # atomic on Windows and POSIX


def find_product(product: str, hotel: str = DEFAULT_HOTEL):
    """
    Returns (weight, shelf_months) for a listed product, or None if it is
    not listed. The hotel's own list wins; otherwise it falls back to
    general. shelf_months is None when the product does not set one.

    There is deliberately no default weight: a guessed net quantity on a
    label is worse than refusing to print it.
    """
    data = _load()
    hotel = hotel.lower()
    for h in ([hotel, DEFAULT_HOTEL] if hotel != DEFAULT_HOTEL else [hotel]):
        prods = data.get(h, {})
        key = _find_key(prods, product)
        if key is not None:
            return _entry_weight(prods[key]), _entry_shelf(prods[key])
    return None


def product_exists(product: str, hotel: str = DEFAULT_HOTEL) -> bool:
    data = _load()
    return _find_key(data.get(hotel.lower(), {}), product) is not None


def add_product(product: str, weight: str, hotel: str = DEFAULT_HOTEL,
                shelf_months=_KEEP) -> str:
    """Add or update a product. Leaving shelf_months out keeps what the product already has."""
    product = product.upper().strip()
    weight = weight.upper().strip()
    hotel = hotel.lower().strip()
    data = _load()
    if hotel not in data:
        data[hotel] = {}
    hotel_products = data[hotel]
    old_key = _find_key(hotel_products, product)
    if shelf_months is _KEEP:
        shelf_months = _entry_shelf(hotel_products[old_key]) if old_key is not None else None
    entry = _make_entry(weight, shelf_months)
    if old_key is not None:
        # Update existing (remove old key casing, add new)
        del hotel_products[old_key]
        hotel_products[product] = entry
        _save(data)
        return f"✅ Updated *{product}* → {weight} in [{hotel}]"
    hotel_products[product] = entry
    _save(data)
    return f"✅ Added *{product}* → {weight} to [{hotel}]"


def update_product(old_product: str, product: str, weight: str,
                   hotel: str = DEFAULT_HOTEL, shelf_months=None):
    """
    Edit a product in place: name, weight and shelf life in one write.

    The web UI used to rename by removing the old name and then adding the
    new one as two requests; if the second failed, the product was gone.
    Returns (ok, message).
    """
    old_product = old_product.upper().strip()
    product = product.upper().strip()
    weight = weight.upper().strip()
    hotel = hotel.lower().strip()
    data = _load()
    prods = data.get(hotel, {})
    old_key = _find_key(prods, old_product)
    if old_key is None:
        return False, f"{old_product} not found in [{hotel}]"
    clash = _find_key(prods, product)
    if clash is not None and clash != old_key:
        return False, f"{product} is already in [{hotel}]"
    # Rebuilt rather than del + insert so the product keeps its place in the list
    data[hotel] = {
        (product if k == old_key else k): (_make_entry(weight, shelf_months) if k == old_key else v)
        for k, v in prods.items()
    }
    _save(data)
    return True, f"Updated {product} in [{hotel}]"


def add_hotel(hotel: str):
    """Create an empty hotel. Returns (ok, message)."""
    hotel = (hotel or "").strip().lower()
    if not HOTEL_NAME_RE.match(hotel):
        return False, "Hotel name: letters, numbers, - or _ only, no spaces (max 30)"
    data = _load()
    if hotel in data:
        return False, f"[{hotel}] already exists"
    data[hotel] = {}
    _save(data)
    return True, f"Added hotel [{hotel}]"


def remove_product(product: str, hotel: str = DEFAULT_HOTEL) -> str:
    product = product.upper().strip()
    hotel = hotel.lower().strip()
    data = _load()
    hotel_products = data.get(hotel, {})
    key_to_remove = next((k for k in hotel_products if k.upper() == product), None)
    if not key_to_remove:
        return f"⚠️ *{product}* not found in [{hotel}]."
    del hotel_products[key_to_remove]
    _save(data)
    return f"✅ Removed *{product}* from [{hotel}]."


def list_products(hotel: str = None) -> str:
    data = _load()
    if not data:
        return "No products in list."

    if hotel:
        hotel = hotel.lower().strip()
        hotel_products = data.get(hotel, {})
        if not hotel_products:
            return f"No products in [{hotel}]."
        lines = [f"📦 *Product List [{hotel}]:*"]
        for product, val in hotel_products.items():
            shelf = _entry_shelf(val)
            shelf_txt = f" ({shelf} mo shelf life)" if shelf else ""
            lines.append(f"  • {product} → {_entry_weight(val)}{shelf_txt}")
        lines.append(
            "\n_Unlisted products need a weight in the message. "
            f"Shelf life defaults to {DEFAULT_SHELF_MONTHS} months._"
        )
        return "\n".join(lines)

    # List all hotels
    lines = []
    for h, prods in data.items():
        lines.append(f"📦 *[{h}]* — {len(prods)} products")
    lines.append(f"\nUse `/listproducts <hotel>` to see products for a specific hotel.")
    return "\n".join(lines)


def list_hotels() -> list:
    """Returns list of hotel names."""
    data = _load()
    return list(data.keys())


def hotel_entries(hotel: str, data: dict = None) -> list:
    """[{name, weight, shelf_months}, ...] for one hotel's own list."""
    data = _load() if data is None else data
    return [
        {"name": k, "weight": _entry_weight(v), "shelf_months": _entry_shelf(v)}
        for k, v in data.get(hotel.lower(), {}).items()
    ]


def all_hotel_entries() -> dict:
    """{hotel: [{name, weight, shelf_months}, ...]} for every hotel."""
    data = _load()
    return {h: hotel_entries(h, data) for h in data}
