"""Gold studies — reproduce the headline numbers the FINDINGS rely on, and unit-test the study machinery (PLAN §h T4).

Two layers:

* **slow** (``pytest.mark.slow``; ~15 s together; they SKIP when the untracked research data under
  ``reports/gold_program`` is absent, e.g. in CI): re-run ``G-STUDY/g_study.py`` on its saved data into a temp dir and
  assert same-week Spearman(Δ MM net, price) = 0.65 ± 0.02, 0 of 69 walk-forward rules with OOS t ≥ 2, Dec/Jan the only
  months with t ≥ 2; re-run ``G-MACRO/g_study.py``'s H2 (weekly dollar beta ≈ −1, |t| ≥ 2 in every regime) and H3 (no
  month passes both halves); the G-INDIA AMFI ρ(flow → next) = 0.115 ± 0.02; and the GS-P1 / GS-P4 scripts, asserting the
  verdicts their FINDINGS.md publish.
* **fast** (< 5 s, synthetic data, always run): a 200-week smoke slice of G-STUDY; ``scripts/gold_studies/common.py``
  (Newey-West, walk-forward ranks, the PLAN f.1 verdict rule, no-look-ahead forward returns, ±inf hygiene); each study's
  honest exits (3 = data not yet ingested, 4 = insufficient history), its no-look-ahead alignment, a planted-signal positive
  control (the machinery can detect a real effect) and the pre-registered negative controls; GS-P2's point-in-time read
  against a temporary DuckDB (never ``data/market.duckdb``).

Nothing here touches the live stack, writes under ``data/``, or calls the network. Deselect the slow layer with
``-m "not slow"``.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.append(str(ROOT / "scripts"))          # `gold_studies` is a package under scripts/; appended, never shadowing

from gold_studies import common as C
from gold_studies import g_study_2_oi_quadrant as GS2
from gold_studies import gs_p1_gld_tonnes as P1
from gold_studies import gs_p2_wgc_flows as P2
from gold_studies import gs_p4_seasonality_in_inr as P4

GP = ROOT / "reports" / "gold_program"
G_STUDY = GP / "G-STUDY"
G_MACRO = GP / "G-MACRO"
G_INDIA = GP / "G-INDIA"
slow = pytest.mark.slow


def _needs(*paths: Path) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"research data not on this machine: {missing[:3]}")


def _load(path: Path, name: str) -> types.ModuleType:
    """Import a research script by path under a unique module name (both agents' scripts are called g_study.py)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        spec.loader.exec_module(mod)
    return mod


def _status(capsys) -> dict:
    out = capsys.readouterr().out.strip().splitlines()
    return json.loads(out[-1])


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# T4 · slow: re-run the research scripts on their saved data
# ─────────────────────────────────────────────────────────────────────────────────────────────────

@slow
def test_g_study_reproduces_headline_numbers(tmp_path: Path) -> None:
    data = G_STUDY / "data"
    _needs(G_STUDY / "g_study.py", *(data / f"cftc_socrata_{k}_gold_088691.csv" for k in ("disagg_fut", "disagg_com", "legacy_fut", "legacy_com")),
           data / "yahoo_GC_F_1d.csv", data / "spdr_gld_historical_archive.bin", data / "fred_DFII10.csv")
    m = _load(G_STUDY / "g_study.py", "g_study_cot")
    m.ROOT, m.RES, m.FIG = tmp_path, tmp_path / "results", tmp_path / "figures"      # outputs to tmp; DATA stays the saved data
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.main()
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    mm = next(r for r in summary["descriptive"]["contemporaneous"] if r["series"] == "Managed-money net")
    assert abs(mm["spearman_same_week"] - 0.65) <= 0.02
    assert abs(mm["spearman_NEXT_week"]) <= 0.05
    for row in summary["descriptive"]["stability"]:
        assert row["spearman_same_week"] >= 0.55 and abs(row["spearman_NEXT_week"]) <= 0.10
    learned = pd.read_csv(tmp_path / "results" / "walk_forward.csv")
    fixed = pd.read_csv(tmp_path / "results" / "walk_forward_fixed_direction.csv")
    assert len(learned) + len(fixed) == 69
    oos_t = pd.concat([learned["OOS_t_excess"], fixed["OOS_t_excess"]])
    assert int((oos_t >= 2).sum()) == 0
    assert int((oos_t <= -2).sum()) == 3
    seas = pd.read_csv(tmp_path / "results" / "seasonality.csv")
    assert set(seas.loc[seas["t_vs_all"] >= 2, "month"]) == {"Dec", "Jan"}
    assert summary["panel"]["disagg_reports"] == 1063 and summary["panel"]["disagg_with_entry"] == 1059
    assert summary["seasonality_walk_forward"]["t_excess"] < 2


@slow
def test_g_macro_h2_dollar_beta_and_h3_no_month(tmp_path: Path) -> None:
    data = G_MACRO / "data"
    _needs(G_MACRO / "g_study.py", data / "fred_DFII10.csv", data / "yahoo_DX-Y_NYB.csv", data / "yahoo_GC_F.csv", data / "worldbank_cmo_monthly.csv")
    m = _load(G_MACRO / "g_study.py", "g_study_macro")
    m.TAB, m.HERE = tmp_path, tmp_path
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m.study_regressions()
        m.study_seasonality()
    weekly = [r for r in m.OUT["changes"] if r["horizon"] == "weekly"]
    assert {r["period"] for r in weekly} >= {"2003-2009", "2010-2021", "2022-2026"}
    for r in weekly:
        assert r["dxy_t"] <= -2, r                      # H2: |t| ≥ 2 in every regime
        assert -1.3 <= r["dxy_beta"] <= -0.8, r          # beta around −1 (−1.23 / −1.02 / −0.97 / −1.01 in the report)
    assert m.OUT["H3_months_passing_both_halves"] == []


def test_g_india_amfi_flow_rho_reproduces() -> None:
    csv = G_INDIA / "scratch" / "amfi_gold_etf_study.csv"
    _needs(csv)
    from scipy import stats

    d = pd.read_csv(csv)[["flow_pct_aum", "ret_next"]].dropna()
    assert abs(float(stats.spearmanr(d["flow_pct_aum"], d["ret_next"])[0]) - 0.115) <= 0.02


@slow
def test_gs_p1_reproduces_findings(tmp_path: Path) -> None:
    _needs(G_STUDY / "data" / "spdr_gld_historical_archive.bin", G_STUDY / "data" / "yahoo_GC_F_1d.csv")
    assert P1.main(["--out", str(tmp_path)]) == 0
    s = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert all(v == C.FAIL for v in s["forecast_verdicts"].values()) and len(s["forecast_verdicts"]) == 6
    assert max(abs(t["t_ic"]) for t in s["tests"]) < 2
    sw = s["descriptive"]["same_week"]
    assert abs(sw["all"] - 0.294) <= 0.02 and sw["h1"] >= 0.2 and sw["h2"] >= 0.2
    assert s["descriptive"]["description_verdict"].startswith("PASS")
    assert s["controls_ok"] and all(c["verdict"] == C.FAIL for c in s["negative_controls"])   # PLAN: controls must FAIL, not merely not-PASS
    assert s["overall"] == C.CONTEXT_ONLY
    text = (tmp_path / "FINDINGS.md").read_text(encoding="utf-8")
    assert "**Verdict: FAIL as a forecast" in text and "- **Use:**" in text and "| Signal | Result (full sample) | Both halves |" in text
    rows = (tmp_path / "FINDINGS_ROW.md").read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 7 and all(len(C.table_cells(r)) == 4 for r in rows)                    # the aggregate (4-column) shape
    published = GP / "GS-P1" / "summary.json"
    if published.exists():
        assert json.loads(published.read_text(encoding="utf-8"))["forecast_verdicts"] == s["forecast_verdicts"]


@slow
def test_gs_p4_reproduces_findings(tmp_path: Path) -> None:
    d = G_MACRO / "data"
    _needs(d / "worldbank_cmo_monthly.csv", d / "yahoo_GC_F.csv", d / "fred_DEXINUS.csv")
    assert P4.main(["--out", str(tmp_path)]) == 0
    s = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    nc = s["negative_controls"]
    # the pre-registered vs-zero statistic is void on this series: its own shuffle control passes far too often (drift, not calendar)
    assert s["pre_registered_statistic_void"] and nc["null_pass_rate_pre"] > 0.10 and nc["null_months_ge2_pre"] > 2
    assert s["context_months_pre_registered_statistic"] == ["Jan", "Feb", "Aug", "Sep"]      # the first draft's "CONTEXT-ONLY" months
    # drift-adjusted: nothing passes, the controls behave, every hypothesis is at most CONTEXT-ONLY
    assert s["pass_months"] == [] and s["controls_ok"] and nc["null_pass_rate_adj"] <= 0.10
    hyp = {h["hypothesis"].split(" ")[0]: h["verdict"] for h in s["hypotheses"]}
    assert set(hyp) == {"H1", "H1b", "H2"} and all(v in (C.FAIL, C.CONTEXT_ONLY) for v in hyp.values()) and hyp["H1b"] == C.FAIL
    assert s["walk_forward_tradable"]["verdict"] == C.FAIL and s["walk_forward_tradable"]["t"] < 2
    assert s["walk_forward_tradable"]["cost_per_switch_pct"] == 0.15
    assert s["overall"] in (C.FAIL, C.CONTEXT_ONLY)
    # the study-level verdict names both statistics: the pre-registered one is VOID by the plan's own rule, the post-hoc one is capped
    assert s["verdict_pre_registered"] == C.VOID
    assert s["overall_label"] == f"VOID (pre-registered statistic) / {s['overall']} (post-hoc drift-adjusted, capped)"
    assert s["null_seed_set"] == "seeds 20261027–20261126"                      # one figure, one seed set (PLAN N4 lists the probes)
    for r in s["months_inr_long"]:
        assert r["verdict"] != C.PASS and r["verdict_adj"] != C.PASS                 # no month passes both halves once drift is removed
    text = (tmp_path / "FINDINGS.md").read_text(encoding="utf-8")
    assert "**Verdict: VOID (pre-registered statistic) / FAIL (post-hoc drift-adjusted, capped) — drift, not a calendar." in text
    assert "is VOID by the plan's own control rule" in text and "festival months do not pass" in text
    rows = (tmp_path / "FINDINGS_ROW.md").read_text(encoding="utf-8").strip().splitlines()
    assert all(len(C.table_cells(r)) == 4 and r.startswith("| GS-P4 · ") for r in rows)
    assert C.table_cells(rows[-1])[-1].startswith("**VOID (PLAN N4") and "\\|t\\|" in rows[3]   # pipes inside a cell are escaped


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# fast: a 200-week smoke slice of G-STUDY
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_g_study_smoke_200_weeks() -> None:
    data = G_STUDY / "data"
    _needs(G_STUDY / "g_study.py", data / "cftc_socrata_disagg_fut_gold_088691.csv", data / "yahoo_GC_F_1d.csv")
    m = _load(G_STUDY / "g_study.py", "g_study_cot_smoke")
    cot = m.load_cot("disagg_fut").tail(200)
    price = m.load_yahoo("GC_F")["close"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        p = m.add_signals(m.build_panel(cot, price, {}), "disagg")
        desc = m.descriptive(p)
    assert len(p) == 200
    ok = p.dropna(subset=["entry"])
    assert len(ok) >= 195                                             # a handful of unverifiable releases are excluded
    assert (ok["entry"] > ok["release"]).all() and (ok["entry"] > ok.index).all()   # entry strictly after the release
    assert 2 <= ok["lag_days"].median() <= 7 and ok["lag_days"].max() <= 51
    mm = next(r for r in desc["contemporaneous"] if r["series"] == "Managed-money net")
    assert mm["spearman_same_week"] >= 0.4 and abs(mm["spearman_NEXT_week"]) < 0.25
    assert m.release_date(pd.Timestamp("2026-10-20")) == pd.Timestamp("2026-10-23")
    xmas = m.release_date(pd.Timestamp("2025-12-23"))
    assert xmas is not None and xmas.weekday() == 0 and xmas > pd.Timestamp("2025-12-26")   # a holiday in the week → Monday


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# fast: common.py
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_newey_west_without_lags_is_the_plain_t() -> None:
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(0.1, 1.0, 2000))
    nw, plain = C.newey_west_t(x, 0), C.plain_t(x)
    assert abs(nw / plain - 1) < 0.01                                 # population vs sample variance only
    assert C.newey_west_t(x, 4) != nw and np.isfinite(C.newey_west_t(x, 4))


def test_forward_returns_start_at_the_close_after_the_signal() -> None:
    p = pd.Series(np.arange(1, 21, dtype=float), index=pd.bdate_range("2024-01-01", periods=20))
    f = C.forward_returns(p, (5,), entry_shift=1)
    i = 3
    assert f["entry_px"].iloc[i] == p.iloc[i + 1]
    assert abs(f["fwd5"].iloc[i] - (p.iloc[i + 6] / p.iloc[i + 1] - 1) * 100) < 1e-12
    assert abs(f["r_next"].iloc[i] - (p.iloc[i + 2] / p.iloc[i + 1] - 1)) < 1e-12
    assert f["fwd5"].iloc[-6:].isna().all()                            # no window may run past the last close


def test_expanding_ranks_use_strictly_earlier_values_only() -> None:
    rng = np.random.default_rng(1)
    s = pd.Series(rng.normal(size=300))
    a = C.expanding_percentile(s, 20)
    s2 = s.copy()
    s2.iloc[-1] = 1e9                                                 # a future shock must not move any earlier rank
    b = C.expanding_percentile(s2, 20)
    assert a.iloc[:-1].equals(b.iloc[:-1]) and b.iloc[-1] == 1.0 and a.iloc[:20].isna().all()
    t = C.expanding_tercile(s, 20)
    assert t.iloc[:20].isna().all() and set(t.dropna().unique()) <= {"top", "middle", "bottom"}


@pytest.mark.parametrize("args, expected", [
    ((3.0, 2.5, 2.2, None), C.PASS),
    ((3.0, 2.5, 2.2, 2.4), C.PASS),
    ((3.0, 2.5, 2.2, 1.0), C.CONTEXT_ONLY),       # the traded leg does not pay → not a signal
    ((3.0, 2.5, 2.2, -2.4), C.CONTEXT_ONLY),      # the traded leg LOSES at t −2.4 → never a PASS (oos_t is signed)
    ((3.0, 2.5, -2.2, None), C.CONTEXT_ONLY),     # sign flips between halves
    ((3.0, 1.0, 2.2, None), C.CONTEXT_ONLY),      # one half below the bar
    ((1.5, 2.5, 2.2, None), C.FAIL),              # full sample below the bar
    ((-3.0, -2.5, -2.2, None), C.PASS),           # a STATISTIC is sign-free (an IC, a cell mean): the direction is reported
    ((float("nan"), 2.5, 2.2, None), C.FAIL),
    ((3.0, float("nan"), 2.2, None), C.CONTEXT_ONLY),
])
def test_verdict_rule_table(args, expected) -> None:
    assert C.verdict(*args) == expected


@pytest.mark.parametrize("args, expected", [
    ((3.0, 2.5, 2.2), C.PASS),                    # pays in the OOS span and in both OOS halves
    ((-3.0, -2.5, -2.2), C.FAIL),                 # loses consistently → FAIL, never PASS (the opposite rule was not pre-registered)
    ((3.0, 2.5, -2.2), C.CONTEXT_ONLY),           # pays overall, loses in one half
    ((3.0, 1.0, 2.2), C.CONTEXT_ONLY),            # one half below the bar
    ((1.5, 2.5, 2.2), C.FAIL),                    # OOS span below the bar
    ((-1.5, 2.5, 2.2), C.FAIL),
    ((float("nan"), 2.5, 2.2), C.FAIL),
    ((3.0, float("nan"), 2.2), C.CONTEXT_ONLY),
])
def test_verdict_traded_is_signed(args, expected) -> None:
    assert C.verdict_traded(*args) == expected


def test_traded_rules_grade_a_consistent_loser_as_fail() -> None:
    """Both callers of the traded verdict (G-STUDY-2 H6, GS-P4 H3) must FAIL a rule that loses money consistently —
    the unsigned statistic rule would have graded t ≤ −2 everywhere as PASS."""
    rng = np.random.default_rng(21)
    n = 1500
    idx = pd.bdate_range("2015-01-02", periods=n)
    label = pd.Series(rng.choice(list(GS2.LABELS.values()), size=n), index=idx, dtype=object)
    bullish = label.isin(GS2.BULLISH).to_numpy()
    r_next = pd.Series(np.where(bullish, -0.004, 0.003) + rng.normal(0, 0.002, n), index=idx)   # 'bullish' labels are followed by losses
    pan = pd.DataFrame({"label": label, "r_next": r_next, "fwd1": r_next.shift(-1) * 100})
    rule = GS2.folklore_rule(pan, 1)
    assert rule["oos_t"] <= -2 and rule["oos_t_h1"] <= -2 and rule["oos_t_h2"] <= -2
    assert rule["verdict"] == C.FAIL
    # GS-P4 H3: months 1–6 look best in the first five years (+10 %) and then lose (−2 %) for two decades — the learned set
    # keeps them (the prior-years mean stays positive), so the rule is long in losing months: FAIL, not PASS
    months = pd.date_range("2000-01-31", "2026-09-30", freq="ME")
    first_half = months.month <= 6
    r = pd.Series(np.where(months.year < 2005, np.where(first_half, 10.0, -10.0), np.where(first_half, -2.0, 2.0)), index=months)
    r += rng.normal(0, 0.3, len(r))
    wf = P4.walk_forward_best_months(r)
    assert set(wf["last_year_months"]) == {"Jan", "Feb", "Mar", "Apr", "May", "Jun"}
    assert wf["t"] <= -2 and wf["t_h1"] <= -2 and wf["t_h2"] <= -2
    assert wf["verdict"] == C.FAIL


def test_walk_forward_rule_detects_a_planted_signal_and_not_noise() -> None:
    rng = np.random.default_rng(7)
    n = 2000
    idx = pd.bdate_range("2012-01-02", periods=n)
    sig = pd.Series(rng.normal(size=n), index=idx)
    r_next = pd.Series(0.006 * sig.to_numpy() + rng.normal(0, 0.01, n), index=idx)   # one-period return earned by a decision at t
    good = C.walk_forward_long_flat(sig, r_next * 100, r_next, 1, periods_per_year=252, min_hist=250)
    assert good["OOS_t_excess"] >= 2 and good["OOS_excess_vs_scaled_pa_pct"] > 0
    noise = C.walk_forward_long_flat(pd.Series(rng.normal(size=n), index=idx), r_next * 100, r_next, 1, periods_per_year=252, min_hist=250)
    assert abs(noise["OOS_t_excess"]) < 2
    assert "_series" in good and len(good["_series"]["pos"]) == n


def test_infinite_inputs_never_reach_a_dot_product() -> None:
    rng = np.random.default_rng(3)
    base = pd.Series(np.r_[np.zeros(5), np.abs(rng.normal(100, 5, 1500))])
    g = C.pct_change_guarded(base, 1, 10.0)
    assert np.isfinite(g.dropna()).all() and g.iloc[:6].isna().all()
    raw = (base / base.shift(1) - 1) * 100                          # has ±inf / NaN at the zero base
    fwd = pd.Series(rng.normal(size=len(base)))
    with warnings.catch_warnings():
        warnings.simplefilter("error")                              # any RuntimeWarning fails the test
        ic = C.rank_ic(raw, fwd, 4)
        t = C.newey_west_t(raw, 4)
        sp = C.tercile_spread(fwd, C.expanding_tercile(raw, 50), 4)
    assert np.isfinite(ic["t"]) and np.isfinite(t) and np.isfinite(sp["t_nw"])


def test_oos_halves_split_at_the_oos_midpoint() -> None:
    idx = pd.bdate_range("2015-01-01", periods=600)
    rng = np.random.default_rng(4)
    r = pd.Series(rng.normal(0.0005, 0.01, 600), index=idx)
    pos = pd.Series((np.arange(600) % 3 == 0).astype(float), index=idx)
    ev = C.evaluate_long_flat(pos, r, h=1, periods_per_year=252, is_end=240)
    t1, t2, cut = C.oos_halves_t(ev, 1)
    assert np.isfinite(t1) and np.isfinite(t2)
    assert pd.Timestamp(cut) == idx[240 + (600 - 240) // 2 - 1]
    assert C.oos_halves_t({}, 1) == (float("nan"), float("nan"), "") or np.isnan(C.oos_halves_t({}, 1)[0])


def test_findings_row_shapes() -> None:
    row = C.Row("S1 → 5", "IC 0.01 (t 0.3); |t| ≥ 2 nowhere", "t 0.1", "t 0.2", C.FAIL)
    assert C.study_row(row) == "| S1 → 5 | IC 0.01 (t 0.3); \\|t\\| ≥ 2 nowhere → **FAIL** | t 0.1 / t 0.2 |"            # study page: 3 columns
    agg = C.aggregate_row("GS-P1", row)
    assert agg == "| GS-P1 · S1 → 5 | IC 0.01 (t 0.3); \\|t\\| ≥ 2 nowhere | t 0.1 / t 0.2 | **FAIL** |"                  # aggregate: 4 columns
    assert C.table_cells(agg) == ["GS-P1 · S1 → 5", "IC 0.01 (t 0.3); |t| ≥ 2 nowhere", "t 0.1 / t 0.2", "**FAIL**"]
    assert len(C.table_cells(C.study_row(row))) == 3
    pend = C.findings_pending_row("GS-P2", "WGC weekly flows → 1 / 4 weeks", "gold_series WGC_ETF_HOLD_T_*")
    assert pend.startswith("| GS-P2 · ") and pend.endswith("| — / — | **PENDING** |") and len(C.table_cells(pend)) == 4
    assert len(C.table_cells(C.findings_pending_row("GS-P2", "q", "n", shape="study"))) == 3
    assert C.findings_rows_md("X", [row, row]).count("\n") == 2 and C.findings_rows_md("X", [row]).startswith("| X · S1 → 5 |")
    assert C.findings_row("a", "b", "c", "d") == "| a | b | c / d |"
    assert C.fmt(-1.5) == "−1.50" and C.fmt(float("nan")) == "" and C.fmt(3) == "3"
    md = C.findings_template("X", "X · title", "26 Oct 2026", "data", "FAIL.", [row, C.findings_row("a", "b", "c", "d")], ["one"], "nothing", "s.py")
    assert md.startswith("# X · title: findings (26 Oct 2026)") and "**Verdict: FAIL.**" in md and md.rstrip().endswith("- **Use:** nothing")
    assert C.study_row(row) in md and "| a | b | c / d |" in md
    assert C.VOID == "VOID" and C.PENDING == "PENDING"


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# fast: common.py — release instants, entries after a release, point-in-time lags, the snapshot copy
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_release_rule_and_entry_after_release() -> None:
    rel = C.release_rule("wgc_weekly", "2026-10-16")                               # Friday-dated week → Monday 11:30 IST = 06:00 UTC
    assert rel == pd.Timestamp("2026-10-19 06:00")
    assert C.release_rule("gld", "2026-10-22") == pd.Timestamp("2026-10-23 00:30")  # T+1 06:00 IST
    sessions = pd.bdate_range("2026-10-12", periods=10)
    pos = C.entry_after_release(sessions, [rel, pd.Timestamp("2026-10-19 18:00"), pd.Timestamp("2026-10-17 09:00"), pd.NaT])
    assert sessions[pos[0]] == pd.Timestamp("2026-10-19")                         # 06:00 UTC Monday → Monday's close
    assert sessions[pos[1]] == pd.Timestamp("2026-10-20")                         # after Monday's 17:30 UTC settlement → Tuesday
    assert sessions[pos[2]] == pd.Timestamp("2026-10-19")                         # a Saturday release → Monday
    assert pos[3] == len(sessions)                                                # NaT → no entry
    assert C.entry_after_release(sessions, [rel], shift=1)[0] == pos[0] + 1
    assert C.entry_after_release(sessions, [pd.Timestamp("2030-01-01")])[0] == len(sessions)


def test_pit_lagged_never_shows_a_revision_before_its_release() -> None:
    dates = pd.date_range("2024-01-05", periods=6, freq="W-FRI")
    rows = [("S", d, 100.0 + i, d + pd.Timedelta(days=3)) for i, d in enumerate(dates)]            # first vintages, Monday
    rows.append(("S", dates[0], 999.0, dates[0] + pd.Timedelta(days=20)))                           # a revision of week 0, 20 days later
    rows.append(("S", dates[1], -1.0, dates[1] + pd.Timedelta(days=3650)))                          # a revision that never happens in-sample
    v = pd.DataFrame(rows, columns=["series_id", "report_date", "value", "release_at"])
    decision = pd.Series([d + pd.Timedelta(days=3) for d in dates], index=dates)                    # each week decided at its own release
    lag1 = C.pit_lagged(v, decision, 1)
    assert np.isnan(lag1.iloc[0]) and lag1.loc[dates[1]] == 100.0 and lag1.loc[dates[2]] == 101.0   # week 2 sees week 1's FIRST vintage
    lag2 = C.pit_lagged(v, decision, 2)
    assert lag2.loc[dates[2]] == 100.0                                             # decided day 17 < day 20: the revision is not visible
    assert lag2.loc[dates[3]] == 101.0
    lag3 = C.pit_lagged(v, decision, 3)
    assert lag3.loc[dates[3]] == 999.0                                             # decided day 24 ≥ day 20: the revision IS what a reader had
    lag4 = C.pit_lagged(v, decision, 4)
    assert lag4.loc[dates[5]] == 101.0                                             # the +10-year revision of week 1 never appears
    fv = C.first_vintage(v).set_index("report_date")
    assert fv.loc[dates[0], "value"] == 100.0 and fv.loc[dates[1], "value"] == 101.0


def _tiny_duckdb(path: Path) -> None:
    import duckdb

    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.execute("INSERT INTO t VALUES (1), (2)")
    con.close()


def test_open_snapshot_removes_its_copy_and_never_touches_the_source(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "src.duckdb"
    _tiny_duckdb(db)
    before = (db.stat().st_mtime_ns, db.stat().st_size)
    made: list[Path] = []

    def fake_mkdtemp(prefix: str = "") -> str:
        d = tmp_path / f"{prefix}owned"
        made.append(d)
        return str(d)

    monkeypatch.setattr(C.tempfile, "mkdtemp", fake_mkdtemp)
    with C.open_snapshot(db) as con:
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2
        assert (made[0] / "snapshot.duckdb").exists()
        import duckdb

        with pytest.raises(duckdb.Error):
            con.execute("INSERT INTO t VALUES (3)")                               # the copy is read-only
    assert made and not made[0].exists()                                          # the whole temp directory is gone
    own = tmp_path / "mine"
    with C.open_snapshot(db, own) as con:
        assert (own / "snapshot.duckdb").exists()
    assert own.exists() and not any(own.iterdir())                                # a caller's directory stays, the copy does not
    with pytest.raises(RuntimeError), C.open_snapshot(db):
        raise RuntimeError("study crashed")
    assert not made[-1].exists()                                                  # cleaned up on an exception too
    assert (db.stat().st_mtime_ns, db.stat().st_size) == before
    with pytest.raises(C.DataNotIngested), C.open_snapshot(tmp_path / "missing.duckdb"):
        pass


def test_open_snapshot_refuses_the_live_store_in_a_busy_window(tmp_path: Path) -> None:
    ist = C.IST
    assert C.is_live_busy(pd.Timestamp("2026-11-04 10:00", tz=ist))              # Wednesday, NSE session
    assert C.is_live_busy(pd.Timestamp("2026-11-04 08:00", tz=ist))              # ICICI login window
    assert C.is_live_busy(pd.Timestamp("2026-11-04 19:00", tz=ist))              # EOD pipeline
    assert not C.is_live_busy(pd.Timestamp("2026-11-04 16:30", tz=ist))          # between the windows
    assert not C.is_live_busy(pd.Timestamp("2026-11-04 22:00", tz=ist))
    assert not C.is_live_busy(pd.Timestamp("2026-11-07 10:00", tz=ist))          # Saturday
    assert C.is_live_busy(pd.Timestamp("2026-11-04 10:00")) and not C.is_live_busy(pd.Timestamp("2026-11-04 04:30"))   # naive = IST wall time
    assert C.is_live_busy(pd.Timestamp("2026-11-04 04:30", tz="UTC"))            # 04:30 UTC = 10:00 IST
    assert C.is_live_store(C.ROOT / "data" / "market.duckdb") and not C.is_live_store(tmp_path / "x.duckdb")
    db = tmp_path / "copy.duckdb"
    _tiny_duckdb(db)
    busy = pd.Timestamp("2026-11-04 10:00", tz=ist)
    with pytest.raises(C.LiveFileBusy), C.open_snapshot(db, live=True, now=busy):
        pass
    assert not any(p.name.startswith("gold_study_") and (p / "snapshot.duckdb").exists() for p in Path(C.tempfile.gettempdir()).glob("gold_study_*"))
    with C.open_snapshot(db, live=True, now=busy, allow_market_hours=True) as con:        # the explicit override
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2
    with C.open_snapshot(db, live=True, now=pd.Timestamp("2026-11-04 16:30", tz=ist)) as con:   # a quiet window
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2
    with C.open_snapshot(db, now=busy) as con:                                    # not the live store → never refused
        assert con.execute("SELECT count(*) FROM t").fetchone()[0] == 2


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# fast: G-STUDY-2 (daily OI × price quadrant)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _synthetic_daily(n: int = 700, seed: int = 11) -> tuple[pd.Series, pd.Series]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2014-01-02", periods=n)
    price = pd.Series(1500 * np.exp(np.cumsum(rng.normal(0, 0.01, n))), index=idx)
    oi = pd.Series(400_000 + np.cumsum(rng.normal(0, 3000, n)).round(), index=idx)
    return oi, price


def test_gs2_exits_3_without_data_and_4_on_the_short_fixture(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        GS2.main(["--out", str(tmp_path)])
    assert e.value.code == C.EXIT_NOT_INGESTED
    st = _status(capsys)
    assert st["status"] == "data not yet ingested" and "gold_cme_daily_voi" in st["needs"]
    assert not any(tmp_path.iterdir())                                 # nothing fabricated
    fixture = GP / "G-CME" / "samples" / "comex_gold_family_daily_oi_oct2026.csv"
    _needs(fixture, G_STUDY / "data" / "yahoo_GC_F_1d.csv")
    with pytest.raises(SystemExit) as e:
        GS2.main(["--fixture", str(fixture), "--out", str(tmp_path)])
    assert e.value.code == C.EXIT_INSUFFICIENT and _status(capsys)["status"] == "insufficient history"
    assert not any(tmp_path.iterdir())


def test_gs2_labels_entry_and_mechanical_flags() -> None:
    oi, price = _synthetic_daily()
    pan = GS2.build_panel(oi, price)
    assert (pan["entry"].dropna() > pan.index[: pan["entry"].notna().sum()]).all()   # entry = the session after T
    for T in pan.index[5:60]:
        dp, do = pan.at[T, "dpx_T"], pan.at[T, "doi"]
        if dp == 0 or do == 0 or np.isnan(dp) or np.isnan(do):
            continue
        assert pan.at[T, "label"] == GS2.LABELS[(int(np.sign(dp)), int(np.sign(do)))]
    assert GS2.ARROWS["short covering"] == "P↑ OI↓" and GS2.ARROWS["short build-up"] == "P↓ OI↑"
    flags = GS2.mechanical_flags(pd.bdate_range("2024-01-01", "2024-03-31"))
    assert flags[pd.Timestamp("2024-01-31")] and flags[pd.Timestamp("2024-01-25")] and not flags[pd.Timestamp("2024-01-24")]
    assert flags[pd.Timestamp("2024-02-29")] and flags[pd.Timestamp("2024-02-28")] and not flags[pd.Timestamp("2024-02-27")]
    assert not flags[pd.Timestamp("2024-01-15")] and flags[pd.Timestamp("2024-03-29")]


def test_gs2_synthetic_run_writes_outputs_and_controls_do_not_pass(tmp_path: Path) -> None:
    oi, price = _synthetic_daily()
    s = GS2.run_study(oi, price, tmp_path, {"oi": "synthetic"})
    assert s["sample"]["sessions"] == 700 and len(s["cells"]) == 12 and len(s["ic_tests"]) == 9 and len(s["folklore_rule"]) == 3
    assert all(r["verdict"] in (C.PASS, C.CONTEXT_ONLY, C.FAIL) for r in s["cells"] + s["ic_tests"] + s["folklore_rule"])
    assert not any(r["verdict"] == C.PASS for r in s["cells"])        # pure noise never passes the both-halves bar
    for col in ("label_placebo", "label_shuffled"):
        assert s["negative_controls"][col]["pass_cells"] == []
    assert all(r["oos_split"] for r in s["folklore_rule"])
    for name in ("summary.json", "REPORT.md", "FINDINGS_ROW.md", "FINDINGS.md", "results/cells.csv", "results/panel.csv"):
        assert (tmp_path / name).exists()
    rows = (tmp_path / "FINDINGS_ROW.md").read_text(encoding="utf-8")
    assert rows.startswith("| G-STUDY-2 · long build-up (P↑ OI↑) → 1 sessions |") and "short covering (P↑ OI↓)" in rows
    assert "**Verdict:" in (tmp_path / "FINDINGS.md").read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# fast: GS-P1 (GLD daily tonnes)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _synthetic_gld(n: int = 3000, seed: int = 5, planted: float = 0.0) -> tuple[pd.Series, pd.Series]:
    """Tonnes random walk; price log-returns optionally driven by the 1-day tonnes change two sessions earlier (so the
    forward window from close(T+1) carries S1_T — a real, tradable effect for the positive control)."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-04", periods=n)
    tonnes = pd.Series(1000 * np.exp(np.cumsum(rng.normal(0, 0.004, n))), index=idx)
    s1 = (tonnes / tonnes.shift(1) - 1).fillna(0)
    r = planted * s1.shift(2).fillna(0) + rng.normal(0, 0.004, n)
    price = pd.Series(1200 * np.exp(np.cumsum(r)), index=idx)
    return tonnes, price


def test_gs_p1_alignment_has_no_look_ahead() -> None:
    tonnes, price = _synthetic_gld()
    pan = P1.build_panel(tonnes, price)
    ok = pan.dropna(subset=["entry"])
    assert (ok["entry"] > ok.index).all()                              # the first price session strictly after T
    assert (ok["entry_px"].to_numpy() == price.reindex(ok["entry"]).to_numpy()).all()
    later = tonnes.copy()
    later.iloc[-1] *= 2                                                # a future holding must not change any earlier signal
    pan2 = P1.build_panel(later, price)
    assert pan["S3"].iloc[:-1].equals(pan2["S3"].iloc[:-1])
    pan3 = P1.build_panel(tonnes, price, entry_shift=2)
    assert (pan3["entry"].dropna() > pan["entry"].reindex(pan3["entry"].dropna().index)).all()


def test_gs_p1_db_path_enters_after_the_stored_release_at() -> None:
    """The --db path carries `release_at` per trust date: the entry is the first session settling after it and never
    earlier than the T+1 rule — a late posting pushes the entry out, an early one cannot pull it in."""
    tonnes, price = _synthetic_gld(n=400)
    rule = P1.build_panel(tonnes, price)
    on_time = pd.Series([C.release_rule("gld", d) for d in tonnes.index], index=tonnes.index)        # T+1 06:00 IST
    pan = P1.build_panel(tonnes, price, release_at=on_time)
    assert pan["entry"].equals(rule["entry"]) and pan["fwd5"].equals(rule["fwd5"])
    late = on_time + pd.Timedelta(days=3, hours=20)                                                  # posted T+4 evening
    pan_late = P1.build_panel(tonnes, price, release_at=late)
    ok = pan_late.dropna(subset=["entry"])
    assert (ok["entry"] > rule.loc[ok.index, "entry"]).all() and (ok["entry"] - ok.index).dt.days.min() >= 5
    early = on_time - pd.Timedelta(days=2)                                                           # 'posted' before the trust date
    assert P1.build_panel(tonnes, price, release_at=early)["entry"].equals(rule["entry"])             # never before T+1
    assert "release_at" in pan.columns and "release_at" not in rule.columns


def test_gs_p1_noise_fails_and_planted_signal_passes(tmp_path: Path) -> None:
    tonnes, price = _synthetic_gld()
    s = P1.run_study(tonnes, price, tmp_path, {"tonnes": "synthetic"})
    assert all(c["control_ok"] == (c["verdict"] == C.FAIL) for c in s["negative_controls"])   # 'ok' means FAIL, not merely not-PASS
    assert s["controls_ok"] and not s["any_pass"] and len(s["tests"]) == 6
    for name in ("summary.json", "REPORT.md", "FINDINGS_ROW.md", "FINDINGS.md", "results/ic_tests.csv", "results/negative_controls.csv"):
        assert (tmp_path / name).exists()
    assert (tmp_path / "FINDINGS_ROW.md").read_text(encoding="utf-8").startswith("| GS-P1 · S1 · 1-day Δ tonnes → 5 sessions |")
    tonnes_p, price_p = _synthetic_gld(planted=1.0)
    r = P1.run_tests(P1.build_panel(tonnes_p, price_p), "S1", 5)
    assert r["t_ic"] >= 2 and r["t_h1"] >= 2 and r["t_h2"] >= 2 and r["oos_t"] >= 2 and r["verdict"] == C.PASS


def test_gs_p1_exits_3_when_the_fixtures_are_missing(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        P1.main(["--fixture-dir", str(tmp_path / "empty"), "--out", str(tmp_path / "out")])
    assert e.value.code == C.EXIT_NOT_INGESTED and _status(capsys)["status"] == "data not yet ingested"
    assert not (tmp_path / "out").exists()


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# fast: GS-P2 (WGC weekly flows) — honest exits, the fixture is check-only, PIT read on a temp DuckDB
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _synthetic_wgc_db(path: Path, weeks: int = 320, seed: int = 9) -> tuple[pd.DataFrame, pd.Series]:
    """A temporary DuckDB with the PLAN c.1 `gold_series` / `gold_daily_bars` shapes filled with synthetic rows."""
    import duckdb

    rng = np.random.default_rng(seed)
    fridays = pd.date_range("2015-01-02", periods=weeks, freq="W-FRI")
    levels = {"NA": 1500.0, "EU": 1200.0, "ASIA": 150.0, "OTHER": 40.0}
    hold = pd.DataFrame({r: lv * np.exp(np.cumsum(rng.normal(0, 0.01, weeks))) for r, lv in levels.items()}, index=fridays)
    hold["GLOBAL"] = hold.sum(axis=1)
    rows = []
    for region in P2.REGIONS:
        for d, v in hold[region].items():
            rel = d + pd.Timedelta(days=3)                                    # Monday 11:30 IST ≈ 06:00 UTC
            rows.append((P2.HOLD_IDS[region], d.date(), "W", float(v), rel.to_pydatetime(), "publisher", rel.to_pydatetime(),
                         "synthetic", "official", 0))
    sessions = pd.bdate_range(fridays[0] - pd.Timedelta(days=10), fridays[-1] + pd.Timedelta(days=120))
    price = pd.Series(1200 * np.exp(np.cumsum(rng.normal(0, 0.01, len(sessions)))), index=sessions)
    con = duckdb.connect(str(path))
    con.execute("""CREATE TABLE gold_series (series_id VARCHAR NOT NULL, report_date DATE NOT NULL, freq VARCHAR NOT NULL,
        value DOUBLE NOT NULL, release_at TIMESTAMP NOT NULL, release_source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL,
        source VARCHAR NOT NULL, quality VARCHAR NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (series_id, report_date, release_at))""")
    con.execute("""CREATE TABLE gold_daily_bars (trade_date DATE NOT NULL, symbol VARCHAR NOT NULL, open DOUBLE, high DOUBLE,
        low DOUBLE, close DOUBLE, adj_close DOUBLE, volume BIGINT, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL,
        PRIMARY KEY (trade_date, symbol, source))""")
    con.executemany("INSERT INTO gold_series VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.executemany("INSERT INTO gold_daily_bars VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(d.date(), "COMEX_GC_FRONT", None, None, None, float(v), None, None, "synthetic", d.to_pydatetime()) for d, v in price.items()])
    # a revision of the first GLOBAL week (+100 t), released 20 days later: weeks decided before day 20 must not see it,
    # weeks decided after it must; and a revision of week 1 'released' ten years out that no in-sample decision may see
    first = fridays[0]
    for i, add, days in ((0, 100.0, 20), (1, 5000.0, 3650)):
        rel = (fridays[i] + pd.Timedelta(days=days)).to_pydatetime()
        con.execute("INSERT INTO gold_series VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [P2.HOLD_IDS["GLOBAL"], fridays[i].date(), "W", float(hold["GLOBAL"].iloc[i]) + add, rel, "fetch", rel, "synthetic", "official", 1])
    assert first == fridays[0]
    con.close()
    return hold, price


def test_gs_p2_exits_3_without_data(tmp_path: Path, capsys) -> None:
    with pytest.raises(SystemExit) as e:
        P2.main(["--out", str(tmp_path)])
    assert e.value.code == C.EXIT_NOT_INGESTED
    st = _status(capsys)
    assert st["status"] == "data not yet ingested" and "WGC_ETF_HOLD_T" in st["needs"] and not any(tmp_path.iterdir())


def test_gs_p2_fixture_dir_is_check_only_and_never_a_verdict(tmp_path: Path, capsys) -> None:
    samples = GP / "G-PHYSICAL" / "samples"
    _needs(samples / "wgc_fsapi_holdings.json", G_STUDY / "data" / "yahoo_GC_F_1d.csv")
    out = tmp_path / "out"
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert P2.main(["--fixture-dir", str(samples), "--out", str(out)]) == 0
    st = _status(capsys)
    assert st["status"] == "checked" and "verdict requires --db" in st["detail"] and "GLOBAL" in st["detail"]
    assert not out.exists()                                            # no REPORT / FINDINGS from the fixture


def test_gs_p2_point_in_time_read_and_synthetic_run(tmp_path: Path, monkeypatch) -> None:
    db = tmp_path / "gold.duckdb"
    hold, price = _synthetic_wgc_db(db)
    with C.open_snapshot(db, tmp_path / "snap") as con:
        first = hold.index[0]
        early = C.read_gold_series(con, [P2.HOLD_IDS["GLOBAL"]], asof=str((first + pd.Timedelta(days=10)).date()))
        late = C.read_gold_series(con, [P2.HOLD_IDS["GLOBAL"]])
        assert abs(float(early.iloc[0]["value"]) - hold["GLOBAL"].iloc[0]) < 1e-9          # the vintage a reader had
        assert abs(float(late.iloc[0]["value"]) - hold["GLOBAL"].iloc[0] - 100.0) < 1e-9     # the revision, once released
        assert len(late) == len(hold)                                                        # one row per report_date
        vint = C.read_gold_series_vintages(con, [P2.HOLD_IDS["GLOBAL"]])
        assert len(vint) == len(hold) + 2                                                    # every vintage, no QUALIFY
        with pytest.raises(C.DataNotIngested):
            C.read_gold_series(con, ["NO_SUCH_SERIES"])
    assert not (tmp_path / "snap" / "snapshot.duckdb").exists()
    # the verdict path: load_inputs copies to a temp dir that must be gone afterwards
    made: list[Path] = []
    monkeypatch.setattr(C.tempfile, "mkdtemp", lambda prefix="": (made.append(tmp_path / f"{prefix}x"), str(tmp_path / f"{prefix}x"))[1])
    inp = P2.load_inputs(db=db)
    assert made and not made[0].exists()
    hold_db, flows, price_db, meta = inp.hold, inp.flows, inp.price, inp.meta
    assert flows is None and set(hold_db.columns) == set(P2.REGIONS) and len(hold_db) == len(hold) and len(price_db) == len(price)
    assert abs(hold_db["GLOBAL"].iloc[0] - hold["GLOBAL"].iloc[0]) < 1e-9              # hold = FIRST vintages, never the revision
    assert inp.vintages is not None and len(inp.vintages) == 5 * len(hold) + 2 and "point-in-time" in meta["holdings"]
    pan = P2.build_panel(hold_db, price_db, vintages=inp.vintages)
    ok = pan.dropna(subset=["entry"])
    assert (pan["release_source"] == "stored").all() and (ok["release"].dt.weekday == 0).all()
    assert (ok["entry"] >= ok["release"]).all() and (ok["release"] > ok.index).all()
    assert np.isfinite(pan[list(P2.SIGNALS)].dropna()).all().all()
    # THE point-in-time proof on the --db verdict path: the +100 revision of week 0 (released day 20) is invisible to the
    # weeks decided on days 3, 10 and 17, visible to the week decided on day 31; the +5000 revision of week 1 never appears
    w = hold.index
    g = hold["GLOBAL"]
    assert abs(pan.loc[w[1], "S1"] - (g.iloc[1] / g.iloc[0] - 1) * 100) < 1e-9             # week 1 (day 10) vs the ORIGINAL week 0
    assert abs(pan.loc[w[2], "S1"] - (g.iloc[2] / g.iloc[1] - 1) * 100) < 1e-9             # week 2 vs the original week 1 (+5000 never seen)
    assert abs(pan.loc[w[4], "S2"] - (g.iloc[4] / (g.iloc[0] + 100.0) - 1) * 100) < 1e-9   # week 4 (day 31) vs week 0 AS REVISED on day 20
    assert abs(pan.loc[w[5], "S2"] - (g.iloc[5] / g.iloc[1] - 1) * 100) < 1e-9             # week 5 vs week 1: the far-future revision is unseen
    naive = P2.build_panel(hold_db, price_db)                                              # the rule path (no vintages) uses first vintages
    assert abs(naive.loc[w[4], "S2"] - (g.iloc[4] / g.iloc[0] - 1) * 100) < 1e-9 and naive.loc[w[4], "S2"] != pan.loc[w[4], "S2"]
    assert (naive["release_source"] == "rule").all() and naive["release"].equals(pan["release"])    # same Monday either way
    s = P2.run_study(hold_db, flows, price_db, tmp_path / "out", meta, vintages=inp.vintages)
    assert len(s["tests"]) == 15 and s["any_pass"] is False
    assert all(c["control_ok"] == (c["verdict"] == C.FAIL) for c in s["negative_controls"])    # 'ok' means FAIL (PLAN), not merely not-PASS
    assert not any(c["verdict"] == C.PASS for c in s["negative_controls"])
    assert s["sample"]["point_in_time"] and s["sample"]["release_source"] == {"stored": len(hold)} and s["sample"]["vintages"] == 5 * len(hold) + 2
    assert s["overall"] in (C.CONTEXT_ONLY, C.FAIL)
    for name in ("summary.json", "REPORT.md", "FINDINGS_ROW.md", "FINDINGS.md", "results/ic_tests.csv"):
        assert (tmp_path / "out" / name).exists()
    rows = (tmp_path / "out" / "FINDINGS_ROW.md").read_text(encoding="utf-8").strip().splitlines()
    assert rows[0].startswith("| GS-P2 · S1 · global 1-wk flow → 1w |") and all(len(C.table_cells(r)) == 4 for r in rows)


def test_gs_p2_zero_holdings_before_a_fund_launch_give_no_signal() -> None:
    fridays = pd.date_range("2003-02-28", periods=60, freq="W-FRI")
    hold = pd.DataFrame({"NA": np.r_[np.zeros(10), np.linspace(8, 200, 50)], "EU": np.linspace(5, 300, 60)}, index=fridays)
    hold["GLOBAL"] = hold["NA"] + hold["EU"]
    price = pd.Series(np.linspace(300, 400, 500), index=pd.bdate_range("2003-02-20", periods=500))
    pan = P2.build_panel(hold, price)
    assert pan["S3"].iloc[:11].isna().all() and np.isfinite(pan["S3"].dropna()).all()     # NA: 0 t base → no % flow
    assert np.isfinite(pan["S1"].dropna()).all() and pan["S1"].notna().sum() > 40


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# fast: GS-P4 (seasonality in rupees)
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _monthly(seed: int = 2, planted_month: int | None = 3, boost: float = 3.0, start: str = "1973-01-31", end: str = "2026-09-30") -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, end, freq="ME")
    r = pd.Series(rng.normal(0.3, 2.0, len(idx)), index=idx)
    if planted_month:
        r[idx.month == planted_month] += boost
    return r


def test_gs_p4_month_table_detects_a_planted_month_only() -> None:
    rows = P4.month_table(_monthly(), P4.LONG_SPLIT)
    by = {r["month"]: r for r in rows}
    mar = by["Mar"]
    assert mar["verdict_adj"] == C.PASS and mar["t_excess"] > 5 and mar["h1_t_excess"] > 2 and mar["h2_t_excess"] > 2
    assert mar["verdict"] == C.CONTEXT_ONLY and mar["post_hoc_cap"]            # a drift-adjusted PASS is capped (post-hoc statistic, N4)
    assert [r["month"] for r in rows if r["verdict_adj"] == C.PASS] == ["Mar"] and not any(r["verdict"] == C.PASS for r in rows)
    assert abs(mar["excess_pct"] - (mar["mean_pct"] - mar["sample_mean_pct"])) < 0.02
    agree = P4.confirm_with_tradable(rows, P4.month_table(_monthly(seed=3, start="2000-09-30"), P4.TRADABLE_SPLIT))
    assert next(r for r in agree if r["month"] == "Mar")["verdict_adj"] == C.PASS
    disagree = P4.confirm_with_tradable(rows, P4.month_table(_monthly(seed=3, boost=-6.0, start="2000-09-30"), P4.TRADABLE_SPLIT))
    assert next(r for r in disagree if r["month"] == "Mar")["verdict_adj"] == C.CONTEXT_ONLY     # sign disagrees → not a PASS
    hyps = P4.hypothesis_summary(agree)
    assert {h["hypothesis"].split(" ")[0] for h in hyps} == {"H1", "H1b", "H2"} and all("verdict_pre" in h for h in hyps)


def test_gs_p4_drift_alone_fools_the_vs_zero_statistic_but_not_the_adjusted_one() -> None:
    """A pure-drift series (no calendar effect, +1 %/month like rupee gold): the vs-zero statistic's shuffle control passes
    often; the drift-adjusted statistic's does not — the reason PLAN N4 voids the pre-registered statistic."""
    r = _monthly(seed=12, planted_month=None) + 0.7                        # mean ≈ +1.0 %/month, sd 2 %
    rows = P4.month_table(r, P4.LONG_SPLIT)
    assert sum(r_["t"] >= 2 for r_ in rows) >= 6 and sum(abs(r_["t_excess"]) >= 2 for r_ in rows) <= 2
    nc = P4.negative_controls(r, _monthly(seed=13, planted_month=None, start="2000-09-30") + 0.7, n_null=12)
    assert nc["null_months_ge2_pre"] > nc["null_months_ge2_adj"] + 2 and nc["null_pass_rate_adj"] <= 0.25
    assert nc["pre_registered_statistic_void"] or nc["null_months_ge2_pre"] >= 4


def test_gs_p4_walk_forward_learns_from_prior_years_and_charges_per_switch() -> None:
    r = _monthly(seed=6, start="2000-01-31")
    wf = P4.walk_forward_best_months(r)
    assert wf["oos_from"] == 2000 + P4.MIN_YEARS and "Mar" in wf["last_year_months"] and len(wf["last_year_months"]) == P4.BEST_K
    assert wf["cost_per_switch_pct"] == C.COST_RT and wf["verdict"] in (C.PASS, C.CONTEXT_ONLY, C.FAIL)
    free = P4.walk_forward_best_months(r, cost_switch=0.0)
    assert free["excess_vs_scaled_pa_pct"] > wf["excess_vs_scaled_pa_pct"]
    ctrl = P4.negative_controls(_monthly(), _monthly(seed=3, start="2000-09-30"), n_null=5)
    assert ctrl["relabel_ok"] and ctrl["relabel_pass_months"] == []      # a planted March must vanish once labels are shuffled
    assert 0.0 <= ctrl["null_pass_rate_adj"] <= 0.4 and "shuffled_walk_forward_t" in ctrl      # 5 seeds: a rate, not a verdict


def test_gs_p4_complete_month_ends_and_exit_3(tmp_path: Path, capsys) -> None:
    daily = pd.Series(np.arange(1.0, 101.0), index=pd.bdate_range("2023-11-01", periods=100))      # ends mid-March 2024
    me = P4.complete_month_ends(daily)
    assert me.index[-1] == pd.Timestamp("2024-02-29") and me.index[0] == pd.Timestamp("2023-11-30")
    with pytest.raises(SystemExit) as e:
        P4.main(["--data-dir", str(tmp_path / "empty"), "--out", str(tmp_path / "out")])
    assert e.value.code == C.EXIT_NOT_INGESTED and _status(capsys)["status"] == "data not yet ingested"
    assert not (tmp_path / "out").exists()
