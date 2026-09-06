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


def resolve_date(raw: str, fallback: datetime = None) -> Optional[datetime]:
    """
    Resolve a flexible date string into a datetime.

    Formatting happens later in format_date_pair(), because the printed
    format depends on the shelf life — the gap between the two dates —
    not on either date alone.

    Supported inputs:
        ""  / None          → None (caller uses default)
        "today"             → today's date
        "today + 3 months"  → today + 3 months  (also: "today+3months", "today + 6 month")
        "15/04/2026"        → DD/MM/YYYY parsed
        "15-04-2026"        → DD-MM-YYYY parsed
        "15/04/26"          → DD/MM/YY parsed
        "15-04-26"          → DD-MM-YY parsed

    Returns a datetime, or None if input is empty/blank.
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
            return base
        # Match +Nmonth(s) or +Nday(s) or +Nyear(s)
        m = re.match(r"^\+(\d+)(months?|days?|years?)$", rest)
        if m:
            num  = int(m.group(1))
            unit = m.group(2)
            if unit.startswith("month"):
                return base + relativedelta(months=num)
            elif unit.startswith("day"):
                return base + relativedelta(days=num)
            elif unit.startswith("year"):
                return base + relativedelta(years=num)
            raise ValueError(f"Unknown unit in date expression: {raw}")
        raise ValueError(f"Cannot parse date expression: {raw}")

    # DD/MM/YYYY or DD-MM-YYYY or DD/MM/YY or DD-MM-YY
    for sep, fmt4, fmt2 in [("/", "%d/%m/%Y", "%d/%m/%y"), ("-", "%d-%m-%Y", "%d-%m-%y")]:
        if sep in raw:
            parts = raw.split(sep)
            if len(parts) == 3:
                year_part = parts[2]
                try:
                    if len(year_part) == 4:
                        return datetime.strptime(raw, fmt4)
                    return datetime.strptime(raw, fmt2)
                except ValueError:
                    pass

    raise ValueError(f"Cannot parse date: {raw}")


# Month abbreviations in capitals — spelled out rather than taken from
# strftime("%b") so the label never changes with the machine's locale.
MONTHS_UPPER = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def format_date_pair(packed: datetime, expiry: datetime) -> Tuple[str, str]:
    """
    Format the packed and use-by dates per FSSAI Reg 5(10)(b)(i).

    Shelf life up to 3 months → DD/MM/YY
    Shelf life over 3 months  → MON YYYY, month in capital letters

    Both dates take the same format so they read as a pair, which
    Reg 5(10)(e) requires them to when grouped together. The packing day
    stays recoverable from the batch number (SRT + DDMMYY + sequence).
    """
    if expiry > packed + relativedelta(months=3):
        return (
            f"{MONTHS_UPPER[packed.month - 1]} {packed.year}",
            f"{MONTHS_UPPER[expiry.month - 1]} {expiry.year}",
        )
    return packed.strftime("%d/%m/%y"), expiry.strftime("%d/%m/%y")


def normalize_weight(raw: str) -> str:
    """
    Smart weight normalization into Legal Metrology unit symbols.

    User gives "2"       → number < 100  → "2 kg"
    User gives "500"     → number >= 100 → "500 g"
    User gives "2 KGS"   → has unit      → "2 kg"
    User gives "500 GMS" → has unit      → "500 g"
    User gives "2kg" / "2kgs" / "2 kg"   → "2 kg"

    The Legal Metrology (Packaged Commodities) Rules allow only the SI
    symbols — lowercase, singular, no full stop. "KGS" and "GMS" are not
    valid net-quantity declarations, so every input form collapses to
    "kg" or "g" here.
    """
    raw = raw.strip().upper()

    # Already has a unit keyword — rewrite it as the SI symbol
    for unit in ["KGS", "KG", "GMS", "GM", "GRAMS", "GRAM", "G"]:
        if unit in raw:
            number = raw.replace(unit, "").strip()
            if unit in ["KGS", "KG"]:
                return f"{number} kg"
            else:
                return f"{number} g"

    # Pure number — apply auto unit logic
    try:
        value = float(raw)
        if value < 100:
            return f"{int(value) if value == int(value) else value} kg"
        else:
            return f"{int(value) if value == int(value) else value} g"
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
        PHALLI, 10, 2                                           → weight auto → "2 kg"
        PHALLI, 10, 500                                         → weight auto → "500 g"
        PHALLI, 10, 2 KGS                                       → normalized to "2 kg"
        PHALLI, 10, 500 GMS                                     → normalized to "500 g"
        PHALLI, 10, 2 kg, packed_date, use_by, hotelname        → full format

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
        # Normalize on the way out too — stored weights may predate the
        # switch to SI symbols.
        weight = normalize_weight(get_weight(product, req_hotel))

    # Resolve dates — inline params (from bot) take priority over function args (from UI)
    today = datetime.now()

    # Packed on
    raw_packed = inline_packed or packed_on
    try:
        packed_dt = resolve_date(raw_packed, fallback=today)
    except ValueError as e:
        return None, f"⚠️ Invalid packed date: {e}"
    packed_dt = packed_dt or today

    # Use by
    raw_bb = inline_bb or best_before
    try:
        expiry_dt = resolve_date(raw_bb, fallback=today)
    except ValueError as e:
        return None, f"⚠️ Invalid use-by date: {e}"
    expiry_dt = expiry_dt or (today + relativedelta(months=3))

    packed_on_str, best_before_str = format_date_pair(packed_dt, expiry_dt)

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
        "`TOOR DAL, 5, 2 kg`\n"
        "`TOOR DAL, 5, 2 kg, today, today + 6 months, taj`\n"
        "`TOOR DAL, 5, 2 kg, 15/04/2026, 15/07/2026`\n\n"
        "_Dates are optional. Defaults: Packed = today, Use By = today + 3 months._\n"
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
