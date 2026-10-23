import json
import os
import re
import shutil

from settings_manager import get_default_shelf_months, SHELF_MONTHS_LIMITS
from product_catalog import migrate as migrate_to_english, norm

PRODUCTS_FILE = os.path.join(os.path.dirname(__file__), "products.json")
BACKUP_FILE   = PRODUCTS_FILE + ".bak"

DEFAULT_HOTEL  = "general"

# A product's own shelf life overrides the configurable default in settings
SHELF_MONTHS_RANGE = SHELF_MONTHS_LIMITS

# Hotel names travel as one bare word: the 6th comma field of a Telegram
# print line, and the last argument of /removeproduct.
HOTEL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,29}$")

# A product's entry is its weight string ("2 kg") or, once it has more than
# a weight, {"weight": "2 kg", "shelf_months": 6, "aliases": [...],
# "allergens": [...]} with only the keys it uses. Plain strings stay the
# norm so older files, recover_products.py and hand edits keep working.
#
# Aliases are the other names a product is typed as (PHALLI for PEANUTS);
# allergens print on the label as "CONTAINS: ...". A hotel's entry that sets
# neither uses its General entry's, so they are kept in one place.
_KEEP = object()   # add/update_product(): leave this field as it is

MAX_ALIASES     = 20
MAX_NAME_LEN    = 40
MAX_ALLERGEN_LEN = 40   # the whole "PEANUT, SOY" text, so it fits one label line


def _entry_weight(val) -> str:
    return str(val.get("weight", "")) if isinstance(val, dict) else str(val)


def _entry_shelf(val):
    return val.get("shelf_months") if isinstance(val, dict) else None


def _entry_aliases(val) -> list:
    return list(val.get("aliases") or []) if isinstance(val, dict) else []


def _entry_allergens(val) -> list:
    return list(val.get("allergens") or []) if isinstance(val, dict) else []


def _make_entry(weight: str, shelf_months, aliases=None, allergens=None):
    extra = {k: v for k, v in (("shelf_months", shelf_months), ("aliases", aliases),
                               ("allergens", allergens)) if v}
    return {"weight": weight, **extra} if extra else weight


def _find_key(hotel_products: dict, product: str):
    product = product.upper()
    return next((k for k in hotel_products if k.upper() == product), None)


def _split_names(raw) -> list:
    """A list, or one comma-separated string, as trimmed upper-case names."""
    items = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(",")
    return [str(s).strip().upper() for s in items if str(s).strip()]


def clean_aliases(raw):
    """(aliases, error) from a list or comma-separated text, duplicates dropped."""
    out, seen = [], set()
    for name in _split_names(raw):
        if len(name) > MAX_NAME_LEN:
            return None, f"Other name '{name[:20]}…' is too long (max {MAX_NAME_LEN})"
        if norm(name) and norm(name) not in seen:
            seen.add(norm(name))
            out.append(name)
    if len(out) > MAX_ALIASES:
        return None, f"At most {MAX_ALIASES} other names per product"
    return out, None


def clean_allergens(raw):
    """(allergens, error) from a list or comma-separated text."""
    out = list(dict.fromkeys(_split_names(raw)))
    if len(", ".join(out)) > MAX_ALLERGEN_LEN:
        return None, f"Allergens must fit one label line — {MAX_ALLERGEN_LEN} characters at most"
    return out, None


def validate_shelf_months(raw):
    """Returns (months or None, error or None). Blank means 'use the default'."""
    if raw is None or str(raw).strip() == "":
        return None, None
    try:
        months = int(str(raw).strip())
    except ValueError:
        return None, "Shelf life must be a whole number of months"
    lo, hi = SHELF_MONTHS_RANGE
    if not lo <= months <= hi:
        return None, f"Shelf life must be between {lo} and {hi} months"
    return months, None


def _read_json(path):
    """Parse a JSON file, or return None if it is missing or unreadable."""
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _load() -> dict:
    data = _read_json(PRODUCTS_FILE)

    if data is None:
        # A truncated products.json takes down every endpoint that lists
        # products, so fall back to the last good copy rather than 500.
        data = _read_json(BACKUP_FILE)
        if data is None:
            raise ValueError(
                f"{PRODUCTS_FILE} is unreadable and there is no usable backup. "
                "Restore it with:  git checkout -- products.json"
            )
        print(f"⚠️  {PRODUCTS_FILE} was unreadable — recovered from {BACKUP_FILE}")
        _save(data)

    # Auto-migrate flat format → hotel-grouped format
    if data and not any(isinstance(v, dict) for v in data.values()):
        data = {DEFAULT_HOTEL: data}
        _save(data)

    # Auto-migrate to English names, once: a list that has never had an
    # alias has never been through it. See product_catalog.py.
    if not any(_entry_aliases(v) for prods in data.values() for v in prods.values()):
        english, report = migrate_to_english(data, DEFAULT_HOTEL)
        if english != data:
            _save(english)
            data = english
            # Plain ASCII: a console without PYTHONUTF8 cannot print emoji,
            # and a failed print here would fail the request that loaded it
            print(f"products.json: English names applied ({len(report)} changes); "
                  f"the old list is in {os.path.basename(BACKUP_FILE)}")
    return data


def _save(data: dict):
    """
    Write atomically, keeping the previous good copy as products.json.bak.

    open(..., "w") truncates the file before a single byte is written, so
    an interrupted or concurrent write leaves a partial document that
    _load() can no longer parse — and run.bat starts bot.py and server.py
    as two processes that both write here. Writing to a temp file and
    renaming means the live file is only ever a complete document.
    """
    tmp = PRODUCTS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    if os.path.exists(PRODUCTS_FILE):
        try:
            shutil.copyfile(PRODUCTS_FILE, BACKUP_FILE)
        except OSError:
            pass          # a missing backup must never block the write
    os.replace(tmp, PRODUCTS_FILE)      # atomic on Windows and POSIX


# ── Finding a product by what was typed ───────
def _general_twin(general: dict, name: str):
    """
    The General product a hotel's own entry stands in for: the one with the
    same name, else one that answers to it — General was renamed since
    (PEANUTS → GROUNDNUTS keeps PEANUTS as another name). None if neither.
    """
    n = norm(name)
    for k in general:
        if norm(k) == n:
            return k
    for k, v in general.items():
        if any(norm(a) == n for a in _entry_aliases(v)):
            return k
    return None


def _merged(data: dict, hotel: str) -> list:
    """
    [(name, entry, aliases, allergens)] as a hotel sees it: its own products,
    then General's that it doesn't override. An own entry with no aliases or
    allergens of its own uses its General twin's.
    """
    hotel   = hotel.lower()
    general = data.get(DEFAULT_HOTEL, {})
    if hotel == DEFAULT_HOTEL:
        return [(k, v, _entry_aliases(v), _entry_allergens(v)) for k, v in general.items()]
    out, covered = [], set()
    for name, val in data.get(hotel, {}).items():
        twin = _general_twin(general, name)
        base = general.get(twin) if twin else None
        if twin:
            covered.add(twin)
        out.append((name, val,
                    _entry_aliases(val) or _entry_aliases(base),
                    _entry_allergens(val) or _entry_allergens(base)))
    out += [(k, v, _entry_aliases(v), _entry_allergens(v))
            for k, v in general.items() if k not in covered]
    return out


def _typo_limit(length: int) -> int:
    """Edits allowed for a typed name of this many letters and digits."""
    return 0 if length < 4 else 1 if length < 10 else 2


def _edit_distance(a: str, b: str, limit: int, change_cost: int = 1) -> int:
    """
    Edits between a and b — insert, delete, change, or swap two neighbouring
    letters — or limit + 1 as soon as it is clearly more than `limit`.
    A changed letter costs `change_cost`: 2 rules it out at limit 1.
    """
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    before, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (change_cost if a[i - 1] != b[j - 1] else 0))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], before[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        before, prev = prev, cur
    return prev[-1]


def resolve_name(product: str, hotel: str = DEFAULT_HOTEL, data: dict = None, typos: bool = True):
    """
    (listed name, how) for a typed product name, where how is "name",
    "alias" or "typo"; (None, None) when nothing matches.

    Spacing and punctuation never count ("W.PEAS" is W PEAS). A typo match
    is deliberately narrow, because the wrong product means the wrong
    weight and allergens on the label:
      - one slip in a name of 4-9 letters, two from 10 up, none below 4;
      - below 7 letters the slip must be a missing, extra or swapped letter,
        never a changed one: short real words sit one change apart (PASTA
        and PISTA, IDLI and IMLI), while PHALI / KAAJU / BADM are the
        typos people actually make;
      - the first letter must match (UDAD is not S. UDAD);
      - the digits must be exactly the same (CASHEW 4 PCS is never 6 PCS);
      - and the closest match must be the only one.
    """
    data = _load() if data is None else data
    key  = norm(product)
    if not key:
        return None, None
    items = _merged(data, hotel)
    for name, *_ in items:
        if norm(name) == key:
            return name, "name"
    for name, _, aliases, _ in items:
        if any(norm(a) == key for a in aliases):
            return name, "alias"

    limit = _typo_limit(len(key)) if typos else 0
    if not limit:
        return None, None
    digits = re.sub(r"\D", "", key)
    change_cost = 1 if len(key) >= 7 else 2
    best, found = limit + 1, set()
    for name, _, aliases, _ in items:
        for cand in [name] + aliases:
            c = norm(cand)
            if len(c) < 4 or c[0] != key[0] or re.sub(r"\D", "", c) != digits:
                continue
            d = _edit_distance(key, c, limit, change_cost)
            if d < best:
                best, found = d, {name}
            elif d == best:
                found.add(name)
    if best <= limit and len(found) == 1:
        return found.pop(), "typo"
    return None, None


def lookup_product(product: str, hotel: str = DEFAULT_HOTEL, typos: bool = True):
    """
    The listed product a typed name means, as {"name", "weight",
    "shelf_months", "allergens", "how"}, or None if it is not listed. The
    hotel's own entry wins; otherwise it falls back to General.
    """
    data = _load()
    name, how = resolve_name(product, hotel, data, typos=typos)
    if name is None:
        return None
    for listed, val, _, allergens in _merged(data, hotel):
        if listed == name:
            return {"name": name, "weight": _entry_weight(val), "shelf_months": _entry_shelf(val),
                    "allergens": allergens, "how": how}
    return None


def product_names(product: str, hotel: str = DEFAULT_HOTEL) -> list:
    """
    Every name the product goes by — its listed name and all its other
    names — when `product` is one of them; [] otherwise. No typo matching:
    this widens a search, so it must not guess.
    """
    data = _load()
    name, _ = resolve_name(product, hotel, data, typos=False)
    if name is None:
        return []
    for listed, _, aliases, _ in _merged(data, hotel):
        if listed == name:
            return [listed] + aliases
    return [name]


def find_product(product: str, hotel: str = DEFAULT_HOTEL):
    """
    Returns (weight, shelf_months) for a listed product, or None if it is
    not listed. shelf_months is None when the product does not set one.

    There is deliberately no default weight: a guessed net quantity on a
    label is worse than refusing to print it.
    """
    found = lookup_product(product, hotel)
    return (found["weight"], found["shelf_months"]) if found else None


def _taken_names(prods: dict, skip_key=None) -> dict:
    """{normalised name or alias: product} for a hotel's list, leaving out skip_key."""
    taken = {}
    for k, v in prods.items():
        if k == skip_key:
            continue
        for n in [k] + _entry_aliases(v):
            taken.setdefault(norm(n), k)
    return taken


def product_exists(product: str, hotel: str = DEFAULT_HOTEL) -> bool:
    data = _load()
    return _find_key(data.get(hotel.lower(), {}), product) is not None


def _check_aliases(prods: dict, skip_key, name: str, aliases: list):
    """aliases minus the product's own name, or an error if another product already answers to one."""
    taken = _taken_names(prods, skip_key)
    kept = [a for a in aliases if norm(a) != norm(name)]
    for a in kept:
        if norm(a) in taken:
            return None, f"{a} already means {taken[norm(a)]}"
    return kept, None


def add_product(product: str, weight: str, hotel: str = DEFAULT_HOTEL,
                shelf_months=_KEEP, aliases=_KEEP, allergens=_KEEP) -> str:
    """
    Add or update a product. A field left out keeps what the product
    already has. A name the list already knows — the product's own, or one
    of its other names — updates that product rather than adding a second.
    """
    product = product.upper().strip()
    weight = weight.upper().strip()
    hotel = hotel.lower().strip()
    data = _load()
    if hotel not in data:
        data[hotel] = {}
    hotel_products = data[hotel]

    listed, how = resolve_name(product, hotel, data, typos=False)
    name    = listed or product
    old_key = _find_key(hotel_products, name)
    old     = hotel_products.get(old_key) if old_key is not None else None
    keep    = lambda new, current: current if new is _KEEP else new
    entry = _make_entry(weight,
                        keep(shelf_months, _entry_shelf(old)),
                        keep(aliases, _entry_aliases(old)),
                        keep(allergens, _entry_allergens(old)))
    if aliases is not _KEEP:
        kept, err = _check_aliases(hotel_products, old_key, name, _entry_aliases(entry))
        if err:
            return f"⚠️ {err} in [{hotel}]."
        entry = _make_entry(weight, _entry_shelf(entry), kept, _entry_allergens(entry))
    called = f" ({product})" if how == "alias" else ""
    if old_key is not None:
        hotel_products[old_key] = entry
        _save(data)
        return f"✅ Updated *{name}*{called} → {weight} in [{hotel}]"
    hotel_products[name] = entry
    _save(data)
    return f"✅ Added *{name}*{called} → {weight} to [{hotel}]"


def update_product(old_product: str, product: str, weight: str,
                   hotel: str = DEFAULT_HOTEL, shelf_months=None,
                   aliases=_KEEP, allergens=_KEEP):
    """
    Edit a product in place: name, weight, shelf life, other names and
    allergens in one write. A renamed product keeps its old name as one of
    its other names, so what people are used to typing still finds it.

    The web UI used to rename by removing the old name and then adding the
    new one as two requests; if the second failed, the product was gone.
    Returns (ok, message).
    """
    old_product = old_product.upper().strip()
    product = product.upper().strip()
    weight = weight.upper().strip()
    hotel = hotel.lower().strip()
    data = _load()
    prods = data.get(hotel, {})
    old_key = _find_key(prods, old_product)
    if old_key is None:
        return False, f"{old_product} not found in [{hotel}]"
    taken = _taken_names(prods, old_key)
    if norm(product) in taken:
        return False, f"{product} is already in [{hotel}]" if taken[norm(product)].upper() == product \
            else f"{product} already means {taken[norm(product)]} in [{hotel}]"

    old = prods[old_key]
    names = _entry_aliases(old) if aliases is _KEEP else list(aliases)
    if norm(old_key) != norm(product) and norm(old_key) not in {norm(a) for a in names}:
        if len(names) >= MAX_ALIASES:
            return False, (f"{old_key} already has {MAX_ALIASES} other names. Remove one first, "
                           f"so its old name can be kept when it is renamed.")
        names.append(old_key.upper())
    names, err = _check_aliases(prods, old_key, product, names)
    if err:
        return False, f"{err} in [{hotel}]"
    entry = _make_entry(weight, shelf_months, names,
                        _entry_allergens(old) if allergens is _KEEP else allergens)

    # Rebuilt rather than del + insert so the product keeps its place in the list
    data[hotel] = {
        (product if k == old_key else k): (entry if k == old_key else v)
        for k, v in prods.items()
    }
    _save(data)
    return True, f"Updated {product} in [{hotel}]"


def add_hotel(hotel: str):
    """Create an empty hotel. Returns (ok, message)."""
    hotel = (hotel or "").strip().lower()
    if not HOTEL_NAME_RE.match(hotel):
        return False, "Hotel name: letters, numbers, - or _ only, no spaces (max 30)"
    data = _load()
    if hotel in data:
        return False, f"[{hotel}] already exists"
    data[hotel] = {}
    _save(data)
    return True, f"Added hotel [{hotel}]"


def remove_product(product: str, hotel: str = DEFAULT_HOTEL) -> str:
    product = product.upper().strip()
    hotel = hotel.lower().strip()
    data = _load()
    hotel_products = data.get(hotel, {})
    key_to_remove = _find_key(hotel_products, product)
    if not key_to_remove:
        owner = _taken_names(hotel_products).get(norm(product))
        if owner and norm(owner) == norm(product):
            key_to_remove = owner          # the name itself, spaced differently
        elif owner:
            # Only another name: those used to be separate entries (KAJU 2 PC)
            # that now live inside one product, so removing it would remove
            # the product they were folded into.
            return (f"⚠️ *{product}* is another name for *{owner}*. Remove *{owner}* to delete "
                    f"the product, or take {product} out of its other names on the Products page.")
    if not key_to_remove:
        return f"⚠️ *{product}* not found in [{hotel}]."
    del hotel_products[key_to_remove]
    _save(data)
    return f"✅ Removed *{key_to_remove}* from [{hotel}]."


def list_products(hotel: str = None) -> str:
    data = _load()
    if not data:
        return "No products in list."

    if hotel:
        hotel = hotel.lower().strip()
        hotel_products = data.get(hotel, {})
        if not hotel_products:
            return f"No products in [{hotel}]."
        lines = [f"📦 *Product List [{hotel}]:*"]
        for product, val in hotel_products.items():
            shelf = _entry_shelf(val)
            shelf_txt = f" ({shelf} mo shelf life)" if shelf else ""
            allergen_txt = " ⚠️" if _entry_allergens(val) else ""
            lines.append(f"  • {product} → {_entry_weight(val)}{shelf_txt}{allergen_txt}")
        lines.append(
            "\n_Unlisted products need a weight in the message. "
            f"Shelf life defaults to {get_default_shelf_months()} months. "
            "⚠️ = prints an allergen line. Old and local names (PHALLI, BADAM) still work._"
        )
        return "\n".join(lines)

    # List all hotels
    lines = []
    for h, prods in data.items():
        lines.append(f"📦 *[{h}]* — {len(prods)} products")
    lines.append(f"\nUse `/listproducts <hotel>` to see products for a specific hotel.")
    return "\n".join(lines)


def list_hotels() -> list:
    """Returns list of hotel names."""
    data = _load()
    return list(data.keys())


def hotel_entries(hotel: str, data: dict = None) -> list:
    """[{name, weight, shelf_months, aliases, allergens}, ...] for one hotel's own list."""
    data = _load() if data is None else data
    return [
        {"name": k, "weight": _entry_weight(v), "shelf_months": _entry_shelf(v),
         "aliases": _entry_aliases(v), "allergens": _entry_allergens(v)}
        for k, v in data.get(hotel.lower(), {}).items()
    ]


def all_hotel_entries() -> dict:
    """{hotel: [{name, weight, shelf_months, aliases, allergens}, ...]} for every hotel."""
    data = _load()
    return {h: hotel_entries(h, data) for h in data}
