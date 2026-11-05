"""Client error reports from the terminal UI (desktop review completeness-02; wave-2 contract K1).

POST /api/client-errors   {message, stack?, tab?, build?, url?, kind?}   ->  204 No Content

The UI (per-tab error boundaries, global-error.tsx, window ``error`` / ``unhandledrejection``) sends one
report per distinct error, fire-and-forget, in the browser and in the desktop app alike (same origin). Each
accepted report becomes ONE structured JSON line ``{"event": "client_error", ...}`` in the ui-api log
(.logs/ui-api.log), so a WebKit-only exception after hours of use leaves the build, tab, time and stack
behind instead of vanishing with the red overlay.

Rules
- Body: a JSON object, at most MAX_BODY_BYTES (8 KB; 413 beyond). ``Content-Type`` application/json, or
  text/plain (``navigator.sendBeacon`` with a string body); anything else 415. Malformed: 422.
- ``message`` is required (a non-empty string). Every other field is optional; unknown fields are ignored.
  Strings are cut to the FIELD_LIMITS, control, format and line/paragraph-separator characters are replaced by
  spaces (C0/C1 incl. U+0085, U+2028/U+2029, bidi overrides; newlines and tabs kept in ``stack``), so one report
  is always one log line for any line splitter (desktop review RAPI-07), and credentials that may ride inside an
  error text are masked (RAPI-06): the values of ``api_key``/``app_key``/``*_key`` secrets, ``apisession``,
  ``*token`` (session_token, access_token, ...), ``*secret``, ``password``/``passwd``/``passphrase``, ``pin``/
  ``mpin``/``tpin`` and ``otp`` written as ``name=value``, ``name: value``, JSON ``"name": "value"``,
  ``'name': 'value'``, ``\\"name\\":\\"value\\"`` (JSON inside a string) or URL-encoded; a quoted value is masked
  up to its closing quote whatever it contains (spaces, ``#``, ``&``, ``,``, ``}``, escaped quotes), and one cut
  off before its closing quote to the end of the line. The whole value of an ``Authorization`` (the scheme word
  is kept) or ``Cookie`` header, and Bearer / Basic credentials that look like one (not "Basic settings").
- ``url``: only the path and the terminal's own ``tab`` / ``sym`` query parameters are kept (no other query
  string, no fragment, no host).
- ``kind``: ``[a-z0-9_.-]{1,32}``, else ``unknown``.
- Nothing from the request itself is logged: no headers, cookies, client address or user agent.
- Rate limit per process: RATE_LIMIT reports per RATE_WINDOW_S (30 per minute). Reports over the limit are
  still answered 204 (the reporter is fire-and-forget; a 429 would only add console noise to a page that is
  already failing), counted, and the count is logged once with the next accepted report
  (``dropped_since_last``). The response header ``X-Client-Error: logged | dropped`` says which happened.
- Cross-site pages cannot post here: the Host/Origin guard (shared/http_guard.py) refuses foreign origins,
  like every other write. There is no GET (reports are read from the log, not from the API).
"""
from __future__ import annotations

import json
import logging
import re
import sys
import threading
import time
import unicodedata
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from errors import fail
from fastapi import APIRouter, Request, Response

router = APIRouter()

MAX_BODY_BYTES = 8 * 1024
RATE_LIMIT = 30
RATE_WINDOW_S = 60.0
FIELD_LIMITS = {"message": 500, "stack": 4000, "tab": 40, "build": 64, "url": 300, "kind": 32}
_KIND_RE = re.compile(r"^[a-z0-9_.-]{1,32}$")
_URL_PARAMS = ("tab", "sym")

# ── credential masking (RAPI-06; round 3 review: a quoted value is masked WHOLE) ─────────────────────────────
# A credential NAME followed by a separator: name=value · name: value · "name": "value" (JSON) · 'name': 'value'
# · \"name\":\"value\" (JSON inside a JSON string) · %22name%22%3A%22value%22 / name%3Dvalue (URL-encoded).
# Header names (Authorization, Cookie) mask their whole value; credential keys mask one value.
_NAME_START = r"(?:(?<![A-Za-z0-9_])|(?<=%22)|(?<=%27))"         # a word start, also right after an encoded quote
_SECRET_NAME_SEP_RE = re.compile(
    rf"""(?i)(?:(?P<hdr>{_NAME_START}(?:proxy-)?authorization|{_NAME_START}set-cookie|{_NAME_START}cookie)"""
    rf"""|(?P<key>{_NAME_START}[a-z0-9_]*(?:api_?key|app_?key|secret_?key|session_?key|private_?key|apisession"""
    rf"""|api_session|token|secret|password|passwd|passphrase)|{_NAME_START}(?:[mt]?pin|t?otp)\b))"""
    r"""(?P<sep>(?:\\*["']|%2[27])?(?:[ \t]|%20)*(?:[:=]|%3[ad])(?:[ \t]|%20)*)""")   # never across a line
_OPEN_QUOTE_RE = re.compile(r"(?i)\\*[\"']|%2[27]")
# An unquoted value: up to whitespace or a quote; '&' ends it only where the next 'name=' pair starts (a URL or
# form body), and , ; ) ] } only where they close a structure (followed by space, the end or another closer).
# '#' and '%XX' are kept: a password's '#' must not end the mask (URL fragments are dropped by _clean_url).
_UNQUOTED_VALUE_RE = re.compile(
    r"""(?:[^\s"'\\&,;)\]}]|\\(?!["'])|&(?![A-Za-z0-9_.\-\[\]%]+=)|[,;)\]}](?=[^\s,;)\]}"']))+""")
_AUTH_SCHEME_RE = re.compile(r"(?i)(?:bearer|basic|token|digest|negotiate|apikey|hmac[a-z0-9-]*)[ \t]+")
_NOT_SECRET = frozenset({"null", "undefined", "none", "true", "false", "nan"})   # kept: they say what went wrong
_BEARER_RE = re.compile(r"(?i)\b(bearer)([ \t]+)([A-Za-z0-9._~+/=-]{8,})")
_BASIC_RE = re.compile(r"(?i)\b(basic)([ \t]+)([A-Za-z0-9+/]{8,}={0,2})")
_REDACTED = "<redacted>"
_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})   # controls, format/bidi, separators
_ACCEPTED_TYPES = ("application/json", "text/plain")


class _JsonLineFormatter(logging.Formatter):
    """One JSON object per line (the same shape as shared/http_guard.py's lines)."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "component": "ui",
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        return json.dumps(payload, default=str, ensure_ascii=False)


# Own handler: ui-api configures no root logging, so a plain logger's lines would never reach the log file.
log = logging.getLogger("suryadhana.client_errors")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(_JsonLineFormatter())
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


class _RateLimit:
    """Sliding window: at most ``limit`` admits per ``window_s``; counts what it refuses."""

    def __init__(self, limit: int = RATE_LIMIT, window_s: float = RATE_WINDOW_S) -> None:
        self.limit = limit
        self.window_s = window_s
        self._times: deque[float] = deque()
        self._dropped = 0
        self._lock = threading.Lock()

    def admit(self, now: float | None = None) -> tuple[bool, int]:
        """(admitted, reports dropped since the last admitted one; reset when admitted)."""
        t = time.monotonic() if now is None else now
        with self._lock:
            while self._times and t - self._times[0] >= self.window_s:
                self._times.popleft()
            if len(self._times) >= self.limit:
                self._dropped += 1
                return False, self._dropped
            self._times.append(t)
            dropped, self._dropped = self._dropped, 0
            return True, dropped


_limiter = _RateLimit()


def _safe_char(ch: str, allowed: str) -> str:
    if ch in allowed:
        return ch
    if " " <= ch < "\x7f":                       # printable ASCII: the common case
        return ch
    if ch < " " or ch == "\x7f" or unicodedata.category(ch) in _UNSAFE_CATEGORIES:
        return " "
    return ch


def _end_of_line(text: str, start: int) -> int:
    eol = text.find("\n", start)
    return len(text) if eol < 0 else eol


def _closing_quote(text: str, start: int, quote: str) -> int:
    """Where the value opened by ``quote`` (ending at ``start``) ends: the index of its closing quote. With no
    closing quote on the line (a cut-off message) the rest of the line is the value, so it is masked too."""
    eol = _end_of_line(text, start)
    if quote in ('"', "'"):                       # JSON / JS / Python string: backslash escapes the next char
        i = start
        while i < eol:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == quote:
                return i
            i += 1
        return eol
    if quote.startswith("%"):                      # URL-encoded %22 / %27; %5C%22 is an escaped quote inside it
        m = re.compile(r"(?<!%5[cC])" + re.escape(quote), re.IGNORECASE).search(text, start, eol)
    else:                                          # \" inside a JSON string: the same token, not escaped deeper
        m = re.compile(r"(?<!\\)" + re.escape(quote)).search(text, start, eol)
    return m.start() if m else eol


def _mask_secrets(text: str) -> str:
    """Mask the value after every credential name (see _SECRET_NAME_SEP_RE): a quoted value up to its closing
    quote, whatever it contains (spaces, '#', '&', ',', '}', escaped quotes); an unquoted one as
    _UNQUOTED_VALUE_RE reads it; an Authorization / Cookie header's whole value (the auth scheme is kept)."""
    out: list[str] = []
    pos = 0
    while (m := _SECRET_NAME_SEP_RE.search(text, pos)) is not None:
        out.append(text[pos:m.end()])
        pos = m.end()
        header = m.group("hdr") is not None
        quote = _OPEN_QUOTE_RE.match(text, pos)
        if quote:
            body = quote.end()
            end = _closing_quote(text, body, quote.group(0))
            scheme = _AUTH_SCHEME_RE.match(text, body, end) if header else None
            keep = scheme.group(0) if scheme else ""
            out.append(quote.group(0) + keep + (_REDACTED if end > body + len(keep) else ""))
            pos = end
            continue
        if header:
            scheme = _AUTH_SCHEME_RE.match(text, pos)
            single = scheme is not None and scheme.group(0).split()[0].lower() in {"bearer", "basic", "token",
                                                                                  "negotiate", "apikey"}
            if scheme is not None and single:       # one credential word after the scheme
                cred = re.compile(r"[^\s\"']+").match(text, scheme.end())
                if cred is not None and cred.group(0).lower() in _NOT_SECRET:     # 'Bearer undefined' says why
                    out.append(scheme.group(0))
                    pos = scheme.end()
                    continue
                out.append(scheme.group(0) + (_REDACTED if cred else ""))
                pos = cred.end() if cred else scheme.end()
            else:                                   # Digest / HMAC parameters, a cookie list, no scheme: all of it
                eol = _end_of_line(text, pos)
                if text[pos:eol].strip().lower() not in _NOT_SECRET:
                    out.append(_REDACTED if eol > pos else "")
                    pos = eol
            continue
        value = _UNQUOTED_VALUE_RE.match(text, pos)
        if value is None:
            continue
        word = value.group(0)
        if word.lower() in _NOT_SECRET or (len(word) == 1 and not word.isalnum()):   # 'token: <' is not one
            continue
        out.append(_REDACTED)
        pos = value.end()
    out.append(text[pos:])
    return "".join(out)


def _looks_like_credential(word: str) -> bool:
    """A Bearer / Basic credential, not an English word ('Basic settings', 'Bearer authentication')."""
    return bool(re.search(r"[0-9+/=._~-]", word)) or (sum(c.isupper() for c in word) >= 2
                                                      and any(c.islower() for c in word))


def _mask_scheme_credential(m: re.Match[str]) -> str:
    return f"{m.group(1)}{m.group(2)}{_REDACTED}" if _looks_like_credential(m.group(3)) else m.group(0)


def _clean_text(value: str, limit: int, *, keep_newlines: bool = False) -> str:
    allowed = "\n\t" if keep_newlines else ""
    text = "".join(_safe_char(ch, allowed) for ch in value)
    text = _mask_secrets(text)
    text = _BEARER_RE.sub(_mask_scheme_credential, text)
    text = _BASIC_RE.sub(_mask_scheme_credential, text)
    return text[:limit]


def _clean_url(value: str) -> str | None:
    """Path plus the terminal's own tab/sym parameters; nothing else (no host, other query, fragment)."""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    path = parts.path or "/"
    if not path.startswith("/"):
        return None
    keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if k in _URL_PARAMS]
    url = path + ("?" + urlencode(keep) if keep else "")
    return _clean_text(url, FIELD_LIMITS["url"])


def sanitize_report(body: Any) -> dict[str, Any]:
    """The fields that are logged, or an HTTP 422 (raised) when the body is not a usable report."""
    if not isinstance(body, dict):
        fail(422, "invalid", "body must be a JSON object {message, stack?, tab?, build?, url?, kind?}")
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        fail(422, "invalid", "message must be a non-empty string")
    out: dict[str, Any] = {"message": _clean_text(message.strip(), FIELD_LIMITS["message"])}
    for name in ("stack", "tab", "build"):
        value = body.get(name)
        if value is None:
            continue
        if not isinstance(value, str):
            fail(422, "invalid", f"{name} must be a string")
        text = _clean_text(value, FIELD_LIMITS[name], keep_newlines=(name == "stack"))
        if text.strip():
            out[name] = text
    url = body.get("url")
    if url is not None:
        if not isinstance(url, str):
            fail(422, "invalid", "url must be a string")
        cleaned = _clean_url(url)
        if cleaned:
            out["url"] = cleaned
    kind = body.get("kind")
    if kind is not None and not isinstance(kind, str):
        fail(422, "invalid", "kind must be a string")
    out["kind"] = kind if isinstance(kind, str) and _KIND_RE.match(kind) else "unknown"
    return out


async def _read_body(request: Request) -> Any:
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if media_type not in _ACCEPTED_TYPES:
        fail(415, "invalid", "Content-Type must be application/json (or text/plain from sendBeacon)")
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > MAX_BODY_BYTES:
                fail(413, "invalid", f"report larger than {MAX_BODY_BYTES // 1024} KB")
        except ValueError:
            fail(400, "invalid", "bad Content-Length")
    buf = bytearray()
    async for chunk in request.stream():
        buf.extend(chunk)
        if len(buf) > MAX_BODY_BYTES:
            fail(413, "invalid", f"report larger than {MAX_BODY_BYTES // 1024} KB")
    try:
        return json.loads(bytes(buf).decode("utf-8"))
    except (ValueError, RecursionError):
        fail(422, "invalid", "body is not valid JSON")


@router.post("", status_code=204, response_class=Response)
async def report_client_error(request: Request) -> Response:
    """Log one UI error report (see the module docstring). Always 204 for a well-formed report."""
    fields = sanitize_report(await _read_body(request))
    admitted, dropped = _limiter.admit()
    if not admitted:
        return Response(status_code=204, headers={"X-Client-Error": "dropped"})
    if dropped:
        fields["dropped_since_last"] = dropped
    log.warning("client_error", extra={"fields": fields})
    return Response(status_code=204, headers={"X-Client-Error": "logged"})
