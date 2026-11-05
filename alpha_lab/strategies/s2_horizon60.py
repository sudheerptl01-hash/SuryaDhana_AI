#!/usr/bin/env python
"""S2 — Horizon-60 probability book (PLAN.md §S2 + Amendments v2).

Deterministic flow: every 12th trading Friday (counted from the first trading Friday of the
anchor year — 2016 for Gate A, 2011 for the Gate-B/full run), a walk-forward logistic model
(L2, C=0.1, January refits; training = earlier grid dates whose 60-session labels completed
≥ 61 sessions before the test year) scores universe T (raw ₹20 floor) on robust flags +
momentum percentile. Book = top 20 by P(top fifth of 60-session next-open excess), AVOID
(P(bottom fifth) above the refit's TRAINING 80th percentile) blocked from new entries,
1.5× buffer, equal weight, crash filter at signal dates. Execution/costs/staleness/hedging:
backtest.engine.

Pre-refit grid dates hold cash (burn-in; the honest start of a model that needs 2 years of
labels). VA-break feature skipped (cost of computing profiles; noted). No coverage columns
are fed to the model (the evidence_probability leak rule).

    PYTHONPATH=alpha_lab python alpha_lab/strategies/s2_horizon60.py          # full protocol run

Research only; writes alpha_lab/reports/s2_*.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402
from backtest import engine  # noqa: E402
from backtest.data_access import load  # noqa: E402
from lib import xs_labels as xl  # noqa: E402
from lib.momentum import select  # noqa: E402
from lib.momentum import signals as desk_signals  # noqa: E402
from strategies import flags as fl  # noqa: E402

N, BUFFER = 20, 1.5
C_REG, MAX_ITER = 0.1, 500
H = 60
TOP_Q, BOT_Q, AVOID_TRAIN_PCT = 0.8, 0.2, 80
END = pd.Timestamp("2026-10-13")
WINDOWS = {"smoke": ("2025-10-01", "2026-10-13"), "gateA": ("2020-01-01", "2026-10-13"),
           "gateB": ("2011-01-01", "2019-12-31"), "full": ("2011-01-01", "2026-10-13")}
FEATURES = ["mom_pct", "below_200dma", "near_52w_low", "near_52w_high", "vol60_decile",
            "split_20d", "bad_results_60d", "good_results_60d", "burst_5d"]


def grid_rows(sessions: pd.DatetimeIndex, anchor_year: int) -> list[int]:
    """Every 12th trading Friday counted from the first trading Friday of `anchor_year`."""
    fridays = [i for i, d in enumerate(sessions)
               if d.weekday() == 4 and d >= pd.Timestamp(anchor_year, 1, 1)]
    return [i for i in fridays[::12] if i + 1 < len(sessions) and sessions[i] <= END]


def build_frames(data: dict, rows: list[int]) -> dict:
    """Members per grid row (computed on the FULL panel), then a column-sliced panel and all
    daily feature/label frames on the member union."""
    panel = data["panel"]
    sig_full = desk_signals(panel)
    members = {s: fl.lab_eligible(sig_full, panel, s) for s in rows}
    union = pd.Index(sorted(set().union(*[set(m) for m in members.values()])))
    P = {k: panel[k][union] for k in ("close", "open", "raw_close", "series", "volume", "turnover_cr")}
    ca = panel["corporate_actions"]
    P["corporate_actions"] = ca[ca["symbol"].isin(set(union))].copy()
    c, v = P["close"], P["volume"]
    sig = desk_signals(P)
    veto = fl.s1_veto_frames(P, data["releases"])
    r1 = c.pct_change(fill_method=None)
    burst = ((r1 >= 0.04) & (v > v.shift(1))).astype(float)
    fwd = xl.forward_open_returns(P["open"], H).where(xl.clean_windows(c, H + 1))
    frames = {
        "mom": sig["mom_nse"],
        "below_200dma": veto["below_200dma"],
        "near_52w_low": veto["near_52w_low"],
        "near_52w_high": fl.near_52w_high(c).fillna(False),
        "vol60": veto["vol60"],
        "split_20d": veto["split_20d"],
        "bad_results_60d": veto["bad_results_60d"],
        "good_results_60d": veto["good_results_60d"],
        "burst_5d": fl.recent(burst, 5) > 0,
        "fwd60": fwd,
    }
    return {"panel": P, "members": members, "frames": frames, "sessions": c.index}


def row_table(frames: dict, day: pd.Timestamp, mem: pd.Index) -> pd.DataFrame:
    """Feature matrix + labels for one grid date, members only."""
    X = pd.DataFrame(index=mem)
    mom = frames["mom"].loc[day, mem]
    X["mom_pct"] = mom.rank(pct=True)
    X["below_200dma"] = frames["below_200dma"].loc[day, mem].astype(bool)
    X["near_52w_low"] = frames["near_52w_low"].loc[day, mem].astype(bool)
    X["near_52w_high"] = frames["near_52w_high"].loc[day, mem].astype(bool)
    v = frames["vol60"].loc[day, mem]
    X["vol60_decile"] = v.rank(pct=True) >= 0.9
    for k in ("split_20d", "bad_results_60d", "good_results_60d", "burst_5d"):
        X[k] = frames[k].loc[day, mem].astype(bool)
    f = frames["fwd60"].loc[day, mem]
    ex = f - f.mean()
    rk = ex.rank(pct=True)
    X["y_top"], X["y_bot"] = (rk >= TOP_Q).where(ex.notna()), (rk <= BOT_Q).where(ex.notna())
    return X


def walk_forward(built: dict, rows: list[int], anchor_year: int, log) -> dict:
    """Per grid row: P(top) series, AVOID set. January refits; two L2 logistics per refit."""
    from sklearn.linear_model import LogisticRegression
    sessions, frames, members = built["sessions"], built["frames"], built["members"]
    tables = {s: row_table(frames, sessions[s], members[s]) for s in rows}
    avail = {}
    for name, key in [("below_200dma", "below_200dma"), ("near_52w_low", "near_52w_low"),
                      ("near_52w_high", "near_52w_high"), ("vol60_decile", "vol60"),
                      ("split_20d", "split_20d"), ("bad_results_60d", "bad_results_60d"),
                      ("good_results_60d", "good_results_60d"), ("burst_5d", "burst_5d"), ("mom_pct", "mom")]:
        fr = frames[key]
        first = fr.replace(False, np.nan).first_valid_index() if fr.dtypes.iloc[0] == bool else fr.first_valid_index()
        avail[name] = first or sessions[0]
    out: dict[int, dict] = {}
    for year in range(anchor_year + 2, END.year + 1):
        y_start = pd.Timestamp(year, 1, 1)
        start_pos = sessions.searchsorted(y_start)
        train_rows = [s for s in rows if s + H + 1 < start_pos]
        test_rows = [s for s in rows if sessions[s].year == year]
        if not test_rows:
            continue
        feats = [f for f in FEATURES if avail[f] <= y_start - pd.DateOffset(years=2)]
        tr = pd.concat([tables[s] for s in train_rows]) if train_rows else pd.DataFrame(columns=FEATURES + ["y_top", "y_bot"])
        tr = tr.dropna(subset=["y_top", "mom_pct"])
        if len(tr) < 600:
            log(f"  {year}: only {len(tr)} training rows — grid dates stay in cash")
            continue
        Xtr = tr[feats].astype(float).to_numpy()
        m_top = LogisticRegression(C=C_REG, max_iter=MAX_ITER).fit(Xtr, tr["y_top"].astype(float))
        m_bot = LogisticRegression(C=C_REG, max_iter=MAX_ITER).fit(Xtr, tr["y_bot"].astype(float))
        thr = float(np.percentile(m_bot.predict_proba(Xtr)[:, 1], AVOID_TRAIN_PCT))
        for s in test_rows:
            t = tables[s].dropna(subset=["mom_pct"])
            Xte = t[feats].astype(float).to_numpy()
            p_top = pd.Series(m_top.predict_proba(Xte)[:, 1], index=t.index)
            p_bot = pd.Series(m_bot.predict_proba(Xte)[:, 1], index=t.index)
            out[s] = {"p_top": p_top, "avoid": set(p_bot.index[p_bot > thr])}
        log(f"  refit {year}: {len(tr):,} rows, {len(feats)} features, thrB {thr:.3f}, {len(test_rows)} grid dates")
    return out


def run_variant(data: dict, anchor_year: int, hedged: bool, log) -> dict:
    panel_full = data["panel"]
    sessions = panel_full["close"].index
    rows = grid_rows(sessions, anchor_year)
    built = build_frames(data, rows)
    P = built["panel"]
    preds = walk_forward(built, rows, anchor_year, log)
    nifty = data["nifty"].reindex(sessions).ffill()
    nifty_ma = nifty.rolling(200, min_periods=180).mean()
    held: set[str] = set()

    def targets(s: int) -> tuple[list[str], bool]:
        nonlocal held
        risk_on = bool(np.isfinite(nifty_ma.iloc[s]) and nifty.iloc[s] > nifty_ma.iloc[s])
        pr = preds.get(s)
        if pr is None:
            held = set()
            return [], risk_on
        picks = select(pr["p_top"], held, N, buffer=BUFFER, blocked=pr["avoid"])
        held = set(picks)
        return picks, risk_on

    cfg = engine.EngineConfig(capital=5_000_000 if hedged else 1_000_000, hedge=hedged,
                              sleeve_frac=0.15 if hedged else 0.0)
    res = engine.run(P, data["nifty"], rows, targets, cfg)
    ew = engine.ew_benchmark(P, rows, lambda s_: built["members"][s_])
    return {"res": res, "ew": ew, "rows": rows, "cfg": cfg, "preds": preds}


def window_gate(v: dict, win: str, min_decisions: int = 25) -> dict:
    a, b = WINDOWS[win]
    eq = v["res"].equity[a:b]
    eq = eq / eq.iloc[0] * v["cfg"].capital
    nif = engine.rebase(v["res"].bench, eq, v["cfg"].capital)
    ewb = engine.rebase(v["ew"], eq, v["cfg"].capital)
    reb = v["res"].rebalances
    decided = reb[(reb["date"] >= pd.Timestamp(a)) & (reb["date"] <= pd.Timestamp(b))]
    n_dec = int(len(decided))
    g = engine.gate_a(eq, nif, ewb, n_dec, min_decisions) if win in ("smoke", "gateA") \
        else engine.gate_b(eq, nif, ewb)
    return {"gate": g, "eq": eq, "nifty": nif, "ew": ewb, "decisions": n_dec,
            "traded": float(decided["traded"].sum()), "costs": float(decided["costs"].sum()),
            "risk_off_rebs": int((~decided["risk_on"]).sum())}


def main() -> None:
    t0 = time.time()
    log = lambda m: print(f"[{time.time()-t0:5.0f}s] {m}", flush=True)  # noqa: E731
    out = LAB / "reports"
    data = load()
    snapshot = str(data["panel"]["close"].index.max().date())
    log(f"panel {data['panel']['close'].shape} to {snapshot}")

    report: list[str] = [f"# S2 — Horizon-60 probability book (run {pd.Timestamp.now():%Y-%m-%d %H:%M}, "
                         f"panel snapshot {snapshot})", ""]
    family: list[str] = []

    for hedged in (False, True):
        tag = "S2H" if hedged else "S2"
        log(f"=== {tag}: anchor 2016 (smoke + Gate A) ===")
        v = run_variant(data, 2016, hedged, log)
        report += [f"## {tag} (plain ₹10L)" if not hedged else "## S2H (hedged ₹50L, 85/15, whole-lot NIFTY short)",
                   f"config: `{json.dumps(v['cfg'].as_dict())}`",
                   f"grid: every 12th trading Friday from first trading Friday of 2016 → {len(v['rows'])} dates; "
                   f"{v['res'].notes[0]}", ""]
        smoke = window_gate(v, "smoke")
        s_eq = smoke["eq"]
        report += [f"### Smoke 2025-10-01→2026-10-13 (mechanics only): {len(s_eq)} sessions, "
                   f"{smoke['decisions']} rebalances, costs ₹{smoke['costs']:,.0f}, "
                   f"equity NaN-free: {not s_eq.isna().any()}", ""]
        ga = window_gate(v, "gateA")
        report += [engine.render_gate(f"{tag} Gate A (2020-01-01→2026-10-13)", ga["gate"]),
                   f"- decisions {ga['decisions']} · traded ₹{ga['traded']:,.0f} · costs ₹{ga['costs']:,.0f} "
                   f"· risk-off rebalances {ga['risk_off_rebs']} · IR {ga['gate']['ir']:.2f}",
                   "", "```", engine.yearly_table(ga["eq"], ga["nifty"], ga["ew"]).to_string(), "```", ""]
        ga["eq"].to_csv(out / f"s2{'_hedged' if hedged else ''}_gateA_equity.csv")
        a_pass = ga["gate"]["pass"]
        family.append(f"| {tag} | Gate A | {'PASS' if a_pass else 'FAIL'} | "
                      f"{ga['gate']['stats']['cagr']:.2f}% | {ga['gate']['nifty']['cagr']:.2f}% | "
                      f"{ga['gate']['ew']['cagr']:.2f}% | {ga['gate']['stats']['max_dd']:.1f}% | {ga['gate']['ir']:.2f} |")
        if not a_pass:
            report += [f"**Verdict: Gate A FAIL — Gate B not run (per protocol).**", ""]
            continue
        log(f"=== {tag}: anchor 2011 (Gate B + full) ===")
        vb = run_variant(data, 2011, hedged, log)
        report += ["### Gate B uses a 2011-anchored grid (same 12-week rule); the model first trades in 2013 "
                   "(2 years of labels needed) — 2011–12 sit in cash, which the gate window includes honestly.", ""]
        gb = window_gate(vb, "gateB")
        report += [engine.render_gate(f"{tag} Gate B (2011-01-01→2019-12-31)", gb["gate"]),
                   "", "```", gb["gate"]["yearly"].to_string(), "```", ""]
        gb["eq"].to_csv(out / f"s2{'_hedged' if hedged else ''}_gateB_equity.csv")
        full = window_gate(vb, "full")
        fs = engine.stats(full["eq"])
        report += [f"### Full 2011→2026 (2011 anchor): CAGR {fs['cagr']:.2f}% vs NIFTY "
                   f"{engine.stats(full['nifty'])['cagr']:.2f}% / EW {engine.stats(full['ew'])['cagr']:.2f}%, "
                   f"maxDD {fs['max_dd']:.1f}%", ""]
        family.append(f"| {tag} | Gate B | {'PASS' if gb['gate']['pass'] else 'FAIL'} | "
                      f"{gb['gate']['stats']['cagr']:.2f}% | {gb['gate']['nifty']['cagr']:.2f}% | "
                      f"{gb['gate']['ew']['cagr']:.2f}% | {gb['gate']['stats']['max_dd']:.1f}% | {gb['gate']['ir']:.2f} |")

    report += ["## Family table (S2 runs)", "", "| Run | Window | Verdict | CAGR | NIFTY | EW-T | maxDD | IR |",
               "|---|---|---|---|---|---|---|---|", *family, "",
               "Notes: VA-break feature skipped (profile cost); results flags exist only where NSE covers the "
               "symbol (uncovered names are simply never flagged — stated asymmetry, no coverage column fed to "
               "the model); labels masked on >50% one-day data breaks (vendored convention).", ""]
    (out / "s2_RESULTS.md").write_text("\n".join(report))
    log("report written → alpha_lab/reports/s2_RESULTS.md")


if __name__ == "__main__":
    main()
