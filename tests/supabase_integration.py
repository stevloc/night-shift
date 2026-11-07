"""End-to-end test of Supabase mode against a REAL Postgres running the real migrations.

Real: SQL migrations + functions (run as service_role), ES256 JWT verification via JWKS, FastAPI app.
Stand-ins: a thin PostgREST shim (RPC -> SQL function call) and an in-memory Storage bucket.

    pip install pgserver "psycopg[binary]"  &&  python tests/supabase_integration.py
"""

import glob
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SERVICE, ANON, URL, CRON = "service-key-test", "anon-key-test", "https://test.supabase.co", "cron-test-secret"
os.environ.update(SUPABASE_URL=URL, SUPABASE_ANON_KEY=ANON, SUPABASE_SERVICE_ROLE_KEY=SERVICE, CRON_SECRET=CRON)
os.environ.pop("OPENROUTER_API_KEY", None)

import httpx  # noqa: E402
import jwt  # noqa: E402
import pgserver  # noqa: E402
import psycopg  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

# ---- Postgres with Supabase's built-ins stubbed, then the real migrations
pg = pgserver.get_server(tempfile.mkdtemp(), cleanup_mode="stop")
db = psycopg.connect(pg.get_uri(), autocommit=True)
db.execute("""
create role anon; create role authenticated; create role service_role bypassrls;
create schema auth; create table auth.users (id uuid primary key);
create schema storage; create table storage.buckets (id text primary key, name text, public boolean,
  file_size_limit bigint, allowed_mime_types text[]);
grant usage on schema public to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
""")
for f in sorted(glob.glob(str(ROOT / "supabase/migrations/*.sql"))):
    db.execute(open(f).read())

# ---- fake Supabase over HTTP: PostgREST RPC, Auth JWKS, Storage
key = ec.generate_private_key(ec.SECP256R1())
jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
jwk.update(kid="test-kid", alg="ES256", use="sig")
bucket = {}


def handler(request: httpx.Request):
    path = request.url.path
    if path == "/auth/v1/.well-known/jwks.json":
        return httpx.Response(200, json={"keys": [jwk]})
    assert request.headers.get("apikey") == SERVICE, f"service key missing on {path}"
    if path.startswith("/rest/v1/rpc/"):
        fn, args = path.rsplit("/", 1)[1], json.loads(request.content or b"{}")
        params = ", ".join(f"{k} => %s" for k in args)
        values = [json.dumps(v) if isinstance(v, (dict, list)) else v for v in args.values()]
        with psycopg.connect(pg.get_uri(), autocommit=True) as c:
            c.execute("set role service_role")
            row = c.execute(f"select public.{fn}({params})", values).fetchone()
        body = json.dumps(row[0] if row else None, default=str)   # like PostgREST: uuids/dates as strings
        return httpx.Response(200, content=body, headers={"content-type": "application/json"})
    if path == "/rest/v1/restaurants":
        with psycopg.connect(pg.get_uri(), autocommit=True) as c:
            c.execute("set role service_role")
            rows = c.execute("select id::text from restaurants where not is_template").fetchall()
        return httpx.Response(200, json=[{"id": r[0]} for r in rows])
    if path.startswith("/storage/v1/object/sign/invoices/"):
        name = unquote(path.split("/object/sign/invoices/", 1)[1])
        return httpx.Response(200, json={"signedURL": f"/object/sign/invoices/{name}?token=t"})
    if path == "/storage/v1/object/list/invoices":
        prefix = json.loads(request.content)["prefix"]
        return httpx.Response(200, json=[{"name": k[len(prefix):]} for k in bucket if k.startswith(prefix)])
    if path == "/storage/v1/object/invoices" and request.method == "DELETE":
        for k in json.loads(request.content)["prefixes"]:
            bucket.pop(k, None)
        return httpx.Response(200, json=[])
    if path.startswith("/storage/v1/object/invoices/"):
        name = unquote(path.split("/object/invoices/", 1)[1])
        if request.method == "POST":
            bucket[name] = request.content
            return httpx.Response(200, json={"Key": name})
        return httpx.Response(200, content=bucket[name])
    return httpx.Response(404)


import api  # noqa: E402  (Supabase mode: env is set)
import engine  # noqa: E402

transport = httpx.MockTransport(handler)
api.STORE.http = httpx.AsyncClient(transport=transport)
api.AUTH.http = httpx.AsyncClient(transport=transport)
engine.FILES.http = httpx.Client(transport=transport)


def token_for(user_id, signer=key):
    now = int(time.time())
    claims = {"sub": user_id, "aud": "authenticated", "iss": f"{URL}/auth/v1", "exp": now + 3600, "iat": now,
              "role": "authenticated", "is_anonymous": True}
    return jwt.encode(claims, signer, algorithm="ES256", headers={"kid": "test-kid"})


def new_user():
    u = str(uuid.uuid4())
    db.execute("insert into auth.users values (%s)", (u,))
    return u, {"Authorization": f"Bearer {token_for(u)}"}


app = TestClient(api.app)
EXPECTED = json.loads((ROOT / "demo-data/expected_results.json").read_text())

# 1. auth required, bad tokens refused
assert app.get("/api/state").status_code == 401
assert app.get("/api/state", headers={"Authorization": "Bearer nonsense"}).status_code == 401
other_key = ec.generate_private_key(ec.SECP256R1())
assert app.get("/api/state", headers={"Authorization": f"Bearer {token_for(str(uuid.uuid4()), other_key)}"}).status_code == 401
assert app.get("/api/config").json() == {"auth": True, "supabaseUrl": URL, "supabaseAnonKey": ANON, "emailSignin": False}
print("ok  401 without/with bad tokens; /api/config exposes only URL + anon key")

# 2. first sign-in seeds the demo restaurant
user_a, A = new_user()
v = app.get("/api/state", headers=A).json()
assert v["has_run"] is False and len(v["dishes"]) == 5
rid_a = db.execute("select id::text from restaurants where owner_user_id = %s", (user_a,)).fetchone()[0]
print("ok  first request created restaurant", rid_a[:8])

# 3. run, then reload from the DB and compare with expected_results.json
app.post("/api/run", headers=A)
v = app.get("/api/state", headers=A).json()
dishes = {d["name"]["en"]: d for d in v["dishes"]}
for want in EXPECTED["results"]:
    got = dishes[want["dish"]]
    assert got["now"]["left"] == want["left_per_order"] and got["now"]["margin_pct"] == want["margin_pct"], want["dish"]
    if "proposal" in want:
        assert got["proposal"]["monthly_change"] == want["proposal"]["gain_per_month"]
assert [d["invoice_no"] for d in v["duplicates"]] == ["RM-20419"]
assert [r["original"] for r in v["report"]["needs_input"]] == ["RICE PAPER 22CM 1 CS"]
paths = db.execute("select storage_path from invoices where restaurant_id = %s order by local_id", (rid_a,)).fetchall()
assert all(p[0].startswith(rid_a + "/") and p[0] in bucket for p in paths) and len(paths) == 3
groups = dict(db.execute("""select "group", count(*) from activity_log where restaurant_id = %s group by 1""", (rid_a,)).fetchall())
assert groups.get("verified") and groups.get("needs_input") and groups.get("proposed"), groups
runs = db.execute("select count(distinct run_id) from activity_log where restaurant_id = %s and run_id is not null", (rid_a,)).fetchone()[0]
assert runs == 1
print("ok  run persisted: numbers match expected_results, 3 files in private bucket, activity groups", groups)

# 4. signed URL + line crop from Storage
url = app.get("/api/invoices/2/image-url", headers=A).json()["url"]
assert url.startswith(f"{URL}/storage/v1/object/sign/invoices/{rid_a}/")
assert app.get("/api/invoices/2/lines/2/image", headers=A).headers["content-type"] == "image/png"
print("ok  signed URL + crop served from the private bucket")

# 5. sad path 1 + approve, persisted
fix = v["report"]["needs_input"][0]
app.post(f"/api/invoices/{fix['invoice_id']}/lines/{fix['line_id']}", headers=A,
         json={"ingredient": "rice_paper", "packs": "10", "per_pack": "50", "pack_unit": "sheet", "pack_price": "38"})
app.post("/api/dishes/brisket-pho/approve", headers=A)
v = app.get("/api/state", headers=A).json()
spring = next(d for d in v["dishes"] if d["id"] == "spring-rolls-2")
assert spring["held_by"] == [] and spring["status"] == "ok"
row = db.execute("select action, user_id::text, details->>'to_price' from decisions where restaurant_id = %s", (rid_a,)).fetchone()
assert row == ("price_scenario", user_a, "16.99"), row
finding = db.execute("select status from findings where restaurant_id = %s and item_key = 'brisket-pho'", (rid_a,)).fetchone()[0]
assert finding == "below_target"
print("ok  correction + approval persisted (decision by", user_a[:8], "), findings table updated")

# 6. another user is isolated
user_b, B = new_user()
assert app.get("/api/state", headers=B).json()["has_run"] is False
print("ok  second user has their own restaurant")

# 7. nightly run: secret required; runs every restaurant
assert app.post("/api/nightly-run").status_code == 403
assert app.post("/api/nightly-run", headers={"X-Cron-Secret": "wrong"}).status_code == 403
r = app.post("/api/nightly-run", headers={"X-Cron-Secret": CRON}).json()
assert r["ok"] and r["restaurants"] == 2, r
vb = app.get("/api/state", headers=B).json()
assert vb["has_run"] and len(vb["invoices"]) == 3
va = app.get("/api/state", headers=A).json()
assert len(va["invoices"]) == 3 and len(va["duplicates"]) == 1 + 4   # second night: every file already counted
print("ok  nightly run: both restaurants processed; already-counted invoices skipped as duplicates")

# 8. reset deletes and reseeds (and removes the user's files)
app.post("/api/reset", headers=A)
va = app.get("/api/state", headers=A).json()
assert va["has_run"] is False and va["decision_log"] == [] and va["invoices"] == []
assert not any(k.startswith(rid_a + "/") for k in bucket)
print("ok  reset: fresh restaurant, old files deleted")
print("ALL SUPABASE-MODE CHECKS PASSED")
