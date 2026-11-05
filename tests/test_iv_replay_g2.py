"""G2 (Terminal v2 PLAN 1.7): ``iv_eod`` on the 23 cached Oct-2026 F&O files reproduces ``reports/terminal_v2/R-IV/iv_compare_NIFTY.csv``
within 0.05 vol-pt (near ATM, iv30_cm, monthly ATM) and correlates ≥ 0.99 with the product's ``option_history.json`` near-expiry
ATM IV. Skips (never fails) where the git-ignored archive is absent (CI); runs on the owner's machine."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

FO = ROOT / "data" / "nse_archive" / "fo"
CSV = ROOT / "reports" / "terminal_v2" / "R-IV" / "iv_compare_NIFTY.csv"
HIST = ROOT / "data" / "nse_archive" / "derived" / "option_history.json"
START, END = date(2026, 10, 1), date(2026, 11, 4)


def _files():
    from fo_iv import files as fo_files

    return fo_files.files(FO, START, END) if FO.exists() else []


@pytest.mark.skipif(not CSV.exists() or len(_files()) < 20, reason="needs the cached Oct-2026 F&O files and R-IV's CSV")
def test_replay_matches_the_prototype_within_0_05_vol_pt():
    from fo_iv import files as fo_files
    from fo_iv import iv_eod

    ref = pd.read_csv(CSV)
    ref = ref[(ref["date"] >= START.isoformat()) & (ref["date"] <= END.isoformat())].set_index("date")
    rows = []
    for day, path in _files():
        res = iv_eod.compute_day(fo_files.load(path), day, 0.065, symbols={"NIFTY"}, surface_symbols={"NIFTY"}, source_file=path.name)
        s = res.summary.iloc[0]
        rows.append({"date": day.isoformat(), "near": s["near_atm_iv"], "iv30": s["iv30_cm"], "monthly": s["monthly_atm_iv"]})
    m = pd.DataFrame(rows).set_index("date").join(ref[["near_atm_iv", "iv30_cm", "monthly_atm_iv", "product_atm_iv"]])
    assert len(m) >= 20
    for ours, theirs in (("near", "near_atm_iv"), ("iv30", "iv30_cm"), ("monthly", "monthly_atm_iv")):
        d = (m[ours] - m[theirs]).abs()
        assert d.max() < 0.05, (ours, d.max())
    assert m["near"].corr(m["product_atm_iv"]) >= 0.99


@pytest.mark.skipif(not HIST.exists() or len(_files()) < 20, reason="needs the cached files and the product's option_history.json")
def test_replay_correlates_with_the_product_history():
    from fo_iv import files as fo_files
    from fo_iv import iv_eod

    hist = {r["date"]: r["atm_iv"] for r in json.loads(HIST.read_text()).get("NIFTY", [])}
    pairs = []
    for day, path in _files():
        s = iv_eod.compute_day(fo_files.load(path), day, 0.065, symbols={"NIFTY"}, surface_symbols=set()).summary.iloc[0]
        if day.isoformat() in hist and s["near_atm_iv"] is not None:
            pairs.append((s["near_atm_iv"], hist[day.isoformat()]))
    df = pd.DataFrame(pairs, columns=["ours", "product"])
    assert len(df) >= 20 and df["ours"].corr(df["product"]) >= 0.99
