"""lablib — shared research lab for SuryaDhana swing-label research (5-20 day holds).

Data (built by build_panel.py + `python3 lablib.py features`):
  panel.parquet    one row per (entity, date), sorted by entity then date.
                   entity = ISIN-based identity (renames/splits bridged).
                   open/high/low/close/vwap are CORPORATE-ACTION ADJUSTED using
                   NSE's own PREV_CLOSE field; raw_close is the unadjusted print.
  features.parquet same row order as panel; all features are point-in-time
                   (computed only from data at or before the close of day t).
  index.parquet    NSE index OHLC by date (long format).

Typical use:
    import sys; sys.path.insert(0, "<lab dir>"); import lablib as L
    P = L.load_panel(); F = L.load_features(); fw = L.Fwd(P)
    lab = L.barrier_labels(P, F, fw, h=10, pt=2.0, sl=1.5)
    rep = L.event_report(lab["label"], F.elig_base.values & lab["valid"], P, F)

Conventions (do not break these — they are what makes the labels bias-free):
  * A signal is formed at the CLOSE of day t. The earliest executable entry is
    the OPEN of day t+1 (fw.at(P.open.values, 1)).
  * Forward windows (t, t+h] must stay inside one entity segment (no suspension
    > 45 days, no extreme corporate-action break) and within a calendar span cap.
    Use fw.ok(h) as the validity mask. NEVER fill an undefined label with 0.
  * Eligibility filters choose WHICH ROWS are samples; they never change label
    values. Eligibility columns live in features.parquet (elig_*).
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
NAN = np.nan

FEATURES = [
    "mom_5", "mom_10", "mom_20", "mom_60", "mom_120", "mom_12_1",
    "dist_sma20", "dist_sma50", "dist_sma200",
    "vol_20", "vol_60", "vol_ratio", "atr_pct", "rsi_14",
    "volz_20", "log_turn20", "deliv_pct", "deliv_z20", "deliv_ratio",
    "gap_open", "intraday", "range_pos", "hl_range",
    "hi52_dist", "lo52_dist", "hi20_dist", "max_ret_20", "min_ret_20", "up_frac_20",
    "beta_60", "idio_vol_60", "rel_mom20", "rel_mom60",
    "mkt_mom5", "mkt_mom20", "mkt_mom60", "mkt_dist_sma50", "mkt_dist_sma200",
    "mkt_vol20", "vix", "breadth50", "breadth_ad", "dispersion",
    "xr_mom20", "xr_mom60", "xr_mom120", "xr_vol20", "xr_volz", "xr_deliv_z",
    "xr_dist_sma50", "xr_hi52", "age",
]
ELIG = ["elig_series", "elig_price", "elig_liq2", "elig_liq5", "elig_seasoned",
        "elig_unlocked", "elig_next", "elig_atr", "elig_date", "elig_equity", "elig_base"]


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def load_panel(cols=None) -> pd.DataFrame:
    return pd.read_parquet(os.path.join(LAB, "panel.parquet"), columns=cols)


def load_features(cols=None) -> pd.DataFrame:
    return pd.read_parquet(os.path.join(LAB, "features.parquet"), columns=cols)


def load_index_wide(field="close") -> pd.DataFrame:
    idx = pd.read_parquet(os.path.join(LAB, "index.parquet"))
    w = idx.pivot_table(index="date", columns="index", values=field, aggfunc="last")
    return w.sort_index()


def _find_col(cols, *cands):
    low = {c.lower(): c for c in cols}
    for c in cands:
        if c.lower() in low:
            return low[c.lower()]
    return None


def market_series(name="Nifty 500"):
    """Return DataFrame(date -> open, high, low, close) for an NSE index."""
    idx = pd.read_parquet(os.path.join(LAB, "index.parquet"))
    col = _find_col(idx["index"].unique(), name, name.upper())
    if col is None:
        raise KeyError(f"index {name!r} not found")
    m = idx[idx["index"] == col].drop_duplicates("date").set_index("date").sort_index()
    return m[["open", "high", "low", "close"]]


# --------------------------------------------------------------------------- #
# Segment-aware positional helpers (fast, vectorized)
# --------------------------------------------------------------------------- #
def segment_codes(P: pd.DataFrame) -> np.ndarray:
    ent = P["entity"].values
    new_ent = np.r_[True, ent[1:] != ent[:-1]]
    brk = P["seg_break"].values.astype(bool)
    return np.cumsum(new_ent | brk) - 1


def _start_end(seg: np.ndarray):
    n = len(seg)
    i = np.arange(n)
    first = np.r_[True, seg[1:] != seg[:-1]]
    start = np.maximum.accumulate(np.where(first, i, 0))
    last = np.r_[seg[1:] != seg[:-1], True]
    end_rev = np.minimum.accumulate(np.where(last, i, n - 1)[::-1])[::-1]
    return start, end_rev


class Fwd:
    """Forward/backward access within an entity segment."""

    def __init__(self, P: pd.DataFrame):
        self.seg = segment_codes(P)
        self.start, self.end = _start_end(self.seg)
        self.n = len(P)
        self.idx = np.arange(self.n)
        self.dates = P["date"].values.astype("datetime64[D]")
        lb = P["label_block"].values.astype(bool) if "label_block" in P.columns else np.zeros(self.n, bool)
        self.lb_cs = np.cumsum(lb)

    def at(self, arr, k: int) -> np.ndarray:
        """Value at row t+k (k may be negative) within the same segment, else NaN."""
        arr = np.asarray(arr, dtype="float64")
        j = self.idx + k
        ok = (j >= self.start) & (j <= self.end)
        out = np.full(self.n, NAN)
        out[ok] = arr[j[ok]]
        return out

    def exists(self, k: int) -> np.ndarray:
        j = self.idx + k
        return (j >= self.start) & (j <= self.end)

    def span_days(self, k: int) -> np.ndarray:
        j = np.clip(self.idx + k, 0, self.n - 1)
        out = (self.dates[j] - self.dates).astype("float64")
        out[~self.exists(k)] = NAN
        return out

    def ok(self, h: int, extra_days: int = 8) -> np.ndarray:
        """Window (t, t+h] exists in-segment, spans <= ceil(h*7/5)+extra days, and
        contains no label_block row (unadjustable corporate action / unexplained jump)."""
        sp = self.span_days(h)
        cap = int(np.ceil(h * 7 / 5)) + extra_days
        ex = self.exists(h)
        j = np.clip(self.idx + h, 0, self.n - 1)
        clean = (self.lb_cs[j] - self.lb_cs) == 0
        return ex & (sp <= cap) & clean


def roll(x, w, start, kind="mean", minp=None, exclusive=False):
    """Rolling mean/std/sum over the last w rows within segment (cumsum based).
    exclusive=True uses rows t-w..t-1 (excludes today)."""
    x = np.asarray(x, dtype="float64")
    n = len(x)
    i = np.arange(n)
    if exclusive:
        x = np.r_[NAN, x[:-1]]
        start = np.minimum(start + 1, n - 1)
        start_eff = start
    else:
        start_eff = start
    valid = ~np.isnan(x)
    xf = np.where(valid, x, 0.0)
    S = np.r_[0.0, np.cumsum(xf)]
    C = np.r_[0, np.cumsum(valid)]
    lo = np.maximum(i - w + 1, start_eff)
    s = S[i + 1] - S[lo]
    c = C[i + 1] - C[lo]
    minp = w if minp is None else minp
    if exclusive:
        okmask = i >= start_eff
    else:
        okmask = np.ones(n, bool)
    if kind == "sum":
        out = s
    elif kind == "mean":
        out = s / np.maximum(c, 1)
    elif kind == "std":
        Q = np.r_[0.0, np.cumsum(xf * xf)]
        q = Q[i + 1] - Q[lo]
        var = (q - s * s / np.maximum(c, 1)) / np.maximum(c - 1, 1)
        out = np.sqrt(np.maximum(var, 0.0))
    else:
        raise ValueError(kind)
    return np.where(okmask & (c >= minp), out, NAN)


def lag(x, k, start):
    x = np.asarray(x, dtype="float64")
    i = np.arange(len(x))
    j = i - k
    ok = j >= start
    out = np.full(len(x), NAN)
    out[ok] = x[j[ok]]
    return out


# --------------------------------------------------------------------------- #
# Feature build (point-in-time)
# --------------------------------------------------------------------------- #
def build_features():
    P = load_panel()
    seg = segment_codes(P)
    start, end = _start_end(seg)
    n = len(P)
    i = np.arange(n)
    c, o, h, l = (P[k].values for k in ("close", "open", "high", "low"))
    v = P["volume_adj"].values
    F = pd.DataFrame(index=P.index)
    c1 = lag(c, 1, start)
    lr1 = np.log(c / c1)
    r1 = c / c1 - 1
    for k in (5, 10, 20, 60, 120):
        F[f"mom_{k}"] = c / lag(c, k, start) - 1
    F["mom_12_1"] = lag(c, 20, start) / lag(c, 250, start) - 1
    for w in (20, 50, 200):
        F[f"dist_sma{w}"] = c / roll(c, w, start, "mean", minp=int(w * 0.8)) - 1
    F["vol_20"] = roll(lr1, 20, start, "std", minp=15)
    F["vol_60"] = roll(lr1, 60, start, "std", minp=45)
    F["vol_ratio"] = F["vol_20"] / F["vol_60"]
    tr = np.nanmax(np.vstack([h - l, np.abs(h - c1), np.abs(l - c1)]), axis=0)
    tr = np.where(np.isnan(c1), h - l, tr)
    atr = roll(tr, 14, start, "mean", minp=14)
    F["atr_pct"] = atr / c
    gain = np.where(np.isnan(r1), NAN, np.clip(c - c1, 0, None))
    loss = np.where(np.isnan(r1), NAN, np.clip(c1 - c, 0, None))
    ag = roll(gain, 14, start, "mean", minp=14)
    al = roll(loss, 14, start, "mean", minp=14)
    rsi = 100 - 100 / (1 + ag / np.where(al == 0, NAN, al))
    rsi = np.where((al == 0) & (ag > 0), 100.0, rsi)
    rsi = np.where((al == 0) & (ag == 0), 50.0, rsi)
    F["rsi_14"] = rsi
    lv = np.log1p(v)
    mu = roll(lv, 20, start, "mean", minp=15, exclusive=True)
    sd = roll(lv, 20, start, "std", minp=15, exclusive=True)
    F["volz_20"] = (lv - mu) / np.where(sd > 0, sd, NAN)
    lt = np.log1p(P["turnover"].values)
    F["log_turn20"] = roll(lt, 20, start, "mean", minp=15)
    dp = np.clip(P["deliv_pct"].values, 0, 100)
    F["deliv_pct"] = dp
    dmu = roll(dp, 20, start, "mean", minp=15, exclusive=True)
    dsd = roll(dp, 20, start, "std", minp=15, exclusive=True)
    F["deliv_z20"] = (dp - dmu) / np.where(dsd > 0, dsd, NAN)
    F["deliv_ratio"] = dp / np.where(dmu > 0, dmu, NAN)
    F["gap_open"] = o / c1 - 1
    F["intraday"] = c / o - 1
    rng = h - l
    F["range_pos"] = (c - l) / np.where(rng > 0, rng, NAN)
    F["hl_range"] = rng / c
    s_h = pd.Series(h)
    s_l = pd.Series(l)
    gser = pd.Series(seg)
    hi52 = s_h.groupby(gser).rolling(250, min_periods=120).max().reset_index(level=0, drop=True).sort_index().values
    lo52 = s_l.groupby(gser).rolling(250, min_periods=120).min().reset_index(level=0, drop=True).sort_index().values
    F["hi52_dist"] = c / hi52 - 1
    F["lo52_dist"] = c / lo52 - 1
    h_prev = lag(h, 1, start)
    hi20 = pd.Series(h_prev).groupby(gser).rolling(20, min_periods=15).max().reset_index(level=0, drop=True).sort_index().values
    F["hi20_dist"] = c / hi20 - 1
    r1s = pd.Series(r1)
    F["max_ret_20"] = r1s.groupby(gser).rolling(20, min_periods=15).max().reset_index(level=0, drop=True).sort_index().values
    F["min_ret_20"] = r1s.groupby(gser).rolling(20, min_periods=15).min().reset_index(level=0, drop=True).sort_index().values
    F["up_frac_20"] = roll((r1 > 0).astype(float) + np.where(np.isnan(r1), NAN, 0), 20, start, "mean", minp=15)

    # market (Nifty 500) by date
    dates = P["date"].values
    mk = market_series("Nifty 500")
    cal = pd.DatetimeIndex(np.sort(np.unique(dates)))
    mk = mk.reindex(cal).ffill()
    mc = mk["close"]
    mlr = np.log(mc / mc.shift(1))
    mfeat = pd.DataFrame(index=cal)
    mfeat["mkt_mom5"] = mc / mc.shift(5) - 1
    mfeat["mkt_mom20"] = mc / mc.shift(20) - 1
    mfeat["mkt_mom60"] = mc / mc.shift(60) - 1
    mfeat["mkt_dist_sma50"] = mc / mc.rolling(50).mean() - 1
    mfeat["mkt_dist_sma200"] = mc / mc.rolling(200, min_periods=150).mean() - 1
    mfeat["mkt_vol20"] = mlr.rolling(20).std()
    mfeat["mkt_lr1"] = mlr
    try:
        vx = market_series("India VIX")["close"].reindex(cal).ffill()
        mfeat["vix"] = vx
    except KeyError:
        mfeat["vix"] = NAN
    di = pd.DatetimeIndex(dates)
    for col in ("mkt_mom5", "mkt_mom20", "mkt_mom60", "mkt_dist_sma50", "mkt_dist_sma200",
                "mkt_vol20", "vix"):
        F[col] = mfeat[col].reindex(di).values
    mlr_row = mfeat["mkt_lr1"].reindex(di).values
    mlr_row = np.where(np.isnan(lr1), NAN, mlr_row)
    x, y = lr1, mlr_row
    mx = roll(x, 60, start, "mean", minp=45)
    my = roll(y, 60, start, "mean", minp=45)
    mxy = roll(x * y, 60, start, "mean", minp=45)
    myy = roll(y * y, 60, start, "mean", minp=45)
    mxx = roll(x * x, 60, start, "mean", minp=45)
    cov = mxy - mx * my
    vy = myy - my * my
    beta = cov / np.where(vy > 0, vy, NAN)
    F["beta_60"] = beta
    vx_ = mxx - mx * mx
    F["idio_vol_60"] = np.sqrt(np.maximum(vx_ - beta * beta * vy, 0))
    F["rel_mom20"] = F["mom_20"].values - F["mkt_mom20"].values
    F["rel_mom60"] = F["mom_60"].values - F["mkt_mom60"].values

    # eligibility (shape of a tradable 5-20 day swing)
    nxt_exists = (i + 1) <= end
    nxt_gap = np.full(n, NAN)
    nxt_gap[nxt_exists] = (dates[i[nxt_exists] + 1] - dates[nxt_exists]).astype("timedelta64[D]").astype(float)
    turn20 = np.expm1(F["log_turn20"].values)
    age = i - start
    F["age"] = np.minimum(age, 500).astype(float)
    F["elig_series"] = (P["series"].values == "EQ")
    F["elig_price"] = P["raw_close"].values >= 20
    F["elig_liq2"] = turn20 >= 2e7
    F["elig_liq5"] = turn20 >= 5e7
    F["elig_seasoned"] = age >= 120
    F["elig_unlocked"] = h > l
    F["elig_next"] = nxt_exists & (nxt_gap <= 5)
    F["elig_atr"] = (F["atr_pct"].values >= 0.005) & (F["atr_pct"].values <= 0.15)
    F["elig_date"] = ~P["date_mismatch"].values.astype(bool)
    # equities only: ETFs / mutual-fund units carry INF ISINs (GOLDBEES, NIFTYBEES, ...)
    F["elig_equity"] = P["isin"].astype(str).str.startswith("INE").values
    # elig_next (t+1 trades) is look-ahead; it is kept as a column but NOT in elig_base —
    # labels are already NaN when the entry bar is missing.
    F["elig_base"] = (F["elig_series"] & F["elig_price"] & F["elig_liq2"] & F["elig_seasoned"]
                      & F["elig_unlocked"] & F["elig_atr"] & F["elig_date"] & F["elig_equity"])

    # cross-sectional (same-date) features among liquid EQ equities.
    # NOTE: no sector data — NSE constituent lists are a current snapshot and leak
    # survivorship/look-ahead (verified by the round-1 audit).
    liq = (F["elig_series"] & F["elig_liq2"] & F["elig_price"] & F["elig_equity"]).values
    dkey = pd.Series(dates)
    tmp = pd.DataFrame({"d": dates, "liq": liq, "r1": r1,
                        "above50": (F["dist_sma50"].values > 0).astype(float)})
    tl = tmp[tmp.liq]
    br = tl.groupby("d").above50.mean()
    ad = tl.groupby("d").r1.apply(lambda s: (s > 0).mean())
    disp = tl.groupby("d").r1.std()
    F["breadth50"] = br.reindex(di).values
    F["breadth_ad"] = ad.reindex(di).values
    F["dispersion"] = disp.reindex(di).values
    for src, dst in (("mom_20", "xr_mom20"), ("mom_60", "xr_mom60"), ("mom_120", "xr_mom120"),
                     ("vol_20", "xr_vol20"), ("volz_20", "xr_volz"), ("deliv_z20", "xr_deliv_z"),
                     ("dist_sma50", "xr_dist_sma50"), ("hi52_dist", "xr_hi52")):
        s = pd.Series(np.where(liq, F[src].values, NAN))
        F[dst] = s.groupby(dkey).rank(pct=True).values
    tr_rank = pd.Series(np.where(liq, turn20, NAN)).groupby(dkey).rank(ascending=False).values
    F["fno_proxy"] = tr_rank <= 200
    for col in FEATURES:
        F[col] = F[col].astype("float32")
    F.to_parquet(os.path.join(LAB, "features.parquet"), index=False)
    stats = {
        "rows": int(n), "elig_base_rows": int(F["elig_base"].sum()),
        "elig_base_share": float(F["elig_base"].mean()),
        **{c: float(F[c].mean()) for c in ELIG},
        "nan_rate_on_elig": {c: float(np.isnan(F.loc[F.elig_base, c].values).mean()) for c in FEATURES},
    }
    with open(os.path.join(LAB, "features_meta.json"), "w") as fh:
        json.dump(stats, fh, indent=1)
    print(json.dumps({k: v for k, v in stats.items() if k != "nan_rate_on_elig"}, indent=1))


# --------------------------------------------------------------------------- #
# Labels: triple barrier (path-dependent), next-open entry, gap-aware fills
# --------------------------------------------------------------------------- #
def barrier_labels(P, F, fw: Fwd, h: int, pt: float, sl: float, side: str = "long",
                   tau_bps: float = 0.0, vol_col: str = "atr_pct", cost_bps: float = 0.0,
                   pt_abs=None, sl_abs=None):
    """Triple-barrier outcome for every row.

    Entry = open[t+1]. Barriers = entry*(1 +/- m*vol[t]) (or absolute fractions
    pt_abs/sl_abs). Daily bars t+1..t+h are scanned; stop is checked before target
    on the same bar (pessimistic) and gaps through a barrier fill at the open.
    At the time barrier the return is labeled with a +/- tau_bps dead zone.
    Returns dict of arrays: label (+1 target, -1 stop, 0/+-1 time), ret (gross,
    side-signed), net (ret - cost), k (bars held), touch ('pt','sl','time'),
    mfe, mae (side-signed), valid.
    """
    sgn = 1.0 if side == "long" else -1.0
    o = P["open"].values
    hi = P["high"].values
    lo = P["low"].values
    cl = P["close"].values
    entry = fw.at(o, 1)
    vol = F[vol_col].values.astype("float64")
    up_d = pt_abs if pt_abs is not None else pt * vol
    dn_d = sl_abs if sl_abs is not None else sl * vol
    if side == "long":
        tgt, stp = entry * (1 + up_d), entry * (1 - dn_d)
    else:
        tgt, stp = entry * (1 - up_d), entry * (1 + dn_d)
    valid = fw.ok(h) & np.isfinite(entry) & (entry > 0) & np.isfinite(tgt) & np.isfinite(stp)
    n = len(P)
    label = np.full(n, NAN)
    ret = np.full(n, NAN)
    kk = np.full(n, NAN)
    touch = np.full(n, "", dtype=object)
    mfe = np.zeros(n)
    mae = np.zeros(n)
    open_ = valid.copy()
    for k in range(1, h + 1):
        ok_, hk, lk, ck = fw.at(o, k), fw.at(hi, k), fw.at(lo, k), fw.at(cl, k)
        if side == "long":
            fav, adv = hk / entry - 1, lk / entry - 1
            gap_stop = open_ & (ok_ <= stp)
            hit_stop = open_ & ~gap_stop & (lk <= stp)
            rest = open_ & ~gap_stop & ~hit_stop
            gap_tgt = rest & (ok_ >= tgt)
            hit_tgt = rest & ~gap_tgt & (hk >= tgt)
        else:
            fav, adv = -(lk / entry - 1), -(hk / entry - 1)
            gap_stop = open_ & (ok_ >= stp)
            hit_stop = open_ & ~gap_stop & (hk >= stp)
            rest = open_ & ~gap_stop & ~hit_stop
            gap_tgt = rest & (ok_ <= tgt)
            hit_tgt = rest & ~gap_tgt & (lk <= tgt)
        mfe = np.where(open_, np.fmax(mfe, np.nan_to_num(fav, nan=-np.inf)), mfe)
        mae = np.where(open_, np.fmin(mae, np.nan_to_num(adv, nan=np.inf)), mae)
        for m_, px, lab, t in ((gap_stop, ok_, -1, "sl"), (hit_stop, stp, -1, "sl"),
                               (gap_tgt, ok_, 1, "pt"), (hit_tgt, tgt, 1, "pt")):
            if m_.any():
                ret[m_] = sgn * (px[m_] / entry[m_] - 1)
                label[m_] = lab
                kk[m_] = k
                touch[m_] = t
        open_ = open_ & ~(gap_stop | hit_stop | gap_tgt | hit_tgt)
        if k == h and open_.any():
            r = sgn * (ck[open_] / entry[open_] - 1)
            ret[open_] = r
            tau = tau_bps / 1e4
            label[open_] = np.where(r > tau, 1, np.where(r < -tau, -1, 0))
            kk[open_] = h
            touch[open_] = "time"
    label[~valid] = NAN
    ret[~valid] = NAN
    mfe = np.where(valid, mfe, NAN)
    mae = np.where(valid, mae, NAN)
    return {"label": label, "ret": ret, "net": ret - cost_bps / 1e4, "k": kk,
            "touch": touch, "mfe": mfe, "mae": mae, "valid": valid}


def fwd_return(P, fw: Fwd, h: int, entry="open1", exit_="close"):
    """Executable forward return: open[t+1] -> close[t+h] (default)."""
    e = fw.at(P["open"].values, 1) if entry == "open1" else P["close"].values
    x = fw.at(P[exit_].values, h)
    r = x / e - 1
    r[~fw.ok(h)] = NAN
    return r


def market_fwd(P, h: int, name="Nifty 500"):
    """Index return over the same executable window, mapped to rows."""
    mk = market_series(name)
    cal = pd.DatetimeIndex(np.sort(np.unique(P["date"].values)))
    mk = mk.reindex(cal).ffill()
    mo = mk["open"].values
    mc = mk["close"].values
    pos = np.searchsorted(cal.values, P["date"].values)
    j1 = pos + 1
    jh = pos + h
    ok = jh < len(cal)
    out = np.full(len(P), NAN)
    out[ok] = mc[jh[ok]] / mo[j1[ok]] - 1
    return out


# --------------------------------------------------------------------------- #
# Diagnostics
# --------------------------------------------------------------------------- #
def event_report(label, mask, P, F=None, positive=1):
    """Class shares overall / by year / by month / by regime / by liquidity tercile,
    plus stability and regime-dependence diagnostics."""
    lab = np.asarray(label, dtype="float64")
    m = np.asarray(mask, bool) & ~np.isnan(lab)
    d = pd.DatetimeIndex(P["date"].values[m])
    y = lab[m]
    df = pd.DataFrame({"y": y, "year": d.year, "month": d.to_period("M").astype(str)})
    classes = sorted(np.unique(y).tolist())
    out = {"n": int(m.sum()), "classes": classes,
           "overall": {str(c): float((y == c).mean()) for c in classes}}
    out["by_year"] = {int(yr): {"n": int(len(g)), **{str(c): float((g.y == c).mean()) for c in classes}}
                      for yr, g in df.groupby("year")}
    mon = df.groupby("month").y.apply(lambda s: float((s == positive).mean()))
    out["monthly_pos"] = {"mean": float(mon.mean()), "std": float(mon.std()),
                          "min": float(mon.min()), "max": float(mon.max()),
                          "series": mon.round(4).to_dict()}
    if F is not None:
        fm = F.loc[m]
        reg = np.where(fm["mkt_dist_sma200"].values > 0, "bull", "bear")
        reg = np.char.add(reg.astype(str), np.where(fm["mkt_mom20"].values > 0, "_up20", "_dn20"))
        rr = pd.DataFrame({"y": y, "reg": reg})
        out["by_regime"] = {r: {"n": int(len(g)), **{str(c): float((g.y == c).mean()) for c in classes}}
                            for r, g in rr.groupby("reg")}
        lt = pd.Series(fm["log_turn20"].values)
        terc = lt.groupby(df.month.values).transform(lambda s: pd.qcut(s.rank(method="first"), 3, labels=False)).values
        tt = pd.DataFrame({"y": y, "t": terc})
        out["by_liquidity_tercile"] = {int(t): {"n": int(len(g)), **{str(c): float((g.y == c).mean()) for c in classes}}
                                       for t, g in tt.groupby("t")}
        # regime dependence: monthly positive share vs Nifty 500 monthly return
        try:
            mk = market_series("Nifty 500")["close"]
            mret = mk.resample("ME").last().pct_change()
            mret.index = mret.index.to_period("M").astype(str)
            j = pd.concat([mon, mret], axis=1, join="inner").dropna()
            out["corr_monthly_pos_vs_mkt_ret"] = float(j.iloc[:, 0].corr(j.iloc[:, 1]))
        except Exception:  # noqa: BLE001
            pass
    return out


def overlap_autocorr(values, P, lag_=1, sample=200000, seed=0):
    """Pooled within-entity lag autocorrelation of a label/return series."""
    v = np.asarray(values, dtype="float64")
    fw = Fwd(P)
    vl = fw.at(v, -lag_)
    ok = ~np.isnan(v) & ~np.isnan(vl)
    idx = np.flatnonzero(ok)
    if len(idx) > sample:
        idx = np.random.default_rng(seed).choice(idx, sample, replace=False)
    return float(np.corrcoef(v[idx], vl[idx])[0, 1])


# --------------------------------------------------------------------------- #
# Purged walk-forward learnability test (LightGBM)
# --------------------------------------------------------------------------- #
def walk_forward(target, mask, P, F, h, kind="binary", features=None,
                 test_years=(2023, 2024, 2025, 2026), weight=None, params=None,
                 train_start="2021-09-01", date_step=1, n_jobs=2, verbose=True):
    """Expanding-window yearly walk-forward with an h+2 trading-day embargo.

    kind: 'binary' (target in {0,1}), 'regression', or 'multiclass' (target in
    {-1,0,1}; score = P(+1) - P(-1)).
    Returns (oos_score array aligned to rows, metrics dict).
    """
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    feats = features or FEATURES
    y = np.asarray(target, dtype="float64")
    m = np.asarray(mask, bool) & ~np.isnan(y)
    dates = P["date"].values.astype("datetime64[D]")
    cal = np.unique(dates)
    if date_step > 1:
        keep_dates = cal[::date_step]
        m_train_sub = np.isin(dates, keep_dates)
    else:
        m_train_sub = np.ones(len(dates), bool)
    X = F[feats].values.astype(np.float32)
    w = None if weight is None else np.asarray(weight, dtype="float64")
    base = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=400,
                subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                n_jobs=n_jobs, verbose=-1)
    if params:
        base.update(params)
    score = np.full(len(y), NAN)
    folds = []
    for Y in test_years:
        ts = np.datetime64(f"{Y}-01-01")
        te = np.datetime64(f"{Y + 1}-01-01")
        ti = np.searchsorted(cal, ts)
        if ti >= len(cal):
            continue
        cutoff = cal[max(0, ti - h - 2)]
        tr = m & m_train_sub & (dates < cutoff) & (dates >= np.datetime64(train_start))
        tm = m & (dates >= ts) & (dates < te)
        if tr.sum() < 20000 or tm.sum() < 1000:
            continue
        if kind == "binary":
            mdl = lgb.LGBMClassifier(**base)
            mdl.fit(X[tr], y[tr].astype(int), sample_weight=None if w is None else w[tr])
            p = mdl.predict_proba(X[tm])[:, 1]
        elif kind == "multiclass":
            mdl = lgb.LGBMClassifier(objective="multiclass", **base)
            yy = (y[tr] + 1).astype(int)
            mdl.fit(X[tr], yy, sample_weight=None if w is None else w[tr])
            pr = mdl.predict_proba(X[tm])
            cls = list(mdl.classes_)
            pu = pr[:, cls.index(2)] if 2 in cls else 0
            pd_ = pr[:, cls.index(0)] if 0 in cls else 0
            p = pu - pd_
        else:
            mdl = lgb.LGBMRegressor(**base)
            mdl.fit(X[tr], y[tr], sample_weight=None if w is None else w[tr])
            p = mdl.predict(X[tm])
        score[tm] = p
        fm = {"year": Y, "n_train": int(tr.sum()), "n_test": int(tm.sum())}
        yt = y[tm]
        dd = dates[tm]
        if kind in ("binary", "multiclass"):
            yb = (yt == 1).astype(int)
            if 0 < yb.mean() < 1:
                fm["auc_up"] = float(roc_auc_score(yb, p))
            if kind == "multiclass":
                yd = (yt == -1).astype(int)
                if 0 < yd.mean() < 1:
                    fm["auc_down_inverted"] = float(roc_auc_score(yd, -p))
            t = pd.DataFrame({"d": dd, "p": p, "y": yb})
            t["r"] = t.groupby("d").p.rank(pct=True)
            fm["base_rate"] = float(t.y.mean())
            fm["top_decile_rate"] = float(t[t.r > 0.9].y.mean())
            fm["bottom_decile_rate"] = float(t[t.r <= 0.1].y.mean())
        else:
            t = pd.DataFrame({"d": dd, "p": p, "y": yt})
            ic = t.groupby("d").apply(lambda g: g.p.rank().corr(g.y.rank()) if len(g) > 20 else NAN,
                                      include_groups=False).dropna()
            fm["ic_mean"] = float(ic.mean())
            sub = ic.iloc[::max(1, h)]
            fm["ic_t_nonoverlap"] = float(sub.mean() / (sub.std() / np.sqrt(len(sub)))) if len(sub) > 3 else NAN
        folds.append(fm)
        if verbose:
            print(json.dumps(fm), flush=True)
    met = {"folds": folds}
    if folds:
        for k in ("auc_up", "auc_down_inverted", "top_decile_rate", "base_rate", "bottom_decile_rate",
                  "ic_mean", "ic_t_nonoverlap"):
            vals = [f[k] for f in folds if k in f and f[k] == f[k]]
            if vals:
                met[f"mean_{k}"] = float(np.mean(vals))
    return score, met


# --------------------------------------------------------------------------- #
# Portfolio simulation (staggered sleeves, next-open entry, costs)
# --------------------------------------------------------------------------- #
def portfolio_sim(score, mask, P, F, fw: Fwd, h, step=5, top_k=20, side="long",
                  exit_rule="time", pt=2.0, sl=1.5, cost_bps=50.0, start="2023-01-01",
                  end=None, max_per_sector=None, random_seed=None, min_score=None):
    """Select top_k rows by score (bottom_k for side='short') on every step-th
    trading date, enter at next open, exit at time barrier (close of t+h) or
    triple barrier. Capital split into ceil(h/step) staggered sleeves.
    If random_seed is set, picks are random among eligible rows (baseline)."""
    s = np.asarray(score, dtype="float64")
    m = np.asarray(mask, bool) & (~np.isnan(s) if random_seed is None else True)
    dates = P["date"].values.astype("datetime64[D]")
    cal = np.unique(dates[m])
    cal = cal[cal >= np.datetime64(start)]
    if end is not None:
        cal = cal[cal <= np.datetime64(end)]
    sig_dates = cal[::step]
    rng = np.random.default_rng(random_seed if random_seed is not None else 0)
    sectors = F["sector"].values if max_per_sector else None
    if exit_rule == "barrier":
        out = barrier_labels(P, F, fw, h, pt, sl, side=side)
        tr_ret = out["ret"]
        tr_k = out["k"]
    else:
        e = fw.at(P["open"].values, 1)
        x = fw.at(P["close"].values, h)
        sgn = 1.0 if side == "long" else -1.0
        tr_ret = sgn * (x / e - 1)
        # forced exit on suspension/break inside window: last available close
        if np.isnan(tr_ret).any():
            last = np.full(len(P), NAN)
            for k in range(1, h + 1):
                xk = fw.at(P["close"].values, k)
                last = np.where(np.isnan(xk), last, xk)
            fb = sgn * (last / e - 1)
            tr_ret = np.where(np.isnan(tr_ret) & np.isfinite(e), fb, tr_ret)
        tr_k = np.full(len(P), float(h))
    ok_trade = m & np.isfinite(tr_ret)
    idx_by_date = pd.Series(np.flatnonzero(ok_trade)).groupby(dates[ok_trade]).apply(np.array)
    cohort_rets, cohort_dates, picks_all = [], [], []
    for d in sig_dates:
        cand = idx_by_date.get(d)
        if cand is None or len(cand) == 0:
            cohort_rets.append(0.0)
            cohort_dates.append(d)
            continue
        if random_seed is not None:
            pick = rng.choice(cand, size=min(top_k, len(cand)), replace=False)
        else:
            sc = s[cand]
            if min_score is not None:
                keep = sc >= min_score if side == "long" else sc <= min_score
                cand, sc = cand[keep], sc[keep]
            order = np.argsort(-sc if side == "long" else sc)
            pick = []
            used = {}
            for j in cand[order]:
                if max_per_sector:
                    sct = sectors[j]
                    if sct != "NA" and used.get(sct, 0) >= max_per_sector:
                        continue
                    used[sct] = used.get(sct, 0) + 1
                pick.append(j)
                if len(pick) >= top_k:
                    break
            pick = np.array(pick, dtype=int)
        if len(pick) == 0:
            cohort_rets.append(0.0)
            cohort_dates.append(d)
            continue
        net = tr_ret[pick] - cost_bps / 1e4
        cohort_rets.append(float(np.mean(net)))
        cohort_dates.append(d)
        picks_all.append(pick)
    cr = np.array(cohort_rets)
    S = int(np.ceil(h / step))
    if len(cr) == 0:
        return {"error": "no cohorts"}
    sleeves = np.ones(S)
    eq = []
    for c, r in enumerate(cr):
        sleeves[c % S] *= (1 + r)
        eq.append(sleeves.mean())
    eq = np.array(eq)
    stepret = np.r_[eq[0] - 1, eq[1:] / eq[:-1] - 1]
    years = max((cohort_dates[-1] - cohort_dates[0]).astype(int) / 365.25, 1e-9) + h / 252
    allpick = np.concatenate(picks_all) if picks_all else np.array([], int)
    tnet = tr_ret[allpick] - cost_bps / 1e4
    dd = eq / np.maximum.accumulate(eq) - 1
    yr = pd.Series(stepret, index=pd.DatetimeIndex(cohort_dates))
    by_year = (yr.groupby(yr.index.year).apply(lambda s_: float(np.prod(1 + s_) - 1))).to_dict()
    res = {
        "trades": int(len(allpick)), "hit_rate": float((tnet > 0).mean()) if len(tnet) else NAN,
        "mean_trade_net": float(tnet.mean()) if len(tnet) else NAN,
        "median_trade_net": float(np.median(tnet)) if len(tnet) else NAN,
        "avg_bars_held": float(np.nanmean(tr_k[allpick])) if len(allpick) else NAN,
        "cagr": float(eq[-1] ** (1 / years) - 1), "total_return": float(eq[-1] - 1),
        "sharpe": float(stepret.mean() / stepret.std() * np.sqrt(252 / step)) if stepret.std() > 0 else NAN,
        "max_dd": float(dd.min()), "by_year": {int(k): v for k, v in by_year.items()},
        "equity": {str(pd.Timestamp(d).date()): float(v) for d, v in zip(cohort_dates, eq)},
        "params": dict(h=h, step=step, top_k=top_k, side=side, exit_rule=exit_rule, pt=pt, sl=sl,
                       cost_bps=cost_bps, start=start, max_per_sector=max_per_sector,
                       random_seed=random_seed),
    }
    return res


def benchmark(P, start="2023-01-01", end=None, name="Nifty 500"):
    mk = market_series(name)["close"]
    mk = mk[mk.index >= pd.Timestamp(start)]
    if end:
        mk = mk[mk.index <= pd.Timestamp(end)]
    years = (mk.index[-1] - mk.index[0]).days / 365.25
    r = mk.pct_change().dropna()
    eq = mk / mk.iloc[0]
    return {"cagr": float((mk.iloc[-1] / mk.iloc[0]) ** (1 / years) - 1),
            "total_return": float(mk.iloc[-1] / mk.iloc[0] - 1),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)),
            "max_dd": float((eq / eq.cummax() - 1).min()),
            "by_year": {int(y): float(g.iloc[-1] / g.iloc[0] - 1) for y, g in mk.groupby(mk.index.year)}}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "features":
        build_features()


# =========================================================================== #
# v2 EVALUATION (round 2+): daily mark-to-market simulator, horizon-matched
# random baselines, cross-sectional learnability metrics.
# Use these instead of portfolio_sim / walk_forward pooled AUC.
# =========================================================================== #
DEV = ("2023-01-01", "2025-12-31")      # selection window (exits must land by end)
HOLDOUT = ("2026-01-01", None)          # final exam (report only, never tune)


def nw_t(x, lag):
    """Newey-West t-statistic of the mean of x with Bartlett weights."""
    x = np.asarray(x, dtype="float64")
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return NAN
    xc = x - x.mean()
    s = (xc @ xc) / n
    for k in range(1, min(lag, n - 1) + 1):
        s += 2 * (1 - k / (lag + 1)) * (xc[k:] @ xc[:-k]) / n
    return float(x.mean() / np.sqrt(max(s, 1e-30) / n))


class Sim:
    """Daily mark-to-market staggered-sleeve simulator.

    Signal at the close of signal date g (row i) -> entry at the open of the
    entity's next bar -> exit at the close of bar i+h (time exit) or at a barrier
    (stop checked before target; gaps through a barrier fill at the open).
    Forced exit at the last valid close when the segment ends, a label_block row
    appears, or the sleeve's next rebalance date arrives. Costs: cost_bps round
    trip, half at entry and half at exit. Capital: S = ceil(h/step) sleeves; a
    sleeve rebalances every S*step trading days. sizing='slot' gives each pick
    1/top_k of sleeve equity (unfilled slots stay in cash earning cash_yield);
    sizing='equal' splits the sleeve equally over all picks.
    """

    def __init__(self, P, F=None, fw=None):
        self.fw = fw if fw is not None else Fwd(P)
        self.o = P["open"].values.astype("float64")
        self.hi = P["high"].values.astype("float64")
        self.lo = P["low"].values.astype("float64")
        self.c = P["close"].values.astype("float64")
        d = P["date"].values.astype("datetime64[D]")
        self.cal = np.unique(d)
        self.didx = np.searchsorted(self.cal, d)
        order = np.argsort(self.didx, kind="stable")
        b = np.searchsorted(self.didx[order], np.arange(len(self.cal) + 1))
        self._order, self._b = order, b
        self.atr = F["atr_pct"].values.astype("float64") if F is not None and "atr_pct" in F else None
        self.n = len(P)

    def rows_on(self, g):
        return self._order[self._b[g]:self._b[g + 1]]

    def _window(self, start, end_exit, h, step):
        g0 = int(np.searchsorted(self.cal, np.datetime64(start)))
        if end_exit is None:
            g_last_exit = len(self.cal) - 1
        else:
            g_last_exit = int(np.searchsorted(self.cal, np.datetime64(end_exit), side="right")) - 1
        g_last_sig = g_last_exit - h - 1
        return g0, g_last_sig, g_last_exit

    def run(self, score, mask, h, step=5, top_k=20, side="long", exit_rule="time",
            pt=2.0, sl=1.5, cost_bps=50.0, start=DEV[0], end_exit=DEV[1], cash_yield=0.0,
            random_seed=None, sizing="slot", select_quantile=None, keep_trades=False):
        """score: array aligned to rows (higher = better long candidate) or None
        with random_seed set. select_quantile=(lo, hi): instead of top_k, hold all
        rows whose same-date score percentile is in [lo, hi] (equal weight)."""
        fw = self.fw
        mask = np.asarray(mask, bool)
        if score is not None:
            score = np.asarray(score, dtype="float64")
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        g0, g_sig_last, g_end = self._window(start, end_exit, h, step)
        S = int(np.ceil(h / step))
        period = S * step
        sigs = list(range(g0, g_sig_last + 1, step))
        if not sigs:
            return {"error": "empty window"}
        D0, D1 = g0, min(g_end, sigs[-1] + period)
        nd = D1 - D0 + 1
        sleeve_eq = np.ones((S, nd))
        invested = np.zeros((S, nd))
        cost = cost_bps / 1e4
        sgn = 1.0 if side == "long" else -1.0
        trades = []
        n_forced = 0
        n_picks_total = 0
        last_w = np.zeros(S, dtype=int)
        lb_cs = fw.lb_cs
        hk = np.arange(1, h + 1)
        for j, g in enumerate(sigs):
            s = j % S
            g_next = min(g + period, D1)
            E = sleeve_eq[s, g - D0]
            cand = self.rows_on(g)
            cand = cand[mask[cand]]
            if score is not None and rng is None:
                cand = cand[np.isfinite(score[cand])]
            if rng is not None:
                k = min(top_k, len(cand)) if select_quantile is None else len(cand)
                pick = rng.choice(cand, size=k, replace=False) if k else cand[:0]
                if select_quantile is not None and len(cand):
                    lo_q, hi_q = select_quantile
                    m_ = rng.random(len(cand))
                    pick = cand[(m_ >= lo_q) & (m_ <= hi_q)]
            elif select_quantile is not None:
                sc = score[cand]
                pr = pd.Series(sc).rank(pct=True).values if len(sc) else sc
                lo_q, hi_q = select_quantile
                pick = cand[(pr >= lo_q) & (pr <= hi_q)]
            else:
                sc = score[cand]
                ordr = np.argsort(-sc if side == "long" else sc, kind="stable")
                pick = cand[ordr[:top_k]]
            days = np.arange(g + 1, g_next + 1)
            seg_len = len(days)
            if len(pick) == 0 or seg_len == 0:
                sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = E * (1 + cash_yield) ** ((days - g) / 252.0)
                last_w[s] = g_next - D0
                continue
            # bar matrix for picks
            rows_k = pick[:, None] + hk[None, :]
            rk = np.clip(rows_k, 0, self.n - 1)
            v = (rows_k <= fw.end[pick][:, None]) & ((lb_cs[rk] - lb_cs[pick][:, None]) == 0) \
                & (self.didx[rk] <= g_next)
            v = np.cumprod(v, axis=1).astype(bool)
            e = np.where(v[:, 0], self.o[rk[:, 0]], NAN)
            ok = v[:, 0] & np.isfinite(e) & (e > 0)
            pick, rk, v, e = pick[ok], rk[ok], v[ok], e[ok]
            npk = len(pick)
            n_picks_total += npk
            if npk == 0:
                sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = E * (1 + cash_yield) ** ((days - g) / 252.0)
                last_w[s] = g_next - D0
                continue
            nvalid = v.sum(1)
            px = np.where(v, self.c[rk], NAN)
            Kx = nvalid.copy()            # exit bar (1-based)
            X = px[np.arange(npk), Kx - 1]
            if exit_rule == "barrier":
                vol = self.atr[pick]
                up_d, dn_d = pt * vol, sl * vol
                if side == "long":
                    tgt, stp = e * (1 + up_d), e * (1 - dn_d)
                else:
                    tgt, stp = e * (1 - up_d), e * (1 + dn_d)
                done = np.zeros(npk, bool)
                for k in range(h):
                    act = v[:, k] & ~done
                    if not act.any():
                        continue
                    ok_, hk_, lk_ = self.o[rk[:, k]], self.hi[rk[:, k]], self.lo[rk[:, k]]
                    if side == "long":
                        gs, hs = act & (ok_ <= stp), act & (lk_ <= stp)
                        gt, ht = act & (ok_ >= tgt), act & (hk_ >= tgt)
                    else:
                        gs, hs = act & (ok_ >= stp), act & (hk_ >= stp)
                        gt, ht = act & (ok_ <= tgt), act & (lk_ <= tgt)
                    hs, gt = hs & ~gs, gt & ~gs & ~hs
                    ht = ht & ~gs & ~hs & ~gt
                    for m_, p_ in ((gs, ok_), (hs, stp), (gt, ok_), (ht, tgt)):
                        if m_.any():
                            X[m_] = p_[m_]
                            Kx[m_] = k + 1
                            px[m_, k] = p_[m_]
                            done |= m_
            forced = (nvalid < h) & (Kx == nvalid)
            n_forced += int(forced.sum())
            # mark-to-market path
            bd = np.where(v, self.didx[rk], 10 ** 9)
            bd = np.where(hk[None, :] <= Kx[:, None], bd, 10 ** 9)
            exit_day = self.didx[rk[np.arange(npk), Kx - 1]]
            cnt = (bd[:, None, :] <= days[None, :, None]).sum(2)          # (npk, nd)
            idx = np.clip(cnt - 1, 0, h - 1)
            price = np.take_along_axis(np.nan_to_num(px, nan=0.0), idx, axis=1)
            rel = price / e[:, None]
            gross = np.where(cnt == 0, 1.0, (1 + sgn * (rel - 1)) * (1 - cost / 2))
            after = days[None, :] >= exit_day[:, None]
            gross = np.where(after, gross * (1 - cost / 2), gross)
            w = (1.0 / top_k) if sizing == "slot" and select_quantile is None else (1.0 / npk)
            cash_frac = max(0.0, 1 - w * npk)
            cg = (1 + cash_yield) ** ((days - g) / 252.0)
            path = cash_frac * cg + w * gross.sum(0)
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = E * path
            invested[s, g - D0 + 1:g_next - D0 + 1] = w * (~after).sum(0)
            last_w[s] = g_next - D0
            net = sgn * (X / e - 1) - cost
            if keep_trades:
                for a in range(npk):
                    trades.append((str(self.cal[g]), int(pick[a]), float(net[a]), int(Kx[a]), bool(forced[a])))
            else:
                trades.append(np.c_[net, Kx, forced])
            # carry sleeve equity flat after g_next is handled by the next signal of this sleeve
        # sleeves that have not started yet stay at 1 (cash); after a sleeve's last
        # window ends, carry its final equity forward to the end of the window.
        for s_ in range(S):
            lw = last_w[s_]
            if 0 < lw < nd - 1:
                sleeve_eq[s_, lw + 1:] = sleeve_eq[s_, lw]
        eq = sleeve_eq.mean(0)
        dates = self.cal[D0:D1 + 1]
        r = np.r_[0.0, eq[1:] / eq[:-1] - 1]
        yrs = max((dates[-1] - dates[0]).astype(int) / 365.25, 1e-9)
        dd = eq / np.maximum.accumulate(eq) - 1
        if keep_trades:
            tn = np.array([t[2] for t in trades]) if trades else np.array([])
            tk = np.array([t[3] for t in trades]) if trades else np.array([])
        else:
            T = np.vstack(trades) if trades else np.zeros((0, 3))
            tn, tk = T[:, 0], T[:, 1]
        ser = pd.Series(eq, index=pd.DatetimeIndex(dates))
        by_year = {int(y): float(gq.iloc[-1] / gq.iloc[0] - 1) for y, gq in ser.groupby(ser.index.year)}
        out = {
            "cagr": float(eq[-1] ** (1 / yrs) - 1), "total_return": float(eq[-1] - 1),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else NAN,
            "max_dd": float(dd.min()), "ann_vol": float(r.std() * np.sqrt(252)),
            "exposure": float(invested.mean()),
            "trades": int(len(tn)), "hit_rate": float((tn > 0).mean()) if len(tn) else NAN,
            "mean_trade_net": float(tn.mean()) if len(tn) else NAN,
            "median_trade_net": float(np.median(tn)) if len(tn) else NAN,
            "avg_bars": float(tk.mean()) if len(tk) else NAN, "forced_exits": int(n_forced),
            "by_year": by_year,
            "params": dict(h=h, step=step, top_k=top_k, side=side, exit_rule=exit_rule, pt=pt, sl=sl,
                           cost_bps=cost_bps, start=start, end_exit=end_exit, sizing=sizing,
                           select_quantile=select_quantile, random_seed=random_seed),
            "_daily_ret": r, "_dates": dates, "_equity": eq,
        }
        if keep_trades:
            out["_trades"] = trades
        return out

    def random_band(self, mask, h, seeds=(1, 2, 3, 4, 5), **kw):
        runs = [self.run(None, mask, h, random_seed=s, **kw) for s in seeds]
        rr = np.vstack([x["_daily_ret"] for x in runs])
        return {
            "cagr_mean": float(np.mean([x["cagr"] for x in runs])),
            "cagr_sd": float(np.std([x["cagr"] for x in runs])),
            "sharpe_mean": float(np.mean([x["sharpe"] for x in runs])),
            "max_dd_mean": float(np.mean([x["max_dd"] for x in runs])),
            "mean_trade_net": float(np.mean([x["mean_trade_net"] for x in runs])),
            "by_year_mean": {y: float(np.mean([x["by_year"].get(y, NAN) for x in runs]))
                             for y in runs[0]["by_year"]},
            "_daily_ret_mean": rr.mean(0), "_dates": runs[0]["_dates"],
        }

    def compare(self, score, mask, h, seeds=(1, 2, 3, 4, 5), **kw):
        """Strategy vs horizon-matched random baseline on the same mask/params."""
        st = self.run(score, mask, h, **kw)
        rb = self.random_band(mask, h, seeds=seeds, **kw)
        diff = st["_daily_ret"] - rb["_daily_ret_mean"]
        res = {k: v for k, v in st.items() if not k.startswith("_")}
        res["random"] = {k: v for k, v in rb.items() if not k.startswith("_")}
        res["excess_cagr_vs_random"] = st["cagr"] - rb["cagr_mean"]
        res["excess_daily_nw_t"] = nw_t(diff, lag=h)
        res["excess_ann_return"] = float(diff.mean() * 252)
        return res


def xs_metrics(score, target, mask, P, h, binary_target=None):
    """Per-date cross-sectional rank IC (score vs continuous target) and, if a
    binary target is given, per-date AUC. Means plus non-overlapping t-stats
    (every h-th date), split by dev/holdout."""
    from scipy.stats import rankdata
    s = np.asarray(score, dtype="float64")
    y = np.asarray(target, dtype="float64")
    m = np.asarray(mask, bool) & np.isfinite(s) & np.isfinite(y)
    d = P["date"].values.astype("datetime64[D]")[m]
    df = pd.DataFrame({"d": d, "s": s[m], "y": y[m]})
    if binary_target is not None:
        df["b"] = np.asarray(binary_target, dtype="float64")[m]
    rows = []
    for dt, g in df.groupby("d", sort=True):
        if len(g) < 30:
            continue
        rs, ry = rankdata(g.s.values), rankdata(g.y.values)
        ic = np.corrcoef(rs, ry)[0, 1]
        auc = NAN
        if binary_target is not None:
            b = g.b.values
            ok = np.isfinite(b)
            pos = b[ok] == 1
            n1, n0 = pos.sum(), (~pos).sum()
            if n1 > 5 and n0 > 5:
                rr = rankdata(g.s.values[ok])
                auc = (rr[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
        rows.append((dt, ic, auc))
    t = pd.DataFrame(rows, columns=["d", "ic", "auc"]).set_index("d")
    out = {}
    for name, (a, b) in (("dev", DEV), ("holdout", (HOLDOUT[0], "2100-01-01"))):
        sub = t[(t.index >= np.datetime64(a)) & (t.index <= np.datetime64(b))]
        if not len(sub):
            continue
        nov = sub.iloc[::max(1, h)]
        for col in ("ic", "auc"):
            x = nov[col].dropna()
            if len(x) > 3:
                out[f"{name}_{col}_mean"] = float(sub[col].mean())
                out[f"{name}_{col}_t_nonoverlap"] = float(x.mean() / (x.std() / np.sqrt(len(x)))) if col == "ic" \
                    else float((x.mean() - 0.5) / (x.std() / np.sqrt(len(x))))
        out[f"{name}_ic_by_year"] = {int(y): float(gq.ic.mean()) for y, gq in sub.groupby(sub.index.year)}
    return out


def walk_forward2(target, mask, P, F, h, kind="regression", features=None,
                  test_years=(2023, 2024, 2025, 2026), weight=None, params=None,
                  train_start="2021-09-01", date_step=2, n_jobs=2, min_train=5000,
                  min_test=200, score_all_mask=True, verbose=False, date_offset=0):
    """Like walk_forward, but (a) scores ALL mask rows in each test year (not only
    rows with a defined label — no look-ahead filter), (b) configurable minimum
    fold sizes for sparse event masks, (c) never trains on NaN targets.
    Returns oos score array. Evaluate with xs_metrics() and Sim.compare()."""
    import lightgbm as lgb
    feats = features or FEATURES
    y = np.asarray(target, dtype="float64")
    mask = np.asarray(mask, bool)
    m_lab = mask & np.isfinite(y)
    dates = P["date"].values.astype("datetime64[D]")
    cal = np.unique(dates)
    sub = np.isin(dates, cal[date_offset::date_step]) if date_step > 1 else np.ones(len(dates), bool)
    X = F[feats].values.astype(np.float32)
    w = None if weight is None else np.asarray(weight, dtype="float64")
    base = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=400,
                subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                n_jobs=n_jobs, verbose=-1)
    if params:
        base.update(params)
    score = np.full(len(y), NAN)
    for Y in test_years:
        ts, te = np.datetime64(f"{Y}-01-01"), np.datetime64(f"{Y + 1}-01-01")
        ti = int(np.searchsorted(cal, ts))
        if ti >= len(cal):
            continue
        cutoff = cal[max(0, ti - h - 2)]
        tr = m_lab & sub & (dates < cutoff) & (dates >= np.datetime64(train_start))
        tm = (mask if score_all_mask else m_lab) & (dates >= ts) & (dates < te)
        if tr.sum() < min_train or tm.sum() < min_test:
            if verbose:
                print(f"skip fold {Y}: train {tr.sum()} test {tm.sum()}")
            continue
        if kind == "binary":
            mdl = lgb.LGBMClassifier(**base)
            mdl.fit(X[tr], y[tr].astype(int), sample_weight=None if w is None else w[tr])
            score[tm] = mdl.predict_proba(X[tm])[:, 1]
        elif kind == "multiclass":
            mdl = lgb.LGBMClassifier(objective="multiclass", **base)
            mdl.fit(X[tr], (y[tr] + 1).astype(int), sample_weight=None if w is None else w[tr])
            pr = mdl.predict_proba(X[tm])
            cls = list(mdl.classes_)
            pu = pr[:, cls.index(2)] if 2 in cls else 0.0
            pdn = pr[:, cls.index(0)] if 0 in cls else 0.0
            score[tm] = pu - pdn
        else:
            mdl = lgb.LGBMRegressor(**base)
            mdl.fit(X[tr], y[tr], sample_weight=None if w is None else w[tr])
            score[tm] = mdl.predict(X[tm])
        if verbose:
            print(f"fold {Y}: train {int(tr.sum())} test {int(tm.sum())}", flush=True)
    return score
