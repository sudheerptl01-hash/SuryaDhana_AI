#!/usr/bin/env python
"""Enter India's monthly gold-import figure — the one number in the gold program that has no feed.

Why by hand (SOURCES.md F14, re-checked 8 Nov 2026): the Ministry of Commerce publishes it around the 15th for the
previous month, but there is no free machine-readable release. `tradestat.commerce.gov.in` offers only a web form with
no CSV / JSON download and no documented terms for automated use, so the program does not scrape it: the figure is
typed from the release and the source string records where it came from.

You are told when: the data-health row `gold_india_imports` ages the stored figure from the month it covers (budget 46
days), so it turns amber on the 16th if the new month is missing, and the hourly check sends one Telegram line.

    python scripts/gold_india_imports.py --month 2026-10 --usd-bn 1.80
    python scripts/gold_india_imports.py --month 2026-10 --usd-bn 1.80 --source "PTI, 15 Oct 2026" --dry-run

The value is US$ BILLIONS, as the release prints it ("gold imports fell to USD 1.8 billion in September"). The month is
the month the figure COVERS, not the release month; the row is dated that month's last day (point-in-time).
"""
from __future__ import annotations

import argparse
import calendar
import json
import sys
import time
from datetime import date, datetime, timedelta, timezone

import httpx

IST = timezone(timedelta(hours=5, minutes=30))
DATA_SERVICE = "http://127.0.0.1:8001"
SERIES = "INDIA_GOLD_IMPORTS_USD_BN"
JOB = "gold_india_imports_manual"
DEFAULT_SOURCE = "Ministry of Commerce monthly release (typed by hand: no machine-readable feed, SOURCES.md F14)"


def month_end(month: str) -> date:
    """'2026-10' → date(2026, 10, 31). The row is dated the month it covers, never the release day."""
    try:
        y, m = (int(x) for x in month.split("-"))
        return date(y, m, calendar.monthrange(y, m)[1])
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"--month must be YYYY-MM (got {month!r})") from exc


def plausible(usd_bn: float) -> str | None:
    """A typo guard, not a judgement: India's monthly gold imports have run ≈ US$1–10 bn. Returns a warning or None."""
    if usd_bn <= 0:
        return "the value must be positive"
    if usd_bn > 25:
        return f"US${usd_bn} bn is far above any month on record — did you type ₹ crore or US$ million by mistake?"
    if usd_bn < 0.2:
        return f"US${usd_bn} bn is far below any month on record — did you mean US$ billions?"
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Store India's monthly gold-import figure (US$ bn).")
    ap.add_argument("--month", required=True, help="the month the figure COVERS, YYYY-MM (e.g. 2026-10)")
    ap.add_argument("--usd-bn", required=True, type=float, help="the figure in US$ BILLIONS (e.g. 1.80)")
    ap.add_argument("--source", default=None, help="where you read it (appended to the stored source string)")
    ap.add_argument("--dry-run", action="store_true", help="print what would be sent and stop")
    ap.add_argument("--base", default=DATA_SERVICE, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)

    day = month_end(a.month)
    today = datetime.now(IST).date()            # IST, like every other date rule in the program
    if day >= today:
        raise SystemExit(f"{a.month} has not ended yet ({day} is not in the past): the figure covers a finished month")
    warn = plausible(a.usd_bn)
    if warn:
        raise SystemExit(f"refusing: {warn}")

    source = DEFAULT_SOURCE + (f" · {a.source}" if a.source else "")
    body = {"job": JOB, "groups": ["india_imports"],
            "params": {"values": [{"series_id": SERIES, "report_date": day.isoformat(), "value": a.usd_bn}],
                       "source": source}}
    print(f"{SERIES}  {day}  US${a.usd_bn} bn")
    if a.dry_run:
        print(json.dumps(body, indent=1))
        return 0

    try:
        r = httpx.post(f"{a.base}/jobs/ingest-gold", params={"job": JOB}, json=body, timeout=60)
        r.raise_for_status()
        jid = r.json().get("job_id")
        for _ in range(40):
            x = httpx.get(f"{a.base}/jobs/{jid}", timeout=30).json()
            if x.get("status") not in ("running", "queued", "pending"):
                break
            time.sleep(2)
    except httpx.HTTPError as exc:
        raise SystemExit(f"data-service did not answer ({type(exc).__name__}): is it running on {a.base}?") from exc

    g = ((x.get("result") or {}).get("groups") or {}).get("india_imports") or {}
    if x.get("status") != "done" or g.get("status") != "ok" or g.get("rejected"):
        print(f"FAILED: {json.dumps({'status': x.get('status'), **g, 'error': x.get('error')}, default=str)[:400]}")
        return 1
    print(f"stored: inserted {g.get('inserted')} · revised {g.get('revised')} · series now through {g.get('last')}")
    print("MONTHLY and the gold flows panel pick it up on their next read; the data-health row returns to fresh.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
