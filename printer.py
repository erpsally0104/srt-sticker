import functools
import math
import os
import re
import threading
import win32print
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter
import qrcode
import textwrap
from parser import PrintRequest
from settings_manager import (get_settings, normalize_roll_type, get_print_settings, get_print_offset,
                              LABEL_TEXT_DEFAULTS)

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

# ── Print quality and offset ──────────────────
# Sent with every job rather than left to whatever the printer was last set
# to. The offset moves the roll's whole print right and down (negative for
# left and up), to square it on the pre-printed stock.
PRINT_DENSITY = 8        # TSPL DENSITY: 0 (lightest) to 15 (darkest)
PRINT_SPEED   = 3        # TSPL SPEED: inches per second
OFFSET_X_PX   = 0        # dots
OFFSET_Y_PX   = 0


def _apply_geometry(roll=None) -> str:
    """
    Refresh module-level geometry from user settings before a print.
    Callers hold _render_lock: the queue worker is not the only renderer,
    because /api/preview renders on a Flask request thread.

    `roll` is the label type being rendered: the large roll has its own
    label size and gap, and the 2-up roll its own vertical gap. None or ""
    means the default label type from settings. Returns the type applied.
    """
    global LABEL_W_MM, LABEL_H_MM, H_GAP_MM, EDGE_MARGIN_MM, V_GAP_MM
    global LABEL_W_PX, LABEL_H_PX, H_GAP_PX, EDGE_MARGIN_PX, DOUBLE_W_MM, DOUBLE_W_PX
    global PRINT_DENSITY, PRINT_SPEED, OFFSET_X_PX, OFFSET_Y_PX

    s = get_settings()
    roll = normalize_roll_type(roll) or normalize_roll_type(s.get("roll_type")) or "single"

    H_GAP_MM       = s.get("double_gap_mm", 1)
    EDGE_MARGIN_MM = s.get("double_margin_mm", 2)
    if roll == "large":
        LABEL_W_MM = s.get("large_width_mm", 75)
        LABEL_H_MM = s.get("large_height_mm", 50)
        V_GAP_MM   = s.get("large_vgap_mm", 2)
    else:
        LABEL_W_MM = s.get("label_width_mm", 50)
        LABEL_H_MM = s.get("label_height_mm", 40)
        V_GAP_MM   = s.get("double_vgap_mm", 2) if roll == "double" else s.get("single_vgap_mm", 2)

    LABEL_W_PX     = _mm_to_px(LABEL_W_MM)
    LABEL_H_PX     = _mm_to_px(LABEL_H_MM)
    H_GAP_PX       = _mm_to_px(H_GAP_MM)
    EDGE_MARGIN_PX = _mm_to_px(EDGE_MARGIN_MM)
    DOUBLE_W_MM    = EDGE_MARGIN_MM * 2 + LABEL_W_MM * 2 + H_GAP_MM
    DOUBLE_W_PX    = EDGE_MARGIN_PX * 2 + LABEL_W_PX * 2 + H_GAP_PX

    quality        = get_print_settings()
    PRINT_DENSITY  = quality["print_density"]
    PRINT_SPEED    = quality["print_speed"]
    dx, dy         = get_print_offset(roll)
    OFFSET_X_PX    = _mm_to_px(dx)
    OFFSET_Y_PX    = _mm_to_px(dy)
    return roll

# ── Typefaces ─────────────────────────────────
# Every line but the brand is set in Bahnschrift, so the label reads as one
# design. It is a DIN-style face made for signs and ships with Windows 10
# and later as one variable font: a face here is (file, named style), and
# its condensed widths are what let a long product name keep its full
# height. Its strokes are even, with no hairlines for the head to
# under-burn. Arial stands in should the font ever be missing.
FONT_TEXT     = r"C:\Windows\Fonts\bahnschrift.ttf"
TEXT_BOLD     = (FONT_TEXT, "Bold")                 # values, licence, non-retail statement
TEXT_BOLD_SC  = (FONT_TEXT, "Bold SemiCondensed")   # keys, small lines, allergens, address
TEXT_REGULAR  = (FONT_TEXT, "Regular")              # ingredients text
FONT_ARIAL_NB = r"C:\Windows\Fonts\ARIALNB.TTF"
FONT_ARIAL    = r"C:\Windows\Fonts\arial.ttf"
FONT_ARIAL_BD = r"C:\Windows\Fonts\arialbd.ttf"
# Brand on the large label. Copperplate's strokes are even and heavy, which
# a 203 dpi head needs: a face with hairline serifs prints them as 1-dot
# lines, which under-burn grey and broken. Georgia Bold ships with
# Windows, so it stands in if Office's Copperplate is missing.
FONT_BRAND     = r"C:\Windows\Fonts\COPRGTB.TTF"
FONT_GEORGIA_BD = r"C:\Windows\Fonts\georgiab.ttf"


def get_font(face, size, fallback=None):
    """
    `face` at `size` px. A face is a font file, or (file, style) for a named
    style of a variable font. Falls back to `fallback`, then to Arial.
    """
    for f in (face, fallback):
        if f:
            try:
                return _load_font(f, size)
            except Exception:
                pass
    return _load_font(FONT_ARIAL, size)


@functools.lru_cache(maxsize=512)
def _load_font(face, size):
    # Cached: fitting a product name tries dozens of sizes and widths, and a
    # variable font's style has to be set on every copy loaded
    path, style = face if isinstance(face, tuple) else (face, None)
    font = ImageFont.truetype(path, size)
    if style:
        font.set_variation_by_name(style)
    return font


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


# Space above a line's capitals, as a share of its size. The small label
# lays its rows out by their top edge and its spacing is tuned to where the
# capitals sit, so text is placed by this rule rather than by the face's
# own ascent, which differs from one face to the next.
LINE_LEAD = 0.25


def _baseline(draw, y, font, lead=LINE_LEAD):
    """Baseline of a line of text whose row starts at y."""
    return y + round(font.size * lead) - _cap_top(draw, font)


def draw_centered(draw, y, text, font, max_width=None, offset=0):
    """Draw text horizontally centered. offset nudges left (negative) or right (positive)."""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    w = max_width if max_width else LABEL_W_PX
    x = (w - text_w) // 2 + offset
    draw.text((x, _baseline(draw, y, font)), text, font=font, fill="black", anchor="ls")
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
# 30 px at 203 dpi ≈ 3.75 mm tall (61 px ≈ 7.6 mm wide). No FSSAI regulation
# prescribes a minimum size for the mark itself — Reg 5(7)(a) asks only that it
# be "displayed ... in contrast color to the background", i.e. that it print
# solid — so this is chosen on legibility and fit, not on a legal minimum.
# 30 is the practical ceiling: the logo is centred on the licence text's
# optical centre and occupies rows 213-242, between the divider rule (rows
# 209-210) and the company-name line. See build_label_image().
FSSAI_LOGO_H = 30

# Alpha cut for the silhouette. The mark is multi-coloured — an indigo wordmark
# between an orange rule and a green rule — so a brightness threshold judges
# each colour separately and can drop the orange rule (luminance 144) whole.
# Every non-transparent pixel is artwork regardless of colour, so alpha is the
# correct silhouette for the single-colour reproduction Reg 5(7)(a) allows.
FSSAI_LOGO_ALPHA_T = 90

# Fallback cut for flattened artwork (no usable alpha). Distance from white,
# 255 - min(R,G,B), NOT luminance: it clusters the three brand inks at 205-231
# where luminance spreads them over 59-144.
FSSAI_LOGO_INK_T = 64

# ── Stroke weight (this is the "make it darker" control) ────────────────
# At 203 dpi a 1-dot line is the faintest mark the head can make: it under-
# burns and prints grey and patchy, which is what "the logo is too dull"
# actually was. Both full-width rules in this wordmark resolve to exactly one
# dot if the artwork is simply downscaled, at every height that fits the label.
# So: binarise at SOURCE resolution, upscale SS×, dilate ONE pixel there (= half
# a dot at final size, unlike a MaxFilter at final size, which grows a whole
# dot, fuses the letters into the rules and destroys the prescribed artwork),
# then area-average down and decide each final dot on coverage. Measured at
# H=30: 34.7% ink, both rules 2 dots, 3.3% of horizontal ink runs left at 1 px
# (was 26.5% / 1 dot / 11.9%).
FSSAI_LOGO_SS     = 4     # supersample factor; must be >=4 — at 2 the dilate blobs
FSSAI_LOGO_DILATE = 1     # px at SS scale; 2 closes the letterforms
FSSAI_LOGO_COV    = 128   # a final dot is ink if >=50% covered. Lower = bolder
                          # (96 -> 36.3%). Do NOT raise above 128: at 160 both
                          # rules collapse back to 1 dot and the fault returns.

# ── Pre-printed veg mark keep-out ─────────────
# The label stock carries the veg/non-veg mark pre-printed in the top-right
# corner, on the same band as the product name. Reg 5(4)(c) sets a 6 mm
# minimum square for a principal display panel up to 100 cm², so that is
# what is reserved here — MEASURE THE STOCK and raise VEG_MARK_MM if the
# printed mark is larger, or a long product name will run across it.
VEG_MARK_MM     = 6
VEG_MARK_MARGIN = 6    # px of clear space between the name and the mark

_logo_cache = {}


def load_fssai_logo(height=None, max_width=None):
    """
    Load fssai_logo.png, scaled to `height` px and reduced to pure black
    and white with strokes thick enough for the thermal head. `max_width`,
    when given, caps the width as well, and the height then shrinks to keep
    the artwork's proportions.

    WHAT IS INK (source resolution). The mark is reduced by its ALPHA channel,
    not its brightness: the logo is multi-coloured and a brightness threshold
    judges each colour separately -- the orange rule sits at luminance 144,
    right on the old cut of 160, and was dropped entirely, printing the mark
    without it. Every non-transparent pixel is artwork whatever its colour, so
    alpha is the exact silhouette for the single-colour reproduction that
    Reg 5(7)(a) allows. Flattened artwork (no usable alpha) falls back to
    255 - min(R,G,B), which is distance from white and treats all three brand
    inks alike; plain luminance does not.

    HOW WIDE (intermediate resolution). Thresholding first and only then
    resampling is deliberate. The mark is reduced ~33x, and a downscale of
    greyscale art blends stroke edges below the cut, leaving 1-dot hairlines --
    the real cause of "the logo is too dull", because a 1-dot line under-burns
    on a 203 dpi head and prints grey and broken. Both full-width rules in the
    wordmark come out exactly one dot tall at every height that fits this
    label. Dilating by one pixel on an SS-times-oversampled grid thickens every
    feature by half a dot, which lifts both rules to 2 dots without fusing the
    letters into them. A MaxFilter at final resolution grows a whole dot
    instead and collapses the wordmark into a slab -- that misrepresents the
    prescribed artwork and fails Reg 5(7)(a) from the other side.

    IS THIS DOT INK (final resolution). The BOX downscale turns the dilated
    silhouette into per-dot coverage; FSSAI_LOGO_COV decides. Everything the
    printer sees is then pure 0/255, which matters because the finished label
    goes through img.convert("1"), i.e. Floyd-Steinberg. Pure black/white
    survives that untouched (verified: zero pixels flipped), but a greyscale
    logo would be dithered into scattered single dots -- exactly the
    under-burning being fixed here. Keep this threshold before the paste.

    `height` is resolved at call time, not bound at import, so editing
    FSSAI_LOGO_H (or sweeping heights from a REPL) actually takes effect.

    Returns None when the file is absent or unreadable, so the label falls
    back to a text-only licence line rather than failing to print. Cached on
    the file's mtime and on every tuning constant, so dropping new artwork in
    -- or changing a constant -- is picked up without restarting the bot.
    """
    if height is None:
        height = FSSAI_LOGO_H

    try:
        mtime = os.path.getmtime(FSSAI_LOGO_PATH)
    except OSError:
        return None

    key = (height, max_width, FSSAI_LOGO_ALPHA_T, FSSAI_LOGO_INK_T,
           FSSAI_LOGO_SS, FSSAI_LOGO_DILATE, FSSAI_LOGO_COV, mtime)
    if key in _logo_cache:
        return _logo_cache[key]

    try:
        src = Image.open(FSSAI_LOGO_PATH)
        # Mode P carries its transparency in .info, so test for it explicitly:
        # converting straight to RGB would silently discard the alpha and turn
        # the whole mark into a solid black box.
        if src.mode in ("RGBA", "LA", "P") or "transparency" in src.info:
            src = src.convert("RGBA")
        else:
            src = src.convert("RGB")

        sw, sh = src.size
        # Never set width and height independently -- the mark is a
        # certification mark with fixed artwork and must not be distorted.
        w = max(1, round(sw * height / sh))
        if max_width and w > max_width:
            w, height = max_width, max(1, round(sh * max_width / sw))

        alpha = src.getchannel("A") if src.mode == "RGBA" else None
        if alpha is not None and alpha.getextrema()[0] < 255:
            mask = alpha.point(lambda p: 255 if p >= FSSAI_LOGO_ALPHA_T else 0)
        else:
            # Opaque artwork: composite onto white first, or the transparent
            # backdrop's own colour would read as ink.
            flat = Image.new("RGB", src.size, "white")
            if alpha is not None:
                flat.paste(src, mask=alpha)
            else:
                flat.paste(src)
            r, g, b = flat.split()
            ink  = ImageChops.invert(ImageChops.darker(ImageChops.darker(r, g), b))
            mask = ink.point(lambda p: 255 if p >= FSSAI_LOGO_INK_T else 0)

        # NOTE the polarity flip: `mask` is 255 = ink (so MaxFilter dilates the
        # artwork), while the label canvas is 0 = ink. The final point()
        # inverts it back.
        ss  = FSSAI_LOGO_SS
        big = mask.resize((w * ss, height * ss), Image.Resampling.BOX)
        big = big.point(lambda p: 255 if p >= 128 else 0)
        if FSSAI_LOGO_DILATE:
            big = big.filter(ImageFilter.MaxFilter(2 * FSSAI_LOGO_DILATE + 1))
        cov  = big.resize((w, height), Image.Resampling.BOX)
        logo = cov.point(lambda p: 0 if p >= FSSAI_LOGO_COV else 255).convert("RGB")
    except Exception as e:
        print(f"[Printer Warning] Could not load {FSSAI_LOGO_PATH}: {e}")
        return None

    # Room for the licence line's logo and the logo sticker's. A size that
    # has gone stale (label resized, artwork replaced) ages out with the rest.
    if len(_logo_cache) >= 4:
        _logo_cache.clear()
    _logo_cache[key] = logo
    return logo


def _non_retail_text(settings):
    """
    Reg 10(4): the statement that marks the pack as not for sale to
    consumers, worded as set in Settings. Never blank: it is mandatory.
    """
    return settings.get("non_retail_text") or LABEL_TEXT_DEFAULTS["non_retail_text"]


def _qr_data(req, batch_no, company_name, fssai_number):
    parts = [
        f"{req.product} {req.weight}",
        f"Batch:{batch_no}",
        f"Packed:{req.packed_on}",
        f"Use By:{req.best_before}",
        f"{company_name} FSSAI Lic. No.:{fssai_number}",
    ]
    if req.allergens:
        parts.append(f"Contains:{req.allergens}")
    # Upper case lets the QR use its alphanumeric mode, which packs about
    # 1.6x more per module than bytes: with an allergen line and a long
    # English name the data no longer fits version 6 otherwise, and the
    # code prints with smaller modules.
    return " ".join(parts).upper()


def _fit_tracked(text, path, fallback, size, min_size, max_w, tracking=1):
    """Largest font from `size` down to `min_size` at which tracked `text` fits max_w, or None."""
    for s in range(size, min_size - 1, -1):
        font = get_font(path, s, fallback)
        if _tracked_width(text, font, tracking) <= max_w:
            return font
    return None


def _draw_allergen_pill(draw, x, cy, allergens, max_w, size, height, min_size=10, filled=True):
    """
    "CONTAINS: ..." white on a black pill, or with filled=False black inside
    a pill outline, its left edge at x and centred on cy, the text at most
    `size` px and shrunk until the pill fits max_w.
    Semi-condensed: at a given width it can be set a size or two larger
    than the full width, which is what keeps a long allergen line legible.

    Too long to stay readable — "GLUTEN (WHEAT), TREE NUTS (CASHEW)" beside
    the small label's QR — it drops the bracketed detail to "GLUTEN, TREE
    NUTS" rather than shrink further: which allergens matter more than
    their sources, and the pill must never run into the QR. Any 40-character
    allergen line fits once shortened. Returns the x the pill ends at.
    """
    full  = f"CONTAINS: {allergens}"
    short = "CONTAINS: " + re.sub(r"\s*\([^)]*\)", "", allergens)
    text, font = full, _fit_tracked(full, TEXT_BOLD_SC, FONT_ARIAL_NB, size, min_size + 2, max_w - height)
    if font is None:
        text, font = short, _fit_tracked(short, TEXT_BOLD_SC, FONT_ARIAL_NB, size, min_size, max_w - height)
    if font is None:
        text, font = full, _fit_tracked(full, TEXT_BOLD_SC, FONT_ARIAL_NB, min_size + 1, min_size, max_w - height)
    font = font or get_font(TEXT_BOLD_SC, min_size, FONT_ARIAL_NB)
    w   = _tracked_width(text, font, 1) + height
    box = (x, cy - height / 2, x + w, cy + height / 2)
    if filled:
        draw.rounded_rectangle(box, radius=height // 2, fill="black")
    else:
        draw.rounded_rectangle(box, radius=height // 2, outline="black", width=2)
    _draw_tracked(draw, x + height / 2, cy - _cap_top(draw, font) / 2, text, font, 1,
                  "white" if filled else "black")
    return x + w


# ── Text set in parts ─────────────────────────
# A product name or net weight is set as parts on one baseline, each part
# (text, font, gap): `gap` px of space before it. That is what lets the
# familiar name in a product name, and the unit in a weight, sit a size
# down from the text they follow.
def _parts_extent(draw, parts):
    """Ink (left, right) of the parts set from x=0, and the x each part starts at."""
    xs, x, left, right = [], 0, None, None
    for text, font, gap in parts:
        x += gap
        l, _, r, _ = draw.textbbox((x, 0), text, font=font, anchor="ls")
        left  = l if left is None else min(left, l)
        right = r if right is None else max(right, r)
        xs.append(x)
        x += draw.textlength(text, font=font)
    return left, right, xs


def _parts_width(draw, parts):
    left, right, _ = _parts_extent(draw, parts)
    return right - left


def _draw_parts(img, draw, parts, x0, x1, baseline, centre=None, fill="black"):
    """
    The parts on `baseline`, centred on `centre` (the middle of x0..x1 if
    not given) as far as that span allows; centre=x0 sets them flush left.
    Wider than the span, they are squeezed sideways to it: everything set
    this way is a mandatory declaration, which must neither run off the
    label nor be cut short.
    """
    left, right, xs = _parts_extent(draw, parts)
    if right - left <= x1 - x0:
        c  = (x0 + x1) / 2 if centre is None else centre
        ox = min(max(c - (left + right) / 2, x0 - left), x1 - right)
        for (text, font, _), x in zip(parts, xs):
            draw.text((ox + x, baseline), text, font=font, fill=fill, anchor="ls")
        return
    boxes  = [draw.textbbox((x, 0), t, font=f, anchor="ls") for (t, f, _), x in zip(parts, xs)]
    top    = min(b[1] for b in boxes)
    mask   = Image.new("L", (math.ceil(right - left), math.ceil(max(b[3] for b in boxes) - top)), 0)
    md     = ImageDraw.Draw(mask)
    for (text, font, _), x in zip(parts, xs):
        md.text((x - left, -top), text, font=font, fill=255, anchor="ls")
    mask = mask.resize((max(1, int(x1 - x0)), mask.height), Image.Resampling.BOX)
    img.paste(fill, (int(x0), round(baseline + top)), mask)


# ── Product name ──────────────────────────────
# Set as large as its row allows. A long name narrows through NAME_WIDTHS
# before it shrinks, giving up each width only once it would drop below
# NAME_NARROW_AT of full size, so names across the range print at one
# height. A familiar name in brackets after it is set a size down
# (TIER_SCALE), so the English name leads: SEMOLINA (RAVA).
NAME_WIDTHS    = ("Bold", "Bold SemiCondensed", "Bold Condensed")
NAME_NARROW_AT = 0.9
TIER_SCALE     = 0.7


def _split_familiar(name):
    """'SEMOLINA (RAVA)' -> ('SEMOLINA', '(RAVA)'); a name that does not end in brackets -> (name, '')."""
    m = re.match(r"^(.*\S)\s*(\([^()]*\))$", name)
    return m.groups() if m else (name, "")


def _name_parts(draw, text, familiar, width, size):
    """A name line's parts at `size` in one of NAME_WIDTHS, the familiar name a size down."""
    font  = get_font((FONT_TEXT, width), size, FONT_ARIAL_BD)
    parts = [(text, font, 0)]
    if familiar:
        tier = get_font((FONT_TEXT, width.replace("Bold", "SemiBold")), round(size * TIER_SCALE), FONT_ARIAL_BD)
        parts.append((familiar, tier, draw.textlength(" ", font=font)))
    return parts


def _name_sizes(top, bottom):
    """(width, size) pairs to try, best first: each width down to NAME_NARROW_AT of `top`, the last to `bottom`."""
    for i, width in enumerate(NAME_WIDTHS):
        floor = bottom if i == len(NAME_WIDTHS) - 1 else max(bottom, round(top * NAME_NARROW_AT))
        for size in range(top, floor - 1, -1):
            yield width, size


def _fit_name(draw, name, max_w, one_line, two_lines=None):
    """
    The name's lines within `max_w`, each a list of parts. `one_line` and
    `two_lines` are (largest, smallest) px sizes: one line is tried first,
    then, where the label has room for them, two lines broken at the space
    that balances them. A line still too wide at the smallest size is
    squeezed when drawn.
    """
    main, familiar = _split_familiar(name)
    for width, size in _name_sizes(*one_line):
        parts = _name_parts(draw, main, familiar, width, size)
        if _parts_width(draw, parts) <= max_w:
            return [parts]

    words = name.split()
    if not two_lines or len(words) < 2:
        return [_name_parts(draw, main, familiar, NAME_WIDTHS[-1], one_line[1])]

    ref = get_font((FONT_TEXT, NAME_WIDTHS[0]), two_lines[0], FONT_ARIAL_BD)
    cut = min(range(1, len(words)), key=lambda i: max(
        draw.textlength(" ".join(words[:i]), font=ref),
        draw.textlength(" ".join(words[i:]), font=ref)))
    halves = (" ".join(words[:cut]), " ".join(words[cut:]))
    for width, size in _name_sizes(*two_lines):
        lines = [_name_parts(draw, half, "", width, size) for half in halves]
        if all(_parts_width(draw, parts) <= max_w for parts in lines):
            break
    return lines


def _draw_name(img, draw, name, box, one_line, two_lines=None):
    """The product name centred in `box` by its capitals, on one line or two, never wider than the box."""
    x0, y0, x1, y1 = box
    lines = _fit_name(draw, name, x1 - x0, one_line, two_lines)
    cap   = -_cap_top(draw, lines[0][0][1])
    gap   = round(cap * 0.45)            # between two lines' capitals
    base  = (y0 + y1 - (cap + gap) * (len(lines) - 1)) / 2 + cap / 2
    for parts in lines:
        _draw_parts(img, draw, parts, x0, x1, base)
        base += cap + gap


# ── Net weight ────────────────────────────────
UNIT_SCALE = 0.65   # the unit's size, as a share of the number's


def _weight_parts(draw, weight, face, size, fallback=None, lead=""):
    """
    A net weight's parts, the unit a size down so the number reads first:
    "25" then "kg". `lead` ("Net Wt.:") goes before it at full size. A
    weight that is not a number and a unit is set as it is.
    """
    font  = get_font(face, size, fallback)
    parts = [(lead, font, 0)] if lead else []
    gap   = draw.textlength(" ", font=font) if lead else 0
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([A-Za-z]+)$", weight.strip())
    if not m:
        return parts + [(weight, font, gap)]
    unit = get_font(face, round(size * UNIT_SCALE), fallback)
    return parts + [(m.group(1), font, gap), (m.group(2), unit, round(size * 0.12))]


def _fit_weight(draw, weight, face, size, max_w, fallback=None, lead="", min_size=12):
    """The weight's parts at the largest size from `size` down that fit max_w; squeezed when drawn if none does."""
    for s in range(size, min_size - 1, -1):
        parts = _weight_parts(draw, weight, face, s, fallback, lead)
        if _parts_width(draw, parts) <= max_w:
            break
    return parts


def build_label_image(req, batch_no):
    img  = Image.new("RGB", (LABEL_W_PX, LABEL_H_PX), color="white")
    draw = ImageDraw.Draw(img)

    # A product with allergens gets one more line, paid for by tightening
    # the top section; every other label keeps the layout it always had.
    has_allergens = bool(req.allergens)

    # Product name: 42px, narrowed before it is shrunk (see _fit_name), so
    # every name prints at much the same height. It is centred across the
    # full label, so it grows towards BOTH edges — the widest it can be
    # while its right edge still clears the pre-printed veg mark is twice
    # the gap from the mark to the centre.
    product_font_size = 42
    veg_mark_left = LABEL_W_PX - _mm_to_px(VEG_MARK_MM) - VEG_MARK_MARGIN
    name_max_w    = 2 * veg_mark_left - LABEL_W_PX
    font_dates   = get_font(TEXT_BOLD_SC, 26 if has_allergens else 28, FONT_ARIAL_NB)
    font_batch   = get_font(TEXT_BOLD_SC, 22, FONT_ARIAL_NB)  # smaller to save space

    # ── Mandatory declarations ────────────────────
    s = get_settings()
    fssai_number    = s.get("fssai_number",    "13620011000563")
    company_prefix  = s.get("company_prefix",  "Packed & Marketed by")
    company_name    = s.get("company_name",    "SRI RADHE TRADERS")
    company_address = s.get("company_address", "BEGUM BAZAR, HYDERABAD, TELANGANA - 500012")

    qr_data = _qr_data(req, batch_no, company_name, fssai_number)
    qr_size = 110
    qr_img  = make_qr(qr_data).resize((qr_size, qr_size), Image.NEAREST)
    qr_x    = LABEL_W_PX - qr_size - 20   # pulled inward from right edge
    qr_y    = 65                           # below green dot
    img.paste(qr_img, (qr_x, qr_y))

    # ── Calculate total content height for vertical centering ──
    # Top section lines
    LINE_PRODUCT = product_font_size + 6   # approx text height for the chosen size
    LINE_WEIGHT  = 34 if has_allergens else 36   # font 30 height approx
    LINE_DATE    = 28 if has_allergens else 30   # font 28 (26) height approx
    LINE_BATCH   = 26   # font 22 height approx (batch only)
    # CONTAINS pill. With it, the batch row still starts below the QR
    # (rows 65-175), which its value would otherwise run into.
    LINE_ALLERGEN = 18 if has_allergens else 0
    GAP_SMALL    = 3 if has_allergens else 6
    GAP_DIVIDER  = 7

    # Bottom section lines
    LINE_BOTTOM  = 20   # font 16 height approx
    # FSSAI licence, company name, company address, non-retail statement —
    # all four are mandatory, so the count is fixed.
    n_bottom_lines = 4

    # Top section total height
    top_h = (LINE_PRODUCT + GAP_SMALL +
             LINE_WEIGHT  + GAP_SMALL +
             (LINE_ALLERGEN + GAP_SMALL if has_allergens else 0) +
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
    cx = LABEL_W_PX / 2
    _draw_name(img, draw, req.product, (cx - name_max_w / 2, y, cx + name_max_w / 2, y + product_font_size),
               (product_font_size, 24))
    y += LINE_PRODUCT + GAP_SMALL

    # Net quantity — the Legal Metrology declaration, so it is labelled
    # "Net Wt." rather than "Weight". Left of centre, and kept clear of the QR.
    weight = _fit_weight(draw, req.weight, TEXT_BOLD_SC, 30, qr_x - 8 - PAD, FONT_ARIAL_NB, lead="Net Wt.:")
    _draw_parts(img, draw, weight, PAD, qr_x - 8, _baseline(draw, y, weight[0][1]), centre=cx - 30)
    y += LINE_WEIGHT + GAP_SMALL

    # Allergen declaration, straight under the net quantity, clear of the QR
    if has_allergens:
        _draw_allergen_pill(draw, PAD, y + LINE_ALLERGEN / 2, req.allergens,
                            qr_x - PAD - 8, 15, LINE_ALLERGEN)
        y += LINE_ALLERGEN + GAP_SMALL

    # Dates — left aligned in two columns, clear of the QR block.
    # VALUE_X is fixed rather than space-padded so a wider fallback font
    # cannot push the value under the QR.
    VALUE_X = 145
    for key, value, font, line_h in (("PACKED:", req.packed_on,   font_dates, LINE_DATE + GAP_SMALL),
                                     ("USE BY:", req.best_before, font_dates, LINE_DATE + GAP_SMALL),
                                     ("BATCH:",  batch_no,        font_batch, LINE_BATCH)):
        base = _baseline(draw, y, font)
        draw.text((PAD, base), key, font=font, fill="black", anchor="ls")
        draw.text((VALUE_X, base), value, font=font, fill="black", anchor="ls")
        y += line_h

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
        lic_font  = fit_font(draw, lic_text, TEXT_BOLD, 22,
                             TEXT_MAX_W - logo.width - LOGO_GAP, FONT_ARIAL_BD)
        # A shallower lead than the other rows: the logo below is spaced
        # from where this line's capitals have always sat
        lic_base  = _baseline(draw, y, lic_font, lead=0.18)
        bbox      = draw.textbbox((0, lic_base), lic_text, font=lic_font, anchor="ls")
        group_w   = logo.width + LOGO_GAP + (bbox[2] - bbox[0])
        gx        = max(PAD, (LABEL_W_PX - group_w) // 2)
        # Sit the logo on the text's optical centre, not its box top
        logo_y = int((bbox[1] + bbox[3]) / 2 - logo.height / 2)
        # Paste ink only. The divider is drawn first and the logo box overlaps
        # it as the mark grows; an unmasked paste would white out mandatory
        # content instead of just colliding with it.
        img.paste(logo, (gx, logo_y), mask=ImageChops.invert(logo.convert("L")))
        draw.text((gx + logo.width + LOGO_GAP, lic_base), lic_text, font=lic_font, fill="black", anchor="ls")
    else:
        fssai_text = f"FSSAI Lic. No. {fssai_number}"
        draw_centered(draw, y, fssai_text,
                      fit_font(draw, fssai_text, TEXT_BOLD, 22, TEXT_MAX_W, FONT_ARIAL_BD))
    y += 26 if has_allergens else 28
              # was 24. The logo is centred on the licence text's optical
              # centre, so a taller mark grows both ways about this line; 28
              # keeps 5 blank rows between the logo and the company name.
              # Paid for out of the label's spare bottom rows (17 -> 13).
              # An allergen label gives 2 of them back for its extra line.

    # Reg 5(6)(a): name preceded by the qualifying phrase, then the
    # complete address on the following line.
    name_text = f"{company_prefix}: {company_name}"
    draw_centered(draw, y, name_text,
                  fit_font(draw, name_text, TEXT_BOLD_SC, 16, TEXT_MAX_W, FONT_ARIAL_NB))
    y += LINE_BOTTOM + 4

    draw_centered(draw, y, company_address,
                  fit_font(draw, company_address, TEXT_BOLD_SC, 16, TEXT_MAX_W, FONT_ARIAL_NB))
    y += LINE_BOTTOM + 4

    # Reg 10(4): not for sale to consumers, worded as set in Settings.
    # Shrinks to fit, and is squeezed sideways if it still runs long.
    notice      = _non_retail_text(s)
    font_notice = fit_font(draw, notice, TEXT_BOLD_SC, 16, TEXT_MAX_W, FONT_ARIAL_NB, min_size=12)
    _draw_parts(img, draw, [(notice, font_notice, 0)], PAD, LABEL_W_PX - PAD,
                _baseline(draw, y, font_notice))

    return img


# ── Large label (75 x 50 mm, CRYSTAL CLEAR) ───
# Top to bottom, at 203 dpi (599 x 400 px):
#   brand band, black on white in a double frame ...... veg mark window right
#   product name, one line or two
#   2 x 2 grid  NET WT. | BATCH NO. / PACKED ON | USE BY ......... QR right
#   storage line between two rules
#   FSSAI logo + licence | packer name, address, customer care
#   non-retail statement (NOT FOR DIRECT SALE TO CONSUMER) in a framed bar
# Rows run down from the top and the bar is pinned to the bottom edge, so
# the footer takes whatever height is left. Sizes are tuned for 75 x 50; a
# die-cut a few mm either way lays out the same.
# Everything is black on white, in frames and rules: no cell, bar or pill
# is filled in, because solid black smears when packed goods are stacked
# on one another.
LARGE_EDGE     = 8      # px (1 mm) kept clear on every edge, for die-cut drift
LARGE_PAD      = 12     # px between the text and the left/right edges
LARGE_BAND_H   = 52     # brand band
LARGE_NAME_H   = 52     # product name row
LARGE_BAR_H    = 30     # non-retail statement bar
LARGE_QR_PX    = 129    # QR box: version 6 at 3 dots per module + quiet zone
LARGE_FOOT_COL = 196    # x of the rule between the FSSAI and packer blocks
BRAND_TRACKING = 0.07   # brand letter spacing, as a share of the font size
STORAGE_TEXT   = "STORE IN A COOL, DRY & HYGIENIC PLACE"
STORAGE_TEXT_SHORT = "STORE COOL & DRY"   # beside a long allergen line


def make_qr_fixed(data, box_px):
    """
    QR code filling a `box_px` square with a whole number of dots per module.

    make_qr() is stretched to its box, which leaves modules of uneven width
    (some 2 dots, some 3); equal modules scan more reliably off a thermal
    print. Version 6 holds 134 bytes at level L, which covers this label's
    data at 3 dots per module in 129 px. Longer data moves up a version and
    drops to the largest whole module size that fits, centred in the box.
    """
    qr = qrcode.QRCode(version=6, error_correction=qrcode.constants.ERROR_CORRECT_L,
                       box_size=1, border=1)
    qr.add_data(data)
    qr.make(fit=True)
    code = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    k    = max(1, box_px // code.width)
    code = code.resize((code.width * k, code.height * k), Image.NEAREST)
    box  = Image.new("RGB", (box_px, box_px), "white")
    box.paste(code, ((box_px - code.width) // 2, (box_px - code.height) // 2))
    return box


def _tracked_width(text, font, tracking):
    return sum(font.getlength(ch) for ch in text) + tracking * (len(text) - 1)


def _draw_tracked(draw, x, baseline, text, font, tracking, fill):
    """Draw `text` with `tracking` px after each character. Returns the x its last character ends at."""
    for ch in text:
        draw.text((x, baseline), ch, font=font, fill=fill, anchor="ls")
        x += font.getlength(ch) + tracking
    return x - tracking


def _cap_top(draw, font):
    """Height of a capital above the baseline, as a negative offset."""
    return draw.textbbox((0, 0), "H", font=font, anchor="ls")[1]


def _split_address(address):
    """Two lines, broken at the comma nearest the middle."""
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) < 2:
        return [address.strip()]
    i = min(range(1, len(parts)),
            key=lambda i: abs(len(", ".join(parts[:i])) - len(", ".join(parts[i:]))))
    return [", ".join(parts[:i]) + ",", ", ".join(parts[i:])]


def _draw_brand_band(draw, box, brand, mark):
    """
    The trade mark in black inside a double frame (rule and keyline), with
    a diamond at each end. Black on white rather than reversed out of a
    solid band: reversed type fills in on a thermal head, the ® worst of
    all, and solid black smears when packed goods are stacked.
    """
    x0, y0, x1, y1 = box
    cy = (y0 + y1) / 2
    # Both lines at least 2 dots, with a 3-dot gap: a 1-dot line under-burns
    draw.rounded_rectangle(box, radius=10, outline="black", width=3)
    draw.rounded_rectangle((x0 + 6, y0 + 6, x1 - 6, y1 - 6), radius=6, outline="black", width=2)
    for cx in (x0 + 22, x1 - 22):
        draw.polygon([(cx, cy - 6), (cx + 6, cy), (cx, cy + 6), (cx - 6, cy)], fill="black")

    # Largest size at which the spaced-out name and its mark clear both diamonds
    max_w = x1 - x0 - 80
    for size in range(40, 15, -1):
        f_name   = get_font(FONT_BRAND, size, FONT_GEORGIA_BD)
        f_mark   = get_font(FONT_BRAND, max(14, round(size * 0.42)), FONT_GEORGIA_BD)
        tracking = round(size * BRAND_TRACKING)
        name_w   = _tracked_width(brand, f_name, tracking)
        mark_w   = 3 + f_mark.getlength(mark) if mark else 0
        if name_w + mark_w <= max_w:
            break

    cap  = _cap_top(draw, f_name)
    base = cy - cap / 2
    x    = _draw_tracked(draw, (x0 + x1) / 2 - (name_w + mark_w) / 2, base,
                         brand, f_name, tracking, "black")
    if mark:
        # Top-aligned with the capitals, like a superscript, and large
        # enough that the letter inside the circle stays legible
        mark_top = draw.textbbox((0, 0), mark, font=f_mark, anchor="lt")[1]
        draw.text((x + 3, base + cap - mark_top), mark, font=f_mark, fill="black", anchor="lt")


def build_large_label_image(req, batch_no):
    img  = Image.new("RGB", (LABEL_W_PX, LABEL_H_PX), color="white")
    draw = ImageDraw.Draw(img)
    W, H = LABEL_W_PX, LABEL_H_PX

    s = get_settings()
    fssai_number    = s.get("fssai_number",    "13620011000563")
    company_prefix  = s.get("company_prefix",  "Packed & Marketed by")
    company_name    = s.get("company_name",    "SRI RADHE TRADERS")
    company_address = s.get("company_address", "BEGUM BAZAR, HYDERABAD, TELANGANA - 500012")
    brand_name      = s.get("brand_name",      "CRYSTAL CLEAR")
    brand_mark      = s.get("brand_mark",      "®")
    customer_care   = s.get("customer_care",   "").strip()

    # ── Brand band ────────────────────────────────
    # Reg 5(4): the veg mark goes close to the brand name, so its window is
    # beside the band, a VEG_MARK_MM square in the top-right corner. It is
    # green and so pre-printed on the stock — the head can only print black.
    veg_px  = _mm_to_px(VEG_MARK_MM)
    veg_box = (W - LARGE_EDGE - veg_px, LARGE_EDGE, W - LARGE_EDGE, LARGE_EDGE + veg_px)
    band    = (LARGE_EDGE, LARGE_EDGE, veg_box[0] - 10, LARGE_EDGE + LARGE_BAND_H)
    _draw_brand_band(draw, band, brand_name, brand_mark)

    # ── Product name ──────────────────────────────
    # Narrows, shrinks, then takes two lines, rather than run off the label:
    # one line from 58 px to 30, two from 28 (the most two lines fit in the
    # row) to 16. Its row is below the veg mark; a mark measured taller than
    # the band (with VEG_MARK_MM raised to suit) reaches the row, and the
    # name then keeps to the left of it as well.
    name_y0 = band[3] + 6
    name_y1 = name_y0 + LARGE_NAME_H
    name_x1 = W - LARGE_PAD
    if veg_box[3] + VEG_MARK_MARGIN > name_y0:
        name_x1 = veg_box[0] - VEG_MARK_MARGIN
    _draw_name(img, draw, req.product, (LARGE_PAD, name_y0, name_x1, name_y1), (58, 30), (28, 16))

    # ── QR + 2 x 2 grid ───────────────────────────
    qr_data = _qr_data(req, batch_no, company_name, fssai_number)
    grid_y0 = name_y1 + 6
    qr_x    = W - LARGE_EDGE - LARGE_QR_PX
    img.paste(make_qr_fixed(qr_data, LARGE_QR_PX), (qr_x, grid_y0))

    gx0, gx1 = LARGE_EDGE + 2, qr_x - 10
    gy0, gy1 = grid_y0, grid_y0 + LARGE_QR_PX - 1
    mx, my   = (gx0 + gx1) // 2, (gy0 + gy1) // 2
    draw.rounded_rectangle((gx0, gy0, gx1, gy1), radius=8, outline="black", width=2)
    draw.line([(mx, gy0), (mx, gy1)], fill="black", width=2)
    draw.line([(gx0, my), (gx1, my)], fill="black", width=2)

    # Net quantity is the cell the receiving kitchen checks, so its value is
    # set largest. It is not filled in black (see the layout notes above).
    font_key = get_font(TEXT_BOLD_SC, 15, FONT_ARIAL_NB)
    cells = [
        ((gx0, gy0, mx, my),  "NET WT.",   req.weight,      42),
        ((mx, gy0, gx1, my),  "BATCH NO.", batch_no,        29),
        ((gx0, my, mx, gy1),  "PACKED ON", req.packed_on,   29),
        ((mx, my, gx1, gy1),  "USE BY",    req.best_before, 29),
    ]
    for (x0, y0, x1, y1), key, value, size in cells:
        _draw_tracked(draw, x0 + 10, y0 + 18, key, font_key, 1, "black")
        if key == "NET WT.":
            # The number large, its unit a size down
            parts = _fit_weight(draw, value, TEXT_BOLD, size, x1 - x0 - 20, FONT_ARIAL_BD)
            _draw_parts(img, draw, parts, x0 + 10, x1 - 10, y1 - 9, centre=x0 + 10)
            continue
        font_value = fit_font(draw, value, TEXT_BOLD, size, x1 - x0 - 20, FONT_ARIAL_BD)
        draw.text((x0 + 10, y1 - 9), value, font=font_value, fill="black", anchor="ls")

    # ── Allergens + storage line, between rules ───
    rule_y = gy1 + 14
    row_x0 = LARGE_EDGE + 2
    row_x1 = W - LARGE_EDGE - 2
    if not req.allergens:
        font_store = get_font(TEXT_BOLD_SC, 16, FONT_ARIAL_NB)
        store_w    = _tracked_width(STORAGE_TEXT, font_store, 1)
        store_x    = (W - store_w) / 2
        _draw_tracked(draw, store_x, rule_y - _cap_top(draw, font_store) / 2, STORAGE_TEXT,
                      font_store, 1, "black")
        draw.line([(row_x0, rule_y), (store_x - 10, rule_y)], fill="black", width=2)
        draw.line([(store_x + store_w + 10, rule_y), (row_x1, rule_y)], fill="black", width=2)
    else:
        # The allergen pill leads the row, as large as it can be while the
        # storage line still fits to its right — in full if possible, else
        # shortened. A pill too long for either has the row to itself:
        # the allergens matter more than the storage advice.
        PILL_H, GAP_RULE = 22, 34          # pill height; pill-to-text gap with its rule
        pill_text = f"CONTAINS: {req.allergens}"
        layout = None
        for size in range(17, 13, -1):
            pill_font = get_font(TEXT_BOLD_SC, size, FONT_ARIAL_NB)
            pill_w    = _tracked_width(pill_text, pill_font, 1) + PILL_H
            for store_text in (STORAGE_TEXT, STORAGE_TEXT_SHORT):
                font_store = _fit_tracked(store_text, TEXT_BOLD_SC, FONT_ARIAL_NB, 16, 12,
                                          row_x1 - row_x0 - pill_w - GAP_RULE)
                if font_store:
                    layout = (size, store_text, font_store)
                    break
            if layout:
                break
        if layout:
            size, store_text, font_store = layout
            pill_end = _draw_allergen_pill(draw, row_x0, rule_y, req.allergens,
                                           row_x1 - row_x0, size, PILL_H, filled=False)
            store_x  = row_x1 - _tracked_width(store_text, font_store, 1)
            _draw_tracked(draw, store_x, rule_y - _cap_top(draw, font_store) / 2, store_text,
                          font_store, 1, "black")
            draw.line([(pill_end + 10, rule_y), (store_x - 10, rule_y)], fill="black", width=2)
        else:
            _draw_allergen_pill(draw, row_x0, rule_y, req.allergens, row_x1 - row_x0, 17, PILL_H,
                                filled=False)

    # ── Footer ────────────────────────────────────
    bar     = (LARGE_EDGE, H - LARGE_EDGE - LARGE_BAR_H, W - LARGE_EDGE, H - LARGE_EDGE)
    foot_y0 = rule_y + 12
    foot_y1 = bar[1] - 6
    col_x   = LARGE_FOOT_COL

    # Left: Reg 5(7)(a) logo over the licence number. Text-only while the
    # artwork file is missing, as on the small label.
    lic_text = f"Lic. No. {fssai_number}"
    font_lic = fit_font(draw, lic_text, TEXT_BOLD, 18, col_x - LARGE_EDGE - 14, FONT_ARIAL_BD)
    lic_cap  = -_cap_top(draw, font_lic)
    logo     = load_fssai_logo(height=42)
    head_h   = logo.height if logo else lic_cap
    block_y  = foot_y0 + (foot_y1 - foot_y0 - (head_h + 6 + lic_cap)) // 2
    mid_x    = (LARGE_EDGE + col_x) // 2
    if logo:
        img.paste(logo, (mid_x - logo.width // 2, block_y), mask=ImageChops.invert(logo.convert("L")))
    else:
        draw.text((mid_x, block_y + lic_cap), "FSSAI", font=font_lic, fill="black", anchor="ms")
    draw.text((mid_x, block_y + head_h + 6 + lic_cap), lic_text, font=font_lic, fill="black", anchor="ms")
    draw.line([(col_x, foot_y0 + 4), (col_x, foot_y1 - 4)], fill="black", width=2)

    # Right: Reg 5(6)(a) qualifying phrase and name, then the complete
    # address, then customer care when one is set
    rx, r_max = col_x + 12, W - LARGE_EDGE - 4 - (col_x + 12)
    prefix = f"{company_prefix}: "
    for size in range(18, 9, -1):
        font_prefix = get_font(TEXT_BOLD_SC, size, FONT_ARIAL_NB)
        font_name   = get_font(TEXT_BOLD, size, FONT_ARIAL_BD)
        if font_prefix.getlength(prefix) + font_name.getlength(company_name) <= r_max:
            break
    lines = _split_address(company_address)
    if customer_care:
        lines.append(f"Customer Care: {customer_care}")
    line_h = (foot_y1 - foot_y0) / (len(lines) + 1)
    base   = foot_y0 + line_h - 4
    draw.text((rx, base), prefix, font=font_prefix, fill="black", anchor="ls")
    draw.text((rx + font_prefix.getlength(prefix), base), company_name, font=font_name,
              fill="black", anchor="ls")
    for i, line in enumerate(lines, 2):
        draw.text((rx, foot_y0 + line_h * i - 4), line, fill="black", anchor="ls",
                  font=fit_font(draw, line, TEXT_BOLD_SC, 18, r_max, FONT_ARIAL_NB))

    # ── Non-retail statement ──────────────────────
    # Reg 10(4): not for sale to consumers, worded as set in Settings.
    # Framed rather than reversed out of a black bar (see the layout notes
    # above). Set as large as the bar allows, spaced out where there is
    # room, and squeezed sideways if it still runs long.
    draw.rounded_rectangle(bar, radius=8, outline="black", width=2)
    notice = _non_retail_text(s)
    nx0, nx1 = bar[0] + 14, bar[2] - 14     # clear of the frame's rounded ends
    font_notice, tracking = get_font(TEXT_BOLD, 12, FONT_ARIAL_BD), 1
    for size in range(19, 11, -1):
        font = get_font(TEXT_BOLD, size, FONT_ARIAL_BD)
        fits = [t for t in (3, 2, 1) if _tracked_width(notice, font, t) <= nx1 - nx0]
        if fits:
            font_notice, tracking = font, fits[0]
            break
    _draw_parts(img, draw, [(ch, font_notice, tracking if i else 0) for i, ch in enumerate(notice)],
                nx0, nx1, (bar[1] + bar[3]) / 2 - _cap_top(draw, font_notice) / 2)

    # Threshold rather than leave it to _pack_mono(): its dithering speckles
    # the anti-aliased edges of type.
    return img.convert("L").point(lambda p: 0 if p < 128 else 255).convert("RGB")


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

    # Sizes are tuned for the 40 mm small label and grow with a taller one,
    # so the text fills a large label in proportion. Never below these.
    scale = max(1.0, LABEL_H_PX / 320)

    font_title = get_font(TEXT_BOLD, round(30 * scale), FONT_ARIAL_BD)

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
    for size in range(round(32 * scale), 17, -1):
        test_font = get_font(TEXT_REGULAR, size, FONT_ARIAL)
        wrapped = _wrap_text_pixel(draw, req.ingredients, test_font, max_text_width)
        line_bbox = draw.textbbox((0, 0), "Ag", font=test_font)
        line_h = (line_bbox[3] - line_bbox[1]) + 3
        total_h = line_h * len(wrapped)
        if total_h <= available_h:
            best_font_size = size
            break

    font_body = get_font(TEXT_REGULAR, best_font_size, FONT_ARIAL)
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
    Largest semi-condensed bold size at which the tracked `text` fits
    `max_width`. Returns (font, tracking_px, ink_box).
    """
    lo, hi, best = 8, 300, None
    while lo <= hi:
        size     = (lo + hi) // 2
        font     = get_font(TEXT_BOLD_SC, size, FONT_ARIAL_NB)
        tracking = round(size * FSSAI_STICKER_TRACKING)
        box      = _tracked_bbox(draw, text, font, tracking)
        if box[2] - box[0] <= max_width:
            best, lo = (font, tracking, box), size + 1
        else:
            hi = size - 1
    if best is None:
        font = get_font(TEXT_BOLD_SC, 8, FONT_ARIAL_NB)
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
    """
    Render a single label (product, ingredients or FSSAI logo) to a PIL image,
    sized for the request's label type. Ingredients and FSSAI logo stickers
    size themselves from the label; product labels have a layout per size.
    """
    with _render_lock:
        roll = _apply_geometry(req.roll_type)
        if req.label_type == "ingredients":
            return build_ingredients_label_image(req)
        if req.label_type == "fssai":
            return build_fssai_label_image(req)
        if roll == "large":
            return build_large_label_image(req, batch_no)
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
            # Pad with white (1). A 0 is a printed dot, and the large label
            # is 599 dots wide on a 600-dot SIZE, so zero padding printed a
            # 1-dot black line down its right edge.
            pad = 8 - remaining
            row = (row << pad) | ((1 << pad) - 1)
            pixel_data.append(row)

    return width_bytes, h, bytes(pixel_data)


def _tspl_header(size_w_mm, size_h_mm) -> bytes:
    return (
        f"SIZE {size_w_mm} mm, {size_h_mm} mm\r\n"
        f"GAP {V_GAP_MM} mm, 0 mm\r\n"
        f"SPEED {PRINT_SPEED}\r\n"
        f"DENSITY {PRINT_DENSITY}\r\n"
        f"DIRECTION 1\r\n"
    ).encode("ascii")


def _offset(img):
    """The print moved by the roll's offset, right and down (negative for left and up)."""
    if not (OFFSET_X_PX or OFFSET_Y_PX):
        return img
    out = Image.new("RGB", img.size, "white")
    out.paste(img, (OFFSET_X_PX, OFFSET_Y_PX))
    return out


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
    """One-per-row path (single or large roll): print `req.quantity` identical labels."""
    try:
        with _render_lock:
            img  = render_label(req, batch_no)
            tspl = _tspl_header(LABEL_W_MM, LABEL_H_MM) + _bitmap_block(_offset(img), req.quantity)
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
            _apply_geometry("double")
            tspl = _tspl_header(DOUBLE_W_MM, LABEL_H_MM)
            for left_img, right_img in rows:
                canvas = _compose_double_row(left_img, right_img)
                tspl += _bitmap_block(_offset(canvas), quantity=1)
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