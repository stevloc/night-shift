"""Night Shift engine: the overnight inbox run, invoice checks, recalculation,
price scenarios, and the decision log.

Trust rules (shown in Settings):
  - Automatic:       read invoices, check totals and duplicates, recalculate, explain.
  - Owner reviews:   any invoice line Night Shift can't read or match with confidence.
  - Owner approves:  any price change. There is no DoorDash connection, so approving
                     only saves a decision; the owner updates DoorDash themselves.

Rule for the "While You Slept" report: every reassuring line carries its evidence
(the numbers that were checked).

Each visitor gets their own copy of the demo state (see Sessions below and api.py).
Code here reads and writes STATE as if it were one dict; STATE points at the current visitor's.
"""

import contextvars
import copy
import csv
import hashlib
import io
import math
import re
import secrets
import threading
import time
import uuid
from collections import OrderedDict, deque
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

import llm
from data import (COMMISSION_CHOICES, DEFAULT_SETTINGS, DEMO_READINGS, DISHES, INBOX, INBOX_FILES, INGREDIENTS,
                  OWNER_NAME, PREVIOUS_INVOICES, RESTAURANT_NAME, RESTAURANT_TZ, UNITS, reading_to_invoice)
from margins import (BELOW_TARGET, COST_UP_OK, LOSES, breakdown, cents, food_cost, ingredient_lines,
                     monthly, proposed_price, same_dimension, status, to_base)

ESSENTIAL = ("ingredient", "pack_size", "pack_unit", "pack_price")
BIG_CHANGE = 0.40      # a unit cost jump over 40% is held for review (likely a misread)
ALERT_CHANGE = 0.05    # price changes of 5%+ are called out on the brief
TZ = ZoneInfo(RESTAURANT_TZ)
NIGHT_START = datetime(2026, 11, 6, 23, 38, tzinfo=TZ)   # seeded clock for demo runs

# Where invoice files live. None = local mode (demo files on disk, uploads in memory);
# api.py sets this to Supabase Storage in production (put/get by path).
FILES = None


def _ingredient_prices():
    return {k: {f: v[f] for f in ("pack_size", "pack_unit", "pack_price", "yield_pct")}
            for k, v in INGREDIENTS.items()}


def _previous_sources():
    return {k: {"kind": "previous", "supplier": s, "invoice_no": n, "date": d}
            for k, (s, n, d) in PREVIOUS_INVOICES.items()}


def new_state(settings=None):
    prices = _ingredient_prices()
    return {
        "has_run": False,
        "prices": prices,                         # current verified pack prices
        "baseline": copy.deepcopy(prices),        # before tonight ("before" column)
        "sources": _previous_sources(),           # where each current price came from
        "recipes": {d: {k: list(v) for k, v in info["recipe"].items()} for d, info in DISHES.items()},
        "settings": copy.deepcopy(settings or DEFAULT_SETTINGS),
        "invoices": [],
        "images": {},                             # invoice id -> ("file", path) or ("bytes", data)
        "fingerprints": {},                       # supplier|number|total -> invoice id
        "price_history_new": [],                  # prices applied this request (appended to price_history)
        "activity": [],                           # the timestamped log
        "decisions": {},                          # dish -> {"state", "price", "reason"}
        "decision_log": [],                       # approved scenarios and dismissals (never deleted)
        "night_minutes": 0,
        "findings": {},
    }


# ------------------------------------------------------------------ per-visitor sessions

_current = contextvars.ContextVar("night_shift_state")
_default_state = new_state()   # used by scripts and tests that don't go through the API


class _SessionState:
    """Behaves like a dict, but always means the current visitor's state."""

    def _d(self):
        try:
            return _current.get()
        except LookupError:
            return _default_state

    def __getitem__(self, key):
        return self._d()[key]

    def __setitem__(self, key, value):
        self._d()[key] = value

    def __contains__(self, key):
        return key in self._d()

    def __getattr__(self, name):          # clear, update, setdefault, get, ...
        return getattr(self._d(), name)


STATE = _SessionState()


def use_session(state):
    """Point STATE at one visitor's state for the rest of this request. Returns a reset token."""
    return _current.set(state)


class Sessions:
    """In-memory visitor sandboxes: each starts as a fresh copy of the demo. Oldest/idle ones are dropped."""

    def __init__(self, max_sessions=200, idle_seconds=6 * 3600):
        self._items = OrderedDict()   # session id -> {"state", "seen", "lock"}
        self._lock = threading.Lock()
        self.max_sessions, self.idle_seconds = max_sessions, idle_seconds

    @staticmethod
    def new_id():
        return secrets.token_urlsafe(18)

    def get(self, session_id):
        now = time.monotonic()
        with self._lock:
            for sid in [k for k, v in self._items.items() if now - v["seen"] > self.idle_seconds]:
                del self._items[sid]
            item = self._items.get(session_id)
            if item is None:
                item = {"state": new_state(), "lock": None}
                self._items[session_id] = item
            item["seen"] = now
            self._items.move_to_end(session_id)
            while len(self._items) > self.max_sessions:
                self._items.popitem(last=False)
            return item

    def __len__(self):
        return len(self._items)


SESSIONS = Sessions()


class RateLimiter:
    """At most `limit` events per key in a sliding window (used for real AI extractions per IP)."""

    def __init__(self, limit=10, window_seconds=3600):
        self.limit, self.window = limit, window_seconds
        self._events = {}
        self._lock = threading.Lock()

    def take(self, key):
        """Use one slot. Returns (allowed, seconds until a slot frees up)."""
        now = time.monotonic()
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and now - events[0] > self.window:
                events.popleft()
            if len(events) >= self.limit:
                return False, self.window - (now - events[0])
            events.append(now)
            return True, 0


EXTRACTIONS = RateLimiter(limit=10, window_seconds=3600)


# ------------------------------------------------------------------ clock + log

def _now():
    """Current time in the restaurant's time zone (stored with its offset)."""
    return datetime.now(TZ).replace(microsecond=0).isoformat()


def _night_time(step=1):
    """Seeded overnight clock, so a demo run reads the same every time (11:38 PM onward)."""
    STATE["night_minutes"] += step
    return (NIGHT_START + timedelta(minutes=STATE["night_minutes"])).isoformat()


def _log(kind, at=None, **params):
    entry = {"id": len(STATE["activity"]), "at": at or _now(), "kind": kind, "params": params,
             "run_id": STATE.get("run_id"), "user_id": STATE.get("actor")}
    STATE["activity"].append(entry)
    return entry


def _logged(kind):
    """Params of every activity entry of one kind (duplicates and confirmations live in the log)."""
    return [{"at": a["at"], **a["params"]} for a in STATE["activity"] if a["kind"] == kind]


def _per_base_cost(pack):
    size, _ = to_base(pack["pack_size"], pack["pack_unit"])
    return pack["pack_price"] / size


def _norm(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def fingerprint(supplier, invoice_no):
    """Supplier + invoice number: two files with the same fingerprint are the same invoice."""
    return f"{_norm(supplier)}|{_norm(invoice_no)}"


# ------------------------------------------------------------------ invoice checks

def _review_reasons(line):
    """Why a line can't be trusted yet (empty list = verified)."""
    reasons = [f"missing_{field}" for field in ESSENTIAL if line.get(field) in (None, "")]
    reasons += [f"unclear_{field}" for field in line.get("unclear", [])
                if field in ESSENTIAL and f"missing_{field}" not in reasons]
    if reasons:
        return reasons
    key = line["ingredient"]
    if not same_dimension(line["pack_unit"], INGREDIENTS[key]["pack_unit"]):
        return ["unit_mismatch"]
    old = _per_base_cost(STATE["prices"][key])
    if abs(_per_base_cost(line) - old) / old > BIG_CHANGE:
        return ["big_change"]
    return []


def _apply_line(invoice, line, at, by_owner=False):
    """Use a verified line's price from now on; remember the old pack for 'vs last order'."""
    key = line["ingredient"]
    line["prev"] = {f: STATE["prices"][key][f] for f in ("pack_size", "pack_unit", "pack_price")}
    line["prev_source"] = dict(STATE["sources"][key])
    STATE["prices"][key].update(pack_size=line["pack_size"], pack_unit=line["pack_unit"], pack_price=line["pack_price"])
    STATE["sources"][key] = {"kind": "owner" if by_owner else "invoice", "supplier": invoice["supplier"],
                             "invoice_no": invoice["invoice_no"], "date": invoice["date"],
                             "invoice_id": invoice["id"], "line_id": line["id"], "original": line["original"]}
    line["applied"] = True
    STATE["price_history_new"].append({
        "ingredient_key": key, "observed_on": (invoice["read_at"] or _now())[:10], "pack_price": line["pack_price"],
        "pack_size": line["pack_size"], "pack_unit": line["pack_unit"], "source": STATE["sources"][key]})
    old, new = _per_base_cost(line["prev"]), _per_base_cost(line)
    if abs(new / old - 1) > 0.0005:
        _log("price_change", at=at, ingredient=key, pct=round(new / old - 1, 4),
             old=line["prev"]["pack_price"], new=line["pack_price"], invoice_no=invoice["invoice_no"])


def process_invoice(image_bytes, mime_type, filename, at=None, client_ip=None):
    """Read one invoice file: dedupe, check totals and packs, apply verified prices, recalculate.

    Demo files (matched by content hash) use demo-data/invoices_extracted_fallback.json: no AI call.
    Anything else goes to the AI, at most 10 new readings per IP per hour.
    """
    clock = (lambda: _night_time(1)) if at == "night" else _now
    demo = DEMO_READINGS.get(hashlib.sha256(image_bytes).hexdigest())
    if demo:
        read, from_demo = reading_to_invoice(demo), True
    else:
        if not llm.is_cached(image_bytes):
            if not llm.CONFIG.openrouter_api_key:
                return {"error": "ai_not_configured"}
            allowed, wait = EXTRACTIONS.take(client_ip or "unknown")
            if not allowed:
                return {"error": "rate_limited", "retry_minutes": max(1, math.ceil(wait / 60))}
        read, _failed = llm.extract_invoice(image_bytes, mime_type)
        from_demo = False
        if not read:
            return {"error": "could_not_read"}

    fp = fingerprint(read["supplier"], read["invoice_no"])
    if read["invoice_no"] and fp in STATE["fingerprints"]:
        original = STATE["invoices"][STATE["fingerprints"][fp]]
        _log("duplicate_skipped", at=clock(), file=filename, supplier=read["supplier"], invoice_no=read["invoice_no"],
             total=read["total"], of_file=original["file"], of_at=original["read_at"])
        return {"duplicate_of": read["invoice_no"]}

    invoice = {
        "id": len(STATE["invoices"]), "file": filename, "read_at": clock(),
        "supplier": read["supplier"], "invoice_no": read["invoice_no"], "date": read["date"],
        "total": read["total"], "used_fallback": from_demo, "fingerprint": fp if read["invoice_no"] else None,
        "mime": mime_type,
        "rows": _detect_rows(image_bytes, len(read["lines"])) if mime_type.startswith("image/") else None,
        "lines": [],
    }
    STATE["invoices"].append(invoice)
    if FILES is not None:   # production: every file goes to the private "invoices" bucket
        ext = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "application/pdf": ".pdf"}.get(mime_type, "")
        path = f"{STATE['restaurant_id']}/{hashlib.sha256(image_bytes).hexdigest()}{ext}"
        FILES.put(path, image_bytes, mime_type)
        STATE["images"][invoice["id"]] = ("storage", path)
    elif demo and (INBOX / filename).exists():   # local mode: demo images are on disk already
        STATE["images"][invoice["id"]] = ("file", str(INBOX / filename))
    else:
        STATE["images"][invoice["id"]] = ("bytes", image_bytes)
    if read["invoice_no"]:
        STATE["fingerprints"][fp] = invoice["id"]

    for i, raw in enumerate(read["lines"]):
        line = {"id": i, **{k: raw.get(k) for k in ("original", "quantity", *ESSENTIAL)},
                "unclear": raw.get("unclear", []), "applied": False, "corrected": False}
        line["reasons"] = _review_reasons(line)
        line["status"] = "needs_review" if line["reasons"] else "verified"
        invoice["lines"].append(line)

    priced = [l for l in invoice["lines"] if l["quantity"] and l["pack_price"]]
    invoice["lines_sum"] = cents(sum(l["quantity"] * l["pack_price"] for l in priced))
    invoice["totals_match"] = (invoice["total"] is not None and len(priced) == len(invoice["lines"])
                               and abs(invoice["lines_sum"] - invoice["total"]) < 0.005)

    review = [l for l in invoice["lines"] if l["status"] == "needs_review"]
    _log("invoice_read", at=invoice["read_at"], supplier=invoice["supplier"], invoice_no=invoice["invoice_no"],
         lines=len(invoice["lines"]), review=len(review))
    for line in invoice["lines"]:
        if line["status"] == "verified":
            _apply_line(invoice, line, at=invoice["read_at"])
    _log("recalculated", at=clock(), dishes=len(DISHES))
    _log_dish_findings(clock)
    return {"invoice_id": invoice["id"], "review": len(review), "used_fallback": from_demo}


def run_night_shift(seeded_clock=True):
    """One night: read every file in demo-data/inbox/ (already-counted invoices are skipped as
    duplicates), recalculate, and log it all under one run id.

    seeded_clock=True (the demo button) stamps the log 11:38 PM...6:55 AM so every demo reads the same;
    the scheduled nightly run uses real time.
    """
    STATE["run_id"] = str(uuid.uuid4())
    STATE["night_minutes"] = 0
    STATE["baseline"] = copy.deepcopy(STATE["prices"])   # "before" = prices before tonight
    STATE["has_run"] = True
    clock = "night" if seeded_clock else None
    _log("shift_start", at=_night_time(0) if seeded_clock else None, files=len(INBOX_FILES))
    results = []
    for filename in INBOX_FILES:   # the three invoices, then the forwarded copy
        path = INBOX / filename
        if path.exists():
            results.append({"file": filename, **process_invoice(path.read_bytes(), "image/png", filename, at=clock)})
    _log("brief_ready", at=datetime(2026, 11, 7, 6, 55, tzinfo=TZ).isoformat() if seeded_clock else None)
    STATE["run_id"] = None
    return results


def upload_invoice(image_bytes, mime_type, filename, client_ip=None):
    return process_invoice(image_bytes, mime_type, filename or "upload", client_ip=client_ip)


def correct_line(invoice_id, line_id, fields):
    """Owner fixes or confirms a line. Pack contents can be given as packs x items per pack."""
    try:
        invoice = STATE["invoices"][invoice_id]
        line = invoice["lines"][line_id]
    except (IndexError, KeyError, TypeError):
        return {"error": "not_found"}

    def number(name, integer=False):
        raw = str(fields.get(name) if fields.get(name) is not None else "").replace(",", ".").replace("$", "").strip()
        value = float(raw)
        if not 0 < value <= 100000 or (integer and value != int(value)):
            raise ValueError
        return value

    errors, clean = {}, {}
    key = fields.get("ingredient")
    if key not in INGREDIENTS:
        errors["ingredient"] = "required"
    packs = per_pack = None
    if fields.get("packs") not in (None, "") or fields.get("per_pack") not in (None, ""):
        # Pack contents entered as "packs x sheets": code multiplies (20 x 25 = 500).
        try:
            packs = number("packs", integer=True)
        except ValueError:
            errors["packs"] = "whole_number"
        try:
            per_pack = number("per_pack")
        except ValueError:
            errors["per_pack"] = "positive_number"
        if packs and per_pack:
            clean["pack_size"] = round(packs * per_pack, 4)
    else:
        try:
            clean["pack_size"] = round(number("pack_size"), 4)
        except ValueError:
            errors["pack_size"] = "positive_number"
    try:
        clean["pack_price"] = round(number("pack_price"), 2)
    except ValueError:
        errors["pack_price"] = "positive_number"
    unit = fields.get("pack_unit")
    if unit not in UNITS:
        errors["pack_unit"] = "required"
    elif key in INGREDIENTS and not same_dimension(unit, INGREDIENTS[key]["pack_unit"]):
        errors["pack_unit"] = "wrong_kind"
    if errors:
        return {"error": "invalid", "fields": errors}

    at = _now()
    if line["applied"]:  # undo the old effect before applying the corrected one
        STATE["prices"][line["ingredient"]].update(line["prev"])
        STATE["sources"][line["ingredient"]] = line["prev_source"]
    line.update(ingredient=key, pack_unit=unit, unclear=[], reasons=[], status="verified", corrected=True, **clean)
    _apply_line(invoice, line, at=at, by_owner=True)
    _log("owner_confirmed", at=at, ingredient=key, pack_size=clean["pack_size"], pack_unit=unit,
         packs=packs, per_pack=per_pack, pack_price=clean["pack_price"],
         per_unit=round(clean["pack_price"] / clean["pack_size"], 4),
         invoice_no=invoice["invoice_no"], original=line["original"])
    _log("recalculated", at=at, dishes=len(DISHES))
    _log_dish_findings(_now)
    return {}


def _detect_rows(image_bytes, n_lines):
    """Find the printed line rows in a table-style invoice: a dark header bar, then rows split by
    thin light separator lines. Returns [(y0, y1), ...] or None if the layout isn't recognised."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception:
        return None
    w, h = img.size
    px = img.load()
    xs = range(int(w * 0.1), int(w * 0.9), 3)

    def share(y, test):
        return sum(1 for x in xs if test(px[x, y])) / len(xs)

    header_end = None
    run = 0
    for y in range(h):
        run = run + 1 if share(y, lambda v: v < 90) > 0.6 else 0
        if run >= 20 and share(y + 1, lambda v: v < 90) <= 0.6:
            header_end = y + 1
            break
    if header_end is None:
        return None
    separators, y = [], header_end + 8
    while y < h and len(separators) < n_lines:
        if share(y, lambda v: v < 240) > 0.85 and share(y, lambda v: v < 120) < 0.2:
            separators.append(y)
            y += 10
        y += 1
    if len(separators) < n_lines:
        return None
    rows, top = [], header_end + 10
    for sep in separators:
        rows.append((top, sep))
        top = sep + 1
    return {"header": (header_end - 50, header_end), "rows": rows, "width": w}


def _image_bytes(invoice_id):
    kind, value = STATE["images"][invoice_id]
    if kind == "storage":
        return FILES.get(value)
    if kind == "file":
        with open(value, "rb") as f:
            return f.read()
    return value


def line_image(invoice_id, line_id):
    """PNG crop of one printed line (with column headers), highlighted, or None if unknown."""
    try:
        invoice = STATE["invoices"][invoice_id]
        y0, y1 = invoice["rows"]["rows"][line_id]
    except (IndexError, KeyError, TypeError):
        return None
    layout = invoice["rows"]
    img = Image.open(io.BytesIO(_image_bytes(invoice_id))).convert("RGB")
    head_top, head_bottom = layout["header"]
    # Two stacked pieces (description | qty, price, amount) so the crop stays readable on a phone.
    split = int(layout["width"] * 0.56)
    pieces = []
    for left, right in ((int(layout["width"] * 0.04), split), (split - 10, int(layout["width"] * 0.96))):
        head = img.crop((left, max(0, head_top), right, head_bottom))
        row = img.crop((left, y0, right, y1)).copy()
        ImageDraw.Draw(row, "RGBA").rectangle((0, 1, row.width - 1, row.height - 2),
                                              fill=(242, 165, 65, 70), outline=(214, 128, 20), width=4)
        piece = Image.new("RGB", (right - left, head.height + row.height), "white")
        piece.paste(head, (0, 0))
        piece.paste(row, (0, head.height))
        pieces.append(piece)
    gap = 10
    out_img = Image.new("RGB", (max(p.width for p in pieces), sum(p.height for p in pieces) + gap), (236, 236, 236))
    out_img.paste(pieces[0], (0, 0))
    out_img.paste(pieces[1], (0, pieces[0].height + gap))
    out = io.BytesIO()
    out_img.save(out, format="PNG")
    return out.getvalue()


def invoice_image(invoice_id):
    """(bytes, media type) of the original invoice, or None."""
    try:
        return _image_bytes(invoice_id), STATE["invoices"][invoice_id]["mime"]
    except (IndexError, KeyError, TypeError):
        return None


def _held_by(dish_id):
    """Ingredients of this dish that have an invoice line waiting for review."""
    recipe = STATE["recipes"][dish_id]
    return sorted({l["ingredient"] for inv in STATE["invoices"] for l in inv["lines"]
                   if l["status"] == "needs_review" and l["ingredient"] in recipe})


def _log_dish_findings(clock):
    """Log a dish only when its finding changes (held / below target / loses money)."""
    seen = STATE["findings"]
    for dish_id in DISHES:
        d = dish_view(dish_id)
        finding = "held" if d["held_by"] else d["status"] if d["status"] in (BELOW_TARGET, LOSES) else None
        if finding and seen.get(dish_id) != finding:
            if finding == "held":
                _log("held", at=clock(), dish=dish_id, ingredients=d["held_by"])
            else:
                _log(finding, at=clock(), dish=dish_id, margin=d["now"]["margin_pct"])
        if not finding and seen.get(dish_id) == "held":
            _log("hold_cleared", at=clock(), dish=dish_id)
        seen[dish_id] = finding


# ------------------------------------------------------------------ dish math

def _recipe_tuples(recipe):
    return {k: (v[0], v[1]) for k, v in recipe.items()}


def dish_view(dish_id, proposal_override=None, recipe_override=None):
    """Everything about one dish: cost lines, before / now / scenario, status, monthly effect."""
    dish = DISHES[dish_id]
    settings = STATE["settings"]
    price = dish["prices"]["doordash"]
    recipe = _recipe_tuples(recipe_override or STATE["recipes"][dish_id])
    lines_now = ingredient_lines(recipe, STATE["prices"])
    lines_before = ingredient_lines(recipe, STATE["baseline"])
    food_now, food_before = food_cost(lines_now), food_cost(lines_before)
    now = breakdown(price, food_now, settings)
    before = breakdown(price, food_before, settings)
    held_by = _held_by(dish_id)
    orders = settings["monthly_orders"][dish_id]
    dish_status = status(now["left_exact"], now["margin_exact"], settings["target_margin_pct"],
                         food_now > food_before + 0.005)

    for line, old in zip(lines_now, lines_before):
        line["cost_before"] = old["cost"]
        line["pack_before"] = {f: old[f] for f in ("pack_size", "pack_unit", "pack_price")}
        line["source"] = STATE["sources"][line["ingredient"]]
        line["recipe_amount"] = DISHES[dish_id]["recipe"][line["ingredient"]][0]  # original recipe card

    decision = STATE["decisions"].get(dish_id, {"state": "open", "price": None, "reason": None})
    scenario = None
    if dish_status in (LOSES, BELOW_TARGET) and not held_by:
        suggested = proposed_price(price, food_now, settings)
        chosen = proposal_override if proposal_override is not None else (decision["price"] or suggested)
        if chosen is not None:
            after = breakdown(chosen, food_now, settings)
            per_order_exact = after["left_exact"] - now["left_exact"]
            per_order = cents(per_order_exact)
            scenario = {
                "price": chosen, "suggested": suggested, "edited": chosen != suggested,
                "after": after, "per_order_change": per_order,
                "monthly_change": cents(monthly(per_order_exact, orders)),
                "reaches_target": after["margin_exact"] >= settings["target_margin_pct"],
                "keep_per_dollar": round(1 - settings["commission_pct"] / 100, 2),
            }

    cost_change_exact = now["left_exact"] - before["left_exact"]
    cost_change = cents(cost_change_exact)
    return {
        "id": dish_id,
        "name": dish["name"],
        "prices": dish["prices"],
        "recipe_lines": lines_now,
        "recipe_edited": STATE["recipes"][dish_id] != {k: list(v) for k, v in dish["recipe"].items()},
        "before": before,
        "now": now,
        "in_store": {"price": dish["prices"]["in_store"], "food_cost": cents(food_now),
                     "left": cents(dish["prices"]["in_store"] - food_now)},
        "status": dish_status,
        "held_by": held_by,
        "monthly_orders": orders,
        "cost_change_per_order": cost_change,
        "cost_change_monthly": cents(monthly(cost_change_exact, orders)),
        "proposal": scenario,
        "decision": decision["state"],
        "dismiss_reason": decision.get("reason"),
        "approval": next((a for a in reversed(STATE["decision_log"])
                          if a["dish"] == dish_id and a["kind"] == "price_scenario" and not a["undone"]), None),
    }


# ------------------------------------------------------------------ recipe edits (Dish Detail)

def _valid_recipe(dish_id, amounts):
    errors, recipe = {}, copy.deepcopy(STATE["recipes"][dish_id])
    for key, value in (amounts or {}).items():
        if key not in recipe:
            continue
        try:
            number = float(str(value).replace(",", "."))
            if not 0 < number <= 1000:
                raise ValueError
            recipe[key][0] = round(number, 3)
        except ValueError:
            errors[key] = "positive_number"
    return recipe, errors


def preview_recipe(dish_id, amounts):
    recipe, errors = _valid_recipe(dish_id, amounts)
    if errors:
        return {"error": "invalid", "fields": errors}
    return {"dish": dish_view(dish_id, recipe_override=recipe)}


def set_recipe(dish_id, amounts):
    recipe, errors = _valid_recipe(dish_id, amounts)
    if errors:
        return {"error": "invalid", "fields": errors}
    changes = [{"ingredient": k, "from": STATE["recipes"][dish_id][k][0], "to": v[0], "unit": v[1]}
               for k, v in recipe.items() if v[0] != STATE["recipes"][dish_id][k][0]]
    STATE["recipes"][dish_id] = recipe
    for c in changes:
        _log("recipe_changed", dish=dish_id, **c)
    _log_dish_findings(_now)
    return {}


# ------------------------------------------------------------------ decisions

def _decision(dish_id):
    return STATE["decisions"].setdefault(dish_id, {"state": "open", "price": None, "reason": None})


def _valid_price(dish_id, value):
    try:
        price = round(float(str(value).replace(",", ".").replace("$", "")), 2)
    except ValueError:
        return None, {"error": "not_a_number"}
    current = DISHES[dish_id]["prices"]["doordash"]
    if not current < price <= 100:
        return None, {"error": "must_be_higher", "min": current, "max": 100}
    return price, None


def preview(dish_id, price):
    price, error = _valid_price(dish_id, price)
    if error:
        return error
    view = dish_view(dish_id, proposal_override=price)
    return {"proposal": view["proposal"]} if view["proposal"] else {"error": "no_proposal"}


def set_proposal(dish_id, value):
    price, error = _valid_price(dish_id, value)
    if error:
        return error
    _decision(dish_id)["price"] = price
    _log("edited", dish=dish_id, price=price)
    return {}


def approve(dish_id):
    """Save the price scenario to the decision log. Nothing is sent to DoorDash."""
    view = dish_view(dish_id)
    if not view["proposal"]:
        return {"error": "no_proposal"}
    p = view["proposal"]
    record = {
        "id": len(STATE["decision_log"]), "at": _now(), "dish": dish_id, "kind": "price_scenario",
        "from_price": view["now"]["price"], "to_price": p["price"],
        "left_before": view["now"]["left"], "left_after": p["after"]["left"],
        "per_order_change": p["per_order_change"], "monthly_change": p["monthly_change"],
        "monthly_orders": view["monthly_orders"], "commission_pct": STATE["settings"]["commission_pct"],
        "reason": None, "user_id": STATE.get("actor"), "published": False, "undone": False,
    }
    STATE["decision_log"].append(record)
    _decision(dish_id)["state"] = "approved"
    _log("approved", dish=dish_id, to_price=p["price"])
    return {"record": record}


def undo(dish_id):
    record = next((a for a in reversed(STATE["decision_log"])
                   if a["dish"] == dish_id and a["kind"] == "price_scenario" and not a["undone"]), None)
    if not record:
        return {"error": "not_found"}
    record.update(undone=True, undone_at=_now())
    _decision(dish_id)["state"] = "open"
    _log("undone", dish=dish_id)
    return {}


DISMISS_REASONS = ("absorb_cost", "temporary_price", "change_recipe", "other")


def dismiss(dish_id, reason, note=""):
    note = (note or "").strip()[:200]
    if reason not in DISMISS_REASONS:
        return {"error": "invalid", "fields": {"reason": "choose_one"}}
    if reason == "other" and not note:
        return {"error": "invalid", "fields": {"note": "required_text"}}
    STATE["decision_log"].append({"id": len(STATE["decision_log"]), "at": _now(), "dish": dish_id, "kind": "dismissed",
                                  "reason": reason, "note": note, "user_id": STATE.get("actor"),
                                  "published": False, "undone": False})
    d = _decision(dish_id)
    d.update(state="dismissed", reason={"code": reason, "note": note})
    _log("dismissed", dish=dish_id, reason=reason, note=note)
    return {}


def restore(dish_id):
    record = next((a for a in reversed(STATE["decision_log"])
                   if a["dish"] == dish_id and a["kind"] == "dismissed" and not a["undone"]), None)
    if record:
        record.update(undone=True, undone_at=_now())
    _decision(dish_id).update(state="open", reason=None)
    _log("restored", dish=dish_id)
    return {}


# ------------------------------------------------------------------ settings

def update_settings(values):
    errors, clean = {}, {}
    try:
        commission = int(values.get("commission_pct"))
        if commission not in COMMISSION_CHOICES:
            raise ValueError
        clean["commission_pct"] = commission
    except (TypeError, ValueError):
        errors["commission_pct"] = "choose_one"
    for name, low, high in (("packaging", 0, 10), ("target_margin_pct", 0, 60)):
        try:
            value = float(str(values.get(name)).replace(",", "."))
            if not low <= value <= high:
                raise ValueError
            clean[name] = round(value, 2)
        except (TypeError, ValueError):
            errors[name] = f"range:{low}:{high}"
    orders = {}
    for dish_id in DISHES:
        try:
            value = int(float(str(values.get("monthly_orders", {}).get(dish_id))))
            if not 0 <= value <= 100000:
                raise ValueError
            orders[dish_id] = value
        except (TypeError, ValueError):
            errors[f"orders_{dish_id}"] = "range:0:100000"
    if not errors and clean["commission_pct"] + clean["target_margin_pct"] >= 100:
        errors["target_margin_pct"] = "impossible"
    if errors:
        return {"error": "invalid", "fields": errors}
    STATE["settings"] = {**clean, "monthly_orders": orders}
    _log("settings_changed", commission_pct=clean["commission_pct"], target_margin_pct=clean["target_margin_pct"])
    return {}


def bookkeeper_csv():
    """Tonight's counted invoices, one row per line, for the bookkeeper.

    Skipped duplicates are not included (they were never counted). Lines still waiting for the
    owner are kept, with status NEEDS REVIEW, so nothing on a real invoice goes missing.
    """
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["supplier", "invoice_number", "invoice_date", "line", "description", "quantity",
                     "unit_price", "line_total", "pack_size", "pack_unit", "ingredient",
                     "line_status", "invoice_total_printed", "invoice_lines_sum", "totals_match"])
    for inv in STATE["invoices"]:
        for line in inv["lines"]:
            qty, price = line["quantity"], line["pack_price"]
            reasons = [r.replace("_", " ").replace("missing ", "missing: ")
                       .replace("unclear ", "unclear: ") for r in line["reasons"]]
            status = ("NEEDS REVIEW (" + "; ".join(reasons) + ")" if line["status"] == "needs_review"
                      else "verified (owner corrected)" if line["corrected"] else "verified")
            writer.writerow([
                inv["supplier"], inv["invoice_no"], inv["date"], line["id"] + 1, line["original"],
                "" if qty is None else f"{qty:g}", "" if price is None else f"{price:.2f}",
                f"{cents(qty * price):.2f}" if qty and price else "",
                "" if line["pack_size"] is None else f"{line['pack_size']:g}", line["pack_unit"] or "",
                INGREDIENTS[line["ingredient"]]["name"]["en"] if line["ingredient"] else "",
                status, "" if inv["total"] is None else f"{inv['total']:.2f}", f"{inv['lines_sum']:.2f}",
                "yes" if inv["totals_match"] else "NO",
            ])
    return out.getvalue()


def reset():
    STATE.clear()
    STATE.update(new_state())


# ------------------------------------------------------------------ "While You Slept" report

def _report(dishes):
    """Three separate groups. Every 'verified' item includes the evidence that was checked."""
    verified, needs_input, proposed = [], [], []
    for inv in STATE["invoices"]:
        verified.append({"kind": "invoice_new", "at": inv["read_at"], "file": inv["file"],
                         "supplier": inv["supplier"], "invoice_no": inv["invoice_no"], "total": inv["total"]})
        item = {"at": inv["read_at"], "invoice_no": inv["invoice_no"], "lines": len(inv["lines"]),
                "lines_sum": inv["lines_sum"], "total": inv["total"]}
        (verified if inv["totals_match"] else needs_input).append(
            {"kind": "totals_match" if inv["totals_match"] else "totals_mismatch", **item})
        parsed = [l for l in inv["lines"] if l["pack_size"] and l["pack_unit"]]
        if parsed:
            verified.append({"kind": "packs_parsed", "at": inv["read_at"], "invoice_no": inv["invoice_no"],
                             "parsed": len(parsed), "of": len(inv["lines"]),
                             "items": [{"ingredient": l["ingredient"], "pack_size": l["pack_size"],
                                        "pack_unit": l["pack_unit"]} for l in parsed if l["ingredient"]]})
        for l in inv["lines"]:
            if l["status"] == "needs_review":
                needs_input.append({"kind": "line_review", "at": inv["read_at"], "invoice_id": inv["id"],
                                    "line_id": l["id"], "invoice_no": inv["invoice_no"], "original": l["original"],
                                    "reasons": l["reasons"], "ingredient": l["ingredient"],
                                    "dishes": [d for d in DISHES if l["ingredient"] in STATE["recipes"][d]]})
    for dup in _logged("duplicate_skipped"):
        verified.append({"kind": "duplicate_skipped", **dup})
    for c in _logged("owner_confirmed"):
        verified.append({"kind": "owner_confirmed", **c})
    recalcs = [a for a in STATE["activity"] if a["kind"] == "recalculated"]
    if recalcs:
        verified.append({"kind": "recalculated", "at": recalcs[-1]["at"], "dishes": len(DISHES),
                         "invoice_prices": sum(1 for s in STATE["sources"].values() if s["kind"] != "previous"),
                         "saved_prices": sum(1 for s in STATE["sources"].values() if s["kind"] == "previous")})
    for d in dishes:
        if d["status"] == COST_UP_OK and not d["held_by"]:
            verified.append({"kind": "cost_up_ok", "at": recalcs[-1]["at"] if recalcs else _now(), "dish": d["id"],
                             "margin": d["now"]["margin_pct"], "target": STATE["settings"]["target_margin_pct"],
                             "cost_change": d["cost_change_per_order"]})
        if d["proposal"] and d["decision"] in ("open", "approved"):
            proposed.append({"kind": "price_scenario", "dish": d["id"], "state": d["decision"],
                             "from_price": d["now"]["price"], "to_price": d["proposal"]["price"],
                             "per_order_change": d["proposal"]["per_order_change"],
                             "monthly_change": d["proposal"]["monthly_change"], "orders": d["monthly_orders"],
                             "approved_at": d["approval"]["at"] if d["approval"] else None})
    verified.sort(key=lambda x: x["at"])
    return {"verified": verified, "needs_input": needs_input, "proposed": proposed}


def view():
    dishes = [dish_view(d) for d in DISHES]
    changes = []
    for inv in STATE["invoices"]:
        for line in inv["lines"]:
            if line["applied"]:
                old, new = _per_base_cost(line["prev"]), _per_base_cost(line)
                pct = round(new / old - 1, 4)
                if abs(pct) > 0.0005:
                    changes.append({"ingredient": line["ingredient"], "pct": pct, "alert": abs(pct) >= ALERT_CHANGE,
                                    "prev": line["prev"], "prev_source": line["prev_source"],
                                    "now": {f: line[f] for f in ("pack_size", "pack_unit", "pack_price")},
                                    "source": STATE["sources"][line["ingredient"]],
                                    "invoice_id": inv["id"], "line_id": line["id"], "original": line["original"],
                                    "has_image": bool(inv["rows"]),
                                    "dishes": [d for d in DISHES if line["ingredient"] in STATE["recipes"][d]]})

    invoices = []
    for inv in STATE["invoices"]:
        lines = []
        for l in inv["lines"]:
            normalized = None
            if all(l.get(f) for f in ESSENTIAL):
                per_unit = l["pack_price"] / l["pack_size"]
                y = STATE["prices"][l["ingredient"]]["yield_pct"]
                normalized = {"per_unit": round(per_unit, 4), "unit": l["pack_unit"], "yield_pct": y,
                              "usable_per_unit": round(per_unit / (y / 100), 4)}
            change = round(_per_base_cost(l) / _per_base_cost(l["prev"]) - 1, 4) if l.get("prev") else None
            lines.append({**{k: l[k] for k in ("id", "original", "quantity", *ESSENTIAL, "status", "reasons", "corrected")},
                          "normalized": normalized, "change": change, "has_image": bool(inv["rows"]),
                          "line_total": cents(l["quantity"] * l["pack_price"]) if l["quantity"] and l["pack_price"] else None})
        invoices.append({**{k: inv[k] for k in ("id", "file", "supplier", "invoice_no", "date", "read_at",
                                                 "used_fallback", "total", "lines_sum", "totals_match")},
                         "lines": lines})

    return {
        "owner": OWNER_NAME,
        "restaurant": RESTAURANT_NAME,
        "has_run": STATE["has_run"],
        "inbox": list(INBOX_FILES),
        "settings": STATE["settings"],
        "commission_choices": list(COMMISSION_CHOICES),
        "dismiss_reasons": list(DISMISS_REASONS),
        "dishes": dishes,
        "changes": changes,
        "report": _report(dishes),
        "invoices": invoices,
        "duplicates": _logged("duplicate_skipped"),
        "timezone": RESTAURANT_TZ,
        "activity": STATE["activity"],
        "decision_log": STATE["decision_log"],
        "ingredients": {k: {"name": v["name"], "pack_unit": v["pack_unit"],
                            "yield_pct": STATE["prices"][k]["yield_pct"], "source": STATE["sources"][k]}
                        for k, v in INGREDIENTS.items()},
        "units": list(UNITS),
    }
