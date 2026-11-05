"""
Per-company NSE filings for the "who is holding" research (docs/NSE_DATA_DICTIONARY.md):

  insider       SEBI PIT disclosures: who (promoter, director, employee trust…), how
                (market purchase, ESOP, pledge…), how much, holding before/after, and the
                intimation date — the day the market learned of it (nse_insider_trades).
  shareholding  Quarterly shareholding pattern; the XBRL filing is parsed for the number
                of shareholders and % held by retail (≤ ₹2 lakh), HNIs, FPIs and mutual
                funds (nse_shareholding).

These are one request per company, so they run weekly over the liquid universe rather
than in the evening pipeline. The market-wide insider query returns nothing; per-company
queries work. Newer XBRL files store percentages as fractions (0.27 = 27%).
"""
from __future__ import annotations

import gzip
import html
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import pandas as pd

from bhavcopy import HEADERS
from shared.logging import get_logger

logger = get_logger(__name__)

API = "https://www.nseindia.com/api"
API_HEADERS = {**HEADERS, "Accept": "application/json, text/plain, */*", "Referer": "https://www.nseindia.com/"}


def _date(v) -> Optional[str]:
    if not v or str(v).strip() in ("-", ""):
        return None
    for fmt in ("%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _f(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ── insider trades ──────────────────────────────────────────────────────────────

def _sane_intimation(intim: Optional[str], broadcast: Optional[str]) -> Optional[str]:
    """Intimation date, unless it is after the broadcast or before 2000 (typos): then the broadcast date."""
    if intim and (intim < "2000-01-01" or (broadcast and intim > broadcast)):
        return broadcast or None
    return intim or broadcast


def parse_insider(records: list[dict], symbol: str) -> pd.DataFrame:
    rows = []
    for r in records or []:
        qty = _f(r.get("secAcq"))
        rows.append({
            "record_id": "|".join(str(r.get(k) or "") for k in ("did", "pid", "acqName", "acqfromDt", "secAcq", "intimDt")),
            "symbol": symbol,
            "person": (r.get("acqName") or "").strip() or None,
            "category": (r.get("personCategory") or "").strip() or None,
            "mode": (r.get("acqMode") or "").strip() or None,
            "txn_type": (r.get("tdpTransactionType") or "").strip() or None,
            "qty": qty,
            "value": _f(r.get("secVal")),
            "before_pct": _f(r.get("befAcqSharesPer")),
            "after_pct": _f(r.get("afterAcqSharesPer")),
            "from_date": _date(r.get("acqfromDt")),
            "to_date": _date(r.get("acqtoDt")),
            # NSE typos put some intimation dates years off (2028, 1925): never after the broadcast, never pre-2000
            "intimation_date": _sane_intimation(_date(r.get("intimDt")), _date(r.get("date"))),
            "broadcast_ts": str(r.get("date") or "") or None,
        })
    # Some companies' feeds list the same disclosure twice; one insert batch must not repeat a key.
    return pd.DataFrame(rows).drop_duplicates(subset=["record_id"], keep="last") if rows else pd.DataFrame(rows)


def insider_windows(since: Optional[date], today: Optional[date] = None) -> list[tuple[date, date]]:
    """Query window for the PIT API. Without dates it returns only the newest 20 records per
    company, so every call carries a range: one long range for a backfill (the API accepts
    years at once), else the last 45 days."""
    today = today or date.today()
    return [(since if since is not None else today - timedelta(days=45), today)]


def yearly_windows(since: date, until: date) -> list[tuple[date, date]]:
    """Calendar-year split, used only if a long range comes back suspiciously full."""
    out, start = [], since
    while start <= until:
        end = min(date(start.year, 12, 31), until)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


INSIDER_SPLIT_AT = 1000        # a response this large may be capped: re-query year by year


# ── shareholding ────────────────────────────────────────────────────────────────

_COUNT_RE = re.compile(r"NumberOfShareholders\s+contextRef=\"([^\"]+)\"[^>]*>([^<]+)<")
_PCT_RE = re.compile(r"ShareholdingAsAPercentageOfTotalNumberOfShares\s+contextRef=\"([^\"]+)\"[^>]*>([^<]+)<")
# FPIs split into Category I/II from late 2022; earlier filings carry a single FPI line.
_FPI = ("institutionsforeignportfolioinvestorcategoryone", "institutionsforeignportfolioinvestorcategorytwo")
_FPI_SINGLE = "institutionsforeignportfolioinvestor"
_COUNT_FIELDS = ("total_holders", "retail_holders", "retail_pct", "hni_holders", "fpi_holders", "fpi_pct",
                 "mf_holders", "mf_pct")


def _norm_ctx(ctx: str) -> Optional[str]:
    """One key per shareholder category across XBRL generations. New filings: `X_ContextI`;
    older ones: `XI`, `MutualFundsOrUti`, and NSE's own typo `…Catergory…`. Per-holder detail
    rows (`DetailsOf…001I`, `…_Context15`) are not categories and return None."""
    if ctx.startswith("DetailsOf"):
        return None
    base = re.sub(r"(_Context)?I$", "", ctx)
    if re.search(r"\d{3}$|_Context\d+$", base):
        return None
    return base.lower().replace("catergory", "category")


def parse_shareholding_xbrl(xml: str) -> dict:
    counts: dict[str, float] = {}
    pcts: dict[str, float] = {}
    for regex, into in ((_COUNT_RE, counts), (_PCT_RE, pcts)):
        for m in regex.finditer(xml):
            key, val = _norm_ctx(m.group(1)), _f(m.group(2))
            if key is not None and val is not None:
                into.setdefault(key, val)
    # Fractions (0.1382) in newer filings, percent (13.82) in older ones.
    scale = 100.0 if pcts and max(pcts.values()) <= 1.0000001 else 1.0

    def pick(d: dict, fragment: str) -> Optional[float]:
        return next((v for k, v in d.items() if fragment in k), None)

    def pct(v: Optional[float]) -> Optional[float]:
        return round(v * scale, 4) if v is not None else None

    def fpi(d: dict) -> Optional[float]:
        parts = [d[k] for k in _FPI if k in d]
        return sum(parts) if parts else d.get(_FPI_SINGLE)

    return {
        "total_holders": max(counts.values()) if counts else None,
        "retail_holders": pick(counts, "nominalsharecapitalupto"),
        "retail_pct": pct(pick(pcts, "nominalsharecapitalupto")),
        "hni_holders": pick(counts, "nominalsharecapitalinexcess"),
        "fpi_holders": fpi(counts),
        "fpi_pct": pct(fpi(pcts)),
        "mf_holders": counts.get("mutualfundsoruti"),
        "mf_pct": pct(pcts.get("mutualfundsoruti")),
    }


def fetch_xbrl(client: httpx.Client, url: str, cache_root: Optional[Path], sleep_s: float = 0.3) -> Optional[str]:
    """XBRL text from the local cache, else from the archive host (then cached, gzipped: the XML
    shrinks ~15x). None on a non-200."""
    cache = cache_root / f"{url.rsplit('/', 1)[-1]}.gz" if cache_root else None
    if cache and cache.exists():
        return gzip.decompress(cache.read_bytes()).decode("utf-8")
    time.sleep(sleep_s)                    # static archive host: lighter pacing than the API
    resp = client.get(url)
    if resp.status_code != 200:
        return None
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(gzip.compress(resp.content))
    return resp.text


def reparse_shareholding(store, client: httpx.Client, cache_root: Optional[Path],
                         progress: Optional[Callable] = None, workers: int = 4) -> dict:
    """Re-read stored filings that have an XBRL link but no FPI/MF split (parsed before the
    older layouts were understood) and update them in place. A few fetchers run in parallel
    (each still paced); writes stay on this thread."""
    rows = store.shareholding_missing_categories()
    out: dict[str, Any] = {"reparse_candidates": len(rows), "reparsed": 0, "failures": []}

    def load(r: dict) -> dict:
        xml = fetch_xbrl(client, r["xbrl_url"], cache_root)
        if xml is None:
            raise ValueError("XBRL not available")
        return {**r, **parse_shareholding_xbrl(xml)}

    fixed: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, (r, fut) in enumerate(zip(rows, [pool.submit(load, r) for r in rows]), 1):
            try:
                fixed.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                out["failures"].append({"symbol": r["symbol"], "period_end": r["period_end"], "error": str(exc)[:120]})
            if len(fixed) >= 200 or (fixed and i == len(rows)):
                out["reparsed"] += store.upsert_shareholding(pd.DataFrame(fixed))
                fixed = []
            if progress:
                progress(i, len(rows))
    out["failure_count"] = len(out["failures"])
    out["failures"] = out["failures"][:30]
    logger.info("NSE shareholding reparse", **{k: v for k, v in out.items() if k != "failures"})
    return out


def _period_end(v) -> Optional[str]:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(str(v).strip().title(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ── orchestration ────────────────────────────────────────────────────────────────

def ingest_filings(store, symbols: list[str], progress: Optional[Callable] = None,
                   xbrl_per_symbol: int = 1, sleep_s: float = 0.9,
                   client: Optional[httpx.Client] = None,
                   datasets: tuple[str, ...] = ("insider", "shareholding"),
                   insider_since: Optional[date] = None, xbrl_sleep_s: float = 0.3,
                   xbrl_cache: Optional[Path] = None) -> dict:
    """Insider trades + new shareholding filings for each symbol. `xbrl_per_symbol` caps how
    many not-yet-stored quarterly filings are parsed per symbol per run (newest first);
    `insider_since` backfills insider trades from that date; XBRL files are kept in
    `xbrl_cache` so a parser change can be replayed without downloading them again."""
    own = client is None
    client = client or httpx.Client(headers=API_HEADERS, timeout=60, follow_redirects=True)
    known = store.known_shareholding_filings()
    out: dict[str, Any] = {"symbols": len(symbols), "insider_rows": 0, "shareholding_rows": 0, "failures": []}
    try:
        windows = insider_windows(insider_since)
        for i, sym in enumerate(symbols, 1):
            queue = list(windows) if "insider" in datasets else []
            while queue:
                a, b = queue.pop(0)
                try:
                    r = client.get(f"{API}/corporates-pit", params={"index": "equities", "symbol": sym,
                                                                    "from_date": f"{a:%d-%m-%Y}", "to_date": f"{b:%d-%m-%Y}"})
                    data = r.json().get("data", []) if r.status_code == 200 else []
                    if len(data) >= INSIDER_SPLIT_AT and (b - a).days > 366:
                        queue.extend(yearly_windows(a, b))
                    else:
                        out["insider_rows"] += store.upsert_insider_trades(parse_insider(data, sym))
                except Exception as exc:  # noqa: BLE001
                    out["failures"].append({"symbol": sym, "dataset": "insider", "window": str(a), "error": str(exc)[:120]})
                time.sleep(sleep_s)
            if "shareholding" not in datasets:
                if progress:
                    progress(i, len(symbols))
                continue
            try:
                r = client.get(f"{API}/corporate-share-holdings-master", params={"index": "equities", "symbol": sym})
                filings = r.json() if r.status_code == 200 else []
                new_rows, parsed = [], 0
                for f in filings or []:
                    period = _period_end(f.get("date"))
                    stamp = str(f.get("broadcastDate") or "")
                    if not period or (sym, period, stamp) in known or parsed >= xbrl_per_symbol:
                        continue
                    known.add((sym, period, stamp))       # some feeds list the same filing twice
                    url = f.get("xbrl") if f.get("xbrl") and not str(f["xbrl"]).endswith("/-") else None
                    row = {"symbol": sym, "period_end": period, "broadcast_ts": stamp,
                           "promoter_pct": _f(f.get("pr_and_prgrp")), "public_pct": _f(f.get("public_val")),
                           "xbrl_url": url, **dict.fromkeys(_COUNT_FIELDS)}
                    xml = fetch_xbrl(client, url, xbrl_cache, xbrl_sleep_s) if url else None
                    if xml:
                        row.update(parse_shareholding_xbrl(xml))
                    new_rows.append(row)
                    parsed += 1
                if new_rows:
                    out["shareholding_rows"] += store.upsert_shareholding(pd.DataFrame(new_rows))
            except Exception as exc:  # noqa: BLE001
                out["failures"].append({"symbol": sym, "dataset": "shareholding", "error": str(exc)[:120]})
            time.sleep(sleep_s)
            if progress:
                progress(i, len(symbols))
    finally:
        if own:
            client.close()
    out["failure_count"] = len(out["failures"])
    out["failures"] = out["failures"][:30]
    logger.info("NSE filings ingest", **{k: v for k, v in out.items() if k != "failures"})
    return out


# ── insider trades after 5 May 2026: single-filing XBRL (NSE circular NSE/CML/2026/11) ─────────────────────────
# The old corporates-pit feed stops in early May 2026. NSE now lists PIT filings at corporates-pit-gg (one row per
# filing, market-wide, date-windowed) and the trade details are in each filing's XBRL file (one context per
# disclosure). Rows go into the same nse_insider_trades table; intimation_date = the public broadcast date.

PIT_GG = "corporates-pit-gg"
_PIT_FACT = re.compile(r"<in-bse-co:([A-Za-z0-9]+)[^>]*contextRef=\"([^\"]+)\"[^>]*>([^<]*)<")


def parse_pit_xbrl(xml: str, symbol: str, app_id: str, broadcast: str) -> list[dict]:
    """One row per disclosure context (Disclosure1, Disclosure2 …) of a PIT XBRL filing."""
    ctx: dict[str, dict[str, str]] = {}
    for tag, c, val in _PIT_FACT.findall(xml):
        ctx.setdefault(c, {})[tag] = html.unescape(val.strip())          # "Odd &amp; Even" → "Odd & Even"
    bdate = _date(broadcast)
    rows = []
    for c, f in ctx.items():
        if "NameOfThePerson" not in f:
            continue                                              # the filing's header context (MainI)
        rows.append({
            "record_id": f"gg|{app_id}|{c}",
            "symbol": symbol,
            "person": f.get("NameOfThePerson") or None,
            "category": f.get("CategoryOfPerson") or None,
            "mode": f.get("ModeOfAcquisitionOrDisposal") or None,
            "txn_type": f.get("SecuritiesAcquiredOrDisposedTransactionType") or None,
            "qty": _f(f.get("SecuritiesAcquiredOrDisposedNumberOfSecurity")),
            "value": _f(f.get("SecuritiesAcquiredOrDisposedValueOfSecurity")),
            "before_pct": _f(f.get("SecuritiesHeldPriorToAcquisitionOrDisposalPercentageOfShareholding")),
            "after_pct": _f(f.get("SecuritiesHeldPostAcquistionOrDisposalPercentageOfShareholding")),
            "from_date": f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyFromDate") or None,
            "to_date": f.get("DateOfAllotmentAdviceOrAcquisitionOfSharesOrSaleOfSharesSpecifyToDate") or None,
            "intimation_date": bdate,                             # point-in-time: when the market could see it
            "broadcast_ts": broadcast or None,
        })
    return rows


def ingest_pit_gg(store, start: date, end: date, progress: Optional[Callable] = None,
                  client: Optional[httpx.Client] = None, xbrl_cache: Optional[Path] = None,
                  window_days: int = 31, sleep_s: float = 0.8, workers: int = 4) -> dict:
    """Insider trades from the single-filing feed for [start, end]: list filings per ~month window, then parse each
    filing's XBRL (cached gzipped under xbrl_cache). Filings already stored (by appId) are skipped."""
    own = client is None
    client = client or httpx.Client(headers=API_HEADERS, timeout=60, follow_redirects=True)
    known = store.known_pit_gg_apps()
    out: dict[str, Any] = {"filings": 0, "parsed": 0, "rows": 0, "skipped_known": 0, "failures": []}
    filings: list[dict] = []
    try:
        a = start
        while a <= end:
            b = min(end, a + timedelta(days=window_days - 1))
            try:
                r = client.get(f"{API}/{PIT_GG}", params={"index": "equities", "from_date": f"{a:%d-%m-%Y}", "to_date": f"{b:%d-%m-%Y}"})
                data = r.json().get("data", []) if r.status_code == 200 else []
                filings += data
            except Exception as exc:  # noqa: BLE001
                out["failures"].append({"window": f"{a}→{b}", "error": str(exc)[:120]})
            time.sleep(sleep_s)
            a = b + timedelta(days=1)
        seen: set[str] = set()
        todo = []
        for f in filings:
            app = str(f.get("appId") or "")
            key = f"{app}|{f.get('xmlFileName')}"
            if not app or key in seen or not f.get("xmlFileName"):
                continue
            seen.add(key)
            if app in known:
                out["skipped_known"] += 1
                continue
            todo.append(f)
        out["filings"] = len(seen)

        def one(f: dict) -> tuple[dict, Optional[list[dict]], Optional[str]]:
            try:
                xml = fetch_xbrl(client, f["xmlFileName"], xbrl_cache)
                if not xml:
                    return f, None, "no XBRL"
                return f, parse_pit_xbrl(xml, str(f.get("symbol") or "").upper(), str(f["appId"]),
                                         str(f.get("broadcastDateTime") or "")), None
            except Exception as exc:  # noqa: BLE001
                return f, None, str(exc)[:120]

        batch: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:       # static archive host: a few parallel fetches
            for i, (f, rows, err) in enumerate(pool.map(one, todo), 1):
                if err:
                    out["failures"].append({"appId": f.get("appId"), "error": err})
                elif rows is not None:
                    batch += rows
                    out["parsed"] += 1
                if len(batch) >= 200 or i == len(todo):
                    if batch:
                        out["rows"] += store.upsert_insider_trades(pd.DataFrame(batch).drop_duplicates("record_id"))
                    batch = []
                if progress:
                    progress(i, len(todo))
    finally:
        if own:
            client.close()
    out["failure_count"] = len(out["failures"])
    out["failures"] = out["failures"][:20]
    return out
