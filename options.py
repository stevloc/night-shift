"""The decision snapshot for one dish: every fact, option and figure the owner (and the optional AI
review) sees. Plain Python, no AI. One source of financial truth: it reuses engine.dish_view() and
margins.breakdown(), and never takes totals from the browser.

    Options (stable ids)
        keep_current   today's DoorDash price
        suggested      the existing whole-dollar scenario that reaches the target (margins.proposed_price)
        custom         the owner's own price scenario (saved with "Change price")
        limit          the owner's highest acceptable price, when they give one

    Order-volume sensitivity (hypothetical, not a forecast)
        N0 = monthly orders (forecast from order history, or the owner's number in Settings)
        C0 = amount left per order at today's price, C1 = amount left per order under the option
        baseline total = N0 x C0         scenario total = N0 x (1 - d) x C1
        modeled monthly change = scenario total - baseline total
        break-even decline (only when 0 < C0 < C1):  d = 1 - C0 / C1

Exact values are kept; rounding is for display only (cents half-up, as in margins.py).
"""

import hashlib
import json
import re

import engine
from data import DISHES, INGREDIENTS
from margins import BELOW_TARGET, LOSES, breakdown, cents

DECLINES = (0.0, 0.05, 0.10)          # hypothetical order-volume cases shown to the owner
NOTE_MAX = 280


# ------------------------------------------------------------------ owner input (preferences, not facts)

def _money(value):
    if value in (None, ""):
        return None
    number = float(str(value).replace(",", ".").replace("$", "").strip())   # ValueError -> field error
    if not 0 <= number <= 100:
        raise ValueError
    return round(number, 2)


def owner_context(dish_id, note="", max_price=None, max_increase=None):
    """Validate what the owner typed. Returns (context, errors). The note is kept as data, never obeyed."""
    errors, context = {}, {}
    current = DISHES[dish_id]["prices"]["doordash"]
    try:
        context["max_price"] = _money(max_price)
        if context["max_price"] is not None and context["max_price"] < current:
            errors["max_price"] = "below_current"
    except ValueError:
        errors["max_price"] = "positive_number"
    try:
        context["max_increase"] = _money(max_increase)
    except ValueError:
        errors["max_increase"] = "positive_number"
    clean = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(note or "")).strip()
    if len(clean) > NOTE_MAX:
        errors["note"] = "too_long"
    context["note"] = clean[:NOTE_MAX]
    limits = [v for v in (context.get("max_price"),
                          None if context.get("max_increase") is None else round(current + context["max_increase"], 2))
              if v is not None]
    context["limit"] = min(limits) if limits else None   # the stricter limit wins
    return context, errors


# ------------------------------------------------------------------ sensitivity

def sensitivity(n0, c0, c1):
    """Hypothetical order-volume cases for one price option, always compared with today's baseline (N0 x C0).

    Exact values. When no break-even decline exists, `threshold.reason` says why (never a meaningless %).
    """
    if not n0 or n0 <= 0:
        return {"available": False, "reason": "no_order_volume"}
    baseline_total = n0 * c0
    cases = [{"decline": d, "orders": n0 * (1 - d), "scenario_total": n0 * (1 - d) * c1,
              "change": n0 * (1 - d) * c1 - baseline_total} for d in DECLINES]
    if c1 <= 0:
        threshold = {"decline": None, "reason": "option_not_positive"}     # the option itself loses money per order
    elif c0 <= 0:
        threshold = {"decline": None, "reason": "baseline_not_positive"}   # today loses money: nothing to erase
    elif abs(c1 - c0) < 1e-9:
        threshold = {"decline": None, "reason": "no_change"}
    elif c1 < c0:
        threshold = {"decline": None, "reason": "option_lower"}
    else:
        threshold = {"decline": 1 - c0 / c1, "reason": None}
    return {"available": True, "orders": n0, "baseline_total": baseline_total, "cases": cases, "threshold": threshold}


# ------------------------------------------------------------------ snapshot

def _option(option_id, price, food_exact, settings, now, orders, limit):
    after = breakdown(price, food_exact, settings)
    per_order_exact = after["left_exact"] - now["left_exact"]
    return {
        "id": option_id, "price": price,
        "after": after,                                   # cents for display + exact values
        "reaches_target": after["margin_exact"] >= settings["target_margin_pct"],
        "loses_money": after["left_exact"] < 0,
        "per_order_change": cents(per_order_exact), "per_order_change_exact": per_order_exact,
        "monthly_change": cents(per_order_exact * orders) if orders else None,
        "within_limit": None if limit is None else price <= limit + 1e-9,
        "sensitivity": None if option_id == "keep_current" else sensitivity(orders, now["left_exact"], after["left_exact"]),
    }


def _hash(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()[:20]


def scope():
    """Restaurant (Supabase) or visitor sandbox (local): reviews are cached inside this scope only."""
    return str(engine.STATE.get("restaurant_id") or engine.STATE.get("scope_id") or "default")


def snapshot(dish_id, context=None):
    """Everything the comparison and the AI review use, computed by code from the current state."""
    context = context or {"note": "", "max_price": None, "max_increase": None, "limit": None}
    view = engine.dish_view(dish_id)
    settings = engine.STATE["settings"]
    recipe = engine.STATE["recipes"][dish_id]
    current_price = view["now"]["price"]
    orders = view["monthly_orders"]
    limit = context.get("limit")
    held = bool(view["held_by"])

    costs = {k: engine.cost_record(k) for k in recipe}
    review_lines = [{"ingredient": l["ingredient"], "invoice_id": inv["id"], "line_id": l["id"],
                     "invoice_no": inv["invoice_no"], "original": l["original"], "reasons": l["reasons"]}
                    for inv in engine.STATE["invoices"] if engine._counted(inv) for l in inv["lines"]
                    if l["status"] == "needs_review" and l["ingredient"] in view["held_by"]]
    open_corrections = [pc for pc in engine._open_corrections()
                        if any(l.get("ingredient") in recipe
                               for l in engine.STATE["invoices"][pc["of_invoice"]]["lines"])]

    # Price options exist only when the dish is below target and every critical input is confirmed.
    options = [_option("keep_current", current_price, view["food_exact"], settings, view["now"], orders, limit)]
    p = view["proposal"]
    priced = not held and view["status"] in (LOSES, BELOW_TARGET) and p is not None
    if priced:
        options.append(_option("suggested", p["suggested"], view["food_exact"], settings, view["now"], orders, limit))
        if p["edited"]:
            options.append(_option("custom", p["price"], view["food_exact"], settings, view["now"], orders, limit))
        if limit is not None and limit > current_price and all(abs(o["price"] - limit) > 0.004 for o in options):
            options.append(_option("limit", limit, view["food_exact"], settings, view["now"], orders, limit))

    conflicts = []
    suggested = next((o for o in options if o["id"] == "suggested"), None)
    if limit is not None and suggested and suggested["price"] > limit + 1e-9:
        best = max((o for o in options if o["within_limit"]), key=lambda o: o["price"])
        conflicts.append({"kind": "limit_below_target_price", "limit": limit, "target_price": suggested["price"],
                          "best_within_limit": best["id"], "best_margin": best["after"]["margin_pct"],
                          "best_reaches_target": best["reaches_target"]})

    decision = view["decision"]
    actions = ["approve", "edit_price", "keep_current", "dismiss"] if priced and decision == "open" else []
    if any(abs(c["pct"]) > 0.0005 and c["current"]["source"].get("invoice_id") is not None for c in costs.values()):
        actions.append("review_supplier_change")
    if review_lines:
        actions.append("confirm_invoice_line")
    if open_corrections:
        actions.append("choose_invoice_version")
    actions += ["edit_recipe", "check_settings"]

    # The version covers every input that can change a figure or the allowed choices.
    facts = {
        "dish": dish_id, "decision": decision, "current_price": current_price,
        "settings": {k: settings[k] for k in ("commission_pct", "packaging", "target_margin_pct")},
        "orders": orders, "order_basis": view["order_basis"], "recipe": recipe,
        "costs": costs, "held_by": view["held_by"], "review_lines": review_lines,
        "open_corrections": [pc["id"] for pc in open_corrections],
        "options": [(o["id"], o["price"]) for o in options],
    }
    snap = {
        "scope": scope(), "dish": dish_id, "version": _hash(facts),
        "dish_status": "held" if held else view["status"], "decision": decision,
        "current_price": current_price, "now": view["now"],
        "settings": facts["settings"],
        "monthly_orders": orders, "order_basis": view["order_basis"],
        "monthly_available": bool(orders and orders > 0),
        "recipe": [{"ingredient": k, "amount": v[0], "unit": v[1], "yield_pct": costs[k]["current"]["yield_pct"]}
                   for k, v in recipe.items()],
        "costs": list(costs.values()),
        "holds": {"held_by": view["held_by"], "held_inputs": view["held_inputs"], "review_lines": review_lines,
                  "open_corrections": [{"id": pc["id"], "invoice_no": pc["invoice_no"], "file": pc["file"]}
                                       for pc in open_corrections]},
        "options": options,
        "conflicts": conflicts,
        "allowed_actions": actions,
        # Owner-supplied preferences: what the owner said, kept apart from measured facts.
        "owner": {"note": context.get("note", ""), "max_price": context.get("max_price"),
                  "max_increase": context.get("max_increase"), "limit": limit},
        "excluded": ["labor", "overhead"],
    }
    snap["evidence"] = evidence(snap)
    return snap


# ------------------------------------------------------------------ evidence registry

def evidence(snap):
    """Every fact the review may cite, by id, with its provenance and a link to the existing evidence."""
    dish = snap["dish"]
    items = []

    def add(eid, provenance, text, link, **extra):
        items.append({"id": eid, "provenance": provenance, "text": text, "link": link, **extra})

    def provenance_of(source):
        return {"invoice": "verified_invoice", "owner": "owner_confirmed"}.get(source["kind"], "previous_record")

    for c in snap["costs"]:
        k, name = c["ingredient"], INGREDIENTS[c["ingredient"]]["name"]["en"]
        cur, src = c["current"], c["current"]["source"]
        held = k in snap["holds"]["held_by"]
        add(f"cost:{k}", provenance_of(src),
            f"{name}: cost in use ${cur['pack_price']:.2f} per {cur['pack_size']:g} {cur['pack_unit']}"
            f" from {src['supplier']} {src['invoice_no']} ({src['date']})"
            + ("; last verified cost: a newer invoice line is waiting for the owner's confirmation" if held else ""),
            "#/invoices" if src.get("invoice_id") is not None else f"#/dishes/{dish}",
            ingredient=k, invoice_no=src["invoice_no"])
        if abs(c["pct"]) > 0.0005:
            cmp_, csrc = c["comparison"], c["comparison"]["source"]
            add(f"comparison:{k}", provenance_of(csrc),
                f"{name}: comparison price before tonight's run ${cmp_['pack_price']:.2f} per {cmp_['pack_size']:g}"
                f" {cmp_['pack_unit']} ({csrc['supplier']} {csrc['invoice_no']}, {csrc['date']});"
                f" unit cost change {c['pct'] * 100:+.1f}%",
                f"#/dishes/{dish}", ingredient=k, invoice_no=csrc["invoice_no"])
        for i, e in enumerate(c["earlier"]):
            add(f"earlier:{k}:{i}", "historical_invoice",
                f"{name}: earlier invoice {e['source']['invoice_no']} ({e['source']['date']}) at ${e['pack_price']:.2f}"
                f" per {e['pack_size']:g} {e['pack_unit']}; historical, not the current price",
                "#/invoices", ingredient=k, invoice_no=e["source"]["invoice_no"])
    for line in snap["holds"]["review_lines"]:
        name = INGREDIENTS[line["ingredient"]]["name"]["en"]
        add(f"hold:{line['ingredient']}", "needs_review",
            f"{name}: invoice {line['invoice_no']} line \"{line['original']}\" needs the owner's confirmation"
            f" ({', '.join(line['reasons'])}); the dish is held", "#/invoices",
            ingredient=line["ingredient"], invoice_no=line["invoice_no"])
    for pc in snap["holds"]["open_corrections"]:
        add(f"correction:{pc['id']}", "needs_review",
            f"Possible corrected invoice {pc['invoice_no']} ({pc['file']}) is waiting; not counted yet", "#/invoices",
            invoice_no=pc["invoice_no"])
    add("recipe", "owner_entered",
        "Recipe per serving: " + "; ".join(f"{r['amount']:g} {r['unit']} {INGREDIENTS[r['ingredient']]['name']['en']}"
                                           f" at {r['yield_pct']:g}% yield" for r in snap["recipe"]),
        f"#/dishes/{dish}")
    s = snap["settings"]
    add("settings:fees", "setting",
        f"DoorDash fee {s['commission_pct']:g}% of the price; packaging ${s['packaging']:.2f} per order", f"#/dishes/{dish}")
    add("settings:target", "setting", f"Owner's target: {s['target_margin_pct']:g}% of the price left after food,"
        " packaging and DoorDash fees", f"#/dishes/{dish}")
    add("price:current", "setting", f"Current DoorDash price ${snap['current_price']:.2f}", f"#/dishes/{dish}")
    basis = snap["order_basis"]
    if snap["monthly_available"]:
        if basis and not basis["edited"]:
            how, prov = (f"forecast from {basis['orders']} DoorDash orders in the {basis['days']} days"
                         f" {basis['from']} to {basis['to']}"), "forecast"
        else:
            how, prov = "set by the owner in Settings", "owner_entered"
        add("orders:monthly", prov, f"Monthly DoorDash orders assumed: {snap['monthly_orders']} ({how})", f"#/dishes/{dish}")
    for o in snap["options"]:
        a = o["after"]
        add(f"option:{o['id']}", "calculated",
            f"Option {o['id']}: price ${o['price']:.2f}, ${a['left']:.2f} left per order ({a['margin_pct']:g}%),"
            f" {'reaches' if o['reaches_target'] else 'below'} the target", f"#/dishes/{dish}")
    if snap["owner"]["note"]:
        add("owner:note", "owner_reported", "The owner's note (their own words; not verified)", "")
    if snap["owner"]["limit"] is not None:
        add("owner:limit", "owner_entered", f"Owner's highest acceptable price: ${snap['owner']['limit']:.2f}", "")
    for i, c in enumerate(snap["conflicts"]):
        add(f"conflict:{i}", "calculated",
            f"The owner's limit ${c['limit']:.2f} is below ${c['target_price']:.2f}, the suggested price that"
            " reaches the target", f"#/dishes/{dish}")
    return items
