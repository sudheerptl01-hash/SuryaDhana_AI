"""suryadhana_decile_screen.py — Phase-2 combinatorial DECILE-10 screen for the two
SuryaDhana structural alpha features (IDS dropped — no delivery data in the DuckDB).

Targets ONLY Decile 10 (the top tenth of each day's cross-section) for each feature, then
intersects the daily top-decile masks for the 2-way combo. This is the unconstrained
signal-research pass (overlap-corrected daily-basket proxy, /HORIZON de-overlap, MIN_TRADES
cull) — hypothesis generation, NOT a capital certification. Survivors go to the production
walk-forward gauntlet (suryadhana_wfo_gauntlet.py) where Pillar B (Amihud/√-impact) and
Pillar C (inverse-vol sizing) are active.

Mirrors scripts/decile_combinatorial_optimizer.py exactly for the prep + metric recipe, and
injects the REAL Nifty-50 (NIFTY1) return series so the β-residual is a genuine market beta.

MODE=PAPER. Canonical Python. Read-only DB. No secrets.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/suryadhana_decile_screen.py
"""
from __future__ import annotations

import os
import sys
import itertools
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import backtest_engine as be  # noqa: E402
import decile_combinatorial_optimizer as dco  # noqa: E402  (reuse MetricEngine + constants)

# The two buildable SuryaDhana structural features (DataFrame column names).
FEATURES = ["beta_resid_5d", "vol_adj_sector_alpha_14"]
SHORT = {"beta_resid_5d": "IdioMom(β-resid)", "vol_adj_sector_alpha_14": "VolAdjSectAlpha"}
TOP_DECILE = 10            # we target Decile 10 only, per the SuryaDhana brief
HORIZON = dco.HORIZON      # 5
FRICTION = dco.FRICTION    # 0.0015
MIN_TRADES = dco.MIN_TRADES


def log(m: str) -> None:
    print(m, flush=True)


def nifty_returns(con) -> dict:
    nr = con.execute("SELECT date, close, adjusted_close FROM ohlcv WHERE ticker='NIFTY1' "
                     "ORDER BY date").fetchall()
    ndf = pd.DataFrame(nr, columns=["date", "close", "adjusted_close"])
    ndf["date"] = pd.to_datetime(ndf["date"])
    px = pd.to_numeric(ndf["adjusted_close"], errors="coerce").fillna(
        pd.to_numeric(ndf["close"], errors="coerce"))
    return {d: (float(r) if pd.notna(r) else 0.0) for d, r in zip(ndf["date"], px.pct_change())}


def load_prepared(con) -> pd.DataFrame:
    """OHLCV → adjusted basis → trailing factors (+ real-Nifty market-relative) → fwd 5d NET."""
    rows = con.execute(
        "SELECT ticker, date, open, high, low, close, volume, adjusted_close "
        "FROM ohlcv ORDER BY ticker, date").fetchall()
    df = pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low",
                                     "close", "volume", "adjusted_close"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "adjusted_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    adj = (df["adjusted_close"] / df["close"]).where(
        (df["close"] > 0) & df["adjusted_close"].notna(), 1.0)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c] * adj
    df = df.drop(columns=["adjusted_close"])

    df = be.compute_indicators(df)
    df = be.compute_market_relative(df, dco.sector_map(), market_ret_by_date=nifty_returns(con))

    df = df.sort_values(["ticker", "date"])
    fwd = df.groupby("ticker", sort=False)["close"].shift(-HORIZON)
    df["net_ret"] = (fwd / df["close"] - 1.0) - FRICTION

    keep = ["ticker", "date", "net_ret", *FEATURES]
    df = df[keep].replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=["net_ret"]).sort_values(["date", "ticker"]).reset_index(drop=True)
    return df


def assign_top_decile(df: pd.DataFrame) -> None:
    """Per-day cross-sectional decile (1..10) for each feature; boolean Decile-10 mask."""
    for f in FEATURES:
        r = df.groupby("date")[f].rank(pct=True, method="first")
        dec = np.ceil(r * 10).clip(1, 10)
        df[f"top10_{f}"] = (dec == TOP_DECILE).to_numpy()


def fpf(pf: float) -> str:
    return "inf" if pf == float("inf") else f"{pf:.2f}"


def main() -> None:
    log(f"MODE=PAPER  DB={DB_PATH}")
    log("=== SuryaDhana Phase-2 DECILE-10 SCREEN (2 features; IDS dropped — no delivery data) ===")
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        df = load_prepared(con)
    finally:
        con.close()
    log(f"  prepared: {len(df):,} rows · {df['ticker'].nunique()} tickers · "
        f"{df['date'].min().date()}→{df['date'].max().date()}")
    for f in FEATURES:
        log(f"  {SHORT[f]:18s} coverage: {df[f].notna().mean()*100:5.1f}% non-null")

    assign_top_decile(df)
    engine = dco.MetricEngine(df)

    configs = []
    # Solo: each feature's Decile-10.
    for f in FEATURES:
        configs.append((f"{SHORT[f]} · D10", df[f"top10_{f}"].to_numpy(dtype=bool)))
    # 2-way intersection (Decile-10 AND Decile-10).
    inter = df[f"top10_{FEATURES[0]}"].to_numpy(dtype=bool) & df[f"top10_{FEATURES[1]}"].to_numpy(dtype=bool)
    configs.append((f"{SHORT[FEATURES[0]]} ∩ {SHORT[FEATURES[1]]} · D10∩D10", inter))

    # Universe-thinning diagnostic: how many names per day survive each mask on average.
    ndays = df["date"].nunique()
    log("\n── Daily universe thinning (avg names/day passing the Decile-10 mask) ──")
    for name, mask in configs:
        per_day = df.loc[mask].groupby("date").size()
        avg = per_day.mean() if len(per_day) else 0.0
        log(f"  {name:48s} avg {avg:6.1f}/day · total {int(mask.sum()):>7,} signals · "
            f"active {len(per_day)}/{ndays} days")

    log("\n── Overlap-corrected daily-basket screen (signal proxy; /HORIZON de-overlap) ──")
    log(f"  {'Config':50s} {'trades':>7} {'win%':>6} {'PF':>6} {'avg%':>7} "
        f"{'CAGR%':>7} {'MaxDD%':>8} {'Calmar':>7}")
    results = []
    for name, mask in configs:
        m = engine.evaluate(mask)
        if m is None:
            log(f"  {name:50s} {'(< %d trades — culled)' % MIN_TRADES:>40s}")
            results.append((name, None))
            continue
        results.append((name, m))
        cal = "inf" if not np.isfinite(m["calmar"]) else f"{m['calmar']:.2f}"
        log(f"  {name:50s} {m['trades']:>7,} {m['win']:>6.1f} {fpf(m['pf']):>6} "
            f"{m['avg']:>7.3f} {m['cagr']:>7.1f} {m['maxdd']:>8.1f} {cal:>7}")

    log("\nSCREEN_DONE — feed survivors (positive avg/CAGR, ≥%d trades) to the WFO gauntlet." % MIN_TRADES)


if __name__ == "__main__":
    main()
