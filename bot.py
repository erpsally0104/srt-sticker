import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    filters,
)

import os
from dotenv import load_dotenv

from user_manager import is_admin, is_authorized, add_user, remove_user, list_users
from product_manager import add_product, remove_product, list_products, list_hotels
from batch_manager import get_next_batch_number
from parser import parse_message
from printer import print_label, get_printer_status
from print_queue import get_queue
from logger import log_print
from settings_manager import get_roll_type, set_roll_type

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def get_username(update: Update) -> str:
    return (update.effective_user.username or "").lower()


def check_auth(update: Update) -> bool:
    return is_authorized(get_username(update))


def check_admin(update: Update) -> bool:
    return is_admin(get_username(update))


# ─────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    await update.message.reply_text(
        "👋 *SRI RADHE Label Bot*\n\n"
        "Send a message in this format to print stickers:\n\n"
        "`Product, Quantity`\n"
        "`Product, Quantity, Weight`\n"
        "`Product, Quantity, Weight, PackedDate, BestBefore, Hotel`\n\n"
        "*Ingredients sticker:*\n"
        "`Ingredients text ;; i`\n"
        "`Ingredients text ;; i 5`\n\n"
        "*FSSAI logo sticker:*\n"
        "`FSSAI number ;; f`\n"
        "`FSSAI number ;; f 5`\n\n"
        "*Examples:*\n"
        "`PHALLI, 10`\n"
        "`TOOR DAL, 5, 1 KG`\n"
        "`TOOR DAL, 5, 1 KG, today, today + 6 months, taj`\n"
        "`TOOR DAL, 5, 1 KG, 15/04/2026, 15/07/2026`\n"
        "`Refined wheat flour, Rice Flour ;; i`\n"
        "`13620011000563 ;; f 10`\n\n"
        "_Dates are optional. Defaults: Packed = today, Use By = today + 3 months._\n"
        "_Date formats: today, today + N months, DD/MM/YYYY, DD-MM-YYYY_\n"
        "Hotel defaults to *general* if not specified.\n"
        "Use /help to see all commands.",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────────────────
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    msg = (
        "📋 *Commands:*\n\n"
        "*Print a label:*\n"
        "`Product, Quantity`\n"
        "`Product, Quantity, Weight`\n"
        "`Product, Quantity, Weight, PackedDate, BestBefore, Hotel`\n\n"
        "_Dates & Hotel are optional._\n"
        "_Packed defaults to today, Use By to today + 3 months._\n"
        "_Date formats: today, today + N months, DD/MM/YYYY, DD-MM-YYYY_\n"
        "_Leave date empty (,,) to use default._\n\n"
        "*Ingredients sticker:*\n"
        "`Ingredients text ;; i`\n"
        "`Ingredients text ;; i 5`\n\n"
        "*FSSAI logo sticker:*\n"
        "`FSSAI number ;; f`\n"
        "`FSSAI number ;; f 5`\n\n"
        "*General:*\n"
        "/status — Check printer status\n"
        "/rolltype — View/set roll type (single or 2-up)\n"
        "/queue — View print queue\n"
        "/cancel ID — Cancel a queued job\n"
        "/cancelall — Cancel all queued jobs\n"
        "/listproducts — Show all hotels\n"
        "/listproducts general — Show products for a hotel\n"
        "/help — Show this message\n"
    )

    if check_admin(update):
        msg += (
            "\n*Admin only:*\n"
            "/adduser @username — Authorize a user\n"
            "/removeuser @username — Remove a user\n"
            "/listusers — Show all authorized users\n"
            "/addproduct PRODUCT WEIGHT — Add to general\n"
            "/addproduct PRODUCT WEIGHT HOTEL — Add to hotel\n"
            "/removeproduct PRODUCT — Remove from general\n"
            "/removeproduct PRODUCT HOTEL — Remove from hotel\n"
        )

    await update.message.reply_text(msg, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────
# /status
# ─────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return
    status = get_printer_status()
    await update.message.reply_text(f"🖨️ *Printer Status*\n\n{status}", parse_mode="Markdown")


# ─────────────────────────────────────────────────────────
# /rolltype [single|double]
# View or set the loaded roll type (which sticker roll is in the printer)
# ─────────────────────────────────────────────────────────
async def cmd_rolltype(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return

    labels = {
        "single": "Single (one 50×40mm label per row)",
        "double": "Double 2-up (two 50×40mm labels side by side)",
    }

    if not context.args:
        current = get_roll_type()
        await update.message.reply_text(
            f"🧻 *Roll Type:* {labels.get(current, current)}\n\n"
            "Change it with:\n`/rolltype single`\n`/rolltype double`",
            parse_mode="Markdown"
        )
        return

    result = set_roll_type(context.args[0])
    if result is None:
        await update.message.reply_text(
            "⚠️ Invalid roll type. Use `/rolltype single` or `/rolltype double`.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        f"✅ Roll type set to *{labels.get(result, result)}*.",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────
# /adduser @username  (admin only)
# ─────────────────────────────────────────────────────────
async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update):
        await update.message.reply_text("⛔ Only the admin can do this.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /adduser @username")
        return
    result = add_user(context.args[0])
    await update.message.reply_text(result)


# ─────────────────────────────────────────────────────────
# /removeuser @username  (admin only)
# ─────────────────────────────────────────────────────────
async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update):
        await update.message.reply_text("⛔ Only the admin can do this.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removeuser @username")
        return
    result = remove_user(context.args[0])
    await update.message.reply_text(result)


# ─────────────────────────────────────────────────────────
# /listusers  (admin only)
# ─────────────────────────────────────────────────────────
async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update):
        await update.message.reply_text("⛔ Only the admin can do this.")
        return
    result = list_users()
    await update.message.reply_text(result, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────
# /addproduct PRODUCT WEIGHT [HOTEL]  (admin only)
# Example: /addproduct MANGO 1 KG
# Example: /addproduct MANGO 1 KG taj
# ─────────────────────────────────────────────────────────
async def cmd_addproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update):
        await update.message.reply_text("⛔ Only the admin can do this.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "/addproduct PRODUCT WEIGHT\n"
            "/addproduct PRODUCT WEIGHT HOTEL\n\n"
            "Example:\n"
            "/addproduct MANGO 1 KG\n"
            "/addproduct MANGO 1 KG taj"
        )
        return

    args = context.args

    # Check if last arg is a known hotel or looks like a hotel name
    # Hotels are single lowercase words that are NOT weight units
    weight_units = {"KG", "KGS", "GM", "GMS", "GRAMS", "GRAM", "G"}
    last_arg_upper = args[-1].upper()

    # Detect hotel: if last arg is not a weight unit and not a number,
    # treat it as hotel name
    hotel = "general"
    weight_end_idx = len(args)

    if last_arg_upper not in weight_units:
        try:
            float(args[-1])
            # It's a number, not a hotel
        except ValueError:
            # Not a number and not a weight unit — could be hotel
            # But only if there are enough args for product + weight before it
            if len(args) >= 4:
                hotel = args[-1].lower()
                weight_end_idx = len(args) - 1

    # Weight = last 2 tokens before hotel, product = everything before weight
    weight_args = args[weight_end_idx - 2 : weight_end_idx]
    weight = " ".join(weight_args)
    product = " ".join(args[: weight_end_idx - 2])

    if not product:
        await update.message.reply_text(
            "Usage:\n"
            "/addproduct PRODUCT WEIGHT\n"
            "/addproduct PRODUCT WEIGHT HOTEL\n\n"
            "Example:\n"
            "/addproduct MANGO 1 KG\n"
            "/addproduct MANGO 1 KG taj"
        )
        return

    result = add_product(product, weight, hotel)
    await update.message.reply_text(result, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────
# /removeproduct PRODUCT [HOTEL]  (admin only)
# ─────────────────────────────────────────────────────────
async def cmd_removeproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_admin(update):
        await update.message.reply_text("⛔ Only the admin can do this.")
        return
    if not context.args:
        await update.message.reply_text(
            "Usage:\n"
            "/removeproduct PRODUCT\n"
            "/removeproduct PRODUCT HOTEL\n\n"
            "Example:\n"
            "/removeproduct MANGO\n"
            "/removeproduct MANGO taj"
        )
        return

    args = context.args
    hotels = list_hotels()

    # If last arg matches a known hotel name, use it
    hotel = "general"
    if len(args) >= 2 and args[-1].lower() in hotels:
        hotel = args[-1].lower()
        product = " ".join(args[:-1])
    else:
        product = " ".join(args)

    result = remove_product(product, hotel)
    await update.message.reply_text(result, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────
# /listproducts [HOTEL]
# ─────────────────────────────────────────────────────────
async def cmd_listproducts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return

    hotel = None
    if context.args:
        hotel = context.args[0].lower()

    result = list_products(hotel)
    await update.message.reply_text(result, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────
# Handle all non-command messages → print requests
# Supports single line and multi-line batch input
# The 4th comma-separated param is hotel (optional, defaults to general)
# ─────────────────────────────────────────────────────────
async def handle_print_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized to use this bot.")
        return

    text = update.message.text.strip()

    # Split into lines, filter empty lines
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Parse all lines first — fail early if any line has an error
    requests = []
    for i, line in enumerate(lines, 1):
        req, error = parse_message(line)
        if error:
            prefix = f"Line {i}: `{line}`\n" if len(lines) > 1 else ""
            await update.message.reply_text(
                f"{prefix}{error}",
                parse_mode="Markdown"
            )
            return
        requests.append(req)

    # All lines valid — check for high quantities (> 50)
    high_qty = [req for req in requests if req.quantity > 50]
    if high_qty:
        # Store pending requests in user_data for confirmation
        context.user_data["pending_print"] = requests
        lines_desc = "\n".join(
            f"  • *{r.product}* × {r.quantity}" for r in high_qty
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, print", callback_data="confirm_print"),
                InlineKeyboardButton("❌ Cancel", callback_data="cancel_print"),
            ]
        ])
        await update.message.reply_text(
            f"⚠️ *High quantity detected:*\n\n{lines_desc}\n\n"
            "Are you sure you want to print this many stickers?",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    # All lines valid — send to printer
    await _execute_print(requests, update, context)

async def _execute_print(requests, update_or_query, context):
    """Shared print execution for both direct prints and confirmed prints."""
    # Determine if this is from a callback query or a regular message
    is_callback = not isinstance(update_or_query, Update)
    if is_callback:
        # CallbackQuery object
        send = update_or_query.message.reply_text
        username = (update_or_query.from_user.username or "").lower()
    else:
        # Regular Update object
        send = update_or_query.message.reply_text
        username = get_username(update_or_query)

    queue = get_queue()
    queued_lines = []

    q_jobs = queue.add_batch(requests, username=username, source="telegram")
    for req, q_job in zip(requests, q_jobs):
        if req.label_type == "ingredients":
            queued_lines.append(
                f"📋 *Ingredients sticker* — {req.quantity} sticker(s) | Job: `{q_job.id}`"
            )
        elif req.label_type == "fssai":
            queued_lines.append(
                f"📋 *FSSAI logo sticker* — {req.fssai_number} — {req.quantity} sticker(s) | Job: `{q_job.id}`"
            )
        else:
            hotel_tag = f" [{req.hotel}]" if req.hotel != "general" else ""
            queued_lines.append(
                f"📋 *{req.product}*{hotel_tag} — {req.quantity} sticker(s) | {req.weight} | Batch: {q_job.batch_no} | Job: `{q_job.id}`"
            )

    if len(requests) == 1:
        req = requests[0]
        if req.label_type == "ingredients":
            await send(
                f"🖨️ *Queued {req.quantity} ingredients sticker(s)*\n\n"
                f"🧾 Ingredients: {req.ingredients}\n"
                f"🔖 Job ID: `{queued_lines[0].split('Job: `')[1].rstrip('`')}`\n\n"
                "_Use /queue to see status, /cancel ID to cancel._",
                parse_mode="Markdown"
            )
        elif req.label_type == "fssai":
            await send(
                f"🖨️ *Queued {req.quantity} FSSAI logo sticker(s)*\n\n"
                f"🔢 FSSAI No.  : {req.fssai_number}\n"
                f"🆔 Job ID     : `{q_jobs[0].id}`\n\n"
                "_Use /queue to see status, /cancel ID to cancel._",
                parse_mode="Markdown"
            )
        else:
            job_id = queued_lines[0].split("Job: `")[1].rstrip("`")
            batch_no = queued_lines[0].split("Batch: ")[1].split(" |")[0]
            hotel_line = f"🏨 Hotel      : {req.hotel}\n" if req.hotel != "general" else ""
            await send(
                f"🖨️ *Queued {req.quantity} sticker(s)*\n\n"
                f"📦 Product    : {req.product}\n"
                f"⚖️ Weight     : {req.weight}\n"
                f"{hotel_line}"
                f"📅 Packed On  : {req.packed_on}\n"
                f"📅 Use By: {req.best_before}\n"
                f"🔖 Batch No   : {batch_no}\n"
                f"🆔 Job ID     : `{job_id}`\n\n"
                "_Use /queue to see status, /cancel ID to cancel._",
                parse_mode="Markdown"
            )
    else:
        summary = f"🖨️ *Queued {len(requests)} job(s)*\n\n"
        await send(
            summary + "\n".join(queued_lines) +
            "\n\n_Use /queue to see status, /cancelall to cancel all._",
            parse_mode="Markdown"
        )


# ─────────────────────────────────────────────────────────
# /queue — Show current print queue
# ─────────────────────────────────────────────────────────
async def cmd_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return

    queue = get_queue()
    # list_all, not list_jobs: list_jobs returns only queued+printing, so a
    # failed job was invisible here and the operator was never told that a
    # print they asked for did not happen.
    all_jobs = queue.list_all()
    active = [j for j in all_jobs if j["status"] in ("queued", "printing")]
    failed = [j for j in all_jobs if j["status"] == "failed"]

    if not active and not failed:
        await update.message.reply_text("📭 Print queue is empty.")
        return

    lines = []
    for j in failed:
        lines.append(
            f"❌ *{j['product']}* × {j['quantity']} — FAILED, nothing printed\n"
            f"    _{j.get('error') or 'Printer error'}_"
        )
    if failed and active:
        lines.append("")
    for j in active:
        status_icon = "🔄" if j["status"] == "printing" else "⏳"
        lines.append(
            f"{status_icon} `{j['id']}` — *{j['product']}* × {j['quantity']} ({j['status']})"
        )

    header = f"🖨️ *Print Queue ({len(active)} active"
    header += f", {len(failed)} failed)*" if failed else ")*"

    await update.message.reply_text(
        header + "\n\n"
        + "\n".join(lines)
        + "\n\n_/cancel ID — cancel a job\n/cancelall — cancel all queued_",
        parse_mode="Markdown"
    )


# ─────────────────────────────────────────────────────────
# /cancel <job_id> — Cancel a specific queued job
# ─────────────────────────────────────────────────────────
async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/cancel JOB_ID`\n\nUse /queue to see job IDs.",
            parse_mode="Markdown"
        )
        return

    job_id = context.args[0].strip()
    queue = get_queue()
    success = queue.cancel(job_id)

    if success:
        await update.message.reply_text(f"✅ Job `{job_id}` cancelled.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"⚠️ Could not cancel `{job_id}` — not found or already printing.",
            parse_mode="Markdown"
        )


# ─────────────────────────────────────────────────────────
# /cancelall — Cancel all queued jobs
# ─────────────────────────────────────────────────────────
async def cmd_cancelall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_auth(update):
        await update.message.reply_text("⛔ You are not authorized.")
        return

    queue = get_queue()
    count = queue.cancel_all()

    if count:
        await update.message.reply_text(f"✅ Cancelled {count} queued job(s).")
    else:
        await update.message.reply_text("📭 No queued jobs to cancel.")


# ─────────────────────────────────────────────────────────
# Callback handler for quantity confirmation
# ─────────────────────────────────────────────────────────
async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm_print":
        pending = context.user_data.pop("pending_print", None)
        if not pending:
            await query.edit_message_text("⚠️ No pending print job found.")
            return
        await query.edit_message_text("✅ Confirmed. Sending to printer...")
        await _execute_print(pending, query, context)

    elif query.data == "cancel_print":
        context.user_data.pop("pending_print", None)
        await query.edit_message_text("❌ Print cancelled.")


# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("rolltype", cmd_rolltype))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CommandHandler("addproduct", cmd_addproduct))
    app.add_handler(CommandHandler("removeproduct", cmd_removeproduct))
    app.add_handler(CommandHandler("listproducts", cmd_listproducts))
    app.add_handler(CommandHandler("queue", cmd_queue))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("cancelall", cmd_cancelall))

    # All non-command text messages → print requests
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_print_request))

    # Inline button callbacks (quantity confirmation)
    app.add_handler(CallbackQueryHandler(handle_confirmation))

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
