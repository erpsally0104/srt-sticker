"""
Ingredients and nutrition for the second sticker a product label can bring,
ticked per item on the Print tab ("Ingredients & nutrition sticker").

SEED fills it in for every product in product_catalog.SEED. A copy saved
from the Print tab (kept on the product in products.json) wins over it; see
product_manager.product_info().

Nutrition is per 100 g, from ICMR-NIN's Indian Food Composition Tables 2017
(IFCT, food code given) where it lists the food, else from USDA FoodData
Central's SR Legacy table (FDC id given). Energy is worked out with FSSAI's
factors (Reg 5(3)(e)): 4 kcal/g protein and available carbohydrate, 9 fat,
2 dietary fibre. Carbohydrate is available carbohydrate, fibre not counted.
Added sugars are 0 throughout: nothing is added to these foods.

These are typical values for each food, not tests of the shop's stock. Once
printed they are a declaration, and the real content may be at most 10%
below what the label says at any point in its shelf life (Reg 5(3)(d)), so
check the big sellers against the supplier's specification.

None means no published values were found for the product (or, for chia,
fennel and melon seeds, none for their sugars). Its sticker carries the
ingredients only, until someone enters the values on the Print tab.
"""

import math

from product_catalog import SEED as CATALOG, norm

# (key, label on the sticker, unit, set under the line above it, largest value accepted)
NUTRIENTS = (
    ("energy_kcal",     "Energy",        "kcal", False, 900),
    ("protein_g",       "Protein",       "g",    False, 100),
    ("carbohydrate_g",  "Carbohydrate",  "g",    False, 100),
    ("total_sugars_g",  "Total Sugars",  "g",    True,  100),
    ("added_sugars_g",  "Added Sugars",  "g",    True,  100),
    ("total_fat_g",     "Total Fat",     "g",    False, 100),
    ("saturated_fat_g", "Saturated Fat", "g",    True,  100),
    ("trans_fat_g",     "Trans Fat",     "g",    True,  100),
    ("sodium_mg",       "Sodium",        "mg",   False, 40000),
)
NUTRIENT_KEYS = tuple(n[0] for n in NUTRIENTS)

# Long enough for a blended product's list; at this length it still prints
# at 12 px or more on the 50 x 40 sticker, together with the table.
MAX_INGREDIENTS_LEN = 300

# name: (ingredients, (energy kcal, protein g, carbohydrate g, total sugars g,
#        added sugars g, total fat g, saturated fat g, trans fat g, sodium mg) or None, source)
SEED = {
    # ── Pulses and dals ───────────────────────────
    "TOOR DAL":                 ("Toor dal (split pigeon peas)",           (340, 21.7, 55.2, 2.1, 0, 1.6, 0.3, 0, 18),      "IFCT 2017 B021: Red gram, dal"),
    "MOONG DAL":                ("Moong dal (split green gram)",           (337, 23.9, 52.6, 1, 0, 1.4, 0.2, 0, 10),        "IFCT 2017 B010: Green gram, dal"),
    "MASOOR DAL":               ("Masoor dal (split red lentils)",         (335, 24.4, 52.5, 2, 0, 0.8, 0.1, 0, 10),        "IFCT 2017 B013: Lentil dal"),
    "CHANA DAL":                ("Chana dal (split Bengal gram)",          (351, 21.6, 46.7, 1, 0, 5.3, 0.5, 0, 21),        "IFCT 2017 B001: Bengal gram, dal"),
    "URAD DAL":                 ("Urad dal (split black gram)",            (335, 23.1, 51, 0.8, 0, 1.7, 0.3, 0, 19),        "IFCT 2017 B003: Black gram, dal"),
    "GUNDU URAD DAL":           ("Whole skinned black gram (gundu urad)",  (335, 23.1, 51, 0.8, 0, 1.7, 0.3, 0, 19),        "IFCT 2017 B003: Black gram, dal"),
    "WHOLE URAD (SABUT)":       ("Whole black gram (sabut urad)",          (319, 22, 44, 0.5, 0, 1.6, 0.3, 0, 27),          "IFCT 2017 B004: Black gram, whole"),
    "BLACK URAD":               ("Whole black gram",                       (319, 22, 44, 0.5, 0, 1.6, 0.3, 0, 27),          "IFCT 2017 B004: Black gram, whole"),
    "GREEN GRAM (MOONG)":       ("Whole green gram (moong)",               (319, 22.5, 46.1, 0.5, 0, 1.1, 0.3, 0, 12),      "IFCT 2017 B011: Green gram, whole"),
    "CHICKPEAS (KABULI)":       ("Kabuli chickpeas",                       (364, 20.5, 50.8, 10.7, 0, 6, 0.6, 0, 24),       "USDA FDC 173756: Chickpeas (garbanzo beans, bengal gram), mature seeds, raw"),
    "BLACK CHICKPEAS (CHANA)":  ("Black chickpeas (kala chana)",           (330, 18.8, 39.6, 1, 0, 5.1, 0.5, 0, 27),        "IFCT 2017 B002: Bengal gram, whole"),
    "BROWN CHICKPEAS":          ("Brown chickpeas",                        (330, 18.8, 39.6, 1, 0, 5.1, 0.5, 0, 27),        "IFCT 2017 B002: Bengal gram, whole"),
    "ROASTED GRAM (FUTANA)":    ("Roasted Bengal gram",                    None,                                            ""),
    "WHITE PEAS":               ("Dried white peas",                       (328, 20.4, 48.9, 2, 0, 1.9, 0.2, 0, 23),        "IFCT 2017 B017: Peas, dry"),
    "KIDNEY BEANS (RAJMA)":     ("Kidney beans (rajma)",                   (322, 19.5, 48.8, 2.3, 0, 1.7, 0.2, 0, 10),      "IFCT 2017 B019: Rajmah, brown"),
    "RED KIDNEY BEANS":         ("Red kidney beans",                       (323, 19.9, 48.6, 1.5, 0, 1.8, 0.3, 0, 10),      "IFCT 2017 B020: Rajmah, red"),
    "BLACK EYED PEAS (LOBIA)":  ("Black-eyed peas (lobia)",                (334, 21.3, 53.8, 1.2, 0, 1.1, 0.3, 0, 13),      "IFCT 2017 B006: Cowpea, white"),
    "DOUBLE BEANS":             ("Dried double beans (lima beans)",        (308, 21.5, 44.4, 8.5, 0, 0.7, 0.2, 0, 18),      "USDA FDC 174252: Lima beans, large, mature seeds, raw"),
    # ── Flours, rava, rice and grains ─────────────
    "SEMOLINA (RAVA)":          ("Wheat semolina (rava)",                  (345, 11.4, 68.4, 1.7, 0, 0.7, 0.1, 0, 2),       "IFCT 2017 A022: Wheat, semolina"),
    "IDLI RAVA":                ("Parboiled rice rava",                    (352, 7.8, 77.2, 0.7, 0, 0.6, 0.2, 0, 3),        "IFCT 2017 A014: Rice, parboiled, milled"),
    "BROKEN WHEAT (DALIA)":     ("Broken wheat (dalia)",                   (337, 10.6, 64.7, 1.8, 0, 1.5, 0.2, 0, 2),       "IFCT 2017 A020: Wheat, whole"),
    "REFINED FLOUR (MAIDA)":    ("Refined wheat flour (maida)",            (351, 10.4, 74.3, 1.8, 0, 0.8, 0.1, 0, 2),       "IFCT 2017 A018: Wheat flour, refined"),
    "GRAM FLOUR (BESAN)":       ("Bengal gram flour (besan)",              (351, 21.6, 46.7, 1, 0, 5.3, 0.5, 0, 21),        "IFCT 2017 B001: Bengal gram, dal"),
    "RICE FLOUR":               ("Rice flour",                             (355, 7.9, 78.2, 0.7, 0, 0.5, 0.2, 0, 2),        "IFCT 2017 A015: Rice, raw, milled"),
    "VERMICELLI (SEMIYA)":      ("Wheat semolina",                         (343, 9.7, 70.4, 1.7, 0, 0.5, 0.1, 0, 3),        "IFCT 2017 A023: Wheat, vermicelli"),
    "FLATTENED RICE (POHA)":    ("Flattened rice (poha)",                  (354, 7.4, 76.8, 0.3, 0, 1.1, 0.3, 0, 3),        "IFCT 2017 A011: Rice flakes"),
    "SAGO (SABUDANA)":          ("Sago pearls (tapioca)",                  (354, 0.2, 87.8, 3.4, 0, 0, 0, 0, 1),            "USDA FDC 169717: Tapioca, pearl, dry"),
    "IDLI RICE":                ("Parboiled rice",                         (352, 7.8, 77.2, 0.7, 0, 0.6, 0.2, 0, 3),        "IFCT 2017 A014: Rice, parboiled, milled"),
    "QUINOA":                   ("Quinoa",                                 (346, 13.1, 53.7, 1.4, 0, 5.5, 0.6, 0, 4),       "IFCT 2017 A009: Quinoa"),
    "PEARL BARLEY":             ("Pearl barley",                           (330, 9.9, 62.1, 0.8, 0, 1.2, 0.2, 0, 9),        "USDA FDC 170284: Barley, pearled, raw"),
    "KODO MILLET":              ("Kodo millet",                            (336, 8.9, 66.2, 1.3, 0, 2.6, 0.2, 0, 3),        "IFCT 2017 A017: Varagu"),
    "FOXTAIL MILLET":           ("Foxtail millet",                         None,                                            ""),
    # ── Nuts and dry fruit ────────────────────────
    "PEANUTS":                  ("Peanuts",                                (541, 23.7, 17.3, 4.4, 0, 39.6, 8.1, 0, 12),     "IFCT 2017 H012: Ground nut"),
    "ROASTED PEANUTS":          ("Roasted peanuts",                        (613, 24.4, 12.9, 4.9, 0, 49.7, 7.7, 0, 6),      "USDA FDC 173806: Peanuts, all types, dry-roasted, without salt"),
    "CASHEW":                   ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "CASHEW WHOLE":             ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "CASHEW 2 PCS":             ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "CASHEW 4 PCS":             ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "CASHEW 4-6 PCS":           ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "CASHEW 6 PCS":             ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "CASHEW 8 PCS":             ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "CASHEW 12 PCS":            ("Cashew kernels",                         (591, 18.8, 25.5, 3.1, 0, 45.2, 7.8, 0, 9),      "IFCT 2017 H005: Cashew nut"),
    "ALMONDS":                  ("Almonds",                                (638, 18.4, 3, 2.2, 0, 58.5, 4.4, 0, 2),         "IFCT 2017 H001: Almond"),
    "ALMOND FLAKES":            ("Sliced almonds",                         (638, 18.4, 3, 2.2, 0, 58.5, 4.4, 0, 2),         "IFCT 2017 H001: Almond"),
    "ALMOND POWDER":            ("Ground almonds",                         (638, 18.4, 3, 2.2, 0, 58.5, 4.4, 0, 2),         "IFCT 2017 H001: Almond"),
    "PISTACHIOS":               ("Pistachios",                             (560, 23.4, 15.8, 7.9, 0, 42.5, 4, 0, 7),        "IFCT 2017 H018: Pistachio nuts"),
    "RAISINS (KISHMISH)":       ("Raisins",                                (298, 2.8, 68.8, 57.1, 0, 0.4, 0.1, 0, 10),      "IFCT 2017 E058: Raisins, dried, golden"),
    "BLACK RAISINS":            ("Black raisins",                          (306, 2.6, 71.3, 61.5, 0, 0.3, 0.1, 0, 11),      "IFCT 2017 E057: Raisins, dried, black"),
    "APRICOTS (KHUBANI)":       ("Dried apricots",                         (316, 3.2, 72.6, 25.7, 0, 0.7, 0.2, 0, 4),       "IFCT 2017 E005: Apricot, dried"),
    "DRIED FIGS (ANJEER)":      ("Dried figs",                             (257, 3.3, 54.1, 47.9, 0, 0.9, 0.1, 0, 10),      "USDA FDC 174665: Figs, dried, uncooked"),
    "DRY COCONUT (KHOPRA)":     ("Dried coconut kernel (copra)",           (662, 7.3, 8, 6.9, 0, 63.3, 43.1, 0, 17),        "IFCT 2017 H006: Coconut, kernal, dry"),
    "CHIRONJI":                 ("Chironji kernels",                       None,                                            ""),
    "MELON SEEDS (TARBUJ)":     ("Melon seed kernels",                     None,                                            ""),
    # ── Seeds ─────────────────────────────────────
    "SUNFLOWER SEEDS":          ("Sunflower seed kernels",                 (610, 23.5, 6.9, 2.8, 0, 51.9, 6.2, 0, 2),       "IFCT 2017 H020: Sunflower seeds"),
    "PUMPKIN SEEDS":            ("Pumpkin seed kernels",                   (593, 30.2, 4.7, 1.4, 0, 49.1, 8.7, 0.1, 7),     "USDA FDC 170556: Seeds, pumpkin and squash seed kernels, dried"),
    "FLAX SEEDS":               ("Flax seeds",                             (492, 18.6, 11, 0.6, 0, 35.7, 3, 0, 33),         "IFCT 2017 H014: Linseeds"),
    "CHIA SEEDS":               ("Chia seeds",                             None,                                            ""),
    "BASIL SEEDS (SABJA)":      ("Sweet basil seeds (sabja)",              None,                                            ""),
    "SESAME SEEDS (TIL)":       ("Sesame seeds",                           (552, 21.7, 10.8, 0.7, 0, 43.1, 6.4, 0, 15),     "IFCT 2017 H011: Gingelly seeds, white"),
    "WHITE SESAME SEEDS":       ("White sesame seeds",                     (552, 21.7, 10.8, 0.7, 0, 43.1, 6.4, 0, 15),     "IFCT 2017 H011: Gingelly seeds, white"),
    "BLACK SESAME SEEDS":       ("Black sesame seeds",                     (540, 19.2, 10.3, 1, 0, 43.1, 6.3, 0, 16),       "IFCT 2017 H009: Gingelly seeds, black"),
    # ── Spices ────────────────────────────────────
    "CUMIN SEEDS (JEERA)":      ("Cumin seeds",                            (357, 13.9, 22.6, 1.4, 0, 16.6, 0.6, 0, 125),    "IFCT 2017 G025: Cumin seeds"),
    "BLACK CUMIN (SHAHJEERA)":  ("Black cumin seeds (shahjeera)",          None,                                            ""),
    "BLACK PEPPER":             ("Black pepper",                           (276, 10.1, 36.2, 0.3, 0, 2.7, 0.7, 0, 24),      "IFCT 2017 G031: Pepper, black"),
    "FENNEL SEEDS (SAUNF)":     ("Fennel seeds",                           None,                                            ""),
    "FENUGREEK SEEDS (METHI)":  ("Fenugreek seeds",                        (290, 25.4, 10.6, 0.6, 0, 5.7, 0.8, 0, 40),      "IFCT 2017 G026: Fenugreek seeds"),
    "MUSTARD SEEDS (RAI)":      ("Mustard seeds",                          (535, 19.5, 16.8, 5.1, 0, 40.2, 2.1, 0, 4),      "IFCT 2017 H013: Mustard seeds"),
    "CAROM SEEDS (AJWAIN)":     ("Carom seeds (ajwain)",                   (393, 15.9, 24.5, 2.8, 0, 21.1, 1.1, 0, 29),     "IFCT 2017 G029: Omum"),
    "CORIANDER (DHANIYA)":      ("Coriander seeds",                        (341, 10.7, 13, 2.4, 0, 17.5, 1, 0, 34),         "IFCT 2017 G024: Coriander seeds"),
    "POPPY SEEDS (KASKAS)":     ("Poppy seeds",                            (458, 20.3, 12.4, 1.9, 0, 30.4, 2.1, 0, 25),     "IFCT 2017 G032: Poppy seeds"),
    "CLOVES (LAUNG)":           ("Cloves",                                 (243, 5.9, 18.7, 2.1, 0, 8.4, 2.7, 0, 183),      "IFCT 2017 G023: Cloves"),
    "CINNAMON (DALCHINI)":      ("Cinnamon",                               (243, 4, 27.5, 2.2, 0, 1.2, 0.3, 0, 10),         "USDA FDC 171320: Spices, cinnamon, ground"),
    "CARDAMOM (ELAICHI)":       ("Green cardamom",                         (293, 8.1, 47.8, 4.3, 0, 2.6, 0.6, 0, 16),       "IFCT 2017 G020: Cardamom, green"),
    "BLACK CARDAMOM":           ("Black cardamom",                         (309, 6.7, 52.5, 2.3, 0, 2.8, 0.5, 0, 16),       "IFCT 2017 G021: Cardamom, black"),
    "BAY LEAF (TEJ PATTA)":     ("Indian bay leaves (tej patta)",          None,                                            ""),
    "NUTMEG (JAIPHAL)":         ("Nutmeg",                                 (488, 6.3, 27.6, 1.1, 0, 36.5, 3.4, 0, 14),      "IFCT 2017 G028: Nutmeg"),
    "MACE (JAVITRI)":           ("Mace",                                   (391, 6.2, 26.5, 0.9, 0, 24.4, 9.3, 0, 27),      "IFCT 2017 G027: Mace"),
    "STAR ANISE":               ("Star anise",                             None,                                            ""),
    "LONG PEPPER (PIPLI)":      ("Long pepper (pippali)",                  (274, 10.5, 35.7, 2.8, 0, 2.3, 0.6, 0, 16),      "IFCT 2017 G030: Pippali"),
    "STONE FLOWER":             ("Stone flower (dagad phool)",             None,                                            ""),
    "ROSE BUDS (GULAB KALI)":   ("Dried rose buds",                        None,                                            ""),
    "DRIED ROSE PETALS":        ("Dried rose petals",                      None,                                            ""),
    "TAMARIND (IMLI)":          ("Tamarind",                               (293, 2.9, 67.4, 52.9, 0, 0.2, 0, 0, 25),        "IFCT 2017 E064: Tamarind, pulp"),
    "KOKUM":                    ("Dried kokum",                            None,                                            ""),
    "KASHMIRI CHILLI":          ("Dried Kashmiri red chillies",            (288, 12.7, 29.5, 4.7, 0, 6.4, 1.1, 0, 19),      "IFCT 2017 G022: Chillies, red"),
    "BYADGI CHILLI":            ("Dried Byadgi red chillies",              (288, 12.7, 29.5, 4.7, 0, 6.4, 1.1, 0, 19),      "IFCT 2017 G022: Chillies, red"),
    "RESHAMPATTI CHILLI":       ("Dried Reshampatti red chillies",         (288, 12.7, 29.5, 4.7, 0, 6.4, 1.1, 0, 19),      "IFCT 2017 G022: Chillies, red"),
    "WHOLE RED CHILLI":         ("Dried whole red chillies",               (288, 12.7, 29.5, 4.7, 0, 6.4, 1.1, 0, 19),      "IFCT 2017 G022: Chillies, red"),
    "WHOLE CHILLI":             ("Dried whole chillies",                   (288, 12.7, 29.5, 4.7, 0, 6.4, 1.1, 0, 19),      "IFCT 2017 G022: Chillies, red"),
    "RED CHILLI":               ("Dried red chillies",                     (288, 12.7, 29.5, 4.7, 0, 6.4, 1.1, 0, 19),      "IFCT 2017 G022: Chillies, red"),
    # ── Everything else ───────────────────────────
    "SOYA CHUNKS":              ("Defatted soya flour",                    (318, 51.5, 16.4, 16.4, 0, 1.2, 0.1, 0, 20),     "USDA FDC 174275: Soy flour, defatted"),
    "BAKING SODA":              ("Sodium bicarbonate (INS 500(ii))",       (0, 0, 0, 0, 0, 0, 0, 0, 27360),                 "USDA FDC 175040: Leavening agents, baking soda"),
    "ROCK SUGAR (MISHRI)":      ("Sugar",                                  (400, 0, 100, 99.8, 0, 0, 0, 0, 1),              "USDA FDC 169655: Sugars, granulated"),
    "SUGAR":                    ("Sugar",                                  (400, 0, 100, 99.8, 0, 0, 0, 0, 1),              "USDA FDC 169655: Sugars, granulated"),
}

# Every name the catalog knows a product by, so a product renamed since (or
# still under an old name) finds its seed: norm(name or alias) -> SEED key
_SEED_NAMES = {}
for _name, _aliases, _ in CATALOG:
    for _n in [_name] + _aliases:
        _SEED_NAMES.setdefault(norm(_n), _name)


def seed_info(*names):
    """
    SEED's {"ingredients", "nutrition", "source"} for the first of `names`
    the catalog knows, by its English name or another of its names; None if
    none is. "nutrition" is {} for a product with no published values.
    """
    for name in names:
        key = _SEED_NAMES.get(norm(name))
        if key in SEED:
            ingredients, values, source = SEED[key]
            return {"ingredients": ingredients,
                    "nutrition": dict(zip(NUTRIENT_KEYS, values)) if values else {},
                    "source": source}
    return None


def _rounded(key, value):
    # Whole kcal and mg; grams to one decimal, as nutrition panels print them
    return int(round(value)) if key in ("energy_kcal", "sodium_mg") else round(value, 1)


def _check_parts(v):
    """An error when a part is bigger than its whole, which is a typo; None if the table adds up."""
    if v["total_sugars_g"] > v["carbohydrate_g"]:
        return "Total sugars can't be more than carbohydrate"
    if v["added_sugars_g"] > v["total_sugars_g"]:
        return "Added sugars can't be more than total sugars"
    # A tenth allowed for rounding each of the three
    if v["saturated_fat_g"] + v["trans_fat_g"] > v["total_fat_g"] + 0.1:
        return "Saturated fat and trans fat together can't be more than total fat"
    if v["protein_g"] + v["carbohydrate_g"] + v["total_fat_g"] > 100.5:
        return "Protein, carbohydrate and fat add up to more than 100 g"
    return None


def clean_info(raw):
    """
    ({"ingredients", "nutrition"}, None) from the Print tab's fields, or
    (None, error). The nutrition table is all or nothing, because a gap
    would read as nought. The ingredients alone, or the table alone, is
    fine; neither is refused.
    """
    if not isinstance(raw, dict):
        return None, "Ingredients and nutrition are missing"
    ingredients = " ".join(str(raw.get("ingredients") or "").split())
    if len(ingredients) > MAX_INGREDIENTS_LEN:
        return None, f"Ingredients must be {MAX_INGREDIENTS_LEN} characters or fewer"
    given = raw.get("nutrition") or {}
    if not isinstance(given, dict):
        return None, "Nutrition values are missing"

    values = {}
    for key, label, unit, _, top in NUTRIENTS:
        v = given.get(key)
        if v is None or str(v).strip() == "":
            continue
        try:
            v = float(str(v).strip())
        except ValueError:
            return None, f"{label} must be a number"
        if not math.isfinite(v) or not 0 <= v <= top:
            return None, f"{label} must be from 0 to {top:g} {unit} per 100 g"
        values[key] = _rounded(key, v)
    if values and len(values) < len(NUTRIENTS):
        missing = [label.lower() for key, label, *_ in NUTRIENTS if key not in values]
        return None, f"Fill in every nutrition value or leave them all blank ({', '.join(missing)} missing)"
    if values:
        err = _check_parts(values)
        if err:
            return None, err
    if not ingredients and not values:
        return None, "Enter the ingredients, the nutrition values, or both"
    return {"ingredients": ingredients, "nutrition": values}, None


def nutrition_rows(nutrition):
    """
    [(label, amount, set under the line above)] for the sticker's table, in
    FSSAI's order. Saturated and trans fat are left out at 0.5 g of fat or
    less, as Reg 5(3)(b) asks for them only above that.
    """
    if not nutrition:
        return []
    low_fat = nutrition.get("total_fat_g", 0) <= 0.5
    return [(label, f"{nutrition[key]:g} {unit}", sub)
            for key, label, unit, sub, _ in NUTRIENTS
            if not (low_fat and key in ("saturated_fat_g", "trans_fat_g"))]
