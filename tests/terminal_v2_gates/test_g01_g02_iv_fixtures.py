"""G1 / G2 on committed fixtures, so they run on a CI runner without the git-ignored ``data/nse_archive``.

* ``fixtures/udiff_20261104_NIFTY_near.csv.zip`` — the NIFTY index rows (options + futures, expiries ≤ 8 Dec 2026) of NSE's
  public UDiFF F&O bhavcopy for the 4 Nov 2026 session (1,063 of 36,667 rows, the file's own columns). PLAN 1.7's G1 cell
  says "fixture 3 Nov NIFTY: 23,931.23"; the 23,931.23 parity forward is the 4 Nov session's (the 3 Nov file gives
  23,725.07 for the same 9 Nov expiry; R-OPTIONS §3.1 quotes it from the 4 Nov chain) — the date in the PLAN is a typo.
* ``fixtures/legacy_fo01APR2022_NIFTY.csv.zip`` — the NIFTY rows (OPTIDX + FUTIDX) of the legacy ``fo01APR2022bhav`` file.

Both trims were checked against the full cached files when they were cut (identical expiry rows; the summary numbers
asserted below are the full-file values). B1's ``tests/unit/test_iv_eod.py`` / ``tests/test_iv_replay_g2.py`` keep the
full-file versions (they skip without the archive)."""
from __future__ import annotations

import math
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from fo_iv import files as fo_files  # noqa: E402
from fo_iv import iv_eod  # noqa: E402
from fo_iv.black76 import MODEL_VERSION  # noqa: E402
from fo_iv.legacy_parser import parse_legacy  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
UDIFF = FIX / "udiff_20261104_NIFTY_near.csv.zip"
LEGACY = FIX / "legacy_fo01APR2022_NIFTY.csv.zip"
RIV = ROOT / "reports" / "terminal_v2" / "R-IV" / "iv_compare_NIFTY.csv"
R = 0.065
NOW = datetime(2026, 11, 5, 9, 0)  # noqa: DTZ001 — first_seen_at is stored naive IST by the job
SESSION = date(2026, 11, 4)
TOL_VOL_PT = 0.05                                   # G2: within 0.05 vol-pt of R-IV's prototype


@pytest.fixture(scope="module")
def nov4() -> iv_eod.DayResult:
    chain = fo_files.parse_udiff(UDIFF.read_bytes(), source_file=UDIFF.name)
    return iv_eod.compute_day(chain, SESSION, R, symbols={"NIFTY"}, surface_symbols={"NIFTY"}, now=NOW, source_file=UDIFF.name)


# ── G1 on the real 4 Nov NIFTY chain ──────────────────────────────────────────────────────────────────────────────

def test_g1_parity_forward_23931_23_on_the_real_4_nov_chain(nov4):
    e = nov4.expiry.set_index("expiry")
    near = e.loc[date(2026, 11, 9)]
    assert near["forward_source"] == "pcp" and abs(near["forward"] - 23931.23) < 0.01, (near["forward"], near["forward_source"])
    assert abs(nov4.summary.iloc[0]["spot"] - 23960.60) < 0.01           # NSE's underlying price on the option rows
    # the forward grows with T at roughly r − q (no dividend input: parity carries it) — every listed expiry is parity-based
    fwd = e["forward"].sort_index()
    assert set(e["forward_source"]) == {"pcp"} and fwd.is_monotonic_increasing, fwd.to_dict()


def test_g1_model_version_and_r_on_every_row_of_the_real_chain(nov4):
    for name in ("surface", "expiry", "summary"):
        frame = getattr(nov4, name)
        assert len(frame) and set(frame["model_version"]) == {MODEL_VERSION} and set(frame["r"]) == {R}, name


def test_g1_untraded_strikes_have_no_iv_on_the_real_chain(nov4):
    s = nov4.surface
    silent = s[s["price_source"] == "none"]
    traded = s[s["price_source"] == "close"]
    assert len(silent) > 50 and silent["iv"].isna().all() and silent["price"].isna().all()
    # negative control: the traded strikes near the money do carry an IV
    near_money = traded[(traded["strike"] - 23950).abs() <= 500]
    assert len(near_money) > 20 and near_money["iv"].notna().all()


def test_g1_near_skips_the_short_dated_and_iv30_is_bracketed(nov4):
    s = nov4.summary.iloc[0]
    assert s["near_expiry"] == date(2026, 11, 9) and s["near_dte"] == 5 and abs(s["near_atm_iv"] - 14.565) < 0.005
    e = nov4.expiry
    lo, hi = e[e["dte"] < 30]["dte"].max(), e[e["dte"] > 30]["dte"].min()
    assert (lo, hi) == (27, 34) and abs(s["iv30_cm"] - 12.8082) < 0.001          # 1 Dec (27 d) and 8 Dec (34 d) bracket 30
    a = e.set_index("dte")["atm_iv"]
    assert min(a[27], a[34]) <= s["iv30_cm"] <= max(a[27], a[34])


def test_g1_negative_control_an_expiry_day_chain_has_no_near():
    """The same chain re-dated to its own near expiry (T = 0 for 9 Nov): that expiry leaves "near" (and the surface IV)."""
    chain = fo_files.parse_udiff(UDIFF.read_bytes(), source_file=UDIFF.name)
    res = iv_eod.compute_day(chain, date(2026, 11, 9), R, symbols={"NIFTY"}, surface_symbols={"NIFTY"}, now=NOW)
    assert date(2026, 11, 9) not in set(res.expiry["expiry"])
    assert res.summary.iloc[0]["near_expiry"] != date(2026, 11, 9)


def test_g1_legacy_parser_on_the_committed_fo01apr2022_trim():
    c = parse_legacy(LEGACY.read_bytes(), source_file=LEGACY.name)
    assert c["underlying"].isna().all() and set(c["instrument"]) == {"OPT", "FUT"}
    res = iv_eod.compute_day(c, date(2022, 4, 1), R, symbols={"NIFTY"}, surface_symbols={"NIFTY"}, now=NOW, legacy=True)
    m = res.expiry[res.expiry["expiry"] == date(2022, 4, 28)].iloc[0]
    assert abs(m["atm_iv"] - 17.13) < 0.01 and m["n_iv_strikes"] == 96 and m["forward_source"] == "pcp", m.to_dict()
    assert abs(m["skew_25d"] - 3.83) < 0.01
    s = res.summary.iloc[0]
    assert s["spot_source"] == "near_future" and "legacy_file" in s["quality_flags"]
    assert set(res.expiry["model_version"]) == {MODEL_VERSION}


# ── G2's comparison rule, runnable everywhere on the 4 Nov session ───────────────────────────────────────────────

def replay_problems(ours: pd.DataFrame, ref: pd.DataFrame, tol: float = TOL_VOL_PT) -> list[str]:
    """G2's rule: every compared column within ``tol`` vol-pt on every common date (NaN on one side only is a miss)."""
    out: list[str] = []
    pairs = (("near", "near_atm_iv"), ("iv30", "iv30_cm"), ("monthly", "monthly_atm_iv"))
    m = ours.join(ref, how="inner")
    if m.empty:
        return ["no common session"]
    for a, b in pairs:
        for day, x, y in zip(m.index, m[a], m[b], strict=True):
            xa, yb = (None if x is None or (isinstance(x, float) and math.isnan(x)) else float(x),
                      None if y is None or (isinstance(y, float) and math.isnan(y)) else float(y))
            if (xa is None) != (yb is None):
                out.append(f"{day} {a}: one side missing ({xa} vs {yb})")
            elif xa is not None and yb is not None and abs(xa - yb) >= tol:
                out.append(f"{day} {a}: {xa:.3f} vs {yb:.3f}")
    return out


def _ours(res: iv_eod.DayResult) -> pd.DataFrame:
    s = res.summary.iloc[0]
    return pd.DataFrame([{"near": s["near_atm_iv"], "iv30": s["iv30_cm"], "monthly": s["monthly_atm_iv"]}],
                        index=pd.Index([SESSION.isoformat()], name="date"))


def _ref() -> pd.DataFrame:
    return pd.read_csv(RIV).set_index("date")[["near_atm_iv", "iv30_cm", "monthly_atm_iv"]]


def test_g2_the_4_nov_session_matches_r_iv_within_0_05_vol_pt(nov4):
    assert replay_problems(_ours(nov4), _ref()) == []


def test_g2_negative_controls_a_0_06_vol_pt_drift_or_a_missing_value_fails(nov4):
    ours = _ours(nov4)
    drift = ours.copy()
    drift.loc[SESSION.isoformat(), "iv30"] = drift.loc[SESSION.isoformat(), "iv30"] + 0.06
    assert any("iv30" in p for p in replay_problems(drift, _ref()))
    gone = ours.copy()
    gone.loc[SESSION.isoformat(), "monthly"] = float("nan")
    assert any("one side missing" in p for p in replay_problems(gone, _ref()))
    assert replay_problems(ours.rename(index={SESSION.isoformat(): "1999-01-01"}), _ref()) == ["no common session"]
