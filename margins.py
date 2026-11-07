"""Margin math. Plain Python, no AI: every number the owner sees comes from here.

DoorDash margin = DoorDash price - 25% commission - $0.50 packaging - food cost
In-store margin = in-store price - food cost
"""

import math

import pandas as pd

from data import DOORDASH_COMMISSION, PACKAGING_COST, MENU


def dish_cost(recipe, prices):
    """Food cost of one serving: sum of (amount x unit price) over the recipe."""
    return sum(amount * prices[ingredient] for ingredient, amount in recipe.items())


def doordash_margin(doordash_price, food_cost):
    """What the restaurant keeps per DoorDash order."""
    commission = doordash_price * DOORDASH_COMMISSION
    return doordash_price - commission - PACKAGING_COST - food_cost


def break_even_doordash_price(food_cost):
    """Lowest DoorDash price where margin is $0 (solves doordash_margin = 0)."""
    return (food_cost + PACKAGING_COST) / (1 - DOORDASH_COMMISSION)


def compute_margins(prices, menu=MENU):
    """Returns (DataFrame of every dish, list of dishes losing money on DoorDash)."""
    rows = []
    for dish, info in menu.items():
        cost = dish_cost(info["recipe"], prices)
        rows.append({
            "Dish": dish,
            "Food cost": round(cost, 2),
            "In-store price": info["in_store_price"],
            "In-store margin": round(info["in_store_price"] - cost, 2),
            "DoorDash price": info["doordash_price"],
            "DoorDash margin": round(doordash_margin(info["doordash_price"], cost), 2),
        })
    df = pd.DataFrame(rows)

    flagged = []
    for row in df[df["DoorDash margin"] < 0].to_dict("records"):
        flagged.append({
            "dish": row["Dish"],
            "food_cost": row["Food cost"],
            "in_store_price": row["In-store price"],
            "in_store_margin": row["In-store margin"],
            "doordash_price": row["DoorDash price"],
            "doordash_margin": row["DoorDash margin"],
            "loss_per_order": -row["DoorDash margin"],
            "break_even_doordash_price": round(break_even_doordash_price(row["Food cost"]), 2),
            "recipe": menu[row["Dish"]]["recipe"],
        })
    return df, flagged


def evaluate_fix(fix, dish, prices, menu=MENU):
    """Compute the new DoorDash margin for an AI-proposed fix.

    The AI only proposes *what* to change (a price, a combo partner, a portion %).
    This function does the arithmetic. Returns the new margin in dollars, or
    None if the proposal can't be evaluated (bad input from the model).
    """
    info = menu[dish]
    cost = dish_cost(info["recipe"], prices)
    kind = fix.get("type")

    try:
        if kind == "raise_price":
            return doordash_margin(float(fix["new_doordash_price"]), cost)

        if kind == "combo":
            # One order, one packaging fee, two items' food cost.
            partner = menu[fix["add_item"]]
            combo_cost = cost + dish_cost(partner["recipe"], prices)
            return doordash_margin(float(fix["combo_doordash_price"]), combo_cost)

        if kind == "smaller_portion":
            # Scale one ingredient (usually the protein) for delivery orders only.
            ingredient = fix["ingredient"]
            pct = float(fix["portion_pct"]) / 100
            if ingredient not in info["recipe"] or not 0 < pct <= 1:
                return None
            smaller = dict(info["recipe"], **{ingredient: info["recipe"][ingredient] * pct})
            return doordash_margin(info["doordash_price"], dish_cost(smaller, prices))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def price_change(fix, dish, menu=MENU):
    """How much the customer-facing DoorDash price goes up (used by the trust ladder)."""
    if fix.get("type") == "raise_price":
        return float(fix["new_doordash_price"]) - menu[dish]["doordash_price"]
    return 0.0


def round_up_to_menu_price(amount):
    """Round up to the next .49 or .99, the way menus are priced."""
    whole = math.floor(amount)
    for candidate in (whole + 0.49, whole + 0.99, whole + 1.49):
        if candidate >= amount:
            return round(candidate, 2)
    return round(whole + 1.99, 2)
