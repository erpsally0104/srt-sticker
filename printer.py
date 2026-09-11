import os
import threading
import win32print
from PIL import Image, ImageDraw, ImageFont
import qrcode
import textwrap
from parser import PrintRequest
from settings_manager import get_settings

PRINTER_NAME = "TSC TE244"

DPI = 203

# ── Label / media dimensions ──────────────────
LABEL_W_MM     = 50
LABEL_H_MM     = 40      # sticker height (updated from 38mm)
H_GAP_MM       = 1       # gap between the two stickers on a 2-up roll
EDGE_MARGIN_MM = 2       # blank margin on the left/right edges of a 2-up roll
V_GAP_MM       = 2       # vertical gap between rows (TSPL GAP)


def _mm_to_px(mm) -> int:
    return int(round(mm / 25.4 * DPI))


LABEL_W_PX     = _mm_to_px(LABEL_W_MM)      # ~400px
LABEL_H_PX     = _mm_to_px(LABEL_H_MM)      # ~320px
H_GAP_PX       = _mm_to_px(H_GAP_MM)        # ~8px
EDGE_MARGIN_PX = _mm_to_px(EDGE_MARGIN_MM)  # ~16px

# ── Double (2-up) media dimensions ────────────
# Layout across the roll: [margin][label][gap][label][margin]
DOUBLE_W_MM = EDGE_MARGIN_MM * 2 + LABEL_W_MM * 2 + H_GAP_MM   # 105mm total
DOUBLE_W_PX = EDGE_MARGIN_PX * 2 + LABEL_W_PX * 2 + H_GAP_PX


def _apply_geometry():
    """
    Refresh module-level geometry from user settings before a print.
    Callers hold _render_lock: the queue worker is not the only renderer,
    because /api/preview renders on a Flask request thread.
    The vertical gap depends on the currently selected roll type.
    """
    global LABEL_W_MM, LABEL_H_MM, H_GAP_MM, EDGE_MARGIN_MM, V_GAP_MM
    global LABEL_W_PX, LABEL_H_PX, H_GAP_PX, EDGE_MARGIN_PX, DOUBLE_W_MM, DOUBLE_W_PX

    s = get_settings()
    roll = s.get("roll_type", "single")

    LABEL_W_MM     = s.get("label_width_mm", 50)
    LABEL_H_MM     = s.get("label_height_mm", 40)
    H_GAP_MM       = s.get("double_gap_mm", 1)
    EDGE_MARGIN_MM = s.get("double_margin_mm", 2)
    V_GAP_MM       = s.get("double_vgap_mm", 2) if roll == "double" else s.get("single_vgap_mm", 2)

    LABEL_W_PX     = _mm_to_px(LABEL_W_MM)
    LABEL_H_PX     = _mm_to_px(LABEL_H_MM)
    H_GAP_PX       = _mm_to_px(H_GAP_MM)
    EDGE_MARGIN_PX = _mm_to_px(EDGE_MARGIN_MM)
    DOUBLE_W_MM    = EDGE_MARGIN_MM * 2 + LABEL_W_MM * 2 + H_GAP_MM
    DOUBLE_W_PX    = EDGE_MARGIN_PX * 2 + LABEL_W_PX * 2 + H_GAP_PX

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


def fit_font(draw, text, path, size, max_width, fallback=None, min_size=9):
    """
    Return the largest font at or below `size` whose `text` fits `max_width`.

    The company name and address are operator-editable and are mandatory
    declarations, so they must shrink to fit rather than run off the edge
    of the sticker.
    """
    while size > min_size:
        font = get_font(path, size, fallback)
        bbox = draw.textbbox((0, 0), text, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            return font
        size -= 1
    return get_font(path, min_size, fallback)


# ── FSSAI logo (Reg 5(7)(a)) ──────────────────
# The mark is a certification mark with fixed artwork — it is loaded from
# a file, never drawn here. Download the official logo from fssai.gov.in
# and save it as fssai_logo.png beside this module. A wordmark around
# 2.5:1 (w:h) sits best on the licence line; transparent PNG is fine.
FSSAI_LOGO_PATH = os.path.join(os.path.dirname(__file__), "fssai_logo.png")
FSSAI_LOGO_H    = 26   # px at 203 dpi ≈ 3.3 mm tall
# Alpha cut for the silhouette below. The mark is downscaled ~38x, so its
# edges land on part-transparent pixels; a low cut keeps them, which
# thickens every stroke by roughly half a dot. That matters because a
# 1-dot-wide line is the faintest mark a thermal head can make.
FSSAI_LOGO_ALPHA_T = 90

# ── Pre-printed veg mark keep-out ─────────────
# The label stock carries the veg/non-veg mark pre-printed in the top-right
# corner, on the same band as the product name. Reg 5(4)(c) sets a 6 mm
# minimum square for a principal display panel up to 100 cm², so that is
# what is reserved here — MEASURE THE STOCK and raise VEG_MARK_MM if the
# printed mark is larger, or a long product name will run across it.
VEG_MARK_MM     = 6
VEG_MARK_MARGIN = 6    # px of clear space between the name and the mark

_logo_cache = {}


def load_fssai_logo(height=FSSAI_LOGO_H, max_width=None):
    """
    Load fssai_logo.png, scaled to `height` px and reduced to pure black
    and white for the thermal head. `max_width`, when given, caps the width
    as well, and the height then shrinks to keep the artwork's proportions.

    The mark is reduced by its ALPHA channel, not its brightness. The FSSAI
    logo is multi-coloured -- an indigo wordmark between an orange rule and a
    green rule -- and a brightness threshold judges each colour separately.
    The orange rule sits at luminance 144, right on the old cut of 160, so it
    was dropped entirely and the mark printed without it. Every non-transparent
    pixel is part of the artwork regardless of its colour, so the alpha channel
    is the correct silhouette for the single-colour reproduction Reg 5(7)(a)
    allows -- and it reproduces the mark's shape exactly.

    Falls back to the brightness threshold when the artwork has no usable
    transparency (a flattened PNG or a JPEG), because there the alpha channel
    is opaque everywhere and would render as a solid black box.

    Returns None when the file is absent or unreadable, so the label falls
    back to a text-only licence line rather than failing to print. Cached on
    the file's mtime, so dropping new artwork in is picked up without
    restarting the bot.
    """
    try:
        mtime = os.path.getmtime(FSSAI_LOGO_PATH)
    except OSError:
        return None

    key = (height, max_width, FSSAI_LOGO_ALPHA_T, mtime)
    if key in _logo_cache:
        return _logo_cache[key]

    try:
        src = Image.open(FSSAI_LOGO_PATH)
        src = src.convert("RGBA")
        w, h = src.size
        target = (max(1, round(w * height / h)), height)
        if max_width and target[0] > max_width:
            target = (max_width, max(1, round(h * max_width / w)))

        alpha = src.split()[-1]
        if alpha.getextrema()[0] < 255:
            # Normal path: transparent background, so alpha is the artwork.
            mask = alpha.resize(target, Image.LANCZOS)
            logo = mask.point(lambda p: 0 if p >= FSSAI_LOGO_ALPHA_T else 255)
        else:
            # Opaque artwork -- fall back to brightness. Kept generous at 200
            # so the orange rule (luminance 144) survives this path too.
            flat = Image.new("RGB", src.size, "white")
            flat.paste(src, mask=alpha)
            grey = flat.resize(target, Image.LANCZOS).convert("L")
            logo = grey.point(lambda p: 0 if p < 200 else 255)

        logo = logo.convert("RGB")
    except Exception as e:
        print(f"[Printer Warning] Could not load {FSSAI_LOGO_PATH}: {e}")
        return None

    # Room for the licence line's logo and the logo sticker's. A size that
    # has gone stale (label resized, artwork replaced) ages out with the rest.
    if len(_logo_cache) >= 4:
        _logo_cache.clear()
    _logo_cache[key] = logo
    return logo


def build_label_image(req, batch_no):
    img  = Image.new("RGB", (LABEL_W_PX, LABEL_H_PX), color="white")
    draw = ImageDraw.Draw(img)

    # Product name: 42px normally, 40px for long names (> 15 chars) to reduce overflow
    product_font_size = 40 if len(req.product) > 15 else 42
    # The name is centred across the full label, so it grows towards BOTH
    # edges — the widest it can be while its right edge still clears the
    # pre-printed veg mark is twice the gap from the mark to the centre.
    veg_mark_left = LABEL_W_PX - _mm_to_px(VEG_MARK_MM) - VEG_MARK_MARGIN
    name_max_w    = 2 * veg_mark_left - LABEL_W_PX
    font_product  = fit_font(draw, req.product, FONT_BRITANNIC,
                             product_font_size, name_max_w, min_size=24)
    font_weight  = get_font(FONT_ARIAL_NB, 30, FONT_ARIAL_N)
    font_dates   = get_font(FONT_ARIAL_NB, 28, FONT_ARIAL_N)
    font_batch   = get_font(FONT_ARIAL_NB, 22, FONT_ARIAL_N)  # smaller to save space
    font_bottom  = get_font(FONT_ARIAL_NB, 16, FONT_ARIAL_N)

    # ── Mandatory declarations ────────────────────
    s = get_settings()
    fssai_number    = s.get("fssai_number",    "13620011000563")
    company_prefix  = s.get("company_prefix",  "Packed & Marketed by")
    company_name    = s.get("company_name",    "SRI RADHE TRADERS")
    company_address = s.get("company_address", "BEGUM BAZAR, HYDERABAD, TELANGANA - 500012")

    qr_data = " ".join([
        f"{req.product} {req.weight}",
        f"Batch:{batch_no}",
        f"Packed:{req.packed_on}",
        f"Use By:{req.best_before}",
        f"{company_name} FSSAI Lic. No.:{fssai_number}",
    ])
    qr_size = 110
    qr_img  = make_qr(qr_data).resize((qr_size, qr_size), Image.NEAREST)
    qr_x    = LABEL_W_PX - qr_size - 20   # pulled inward from right edge
    qr_y    = 65                           # below green dot
    img.paste(qr_img, (qr_x, qr_y))

    # ── Calculate total content height for vertical centering ──
    # Top section lines
    LINE_PRODUCT = product_font_size + 6   # approx text height for the chosen size
    LINE_WEIGHT  = 36   # font 30 height approx
    LINE_DATE    = 30   # font 28 height approx
    LINE_BATCH   = 26   # font 22 height approx (batch only)
    GAP_SMALL    = 6
    GAP_DIVIDER  = 7

    # Bottom section lines
    LINE_BOTTOM  = 20   # font 16 height approx
    # FSSAI licence, company name, company address, NOT FOR RETAIL SALE —
    # all four are mandatory, so the count is fixed.
    n_bottom_lines = 4

    # Top section total height
    top_h = (LINE_PRODUCT + GAP_SMALL +
             LINE_WEIGHT  + GAP_SMALL +
             LINE_DATE    + GAP_SMALL +   # Packed
             LINE_DATE    + GAP_SMALL +   # Use By
             LINE_BATCH)                  # Batch (smaller font)

    # Divider + bottom section
    bottom_h = GAP_DIVIDER + 2 + GAP_DIVIDER + (LINE_BOTTOM + 4) * n_bottom_lines

    total_h  = top_h + GAP_DIVIDER + bottom_h

    # Vertical start offset to center everything
    top_pad  = max(8, (LABEL_H_PX - total_h) // 2)

    # ── Draw top section ──────────────────────────
    PAD = 8
    y   = top_pad

    # Product name — centered full width
    draw_centered(draw, y, req.product, font_product)
    y += LINE_PRODUCT + GAP_SMALL

    # Net quantity — the Legal Metrology declaration, so it is labelled
    # "Net Wt." rather than "Weight"
    draw_centered(draw, y, f"Net Wt.: {req.weight}", font_weight, offset=-30)
    y += LINE_WEIGHT + GAP_SMALL

    # Dates — left aligned in two columns, clear of the QR block.
    # VALUE_X is fixed rather than space-padded so a wider fallback font
    # cannot push the value under the QR.
    VALUE_X = 145
    draw.text((PAD, y), "PACKED:", font=font_dates, fill="black")
    draw.text((VALUE_X, y), req.packed_on, font=font_dates, fill="black")
    y += LINE_DATE + GAP_SMALL
    draw.text((PAD, y), "USE BY:", font=font_dates, fill="black")
    draw.text((VALUE_X, y), req.best_before, font=font_dates, fill="black")
    y += LINE_DATE + GAP_SMALL
    draw.text((PAD, y), "BATCH:", font=font_batch, fill="black")
    draw.text((VALUE_X, y), batch_no, font=font_batch, fill="black")
    y += LINE_BATCH

    # ── Divider ───────────────────────────────────
    divider_y = y + GAP_DIVIDER
    draw.line([(0, divider_y), (LABEL_W_PX, divider_y)], fill="black", width=2)
    y = divider_y + GAP_DIVIDER

    # ── Bottom section — centered, all four mandatory ─
    TEXT_MAX_W = LABEL_W_PX - (PAD * 2)

    # Reg 5(7)(a): the FSSAI logo together with the licence number. Falls
    # back to a text-only line while the artwork file is missing, so the
    # printer never stops on account of it.
    logo = load_fssai_logo()
    if logo:
        LOGO_GAP  = 8
        lic_text  = f"Lic. No. {fssai_number}"
        lic_font  = fit_font(draw, lic_text, FONT_ARIAL_BD, 22,
                             TEXT_MAX_W - logo.width - LOGO_GAP, FONT_ARIAL_NB)
        bbox      = draw.textbbox((0, 0), lic_text, font=lic_font)
        group_w   = logo.width + LOGO_GAP + (bbox[2] - bbox[0])
        gx        = max(PAD, (LABEL_W_PX - group_w) // 2)
        # Sit the logo on the text's optical centre, not its box top
        logo_y = int(y + (bbox[1] + bbox[3]) / 2 - logo.height / 2)
        img.paste(logo, (gx, logo_y))
        draw.text((gx + logo.width + LOGO_GAP, y), lic_text, font=lic_font, fill="black")
    else:
        fssai_text = f"FSSAI Lic. No. {fssai_number}"
        draw_centered(draw, y, fssai_text,
                      fit_font(draw, fssai_text, FONT_ARIAL_BD, 22, TEXT_MAX_W, FONT_ARIAL_NB))
    y += 24

    # Reg 5(6)(a): name preceded by the qualifying phrase, then the
    # complete address on the following line.
    name_text = f"{company_prefix}: {company_name}"
    draw_centered(draw, y, name_text,
                  fit_font(draw, name_text, FONT_ARIAL_NB, 16, TEXT_MAX_W, FONT_ARIAL_N))
    y += LINE_BOTTOM + 4

    draw_centered(draw, y, company_address,
                  fit_font(draw, company_address, FONT_ARIAL_NB, 16, TEXT_MAX_W, FONT_ARIAL_N))
    y += LINE_BOTTOM + 4

    # Reg 10(4) requires this exact wording, in capitals
    draw_centered(draw, y, "NOT FOR RETAIL SALE", font_bottom)

    return img


def _wrap_text_pixel(draw, text, font, max_width):
    """
    Word-wrap text based on actual pixel width measurement (not char count).
    Returns a list of lines that each fit within max_width pixels.
    """
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}".strip() if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            current_line = test_line
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines


def build_ingredients_label_image(req):
    """
    Build an ingredients-only sticker that fills the full 50x38mm label.
    "Ingredients :" as bold header, then the text in a large font,
    auto-sized to occupy as much of the label as possible.
    """
    img  = Image.new("RGB", (LABEL_W_PX, LABEL_H_PX), color="white")
    draw = ImageDraw.Draw(img)

    PAD = 6  # minimal padding to use full width

    font_title = get_font(FONT_ARIAL_BD, 30)

    # Draw "Ingredients :" header
    title_text = "Ingredients :"
    draw.text((PAD, PAD), title_text, font=font_title, fill="black")
    title_bbox = draw.textbbox((0, 0), title_text, font=font_title)
    title_h = title_bbox[3] - title_bbox[1]
    body_y_start = PAD + title_h + 6

    max_text_width = LABEL_W_PX - (PAD * 2)
    available_h = LABEL_H_PX - body_y_start - PAD

    # Auto-size: try font sizes from large to small, pick the biggest that fits
    best_font_size = 18
    for size in range(32, 17, -1):
        test_font = get_font(FONT_ARIAL, size)
        wrapped = _wrap_text_pixel(draw, req.ingredients, test_font, max_text_width)
        line_bbox = draw.textbbox((0, 0), "Ag", font=test_font)
        line_h = (line_bbox[3] - line_bbox[1]) + 3
        total_h = line_h * len(wrapped)
        if total_h <= available_h:
            best_font_size = size
            break

    font_body = get_font(FONT_ARIAL, best_font_size)
    wrapped_lines = _wrap_text_pixel(draw, req.ingredients, font_body, max_text_width)
    line_bbox = draw.textbbox((0, 0), "Ag", font=font_body)
    line_h = (line_bbox[3] - line_bbox[1]) + 3

    y = body_y_start
    for line in wrapped_lines:
        if y + line_h > LABEL_H_PX - PAD:
            break
        draw.text((PAD, y), line, font=font_body, fill="black")
        y += line_h

    return img


# ── FSSAI logo sticker ────────────────────────
# Carries only the FSSAI logo and a licence number. Both are sized from
# the label rather than fixed, so the pair still fills the sticker if the
# label size in settings changes.
FSSAI_STICKER_MARGIN_MM = 2      # clear space kept on every edge
FSSAI_STICKER_TRACKING  = 0.04   # extra space between digits, in em
FSSAI_STICKER_GAP       = 0.45   # logo-to-number gap, as a share of digit height


def _tracked_bbox(draw, text, font, tracking):
    """Ink box of `text` with `tracking` px added after each character, baseline at y=0."""
    boxes, x = [], 0
    for ch in text:
        boxes.append(draw.textbbox((x, 0), ch, font=font, anchor="ls"))
        x += font.getlength(ch) + tracking
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _fit_sticker_number(draw, text, max_width):
    """
    Largest Arial Narrow Bold size at which the tracked `text` fits
    `max_width`. Returns (font, tracking_px, ink_box).
    """
    lo, hi, best = 8, 300, None
    while lo <= hi:
        size     = (lo + hi) // 2
        font     = get_font(FONT_ARIAL_NB, size, FONT_ARIAL_BD)
        tracking = round(size * FSSAI_STICKER_TRACKING)
        box      = _tracked_bbox(draw, text, font, tracking)
        if box[2] - box[0] <= max_width:
            best, lo = (font, tracking, box), size + 1
        else:
            hi = size - 1
    if best is None:
        font = get_font(FONT_ARIAL_NB, 8, FONT_ARIAL_BD)
        best = (font, 0, _tracked_bbox(draw, text, font, 0))
    return best


def build_fssai_label_image(req):
    """
    Build an FSSAI logo sticker: the logo as large as the label allows,
    and the licence number on one line beneath it, set to the logo's width.
    Nothing else is printed.
    """
    img  = Image.new("RGB", (LABEL_W_PX, LABEL_H_PX), color="white")
    draw = ImageDraw.Draw(img)

    margin = _mm_to_px(FSSAI_STICKER_MARGIN_MM)
    box_w  = LABEL_W_PX - 2 * margin
    box_h  = LABEL_H_PX - 2 * margin
    number = req.fssai_number

    # The logo is the whole point of this sticker, so missing artwork fails
    # the job rather than printing a bare number.
    logo = load_fssai_logo(height=box_h, max_width=box_w)
    if logo is None:
        raise RuntimeError(f"FSSAI logo artwork missing or unreadable: {FSSAI_LOGO_PATH}")

    font, tracking, box = _fit_sticker_number(draw, number, logo.width)
    num_h = box[3] - box[1]
    gap   = round(num_h * FSSAI_STICKER_GAP)

    # A wide, short label runs out of height before width: shrink the logo
    # to leave room for the number, then refit the number to the new width.
    if logo.height + gap + num_h > box_h:
        logo = load_fssai_logo(height=box_h - gap - num_h, max_width=box_w)
        font, tracking, box = _fit_sticker_number(draw, number, logo.width)
        num_h = box[3] - box[1]
        gap   = round(num_h * FSSAI_STICKER_GAP)

    # Centre the logo and number as one group
    top = (LABEL_H_PX - (logo.height + gap + num_h)) // 2
    img.paste(logo, ((LABEL_W_PX - logo.width) // 2, top))

    x = (LABEL_W_PX - (box[2] - box[0])) // 2 - box[0]
    y = top + logo.height + gap - box[1]    # baseline that puts the digits' top `gap` below the logo
    for ch in number:
        draw.text((x, y), ch, font=font, fill="black", anchor="ls")
        x += font.getlength(ch) + tracking

    # Threshold rather than leave it to _pack_mono(), whose dithering turns
    # the anti-aliased edges of type this large into speckle.
    return img.convert("L").point(lambda p: 0 if p < 128 else 255).convert("RGB")


# Geometry lives in module globals that _apply_geometry() rewrites, so a
# preview must not re-point them halfway through the worker's render.
_render_lock = threading.RLock()


def render_label(req, batch_no: str = ""):
    """Render a single label (product, ingredients or FSSAI logo) to a PIL image."""
    with _render_lock:
        _apply_geometry()
        if req.label_type == "ingredients":
            return build_ingredients_label_image(req)
        if req.label_type == "fssai":
            return build_fssai_label_image(req)
        return build_label_image(req, batch_no)


def _pack_mono(img):
    """
    Convert a PIL image into a 1-bit TSPL bitmap.
    Returns (width_bytes, height, pixel_bytes).
    """
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

    return width_bytes, h, bytes(pixel_data)


def _tspl_header(size_w_mm, size_h_mm) -> bytes:
    return (
        f"SIZE {size_w_mm} mm, {size_h_mm} mm\r\n"
        f"GAP {V_GAP_MM} mm, 0 mm\r\n"
        f"DIRECTION 1\r\n"
    ).encode("ascii")


def _bitmap_block(img, quantity: int = 1) -> bytes:
    """One CLS + BITMAP + PRINT block (a single printed form)."""
    width_bytes, h, data = _pack_mono(img)
    return (
        b"CLS\r\n"
        + f"BITMAP 0,0,{width_bytes},{h},0,".encode("ascii")
        + data
        + f"\r\nPRINT {quantity},1\r\n".encode("ascii")
    )


def _compose_double_row(left_img, right_img=None):
    """
    Place one or two labels on a 2-up (105mm) canvas.
    Layout across the roll: [2mm margin][left label][1mm gap][right label][2mm margin].
    """
    canvas = Image.new("RGB", (DOUBLE_W_PX, LABEL_H_PX), color="white")
    if left_img is not None:
        canvas.paste(left_img, (EDGE_MARGIN_PX, 0))
    if right_img is not None:
        canvas.paste(right_img, (EDGE_MARGIN_PX + LABEL_W_PX + H_GAP_PX, 0))
    return canvas


def _send_to_printer(tspl_data: bytes) -> bool:
    try:
        hPrinter = win32print.OpenPrinter(PRINTER_NAME)
        try:
            win32print.StartDocPrinter(hPrinter, 1, ("Label Job", None, "RAW"))
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


def print_label(req, batch_no: str = "") -> bool:
    """Single-roll path: print `req.quantity` identical labels, one per row."""
    try:
        with _render_lock:
            img  = render_label(req, batch_no)
            tspl = _tspl_header(LABEL_W_MM, LABEL_H_MM) + _bitmap_block(img, req.quantity)
    except Exception as e:
        print(f"[Printer Error] {e}")
        return False
    return _send_to_printer(tspl)


def print_double_rows(rows) -> bool:
    """
    Double-roll path: print a sequence of 2-up rows.
    `rows` is a list of (left_img, right_img_or_None) tuples — one printed form each.
    """
    if not rows:
        return True
    try:
        with _render_lock:
            _apply_geometry()
            tspl = _tspl_header(DOUBLE_W_MM, LABEL_H_MM)
            for left_img, right_img in rows:
                canvas = _compose_double_row(left_img, right_img)
                tspl += _bitmap_block(canvas, quantity=1)
    except Exception as e:
        print(f"[Printer Error] {e}")
        return False
    return _send_to_printer(tspl)


# winspool PRINTER_STATUS_* bits. The old code read 0x10 as "busy", but
# 0x10 is PAPER_OUT — busy is 0x200 and printing is 0x400. A printer that
# was merely mid-job therefore reported as a fault.
# PRINTER_ATTRIBUTE_WORK_OFFLINE. Lives in Attributes, not Status — with it
# set, GetPrinter reports Status 0 while the spooler holds every job.
_ATTR_WORK_OFFLINE = 0x00000400

# A couple of jobs in flight is normal; a pile means one is wedged at the
# head of the queue and everything behind it is blocked.
_STUCK_JOB_THRESHOLD = 5

_ST_PAUSED    = 0x00000001
_ST_ERROR     = 0x00000002
_ST_PAPER_JAM = 0x00000008
_ST_PAPER_OUT = 0x00000010
_ST_OFFLINE   = 0x00000080
_ST_IO_ACTIVE = 0x00000100
_ST_BUSY      = 0x00000200
_ST_PRINTING  = 0x00000400
_ST_DOOR_OPEN = 0x00400000
_ST_POWER_SAVE = 0x01000000

# States that mean "working normally", not "broken". Treating these as
# faults is what made the UI sit on Offline while the printer was fine.
_ST_HEALTHY = _ST_IO_ACTIVE | _ST_BUSY | _ST_PRINTING | _ST_POWER_SAVE


def check_printer():
    """
    Returns (online: bool, message: str).

    `online` means jobs will print — a busy or actively printing printer
    is online. Only a real fault or a missing printer is offline.
    """
    try:
        hPrinter = win32print.OpenPrinter(PRINTER_NAME)
        try:
            info = win32print.GetPrinter(hPrinter, 2)
        finally:
            win32print.ClosePrinter(hPrinter)
    except Exception as e:
        return False, f"🔴 Cannot connect to printer '{PRINTER_NAME}': {e}"

    # Attributes and cJobs are checked BEFORE Status, because the two faults
    # they catch both leave Status at 0 — the app reported "online and ready"
    # for a printer Windows was silently swallowing every job for.
    if info.get("Attributes", 0) & _ATTR_WORK_OFFLINE:
        return False, ("🔴 Windows has this printer set to 'Use Printer Offline'. "
                       "Untick it in Devices & Printers — jobs are being queued, not printed.")

    queued = info.get("cJobs", 0) or 0
    if queued > _STUCK_JOB_THRESHOLD:
        return False, (f"🔴 {queued} jobs are stuck in the Windows print queue. "
                       "Clear it — new labels will queue behind them and never print.")

    status = info["Status"]

    if status == 0:
        return True, "🟢 Printer is online and ready."
    if status & _ST_OFFLINE:
        return False, "🔴 Printer is offline — check power and the USB cable."
    if status & _ST_PAPER_OUT:
        return False, "🔴 Out of labels."
    if status & _ST_PAPER_JAM:
        return False, "🔴 Label jam."
    if status & _ST_DOOR_OPEN:
        return False, "🔴 Printer cover is open."
    if status & _ST_ERROR:
        return False, "🔴 Printer error."
    if status & _ST_PAUSED:
        return False, "🔴 Printer is paused in Windows — resume it from Devices & Printers."
    if status & _ST_PRINTING:
        return True, "🟢 Printer is online — printing."
    if status & _ST_BUSY or status & _ST_IO_ACTIVE:
        return True, "🟢 Printer is online — busy."
    if status & ~_ST_HEALTHY == 0:
        return True, "🟢 Printer is online and ready."

    # Unknown flag: report it rather than guessing it is a fault
    return True, f"🟡 Printer is online — unrecognised status code {status}."


def get_printer_status() -> str:
    return check_printer()[1]