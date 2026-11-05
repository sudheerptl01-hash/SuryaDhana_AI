"""
NSE surveillance and risk flags per stock, from three free daily NSE files:

  content/cm/REG1_INDddmmyy.csv          surveillance indicators: GSM / ASM (long and short term) / ESM stages,
                                         insolvency (IRP), pledge, loss-making, trade-to-trade (BZ/SZ) and more
                                         (100 = not applicable; any other value = flagged, the stage where staged)
  content/equities/sec_list_ddmmyyyy.csv price band (circuit limit) per symbol: 2 / 5 / 10 / 20 % or No Band
  archives/fo/sec_ban/fo_secban_ddmmyyyy.csv  F&O securities in the ban period (named for the trade date)

Why it matters for a swing trader: ASM / GSM / ESM mean higher margins (up to 100%), trade-to-trade settlement or
a tighter band; a 2–5% band can trap a position in a circuit; a stock in the F&O ban can't take new positions.
Context, not a signal. Nothing here changes a Desk rule.
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

import httpx
import pandas as pd

ARCHIVE = "https://nsearchives.nseindia.com"
# staged measures: column prefix → label shown in the terminal
STAGED = {"GSM": "GSM", "Long_Term_Additional_Surveillance_Measure": "ASM LT", "Short_Term_Additional_Surveillance_Measure": "ASM ST",
          "ESM": "ESM", "Insolvency_Resolution_Process": "IRP"}
# yes / no flags worth showing (the rest of the file is mostly price-variation triggers behind the measures above)
FLAGS = {"Under BZ/SZ Series": "trade-to-trade", "Pledge": "pledge", "Total Pledge": "high pledge", "Loss making": "loss-making",
         "The Overall encumbered share in the scrip is more than 50 Percent.": "encumbered > 50%",
         "Company has failed to pay Annual listing fee": "listing fee unpaid",
         "Derivative contracts in the scrip to be moved out of F and O": "leaving F&O", "Default": "default"}


def urls(day: date) -> dict[str, str]:
    return {"reg1": f"{ARCHIVE}/content/cm/REG1_IND{day:%d%m%y}.csv",
            "bands": f"{ARCHIVE}/content/equities/sec_list_{day:%d%m%Y}.csv",
            "ban": f"{ARCHIVE}/archives/fo/sec_ban/fo_secban_{day:%d%m%Y}.csv"}


def parse_reg1(content: bytes) -> dict[str, dict[str, Any]]:
    """REG1_IND → {symbol: {"series", "measures": {"ASM LT": 1, …}, "flags": ["pledge", …]}} for flagged symbols."""
    df = pd.read_csv(io.BytesIO(content))
    df.columns = [str(c).strip() for c in df.columns]
    out: dict[str, dict[str, Any]] = {}
    for r in df.itertuples(index=False):
        row = dict(zip(df.columns, r))
        measures: dict[str, int] = {}
        for col, val in row.items():
            for prefix, label in STAGED.items():
                if str(col).startswith(prefix) and pd.notna(val) and str(val).strip() not in ("100", ""):
                    measures[label] = int(float(val))
        flags = [label for col, label in FLAGS.items() if col in row and pd.notna(row[col]) and str(row[col]).strip() not in ("100", "")]
        if measures or flags:
            out[str(row.get("Symbol")).strip()] = {"series": str(row.get("Series") or "").strip(), "measures": measures, "flags": flags}
    return out


def parse_bands(content: bytes) -> dict[str, dict[str, Any]]:
    """sec_list → {symbol: {"band": 2|5|10|20|None, "series", "remarks"}} (equity series; None = no band)."""
    df = pd.read_csv(io.BytesIO(content))
    df.columns = [str(c).strip() for c in df.columns]
    out: dict[str, dict[str, Any]] = {}
    for r in df.itertuples(index=False):
        sym, series, band, remarks = str(r.Symbol).strip(), str(r.Series).strip(), str(r.Band).strip(), str(r.Remarks).strip()
        try:
            b: Optional[float] = float(band)
        except ValueError:
            b = None                                  # "No Band"
        if sym not in out or series == "EQ":          # prefer the EQ row when a stock has several series
            out[sym] = {"band": b, "series": series, "remarks": None if remarks in ("-", "nan", "") else remarks}
    return out


def parse_ban(content: bytes) -> list[str]:
    """fo_secban → symbols in the F&O ban (first line is a title; rows are "n,SYMBOL")."""
    out = []
    for line in content.decode("utf-8", "ignore").splitlines()[1:]:
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1]:
            out.append(parts[1])
    return out


def _latest(client: httpx.Client, kind: str, cache: Path, today: date, ahead: int = 0) -> tuple[Optional[bytes], Optional[date]]:
    """Newest published file of `kind`, looking back a week (the ban file is named for the *next* trade date, so it
    is tried `ahead` days forward first). Downloads are kept in `cache`."""
    for k in range(-ahead, 8):
        day = today - timedelta(days=k)
        path = cache / kind / f"{day.isoformat()}.csv"
        if path.exists():
            return path.read_bytes(), day
        try:
            r = client.get(urls(day)[kind])
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and len(r.content) > 20 and not r.content.lstrip().startswith(b"<"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
            return r.content, day
    return None, None


def load(cache: Path, headers: dict[str, str], today: Optional[date] = None) -> dict[str, Any]:
    """All three files, newest available, parsed."""
    today = today or date.today()
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        reg1, d1 = _latest(client, "reg1", cache, today)
        bands, d2 = _latest(client, "bands", cache, today)
        ban, d3 = _latest(client, "ban", cache, today, ahead=4)
    return {"surveillance": parse_reg1(reg1) if reg1 else {}, "bands": parse_bands(bands) if bands else {},
            "ban": parse_ban(ban) if ban else [],
            "dates": {"surveillance": d1.isoformat() if d1 else None, "bands": d2.isoformat() if d2 else None,
                      "ban": d3.isoformat() if d3 else None}}


def flags_for(symbol: str, data: dict[str, Any]) -> dict[str, Any]:
    """One stock's risk flags in display order: F&O ban, staged measures, a tight band, trade-to-trade, the rest."""
    s = (data.get("surveillance") or {}).get(symbol) or {}
    b = (data.get("bands") or {}).get(symbol) or {}
    chips: list[dict[str, Any]] = []
    if symbol in (data.get("ban") or []):
        chips.append({"code": "F&O BAN", "level": "high", "why": "in the F&O ban period: no new derivative positions"})
    for label, stage in (s.get("measures") or {}).items():
        lvl = "high" if label in ("GSM", "ESM", "IRP") or stage >= 2 else "medium"
        chips.append({"code": f"{label} {stage}", "level": lvl,
                      "why": f"NSE {label} stage {stage}: higher margins, closer surveillance"
                             + (" (insolvency resolution)" if label == "IRP" else "")})
    if b.get("band") is not None and b["band"] <= 5:
        chips.append({"code": f"BAND {b['band']:g}%", "level": "high" if b["band"] <= 2 else "medium",
                      "why": f"daily price band ±{b['band']:g}%: a position can be trapped in a circuit"})
    if b.get("series") in ("BE", "BZ", "SZ") or "trade-to-trade" in (s.get("flags") or []):
        chips.append({"code": "T2T", "level": "high", "why": "trade-to-trade settlement: no intraday netting, thin liquidity"})
    for f in s.get("flags") or []:
        if f != "trade-to-trade":
            chips.append({"code": f.upper(), "level": "low", "why": f"NSE surveillance file: {f}"})
    return {"symbol": symbol, "band": b.get("band"), "series": b.get("series") or s.get("series"), "chips": chips}
