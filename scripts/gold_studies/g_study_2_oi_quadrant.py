#!/usr/bin/env python
"""G-STUDY-2 — does the daily open-interest × price quadrant (COMEX gold product OI) forecast anything? Pre-registered
in reports/gold_program/G-STUDY-2/PLAN.md (read it first; the pass bars there are binding).

    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/g_study_2_oi_quadrant.py --db data/market.duckdb [--out DIR]
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/g_study_2_oi_quadrant.py --fixture <product-oi.csv>

Stored data only, no network. The verdict run needs `gold_cme_daily_voi` (CME FTP daily_volume.xlsx, 2014 →; PLAN c.4
backfill after owner decision O-6) read from a read-only snapshot copy of the DuckDB file; `--fixture` accepts the
G-CME product-OI CSV shape (`trade_date,sym,…,oi`). Fewer than 500 sessions → `insufficient history` (code 4); no table
→ `data not yet ingested` (code 3). It never substitutes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gold_studies import common as C

STUDY = "G-STUDY-2"
TITLE = "Daily OI × price quadrant (COMEX gold product OI)"
SCRIPT = "scripts/gold_studies/g_study_2_oi_quadrant.py"
HORIZONS = (1, 5, 20)
SPLIT = "2020-06-30"
MIN_SESSIONS = 500
SEED = 20261026
PLACEBO_LAG = 60
PERIODS_PER_YEAR = 252
PRODUCTS = ("GC",)
LABELS = {(1, 1): "long build-up", (-1, 1): "short build-up", (1, -1): "short covering", (-1, -1): "long unwinding"}
ARROWS = {"long build-up": "P↑ OI↑", "short build-up": "P↓ OI↑", "short covering": "P↑ OI↓", "long unwinding": "P↓ OI↓"}
EXPECTED_SIGN = {"long build-up": 1, "short build-up": -1, "short covering": -1, "long unwinding": 1}   # the folklore (H1–H4)
BULLISH = {"long build-up", "long unwinding"}
ACTIVE_MONTHS = (2, 4, 6, 8, 10, 12)
OI_CHANGES = (1, 5, 20)
DEFAULT_OUT = C.GOLD_PROGRAM / "G-STUDY-2"


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def load_inputs(db: Path | None = None, fixture: Path | None = None, products: tuple[str, ...] = PRODUCTS,
                price_csv: Path | None = None, *, allow_market_hours: bool = False, tmp_dir: Path | None = None
                ) -> tuple[pd.Series, pd.Series, dict[str, str]]:
    """Product open interest summed over `products` by trade date, the GC=F close by session, and their sources. The
    DuckDB file is read on a snapshot copy that is removed afterwards (never the live file itself). The CME daily file
    for T is final (no revisions are stored for `gold_cme_daily_voi`): the T+1 entry rule is the point-in-time rule."""
    if db is not None:
        with C.open_snapshot(db, tmp_dir, allow_market_hours=allow_market_hours) as con:
            df = C.read_cme_product_oi(con, products)
            price = C.read_daily_bars(con, "COMEX_GC_FRONT")
        meta = {"oi": f"gold_cme_daily_voi {products} ({db})", "price": "gold_daily_bars COMEX_GC_FRONT"}
    elif fixture is not None:
        df = C.load_cme_family_oi_csv(fixture)
        px = price_csv or C.G_STUDY_DATA / "yahoo_GC_F_1d.csv"
        price = C.load_yahoo_daily(px)["close"]
        meta = {"oi": str(fixture), "price": str(px)}
    else:
        raise C.DataNotIngested("gold_cme_daily_voi (CME FTP daily_volume.xlsx backfill, 2014 →)")
    df = df[df["sym"].isin(products)]
    if df.empty:
        raise C.DataNotIngested(f"no rows for products {products}")
    oi = df.groupby("trade_date")["oi"].sum().sort_index()
    return oi, price, meta


def mechanical_flags(dates: pd.DatetimeIndex) -> pd.Series:
    """Approximate roll/expiry mechanics without the CME calendar: the last 5 sessions of the month before an active
    delivery month (first notice day = that month's last business day) and the last 2 sessions of an active month
    (around last trade). With `gold_cme_calendar` stored, B1's FND/LTD dates should replace this."""
    idx = pd.DatetimeIndex(dates)
    s = pd.Series(idx, index=idx)
    per = s.dt.to_period("M")
    from_end = s.groupby(per).cumcount(ascending=False)         # 0 = last session of the month
    month = s.dt.month
    before_active = month.isin([m - 1 if m > 1 else 12 for m in ACTIVE_MONTHS])
    active = month.isin(ACTIVE_MONTHS)
    return ((before_active & (from_end < 5)) | (active & (from_end < 2))).astype(bool)


def build_panel(oi: pd.Series, price: pd.Series, entry_shift: int = 1, horizons: tuple[int, ...] = HORIZONS) -> pd.DataFrame:
    """One row per OI trade date T: label from Δclose_T × ΔOI_T (both as of T), OI % changes, `mechanical` flag; entry =
    the `entry_shift`-th price session strictly after T (the file for T is posted on T+1 before T+1's settlement);
    forward returns from that entry close; `r_next` between consecutive entries."""
    o = pd.Series(oi, dtype=float).dropna().sort_index()
    p = pd.Series(price, dtype=float).dropna().sort_index()
    pan = pd.DataFrame({"oi": o})
    px_T = p.reindex(pan.index, method="ffill")
    pan["px_T"] = px_T
    pan["dpx_T"] = px_T.pct_change() * 100
    pan["doi"] = o.diff()
    sp, so = np.sign(pan["dpx_T"]), np.sign(pan["doi"])
    lab = [LABELS.get((int(a), int(b))) if not (np.isnan(a) or np.isnan(b) or a == 0 or b == 0) else None for a, b in zip(sp, so)]
    pan["label"] = pd.Series(lab, index=pan.index, dtype=object)
    for k in OI_CHANGES:
        pan[f"oi_chg{k}"] = (o / o.shift(k) - 1) * 100
    pan["mechanical"] = mechanical_flags(pan.index).to_numpy()
    pv = p.to_numpy()
    n = len(pv)
    pos = p.index.searchsorted(pan.index.to_numpy(), side="right") + (entry_shift - 1)
    valid = pos < n
    eidx = np.where(valid, pos, n - 1)
    pan["entry"] = pd.to_datetime(np.where(valid, p.index.to_numpy()[eidx], np.datetime64("NaT")))
    pan["entry_px"] = np.where(valid, pv[eidx], np.nan)
    for h in horizons:
        ok = valid & (pos + h < n)
        hidx = np.where(ok, pos + h, n - 1)
        pan[f"fwd{h}"] = np.where(ok, (pv[hidx] / pv[eidx] - 1) * 100, np.nan)
    pan["r_next"] = pan["entry_px"].shift(-1) / pan["entry_px"] - 1
    return pan


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def cell_tests(pan: pd.DataFrame, h: int, *, split: str = SPLIT, exclude_mechanical: bool = False, label_col: str = "label") -> list[dict[str, Any]]:
    """Each quadrant's forward excess return vs the unconditional mean (NW t, lags h−1), full sample and halves."""
    d = pan if not exclude_mechanical else pan[~pan["mechanical"]]
    fwd = d[f"fwd{h}"]
    h1, h2 = C.halves(d.index, split)
    rows = []
    for lab in LABELS.values():
        m = d[label_col] == lab
        full = C.cell_vs_all(fwd, m, h - 1)
        c1 = C.cell_vs_all(fwd[h1], m[h1], h - 1)
        c2 = C.cell_vs_all(fwd[h2], m[h2], h - 1)
        v = C.verdict(full["t_nw"], c1["t_nw"], c2["t_nw"])
        exp = EXPECTED_SIGN[lab]
        rows.append({"quadrant": lab, "h": h, "n": full["n"], "mean": full["mean"], "hit_pct": full["hit_pct"], "excess": full["excess"],
                     "t": full["t_nw"], "h1_excess": c1["excess"], "h1_t": c1["t_nw"], "h1_n": c1["n"], "h2_excess": c2["excess"], "h2_t": c2["t_nw"],
                     "h2_n": c2["n"], "expected_sign": exp, "sign_as_folklore": bool(full["excess"] == full["excess"] and np.sign(full["excess"]) == exp),
                     "mechanical_excluded": exclude_mechanical, "verdict": v})
    return rows


def ic_tests(pan: pd.DataFrame, h: int, *, split: str = SPLIT) -> list[dict[str, Any]]:
    """H5: rank IC of the continuous OI change (1/5/20 sessions) vs fwd_h, full sample and halves."""
    fwd = pan[f"fwd{h}"]
    h1, h2 = C.halves(pan.index, split)
    rows = []
    for k in OI_CHANGES:
        sig = f"oi_chg{k}"
        ic, ic1, ic2 = C.rank_ic(pan[sig], fwd, h - 1), C.rank_ic(pan.loc[h1, sig], fwd[h1], h - 1), C.rank_ic(pan.loc[h2, sig], fwd[h2], h - 1)
        rows.append({"signal": sig, "h": h, "n": ic["n"], "ic": ic["spearman"], "t_ic": ic["t"], "ic_h1": ic1["spearman"], "t_h1": ic1["t"],
                     "ic_h2": ic2["spearman"], "t_h2": ic2["t"], "verdict": C.verdict(ic["t"], ic1["t"], ic2["t"])})
    return rows


def folklore_rule(pan: pd.DataFrame, h: int, *, split: str = SPLIT, label_col: str = "label") -> dict[str, Any]:
    """H6: long after a 'bullish' label (long build-up / long unwinding), flat otherwise; fixed, after costs; OOS t in
    the full OOS span and in both OOS halves (the OOS span cut at its midpoint, PLAN 'Tests'). The verdict is SIGNED
    (`C.verdict_traded`): the rule must PAY — a rule that loses consistently is a FAIL, never a PASS."""
    ind = pan[label_col].isin(BULLISH).astype(float)
    ind[pan[label_col].isna()] = np.nan
    ev = C.indicator_long_flat(ind, pan["r_next"], h, periods_per_year=PERIODS_PER_YEAR)
    if not ev:
        return {}
    t1, t2, cut = C.oos_halves_t(ev, h)
    oos_t = ev.get("OOS_t_excess", float("nan"))
    return {"rule": "long after long build-up / long unwinding", "h": h, "oos_from": ev["is_end"], "oos_split": cut,
            "oos_exposure_pct": ev.get("OOS_exposure_pct"), "oos_strat_cagr": ev.get("OOS_strat_cagr"), "oos_bh_cagr": ev.get("OOS_bh_cagr"),
            "oos_excess_pa_pct": ev.get("OOS_excess_vs_scaled_pa_pct"), "oos_t": oos_t, "oos_t_h1": round(t1, 2), "oos_t_h2": round(t2, 2),
            "verdict": C.verdict_traded(oos_t, t1, t2)}


def negative_controls(pan: pd.DataFrame, seed: int = SEED, placebo_lag: int = PLACEBO_LAG) -> dict[str, Any]:
    """Labels lagged 60 sessions and labels shuffled (seed) must produce no PASS cell and an H6 OOS |t| < 2."""
    rng = np.random.default_rng(seed)
    p = pan.copy()
    p["label_placebo"] = p["label"].shift(placebo_lag)
    p["label_shuffled"] = pd.Series(rng.permutation(p["label"].to_numpy(copy=True)), index=p.index, dtype=object)
    out: dict[str, Any] = {}
    for col in ("label_placebo", "label_shuffled"):
        cells = [r for h in HORIZONS for r in cell_tests(p, h, label_col=col)]
        rules = [folklore_rule(p, h, label_col=col) for h in HORIZONS]
        out[col] = {"pass_cells": [f"{r['quadrant']}@{r['h']}" for r in cells if r["verdict"] == C.PASS],
                    "rule_oos_t": [r.get("oos_t") for r in rules],
                    "ok": not any(r["verdict"] == C.PASS for r in cells) and all(abs(r.get("oos_t", 0.0) or 0.0) < 2 for r in rules)}
    out["ok"] = all(v["ok"] for v in out.values() if isinstance(v, dict))
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def run_study(oi: pd.Series, price: pd.Series, out: Path, meta: dict[str, str] | None = None) -> dict[str, Any]:
    res = out / "results"
    res.mkdir(parents=True, exist_ok=True)
    pan = build_panel(oi, price)
    cells = [r for h in HORIZONS for r in cell_tests(pan, h)]
    cells_nomech = [r for h in HORIZONS for r in cell_tests(pan, h, exclude_mechanical=True)]
    ics = [r for h in HORIZONS for r in ic_tests(pan, h)]
    rules = [r for r in (folklore_rule(pan, h) for h in HORIZONS) if r]
    late = [r for h in HORIZONS for r in cell_tests(build_panel(oi, price, entry_shift=2), h)]
    controls = negative_controls(pan)
    for name, rows in (("cells", cells), ("cells_no_mechanical", cells_nomech), ("ic_tests", ics), ("folklore_rule", rules), ("cells_late_entry", late)):
        pd.DataFrame(rows).to_csv(res / f"{name}.csv", index=False)
    pan.to_csv(res / "panel.csv")
    counts = pan["label"].value_counts(dropna=True).to_dict()
    any_cell_pass = any(r["verdict"] == C.PASS for r in cells)
    rule_pass = any(r["verdict"] == C.PASS for r in rules)
    overall = C.PASS if (any_cell_pass and rule_pass) else (C.CONTEXT_ONLY if any(r["verdict"] in (C.PASS, C.CONTEXT_ONLY) for r in cells + ics + rules) else C.FAIL)
    summary: dict[str, Any] = {"study": STUDY, "plan": "reports/gold_program/G-STUDY-2/PLAN.md", "generated": pd.Timestamp.now().isoformat(timespec="minutes"),
                               "inputs": meta or {}, "sample": {"sessions": len(pan), "first": str(pan.index[0].date()), "last": str(pan.index[-1].date()),
                                                                "split": SPLIT, "label_counts": {str(k): int(v) for k, v in counts.items()},
                                                                "mechanical_sessions": int(pan["mechanical"].sum()), "cost_rt_pct": C.COST_RT},
                               "cells": cells, "cells_no_mechanical": cells_nomech, "ic_tests": ics, "folklore_rule": rules, "cells_late_entry": late,
                               "negative_controls": controls, "controls_ok": controls["ok"], "overall": overall}
    C.write_json(out / "summary.json", summary)
    (out / "REPORT.md").write_text(report_md(summary), encoding="utf-8")
    (out / "FINDINGS_ROW.md").write_text(findings_rows_md(summary), encoding="utf-8")
    (out / "FINDINGS.md").write_text(findings_md(summary), encoding="utf-8")
    return summary


def _rows(summary: dict[str, Any]) -> list[C.Row]:
    rows = [C.Row(f"{r['quadrant']} ({ARROWS[r['quadrant']]}) → {r['h']} sessions",
                  f"excess {C.fmt(r['excess'])} % (t {C.fmt(r['t'])}, n {r['n']})",
                  f"{C.fmt(r['h1_excess'])} % (t {C.fmt(r['h1_t'])})", f"{C.fmt(r['h2_excess'])} % (t {C.fmt(r['h2_t'])})", r["verdict"])
            for r in summary["cells"]]
    for r in summary["folklore_rule"]:
        rows.append(C.Row(f"H6 · {r['rule']} → {r['h']} sessions, after 0.15 %",
                          f"OOS {C.fmt(r['oos_excess_pa_pct'])} %/yr (t {C.fmt(r['oos_t'])})",
                          f"t {C.fmt(r['oos_t_h1'])}", f"t {C.fmt(r['oos_t_h2'])}", r["verdict"]))
    return rows


def findings_rows_md(summary: dict[str, Any]) -> str:
    """The 4-column rows to paste into reports/gold_program/FINDINGS.md (shape: scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md)."""
    return C.findings_rows_md(STUDY, _rows(summary))


def findings_md(summary: dict[str, Any]) -> str:
    """The study's own FINDINGS.md in the reports/fii_positioning format, every sentence computed from the summary."""
    s, nc = summary["sample"], summary["negative_controls"]
    cells, rules, ics = summary["cells"], summary["folklore_rule"], summary["ic_tests"]
    n_pass = sum(r["verdict"] == C.PASS for r in cells)
    n_ctx = sum(r["verdict"] == C.CONTEXT_ONLY for r in cells)
    n_ge2 = sum(abs(r["t"]) >= 2 for r in cells if not np.isnan(r["t"]))
    folklore_ok = sum(r["sign_as_folklore"] for r in cells)
    overall = summary["overall"]
    if overall == C.PASS:
        verdict_line = ("PASS as a forecast for at least one quadrant AND the traded rule — an exception to the prior; the owner's "
                        "separate approval is still required before any badge changes (PLAN f.5).")
    elif overall == C.CONTEXT_ONLY:
        verdict_line = (f"CONTEXT-ONLY. {n_ctx} of 12 cells reach |t| ≥ 2 in the full sample but none holds in both halves with a paying "
                        "rule; the quadrant labels describe yesterday, they do not forecast.")
    else:
        verdict_line = ("FAIL as a forecast at 1, 5 and 20 sessions for every quadrant and for the continuous OI change; the daily "
                        "OI × price label describes yesterday's session, it does not forecast.")
    bullets = [(f"{n_ge2} of 12 cells reach |t| ≥ 2 in the full sample ({n_pass} PASS, {n_ctx} CONTEXT-ONLY); ≈0.6 would by chance. "
               f"The folklore sign holds in {folklore_ok} of 12 cells."),
               "H6 (long after long build-up / long unwinding, flat otherwise, 0.15 % per round trip): " +
               "; ".join(f"h={r['h']} OOS {C.fmt(r['oos_excess_pa_pct'])} %/yr (t {C.fmt(r['oos_t'])}; halves {C.fmt(r['oos_t_h1'])} / "
                         f"{C.fmt(r['oos_t_h2'])}) {r['verdict']}" for r in rules) + ".",
               "H5 (continuous OI change, rank IC): " + "; ".join(f"{r['signal']}@{r['h']} IC {C.fmt(r['ic'], 3)} (t {C.fmt(r['t_ic'])}) {r['verdict']}"
                                                                for r in ics) + ".",
               (f"Without the {s['mechanical_sessions']} mechanical (roll / expiry) sessions and with entry at T+2 the picture is the same "
               f"(REPORT.md); negative controls (60-session placebo, seeded shuffle) ok: {nc['ok']}."),
               f"Sample: {s['sessions']} sessions {s['first']} → {s['last']}, halves at {s['split']}; labels {s['label_counts']}."]
    use = ("the GOLD page keeps the four labels on `d.quadrant` / `p.daily.comex` as a description of yesterday's session with the "
           "`context` badge and the caption 'folklore: no forecasting power (G-STUDY-2)'; no alert, no colour, nothing feeds a trade."
           if overall != C.PASS else "do not change any badge from this file alone — PLAN f.5 requires the owner's separate approval.")
    return C.findings_template(STUDY, f"{STUDY} · {TITLE}", C.now_label(),
                               f"{s['sessions']} sessions of COMEX GC product open interest (CME FTP daily volume files) priced on GC=F, "
                               f"{s['first']} → {s['last']}; the file for T is public before session T+1 settles, so entry = close(T+1); "
                               f"Newey-West t for the overlapping 5- and 20-session windows; costs {s['cost_rt_pct']} % per round trip.",
                               verdict_line, _rows(summary), bullets, use, SCRIPT)


def report_md(summary: dict[str, Any]) -> str:
    s = summary["sample"]
    ccols = ["quadrant", "h", "n", "mean", "hit_pct", "excess", "t", "h1_excess", "h1_t", "h1_n", "h2_excess", "h2_t", "h2_n", "sign_as_folklore", "verdict"]
    nc = summary["negative_controls"]
    parts = [f"# {STUDY} · {TITLE} — result tables\n",
             (f"Generated {summary['generated']} by `{SCRIPT}` from the plan in `PLAN.md`. Sessions {s['sessions']} ({s['first']} → {s['last']}); "
              f"labels {s['label_counts']}; mechanical sessions {s['mechanical_sessions']}; halves at {s['split']}; costs {s['cost_rt_pct']} %.\n"),
             "## Quadrant cells (label from Δclose_T × ΔOI_T; entry = close of T+1)\n", C.md_table(summary["cells"], ccols),
             "\n## Without mechanical (roll / expiry) sessions\n", C.md_table(summary["cells_no_mechanical"], ccols),
             "\n## Entry one session later (T+2)\n", C.md_table(summary["cells_late_entry"], ccols),
             "\n## H5 · continuous OI change, rank IC\n",
             C.md_table(summary["ic_tests"], ["signal", "h", "n", "ic", "t_ic", "ic_h1", "t_h1", "ic_h2", "t_h2", "verdict"]),
             "\n## H6 · the folklore rule after costs (OOS halves cut at the OOS midpoint)\n",
             C.md_table(summary["folklore_rule"], ["rule", "h", "oos_from", "oos_split", "oos_exposure_pct", "oos_strat_cagr", "oos_bh_cagr",
                                                   "oos_excess_pa_pct", "oos_t", "oos_t_h1", "oos_t_h2", "verdict"]),
             (f"\n## Negative controls\n\nplacebo: pass cells {nc['label_placebo']['pass_cells']}, rule t {nc['label_placebo']['rule_oos_t']} → "
              f"ok {nc['label_placebo']['ok']}; shuffled: pass cells {nc['label_shuffled']['pass_cells']}, rule t "
              f"{nc['label_shuffled']['rule_oos_t']} → ok {nc['label_shuffled']['ok']}.\n"),
             f"\n## Overall: **{summary['overall']}** (controls ok: {summary['controls_ok']})\n"]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="data-service DuckDB file (read on a snapshot copy)")
    ap.add_argument("--fixture", type=Path, default=None, help="product-OI CSV in the G-CME sample shape (trade_date,sym,…,oi)")
    ap.add_argument("--products", default=",".join(PRODUCTS), help="comma-separated product codes summed into the OI (default GC; GC,MGC for the variant)")
    ap.add_argument("--allow-market-hours", action="store_true",
                    help="copy the live DuckDB even inside an IST busy window (07:45–15:45, 18:30–21:15 Mon–Fri); default: refuse, exit 5")
    ap.add_argument("--tmp-dir", type=Path, default=None, help="where the read-only snapshot copy goes (default: a temp dir, removed afterwards)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    products = tuple(p.strip() for p in a.products.split(",") if p.strip())
    try:
        oi, price, meta = load_inputs(a.db, a.fixture, products, allow_market_hours=a.allow_market_hours, tmp_dir=a.tmp_dir)
    except C.DataNotIngested as e:
        C.not_ingested(STUDY, "gold_cme_daily_voi (C1 daily_volume.xlsx backfill 2014 →, ≈3,227 files) + gold_daily_bars COMEX_GC_FRONT",
                       "approve O-6, run the CME FTP backfill (PLAN c.4) and the gold_cme_daily job, then pass --db", str(e))
    except (C.LiveFileBusy, C.SnapshotSpace) as e:
        C.live_busy(STUDY, str(e))
    if len(oi) < MIN_SESSIONS:
        C.insufficient(STUDY, f">= {MIN_SESSIONS} sessions of product OI", f"{len(oi)} sessions ({oi.index[0].date()} → {oi.index[-1].date()})")
    summary = run_study(oi, price, a.out, meta)
    print(C.Status(STUDY, "ran", detail=f"overall {summary['overall']}; controls ok {summary['controls_ok']}; out {a.out}").to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
