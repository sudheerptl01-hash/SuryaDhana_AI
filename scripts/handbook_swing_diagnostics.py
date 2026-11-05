#!/usr/bin/env python
"""
Post-mortem of the handbook swing backtest (scripts/handbook_swing_backtest.py).

Reads the trade logs of the as-written run (ICICI costs, GTT entries) and the gross run (no costs) and answers:
  1. holding period — sessions held, by setup and outcome;
  2. activity — signals per day, entries per day/week/month, positions held, capital used;
  3. winners vs losers — exit reasons, how far each trade went for and against you (MFE / MAE, in R),
     losers that were in profit first, stops hit by an overnight gap;
  4. "what if I had held longer" — (a) every entry held a fixed 5/10/20/40/60 sessions with no stop,
     (b) what each trade did in the 5/10/20/40 sessions AFTER its actual exit;
  5. where the money went — gross edge vs costs, by regime at entry and by year.
All forward returns are from the actual fill price to later closes on the adjusted panel, and are also shown as
excess over the equal-weight tradable universe over the same window (so a rising market is not mistaken for skill).

    python scripts/handbook_swing_diagnostics.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import handbook_swing_backtest as hb  # noqa: E402
from shared.trading_costs import PROFILES, CostModel  # noqa: E402

OUT = ROOT / "reports" / "handbook_swing"
AS_WRITTEN = OUT / "trades_2020_icici_moneysaver_s0.0015_r0.005_gtt.csv"
GROSS = OUT / "trades_2020_none_s0.0_r0.005_gtt.csv"
HOLDS = (5, 10, 20, 40, 60)
AFTER = (5, 10, 20, 40)


def md(df: pd.DataFrame, index: bool = True) -> str:
    d = df.reset_index() if index else df
    lines = ["| " + " | ".join(map(str, d.columns)) + " |", "|" + "---|" * len(d.columns)]
    for r in d.itertuples(index=False):
        lines.append("| " + " | ".join("" if (isinstance(v, float) and np.isnan(v)) else
                                        (f"{v:,.2f}" if isinstance(v, float) else str(v)) for v in r) + " |")
    return "\n".join(lines)


def main() -> None:
    data = hb.load("2018-05-01")
    f = hb.build(data)
    reg = hb.regime(f, data)
    sig = hb.setups(f)
    idx, cols = f["idx"], list(f["c"].columns)
    col = {s: i for i, s in enumerate(cols)}
    c, h, lo = f["c"].to_numpy(), f["h"].to_numpy(), f["lo"].to_numpy()
    ew = f["ret"].where(f["tradable"]).mean(axis=1).fillna(0)            # equal-weight universe daily return
    ew_level = (1 + ew).cumprod().to_numpy()
    cm = CostModel(PROFILES["icici_moneysaver"])
    rt_cost = cm.round_trip_pct(25_000) / 100 + 2 * 0.0015                # ~1.30% round trip incl. slippage

    t = pd.read_csv(AS_WRITTEN, parse_dates=["entry_date", "exit_date"])
    g = pd.read_csv(GROSS, parse_dates=["entry_date", "exit_date"])
    L: list[str] = ["# Handbook swing backtest — post-mortem", "",
                    "As-written run: 2020-01-01 → 2026-10-09, ₹5 lakh, 0.5% risk per trade, ICICI MoneySaver + 0.15% "
                    "slippage per side, GTT breakout entries. Gross run = same rules, no costs.", ""]

    # per-trade path statistics
    rows = []
    for tr in t.itertuples(index=False):
        j = col.get(tr.symbol)
        if j is None:
            continue
        e = idx.get_loc(tr.entry_date)
        x = idx.get_loc(tr.exit_date)
        rps = tr.pnl / (tr.R * tr.shares) if tr.R else np.nan          # risk per share (₹)
        hh, ll = np.nanmax(h[e:x + 1, j]), np.nanmin(lo[e:x + 1, j])
        rec = {"symbol": tr.symbol, "setup": tr.setup, "reason": tr.reason, "R": tr.R, "days": tr.days,
               "entry_date": tr.entry_date, "win": tr.R > 0,
               "mfe_R": (hh - tr.entry) / rps if rps > 0 else np.nan, "mae_R": (ll - tr.entry) / rps if rps > 0 else np.nan,
               "stop_pct": rps / tr.entry * 100, "regime": int(reg["score"].iloc[e - 1])}
        for n in HOLDS:                                                    # held n sessions from entry, no stop
            k = e + n
            if k < len(idx) and np.isfinite(c[k, j]):
                ret = c[k, j] / tr.entry - 1
                rec[f"hold{n}_pct"] = ret * 100
                rec[f"hold{n}_net_pct"] = (ret - rt_cost) * 100
                rec[f"hold{n}_ex_pct"] = (ret - (ew_level[k] / ew_level[e - 1] - 1)) * 100
                rec[f"hold{n}_net_R"] = (ret - rt_cost) * tr.entry / rps if rps > 0 else np.nan
        for n in AFTER:                                                    # what happened after the actual exit
            k = x + n
            if k < len(idx) and np.isfinite(c[k, j]) and np.isfinite(c[x, j]):
                rec[f"after{n}_pct"] = (c[k, j] / c[x, j] - 1) * 100
                rec[f"after{n}_ex_pct"] = rec[f"after{n}_pct"] - (ew_level[k] / ew_level[x] - 1) * 100
        rows.append(rec)
    p = pd.DataFrame(rows)
    p.to_csv(OUT / "diagnostics_trades.csv", index=False)

    # 1. holding period
    q = p["days"].describe(percentiles=[.25, .5, .75, .9])
    L += ["## 1. Holding period (trading sessions)", "",
          f"Median **{q['50%']:.0f}** sessions, mean {q['mean']:.1f}, 25% of trades ≤ {q['25%']:.0f}, 75% ≤ {q['75%']:.0f}, "
          f"90% ≤ {q['90%']:.0f}, longest {q['max']:.0f}. The handbook describes holds of 2–8 weeks (10–40 sessions); "
          f"{(p['days'] >= 10).mean() * 100:.0f}% of trades lasted 10 sessions or more.", ""]
    buckets = pd.cut(p["days"], [0, 1, 2, 5, 10, 20, 40, 400], labels=["1", "2", "3–5", "6–10", "11–20", "21–40", "> 40"])
    hb_tab = p.groupby(buckets, observed=False).agg(trades=("R", "size"), win_pct=("win", "mean"), avg_R=("R", "mean"))
    hb_tab["win_pct"] = (hb_tab["win_pct"] * 100).round(1)
    hb_tab["share_pct"] = (hb_tab["trades"] / len(p) * 100).round(1)
    L += [md(hb_tab.rename_axis("sessions held").round(2)), ""]
    by_setup = p.groupby("setup").agg(trades=("R", "size"), median_days=("days", "median"), mean_days=("days", "mean"),
                                      win_days=("days", lambda s: s[p.loc[s.index, "win"]].median()),
                                      loss_days=("days", lambda s: s[~p.loc[s.index, "win"]].median())).round(1)
    L += ["By setup (median days for winners and losers):", "", md(by_setup), ""]

    # 2. activity
    allowed_breakout = reg["score"] >= 3
    allowed_pull = reg["score"] >= 2
    window = (idx >= pd.Timestamp("2020-01-01"))
    sig_rows = {}
    for name, s in sig.items():
        if name == "A_breakout_confirmed":
            continue
        cnt = s["signal"].sum(axis=1)
        ok = allowed_breakout if name in hb.BREAKOUT_SETUPS else allowed_pull
        sig_rows[name] = {"signals per day (avg)": cnt[window].mean(), "allowed by regime per day": cnt[window & ok].mean()}
    sig_tab = pd.DataFrame(sig_rows).T.round(2)
    sessions = int(window.sum())
    weeks = t["entry_date"].dt.to_period("W").nunique()
    ent_day = t.groupby("entry_date").size()
    eq = pd.read_csv(OUT / "equity_2020_icici_moneysaver_s0.0015_r0.005_gtt.csv", parse_dates=["date"]).set_index("date")
    L += ["## 2. Activity", "",
          f"- **{len(t):,} trades in {sessions:,} sessions = {len(t) / sessions:.2f} new trades per day**, "
          f"{len(t) / (sessions / 5):.1f} per week, {len(t) / (sessions / 21):.1f} per month.",
          f"- Days with at least one entry: {len(ent_day) / sessions * 100:.0f}% · busiest day {ent_day.max()} entries · "
          f"weeks with an entry: {weeks} of {sessions // 5}.",
          f"- Positions held at once: average {eq['positions'].mean():.1f}, maximum {eq['positions'].max()} (cap 8).",
          f"- Capital at work: average {eq['invested_pct'].mean() * 100:.0f}% (the rest idle in cash, earning nothing).",
          f"- Round trips cost ≈ {rt_cost * 100:.2f}% each (ICICI + slippage); "
          f"total charges paid ₹{t['pnl'].sum() - g['pnl'].sum():+,.0f} vs the gross run's P&L.", "",
          "Signals the scanner produced (before portfolio limits):", "", md(sig_tab), ""]
    yr = t.groupby(t["entry_date"].dt.year).agg(trades=("R", "size"), win_pct=("R", lambda s: (s > 0).mean() * 100),
                                                 expectancy_R=("R", "mean")).round(2)
    L += ["Trades per year:", "", md(yr), ""]

    # 3. winners vs losers
    wl = p.groupby("win").agg(trades=("R", "size"), avg_R=("R", "mean"), median_days=("days", "median"),
                              avg_mfe_R=("mfe_R", "mean"), avg_mae_R=("mae_R", "mean")).round(2)
    wl.index = wl.index.map({True: "winners", False: "losers"})
    reasons = p.groupby("reason").agg(trades=("R", "size"), win_pct=("win", "mean"), avg_R=("R", "mean"),
                                      median_days=("days", "median"), avg_mfe_R=("mfe_R", "mean")).sort_values("trades", ascending=False)
    reasons["win_pct"] = (reasons["win_pct"] * 100).round(1)
    losers = p[~p["win"]]
    green_first = losers[losers["mfe_R"] >= 1.0]
    gap = p[p["reason"] == "stop (gap)"]
    L += ["## 3. Winners vs losers", "", md(wl), "",
          "MFE = the best price reached while held, in R; MAE = the worst. A loser with MFE ≥ +1R was a winner first.", "",
          f"- {len(p[p['win']]):,} winners ({p['win'].mean() * 100:.0f}%) vs {len(losers):,} losers.",
          f"- **{len(green_first)} losers ({len(green_first) / len(losers) * 100:.0f}%) were up at least +1R before they lost** "
          f"(median MFE of all losers {losers['mfe_R'].median():.2f}R).",
          f"- {len(gap)} stops were hit by an overnight gap, average {gap['R'].mean():.2f}R (worse than the planned −1R).",
          f"- Average stop distance {p['stop_pct'].mean():.1f}% of price; {(p['stop_pct'] >= 7.9).mean() * 100:.0f}% of stops "
          "sat at the 8% cap.", "", "Why trades ended:", "", md(reasons.round(2)), ""]

    # 4. what if held longer
    hold = pd.DataFrame({f"{n} sessions": {
        "avg return %": p[f"hold{n}_pct"].mean(), "median return %": p[f"hold{n}_pct"].median(),
        "avg vs universe %": p[f"hold{n}_ex_pct"].mean(), "% beating universe": (p[f"hold{n}_ex_pct"] > 0).mean() * 100,
        "avg after costs %": p[f"hold{n}_net_pct"].mean(), "avg after costs R": p[f"hold{n}_net_R"].mean(),
        "% profitable after costs": (p[f"hold{n}_net_pct"] > 0).mean() * 100} for n in HOLDS}).round(2)
    actual = {"avg R (actual exits, after costs)": round(p["R"].mean(), 3)}
    L += ["## 4. What if they had been held longer?", "",
          "### (a) Every entry held a fixed number of sessions, no stop", "",
          md(hold.rename_axis("held from entry")), "",
          f"For comparison the actual exits averaged {actual['avg R (actual exits, after costs)']}R per trade after costs.", ""]
    by_setup_hold = pd.DataFrame({s: {f"{n}d vs universe %": grp[f"hold{n}_ex_pct"].mean() for n in (5, 20, 60)}
                                  for s, grp in p.groupby("setup")}).T.round(2)
    L += ["Excess over the universe by setup:", "", md(by_setup_hold.rename_axis("setup")), ""]
    after = pd.DataFrame({grp: {f"{n} sessions later %": d[f"after{n}_pct"].mean() for n in AFTER} |
                          {f"{n} sessions later vs universe %": d[f"after{n}_ex_pct"].mean() for n in AFTER}
                          for grp, d in (("winners", p[p["win"]]), ("losers", p[~p["win"]]),
                                         ("stopped out", p[p["reason"].str.startswith("stop")]),
                                         ("failed breakout", p[p["reason"] == "failed breakout"]),
                                         ("trailed out (20-EMA)", p[p["reason"] == "trail 20-EMA"]),
                                         ("time stop", p[p["reason"] == "time stop"]))}).T.round(2)
    L += ["### (b) What each trade did AFTER its actual exit", "", md(after.rename_axis("group")), ""]

    # 5. where the money went
    reg_tab = p.groupby("regime").agg(trades=("R", "size"), win_pct=("win", "mean"), avg_R=("R", "mean")).round(3)
    reg_tab["win_pct"] = (reg_tab["win_pct"] * 100).round(1)
    gross_by = g.groupby("setup")["R"].mean().rename("gross R")
    net_by = t.groupby("setup")["R"].mean().rename("after-cost R")
    money = pd.concat([gross_by, net_by], axis=1)
    money["cost drag R"] = money["gross R"] - money["after-cost R"]
    L += ["## 5. Where the money went", "",
          f"- Gross expectancy {g['R'].mean():+.3f}R per trade; after ICICI costs and slippage {t['R'].mean():+.3f}R. "
          f"The rules have no edge before costs, and costs take a further ≈{g['R'].mean() - t['R'].mean():.2f}R per trade.",
          "", "By setup:", "", md(money.round(3).rename_axis("setup")), "",
          "By regime score on the entry day (the handbook allows breakouts at 3–4, pullbacks at 2+):", "",
          md(reg_tab.rename_axis("regime")), ""]
    (OUT / "DIAGNOSTICS.md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
