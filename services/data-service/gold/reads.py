"""The ``/db/gold/*`` read functions (PLAN §c.5). Every reply is a plain dict of JSON-safe values; row lists sit under
``rows`` (ui-api's ``_rows`` helper accepts that shape) and the single-value series under ``series`` with the as-of
(point-in-time) read applied: ``asof`` defaults to now, so a revision published later never leaks into an earlier view.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from gold import cot_metrics, db, pit, schema
from gold.catalog_seed import build_rows
from gold.db import iso_utc, utcnow
from gold.ingest_yahoo import SERIES_BY_SYMBOL, SYMBOL_BY_SERIES, is_partial

_CATALOG: dict[str, dict[str, Any]] | None = None

# wave 1c (C-DATA-3 / C-TRADER-8 / C-BEGINNER-6/14/15): catalog ids whose data lives in a typed table, not gold_series.
# ``series`` serves them as point-in-time points — report_date = the table's date, release_at = the row's release_at or
# first_seen_at (a bar has no publisher release instant: our fetch time is when it became known to us).
ETF_SERIES: dict[str, str] = {"GLD_TONNES": "GLD", "IAU_TONNES": "IAU"}            # series_id → fund (gold_etf_holdings.tonnes)
ASIA_SERIES: dict[str, tuple[str, str]] = {                                           # series_id → (exchange, measure)
    "SGE_AUTD_OI": ("SGE", "autd_oi"), "SGE_AUTD_DIRECTION": ("SGE", "autd_direction"), "SHFE_AU_FRONT_OI": ("SHFE", "front_oi"),
}
DIRECTION_CODE: dict[str, float] = {"long to short": 1.0, "short to long": -1.0}       # SGE deferred-fee direction → ±1 (0 = none)


def catalog_rows(store: Any) -> list[dict[str, Any]]:
    df = db.query_df(store, "SELECT * FROM gold_series_catalog ORDER BY series_id")
    rows = db.records(df)
    return rows if rows else [dict(r, verified_at=iso_utc(r["verified_at"])) for r in build_rows()]


def _catalog_map(store: Any) -> dict[str, dict[str, Any]]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = {str(r["series_id"]): r for r in catalog_rows(store)}
    return _CATALOG


def invalidate_catalog_cache() -> None:
    global _CATALOG
    _CATALOG = None


def catalog(store: Any) -> dict[str, Any]:
    rows = catalog_rows(store)
    return {"rows": rows, "count": len(rows), "as_of": iso_utc(utcnow())}


# ── series (PIT, resampled) ─────────────────────────────────────────────────────────────────────────

def _table_backed(store: Any, sid: str, *, start: date | None, end: date | None, asof: datetime) -> pd.DataFrame | None:
    """PIT points for a catalog id served from a typed table (None when ``sid`` is not one of them). Columns:
    report_date, value, release_at, quality, source — the same shape ``pit.asof_series`` returns."""
    cols = ["report_date", "value", "release_at", "quality", "source"]
    window = ""
    params: list[Any]
    if sid in SYMBOL_BY_SERIES:
        base = """SELECT trade_date AS report_date, close AS value, first_seen_at AS release_at, 'close' AS quality, source
                  FROM gold_daily_bars WHERE symbol = ? AND close IS NOT NULL AND first_seen_at <= ?"""
        params = [SYMBOL_BY_SERIES[sid], asof]
    elif sid in ETF_SERIES:
        base = """SELECT report_date, tonnes AS value, release_at, 'official' AS quality, source FROM gold_etf_holdings
                  WHERE fund = ? AND tonnes IS NOT NULL AND release_at <= ?"""
        params = [ETF_SERIES[sid], asof]
    elif sid in ASIA_SERIES:
        exchange, measure = ASIA_SERIES[sid]
        if measure == "front_oi":                       # the max-OI au contract per day (China's "main" month)
            base = """SELECT trade_date AS report_date, open_interest AS value, release_at, contract AS quality, source FROM gold_asia_daily
                      WHERE exchange = ? AND open_interest IS NOT NULL AND release_at <= ?"""
            window = " QUALIFY ROW_NUMBER() OVER (PARTITION BY trade_date ORDER BY open_interest DESC, contract) = 1"
        else:
            col = "open_interest" if measure == "autd_oi" else "direction"
            base = f"""SELECT trade_date AS report_date, {col} AS value, release_at, contract AS quality, source FROM gold_asia_daily
                       WHERE exchange = ? AND contract = 'Au(T+D)' AND {col} IS NOT NULL AND release_at <= ?"""
        params = [exchange, asof]
    else:
        return None
    day_col = "trade_date" if sid in SYMBOL_BY_SERIES or sid in ASIA_SERIES else "report_date"
    if start:
        base += f" AND {day_col} >= ?"
        params.append(start)
    if end:
        base += f" AND {day_col} <= ?"
        params.append(end)
    df = db.query_df(store, base + window + " ORDER BY report_date", params)
    if df.empty:
        return pd.DataFrame(columns=cols)
    if sid == "SGE_AUTD_DIRECTION":
        df["value"] = df["value"].map(lambda v: DIRECTION_CODE.get(str(v or "").strip().lower(), 0.0))
    elif sid in SYMBOL_BY_SERIES:                   # a bar fetched before its session close is 'partial', not a 'close'
        sym = SYMBOL_BY_SERIES[sid]
        df["quality"] = ["partial" if is_partial(sym, d, t) else "close" for d, t in zip(df["report_date"], df["release_at"])]
    return df.drop_duplicates("report_date", keep="last")[cols]


def series(store: Any, ids: list[str], *, start: date | None = None, end: date | None = None, asof: datetime | None = None,
           freq: str | None = None) -> dict[str, Any]:
    asof_dt = asof or utcnow()
    cat = _catalog_map(store)
    df = pit.asof_series(store, ids, start=start, end=end, asof=asof_dt)
    out = []
    for sid in ids:
        sub = df[df["series_id"] == sid] if not df.empty else pd.DataFrame()
        if sub.empty:                                   # not in gold_series: a table-backed id (bars, ETF tonnes, Asia OI) or unknown
            tb = _table_backed(store, sid, start=start, end=end, asof=asof_dt)
            sub = tb if tb is not None else sub
        row = cat.get(sid, {})
        how = str(row.get("resample") or "last")
        pts = sub[["report_date", "value", "release_at"]].reset_index(drop=True) if not sub.empty else pd.DataFrame(
            columns=["report_date", "value", "release_at"])
        if freq in ("W", "M") and not pts.empty:
            pts = pit.resample(pts, freq, how)
        out.append({"series_id": sid, "name": row.get("name"), "unit": row.get("unit"), "freq_native": row.get("freq"),
                    "quality": (sub["quality"].iloc[-1] if not sub.empty else None), "resample": how,
                    "points": [{"report_date": _day(r.report_date), "value": _f(r.value), "release_at": _iso(r.release_at)}
                               for r in pts.itertuples(index=False)],
                    "catalog": {k: row.get(k) for k in ("publisher", "verdict", "badge", "lag_note", "terms", "max_age_days", "source_entry")}})
    return {"as_of": iso_utc(utcnow()), "asof_applied": iso_utc(asof_dt), "freq": freq or "D", "series": out}


# ── typed tables ────────────────────────────────────────────────────────────────────────────────────

def cot(store: Any, *, weeks: int = 52, report: str = "disagg", fut_or_combined: str = "F", contract: str = "088691") -> dict[str, Any]:
    panel = cot_metrics.load_panel(store, contract, report, fut_or_combined)
    rows = db.records(panel.tail(max(1, weeks))) if not panel.empty else []
    summary = cot_metrics.summary(store, weeks=weeks, contract=contract) if report == "disagg" and fut_or_combined == "F" else {}
    return {"as_of": iso_utc(utcnow()), "report": report, "fut_or_combined": fut_or_combined, "contract_code": contract,
            "rows": rows, **summary}


def cme_voi(store: Any, *, start: date | None = None, products: list[str] | None = None) -> dict[str, Any]:
    start = start or (utcnow().date() - timedelta(days=90))
    sql = "SELECT * FROM gold_cme_daily_voi WHERE trade_date >= ?"
    params: list[Any] = [start]
    if products:
        sql += f" AND product_code IN ({', '.join('?' for _ in products)})"
        params += products
    return {"rows": db.records(db.query_df(store, sql + " ORDER BY trade_date, product_code, fut_or_opt", params)), "from": start.isoformat()}


def cme_efrp(store: Any, *, start: date | None = None) -> dict[str, Any]:
    start = start or (utcnow().date() - timedelta(days=60))
    df = db.query_df(store, "SELECT * FROM gold_cme_efrp WHERE process_date >= ? ORDER BY process_date, row_no", [start])
    daily = db.query_df(store, """
        SELECT process_date, SUM(round_turns) AS round_turns, COUNT(*) AS prints FROM gold_cme_efrp
        WHERE product = 'GOLD' AND process_date >= ? GROUP BY process_date ORDER BY process_date""", [start])
    return {"rows": db.records(df), "daily_gold": db.records(daily), "from": start.isoformat()}


def _full_closures(exchange: str) -> set[date]:
    """Exchange days with no session at all (MCX: shared/mcx_specs full closures; a morning/evening closure still trades)."""
    if exchange != "MCX":
        return set()
    try:
        from shared import mcx_specs as specs

        return {d for d, (_, closure) in specs.MCX_HOLIDAYS_2026.items() if closure == "full"}
    except Exception:  # noqa: BLE001 — the specs module is optional for a read
        return set()


def sessions_between(prev: date | None, cur: date, *, closures: set[date] | None = None) -> int | None:
    """Trading sessions in (prev, cur]: weekdays minus full closures. None without a previous row. A stored OI delta
    whose previous row is more than one session back spans the gap (wave 1c, C-TRADER-18: '29 Oct → 3 Nov labelled as one
    day'); the UI prints 'over N sessions' when this is > 1."""
    if prev is None or cur <= prev:
        return None
    closures = closures or set()
    n, d = 0, prev
    while d < cur:
        d += timedelta(days=1)
        if d.weekday() < 5 and d not in closures:
            n += 1
    return n


def _with_sessions_spanned(store: Any, rows: pd.DataFrame, exchange: str) -> list[dict[str, Any]]:
    """``db.records`` plus ``oi_change_from`` (the previous stored trade_date of the same contract and source) and
    ``sessions_spanned`` (sessions that delta covers; 1 = one day, >1 = a gap in the master)."""
    recs = db.records(rows)
    if not recs:
        return recs
    closures = _full_closures(exchange)
    keys = {(r["symbol"], str(r["expiry"]), r["source"]) for r in recs}
    days = [d for d in (db.to_date(r["trade_date"]) for r in recs) if d is not None]
    if not days:
        return recs
    prev = db.query_df(store, """
        SELECT symbol, expiry, source, trade_date,
               LAG(trade_date) OVER (PARTITION BY exchange, symbol, expiry, source ORDER BY trade_date) AS prev_date
        FROM gold_curve WHERE exchange = ? AND trade_date <= ?""", [exchange, max(days)])
    lookup: dict[tuple[str, str, str, date], date | None] = {}
    for r in prev.itertuples(index=False):
        k = (str(r.symbol), str(db.to_date(r.expiry)), str(r.source))
        td = db.to_date(r.trade_date)
        if k in keys and td is not None:
            lookup[(k[0], k[1], k[2], td)] = db.to_date(r.prev_date)
    for r in recs:
        cur = db.to_date(r["trade_date"])
        p = lookup.get((r["symbol"], str(r["expiry"]), r["source"], cur)) if cur else None
        r["oi_change_from"] = p.isoformat() if p else None
        r["sessions_spanned"] = sessions_between(p, cur, closures=closures) if (cur and r.get("oi_change") is not None) else None
    return recs


def curve(store: Any, *, exchange: str = "COMEX", day: date | None = None) -> dict[str, Any]:
    """The latest curve on/before ``day`` per source (proxy and official coexist), plus the curve one week earlier.
    Every row carries ``oi_change_from`` / ``sessions_spanned`` (see ``_with_sessions_spanned``)."""
    day = day or utcnow().date()
    latest = db.scalar(store, "SELECT MAX(trade_date) FROM gold_curve WHERE exchange = ? AND trade_date <= ?", [exchange, day])
    latest_d = db.to_date(latest)
    if latest_d is None:
        return {"exchange": exchange, "date": None, "rows": [], "ghost_1w": []}
    rows = db.query_df(store, "SELECT * FROM gold_curve WHERE exchange = ? AND trade_date = ? ORDER BY symbol, expiry, source", [exchange, latest_d])
    ghost_day = db.scalar(store, "SELECT MAX(trade_date) FROM gold_curve WHERE exchange = ? AND trade_date <= ?",
                          [exchange, latest_d - timedelta(days=7)])
    ghost_d = db.to_date(ghost_day)
    ghost = db.query_df(store, "SELECT * FROM gold_curve WHERE exchange = ? AND trade_date = ? ORDER BY symbol, expiry, source",
                        [exchange, ghost_d]) if ghost_d is not None else pd.DataFrame()
    return {"exchange": exchange, "date": latest_d.isoformat(), "rows": _with_sessions_spanned(store, rows, exchange),
            "ghost_1w": _with_sessions_spanned(store, ghost, exchange), "ghost_date": ghost_d.isoformat() if ghost_d else None}


def curve_history(store: Any, *, exchange: str = "MCX", symbol: str = "GOLD", days: int = 120) -> dict[str, Any]:
    df = db.query_df(store, """
        SELECT trade_date, session_date, symbol, expiry, settle, open_interest, oi_change, source, quality FROM gold_curve
        WHERE exchange = ? AND symbol = ? AND trade_date >= ? ORDER BY trade_date, expiry""",
                     [exchange, symbol, utcnow().date() - timedelta(days=days)])
    return {"exchange": exchange, "symbol": symbol, "rows": _with_sessions_spanned(store, df, exchange)}


def margins(store: Any, *, day: date | None = None, exchange: str | None = None) -> dict[str, Any]:
    day = day or utcnow().date()
    sql = "SELECT * FROM gold_margins WHERE trade_date = (SELECT MAX(trade_date) FROM gold_margins WHERE trade_date <= ?"
    params: list[Any] = [day]
    if exchange:
        sql += " AND exchange = ?"
        params.append(exchange)
    sql += ")"
    if exchange:
        sql += " AND exchange = ?"
        params.append(exchange)
    return {"rows": db.records(db.query_df(store, sql + " ORDER BY exchange, symbol, expiry", params))}


def cme_prf(store: Any, *, symbol: str = "GC") -> dict[str, Any]:
    """gold_cme_prf rows for one root symbol on its latest ``biz_date`` (the COMEX contract spec card; the API_CONTRACT §4
    optional read behind ``/api/gold/contracts?exchange=COMEX`` → ``comex_spec``)."""
    df = db.query_df(store, """SELECT * FROM gold_cme_prf WHERE symbol = ?
                               AND biz_date = (SELECT MAX(biz_date) FROM gold_cme_prf WHERE symbol = ?) ORDER BY mat_date""",
                     [symbol, symbol])
    return {"symbol": symbol, "biz_date": _day(df["biz_date"].iloc[0]) if not df.empty else None, "rows": db.records(df)}


def cme_calendar(store: Any, *, symbol: str = "GC", as_of: date | None = None) -> dict[str, Any]:
    """gold_cme_calendar rows for one root symbol on the latest ``as_of`` (≤ the given one): FND / LTD / intent dates per
    delivery month, the source of the COMEX_FND / COMEX_LTD events (wave 1c, C-TRADER-13 / C-DATA-8)."""
    params: list[Any] = [symbol]
    sql = "SELECT MAX(as_of) FROM gold_cme_calendar WHERE symbol = ?"
    if as_of:
        sql += " AND as_of <= ?"
        params.append(as_of)
    day = db.to_date(db.scalar(store, sql, params))
    if day is None:
        return {"symbol": symbol, "as_of": None, "rows": []}
    df = db.query_df(store, "SELECT * FROM gold_cme_calendar WHERE symbol = ? AND as_of = ? ORDER BY mmy", [symbol, day])
    return {"symbol": symbol, "as_of": day.isoformat(), "rows": db.records(df)}


def bars(store: Any, *, symbol: str, interval: str = "1d", start: date | datetime | None = None, end: date | datetime | None = None,
         limit: int = 20000) -> dict[str, Any]:
    """``symbol`` is a Yahoo symbol (``GC=F``, ``GCZ26.CMX``) or a catalog id (``COMEX_GC_FRONT``); ``interval`` 1d | 1m | 5m.
    Intraday ``ts`` is serialised with an explicit ``+00:00`` (the store is UTC-naive; wave 1c, C-TRADER-1 / C-DATA-1)."""
    sym = SYMBOL_BY_SERIES.get(symbol, symbol)
    params: list[Any]
    if interval == "1d":
        start_d = db.to_date(start) or (utcnow().date() - timedelta(days=400))
        sql = ("SELECT trade_date, open, high, low, close, adj_close, volume, source, first_seen_at FROM gold_daily_bars "
               "WHERE symbol = ? AND trade_date >= ?")
        params = [sym, start_d]
        if end:
            sql += " AND trade_date <= ?"
            params.append(db.to_date(end))
        df = db.query_df(store, sql + " ORDER BY trade_date", params).tail(limit)
        if not df.empty:        # a bar fetched before its session close is the in-progress session, not a close (C-DATA-21)
            df["partial"] = [is_partial(sym, d, t) for d, t in zip(df["trade_date"], df["first_seen_at"])]
    else:
        start_dt = pd.Timestamp(start).to_pydatetime() if start else (utcnow() - timedelta(days=7))
        sql = "SELECT ts, open, high, low, close, volume, source FROM gold_bars_intraday WHERE symbol = ? AND interval = ? AND ts >= ?"
        params = [sym, interval, start_dt]
        if end:
            sql += " AND ts <= ?"
            params.append(pd.Timestamp(end).to_pydatetime())
        df = db.query_df(store, sql + " ORDER BY ts", params).tail(limit)
    return {"symbol": sym, "series_id": SERIES_BY_SYMBOL.get(sym), "interval": interval, "rows": db.records(df), "count": len(df)}


def asia(store: Any, *, start: date | None = None, exchange: str | None = None) -> dict[str, Any]:
    start = start or (utcnow().date() - timedelta(days=90))
    sql = "SELECT * FROM gold_asia_daily WHERE trade_date >= ?"
    params: list[Any] = [start]
    if exchange:
        sql += " AND exchange = ?"
        params.append(exchange)
    return {"rows": db.records(db.query_df(store, sql + " ORDER BY trade_date, exchange, contract", params)), "from": start.isoformat()}


def etf(store: Any, *, start: date | None = None, fund: str | None = None) -> dict[str, Any]:
    start = start or (utcnow().date() - timedelta(days=90))
    sql = "SELECT * FROM gold_etf_holdings WHERE report_date >= ?"
    params: list[Any] = [start]
    if fund:
        sql += " AND fund = ?"
        params.append(fund.upper())
    return {"rows": db.records(db.query_df(store, sql + " ORDER BY report_date, fund", params)), "from": start.isoformat()}


def fed_path(store: Any, *, asof: date | None = None) -> dict[str, Any]:
    asof = asof or utcnow().date()
    day = db.to_date(db.scalar(store, "SELECT MAX(as_of) FROM gold_fed_path WHERE as_of <= ?", [asof]))
    if day is None:
        return {"as_of": None, "rows": []}
    df = db.query_df(store, "SELECT * FROM gold_fed_path WHERE as_of = ? ORDER BY meeting", [day])
    return {"as_of": day.isoformat(), "rows": db.records(df)}


def events(store: Any, *, start: date | None = None, end: date | None = None, kinds: list[str] | None = None) -> dict[str, Any]:
    start = start or utcnow().date()
    end = end or (start + timedelta(days=30))
    sql = "SELECT * FROM gold_events WHERE event_date BETWEEN ? AND ?"
    params: list[Any] = [start, end]
    if kinds:
        sql += f" AND kind IN ({', '.join('?' for _ in kinds)})"
        params += kinds
    return {"rows": db.records(db.query_df(store, sql + " ORDER BY event_date, time_ist NULLS LAST, kind", params)),
            "from": start.isoformat(), "to": end.isoformat()}


def log(store: Any, *, days: int = 60) -> dict[str, Any]:
    df = db.query_df(store, "SELECT * FROM gold_preopen_log WHERE day >= ? ORDER BY day", [utcnow().date() - timedelta(days=days)])
    rows = db.records(df)
    scored = [r for r in rows if r.get("error") is not None]
    errs = sorted(abs(float(r["error"])) for r in scored)
    stats = {"days": len(scored), "median_abs_error": errs[len(errs) // 2] if errs else None,
             "mean_abs_error": (sum(errs) / len(errs)) if errs else None,
             "p90": errs[min(len(errs) - 1, int(0.9 * len(errs)))] if errs else None,
             "bias": (sum(float(r["error"]) for r in scored) / len(scored)) if scored else None,
             "naive_mean_abs_error": (sum(abs(float(r["naive_error"])) for r in scored if r.get("naive_error") is not None)
                                      / max(1, sum(1 for r in scored if r.get("naive_error") is not None))) if scored else None,
             "stale_days": sum(1 for r in rows if r.get("stale_baseline"))}
    return {"rows": rows, "accuracy": stats}


def brief(store: Any, *, day: date | None = None) -> dict[str, Any]:
    if day is None:
        v = db.scalar(store, "SELECT MAX(report_date) FROM gold_brief_docs")
        day = db.to_date(v) if v is not None else None
    if day is None:
        return {"available": False, "row": None}
    df = db.query_df(store, "SELECT * FROM gold_brief_docs WHERE report_date = ?", [day])
    if df.empty:
        return {"available": False, "report_date": day.isoformat(), "row": None}
    row = db.records(df)[0]
    doc = json.loads(row.pop("doc")) if isinstance(row.get("doc"), str) else row.pop("doc", None)
    return {"available": True, "report_date": day.isoformat(), "row": row, "doc": doc,
            "data_quality": (doc or {}).get("data_quality"), "synthesis": (doc or {}).get("synthesis")}


def health_daily(store: Any, *, start: date | None = None) -> dict[str, Any]:
    start = start or (utcnow().date() - timedelta(days=90))
    df = db.query_df(store, "SELECT * FROM gold_health_daily WHERE day >= ? ORDER BY day", [start])
    rows = db.records(df)
    for r in rows:
        if isinstance(r.get("gauges"), str):
            try:
                r["gauges"] = json.loads(r["gauges"])
            except ValueError:
                pass
    return {"rows": rows}


def meta(store: Any) -> dict[str, Any]:
    """Freshness per gold table plus the catalog's staleness verdict per series (older than ``max_age_days``)."""
    tables = schema.positions_meta(store)
    cat = _catalog_map(store)
    latest = db.query_df(store, "SELECT series_id, MAX(report_date) AS last FROM gold_series GROUP BY series_id")
    today = utcnow().date()
    stale, fresh = [], 0
    for r in latest.itertuples(index=False):
        row = cat.get(str(r.series_id))
        last_d = db.to_date(r.last)
        if not row or last_d is None:
            continue
        age = (today - last_d).days
        if age > int(row.get("max_age_days") or 4):
            stale.append({"series_id": r.series_id, "last": str(r.last), "age_days": age, "max_age_days": row.get("max_age_days")})
        else:
            fresh += 1
    return {"tables": tables, "series": {"fresh": fresh, "stale": stale, "catalogued": len(cat), "stored": len(latest)}}


def _iso(v: Any) -> str | None:
    """Datetimes leave reads.py with an explicit UTC offset, dates as YYYY-MM-DD (``db.iso_utc``)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return iso_utc(v)


def _day(v: Any) -> str | None:
    d = db.to_date(v)
    return d.isoformat() if d else None


def _f(v: Any) -> float | None:
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None
