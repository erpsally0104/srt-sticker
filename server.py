import io
from datetime import datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
from functools import wraps

from auth import (init_db, verify_user, generate_tokens, verify_access_token,
                  verify_refresh_token, change_password)
from logger import log_print, get_logs, get_all_usernames
from parser import parse_message, format_date_pair, PrintRequest
from printer import print_label, render_label, get_printer_status, check_printer
from batch_manager import get_next_batch_number
from print_queue import get_queue
from product_manager import (
    add_product, remove_product, update_product, add_hotel, list_hotels,
    hotel_entries, all_hotel_entries, validate_shelf_months,
)
from settings_manager import (
    get_settings, get_roll_type, set_roll_type, set_geometry, GEOMETRY_DEFAULTS,
    get_label_text_settings, set_label_text_settings, LABEL_TEXT_DEFAULTS,
)
from templates_manager import list_templates, save_template, remove_template

app = Flask(__name__)
CORS(app)

ALLOWED_ORIGINS = [
    "https://srt-labels.github.io",
    "http://localhost",
    "http://127.0.0.1",
    "null",   # local file:// opens as null origin
]

@app.after_request
def add_headers(response):
    origin = request.headers.get("Origin", "")
    # Allow any origin that matches our list, or any localhost/file
    if origin in ALLOWED_ORIGINS or "localhost" in origin or "127.0.0.1" in origin or not origin:
        response.headers["Access-Control-Allow-Origin"]  = origin or "*"
    else:
        response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Headers"]  = "Authorization, Content-Type, ngrok-skip-browser-warning"
    response.headers["Access-Control-Allow-Methods"]  = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["ngrok-skip-browser-warning"]    = "true"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return "", 204

init_db()

ADMIN_USER = "shubhamagarwal25"


# ── Auth decorator ────────────────────────────────
def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401
        token    = auth_header.split(" ", 1)[1]
        username = verify_access_token(token)
        if not username:
            return jsonify({"error": "Token expired or invalid"}), 401
        request.username = username
        return f(*args, **kwargs)
    return decorated


def is_admin():
    return getattr(request, "username", "") == ADMIN_USER


# ── Auth endpoints ────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    body     = request.get_json()
    username = (body.get("username") or "").strip()
    password = (body.get("password") or "").strip()
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if not verify_user(username, password):
        return jsonify({"error": "Invalid username or password"}), 401
    tokens = generate_tokens(username)
    tokens["username"] = username
    tokens["is_admin"] = username == ADMIN_USER
    return jsonify(tokens)


@app.route("/api/refresh", methods=["POST"])
def refresh():
    body          = request.get_json()
    refresh_token = (body.get("refresh_token") or "").strip()
    username      = verify_refresh_token(refresh_token)
    if not username:
        return jsonify({"error": "Refresh token expired, please log in again"}), 401
    tokens = generate_tokens(username)
    tokens["username"] = username
    tokens["is_admin"] = username == ADMIN_USER
    return jsonify(tokens)


# ── Protected endpoints ───────────────────────────
@app.route("/api/change-password", methods=["POST"])
@require_auth
def api_change_password():
    """
    Change your OWN password. Deliberately not an admin function: it acts on
    request.username from the token, so nobody can set anyone else's password
    by passing a different name in the body.
    """
    body = request.get_json() or {}
    ok, err = change_password(
        request.username,
        (body.get("current_password") or ""),
        (body.get("new_password") or ""),
    )
    if not ok:
        return jsonify({"error": err}), 400

    # Existing tokens keep working: there is no revocation list, and the
    # signing key is shared, so re-issuing here at least hands the caller a
    # fresh pair rather than leaving them on ones minted before the change.
    tokens = generate_tokens(request.username)
    tokens["username"] = request.username
    tokens["is_admin"] = request.username == ADMIN_USER
    return jsonify(tokens)


@app.route("/api/status", methods=["GET"])
@require_auth
def status():
    online, message = check_printer()
    return jsonify({"status": message, "online": online})


# ── Settings (roll type) ──────────────────────────
@app.route("/api/settings", methods=["GET"])
@require_auth
def get_app_settings():
    return jsonify(get_settings())


@app.route("/api/settings", methods=["POST"])
@require_auth
def update_app_settings():
    body = request.get_json() or {}

    # The FSSAI number, company name and address are legal declarations on
    # every label, so only the admin may change them. Checked before any
    # write so a refused request changes nothing. Values sent unchanged are
    # let through: the settings form posts every field on each save.
    text_updates = {k: body[k] for k in body if k in LABEL_TEXT_DEFAULTS}
    if text_updates and not is_admin():
        current = get_label_text_settings()
        if any(str(v).strip() != current.get(k) for k, v in text_updates.items()):
            return jsonify({"error": "Only the admin can change the FSSAI number, company name and address"}), 403
        text_updates = {}

    # Roll type (optional)
    if "roll_type" in body:
        if set_roll_type(body.get("roll_type")) is None:
            return jsonify({"error": "Invalid roll_type (use 'single' or 'double')"}), 400

    # Print geometry (optional)
    geo_updates = {k: body[k] for k in body if k in GEOMETRY_DEFAULTS}
    if geo_updates:
        applied, err = set_geometry(geo_updates)
        if err:
            return jsonify({"error": err}), 400

    # Label text settings (FSSAI / company line) (optional)
    if text_updates:
        applied, err = set_label_text_settings(text_updates)
        if err:
            return jsonify({"error": err}), 400

    return jsonify(get_settings())


# ── Products ──────────────────────────────────────
@app.route("/api/products", methods=["GET"])
@require_auth
def get_products():
    hotel = request.args.get("hotel", "").strip().lower()
    hotels = list_hotels()

    if hotel:
        # Return products for a specific hotel
        return jsonify({"products": hotel_entries(hotel), "hotels": hotels, "current_hotel": hotel})
    # Return all hotels with their products
    return jsonify({"by_hotel": all_hotel_entries(), "hotels": hotels})


def _shelf_from_body(body):
    """(months or None, error or None) from an optional shelf_months field."""
    return validate_shelf_months(body.get("shelf_months"))


@app.route("/api/products/add", methods=["POST"])
@require_auth
def api_add_product():
    body    = request.get_json() or {}
    product = (body.get("product") or "").strip().upper()
    weight  = (body.get("weight") or "").strip().upper()
    hotel   = (body.get("hotel") or "general").strip().lower()
    if not product or not weight:
        return jsonify({"error": "Product and weight required"}), 400
    if "shelf_months" in body:
        shelf, err = _shelf_from_body(body)
        if err:
            return jsonify({"error": err}), 400
        result = add_product(product, weight, hotel, shelf_months=shelf)
    else:
        result = add_product(product, weight, hotel)
    return jsonify({"message": result})


@app.route("/api/products/update", methods=["POST"])
@require_auth
def api_update_product():
    body    = request.get_json() or {}
    old     = (body.get("old_product") or "").strip().upper()
    product = (body.get("product") or "").strip().upper()
    weight  = (body.get("weight") or "").strip().upper()
    hotel   = (body.get("hotel") or "general").strip().lower()
    if not old or not product or not weight:
        return jsonify({"error": "Product and weight required"}), 400
    shelf, err = _shelf_from_body(body)
    if err:
        return jsonify({"error": err}), 400
    ok, message = update_product(old, product, weight, hotel, shelf_months=shelf)
    if not ok:
        return jsonify({"error": message}), 400
    return jsonify({"message": message})


@app.route("/api/products/remove", methods=["POST"])
@require_auth
def api_remove_product():
    body    = request.get_json() or {}
    product = (body.get("product") or "").strip().upper()
    hotel   = (body.get("hotel") or "general").strip().lower()
    if not product:
        return jsonify({"error": "Product required"}), 400
    result = remove_product(product, hotel)
    return jsonify({"message": result})


@app.route("/api/hotels/add", methods=["POST"])
@require_auth
def api_add_hotel():
    body = request.get_json() or {}
    ok, message = add_hotel(body.get("hotel"))
    if not ok:
        return jsonify({"error": message}), 400
    return jsonify({"message": message, "hotels": list_hotels()})


# ── Ingredient templates ──────────────────────────
@app.route("/api/ingredient-templates", methods=["GET"])
@require_auth
def api_list_templates():
    return jsonify({"templates": list_templates()})


@app.route("/api/ingredient-templates/save", methods=["POST"])
@require_auth
def api_save_template():
    body = request.get_json() or {}
    ok, message = save_template(body.get("name"), body.get("text"))
    if not ok:
        return jsonify({"error": message}), 400
    return jsonify({"message": message, "templates": list_templates()})


@app.route("/api/ingredient-templates/remove", methods=["POST"])
@require_auth
def api_remove_template():
    body = request.get_json() or {}
    if not remove_template(body.get("name")):
        return jsonify({"error": "Template not found"}), 404
    return jsonify({"message": "Removed", "templates": list_templates()})


# ── Printing ──────────────────────────────────────
@app.route("/api/print", methods=["POST"])
@require_auth
def print_labels():
    body  = request.get_json() or {}
    jobs  = body.get("jobs", [])
    hotel = (body.get("hotel") or "general").strip().lower()
    packed_on   = (body.get("packed_on") or "").strip() or None
    best_before = (body.get("best_before") or "").strip() or None
    if not jobs:
        return jsonify({"error": "No jobs provided"}), 400

    results  = []
    username = request.username
    queue    = get_queue()

    # Parse all lines first, preserving order. Valid requests are queued together
    # in one atomic batch so a multi-line submission is paired together in 2-up mode.
    entries     = []   # ("fail", line, error) or ("ok", line, req)
    valid_reqs  = []
    for job in jobs:
        line = job.get("line", "").strip()
        if not line:
            continue
        req, error = parse_message(line, hotel=hotel, packed_on=packed_on, best_before=best_before)
        if error:
            entries.append(("fail", line, error))
        else:
            entries.append(("ok", line, req))
            valid_reqs.append(req)

    q_jobs = queue.add_batch(valid_reqs, username=username, source="ui") if valid_reqs else []
    q_iter = iter(q_jobs)

    for kind, line, payload in entries:
        if kind == "fail":
            results.append({"line": line, "success": False, "error": payload})
            continue
        req   = payload
        q_job = next(q_iter)
        results.append({
            "line":        line,
            "success":     True,
            "queued":      True,
            "job_id":      q_job.id,
            "product":     req.product,
            "weight":      req.weight,
            "quantity":    req.quantity,
            "packed_on":   req.packed_on,
            "best_before": req.best_before,
            "batch_no":    q_job.batch_no,
            "error":       None,
        })

    return jsonify({"results": results})


@app.route("/api/preview", methods=["POST"])
@require_auth
def preview_label():
    """Render one label to a PNG exactly as it would print, without queueing it."""
    body  = request.get_json() or {}
    line  = (body.get("line") or "").strip()
    hotel = (body.get("hotel") or "general").strip().lower()
    packed_on   = (body.get("packed_on") or "").strip() or None
    best_before = (body.get("best_before") or "").strip() or None
    if not line:
        return jsonify({"error": "Nothing to preview"}), 400
    req, error = parse_message(line, hotel=hotel, packed_on=packed_on, best_before=best_before)
    if error:
        return jsonify({"error": error}), 400
    # A preview must not use up one of the day's lot numbers, so the
    # sequence digits are left as placeholders.
    batch_no = f"SRT{datetime.now():%d%m%y}xxx" if req.label_type == "product" else ""
    try:
        img = render_label(req, batch_no)
    except Exception as e:
        return jsonify({"error": f"Could not render the label: {e}"}), 500
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/api/test-print", methods=["POST"])
@require_auth
def test_print():
    """Queue a calibration label using the saved settings."""
    today = datetime.now()
    packed, expiry = format_date_pair(today, today + relativedelta(months=3))
    # Two on a 2-up roll, so both columns can be checked for alignment
    qty = 2 if get_roll_type() == "double" else 1
    req = PrintRequest(product="TEST LABEL", weight="1 kg", quantity=qty,
                       packed_on=packed, best_before=expiry)
    job = get_queue().add_test(req, username=request.username)
    return jsonify({"job_id": job.id, "quantity": qty})


# ── Queue endpoints ───────────────────────────────
@app.route("/api/queue", methods=["GET"])
@require_auth
def get_print_queue():
    queue = get_queue()
    jobs = queue.list_all()
    # The printer state rides along so the UI's queue poll also keeps the
    # status pill current, without a second request through the tunnel.
    online, message = check_printer()
    return jsonify({"jobs": jobs, "printer": {"online": online, "status": message}})


@app.route("/api/queue/cancel", methods=["POST"])
@require_auth
def cancel_queue_job():
    body   = request.get_json() or {}
    job_id = (body.get("job_id") or "").strip()
    if not job_id:
        return jsonify({"error": "job_id required"}), 400
    queue   = get_queue()
    success = queue.cancel(job_id)
    if success:
        return jsonify({"message": f"Job {job_id} cancelled"})
    return jsonify({"error": "Job not found or already processing"}), 404


@app.route("/api/queue/cancel-all", methods=["POST"])
@require_auth
def cancel_all_queue_jobs():
    queue = get_queue()
    count = queue.cancel_all()
    return jsonify({"message": f"Cancelled {count} job(s)", "count": count})


@app.route("/api/queue/retry", methods=["POST"])
@require_auth
def retry_queue_jobs():
    """Requeue one failed job (job_id) or every failed job (no job_id)."""
    body   = request.get_json(silent=True) or {}
    job_id = (body.get("job_id") or "").strip() or None
    count  = get_queue().retry(job_id)
    if job_id and not count:
        return jsonify({"error": "Job not found or not failed"}), 404
    return jsonify({"message": f"Requeued {count} job(s)", "count": count})


@app.route("/api/queue/dismiss", methods=["POST"])
@require_auth
def dismiss_queue_jobs():
    """Clear one failed job (job_id) or every failed job (no job_id) from the list."""
    body   = request.get_json(silent=True) or {}
    job_id = (body.get("job_id") or "").strip() or None
    count  = get_queue().dismiss(job_id)
    if job_id and not count:
        return jsonify({"error": "Job not found or not failed"}), 404
    return jsonify({"message": f"Cleared {count} job(s)", "count": count})


# ── Logs endpoint ────────────────────────────────
def _local_day_start_utc(day: str) -> str:
    """'YYYY-MM-DD' as a local calendar day → its midnight in UTC, the zone print_logs stores."""
    local_midnight = datetime.strptime(day, "%Y-%m-%d")
    return local_midnight.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@app.route("/api/logs", methods=["GET"])
@require_auth
def get_print_logs():
    username       = request.username
    admin          = is_admin()
    filter_user    = request.args.get("user", "").strip() or None
    filter_product = request.args.get("product", "").strip() or None
    date_from      = request.args.get("from", "").strip()
    date_to        = request.args.get("to", "").strip()
    try:
        limit  = max(1, min(int(request.args.get("limit", 100)), 500))
        offset = max(0, int(request.args.get("offset", 0)))
        since  = _local_day_start_utc(date_from) if date_from else None
        # 'to' is inclusive: everything before the start of the next day
        until  = (_local_day_start_utc((datetime.strptime(date_to, "%Y-%m-%d")
                                         + timedelta(days=1)).strftime("%Y-%m-%d"))
                  if date_to else None)
    except ValueError:
        return jsonify({"error": "Invalid limit, offset or date"}), 400

    # One extra row tells us whether there is another page
    logs = get_logs(username, admin, limit + 1, filter_user, filter_product,
                    since_utc=since, until_utc=until, offset=offset)
    has_more = len(logs) > limit
    logs = logs[:limit]
    usernames = get_all_usernames() if admin else [username]

    return jsonify({
        "logs":      logs,
        "has_more":  has_more,
        "is_admin":  admin,
        "usernames": usernames
    })


if __name__ == "__main__":
    print("🌐 Label Bot UI server running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
