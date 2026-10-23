#!/usr/bin/env python3
"""Family E of ml/IMPROVEMENT_PLAN_2.md Q6 for every (date, ticker) row of ml/data_10y/model_dataset.parquet.

Point in time: an announcement in the bundle of session t is usable at t (entry at t+1's open); a file dated on a
non-session date maps to the next session.  Every column at t uses only files dated <= t and prices <= t.

  sess_since_results  sessions since the most recent results release session (0 on it), capped at 126; 126 if none
  results_last_5      1 if a release session lies in [t-4, t], else 0
  results_last_20     1 if a release session lies in [t-19, t], else 0
  ear_3d              s = most recent release session; for 1 <= t-s <= 59: close[s+1]/close[s-1] - 1 minus the
                      equal-weight universe's mean of the same ratio over its members on s (adjusted closes);
                      NaN otherwise (no release within 60 sessions, or t = s)
  ear_vol_z           (volume[s] - mean(volume[s-20..s-1])) / sd(volume[s-20..s-1]) (split-adjusted volume, >= 15
                      observations, ddof 1); NaN when ear_3d is NaN
  ann_count_20        distinct non-routine announcements in [t-19, t]
  rating_20           sessions in [t-19, t] with >= 1 credit-rating announcement
  mgmt_change_60      sessions in [t-59, t] with >= 1 management-change announcement
  orders_20           sessions in [t-19, t] with >= 1 order / contract announcement
  insolvency_60       1 if an insolvency announcement lies in [t-59, t], else 0
Coverage (EVENTS.md deviation D1): a session is uncovered when its file is missing or lists fewer than 20 company
announcements; runs of >= 3 uncovered sessions are coverage gaps.  A value that a gap could change is NaN: counts
and zero flags whose window touches a gap, sess_since_results / ear_3d when a gap lies after the last observed
release inside the look-back.  A positive flag or an observed release after the last gap is kept.

Usage: python3 -m ml.events.features            (writes ml/data_ext/event_features_10y.parquet + manifest)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ml.events import classify as C

ML = Path(__file__).resolve().parents[1]
RAW = ML / "data_ext" / "events_raw.parquet"
OUT = ML / "data_ext" / "event_features_10y.parquet"
MANIFEST = ML / "data_ext" / "event_features_manifest.json"
DATASET = ML / "data_10y" / "model_dataset.parquet"
PRICES = ML / "results" / "improve" / "cache" / "features_prices_export_10y.parquet"
ETF = ML / "data_ext" / "etf_list_10y.csv"
FEATURES = ["sess_since_results", "results_last_5", "results_last_20", "ear_3d", "ear_vol_z", "ann_count_20",
            "rating_20", "mgmt_change_60", "orders_20", "insolvency_60"]
CAP = 126
EAR_WINDOW = 60
VOL_WINDOW, VOL_MIN_OBS = 20, 15
COVER_MIN_RECORDS = 20
GAP_MIN_RUN = 3
MIN_PRICE, MIN_MED_TURNOVER = 10.0, 1e7   # the dataset's universe rule (ml/data.py), verified equal to its rows
T0 = time.time()


def log(msg: str) -> None:
    print(f"[events.features +{time.time() - T0:6.0f}s] {msg}", flush=True)


# ----------------------------------------------------------------------------- inputs
EV_COLS = ["source", "file_date", "symbol", "category_raw", "text", "bm_date"]
NAV = "Declaration of NAV"


def load_prices(until=None) -> pd.DataFrame:
    p = pd.read_parquet(PRICES, columns=["date", "ticker", "close", "close_unadj", "volume", "turnover"])
    p["date"] = pd.to_datetime(p["date"])
    if until is not None:
        p = p[p["date"] <= pd.Timestamp(until)]
    etf = set(pd.read_csv(ETF)["symbol"])
    p = p[~p["ticker"].isin(etf)].sort_values(["ticker", "date"]).reset_index(drop=True)
    med = p.groupby("ticker", sort=False)["turnover"].transform(lambda s: s.rolling(20, min_periods=10).median())
    p["universe"] = (p["close_unadj"] >= MIN_PRICE) & (med >= MIN_MED_TURNOVER)
    p["volume_adj"] = p["volume"] * p["close_unadj"] / p["close"]   # split/bonus-adjusted volume
    return p


def drop_nav(ev: pd.DataFrame) -> tuple[pd.DataFrame, np.ndarray]:
    """(records without the mutual-fund NAV lines, every file date).  NAV lines are routine and enter no feature;
    the file dates keep "a file exists" for the coverage rule."""
    fd = np.sort(ev["file_date"].unique()).astype("datetime64[ns]")
    nav = ev["category_raw"].fillna("").str.startswith(NAV).to_numpy()
    return ev[~nav].reset_index(drop=True), fd


def load_events(until=None) -> tuple[pd.DataFrame, np.ndarray]:
    """events_raw without the NAV lines (EV_COLS only) and the dates of every file, optionally up to `until`."""
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
    fd = pq.read_table(RAW, columns=["file_date"]).column(0)
    t = pq.read_table(RAW, columns=EV_COLS)
    keep = pc.invert(pc.fill_null(pc.starts_with(t["category_raw"], NAV), False))
    if until is not None:
        lim = pd.Timestamp(until).to_datetime64()
        keep = pc.and_(keep, pc.less_equal(t["file_date"], pc.cast(lim, t.schema.field("file_date").type)))
        fd = pc.filter(fd, pc.less_equal(fd, pc.cast(lim, fd.type)))
    t = t.filter(keep)
    ev = t.to_pandas()
    del t
    ev["file_date"] = pd.to_datetime(ev["file_date"])
    ev["bm_date"] = pd.to_datetime(ev["bm_date"])
    files = np.unique(fd.to_numpy(zero_copy_only=False)).astype("datetime64[ns]")
    return ev, files


def coverage(ev: pd.DataFrame, file_dates: np.ndarray, sess: np.ndarray, first_seen: pd.Series) -> pd.DataFrame:
    """Per-session coverage.  Company records = non-NAV announcement records whose symbol had traded (price row) on
    or before the file date.  uncovered = no file, or fewer than COVER_MIN_RECORDS company records.  run_start /
    run_end delimit each run of consecutive uncovered sessions (by session index)."""
    an = ev[(ev["source"] == "an") & ~ev["category_raw"].fillna("").str.startswith(NAV)]
    fs = an["symbol"].astype(str).map(first_seen)
    an = an[fs.notna().to_numpy() & (fs.to_numpy(dtype="datetime64[ns]") <= an["file_date"].to_numpy(dtype="datetime64[ns]"))]
    n = an.groupby("file_date").size()
    sd = pd.DatetimeIndex(sess)
    has_file = sd.isin(pd.DatetimeIndex(file_dates))
    nrec = n.reindex(sd).fillna(0).to_numpy()
    unc = ~has_file | (nrec < COVER_MIN_RECORDS)
    S = len(sess)
    rs = np.full(S, -1)
    re_ = np.full(S, -1)
    i = 0
    while i < S:
        if unc[i]:
            j = i
            while j + 1 < S and unc[j + 1]:
                j += 1
            rs[i:j + 1], re_[i:j + 1] = i, j
            i = j + 1
        else:
            i += 1
    full_len = np.where(unc, re_ - rs + 1, 0)
    return pd.DataFrame({"session": sd, "has_file": has_file, "company_records": nrec.astype(int), "uncovered": unc,
                         "run_start": rs, "run_end": re_, "gap": unc & (full_len >= GAP_MIN_RUN)})


class Gaps:
    """Coverage gaps as known at each session t (causal): a run of uncovered sessions is a gap once it has reached
    GAP_MIN_RUN sessions by t.  Runs that ended before t use their full length; the run containing t (when t is
    uncovered) uses its length so far.  Sessions before the first session count as gap."""

    def __init__(self, cov: pd.DataFrame):
        self.S = len(cov)
        self.unc = cov["uncovered"].to_numpy()
        self.rs = cov["run_start"].to_numpy()
        gfull = cov["gap"].to_numpy()
        self.cg = np.r_[0, np.cumsum(gfull)]
        idx = np.arange(self.S)
        self.last_full = np.maximum.accumulate(np.where(gfull, idx, -1))
        self.idx = idx
        cur_len = np.where(self.unc, idx - self.rs + 1, 0)
        self.cur_gap = self.unc & (cur_len >= GAP_MIN_RUN)          # t is a gap session as of t
        self.cur_start = np.where(self.unc, self.rs, idx + 1)         # first session of the run containing t

    def _cnt_full(self, lo, hi):
        lo_c, hi_c = np.clip(lo, 0, self.S), np.clip(hi + 1, 0, self.S)
        return np.where(hi_c > lo_c, self.cg[hi_c] - self.cg[lo_c], 0)

    def any_in(self, lo: np.ndarray) -> np.ndarray:
        """Any gap session in [lo, t] as known at t, for every t (vector over t)."""
        t = self.idx
        before = self._cnt_full(lo, self.cur_start - 1) > 0             # completed runs before the current run
        cur = self.cur_gap & (self.cur_start <= t) & (t >= lo)           # the current run (overlaps [lo, t] since t is in it)
        return before | cur | (lo < 0)

    def last(self) -> np.ndarray:
        """Most recent gap session <= t as known at t (-1 if none)."""
        prev = np.where(self.cur_start - 1 >= 0, self.last_full[np.clip(self.cur_start - 1, 0, self.S - 1)], -1)
        prev = np.where(self.cur_start - 1 >= 0, prev, -1)
        return np.where(self.cur_gap, self.idx, prev)


# ----------------------------------------------------------------------------- build
def _hash_text(cat: pd.Series, txt: pd.Series) -> np.ndarray:
    h1 = pd.util.hash_pandas_object(cat.fillna("").astype(str), index=False).to_numpy()
    h2 = pd.util.hash_pandas_object(txt.fillna("").astype(str).str[:300], index=False).to_numpy()
    return h1 * np.uint64(1000003) ^ h2


def build(ev: pd.DataFrame, file_dates: np.ndarray, prices: pd.DataFrame, keys: pd.DataFrame,
          cls: pd.DataFrame | None = None, return_parts: bool = False, chunk: int = 400):
    """Family E for the (date, ticker) rows of `keys`, from the announcement records `ev` (NAV lines may be absent),
    the dates of every file, and `prices`.  The session calendar is the set of price dates.  Per-ticker blocks are
    computed `chunk` tickers at a time."""
    sess = np.sort(prices["date"].unique()).astype("datetime64[ns]")
    S = len(sess)
    tick = np.sort(prices["ticker"].unique())
    K = len(tick)
    si = np.searchsorted(sess, prices["date"].to_numpy(dtype="datetime64[ns]"))
    ki = np.searchsorted(tick, prices["ticker"].to_numpy())
    Cl = np.full((S, K), np.nan)
    Cl[si, ki] = prices["close"].to_numpy(float)
    U = np.zeros((S, K), bool)
    U[si, ki] = prices["universe"].to_numpy(bool)
    # equal-weight universe ratio per session: mean over members on s of C[s+1]/C[s-1] - 1
    with np.errstate(invalid="ignore", divide="ignore"):
        num = np.zeros(S)
        den = np.zeros(S)
        for k0 in range(0, K, 1000):
            c = Cl[:, k0:k0 + 1000]
            r = np.full(c.shape, np.nan)
            r[1:-1] = c[2:] / c[:-2] - 1.0
            m = U[:, k0:k0 + 1000] & np.isfinite(r)
            num += np.where(m, r, 0.0).sum(1)
            den += m.sum(1)
        ew = np.where(den > 0, num / np.maximum(den, 1), np.nan)
    del U
    V = np.full((S, K), np.nan)
    V[si, ki] = prices["volume_adj"].to_numpy(float)
    if cls is None:
        cls = C.classify(ev)
    first_seen = prices.groupby("ticker", sort=False)["date"].min()
    covtab = coverage(ev, file_dates, sess, first_seen)
    G = Gaps(covtab)
    idx = np.arange(S)
    gap20, gap60, gap5 = G.any_in(idx - 19), G.any_in(idx - 59), G.any_in(idx - 4)
    last_gap = G.last()
    # --- events as (session, ticker) lists
    an = ev["source"].to_numpy() == "an"
    s_ev = np.searchsorted(sess, ev["file_date"].to_numpy(dtype="datetime64[ns]"), side="left")
    sym = ev["symbol"].astype(str).to_numpy()
    k_ev = np.searchsorted(tick, sym)
    k_ok = an & (k_ev < K) & (tick[np.minimum(k_ev, K - 1)] == sym) & (s_ev < S)
    nr = cls["non_routine"].to_numpy(bool) & k_ok
    h = _hash_text(ev.loc[nr, "category_raw"], ev.loc[nr, "text"])
    nrd = pd.DataFrame({"s": s_ev[nr], "k": k_ev[nr], "h": h}).drop_duplicates()
    nr_s, nr_k = nrd["s"].to_numpy(), nrd["k"].to_numpy()
    del nrd, h
    flags = {c: (s_ev[cls[c].to_numpy(bool) & k_ok], k_ev[cls[c].to_numpy(bool) & k_ok])
             for c in ("rating", "mgmt_change", "orders", "insolvency")}
    rev = C.results_events(ev, cls, sess)
    rel = C.release_sessions(rev)
    rsym = rel["symbol"].astype(str).to_numpy()
    rk = np.searchsorted(tick, rsym)
    rok = (rk < K) & (tick[np.minimum(rk, K - 1)] == rsym)
    rel_s, rel_k = rel["s"].to_numpy()[rok], rk[rok]
    # --- keys
    kd = keys["date"].to_numpy(dtype="datetime64[ns]")
    qs = np.searchsorted(sess, kd)
    assert (qs < S).all() and (sess[qs] == kd).all(), "dataset dates outside the price calendar"
    kt = keys["ticker"].astype(str).to_numpy()
    qk = np.searchsorted(tick, kt)
    assert (qk < K).all() and (tick[qk] == kt).all(), "dataset tickers outside prices"
    res = {c: np.full(len(keys), np.nan, np.float32) for c in FEATURES}

    def dense(s_arr, k_arr, k0, n, kind):
        m = (k_arr >= k0) & (k_arr < k0 + n)
        M = np.zeros((S, n), np.float64 if kind == "count" else bool)
        if kind == "count":
            np.add.at(M, (s_arr[m], k_arr[m] - k0), 1.0)
        else:
            M[s_arr[m], k_arr[m] - k0] = True
        return M

    def wsum(M, W):
        c = np.vstack([np.zeros((1, M.shape[1])), np.cumsum(M, axis=0, dtype=np.float64)])
        return c[idx + 1] - c[np.clip(idx - W + 1, 0, S)]

    for k0 in range(0, K, chunk):
        sel_rows = np.flatnonzero((qk >= k0) & (qk < k0 + chunk))
        if not len(sel_rows):
            continue
        n = min(chunk, K - k0)
        R = dense(rel_s, rel_k, k0, n, "flag")
        lr = np.maximum.accumulate(np.where(R, idx[:, None], -1), axis=0)          # last release session <= t
        d = np.where(lr >= 0, idx[:, None] - lr, 10 ** 6)
        lo = np.where(d < CAP, lr, idx[:, None] - CAP)                              # value known iff no gap in (lo, t]
        known = (last_gap[:, None] <= lo) & (lo >= -1)
        out = {"sess_since_results": np.where(known, np.minimum(d, CAP), np.nan)}
        out["results_last_5"] = np.where(d <= 4, 1.0, np.where(gap5[:, None], np.nan, 0.0))
        out["results_last_20"] = np.where(d <= 19, 1.0, np.where(gap20[:, None], np.nan, 0.0))
        c = Cl[:, k0:k0 + n]
        v = V[:, k0:k0 + n]
        with np.errstate(invalid="ignore", divide="ignore"):
            r3 = np.full(c.shape, np.nan)
            r3[1:-1] = c[2:] / c[:-2] - 1.0
            ex = r3 - ew[:, None]
            vf = np.where(np.isfinite(v), v, 0.0)
            vn = np.isfinite(v).astype(np.float64)
            cs, cs2, cn = (np.vstack([np.zeros((1, n)), np.cumsum(a, axis=0)]) for a in (vf, vf * vf, vn))
            lo_v = np.clip(idx - VOL_WINDOW, 0, S)
            n_w = cn[idx] - cn[lo_v]
            m_w = (cs[idx] - cs[lo_v]) / n_w
            var_w = ((cs2[idx] - cs2[lo_v]) - n_w * m_w ** 2) / (n_w - 1)
            sd_w = np.sqrt(np.where(var_w > 0, var_w, np.nan))
            vz = np.where((n_w >= VOL_MIN_OBS) & (idx[:, None] - VOL_WINDOW >= 0), (v - m_w) / sd_w, np.nan)
        ear_ok = (d >= 1) & (d <= EAR_WINDOW - 1) & (last_gap[:, None] <= lr)
        lrc = np.clip(lr, 0, S - 1)
        kk = np.broadcast_to(np.arange(n), (S, n))
        ear = np.where(ear_ok, ex[lrc, kk], np.nan)
        out["ear_3d"] = ear
        out["ear_vol_z"] = np.where(ear_ok & np.isfinite(ear), vz[lrc, kk], np.nan)
        out["ann_count_20"] = np.where(gap20[:, None], np.nan, wsum(dense(nr_s, nr_k, k0, n, "count"), 20))
        for name, cl_, W, g in (("rating_20", "rating", 20, gap20), ("mgmt_change_60", "mgmt_change", 60, gap60),
                                ("orders_20", "orders", 20, gap20)):
            M = dense(*flags[cl_], k0, n, "flag").astype(np.float64)
            out[name] = np.where(g[:, None], np.nan, wsum(M, W))
        ins_n = wsum(dense(*flags["insolvency"], k0, n, "flag").astype(np.float64), 60)
        out["insolvency_60"] = np.where(ins_n > 0, 1.0, np.where(gap60[:, None], np.nan, 0.0))
        for name in FEATURES:
            res[name][sel_rows] = out[name][qs[sel_rows], qk[sel_rows] - k0].astype(np.float32)
    o = pd.DataFrame({"date": keys["date"].to_numpy(), "ticker": keys["ticker"].to_numpy()})
    for name in FEATURES:
        o[name] = res[name]
    if return_parts:
        return o, dict(sess=sess, tick=tick, releases=rel, results_events=rev, coverage=covtab, ew=ew, cls=cls)
    return o


def dataset_keys() -> pd.DataFrame:
    k = pd.read_parquet(DATASET, columns=["date", "ticker"])
    k["date"] = pd.to_datetime(k["date"])
    return k


def run() -> dict:
    keys = dataset_keys()
    prices = load_prices()
    ev, files = load_events()
    log(f"inputs: {len(keys):,} dataset rows, {len(prices):,} price rows, {len(ev):,} non-NAV records, {len(files)} files")
    cls = C.classify(ev)
    log("classified")
    out, parts = build(ev, files, prices, keys, cls=cls, return_parts=True)
    log("built")
    assert len(out) == len(keys) and (out["ticker"].to_numpy() == keys["ticker"].to_numpy()).all()
    assert not out.duplicated(["date", "ticker"]).any()
    out = out[["date", "ticker"] + FEATURES]
    tmp = OUT.with_suffix(".tmp.parquet")
    out.to_parquet(tmp, index=False)
    tmp.replace(OUT)
    cov = parts["coverage"]
    gaps = []
    g = cov[cov["gap"]]
    if len(g):
        run_id = (g["session"].diff().dt.days.fillna(99) > 7).cumsum()  # contiguous runs (calendar)
        for _, x in g.groupby(run_id):
            gaps.append({"from": str(x["session"].min().date()), "to": str(x["session"].max().date()), "sessions": int(len(x))})
    isolated = [str(d.date()) for d in cov.loc[cov["uncovered"] & ~cov["gap"], "session"]]
    man = {
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": int(len(out)), "columns": FEATURES,
        "key": ["date", "ticker"], "row_set": "identical to ml/data_10y/model_dataset.parquet (same order)",
        "sources": {"announcements": str(RAW.relative_to(ML)), "prices": str(PRICES.relative_to(ML)),
                    "universe_rule": f"close_unadj >= {MIN_PRICE} and 20-session median turnover >= {MIN_MED_TURNOVER:.0f} "
                                     "(min 10 obs), ETFs excluded: equal to the dataset's rows"},
        "point_in_time": "an announcement in the bundle of session t is usable at t (entry at t+1's open); "
                         "files on non-session dates map to the next session",
        "coverage": {"min_company_records": COVER_MIN_RECORDS, "gap_min_run": GAP_MIN_RUN, "gaps": gaps,
                     "isolated_uncovered_sessions_treated_as_empty": isolated},
        "nan_share": {c: round(float(out[c].isna().mean()), 4) for c in FEATURES},
        "release_sessions": int(len(parts["releases"])),
        "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(),
        "seconds": round(time.time() - T0, 1),
    }
    MANIFEST.write_text(json.dumps(man, indent=1))
    log(f"wrote {OUT} ({len(out):,} rows) and the manifest")
    return man


def main() -> None:
    argparse.ArgumentParser().parse_args()
    run()


if __name__ == "__main__":
    main()
