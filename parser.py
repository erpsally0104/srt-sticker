from dataclasses import dataclass, field
from typing import Optional, Tuple
from datetime import datetime
from dateutil.relativedelta import relativedelta
import re

from product_manager import get_weight


@dataclass
class PrintRequest:
    product: str
    weight: str
    quantity: int
    packed_on: str
    best_before: str
    label_type: str = "product"  # "product" or "ingredients"
    ingredients: str = ""        # raw ingredients text for ingredients labels
    hotel: str = "general"       # hotel/client this product belongs to


def resolve_date(raw: str, fallback: datetime = None) -> Optional[str]:
    """
    Resolve a flexible date string into DD/MM/YY format.

    Supported inputs:
        ""  / None          → None (caller uses default)
        "today"             → today's date
        "today + 3 months"  → today + 3 months  (also: "today+3months", "today + 6 month")
        "15/04/2026"        → DD/MM/YYYY parsed
        "15-04-2026"        → DD-MM-YYYY parsed
        "15/04/26"          → DD/MM/YY parsed
        "15-04-26"          → DD-MM-YY parsed

    Returns DD/MM/YY string or None if input is empty/blank.
    Raises ValueError on unparseable input.
    """
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None

    low = raw.lower().replace(" ", "")

    # "today" or "today+Nmonth(s)"
    if low.startswith("today"):
        base = fallback or datetime.now()
        rest = low[5:]  # after "today"
        if not rest:
            return base.strftime("%d/%m/%y")
        # Match +Nmonth(s) or +Nday(s) or +Nyear(s)
        m = re.match(r"^\+(\d+)(months?|days?|years?)$", rest)
        if m:
            num  = int(m.group(1))
            unit = m.group(2)
            if unit.startswith("month"):
                dt = base + relativedelta(months=num)
            elif unit.startswith("day"):
                dt = base + relativedelta(days=num)
            elif unit.startswith("year"):
                dt = base + relativedelta(years=num)
            else:
                raise ValueError(f"Unknown unit in date expression: {raw}")
            return dt.strftime("%d/%m/%y")
        raise ValueError(f"Cannot parse date expression: {raw}")

    # DD/MM/YYYY or DD-MM-YYYY or DD/MM/YY or DD-MM-YY
    for sep, fmt4, fmt2 in [("/", "%d/%m/%Y", "%d/%m/%y"), ("-", "%d-%m-%Y", "%d-%m-%y")]:
        if sep in raw:
            parts = raw.split(sep)
            if len(parts) == 3:
                year_part = parts[2]
                try:
                    if len(year_part) == 4:
                        dt = datetime.strptime(raw, fmt4)
                    else:
                        dt = datetime.strptime(raw, fmt2)
                    return dt.strftime("%d/%m/%y")
                except ValueError:
                    pass

    raise ValueError(f"Cannot parse date: {raw}")


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


def parse_message(
    text: str,
    hotel: str = "general",
    packed_on: str = None,
    best_before: str = None,
) -> Tuple[Optional[PrintRequest], Optional[str]]:
    """
    Parses a print request message.

    Accepted formats:
        phalli, 10                                              → product uppercased, weight from product list
        PHALLI, 10, 2                                           → weight auto → "2 KGS"
        PHALLI, 10, 500                                         → weight auto → "500 GMS"
        PHALLI, 10, 2 KGS                                      → weight kept as "2 KGS"
        PHALLI, 10, 500 GMS                                     → weight kept as "500 GMS"
        PHALLI, 10, 2 KGS, packed_date, best_before, hotelname → full format

    packed_on / best_before can also be passed as function args (from UI / server).
    Date values support: today, today + 3 months, DD/MM/YYYY, DD-MM-YYYY, etc.

    Ingredients-only format:
        Refined wheat flour, Whole Wheat Flour ;; i
        Refined wheat flour, Whole Wheat Flour ;; i 5

    Returns (PrintRequest, None) on success or (None, error_message) on failure.
    """

    # ── Check for ingredients-only format: text ;; i [quantity] ──
    if ";;" in text:
        return _parse_ingredients(text)

    parts = [p.strip() for p in text.split(',')]

    if len(parts) < 2 or len(parts) > 6:
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

    # 3. Weight (optional 3rd param)
    # 4. Packed date (optional 4th param)
    # 5. Best before (optional 5th param)
    # 6. Hotel (optional 6th param)
    req_hotel = hotel
    weight = None
    inline_packed = None
    inline_bb = None

    if len(parts) >= 3 and parts[2].strip():
        weight = normalize_weight(parts[2])
    if len(parts) >= 4 and parts[3].strip():
        inline_packed = parts[3].strip()
    if len(parts) >= 5 and parts[4].strip():
        inline_bb = parts[4].strip()
    if len(parts) >= 6 and parts[5].strip():
        req_hotel = parts[5].strip().lower()

    if weight is None:
        weight = get_weight(product, req_hotel)

    # Resolve dates — inline params (from bot) take priority over function args (from UI)
    today = datetime.now()

    # Packed on
    raw_packed = inline_packed or packed_on
    try:
        resolved_packed = resolve_date(raw_packed, fallback=today)
    except ValueError as e:
        return None, f"⚠️ Invalid packed date: {e}"
    packed_on_str = resolved_packed or today.strftime("%d/%m/%y")

    # Best before
    raw_bb = inline_bb or best_before
    try:
        resolved_bb = resolve_date(raw_bb, fallback=today)
    except ValueError as e:
        return None, f"⚠️ Invalid best-before date: {e}"
    best_before_str = resolved_bb or (today + relativedelta(months=3)).strftime("%d/%m/%y")

    return PrintRequest(
        product=product,
        weight=weight,
        quantity=quantity,
        packed_on=packed_on_str,
        best_before=best_before_str,
        hotel=req_hotel,
    ), None


def _parse_ingredients(text: str) -> Tuple[Optional[PrintRequest], Optional[str]]:
    """
    Parse ingredients-only sticker format.

    Format: <ingredients text> ;; i [quantity]
    Examples:
        Refined wheat flour, Whole Wheat Flour ;; i       → 1 sticker
        Refined wheat flour, Whole Wheat Flour ;; i 5     → 5 stickers
    """
    parts = text.split(";;")
    if len(parts) != 2:
        return None, _ingredients_format_error()

    ingredients_text = parts[0].strip()
    suffix = parts[1].strip()

    # suffix should be "i" or "i <number>"
    suffix_parts = suffix.split()
    if not suffix_parts or suffix_parts[0].lower() != "i":
        return None, _ingredients_format_error()

    if not ingredients_text:
        return None, "⚠️ Ingredients text cannot be empty."

    # Quantity (default 1)
    quantity = 1
    if len(suffix_parts) >= 2:
        try:
            quantity = int(suffix_parts[1])
            if quantity <= 0:
                return None, "⚠️ Quantity must be a positive number."
            if quantity > 500:
                return None, "⚠️ Quantity cannot exceed 500 per request."
        except ValueError:
            return None, "⚠️ Quantity after `i` must be a valid number.\n\n" + _ingredients_format_error()

    return PrintRequest(
        product="INGREDIENTS",
        weight="",
        quantity=quantity,
        packed_on="",
        best_before="",
        label_type="ingredients",
        ingredients=ingredients_text,
    ), None


def _format_error() -> str:
    return (
        "❌ *Invalid format.* Use:\n\n"
        "`Product, Quantity`\n"
        "`Product, Quantity, Weight`\n"
        "`Product, Quantity, Weight, PackedDate, BestBefore, Hotel`\n\n"
        "*Examples:*\n"
        "`PHALLI, 10`\n"
        "`TOOR DAL, 5, 2`\n"
        "`TOOR DAL, 5, 2 KGS`\n"
        "`TOOR DAL, 5, 2 KGS, today, today + 6 months, taj`\n"
        "`TOOR DAL, 5, 2 KGS, 15/04/2026, 15/07/2026`\n\n"
        "_Dates are optional. Defaults: Packed = today, Best Before = today + 3 months._\n"
        "_Date formats: today, today + N months, DD/MM/YYYY, DD-MM-YYYY_\n\n"
        "*Ingredients sticker:*\n"
        "`Refined wheat flour, Rice Flour ;; i`\n"
        "`Refined wheat flour, Rice Flour ;; i 5`"
    )


def _ingredients_format_error() -> str:
    return (
        "❌ *Invalid ingredients format.* Use:\n\n"
        "`Ingredients text ;; i`\n"
        "or\n"
        "`Ingredients text ;; i 5`\n\n"
        "*Examples:*\n"
        "`Refined wheat flour, Whole Wheat Flour ;; i`\n"
        "`Refined wheat flour, Rice Flour ;; i 10`"
    )
