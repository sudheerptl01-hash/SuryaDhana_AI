"""generate_oos_propensity.py — leak-safe out-of-sample propensity P(up over next 5 days).

Trains a SINGLE XGBoost direction model on PAST data (date <= TRAIN_END), then scores a
holdout window strictly AFTER TRAIN_END, so the propensity is look-ahead-free by
construction: the model never saw the scored dates, and each scored bar uses only
trailing features available at that bar. Persists per-(ticker, date) prob_up into
`ml_oos_predictions` for the backtest to merge point-in-time.

Stages:
  --stage smoke : train on 1 month, score a 15-day and a 45-day window, REPORT only
                  (no DB write). Validates the pipeline + sanity before the real train.
  --stage full  : train on all data <= TRAIN_END (default 2025-05-31), score
                  SCORE_START..present (~last year), persist to ml_oos_predictions +
                  save the deployable model.

MODE=PAPER. Canonical python only. Never uses future data.

Run:
  DB_PATH=.../data/market.duckdb /Users/sudheer/Desktop/jupyter_env/bin/python \
      scripts/generate_oos_propensity.py --stage smoke
  ...                                    --stage full
"""
from __future__ import annotations

import os
import sys
import argparse
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))                              # for `shared.logging`
DB_PATH = os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH") \
    or str(REPO / "data" / "market.duckdb")

HORIZON = 5
EMBARGO_DAYS = HORIZON + 2          # purge gap between train labels and the score window
MODEL_OUT = REPO / "services" / "ui-api" / "models" / "ml_workspace" / "holdout_2025_05.pkl"

# Curated leakage-safe feature set (mirrors ml_workspace.FEATURE_COLUMNS); intersected
# with the live ml_features columns at runtime so a schema drift can never crash the run.
FEATURE_COLUMNS = [
    "ret_1d", "ret_5d", "ret_20d", "log_ret",
    "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
    "rsi_14", "rsi_7", "rsi_28", "macd", "macd_signal", "macd_hist",
    "bollinger_pctb", "bb_width", "atr_14_pct", "realized_vol_20d",
    "volume_zscore", "volume_ratio", "obv", "gap_pct", "high_low_ratio", "close_position",
    "stoch_k", "stoch_d", "williams_r", "roc_5", "roc_10", "roc_20", "mfi_14", "cmf_20",
    "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
    "india_vix", "vix_zscore", "nifty_ret_5d", "nifty_regime", "market_breadth", "usd_inr",
    "trailing_pe", "price_to_book", "ev_to_ebitda", "peg_ratio",
    "revenue_growth", "gross_margins", "operating_margins", "profit_margins",
    "return_on_equity", "return_on_assets", "debt_to_equity", "current_ratio", "altman_z",
]

# ── Reuse the production DirectionClassifier (load by file path; avoids the `models`
#    package-name collision between services/ml-service and services/ui-api) ──────────
_xgb_path = REPO / "services" / "ml-service" / "models" / "xgb_classifier.py"
_spec = importlib.util.spec_from_file_location("sd_xgb_classifier", str(_xgb_path))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
DirectionClassifier = _mod.DirectionClassifier


def _present_features(con) -> list[str]:
    cols = {d[0] for d in con.execute("SELECT * FROM ml_features LIMIT 0").description}
    return [c for c in FEATURE_COLUMNS if c in cols]


def load_join(con, feats: list[str], start: str, end: str) -> pd.DataFrame:
    """ml_features ⋈ ml_labels (horizon=5) over [start, end] — the model's own training
    features + the forward-direction target. Mirrors ml_workspace._load_training_frame."""
    feat_sql = ", ".join(f"f.{c}" for c in feats)
    sql = f"""
        SELECT f.date, f.ticker, {feat_sql}, l.label_direction AS y
        FROM ml_features f
        JOIN ml_labels l ON f.ticker = l.ticker AND f.date = l.date
        WHERE l.horizon_days = 5 AND l.label_return_pct IS NOT NULL
          AND l.label_direction IS NOT NULL
          AND f.date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)
        ORDER BY f.date, f.ticker
    """
    df = con.execute(sql, [start, end]).fetchdf()
    if not df.empty:
        # Coerce every feature to numeric: some columns (e.g. nifty_regime) are stored as
        # object/text and may be all-NULL. errors="coerce" → NaN, which the classifier's
        # internal inf/nan→0 fill handles. Keeps the 55-col schema stable (feature parity).
        for c in feats:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.replace([np.inf, -np.inf], np.nan)
        df["date"] = pd.to_datetime(df["date"])
    return df


def _embargoed_train_end(train_end: str, score_start: str) -> str:
    """Cap the training feature-date so no training label can realize inside the score
    window. A row at date D carries a label realized ~HORIZON trading days later; if that
    realization reaches SCORE_START it leaks the scored period into training. Purging the
    last EMBARGO_DAYS of the train window (López de Prado embargo for a forward holdout)
    removes that overlap. Returns the stricter of (train_end, score_start - EMBARGO_DAYS)."""
    cap = (pd.Timestamp(score_start) - pd.Timedelta(days=EMBARGO_DAYS)).date()
    eff = min(pd.Timestamp(train_end).date(), cap)
    return str(eff)


def train_model(con, feats, train_start, train_end, score_start):
    """Fit a DirectionClassifier on [train_start, embargoed(train_end)] with a temporal
    tail held out (within the train window) for early stopping — no label leakage into the
    score window (the last EMBARGO_DAYS of the train window are purged)."""
    eff_end = _embargoed_train_end(train_end, score_start)
    if eff_end != train_end:
        print(f"  embargo: train_end {train_end} → {eff_end} "
              f"(purged last {EMBARGO_DAYS}d so labels can't realize into score window)",
              flush=True)
    tr = load_join(con, feats, train_start, eff_end)
    if tr.empty:
        raise SystemExit(f"No training rows in {train_start}..{eff_end}")
    tr = tr.sort_values("date").reset_index(drop=True)
    cut = tr["date"].quantile(0.85)
    trn, val = tr[tr["date"] <= cut], tr[tr["date"] > cut]
    if val.empty:                                   # tiny window (smoke): no early stop
        trn, val = tr, None
    clf = DirectionClassifier()
    if val is None:
        clf.fit(trn[feats], trn["y"].astype(int))
    else:
        clf.fit(trn[feats], trn["y"].astype(int), val[feats], val["y"].astype(int))
    return clf, tr


def score_window(clf, con, feats, score_start, score_end) -> pd.DataFrame:
    sc = load_join(con, feats, score_start, score_end)
    if sc.empty:
        return sc
    sc = sc.copy()
    sc["prob_up"] = clf.predict_proba(sc[feats])[:, 1]
    return sc


def _auc(y, p) -> float | None:
    try:
        from sklearn.metrics import roc_auc_score
        if len(np.unique(y)) < 2:
            return None
        return float(roc_auc_score(y, p))
    except Exception:
        return None


def report(tag, tr, sc):
    print(f"\n── {tag} ──", flush=True)
    if sc.empty:
        print("  (no rows scored)", flush=True); return
    p = sc["prob_up"]
    leak_ok = tr["date"].max() < sc["date"].min()
    print(f"  train: {tr['date'].min().date()}..{tr['date'].max().date()}  "
          f"({len(tr):,} rows, {tr['ticker'].nunique()} tickers)", flush=True)
    print(f"  score: {sc['date'].min().date()}..{sc['date'].max().date()}  "
          f"({len(sc):,} rows, {sc['ticker'].nunique()} tickers)", flush=True)
    print(f"  prob_up  mean={p.mean():.4f}  std={p.std():.4f}  "
          f"min={p.min():.4f}  max={p.max():.4f}", flush=True)
    print(f"  base up-rate (scored)={sc['y'].mean():.4f}   "
          f"AUC={_auc(sc['y'], p)}", flush=True)
    print(f"  LEAK-SAFE (train.max < score.min): {'PASS ✅' if leak_ok else 'FAIL ❌'} "
          f"(gap {(sc['date'].min()-tr['date'].max()).days}d)", flush=True)


# ── Persistence (mirror slippage_store defensive single-writer pattern) ───────────────
DDL = """
CREATE TABLE IF NOT EXISTS ml_oos_predictions (
    ticker VARCHAR, date DATE, prob_up DOUBLE,
    model_trained_until DATE, horizon_days INTEGER
);
"""


def _open_write_conn(retries=4, base_sleep=0.3):
    import time
    for attempt in range(retries):
        try:
            return duckdb.connect(DB_PATH, read_only=False)
        except Exception:
            if attempt < retries - 1:
                time.sleep(min(base_sleep * (2 ** attempt), 2.0))
    return None


def persist(sc: pd.DataFrame, model_trained_until: str) -> bool:
    """Idempotent write of (ticker,date,prob_up,model_trained_until,horizon=5). Returns
    True on success; never raises into the caller (single-writer lock may be held)."""
    wc = _open_write_conn()
    if wc is None:
        print("  ⚠ could not acquire DuckDB write lock (data-service may hold it); "
              "skipped persistence.", flush=True)
        return False
    try:
        out = pd.DataFrame({
            # plain object str — DuckDB's pandas scan rejects pandas StringDtype ('str')
            "ticker": sc["ticker"].astype(str).astype(object),
            "date": pd.to_datetime(sc["date"]),
            "prob_up": sc["prob_up"].astype(float),
            "model_trained_until": pd.to_datetime(model_trained_until),
            "horizon_days": int(HORIZON),
        })
        wc.execute(DDL)
        wc.execute("DELETE FROM ml_oos_predictions WHERE horizon_days = 5")
        wc.register("oos_df", out)
        wc.execute("INSERT INTO ml_oos_predictions SELECT CAST(ticker AS VARCHAR), "
                   "CAST(date AS DATE), CAST(prob_up AS DOUBLE), "
                   "CAST(model_trained_until AS DATE), CAST(horizon_days AS INTEGER) "
                   "FROM oos_df")
        wc.unregister("oos_df")
        n = wc.execute("SELECT COUNT(*) FROM ml_oos_predictions").fetchone()[0]
        bad = wc.execute("SELECT COUNT(*) FROM ml_oos_predictions "
                         "WHERE model_trained_until >= date").fetchone()[0]
        print(f"  persisted {n:,} rows to ml_oos_predictions; leak-check rows "
              f"(model_trained_until >= date) = {bad}", flush=True)
        return bad == 0
    except Exception as e:
        print(f"  ⚠ persistence failed: {str(e)[:120]}", flush=True)
        return False
    finally:
        try:
            wc.close()
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["smoke", "full"], default="smoke")
    ap.add_argument("--train-end", default="2025-05-31")
    ap.add_argument("--score-start", default="2025-06-01")
    ap.add_argument("--score-end", default="2026-12-31")
    args = ap.parse_args()

    con = duckdb.connect(DB_PATH, read_only=True)
    feats = _present_features(con)
    print(f"MODE=PAPER  DB={DB_PATH}\nfeatures present: {len(feats)}/{len(FEATURE_COLUMNS)}",
          flush=True)

    if args.stage == "smoke":
        print("\n=== STAGE A — SMOKE TEST (train 1 month, score 15d + 45d, no persist) ===",
              flush=True)
        clf, tr = train_model(con, feats, "2025-03-01", "2025-03-31", "2025-04-01")
        report("15-day window (2025-04-01 → 2025-04-15)",
               tr, score_window(clf, con, feats, "2025-04-01", "2025-04-15"))
        report("45-day window (2025-04-01 → 2025-05-15)",
               tr, score_window(clf, con, feats, "2025-04-01", "2025-05-15"))
        print("\nSMOKE_DONE — review prob_up sanity + LEAK-SAFE before running --stage full",
              flush=True)
    else:
        print(f"\n=== STAGE B — FULL (train <= {args.train_end}, score "
              f"{args.score_start} → present) ===", flush=True)
        data_start = str(con.execute("SELECT MIN(date) FROM ml_features").fetchone()[0])
        clf, tr = train_model(con, feats, data_start, args.train_end, args.score_start)
        sc = score_window(clf, con, feats, args.score_start, args.score_end)
        report("HOLDOUT score", tr, sc)
        eff_end = str(tr["date"].max().date())   # honest (embargoed) cutoff for leak-check
        # Release the read-only handle BEFORE persist: DuckDB refuses a read-write
        # connection while any read-only handle to the same file is open in-process.
        con.close()
        ok = persist(sc, eff_end)
        MODEL_OUT.parent.mkdir(parents=True, exist_ok=True)
        clf.save(str(MODEL_OUT))
        print(f"  saved model → {MODEL_OUT}", flush=True)
        print(f"\nFULL_DONE — persisted={ok}", flush=True)
        return

    con.close()


if __name__ == "__main__":
    main()
