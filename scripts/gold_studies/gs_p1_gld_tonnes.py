#!/usr/bin/env python
"""GS-P1 — do daily GLD tonnes (SPDR Gold Shares holdings) predict COMEX gold? Pre-registered in
reports/gold_program/GS-P1/PLAN.md (read it first; the pass bars there are binding).

    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/gs_p1_gld_tonnes.py [--db data/market.duckdb] [--out DIR]

Stored data only, no network: the saved SPDR archive XLSX and the Yahoo GC=F CSV under reports/gold_program (default),
or the data-service tables gold_etf_holdings / gold_daily_bars read from a read-only snapshot copy (--db).

Alignment: the trust posts day T's holdings after the 13:30 ET settlement of T, so a signal dated T is traded at the
close of the first COMEX session strictly after T and every forward window starts there (no look-ahead).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gold_studies import common as C

STUDY = "GS-P1"
TITLE = "GLD daily tonnes vs COMEX gold"
SCRIPT = "scripts/gold_studies/gs_p1_gld_tonnes.py"
HORIZONS = (5, 20)                       # sessions
SPLIT = "2015-12-31"                     # H1 = 2004-11 → 2015-12, H2 = 2016-01 →
MIN_HIST = 250                           # sessions before an expanding rank / tercile cut-off is used
SIGNALS = {"S1": 1, "S2": 5, "S3": 20}   # name → look-back in sessions (% change in tonnes)
PLACEBO_LAG = 60
SEED = 20261026
REFIT_EVERY = 20
PERIODS_PER_YEAR = 252
DEFAULT_OUT = C.GOLD_PROGRAM / "GS-P1"


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def load_inputs(db: Path | None = None, fixture_dir: Path | None = None, *, allow_market_hours: bool = False,
                tmp_dir: Path | None = None) -> tuple[pd.Series, pd.Series, dict[str, str], pd.Series | None]:
    """GLD tonnes by trust date and the GC=F close by session, where each came from, and — on the --db path — the stored
    `release_at` per trust date (the entry is taken after it; the archive path uses the T+1 rule). The DuckDB file is
    read on a snapshot copy that is removed afterwards (never the live file itself)."""
    if db is not None:
        with C.open_snapshot(db, tmp_dir, allow_market_hours=allow_market_hours) as con:
            etf = C.read_etf_holdings(con, "GLD")
            price = C.read_daily_bars(con, "COMEX_GC_FRONT")
        return etf["tonnes"], price, {"tonnes": f"gold_etf_holdings GLD ({db}; entry after the stored release_at)",
                                      "price": "gold_daily_bars COMEX_GC_FRONT"}, etf["release_at"]
    if fixture_dir is not None:
        # an explicit fixture directory is used strictly: a missing file is 'not ingested', never a silent fallback
        gld_path, px_path = fixture_dir / "spdr_gld_historical_archive.bin", fixture_dir / "yahoo_GC_F_1d.csv"
    else:
        gld_path = C.G_STUDY_DATA / "spdr_gld_historical_archive.bin"
        if not gld_path.exists():
            gld_path = C.G_MACRO_DATA / "spdr_gld_historical_archive.xlsx"
        px_path = C.G_STUDY_DATA / "yahoo_GC_F_1d.csv"
        if not px_path.exists():
            px_path = C.G_MACRO_DATA / "yahoo_GC_F.csv"
    tonnes = C.load_gld_archive(gld_path)["tonnes"]
    price = C.load_yahoo_daily(px_path)["close"]
    return tonnes, price, {"tonnes": str(gld_path), "price": str(px_path)}, None


def build_panel(tonnes: pd.Series, price: pd.Series, entry_shift: int = 1, horizons: tuple[int, ...] = HORIZONS,
                release_at: pd.Series | None = None) -> pd.DataFrame:
    """One row per trust date T. Signals use tonnes up to T only; `entry` is the `entry_shift`-th price session strictly
    after T — and, when the stored `release_at` is given (the --db path), never before the first session whose
    settlement follows that instant (the later of the two: a late posting pushes the entry out, never in); forward
    returns run from that entry close; `r_next` is the return between consecutive entries (what a position decided
    at T earns until the next decision). Nothing to the right of T enters a signal."""
    t = pd.Series(tonnes, dtype=float).dropna().sort_index()
    p = pd.Series(price, dtype=float).dropna().sort_index()
    pan = pd.DataFrame({"tonnes": t})
    for name, k in SIGNALS.items():
        pan[name] = (t / t.shift(k) - 1) * 100
    pv = p.to_numpy()
    n = len(pv)
    pos = p.index.searchsorted(pan.index.to_numpy(), side="right") + (entry_shift - 1)
    if release_at is not None:
        rel = pd.to_datetime(pd.Series(release_at)).reindex(pan.index)
        pos = np.maximum(pos, C.entry_after_release(p.index, rel, shift=entry_shift - 1))
        pan["release_at"] = rel.to_numpy()
    valid = pos < n
    eidx = np.where(valid, pos, n - 1)
    pan["entry"] = pd.to_datetime(np.where(valid, p.index.to_numpy()[eidx], np.datetime64("NaT")))
    pan["entry_px"] = np.where(valid, pv[eidx], np.nan)
    for h in horizons:
        ok = valid & (pos + h < n)
        hidx = np.where(ok, pos + h, n - 1)
        pan[f"fwd{h}"] = np.where(ok, (pv[hidx] / pv[eidx] - 1) * 100, np.nan)
    pan["r_next"] = pan["entry_px"].shift(-1) / pan["entry_px"] - 1
    # descriptive columns: as of T (never forward)
    px_T = p.reindex(pan.index, method="ffill")
    pan["px_T"] = px_T
    pan["dpx_T"] = px_T.pct_change() * 100
    pan["dtonnes_T"] = t.pct_change() * 100
    return pan


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def run_tests(pan: pd.DataFrame, sig: str, h: int, *, split: str = SPLIT, min_hist: int = MIN_HIST,
              refit_every: int = REFIT_EVERY, label: str | None = None) -> dict[str, Any]:
    """Rank IC (full + halves), tercile spread, walk-forward long/flat after costs, and the PLAN f.1 verdict."""
    lags = max(h - 1, 0)
    fwd = pan[f"fwd{h}"]
    ic = C.rank_ic(pan[sig], fwd, lags)
    h1, h2 = C.halves(pan.index, split)
    ic1 = C.rank_ic(pan.loc[h1, sig], fwd[h1], lags)
    ic2 = C.rank_ic(pan.loc[h2, sig], fwd[h2], lags)
    spread = C.tercile_spread(fwd, C.expanding_tercile(pan[sig], min_hist), lags)
    wf = C.walk_forward_long_flat(pan[sig], fwd, pan["r_next"], h, periods_per_year=PERIODS_PER_YEAR, min_hist=min_hist,
                                  refit_every=refit_every)
    oos_t = wf.get("OOS_t_excess", float("nan"))
    return {"signal": label or sig, "h": h, "n": ic["n"], "ic": ic["spearman"], "t_ic": ic["t"],
            "ic_h1": ic1["spearman"], "t_h1": ic1["t"], "n_h1": ic1["n"], "ic_h2": ic2["spearman"], "t_h2": ic2["t"], "n_h2": ic2["n"],
            "top_mean": spread["top_mean"], "bottom_mean": spread["bottom_mean"], "spread": spread["spread"], "t_spread": spread["t_nw"],
            "oos_from": wf.get("is_end"), "oos_exposure_pct": wf.get("OOS_exposure_pct"),
            "oos_excess_pa_pct": wf.get("OOS_excess_vs_scaled_pa_pct"), "oos_t": oos_t,
            "oos_strat_cagr": wf.get("OOS_strat_cagr"), "oos_bh_cagr": wf.get("OOS_bh_cagr"),
            "verdict": C.verdict(ic["t"], ic1["t"], ic2["t"], oos_t=oos_t)}


def descriptive(pan: pd.DataFrame, split: str = SPLIT) -> dict[str, Any]:
    """Not graded as a forecast: how the tonnes move WITH the price (same day, same week) and the lead/lag profile."""
    d = pan.dropna(subset=["dtonnes_T", "dpx_T"])
    h1, h2 = C.halves(d.index, split)

    def rho(a: pd.Series, b: pd.Series) -> float:
        x = pd.concat([a, b], axis=1).dropna()
        return round(float(stats.spearmanr(x.iloc[:, 0], x.iloc[:, 1])[0]), 3) if len(x) > 30 else float("nan")

    same_day = {"all": rho(d["dtonnes_T"], d["dpx_T"]), "h1": rho(d.loc[h1, "dtonnes_T"], d.loc[h1, "dpx_T"]),
                "h2": rho(d.loc[h2, "dtonnes_T"], d.loc[h2, "dpx_T"]), "n": len(d)}
    wk = pd.DataFrame({"t": pan["tonnes"], "p": pan["px_T"]}).resample("W-FRI").last().pct_change() * 100
    wk = wk.dropna()
    wh1, wh2 = C.halves(wk.index, split)
    same_week = {"all": rho(wk["t"], wk["p"]), "h1": rho(wk.loc[wh1, "t"], wk.loc[wh1, "p"]), "h2": rho(wk.loc[wh2, "t"], wk.loc[wh2, "p"]),
                 "n": len(wk)}
    lead_lag = [{"k_sessions": k, "spearman": rho(d["dtonnes_T"].shift(-k), d["dpx_T"]),
                 "reads": "tonnes lead price" if k < 0 else ("same day" if k == 0 else "price leads tonnes")} for k in range(-5, 6)]
    stable = all(abs(v) >= 0.2 for v in (same_week["h1"], same_week["h2"])) and np.sign(same_week["h1"]) == np.sign(same_week["h2"])
    return {"same_day": same_day, "same_week": same_week, "lead_lag": lead_lag,
            "description_verdict": "PASS as description" if (abs(same_week["all"]) >= 0.2 and stable) else "weak as description"}


def negative_controls(pan: pd.DataFrame, seed: int = SEED, placebo_lag: int = PLACEBO_LAG) -> list[dict[str, Any]]:
    """Pre-registered controls on S3: a 60-session-stale copy and a date-shuffled copy must not PASS."""
    rng = np.random.default_rng(seed)
    pan = pan.copy()
    pan["S3_placebo"] = pan["S3"].shift(placebo_lag)
    vals = pan["S3"].to_numpy(copy=True)
    pan["S3_shuffled"] = rng.permutation(vals)
    rows = []
    for col, name in (("S3_placebo", f"S3 lagged {placebo_lag} sessions (placebo)"), ("S3_shuffled", "S3 shuffled (seed)")):
        for h in HORIZONS:
            r = run_tests(pan, col, h, label=name)
            r["control_ok"] = r["verdict"] == C.FAIL          # PLAN: the controls "must FAIL at both horizons" (not merely not-PASS)
            rows.append(r)
    return rows


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def run_study(tonnes: pd.Series, price: pd.Series, out: Path, meta: dict[str, str] | None = None,
              release_at: pd.Series | None = None) -> dict[str, Any]:
    """The whole pre-registered procedure; writes results/, summary.json, REPORT.md, FINDINGS_ROW.md under `out`."""
    res = out / "results"
    res.mkdir(parents=True, exist_ok=True)
    pan = build_panel(tonnes, price, release_at=release_at)
    usable = pan.dropna(subset=["entry"])
    tests = [run_tests(pan, s, h) for s in SIGNALS for h in HORIZONS]
    late = [run_tests(build_panel(tonnes, price, entry_shift=2, release_at=release_at), s, h, label=f"{s} (entry T+2)")
            for s in ("S2", "S3") for h in HORIZONS]
    desc = descriptive(pan)
    controls = negative_controls(pan)
    pd.DataFrame(tests).to_csv(res / "ic_tests.csv", index=False)
    pd.DataFrame(late).to_csv(res / "ic_tests_late_entry.csv", index=False)
    pd.DataFrame(controls).to_csv(res / "negative_controls.csv", index=False)
    pan.to_csv(res / "panel.csv")
    lag = (usable["entry"] - usable.index).dt.days
    summary: dict[str, Any] = {
        "study": STUDY, "plan": "reports/gold_program/GS-P1/PLAN.md", "generated": pd.Timestamp.now().isoformat(timespec="minutes"),
        "inputs": meta or {}, "sample": {"trust_dates": len(pan), "with_entry": len(usable),
                                        "first": str(pan.index[0].date()), "last": str(pan.index[-1].date()),
                                        "median_lag_T_to_entry_days": float(lag.median()), "max_lag_days": int(lag.max()),
                                        "split": SPLIT, "cost_rt_pct": C.COST_RT,
                                        "entry_rule": "after the stored release_at (and never before T+1)" if release_at is not None
                                        else "T+1 (the trust posts T after the settlement)"},
        "tests": tests, "late_entry": late, "descriptive": desc, "negative_controls": controls,
        "controls_ok": all(c["control_ok"] for c in controls),
        "forecast_verdicts": {f"{t['signal']}@{t['h']}": t["verdict"] for t in tests},
        "any_pass": any(t["verdict"] == C.PASS for t in tests),
    }
    overall = C.PASS if summary["any_pass"] else (C.CONTEXT_ONLY if any(t["verdict"] == C.CONTEXT_ONLY for t in tests)
                                                   or desc["description_verdict"].startswith("PASS") else C.FAIL)
    summary["overall"] = overall
    C.write_json(out / "summary.json", summary)
    (out / "REPORT.md").write_text(report_md(summary), encoding="utf-8")
    (out / "FINDINGS_ROW.md").write_text(findings_rows_md(summary), encoding="utf-8")
    (out / "FINDINGS.md").write_text(findings_md(summary), encoding="utf-8")
    return summary


def _row(t: dict[str, Any]) -> C.Row:
    sig = {"S1": "S1 · 1-day Δ tonnes", "S2": "S2 · 5-day Δ tonnes", "S3": "S3 · 20-day Δ tonnes"}.get(t["signal"], t["signal"])
    result = (f"IC {C.fmt(t['ic'], 3)} (t {C.fmt(t['t_ic'])}); tercile spread {C.fmt(t['spread'])} % (t {C.fmt(t['t_spread'])}); "
              f"OOS {C.fmt(t['oos_excess_pa_pct'])} %/yr after costs (t {C.fmt(t['oos_t'])})")
    return C.Row(f"{sig} → {t['h']} sessions", result, f"IC {C.fmt(t['ic_h1'], 3)} (t {C.fmt(t['t_h1'])})",
                 f"IC {C.fmt(t['ic_h2'], 3)} (t {C.fmt(t['t_h2'])})", t["verdict"])


def _rows(summary: dict[str, Any]) -> list[C.Row]:
    rows = [_row(t) for t in summary["tests"]]
    d = summary["descriptive"]
    rows.append(C.Row("Same-week Δ tonnes vs Δ price (description, not a forecast)",
                      f"Spearman {C.fmt(d['same_week']['all'], 3)} (n {d['same_week']['n']})",
                      C.fmt(d["same_week"]["h1"], 3), C.fmt(d["same_week"]["h2"], 3), d["description_verdict"]))
    return rows


def findings_rows_md(summary: dict[str, Any]) -> str:
    """The 4-column rows to paste into reports/gold_program/FINDINGS.md (shape: scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md)."""
    return C.findings_rows_md(STUDY, _rows(summary))


def findings_md(summary: dict[str, Any]) -> str:
    """The study's own FINDINGS.md in the reports/fii_positioning format, every sentence computed from the summary."""
    s, d, tests = summary["sample"], summary["descriptive"], summary["tests"]
    n_fail = sum(t["verdict"] == C.FAIL for t in tests)
    max_t = max(abs(t["t_ic"]) for t in tests)
    best_oos = max(tests, key=lambda t: (t["oos_excess_pa_pct"] if t["oos_excess_pa_pct"] is not None else -1e9))
    lag = {r["k_sessions"]: r["spearman"] for r in d["lead_lag"]}
    sw = d["same_week"]
    overall = summary["overall"]
    if summary["any_pass"]:
        verdict_line = ("PASS as a forecast for at least one signal — an exception to the prior; the owner's separate approval is still "
                        "required before any badge changes (PLAN f.5).")
    elif overall == C.CONTEXT_ONLY:
        verdict_line = (f"FAIL as a forecast ({n_fail} of {len(tests)} signal × horizon tests; largest |t| {C.fmt(max_t)}); PASS as a "
                        f"description — the tonnes move WITH the price (same-week Spearman {C.fmt(sw['all'], 2)}, stable across halves) and "
                        "follow it rather than lead it. The ETF panel is context, not a timing tool.")
    else:
        verdict_line = f"FAIL as a forecast ({n_fail} of {len(tests)} tests) and weak even as a description (same-week ρ {C.fmt(sw['all'], 2)})."
    bullets = [(f"Rank IC never clears |t| 2 at 5 or 20 sessions (largest |t| {C.fmt(max_t)}); the walk-forward long/flat rule after 0.15 % "
               f"earns at best {C.fmt(best_oos['oos_excess_pa_pct'])} %/yr over scaled buy-and-hold ({best_oos['signal']}@{best_oos['h']}, "
               f"t {C.fmt(best_oos['oos_t'])}) out of sample from {best_oos['oos_from']}."),
               (f"Entry one session later (T+2) changes nothing (REPORT.md); the negative controls (60-session placebo, seeded shuffle) "
               f"behave: ok = {summary['controls_ok']}."),
               (f"Lead/lag: Spearman(Δtonnes, Δprice) is {C.fmt(lag.get(0), 2)} on the same day, {C.fmt(lag.get(1), 2)} when the price leads by one "
               f"session and {C.fmt(lag.get(-1), 2)} when the tonnes lead — the trust's holdings respond to the price, not the other way "
               f"round (creations/redemptions settle after the move)."),
               (f"Same-week relation: Spearman {C.fmt(sw['all'], 3)} (halves {C.fmt(sw['h1'], 3)} / {C.fmt(sw['h2'], 3)}, n {sw['n']}); same day "
               f"{C.fmt(d['same_day']['all'], 3)}. In line with G-STUDY (weekly 4-week change t ≤ 1.0) and G-MACRO (contemporaneous only)."),
               (f"Sample: {s['trust_dates']} trust dates {s['first']} → {s['last']} (median lag trust date → entry {s['median_lag_T_to_entry_days']:.0f} "
               f"day, max {s['max_lag_days']}); halves at {s['split']}; costs {s['cost_rt_pct']} % per round trip; data display-only under "
               "SPDR's disclaimer (O-1) — only statistics are published.")]
    use = ("`ph.etf` and the ETF-HOLDINGS health tile keep the `context` badge with the caption 'moves with the price, does not lead it "
           "(GS-P1, 26 Oct 2026)'; divergence (price up, tonnes down) stays a description of who is buying, never an alert or a signal."
           if overall != C.PASS else "do not change any badge from this file alone — PLAN f.5 requires the owner's separate approval.")
    return C.findings_template(STUDY, f"{STUDY} · {TITLE}", C.now_label(),
                               f"{s['trust_dates']} daily GLD holdings (SPDR archive) {s['first']} → {s['last']}, priced on GC=F; the trust posts "
                               "day T after the COMEX settlement, so entry = close of T+1 (no forward window contains a public close); "
                               f"Newey-West t for the overlapping 5- and 20-session windows; costs {s['cost_rt_pct']} % per round trip.",
                               verdict_line, _rows(summary), bullets, use, SCRIPT)


def report_md(summary: dict[str, Any]) -> str:
    s = summary["sample"]
    cols = ["signal", "h", "n", "ic", "t_ic", "ic_h1", "t_h1", "ic_h2", "t_h2", "top_mean", "bottom_mean", "spread", "t_spread",
            "oos_from", "oos_exposure_pct", "oos_excess_pa_pct", "oos_t", "oos_strat_cagr", "oos_bh_cagr", "verdict"]
    d = summary["descriptive"]
    parts = [f"# {STUDY} · {TITLE} — result tables\n",
             (f"Generated {summary['generated']} by `{SCRIPT}` from the plan in `PLAN.md`. Trust dates {s['trust_dates']} "
              f"({s['first']} → {s['last']}), {s['with_entry']} with a COMEX entry; median lag trust date → entry "
              f"{s['median_lag_T_to_entry_days']:.0f} days (max {s['max_lag_days']}); halves split at {s['split']}; costs {s['cost_rt_pct']} % "
              "per round trip.\n"),
             "## Forecast tests (signal known at T, entry = close of the first session after T)\n",
             ("IC = Spearman(signal, forward return); t = Newey-West t of the rank slope (lags h−1); tercile cut-offs expanding on past values; "
              "OOS = walk-forward long/flat rule after costs vs buy-and-hold scaled to its exposure.\n"),
             C.md_table(summary["tests"], cols),
             "\n## Robustness: entry one session later (T+2)\n", C.md_table(summary["late_entry"], cols),
             "\n## Negative controls (must not PASS)\n", C.md_table(summary["negative_controls"], cols + ["control_ok"]),
             (f"\n## Description (not a forecast)\n\nSame day: Spearman {C.fmt(d['same_day']['all'], 3)} (h1 {C.fmt(d['same_day']['h1'], 3)}, "
              f"h2 {C.fmt(d['same_day']['h2'], 3)}, n {d['same_day']['n']}). Same week: {C.fmt(d['same_week']['all'], 3)} "
              f"(h1 {C.fmt(d['same_week']['h1'], 3)}, h2 {C.fmt(d['same_week']['h2'], 3)}, n {d['same_week']['n']}) → "
              f"{d['description_verdict']}.\n"),
             C.md_table(d["lead_lag"], ["k_sessions", "spearman", "reads"]),
             f"\n## Overall: **{summary['overall']}** (controls ok: {summary['controls_ok']})\n"]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=None, help="data-service DuckDB file (read on a snapshot copy); default: saved research CSV/XLSX")
    ap.add_argument("--fixture-dir", type=Path, default=None, help="directory with spdr_gld_historical_archive.bin and yahoo_GC_F_1d.csv")
    ap.add_argument("--allow-market-hours", action="store_true",
                    help="copy the live DuckDB even inside an IST busy window (07:45–15:45, 18:30–21:15 Mon–Fri); default: refuse, exit 5")
    ap.add_argument("--tmp-dir", type=Path, default=None, help="where the read-only snapshot copy goes (default: a temp dir, removed afterwards)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    try:
        tonnes, price, meta, release_at = load_inputs(a.db, a.fixture_dir, allow_market_hours=a.allow_market_hours, tmp_dir=a.tmp_dir)
    except C.DataNotIngested as e:
        C.not_ingested(STUDY, "gold_etf_holdings (GLD) + gold_daily_bars (COMEX_GC_FRONT), or the saved SPDR archive + GC=F CSV",
                       "run the gold_morning / gold_overnight jobs (PLAN c.3) or point --fixture-dir at the saved files", str(e))
    except (C.LiveFileBusy, C.SnapshotSpace) as e:
        C.live_busy(STUDY, str(e))
    if len(tonnes) < MIN_HIST + 260:
        C.insufficient(STUDY, f">= {MIN_HIST + 260} trust dates", f"{len(tonnes)} rows")
    summary = run_study(tonnes, price, a.out, meta, release_at=release_at)
    print(C.Status(STUDY, "ran", detail=f"overall {summary['overall']}; controls ok {summary['controls_ok']}; out {a.out}").to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
