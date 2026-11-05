"""The legacy NSE F&O bhavcopy (``foDDMONYYYYbhav.csv.zip``, 2001 → 2024-07-05; cached 2019-10-01 →): 16 columns, no
underlying price, volume in contracts, dates ``DD-Mon-YYYY`` (R-IV §2 row 5, §4.5 trap 6). The put-call-parity forward
removes the need for a spot (verified on the 1 Apr 2022 file: NIFTY monthly ATM 17.13 %, 96 IV strikes).

Output: the same contracts frame as ``files.parse_udiff`` with ``underlying`` NaN and ``lot`` NaN (not in the file).
"""
from __future__ import annotations

import io

import pandas as pd

from fo_iv.files import CONTRACT_COLUMNS, _num, _unzip_first

LEGACY_COLUMNS = ("INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "OPEN", "HIGH", "LOW", "CLOSE", "SETTLE_PR", "CONTRACTS",
                  "VAL_INLAKH", "OPEN_INT", "CHG_IN_OI", "TIMESTAMP")


def parse_legacy(blob: bytes, source_file: str = "") -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(_unzip_first(blob)), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    missing = [c for c in LEGACY_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"not a legacy F&O bhavcopy (missing {missing[:3]})")
    ins = df["INSTRUMENT"].str.strip()
    keep = ins.isin(["FUTSTK", "OPTSTK", "FUTIDX", "OPTIDX"])
    df, ins = df[keep], ins[keep]
    opt = ins.isin(["OPTSTK", "OPTIDX"])
    out = pd.DataFrame({
        "symbol": df["SYMBOL"].str.strip(),
        "kind": ins.map({"FUTSTK": "stock", "OPTSTK": "stock", "FUTIDX": "index", "OPTIDX": "index"}),
        "instrument": ins.map({"FUTSTK": "FUT", "FUTIDX": "FUT", "OPTSTK": "OPT", "OPTIDX": "OPT"}),
        "expiry": pd.to_datetime(df["EXPIRY_DT"].str.strip(), format="%d-%b-%Y", errors="coerce").dt.date,
        "strike": _num(df["STRIKE_PR"]),
        "opt_type": df["OPTION_TYP"].str.strip().where(opt),
        "close": _num(df["CLOSE"]), "settle": _num(df["SETTLE_PR"]),
        "volume": _num(df["CONTRACTS"]), "oi": _num(df["OPEN_INT"]), "oi_chg": _num(df["CHG_IN_OI"]),
        "lot": None, "underlying": None,
    })
    out["source_file"] = source_file
    out = out.dropna(subset=["symbol", "instrument", "expiry"]).reset_index(drop=True)
    return out[CONTRACT_COLUMNS]
