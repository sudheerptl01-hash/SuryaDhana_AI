"""
Monthly momentum allocator: the ONE implementation of universe, signals, regime
filter and selection, used by both the research backtest (scripts/phase_b_allocator.py)
and the live/paper Decision Desk (shared/decision_desk.py). Keeping a single code
path means live decisions cannot drift from what was tested.

Approved rule set (docs/PRODUCT_STRATEGY.md, owner approval 2026-09-27): see
StrategyConfig defaults. Evidence: reports/phase_b/, reports/phase_b_extended/.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[1]

UNIVERSE_SIZE = 300
MIN_PRICE = 20.0
MIN_HISTORY = 250


@dataclass(frozen=True)
class StrategyConfig:
    """The approved monthly rule set (separate from the legacy 5-day rules)."""
    signal: str = "mom_nse"          # mom_nse | mom_121 | lowvol | blend
    n: int = 20                      # target positions (≤ 20)
    buffer: float = 1.5              # holdings kept while rank ≤ buffer·n
    overlay: str = "nifty200_vt"     # none | nifty200 | nifty200_vt
    vol_target: float = 0.15         # annualised, for the _vt overlay
    equity_share: float = 0.66       # of capital in the strategy; rest in a liquid fund (Option B)
    sector_cap: float | None = 0.40  # max share of positions per NSE industry (None = off)
    max_position_pct: float = 0.15   # hard cap per stock (of total capital)
    emergency_dd: float = -0.20      # portfolio drawdown from peak → all to cash, manual re-enable
    cash_yield: float = 0.06         # liquid fund, for paper NAV
    # Block NEW entries in stocks a non-institutional client net-bought through a bulk deal in
    # the last N sessions (0 = off). Candidate rule under review: reports/desk_filter/REPORT.md.
    avoid_bulk_buy_days: int = 0

    @property
    def name(self) -> str:
        sc = f"|sc{int(self.sector_cap * 100)}" if self.sector_cap else ""
        bulk = f"|nobulk{self.avoid_bulk_buy_days}" if self.avoid_bulk_buy_days else ""
        return f"{self.signal}|N{self.n}|{self.overlay}{sc}{bulk}"

    def as_dict(self) -> dict:
        return asdict(self)


# ── reference data ──────────────────────────────────────────────────────────────

def _ref_dir() -> Path:
    for cand in (os.getenv("REFERENCE_DIR"), str(_ROOT / "data" / "reference"), "/data/reference"):
        if cand and Path(cand).is_dir():
            return Path(cand)
    return _ROOT / "data" / "reference"


def _symbol_column(path: Path) -> pd.Series:
    df = pd.read_csv(path)
    col = next(c for c in df.columns if c.strip().upper() == "SYMBOL")
    return df[col].astype(str).str.strip()


@lru_cache(maxsize=1)
def etf_symbols() -> frozenset[str]:
    p = _ref_dir() / "nse_etf_list.csv"
    return frozenset(_symbol_column(p)) if p.exists() else frozenset()


@lru_cache(maxsize=1)
def equity_symbols() -> frozenset[str]:
    p = _ref_dir() / "nse_equity_list.csv"
    return frozenset(_symbol_column(p)) if p.exists() else frozenset()


@lru_cache(maxsize=1)
def industries() -> dict[str, str]:
    """NSE industry per symbol (Nifty Total Market list); missing names are 'Unknown'."""
    p = _ref_dir() / "nse_industry.csv"
    if not p.exists():
        return {}
    df = pd.read_csv(p)
    cols = {c.strip().lower(): c for c in df.columns}
    return dict(zip(df[cols["symbol"]].astype(str).str.strip(), df[cols["industry"]].astype(str).str.strip()))


def is_etf(sym: str) -> bool:
    """Official ETF list, ETF-style suffixes, or index/commodity names that are not listed equities."""
    u = sym.upper()
    if sym in etf_symbols() or u.endswith(("BEES", "ETF", "IETF")):
        return True
    return sym not in equity_symbols() and any(t in u for t in ("NIFTY", "SENSEX", "GOLD", "SILVER"))


# ── signals (use data up to and including the signal close only) ───────────────

def signals(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    c = panel["close"]
    r = c.pct_change(fill_method=None)
    sigma = r.rolling(252, min_periods=200).std() * math.sqrt(252)
    ret6 = c / c.shift(126) - 1
    ret12 = c / c.shift(252) - 1

    def z(df: pd.DataFrame) -> pd.DataFrame:
        return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)

    return {
        "mom_nse": (z(ret6 / sigma) + z(ret12 / sigma)) / 2,
        "mom_121": c.shift(21) / c.shift(252) - 1,
        "lowvol": -sigma,
        "sigma": sigma,
        "liq": panel["turnover_cr"].rolling(126, min_periods=100).median(),
        "hist": c.notna().cumsum(),
        "ret6": ret6, "ret12": ret12,
    }


def eligible(sig: dict[str, pd.DataFrame], panel: dict[str, pd.DataFrame], s: int) -> pd.Index:
    """Point-in-time universe at signal row s (EQ-series stocks, no ETFs)."""
    close = panel["close"].iloc[s]
    ok = (panel["series"].iloc[s] == "EQ") & (close >= MIN_PRICE) & (sig["hist"].iloc[s] >= MIN_HISTORY)
    ok &= ~pd.Series([is_etf(c) for c in close.index], index=close.index)
    liq = sig["liq"].iloc[s][ok].dropna()
    return liq.sort_values(ascending=False).index[:UNIVERSE_SIZE]


def select(score: pd.Series, held: set[str], n: int, buffer: float = 1.5,
           sectors: dict[str, str] | None = None, sector_cap: float | None = None,
           blocked: set[str] | None = None) -> list[str]:
    """Top-n by score with a buffer (holdings stay while rank ≤ buffer·n) and an optional
    per-industry cap (max floor(cap·n) names per known industry; 'Unknown' uncapped).
    `blocked` names can be kept if already held but are never newly bought."""
    blocked = blocked or set()
    ranked = score.dropna().sort_values(ascending=False)
    rank = pd.Series(np.arange(1, len(ranked) + 1), index=ranked.index)
    limit = max(1, math.floor(sector_cap * n)) if sector_cap else None
    counts: dict[str, int] = {}

    def fits(sym: str) -> bool:
        if limit is None:
            return True
        sec = (sectors or {}).get(sym, "Unknown")
        return sec == "Unknown" or counts.get(sec, 0) < limit

    def take(sym: str, out: list[str]) -> None:
        out.append(sym)
        sec = (sectors or {}).get(sym, "Unknown")
        counts[sec] = counts.get(sec, 0) + 1

    out: list[str] = []
    for sym in sorted((s for s in held if s in rank.index and rank[s] <= buffer * n), key=lambda s: rank[s]):
        if len(out) < n and fits(sym):
            take(sym, out)
    for sym in ranked.index:
        if len(out) >= n:
            break
        if sym not in out and (sym in held or sym not in blocked) and fits(sym):
            take(sym, out)
    return out[:n]


def bulk_buy_blocklist(panel: dict[str, pd.DataFrame], s: int, days: int) -> set[str]:
    """Symbols with a non-institutional bulk-deal net buy in the `days` sessions ending at row s.
    Deals are published the evening of the deal date, so the signal close may include them."""
    events = panel.get("bulk_buy_events")
    if events is None:
        raise ValueError("avoid_bulk_buy_days is set but the panel has no 'bulk_buy_events' "
                         "(load them with shared.deal_filters.non_institutional_buy_events)")
    idx = panel["close"].index
    window = idx[max(0, s - days + 1): s + 1]
    return set(events.loc[events["date"].isin(window), "symbol"])


def regime_on(nifty: pd.Series, day: pd.Timestamp) -> bool:
    """Risk-on when NIFTY's close is above its 200-day average (as of `day`)."""
    ma = nifty.rolling(200).mean()
    nv, nm = nifty.asof(day), ma.asof(day)
    return bool(np.isfinite(nm) and nv > nm)


def vol_target_exposure(equity_curve: pd.Series, target: float) -> float:
    """min(1, target / 60-day realised volatility of the book); 1.0 until 60 days exist."""
    if len(equity_curve) <= 60:
        return 1.0
    rv = equity_curve.pct_change().iloc[-60:].std() * math.sqrt(252)
    return min(1.0, target / rv) if rv > 0 else 1.0


@dataclass
class TargetDecision:
    signal_date: pd.Timestamp
    risk_on: bool
    targets: list[str]
    exposure: float
    universe_size: int
    universe: list[str] | None = None
    blocked: list[str] | None = None         # universe names barred from new entries this month


def compute_targets(cfg: StrategyConfig, panel: dict[str, pd.DataFrame], sig: dict[str, pd.DataFrame],
                    nifty: pd.Series, s: int, held: set[str], equity_curve: pd.Series | None = None
                    ) -> TargetDecision:
    """The monthly decision at signal row s (the last close before the rebalance)."""
    sday = panel["close"].index[s]
    risk_on = regime_on(nifty, sday) if cfg.overlay.startswith("nifty200") else True
    targets: list[str] = []
    uni = eligible(sig, panel, s)
    secs = industries() if cfg.sector_cap else None
    blocked = bulk_buy_blocklist(panel, s, cfg.avoid_bulk_buy_days) if cfg.avoid_bulk_buy_days else set()
    if risk_on:
        if cfg.signal == "blend":
            half = max(cfg.n // 2, 1)
            a = select(sig["mom_nse"].iloc[s][uni], held, half, cfg.buffer, secs, cfg.sector_cap, blocked)
            b = select(sig["lowvol"].iloc[s][uni].drop(a, errors="ignore"), held - set(a), half, cfg.buffer,
                       secs, cfg.sector_cap, blocked)
            targets = a + b
        else:
            targets = select(sig[cfg.signal].iloc[s][uni], held, cfg.n, cfg.buffer, secs, cfg.sector_cap, blocked)
    exposure = 1.0
    if cfg.overlay == "nifty200_vt" and equity_curve is not None:
        exposure = vol_target_exposure(equity_curve, cfg.vol_target)
    return TargetDecision(sday, risk_on, targets, exposure, len(uni), list(uni),
                          sorted(blocked & set(uni)) if blocked else None)
