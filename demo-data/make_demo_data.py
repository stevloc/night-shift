"""Generate the fictional Night Shift demo data pack.

Everything here is invented: the restaurant, suppliers, prices and orders.
Run:  python3 make_demo_data.py   (writes files next to this script)
"""
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).parent
(OUT / "inbox").mkdir(exist_ok=True)

RESTAURANT = {
    "name": "Pho Nightingale (fictional)",
    "address": "100 Example St, Pittsburgh, PA",
}

# Owner settings: what the owner enters once during onboarding.
SETTINGS = {
    "doordash_commission_pct": 25,       # Plus plan; Basic 15, Premier 30
    "packaging_per_delivery_order": 0.50,
    "target_delivery_margin_pct": 38,    # owner's target for "left after food, packaging, fees"
    "currency": "USD",
    "note": "Margin = price - ingredient cost - packaging - DoorDash commission. Labor and overhead excluded.",
}

# Ingredients. pack_size is in base_unit; price is per pack (last known, before tonight's invoices).
# yield_pct = share of what you buy that ends up on the plate (trim, cooking loss).
INGREDIENTS = [
    # id, name, invoice aliases, pack_desc, pack_size, base_unit, last_pack_price, yield_pct
    ("brisket", "Beef brisket", "BEEF BRISKET CHOICE", "20 LB case", 20, "lb", 119.80, 70),
    ("chicken_thigh", "Chicken thigh, boneless", "CHKN THIGH BNLS", "40 LB case", 40, "lb", 95.60, 75),
    ("pork_shoulder", "Pork shoulder", "PORK SHOULDER BNLS", "30 LB case", 30, "lb", 89.70, 70),
    ("beef_bones", "Beef soup bones", "BEEF SOUP BONES", "40 LB case", 40, "lb", 48.00, 100),
    ("pho_noodles", "Rice noodles (banh pho)", "RICE STICK 3MM", "30 LB case", 30, "lb", 54.00, 100),
    ("vermicelli", "Rice vermicelli", "RICE VERMICELLI", "30 LB case", 30, "lb", 57.00, 100),
    ("rice_paper", "Rice paper 22cm", "RICE PAPER 22CM", "case of 20 packs x 50 sheets", 1000, "sheet", 76.00, 95),
    ("shrimp", "Shrimp 31/40, cooked", "SHRIMP 31/40 CKD", "2 LB bag", 2, "lb", 19.98, 90),
    ("thai_basil", "Thai basil", "THAI BASIL", "5 LB case", 5, "lb", 22.50, 80),
    ("bean_sprouts", "Bean sprouts", "BEAN SPROUTS", "10 LB case", 10, "lb", 12.00, 90),
    ("onions", "Yellow onions", "ONION YELLOW JBO", "50 LB sack", 50, "lb", 32.00, 90),
    ("carrots", "Carrots", "CARROTS JUMBO", "25 LB sack", 25, "lb", 21.00, 85),
    ("baguette", "Banh mi baguette", "BAGUETTE 8IN", "24 ct", 24, "each", 14.40, 100),
    ("fish_sauce", "Fish sauce", "FISH SAUCE", "1 gal (128 fl oz)", 128, "fl_oz", 14.00, 100),
    ("pho_spices", "Pho spice kit", "PHO SPICE KIT", "kit for 40 bowls", 40, "bowl", 18.00, 100),
]

MENU = [
    # dish, in-store price, DoorDash price
    ("Brisket Pho", 13.95, 15.99),
    ("Chicken Pho", 12.95, 14.99),
    ("Banh Mi (grilled pork)", 9.95, 11.49),
    ("Bun Cha", 13.50, 15.49),
    ("Spring Rolls (2)", 6.50, 7.99),
]

RECIPES = [
    # dish, ingredient_id, qty per serving (base unit)
    ("Brisket Pho", "brisket", 0.35), ("Brisket Pho", "beef_bones", 0.50),
    ("Brisket Pho", "pho_noodles", 0.30), ("Brisket Pho", "thai_basil", 0.04),
    ("Brisket Pho", "bean_sprouts", 0.15), ("Brisket Pho", "onions", 0.10),
    ("Brisket Pho", "fish_sauce", 0.50), ("Brisket Pho", "pho_spices", 1),
    ("Chicken Pho", "chicken_thigh", 0.30), ("Chicken Pho", "beef_bones", 0.30),
    ("Chicken Pho", "pho_noodles", 0.30), ("Chicken Pho", "thai_basil", 0.04),
    ("Chicken Pho", "bean_sprouts", 0.15), ("Chicken Pho", "onions", 0.10),
    ("Chicken Pho", "fish_sauce", 0.50), ("Chicken Pho", "pho_spices", 1),
    ("Banh Mi (grilled pork)", "baguette", 1), ("Banh Mi (grilled pork)", "pork_shoulder", 0.25),
    ("Banh Mi (grilled pork)", "carrots", 0.08), ("Banh Mi (grilled pork)", "fish_sauce", 0.25),
    ("Bun Cha", "pork_shoulder", 0.35), ("Bun Cha", "vermicelli", 0.25),
    ("Bun Cha", "carrots", 0.05), ("Bun Cha", "thai_basil", 0.03),
    ("Bun Cha", "fish_sauce", 1.0),
    ("Spring Rolls (2)", "rice_paper", 2), ("Spring Rolls (2)", "shrimp", 0.12),
    ("Spring Rolls (2)", "vermicelli", 0.06), ("Spring Rolls (2)", "thai_basil", 0.02),
]

# Tonight's invoices. Each line: (alias as printed, qty, unit printed, pack price printed)
INVOICE_DATE = "2026-11-06"
INVOICES = [
    {
        "file": "invoice_rivermark_meats_2026-11-06.png",
        "supplier": "Rivermark Meats (fictional)",
        "number": "RM-20419",
        "lines": [
            ("BEEF BRISKET CHOICE 20 LB CS", 2, "CS", 134.20),   # was 119.80 -> +12.0%
            ("CHKN THIGH BNLS 40 LB CS", 1, "CS", 95.60),
            ("PORK SHOULDER BNLS 30 LB CS", 1, "CS", 89.70),
            ("BEEF SOUP BONES 40 LB CS", 1, "CS", 48.00),
        ],
    },
    {
        "file": "invoice_greenleaf_produce_2026-11-06.png",
        "supplier": "Greenleaf Produce Supply (fictional)",
        "number": "GL-88302",
        "lines": [
            ("THAI BASIL 5 LB CS", 1, "CS", 22.50),
            ("BEAN SPROUTS 10 LB CS", 2, "CS", 12.60),           # +5%: small, no action
            ("ONION YELLOW JBO 50 LB SK", 1, "SK", 32.00),
            ("CARROTS JUMBO 25 LB SK", 1, "SK", 21.00),
        ],
    },
    {
        "file": "invoice_lotus_pantry_2026-11-06.png",
        "supplier": "Lotus Pantry Wholesale (fictional)",
        "number": "LP-5521",
        "lines": [
            ("RICE STICK 3MM 30 LB CS", 1, "CS", 54.00),
            ("RICE VERMICELLI 30 LB CS", 1, "CS", 57.00),
            ("RICE PAPER 22CM 1 CS", 1, "CS", 38.00),            # pack count missing -> Needs review
            ("FISH SAUCE 1 GAL", 2, "EA", 14.00),
            ("BAGUETTE 8IN 24 CT", 3, "CT", 14.40),
        ],
    },
]

# ---------- write tables ----------
with open(OUT / "settings.json", "w") as f:
    json.dump({"restaurant": RESTAURANT, **SETTINGS}, f, indent=2)

with open(OUT / "ingredients.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ingredient_id", "name", "invoice_alias", "pack_desc", "pack_size", "base_unit",
                "last_pack_price", "yield_pct"])
    w.writerows(INGREDIENTS)

with open(OUT / "menu.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["dish", "instore_price", "doordash_price"])
    w.writerows(MENU)

with open(OUT / "recipes.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["dish", "ingredient_id", "qty_per_serving"])
    w.writerows(RECIPES)

# Price history: 4 prior deliveries per ingredient at the last price (brisket drifts up slightly).
start = date(2026, 10, 9)
with open(OUT / "price_history.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "ingredient_id", "pack_price"])
    for i in range(4):
        d = (start + timedelta(days=7 * i)).isoformat()
        for ing in INGREDIENTS:
            w.writerow([d, ing[0], ing[6]])

# 90 days of DoorDash order history with a weekend bump (for the volume forecast).
random.seed(7)
base_daily = {"Brisket Pho": 6.5, "Chicken Pho": 5.0, "Banh Mi (grilled pork)": 4.0,
              "Bun Cha": 3.0, "Spring Rolls (2)": 5.5}
weekday_factor = [0.8, 0.8, 0.9, 1.0, 1.3, 1.4, 1.1]  # Mon..Sun
end = date(2026, 11, 6)
with open(OUT / "doordash_orders.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["date", "dish", "orders"])
    for k in range(90):
        d = end - timedelta(days=89 - k)
        for dish, b in base_daily.items():
            lam = b * weekday_factor[d.weekday()]
            n = max(0, round(random.gauss(lam, lam ** 0.5)))
            w.writerow([d.isoformat(), dish, n])

# ---------- invoice images ----------
def font(size, bold=False):
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for n in names:
        for p in ["/usr/share/fonts/truetype/dejavu/" + n, n]:
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()

def draw_invoice(inv):
    W, H = 1240, 1500
    img = Image.new("RGB", (W, H), (252, 251, 247))
    d = ImageDraw.Draw(img)
    d.text((70, 60), inv["supplier"], fill=(20, 24, 43), font=font(40, True))
    d.text((70, 115), "Wholesale food distribution  ·  SAMPLE / FICTIONAL", fill=(110, 110, 110), font=font(22))
    d.text((W - 420, 60), "INVOICE", fill=(196, 106, 18), font=font(44, True))
    d.text((W - 420, 120), f"No. {inv['number']}", fill=(40, 40, 40), font=font(24))
    d.text((W - 420, 155), f"Date: {INVOICE_DATE}", fill=(40, 40, 40), font=font(24))
    d.text((70, 210), "Bill to:", fill=(110, 110, 110), font=font(22))
    d.text((70, 240), RESTAURANT["name"], fill=(20, 24, 43), font=font(26, True))
    d.text((70, 275), RESTAURANT["address"], fill=(40, 40, 40), font=font(22))

    y = 360
    cols = [70, 720, 830, 1000]
    d.rectangle([60, y - 10, W - 60, y + 40], fill=(20, 24, 43))
    for x, h in zip(cols, ["Item", "Qty", "Unit price", "Amount"]):
        d.text((x, y), h, fill=(246, 243, 236), font=font(24, True))
    y += 70
    total = 0.0
    for desc, qty, unit, price in inv["lines"]:
        amt = round(qty * price, 2)
        total += amt
        d.text((cols[0], y), desc, fill=(30, 30, 30), font=font(24))
        d.text((cols[1], y), f"{qty} {unit}", fill=(30, 30, 30), font=font(24))
        d.text((cols[2], y), f"${price:,.2f}", fill=(30, 30, 30), font=font(24))
        d.text((cols[3], y), f"${amt:,.2f}", fill=(30, 30, 30), font=font(24))
        y += 50
        d.line([60, y - 8, W - 60, y - 8], fill=(225, 220, 208), width=1)
    y += 30
    d.text((cols[2], y), "TOTAL", fill=(20, 24, 43), font=font(28, True))
    d.text((cols[3], y), f"${total:,.2f}", fill=(20, 24, 43), font=font(28, True))
    d.text((70, H - 90), "Payment terms: Net 14. Thank you for your business.", fill=(110, 110, 110), font=font(22))
    img.save(OUT / "inbox" / inv["file"])
    return round(total, 2)

invoice_json = []
for inv in INVOICES:
    tot = draw_invoice(inv)
    invoice_json.append({
        "file": "inbox/" + inv["file"], "supplier": inv["supplier"], "number": inv["number"],
        "date": INVOICE_DATE, "total": tot,
        "lines": [{"description": a, "qty": q, "unit": u, "unit_price": p, "amount": round(q * p, 2)}
                  for a, q, u, p in inv["lines"]],
    })
# Ground-truth extraction: use as the demo fallback if the vision API fails.
with open(OUT / "invoices_extracted_fallback.json", "w") as f:
    json.dump(invoice_json, f, indent=2)

# ---------- compute expected results (the same math the app must do) ----------
ing = {i[0]: dict(zip(["id", "name", "alias", "pack_desc", "pack_size", "unit", "price", "yield"], i))
       for i in INGREDIENTS}
new_price = dict((i[0], i[6]) for i in INGREDIENTS)
new_price["brisket"] = 134.20
new_price["bean_sprouts"] = 12.60
needs_review = {"rice_paper"}  # "1 CS" with no pack count

def unit_cost(iid, prices):
    i = ing[iid]
    return prices[iid] / i["pack_size"] / (i["yield"] / 100)

def dish_cost(dish, prices):
    return sum(q * unit_cost(iid, prices) for d_, iid, q in RECIPES if d_ == dish)

c = SETTINGS["doordash_commission_pct"] / 100
pack = SETTINGS["packaging_per_delivery_order"]
target = SETTINGS["target_delivery_margin_pct"]

# monthly volume forecast: last 28 days average x 30.4
orders = {}
with open(OUT / "doordash_orders.csv") as f:
    rows = list(csv.DictReader(f))
last28 = {r["dish"]: 0 for r in rows}
cutoff = (end - timedelta(days=27)).isoformat()
for r in rows:
    if r["date"] >= cutoff:
        last28[r["dish"]] += int(r["orders"])

old_prices = {i[0]: i[6] for i in INGREDIENTS}
results = []
for dish, instore, dd in MENU:
    before = dish_cost(dish, old_prices)
    after = dish_cost(dish, new_price)
    left = dd - dd * c - pack - after
    pct = left / dd * 100
    uses = {iid for d_, iid, _ in RECIPES if d_ == dish}
    if uses & needs_review:
        status = "Needs review"
    elif left < 0:
        status = "Loses money after the costs shown"
    elif pct < target:
        status = "Below your target margin"
    elif after > before + 0.005:
        status = "Cost increased; no action needed"
    else:
        status = "OK"
    monthly = round(last28[dish] / 28 * 30.4)
    row = {"dish": dish, "doordash_price": dd, "cost_before": round(before, 2), "cost_after": round(after, 2),
           "left_per_order": round(left, 2), "margin_pct": round(pct, 1), "status": status,
           "forecast_monthly_orders": monthly}
    if status == "Below your target margin":
        nd = dd + 1.00
        nleft = nd - nd * c - pack - after
        row["proposal"] = {"new_doordash_price": round(nd, 2), "left_per_order": round(nleft, 2),
                           "margin_pct": round(nleft / nd * 100, 1),
                           "gain_per_order": round(nleft - left, 2),
                           "gain_per_month": round((nleft - left) * monthly, 2)}
    results.append(row)

with open(OUT / "expected_results.json", "w") as f:
    json.dump({"settings": SETTINGS, "results": results}, f, indent=2)

for r in results:
    print(r)
