import json
import os

USERS_FILE = os.path.join(os.path.dirname(__file__), "users.json")


def _load() -> dict:
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        # A corrupt users.json must not lock every operator out of the bot
        print("⚠️  users.json is unreadable — treating as empty until it is fixed")
        return {}


def _save(data: dict):
    # Atomic write: open(..., "w") truncates first, so an interrupted or
    # concurrent write would leave a partial file that _load() cannot parse.
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, USERS_FILE)


def is_admin(username: str) -> bool:
    return _load()["admin"].lower() == username.lower().lstrip("@")


def is_authorized(username: str) -> bool:
    data = _load()
    normalized = username.lower().lstrip("@")
    return normalized in [u.lower() for u in data["authorized_users"]]


def add_user(username: str) -> str:
    username = username.lower().lstrip("@")
    data = _load()
    if username in [u.lower() for u in data["authorized_users"]]:
        return f"⚠️ @{username} is already authorized."
    data["authorized_users"].append(username)
    _save(data)
    return f"✅ @{username} has been authorized."


def remove_user(username: str) -> str:
    username = username.lower().lstrip("@")
    data = _load()

    if username == data["admin"].lower():
        return "⛔ Cannot remove the admin."

    normalized_list = [u.lower() for u in data["authorized_users"]]
    if username not in normalized_list:
        return f"⚠️ @{username} is not in the authorized list."

    data["authorized_users"] = [
        u for u in data["authorized_users"] if u.lower() != username
    ]
    _save(data)
    return f"✅ @{username} has been removed."


def list_users() -> str:
    data = _load()
    users = data["authorized_users"]
    if not users:
        return "No authorized users."
    lines = [f"👥 *Authorized Users:*"]
    for u in users:
        tag = " _(admin)_" if u.lower() == data["admin"].lower() else ""
        lines.append(f"  • @{u}{tag}")
    return "\n".join(lines)
