#!/usr/bin/env python
"""Can ICICI Breeze serve MCX option quotes — and at what cost per snapshot? (FINAL ROUND, 14 Nov 2026)

WHY THIS EXISTS. The product rating's last open Commodities item is "MCX gold/silver/crude option chains with
IV (after the Breeze MCX probe / O-8)", and three reports in a row carried it as "pending a live session". The
SDK answers half of it offline, and this script answers the other half in ONE command on the next trading day.

What the installed SDK already settles (breeze_connect 1.0.x, read from its own source — no session needed):

  * ``get_option_chain_quotes`` refuses anything but NFO/BFO:
        if exchange_code.lower() not in ["nfo", "bfo"]: -> OPT_CHAIN_EXCH_CODE_ERROR
    so there is NO one-call MCX option chain. That is a vendor restriction, not a permission or session problem.
  * The per-contract paths DO list MCX with options:
        EXCHANGE_CODES_HIST_V2 = ['nse','bse','nfo','ndx','mcx','bfo']
        PRODUCT_TYPES_HIST_V2  = ['futures','options','cash']
        FNO_EXCHANGE_TYPES     = ['nfo','mcx','ndx','bfo']
    so a chain can only be assembled strike by strike: one call per (strike, right).

What this probe measures, and nothing more: whether those per-strike calls actually RETURN MCX option data on
this account, what the payload looks like (is there an LTP? an OI? enough to compute IV?), and the real cost —
because that cost decides whether the feature is worth building. A +/-N-strike window at 2 rights is 2N+2 calls
per contract per snapshot against a 4,000/day ledger cap shared with everything else.

    python scripts/probe_mcx_options.py                      # GOLD, 2 strikes either side (10 calls)
    python scripts/probe_mcx_options.py --family SILVER --strikes 1
    python scripts/probe_mcx_options.py --dry-run            # show the plan and the call cost, ask nothing

READ-ONLY and budgeted: every call goes through the shared Breeze ledger (`shared.breeze_budget`), so it can
never outrun the daily cap, and it refuses to run without a live session instead of forcing a login. It places
no order (no order method is imported), writes to no table, and prints a report to stdout + the scratch path.

Exit codes: 0 probe ran (see the verdict) | 2 no live session (run it on a trading day after the 08:00 login)
            3 the account refused MCX options (the verdict says so) | 4 the budget refused the calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "ui-api"))

IST = timezone(timedelta(hours=5, minutes=30))
#: strike steps per family. Only the CMDT desk's own families are probed, because the desk's deployed endpoint
#: resolves their front expiry and a reference price for us (GOLD options follow the identical per-strike call
#: once this answers; the gold desk resolves its contracts separately, so it is out of this probe's scope).
STEPS: dict[str, float] = {"SILVER": 500.0, "SILVERM": 500.0, "SILVERMIC": 500.0,
                           "CRUDEOIL": 50.0, "CRUDEOILM": 50.0}
UI_API = "http://127.0.0.1:8010"
CALLER = "probe.mcx_options"


def _round_to(x: float, step: float) -> float:
    return round(x / step) * step


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Probe whether Breeze serves MCX option quotes, and the cost.")
    ap.add_argument("--family", default="SILVER", choices=sorted(STEPS), help="MCX family (default SILVER)")
    ap.add_argument("--strikes", type=int, default=2, help="strikes either side of the money (default 2 → 10 calls)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and the cost, call nothing")
    a = ap.parse_args(argv)

    step = STEPS[a.family]
    planned = (2 * a.strikes + 1) * 2
    print(f"probe: {a.family} · ±{a.strikes} strikes of {step:g} · 2 rights → {planned} metered calls")
    out: dict[str, Any] = {"family": a.family, "strikes": a.strikes, "planned_calls": planned,
                           "sdk": {"chain_endpoint": "NFO/BFO only — no one-call MCX chain",
                                   "per_contract": "EXCHANGE_CODES_HIST_V2 + FNO_EXCHANGE_TYPES include mcx"},
                           "ran_at_ist": datetime.now(IST).isoformat(timespec="seconds")}
    if a.dry_run:
        print(json.dumps(out, indent=1))
        return 0

    # a bare script does not inherit the services' environment: load .env the way shared/config does, or the
    # client getter reports "credentials not configured" when they are merely unloaded (a misleading diagnostic)
    from shared.config import load_env_into_process
    load_env_into_process()

    from routers.positions import _get_breeze_client               # the cached, session-aware client
    from shared.breeze_budget import BudgetExceeded, ledger

    client, err = _get_breeze_client()
    if client is None:
        print(f"no live session: {err}\n→ run this on a trading day after the 08:00 login (exit 2)")
        return 2

    # The front expiry and a reference price come from the desk's OWN deployed endpoint — tested code that
    # already resolves the front contract by OI and falls back to the ICICI band midpoint. No private imports.
    expiry: str | None = None
    ref: float | None = None
    try:
        import httpx
        q = httpx.get(f"{UI_API}/api/commodity/desk/quote", params={"contract": a.family}, timeout=30).json()
        expiry = q.get("expiry")
        ref = ((q.get("quote") or {}).get("ltp")) or ((q.get("best") or {}).get("price"))
        print(f"desk says: expiry {expiry} · reference {ref} ({(q.get('best') or {}).get('source', 'live quote')})")
    except Exception as exc:                                        # noqa: BLE001 — the probe degrades, never crashes
        print(f"could not reach the desk endpoint ({type(exc).__name__}: {exc}) — is ui-api up?")
    if not expiry or not ref:
        print("no stored expiry/reference price for this family — probe needs one; exit 2")
        return 2
    atm = _round_to(float(ref), step)
    strikes = [atm + i * step for i in range(-a.strikes, a.strikes + 1)]
    print(f"front expiry {expiry} · reference {ref:,.0f} · ATM {atm:,.0f} · strikes {strikes[0]:,.0f}…{strikes[-1]:,.0f}")

    served, refused, shapes = 0, 0, []
    try:
        for strike in strikes:
            for right in ("call", "put"):
                with ledger().guard(CALLER, "get_quotes"):
                    r = client.get_quotes(stock_code=a.family, exchange_code="MCX", product_type="options",
                                          expiry_date=f"{expiry}T06:00:00.000Z", right=right,
                                          strike_price=str(int(strike)))
                ok = isinstance(r, dict) and str(r.get("Status")) == "200" and bool(r.get("Success"))
                if ok:
                    served += 1
                    row = (r.get("Success") or [{}])[0]
                    shapes.append({"strike": strike, "right": right,
                                   "fields": sorted(k for k, v in row.items() if v not in (None, "", 0))[:14]})
                else:
                    refused += 1
                    if refused == 1:
                        out["first_refusal"] = str(r.get("Error") or r)[:200]
    except BudgetExceeded as exc:
        print(f"the Breeze ledger refused the calls ({exc}) — try later; exit 4")
        return 4

    out.update({"served": served, "refused": refused, "sample_fields": shapes[:3]})
    has_price = any("ltp" in f.lower() or "last" in f.lower() for s in shapes for f in s["fields"])
    has_oi = any("open_interest" in f.lower() or f.lower() == "oi" for s in shapes for f in s["fields"])
    out["verdict"] = ("MCX options ARE served per strike: a chain is assemblable at "
                      f"{planned} calls per snapshot (price={has_price}, open_interest={has_oi}); "
                      "IV must be computed locally (Black-76 on the futures price, as the NSE path does)"
                      if served else "the account did NOT serve MCX option quotes — see first_refusal")
    print(json.dumps(out, indent=1))
    dest = Path.home() / ".suryadhana_pm_scratch" / "final_round_20261113" / "mcx_options_probe.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=1))
    print(f"\nwritten: {dest}")
    return 0 if served else 3


if __name__ == "__main__":
    sys.exit(main())
