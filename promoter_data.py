#!/usr/bin/env python3
"""Fetch promoter (and broad shareholding) data for Indian stocks from NSE.

NSE (National Stock Exchange of India) publishes the quarterly Shareholding
Pattern (SHP) for every listed company. This script pulls the promoter &
promoter-group holding, public holding and pledged/encumbered figures for a
list of symbols -- by default the Nifty 50 -- and writes the result to CSV
or JSON.

Examples
--------
    # Whole Nifty 50 -> CSV (default)
    python3 promoter_data.py

    # A few specific symbols
    python3 promoter_data.py --symbols RELIANCE TCS INFY

    # Read symbols from a file (one per line)
    python3 promoter_data.py --symbols-file my_symbols.txt

    # JSON output to a custom path, keep the raw NSE payloads too
    python3 promoter_data.py --format json --out promoters.json --raw

    # Offline demo (no network) using bundled illustrative figures
    python3 promoter_data.py --demo

Network note
------------
NSE actively blocks non-browser clients, so the script first "warms up" a
requests.Session against the NSE home page to obtain the cookies the API
expects, sends browser-like headers, and rate-limits itself politely. If you
run this inside a sandbox with an egress allowlist, add ``nseindia.com`` to
the allowlist (or run the script locally / use ``--demo``).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

try:
    import requests
except ImportError:  # pragma: no cover - dependency hint
    sys.exit("The 'requests' package is required. Install it with: pip install requests")


# --------------------------------------------------------------------------- #
# Nifty 50 constituents (as of 2025; the index is rebalanced periodically).
# Override anytime with --symbols or --symbols-file.
# --------------------------------------------------------------------------- #
NIFTY_50: list[str] = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "BRITANNIA", "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO",
    "HINDALCO", "HINDUNILVR", "ICICIBANK", "INDUSINDBK", "INFY",
    "ITC", "JSWSTEEL", "KOTAKBANK", "LT", "LTIM",
    "M&M", "MARUTI", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATAMOTORS", "TATASTEEL", "TCS",
    "TECHM", "TITAN", "TRENT", "ULTRACEMCO", "WIPRO",
]

NSE_HOME = "https://www.nseindia.com"
# Quarterly shareholding-pattern records for an equity symbol.
NSE_SHP_API = NSE_HOME + "/api/corporate-share-holdings-master"
# Quote endpoint -- carries pledge / encumbered info under security/promoter info.
NSE_QUOTE_API = NSE_HOME + "/api/quote-equity"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


@dataclass
class PromoterRecord:
    """A single stock's promoter / shareholding snapshot."""

    symbol: str
    company: str = ""
    period: str = ""               # e.g. "31-Mar-2025"
    promoter_pct: float | None = None
    public_pct: float | None = None
    pledged_pct: float | None = None
    source: str = "NSE"
    error: str = ""

    def as_row(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------- #
# NSE client
# --------------------------------------------------------------------------- #
class NSEClient:
    """Thin, polite NSE API client with cookie warm-up and retries."""

    def __init__(self, delay: float = 1.0, timeout: int = 20, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update(BROWSER_HEADERS)
        self._warm = False

    def _warm_up(self) -> None:
        """Hit the home page so NSE hands us the cookies its API requires."""
        if self._warm:
            return
        self.session.get(NSE_HOME, timeout=self.timeout)
        self._warm = True

    def _get_json(self, url: str, params: dict[str, str], referer: str) -> Any:
        self._warm_up()
        headers = {"Referer": referer}
        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                resp = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout
                )
                if resp.status_code == 200:
                    return resp.json()
                # 401/403 usually means the cookie went stale -> re-warm.
                if resp.status_code in (401, 403):
                    self._warm = False
                    self._warm_up()
                last_err = RuntimeError(f"HTTP {resp.status_code}")
            except Exception as exc:  # noqa: BLE001 - surfaced to caller
                last_err = exc
            time.sleep(self.delay * attempt)  # linear backoff
        raise RuntimeError(f"GET {url} failed after {self.retries} tries: {last_err}")

    def fetch(self, symbol: str) -> PromoterRecord:
        rec = PromoterRecord(symbol=symbol)
        quotes_ref = f"{NSE_HOME}/get-quotes/equity?symbol={symbol}"
        try:
            shp = self._get_json(
                NSE_SHP_API,
                {"index": "equities", "symbol": symbol},
                referer=quotes_ref,
            )
            _parse_shareholding(shp, rec)
        except Exception as exc:  # noqa: BLE001
            rec.error = str(exc)

        # Best-effort pledge enrichment from the quote endpoint.
        try:
            quote = self._get_json(
                NSE_QUOTE_API,
                {"symbol": symbol},
                referer=quotes_ref,
            )
            if not rec.company:
                rec.company = _first_str(quote, ["companyName", "name"])
            if rec.pledged_pct is None:
                rec.pledged_pct = _find_pct(quote, ("pledge", "encumber"))
        except Exception:  # noqa: BLE001 - pledge is optional
            pass

        time.sleep(self.delay)
        return rec


# --------------------------------------------------------------------------- #
# Defensive parsing helpers.
# NSE's JSON shapes change over time, so we search rather than hard-index.
# --------------------------------------------------------------------------- #
def _iter_dicts(obj: Any) -> Iterable[dict]:
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dicts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_dicts(v)


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    # Strip thousands separators so "1,234.5%" parses as 1234.5, not 1.
    text = str(value).replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def _first_str(obj: Any, keys: list[str]) -> str:
    for d in _iter_dicts(obj):
        for k in keys:
            if k in d and isinstance(d[k], str) and d[k].strip():
                return d[k].strip()
    return ""


def _find_pct(obj: Any, name_hints: tuple[str, ...]) -> float | None:
    """Find a percentage whose sibling key/name mentions one of name_hints."""
    for d in _iter_dicts(obj):
        joined = " ".join(str(k).lower() for k in d.keys())
        name_val = " ".join(
            str(v).lower() for v in d.values() if isinstance(v, str)
        )
        haystack = f"{joined} {name_val}"
        if any(h in haystack for h in name_hints):
            for k, v in d.items():
                kl = str(k).lower()
                if "pct" in kl or "percent" in kl or "%" in kl:
                    f = _to_float(v)
                    if f is not None:
                        return f
    return None


def _parse_shareholding(payload: Any, rec: PromoterRecord) -> None:
    """Pull promoter %, public % and period out of the SHP payload."""
    if not rec.company:
        rec.company = _first_str(payload, ["companyName", "company", "name"])
    rec.period = rec.period or _first_str(
        payload, ["date", "submissionDate", "asOnDate", "period", "quarter"]
    )

    # Look for category rows mentioning "promoter" / "public".
    for d in _iter_dicts(payload):
        text = " ".join(str(v).lower() for v in d.values() if isinstance(v, str))
        if "promoter" in text and rec.promoter_pct is None:
            for k, v in d.items():
                if "pct" in str(k).lower() or "percent" in str(k).lower():
                    rec.promoter_pct = _to_float(v)
                    break
        if "public" in text and rec.public_pct is None:
            for k, v in d.items():
                if "pct" in str(k).lower() or "percent" in str(k).lower():
                    rec.public_pct = _to_float(v)
                    break

    if rec.promoter_pct is None:
        rec.promoter_pct = _find_pct(payload, ("promoter",))
    if rec.public_pct is None:
        rec.public_pct = _find_pct(payload, ("public",))


# --------------------------------------------------------------------------- #
# Demo / offline mode
# --------------------------------------------------------------------------- #
def load_demo_records(symbols: list[str]) -> list[PromoterRecord]:
    sample_path = Path(__file__).with_name("sample_data.json")
    data = json.loads(sample_path.read_text())
    out: list[PromoterRecord] = []
    for sym in symbols:
        d = data.get(sym)
        if d:
            out.append(PromoterRecord(symbol=sym, source="DEMO (illustrative)", **d))
        else:
            out.append(
                PromoterRecord(symbol=sym, source="DEMO", error="not in sample set")
            )
    return out


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
FIELDS = [
    "symbol", "company", "period",
    "promoter_pct", "public_pct", "pledged_pct",
    "source", "error",
]


def write_csv(records: list[PromoterRecord], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        for r in records:
            writer.writerow(r.as_row())


def write_json(records: list[PromoterRecord], path: Path) -> None:
    path.write_text(
        json.dumps([r.as_row() for r in records], indent=2), encoding="utf-8"
    )


def print_table(records: list[PromoterRecord]) -> None:
    def fmt(v: float | None) -> str:
        return f"{v:6.2f}" if isinstance(v, (int, float)) else "   -- "

    print(f"\n{'SYMBOL':<12}{'PROMOTER%':>11}{'PUBLIC%':>10}{'PLEDGED%':>10}  PERIOD")
    print("-" * 64)
    for r in records:
        note = f"  !{r.error}" if r.error else ""
        print(
            f"{r.symbol:<12}{fmt(r.promoter_pct):>11}{fmt(r.public_pct):>10}"
            f"{fmt(r.pledged_pct):>10}  {r.period or '':<12}{note}"
        )
    print()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def resolve_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [s.upper() for s in args.symbols]
    if args.symbols_file:
        lines = Path(args.symbols_file).read_text().splitlines()
        return [ln.strip().upper() for ln in lines if ln.strip() and not ln.startswith("#")]
    return list(NIFTY_50)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = p.add_mutually_exclusive_group()
    src.add_argument("--symbols", nargs="+", help="Explicit NSE symbols, e.g. RELIANCE TCS")
    src.add_argument("--symbols-file", help="Path to a file with one symbol per line")
    p.add_argument("--format", choices=["csv", "json"], default="csv", help="Output format")
    p.add_argument("--out", help="Output file path (default: promoter_data.<ext>)")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds between NSE calls")
    p.add_argument("--demo", action="store_true", help="Offline demo using bundled sample data")
    p.add_argument("--raw", action="store_true", help="Also dump raw NSE payloads to ./raw/")
    args = p.parse_args(argv)

    symbols = resolve_symbols(args)
    print(f"Fetching promoter data for {len(symbols)} symbol(s)...", file=sys.stderr)

    if args.demo:
        records = load_demo_records(symbols)
    else:
        client = NSEClient(delay=args.delay)
        raw_dir = Path("raw")
        if args.raw:
            raw_dir.mkdir(exist_ok=True)
        records = []
        for i, sym in enumerate(symbols, 1):
            print(f"  [{i}/{len(symbols)}] {sym}", file=sys.stderr)
            rec = client.fetch(sym)
            records.append(rec)

    print_table(records)

    out_path = Path(args.out) if args.out else Path(f"promoter_data.{args.format}")
    if args.format == "csv":
        write_csv(records, out_path)
    else:
        write_json(records, out_path)
    print(f"Wrote {len(records)} records to {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
