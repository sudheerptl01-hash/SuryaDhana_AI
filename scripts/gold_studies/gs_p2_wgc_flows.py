#!/usr/bin/env python
"""GS-P2 — do the World Gold Council's weekly gold-ETF flows (by region) predict COMEX gold? Pre-registered in
reports/gold_program/GS-P2/PLAN.md (read it first; the pass bars there are binding).

    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/gs_p2_wgc_flows.py --db data/market.duckdb [--out DIR]
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/gs_p2_wgc_flows.py --fixture-dir <dir> --check-only

Stored data only, no network. The verdict run needs the `gold_series` rows WGC_ETF_HOLD_T_* (weekly holdings by region,
every vintage with its release_at) written by the gold_weekly job and its backfill (PLAN c.3/c.4), read from a read-only
snapshot copy of the DuckDB file that is removed afterwards (never copied inside an IST busy window unless
--allow-market-hours). The panel is point-in-time: each week's signal uses the earlier weeks' holdings as they stood at
that week's release instant, so a later revision is never seen before its own release_at. Until the rows exist the script exits with `{"status": "data not yet ingested"}` (code 3) — it never
substitutes. `--fixture-dir` accepts the fsapi chart JSON shape saved by G-PHYSICAL for the ingest replay test only:
it loads, cross-checks Δholdings against the published flows and prints row counts; it never computes a verdict
(PLAN: "a verdict is computed only from the stored tables after O-1 and O-13"). `--check-only` does the same on `--db`.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gold_studies import common as C

STUDY = "GS-P2"
TITLE = "WGC weekly gold-ETF flows by region vs COMEX gold"
SCRIPT = "scripts/gold_studies/gs_p2_wgc_flows.py"
HORIZONS = {"1w": 5, "4w": 20, "13w": 65}        # name → sessions after the entry close
PRIMARY = ("1w", "4w")
WEEKS = {"1w": 1, "4w": 4, "13w": 13}
SPLIT = "2014-12-31"
MIN_HIST = 104                                   # weeks before an expanding rank / tercile cut-off is used
MIN_WEEKS = MIN_HIST + 160
REFIT_EVERY = 1
PERIODS_PER_YEAR = 52
PLACEBO_LAG = 26
SEED = 20261026
MIN_BASE_T = 10.0                                # a region's % flow is defined only once it holds >= 10 t (PLAN amendment A1)
REGIONS = ("GLOBAL", "NA", "EU", "ASIA", "OTHER")
HOLD_IDS = {r: f"WGC_ETF_HOLD_T_{r}" for r in REGIONS}
FLOW_IDS = {r: f"WGC_ETF_FLOW_T_{r}" for r in REGIONS}
FSAPI_REGION = {"North America": "NA", "Europe": "EU", "Asia": "ASIA", "Other": "OTHER"}
SIGNALS = {"S1": ("GLOBAL", 1), "S2": ("GLOBAL", 4), "S3": ("NA", 4), "S4": ("EU", 4), "S5": ("ASIA", 4)}   # region, weeks
CROSSCHECK_TOL_T = 0.5
DEFAULT_OUT = C.GOLD_PROGRAM / "GS-P2"


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _regionalise(df: pd.DataFrame) -> pd.DataFrame:
    """fsapi column names → region codes; GLOBAL = the sum of the four regions (NaN-safe, needs at least one)."""
    cols = {c: FSAPI_REGION[c] for c in df.columns if c in FSAPI_REGION}
    out = df[list(cols)].rename(columns=cols).apply(pd.to_numeric, errors="coerce")
    out["GLOBAL"] = out[[c for c in ("NA", "EU", "ASIA", "OTHER") if c in out.columns]].sum(axis=1, min_count=1)
    return out


@dataclass
class Inputs:
    """What a run reads. `hold` = the FIRST vintage of each week's holdings by region (what a reader saw at release);
    `vintages` = every stored vintage (long: series_id, report_date, value, release_at) for the point-in-time signals
    — None on the fixture path, where no revision history exists and the Monday rule stands in for release_at."""

    hold: pd.DataFrame
    vintages: pd.DataFrame | None
    flows: pd.DataFrame | None
    price: pd.Series
    meta: dict[str, str]


def _wide_first_vintage(vint: pd.DataFrame, ids: dict[str, str]) -> pd.DataFrame:
    fv = C.first_vintage(vint)
    wide = fv.pivot(index="report_date", columns="series_id", values="value").rename(columns={v: k for k, v in ids.items()})
    return wide.sort_index()


def load_inputs(db: Path | None = None, fixture_dir: Path | None = None, price_csv: Path | None = None, *,
                allow_market_hours: bool = False, tmp_dir: Path | None = None) -> Inputs:
    """Weekly holdings by region (tonnes, week-ending dates) with every vintage, the published weekly flows when stored
    (cross-check), the GC=F close by session, and where each came from. Raises DataNotIngested when the primary table
    is absent. The DuckDB file is read on a snapshot copy that is removed afterwards (never the live file itself)."""
    if db is not None:
        with C.open_snapshot(db, tmp_dir, allow_market_hours=allow_market_hours) as con:
            vint = C.read_gold_series_vintages(con, list(HOLD_IDS.values()))
            hold = _wide_first_vintage(vint, HOLD_IDS)
            flows = None
            try:
                flows = _wide_first_vintage(C.read_gold_series_vintages(con, list(FLOW_IDS.values())), FLOW_IDS)
            except C.DataNotIngested:
                pass
            price = C.read_daily_bars(con, "COMEX_GC_FRONT")
        vint["region"] = vint["series_id"].map({v: k for k, v in HOLD_IDS.items()})
        return Inputs(hold, vint, flows, price,
                      {"holdings": f"gold_series {sorted(HOLD_IDS.values())} ({db}; {len(vint)} vintages, point-in-time)",
                       "price": "gold_daily_bars COMEX_GC_FRONT"})
    if fixture_dir is not None:
        hold = _regionalise(C.load_wgc_fsapi(fixture_dir / "wgc_fsapi_holdings.json", "Weekly")["holdings"])
        flows = None
        fp = fixture_dir / "wgc_fsapi_flows.json"
        if fp.exists():
            flows = _regionalise(C.load_wgc_fsapi(fp, "Weekly")["flows"])
        px = price_csv or (fixture_dir / "yahoo_GC_F_1d.csv")
        if not px.exists():
            px = C.G_STUDY_DATA / "yahoo_GC_F_1d.csv"
        price = C.load_yahoo_daily(px)["close"]
        return Inputs(hold.sort_index(), None, flows, price, {"holdings": str(fixture_dir / "wgc_fsapi_holdings.json"), "price": str(px)})
    raise C.DataNotIngested("gold_series WGC_ETF_HOLD_T_* (weekly holdings by region)")


def crosscheck(hold: pd.DataFrame, flows: pd.DataFrame | None) -> dict[str, Any]:
    """Δ weekly global holdings vs the published weekly global flow where both exist (they must agree within rounding)."""
    if flows is None or "GLOBAL" not in flows.columns:
        return {"weeks": 0, "ok": True, "note": "no published flows stored; Δholdings used unchecked"}
    d = pd.concat([hold["GLOBAL"].diff().rename("dhold"), flows["GLOBAL"].rename("flow")], axis=1).dropna()
    if d.empty:
        return {"weeks": 0, "ok": True, "note": "no overlapping weeks"}
    diff = (d["dhold"] - d["flow"]).abs()
    return {"weeks": len(d), "median_abs_diff_t": round(float(diff.median()), 3), "max_abs_diff_t": round(float(diff.max()), 3),
            "ok": bool(diff.median() <= CROSSCHECK_TOL_T)}


def build_panel(hold: pd.DataFrame, price: pd.Series, horizons: dict[str, int] = HORIZONS, vintages: pd.DataFrame | None = None
                ) -> pd.DataFrame:
    """One row per week-ending Friday W, POINT-IN-TIME. The decision instant `release_at` is the stored first release
    of W's holdings (the `wgc_weekly` rule — the Monday after W, 11:30 IST — when no vintages are given: the fixture
    path, or a row without one); `release` is its date. Each signal is the % change of W's first-vintage holdings over
    the holdings of W−k **as they stood at that instant** (`C.pit_lagged`: the latest vintage with release_at <= the
    decision; a revision published later is never seen). Entry = the first price session whose settlement comes after
    the release instant (Monday's close for an 11:30 IST release; Tuesday if Monday is a holiday); forward returns from
    that entry close; `r_next` between consecutive entries. Descriptive columns (`dhold_*`) use first vintages."""
    h = hold.sort_index()
    p = pd.Series(price, dtype=float).dropna().sort_index()
    pan = pd.DataFrame(index=h.index)
    rule = pd.Series([C.release_rule("wgc_weekly", d) for d in h.index], index=h.index)
    if vintages is not None and len(vintages):
        fv = C.first_vintage(vintages[vintages["series_id"] == HOLD_IDS["GLOBAL"]]).set_index("report_date")["release_at"]
        pan["release_at"] = pd.to_datetime(fv.reindex(h.index))
        pan["release_source"] = np.where(pan["release_at"].notna(), "stored", "rule")
        pan["release_at"] = pan["release_at"].fillna(rule)
    else:
        pan["release_at"], pan["release_source"] = rule, "rule"
    for name, (region, k) in SIGNALS.items():
        if region not in h.columns:
            continue
        if vintages is not None and len(vintages):
            v = vintages[vintages["series_id"] == HOLD_IDS[region]]
            lagged = C.pit_lagged(v, pan["release_at"], k).reindex(h.index)
            pan[name] = C.pct_vs_base(h[region], lagged, MIN_BASE_T)      # the k-th earlier report as known at the decision
        else:
            pan[name] = C.pct_change_guarded(h[region], k, MIN_BASE_T)   # NaN before a region's first 10 t (NA was 0 t until GLD, Nov 2004)
    pan["release"] = pan["release_at"].dt.normalize()
    pv = p.to_numpy()
    n = len(pv)
    pos = C.entry_after_release(p.index, pan["release_at"])
    valid = pos < n
    eidx = np.where(valid, pos, n - 1)
    pan["entry"] = pd.to_datetime(np.where(valid, p.index.to_numpy()[eidx], np.datetime64("NaT")))
    pan["entry_px"] = np.where(valid, pv[eidx], np.nan)
    for name, hs in horizons.items():
        ok = valid & (pos + hs < n)
        hidx = np.where(ok, pos + hs, n - 1)
        pan[f"fwd{name}"] = np.where(ok, (pv[hidx] / pv[eidx] - 1) * 100, np.nan)
    pan["r_next"] = pan["entry_px"].shift(-1) / pan["entry_px"] - 1
    px_W = p.reindex(pan.index, method="ffill")
    pan["px_W"] = px_W
    pan["dpx_week"] = px_W.pct_change() * 100
    for region in REGIONS:
        if region in h.columns:
            pan[f"dhold_{region}"] = h[region].diff()
    return pan


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def run_tests(pan: pd.DataFrame, sig: str, hname: str, *, split: str = SPLIT, min_hist: int = MIN_HIST, label: str | None = None) -> dict[str, Any]:
    lags = WEEKS[hname] - 1
    fwd = pan[f"fwd{hname}"]
    ic = C.rank_ic(pan[sig], fwd, lags)
    h1, h2 = C.halves(pan.index, split)
    ic1, ic2 = C.rank_ic(pan.loc[h1, sig], fwd[h1], lags), C.rank_ic(pan.loc[h2, sig], fwd[h2], lags)
    spread = C.tercile_spread(fwd, C.expanding_tercile(pan[sig], min_hist), lags)
    wf = C.walk_forward_long_flat(pan[sig], fwd, pan["r_next"], WEEKS[hname], periods_per_year=PERIODS_PER_YEAR, min_hist=min_hist,
                                  refit_every=REFIT_EVERY)
    oos_t = wf.get("OOS_t_excess", float("nan"))
    return {"signal": label or sig, "h": hname, "n": ic["n"], "ic": ic["spearman"], "t_ic": ic["t"],
            "ic_h1": ic1["spearman"], "t_h1": ic1["t"], "n_h1": ic1["n"], "ic_h2": ic2["spearman"], "t_h2": ic2["t"], "n_h2": ic2["n"],
            "top_mean": spread["top_mean"], "bottom_mean": spread["bottom_mean"], "spread": spread["spread"], "t_spread": spread["t_nw"],
            "oos_from": wf.get("is_end"), "oos_exposure_pct": wf.get("OOS_exposure_pct"), "oos_excess_pa_pct": wf.get("OOS_excess_vs_scaled_pa_pct"),
            "oos_t": oos_t, "verdict": C.verdict(ic["t"], ic1["t"], ic2["t"], oos_t=oos_t)}


def descriptive(pan: pd.DataFrame, split: str = SPLIT) -> list[dict[str, Any]]:
    """Same-week Spearman of each region's flow vs the week's price change (which region tracks the price)."""
    h1, h2 = C.halves(pan.index, split)
    def rho(col: str, mask: pd.Series | None) -> float:
        d = pan[[col, "dpx_week"]] if mask is None else pan.loc[mask, [col, "dpx_week"]]
        d = d.replace([np.inf, -np.inf], np.nan).dropna()
        return round(float(stats.spearmanr(d[col], d["dpx_week"])[0]), 3) if len(d) > 30 else float("nan")

    rows = []
    for region in REGIONS:
        col = f"dhold_{region}"
        if col not in pan:
            continue
        rows.append({"region": region, "n": int(pan[[col, "dpx_week"]].dropna().shape[0]), "spearman_same_week": rho(col, None),
                     "h1": rho(col, h1), "h2": rho(col, h2)})
    return rows


def negative_controls(pan: pd.DataFrame, seed: int = SEED, placebo_lag: int = PLACEBO_LAG) -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    pan = pan.copy()
    pan["S2_placebo"] = pan["S2"].shift(placebo_lag)
    pan["S2_shuffled"] = rng.permutation(pan["S2"].to_numpy(copy=True))
    rows = []
    for col, name in (("S2_placebo", f"S2 lagged {placebo_lag} weeks (placebo)"), ("S2_shuffled", "S2 shuffled (seed)")):
        for hname in PRIMARY:
            r = run_tests(pan, col, hname, label=name)
            r["control_ok"] = r["verdict"] == C.FAIL          # PLAN: the controls "must FAIL at both horizons" (not merely not-PASS)
            rows.append(r)
    return rows


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def run_study(hold: pd.DataFrame, flows: pd.DataFrame | None, price: pd.Series, out: Path, meta: dict[str, str] | None = None,
              vintages: pd.DataFrame | None = None) -> dict[str, Any]:
    res = out / "results"
    res.mkdir(parents=True, exist_ok=True)
    xc = crosscheck(hold, flows)
    pan = build_panel(hold, price, vintages=vintages)
    sigs = [s for s in SIGNALS if s in pan.columns]
    tests = [run_tests(pan, s, h) for s in sigs for h in HORIZONS]
    desc = descriptive(pan)
    controls = negative_controls(pan)
    pd.DataFrame(tests).to_csv(res / "ic_tests.csv", index=False)
    pd.DataFrame(desc).to_csv(res / "descriptive.csv", index=False)
    pd.DataFrame(controls).to_csv(res / "negative_controls.csv", index=False)
    pan.to_csv(res / "panel.csv")
    primary = [t for t in tests if t["h"] in PRIMARY]
    usable = pan.dropna(subset=["entry"])
    summary: dict[str, Any] = {"study": STUDY, "plan": "reports/gold_program/GS-P2/PLAN.md", "generated": pd.Timestamp.now().isoformat(timespec="minutes"),
                               "inputs": meta or {}, "crosscheck": xc,
                               "sample": {"weeks": len(pan), "with_entry": len(usable), "first": str(pan.index[0].date()),
                                          "last": str(pan.index[-1].date()), "split": SPLIT, "cost_rt_pct": C.COST_RT,
                                          "point_in_time": vintages is not None and len(vintages) > 0,
                                          "release_source": pan["release_source"].value_counts().to_dict(),
                                          "vintages": len(vintages) if vintages is not None else 0},
                               "tests": tests, "descriptive": desc, "negative_controls": controls,
                               "controls_ok": all(c["control_ok"] for c in controls),
                               "any_pass": any(t["verdict"] == C.PASS for t in primary)}
    desc_strong = [r for r in summary["descriptive"] if abs(r["spearman_same_week"]) >= 0.2 and np.sign(r["h1"]) == np.sign(r["h2"])
                   and min(abs(r["h1"]), abs(r["h2"])) >= 0.2]
    summary["description_verdict"] = "PASS as description" if desc_strong else "weak as description"
    summary["overall"] = C.PASS if summary["any_pass"] else (
        C.CONTEXT_ONLY if any(t["verdict"] == C.CONTEXT_ONLY for t in primary) or desc_strong else C.FAIL)
    C.write_json(out / "summary.json", summary)
    (out / "REPORT.md").write_text(report_md(summary), encoding="utf-8")
    (out / "FINDINGS_ROW.md").write_text(findings_rows_md(summary), encoding="utf-8")
    (out / "FINDINGS.md").write_text(findings_md(summary), encoding="utf-8")
    return summary


NAMES = {"S1": "S1 · global 1-wk flow", "S2": "S2 · global 4-wk flow", "S3": "S3 · North America 4-wk", "S4": "S4 · Europe 4-wk",
         "S5": "S5 · Asia 4-wk"}


def _rows(summary: dict[str, Any]) -> list[C.Row]:
    rows = [C.Row(f"{NAMES.get(t['signal'], t['signal'])} → {t['h']}",
                  (f"IC {C.fmt(t['ic'], 3)} (t {C.fmt(t['t_ic'])}); OOS {C.fmt(t['oos_excess_pa_pct'])} %/yr after costs "
                   f"(t {C.fmt(t['oos_t'])})"),
                  f"IC {C.fmt(t['ic_h1'], 3)} (t {C.fmt(t['t_h1'])})", f"IC {C.fmt(t['ic_h2'], 3)} (t {C.fmt(t['t_h2'])})", t["verdict"])
            for t in summary["tests"] if t["h"] in PRIMARY]
    for r in summary["descriptive"]:
        strong = abs(r["spearman_same_week"]) >= 0.2 and np.sign(r["h1"]) == np.sign(r["h2"]) and min(abs(r["h1"]), abs(r["h2"])) >= 0.2
        rows.append(C.Row(f"Same-week Δholdings {r['region']} vs Δ price (description, not a forecast)",
                          f"Spearman {C.fmt(r['spearman_same_week'], 3)} (n {r['n']})", C.fmt(r["h1"], 3), C.fmt(r["h2"], 3),
                          "PASS as description" if strong else "weak as description"))
    return rows


def findings_rows_md(summary: dict[str, Any]) -> str:
    """The 4-column rows to paste into reports/gold_program/FINDINGS.md (shape: scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md)."""
    return C.findings_rows_md(STUDY, _rows(summary))


def findings_md(summary: dict[str, Any]) -> str:
    """The study's own FINDINGS.md in the reports/fii_positioning format, every sentence computed from the summary."""
    s, tests = summary["sample"], [t for t in summary["tests"] if t["h"] in PRIMARY]
    n_fail = sum(t["verdict"] == C.FAIL for t in tests)
    max_t = max(abs(t["t_ic"]) for t in tests) if tests else float("nan")
    desc = sorted(summary["descriptive"], key=lambda r: -abs(r["spearman_same_week"]))
    overall = summary["overall"]
    if summary["any_pass"]:
        verdict_line = ("PASS as a forecast for at least one signal — an exception to the prior; the owner's separate approval is still "
                        "required before any badge changes (PLAN f.5).")
    elif overall == C.CONTEXT_ONLY:
        verdict_line = (f"FAIL as a forecast ({n_fail} of {len(tests)} primary tests; largest |t| {C.fmt(max_t)}); {summary['description_verdict']} "
                        "— last week's flows say who bought, not what comes next.")
    else:
        verdict_line = f"FAIL as a forecast ({n_fail} of {len(tests)} primary tests) and {summary['description_verdict']}."
    bullets = [f"Largest |t| of the rank IC across the {len(tests)} primary tests: {C.fmt(max_t)}; the 13-week secondary horizon is in REPORT.md.",
               "Same-week tracking by region (Spearman of Δholdings vs the week's price change): " +
               "; ".join(f"{r['region']} {C.fmt(r['spearman_same_week'], 2)} ({C.fmt(r['h1'], 2)} / {C.fmt(r['h2'], 2)})" for r in desc) + ".",
               f"Cross-check Δholdings vs the published weekly flows: {summary['crosscheck']}.",
               f"Negative controls (26-week placebo, seeded shuffle) ok: {summary['controls_ok']}.",
               (f"Sample: {s['weeks']} weeks {s['first']} → {s['last']} ({s['with_entry']} with an entry), halves at {s['split']}, costs "
               f"{s['cost_rt_pct']} % per round trip; point-in-time {s['point_in_time']} ({s['vintages']} stored vintages; release "
               f"instants {s['release_source']}); WGC numbers are display-only under O-1 — only statistics are published.")]
    use = ("`ph.etf`'s WGC weekly-flow bars keep the `context` badge ('who bought last week, not what comes next — GS-P2'); no region's "
           "flow becomes an alert or a signal." if overall != C.PASS
           else "do not change any badge from this file alone — PLAN f.5 requires the owner's separate approval.")
    return C.findings_template(STUDY, f"{STUDY} · {TITLE}", C.now_label(),
                               f"{s['weeks']} weekly WGC holdings by region (week ending Friday, published Monday ≈11:30 IST) {s['first']} → "
                               f"{s['last']}, priced on GC=F with entry at Monday's close; Newey-West t for the overlapping 4-week windows; "
                               f"costs {s['cost_rt_pct']} % per round trip.", verdict_line, _rows(summary), bullets, use, SCRIPT)


def report_md(summary: dict[str, Any]) -> str:
    s = summary["sample"]
    cols = ["signal", "h", "n", "ic", "t_ic", "ic_h1", "t_h1", "ic_h2", "t_h2", "top_mean", "bottom_mean", "spread", "t_spread",
            "oos_from", "oos_exposure_pct", "oos_excess_pa_pct", "oos_t", "verdict"]
    parts = [f"# {STUDY} · {TITLE} — result tables\n",
             (f"Generated {summary['generated']} by `{SCRIPT}` from the plan in `PLAN.md`. Weeks {s['weeks']} ({s['first']} → {s['last']}), "
              f"{s['with_entry']} with an entry; halves at {s['split']}; costs {s['cost_rt_pct']} % per round trip. Cross-check Δholdings vs "
              f"published flows: {summary['crosscheck']}.\n"),
             "## Forecast tests (signal known Monday, entry = Monday's close)\n", C.md_table(summary["tests"], cols),
             "\n## Negative controls (must not PASS)\n", C.md_table(summary["negative_controls"], cols + ["control_ok"]),
             "\n## Description: same-week Δholdings vs the week's price change\n",
             C.md_table(summary["descriptive"], ["region", "n", "spearman_same_week", "h1", "h2"]),
             f"\n## Overall: **{summary['overall']}** (controls ok: {summary['controls_ok']})\n"]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="data-service DuckDB file (read on a snapshot copy)")
    ap.add_argument("--fixture-dir", type=Path, default=None,
                    help="directory with wgc_fsapi_holdings.json (+ wgc_fsapi_flows.json): replay check only, never a verdict")
    ap.add_argument("--check-only", action="store_true", help="load and cross-check only; compute no forecast statistic")
    ap.add_argument("--allow-market-hours", action="store_true",
                    help="copy the live DuckDB even inside an IST busy window (07:45–15:45, 18:30–21:15 Mon–Fri); default: refuse, exit 5")
    ap.add_argument("--tmp-dir", type=Path, default=None, help="where the read-only snapshot copy goes (default: a temp dir, removed afterwards)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    try:
        inp = load_inputs(a.db, a.fixture_dir, allow_market_hours=a.allow_market_hours, tmp_dir=a.tmp_dir)
    except C.DataNotIngested as e:
        C.not_ingested(STUDY, "gold_series WGC_ETF_HOLD_T_{GLOBAL,NA,EU,ASIA,OTHER} weekly (SOURCES.md E5) + gold_daily_bars COMEX_GC_FRONT",
                       "run the gold_weekly job and the WGC backfill (PLAN c.3/c.4) after owner decision O-1, then pass --db", str(e))
    except (C.LiveFileBusy, C.SnapshotSpace) as e:
        C.live_busy(STUDY, str(e))
    hold, flows, price, meta = inp.hold, inp.flows, inp.price, inp.meta
    xc = crosscheck(hold, flows)
    if a.check_only or a.db is None:
        # the fixture path is the ingest-replay check; the verdict needs the stored, point-in-time rows (PLAN 'Data', O-1/O-13)
        print(C.Status(STUDY, "checked", detail=f"weeks {len(hold)} ({hold.index[0].date()} → {hold.index[-1].date()}); regions "
                                                 f"{[c for c in REGIONS if c in hold.columns]}; crosscheck {xc}; "
                                                 f"{'verdict requires --db (stored gold_series rows)' if a.db is None else 'check only'}").to_json())
        return 0
    if not xc["ok"]:
        C.insufficient(STUDY, "Δholdings must agree with the published flows within rounding", str(xc))
    if len(hold) < MIN_WEEKS:
        C.insufficient(STUDY, f">= {MIN_WEEKS} weeks of holdings", f"{len(hold)} weeks")
    summary = run_study(hold, flows, price, a.out, meta, vintages=inp.vintages)
    print(C.Status(STUDY, "ran", detail=f"overall {summary['overall']}; controls ok {summary['controls_ok']}; out {a.out}").to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
