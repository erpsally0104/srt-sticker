import json
import os

PRODUCTS_FILE = os.path.join(os.path.dirname(__file__), "products.json")

DEFAULT_WEIGHT = "500 GMS"
DEFAULT_HOTEL  = "general"


def _load() -> dict:
    with open(PRODUCTS_FILE, "r") as f:
        data = json.load(f)
    # Auto-migrate flat format → hotel-grouped format
    if data and not any(isinstance(v, dict) for v in data.values()):
        data = {DEFAULT_HOTEL: data}
        _save(data)
    return data


def _save(data: dict):
    with open(PRODUCTS_FILE, "w") as f:
        json.dump(data, f, indent=2)


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
