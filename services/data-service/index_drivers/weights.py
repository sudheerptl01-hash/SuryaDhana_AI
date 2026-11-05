"""Point-in-time weights (R-DRIVERS §3): ``ffmc = shares × prev_close × (1 − promoter %)`` with ``shares`` from the newest
XBRL filing with ``filed_at ≤ d`` (split-scaled from its period end to d) and ``promoter %`` from the newest shareholding
filing with ``broadcast_ts ≤ d`` (fallback: period_end + 21 days); normalised to 100 %. Calibration on a day with NSE's top-10
file: ``iwf_correction_i = official_i / rebuilt_i`` for the ten, the rest pro rata to the remaining share. NSE's sector capping
(single ≤ 33 %, top-3 ≤ 62 %) applied iteratively for NIFTY BANK (approximate until O-T13's official cap factors).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_health import db
from index_drivers.schema import CASTS, COLUMNS

BANK_CAPS = (0.33, 0.62)
CAPPED_INDICES = {"NIFTY BANK": BANK_CAPS}


def members_for(store: Any, index_name: str, day: date) -> tuple[pd.DataFrame, date | None, str]:
    """Members as of ``day``: the newest archived list dated ≤ day, else the OLDEST archived list (the page says "members as
    of <date> applied before"); (frame, list_date, note)."""
    before = db.query_df(store, """SELECT symbol, industry FROM index_constituents_daily WHERE index_name = ? AND date = (
                                     SELECT MAX(date) FROM index_constituents_daily WHERE index_name = ? AND date <= ?)""", [index_name, index_name, day])
    if not before.empty:
        d = db.to_date(db.scalar(store, "SELECT MAX(date) FROM index_constituents_daily WHERE index_name = ? AND date <= ?", [index_name, day]))
        return before, d, "archived list"
    after = db.query_df(store, """SELECT symbol, industry FROM index_constituents_daily WHERE index_name = ? AND date = (
                                    SELECT MIN(date) FROM index_constituents_daily WHERE index_name = ?)""", [index_name, index_name])
    d = db.to_date(db.scalar(store, "SELECT MIN(date) FROM index_constituents_daily WHERE index_name = ?", [index_name]))
    return after, d, f"members as of {d} applied before that date" if d else "no constituent list stored"


def load_splits(store: Any) -> pd.DataFrame:
    if not db.table_exists(store, "splits"):
        return pd.DataFrame(columns=["ticker", "date", "ratio"])
    sp = db.query_df(store, "SELECT ticker, date, ratio FROM splits WHERE ratio > 0")
    sp["date"] = pd.to_datetime(sp["date"]).dt.tz_localize(None).dt.normalize()
    return sp


def load_shareholding(store: Any, symbols: list[str]) -> pd.DataFrame:
    if not db.table_exists(store, "nse_shareholding") or not symbols:
        return pd.DataFrame(columns=["symbol", "period_end", "public_at", "promoter_pct"])
    sh = db.query_df(store, """SELECT symbol, period_end, broadcast_ts, promoter_pct FROM nse_shareholding
                               WHERE list_contains(?, symbol) AND promoter_pct IS NOT NULL""", [symbols])
    if sh.empty:
        return pd.DataFrame(columns=["symbol", "period_end", "public_at", "promoter_pct"])
    sh["period_end"] = pd.to_datetime(sh["period_end"])
    sh["public_at"] = broadcast_dates(sh["broadcast_ts"]).fillna(sh["period_end"] + pd.Timedelta(days=21)).dt.normalize()
    return sh[["symbol", "period_end", "public_at", "promoter_pct"]].sort_values("public_at").reset_index(drop=True)


def broadcast_dates(s: pd.Series) -> pd.Series:
    """NSE's ``broadcast_ts`` ('06-OCT-2026 17:00:45') → Timestamp; the exact format first, then a tolerant parse of the rest
    (pandas infers ONE format per series and silently returns NaT for anything else — the fallback would then push a filing
    three weeks late)."""
    text = s.astype(str).str.strip()
    out = pd.to_datetime(text, format="%d-%b-%Y %H:%M:%S", errors="coerce")
    rest = out.isna() & text.ne("") & text.str.lower().ne("none")
    if rest.any():
        out[rest] = pd.to_datetime(text[rest], errors="coerce", dayfirst=True)
    return out


def promoter_pit(sh: pd.DataFrame, symbol: str, day: date) -> tuple[float, date | None]:
    """(promoter %, the filing's public date) known at ``day``; 0 % when no filing is public yet (flagged by the caller)."""
    if sh.empty:
        return 0.0, None
    p = sh[(sh["symbol"] == symbol) & (sh["public_at"] <= pd.Timestamp(day))]
    if p.empty:
        return 0.0, None
    row = p.iloc[-1]
    return float(row["promoter_pct"]), row["public_at"].date()


def shares_pit(financials_root: Path, symbol: str, day: date, splits: pd.DataFrame) -> tuple[float | None, datetime | None]:
    """(shares outstanding, filed_at) from the newest cached XBRL filing with ``filed_at ≤ day``, split-scaled to ``day``."""
    import financials as fin

    c = fin.load(financials_root, symbol)
    if not c or not c.get("quarters"):
        return None, None
    cutoff = day.strftime("%Y-%m-%dT%H:%M:%S")
    q = [x for x in c["quarters"] if (x.get("filed_at") or "9999") <= cutoff]
    if not q:
        return None, None
    q = sorted(q, key=lambda x: x.get("period_end") or "", reverse=True)
    sh = fin.shares_estimate(fin.with_growth(q))
    if not sh:
        return None, None
    pe = pd.Timestamp(q[0]["period_end"])
    k = 1.0
    if len(splits):
        k = float(splits[(splits["ticker"] == symbol) & (splits["date"] > pe) & (splits["date"] <= pd.Timestamp(day))]["ratio"].prod())
    filed = q[0].get("filed_at")
    try:
        filed_at = datetime.fromisoformat(filed) if filed else None
    except ValueError:
        filed_at = None
    return float(sh) * k, filed_at


def apply_caps(w: dict[str, float], single: float, top3: float, rounds: int = 6) -> dict[str, float]:
    """NSE sector-index capping (single ≤ single, top three ≤ top3) applied iteratively on normalised weights."""
    w = dict(w)
    for _ in range(rounds):
        over = {s: single for s, v in w.items() if v > single}
        if over:
            rest = 1.0 - sum(over.values())
            free = sum(v for s, v in w.items() if s not in over)
            w = {s: (over[s] if s in over else v / free * rest) for s, v in w.items()}
        t3 = sorted(w, key=lambda s: w[s], reverse=True)[:3]
        if len(w) > 3 and sum(w[s] for s in t3) > top3:
            k = top3 / sum(w[s] for s in t3)
            rest = 1.0 - top3
            free = sum(v for s, v in w.items() if s not in t3)
            w = {s: (v * k if s in t3 else v / free * rest) for s, v in w.items()}
    return w


class SharesCache:
    """shares_pit per (symbol, year-month): a filing changes at most a few times a year, a backfill asks 50 × 1,700 times."""

    def __init__(self, financials_root: Path, splits: pd.DataFrame) -> None:
        self.root, self.splits = financials_root, splits
        self.cache: dict[tuple[str, str], tuple[float | None, datetime | None]] = {}
        self.split_months: set[tuple[str, str]] = {(str(t), pd.Timestamp(d).strftime("%Y-%m")) for t, d in zip(splits["ticker"], splits["date"], strict=True)} \
            if len(splits) else set()

    def get(self, symbol: str, day: date) -> tuple[float | None, datetime | None]:
        ym = day.strftime("%Y-%m")
        # a month with a split (or a filing landing mid-month) must not reuse the 1st's answer: key by day in a split month,
        # and re-check on the day a newer filing may have appeared (cheap: the JSON is small and cached by the OS)
        key = (symbol, day.isoformat() if (symbol, ym) in self.split_months else ym)
        if key not in self.cache:
            self.cache[key] = shares_pit(self.root, symbol, day, self.splits)
        return self.cache[key]


def rebuild(index_name: str, day: date, members: pd.DataFrame, prev_close: dict[str, float], shares: SharesCache, sh: pd.DataFrame,
            *, now: datetime) -> pd.DataFrame:
    """Rows of index_weights_daily (method ``rebuilt``) for the members priced on ``day``."""
    rec = []
    for sym in members["symbol"]:
        pc = prev_close.get(sym)
        if pc is None or not np.isfinite(pc) or pc <= 0:
            continue
        n, filed_at = shares.get(sym, day)
        if not n:
            continue
        promo, public_at = promoter_pit(sh, sym, day)
        rec.append({"symbol": sym, "ffmc": n * pc * (1 - promo / 100.0), "shares": n, "shares_filed_at": filed_at, "promoter_pct": promo,
                    "promoter_public_at": public_at})
    if not rec:
        return pd.DataFrame(columns=COLUMNS["index_weights_daily"])
    tot = sum(r["ffmc"] for r in rec)
    w = {r["symbol"]: r["ffmc"] / tot for r in rec}
    if index_name in CAPPED_INDICES:
        w = apply_caps(w, *CAPPED_INDICES[index_name])
    rows = [{"index_name": index_name, "date": day, "symbol": r["symbol"], "method": "rebuilt", "weight_pct": round(w[r["symbol"]] * 100, 6),
             "ffmc_cr": round(r["ffmc"] / 1e7, 4), "shares": r["shares"], "shares_filed_at": r["shares_filed_at"], "promoter_pct": r["promoter_pct"],
             "promoter_public_at": r["promoter_public_at"], "iwf_correction": None, "computed_at": now} for r in rec]
    return pd.DataFrame(rows, columns=COLUMNS["index_weights_daily"])


def calibrate(rebuilt: pd.DataFrame, official: dict[str, float], *, now: datetime) -> pd.DataFrame:
    """``rebuilt_calibrated``: the official ten exactly, the others pro rata to 100 − Σ official; iwf_correction stored per name."""
    if rebuilt.empty or not official:
        return pd.DataFrame(columns=COLUMNS["index_weights_daily"])
    r = rebuilt.set_index("symbol")
    off = {s: v for s, v in official.items() if s in r.index}
    rest_target = 100.0 - sum(off.values())
    rest_rebuilt = float(r.loc[[s for s in r.index if s not in off], "weight_pct"].sum())
    rows = []
    for s, row in r.iterrows():
        if s in off:
            w, corr = off[s], (off[s] / row["weight_pct"]) if row["weight_pct"] else None
        else:
            w = row["weight_pct"] / rest_rebuilt * rest_target if rest_rebuilt else 0.0
            corr = (w / row["weight_pct"]) if row["weight_pct"] else None
        rows.append({**row.to_dict(), "symbol": s, "method": "rebuilt_calibrated", "weight_pct": round(float(w), 6),
                     "iwf_correction": round(float(corr), 6) if corr else None, "computed_at": now})
    return pd.DataFrame(rows, columns=COLUMNS["index_weights_daily"])


def write_weights(store: Any, df: pd.DataFrame) -> int:
    return db.upsert(store, "index_weights_daily", df, COLUMNS["index_weights_daily"], CASTS["index_weights_daily"])


def latest_calibration(store: Any, index_name: str, day: date) -> tuple[dict[str, float], date | None]:
    """The newest stored iwf_correction per symbol dated ≤ day (carried forward between top-10 files)."""
    df = db.query_df(store, """SELECT symbol, iwf_correction FROM index_weights_daily
                               WHERE index_name = ? AND method = 'rebuilt_calibrated' AND iwf_correction IS NOT NULL AND date = (
                                 SELECT MAX(date) FROM index_weights_daily WHERE index_name = ? AND method = 'rebuilt_calibrated' AND date <= ?)""",
                     [index_name, index_name, day])
    if df.empty:
        return {}, None
    d = db.to_date(db.scalar(store, "SELECT MAX(date) FROM index_weights_daily WHERE index_name = ? AND method = 'rebuilt_calibrated' AND date <= ?",
                             [index_name, day]))
    return {str(r.symbol): float(r.iwf_correction) for r in df.itertuples(index=False)}, d


def carry_calibration(rebuilt: pd.DataFrame, corrections: dict[str, float], *, now: datetime) -> pd.DataFrame:
    """Between top-10 files: apply the last known corrections and renormalise (method ``rebuilt_calibrated``, carried)."""
    if rebuilt.empty or not corrections:
        return pd.DataFrame(columns=COLUMNS["index_weights_daily"])
    r = rebuilt.copy()
    r["iwf_correction"] = r["symbol"].map(corrections).fillna(1.0)
    r["weight_pct"] = r["weight_pct"] * r["iwf_correction"]
    tot = float(r["weight_pct"].sum())
    if tot <= 0:
        return pd.DataFrame(columns=COLUMNS["index_weights_daily"])
    r["weight_pct"] = (r["weight_pct"] / tot * 100).round(6)
    r["method"], r["computed_at"] = "rebuilt_calibrated", now
    return r[COLUMNS["index_weights_daily"]]
