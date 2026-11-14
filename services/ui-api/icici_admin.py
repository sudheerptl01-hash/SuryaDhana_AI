from __future__ import annotations

import io
import json
import logging
import os
import re
import stat
import tempfile
import threading
import time
import unicodedata
from collections.abc import Collection
from pathlib import Path
from typing import Any

import httpx


def extract_session_token(raw: str) -> str:
    """Accept either a raw token or a full redirect URL from ICICI."""
    value = raw.strip()
    if not value:
        return ""
    # Search regardless of scheme: a copied address bar often reads "127.0.0.1/?apisession=…".
    match = re.search(r"(?:apisession|session_token|api_session)=([^&\s#]+)", value, re.IGNORECASE)
    return match.group(1) if match else value


def build_login_url(api_key: str) -> str | None:
    api_key = api_key.strip()
    if not api_key:
        return None
    return f"https://api.icicidirect.com/apiuser/login?api_key={api_key}"


def find_env_file() -> Path | None:
    resolved = Path(__file__).resolve()
    repo_root = resolved.parent
    if len(resolved.parents) > 2:
        repo_root = resolved.parents[2]

    candidates = [
        os.environ.get("UI_API_ENV_FILE", "").strip(),
        str(Path.cwd() / ".env"),
        str(Path(__file__).resolve().parent / ".env"),
        str(repo_root / ".env"),
        "/app/.env",
    ]

    seen: set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        path = Path(candidate)
        if path.exists():
            return path
    return None


# ── .env write validation (fix-round-1 adversarial check on C2-security-03) ─────────────────────────
# The PAPER ONLY opt-in (EXECUTION_LIVE_ALLOWED) and the HTTP guard settings (GUARD_*) live in .env, and the
# Broker tab writes .env through POST /api/positions/credentials and /session-token. A value carrying a line
# break used to add a NEW line ("abc\nEXECUTION_LIVE_ALLOWED=1"), which load_dotenv applies at the next
# ui-api start. Every write is now checked BEFORE anything changes (os.environ or the file):
#  * keys: the routes pass ICICI_ENV_KEYS as the allowlist; without one, a key must still look like an env
#    name and must not be one of the posture/security keys below;
#  * values: no control or format characters (C0/C1 incl. CR, LF, NUL, DEL, U+0085), no Unicode line or
#    paragraph separators (str.splitlines() would split on them at the next write), at most 1024 chars;
#  * values must also READ BACK exactly (desktop review RAPI-04 / SECREL-03). .env is read by python-dotenv
#    (load_dotenv in every service, pydantic settings, master-controller's dotenv_values) and by a few plain
#    parsers that strip one layer of surrounding quotes (scripts/daily_session_refresh.py, routers/config.py).
#    python-dotenv expands ${NAME} (even inside single quotes), cuts an unquoted value at " #", strips
#    surrounding spaces and reads a leading quote as an opening quote that may swallow the following lines.
#    So a value is written as KEY=value when that reads back exactly everywhere (every ordinary credential:
#    the .env bytes are the same as before), else as KEY='value', else as KEY="value": the first form that
#    reads back exactly through python-dotenv AND the plain rule (and, for RAW_READ_ENV_KEYS, the raw rule),
#    checked by actually parsing the line followed by quoted sentinel lines (so a quote that would swallow
#    the next lines is caught). A value no form stores exactly is refused: it contains "${" (python-dotenv
#    expands it in every quoting style), starts or ends with a quote that the plain parsers would strip,
#    or mixes ' #' / a surrounding space with both quote kinds or an escape (P13).
#    persist_env_updates then re-reads the new file with python-dotenv and the plain rule before it replaces
#    .env, and keeps the old file unless every updated key reads back exactly and no value another key holds
#    today is lost or changed. A key that only APPEARS is allowed: that is a save repairing a .env the pre-fix
#    raw writer corrupted (a stray quote swallowed the following lines), except a protected key, which is
#    never switched on that way. The routes return the refusal reason (key names only) as persisted_reason.
#    The file keeps its permission bits (a chmod 600 survives a credential save; SECREL-13); a .env that has
#    to be created is created 0600.
ICICI_ENV_KEYS: frozenset[str] = frozenset({
    "ICICI_API_KEY", "ICICI_API_SECRET", "ICICI_CLIENT_ID", "ICICI_PASSWORD", "ICICI_SESSION_TOKEN",
    # GOLD program PLAN §g: the BRKR "Auto-login (TOTP)" panel saves the authenticator secret through this writer
    # (routers/positions.py POST /api/positions/totp), after the owner confirmed the current code; bare base32 only.
    "ICICI_TOTP_SECRET"})
# Read by scripts that take the text after '=' verbatim (only .strip(), no quote removal): scripts/fetch_all_icici.py
# and scripts/icici_session_helper.py. These keys are therefore always stored unquoted; a value that would need
# quoting is refused (a real ICICI key, secret or session token never has a surrounding space, a quote or ' #').
RAW_READ_ENV_KEYS: frozenset[str] = frozenset({"ICICI_API_KEY", "ICICI_API_SECRET", "ICICI_SESSION_TOKEN"})
PROTECTED_ENV_PREFIXES: tuple[str, ...] = ("EXECUTION_", "GUARD_", "UI_API_", "PYTEST_")
PROTECTED_ENV_KEYS: frozenset[str] = frozenset({"FORWARDED_ALLOW_IPS", "MONITOR_WS_MAX", "PAPER_TRADES_DB", "PREFS_DB"})
MAX_ENV_VALUE_CHARS = 1024
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_BAD_CHAR_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


_COMMENT_RE = re.compile(r"\s#")
_ENV_WRITE_LOCK = threading.Lock()
_log = logging.getLogger("ui-api.icici_admin")


class EnvValueError(ValueError):
    """A .env update was refused; the message names the key, never the value."""


def _needs_quotes(value: str) -> bool:
    """True when an unquoted KEY=value would not read back as ``value`` (python-dotenv or a plain parser)."""
    return (value != value.strip() or value.startswith(("'", '"')) or value.endswith(("'", '"'))
            or _COMMENT_RE.search(value) is not None)


# Lines appended after a candidate line when it is test-parsed: an opening quote that is not closed on its own
# line makes python-dotenv read on into the following lines (RAPI-04), which these sentinels expose.
_PROBE_TAIL_KEYS = ("SD_ENV_PROBE_SQ", "SD_ENV_PROBE_DQ", "SD_ENV_PROBE_RAW")
_PROBE_TAIL = "".join(f"\n{k}={q}q{q}" for k, q in zip(_PROBE_TAIL_KEYS, ("'", '"', ""))) + "\n"


def _line_reads_back(key: str, line: str, value: str) -> bool:
    """True when ``line`` reads back as exactly ``value`` in every .env reader and leaves the next lines alone."""
    text = line + _PROBE_TAIL
    if _plain_parse(text).get(key) != value:
        return False
    if key in RAW_READ_ENV_KEYS and _raw_parse(text).get(key) != value:
        return False
    parsed = _dotenv_parse_text(text)
    if parsed is None:                                   # python-dotenv not installed: the plain rules decide
        return True
    return parsed.get(key) == value and all(parsed.get(k) == "q" for k in _PROBE_TAIL_KEYS)


def encode_env_line(key: str, value: str) -> str | None:
    """The .env line for ``value``: unquoted when that reads back exactly (every ordinary credential), else
    single-quoted, else double-quoted, whichever first reads back exactly everywhere. None when no form does."""
    candidates = [] if _needs_quotes(value) else [f"{key}={value}"]
    candidates += [f"{key}='{value}'", f'{key}="{value}"']
    return next((line for line in candidates if _line_reads_back(key, line, value)), None)


def env_line(key: str, value: str) -> str:
    """The .env line for an accepted value (see encode_env_line); EnvValueError if it cannot be stored exactly."""
    line = encode_env_line(key, value)
    if line is None:
        raise EnvValueError(f"{key} {_unstorable_reason(key)}")
    return line


def plain_env_value(raw: str) -> str:
    """How the plain .env parsers read a value (daily_session_refresh.read_env_file, routers/config.py)."""
    return raw.strip().strip('"').strip("'")


def _unstorable_reason(key: str | None) -> str:
    if key in RAW_READ_ENV_KEYS:
        return (f"cannot be stored in .env exactly: some scripts read {key} without removing quotes, so it must "
                "fit unquoted (no leading or trailing space or quote, no ' #')")
    return ("cannot be stored in .env exactly: no quoting reads back the same in every .env reader (it starts or "
            "ends with a quote, or needs quoting and also holds both kinds of quote or an escape)")


def env_value_problem(value: Any, key: str | None = None) -> str | None:
    """Why ``value`` cannot be written to .env (None = fine). Never includes the value itself. With ``key``, the
    key-specific rules apply too (RAW_READ_ENV_KEYS are stored unquoted only)."""
    if not isinstance(value, str):
        return "must be text"
    if len(value) > MAX_ENV_VALUE_CHARS:
        return f"is longer than {MAX_ENV_VALUE_CHARS} characters"
    for ch in value:
        if unicodedata.category(ch) in _BAD_CHAR_CATEGORIES:
            if ch in "\r\n":
                return "contains a line break"
            if ch == "\0":
                return "contains a NUL character"
            return f"contains a control character (U+{ord(ch):04X})"
    if "${" in value:
        return "contains '${', which .env readers expand as a variable"
    if encode_env_line(key or "SD_ENV_VALUE", value) is None:
        return _unstorable_reason(key)
    return None


def validate_env_updates(updates: dict[str, Any], allowed_keys: Collection[str] | None = None) -> None:
    """Raise EnvValueError unless every key and value may be written to .env (see the block comment)."""
    for key, value in updates.items():
        if not isinstance(key, str) or not _ENV_KEY_RE.match(key):
            raise EnvValueError("refused: not a valid .env key name")
        if allowed_keys is not None:
            if key not in allowed_keys:
                raise EnvValueError(f"refused: {key} cannot be changed from the terminal")
        elif key in PROTECTED_ENV_KEYS or key.startswith(PROTECTED_ENV_PREFIXES):
            raise EnvValueError(f"refused: {key} cannot be changed from the terminal")
        problem = env_value_problem(value, key)
        if problem:
            raise EnvValueError(f"{key} {problem}")


def _split_lines(text: str) -> list[str]:
    """Lines split on \\n only (str.splitlines() also splits on U+0085, U+2028, \\x0c … inside other values)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [ln.removesuffix("\r") for ln in lines]


def _dotenv_parse(path: Path) -> dict[str, str | None] | None:
    """python-dotenv's reading of ``path`` (interpolation on, as load_dotenv does); None if it is not installed.
    A missing file reads as empty."""
    try:
        from dotenv import dotenv_values
    except ImportError:
        return None
    return dict(dotenv_values(path)) if path.exists() else {}


def _dotenv_parse_text(text: str) -> dict[str, str | None] | None:
    """python-dotenv's parser on ``text``; None if it is not installed. Used to test candidate lines: the parser
    itself (not dotenv_values) so a rejected candidate does not log "could not parse" warnings. Interpolation is
    not applied; it cannot change a value without '${', and such values are refused before any line is built
    (the whole-file check in persist_env_updates runs the full dotenv_values, interpolation included)."""
    try:
        from dotenv.parser import parse_stream
    except ImportError:
        return None
    return {b.key: b.value for b in parse_stream(io.StringIO(text)) if b.key is not None}


def _plain_parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _split_lines(text):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            out[key.strip()] = plain_env_value(val)
    return out


def _raw_parse(text: str) -> dict[str, str]:
    """How scripts/fetch_all_icici.py and scripts/icici_session_helper.py read .env: no quote removal."""
    out: dict[str, str] = {}
    for line in _split_lines(text):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            out[key.strip()] = val.strip()
    return out


def _readback_problem(before: Path, after: Path, after_text: str, updates: dict[str, str]) -> str | None:
    """Why the rewritten file would not read back as intended (None = fine). Names keys, never values."""
    plain, raw = _plain_parse(after_text), _raw_parse(after_text)
    for key, value in updates.items():
        if plain.get(key) != value:
            return f"{key} would not read back exactly (plain parser)"
        if key in RAW_READ_ENV_KEYS and raw.get(key) != value:
            return f"{key} would not read back exactly (raw parser)"
    new, old = _dotenv_parse(after), _dotenv_parse(before)
    if new is None or old is None:
        return None
    for key, value in updates.items():
        if new.get(key) != value:
            return f"{key} would not read back exactly (python-dotenv)"
    for key in sorted(set(old) | set(new)):
        if key in updates or old.get(key) == new.get(key):
            continue
        if old.get(key) is not None:                  # a value the file holds today would be lost or changed
            return f"{key} would change"
        # A key with no value today that gets one: a save that REPAIRS a .env the pre-fix raw writer corrupted (a
        # stray quote swallowed the next lines; the rewritten line gives them back). Allowed (round 3 review), but
        # never for a protected key: a repair must not switch on EXECUTION_LIVE_ALLOWED and the like; fix by hand.
        if key in PROTECTED_ENV_KEYS or key.startswith(PROTECTED_ENV_PREFIXES):
            return f"{key} would appear"
    return None


NEW_ENV_FILE_MODE = 0o600


def persist_env_updates(updates: dict[str, str], *, allowed_keys: Collection[str] | None = None,
                        env_path: Path | None = None) -> dict[str, Any]:
    """Set KEY=value in .env: update in place, exactly one line per key.

    The previous version treated "value unchanged" as "key absent" and appended a
    duplicate line every time the same token was re-pasted. Duplicates of an updated
    key are collapsed onto its first line; the write is atomic (tmp + rename).

    Every key and value is validated first (validate_env_updates): EnvValueError, and nothing is written,
    when one is refused. The new file is then re-read (see the block comment above) before it replaces .env;
    if it would not read back as intended, .env is left as it was and the result says
    ``{"persisted": False, "reason": ...}``. Writes are serialized and keep .env's permission bits.

    ``env_path`` names the file (scripts/daily_session_refresh.py passes the repo's .env); without it the
    file is located by find_env_file() and nothing is written when there is none. A named file that does
    not exist yet is created with mode 0600 (its folder must exist).
    """
    validate_env_updates(updates, allowed_keys)
    if env_path is None:
        env_path = find_env_file()
        if env_path is None:
            return {"persisted": False, "path": None}
    env_path = Path(env_path)

    with _ENV_WRITE_LOCK:
        try:
            mode = stat.S_IMODE(env_path.stat().st_mode)
            lines = _split_lines(env_path.read_text())
        except FileNotFoundError:                      # a new .env holds secrets: owner-only
            mode, lines = NEW_ENV_FILE_MODE, []
        for key, value in updates.items():
            idx = [i for i, ln in enumerate(lines) if re.match(rf"^{re.escape(key)}=", ln)]
            if idx:
                lines[idx[0]] = env_line(key, value)
                for i in reversed(idx[1:]):
                    del lines[i]
            else:
                lines.append(env_line(key, value))

        text = "\n".join(lines) + "\n"
        # A temp file of its own (O_EXCL, 0600) next to .env: _ENV_WRITE_LOCK is per process, and ui-api and
        # master-controller (/password, /userid) both write .env; a shared ".env.tmp" let one writer truncate the
        # other's temp file or rename it half-written (round 4a review, minor).
        fd, tmp_name = tempfile.mkstemp(dir=env_path.parent, prefix=f"{env_path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fchmod(fh.fileno(), mode)          # the original bits (umask cannot widen or narrow them)
            problem = _readback_problem(env_path, tmp, text, updates)
            if problem:
                _log.warning(json.dumps({"event": "env_write_refused", "reason": problem, "keys": sorted(updates)}))
                tmp.unlink(missing_ok=True)
                return {"persisted": False, "path": str(env_path), "reason": problem}
            tmp.replace(env_path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    return {"persisted": True, "path": str(env_path)}


# The Breeze SDK folds every failure into Exception("Unexpected error: …"), so failures are
# classified from the message. Network failures are retried; login failures are not.
_NETWORK_ERR = re.compile(r"ConnectTimeout|Max retries exceeded|timed out|Connection (aborted|refused|reset)|"
                          r"NameResolution|Failed to establish|RemoteDisconnected|ReadTimeout", re.I)
_EXPIRED_ERR = re.compile(r"session.*(expired|invalid|incorrect)|check session key|Resource not available|"
                          r"Invalid session", re.I)
_KEY_ERR = re.compile(r"Public Key does not exist|check api key|AppKey|api ?key.*(incorrect|invalid)", re.I)
PROBE_ATTEMPTS = 3
PROBE_BACKOFF_S = (2.0, 5.0)


# The public error kind (desktop review P4): the additive ``error_kind`` field of /api/positions/connection-status,
# /open-positions, /summary, /sector-exposure and /trade-history, and of daily_session_refresh's token check.
# 'expired' = ICICI refused the session token (log in again: /login); 'network' = ICICI's API could not be
# reached (NOT a login problem); 'credentials' = API key/secret missing or rejected; 'unknown' = anything else.
# null while connected.
PUBLIC_ERROR_KINDS = ("expired", "network", "credentials", "unknown")
_PUBLIC_KIND = {"session_expired": "expired", "network": "network", "credentials": "credentials"}


def public_error_kind(kind: str | None) -> str:
    """Probe/classifier kind ('session_expired', 'network', 'credentials', 'other' or None) → public kind."""
    return _PUBLIC_KIND.get(kind or "", "unknown")


def classify_breeze_error(message: str) -> tuple[str, str]:
    """(kind, user-facing message) for a failed Breeze login."""
    if _NETWORK_ERR.search(message):
        return "network", ("Couldn't reach ICICI's API server (api.icicidirect.com): the connection timed out "
                           f"{PROBE_ATTEMPTS} times. This is a network problem, not your session token. Check the "
                           "internet connection or VPN and retry; ICICI's API also has short outages.")
    if _EXPIRED_ERR.search(message):
        return "session_expired", ("The ICICI session has expired or is invalid. Session tokens last one trading "
                                   "day: log in again and paste the new token (or set up TOTP auto-login).")
    if _KEY_ERR.search(message):
        return "credentials", "ICICI rejected the API key or secret. Check them on the Broker tab."
    return "other", message


def probe_breeze_connection(api_key: str, api_secret: str, session_token: str,
                            sleep=time.sleep) -> dict[str, Any]:
    api_key = api_key.strip()
    api_secret = api_secret.strip()
    token = extract_session_token(session_token)

    if not api_key or not api_secret:
        return {"connected": False, "error_kind": "credentials", "error": "ICICI API key and secret are required."}
    if not token:
        return {"connected": False, "error_kind": "session_expired", "error": "ICICI session token is required."}

    import requests
    try:      # breeze_connect downloads ICICI's security master at import, with no timeout: use the cache
        from shared.breeze_cache import install as _breeze_cache_install
        _breeze_cache_install()
    except Exception:  # noqa: BLE001
        pass
    from breeze_connect import BreezeConnect

    original_get = requests.get

    def _get_with_timeout(url: str, **kwargs: Any):
        kwargs.setdefault("timeout", (10, 20))          # connect, read
        return original_get(url, **kwargs)

    last = ""
    for attempt in range(1, PROBE_ATTEMPTS + 1):
        requests.get = _get_with_timeout  # type: ignore[assignment]  # the SDK calls requests.get directly
        try:
            breeze = BreezeConnect(api_key=api_key)
            from shared.breeze_budget import ledger as _ledger      # PLAN §0.11: the probe's two ICICI calls are metered too
            # the LOGIN label, not the probe's: generate_session is the same ICICI call whichever path
            # makes it, and two labels meant two quotas, so neither governed the thing they both spend. The
            # one call the terminal cannot do without needs a single bound (F15 / Architecture).
            with _ledger().guard("ui-api.login", "generate_session"):
                breeze.generate_session(api_secret=api_secret, session_token=token)
            with _ledger().guard("ui-api.probe", "get_customer_details"):
                details = breeze.get_customer_details(api_session=token)
        except Exception as exc:  # noqa: BLE001 — the SDK raises bare Exception
            last = str(exc)
            kind, _ = classify_breeze_error(last)
            if kind != "network" or attempt == PROBE_ATTEMPTS:
                break
            sleep(PROBE_BACKOFF_S[min(attempt - 1, len(PROBE_BACKOFF_S) - 1)])
            continue
        finally:
            requests.get = original_get
        if details and details.get("Status") == 200:
            success = details.get("Success") or {}
            return {"connected": True, "account_name": success.get("idirect_user_name"),
                    "customer_id": success.get("idirect_userid"), "attempts": attempt}
        kind, message = classify_breeze_error(str(details))
        return {"connected": False, "error_kind": kind,
                "error": message if kind != "other" else f"Unexpected Breeze response: {details}"}
    kind, message = classify_breeze_error(last)
    return {"connected": False, "error_kind": kind, "error": message, "detail": last[:300]}


async def propagate_runtime_config(
    *,
    api_key: str,
    api_secret: str,
    session_token: str,
) -> dict[str, Any]:
    payload = {
        "api_key": api_key,
        "api_secret": api_secret,
        "session_token": extract_session_token(session_token),
    }
    targets = {
        "data_service": os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/"),
        "execution_service": os.environ.get("EXECUTION_SERVICE_URL", "http://localhost:8006").rstrip("/"),
    }

    results: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        for name, base_url in targets.items():
            try:
                endpoint = "/provider/configure" if name == "data_service" else "/broker/configure"
                response = await client.post(f"{base_url}{endpoint}", json=payload)
                results[name] = {
                    "ok": response.status_code == 200,
                    "status_code": response.status_code,
                    "body": response.json(),
                }
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "error": str(exc),
                }
    return results


async def collect_backend_status() -> dict[str, Any]:
    targets = {
        "data_service": (
            os.environ.get("DATA_SERVICE_URL", "http://localhost:8001").rstrip("/"),
            "/provider/status",
        ),
        "execution_service": (
            os.environ.get("EXECUTION_SERVICE_URL", "http://localhost:8006").rstrip("/"),
            "/broker/status",
        ),
    }

    results: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for name, (base_url, endpoint) in targets.items():
            try:
                response = await client.get(f"{base_url}{endpoint}")
                results[name] = {
                    "ok": response.status_code == 200,
                    "status_code": response.status_code,
                    "body": response.json(),
                }
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "error": str(exc),
                }
    return results
