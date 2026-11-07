# Scheduled nightly run

Every night at **3:30 AM America/New_York**, GitHub Actions starts Night Shift's overnight invoice run for
every restaurant. This page covers how it works, the secrets it needs, how to turn it on and test it, and how
to check the results in Supabase.

## How it works

```
GitHub Actions (.github/workflows/nightly.yml)
  1. gate: is it 3:30 AM in New York for the schedule that fired?   (two UTC crons, one per DST offset)
  2. python3 scripts/nightly_client.py        (standard library only, no pip install)
       GET  /api/health                         wake Render's free instance (retries while it boots)
       POST /api/nightly-run                    X-Cron-Secret: <CRON_SECRET>
                                                X-Run-Key:     nightly-<New York date>
  3. prints a counts-only summary (also on the run's Summary page); exit 1 = job failed

Render (api.py → engine.py, unchanged engine code)
  for each restaurant (Supabase): load → engine.run_night_shift → save   (one transaction per restaurant)
```

**Why it calls the endpoint instead of running the code on the GitHub runner.** The endpoint already
existed (it is what the previous 11:40 PM workflow called) and it runs the code that is deployed. The
Supabase service-role key and the OpenRouter key stay on Render, so GitHub only holds a URL and a shared
secret. The per-restaurant lock that keeps the nightly run from racing an owner's request in the app also
only exists inside the server process.

**What the run does:** it is the same as pressing **Run Night Shift**, using real time instead of the demo
clock. It reads the inbox, skips invoices that were already counted, checks totals and pack sizes, holds
unclear lines as *Needs your input*, recalculates every dish and prepares the Morning Brief. Price changes
stay **proposed**: nothing is approved, and nothing is ever published to DoorDash. It never runs **Review
my options** or **Investigate this alert**; those stay owner-triggered. The invoice cache (by file hash), the
saved readings for demo invoices, the AI rate limit and every calculation are unchanged.

## Protection against duplicates and overlap

| Risk | Protection |
|---|---|
| Two workflow runs at once (schedule + manual click) | `concurrency: night-shift-nightly-run`. The second run waits; a running job is never cancelled. |
| Two calls reaching the server at once | A server-side lock. The second call gets **409**, and the client waits (up to 10 × 30 s), then reports the result. |
| A retry or a second trigger on the same night | **Run key** (`nightly-YYYY-MM-DD`, New York date). A restaurant that already *completed* a run with that key is not run again; the endpoint returns that run's saved counts. |
| Both UTC schedules firing on the same day | The gate step only lets the schedule matching New York's current UTC offset continue. The run key covers it anyway. |
| The same invoice counted twice | Already enforced by the engine: same supplier + number + contents = duplicate, skipped. A different version of the same number becomes a *possible correction* for the owner. The database also has `unique (restaurant_id, fingerprint)`. |
| A half-finished run | Each restaurant is saved in one transaction, after its run ends. A crash saves nothing, so the retry runs that restaurant again. |

The client retries the POST only when the request never reached the app (network error, timeout, or
HTTP 502/503/504 from Render's proxy while it wakes), always with the same run key, so a retry cannot
redo a finished night.

## When the job fails (red ❌)

| What the log says | Meaning / fix |
|---|---|
| `Missing NIGHTSHIFT_URL and/or CRON_SECRET` | Add the repository secrets (below). |
| `Forbidden: CRON_SECRET does not match…` | The GitHub secret and Render's `CRON_SECRET` differ, or Render has none. |
| `Not found: check NIGHTSHIFT_URL` | Wrong URL (it must be the base URL, without `/api/...`). |
| `The service did not respond to /api/health` | Render is down or still deploying. Re-run the workflow. |
| `Problem in restaurant <id>: <ExceptionName>` | Loading or saving that restaurant failed (e.g. Supabase unavailable). The other restaurants still ran; re-running with the same run key runs only the failed one. |
| `Problem in restaurant <id>: could_not_read x1` (or `rate_limited`, `ai_not_configured`) | An inbox file could not be processed. Everything else was saved. That night is now recorded as done, so to retry those files, run manually with a **new** run key: invoices already counted are skipped as duplicates. |

The log holds counts, error codes, exception class names and restaurant ids only. It never contains the
secret, the URL, the raw response, supplier names, invoice numbers, amounts or lines.

## Required GitHub secrets

Repository → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret | Value |
|---|---|
| `NIGHTSHIFT_URL` | `https://night-shift-r237.onrender.com` |
| `CRON_SECRET` | The **same** long random value as `CRON_SECRET` in Render → Environment (`openssl rand -hex 32`) |

Nothing else is needed on GitHub. Supabase and OpenRouter keys stay on Render.

## Enable it

1. Render → your service → **Environment**: make sure `CRON_SECRET` is set (and the `SUPABASE_*` values).
   If you add or change it, Render redeploys.
2. GitHub: add the two secrets above.
3. Merge the branch with this workflow into **`main`**. GitHub only runs scheduled workflows from the
   default branch, and **Run workflow** only appears once the file is on `main`.
4. Repository → **Actions**: if Actions are disabled, enable them. If "Nightly run" shows *disabled*, click
   **Enable workflow**. (GitHub disables scheduled workflows after 60 days without repository activity.)

## Test it

**Locally, before merging** (local demo mode, no Supabase needed):

```bash
CRON_SECRET=local-test python api.py          # terminal 1
# open http://localhost:8000 once: local mode only runs visitor sandboxes that exist
NIGHTSHIFT_URL=http://localhost:8000 CRON_SECRET=local-test RUN_KEY=local-1 \
  python3 scripts/nightly_client.py           # terminal 2: exit 0, "Invoices processed: 3"
NIGHTSHIFT_URL=http://localhost:8000 CRON_SECRET=local-test RUN_KEY=local-1 \
  python3 scripts/nightly_client.py           # again: "already done for this key 1", nothing re-run
python -m pytest -q tests/test_nightly.py     # automated checks (no network)
```

**On GitHub, after merging:**

1. Actions → **Nightly run** → **Run workflow** (branch `main`). Leave *run_key* empty to run tonight's
   key (`nightly-<today's New York date>`), or type e.g. `manual-test-1` to force a separate run without
   using up tonight's key.
2. Open the run → the **Summary** page. Expect something like:

   ```
   Run key: manual-test-1
   Started: 2026-11-08T10:02:11-05:00
   Completed: 2026-11-08T10:02:19-05:00
   Restaurants: 2 (run now 2, already done for this key 0, failed 0)
   Invoices processed: 0
   Duplicates skipped: 8
   Possible corrections (owner chooses): 0
   Review holds: 0
   Errors: 0
   Result: OK
   ```

   On the demo inbox, a restaurant that already ran sees every file as a duplicate. A fresh restaurant
   reports 3 processed, 1 duplicate skipped and at least 1 review hold (the rice paper line).
3. Click **Run workflow** again with the same run key: it should report `already done for this key` and
   change nothing.
4. The next morning, check that the 3:30 AM run is green. One of the two scheduled jobs logs "the other one
   runs" and does nothing; that is expected.

## Verify the results in Supabase

Supabase → **SQL Editor** (it runs as the database owner, so RLS does not hide rows):

```sql
-- Completed scheduled runs, newest first, with their counts
select restaurant_id, at, evidence->'params'->>'run_key' as run_key,
       evidence->'params'->'summary'          as summary
from public.activity_log
where evidence->>'kind' = 'brief_ready' and evidence->'params' ? 'run_key'
order by at desc
limit 20;

-- Each night ran at most once per restaurant (expect no rows)
select restaurant_id, evidence->'params'->>'run_key' as run_key, count(*)
from public.activity_log
where evidence->>'kind' = 'brief_ready' and evidence->'params' ? 'run_key'
group by 1, 2
having count(*) > 1;

-- No invoice counted twice (expect no rows)
select restaurant_id, fingerprint, count(*)
from public.invoices
where fingerprint is not null
group by 1, 2
having count(*) > 1;

-- Duplicates skipped in the last day
select restaurant_id, at, evidence->'params'->>'invoice_no' as invoice_no
from public.activity_log
where evidence->>'kind' = 'duplicate_skipped' and at > now() - interval '1 day'
order by at desc;

-- Lines waiting for the owner (review holds)
select restaurant_id, invoice_local_id, line_no, ingredient_key, reasons
from public.invoice_lines
where needs_review
order by restaurant_id, invoice_local_id, line_no;
```

Every entry from one run shares a `run_id` in `activity_log`. In the app, the owner sees the same run
under **While You Slept**.

## Limits

- The server-side lock is per process. Render runs one instance on this plan; with several instances,
  the workflow's concurrency group and the run key still prevent duplicate runs.
- GitHub may start scheduled jobs late (usually minutes). The gate checks which schedule fired, not the
  exact minute, so a late start still runs once.
- The inbox is the fixed demo set (`demo-data/inbox/`). There is no supplier email or upload inbox yet.
- New (non-demo) inbox files would share the existing limit of 10 AI readings per hour, with
  `unknown` as the client key. Demo files never call the AI.
