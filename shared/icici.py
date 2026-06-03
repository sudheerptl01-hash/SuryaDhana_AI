"""
shared/icici.py — Single source of truth for ICICI Breeze credentials.

Every service that talks to Breeze (data-service for live quotes/intraday,
execution-service for order placement) loads credentials from the SAME place —
environment variables sourced from the project `.env` — and normalizes the daily
session token identically. No per-service manual configuration, no UI paste step.

Constraint: the ICICI session token is a DAILY token; it cannot be derived from
api_key/secret. Refresh it once per trading day (drop the fresh value into `.env`,
or paste it via the UI which writes the same key). Every service then auto-connects
from it at startup via `load_icici_credentials()`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

# ICICI's login redirect returns the token as `apisession=<token>` (sometimes
# `session_token=`). Accept the full pasted URL or a bare token interchangeably.
_SESSION_RE = re.compile(
    r"(?:apisession|session_token|apiSession|api_session)=([^&\s]+)",
    re.IGNORECASE,
)


def extract_session_token(raw: str | None) -> str:
    """Return the bare session token from either a raw token or a full redirect URL."""
    value = (raw or "").strip()
    if not value:
        return ""
    if not value.lower().startswith("http"):
        return value
    match = _SESSION_RE.search(value)
    return match.group(1) if match else value


@dataclass(frozen=True)
class ICICICredentials:
    api_key: str
    api_secret: str
    session_token: str
    client_id: str = ""
    password: str = ""

    @property
    def is_complete(self) -> bool:
        """True when api_key, api_secret and session_token are all present."""
        return bool(self.api_key and self.api_secret and self.session_token)

    @property
    def needs_daily_token(self) -> bool:
        """Key/secret configured but the daily session token is missing/expired."""
        return bool(self.api_key and self.api_secret and not self.session_token)


def load_icici_credentials() -> ICICICredentials:
    """Load and normalize ICICI Breeze credentials from the environment (.env)."""
    return ICICICredentials(
        api_key=os.environ.get("ICICI_API_KEY", "").strip(),
        api_secret=os.environ.get("ICICI_API_SECRET", "").strip(),
        session_token=extract_session_token(os.environ.get("ICICI_SESSION_TOKEN", "")),
        client_id=os.environ.get("ICICI_CLIENT_ID", "").strip(),
        password=os.environ.get("ICICI_PASSWORD", "").strip(),
    )
