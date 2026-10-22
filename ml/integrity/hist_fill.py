#!/usr/bin/env python3
"""Sessions missing from the history stream's final parquet, rebuilt from its own raw files.

The history stream (P4) builds equity_eod rows from the CM bhavcopy + MTO delivery file of
each day.  A day whose PR-bundle bc member has an over-long CSV row fails its parser as a
whole, so those sessions are absent from ml/data_hist/equity_eod_2016_2021.parquet although
their CM and MTO files are on disk (ml/data_raw/hist/cm, ml/data_raw/hist/mto).

This module rebuilds such sessions with P4's conventions (turnover and VWAP rounded half up,
delivery from the MTO file, the store's EQ/BE/BZ/SM/ST series) and proves the construction
on neighbouring days first: it must reproduce P4's own rows there exactly, every column.
Output: ml/data_ext/staging/hist_missing_sessions.parquet (+ hist_fill.json).

Run: OMP_NUM_THREADS=2 python3 -I ml/integrity/hist_fill.py
"""
from __future__ import annotations

import io
import json
import sys
import time
import zipfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import nse_historical_ingest as nhi  # noqa: E402
from ml.integrity.common import ML_DIR, OUT, log, wjson  # noqa: E402
from ml.integrity.sessions import STAGING, compare_frames, parse_mto  # noqa: E402

HIST = ML_DIR / "data_hist" / "equity_eod_2016_2021.parquet"
RAW_H = ML_DIR / "data_raw" / "hist"
SERIES = ["EQ", "BE", "BZ", "SM", "ST"]
COLS = ["prev_close", "open", "high", "low", "last", "close", "vwap", "volume", "turnover", "trades",
        "deliv_qty", "deliv_pct"]


def _half_up(x: pd.Series, k: int) -> pd.Series:
    """The history stream's rounding (ml/history/parse.py): floor(x * 10^k + 0.5 + 1e-7) / 10^k."""
    f = 10.0 ** k
    return np.floor(x * f + 0.5 + 1e-7) / f


def rows_p4_convention(d: date) -> pd.DataFrame:
    mon = d.strftime("%b").upper()
    cm_raw = (RAW_H / "cm" / f"cm{d:%d}{mon}{d.year}bhav.csv.zip").read_bytes()
    mto_raw = (RAW_H / "mto" / f"MTO_{d:%d%m%Y}.DAT").read_bytes()
    with zipfile.ZipFile(io.BytesIO(cm_raw)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        cm = pd.read_csv(zf.open(name))
    cm.columns = [c.strip().upper() for c in cm.columns]
    cm["SERIES"] = cm["SERIES"].astype(str).str.strip()
    cm = cm[cm["SERIES"].isin(SERIES)].copy()
    vol = nhi._to_num(cm["TOTTRDQTY"])
    val = nhi._to_num(cm["TOTTRDVAL"])
    out = pd.DataFrame({
        "date": pd.Timestamp(d).normalize(), "ticker": cm["SYMBOL"].astype(str).str.strip(), "series": cm["SERIES"],
        "isin": cm["ISIN"].astype(str).str.strip() if "ISIN" in cm.columns else pd.NA,
        "prev_close": nhi._to_num(cm["PREVCLOSE"]), "open": nhi._to_num(cm["OPEN"]), "high": nhi._to_num(cm["HIGH"]),
        "low": nhi._to_num(cm["LOW"]), "last": nhi._to_num(cm["LAST"]), "close": nhi._to_num(cm["CLOSE"]),
        "vwap": _half_up(val / vol.where(vol > 0), 2),
        "volume": vol, "turnover": _half_up(val * 1.0 / 1e5, 2) * 1e5,
        "trades": nhi._to_num(cm["TOTALTRADES"]), "source": "cm_mto"})
    mto = parse_mto(mto_raw)
    out = out.merge(mto[["ticker", "series", "deliv_qty", "deliv_pct"]], on=["ticker", "series"], how="left")
    out = out[out["volume"] > 0]
    return nhi._finalize(out)


def main(argv=None) -> int:
    t0 = time.time()
    e = pd.read_parquet(HIST)
    e["date"] = pd.to_datetime(e["date"])
    stored = set(e["date"].dt.date)
    sess = pd.read_csv(ML_DIR / "data_hist" / "sessions_2016_2021.csv", dtype=str)
    cal = set(nhi.trading_days(date(2016, 10, 1), date(2021, 9, 30)))
    missing = sorted(d for d in cal if d not in stored)
    res = {"history_parquet_sessions": len(stored), "calendar_sessions": len(cal),
           "missing_sessions": [str(d) for d in missing], "checks": {}, "built": {}}
    # prove the construction on the neighbours of every missing day
    neigh = sorted({x for d in missing for x in stored if 0 < abs((x - d).days) <= 4})
    ok_all = True
    for d in neigh:
        mine = rows_p4_convention(d)
        p4 = e[(e["date"] == pd.Timestamp(d)) & e["series"].isin(SERIES)]
        c = compare_frames(mine, p4, COLS)
        same = c["only_a"] == 0 and c["only_b"] == 0 and all(
            v["max_abs_diff"] == 0 and v["nan_mismatch"] == 0 for v in c.values() if isinstance(v, dict))
        res["checks"][str(d)] = {"identical_to_p4_rows": bool(same), "rows": c["rows_a"],
                                 "worst": {k: v for k, v in c.items() if isinstance(v, dict) and
                                           (v["max_abs_diff"] or v["nan_mismatch"])}}
        ok_all &= same
    res["construction_identical_on_all_neighbours"] = bool(ok_all)
    frames = []
    if ok_all:
        for d in missing:
            if not (RAW_H / "cm" / f"cm{d:%d}{d.strftime('%b').upper()}{d.year}bhav.csv.zip").exists():
                res["built"][str(d)] = "no CM file on disk"
                continue
            x = rows_p4_convention(d)
            frames.append(x)
            res["built"][str(d)] = {"rows": int(len(x)), "by_series": {k: int(v) for k, v in
                                                                     x["series"].value_counts().items()}}
    if frames:
        out = pd.concat(frames, ignore_index=True)
        out["date"] = pd.to_datetime(out["date"]).astype("datetime64[ns]")
        STAGING.mkdir(parents=True, exist_ok=True)
        out.to_parquet(STAGING / "hist_missing_sessions.parquet", index=False)
        res["rows_total"] = int(len(out))
    res["seconds"] = round(time.time() - t0, 1)
    wjson(OUT / "hist_fill.json", res)
    log(f"hist fill: missing {res['missing_sessions']}, construction identical {ok_all}, built {res['built']}", "hist")
    print(json.dumps({k: v for k, v in res.items() if k != "checks"}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
