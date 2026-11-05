"""
MOV page: NSE live market analysis during the session. Gainers and losers per universe, most active by value,
volume surges vs the 1-week average, live 52-week highs and lows, F&O OI spurts, and every sectoral / broad index
with its breadth. NSE's own live endpoints (www.nseindia.com/api, ~1 min delayed), cached 30 s while the market
is open and 10 min otherwise. Nothing is stored: the EOD bhavcopy has the closing picture.
"""
from __future__ import annotations

import re

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

PAGE = "https://www.nseindia.com/market-data/top-gainers-losers"
HEATMAP_BROAD = ("NIFTY 50", "NIFTY NEXT 50", "NIFTY MIDCAP 50")   # heatmap-symbols caps a list at 50 names
API = "https://www.nseindia.com/api"
UNIVERSES = ("NIFTY", "BANKNIFTY", "NIFTYNEXT50", "FOSec", "SecGtr20", "allSec")
INDEX_GROUPS = ("INDICES ELIGIBLE IN DERIVATIVES", "BROAD MARKET INDICES", "SECTORAL INDICES", "THEMATIC INDICES",
                "FIXED INCOME INDICES")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def parse_variations(payload: dict, universe: str, n: int = 20) -> list[dict[str, Any]]:
    """live-analysis-variations (gainers / loosers) → rows for one universe. turnover is in ₹ lakh."""
    rows = []
    for r in ((payload or {}).get(universe) or {}).get("data") or []:
        rows.append({"symbol": r.get("symbol"), "ltp": _f(r.get("ltp")), "change_pct": _f(r.get("perChange", r.get("net_price"))),
                     "open": _f(r.get("open_price")), "high": _f(r.get("high_price")), "low": _f(r.get("low_price")),
                     "prev_close": _f(r.get("prev_price")), "volume": _f(r.get("trade_quantity")),
                     "value_cr": (_f(r.get("turnover")) or 0) / 100 or None})
    return [r for r in rows if r["symbol"]][:n]


def parse_active(payload: dict, n: int = 20) -> list[dict[str, Any]]:
    return [{"symbol": r.get("symbol"), "ltp": _f(r.get("lastPrice")), "change_pct": _f(r.get("pChange")),
             "volume": _f(r.get("totalTradedVolume")), "value_cr": (_f(r.get("totalTradedValue")) or 0) / 1e7 or None,
             "year_high": _f(r.get("yearHigh")), "year_low": _f(r.get("yearLow"))}
            for r in ((payload or {}).get("data") or [])[:n] if r.get("symbol")]


def parse_volume_gainers(payload: dict, n: int = 60) -> list[dict[str, Any]]:
    """Volume vs the 1-week average (×). turnover is in ₹ lakh."""
    return [{"symbol": r.get("symbol"), "company": r.get("companyName"), "ltp": _f(r.get("ltp")), "change_pct": _f(r.get("pChange")),
             "volume": _f(r.get("volume")), "vs_week": _f(r.get("week1volChange")), "vs_2week": _f(r.get("week2volChange")),
             "value_cr": (_f(r.get("turnover")) or 0) / 100 or None}
            for r in ((payload or {}).get("data") or [])[:n] if r.get("symbol")]


def parse_52w(payload: dict, n: int = 30) -> dict[str, Any]:
    rows = [{"symbol": r.get("symbol"), "company": r.get("comapnyName") or r.get("companyName"), "ltp": _f(r.get("ltp")),
             "change_pct": _f(r.get("pChange")), "new_level": _f(r.get("new52WHL")), "prev_level": _f(r.get("prev52WHL")),
             "prev_date": r.get("prevHLDate")}
            for r in ((payload or {}).get("data") or []) if r.get("symbol")]
    count = (payload or {}).get("high", (payload or {}).get("low"))
    return {"count": int(count) if count is not None else len(rows), "rows": rows[:n]}


def parse_oi_spurts(payload: dict, n: int = 20) -> list[dict[str, Any]]:
    rows = [{"symbol": r.get("symbol"), "oi": _f(r.get("latestOI")), "prev_oi": _f(r.get("prevOI")), "oi_change": _f(r.get("changeInOI")),
             "oi_change_pct": _f(r.get("avgInOI")), "underlying": _f(r.get("underlyingValue")), "volume": _f(r.get("volume"))}
            for r in ((payload or {}).get("data") or []) if r.get("symbol")]
    return sorted(rows, key=lambda r: -(r["oi_change_pct"] or 0))[:n]


def parse_indices(payload: dict) -> list[dict[str, Any]]:
    out = []
    for r in (payload or {}).get("data") or []:
        if r.get("key") not in INDEX_GROUPS:
            continue
        adv, dec = _f(r.get("advances")), _f(r.get("declines"))
        out.append({"group": r.get("key"), "index": r.get("index"), "last": _f(r.get("last")), "change_pct": _f(r.get("percentChange")),
                    "advances": int(adv) if adv is not None else None, "declines": int(dec) if dec is not None else None,
                    "pct_30d": _f(r.get("perChange30d")), "pct_365d": _f(r.get("perChange365d")),
                    "year_high": _f(r.get("yearHigh")), "year_low": _f(r.get("yearLow")), "pe": _f(r.get("pe"))})
    return out


def parse_heatmap(rows: list[dict]) -> dict[str, dict[str, Any]]:
    """heatmap-symbols rows → {symbol: live quote}. quantityTraded is the traded value in rupees."""
    out: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        sym = r.get("symbol")
        if not sym or r.get("series") not in (None, "EQ", "BE"):
            continue
        out[sym] = {"ltp": _f(r.get("lastPrice")), "change_pct": _f(r.get("pChange")), "vwap": _f(r.get("VWAP")),
                    "value_cr": (_f(r.get("quantityTraded")) or 0) / 1e7 or None, "time": r.get("lastUpdatedTime")}
    return out


# Filing categories, first match wins (subject + attachment text, lower-case). "routine" is hidden by default.
FILING_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("routine", ("depositories and participants", "trading window", "newspaper publication", "structural digital database",
                 "compliance certificate", "regulation 74(5)", "reg. 74(5)", "loss of share certificate", "duplicate share",
                 "esop", "esos", "statement of investor complaints")),
    ("results", ("financial result", "integrated filing", "results for the quarter", "audited results", "unaudited results")),
    ("orders", ("award of order", "receipt of order", "bagging", "order win", "contract", "letter of award", "work order")),
    ("rating", ("credit rating",)),
    ("insider", ("insider trading", "sast", "takeover regulations", "substantial acquisition", "pledge", "encumbrance",
                 "regulation 29", "regulation 31")),
    ("m&a", ("acquisition", "amalgamation", "merger", "scheme of arrangement", "demerger", "open offer", "takeover")),
    ("capital", ("dividend", "record date", "bonus", "split", "buyback", "buy back", "rights issue", "allotment",
                 "fund raising", "qip", "preferential issue", "warrants")),
    ("people", ("appointment", "resignation", "cessation", "change in management", "change in directorate",
                "key managerial")),
    ("board", ("board meeting", "outcome of board")),
    ("analyst", ("analysts/institutional", "investor meet", "con. call", "earnings call")),
    ("press", ("press release", "media release")),
)


_RESULTS_TEXT = re.compile(r"submitted to the exchange,? the financial results|(approved|adopted|considered)\b.{0,120}\bresults"
                           r"|(un)?audited\b.{0,60}\bfinancial results (of|for)", re.I | re.S)


def filing_category(subject: str, text: str = "") -> str:
    """NSE's subject is standardised, so it decides first: an earnings-call / analyst-meet notice that mentions
    'financial results' is analyst news, not results; 'Integrated Filing- Governance' is routine; a note on
    delayed results is not results. 'Outcome of Board Meeting' is results only when the text says results were
    filed or approved. Everything else falls back to keywords."""
    s, t = subject.lower(), text.lower()
    if "integrated filing- governance" in s or "integrated filing-governance" in s:
        return "routine"
    if "delayed" in s and "result" in s:
        return "other"
    if any(k in s for k in ("analysts/institutional", "investor meet", "con. call")):
        return "analyst"
    if "financial result" in s or "integrated filing- financial" in s or "integrated filing-financial" in s:
        return "results"
    if "outcome of board" in s and _RESULTS_TEXT.search(t):
        return "results"
    if ("press release" in s or "media release" in s or "general update" in s) and "result" in t:
        return "press"
    blob = f"{s} {t}"
    for cat, keys in FILING_RULES:
        if cat == "results" and any(k in blob for k in ("earnings call", "conference call", "con. call", "call with media",
                                                         "analyst", "investor meet", "intimation of board meeting",
                                                         "board meeting intimation", "to consider and approve")):
            continue                                   # talks about results, but is not the results
        if any(k in blob for k in keys):
            return cat
    return "other"


def parse_announcements(rows: list[dict]) -> list[dict[str, Any]]:
    out = []
    for r in rows or []:
        if not r.get("symbol"):
            continue
        subject, text = r.get("desc") or "", r.get("attchmntText") or ""
        out.append({"symbol": r["symbol"], "company": r.get("sm_name"), "time": r.get("sort_date") or r.get("an_dt"),
                    "subject": subject, "text": text[:600], "pdf": r.get("attchmntFile") or None,
                    "category": filing_category(subject, text), "seq": r.get("seq_id")})
    return sorted(out, key=lambda x: x["time"] or "", reverse=True)


def parse_gift_nifty(status: dict) -> dict[str, Any]:
    """NSE marketStatus → GIFT NIFTY (NSE IX NIFTY future: 06:30–15:40 and 16:35–02:45 IST) and the gap it implies
    against NIFTY 50's last close. `giftnifty` updates after the Indian close, so it is GIFT, not NSE's own future."""
    g = (status or {}).get("giftnifty") or {}
    cm: dict[str, Any] = next((m for m in (status or {}).get("marketState") or [] if m.get("market") == "Capital Market"), {})
    last, nifty = _f(g.get("LASTPRICE")), _f(cm.get("last"))
    return {"last": last, "change": _f(g.get("DAYCHANGE")), "change_pct": _f(g.get("PERCHANGE")),
            "expiry": g.get("EXPIRYDATE"), "time": g.get("TIMESTMP"), "contracts": _f(g.get("CONTRACTSTRADED")),
            "nifty_last": nifty, "nifty_status": cm.get("marketStatus"),
            "implied_gap_pct": round((last / nifty - 1) * 100, 2) if last and nifty else None}


def parse_index_quote(all_indices: dict, name: str = "NIFTY 50") -> dict[str, Any]:
    """One index from NSE allIndices: last, change, %, open / high / low / previous close and NSE's timestamp."""
    row = next((r for r in (all_indices or {}).get("data") or [] if r.get("index") == name), None) or {}
    return {"index": name, "last": _f(row.get("last")), "change": _f(row.get("variation")), "change_pct": _f(row.get("percentChange")),
            "open": _f(row.get("open")), "high": _f(row.get("high")), "low": _f(row.get("low")),
            "previous_close": _f(row.get("previousClose")), "time": (all_indices or {}).get("timestamp")}


def parse_symbol_chart(payload: dict, minutes: int = 5) -> dict[str, Any]:
    """NSE chart-databyindex-dynamic → OHLC bars of `minutes` from its ~1-minute price points (normal market only;
    pre-open points ('PO', or anything before 09:15) and the 15:30–16:00 closing session are dropped). NSE stamps IST clock time as if it were UTC epoch-ms, so `ts` is
    IST-as-UTC seconds (what lightweight-charts wants for local display). No volume in this feed."""
    open_s, close_s = 9 * 3600 + 15 * 60, 15 * 3600 + 30 * 60   # normal market only: no pre-open, no closing session
    pts = [(int(p[0]) // 1000, _f(p[1])) for p in payload.get("grapthData") or []
           if len(p) >= 2 and (len(p) < 3 or p[2] != "PO") and _f(p[1]) and open_s <= (int(p[0]) // 1000) % 86400 < close_s]
    step = max(1, minutes) * 60
    bars: dict[int, dict[str, Any]] = {}
    for ts, px in sorted(pts):
        b = ts - ts % step
        bar = bars.get(b)
        if bar is None:
            bars[b] = {"ts": b, "open": px, "high": px, "low": px, "close": px, "volume": 0}
        else:
            bar["high"], bar["low"], bar["close"] = max(bar["high"], px), min(bar["low"], px), px
    rows = [dict(v, date=datetime.fromtimestamp(k, timezone.utc).strftime("%Y-%m-%d %H:%M:%S")) for k, v in sorted(bars.items())]
    return {"day": rows[-1]["date"][:10] if rows else None, "previous_close": _f(payload.get("closePrice")), "rows": rows}


_RS = re.compile(r"(?:rs\.?|₹|inr)\s*([0-9]+(?:\.[0-9]+)?)", re.I)


def parse_actions(rows: list[dict], today: Optional[datetime] = None) -> dict[str, Any]:
    """NSE corporate actions for one company → typed items (dividend / bonus / split / buyback / rights / other),
    rupees per share for dividends (interim + special added up, special flagged), dividends per Indian financial
    year, and the trailing-12-month dividend per share. TTM is withheld when a split or bonus happened inside the
    window (per-share amounts before and after would not be comparable)."""
    now = today or datetime.now()
    items: list[dict[str, Any]] = []
    for r in rows or []:
        subj = str(r.get("subject") or "").strip()
        try:
            ex = datetime.strptime(str(r.get("exDate") or "").strip(), "%d-%b-%Y")
        except ValueError:
            continue
        low = subj.lower()
        kind = ("dividend" if "dividend" in low else "bonus" if "bonus" in low else
                "split" if "split" in low or "sub-division" in low or "subdivision" in low else
                "buyback" if "buy back" in low or "buyback" in low else "rights" if "rights" in low else "other")
        amount = sum(float(x) for x in _RS.findall(subj)) if kind == "dividend" else None
        if kind == "split":
            amount = None                       # "From Rs 10 To Rs 2" is a face value, not a payout
        items.append({"ex_date": ex.date().isoformat(), "kind": kind, "subject": subj, "rs_per_share": amount,
                      "special": "special" in low})
    items.sort(key=lambda x: x["ex_date"], reverse=True)
    from datetime import timedelta
    since = (now - timedelta(days=365)).date().isoformat()          # not replace(year=…): 29 Feb
    window = [i for i in items if i["ex_date"] > since and i["ex_date"] <= now.date().isoformat()]
    reshaped = any(i["kind"] in ("bonus", "split") for i in window)
    ttm = round(sum(i["rs_per_share"] or 0 for i in window if i["kind"] == "dividend"), 2)
    by_fy: dict[str, float] = {}
    for i in items:
        if i["kind"] == "dividend" and i["rs_per_share"]:
            d = datetime.fromisoformat(i["ex_date"])
            fy = f"FY{(d.year + 1 if d.month >= 4 else d.year) % 100:02d}"
            by_fy[fy] = round(by_fy.get(fy, 0) + i["rs_per_share"], 2)
    return {"items": items, "ttm_dividend": None if reshaped else ttm, "ttm_reshaped": reshaped, "by_fy": by_fy}


def market_open(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    return now.weekday() < 5 and (9, 15) <= (now.hour, now.minute) <= (15, 35)


_IST = timezone(timedelta(hours=5, minutes=30))


def fresh_nse_print(timestamp: Any, now: datetime | None = None, max_age_s: float = 300.0) -> bool:
    """NSE's own timestamp (`08-Nov-2026 18:19` / `… 18:19:05`, IST wall clock) within `max_age_s` of `now` (aware;
    default: the current time) and at most 2 min ahead of it: NSE is printing whatever the calendar says (Muhurat,
    a special Saturday session)."""
    if not isinstance(timestamp, str):
        return False
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            t = datetime.strptime(timestamp.strip(), fmt).replace(tzinfo=_IST)
        except ValueError:
            continue
        age = ((now or datetime.now(_IST)) - t).total_seconds()
        return -120 <= age <= max_age_s
    return False


class NseLive:
    """Shared NSE session and per-endpoint TTL cache (30 s during the session, 10 min otherwise). Thread-safe."""

    def __init__(self, headers: dict[str, str]) -> None:
        self.headers = {**headers, "Accept": "application/json,*/*", "Referer": PAGE}
        self._client: Optional[httpx.Client] = None
        self._warm = 0.0
        self._cache: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        # circuit breaker: when NSE refuses us (403/429 even after a fresh cookie) back off for BACKOFF_S and serve
        # the last good copy, so the terminal's live pages can't get the machine's IP blocked
        self.blocked_until = 0.0

    BACKOFF_S = 600

    def _session(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                # short timeouts: a slow NSE answer must not hold the live pages past the UI proxy's 30 s limit
                self._client = httpx.Client(headers=self.headers, timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True)
            if time.time() - self._warm > 600:
                self._client.get(PAGE)
                self._warm = time.time()
            return self._client

    def get(self, path: str, ttl_open: float = 30, ttl_closed: float = 600) -> Any:
        ttl = ttl_open if market_open() else ttl_closed
        hit = self._cache.get(path)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        if time.time() < self.blocked_until:
            if hit:
                return hit[1]                               # stale but honest: callers show their own timestamps
            raise RuntimeError(f"NSE is throttling us; retrying after {time.strftime('%H:%M', time.localtime(self.blocked_until))}")
        r = self._session().get(f"{API}/{path}")
        if r.status_code in (401, 403):
            self._warm = 0.0
            r = self._session().get(f"{API}/{path}")
        if r.status_code in (403, 429):
            self.blocked_until = time.time() + self.BACKOFF_S
            if hit:
                return hit[1]
        r.raise_for_status()
        val = r.json()
        self._cache[path] = (time.time(), val)
        return val

    def snapshot(self, universe: str = "FOSec") -> dict[str, Any]:
        paths = {"gainers": "live-analysis-variations?index=gainers", "losers": "live-analysis-variations?index=loosers",
                 "value": "live-analysis-most-active-securities?index=value", "volume": "live-analysis-volume-gainers",
                 "high": "live-analysis-data-52weekhighstock", "low": "live-analysis-data-52weeklowstock",
                 "oi": "live-analysis-oi-spurts-underlyings", "indices": "allIndices"}
        self._session()                                    # warm once before fanning out
        raw: dict[str, Any] = {}
        errors: dict[str, str] = {}

        def fetch(k: str) -> None:
            try:
                raw[k] = self.get(paths[k])
            except Exception as exc:                       # one NSE endpoint failing must not blank the page
                errors[k] = str(exc)[:120]
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(fetch, paths))
        ts = ((raw.get("gainers") or {}).get(universe) or {}).get("timestamp") or (raw.get("value") or {}).get("timestamp")
        return {
            "universe": universe, "timestamp": ts, "market_open": market_open(), "errors": errors,
            "gainers": parse_variations(raw.get("gainers") or {}, universe),
            "losers": parse_variations(raw.get("losers") or {}, universe),
            "most_active": parse_active(raw.get("value") or {}),
            "volume_surge": parse_volume_gainers(raw.get("volume") or {}),
            "highs": parse_52w(raw.get("high") or {}), "lows": parse_52w(raw.get("low") or {}),
            "oi_spurts": parse_oi_spurts(raw.get("oi") or {}),
            "indices": parse_indices(raw.get("indices") or {}),
        }

    def heatmap_quotes(self) -> dict[str, Any]:
        """Live quotes for every member of NSE's sectoral indices plus NIFTY 50 / NEXT 50 / MIDCAP 50 (≈300 stocks)
        from the heatmap endpoints: one request per index, cached like the rest (30 s in session)."""
        self._session()
        try:
            sectors = [x["index"] for x in self.get("heatmap-index?type=Sectoral%20Indices", ttl_open=3600) or [] if x.get("index")]
        except Exception:
            sectors = []
        lists = [("Sectoral Indices", ix) for ix in sectors] + [("Broad Market Indices", ix) for ix in HEATMAP_BROAD]
        quotes: dict[str, dict[str, Any]] = {}
        failed: list[str] = []

        def fetch(item: tuple[str, str]) -> None:
            kind, ix = item
            try:
                # 60 s: 26 lists per refresh is the heaviest NSE call the terminal makes
                quotes.update(parse_heatmap(self.get(f"heatmap-symbols?type={kind.replace(' ', '%20')}&indices={ix.replace(' ', '%20').replace('&', '%26')}", ttl_open=60)))
            except Exception:
                failed.append(ix)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(fetch, lists))
        return {"quotes": quotes, "lists": len(lists), "failed": failed, "market_open": market_open()}

    def announcements(self, day: Optional[datetime] = None) -> dict[str, Any]:
        """Every NSE equity announcement of `day` (default today), categorised. Cached 60 s in session."""
        d = (day or datetime.now()).strftime("%d-%m-%Y")
        rows = self.get(f"corporate-announcements?index=equities&from_date={d}&to_date={d}", ttl_open=60)
        items = parse_announcements(rows if isinstance(rows, list) else [])
        counts: dict[str, int] = {}
        for x in items:
            counts[x["category"]] = counts.get(x["category"], 0) + 1
        return {"date": d, "items": items, "counts": counts, "market_open": market_open()}

    def index_members(self, index: str, group: str) -> dict[str, Any]:
        """Live members of one NSE index (heatmap-symbols), for the MOV sector-board drill-down. Cached 60 s."""
        kind = {"SECTORAL INDICES": "Sectoral Indices", "THEMATIC INDICES": "Thematic Indices"}.get(group.upper(), "Broad Market Indices")
        q = parse_heatmap(self.get(f"heatmap-symbols?type={kind.replace(' ', '%20')}&indices={index.replace(' ', '%20').replace('&', '%26')}",
                                   ttl_open=60))
        rows = [{"symbol": k, **v} for k, v in q.items()]
        rows.sort(key=lambda r: -(r["change_pct"] if r["change_pct"] is not None else -999))
        return {"index": index, "group": kind, "members": rows, "capped": len(rows) >= 50 and kind == "Broad Market Indices"}

    def gift_nifty(self) -> dict[str, Any]:
        """GIFT NIFTY from NSE's marketStatus. It trades through the Indian evening and night, so the cache is 30 s in
        session and 60 s outside it (not the usual 10 min)."""
        return parse_gift_nifty(self.get("marketStatus", ttl_open=30, ttl_closed=60))

    def index_quote(self, name: str = "NIFTY 50") -> dict[str, Any]:
        """Live index from NSE allIndices (the header's NIFTY when ICICI is not streaming); 15 s cache in session, and
        also while the cached copy's own NSE timestamp is fresh outside the calendar (Muhurat, special sessions: the
        header chip and the app's menu bar call a print under 3 min old live); 5 min otherwise."""
        hit = self._cache.get("allIndices")
        printing = bool(hit) and isinstance(hit[1], dict) and fresh_nse_print(hit[1].get("timestamp"))
        return parse_index_quote(self.get("allIndices", ttl_open=15, ttl_closed=15 if printing else 300), name)

    def symbol_chart(self, symbol: str, minutes: int = 5) -> dict[str, Any]:
        """Latest session's intraday bars for an EQ symbol (fallback when ICICI is not connected); 30 s cache."""
        from urllib.parse import quote
        payload = self.get(f"chart-databyindex-dynamic?index={quote(symbol.upper() + 'EQN')}&type=symbol",
                           ttl_open=30, ttl_closed=600)
        return parse_symbol_chart(payload, minutes)

    def index_chart(self, name: str = "NIFTY 50", minutes: int = 1) -> dict[str, Any]:
        """Latest session's intraday path of an NSE index (per-second feed bucketed to `minutes`); 30 s cache."""
        from urllib.parse import quote
        payload = self.get(f"chart-databyindex-dynamic?index={quote(name.upper())}&type=index", ttl_open=30, ttl_closed=600)
        return parse_symbol_chart(payload, minutes)

    def symbol_announcements(self, symbol: str, days: int = 30, today: Optional[datetime] = None) -> dict[str, Any]:
        """One company's NSE announcements over the last `days` days, categorised, newest first; 5 min cache."""
        from datetime import timedelta
        from urllib.parse import quote
        end = today or datetime.now()
        start = end - timedelta(days=days)
        rows = self.get(f"corporate-announcements?index=equities&symbol={quote(symbol.upper())}"
                        f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}", ttl_open=300, ttl_closed=900)
        items = parse_announcements(rows if isinstance(rows, list) else (rows or {}).get("data", []))
        return {"symbol": symbol.upper(), "days": days, "items": items}


    def symbol_actions(self, symbol: str, years: int = 5, today: Optional[datetime] = None) -> dict[str, Any]:
        """One company's corporate actions over `years` years (dividends, bonus, splits, buybacks); 1 h cache."""
        from urllib.parse import quote
        end = today or datetime.now()
        from datetime import timedelta
        start = end - timedelta(days=365 * years)
        rows = self.get(f"corporates-corporateActions?index=equities&symbol={quote(symbol.upper())}"
                        f"&from_date={start:%d-%m-%Y}&to_date={end:%d-%m-%Y}", ttl_open=3600, ttl_closed=3600)
        return {"symbol": symbol.upper(), "years": years,
                **parse_actions(rows if isinstance(rows, list) else (rows or {}).get("data", []), today)}
