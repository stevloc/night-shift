"""The scheduled nightly run: the server entry point (POST /api/nightly-run) and the GitHub Actions client
(scripts/nightly_client.py). No network, no AI: the client is driven with a fake HTTP function, the
endpoint runs in local demo mode or against a fake Supabase store."""

import dataclasses
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
os.environ.pop("OPENROUTER_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import engine  # noqa: E402
import investigate  # noqa: E402
import llm  # noqa: E402
import nightly_client  # noqa: E402

SECRET = "test-cron-secret-123456"
HEADERS = {"X-Cron-Secret": SECRET}
SENSITIVE = ("Rivermark", "Greenleaf", "Lotus", "RM-20419", "brisket", "rice")


@pytest.fixture(autouse=True)
def server(monkeypatch):
    monkeypatch.setattr(api, "CONFIG", dataclasses.replace(api.CONFIG, cron_secret=SECRET))
    monkeypatch.setattr(api, "STORE", None)
    engine.SESSIONS._items.clear()

    def forbidden(*a, **k):
        raise AssertionError("the nightly run must never call the AI review or the investigator")
    monkeypatch.setattr(llm, "review_decision", forbidden)
    monkeypatch.setattr(llm, "chat_turn", forbidden)
    monkeypatch.setattr(investigate, "run", forbidden)
    yield
    engine.SESSIONS._items.clear()


def one_restaurant():
    """A local-mode visitor sandbox, as the browser would create it."""
    client = TestClient(api.app)
    assert client.get("/api/state").json()["has_run"] is False
    return client


def only_state():
    return next(iter(engine.SESSIONS._items.values()))["state"]


def nightly(key=None, **headers):
    h = {**HEADERS, **({"X-Run-Key": key} if key else {}), **headers}
    return TestClient(api.app).post("/api/nightly-run", headers=h)


# ------------------------------------------------------------------ server entry point

def test_secret_required():
    assert TestClient(api.app).post("/api/nightly-run").status_code == 403
    assert nightly(**{"X-Cron-Secret": "wrong"}).status_code == 403


def test_invalid_run_key_rejected():
    assert nightly("bad key; drop").status_code == 400


def test_runs_once_and_reports_counts_only():
    owner = one_restaurant()
    r = nightly("nightly-2026-11-08")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["restaurants"] == 1 and body["restaurants_run"] == 1
    assert body["invoices_processed"] == 3 and body["duplicates_skipped"] == 1
    assert body["review_holds"] >= 1 and body["errors"] == 0   # rice paper: no pack size -> held
    assert not any(word.lower() in r.text.lower() for word in SENSITIVE), "summary must not leak invoice contents"
    view = owner.get("/api/state").json()
    assert view["has_run"] and len(view["invoices"]) == 3
    assert view["decision_log"] == []   # owner controls untouched: nothing approved


def test_same_run_key_is_not_run_twice():
    owner = one_restaurant()
    first = nightly("nightly-2026-11-08").json()
    activity = len(only_state()["activity"])
    again = nightly("nightly-2026-11-08")
    assert again.status_code == 200
    body = again.json()
    assert body["restaurants_run"] == 0 and body["restaurants_already_done"] == 1
    assert body["invoices_processed"] == first["invoices_processed"]   # earlier counts reported
    assert len(only_state()["activity"]) == activity, "a repeated key must not write anything"
    assert len(owner.get("/api/state").json()["invoices"]) == 3


def test_new_run_key_reprocesses_but_never_double_counts_invoices():
    owner = one_restaurant()
    nightly("nightly-2026-11-08")
    body = nightly("manual-test-1").json()
    assert body["restaurants_run"] == 1
    assert body["invoices_processed"] == 0 and body["duplicates_skipped"] == 4
    assert len(owner.get("/api/state").json()["invoices"]) == 3


def test_overlapping_run_gets_409(monkeypatch):
    class Busy:
        def locked(self):
            return True
    monkeypatch.setattr(api, "NIGHTLY_LOCK", Busy())
    r = nightly("nightly-2026-11-08")
    assert r.status_code == 409 and r.json()["error"] == "already_running"


def test_processing_errors_fail_the_run(monkeypatch):
    one_restaurant()
    monkeypatch.setattr(engine, "process_invoice", lambda *a, **k: {"error": "could_not_read"})
    r = nightly("nightly-2026-11-08")
    assert r.status_code == 500
    body = r.json()
    assert not body["ok"] and body["errors"] == 4
    assert body["results"][0]["error_codes"] == {"could_not_read": 4}


class FakeStore:
    def __init__(self, broken=()):
        self.states = {"r-ok-0001": engine.new_state(), "r-bad-0002": engine.new_state()}
        self.broken, self.saves = set(broken), []

    async def all_restaurants(self):
        return list(self.states)

    async def load(self, rid):
        if rid in self.broken:
            raise ConnectionError("database unavailable")
        return self.states[rid], {"activity": len(self.states[rid]["activity"])}

    async def save(self, rid, state, meta):
        self.saves.append(rid)


def test_supabase_mode_one_failure_fails_job_but_others_still_run(monkeypatch):
    store = FakeStore(broken={"r-bad-0002"})
    monkeypatch.setattr(api, "STORE", store)
    r = nightly("nightly-2026-11-08")
    assert r.status_code == 500
    body = r.json()
    assert body["restaurants"] == 2 and body["restaurants_run"] == 1 and body["restaurants_failed"] == 1
    assert store.saves == ["r-ok-0001"]
    bad = next(x for x in body["results"] if x["restaurant"] == "r-bad-0002")
    assert bad["failure"] == "ConnectionError" and "database unavailable" not in r.text

    # retry with the same key: the finished restaurant is reported, not re-run or re-saved
    store.broken.clear()
    body = nightly("nightly-2026-11-08").json()
    assert body["ok"] and body["restaurants_run"] == 1 and body["restaurants_already_done"] == 1
    assert store.saves == ["r-ok-0001", "r-bad-0002"]


def test_demo_button_unchanged():
    view = TestClient(api.app).post("/api/run").json()["view"]
    assert view["has_run"] and len(view["invoices"]) == 3


# ------------------------------------------------------------------ GitHub Actions client

ENV = {"NIGHTSHIFT_URL": "https://night-shift.example.com/", "CRON_SECRET": SECRET, "RUN_KEY": ""}
OK_BODY = {"ok": True, "restaurants": 2, "restaurants_run": 2, "restaurants_already_done": 0, "restaurants_failed": 0,
           "invoices_processed": 6, "duplicates_skipped": 2, "possible_corrections": 0, "review_holds": 2, "errors": 0,
           "results": [{"restaurant": "abc", "ok": True}, {"restaurant": "def", "ok": True}]}


class FakeHttp:
    """Replies from a queue per path (the last reply repeats); records each call."""

    def __init__(self, posts, health=((200, b"{}"),)):
        self.queues = {"/api/health": list(health), "/api/nightly-run": list(posts)}
        self.calls = []

    def __call__(self, method, url, headers=None, timeout=30):
        path = url.split(".com", 1)[1]
        self.calls.append((method, path, dict(headers or {})))
        queue = self.queues[path]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return status, body if isinstance(body, bytes) else json.dumps(body).encode()


def run_client(http, tmp_path, env=None):
    summary = tmp_path / "summary.md"
    summary.unlink(missing_ok=True)
    code = nightly_client.main({**ENV, **(env or {}), "GITHUB_STEP_SUMMARY": str(summary)},
                               http=http, sleep=lambda s: None, clock=lambda: "2026-11-08T03:30:00-05:00")
    return code, summary.read_text() if summary.exists() else ""


def test_client_success(tmp_path, capsys):
    http = FakeHttp([(200, OK_BODY)])
    code, summary = run_client(http, tmp_path)
    out = capsys.readouterr().out
    assert code == 0
    for text in ("Started:", "Completed:", "Invoices processed: 6", "Duplicates skipped: 2", "Review holds: 2",
                 "Errors: 0", "Result: OK"):
        assert text in out and text in summary
    post = next(c for c in http.calls if c[1] == "/api/nightly-run")
    assert post[0] == "POST" and post[2]["X-Cron-Secret"] == SECRET
    assert post[2]["X-Run-Key"].startswith("nightly-20")
    assert SECRET not in out and "night-shift.example" not in out and SECRET not in summary


def test_client_fails_on_server_errors(tmp_path, capsys):
    body = {**OK_BODY, "ok": False, "errors": 1,
            "results": [{"restaurant": "abcdef1234567", "ok": False, "error_codes": {"could_not_read": 1}}]}
    code, _ = run_client(FakeHttp([(500, body)]), tmp_path)
    out = capsys.readouterr().out
    assert code == 1 and "could_not_read x1" in out and "::error" in out and "Result: FAILED" in out


@pytest.mark.parametrize("status,message", [(403, "CRON_SECRET does not match"), (404, "check NIGHTSHIFT_URL")])
def test_client_auth_and_url_errors(tmp_path, capsys, status, message):
    code, _ = run_client(FakeHttp([(status, b"<html>secret page</html>")]), tmp_path)
    out = capsys.readouterr().out
    assert code == 1 and message in out and "secret page" not in out


def test_client_retries_network_errors_with_same_key(tmp_path):
    http = FakeHttp([TimeoutError("timed out"), (502, b"bad gateway"), (200, OK_BODY)])
    code, _ = run_client(http, tmp_path, {"RUN_KEY": "nightly-2026-11-08"})
    posts = [c for c in http.calls if c[1] == "/api/nightly-run"]
    assert code == 0 and len(posts) == 3
    assert {c[2]["X-Run-Key"] for c in posts} == {"nightly-2026-11-08"}


def test_client_waits_for_a_run_in_progress(tmp_path):
    http = FakeHttp([(409, {"ok": False, "error": "already_running"}), (200, OK_BODY)])
    assert run_client(http, tmp_path)[0] == 0


def test_client_gives_up_after_repeated_gateway_errors(tmp_path, capsys):
    code, _ = run_client(FakeHttp([(503, b"")]), tmp_path)
    assert code == 1 and "kept answering HTTP 503" in capsys.readouterr().out


def test_client_fails_when_service_never_wakes(tmp_path, capsys):
    http = FakeHttp([(200, OK_BODY)], health=[ConnectionRefusedError()])
    code, _ = run_client(http, tmp_path)
    assert code == 1 and "did not respond" in capsys.readouterr().out
    assert not any(c[1] == "/api/nightly-run" for c in http.calls)


def test_client_rejects_unexpected_response(tmp_path):
    assert run_client(FakeHttp([(200, b"not json")]), tmp_path)[0] == 1


@pytest.mark.parametrize("env", [{"CRON_SECRET": ""}, {"NIGHTSHIFT_URL": ""}, {"NIGHTSHIFT_URL": "http://evil.example.com"},
                                 {"RUN_KEY": "bad key"}])
def test_client_config_errors(tmp_path, env):
    http = FakeHttp([(200, OK_BODY)])
    assert run_client(http, tmp_path, env)[0] == 1 and http.calls == []


def test_default_run_key_uses_new_york_date():
    # 03:30 EST on Nov 8 is 08:30 UTC; 04:30 UTC on Nov 8 is still Nov 7 in New York
    assert nightly_client.default_run_key(datetime(2026, 11, 8, 8, 30, tzinfo=timezone.utc)) == "nightly-2026-11-08"
    assert nightly_client.default_run_key(datetime(2026, 11, 8, 4, 30, tzinfo=timezone.utc)) == "nightly-2026-11-07"


def test_client_end_to_end_against_the_real_endpoint(tmp_path):
    """The client and the server agree on headers and fields."""
    one_restaurant()
    app = TestClient(api.app)

    def http(method, url, headers=None, timeout=30):
        path = url.split(".com", 1)[1]
        r = app.get(path) if method == "GET" else app.post(path, headers=headers)
        return r.status_code, r.content

    code, summary = run_client(http, tmp_path, {"RUN_KEY": "nightly-2026-11-08"})
    assert code == 0 and "Invoices processed: 3" in summary and "Duplicates skipped: 1" in summary
    code, summary = run_client(http, tmp_path, {"RUN_KEY": "nightly-2026-11-08"})
    assert code == 0 and "already done for this key 1" in summary
