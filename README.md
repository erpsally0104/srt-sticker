# SRI RADHE Label Bot 🖨️

Telegram bot that prints labels on a TSC printer via USB.

---

## Setup Instructions

### Step 1 — Install Python dependencies
```
pip install -r requirements.txt
```

### Step 2 — Get your Telegram Bot Token
1. Open Telegram → search **@BotFather**
2. Send `/newbot`
3. Follow prompts → copy the token
4. Paste it in `bot.py` where it says `YOUR_BOT_TOKEN_HERE`

### Step 3 — Set your printer name
1. Open Windows → **Devices & Printers**
2. Find your TSC printer → right-click → **Printer properties** → copy the exact name
3. Paste it in `printer.py` where it says `PRINTER_NAME = "TSC TTP-244 Pro"`

### Step 4 — Adjust label size (if needed)
In `printer.py`, update these values to match your sticker size:
```python
LABEL_WIDTH_MM  = 100   # width of sticker in mm
LABEL_HEIGHT_MM = 60    # height of sticker in mm
GAP_MM          = 3     # gap between stickers
```

### Step 5 — Add the FSSAI logo artwork
FSSAI Reg 5(7)(a) requires the **logo** on the label, not just the licence number.
The mark is a certification mark, so it is loaded from a file and never drawn in code.

1. Download the official logo from **fssai.gov.in**
2. Save it as **`fssai_logo.png`** in this folder (beside `printer.py`)
3. A wordmark around 2.5:1 (width:height) sits best on the licence line; transparent PNG is fine

It is picked up on the next label without restarting. Until the file is added, the
label falls back to a text-only `FSSAI Lic. No. ...` line so printing never stops.

---

### Step 6 — Run the bot
```
python bot.py
```

---

## Usage

### Print a label
```
PHALLI | 10
TOOR DAL | 5 | 1 KG
```

### Commands
| Command | Who | Description |
|---|---|---|
| /start | All | Welcome message |
| /help | All | Show commands |
| /status | Authorized | Check printer status |
| /listproducts | Authorized | Show product list |
| /adduser @username | Admin | Authorize a user |
| /removeuser @username | Admin | Remove a user |
| /listusers | Admin | List authorized users |
| /addproduct PRODUCT WEIGHT | Admin | Add/update product |
| /removeproduct PRODUCT | Admin | Remove product |

---

## Auto-generated fields
| Field | Logic |
|---|---|
| Packed On | Today's date |
| Use By | Packed On + the product's shelf life (3 months if not set) |
| Batch No | SRT + DDMMYY + 3-digit sequence (e.g. SRT020426001) |

---

## File Structure
```
label-bot/
├── bot.py              ← Main bot
├── printer.py          ← TSPL + win32print
├── parser.py           ← Message parsing
├── user_manager.py     ← User auth
├── product_manager.py  ← Product weights
├── batch_manager.py    ← Batch number generation
├── users.json          ← Authorized users (auto-managed)
├── products.json       ← Product weights (auto-managed)
├── batch.json          ← Daily batch counter (auto-managed)
└── requirements.txt
```
