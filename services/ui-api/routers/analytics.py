"""Analytics: signals, labels, feature quality (future extensibility)."""
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/signal-coverage")
async def get_signal_coverage():
    """How many stocks have ML signals generated."""
    return {
        "stocks_with_signals": 0,
        "total_signals_generated": 0,
        "coverage_pct": 0,
        "last_signal_time": None,
        "note": "Signals table empty until ml-service runs",
    }


@router.get("/feature-quality")
async def get_feature_quality():
    """Feature engineering completeness (future: after feature-service runs)."""
    return {
        "stocks_with_features": 0,
        "total_feature_rows": 0,
        "average_features_per_stock": 0,
        "feature_coverage_pct": 0,
        "note": "Features table empty until feature-service runs",
    }


@router.get("/label-distribution")
async def get_label_distribution():
    """Label statistics (future: after label generation)."""
    return {
        "total_labels": 0,
        "up_labels_pct": 0,
        "down_labels_pct": 0,
        "average_return_pct": 0,
        "note": "Labels table empty until label generation runs",
    }
