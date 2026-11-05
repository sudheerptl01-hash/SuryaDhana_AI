import sys
from pathlib import Path
# Service folders use hyphens (not importable as packages): put the repo root
# (for `shared`) and the service folder on sys.path and import the module directly.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/feature-service"))

import pandas as pd
import numpy as np
import pytest
from labels.label_builder import build_labels, validate_no_lookahead


def _make_ohlcv(n: int = 30) -> pd.DataFrame:
    close = 100.0 + np.cumsum(np.random.randn(n))
    return pd.DataFrame({
        "ticker": "TEST",
        "date": pd.date_range("2024-01-01", periods=n, freq="B"),
        "open": close * 0.99,
        "high": close * 1.01,
        "low": close * 0.98,
        "close": close,
        "volume": np.random.randint(100000, 1000000, n),
    })


def test_label_builder_no_lookahead_in_features():
    with pytest.raises(ValueError, match="LOOK-AHEAD BIAS"):
        validate_no_lookahead(["rsi_14", "label_return_pct", "sma_20"])


def test_labels_created():
    df = _make_ohlcv(30)
    df = build_labels(df, horizon=5)
    labeled = df.dropna(subset=["label_direction"])
    assert len(labeled) == 25  # 30 - 5 horizon rows


def test_label_direction_binary():
    df = _make_ohlcv(30)
    df = build_labels(df, horizon=5)
    labeled = df.dropna(subset=["label_direction"])
    assert set(labeled["label_direction"].unique()).issubset({0, 1})


def test_last_n_rows_have_no_label():
    df = _make_ohlcv(30)
    df = build_labels(df, horizon=5)
    assert df.tail(5)["label_direction"].isna().all()
