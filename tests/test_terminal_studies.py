"""Terminal v2 studies (B8): the pre-registered machinery, with positive and negative controls for every rule.

Fast (synthetic data, temp DuckDB files under pytest's tmp_path; < 10 s): never touches the live stack, never opens
`data/market.duckdb`, never writes under `data/`, never calls the network. What is pinned:

* `scripts/terminal_studies/common.py` — HAC OLS recovers a planted slope and not noise; the SIGNED verdict rule (a t >= 2
  against the registered sign is a FAIL; full-sample-only is CONTEXT-ONLY; ceilings; two-sided cannot PASS; NaN never
  passes); controls VOID / CAP; forward windows start at the close of T+1 (no look-ahead: T's own close cannot move them);
  the walk-forward tercile ignores the future; placebo transforms; the F&O cost schedule never undercuts the 0.15 % floor;
  the cash leg uses `shared/trading_costs.py`; the live store is refused in a busy window without a copy;
* each study's statistic on fixtures (planted effect found, noise not), the GEX sign convention and gamma, the drivers
  fit gate / event thinning / signed persistence;
* honest exits (3 on an empty store), outputs stamped PROVISIONAL, verdicts in the vocabulary;
* the pre-registration itself: each PLAN exists, says it predates the results, and agrees with the code's split dates and
  registered signs; the registry lists every id; no network client in the package.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.append(str(ROOT / "scripts"))

from terminal_studies import common as C
from terminal_studies import tv_drivers as DRV
from terminal_studies import tv_gex as GEX
from terminal_studies import tv_ivrv as IVRV

VOCAB = {C.PASS, C.PASS_DESC, C.CONTEXT_ONLY, C.FAIL, C.VOID, C.PENDING}


def _bdays(n: int, start: str = "2019-01-01") -> pd.DatetimeIndex:
    return pd.bdate_range(start, periods=n)


# ── statistics and the verdict rule ───────────────────────────────────────────────────────────────────────────────

def test_ols_hac_finds_planted_slope_and_not_noise():
    rng = np.random.default_rng(1)
    idx = _bdays(1200)
    x = pd.Series(rng.normal(size=1200), index=idx)
    z = pd.Series(rng.normal(size=1200), index=idx)
    y = 0.5 * x + 0.3 * z + pd.Series(rng.normal(size=1200), index=idx)
    r = C.ols_hac(y, pd.DataFrame({"x": x, "z": z}), lags=5)
    assert abs(r["coef"]["x"] - 0.5) < 0.1 and r["t"]["x"] > 8
    noise = C.ols_hac(pd.Series(rng.normal(size=1200), index=idx), pd.DataFrame({"x": x}), lags=5)
    assert abs(noise["t"]["x"]) < 3.5


def test_signed_verdict_rule():
    assert C.signed_verdict(3, 2.5, 2.2, +1, traded_ok=True) == C.PASS
    assert C.signed_verdict(3, 2.5, 2.2, +1, traded_ok=False) == C.CONTEXT_ONLY          # pays nothing after costs
    assert C.signed_verdict(3, 2.5, 2.2, +1, traded_ok=None) == C.CONTEXT_ONLY
    assert C.signed_verdict(-3, -2.5, -2.2, +1, traded_ok=True) == C.FAIL                 # strong, but against the registered sign
    assert C.signed_verdict(-3, -2.5, -2.2, -1, traded_ok=True) == C.PASS
    assert C.signed_verdict(2.5, 1.0, 2.5, +1, traded_ok=True) == C.CONTEXT_ONLY          # full sample only
    assert C.signed_verdict(1.9, 2.5, 2.5, +1, traded_ok=True) == C.FAIL
    assert C.signed_verdict(3, 3, 3, +1, ceiling=C.PASS_DESC) == C.PASS_DESC
    assert C.signed_verdict(3, 3, 3, +1, ceiling=C.CONTEXT_ONLY) == C.CONTEXT_ONLY
    assert C.signed_verdict(3, 3, 3, 0, traded_ok=True) == C.CONTEXT_ONLY                 # two-sided: nothing registered
    assert C.signed_verdict(float("nan"), 3, 3, +1, traded_ok=True) == C.FAIL
    assert not C.meets(3, -3, 3, 0)                                                       # two-sided needs one common sign


def test_controls_void_and_cap():
    assert C.apply_controls(C.PASS, voided_by=["N1"], capped_by=[])[0] == C.VOID
    assert C.apply_controls(C.PASS, voided_by=[], capped_by=["N4"])[0] == C.CONTEXT_ONLY
    assert C.apply_controls(C.PASS_DESC, voided_by=[], capped_by=["cap"])[0] == C.CONTEXT_ONLY
    assert C.apply_controls(C.FAIL, voided_by=[], capped_by=["N4"])[0] == C.FAIL


# ── point-in-time windows ─────────────────────────────────────────────────────────────────────────────────────────

def test_forward_windows_start_after_the_close_of_t_plus_1():
    rng = np.random.default_rng(2)
    idx = _bdays(80)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 80))), index=idx)
    t = 30
    ret, rv = C.forward_ret(close), C.forward_rv(close)
    exp_ret = (close.iloc[t + 21] / close.iloc[t + 1] - 1) * 100
    assert math.isclose(ret.iloc[t], exp_ret, rel_tol=1e-12)
    lr = np.log(close / close.shift(1)).iloc[t + 2: t + 22]
    assert math.isclose(rv.iloc[t], lr.std(ddof=1) * math.sqrt(252) * 100, rel_tol=1e-12)
    bumped = close.copy()
    bumped.iloc[: t + 1] *= 1.3                                                           # T's own close and everything before
    assert math.isclose(C.forward_ret(bumped).iloc[t], ret.iloc[t], rel_tol=1e-12)
    assert math.isclose(C.forward_rv(bumped).iloc[t], rv.iloc[t], rel_tol=1e-12)
    moved = close.copy()
    moved.iloc[t + 1] *= 1.05                                                             # the entry close does move them
    assert not math.isclose(C.forward_ret(moved).iloc[t], ret.iloc[t], rel_tol=1e-9)


def test_trailing_rv_is_production_close_to_close():
    C.ensure_data_service_path()
    from fo_iv import realised

    rng = np.random.default_rng(3)
    idx = _bdays(60)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 60))), index=idx)
    frame = pd.DataFrame({"close": close.to_numpy(), "prev_close": close.shift(1).to_numpy()})
    assert math.isclose(C.trailing_rv(close).iloc[-1], realised.close_to_close(frame, 20), rel_tol=1e-9)


def test_tercile_is_walk_forward_and_placebos_keep_values():
    rng = np.random.default_rng(4)
    s = pd.Series(rng.normal(size=600), index=_bdays(600))
    top = C.top_tercile(s, 252)
    s2 = s.copy()
    s2.iloc[400:] = 99.0                                                                  # rewrite the future
    assert top.iloc[:400].equals(C.top_tercile(s2, 252).iloc[:400])
    assert top.iloc[:252].isna().all() and top.iloc[252:].notna().all()
    assert sorted(C.circular_shift(s).to_numpy()) == sorted(s.to_numpy())
    p1, p2 = C.permute(s), C.permute(s)
    assert p1.equals(p2) and sorted(p1.to_numpy()) == sorted(s.to_numpy()) and not p1.equals(s)
    assert C.placebo_lag(s, 250).iloc[250] == s.iloc[0]


# ── costs ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_fno_costs_never_below_the_floor_and_straddle_arithmetic():
    f = C.FNO
    assert f.order_pct("sell") >= C.FLOOR_PCT and f.order_pct("buy") >= C.FLOOR_PCT
    cheap = C.FnoCosts(stt_sell_pct=0.0, exchange_pct=0.0, sebi_pct=0.0, stamp_buy_pct=0.0, brokerage_pct=0.0, half_spread_pct=0.0)
    assert cheap.order_pct("sell") == C.FLOOR_PCT                                         # the floor binds
    pnl = C.straddle_to_expiry_pnl_pct(100.0, 100.0, 1000.0, 1000.0, 1000.0, f)
    assert math.isclose(pnl, (200 - 2 * 100 * f.order_pct("sell") / 100) / 1000 * 100, rel_tol=1e-12)
    loss = C.straddle_to_expiry_pnl_pct(100.0, 100.0, 1000.0, 1000.0, 1300.0, f)           # 300 intrinsic, exercise STT charged
    assert loss < (200 - 300) / 1000 * 100
    one = C.straddle_one_session_pnl_pct(50, 50, 50, 50, 1000, f)
    assert one < 0                                                                        # flat prices lose exactly the costs


def test_cash_leg_uses_the_frozen_cost_model():
    from shared.trading_costs import default_model

    v = C.cash_round_trip_pct(100_000)
    assert v >= C.FLOOR_PCT and math.isclose(v, max(C.FLOOR_PCT, default_model().round_trip_pct(100_000, "delivery")), rel_tol=1e-12)


def test_live_store_is_refused_in_a_busy_window_without_a_copy(tmp_path, monkeypatch):
    live = tmp_path / "market.duckdb"
    live.write_bytes(b"not opened")
    monkeypatch.setattr(C, "LIVE_DB", live)
    busy = pd.Timestamp("2026-11-05 10:00", tz="Asia/Kolkata")                           # a Thursday in session
    with pytest.raises(C.LiveFileBusy), C.open_inputs(live, now=busy):
        pass
    assert sorted(p.name for p in tmp_path.iterdir()) == ["market.duckdb"]               # nothing copied


def test_build_inputs_refuses_data_dir():
    from terminal_studies import build_inputs as B

    with pytest.raises(SystemExit):
        B._refuse_data_dir(C.ROOT / "data" / "x.duckdb")
    B._refuse_data_dir(Path("/tmp/b8_ok.duckdb"))                                         # anything else is fine


# ── TV-IVRV ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _ivrv_frame(n: int, planted: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = _bdays(n)
    s = pd.Series(rng.normal(size=n), index=idx).rolling(5, min_periods=1).mean()
    f = pd.DataFrame(index=idx)
    f["rv20"] = 15 + rng.normal(0, 1, n)
    f["RVF"] = f["rv20"] + rng.normal(0, 2, n)
    f["RET"] = planted * s + rng.normal(0, 1, n)
    f["iv30_cm"] = f["rv20"] + 1.0
    f["VRPR"] = f["iv30_cm"] - f["RVF"]
    f["S"] = s
    return f


def test_ivrv_statistics_find_a_planted_effect_and_not_noise():
    planted = _ivrv_frame(1500, 1.5, 5)
    st = IVRV.stat_set(planted, planted["S"])
    assert st["G3"]["t_full"] > 4 and st["G3"]["t_h1"] > 2 and st["G3"]["t_h2"] > 2
    flipped = _ivrv_frame(1500, -1.5, 5)
    st_f = IVRV.stat_set(flipped, flipped["S"])["G3"]
    assert C.signed_verdict(st_f["t_full"], st_f["t_h1"], st_f["t_h2"], +1, traded_ok=True) == C.FAIL
    noise = _ivrv_frame(1500, 0.0, 6)
    st_n = IVRV.stat_set(noise, noise["S"])["G3"]
    assert C.signed_verdict(st_n["t_full"], st_n["t_h1"], st_n["t_h2"], +1, traded_ok=True) != C.PASS


def test_ivrv_cond_minus_all_signs():
    idx = _bdays(400)
    cond = pd.Series(np.tile([1.0, 0.0], 200), index=idx)
    pnl = pd.Series(np.where(cond == 1, 1.0, -1.0) + np.random.default_rng(7).normal(0, 0.1, 400), index=idx)
    r = IVRV.cond_minus_all(pnl, cond, 1, "2019-06-30")
    assert r["mean_full"] > 0.9 and r["t_full"] > 10


# ── TV-GEX ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_black76_gamma_matches_finite_difference_of_production_delta():
    C.ensure_data_service_path()
    from fo_iv import black76 as b76

    f, k, t, s, r, h = 24000.0, 24500.0, 20 / 365, 0.14, 0.065, 1.0
    fd = (b76.delta(f + h, k, t, s, True, r) - b76.delta(f - h, k, t, s, True, r)) / (2 * h)
    g = GEX.black76_gamma(np.array([f]), np.array([k]), np.array([t]), np.array([s]), np.array([r]))[0]
    assert math.isclose(g, fd, rel_tol=1e-4)


def _surface(day: str, oi_ce: float, oi_pe: float, n_iv: int = 10) -> pd.DataFrame:
    rows = []
    for e, dte in (("2026-11-10", 5), ("2026-11-17", 12), ("2026-11-24", 19)):
        for i, k in enumerate(range(22000, 26001, 100)):
            iv = (14.0 + abs(k - 24000) / 400.0) if i % (41 // n_iv or 1) == 0 else None
            for side, oi in (("CE", oi_ce), ("PE", oi_pe)):
                rows.append({"date": pd.Timestamp(day), "expiry": pd.Timestamp(e), "strike": float(k), "opt_type": side, "iv": iv,
                             "oi": oi, "forward": 24000.0, "t_years": dte / 365, "r": 0.065})
    return pd.DataFrame(rows)


def test_gex_sign_convention_and_interpolation():
    calls = GEX.day_proxy(_surface("2026-11-05", 1000.0, 0.0))
    puts = GEX.day_proxy(_surface("2026-11-05", 0.0, 1000.0))
    both = GEX.day_proxy(_surface("2026-11-05", 1000.0, 1000.0))
    assert math.isclose(calls["NGS"], 1.0) and math.isclose(puts["NGS"], -1.0) and abs(both["NGS"]) < 1e-9
    assert calls["n_expiries"] == 3 and calls["dg_total_cr"] > 0
    sf = _surface("2026-11-05", 1.0, 1.0)
    g = sf[sf["expiry"] == pd.Timestamp("2026-11-10")]
    per = GEX.strike_sigmas(g)
    assert per is not None and per["sigma"].notna().all()
    known = g.dropna(subset=["iv"]).groupby("strike")["iv"].mean() / 100
    assert np.allclose(per.set_index("strike").loc[known.index, "sigma"], known)          # own IV kept
    hi = known.index.max()
    assert per.set_index("strike").loc[per["strike"].max(), "sigma"] == pytest.approx(known.loc[hi])  # flat beyond the wing
    few = g.copy()
    few.loc[few["strike"] > 22300, "iv"] = None
    assert GEX.strike_sigmas(few) is None                                                  # < 4 IV-bearing strikes


def test_gex_zero_gamma_exists_when_calls_sit_above_and_puts_below():
    s = _surface("2026-11-05", 0.0, 0.0)
    s.loc[(s["opt_type"] == "CE") & (s["strike"] >= 24500), "oi"] = 1000.0
    s.loc[(s["opt_type"] == "PE") & (s["strike"] <= 23500), "oi"] = 1000.0
    p = GEX.day_proxy(s)
    assert math.isfinite(p["zero_gamma_x"]) and 0.95 < p["zero_gamma_x"] < 1.05


# ── TV-DRIVERS ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_drivers_fit_gate_and_event_thinning():
    idx = _bdays(200)
    fit = pd.DataFrame({"residual_points": 1.0, "prev_index_level": 20000.0, "members_priced": 50}, index=idx)
    fit.loc[idx[120], "members_priced"] = 30                                                # one bad session
    g = DRV.fit_gate(fit)
    bad = 120
    assert not g["decision_ok"].iloc[bad - 21] and not g["decision_ok"].iloc[bad + 19]      # windows touching it are out
    assert g["decision_ok"].iloc[bad - 22] and g["decision_ok"].iloc[bad + 20]
    lead = pd.Series(["A"] * 10 + ["B"] * 5 + ["C"] * 30 + ["D"] * 155, index=idx)
    ev = DRV.events({"sessions": idx}, lead, pd.Series(True, index=idx))
    assert list(ev) == [idx[10], idx[45]]                                                  # C at +5 is thinned away


def test_drivers_signed_persistence_planted_and_placebo():
    rng = np.random.default_rng(8)
    idx = _bdays(900)
    syms = [f"S{i}" for i in range(10)]
    rets = pd.DataFrame(rng.normal(0, 0.01, (900, 10)), index=idx, columns=syms)
    rets["S0"] = 0.004 + rng.normal(0, 0.01, 900)                                          # a persistent driver
    w = pd.DataFrame(0.1, index=idx, columns=syms)
    level = pd.Series(10000 * np.cumprod(1 + rets.mean(axis=1)), index=idx)
    pts = rets.mul(w).mul(level.shift(1).fillna(10000), axis=0)
    p0 = pts.fillna(0.0)
    p = {"sessions": idx, "pts": pts, "wts": w, "w20": p0.rolling(20, min_periods=20).sum(), "f20": p0.rolling(20).sum().shift(-21),
         "r_fwd": np.expm1(np.log1p(rets).rolling(20).sum()).shift(-21) * 100, "level": level, "R_N": C.forward_ret(level)}
    lead = pd.Series("S0", index=idx, dtype=object)
    y, _s = DRV.d2_series(p, lead)
    st = C.mean_by_halves(y.dropna(), 19, "2020-10-31")
    assert st["t_full"] > 2 and st["t_h1"] > 2 and st["t_h2"] > 2
    p["wlead"] = pd.Series("S5", index=idx, dtype=object)
    rnd = DRV.random_weight_leader(p, seed=1)
    noise = pd.Series([x if x != "S0" else "S1" for x in rnd], index=idx, dtype=object)     # never the planted name
    yn, _ = DRV.d2_series(p, noise)
    sn = C.mean_by_halves(yn.dropna(), 19, "2020-10-31")
    assert not C.meets(sn["t_full"], sn["t_h1"], sn["t_h2"], +1)


# ── honest exits and outputs ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("mod", [IVRV, GEX, DRV])
def test_scripts_exit_3_on_an_empty_store(tmp_path, mod, capsys):
    db = tmp_path / "empty.duckdb"
    duckdb.connect(str(db)).close()
    with pytest.raises(SystemExit) as e:
        mod.main(["--db", str(db), "--out-dir", str(tmp_path / "out")])
    assert e.value.code == C.EXIT_NOT_INGESTED
    assert not (tmp_path / "out").exists()


def test_outputs_are_stamped_provisional(tmp_path):
    C.write_outputs(tmp_path, summary={"x": float("nan")}, report_md="# R\n\nbody\n", findings_md="# F\n\nrows\n", findings_row_md="| a |\n",
                    results={"t": pd.DataFrame({"a": [1]})}, provisional=True, results_dir=tmp_path / "results")
    rep = (tmp_path / "REPORT.md").read_text()
    has = rep.startswith("# R\n\n**PROVISIONAL**")
    assert has, "PROVISIONAL banner missing under the heading"
    assert (tmp_path / "summary.json").read_text().count("null") == 1                      # NaN → null, valid JSON
    assert (tmp_path / "results" / "t.csv").exists()


def test_per_session_frames_never_land_under_reports():
    d = C.default_results_dir(C.STUDIES_DIR / "iv_rv")                                     # NSE prices: public repo, no redistribution
    inside = str(d.resolve()).startswith(str((C.ROOT / "reports").resolve()))
    assert not inside, f"default results dir {d} is under reports/"


# ── the pre-registration itself ───────────────────────────────────────────────────────────────────────────────────

PLANS = {"iv_rv": (IVRV, "30 Sep 2023"), "drivers": (DRV, "30 Apr 2023"), "gex": (GEX, "31 Mar 2023")}


@pytest.mark.parametrize("name", sorted(PLANS))
def test_plans_predate_results_and_match_the_code(name):
    mod, split_text = PLANS[name]
    text = (C.STUDIES_DIR / name / "PLAN.md").read_text(encoding="utf-8")
    checks = {"before any result": "before any result was computed" in text, "split date": split_text in text,
              "verdict rule": "## Verdict rule" in text, "controls": "## Negative controls" in text, "costs": "## Costs" in text,
              "halves": "## Halves" in text, "code split": pd.Timestamp(mod.SPLIT).strftime("%d %b %Y").lstrip("0") in text
              or pd.Timestamp(mod.SPLIT).strftime("%d %b %Y") in text}
    missing = [k for k, ok in checks.items() if not ok]
    assert not missing, f"{name}/PLAN.md lacks {missing}"


def test_gex_plan_signs_match_the_code():
    text = (C.STUDIES_DIR / "gex" / "PLAN.md").read_text(encoding="utf-8")
    x1 = re.search(r"\| X1 \| NGS \(C1\) \| \*\*(.)\*\*", text)
    x2 = re.search(r"\| X2 \| TGL \(C2\) \| \*\*(.)\*\*", text)
    assert x1 and x2, "the registered-sign table is missing"
    assert (x1.group(1) == "−") == (GEX.SIGNS["X1"] == -1) and (x2.group(1) == "+") == (GEX.SIGNS["X2"] == +1)


def test_registry_lists_every_study():
    text = (ROOT / "reports" / "terminal_v2" / "STUDIES.md").read_text(encoding="utf-8")
    for sid, d in (("TV-IVRV", "iv_rv"), ("TV-DRIVERS", "drivers"), ("TV-GEX", "gex")):
        listed = f"| {sid} |" in text and f"reports/terminal_v2/studies/{d}/PLAN.md" in text
        assert listed, f"{sid} missing from STUDIES.md"
    assert {IVRV.STUDY, DRV.STUDY, GEX.STUDY} == {"TV-IVRV", "TV-DRIVERS", "TV-GEX"}


def test_no_network_client_in_the_package():
    pat = re.compile(r"\b(httpx|requests|yfinance|urllib\.request|aiohttp|socket)\b|query[12]\.finance\.yahoo")
    hits = [p.name for p in (ROOT / "scripts" / "terminal_studies").glob("*.py") if pat.search(p.read_text(encoding="utf-8"))]
    assert not hits, f"network client referenced in {hits}"


def test_against_sign_is_reported_but_stays_fail():
    assert C.signed_verdict(-3, -3, -3, +1, traded_ok=True) == C.FAIL
    assert C.against_sign_note(-3, -3, -3, +1) and "AGAINST" in C.against_sign_note(-3, -3, -3, +1)[0]
    assert C.against_sign_note(-2.5, -1, -1, +1) == ["|t| ≥ 2 against the registered sign in the full sample only"]
    assert C.against_sign_note(3, 3, 3, +1) == [] and C.against_sign_note(-3, -3, -3, 0) == []
