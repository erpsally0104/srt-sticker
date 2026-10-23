# Product Overview

SRI RADHE Label Bot is a label-printing system for **Sri Radhe Traders** (a wholesale/institutional food goods business in Begum Bazar, Hyderabad). It generates and prints product stickers on a TSC thermal label printer (TSC TE244) connected over USB to a Windows machine.

## Two ways to use it

1. **Telegram bot** (`bot.py`) — Authorized users send text messages in a simple format to print labels. Admins manage users and products via slash commands.
2. **Web UI** (`index.html` / `ui.html` + `server.py`) — A PWA-style web app backed by a Flask API with JWT login. Exposed publicly via an ngrok tunnel.

Both front-ends share the same parsing, printing, batch-numbering, and queue logic.

## What a label contains

- Product name (in English, with the familiar Indian name in brackets where needed, e.g. `SEMOLINA (RAVA)`), weight
- Allergen line, `CONTAINS: ...`, for products that set allergens (both label sizes)
- Packed On date, Best Before date
- Batch number (auto-generated)
- QR code encoding all label details
- FSSAI license number and company address
- "Not For Retail Sale | For Institutional Sale Only"

The **large 75 × 50 mm label** adds the registered brand **CRYSTAL CLEAR®** (white on black across the top, beside the pre-printed green veg mark), a storage line, and a customer care line. Its brand name, ® / ™ / none, and customer care contact are admin-only settings.

There is also an **ingredients-only** sticker type that fills the label with auto-sized ingredient text, and an **FSSAI logo** sticker type that prints only the FSSAI logo with a 14-digit licence number beneath it (`13620011000563 ;; f 5` on Telegram). Neither takes a batch number or appears in the print history.

## Key business rules

- **Batch number format**: `SRT{DDMMYY}{3-digit sequence}` (e.g. `SRT020426001`), sequence resets daily.
- **Date defaults**: Packed On = today; Use By = Packed On + the product's shelf life (`shelf_months`), falling back to the `default_shelf_months` setting (2 months, configurable in Settings → Dates). In the web UI, Use By follows each product's shelf life until the operator picks one by hand, which then applies to every item.
- **No guessed weights**: a product that isn't in the list must be given a weight; it is refused otherwise (the net quantity is a mandatory declaration).
- **English names, old names still work**: every product prints under its English name. Its older and local names are kept as aliases (PHALLI → PEANUTS), and a small typo is tolerated, so operators type what they are used to. Typo matching is deliberately narrow because the wrong product means the wrong weight and allergens: same first letter, digits identical, one best match only, and below 7 letters only a missing/extra/swapped letter (PASTA never becomes PISTA). It is never applied when the line states a weight (the product may be new), nor to rows the UI fills itself (History reprints, restored drafts).
- **Removing by another name is refused** (it names the product instead): old duplicate entries were folded into one product, so removing an alias would delete it.
- **Print as typed** (web UI, per item): prints the name exactly as typed, with no English swap and no other-name or typo correction. A name the list knows (its own or an alias) still brings that product's weight, shelf life and allergens; a typo does not, so it needs a weight like any unlisted product. History records it (`print_logs.as_typed`) so a reprint does the same.
- **Date inputs** accept: `today`, `today + N months/days/years`, `DD/MM/YYYY`, `DD-MM-YYYY`, `DD/MM/YY`.
- **Weight auto-units**: a bare number < 100 becomes KGS, >= 100 becomes GMS; explicit units are respected.
- **Products are scoped per "hotel"** (client/institution). `general` is the default hotel; product weights fall back to `general` when not found for a specific hotel.
- **Quantity limits**: 1–500 per request. Quantities > 50 trigger a confirmation prompt in the Telegram flow.
- **Label type** (a.k.a. roll type): `single` (one 50×40 label per row), `double` (2-up: two 50×40 labels side by side) or `large` (one 75×50 CRYSTAL CLEAR label per row). Every print job carries its own type, picked on the web UI's Print tab. The **default label type** (Settings tab, or `/rolltype`) is what the Print tab starts on and what every Telegram print uses. On a 2-up roll, consecutive queued 2-up labels print two per row (different products can share a row), doubling throughput.
- **Authorization**: Telegram uses `users.json` (admin + authorized usernames). Web UI uses a SQLite users table with bcrypt passwords and JWT tokens.
