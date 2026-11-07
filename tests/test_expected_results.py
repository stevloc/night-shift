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


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
