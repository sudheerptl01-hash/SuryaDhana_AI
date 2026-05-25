"""Model and strategy performance (future: after backtesting runs)."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/backtest-summary")
async def get_backtest_summary():
    """Overall backtest performance metrics."""
    return {
        "status": "pending",
        "sharpe_ratio": None,
        "cagr_pct": None,
        "max_drawdown_pct": None,
        "win_rate_pct": None,
        "profit_factor": None,
        "note": "Run backtesting to populate these metrics",
    }


@router.get("/model-comparison")
async def get_model_comparison():
    """Compare classifier vs regressor performance."""
    return {
        "classifier": {
            "accuracy_pct": None,
            "precision_pct": None,
            "recall_pct": None,
            "f1_score": None,
        },
        "regressor": {
            "mae": None,
            "rmse": None,
            "r2_score": None,
        },
        "note": "Train models to populate these metrics",
    }


@router.get("/strategy-performance")
async def get_strategy_performance():
    """Live/paper trading performance."""
    return {
        "trades_executed": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_pnl_pct": 0,
        "avg_trade_return_pct": 0,
        "current_positions": 0,
        "note": "Live trading results will appear here",
    }
