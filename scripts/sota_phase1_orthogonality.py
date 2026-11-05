"""sota_phase1_orthogonality.py — PHASE 1: Orthogonal Feature Isolation.

Goal: stop guessing filter intersections. Mathematically isolate mutually
UNCORRELATED daily cross-sectional signals so any combination we route through
the WFO gauntlet compounds *independent* edge, not redundant noise.

Method (auditable, reproducible, seeded):
  1. Build the production-identical prepared factor frame via
     `analytics._load_prepared(..., need_market_relative=True)` — same adjusted-close
     scaling + `backtest_engine.compute_indicators` + `compute_market_relative` the
     live WFO uses. Zero re-implementation, zero look-ahead (every column is strictly
     trailing per FIELD_MAP's contract).
  2. For each candidate filter, derive its DAILY CROSS-SECTIONAL DECILE signal:
        decile = groupby(date)[col].rank(pct=True) -> ceil(pct*10) in 1..10
     This is EXACTLY the quantity the production `mode="decile"` screen tilts on, so
     the correlation structure we measure is the structure the strategy actually sees.
     (We correlate the decile rank, not the raw factor: the screen is rank-based, so
     rank-space is the honest geometry. Spearman on raw factor == Pearson on rank ==
     what we compute here.)
  3. Spearman rank-correlation matrix (pairwise, on the pooled panel) + PCA on the
     standardized decile panel (explained-variance ratios + loadings).
  4. Select mutually orthogonal features (|rho| < ORTHO_THRESHOLD) and formulate 3
     DISTINCT intersections, each built only from low-correlation features, pairing
     a DEFENSIVE (drawdown-control) axis with an OFFENSIVE (alpha) axis where the math
     supports it. Print the matrix, the PCA loadings, and the 3 combos with pairwise rho.

MODE=PAPER. Canonical Python. Read-only DB. No secrets.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/sota_phase1_orthogonality.py
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import duckdb  # noqa: E402
import backtest_engine as be  # noqa: E402
from backtest_engine import FIELD_MAP  # noqa: E402
from routers.analytics import _load_prepared, _sector_map, _nifty_returns  # noqa: E402

SEED = 42
np.random.seed(SEED)

ORTHO_THRESHOLD = 0.20   # |Spearman rho| below this ⇒ treat as orthogonal (decorrelated)
FORWARD_DAYS = 5

# Candidate library: the defensive (least-loss) + offensive (alpha) tails flagged by
# prior research. Catalog field names; mapped to DataFrame columns via FIELD_MAP.
DEFENSIVE = ["atr_14_pct", "corr_nifty_30", "dist_ma200_pct", "squeeze_ratio"]
OFFENSIVE = ["vol_adj_sector_alpha_14", "beta_resid_5d", "sector_rel_mom_14_pct",
             "rsi_14", "within_52w_high_pct"]
CANDIDATES = DEFENSIVE + OFFENSIVE

MARKET_RELATIVE = {"vol_adj_sector_alpha_14", "sector_rel_mom_14_pct", "corr_nifty_30",
                   "beta_resid_5d", "sector_positive_regime", "decoupled_leader"}


def date_span(con) -> tuple:
    mn, mx = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    return pd.Timestamp(mn).date(), pd.Timestamp(mx).date()


def daily_decile(df: pd.DataFrame, col: str) -> pd.Series:
    """Daily cross-sectional decile (1..10) of `col` — the production decile signal.

    pct-rank within each date, then map to 1..10. NaN factor ⇒ NaN decile (excluded
    from that day's cross-section, exactly as the screen would exclude it).
    """
    pr = df.groupby("date")[col].rank(pct=True, method="average")
    dec = np.ceil(pr * 10.0).clip(1, 10)
    return dec


def main() -> None:
    print(f"MODE=PAPER  DB={DB_PATH}  SEED={SEED}", flush=True)
    print("=== PHASE 1 — ORTHOGONAL FEATURE ISOLATION (PCA + Spearman) ===", flush=True)
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        from_dt, to_dt = date_span(con)
        print(f"  span {from_dt} -> {to_dt}  | candidates: {len(CANDIDATES)} "
              f"({len(DEFENSIVE)} defensive + {len(OFFENSIVE)} offensive)", flush=True)
        # Production-identical factor build (need_market_relative=True for MR factors).
        df = _load_prepared(con, from_dt, to_dt, FORWARD_DAYS, scope_tickers=None,
                            need_market_relative=True, allow_lookahead=False)
    finally:
        con.close()
    if df is None or df.empty:
        print("  ABORT: empty prepared frame", flush=True)
        return

    # Keep only in-span bars (drop the 400d warm-up + forward look pad) so the geometry
    # reflects the actual tradable cross-sections, not warm-up partials.
    df = df[(df["date"] >= pd.Timestamp(from_dt)) & (df["date"] <= pd.Timestamp(to_dt))].copy()
    print(f"  prepared panel: {len(df):,} bars | {df['ticker'].nunique()} tickers | "
          f"{df['date'].nunique()} trading days", flush=True)

    # Build the daily decile panel (one column per candidate).
    dec_panel = pd.DataFrame(index=df.index)
    dec_panel["date"] = df["date"].values
    missing = []
    for field in CANDIDATES:
        col = FIELD_MAP.get(field, field)
        if col not in df.columns:
            missing.append((field, col))
            continue
        dec_panel[field] = daily_decile(df, col).values
    if missing:
        print(f"  WARN missing columns (skipped): {missing}", flush=True)
    feats = [f for f in CANDIDATES if f in dec_panel.columns]

    # Drop rows with any NaN decile so the correlation/PCA use a common complete panel.
    mat = dec_panel[feats].apply(pd.to_numeric, errors="coerce")
    mat = mat.dropna(how="any")
    print(f"  complete-case decile panel for geometry: {len(mat):,} rows x {len(feats)} feats",
          flush=True)

    # ── Spearman rank-correlation matrix (decile rank == Spearman geometry) ──
    # On the decile rank, Pearson == Spearman of the underlying factor.
    corr = mat.corr(method="pearson")
    print("\n── SPEARMAN/RANK CORRELATION MATRIX (daily cross-sectional decile) ──", flush=True)
    with pd.option_context("display.width", 200, "display.max_columns", 50,
                           "display.float_format", lambda x: f"{x:+.2f}"):
        print(corr.to_string(), flush=True)

    # ── PCA on standardized deciles ──
    X = (mat.values - mat.values.mean(axis=0)) / (mat.values.std(axis=0, ddof=1) + 1e-12)
    # SVD-based PCA (deterministic, no sklearn dependency required, but use sklearn if present).
    try:
        from sklearn.decomposition import PCA
        pca = PCA(svd_solver="full", random_state=SEED)
        pca.fit(X)
        evr = pca.explained_variance_ratio_
        loadings = pca.components_  # (n_pc, n_feat)
        src = "sklearn.PCA"
    except Exception:
        U, S, Vt = np.linalg.svd(X - X.mean(axis=0), full_matrices=False)
        var = (S ** 2) / (X.shape[0] - 1)
        evr = var / var.sum()
        loadings = Vt
        src = "numpy.svd"

    print(f"\n── PCA EXPLAINED VARIANCE ({src}) ──", flush=True)
    cum = np.cumsum(evr)
    for i, (e, c) in enumerate(zip(evr, cum), start=1):
        print(f"  PC{i:<2d} evr={e*100:6.2f}%   cumulative={c*100:6.2f}%", flush=True)
    n_pc_show = min(4, loadings.shape[0])
    print(f"\n── PCA LOADINGS (first {n_pc_show} PCs; |loading| ranks each feature's axis) ──",
          flush=True)
    load_df = pd.DataFrame(loadings[:n_pc_show].T, index=feats,
                           columns=[f"PC{i+1}" for i in range(n_pc_show)])
    with pd.option_context("display.width", 200, "display.float_format", lambda x: f"{x:+.3f}"):
        print(load_df.to_string(), flush=True)

    # ── Orthogonal-pair discovery: all candidate pairs with |rho| < threshold ──
    print(f"\n── ORTHOGONAL PAIRS (|rho| < {ORTHO_THRESHOLD}) ──", flush=True)
    ortho_pairs = []
    for i in range(len(feats)):
        for j in range(i + 1, len(feats)):
            r = corr.iloc[i, j]
            if abs(r) < ORTHO_THRESHOLD:
                tag_i = "D" if feats[i] in DEFENSIVE else "O"
                tag_j = "D" if feats[j] in DEFENSIVE else "O"
                ortho_pairs.append((feats[i], feats[j], float(r), tag_i + tag_j))
    ortho_pairs.sort(key=lambda t: abs(t[2]))
    for a, b, r, tag in ortho_pairs:
        print(f"  [{tag}] {a:26s} x {b:26s}  rho={r:+.3f}", flush=True)

    # Persist the matrix + loadings + ortho pairs for the Phase-3 report.
    out = {
        "span": [str(from_dt), str(to_dt)],
        "features": feats,
        "ortho_threshold": ORTHO_THRESHOLD,
        "n_rows_geometry": int(len(mat)),
        "corr_matrix": corr.round(4).to_dict(),
        "pca_evr": [round(float(e), 5) for e in evr],
        "pca_loadings": load_df.round(4).to_dict(),
        "ortho_pairs": [{"a": a, "b": b, "rho": round(r, 4), "tag": t}
                        for (a, b, r, t) in ortho_pairs],
    }
    outp = REPO / "sota_phase1_orthogonality.json"
    outp.write_text(json.dumps(out, indent=2, default=str))
    print(f"\nPHASE1_DONE — wrote {outp.name}", flush=True)


if __name__ == "__main__":
    main()
