"""The ``/db/gold/*`` read functions (PLAN §c.5). Every reply is a plain dict of JSON-safe values; row lists sit under
``rows`` (ui-api's ``_rows`` helper accepts that shape) and the single-value series under ``series`` with the as-of
(point-in-time) read applied: ``asof`` defaults to now, so a revision published later never leaks into an earlier view.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from gold import cot_metrics, db, ingest_india, mcx_close, pit, schema
from gold import mcx_daily as mcx_daily_mod
from gold.catalog_seed import build_rows
from gold.db import iso_utc, utcnow
from gold.ingest_india import band_midpoint, band_session, previous_mcx_session
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
# wave 1d (gold_open_issues: MACRO Brent 9 days stale; real yield / 2-y two sessions behind): the same quantity from a
# fresher stored source. ``series`` reports the twin's last point as ``fresher_twin`` when it is newer; it never
# substitutes one for the other (a reader picks, and prints the twin's own id, source and date).
TWINS: dict[str, str] = {
    "FRED_DCOILBRENTEU": "BRENT_FRONT", "BRENT_FRONT": "FRED_DCOILBRENTEU",
    "FRED_DFII10": "UST_REAL_10Y", "UST_REAL_10Y": "FRED_DFII10",
    "FRED_DGS2": "UST_NOM_2Y", "UST_NOM_2Y": "FRED_DGS2",
    "FRED_DGS10": "UST_NOM_10Y", "UST_NOM_10Y": "FRED_DGS10",
    "FRED_GVZCLS": "GVZ_CLOSE", "GVZ_CLOSE": "FRED_GVZCLS",
    "FRED_VIXCLS": "VIX_CLOSE", "VIX_CLOSE": "FRED_VIXCLS",
    "USDINR_FBIL": "USDINR_CLOSE", "USDINR_CLOSE": "USDINR_FBIL",
}
# How a twin relates to its partner (round 2, check: BZ=F is NOT the same quantity as FRED's dated Brent — 96.1 vs 107.03 on
# 3 Nov). ``same_level`` False = switching changes the level, so a reader must say which it shows, never splice the two.
TWIN_RELATION: dict[frozenset[str], tuple[str, bool]] = {
    frozenset({"FRED_DCOILBRENTEU", "BRENT_FRONT"}): ("front-month future (ICE/NYMEX BZ, last trade) vs dated Brent spot (EIA via FRED): "
                                                      "different instruments, levels differ by the spot–future spread", False),
    frozenset({"FRED_DFII10", "UST_REAL_10Y"}): ("same 10-y TIPS real yield: FRED H.15 constant maturity vs the Treasury par real "
                                                 "curve CSV (a few bp apart)", True),
    frozenset({"FRED_DGS2", "UST_NOM_2Y"}): ("same 2-y Treasury yield: FRED H.15 vs the Treasury par curve CSV", True),
    frozenset({"FRED_DGS10", "UST_NOM_10Y"}): ("same 10-y Treasury yield: FRED H.15 vs the Treasury par curve CSV", True),
    frozenset({"FRED_GVZCLS", "GVZ_CLOSE"}): ("same Cboe GVZ close: FRED vs the Yahoo ^GVZ daily bar", True),
    frozenset({"FRED_VIXCLS", "VIX_CLOSE"}): ("same Cboe VIX close: FRED vs the Yahoo ^VIX daily bar", True),
    frozenset({"USDINR_FBIL", "USDINR_CLOSE"}): ("USD/INR: the FBIL reference rate (≈13:30 IST fix) vs the market close — "
                                                 "different clocks", False),
}
# Derived series whose earlier pairing is superseded (round 2, check: old-pairing MCX basis points stayed the latest for
# sessions the wave-1d derive had not re-written yet, e.g. the −2.09 % artefact on 4 Nov). Once a point with a CURRENT
# quality is visible at the read's as-of instant, points whose latest vintage carries a RETIRED quality are dropped from
# the read (they stay stored for audit; a replay before the wave-1d derive ran still sees the old series).
SUPERSEDED_QUALITY: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "MCX_BASIS_PCT": (frozenset({"derived"}), frozenset({"derived_vwap30", "derived_band"})),
    "MCX_BASIS_CARRY_ADJ_PCT": (frozenset({"derived"}), frozenset({"derived_vwap30", "derived_band"})),
}


def twin_relation(a: str, b: str) -> tuple[str | None, bool | None]:
    rel = TWIN_RELATION.get(frozenset({a, b}))
    return (rel[0], rel[1]) if rel else (None, None)


def drop_superseded(sid: str, sub: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """(rows, dropped): ``sub`` without the retired-quality points of ``sid`` once a current-quality point is visible."""
    rule = SUPERSEDED_QUALITY.get(sid)
    if rule is None or sub.empty or "quality" not in sub.columns:
        return sub, 0
    retired, current = rule
    q = sub["quality"].astype(str)
    if not q.isin(current).any():
        return sub, 0
    keep = ~q.isin(retired)
    return sub[keep], int((~keep).sum())


def catalog_rows(store: Any) -> list[dict[str, Any]]:
    """The stored catalog, plus any code row the table does not have yet (wave 1d, C-DATA-17: a row shipped in code
    is live the moment the code is, not after the next ``catalog`` job). Stored rows win on a shared id."""
    df = db.query_df(store, "SELECT * FROM gold_series_catalog ORDER BY series_id")
    rows = db.records(df)
    have = {str(r["series_id"]) for r in rows}
    missing = [dict(r, verified_at=iso_utc(r["verified_at"])) for r in build_rows() if r["series_id"] not in have]
    return sorted(rows + missing, key=lambda r: str(r["series_id"])) if missing else rows


def _catalog_map(store: Any) -> dict[str, dict[str, Any]]:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = {str(r["series_id"]): r for r in catalog_rows(store)}
    return _CATALOG


def catalog_row(cat: dict[str, dict[str, Any]], sid: str) -> dict[str, Any]:
    """The catalog row of ``sid``; a per-contract MCX VWAP30 id resolves to its family template row
    ('MCX_GOLD_202612_VWAP30' → 'MCX_GOLD_VWAP30')."""
    row = cat.get(sid)
    if row is None:
        key = mcx_close.catalog_key(sid)
        row = cat.get(key) if key else None
    return row or {}


def invalidate_catalog_cache() -> None:
    global _CATALOG
    _CATALOG = None


def catalog(store: Any) -> dict[str, Any]:
    rows = catalog_rows(store)
    return {"rows": rows, "count": len(rows), "as_of": iso_utc(utcnow())}


# ── series (PIT, resampled) ─────────────────────────────────────────────────────────────────────────

def ist_day(ts: Any) -> date:
    """The IST calendar day of an instant (the store is UTC-naive; an aware value is converted, not re-stamped). The
    day a terminal reader is in — what "today" means for a session date, an age in days and a future-row guard."""
    t = pd.Timestamp(ts)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    return t.tz_convert("Asia/Kolkata").date()


def _table_backed(store: Any, sid: str, *, start: date | None, end: date | None, asof: datetime) -> pd.DataFrame | None:
    """PIT points for a catalog id served from a typed table (None when ``sid`` is not one of them). Columns:
    report_date, value, release_at, quality, source — the same shape ``pit.asof_series`` returns. No row dated after the
    as-of's IST day is ever served (wave 2, C-DATA-02: a weekend quote stored as next Monday read back as age −1)."""
    cols = ["report_date", "value", "release_at", "quality", "source"]
    window = ""
    params: list[Any]
    if sid in SYMBOL_BY_SERIES:
        base = """SELECT trade_date AS report_date, close AS value, adj_close AS vendor_close, first_seen_at AS release_at,
                         'close' AS quality, source
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
    today = ist_day(asof)                           # never a session dated after the reader's own IST day
    keep = [(db.to_date(d) or today) <= today for d in df["report_date"]]
    n_future = len(keep) - sum(keep)
    if n_future:
        df = df[keep]
        if df.empty:
            out = pd.DataFrame(columns=cols)
            out.attrs["future_dropped"] = n_future
            return out
    if sid == "SGE_AUTD_DIRECTION":
        df["value"] = df["value"].map(lambda v: DIRECTION_CODE.get(str(v or "").strip().lower(), 0.0))
    elif sid in SYMBOL_BY_SERIES:                   # a bar fetched before its session close is 'partial', not a 'close'
        sym = SYMBOL_BY_SERIES[sid]
        df["quality"] = [_bar_quality(sym, d, t, c, v) for d, t, c, v in
                         zip(df["report_date"], df["release_at"], df["value"], df["vendor_close"], strict=True)]
    out = df.drop_duplicates("report_date", keep="last")[cols]
    out.attrs["future_dropped"] = n_future          # read by ``series`` so the guard can never fire silently
    return out


def _bar_quality(sym: str, day: Any, seen: Any, close: Any, vendor_close: Any) -> str:
    """The clock a daily bar's close was read on: ``partial`` (fetched before the session closed — an in-progress price,
    never a settlement), ``open_snapshot`` (an FX row still carrying Yahoo's own completed-bar close, which is the
    00:00 London OPENING snapshot ≈ the PREVIOUS session's close — written before the wave-2 fix, see
    ``ingest_yahoo.fx_session_close``) or ``close``.

    On an ``=X`` row the label is INFERRED from ``close`` vs the vendor's ``adj_close``, not recorded: a close equal to
    the vendor's is read as the un-rebuilt opening snapshot, which also catches a genuinely FLAT session and a pair
    whose rebuilt close rounds to the same 4 dp. The label therefore UNDER-claims (it can call a rebuilt close an
    opening snapshot) and never over-claims — an FX row whose vendor number is missing is ``open_snapshot`` too, since
    nothing recorded which clock it came from. Recording it needs a ``close_source`` column on ``gold_daily_bars``
    (``gold/schema.py``, raised as a patch request); until then this is the honest reading of what is stored."""
    if is_partial(sym, day, seen):
        return "partial"
    if sym.endswith("=X") and not (close is not None and vendor_close is not None and float(close) != float(vendor_close)):
        return "open_snapshot"
    return "close"


def series(store: Any, ids: list[str], *, start: date | None = None, end: date | None = None, asof: datetime | None = None,
           freq: str | None = None) -> dict[str, Any]:
    asof_dt = asof or utcnow()
    today_ist = ist_day(asof_dt)
    cat = _catalog_map(store)
    df = pit.asof_series(store, ids, start=start, end=end, asof=asof_dt)
    out = []
    for sid in ids:
        sub = df[df["series_id"] == sid] if not df.empty else pd.DataFrame()
        # wave 2 (C-DATA-02): a DAILY observation dated after the reader's own IST day describes a session that has not
        # happened — it is dropped and COUNTED, never served (a derived series inherits the bad date from its input)
        future = 0
        if sub.empty:                                   # not in gold_series: a table-backed id (bars, ETF tonnes, Asia OI) or unknown
            tb = _table_backed(store, sid, start=start, end=end, asof=asof_dt)
            if tb is not None:
                future = int(tb.attrs.get("future_dropped", 0))
                sub = tb
        sub, superseded = drop_superseded(sid, sub)
        row = catalog_row(cat, sid)
        if not sub.empty and (sid in SYMBOL_BY_SERIES or str(row.get("freq") or "D") == "D"):
            keep = [(db.to_date(d) or today_ist) <= today_ist for d in sub["report_date"]]
            future += len(keep) - sum(keep)
            if not all(keep):
                sub = sub[keep]
        how = str(row.get("resample") or "last")
        pts = sub[["report_date", "value", "release_at"]].reset_index(drop=True) if not sub.empty else pd.DataFrame(
            columns=["report_date", "value", "release_at"])
        partial_days: set[str] = set()
        if not sub.empty and sid in SYMBOL_BY_SERIES:          # wave 1d: the store's own partial flag, per point
            partial_days = {str(_day(d)) for d, q in zip(sub["report_date"], sub["quality"]) if q == "partial"}
        if freq in ("W", "M") and not pts.empty:
            pts = pit.resample(pts, freq, how)
        points = []
        for r in pts.itertuples(index=False):
            p = {"report_date": _day(r.report_date), "value": _f(r.value), "release_at": _iso(r.release_at)}
            if freq in (None, "D") and p["report_date"] in partial_days:
                p["partial"] = True
            points.append(p)
        last_day = db.to_date(points[-1]["report_date"]) if points else None
        max_age = row.get("max_age_days")
        # the age a reader lives in: IST days since the last observation, never negative (a negative age meant a
        # future-dated row, which is now dropped above and reported as future_points_dropped)
        age = max(0, (today_ist - last_day).days) if last_day else None
        out.append({"series_id": sid, "name": row.get("name"), "unit": row.get("unit"), "freq_native": row.get("freq"),
                    "quality": (sub["quality"].iloc[-1] if not sub.empty else None), "resample": how,
                    "points": points,
                    "last_point_partial": bool(points and points[-1].get("partial")),
                    "age_days": age, "stale": (age is not None and max_age is not None and age > int(max_age)),
                    "fresher_twin": _fresher_twin(store, sid, last_day, asof_dt, cat),
                    "superseded_points": superseded, "future_points_dropped": future,
                    "catalog": {k: row.get(k) for k in ("publisher", "verdict", "badge", "lag_note", "terms", "max_age_days", "source_entry")}})
    return {"as_of": iso_utc(utcnow()), "asof_applied": iso_utc(asof_dt), "freq": freq or "D", "series": out}


def _fresher_twin(store: Any, sid: str, last_day: date | None, asof: datetime, cat: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """The twin's latest point when it is NEWER than ``sid``'s (or ``sid`` has none): {series_id, report_date, value,
    release_at, source, quality, name, verdict, ahead_days, relation, same_level}. None when there is no twin or it is not
    fresher. ``same_level`` False (Brent future vs dated spot, the FBIL fix vs the close) = a different quantity: show it
    under its own id and name, never as the primary's value."""
    twin = TWINS.get(sid)
    if not twin:
        return None
    today = ist_day(asof)
    start = (last_day or asof.date() - timedelta(days=30))
    df = pit.asof_series(store, [twin], start=start, asof=asof)
    if df.empty:
        df = _table_backed(store, twin, start=start, end=None, asof=asof)
        if df is None or df.empty:
            return None
    # wave 2 (C-DATA-02): a point dated after the reader's IST day describes a session that has not happened, so it is
    # not "fresher" — and it must not hide the twin's real latest point either (``gold_series`` has no session clock)
    df = df[[(db.to_date(d) or today) <= today for d in df["report_date"]]]
    if df.empty:
        return None
    last = df.iloc[-1]
    d = db.to_date(last["report_date"])
    if d is None or (last_day is not None and d <= last_day):
        return None
    row = cat.get(twin, {})
    sym = SYMBOL_BY_SERIES.get(twin)
    relation, same_level = twin_relation(sid, twin)
    return {"series_id": twin, "report_date": d.isoformat(), "value": _f(last["value"]), "release_at": _iso(last["release_at"]),
            "source": last.get("source") if hasattr(last, "get") else None, "quality": last.get("quality") if hasattr(last, "get") else None,
            "partial": bool(sym and str(last.get("quality")) == "partial"), "name": row.get("name"), "verdict": row.get("verdict"),
            "ahead_days": (d - last_day).days if last_day else None, "relation": relation, "same_level": same_level}


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
    return {"rows": db.records(df), "daily_gold": db.records(daily), "from": start.isoformat(), "avg_20d": efrp_avg(store)}


EFRP_AVG_SESSIONS = 20
EFRP_AVG_MIN_SESSIONS = 5


def efrp_avg(store: Any, *, sessions: int = EFRP_AVG_SESSIONS, min_sessions: int = EFRP_AVG_MIN_SESSIONS) -> dict[str, Any]:
    """The latest stored gold EFP/EFR day against the average of the up-to-20 stored sessions BEFORE it (wave 1d,
    gold_open_issues PHYSICAL › OTC: '20-d avg —'). Independent of the caller's ``from`` window; the average is None
    with a reason until ``min_sessions`` prior sessions are stored (the 2021→ archive backfill fills them)."""
    daily = db.query_df(store, """
        SELECT process_date, SUM(round_turns) AS round_turns FROM gold_cme_efrp WHERE product = 'GOLD'
        GROUP BY process_date ORDER BY process_date DESC LIMIT ?""", [sessions + 1])
    if daily.empty:
        return {"latest_date": None, "latest_round_turns": None, "avg_round_turns": None, "sessions": 0,
                "note": "no CME EFP/EFR file stored yet"}
    latest, prior = daily.iloc[0], daily.iloc[1:]
    n = len(prior)
    avg = float(prior["round_turns"].mean()) if n >= min_sessions else None
    return {"latest_date": _day(latest["process_date"]), "latest_round_turns": _f(latest["round_turns"]),
            "avg_round_turns": round(avg, 1) if avg is not None else None, "sessions": n,
            "window": {"from": _day(prior["process_date"].iloc[-1]), "to": _day(prior["process_date"].iloc[0])} if n else None,
            "vs_avg_pct": round((float(latest["round_turns"]) / avg - 1.0) * 100.0, 1) if avg else None,
            "note": None if avg is not None else f"the average needs {min_sessions} prior stored sessions; {n} stored"}


def _full_closures(exchange: str) -> set[date]:
    """Exchange days with no session at all (MCX: shared/mcx_specs full closures; a morning/evening closure still trades)."""
    if exchange != "MCX":
        return set()
    try:
        from shared import mcx_specs as specs

        return {d for d, (_, closure) in specs.MCX_HOLIDAYS_2026.items() if closure == "full"}
    except Exception:  # noqa: BLE001 — the specs module is optional for a read
        return set()


def _special_sessions(exchange: str) -> set[date]:
    """Dated special sessions (MCX Muhurat, Sun 8 Nov 2026: shared/mcx_specs) — sessions on a weekend (wave 1e, M-D)."""
    if exchange != "MCX":
        return set()
    try:
        from shared import mcx_specs as specs

        return set(specs.SPECIAL_SESSION_WINDOWS)
    except Exception:  # noqa: BLE001 — the specs module is optional for a read
        return set()


def sessions_between(prev: date | None, cur: date, *, closures: set[date] | None = None,
                     specials: set[date] | None = None) -> int | None:
    """Trading sessions in (prev, cur]: weekdays minus full closures, plus dated special sessions (``specials``: MCX
    Muhurat). None without a previous row. A stored OI delta whose previous row is more than one session back spans the
    gap (wave 1c, C-TRADER-18: '29 Oct → 3 Nov labelled as one day'); the UI prints 'over N sessions' when this is > 1."""
    if prev is None or cur <= prev:
        return None
    closures = closures or set()
    specials = specials or set()
    n, d = 0, prev
    while d < cur:
        d += timedelta(days=1)
        if (d.weekday() < 5 and d not in closures) or d in specials:
            n += 1
    return n


def _with_sessions_spanned(store: Any, rows: pd.DataFrame, exchange: str) -> list[dict[str, Any]]:
    """``db.records`` plus ``oi_change_from`` (the previous stored trade_date of the same contract and source) and
    ``sessions_spanned`` (sessions that delta covers; 1 = one day, >1 = a gap in the master)."""
    recs = db.records(rows)
    if not recs:
        return recs
    closures, specials = _full_closures(exchange), _special_sessions(exchange)
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
        r["sessions_spanned"] = sessions_between(p, cur, closures=closures, specials=specials) if (cur and r.get("oi_change") is not None) else None
    return recs


# ── MCX settlements (wave 1d, the 5 Nov blocker) ─────────────────────────────────────────────────────
# A master row (source icici_master_band) is keyed by S1, the session of its OI; its band midpoint is the settlement of
# band_session(S1), the session BEFORE. Reads re-key: row S gets settle = the Breeze VWAP30 proxy of S when stored, else
# the midpoint of the master row whose band session IS S (the next file), else None — never the previous session's.

def _yyyymm(d: date | None) -> str | None:
    return f"{d:%Y%m}" if d else None


def _vwap_lookup(store: Any, keys: set[tuple[str, date]], start: date | None, end: date | None,
                 asof: datetime | None = None) -> dict[tuple[str, str, date], dict[str, Any]]:
    """{(family, YYYYMM, session): {value, lots, release_at}} from the stored VWAP30 series (as of ``asof``)."""
    ids: list[str] = []
    for fam, exp in keys:
        if fam in mcx_close.BREEZE_CODE and exp is not None:
            ids += [mcx_close.series_id(fam, exp), mcx_close.lots_series_id(fam, exp)]
    if not ids:
        return {}
    df = pit.asof_series(store, sorted(set(ids)), start=start, end=end, asof=asof)
    out: dict[tuple[str, str, date], dict[str, Any]] = {}
    for r in df.itertuples(index=False):
        p = mcx_close.parse_series_id(str(r.series_id))
        d = db.to_date(r.report_date)
        if p is None or d is None:
            continue
        k = (p[0], f"{p[1]:04d}{p[2]:02d}", d)
        rec = out.setdefault(k, {})
        if p[3]:
            rec["lots"] = int(r.value)
        else:
            rec["value"], rec["release_at"] = float(r.value), _iso(r.release_at)
    return {k: v for k, v in out.items() if "value" in v}


def mcx_settlement_rows(store: Any, recs: list[dict[str, Any]], *, asof: datetime | None = None) -> list[dict[str, Any]]:
    """Add the session-correct settlement to MCX master rows (others pass through untouched):
    ``settle`` (re-keyed, see above), ``settle_source`` breeze_vwap30 | band_midpoint | None, ``settle_quality``
    vwap30_proxy | band_proxy, ``settle_session``, ``settle_vwap30`` / ``vwap30_lots``, ``settle_band`` (the band-derived
    value for this session), ``settle_check`` {band_vs_vwap30_pct, flagged} when both exist for the session, and the raw
    band of the row labelled with the session it belongs to: ``band_midpoint``, ``band_session`` (+ label), ``oi_session``."""
    mrecs = [r for r in recs if r.get("source") == "icici_master_band"]
    if not mrecs:
        return recs
    days = [d for d in (db.to_date(r.get("trade_date")) for r in mrecs) if d is not None]
    syms = sorted({str(r["symbol"]) for r in mrecs})
    lo_d, hi_d = min(days), max(days)
    marks = ", ".join("?" for _ in syms)
    nxt = db.query_df(store, f"""SELECT symbol, expiry, trade_date, band_lo, band_hi, settle FROM gold_curve
                                 WHERE exchange = 'MCX' AND source = 'icici_master_band' AND symbol IN ({marks})
                                 AND trade_date > ? AND trade_date <= ?""", [*syms, lo_d, hi_d + timedelta(days=14)])
    band_for: dict[tuple[str, str, date], float] = {}
    for r in nxt.itertuples(index=False):
        td = db.to_date(r.trade_date)
        mid = band_midpoint(r.band_lo, r.band_hi) or _f(r.settle)
        if td is not None and mid:
            band_for[(str(r.symbol), str(db.to_date(r.expiry)), band_session(td))] = mid
    keys: set[tuple[str, date]] = set()
    for r in mrecs:
        e = db.to_date(r.get("expiry"))
        if e is not None:
            keys.add((str(r["symbol"]), e))
    vw = _vwap_lookup(store, keys, lo_d, hi_d, asof)
    for r in mrecs:
        td = db.to_date(r.get("trade_date"))
        exp = db.to_date(r.get("expiry"))
        if td is None:
            continue
        fam = str(r["symbol"])
        raw_mid = band_midpoint(r.get("band_lo"), r.get("band_hi")) or _f(r.get("settle"))
        bs = band_session(td)
        b = band_for.get((fam, str(exp), td))
        v = vw.get((fam, _yyyymm(exp) or "", td))
        settle, src, qual = ((v["value"], "breeze_vwap30", "vwap30_proxy") if v else
                             (b, "band_midpoint", "band_proxy") if b else (None, None, None))
        # round 2 (check: the raw stored ``session_date`` passed through, = trade_date on rows written before the relabel,
        # so a reader pairing ``settle`` with it mislabelled the session). In this read ``session_date`` is the session the
        # SERVED ``settle`` belongs to (= ``settle_session``; null while ``settle`` is null) whatever the stored value is —
        # migration-independent. The raw band's session is ``band_session``; the OI's is ``oi_session``.
        r.update({"oi_session": td.isoformat(), "band_midpoint": raw_mid, "band_session": bs.isoformat(),
                  "band_session_label": mcx_close.session_label(bs), "settle": settle, "settle_source": src, "settle_quality": qual,
                  "settle_session": td.isoformat() if settle else None, "settle_session_label": mcx_close.session_label(td) if settle else None,
                  "session_date": td.isoformat() if settle else None,
                  "settle_vwap30": v["value"] if v else None, "vwap30_lots": v.get("lots") if v else None, "settle_band": b,
                  "settle_check": mcx_close.settlement_check(b, v["value"] if v else None),
                  "settle_inr_per_10g": ingest_india.per_10g(settle, fam) if settle else None})   # D3: PETAL × 10, GUINEA × 1.25
    return recs


def _latest_completed(day: date, asof: datetime) -> date | None:
    """The latest MCX session completed at the read's instant: ``asof``, or the end of ``day`` (IST) for a past ``date``."""
    end_of_day = datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=mcx_close.IST).astimezone(mcx_close.UTC).replace(tzinfo=None)
    return mcx_close.latest_completed_session(min(asof, end_of_day))


def _settlement_block(symbol: str, expiry: date | None, bands: list[tuple[date, float | None, Any]], vw_pts: dict[date, float],
                      lots: dict[date, int], latest: date | None = None) -> dict[str, Any]:
    """The fair-block fields from one contract's band rows (newest first: (band_session, midpoint, release_at)) and VWAP30
    points: the VWAP30 when its session is the newest, else the band midpoint labelled with its REAL session. ``latest`` =
    the latest COMPLETED MCX session at the read's instant: ``settlement_is_latest`` says whether the served number belongs
    to it (round 2, check: a failed 23:58 job left the consumer unable to tell the proxy was a session behind)."""
    factor, ref = ingest_india.landed_factor(symbol)
    out: dict[str, Any] = {"symbol": symbol, "expiry": expiry.isoformat() if expiry else None, "settlement": None,
                           "settlement_source": None, "settlement_session": None, "settlement_session_label": None,
                           "settlement_quality": None, "band_midpoint": None, "band_session": None, "band_session_label": None,
                           "band_release_at": None, "vwap30_lots": None, "settlement_check": None, "band_same_session_pct": None,
                           "latest_completed_session": latest.isoformat() if latest else None,
                           "latest_completed_session_label": mcx_close.session_label(latest), "settlement_is_latest": False,
                           "settlement_sessions_behind": None,
                           "unit": ingest_india.QUOTE_UNIT.get(symbol), "quote_grams": ingest_india.QUOTE_GRAMS.get(symbol),
                           "purity": ingest_india.MCX_PURITY.get(symbol), "basis_reference": ref, "landed_factor": round(factor, 6),
                           "settlement_inr_per_10g": None, "band_midpoint_inr_per_10g": None,
                           "as_of": iso_utc(utcnow())}
    vw_day = max(vw_pts) if vw_pts else None
    if bands:
        out.update({"band_midpoint": bands[0][1], "band_session": bands[0][0].isoformat(),
                    "band_session_label": mcx_close.session_label(bands[0][0]), "band_release_at": _iso(bands[0][2])})
    if vw_day is not None and (not bands or vw_day >= bands[0][0]):
        out.update({"settlement": vw_pts[vw_day], "settlement_source": "breeze_vwap30", "settlement_session": vw_day.isoformat(),
                    "settlement_session_label": mcx_close.session_label(vw_day), "settlement_quality": "vwap30_proxy",
                    "vwap30_lots": lots.get(vw_day)})
        out["settlement_check"] = mcx_close.settlement_check(bands[0][1], vw_pts[vw_day]) if bands else None
        same = next((m for s_, m, _ in bands if s_ == vw_day), None)
        chk = mcx_close.settlement_check(same, vw_pts[vw_day])
        out["band_same_session_pct"] = chk["band_vs_vwap30_pct"] if chk else None
    elif bands:
        out.update({"settlement": bands[0][1], "settlement_source": "band_midpoint", "settlement_session": bands[0][0].isoformat(),
                    "settlement_session_label": mcx_close.session_label(bands[0][0]), "settlement_quality": "band_proxy"})
        out["settlement_check"] = mcx_close.settlement_check(bands[0][1], vw_pts.get(bands[0][0]))
        out["band_same_session_pct"] = out["settlement_check"]["band_vs_vwap30_pct"] if out["settlement_check"] else None
    elif expiry is not None:
        out["note"] = f"no band or VWAP30 stored for MCX {symbol} {expiry:%b-%y}"
    sess = db.to_date(out["settlement_session"])
    if sess is not None and latest is not None:
        out["settlement_is_latest"] = sess >= latest
        out["settlement_sessions_behind"] = len(mcx_close.sessions_between(sess + timedelta(days=1), latest)) if sess < latest else 0
    out["settlement_inr_per_10g"] = ingest_india.per_10g(out["settlement"], symbol)        # D3: PETAL ₹/1 g × 10, GUINEA ₹/8 g × 1.25
    out["band_midpoint_inr_per_10g"] = ingest_india.per_10g(out["band_midpoint"], symbol)
    return out


def _settlement_inputs(store: Any, keys: list[tuple[str, date]], day: date, asof: datetime
                       ) -> dict[tuple[str, date], tuple[list[tuple[date, float | None, Any]], dict[date, float], dict[date, int]]]:
    """Batch: per (symbol, expiry) the 12 newest band rows visible at ``asof`` and the VWAP30 / lots points of the last 3 weeks
    (two queries for the whole chain)."""
    out: dict[tuple[str, date], tuple[list[tuple[date, float | None, Any]], dict[date, float], dict[date, int]]] = {
        k: ([], {}, {}) for k in keys}
    if not keys:
        return out
    syms = sorted({k[0] for k in keys})
    marks = ", ".join("?" for _ in syms)
    band = db.query_df(store, f"""SELECT symbol, expiry, trade_date, band_lo, band_hi, settle, release_at FROM gold_curve
                                  WHERE exchange = 'MCX' AND source = 'icici_master_band' AND symbol IN ({marks}) AND trade_date <= ?
                                  AND release_at <= ? QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol, expiry ORDER BY trade_date DESC) <= 12
                                  ORDER BY symbol, expiry, trade_date DESC""", [*syms, day, asof])
    for r in band.itertuples(index=False):
        e, td = db.to_date(r.expiry), db.to_date(r.trade_date)
        if e is None or td is None or (str(r.symbol), e) not in out:
            continue
        out[(str(r.symbol), e)][0].append((band_session(td), band_midpoint(r.band_lo, r.band_hi) or _f(r.settle), r.release_at))
    ids = [i for f, e in keys if f in mcx_close.BREEZE_CODE for i in (mcx_close.series_id(f, e), mcx_close.lots_series_id(f, e))]
    vws = pit.asof_series(store, ids, start=day - timedelta(days=21), end=day, asof=asof) if ids else pd.DataFrame()
    by_id = {mcx_close.series_id(f, e): (f, e) for f, e in keys if f in mcx_close.BREEZE_CODE}
    for r in vws.itertuples(index=False):
        sid, rd = str(r.series_id), db.to_date(r.report_date)
        lot = sid.endswith("_LOTS")
        k = by_id.get(sid[:-5] if lot else sid)
        if k is None or rd is None:
            continue
        if lot:
            out[k][2][rd] = int(r.value)
        else:
            out[k][1][rd] = float(r.value)
    return out


def _front_expiry(store: Any, symbol: str, day: date) -> date | None:
    return db.to_date(db.scalar(store, """SELECT MIN(expiry) FROM gold_curve WHERE exchange = 'MCX' AND source = 'icici_master_band'
        AND symbol = ? AND trade_date = (SELECT MAX(trade_date) FROM gold_curve WHERE exchange = 'MCX'
        AND source = 'icici_master_band' AND symbol = ? AND trade_date <= ?) AND expiry >= trade_date""", [symbol, symbol, day]))


def mcx_settlement(store: Any, *, symbol: str = "GOLD", expiry: date | None = None, day: date | None = None,
                   asof: datetime | None = None) -> dict[str, Any]:
    """The latest COMPLETED session's settlement proxy for one MCX contract on/before ``day`` (API_CONTRACT wave 1d
    fair block): the Breeze VWAP30 when it is the newest session stored, else the ICICI band midpoint labelled with its
    REAL session. ``settlement_check`` compares the newest band midpoint with the VWAP30 of the settlement session
    (flagged beyond 0.6 %: the band is stale); ``band_same_session_pct`` checks the proxy pair of one session."""
    asof_dt = asof or utcnow()
    day = day or asof_dt.replace(tzinfo=mcx_close.UTC).astimezone(mcx_close.IST).date()
    expiry = expiry or _front_expiry(store, symbol, day)
    latest = _latest_completed(day, asof_dt)
    if expiry is None:
        return {**_settlement_block(symbol, None, [], {}, {}, latest), "note": f"no MCX {symbol} contract stored"}
    bands, vw_pts, lots = _settlement_inputs(store, [(symbol, expiry)], day, asof_dt)[(symbol, expiry)]
    return _settlement_block(symbol, expiry, bands, vw_pts, lots, latest)


def mcx_latest_settlements(store: Any, rows: list[dict[str, Any]], *, day: date | None = None,
                           asof: datetime | None = None) -> list[dict[str, Any]]:
    """``mcx_settlement`` for every (symbol, expiry) of the given master rows — the CONTRACTS chain in two queries."""
    asof_dt = asof or utcnow()
    day = day or asof_dt.replace(tzinfo=mcx_close.UTC).astimezone(mcx_close.IST).date()
    keys: list[tuple[str, date]] = []
    for r in rows:
        e = db.to_date(r.get("expiry"))
        if r.get("source") == "icici_master_band" and e is not None and (str(r["symbol"]), e) not in keys:
            keys.append((str(r["symbol"]), e))
    keys.sort()
    inputs = _settlement_inputs(store, keys, day, asof_dt)
    latest = _latest_completed(day, asof_dt)
    return [_settlement_block(s_, e, *inputs[(s_, e)], latest) for s_, e in keys]


def curve(store: Any, *, exchange: str = "COMEX", day: date | None = None) -> dict[str, Any]:
    """The latest curve on/before ``day`` per source (proxy and official coexist), plus the curve one week earlier.
    Every row carries ``oi_change_from`` / ``sessions_spanned`` (see ``_with_sessions_spanned``); MCX master rows carry
    the session-correct settlement (``mcx_settlement_rows``) and the reply adds ``settlements`` (wave 1d)."""
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
    recs = _with_sessions_spanned(store, rows, exchange)
    ghost_recs = _with_sessions_spanned(store, ghost, exchange)
    out: dict[str, Any] = {"exchange": exchange, "date": latest_d.isoformat(), "rows": recs, "ghost_1w": ghost_recs,
                           "ghost_date": ghost_d.isoformat() if ghost_d else None}
    if exchange == "MCX":
        mcx_settlement_rows(store, recs)
        mcx_settlement_rows(store, ghost_recs)
        out["settlements"] = mcx_latest_settlements(store, recs, day=day)
        out["settle_note"] = ("MCX master rows: trade_date = the session of the OI; the band midpoint is the settlement of "
                              "band_session (one session earlier); settle = the VWAP30 proxy or the next file's midpoint for "
                              "THIS session (None until one exists)")
    return out


def curve_history(store: Any, *, exchange: str = "MCX", symbol: str = "GOLD", days: int = 120) -> dict[str, Any]:
    df = db.query_df(store, """
        SELECT trade_date, session_date, symbol, expiry, settle, band_lo, band_hi, open_interest, oi_change, source, quality
        FROM gold_curve WHERE exchange = ? AND symbol = ? AND trade_date >= ? ORDER BY trade_date, expiry""",
                     [exchange, symbol, utcnow().date() - timedelta(days=days)])
    recs = _with_sessions_spanned(store, df, exchange)
    out: dict[str, Any] = {"exchange": exchange, "symbol": symbol, "rows": recs}
    if exchange == "MCX":
        mcx_settlement_rows(store, recs)
        # wave 1d: one settlement per SESSION for the front contract (VWAP30, else the re-keyed band) — includes the sessions
        # the master skipped (their band arrives with the next file); the line to draw for a settlement history
        front = mcx_close.session_settlements(store, symbol)
        since = utcnow().date() - timedelta(days=days)
        out["session_settlements"] = [{"session": _day(r.session), "expiry": _day(r.expiry), "settle": _f(r.settle), "source": r.source,
                                       "quality": "vwap30_proxy" if r.source == "breeze_vwap30" else "band_proxy"}
                                      for r in front.itertuples(index=False) if (db.to_date(r.session) or date.min) >= since]
    return out


MCX_DAILY_DEFAULT_DAYS = 180
# Quotation units of the non-gold MCX families the CMDT desks read (R5-CMDTY): gold_mcx_daily is keyed
# (trade_date, family, expiry) and family-generic; these rows arrive once the gold_breeze_daily family
# extension is approved (pending patch request). ingest_india.QUOTE_UNIT stays gold-only.
MCX_DAILY_EXTRA_UNITS: dict[str, str] = {"SILVER": "INR/kg", "SILVERM": "INR/kg", "SILVERMIC": "INR/kg",
                                         "CRUDEOIL": "INR/bbl", "CRUDEOILM": "INR/bbl"}


def mcx_daily(store: Any, *, family: str | None = None, expiry: date | None = None, start: date | None = None,
              end: date | None = None, limit: int = 20000) -> dict[str, Any]:
    """Breeze daily bars of MCX gold futures per expiry (gold_mcx_daily, O-8): OHLC in the family's quotation unit
    (``unit`` per row: PETAL ₹/1 g, GUINEA ₹/8 g), volume and open interest in lots, ``release_at`` = our fetch time of
    the stored values and ``first_seen_at`` = the first fetch, both served with ``+00:00``; dates ``YYYY-MM-DD``.
    ``from`` defaults to 180 days back. A broker bar, not MCX's official bhavcopy (``quality`` = broker)."""
    start = start or (utcnow().date() - timedelta(days=MCX_DAILY_DEFAULT_DAYS))
    sql = f"SELECT * FROM {mcx_daily_mod.TABLE} WHERE trade_date >= ?"
    params: list[Any] = [start]
    if end:
        sql += " AND trade_date <= ?"
        params.append(end)
    if family:
        sql += " AND family = ?"
        params.append(family)
    if expiry:
        sql += " AND expiry = ?"
        params.append(expiry)
    df = db.query_df(store, sql + " ORDER BY family, expiry, trade_date", params).tail(limit)
    rows = db.records(df)
    for r in rows:
        fam = str(r.get("family"))
        r["unit"] = ingest_india.QUOTE_UNIT.get(fam) or MCX_DAILY_EXTRA_UNITS.get(fam)
    return {"rows": rows, "count": len(rows), "from": start.isoformat(), "to": end.isoformat() if end else None, "family": family,
            "expiry": expiry.isoformat() if expiry else None, "source": mcx_daily_mod.SOURCE, "quality": mcx_daily_mod.QUALITY,
            "note": ("ICICI Breeze daily bars per LIVE contract (fetched 09:35 for the previous session); volume and OI in lots; "
                     "not MCX's official bhavcopy")}


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
    Intraday ``ts`` is serialised with an explicit ``+00:00`` (the store is UTC-naive; wave 1c, C-TRADER-1 / C-DATA-1).
    A daily bar dated after the reader's IST day is not served and is counted in ``future_rows_dropped`` (wave 2,
    C-DATA-02: a weekend snapshot of Friday's last quote had been stored under next Monday's date)."""
    sym = SYMBOL_BY_SERIES.get(symbol, symbol)
    params: list[Any]
    dropped = 0
    if interval == "1d":
        start_d = db.to_date(start) or (utcnow().date() - timedelta(days=400))
        today_ist = ist_day(utcnow())
        end_d = min(db.to_date(end) or today_ist, today_ist)
        sql = ("SELECT trade_date, open, high, low, close, adj_close, volume, source, first_seen_at FROM gold_daily_bars "
               "WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?")
        params = [sym, start_d, end_d]
        # the counter means what it says: rows THIS read asked for and did not serve. A window that ended before today
        # never asked for them, so it reports 0 (and pays no COUNT(*)) — the count is the honesty check on the clamp
        # above, not a property of the symbol.
        if (db.to_date(end) or today_ist) >= today_ist:
            dropped = int(db.scalar(store, "SELECT COUNT(*) FROM gold_daily_bars "
                                           "WHERE symbol = ? AND trade_date > ? AND trade_date >= ?",
                                    [sym, today_ist, start_d]) or 0)
        df = db.query_df(store, sql + " ORDER BY trade_date", params).tail(limit)
        if not df.empty:        # a bar fetched before its session close is the in-progress session, not a close (C-DATA-21)
            df["partial"] = [is_partial(sym, d, t) for d, t in zip(df["trade_date"], df["first_seen_at"])]
            # wave 1d (WEEKLY 'Tue 172,512 ?'): Yahoo sometimes repeats the previous session's volume on a futures bar; the
            # store flags an exact repeat so a reader can grey it instead of printing it as that day's volume.
            # wave 2 (C-DATA-05): the previous row's volume may itself be a mid-session count, so the comparison also runs
            # against the last SETTLED (non-partial) volume — a value carried forward over a partial bar is still a repeat
            vol = pd.to_numeric(df["volume"], errors="coerce")
            partial = df["partial"].to_numpy(dtype=bool)
            settled = vol.where(~partial).shift(1).ffill()                     # the last volume of a session that had closed
            after_partial = pd.Series(partial, index=df.index).shift(1).fillna(False).to_numpy(dtype=bool)
            df["volume_repeat"] = (((vol == vol.shift(1)) | ((vol == settled) & after_partial))
                                   & vol.notna() & (vol > 0)).astype(bool)
    else:
        start_dt = pd.Timestamp(start).to_pydatetime() if start else (utcnow() - timedelta(days=7))
        sql = "SELECT ts, open, high, low, close, volume, source FROM gold_bars_intraday WHERE symbol = ? AND interval = ? AND ts >= ?"
        params = [sym, interval, start_dt]
        if end:
            sql += " AND ts <= ?"
            params.append(pd.Timestamp(end).to_pydatetime())
        df = db.query_df(store, sql + " ORDER BY ts", params).tail(limit)
    return {"symbol": sym, "series_id": SERIES_BY_SYMBOL.get(sym), "interval": interval, "rows": db.records(df), "count": len(df),
            "future_rows_dropped": dropped}


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
    rows = db.records(df)
    for r in rows:              # wave 1d (MACRO › FED PATH): the tracker's dates are SOFR/IMM horizons, not FOMC decision days
        m = db.to_date(r.get("meeting"))
        imm = bool(m and m.month in (3, 6, 9, 12) and m.weekday() == 2 and 15 <= m.day <= 21)
        r["horizon_kind"] = "imm_third_wednesday" if imm else "tracker_date"
        r["horizon_label"] = (f"{m:%a %d %b %Y} (SOFR/IMM horizon, not an FOMC date)" if imm else f"{m:%a %d %b %Y} (tracker date)") if m else None
    return {"as_of": day.isoformat(), "rows": rows,
            "note": "Atlanta Fed Market Probability Tracker: probabilities at SOFR-futures (IMM, third-Wednesday) horizons; the FOMC "
                    "decision calendar is the Fed's own (federalreserve.gov/monetarypolicy/fomccalendars.htm)"}


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
    stats: dict[str, Any] = {"days": len(scored), "median_abs_error": errs[len(errs) // 2] if errs else None,
             "mean_abs_error": (sum(errs) / len(errs)) if errs else None,
             "p90": errs[min(len(errs) - 1, int(0.9 * len(errs)))] if errs else None,
             "bias": (sum(float(r["error"]) for r in scored) / len(scored)) if scored else None,
             "naive_mean_abs_error": (sum(abs(float(r["naive_error"])) for r in scored if r.get("naive_error") is not None)
                                      / max(1, sum(1 for r in scored if r.get("naive_error") is not None))) if scored else None,
             "stale_days": sum(1 for r in rows if r.get("stale_baseline"))}
    checked = _log_vwap_checks(store, rows)
    flagged = [r for r in checked if r.get("stale_baseline_vwap30")]
    naive_v = [abs(float(r["naive_error_vwap30"])) for r in checked if r.get("naive_error_vwap30") is not None]
    # round 2 (check: the ₹1,466 → ₹569 comparison mixed day sets): the stored naive miss on the SAME checked days
    naive_same = [abs(float(r["naive_error"])) for r in checked if r.get("naive_error_vwap30") is not None and r.get("naive_error") is not None]
    any_checked = [r for r in rows if r.get("stale_check_source")]
    stats.update({"checked_days_vwap30": len(checked), "stale_days_vwap30": len(flagged),
                  "naive_mean_abs_error_vwap30": (sum(naive_v) / len(naive_v)) if naive_v else None,
                  "naive_mean_abs_error_stored_same_days": (sum(naive_same) / len(naive_same)) if naive_same else None,
                  "checked_days_any": len(any_checked), "stale_days_any": sum(1 for r in any_checked if r.get("stale_baseline_checked")),
                  "unchecked_days": sorted(str(r.get("day"))[:10] for r in rows if not r.get("stale_check_source")),
                  "stale_rule": (f"|baseline ÷ VWAP30 of the previous MCX session − 1| > {mcx_close.SETTLE_CHECK_PCT} %; without a "
                                 "stored VWAP30, the same test against the band midpoint centred on that session (the next "
                                 "master's); stored numbers are never rewritten, only flagged")})
    return {"rows": rows, "accuracy": stats}


_LOG_CONTRACT = re.compile(r"^\s*(GOLD|GOLDM|GOLDTEN|GOLDPETAL|GOLDGUINEA)\s+([A-Z]{3})-(\d{2})\s*$", re.IGNORECASE)


def _log_contract(r: dict[str, Any]) -> tuple[str, str] | None:
    """('GOLD', '202612') from the row's expiry, else from its 'GOLD DEC-26' label."""
    exp = db.to_date(r.get("expiry"))
    m = _LOG_CONTRACT.match(str(r.get("contract") or ""))
    if m is None:
        return None
    if exp is not None:
        return m.group(1).upper(), f"{exp:%Y%m}"
    try:
        mon = datetime.strptime(m.group(2).title(), "%b").month  # noqa: DTZ007 — a month name, no zone
    except ValueError:
        return None
    return m.group(1).upper(), f"20{m.group(3)}{mon:02d}"


def _master_expiries(store: Any, families: set[str]) -> dict[tuple[str, str], date]:
    """{(family, YYYYMM): expiry} from every stored ICICI master row (the exchange's own dates)."""
    if not families:
        return {}
    fams = sorted(families)
    df = db.query_df(store, f"""SELECT DISTINCT symbol, expiry FROM gold_curve WHERE exchange = 'MCX' AND source = 'icici_master_band'
                                AND symbol IN ({', '.join('?' for _ in fams)})""", fams)
    out: dict[tuple[str, str], date] = {}
    for r in df.itertuples(index=False):
        e = db.to_date(r.expiry)
        if e is not None:
            out.setdefault((str(r.symbol), f"{e:%Y%m}"), e)
    return out


def _log_expiry(r: dict[str, Any], c: tuple[str, str], master: dict[tuple[str, str], date]) -> tuple[date | None, str | None]:
    """(expiry, source) of a log row (PM decision D2): the row's own expiry ('row'); else the contract label's month in the
    stored ICICI master ('master'); else the exchange rule (shared/mcx_specs via ``ingest_india.family_expiry``, 'rule')."""
    exp = db.to_date(r.get("expiry"))
    if exp is not None:
        return exp, "row"
    if c in master:
        return master[c], "master"
    try:
        return ingest_india.family_expiry(c[0], int(c[1][:4]), int(c[1][4:])), "rule"
    except (ValueError, KeyError):
        return None, None


def _band_by_session(store: Any, keys: set[tuple[str, date]], start: date) -> dict[tuple[str, date, date], float]:
    """{(family, expiry, session): band midpoint centred on that session} — from the master whose OI session FOLLOWS it."""
    if not keys:
        return {}
    fams = sorted({f for f, _ in keys})
    df = db.query_df(store, f"""SELECT symbol, expiry, trade_date, band_lo, band_hi, settle FROM gold_curve WHERE exchange = 'MCX'
                                AND source = 'icici_master_band' AND symbol IN ({', '.join('?' for _ in fams)}) AND trade_date >= ?""",
                     [*fams, start])
    out: dict[tuple[str, date, date], float] = {}
    for r in df.itertuples(index=False):
        e, td = db.to_date(r.expiry), db.to_date(r.trade_date)
        mid = band_midpoint(r.band_lo, r.band_hi) or _f(r.settle)
        if e is not None and td is not None and mid and (str(r.symbol), e) in keys:
            out.setdefault((str(r.symbol), e, band_session(td)), mid)
    return out


def _log_vwap_checks(store: Any, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Wave 1d: each accuracy-log row whose contract has a stored VWAP30 for the session before its morning gets
    ``settle_vwap30`` / ``settle_vwap30_session``, ``baseline_vs_vwap30_pct``, ``stale_baseline_vwap30`` (the 0.6 % test)
    and ``naive_error_vwap30`` (open − that proxy); a band-midpoint baseline also gets ``baseline_session_real`` (the
    session its band was centred on). Returns the rows that could be checked against a VWAP30.

    Round 2 (PM decision D2): every row also gets ``expiry_derived`` / ``expiry_source`` ('row' | 'master' | 'rule': a row
    stored without an expiry takes it from its 'GOLD DEC-26' label); a row with no stored VWAP30 is checked with the SAME
    0.6 % test against the band midpoint centred on that session (``settle_band_session``, ``baseline_vs_band_pct``,
    ``stale_baseline_band``); ``stale_check_source`` ('breeze_vwap30' | 'band_midpoint' | None) and
    ``stale_baseline_checked`` say which reference decided. Stored numbers are never rewritten — only flagged."""
    contracts: dict[int, tuple[str, str]] = {}
    for i, r in enumerate(rows):
        c = _log_contract(r)
        if c is not None:
            contracts[i] = c
    if not contracts:
        return []
    master = _master_expiries(store, {c[0] for c in contracts.values()})
    expiries: dict[int, date] = {}
    for i, c in contracts.items():
        exp, src = _log_expiry(rows[i], c, master)
        rows[i]["expiry_derived"], rows[i]["expiry_source"] = (exp.isoformat() if exp else None), src
        if exp is not None:
            expiries[i] = exp
    days = [d for d in (db.to_date(rows[i].get("day")) for i in contracts) if d is not None]
    if not days:
        return []
    start = min(days) - timedelta(days=14)
    ids = sorted({f"MCX_{c[0]}_{c[1]}_VWAP30" for c in contracts.values()})
    df = pit.asof_series(store, ids, start=start)
    vw = {(str(r.series_id), db.to_date(r.report_date)): float(r.value) for r in df.itertuples(index=False)}
    bands = _band_by_session(store, {(contracts[i][0], e) for i, e in expiries.items()}, start)
    out = []
    for i, c in contracts.items():
        r = rows[i]
        d = db.to_date(r.get("day"))
        if d is None:
            continue
        prev = previous_mcx_session(d)
        if "band midpoint" in str(r.get("baseline_source") or "").lower():
            r["baseline_session_real"] = band_session(prev).isoformat()
        base = _f(r.get("baseline"))
        b = bands.get((c[0], expiries[i], prev)) if i in expiries else None
        if b is not None:
            chk_b = mcx_close.settlement_check(base, b)
            r["settle_band_session"], r["baseline_vs_band_pct"] = b, (chk_b["band_vs_vwap30_pct"] if chk_b else None)
            r["stale_baseline_band"] = bool(chk_b and chk_b["flagged"])
        v = vw.get((f"MCX_{c[0]}_{c[1]}_VWAP30", prev))
        if v is None:
            if b is not None and base:
                r["stale_check_source"], r["stale_baseline_checked"] = "band_midpoint", r["stale_baseline_band"]
            continue
        r["settle_vwap30"], r["settle_vwap30_session"] = v, prev.isoformat()
        chk = mcx_close.settlement_check(base, v)
        r["baseline_vs_vwap30_pct"] = chk["band_vs_vwap30_pct"] if chk else None
        r["stale_baseline_vwap30"] = bool(chk and chk["flagged"])
        r["naive_error_vwap30"] = round(float(r["actual_open"]) - v, 2) if r.get("actual_open") is not None else None
        if chk:
            r["stale_check_source"], r["stale_baseline_checked"] = "breeze_vwap30", r["stale_baseline_vwap30"]
        out.append(r)
    return out


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
        row = catalog_row(cat, str(r.series_id))       # round 2: 'MCX_GOLD_202612_VWAP30' → its family template row
        last_d = db.to_date(r.last)
        if not row or last_d is None:
            continue
        pc = mcx_close.parse_series_id(str(r.series_id))
        if pc is not None and ingest_india.family_expiry(pc[0], pc[1], pc[2]) < today:
            continue                                    # an expired contract month stops updating by design: not stale
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
