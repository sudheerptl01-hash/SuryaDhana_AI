import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))

import market_internals as mi  # noqa: E402

PAYLOAD = {"timestamp": "13-Oct-2026 11:33", "advances": 4102, "declines": 5380, "data": [
    {"index": "NIFTY 50", "last": 22503.05, "percentChange": 0.62, "advances": "34", "declines": "14"},
    {"index": "NIFTY 500", "last": 21872.8, "percentChange": 0.23, "advances": "207", "declines": "289"},
    {"index": "NIFTY SMALLCAP 250", "last": 17648.15, "percentChange": -0.7}]}


def test_snapshot_reads_breadth_and_segments():
    s = mi.snapshot(PAYLOAD)
    assert s["nifty"] == 22503.05 and s["n50_pct"] == 0.62 and s["small_pct"] == -0.7 and s["mid_pct"] is None
    assert (s["n500_adv"], s["n500_dec"], s["all_adv"], s["all_dec"]) == (207, 289, 4102, 5380)
    assert mi.snapshot({"data": []}) is None


def test_append_skips_unchanged_nse_timestamp(tmp_path):
    s = mi.snapshot(PAYLOAD)
    assert mi.append(tmp_path, s) is True
    assert mi.append(tmp_path, s) is False                      # NSE has not updated since the last sample
    assert mi.append(tmp_path, {**s, "nse_ts": "13-Oct-2026 11:35"}) is True
    assert len(mi.read(tmp_path, "2026-10-13")) == 2


def test_summary_flags_a_narrow_rally():
    early = {**mi.snapshot(PAYLOAD), "n500_adv": 300, "n500_dec": 190}
    rows = [early, mi.snapshot(PAYLOAD)]
    out = mi.summary(rows)
    assert out["divergence"] == "narrow: NIFTY up, most stocks down"
    assert out["net_now"] == -82 and out["net_best"] == 110 and out["ad_ratio"] == 0.72
    assert out["small_minus_n50"] == -1.32
    assert mi.summary([]) == {}
