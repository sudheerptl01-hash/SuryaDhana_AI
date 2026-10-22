#!/usr/bin/env python3
"""Pre-registered external-data feature families F1-F4 (ml/IMPROVEMENT_PLAN.md
section 2-P3; definitions fixed in the P3 task brief).

Outputs (ml/data_ext/)
----------------------
extra_features.parquet   key (date, ticker): F2 sector (10) + F3 F&O (8) for
                         every EOD-export row from 2022-10-03 that passes the
                         universe filter (close >= 10 and trailing 20-session
                         median turnover >= 1e7, min 10 obs -- ml/data.py)
market_state.parquet     key date: F1 market state (10) + F4 flows (4)
extra_features_manifest.json  families, definitions, conventions, sources

Point in time: every value at date t uses only EOD bars and archive files
dated <= t (rolling windows / shifts on past values; same-day end-of-day
prints allowed, the convention of every existing feature: labels enter at
the NEXT open). Each external source's sessions are counted on that source's
own file calendar; EOD-derived series on the EOD export's calendar.

Conventions fixed before any IC was computed (data-integrity reasons):
* aggregates (EW market return, breadth, dispersion, industry medians/ranks)
  run over the universe EXCLUDING ETFs, i.e. the v2 universe definition, so
  the values for stocks are the same whether the file is joined to v1 or v2;
  ETF rows (v1 only) get F2 values inside their own "ETF" group;
* universe names without an NSE industry form an explicit "Unclassified"
  group, and names in unmapped industries / Unclassified / ETFs take the
  Nifty 500 20-session return as secidx_ret_20 (the constituent lists are a
  2026-10-19 snapshot: a NaN pattern would mark today's index members, a
  look-ahead; measured in the report). build(policy={"unclassified": "nan",
  "secidx_unmapped": "nan"}) reproduces the literal brief for comparison;
* the EW market return excludes single-day moves with |r| > 0.22 (the repo's
  SPLIT_MOVE threshold: unadjusted splits/bonuses; NSE price bands cap
  non-F&O names at 20%); cs_dispersion_20 is taken over names with
  flag_split_20d == 0 (no such move in the trailing 20 sessions).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.extdata import common as C  # noqa: E402

SPLIT_MOVE = 0.22
SELLOFF = -0.08
SELLOFF_CAP = 252
GROUP_MIN = 5
UNCLASSIFIED = "Unclassified"
ETF_GROUP = "ETF"
# Leak-safe conventions (see module docstring and the P3 report): names without
# an industry label form an "Unclassified" group; unmapped / unclassified
# names take the broad-market index's 20-session return as secidx_ret_20.
# The literal brief (NaN for both) is available for comparison via build(...).
SECIDX_DEFAULT_INDEX = "Nifty 500"
POLICY_DEFAULT = {"unclassified": "group", "secidx_unmapped": "default_index"}
# label-study fallback ETF rule (ml/label_study.py) when P1's list is absent
ETF_PATTERN = (r"(?:BEES|ETF|LIQUID|LIQID|GILT|BETF|SENSEX|NIFTY|GOLD|SILV|CASE$|360$|"
               r"BND$|BETA$|ADD$)")
ETF_NAME_EXCEPTIONS = {"BETA", "SKYGOLD", "SILVERTUC", "SHANTIGOLD", "GOLDIAM",
                       "PNBGILTS", "DECNGOLD"}

F1 = ["mkt_ret_20", "mkt_ret_63", "mkt_dd_252", "mkt_vol_20", "mkt_breadth_200",
      "sessions_since_selloff", "cs_dispersion_20", "vix_close", "vix_chg_20",
      "nifty50_pe"]
F2 = ["ind_mom_20", "ind_ret_63", "rel_mom_20", "rel_ret_126", "rel_deliv",
      "indn_rank_mom_20", "indn_rank_ret_126", "indn_rank_deliv_sma", "indn_rank_atr",
      "secidx_ret_20"]
F3 = ["fo_member", "fut_basis_near", "fut_oi_chg_5", "fut_oi_chg_20", "fut_oi_z_60",
      "pcr_oi", "pcr_chg_5", "opt_oi_to_turnover"]
F4 = ["fii_idx_fut_net", "fii_idx_fut_net_chg_5", "fii_stk_fut_net", "client_idx_pcr"]
FAMILIES = {"F1_market_state": F1, "F2_sector": F2, "F3_fo": F3, "F4_flows": F4}
BASE = ["mom_20", "ret_63d", "ret_126d", "deliv_pct_sma_20", "atr_pct"]


# ========================================================================= #
# inputs
# ========================================================================= #

def load_eod(eod_path: Path = C.EOD_EXPORT, max_date: pd.Timestamp | None = None
             ) -> pd.DataFrame:
    cols = ["date", "ticker", "high", "low", "close", "turnover", "deliv_pct"]
    eod = pd.read_parquet(eod_path, columns=cols)
    eod["date"] = pd.to_datetime(eod["date"])
    if max_date is not None:
        eod = eod[eod["date"] <= max_date]
    assert not eod.duplicated(["date", "ticker"]).any(), "duplicate (date, ticker)"
    return eod.sort_values(["ticker", "date"]).reset_index(drop=True)


def load_etf_set(tickers: pd.Index) -> tuple[set, str]:
    import hashlib
    p = C.EXT / "etf_list.csv"
    if p.exists():
        e = pd.read_csv(p)
        col = next((c for c in e.columns if c.strip().lower() in ("ticker", "symbol")), None)
        if col is not None:
            sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            return (set(e[col].astype(str).str.strip()),
                    f"ml/data_ext/etf_list.csv (P1; {len(e)} rows; sha256 {sha})")
    t = pd.Series(tickers.astype(str))
    m = t.str.contains(ETF_PATTERN, regex=True) & ~t.isin(ETF_NAME_EXCEPTIONS)
    return set(t[m]), "ml/label_study.py name rule (P1 etf_list.csv absent at build time)"


def alias_map(eod_dates: pd.DatetimeIndex) -> dict:
    """External-file date -> EOD date, only where the EOD export is mis-dated
    (parse.EXT_TO_EOD_ALIAS): applied only when the EOD export holds the
    target date and not the source date."""
    from ml.extdata.parse import EXT_TO_EOD_ALIAS
    s = set(eod_dates)
    out = {}
    for src, dst in EXT_TO_EOD_ALIAS.items():
        if pd.Timestamp(dst) in s and pd.Timestamp(src) not in s:
            out[pd.Timestamp(src)] = pd.Timestamp(dst)
    return out


# ========================================================================= #
# base per-ticker series (ml/data.py / build_features definitions)
# ========================================================================= #

def base_features(eod: pd.DataFrame) -> pd.DataFrame:
    df = eod.copy()
    g = df.groupby("ticker", sort=False)
    prev = g["close"].shift(1)
    df["ret_1d"] = df["close"] / prev - 1.0
    df["mom_20"] = df["close"] / g["close"].shift(20) - 1.0
    df["ret_63d"] = df["close"] / g["close"].shift(63) - 1.0
    df["ret_126d"] = df["close"] / g["close"].shift(126) - 1.0

    def roll(col, w, mp, fn):
        r = getattr(g[col].rolling(w, min_periods=mp), fn)()
        return r.reset_index(level=0, drop=True).sort_index()

    df["deliv_pct_sma_20"] = roll("deliv_pct", 20, 20, "mean")
    tr = pd.concat([df["high"] - df["low"], (df["high"] - prev).abs(),
                    (df["low"] - prev).abs()], axis=1).max(axis=1)
    df["_tr"] = tr
    atr = (df.groupby("ticker", sort=False)["_tr"]
           .ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
           .reset_index(level=0, drop=True).sort_index())
    df["atr_pct"] = atr / df["close"]
    df["med_turn_20"] = roll("turnover", 20, 10, "median")
    df["universe"] = (df["close"] >= C.MIN_PRICE) & (df["med_turn_20"] >= C.MIN_MED_TURNOVER)
    sma200 = roll("close", 200, 120, "mean")
    df["dist_200dma"] = df["close"] / sma200 - 1.0
    absret = df["ret_1d"].abs()
    df["_absret"] = absret
    mx = (df.groupby("ticker", sort=False)["_absret"].rolling(20, min_periods=1).max()
          .reset_index(level=0, drop=True).sort_index())
    df["flag_split_20d"] = (mx > SPLIT_MOVE).astype("float32")
    return df.drop(columns=["_tr", "_absret"])


# ========================================================================= #
# F1 market state + F4 flows (one row per EOD date)
# ========================================================================= #

def _sessions_since(flag: np.ndarray, cap: int) -> np.ndarray:
    out = np.empty(len(flag))
    last = None
    for i, f in enumerate(flag):
        if f:
            last = i
        out[i] = cap if last is None else min(i - last, cap)
    return out


def _ext_series_on_eod(ser: pd.Series, eod_dates: pd.DatetimeIndex, amap: dict) -> pd.Series:
    """Map a series indexed by external-file date onto EOD dates (exact date,
    alias-aware)."""
    s = ser.copy()
    s.index = pd.DatetimeIndex([amap.get(t, t) for t in s.index])
    s = s[~s.index.duplicated(keep="last")]
    return s.reindex(eod_dates)


def market_state(base: pd.DataFrame, etf: set, idx: pd.DataFrame, part: pd.DataFrame
                 ) -> tuple[pd.DataFrame, dict]:
    b = base[~base["ticker"].isin(etf)].copy()   # sorted (ticker, date)
    dates = pd.DatetimeIndex(sorted(base["date"].unique()))
    # member at t-1 = in the universe on the previous EOD session (the
    # ticker's previous row must be that session). The mean is a group mean on
    # the long frame (rows in ticker order), so it is bit-for-bit identical
    # whatever later tickers or dates exist in the input.
    prev_session = pd.Series(dates[:-1], index=dates[1:])
    g = b.groupby("ticker", sort=False)
    prev_row_date = g["date"].shift(1)
    u_prev = (g["universe"].shift(1).fillna(False).astype(bool)
              & (prev_row_date == b["date"].map(prev_session)))
    ok = u_prev & b["ret_1d"].notna()
    valid = ok & (b["ret_1d"].abs() <= SPLIT_MOVE)
    r = b.loc[valid].groupby("date")["ret_1d"].mean().reindex(dates)
    n_members = valid.groupby(b["date"]).sum().reindex(dates).fillna(0).astype(int)
    n_excluded = (ok & ~valid).groupby(b["date"]).sum().reindex(dates).fillna(0)
    r[n_members == 0] = np.nan
    lr = np.log1p(r)
    ms = pd.DataFrame(index=dates)
    ms["ew_ret_1d"] = r
    ms["ew_n_members"] = n_members
    ms["mkt_ret_20"] = np.expm1(lr.rolling(20, min_periods=20).sum())
    ms["mkt_ret_63"] = np.expm1(lr.rolling(63, min_periods=63).sum())
    first = lr.first_valid_index()
    lvl = np.exp(lr.fillna(0.0).cumsum())
    lvl[lvl.index < first] = np.nan
    ms["ew_index"] = lvl
    ms["mkt_dd_252"] = lvl / lvl.rolling(252, min_periods=126).max() - 1.0
    ms["mkt_vol_20"] = r.rolling(20, min_periods=20).std()

    ub = b[b["universe"]]
    above = (ub["dist_200dma"] > 0).astype(float).where(ub["dist_200dma"].notna())
    ms["mkt_breadth_200"] = above.groupby(ub["date"]).mean().reindex(dates)
    flag = (ms["mkt_ret_20"] < SELLOFF).fillna(False).to_numpy()
    ms["sessions_since_selloff"] = _sessions_since(flag, SELLOFF_CAP)
    disp = ub[(ub["flag_split_20d"] == 0) & ub["mom_20"].notna()]
    ms["cs_dispersion_20"] = disp.groupby("date")["mom_20"].std().reindex(dates)

    amap = alias_map(dates)
    vix = idx[idx["index_name"] == "India VIX"].set_index("date")["close"].sort_index()
    vix = vix[vix > 0]
    ms["vix_close"] = _ext_series_on_eod(vix, dates, amap)
    ms["vix_chg_20"] = _ext_series_on_eod(np.log(vix / vix.shift(20)), dates, amap)
    pe = idx[idx["index_name"] == "Nifty 50"].set_index("date")["pe"].sort_index()
    ms["nifty50_pe"] = _ext_series_on_eod(pe, dates, amap)

    p = part.copy()
    fii = p[p["client_type"].str.upper() == "FII"].set_index("date").sort_index()
    cli = p[p["client_type"].str.lower() == "client"].set_index("date").sort_index()
    den = fii["fut_idx_long"] + fii["fut_idx_short"]
    fidx = ((fii["fut_idx_long"] - fii["fut_idx_short"]) / den).where(den > 0)
    dens = fii["fut_stk_long"] + fii["fut_stk_short"]
    fstk = ((fii["fut_stk_long"] - fii["fut_stk_short"]) / dens).where(dens > 0)
    cpcr = (cli["opt_idx_put_long"] / cli["opt_idx_call_long"]).where(cli["opt_idx_call_long"] > 0)
    ms["fii_idx_fut_net"] = _ext_series_on_eod(fidx, dates, amap)
    ms["fii_idx_fut_net_chg_5"] = _ext_series_on_eod(fidx - fidx.shift(5), dates, amap)
    ms["fii_stk_fut_net"] = _ext_series_on_eod(fstk, dates, amap)
    ms["client_idx_pcr"] = _ext_series_on_eod(cpcr, dates, amap)
    ms.index.name = "date"
    info = {"ew_members_median": float(n_members[n_members > 0].median()),
            "ew_excluded_big_moves_total": int(n_excluded.sum()),
            "ew_first_return_date": str(first.date()) if first is not None else None,
            "alias_map": {str(k.date()): str(v.date()) for k, v in amap.items()}}
    return ms.reset_index(), info


# ========================================================================= #
# F2 sector
# ========================================================================= #

def _index_ret20(idx: pd.DataFrame) -> pd.DataFrame:
    """20-session return per index on that index's own file calendar."""
    x = idx[["date", "index_name", "close"]].dropna().sort_values(["index_name", "date"])
    x = x[x["close"] > 0]
    x["ret_20"] = x["close"] / x.groupby("index_name")["close"].shift(20) - 1.0
    return x


def sector_features(uni: pd.DataFrame, ind_map: pd.DataFrame, smap: pd.DataFrame,
                    idx: pd.DataFrame, etf: set, amap: dict, policy: dict | None = None
                    ) -> tuple[pd.DataFrame, dict, pd.DataFrame]:
    """uni: universe rows (date, ticker, mom_20, ret_63d, ret_126d,
    deliv_pct_sma_20, atr_pct)."""
    pol = dict(POLICY_DEFAULT, **(policy or {}))
    u = uni.copy()
    imap = dict(zip(ind_map["symbol"].astype(str), ind_map["industry"].astype(str)))
    u["industry"] = u["ticker"].map(imap)
    if pol["unclassified"] == "group":
        u["grp"] = u["industry"].fillna(UNCLASSIFIED)
    else:   # literal brief: no group -> NaN for every F2 feature
        u["grp"] = u["industry"]
    u.loc[u["ticker"].isin(etf), "grp"] = ETF_GROUP
    keys = [u["date"], u["grp"]]
    out = pd.DataFrame({"date": u["date"], "ticker": u["ticker"]}, index=u.index)
    stats = {}
    for src in ["mom_20", "ret_63d", "ret_126d", "deliv_pct_sma_20", "atr_pct"]:
        gb = u[src].groupby(keys)
        cnt = gb.transform("count")
        stats[src] = {"med": gb.transform("median").where(cnt >= GROUP_MIN),
                      "rank": gb.rank(pct=True).where(cnt >= GROUP_MIN)}
    out["ind_mom_20"] = stats["mom_20"]["med"]
    out["ind_ret_63"] = stats["ret_63d"]["med"]
    out["rel_mom_20"] = u["mom_20"] - stats["mom_20"]["med"]
    out["rel_ret_126"] = u["ret_126d"] - stats["ret_126d"]["med"]
    out["rel_deliv"] = u["deliv_pct_sma_20"] - stats["deliv_pct_sma_20"]["med"]
    out["indn_rank_mom_20"] = stats["mom_20"]["rank"]
    out["indn_rank_ret_126"] = stats["ret_126d"]["rank"]
    out["indn_rank_deliv_sma"] = stats["deliv_pct_sma_20"]["rank"]
    out["indn_rank_atr"] = stats["atr_pct"]["rank"]

    # sector index 20-session return (primary index, fallback where absent)
    r20 = _index_ret20(idx)
    r20["date"] = r20["date"].map(lambda t: amap.get(t, t))
    piv = r20.pivot_table(index="date", columns="index_name", values="ret_20",
                          aggfunc="last")
    rows = []
    for _, m in smap.iterrows():
        prim = piv[m["index_name"]] if m["index_name"] in piv.columns else None
        fb = m.get("fallback_index_name") or ""
        fbs = piv[fb] if fb and fb in piv.columns else None
        if prim is None and fbs is None:
            continue
        s = prim if prim is not None else fbs
        if prim is not None and fbs is not None:
            s = prim.where(prim.notna(), fbs)
        rows.append(pd.DataFrame({"date": s.index, "industry": m["industry"],
                                  "secidx_ret_20": s.to_numpy()}))
    sec = pd.concat(rows, ignore_index=True)
    sec = sec.dropna(subset=["secidx_ret_20"])
    merged = u[["date", "industry"]].merge(sec, on=["date", "industry"], how="left")
    vals = merged["secidx_ret_20"].to_numpy()
    mapped = u["industry"].isin(set(smap["industry"])).to_numpy()
    n_default = 0
    if pol["secidx_unmapped"] == "default_index" and SECIDX_DEFAULT_INDEX in piv.columns:
        dflt = piv[SECIDX_DEFAULT_INDEX].reindex(u["date"]).to_numpy()
        vals = np.where(mapped, vals, dflt)
        n_default = int((~mapped).sum())
    out["secidx_ret_20"] = vals
    info = {"group_rows": u["grp"].value_counts(dropna=False).to_dict(),
            "classified_row_share": float(u["industry"].notna().mean()),
            "policy": pol, "secidx_rows_on_default_index": n_default,
            "secidx_default_index": SECIDX_DEFAULT_INDEX}
    return out, info, u[["date", "ticker", "industry", "grp"]]


# ========================================================================= #
# F3 F&O
# ========================================================================= #

def fo_features(keys: pd.DataFrame, fo: pd.DataFrame, med_turn: pd.Series,
                amap: dict) -> tuple[pd.DataFrame, dict]:
    """keys: universe rows (date, ticker) with spot close in 'close' and
    the EOD 20-session median turnover in med_turn (aligned to keys)."""
    f = fo.copy()
    f["date"] = f["date"].map(lambda t: amap.get(t, t))
    cal = pd.DatetimeIndex(sorted(f["date"].unique()))
    fut = f[f["has_future"] == 1]
    oi = fut.pivot(index="date", columns="ticker", values="fut_oi_total").reindex(cal)
    oi = oi.where(oi > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        chg5 = np.log(oi / oi.shift(5))
        chg20 = np.log(oi / oi.shift(20))
    mu = oi.rolling(60, min_periods=40).mean()
    sd = oi.rolling(60, min_periods=40).std()
    z60 = ((oi - mu) / sd).where(sd > 0)
    pcr_long = (fut["opt_put_oi"] / fut["opt_call_oi"]).where(fut["opt_call_oi"] > 0)
    pcr = (fut.assign(pcr=pcr_long).pivot(index="date", columns="ticker", values="pcr")
           .reindex(cal))
    pcr_chg5 = pcr - pcr.shift(5)

    def stack(w: pd.DataFrame, name: str) -> pd.Series:
        s = w.stack()
        s.index.names = ["date", "ticker"]
        return s.rename(name)

    long = pd.concat([stack(chg5, "fut_oi_chg_5"), stack(chg20, "fut_oi_chg_20"),
                      stack(z60, "fut_oi_z_60"), stack(pcr, "pcr_oi"),
                      stack(pcr_chg5, "pcr_chg_5")], axis=1)
    lvl = fut.set_index(["date", "ticker"])[["basis_near", "opt_call_oi", "opt_put_oi"]]
    mi = pd.MultiIndex.from_frame(keys[["date", "ticker"]])
    out = pd.DataFrame(index=keys.index)
    in_fut = mi.isin(lvl.index)
    date_has_file = keys["date"].isin(set(cal)).to_numpy()
    out["fo_member"] = np.where(in_fut, 1.0, np.where(date_has_file, 0.0, np.nan))
    lv = lvl.reindex(mi)
    out["fut_basis_near"] = lv["basis_near"].to_numpy()
    lg = long.reindex(mi)
    for c in ["fut_oi_chg_5", "fut_oi_chg_20", "fut_oi_z_60", "pcr_oi", "pcr_chg_5"]:
        out[c] = lg[c].to_numpy()
    opt_oi = lv[["opt_call_oi", "opt_put_oi"]].sum(axis=1, min_count=1).to_numpy()
    notional = opt_oi * keys["close"].to_numpy()  # NaN when the stock has no options
    mt = med_turn.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        out["opt_oi_to_turnover"] = np.where(mt > 0, notional / mt, np.nan)
    for c in F3[1:]:
        out.loc[out["fo_member"] != 1, c] = np.nan
    info = {"fo_calendar_sessions": int(len(cal)),
            "fo_member_rows": int(np.nansum(out["fo_member"].to_numpy() == 1)),
            "fo_member_tickers_not_in_universe_rows": None}
    return out[F3], info


# ========================================================================= #
# build
# ========================================================================= #

def load_staging(max_date: pd.Timestamp | None = None):
    fo = pd.read_parquet(C.EXT / "fo_daily_stock.parquet")
    idx = pd.read_parquet(C.EXT / "index_daily.parquet")
    part = pd.read_parquet(C.EXT / "fo_participant_oi.parquet")
    if max_date is not None:
        fo, idx, part = (x[x["date"] <= max_date] for x in (fo, idx, part))
    return fo, idx, part


def placebo_industry_map(seed: int = C.SEED) -> pd.DataFrame:
    """Industry labels permuted among the classified symbols (same coverage,
    same group sizes): the control that separates industry information from
    the snapshot-coverage look-ahead."""
    m = pd.read_csv(C.EXT / "industry_map.csv")
    rng = np.random.default_rng(seed)
    m = m.copy()
    m["industry"] = rng.permutation(m["industry"].to_numpy())
    return m


def build(eod_path: Path = C.EOD_EXPORT, max_date: pd.Timestamp | None = None,
          staging: tuple | None = None, write: bool = True,
          start: str = C.FEATURE_START, policy: dict | None = None,
          industry_map: pd.DataFrame | None = None) -> dict:
    t0 = time.perf_counter()
    eod = load_eod(eod_path, max_date)
    base = base_features(eod)
    fo, idx, part = staging if staging is not None else load_staging(max_date)
    if max_date is not None:
        fo, idx, part = (x[x["date"] <= max_date] for x in (fo, idx, part))
    etf, etf_src = load_etf_set(pd.Index(base["ticker"].unique()))
    ind_map = industry_map if industry_map is not None else pd.read_csv(C.EXT / "industry_map.csv")
    smap = pd.read_csv(C.EXT / "sector_index_map.csv").fillna("")

    ms, ms_info = market_state(base, etf, idx, part)
    dates = pd.DatetimeIndex(sorted(base["date"].unique()))
    amap = alias_map(dates)

    uni = base[base["universe"] & (base["date"] >= pd.Timestamp(start))].copy()
    uni = uni.sort_values(["date", "ticker"]).reset_index(drop=True)
    # aggregates exclude ETFs; ETF rows keep their own group
    f2, f2_info, groups = sector_features(uni, ind_map, smap, idx, etf, amap, policy)
    f3, f3_info = fo_features(uni[["date", "ticker", "close"]], fo, uni["med_turn_20"], amap)

    extra = pd.concat([uni[["date", "ticker"]], f2[F2], f3[F3]], axis=1)
    ms_out = ms[ms["date"] >= pd.Timestamp(start)][["date"] + F1 + F4].reset_index(drop=True)
    res = {"extra": extra, "market_state": ms_out, "market_state_full": ms,
           "base_universe": uni, "groups": groups,
           "info": {"etf_source": etf_src, "n_etf_tickers": len(etf),
                    "market_state": ms_info, "f2": f2_info, "f3": f3_info,
                    "rows": int(len(extra)), "tickers": int(extra["ticker"].nunique()),
                    "date_min": str(extra["date"].min().date()),
                    "date_max": str(extra["date"].max().date()),
                    "seconds": round(time.perf_counter() - t0, 1)}}
    if write:
        extra.to_parquet(C.EXT / "extra_features.parquet", index=False)
        ms_out.to_parquet(C.EXT / "market_state.parquet", index=False)
        write_manifest(res["info"])
    return res


DEFINITIONS = {
    "mkt_ret_20": "compounded 20-session return of the equal-weight universe index; the EW daily return at t is the mean 1-day return at t over names in the universe at t-1 (ETFs excluded; single-day |r| > 0.22 excluded as corporate-action artefacts)",
    "mkt_ret_63": "same, 63 sessions",
    "mkt_dd_252": "EW index level / its trailing 252-session max (incl. t; min 126 obs) - 1",
    "mkt_vol_20": "sample sd of the EW daily return over 20 sessions",
    "mkt_breadth_200": "share of universe names (ex-ETF) at t with close above their 200-session SMA (SMA needs >= 120 obs; names without it excluded)",
    "sessions_since_selloff": "EOD sessions since the last date with mkt_ret_20 < -0.08 (0 on such a date); 252 if none within reach (capped at 252)",
    "cs_dispersion_20": "cross-sectional sd of mom_20 over universe names (ex-ETF) with flag_split_20d == 0",
    "vix_close": "India VIX close (ind_close_all) on date t",
    "vix_chg_20": "log(VIX_t / VIX 20 index-file sessions earlier)",
    "nifty50_pe": "Nifty 50 P/E (ind_close_all) on date t",
    "ind_mom_20": "median mom_20 over universe names in the stock's industry group at t; NaN if < 5 non-NaN names",
    "ind_ret_63": "median ret_63d over the industry group at t; NaN if < 5",
    "rel_mom_20": "mom_20 - ind_mom_20",
    "rel_ret_126": "ret_126d - industry-group median ret_126d (>= 5 names)",
    "rel_deliv": "deliv_pct_sma_20 - industry-group median deliv_pct_sma_20 (>= 5 names)",
    "indn_rank_mom_20": "percentile rank (pct=True, average ties) of mom_20 within the industry group at t; NaN if < 5",
    "indn_rank_ret_126": "same for ret_126d",
    "indn_rank_deliv_sma": "same for deliv_pct_sma_20",
    "indn_rank_atr": "same for atr_pct",
    "secidx_ret_20": "20-session return (index's own file calendar) of the sector index mapped to the stock's industry (sector_index_map.csv; Healthcare falls back to Nifty Pharma where the Healthcare index return is missing); names in unmapped industries, Unclassified names and ETFs take the Nifty 500 20-session return (leak-safe deviation from the brief's NaN: a NaN here would mark membership of today's index lists)",
    "fo_member": "1 if the stock has a stock future in that day's F&O bhavcopy, 0 if the file exists and it has none, NaN if the day's file is missing",
    "fut_basis_near": "(near-month futures settle / spot close - 1) x 365 / calendar days to expiry; NaN if days to expiry < 2",
    "fut_oi_chg_5": "log(fut_oi_total_t / fut_oi_total 5 F&O sessions earlier); NaN unless a member at both dates",
    "fut_oi_chg_20": "same, 20 sessions",
    "fut_oi_z_60": "(fut_oi_total - rolling 60-session mean) / rolling 60-session sd, F&O calendar, >= 40 member sessions in the window",
    "pcr_oi": "stock-option put OI / call OI (all expiries)",
    "pcr_chg_5": "pcr_oi_t - pcr_oi 5 F&O sessions earlier",
    "opt_oi_to_turnover": "(call OI + put OI, shares) x spot close / 20-session median EOD turnover (rupees; min 10 obs): option open interest in days of cash-market traded value",
    "fii_idx_fut_net": "(FII Future Index Long - Short) / (Long + Short), participant-wise OI (contracts)",
    "fii_idx_fut_net_chg_5": "fii_idx_fut_net_t - fii_idx_fut_net 5 participant-file sessions earlier",
    "fii_stk_fut_net": "(FII Future Stock Long - Short) / (Long + Short)",
    "client_idx_pcr": "Client Option Index Put Long / Client Option Index Call Long",
}


def write_manifest(info: dict) -> None:
    man = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "builder": "ml/extdata/features.py (P3 external-data stream)",
        "families": FAMILIES,
        "n_features": {k: len(v) for k, v in FAMILIES.items()},
        "files": {"extra_features": "ml/data_ext/extra_features.parquet (key date, ticker; F2 + F3)",
                  "market_state": "ml/data_ext/market_state.parquet (key date; F1 + F4)"},
        "definitions": DEFINITIONS,
        "base_series": "mom_20, ret_63d, ret_126d, deliv_pct_sma_20, atr_pct recomputed from the EOD export with the ml/data.py / build_features definitions (unadjusted prices)",
        "universe": "close >= 10 and trailing 20-session median turnover >= 1e7 (min 10 obs), EOD-export EQ/BE rows, from 2022-10-03",
        "pit_rule": "every value at t uses only bars and archive files dated <= t; same-day end-of-day prints allowed (labels enter at the next open)",
        "known_limitations": [
            "industry labels come from 2026-10-19 constituent lists (not point in time); unlisted names form an 'Unclassified' group and unmapped names take the Nifty 500 return in secidx_ret_20, so no NaN pattern marks today's index members; the residual exposure is measured in ml/results/improve/extdata/extdata.json (industry_survivorship_diagnostic, partition_identifiability)",
            "prices, and futures OI in shares, are not adjusted for splits/bonuses (as in v1); rolling OI changes jump on such ex-dates",
            "the six special sessions P1 adds have no rows (not in the v1 export)",
        ],
        "info": info,
    }
    (C.EXT / "extra_features_manifest.json").write_text(json.dumps(man, indent=1, default=str))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eod", default=str(C.EOD_EXPORT))
    ap.add_argument("--max-date", default=None)
    a = ap.parse_args()
    md = pd.Timestamp(a.max_date) if a.max_date else None
    res = build(Path(a.eod), md)
    print(json.dumps(res["info"], indent=1, default=str))


if __name__ == "__main__":
    main()
