"""
IPO page: open and forthcoming issues with category-wise subscription (NSE), and a scorecard of recent listings
(listing-day gain and the return since, from our NSE bhavcopy), plus a descriptive table of QIB subscription level vs
listing outcome. Descriptive, not a pre-registered study: nothing here is a trading rule.

NSE endpoints (www.nseindia.com/api, cookie warm-up via the IPO page):
  all-upcoming-issues?category=ipo   forthcoming + open issues (dates, price band, size, lot)
  ipo-current-issue                  issues open today
  public-past-issues                 every past issue since 2016 (listing date, issue price, security type)
  ipo-detail?symbol=S&series=EQ      bid book by category (QIB / NII / RII), times subscribed
Details of listed issues never change, so they are cached on disk (data/nse_archive/ipo/<symbol>.json).
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Optional

import httpx
import numpy as np
import pandas as pd

PAGE = "https://www.nseindia.com/market-data/all-upcoming-issues-ipo"
API = "https://www.nseindia.com/api"
MAINBOARD = {"EQ", "BE"}
SME = {"SME"}


def _f(v: Any) -> Optional[float]:
    try:
        x = float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def parse_band(s: Any) -> tuple[Optional[float], Optional[float]]:
    """'Rs.258 to Rs.272' → (258, 272); '   272' → (272, 272); '-' → (None, None)."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(s or "").replace(",", ""))]
    if not nums:
        return None, None
    return min(nums), max(nums)


def parse_date(s: Any) -> Optional[str]:
    for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip().title() if fmt != "%Y-%m-%d" else str(s).strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_bids(detail: dict) -> dict[str, Optional[float]]:
    """Times subscribed per category from ipo-detail's bidDetails (srNo 1 = QIB, 2 = NII, 3 = RII, Total)."""
    out: dict[str, Optional[float]] = {"qib": None, "nii": None, "retail": None, "employee": None, "total": None}
    for b in detail.get("bidDetails") or []:
        cat, sr, x = str(b.get("category", "")).lower(), str(b.get("srNo") or ""), _f(b.get("noOfTime"))
        if x is None:
            continue
        if cat == "total":
            out["total"] = x
        elif sr == "1" or cat.startswith("qualified institutional"):
            out["qib"] = x
        elif sr == "2" or cat == "non institutional investors":
            out["nii"] = x
        elif sr == "3" or cat.startswith("retail individual"):
            out["retail"] = x
        elif "employee" in cat and out["employee"] is None:
            out["employee"] = x
    return out


def parse_upcoming(rows: list[dict]) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        lo, hi = parse_band(r.get("priceBand") or r.get("issuePrice"))
        shares = _f(r.get("issueSize"))
        out.append({"symbol": r.get("symbol"), "company": r.get("companyName"), "series": r.get("series"),
                    "status": r.get("status"), "start": parse_date(r.get("issueStartDate")), "end": parse_date(r.get("issueEndDate")),
                    "price_lo": lo, "price_hi": hi, "shares": shares, "lot": _f(r.get("lotSize")),
                    "size_cr": shares * hi / 1e7 if shares and hi else None})
    return [r for r in out if r["symbol"]]


def parse_past(rows: list[dict], kinds: set[str]) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        if r.get("securityType") not in kinds:
            continue
        listed = parse_date(r.get("listingDate"))
        issue = _f(r.get("issuePrice"))
        if not listed or not issue:
            continue
        out.append({"symbol": str(r.get("symbol", "")).strip(), "company": r.get("companyName") or r.get("company"),
                    "kind": "SME" if r.get("securityType") == "SME" else "Mainboard", "issue_price": issue,
                    "price_band": r.get("priceRange"), "open": parse_date(r.get("ipoStartDate")),
                    "close": parse_date(r.get("ipoEndDate")), "listing_date": listed})
    return sorted(out, key=lambda r: r["listing_date"], reverse=True)


def scorecard(past: list[dict], px: pd.DataFrame) -> list[dict[str, Any]]:
    """Listing-day open / close vs the issue price, then +20 / +60 sessions and the latest close (bhavcopy)."""
    if not past:
        return []
    paths = {s: g.sort_values("date") for s, g in px.groupby("symbol")} if px is not None and not px.empty else {}
    out = []
    for r in past:
        g = paths.get(r["symbol"])
        row = {**r, "list_open": None, "list_close": None, "listing_gain_pct": None, "listing_close_pct": None,
               "ret_20d_pct": None, "ret_60d_pct": None, "last_close": None, "since_issue_pct": None, "sessions": 0}
        if g is not None:
            g = g[g["date"] >= pd.Timestamp(r["listing_date"])]
        if g is not None and not g.empty:
            first, iss = g.iloc[0], r["issue_price"]
            # listing day: raw prices vs the issue price. After that: split/bonus-adjusted closes (adj_close), chained
            # from the day-1 close, so a later 1:5 split doesn't read as −80%.
            adj = g["adj_close"] if "adj_close" in g else g["close"]
            growth = adj / adj.iloc[0]
            row.update(list_open=float(first["open"]), list_close=float(first["close"]), sessions=len(g),
                       listing_gain_pct=(first["open"] / iss - 1) * 100, listing_close_pct=(first["close"] / iss - 1) * 100,
                       last_close=float(g["close"].iloc[-1]),
                       since_issue_pct=(first["close"] / iss * growth.iloc[-1] - 1) * 100)
            for n, key in ((20, "ret_20d_pct"), (60, "ret_60d_pct")):
                if len(g) > n:
                    row[key] = (growth.iloc[n] - 1) * 100
        out.append(row)
    return out


QIB_BUCKETS = [(0, 10, "< 10×"), (10, 50, "10–50×"), (50, 100, "50–100×"), (100, 1e9, "≥ 100×")]


def buckets(rows: list[dict]) -> list[dict[str, Any]]:
    """Listing outcome by QIB subscription bucket: count, mean / median listing gain, share listed above issue,
    mean 60-session return from the listing-day close."""
    df = pd.DataFrame([r for r in rows if r.get("qib") is not None and r.get("listing_gain_pct") is not None])
    out = []
    for lo, hi, label in QIB_BUCKETS:
        b = df[(df["qib"] >= lo) & (df["qib"] < hi)] if not df.empty else df
        r60 = b["ret_60d_pct"].dropna() if not b.empty else pd.Series(dtype=float)
        out.append({"bucket": label, "n": len(b),
                    "mean_listing_gain": round(float(b["listing_gain_pct"].mean()), 1) if len(b) else None,
                    "median_listing_gain": round(float(b["listing_gain_pct"].median()), 1) if len(b) else None,
                    "pct_listed_above": round(float((b["listing_gain_pct"] > 0).mean() * 100), 0) if len(b) else None,
                    "n_60d": len(r60), "mean_ret_60d": round(float(r60.mean()), 1) if len(r60) else None})
    return out


class IpoFeed:
    """NSE IPO endpoints with TTL caches, a disk cache for listed issues' bid books, and a background warm-up."""

    def __init__(self, cache_dir: Path, headers: dict[str, str]) -> None:
        self.cache_dir = cache_dir
        self.headers = {**headers, "Accept": "application/json,*/*", "Referer": PAGE}
        self._client: Optional[httpx.Client] = None
        self._warm = 0.0
        self._ttl: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.warming = {"running": False, "done": 0, "total": 0}
        self._empty: dict[str, float] = {}        # symbol → when NSE last returned no bid book (retry after 6 h)

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(headers=self.headers, timeout=25, follow_redirects=True)
            if time.time() - self._warm > 600:
                self._client.get(PAGE)
                self._warm = time.time()
            r = self._client.get(f"{API}/{path}", params=params)
            if r.status_code in (401, 403):
                self._warm = 0.0
                self._client.get(PAGE)
                self._warm = time.time()
                r = self._client.get(f"{API}/{path}", params=params)
            r.raise_for_status()
            return r.json()

    def cached(self, key: str, ttl: float, fn: Callable[[], Any]) -> Any:
        hit = self._ttl.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        val = fn()
        self._ttl[key] = (time.time(), val)
        return val

    def upcoming(self) -> list[dict]:
        return self.cached("upcoming", 600, lambda: self._get("all-upcoming-issues", {"category": "ipo"}))

    def current(self) -> list[dict]:
        return self.cached("current", 120, lambda: self._get("ipo-current-issue"))

    def past(self) -> list[dict]:
        return self.cached("past", 6 * 3600, lambda: self._get("public-past-issues"))

    def _path(self, symbol: str) -> Path:
        return self.cache_dir / f"{re.sub(r'[^A-Za-z0-9_&-]', '_', symbol)}.json"

    def detail(self, symbol: str, series: str = "EQ", listed: bool = False) -> dict:
        """Bid book of one issue. Listed issues come from (and go to) the disk cache; open ones are cached 2 min."""
        path = self._path(symbol)
        if listed and path.exists():
            return json.loads(path.read_text())
        d = self.cached(f"detail:{symbol}", 120, lambda: self._get("ipo-detail", {"symbol": symbol, "series": series}))
        if listed and (parse_bids(d).get("total") or 0) > 0:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(d))
        return d

    def cached_bids(self, symbol: str) -> Optional[dict]:
        path = self._path(symbol)
        return parse_bids(json.loads(path.read_text())) if path.exists() else None

    def warm_details(self, past: list[dict], limit: int = 200, sleep_s: float = 0.7) -> None:
        """Fetch missing bid books for the newest `limit` listed issues, in a background thread."""
        if self.warming["running"]:
            return
        now = time.time()
        todo = [r for r in past[:limit] if not self._path(r["symbol"]).exists()
                and now - self._empty.get(r["symbol"], 0.0) > 6 * 3600]
        if not todo:
            return
        self.warming.update(running=True, done=0, total=len(todo))

        def run() -> None:
            try:
                for r in todo:
                    try:
                        self.detail(r["symbol"], "SME" if r["kind"] == "SME" else "EQ", listed=True)
                    except Exception:
                        pass
                    if not self._path(r["symbol"]).exists():
                        self._empty[r["symbol"]] = time.time()
                    self.warming["done"] += 1
                    time.sleep(sleep_s)
            finally:
                self.warming["running"] = False
        threading.Thread(target=run, daemon=True).start()


def days_left(end: Optional[str], today: Optional[date] = None) -> Optional[int]:
    if not end:
        return None
    return (date.fromisoformat(end) - (today or date.today())).days
