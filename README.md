# Night Shift 🌙

**Live demo:** https://YOUR-SERVICE.onrender.com  *(replace after the first Render deploy)*

An overnight back office for small restaurants (DoorDash "Back House" track). While the owner
sleeps, Night Shift reads tonight's supplier invoices, checks them (totals, pack sizes, duplicates),
recalculates every dish, and has a plain-language Morning Brief ready in English or Spanish.
Every number can show where it came from.

> **All data is fictional.** "Pho Nightingale", its suppliers (Rivermark Meats, Greenleaf Produce
> Supply, Lotus Pantry Wholesale), invoices, prices and order history are invented for this demo
> (`demo-data/`). Any resemblance to real businesses is coincidental.

## What's real vs. simulated

| Real (running code) | Simulated / out of scope |
|---|---|
| Cost math: pack size, unit conversion, yield, DoorDash fee, packaging, margin (`margins.py`), tested against `demo-data/expected_results.json` | The restaurant, suppliers, invoices, prices and 90 days of orders |
| Invoice checks: totals vs. line sums, pack-size parsing, duplicate detection (supplier + number + total), "Needs review" holds | "Overnight": you press **Run Night Shift**; the log uses a fixed overnight clock so every demo is identical |
| AI invoice reading for **new** uploads (OpenRouter vision model), cached by file hash | Demo invoices are never sent to the AI: their known reading is in `invoices_extracted_fallback.json` |
| Option comparison (keep / suggested / your price / your limit) and order-volume what-ifs (`options.py`) | Order-volume cases are hypothetical: there is no demand or price-elasticity data |
| Optional AI decision review, one owner-triggered call, strictly validated (`review.py`) | No prepared or canned reviews: without a key the app says the review is unavailable |
| Monthly forecast from order history (last 28 days ÷ 28 × 30.4) | Price scenarios assume unchanged order volume (labelled as such) |
| Decision log, bookkeeper CSV export, per-visitor sandboxes | **No DoorDash connection.** Approving saves a decision; it never publishes a price |

Labor and overhead are not included in any figure (the app says so).

## Where AI is used (and where it isn't)

There are **two** AI calls, both through OpenRouter with the same key (`OPENROUTER_API_KEY`) and model
(`OPENROUTER_MODEL`, default `anthropic/claude-sonnet-5.5`). There are no agents, no loops, no background calls.

| Call | When | Purpose | Cached | If unavailable |
|---|---|---|---|---|
| `llm.extract_invoice()` | A **new** invoice image/PDF is uploaded (`engine.process_invoice`) | Read supplier, number, date, total and each line into JSON | On disk (`llm_cache.json`) by file hash; demo invoices never call it | Friendly error; nothing is counted |
| `llm.review_decision()` | The owner presses **Get an AI decision review** | Explain the options the code calculated, against the owner's limit and note | In memory, per restaurant/session, keyed by snapshot version + owner input + language + model + prompt version | "AI review isn't available"; the full comparison and all buttons keep working |

**Deterministic code, always:** matching invoice lines, parsing pack sizes, unit costs and yields, totals
and duplicate checks, holds, every dish calculation, statuses, the suggested price, the option comparison,
order-volume what-ifs, monthly effects, the report, and every saved owner decision.

**What the review may and may not do** (enforced in `review.validate`, not just asked for in the prompt):
- It only sees the code's snapshot (`options.snapshot`): cost records with their invoice lines, the
  comparison baseline, recipe and yields, fees, target, holds, options with stable ids, order-volume
  assumption, allowed actions, and the owner's limit and note (marked as unverified, untrusted text).
- Its suggested option must be one the code offered and the owner's limit allows; every point must cite
  evidence ids from the snapshot; any `$` or `%` in its text must already exist in the snapshot; if the
  limit conflicts with the target, it must say so. Anything else → rejected, shown as unavailable.
- Figures shown next to the review come from the snapshot, never from the model.
- It cannot approve, change a price, resolve an invoice hold, change a menu, or publish anything.
  The review route is read-only (it never saves state) and holds no lock while waiting for the model;
  afterwards it re-checks the snapshot and **discards** an answer written for numbers that have changed.
- A dish with an unconfirmed invoice input (e.g. rice paper with no pack size) gets **no** pricing review.
- Limits: 25 s timeout, 900 output tokens, no retries, 10 reviews per IP per hour (a separate bucket from
  the 10 invoice readings per IP per hour, which are unchanged).
- Validation checks references, not truth. Manual evaluation cases: `docs/decision-review-eval.md`.

**Provenance shown in the app:** invoices say "Read by AI just now" or "Replayed from saved reading";
reviews say "Generated just now · model" or "Saved review from <time>". These are independent: a
replayed invoice can have a live review.

## Comparison baseline

"Before" always means **prices before tonight's run** (or your saved prices if Night Shift hasn't run).
The current cost of each ingredient is the latest verified invoice line. If an ingredient changed twice
(e.g. RM-20419 at $134.20, then NB-7731 at $140.00), the earlier invoice is shown as history, never as the
current price. The brief, the dish card, the supplier panel, popovers, Dish Detail and the review all read
the same cost record (`engine.cost_record`).

## Run locally

```bash
cp .env.example .env            # optional: add OPENROUTER_API_KEY to read new invoices with AI
pip install -r requirements.txt
npm --prefix web ci && npm --prefix web run build
python api.py                    # http://localhost:8000  (uses $PORT if set)
```

With Docker (same image Render builds):

```bash
docker build -t night-shift . && docker run -p 8000:8000 -e PORT=8000 --env-file .env night-shift
```

Reset: **Reset demo** in the app (or `POST /api/reset`) gives you a fresh copy of the demo restaurant.

Tests (numbers vs. `expected_results.json`, sad paths, sandboxing, upload guards, options, AI review guards):

```bash
python -m pytest -q tests      # or: python tests/test_expected_results.py
```

## Production architecture (Render + Supabase)

- **One Docker service on Render** (free): FastAPI serves `/api/*` and the built React app at `/`.
- **Supabase Postgres** holds every restaurant's data (`supabase/migrations/`). Every table has
  `restaurant_id` and `created_at`; **RLS is on with no policies**, and the browser roles have no grants,
  so only the backend (service-role key) can read or write. Each request loads the user's restaurant with
  one SQL function (`get_restaurant_state`) and saves changes with another (`save_restaurant_state`).
- **Supabase Auth**: the browser uses the anon key only to sign in ("Try the demo" = anonymous sign-in,
  or an email magic link). The backend verifies the access token on every `/api` request (JWKS) and
  scopes everything to that user's restaurant. First sign-in calls `create_demo_restaurant(user_id)`,
  which copies the demo template (generated from `demo-data/` by `scripts/build_seed_sql.py`).
  **Reset demo** deletes the user's restaurant and files and reseeds.
- **Supabase Storage**: private bucket `invoices`; the backend uploads files and hands the browser
  5-minute signed URLs.
- **Nightly run**: `POST /api/nightly-run` with header `X-Cron-Secret`, called by
  `.github/workflows/nightly.yml` at 11:40 PM New York time. It runs every restaurant; invoices already
  counted are skipped as duplicates (the demo inbox is the same file set every night).
- **Without Supabase variables** the app runs in local demo mode (no sign-in, in-memory sandboxes).
- **Cost protection**: demo invoices never call the AI (matched by file hash); new uploads are images or
  PDF, at most 5 MB, at most 10 AI readings per IP per hour.

## Overnight scheduling (what actually exists)

- **Production:** `.github/workflows/nightly.yml` calls `POST /api/nightly-run` (header `X-Cron-Secret`)
  at 11:40 PM New York time, for every restaurant. It only runs once the repo secrets `NIGHTSHIFT_URL`
  and `CRON_SECRET` are set; it can also be started by hand (Actions → "Nightly run" → Run workflow).
  It re-reads the same demo inbox, so already-counted invoices are skipped as duplicates.
- **Demo / local mode:** there is no background scheduler. The owner (or presenter) presses
  **Run Night Shift on tonight's inbox**; the log uses a fixed overnight clock (11:38 PM–6:55 AM) so every
  demo reads the same.

## 5-minute demo

Before: `python api.py`, open the app, **Reset demo**. With `OPENROUTER_API_KEY` set, the AI reads
the NB-7731 photo and writes the review live; without it, steps 1:00 and 3:00 show the honest
"unavailable" path (both are worth showing).

| Time | Do | Show |
|---|---|---|
| 0:00 | **Run Night Shift on tonight's inbox** → While You Slept | 3 invoices verified with evidence, 1 duplicate skipped, rice paper *Needs your input*, Brisket Pho *Proposed, not applied* |
| 1:00 | Invoice Review → upload `test_invoice_northbank_NB-7731.png` (fresh invoice) | "Read by AI just now"; 2 × 20 lb at $140 = $280 matches the total; $7.00/lb, $10.00 usable/lb at 70% yield |
| 1:40 | Morning Brief → Brisket Pho | **What changed**: $119.80 → $140.00 per 20 lb (↑ 16.9% vs. before tonight's run), current from NB-7731; RM-20419 $134.20 shown as historical. Left per order $6.36 → $5.84 (36.5%, target 38%) |
| 2:20 | **Review my options** → largest increase `0.50`, note "I can raise the price by at most fifty cents, and I want to preserve the portion." | Option cards: keep $15.99 (36.5%), suggested $16.99 (38.8%, above your limit), your limit $16.49 (37.7%, below target); conflict notice; what-if table (orders unchanged / 5% / 10% fewer) and "about 6% fewer orders would erase the improvement", labelled hypothetical |
| 3:00 | **Get an AI decision review** | Suggested option with figures from code, cost / customer / data points each linked to evidence, "You said" on the note, one question. Point out: "This review changed nothing." (No key → the unavailable message; the comparison stays.) |
| 3:40 | **Change price** → 16.49 → **Approve your price** | Labelled "Your price scenario … below your target (37.7%)"; decision log card; "Update this price in DoorDash Merchant Portal" (the real next step; Night Shift never publishes) |
| 4:15 | Spring Rolls (missing rice-paper pack size) | Hold + previous cost disclosed; "Options wait for your confirmation"; no AI pricing review. Invoice Review → fix line → 10 packs × 50 sheets → Spring Rolls back to OK |
| 4:45 | Refresh the page | Decision and log are still there; switch to **Español** to show the same flow |

## How the math works (`margins.py`)

```
cost per serving   = qty per serving × pack price ÷ pack size ÷ yield
                     brisket: 0.35 lb × $134.20 ÷ 20 lb ÷ 70% = $3.35
amount left        = DoorDash price − DoorDash fee (25%) − packaging ($0.50) − ingredients
                     $15.99 − $4.00 − $0.50 − $5.51 = $5.99   (37.4%; target 38%)
scenario           = smallest whole-dollar increase that reaches the target → $16.99
change per order   = +$1 × (1 − 25%) = +$0.75
monthly scenario   = $0.75 × 225 forecast orders = $168.75 ≈ ~$169
```

Math uses exact values and rounds to the cent only for display, so a displayed line can differ
from a displayed total by 1¢ (noted in the UI). This matches `expected_results.json`.

## Files

| Path | Job |
|---|---|
| `data.py` | Loads `demo-data/` at start-up; parses pack sizes and matches invoice lines to ingredients (code, not AI). |
| `margins.py` | All calculations. |
| `llm.py` | The two AI calls: read a new invoice image/PDF into structured lines; the optional decision review. Never calculates. |
| `engine.py` | Invoice checks, holds, corrections, cost records, scenarios, decision log, report, sessions, rate limit. |
| `options.py` | The decision snapshot: options with stable ids, order-volume what-ifs, evidence registry, allowed actions. No AI. |
| `review.py` | AI decision review: prompt, strict validation, scoped cache, its own rate limit. |
| `api.py` | FastAPI: `/api/*` + the built app; auth middleware; upload guards; `/api/health`, `/api/config`, `/api/nightly-run`. |
| `config.py` | Reads the six environment variables (secrets are never printed). |
| `auth.py` | Verifies Supabase access tokens (JWKS; legacy HS256 via Supabase Auth). |
| `store.py` | Supabase persistence (2 RPCs per request) and the private Storage bucket. |
| `supabase/migrations/` | Schema + RLS, server-side functions, demo template seed, storage bucket. |
| `web/` | React + Vite + TypeScript UI (English/Spanish, WCAG 2.2 AA). |
| `tests/` | Checks against `expected_results.json`; options, labels and the AI review with a stubbed provider. |
| `docs/decision-review-eval.md` | Manual evaluation cases for the live AI review. |
| `Dockerfile` | Stage 1 builds `web/` with Node; stage 2 runs it all on slim Python. |

## How this was built

Built during a hackathon with AI coding assistance (Claude Code). The developer directed the
product, reviewed the output, and tested the app; the AI wrote much of the code under that direction.

## Limitations

- All data is fictional; there is no DoorDash or supplier connection. Approving saves a decision only.
- Figures exclude labor and overhead. Monthly figures assume the forecast order volume; the what-if
  cases are thresholds, not demand forecasts. There is no customer, competitor or supplier-quote data.
- The AI review's guards check structure, references and figures, not that every sentence is right.
  Reviews are cached in memory (lost on restart); the owner's limit and note are not saved.
- "Before" is the price before the latest run; a decision made against an older baseline is not re-based.

## Setup checklist

### 1. Supabase dashboard
1. **Create a project** (supabase.com → New project). Save the database password somewhere safe.
2. **Run the migrations**, in order: either `supabase link --project-ref <ref>` then `supabase db push`,
   or SQL Editor → paste and run each file in `supabase/migrations/` in filename order
   (`…001_schema`, `…002_functions`, `…003_seed_demo_template`, `…004_storage`).
3. **Check the result**: Table Editor shows 11 tables, each marked "RLS enabled" with no policies;
   `restaurants` has one row with `is_template = true`.
4. **Enable anonymous sign-ins**: Authentication → Sign In / Providers → "Allow anonymous sign-ins" → on.
5. **Email (magic link)**: Authentication → Sign In / Providers → Email → enabled. The built-in mailer is
   rate-limited, so for real use add your own SMTP (Authentication → Emails → SMTP settings).
6. **Redirect URLs**: Authentication → URL Configuration → Site URL = your Render URL
   (`https://YOUR-SERVICE.onrender.com`); add it (and `http://localhost:8000` for local tests) to Redirect URLs.
7. **Storage bucket**: Storage → confirm a **private** bucket named `invoices` exists (migration 004 creates
   it; if not, New bucket → name `invoices`, Public off, 5 MB limit, allowed types image/png, image/jpeg,
   image/webp, application/pdf). Add **no** policies.
8. **Copy keys**: Project Settings → API: Project URL, `anon` public key, `service_role` secret key.

### 2. Render (Web Service → Environment)

| Variable | Value |
|---|---|
| `SUPABASE_URL` | Project URL, e.g. `https://abcd1234.supabase.co` |
| `SUPABASE_ANON_KEY` | anon public key |
| `SUPABASE_SERVICE_ROLE_KEY` | service_role key (**secret**: never put it in the frontend or the repo) |
| `CRON_SECRET` | a long random string (`openssl rand -hex 32`) |
| `OPENROUTER_API_KEY` | optional, for reading new uploads with AI |
| `OPENROUTER_MODEL` | optional, default `anthropic/claude-sonnet-5.5` |
| `EMAIL_SIGNIN` | optional, `true` shows "Sign in with email" (set up custom SMTP in Supabase first). Default: off, "Try the demo" only |

Service settings: Language **Docker**, Dockerfile path `./Dockerfile`, build context `.`, Instance **Free**,
Health check path `/api/health`, start command blank (the Dockerfile reads `$PORT`), auto-deploy on commit.

### 3. GitHub (repo → Settings → Secrets and variables → Actions → New repository secret)

| Secret | Value |
|---|---|
| `NIGHTSHIFT_URL` | your Render URL, e.g. `https://YOUR-SERVICE.onrender.com` (no trailing slash) |
| `CRON_SECRET` | the **same** value as on Render |

Then Actions → "Nightly run" → **Run workflow** once to test it.

## Tests

```bash
python -m pytest -q tests                       # local mode: numbers vs. expected_results.json, sad paths
pip install pgserver "psycopg[binary]"
python tests/supabase_integration.py            # Supabase mode against a real Postgres + the real migrations
```
