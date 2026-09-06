import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

VALID_ROLL_TYPES = {"single", "double"}

# ── Print geometry (all values in mm) ─────────
GEOMETRY_DEFAULTS = {
    "label_width_mm":   50,   # sticker width (both rolls)
    "label_height_mm":  40,   # sticker height (both rolls)
    "single_vgap_mm":   2,    # vertical gap between labels on the 1-up roll
    "double_vgap_mm":   2,    # vertical gap between rows on the 2-up roll
    "double_gap_mm":    1,    # horizontal gap between the two stickers (2-up)
    "double_margin_mm": 2,    # blank margin on each outer edge (2-up)
}

# (min, max) allowed range for each geometry field, in mm
GEOMETRY_LIMITS = {
    "label_width_mm":   (20, 100),
    "label_height_mm":  (20, 100),
    "single_vgap_mm":   (0, 20),
    "double_vgap_mm":   (0, 20),
    "double_gap_mm":    (0, 30),
    "double_margin_mm": (0, 30),
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

# Dropped in the FSSAI compliance pass: the two visibility toggles could
# produce a label with no licence number or no name and address, and
# company_line has been split into prefix / name / address above.
RETIRED_KEYS = ("show_fssai", "show_company_line", "company_line")

DEFAULT_SETTINGS = {
    "roll_type": "single",  # "single" (1 label per row) | "double" (2 labels side by side)
    **GEOMETRY_DEFAULTS,
    **LABEL_TEXT_DEFAULTS,
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
    with open(SETTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_settings() -> dict:
    return _load()


def get_roll_type() -> str:
    """Returns the currently loaded roll type: 'single' or 'double'."""
    roll_type = _load().get("roll_type", "single")
    return roll_type if roll_type in VALID_ROLL_TYPES else "single"


def set_roll_type(value: str):
    """
    Set the roll type. Returns the normalized value on success,
    or None if the value is invalid.
    """
    value = (value or "").strip().lower()
    if value not in VALID_ROLL_TYPES:
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
