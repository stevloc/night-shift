"""Night Shift HTTP API (FastAPI). One service: the API under /api, the built React app at /.

Every route calls one engine function and returns the fresh view, so the UI always shows
code-computed numbers. Each visitor gets a session cookie and their own copy of the demo.

Run locally:   uvicorn api:app --port 8000      (or: python api.py, which reads $PORT)
"""

import asyncio
import hmac
import os
import re
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import engine
from auth import AuthError, SupabaseAuth
from config import CONFIG
from data import DISHES
from store import SupabaseFiles, SupabaseStore

app = FastAPI(title="Night Shift API")
ROOT = Path(__file__).parent
COOKIE = "ns_session"
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ERROR_STATUS = {"too_large": 413, "bad_file": 415, "rate_limited": 429, "ai_not_configured": 503}
PUBLIC_PATHS = {"/api/health", "/api/config", "/api/nightly-run"}

# Production (Supabase) vs. local demo mode (in-memory sandboxes keyed by a cookie).
if CONFIG.supabase_enabled:
    STORE = SupabaseStore(CONFIG.supabase_url, CONFIG.supabase_service_role_key)
    AUTH = SupabaseAuth(CONFIG.supabase_url, CONFIG.supabase_anon_key)
    engine.FILES = SupabaseFiles(CONFIG.supabase_url, CONFIG.supabase_service_role_key)
else:
    STORE = AUTH = None
LOCKS = {}   # restaurant id -> asyncio.Lock: one request at a time per restaurant


# ------------------------------------------------------------------ sessions

@app.middleware("http")
async def visitor_session(request: Request, call_next):
    """Supabase mode: verify the user's token, load their restaurant, run, save.
    Local mode: a session cookie gives each visitor their own in-memory demo."""
    if not request.url.path.startswith("/api/") or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    if STORE is not None:
        return await _with_supabase_user(request, call_next)
    sid = request.cookies.get(COOKIE)
    is_new = not (sid and SESSION_ID.match(sid))
    if is_new:
        sid = engine.Sessions.new_id()
    item = engine.SESSIONS.get(sid)
    if item["lock"] is None:
        item["lock"] = asyncio.Lock()
    async with item["lock"]:
        token = engine.use_session(item["state"])
        try:
            response = await call_next(request)
        finally:
            engine._current.reset(token)
    if is_new:
        https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(COOKIE, sid, max_age=7 * 24 * 3600, httponly=True, samesite="lax", secure=https)
    return response


def _unauthorized():
    return JSONResponse({"detail": {"error": "unauthorized"}}, status_code=401)


async def _with_supabase_user(request: Request, call_next):
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return _unauthorized()
    try:
        user = await AUTH.user(header[7:].strip())
    except AuthError:
        return _unauthorized()
    restaurant_id = await STORE.restaurant_for(user["id"])   # first sign-in: create_demo_restaurant
    request.state.user = user
    async with LOCKS.setdefault(restaurant_id, asyncio.Lock()):
        state, meta = await STORE.load(restaurant_id)
        state["actor"] = user["id"]
        token = engine.use_session(state)
        try:
            response = await call_next(request)
            changed = request.method != "GET" and response.status_code < 400 and request.url.path != "/api/reset"
            if changed:
                await STORE.save(restaurant_id, state, meta)
        finally:
            engine._current.reset(token)
    return response


def _client_ip(request: Request):
    """Real visitor IP behind Render's proxy (first X-Forwarded-For entry)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _respond(outcome):
    """Errors -> HTTP error with codes the UI translates; success -> outcome + fresh view."""
    if outcome.get("error"):
        raise HTTPException(status_code=ERROR_STATUS.get(outcome["error"], 422), detail=outcome)
    return {**outcome, "view": engine.view()}


def _dish(dish_id):
    if dish_id not in DISHES:
        raise HTTPException(404)
    return dish_id


def _sniff(data: bytes):
    """File type from its first bytes (never trust the file name): images and PDF only."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


class Price(BaseModel):
    price: float | str


class LineFix(BaseModel):
    ingredient: str | None = None
    pack_size: float | str | None = None
    pack_unit: str | None = None
    pack_price: float | str | None = None
    packs: float | str | None = None
    per_pack: float | str | None = None


class Settings(BaseModel):
    commission_pct: int | str
    packaging: float | str
    target_margin_pct: float | str
    monthly_orders: dict[str, int | float | str]


class Recipe(BaseModel):
    amounts: dict[str, float | str]


class Dismissal(BaseModel):
    reason: str = ""
    note: str = ""


class KeepPrice(BaseModel):
    note: str = ""


class CorrectionChoice(BaseModel):
    choice: str = ""


# ------------------------------------------------------------------ routes

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/config")
def public_config():
    """What the browser may know: the Supabase URL and the anon (public) key, for sign-in only."""
    if not CONFIG.supabase_enabled:
        return {"auth": False}
    return {"auth": True, "supabaseUrl": CONFIG.supabase_url, "supabaseAnonKey": CONFIG.supabase_anon_key,
            "emailSignin": CONFIG.email_signin}


@app.post("/api/nightly-run")
async def nightly_run(request: Request):
    """Scheduled run for every restaurant. Requires header X-Cron-Secret == CRON_SECRET."""
    given = request.headers.get("x-cron-secret", "")
    if not CONFIG.cron_secret or not hmac.compare_digest(given.encode(), CONFIG.cron_secret.encode()):
        raise HTTPException(403, detail={"error": "forbidden"})
    results = []
    if STORE is None:   # local mode: every in-memory sandbox
        for item in list(engine.SESSIONS._items.values()):
            token = engine.use_session(item["state"])
            try:
                await run_in_threadpool(engine.run_night_shift, False)
            finally:
                engine._current.reset(token)
            results.append({"ok": True})
        return {"ok": True, "restaurants": len(results)}
    for restaurant_id in await STORE.all_restaurants():
        async with LOCKS.setdefault(restaurant_id, asyncio.Lock()):
            try:
                state, meta = await STORE.load(restaurant_id)
                state["actor"] = None
                token = engine.use_session(state)
                try:
                    await run_in_threadpool(engine.run_night_shift, False)
                    await STORE.save(restaurant_id, state, meta)
                finally:
                    engine._current.reset(token)
                results.append({"restaurant_id": restaurant_id, "ok": True})
            except Exception as error:   # one bad restaurant must not stop the others
                results.append({"restaurant_id": restaurant_id, "ok": False, "error": type(error).__name__})
    return {"ok": all(r["ok"] for r in results), "restaurants": len(results), "results": results}


@app.get("/api/state")
def state():
    return engine.view()


@app.post("/api/run")
def run():
    """Night Shift reads every file in demo-data/inbox/ (seeded clock: identical every run)."""
    return {"results": engine.run_night_shift(), "view": engine.view()}


@app.post("/api/invoices")
async def upload(request: Request, file: UploadFile = File(...)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail={"error": "too_large", "max": 5})
    kind = _sniff(data)
    if not kind:
        raise HTTPException(415, detail={"error": "bad_file"})
    # The AI call can take a while: run it off the event loop (the session stays bound to this request).
    outcome = await run_in_threadpool(engine.upload_invoice, data, kind, file.filename, _client_ip(request))
    return _respond(outcome)


@app.get("/api/invoices/{invoice_id}/image-url")
def invoice_image_url(invoice_id: int):
    """A link the browser can open: a 5-minute signed URL (Supabase) or this app's own route (local)."""
    try:
        kind, value = engine.STATE["images"][invoice_id]
    except KeyError:
        raise HTTPException(404)
    if kind == "storage":
        return {"url": engine.FILES.signed_url(value, seconds=300)}
    return {"url": f"/api/invoices/{invoice_id}/image"}


@app.get("/api/invoices/{invoice_id}/image")
def invoice_image(invoice_id: int):
    found = engine.invoice_image(invoice_id)
    if found is None:
        raise HTTPException(404)
    return Response(found[0], media_type=found[1])


@app.get("/api/invoices/{invoice_id}/lines/{line_id}/image")
def line_image(invoice_id: int, line_id: int):
    png = engine.line_image(invoice_id, line_id)
    if png is None:
        raise HTTPException(404)
    return Response(png, media_type="image/png")


@app.post("/api/invoices/{invoice_id}/lines/{line_id}")
def correct_line(invoice_id: int, line_id: int, body: LineFix):
    return _respond(engine.correct_line(invoice_id, line_id, body.model_dump()))


@app.post("/api/dishes/{dish_id}/preview")
def preview(dish_id: str, body: Price):
    outcome = engine.preview(_dish(dish_id), body.price)
    if outcome.get("error"):
        raise HTTPException(status_code=422, detail=outcome)
    return outcome


@app.post("/api/dishes/{dish_id}/recipe/preview")
def preview_recipe(dish_id: str, body: Recipe):
    outcome = engine.preview_recipe(_dish(dish_id), body.amounts)
    if outcome.get("error"):
        raise HTTPException(status_code=422, detail=outcome)
    return outcome


@app.put("/api/dishes/{dish_id}/recipe")
def set_recipe(dish_id: str, body: Recipe):
    return _respond(engine.set_recipe(_dish(dish_id), body.amounts))


@app.post("/api/dishes/{dish_id}/proposal")
def set_proposal(dish_id: str, body: Price):
    return _respond(engine.set_proposal(_dish(dish_id), body.price))


@app.post("/api/dishes/{dish_id}/approve")
def approve(dish_id: str):
    return _respond(engine.approve(_dish(dish_id)))


@app.post("/api/dishes/{dish_id}/undo")
def undo(dish_id: str):
    return _respond(engine.undo(_dish(dish_id)))


@app.post("/api/dishes/{dish_id}/dismiss")
def dismiss(dish_id: str, body: Dismissal):
    return _respond(engine.dismiss(_dish(dish_id), body.reason, body.note))


@app.post("/api/dishes/{dish_id}/keep")
def keep_price(dish_id: str, body: KeepPrice):
    """Keep the current DoorDash price on purpose (saved to the decision log, reason optional)."""
    return _respond(engine.keep_price(_dish(dish_id), body.note))


@app.post("/api/corrections/{correction_id}")
def resolve_correction(correction_id: int, body: CorrectionChoice):
    """Possible corrected invoice: the owner picks which version counts (keep_original | use_new)."""
    return _respond(engine.resolve_correction(correction_id, body.choice))


@app.post("/api/dishes/{dish_id}/restore")
def restore(dish_id: str):
    return _respond(engine.restore(_dish(dish_id)))


@app.put("/api/settings")
def settings(body: Settings):
    return _respond(engine.update_settings(body.model_dump()))


@app.get("/api/export/bookkeeper.csv")
def bookkeeper_csv():
    """Download: tonight's counted invoices (duplicates excluded, review items flagged)."""
    return Response(engine.bookkeeper_csv(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="night-shift-invoices-2026-11-06.csv"'})


@app.post("/api/reset")
async def reset(request: Request):
    """This user only: delete their restaurant and reseed a fresh copy of the demo."""
    if STORE is None:
        engine.reset()
        return {"view": engine.view()}
    user = request.state.user
    restaurant_id = await STORE.reset(user["id"], engine.FILES)
    state, _meta = await STORE.load(restaurant_id)
    state["actor"] = user["id"]
    engine.STATE.clear()
    engine.STATE.update(state)
    return {"view": await run_in_threadpool(engine.view)}


# Serve the built React app (web/dist) at / when it exists. Registered last so /api wins.
DIST = ROOT / "web" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")
