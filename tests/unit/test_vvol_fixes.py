"""V-VOL (fix wave 2, 6 Nov 2026): the volatility-correctness fixes from the 5 Nov 43-page review, each rule with a negative
control. M04 one time convention + one forward / ATM IV for the chain and the store; M05 chain units; M06 the range-outlier
rule (INFY's bad 23 Oct low), the late-entrant RV cache and the ``iv_repair`` job; M43 IV30 flat fill, % MWPL from the merged
combined-OI row, BAN from NSE's list; M44 the SPAN-file ingest; M02 paid vs delivered over each monthly option's own life;
M03 the near-expiry skew series; m001 / m064 / m065 the DERV VIX source, date and calendar roll."""
from __future__ import annotations

# ruff: noqa: DTZ001
import io
import math
import sys
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

import nse_positions as npz  # noqa: E402
import option_chain as oc  # noqa: E402
from fo_iv import black76 as b76  # noqa: E402
from fo_iv import iv_eod, jobs, reads, realised  # noqa: E402
from fo_iv.files import CONTRACT_COLUMNS  # noqa: E402

FIX = ROOT / "tests" / "unit" / "fixtures" / "terminal_v2"
R = 0.065
NOW = datetime(2026, 11, 6, 3, 0)


@pytest.fixture
def store(tmp_path):
    from storage.duckdb_store import DuckDBStore

    s = DuckDBStore(str(tmp_path / "v.duckdb"))
    yield s
    s.close()


# ── M04: one time convention ───────────────────────────────────────────────────────────────────────────────────────

def test_t_years_end_of_day_is_whole_days_and_intraday_is_fractional():
    exp = date(2026, 11, 9)
    assert b76.t_years(exp, date(2026, 11, 5)) == pytest.approx(4 / 365)                  # EOD: the 15:30 close → whole days
    assert b76.t_years(exp, datetime(2026, 11, 5, 15, 30)) == pytest.approx(4 / 365)      # the close itself = the EOD value
    assert b76.t_years(exp, datetime(2026, 11, 9, 12, 0)) == pytest.approx(3.5 / 24 / 365)  # expiry day, 3.5 h left
    assert b76.t_years(exp, datetime(2026, 11, 9, 16, 0)) == 0.0                           # past the expiry close → 0
    # negative control: the retired chain rule (+ half a day) is NOT the convention
    assert b76.t_years(exp, date(2026, 11, 5)) != pytest.approx(4.5 / 365)


def _bhav(day: str, expiry: str, forward: float, vol: float, *, lot: int = 65, untraded: set[float] = frozenset()) -> pd.DataFrame:
    """A UDiFF-shaped chain priced with Black-76 at T = whole days ÷ 365 (the convention), parity-consistent."""
    t = (pd.Timestamp(expiry) - pd.Timestamp(day)).days / 365
    rows = []
    for k in np.arange(forward * 0.9, forward * 1.1, 50.0):
        k = float(round(k / 50) * 50)
        for side, call in (("CE", True), ("PE", False)):
            px = b76.price(forward, k, t, vol + 0.02 * math.log(forward / k), call, R)
            traded = k not in untraded
            rows.append({"TradDt": pd.Timestamp(day), "FinInstrmTp": "IDO", "TckrSymb": "NIFTY", "XpryDt": pd.Timestamp(expiry), "StrkPric": k,
                         "OptnTp": side, "ClsPric": round(px, 2), "SttlmPric": round(px, 2), "UndrlygPric": forward * math.exp(-R * t),
                         "OpnIntrst": 6500.0 * (3 if (side == "CE" and k == 25000) else 1), "ChngInOpnIntrst": 650.0,
                         "TtlTradgVol": 0.0 if not traded else 120.0, "NewBrdLotQty": lot})
    return pd.DataFrame(rows).drop_duplicates(["StrkPric", "OptnTp"])


def _as_contracts(b: pd.DataFrame) -> pd.DataFrame:
    """The same chain in the IV store's contracts frame (fo_iv.files layout)."""
    out = pd.DataFrame({"symbol": b["TckrSymb"], "kind": "index", "instrument": "OPT", "expiry": b["XpryDt"].dt.date, "strike": b["StrkPric"],
                        "opt_type": b["OptnTp"], "close": b["ClsPric"], "settle": b["SttlmPric"], "volume": b["TtlTradgVol"], "oi": b["OpnIntrst"],
                        "oi_chg": b["ChngInOpnIntrst"], "lot": b["NewBrdLotQty"], "underlying": b["UndrlygPric"], "source_file": "synthetic"})
    return out[CONTRACT_COLUMNS]


def test_one_expiry_prints_one_atm_iv_on_the_chain_and_in_the_store():
    b = _bhav("2026-11-05", "2026-11-09", 24545.75, 0.154)
    c = oc.chain(b, "NIFTY")
    res = iv_eod.compute_day(_as_contracts(b), date(2026, 11, 5), R, now=NOW)
    e = res.expiry.iloc[0]
    assert c["forward"] == pytest.approx(e["forward"], abs=0.01) and c["forward_source"] == "put-call parity" and e["forward_source"] == "pcp"
    assert c["atm_iv"] == pytest.approx(e["atm_iv"], abs=0.01)                             # the M04 defect: 14.6 vs 15.4
    assert c["t_days"] == 4.0 and c["time_convention"] == b76.TIME_CONVENTION and c["model_version"] == b76.MODEL_VERSION
    assert iv_eod.PCP_FUTURE_TOL == b76.PCP_FUTURE_TOL                                    # one parity-vs-future tolerance
    # negative control: solving the same premiums with the retired half-day T gives a LOWER IV (the 0.8-pt gap of 5 Nov)
    atm = min(c["rows"], key=lambda r: abs(r["strike"] - c["forward"]))
    t_old = 4.5 / 365
    iv_old = b76.implied_vol(atm["ce"]["price"], c["forward"], atm["strike"], t_old, True, R)
    assert iv_old is not None and iv_old * 100 < c["atm_iv"] - 0.5


def test_chain_units_traded_flags_and_the_wall_row():
    b = _bhav("2026-11-05", "2026-11-23", 24000.0, 0.14, untraded={24100.0})
    b.loc[(b["StrkPric"] == 22000.0) & (b["OptnTp"] == "PE"), "OpnIntrst"] = 6500.0 * 40     # the put wall, 8.3 % below
    c = oc.chain(b, "NIFTY")
    r = next(x for x in c["rows"] if x["strike"] == 25000.0)
    assert r["ce"]["oi"] == 19500.0 and r["ce"]["oi_contracts"] == 300.0 and r["ce"]["oi_chg_contracts"] == 10.0      # shares ÷ lot 65
    assert c["units"]["volume"] == "contracts" and c["units"]["oi"] == "shares" and c["call_oi_total_contracts"] == c["call_oi_total"] / 65
    u = next(x for x in c["rows"] if x["strike"] == 24100.0)
    assert u["ce"]["traded"] is False and u["ce"]["iv"] is None and u["ce"]["price"] is not None                 # settlement, marked
    assert next(x for x in c["rows"] if x["strike"] == 24200.0)["ce"]["traded"] is True
    assert c["support"][0] == 22000.0 and c["rows"][0]["strike"] == 22000.0                  # m048: the wall's own row is on the page
    # negative control: a wall beyond 2 × the window stays an edge marker (no 30-row stretch of the table)
    b2 = _bhav("2026-11-05", "2026-11-23", 24000.0, 0.14)
    far = b2[b2["StrkPric"] == b2["StrkPric"].max()].copy().assign(StrkPric=19000.0, OpnIntrst=6500.0 * 90)
    c2 = oc.chain(pd.concat([b2, far]), "NIFTY")
    assert c2["support"][0] == 19000.0 and c2["rows"][0]["strike"] > 21000.0


def test_live_chain_values_at_the_snapshot_clock():
    s = 22_400.0

    def leg(k: float, call: bool, t_days: float) -> dict:
        px = b76.price(s, k, t_days / 365, 0.14, call, R)
        return {"strikePrice": k, "expiryDate": "13-10-2026", "lastPrice": round(px, 2), "openInterest": 100, "changeinOpenInterest": 1,
                "totalTradedVolume": 500, "underlyingValue": s * math.exp(-R * t_days / 365)}
    t_days = 1 + 4.5 / 24                                              # 11:00 IST on 12 Oct → 13 Oct 15:30
    data = [{"strikePrice": k, "expiryDates": "13-Oct-2026", "CE": leg(k, True, t_days), "PE": leg(k, False, t_days)} for k in range(21_900, 22_950, 50)]
    df = oc.live_frame({"records": {"data": data, "underlyingValue": s}}, "NIFTY", lot=65, now=datetime(2026, 10, 12, 11, 0))
    out = oc.chain(df, "NIFTY")
    assert out["t_days"] == pytest.approx(t_days, abs=1e-4) and out["atm_iv"] == pytest.approx(14.0, abs=0.3)
    # negative control: the same prices valued at the close (whole days) read a different IV
    df_close = oc.live_frame({"records": {"data": data, "underlyingValue": s}}, "NIFTY", lot=65, today=date(2026, 10, 12))
    assert abs(oc.chain(df_close, "NIFTY")["atm_iv"] - 14.0) > 0.5


# ── M06: realised vol ──────────────────────────────────────────────────────────────────────────────────────────────

def _ohlc(n: int = 90, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 1000 * np.exp(np.cumsum(rng.normal(0, 0.015, n)))
    prev = np.r_[close[0], close[:-1]]
    opn = prev * np.exp(rng.normal(0, 0.005, n))
    high = np.maximum(opn, close) * np.exp(abs(rng.normal(0, 0.006, n)))
    low = np.minimum(opn, close) * np.exp(-abs(rng.normal(0, 0.006, n)))
    return pd.DataFrame({"date": [date(2026, 6, 1) + timedelta(days=i) for i in range(n)], "open": opn, "high": high, "low": low,
                         "close": close, "prev_close": prev})


def test_a_bad_low_print_leaves_the_range_estimators_and_a_trend_day_does_not():
    df = _ohlc()
    clean = realised.all_three(df)
    bad = df.copy()
    i = bad.index[-8]
    bad.loc[i, "low"] = min(bad.loc[i, "open"], bad.loc[i, "close"]) * 0.90        # INFY 23 Oct: a 10 % wick, the close back near the open
    got = realised.all_three(bad)
    assert realised.outlier_dates(bad) == [bad.loc[i, "date"]]
    assert got["rv20_cc"] == pytest.approx(clean["rv20_cc"])                        # close-to-close keeps the session
    assert abs(got["rv20_yz"] - clean["rv20_yz"]) < 0.15 * clean["rv20_yz"] and abs(got["rv20_parkinson"] - clean["rv20_parkinson"]) < 0.15 * clean["rv20_parkinson"]
    roll = iv_eod.RvCache.rolling(bad).iloc[-1]                                     # the rolling twin applies the same rule
    for k in ("rv20_cc", "rv20_parkinson", "rv20_yz"):
        assert roll[k] == pytest.approx(got[k], rel=1e-9), k
    assert bool(roll["range_outlier"])
    # negative control 1: the old estimator (no rule) is blown up by the same print
    d = realised._clean(bad).tail(20)
    u, dn, c = np.log(d["high"] / d["open"]), np.log(d["low"] / d["open"]), np.log(d["close"] / d["open"])
    rs_all = (u * (u - c) + dn * (dn - c)).mean() * 252
    assert rs_all > 2 * realised.rs_terms(d[~realised.range_outliers(realised._clean(bad)).tail(20).to_numpy()]).mean() * 252
    # negative control 2: a −9 % TREND day (close at the low) is real volatility and is never flagged
    trend = df.copy()
    trend.loc[i, "close"] = trend.loc[i, "open"] * 0.91
    trend.loc[i, "low"] = trend.loc[i, "close"] * 0.999
    trend.loc[trend.index[-7], "prev_close"] = trend.loc[i, "close"]
    assert realised.outlier_dates(trend) == []


def test_enrich_never_files_yesterdays_rv_under_today(store):
    day = date(2026, 11, 4)
    rows = []
    for k, d in enumerate(pd.bdate_range("2026-08-01", "2026-11-03")):
        rows.append({"symbol": "NIFTY 50", "date": d.date(), "open": 24000 + k, "high": 24100 + k, "low": 23900 + k, "close": 24050 + k * 1.5,
                     "source": "nse_daily_file", "first_seen_at": NOW})
    store.write("INSERT INTO index_ohlc_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(rows)})
    summ = pd.DataFrame([{**{c: None for c in iv_eod.COLUMNS["iv_summary_daily"]}, "date": day, "symbol": "NIFTY", "iv30_cm": 13.0}])
    out = iv_eod.enrich(store, summ, day, history=iv_eod.IvHistory(store, day))
    assert out.iloc[0]["rv20_cc"] is None and "rv_input_missing" in out.iloc[0]["quality_flags"]   # 4 Nov's OHLC not stored yet
    # negative control: once the session's own row is stored, RV is computed
    store.write("INSERT INTO index_ohlc_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame([{**rows[-1], "date": day}])})
    out2 = iv_eod.enrich(store, summ, day, history=iv_eod.IvHistory(store, day))
    assert out2.iloc[0]["rv20_cc"] is not None and out2.iloc[0]["iv_minus_rv20"] == pytest.approx(13.0 - out2.iloc[0]["rv20_cc"], abs=1e-4)


def test_iv_repair_fills_late_entrants_flat_iv30_and_ranks(store):
    days = [d.date() for d in pd.bdate_range("2026-07-01", "2026-11-05")]
    ohlc = _ohlc(len(days) + 30, seed=11)
    bh = []
    for d, r in zip([d.date() for d in pd.bdate_range(end="2026-11-05", periods=len(days) + 30)], ohlc.itertuples(index=False), strict=True):
        bh.append({"symbol": "NEWNAME", "series": "EQ", "date": d, "open": r.open, "high": r.high, "low": r.low, "close": r.close, "prev_close": r.prev_close})
    store.write("INSERT INTO nse_bhavcopy BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(bh)})
    summ, exp = [], []
    for k, d in enumerate(days):
        for sym in ("NEWNAME", "NODATA"):
            summ.append({"date": d, "symbol": sym, "iv30_cm": None if k % 2 else 20.0 + k * 0.01, "monthly_atm_iv": 21.0, "quality_flags": "no_cm30" if k % 2 else None,
                         "model_version": "b76-pcp-v1", "first_seen_at": NOW})
            exp.append({"date": d, "symbol": sym, "expiry": d + timedelta(days=18), "dte": 18, "atm_iv": 19.5, "model_version": "b76-pcp-v1", "first_seen_at": NOW})
    store.write("INSERT INTO iv_summary_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(summ)})
    store.write("INSERT INTO iv_expiry_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(exp)})
    out = jobs.run_repair(store, now=NOW)
    assert out["status"] == "ok" and out["rows"] == 2 * len(days) and out["iv30_flat"] == len(days)            # odd sessions, both names
    got = store.read("SELECT * FROM iv_summary_daily WHERE date = '2026-11-05' ORDER BY symbol")
    new, nod = got.iloc[0], got.iloc[1]
    assert new["symbol"] == "NEWNAME" and new["rv20_cc"] > 0 and new["rv20_yz"] > 0 and new["iv_rank_252"] is not None
    assert new["iv_minus_rv20"] == pytest.approx(new["iv30_cm"] - new["rv20_cc"], abs=1e-3)
    odd = store.read("SELECT iv30_cm, quality_flags FROM iv_summary_daily WHERE symbol = 'NEWNAME' AND date = ?", [days[1]]).iloc[0]
    assert odd["iv30_cm"] == pytest.approx(19.5) and "cm30_flat" in odd["quality_flags"] and "no_cm30" not in odd["quality_flags"]
    # negative control: a name with no equity rows keeps an empty RV (never borrowed from another symbol)
    assert nod["symbol"] == "NODATA" and pd.isna(nod["rv20_cc"]) and pd.isna(nod["iv_minus_rv20"])
    assert jobs.run_repair(store, now=NOW)["iv30_flat"] == out["iv30_flat"]                                      # idempotent


# ── M02 / M03 / M44 reads ──────────────────────────────────────────────────────────────────────────────────────────

def test_paid_vs_delivered_uses_monthlies_at_30_dte_and_the_options_own_life(store):
    sessions = [d.date() for d in pd.bdate_range("2026-08-03", "2026-11-05")]
    expiries = [date(2026, 9, 29), date(2026, 10, 27), date(2026, 11, 24)]
    weeklies = [d for d in (date(2026, 9, 8) + timedelta(days=7 * i) for i in range(12)) if d not in expiries]
    exp_rows = []
    for d in sessions:
        for e in [*expiries, *weeklies]:
            if 0 < (e - d).days <= 60:
                exp_rows.append({"date": d, "symbol": "NIFTY", "expiry": e, "dte": (e - d).days, "atm_iv": 14.0 if e in expiries else 30.0,
                                 "model_version": "b76-pcp-v1", "first_seen_at": NOW})
    store.write("INSERT INTO iv_expiry_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(exp_rows)})
    rng = np.random.default_rng(5)
    close = 24000 * np.exp(np.cumsum(rng.normal(0, 0.01 / 1.0, len(sessions))))      # ≈ 15.9 % a year
    store.write("INSERT INTO index_ohlc_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(
        {"symbol": "NIFTY 50", "date": sessions, "open": close, "high": close, "low": close, "close": close, "source": "nse_daily_file", "first_seen_at": NOW})})
    out = reads.paid_vs_delivered(store, "NIFTY", n=12)
    rows = {r["expiry"]: r for r in out["rows"]}
    assert set(rows) == {"2026-09-29", "2026-10-27", "2026-11-24"}                      # monthlies only: a weekly is never picked
    sep = rows["2026-09-29"]
    assert sep["iv_paid"] == 14.0 and 25 <= sep["entry_dte"] <= 35 and sep["sessions"] >= 18
    entry = date.fromisoformat(sep["entry"])
    life = [(c1, c0) for d, c1, c0 in zip(sessions[1:], close[1:], close[:-1], strict=True) if entry < d <= date(2026, 9, 29)]
    want = math.sqrt(np.mean([math.log(a / b) ** 2 for a, b in life]) * 252) * 100
    assert sep["rv_delivered"] == pytest.approx(want, abs=1e-3) and sep["paid_minus_delivered"] == pytest.approx(14.0 - want, abs=1e-3)
    assert rows["2026-11-24"]["open"] is True and rows["2026-11-24"]["rv_delivered"] is None   # still open: nothing delivered yet
    assert out["closed"] == 2 and out["badge"] == "context" and out["verdict"].endswith("does not predict the next")
    # negative control: the trailing RV20 the old ledger used is not the option's own-life number
    trailing = realised.close_to_close(pd.DataFrame({"date": sessions, "close": close, "prev_close": np.r_[close[0], close[:-1]]})[
        [d <= entry for d in sessions]])
    assert trailing is not None and abs(trailing - sep["rv_delivered"]) > 1e-3


def test_near_skew_series_is_the_first_expiry_beyond_two_days(store):
    rows = []
    for d, items in ((date(2026, 11, 4), [(date(2026, 11, 5), 1, 9.0), (date(2026, 11, 9), 5, -0.07), (date(2026, 11, 23), 19, 1.1)]),
                     (date(2026, 11, 5), [(date(2026, 11, 9), 4, -0.78), (date(2026, 11, 23), 18, 1.07)])):
        for e, dte, sk in items:
            rows.append({"date": d, "symbol": "NIFTY", "expiry": e, "dte": dte, "atm_iv": 14.0, "skew_25d": sk, "model_version": "b76-pcp-v1",
                         "first_seen_at": NOW})
    store.write("INSERT INTO iv_expiry_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(rows)})
    got = reads.near_skew(store, "NIFTY")["rows"]
    assert [(r["date"], r["skew_25d"]) for r in got] == [("2026-11-04", -0.07), ("2026-11-05", -0.78)]   # never the 1-day expiry (9.0)


def test_contract_delta_read_and_the_screen_ban_and_mwpl(store, tmp_path):
    store.write("INSERT INTO nse_contract_delta BY NAME SELECT * FROM f", frames={"f": pd.DataFrame([
        {"date": date(2026, 11, 5), "symbol": "NIFTY", "expiry": date(2026, 11, 9), "strike": 24550.0, "opt_type": t, "delta_factor": v, "first_seen_at": NOW}
        for t, v in (("CE", 0.504765), ("PE", -0.495235))])})
    cd = reads.contract_delta(store, "NIFTY")
    assert cd["as_of"] == "2026-11-05" and cd["expiry"] == "2026-11-09" and len(cd["rows"]) == 2
    # the combined-OI row arrives in two files; the merge keeps both halves whatever the order (M43)
    now = NOW
    npz._write_table(store, "nse_combined_oi", npz.parse_combined_oi_deleq((FIX / "combineoi_deleq_04112026.csv").read_bytes(), date(2026, 11, 5)), now)
    npz._write_table(store, "nse_combined_oi", npz.parse_combined_oi_zip((FIX / "combineoi_05112026_sample.zip").read_bytes(), date(2026, 11, 5)), now)
    k = store.read("SELECT * FROM nse_combined_oi WHERE symbol = 'KAYNES'").iloc[0]
    assert k["mwpl"] == 4679418 and k["notional_oi"] is not None and not pd.isna(k["notional_oi"]) and k["fut_equiv_oi"] == pytest.approx(4001371.29, abs=0.1)
    store.write("INSERT INTO iv_summary_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame([
        {"date": date(2026, 11, 5), "symbol": s, "iv30_cm": 30.0, "model_version": "b76-pcp-v1", "first_seen_at": NOW} for s in ("KAYNES", "INFY", "NIFTY")])})
    ban_dir = tmp_path / "ban"
    ban_dir.mkdir()
    (ban_dir / "2026-11-06.csv").write_text("Securities in Ban For Trade Date 06-NOV-2026:\n1,KAYNES\n")
    sc = reads.contract_screen(store, ban_dir=ban_dir)
    by = {r["symbol"]: r for r in sc["rows"]}
    assert by["KAYNES"]["ban"] is True and by["INFY"]["ban"] is False and sc["ban_date"] == "2026-11-06" and sc["ban_source"] == "NSE fo_secban"
    assert by["KAYNES"]["mwpl_pct"] == pytest.approx(4001371.29 / 4679418 * 100, abs=0.01) and by["INFY"]["mwpl_pct"] == pytest.approx(16.945, abs=0.01)
    # negative control: without NSE's list the 95 % / 80 % rule cannot place KAYNES (85.5 %, inside its band) → unknown, not False
    sc2 = reads.contract_screen(store, ban_dir=tmp_path / "missing")
    assert {r["symbol"]: r["ban"] for r in sc2["rows"]}["KAYNES"] is None and sc2["ban_source"].startswith("MWPL rule")


def test_the_old_replace_wiped_the_other_files_columns(store):
    """Negative control for the merge: a plain upsert of the zip after the deleq file loses notional OI (the 5 Nov state)."""
    from data_health import db as tdb
    from fo_iv.schema import CASTS, COLUMNS

    d = date(2026, 11, 5)
    deleq = npz.parse_combined_oi_deleq((FIX / "combineoi_deleq_04112026.csv").read_bytes(), d).assign(first_seen_at=NOW)
    z = npz.parse_combined_oi_zip((FIX / "combineoi_05112026_sample.zip").read_bytes(), d).assign(first_seen_at=NOW)
    tdb.upsert(store, "nse_combined_oi", deleq, COLUMNS["nse_combined_oi"], CASTS["nse_combined_oi"])
    tdb.upsert(store, "nse_combined_oi", z, COLUMNS["nse_combined_oi"], CASTS["nse_combined_oi"])
    assert pd.isna(store.read("SELECT notional_oi FROM nse_combined_oi WHERE symbol = 'KAYNES'").iloc[0, 0])


# ── M44: the SPAN file ─────────────────────────────────────────────────────────────────────────────────────────────

def _span_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("nsccl.20261105.s.spn", "<spanFile>" + "x" * 200_000 + "</spanFile>")
    return buf.getvalue()


def test_span_file_is_fetched_once_into_the_margin_directory_and_pruned(store, tmp_path, monkeypatch):
    import httpx

    from shared.http_client import PacedClient

    calls: list[str] = []
    body = {"v": _span_zip()}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, content=body["v"], headers={"last-modified": "Thu, 05 Nov 2026 11:26:03 GMT"})

    http = PacedClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    monkeypatch.setattr(npz, "SPAN_KEEP", 2)
    for i in range(3):                                         # three older files already on disk
        (npz.span_dir(tmp_path)).mkdir(parents=True, exist_ok=True)
        (npz.span_dir(tmp_path) / f"nsccl.2026110{i}.s.zip").write_bytes(b"PK old")
    out = npz.ingest_files(store, http, ["nse_span_zip"], date(2026, 11, 5), date(2026, 11, 5), tmp_path)
    target = npz.span_dir(tmp_path) / "nsccl.20261105.s.zip"
    assert target.exists() and target.read_bytes() == body["v"] and calls == ["https://nsearchives.nseindia.com/archives/nsccl/span/nsccl.20261105.s.zip"]
    assert out["datasets"]["nse_span_zip"]["statuses"] == {"downloaded": 1}
    assert sorted(p.name for p in npz.span_dir(tmp_path).iterdir()) == ["nsccl.20261102.s.zip", "nsccl.20261105.s.zip"]    # newest SPAN_KEEP
    npz.ingest_files(store, http, ["nse_span_zip"], date(2026, 11, 5), date(2026, 11, 5), tmp_path)
    assert len(calls) == 1                                     # stored → never fetched again
    # negative control: an HTML bot wall / a non-zip body is never written
    body["v"] = b"PK\x03\x04 not really a zip"
    bad = npz.ingest_span_file(store, http, date(2026, 11, 6), tmp_path)
    assert bad["status"] in ("parse_error", "error") and not (npz.span_dir(tmp_path) / "nsccl.20261106.s.zip").exists()


def test_iv_eod_fetches_the_mwpl_zip_and_span_after_the_pinned_files():
    assert jobs.EOD_FILES == ("index_ohlc_daily", "nse_fo_volt", "nse_contract_delta", "nse_combined_oi")     # the controller's pinned list
    assert set(jobs.EOD_EXTRA_FILES) == {"nse_combined_oi_zip", "nse_span_zip"} and set(jobs.EOD_EXTRA_FILES) <= set(npz.TERMINAL_DATASETS)
    assert "iv_repair" in jobs.JOBS


def test_the_10mb_span_file_waits_outside_the_morning_freeze_window():
    """Round 2 (checker deploy note): the 08:35 morning sweep can re-run iv_eod inside 07:45–09:20 IST; the ≈ 10 MB SPAN zip
    is deferred there (the light MWPL zip is not), and fetched in the evening pass as before."""
    morning = datetime(2026, 11, 6, 3, 5)                       # 08:35 IST
    fetch, deferred = jobs.extra_files_for(morning)
    assert fetch == ["nse_combined_oi_zip"] and deferred == ["nse_span_zip"]
    assert jobs.extra_files_for(datetime(2026, 11, 6, 3, 50)) == (["nse_combined_oi_zip", "nse_span_zip"], [])   # 09:20 IST: window over
    # negative control: the 20:30 evening pass (15:00 UTC) and the 22:45 retry fetch both files
    assert jobs.extra_files_for(datetime(2026, 11, 6, 15, 0)) == (list(jobs.EOD_EXTRA_FILES), [])
    assert jobs.extra_files_for(datetime(2026, 11, 6, 17, 15)) == (list(jobs.EOD_EXTRA_FILES), [])


# ── DERV (fo_analytics): one VIX, a date, the calendar roll ────────────────────────────────────────────────────────

def test_derv_vix_uses_vix_daily_and_prints_a_date():
    import duckdb
    import fo_analytics as fa

    con = duckdb.connect()
    con.execute("CREATE TABLE market_index_daily (symbol VARCHAR, date DATE, close DOUBLE, source VARCHAR, x VARCHAR)")
    con.execute("CREATE TABLE vix_daily (date DATE, close DOUBLE)")
    for i in range(40):
        d = (pd.Timestamp("2026-09-01") + pd.offsets.BDay(i)).date()
        con.execute("INSERT INTO market_index_daily VALUES ('INDIAVIX', ?, ?, 'yahoo', NULL), ('NIFTY50', ?, 24000, 'nse', NULL)", [d, 15.62, d])
        if i >= 10:
            con.execute("INSERT INTO vix_daily VALUES (?, 15.58)", [d])
    out = fa.q_vix(con, 100)
    assert out["level"] == 15.58 and out["source"] == "vix_daily" and len(out["as_of"]) == 10 and "T" not in out["as_of"]
    assert out["rows"][0]["vix"] == 15.62                       # before vix_daily starts, the legacy series fills
    # negative control: without vix_daily the legacy close is what prints (and says so)
    con.execute("DROP TABLE vix_daily")
    assert fa.q_vix(con, 100)["level"] == 15.62 and fa.q_vix(con, 100)["source"] == "market_index_daily"


def test_derv_roll_cost_is_the_calendar_spread_not_the_next_basis():
    import fo_analytics as fa

    r = fa.roll_spread(24546.0, 24677.1, 18, 54)
    assert r["roll_spread_pts"] == pytest.approx(131.1) and r["roll_days"] == 36
    assert r["roll_spread_ann_pct"] == pytest.approx((24677.1 / 24546 - 1) * 100 * 365 / 36, abs=0.01)
    assert fa.roll_spread(None, 24677.1, 18, 54)["roll_spread_pts"] is None            # negative control: no near close → nothing
    assert fa.roll_spread(24546.0, 24677.1, 18, 18)["roll_spread_pts"] is None         # same expiry → no calendar


# ── round 2 (checker notes) ────────────────────────────────────────────────────────────────────────────────────────

def test_iv_repair_expected_move_follows_summarise_near_fallback(store):
    """iv_repair's 1-day expected move uses summarise's base (IV30, else the NEAR ATM IV); IV − RV keeps enrich's base (IV30,
    else the ~1-month IV). The repair used the ~1-month IV for both and blanked 10,558 near-only rows iv_eod fills."""
    d = date(2026, 10, 23)
    store.write("INSERT INTO iv_summary_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame([
        {"date": d, "symbol": "NEARONLY", "iv30_cm": None, "monthly_atm_iv": None, "near_atm_iv": 31.75, "quality_flags": "no_cm30",
         "model_version": "b76-pcp-v1", "first_seen_at": NOW},
        {"date": d, "symbol": "WITHIV30", "iv30_cm": 22.0, "monthly_atm_iv": 23.0, "near_atm_iv": 40.0, "quality_flags": None,
         "model_version": "b76-pcp-v1", "first_seen_at": NOW},
        {"date": d, "symbol": "NOTHING", "iv30_cm": None, "monthly_atm_iv": None, "near_atm_iv": None, "quality_flags": "no_cm30",
         "model_version": "b76-pcp-v1", "first_seen_at": NOW}])})
    jobs.run_repair(store, now=NOW)
    got = store.read("SELECT symbol, iv30_cm, expected_move_1d_pct, iv_minus_rv20 FROM iv_summary_daily ORDER BY symbol").set_index("symbol")
    assert got.loc["NEARONLY", "expected_move_1d_pct"] == pytest.approx(31.75 / math.sqrt(252), abs=1e-4)     # kept, as iv_eod files it
    assert pd.isna(got.loc["NEARONLY", "iv30_cm"]) and pd.isna(got.loc["NEARONLY", "iv_minus_rv20"])          # no IV − RV base → none
    assert got.loc["WITHIV30", "expected_move_1d_pct"] == pytest.approx(22.0 / math.sqrt(252), abs=1e-4)      # IV30 wins over near
    # negative control: a row with no IV at all stays empty (nothing is borrowed)
    assert pd.isna(got.loc["NOTHING", "expected_move_1d_pct"])
    # and summarise's own rule is the same one (fresh EOD rows and repaired history agree)
    s = iv_eod.summarise("X", [{"expiry": date(2026, 10, 27), "dte": 4, "atm_iv": 31.75}], d, R, spot=100.0, spot_source="eq",
                         legacy=False, now=NOW)
    assert s["iv30_cm"] is None and s["expected_move_1d_pct"] == pytest.approx(31.75 / math.sqrt(252), abs=1e-4)


def test_monthly_ledger_skips_a_dead_redated_twin_and_names_a_missing_month(store):
    """NSE re-dated the March 2026 NIFTY monthly 31 → 30 March; the 2026-03-31 rows stop at 95 DTE. The month must use the
    alive 30 March contract (it vanished from the ledger), and a month with no usable row is named in ``skipped``."""
    sessions = [d.date() for d in pd.bdate_range("2026-01-01", "2026-05-05")]
    monthly = [date(2026, 2, 24), date(2026, 3, 30), date(2026, 4, 28)]
    dead = date(2026, 3, 31)
    rows = []
    for d in sessions:
        for e in monthly:
            if 0 < (e - d).days <= 90:
                rows.append({"date": d, "symbol": "NIFTY", "expiry": e, "dte": (e - d).days, "atm_iv": 14.0, "model_version": "b76-pcp-v1",
                             "first_seen_at": NOW})
        if d <= date(2026, 1, 2):                         # the dead twin: listed, then gone at ≈ 88 DTE
            rows.append({"date": d, "symbol": "NIFTY", "expiry": dead, "dte": (dead - d).days, "atm_iv": 15.0, "model_version": "b76-pcp-v1",
                         "first_seen_at": NOW})
    # April's 25–35 DTE rows are missing (a gap in the store): the month must be named, not dropped silently
    rows = [r for r in rows if not (r["expiry"] == date(2026, 4, 28) and 25 <= r["dte"] <= 35)]
    store.write("INSERT INTO iv_expiry_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(rows)})
    close = 24000 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, len(sessions))))
    store.write("INSERT INTO index_ohlc_daily BY NAME SELECT * FROM f", frames={"f": pd.DataFrame(
        {"symbol": "NIFTY 50", "date": sessions, "open": close, "high": close, "low": close, "close": close, "source": "nse_daily_file", "first_seen_at": NOW})})
    out = reads.paid_vs_delivered(store, "NIFTY", n=12)
    got = [r["expiry"] for r in out["rows"]]
    assert "2026-03-30" in got and "2026-03-31" not in got                     # the alive contract, not the dead twin
    assert out["skipped"] == [{"month": "2026-04", "expiry": "2026-04-28", "reason": "no stored ATM IV 25–35 days before the expiry"}]
    # negative control: the old rule (the last LISTED expiry of the month) picks the dead twin
    assert reads.monthly_expiries([*monthly, dead])[1] == dead
    last_seen = {e: max(r["date"] for r in rows if r["expiry"] == e) for e in [*monthly, dead]}
    assert reads.monthly_expiries([*monthly, dead], last_seen, sessions[-1])[1] == date(2026, 3, 30)


def _literal(path: Path, name: str) -> object:
    """A module-level constant read with ast (no import of ui-api's app modules from the core suite)."""
    import ast

    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets) and node.value is not None:
                return ast.literal_eval(node.value)
    raise KeyError(f"{name} not in {path}")


def _convention_mismatches(paths: list[Path]) -> list[str]:
    return [str(p) for p in paths if _literal(p, "TIME_CONVENTION") != b76.TIME_CONVENTION]


def test_one_clock_and_one_rate_literals_are_pinned(tmp_path):
    """ui-api mirrors fo_iv.black76.TIME_CONVENTION as a string literal (it cannot import data-service), and the chain's r is
    the store's default rate: a drift in either brings back two ATM IVs for one expiry (M04)."""
    ui = ROOT / "services" / "ui-api"
    mirrors = [ui / "options_math.py", ui / "routers" / "derivatives.py"]
    assert b76.TIME_CONVENTION == "cal365-1530" and _convention_mismatches(mirrors) == []
    assert oc.RISK_FREE == iv_eod.DEFAULT_R == 0.065
    # negative control: a mirror still on the half-day rule is caught
    stale = tmp_path / "stale.py"
    stale.write_text('TIME_CONVENTION = "cal365-1530+half"\n')
    assert _convention_mismatches([*mirrors, stale]) == [str(stale)]
