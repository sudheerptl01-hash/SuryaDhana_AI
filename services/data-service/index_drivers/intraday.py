"""Within-day index contribution (FINAL round R2-DRIV; RATING R9-I3 "an intraday within-day contribution timeline").

Per constituent, intraday contribution at minute t = prev index close × weight × intraday return, the same additive
identity as the nightly ``index_contribution_daily`` (points = L_{d−1} × w × r) read minute by minute:

- **Minute closes** come from the live tick store's parquet day files (``data/ticks/<IST date>/part-*.parquet``, written by
  ``live_ticks`` → ``tick_store``): the last print per symbol per arrival minute, bounded to the 09:15–15:30 session. The
  read is an in-memory DuckDB over the parquet parts (the ``prime_from_store`` pattern) — **never** ``market.duckdb``.
- **Fallback** where a name has no prints (unsubscribed): the 2-minute tape's stored spot (``iv_intraday``, UTC ts → IST),
  which carries the three indices and the watch names. A member on neither source is an **honest gap** — listed with its
  weight, never interpolated. Within the session, a name's last print is carried forward after its first print (that IS
  the price at that minute); before the first print the series is null (no backfill).
- **Weights / members / prev closes** are the stored point-in-time tables: ``index_weights_daily`` (best stored method on
  the latest date ≤ the session), ``index_constituents_daily``, ``index_ohlc_daily`` (prev index close) and
  ``nse_bhavcopy`` (a member's previous close when its ticks carried none).
- The **fit is shown, never hidden**: actual index move (its own minute series) vs Σ member points, with the residual per
  minute. Badges: timeline ``context``, fit/points ``arithmetic``; the note ends "describes, does not predict". Nothing
  here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.

Closed-market it renders the stored session (the parquet parts are on disk); live it ends the grid at the current minute.
A 30 s in-process cache keeps the request path fast (p95 budget 250 ms; the cold parquet scan is ~0.4 s once).
"""
from __future__ import annotations

import threading
import time as _time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from data_health import db

IST = timezone(timedelta(hours=5, minutes=30))
SESSION_OPEN_M, SESSION_CLOSE_M = 9 * 60 + 15, 15 * 60 + 30
DESCRIBES = "describes, does not predict"
#: best stored weight method first (same ranking as ui-api routers/markets.py METHOD_RANK)
METHOD_RANK = {"rebuilt_fitted": 0, "rebuilt_calibrated": 1, "rebuilt_capped": 2, "rebuilt": 3, "official_top10": 4}
#: the 2-min tape's spelling of the index underlyings (iv_intraday keys stocks by their NSE symbol)
TAPE_INDEX = {"NIFTY 50": "NIFTY", "NIFTY BANK": "BANKNIFTY", "NIFTY FINANCIAL SERVICES": "FINNIFTY"}
SOURCE_TICKS, SOURCE_TAPE = "icici-ws", "iv_intraday (2-min tape)"
CACHE_TTL_S = 30.0
BADGES = {"timeline": "context", "members": "arithmetic", "fit": "arithmetic"}

_cache: dict[tuple[Any, ...], tuple[float, dict[str, Any]]] = {}
_cache_lock = threading.Lock()


def _ticks_base() -> Path:
    import tick_store

    return tick_store.default_base_dir()


def _mins(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def _hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def minute_grid(interval: str, until: str | None = None) -> list[str]:
    """The session grid 09:15 → min(`until`, 15:30) at 1- or 5-minute steps (376 / 76 slots for a full day)."""
    step = 5 if interval == "5m" else 1
    end = min(_mins(until), SESSION_CLOSE_M) if until else SESSION_CLOSE_M
    return [_hhmm(t) for t in range(SESSION_OPEN_M, end + 1, step)]


def bucket_of(minute: str, interval: str) -> str:
    """A print's arrival minute → its grid slot (floor; 1m is the identity)."""
    if interval != "5m":
        return minute
    m = _mins(minute)
    return _hhmm(SESSION_OPEN_M + ((m - SESSION_OPEN_M) // 5) * 5)


def forward_fill(px_by_bucket: dict[str, float], grid: list[str]) -> list[float | None]:
    """Last print carried forward AFTER the first observation; null before it (honest gap, never a backfill)."""
    out: list[float | None] = []
    last: float | None = None
    for m in grid:
        v = px_by_bucket.get(m)
        if v is not None:
            last = v
        out.append(last)
    return out


def read_tick_day(files: list[str], symbols: list[str]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """One in-memory DuckDB scan of the day's parquet parts → ({symbol: {minute: close}}, {symbol: prev_close}).
    Minutes outside 09:15–15:30 (post-close pushes arrive stamped by arrival) are dropped here."""
    if not files or not symbols:
        return {}, {}
    import duckdb

    con = duckdb.connect()
    try:
        rows = con.execute(
            """SELECT symbol, substr(ts, 12, 5) AS minute, arg_max(price, ts) AS close, max(prev_close) AS prev
               FROM read_parquet(?)
               WHERE price IS NOT NULL AND list_contains(?, symbol)
                 AND substr(ts, 12, 5) BETWEEN '09:15' AND '15:30'
               GROUP BY 1, 2""",
            [files, list(symbols)]).fetchall()
    finally:
        con.close()
    closes: dict[str, dict[str, float]] = {}
    prevs: dict[str, float] = {}
    for sym, minute, close, prev in rows:
        closes.setdefault(str(sym), {})[str(minute)] = float(close)
        if prev is not None and str(sym) not in prevs:
            prevs[str(sym)] = float(prev)
    return closes, prevs


def tape_minutes(store: Any, symbols: list[str], day: date) -> dict[str, dict[str, float]]:
    """The 2-min tape's stored spot per minute for `symbols` on `day` (``iv_intraday`` ts is UTC → +05:30), bounded to
    the session. Missing table / no rows → {} (the caller lists the gap)."""
    if not symbols:
        return {}
    try:
        df = db.query_df(store, """SELECT symbol, strftime(ts + INTERVAL 330 MINUTE, '%H:%M') AS minute,
                                          arg_max(spot, ts) AS spot
                                   FROM iv_intraday
                                   WHERE spot IS NOT NULL AND list_contains(?, symbol)
                                     AND CAST(ts + INTERVAL 330 MINUTE AS DATE) = ?
                                   GROUP BY 1, 2""", [list(symbols), day])
    except Exception:  # noqa: BLE001 — the tape is a fallback; without the table there is simply no fallback
        return {}
    out: dict[str, dict[str, float]] = {}
    for r in df.itertuples(index=False):
        minute = str(r.minute)
        if "09:15" <= minute <= "15:30" and r.spot is not None:
            out.setdefault(str(r.symbol), {})[minute] = float(r.spot)
    return out


def _members(store: Any, index: str, day: date) -> dict[str, str | None]:
    df = db.query_df(store, """SELECT symbol, arg_max(industry, date) AS industry FROM index_constituents_daily
                               WHERE index_name = ? AND date = (SELECT MAX(date) FROM index_constituents_daily
                                                                WHERE index_name = ? AND date <= ?)
                               GROUP BY symbol""", [index, index, day])
    return {str(r.symbol): (str(r.industry) if r.industry else None) for r in df.itertuples(index=False)}


def _weights(store: Any, index: str, day: date) -> tuple[dict[str, float], str | None, str | None]:
    """Best stored method per symbol on the latest date ≤ `day` → ({symbol: weight_pct}, method, as_of)."""
    df = db.query_df(store, """SELECT symbol, weight_pct, method, date FROM index_weights_daily
                               WHERE index_name = ? AND date = (SELECT MAX(date) FROM index_weights_daily
                                                                WHERE index_name = ? AND date <= ?)""",
                     [index, index, day])
    best: dict[str, tuple[int, float]] = {}
    as_of: str | None = None
    for r in df.itertuples(index=False):
        if r.weight_pct is None:
            continue
        rank = METHOD_RANK.get(str(r.method), 9)
        sym = str(r.symbol)
        if sym not in best or rank < best[sym][0]:
            best[sym] = (rank, float(r.weight_pct))
        as_of = str(r.date)[:10]
    method = None
    if best:
        top = min(rank for rank, _ in best.values())
        method = next((m for m, k in METHOD_RANK.items() if k == top), None)
    return {s: w for s, (_, w) in best.items()}, method, as_of


def _prev_index_level(store: Any, index: str, day: date) -> float | None:
    v = db.scalar(store, "SELECT arg_max(close, date) FROM index_ohlc_daily WHERE symbol = ? AND date < ?", [index, day])
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _bhav_prev(store: Any, symbols: list[str], day: date) -> dict[str, float]:
    """Previous-session bhavcopy closes for members whose ticks carried no prev_close (fallback only)."""
    if not symbols:
        return {}
    try:
        df = db.query_df(store, """SELECT symbol, max(close) AS close FROM nse_bhavcopy
                                   WHERE date = (SELECT MAX(date) FROM nse_bhavcopy WHERE date < ?)
                                     AND series IN ('EQ', 'BE') AND list_contains(?, symbol)
                                   GROUP BY symbol""", [day, list(symbols)])
    except Exception:  # noqa: BLE001 — fallback only
        return {}
    return {str(r.symbol): float(r.close) for r in df.itertuples(index=False) if r.close}


def _last_value(series: list[float | None]) -> float | None:
    for v in reversed(series):
        if v is not None:
            return v
    return None


def _resolve_day(base: Path, requested: date | None, today: date) -> date:
    """The requested session, else today when its tick dir exists, else the latest stored tick day."""
    if requested is not None:
        return requested
    if (base / today.isoformat()).is_dir():
        return today
    stored = sorted(p.name for p in base.glob("20??-??-??") if p.is_dir()) if base.is_dir() else []
    if stored:
        try:
            return date.fromisoformat(stored[-1])
        except ValueError:
            pass
    return today


def intraday(store: Any, index: str, *, day: date | None = None, interval: str = "1m", top: int = 7,
             ticks_base: Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """The within-day contribution payload (see the module docstring). Pure read; 30 s in-process cache."""
    now = now or datetime.now(IST)
    base = ticks_base or _ticks_base()
    session = _resolve_day(base, day, now.date())
    key = (index, session.isoformat(), interval, int(top), str(base),
           now.strftime("%H:%M") if session == now.date() else "")
    with _cache_lock:
        hit = _cache.get(key)
        if hit and _time.monotonic() - hit[0] < CACHE_TTL_S:
            return hit[1]
    out = _compute(store, index, session, interval=interval, top=top, base=base, now=now)
    with _cache_lock:
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = (_time.monotonic(), out)
    return out


def _compute(store: Any, index: str, session: date, *, interval: str, top: int, base: Path,
             now: datetime) -> dict[str, Any]:
    industry = _members(store, index, session)
    weights, method, weights_as_of = _weights(store, index, session)
    members = sorted(s for s in industry if s in weights) or sorted(weights)
    day_dir = base / session.isoformat()
    files = sorted(str(f) for f in day_dir.glob("part-*.parquet")) if day_dir.is_dir() else []
    closes, tick_prevs = read_tick_day(files, [*members, index])

    # fallbacks: the 2-min tape for the index and any member with no prints; bhavcopy for missing prev closes
    source_of: dict[str, str] = {s: SOURCE_TICKS for s in closes}
    missing = [s for s in members if s not in closes]
    tape_want = ([TAPE_INDEX.get(index, index)] if index not in closes else []) + missing
    tape = tape_minutes(store, tape_want, session)
    for s in missing:
        if tape.get(s):
            closes[s] = tape[s]
            source_of[s] = SOURCE_TAPE
    index_minutes = closes.get(index)
    index_source = source_of.get(index)
    if index_minutes is None and tape.get(TAPE_INDEX.get(index, index)):
        index_minutes, index_source = tape[TAPE_INDEX.get(index, index)], SOURCE_TAPE
    prev_level = _prev_index_level(store, index, session) or tick_prevs.get(index)
    prevs = dict(tick_prevs)
    prevs.update(_bhav_prev(store, [s for s in members if s in closes and s not in prevs], session))

    live = session == now.date() and SESSION_OPEN_M <= (now.hour * 60 + now.minute) <= SESSION_CLOSE_M + 5
    grid = minute_grid(interval, until=now.strftime("%H:%M") if live else None)

    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    for s in members:
        w = weights.get(s)
        if s not in closes:
            gaps.append({"symbol": s, "weight_pct": w, "reason": "no prints on either source"})
            continue
        prev = prevs.get(s)
        if not prev or not prev_level or not w:
            gaps.append({"symbol": s, "weight_pct": w, "reason": "no previous close stored" if not prev else "no stored weight"})
            continue
        px = forward_fill({bucket_of(m, interval): v for m, v in sorted(closes[s].items())}, grid)
        series = [round(prev_level * (w / 100.0) * (p / prev - 1), 2) if p is not None else None for p in px]
        last_px = _last_value(px)
        rows.append({"symbol": s, "industry": industry.get(s), "weight_pct": round(w, 4), "source": source_of.get(s, SOURCE_TICKS),
                     "points": _last_value(series), "ret_pct": round((last_px / prev - 1) * 100, 2) if last_px else None,
                     "series": series})

    explained = [None if not any(r["series"][i] is not None for r in rows)
                 else round(sum(r["series"][i] or 0.0 for r in rows), 2) for i in range(len(grid))]
    priced = [sum(1 for r in rows if r["series"][i] is not None) for i in range(len(grid))]
    actual: list[float | None] = [None] * len(grid)
    if index_minutes and prev_level:
        ilvl = forward_fill({bucket_of(m, interval): v for m, v in sorted(index_minutes.items())}, grid)
        actual = [round(v - prev_level, 2) if v is not None else None for v in ilvl]
    residual = [round(a - e, 2) if a is not None and e is not None else None for a, e in zip(actual, explained, strict=True)]

    rows.sort(key=lambda r: -(r["points"] or 0.0))
    adds = [r for r in rows if (r["points"] or 0.0) > 0][:top]
    drags = sorted((r for r in rows if (r["points"] or 0.0) < 0), key=lambda r: r["points"] or 0.0)[:top]
    shown = {r["symbol"] for r in adds} | {r["symbol"] for r in drags}
    others = [None if (e := explained[i]) is None
              else round(e - sum(r["series"][i] or 0.0 for r in rows if r["symbol"] in shown), 2)
              for i in range(len(grid))]
    observed = [m for r in rows for m in ([grid[i] for i, v in enumerate(r["series"]) if v is not None][:1])]
    first_minute = min(observed) if observed else None
    slim = {k: None for k in ("series",)}  # the full per-member series travels only for the shown names

    return {
        "index": index, "date": session.isoformat(), "interval": interval, "live": live,
        "minutes": grid, "prev_index_level": round(prev_level, 2) if prev_level else None,
        "actual_pts": actual, "explained_pts": explained, "residual_pts": residual, "priced": priced,
        "residual_now": _last_value(residual), "index_source": index_source,
        "members": {"add": adds, "drag": drags,
                    "rest": [{**r, **slim} for r in rows if r["symbol"] not in shown]},
        "others_pts": others,
        "coverage": {"members_total": len(members), "members_priced": len(rows), "gaps": gaps},
        "weight_method": method, "weights_as_of": weights_as_of,
        "first_minute": first_minute, "last_minute": grid[-1] if grid else None,
        "as_of": now.isoformat(timespec="seconds"), "badges": dict(BADGES),
        "note": ("points = previous index close × weight × intraday return, from the tick store's minute closes "
                 "(a name's last print is carried forward after its first print; blank before it — gaps are shown, "
                 f"never filled); Σ member points vs the index's own move, residual shown — {DESCRIBES}"),
    }
