#!/usr/bin/env python3
"""Entry point for the scheduled Night Shift run (.github/workflows/nightly.yml). Standard library only.

It does not process anything itself: it wakes the Render service and calls the existing authenticated
endpoint POST /api/nightly-run, which runs the same engine code as the app (invoice cache, duplicate
checks, holds, rate limits and calculations unchanged). It never calls the AI decision review or the
investigator, and it never approves anything.

Environment:
    NIGHTSHIFT_URL   the Render URL, e.g. https://night-shift-r237.onrender.com   (required)
    CRON_SECRET      same value as CRON_SECRET on Render                          (required)
    RUN_KEY          optional; default "nightly-<New York date>". A restaurant that already completed a
                     run with this key is not run again (retries and repeated triggers are safe).

Exit status: 0 when every restaurant was processed with no errors, 1 otherwise.
Output: counts only. The secret, the URL, the raw response and invoice contents are never printed.
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
COUNTS = ("invoices_processed", "duplicates_skipped", "possible_corrections", "review_holds", "errors")
LABELS = {"invoices_processed": "Invoices processed", "duplicates_skipped": "Duplicates skipped",
          "possible_corrections": "Possible corrections (owner chooses)", "review_holds": "Review holds",
          "errors": "Errors"}
RUN_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
CODE = re.compile(r"^[A-Za-z_]{1,60}$")
GATEWAY = {502, 503, 504}   # Render's proxy while the service wakes: the app never saw the request

WAKE_TRIES, WAKE_WAIT, WAKE_TIMEOUT = 6, 20, 120
RUN_TRIES, RUN_WAIT, RUN_TIMEOUT = 3, 30, 600
BUSY_TRIES, BUSY_WAIT = 10, 30   # 409: a run is in progress; wait for it, then report its counts


class Failure(Exception):
    pass


def send(method, url, headers=None, timeout=30):
    """(status, body bytes). Network problems raise OSError (URLError and timeouts are OSErrors)."""
    request = urllib.request.Request(url, method=method, headers=headers or {},
                                     data=b"" if method == "POST" else None)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def default_run_key(now=None):
    return "nightly-" + (now or datetime.now(NY)).astimezone(NY).date().isoformat()


def wake(base, http, sleep):
    for attempt in range(1, WAKE_TRIES + 1):
        try:
            status, _ = http("GET", f"{base}/api/health", timeout=WAKE_TIMEOUT)
            if status == 200:
                return
            reason = f"HTTP {status}"
        except OSError as error:
            reason = type(error).__name__
        print(f"Waking the service: attempt {attempt}/{WAKE_TRIES} failed ({reason}).")
        if attempt < WAKE_TRIES:
            sleep(WAKE_WAIT)
    raise Failure("The service did not respond to /api/health.")


def call_run(base, secret, run_key, http, sleep):
    """POST /api/nightly-run. Retrying is safe: the run key makes a second call report, not redo."""
    headers = {"X-Cron-Secret": secret, "X-Run-Key": run_key, "Accept": "application/json"}
    network_tries = busy_tries = 0
    while True:
        try:
            status, body = http("POST", f"{base}/api/nightly-run", headers=headers, timeout=RUN_TIMEOUT)
        except OSError as error:
            network_tries += 1
            if network_tries >= RUN_TRIES:
                raise Failure(f"Could not reach /api/nightly-run ({type(error).__name__}).")
            print(f"Network problem ({type(error).__name__}); retrying with the same run key.")
            sleep(RUN_WAIT)
            continue
        if status in GATEWAY:
            network_tries += 1
            if network_tries >= RUN_TRIES:
                raise Failure(f"/api/nightly-run kept answering HTTP {status}.")
            print(f"HTTP {status} from the host; retrying with the same run key.")
            sleep(RUN_WAIT)
            continue
        if status == 409:
            busy_tries += 1
            if busy_tries >= BUSY_TRIES:
                raise Failure("Another run was still in progress; gave up waiting.")
            print("Another run is in progress; waiting for it to finish.")
            sleep(BUSY_WAIT)
            continue
        if status == 403:
            raise Failure("Forbidden: CRON_SECRET does not match the CRON_SECRET set on Render.")
        if status == 404:
            raise Failure("Not found: check NIGHTSHIFT_URL (it should be the Render service's base URL).")
        try:
            data = json.loads(body or b"{}")
        except ValueError:
            data = None
        if not isinstance(data, dict) or "restaurants" not in data:
            raise Failure(f"Unexpected response from /api/nightly-run (HTTP {status}).")
        return status, data


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def report(status, data, run_key, started, completed):
    """Counts-only summary lines; returns (lines, ok)."""
    results = data.get("results") if isinstance(data.get("results"), list) else []
    failed = [r for r in results if isinstance(r, dict) and not r.get("ok")]
    ok = status == 200 and data.get("ok") is True and not failed and _int(data.get("errors")) == 0
    lines = [
        f"Run key: {run_key}",
        f"Started: {started}",
        f"Completed: {completed}",
        f"Restaurants: {_int(data.get('restaurants'))} "
        f"(run now {_int(data.get('restaurants_run'))}, already done for this key "
        f"{_int(data.get('restaurants_already_done'))}, failed {_int(data.get('restaurants_failed'))})",
        *(f"{LABELS[k]}: {_int(data.get(k))}" for k in COUNTS),
    ]
    for r in failed:
        what = r.get("failure") if CODE.match(str(r.get("failure", ""))) else None
        codes = r.get("error_codes") if isinstance(r.get("error_codes"), dict) else {}
        codes = ", ".join(f"{c} x{_int(n)}" for c, n in sorted(codes.items()) if CODE.match(str(c)))
        rid = re.sub(r"[^A-Za-z0-9-]", "", str(r.get("restaurant", "")))[:8] or "?"
        lines.append(f"Problem in restaurant {rid}: {what or codes or 'unknown error'}")
    lines.append("Result: OK" if ok else f"Result: FAILED (HTTP {status})")
    return lines, ok


def main(env=None, http=send, sleep=time.sleep, clock=None):
    env = os.environ if env is None else env
    clock = clock or (lambda: datetime.now(NY).replace(microsecond=0).isoformat())
    base = (env.get("NIGHTSHIFT_URL") or "").strip().rstrip("/")
    secret = env.get("CRON_SECRET") or ""
    run_key = (env.get("RUN_KEY") or "").strip() or default_run_key()
    started = clock()
    try:
        if not base or not secret:
            raise Failure("Missing NIGHTSHIFT_URL and/or CRON_SECRET (set them as repository secrets).")
        if not (base.startswith("https://") or re.match(r"^http://(localhost|127\.0\.0\.1)(:\d+)?(/|$)", base)):
            raise Failure("NIGHTSHIFT_URL must start with https://.")
        if not RUN_KEY.match(run_key):
            raise Failure("RUN_KEY may only use letters, digits, '.', '_', ':' and '-' (max 64).")
        print(f"Night Shift scheduled run started {started} (run key {run_key}).")
        wake(base, http, sleep)
        status, data = call_run(base, secret, run_key, http, sleep)
        lines, ok = report(status, data, run_key, started, clock())
    except Failure as error:
        lines, ok = [f"Run key: {run_key}", f"Started: {started}", f"Completed: {clock()}",
                     f"Error: {error}", "Result: FAILED"], False
    for line in lines:
        print(line)
    if not ok:
        print("::error title=Night Shift nightly run failed::" + lines[-2 if lines[-1] == "Result: FAILED" else -1])
    summary_file = env.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as fh:
            fh.write("### Night Shift nightly run\n\n" + "\n".join(f"- {line}" for line in lines) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
