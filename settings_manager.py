import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

# Label types, one per roll the printer can hold:
#   single — one small label per row
#   double — two small labels side by side (2-up)
#   large  — one 75 x 50 mm CRYSTAL CLEAR label per row
# Every print job carries its own type. The "roll_type" setting is only the
# default: what the web UI starts on and what Telegram always prints.
VALID_ROLL_TYPES = {"single", "double", "large"}

# ── Print geometry (all values in mm) ─────────
GEOMETRY_DEFAULTS = {
    "label_width_mm":   50,   # small sticker width (single and 2-up)
    "label_height_mm":  40,   # small sticker height (single and 2-up)
    "single_vgap_mm":   2,    # vertical gap between labels on the 1-up roll
    "double_vgap_mm":   2,    # vertical gap between rows on the 2-up roll
    "double_gap_mm":    1,    # horizontal gap between the two stickers (2-up)
    "double_margin_mm": 2,    # blank margin on each outer edge (2-up)
    "large_width_mm":   75,   # large (CRYSTAL CLEAR) sticker width
    "large_height_mm":  50,   # large (CRYSTAL CLEAR) sticker height
    "large_vgap_mm":    2,    # vertical gap between labels on the large roll
}

# (min, max) allowed range for each geometry field, in mm
GEOMETRY_LIMITS = {
    "label_width_mm":   (20, 100),
    "label_height_mm":  (20, 100),
    "single_vgap_mm":   (0, 20),
    "double_vgap_mm":   (0, 20),
    "double_gap_mm":    (0, 30),
    "double_margin_mm": (0, 30),
    # The large layout is drawn for 75 x 50: these are the sizes it still
    # fits (below 49 mm tall the footer lines run into each other)
    "large_width_mm":   (70, 100),
    "large_height_mm":  (49, 60),
    "large_vgap_mm":    (0, 20),
}

# ── Label text defaults ────────────────────────
# These are all mandatory declarations under FSSAI Reg 5(6)(a), 5(7) and
# Reg 10(1), so they are content settings only — there is deliberately no
# switch to hide any of them.
LABEL_TEXT_DEFAULTS = {
    "fssai_number":    "13620011000563",
    # Reg 5(6)(a): the name must be preceded by a qualifying phrase.
    "company_prefix":  "Packed & Marketed by",
    "company_name":    "SRI RADHE TRADERS",
    # Reg 5(6)(a) requires the COMPLETE address, door number included.
    "company_address": "15-7-173/A, BEGUM BAZAR, HYDERABAD, TELANGANA - 500012",
}

# ── Brand (large label only) ───────────────────
# The registered trade mark printed across the top of the 75 x 50 label.
# The mark is a setting, not hard-coded: Trade Marks Act s.107 makes it an
# offence to show (R) on a mark that is not registered, or on goods outside
# the classes it is registered for — switch to (TM) or none if that applies.
BRAND_DEFAULTS = {
    "brand_name":    "CRYSTAL CLEAR",
    "brand_mark":    "®",
    # Printed as "Customer Care: <this>". Optional — blank leaves the line off.
    "customer_care": "radhetraders.dk@gmail.com",
}

VALID_BRAND_MARKS = {"®", "™", ""}   # (R), (TM), none

# ── Date defaults ──────────────────────────────
# Use By = Packed + this many months for any product that does not set its
# own shelf life. A setting rather than a constant because it is a business
# decision: FSSAI fixes the FORMAT of the two dates, not the shelf life.
DATE_DEFAULTS = {
    "default_shelf_months": 2,
}

# (min, max) months, for both this default and a product's own shelf life
SHELF_MONTHS_LIMITS = (1, 60)

# Dropped in the FSSAI compliance pass: the two visibility toggles could
# produce a label with no licence number or no name and address, and
# company_line has been split into prefix / name / address above.
RETIRED_KEYS = ("show_fssai", "show_company_line", "company_line")

DEFAULT_SETTINGS = {
    "roll_type": "single",  # default label type: "single" | "double" | "large"
    **GEOMETRY_DEFAULTS,
    **DATE_DEFAULTS,
    **LABEL_TEXT_DEFAULTS,
    **BRAND_DEFAULTS,
}


def _coerce_mm(value, default):
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    # keep whole numbers as ints so TSPL emits "50 mm" not "50.0 mm"
    return int(num) if float(num).is_integer() else num


def _load() -> dict:
    if not os.path.exists(SETTINGS_FILE):
        _save(DEFAULT_SETTINGS.copy())
        return DEFAULT_SETTINGS.copy()
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        data = {}
    # Ensure all default keys exist
    changed = False
    for key, val in DEFAULT_SETTINGS.items():
        if key not in data:
            data[key] = val
            changed = True
    # Drop settings that no longer drive the label
    for key in RETIRED_KEYS:
        if key in data:
            del data[key]
            changed = True
    if changed:
        _save(data)
    return data


def _save(data: dict):
    # Atomic write: open(..., "w") truncates first, so an interrupted or
    # concurrent write would leave a partial file that _load() cannot parse.
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, SETTINGS_FILE)


def get_settings() -> dict:
    return _load()


def normalize_roll_type(value):
    """'single' / 'double' / 'large' from any casing, or None if it is not one of them."""
    value = (value or "").strip().lower()
    return value if value in VALID_ROLL_TYPES else None


def get_roll_type() -> str:
    """Returns the default label type: 'single', 'double' or 'large'."""
    return normalize_roll_type(_load().get("roll_type")) or "single"


def set_roll_type(value: str):
    """
    Set the default label type. Returns the normalized value on success,
    or None if the value is invalid.
    """
    value = normalize_roll_type(value)
    if value is None:
        return None
    data = _load()
    data["roll_type"] = value
    _save(data)
    return value


def get_geometry() -> dict:
    """Return all print-geometry values (mm), coerced and clamped to valid ranges."""
    data = _load()
    geo = {}
    for key, default in GEOMETRY_DEFAULTS.items():
        val = _coerce_mm(data.get(key, default), default)
        lo, hi = GEOMETRY_LIMITS[key]
        val = max(lo, min(hi, val))
        geo[key] = int(val) if float(val).is_integer() else val
    return geo


def set_geometry(updates: dict):
    """
    Update one or more geometry values. Returns (applied_dict, None) on success
    or (None, error_message) if any value is invalid / out of range.
    """
    if not updates:
        return {}, None
    data = _load()
    applied = {}
    for key, raw in updates.items():
        if key not in GEOMETRY_DEFAULTS:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None, f"Invalid value for {key}"
        lo, hi = GEOMETRY_LIMITS[key]
        if val < lo or val > hi:
            return None, f"{key.replace('_mm','').replace('_',' ')} must be between {lo} and {hi} mm"
        val = int(val) if float(val).is_integer() else val
        data[key] = val
        applied[key] = val
    _save(data)
    return applied, None


# ── Date settings ─────────────────────────────────
def get_default_shelf_months() -> int:
    """Months added to the packed date when a product sets no shelf life."""
    lo, hi = SHELF_MONTHS_LIMITS
    try:
        val = int(_load().get("default_shelf_months", DATE_DEFAULTS["default_shelf_months"]))
    except (TypeError, ValueError):
        return DATE_DEFAULTS["default_shelf_months"]
    return max(lo, min(hi, val))


def set_date_settings(updates: dict):
    """
    Update the date defaults. Returns (applied_dict, None) on success or
    (None, error_message) if a value is not a whole number in range.
    """
    if not updates:
        return {}, None
    data = _load()
    applied = {}
    lo, hi = SHELF_MONTHS_LIMITS
    for key, raw in updates.items():
        if key not in DATE_DEFAULTS:
            continue
        try:
            val = int(str(raw).strip())
        except (TypeError, ValueError):
            return None, "Default shelf life must be a whole number of months"
        if not lo <= val <= hi:
            return None, f"Default shelf life must be between {lo} and {hi} months"
        data[key] = val
        applied[key] = val
    _save(data)
    return applied, None


# ── Label text settings (FSSAI / company line) ────
def get_label_text_settings() -> dict:
    """Return the label text visibility & content settings."""
    data = _load()
    return {k: data.get(k, v) for k, v in LABEL_TEXT_DEFAULTS.items()}


def set_label_text_settings(updates: dict):
    """
    Update label text settings. Accepts any subset of LABEL_TEXT_DEFAULTS keys.
    Returns (applied_dict, None) on success or (None, error_message) on failure.
    """
    if not updates:
        return {}, None
    data = _load()
    applied = {}
    for key, raw in updates.items():
        if key not in LABEL_TEXT_DEFAULTS:
            continue
        val = str(raw).strip()
        if not val:
            # Every one of these is a mandatory declaration — blanking any
            # of them would print a non-compliant label.
            return None, f"{key.replace('_', ' ').title()} cannot be empty"
        data[key] = val
        applied[key] = val
    _save(data)
    return applied, None


# ── Brand settings (large label) ──────────────────
def set_brand_settings(updates: dict):
    """
    Update the brand name, its registration mark and the customer care line.
    Returns (applied_dict, None) on success or (None, error_message) on failure.
    """
    if not updates:
        return {}, None
    data = _load()
    applied = {}
    for key, raw in updates.items():
        if key not in BRAND_DEFAULTS:
            continue
        val = str(raw).strip()
        if key == "brand_name" and not val:
            return None, "Brand name cannot be empty"
        if key == "brand_mark" and val not in VALID_BRAND_MARKS:
            return None, "Brand mark must be ®, ™ or none"
        data[key] = val
        applied[key] = val
    _save(data)
    return applied, None
