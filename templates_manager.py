"""
Saved ingredient texts, so an operator picks one instead of retyping it.

Stored as {name: text} in ingredient_templates.json beside this module.
"""

import json
import os

TEMPLATES_FILE = os.path.join(os.path.dirname(__file__), "ingredient_templates.json")

MAX_NAME_LEN = 40
MAX_TEXT_LEN = 2000


def _load() -> dict:
    try:
        with open(TEMPLATES_FILE, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict):
    # Atomic write, as in settings_manager: bot.py and server.py are two
    # processes, and a truncated file would lose every template.
    tmp = TEMPLATES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, TEMPLATES_FILE)


def list_templates() -> list:
    """[{name, text}, ...] sorted by name."""
    data = _load()
    return [{"name": k, "text": data[k]} for k in sorted(data, key=str.lower)]


def save_template(name: str, text: str):
    """Add or overwrite a template. Returns (ok, message)."""
    name = (name or "").strip()
    text = (text or "").strip()
    if not name:
        return False, "Template name is required"
    if len(name) > MAX_NAME_LEN:
        return False, f"Template name must be {MAX_NAME_LEN} characters or fewer"
    if not text:
        return False, "Ingredients text is empty"
    if len(text) > MAX_TEXT_LEN:
        return False, f"Ingredients text must be {MAX_TEXT_LEN} characters or fewer"
    if ";;" in text:
        return False, "Ingredients text cannot contain ';;'"
    data = _load()
    # Saving under an existing name in different case replaces it
    for k in [k for k in data if k.lower() == name.lower()]:
        del data[k]
    data[name] = text
    _save(data)
    return True, f"Saved '{name}'"


def remove_template(name: str) -> bool:
    data = _load()
    keys = [k for k in data if k.lower() == (name or "").strip().lower()]
    if not keys:
        return False
    for k in keys:
        del data[k]
    _save(data)
    return True
