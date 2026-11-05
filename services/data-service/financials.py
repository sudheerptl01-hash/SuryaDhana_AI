"""Quarterly financials (Bloomberg FA for NSE): revenue, profit and EPS for each of a company's last quarters, read
from the XBRL file attached to every NSE results filing.

Feeds (one request each, per company; same as results_history):
  integrated-filing-results      April 2025 → today  (type 'Integrated Filing- Financials'; qe_Date, consolidated)
  corporates-financial-results   2007 → early 2025   (toDate, consolidated)
Per quarter the consolidated filing is preferred (standalone otherwise); a revision replaces the original.

XBRL facts are in rupees whatever 'LevelOfRoundingUsedInFinancialStatements' says. The quarter is the 'OneD'
context (older filings label the year-to-date context with the quarter's dates too, so duration alone is not
enough); a context without dimensions lasting 80–100 days is the fallback. Banks file a different taxonomy:
interest earned stands in for revenue, and net interest income is reported.

Filed numbers never change, so each company's quarters are cached in data/nse_archive/financials/<SYMBOL>.json and
re-read at most once a day (new quarters only).
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import httpx

from nse_filings import API, API_HEADERS

# first tag found wins (local names, any namespace prefix)
FIELDS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromOperations", "InterestEarned",
                "NetPremiumIncome", "PremiumEarned", "NetPremiumWritten"),          # insurers: life (LI) / general (GI)
    "other_income": ("OtherIncome",),
    "total_income": ("Income",),
    "expenses": ("Expenses", "ExpenditureExcludingProvisionsAndContingencies"),
    "finance_costs": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",),
    "interest_expended": ("InterestExpended",),
    "pbt": ("ProfitBeforeTax", "ProfitLossFromOrdinaryActivitiesBeforeTax", "ProfitLossBeforeTax"),
    "pat": ("ProfitLossForPeriod", "ProfitLossForThePeriod",
            "ProfitLossAfterTaxAndExtraordinaryItems", "ProfitLossAfterTax"),
    "eps": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
            "BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsPerShareAfterExtraordinaryItems",
            "BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized"),
    "pat_owners": ("ProfitOrLossAttributableToOwnersOfParent", "ProfitLossAttributableToOwnersOfParent",
                   "ProfitLossAfterTaxesMinorityInterestAndShareOfProfitLossOfAssociates"),
    "paid_up": ("PaidUpValueOfEquityShareCapital",),
    "face_value": ("FaceValueOfEquityShareCapital",),
}
# balance-sheet facts sit on an instant context at the quarter end (half-year and year-end filings only)
INSTANT_FIELDS: dict[str, tuple[str, ...]] = {
    "book_equity": ("EquityAttributableToOwnersOfParent", "Equity", "TotalEquity"),
}
SCHEMA = 2          # bump when parse_xbrl gains fields: cached quarters of an older schema are read again
BANK_SCHEMA = 1     # banks only: book value from Capital + ReservesAndSurplus (13 Oct 2026)
TAXO_SCHEMA = 1     # companies where nothing parsed (insurers' LI / GI taxonomies, 13 Oct 2026) are read again


def cache_current(cache: Optional[dict[str, Any]]) -> bool:
    """True when a cached company was parsed with every field the parser now reads."""
    if not cache or cache.get("schema", 1) < SCHEMA:
        return False
    if any(q.get("bank") for q in cache.get("quarters") or []) and cache.get("bank_schema", 0) < BANK_SCHEMA:
        return False
    qs = cache.get("quarters") or []
    if qs and all(q.get("pat") is None and q.get("revenue") is None for q in qs) and cache.get("taxo_schema", 0) < TAXO_SCHEMA:
        return False
    return True

_CTX = re.compile(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', re.S)
_FACT = re.compile(r'<[\w-]+:(\w+)\b[^>]*contextRef="([^"]+)"[^>]*>([^<]*)<')


def _f(v: str) -> Optional[float]:
    try:
        return float(v.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def quarter_context(xml: str) -> Optional[tuple[str, str, str]]:
    """(context id, start, end) of the quarter: 'OneD' if present, else the latest dimension-free 80–100 day context."""
    found = []
    for cid, body in _CTX.findall(xml):
        if "dimension=" in body:
            continue
        s = re.search(r"<xbrli:startDate>([^<]+)<", body)
        e = re.search(r"<xbrli:endDate>([^<]+)<", body)
        if not (s and e):
            continue
        start, end = s.group(1).strip(), e.group(1).strip()
        if cid == "OneD":
            return cid, start, end
        try:
            days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        except ValueError:
            continue
        if 80 <= days <= 100:
            found.append((end, cid, start))
    if not found:
        return None
    end, cid, start = max(found)
    return cid, start, end


def instant_context(xml: str, end: str) -> Optional[str]:
    """Id of the dimension-free instant context at `end` (the balance-sheet date), if the filing has one."""
    for cid, body in _CTX.findall(xml):
        if "dimension=" in body:
            continue
        i = re.search(r"<xbrli:instant>([^<]+)<", body)
        if i and i.group(1).strip() == end:
            return cid
    return None


def shares_estimate(rows: list[dict[str, Any]]) -> Optional[float]:
    """Shares outstanding from the newest filings (rows newest first). Paid-up capital ÷ face value is exact when
    filed correctly, but filers make typos (SHILPAMED's Jun-2026 XBRL has a face value of 1956 instead of 1), so it
    is cross-checked against profit ÷ EPS: the newest quarter where the two agree within 25% wins; failing that,
    profit ÷ EPS of the newest quarter that has both."""
    implied_first: Optional[float] = None
    for q in rows[:4]:
        pat = q.get("pat_owners") if q.get("pat_owners") not in (None, 0) else q.get("pat")
        implied = pat / q["eps"] if pat and q.get("eps") and q["eps"] * pat > 0 else None
        if implied_first is None and implied:
            implied_first = implied
        cand = q.get("shares")
        if cand and implied and abs(cand / implied - 1) < 0.25:
            return float(cand)
        if cand and not implied and q is rows[0]:
            return float(cand)
    return implied_first


def valuation(rows: list[dict[str, Any]], price: Optional[float]) -> dict[str, Any]:
    """Market cap, trailing-twelve-month profit, P/E and P/B from the newest quarters (rows newest first) and a
    price. TTM needs the last four quarters to be consecutive; shares = paid-up capital ÷ face value of the latest
    filing (a bonus or split after that quarter-end would make this stale)."""
    if not rows or not price:
        return {}
    shares = shares_estimate(rows)
    out: dict[str, Any] = {"price": price, "shares": shares, "mcap": shares * price if shares else None}
    four = rows[:4]
    consecutive = len(four) == 4 and all(
        (date.fromisoformat(a["period_end"]).year * 12 + date.fromisoformat(a["period_end"]).month)
        - (date.fromisoformat(b["period_end"]).year * 12 + date.fromisoformat(b["period_end"]).month) == 3
        for a, b in zip(four, four[1:]))
    # profit to owners when filed; some companies put 0 there while reporting a profit, so 0 counts as not filed
    profits: list[Optional[float]] = [q["pat_owners"] if q.get("pat_owners") not in (None, 0) or q.get("pat") in (None, 0)
                                      else q.get("pat") for q in four]
    known = [v for v in profits if v is not None]
    ttm = float(sum(known)) if consecutive and len(known) == 4 else None
    out["ttm_profit"] = ttm
    out["pe"] = round(out["mcap"] / ttm, 1) if out["mcap"] and ttm and ttm > 0 else None
    if out["pe"] is not None and out["pe"] < 1:          # below 1× is a filing / share-count error, not a bargain
        out["pe"] = None
    book = next(((q["book_equity"], q["period_end"]) for q in rows if q.get("book_equity")), None)
    out["book_equity"], out["book_as_of"] = (book if book else (None, None))
    out["pb"] = round(out["mcap"] / book[0], 2) if out["mcap"] and book and book[0] > 0 else None
    return out


def pe_series(rows: list[dict[str, Any]], closes: "Any", shares: Optional[float]) -> dict[str, Any]:
    """Daily trailing P/E, point-in-time: on each day, market cap (split/bonus-adjusted close × today's share count)
    ÷ the last four quarters' profit **as filed by that day** (a quarter counts from its filing date). `rows` newest
    first (with_growth output); `closes` a pandas Series of adjusted closes indexed by date. Days with no
    four consecutive filed quarters, or a loss, are skipped. Returns points plus percentile stats."""
    import pandas as pd
    if not shares or closes is None or len(closes) == 0 or len(rows) < 4:
        return {"points": []}
    def months(pe: str) -> int:
        d = date.fromisoformat(pe)
        return d.year * 12 + d.month
    ttm = []                                          # (available_from, ttm profit), oldest first
    for i in range(len(rows) - 3):
        four = rows[i:i + 4]
        if not all(months(a["period_end"]) - months(b["period_end"]) == 3 for a, b in zip(four, four[1:])):
            continue
        prof = [q["pat_owners"] if q.get("pat_owners") not in (None, 0) or q.get("pat") in (None, 0) else q.get("pat") for q in four]
        if any(v is None for v in prof) or not four[0].get("filed_at"):
            continue
        ttm.append((pd.Timestamp(four[0]["filed_at"][:10]), float(sum(prof))))
    if not ttm:
        return {"points": []}
    ttm.sort()
    starts = pd.DatetimeIndex([t for t, _ in ttm])
    vals = [v for _, v in ttm]
    pts = []
    for d, px in closes.dropna().items():
        k = int(starts.searchsorted(pd.Timestamp(d), side="right")) - 1
        if k < 0 or vals[k] <= 0:
            continue
        pts.append((pd.Timestamp(d).date().isoformat(), round(float(px) * shares / vals[k], 2)))
    if not pts:
        return {"points": []}
    series = pd.Series([p for _, p in pts])
    now = pts[-1][1]
    return {"points": [{"date": d, "pe": p} for d, p in pts], "now": now,
            "median": round(float(series.median()), 1), "p25": round(float(series.quantile(0.25)), 1),
            "p75": round(float(series.quantile(0.75)), 1), "low": round(float(series.min()), 1), "high": round(float(series.max()), 1),
            "percentile": round(float((series < now).mean() * 100), 0), "since": pts[0][0]}


def parse_xbrl(xml: str) -> Optional[dict[str, Any]]:
    """One quarter's headline numbers (₹) from an NSE results XBRL file, or None if it has no quarter context."""
    q = quarter_context(xml)
    if not q:
        return None
    cid, start, end = q
    facts: dict[str, float] = {}
    for name, ctx, val in _FACT.findall(xml):
        if ctx == cid and name not in facts:
            v = _f(val)
            if v is not None:
                facts[name] = v
    out: dict[str, Any] = {"period_start": start, "period_end": end, "bank": "InterestEarned" in facts}
    for key, tags in FIELDS.items():
        out[key] = next((facts[t] for t in tags if t in facts), None)
    inst = instant_context(xml, end)
    ifacts: dict[str, float] = {}
    if inst:
        for name, ctx, val in _FACT.findall(xml):
            if ctx == inst and name not in ifacts:
                v = _f(val)
                if v is not None:
                    ifacts[name] = v
    for key, tags in INSTANT_FIELDS.items():
        out[key] = next((ifacts[t] for t in tags if t in ifacts), None)
    if out["book_equity"] is None and "Capital" in ifacts and "ReservesAndSurplus" in ifacts:
        out["book_equity"] = ifacts["Capital"] + ifacts["ReservesAndSurplus"]     # banking taxonomy
    out["shares"] = out["paid_up"] / out["face_value"] if out.get("paid_up") and out.get("face_value") else None
    if out["bank"] and out["revenue"] is not None and out["interest_expended"] is not None:
        out["nii"] = out["revenue"] - out["interest_expended"]
    return out


def _d(v: Any) -> Optional[date]:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(str(v).strip().title(), fmt).date()
        except ValueError:
            continue
    return None


def _ts(v: Any) -> str:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return datetime.strptime(str(v).strip(), fmt).isoformat()
        except ValueError:
            continue
    return ""


def choose_filings(integrated: list[dict], legacy: list[dict]) -> list[dict[str, Any]]:
    """One filing per quarter-end, newest first: consolidated over standalone, the latest revision within each."""
    cands = []
    for r in integrated or []:
        if "Financ" not in str(r.get("type", "")) or not r.get("xbrl"):
            continue
        cands.append({"period_end": _d(r.get("qe_Date")), "consolidated": str(r.get("consolidated", "")).startswith("Cons"),
                      "filed_at": _ts(r.get("broadcast_Date")), "xbrl": r["xbrl"]})
    for r in legacy or []:
        if not r.get("xbrl") or str(r.get("period", "Quarterly")) != "Quarterly":
            continue
        cands.append({"period_end": _d(r.get("toDate")), "consolidated": str(r.get("consolidated", "")).startswith("Cons"),
                      "filed_at": _ts(r.get("broadCastDate")), "xbrl": r["xbrl"]})
    best: dict[date, dict[str, Any]] = {}
    for c in cands:
        pe = c["period_end"]
        if pe is None or not str(c["xbrl"]).lower().endswith(".xml"):
            continue
        cur = best.get(pe)
        if cur is None or (c["consolidated"], c["filed_at"]) > (cur["consolidated"], cur["filed_at"]):
            best[pe] = c
    return [dict(best[k], period_end=k.isoformat()) for k in sorted(best, reverse=True)]


MONEY_FIELDS = ("revenue", "other_income", "total_income", "expenses", "finance_costs", "depreciation",
                "interest_expended", "pbt", "pat", "pat_owners", "nii", "book_equity", "paid_up")


def fix_scale(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Some filers enter one quarter's XBRL in the wrong unit (COROMANDEL's Mar-2026 filing reports revenue of
    ₹60 cr and a full year of ₹315 cr, both exactly 100× too small). A quarter whose revenue is more than 30× away
    from the company's median quarter, and lands within 3× of it once multiplied or divided by 100, has every
    money field rescaled and is marked `scale_fixed` (±100), but only when the error is confirmed: that filing's
    paid-up capital (or profit ÷ EPS) is off by the same factor. Needs at least four quarters with revenue."""
    revs = sorted(q["revenue"] for q in rows if q.get("revenue") and q["revenue"] > 0)
    if len(revs) < 4:
        return rows
    med = revs[len(revs) // 2]

    def median_of(vals: list[float]) -> Optional[float]:
        vals = sorted(v for v in vals if v and v > 0)
        return vals[len(vals) // 2] if vals else None

    def confirmed(q: dict[str, Any], factor: float) -> bool:
        """A unit error scales the whole filing, share capital included; a genuinely tiny quarter does not."""
        others = [x for x in rows if x is not q]
        ref_pu = median_of([x.get("paid_up") for x in others])
        if q.get("paid_up") and ref_pu:
            return abs(q["paid_up"] * factor / ref_pu - 1) < 0.10
        ref_sh = median_of([x["pat"] / x["eps"] for x in others if x.get("pat") and x.get("eps") and x["pat"] * x["eps"] > 0])
        if q.get("pat") and q.get("eps") and ref_sh and q["pat"] * q["eps"] > 0:
            return abs(q["pat"] * factor / q["eps"] / ref_sh - 1) < 0.20
        return False

    out = []
    for q in rows:
        r = q.get("revenue")
        factor = None
        if r and r > 0:
            if r < med / 30 and med / 3 <= r * 100 <= med * 3:
                factor = 100.0
            elif r > med * 30 and med / 3 <= r / 100 <= med * 3:
                factor = 0.01
        if factor and not confirmed(q, factor):
            factor = None
        if factor:
            q = {**q, **{k: q[k] * factor for k in MONEY_FIELDS if isinstance(q.get(k), (int, float))},
                 "scale_fixed": 100 if factor > 1 else -100}
            if q.get("paid_up") and q.get("face_value"):
                q["shares"] = q["paid_up"] / q["face_value"]
        out.append(q)
    return out


def with_growth(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add YoY / QoQ growth and margins. `rows` newest first, one per quarter-end. No EPS growth: reported EPS is
    not adjusted for bonuses / splits (HDFCBANK's 1:1 bonus halves it), so only revenue and profit are compared."""
    rows = fix_scale(rows)

    def ago(pe: str, months: int) -> Optional[dict[str, Any]]:
        d = date.fromisoformat(pe)
        y, m = d.year, d.month - months
        while m <= 0:
            y, m = y - 1, m + 12
        for r in rows:                                  # same month-end of an earlier year/quarter
            rd = date.fromisoformat(r["period_end"])
            if (rd.year, rd.month) == (y, m):
                return r
        return None

    def g(a: Optional[float], b: Optional[float]) -> Optional[float]:
        return round((a / b - 1) * 100, 1) if a is not None and b not in (None, 0) and b > 0 else None

    def turn(a: Optional[float], b: Optional[float]) -> Optional[str]:
        """Profit changing sign makes a % meaningless: say what happened instead."""
        if a is None or b is None:
            return None
        return "to loss" if a < 0 <= b else "to profit" if b < 0 <= a else "loss both" if a < 0 and b < 0 else None

    out = []
    for r in rows:
        y, q = ago(r["period_end"], 12), ago(r["period_end"], 3)
        rev, pat = r.get("revenue"), r.get("pat")
        py, pq = (y or {}).get("pat"), (q or {}).get("pat")
        out.append({**r, "pat_yoy_turn": turn(pat, py), "pat_qoq_turn": turn(pat, pq),
                    "revenue_yoy": g(rev, (y or {}).get("revenue")), "revenue_qoq": g(rev, (q or {}).get("revenue")),
                    "pat_yoy": g(pat, py) if turn(pat, py) is None else None,
                    "pat_qoq": g(pat, pq) if turn(pat, pq) is None else None,
                    "pat_margin": round(pat / rev * 100, 1) if pat is not None and rev else None})
    return out


def _cache_path(root: Path, symbol: str) -> Path:
    return root / f"{symbol}.json"


def load(root: Path, symbol: str) -> Optional[dict[str, Any]]:
    try:
        return json.loads(_cache_path(root, symbol).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def refresh(root: Path, symbol: str, quarters: int = 12, client: Optional[httpx.Client] = None,
            sleep_s: float = 0.3) -> dict[str, Any]:
    """Read the feeds, download XBRL only for quarters not cached yet, save and return the cache."""
    own = client is None
    client = client or httpx.Client(headers=API_HEADERS, timeout=30, follow_redirects=True)
    cache = load(root, symbol) or {"symbol": symbol, "quarters": []}
    if cache.get("quarters") and not cache_current(cache):     # parsed with fewer fields: read the filings again
        cache = {"symbol": symbol, "quarters": []}
    have = {q["period_end"] for q in cache["quarters"]}
    try:
        feeds = []
        for path, extra in (("integrated-filing-results", {}), ("corporates-financial-results", {"period": "Quarterly"})):
            try:
                r = client.get(f"{API}/{path}", params={"index": "equities", "symbol": symbol, **extra})
                d = r.json() if r.status_code == 200 else []
                feeds.append(d if isinstance(d, list) else d.get("data", []))
            except (httpx.HTTPError, ValueError):
                feeds.append([])
            time.sleep(sleep_s)
        for f in choose_filings(feeds[0], feeds[1])[:quarters]:
            if f["period_end"] in have:
                continue
            try:
                x = client.get(f["xbrl"])
                parsed = parse_xbrl(x.text) if x.status_code == 200 else None
            except httpx.HTTPError:
                parsed = None
            if parsed and parsed["period_end"] == f["period_end"]:
                cache["quarters"].append({**parsed, "consolidated": f["consolidated"], "filed_at": f["filed_at"], "xbrl": f["xbrl"]})
            time.sleep(sleep_s)
    finally:
        if own:
            client.close()
    cache["quarters"] = sorted(cache["quarters"], key=lambda q: q["period_end"], reverse=True)[:quarters]
    cache["fetched_at"] = datetime.now().isoformat(timespec="seconds")
    cache["schema"] = SCHEMA
    cache["bank_schema"] = BANK_SCHEMA
    cache["taxo_schema"] = TAXO_SCHEMA
    root.mkdir(parents=True, exist_ok=True)
    _cache_path(root, symbol).write_text(json.dumps(cache), encoding="utf-8")
    return cache
