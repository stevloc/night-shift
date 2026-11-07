"""Seed data for "Pho Real", a fictional pho restaurant.

Everything Night Shift knows about the restaurant lives here:
  - INGREDIENTS: what each ingredient costs per unit (before last night's invoice)
  - MENU: each dish's in-store price, DoorDash price, and recipe
  - DoorDash economics: 25% commission + $0.50 packaging per order

The planted problem: the supplier raised brisket 12% ($11.50 -> $12.88/lb).
That pushes Brisket Pho and Pho Dac Biet below zero on DoorDash,
while both stay profitable in-store.
"""

RESTAURANT_NAME = "Pho Real"

DOORDASH_COMMISSION = 0.25   # 25% of the DoorDash menu price
PACKAGING_COST = 0.50        # bowl, lid, bag, per delivery order

# key -> display name, unit, price per unit (USD)
INGREDIENTS = {
    "brisket":        {"name": "Beef brisket",       "unit": "lb",      "price": 11.50},
    "eye_of_round":   {"name": "Eye of round",       "unit": "lb",      "price": 10.50},
    "beef_tendon":    {"name": "Beef tendon",        "unit": "lb",      "price": 6.00},
    "beef_meatballs": {"name": "Beef meatballs",     "unit": "lb",      "price": 7.00},
    "beef_bones":     {"name": "Beef bones (broth)", "unit": "lb",      "price": 2.20},
    "chicken_thigh":  {"name": "Chicken thigh",      "unit": "lb",      "price": 3.80},
    "chicken_bones":  {"name": "Chicken bones",      "unit": "lb",      "price": 1.50},
    "rice_noodles":   {"name": "Rice noodles",       "unit": "lb",      "price": 2.40},
    "tofu":           {"name": "Tofu",               "unit": "lb",      "price": 2.50},
    "vegetables":     {"name": "Mixed vegetables",   "unit": "lb",      "price": 1.80},
    "herbs":          {"name": "Herb & garnish kit", "unit": "serving", "price": 0.30},
    "shrimp":         {"name": "Shrimp",             "unit": "lb",      "price": 9.00},
    "rice_paper":     {"name": "Rice paper",         "unit": "sheet",   "price": 0.08},
    "pork_shoulder":  {"name": "Pork shoulder",      "unit": "lb",      "price": 4.50},
    "baguette":       {"name": "Baguette",           "unit": "each",    "price": 0.60},
    "pickled_veg":    {"name": "Pickled daikon & carrot", "unit": "serving", "price": 0.20},
    "coffee":         {"name": "Phin coffee",        "unit": "serving", "price": 0.35},
    "condensed_milk": {"name": "Condensed milk",     "unit": "serving", "price": 0.25},
}

# dish -> prices + recipe (ingredient key -> amount in that ingredient's unit)
MENU = {
    "Brisket Pho": {
        "in_store_price": 13.95,
        "doordash_price": 15.45,
        "recipe": {"brisket": 0.75, "beef_bones": 0.50, "rice_noodles": 0.25, "herbs": 1},
    },
    "Pho Dac Biet (House Special)": {
        "in_store_price": 15.95,
        "doordash_price": 15.95,
        "recipe": {"brisket": 0.45, "eye_of_round": 0.25, "beef_tendon": 0.10,
                   "beef_meatballs": 0.10, "beef_bones": 0.50, "rice_noodles": 0.25, "herbs": 1},
    },
    "Rare Steak Pho": {
        "in_store_price": 13.95,
        "doordash_price": 15.45,
        "recipe": {"eye_of_round": 0.40, "beef_bones": 0.50, "rice_noodles": 0.25, "herbs": 1},
    },
    "Chicken Pho": {
        "in_store_price": 12.95,
        "doordash_price": 14.45,
        "recipe": {"chicken_thigh": 0.40, "chicken_bones": 0.50, "rice_noodles": 0.25, "herbs": 1},
    },
    "Veggie Pho": {
        "in_store_price": 12.50,
        "doordash_price": 13.95,
        "recipe": {"tofu": 0.30, "vegetables": 0.40, "rice_noodles": 0.25, "herbs": 1},
    },
    "Spring Rolls (2)": {
        "in_store_price": 6.95,
        "doordash_price": 7.95,
        "recipe": {"shrimp": 0.15, "rice_paper": 2, "rice_noodles": 0.05, "herbs": 1},
    },
    "Grilled Pork Banh Mi": {
        "in_store_price": 9.50,
        "doordash_price": 10.95,
        "recipe": {"baguette": 1, "pork_shoulder": 0.30, "pickled_veg": 1, "herbs": 1},
    },
    "Vietnamese Iced Coffee": {
        "in_store_price": 5.50,
        "doordash_price": 6.50,
        "recipe": {"coffee": 1, "condensed_milk": 1},
    },
}

# What last night's supplier invoice says (used to draw sample_invoice.png,
# and as the fallback "extraction" if the AI call fails). Brisket is up 12%.
SAMPLE_INVOICE = {
    "supplier": "Saigon Wholesale Meats & Produce",
    "invoice_no": "INV-20847",
    "date": "Nov 6, 2026",
    "lines": [
        # (ingredient key, description on invoice, qty, unit, unit price)
        ("brisket",       "Beef brisket, choice",      40, "lb", 12.88),
        ("eye_of_round",  "Beef eye of round",         25, "lb", 10.50),
        ("beef_bones",    "Beef marrow/knuckle bones", 60, "lb", 2.20),
        ("beef_tendon",   "Beef tendon",               10, "lb", 6.00),
        ("rice_noodles",  "Banh pho rice noodles",     50, "lb", 2.40),
        ("chicken_thigh", "Chicken thigh, boneless",   30, "lb", 3.80),
        ("herbs",         "Herb & garnish kits",      200, "ea", 0.30),
    ],
}

FALLBACK_EXTRACTED_PRICES = [
    {"ingredient": key, "unit_price": price}
    for key, _desc, _qty, _unit, price in SAMPLE_INVOICE["lines"]
]


def baseline_prices():
    """Ingredient prices before tonight's invoice, as {key: price}."""
    return {key: info["price"] for key, info in INGREDIENTS.items()}
