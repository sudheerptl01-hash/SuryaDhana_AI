"""G1 (Terminal v2 PLAN 1.7): the IV store's method — Black-76 round trip, the parity forward, untraded strikes carry no IV,
expiry-day / T ≤ 2 d rows out of "near", iv30_cm bracketing, rank vs percentile on a synthetic series (rank 21 / pctile 60),
the legacy parser on fo01APR2022bhav (monthly ATM 17.13 %, 96 IV strikes), model_version + r on every row, the realised-vol
estimators and their rolling twin, the event variance split. Every rule has a negative control."""
from __future__ import annotations

# ruff: noqa: DTZ001
import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from fo_iv import black76 as b76  # noqa: E402
from fo_iv import events, iv_eod, realised  # noqa: E402
from fo_iv import files as fo_files  # noqa: E402
from fo_iv.black76 import MODEL_VERSION  # noqa: E402
from fo_iv.files import CONTRACT_COLUMNS  # noqa: E402
from fo_iv.schema import COLUMNS  # noqa: E402

R = 0.065
LEGACY = ROOT / "data" / "nse_archive" / "fo" / "2022" / "fo01APR2022bhav.csv.zip"
NOW = datetime(2026, 11, 5, 0, 0)


# ── synthetic chains ───────────────────────────────────────────────────────────────────────────────────────────────

def _chain(symbol: str, day: date, expiries: dict[int, float], forward: float, *, strikes: np.ndarray | None = None, untraded: set[float] = frozenset(),
           spot: float | None = None, kind: str = "index", skew: float = 0.0) -> pd.DataFrame:
    """Option rows priced with Black-76 at a known forward and vol per expiry (dte → vol); ``untraded`` strikes get volume 0."""
    rows = []
    strikes = strikes if strikes is not None else np.arange(forward * 0.85, forward * 1.15, forward * 0.01)
    for dte, vol in expiries.items():
        exp = day + timedelta(days=dte)
        t = dte / 365.0
        for k in strikes:
            k = float(round(k, 2))
            v = vol + skew * (math.log(forward / k))          # a put-side smile when skew > 0
            for side, call in (("CE", True), ("PE", False)):
                px = b76.price(forward, k, t, v, call, R)
                traded = k not in untraded
                rows.append({"symbol": symbol, "kind": kind, "instrument": "OPT", "expiry": exp, "strike": k, "opt_type": side, "close": round(px, 2),
                             "settle": round(px, 2), "volume": 100.0 if traded else 0.0, "oi": 1000.0, "oi_chg": 10.0, "lot": 65,
                             "underlying": spot, "source_file": "synthetic"})
        rows.append({"symbol": symbol, "kind": kind, "instrument": "FUT", "expiry": exp, "strike": 0.0, "opt_type": None, "close": forward,
                     "settle": forward, "volume": 100.0, "oi": 1.0, "oi_chg": 0.0, "lot": 65, "underlying": spot, "source_file": "synthetic"})
    return pd.DataFrame(rows, columns=CONTRACT_COLUMNS)


# ── Black-76 ───────────────────────────────────────────────────────────────────────────────────────────────────────

def test_black76_round_trip_and_bounds():
    f, t = 24000.0, 30 / 365
    for k, vol, call in ((23500.0, 0.14, True), (24500.0, 0.12, False), (24000.0, 0.2, True)):
        px = b76.price(f, k, t, vol, call, R)
        assert abs(b76.implied_vol(px, f, k, t, call, R) - vol) < 1e-4
    assert b76.implied_vol(None, f, 24000, t, True, R) is None
    assert b76.implied_vol(0.01, f, 23000, t, True, R) is None            # below intrinsic + pad → no IV (negative control)
    assert b76.implied_vol(px, f, 24000, 0.0, True, R) is None            # T = 0 → no IV
    assert 0 < b76.delta(f, 23500, t, 0.14, True, R) < 1 and -1 < b76.delta(f, 24500, t, 0.12, False, R) < 0
    assert b76.vega(f, 24000, t, 0.14, R) > 0
    assert abs(b76.forward_from_parity(24000, 300.0, 250.0, t, R) - (24000 + 50 * math.exp(R * t))) < 1e-9


def test_cm_variance_interp_brackets_only():
    assert b76.cm_variance_interp(20, 0.10, 40, 0.20, 30) == pytest.approx(math.sqrt(((0.01 * 20 / 365) * 0.5 + (0.04 * 40 / 365) * 0.5) / (30 / 365)), rel=1e-9)
    assert b76.cm_variance_interp(35, 0.1, 60, 0.2, 30) is None            # both beyond 30 → no bracket
    assert b76.cm_variance_interp(10, 0.1, 20, 0.2, 30) is None            # both before 30


# ── the parity forward, untraded strikes, near / expiry-day rules ──────────────────────────────────────────────────

def test_parity_forward_is_recovered_and_recorded_on_every_row():
    day = date(2026, 11, 3)
    fwd = 23931.23
    c = _chain("NIFTY", day, {6: 0.14, 20: 0.135, 48: 0.13}, fwd, spot=23810.85)
    res = iv_eod.compute_day(c, day, R, surface_symbols={"NIFTY"}, now=NOW, source_file="synthetic")
    assert res.symbols == 1
    e = res.expiry
    assert set(e["forward_source"]) == {"pcp"}
    assert (e["forward"] - fwd).abs().max() < 1.0, e[["expiry", "forward"]]
    assert (e["atm_iv"] - pd.Series([14.0, 13.5, 13.0])).abs().max() < 0.05
    assert set(e["model_version"]) == {MODEL_VERSION} and set(e["r"]) == {R}
    assert set(res.surface["model_version"]) == {MODEL_VERSION} and set(res.surface["r"]) == {R}
    assert set(res.summary["model_version"]) == {MODEL_VERSION} and set(res.summary["r"]) == {R}
    assert list(res.surface.columns) == COLUMNS["iv_surface_daily"] and list(res.summary.columns) == COLUMNS["iv_summary_daily"]


def test_untraded_strikes_carry_no_iv_but_traded_ones_do():
    day = date(2026, 11, 3)
    strikes = np.arange(22000, 26001, 250, dtype=float)
    silent = {22500.0, 25500.0}
    c = _chain("NIFTY", day, {30: 0.14}, 24000.0, strikes=strikes, untraded=silent, spot=24000.0)
    res = iv_eod.compute_day(c, day, R, surface_symbols={"NIFTY"}, now=NOW)
    s = res.surface
    off = s[s["strike"].isin(silent)]
    assert len(off) == 4 and off["iv"].isna().all() and set(off["price_source"]) == {"none"} and off["price"].isna().all()
    on = s[(~s["strike"].isin(silent)) & (s["strike"].between(23500, 24500))]
    assert on["iv"].notna().all() and set(on["price_source"]) == {"close"}           # negative control: traded strikes have an IV


def test_expiry_day_and_short_dte_rows_stay_in_the_surface_but_out_of_near():
    day = date(2026, 11, 3)
    c = _chain("NIFTY", day, {0: 0.3, 1: 0.25, 2: 0.2, 6: 0.14, 34: 0.13}, 24000.0, spot=24000.0)
    res = iv_eod.compute_day(c, day, R, surface_symbols={"NIFTY"}, now=NOW)
    e = res.expiry.set_index("dte")
    assert 0 not in e.index                                               # T = 0 → nothing computable
    assert {1, 2} <= set(e.index) and all("short_dte" in str(e.at[d, "quality_flags"]) for d in (1, 2))
    s = res.summary.iloc[0]
    assert s["near_dte"] == 6 and abs(s["near_atm_iv"] - 14.0) < 0.05     # near skips dte ≤ 2
    assert s["iv30_cm"] is not None and 13.0 < s["iv30_cm"] < 14.0        # bracketed by 6 and 34


def test_iv30_cm_needs_a_bracket():
    day = date(2026, 11, 3)
    # M43: one expiry inside 10–60 d and no bracket → IV30 is that expiry's ATM IV, flagged cm30_flat (never silent)
    one = _chain("NIFTY", day, {20: 0.14}, 24000.0, spot=24000.0)
    res = iv_eod.compute_day(one, day, R, now=NOW)
    s = res.summary.iloc[0]
    assert abs(s["iv30_cm"] - 14.0) < 0.05 and "cm30_flat" in s["quality_flags"] and "no_cm30" not in s["quality_flags"]
    # negative control: the only expiry is 5 days out (outside 10–60) → no IV30, flagged no_cm30
    short = _chain("NIFTY", day, {5: 0.14}, 24000.0, spot=24000.0)
    s0 = iv_eod.compute_day(short, day, R, now=NOW).summary.iloc[0]
    assert s0["iv30_cm"] is None and "no_cm30" in s0["quality_flags"] and "cm30_flat" not in s0["quality_flags"]
    two = _chain("NIFTY", day, {20: 0.10, 40: 0.20}, 24000.0, spot=24000.0)
    s2 = iv_eod.compute_day(two, day, R, now=NOW).summary.iloc[0]
    # var30 = (0.01·20/365·½ + 0.04·40/365·½) / (30/365) = 0.0300 → 17.32 %
    assert abs(s2["iv30_cm"] - 17.32) < 0.1 and s2["term_slope_30_90"] is None


def test_pcp_forward_falls_back_to_the_future_when_they_disagree():
    day = date(2026, 11, 3)
    c = _chain("NIFTY", day, {30: 0.14}, 24000.0, spot=24000.0)
    c.loc[c["instrument"] == "FUT", "close"] = 24400.0                    # 1.7 % away from the parity forward
    e = iv_eod.compute_day(c, day, R, now=NOW).expiry.iloc[0]
    assert e["forward_source"] == "future" and "pcp_fallback_future" in e["quality_flags"] and e["forward"] == 24400.0
    c.loc[c["instrument"] == "FUT", "close"] = 24050.0                    # within 0.5 %: parity stands (negative control)
    e2 = iv_eod.compute_day(c, day, R, now=NOW).expiry.iloc[0]
    assert e2["forward_source"] == "pcp"


# ── rank vs percentile ─────────────────────────────────────────────────────────────────────────────────────────────

def test_rank_21_and_percentile_60_on_a_synthetic_series():
    today = 12.81
    prior = list(np.linspace(8.5, 12.8, 150)) + list(np.linspace(13.0, 28.87, 100))      # 150 below, 100 above
    rank, pct = iv_eod.rank_and_percentile(prior, today)
    assert round(rank) == 21 and pct == 60.0
    assert iv_eod.rank_and_percentile(prior[:10], today) == (None, None)                 # negative control: too few observations
    assert iv_eod.rank_and_percentile(prior, None) == (None, None)
    rank_hi, pct_hi = iv_eod.rank_and_percentile(prior, 30.0)
    assert rank_hi == 100.0 and pct_hi == 100.0


# ── legacy parser ──────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not LEGACY.exists(), reason="cached legacy file not present (data/ is git-ignored)")
def test_legacy_parser_fo01apr2022_monthly_atm_17_13_with_96_iv_strikes():
    day = date(2022, 4, 1)
    c = fo_files.load(LEGACY)
    assert c["underlying"].isna().all() and (c["instrument"] == "OPT").any()
    res = iv_eod.compute_day(c, day, R, symbols={"NIFTY"}, surface_symbols={"NIFTY"}, now=NOW, legacy=True)
    monthly = res.expiry[res.expiry["expiry"] == date(2022, 4, 28)].iloc[0]
    assert abs(monthly["atm_iv"] - 17.13) < 0.05 and monthly["n_iv_strikes"] == 96 and monthly["forward_source"] == "pcp"
    assert abs(monthly["skew_25d"] - 3.83) < 0.05
    s = res.summary.iloc[0]
    assert s["spot_source"] == "near_future" and "legacy_file" in s["quality_flags"] and "spot_from_future" in s["quality_flags"]


def test_legacy_parser_rejects_a_udiff_body():
    from fo_iv.legacy_parser import parse_legacy

    with pytest.raises(ValueError):
        parse_legacy(b"TradDt,FinInstrmTp,TckrSymb\n2026-11-03,IDO,NIFTY\n")


# ── realised vol ───────────────────────────────────────────────────────────────────────────────────────────────────

def _ohlc(n: int = 60, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    prev = np.r_[close[0], close[:-1]]
    opn = prev * np.exp(rng.normal(0, 0.003, n))
    high = np.maximum(opn, close) * np.exp(abs(rng.normal(0, 0.005, n)))
    low = np.minimum(opn, close) * np.exp(-abs(rng.normal(0, 0.005, n)))
    return pd.DataFrame({"date": [date(2026, 1, 1) + timedelta(days=i) for i in range(n)], "open": opn, "high": high, "low": low, "close": close,
                         "prev_close": prev})


def test_realised_estimators_agree_with_the_rolling_cache_and_drop_corporate_actions():
    df = _ohlc()
    single = realised.all_three(df)
    roll = iv_eod.RvCache.rolling(df).iloc[-1]
    for k in ("rv20_cc", "rv20_parkinson", "rv20_yz"):
        assert single[k] is not None and abs(single[k] - roll[k]) < 1e-6, k
    assert 5 < single["rv20_cc"] < 40
    split = df.copy()
    split.loc[split.index[-5], "close"] = split.loc[split.index[-5], "prev_close"] / 5      # a 1:5 split in an unadjusted series
    assert realised.close_to_close(split) == pytest.approx(realised.close_to_close(df.drop(df.index[-5])), rel=0.05)   # the jump day is dropped
    assert realised.parkinson(df.drop(columns=["high", "low"])) is None                     # negative control: no H/L → no Parkinson


# ── events ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_event_variance_split():
    assert events.event_variance_split(40.0, 8, 25.0, 36) is not None and events.event_variance_split(40.0, 8, 25.0, 36) > 3
    assert events.event_variance_split(20.0, 8, 25.0, 36) is None            # no event premium in the near expiry
    assert events.event_variance_split(40.0, 36, 25.0, 8) is None            # mis-ordered expiries
