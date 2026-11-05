"""
Execution router — exposes the live_execution.py engine to the Next.js UI.
All endpoints are synchronous wrappers; asyncio is handled by FastAPI.

PAPER ONLY guard (desktop review C2-security-03). The product runs paper-only, but the legacy engine
persists its mode in paper_trades.db and restores it at start, and its LIVE branch sends real NSE market
orders through Breeze. ui-api therefore refuses LIVE unless the owner opts in with
EXECUTION_LIVE_ALLOWED=1 (environment / .env, read per request):
- POST /mode with LIVE -> 403 (before the confirm_live check);
- at startup (main.py lifespan) a LIVE mode restored from SQLite (or EXECUTION_MODE=LIVE) is switched to
  PAPER through the engine's own set_mode, with a WARNING;
- every route re-checks: an engine found in LIVE without the opt-in is switched to PAPER, and an order
  path (/order, /rebalance with dry_run=false, /liquidate) is refused with 403 (nothing reaches the broker);
- GET /status adds `live_allowed` and `mode_policy` (PAPER_ONLY | LIVE_ALLOWED); `mode` stays the
  effective mode.
The engine code (services/execution-service/) is unchanged; with the opt-in set, behaviour is as before.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from errors import fail
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel


# Locate live_execution.py across local-dev and Docker layouts
def _find_live_execution() -> str | None:
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "execution-service" / "live_execution.py",   # local dev
        here.parents[1] / "live_execution.py",                          # ui-api root copy
        Path("/app/scripts/live_execution.py"),                         # Docker (scripts mount)
        Path("/app/live_execution.py"),                                 # Docker (root copy)
    ]
    for c in candidates:
        if c.exists():
            return str(c.parent)
    return None

_exec_path = _find_live_execution()
if _exec_path and _exec_path not in sys.path:
    sys.path.insert(0, _exec_path)

try:
    from live_execution import ExecutionMode, get_engine
    _engine_available = True
except ImportError as _import_err:
    _engine_available = False
    _import_error_msg = str(_import_err)

router = APIRouter()
log = logging.getLogger("ui-api.execution")

AVAILABLE_MODELS = ["XGBoost", "RL Agent", "XGBoost+RL Ensemble", "Manual"]

LIVE_OPT_IN_ENV = "EXECUTION_LIVE_ALLOWED"
_LIVE_HINT = f"set {LIVE_OPT_IN_ENV}=1 in .env and restart ui-api to allow real-money orders"


def _require_engine():
    if not _engine_available:
        raise HTTPException(
            status_code=503,
            detail=f"Execution engine not available: {_import_error_msg if not _engine_available else ''}",
        )
    return get_engine()


# ── PAPER ONLY guard (see the module docstring) ────────────────────────────────

def live_allowed() -> bool:
    """True only when the owner opted in to real-money execution (EXECUTION_LIVE_ALLOWED=1)."""
    return os.environ.get(LIVE_OPT_IN_ENV, "").strip() == "1"


def _mode_policy() -> dict[str, Any]:
    allowed = live_allowed()
    return {"live_allowed": allowed, "mode_policy": "LIVE_ALLOWED" if allowed else "PAPER_ONLY"}


def _is_live(engine: Any) -> bool:
    """The engine's effective mode is LIVE. Fails closed: an unreadable status counts as LIVE."""
    try:
        return str(engine.get_status().get("mode", "")).upper() == "LIVE"
    except Exception:  # noqa: BLE001 — never let a status read open the LIVE path
        return True


def _event(level: int, event: str, **fields: Any) -> None:
    log.log(level, json.dumps({"event": event, **fields}, default=str))


async def _switch_to_paper(engine: Any, where: str) -> bool:
    """Put the engine back in PAPER through its own set_mode (persists to paper_trades.db)."""
    try:
        await engine.set_mode(ExecutionMode.PAPER)
    except Exception as exc:  # noqa: BLE001 — logged; order paths stay refused while LIVE
        _event(logging.ERROR, "execution.paper_guard_failed", where=where, error=type(exc).__name__)
        return False
    _event(logging.WARNING, "execution.live_refused", where=where, action="switched to PAPER",
           opt_in=LIVE_OPT_IN_ENV)
    return True


async def _guarded_engine(order_path: bool = False) -> Any:
    """The engine, never in LIVE without the opt-in. An order path that finds it LIVE is refused (403)."""
    engine = _require_engine()
    if live_allowed() or not _is_live(engine):
        return engine
    await _switch_to_paper(engine, "order" if order_path else "request")
    if order_path:
        fail(403, "unauthorized",
             "Order refused: the execution engine was in LIVE mode, but SuryaDhana runs PAPER ONLY. It has been "
             "switched to PAPER and nothing was sent to the broker; resubmit to place a paper order.",
             hint=_LIVE_HINT)
    return engine


async def enforce_paper_only_at_startup() -> str:
    """main.py lifespan hook: switch a LIVE mode restored from SQLite back to PAPER unless opted in.

    Returns the outcome (unavailable · live_allowed · paper · switched · error). Never raises."""
    if not _engine_available:
        return "unavailable"
    if live_allowed():
        _event(logging.WARNING, "execution.live_allowed", opt_in=LIVE_OPT_IN_ENV)
        return "live_allowed"
    try:
        engine = await asyncio.to_thread(get_engine)  # first construction opens SQLite: off the event loop
        if not _is_live(engine):
            return "paper"
        return "switched" if await _switch_to_paper(engine, "startup") else "error"
    except Exception as exc:  # noqa: BLE001 — startup must not fail; order paths re-check per request
        _event(logging.ERROR, "execution.paper_guard_failed", where="startup", error=type(exc).__name__)
        return "error"


# ── Status ─────────────────────────────────────────────────────────────────────

@router.get("/status")
async def get_execution_status():
    """Engine state, mode, equity, daily MTM."""
    if not _engine_available:
        return {
            "available": False,
            "mode": "PAPER",
            "state": "UNAVAILABLE",
            "active_model": "XGBoost",
            "equity": float(os.environ.get("INITIAL_EQUITY", "10000")),
            "daily_pnl_inr": 0.0,
            "daily_pnl_pct": 0.0,
            "daily_loss_limit_pct": 2.0,
            "kill_switch_headroom_pct": 2.0,
            "unrealized_pnl_inr": 0.0,
            "open_positions": 0,
            "kill_switch_reason": "",
            "available_models": AVAILABLE_MODELS,
            **_mode_policy(),
        }
    engine = await _guarded_engine()
    status = engine.get_status()
    status["available"] = True
    status["available_models"] = AVAILABLE_MODELS
    status.update(_mode_policy())
    return status


# ── Mode Control ───────────────────────────────────────────────────────────────

class SetModeRequest(BaseModel):
    mode: str  # "PAPER" | "LIVE"
    confirm_live: bool = False  # must be True when switching to LIVE


@router.post("/mode")
async def set_execution_mode(req: SetModeRequest):
    engine = await _guarded_engine()
    try:
        new_mode = ExecutionMode(req.mode.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid mode '{req.mode}'. Use PAPER or LIVE.")

    if new_mode == ExecutionMode.LIVE and not live_allowed():
        _event(logging.WARNING, "execution.live_refused", where="mode", action="refused")
        fail(403, "unauthorized", "LIVE execution is disabled: SuryaDhana runs PAPER ONLY.", hint=_LIVE_HINT)

    if new_mode == ExecutionMode.LIVE and not req.confirm_live:
        raise HTTPException(
            status_code=400,
            detail="Switching to LIVE mode requires confirm_live=true. Real money will be traded.",
        )

    try:
        await engine.set_mode(new_mode)
        return {"mode": new_mode.value, "message": f"Execution mode set to {new_mode.value}"}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ── Active Model ───────────────────────────────────────────────────────────────

class SetModelRequest(BaseModel):
    model: str


@router.post("/model")
async def set_active_model(req: SetModelRequest):
    engine = await _guarded_engine()
    if req.model not in AVAILABLE_MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown model '{req.model}'. Valid: {AVAILABLE_MODELS}",
        )
    await engine.set_active_model(req.model)
    return {"active_model": req.model}


# ── Positions ──────────────────────────────────────────────────────────────────

@router.get("/positions")
async def get_live_positions():
    """Current positions with LTP and unrealized P&L."""
    if not _engine_available:
        return {"positions": [], "count": 0, "available": False}
    engine = await _guarded_engine()
    try:
        positions = await engine.get_positions()
        return {
            "positions": positions,
            "count": len(positions),
            "available": True,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Position fetch error: {exc}")


# ── Orders ─────────────────────────────────────────────────────────────────────

@router.get("/orders")
async def get_order_history(limit: int = 50):
    if not _engine_available:
        return {"orders": [], "count": 0}
    engine = await _guarded_engine()
    try:
        orders = await engine.get_orders(limit=limit)
        return {"orders": orders, "count": len(orders)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Order fetch error: {exc}")


# ── Manual Order ───────────────────────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    symbol: str
    side: str           # "BUY" | "SELL"
    quantity: int
    price: float
    signal_source: str = "Manual"
    stop_loss_price: float = 0.0


@router.post("/order")
async def place_manual_order(req: PlaceOrderRequest):
    engine = await _guarded_engine(order_path=True)
    if req.side.upper() not in ("BUY", "SELL"):
        raise HTTPException(status_code=400, detail="side must be BUY or SELL")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity must be positive")
    if req.price <= 0:
        raise HTTPException(status_code=400, detail="price must be positive")
    result = await engine.place_order(
        symbol=req.symbol.upper(),
        side=req.side.upper(),
        quantity=req.quantity,
        price=req.price,
        signal_source=req.signal_source,
        stop_loss_price=req.stop_loss_price,
    )
    return result


# (dead route /order/scheduled + its request model removed — Bloomberg program F1.5;
#  the TWAP/VWAP/POV engine lives on in ExecutionEngine.execute_scheduled and stays
#  covered by the execution-service suite)



# ── Weight Rebalance ───────────────────────────────────────────────────────────

class RebalanceRequest(BaseModel):
    target_weights: dict[str, float]      # {symbol: 0.0–1.0}
    prices: dict[str, float]              # {symbol: ltp}
    signal_sources: dict[str, str] = {}  # {symbol: "XGBoost" | "RL Agent"}
    dry_run: bool = True                  # if True, return proposed orders without executing


@router.post("/rebalance")
async def rebalance_portfolio(req: RebalanceRequest):
    engine = await _guarded_engine(order_path=not req.dry_run)
    proposed = await engine.translate_weights_to_orders(
        target_weights=req.target_weights,
        prices=req.prices,
        signal_sources=req.signal_sources or None,
    )

    if req.dry_run:
        return {"dry_run": True, "proposed_orders": proposed}

    executed = []
    for order in proposed:
        result = await engine.place_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=order["quantity"],
            price=order["price"],
            signal_source=order.get("signal_source", "Rebalance"),
        )
        executed.append(result)

    return {"dry_run": False, "executed_orders": executed}


# ── Kill Switch ────────────────────────────────────────────────────────────────

class KillSwitchRequest(BaseModel):
    reason: str = "Manual LIQUIDATE & HALT"
    confirm: bool = False   # caller must set to True


@router.post("/liquidate")
async def execute_kill_switch(req: KillSwitchRequest):
    """
    LIQUIDATE ALL POSITIONS and halt the engine.
    Requires confirm=true. This cannot be undone without a manual engine reset.
    """
    if not req.confirm:
        raise HTTPException(
            status_code=400,
            detail="confirm=true required. This will sell ALL positions and halt trading.",
        )
    engine = await _guarded_engine(order_path=True)
    result = await engine.execute_kill_switch(reason=req.reason)
    return result


# ── Reconcile ─────────────────────────────────────────────────────────────────

class ReconcileRequest(BaseModel):
    broker_positions: list[dict[str, Any]]


@router.post("/reconcile")
async def reconcile_positions(req: ReconcileRequest):
    engine = await _guarded_engine()
    deltas = await engine.reconcile_positions(req.broker_positions)
    return {"delta_orders": deltas, "count": len(deltas)}


# ── Engine Reset (new trading day) ─────────────────────────────────────────────

class ResetRequest(BaseModel):
    new_equity: float | None = None
    confirm: bool = False


@router.post("/reset")
async def reset_engine(req: ResetRequest):
    if not req.confirm:
        raise HTTPException(status_code=400, detail="confirm=true required to reset engine state.")
    engine = await _guarded_engine()
    result = await engine.reset_engine(new_equity=req.new_equity)
    return result
