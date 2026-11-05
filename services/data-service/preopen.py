"""
PRE page: NSE's pre-open call auction (09:00–09:08 IST). For each stock NSE publishes the indicative
equilibrium price (IEP), the gap vs the previous close, and the total buy and sell quantity in the order book.
The imbalance is the earliest read on the open. NSE keeps the last session's pre-open until the next one starts.

The final snapshot of each session (after 09:08) is archived to data/nse_archive/preopen/<date>_<key>.json, so
the imbalance can be researched later; the EOD bhavcopy does not have it.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import httpx

PAGE = "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market"
API = "https://www.nseindia.com/api/market-data-pre-open"
KEYS = ("NIFTY", "BANKNIFTY", "FO", "ALL")


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def parse(payload: dict) -> dict[str, Any]:
    """NSE pre-open JSON → one flat row per stock plus the session header."""
    rows: list[dict[str, Any]] = []
    for item in payload.get("data") or []:
        m = item.get("metadata") or {}
        p = (item.get("detail") or {}).get("preOpenMarket") or {}
        buy, sell = _f(p.get("totalBuyQuantity")), _f(p.get("totalSellQuantity"))
        iep = _f(m.get("iep")) or _f(p.get("IEP")) or _f(m.get("lastPrice"))
        prev = _f(m.get("previousClose")) or _f(p.get("prevClose"))
        yh, yl = _f(m.get("yearHigh")), _f(m.get("yearLow"))
        rows.append({
            "symbol": m.get("symbol"), "series": m.get("series"), "iep": iep, "prev_close": prev,
            "change": _f(m.get("change")), "change_pct": _f(m.get("pChange")),
            "final_qty": _f(m.get("finalQuantity")), "value": _f(m.get("totalTurnover")),
            "buy_qty": buy, "sell_qty": sell,
            # +1 = only buyers left in the book, −1 = only sellers
            "imbalance": (buy - sell) / (buy + sell) if buy is not None and sell is not None and buy + sell > 0 else None,
            "ato_buy": _f(p.get("atoBuyQty")), "ato_sell": _f(p.get("atoSellQty")),
            "year_high": yh, "year_low": yl,
            "vs_year_high_pct": (iep / yh - 1) * 100 if iep and yh else None,
            "market_cap": _f(m.get("marketCap")), "purpose": m.get("purpose"),
        })
    rows = [r for r in rows if r["symbol"]]
    return {"timestamp": payload.get("timestamp"), "advances": payload.get("advances"),
            "declines": payload.get("declines"), "unchanged": payload.get("unchanged"),
            "total_value": _f(payload.get("totalTradedValue")), "rows": rows}


def session_date(ts: Optional[str]) -> Optional[str]:
    """'09-Oct-2026 09:09:49' → '2026-10-09'."""
    try:
        return datetime.strptime(ts or "", "%d-%b-%Y %H:%M:%S").date().isoformat()
    except ValueError:
        return None


def is_final(ts: Optional[str]) -> bool:
    """The auction closes at 09:08; a snapshot stamped later is that session's final book."""
    try:
        t = datetime.strptime(ts or "", "%d-%b-%Y %H:%M:%S")
    except ValueError:
        return False
    return (t.hour, t.minute) >= (9, 8)


class PreOpenFeed:
    """NSE session (cookie warm-up), a short TTL cache per key, and the daily archive. Thread-safe."""

    def __init__(self, archive: Path, headers: dict[str, str], ttl_live_s: float = 20, ttl_idle_s: float = 600) -> None:
        self.archive = archive
        self.headers = {**headers, "Accept": "application/json,*/*", "Referer": PAGE}
        self.ttl_live, self.ttl_idle = ttl_live_s, ttl_idle_s
        self._client: Optional[httpx.Client] = None
        self._warm = 0.0
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _session(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(headers=self.headers, timeout=20, follow_redirects=True)
        if time.time() - self._warm > 600:          # NSE cookies expire; re-visit the page every 10 min
            self._client.get(PAGE)
            self._warm = time.time()
        return self._client

    @staticmethod
    def _live_window(now: datetime) -> bool:
        return (9, 0) <= (now.hour, now.minute) <= (9, 16) and now.weekday() < 5

    def get(self, key: str, now: Optional[datetime] = None) -> dict[str, Any]:
        now = now or datetime.now()
        ttl = self.ttl_live if self._live_window(now) else self.ttl_idle
        with self._lock:
            hit = self._cache.get(key)
            if hit and time.time() - hit[0] < ttl:
                return hit[1]
            client = self._session()
            r = client.get(API, params={"key": key})
            if r.status_code in (401, 403):
                self._warm = 0.0
                r = self._session().get(API, params={"key": key})
            r.raise_for_status()
            raw = r.json()
            out = parse(raw)
            out["key"], out["fetched_at"] = key, datetime.now().isoformat(timespec="seconds")
            self._cache[key] = (time.time(), out)
        self._archive(key, out["timestamp"], raw)
        return out

    def _archive(self, key: str, ts: Optional[str], raw: dict) -> None:
        day = session_date(ts)
        if not day or not is_final(ts) or not raw.get("data"):
            return
        path = self.archive / f"{day}_{key}.json"
        if path.exists():
            return
        try:
            self.archive.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(raw))
            tmp.replace(path)
        except OSError:
            pass                                     # the archive is a bonus; never fail the page for it
