"""
Results history (Bloomberg ERN for NSE): when each quarterly result was released and how the stock reacted.

Release timestamps come from two free NSE feeds (one request each, per company):
  corporates-financial-results   2007 → early 2025 (field broadCastDate)
  integrated-filing-results      April 2025 → today (SEBI's integrated filing; field broadcast_Date)
The earliest broadcast per quarter-end is the release (consolidated and standalone are filed minutes apart).
Since 6 Nov 2026 (review M12) the company's own NSE results filing is read too ("Financial Result Updates" / an "Outcome of
Board Meeting" that submits the results): it is often hours earlier than the integrated feed's broadcast (MOTHERSON 5 Nov
2026: results filed 14:58:36, integrated broadcast 20:34), and an intraday filer's reaction is that session, not the next.
That earlier time goes to its OWN column, `nse_results.filed_at` (+ `filed_source`); `released_at` stays exactly the
feeds' earliest broadcast, because alpha_lab's S1 paper shadow builds its bad-results veto from `released_at` and the
trading inputs are frozen until the owner reviews them (tests/unit/test_results_history.py proves the S1 input bytes are
unchanged). The terminal's readers here (EVTS scoreboard, typical moves, the wrap, options-into-results) use
COALESCE(filed_at, released_at).
The integrated feed also carries each quarter's "Integrated Filing- Governance", filed one to two weeks *before*
the results; only "… Financials" rows count (until 14 Oct 2026 governance filings were taken as the release for
~41% of 2025–26 quarters).
Rows are stored in `nse_results` (point-in-time; refreshed per symbol at most once a week; `filed_at` only ever moves
earlier, like `released_at`).

Reaction, from split/bonus-adjusted NSE closes:
  released while the market is open (before 15:30 IST on a session) → previous close → that session's close
  released after 15:30 or on a holiday                              → close before → next session's close
`vs_nifty` subtracts NIFTY 50's move over the same window; `gap` is the first reaction session's open vs the
close before it.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Optional

import httpx
import numpy as np
import pandas as pd

from nse_filings import API, API_HEADERS

MARKET_OPEN, MARKET_CLOSE = (9, 15), (15, 30)
AVOID_REACTION_PCT, AVOID_SESSIONS = -5.0, 60      # reports/results_drift/FINDINGS.md (H2)
FEEDS: tuple[tuple[str, dict[str, str], str, str], ...] = (("corporates-financial-results", {"period": "Quarterly"}, "broadCastDate", "toDate"),
         ("integrated-filing-results", {}, "broadcast_Date", "qe_Date"))


def _ts(v: Any) -> Optional[datetime]:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            continue
    return None


def parse_releases(rows_by_feed: list[tuple[list[dict], str, str]], symbol: str) -> pd.DataFrame:
    """Earliest broadcast per quarter-end across feeds → (symbol, period_end, released_at)."""
    out = []
    for rows, ts_key, period_key in rows_by_feed:
        for r in rows or []:
            kind = str(r.get("type") or "")
            if kind and "financ" not in kind.lower():       # integrated feed: governance etc. are not results
                continue
            ts, pe = _ts(r.get(ts_key)), _ts(r.get(period_key))
            if ts and pe:
                out.append({"symbol": symbol, "period_end": pe.date(), "released_at": ts})
    if not out:
        return pd.DataFrame(columns=["symbol", "period_end", "released_at"])
    df = pd.DataFrame(out).sort_values("released_at")
    # a quarter's results arrive within days of each other (standalone / consolidated / revised): keep the first
    return df.drop_duplicates("period_end", keep="first").reset_index(drop=True)


ANNOUNCEMENT_FEED = "corporate-announcements"
ANNOUNCEMENT_RECENT_DAYS = 30             # routine fetches (nightly pass, weekly / ERN refresh): this quarter's filing only
ANNOUNCEMENT_REPAIR_DAYS = 800            # the one-off history repair (≈ 8 quarters: typical_moves reads the last eight)
ANNOUNCEMENT_MAX_LEAD = timedelta(days=3)  # a results filing at most this long before the feed's broadcast is the same release
ANNOUNCEMENT_MAX_AFTER_PERIOD = timedelta(days=120)   # SEBI's 45 / 60 days, with room for a delayed filer
_PERIOD_RE = re.compile(r"(?:quarter|period|half[- ]?year|year|nine months)(?: and [a-z ]+)? ended(?: on)?\s+([A-Za-z0-9 ,./\-]{6,24})", re.I)
_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y", "%d %B, %Y", "%d %B %Y", "%d %b %Y", "%d-%m-%Y", "%d.%m.%Y",
                 "%d/%m/%Y", "%d-%b-%Y", "%d-%B-%Y")
Filing = tuple[datetime, Optional[date]]


def period_from_text(text: str) -> Optional[date]:
    """The quarter end a results filing names ('… the financial results for the period ended Jun 30, 2026'), or None.
    Only calendar quarter ends count (31 Mar, 30 Jun, 30 Sep, 31 Dec)."""
    m = _PERIOD_RE.search(text or "")
    if not m:
        return None
    raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", m.group(1)).strip(" ,.")
    raw = re.sub(r"\bSept\b", "Sep", raw, flags=re.I)
    for n in range(len(raw), 5, -1):                     # the match may run into the next words: shorten until it parses
        chunk = raw[:n].strip(" ,.")
        for fmt in _DATE_FORMATS:
            try:
                d = datetime.strptime(chunk, fmt).date()
            except ValueError:
                continue
            q_end = (d.month, d.day) in ((3, 31), (6, 30), (9, 30), (12, 31))
            return d if q_end else None
    return None


def _iso_ts(v: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(v).strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def results_announcements(rows: list[dict]) -> list[tuple[datetime, Optional[date]]]:
    """(filed_at, period_end or None) for each NSE announcement that IS a results filing (data-service's own
    categoriser: an earnings-call notice or a board-meeting intimation is not results)."""
    from nse_live import filing_category
    out = []
    for r in rows or []:
        subject, text = str(r.get("desc") or ""), str(r.get("attchmntText") or "")
        if filing_category(subject, text) != "results":
            continue
        ts = _ts(r.get("an_dt")) or _iso_ts(r.get("sort_date"))
        if ts:
            out.append((ts, period_from_text(f"{subject} {text}")))
    # Sort on an explicit key, never on the tuples themselves: the second element is Optional[date], so two
    # filings sharing one `filed_at` — which NSE produces, the same company filing twice in the same second —
    # made Python fall through to comparing a date against None and raise
    # "TypeError: '<' not supported between instances of 'NoneType' and 'datetime.date'".
    # That killed the whole `nse_results` job (seen 13 Nov 15:15 and 17:15), not just the one symbol, because
    # results_filings_by_day builds every symbol inside one comprehension.
    return sorted(out, key=lambda t: (t[0], t[1] is not None, t[1] or date.min))


def reconcile_with_announcements(releases: pd.DataFrame, ann: list[tuple[datetime, Optional[date]]], symbol: str) -> pd.DataFrame:
    """Move each release to the earliest results filing of the same quarter: one naming the quarter end, or (no date in
    the text) one at most ANNOUNCEMENT_MAX_LEAD before the feed's broadcast and after the quarter end. A filing naming a
    quarter the feeds do not carry yet (the XBRL lags the PDF by hours) adds that quarter. `source` says which won."""
    rel = releases.copy()
    if rel.empty:
        rel = pd.DataFrame(columns=["symbol", "period_end", "released_at"])
    rel["source"] = "feed"
    rel["period_end"] = pd.to_datetime(rel["period_end"]).dt.date if len(rel) else rel["period_end"]
    rel["released_at"] = pd.to_datetime(rel["released_at"]) if len(rel) else rel["released_at"]
    by_pe = {pe: i for i, pe in zip(rel.index, rel["period_end"], strict=True)}
    extra: list[tuple[pd.Timestamp, date]] = []
    for ts, pe in ann:
        t = pd.Timestamp(ts)
        if pe is not None:
            if t.date() <= pe or t - pd.Timestamp(pe) > pd.Timedelta(ANNOUNCEMENT_MAX_AFTER_PERIOD):
                continue
            if pe in by_pe:
                i = by_pe[pe]
                if t < rel.at[i, "released_at"]:
                    rel.at[i, "released_at"], rel.at[i, "source"] = t, "announcement"
            elif not any(x[1] == pe for x in extra):
                extra.append((t, pe))
            continue
        cand = rel[(rel["released_at"] >= t) & (rel["released_at"] - t <= pd.Timedelta(ANNOUNCEMENT_MAX_LEAD))
                   & (pd.to_datetime(rel["period_end"]) < t.normalize())]
        if len(cand):
            i = cand["released_at"].idxmin()
            rel.at[i, "released_at"], rel.at[i, "source"] = t, "announcement"
    if extra:
        rel = pd.concat([rel, pd.DataFrame([{"symbol": symbol, "period_end": pe, "released_at": t, "source": "announcement_only"}
                                            for t, pe in extra])], ignore_index=True)
    return rel.sort_values("released_at").reset_index(drop=True)


_PACED: Any = None


def _paced() -> Any:
    """The process's paced NSE client for the announcement reads (shared/http_client: allowlist, ≥ 1.2 s per host,
    NSE 403/429 → 600 s breaker). One per process so the pacing holds across symbols and jobs."""
    global _PACED
    if _PACED is None:
        from shared.http_client import PacedClient
        _PACED = PacedClient(timeout_s=30)
    return _PACED


def _announcement_rows(paced: Any, params: dict[str, str]) -> Optional[list[dict]]:
    """One corporate-announcements GET through the paced client; None when it failed (never an empty 'no filings')."""
    from shared.http_client import UpstreamError
    try:
        r = paced.get(f"{API}/{ANNOUNCEMENT_FEED}", params={"index": "equities", **params}, headers=API_HEADERS)
        if r.status_code != 200:
            return None
        data = r.json()
    except (httpx.HTTPError, ValueError, UpstreamError):
        return None
    return data if isinstance(data, list) else (data or {}).get("data", []) if isinstance(data, dict) else None


def results_filings_by_day(start: date, end: date, paced: Any = None) -> Optional[dict[str, list[Filing]]]:
    """Results filings of EVERY company from NSE's day-wide announcement list, one paced request per calendar day
    (the nightly pass: ≈ 5 requests instead of one per reporter). None if any day failed, so the caller falls back to
    per-symbol reads instead of taking a failed day for 'no filing'."""
    paced = paced or _paced()
    by_symbol: dict[str, list[dict]] = {}
    d = start
    while d <= end:
        rows = _announcement_rows(paced, {"from_date": f"{d:%d-%m-%Y}", "to_date": f"{d:%d-%m-%Y}"})
        if rows is None:
            return None
        for r in rows:
            if r.get("symbol"):
                by_symbol.setdefault(str(r["symbol"]).upper(), []).append(r)
        d += timedelta(days=1)
    # R17-A: `sorted(set(ann))` re-sorted the very tuples whose comparison the callee was fixed for — the
    # same TypeError, in the caller the fix's own comment named as the blast radius ("results_filings_by_day
    # builds every symbol inside one comprehension"). `results_announcements` already returns them sorted, so
    # the only work left is dedupe, and dict.fromkeys does that while preserving that order and comparing
    # nothing. A sort that was never needed is a sort that cannot raise.
    return {sym: list(dict.fromkeys(ann)) for sym, rows in by_symbol.items()
            if (ann := results_announcements(rows))}


def fetch_releases(symbol: str, client: Optional[httpx.Client] = None, sleep_s: float = 0.6,
                   with_announcements: bool = True, today: Optional[date] = None,
                   announcement_days: int = 0, announcements: Optional[list[Filing]] = None,
                   paced: Any = None) -> pd.DataFrame:
    """Release times for one company → (symbol, period_end, released_at, filed_at, filed_source).

    `released_at`: the two results feeds' earliest broadcast per quarter, exactly as before review M12 (two requests on
    `client`, unchanged pacing). `filed_at`: the earlier of that and the company's own results filing (review M12), from
    `announcements` when the caller prefetched them (results_filings_by_day) or one paced request over the last
    `announcement_days` when the caller asks (the ingest job: ANNOUNCEMENT_RECENT_DAYS routinely, ANNOUNCEMENT_REPAIR_DAYS
    for the one-off repair). The default (0) makes no announcement request: an unpatched caller (ERN's refresh, an older
    main.py) keeps exactly the two pre-M12 requests, and filed_at is then the feed's time. A filing for a quarter the feeds
    do not carry yet is not returned: nse_results needs the feed's `released_at`, and the evening pass stores the
    quarter once the feed has it."""
    own = client is None
    client = client or httpx.Client(headers=API_HEADERS, timeout=30, follow_redirects=True)
    got = []
    ann: list[Filing] = []
    try:
        for path, extra, ts_key, period_key in FEEDS:
            try:
                r = client.get(f"{API}/{path}", params={"index": "equities", "symbol": symbol, **extra})
                data = r.json() if r.status_code == 200 else []
                got.append((data if isinstance(data, list) else data.get("data", []), ts_key, period_key))
            except (httpx.HTTPError, ValueError):
                got.append(([], ts_key, period_key))
            time.sleep(sleep_s)
    finally:
        if own:
            client.close()
    rel = parse_releases(got, symbol)
    if announcements is not None:
        ann = list(announcements)
    elif with_announcements and announcement_days > 0 and not rel.empty:
        end = today or date.today()  # noqa: DTZ011 — NSE's dd-mm-yyyy window on the local (IST) clock
        start = end - timedelta(days=announcement_days)
        rows = _announcement_rows(paced or _paced(), {"symbol": symbol, "from_date": f"{start:%d-%m-%Y}",
                                                      "to_date": f"{end:%d-%m-%Y}"})
        ann = results_announcements(rows or [])
    return with_filed_times(rel, ann, symbol)


def with_filed_times(rel: pd.DataFrame, ann: list[Filing], symbol: str) -> pd.DataFrame:
    """The feeds' rows with `filed_at` / `filed_source` added; `released_at` is returned untouched (byte for byte)."""
    out = rel.copy()
    out["filed_at"] = pd.to_datetime(out["released_at"]) if len(out) else pd.Series(dtype="datetime64[ns]")
    out["filed_source"] = "feed"
    if out.empty or not ann:
        return out[["symbol", "period_end", "released_at", "filed_at", "filed_source"]]
    rec = reconcile_with_announcements(rel, ann, symbol)
    rec = rec[rec["source"] != "announcement_only"]
    key = {pd.Timestamp(pe).date(): (t, src) for pe, t, src in zip(rec["period_end"], rec["released_at"], rec["source"], strict=True)}
    for i, pe in zip(out.index, out["period_end"], strict=True):
        t, src = key.get(pd.Timestamp(pe).date(), (None, "feed"))
        if t is not None and pd.Timestamp(t) < pd.Timestamp(out.at[i, "filed_at"]):
            out.at[i, "filed_at"], out.at[i, "filed_source"] = pd.Timestamp(t), src
    return out[["symbol", "period_end", "released_at", "filed_at", "filed_source"]]


# ── storage: released_at through the store's own upsert, filed_at in its own column ─────────────────────────────────
FILED_DDL = ("ALTER TABLE nse_results ADD COLUMN IF NOT EXISTS filed_at TIMESTAMP",
             "ALTER TABLE nse_results ADD COLUMN IF NOT EXISTS filed_source VARCHAR")


def ensure_filed_columns(con) -> None:
    """Additive, idempotent: the two review-M12 columns on nse_results (nullable; nothing else reads them)."""
    for ddl in FILED_DDL:
        con.execute(ddl)


def write_filed_times(con, rel: pd.DataFrame) -> int:
    """filed_at = the earliest results-filing time seen for each stored (symbol, period_end); it only moves earlier, like
    released_at's LEAST() upsert. Never touches released_at (alpha_lab's S1 input)."""
    if rel is None or rel.empty or "filed_at" not in rel.columns:
        return 0
    frame = rel.loc[rel["filed_at"].notna(), ["symbol", "period_end", "filed_at", "filed_source"]].copy()
    if frame.empty:
        return 0
    frame["period_end"] = pd.to_datetime(frame["period_end"]).dt.date
    frame["filed_at"] = pd.to_datetime(frame["filed_at"])
    for col in ("symbol", "filed_source"):            # pandas ≥ 3 'str' dtype: DuckDB's scan wants object
        frame[col] = frame[col].astype(object)
    ensure_filed_columns(con)
    con.register("_filed_frame", frame)
    try:
        n = con.execute("""
            UPDATE nse_results AS r SET
                filed_source = CASE WHEN r.filed_at IS NULL OR f.filed_at < r.filed_at THEN f.filed_source ELSE r.filed_source END,
                filed_at = LEAST(COALESCE(r.filed_at, f.filed_at), f.filed_at)
            FROM _filed_frame AS f
            WHERE r.symbol = f.symbol AND r.period_end = f.period_end::DATE
        """).fetchone()
    finally:
        con.unregister("_filed_frame")
    return int(n[0]) if n and n[0] is not None else len(frame)


def store_releases(store, rel: pd.DataFrame) -> int:
    """Store one company's releases: released_at through DuckDBStore.upsert_results exactly as before review M12 (same
    three columns, same LEAST() rule), then filed_at in its own column. Returns the store's row count."""
    if rel is None or rel.empty:
        return 0
    n = store.upsert_results(rel[["symbol", "period_end", "released_at"]])
    if "filed_at" in rel.columns:
        with store.writer() as con:
            write_filed_times(con, rel)
    return n


def release_time_sql(con) -> str:
    """The release-time expression the terminal's readers use: the results filing when stored, else the feed."""
    cols = {r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'nse_results'").fetchall()}
    return "COALESCE(filed_at, released_at)" if "filed_at" in cols else "released_at"


def reaction_pos(released: pd.Timestamp, sessions: pd.DatetimeIndex) -> tuple[int | None, str]:
    """Index in `sessions` of the session that first trades on a release, and the timing label:
    pre-open / market hours (released before 15:30 on a session → that session) or after close (→ next session)."""
    day = released.normalize()
    pos = int(sessions.searchsorted(day, side="left"))              # first session on/after the release day
    in_session = pos < len(sessions) and sessions[pos] == day and (released.hour, released.minute) < MARKET_CLOSE
    timing = ("pre-open" if (released.hour, released.minute) < MARKET_OPEN else "market hours") if in_session else "after close"
    if not in_session and pos < len(sessions) and sessions[pos] == day:
        pos += 1
    return (pos if 0 < pos < len(sessions) else None), timing


def typical_moves(con, symbols: list[str], quarters: int = 8) -> dict[str, dict[str, float]]:
    """Average absolute results-day move over each symbol's last `quarters` releases (raw EQ closes; a reaction of
    more than 40% is treated as an unadjusted split and skipped). For the corporate calendar."""
    if not symbols:
        return {}
    since = (pd.Timestamp.now() - pd.Timedelta(days=3 * 365)).date().isoformat()
    t = release_time_sql(con)                 # review M12: the results filing's time when stored (display only)
    rel = con.execute(f"SELECT symbol, {t} AS released_at FROM nse_results WHERE list_contains(?, symbol) AND {t} >= ?::TIMESTAMP",
                      [symbols, since]).df()
    if rel.empty:
        return {}
    bars = con.execute("""SELECT symbol, date, close FROM nse_bhavcopy WHERE series = 'EQ' AND list_contains(?, symbol)
                          AND date >= ?::DATE ORDER BY symbol, date""", [sorted(rel["symbol"].unique().tolist()), since]).df()
    bars["date"] = pd.to_datetime(bars["date"])
    out: dict[str, dict[str, float]] = {}
    for sym, g in rel.groupby("symbol"):
        b = bars[bars["symbol"] == sym]
        if len(b) < 2:
            continue
        sessions, close = pd.DatetimeIndex(b["date"]), b["close"].to_numpy()
        moves = []
        for ts in sorted(pd.to_datetime(g["released_at"]), reverse=True):
            pos, _ = reaction_pos(pd.Timestamp(ts), sessions)
            if pos is not None and close[pos - 1] > 0:
                m = (close[pos] / close[pos - 1] - 1) * 100
                if abs(m) < 40:
                    moves.append(abs(m))
            if len(moves) >= quarters:
                break
        if moves:
            out[sym] = {"avg_abs_move_pct": round(float(np.mean(moves)), 2), "quarters": len(moves)}
    return out


def reactions(releases: pd.DataFrame, bars: pd.DataFrame, nifty: pd.Series, limit: int = 12) -> list[dict[str, Any]]:
    """`bars`: adjusted daily rows (date, adj_open, adj_close) of the stock; `nifty`: close by date."""
    if releases.empty or bars.empty:
        return []
    b = bars.sort_values("date").set_index("date")
    sessions = b.index
    nifty = nifty.sort_index()
    out = []
    for r in releases.sort_values("released_at", ascending=False).itertuples():
        ts = pd.Timestamp(r.released_at)
        pos, timing = reaction_pos(ts, sessions)
        if pos is None:
            continue
        before, react = sessions[pos - 1], sessions[pos]
        c0, c1, o1 = b["adj_close"].iloc[pos - 1], b["adj_close"].iloc[pos], b["adj_open"].iloc[pos]
        move = (c1 / c0 - 1) * 100
        n0, n1 = nifty.asof(before), nifty.asof(react)
        idx = (n1 / n0 - 1) * 100 if pd.notna(n0) and pd.notna(n1) and n0 else None
        out.append({"period_end": pd.Timestamp(r.period_end).strftime("%Y-%m-%d"), "released_at": ts.strftime("%Y-%m-%d %H:%M"),
                    "timing": timing, "reaction_date": react.strftime("%Y-%m-%d"),
                    "move_pct": round(float(move), 2), "gap_pct": round(float((o1 / c0 - 1) * 100), 2),
                    "vs_nifty_pct": round(float(move - idx), 2) if idx is not None else None})
        if len(out) >= limit:
            break
    return out


def summary(rx: list[dict[str, Any]]) -> dict[str, Any]:
    if not rx:
        return {"quarters": 0}
    mv = pd.Series([r["move_pct"] for r in rx])
    ex = pd.Series([r["vs_nifty_pct"] for r in rx if r["vs_nifty_pct"] is not None])
    return {"quarters": len(rx), "avg_abs_move_pct": round(float(mv.abs().mean()), 2),
            "median_abs_move_pct": round(float(mv.abs().median()), 2), "up_pct": round(float((mv > 0).mean() * 100), 0),
            "biggest_up_pct": round(float(mv.max()), 2), "biggest_down_pct": round(float(mv.min()), 2),
            "avg_abs_vs_nifty_pct": round(float(ex.abs().mean()), 2) if len(ex) else None}


def recent_reactions(con, days: int = 10, min_turnover_cr: float = 5.0) -> list[dict[str, Any]]:
    """Results released in the last `days` and how each stock reacted on its reaction session (raw EQ closes; NIFTY 50
    for context), with the stock's typical results move for comparison. Releases whose reaction session has not
    traded yet are listed with move None ("pending")."""
    since = (pd.Timestamp.now().normalize() - pd.Timedelta(days=days)).isoformat()
    t = release_time_sql(con)                 # review M12: the results filing's time when stored (EVTS, wrap, implied moves)
    rel = con.execute(f"SELECT symbol, period_end, {t} AS released_at, released_at AS feed_released_at FROM nse_results WHERE {t} >= ?::TIMESTAMP "
                      f"ORDER BY {t} DESC", [since]).df()
    if rel.empty:
        return []
    syms = sorted(rel["symbol"].unique().tolist())
    start = (pd.Timestamp(since) - pd.Timedelta(days=40)).date().isoformat()
    bars = con.execute("""SELECT symbol, date, close, turnover_lacs FROM nse_bhavcopy WHERE series = 'EQ'
                          AND list_contains(?, symbol) AND date >= ?::DATE ORDER BY symbol, date""", [syms, start]).df()
    bars["date"] = pd.to_datetime(bars["date"])
    n50 = con.execute("SELECT date, close FROM market_index_daily WHERE symbol = 'NIFTY50' AND date >= ?::DATE ORDER BY date",
                      [start]).df()
    nifty = pd.Series(n50["close"].to_numpy(dtype=float), index=pd.to_datetime(n50["date"]))
    all_sessions = pd.DatetimeIndex(sorted(bars["date"].unique()))
    typical = typical_moves(con, syms)
    out = []
    for r in rel.itertuples():
        b = bars[bars["symbol"] == r.symbol]
        if b.empty:
            continue
        med_to = float(b["turnover_lacs"].tail(20).median()) / 100
        if med_to < min_turnover_cr:
            continue
        ts = pd.Timestamp(r.released_at)
        pos, timing = reaction_pos(ts, all_sessions)
        feed_ts = pd.Timestamp(r.feed_released_at)
        row: dict[str, Any] = {"symbol": r.symbol, "period_end": pd.Timestamp(r.period_end).strftime("%Y-%m-%d"),
                               "released_at": ts.strftime("%Y-%m-%d %H:%M"), "timing": timing, "turnover_cr": round(med_to, 1),
                               "feed_released_at": feed_ts.strftime("%Y-%m-%d %H:%M"),
                               "time_source": "filing" if ts < feed_ts else "feed",
                               "reaction_date": None, "move_pct": None, "vs_nifty_pct": None, "sessions_since": None, "avoid": False,
                               "typical_move_pct": typical.get(r.symbol, {}).get("avg_abs_move_pct")}
        if pos is not None:
            d0, d1 = all_sessions[pos - 1], all_sessions[pos]
            px = b.set_index("date")["close"]
            if d0 in px.index and d1 in px.index and px[d0] > 0:
                move = (px[d1] / px[d0] - 1) * 100
                if abs(move) < 40:
                    n0, n1 = nifty.asof(d0), nifty.asof(d1)
                    vs = round(float(move - (n1 / n0 - 1) * 100), 2) if pd.notna(n0) and pd.notna(n1) else None
                    since = len(all_sessions) - 1 - pos
                    # reports/results_drift: after a ≤ −5% excess reaction, stocks lagged for ~60 sessions (H2 PASS)
                    row.update(reaction_date=d1.strftime("%Y-%m-%d"), move_pct=round(float(move), 2), vs_nifty_pct=vs,
                               sessions_since=since, avoid=bool(vs is not None and vs <= AVOID_REACTION_PCT and since <= AVOID_SESSIONS))
        out.append(row)
    return out


def display_releases(store, symbol: str) -> pd.DataFrame:
    """One company's releases for the ERN / DES table: (symbol, period_end, released_at) where released_at is the
    results filing's time when stored (review M12), else the feed's. Display only; never written back."""
    with store.reader() as con:
        t = release_time_sql(con)
        return con.execute(f"SELECT symbol, period_end, {t} AS released_at FROM nse_results WHERE symbol = ? ORDER BY {t}",
                           [symbol]).df()
