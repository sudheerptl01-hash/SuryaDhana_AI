"""The cached NSE F&O bhavcopies on disk and the UDiFF loader (R-IV §2 rows 4–5).

Both formats are normalised to one contracts frame::

    symbol, kind (index|stock), instrument (FUT|OPT), expiry (date), strike, opt_type (CE|PE|None), close, settle,
    volume (contracts), oi, oi_chg, lot, underlying (UDiFF only; NaN for legacy), source_file

``close`` is NSE's official close (the last-30-minute average); ``volume`` in contracts decides "traded" (R-IV §4.5 trap 1:
an untraded strike's settle is a theoretical value → no IV).
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

UDIFF_RE = re.compile(r"BhavCopy_NSE_FO_0_0_0_(\d{8})_F_0000\.csv\.zip$")
LEGACY_RE = re.compile(r"fo(\d{2})([A-Z]{3})(\d{4})bhav\.csv\.zip$")
MONTHS = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
UDIFF_START = date(2024, 7, 8)
CONTRACT_COLUMNS = ["symbol", "kind", "instrument", "expiry", "strike", "opt_type", "close", "settle", "volume", "oi", "oi_chg", "lot",
                    "underlying", "source_file"]


def day_of(path: Path) -> date | None:
    m = UDIFF_RE.search(path.name)
    if m:
        s = m.group(1)
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    m = LEGACY_RE.search(path.name)
    if m:
        return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    return None


def is_legacy(path: Path) -> bool:
    return LEGACY_RE.search(path.name) is not None


def files(root: Path, start: date | None = None, end: date | None = None, *, prefer_udiff: bool = True) -> list[tuple[date, Path]]:
    """Every cached F&O file under ``root/<year>/`` in [start, end], one per day (UDiFF preferred where both exist)."""
    by_day: dict[date, Path] = {}
    for p in sorted(root.glob("*/*.csv.zip")):
        d = day_of(p)
        if d is None or (start and d < start) or (end and d > end):
            continue
        if d in by_day and prefer_udiff and is_legacy(p):
            continue
        by_day[d] = p
    return sorted(by_day.items())


def _unzip_first(blob: bytes) -> bytes:
    if blob[:2] != b"PK":
        return blob
    z = zipfile.ZipFile(io.BytesIO(blob))
    name = next((n for n in z.namelist() if n.lower().endswith(".csv")), z.namelist()[0])
    return z.read(name)


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip().replace({"-": None, "": None, "nan": None}), errors="coerce")


def parse_udiff(blob: bytes, source_file: str = "") -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(_unzip_first(blob)), dtype=str, low_memory=False)
    df.columns = [c.strip() for c in df.columns]
    if "FinInstrmTp" not in df.columns:
        raise ValueError("not a UDiFF F&O bhavcopy")
    tp = df["FinInstrmTp"].str.strip()
    keep = tp.isin(["STF", "STO", "IDF", "IDO"])
    df, tp = df[keep], tp[keep]
    out = pd.DataFrame({
        "symbol": df["TckrSymb"].str.strip(),
        "kind": tp.map({"STF": "stock", "STO": "stock", "IDF": "index", "IDO": "index"}),
        "instrument": tp.map({"STF": "FUT", "IDF": "FUT", "STO": "OPT", "IDO": "OPT"}),
        "expiry": pd.to_datetime(df["XpryDt"], errors="coerce").dt.date,
        "strike": _num(df["StrkPric"]),
        "opt_type": df["OptnTp"].str.strip().where(tp.isin(["STO", "IDO"])),
        "close": _num(df["ClsPric"]), "settle": _num(df["SttlmPric"]),
        "volume": _num(df["TtlTradgVol"]), "oi": _num(df["OpnIntrst"]), "oi_chg": _num(df["ChngInOpnIntrst"]),
        "lot": _num(df["NewBrdLotQty"]) if "NewBrdLotQty" in df.columns else None,
        "underlying": _num(df["UndrlygPric"]) if "UndrlygPric" in df.columns else None,
    })
    out["source_file"] = source_file
    out = out.dropna(subset=["symbol", "instrument", "expiry"]).reset_index(drop=True)
    return out[CONTRACT_COLUMNS]


def load(path: Path) -> pd.DataFrame:
    """Either format → the contracts frame (legacy through ``legacy_parser``)."""
    blob = path.read_bytes()
    if is_legacy(path):
        from fo_iv.legacy_parser import parse_legacy

        return parse_legacy(blob, source_file=path.name)
    return parse_udiff(blob, source_file=path.name)
