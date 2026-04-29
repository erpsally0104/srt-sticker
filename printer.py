import win32print
from PIL import Image, ImageDraw, ImageFont
import qrcode
from parser import PrintRequest

PRINTER_NAME = "TSC TE244"

DPI        = 203
LABEL_W_PX = int(50 / 25.4 * DPI)   # ~400px
LABEL_H_PX = int(38 / 25.4 * DPI)   # ~304px

FONT_BRITANNIC = r"C:\Windows\Fonts\britanic.ttf"
FONT_ARIAL_NB  = r"C:\Windows\Fonts\ARIALNB.TTF"
FONT_ARIAL_N   = r"C:\Windows\Fonts\ARIALN.TTF"
FONT_ARIAL     = r"C:\Windows\Fonts\arial.ttf"
FONT_ARIAL_BD  = r"C:\Windows\Fonts\arialbd.ttf"


def get_font(path, size, fallback=None):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        if fallback:
            try:
                return ImageFont.truetype(fallback, size)
            except Exception:
                pass
        return ImageFont.truetype(FONT_ARIAL, size)


def make_qr(data):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=4,
        border=1,
    )
    qr.add_data(data)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def draw_centered(draw, y, text, font, max_width=None, offset=0):
    """Draw text horizontally centered. offset nudges left (negative) or right (positive)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    w = max_width if max_width else LABEL_W_PX
    x = (w - text_w) // 2 + offset
    draw.text((x, y), text, font=font, fill="black")
    return bbox[3] - bbox[1]  # return text height


def build_label_image(req, batch_no):
    img  = Image.new("RGB", (LABEL_W_PX, LABEL_H_PX), color="white")
    draw = ImageDraw.Draw(img)

    font_product = get_font(FONT_BRITANNIC, 40)
    font_weight  = get_font(FONT_ARIAL_NB, 30, FONT_ARIAL_N)
    font_dates   = get_font(FONT_ARIAL_NB, 28, FONT_ARIAL_N)
    font_batch   = get_font(FONT_ARIAL_NB, 22, FONT_ARIAL_N)  # smaller to save space
    font_bottom  = get_font(FONT_ARIAL_NB, 17, FONT_ARIAL_N)
    font_fssai   = get_font(FONT_ARIAL_BD, 22, FONT_ARIAL_NB)

    # ── QR Code ───────────────────────────────────
    qr_data = (
        f"{req.product} {req.weight} "
        f"Batch:{batch_no} "
        f"Packed:{req.packed_on} "
        f"Best Before:{req.best_before} "
        f"SRI RADHE TRADERS FSSAI Lic. No.:13620011000563"
    )
    qr_size = 110
    qr_img  = make_qr(qr_data).resize((qr_size, qr_size), Image.NEAREST)
    qr_x    = LABEL_W_PX - qr_size - 20   # pulled inward from right edge
    qr_y    = 65                           # below green dot
    img.paste(qr_img, (qr_x, qr_y))

    # ── Calculate total content height for vertical centering ──
    # Top section lines
    LINE_PRODUCT = 46   # font 40 height approx
    LINE_WEIGHT  = 36   # font 30 height approx
    LINE_DATE    = 30   # font 28 height approx
    LINE_BATCH   = 26   # font 22 height approx (batch only)
    GAP_SMALL    = 6
    GAP_DIVIDER  = 10

    # Bottom section lines
    LINE_BOTTOM  = 21   # font 17 height approx
    N_BOTTOM     = 3    # 3 lines in bottom section

    # Top section total height
    top_h = (LINE_PRODUCT + GAP_SMALL +
             LINE_WEIGHT  + GAP_SMALL +
             LINE_DATE    + GAP_SMALL +   # Packed
             LINE_DATE    + GAP_SMALL +   # Best Before
             LINE_BATCH)                  # Batch (smaller font)

    # Divider + bottom section
    bottom_h = GAP_DIVIDER + 2 + GAP_DIVIDER + (LINE_BOTTOM + 4) * N_BOTTOM

    total_h  = top_h + GAP_DIVIDER + bottom_h

    # Vertical start offset to center everything
    top_pad  = max(8, (LABEL_H_PX - total_h) // 2)

    # ── Draw top section ──────────────────────────
    PAD = 8
    y   = top_pad

    # Product name — centered full width
    draw_centered(draw, y, req.product, font_product)
    y += LINE_PRODUCT + GAP_SMALL

    # Weight — centered full width
    draw_centered(draw, y, f"Weight: {req.weight}", font_weight, offset=-30)
    y += LINE_WEIGHT + GAP_SMALL

    # Dates — left aligned, constrained to left of QR
    # QR occupies x=qr_x to end, y=qr_y to qr_y+qr_size
    # Text lines that fall in QR y-zone are left-aligned (they naturally stay left)
    draw.text((PAD, y), f"Packed:       {req.packed_on}", font=font_dates, fill="black")
    y += LINE_DATE + GAP_SMALL
    draw.text((PAD, y), f"Best Before: {req.best_before}", font=font_dates, fill="black")
    y += LINE_DATE + GAP_SMALL
    draw.text((PAD, y), f"Batch:          {batch_no}", font=font_batch, fill="black")
    y += LINE_BATCH

    # ── Divider ───────────────────────────────────
    divider_y = y + GAP_DIVIDER
    draw.line([(0, divider_y), (LABEL_W_PX, divider_y)], fill="black", width=2)
    y = divider_y + GAP_DIVIDER

    # ── Bottom section — centered ─────────────────
    # fssai first — 20px bold
    draw_centered(draw, y, "FSSAI Lic. No. 13620011000563", font_fssai)
    y += 24
    # Address
    draw_centered(draw, y, "SRI RADHE TRADERS, BEGUM BAZAR, HYD.", font_bottom)
    y += LINE_BOTTOM + 4
    # Not For Retail last
    draw_centered(draw, y, "Not For Retail Sale | For Institutional Sale Only", font_bottom)

    return img


def image_to_tspl_bitmap(img, quantity=1):
    img_mono    = img.convert("1")
    w, h        = img_mono.size
    width_bytes = (w + 7) // 8
    pixel_data  = bytearray()
    pixels      = img_mono.load()

    for row_y in range(h):
        row = 0
        for x in range(w):
            bit = 0 if pixels[x, row_y] == 0 else 1
            row = (row << 1) | bit
            if (x + 1) % 8 == 0:
                pixel_data.append(row)
                row = 0
        remaining = w % 8
        if remaining:
            row = row << (8 - remaining)
            pixel_data.append(row)

    header = (
        f"SIZE 50 mm, 38 mm\r\n"
        f"GAP 2 mm, 0 mm\r\n"
        f"DIRECTION 1\r\n"
        f"CLS\r\n"
        f"BITMAP 0,0,{width_bytes},{h},0,"
    ).encode("ascii")

    return header + bytes(pixel_data) + f"\r\nPRINT {quantity},1\r\n".encode("ascii")


def print_label(req, batch_no: str) -> bool:
    try:
        img       = build_label_image(req, batch_no)
        tspl_data = image_to_tspl_bitmap(img, req.quantity)

        hPrinter = win32print.OpenPrinter(PRINTER_NAME)
        try:
            hJob = win32print.StartDocPrinter(hPrinter, 1, ("Label Job", None, "RAW"))
            try:
                win32print.StartPagePrinter(hPrinter)
                win32print.WritePrinter(hPrinter, tspl_data)
                win32print.EndPagePrinter(hPrinter)
            finally:
                win32print.EndDocPrinter(hPrinter)
        finally:
            win32print.ClosePrinter(hPrinter)
        return True
    except Exception as e:
        print(f"[Printer Error] {e}")
        return False


def get_printer_status() -> str:
    try:
        hPrinter = win32print.OpenPrinter(PRINTER_NAME)
        info = win32print.GetPrinter(hPrinter, 2)
        win32print.ClosePrinter(hPrinter)
        status = info["Status"]
        if status == 0:
            return "🟢 Printer is online and ready."
        elif status & 0x00000080:
            return "🔴 Printer is offline."
        elif status & 0x00000010:
            return "🟡 Printer is busy."
        elif status & 0x00000002:
            return "🔴 Printer error."
        else:
            return f"🟡 Printer status code: {status}"
    except Exception as e:
        return f"🔴 Cannot connect to printer: {e}"