"""
Decision Desk API (paper trading of the approved monthly momentum strategy).

GET  /api/desk/status    book, positions, NAV history, briefs (with orders), events
GET  /api/desk/preview   what the brief would say if the month ended at the latest close
POST /api/desk/daily     run the evening cycle (called by master-controller after EOD data)
POST /api/desk/reenable  clear the emergency stop after a manual review

Engine: shared/decision_desk.py (same selection code as the backtest). Handlers are
sync `def`s: FastAPI runs them in the threadpool, so the event loop never blocks.
Config: DESK_CAPITAL (₹, default 5,00,000), DESK_EQUITY_SHARE (default 0.66 = Option B),
DESK_AVOID_BULK_BUY_DAYS (default 0 = off; candidate filter under review),
DESK_LEDGER (default <data>/decision_desk.db), COST_PROFILE (shared/trading_costs.py).
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
from fastapi import APIRouter, HTTPException, Query

# shared/ lives at the repo root locally and is bind-mounted at /app/shared in Docker
for _p in (Path(__file__).resolve().parents[3], Path(__file__).resolve().parents[1]):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from shared.decision_desk import Desk  # noqa: E402
from shared.momentum import StrategyConfig  # noqa: E402
from shared.nse_panel import load_panel  # noqa: E402
from shared.trading_costs import default_model  # noqa: E402

from db import DB_PATH  # noqa: E402
from routers.analytics import _acquire_readonly  # noqa: E402
from shared.deal_filters import non_institutional_buy_events  # noqa: E402

# Candidate rule under owner review (reports/desk_filter/REPORT.md). 0 = the approved rules.
_AVOID_BULK_DAYS = int(os.getenv("DESK_AVOID_BULK_BUY_DAYS", "0"))

router = APIRouter()
_run_lock = threading.Lock()
_desk: Desk | None = None
# Set only inside the scheduled cycle: it must plan on the latest EOD data, so it waits
# for a current snapshot; status/preview pages accept a copy up to the snapshot TTL old.
_fresh_read = threading.local()


def _load_market(start: date) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    con, owns = _acquire_readonly(lambda *_: None, fresh=getattr(_fresh_read, "on", False))
    try:
        panel = load_panel(con, start=str(start))
        nifty = con.execute("SELECT date, close FROM market_index_daily WHERE symbol='NIFTY50' ORDER BY date").df()
        if _AVOID_BULK_DAYS:        # candidate filter (off unless DESK_AVOID_BULK_BUY_DAYS > 0)
            deals = con.execute("SELECT date, symbol, client_name, side, qty FROM nse_deals WHERE kind = 'bulk' "
                                "AND date >= ?::DATE", [str(start)]).df()
            deals["date"] = pd.to_datetime(deals["date"])
            panel["bulk_buy_events"] = non_institutional_buy_events(deals)
    finally:
        if owns:
            con.close()
    if panel["close"].empty:
        raise HTTPException(status_code=503, detail="No NSE bhavcopy data yet (run POST /jobs/ingest-bhavcopy)")
    return panel, nifty.assign(date=pd.to_datetime(nifty["date"])).set_index("date")["close"]


def get_desk() -> Desk:
    global _desk
    if _desk is None:
        cfg = StrategyConfig(equity_share=float(os.getenv("DESK_EQUITY_SHARE", "0.66")),
                             avoid_bulk_buy_days=_AVOID_BULK_DAYS)
        ledger = Path(os.getenv("DESK_LEDGER") or Path(DB_PATH).resolve().parent / "decision_desk.db")
        _desk = Desk(ledger, cfg, default_model(), _load_market,
                     start_capital=float(os.getenv("DESK_CAPITAL", "500000")))
    return _desk


@router.get("/status")
def desk_status() -> dict:
    return get_desk().status()


@router.get("/preview")
def desk_preview() -> dict:
    return get_desk().preview()


@router.post("/daily")
def desk_daily(today: date | None = Query(None, description="IST date (default: today)")) -> dict:
    if not _run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Decision Desk cycle already running")
    _fresh_read.on = True
    try:
        return get_desk().daily(today)
    except duckdb.Error as exc:
        raise HTTPException(status_code=503, detail=f"market data unavailable: {exc}") from exc
    finally:
        _fresh_read.on = False
        _run_lock.release()


@router.post("/reenable")
def desk_reenable() -> dict:
    return get_desk().reenable()
