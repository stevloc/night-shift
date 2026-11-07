"""The bounded tool-using investigator ("Investigate this alert").

MOCK MODEL: every test here replaces llm.chat_turn with MockModel, a small rule-based stand-in that
reads the alert and the *actual* tool results and picks the next step. It exercises the orchestration
(tool execution, limits, validation, no mutations). It says nothing about how a real model behaves:
live behaviour is unverified until run with OPENROUTER_API_KEY (see docs/decision-review-eval.md).
"""

import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("OPENROUTER_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import engine  # noqa: E402
import investigate  # noqa: E402
import llm  # noqa: E402
import review  # noqa: E402

NB_7731 = {"file": "nb.png", "supplier": "Northbank Provisions (fictional)", "number": "NB-7731", "date": "2026-11-07",
           "total": 280.0, "lines": [{"description": "BEEF BRISKET CHOICE 20 LB CS", "qty": 2, "unit": "CS",
                                      "unit_price": 140.0, "amount": 280.0}]}
NB_BYTES = b"\x89PNG\r\n\x1a\nNB-7731-investigate"


def call(name, **args):
    return SimpleNamespace(id=f"call_{name}_{len(json.dumps(args))}",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def reply(content=None, tool_calls=None):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


class MockModel:
    """Rule-based stand-in for the model. Decides from the alert text and the tool results it was given."""

    def __init__(self):
        self.turns, self.override = [], None

    def __call__(self, messages, tools, final, timeout):
        self.turns.append({"final": final, "timeout": timeout})
        if self.override:
            return self.override(messages, final)
        alert = messages[1]["content"]
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        dish = alert.split("dish_id ")[1].split(")")[0]
        held = [line.split(": ")[1] for line in alert.splitlines() if line.startswith("Held ingredients")]
        if not results and held:                         # unconfirmed input: look at the line and its history
            ing = held[0].split(", ")[0]
            return reply(tool_calls=[call("get_invoice_evidence", ingredient=ing),
                                     call("get_ingredient_cost_history", ingredient=ing)])
        if not results:                                  # cost change: history of the biggest mover + the dish
            ing = alert.split("tonight's run: ")[1].split(" ")[0]
            return reply(tool_calls=[call("get_ingredient_cost_history", ingredient=ing),
                                     call("get_dish_context", dish_id=dish)])
        held_lines = [l for r in results for l in r.get("lines", []) if l["status"] == "held"]
        history = next((r for r in results if "dated_deliveries" in r), None)
        if held_lines:
            refs = [held_lines[0]["ref"]] + [d["ref"] for d in (history or {}).get("dated_deliveries", [])]
            missing = bool(history and history["status"] == "missing")
            return reply(json.dumps({
                "outcome": "needs_confirmation",
                "summary": "The rice paper line has no pack size, so its cost per sheet can't be checked."
                           + (" There is no earlier delivery history to compare with." if missing else ""),
                "evidence_refs": refs, "scenario_ids": [],
                "uncertainty": ["No previous cost is on record."] if missing else [],
                "question": "How many sheets are in one case on " + held_lines[0]["invoice_no"] + "?",
                "next_step": "confirm_invoice_line"}))
        ctx = next((r for r in results if "current_doordash_price" in r), None)
        scenario = next((r for r in results if str(r.get("ref", "")).startswith("scenario:")), None)
        if ctx and not scenario and ctx["status_now"] in ("below_target", "loses_money") and not final:
            return reply(tool_calls=[call("calculate_price_scenario", dish_id=dish,
                                          price=round(ctx["current_doordash_price"] + 1, 2))])
        cur = history["current_accepted"]
        return reply(json.dumps({
            "outcome": "ready_for_review",
            "summary": f"The accepted brisket cost is now ${cur['pack_price']:.2f} per case."
                       + (f" At ${scenario['price']:.2f} the calculator leaves ${scenario['left_per_order']:.2f} per order."
                          if scenario else ""),
            "evidence_refs": [cur["ref"], history["before_tonights_run"]["ref"], ctx["ref"]],
            "scenario_ids": [scenario["ref"]] if scenario else [],
            "uncertainty": ["Order volume is assumed unchanged."], "question": None,
            "next_step": "approve_or_edit_price"}))


@pytest.fixture
def client():
    c = TestClient(api.app)
    c.post("/api/run")
    return c


@pytest.fixture
def brisket_140(client, monkeypatch):
    monkeypatch.setitem(engine.DEMO_READINGS, hashlib.sha256(NB_BYTES).hexdigest(), NB_7731)
    assert client.post("/api/invoices", files={"file": ("nb.png", NB_BYTES, "image/png")}).status_code == 200
    return client


@pytest.fixture
def model(monkeypatch):
    """Key configured, tool support confirmed (no network), mock model in place."""
    monkeypatch.setattr(api, "CONFIG", dataclasses.replace(api.CONFIG, openrouter_api_key="test-key"))
    monkeypatch.setattr(llm, "supports_tools", lambda *a, **k: True)
    monkeypatch.setattr(review, "REVIEWS", engine.RateLimiter(limit=50, window_seconds=3600))
    mock = MockModel()
    monkeypatch.setattr(llm, "chat_turn", mock)
    return mock


def investigate_dish(c, dish_id):
    return c.post(f"/api/dishes/{dish_id}/investigate", json={}).json()


def session_state(client):
    """The visitor's real state (for direct tool checks)."""
    sid = client.cookies.get(api.COOKIE)
    return engine.SESSIONS._items[sid]["state"]


# ------------------------------------------------------------------ 1. verified cost change

def test_verified_cost_change_produces_a_supported_finding(brisket_140, model):
    r = investigate_dish(brisket_140, "brisket-pho")
    assert r["status"] == "ok" and r["finding"]["outcome"] == "ready_for_review"
    assert [e["tool"] for e in r["events"]] == ["get_ingredient_cost_history", "get_dish_context",
                                                "calculate_price_scenario"]
    assert all(e["status"] == "ok" for e in r["events"])
    assert set(r["finding"]["evidence_refs"]) == set(r["refs"])      # every reference was retrieved in this run
    assert any(v.get("invoice_no") == "NB-7731" for v in r["refs"].values())
    scenario = r["scenarios"][0]                                     # figures come from the calculator
    assert scenario["price"] == 16.99 and scenario["left_per_order"] == 6.59 and scenario["reaches_target"]
    assert "$140.00" in r["finding"]["summary"]
    assert r["turns"] == 3 and r["tool_executions"] == 3


# ------------------------------------------------------------------ 2. unclear package size

def test_unclear_pack_size_asks_one_question_and_keeps_the_hold(client, model):
    before = client.get("/api/state").json()
    r = investigate_dish(client, "spring-rolls-2")
    assert r["status"] == "ok" and r["finding"]["outcome"] == "needs_confirmation"
    assert [e["tool"] for e in r["events"]] == ["get_invoice_evidence", "get_ingredient_cost_history"]
    assert r["events"][0]["status"] == "held"
    assert "LP-5521" in r["finding"]["question"] and r["finding"]["next_step"] == "confirm_invoice_line"
    assert r["readings"] == ["saved"]          # the invoice reading itself was a saved replay, labelled as such
    after = client.get("/api/state").json()
    assert after == before
    assert next(d for d in after["dishes"] if d["id"] == "spring-rolls-2")["held_by"] == ["rice_paper"]


def test_tools_validate_arguments_and_refuse_held_scenarios(client):
    token = engine.use_session(session_state(client))
    try:
        inv = investigate.Investigation("spring-rolls-2")
        out = inv.call("calculate_price_scenario", json.dumps({"dish_id": "spring-rolls-2", "price": 8.99}))
        assert out["status"] == "held" and inv.scenarios == {}
        assert inv.call("get_invoice_evidence", json.dumps({"ingredient": "../etc/passwd"}))["error"] == "unknown_ingredient"
        assert inv.call("calculate_price_scenario", json.dumps({"dish_id": "bun-cha", "price": "lots"}))["status"] == "error"
        assert inv.call("get_dish_context", "not json")["error"] == "invalid_arguments"
        history = inv.call("get_ingredient_cost_history", json.dumps({"ingredient": "rice_paper"}))
        assert history["held_lines_excluded"] == 1     # the held line is never an accepted cost
        assert history["current_accepted"]["pack_price"] == 76.0
    finally:
        engine._current.reset(token)


# ------------------------------------------------------------------ 3. missing history

def test_missing_history_is_stated_not_invented(client, model, monkeypatch):
    monkeypatch.setitem(investigate.PRICE_HISTORY, "rice_paper", [])
    r = investigate_dish(client, "spring-rolls-2")
    history = next(e for e in r["events"] if e["tool"] == "get_ingredient_cost_history")
    assert history["status"] == "missing"
    assert r["finding"]["outcome"] == "needs_confirmation" and "No previous cost" in r["finding"]["uncertainty"][0]
    assert not any(ref.startswith("history:") for ref in r["finding"]["evidence_refs"])

    def invents_history(messages, final):           # cites a delivery that no tool returned
        if not any(m["role"] == "tool" for m in messages):
            return reply(tool_calls=[call("get_ingredient_cost_history", ingredient="rice_paper")])
        return reply(json.dumps({"outcome": "needs_confirmation", "summary": "Last delivery was $76.00.",
                                 "evidence_refs": ["history:rice_paper:2026-10-30"], "question": "Confirm?"}))
    model.override = invents_history
    r = investigate_dish(client, "spring-rolls-2")
    assert r["status"] == "unavailable" and r["reason"] == "invalid_output" and r["finding"] is None


def test_unsupported_figures_and_ready_while_held_are_rejected(brisket_140, client, model):
    def made_up_price(messages, final):
        if not any(m["role"] == "tool" for m in messages):
            return reply(tool_calls=[call("get_dish_context", dish_id="brisket-pho")])
        return reply(json.dumps({"outcome": "ready_for_review", "summary": "Charge $18.25 to be safe.",
                                 "evidence_refs": ["dish:brisket-pho"]}))
    model.override = made_up_price
    assert investigate_dish(brisket_140, "brisket-pho")["reason"] == "invalid_output"

    def ready_on_held(messages, final):
        if not any(m["role"] == "tool" for m in messages):
            return reply(tool_calls=[call("get_dish_context", dish_id="spring-rolls-2")])
        return reply(json.dumps({"outcome": "ready_for_review", "summary": "Looks fine.",
                                 "evidence_refs": ["dish:spring-rolls-2"]}))
    model.override = ready_on_held
    assert investigate_dish(brisket_140, "spring-rolls-2")["reason"] == "invalid_output"


# ------------------------------------------------------------------ 4. failures and limits

def test_never_finishing_model_stops_at_the_limits(brisket_140, model):
    model.override = lambda messages, final: reply(tool_calls=[
        call("get_dish_context", dish_id="brisket-pho"),
        call("calculate_price_scenario", dish_id="brisket-pho", price=round(16 + len(messages) / 100, 2)),
        call("calculate_price_scenario", dish_id="brisket-pho", price=round(17 + len(messages) / 100, 2))])
    r = investigate_dish(brisket_140, "brisket-pho")
    assert r["status"] == "unavailable" and r["reason"] == "incomplete"
    assert r["tool_executions"] <= investigate.MAX_TOOLS and len(r["events"]) == r["tool_executions"]
    assert r["turns"] <= investigate.MAX_TURNS and model.turns[-1]["final"] is True
    assert sum(e["tool"] == "get_dish_context" for e in r["events"]) == 1   # repeated call never re-executed


def test_timeout_and_deadline_end_the_run(brisket_140, model):
    class APITimeoutError(Exception):
        pass

    def slow(messages, final):
        raise APITimeoutError("Request timed out.")
    model.override = slow
    r = investigate_dish(brisket_140, "brisket-pho")
    assert r["status"] == "unavailable" and r["reason"] == "timeout" and r["events"] == []

    ticks = iter([0, 0, 50, 50, 50])                   # the deadline passes after the first turn
    model.override = lambda messages, final: reply(tool_calls=[call("get_dish_context", dish_id="brisket-pho")])
    out = investigate.run(session_state(brisket_140), "brisket-pho", {}, clock=lambda: next(ticks))
    assert out["reason"] == "deadline" and out["turns"] == 1
    assert all(t["timeout"] <= investigate.REQUEST_TIMEOUT for t in model.turns)
    assert brisket_140.post("/api/dishes/brisket-pho/approve").status_code == 200     # the app still works


def test_unsupported_tools_and_provider_errors_are_unavailable(brisket_140, model, monkeypatch):
    monkeypatch.setattr(llm, "supports_tools", lambda *a, **k: False)
    r = investigate_dish(brisket_140, "brisket-pho")
    assert r["reason"] == "tools_unsupported" and model.turns == [] and r["events"] == []
    monkeypatch.setattr(llm, "supports_tools", lambda *a, **k: None)   # unknown: try it, report the provider's answer

    def no_tools(messages, final):
        raise RuntimeError("No endpoints found that support tool use")
    model.override = no_tools
    assert investigate_dish(brisket_140, "brisket-pho")["reason"] == "tools_unsupported"


# ------------------------------------------------------------------ 5. no API key

def test_no_api_key_means_no_investigation_and_no_activity(client, monkeypatch):
    called = []
    monkeypatch.setattr(llm, "chat_turn", lambda *a, **k: called.append(1))
    r = investigate_dish(client, "brisket-pho")
    assert r["status"] == "unavailable" and r["reason"] == "ai_not_configured" and r["events"] == [] and not called
    assert r["snapshot"]["options"]                     # the deterministic comparison is still returned


# ------------------------------------------------------------------ 6. no unintended mutations

def test_investigation_changes_nothing(brisket_140, model):
    before = brisket_140.get("/api/state").json()
    cache_before = dict(llm._cache)
    investigate_dish(brisket_140, "brisket-pho")
    investigate_dish(brisket_140, "spring-rolls-2")
    assert brisket_140.get("/api/state").json() == before   # invoices, costs, recipes, decisions, prices, log
    assert dict(llm._cache) == cache_before                   # invoice-reading cache untouched
