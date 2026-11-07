"""Persistence for production (Supabase) + the row <-> engine-state mapping.

The engine works on one restaurant's state as a dict. Each API request:
    load  -> one RPC: get_restaurant_state(restaurant_id)           (Postgres function, one round trip)
    run   -> engine functions on the dict (pure Python, tested)
    save  -> one RPC: save_restaurant_state(restaurant_id, rows)    (one transaction)

Only the backend talks to Supabase, with the service-role key. Tables have RLS on and no policies.
Invoice files go to the private "invoices" bucket and reach the browser only as short-lived signed URLs.
"""

import copy
import json

import httpx

import engine
from data import DISHES, INGREDIENTS

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
BUCKET = "invoices"

# Which "While You Slept" group each activity kind belongs to (null = owner action).
GROUP = {
    "shift_start": "verified", "invoice_read": "verified", "recalculated": "verified", "duplicate_skipped": "verified",
    "owner_confirmed": "verified", "hold_cleared": "verified", "price_change": "verified", "brief_ready": "verified",
    "held": "needs_input",
    "below_target": "proposed", "loses_money": "proposed", "approved": "proposed",
}


def _message(entry):
    """Plain-English line stored next to the structured evidence (for people reading the table)."""
    k, p = entry["kind"], entry["params"]
    return {
        "shift_start": f"Night Shift started: {p.get('files')} files in the inbox.",
        "invoice_read": f"Read {p.get('supplier')} {p.get('invoice_no')}: {p.get('lines')} lines, {p.get('review')} to review.",
        "duplicate_skipped": f"Duplicate of {p.get('invoice_no')}, skipped. Not counted. ({p.get('file')})",
        "price_change": f"{p.get('ingredient')}: {p.get('old')} -> {p.get('new')} per pack ({p.get('invoice_no')}).",
        "owner_confirmed": f"Owner confirmed {p.get('ingredient')} case = {p.get('pack_size'):g} {p.get('pack_unit')}."
        if isinstance(p.get("pack_size"), (int, float)) else f"Owner confirmed {p.get('ingredient')}.",
        "approved": f"Approved {p.get('dish')} at {p.get('to_price')}. Saved, not published.",
        "dismissed": f"Dismissed {p.get('dish')}: {p.get('reason')}.",
    }.get(k, f"{k.replace('_', ' ')}{(': ' + p['dish']) if 'dish' in p else ''}")


# ------------------------------------------------------------------ rows -> engine state

def _num(x):
    return None if x is None else float(x)


def state_from_rows(snapshot):
    """Build the engine's state dict from get_restaurant_state() output."""
    r = snapshot["restaurant"]
    state = engine.new_state(r["settings"])
    es = r.get("engine_state") or {}
    state.update(has_run=bool(es.get("has_run")), decisions=es.get("decisions", {}), findings=es.get("findings", {}),
                 restaurant_id=r["id"])

    for row in snapshot["ingredients"]:
        key = row["ingredient_key"]
        state["prices"][key].update(pack_size=_num(row["pack_size"]), pack_unit=row["pack_unit"],
                                    pack_price=_num(row["pack_price"]), yield_pct=_num(row["yield_pct"]))
        if row.get("baseline_pack_price") is not None:
            state["baseline"][key].update(pack_size=_num(row["baseline_pack_size"]), pack_unit=row["baseline_pack_unit"],
                                          pack_price=_num(row["baseline_pack_price"]), yield_pct=_num(row["yield_pct"]))
        if row.get("source"):
            state["sources"][key] = row["source"]

    if snapshot["recipes"]:
        state["recipes"] = {}
        for row in snapshot["recipes"]:
            state["recipes"].setdefault(row["item_key"], {})[row["ingredient_key"]] = [_num(row["qty"]), row["unit"]]

    lines = {}
    for row in snapshot["invoice_lines"]:
        lines.setdefault(row["invoice_local_id"], []).append({
            "id": row["line_no"], "original": row["description"], "quantity": _num(row["quantity"]),
            "ingredient": row["ingredient_key"], "pack_size": _num(row["pack_size"]), "pack_unit": row["pack_unit"],
            "pack_price": _num(row["pack_price"]), "unclear": row["unclear"] or [], "reasons": row["reasons"] or [],
            "status": "needs_review" if row["needs_review"] else "verified", "corrected": row["corrected"],
            "applied": row["applied"], "prev": row["prev"], "prev_source": row["prev_source"]})
    for row in snapshot["invoices"]:
        lid = row["local_id"]
        state["invoices"].append({
            "id": lid, "file": row["file_name"], "read_at": row["read_at"], "supplier": row["supplier"],
            "invoice_no": row["invoice_number"], "date": row["invoice_date"], "total": _num(row["total"]),
            "used_fallback": row["from_demo"], "fingerprint": row["fingerprint"], "mime": row["mime"],
            "rows": row["layout"], "lines_sum": _num(row["lines_sum"]), "totals_match": row["totals_match"],
            "lines": sorted(lines.get(lid, []), key=lambda l: l["id"])})
        if row["fingerprint"]:
            state["fingerprints"][row["fingerprint"]] = lid
        if row["storage_path"]:
            state["images"][lid] = ("storage", row["storage_path"])

    state["decision_log"] = [row["details"] for row in snapshot["decisions"]]
    state["activity"] = [{"id": row["local_id"], "at": row["at"], "kind": row["evidence"].get("kind"),
                          "params": row["evidence"].get("params", {}), "run_id": row["run_id"]}
                         for row in snapshot["activity_log"]]
    return state


# ------------------------------------------------------------------ engine state -> rows

def _finding(dish):
    status = "needs_review" if dish["held_by"] else dish["status"]
    return {"item_key": dish["id"], "status": status, "evidence": {
        "amount_left": dish["now"]["left"], "margin_pct": dish["now"]["margin_pct"],
        "target_pct": engine.STATE["settings"]["target_margin_pct"], "food_cost": dish["now"]["food_cost"],
        "cost_change_per_order": dish["cost_change_per_order"], "held_by": dish["held_by"],
        "scenario": dish["proposal"] and {"price": dish["proposal"]["price"],
                                          "per_order_change": dish["proposal"]["per_order_change"],
                                          "monthly_change": dish["proposal"]["monthly_change"]}}}


def rows_from_state(state, loaded_activity):
    """What save_restaurant_state() needs. Call with engine.STATE pointing at `state`."""
    ingredients = []
    for key, p in state["prices"].items():
        meta, base = INGREDIENTS[key], state["baseline"][key]
        ingredients.append({"ingredient_key": key, "name": meta["name"], "invoice_alias": meta["alias"],
                            "pack_desc": meta["pack_desc"], "pack_size": p["pack_size"], "pack_unit": p["pack_unit"],
                            "pack_price": p["pack_price"], "yield_pct": p["yield_pct"],
                            "baseline_pack_size": base["pack_size"], "baseline_pack_unit": base["pack_unit"],
                            "baseline_pack_price": base["pack_price"], "source": state["sources"].get(key)})
    invoices, lines = [], []
    for inv in state["invoices"]:
        image = state["images"].get(inv["id"])
        invoices.append({"local_id": inv["id"], "file_name": inv["file"], "supplier": inv["supplier"],
                         "invoice_number": inv["invoice_no"], "invoice_date": inv["date"], "total": inv["total"],
                         "lines_sum": inv["lines_sum"], "totals_match": inv["totals_match"],
                         "fingerprint": inv["fingerprint"], "mime": inv.get("mime"), "layout": inv.get("rows"),
                         "storage_path": image[1] if image and image[0] == "storage" else None,
                         "from_demo": inv["used_fallback"], "read_at": inv["read_at"]})
        for l in inv["lines"]:
            confidence = None if not l["ingredient"] else 1.0 if (l["corrected"] or not l["unclear"]) else 0.5
            lines.append({"invoice_local_id": inv["id"], "line_no": l["id"], "description": l["original"],
                          "quantity": l["quantity"], "ingredient_key": l["ingredient"], "pack_size": l["pack_size"],
                          "pack_unit": l["pack_unit"], "pack_price": l["pack_price"], "match_confidence": confidence,
                          "needs_review": l["status"] == "needs_review", "reasons": l["reasons"],
                          "unclear": l["unclear"], "corrected": l["corrected"], "applied": l["applied"],
                          "prev": l.get("prev"), "prev_source": l.get("prev_source")})
    return {
        "settings": state["settings"],
        "engine_state": {"has_run": state["has_run"], "decisions": state["decisions"], "findings": state["findings"]},
        "ingredients": ingredients,
        "recipes": [{"item_key": d, "ingredient_key": k, "qty": v[0], "unit": v[1]}
                    for d, rec in state["recipes"].items() for k, v in rec.items()],
        "invoices": invoices,
        "invoice_lines": lines,
        "price_history_new": state["price_history_new"],
        "findings": [_finding(engine.dish_view(d)) for d in DISHES],
        "decisions": [{"local_id": e["id"], "item_key": e["dish"], "action": e["kind"],
                       "reason": e.get("note") or e.get("reason"), "user_id": e.get("user_id"),
                       "decided_at": e["at"], "details": e} for e in state["decision_log"]],
        "activity_new": [{"local_id": a["id"], "run_id": a.get("run_id"), "group": GROUP.get(a["kind"]),
                          "message": _message(a), "evidence": {"kind": a["kind"], "params": a["params"]}, "at": a["at"]}
                         for a in state["activity"][loaded_activity:]],
    }


# ------------------------------------------------------------------ Supabase (PostgREST + Storage)

class SupabaseStore:
    """Database access with the service-role key. Never sends the key anywhere but Supabase."""

    def __init__(self, url, service_key, http=None):
        self.url = url
        self._headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
        self.http = http or httpx.AsyncClient(timeout=TIMEOUT)
        self._restaurants = {}   # user id -> restaurant id (cache; restaurants never move between users)

    async def rpc(self, fn, args):
        r = await self.http.post(f"{self.url}/rest/v1/rpc/{fn}", json=args, headers=self._headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Supabase RPC {fn} failed with HTTP {r.status_code}")   # no body: may echo input
        return r.json() if r.content else None

    async def restaurant_for(self, user_id):
        """The user's restaurant; created from the demo template on first sign-in."""
        if user_id not in self._restaurants:
            self._restaurants[user_id] = await self.rpc("create_demo_restaurant", {"p_user_id": user_id})
        return self._restaurants[user_id]

    async def load(self, restaurant_id):
        snapshot = await self.rpc("get_restaurant_state", {"p_restaurant_id": restaurant_id})
        state = state_from_rows(snapshot)
        return state, {"activity": len(state["activity"])}

    async def save(self, restaurant_id, state, meta):
        rows = rows_from_state(state, meta["activity"])
        await self.rpc("save_restaurant_state", {"p_restaurant_id": restaurant_id,
                                                 "p_state": json.loads(json.dumps(rows, default=str))})

    async def reset(self, user_id, files=None):
        old = self._restaurants.get(user_id) or await self.restaurant_for(user_id)
        new = await self.rpc("reset_demo_restaurant", {"p_user_id": user_id})
        self._restaurants[user_id] = new
        if files is not None:
            files.delete_prefix(f"{old}/")
        return new

    async def all_restaurants(self):
        r = await self.http.get(f"{self.url}/rest/v1/restaurants",
                                params={"select": "id", "is_template": "eq.false"}, headers=self._headers)
        r.raise_for_status()
        return [row["id"] for row in r.json()]


class SupabaseFiles:
    """Private bucket access (sync: called from engine code running in a worker thread)."""

    def __init__(self, url, service_key, http=None):
        self.base = f"{url}/storage/v1"
        self._headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
        self.http = http or httpx.Client(timeout=TIMEOUT)

    def put(self, path, data, mime):
        r = self.http.post(f"{self.base}/object/{BUCKET}/{path}", content=data,
                           headers={**self._headers, "Content-Type": mime, "x-upsert": "true"})
        r.raise_for_status()

    def get(self, path):
        r = self.http.get(f"{self.base}/object/{BUCKET}/{path}", headers=self._headers)
        r.raise_for_status()
        return r.content

    def signed_url(self, path, seconds=300):
        """Short-lived link the browser can open without any key."""
        r = self.http.post(f"{self.base}/object/sign/{BUCKET}/{path}", json={"expiresIn": seconds}, headers=self._headers)
        r.raise_for_status()
        return f"{self.base}{r.json()['signedURL']}"

    def delete_prefix(self, prefix):
        r = self.http.post(f"{self.base}/object/list/{BUCKET}", json={"prefix": prefix, "limit": 1000},
                           headers=self._headers)
        r.raise_for_status()
        names = [f"{prefix}{o['name']}" for o in r.json() if o.get("name")]
        if names:
            self.http.request("DELETE", f"{self.base}/object/{BUCKET}", json={"prefixes": names},
                              headers=self._headers).raise_for_status()


def fresh_copy(state):
    """Deep copy for tests (the engine mutates state in place)."""
    return copy.deepcopy(state)
