"""decile_combinatorial_optimizer.py — dynamic-decile alpha-filter combinatorial search.

An elite, fully-vectorized SIGNAL-RESEARCH engine over the 5-year NSE DuckDB history.
For each alpha filter it builds a daily cross-sectional DECILE distribution, auto-discovers
the filter's optimal *extreme* decile band by forward-return edge, then runs an exhaustive
K>=2 combinatorial search intersecting those optimal bands. Every configuration is scored
with an overall matrix (trades / win% / profit-factor / max-DD% / CAGR / Calmar) plus a
year-over-year matrix, low-sample anomalies are culled, and the survivors are ranked by
Calmar into a professional DECILE_OPTIMIZATION_REPORT.md with ASCII decile charts and
solo-vs-combined + YoY tables.

This is HYPOTHESIS-GENERATION to surface robust multi-factor screens — NOT a capital
certification. With ~2k trials the best-by-chance bias is real: winners must be re-validated
through the production walk-forward engine + trial_ledger / Deflated-Sharpe before any capital.

Design contract (CLAUDE.md):
  * Factors are strictly TRAILING (computed by the production backtest_engine); the forward
    5-day return is the OUTCOME only, never a feature → zero look-ahead.
  * >= 0.15% round-trip friction is subtracted from every trade (the hard floor).
  * MODE=PAPER. Canonical Python only. Read-only DB. No secrets.

Reuses the production factor engine (no re-implementation):
  * services/ui-api/backtest_engine.py :: compute_indicators / compute_market_relative
  * sector map mirrors routers/analytics.py :: _sector_map (data/NSE_1500.csv)

Run:
  DB_PATH=.../data/market.duckdb /Users/sudheer/Desktop/jupyter_env/bin/python \
      scripts/decile_combinatorial_optimizer.py --stage smoke   # 3 filters, validate
  ...                                            --stage full    # all 11 filters
"""
from __future__ import annotations

import os
import sys
import argparse
import itertools
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import duckdb

# ── Bootstrap (mirror scripts/generate_oos_propensity.py) ─────────────────────────────
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))                                  # shared.*
sys.path.insert(0, str(REPO / "services" / "ui-api"))          # backtest_engine
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import backtest_engine as be  # noqa: E402  (production trailing-factor engine)

# ── Constants ─────────────────────────────────────────────────────────────────────────
HORIZON = 5                      # forward holding period (trading days)
FRICTION = 0.0015                # 0.15% round-trip friction floor (CLAUDE.md hard rule)
MIN_TRADES = 120                 # cull any config with fewer trades over the 5y history
MIN_BAND_TRADES = 250            # an optimal decile band must clear this sample to qualify
N_DECILES = 10
TOP_SYSTEMS = 15                 # detailed blocks rendered in the report
MAX_TABLE_ROWS = 100             # rows rendered in the full ranked table (rest → CSV)

# All 11 trailing, bias-free continuous factors (DataFrame column names, not filter ids).
ALL_FACTORS = [
    "vmi_ratio", "vol_zscore_20", "intraday_intention", "squeeze_ratio",
    "sector_rel_mom_14_pct", "corr_nifty_30",
    "rsi_14", "atr_pct", "above_52w_low_pct", "within_52w_high_pct", "dist_ma200_pct",
]
SMOKE_FACTORS = ["vmi_ratio", "vol_zscore_20", "squeeze_ratio"]   # 3 → 4 combos
MARKET_REL_FACTORS = {"sector_rel_mom_14_pct", "corr_nifty_30"}    # need compute_market_relative

# Short labels for readable report tables / combo names.
SHORT = {
    "vmi_ratio": "VMI", "vol_zscore_20": "VIPT", "intraday_intention": "Intent",
    "squeeze_ratio": "Squeeze", "sector_rel_mom_14_pct": "SectDisp", "corr_nifty_30": "BetaCpl",
    "rsi_14": "RSI", "atr_pct": "ATR", "above_52w_low_pct": "Abv52L",
    "within_52w_high_pct": "Nr52H", "dist_ma200_pct": "Dist200",
}

# Candidate optimal bands: only the extremes, so the rule reads as "Top/Bottom X%".
CANDIDATE_BANDS: dict[str, list[int]] = {
    "Top 10%": [10], "Top 20%": [9, 10], "Top 30%": [8, 9, 10],
    "Bottom 10%": [1], "Bottom 20%": [1, 2], "Bottom 30%": [1, 2, 3],
}


def log(msg: str) -> None:
    print(msg, flush=True)


# ── Sector map (mirror analytics._sector_map: data/NSE_1500.csv) ──────────────────────
def sector_map() -> dict[str, str]:
    path = os.getenv("STOCK_UNIVERSE_PATH") or str(REPO / "data" / "NSE_1500.csv")
    mapping: dict[str, str] = {}
    try:
        udf = pd.read_csv(path, usecols=["ticker", "sector"])
        for t, s in zip(udf["ticker"], udf["sector"]):
            if isinstance(t, str):
                mapping[t.upper()] = s.strip() if isinstance(s, str) and s.strip() else "Unknown"
    except Exception as e:
        log(f"  ⚠ sector map unavailable ({str(e)[:80]}); sector-dispersion factor may degrade")
    return mapping


# ── Pillar 0: data + trailing-factor prep (one pass, memory-efficient) ────────────────
def load_prepared(con, factors: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Load OHLCV → adjusted-close basis → production trailing factors → forward 5d NET
    return target. Returns (slim frame sorted by date, factors actually present)."""
    rows = con.execute(
        "SELECT ticker, date, open, high, low, close, volume, adjusted_close "
        "FROM ohlcv ORDER BY ticker, date"
    ).fetchall()
    df = pd.DataFrame(rows, columns=["ticker", "date", "open", "high", "low",
                                     "close", "volume", "adjusted_close"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "adjusted_close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Split/dividend adjustment onto the adjusted-close basis (analytics._load_prepared).
    adj = (df["adjusted_close"] / df["close"]).where(
        (df["close"] > 0) & df["adjusted_close"].notna(), 1.0)
    for c in ("open", "high", "low", "close"):
        df[c] = df[c] * adj
    df = df.drop(columns=["adjusted_close"])

    df = be.compute_indicators(df)
    need_mr = bool(MARKET_REL_FACTORS.intersection(factors))
    if need_mr:
        try:
            df = be.compute_market_relative(df, sector_map())
        except Exception as e:
            log(f"  ⚠ compute_market_relative failed ({str(e)[:80]}); dropping market-relative factors")
            for col in MARKET_REL_FACTORS:
                if col in df.columns:
                    df = df.drop(columns=[col])

    # Forward 5d NET return (the OUTCOME only — never a feature). Per ticker, no leak across names.
    df = df.sort_values(["ticker", "date"])
    fwd = df.groupby("ticker", sort=False)["close"].shift(-HORIZON)
    df["net_ret"] = (fwd / df["close"] - 1.0) - FRICTION

    present = [f for f in factors if f in df.columns]
    missing = [f for f in factors if f not in df.columns]
    if missing:
        log(f"  ⚠ factors absent from frame (skipped): {missing}")

    keep = ["ticker", "date", "net_ret", *present]
    df = df[keep].replace([np.inf, -np.inf], np.nan)
    df = df.dropna(subset=["net_ret"])                       # drop unrealised tail (last 5 bars)
    for f in present:
        df[f] = df[f].astype("float32")
    df = df.sort_values(["date", "ticker"]).reset_index(drop=True)
    return df, present


# ── Pillar 1: dynamic decile ranking + optimal-band discovery ─────────────────────────
def assign_deciles(df: pd.DataFrame, factors: list[str]) -> None:
    """Add a daily cross-sectional decile (1..10) column per factor, in place. Vectorised
    groupby-rank; NaN factor values get NaN decile (excluded from every band)."""
    for f in factors:
        r = df.groupby("date")[f].rank(pct=True, method="first")
        dec = np.ceil(r * N_DECILES)
        df[f"dec_{f}"] = dec.clip(1, N_DECILES)


def decile_distribution(df: pd.DataFrame, f: str) -> pd.DataFrame:
    """Per-decile aggregate of net_ret for one factor (deciles 1..10)."""
    g = df.dropna(subset=[f"dec_{f}"]).groupby(f"dec_{f}")["net_ret"]
    dist = g.agg(n="size", mean="mean", std="std",
                 win=lambda s: float((s > 0).mean())).reindex(range(1, N_DECILES + 1))
    return dist


def monotonicity(dist: pd.DataFrame) -> float:
    """Spearman rank-correlation between decile index (1..10) and per-decile mean return.
    +1 ⇒ cleanly increasing edge, −1 ⇒ cleanly decreasing, ~0 ⇒ non-monotonic (noise).
    A 'Top/Bottom X%' rule only captures a *real* edge when |monotonicity| is high."""
    m = dist["mean"].to_numpy(dtype=float)
    valid = np.isfinite(m)
    if int(valid.sum()) < 3:
        return float("nan")
    rd = pd.Series(np.arange(1, N_DECILES + 1)[valid]).rank().to_numpy()
    rm = pd.Series(m[valid]).rank().to_numpy()
    if rd.std() < 1e-12 or rm.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(rd, rm)[0, 1])


def pick_optimal_band(df: pd.DataFrame, f: str) -> Optional[dict]:
    """Choose the extreme decile band with the best per-trade information ratio (mean/std),
    requiring n >= MIN_BAND_TRADES and a positive (post-friction) mean. None ⇒ no edge."""
    dcol = f"dec_{f}"
    best: Optional[dict] = None
    for label, decs in CANDIDATE_BANDS.items():
        sub = df.loc[df[dcol].isin(decs), "net_ret"]
        n = int(sub.size)
        if n < MIN_BAND_TRADES:
            continue
        mean = float(sub.mean())
        std = float(sub.std())
        if not np.isfinite(mean) or mean <= 0:
            continue
        ir = mean / std if std > 1e-12 else 0.0
        cand = {"factor": f, "band": label, "deciles": decs, "ir": ir,
                "mean": mean, "n": n, "win": float((sub > 0).mean())}
        if best is None or ir > best["ir"]:
            best = cand
    return best


# ── Pillar 3: metric engine (fast numpy; daily-basket signal-proxy equity) ────────────
class MetricEngine:
    """Precomputes chronological date codes + per-code year so every config's overall +
    YoY + daily-basket equity metrics are pure numpy bincount ops (no per-combo groupby)."""

    def __init__(self, df: pd.DataFrame):
        self.net = df["net_ret"].to_numpy(dtype=np.float64)
        codes, uniq = pd.factorize(df["date"], sort=True)       # codes chronological (df sorted by date)
        self.codes = codes.astype(np.int64)
        self.uniq_dates = pd.DatetimeIndex(uniq)
        self.n_dates = len(uniq)
        self.year_of_code = self.uniq_dates.year.to_numpy()
        self.ordinal = self.uniq_dates.map(lambda d: d.toordinal()).to_numpy(dtype=np.float64)

    def evaluate(self, mask: np.ndarray) -> Optional[dict]:
        idx = np.flatnonzero(mask)
        if idx.size < MIN_TRADES:
            return None
        r = self.net[idx]
        dc = self.codes[idx]
        # Trade-level
        n = int(idx.size)
        win = float((r > 0).mean()) * 100.0
        avg = float(r.mean()) * 100.0
        pos = float(r[r > 0].sum())
        neg = float(r[r < 0].sum())
        pf = (pos / abs(neg)) if neg < 0 else float("inf")
        # Daily-basket equity (signal proxy): mean net_ret per entry date, compounded.
        # OVERLAP CORRECTION — a trade is held HORIZON days, so on any calendar day only
        # ~1/HORIZON of the book matures (deploy 1/H capital per day, H rolling tranches).
        # Dividing the daily basket return by HORIZON de-overlaps the compounding; without
        # it, ~H overlapping H-day returns are compounded daily and inflate CAGR/MaxDD ~Hx.
        sums = np.bincount(dc, weights=r, minlength=self.n_dates)
        cnts = np.bincount(dc, minlength=self.n_dates)
        present = np.flatnonzero(cnts > 0)                       # already chronological
        daily = (sums[present] / cnts[present]) / HORIZON
        eq = np.cumprod(1.0 + daily)
        peak = np.maximum.accumulate(eq)
        dd = eq / peak - 1.0
        maxdd = float(dd.min()) * 100.0
        eqf = float(eq[-1])
        yrs = max((self.ordinal[present[-1]] - self.ordinal[present[0]]) / 365.25, 1e-9)
        cagr = (eqf ** (1.0 / yrs) - 1.0) * 100.0 if eqf > 0 else -100.0
        calmar = (cagr / abs(maxdd)) if maxdd < -1e-9 else float("nan")
        # YoY matrix (compound the daily basket within each calendar year)
        yoy: dict[int, dict] = {}
        yrs_present = self.year_of_code[present]
        for y in np.unique(yrs_present):
            ymask = yrs_present == y
            yret = (np.prod(1.0 + daily[ymask]) - 1.0) * 100.0
            ntr = int(cnts[present][ymask].sum())
            yoy[int(y)] = {"ret": float(yret), "n": ntr}
        n_pos_years = sum(1 for v in yoy.values() if v["ret"] > 0)
        consistency = n_pos_years / len(yoy) if yoy else 0.0
        return {
            "trades": n, "win": win, "pf": pf, "avg": avg,
            "cagr": cagr, "maxdd": maxdd, "calmar": calmar,
            "consistency": consistency, "n_years": len(yoy), "yoy": yoy,
        }


# ── ASCII rendering helpers ───────────────────────────────────────────────────────────
def ascii_decile_chart(dist: pd.DataFrame, chosen: Optional[set[int]], width: int = 34) -> str:
    means = [dist["mean"].get(d, np.nan) for d in range(1, N_DECILES + 1)]
    finite = [abs(m) * 100 for m in means if np.isfinite(m)]
    vmax = max(finite) if finite else 1.0
    lines = []
    for d in range(1, N_DECILES + 1):
        m = means[d - 1]
        if not np.isfinite(m):
            lines.append(f"  D{d:>2}        (no data)")
            continue
        pct = m * 100
        nb = int(round(abs(pct) / vmax * width)) if vmax > 0 else 0
        glyph = "█" if pct >= 0 else "▒"
        mark = " *" if (chosen and d in chosen) else "  "
        lines.append(f"  D{d:>2}{mark}| {glyph * max(nb, 0)} {pct:+.3f}%")
    return "\n".join(lines)


def ascii_yoy_bars(yoy: dict[int, dict], width: int = 30) -> str:
    if not yoy:
        return "  (no yearly data)"
    vmax = max((abs(v["ret"]) for v in yoy.values()), default=1.0) or 1.0
    lines = []
    for y in sorted(yoy):
        ret = yoy[y]["ret"]
        nb = int(round(abs(ret) / vmax * width))
        glyph = "█" if ret >= 0 else "▒"
        lines.append(f"  {y} | {glyph * max(nb, 0)} {ret:+.2f}%  (n={yoy[y]['n']})")
    return "\n".join(lines)


def fpf(pf: float) -> str:
    return "∞" if pf == float("inf") else f"{pf:.2f}"


def fcal(c: float) -> str:
    return "—" if not np.isfinite(c) else f"{c:.2f}"


# ── Report builder ────────────────────────────────────────────────────────────────────
def build_report(stage: str, df: pd.DataFrame, factors: list[str],
                 bands: dict[str, dict], excluded: list[str],
                 solo: dict[str, dict], combos: list[dict], years: list[int]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    span = f"{df['date'].min().date()} → {df['date'].max().date()}"
    L: list[str] = []
    L.append(f"# Decile Combinatorial Optimization Report")
    L.append("")
    L.append(f"> **Signal-research scan — hypothesis generation, NOT a capital certification.** "
             f"Winners must be re-validated through the production walk-forward engine + "
             f"`trial_ledger`/Deflated-Sharpe before any capital is risked.")
    L.append("")
    L.append(f"- **Generated:** {now}  ·  **Stage:** `{stage}`  ·  **MODE:** PAPER")
    L.append(f"- **Universe:** {df['ticker'].nunique():,} NSE tickers (full traded universe, PIT-active per day)")
    L.append(f"- **History:** {span}  ·  **Rows:** {len(df):,}  ·  **Horizon:** {HORIZON}d  ·  "
             f"**Friction:** {FRICTION*100:.2f}% round-trip")
    L.append(f"- **Factors searched:** {len(factors)} requested → {len(bands)} with edge "
             f"({len(excluded)} excluded)  ·  **Surviving combos (≥{MIN_TRADES} trades):** {len(combos)}")
    L.append(f"- **Equity model:** daily-basket signal proxy (trade-level + YoY are exact; "
             f"CAGR/MaxDD/Calmar are an internally-consistent proxy for ranking)")
    L.append("")

    # ── Section A — optimal decile bands ──
    L.append("## A. Optimal Decile Bands (auto-discovered)")
    L.append("")
    L.append("Each factor's daily cross-section is ranked into 10 deciles; the *extreme* band with the "
             "best per-trade information ratio (mean/σ, net of friction, n≥%d) is selected as its rule." % MIN_BAND_TRADES)
    L.append("")
    L.append("`Mono` = Spearman(decile → mean return): |Mono|→1 is a clean monotone gradient; "
             "~0 means the 'Top/Bottom X%' rule sits on a **non-monotonic (noisy)** factor — treat its edge with suspicion.")
    L.append("")
    L.append("| Factor | Rule | Deciles | Mono | IR | Mean net 5d | Win% | n |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|")
    weak: list[str] = []
    for f in factors:
        b = bands.get(f)
        if not b:
            continue
        mono = b.get("mono", float("nan"))
        flag = " ⚠" if np.isfinite(mono) and abs(mono) < 0.3 else ""
        if flag:
            weak.append(SHORT.get(f, f))
        L.append(f"| {SHORT.get(f,f)} (`{f}`) | **{b['band']}** | {b['deciles']} | "
                 f"{mono:+.2f}{flag} | {b['ir']:.3f} | {b['mean']*100:+.3f}% | {b['win']*100:.1f}% | {b['n']:,} |")
    if weak:
        L.append("")
        L.append(f"**⚠ Non-monotonic factors (|Mono| < 0.30 — band edge is likely noise):** "
                 + ", ".join(weak))
    if excluded:
        L.append("")
        L.append(f"**Excluded (no positive-edge extreme band):** "
                 + ", ".join(f"`{e}`" for e in excluded))
    L.append("")
    L.append("### Per-factor decile distribution (mean net 5d return; `*` = chosen band)")
    for f in factors:
        if f not in bands:
            continue
        L.append("")
        L.append(f"**{SHORT.get(f,f)}** — `{f}` → {bands[f]['band']}")
        L.append("```")
        L.append(ascii_decile_chart(decile_distribution(df, f), set(bands[f]["deciles"])))
        L.append("```")
    L.append("")

    # ── Section B — top systems ──
    L.append(f"## B. Top {min(TOP_SYSTEMS, len(combos))} Systems by Calmar")
    L.append("")
    for rank, c in enumerate(combos[:TOP_SYSTEMS], 1):
        names = " + ".join(SHORT.get(f, f) for f in c["factors"])
        L.append(f"### {rank}. {names}  (K={c['k']})")
        L.append("")
        L.append(f"- **Calmar {fcal(c['calmar'])}**  ·  CAGR {c['cagr']:+.2f}%  ·  MaxDD {c['maxdd']:.2f}%  "
                 f"·  Trades {c['trades']:,}  ·  Win {c['win']:.1f}%  ·  PF {fpf(c['pf'])}  "
                 f"·  Consistency {c['consistency']*100:.0f}% ({sum(1 for v in c['yoy'].values() if v['ret']>0)}/{c['n_years']} yrs)")
        L.append("")
        # Solo vs combined
        L.append("| Config | Trades | Win% | PF | Avg net | CAGR | MaxDD | Calmar |")
        L.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for f in c["factors"]:
            s = solo.get(f)
            if not s:
                L.append(f"| {SHORT.get(f,f)} *(solo)* | — | — | — | — | — | — | — |")
                continue
            L.append(f"| {SHORT.get(f,f)} *(solo)* | {s['trades']:,} | {s['win']:.1f}% | {fpf(s['pf'])} | "
                     f"{s['avg']:+.3f}% | {s['cagr']:+.2f}% | {s['maxdd']:.2f}% | {fcal(s['calmar'])} |")
        L.append(f"| **COMBINED** | **{c['trades']:,}** | **{c['win']:.1f}%** | **{fpf(c['pf'])}** | "
                 f"**{c['avg']:+.3f}%** | **{c['cagr']:+.2f}%** | **{c['maxdd']:.2f}%** | **{fcal(c['calmar'])}** |")
        L.append("")
        # YoY matrix
        hdr = "| Config | " + " | ".join(str(y) for y in years) + " |"
        sep = "|---|" + "|".join(["---:"] * len(years)) + "|"
        L.append("**Year-over-Year net return**")
        L.append("")
        L.append(hdr)
        L.append(sep)
        for f in c["factors"]:
            s = solo.get(f)
            cells = [f"{s['yoy'][y]['ret']:+.1f}%" if s and y in s["yoy"] else "·" for y in years]
            L.append(f"| {SHORT.get(f,f)} *(solo)* | " + " | ".join(cells) + " |")
        cells = [f"**{c['yoy'][y]['ret']:+.1f}%**" if y in c["yoy"] else "·" for y in years]
        L.append(f"| **COMBINED** | " + " | ".join(cells) + " |")
        L.append("")
        L.append("```")
        L.append(ascii_yoy_bars(c["yoy"]))
        L.append("```")
        L.append("")

    # ── Section C — full ranked table ──
    L.append(f"## C. Full Ranked Table (top {min(MAX_TABLE_ROWS, len(combos))} of {len(combos)}; "
             f"full set in `decile_optimization_results.csv`)")
    L.append("")
    L.append("| # | System | K | Trades | Win% | PF | MaxDD% | CAGR% | Calmar | Consist |")
    L.append("|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i, c in enumerate(combos[:MAX_TABLE_ROWS], 1):
        names = "+".join(SHORT.get(f, f) for f in c["factors"])
        L.append(f"| {i} | {names} | {c['k']} | {c['trades']:,} | {c['win']:.1f} | {fpf(c['pf'])} | "
                 f"{c['maxdd']:.1f} | {c['cagr']:+.1f} | {fcal(c['calmar'])} | {c['consistency']*100:.0f}% |")
    L.append("")

    # ── Section D — methodology ──
    L.append("## D. Methodology & Honest Caveats")
    L.append("")
    L.append(f"- **Deciles:** daily cross-sectional rank into 10 buckets per factor; the optimal "
             f"*extreme* band (Top/Bottom 10/20/30%) is chosen by per-trade information ratio (mean/σ) "
             f"net of {FRICTION*100:.2f}% friction, requiring n≥{MIN_BAND_TRADES} and a positive mean.")
    L.append(f"- **Combinations:** all K≥2 intersections (logical AND) of the surviving optimal bands.")
    L.append(f"- **Equity:** each entry date forms an equal-weight basket of qualifying names; the "
             f"per-date basket {HORIZON}d return is **overlap-corrected** (÷{HORIZON}, since only ~1/{HORIZON} "
             f"of the book matures each calendar day with rolling tranches) then compounded into one curve. "
             f"A signal proxy — the production `_core_backtest` is the capital-accurate engine with position "
             f"limits + market impact.")
    L.append(f"- **Cull:** configs with < {MIN_TRADES} trades over the full history are discarded.")
    L.append(f"- **Look-ahead:** every factor is strictly trailing (production `compute_indicators` / "
             f"`compute_market_relative`); the forward {HORIZON}-day return is the outcome only.")
    L.append(f"- **Survivorship:** the full traded universe is used (as-of index-membership tables are "
             f"empty); pre-2021 entrants/exits are not reconstructed — treat absolute levels accordingly.")
    L.append(f"- **Data-snooping:** {len(combos)} surviving trials means the top Calmar is upward-biased "
             f"by selection. This report RANKS hypotheses; it does not certify edges. Re-run the top "
             f"systems through the production WFO + `trial_ledger`/DSR before risking capital.")
    L.append("")
    return "\n".join(L)


# ── Orchestration ─────────────────────────────────────────────────────────────────────
def run(stage: str) -> None:
    factors_req = SMOKE_FACTORS if stage == "smoke" else ALL_FACTORS
    log(f"MODE=PAPER  DB={DB_PATH}")
    log(f"=== STAGE {stage.upper()} — {len(factors_req)} factors: "
        f"{[SHORT.get(f,f) for f in factors_req]} ===")

    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        log("Loading OHLCV + computing trailing factors + forward target …")
        df, factors = load_prepared(con, factors_req)
    finally:
        con.close()
    log(f"  prepared: {len(df):,} rows · {df['ticker'].nunique()} tickers · "
        f"{df['date'].min().date()}→{df['date'].max().date()} · factors present: {len(factors)}")

    # Pillar 1 — deciles + optimal bands
    log("Pillar 1: daily decile ranking + optimal-band discovery …")
    assign_deciles(df, factors)
    bands: dict[str, dict] = {}
    excluded: list[str] = []
    for f in factors:
        b = pick_optimal_band(df, f)
        if b is None:
            excluded.append(f)
            log(f"  {SHORT.get(f,f):8s} → no positive-edge band (excluded)")
        else:
            b["mono"] = monotonicity(decile_distribution(df, f))
            bands[f] = b
            df[f"opt_{f}"] = df[f"dec_{f}"].isin(b["deciles"]).to_numpy()
            log(f"  {SHORT.get(f,f):8s} → {b['band']:9s} IR={b['ir']:.3f} "
                f"mean={b['mean']*100:+.3f}% mono={b['mono']:+.2f} n={b['n']:,}")
    survivors = list(bands.keys())
    if len(survivors) < 2:
        log(f"✖ only {len(survivors)} factor(s) survived — need ≥2 for a combination. Stopping.")
        return

    engine = MetricEngine(df)
    opt_arrays = {f: df[f"opt_{f}"].to_numpy(dtype=bool) for f in survivors}
    years = sorted({int(y) for y in df["date"].dt.year.unique()})

    # Solo metrics (each surviving factor's optimal band on its own)
    solo: dict[str, dict] = {}
    for f in survivors:
        m = engine.evaluate(opt_arrays[f])
        if m:
            solo[f] = m | {"factors": [f]}

    # Pillar 2 — combinatorial search (K≥2)
    log(f"Pillar 2: combinatorial search over {len(survivors)} factors (K=2..{len(survivors)}) …")
    combos: list[dict] = []
    n_tested = 0
    for k in range(2, len(survivors) + 1):
        for combo in itertools.combinations(survivors, k):
            n_tested += 1
            mask = opt_arrays[combo[0]].copy()
            for f in combo[1:]:
                mask &= opt_arrays[f]
            m = engine.evaluate(mask)              # None when < MIN_TRADES
            if m is None:
                continue
            combos.append(m | {"factors": list(combo), "k": k})
    log(f"  tested {n_tested:,} combinations → {len(combos):,} survived the ≥{MIN_TRADES}-trade floor")

    # Pillar 4 — rank by Calmar (NaN/inf last), then CAGR
    def sort_key(c: dict):
        cal = c["calmar"]
        return (cal if np.isfinite(cal) else -1e18, c["cagr"])
    combos.sort(key=sort_key, reverse=True)

    # CSV sidecar (full set, programmatic)
    csv_path = REPO / "decile_optimization_results.csv"
    if combos:
        rec = pd.DataFrame([{
            "system": "+".join(SHORT.get(f, f) for f in c["factors"]),
            "factors": ";".join(c["factors"]), "k": c["k"], "trades": c["trades"],
            "win_pct": round(c["win"], 2), "profit_factor": (None if c["pf"] == float("inf") else round(c["pf"], 4)),
            "avg_net_pct": round(c["avg"], 4), "cagr_pct": round(c["cagr"], 3),
            "maxdd_pct": round(c["maxdd"], 3),
            "calmar": (None if not np.isfinite(c["calmar"]) else round(c["calmar"], 4)),
            "consistency_pct": round(c["consistency"] * 100, 1),
        } for c in combos])
        rec.insert(0, "rank", range(1, len(rec) + 1))
        rec.to_csv(csv_path, index=False)
        log(f"  wrote {len(rec):,} ranked rows → {csv_path.name}")

    # Report
    report = build_report(stage, df, factors, bands, excluded, solo, combos, years)
    report_path = REPO / "DECILE_OPTIMIZATION_REPORT.md"
    report_path.write_text(report)
    log(f"  wrote report → {report_path.name}")

    # Console summary of the podium
    log(f"\n── Top {min(5, len(combos))} by Calmar ──")
    for i, c in enumerate(combos[:5], 1):
        log(f"  {i}. {'+'.join(SHORT.get(f,f) for f in c['factors']):28s} "
            f"Calmar={fcal(c['calmar']):>6} CAGR={c['cagr']:+.1f}% MaxDD={c['maxdd']:.1f}% "
            f"trades={c['trades']:,} win={c['win']:.1f}%")
    log(f"\n{stage.upper()}_DONE — combos={len(combos)} report=DECILE_OPTIMIZATION_REPORT.md")


def main() -> None:
    ap = argparse.ArgumentParser(description="Dynamic-decile alpha-filter combinatorial optimizer")
    ap.add_argument("--stage", choices=["smoke", "full"], default="smoke",
                    help="smoke = 3 filters (validate); full = all 11 filters")
    run(ap.parse_args().stage)


if __name__ == "__main__":
    main()
