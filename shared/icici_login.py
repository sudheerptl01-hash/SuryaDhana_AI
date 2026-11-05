"""
shared/icici_login.py — unattended ICICI Breeze login for the daily session token.

ICICI's API login page takes the iDirect user ID + password, then a 6-digit code, and
finally redirects the browser to the app's registered URL with `?apisession=<token>`.
With TOTP enabled on the ICICI account (Settings on icicidirect.com) that code comes
from an authenticator app, so it can be generated here from the TOTP secret (RFC 6238)
and the whole login runs without a person.

Safety rules — a broker locks an account after repeated failures, so this module:
  * types the code at most once per run and never retries a rejected login or code;
  * stops with LoginNeedsHuman on a captcha, an SMS-OTP panel or any error text.

Secrets are read from the environment/.env first, then from the macOS login Keychain
(service "suryadhana", account = variable name). Keeping ICICI_TOTP_SECRET in the
Keychain means a leaked .env alone (which holds the password) is not a full login.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import parse_qs, quote, unquote, urlparse

KEYCHAIN_SERVICE = "suryadhana"
LOGIN_URL = "https://api.icicidirect.com/apiuser/login?api_key={api_key}"

# Selectors of ICICI's login page (api.icicidirect.com/apiuser/login), read from its markup.
USER_ID_INPUT = "#txtuid"
PASSWORD_INPUT = "#txtPass"
TERMS_CHECKBOX = "#chkssTnc"
LOGIN_BUTTON = "#btnSubmit"
CODE_BOXES = "#pnlOTP input[tg-nm=otp]"
SMS_FALLBACK_LINK = "#pnlOTP a[onclick*=goforotp]"     # "Having issues? Verify with OTP" on the TOTP panel
CODE_ERROR = "#otperr"

_TOKEN_KEYS = ("apisession", "api_session", "session_token")


class LoginNeedsHuman(RuntimeError):
    """Stop and ask the account owner: retrying on our own could lock the account."""


class LoginTransient(RuntimeError):
    """Network or page-timing trouble: safe to try again later."""


# ── TOTP (RFC 6238 over RFC 4226) ─────────────────────────────────────────────────

@dataclass(frozen=True)
class TotpSpec:
    secret: bytes
    digits: int = 6
    period: int = 30
    algorithm: str = "sha1"


def parse_totp_secret(value: str) -> TotpSpec:
    """Accept a base32 secret (spaces / lower case fine) or a full otpauth:// URI."""
    raw = (value or "").strip()
    digits, period, algorithm = 6, 30, "sha1"
    if raw.lower().startswith("otpauth://"):
        q = {k.lower(): v[0] for k, v in parse_qs(urlparse(raw).query).items()}
        raw = q.get("secret", "")
        digits = int(q.get("digits", digits))
        period = int(q.get("period", period))
        algorithm = q.get("algorithm", algorithm).lower()
    b32 = re.sub(r"[\s-]", "", unquote(raw)).upper()
    if not b32:
        raise ValueError("empty TOTP secret")
    b32 += "=" * (-len(b32) % 8)
    try:
        secret = base64.b32decode(b32, casefold=True)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise ValueError("TOTP secret is not valid base32") from exc
    if algorithm not in ("sha1", "sha256", "sha512"):
        raise ValueError(f"unsupported TOTP algorithm {algorithm!r}")
    return TotpSpec(secret, digits, period, algorithm)


def totp(spec: TotpSpec, for_time: float) -> str:
    counter = int(for_time // spec.period)
    digest = hmac.new(spec.secret, struct.pack(">Q", counter), getattr(hashlib, spec.algorithm)).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** spec.digits)
    return str(code).zfill(spec.digits)


def fresh_totp(spec: TotpSpec, clock: Callable[[], float] = time.time,
               sleep: Callable[[float], None] = time.sleep, min_remaining: float = 5.0) -> str:
    """A code with at least `min_remaining` seconds of validity left (waits for the next
    window otherwise), so it cannot expire between typing and ICICI checking it."""
    now = clock()
    remaining = spec.period - (now % spec.period)
    if remaining < min_remaining:
        sleep(remaining + 0.5)
        now = clock()
    return totp(spec, now)


# ── Secrets ───────────────────────────────────────────────────────────────────────

def read_secret(name: str, env: Optional[Mapping[str, str]] = None,
                runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """`name` from env (.env merged by the caller), else the macOS login Keychain."""
    value = ((env if env is not None else os.environ).get(name) or "").strip()
    if value or sys.platform != "darwin":
        return value
    try:
        res = runner(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", name, "-w"],
                     capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return res.stdout.strip() if res.returncode == 0 else ""


# ── Token + page helpers ──────────────────────────────────────────────────────────

def extract_token(url: str, post_data: Optional[str] = None) -> str:
    """Session token from the redirect: query string (GET) or form body (POST)."""
    for blob in (urlparse(url).query, urlparse(url).fragment, post_data or ""):
        for key, vals in parse_qs(blob).items():
            if key.lower() in _TOKEN_KEYS and vals and vals[0].strip():
                return vals[0].strip()
    return ""


def classify_code_panel(text: str) -> str:
    """'totp' (authenticator code), 'sms' (code sent to phone/e-mail) or 'unknown'."""
    t = text or ""
    if re.search(r"\bTOTP\b|authenticat|time[\s-]*based", t, re.I):
        return "totp"
    if re.search(r"\bsent\b|\bSMS\b|mobile|e-?mail|registered", t, re.I):
        return "sms"
    return "unknown"


def mask(value: str, keep: int = 3) -> str:
    return (value[:keep] + "•" * max(0, len(value) - keep)) if value else ""


_SUCCESS_HTML = ("<html><body style='font-family:sans-serif;padding:40px;background:#05070a;color:#d6dbe4'>"
                 "<h2 style='color:#16d98a'>SuryaDhana: ICICI session captured</h2>"
                 "<p>You can close this window.</p></body></html>")

_VISIBLE_ERROR_JS = """() => {
  const out = [];
  for (const el of document.querySelectorAll('#dvgetotp, #pnlLogmain, [id*="err" i], .error, .alert')) {
    if (!(el.offsetWidth || el.offsetHeight)) continue;
    const t = (el.innerText || '').trim();
    if (t && t.length < 300 && /invalid|incorrect|wrong|locked|blocked|error|fail|expired|not\\s+valid/i.test(t)) out.push(t);
  }
  return out.join(' | ');
}"""

_CAPTCHA_JS = """() => Array.from(document.querySelectorAll('img, input, iframe, div'))
  .some(el => (el.offsetWidth || el.offsetHeight) &&
              /captcha/i.test([el.id, el.name, el.src, el.className].join(' ')))"""


def _launch(pw, headless: bool):
    try:  # the installed Google Chrome, same as the UI audit harness
        return pw.chromium.launch(channel="chrome", headless=headless)
    except Exception:
        return pw.chromium.launch(headless=headless)


def browser_login(api_key: str, user_id: str, password: str, totp_spec: Optional[TotpSpec], *,
                  login_url: Optional[str] = None, headless: bool = True, attended: bool = False,
                  panel_timeout_s: float = 25.0, finish_timeout_s: float = 30.0,
                  manual_timeout_s: float = 180.0, screenshot_path: Optional[str] = None,
                  log: Callable[[str], None] = print,
                  otp_provider: Optional[Callable[[str], Optional[str]]] = None) -> str:
    """Drive ICICI's real login page and return the session token.

    `attended=True` (visible browser) lets a person type the code when there is no TOTP
    secret or ICICI sent an SMS code. `otp_provider(panel_text)` supplies that code
    unattended (the Telegram hand-off: it asks you and waits for your reply; None = gave up).
    Without either, unattended runs raise LoginNeedsHuman.
    """
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    if not (user_id and password):
        raise LoginNeedsHuman("ICICI_CLIENT_ID (iDirect user ID) or ICICI_PASSWORD is missing")
    url = login_url or LOGIN_URL.format(api_key=quote(api_key, safe=""))
    captured: list[str] = []
    dialogs: list[str] = []

    def _capture(route) -> None:
        req = route.request
        try:
            body = req.post_data
        except Exception:
            body = None
        token = extract_token(req.url, body)
        if token and not captured:
            captured.append(token)
            route.fulfill(status=200, content_type="text/html", body=_SUCCESS_HTML)
        else:
            route.continue_()

    def _switch_to_sms(page) -> str:
        link = page.query_selector(SMS_FALLBACK_LINK)
        if link is None:
            raise LoginNeedsHuman("ICICI wants the authenticator code (set ICICI_TOTP_SECRET) and shows no SMS option")
        link.click()
        try:      # the panel is replaced: wait until it no longer asks for the authenticator code
            page.wait_for_function(
                "() => { const p = document.querySelector('#pnlOTP');"
                " return p && !/authenticat|\\bTOTP\\b/i.test(p.innerText) && p.querySelector('input[tg-nm=otp]'); }",
                timeout=panel_timeout_s * 1000)
        except PWTimeout:
            why = " | ".join(filter(None, [page.evaluate(_VISIBLE_ERROR_JS), *dialogs]))
            raise LoginTransient(f"ICICI did not switch to an SMS OTP{': ' + why if why else ''}")
        return page.inner_text("#pnlOTP")

    def _submit_code(page, code: str, what: str) -> None:
        """Type the code into ICICI's box(es), submit, wait for the token; one attempt."""
        boxes = page.query_selector_all(CODE_BOXES)
        if len(boxes) == 1:
            boxes[0].fill(code)
        else:
            for box, digit in zip(boxes, code):
                box.fill(digit)
        submitted = page.evaluate("() => typeof submitotp === 'function' ? (submitotp(), true) : false")
        if not submitted:
            page.click("#pnlOTP button:visible, #pnlOTP input[type=button]:visible")
        log(f"  submitted {what} (single attempt)")
        if not _wait_for_token(finish_timeout_s, page):
            err = ""
            if page.query_selector(CODE_ERROR) and page.is_visible(CODE_ERROR):
                err = page.inner_text(CODE_ERROR).strip()
            why = " | ".join(filter(None, [err, page.evaluate(_VISIBLE_ERROR_JS), *dialogs]))
            if why:
                raise LoginNeedsHuman(f"ICICI rejected the {what}: {why}")
            raise LoginTransient("no session token after submitting the code")

    def _wait_for_token(seconds: float, page) -> bool:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if captured:
                return True
            page.wait_for_timeout(250)
        return bool(captured)

    with sync_playwright() as pw:
        browser = _launch(pw, headless)
        context = browser.new_context()
        # The redirect goes to the app's own URL (e.g. https://127.0.0.1): catch it before the
        # browser tries to connect. ICICI's own pages are never touched.
        context.route(lambda u: not urlparse(u).netloc.lower().endswith("icicidirect.com"), _capture)
        page = context.new_page()
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        ok = False
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_selector(USER_ID_INPUT, state="visible", timeout=20_000)
            page.fill(USER_ID_INPUT, user_id)
            page.fill(PASSWORD_INPUT, password)
            if page.query_selector(TERMS_CHECKBOX) and not page.is_checked(TERMS_CHECKBOX):
                page.check(TERMS_CHECKBOX)
            page.click(LOGIN_BUTTON)
            log("  submitted user ID + password")

            try:
                page.wait_for_selector(CODE_BOXES, state="visible", timeout=panel_timeout_s * 1000)
            except PWTimeout:
                why = " | ".join(filter(None, [page.evaluate(_VISIBLE_ERROR_JS), *dialogs]))
                if page.evaluate(_CAPTCHA_JS):
                    raise LoginNeedsHuman("ICICI is showing a captcha — log in once by hand")
                if why:
                    raise LoginNeedsHuman(f"ICICI rejected the login: {why}")
                raise LoginTransient("the 6-digit code panel never appeared")
            if page.evaluate(_CAPTCHA_JS):
                raise LoginNeedsHuman("ICICI is showing a captcha — log in once by hand")

            panel_text = page.inner_text("#pnlOTP")
            mode = classify_code_panel(panel_text)
            log(f"  code panel: {mode}")
            if mode != "sms" and totp_spec is None and otp_provider is not None:
                # The account uses an authenticator app (ICICI: "Verify TOTP") and we don't hold its secret. ICICI
                # texts an OTP only after "Having issues? Verify with OTP" is clicked; without that no SMS is sent.
                panel_text = _switch_to_sms(page)
                mode = classify_code_panel(panel_text)
                log(f"  asked ICICI to text an OTP instead: panel now {mode}")
            if mode == "sms" or totp_spec is None:
                reason = ("ICICI sent an SMS/e-mail OTP (TOTP is not enabled on the account)"
                          if mode == "sms" else "ICICI_TOTP_SECRET is not configured")
                if otp_provider is not None:              # unattended hand-off (Telegram): ask, wait, submit
                    log(f"  {reason}: asking for the code…")
                    code = otp_provider(panel_text)
                    if not code:
                        raise LoginNeedsHuman("no OTP received in time")
                    _submit_code(page, code, "SMS OTP")
                elif not attended:
                    raise LoginNeedsHuman(reason)
                else:
                    log(f"  {reason}: type the code in the browser window…")
                    if not _wait_for_token(manual_timeout_s, page):
                        raise LoginNeedsHuman("no code entered in time")
            else:
                _submit_code(page, fresh_totp(totp_spec), "authenticator code")
            ok = True
            return captured[0]
        except PWTimeout as exc:
            raise LoginTransient(f"ICICI page timed out: {exc}".splitlines()[0]) from exc
        finally:
            if not ok and screenshot_path:
                try:
                    page.screenshot(path=screenshot_path, full_page=True)
                    log(f"  screenshot of the failure: {screenshot_path}")
                except Exception:
                    pass
            browser.close()
