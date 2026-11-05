"""The two free files the drivers need (R-DRIVERS §4, verified 4 Nov 2026): NSE's daily NIFTY 50 top-10 weights
(``top10nifty50_DDMMYY.csv``: SYMBOL, SECURITY, WEIGHTAGE(%)) and the niftyindices.com constituent lists (``ind_nifty50list.csv``,
``ind_niftybanklist.csv``: Company Name, Industry, Symbol, Series, ISIN Code). Both display-only with attribution (O-T11),
both through ``data_health.ingest_log.fetch_logged`` (cache, If-Modified-Since, sha256). The constituent lists are archived
every day so a point-in-time membership history grows from the day the job starts.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from data_health import db, ingest_log

from index_drivers.schema import CASTS, COLUMNS

ARCHIVE = "https://nsearchives.nseindia.com"
NIFTYINDICES = "https://niftyindices.com"
TOP10_URL = f"{ARCHIVE}/content/indices/top10nifty50_{{d:%d%m%y}}.csv"
CONSTITUENT_URLS: dict[str, str] = {
    "NIFTY 50": f"{NIFTYINDICES}/IndexConstituent/ind_nifty50list.csv",
    "NIFTY BANK": f"{NIFTYINDICES}/IndexConstituent/ind_niftybanklist.csv",
    "NIFTY NEXT 50": f"{NIFTYINDICES}/IndexConstituent/ind_niftynext50list.csv",       # O-T12
    "NIFTY IT": f"{NIFTYINDICES}/IndexConstituent/ind_niftyitlist.csv",                # O-T12
}
INDICES: tuple[str, ...] = ("NIFTY 50", "NIFTY BANK")       # first release (O-T12 default); NEXT 50 / IT on the owner's word
TOP10_INDEX = "NIFTY 50"


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip(), errors="coerce")


def parse_top10(blob: bytes, day: date) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(blob), dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]
    sym = next((c for c in df.columns if c.startswith("SYMBOL")), None)
    w = next((c for c in df.columns if c.startswith("WEIGHT")), None)
    if sym is None or w is None:
        raise ValueError(f"top10 layout changed: {list(df.columns)}")
    out = pd.DataFrame({"symbol": df[sym].astype(str).str.strip(), "weight_pct": _num(df[w])}).dropna()
    if len(out) != 10 or not (40 <= out["weight_pct"].sum() <= 80):
        raise ValueError(f"top10 sanity: {len(out)} rows, sum {out['weight_pct'].sum():.2f}")
    out["date"] = day
    return out.reset_index(drop=True)


def parse_constituents(blob: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(blob), dtype=str)
    df.columns = [c.strip() for c in df.columns]
    need = {"Company Name", "Industry", "Symbol", "Series"}
    if not need <= set(df.columns):
        raise ValueError(f"constituent list layout changed: {list(df.columns)}")
    eq = df[df["Series"].astype(str).str.strip() == "EQ"]
    isin = next((c for c in df.columns if c.upper().startswith("ISIN")), None)
    out = pd.DataFrame({"symbol": eq["Symbol"].astype(str).str.strip(), "industry": eq["Industry"].astype(str).str.strip(),
                        "isin": eq[isin].astype(str).str.strip() if isin else None, "company": eq["Company Name"].astype(str).str.strip()})
    if out.empty:
        raise ValueError("constituent list has no EQ rows")
    return out.reset_index(drop=True)


def write_top10(store: Any, parsed: pd.DataFrame, day: date, *, now: datetime) -> int:
    rows = parsed.assign(index_name=TOP10_INDEX, method="official_top10", ffmc_cr=None, shares=None, shares_filed_at=None, promoter_pct=None,
                         promoter_public_at=None, iwf_correction=None, computed_at=now)
    return db.upsert(store, "index_weights_daily", rows, COLUMNS["index_weights_daily"], CASTS["index_weights_daily"])


def write_constituents(store: Any, index_name: str, parsed: pd.DataFrame, day: date, *, source: str, now: datetime) -> int:
    rows = parsed.assign(index_name=index_name, date=day, source=source, first_seen_at=now)
    return db.upsert(store, "index_constituents_daily", rows, COLUMNS["index_constituents_daily"], CASTS["index_constituents_daily"])


def ingest_top10(store: Any, http: Any, day: date, cache_root: Path, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or db.utcnow()
    url = TOP10_URL.format(d=day)
    f = ingest_log.fetch_logged(store, http, "nse_top10_weights", day, url, cache_root=cache_root / "nse_archive", now=now)
    out: dict[str, Any] = {"status": f.status, "rows": 0}
    if f.ok and f.body:
        try:
            out["rows"] = write_top10(store, parse_top10(f.body, day), day, now=now)
        except Exception as exc:  # noqa: BLE001
            out["status"], out["error"] = "parse_error", f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def ingest_constituents(store: Any, http: Any, index_name: str, day: date, cache_root: Path, *, now: datetime | None = None,
                        revalidate: bool = True) -> dict[str, Any]:
    """Conditional GET of the list (changes on reconstitution); the day's membership row is written from the cached body on a 304."""
    now = now or db.utcnow()
    url = CONSTITUENT_URLS[index_name]
    key = index_name.lower().replace(" ", "_")
    f = ingest_log.fetch_logged(store, http, f"index_constituents:{key}", day, url, cache_root=cache_root / "nse_archive",
                                cache_name=url.rsplit("/", 1)[-1], revalidate=revalidate, now=now)
    out: dict[str, Any] = {"status": f.status, "rows": 0}
    if f.body:
        try:
            out["rows"] = write_constituents(store, index_name, parse_constituents(f.body), day, source="niftyindices_csv", now=now)
        except Exception as exc:  # noqa: BLE001
            out["status"], out["error"] = "parse_error", f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


def official_top10(store: Any, day: date) -> dict[str, float]:
    df = db.query_df(store, "SELECT symbol, weight_pct FROM index_weights_daily WHERE index_name = ? AND date = ? AND method = 'official_top10'",
                     [TOP10_INDEX, day])
    return {str(r.symbol): float(r.weight_pct) for r in df.itertuples(index=False)}
