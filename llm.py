"""The two AI jobs, via OpenRouter (OpenAI-compatible API).

1. extract_invoice: read a supplier invoice photo -> [{ingredient, unit_price}]
2. suggest_fixes:   propose 2-3 fixes for a dish losing money on DoorDash

Rule: the model never does margin math. It proposes *what* to change
(a new price, a combo partner, a portion size); margins.py computes the result.

Both functions fall back to safe hardcoded answers if the API fails,
so the demo never breaks. Each returns (result, used_fallback).
"""

import base64
import json
import os
import re

from openai import OpenAI

from data import FALLBACK_EXTRACTED_PRICES, INGREDIENTS, MENU
from margins import round_up_to_menu_price

MODEL = os.environ.get("NIGHT_SHIFT_MODEL", "anthropic/claude-sonnet-5.5")


def _client():
    return OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],  # KeyError -> fallback
        timeout=45,
        max_retries=1,
    )


def _parse_json(text):
    """Models sometimes wrap JSON in ```fences``` or prose; grab the JSON object."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0) if match else text)


def _ask(messages):
    response = _client().chat.completions.create(
        model=MODEL, messages=messages, temperature=0.2
    )
    return _parse_json(response.choices[0].message.content)


# ---------------------------------------------------------------- 1. invoices

def extract_invoice(image_bytes, mime_type="image/png"):
    """Read an invoice image. Returns ([{ingredient, unit_price}], used_fallback)."""
    known = "\n".join(f"- {key}: {info['name']} (per {info['unit']})"
                      for key, info in INGREDIENTS.items())
    prompt = (
        "You are reading a restaurant supplier invoice. For each line item, "
        "match it to one of these known ingredient keys and report its unit price "
        "exactly as printed. Skip lines that match no key. Do not calculate anything.\n\n"
        f"Known ingredients:\n{known}\n\n"
        'Reply with JSON only: {"items": [{"ingredient": "<key>", "unit_price": <number>}]}'
    )
    image_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode()}"

    try:
        result = _ask([{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]}])
        items = [
            {"ingredient": item["ingredient"], "unit_price": float(item["unit_price"])}
            for item in result["items"]
            if item.get("ingredient") in INGREDIENTS
        ]
        if not items:
            raise ValueError("no recognizable line items")
        return items, False
    except Exception as error:  # network, auth, bad JSON... never break the demo
        print(f"[night-shift] invoice extraction failed, using fallback: {error}")
        return FALLBACK_EXTRACTED_PRICES, True


# ---------------------------------------------------------------- 2. fixes

def suggest_fixes(flagged_item):
    """Propose fixes for one losing dish. Returns ([fix, ...], used_fallback).

    Each fix is one of:
      {"type": "raise_price",     "title", "rationale", "new_doordash_price"}
      {"type": "combo",           "title", "rationale", "add_item", "combo_doordash_price"}
      {"type": "smaller_portion", "title", "rationale", "ingredient", "portion_pct"}
    """
    other_items = {name: info["doordash_price"] for name, info in MENU.items()
                   if name != flagged_item["dish"]}
    prompt = (
        "You advise a small pho restaurant. This dish now loses money on DoorDash "
        "(25% commission + $0.50 packaging) because an ingredient got more expensive.\n\n"
        f"Dish data (computed by our system, trust these numbers):\n"
        f"{json.dumps(flagged_item, indent=2)}\n\n"
        f"Other menu items and their DoorDash prices: {json.dumps(other_items)}\n\n"
        "Propose exactly 3 fixes, one of each type:\n"
        '1. "raise_price": a new DoorDash price, ending in .49 or .99, at or above '
        "break_even_doordash_price.\n"
        '2. "combo": pair it with one other menu item (exact name from the list) at a '
        "single combo DoorDash price.\n"
        '3. "smaller_portion": shrink one recipe ingredient (use its key from the recipe) '
        "for delivery only, as portion_pct (e.g. 85 means 85% of normal).\n\n"
        "Do NOT calculate margins or profits; our system does that. "
        "Keep title under 8 words and rationale to one sentence a busy owner understands.\n\n"
        "Reply with JSON only, using exactly these field names:\n"
        '{"fixes": [\n'
        '  {"type": "raise_price", "title": "...", "rationale": "...", "new_doordash_price": 0.00},\n'
        '  {"type": "combo", "title": "...", "rationale": "...", "add_item": "<menu item name>", '
        '"combo_doordash_price": 0.00},\n'
        '  {"type": "smaller_portion", "title": "...", "rationale": "...", '
        '"ingredient": "<recipe key>", "portion_pct": 85}\n'
        "]}"
    )
    try:
        fixes = _ask([{"role": "user", "content": prompt}])["fixes"]
        fixes = [_normalize(f) for f in fixes
                 if f.get("type") in ("raise_price", "combo", "smaller_portion")]
        if len(fixes) < 2:
            raise ValueError("model returned too few usable fixes")
        return fixes[:3], False
    except Exception as error:
        print(f"[night-shift] fix suggestion failed, using fallback: {error}")
        return _fallback_fixes(flagged_item), True


# Models occasionally rename fields; map common variants to the names margins.py expects.
_ALIASES = {
    "new_price": "new_doordash_price",
    "with_item": "add_item", "item": "add_item", "paired_item": "add_item",
    "combo_price": "combo_doordash_price",
    "percent": "portion_pct", "portion_percent": "portion_pct",
}


def _normalize(fix):
    return {_ALIASES.get(key, key): value for key, value in fix.items()}


def _fallback_fixes(item):
    """Rule-based fixes so the 7 AM Brief always has something to approve."""
    recipe = item["recipe"]
    priciest = max(recipe, key=lambda key: recipe[key] * INGREDIENTS[key]["price"])
    new_price = round_up_to_menu_price(item["break_even_doordash_price"] + 0.75)
    coffee = MENU["Vietnamese Iced Coffee"]["doordash_price"]
    combo_price = round_up_to_menu_price(item["doordash_price"] + coffee - 0.50)
    return [
        {"type": "raise_price", "title": f"Raise DoorDash price to ${new_price:.2f}",
         "rationale": "Covers the supplier increase while staying close to the current price.",
         "new_doordash_price": new_price},
        {"type": "combo", "title": "Bundle with Vietnamese Iced Coffee",
         "rationale": "The coffee's high margin carries the bowl, and the combo feels like a deal.",
         "add_item": "Vietnamese Iced Coffee", "combo_doordash_price": combo_price},
        {"type": "smaller_portion",
         "title": f"Delivery portion: 85% {INGREDIENTS[priciest]['name'].lower()}",
         "rationale": "A slightly lighter delivery bowl cuts cost without changing the price.",
         "ingredient": priciest, "portion_pct": 85},
    ]
