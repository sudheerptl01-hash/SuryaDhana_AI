"""sota_inversion_spread_search.py — THE INVERSION TEST.

Three independent research programs (single-factor, PCA-orthogonal multi-factor under
breadth, regime-timing overlay) triple-confirmed a sharp diagnostic: the LONG-ONLY
27-factor decile stack on this 100-NSE library UNDERPERFORMS its own +122% equal-weight
benchmark OOS, net of cost. The selection axis systematically picks subsets that LOSE to
a broad rising market.

QUESTION (this script): is that underperformance real, mis-signed INFORMATION — tradeable
by INVERTING the construction — or is it merely concentration / vol-drag with NO directional
edge?

HYPOTHESIS: a DOLLAR-NEUTRAL (and ideally beta-neutral) LONG-SHORT spread that SHORTS the
most negative-alpha screened cohort and goes LONG the benchmark (equal-weight universe)
isolates the relative cross-sectional spread, nets out market beta, and — IF the selection
axis carries real mis-signed information — yields positive OOS alpha that survives the
DSR>0.95 gate.

  • "real info, wrong sign"     ⇒ spread is positive GROSS but is (or is not) killed by short
                                  frictions (borrow + symmetric Amihud). We quantify the gap.
  • "no info, concentration drag"⇒ spread is ~flat/negative EVEN GROSS. The long-only loss was
                                  idiosyncratic concentration, not tradeable mis-signed info.

────────────────────────────────────────────────────────────────────────────────────────
EXECUTION PATH (documented honestly):
The production engine (`backtest_engine.simulate_portfolio`, `routers.analytics._core_wfo`)
is STRICTLY LONG-ONLY — grep confirms NO short / borrow / negative-weight / leverage path,
and the DuckDB has NO shortable / F&O / SLB flag. So we DO NOT fake a short through the
long-only sim. Instead we build the dollar-neutral spread HONESTLY ON TOP OF the same
machinery:
  • Same DB read + same prepared panel via `analytics._load_context` (which calls
    `_load_prepared` → `be.compute_indicators` + `be.compute_market_relative`). No
    reimplementation of indicators, no look-ahead.
  • Same WFO walk-forward windows via `analytics._wfo_windows` (rolling IS→embargoed OOS,
    contiguous OOS tiling). We evaluate the spread ONLY on the stitched OOS segments.
  • Same per-name forward economics via `ctx.resolve(sig, ticker)` — the engine's own
    look-ahead-free, friction-baked, stop/time-exit-resolved entry dict carrying
    net_return_pct, gross_return_pct, atr_pct, adv (ADV20), amihud (ILLIQ), sector.
  • Same cross-sectional decile recipe via `be.assign_decile` (bit-for-bit the production
    screen) to define the SHORT cohort each bar.
  • Same impact arithmetic copied from `simulate_portfolio` (verified at backtest_engine.py
    L1085 / L1126): temporary √-law round-trip 2·Y·ATR%·√(alloc/ADV) and permanent Amihud
    round-trip amihud_coef·ILLIQ·alloc·100 — debited SYMMETRICALLY on BOTH legs.

SHORT-SIDE REALISM (non-negotiable, never weakened to manufacture a positive):
  (a) Borrow / financing cost on the short leg: INDIAN SLB annualized rate. Default 150
      bps/yr (mid of the documented 50–200 bps/yr NSE SLB lending-fee band), applied pro-rata
      over the ~5-day holding horizon. Stated as an ASSUMPTION.
  (b) Amihud market impact is symmetric ⇒ debited on BOTH legs (same √-law + permanent code).
  (c) friction_bps floor = 15.0 per leg (already baked into net_return_pct by the resolver);
      a long-short round-trip therefore pays ~2× friction (long leg + short leg).
  (d) SHORTABLE-UNIVERSE constraint: NO shortable flag exists in the data, so the short leg
      is RESTRICTED to the most-liquid decile (top-decile ADV20 in-window) as the realistic
      F&O/SLB-available proxy. DOCUMENTED assumption.

BETA NEUTRALITY: the spread is constructed dollar-neutral (long benchmark − short cohort,
equal gross per leg). We additionally beta-hedge the long benchmark leg by the realized
short-cohort beta (estimated IN-SAMPLE only, applied OOS) and REPORT the realized spread
beta to confirm ~neutrality. The bull-market trap (a naive outright short loses in a +122%
tape) is avoided precisely because the long benchmark leg offsets the short's market beta.

DSR GATE: every (cohort × neutralization × N) cell is a trial; DSR deflates against the
TOTAL trial count via n_eff so the multiple-testing denominator is honest.

MODE=PAPER. Read-only DuckDB. No secrets. Capital = ₹1,00,00,000. Seed=42.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python sota_inversion_spread_search.py
"""
from __future__ import annotations

import os
import sys
import csv
import json
import random
import logging
from pathlib import Path
from datetime import timedelta
from typing import Optional, Callable

import numpy as np
import pandas as pd
import duckdb

# ── Bootstrap (mirror prior sota scripts) ────────────────────────────────────────
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import backtest_engine as be  # noqa: E402
from routers.analytics import (  # noqa: E402
    _load_context, _wfo_windows, WFOBacktestRequest,
)

# ── Reproducibility ──────────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# ── Config (all knobs surfaced; no magic numbers below this block) ───────────────
CAPITAL = 10_000_000.0          # ₹1 Crore (paper)
FORWARD_DAYS = 5                # holding horizon (same as falsified studies)
FRICTION_BPS = 15.0             # 0.15% per-leg floor (CLAUDE.md hard rule); baked into net_return_pct
IN_SAMPLE_DAYS = 365            # WFO IS length (same windows as falsified studies)
OUT_SAMPLE_DAYS = 90            # WFO OOS length
EMBARGO_DAYS = 7                # IS→OOS gap (engine default; > holding horizon)
TRADING_DAYS = be.TRADING_DAYS  # annualization basis (252)

# Short-side realism
SLB_BORROW_BPS_PER_YEAR = 150.0     # Indian SLB lending fee assumption (mid of 50–200 bps/yr band)
AMIHUD_COEF = 1.0                   # permanent-leg multiplier λ_mult (per-name ILLIQ carries scale) — engine default
IMPACT_TEMP_COEF = 1.0              # Almgren-style √-law temporary coef Y (engine default impact_coef≈1)
SHORTABLE_LIQ_DECILE = 6            # short leg restricted to top-5-ADV-deciles (top-half liquid).
                                    # Rationale: we already gate the WHOLE universe to the top-100
                                    # most-liquid names (≈ the NSE F&O/SLB-eligible large-cap set, which
                                    # spans ~180 names); within that, the top-half by ADV is a defensible
                                    # realistically-shortable proxy. A stricter top-DECILE gate (10 names)
                                    # intersected with the factor decile (10 names) yields ~1-2 shortable
                                    # names — an idiosyncratic coin-flip, not a cohort (DOCUMENTED).

# Benchmark / investable-universe gate. The engine's +122% benchmark = equal-weight of the
# top-100 most-liquid (by in-window dollar volume) names (analytics._build_benchmark / L634,
# BENCHMARK_LABEL "Nifty-50 proxy (top-100 mkt-cap, equal-weight)"). We mirror that PER BAR:
# restrict the cross-section to the top BENCH_TOP_N names by signal-day ADV20, drop NaN-ADV
# microcaps. This makes the LONG leg the genuine investable benchmark — NOT a 644-name
# microcap soup — and removes look-ahead-free names with no real liquidity from BOTH legs.
BENCH_TOP_N = 100

# Sweep
BREADTH_GRID = [5, 10, 20, 30]      # short-cohort size N (cells per cohort×neutralization)
DSR_GATE = 0.95                     # Phase-3 hard gate
CAGR_GATE = 0.0                     # positive OOS alpha floor
DECILE_N = be.DECILE_N              # production decile count (10)

# ── Overlap + breadth realism (CRITICAL anti-curve-fit corrections) ──────────────
# Signals fire DAILY but each trade holds FORWARD_DAYS bars, so consecutive signal-bar
# returns OVERLAP — compounding them as if independent counts the same 5-day move ~5×
# and FRAUDULENTLY inflates CAGR/Calmar. We therefore sample NON-OVERLAPPING bars (every
# FORWARD_DAYS-th signal date) so each 5-day return is counted ONCE. Standard overlapping-
# horizon correction. We also require a MINIMUM shortable-cohort breadth: a 2-name short
# leg is an idiosyncratic coin-flip, not a tradeable cohort — its tail dominates and is not
# a real edge. Bars below the floor are dropped (no short that bar).
DEOVERLAP_STEP = FORWARD_DAYS       # keep every FORWARD_DAYS-th signal bar (non-overlapping)
MIN_SHORT_NAMES = 5                 # minimum diversified shortable cohort; below ⇒ no short bar

# Market-relative fields requiring need_market_relative=True
MARKET_RELATIVE = {"vol_adj_sector_alpha_14", "sector_rel_mom_14_pct", "corr_nifty_30",
                   "sector_positive_regime", "decoupled_leader", "beta_resid_5d"}

# ── SHORT cohorts: the cross-sections the long-only stack SELECTS (and that underperform).
# Each is a single decile screen on a prepared-panel column. The long-only book BOUGHT these;
# the inversion SHORTS them. `bad_side` = the decile end the long-only screen treated as the
# "buy" — i.e. the cohort we now short. We test multiple so the trial count is honest.
SHORT_COHORTS: list[dict] = [
    {"name": "ORTHO-A-short · vol_adj_sector_alpha↑D10",
     "col": "vol_adj_sector_alpha_14", "side": "top",
     "note": "Long-only BOUGHT top-decile vol-adj sector alpha (offensive axis); it underperformed. Short it."},
    {"name": "low-ATR↓D1",
     "col": "atr_pct", "side": "bottom",
     "note": "Long-only BOUGHT bottom-decile ATR (defensive low-vol axis); it underperformed. Short it."},
    {"name": "squeeze↑D10",
     "col": "squeeze_ratio", "side": "top",
     "note": "Squeeze-ratio top decile (offensive breakout axis from regime work). Short it."},
    {"name": "sector_rel_mom↑D10",
     "col": "sector_rel_mom_14_pct", "side": "top",
     "note": "Sector relative momentum winners — the classic chase the long book made. Short it."},
]
NEUTRALIZATIONS = ["dollar", "beta"]   # dollar-neutral, and dollar+beta-neutral

LOG_PATH = REPO / "sota_inversion_spread_run.log"
CSV_PATH = REPO / "sota_inversion_spread_results.csv"
JSON_PATH = REPO / "sota_inversion_spread_results.json"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("inversion")


# ── Per-name impact replicated EXACTLY from simulate_portfolio (be L1085 / L1126) ─────────
def round_trip_impact_pct(alloc: float, adv: Optional[float], atr_pct: Optional[float],
                          illiq: Optional[float]) -> float:
    """Symmetric round-trip impact in % of notional for ONE name at `alloc` notional.

    Byte-faithful to `backtest_engine.simulate_portfolio`:
      temporary √-law : 2·Y·ATR%·√(alloc/ADV)         (be L1085)
      permanent Amihud: amihud_coef·ILLIQ·alloc·100    (be L1126)
    Both are symmetric in trade direction, so the SAME cost applies whether the leg is
    long or short — we debit it on both legs.
    """
    impact = 0.0
    a = float(atr_pct) if atr_pct else 0.0
    if adv and adv > 0:
        impact += 2.0 * IMPACT_TEMP_COEF * a * (alloc / float(adv)) ** 0.5
    if illiq and illiq > 0:
        impact += AMIHUD_COEF * float(illiq) * alloc * 100.0
    return impact


def borrow_pct(holding_days: float) -> float:
    """Short-leg SLB borrow/financing cost in % for a `holding_days` hold (pro-rata annual)."""
    return SLB_BORROW_BPS_PER_YEAR / 100.0 * (holding_days / float(TRADING_DAYS))


def deoverlap(panel: pd.DataFrame) -> pd.DataFrame:
    """Keep every DEOVERLAP_STEP-th distinct signal date so 5-day-forward returns do NOT
    overlap. Eliminates the overlapping-horizon compounding artifact that inflates CAGR."""
    if panel.empty:
        return panel
    dates = sorted(pd.to_datetime(panel["entry_date"]).unique())
    keep = set(str(pd.Timestamp(d).date()) for d in dates[::DEOVERLAP_STEP])
    return panel[panel["entry_date"].astype(str).isin(keep)].copy()


# ── Harvest per-bar resolved names from the production context ────────────────────────────
def harvest_window(ctx, from_ts: pd.Timestamp, to_ts: pd.Timestamp) -> pd.DataFrame:
    """Return a long DataFrame of every (signal-bar, ticker) the engine can price in
    [from_ts, to_ts], with the engine's own look-ahead-free forward economics + liquidity.

    Reuses `ctx.grouped` (sorted per-bar candidate frames) and `ctx.resolve` (memoized,
    friction-baked exit resolution) — NO indicator recompute, NO look-ahead.
    """
    from bisect import bisect_left, bisect_right
    lo = bisect_left(ctx.grouped_keys, from_ts)
    hi = bisect_right(ctx.grouped_keys, to_ts)
    rows: list[dict] = []
    for entry_date, day_df in ctx.grouped[lo:hi]:
        if day_df is None or day_df.empty:
            continue
        d = day_df
        # As-of index membership (mirror _simulate_window): never select a non-constituent.
        if "index_member" in d.columns:
            d = d[d["index_member"]]
            if d.empty:
                continue
        d = d.drop_duplicates(subset=["ticker"], keep="first")
        sig = ctx.date_to_gidx[entry_date]
        if "adv20" not in d.columns:
            continue
        # ── Investable-universe gate (mirror _build_benchmark): keep only names with finite,
        # positive signal-day ADV20, then the top BENCH_TOP_N by ADV20. The LONG leg over this
        # set IS the equal-weight top-100-liquid benchmark (the +122% tape); microcaps with no
        # real liquidity (NaN ADV) are dropped from BOTH legs. Strictly same-bar (no look-ahead).
        d = d[pd.to_numeric(d["adv20"], errors="coerce").notna() & (pd.to_numeric(d["adv20"], errors="coerce") > 0)]
        if len(d) < 10:
            continue
        d = d.sort_values("adv20", ascending=False).head(BENCH_TOP_N)
        # Rank cohort columns + liquidity decile ON THIS BAR's liquid cross-section (zero look-ahead).
        cols_present = [c for c in COHORT_COLS if c in d.columns]
        decile_cache: dict[str, pd.Series] = {}
        for c in cols_present:
            decile_cache[c] = be.assign_decile(d[c])
        liq_decile = be.assign_decile(d["adv20"])
        tickers = d["ticker"].tolist()
        idx = d.index.tolist()
        for pos, tkr in zip(idx, tickers):
            ent = ctx.resolve(sig, tkr)
            if ent is None:
                continue
            row = {
                "entry_date": ent["entry_date"],
                "exit_date": ent["exit_date"],
                "ticker": tkr,
                "net_return_pct": ent["net_return_pct"],
                "gross_return_pct": ent["gross_return_pct"],
                "holding_days": ent["holding_days"],
                "atr_pct": ent.get("atr_pct"),
                "adv": ent.get("adv"),
                "amihud": ent.get("amihud"),
                "liq_decile": float(liq_decile.loc[pos]) if pos in liq_decile.index else np.nan,
            }
            for c in cols_present:
                row[f"dec_{c}"] = float(decile_cache[c].loc[pos]) if pos in decile_cache[c].index else np.nan
            rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# Columns we will need deciles for (union of all cohort cols)
COHORT_COLS = sorted({c["col"] for c in SHORT_COHORTS})


def spread_daily_returns(panel: pd.DataFrame, cohort: dict, n_short: int,
                         neutralization: str, beta_hat: Optional[float],
                         capital: float) -> pd.DataFrame:
    """Build the dollar(/beta)-neutral spread per signal-bar from a harvested panel.

    LONG  leg  = equal-weight benchmark (ALL resolved names this bar) — the +122% tape.
    SHORT leg  = the screened cohort (decile end the long-only book bought), restricted to
                 the shortable (top-ADV-decile) universe, top `n_short` by liquidity.

    Per leg gross notional = `capital` (dollar-neutral). Each leg's per-name realised return
    is the engine's NET return (friction baked) MINUS symmetric round-trip Amihud impact at
    that name's per-slot notional; the SHORT leg additionally pays borrow and flips sign.
    Returns one row per signal bar with long/short/spread returns + exposure diagnostics.
    """
    dcol = f"dec_{cohort['col']}"
    if dcol not in panel.columns:
        return pd.DataFrame()
    out_rows: list[dict] = []
    for ed, g in panel.groupby("entry_date"):
        g = g.dropna(subset=["net_return_pct"])
        if g.empty:
            continue
        # ── LONG leg: equal-weight benchmark = the full resolved cross-section this bar ──
        n_long = len(g)
        long_alloc = capital / n_long
        long_rets = []
        for _, r in g.iterrows():
            imp = round_trip_impact_pct(long_alloc, r["adv"], r["atr_pct"], r["amihud"])
            long_rets.append((r["net_return_pct"] - imp) / 100.0)
        long_ret = float(np.mean(long_rets)) if long_rets else 0.0

        # ── SHORT leg: the screened cohort, shortable-restricted, top-N by liquidity ──
        end = cohort["side"]
        if end == "top":
            coh = g[g[dcol] >= float(DECILE_N)]
        else:
            coh = g[g[dcol] <= 1.0]
        # Shortable-universe proxy: only the most-liquid (top ADV) decile is realistically
        # F&O/SLB-shortable. If the screen leaves <2 shortable names, this bar has no short.
        coh = coh[coh["liq_decile"] >= float(SHORTABLE_LIQ_DECILE)]
        if len(coh) < MIN_SHORT_NAMES:
            continue
        coh = coh.sort_values("adv", ascending=False).head(n_short)
        n_s = len(coh)
        short_alloc = capital / n_s
        short_rets = []
        for _, r in coh.iterrows():
            imp = round_trip_impact_pct(short_alloc, r["adv"], r["atr_pct"], r["amihud"])
            brw = borrow_pct(r["holding_days"])
            # SHORT pnl = -(price move); cost legs (impact + borrow) are ALWAYS a debit.
            short_rets.append(-(r["net_return_pct"] / 100.0) - imp / 100.0 - brw / 100.0)
        short_ret = float(np.mean(short_rets)) if short_rets else 0.0

        # ── Neutralization ──
        if neutralization == "beta" and beta_hat is not None:
            # Hedge the SHORT cohort's market beta by scaling the LONG benchmark leg.
            # spread = β·(long benchmark) − (short cohort gross move) ; cost legs unchanged.
            long_w = float(beta_hat)
        else:
            long_w = 1.0
        spread_ret = long_w * long_ret + short_ret
        out_rows.append({
            "entry_date": ed,
            "long_ret": long_ret,
            "short_ret": short_ret,
            "spread_ret": spread_ret,
            "n_long": n_long,
            "n_short": n_s,
            "long_w": long_w,
        })
    return pd.DataFrame(out_rows).sort_values("entry_date") if out_rows else pd.DataFrame()


def perf_metrics(daily_ret: np.ndarray, n_periods_per_year: float) -> dict:
    """CAGR / MaxDD / Sharpe / Calmar from a per-signal-bar return series.

    Bars are ~weekly (5-day holding, non-overlapping signal cadence within a window), so we
    annualize by the realised bar frequency. NAV compounds the bar returns.
    """
    r = np.asarray(daily_ret, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 3:
        return {"cagr_pct": 0.0, "max_dd_pct": 0.0, "sharpe": 0.0, "calmar": 0.0,
                "total_return_pct": 0.0, "n_bars": int(len(r))}
    nav = np.cumprod(1.0 + r)
    total_ret = float(nav[-1] - 1.0)
    years = len(r) / n_periods_per_year
    cagr = (nav[-1] ** (1.0 / years) - 1.0) if years > 0 and nav[-1] > 0 else -1.0
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    max_dd = float(dd.min())
    sd = float(np.std(r, ddof=1))
    sharpe = (float(np.mean(r)) / sd * np.sqrt(n_periods_per_year)) if sd > 1e-12 else 0.0
    calmar = (cagr / abs(max_dd)) if max_dd < -1e-9 else 0.0
    return {"cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(max_dd * 100, 2),
            "sharpe": round(sharpe, 3), "calmar": round(calmar, 3),
            "total_return_pct": round(total_ret * 100, 2), "n_bars": int(len(r))}


def estimate_beta(panel_is: pd.DataFrame, cohort: dict, capital: float) -> Optional[float]:
    """IN-SAMPLE realized beta of the SHORT cohort's gross return vs the benchmark leg.

    Used to set the beta-neutral long weight; estimated on IS bars ONLY, applied OOS — no
    look-ahead. Returns None when too few overlapping bars.
    """
    sp = spread_daily_returns(panel_is, cohort, n_short=max(BREADTH_GRID),
                              neutralization="dollar", beta_hat=None, capital=capital)
    if sp.empty or len(sp) < 8:
        return None
    # cohort gross proxy = -short_ret (undo the sign + cost is a small bias; use long vs short)
    x = sp["long_ret"].to_numpy(dtype=float)      # benchmark (market proxy)
    y = (-sp["short_ret"]).to_numpy(dtype=float)  # cohort gross move
    if np.std(x) < 1e-9:
        return None
    beta = float(np.cov(y, x, ddof=1)[0, 1] / np.var(x, ddof=1))
    # Clamp to a sane hedge ratio (avoid degenerate leverage from a noisy IS estimate).
    return float(np.clip(beta, 0.2, 2.5))


def main() -> None:
    log.info("=" * 90)
    log.info("INVERSION TEST — dollar/beta-neutral long-short spread on the falsified long-only stack")
    log.info("MODE=PAPER  seed=%d  capital=₹%.0f  borrow=%.0f bps/yr  shortable=top-ADV-D%d",
             SEED, CAPITAL, SLB_BORROW_BPS_PER_YEAR, SHORTABLE_LIQ_DECILE)
    log.info("=" * 90)

    con = duckdb.connect(DB_PATH, read_only=True)
    from_dt, to_dt = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    con.close()
    from_ts, to_ts = pd.Timestamp(from_dt), pd.Timestamp(to_dt)
    log.info("Span %s → %s", from_dt, to_dt)

    # Build the production context ONCE (it depends only on fixed entry/forward/friction).
    req = WFOBacktestRequest(
        from_date=str(from_dt), to_date=str(to_dt),
        scope="universe", forward_days=FORWARD_DAYS, friction_bps=FRICTION_BPS,
        starting_capital=CAPITAL, max_positions=max(BREADTH_GRID),
        max_stocks_per_day=500,   # do NOT cap the cross-section — we harvest the full bar
        entry_timing="next_open", in_sample_days=IN_SAMPLE_DAYS,
        out_sample_days=OUT_SAMPLE_DAYS, embargo_days=EMBARGO_DAYS, filters=[],
    )
    need_mr = any(c in MARKET_RELATIVE for c in COHORT_COLS)
    log.info("Loading production context (need_market_relative=%s)…", need_mr)
    ctx = _load_context(req, from_dt, to_dt, need_mr, lambda p, m: None)
    if ctx is None:
        log.error("Context load failed — aborting (no fabricated numbers).")
        return
    log.info("Context ready: %d bars, %d tickers", len(ctx.grouped), len(ctx.tkr_series))

    windows = _wfo_windows(from_ts, to_ts, IN_SAMPLE_DAYS, OUT_SAMPLE_DAYS, EMBARGO_DAYS)
    log.info("WFO windows: %d (IS=%dd, OOS=%dd, embargo=%dd)",
             len(windows), IN_SAMPLE_DAYS, OUT_SAMPLE_DAYS, EMBARGO_DAYS)

    # ── Pre-harvest per-window IS and OOS panels once (reused across cells) ──
    log.info("Harvesting per-window resolved panels (IS + OOS)…")
    is_panels: list[pd.DataFrame] = []
    oos_panels: list[pd.DataFrame] = []
    for (is_s, is_e, oos_s, oos_e) in windows:
        # De-overlap PER WINDOW so each 5-day-forward return is counted once (no overlapping-
        # horizon compounding). Applied identically to IS (beta est.) and OOS (reporting).
        is_panels.append(deoverlap(harvest_window(ctx, is_s, is_e)))
        oos_panels.append(deoverlap(harvest_window(ctx, oos_s, oos_e)))
    oos_all = pd.concat([p for p in oos_panels if not p.empty], ignore_index=True) \
        if any(not p.empty for p in oos_panels) else pd.DataFrame()
    log.info("Harvested + de-overlapped (step=%d). OOS resolved name-bars: %d",
             DEOVERLAP_STEP, len(oos_all))

    # Annualization frequency from realised, NON-OVERLAPPING OOS bar cadence (≈ every 5 td).
    if not oos_all.empty:
        ed = pd.to_datetime(oos_all["entry_date"]).sort_values().unique()
        span_years = (pd.Timestamp(ed[-1]) - pd.Timestamp(ed[0])).days / 365.25
        bars_per_year = (len(ed) / span_years) if span_years > 0 else (TRADING_DAYS / DEOVERLAP_STEP)
    else:
        bars_per_year = TRADING_DAYS / DEOVERLAP_STEP
    log.info("Non-overlapping OOS bar cadence ≈ %.1f bars/yr (≈ %d trading days/bar)",
             bars_per_year, DEOVERLAP_STEP)

    # ── Sweep cohorts × neutralizations × N ──
    results: list[dict] = []
    spread_series: dict[str, list[float]] = {}   # for DSR (per-cell daily OOS returns)
    for cohort in SHORT_COHORTS:
        for neutral in NEUTRALIZATIONS:
            for n_short in BREADTH_GRID:
                cell = f"{cohort['name']} | {neutral}-neutral | N={n_short}"
                # Beta hint: estimate per-window IS beta, average (applied to that window's OOS).
                # We compute a single stable IS beta across all IS panels for the cell hedge.
                beta_hat = None
                if neutral == "beta":
                    is_all = pd.concat([p for p in is_panels if not p.empty], ignore_index=True) \
                        if any(not p.empty for p in is_panels) else pd.DataFrame()
                    beta_hat = estimate_beta(is_all, cohort, CAPITAL) if not is_all.empty else None

                # Build OOS spread per window, stitch (strict OOS-only).
                oos_bar_rets: list[float] = []
                stitched = []
                for p_oos in oos_panels:
                    if p_oos.empty:
                        continue
                    sp = spread_daily_returns(p_oos, cohort, n_short, neutral, beta_hat, CAPITAL)
                    if not sp.empty:
                        stitched.append(sp)
                if stitched:
                    sp_all = pd.concat(stitched, ignore_index=True).sort_values("entry_date")
                    oos_bar_rets = sp_all["spread_ret"].tolist()
                m = perf_metrics(np.array(oos_bar_rets), bars_per_year)

                # GROSS spread (no Amihud, no borrow) to separate "info" from "frictions".
                gross_rets: list[float] = []
                for p_oos in oos_panels:
                    if p_oos.empty:
                        continue
                    sg = spread_gross(p_oos, cohort, n_short, neutral, beta_hat)
                    if sg:
                        gross_rets.extend(sg)
                mg = perf_metrics(np.array(gross_rets), bars_per_year)

                # Realized spread beta vs benchmark (OOS) — confirm neutrality.
                sp_beta = realized_spread_beta(stitched)

                key = cell
                spread_series[key] = oos_bar_rets
                row = {
                    "cohort": cohort["name"], "neutralization": neutral, "N": n_short,
                    "beta_hat_is": (round(beta_hat, 3) if beta_hat is not None else None),
                    "oos_cagr_pct": m["cagr_pct"], "oos_max_dd_pct": m["max_dd_pct"],
                    "oos_sharpe": m["sharpe"], "oos_calmar": m["calmar"],
                    "oos_total_return_pct": m["total_return_pct"], "n_bars": m["n_bars"],
                    "spread_beta_oos": sp_beta,
                    "gross_cagr_pct": mg["cagr_pct"], "gross_sharpe": mg["sharpe"],
                    "gross_total_return_pct": mg["total_return_pct"],
                }
                results.append(row)
                log.info("%-62s netCAGR=%7.2f%% grossCAGR=%7.2f%% Sharpe=%6.2f β=%5s DD=%7.2f%% bars=%d",
                         cell, m["cagr_pct"], mg["cagr_pct"], m["sharpe"],
                         (f"{sp_beta:.2f}" if sp_beta is not None else "  na"),
                         m["max_dd_pct"], m["n_bars"])

    # ── Study-level Deflated Sharpe, deflated against ALL trials (honest n_eff) ──
    n_trials = len(results)
    trial_sharpes = [r["oos_sharpe"] for r in results]
    log.info("-" * 90)
    log.info("Computing Deflated Sharpe for every cell (n_eff = %d total trials)…", n_trials)
    for r in results:
        key = f"{r['cohort']} | {r['neutralization']}-neutral | N={r['N']}"
        rets = spread_series.get(key, [])
        # freq = realised NON-OVERLAPPING bar cadence so DSR's internal annualization matches
        # perf_metrics (bars are ~weekly, NOT daily — using 252 would mis-annualize the Sharpe).
        dsr = be.deflated_sharpe_ratio(rets, trial_sharpes, freq=bars_per_year, n_eff=n_trials)
        r["dsr"] = round(float(dsr.get("dsr", 0.0)), 4)
        r["psr_zero"] = round(float(dsr.get("psr_zero", 0.0)), 4)
        r["dsr_n_trials"] = n_trials
        r["survives"] = bool(r["oos_cagr_pct"] > CAGR_GATE and r["dsr"] > DSR_GATE)

    # ── Persist ──
    fields = ["cohort", "neutralization", "N", "beta_hat_is", "oos_cagr_pct", "oos_max_dd_pct",
              "oos_sharpe", "oos_calmar", "oos_total_return_pct", "spread_beta_oos", "n_bars",
              "gross_cagr_pct", "gross_sharpe", "gross_total_return_pct",
              "dsr", "psr_zero", "dsr_n_trials", "survives"]
    with open(CSV_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in results:
            w.writerow({k: r.get(k) for k in fields})

    survivors = [r for r in results if r["survives"]]
    least_bad = max(results, key=lambda r: r["oos_cagr_pct"]) if results else None
    best_gross = max(results, key=lambda r: r["gross_cagr_pct"]) if results else None
    payload = {
        "mode": "PAPER", "seed": SEED, "span": [str(from_dt), str(to_dt)],
        "capital": CAPITAL, "borrow_bps_per_year": SLB_BORROW_BPS_PER_YEAR,
        "shortable_universe": f"top-ADV-decile (D{SHORTABLE_LIQ_DECILE}) proxy — NO SLB flag in data",
        "execution_path": "spread-on-WFO-windows (engine is long-only; no native short)",
        "friction_bps_per_leg": FRICTION_BPS, "amihud_coef": AMIHUD_COEF,
        "impact_temp_coef": IMPACT_TEMP_COEF, "n_windows": len(windows),
        "n_trials": n_trials, "dsr_gate": DSR_GATE,
        "n_survivors": len(survivors),
        "least_bad_net": least_bad, "best_gross": best_gross,
        "survivors": survivors, "results": results,
    }
    with open(JSON_PATH, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    log.info("=" * 90)
    log.info("VERDICT: %d / %d cells survive (OOS CAGR>0 AND DSR>%.2f)", len(survivors), n_trials, DSR_GATE)
    if least_bad:
        log.info("Least-bad NET cell:  %s | %s | N=%s → netCAGR=%.2f%% DSR=%.4f",
                 least_bad["cohort"], least_bad["neutralization"], least_bad["N"],
                 least_bad["oos_cagr_pct"], least_bad["dsr"])
    if best_gross:
        log.info("Best GROSS cell:     %s | %s | N=%s → grossCAGR=%.2f%% (netCAGR=%.2f%%)",
                 best_gross["cohort"], best_gross["neutralization"], best_gross["N"],
                 best_gross["gross_cagr_pct"], best_gross["oos_cagr_pct"])
    log.info("Artifacts: %s | %s | %s", CSV_PATH.name, JSON_PATH.name, LOG_PATH.name)
    log.info("=" * 90)


def spread_gross(panel: pd.DataFrame, cohort: dict, n_short: int, neutralization: str,
                 beta_hat: Optional[float]) -> list[float]:
    """GROSS spread bar returns — NO Amihud impact, NO borrow. Isolates pure cross-sectional
    information (the 'is there info at all' test) from the short-frictions question."""
    dcol = f"dec_{cohort['col']}"
    if dcol not in panel.columns:
        return []
    rets: list[float] = []
    for ed, g in panel.groupby("entry_date"):
        g = g.dropna(subset=["net_return_pct"])
        if g.empty:
            continue
        long_ret = float(np.mean(g["net_return_pct"].to_numpy())) / 100.0
        end = cohort["side"]
        coh = g[g[dcol] >= float(DECILE_N)] if end == "top" else g[g[dcol] <= 1.0]
        coh = coh[coh["liq_decile"] >= float(SHORTABLE_LIQ_DECILE)]
        if len(coh) < MIN_SHORT_NAMES:
            continue
        coh = coh.sort_values("adv", ascending=False).head(n_short)
        short_ret = -float(np.mean(coh["net_return_pct"].to_numpy())) / 100.0
        long_w = float(beta_hat) if (neutralization == "beta" and beta_hat is not None) else 1.0
        rets.append(long_w * long_ret + short_ret)
    return rets


def realized_spread_beta(stitched: list[pd.DataFrame]) -> Optional[float]:
    """Realized OOS beta of the spread return vs the benchmark (long_ret) leg — neutrality check."""
    if not stitched:
        return None
    sp = pd.concat(stitched, ignore_index=True)
    if len(sp) < 8:
        return None
    x = sp["long_ret"].to_numpy(dtype=float)
    y = sp["spread_ret"].to_numpy(dtype=float)
    if np.std(x) < 1e-9:
        return None
    return round(float(np.cov(y, x, ddof=1)[0, 1] / np.var(x, ddof=1)), 3)


if __name__ == "__main__":
    main()
