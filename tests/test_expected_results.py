"""Checks the app's numbers against demo-data/expected_results.json (the dataset's ground truth),
plus the two sad paths and the visitor sandboxes. Run:  python -m pytest -q  (or: python tests/test_expected_results.py)
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.pop("OPENROUTER_API_KEY", None)   # demo must work with no AI at all

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402

EXPECTED = json.loads((Path(api.ROOT) / "demo-data" / "expected_results.json").read_text())
STATUS = {"below_target": "Below your target margin", "cost_up_ok": "Cost increased; no action needed",
          "ok": "OK", "loses_money": "Loses money after the costs shown"}


def run_demo():
    client = TestClient(api.app)
    view = client.post("/api/run").json()["view"]
    return client, view


def test_numbers_match_expected_results():
    _, view = run_demo()
    dishes = {d["name"]["en"]: d for d in view["dishes"]}
    for want in EXPECTED["results"]:
        got = dishes[want["dish"]]
        assert got["prices"]["doordash"] == want["doordash_price"]
        assert round(got["before"]["food_cost"], 2) == want["cost_before"], want["dish"]
        assert round(got["now"]["food_cost"], 2) == want["cost_after"], want["dish"]
        assert got["now"]["left"] == want["left_per_order"], want["dish"]
        assert got["now"]["margin_pct"] == want["margin_pct"], want["dish"]
        assert got["monthly_orders"] == want["forecast_monthly_orders"], want["dish"]
        status = "Needs review" if got["held_by"] else STATUS[got["status"]]
        assert status == want["status"], (want["dish"], status)
        if "proposal" in want:
            p, wp = got["proposal"], want["proposal"]
            assert p["price"] == wp["new_doordash_price"]
            assert p["after"]["left"] == wp["left_per_order"]
            assert p["after"]["margin_pct"] == wp["margin_pct"]
            assert p["per_order_change"] == wp["gain_per_order"]
            assert p["monthly_change"] == wp["gain_per_month"]


def test_duplicate_skipped_and_rice_paper_correction():
    client, view = run_demo()
    assert [d["invoice_no"] for d in view["duplicates"]] == ["RM-20419"]
    assert view["duplicates"][0]["file"] == "FWD_scan_rivermark_RM-20419.png"
    review = view["report"]["needs_input"]
    assert [r["original"] for r in review] == ["RICE PAPER 22CM 1 CS"]
    r = client.post(f"/api/invoices/{review[0]['invoice_id']}/lines/{review[0]['line_id']}",
                    json={"ingredient": "rice_paper", "packs": "10", "per_pack": "50", "pack_unit": "sheet",
                          "pack_price": "38.00"}).json()["view"]
    spring = next(d for d in r["dishes"] if d["id"] == "spring-rolls-2")
    assert spring["held_by"] == [] and spring["status"] == "ok"
    assert round(spring["now"]["food_cost"], 2) == 1.72
    assert any(a["kind"] == "owner_confirmed" and a["params"]["pack_size"] == 500 for a in r["activity"])


def test_visitors_are_sandboxed():
    a, b = TestClient(api.app), TestClient(api.app)
    a.post("/api/run")
    a.post("/api/dishes/brisket-pho/approve")
    assert len(a.get("/api/state").json()["decision_log"]) == 1
    assert b.get("/api/state").json()["has_run"] is False      # b never saw a's run
    a.post("/api/reset")
    assert a.get("/api/state").json()["decision_log"] == []


def test_health_and_upload_guards():
    c = TestClient(api.app)
    assert c.get("/api/health").json() == {"ok": True}
    assert c.post("/api/invoices", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 415
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (5 * 1024 * 1024)
    assert c.post("/api/invoices", files={"file": ("big.png", big, "image/png")}).status_code == 413
    # A new (non-demo) image with no API key: friendly error, no crash.
    r = c.post("/api/invoices", files={"file": ("new.png", b"\x89PNG\r\n\x1a\nnot-a-demo", "image/png")})
    assert r.status_code == 503 and r.json()["detail"]["error"] == "ai_not_configured"
    # A demo file re-uploaded: read from the fallback reading, no API needed.
    demo = (Path(api.ROOT) / "demo-data" / "inbox" / "invoice_lotus_pantry_2026-11-06.png").read_bytes()
    assert c.post("/api/invoices", files={"file": ("lotus.png", demo, "image/png")}).status_code == 200


def _fake_upload(client, monkeypatch, number="RM-20419", bump=0.0, name="corrected.png"):
    """Upload a file whose (fake) saved reading is invoice `number`, with one price changed by `bump`."""
    import copy, hashlib, engine
    reading = copy.deepcopy(next(r for r in engine.DEMO_READINGS.values() if r["number"] == number))
    reading["lines"][0]["unit_price"] = round(reading["lines"][0]["unit_price"] + bump, 2)
    reading["lines"][0]["amount"] = round(reading["lines"][0]["unit_price"] * reading["lines"][0]["qty"], 2)
    reading["total"] = round(sum(l["amount"] for l in reading["lines"]), 2)
    data = b"\x89PNG\r\n\x1a\n" + name.encode() + str(bump).encode()
    monkeypatch.setitem(engine.DEMO_READINGS, hashlib.sha256(data).hexdigest(), reading)
    return client.post("/api/invoices", files={"file": (name, data, "image/png")})


def test_saved_readings_are_labelled_as_replays():
    _, view = run_demo()
    assert view["invoices"] and all(inv["extraction"] == "saved" for inv in view["invoices"])


def test_same_number_same_contents_is_a_duplicate(monkeypatch):
    client, _ = run_demo()
    r = _fake_upload(client, monkeypatch, bump=0.0, name="again.png").json()
    assert r["duplicate_of"] == "RM-20419"
    assert r["view"]["possible_corrections"] == []


def test_same_number_different_contents_is_held_then_owner_chooses(monkeypatch):
    client, before = run_demo()
    brisket_before = next(d for d in before["dishes"] if d["id"] == "brisket-pho")["now"]["food_cost"]
    r = _fake_upload(client, monkeypatch, bump=10.0).json()
    assert r["possible_correction"] == "RM-20419"
    pcs = r["view"]["possible_corrections"]
    assert len(pcs) == 1 and pcs[0]["only_new"] and pcs[0]["only_counted"]
    assert any(i["kind"] == "possible_correction" for i in r["view"]["report"]["needs_input"])
    assert len(r["view"]["invoices"]) == 3            # not counted yet
    v = client.post(f"/api/corrections/{pcs[0]['id']}", json={"choice": "use_new"}).json()["view"]
    old = next(i for i in v["invoices"] if i["invoice_no"] == "RM-20419" and i["superseded_by"] is not None)
    new = next(i for i in v["invoices"] if i["replaces"] == old["id"])
    assert new["total"] != old["total"] and v["possible_corrections"] == []
    brisket_after = next(d for d in v["dishes"] if d["id"] == "brisket-pho")["now"]["food_cost"]
    assert brisket_after > brisket_before             # the corrected (higher) price now counts
    assert any(a["kind"] == "correction_effect" for a in v["activity"])
    csv_text = client.get("/api/export/bookkeeper.csv").text
    assert csv_text.count("RM-20419") == len(new["lines"])   # only one version is counted
    # The corrected version arriving again is now just a duplicate.
    assert _fake_upload(client, monkeypatch, bump=10.0, name="again.png").json()["duplicate_of"] == "RM-20419"


def test_keep_current_price_is_logged_with_optional_reason():
    client, _ = run_demo()
    v = client.post("/api/dishes/brisket-pho/keep", json={"note": "Regulars order it daily"}).json()["view"]
    rec = v["decision_log"][-1]
    assert rec["kind"] == "kept_price" and rec["note"] == "Regulars order it daily" and rec["published"] is False
    assert next(d for d in v["dishes"] if d["id"] == "brisket-pho")["decision"] == "kept"
    v = client.post("/api/dishes/brisket-pho/restore").json()["view"]
    assert next(d for d in v["dishes"] if d["id"] == "brisket-pho")["decision"] == "open"


def test_held_dish_shows_previous_cost_and_correction_logs_effect():
    client, view = run_demo()
    spring = next(d for d in view["dishes"] if d["id"] == "spring-rolls-2")
    held = spring["held_inputs"]
    assert [h["ingredient"] for h in held] == ["rice_paper"] and held[0]["source"]["date"]
    review = view["report"]["needs_input"][0]
    v = client.post(f"/api/invoices/{review['invoice_id']}/lines/{review['line_id']}",
                    json={"ingredient": "rice_paper", "packs": "10", "per_pack": "50", "pack_unit": "sheet",
                          "pack_price": "38.00"}).json()["view"]
    effects = [a["params"] for a in v["activity"] if a["kind"] == "correction_effect"]
    assert any(e["dish"] == "spring-rolls-2" and e["status_from"] == "held" for e in effects)


def test_order_basis_explains_the_forecast():
    _, view = run_demo()
    basis = next(d for d in view["dishes"] if d["id"] == "brisket-pho")["order_basis"]
    assert basis["days"] == 28 and basis["forecast"] == round(basis["orders"] / 28 * basis["days_per_month"])


if __name__ == "__main__":
    import inspect
    for name, fn in list(globals().items()):
        if name.startswith("test_") and not inspect.signature(fn).parameters:   # monkeypatch tests: use pytest
            fn()
            print("ok", name)
