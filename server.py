from flask import Flask, request, jsonify
from flask_cors import CORS
from functools import wraps

from auth import init_db, verify_user, generate_tokens, verify_access_token, verify_refresh_token
from logger import log_print, get_logs, get_all_usernames
from parser import parse_message
from printer import print_label, get_printer_status
from batch_manager import get_next_batch_number
from product_manager import (
    add_product, remove_product, list_hotels,
    get_hotel_products, _load as load_products
)

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
@app.route("/api/status", methods=["GET"])
@require_auth
def status():
    return jsonify({"status": get_printer_status()})


@app.route("/api/products", methods=["GET"])
@require_auth
def get_products():
    hotel = request.args.get("hotel", "").strip().lower()
    hotels = list_hotels()

    if hotel:
        # Return products for a specific hotel
        prods = get_hotel_products(hotel)
        products = [{"name": k, "weight": v} for k, v in prods.items()]
        return jsonify({"products": products, "hotels": hotels, "current_hotel": hotel})
    else:
        # Return all hotels with their products
        all_data = load_products()
        by_hotel = {}
        for h, prods in all_data.items():
            by_hotel[h] = [{"name": k, "weight": v} for k, v in prods.items()]
        return jsonify({"by_hotel": by_hotel, "hotels": hotels})


@app.route("/api/print", methods=["POST"])
@require_auth
def print_labels():
    body  = request.get_json()
    jobs  = body.get("jobs", [])
    hotel = (body.get("hotel") or "general").strip().lower()
    packed_on   = (body.get("packed_on") or "").strip() or None
    best_before = (body.get("best_before") or "").strip() or None
    if not jobs:
        return jsonify({"error": "No jobs provided"}), 400

    results  = []
    username = request.username

    for job in jobs:
        line = job.get("line", "").strip()
        if not line:
            continue
        req, error = parse_message(line, hotel=hotel, packed_on=packed_on, best_before=best_before)
        if error:
            results.append({"line": line, "success": False, "error": error})
            continue

        batch_no = get_next_batch_number()
        success  = print_label(req, batch_no)

        if success:
            log_print(
                username    = username,
                source      = "ui",
                product     = req.product,
                weight      = req.weight,
                quantity    = req.quantity,
                batch_no    = batch_no,
                packed_on   = req.packed_on,
                best_before = req.best_before
            )

        results.append({
            "line":        line,
            "success":     success,
            "product":     req.product,
            "weight":      req.weight,
            "quantity":    req.quantity,
            "packed_on":   req.packed_on,
            "best_before": req.best_before,
            "batch_no":    batch_no,
            "error":       None if success else "Printer error"
        })

    return jsonify({"results": results})


@app.route("/api/products/add", methods=["POST"])
@require_auth
def api_add_product():
    body    = request.get_json()
    product = body.get("product", "").strip().upper()
    weight  = body.get("weight", "").strip().upper()
    hotel   = (body.get("hotel") or "general").strip().lower()
    if not product or not weight:
        return jsonify({"error": "Product and weight required"}), 400
    result = add_product(product, weight, hotel)
    return jsonify({"message": result})


@app.route("/api/products/remove", methods=["POST"])
@require_auth
def api_remove_product():
    body    = request.get_json()
    product = body.get("product", "").strip().upper()
    hotel   = (body.get("hotel") or "general").strip().lower()
    if not product:
        return jsonify({"error": "Product required"}), 400
    result = remove_product(product, hotel)
    return jsonify({"message": result})


# ── Logs endpoint ────────────────────────────────
@app.route("/api/logs", methods=["GET"])
@require_auth
def get_print_logs():
    username       = request.username
    admin          = is_admin()
    filter_user    = request.args.get("user", "").strip() or None
    filter_product = request.args.get("product", "").strip() or None
    limit          = min(int(request.args.get("limit", 100)), 500)

    logs      = get_logs(username, admin, limit, filter_user, filter_product)
    usernames = get_all_usernames() if admin else [username]

    return jsonify({
        "logs":      logs,
        "is_admin":  admin,
        "usernames": usernames
    })


if __name__ == "__main__":
    print("🌐 Label Bot UI server running at http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
