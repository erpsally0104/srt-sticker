import json
import os
from datetime import datetime

BATCH_FILE = os.path.join(os.path.dirname(__file__), "batch.json")


def get_next_batch_number() -> str:
    """
    Generates the next batch number in format SRT{DDMMYY}{3-digit sequence}.
    Resets counter every day.
    Example: SRT020426001, SRT020426002, ...
    """
    today = datetime.now().strftime("%d%m%y")

    with open(BATCH_FILE, "r") as f:
        data = json.load(f)

    # Reset counter if it's a new day
    if data["date"] != today:
        data["date"] = today
        data["counter"] = 0

    data["counter"] += 1

    with open(BATCH_FILE, "w") as f:
        json.dump(data, f, indent=2)

    return f"SRT{today}{data['counter']:03d}"
