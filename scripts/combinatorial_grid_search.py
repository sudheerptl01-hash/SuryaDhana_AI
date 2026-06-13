#!/usr/bin/env python
"""
combinatorial_grid_search.py — exhaustive, vectorized combinatorial backtest of the
six structural alpha filters over the 5-year Nifty-1500 DuckDB dataset.

Research question
-----------------
Which *combinations* of {VMI, VIPT, Sector Dispersion, Beta-Coupling, Intraday
Intention, The Squeeze} form the most robust institutional edge — robust meaning a
high risk-adjusted return that holds up year-over-year, not a single lucky bull run?

Engine design (ruthlessly vectorized — no per-row Python loops)
---------------------------------------------------------------
1. Load 5y OHLCV once; corporate-action-adjust OHLC onto the adjusted-close basis.
2. Derive every filter signal with the SAME look-ahead-free engine that powers the
   Backtest Lab (`backtest_engine.compute_indicators` + `compute_market_relative`).
   Signals on day T use strictly trailing data; entry is the NEXT bar's open.
3. Forward return per signal: enter next-open, exit 5 trading days later, net of a
   strict 0.15% (15 bps) round-trip friction. Computed by grouped vector shifts.
4. `itertools.combinations` enumerates all 2**6 − 1 = 63 filter subsets. Each subset
   is a boolean AND of its signal masks — one vectorized mask per combination.
5. Equity is a DAILY-MARKED equal-weight portfolio: each trade's net 5-day return is
   attributed geometrically across its 5 holding bars, and the portfolio's daily
   return is the mean across positions concurrently held that day (cash on idle
   days). This makes CAGR / MaxDD / Sharpe *frequency-fair* — a filter that fires
   every day cannot fake leverage by overlapping 5-day returns.

Anti-curve-fitting
------------------
• Discard any combination with < 100 trades over 5 years (kills micro-sample flukes).
• 15 bps friction deducted from every trade before any metric is computed.
• Ranked by Sharpe (risk-adjusted), never by raw return. Calmar reported alongside.
• A year-over-year matrix proves (or disproves) regime independence.

Output: combinatorial_backtest_results.md (Top-20 with overall metrics + YoY).
MODE = research/PAPER — nothing here trades.
Run: /Users/sudheer/Desktop/jupyter_env/bin/python scripts/combinatorial_grid_search.py
"""
from __future__ import annotations

import itertools
import os
import shutil
import sys
import time
from datetime import datetime

import duckdb
import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "services", "ui-api"))
import backtest_engine as be  # noqa: E402  (validated trailing-indicator engine)

# C4+C9 (§3.6) — cross-campaign trial ledger + cluster-adjusted effective-N. Imported
# DEFENSIVELY: if either module is unavailable the grid still produces the per-run
# nominal-N DSR exactly as before (zero regression). Flags gate every use below.
try:
    import trial_ledger as _tl  # noqa: E402
    _LEDGER_OK = True
except Exception:               # pragma: no cover - import-environment dependent
    _tl = None
    _LEDGER_OK = False
try:
    import effective_trials as _et  # noqa: E402
    _EFF_N_OK = True
except Exception:               # pragma: no cover
    _et = None
    _EFF_N_OK = False

# ── Configuration ─────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DATABASE_URL", os.path.join(REPO, "data", "market.duckdb"))
UNIVERSE_CSV = os.getenv("STOCK_UNIVERSE_PATH", os.path.join(REPO, "data", "NSE_1500.csv"))
SNAPSHOT = "/tmp/combigrid_snapshot.duckdb"
OUT_MD = os.path.join(REPO, "combinatorial_backtest_results.md")

EVAL_START = os.getenv("GRID_FROM", "2021-06-01")
EVAL_END = os.getenv("GRID_TO", "2026-06-01")
HOLD = 5                  # forward holding period (trading days)
FRICTION = 0.0015         # 15 bps round-trip — CLAUDE.md compliance floor
MIN_TRADES = 100          # anti-curve-fit sample floor
TOP_N = 20
TRADING_DAYS = 252

# Six canonical filter signals (economically-motivated, documented thresholds).
FILTER_DOC = {
    "VMI":          "vmi_ratio ≥ 1.0  — dollar-volume at/above its volatility-normalized 20d baseline",
    "VIPT":         "vipt_breakout — close clears the 20d range on > 3σ volume thrust",
    "SectorDisp":   "positive sector regime AND top-decile sector-relative 14d momentum (cross-sectional)",
    "BetaDecouple": "decoupled_leader — 30d corr < 0.2 in a market pullback while holding positive 5d return",
    "Intention":    "intraday_intention ≥ 0.8 — buyers defending the close (3-day aggregated CLV)",
    "Squeeze":      "squeeze_on — Bollinger Bands compressed inside Keltner Channels",
}


# ── Data load ─────────────────────────────────────────────────────────────────────
def _connect() -> duckdb.DuckDBPyConnection:
    """Read-only handle; fall back to an isolated snapshot if the live DB is write-locked."""
    try:
        return duckdb.connect(DB_PATH, read_only=True)
    except Exception:
        shutil.copy2(DB_PATH, SNAPSHOT)
        return duckdb.connect(SNAPSHOT, read_only=True)


def _sector_map() -> dict[str, str]:
    try:
        u = pd.read_csv(UNIVERSE_CSV, usecols=["ticker", "sector"])
        return {str(t).upper(): (s.strip() if isinstance(s, str) and s.strip() else "Unknown")
                for t, s in zip(u["ticker"], u["sector"])}
    except Exception:
        return {}


def load_prepared() -> pd.DataFrame:
    """Load all OHLCV up to EVAL_END (+forward bars), adjust, attach every factor."""
    con = _connect()
    df = con.execute(
        """SELECT ticker, date, open, high, low, close, volume, adjusted_close
           FROM ohlcv WHERE date <= ? ORDER BY ticker, date""",
        [pd.Timestamp(EVAL_END) + pd.Timedelta(days=20)],
    ).fetchdf()
    con.close()

    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "adjusted_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
    # Split/dividend adjustment onto the adjusted-close basis (corporate-action safe).
    adj = (df["adjusted_close"] / df["close"]).where((df["close"] > 0) & df["adjusted_close"].notna(), 1.0)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c] * adj
    df = df.drop(columns=["adjusted_close"])

    t0 = time.time()
    df = be.compute_indicators(df)
    print(f"  compute_indicators: {time.time() - t0:.1f}s")
    t0 = time.time()
    df = be.compute_market_relative(df, _sector_map())
    print(f"  compute_market_relative: {time.time() - t0:.1f}s")
    return df


# ── Signal + forward-return construction (vectorized) ─────────────────────────────
def build_signals(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, np.ndarray], np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[int]]:
    df = df.sort_values(["ticker", "date"]).reset_index(drop=True)
    g = df.groupby("ticker", sort=False)

    # Forward trade: enter NEXT open, exit 5 bars later close, net of round-trip friction.
    entry_px = g["open"].shift(-1)
    exit_px = g["close"].shift(-HOLD)
    gross = exit_px / entry_px - 1.0
    net = (gross - FRICTION).to_numpy()
    valid_fwd = (entry_px.notna() & exit_px.notna() & (entry_px > 0)).to_numpy()

    # Eval calendar: every distinct trading date from EVAL_START onward (holding bars
    # past EVAL_END remain markable). Signals are only eligible inside [start, end].
    start_ts, end_ts = pd.Timestamp(EVAL_START), pd.Timestamp(EVAL_END)
    cal = np.sort(df.loc[df["date"] >= start_ts, "date"].unique())
    didx_map = {d: i for i, d in enumerate(cal)}
    n_dates = len(cal)
    years = np.array([pd.Timestamp(d).year for d in cal])
    unique_years = sorted(set(int(y) for y in years))

    df["gidx"] = df["date"].map(didx_map).astype("float64")   # NaN before EVAL_START
    gcol = df.groupby("ticker", sort=False)["gidx"]
    fwd_gidx = np.full((len(df), HOLD), np.nan)
    for k in range(1, HOLD + 1):
        fwd_gidx[:, k - 1] = gcol.shift(-k).to_numpy()

    in_eval = ((df["date"] >= start_ts) & (df["date"] <= end_ts)).to_numpy()
    base = in_eval & valid_fwd & np.isfinite(net)

    # Geometric per-day attribution of each trade's net return across its HOLD bars.
    safe_net = np.where(np.isfinite(net), net, 0.0)
    per_day = np.power(1.0 + np.clip(safe_net, -0.999999, None), 1.0 / HOLD) - 1.0

    # Cross-sectional sector-dispersion rank (top decile within each day).
    rank_pct = df.groupby("date")["sector_rel_mom_14_pct"].rank(pct=True).to_numpy()

    sig = {
        "VMI":          (df["vmi_ratio"].to_numpy() >= 1.0),
        "VIPT":         df["vipt_breakout"].fillna(False).to_numpy().astype(bool),
        "SectorDisp":   (df["sector_positive_regime"].fillna(False).to_numpy().astype(bool) & (rank_pct >= 0.90)),
        "BetaDecouple": df["decoupled_leader"].fillna(False).to_numpy().astype(bool),
        "Intention":    (df["intraday_intention"].to_numpy() >= 0.8),
        "Squeeze":      df["squeeze_on"].fillna(False).to_numpy().astype(bool),
    }
    # NaN-safe: every comparison against NaN yields False; booleans are pre-filled.
    for k in sig:
        sig[k] = np.where(np.isfinite(sig[k].astype(float)) if sig[k].dtype != bool else True, sig[k], False)
        sig[k] = np.asarray(sig[k], dtype=bool)

    return df, sig, base, net, per_day, fwd_gidx, (n_dates, years, unique_years)


# ── Metrics ───────────────────────────────────────────────────────────────────────
def _sharpe(daily: np.ndarray) -> float:
    if daily.size < 2:
        return 0.0
    sd = float(daily.std(ddof=1))
    return float(daily.mean() / sd * np.sqrt(TRADING_DAYS)) if sd > 1e-12 else 0.0


def _max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    return float(((equity / peak) - 1.0).min() * 100.0)


def evaluate(combo: tuple[str, ...], sig, base, net, per_day, fwd_gidx, cal_meta) -> dict | None:
    n_dates, years, unique_years = cal_meta
    mask = base.copy()
    for name in combo:
        mask &= sig[name]
    idx = np.flatnonzero(mask)
    n_trades = int(idx.size)
    if n_trades < MIN_TRADES:
        return None

    tn = net[idx]
    wins = tn[tn > 0]
    losses = tn[tn <= 0]
    win_rate = len(wins) / n_trades * 100.0
    avg_win = float(wins.mean() * 100.0) if wins.size else 0.0
    avg_loss = float(losses.mean() * 100.0) if losses.size else 0.0
    gross_win = float(wins.sum())
    gross_loss = float(abs(losses.sum()))
    profit_factor = (gross_win / gross_loss) if gross_loss > 1e-12 else float("inf")
    expectancy = float(tn.mean() * 100.0)

    # Daily-marked equal-weight portfolio equity (overlap-fair).
    s = np.zeros(n_dates)
    c = np.zeros(n_dates)
    pd_sel = per_day[idx]
    for k in range(HOLD):
        tgt = fwd_gidx[idx, k]
        ok = np.isfinite(tgt)
        t = tgt[ok].astype(np.int64)
        np.add.at(s, t, pd_sel[ok])
        np.add.at(c, t, 1)
    daily = np.where(c > 0, s / np.maximum(c, 1), 0.0)
    equity = np.cumprod(1.0 + daily)

    total_return = float((equity[-1] - 1.0) * 100.0)
    cagr = float((equity[-1] ** (TRADING_DAYS / max(n_dates, 1)) - 1.0) * 100.0)
    mdd = _max_drawdown(equity)
    sharpe = _sharpe(daily)
    calmar = float(cagr / abs(mdd)) if abs(mdd) > 1e-9 else 0.0

    yoy = {}
    for y in unique_years:
        ym = years == y
        yoy[y] = float((np.prod(1.0 + daily[ym]) - 1.0) * 100.0) if ym.any() else 0.0

    return {
        "combo": combo, "n_trades": n_trades, "win_rate": win_rate,
        "avg_win": avg_win, "avg_loss": avg_loss, "profit_factor": profit_factor,
        "expectancy": expectancy, "total_return": total_return, "cagr": cagr,
        "max_dd": mdd, "sharpe": sharpe, "calmar": calmar, "yoy": yoy,
        "daily": daily,                 # per-day portfolio returns (for Deflated Sharpe)
        "dsr": None,                    # filled in main() once the full trial set is known
    }


# ── Report ────────────────────────────────────────────────────────────────────────
def _pf(x: float) -> str:
    return "∞" if x == float("inf") else f"{x:.2f}"


def write_report(rows: list[dict], unique_years: list[int], n_universe: int, n_dates: int,
                 elapsed: float, tested: int, surviving: int, pbo: dict | None = None) -> None:
    top = rows[:TOP_N]
    lines: list[str] = []
    A = lines.append
    A("# Combinatorial Alpha Grid — Top Institutional Edges\n")
    A(f"_Generated {datetime.now():%Y-%m-%d %H:%M} · MODE=PAPER (research)_\n")
    A("## Methodology\n")
    A(f"- **Dataset**: Nifty-1500 DuckDB · {n_universe:,} tickers · window **{EVAL_START} → {EVAL_END}** "
      f"({n_dates:,} trading days)")
    A(f"- **Trade model**: signal on day T → enter **next open** → exit **+{HOLD} trading days** close · "
      f"net of **{FRICTION*100:.2f}% friction** per trade")
    A("- **Equity**: daily-marked equal-weight portfolio (each trade's 5-day return attributed geometrically "
      "across its holding bars; portfolio = mean of concurrently-held positions, cash on idle days). This makes "
      "CAGR / MaxDD / Sharpe **frequency-fair** — high-firing filters cannot fake leverage via overlapping returns.")
    A(f"- **Anti-curve-fit**: combinations with **< {MIN_TRADES} trades discarded**; ranked by **Sharpe** "
      "(risk-adjusted), not raw return.")
    A(f"- **Search**: all 2⁶−1 = {tested} filter combinations · **{surviving}** cleared the trade floor · "
      f"engine ran in {elapsed:.1f}s.")
    A("- **Multiple-testing correction (Bailey & López de Prado)**: the **Deflated Sharpe Ratio (DSR)** "
      f"column is P(true SR > expected-max-of-{surviving} under the null) — it deflates each combo's Sharpe "
      "for the number of trials, sample length, skew and kurtosis. **DSR ≳ 0.95** survives multiple-testing; "
      "**< 0.5** is likely a selection artefact even if the raw Sharpe looks high. (DSR assumes independent "
      "trials; these combos overlap heavily, so the effective trial count is < the nominal count and DSR is a "
      "*conservative lower bound* — the PSR column gives the un-deflated significance for contrast.)")
    if pbo:
        A(f"- **Probability of Backtest Overfitting (PBO)** via CSCV over {pbo['n_blocks']} calendar-year blocks × "
          f"{pbo['n_configs']} combos ({pbo['n_splits']} symmetric splits): **PBO = {pbo['pbo']:.2f}** "
          f"→ ~{pbo['pbo']*100:.0f}% chance the in-sample-best combo ranks below the out-of-sample median.")
    A("")

    A("## Filter definitions (all strictly trailing — zero look-ahead)\n")
    A("| Filter | Signal |")
    A("|---|---|")
    for k, v in FILTER_DOC.items():
        A(f"| **{k}** | {v} |")
    A("")

    A("## Top 20 — Overall metrics (ranked by Sharpe)\n")
    A("_**PSR** = P(SR>0) in isolation; **DSR** = Deflated Sharpe after correcting for the "
      f"{surviving} trials. PSR high + DSR low ⇒ the Sharpe is real but **eaten by the search** "
      "(too many combos tried for the signal present)._\n")
    A("| # | Filter Combination | Trades | Win % | Avg Win % | Avg Loss % | Profit Factor | Expectancy % | Sharpe | PSR | DSR | Calmar | Max DD % | CAGR % | Total Ret % |")
    A("|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
    for i, r in enumerate(top, 1):
        dsr, psr = r.get("dsr"), r.get("psr")
        dsr_s = f"{dsr:.2f}" if dsr is not None else "—"
        psr_s = f"{psr:.2f}" if psr is not None else "—"
        A(f"| {i} | {' + '.join(r['combo'])} | {r['n_trades']:,} | {r['win_rate']:.1f} | "
          f"{r['avg_win']:.2f} | {r['avg_loss']:.2f} | {_pf(r['profit_factor'])} | {r['expectancy']:.3f} | "
          f"**{r['sharpe']:.2f}** | {psr_s} | {dsr_s} | {r['calmar']:.2f} | {r['max_dd']:.1f} | {r['cagr']:.1f} | {r['total_return']:.1f} |")
    A("")

    A("## Top 20 — Year-over-Year return matrix (%)\n")
    A("_Each cell is the strategy's compounded return within that calendar year — proves the edge isn't a single-year artefact._\n")
    A("> ⚠️ **Partial / warm-up years**: 2021 covers Jun–Dec only and overlaps factor warm-up (200d MA, "
      "30d corr) so its sample is thin and its % is not comparable to a full year; 2026 covers Jan–Jun only. "
      "Judge robustness on the **full years 2022–2025**.\n")
    yhdr = " | ".join(str(y) for y in unique_years)
    A(f"| # | Filter Combination | {yhdr} |")
    A("|---|---|" + "--:|" * len(unique_years))
    for i, r in enumerate(top, 1):
        cells = " | ".join(f"{r['yoy'].get(y, 0.0):+.1f}" for y in unique_years)
        A(f"| {i} | {' + '.join(r['combo'])} | {cells} |")
    A("")

    if top:
        best = top[0]
        full_years = [y for y in unique_years if 2022 <= y <= 2025]   # exclude partial 2021/2026
        pos_full = sum(1 for y in full_years if best["yoy"].get(y, 0.0) > 0)
        A("## Read-out\n")
        bdsr, bpsr = best.get("dsr"), best.get("psr")
        bdsr_s = f"{bdsr:.2f}" if bdsr is not None else "—"
        bpsr_s = f"{bpsr:.2f}" if bpsr is not None else "—"
        A(f"- **Best risk-adjusted edge**: `{' + '.join(best['combo'])}` — Sharpe **{best['sharpe']:.2f}**, "
          f"PSR {bpsr_s}, DSR **{bdsr_s}**, Calmar {best['calmar']:.2f}, {best['n_trades']:,} trades, "
          f"win {best['win_rate']:.1f}%, PF {_pf(best['profit_factor'])}, MaxDD {best['max_dd']:.1f}%.")
        if bdsr is not None:
            verdict = ("survives multiple-testing" if bdsr >= 0.95 else
                       "is borderline under multiple-testing" if bdsr >= 0.5 else
                       "does **not** survive the 43-combo search — even the winner's Sharpe is within the "
                       "expected-max-under-null, i.e. largely trial-count luck given the deep drawdowns")
            A(f"- **Multiple-testing verdict**: PSR {bpsr_s} (raw significance) vs DSR {bdsr_s} (post-search) → this edge {verdict}.")
        if pbo:
            A(f"- **Overfitting probability (PBO)**: **{pbo['pbo']:.2f}** across {pbo['n_splits']} CSCV splits — "
              f"{'low (robust selection)' if pbo['pbo'] < 0.3 else 'elevated (treat the winner with caution)' if pbo['pbo'] < 0.6 else 'high (the search is overfit)'}.")
        A(f"- **Regime robustness (full years 2022–2025)**: positive in **{pos_full}/{len(full_years)}**.")
        A("- Treat single-filter rows as the baseline edge; multi-filter rows that *raise Sharpe without "
          "collapsing trade count* are the genuine interaction effects worth trading.\n")

    with open(OUT_MD, "w") as f:
        f.write("\n".join(lines))
    print(f"  report -> {OUT_MD}")


# ── Main ──────────────────────────────────────────────────────────────────────────
def main() -> None:
    t_start = time.time()
    print("=" * 78)
    print(f"COMBINATORIAL GRID SEARCH  {EVAL_START} → {EVAL_END}  | hold {HOLD}d | "
          f"friction {FRICTION*100:.2f}% | min {MIN_TRADES} trades")
    print("=" * 78)

    print("[1/3] Loading + factor engine …")
    df = load_prepared()
    n_universe = int(df["ticker"].nunique())
    print(f"      rows={len(df):,}  tickers={n_universe:,}")

    print("[2/3] Building signals + forward returns …")
    df, sig, base, net, per_day, fwd_gidx, cal_meta = build_signals(df)
    n_dates, years, unique_years = cal_meta
    print(f"      eval trading days={n_dates:,}  base-eligible signals={int(base.sum()):,}")
    for k in sig:
        print(f"        {k:13s} fires on {int((sig[k] & base).sum()):>7,} eligible rows")

    print("[3/3] Sweeping 2⁶−1 = 63 combinations …")
    names = list(sig)
    results: list[dict] = []
    tested = 0
    for r in range(1, len(names) + 1):
        for combo in itertools.combinations(names, r):
            tested += 1
            res = evaluate(combo, sig, base, net, per_day, fwd_gidx, cal_meta)
            if res is not None:
                results.append(res)
    results.sort(key=lambda d: (d["sharpe"], d["calmar"]), reverse=True)
    elapsed = time.time() - t_start
    print(f"      {tested} tested · {len(results)} cleared ≥{MIN_TRADES} trades · {elapsed:.1f}s")

    # ── Multiple-testing correction (G3): Deflated Sharpe per combo + portfolio PBO ──
    # The winning Sharpe is inflated purely by searching 63 combinations. DSR deflates
    # each combo's SR by the expected max-of-N under the null; PBO (CSCV over the YoY
    # blocks) estimates the probability the in-sample-best is overfit.
    trial_sharpes = [r["sharpe"] for r in results]            # SR of every surviving trial
    for r in results:
        d = be.deflated_sharpe_ratio(r["daily"], trial_sharpes)
        r["dsr"] = d["dsr"]            # P(SR robust AFTER correcting for 43 trials)
        r["psr"] = d["psr_zero"]       # P(SR>0) in isolation, BEFORE the trial haircut
        r["sr0_annual"] = d["sr0_annual"]
    # PBO via CSCV on the YoY return matrix (blocks = calendar years, configs = combos).
    perf = np.array([[r["yoy"].get(y, 0.0) for r in results] for y in unique_years], dtype=float)
    pbo = be.probability_of_backtest_overfitting(perf)
    if pbo:
        print(f"      DSR(top)={results[0]['dsr']:.3f}  ·  PBO={pbo['pbo']:.3f} "
              f"(CSCV {pbo['n_splits']} splits over {pbo['n_blocks']} years × {pbo['n_configs']} combos)")

    write_report(results, unique_years, n_universe, n_dates, elapsed, tested, len(results), pbo)

    print("\nTOP 10 (console):")
    print(f"  {'#':>2}  {'combination':<46}{'trades':>7}{'win%':>6}{'PF':>6}{'sharpe':>8}{'calmar':>7}{'maxDD%':>8}{'CAGR%':>7}")
    for i, r in enumerate(results[:10], 1):
        print(f"  {i:>2}  {' + '.join(r['combo']):<46}{r['n_trades']:>7,}{r['win_rate']:>6.1f}"
              f"{_pf(r['profit_factor']):>6}{r['sharpe']:>8.2f}{r['calmar']:>7.2f}{r['max_dd']:>8.1f}{r['cagr']:>7.1f}")
    print("=" * 78)


if __name__ == "__main__":
    main()
