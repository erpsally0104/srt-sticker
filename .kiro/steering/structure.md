# Project Structure

Flat, single-directory Python project. All modules live in the repo root; there are no packages or subfolders for source code.

## Module map

| File | Responsibility |
|------|----------------|
| `bot.py` | Telegram bot entry point. Command handlers, message handling, high-quantity confirmation flow. |
| `server.py` | Flask API entry point. JWT-protected endpoints for the web UI (login, print, products, queue, logs, status). |
| `parser.py` | `parse_message()` + `PrintRequest` dataclass. Turns text lines into print requests; handles dates, weights, and ingredients format. |
| `printer.py` | Renders labels to Pillow images, converts to TSPL bitmaps, prints via `win32print`. Also `get_printer_status()`. |
| `print_queue.py` | Thread-safe singleton `PrintQueue` with a background worker. Jobs are queued, printed one at a time, and cancellable; failed jobs can be retried (same batch number) or dismissed. |
| `batch_manager.py` | `get_next_batch_number()` — daily-resetting sequential batch numbers. |
| `product_manager.py` | CRUD over `products.json`, hotel-scoped, with flat→grouped and English-name auto-migrations. An entry is a weight string, or `{"weight", "shelf_months", "aliases", "allergens"}` with only the keys it uses. `lookup_product()` / `resolve_name()` find a product by name, alias or small typo, falling back to `general`; a hotel entry without its own aliases/allergens uses General's. |
| `product_catalog.py` | Seed table of English names, aliases and allergens, and the one-time migration that applies it (`python product_catalog.py` dry-runs it). |
| `templates_manager.py` | Saved ingredient texts over `ingredient_templates.json`. |
| `user_manager.py` | Telegram auth over `users.json` (admin + authorized users). |
| `settings_manager.py` | App settings over `settings.json`: the default label type `roll_type` (`single` / `double` / `large`), print geometry (small and large label sizes, gaps, margins), `default_shelf_months` (the Use By fallback), label text and brand settings, each validated. |
| `auth.py` | Web UI auth: SQLite users, bcrypt, JWT access/refresh tokens. |
| `logger.py` | Print audit log in the `print_logs` SQLite table. |
| `index.html`, `ui.html`, `sw.js`, `manifest.json`, `icon.png` | PWA web front-end assets. |
| `*.json`, `users.db` | Runtime data/state (auto-managed, not hand-edited). |

## Architectural conventions

- **Shared core, two front-ends.** `bot.py` (Telegram) and `server.py` (Flask) are thin adapters over the same core modules (`parser`, `printer`, `print_queue`, `*_manager`, `logger`). Put shared logic in the core modules, not in the front-ends.
- **All printing goes through the queue.** Front-ends call `get_queue().add_batch(reqs, username, source)` (atomic multi-line submit) rather than calling `print_label()` directly. `source` is `"telegram"` or `"ui"`. The background worker handles actual printing, logging, and cleanup. Each job's `req.roll_type` is fixed when it is queued (blank → the default label type). The worker takes jobs FIFO: a `single` or `large` job prints on its own; a `double` job prints 2-up together with the `double` jobs queued straight after it.
- **Data-manager pattern.** JSON-backed modules use private `_load()` / `_save()` helpers and return user-facing status strings (often with emoji + Markdown) rather than raising. SQLite modules open a connection per call via `get_db()`.
- **`PrintRequest` is the common currency.** Everything downstream of parsing operates on `PrintRequest` (fields include `product`, `weight`, `quantity`, `packed_on`, `best_before`, `hotel`, `label_type`, `ingredients`, `fssai_number`, `roll_type`, `allergens`, `requested_as`, `as_typed`). `label_type` is `"product"`, `"ingredients"` or `"fssai"`; only `"product"` labels get a batch number and a print-log row. `roll_type` is the label size/roll (`"single"`, `"double"`, `"large"`) — a separate axis from `label_type`.
- **Normalization rules.** Products are stored/compared UPPERCASE, and names/aliases match ignoring spaces and punctuation (`product_catalog.norm()`); hotels and usernames lowercase; usernames have leading `@` stripped. The browser's product resolver in `index.html` mirrors `resolve_name()` — change both together.
- **Singletons.** The print queue is a module-level singleton accessed via `get_queue()`.

## Conventions to follow when editing

- Match the existing style: section-divider comments (`# ───...───`), emoji in user-facing messages, `parse_mode="Markdown"` for Telegram replies.
- Keep the module layout flat — don't introduce packages unless there's a clear reason.
- When adding a label field, update the QR data string, the image layout in `printer.py`, and the `PrintRequest` dataclass together.
- Return status strings from manager functions rather than raising for expected user errors; reserve exceptions for truly unexpected failures.
