"""
Unit tests for the data-quality + ML-dataset fixes:
  - ingestion quality gate (services/data-service/ingest.py)
  - instrument classification (services/data-service/instruments.py)
  - cost-aware / triple-barrier labels (services/feature-service/feature_engine.py)
  - purged time split + date-based walk-forward folds (services/ml-service/training/splits.py)
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT, ROOT / "services" / "data-service", ROOT / "services" / "feature-service",
          ROOT / "services" / "ml-service"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ingest  # noqa: E402
from feature_engine import DEFAULT_TRAIN_FEATURES, build_labels_v2  # noqa: E402
from instruments import classify_universe  # noqa: E402
from training.splits import date_folds, purged_time_split  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


def _bars(closes, start="2024-01-01", volume=100_000):
    closes = np.asarray(closes, dtype=float)
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame({
        "ticker": "TEST", "date": dates,
        "open": closes, "high": closes * 1.01, "low": closes * 0.99, "close": closes,
        "volume": volume, "adjusted_close": closes,
    })


# ── Quality gate ───────────────────────────────────────────────────────────────

def test_spike_and_revert_is_quarantined():
    closes = [100.0] * 15 + [9500.0] + [101.0] * 15  # CYBERTECH-style bad tick
    clean, bad = ingest.validate_bars(_bars(closes))
    assert list(bad["reason"]) == ["spike_and_revert"]
    assert bad["close"].iloc[0] == 9500.0
    assert len(clean) == len(closes) - 1


def test_two_day_spike_is_quarantined():
    closes = [50.0] * 12 + [4800.0, 4900.0] + [51.0] * 12
    _, bad = ingest.validate_bars(_bars(closes))
    assert set(bad["close"]) == {4800.0, 4900.0}


def test_sustained_level_change_is_not_flagged():
    # A genuine re-rating / unadjusted level change persists — not a spike.
    closes = [100.0] * 15 + [200.0] * 15
    _, bad = ingest.validate_bars(_bars(closes))
    assert bad.empty


def test_strong_rally_is_not_flagged():
    closes = [100 * (1.2 ** i) for i in range(10)] + [100 * 1.2 ** 9] * 10  # 5x in 9 days
    _, bad = ingest.validate_bars(_bars(closes))
    assert bad.empty


def test_small_ohlc_envelope_error_is_repaired_not_rejected():
    df = _bars([100.0] * 10)
    df.loc[3, "open"] = df.loc[3, "high"] * 1.005  # 0.5% above high — vendor rounding
    clean, bad = ingest.validate_bars(df)
    assert bad.empty
    assert clean.loc[3, "high"] >= clean.loc[3, "open"]


def test_large_ohlc_violation_and_nonpositive_rejected():
    df = _bars([100.0] * 10)
    df.loc[2, "close"] = df.loc[2, "high"] * 1.5
    df.loc[5, "low"] = 0.0
    _, bad = ingest.validate_bars(df)
    assert set(bad["reason"]) == {"ohlc_inconsistent", "nonpositive_or_missing_price"}


def test_flat_zero_volume_placeholder_rejected():
    df = _bars([100.0] * 10)
    df.loc[4, ["open", "high", "low", "close"]] = 100.0
    df.loc[4, "volume"] = 0
    _, bad = ingest.validate_bars(df)
    assert list(bad["reason"]) == ["flat_zero_volume_bar"]


def test_unsettled_today_bar_is_dropped_intraday_and_kept_after_close():
    today = datetime(2026, 9, 25, 11, 0, tzinfo=IST)
    df = pd.DataFrame({"date": pd.to_datetime(["2026-09-24", "2026-09-25"])})
    assert len(ingest._drop_unsettled_today(df, today)) == 1
    assert len(ingest._drop_unsettled_today(df, today.replace(hour=16, minute=5))) == 2


# ── Incremental refresh: adjustment drift → full re-fetch ───────────────────────

class _FakeYahoo:
    def __init__(self, df):
        self.df = df

    def fetch_single(self, ticker, start, end=None):
        return self.df[(self.df["date"].dt.date >= start) & (self.df["date"].dt.date <= end)]

    def to_dataframe(self, batch):
        return batch.copy()


class _FakeStore:
    def __init__(self, df, foreign=0):
        self.df = df.copy()
        self.foreign = foreign
        self.replaced = None
        self.upserted = None

    def get_latest_ohlcv_date(self, t):
        return self.df["date"].max().date()

    def count_non_source_rows(self, t, s):
        return self.foreign

    def get_earliest_ohlcv_date(self, t):
        return self.df["date"].min().date()

    def get_ohlcv(self, t, start=None, end=None):
        return self.df[self.df["date"].dt.date >= start].copy()

    def replace_ticker_history(self, t, df, source):
        self.replaced = df
        return len(df)

    def upsert_ohlcv(self, df, source):
        self.upserted = df
        return len(df)

    def insert_quarantine(self, df, source):
        return len(df)

    def delete_ohlcv_dates(self, t, dates):
        pass


def _yahoo_series(n=400, factor=1.0):
    closes = np.linspace(100, 140, n) * factor
    return _bars(closes, start="2025-01-01")


def test_incremental_refresh_appends_when_basis_unchanged():
    full = _yahoo_series()
    stored = full.iloc[:-5]
    now = datetime.combine(full["date"].max().date(), datetime.min.time(), IST).replace(hour=17)
    store = _FakeStore(stored)
    r = ingest.refresh_ticker(_FakeYahoo(full), store, "TEST", now_ist=now)
    assert r.status == ingest.STATUS_UPDATED
    assert store.replaced is None and store.upserted is not None


def test_split_readjustment_triggers_full_replace():
    full = _yahoo_series()
    stored = _yahoo_series(factor=2.0).iloc[:-5]  # stored on the pre-split basis
    now = datetime.combine(full["date"].max().date(), datetime.min.time(), IST).replace(hour=17)
    store = _FakeStore(stored)
    r = ingest.refresh_ticker(_FakeYahoo(full), store, "TEST", now_ist=now)
    assert r.status == ingest.STATUS_READJUSTED
    assert store.replaced is not None


def test_mixed_source_series_is_rebuilt():
    full = _yahoo_series()
    now = datetime.combine(full["date"].max().date(), datetime.min.time(), IST).replace(hour=17)
    store = _FakeStore(full, foreign=12)  # legacy ICICI rows present
    r = ingest.refresh_ticker(_FakeYahoo(full), store, "TEST", now_ist=now)
    assert r.status == ingest.STATUS_READJUSTED


def test_empty_fetch_reports_no_data_not_current():
    full = _yahoo_series()
    store = _FakeStore(full)
    empty = _FakeYahoo(full.iloc[0:0])
    r = ingest.refresh_ticker(empty, store, "TEST")
    assert r.status == ingest.STATUS_NO_DATA


# ── Instrument classification ──────────────────────────────────────────────────

def test_classification_uses_nse_lists_not_name_patterns(tmp_path):
    pd.DataFrame({"SYMBOL": ["RELIANCE", "SKYGOLD", "GOLDIAM"]}).to_csv(tmp_path / "nse_equity_list.csv", index=False)
    pd.DataFrame({"Symbol": ["GOLDBEES", "LIQUIDBEES"]}).to_csv(tmp_path / "nse_etf_list.csv", index=False)
    df = classify_universe(["RELIANCE", "SKYGOLD", "GOLDIAM", "GOLDBEES", "LIQUIDBEES",
                            "DUMMYVEDL1", "AXISGOLD", "OLDNAME"], tmp_path).set_index("ticker")
    assert df.loc["SKYGOLD", "instrument_type"] == "EQUITY"      # jewellery company, not an ETF
    assert df.loc["GOLDIAM", "ml_eligible"]
    assert df.loc["GOLDBEES", "instrument_type"] == "ETF"
    assert df.loc["DUMMYVEDL1", "instrument_type"] == "INVALID"
    assert df.loc["AXISGOLD", "instrument_type"] == "ETF"
    assert df.loc["OLDNAME", "instrument_type"] == "UNKNOWN" and not df.loc["OLDNAME", "ml_eligible"]


# ── Labels ─────────────────────────────────────────────────────────────────────

def _label_frame(closes, highs=None, lows=None, dates=None, adj=None):
    closes = np.asarray(closes, float)
    return pd.DataFrame({
        "date": dates if dates is not None else pd.bdate_range("2024-01-01", periods=len(closes)),
        "high": highs if highs is not None else closes,
        "low": lows if lows is not None else closes,
        "close": closes,
        "adjusted_close": adj if adj is not None else closes,
    })


def test_direction_requires_beating_cost_hurdle():
    closes = [100, 100, 100, 100, 100, 100.10, 100, 100, 100, 100, 100.30]
    lb = build_labels_v2(_label_frame(closes), horizon=5, cost_hurdle_pct=0.15)
    assert lb.loc[0, "label_return_pct"] == pytest.approx(0.10)
    assert lb.loc[0, "label_direction"] == 0          # +0.10% < 0.15% cost → not "UP"
    assert lb.loc[5, "label_direction"] == 1          # +0.20% beats the hurdle


def test_triple_barrier_first_touch_and_timeout():
    closes = [100] * 12
    highs = [100] * 12
    lows = [100] * 12
    highs[2] = 102.5                                   # target touched on day 2
    lows[8] = 97.0                                     # stop touched later for row 6
    lb = build_labels_v2(_label_frame(closes, highs, lows), horizon=5)
    assert lb.loc[0, "label_barrier"] == 1
    assert lb.loc[6, "label_barrier"] == -1
    assert lb.loc[2, "label_barrier"] == 0             # window bars 3..7 touch neither barrier
    assert lb["label_return_pct"].iloc[-5:].isna().all()  # no future → no label


def test_same_bar_barrier_tie_resolves_to_stop():
    closes = [100.0] * 10
    highs = [100.0] * 10
    lows = [100.0] * 10
    highs[1], lows[1] = 103.0, 97.0                   # one wide bar touches both barriers
    lb = build_labels_v2(_label_frame(closes, highs, lows), horizon=5)
    assert lb.loc[0, "label_barrier"] == -1


def test_labels_use_adjusted_close_total_return():
    closes = [100.0] * 10
    adj = [98.0] * 5 + [100.0] * 5                     # dividend-adjusted history
    lb = build_labels_v2(_label_frame(closes, adj=adj), horizon=5)
    assert lb.loc[0, "label_return_pct"] == pytest.approx((100 / 98 - 1) * 100)


def test_labels_masked_across_data_gap_and_impossible_jump():
    dates = list(pd.bdate_range("2024-01-01", periods=6)) + list(pd.bdate_range("2024-03-01", periods=6))
    lb = build_labels_v2(_label_frame([100.0] * 12, dates=pd.to_datetime(dates)), horizon=5)
    assert lb.loc[2, "label_return_pct"] != lb.loc[2, "label_return_pct"]  # NaN: spans a 2-month hole

    closes = [100.0] * 6 + [300.0] * 6                                      # 3x overnight = data break
    lb2 = build_labels_v2(_label_frame(closes), horizon=5)
    assert lb2.loc[1:5, "label_return_pct"].isna().all()


def test_default_training_features_exclude_price_levels_and_labels():
    banned = {"sma_20", "sma_50", "sma_200", "ema_12", "ema_26", "macd", "atr_14", "obv",
              "label_barrier", "label_direction", "label_return_pct", "trailing_pe"}
    assert not banned & set(DEFAULT_TRAIN_FEATURES)


# ── Time split ─────────────────────────────────────────────────────────────────

def _panel(n_dates=100, n_tickers=30):
    dates = pd.bdate_range("2024-01-01", periods=n_dates)
    return pd.DataFrame({
        "date": np.repeat(dates, n_tickers),
        "ticker": np.tile([f"T{i}" for i in range(n_tickers)], n_dates),
    })


def test_purged_split_separates_dates_with_gap():
    df = _panel()
    sp = purged_time_split(df["date"], val_frac=0.2, purge=5)
    tr_dates = set(df.iloc[sp.train_idx]["date"])
    va_dates = set(df.iloc[sp.val_idx]["date"])
    assert not tr_dates & va_dates
    all_dates = sorted(df["date"].unique())
    gap = all_dates.index(min(va_dates)) - all_dates.index(max(tr_dates)) - 1
    assert gap == 5
    # every ticker appears on both sides — the split is by time, not by ticker
    assert set(df.iloc[sp.train_idx]["ticker"]) == set(df.iloc[sp.val_idx]["ticker"])


def test_date_folds_are_measured_in_dates_not_rows():
    df = _panel(n_dates=200, n_tickers=50)             # 10,000 rows
    folds = date_folds(df["date"], train_dates=60, test_dates=20, n_folds=5, purge=5)
    assert len(folds) == 5
    tr, te = folds[0]
    assert df.iloc[tr]["date"].nunique() == 60
    assert df.iloc[te]["date"].nunique() == 20
    assert df.iloc[tr]["date"].max() < df.iloc[te]["date"].min()


# ── Real DuckDB: replace operations must be repeatable on overlapping keys ─────
# (DuckDB 1.1 rejects DELETE + re-INSERT of one primary key inside a transaction;
#  a fake store cannot catch that, so these run against an actual database.)

from storage.duckdb_store import DuckDBStore  # noqa: E402


@pytest.fixture()
def real_store(tmp_path):
    store = DuckDBStore(str(tmp_path / "t.duckdb"))
    yield store
    store.close()


def test_replace_ticker_history_twice_overlapping(real_store):
    first = _bars([100.0 + i for i in range(10)]).drop(columns=["ticker"])
    real_store.replace_ticker_history("ABC", first, "yahoo_v8")
    second = _bars([200.0 + i for i in range(8)], start="2024-01-03").drop(columns=["ticker"])
    real_store.replace_ticker_history("ABC", second, "yahoo_v8")
    got = real_store.get_ohlcv("ABC")
    assert len(got) == 8                                   # dates absent from the new history are gone
    assert got["close"].iloc[0] == 200.0                   # overlapping dates replaced


def test_replace_instruments_twice(real_store):
    df = pd.DataFrame({"ticker": ["A", "B"], "instrument_type": ["EQUITY", "ETF"],
                       "ml_eligible": [True, False], "classified_by": ["x", "y"]})
    real_store.replace_instruments(df)
    real_store.replace_instruments(df.iloc[:1].assign(instrument_type="ETF", ml_eligible=False))
    inst = real_store.get_instruments()
    assert inst["ticker"].tolist() == ["A"] and not inst["ml_eligible"].iloc[0]


def test_replace_ml_dataset_twice_is_full_replacement(real_store):
    dates = pd.to_datetime(["2024-01-01", "2024-01-02"])
    feats = pd.DataFrame({"ticker": ["A", "A"], "date": dates, "rsi_14": [40.0, 50.0], "feature_version": "v2"})
    labels = pd.DataFrame({"ticker": ["A", "A"], "date": dates, "horizon_days": [5, 5],
                           "label_direction": [1, 0], "label_return_pct": [1.0, -1.0]})
    real_store.replace_ml_dataset(feats, labels)
    feats2 = feats.iloc[1:].assign(rsi_14=[55.0]).drop(columns=["feature_version"])
    real_store.replace_ml_dataset(feats2, labels.iloc[1:])
    f = real_store.get_ml_features()
    assert len(f) == 1 and f["rsi_14"].iloc[0] == 55.0
    assert f["feature_version"].isna().iloc[0]              # no stale value carried over
    assert len(real_store.get_ml_labels()) == 1
