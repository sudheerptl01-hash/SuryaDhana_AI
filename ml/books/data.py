"""Data layer for the P2 book-construction stream.

* ``load_base`` / ``load_scores`` rebuild the exact base panel of ``ml/scale5y_report.py`` (v1 dataset rows
  with a clean 20-session label over the 43 monthly folds + holdout, joined to the frozen preds).
* ``load_prices`` builds the ``sessions, tick, O, adv20`` objects that ``ml.strategy_backtest.build_blocks``
  expects, from ``ml/results/improve/cache/features_prices_export_v1.parquet`` (the equity_features rows the
  DuckDB served; the DuckDB itself is never opened here).
* ``cost_components`` computes the name-level cost inputs (Corwin-Schultz spread, daily sigma, ADV20).
* ``forward_absret_max`` gives the 40-session analogue of the dataset's y_clean_20d split/circuit screen.
* ``industry_map`` reads (or, if absent, creates) ``ml/data_ext/industry_map.csv`` from the four NSE lists.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ML_DIR = Path(__file__).resolve().parents[1]
DATA_5Y = ML_DIR / "data_5y"
SCALE5Y = ML_DIR / "results" / "scale5y"
PREDS = SCALE5Y / "preds"
PRICES_PARQUET = ML_DIR / "results" / "improve" / "cache" / "features_prices_export_v1.parquet"
INDUSTRY_MAP = ML_DIR / "data_ext" / "industry_map.csv"
TASK = "beat_mkt_20d"
PRICE_START = "2022-10-03"          # scale5y_report.load_prices: equity_features WHERE date >= 2022-10-03
SPLIT_MOVE_THRESHOLD = 0.22         # ml/data.py: |ret_1d| above this poisons a label window (split / circuit)
HEUR = "heuristic_mom20"

INDUSTRY_LISTS = (                  # first list wins on duplicate symbols
    ("ind_nifty500list.csv", "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"),
    ("ind_niftymidcap150list.csv", "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv"),
    ("ind_niftysmallcap250list.csv", "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"),
    ("ind_niftymicrocap250_list.csv", "https://archives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv"),
)
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/124.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------- base panel and scores
def load_splits() -> dict:
    return json.loads((DATA_5Y / "splits.json").read_text())


def load_base(splits: dict) -> pd.DataFrame:
    """Same rows, order and derived columns as ml/scale5y_report.py load_base (plus the two neutralisation
    controls atr_pct and log_turnover, which it also loads as features)."""
    cols = ["date", "ticker", "y_raw_20d", "y_excess_20d", "label_beat_mkt_20d", "y_clean_20d",
            "cs_rank_turnover", "cs_rank_mom_20", "log_turnover", "atr_pct"]
    d = pd.read_parquet(DATA_5Y / "model_dataset.parquet", columns=cols)
    d["date"] = pd.to_datetime(d["date"])
    fold = pd.Series(pd.NA, index=d.index, dtype="object")
    for s in splits["folds"] + [splits["holdout"]]:
        fold[(d["date"] >= s["test_start"]) & (d["date"] <= s["test_end"])] = s["name"]
    d["fold"] = fold
    m = d["fold"].notna() & d["label_beat_mkt_20d"].notna() & d["y_clean_20d"].astype(bool)
    base = d[m].sort_values(["date", "ticker"]).reset_index(drop=True)
    base["segment"] = np.where(base["fold"] == "holdout", "holdout", "cv")
    base["mkt_med"] = base["y_raw_20d"] - base["y_excess_20d"]
    base["month"] = base["date"].dt.strftime("%Y-%m")
    return base


def load_scores(base: pd.DataFrame, models: list[str]) -> tuple[dict, dict]:
    """Frozen preds joined on (date, ticker) exactly as ml/scale5y_report.py load_scores (label check, one-to-one
    join, momentum heuristic = cs_rank_mom_20 with NaN -> 0.5, every score finite)."""
    key = base[["date", "ticker"]]
    y = base["label_beat_mkt_20d"].to_numpy(float)
    scores, meta = {}, {}
    for m in models:
        if m == HEUR:
            h = base["cs_rank_mom_20"].to_numpy(float)
            scores[m] = np.where(np.isfinite(h), h, 0.5)
            meta[m] = {"source": "cs_rank_mom_20 (NaN -> 0.5)", "coverage": float(np.isfinite(h).mean())}
            continue
        p = PREDS / f"{m}__{TASK}.parquet"
        pr = pd.read_parquet(p, columns=["date", "ticker", "score", "y"])
        pr["date"] = pd.to_datetime(pr["date"])
        mm = key.merge(pr, on=["date", "ticker"], how="left", validate="one_to_one")
        sc = mm["score"].to_numpy(float)
        ok = np.isfinite(sc)
        assert np.array_equal(mm["y"].to_numpy(float)[ok], y[ok]), f"{m}: label mismatch"
        scores[m] = sc
        meta[m] = {"source": str(p.relative_to(ML_DIR.parent)), "coverage": float(ok.mean()),
                   "n_pred_rows": int(len(pr))}
    for m, v in scores.items():
        assert np.isfinite(v).all(), f"{m}: non-finite scores on {int((~np.isfinite(v)).sum())} rows"
    return scores, meta


# --------------------------------------------------------------------------- prices
def read_price_parquet() -> pd.DataFrame:
    s = pd.read_parquet(PRICES_PARQUET, columns=["date", "ticker", "open", "high", "low", "close", "turnover"])
    s["date"] = pd.to_datetime(s["date"])
    assert not s.duplicated(["date", "ticker"]).any()
    return s


def load_prices(base: pd.DataFrame, raw: pd.DataFrame):
    """Parquet twin of ml/scale5y_report.py load_prices: open and turnover pivoted date x ticker on the sessions
    from 2022-10-03, ADV20 = 20-session rolling median turnover (min_periods 10)."""
    s = raw.loc[raw["date"] >= PRICE_START, ["date", "ticker", "open", "turnover"]]
    sessions = pd.DatetimeIndex(sorted(s["date"].unique()))
    tick = np.array(sorted(base["ticker"].unique()))
    s = s[s["ticker"].isin(tick)]
    O = s.pivot(index="date", columns="ticker", values="open").reindex(index=sessions, columns=tick)
    T = s.pivot(index="date", columns="ticker", values="turnover").reindex(index=sessions, columns=tick)
    adv20 = T.rolling(20, min_periods=10).median()
    return sessions, tick, O, adv20


def _own_series(raw: pd.DataFrame, tick: np.ndarray) -> pd.DataFrame:
    r = raw[raw["ticker"].isin(tick)].sort_values(["ticker", "date"]).reset_index(drop=True)
    g = r.groupby("ticker", sort=False)
    r["prev_close"] = g["close"].shift(1)
    r["ret_1d"] = r["close"] / r["prev_close"] - 1.0          # == the dataset's ret_1d (checked: 100% of rows)
    return r


def corwin_schultz_2day(r: pd.DataFrame) -> np.ndarray:
    """Corwin & Schultz (2012) two-day high-low spread estimate for the pair (t-1, t) of each ticker's consecutive
    trading days, assigned to day t, with the paper's overnight-return adjustment of day t's high/low (if day t's
    low is above day t-1's close, or its high below it, both are shifted by the gap). Negative values are kept
    (floored after the rolling median)."""
    g = r.groupby("ticker", sort=False)
    h1, l1, c0 = r["high"].to_numpy(float), r["low"].to_numpy(float), g["close"].shift(1).to_numpy(float)
    h0, l0 = g["high"].shift(1).to_numpy(float), g["low"].shift(1).to_numpy(float)
    up = np.where(np.isfinite(c0) & (l1 > c0), l1 - c0, 0.0)          # gap up: shift day t down
    dn = np.where(np.isfinite(c0) & (h1 < c0), c0 - h1, 0.0)          # gap down: shift day t up
    h1a, l1a = h1 - up + dn, l1 - up + dn
    with np.errstate(invalid="ignore", divide="ignore"):
        beta = np.log(h0 / l0) ** 2 + np.log(h1a / l1a) ** 2
        gamma = np.log(np.maximum(h0, h1a) / np.minimum(l0, l1a)) ** 2
        k = 3.0 - 2.0 * np.sqrt(2.0)
        alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
        S = 2.0 * (np.exp(alpha) - 1.0) / (1.0 + np.exp(alpha))
    ok = np.isfinite(h0) & np.isfinite(l0) & (h0 > 0) & (l0 > 0) & (h1a > 0) & (l1a > 0)
    return np.where(ok, S, np.nan)


def cost_components(raw: pd.DataFrame, sessions: pd.DatetimeIndex, tick: np.ndarray, adv20: pd.DataFrame) -> dict:
    """Name-level cost inputs on the engine's session x ticker grid, all point-in-time at the session:
    half_spread = 0.5 x max(0, 60-session rolling median of the Corwin-Schultz two-day estimate);
    sigma = 20-session sd of the daily close-to-close return (|r| > 22% split/circuit days excluded, as the
    program's regime volatility does); adv = ADV20 of the engine. Gaps: a missing component is carried forward up
    to 20 sessions, then replaced by that session's cross-sectional median (spread, sigma) or Rs 1 crore (ADV,
    the universe's minimum median turnover)."""
    r = _own_series(raw, tick)
    r["cs2"] = corwin_schultz_2day(r)
    rr = r["ret_1d"].where(r["ret_1d"].abs() <= SPLIT_MOVE_THRESHOLD)
    g = r.groupby("ticker", sort=False)
    r["cs_med60"] = g["cs2"].transform(lambda s: s.rolling(60, min_periods=20).median())
    r["sigma20"] = rr.groupby(r["ticker"], sort=False).transform(lambda s: s.rolling(20, min_periods=10).std())

    def grid(col: str) -> pd.DataFrame:
        return r.pivot(index="date", columns="ticker", values=col).reindex(index=sessions, columns=tick)

    spread = grid("cs_med60").clip(lower=0.0).ffill(limit=20)
    sigma = grid("sigma20").ffill(limit=20)
    fill_note = {"spread_nan_before_fill": float(spread.isna().to_numpy().mean()),
                 "sigma_nan_before_fill": float(sigma.isna().to_numpy().mean())}
    spread = spread.T.fillna(spread.median(axis=1)).T
    sigma = sigma.T.fillna(sigma.median(axis=1)).T
    adv = adv20.where(adv20 > 0).ffill(limit=20).fillna(1e7)
    return {"half_spread": 0.5 * spread.to_numpy(float), "sigma": sigma.to_numpy(float),
            "adv": adv.to_numpy(float), "fill": fill_note, "own": r}


def forward_absret_max(own: pd.DataFrame, sessions: pd.DatetimeIndex, tick: np.ndarray, w: int) -> np.ndarray:
    """max |ret_1d| over sessions t+1 .. t+w (the ticker's own close-to-close returns; sessions it did not trade are
    skipped), on the engine's session x ticker grid: the y_clean_20d screen of ml/data.py extended to w sessions."""
    a = own.pivot(index="date", columns="ticker", values="ret_1d").reindex(index=sessions, columns=tick).abs()
    fm = a.iloc[::-1].rolling(w, min_periods=1).max().iloc[::-1].shift(-1)
    return fm.to_numpy(float)


# --------------------------------------------------------------------------- industry map
def _download(url: str, tries: int = 3) -> bytes:
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "text/csv,*/*"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as e:                      # noqa: BLE001 -- retried, then re-raised
            last = e
            time.sleep(60 if "403" in str(e) or "429" in str(e) else 1.5)
    raise RuntimeError(f"download failed: {url}: {last}")


def industry_map(log=print) -> tuple[dict, dict]:
    """symbol -> NSE industry. Uses ml/data_ext/industry_map.csv when it exists (another stream may have written
    it); otherwise downloads the four NSE index lists (browser user agent, one request at a time, 1-2 s apart),
    parses them as data with the csv module and writes the map (symbol,industry,source_list; first list wins)."""
    prov = {"path": str(INDUSTRY_MAP.relative_to(ML_DIR.parent))}
    if not INDUSTRY_MAP.exists():
        rows, seen, files = [], set(), {}
        for i, (name, url) in enumerate(INDUSTRY_LISTS):
            if i:
                time.sleep(1.0 + 0.25 * i)
            blob = _download(url)
            files[name] = {"url": url, "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
            rd = csv.DictReader(io.StringIO(blob.decode("utf-8-sig", errors="replace")))
            n = 0
            for rec in rd:
                sym = (rec.get("Symbol") or "").strip()
                ind = (rec.get("Industry") or "").strip()
                if not sym or not ind:
                    continue
                n += 1
                if sym in seen:
                    continue
                seen.add(sym)
                rows.append((sym, ind, name.replace(".csv", "")))
            files[name]["rows"] = n
            log(f"industry list {name}: {n} rows")
        INDUSTRY_MAP.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDUSTRY_MAP.with_suffix(".csv.tmp_books")
        with open(tmp, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["symbol", "industry", "source_list"])
            w.writerows(sorted(rows))
        try:                                        # never clobber a map another stream wrote meanwhile
            os.link(tmp, INDUSTRY_MAP)
            prov.update({"created_by": "ml/books (this stream)", "lists": files})
        except FileExistsError:
            prov["note"] = "another stream wrote the map while this one downloaded; theirs is used"
        finally:
            tmp.unlink(missing_ok=True)
    else:
        prov["created_by"] = "file already in place, used as found"
    m = pd.read_csv(INDUSTRY_MAP, dtype=str)
    cols = {c.lower(): c for c in m.columns}
    sc = cols.get("symbol") or cols.get("ticker")
    ic = cols.get("industry")
    assert sc and ic, f"industry map needs symbol and industry columns, has {list(m.columns)}"
    m = m.dropna(subset=[sc, ic])
    mp = dict(zip(m[sc].str.strip(), m[ic].str.strip()))
    prov.update({"n_symbols": len(mp), "n_industries": len(set(mp.values())),
                 "sha256": hashlib.sha256(INDUSTRY_MAP.read_bytes()).hexdigest()})
    return mp, prov
