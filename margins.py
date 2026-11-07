"""All the math. Plain Python, no AI. Every number the owner sees comes from here.

    Estimated amount left (per DoorDash order)
        = DoorDash price - ingredient cost - packaging - DoorDash commission
    Labor and overhead are NOT included (the UI says so).

    Margin = amount left / DoorDash price.
    Math runs on exact values; amounts are rounded to the cent (half up) only for display.
    So a displayed step can differ from the displayed total by 1 cent (the UI notes this).
    Raising the price by $1 adds $1 x (1 - commission) to the amount left,
    because the commission grows with the price ($0.75 at 25%).
"""

import math
from decimal import ROUND_HALF_UP, Decimal

from data import UNITS

LOSES = "loses_money"
BELOW_TARGET = "below_target"
COST_UP_OK = "cost_up_ok"
OK = "ok"


def cents(x):
    """Round money half-up to cents ($1.625 -> $1.63), like a cash register."""
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def to_base(amount, unit):
    """Convert an amount to its base unit (grams or each)."""
    base, factor = UNITS[unit]
    return amount * factor, base


def same_dimension(unit_a, unit_b):
    return unit_a in UNITS and unit_b in UNITS and UNITS[unit_a][0] == UNITS[unit_b][0]


def unit_costs(item):
    """Cost per purchase unit, and per usable purchase unit after yield.

    item: {"pack_size", "pack_unit", "pack_price", "yield_pct"}
    """
    per_unit = item["pack_price"] / item["pack_size"]
    usable = per_unit / (item["yield_pct"] / 100)
    return per_unit, usable


def serving_cost(item, amount, unit):
    """Cost of `amount unit` of an ingredient, after yield."""
    pack_base, _ = to_base(item["pack_size"], item["pack_unit"])
    need_base, _ = to_base(amount, unit)
    cost_per_base = item["pack_price"] / pack_base / (item["yield_pct"] / 100)
    return need_base * cost_per_base


def ingredient_lines(recipe, prices):
    """Per-ingredient cost breakdown for one serving (for the Dish Detail table)."""
    lines = []
    for key, (amount, unit) in recipe.items():
        item = prices[key]
        per_unit, usable = unit_costs(item)
        lines.append({
            "ingredient": key,
            "pack_size": item["pack_size"], "pack_unit": item["pack_unit"], "pack_price": item["pack_price"],
            "cost_per_unit": round(per_unit, 4), "yield_pct": item["yield_pct"],
            "usable_cost_per_unit": round(usable, 4),
            "amount": amount, "unit": unit,
            "cost_exact": serving_cost(item, amount, unit),
            "cost": cents(serving_cost(item, amount, unit)),
        })
    return lines


def food_cost(lines):
    """Exact ingredient cost per serving (sum of exact line costs)."""
    return sum(line["cost_exact"] for line in lines)


def breakdown(price, food, settings):
    """One DoorDash order step by step: exact math, cents for display, margin from the exact amount left."""
    commission = price * settings["commission_pct"] / 100
    left = price - food - settings["packaging"] - commission
    return {
        "price": cents(price),
        "commission": cents(commission),
        "packaging": cents(settings["packaging"]),
        "food_cost": cents(food),
        "left": cents(left),
        "left_exact": left,
        "margin_pct": round(left / price * 100, 1) if price else 0.0,
        "margin_exact": left / price * 100 if price else 0.0,
    }


def status(left, margin_pct, target_pct, cost_went_up):
    if left < 0:
        return LOSES
    if margin_pct < target_pct:
        return BELOW_TARGET
    if cost_went_up:
        return COST_UP_OK
    return OK


def proposed_price(current_price, food, settings):
    """Smallest whole-dollar DoorDash price increase that gets back to the target margin.

    Solve  (p*(1-c) - food - packaging) / p >= target   ->   p >= (food + packaging) / (1 - c - target)
    """
    c = settings["commission_pct"] / 100
    t = settings["target_margin_pct"] / 100
    if 1 - c - t <= 0:
        return None  # target is impossible at this commission
    needed = (food + settings["packaging"]) / (1 - c - t)
    # Whole-dollar steps keep menu endings (.95 stays .95). Check with the rounded breakdown too.
    steps = max(1, math.ceil(round(needed - current_price, 6)))
    price = round(current_price + steps, 2)
    while breakdown(price, food, settings)["margin_exact"] < settings["target_margin_pct"]:
        price = round(price + 1, 2)
    return price


def monthly(per_order, orders):
    """Monthly effect, estimated at the owner's current order volume."""
    return per_order * orders
