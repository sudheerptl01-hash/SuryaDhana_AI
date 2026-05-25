#!/usr/bin/env python
"""
ICICI Breeze Session Token Helper
===================================
Breeze session tokens expire every 24 hours and must be refreshed manually
before each trading day. Run this script each morning to get a fresh token.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/icici_session_helper.py

Steps:
    1. Script prints the ICICI login URL
    2. Open it in a browser and log in with your ICICI Direct credentials
    3. After login you are redirected to a URL containing: ?session_token=XXXXXX
    4. Copy that token and paste it when prompted (or update .env directly)
    5. The script rewrites ICICI_SESSION_TOKEN in your .env file
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

# Ensure project root is on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_api_key_from_env(env_path: Path) -> str:
    for line in env_path.read_text().splitlines():
        if line.startswith("ICICI_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def _update_env(env_path: Path, session_token: str) -> None:
    content = env_path.read_text()
    new_content = re.sub(
        r"^ICICI_SESSION_TOKEN=.*$",
        f"ICICI_SESSION_TOKEN={session_token}",
        content,
        flags=re.MULTILINE,
    )
    env_path.write_text(new_content)


def main() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        print(f"[ERROR] .env not found at {env_path}")
        sys.exit(1)

    api_key = _load_api_key_from_env(env_path)
    if not api_key:
        print("[ERROR] ICICI_API_KEY is not set in .env. Add it first.")
        sys.exit(1)

    try:
        from breeze_connect import BreezeConnect  # type: ignore[import]
    except ImportError:
        print("[ERROR] breeze-connect not installed. Run:")
        print("  /Users/sudheer/Desktop/jupyter_env/bin/pip install breeze-connect==1.0.69")
        sys.exit(1)

    breeze = BreezeConnect(api_key=api_key)

    print("\n" + "=" * 60)
    print("  ICICI Breeze — Daily Session Token Refresh")
    print("=" * 60)
    print(f"\n  API Key  : {api_key[:6]}{'*' * (len(api_key) - 6)}")
    print("\n  Step 1: Open this URL in your browser and log in:")
    print(f"\n    {breeze.get_customer_details.__doc__ or ''}")

    # Generate the login URL
    login_url = f"https://api.icicidirect.com/apiuser/login?api_key={api_key}"
    print(f"\n    {login_url}\n")

    print("  Step 2: After login you will be redirected to a URL like:")
    print("    https://your-redirect/?session_token=ABCDEF123456\n")

    session_token = input("  Paste the session_token value here: ").strip()
    if not session_token:
        print("[ABORTED] No token entered.")
        sys.exit(1)

    # Validate by attempting a connection
    print("\n  Validating token...")
    try:
        api_secret = ""
        for line in env_path.read_text().splitlines():
            if line.startswith("ICICI_API_SECRET="):
                api_secret = line.split("=", 1)[1].strip()
                break
        if not api_secret:
            print("[WARNING] ICICI_API_SECRET not found in .env — skipping validation")
        else:
            breeze.generate_session(api_secret=api_secret, session_token=session_token)
            details = breeze.get_customer_details(api_session=session_token)
            if details and details.get("Status") == 200:
                name = details.get("Success", {}).get("idirect_user_name", "unknown")
                print(f"  [OK] Connected as: {name}")
            else:
                print(f"  [WARNING] Validation response: {details}")
    except Exception as exc:
        print(f"  [WARNING] Validation failed: {exc} — token may still be valid")

    # Write to .env
    _update_env(env_path, session_token)
    print(f"\n  [SAVED] ICICI_SESSION_TOKEN updated in {env_path}")
    print("\n  Restart the data-service to pick up the new token.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
