"""
Data-quality check for the NSE bhavcopy panel (Phase A exit criterion).

1. Adjusted NSE daily returns vs Yahoo adjusted-close returns for every symbol in
   both sources: share of days that disagree, and the largest disagreements
   (a missed split/bonus shows up as a ±50%+ one-day gap).
2. Corporate-action factors derived from PREV_CLOSE vs the Yahoo splits table.
3. Survivorship: symbols that traded in EQ since 2020 but are not in today's
   instrument list (what the Yahoo-only research never saw).

Usage:  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/nse_panel_qa.py
Output: reports/data_quality/NSE_PANEL_QA.md (+ qa_mismatches.csv)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from nse_panel import corporate_action_factors, load_panel, pick_equity_rows, survivorship_report  # noqa: E402


def main() -> None:
    out = ROOT / "reports" / "data_quality"
    out.mkdir(parents=True, exist_ok=True)
    db = ROOT / "data" / "market.duckdb"
    tmp = Path(tempfile.mkdtemp(prefix="qa_"))
    shutil.copy2(db, tmp / "s.duckdb")
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", tmp / "s.duckdb.wal")
    con = duckdb.connect(str(tmp / "s.duckdb"))
    try:
        panel = load_panel(con)
        yahoo = con.execute("SELECT ticker, date, adjusted_close FROM ohlcv").df()
        splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0").df()
        inst = con.execute("SELECT ticker, instrument_type FROM instruments").df()
        raw = con.execute("SELECT symbol, series, date, prev_close, close, open, high, low, avg_price, volume "
                          "FROM nse_bhavcopy").df()
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)

    # 1. return agreement
    yahoo["date"] = pd.to_datetime(yahoo["date"])
    yw = yahoo.pivot(index="date", columns="ticker", values="adjusted_close").sort_index()
    common = sorted(set(yw.columns) & set(panel["close"].columns))
    dates = panel["close"].index.intersection(yw.index)
    rn = panel["close"].loc[dates, common].pct_change(fill_method=None)
    ry = yw.loc[dates, common].pct_change(fill_method=None)
    both = rn.notna() & ry.notna()
    diff = (rn - ry).abs().where(both)
    n_obs = int(both.values.sum())
    frac_1pct = float((diff > 0.01).values.sum() / n_obs)
    frac_5pct = float((diff > 0.05).values.sum() / n_obs)
    big = diff.stack()
    big = big[big > 0.2].sort_values(ascending=False)
    mism = big.rename("abs_diff").reset_index().rename(columns={"level_0": "date", "level_1": "symbol"})
    mism["nse_ret"] = [rn.at[d, s] for d, s in zip(mism["date"], mism["symbol"])]
    mism["yahoo_ret"] = [ry.at[d, s] for d, s in zip(mism["date"], mism["symbol"])]
    mism.to_csv(out / "qa_mismatches.csv", index=False)
    per_sym = diff.gt(0.05).sum().sort_values(ascending=False)

    # 2. corporate actions: how good is the gap rule where Yahoo gives the truth?
    events = panel["corporate_actions"]
    raw["date"] = pd.to_datetime(raw["date"])
    splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
    sp = splits[(splits["date"] >= panel["close"].index[0]) & splits["ticker"].isin(common)]
    eq_common = pick_equity_rows(raw[raw["symbol"].isin(common)]).sort_values(["symbol", "date"])
    blind = corporate_action_factors(eq_common, None)       # gap rule alone, Yahoo hidden
    hits = 0
    for t, d, r in zip(sp["ticker"], sp["date"], sp["ratio"]):
        b = blind[(blind["symbol"] == t) & ((blind["date"] - d).dt.days.abs() <= 7)]
        hits += bool(len(b)) and bool(((b["k"] * r - 1).abs() < 0.05).any())
    recall = hits / len(sp) if len(sp) else float("nan")
    false_pos = 0
    for t, d in zip(blind["symbol"], blind["date"]):
        s_ = sp[(sp["ticker"] == t) & ((sp["date"] - d).dt.days.abs() <= 7)]
        false_pos += s_.empty
    precision = 1 - false_pos / len(blind) if len(blind) else float("nan")

    # 3. survivorship
    current = set(inst["ticker"])
    surv = survivorship_report(panel, current)
    eq_hist = set(panel["close"].columns[(panel["series"] == "EQ").any()])
    liquid = panel["turnover_cr"].rolling(126, min_periods=60).median().max() >= 10
    gone_liquid = sorted(s for s in eq_hist if s not in current and bool(liquid.get(s, False)))

    lines = [
        "# NSE bhavcopy panel: data-quality check", "",
        f"Panel: {panel['close'].shape[0]:,} sessions × {panel['close'].shape[1]:,} symbols "
        f"({panel['close'].index[0].date()} → {panel['close'].index[-1].date()}).", "",
        "## 1. Agreement with Yahoo adjusted closes",
        f"- Symbols in both sources: **{len(common):,}**; overlapping daily returns: **{n_obs:,}**",
        f"- Days where the two differ by more than 1 point: **{frac_1pct:.2%}**; more than 5 points: **{frac_5pct:.3%}**",
        f"- One-day gaps > 20 points (missed or mis-dated corporate action in either source): **{len(mism)}** "
        f"(listed in `qa_mismatches.csv`)",
        "- Symbols with the most >5-point disagreements: " + ", ".join(f"{s} ({n})" for s, n in per_sym.head(10).items()),
        "", "## 2. Corporate actions",
        f"- Events applied: **{len(events):,}** ({events['source'].value_counts().to_dict()})",
        f"- Gap rule scored against Yahoo on {len(sp)} known splits/bonuses: recall **{recall:.0%}**, "
        f"precision **{precision:.0%}** ({false_pos} gaps flagged with no Yahoo split within 7 days)",
        "", "## 3. Survivorship: what the Yahoo-only universe was missing",
        f"- Symbols traded in EQ series since {panel['close'].index[0].date()}: **{len(eq_hist):,}**",
        f"- Not in today's instrument list: **{len(eq_hist - current):,}**, of which **{len(gone_liquid):,}** "
        f"were liquid (≥ ₹10 Cr median turnover at some point)",
        f"- Stopped trading 30+ days before the last session: **{surv['stopped_trading_30d_plus']:,}**",
        "- Examples (liquid, missing from the old universe): " + ", ".join(gone_liquid[:30]), "",
    ]
    (out / "NSE_PANEL_QA.md").write_text("\n".join(lines))
    print("\n".join(lines))
    print("\nTop mismatches:\n", mism.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
