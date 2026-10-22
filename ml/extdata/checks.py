#!/usr/bin/env python3
"""Checks for the P3 external-data stream.

* coverage per source and year (files, 404s, content-date exclusions,
  special sessions, alias days), F&O membership per year, industry-map
  coverage of the universe per year;
* point in time:
  (a) 100 random (date, ticker) cells of F2/F3 recomputed by an independent
      code path (csv-module readers, numpy loops) from the raw files and EOD
      bars restricted to dates <= t;
  (b) for every session t of one month, all inputs dated after t removed
      (files by file-name date, EOD bars by date) and the pipeline re-run;
      the rows at t must equal the full build; for the last session the
      removal is literal (a directory holding only the files <= t, parsed
      without the cache);
  (c) shift test: inputs truncated at T0, every row dated <= T0 must equal
      the full build (no value changes when future bars are appended);
* unit continuity at the 2024-07 F&O format switch;
* base-series cross-check against the v1 dataset;
* NaN share per feature; descriptive monthly IC (REPORTING ONLY: reads
  y_excess_20d / y_clean_20d of the v1 dataset after the features are
  built; never used to choose, drop or transform anything).
"""
from __future__ import annotations

import csv
import io
import json
import os
import shutil
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.extdata import common as C  # noqa: E402
from ml.extdata import features as F  # noqa: E402
from ml.extdata import parse as P  # noqa: E402

RTOL = 1e-9
RTOL_Z = 1e-6   # rolling sd: pandas' online algorithm vs numpy two-pass

# inputs of the build being checked (run_all.py sets them; default = v1)
SOURCES = {"eod": C.EOD_EXPORT, "prices": None, "dataset": C.V1_DATASET, "tag": "v1"}


def configure(eod=None, prices=None, dataset=None, tag=None) -> None:
    if eod is not None:
        SOURCES["eod"] = Path(eod)
    SOURCES["prices"] = Path(prices) if prices else None
    if dataset is not None:
        SOURCES["dataset"] = Path(dataset)
    if tag is not None:
        SOURCES["tag"] = tag


def _load_prices(max_date=None) -> pd.DataFrame:
    return F.load_eod(SOURCES["eod"], max_date, SOURCES["prices"])


def _jsonable(x):
    if isinstance(x, (np.floating,)):
        return None if not np.isfinite(x) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, float) and not np.isfinite(x):
        return None
    return x


def _close(a: float, b: float, rtol: float = RTOL, atol: float = 1e-12) -> bool:
    if (a is None or (isinstance(a, float) and np.isnan(a))) and \
            (b is None or (isinstance(b, float) and np.isnan(b))):
        return True
    if a is None or b is None or np.isnan(a) or np.isnan(b):
        return False
    return abs(a - b) <= atol + rtol * max(abs(a), abs(b))


# ========================================================================= #
# coverage
# ========================================================================= #

def coverage(fo: pd.DataFrame, idx: pd.DataFrame, part: pd.DataFrame,
             res: dict) -> dict:
    from ml.extdata.download import load_status
    eod_s = set(C.eod_sessions(SOURCES["eod"]))
    sessions = sorted(eod_s | set(C.SPECIAL_SESSIONS))
    specials = set(C.SPECIAL_SESSIONS)
    meta = json.loads((C.OUT / "parse_meta.json").read_text())
    out: dict = {"expected_sessions": len(sessions), "eod_sessions": len(eod_s),
                 "special_sessions": [d.isoformat() for d in sorted(specials)],
                 "alias_ext_to_eod": {k.isoformat(): v.isoformat()
                                      for k, v in P.EXT_TO_EOD_ALIAS.items()}}
    per_source = {}
    for kind, frame in (("fo", fo), ("indices", idx), ("participant", part)):
        have = set(pd.to_datetime(frame["date"]).dt.date.unique())
        st = load_status(kind)
        s404 = sorted({r["date"] for r in st.values() if r.get("status") == "404" and r["date"]})
        excluded = [m for m in meta[kind] if not m.get("date_ok")]
        amap = {s: d for s, d in P.EXT_TO_EOD_ALIAS.items() if s in have and d in eod_s}
        covered_eod = {amap.get(d, d) for d in have}
        missing_eod = sorted(d for d in eod_s if d not in covered_eod)
        by_year = {}
        for y in sorted({d.year for d in sessions}):
            exp_y = [d for d in sessions if d.year == y]
            by_year[y] = {"expected": len(exp_y),
                          "files_ok": sum(1 for d in exp_y if d in have),
                          "eod_sessions_without_file": sum(1 for d in eod_s
                                                           if d.year == y and d not in covered_eod)}
        per_source[kind] = {
            "files_ok_in_window": int(sum(1 for d in have if C.MAIN_START <= d <= C.MAIN_END)),
            "files_ok_total": int(len(have)),
            "http_404_dates": s404,
            "excluded_content_date_mismatch": [{"file": m["file"], "content_dates":
                                                m.get("content_dates"), "error": m.get("error")}
                                               for m in excluded],
            "eod_sessions_without_file": [d.isoformat() for d in missing_eod],
            "special_sessions": {d.isoformat(): ("ok" if d in have else
                                                 ("404" if d.isoformat() in s404 else "absent"))
                                 for d in sorted(specials)},
            "alias_days_used": {k.isoformat(): v.isoformat() for k, v in amap.items()},
            "by_year": by_year,
        }
    out["per_source"] = per_source

    # F&O membership per year
    fut = fo[fo["has_future"] == 1]
    per_day = fut.groupby("date")["ticker"].nunique()
    yr = per_day.groupby(per_day.index.year)
    out["fo_members_per_year"] = {
        int(y): {"mean_daily": round(float(s.mean()), 1), "min_daily": int(s.min()),
                 "max_daily": int(s.max()),
                 "distinct_tickers": int(fut[fut["date"].dt.year == y]["ticker"].nunique())}
        for y, s in yr}
    ex = res["extra"]
    fm = ex.groupby(ex["date"].dt.year)["fo_member"].agg(
        lambda s: float((s == 1).mean()))
    out["universe_rows_fo_member_share_by_year"] = {int(k): round(v, 4) for k, v in fm.items()}

    # industry-map coverage of the universe
    g = res["groups"]
    g = g.assign(year=g["date"].dt.year, classified=g["industry"].notna(),
                 etf=g["grp"] == F.ETF_GROUP)
    cov = {}
    for y, s in g.groupby("year"):
        ne = s[~s["etf"]]
        cov[int(y)] = {"rows": int(len(s)),
                       "share_rows_known_industry": round(float(s["classified"].mean()), 4),
                       "share_rows_known_industry_ex_etf": round(float(ne["classified"].mean()), 4),
                       "share_rows_etf_group": round(float(s["etf"].mean()), 4),
                       "share_tickers_known_industry": round(
                           float(s.groupby("ticker")["classified"].first().mean()), 4)}
    out["industry_coverage_by_year"] = cov
    out["industry_coverage_overall"] = round(float(g["classified"].mean()), 4)
    return out


# ========================================================================= #
# integrity of the F&O units / symbols / participant identities
# ========================================================================= #

def unit_continuity() -> dict:
    """Legacy 2024-07-05 OPEN_INT vs UDiFF 2024-07-08 (OpnIntrst - ChngInOpnIntrst)
    per futures contract: equal iff both are in the same units."""
    a = C.RAW_FO / "fo05JUL2024bhav.csv.zip"
    b = C.RAW_FO / "BhavCopy_NSE_FO_0_0_0_20240708_F_0000.csv.zip"
    if not (a.exists() and b.exists()):
        return {"available": False}
    la = P.fo_contract_oi(a)
    ub = P.fo_contract_oi(b)
    m = la.merge(ub, on=["ticker", "expiry"], suffixes=("_0705", "_0708"))
    implied_prev = m["oi_0708"] - m["oi_chg_0708"]
    eq = (implied_prev == m["oi_0705"])
    rel = (implied_prev - m["oi_0705"]).abs() / m["oi_0705"].where(m["oi_0705"] > 0)
    # UDiFF volume units: TtlTrfVal / (TtlTradgVol x lot x settle) ~ 1 for futures
    raw = P._read_zip_csv(b)
    stf = raw[(raw["FinInstrmTp"] == "STF") & (raw["TtlTradgVol"] > 0)]
    ratio = stf["TtlTrfVal"] / (stf["TtlTradgVol"] * stf["NewBrdLotQty"] * stf["ClsPric"])
    oi_lots = (stf["OpnIntrst"] / stf["NewBrdLotQty"])
    return {"available": True, "contracts_matched": int(len(m)),
            "oi_identity_exact": int(eq.sum()),
            "oi_identity_share": round(float(eq.mean()), 4),
            "max_rel_deviation": _jsonable(float(rel.max())) if len(rel) else None,
            "udiff_turnover_over_contracts_x_lot_x_close_median": round(float(ratio.median()), 4),
            "udiff_oi_divisible_by_lot_share": round(float((oi_lots % 1 == 0).mean()), 4),
            "reading": ("OI is in shares in both formats (identity holds across the switch); "
                        "UDiFF TtlTradgVol is in contracts (turnover = contracts x lot x price)")}


def symbol_match(fo: pd.DataFrame) -> dict:
    eod = pd.read_parquet(SOURCES["eod"], columns=["date", "ticker"])
    eod["date"] = pd.to_datetime(eod["date"])
    eod_dates = set(eod["date"].dt.date.unique())
    amap = {pd.Timestamp(s): pd.Timestamp(d) for s, d in P.EXT_TO_EOD_ALIAS.items()
            if d in eod_dates and s not in eod_dates}
    f = fo[fo["has_future"] == 1][["date", "ticker"]].copy()
    f["date"] = f["date"].map(lambda t: amap.get(t, t))
    f = f[f["date"].dt.date.isin(eod_dates)]
    k = set(zip(eod["date"], eod["ticker"]))
    hit = np.array([(d, t) in k for d, t in zip(f["date"], f["ticker"])])
    miss = f[~hit]
    return {"fo_stock_rows_on_eod_dates": int(len(f)), "matched_share": round(float(hit.mean()), 5),
            "unmatched_rows": int((~hit).sum()),
            "unmatched_tickers": miss["ticker"].value_counts().head(20).to_dict()}


def participant_identity(part: pd.DataFrame) -> dict:
    cols = list(P.PART_NUMERIC.values())
    tot = part[part["client_type"].str.upper() == "TOTAL"].set_index("date")[cols]
    four = (part[part["client_type"].str.upper() != "TOTAL"].groupby("date")[cols].sum())
    four = four.reindex(tot.index)
    dev = (four - tot).abs()
    sum_ok = (dev <= 1.0).all(axis=1)   # NSE rounds index-option sums by up to 1 contract
    ls_ok = ((tot["fut_idx_long"] == tot["fut_idx_short"])
             & (tot["fut_stk_long"] == tot["fut_stk_short"]))
    types = part.groupby("date")["client_type"].apply(lambda s: tuple(sorted(s)))
    return {"files": int(len(tot)),
            "four_types_sum_to_total_within_1_contract_share": round(float(sum_ok.mean()), 4),
            "four_types_sum_exact_share": round(float((dev < 0.5).all(axis=1).mean()), 4),
            "max_abs_deviation_contracts": float(dev.max().max()),
            "total_long_equals_short_futures_share": round(float(ls_ok.mean()), 4),
            "client_type_sets": {", ".join(k): int(v) for k, v in types.value_counts().items()}}


def basis_sanity(fo: pd.DataFrame) -> dict:
    b = fo[(fo["has_future"] == 1) & fo["basis_near"].notna()]
    out = {}
    for y, s in b.groupby(b["date"].dt.year):
        q = s["basis_near"].quantile([0.01, 0.05, 0.5, 0.95, 0.99])
        out[int(y)] = {f"p{int(k * 100)}": round(float(v), 4) for k, v in q.items()}
        out[int(y)]["n"] = int(len(s))
    spot_missing = fo[(fo["has_future"] == 1) & fo["spot_close"].isna()]
    return {"annualised_basis_quantiles_by_year": out,
            "fut_rows_without_spot": int(len(spot_missing)),
            "fut_rows_without_spot_dates": spot_missing["date"].dt.date.astype(str)
            .value_counts().head(10).to_dict()}


# ========================================================================= #
# base cross-check vs v1
# ========================================================================= #

def base_crosscheck(res: dict) -> dict:
    uni = res["base_universe"][["date", "ticker"] + F.BASE]
    v1 = pd.read_parquet(SOURCES["dataset"], columns=["date", "ticker"] + F.BASE)
    v1["date"] = pd.to_datetime(v1["date"]).astype("datetime64[ns]")
    k1 = pd.MultiIndex.from_frame(v1[["date", "ticker"]])
    k2 = pd.MultiIndex.from_frame(uni[["date", "ticker"]])
    m = v1.merge(uni, on=["date", "ticker"], suffixes=("_v1", "_ext"))
    out = {"dataset": str(SOURCES["dataset"]), "v1_rows": int(len(v1)), "ext_rows": int(len(uni)),
           "common_rows": int(len(m)),
           "rows_only_in_v1": int((~k1.isin(k2)).sum()),
           "rows_only_in_ext": int((~k2.isin(k1)).sum()), "features": {}}
    for f in F.BASE:
        a, b = m[f + "_v1"].to_numpy(), m[f + "_ext"].to_numpy()
        both = np.isfinite(a) & np.isfinite(b)
        d = np.abs(a[both] - b[both])
        out["features"][f] = {"n_both_finite": int(both.sum()),
                              "max_abs_diff": float(d.max()) if d.size else None,
                              "n_abs_diff_gt_1e-9": int((d > 1e-9).sum()),
                              "nan_pattern_mismatch": int((np.isfinite(a) != np.isfinite(b)).sum())}
    return out


# ========================================================================= #
# (a) independent recomputation of random cells
# ========================================================================= #

class EodArrays:
    """Per-ticker numpy arrays of the EOD export; every query slices the
    prefix dated <= t."""

    def __init__(self, eod: pd.DataFrame):
        self.d = {}
        for tk, g in eod.groupby("ticker", sort=False):
            self.d[tk] = {c: g[c].to_numpy() for c in
                          ("date", "close", "close_raw", "high", "low", "turnover", "deliv_pct")}
        self.by_date = eod.groupby("date")["ticker"].apply(list).to_dict()

    def values_at(self, tk: str, t: pd.Timestamp) -> dict | None:
        a = self.d[tk]
        pos = np.searchsorted(a["date"], np.datetime64(t), side="right") - 1
        if pos < 0 or a["date"][pos] != np.datetime64(t):
            return None
        n = pos + 1
        c, h, lo = a["close"][:n], a["high"][:n], a["low"][:n]
        to, dv = a["turnover"][:n], a["deliv_pct"][:n]
        win = to[max(0, n - 20):n]
        win = win[np.isfinite(win)]
        med = float(np.median(win)) if win.size >= 10 else np.nan
        craw = float(a["close_raw"][pos])
        out = {"close": float(c[-1]), "close_raw": craw, "med_turn_20": med,
               "universe": bool(craw >= C.MIN_PRICE and np.isfinite(med) and med >= C.MIN_MED_TURNOVER)}
        out["mom_20"] = float(c[-1] / c[-21] - 1) if n >= 21 else np.nan
        out["ret_63d"] = float(c[-1] / c[-64] - 1) if n >= 64 else np.nan
        out["ret_126d"] = float(c[-1] / c[-127] - 1) if n >= 127 else np.nan
        dw = dv[n - 20:n] if n >= 20 else np.array([np.nan])
        out["deliv_pct_sma_20"] = float(np.mean(dw)) if (n >= 20 and np.isfinite(dw).all()) else np.nan
        if n >= 14:
            alpha = 1.0 / 14.0
            y = float(h[0] - lo[0])
            for k in range(1, n):
                tr = max(h[k] - lo[k], abs(h[k] - c[k - 1]), abs(lo[k] - c[k - 1]))
                y = (1.0 - alpha) * y + alpha * tr
            out["atr_pct"] = y / float(c[-1])
        else:
            out["atr_pct"] = np.nan
        return out


def _rank_pct(vals: np.ndarray, x: float) -> float:
    n = vals.size
    less = np.sum(vals < x)
    eq = np.sum(vals == x)
    return float((less + (eq + 1) / 2.0) / n)


def _read_index_closes(path: Path, names: list[str]) -> tuple[bool, dict]:
    d = P.ddmmyyyy_date(P.IDX_RE, path.name)
    txt = path.read_bytes().decode("latin-1")
    rd = csv.reader(io.StringIO(txt))
    hdr = [h.strip().lstrip("﻿") for h in next(rd)]
    i_name, i_date, i_close = (hdr.index("Index Name"), hdr.index("Index Date"),
                               hdr.index("Closing Index Value"))
    ok_dates, closes = set(), {}
    for r in rd:
        if len(r) <= i_close:
            continue
        ds = r[i_date].strip()
        okd = None
        for fmt in ("%d-%m-%Y", "%m-%d-%Y", "%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                if datetime.strptime(ds, fmt).date() == d:
                    okd = True
                    break
            except ValueError:
                continue
        ok_dates.add(bool(okd))
        nm = r[i_name].strip()
        if nm in names and nm not in closes:
            try:
                v = float(r[i_close].strip())
                if v > 0:
                    closes[nm] = v
            except ValueError:
                pass
    return ok_dates == {True}, closes


def _indep_secidx(t: pd.Timestamp, industry: str | None, smap: pd.DataFrame,
                  idx_files: list[Path], idx_cache: dict, eod_dates: set,
                  default_index: str | None) -> float:
    """Sector-index 20-session return at EOD date t from index files dated <= t;
    NaN unless the newest valid file containing the index is dated t."""
    row = smap[smap["industry"] == industry] if industry is not None else smap.iloc[0:0]
    if row.empty:
        prim, fb = default_index, None
    else:
        prim = row.iloc[0]["index_name"]
        fb = row.iloc[0]["fallback_index_name"] or None
    if prim is None:
        return np.nan
    amap = {pd.Timestamp(s): pd.Timestamp(d) for s, d in P.EXT_TO_EOD_ALIAS.items()
            if d in eod_dates and s not in eod_dates}
    names = (list(smap["index_name"]) + [x for x in smap["fallback_index_name"] if x]
             + ([default_index] if default_index else []))

    def ret20(name):
        closes, newest = [], None
        for p in reversed(idx_files):
            if p not in idx_cache:
                idx_cache[p] = _read_index_closes(p, names)
            ok, cl = idx_cache[p]
            if ok and name in cl:
                if newest is None:
                    fd = pd.Timestamp(P.ddmmyyyy_date(P.IDX_RE, p.name))
                    newest = amap.get(fd, fd)
                closes.append(cl[name])
            if len(closes) == 21:
                break
        if newest != t or len(closes) < 21:
            return np.nan
        return closes[0] / closes[20] - 1.0

    v = ret20(prim)
    if np.isnan(v) and fb:
        v = ret20(fb)
    if np.isnan(v) and default_index and prim != default_index:
        v = ret20(default_index)   # mapped index without a value that date
    return v


def _read_fo_symbols(path: Path, symbols: set) -> tuple[date | None, dict]:
    fd, fmt = P.fo_file_date(path.name)
    with zipfile.ZipFile(path) as zf:
        nm = [n for n in zf.namelist() if n.lower().endswith(".csv")][0]
        txt = zf.read(nm).decode("latin-1")
    rd = csv.DictReader(io.StringIO(txt))
    out = {s: {"fut": [], "ce": 0.0, "pe": 0.0, "n_ce": 0, "n_pe": 0, "n_opt": 0}
           for s in symbols}
    stamps = set()
    for r in rd:
        r = {(k or "").strip(): (v or "").strip() for k, v in r.items()}
        if fmt == "legacy":
            stamps.add(r.get("TIMESTAMP", ""))
            sym, inst, ot = r["SYMBOL"], r["INSTRUMENT"], r["OPTION_TYP"]
            if sym not in symbols:
                continue
            exp = datetime.strptime(r["EXPIRY_DT"], "%d-%b-%Y").date()
            settle, oi = float(r["SETTLE_PR"]), float(r["OPEN_INT"])
            is_fut, is_opt = inst == "FUTSTK", inst == "OPTSTK"
        else:
            stamps.add(r.get("TradDt", ""))
            sym, tp, ot = r["TckrSymb"], r["FinInstrmTp"], r["OptnTp"]
            if sym not in symbols:
                continue
            xs = r.get("FininstrmActlXpryDt") or r["XpryDt"]
            exp = datetime.strptime(xs, "%Y-%m-%d").date()
            settle, oi = float(r["SttlmPric"] or "nan"), float(r["OpnIntrst"] or "nan")
            is_fut, is_opt = tp == "STF", tp == "STO"
        if is_fut and exp >= fd:
            out[sym]["fut"].append((exp, settle, oi))
        elif is_opt and ot in ("CE", "PE"):
            out[sym]["ce" if ot == "CE" else "pe"] += oi
            out[sym]["n_ce" if ot == "CE" else "n_pe"] += 1
            out[sym]["n_opt"] += 1
    if fmt == "legacy":
        cds = {datetime.strptime(s, "%d-%b-%Y").date() for s in stamps if s}
    else:
        cds = {datetime.strptime(s, "%Y-%m-%d").date() for s in stamps if s}
    return (fd if cds == {fd} else None), out


def _indep_f3(t: pd.Timestamp, tickers: list[str], fo_files: list[Path], eodA: EodArrays,
              fo_cache: dict, eod_dates: set) -> dict:
    """F3 at EOD date t from the last 61 valid F&O files dated <= t."""
    amap = {pd.Timestamp(s): pd.Timestamp(d) for s, d in P.EXT_TO_EOD_ALIAS.items()
            if d in eod_dates and s not in eod_dates}
    syms = set(tickers)
    seq = []   # newest first: (eod_date, file_date, data)
    for p in reversed(fo_files):
        key = (p.name, tuple(sorted(syms)))
        if key not in fo_cache:
            fo_cache[key] = _read_fo_symbols(p, syms)
        fd, data = fo_cache[key]
        if fd is None:
            continue
        seq.append((amap.get(pd.Timestamp(fd), pd.Timestamp(fd)), fd, data))
        if len(seq) == 61:
            break
    out = {}
    have_t = bool(seq) and seq[0][0] == t
    for tk in tickers:
        r = {c: np.nan for c in F.F3}
        if not have_t:
            out[tk] = r
            continue

        def oi_at(k):
            if k >= len(seq):
                return np.nan
            fut = seq[k][2][tk]["fut"]
            if not fut:
                return np.nan
            v = sum(x[2] for x in fut)
            return v if v > 0 else np.nan

        def pcr_at(k):
            if k >= len(seq):
                return np.nan
            dd = seq[k][2][tk]
            if not dd["fut"] or dd["n_ce"] == 0 or dd["n_pe"] == 0 or dd["ce"] <= 0:
                return np.nan
            return dd["pe"] / dd["ce"]

        dat = seq[0][2][tk]
        if not dat["fut"]:
            r["fo_member"] = 0.0
            out[tk] = r
            continue
        r["fo_member"] = 1.0
        ev = eodA.values_at(tk, t)
        spot = ev["close_raw"] if ev else np.nan
        near = sorted(dat["fut"])[0]
        dte = (near[0] - seq[0][1]).days
        if dte >= 2 and near[1] > 0 and spot > 0:
            r["fut_basis_near"] = (near[1] / spot - 1.0) * 365.0 / dte
        o0 = oi_at(0)
        r["fut_oi_chg_5"] = np.log(o0 / oi_at(5)) if np.isfinite(o0 / oi_at(5)) else np.nan
        r["fut_oi_chg_20"] = np.log(o0 / oi_at(20)) if np.isfinite(o0 / oi_at(20)) else np.nan
        w = np.array([oi_at(k) for k in range(min(60, len(seq)))])
        w = w[np.isfinite(w)]
        if w.size >= 40 and np.isfinite(o0):
            sd = float(np.std(w, ddof=1))
            r["fut_oi_z_60"] = (o0 - float(np.mean(w))) / sd if sd > 0 else np.nan
        r["pcr_oi"] = pcr_at(0)
        r["pcr_chg_5"] = pcr_at(0) - pcr_at(5)
        if dat["n_opt"] > 0 and ev and np.isfinite(ev["med_turn_20"]) and ev["med_turn_20"] > 0:
            opt_oi = (dat["ce"] if dat["n_ce"] else 0.0) + (dat["pe"] if dat["n_pe"] else 0.0)
            r["opt_oi_to_turnover"] = opt_oi * spot / ev["med_turn_20"]
        out[tk] = r
    return out


def pit_recompute_cells(res: dict, n_dates: int = 25, per_date: int = 2) -> dict:
    t0 = time.perf_counter()
    rng = np.random.default_rng(C.SEED)
    ex = res["extra"]
    eod = _load_prices()
    eodA = EodArrays(eod)
    eod_dates = set(eod["date"].dt.date.unique())
    etf, _ = F.load_etf_set(pd.Index(eod["ticker"].unique()))
    imap = dict(pd.read_csv(C.EXT / "industry_map.csv")[["symbol", "industry"]].values)
    smap = pd.read_csv(C.EXT / "sector_index_map.csv").fillna("")
    dates = np.sort(ex["date"].unique())
    pick = np.sort(rng.choice(dates, size=n_dates, replace=False))
    fo_all = P.list_raw("fo")
    idx_all = P.list_raw("indices")
    fo_dates = {p: P.fo_file_date(p.name)[0] for p in fo_all}
    idx_dates = {p: P.ddmmyyyy_date(P.IDX_RE, p.name) for p in idx_all}
    idx_cache, fo_cache = {}, {}
    cells, n_vals, n_match, worst = [], 0, 0, 0.0
    for t in pick:
        t = pd.Timestamp(t)
        rows_t = ex[ex["date"] == t]
        f2_pool = rows_t[rows_t["ind_mom_20"].notna()]["ticker"].to_numpy()
        f3_pool = rows_t[rows_t["fo_member"] == 1]["ticker"].to_numpy()
        f2_t = list(rng.choice(f2_pool, size=min(per_date, len(f2_pool)), replace=False))
        f3_t = list(rng.choice(f3_pool, size=min(per_date, len(f3_pool)), replace=False))
        # ---- F2: cross-section at t from bars <= t ---------------------------
        vals = {}
        for tk in eodA.by_date.get(t, []):
            v = eodA.values_at(tk, t)
            if v and v["universe"]:
                vals[tk] = v
        grp = {tk: (F.ETF_GROUP if tk in etf else imap.get(tk, F.UNCLASSIFIED)) for tk in vals}
        idx_le = [p for p in idx_all if idx_dates[p] <= t.date()]
        for tk in f2_t:
            g = grp[tk]
            mem = [k for k in vals if grp[k] == g]
            rec = {}
            for src, med_name, rel_name, rank_name in [
                    ("mom_20", "ind_mom_20", "rel_mom_20", "indn_rank_mom_20"),
                    ("ret_63d", "ind_ret_63", None, None),
                    ("ret_126d", None, "rel_ret_126", "indn_rank_ret_126"),
                    ("deliv_pct_sma_20", None, "rel_deliv", "indn_rank_deliv_sma"),
                    ("atr_pct", None, None, "indn_rank_atr")]:
                arr = np.array([vals[k][src] for k in mem], dtype=float)
                arr = arr[np.isfinite(arr)]
                x = vals[tk][src]
                ok = arr.size >= F.GROUP_MIN
                med = float(np.median(arr)) if ok else np.nan
                if med_name:
                    rec[med_name] = med
                if rel_name:
                    rec[rel_name] = x - med if (ok and np.isfinite(x)) else np.nan
                if rank_name:
                    rec[rank_name] = _rank_pct(arr, x) if (ok and np.isfinite(x)) else np.nan
            rec["secidx_ret_20"] = _indep_secidx(t, imap.get(tk) if tk not in etf else None,
                                                 smap, idx_le, idx_cache, eod_dates,
                                                 F.SECIDX_DEFAULT_INDEX)
            stored = rows_t[rows_t["ticker"] == tk].iloc[0]
            cmp = {}
            for f in F.F2:
                ok = _close(float(stored[f]), float(rec[f]))
                n_vals += 1
                n_match += ok
                if np.isfinite(stored[f]) and np.isfinite(rec[f]):
                    worst = max(worst, abs(stored[f] - rec[f]) / max(1e-12, abs(stored[f])))
                cmp[f] = {"stored": _jsonable(float(stored[f])),
                          "recomputed": _jsonable(float(rec[f])), "equal": bool(ok)}
            cells.append({"date": str(t.date()), "ticker": tk, "family": "F2",
                          "group": g, "all_equal": all(c["equal"] for c in cmp.values()),
                          "values": cmp})
        # ---- F3: raw F&O files <= t ------------------------------------------
        fo_le = [p for p in fo_all if fo_dates[p] <= t.date()]
        rec3 = _indep_f3(t, f3_t, fo_le, eodA, fo_cache, eod_dates)
        for tk in f3_t:
            stored = rows_t[rows_t["ticker"] == tk].iloc[0]
            cmp = {}
            for f in F.F3:
                rt = RTOL_Z if f == "fut_oi_z_60" else RTOL
                ok = _close(float(stored[f]), float(rec3[tk][f]), rtol=rt)
                n_vals += 1
                n_match += ok
                cmp[f] = {"stored": _jsonable(float(stored[f])),
                          "recomputed": _jsonable(float(rec3[tk][f])), "equal": bool(ok)}
            cells.append({"date": str(t.date()), "ticker": tk, "family": "F3",
                          "all_equal": all(c["equal"] for c in cmp.values()), "values": cmp})
    n_cells = len(cells)
    n_ok = sum(c["all_equal"] for c in cells)
    return {"method": ("independent code path: csv-module readers of the raw F&O zips and "
                       "ind_close_all files dated <= t, numpy loops over EOD bars dated <= t "
                       "(Wilder ATR by explicit recursion, medians/ranks by counting)"),
            "seed": C.SEED, "n_dates": int(n_dates), "n_cells": n_cells,
            "n_cells_all_equal": int(n_ok), "n_values": int(n_vals), "n_values_equal": int(n_match),
            "tolerance": {"rtol": RTOL, "rtol_fut_oi_z_60": RTOL_Z, "nan_equals_nan": True},
            "max_rel_diff_f2_finite": worst, "passed": n_ok == n_cells,
            "seconds": round(time.perf_counter() - t0, 1), "cells": cells}


# ========================================================================= #
# (b) per-session truncation over one month, (c) shift test
# ========================================================================= #

def _compare(full: pd.DataFrame, trunc: pd.DataFrame, keys: list[str], cols: list[str]) -> dict:
    m = full.merge(trunc, on=keys, how="outer", suffixes=("_full", "_trunc"), indicator=True)
    out = {"rows_full": int(len(full)), "rows_trunc": int(len(trunc)),
           "rows_only_in_one": int((m["_merge"] != "both").sum()), "per_feature": {}}
    n_bad = out["rows_only_in_one"]
    mb = m[m["_merge"] == "both"]
    n_exact = 0
    for c in cols:
        a, b = mb[c + "_full"].to_numpy(dtype=float), mb[c + "_trunc"].to_numpy(dtype=float)
        nan_mis = int((np.isnan(a) != np.isnan(b)).sum())
        both = np.isfinite(a) & np.isfinite(b)
        diff = np.abs(a[both] - b[both])
        tol = 1e-12 * np.maximum(1.0, np.abs(a[both]))
        n_diff = int((diff > tol).sum())
        n_bits = int((diff > 0).sum())
        out["per_feature"][c] = {"max_abs_diff": float(diff.max()) if diff.size else 0.0,
                                 "n_diff": n_diff, "n_not_bitwise_equal": n_bits,
                                 "nan_mismatch": nan_mis}
        n_bad += nan_mis + n_diff
        n_exact += n_bits
    out["identical"] = n_bad == 0
    out["bitwise_identical"] = n_bad == 0 and n_exact == 0
    out["tolerance"] = "|diff| <= 1e-12 x max(1, |value|); NaN must match NaN"
    return out


def _truncated_build(t: pd.Timestamp, raw_dirs: dict | None = None, use_cache: bool = True):
    rep = P.run(max_date=t.date(), write=False, raw_dirs=raw_dirs, use_cache=use_cache,
                eod_path=SOURCES["eod"])
    fo, idx, part = rep["_frames"]
    return F.build(SOURCES["eod"], max_date=t, staging=(fo, idx, part), write=False,
                   prices_path=SOURCES["prices"])


def pit_month_truncation(res: dict, month: str = "2024-07") -> dict:
    t0 = time.perf_counter()
    ex, ms = res["extra"], res["market_state"]
    ds = sorted(ex.loc[ex["date"].dt.strftime("%Y-%m") == month, "date"].unique())
    per_date = []
    for i, t in enumerate(ds):
        t = pd.Timestamp(t)
        literal = i == len(ds) - 1
        raw_dirs, tmp = None, None
        if literal:
            tmp = C.EXT / "_pit_tmp" / f"files_le_{t:%Y%m%d}"
            if tmp.exists():
                shutil.rmtree(tmp)
            raw_dirs = {}
            for kind, src in (("fo", C.RAW_FO), ("indices", C.RAW_IDX),
                              ("participant", C.RAW_PART)):
                dst = tmp / kind
                dst.mkdir(parents=True)
                for p in P.list_raw(kind, t.date()):
                    os.symlink(p, dst / p.name)
                raw_dirs[kind] = dst
        tr = _truncated_build(t, raw_dirs, use_cache=not literal)
        a = _compare(ex[ex["date"] == t], tr["extra"][tr["extra"]["date"] == t],
                     ["date", "ticker"], F.F2 + F.F3)
        b = _compare(ms[ms["date"] == t], tr["market_state"][tr["market_state"]["date"] == t],
                     ["date"], F.F1 + F.F4)
        n_after = {k: int(sum(1 for p in P.list_raw(k)
                              if (P.fo_file_date(p.name)[0] if k == "fo" else
                                  P.ddmmyyyy_date(P.IDX_RE if k == "indices" else P.PART_RE,
                                                  p.name)) > t.date()))
                   for k in ("fo", "indices", "participant")}
        per_date.append({"t": str(t.date()), "literal_file_removal_no_cache": literal,
                         "files_removed_after_t": n_after,
                         "extra_rows_identical": a["identical"], "extra_rows": a["rows_full"],
                         "market_state_identical": b["identical"],
                         "worst_extra": {k: v for k, v in a["per_feature"].items()
                                         if v["n_diff"] or v["nan_mismatch"]},
                         "worst_market": {k: v for k, v in b["per_feature"].items()
                                          if v["n_diff"] or v["nan_mismatch"]}})
        if tmp is not None:
            shutil.rmtree(tmp)
        print(f"  (b) {t.date()}: extra identical={a['identical']} "
              f"market identical={b['identical']}", flush=True)
    ok = all(d["extra_rows_identical"] and d["market_state_identical"] for d in per_date)
    return {"month": month, "n_sessions": len(per_date), "passed": ok,
            "seconds": round(time.perf_counter() - t0, 1), "per_date": per_date}


def pit_shift_test(res: dict, cutoffs=("2023-12-29", "2025-06-30")) -> dict:
    t0 = time.perf_counter()
    out = []
    for c in cutoffs:
        T0 = pd.Timestamp(c)
        tr = _truncated_build(T0)
        a = _compare(res["extra"][res["extra"]["date"] <= T0], tr["extra"],
                     ["date", "ticker"], F.F2 + F.F3)
        b = _compare(res["market_state"][res["market_state"]["date"] <= T0],
                     tr["market_state"], ["date"], F.F1 + F.F4)
        out.append({"T0": c, "extra_rows_compared": a["rows_full"],
                    "extra_identical": a["identical"], "market_rows_compared": b["rows_full"],
                    "market_identical": b["identical"],
                    "extra_per_feature": a["per_feature"], "market_per_feature": b["per_feature"]})
        print(f"  (c) T0={c}: extra identical={a['identical']} market identical={b['identical']}",
              flush=True)
    return {"cutoffs": list(cutoffs), "passed": all(x["extra_identical"] and x["market_identical"]
                                                    for x in out),
            "seconds": round(time.perf_counter() - t0, 1), "results": out}


# ========================================================================= #
# NaN shares, descriptive IC, survivorship diagnostic
# ========================================================================= #

def nan_shares(res: dict) -> dict:
    ex, ms = res["extra"], res["market_state"]
    out = {"extra_features": {}, "market_state": {}}
    for f in F.F2 + F.F3:
        by = ex.groupby(ex["date"].dt.year)[f].apply(lambda s: float(s.isna().mean()))
        out["extra_features"][f] = {"overall": round(float(ex[f].isna().mean()), 4),
                                    "by_year": {int(k): round(v, 4) for k, v in by.items()}}
    fm = ex["fo_member"] == 1
    for f in F.F3[1:]:
        out["extra_features"][f]["among_fo_members"] = round(float(ex.loc[fm, f].isna().mean()), 4)
    for f in F.F1 + F.F4:
        out["market_state"][f] = {"overall": round(float(ms[f].isna().mean()), 4),
                                  "n_nan_dates": int(ms[f].isna().sum()),
                                  "nan_dates": ms.loc[ms[f].isna(), "date"].dt.date.astype(str)
                                  .tolist()[:15]}
    return out


def monthly_ic(res: dict) -> dict:
    """REPORTING ONLY. Per-date Spearman IC of each stock-level feature vs
    y_excess_20d on y_clean_20d rows of the v1 dataset (dates with >= 50
    valid pairs), averaged by calendar month. Market-level features (F1, F4)
    are constant within a date: no cross-sectional IC."""
    from scipy.stats import spearmanr
    v1 = pd.read_parquet(SOURCES["dataset"], columns=["date", "ticker", "y_excess_20d", "y_clean_20d"])
    v1["date"] = pd.to_datetime(v1["date"]).astype("datetime64[ns]")
    v1 = v1[v1["y_clean_20d"].astype(bool) & v1["y_excess_20d"].notna()]
    m = v1.merge(res["extra"], on=["date", "ticker"], how="inner")
    y = m["y_excess_20d"].to_numpy(dtype=float)
    idxmap = m.groupby("date").indices
    out = {}
    for f in F.F2 + F.F3:
        x = m[f].to_numpy(dtype=float)
        daily = {}
        for d, ix in idxmap.items():
            xi, yi = x[ix], y[ix]
            k = np.isfinite(xi) & np.isfinite(yi)
            if int(k.sum()) < 50 or np.unique(xi[k]).size < 2:
                continue
            r = spearmanr(xi[k], yi[k])
            rho = float(getattr(r, "statistic", getattr(r, "correlation", np.nan)))
            if np.isfinite(rho):
                daily[pd.Timestamp(d)] = rho
        s = pd.Series(daily, dtype=float)
        if s.empty:
            out[f] = {"n_months": 0}
            continue
        mo = s.groupby(s.index.strftime("%Y-%m")).mean()
        out[f] = {"n_dates": int(len(s)), "n_months": int(len(mo)),
                  "n_months_positive": int((mo > 0).sum()),
                  "mean_monthly_ic": round(float(mo.mean()), 5),
                  "monthly": {k: round(float(v), 5) for k, v in mo.items()}}
    for f in F.F1 + F.F4:
        out[f] = {"n_months": None, "note": "market-level (one value per date): cross-sectional "
                                            "IC undefined"}
    return {"label": "REPORTING ONLY - descriptive; not used to add, drop or transform any "
                     "feature; family membership fixed in ml/IMPROVEMENT_PLAN.md",
            "target": f"y_excess_20d on y_clean_20d rows ({SOURCES['tag']} dataset)",
            "min_pairs_per_date": 50,
            "features": out}


def survivorship_diag(res: dict) -> dict:
    """REPORTING ONLY. How much 'has an industry label' (2026-10-19 lists)
    says about future excess returns, by year, on ex-ETF universe rows."""
    v1 = pd.read_parquet(SOURCES["dataset"], columns=["date", "ticker", "y_excess_20d", "y_clean_20d",
                                                     "label_beat_mkt_20d"])
    v1["date"] = pd.to_datetime(v1["date"]).astype("datetime64[ns]")
    g = res["groups"]
    m = v1.merge(g, on=["date", "ticker"])
    m = m[m["y_clean_20d"].astype(bool) & (m["grp"] != F.ETF_GROUP)]
    m["classified"] = m["industry"].notna()
    out = {}
    def auc_binary(flag: pd.Series, lab: pd.Series) -> float:
        # AUC of a 0/1 score = 0.5 + (P(flag | label 1) - P(flag | label 0)) / 2
        lab = lab.astype(float)
        a = flag[lab == 1].mean()
        b = flag[lab == 0].mean()
        return float(0.5 + 0.5 * (a - b))

    for y, s in m.groupby(m["date"].dt.year):
        c, u = s[s["classified"]], s[~s["classified"]]
        pc, pu = c["label_beat_mkt_20d"].mean(), u["label_beat_mkt_20d"].mean()
        out[int(y)] = {"rows": int(len(s)), "share_classified": round(float(s["classified"].mean()), 4),
                       "mean_y_excess_classified": round(float(c["y_excess_20d"].mean()), 5),
                       "mean_y_excess_unclassified": round(float(u["y_excess_20d"].mean()), 5),
                       "beat_rate_classified": round(float(pc), 4),
                       "beat_rate_unclassified": round(float(pu), 4),
                       "auc_of_classified_indicator": round(
                           auc_binary(s["classified"].astype(float), s["label_beat_mkt_20d"]), 4)}
    sec_nan = res["extra"][["date", "ticker", "secidx_ret_20"]].merge(
        m[["date", "ticker", "label_beat_mkt_20d"]], on=["date", "ticker"])
    isn = sec_nan["secidx_ret_20"].isna()
    p1, p0 = sec_nan.loc[~isn, "label_beat_mkt_20d"].mean(), sec_nan.loc[isn, "label_beat_mkt_20d"].mean()
    return {"label": "REPORTING ONLY - leak diagnostic for the static (2026-10-19) industry lists",
            "by_year": out,
            "secidx_ret_20_nan_indicator": {
                "share_nan": round(float(isn.mean()), 4),
                "beat_rate_non_nan": round(float(p1), 4),
                "beat_rate_nan": round(float(p0), 4),
                "auc_of_non_nan_indicator": round(auc_binary((~isn).astype(float),
                                                             sec_nan["label_beat_mkt_20d"]), 4)},
            "note": ("auc_of_classified_indicator = 0.5 + (P(classified | beat) - "
                     "P(classified | not beat))/2: the pooled AUC a model would get from the "
                     "membership flag alone")}


def size_proxy_diag(res: dict) -> dict:
    """REPORTING ONLY. Separates a genuine size effect from the look-ahead:
    at each date the ex-ETF universe names are ranked by their point-in-time
    20-session median turnover and the top N flagged, N = the number of
    names carrying an industry label that date. AUC of that PIT flag vs the
    AUC of the snapshot 'classified' flag, by year."""
    v1 = pd.read_parquet(SOURCES["dataset"], columns=["date", "ticker", "y_clean_20d",
                                                     "label_beat_mkt_20d"])
    v1["date"] = pd.to_datetime(v1["date"]).astype("datetime64[ns]")
    g = res["groups"].merge(res["base_universe"][["date", "ticker", "med_turn_20"]],
                            on=["date", "ticker"])
    g = g[g["grp"] != F.ETF_GROUP].copy()
    g["classified"] = g["industry"].notna()
    n_cls = g.groupby("date")["classified"].transform("sum")
    rk = g.groupby("date")["med_turn_20"].rank(ascending=False, method="first")
    g["pit_top_n"] = rk <= n_cls
    m = g.merge(v1, on=["date", "ticker"])
    m = m[m["y_clean_20d"].astype(bool) & m["label_beat_mkt_20d"].notna()]

    def auc_binary(flag, lab):
        return float(0.5 + 0.5 * (flag[lab == 1].mean() - flag[lab == 0].mean()))

    out = {}
    for y, s in m.groupby(m["date"].dt.year):
        lab = s["label_beat_mkt_20d"].astype(float)
        out[int(y)] = {"auc_snapshot_classified": round(auc_binary(s["classified"].astype(float), lab), 4),
                       "auc_pit_turnover_top_n": round(auc_binary(s["pit_top_n"].astype(float), lab), 4),
                       "overlap_share": round(float((s["classified"] == s["pit_top_n"]).mean()), 4)}
    return {"label": "REPORTING ONLY - leak diagnostic", "by_year": out,
            "reading": ("if the PIT size flag's AUC is near 0.5 while the snapshot flag's is "
                        "well above, the snapshot flag carries future information")}


def partition_identifiability(res: dict) -> dict:
    """REPORTING ONLY (no labels). Can a classifier recover the snapshot
    partition ('has an industry label in the 2026-10-19 lists') from the
    features a model would see? Train on 2023 rows, score 2025 rows (ex-ETF
    universe); the AUC increment of F2 over the base features measures how
    much F2 exposes the partition."""
    import lightgbm as lgb
    from sklearn.metrics import roc_auc_score
    basecols = ["log_turnover", "cs_rank_turnover", "atr_pct", "vol_20", "deliv_pct_sma_20",
                "mom_20", "ret_126d", "ret_252d", "dist_52w_high", "mom_12_1"]
    v1 = pd.read_parquet(SOURCES["dataset"], columns=["date", "ticker"] + basecols)
    v1["date"] = pd.to_datetime(v1["date"]).astype("datetime64[ns]")
    g = res["groups"]
    m = v1.merge(g, on=["date", "ticker"]).merge(res["extra"][["date", "ticker"] + F.F2],
                                                on=["date", "ticker"])
    m = m.merge(res["market_state"][["date"] + F.F1], on="date", how="left")
    m = m[m["grp"] != F.ETF_GROUP]
    m["classified"] = m["industry"].notna().astype(int)
    tr = m[m["date"].dt.year == 2023].sample(n=min(200_000, int((m["date"].dt.year == 2023).sum())),
                                            random_state=C.SEED)
    te = m[m["date"].dt.year == 2025].sample(n=min(200_000, int((m["date"].dt.year == 2025).sum())),
                                            random_state=C.SEED)
    sets = {"base10": basecols, "base10+F2": basecols + F.F2,
            "base10+F2+F1": basecols + F.F2 + F.F1, "F2_only": F.F2}
    out = {}
    for name, cols in sets.items():
        mdl = lgb.LGBMClassifier(n_estimators=200, num_leaves=31, learning_rate=0.05,
                                 min_child_samples=200, subsample=0.8, subsample_freq=1,
                                 colsample_bytree=0.8, n_jobs=2, random_state=C.SEED, verbose=-1)
        mdl.fit(tr[cols], tr["classified"])
        p = mdl.predict_proba(te[cols])[:, 1]
        out[name] = round(float(roc_auc_score(te["classified"], p)), 4)
    return {"label": "REPORTING ONLY - partition identifiability (target = snapshot "
                     "classification flag, no return labels)",
            "train": "2023 rows (200k sample)", "test": "2025 rows (200k sample)",
            "test_auc_predicting_classified": out}
