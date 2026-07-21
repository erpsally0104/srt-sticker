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

## Data stores

- **JSON files** (auto-managed, in repo root):
  - `users.json` — Telegram admin + authorized usernames.
  - `products.json` — hotel-grouped product → weight map.
  - `batch.json` — daily batch counter (`{"date": "DDMMYY", "counter": N}`).
  - `settings.json` — app settings: `roll_type` (`single` | `double`) plus print geometry in mm (`label_width_mm`, `label_height_mm`, `single_vgap_mm`, `double_vgap_mm`, `double_gap_mm`, `double_margin_mm`), all editable from the UI Settings tab.
- **SQLite** (`users.db`): `users` table (web UI login, bcrypt) and `print_logs` table (audit log). Tables are created on import/startup via `init_db()` / `init_logs_table()`.

## Printing

- Output is **TSPL** (TSC Printer Language) sent as RAW data to the printer.
- Default label size is **50mm × 40mm at 203 DPI**. `PRINTER_NAME` in `printer.py` must match the exact Windows printer name. Geometry (label size, gaps, margins) lives in `settings.json` and is applied per-print via `printer._apply_geometry()`, which refreshes the module globals from settings on the single queue-worker thread. The module-level constants are just fallback defaults.
- Labels are drawn as a Pillow image, converted to a 1-bit TSPL `BITMAP` command, then printed.
- **Two roll types** (selected in the UI / `/rolltype`, persisted in `settings.json`): `single` prints one label per row (`SIZE 50 mm, 40 mm`); `double` is a 2-up roll that prints two labels side by side per row (`SIZE 105 mm, 40 mm`, laid out as 2mm margin + 50mm + 1mm gap + 50mm + 2mm margin). In double mode the queue worker flattens all queued labels and prints them two per row, so two *different* products can share a row; an odd final label prints alone with the right column blank.

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
