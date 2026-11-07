"""Seed data, loaded fresh from demo-data/ every time the server starts. All of it is fictional.

    demo-data/settings.json        owner settings (25% DoorDash fee, $0.50 packaging, 38% target)
    demo-data/ingredients.csv      pack size, unit, last pack price, yield %, invoice alias
    demo-data/recipes.csv          quantity of each ingredient per serving (in its pack unit)
    demo-data/menu.csv             in-store and DoorDash prices
    demo-data/price_history.csv    prior deliveries (source of "before" prices)
    demo-data/doordash_orders.csv  90 days of orders -> monthly forecast (last 28 days)
    demo-data/inbox/*.png          tonight's invoices (plus a forwarded duplicate)
    demo-data/invoices_extracted_fallback.json   what those invoices say (used instead of the AI)

How a per-serving cost is built (see margins.py):
    pack price / pack size / yield x quantity per serving
    e.g. brisket: $134.20 / 20 lb / 70% x 0.35 lb
"""

import csv
import hashlib
import json
import re
from datetime import date, timedelta
from pathlib import Path

DEMO = Path(__file__).parent / "demo-data"
INBOX = DEMO / "inbox"


def _rows(name):
    with open(DEMO / name, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


# ---------------------------------------------------------------- units
# Everything converts to a base unit: grams, millilitres, or a count.
UNITS = {
    "lb": ("g", 453.592),
    "kg": ("g", 1000.0),
    "oz": ("g", 28.3495),
    "g": ("g", 1.0),
    "fl_oz": ("ml", 29.5735),
    "gal": ("ml", 3785.41),
    "each": ("each", 1.0),
    "sheet": ("each", 1.0),
    "bowl": ("bowl", 1.0),   # pho spice kit "for 40 bowls"
}

# ---------------------------------------------------------------- settings
_settings = json.loads((DEMO / "settings.json").read_text())
RESTAURANT_NAME = _settings["restaurant"]["name"]
RESTAURANT_TZ = _settings["restaurant"].get("timezone", "America/New_York")   # Pittsburgh, PA
OWNER_NAME = _settings["restaurant"].get("owner", "")   # demo default; each restaurant can override
COMMISSION_CHOICES = (15, 25, 30)

# Spanish names (the dataset is English-only).
_ES = {
    "brisket": "Pecho de res", "chicken_thigh": "Muslo de pollo, sin hueso", "pork_shoulder": "Paleta de cerdo",
    "beef_bones": "Huesos de res para sopa", "pho_noodles": "Fideos de arroz (banh pho)",
    "vermicelli": "Fideos de arroz finos", "rice_paper": "Papel de arroz 22 cm", "shrimp": "Camarón 31/40, cocido",
    "thai_basil": "Albahaca tailandesa", "bean_sprouts": "Brotes de soya", "onions": "Cebolla amarilla",
    "carrots": "Zanahorias", "baguette": "Pan de banh mi", "fish_sauce": "Salsa de pescado",
    "pho_spices": "Kit de especias para pho",
    "Brisket Pho": "Pho de pecho de res", "Chicken Pho": "Pho de pollo",
    "Banh Mi (grilled pork)": "Banh mi (cerdo a la parrilla)", "Bun Cha": "Bun cha",
    "Spring Rolls (2)": "Rollos frescos (2)",
}

# ---------------------------------------------------------------- ingredients
INGREDIENTS = {}
for r in _rows("ingredients.csv"):
    key = r["ingredient_id"]
    INGREDIENTS[key] = {
        "name": {"en": r["name"], "es": _ES.get(key, r["name"])},
        "alias": r["invoice_alias"],
        "pack_desc": r["pack_desc"],
        "pack_size": float(r["pack_size"]),
        "pack_unit": r["base_unit"],
        "pack_price": float(r["last_pack_price"]),
        "yield_pct": float(r["yield_pct"]),
    }

# ---------------------------------------------------------------- menu + recipes
DISHES = {}
for r in _rows("menu.csv"):
    DISHES[_slug(r["dish"])] = {
        "name": {"en": r["dish"], "es": _ES.get(r["dish"], r["dish"])},
        "prices": {"in_store": float(r["instore_price"]), "doordash": float(r["doordash_price"])},
        "recipe": {},
    }
_by_name = {d["name"]["en"]: k for k, d in DISHES.items()}
for r in _rows("recipes.csv"):
    key = r["ingredient_id"]
    # Quantities are in the ingredient's own unit (lb, sheet, fl oz, ...).
    DISHES[_by_name[r["dish"]]]["recipe"][key] = (float(r["qty_per_serving"]), INGREDIENTS[key]["pack_unit"])

# ---------------------------------------------------------------- forecast (owner can edit in Settings)
_orders = _rows("doordash_orders.csv")
_last_day = max(date.fromisoformat(r["date"]) for r in _orders)
FORECAST_WINDOW_DAYS = 28
_window_start = _last_day - timedelta(days=FORECAST_WINDOW_DAYS - 1)
_forecast = {k: 0 for k in DISHES}
for r in _orders:
    if date.fromisoformat(r["date"]) >= _window_start:
        _forecast[_by_name[r["dish"]]] += int(r["orders"])

DAYS_PER_MONTH = 30.4
DEFAULT_SETTINGS = {
    "commission_pct": int(_settings["doordash_commission_pct"]),
    "packaging": float(_settings["packaging_per_delivery_order"]),
    "target_margin_pct": float(_settings["target_delivery_margin_pct"]),
    "owner_name": OWNER_NAME,
    # Forecast: average DoorDash orders per day over the last 28 days x 30.4 days.
    "monthly_orders": {k: round(n / FORECAST_WINDOW_DAYS * DAYS_PER_MONTH) for k, n in _forecast.items()},
}
# The order history behind each forecast (shown in the "monthly change" tooltip).
ORDER_HISTORY = {k: {"orders": n, "days": FORECAST_WINDOW_DAYS, "from": _window_start.isoformat(),
                     "to": _last_day.isoformat(), "days_per_month": DAYS_PER_MONTH,
                     "forecast": DEFAULT_SETTINGS["monthly_orders"][k]}
                 for k, n in _forecast.items()}

# ---------------------------------------------------------------- where today's prices came from
_last_delivery = max(r["date"] for r in _rows("price_history.csv"))
# Dated pack prices from past deliveries (newest last). The file has no pack size: it is the
# ingredient's standard pack from ingredients.csv, and the investigator says so.
PRICE_HISTORY = {k: [] for k in INGREDIENTS}
for r in sorted(_rows("price_history.csv"), key=lambda r: r["date"]):
    PRICE_HISTORY[r["ingredient_id"]].append({"date": r["date"], "pack_price": float(r["pack_price"])})
PREVIOUS_INVOICES = {k: ("Price history:", "last delivery", _last_delivery) for k in INGREDIENTS}

# ---------------------------------------------------------------- tonight's inbox
_fallback = json.loads((DEMO / "invoices_extracted_fallback.json").read_text())


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Known demo files by content hash -> their ground-truth reading. A file with the same bytes
# (like the forwarded copy of RM-20419) maps to the same reading, so it is never sent to the AI.
DEMO_READINGS = {}
for inv in _fallback:
    path = DEMO / inv["file"]
    if path.exists():
        DEMO_READINGS[_sha(path)] = inv

# Overnight order: the invoices listed in the fallback file first, then anything else in inbox/.
_listed = [Path(inv["file"]).name for inv in _fallback]
INBOX_FILES = _listed + sorted(p.name for p in INBOX.glob("*") if p.is_file() and p.name not in _listed)


# ---------------------------------------------------------------- reading a printed line (code, not AI)
_PACK_PATTERNS = [
    (re.compile(r"(\d+(?:\.\d+)?)\s*LB\b", re.I), "lb"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*KG\b", re.I), "kg"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*GAL\b", re.I), "gal"),
    (re.compile(r"(\d+(?:\.\d+)?)\s*FL\s*OZ\b", re.I), "fl_oz"),
    (re.compile(r"(\d+)\s*CT\b", re.I), "each"),
]


def parse_pack(description):
    """Pack size printed in the description ('30 LB CS', '1 GAL', '24 CT'), else (None, None).

    '1 CS' alone says how many cases, not what is inside one, so it is NOT a pack size.
    """
    for pattern, unit in _PACK_PATTERNS:
        m = pattern.search(description)
        if m:
            return float(m.group(1)), unit
    return None, None


def match_ingredient(description):
    """Ingredient whose invoice alias starts the printed description."""
    text = description.upper()
    for key, info in INGREDIENTS.items():
        if text.startswith(info["alias"].upper()):
            return key
    return None


def reading_to_invoice(inv):
    """Turn a ground-truth reading into the same shape the AI returns."""
    lines = []
    for line in inv["lines"]:
        key = match_ingredient(line["description"])
        size, unit = parse_pack(line["description"])
        if key and unit == "gal" and INGREDIENTS[key]["pack_unit"] == "fl_oz":
            size, unit = size * 128, "fl_oz"   # 1 gal = 128 fl oz, the unit the recipe uses
        if key and unit == "each" and INGREDIENTS[key]["pack_unit"] == "sheet":
            unit = "sheet"
        lines.append({"original": line["description"], "quantity": float(line["qty"]), "ingredient": key,
                      "pack_size": size, "pack_unit": unit, "pack_price": float(line["unit_price"]),
                      "unclear": [], "printed_amount": float(line["amount"])})
    return {"supplier": inv["supplier"], "invoice_no": inv["number"], "date": inv["date"],
            "total": float(inv["total"]), "lines": lines}
