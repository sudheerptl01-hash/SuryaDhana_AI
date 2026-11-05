"""
Instrument classification: operating companies vs ETFs / funds / placeholders.

Source of truth is NSE's own reference files, cached in ``data/reference/``:
  - nse_equity_list.csv  (EQUITY_L.csv    — every listed equity symbol)
  - nse_etf_list.csv     (eq_etfseclist.csv — every listed ETF symbol)

Name heuristics alone misclassify real companies (SHANTIGOLD, SKYGOLD, GOLDIAM and
DECNGOLD are jewellery / mining businesses, not gold ETFs), so a symbol is only
called an ETF when NSE lists it as one. Refresh the files with
``scripts/refresh_instrument_reference.py``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from shared.logging import get_logger

logger = get_logger(__name__)

EQUITY = "EQUITY"
ETF = "ETF"
INVALID = "INVALID"
UNKNOWN = "UNKNOWN"

# Symbols absent from both NSE lists (delisted / renamed). Only these narrow,
# unambiguous rules apply to them — everything else stays UNKNOWN.
_PLACEHOLDER = re.compile(r"^DUMMY", re.I)
_FUND_HOUSE_ETF = re.compile(r"^(AXIS|SBI|HDFC|ICICI|NIPPON|KOTAK|MIRAE|UTI)(GOLD|SILVER)$", re.I)


def _read_symbols(path: Path, column: str) -> set[str]:
    if not path.exists():
        return set()
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    return set(df[column].astype(str).str.strip().str.upper())


def classify_universe(tickers: list[str], reference_dir: Path) -> pd.DataFrame:
    """Return [ticker, instrument_type, ml_eligible, classified_by] for ``tickers``."""
    equities = _read_symbols(reference_dir / "nse_equity_list.csv", "SYMBOL")
    etfs = _read_symbols(reference_dir / "nse_etf_list.csv", "Symbol")
    if not equities or not etfs:
        raise FileNotFoundError(
            f"NSE reference lists missing in {reference_dir} — "
            "run scripts/refresh_instrument_reference.py"
        )

    rows = []
    for raw in tickers:
        t = str(raw).strip().upper()
        if t in etfs:
            itype, by = ETF, "nse_etf_list"
        elif t in equities:
            itype, by = EQUITY, "nse_equity_list"
        elif _PLACEHOLDER.match(t):
            itype, by = INVALID, "rule:placeholder"
        elif _FUND_HOUSE_ETF.match(t):
            itype, by = ETF, "rule:fund_house_commodity_etf"
        else:
            itype, by = UNKNOWN, "rule:not_in_nse_lists"
        rows.append({
            "ticker": t,
            "instrument_type": itype,
            "ml_eligible": itype == EQUITY,
            "classified_by": by,
        })
    df = pd.DataFrame(rows).drop_duplicates("ticker")
    logger.info(
        "Universe classified",
        total=len(df),
        **{k.lower(): int(v) for k, v in df["instrument_type"].value_counts().items()},
    )
    return df
