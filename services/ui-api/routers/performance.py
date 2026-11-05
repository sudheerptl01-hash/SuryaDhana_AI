"""Model and strategy performance summaries.

model-comparison and strategy-performance read their real sources (ml-service's
active-model OOS metrics; the execution engine's paper/live ledger). They used to
return hard-coded nulls/zeros regardless of state. backtest-summary stays "pending":
backtests run on demand in the Backtest tab and are not persisted as a summary.
"""
import os

import httpx
from fastapi import APIRouter

router = APIRouter()

ML_SVC = os.getenv("ML_SERVICE_URL", "http://ml-service:8003")


@router.get("/backtest-summary")
async def get_backtest_summary():
    """Overall backtest performance metrics (not persisted — run a backtest)."""
    return {
        "status": "pending",
        "sharpe_ratio": None,
        "cagr_pct": None,
        "max_drawdown_pct": None,
        "win_rate_pct": None,
        "profit_factor": None,
        "note": "Backtests run on demand in the Backtest tab; results are not persisted here",
    }


def _pct(v):
    return round(float(v) * 100, 2) if isinstance(v, (int, float)) else None


@router.get("/model-comparison")
async def get_model_comparison():
    """Active classifier's out-of-sample metrics from ml-service."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{ML_SVC}/metrics")
        m = r.json() if r.status_code == 200 else {}
    except Exception:
        m = {}
    return {
        "classifier": {
            "accuracy_pct": _pct(m.get("accuracy")),
            "precision_pct": _pct(m.get("precision")),
            "recall_pct": _pct(m.get("recall")),
            "f1_score": m.get("f1_score"),
            "auc_roc": m.get("auc_roc"),
            "val_samples": m.get("val_samples"),
        },
        # The return regressor is trained alongside but not evaluated/persisted yet.
        "regressor": {"mae": None, "rmse": None, "r2_score": None},
        "note": "Out-of-sample metrics of the active model" if m else "No trained model — train in the ML Engine tab",
    }


@router.get("/strategy-performance")
async def get_strategy_performance():
    """Paper/live ledger summary from the execution engine."""
    from routers import execution as _exec

    if not getattr(_exec, "_engine_available", False):
        return {"trades_executed": 0, "current_positions": 0, "note": "Execution engine unavailable"}
    engine = _exec.get_engine()
    orders = await engine.get_orders(limit=10_000)
    filled = [o for o in orders if o.get("status") == "FILLED"]
    status = engine.get_status()
    return {
        "trades_executed": len(filled),
        "current_positions": status.get("open_positions", 0),
        "equity": status.get("equity"),
        "daily_pnl_inr": status.get("daily_pnl_inr"),
        "daily_pnl_pct": status.get("daily_pnl_pct"),
        "mode": status.get("mode"),
        "note": "From the execution engine ledger (data/paper_trades.db in PAPER mode)",
    }
