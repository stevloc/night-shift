"""Verify the Supabase access token sent with every /api request.

Supabase signs tokens with asymmetric keys (ES256/RS256) published at
    {SUPABASE_URL}/auth/v1/.well-known/jwks.json
which we verify locally (no network call per request; keys cached 10 minutes). Projects still on the
legacy shared secret (HS256) are verified by asking Supabase Auth itself (/auth/v1/user), cached 60 s.
Either way we check signature, expiry, audience "authenticated" and the issuer.
"""

import hashlib
import time

import httpx
import jwt

ASYMMETRIC = ("ES256", "RS256", "EdDSA")


class AuthError(Exception):
    pass


class SupabaseAuth:
    def __init__(self, url, anon_key, http=None):
        self.url = url
        self.issuer = f"{url}/auth/v1"
        self.anon_key = anon_key
        self.http = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self._jwks, self._jwks_at = {}, 0.0
        self._seen = {}   # sha256(token) -> (user, expires_at), for the HS256 path

    async def _key(self, kid):
        if kid not in self._jwks or time.monotonic() - self._jwks_at > 600:
            r = await self.http.get(f"{self.issuer}/.well-known/jwks.json")
            r.raise_for_status()
            self._jwks = {k["kid"]: jwt.PyJWK(k).key for k in r.json().get("keys", []) if "kid" in k}
            self._jwks_at = time.monotonic()
        if kid not in self._jwks:
            raise AuthError("unknown signing key")
        return self._jwks[kid]

    async def user(self, token):
        """Returns {"id", "is_anonymous", "email"} or raises AuthError."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise AuthError("malformed token") from e
        alg = header.get("alg")
        if alg in ASYMMETRIC:
            try:
                claims = jwt.decode(token, key=await self._key(header.get("kid")), algorithms=[alg],
                                    audience="authenticated", issuer=self.issuer,
                                    options={"require": ["exp", "sub"]})
            except jwt.PyJWTError as e:
                raise AuthError("invalid token") from e
            return {"id": claims["sub"], "is_anonymous": bool(claims.get("is_anonymous")), "email": claims.get("email")}
        if alg == "HS256":
            return await self._via_auth_server(token)
        raise AuthError("unsupported token")

    async def _via_auth_server(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        cached = self._seen.get(digest)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        r = await self.http.get(f"{self.issuer}/user",
                                headers={"apikey": self.anon_key, "Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            raise AuthError("invalid token")
        body = r.json()
        user = {"id": body["id"], "is_anonymous": bool(body.get("is_anonymous")), "email": body.get("email")}
        if len(self._seen) > 5000:
            self._seen.clear()
        self._seen[digest] = (user, time.monotonic() + 60)
        return user
