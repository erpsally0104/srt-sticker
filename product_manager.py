import json
import os

PRODUCTS_FILE = os.path.join(os.path.dirname(__file__), "products.json")

DEFAULT_WEIGHT = "500 GMS"


def _load() -> dict:
    with open(PRODUCTS_FILE, "r") as f:
        return json.load(f)


def _save(data: dict):
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_weight(product: str) -> str:
    """Returns the default weight for a product, or DEFAULT_WEIGHT if not found."""
    data = _load()
    # Case-insensitive lookup
    for key, val in data.items():
        if key.upper() == product.upper():
            return val
    return DEFAULT_WEIGHT


def product_exists(product: str) -> bool:
    data = _load()
    return any(k.upper() == product.upper() for k in data)


def add_product(product: str, weight: str) -> str:
    product = product.upper().strip()
    weight = weight.upper().strip()
    data = _load()
    if any(k.upper() == product for k in data):
        data[product] = weight
        _save(data)
        return f"✅ Updated *{product}* → {weight}"
    data[product] = weight
    _save(data)
    return f"✅ Added *{product}* → {weight}"


def remove_product(product: str) -> str:
    product = product.upper().strip()
    data = _load()
    key_to_remove = next((k for k in data if k.upper() == product), None)
    if not key_to_remove:
        return f"⚠️ *{product}* not found in product list."
    del data[key_to_remove]
    _save(data)
    return f"✅ Removed *{product}* from product list."


def list_products() -> str:
    data = _load()
    if not data:
        return "No products in list."
    lines = ["📦 *Product List:*"]
    for product, weight in data.items():
        lines.append(f"  • {product} → {weight}")
    lines.append(f"\n_Default weight for unlisted products: {DEFAULT_WEIGHT}_")
    return "\n".join(lines)
