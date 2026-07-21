import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

VALID_ROLL_TYPES = {"single", "double"}
DEFAULT_SETTINGS = {
    "roll_type": "single",  # "single" (1 label per row) | "double" (2 labels side by side)
}


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
