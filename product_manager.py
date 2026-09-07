import json
import os
import shutil

PRODUCTS_FILE = os.path.join(os.path.dirname(__file__), "products.json")
BACKUP_FILE   = PRODUCTS_FILE + ".bak"

DEFAULT_WEIGHT = "500 g"
DEFAULT_HOTEL  = "general"


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


def get_weight(product: str, hotel: str = DEFAULT_HOTEL) -> str:
    """Returns the default weight for a product in a hotel, or DEFAULT_WEIGHT if not found."""
    data = _load()
    hotel_products = data.get(hotel.lower(), {})
    for key, val in hotel_products.items():
        if key.upper() == product.upper():
            return val
    # Fallback to general if not found in specific hotel
    if hotel.lower() != DEFAULT_HOTEL:
        general = data.get(DEFAULT_HOTEL, {})
        for key, val in general.items():
            if key.upper() == product.upper():
                return val
    return DEFAULT_WEIGHT


def product_exists(product: str, hotel: str = DEFAULT_HOTEL) -> bool:
    data = _load()
    hotel_products = data.get(hotel.lower(), {})
    return any(k.upper() == product.upper() for k in hotel_products)


def add_product(product: str, weight: str, hotel: str = DEFAULT_HOTEL) -> str:
    product = product.upper().strip()
    weight = weight.upper().strip()
    hotel = hotel.lower().strip()
    data = _load()
    if hotel not in data:
        data[hotel] = {}
    hotel_products = data[hotel]
    if any(k.upper() == product for k in hotel_products):
        # Update existing (remove old key casing, add new)
        old_key = next(k for k in hotel_products if k.upper() == product)
        del hotel_products[old_key]
        hotel_products[product] = weight
        _save(data)
        return f"✅ Updated *{product}* → {weight} in [{hotel}]"
    hotel_products[product] = weight
    _save(data)
    return f"✅ Added *{product}* → {weight} to [{hotel}]"


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
        for product, weight in hotel_products.items():
            lines.append(f"  • {product} → {weight}")
        lines.append(f"\n_Default weight for unlisted products: {DEFAULT_WEIGHT}_")
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


def get_hotel_products(hotel: str = DEFAULT_HOTEL) -> dict:
    """Returns the product dict for a specific hotel."""
    data = _load()
    return data.get(hotel.lower(), {})
