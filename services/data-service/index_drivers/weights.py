"""Point-in-time weights (R-DRIVERS §3): ``ffmc = shares × prev_close × (1 − promoter %)`` with ``shares`` from the newest
XBRL filing with ``filed_at ≤ d`` (split-scaled from its period end to d) and ``promoter %`` from the newest shareholding
filing with ``broadcast_ts ≤ d`` (fallback: period_end + 21 days); normalised to 100 %. Calibration on a day with NSE's top-10
file: ``iwf_correction_i = official_i / rebuilt_i`` for the ten, the rest pro rata to the remaining share.

NIFTY BANK (review M46): the capping is DATED (``CAP_SCHEDULE``). NSE's sector capping (single ≤ 33 %, top three ≤ 62 %) held
until SEBI's December 2024 rule for non-benchmark derivative indices (≥ 14 members, top ≤ 20 %, top three ≤ 45 %) was phased
in. The interim caps and their dates are inferred from the index's own closes (6 Nov 2026: the cap pair that best explains
each month's NIFTY BANK moves from stored member closes; the old 33/62 missed by ≈ 100 pts a day in 2026, 20/45 by ≈ 55),
until NSE's official cap factors are stored (owner item O-T13). There is no NSE top-10 file for BANK, so its capped weights
are then corrected by a ridge fit to the index's own published closes over the 60 sessions BEFORE the day (``fit_history``
→ ``fit_corrections``; method ``rebuilt_fitted``): point in time, so the stored residual is an out-of-sample error
(prototype on 100 sessions to 5 Nov 2026: MAE ≈ 13 pts a day against ≈ 55 for the caps alone).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from data_health import db

from index_drivers.schema import CASTS, COLUMNS

BANK_CAPS = (0.33, 0.62)                    # NSE's sector capping before the SEBI glide path (the first schedule row)
CAPPED_INDICES = {"NIFTY BANK": BANK_CAPS}  # kept for readers; the dated CAP_SCHEDULE decides
CAP_SCHEDULE: dict[str, tuple[tuple[date, tuple[float, float]], ...]] = {
    "NIFTY BANK": ((date(2000, 1, 1), BANK_CAPS),
                   (date(2025, 10, 31), (0.29, 0.58)),     # inferred tranche (Nov–Dec 2025 fit best)
                   (date(2026, 1, 12), (0.25, 0.55)),      # inferred tranche (mid-Jan 2026)
                   (date(2026, 2, 16), (0.20, 0.45))),     # the SEBI limits (best from mid-Feb 2026 on)
}
CAP_SOURCE = "inferred from NIFTY BANK's own closes (6 Nov 2026); NSE's official cap factors pending (O-T13)"
FIT_INDICES = frozenset({"NIFTY BANK"})     # no NSE top-10 file: calibrated to the index's own closes
FIT_LOOKBACK, FIT_MIN_SESSIONS = 60, 40
FIT_LAMBDA = 3e-6                           # ridge toward no correction (prototype: λ 1e-6…1e-5 all ≈ 13–16 pts OOS)
FIT_CLIP = (0.5, 1.5)


def caps_for(index_name: str, day: date) -> tuple[float, float] | None:
    """The (single, top three) caps in force for ``index_name`` on ``day``, or None for an uncapped index."""
    cur = None
    for since, caps in CAP_SCHEDULE.get(index_name, ()):
        if day >= since:
            cur = caps
    return cur


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
    caps = caps_for(index_name, day)
    if caps:
        w = apply_caps(w, *caps)
    method = "rebuilt_capped" if caps else "rebuilt"
    rows = [{"index_name": index_name, "date": day, "symbol": r["symbol"], "method": method, "weight_pct": round(w[r["symbol"]] * 100, 6),
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


# ── NIFTY BANK: the fit to the index's own closes (review M46) ───────────────────────────────────────────────────────

def fit_history(store: Any, index_name: str, day: date, lookback: int = FIT_LOOKBACK) -> pd.DataFrame:
    """The ``lookback`` stored sessions BEFORE ``day``: (date, symbol, prior_w, ret, index_ret) from the capped prior weights
    (``rebuilt_capped`` rows), the stored member returns and the stored index move. Nothing dated ``day`` or later."""
    cols = ["date", "symbol", "prior_w", "ret", "index_ret"]
    if not db.table_exists(store, "index_contribution_fit"):
        return pd.DataFrame(columns=cols)
    df = db.query_df(store, """WITH f AS (SELECT date, actual_points / NULLIF(prev_index_level, 0) AS index_ret FROM index_contribution_fit
                                          WHERE index_name = ? AND date < ? ORDER BY date DESC LIMIT ?)
                               SELECT f.date, w.symbol, w.weight_pct / 100.0 AS prior_w, c.ret_pct / 100.0 AS ret, f.index_ret
                               FROM f JOIN index_weights_daily w ON w.index_name = ? AND w.date = f.date AND w.method = 'rebuilt_capped'
                               LEFT JOIN index_contribution_daily c ON c.index_name = ? AND c.date = f.date AND c.symbol = w.symbol
                               ORDER BY f.date""", [index_name, day, lookback, index_name, index_name])
    return df if not df.empty else pd.DataFrame(columns=cols)


def fit_corrections(history: pd.DataFrame, *, lam: float = FIT_LAMBDA, min_sessions: int = FIT_MIN_SESSIONS,
                    clip: tuple[float, float] = FIT_CLIP) -> dict[str, float] | None:
    """Per-member corrections c (weight = prior × c, renormalised) minimising Σ_t (index_ret_t − Σ_i prior_it c_i r_it)²
    + λ Σ_i (c_i − 1)², clipped; None with fewer than ``min_sessions`` sessions (the prior alone is then used, and says so)."""
    if history is None or history.empty:
        return None
    h = history.dropna(subset=["index_ret", "prior_w"])
    if h["date"].nunique() < min_sessions:
        return None
    x = (h.assign(v=h["prior_w"] * h["ret"].fillna(0.0)).pivot_table(index="date", columns="symbol", values="v", aggfunc="sum").fillna(0.0))
    y = h.groupby("date")["index_ret"].first().reindex(x.index).to_numpy(dtype=float)
    xm = x.to_numpy(dtype=float)
    n = xm.shape[1]
    with np.errstate(all="ignore"):
        a = xm.T @ xm + lam * np.eye(n)
        b = xm.T @ y + lam * np.ones(n)
        c = np.linalg.solve(a, b)
    if not np.all(np.isfinite(c)):
        return None
    c = np.clip(c, *clip)
    return {str(sym): float(v) for sym, v in zip(x.columns, c, strict=True)}


def apply_corrections(prior: pd.DataFrame, corrections: dict[str, float], *, now: datetime) -> pd.DataFrame:
    """``rebuilt_fitted`` rows: the capped prior × the fitted correction, renormalised to 100 %; ``iwf_correction`` stored."""
    if prior.empty or not corrections:
        return pd.DataFrame(columns=COLUMNS["index_weights_daily"])
    r = prior.copy()
    r["iwf_correction"] = r["symbol"].map(corrections).fillna(1.0)
    r["weight_pct"] = r["weight_pct"] * r["iwf_correction"]
    tot = float(r["weight_pct"].sum())
    if tot <= 0:
        return pd.DataFrame(columns=COLUMNS["index_weights_daily"])
    r["weight_pct"] = (r["weight_pct"] / tot * 100).round(6)
    r["iwf_correction"] = r["iwf_correction"].round(6)
    r["method"], r["computed_at"] = "rebuilt_fitted", now
    return r[COLUMNS["index_weights_daily"]]
