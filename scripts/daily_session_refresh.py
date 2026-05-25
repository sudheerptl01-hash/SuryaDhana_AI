#!/usr/bin/env python
"""
ICICI Breeze — Daily Session Token Auto-Refresh
================================================
Run once each morning before the market opens.

What it does:
  1. Checks if a fresh token was already obtained today — exits immediately if so.
  2. Opens a real Chromium browser (via Playwright) at the ICICI login page.
  3. Auto-fills your Client ID and Password from .env.
  4. Pauses for you to enter the OTP sent to your registered mobile.
  5. Captures the session_token from the redirect URL automatically.
  6. Writes ICICI_SESSION_TOKEN into .env and stamps today's date.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/daily_session_refresh.py

Prerequisites in .env:
    ICICI_API_KEY      — your Breeze API key
    ICICI_CLIENT_ID    — your ICICI Direct client ID (login username)
    ICICI_PASSWORD     — your ICICI Direct login password
    ICICI_SESSION_TOKEN — updated by this script automatically

Run once:   python scripts/daily_session_refresh.py
Force-run:  python scripts/daily_session_refresh.py --force
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"
CACHE_FILE = ROOT / ".session_cache.json"

ICICI_LOGIN_URL = "https://api.icicidirect.com/apiuser/login?api_key={api_key}"  # api_key is URL-encoded at call site
OTP_WAIT_SECONDS = 120  # how long to wait for the user to enter OTP


# ── .env helpers ──────────────────────────────────────────────────────────────

def _read_env() -> dict[str, str]:
    result: dict[str, str] = {}
    if not ENV_FILE.exists():
        return result
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip()
    return result


def _write_env_value(key: str, value: str) -> None:
    content = ENV_FILE.read_text()
    pattern = rf"^{re.escape(key)}=.*$"
    replacement = f"{key}={value}"
    new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    if new_content == content:
        # Key not found — append it
        new_content = content.rstrip() + f"\n{key}={value}\n"
    ENV_FILE.write_text(new_content)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _already_refreshed_today() -> bool:
    if not CACHE_FILE.exists():
        return False
    try:
        cache = json.loads(CACHE_FILE.read_text())
        return cache.get("date") == str(date.today())
    except Exception:
        return False


def _stamp_today(token: str) -> None:
    CACHE_FILE.write_text(json.dumps({"date": str(date.today()), "token": token[:6] + "***"}))


# ── Token extraction ──────────────────────────────────────────────────────────

def _extract_token_from_url(url: str) -> str | None:
    # ICICI uses 'apisession' in the redirect URL (not 'session_token')
    _PARAM_NAMES = ("apisession", "session_token", "SessionToken", "apiSession", "api_session")
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        for key in _PARAM_NAMES:
            token = params.get(key, [None])[0]
            if token:
                return token
        # Also check hash fragment
        if parsed.fragment:
            fparams = parse_qs(parsed.fragment)
            for key in _PARAM_NAMES:
                token = fparams.get(key, [None])[0]
                if token:
                    return token
    except Exception:
        pass
    return None


def _extract_token_from_page(page_content: str) -> str | None:
    match = re.search(
        r"(?:apisession|session_token|apiSession)[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_\-]+)",
        page_content,
    )
    return match.group(1) if match else None


# ── Browser automation ────────────────────────────────────────────────────────

def _run_browser_flow(api_key: str, client_id: str, password: str) -> str:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    print("\n  Opening ICICI login in browser...")
    print("  → The browser will auto-fill your Client ID and Password.")
    print("  → Enter the OTP on your phone when prompted.")
    print(f"  → You have {OTP_WAIT_SECONDS} seconds to complete OTP entry.\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, slow_mo=500)
        context = browser.new_context()
        page = context.new_page()

        captured_token: list[str] = []

        # ── Intercept the localhost redirect BEFORE Chrome tries to connect ────
        # ICICI redirects to http://127.0.0.1/?session_token=XXX after login.
        # Without interception Playwright navigates there, gets ERR_CONNECTION_REFUSED,
        # and replaces the URL with chrome-error:// — losing the token.
        # We route all 127.0.0.1/localhost requests, grab the token, show a
        # success page, and abort the real network request.
        def _intercept_redirect(route):
            url = route.request.url
            token = _extract_token_from_url(url)
            if token and not captured_token:
                captured_token.append(token)
                print(f"\n  [AUTO] Session token captured from redirect URL!")
                route.fulfill(
                    status=200,
                    content_type="text/html",
                    body="<html><body style='font-family:sans-serif;padding:40px'>"
                         "<h2 style='color:green'>✓ Login successful!</h2>"
                         "<p>Session token captured. You can close this window.</p>"
                         "</body></html>",
                )
            else:
                route.abort()

        context.route("http://127.0.0.1/**", _intercept_redirect)
        context.route("http://localhost/**",  _intercept_redirect)
        context.route("https://127.0.0.1/**", _intercept_redirect)
        context.route("https://localhost/**",  _intercept_redirect)

        # Fallback: also watch all responses and navigations
        def _on_response(response):
            url = response.url
            token = _extract_token_from_url(url)
            if token and not captured_token:
                captured_token.append(token)

        def _on_navigation(frame):
            if frame == page.main_frame:
                url = page.url
                token = _extract_token_from_url(url)
                if token and not captured_token:
                    captured_token.append(token)

        page.on("response", _on_response)
        page.on("framenavigated", _on_navigation)

        login_url = ICICI_LOGIN_URL.format(api_key=quote(api_key, safe=""))
        page.goto(login_url, wait_until="domcontentloaded", timeout=45_000)

        # ── Step 1: Fill Client ID ─────────────────────────────────────────────
        if client_id:
            _fill_field(page, [
                'input[name="userId"]',
                'input[id="userId"]',
                'input[placeholder*="Client"]',
                'input[placeholder*="User"]',
                'input[type="text"]:visible',
            ], client_id, label="Client ID")

        # ── Step 2: Fill Password ──────────────────────────────────────────────
        if password:
            _fill_field(page, [
                'input[name="password"]',
                'input[id="password"]',
                'input[type="password"]:visible',
            ], password, label="Password")

        # ── Step 3: Accept Terms & Conditions (checkbox or agree button) ───────
        _accept_terms(page)
        time.sleep(0.5)  # let page re-enable the login button after T&C check

        # ── Step 4: Click login/submit ─────────────────────────────────────────
        _click_button(page, [
            'button[type="submit"]',
            'button:text("Login")',
            'button:text("Sign In")',
            'button:text("Submit")',
            'input[type="submit"]',
            'a:text("Login")',
        ])

        print("  [WAITING] Enter the OTP in the browser window...")

        # ── Step 4: Wait for OTP completion / redirect ─────────────────────────
        deadline = time.time() + OTP_WAIT_SECONDS
        while time.time() < deadline:
            if captured_token:
                break
            # Also check current page URL
            token = _extract_token_from_url(page.url)
            if token:
                captured_token.append(token)
                break
            # Check page content for token
            try:
                content = page.content()
                token = _extract_token_from_page(content)
                if token:
                    captured_token.append(token)
                    break
            except Exception:
                pass
            time.sleep(2)

        # ── Step 5: Fallback — ask user to paste URL ───────────────────────────
        if not captured_token:
            print("\n  [MANUAL FALLBACK] Could not auto-capture the session token.")
            print("  After login completes, copy the full redirect URL from the browser.")
            current_url = page.url
            print(f"  Current URL: {current_url}\n")
            try:
                pasted = input("  Paste the redirect URL (or just the session_token value): ").strip()
            except EOFError:
                print("\n[ERROR] This script must be run from an interactive terminal, not a pipe.")
                print("  Run: /Users/sudheer/Desktop/jupyter_env/bin/python scripts/daily_session_refresh.py")
                browser.close()
                sys.exit(1)
            if pasted.startswith("http"):
                token = _extract_token_from_url(pasted)
                captured_token.append(token or pasted)
            else:
                captured_token.append(pasted)

        browser.close()

    if not captured_token or not captured_token[0]:
        raise RuntimeError("Failed to obtain session token from ICICI login flow.")

    return captured_token[0]


def _accept_terms(page) -> None:
    """Check the T&C checkbox / click agree button if present on the ICICI login page."""
    selectors = [
        # Checkboxes
        'input[type="checkbox"]:visible',
        'input[name*="agree"]:visible',
        'input[name*="terms"]:visible',
        'input[id*="agree"]:visible',
        'input[id*="terms"]:visible',
        # Clickable labels / buttons
        'label:has-text("agree"):visible',
        'label:has-text("Terms"):visible',
        'label:has-text("Agree"):visible',
        'button:has-text("Agree"):visible',
        'button:has-text("I Agree"):visible',
        'a:has-text("Agree"):visible',
        'span:has-text("I agree"):visible',
    ]
    for selector in selectors:
        try:
            el = page.wait_for_selector(selector, timeout=2_000, state="visible")
            if el:
                # For checkboxes only click if not already checked
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                if tag == "input":
                    checked = el.is_checked()
                    if not checked:
                        el.click()
                        print("  [AUTO] Checked T&C checkbox")
                else:
                    el.click()
                    print("  [AUTO] Clicked T&C agree button")
                time.sleep(0.5)
                return
        except Exception:
            continue
    # T&C element not found — not all ICICI pages require it
    pass


def _fill_field(page, selectors: list[str], value: str, label: str) -> None:
    from playwright.sync_api import TimeoutError as PWTimeout
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=3_000, state="visible")
            page.fill(selector, value)
            print(f"  [AUTO] Filled {label}")
            return
        except Exception:
            continue
    print(f"  [SKIP] Could not auto-fill {label} — fill it manually in the browser.")


def _click_button(page, selectors: list[str]) -> None:
    # Extended selector list covering ICICI Direct's various page layouts
    extended = selectors + [
        "#btnSubmit",
        "#submit",
        "#loginBtn",
        "#login-btn",
        ".btn-primary",
        ".login-button",
        ".submit-btn",
        'button[class*="login"]',
        'button[class*="submit"]',
        'button[class*="btn"]',
        'input[class*="btn"]',
        'input[class*="login"]',
        # Last resort: any visible button on the page
        "button:visible",
    ]
    for selector in extended:
        try:
            el = page.wait_for_selector(selector, timeout=2_000, state="visible")
            if el:
                el.click()
                print(f"  [AUTO] Clicked login button ({selector})")
                return
        except Exception:
            continue

    # Final fallback: press Enter on the password field (submits most login forms)
    try:
        pw_field = page.query_selector('input[type="password"]:visible')
        if pw_field:
            pw_field.press("Enter")
            print("  [AUTO] Submitted login via Enter key")
            return
    except Exception:
        pass

    print("  [MANUAL] Could not auto-click login — please click the Login button in the browser.")


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_token(api_key: str, api_secret: str, session_token: str) -> bool:
    try:
        from breeze_connect import BreezeConnect  # type: ignore[import]
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret, session_token=session_token)
        details = breeze.get_customer_details(api_session=session_token)
        if details and details.get("Status") == 200:
            name = details.get("Success", {}).get("idirect_user_name", "unknown")
            print(f"  [OK] Session validated — logged in as: {name}")
            return True
        print(f"  [WARN] Validation response: {details}")
        return False
    except Exception as exc:
        print(f"  [WARN] Validation failed: {exc}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh ICICI Breeze session token")
    parser.add_argument("--force", action="store_true", help="Refresh even if already done today")
    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("  ICICI Breeze — Daily Session Token Refresh")
    print("=" * 60)

    # ── Already fresh? ─────────────────────────────────────────────────────────
    env = _read_env()
    if not args.force and _already_refreshed_today():
        existing = env.get("ICICI_SESSION_TOKEN", "")
        if existing:
            print(f"\n  [SKIP] Session token already refreshed today ({date.today()}).")
            print("  Run with --force to refresh again.\n")
            print("=" * 60 + "\n")
            sys.exit(0)

    # ── Validate existing token first (skip browser if still alive) ────────────
    existing_token = env.get("ICICI_SESSION_TOKEN", "")
    api_key_val = env.get("ICICI_API_KEY", "")
    api_secret_val = env.get("ICICI_API_SECRET", "")
    if not args.force and existing_token and api_key_val and api_secret_val:
        print("\n  Checking if existing session token is still valid...")
        if _validate_token(api_key_val, api_secret_val, existing_token):
            _stamp_today(existing_token)
            print(f"  [SKIP] Existing token is valid — no refresh needed today.")
            print("=" * 60 + "\n")
            sys.exit(0)
        print("  Existing token is expired — starting fresh login flow.")

    # ── Load credentials ───────────────────────────────────────────────────────
    api_key = env.get("ICICI_API_KEY", "")
    api_secret = env.get("ICICI_API_SECRET", "")
    client_id = env.get("ICICI_CLIENT_ID", "")
    password = env.get("ICICI_PASSWORD", "")

    if not api_key:
        print("[ERROR] ICICI_API_KEY not set in .env")
        sys.exit(1)
    if not api_secret:
        print("[ERROR] ICICI_API_SECRET not set in .env")
        sys.exit(1)
    if not client_id:
        print("[WARN] ICICI_CLIENT_ID not set — you'll need to fill it manually in the browser.")
    if not password:
        print("[WARN] ICICI_PASSWORD not set — you'll need to fill it manually in the browser.")

    print(f"\n  API Key  : {api_key[:6]}{'*' * max(0, len(api_key) - 6)}")
    print(f"  Client ID: {client_id or '(not set)'}")

    # ── Run browser flow ───────────────────────────────────────────────────────
    try:
        session_token = _run_browser_flow(api_key, client_id, password)
    except KeyboardInterrupt:
        print("\n[ABORTED] Refresh cancelled.")
        sys.exit(1)

    print(f"\n  Token captured: {session_token[:6]}{'*' * max(0, len(session_token) - 6)}")

    # ── Validate ───────────────────────────────────────────────────────────────
    _validate_token(api_key, api_secret, session_token)

    # ── Write to .env ──────────────────────────────────────────────────────────
    _write_env_value("ICICI_SESSION_TOKEN", session_token)
    _stamp_today(session_token)

    print(f"\n  [SAVED] ICICI_SESSION_TOKEN updated in {ENV_FILE.name}")
    print(f"  [CACHED] Stamped {date.today()} — won't re-run until tomorrow.")
    print("\n  Restart the data-service to pick up the new token:")
    print("    /Users/sudheer/Desktop/jupyter_env/bin/python -m uvicorn main:app --reload --port 8001")
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    main()
