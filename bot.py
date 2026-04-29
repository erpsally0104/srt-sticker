import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

from user_manager import is_admin, is_authorized, add_user, remove_user, list_users
from product_manager import add_product, remove_product, list_products, list_hotels
from batch_manager import get_next_batch_number
from parser import parse_message
from printer import print_label, get_printer_status
from logger import log_print

# ──────────────────────────────────────────────
# PASTE YOUR TELEGRAM BOT TOKEN HERE
# Get it from @BotFather on Telegram
# ──────────────────────────────────────────────
BOT_TOKEN = "8615569196:AAFd0jeJrkd1Vh_mVJRqsqZwizavRJfB5LI"

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
        "`Product, Quantity, Weight, Hotel`\n\n"
        "*Ingredients sticker:*\n"
        "`Ingredients text ;; i`\n"
        "`Ingredients text ;; i 5`\n\n"
        "*Examples:*\n"
        "`PHALLI, 10`\n"
        "`TOOR DAL, 5, 1 KG`\n"
        "`TOOR DAL, 5, 1 KG, taj`\n"
        "`Refined wheat flour, Rice Flour ;; i`\n\n"
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
        "`Product, Quantity, Weight, Hotel`\n\n"
        "_Hotel is optional — defaults to general._\n\n"
        "*Ingredients sticker:*\n"
        "`Ingredients text ;; i`\n"
        "`Ingredients text ;; i 5`\n\n"
        "*General:*\n"
        "/status — Check printer status\n"
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

    # All lines valid — send to printer
    if len(requests) > 1:
        await update.message.reply_text(f"🖨️ Printing {len(requests)} jobs...")
    else:
        await update.message.reply_text("🖨️ Sending to printer...")

    success_lines = []
    failed_lines  = []

    for req in requests:
        if req.label_type == "ingredients":
            # Ingredients stickers don't need a batch number
            success = print_label(req)
            if success:
                success_lines.append(
                    f"✅ *Ingredients sticker* — {req.quantity} sticker(s)"
                )
            else:
                failed_lines.append(f"❌ *Ingredients sticker* — print failed")
        else:
            batch_no = get_next_batch_number()
            success  = print_label(req, batch_no)
            if success:
                hotel_tag = f" [{req.hotel}]" if req.hotel != "general" else ""
                success_lines.append(
                    f"✅ *{req.product}*{hotel_tag} — {req.quantity} sticker(s) | {req.weight} | Batch: {batch_no}"
                )
                log_print(
                    username    = get_username(update),
                    source      = "telegram",
                    product     = req.product,
                    weight      = req.weight,
                    quantity    = req.quantity,
                    batch_no    = batch_no,
                    packed_on   = req.packed_on,
                    best_before = req.best_before
                )
            else:
                failed_lines.append(f"❌ *{req.product}* — print failed")

    # Build reply
    if len(requests) == 1 and success_lines:
        req = requests[0]
        if req.label_type == "ingredients":
            await update.message.reply_text(
                f"✅ *Printing {req.quantity} ingredients sticker(s)*\n\n"
                f"🧾 Ingredients: {req.ingredients}",
                parse_mode="Markdown"
            )
        else:
            batch_no = success_lines[0].split("Batch: ")[1]
            hotel_line = f"🏨 Hotel      : {req.hotel}\n" if req.hotel != "general" else ""
            await update.message.reply_text(
                f"✅ *Printing {req.quantity} sticker(s)*\n\n"
                f"📦 Product    : {req.product}\n"
                f"⚖️ Weight     : {req.weight}\n"
                f"{hotel_line}"
                f"📅 Packed On  : {req.packed_on}\n"
                f"📅 Best Before: {req.best_before}\n"
                f"🔖 Batch No   : {batch_no}",
                parse_mode="Markdown"
            )
    else:
        all_lines = success_lines + failed_lines
        summary   = f"*Print Summary ({len(success_lines)}/{len(requests)} succeeded)*\n\n"
        await update.message.reply_text(
            summary + "\n".join(all_lines),
            parse_mode="Markdown"
        )

    if failed_lines:
        await update.message.reply_text(
            "⚠️ Some jobs failed. Use /status to check printer.",
            parse_mode="Markdown"
        )


# ─────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("removeuser", cmd_removeuser))
    app.add_handler(CommandHandler("listusers", cmd_listusers))
    app.add_handler(CommandHandler("addproduct", cmd_addproduct))
    app.add_handler(CommandHandler("removeproduct", cmd_removeproduct))
    app.add_handler(CommandHandler("listproducts", cmd_listproducts))

    # All non-command text messages → print requests
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_print_request))

    print("🤖 Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
