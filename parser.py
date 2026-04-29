from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime
from dateutil.relativedelta import relativedelta

from product_manager import get_weight


@dataclass
class PrintRequest:
    product: str
    weight: str
    quantity: int
    packed_on: str
    best_before: str


def normalize_weight(raw: str) -> str:
    """
    Smart weight normalization:

    User gives "2"     → number < 100  → "2 KGS"
    User gives "500"   → number >= 100 → "500 GMS"
    User gives "2 KGS" → has unit      → "2 KGS" (unchanged)
    User gives "500 GMS" → has unit    → "500 GMS" (unchanged)
    User gives "2kg" / "2kgs" / "2 kg" → normalized to "2 KGS"
    """
    raw = raw.strip().upper()

    # Already has a unit keyword — return as-is (cleaned up)
    for unit in ["KGS", "KG", "GMS", "GM", "GRAMS", "GRAM", "G"]:
        if unit in raw:
            # Normalize to KGS or GMS
            number = raw.replace(unit, "").strip()
            if unit in ["KGS", "KG"]:
                return f"{number} KGS"
            else:
                return f"{number} GMS"

    # Pure number — apply auto unit logic
    try:
        value = float(raw)
        if value < 100:
            return f"{int(value) if value == int(value) else value} KGS"
        else:
            return f"{int(value) if value == int(value) else value} GMS"
    except ValueError:
        # Not a number, return as-is
        return raw


def parse_message(text: str) -> Tuple[Optional[PrintRequest], Optional[str]]:
    """
    Parses a print request message.

    Accepted formats:
        phalli, 10              → product uppercased, weight from product list
        PHALLI, 10, 2           → weight auto → "2 KGS"
        PHALLI, 10, 500         → weight auto → "500 GMS"
        PHALLI, 10, 2 KGS       → weight kept as "2 KGS"
        PHALLI, 10, 500 GMS     → weight kept as "500 GMS"

    Returns (PrintRequest, None) on success or (None, error_message) on failure.
    """
    parts = [p.strip() for p in text.split(',')]

    if len(parts) < 2 or len(parts) > 3:
        return None, _format_error()

    # 1. Product — always uppercase
    product = parts[0].upper().strip()
    if not product:
        return None, _format_error()

    # 2. Quantity
    try:
        quantity = int(parts[1].strip())
        if quantity <= 0:
            return None, "⚠️ Quantity must be a positive number."
        if quantity > 500:
            return None, "⚠️ Quantity cannot exceed 500 per request."
    except ValueError:
        return None, "⚠️ Quantity must be a valid number.\n\n" + _format_error()

    # 3. Weight
    if len(parts) == 3:
        weight = normalize_weight(parts[2])
    else:
        weight = get_weight(product)  # lookup from products.json

    # 4. Auto dates
    today       = datetime.now()
    best_before = today + relativedelta(months=3)
    packed_on   = today.strftime("%d/%m/%y")
    best_before_str = best_before.strftime("%d/%m/%y")

    return PrintRequest(
        product=product,
        weight=weight,
        quantity=quantity,
        packed_on=packed_on,
        best_before=best_before_str,
    ), None


def _format_error() -> str:
    return (
        "❌ *Invalid format.* Use:\n\n"
        "`Product, Quantity`\n"
        "or\n"
        "`Product, Quantity, Weight`\n\n"
        "*Examples:*\n"
        "`PHALLI, 10`\n"
        "`TOOR DAL, 5, 2`\n"
        "`TOOR DAL, 5, 500`\n"
        "`TOOR DAL, 5, 2 KGS`"
    )