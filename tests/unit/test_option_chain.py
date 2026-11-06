"""EOD option chain (services/data-service/option_chain.py): Black–Scholes inversion, max pain, chain assembly."""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
import option_chain as oc  # noqa: E402


@pytest.mark.parametrize("call", [True, False])
def test_implied_vol_recovers_the_input_vol(call):
    s, k, t, v = 22_500.0, 22_800.0, 20 / 365, 0.14
    px = oc.bs_price(s, k, t, v, call)
    assert oc.implied_vol(px, s, k, t, call) == pytest.approx(v, abs=1e-4)


def test_implied_vol_rejects_prices_below_intrinsic():
    assert oc.implied_vol(10.0, 22_500.0, 22_000.0, 10 / 365, True) is None      # intrinsic ≈ 500


def test_max_pain_is_where_writers_pay_least():
    strikes = np.array([100.0, 110.0, 120.0])
    # calls 1,000 @100, puts 3,000 @120 → payout at 100: 60,000; at 110: 40,000; at 120: 20,000
    assert oc.max_pain(strikes, np.array([1000.0, 0, 0]), np.array([0, 0, 3000.0])) == 120.0


def _bhav(spot=22_500.0, t_days=10, vol=0.12):
    rows, t = [], t_days / 365
    exp = pd.Timestamp("2026-10-19")
    for k in np.arange(21_500, 23_600, 100.0):
        for kind, call in (("CE", True), ("PE", False)):
            px = oc.bs_price(spot, k, t, vol, call)            # T = whole days ÷ 365 at the close (black76.TIME_CONVENTION)
            rows.append({"TradDt": pd.Timestamp("2026-10-09"), "FinInstrmTp": "IDO", "TckrSymb": "NIFTY", "XpryDt": exp,
                         "StrkPric": k, "OptnTp": kind, "ClsPric": px, "SttlmPric": px, "UndrlygPric": spot,
                         "OpnIntrst": 5000.0 if (kind == "CE" and k == 23_000) or (kind == "PE" and k == 22_000) else 100.0,
                         "ChngInOpnIntrst": 0.0, "TtlTradgVol": 10.0, "NewBrdLotQty": 65})
    return pd.DataFrame(rows)


def test_chain_finds_atm_iv_walls_and_pcr():
    c = oc.chain(_bhav(), "NIFTY")
    assert c["found"] and c["atm"] == 22_500.0 and c["forward_source"] == "put-call parity"
    assert c["atm_iv"] == pytest.approx(12.0, abs=0.3)
    assert c["resistance"][0] == 23_000.0 and c["support"][0] == 22_000.0
    assert c["pcr_oi"] == pytest.approx(1.0)
    assert oc.chain(_bhav(), "BANKNIFTY") == {"symbol": "BANKNIFTY", "found": False}


def test_update_history_is_incremental(tmp_path):
    import zipfile
    root, cache = tmp_path / "fo", tmp_path / "derived" / "h.json"
    for day in ("20261008", "20261009"):
        df = _bhav().assign(TradDt=pd.Timestamp(day))
        d = root / "2026"
        d.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(d / f"BhavCopy_NSE_FO_0_0_0_{day}_F_0000.csv.zip", "w") as z:
            z.writestr(f"BhavCopy_NSE_FO_0_0_0_{day}_F_0000.csv", df.assign(XpryDt=df["XpryDt"].dt.strftime("%Y-%m-%d"),
                       TradDt=df["TradDt"].dt.strftime("%Y-%m-%d")).to_csv(index=False))
    oc.load.cache_clear()
    h = oc.update_history(root, cache, ("NIFTY",))
    assert [r["date"] for r in h["NIFTY"]] == ["2026-10-08", "2026-10-09"]
    assert h["NIFTY"][-1]["atm_iv"] == pytest.approx(12.0, abs=0.5)
    mtime = cache.stat().st_mtime_ns
    oc.update_history(root, cache, ("NIFTY",))              # nothing new → file untouched
    assert cache.stat().st_mtime_ns == mtime


def test_live_frame_feeds_the_same_chain_engine():
    s, t_days = 22_400.0, 1
    def leg(k, call):
        px = oc.bs_price(s, k, t_days / 365, 0.14, call)
        return {"strikePrice": k, "expiryDate": "13-10-2026", "lastPrice": round(px, 2), "openInterest": 1000 + k % 7,
                "changeinOpenInterest": 10, "totalTradedVolume": 500, "underlyingValue": s}
    data = [{"strikePrice": k, "expiryDates": "13-Oct-2026", "CE": leg(k, True), "PE": leg(k, False)}
            for k in range(21_900, 22_950, 50)]
    df = oc.live_frame({"records": {"data": data, "underlyingValue": s}}, "NIFTY", lot=65,
                       today=__import__("datetime").date(2026, 10, 12))
    assert set(df["FinInstrmTp"]) == {"IDO"} and df["OpnIntrst"].iloc[0] % 65 == 0       # contracts × lot
    out = oc.chain(df, "NIFTY")
    assert out["found"] and out["atm"] == 22_400.0 and out["lot"] == 65
    assert out["atm_iv"] == pytest.approx(14.0, abs=1.0)
    assert out["expiry"] == "2026-10-13"
