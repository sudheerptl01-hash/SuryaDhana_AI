#!/usr/bin/env python
"""
ICICI Breeze — daily session token refresh (unattended with TOTP).

Scheduled by the master controller (08:00 IST Mon–Fri, and once at start-up on a
trading morning). Also runnable by hand:

    python scripts/daily_session_refresh.py             # visible browser; you may type the code
    python scripts/daily_session_refresh.py --headless  # unattended (needs ICICI_TOTP_SECRET)
    python scripts/daily_session_refresh.py --check     # only report whether today's token works
    python scripts/daily_session_refresh.py --force     # log in even if the current token works

Flow: keep the current token if it still works → otherwise log in on ICICI's real page
(iDirect user ID + password + authenticator code, shared/icici_login.py) → hand the
token to ui-api, which saves it to .env and reconnects the data/execution services.
If ICICI's API cannot be reached, the current token is NOT treated as expired: no login is
started (it would text an OTP for nothing) and the run ends "unreachable" (retry later).
If ui-api does not take the token for about 2 minutes, the token is written to .env here and
pushed to data-service directly, and the run reports a WARNING (outcome "warning"): ui-api keeps
its old token until it restarts or the token is pasted on BRKR.

Secrets (never printed): ICICI_CLIENT_ID (iDirect user ID, e.g. AD206594),
ICICI_PASSWORD, ICICI_TOTP_SECRET — from .env or the macOS Keychain. Recommended for
the TOTP secret, so .env alone is not a full login:
    security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w

Exit codes: 0 ok · 2 needs you (no TOTP secret, captcha, rejected login/code) · 3 retry
later. The last stdout line is `RESULT {json}` for the scheduler: status (valid | refreshed |
skipped | expired | unreachable | retry | needs_human | blocked), detail, and on a login
"outcome": "ok" | "warning" with "via": "ui-api" | ".env".
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.icici import extract_session_token  # noqa: E402
from shared.icici_login import (  # noqa: E402
    LoginNeedsHuman,
    LoginTransient,
    browser_login,
    mask,
    parse_totp_secret,
    read_secret,
)

ENV_FILE = ROOT / ".env"
CACHE_FILE = ROOT / ".session_cache.json"
# After ICICI rejects the user ID / password, unattended runs stop retrying the same credentials: a broker locks
# the account after a few wrong passwords. Cleared when the credentials in .env change or a login succeeds.
BLOCK_FILE = ROOT / ".icici_login_block.json"
SHOT_FILE = ROOT / ".logs" / "icici_login_failure.png"
UI_API = os.getenv("UI_API_URL", "http://localhost:8010").rstrip("/")
DATA_SERVICE = os.getenv("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/")
# ui-api's .env writer and Breeze check (one implementation for both): loaded by file path, because putting
# services/ui-api on sys.path would shadow modules of master-controller, which imports this script.
ICICI_ADMIN_FILE = ROOT / "services" / "ui-api" / "icici_admin.py"

# master-controller kills this script after 480 s, and up to 5 min of that may be the wait for your SMS OTP.
# Every wait after the login is sized from what is left, so a slow ui-api cannot get the token lost in a kill.
_STARTED = time.monotonic()
RUN_BUDGET_S = 450.0
UI_API_HANDOFF_MAX_S = 120.0       # "about 2 minutes" of hand-off retries (ui-api restarts take ~20-60 s)
UI_API_HANDOFF_MIN_S = 15.0
UI_API_RETRY_WAITS_S = (2.0, 4.0, 8.0, 15.0, 30.0)
FALLBACK_RESERVE_S = 60.0          # kept back for the .env fallback: data-service's reconnect is a Breeze login

EXIT_OK, EXIT_NEEDS_HUMAN, EXIT_RETRY = 0, 2, 3


# ── .env ─────────────────────────────────────────────────────────────────────────

def read_env_file() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _icici_admin():
    """services/ui-api/icici_admin.py as a private module (see ICICI_ADMIN_FILE)."""
    name = "_suryadhana_icici_admin"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, ICICI_ADMIN_FILE)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {ICICI_ADMIN_FILE}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        try:
            spec.loader.exec_module(mod)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return mod


def write_env_value(key: str, value: str) -> None:
    """Set KEY=value in .env the way ui-api does (desktop review P13): quoted when needed so '#', '$', quotes and
    spaces read back exactly in python-dotenv and the plain parsers, re-read before an atomic rename, the file's
    mode kept (a new .env is created 0600). Posture/guard keys (EXECUTION_*, GUARD_*, ...) are refused.

    Raises ValueError naming the key, never the value, when the value cannot be stored exactly or the re-read
    failed (.env is then left as it was). Used for the token fallback and by master-controller's /password and
    /userid."""
    admin = _icici_admin()
    out = admin.persist_env_updates({key: value}, env_path=ENV_FILE)
    if not out.get("persisted"):
        raise ValueError(f"{key} was not saved to .env: {out.get('reason') or 'it would not read back exactly'}")


# ── Breeze + ui-api ──────────────────────────────────────────────────────────────

def check_token(api_key: str, api_secret: str, token: str, probe=None) -> tuple[str, str]:
    """(state, message) for a session token: state is 'valid' or the public error kind 'expired' | 'network' |
    'credentials' | 'unknown' (desktop review P4). The same Breeze check ui-api runs (network failures retried 3x),
    so an ICICI outage is no longer mistaken for an expired token."""
    if not (api_key and api_secret):
        return "credentials", "ICICI_API_KEY / ICICI_API_SECRET missing"
    if not token:
        return "expired", "no session token"
    admin = _icici_admin()
    try:
        res = (probe or admin.probe_breeze_connection)(api_key, api_secret, token)
    except Exception as exc:  # noqa: BLE001 — the SDK raises bare Exception; classify it like the probe does
        kind, message = admin.classify_breeze_error(str(exc))
        return admin.public_error_kind(kind), message
    if res.get("connected"):
        return "valid", ""
    return admin.public_error_kind(res.get("error_kind")), str(res.get("error") or "")


def token_works(api_key: str, api_secret: str, token: str) -> bool:
    """True when the token works now (False also when ICICI could not be reached: use check_token to tell)."""
    return check_token(api_key, api_secret, token)[0] == "valid"


def _time_left() -> float:
    return RUN_BUDGET_S - (time.monotonic() - _STARTED)


def handoff_budget_s() -> float:
    """Seconds the ui-api hand-off may take: about 2 minutes, less when the login itself took long."""
    return max(UI_API_HANDOFF_MIN_S, min(UI_API_HANDOFF_MAX_S, _time_left() - FALLBACK_RESERVE_S))


def handoff_to_ui_api(token: str, budget_s: float, post=None, clock=time.monotonic, sleep=time.sleep) -> tuple[dict | None, str]:
    """POST the token to ui-api's /session-token until it answers 200 or ``budget_s`` runs out (P3).

    ui-api saves the token to .env, checks it with Breeze (10-40 s) and pushes it to the data/execution services.
    Connection errors, timeouts and 5xx (ui-api restarting) are retried with backoff; a 4xx is final. Returns
    (ui-api's JSON body, "") or (None, why it was not taken). ``fresh_login``: ICICI ended the previous session when
    it issued this token, so ui-api saves it even if its check fails."""
    post = post or httpx.post
    deadline = clock() + budget_s
    attempts, why = 0, "not tried"
    while True:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        attempts += 1
        try:
            r = post(f"{UI_API}/api/positions/session-token", json={"token": token, "fresh_login": True},
                     timeout=max(5.0, remaining))
            if r.status_code == 200:
                body = r.json()
                if isinstance(body, dict):
                    return body, ""
                why = "HTTP 200 without a JSON object"
            else:
                why = f"HTTP {r.status_code}"
                if 400 <= r.status_code < 500 and r.status_code not in (408, 425, 429):
                    return None, f"{why} (refused)"
        except (httpx.HTTPError, ValueError) as exc:
            why = type(exc).__name__
        wait = UI_API_RETRY_WAITS_S[min(attempts - 1, len(UI_API_RETRY_WAITS_S) - 1)]
        if clock() + wait >= deadline:
            break
        sleep(wait)
    return None, f"{why} after {attempts} attempt(s) in {int(budget_s)} s"


def push_token_to_data_service(api_key: str, api_secret: str, token: str, timeout_s: float, post=None) -> dict:
    """data-service's POST /provider/configure takes the credentials in its body (a missing field = its own
    environment, which still holds the old token). Send the new token so live quotes reconnect with it now."""
    post = post or httpx.post
    try:
        r = post(f"{DATA_SERVICE}/provider/configure",
                 json={"api_key": api_key, "api_secret": api_secret, "session_token": token}, timeout=timeout_s)
        body = r.json() if r.status_code == 200 else {}
        return {"ok": r.status_code == 200, "connected": bool(isinstance(body, dict) and body.get("connected")),
                "status_code": r.status_code}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "connected": False, "error": type(exc).__name__}


def apply_token(token: str, api_key: str, api_secret: str) -> dict:
    """Hand the new token to ui-api (retried for about 2 minutes). If ui-api never takes it: write .env here, push
    the token to data-service directly, and say so (``via`` ".env"); ui-api keeps its old token until it restarts.

    Returns {"via": "ui-api" | ".env" | "none", "connected": bool, "error": str | None, "error_kind": str | None,
    "why": why ui-api did not take it, "data_service": the direct push's result}."""
    body, why = handoff_to_ui_api(token, budget_s=handoff_budget_s())
    if body is not None:
        return {"via": "ui-api", "connected": bool(body.get("connected")), "error": body.get("error"),
                "error_kind": body.get("error_kind")}
    try:
        write_env_value("ICICI_SESSION_TOKEN", token)
    except (ValueError, OSError) as exc:
        return {"via": "none", "connected": False, "why": why, "error_kind": "unknown",
                "error": f"ui-api did not take the token ({why}) and .env could not be written: {exc}"}
    ds = push_token_to_data_service(api_key, api_secret, token, timeout_s=max(5.0, min(60.0, _time_left() - 30.0)))
    # data-service's reconnect is itself a Breeze login; only when it did not confirm, check (up to ~100 s when ICICI
    # is unreachable: 3 tries) if there is time, else leave it to the next run, which checks .env before logging in
    state, message = ("valid", "") if ds["connected"] else (
        check_token(api_key, api_secret, token) if _time_left() > 110.0 else ("unknown", "no time left to check it"))
    return {"via": ".env", "connected": state == "valid", "why": why, "data_service": ds,
            "error": None if state == "valid" else message, "error_kind": None if state == "valid" else state}


def notify_mac(title: str, body: str) -> None:
    """Desktop notification — the only alert channel when Telegram/Discord are not set."""
    if sys.platform != "darwin":
        return
    script = f'display notification {json.dumps(body[:220])} with title {json.dumps(title)}'
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], timeout=10, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass


def finish(code: int, status: str, detail: str, **extra) -> None:
    CACHE_FILE.write_text(json.dumps({"at": datetime.now().isoformat(timespec="seconds"),
                                      "status": status, "detail": detail, **extra}))
    print("RESULT " + json.dumps({"status": status, "detail": detail, **extra}))
    sys.exit(code)


# ── wrong-password guard ─────────────────────────────────────────────────────────

def credential_fingerprint(user_id: str, password: str) -> str:
    """One-way fingerprint of the credentials, so the block lifts by itself once they are corrected."""
    return hashlib.sha256(f"suryadhana|{user_id}|{password}".encode()).hexdigest()[:16]


def blocked_reason(fingerprint: str) -> str | None:
    try:
        b = json.loads(BLOCK_FILE.read_text())
    except (OSError, ValueError):
        return None
    return b.get("reason") if b.get("fingerprint") == fingerprint else None


def is_credentials_rejection(message: str) -> bool:
    m = message.lower()
    return "rejected the login" in m and any(w in m for w in ("credential", "password", "user id", "userid", "invalid"))


# ── main ─────────────────────────────────────────────────────────────────────────

OTP_REQUEST = ROOT / "data" / "icici_otp_request.json"
OTP_REPLY = ROOT / "data" / "icici_otp.json"
OTP_LAST_ASK = ROOT / "data" / "icici_otp_last_ask.json"     # kept: a restart must not text you again right away
OTP_WAIT_S = 300


def telegram_send(env: dict[str, str], text: str) -> bool:
    """Plain-text Telegram message to TELEGRAM_CHAT_ID (no-op when not configured)."""
    tok, chat = env.get("TELEGRAM_BOT_TOKEN", ""), env.get("TELEGRAM_CHAT_ID", "")
    if not (tok and chat):
        return False
    try:
        r = httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text}, timeout=15)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


def minutes_since_otp_ask(now: float | None = None) -> float | None:
    """Minutes since the last SMS OTP request on Telegram; None if there was none."""
    try:
        asked = float(json.loads(OTP_LAST_ASK.read_text()).get("at", 0))
    except (OSError, ValueError):
        return None
    return ((now or time.time()) - asked) / 60 if asked else None


def telegram_otp_provider(env: dict[str, str], wait_s: float = OTP_WAIT_S, poll_s: float = 1.0,
                          clock=time.time, sleep=time.sleep):
    """An otp_provider for browser_login: tell you on Telegram that ICICI sent an SMS OTP, then wait for the code
    your reply leaves in data/icici_otp.json (the controller's Telegram bot writes it). None = no reply in time."""
    def provide(panel_text: str) -> str | None:
        OTP_REPLY.unlink(missing_ok=True)
        OTP_REQUEST.parent.mkdir(parents=True, exist_ok=True)
        start = clock()
        OTP_REQUEST.write_text(json.dumps({"at": start}))
        OTP_LAST_ASK.write_text(json.dumps({"at": start}))
        phone = env.get("ICICI_MOBILE", "")
        where = f"your phone ending {phone[-2:]}" if len(phone) >= 4 else "your registered phone"
        telegram_send(env, f"🔐 ICICI login: an OTP was sent to {where}.\nReply with the 6 digits within "
                           f"{int(wait_s // 60)} minutes (or /otp 123456).")
        try:
            while clock() - start < wait_s:
                try:
                    got = json.loads(OTP_REPLY.read_text())
                    if float(got.get("at", 0)) >= start and str(got.get("code", "")).isdigit():
                        return str(got["code"])
                except (OSError, ValueError):
                    pass
                sleep(poll_s)
            telegram_send(env, "⌛ No OTP received in time: ICICI login stopped. Send /login to try again.")
            return None
        finally:
            OTP_REQUEST.unlink(missing_ok=True)
            OTP_REPLY.unlink(missing_ok=True)
    return provide


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh the daily ICICI Breeze session token")
    ap.add_argument("--headless", action="store_true", help="no browser window; fail instead of waiting for a person")
    ap.add_argument("--force", action="store_true", help="log in even if the current token still works")
    ap.add_argument("--check", action="store_true", help="only test the current token")
    ap.add_argument("--quiet-minutes", type=float, default=0,
                    help="don't ask for an SMS OTP if one was asked this many minutes ago (start-up checks)")
    ap.add_argument("--ignore-block", action="store_true",
                    help="try even though ICICI rejected these credentials before (a login you asked for)")
    args = ap.parse_args()

    # .env is the source of truth (ui-api writes it); a long-running parent's env may be stale.
    env = {**os.environ, **read_env_file()}
    api_key, api_secret = env.get("ICICI_API_KEY", ""), env.get("ICICI_API_SECRET", "")
    current = extract_session_token(env.get("ICICI_SESSION_TOKEN", ""))
    if not (api_key and api_secret):
        finish(EXIT_NEEDS_HUMAN, "needs_human", "ICICI_API_KEY / ICICI_API_SECRET missing in .env")

    if not args.force:
        print("Checking the current session token…")
        state, message = check_token(api_key, api_secret, current)
        if state == "valid":
            finish(EXIT_OK, "valid", "current token still works", token=mask(current))
        if state == "network":   # an outage says nothing about the token; a login now would text an OTP for nothing
            finish(EXIT_RETRY, "unreachable", f"ICICI unreachable, the token could not be checked: {message}",
                   error_kind="network")
        if args.check:
            finish(EXIT_RETRY, "expired", "current token no longer works", error_kind=state)
        print("  expired — logging in")
        ago = minutes_since_otp_ask()
        if args.quiet_minutes and ago is not None and ago < args.quiet_minutes:
            finish(EXIT_OK, "skipped", f"an OTP was asked {int(ago)} min ago; not asking again now")

    user_id = read_secret("ICICI_CLIENT_ID", env)
    password = read_secret("ICICI_PASSWORD", env)
    raw_totp = read_secret("ICICI_TOTP_SECRET", env)
    try:
        totp_spec = parse_totp_secret(raw_totp) if raw_totp else None
    except ValueError as exc:
        finish(EXIT_NEEDS_HUMAN, "needs_human", f"ICICI_TOTP_SECRET is unusable: {exc}")
    print(f"User {mask(user_id)} · TOTP {'configured' if totp_spec else 'not configured'} · "
          f"{'headless' if args.headless else 'visible browser'}")

    fingerprint = credential_fingerprint(user_id, password)
    reason = blocked_reason(fingerprint)
    if reason and args.headless and not args.force and not args.ignore_block:
        finish(EXIT_NEEDS_HUMAN, "blocked",
               f"not retrying: ICICI rejected these credentials before ({reason}). Correct ICICI_CLIENT_ID / "
               "ICICI_PASSWORD in .env (the block lifts by itself), or run once with --force")

    SHOT_FILE.parent.mkdir(exist_ok=True)
    try:
        via_telegram = args.headless and bool(env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"))
        token = browser_login(api_key, user_id, password, totp_spec, headless=args.headless,
                              attended=not args.headless, screenshot_path=str(SHOT_FILE),
                              otp_provider=telegram_otp_provider(env) if via_telegram else None)
    except LoginNeedsHuman as exc:
        if is_credentials_rejection(str(exc)):
            BLOCK_FILE.write_text(json.dumps({"fingerprint": fingerprint, "reason": str(exc)[:200],
                                              "at": datetime.now().isoformat(timespec="seconds")}))
        if args.headless:
            notify_mac("SuryaDhana · ICICI login needs you", str(exc))
        finish(EXIT_NEEDS_HUMAN, "needs_human", str(exc))
    except LoginTransient as exc:
        finish(EXIT_RETRY, "retry", str(exc))

    BLOCK_FILE.unlink(missing_ok=True)
    applied = apply_token(token, api_key, api_secret)
    if not applied["connected"]:
        notify_mac("SuryaDhana · ICICI session", f"Got a token but Breeze rejected it: {applied['error']}")
        finish(EXIT_RETRY, "retry", f"new token not accepted: {applied['error']}", token=mask(token),
               via=applied["via"], error_kind=applied.get("error_kind"))
    if applied["via"] != "ui-api":
        quotes = "on" if applied.get("data_service", {}).get("connected") else "not confirmed"
        detail = (f"WARNING: logged in, but ui-api did not take the token ({applied.get('why')}). It was saved to .env "
                  f"only and sent to data-service directly (live quotes: {quotes}); ui-api keeps the old token until "
                  "it restarts or the token is pasted on BRKR.")
        notify_mac("SuryaDhana · ICICI token saved to .env only", detail)
        finish(EXIT_OK, "refreshed", detail, outcome="warning", via=applied["via"], token=mask(token))
    finish(EXIT_OK, "refreshed", "logged in, token applied via ui-api", outcome="ok", via="ui-api", token=mask(token))


if __name__ == "__main__":
    main()
