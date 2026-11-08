#!/usr/bin/env python
"""Backfill and verify India's monthly gold imports from UN Comtrade — the one machine-readable official source.

Found 8 Nov 2026, after the trade portal (form only), RBI (captcha) and the Commerce Ministry's monthly release (carries
no standalone gold figure — see SOURCES.md F14) all proved closed. Comtrade's public preview endpoint answers without a
key and India reports HS 7108 (gold, unwrought/semi-manufactured) monthly, in US dollars and kilograms.

Its one limitation is the lag: India's data runs about 14 months behind (through 2025-08 as of 8 Nov 2026), so this
cannot give you the current month — that still comes from the press release. What it does give is:

  * **history** — the stored series had 4 points; this fills every month Comtrade has;
  * **verification** — a month already stored is never overwritten, only compared, so a hand-typed figure is checked
    against the official filing and a mismatch is printed.

    python scripts/gold_india_imports_comtrade.py --since 2023-01 --dry-run   # see what it would do
    python scripts/gold_india_imports_comtrade.py --since 2023-01            # fill the gaps, verify the rest

Exit codes: 0 done (nothing to do counts) · 1 a stored month disagrees with Comtrade · 4 the network refused us.
"""
from __future__ import annotations

import argparse
import calendar
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

IST = timezone(timedelta(hours=5, minutes=30))
API = "https://comtradeapi.un.org/public/v1/preview/C/M/HS"
REPORTER_INDIA = 699
HS_GOLD = "7108"                 # gold, unwrought or in semi-manufactured forms, or in powder form
UA = "SuryaDhana-research/1.0 (personal research)"
PACE_S = 6.0                     # one period per request, and the preview endpoint refuses a faster cadence:
                                 # 1.3 s drew an HTTP error on the second call, 6 s answers 200 every time (8 Nov 2026)
DATA_SVC = "http://127.0.0.1:8001"
SERIES = "INDIA_GOLD_IMPORTS_USD_BN"
# A hand-typed press figure and the final filing differ a little (revisions, valuation). Flag only a real divergence.
TOLERANCE_PCT = 10.0


def months(since: str, until: str) -> list[str]:
    """Inclusive YYYY-MM range as Comtrade periods (YYYYMM), oldest first."""
    y1, m1 = (int(x) for x in since.split("-"))
    y2, m2 = (int(x) for x in until.split("-"))
    out, y, m = [], y1, m1
    while (y, m) <= (y2, m2):
        out.append(f"{y}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def period_to_date(period: str) -> date:
    """'202508' → the last day of that month (the point-in-time date the store uses)."""
    y, m = int(period[:4]), int(period[4:])
    return date(y, m, calendar.monthrange(y, m)[1])


def fetch(client: httpx.Client, period: str) -> tuple[float, float] | None:
    """(US$ bn, tonnes) for one month, or None when Comtrade has no filing for it yet."""
    body = None
    for attempt in range(3):                      # a throttled call is the normal failure here, so back off and retry
        time.sleep(PACE_S * (1 + attempt * 2))
        r = client.get(API, params={"reporterCode": REPORTER_INDIA, "period": period, "partnerCode": 0,
                                    "cmdCode": HS_GOLD, "flowCode": "M"},
                       headers={"User-Agent": UA}, timeout=45)
        if r.status_code in (429, 500, 502, 503, 504):
            print(f"    {period}: HTTP {r.status_code}, backing off")
            continue
        r.raise_for_status()
        body = r.json()
        break
    if body is None:
        raise httpx.HTTPError(f"Comtrade kept refusing {period}")
    rows = body.get("data") or []
    if not rows:
        # A throttled preview call answers 200 with an EMPTY data list, not an error (observed 8 Nov 2026: 202509 came
        # back empty at a 1.2 s cadence, then returned its real 9.61 at 6 s). Treating that as "not filed" would leave
        # silent holes in the series, so an empty answer is always re-asked once, slowly, before it is believed.
        time.sleep(PACE_S * 3)
        r2 = client.get(API, params={"reporterCode": REPORTER_INDIA, "period": period, "partnerCode": 0,
                                     "cmdCode": HS_GOLD, "flowCode": "M"},
                        headers={"User-Agent": UA}, timeout=45)
        r2.raise_for_status()
        rows = (r2.json().get("data") or [])
        if not rows:
            return None
    row = rows[0]
    usd = float(row.get("primaryValue") or 0.0)
    kg = float(row.get("netWgt") or 0.0)
    return (usd / 1e9, kg / 1000.0) if usd > 0 else None


def stored(client: httpx.Client) -> dict[str, float]:
    """{'YYYY-MM': value} already in the store."""
    r = client.get(f"{DATA_SVC}/db/gold/series", params={"ids": SERIES, "freq": "M"}, timeout=30)
    r.raise_for_status()
    pts = ((r.json().get("series") or [{}])[0] or {}).get("points") or []
    return {str(p.get("report_date", ""))[:7]: float(p.get("value")) for p in pts if p.get("value") is not None}


def main(argv: list[str] | None = None) -> int:
    today = datetime.now(IST).date()
    ap = argparse.ArgumentParser(description="Backfill / verify India's monthly gold imports from UN Comtrade.")
    ap.add_argument("--since", default="2023-01", help="first month, YYYY-MM (default 2023-01)")
    ap.add_argument("--until", default=(today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"),
                    help="last month, YYYY-MM (default: last month)")
    ap.add_argument("--dry-run", action="store_true", help="report what would be stored, write nothing")
    ap.add_argument("--max-requests", type=int, default=60, help="hard cap on requests in one run (default 60)")
    a = ap.parse_args(argv)

    periods = months(a.since, a.until)[:a.max_requests]
    if not periods:
        print("nothing to do: empty month range")
        return 0
    filled, verified, missing, mismatched = [], [], [], []
    try:
        with httpx.Client() as client:
            have = stored(client)
            print(f"{SERIES}: {len(have)} months stored · checking {len(periods)} months "
                  f"({periods[0]} → {periods[-1]}) against Comtrade")
            for p in periods:
                got = fetch(client, p)
                key = f"{p[:4]}-{p[4:]}"
                if got is None:
                    missing.append(key)
                    continue
                usd_bn, tonnes = got
                if key in have:
                    delta = abs(have[key] - usd_bn) / max(usd_bn, 1e-9) * 100
                    (mismatched if delta > TOLERANCE_PCT else verified).append((key, have[key], usd_bn, delta))
                    continue
                print(f"  {key}  US${usd_bn:.3f} bn · {tonnes:,.1f} t  → store")
                if not a.dry_run:
                    cmd = [sys.executable, "scripts/gold_india_imports.py", "--month", key,
                           "--usd-bn", f"{usd_bn:.3f}",
                           "--source", f"UN Comtrade HS {HS_GOLD}, India monthly filing (period {p})"]
                    if subprocess.run(cmd, check=False, capture_output=True).returncode != 0:
                        print(f"    store refused {key} (see the plausibility guard)")
                        continue
                filled.append(key)
    except httpx.HTTPError as exc:
        print(f"Comtrade did not answer ({type(exc).__name__}) — try later")
        return 4

    print(f"\n{'would fill' if a.dry_run else 'filled'}: {len(filled)}"
          f" · verified against the filing: {len(verified)}"
          f" · not yet filed at Comtrade: {len(missing)}")
    if missing:
        print(f"  (Comtrade's India frontier: everything after {missing[0]} is still unfiled — the current month "
              f"always comes from the press release)")
    for key, was, now, delta in mismatched:
        print(f"  MISMATCH {key}: stored {was:g} vs Comtrade {now:.3f} ({delta:.0f}% apart) — nothing overwritten; "
              f"check which is right, then revise with scripts/gold_india_imports.py --month {key} --usd-bn <value>")
    return 1 if mismatched else 0


if __name__ == "__main__":
    sys.exit(main())
