# Technology Stack

## Language & runtime

- **Python 3** (uses `str | None` syntax, so 3.10+). Runs on **Windows** — the printer integration depends on `pywin32` / `win32print` and Windows font paths.
- A local virtualenv lives in `.venv`.

## Key libraries

- `python-telegram-bot==21.3` — async Telegram bot (v21 API, `ApplicationBuilder`, async handlers).
- `flask` + `flask-cors` — Web API server.
- `pyjwt` — JWT access/refresh tokens for the web UI.
- `bcrypt` — password hashing for web UI users.
- `pywin32` — raw printing to the TSC printer via `win32print`.
- `Pillow` — renders the label as a bitmap image.
- `qrcode` — QR code generation.
- `python-dateutil` — `relativedelta` for date math.
- `python-dotenv` — loads `BOT_TOKEN` from `.env`.
- `pypdfium2` — renders PDF pages for the Docs tab (PDFium is not thread-safe: only the document worker thread calls it).
- `certifi` — CA certificates for downloading Docs-tab links (urllib with Windows' store alone fails on some sites). Link downloads use a stdlib urllib opener with no proxy, http(s) only, and a check on every connection's peer address that refuses non-public IPs, so a link or redirect can't reach the shop's LAN.
- **LibreOffice** (optional, installed on the shop computer, not pip) — converts Word / Excel / PowerPoint / text files to PDF for the Docs tab. Without it those files are refused with a message; PDFs and photos still print.

## Data stores

- **JSON files** (auto-managed, in repo root):
  - `users.json` — Telegram admin + authorized usernames.
  - `products.json` — hotel-grouped product → weight map; an entry may also hold shelf life, aliases, allergens, and the ingredients & nutrition saved from the Print tab.
  - `batch.json` — daily batch counter (`{"date": "DDMMYY", "counter": N}`).
  - `settings.json` — app settings: the default label type `roll_type` (`single` | `double` | `large`) plus print geometry in mm (`label_width_mm`, `label_height_mm`, `single_vgap_mm`, `double_vgap_mm`, `double_gap_mm`, `double_margin_mm`, `large_width_mm`, `large_height_mm`, `large_vgap_mm`, and a per-roll print offset `{single,double,large}_offset_{x,y}_mm`, −3 to 3), print quality (`print_density` 0–15, `print_speed` 2–6 in/s), label text (`fssai_number`, `company_prefix`, `company_name`, `company_address`, and the non-retail statement `non_retail_text`), brand (`brand_name`, `brand_mark`, `customer_care`), and the Docs tab's office printer (`doc_printer`, blank = the first HP printer; `doc_keepalive_minutes` 0–30, 0 = off), all editable from the UI Settings tab.
- **SQLite** (`users.db`): `users` table (web UI login, bcrypt) and `print_logs` table (audit log). Tables are created on import/startup via `init_db()` / `init_logs_table()`.

## Printing

- Output is **TSPL** (TSC Printer Language) sent as RAW data to the printer.
- Default label size is **50mm × 40mm at 203 DPI**. `PRINTER_NAME` in `printer.py` must match the exact Windows printer name. Geometry (label size, gaps, margins) lives in `settings.json` and is applied per-print via `printer._apply_geometry()`, which refreshes the module globals from settings on the single queue-worker thread. The module-level constants are just fallback defaults.
- Labels are drawn as a Pillow image, converted to a 1-bit TSPL `BITMAP` command, then printed. Every job's header sends `SPEED` and `DENSITY` from settings, and the bitmap is moved by the roll's print offset before it is sent (previews are never offset).
- **Three label types**, chosen per print (default in `settings.json`, set from the UI Settings tab or `/rolltype`): `single` prints one label per row (`SIZE 50 mm, 40 mm`); `double` is a 2-up roll that prints two labels side by side per row (`SIZE 105 mm, 40 mm`, laid out as 2mm margin + 50mm + 1mm gap + 50mm + 2mm margin); `large` prints one 75×50 label per row (`SIZE 75 mm, 50 mm`) with its own layout, `build_large_label_image()`. The queue worker flattens consecutive 2-up jobs and prints them two per row, so two *different* products can share a row; an odd final label prints alone with the right column blank. Ingredients and FSSAI logo stickers size themselves to whichever label they are printed on. So does a product's ingredients & nutrition sticker (`build_info_label_image()`): flush left, clear of the pre-printed veg mark, one text size for everything (the largest that fits, never below 12 px, about 1.1 mm capitals), saturated/trans fat rows left out at 0.5 g fat or less. On a single or large roll each pair is sent as two forms per label (`PRINT 1,1` each), so the data sent grows with the quantity.
- The large label's brand uses Copperplate Gothic Bold (an MS Office font), falling back to Georgia Bold (ships with Windows).
- **Documents (Docs tab)** print on an ordinary Windows printer picked per job (default: the office HP) through GDI, not TSPL: each page becomes a bitmap at up to 300 DPI (grayscale on a mono printer or for black & white), centred inside the printable area. Orientation `auto` sets the paper from the first page and turns any page the other way round; `portrait` / `landscape` draw every page upright. Copies, two-sided (`DMDUP_VERTICAL` = long edge), colour and orientation go in the DEVMODE. The driver makes the copies when `DeviceCapabilities` says it can (collated for multi-page files); otherwise the pages are sent once per copy, with a blank back between two-sided copies that end on a front. Before each job the worker knocks on the printer's IP (TCP connect to its print port, then 631 and 80) for up to 45 s to wake it; the IP comes from the Windows port (Standard TCP/IP registry key, an IPP URL, or an IP in the port name), so a WSD port gives no knock. Printers that would open a dialog (`PORTPROMPT:`, `FILE:`, OneNote, Fax) are never offered.
- All other label text uses **Bahnschrift** (a variable font in Windows 10 and later), falling back to Arial. A face is a `(file, style)` pair passed to `printer.get_font()`, e.g. `TEXT_BOLD_SC = (FONT_TEXT, "Bold SemiCondensed")`. Product names go through `_draw_name()`: narrowed through Bold → SemiCondensed → Condensed before shrinking, a trailing bracketed familiar name set at 0.7×, and squeezed sideways as a last resort, so a name never leaves its box. Net weights go through `_weight_parts()`, which sets the unit at 0.65× the number.

## Configuration that must be edited per-deployment

- `BOT_TOKEN` — set in `.env`.
- `PRINTER_NAME` in `printer.py`.
- `ADMIN_USER` in `server.py` and `SECRET_KEY` in `auth.py`.
- Hard-coded paths in `run.bat` and the ngrok domain.

## Common commands (Windows / cmd)

```
pip install -r requirements.txt   # install deps
python bot.py                     # run the Telegram bot
python server.py                  # run the Flask UI API on :5000
run.bat                           # start bot + server + ngrok + open UI
```

There is no test suite or linter configured. Do not add one unless asked.

## Security notes (be careful here)

- `SECRET_KEY` in `auth.py` and default admin credentials are hard-coded — flag before committing changes that expose them further.
- The web server binds `0.0.0.0:5000` and is exposed via ngrok; CORS is intentionally permissive.
- Treat `.env`, `users.db`, and `*.json` credential/state files as sensitive.
