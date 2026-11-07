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
| Monthly forecast from order history (last 28 days ÷ 28 × 30.4) | Price scenarios assume unchanged order volume (labelled as such) |
| Decision log, bookkeeper CSV export, per-visitor sandboxes | **No DoorDash connection.** Approving saves a decision; it never publishes a price |

Labor and overhead are not included in any figure (the app says so).

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

Tests (numbers vs. `expected_results.json`, both sad paths, sandboxing, upload guards):

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

## 5-minute demo

| Time | Do | Show |
|---|---|---|
| 0:00 | **Run Night Shift on tonight's inbox** | 3 invoices read, 1 duplicate skipped |
| 0:30 | **While You Slept** | *Verified* with evidence (e.g. RM-20419: 4 lines add up to $501.70 = printed total), "Duplicate of RM-20419, skipped. Not counted.", *Needs your input*: rice paper, *Proposed, not applied*: Brisket Pho |
| 1:15 | Brisket Pho → **Review supplier change** | Highlighted invoice line: $119.80 → $134.20 per 20 lb case (+12%) |
| 1:45 | **Compare price scenario** → tap **~$169** | $15.99 → $16.99: +$0.75 per order × 225 forecast orders, a scenario at unchanged order volume |
| 2:15 | **Approve this scenario** | "Saved. Update this price in your DoorDash Merchant Portal." + decision log. Never published. |
| 2:45 | Invoice Review → "RICE PAPER 22CM 1 CS" → **Fix this line** → 10 packs × 50 sheets | "= 500 sheets"; per-sheet cost stays $0.076; Spring Rolls back to OK; logged "Owner confirmed … case = 500 sheets" |
| 3:30 | Invoice Review → **Skipped duplicates** | Same supplier + number + total as the file read minutes earlier |
| 4:00 | Dish Detail → **Edit recipe amounts** | Costs and status update live |
| 4:30 | **Export for bookkeeper (CSV)**, switch to **Español** | Duplicates left out, review lines flagged; same flow in Spanish |

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
| `llm.py` | The AI's one job: read a new invoice image/PDF into structured lines. Never calculates. |
| `engine.py` | Invoice checks, holds, corrections, scenarios, decision log, report, sessions, rate limit. |
| `api.py` | FastAPI: `/api/*` + the built app; auth middleware; upload guards; `/api/health`, `/api/config`, `/api/nightly-run`. |
| `config.py` | Reads the six environment variables (secrets are never printed). |
| `auth.py` | Verifies Supabase access tokens (JWKS; legacy HS256 via Supabase Auth). |
| `store.py` | Supabase persistence (2 RPCs per request) and the private Storage bucket. |
| `supabase/migrations/` | Schema + RLS, server-side functions, demo template seed, storage bucket. |
| `web/` | React + Vite + TypeScript UI (English/Spanish, WCAG 2.2 AA). |
| `tests/` | Checks against `expected_results.json`. |
| `Dockerfile` | Stage 1 builds `web/` with Node; stage 2 runs it all on slim Python. |

## How this was built

Built during a hackathon with AI coding assistance (Claude Code). The developer directed the
product, reviewed the output, and tested the app; the AI wrote much of the code under that direction.

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
