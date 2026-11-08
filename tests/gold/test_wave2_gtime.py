"""Wave 2, lane G-TIME (8 Nov 2026) — point-in-time correctness of the Yahoo daily store. Every rule has a negative
control that fails on the old behaviour.

C-DATA-02  No stored bar may carry a trade_date after the session it describes. Yahoo opens the next exchange-local
           bucket as soon as the date turns and fills it with the only print there is — Friday's last quote — so the
           Sunday-morning IST catch-up stored USD/INR 93.91 under Mon 09 Nov (age_days −1, "as of Mon 09 Nov" on a
           Sunday). The FX day rolls at 17:00 America/New_York, so Friday 17:00 → Sunday's open belongs to FRIDAY.
           Second half of the same finding: Yahoo's COMPLETED FX bar closes at its own open (the 00:00 London snapshot,
           ≈ 2 h after the roll that STARTS the session), so every stored FX "close" dated D was really D−1's close;
           the session close of D is D+1's opening snapshot, or the quote feed's own last print for D.
C-DATA-05  A bar fetched before its session closed (``is_partial``) must be re-fetched until it is final: a catch-up's
           ``backfill_from`` used to REPLACE the routine 5-day look-back, so the run that resumed from the day after
           GC=F's partial Thu 05 Nov bar never re-read it (close 4,098.4 mid-session against the final 4,113.5, and
           Friday's change computed off it). ``period1`` now only ever widens.
"""
from __future__ import annotations

# ruff: noqa: DTZ001
# (timestamps are UTC-naive by the store's convention)
import json
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
import pytest
from _support import FakeHttp, FakeResponse
from gold import db, ingest_yahoo, pit, reads

MON, TUE, WED, THU, FRI, SUN, NEXT_MON = (date(2026, 11, d) for d in (2, 3, 4, 5, 6, 8, 9))
SUNDAY_1017_IST = datetime(2026, 11, 8, 4, 47)          # the catch-up instant that stored the Monday-dated FX rows
LONDON, NY = "Europe/London", "America/New_York"


def _epoch(ts: str, tz: str) -> int:
    return int(pd.Timestamp(ts, tz=tz).timestamp())


def _chart(symbol: str, tz: str, rows: list[tuple[str, float, float, float, float]], *, anchor: str | None = None,
           quote: tuple[str, float] | None = None, volume: list[int] | None = None) -> dict[str, Any]:
    """A Yahoo 1d chart body: ``rows`` are (ISO stamp in ``tz``, o, h, l, c); ``anchor`` is
    ``currentTradingPeriod.regular.start`` (the time-of-day a COMPLETED bar is stamped with); ``quote`` is
    (``regularMarketTime`` in ``tz``, ``regularMarketPrice``)."""
    meta: dict[str, Any] = {"symbol": symbol, "exchangeTimezoneName": tz, "dataGranularity": "1d"}
    if anchor:
        meta["currentTradingPeriod"] = {"regular": {"start": _epoch(anchor, tz)}}
    if quote:
        meta["regularMarketTime"], meta["regularMarketPrice"] = _epoch(quote[0], tz), quote[1]
    q = {k: [r[i + 1] for r in rows] for i, k in enumerate(("open", "high", "low", "close"))}
    q["volume"] = volume or [0] * len(rows)
    return {"chart": {"result": [{"meta": meta, "timestamp": [_epoch(r[0], tz) for r in rows],
                                  "indicators": {"quote": [q]}}]}}


# the week Yahoo publishes for INR=X: every completed bar closes at its OWN open (the 00:00 London snapshot)
FX_WEEK: list[tuple[str, float, float, float, float]] = [
    ("2026-11-02 00:00", 94.9897, 95.0236, 94.6520, 94.9897),
    ("2026-11-03 00:00", 94.7254, 94.8985, 94.5635, 94.7254),
    ("2026-11-04 00:00", 94.7484, 94.8709, 94.2855, 94.7484),
    ("2026-11-05 00:00", 94.5300, 94.5650, 94.3100, 94.5300),
    ("2026-11-06 00:00", 94.4589, 94.5178, 93.8308, 94.4589),
]
WEEKEND_BUCKET = ("2026-11-08 00:00", 93.91, 93.91, 93.91, 93.91)          # Sunday-stamped, holding Friday's last print


def _bar(sym: str, d: date, o: float, h: float, lo: float, c: float, seen: datetime, *, vendor: float | None = None,
         volume: int = 0) -> dict[str, Any]:
    return {"trade_date": d, "symbol": sym, "open": o, "high": h, "low": lo, "close": c,
            "adj_close": c if vendor is None else vendor, "volume": volume, "source": "yahoo", "first_seen_at": seen}


# ── C-DATA-02 (1): the weekend bucket is Friday's, never next Monday ─────────────────────────────────────────────

def test_the_weekend_fx_bucket_is_friday_and_keeps_fridays_own_range():
    body = _chart("INR=X", LONDON, [*FX_WEEK, WEEKEND_BUCKET], anchor="2026-11-06 00:00",
                  quote=("2026-11-06 11:15", 93.91))
    meta, bars = ingest_yahoo.parse_chart(body, expect_interval="1d")
    out = ingest_yahoo.daily_bars_frame(meta, bars, "INR=X", now=SUNDAY_1017_IST)
    days = [db.to_date(d) for d in out["trade_date"]]
    assert NEXT_MON not in days and SUN not in days and max(days) == FRI          # the defect: a 2026-11-09 row
    fri = out[out["trade_date"] == FRI].iloc[0]
    # Friday's real open / high / low survive the merge and its close is the week's last print, not the 00:00 snapshot
    assert (fri["open"], fri["high"], fri["low"], fri["close"]) == (94.4589, 94.5178, 93.8308, 93.91)
    assert fri["adj_close"] == 94.4589                                            # the vendor's own number is kept
    assert len(out) == 5

    # negative control: the same body once the FX week has OPENED (the bucket is stamped Monday in London and the quote
    # is Sunday 17:30 New York, past the 17:00 roll) — then a Monday row is right, and Friday's close is Monday's open
    opened = _chart("INR=X", LONDON, [*FX_WEEK, ("2026-11-09 00:00", 93.95, 93.99, 93.94, 93.98)],
                    anchor="2026-11-06 00:00", quote=("2026-11-08 22:30", 93.98))
    m2, b2 = ingest_yahoo.parse_chart(opened, expect_interval="1d")
    out2 = ingest_yahoo.daily_bars_frame(m2, b2, "INR=X", now=datetime(2026, 11, 8, 22, 35))
    rows2 = {db.to_date(d): r for d, r in zip(out2["trade_date"], out2.to_dict(orient="records"), strict=True)}
    assert set(rows2) == {MON, TUE, WED, THU, FRI, NEXT_MON}
    assert rows2[NEXT_MON]["close"] == 93.98 and rows2[FRI]["close"] == 93.95     # Friday ends at Monday's open snapshot


def test_quote_session_date_rolls_at_1700_new_york_and_never_crosses_the_weekend_gap():
    q = ingest_yahoo.quote_session_date
    assert q("INR=X", pd.Timestamp("2026-11-06 16:00", tz=NY)) == FRI             # inside Friday's session
    assert q("INR=X", pd.Timestamp("2026-11-06 17:00", tz=NY)) == FRI             # the roll instant is Friday's close
    assert q("INR=X", pd.Timestamp("2026-11-07 19:00", tz=NY)) == FRI             # Saturday evening: still Friday's print
    assert q("INR=X", pd.Timestamp("2026-11-08 12:00", tz=NY)) == FRI             # Sunday, before the 17:00 FX open
    assert q("GC=F", pd.Timestamp("2026-11-08 17:30", tz=NY)) == FRI              # Globex opens 18:00, not 17:00
    # … and the Sunday-evening opens really do start the new week (the rule is not "always the previous Friday")
    assert q("INR=X", pd.Timestamp("2026-11-08 17:30", tz=NY)) == NEXT_MON
    assert q("GC=F", pd.Timestamp("2026-11-08 18:19", tz=NY)) == NEXT_MON
    assert q("GC=F", pd.Timestamp("2026-11-05 16:40", tz=NY)) == THU              # the 03:10 IST fetch, 20 min early
    assert q("GC=F", pd.Timestamp("2026-11-05 18:10", tz=NY)) == FRI              # past the roll: the next trade date
    # cash sessions have no overnight session: a weekend quote is Friday's close, a weekday quote its own day
    assert q("GLD", pd.Timestamp("2026-11-07 10:00", tz=NY)) == FRI
    assert q("GLD", pd.Timestamp("2026-11-05 18:00", tz=NY)) == THU
    assert q("GOLDBEES.NS", pd.Timestamp("2026-11-07 10:00", tz="Asia/Kolkata")) == FRI
    # … and an NSE name is dated by the NSE day, not by New York's. GOLDBEES trades 09:15–15:30 IST = 22:45–05:00 the
    # PREVIOUS day in New York, so for the whole first half of every IST session the New York date is yesterday's:
    # round 1 returned Friday here, i.e. a session that had settled two IST days earlier (round-2 major 1)
    assert q("GOLDBEES.NS", pd.Timestamp("2026-11-09 10:00", tz="Asia/Kolkata")) == NEXT_MON
    assert q("GOLDBEES.NS", pd.Timestamp("2026-11-10 10:00", tz="Asia/Kolkata")) == date(2026, 11, 10)


def test_the_quote_clock_and_the_session_clock_agree():
    """``quote_session_date`` (which session a quote belongs to) and ``session_close_utc`` (when that session is final)
    must read ONE clock — ``session_clock``. The invariant: a quote may only be dated to a session that was still open
    at some instant during the quote's own exchange-local day. Round 1 dated a cash quote by the New York day while the
    close was measured in Asia/Kolkata, so a live Monday-morning GOLDBEES.NS bar was given Friday's settled session."""
    for sym in ("GC=F", "INR=X", "DX-Y.NYB", "GCZ26.CMX", "GLD", "^VIX", "GOLDBEES.NS"):
        zone = ingest_yahoo.session_clock(sym)[0]
        assert ingest_yahoo.session_close_utc(sym, FRI).date() in (FRI, date(2026, 11, 7))   # the clock is one function
        for hours in range(24 * 5):                        # every hour Fri 00:00 → Tue 23:00, exchange-local
            t = pd.Timestamp("2026-11-06 00:00", tz=zone) + pd.Timedelta(hours=hours)
            if t.weekday() >= 5 and not ingest_yahoo.special_session_day(t.date(), sym):
                continue                                   # the weekend gap: the only quote there is Friday's last
            d = ingest_yahoo.quote_session_date(sym, t)
            day_start = t.normalize().tz_convert("UTC").tz_localize(None)
            assert ingest_yahoo.session_close_utc(sym, d) >= day_start, (sym, str(t), d)

    # the two instants the round-2 brief names, spelled out
    q, fri_eve, sun_eve = ingest_yahoo.quote_session_date, pd.Timestamp("2026-11-06 18:00", tz=NY), pd.Timestamp("2026-11-08 18:30", tz=NY)
    assert q("GC=F", fri_eve) == FRI and q("INR=X", fri_eve) == FRI and q("GLD", fri_eve) == FRI
    assert q("GOLDBEES.NS", fri_eve) == FRI                # Sat 04:30 IST: Friday's close is the last print there is
    assert q("GC=F", sun_eve) == NEXT_MON and q("INR=X", sun_eve) == NEXT_MON      # the week has opened
    assert q("GOLDBEES.NS", sun_eve) == NEXT_MON           # Mon 05:00 IST: Monday's own session, still ahead (partial)
    assert q("GLD", sun_eve) == FRI                        # US cash has no Sunday session at all


def test_a_live_cash_bar_is_not_folded_into_a_settled_session():
    """The write-side half of the same defect: dating Monday's live GOLDBEES.NS bar by the New York day put it on
    Friday, and because Friday's 15:30 IST close had long passed the row was stored as a settled ``close`` — a value
    from another session, under a date no read-time clamp can question. Round 1 stored [THU, FRI] with Friday at 95.8."""
    body = _chart("GOLDBEES.NS", "Asia/Kolkata",
                  [("2026-11-05 09:15", 92.0, 92.6, 91.8, 92.4), ("2026-11-06 09:15", 92.5, 93.1, 92.3, 92.9),
                   ("2026-11-09 10:05", 93.0, 95.9, 92.9, 95.8)], anchor="2026-11-06 09:15",
                  quote=("2026-11-09 10:05", 95.8))
    meta, bars = ingest_yahoo.parse_chart(body, expect_interval="1d")
    out = ingest_yahoo.daily_bars_frame(meta, bars, "GOLDBEES.NS", now=datetime(2026, 11, 9, 4, 35))   # Mon 10:05 IST
    rows = {db.to_date(d): r for d, r in zip(out["trade_date"], out.to_dict(orient="records"), strict=True)}
    assert set(rows) == {THU, FRI, NEXT_MON}
    assert rows[FRI]["close"] == 92.9 and rows[NEXT_MON]["close"] == 95.8
    # and Monday's own row is the session in progress, never a close
    assert ingest_yahoo.is_partial("GOLDBEES.NS", NEXT_MON, rows[NEXT_MON]["first_seen_at"]) is True
    assert ingest_yahoo.is_partial("GOLDBEES.NS", FRI, rows[FRI]["first_seen_at"]) is False


def test_a_future_dated_row_is_never_written_whatever_the_body_says():
    # a body whose trailing bucket is stamped a WEEK ahead (a vendor glitch): the row is dropped, the rest is kept
    body = _chart("GC=F", NY, [("2026-11-05 00:00", 4075.4, 4155.8, 4067.0, 4113.5),
                               ("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9),
                               ("2026-11-16 00:00", 4080.0, 4090.0, 4070.0, 4085.0)], anchor="2026-11-06 00:00")
    meta, bars = ingest_yahoo.parse_chart(body, expect_interval="1d")
    out = ingest_yahoo.daily_bars_frame(meta, bars, "GC=F", now=SUNDAY_1017_IST)
    assert [db.to_date(d) for d in out["trade_date"]] == [THU, FRI]
    # negative control: the Globex week opens on Sunday evening New York, which is already Monday in IST — a real
    # in-progress Monday bar is NOT a future row
    live = _chart("GC=F", NY, [("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9),
                               ("2026-11-08 18:19", 4080.0, 4082.0, 4078.0, 4081.2)], anchor="2026-11-06 00:00")
    m2, b2 = ingest_yahoo.parse_chart(live, expect_interval="1d")
    out2 = ingest_yahoo.daily_bars_frame(m2, b2, "GC=F", now=datetime(2026, 11, 8, 23, 25))   # Mon 04:55 IST
    assert [db.to_date(d) for d in out2["trade_date"]] == [FRI, NEXT_MON]


@pytest.mark.parametrize("sym", ["GC=F", "SI=F", "DX-Y.NYB", "GCZ26.CMX"])
def test_a_post_session_print_may_not_touch_a_settled_session(sym):
    """Round-2 major 2. A trailing bucket re-dated onto a session that has ALREADY SETTLED is dropped, not merged:
    Yahoo's final futures close is the 13:30 ET settlement print while the session's last trade is a different number,
    so merging would replace a settlement with a late trade and store it as a ``close`` — and ``high: max`` /
    ``low: min`` would widen a closed session's range with a print from outside it. DX-Y.NYB matters on its own: MACRO
    and HEALTH print it beside the FX legs as the sign check for the dollar."""
    settled = [("2026-11-05 00:00", 4075.4, 4155.8, 4067.0, 4113.5), ("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9)]
    body = _chart(sym, NY, [*settled, ("2026-11-08 00:00", 4150.0, 4150.0, 4000.0, 4046.2)], anchor="2026-11-06 00:00",
                  quote=("2026-11-08 12:00", 4046.2))
    meta, bars = ingest_yahoo.parse_chart(body, expect_interval="1d")
    out = ingest_yahoo.daily_bars_frame(meta, bars, sym, now=SUNDAY_1017_IST)
    assert [db.to_date(d) for d in out["trade_date"]] == [THU, FRI]
    assert list(out["close"]) == [4113.5, 4074.9] and list(out["adj_close"]) == [4113.5, 4074.9]
    assert list(out["high"]) == [4155.8, 4116.2] and list(out["low"]) == [4067.0, 4035.1]

    # deliberate scope: a bucket that is the ONLY thing the body says about that settled session is still kept —
    # there is nothing better to serve, and it cannot overwrite a settlement either, because a session the store
    # already holds settled is inside the fetch window and so comes back with its own anchored bar (the end-to-end
    # store test below is that path). It is dated Friday, not next Monday.
    lone = _chart(sym, NY, [("2026-11-08 00:00", 4046.2, 4046.2, 4046.2, 4046.2)], anchor="2026-11-06 00:00",
                  quote=("2026-11-08 12:00", 4046.2))
    m2, b2 = ingest_yahoo.parse_chart(lone, expect_interval="1d")
    out2 = ingest_yahoo.daily_bars_frame(m2, b2, sym, now=SUNDAY_1017_IST)
    assert [db.to_date(d) for d in out2["trade_date"]] == [FRI] and out2["close"].iloc[0] == 4046.2

    # negative control: the merge is still there while the session is OPEN — Yahoo's anchored in-progress Monday bar
    # plus a later off-anchor print of that same Monday session: the fresher close wins and the range is the union
    live = _chart(sym, NY, [("2026-11-09 00:00", 4080.0, 4082.0, 4078.0, 4081.0),
                            ("2026-11-09 11:30", 4081.0, 4090.0, 4079.0, 4088.0)], anchor="2026-11-09 00:00",
                  quote=("2026-11-09 11:30", 4088.0))
    m3, b3 = ingest_yahoo.parse_chart(live, expect_interval="1d")
    out3 = ingest_yahoo.daily_bars_frame(m3, b3, sym, now=datetime(2026, 11, 9, 16, 35))      # Mon 11:35 ET, still open
    assert len(out3) == 1 and db.to_date(out3["trade_date"].iloc[0]) == NEXT_MON
    assert (out3["close"].iloc[0], out3["high"].iloc[0], out3["open"].iloc[0]) == (4088.0, 4090.0, 4080.0)


def test_a_weekend_fetch_cannot_overwrite_a_settled_close_in_the_store(store):
    """The same rule end to end: a settled bar already in the store survives a weekend fetch byte for byte, and the
    weekend bucket adds no row of its own. A corrupted close here is unrecoverable — ``gold_daily_bars`` keeps one row
    per (trade_date, symbol, source) and the reads have no way to tell a settlement from a late trade."""
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("GC=F", FRI, 4098.5, 4116.2, 4035.1, 4074.9, datetime(2026, 11, 6, 22, 30), volume=215643)]))
    body = _chart("GC=F", NY, [("2026-11-05 00:00", 4075.4, 4155.8, 4067.0, 4113.5),
                               ("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9),
                               ("2026-11-08 00:00", 4046.2, 4046.2, 4046.2, 4046.2)], anchor="2026-11-06 00:00",
                  quote=("2026-11-08 12:00", 4046.2), volume=[215643, 198000, 1200])
    http = FakeHttp({"chart/GC=F": FakeResponse(200, json.dumps(body))})
    ingest_yahoo.fetch_daily(store, http, symbols=["GC=F"], now=SUNDAY_1017_IST)
    row = db.query_df(store, "SELECT * FROM gold_daily_bars WHERE symbol = 'GC=F' AND trade_date = ?", [FRI]).iloc[0]
    assert row.close == 4074.9 and row.adj_close == 4074.9 and row.high == 4116.2
    assert db.scalar(store, "SELECT COUNT(*) FROM gold_daily_bars WHERE symbol = 'GC=F' AND trade_date > ?", [FRI]) == 0


# ── C-DATA-02 (2): an FX close is the session's close, not its opening snapshot ──────────────────────────────────

def test_a_weekend_stamped_bucket_is_fridays_even_once_ist_has_turned_monday():
    """The reachable case the future-row guard does NOT cover: a start-up catch-up at 03:40 IST Monday runs at 17:10
    Sunday New York, before Globex opens at 18:00, so Yahoo's Sunday-stamped bucket still holds Friday's last print
    while the IST day is already Monday. ``session_date`` dated it Monday — a session that had not begun."""
    body = _chart("GC=F", NY, [("2026-11-05 00:00", 4075.4, 4155.8, 4067.0, 4113.5),
                               ("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9),
                               ("2026-11-08 00:00", 4046.2, 4046.2, 4046.2, 4046.2)], anchor="2026-11-06 00:00",
                  quote=("2026-11-08 17:10", 4046.2))
    meta, bars = ingest_yahoo.parse_chart(body, expect_interval="1d")
    out = ingest_yahoo.daily_bars_frame(meta, bars, "GC=F", now=datetime(2026, 11, 8, 22, 10))     # Mon 03:40 IST
    assert [db.to_date(d) for d in out["trade_date"]] == [THU, FRI]
    # the bucket holds Friday's 17:00 ET Globex LAST (4,046.2), which is NOT Friday's settlement (4,074.9): the dated
    # row is Friday's but the settled session keeps every one of its own numbers (round-2 major 2 / minor 3 — round 1
    # used the bucket's close, and the old test could not see it because the two numbers were equal)
    assert out["close"].iloc[-1] == 4074.9 and out["adj_close"].iloc[-1] == 4074.9
    assert (out["open"].iloc[-1], out["high"].iloc[-1], out["low"].iloc[-1]) == (4098.5, 4116.2, 4035.1)
    # negative control: half an hour later the week HAS opened (18:19 New York) and the bucket is Monday's own session
    opened = _chart("GC=F", NY, [("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9),
                                 ("2026-11-08 18:19", 4076.0, 4081.0, 4075.0, 4080.0)], anchor="2026-11-06 00:00",
                    quote=("2026-11-08 18:19", 4080.0))
    m2, b2 = ingest_yahoo.parse_chart(opened, expect_interval="1d")
    out2 = ingest_yahoo.daily_bars_frame(m2, b2, "GC=F", now=datetime(2026, 11, 8, 23, 25))        # Mon 04:55 IST
    assert [db.to_date(d) for d in out2["trade_date"]] == [FRI, NEXT_MON]


def test_an_fx_close_is_the_next_sessions_opening_snapshot_and_futures_are_left_alone():
    body = _chart("INR=X", LONDON, FX_WEEK, anchor="2026-11-06 00:00", quote=("2026-11-06 11:15", 93.91))
    meta, bars = ingest_yahoo.parse_chart(body, expect_interval="1d")
    out = ingest_yahoo.daily_bars_frame(meta, bars, "INR=X", now=SUNDAY_1017_IST)
    rows = {db.to_date(d): r for d, r in zip(out["trade_date"], out.to_dict(orient="records"), strict=True)}
    for i, (d, nxt) in enumerate(((MON, TUE), (TUE, WED), (WED, THU), (THU, FRI))):
        assert rows[d]["close"] == rows[nxt]["open"], d                           # the session's own close
        assert rows[d]["adj_close"] == FX_WEEK[i][4]                              # Yahoo's number, kept for audit
        assert rows[d]["close"] != rows[d]["open"] or FX_WEEK[i][1] == FX_WEEK[i + 1][1]
    assert rows[FRI]["close"] == 93.91 and rows[FRI]["adj_close"] == 94.4589       # the quote feed's last print for Friday
    assert rows[THU]["low"] <= rows[THU]["close"] <= rows[THU]["high"]            # the rebuilt close stays inside the range

    # negative control: a futures symbol is untouched — Yahoo's futures close IS the settlement-time print
    fut = _chart("GC=F", NY, [("2026-11-05 00:00", 4075.4, 4155.8, 4067.0, 4113.5),
                              ("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9)], anchor="2026-11-06 00:00")
    m2, b2 = ingest_yahoo.parse_chart(fut, expect_interval="1d")
    out2 = ingest_yahoo.daily_bars_frame(m2, b2, "GC=F", now=SUNDAY_1017_IST)
    assert list(out2["close"]) == [4113.5, 4074.9] and list(out2["adj_close"]) == [4113.5, 4074.9]


def test_the_csv_seeds_follow_the_same_fx_rule(now):
    text = "date,open,high,low,close,volume\n" + "".join(
        f"{r[0][:10]},{r[1]},{r[2]},{r[3]},{r[4]},0\n" for r in FX_WEEK)
    df = ingest_yahoo.parse_daily_csv(text, "INR=X", now=datetime(2026, 11, 7, 5, 0))
    rows = {db.to_date(d): r for d, r in zip(df["trade_date"], df.to_dict(orient="records"), strict=True)}
    assert rows[WED]["close"] == 94.5300 and rows[WED]["adj_close"] == 94.7484     # Wednesday ends at Thursday's snapshot
    assert rows[FRI]["close"] == 94.4589                                           # no successor, no quote: the vendor's
    # negative control: a non-FX seed keeps every close exactly as published
    text2 = "date,open,high,low,close,volume\n2026-11-05,4075.4,4155.8,4067.0,4113.5,215643\n"
    df2 = ingest_yahoo.parse_daily_csv(text2, "GC=F", now=datetime(2026, 11, 7, 5, 0))
    assert df2["close"].iloc[0] == 4113.5 and df2["adj_close"].iloc[0] == 4113.5


# ── C-DATA-02 (3): the reads never serve a session dated after the reader's own IST day ──────────────────────────

def _seed_fx(store: Any) -> None:
    seen = datetime(2026, 11, 8, 4, 47)
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("INR=X", WED, 94.7484, 94.8709, 94.2855, 94.5300, seen, vendor=94.7484),       # rebuilt: close != vendor
        _bar("INR=X", THU, 94.5300, 94.5650, 94.3100, 94.5300, seen),                       # legacy: close == vendor
        _bar("INR=X", FRI, 94.4589, 94.5178, 93.8308, 93.9100, seen, vendor=94.4589),
        _bar("INR=X", NEXT_MON, 93.91, 93.91, 93.91, 93.91, seen),                          # the future-dated row
    ]))


def test_series_drops_a_future_dated_point_and_reports_it(store):
    _seed_fx(store)
    reads.invalidate_catalog_cache()
    s = reads.series(store, ["USDINR_CLOSE"], start=MON, asof=SUNDAY_1017_IST)["series"][0]
    assert [p["report_date"] for p in s["points"]] == ["2026-11-04", "2026-11-05", "2026-11-06"]
    assert s["future_points_dropped"] == 1 and s["age_days"] == 2 and s["points"][-1]["value"] == 93.91
    # the clock a close was read on is named: rebuilt vs Yahoo's own completed-bar close (its OPENING snapshot)
    qual = reads._table_backed(store, "USDINR_CLOSE", start=MON, end=None, asof=SUNDAY_1017_IST)
    assert list(qual["quality"]) == ["close", "open_snapshot", "close"]
    # negative control: a session dated the reader's own IST day is served, with age 0 — the clamp is today, not yesterday
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("INR=X", SUN, 93.95, 93.99, 93.90, 93.96, datetime(2026, 11, 8, 4, 47), vendor=93.95)]))
    s2 = reads.series(store, ["USDINR_CLOSE"], start=MON, asof=SUNDAY_1017_IST)["series"][0]
    assert s2["points"][-1]["report_date"] == "2026-11-08" and s2["age_days"] == 0 and s2["future_points_dropped"] == 1


def test_bars_does_not_serve_a_future_dated_bar(store):
    _seed_fx(store)
    out = reads.bars(store, symbol="INR=X", start=MON)
    assert [r["trade_date"] for r in out["rows"]] == ["2026-11-04", "2026-11-05", "2026-11-06"]
    assert out["future_rows_dropped"] == 1
    # negative control: a futures symbol with no future row reports none and serves every bar
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("GC=F", FRI, 4098.5, 4116.2, 4035.1, 4074.9, datetime(2026, 11, 8, 4, 47))]))
    gc = reads.bars(store, symbol="GC=F", start=MON)
    assert gc["future_rows_dropped"] == 0 and len(gc["rows"]) == 1
    # … and the counter means the rows THIS read asked for: a window that ended before today never asked for them
    past = reads.bars(store, symbol="INR=X", start=date(2026, 1, 1), end=date(2026, 6, 30))
    assert past["count"] == 0 and past["future_rows_dropped"] == 0


def test_an_fx_close_equal_to_the_vendors_is_not_claimed_as_a_session_close():
    """The ``open_snapshot`` label is INFERRED from close vs adj_close, not recorded, so it is pinned to UNDER-claim:
    an FX close that equals Yahoo's own number — a legacy row, a flat session, or a missing vendor number — is read as
    the opening snapshot, never announced as a session close. Recording it needs a ``close_source`` column (patch
    request against gold/schema.py)."""
    settled = datetime(2026, 11, 6, 22, 30)
    assert reads._bar_quality("INR=X", FRI, settled, 94.53, 94.4589) == "close"          # rebuilt: a different number
    assert reads._bar_quality("INR=X", FRI, settled, 94.53, 94.53) == "open_snapshot"    # equal: cannot tell, so no claim
    assert reads._bar_quality("INR=X", FRI, settled, 94.53, None) == "open_snapshot"     # nothing recorded the clock
    assert reads._bar_quality("GC=F", FRI, settled, 4074.9, 4074.9) == "close"           # a futures close IS the settlement
    assert reads._bar_quality("GC=F", FRI, THU_PARTIAL_SEEN, 4074.9, 4074.9) == "partial"


def test_a_daily_derived_series_cannot_carry_a_future_report_date(store):
    asof = SUNDAY_1017_IST
    pit.upsert_series(store, pit.series_frame("MCX_BASIS_PCT", [(FRI, 0.89), (NEXT_MON, 1.21)], freq="D",
                                             source="derived", quality="derived_vwap30", now=asof), now=asof)
    reads.invalidate_catalog_cache()
    s = reads.series(store, ["MCX_BASIS_PCT"], start=MON, asof=asof)["series"][0]
    assert [p["report_date"] for p in s["points"]] == ["2026-11-06"] and s["future_points_dropped"] == 1
    # negative control (deliberate scope): a MONTHLY series is dated by its period, not by a session clock, so the
    # future-session guard does not touch it
    pit.upsert_series(store, pit.series_frame("INDIA_GOLD_IMPORTS_USD_BN", [(date(2026, 12, 1), 4.2)], freq="M",
                                             source="pib_manual", now=asof), now=asof)
    m = reads.series(store, ["INDIA_GOLD_IMPORTS_USD_BN"], start=MON, asof=asof)["series"][0]
    assert [p["report_date"] for p in m["points"]] == ["2026-12-01"] and m["future_points_dropped"] == 0


def test_age_is_counted_in_ist_days_and_is_never_negative(store):
    _seed_fx(store)                                                     # bars to Fri 06 Nov, plus a 2026-11-09 row
    reads.invalidate_catalog_cache()
    # 01:30 IST on Mon 09 Nov (20:00 UTC on the 8th): the Monday session has started in IST, so its own in-progress bar
    # is the last point and its age is 0 — an age measured on the UTC calendar would read −1
    late = datetime(2026, 11, 8, 20, 0)
    s = reads.series(store, ["USDINR_CLOSE"], start=MON, asof=late)["series"][0]
    assert s["points"][-1]["report_date"] == "2026-11-09" and s["age_days"] == 0
    assert s["points"][-1]["partial"] is True and s["future_points_dropped"] == 0
    # negative control: read on Sunday the same row is in the future, is dropped, and the age is the real IST gap
    early = reads.series(store, ["USDINR_CLOSE"], start=MON, asof=SUNDAY_1017_IST)["series"][0]
    assert early["points"][-1]["report_date"] == "2026-11-06" and early["age_days"] == 2


def test_a_future_dated_twin_is_not_fresher(store):
    asof = SUNDAY_1017_IST
    _seed_fx(store)                                                     # USDINR_CLOSE has a 2026-11-09 bar
    pit.upsert_series(store, pit.series_frame("USDINR_FBIL", [(FRI, 94.40)], freq="D", source="rbi_ref",
                                             release_kind="rbi_ref", now=asof), now=asof)
    reads.invalidate_catalog_cache()
    s = {x["series_id"]: x for x in reads.series(store, ["USDINR_FBIL", "USDINR_CLOSE"], start=MON, asof=asof)["series"]}
    assert s["USDINR_FBIL"]["fresher_twin"] is None                     # the 11-09 bar must not read as "one day ahead"
    # negative control: a twin point dated TODAY is fresher and is reported
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("INR=X", SUN, 93.95, 93.99, 93.90, 93.96, datetime(2026, 11, 8, 4, 47), vendor=93.95)]))
    s2 = reads.series(store, ["USDINR_FBIL"], start=MON, asof=asof)["series"][0]
    assert s2["fresher_twin"]["series_id"] == "USDINR_CLOSE" and s2["fresher_twin"]["report_date"] == "2026-11-08"


def test_a_future_dated_gold_series_twin_is_not_fresher_either(store):
    """The twin lookup reads ``gold_series`` straight through ``pit.asof_series``, which has no session clock: a
    future-dated FBIL row must not be announced as "one day ahead" of the market close."""
    asof = SUNDAY_1017_IST
    _seed_fx(store)
    pit.upsert_series(store, pit.series_frame("USDINR_FBIL", [(THU, 94.52), (NEXT_MON, 93.80)], freq="D",
                                             source="rbi_ref", now=asof), now=asof)
    reads.invalidate_catalog_cache()
    s = reads.series(store, ["USDINR_CLOSE"], start=MON, asof=asof)["series"][0]
    assert s["fresher_twin"] is None                                    # FBIL's newest VISIBLE day is Thu, behind Friday
    # negative control: an FBIL row dated today IS fresher than a market close that stops on Friday
    pit.upsert_series(store, pit.series_frame("USDINR_FBIL", [(SUN, 93.88)], freq="D", source="rbi_ref", now=asof), now=asof)
    s2 = reads.series(store, ["USDINR_CLOSE"], start=MON, asof=asof)["series"][0]
    assert s2["fresher_twin"]["series_id"] == "USDINR_FBIL" and s2["fresher_twin"]["report_date"] == "2026-11-08"


# ── C-DATA-05: a partial bar is re-fetched until it is final ─────────────────────────────────────────────────────

THU_PARTIAL_SEEN = datetime(2026, 11, 5, 21, 40)        # 03:10 IST Friday: 20 min before the winter Globex close
FINAL_BODY = _chart("GC=F", NY, [("2026-11-04 00:00", 3940.8, 4081.2, 3928.2, 4073.0),
                                 ("2026-11-05 00:00", 4075.4, 4155.8, 4067.0, 4113.5),
                                 ("2026-11-06 00:00", 4098.5, 4116.2, 4035.1, 4074.9)], anchor="2026-11-06 00:00",
                    volume=[163000, 215643, 198000])


def _seed_gc(store: Any, *, last: date = FRI) -> None:
    settled = ingest_yahoo.session_close_utc("GC=F", last) + timedelta(hours=10)      # fetched after its Globex close
    rows = [_bar("GC=F", WED, 3940.8, 4081.2, 3928.2, 4073.0, THU_PARTIAL_SEEN, volume=163000),
            # the partial Thursday bar: a mid-session close and the previous session's open
            _bar("GC=F", THU, 3940.8, 4155.8, 4067.0, 4098.4, THU_PARTIAL_SEEN, volume=208286),
            _bar("GC=F", last, 4098.5, 4116.2, 4035.1, 4074.9, settled, volume=215643)]
    db.upsert(store, "gold_daily_bars", pd.DataFrame(rows))


def _period1(http: FakeHttp) -> date:
    return pd.Timestamp(http.calls[-1][1]["params"]["period1"], unit="s", tz="UTC").date()


def test_a_catch_up_widens_the_look_back_and_heals_the_partial_bar(store):
    _seed_gc(store)
    assert ingest_yahoo.partial_dates(store, "GC=F", now=SUNDAY_1017_IST) == [THU]
    http = FakeHttp({"chart/GC=F": FakeResponse(200, json.dumps(FINAL_BODY))})
    out = ingest_yahoo.fetch_daily(store, http, symbols=["GC=F"], backfill_from=FRI, now=SUNDAY_1017_IST)
    # the old behaviour: start = backfill_from = 2026-11-06, which skips the 00:00 ET stamp of the 11-05 bar
    assert _period1(http) <= THU, _period1(http)
    row = db.query_df(store, "SELECT * FROM gold_daily_bars WHERE symbol = 'GC=F' AND trade_date = ?", [THU]).iloc[0]
    assert row.close == 4113.5 and row.volume == 215643
    assert ingest_yahoo.is_partial("GC=F", THU, row.first_seen_at) is False
    assert out["GC=F"]["repaired_partials"] == 1 and ingest_yahoo.partial_dates(store, "GC=F", now=SUNDAY_1017_IST) == []


def test_the_look_back_is_never_narrowed_by_a_catch_up_or_by_a_long_outage(store):
    body = FakeResponse(200, json.dumps(FINAL_BODY))
    # (a) an outage that moved the last stored bar more than five days past the partial bar: the hole was permanent
    _seed_gc(store, last=date(2026, 11, 20))
    http = FakeHttp({"chart/GC=F": body})
    ingest_yahoo.fetch_daily(store, http, symbols=["GC=F"], now=datetime(2026, 11, 21, 4, 47))
    assert _period1(http) <= THU, _period1(http)
    # (b) a backfill_from EARLIER than the routine window still wins (min, not max)
    http2 = FakeHttp({"chart/GC=F": body})
    ingest_yahoo.fetch_daily(store, http2, symbols=["GC=F"], backfill_from=date(2026, 1, 1), now=datetime(2026, 11, 21, 4, 47))
    assert _period1(http2) == date(2026, 1, 1)
    # negative control: with no partial bar left, the routine look-back is exactly the last bar − 5 days
    last = ingest_yahoo.last_trade_date(store, "GC=F")
    assert ingest_yahoo.partial_dates(store, "GC=F", now=datetime(2026, 11, 21, 4, 47)) == []
    http3 = FakeHttp({"chart/GC=F": body})
    ingest_yahoo.fetch_daily(store, http3, symbols=["GC=F"], now=datetime(2026, 11, 21, 4, 47))
    assert _period1(http3) == last - timedelta(days=5)


def test_a_volume_carried_forward_over_a_partial_bar_is_flagged(store):
    seen = datetime(2026, 11, 8, 4, 47)
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("GC=F", WED, 3940.8, 4081.2, 3928.2, 4073.0, seen, volume=163000),
        _bar("GC=F", THU, 3940.8, 4155.8, 4067.0, 4098.4, THU_PARTIAL_SEEN, volume=208286),   # in-progress count
        _bar("GC=F", FRI, 4098.5, 4116.2, 4035.1, 4074.9, seen, volume=163000)]))             # Wednesday's, carried
    rows = reads.bars(store, symbol="GC=F", start=MON)["rows"]
    assert [r["volume_repeat"] for r in rows] == [False, False, True]
    # negative control: a genuine Friday volume is not flagged just because Thursday's bar is partial
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("GC=F", FRI, 4098.5, 4116.2, 4035.1, 4074.9, seen, volume=215643)]))
    rows2 = reads.bars(store, symbol="GC=F", start=MON)["rows"]
    assert [r["volume_repeat"] for r in rows2] == [False, False, False]


def test_the_job_reports_what_it_healed(store):
    from gold import jobs

    _seed_gc(store)
    http = FakeHttp({"chart/GC=F": FakeResponse(200, json.dumps(FINAL_BODY))})
    res = jobs.run_job(store, http, "gold_overnight", ["yahoo_daily"], backfill_from=FRI, now=SUNDAY_1017_IST,
                       params={"symbols": ["GC=F"]})
    g = res["groups"]["yahoo_daily"]
    assert g["status"] == "ok" and g["repaired_partials"] == 1 and g["partials_open"] == 0
    # negative control: a run with nothing to heal says 0
    res2 = jobs.run_job(store, http, "gold_overnight", ["yahoo_daily"], force=True, now=SUNDAY_1017_IST,
                        params={"symbols": ["GC=F"]})
    assert res2["groups"]["yahoo_daily"]["repaired_partials"] == 0


FRIDAY_0640_IST = datetime(2026, 11, 6, 1, 10)         # 06:40 IST Friday = 20:10 ET Thursday, past the 17:00 ET close


def _seed_one_partial(store: Any) -> None:
    """GC=F holds the partial Thursday bar (the 03:10 IST Friday pull, 20 min early) and nothing else is partial;
    INR=X's only bar is settled, so it is NOT a repair candidate."""
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("GC=F", WED, 3940.8, 4081.2, 3928.2, 4073.0, datetime(2026, 11, 4, 22, 30), volume=163000),
        _bar("GC=F", THU, 3940.8, 4155.8, 4067.0, 4098.4, THU_PARTIAL_SEEN, volume=208286),
        _bar("INR=X", THU, 94.53, 94.57, 94.31, 94.53, datetime(2026, 11, 5, 22, 30), vendor=94.53)]))


def test_a_partial_bar_heals_without_waiting_for_the_next_overnight_run(store):
    """C-DATA-05, round 2. In winter the 03:10 IST pull lands 20 minutes before the 17:00 ET Globex close, so the
    session it just stored is a mid-session price for the whole following IST day — widening ``period1`` heals it only
    at the NEXT 03:10. The repair pass runs the same code on a second, cheap trigger: only the symbols whose latest
    stored bar is an in-progress session that has SINCE closed, at most one paced call each, none when there is
    nothing to heal, and never a session that is still running."""
    _seed_one_partial(store)
    assert ingest_yahoo.settled_partials(store, "GC=F", now=FRIDAY_0640_IST) == [THU]
    assert ingest_yahoo.settled_partials(store, "INR=X", now=FRIDAY_0640_IST) == []          # settled: left alone
    # a session still RUNNING is not a candidate: re-pulling it would only store another in-progress price
    assert ingest_yahoo.settled_partials(store, "GC=F", now=THU_PARTIAL_SEEN + timedelta(minutes=10)) == []
    # and the live shape of the defect is an INTERIOR partial — Thursday's mid-session bar with Friday's SETTLED bar
    # after it, which a "latest bar only" rule would never pick up
    db.upsert(store, "gold_daily_bars", pd.DataFrame([
        _bar("GC=F", FRI, 4098.5, 4116.2, 4035.1, 4074.9, datetime(2026, 11, 6, 22, 30), volume=215643)]))
    assert ingest_yahoo.settled_partials(store, "GC=F", now=FRIDAY_0640_IST) == [THU]
    db.execute(store, "DELETE FROM gold_daily_bars WHERE symbol = 'GC=F' AND trade_date = ?", [FRI])

    http = FakeHttp({"chart/GC=F": FakeResponse(200, json.dumps(FINAL_BODY))})
    res = ingest_yahoo.repair_partials(store, http, now=FRIDAY_0640_IST)
    assert res["candidates"] == 1 and res["calls"] == 1 and res["repaired_partials"] == 1 and res["skipped"] == 0
    assert [u for u, _ in http.calls] == [ingest_yahoo.CHART_URL.format(symbol="GC=F")]      # INR=X cost no call
    row = db.query_df(store, "SELECT * FROM gold_daily_bars WHERE symbol = 'GC=F' AND trade_date = ?", [THU]).iloc[0]
    assert row.close == 4113.5 and row.volume == 215643
    assert ingest_yahoo.is_partial("GC=F", THU, row.first_seen_at) is False

    # negative control: nothing left to heal → not one Yahoo call (so the pass costs nothing on a normal morning)
    http2 = FakeHttp({"chart/GC=F": FakeResponse(200, json.dumps(FINAL_BODY))})
    res2 = ingest_yahoo.repair_partials(store, http2, now=FRIDAY_0640_IST)
    assert res2["candidates"] == 0 and res2["calls"] == 0 and res2["repaired_partials"] == 0 and http2.calls == []


def test_the_repair_pass_is_a_job_group_of_its_own(store):
    from gold import jobs

    _seed_one_partial(store)
    http = FakeHttp({"chart/GC=F": FakeResponse(200, json.dumps(FINAL_BODY))})
    g = jobs.run_job(store, http, "gold_morning", ["yahoo_partials"], now=FRIDAY_0640_IST)["groups"]["yahoo_partials"]
    assert g["status"] == "ok" and g["candidates"] == 1 and g["calls"] == 1 and g["repaired_partials"] == 1
    # negative control: the group is a no-op with nothing to heal, and says so
    g2 = jobs.run_job(store, http, "gold_morning", ["yahoo_partials"], now=FRIDAY_0640_IST)["groups"]["yahoo_partials"]
    assert g2["status"] == "ok" and g2["candidates"] == 0 and g2["calls"] == 0


@pytest.mark.parametrize("sym,expected", [("INR=X", True), ("EURUSD=X", True), ("GC=F", False), ("GLD", False),
                                          ("GOLDBEES.NS", False), ("DX-Y.NYB", False)])
def test_only_the_fx_pairs_get_a_rebuilt_close(sym, expected):
    rows = [("2026-11-05 00:00", 10.0, 11.0, 9.0, 10.0), ("2026-11-06 00:00", 12.0, 13.0, 11.5, 12.0)]
    meta, bars = ingest_yahoo.parse_chart(_chart(sym, NY, rows, anchor="2026-11-06 00:00"), expect_interval="1d")
    out = ingest_yahoo.daily_bars_frame(meta, bars, sym, now=SUNDAY_1017_IST)
    assert bool(out["close"].iloc[0] == 12.0) is expected
    assert out["adj_close"].iloc[0] == 10.0


def test_a_dated_special_session_is_a_session_of_its_own_not_the_friday_before():
    """8 Nov 2026 (round 2 regression): the new session helpers rolled every weekend date back to Friday, so today's
    Muhurat bar was dated 6 Nov, collided with Friday's own bar and was dropped by `collapse_sessions` — the Muhurat
    session would simply have had no stored bar. CLAUDE.md binds every session helper to count SPECIAL_SESSIONS_2026."""
    q, sun = ingest_yahoo.quote_session_date, date(2026, 11, 8)
    assert ingest_yahoo.special_session_day(sun) and not ingest_yahoo.special_session_day(date(2026, 11, 15))
    assert ingest_yahoo.previous_friday(sun, "GOLDBEES.NS") == sun        # a session of its own, on an Indian exchange
    assert q("GOLDBEES.NS", pd.Timestamp("2026-11-08 14:30", tz="Asia/Kolkata")) == sun
    # negative control: COMEX, ICE and the FX fixings are SHUT that Sunday — dating a quote to it would invent a session
    assert ingest_yahoo.previous_friday(sun, "GC=F") == FRI and not ingest_yahoo.special_session_day(sun, "GC=F")
    assert q("GC=F", pd.Timestamp("2026-11-08 14:30", tz="Asia/Kolkata")) == FRI
    assert q("INR=X", pd.Timestamp("2026-11-08 05:00", tz=NY)) == FRI
    # negative controls: an ORDINARY Sunday still rolls back, and the Friday before the special session is untouched
    nxt = date(2026, 11, 15)
    assert ingest_yahoo.previous_friday(nxt) == date(2026, 11, 13)
    assert q("GOLDBEES.NS", pd.Timestamp("2026-11-15 14:30", tz="Asia/Kolkata")) == date(2026, 11, 13)
    assert q("GOLDBEES.NS", pd.Timestamp("2026-11-06 14:30", tz="Asia/Kolkata")) == FRI
    # end to end: the Muhurat bar survives collapse_sessions instead of colliding with Friday's
    bars = pd.DataFrame([{"trade_date": FRI, "symbol": "GOLDBEES.NS", "close": 100.0},
                         {"trade_date": sun, "symbol": "GOLDBEES.NS", "close": 101.0}])
    assert sorted({str(d) for d in bars["trade_date"]}) == ["2026-11-06", "2026-11-08"]
