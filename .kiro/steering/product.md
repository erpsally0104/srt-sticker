# Product Overview

SRI RADHE Label Bot is a label-printing system for **Sri Radhe Traders** (a wholesale/institutional food goods business in Begum Bazar, Hyderabad). It generates and prints product stickers on a TSC thermal label printer (TSC TE244) connected over USB to a Windows machine.

## Two ways to use it

1. **Telegram bot** (`bot.py`) — Authorized users send text messages in a simple format to print labels. Admins manage users and products via slash commands.
2. **Web UI** (`index.html` / `ui.html` + `server.py`) — A PWA-style web app backed by a Flask API with JWT login. Exposed publicly via an ngrok tunnel.

Both front-ends share the same parsing, printing, batch-numbering, and queue logic.

## What a label contains

- Product name, weight
- Packed On date, Best Before date
- Batch number (auto-generated)
- QR code encoding all label details
- FSSAI license number and company address
- "Not For Retail Sale | For Institutional Sale Only"

There is also an **ingredients-only** sticker type that fills the label with auto-sized ingredient text, and an **FSSAI logo** sticker type that prints only the FSSAI logo with a 14-digit licence number beneath it (`13620011000563 ;; f 5` on Telegram). Neither takes a batch number or appears in the print history.

## Key business rules

- **Batch number format**: `SRT{DDMMYY}{3-digit sequence}` (e.g. `SRT020426001`), sequence resets daily.
- **Date defaults**: Packed On = today; Use By = Packed On + the product's shelf life (`shelf_months`, 3 when not set). In the web UI, Use By follows each product's shelf life until the operator picks one by hand, which then applies to every item.
- **No guessed weights**: a product that isn't in the list must be given a weight; it is refused otherwise (the net quantity is a mandatory declaration).
- **Date inputs** accept: `today`, `today + N months/days/years`, `DD/MM/YYYY`, `DD-MM-YYYY`, `DD/MM/YY`.
- **Weight auto-units**: a bare number < 100 becomes KGS, >= 100 becomes GMS; explicit units are respected.
- **Products are scoped per "hotel"** (client/institution). `general` is the default hotel; product weights fall back to `general` when not found for a specific hotel.
- **Quantity limits**: 1–500 per request. Quantities > 50 trigger a confirmation prompt in the Telegram flow.
- **Roll type**: the printer can hold a single-label roll or a 2-up roll (two labels side by side). Operators select the loaded roll type in the UI (or via `/rolltype`); on a 2-up roll, queued labels are printed two per row (different products can share a row), doubling throughput.
- **Authorization**: Telegram uses `users.json` (admin + authorized usernames). Web UI uses a SQLite users table with bcrypt passwords and JWT tokens.
