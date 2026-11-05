"""Monthly-rebalance backtest engine with a daily-marked equity curve (PLAN.md + Amendments v2).

Mechanics
- Signals at a rebalance session's close; ALL trades at the NEXT session's open.
- Holdings are share counts; the book is marked daily at last-known closes. A name with no
  trade for > `stale_zero_sessions` is written to ZERO in the mark (amendment 10); one with no
  trade for > `stale_exit_sessions` at a rebalance is force-sold at its last traded close with
  DOUBLE slippage.
- Cash earns `cash_rate`/yr per session; while a hedge is on, the margin portion
  (`margin_frac` × hedge notional) earns 0.
- Costs per traded delivery leg: vendored ICICI round trip at the leg's value / 2 + `slippage`
  per side. Futures hedge: `hedge_cost` per side on notional traded + a 2-side monthly roll.
- Hedge (amendment 3): while risk-off, short NIFTY futures rounded to WHOLE lots
  (`nifty_lot` × index level) nearest to the equity book's value; residual exposure reported.
- Sleeve (amendment 3): `sleeve_frac` of equity is permanently cash (hedged variants 0.15).

The engine knows nothing about any strategy: it takes `targets(s) -> (list[str], risk_on)`.
"""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402
from lib.trading_costs import default_model  # noqa: E402


@dataclass
class EngineConfig:
    capital: float = 1_000_000.0
    n_positions: int = 20
    cash_rate: float = 0.06
    slippage: float = 0.0005          # per side, delivery
    sleeve_frac: float = 0.0          # permanent cash sleeve share (hedged variants: 0.15)
    hedge: bool = False
    hedge_cost: float = 0.0003        # per side, futures all-in
    nifty_lot: int = 75
    margin_frac: float = 0.13         # of hedge notional, earns 0 while on
    max_weight: float = 0.15
    stale_exit_sessions: int = 10
    stale_zero_sessions: int = 60

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Result:
    equity: pd.Series
    bench: pd.Series                  # NIFTY 50 price, rebased
    rebalances: pd.DataFrame
    costs_paid: float
    config: EngineConfig
    notes: list[str] = field(default_factory=list)


def _side_cost_pct(model, value: float, slippage: float) -> float:
    return model.round_trip_pct(max(value, 1.0)) / 200.0 + slippage


def staleness(close: pd.DataFrame) -> np.ndarray:
    """Sessions since each (row, col) last had a real close print (0 on a trading day)."""
    real = close.notna().to_numpy()
    n = len(close)
    out = np.zeros(close.shape, np.int32)
    run = np.full(close.shape[1], 10_000, np.int32)
    for t in range(n):
        run = np.where(real[t], 0, run + 1)
        out[t] = run
    return out


def run(panel: dict, nifty: pd.Series, signal_rows: list[int],
        targets: Callable[[int], tuple[list[str], bool]], cfg: EngineConfig) -> Result:
    close, open_ = panel["close"], panel["open"]
    sessions = close.index
    stale = staleness(close)
    Cff = close.ffill().to_numpy()
    M = np.where(stale > cfg.stale_zero_sessions, 0.0, Cff)       # daily mark (amendment 10)
    O = open_.to_numpy()
    cols = {s: j for j, s in enumerate(close.columns)}
    nif = nifty.reindex(sessions).ffill().to_numpy(float)
    model = default_model()
    daily_cash = (1 + cfg.cash_rate) ** (1 / 252) - 1

    cash = cfg.capital
    shares: dict[str, float] = {}
    hedge_notional = 0.0
    equity_path = np.full(len(sessions), np.nan)
    reb_rows: list[dict] = []
    total_costs = 0.0
    notes: list[str] = []
    forced_exits = 0
    prev_risk_on: bool | None = None
    whipsaws = 0

    first = signal_rows[0]
    equity_path[:first + 1] = cfg.capital
    for k, s in enumerate(signal_rows):
        exec_row = s + 1
        if exec_row >= len(sessions):
            break
        names, risk_on = targets(s)
        if prev_risk_on is not None and risk_on != prev_risk_on:
            whipsaws += 1
        prev_risk_on = risk_on
        names = list(names)[:cfg.n_positions]

        def px(sym: str, row: int) -> float:
            j = cols[sym]
            p = O[row, j]
            return p if np.isfinite(p) and p > 0 else Cff[row - 1, j]

        # forced exits of stale holdings first (amendment 10)
        for sym in list(shares):
            j = cols[sym]
            if stale[exec_row, j] > cfg.stale_exit_sessions:
                val = shares.pop(sym) * Cff[exec_row, j]
                c_ = val * (_side_cost_pct(model, val, cfg.slippage) + cfg.slippage)   # double slippage
                cash += val - c_
                total_costs += c_
                forced_exits += 1

        held_value = sum(sh * px(sym, exec_row) for sym, sh in shares.items())
        equity_now = cash + held_value
        target_names = names if (risk_on or cfg.hedge) else []
        invest = (1 - cfg.sleeve_frac)
        w = min(invest / max(len(target_names), 1), cfg.max_weight) if target_names else 0.0
        target_value = {sym: equity_now * w for sym in target_names}

        traded, costs = 0.0, 0.0
        for sym in list(shares):                                   # sells
            tv = target_value.get(sym, 0.0)
            p = px(sym, exec_row)
            cur = shares[sym] * p
            if tv < cur - 1e-9:
                sell_val = cur - tv
                shares[sym] -= sell_val / p
                c_ = sell_val * _side_cost_pct(model, sell_val, cfg.slippage)
                cash += sell_val - c_
                costs += c_
                traded += sell_val
                if shares[sym] * p < 1.0:
                    shares.pop(sym)
        for sym, tv in target_value.items():                       # buys
            p = px(sym, exec_row)
            if not (np.isfinite(p) and p > 0) or stale[exec_row, cols[sym]] > cfg.stale_exit_sessions:
                continue                                           # never buy a name that isn't trading
            cur = shares.get(sym, 0.0) * p
            if tv > cur + 1e-9:
                want = tv - cur
                rate = _side_cost_pct(model, want, cfg.slippage)
                take = min(want * (1 + rate), max(cash, 0.0))
                if take <= 0:
                    continue
                buy_val = take / (1 + rate)
                shares[sym] = shares.get(sym, 0.0) + buy_val / p
                cash -= take
                costs += take - buy_val
                traded += buy_val

        # hedge: whole NIFTY lots nearest to the equity book value (amendment 3)
        new_hedge = 0.0
        lots = 0
        if cfg.hedge and not risk_on and np.isfinite(nif[exec_row]):
            book_val = sum(sh * px(sym, exec_row) for sym, sh in shares.items())
            lot_notional = cfg.nifty_lot * nif[exec_row]
            lots = int(round(book_val / lot_notional))
            new_hedge = lots * lot_notional
        hedge_trade_cost = cfg.hedge_cost * abs(new_hedge - hedge_notional)
        if hedge_notional > 0 and new_hedge > 0:
            hedge_trade_cost += 2 * cfg.hedge_cost * min(hedge_notional, new_hedge)    # monthly roll
        cash -= hedge_trade_cost
        costs += hedge_trade_cost
        hedge_notional = new_hedge
        total_costs += costs

        book_val = sum(sh * px(sym, exec_row) for sym, sh in shares.items())
        reb_rows.append({"date": sessions[s], "exec": sessions[exec_row], "n": len(target_names),
                         "risk_on": risk_on, "traded": traded, "costs": costs, "equity": equity_now,
                         "hedge": hedge_notional, "hedge_lots": lots,
                         "residual_exposure": book_val - hedge_notional if hedge_notional else np.nan})

        nxt = min(signal_rows[k + 1] + 1 if k + 1 < len(signal_rows) else len(sessions) - 1, len(sessions) - 1)
        idx = np.array([cols[sym] for sym in shares], dtype=int)
        qty = np.array([shares[sym] for sym in shares], dtype=float)
        margin = cfg.margin_frac * hedge_notional
        for t in range(exec_row, nxt + 1):
            cash += (cash - min(margin, max(cash, 0.0))) * daily_cash     # margin earns 0
            if hedge_notional > 0 and t > exec_row and np.isfinite(nif[t]) and np.isfinite(nif[t - 1]):
                cash -= hedge_notional * (nif[t] / nif[t - 1] - 1)
            book = float((M[t, idx] * qty).sum()) if len(idx) else 0.0
            equity_path[t] = cash + book

    eq = pd.Series(equity_path, index=sessions).dropna()
    bench = pd.Series(nif, index=sessions).reindex(eq.index)
    bench = bench / bench.iloc[0] * cfg.capital
    notes.append(f"forced stale exits: {forced_exits}; regime whipsaws: {whipsaws}")
    return Result(eq, bench, pd.DataFrame(reb_rows), total_costs, cfg, notes)


def ew_benchmark(panel: dict, signal_rows: list[int], members_fn: Callable[[int], pd.Index]) -> pd.Series:
    """Equal-weight benchmark: the point-in-time universe, reconstituted at each signal date,
    daily EW mean of member close-to-close returns, no costs (amendment 1, gate 1b)."""
    close = panel["close"]
    ret = close.pct_change(fill_method=None)
    sessions = close.index
    out = np.full(len(sessions), np.nan)
    level = 1.0
    for k, s in enumerate(signal_rows):
        exec_row = s + 1
        nxt = min(signal_rows[k + 1] + 1 if k + 1 < len(signal_rows) else len(sessions) - 1, len(sessions) - 1)
        if exec_row >= len(sessions):
            break
        cols = close.columns.get_indexer(members_fn(s))
        cols = cols[cols >= 0]
        r = ret.iloc[exec_row:nxt + 1, cols]
        out[exec_row - 1] = level if np.isnan(out[exec_row - 1]) else out[exec_row - 1]
        for off, (_, row) in enumerate(r.iterrows()):
            level *= 1 + np.nanmean(row.to_numpy()) if np.isfinite(np.nanmean(row.to_numpy())) else 1.0
            out[exec_row + off] = level
    return pd.Series(out, index=sessions).dropna()


# ── metrics and gates (Amendments v2) ───────────────────────────────────────────

def stats(eq: pd.Series) -> dict:
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    dd = (eq / eq.cummax() - 1).min()
    return {"cagr": cagr * 100, "max_dd": dd * 100, "years": yrs,
            "final": float(eq.iloc[-1]), "start": str(eq.index[0].date()), "end": str(eq.index[-1].date())}


def monthly_excess_ir(eq: pd.Series, bench: pd.Series) -> float:
    m = eq.resample("ME").last().pct_change().dropna()
    b = bench.resample("ME").last().pct_change().reindex(m.index)
    ex = (m - b).dropna()
    return float(ex.mean() / ex.std(ddof=1) * math.sqrt(12)) if len(ex) > 3 and ex.std() > 0 else float("nan")


def yearly_table(eq: pd.Series, *benches: pd.Series, names: tuple[str, ...] = ("nifty", "ew")) -> pd.DataFrame:
    def yearly(s):
        s = s.dropna()
        y = s.resample("YE").last()
        prev = y.shift(1)
        prev.iloc[0] = s.iloc[0]
        return ((y / prev - 1) * 100).round(1)
    d = {"strategy": yearly(eq)}
    for nm, b in zip(names, benches):
        d[nm] = yearly(b.reindex(eq.index).dropna())
    out = pd.DataFrame(d)
    out.index = [i.year for i in out.index]
    return out


def rebase(s: pd.Series, like: pd.Series, capital: float) -> pd.Series:
    s = s.reindex(like.index).ffill().dropna()
    return s / s.iloc[0] * capital


def gate_a(eq: pd.Series, nifty_b: pd.Series, ew_b: pd.Series, decisions: int, min_decisions: int = 30) -> dict:
    s, b, e = stats(eq), stats(nifty_b), stats(ew_b)
    ir = monthly_excess_ir(eq, nifty_b)
    checks = {
        f"1a CAGR {s['cagr']:.2f}% > NIFTY {b['cagr']:.2f}% (price-to-price)": s["cagr"] > b["cagr"],
        f"1b CAGR {s['cagr']:.2f}% > EW universe {e['cagr']:.2f}%": s["cagr"] > e["cagr"],
        f"2  maxDD {s['max_dd']:.1f}% ≥ −30% and ≥ 1.25×NIFTY ({1.25*b['max_dd']:.1f}%)":
            s["max_dd"] >= -30 and s["max_dd"] >= 1.25 * b["max_dd"],
        f"3  IR {ir:.2f} ≥ 0.45": ir >= 0.45,
        f"4  decisions {decisions} ≥ {min_decisions}": decisions >= min_decisions,
    }
    return {"pass": all(checks.values()), "checks": checks, "stats": s, "nifty": b, "ew": e, "ir": ir}


def gate_b(eq: pd.Series, nifty_b: pd.Series, ew_b: pd.Series) -> dict:
    s, b, e = stats(eq), stats(nifty_b), stats(ew_b)
    yt = yearly_table(eq, nifty_b, ew_b)
    pos = int((yt["strategy"] > yt["nifty"]).sum())
    checks = {
        f"1a CAGR {s['cagr']:.2f}% > NIFTY {b['cagr']:.2f}%": s["cagr"] > b["cagr"],
        f"1b CAGR {s['cagr']:.2f}% > EW universe {e['cagr']:.2f}%": s["cagr"] > e["cagr"],
        f"2  maxDD {s['max_dd']:.1f}% ≥ −35%": s["max_dd"] >= -35,
        f"3  excess years vs NIFTY {pos}/{len(yt)} ≥ 5": pos >= 5,
    }
    return {"pass": all(checks.values()), "checks": checks, "stats": s, "nifty": b, "ew": e,
            "ir": monthly_excess_ir(eq, nifty_b), "yearly": yt}


def render_gate(name: str, g: dict) -> str:
    lines = [f"### {name}: **{'PASS' if g['pass'] else 'FAIL'}**"]
    lines += [f"- {'✅' if ok else '❌'} {c}" for c, ok in g["checks"].items()]
    return "\n".join(lines)
