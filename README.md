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

## Document printing (Docs tab)

The **Docs** tab in the web UI prints a PDF, a photo, or a Word / Excel / PowerPoint file on one
of the shop computer's printers (normally the HP), from anywhere the web UI opens. Files print
one at a time, separately from labels, and never on the label printer.

- **Printer:** picked from the printers installed on the shop computer. The tab starts on the
  default one (**Settings → Document Printer**; automatic picks the first printer with "HP" in
  its name).
- **Options:** copies (1 to 99), pages (e.g. `1-3, 5`, or `4-` for 4 to the end), two-sided
  (only on a printer that can), colour or black & white (only on a colour printer), and
  orientation (Auto follows the first page).
- **File or link:** upload a file, or paste a public link to one. The shop computer downloads
  it. Google Drive, Google Docs / Sheets / Slides and Dropbox share links work when they are
  shared with anyone who has the link. Links into the shop's own network (the router, the
  printers, this computer) are refused, including through a redirect.

### Setup on the shop computer
1. `pip install -r requirements.txt` (adds `pypdfium2`, which draws the PDF pages, and
   `certifi`, the certificate list used when downloading from a link).
2. For Word, Excel and PowerPoint files, install **LibreOffice** (free, from libreoffice.org).
   Without it, PDFs and photos still print, and the Docs tab says the other files need it.
3. Install the HP printer in Windows. If the automatic default is wrong, pick the right one
   under **Settings → Document Printer**.

### Keeping the printer reachable while it sleeps
An HP printer on Wi-Fi goes to sleep after a few minutes without work. Sleep itself is fine.
These steps stop it from dropping off the network or switching itself off:

1. **Fixed address.** Reserve the printer's IP address in the router (DHCP reservation), so it
   keeps the same address after every restart.
2. **Standard TCP/IP port.** In Windows: Printers & scanners → the HP → Printer properties → Ports.
   If the ticked port starts with `WSD`, click **Add Port → Standard TCP/IP Port**, enter the
   printer's IP address, and tick the new port. WSD ports lose the printer when it sleeps.
   Then **Configure Port** → untick **SNMP Status Enabled**, so Windows doesn't mark a sleeping
   printer offline.
3. **Never shut down.** Open the printer's own web page (type its IP address into a browser) and
   find the energy or power settings (the exact names vary by model and firmware). Set
   **Shut Down After Inactivity** to **Never**, or turn on **Delay Shutdown When Ports Are Active**,
   and set **Sleep After Inactivity** to the longest time offered. The same settings are on the
   printer's screen under Setup → Energy Settings. Once the printer has shut down, nothing can
   wake it over the network.
4. **Firmware.** Install the printer's firmware updates (from its web page or its screen).
5. If it still drops off Wi-Fi while asleep, connect it to the router with an **Ethernet** cable,
   or to the shop computer by **USB**. Wired connections don't have this Wi-Fi sleep problem.
6. The shop computer must not sleep either (Windows Settings → System → Power → Sleep: Never),
   or the bot, the server and the tunnel stop with it.

What the server does about sleep:
- Before each file it knocks on the printer (opens a TCP connection to its print port) until the
  printer answers, for up to 45 seconds, then sends the file to Windows. If the printer never
  answered, Windows keeps the file and prints it as soon as the printer is back, and the Docs tab
  shows it waiting.
- Every 2 minutes it knocks again (Settings → Document Printer → Keep-awake check; 0 turns it off).
  This keeps the printer's Wi-Fi connection in use, and the Docs tab shows when the printer
  stopped answering. The **Wake** button on the Docs tab knocks straight away.
- It follows each file in the Windows print queue until the printer has taken it, and the Docs
  tab says why a file is waiting (printer asleep, out of paper, paused).

Limits: 25 MB per file (uploaded or downloaded), 1 to 99 copies, 300 pages per copy. With Auto
orientation, a page the other way round from the first one is turned to fill the paper. Pages
bigger than the paper are shrunk to fit it, and photos fill the page.

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
| Use By | Packed On + the product's shelf life, or the default shelf life from Settings (2 months) when it sets none |
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
