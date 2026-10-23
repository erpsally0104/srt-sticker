"""
English product names, the other names they go by, and their allergens.

Labels print every product under its English name — with the familiar
Indian name in brackets where kitchen staff may not know the English word
(SEMOLINA (RAVA), GRAM FLOUR (BESAN)). Dal names stay as the trade knows
them. Every older or local name is kept as an alias, so PHALLI, PALLI and
GROUNDNUT all still find PEANUTS, in the web UI and on Telegram.

SEED is applied to products.json once, by product_manager._load(), the
first time it finds a list with no aliases in it. That renames each listed
product to its English name and folds spelling variants of one product
(W. PEAS / W PEAS / WHITE PEAS) into a single entry. After that the
Products page owns the data: names, aliases and allergens are edited there.

    python product_catalog.py     # show what the migration does to products.json

Only true variants are merged — same product, same weight. Look-alikes that
may be different products (KABULI vs KABULI CHANA) are left alone; so are
names without a confident English equivalent.
"""

import re

# Allergen wording for the label: "CONTAINS: <these, comma-separated>".
# FSSAI's list: cereals containing gluten, crustacean, milk, egg, fish,
# peanut, tree nuts, soybean, sulphite (10 mg/kg and over).
PEANUT = "PEANUT"
GLUTEN_WHEAT = "GLUTEN (WHEAT)"
GLUTEN_BARLEY = "GLUTEN (BARLEY)"
SOY = "SOY"
def tree_nut(nut): return f"TREE NUTS ({nut})"

# (English name, [names it was or may be typed as], [allergens])
SEED = [
    # ── Pulses and dals ─────────────────────────
    ("TOOR DAL", ["TOORDAL", "TUR DAL", "TUVAR DAL", "TOOVAR DAL", "ARHAR DAL", "KANDI PAPPU"], []),
    ("MOONG DAL", ["MOONGDAL", "MUNG DAL", "YELLOW MOONG DAL", "PESARA PAPPU"], []),
    ("MASOOR DAL", ["MASOORDAL", "MASUR DAL", "RED LENTILS"], []),
    ("CHANA DAL", ["CHANADAL", "BENGAL GRAM DAL", "SENAGA PAPPU"], []),
    ("URAD DAL", ["URADDAL", "UDAD DAL", "MINAPA PAPPU"], []),
    ("GUNDU URAD DAL", ["G. UDAD DAL", "G. URAD DAL", "GUNDU UDAD DAL", "GUNDU URAD"], []),
    ("WHOLE URAD (SABUT)", ["S. UDAD", "SABIT UDAD", "SABUT URAD", "SABUT UDAD"], []),
    ("BLACK URAD", ["BLACK UDAD", "KALI URAD"], []),
    ("GREEN GRAM (MOONG)", ["G. MOONG", "GREEN MOONG", "SABUT MOONG", "WHOLE MOONG", "GREEN GRAM", "PESALU"], []),
    ("CHICKPEAS (KABULI)", ["KABULICHANA", "KABULI CHANA", "CHOLE", "CHHOLE", "SAFED CHANA", "CHICKPEAS"], []),
    ("BLACK CHICKPEAS (CHANA)", ["BLACK CHANA", "CHANA BLACK", "KALA CHANA", "BLACK CHICKPEAS"], []),
    ("BROWN CHICKPEAS", ["BROWN CHANA"], []),
    ("ROASTED GRAM (FUTANA)", ["FUTANA", "PUTNA", "PUTANA", "PUTNALU", "PUTNALA PAPPU", "ROASTED GRAM"], []),
    ("WHITE PEAS", ["W. PEAS", "SAFED MATAR", "VATANA", "WHITE MATAR"], []),
    ("KIDNEY BEANS (RAJMA)", ["RAJMA", "RAJMAH", "RAJMA CHITRA", "KIDNEY BEANS"], []),
    ("RED KIDNEY BEANS", ["RED RAJMA"], []),
    ("BLACK EYED PEAS (LOBIA)", ["LOBIYA", "LOBIA", "BOBBARLU", "CHAWLI", "BLACK EYED PEAS", "COWPEAS"], []),
    ("DOUBLE BEANS", ["LIMA BEANS", "BUTTER BEANS"], []),

    # ── Flours, rava, rice and grains ───────────
    ("SEMOLINA (RAVA)", ["RAWA", "RAVA", "SOOJI", "SUJI", "BOMBAY RAVA", "BOMBAY RAWA", "UPMA RAVA", "SEMOLINA"], [GLUTEN_WHEAT]),
    ("IDLI RAVA", ["IDLY RAWA", "IDLI RAWA", "IDLY RAVA", "RICE RAVA"], []),
    ("BROKEN WHEAT (DALIA)", ["WHEAT RAWA", "W. RAWA", "WHEAT RAVA", "GODHUMA RAVA", "BROKEN WHEAT"], [GLUTEN_WHEAT]),
    ("REFINED FLOUR (MAIDA)", ["MAIDA", "ALL PURPOSE FLOUR", "REFINED WHEAT FLOUR", "REFINED FLOUR"], [GLUTEN_WHEAT]),
    ("GRAM FLOUR (BESAN)", ["BESAN", "BESAN ATTA", "SENAGA PINDI", "CHICKPEA FLOUR", "GRAM FLOUR"], []),
    ("RICE FLOUR", ["RICEFLOUR", "CHAWAL ATTA", "BIYYAM PINDI", "BIYYAPU PINDI"], []),
    ("VERMICELLI (SEMIYA)", ["SEMIYA", "SEMIYAN", "SEVIYAN", "VERMICELLI"], [GLUTEN_WHEAT]),
    ("FLATTENED RICE (POHA)", ["POHA", "POHE", "ATUKULU", "AVAL", "BEATEN RICE", "RICE FLAKES", "FLATTENED RICE"], []),
    ("SAGO (SABUDANA)", ["SABUDANA", "SAGUDANA", "SABOODANA", "SAGO"], []),
    ("IDLI RICE", ["IDLY RICE"], []),
    ("QUINOA", ["QUINOVA", "QUINVA"], []),
    ("PEARL BARLEY", ["BARLEY", "JAU"], [GLUTEN_BARLEY]),
    ("KODO MILLET", ["ARIKELU", "KODRA", "VARAGU"], []),
    ("FOXTAIL MILLET", ["KORRALU", "KORRA", "KANGNI", "THINAI"], []),

    # ── Nuts and dry fruit ──────────────────────
    ("PEANUTS", ["PHALLI", "PALLI", "MOONGPHALI", "MUNGFALI", "GROUNDNUT", "GROUNDNUTS", "SINGDANA", "PALLILU", "PEANUT"], [PEANUT]),
    ("ROASTED PEANUTS", ["ROASTED PHALLI", "ROASTED PALLI", "ROASTED GROUNDNUT", "ROASTED PEANUT"], [PEANUT]),
    ("CASHEW", ["KAJU", "KAJOO", "CASHEWS", "CASHEW NUTS", "CASHEWNUT"], [tree_nut("CASHEW")]),
    ("CASHEW WHOLE", ["S. KAJU", "SABIT KAJU", "SABUT KAJU", "KAJU WHOLE", "WHOLE KAJU", "WHOLE CASHEW"], [tree_nut("CASHEW")]),
    ("CASHEW 2 PCS", ["KAJU 2 PC", "KAJU 2 PCS", "CASHEW 2 PC"], [tree_nut("CASHEW")]),
    ("CASHEW 4 PCS", ["KAJU 4 PC", "KAJU 4 PCS", "CASHEW 4 PC"], [tree_nut("CASHEW")]),
    ("CASHEW 4-6 PCS", ["KAJU 4-6 PC", "KAJU 4-6 PCS", "CASHEW 4-6 PC"], [tree_nut("CASHEW")]),
    ("CASHEW 6 PCS", ["KAJU 6 PC", "KAJU 6 PCS", "CASHEW 6 PC"], [tree_nut("CASHEW")]),
    ("CASHEW 8 PCS", ["KAJU 8 PC", "KAJU 8 PCS", "CASHEW 8 PC"], [tree_nut("CASHEW")]),
    ("CASHEW 12 PCS", ["KAJU 12 PC", "KAJU 12 PCS", "CASHEW 12 PC"], [tree_nut("CASHEW")]),
    ("ALMONDS", ["BADAM", "BADAAM", "BADAM GIRI", "ALMOND"], [tree_nut("ALMOND")]),
    ("ALMOND FLAKES", ["BADAM FLAKES", "SLICED ALMONDS"], [tree_nut("ALMOND")]),
    ("ALMOND POWDER", ["BADAM POWDER", "ALMOND FLOUR"], [tree_nut("ALMOND")]),
    ("PISTACHIOS", ["PISTA", "PISTHA", "PISTACHIO"], [tree_nut("PISTACHIO")]),
    ("RAISINS (KISHMISH)", ["KISMISS", "KISMISH", "KISHMISH", "KISMIS", "RAISINS", "RAISIN"], []),
    ("BLACK RAISINS", ["B. KISMISH", "B. KISMISS", "BLACK KISMISH", "BLACK KISHMISH", "KALI DRAKSH"], []),
    ("APRICOTS (KHUBANI)", ["KHURBANI", "KURBANI", "KHUBANI", "DRIED APRICOTS", "APRICOTS"], []),
    ("DRIED FIGS (ANJEER)", ["ANJIR", "ANJEER", "FIGS", "DRIED FIGS"], []),
    ("DRY COCONUT (KHOPRA)", ["KHOPRA", "KOPRA", "COPRA", "ENDU KOBBARI", "SUKHA NARIYAL", "DRY COCONUT"], []),
    ("CHIRONJI", ["CHAROLI", "SARAPAPPU"], []),
    ("MELON SEEDS (TARBUJ)", ["TARBUJ", "TARBOOJ", "MAGAZ", "MAGAJ", "MELON SEEDS", "WATERMELON SEEDS"], []),

    # ── Seeds ───────────────────────────────────
    ("SUNFLOWER SEEDS", ["SUNFLOWER", "SUNFLOWER SEED"], []),
    ("PUMPKIN SEEDS", ["PUMPKIN", "PUMPKIN SEED", "KADDU BEEJ"], []),
    ("FLAX SEEDS", ["FLAXSEEDS", "FLAXSEED", "ALSI", "LINSEED", "AVISE GINJALU"], []),
    ("CHIA SEEDS", ["CHIASEEDS", "CHIA SEED"], []),
    ("BASIL SEEDS (SABJA)", ["SABJA SEEDS", "SABJA", "TUKMARIA", "SABJA GINJALU", "BASIL SEEDS"], []),
    ("SESAME SEEDS (TIL)", ["TILLI", "TIL", "NUVVULU", "SESAME", "SESAME SEEDS"], []),
    ("WHITE SESAME SEEDS", ["W. TILLI", "WHITE TILLI", "WHITE TIL", "SAFED TIL", "WHITE SESAME"], []),
    ("BLACK SESAME SEEDS", ["B. TILLI", "BLACK TILLI", "BLACK TIL", "KALA TIL", "BLACK SESAME"], []),

    # ── Spices ──────────────────────────────────
    ("CUMIN SEEDS (JEERA)", ["JEERA", "JIRA", "ZEERA", "JEELAKARRA", "CUMIN", "CUMIN SEEDS"], []),
    ("BLACK CUMIN (SHAHJEERA)", ["SHAHJEERA", "SHAH JEERA", "SHAHI JEERA", "KALA JEERA", "BLACK CUMIN"], []),
    ("BLACK PEPPER", ["KALIMIRCHI", "KALI MIRCHI", "KALI MIRCH", "MIRIYALU", "PEPPER"], []),
    ("FENNEL SEEDS (SAUNF)", ["SOUNF", "SAUNF", "SONF", "SOMPU", "FENNEL", "FENNEL SEEDS"], []),
    ("FENUGREEK SEEDS (METHI)", ["METHI", "METHI DANA", "MENTHULU", "FENUGREEK", "FENUGREEK SEEDS"], []),
    ("MUSTARD SEEDS (RAI)", ["RAI", "SARSON", "AVALU", "MUSTARD", "MUSTARD SEEDS"], []),
    ("CAROM SEEDS (AJWAIN)", ["AJWAIN", "AJWAN", "VAMU", "OMAM", "CAROM SEEDS"], []),
    ("CORIANDER (DHANIYA)", ["DHANIYA", "DHANIA", "DANIYA", "DHANIYALU", "CORIANDER", "CORIANDER SEEDS"], []),
    ("POPPY SEEDS (KASKAS)", ["KAS KAS", "KHUS KHUS", "KHASKHAS", "GASAGASALU", "POPPY SEEDS"], []),
    ("CLOVES (LAUNG)", ["LOUNG", "LAUNG", "LAVANG", "LONG", "LAVANGALU", "CLOVE", "CLOVES"], []),
    ("CINNAMON (DALCHINI)", ["DALCHINI", "DAL CHINI", "CHEKKA", "CINNAMON"], []),
    ("CARDAMOM (ELAICHI)", ["ELAICHI", "ELACHI", "ILAICHI", "YELAKKAI", "GREEN ELAICHI", "CARDAMOM", "GREEN CARDAMOM"], []),
    ("BLACK CARDAMOM", ["B. ELAICHI", "BADI ELAICHI", "BADA ELAICHI", "DODA ELAICHI", "DODDA ELAICHI", "KALI ELAICHI"], []),
    ("BAY LEAF (TEJ PATTA)", ["TEJ PATTA", "TEJ PATTI", "BIRYANI AKU", "BAY LEAF", "BAY LEAVES"], []),
    ("NUTMEG (JAIPHAL)", ["JAIPHAL", "JAYPHAL", "JAJIKAYA", "NUTMEG"], []),
    ("MACE (JAVITRI)", ["JAVITRI", "JAVETRI", "JAPATRI", "JAJIPATRI", "MACE"], []),
    ("STAR ANISE", ["STAR ANNISE", "STAR ANIS", "BADIYAN", "BADIAN", "CHAKRI PHOOL", "ANASA PUVVU"], []),
    ("LONG PEPPER (PIPLI)", ["PIPLI", "PIPALI", "PIPPALI", "LONG PEPPER"], []),
    ("STONE FLOWER", ["PHATTAR PHOOL", "PATHAR PHOOL", "PATTHAR PHOOL", "DAGAD PHOOL", "KALPASI"], []),
    ("ROSE BUDS (GULAB KALI)", ["GULAB KALI", "ROSE BUDS", "DRIED ROSE BUDS"], []),
    ("DRIED ROSE PETALS", ["ROSE PETAL", "ROSE PETALS", "GULAB PATTI"], []),
    ("TAMARIND (IMLI)", ["IMLY", "IMLI", "CHINTAPANDU", "TAMARIND"], []),
    ("KOKUM", ["KOKAM", "AMSUL"], []),
    ("KASHMIRI CHILLI", ["KASHMIRI MIRCHI", "KASH. MIRCHI", "KASHMIRI MIRCH", "KASHMIRI CHILLY"], []),
    ("BYADGI CHILLI", ["BEDGI MIRCHI", "BYADGI MIRCHI", "BEDGI CHILLI", "BYADGI CHILLY"], []),
    ("RESHAMPATTI CHILLI", ["RESHAMPATTI CHILLY", "RESHAMPATTI MIRCHI"], []),
    ("WHOLE RED CHILLI", ["S. MIRCHI", "SABIT MIRCHI", "SABUT MIRCHI", "SABUT LAL MIRCH", "WHOLE RED CHILLY"], []),
    ("WHOLE CHILLI", ["CHILLY WHOLE", "CHILLI WHOLE", "WHOLE CHILLY"], []),
    ("RED CHILLI", ["RED CHILLY", "LAL MIRCHI", "LAL MIRCH"], []),

    # ── Everything else ─────────────────────────
    ("SOYA CHUNKS", ["MEAL MAKER", "SOYA BADI", "SOYA NUGGETS"], [SOY]),
    ("BAKING SODA", ["COOKING SODA", "EATING SODA", "MEETHA SODA", "SODA BICARB", "SODIUM BICARBONATE"], []),
    ("ROCK SUGAR (MISHRI)", ["MISHRI", "MISRI", "KALKANDA", "SUGAR CANDY", "ROCK SUGAR"], []),
    ("SUGAR", ["CHEENI", "SHAKKAR"], []),
]


def norm(name) -> str:
    """Letters and digits only, upper case: 'W. Peas' and 'WPEAS' are one name."""
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


def grams(weight):
    """'2 kg' / '2 KGS' / '500 GMS' → grams, or None when it doesn't parse."""
    m = re.match(r"^\s*([\d.]+)\s*(KGS?|KILOS?|GMS?|GRAMS?|G)?\s*$", str(weight).upper())
    if not m:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    return n * 1000 if (m.group(2) or "").startswith("K") else n


def _same_weight(a, b) -> bool:
    ga, gb = grams(a), grams(b)
    if ga is None or gb is None:
        return str(a).strip().upper() == str(b).strip().upper()
    return ga == gb


def migrate(data: dict, default_hotel: str = "general"):
    """
    Rename every SEED product in `data` ({hotel: {name: entry}}) to its English
    name, fold its variants into one entry and give it its aliases and
    allergens. Returns (new_data, report_lines). Pure: `data` is not changed.

    A variant whose weight differs from the first one found is a different
    pack, not a spelling — it keeps its own name and entry, and is reported.
    Outside General, a product General also has gets only the rename: its
    aliases and allergens stay on the General entry, which hotels fall back
    to, so they are edited in one place.
    """
    index = {}
    for i, (english, aliases, _) in enumerate(SEED):
        for n in [english] + aliases:
            index.setdefault(norm(n), i)

    general_names = {index.get(norm(k)) for k in data.get(default_hotel, {})} - {None}
    out, report = {}, []

    for hotel, prods in data.items():
        groups = {}                   # seed index → [(old name, entry)]
        order  = []                   # ("seed", i) or ("keep", name), in list order
        for key, val in prods.items():
            i = index.get(norm(key))
            if i is None:
                order.append(("keep", key))
                continue
            if i not in groups:
                groups[i] = []
                order.append(("seed", i))
            groups[i].append((key, val))

        new = {}
        for kind, ref in order:
            if kind == "keep":
                new[ref] = prods[ref]
                continue
            english, seed_aliases, allergens = SEED[ref]
            # An entry already under the English name leads its group, so a
            # variant kept apart (a different pack) never lands on its key
            members = sorted(groups[ref], key=lambda m: norm(m[0]) != norm(english))
            first_key, first_val = members[0]
            weight = first_val.get("weight", "") if isinstance(first_val, dict) else str(first_val)
            entry  = dict(first_val) if isinstance(first_val, dict) else {"weight": weight}

            folded, kept_apart = [first_key], []
            for key, val in members[1:]:
                w = val.get("weight", "") if isinstance(val, dict) else str(val)
                if _same_weight(w, weight):
                    folded.append(key)
                    shelf = val.get("shelf_months") if isinstance(val, dict) else None
                    if shelf and not entry.get("shelf_months"):
                        entry["shelf_months"] = shelf
                else:
                    kept_apart.append((key, val))

            if hotel == default_hotel or ref not in general_names:
                apart = {norm(k) for k, _ in kept_apart}
                names, seen = [], {norm(english)}
                for n in folded + seed_aliases:
                    if norm(n) not in seen and norm(n) not in apart:
                        seen.add(norm(n))
                        names.append(n.upper())
                entry.setdefault("aliases", names)
                if allergens and not entry.get("allergens"):
                    entry["allergens"] = list(allergens)
            new[english] = entry if len(entry) > 1 else entry["weight"]

            renamed = [k for k in folded if k != english]
            if renamed:
                report.append(f"[{hotel}] {' + '.join(renamed):40s} → {english}")
            for key, val in kept_apart:
                new[key] = val
                report.append(f"[{hotel}] {key:40s}   kept apart: weight differs from {first_key}")
        out[hotel] = new
    return out, report


if __name__ == "__main__":
    import json
    from product_manager import PRODUCTS_FILE, _read_json
    current = _read_json(PRODUCTS_FILE) or {}
    if any(isinstance(v, dict) and "aliases" in v for p in current.values() for v in p.values()):
        print("products.json already has English names — nothing to do.")
    else:
        _, lines = migrate(current)
        print("\n".join(lines) or "Nothing to rename.")
