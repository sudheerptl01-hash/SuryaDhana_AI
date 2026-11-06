"""MCX settlement proxy from ICICI Breeze 1-minute bars (wave 1d, the 5 Nov blocker; SOURCES.md F2).

Why: the ICICI master's price-band midpoint is the settlement of the session BEFORE the one its OI belongs to
(``ingest_india.band_session``), so every number divided by "yesterday's settlement" was one session stale. MCX's own
daily settlement price is the volume-weighted average of the last 30 minutes of trading; the honest proxy we can
compute is the same average over Breeze's 1-minute bars: Σ close·lots ÷ Σ lots over the bars that START inside
[close − 30 min, close). It is labelled a PROXY (``quality = proxy``) everywhere; it is never called the settlement.

Storage: ``gold_series`` rows ``MCX_<FAMILY>_<YYYYMM>_VWAP30`` (₹ in the family's quotation unit) and
``MCX_<FAMILY>_<YYYYMM>_VWAP30_LOTS`` (lots traded inside the window — a thin window reads as thin), ``report_date`` =
the session, ``release_at`` = that session's close (23:30 / 23:55 IST, 17:00 on an evening closure), ``source``
``breeze_1m_vwap30``. Re-running a session that is stored is a no-op (zero Breeze calls) unless ``force``; a changed
value becomes a new vintage (``pit.upsert_series``). A window whose final minute is not in yet is never stored before
close + ``FINAL_AFTER_MIN``: it is queued (``PENDING_KEY`` in gold_ingest_state) with every capped, budget-refused or
failed contract, and the next run without explicit sessions fetches the queue too, fronts first (round 2).

Breeze: read-only ``get_historical_data_v2`` only, one call per (session, contract), every call through the shared
budget ledger (``shared.breeze_budget``, caller ``data-service.gold_vwap30``), paced, capped per run, and stopped
after three consecutive failures. The client is the data-service live provider's session (``main._breeze_connect``);
with no session the group says so (``status: no_session``) and ui-api computes the proxy from its own session.
Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.
"""
from __future__ import annotations

import json
import os
import re
import time as _time
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from gold import db, pit
from gold.db import utcnow
from gold.ingest_india import family_expiry
from shared import mcx_specs as specs
from shared.logging import get_logger

logger = get_logger(__name__)

IST = ZoneInfo("Asia/Kolkata")
UTC = ZoneInfo("UTC")
SOURCE = "breeze_1m_vwap30"
QUALITY = "proxy"
WINDOW_MIN = 30                       # MCX settlement methodology: VWAP of the last 30 minutes
GRACE_MIN = 2                         # Breeze's last 1-minute bar lands about a minute after the close
SETTLE_CHECK_PCT = 0.6                # band midpoint vs VWAP30 beyond this = a stale band (the accuracy log uses the same test)
BREEZE_CODE: dict[str, str] = {"GOLD": "GOLD", "GOLDM": "GOLDMI", "GOLDTEN": "GOLDTE", "GOLDPETAL": "GOLDPE", "GOLDGUINEA": "GOLDGU"}
FAMILIES: tuple[str, ...] = tuple(BREEZE_CODE)
BUDGET_CALLER = "data-service.gold_vwap30"
MAX_EXPIRIES = int(os.getenv("GOLD_VWAP30_MAX_EXPIRIES", "3"))     # per family: the front + the next live months (OI > 0)
MAX_CALLS = int(os.getenv("GOLD_VWAP30_MAX_CALLS", "30"))           # per run (a nightly run needs ≤ 15)
PACE_S = float(os.getenv("GOLD_VWAP30_PACE_S", "1.1"))              # under the ledger's 60/min cap with room for the rest
MAX_CONSECUTIVE_FAILURES = 3
# Round 2 (check: a 23:58 run, 3 min after the 23:55 close, could store a short window for good): a window whose last bar
# starts before close − 1 min is NOT stored while the run is within FINAL_AFTER_MIN of the close — it is queued and the
# next run (the 00:15 retry, else the next night) fetches it again; from close + FINAL_AFTER_MIN on, Breeze's bars are
# final and the window is stored as it is (a thin month that did not trade in the last minute stays thin, flagged).
FINAL_AFTER_MIN = int(os.getenv("GOLD_VWAP30_FINAL_AFTER_MIN", "10"))
PENDING_KEY = "mcx_close.pending"     # gold_ingest_state: contracts to fetch again (deferred, capped, refused, failed)
PENDING_MAX_AGE_DAYS = 21             # Breeze 1-minute history reached back ≈ 14 sessions in the 5 Nov probes
PENDING_MAX_ATTEMPTS = 3              # a contract that errored three times is dropped from the queue (logged in the result)
PENDING_MAX_ITEMS = 300
SPECIAL_LOOKBACK_DAYS = 4             # a run without sessions also stores a special session (Muhurat) this recent
FAMILY_PRIORITY: dict[str, int] = {"GOLD": 0, "GOLDM": 1, "GOLDTEN": 2, "GOLDPETAL": 3, "GOLDGUINEA": 4}
SERIES_RE = re.compile(r"^MCX_(GOLD|GOLDM|GOLDTEN|GOLDPETAL|GOLDGUINEA)_(\d{4})(\d{2})_VWAP30(_LOTS)?$")


class BreezeShapeError(RuntimeError):
    """Breeze answered without a ``Success`` list (an HTTP 500 body, an auth error, an empty answer)."""


# ── ids and sessions ────────────────────────────────────────────────────────────────────────────────

def series_id(family: str, expiry: date) -> str:
    return f"MCX_{family}_{expiry:%Y%m}_VWAP30"


def lots_series_id(family: str, expiry: date) -> str:
    return f"{series_id(family, expiry)}_LOTS"


def parse_series_id(sid: str) -> tuple[str, int, int, bool] | None:
    """('GOLD', 2026, 12, is_lots) for 'MCX_GOLD_202612_VWAP30[_LOTS]', else None."""
    m = SERIES_RE.match(sid or "")
    return (m.group(1), int(m.group(2)), int(m.group(3)), bool(m.group(4))) if m else None


def catalog_key(sid: str) -> str | None:
    """The catalog template row of a per-contract id: 'MCX_GOLD_202612_VWAP30' → 'MCX_GOLD_VWAP30' (one row per family,
    not per month — the contract months roll, the verdict does not)."""
    p = parse_series_id(sid)
    if p is None:
        return None
    return f"MCX_{p[0]}_VWAP30" + ("_LOTS" if p[3] else "")


def session_close(day: date) -> datetime | None:
    """The IST close of the MCX session on ``day`` (23:30 / 23:55, 17:00 on an evening closure), None when shut."""
    w = specs.trading_window(day)
    return w[1] if w else None


def session_label(day: date | None) -> str | None:
    """How a settlement is named everywhere (PLAN 0.1 #8): 'Wed 04 Nov settlement'."""
    return f"{day:%a %d %b} settlement" if day else None


def latest_completed_session(now: datetime) -> date | None:
    """The latest MCX session whose close (+ the grace minutes) is at or before ``now`` (UTC-naive)."""
    now_ist = now.replace(tzinfo=UTC).astimezone(IST)
    d = now_ist.date()
    for _ in range(14):
        close = session_close(d)
        if close is not None and now_ist >= close + timedelta(minutes=GRACE_MIN):
            return d
        d -= timedelta(days=1)
    return None


def sessions_between(start: date, end: date) -> list[date]:
    """MCX sessions in [start, end] (weekends and full closures skipped)."""
    out, d = [], start
    while d <= end:
        if session_close(d) is not None:
            out.append(d)
        d += timedelta(days=1)
    return out


# ── the average ─────────────────────────────────────────────────────────────────────────────────────

def _bar_time(raw: Any) -> datetime | None:
    try:
        return datetime.strptime(str(raw)[:16], "%Y-%m-%d %H:%M").replace(tzinfo=IST)   # Breeze stamps IST wall time
    except ValueError:
        return None


def vwap30(bars: Iterable[dict[str, Any]], close_ist: datetime) -> dict[str, Any] | None:
    """Σ close·lots ÷ Σ lots over the 1-minute bars that START in [close − 30 min, close); None when the window traded
    nothing (an illiquid month: no proxy rather than a made-up one)."""
    start = close_ist - timedelta(minutes=WINDOW_MIN)
    win: list[tuple[datetime, float, float, Any]] = []
    for b in bars:
        t = _bar_time(b.get("datetime"))
        try:
            px, vol = float(b.get("close") or 0), float(b.get("volume") or 0)
        except (TypeError, ValueError):
            continue
        if t is None or not (start <= t < close_ist) or not px > 0:
            continue
        win.append((t, px, max(vol, 0.0), b.get("open_interest")))
    lots = sum(v for _, _, v, _ in win)
    if not win or lots <= 0:
        return None
    win.sort(key=lambda x: x[0])
    vw = sum(px * v for _, px, v, _ in win) / lots
    return {"vwap": round(vw, 2), "lots": int(round(lots)), "bars": len(win), "first_bar": win[0][0].strftime("%H:%M"),
            "last_bar": win[-1][0].strftime("%H:%M"), "last_close": win[-1][1],
            "last_oi": int(win[-1][3]) if str(win[-1][3] or "").strip().lstrip("-").isdigit() else None,
            "window": f"{start:%H:%M}–{close_ist:%H:%M} IST"}


def fetch_bars(breeze: Any, family: str, expiry: date, day: date, close_ist: datetime) -> list[dict[str, Any]]:
    """One read-only ``get_historical_data_v2`` call (1-minute bars, the 40 minutes before the close) through the budget
    ledger; raises ``BudgetExceeded`` before the SDK runs past the cap and ``BreezeShapeError`` on a non-list answer."""
    from shared.breeze_budget import ledger

    frm = (close_ist - timedelta(minutes=WINDOW_MIN + 10)).strftime("%Y-%m-%dT%H:%M:00.000Z")   # Breeze reads IST wall time
    to = (close_ist + timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:00.000Z")
    with ledger().guard(BUDGET_CALLER, "get_historical_data_v2"):
        resp = breeze.get_historical_data_v2(interval="1minute", from_date=frm, to_date=to, stock_code=BREEZE_CODE[family],
                                             exchange_code="MCX", product_type="futures",
                                             expiry_date=f"{expiry.isoformat()}T06:00:00.000Z", right="others", strike_price="0")
    rows = resp.get("Success") if isinstance(resp, dict) and resp.get("Status") == 200 else None
    if not isinstance(rows, list):
        err = resp.get("Error") if isinstance(resp, dict) else type(resp).__name__
        raise BreezeShapeError(f"Breeze status {resp.get('Status') if isinstance(resp, dict) else '?'}: {str(err)[:100]}")
    return [r for r in rows if isinstance(r, dict) and str(r.get("datetime", "")).startswith(day.isoformat())]


# ── which contracts ─────────────────────────────────────────────────────────────────────────────────

def contracts_for(store: Any, session: date, *, families: Iterable[str] | None = None,
                  max_expiries: int = MAX_EXPIRIES) -> list[tuple[str, date]]:
    """(family, expiry) to average for ``session``: from the latest ICICI master on/before it, per family the front
    month plus the next live months (OI > 0), at most ``max_expiries``; with no master stored, the computed GOLD and
    GOLDM fronts (the desk's contracts)."""
    fams = [f for f in (families or FAMILIES) if f in BREEZE_CODE]
    latest = db.to_date(db.scalar(store, """SELECT MAX(trade_date) FROM gold_curve WHERE exchange = 'MCX'
                                            AND source = 'icici_master_band' AND trade_date <= ?""", [session]))
    out: list[tuple[str, date]] = []
    if latest is not None:
        df = db.query_df(store, """SELECT symbol, expiry, open_interest FROM gold_curve WHERE exchange = 'MCX'
                                   AND source = 'icici_master_band' AND trade_date = ? AND expiry >= ? ORDER BY symbol, expiry""",
                         [latest, session])
        for fam in fams:
            sub = df[df["symbol"] == fam]
            picked: list[date] = []
            for i, r in enumerate(sub.itertuples(index=False)):
                exp = db.to_date(r.expiry)
                oi = r.open_interest
                if exp is None:
                    continue
                if i == 0 or (oi is not None and not pd.isna(oi) and int(oi) > 0):
                    picked.append(exp)
                if len(picked) >= max_expiries:
                    break
            out += [(fam, e) for e in picked]
    if not out:
        for fam in (f for f in ("GOLD", "GOLDM") if f in fams):
            if fam in specs.CONTRACTS:
                out += [(fam, e) for e in specs.active_expiries(fam, session, count=1)]
            else:                                        # pragma: no cover — both are in shared/mcx_specs today
                out.append((fam, family_expiry(fam, session.year, session.month)))
    return out


def stored(store: Any, family: str, expiry: date, session: date) -> bool:
    return bool(db.scalar(store, "SELECT COUNT(*) FROM gold_series WHERE series_id = ? AND report_date = ?",
                          [series_id(family, expiry), session]))


def frame(family: str, expiry: date, session: date, res: dict[str, Any], *, now: datetime) -> pd.DataFrame:
    """The two gold_series rows of one computed window (value + lots), released at the session close."""
    close = session_close(session)
    rel = close.astimezone(UTC).replace(tzinfo=None) if close else now
    base = {"report_date": session, "freq": "D", "release_at": min(rel, now), "release_source": "rule", "first_seen_at": now,
            "source": SOURCE, "quality": QUALITY, "revision": 0}
    return pd.DataFrame([{**base, "series_id": series_id(family, expiry), "value": float(res["vwap"])},
                         {**base, "series_id": lots_series_id(family, expiry), "value": float(res["lots"])}])


# ── the group ───────────────────────────────────────────────────────────────────────────────────────

def window_complete(res: dict[str, Any], close_ist: datetime) -> bool:
    """True when the window's last bar starts at close − 1 min (Breeze's final minute is in)."""
    return str(res.get("last_bar") or "") >= (close_ist - timedelta(minutes=1)).strftime("%H:%M")


def is_final(close_ist: datetime, now: datetime) -> bool:
    """From close + FINAL_AFTER_MIN on, Breeze's 1-minute bars for the session are taken as final."""
    return now.replace(tzinfo=UTC) >= close_ist + timedelta(minutes=FINAL_AFTER_MIN)


def _priority(item: tuple[date, str, date], rank: dict[tuple[date, str, date], int]) -> tuple[int, int, int]:
    """Fronts first (every family's nearest month, GOLD → GOLDM → TEN → PETAL → GUINEA), newest session first; then the
    second months, … — so a capped catch-up spends its calls where the fair block and the basis read."""
    d, fam, _ = item
    return rank.get(item, 9), FAMILY_PRIORITY.get(fam, 9), -d.toordinal()


def load_pending(store: Any) -> list[dict[str, Any]]:
    try:
        raw = db.get_state(store, PENDING_KEY)
        items = json.loads(raw) if raw else []
    except Exception:  # noqa: BLE001 — a corrupt or missing queue is an empty queue
        return []
    return [i for i in items if isinstance(i, dict) and db.to_date(i.get("session")) and db.to_date(i.get("expiry"))
            and i.get("family") in BREEZE_CODE]


def save_pending(store: Any, items: list[dict[str, Any]], *, now: datetime) -> bool:
    try:
        db.set_state(store, PENDING_KEY, json.dumps(items[:PENDING_MAX_ITEMS], sort_keys=True), now=now)
        return True
    except Exception:  # noqa: BLE001 — a read-only store: the queue is advisory (the next backfill_from run re-plans)
        return False


def run(store: Any, get_breeze: Callable[[], Any] | None, *, now: datetime | None = None, sessions: list[Any] | None = None,
        backfill_from: date | None = None, families: Iterable[str] | None = None, force: bool = False,
        max_calls: int | None = None, pace_s: float | None = None, sleep: Callable[[float], None] = _time.sleep) -> dict[str, Any]:
    """Compute and store the VWAP30 proxy of the latest completed session (or ``sessions`` / every session since
    ``backfill_from``) for the contracts ``contracts_for`` picks, plus — on a run without explicit ``sessions`` — the
    contracts queued by earlier runs (``PENDING_KEY``: a window that was not final yet, a capped or budget-refused
    remainder, a failed call). The plan runs fronts first and newest first (``_priority``). Returns per-contract
    outcomes, Breeze call counts and the queue left behind."""
    from shared.breeze_budget import BudgetExceeded

    now = now or utcnow()
    last = latest_completed_session(now)
    if sessions:
        days = sorted({d for d in (db.to_date(s) for s in sessions) if d is not None and session_close(d) is not None
                       and (last is None or d <= last)})
    elif backfill_from is not None and last is not None:
        days = sessions_between(backfill_from, last)
    else:
        # the latest session, plus a dated special session of the last few days (Muhurat, Sun 8 Nov 2026): the 23:58 job
        # runs Mon–Fri, so the Monday run also stores Sunday's window (stored contracts cost no call; wave 1e M-D)
        days = ([d for d in sessions_between(last - timedelta(days=SPECIAL_LOOKBACK_DAYS), last)
                 if d == last or d in specs.SPECIAL_SESSION_WINDOWS] if last is not None else [])
    oldest = (now.date() - timedelta(days=PENDING_MAX_AGE_DAYS))
    pending_in = load_pending(store)
    queued: dict[tuple[date, str, date], dict[str, Any]] = {}
    for it in pending_in:
        sd, ed = db.to_date(it["session"]), db.to_date(it["expiry"])
        if sd is None or ed is None or sd < oldest or (last is not None and sd > last):
            continue                                                         # too old for Breeze's 1-minute history
        queued[(sd, str(it["family"]), ed)] = it
    fams = [f for f in (families or FAMILIES) if f in BREEZE_CODE]
    rank: dict[tuple[date, str, date], int] = {}
    plan_set: set[tuple[date, str, date]] = set()
    already = 0
    for d in days:
        per_fam: dict[str, int] = {}
        for fam, exp in contracts_for(store, d, families=fams):
            item = (d, fam, exp)
            rank[item] = per_fam.get(fam, 0)
            per_fam[fam] = rank[item] + 1
            if not force and stored(store, fam, exp, d):
                already += 1
                queued.pop(item, None)
                continue
            plan_set.add(item)
    if not sessions:                                                         # the nightly / catch-up run also drains the queue
        for item in list(queued):
            if item[1] not in fams:
                continue
            if not force and stored(store, item[1], item[2], item[0]):
                queued.pop(item, None)
                continue
            rank.setdefault(item, int(queued[item].get("rank", 1)))
            plan_set.add(item)
    plan = sorted(plan_set, key=lambda it: _priority(it, rank))
    base = {"sessions": [d.isoformat() for d in days], "already_stored": already, "planned": len(plan), "breeze_calls": 0,
            "queued_in": len(pending_in)}
    if not plan:
        if len(queued) != len(pending_in):
            save_pending(store, list(queued.values()), now=now)
        return {"status": "ok", "inserted": 0, **base, "queued": len(queued)}
    breeze = None
    if get_breeze is not None:
        try:
            breeze = get_breeze()
        except Exception:  # noqa: BLE001 — a broken session getter is "no session", never a crash
            breeze = None
    if breeze is None:
        for item in plan:
            queued.setdefault(item, _queue_item(item, "no_session", rank.get(item, 1)))
        save_pending(store, list(queued.values()), now=now)
        return {"status": "no_session", "inserted": 0, **base, "queued": len(queued),
                "reason": "data-service has no live Breeze session (the ≈08:00 ICICI login connects it); ui-api computes the "
                          "proxy from its own session meanwhile"}
    cap = max_calls if max_calls is not None else MAX_CALLS
    pace = PACE_S if pace_s is None else pace_s
    frames: list[pd.DataFrame] = []
    outcomes: list[dict[str, Any]] = []
    calls, fails, status = 0, 0, "ok"
    broken: set[tuple[date, str]] = set()          # a family whose call failed: its other months that session are skipped
    done: set[tuple[date, str, date]] = set()      # stored, or a final answer (no trades after the window was final)
    retry: dict[tuple[date, str, date], str] = {}  # stays queued with this reason
    dropped: list[dict[str, Any]] = []
    for n, item in enumerate(plan):
        d, fam, exp = item
        if calls >= cap:
            status = "capped"
            for rest in plan[n:]:
                retry.setdefault(rest, "capped")
            break
        close = session_close(d)
        if close is None:
            done.add(item)
            continue
        key = {"session": d.isoformat(), "family": fam, "expiry": exp.isoformat(), "series_id": series_id(fam, exp)}
        if (d, fam) in broken:
            outcomes.append({**key, "status": "skipped", "reason": f"{fam} failed earlier this session"})
            retry[item] = "skipped"
            continue
        if calls:
            sleep(pace)
        calls += 1
        try:
            bars = fetch_bars(breeze, fam, exp, d, close)
        except BudgetExceeded as exc:
            outcomes.append({**key, "status": "budget", "reason": str(exc)[:160]})
            status = "budget"
            calls -= 1                                   # refused before the SDK ran: ICICI did not count it
            for rest in plan[n:]:
                retry.setdefault(rest, "budget")
            break
        except Exception as exc:  # noqa: BLE001 — one contract never stops the others (until three in a row fail)
            fails += 1
            broken.add((d, fam))
            outcomes.append({**key, "status": "error", "error": f"{type(exc).__name__}: {str(exc)[:120]}"})
            attempts = int((queued.get(item) or {}).get("attempts", 0)) + 1
            if attempts >= PENDING_MAX_ATTEMPTS:
                dropped.append({**key, "attempts": attempts})
                done.add(item)
            else:
                retry[item] = "error"
                queued[item] = {**_queue_item(item, "error", rank.get(item, 1)), "attempts": attempts}
            if fails >= MAX_CONSECUTIVE_FAILURES:
                status = "degraded"
                for rest in plan[n + 1:]:
                    retry.setdefault(rest, "degraded")
                break
            continue
        fails = 0
        res = vwap30(bars, close)
        final = is_final(close, now)
        if res is None:
            if final:
                outcomes.append({**key, "status": "no_trades", "bars": len(bars)})
                done.add(item)
            else:
                outcomes.append({**key, "status": "incomplete", "bars": len(bars),
                                 "reason": f"no bar in the window yet; fetched again after {FINAL_AFTER_MIN} min past the close"})
                retry[item] = "incomplete"
            continue
        complete = window_complete(res, close)
        if not complete and not final:
            outcomes.append({**key, "status": "incomplete", **res,
                             "reason": (f"last bar {res['last_bar']} < {(close - timedelta(minutes=1)):%H:%M}: Breeze's final minute is "
                                        f"not in yet; not stored, fetched again after {FINAL_AFTER_MIN} min past the close")})
            retry[item] = "incomplete"
            continue
        frames.append(frame(fam, exp, d, res, now=now))
        outcomes.append({**key, "status": "ok", **res, "complete": complete})
        done.add(item)
    written = pit.upsert_series(store, pd.concat(frames, ignore_index=True), now=now) if frames else {"inserted": 0, "revised": 0}
    for item in done:
        queued.pop(item, None)
    for item, why in retry.items():
        prev = queued.get(item) or _queue_item(item, why, rank.get(item, 1))
        queued[item] = {**prev, "reason": why}
    queue = sorted(queued.values(), key=lambda it: (str(it["session"]), FAMILY_PRIORITY.get(str(it["family"]), 9), str(it["expiry"])),
                   reverse=True)
    saved = save_pending(store, queue, now=now)
    if status == "ok" and calls and not frames and all(o["status"] in ("error", "skipped") for o in outcomes):
        status = "degraded"
    logger.info("gold.vwap30.run", calls=calls, stored=len(frames), status=status, queued=len(queue))
    return {**base, "status": status, "inserted": int(written.get("inserted", 0)) + int(written.get("revised", 0)), "breeze_calls": calls,
            "contracts": outcomes, "queued": len(queue), "queue_saved": saved, "dropped_after_errors": dropped}


def _queue_item(item: tuple[date, str, date], reason: str, rank: int = 1) -> dict[str, Any]:
    """One queued contract: its session, family, expiry, why it waits, the failed attempts so far, its month rank (0 = front)."""
    return {"session": item[0].isoformat(), "family": item[1], "expiry": item[2].isoformat(), "reason": reason, "attempts": 0,
            "rank": int(rank)}


def settlement_check(band_mid: float | None, vwap: float | None) -> dict[str, Any] | None:
    """{band_vs_vwap30_pct, flagged}: the band midpoint against the VWAP30 proxy; flagged beyond ``SETTLE_CHECK_PCT``."""
    if not band_mid or not vwap:
        return None
    pct = (float(band_mid) / float(vwap) - 1.0) * 100.0
    return {"band_vs_vwap30_pct": round(pct, 3), "flagged": abs(pct) > SETTLE_CHECK_PCT, "threshold_pct": SETTLE_CHECK_PCT}


def session_settlements(store: Any, family: str = "GOLD", *, asof: datetime | None = None) -> pd.DataFrame:
    """One row per session: the FRONT contract's settlement proxy for that session (front = the nearest expiry on or
    after it): the VWAP30 when stored, else the midpoint of the master whose band is centred on that session.
    Columns: session, expiry, settle, source ('breeze_vwap30' | 'band_midpoint'). Used by ``derive.derive_india``
    (MCX_BASIS_PCT) so the basis pairs a settlement with ITS session's duty-paid landed price."""
    from gold.ingest_india import band_midpoint, band_session

    cols = ["session", "expiry", "settle", "source"]
    bands = db.query_df(store, """SELECT trade_date, expiry, band_lo, band_hi, settle FROM gold_curve WHERE exchange = 'MCX'
                                  AND source = 'icici_master_band' AND symbol = ? AND release_at <= ?""", [family, asof or utcnow()])
    cand: dict[tuple[date, date], tuple[float, str]] = {}
    for r in bands.itertuples(index=False):
        td, exp = db.to_date(r.trade_date), db.to_date(r.expiry)
        mid = band_midpoint(r.band_lo, r.band_hi) or (float(r.settle) if r.settle is not None and not pd.isna(r.settle) else None)
        if td is None or exp is None or not mid:
            continue
        s = band_session(td)
        if exp >= s:
            cand.setdefault((s, exp), (mid, "band_midpoint"))
    vw = db.query_df(store, f"""SELECT series_id, report_date, value FROM gold_series WHERE series_id LIKE 'MCX_{family}_%_VWAP30'
                                AND release_at <= ? QUALIFY ROW_NUMBER() OVER (PARTITION BY series_id, report_date
                                ORDER BY release_at DESC) = 1""", [asof or utcnow()])
    for r in vw.itertuples(index=False):
        p = parse_series_id(str(r.series_id))
        d = db.to_date(r.report_date)
        if p is None or p[0] != family or p[3] or d is None:
            continue
        exp = next((e for (s, e) in cand if s == d and (e.year, e.month) == (p[1], p[2])), None)
        if exp is None:
            exp = family_expiry(family, p[1], p[2])
        if exp >= d:
            cand[(d, exp)] = (float(r.value), "breeze_vwap30")          # the VWAP30 wins over the band for its session
    rows: dict[date, tuple[date, float, str]] = {}
    for (s, exp), (v, src) in sorted(cand.items()):
        if s not in rows:                                                    # sorted by expiry within a session → the front
            rows[s] = (exp, v, src)
    return pd.DataFrame([{"session": s, "expiry": e, "settle": v, "source": src} for s, (e, v, src) in sorted(rows.items())],
                        columns=cols)
