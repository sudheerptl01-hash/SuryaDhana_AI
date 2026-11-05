#!/usr/bin/env python
"""S3 — Leader-dip (PLAN.md §S3 + Amendments v2): daily scan, 5-session hold.

Setup at close t (all point-in-time): in universe L (EQ, RAW close ≥ ₹20, 20-session median
turnover ≥ ₹5 cr, ≥ 250 sessions, no ETFs) · momentum percentile ≥ 0.70 within that day's L ·
close > 200-DMA · RSI(2) < 5 · not circuit-pinned (|1-day move| ≥ 9.5% closing at the day's
high/low). Enter the NEXT open, slot = 20% of equity (delivery) or exactly 1 futures lot
(futures variant), max 5 concurrent, exit at the open of t+6; one entry per stock per 10
sessions; oversubscription → highest momentum percentile first.

Variants (Amendments v2 §2):
  delivery  ₹10L, ICICI MoneySaver round trip at slot value + 0.05%/side slippage, cash 0%.
  futures   ₹1Cr, F&O names only (membership known at t), 1 lot = ₹5L notional before
            2024-11-20 else ₹15L (dated proxy), max 5 lots, 0.03%/side, Gate A only
            (fut data era); spot opens proxy futures fills (flagged).

    PYTHONPATH=alpha_lab python alpha_lab/strategies/s3_leader_dip.py [--all]

Research only; writes alpha_lab/reports/s3_*.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402
from backtest import engine  # noqa: E402
from backtest.data_access import load  # noqa: E402
from lib.momentum import is_etf  # noqa: E402
from lib.momentum import signals as desk_signals  # noqa: E402
from lib.trading_costs import default_model  # noqa: E402
from strategies import flags as fl  # noqa: E402

warnings.filterwarnings("ignore", category=RuntimeWarning)

SMOKE = ("2025-10-01", "2026-10-13")
GATE_A = ("2020-01-01", "2026-10-13")
GATE_B = ("2011-01-01", "2019-12-31")
MOM_PCT, MAX_SLOTS, HOLD, COOLDOWN = 0.70, 5, 5, 10
CIRCUIT = 0.095
LOT_SWITCH = pd.Timestamp("2024-11-20")
LOT_BEFORE, LOT_AFTER = 500_000.0, 1_500_000.0


def build_signals(panel: dict) -> dict:
    """All full-panel frames, computed once (everything uses data to the close of its own row)."""
    c, o, h, lo = panel["close"], panel["open"], panel["high"], panel["low"]
    raw, series, to = panel["raw_close"], panel["series"], panel["turnover_cr"]
    etf = pd.Series([is_etf(s) for s in c.columns], index=c.columns)
    med20 = to.rolling(20, min_periods=10).median()
    hist = c.notna().cumsum()
    L = series.eq("EQ") & raw.ge(20.0) & med20.ge(5.0) & hist.ge(250) & ~etf
    mom = desk_signals(panel)["mom_nse"]
    pct = mom.where(L).rank(axis=1, pct=True)
    above200 = c > fl.sma(c, 200)
    dip = fl.rsi2(c) < 5
    ret1 = c / c.shift(1) - 1
    pinned = (ret1.abs() >= CIRCUIT) & ((c >= h * 0.9995) | (c <= lo * 1.0005))
    setup = L & (pct >= MOM_PCT) & above200 & dip & ~pinned & c.notna()
    return {"setup": setup, "pct": pct, "L": L}


def simulate(panel: dict, sig: dict, start: str, end: str, variant: str, capital: float,
             fo_first: pd.Series | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """Event loop: signals on row t-1 enter at open[t], exit at open[t-1+6]. Returns (equity, trades)."""
    c, o = panel["close"], panel["open"]
    sessions = c.index
    Cff = c.ffill().to_numpy()
    O, SET = o.to_numpy(), sig["setup"].to_numpy()
    PCT = sig["pct"].to_numpy()
    cols = c.columns
    col_of = {s: j for j, s in enumerate(cols)}
    model = default_model()
    t0 = sessions.searchsorted(pd.Timestamp(start))
    t1 = sessions.searchsorted(pd.Timestamp(end), side="right") - 1
    fo_ok = None
    if fo_first is not None:
        fo_ok = np.full(len(cols), np.iinfo(np.int64).max, dtype="int64")
        for s_, d in fo_first.items():
            j = col_of.get(s_)
            if j is not None:
                fo_ok[j] = sessions.searchsorted(d)

    def side_cost(value: float, forced: bool = False) -> float:
        if variant == "futures":
            return value * 0.0003
        return value * (model.round_trip_pct(max(value, 1.0)) / 200.0 + 0.0005 + (0.0005 if forced else 0.0))

    cash, positions = capital, []            # position: dict(sym j qty entry_px entry_row exit_row slot)
    last_entry: dict[int, int] = {}
    eq = np.full(len(sessions), np.nan)
    trades: list[dict] = []
    eq[t0 - 1 if t0 else 0] = capital
    for t in range(t0, t1 + 1):
        # 1) exits at today's open
        for p in [p for p in positions if p["exit_row"] <= t]:
            j = p["j"]
            px, forced = O[t, j], False
            if not (np.isfinite(px) and px > 0):
                px, forced = Cff[t, j], True
            value = p["qty"] * px
            cost = side_cost(value, forced=forced)
            if variant == "futures":
                cash += p["qty"] * (px - p["entry_px"]) - cost     # margin accounting: only P&L moves cash
                net = (p["qty"] * (px - p["entry_px"]) - cost - p["cost_in"]) / p["slot"]
            else:
                cash += value - cost
                net = (value - cost - p["cost_in"]) / p["slot"] - 1
            trades.append({"symbol": cols[p["j"]], "signal": str(sessions[p["entry_row"] - 1].date()),
                           "entry": str(sessions[p["entry_row"]].date()), "exit": str(sessions[t].date()),
                           "entry_px": p["entry_px"], "exit_px": px, "net_pct": net * 100, "forced": forced})
            positions.remove(p)
        # 2) entries from yesterday's signals
        if t - 1 >= 0 and len(positions) < MAX_SLOTS:
            js = np.flatnonzero(SET[t - 1])
            if fo_ok is not None:
                js = js[fo_ok[js] <= t - 1]
            js = [j for j in js if t - last_entry.get(j, -10**9) >= COOLDOWN
                  and j not in {p["j"] for p in positions}]
            js.sort(key=lambda j: -(PCT[t - 1, j] if np.isfinite(PCT[t - 1, j]) else 0))
            mark = cash + sum(p["qty"] * (O[t, p["j"]] if np.isfinite(O[t, p["j"]]) else Cff[t - 1, p["j"]])
                              for p in positions)
            for j in js[:MAX_SLOTS - len(positions)]:
                px = O[t, j]
                if not (np.isfinite(px) and px > 0):
                    continue
                if variant == "futures":
                    slot = LOT_BEFORE if sessions[t] < LOT_SWITCH else LOT_AFTER
                    qty = slot / px
                    cost = side_cost(slot)
                    if cash < slot * 0.25:                  # SPAN+exposure margin headroom
                        continue
                    cash -= cost                            # futures: only the fee leaves cash at entry
                    cost_in = cost
                else:
                    slot = 0.20 * mark
                    gross = min(slot, max(cash, 0.0))
                    if gross < 1000:
                        continue
                    rate = model.round_trip_pct(max(gross, 1.0)) / 200.0 + 0.0005
                    invested = gross / (1 + rate)
                    qty = invested / px
                    cash -= gross
                    cost_in, slot = gross - invested, invested
                positions.append({"j": j, "qty": qty, "entry_px": px, "entry_row": t,
                                  "exit_row": t + HOLD, "slot": slot, "cost_in": cost_in})
                last_entry[j] = t
        # 3) daily mark at the close
        if variant == "futures":
            book = sum(p["qty"] * (Cff[t, p["j"]] - p["entry_px"]) for p in positions)
        else:
            book = sum(p["qty"] * Cff[t, p["j"]] for p in positions)
        eq[t] = cash + book
    equity = pd.Series(eq, index=sessions).dropna()
    return equity, pd.DataFrame(trades)


def month_end_rows(sessions: pd.DatetimeIndex, start: str, end: str) -> list[int]:
    ends = sessions.to_series().groupby(sessions.to_period("M")).max()
    a, b = pd.Timestamp(start) - pd.DateOffset(days=40), pd.Timestamp(end)
    return [sessions.get_loc(d) for d in ends if a <= d <= b and sessions.get_loc(d) + 1 < len(sessions)]


def run_window(data, sig, start, end, variant, capital):
    panel = data["panel"]
    sessions = panel["close"].index
    fo_first = None
    if variant == "futures":
        fo = data["fo"]
        fo_first = fo[fo["kind"] == "stock"].groupby("symbol")["date"].min()
    eq, trades = simulate(panel, sig, start, end, variant, capital, fo_first)
    eq = eq[start:end]
    eq = eq / eq.iloc[0] * capital
    nif = engine.rebase(data["nifty"], eq, capital)
    rows = month_end_rows(sessions, start, end)
    Lb = sig["L"]
    ew = engine.ew_benchmark(panel, rows, lambda s: Lb.iloc[s][Lb.iloc[s]].index)
    ew = engine.rebase(ew, eq, capital)
    return eq, trades, nif, ew


def trade_stats(trades: pd.DataFrame, eq: pd.Series, capital: float) -> dict:
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    return {"entries": len(trades), "win_rate": float((trades["net_pct"] > 0).mean() * 100) if len(trades) else np.nan,
            "avg_net": float(trades["net_pct"].mean()) if len(trades) else np.nan,
            "median_net": float(trades["net_pct"].median()) if len(trades) else np.nan,
            "forced_exits": int(trades["forced"].sum()) if len(trades) else 0,
            "entries_per_year": len(trades) / yrs if yrs else np.nan}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-smoke", action="store_true")
    args = ap.parse_args()
    t0 = time.time()
    data = load()
    panel = data["panel"]
    print(f"[{time.time()-t0:5.0f}s] panel {panel['close'].shape}")
    sig = build_signals(panel)
    n_setup = int(sig["setup"].to_numpy().sum())
    print(f"[{time.time()-t0:5.0f}s] signals built; setup days total {n_setup:,}")
    out = LAB / "reports"
    blocks: list[str] = []
    results: dict[str, dict] = {}

    if not args.skip_smoke:
        eq, tr, nif, ew = run_window(data, sig, *SMOKE, "delivery", 1_000_000)
        st = trade_stats(tr, eq, 1_000_000)
        blocks += [f"## Smoke (delivery) {SMOKE[0]} → {SMOKE[1]}",
                   f"- entries {st['entries']} · win {st['win_rate']:.0f}% · avg net {st['avg_net']:.2f}% · "
                   f"equity end ₹{eq.iloc[-1]:,.0f}",
                   "- example trades:", "```", tr.head(8).to_string(index=False), "```", ""]
        print(f"[{time.time()-t0:5.0f}s] smoke: {st['entries']} entries, win {st['win_rate']:.0f}%")

    # delivery Gate A
    eq, tr, nif, ew = run_window(data, sig, *GATE_A, "delivery", 1_000_000)
    tr.to_csv(out / "s3_trades_delivery_gateA.csv", index=False)
    eq.to_csv(out / "s3_equity_delivery_gateA.csv")
    st = trade_stats(tr, eq, 1_000_000)
    ga = engine.gate_a(eq, nif, ew, decisions=st["entries"])
    results["delivery Gate A"] = ga
    yt = engine.yearly_table(eq, nif, ew)
    blocks += [f"## Delivery ₹10L — Gate A {GATE_A[0]} → {GATE_A[1]}",
               f"- {json.dumps(st)}",
               engine.render_gate("Gate A (delivery)", ga), "",
               "```", yt.to_string(), "```", ""]
    print(f"[{time.time()-t0:5.0f}s] delivery Gate A: {'PASS' if ga['pass'] else 'FAIL'} "
          f"(CAGR {ga['stats']['cagr']:.1f}% vs NIFTY {ga['nifty']['cagr']:.1f}% / EW {ga['ew']['cagr']:.1f}%)")

    if ga["pass"]:
        eqb, trb, nifb, ewb = run_window(data, sig, *GATE_B, "delivery", 1_000_000)
        trb.to_csv(out / "s3_trades_delivery_gateB.csv", index=False)
        gb = engine.gate_b(eqb, nifb, ewb)
        results["delivery Gate B"] = gb
        blocks += [f"## Delivery — Gate B {GATE_B[0]} → {GATE_B[1]}",
                   engine.render_gate("Gate B (delivery)", gb), "",
                   "```", gb["yearly"].to_string(), "```", ""]
    else:
        blocks += ["## Delivery — Gate B: **not run** (Gate A failed, per protocol)", ""]

    # futures Gate A (separate family member; Gate B = N/A, fut data era)
    eqf, trf, niff, ewf = run_window(data, sig, *GATE_A, "futures", 10_000_000)
    trf.to_csv(out / "s3_trades_futures_gateA.csv", index=False)
    eqf.to_csv(out / "s3_equity_futures_gateA.csv")
    stf = trade_stats(trf, eqf, 10_000_000)
    gaf = engine.gate_a(eqf, niff, ewf, decisions=stf["entries"])
    results["futures Gate A"] = gaf
    blocks += [f"## Futures ₹1Cr (1 lot/name, dated lot proxy; spot opens proxy fills) — Gate A",
               f"- {json.dumps(stf)}",
               engine.render_gate("Gate A (futures)", gaf),
               "- Gate B: **N/A** — fut_close data begins 2019-10 (Amendments v2 §2).", "",
               "```", engine.yearly_table(eqf, niff, ewf).to_string(), "```", ""]
    print(f"[{time.time()-t0:5.0f}s] futures Gate A: {'PASS' if gaf['pass'] else 'FAIL'}")

    verdicts = {k: ("PASS" if v["pass"] else "FAIL") for k, v in results.items()}
    cfg = {"mom_pct": MOM_PCT, "slots": MAX_SLOTS, "hold": HOLD, "cooldown": COOLDOWN, "circuit": CIRCUIT,
           "lot_proxy": {"before_2024-11-20": LOT_BEFORE, "after": LOT_AFTER},
           "windows": {"smoke": SMOKE, "gateA": GATE_A, "gateB": GATE_B}}
    head = [f"# S3 Leader-dip — results ({pd.Timestamp.now():%Y-%m-%d %H:%M}, panel snapshot same day)",
            f"- Pre-registered expectation (PLAN §S3): delivery likely fails on costs; futures is the live candidate; "
            f"both failing = a 'stay away' verdict, which is a wanted outcome.",
            f"- Verdicts: `{json.dumps(verdicts)}`",
            f"- config: `{json.dumps(cfg)}`", ""]
    (out / "s3_RESULTS.md").write_text("\n".join(head + blocks))
    print(f"[{time.time()-t0:5.0f}s] wrote reports/s3_RESULTS.md")


if __name__ == "__main__":
    main()
