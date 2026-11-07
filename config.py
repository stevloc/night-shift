"""All configuration comes from environment variables (never from files in the repo).

    OPENROUTER_API_KEY          AI invoice reading for new uploads (optional)
    OPENROUTER_MODEL            which OpenRouter model reads invoices (optional)
    SUPABASE_URL                https://<project>.supabase.co  (unset -> local in-memory mode)
    SUPABASE_ANON_KEY           public key, sent to the browser for sign-in only
    SUPABASE_SERVICE_ROLE_KEY   server-only key: the backend is the only thing that touches the DB
    CRON_SECRET                 shared secret for POST /api/nightly-run

Secrets are never printed: repr() of Config hides them, and nothing logs os.environ.
"""

import os
from dataclasses import dataclass, field


def _env(name):
    value = os.environ.get(name, "").strip()
    return value or None


@dataclass(frozen=True)
class Config:
    openrouter_api_key: str | None = field(default=None, repr=False)
    openrouter_model: str = "anthropic/claude-sonnet-5.5"
    supabase_url: str | None = None
    supabase_anon_key: str | None = field(default=None, repr=False)
    supabase_service_role_key: str | None = field(default=None, repr=False)
    cron_secret: str | None = field(default=None, repr=False)

    @property
    def supabase_enabled(self):
        """Supabase mode needs all three Supabase values; otherwise the app runs in local demo mode."""
        return bool(self.supabase_url and self.supabase_anon_key and self.supabase_service_role_key)


def load():
    return Config(
        openrouter_api_key=_env("OPENROUTER_API_KEY"),
        # NIGHT_SHIFT_MODEL is the older name; OPENROUTER_MODEL wins.
        openrouter_model=_env("OPENROUTER_MODEL") or _env("NIGHT_SHIFT_MODEL") or "anthropic/claude-sonnet-5.5",
        supabase_url=(_env("SUPABASE_URL") or "").rstrip("/") or None,
        supabase_anon_key=_env("SUPABASE_ANON_KEY"),
        supabase_service_role_key=_env("SUPABASE_SERVICE_ROLE_KEY"),
        cron_secret=_env("CRON_SECRET"),
    )


CONFIG = load()
