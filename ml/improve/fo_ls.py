#!/usr/bin/env python3
"""Q4 (ml/IMPROVEMENT_PLAN_2.md): market-neutral long-short on F&O names via stock futures.

Universe on signal date t = F&O members (a stock future exists on t) among the ten-year control's scored rows.
Long the top quintile in cash (adjusted opens t+1 -> t+21, the engine's paths); short the bottom quintile through
the near-month stock future (next month when the near one has fewer than 3 sessions to expiry at entry), marked on
settlement prices t+1 -> t+21, rolled at expiry and chain-linked. Two books (the plan's two trials): the plain
control score and the score neutralised within the F&O universe per date (vol+size). Twenty overlapping tranches
aggregated daily with ml/strategy_backtest.py's Calendar; costs 20 bps per side long, 40 bps per side short plus
10 bps per roll. Every convention is fixed in ml/results/improve2/fo_ls/FO_LS.md section 1 (written before any
result); this module implements it and writes fo_ls.json and the results section of FO_LS.md.

Added after the results of record existed (the primary books are unchanged, number for number): drawdown peak /
trough / recovery dates; an independent recomputation of a seeded sample of short-leg paths from the raw futures
rows; a split/bonus check of the futures adjustment; and a total-return sensitivity (FO_LS.md 2.7: cash dividends
credited to the long leg, the dividend added back on contracts NSE adjusted for it), which is not a pass-mark input.

Reused, not reimplemented: ml/books/data.py (base panel, scores, price grid, name-level cost inputs),
ml/strategy_backtest.py (build_blocks, leg, trade_fracs, Calendar, series_stats, beta_alpha, tranche_stats,
dsr_block, wmoments), ml/books/engine.py (neutralise, BookEngine.run_members, _order),
ml/books/construct.py (summarize, per_date_spearman).

    cd /home/user/SuryaDhana_AI && python3 -m ml.improve.fo_ls            # full run (light: no model training)
    cd /home/user/SuryaDhana_AI && python3 -m ml.improve.fo_ls --smoke    # three folds, writes to fo_ls/smoke/
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import argparse
import dataclasses
import json
import math
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books import construct as C
from ml.books import data as D
from ml.books import engine as E

ML_DIR = Path(__file__).resolve().parents[1]
REPO = ML_DIR.parent
DATA_10Y = ML_DIR / "data_10y"
PREDS_10Y = ML_DIR / "results" / "improve" / "ab" / "10y" / "preds"
PRICES = ML_DIR / "results" / "improve" / "cache" / "features_prices_export_10y.parquet"
PRICE_START = "2017-10-02"
FO_PARQUET = ML_DIR / "data_ext" / "fo_daily_stock.parquet"
INDEX_PARQUET = ML_DIR / "data_ext" / "index_daily.parquet"
CA_FEED = ML_DIR / "data_ext" / "corporate_actions_feed_10y.csv"
BREAK_FLAGS = ML_DIR / "data_ext" / "price_break_flags_10y.csv"
CA_ALL = ML_DIR / "data_ext" / "corporate_actions_all_10y.csv"     # every bc record, dividends included
BOOKS_JSON = ML_DIR / "results" / "improve" / "books" / "books.json"
OUT = ML_DIR / "results" / "improve2" / "fo_ls"
MD_MARKER = "<!-- RESULTS"
MD_END = "<!-- END OF GENERATED RESULTS -->"

MODEL = "control"
H = sb.HORIZON                      # 20 sessions
QUINT = 0.20
NEXT_IF_LT = 3                      # use the next-month contract when the near one has < 3 sessions to expiry
C_LONG, C_SHORT, C_ROLL = 20e-4, 40e-4, 10e-4
BREAK_TOL = 0.05                    # futures vs cash one-session return gap that marks a data / adjustment break
N_TRIALS = 261
RF = sb.RF_ANNUAL                   # 5.5% a year
PPY = sb.PPY
BOOKS = {"plain": "none", "neutral": "vol+size"}
VARIANTS = ("net", "gross", "no_netting")
SMOKE_RANGE = ("2019-01-01", "2019-03-31")
NIFTY = "Nifty 50"
# total-return sensitivity (added after the results of record; FO_LS.md 2.7): a stock-futures contract counts as
# adjusted for a dividend when the dividend is at least DIV_ADJ_MIN of the previous unadjusted close and the
# ex-date futures-minus-cash return gap is below DIV_ADJ_SHARE of the dividend yield (an unadjusted contract does
# not fall on the ex-date, so the gap is about the whole yield; an adjusted one falls with the cash, gap about 0)
DIV_ADJ_MIN, DIV_ADJ_SHARE = 0.02, 0.5
DIV_AMT = re.compile(r"(?:RS|RE|DIV|DV)\.?\s*[-:]?\s*(\d+(?:\.\d+)?)(?!\s*%)")
N_CHECK = 400                       # independent short-path recomputation: sampled name-windows

T0 = time.time()
_LOG: Path | None = None


def log(msg: str) -> None:
    line = f"[fo_ls +{time.time() - T0:5.0f}s] {msg}"
    print(line, flush=True)
    if _LOG is not None:
        with open(_LOG, "a") as fh:
            fh.write(line + "\n")


def rel(p: Path) -> str:
    return str(Path(p).resolve().relative_to(REPO))


# --------------------------------------------------------------------------- inputs
def load_panel(smoke: bool):
    """Base panel and control scores of the ten-year books (ml/books/data.py, as ml/improve/ab_books.py --tag 10y)."""
    D.DATA_5Y, D.PREDS, D.PRICES_PARQUET, D.PRICE_START = DATA_10Y, PREDS_10Y, PRICES, PRICE_START
    splits = D.load_splits()
    base = D.load_base(splits)
    scores, smeta = D.load_scores(base, [MODEL])
    score = scores[MODEL]
    if smoke:
        m = (base["date"] >= SMOKE_RANGE[0]) & (base["date"] <= SMOKE_RANGE[1])
        score = score[m.to_numpy()]
        base = base[m].reset_index(drop=True)
        last = base["month"].max()
        base["segment"] = np.where(base["month"] == last, "holdout", "cv")   # smoke only: a stand-in holdout
    return base, score, smeta


def price_grids(sessions: pd.DatetimeIndex, tickers: list[str]):
    """Adjusted close, unadjusted close and the split/bonus adjustment factor close / close_unadj on the grid."""
    p = pd.read_parquet(PRICES, columns=["date", "ticker", "close", "close_unadj"])
    p["date"] = pd.to_datetime(p["date"])
    p = p[(p["date"] >= sessions[0]) & p["ticker"].isin(tickers)]
    cadj = p.pivot(index="date", columns="ticker", values="close").reindex(index=sessions, columns=tickers)
    cu = p.pivot(index="date", columns="ticker", values="close_unadj").reindex(index=sessions, columns=tickers)
    fac = (cadj / cu).ffill().bfill()
    return cadj.to_numpy(float), cu.to_numpy(float), fac.to_numpy(float)


def expiry_session(e: np.ndarray, sessions: pd.DatetimeIndex) -> np.ndarray:
    """Last price session on or before each expiry date; expiries after the last session get distinct indices
    beyond the grid (they never expire inside the sample)."""
    sv = sessions.values.astype("datetime64[ns]")
    ev = e.astype("datetime64[ns]")
    i = np.searchsorted(sv, ev, side="right") - 1
    beyond = ev > sv[-1]
    extra = ((ev - sv[-1]) / np.timedelta64(1, "D")).astype(float)
    return np.where(beyond, len(sv) + extra, i).astype(float)


@dataclasses.dataclass
class FutGrid:
    tickers: list
    col: dict
    present: np.ndarray        # (S, J) stock has a futures row (after the session imputation)
    SN: np.ndarray             # near settle on the common calendar (NaN if absent / off-calendar)
    SX: np.ndarray             # next settle on the common calendar
    Nc: np.ndarray             # (S,) common near-contract expiry session index
    Xc: np.ndarray             # (S,) common next-contract expiry session index
    off: np.ndarray            # (S, J) off-calendar contract row (special early expiry)
    brk: np.ndarray            # (S, J) futures/cash break on the session
    pb: np.ndarray             # (S, J) price-break-flag ex-date on the session
    fac: np.ndarray            # (S, J) adjustment factor
    cadj: np.ndarray           # (S, J) adjusted cash close (raw: NaN when the stock did not trade in cash)
    cadj_ff: np.ndarray        # (S, J) the same, forward- then back-filled (basis path only)
    meta: dict


def futures_grid(sessions: pd.DatetimeIndex) -> FutGrid:
    f = pd.read_parquet(FO_PARQUET, columns=["date", "ticker", "fut_near_settle", "fut_near_expiry",
                                            "fut_next_settle", "fut_next_expiry", "window"])
    f["date"] = pd.to_datetime(f["date"])
    f = f[(f["date"] >= sessions[0]) & (f["date"] <= sessions[-1])].copy()
    assert not f.duplicated(["date", "ticker"]).any(), "futures file has duplicate (date, ticker)"
    f_dates = set(f["date"].unique())
    not_price = sorted(d for d in f_dates if d not in set(sessions))
    assert not not_price, f"futures sessions outside the price calendar: {not_price[:5]}"
    f["ne_i"] = expiry_session(f["fut_near_expiry"].to_numpy(), sessions)
    nx = f["fut_next_expiry"].to_numpy()
    f["xe_i"] = np.where(pd.isna(nx), np.nan, expiry_session(np.where(pd.isna(nx), f["fut_near_expiry"].to_numpy(), nx),
                                                             sessions))
    tickers = sorted(f["ticker"].unique())
    col = {t: j for j, t in enumerate(tickers)}

    def piv(c):
        return np.array(f.pivot(index="date", columns="ticker", values=c).reindex(index=sessions, columns=tickers), dtype=float)

    NS, XS, NE, XE = piv("fut_near_settle"), piv("fut_next_settle"), piv("ne_i"), piv("xe_i")
    present = np.isfinite(NS)
    S = len(sessions)
    mode_n = f.groupby("date")["ne_i"].agg(lambda s: s.mode().iloc[0])
    mode_x = f.groupby("date")["xe_i"].agg(lambda s: s.mode().iloc[0])
    Nc = np.array(mode_n.reindex(sessions), dtype=float)
    Xc = np.array(mode_x.reindex(sessions), dtype=float)
    cadj, cu, fac = price_grids(sessions, tickers)
    # ---- whole sessions missing from the futures file (inside its span): impute from the cash close
    first_f = min(f_dates)
    missing = [i for i, d in enumerate(sessions) if d not in f_dates and d > first_f]
    imputed = []
    for i in missing:
        assert Nc[i - 1] != i - 1, "an imputed session follows an expiry session"
        ratio = cu[i] / cu[i - 1]
        NS[i] = NS[i - 1] * ratio
        XS[i] = XS[i - 1] * ratio
        NE[i], XE[i], Nc[i], Xc[i] = NE[i - 1], XE[i - 1], Nc[i - 1], Xc[i - 1]
        present[i] = present[i - 1]
        imputed.append({"session": str(sessions[i].date()), "stocks_imputed": int(np.isfinite(NS[i]).sum()),
                        "stocks_present_previous_session": int(present[i - 1].sum()),
                        "stocks_without_cash_close": int((present[i - 1] & ~np.isfinite(ratio)).sum())})
        present[i] &= np.isfinite(NS[i])
    assert np.isfinite(Nc).all() and np.isfinite(Xc).all(), "common contract calendar has gaps"
    # ---- calendar-aligned settles and off-calendar rows
    on_n = present & (NE == Nc[:, None])
    on_x = np.isfinite(XS) & (XE == Xc[:, None])
    off = present & ((NE != Nc[:, None]) | (np.isfinite(XE) & (XE != Xc[:, None])))
    SN = np.where(on_n, NS, np.nan)
    SX = np.where(on_x, XS, np.nan)
    # ---- futures / cash break screen: same contract, consecutive sessions, split-adjusted
    brk = np.zeros_like(present)
    rs = cadj[1:] / cadj[:-1] - 1.0
    n_cmp = 0
    for i in range(1, S):
        for c in (Nc[i - 1], Xc[i - 1]):
            if c < i:                              # expired on i-1: no continuation
                continue
            p0 = (SN[i - 1] if Nc[i - 1] == c else SX[i - 1]) * fac[i - 1]
            if Nc[i] == c:
                p1 = SN[i] * fac[i]
            elif Xc[i] == c:
                p1 = SX[i] * fac[i]
            else:
                raise AssertionError(f"contract {c} alive on session {i} but neither near nor next")
            rf_ = p1 / p0 - 1.0
            ok = np.isfinite(rf_) & np.isfinite(rs[i - 1])
            n_cmp += int(ok.sum())
            brk[i] |= ok & (np.abs(rf_ - rs[i - 1]) > BREAK_TOL)
    # ---- price-break flags (unadjustable corporate actions)
    pbf = pd.read_csv(BREAK_FLAGS, parse_dates=["ex_date"])
    pbf = pbf[pbf["ticker"].isin(col)]
    pb = np.zeros_like(present)
    sv = sessions.values
    n_pb = 0
    for t, d in zip(pbf["ticker"], pbf["ex_date"]):
        i = int(np.searchsorted(sv, np.datetime64(d), side="left"))
        if 0 <= i < S:
            pb[i, col[t]] = True
            n_pb += 1
    meta = {"rows_in_span": int(len(f)), "stocks": len(tickers), "windows": f["window"].value_counts().to_dict(),
            "sessions_missing_from_futures_file_imputed": imputed,
            "expiry_sessions_in_span": int(len(set(Nc.astype(int)) & set(range(S)))),
            "off_calendar_rows": int(off.sum()), "off_calendar_stocks": sorted({tickers[j] for j in np.flatnonzero(off.any(0))}),
            "break_screen": {"tolerance_abs_return_gap": BREAK_TOL, "comparisons": n_cmp, "break_sessions": int(brk.sum()),
                             "break_stocks": sorted({tickers[j] for j in np.flatnonzero(brk.any(0))})},
            "price_break_flags_on_fo_stocks_in_span": n_pb,
            "split_bonus_events_on_fo_stocks_in_span": int(sum(
                1 for t, d in pd.read_csv(CA_FEED, parse_dates=["ex_date"])[["ticker", "ex_date"]].itertuples(index=False)
                if t in col and sessions[0] <= d <= sessions[-1])),
            "next_settle_missing_share_of_rows": float(np.mean(~np.isfinite(XS[present])))}
    cadj_ff = pd.DataFrame(cadj).ffill().bfill().to_numpy(float)
    return FutGrid(tickers, col, present, SN, SX, Nc, Xc, off, brk, pb, fac, cadj, cadj_ff, meta)


# --------------------------------------------------------------------------- contracts and universe
def entry_contract(G: FutGrid, p: int) -> float:
    a = p + 1
    return G.Nc[a] if G.Nc[a] - a >= NEXT_IF_LT else G.Xc[a]


def contract_steps(G: FutGrid, p: int):
    """Held contract for each increment (d-1 -> d), d = t+2 .. t+21, and the roll target when the held contract's
    expiry session is d and d is before the exit session."""
    a, b = p + 1, p + 1 + H
    c = entry_contract(G, p)
    steps = []
    for d in range(a + 1, b + 1):
        roll = (c == d) and (d < b)
        new = G.Xc[d] if roll else None
        steps.append((d, c, roll, new))
        if roll:
            c = new
    return entry_contract(G, p), steps, c


def settle_at(G: FutGrid, c: float, d: int, cols: np.ndarray) -> np.ndarray:
    if G.Nc[d] == c:
        return G.SN[d, cols] * G.fac[d, cols]
    if G.Xc[d] == c:
        return G.SX[d, cols] * G.fac[d, cols]
    raise AssertionError(f"contract {c} is neither near nor next on session {d}")


def universe_mask(base: pd.DataFrame, G: FutGrid, sessions: pd.DatetimeIndex) -> tuple[np.ndarray, dict]:
    pos_of = {d: i for i, d in enumerate(sessions)}
    p = base["date"].map(pos_of).to_numpy()
    j = base["ticker"].map(G.col).to_numpy(float)
    has = np.isfinite(j)
    ji = np.where(has, j, 0).astype(int)
    member = has & G.present[p, ji]
    c0_by_session = np.array([entry_contract(G, q) if q + 1 < len(sessions) else np.nan for q in range(len(sessions))])
    c0 = c0_by_session[p]
    listed_n = (c0 == G.Nc[p]) & np.isfinite(G.SN[p, ji])
    listed_x = (c0 == G.Xc[p]) & np.isfinite(G.SX[p, ji])
    assert np.all((c0 == G.Nc[p]) | (c0 == G.Xc[p])), "entry contract not listed on the signal date's calendar"
    listed = member & (listed_n | listed_x)

    def window_any(flag: np.ndarray, lo: int, hi: int) -> np.ndarray:
        cs = np.vstack([np.zeros((1, flag.shape[1])), np.cumsum(flag, axis=0)])
        S = flag.shape[0]
        lo_i, hi_i = np.clip(p + lo, 0, S), np.clip(p + hi + 1, 0, S)
        return (cs[hi_i, ji] - cs[lo_i, ji]) > 0

    ex_pb = listed & window_any(G.pb, 2, H + 1)
    ex_off = listed & window_any(G.off, 1, H + 1)
    ex_brk = listed & window_any(G.brk, 2, H + 1)
    keep = listed & ~ex_pb & ~ex_off            # A1: the futures/cash break screen is a diagnostic, not an exclusion
    n_dates = base["date"].nunique()
    info = {"scored_rows": int(len(base)), "fo_member_rows": int(member.sum()),
            "fo_member_rows_per_date_mean": float(member.sum() / n_dates),
            "excluded_entry_contract_not_listed": int((member & ~listed).sum()),
            "excluded_price_break_flag_in_window": int(ex_pb.sum()),
            "excluded_off_calendar_contract_in_window": int(ex_off.sum()),
            "diagnostic_futures_cash_gap_in_window_kept": int((keep & ex_brk).sum()),
            "excluded_any_window_rule": int((listed & ~keep).sum()),
            "universe_rows": int(keep.sum()), "universe_rows_per_date_mean": float(keep.sum() / n_dates),
            "universe_tickers": int(base.loc[keep, "ticker"].nunique())}
    return keep, info


# --------------------------------------------------------------------------- short-leg paths
def short_paths(blocks, tick: np.ndarray, G: FutGrid, div_add: np.ndarray | None = None):
    """Per block: futures value path (H+1, n) of every universe name (chain-linked across rolls, split-adjusted),
    the matching cash-close path (same alive pattern), a (H, n) roll mask, and the contract bookkeeping.
    div_add (S, J), total-return sensitivity only: the split-adjusted dividend NSE took out of an adjusted contract's
    price on its ex-date session, added back to that session's settle in the return (the position is adjusted, so
    the holder neither gains nor loses the dividend)."""
    jmap = np.array([G.col[t] for t in tick])
    fut, spot, rolls, info = [], [], [], []
    cnt = {"entry_settle_backfilled": 0, "entry_never_quoted_flat": 0, "settle_carried_forward": 0,
           "names_flat_after_final_settlement": 0, "name_windows": 0, "rolls": 0}
    for b in blocks:
        cols = jmap[b.ci]
        n = cols.size
        c0, steps, c_exit = contract_steps(G, b.pos)
        a = b.pos + 1
        prev = settle_at(G, c0, a, cols)
        s_prev = G.cadj_ff[a, cols].copy()
        pending = ~np.isfinite(prev)
        cnt["entry_settle_backfilled"] += int(pending.sum())
        alive = ~pending
        V, Vs = np.ones(n), np.ones(n)
        P, Ps = np.ones((H + 1, n)), np.ones((H + 1, n))
        R = np.zeros((H, n), bool)
        for i, (d, c, roll, new) in enumerate(steps, start=1):
            cur = settle_at(G, c, d, cols)
            s_cur = G.cadj_ff[d, cols]
            enter = pending & (c == c0) & np.isfinite(cur)
            cnt["settle_carried_forward"] += int((alive & ~np.isfinite(cur)).sum())
            cur = np.where(np.isfinite(cur), cur, prev)
            add = 0.0 if div_add is None else div_add[d, cols]
            V = np.where(alive, V * (cur + add) / prev, V)
            Vs = np.where(alive, Vs * s_cur / s_prev, Vs)
            P[i], Ps[i] = V, Vs
            prev = np.where(enter, cur, prev)
            pending &= ~enter
            alive |= enter
            if roll:
                nxt = settle_at(G, new, d, cols)
                dead = alive & ~np.isfinite(nxt)
                cnt["names_flat_after_final_settlement"] += int(dead.sum())
                alive &= ~dead
                pending[:] = False                    # a name never entered by the first roll stays flat
                R[i - 1] = alive
                cnt["rolls"] += 1
                prev = np.where(alive, nxt, prev)
            else:
                prev = cur
            s_prev = s_cur
        cnt["entry_never_quoted_flat"] += int(pending.sum())
        cnt["name_windows"] += n
        fut.append(P)
        spot.append(Ps)
        rolls.append(R)
        info.append({"entry": c0, "exit": c_exit, "next_month_entry": bool(c0 != G.Nc[a]), "n_rolls": sum(s[2] for s in steps)})
    # the exiting tranche (k-H) holds the near contract of the entering tranche's entry session
    mism = 0
    for k in range(H, len(blocks)):
        a = blocks[k].pos + 1
        mism += int(info[k - H]["exit"] != G.Nc[a])
    cnt["exiting_tranche_contract_not_near_at_next_entry"] = mism
    return fut, spot, rolls, info, cnt


def close_marked(blocks, sessions: pd.DatetimeIndex, tick: np.ndarray, O: pd.DataFrame, raw: pd.DataFrame):
    """A2: the engine's long paths with the interior marks (1 .. H-1) at the adjusted close of sessions t+2 .. t+H
    instead of the adjusted open; path[0] = 1 at the entry open and path[H] = 1 + y_raw_20d (the engine's pin) are
    kept, so every tranche return is unchanged. Missing closes are carried forward, as the engine does for opens."""
    cl = raw.loc[raw["date"] >= sessions[0], ["date", "ticker", "close"]]
    cl = cl[cl["ticker"].isin(tick)]
    Cf = cl.pivot(index="date", columns="ticker", values="close").reindex(index=sessions, columns=tick).ffill().to_numpy(float)
    Ob = O.bfill().to_numpy(float)
    out, n_fill = [], 0
    for b in blocks:
        entry = Ob[b.pos + 1, b.ci]
        P = b.path.copy()
        mid = Cf[b.pos + 2:b.pos + 1 + H, b.ci] / entry[None, :]
        bad = ~np.isfinite(mid)
        n_fill += int(bad.sum())
        P[1:H] = mid
        P = np.array(pd.DataFrame(P).ffill().fillna(1.0), dtype=float)
        P[H] = b.path[H]
        out.append(dataclasses.replace(b, path=P))
    return out, {"interior_marks_unavailable_carried": n_fill}


# --------------------------------------------------------------------------- total-return sensitivity (post-result)
def dividends(sessions: pd.DatetimeIndex, G: FutGrid):
    """Cash dividends of the F&O stocks from the bc records (corporate_actions_all_10y.csv, kind 'dividend'):
    amount = sum of the rupee amounts in the purpose text of the record(s) still listed last before the ex-date
    (earlier records are preliminary notices, often without an amount); ex-date -> first price session on or after it.
    Returns DV (S, J): split-adjusted dividend per share on its ex-date session (long-leg credit), FA (S, J): the
    same restricted to contracts NSE adjusted for the dividend (short-leg add-back), and the event accounting."""
    ca = pd.read_csv(CA_ALL, parse_dates=["ex_date", "last_seen"])
    d = ca[(ca["kind"] == "dividend") & ca["ticker"].isin(G.col) & ca["ex_date"].notna()].copy()

    def amount(p) -> float:
        v = DIV_AMT.findall(str(p).upper())
        return float(sum(float(x) for x in v)) if v else float("nan")

    d["amt"] = d["purpose"].map(amount)
    n_events = int(d.groupby(["ticker", "ex_date"]).ngroups)
    d = d[d["amt"].notna()]
    d = d[d["last_seen"] == d.groupby(["ticker", "ex_date"])["last_seen"].transform("max")]
    d = d.drop_duplicates(["ticker", "ex_date", "purpose"])
    ev = d.groupby(["ticker", "ex_date"], as_index=False)["amt"].sum()
    S, J = G.present.shape
    sv = sessions.values
    DV, FA = np.zeros((S, J)), np.zeros((S, J))
    by_year, n_in, n_adj, n_large, n_conf, n_nonmem = {}, 0, 0, 0, 0, 0
    for t, e, a in ev.itertuples(index=False):
        x = int(np.searchsorted(sv, np.datetime64(e), side="left"))
        if x <= 0 or x >= S:
            continue
        j = G.col[t]
        DV[x, j] += a * G.fac[x, j]
        n_in += 1
        cu_prev = G.cadj[x - 1, j] / G.fac[x - 1, j]
        dy = a / cu_prev if np.isfinite(cu_prev) and cu_prev > 0 else float("nan")
        if not (np.isfinite(dy) and dy >= DIV_ADJ_MIN):
            continue
        n_large += 1
        if not (G.present[x, j] or G.present[x - 1, j]):
            n_nonmem += 1                                 # not an F&O member around the ex-date: no short exposure
            continue
        yr = by_year.setdefault(str(sessions[x].year), {"member_events_ge_2pct": 0, "futures_adjusted": 0})
        yr["member_events_ge_2pct"] += 1
        if not (G.present[x, j] and G.present[x - 1, j]) or G.fac[x, j] != G.fac[x - 1, j]:
            n_conf += 1                                   # member, but no quote on one side or a split the same day
            continue
        c = G.Nc[x - 1] if G.Nc[x - 1] >= x else G.Xc[x - 1]
        s0 = G.SN[x - 1, j] if G.Nc[x - 1] == c else G.SX[x - 1, j]
        s1 = G.SN[x, j] if G.Nc[x] == c else G.SX[x, j]
        gap = (s1 / s0 - 1.0) - (G.cadj[x, j] / G.cadj[x - 1, j] - 1.0)
        if np.isfinite(gap) and gap / dy < DIV_ADJ_SHARE:
            FA[x, j] = a * G.fac[x, j]
            n_adj += 1
            yr["futures_adjusted"] += 1
    meta = {"source": rel(CA_ALL), "fo_dividend_events": n_events, "events_with_amount_in_span": n_in,
            "share_events_with_amount": float(len(ev) / max(n_events, 1)),
            "events_ge_2pct_of_price": n_large, "events_ge_2pct_not_fo_member": n_nonmem,
            "events_ge_2pct_member_unclassifiable": n_conf,
            "futures_adjusted_events": n_adj, "by_year_ge_2pct": dict(sorted(by_year.items())),
            "rule": f"adjusted if dividend >= {DIV_ADJ_MIN:.0%} of the previous unadjusted close and the ex-date "
                    f"futures-minus-cash return gap < {DIV_ADJ_SHARE} x the dividend yield"}
    return DV, FA, meta


def with_dividends(cblocks, tick: np.ndarray, G: FutGrid, O: pd.DataFrame, DV: np.ndarray):
    """Long paths credited with cash dividends whose ex-date session is t+2 .. t+21 (bought at the open of t+1 cum
    dividend, sold at the open of t+21), added (not reinvested) from the ex-date's mark on, per rupee of entry."""
    jmap = np.array([G.col[t] for t in tick])
    Ob = O.bfill().to_numpy(float)
    out = []
    for b in cblocks:
        a = b.pos + 1
        cum = np.cumsum(DV[a + 1:a + 1 + H][:, jmap[b.ci]], axis=0) / Ob[a, b.ci][None, :]
        P = b.path.copy()
        P[1:] += cum
        out.append(dataclasses.replace(b, path=P))
    return out


def split_check(G: FutGrid, sessions: pd.DatetimeIndex) -> dict:
    """Every validated split/bonus ex-date of an F&O stock with a futures quote on both sides: the same contract's
    split-adjusted settle return against the adjusted cash close return on the ex-date session."""
    ca = pd.read_csv(CA_FEED, parse_dates=["ex_date"])
    ca = ca[ca["ticker"].isin(G.col) & (ca["ex_date"] >= sessions[0]) & (ca["ex_date"] <= sessions[-1])]
    sv, rows = sessions.values, []
    for t, d in zip(ca["ticker"], ca["ex_date"]):
        i = int(np.searchsorted(sv, np.datetime64(d), side="left"))
        if i <= 0 or i >= len(sessions) or sessions[i] != d:
            continue
        j = G.col[t]
        if not (G.present[i, j] and G.present[i - 1, j]):
            continue
        c = G.Nc[i - 1] if G.Nc[i - 1] >= i else G.Xc[i - 1]
        s0 = G.SN[i - 1, j] if G.Nc[i - 1] == c else G.SX[i - 1, j]
        s1 = G.SN[i, j] if G.Nc[i] == c else G.SX[i, j]
        raw_r = s1 / s0 - 1.0
        adj_r = (s1 * G.fac[i, j]) / (s0 * G.fac[i - 1, j]) - 1.0
        cash_r = G.cadj[i, j] / G.cadj[i - 1, j] - 1.0
        if np.isfinite(adj_r) and np.isfinite(cash_r):
            rows.append((raw_r, abs(adj_r - cash_r)))
    r = np.array(rows)
    return {"events": int(len(r)), "median_abs_unadjusted_futures_return": float(np.median(np.abs(r[:, 0]))),
            "max_abs_gap_adjusted_futures_vs_cash": float(r[:, 1].max()),
            "share_gap_gt_2pt": float((r[:, 1] > 0.02).mean())} if len(r) else {"events": 0}


# --------------------------------------------------------------------------- independent check of the short paths
def independent_short_check(blocks, tick: np.ndarray, fut, sessions: pd.DatetimeIndex, n: int = N_CHECK) -> dict:
    """Recompute the futures value at exit for a seeded sample of name-windows directly from the raw futures rows
    of each stock (no grid, no common calendar): the stock's own near expiry at t+1 (next month if < 3 sessions),
    settles of the contract with that expiry, split factor close / close_unadj of the price export, roll at the
    expiry session into the stock's own next expiry. Windows with a gap or a flat tail are skipped (counted)."""
    f = pd.read_parquet(FO_PARQUET, columns=["date", "ticker", "fut_near_settle", "fut_near_expiry",
                                            "fut_next_settle", "fut_next_expiry"])
    f["date"] = pd.to_datetime(f["date"])
    px = pd.read_parquet(PRICES, columns=["date", "ticker", "close", "close_unadj"])
    px["date"] = pd.to_datetime(px["date"])
    sv = sessions.values
    rng = np.random.default_rng(sb.SEED)
    ks = rng.choice(len(blocks), min(n, len(blocks)), replace=False)
    picks = [(k, int(rng.integers(len(blocks[k].ci)))) for k in ks]
    need = {tick[blocks[k].ci[j]] for k, j in picks}
    fr = {t: g.set_index("date") for t, g in f[f["ticker"].isin(need)].groupby("ticker")}
    pr = {t: g.set_index("date") for t, g in px[px["ticker"].isin(need)].groupby("ticker")}

    def es(e) -> int:
        return int(np.searchsorted(sv, np.datetime64(e), side="right") - 1)

    diffs, n_roll, skipped = [], 0, 0
    for k, j in picks:
        b, t = blocks[k], tick[blocks[k].ci[j]]
        g, p = fr[t], pr[t]
        a, e_ = b.pos + 1, b.pos + 1 + H

        def settle(i, c):
            d = sessions[i]
            if d not in g.index or d not in p.index:
                return None
            r, q = g.loc[d], p.loc[d]
            if pd.notna(r["fut_near_expiry"]) and es(r["fut_near_expiry"]) == c:
                v = r["fut_near_settle"]
            elif pd.notna(r["fut_next_expiry"]) and es(r["fut_next_expiry"]) == c:
                v = r["fut_next_settle"]
            else:
                return None
            v = v * q["close"] / q["close_unadj"]
            return v if np.isfinite(v) else None

        if sessions[a] not in g.index:
            skipped += 1
            continue
        r0 = g.loc[sessions[a]]
        c = es(r0["fut_near_expiry"])
        if c - a < NEXT_IF_LT:
            c = es(r0["fut_next_expiry"])
        prev, V, ok, rolled = settle(a, c), 1.0, True, False
        ok = prev is not None
        for d in range(a + 1, e_ + 1):
            if not ok:
                break
            cur = settle(d, c)
            if cur is None:
                ok = False
                break
            V *= cur / prev
            prev = cur
            if d == c and d < e_:
                rr = g.loc[sessions[d]] if sessions[d] in g.index else None
                if rr is None or pd.isna(rr["fut_next_expiry"]):
                    ok = False
                    break
                c = es(rr["fut_next_expiry"])
                prev = settle(d, c)
                ok = prev is not None
                rolled = True
        if not ok:
            skipped += 1
            continue
        n_roll += rolled
        diffs.append(abs(V - fut[k][-1, j]))
    diffs = np.array(diffs)
    return {"sampled_name_windows": len(picks), "checked": int(diffs.size), "checked_with_roll": int(n_roll),
            "skipped_gap_or_flat": skipped, "max_abs_diff_exit_value": float(diffs.max()) if diffs.size else None,
            "share_abs_diff_gt_1e_9": float((diffs > 1e-9).mean()) if diffs.size else None,
            "seed": sb.SEED}


# --------------------------------------------------------------------------- statistics
def wmean(x: np.ndarray, e: np.ndarray) -> float:
    return float((e * x).sum() / e.sum())


def drawdown_dates(x: np.ndarray, e: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    """Peak, trough and recovery sessions of the largest drawdown of the fixed-capital NAV (sb.series_stats' NAV)."""
    nav = np.cumprod(1.0 + e * x)
    run = np.maximum.accumulate(nav)
    tr = int(np.argmin(nav / run - 1.0))
    pk = int(np.argmax(nav[:tr + 1]))
    rec = np.flatnonzero(nav[tr:] >= nav[pk])
    return {"max_dd_peak": str(dates[pk].date()), "max_dd_trough": str(dates[tr].date()),
            "max_dd_recovered": str(dates[tr + rec[0]].date()) if rec.size else None}


def dimson_beta(x: np.ndarray, m: np.ndarray, m_lag: np.ndarray, e: np.ndarray) -> dict:
    X = np.column_stack([np.ones_like(m), m, m_lag])
    W = e[:, None]
    coef = np.linalg.solve(X.T @ (W * X), X.T @ (e * x))
    return {"beta_dimson": float(coef[1] + coef[2]), "lag0": float(coef[1]), "lag1": float(coef[2])}


def seg_stats(cal, seg: str, DL, DS, DSb, R, Rg, nifty: np.ndarray) -> dict:
    cols, e = cal.cols[seg], cal.expo[seg]
    codes, draws = cal.month_codes[seg], cal.draws[seg]
    xl, xs, xb = cal.seg_series(DL, seg), cal.seg_series(DS, seg), cal.seg_series(DSb, seg)
    x = xl + xs
    day_idx = cal.pos0 + 2 + cols                       # session index of each P&L day
    m, m1 = nifty[day_idx], nifty[day_idx - 1]
    st = sb.series_stats(x, e, codes, draws, rf=RF)
    st0 = sb.series_stats(x, e, codes, draws, rf=0.0)
    ba = sb.beta_alpha(x, m, e)
    dj = dimson_beta(x, m, m1, e)
    t = sb.tranche_stats(R, Rg, H=H)
    dd = drawdown_dates(x, e, cal.day_dates[cols])
    return {"ann_net_return": st["ann_mean_daily"], "ann_return_tranche": t["ann_return_252_h"],
            "ann_excess_over_rf": st["ann_mean_daily"] - RF, "ann_vol": st["ann_vol"],
            "sharpe": st["sharpe"], "sharpe_ci95": st["sharpe_ci95"], "p_sharpe_gt0": st["p_sharpe_gt0"],
            "sharpe_rf0": st0["sharpe"], "sharpe_rf0_ci95": st0["sharpe_ci95"],
            "max_dd": st["max_dd"], **dd, "cum_return_fixed_capital": st["cum_return_fixed_capital"],
            "n_days": st["n_days"], "n_month_blocks": st["n_month_blocks"], "mean_exposure": st["mean_exposure"],
            "beta_plain": ba["beta_vs_benchmark"], "alpha_ann_plain": ba["alpha_ann"],
            "beta_dimson": dj["beta_dimson"], "beta_dimson_lag0": dj["lag0"], "beta_dimson_lag1": dj["lag1"],
            "beta_long_leg_dimson": dimson_beta(xl, m, m1, e)["beta_dimson"],
            "beta_short_leg_dimson": dimson_beta(xs, m, m1, e)["beta_dimson"],
            "long_leg_ann": PPY * wmean(xl, e), "short_leg_ann": PPY * wmean(xs, e),
            "short_leg_basis_ann": PPY * wmean(xb, e),
            "mean_tranche_net": t["mean_net_h"], "hit_rate_tranches_net_positive": t["hit_rate_net_positive"],
            "n_tranches": t["n_tranches"]}


def by_year(cal, DL, DS, nifty: np.ndarray) -> dict:
    seg = "combined"
    cols, e = cal.cols[seg], cal.expo[seg]
    xl, xs = cal.seg_series(DL, seg), cal.seg_series(DS, seg)
    x = xl + xs
    day_idx = cal.pos0 + 2 + cols
    yrs = cal.day_dates[cols].year
    out = {}
    for y in sorted(set(yrs)):
        k = yrs == y
        if e[k].sum() <= 0 or k.sum() < 20:
            continue
        mu, sd, _, _, _ = sb.wmoments(x[k], e[k])
        out[str(y)] = {"sessions": int(k.sum()), "mean_exposure": float(e[k].mean()),
                       "ann_net_return": mu * PPY, "sharpe": (mu - RF / PPY) / sd * math.sqrt(PPY) if sd > 0 else None,
                       "long_leg_ann": PPY * wmean(xl[k], e[k]), "short_leg_ann": PPY * wmean(xs[k], e[k]),
                       "beta_plain": sb.beta_alpha(x[k], nifty[day_idx[k]], e[k])["beta_vs_benchmark"]}
    return out


def increments(Lp, Sp, Spot, tl, ts, rollf, nextm, variant: str):
    incL = np.diff(Lp, axis=1)
    incS = -np.diff(Sp, axis=1)
    incB = np.diff(Spot, axis=1) - np.diff(Sp, axis=1)          # short futures minus short cash: basis, cost-free
    if variant == "gross":
        return incL, incS, incB
    if variant == "net":
        lb, ls_, sbuy, ssell = tl["buy"], tl["sell"], ts["buy"], ts["sell"]
        overlap_roll = C_ROLL * (1.0 - ts["buy"]) * nextm
    elif variant == "no_netting":
        lb = ls_ = sbuy = ssell = np.ones(len(Lp))
        overlap_roll = np.zeros(len(Lp))
    else:
        raise ValueError(variant)
    incL[:, 0] -= C_LONG * lb
    incL[:, -1] -= C_LONG * ls_
    incS[:, 0] -= C_SHORT * sbuy + overlap_roll
    incS[:, -1] -= C_SHORT * ssell
    incS -= C_ROLL * rollf
    return incL, incS, incB


def run_book(name: str, sc: np.ndarray, blocks, lblocks, sblocks, spblocks, rolls, binfo, eng, nifty,
             var_sr: float) -> dict:
    """blocks: the engine's blocks (membership); lblocks: the long-leg value paths used for the daily marks."""
    cal, n_tick = eng.cal, eng.n_tick
    mem_l, mem_s = [], []
    for b in blocks:
        s = sc[b.rows]
        o = E._order(s, b.ci, np.isfinite(s))
        k = max(1, int(round(QUINT * o.size)))
        mem_l.append(o[:k])
        mem_s.append(o[-k:])
    Lp, Wl, size_l = sb.leg(lblocks, mem_l, n_tick, H)
    Sp, Ws, size_s = sb.leg(sblocks, mem_s, n_tick, H)
    Spot, _, _ = sb.leg(spblocks, mem_s, n_tick, H)
    tl, ts = sb.trade_fracs(Wl, H), sb.trade_fracs(Ws, H)
    rollf = np.array([rolls[k][:, m].mean(axis=1) for k, m in enumerate(mem_s)])
    nextm = np.array([float(x["next_month_entry"]) for x in binfo])
    month_of = np.array([b.month for b in blocks])
    segs, months, yrs = {s: {} for s in sb.SEGMENTS}, None, None
    dsr = {}
    for v in VARIANTS:
        incL, incS, incB = increments(Lp, Sp, Spot, tl, ts, rollf, nextm, v)
        DL, DS, DB = cal.to_days(incL), cal.to_days(incS), cal.to_days(incB)
        R = incL.sum(1) + incS.sum(1)
        Rg = (Lp[:, -1] - 1.0) - (Sp[:, -1] - 1.0)
        for seg in sb.SEGMENTS:
            m = cal.masks[seg]
            segs[seg][v] = seg_stats(cal, seg, DL, DS, DB, R[m], Rg[m], nifty)
        if v == "net":
            exc = pd.Series(R - RF * H / PPY).groupby(month_of).mean()
            raw = pd.Series(R).groupby(month_of).mean()
            months = {"n_months": int(len(exc)), "months_positive_excess_over_rf": int((exc > 0).sum()),
                      "months_positive_net": int((raw > 0).sum()), "share_months_positive_excess": float((exc > 0).mean()),
                      "metric": "mean net (costs) tranche return by signal month; excess = minus rf over 20 sessions",
                      "monthly_net": {k_: float(x_) for k_, x_ in raw.items()}}
            yrs = by_year(cal, DL, DS, nifty)
            x = cal.seg_series(DL, "combined") + cal.seg_series(DS, "combined")
            e = cal.expo["combined"]
            dsr[str(N_TRIALS)] = sb.dsr_block(x - RF / PPY, e, var_sr, N_TRIALS, f"{name} net daily minus rf", PPY)
            dsr["rf0_for_information"] = sb.dsr_block(x, e, var_sr, N_TRIALS, f"{name} net daily, rf 0", PPY)
    c = segs["combined"]["net"]
    p = {"sharpe": c["sharpe"], "sharpe_ci95": c["sharpe_ci95"], "beta_plain": c["beta_plain"],
         "beta_dimson": c["beta_dimson"], "sharpe_ge_1": bool(c["sharpe"] >= 1.0),
         "ci_lower_gt_0": bool(c["sharpe_ci95"][0] > 0),
         "beta_plain_within_0_2": bool(abs(c["beta_plain"]) <= 0.2),
         "beta_dimson_within_0_2": bool(abs(c["beta_dimson"]) <= 0.2)}
    p["pass"] = bool(p["sharpe_ge_1"] and p["ci_lower_gt_0"] and p["beta_plain_within_0_2"] and p["beta_dimson_within_0_2"])
    usize = np.array([len(b.ci) for b in blocks])
    return {"key": f"{MODEL}|{BOOKS[name]}|fo_ls_quintile_futures", "book": name, "neutralisation": BOOKS[name],
            "n_signal_dates": len(blocks), "universe_size_mean": float(usize.mean()),
            "names_long_mean": float(size_l.mean()), "names_short_mean": float(size_s.mean()),
            "turnover_per_rebalance_long": float(np.nanmean(tl["buy_raw"])),
            "turnover_per_rebalance_short": float(np.nanmean(ts["buy_raw"])),
            "turnover_annualised_long": float(np.nanmean(tl["buy_raw"])) * PPY / H,
            "turnover_annualised_short": float(np.nanmean(ts["buy_raw"])) * PPY / H,
            "rolls_per_tranche_mean": float(rollf.sum(1).mean()),
            "share_tranches_entering_next_month": float(nextm.mean()),
            "capacity_long_leg": sb.capacity(Wl, blocks, H),
            "capacity_short_names_cash_adv_indicative": sb.capacity(Ws, blocks, H),
            "segments": segs, "months": months, "by_year": yrs, "dsr": dsr, "pass_mark": p,
            "_mem": (mem_l, mem_s)}


# --------------------------------------------------------------------------- context (not trials)
def context_books(eng, blocks, scs: dict, codes, y_raw, direction) -> dict:
    out = {}
    for name, sc in scs.items():
        top, bot = [], []
        for b in blocks:
            s = sc[b.rows]
            o = E._order(s, b.ci, np.isfinite(s))
            k = max(1, int(round(QUINT * o.size)))
            top.append((o[:k], None))
            bot.append((o[-k:], None))
        for basket, mem in (("top_quintile", top), ("bottom_quintile", bot)):
            r = eng.run_members(mem, basket)
            s = C.summarize(f"{MODEL}|{BOOKS[name]}|fo_{basket}", r, eng,
                            {"scorer": MODEL, "neutralisation": BOOKS[name], "basket": basket}, direction)
            mon = pd.Series(s["monthly_net_20bps"])
            s["by_year_per_tranche_all"] = {y: float(v) for y, v in mon.groupby(mon.index.str[:4]).mean().items()}
            keep = ("key", "neutralisation", "basket", "n_signal_dates", "basket_size_mean", "turnover_per_rebalance",
                    "capacity", "breakeven_flat_cost_bps_per_side", "name_level_trade_weighted_cost_bps_per_side",
                    "months_positive", "n_months", "by_year_per_tranche_all")
            d = {k: s[k] for k in keep}
            d["combined"] = {ck: s["segments"]["combined"][ck] for ck in ("gross", "20bps", E.NAME_KEY)}
            d["cv_20bps"], d["holdout_20bps"] = s["segments"]["cv"]["20bps"], s["segments"]["holdout"]["20bps"]
            out[f"{name}|{basket}"] = d
        out[f"{name}|rank_ic_y_raw_20d_within_fo"] = C.per_date_spearman(codes, sc, y_raw)
    b = eng.bench["ew_universe"]
    x = eng.cal.seg_series(b["D"], "combined")
    e = eng.cal.expo["combined"]
    st = sb.series_stats(x, e, eng.cal.month_codes["combined"], eng.cal.draws["combined"], rf=RF)
    out["ew_fo_universe"] = {"ann_mean_daily": st["ann_mean_daily"], "sharpe_rf_5_5": st["sharpe"], "ann_vol": st["ann_vol"],
                             "turnover_per_rebalance": b["turnover"]}
    return out


# --------------------------------------------------------------------------- report
def f_pct(x, d=1):
    return "n/a" if x is None or not np.isfinite(x) else f"{100 * x:+.{d}f}%"


def f_num(x, d=2):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:+.{d}f}"


def write_md(res: dict, md_path: Path) -> None:
    head = md_path.read_text() if md_path.exists() else ""
    tail = head[head.index(MD_END) + len(MD_END):] if MD_END in head else "\n"
    if MD_MARKER in head:
        head = head[:head.index(MD_MARKER)]
    L = [MD_MARKER + " (written by ml/improve/fo_ls.py from fo_ls.json; everything above this line was fixed before any result) -->", ""]
    L += ["## 2. Results", "",
          f"Signal dates {res['calendar']['first_signal']} to {res['calendar']['last_signal']} ({res['calendar']['n_signal_dates']}), "
          f"P&L sessions to {res['calendar']['last_pnl_session']}. Universe: {res['data']['universe']['universe_rows_per_date_mean']:.0f} "
          f"F&O names per date on average ({res['data']['universe']['universe_tickers']} stocks over the sample). "
          f"Costs: long {1e4 * C_LONG:.0f} bps per side, short {1e4 * C_SHORT:.0f} bps per side + {1e4 * C_ROLL:.0f} bps per roll. "
          f"Sharpe uses rf {100 * RF:.1f}% (FO_LS.md §1.6 D4). DSR at N = {N_TRIALS}, V[SR] = {res['var_sr_daily']:.5f}.", ""]
    L += ["### 2.1 Pass mark", "",
          "| Book | Net Sharpe [95% CI] | Sharpe ≥ 1.0 | CI lower > 0 | Beta plain | Beta Dimson | Both within ±0.2 | Verdict |",
          "|---|---|---|---|---:|---:|---|---|"]
    for name in BOOKS:
        p = res["books"][name]["pass_mark"]
        L.append(f"| {name} | {f_num(p['sharpe'])} [{f_num(p['sharpe_ci95'][0])}, {f_num(p['sharpe_ci95'][1])}] | "
                 f"{'yes' if p['sharpe_ge_1'] else 'no'} | {'yes' if p['ci_lower_gt_0'] else 'no'} | "
                 f"{f_num(p['beta_plain'])} | {f_num(p['beta_dimson'])} | "
                 f"{'yes' if p['beta_plain_within_0_2'] and p['beta_dimson_within_0_2'] else 'no'} | "
                 f"**{'PASS' if p['pass'] else 'FAIL'}** |")
    L += ["", "### 2.2 The two books (all signal dates, net of costs unless stated)", "",
          "| | plain | neutral |", "|---|---:|---:|"]
    rows = [
        ("Annualised net return", lambda b: f_pct(b["segments"]["combined"]["net"]["ann_net_return"])),
        ("  of which long leg (net)", lambda b: f_pct(b["segments"]["combined"]["net"]["long_leg_ann"])),
        ("  of which short leg (net, incl. basis and rolls)", lambda b: f_pct(b["segments"]["combined"]["net"]["short_leg_ann"])),
        ("  short leg's basis convergence (gross)", lambda b: f_pct(b["segments"]["combined"]["net"]["short_leg_basis_ann"])),
        ("Annualised gross return", lambda b: f_pct(b["segments"]["combined"]["gross"]["ann_net_return"])),
        ("Annualised net, no netting", lambda b: f_pct(b["segments"]["combined"]["no_netting"]["ann_net_return"])),
        ("Annualised volatility", lambda b: f"{100 * b['segments']['combined']['net']['ann_vol']:.1f}%"),
        ("Sharpe, rf 5.5% [95% CI]", lambda b: f"{f_num(b['segments']['combined']['net']['sharpe'])} "
                                               f"[{f_num(b['segments']['combined']['net']['sharpe_ci95'][0])}, "
                                               f"{f_num(b['segments']['combined']['net']['sharpe_ci95'][1])}]"),
        ("Sharpe, rf 0 [95% CI]", lambda b: f"{f_num(b['segments']['combined']['net']['sharpe_rf0'])} "
                                            f"[{f_num(b['segments']['combined']['net']['sharpe_rf0_ci95'][0])}, "
                                            f"{f_num(b['segments']['combined']['net']['sharpe_rf0_ci95'][1])}]"),
        ("Gross Sharpe, rf 5.5%", lambda b: f_num(b["segments"]["combined"]["gross"]["sharpe"])),
        ("Max drawdown (fixed capital); peak → trough", lambda b: f"{f_pct(b['segments']['combined']['net']['max_dd'])}; "
                                                                  f"{b['segments']['combined']['net']['max_dd_peak']} → "
                                                                  f"{b['segments']['combined']['net']['max_dd_trough']}"),
        ("Max drawdown gross; peak → trough", lambda b: f"{f_pct(b['segments']['combined']['gross']['max_dd'])}; "
                                                        f"{b['segments']['combined']['gross']['max_dd_peak']} → "
                                                        f"{b['segments']['combined']['gross']['max_dd_trough']}"),
        ("Months positive (excess over rf)", lambda b: f"{b['months']['months_positive_excess_over_rf']}/{b['months']['n_months']}"),
        ("Months positive (net > 0)", lambda b: f"{b['months']['months_positive_net']}/{b['months']['n_months']}"),
        ("Beta to Nifty 50, plain", lambda b: f_num(b["segments"]["combined"]["net"]["beta_plain"])),
        ("Beta to Nifty 50, Dimson (lag 0 + lag 1)", lambda b: f_num(b["segments"]["combined"]["net"]["beta_dimson"])),
        ("  long leg / short leg Dimson beta", lambda b: f"{f_num(b['segments']['combined']['net']['beta_long_leg_dimson'])} / "
                                                         f"{f_num(b['segments']['combined']['net']['beta_short_leg_dimson'])}"),
        ("Turnover per rebalance, long / short", lambda b: f"{100 * b['turnover_per_rebalance_long']:.0f}% / "
                                                          f"{100 * b['turnover_per_rebalance_short']:.0f}%"),
        ("Rolls per tranche; tranches entering next month", lambda b: f"{b['rolls_per_tranche_mean']:.2f}; "
                                                                      f"{100 * b['share_tranches_entering_next_month']:.0f}%"),
        ("Names per leg (long / short); universe", lambda b: f"{b['names_long_mean']:.1f} / {b['names_short_mean']:.1f}; "
                                                             f"{b['universe_size_mean']:.0f}"),
        ("Holdout (2026-08..09) net Sharpe", lambda b: f_num(b["segments"]["holdout"]["net"]["sharpe"])),
        (f"DSR (N = {N_TRIALS})", lambda b: f"{b['dsr'][str(N_TRIALS)]['dsr']:.3f}"),
    ]
    for lab, fn in rows:
        L.append(f"| {lab} | {fn(res['books']['plain'])} | {fn(res['books']['neutral'])} |")
    sr0 = res["books"]["plain"]["dsr"][str(N_TRIALS)]["sr0_expected_max_annualised"]
    L += ["", f"The expected best null Sharpe at N = {N_TRIALS} and V[SR] = {res['var_sr_daily']:.5f} is {sr0:.2f} a year.", ""]
    L += ["### 2.3 By year (calendar year of the P&L session; net)", "",
          "| Year | plain: net / Sharpe / long / short / beta | neutral: net / Sharpe / long / short / beta |", "|---|---|---|"]
    yrs = sorted(set(res["books"]["plain"]["by_year"]) | set(res["books"]["neutral"]["by_year"]))
    for y in yrs:
        cells = []
        for name in BOOKS:
            r = res["books"][name]["by_year"].get(y)
            cells.append("n/a" if r is None else f"{f_pct(r['ann_net_return'])} / {f_num(r['sharpe'])} / "
                                                 f"{f_pct(r['long_leg_ann'])} / {f_pct(r['short_leg_ann'])} / {f_num(r['beta_plain'])}")
        L.append(f"| {y} | {cells[0]} | {cells[1]} |")
    cx = res["context"]
    L += ["", "### 2.4 Context (not trials): long-only F&O quintiles vs the equal-weight F&O universe (cash)", "",
          "| Score | Basket | Excess vs EW F&O, 20 bps | IR [95% CI] | Name-level cost excess | Months beating EW | Turnover |",
          "|---|---|---:|---|---:|---:|---:|"]
    for name in BOOKS:
        for bk in ("top_quintile", "bottom_quintile"):
            d = cx[f"{name}|{bk}"]
            c, cn = d["combined"]["20bps"], d["combined"][E.NAME_KEY]
            L.append(f"| {name} | {bk} | {f_pct(c['excess_ann_vs_ew'])} | {f_num(c['ir'])} [{f_num(c['ir_ci95'][0])}, "
                     f"{f_num(c['ir_ci95'][1])}] | {f_pct(cn['excess_ann_vs_ew'])} | {d['months_positive']}/{d['n_months']} | "
                     f"{100 * d['turnover_per_rebalance']:.0f}% |")
    ew = cx["ew_fo_universe"]
    L += ["", f"Equal-weight F&O universe: {f_pct(ew['ann_mean_daily'])} a year, Sharpe (rf 5.5%) {f_num(ew['sharpe_rf_5_5'])}. "
              f"Rank IC with y_raw_20d inside the F&O universe: plain {f_num(cx['plain|rank_ic_y_raw_20d_within_fo'], 3)}, "
              f"neutral {f_num(cx['neutral|rank_ic_y_raw_20d_within_fo'], 3)}. "
              f"Beta check on the cash EW F&O universe: with the engine's open marks plain {f_num(res['beta_sanity']['ew_fo_universe_beta_plain'])}, "
              f"Dimson {f_num(res['beta_sanity']['ew_fo_universe_beta_dimson'])}; with interior close marks (A2) plain "
              f"{f_num(res['beta_sanity']['ew_fo_universe_close_marks_beta_plain'])}, Dimson "
              f"{f_num(res['beta_sanity']['ew_fo_universe_close_marks_beta_dimson'])}.", ""]
    L += ["### 2.5 Sensitivity: the long leg on the engine's open-to-open marks (the convention before amendment A2)", "",
          "Tranche returns are identical to the primary books; only the daily marks, and so the daily statistics, differ.", "",
          "| Book | Net Sharpe [95% CI] | Ann. vol | Beta plain | Beta Dimson | Max DD | DSR | Verdict under the same rule |",
          "|---|---|---:|---:|---:|---:|---:|---|"]
    for name in BOOKS:
        so = res["sensitivity_open_marks"][name]
        c = so["combined"]["net"]
        L.append(f"| {name} | {f_num(c['sharpe'])} [{f_num(c['sharpe_ci95'][0])}, {f_num(c['sharpe_ci95'][1])}] | "
                 f"{100 * c['ann_vol']:.1f}% | {f_num(c['beta_plain'])} | {f_num(c['beta_dimson'])} | {f_pct(c['max_dd'])} | "
                 f"{so['dsr']['dsr']:.3f} | {'PASS' if so['pass_mark']['pass'] else 'FAIL'} |")
    L.append("")
    dd = res["data"]
    u, fg, sp = dd["universe"], dd["futures"], dd["short_paths"]
    L += ["### 2.6 Data accounting", "",
          f"- F&O member rows among the scored rows: {u['fo_member_rows']:,} of {u['scored_rows']:,}; excluded: entry contract not listed "
          f"{u['excluded_entry_contract_not_listed']:,}, price-break flag in window {u['excluded_price_break_flag_in_window']:,}, "
          f"off-calendar contract in window {u['excluded_off_calendar_contract_in_window']:,} (any window rule "
          f"{u['excluded_any_window_rule']:,}); universe {u['universe_rows']:,} rows, of which "
          f"{u['diagnostic_futures_cash_gap_in_window_kept']:,} have a futures/cash gap above "
          f"{100 * BREAK_TOL:.0f} points inside the window (kept, amendment A1).",
          f"- Futures file: {fg['stocks']} stocks; sessions imputed {[x['session'] for x in fg['sessions_missing_from_futures_file_imputed']]}; "
          f"off-calendar rows {fg['off_calendar_rows']} ({', '.join(fg['off_calendar_stocks'])}); break sessions "
          f"{fg['break_screen']['break_sessions']} of {fg['break_screen']['comparisons']:,} comparisons.",
          f"- Short paths: {sp['name_windows']:,} name-windows; entry settle back-filled {sp['entry_settle_backfilled']}, never quoted "
          f"(flat) {sp['entry_never_quoted_flat']}; settles carried forward {sp['settle_carried_forward']}; names flat after a final "
          f"settlement with no roll target {sp['names_flat_after_final_settlement']}; exiting tranche not in the next entry's near "
          f"contract {sp['exiting_tranche_contract_not_near_at_next_entry']}.",
          f"- Long paths: exit mark matches the label on {100 * dd['long_paths']['exit_mark_matches_label_frac']:.3f}% of rows; entry "
          f"open back-filled {dd['long_paths']['entry_open_backfilled']}; interior close marks carried forward "
          f"{dd['long_paths']['interior_marks_unavailable_carried']}.",
          f"- Nifty 50 sessions missing on the price calendar (forward-filled): {dd['nifty_missing_sessions']}."]
    ic, sc_ = dd["independent_short_check"], dd["split_bonus_check"]
    L += [f"- Independent recomputation of the short leg (seeded sample of {ic['sampled_name_windows']} name-windows, "
          f"straight from each stock's raw futures rows without the common calendar): {ic['checked']} checked "
          f"({ic['checked_with_roll']} with a roll, {ic['skipped_gap_or_flat']} skipped for a gap or a flat tail), "
          f"largest difference in the exit value {ic['max_abs_diff_exit_value']:.1e}.",
          f"- Split/bonus adjustment of the futures: {sc_['events']} validated ex-dates of F&O stocks with quotes on both "
          f"sides; the unadjusted settle moves by a median {100 * sc_['median_abs_unadjusted_futures_return']:.0f}% on the "
          f"ex-date, the adjusted settle stays within {100 * sc_['max_abs_gap_adjusted_futures_vs_cash']:.1f} points of "
          f"the adjusted cash close ({100 * sc_['share_gap_gt_2pt']:.1f}% of events above 2 points).", ""]
    tr = res["sensitivity_total_return"]
    dm = tr["dividends"]
    L += ["### 2.7 Sensitivity added after the results of record: dividends (total return)", "",
          "This sensitivity was added after §2.1-2.6 existed. It changes no convention, book or pass mark. "
          "The primary long leg is price-only (the engine's convention) and the futures short owes no dividends, so "
          "the book misses the long leg's dividends. Separately, NSE adjusts a stock-futures contract on the ex-date "
          "of a large dividend, and the unadjusted settle chain books that adjustment as a gain to the short. "
          "The sensitivity corrects both. Cash dividends with ex-date t+2..t+21 are credited to the long leg. "
          "On contracts classified as adjusted, the dividend is added back to the ex-date settle. "
          f"Rule: {dm['rule']}.", "",
          f"- Dividend events of F&O stocks with a parsed amount: {100 * dm['share_events_with_amount']:.1f}% "
          f"({dm['events_with_amount_in_span']:,} in the price span). Events at or above 2% of price: "
          f"{dm['events_ge_2pct_of_price']}, of which {dm['events_ge_2pct_not_fo_member']} fall outside the stock's F&O "
          f"membership (no short exposure possible) and {dm['events_ge_2pct_member_unclassifiable']} are members without "
          f"a quote on one side or with a split the same day (left unadjusted). Classified as adjusted contracts: "
          f"{dm['futures_adjusted_events']}. By year (member events at or above 2% / classified adjusted): "
          + ", ".join(f"{y} {v['member_events_ge_2pct']}/{v['futures_adjusted']}" for y, v in dm["by_year_ge_2pct"].items())
          + ".",
          f"- Cross-check: the dividend credit of the equal-weight F&O universe is "
          f"{f_pct(dm['ew_fo_universe_dividend_credit_ann'], 2)} a year. The Nifty 50's own dividend yield "
          f"averages {f_pct(dm['nifty50_div_yield_mean_over_pnl_sessions'], 2)} over the same sessions.", "",
          "| Book | Net ann. | Long-leg dividends | Short-leg add-back | Net Sharpe [95% CI] | Sharpe rf 0 | "
          "Beta plain / Dimson | DSR | Verdict under the same rule |",
          "|---|---:|---:|---:|---|---:|---|---:|---|"]
    for name in BOOKS:
        t_ = tr[name]
        c = t_["combined"]["net"]
        L.append(f"| {name} | {f_pct(c['ann_net_return'])} | {f_pct(t_['long_leg_dividend_credit_ann'], 2)} | "
                 f"{f_pct(t_['short_leg_adjusted_dividend_addback_ann'], 2)} | {f_num(c['sharpe'])} "
                 f"[{f_num(c['sharpe_ci95'][0])}, {f_num(c['sharpe_ci95'][1])}] | {f_num(c['sharpe_rf0'])} | "
                 f"{f_num(c['beta_plain'])} / {f_num(c['beta_dimson'])} | {t_['dsr']['dsr']:.3f} | "
                 f"{'PASS' if t_['pass_mark']['pass'] else 'FAIL'} |")
    L.append("")
    md_path.write_text(head + "\n".join(L) + "\n" + MD_END + tail)


# --------------------------------------------------------------------------- main
def main() -> None:
    global _LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="three folds (2019-01..2019-03), outputs to fo_ls/smoke/")
    a = ap.parse_args()
    out = OUT / "smoke" if a.smoke else OUT
    out.mkdir(parents=True, exist_ok=True)
    _LOG = out / "log.txt"
    _LOG.write_text("")
    var_sr = float(json.loads(BOOKS_JSON.read_text())["dsr_common"]["var_sr_daily_across_66_books"])
    base, score, smeta = load_panel(a.smoke)
    raw = D.read_price_parquet()
    sessions = pd.DatetimeIndex(sorted(raw.loc[raw["date"] >= PRICE_START, "date"].unique()))
    log(f"base {len(base):,} scored rows, {base['date'].nunique()} signal dates; {len(sessions)} price sessions")
    G = futures_grid(sessions)
    log(f"futures grid: {G.meta['stocks']} stocks, imputed {G.meta['sessions_missing_from_futures_file_imputed']}, "
        f"off-calendar {G.meta['off_calendar_rows']}, breaks {G.meta['break_screen']['break_sessions']}")
    keep, uinfo = universe_mask(base, G, sessions)
    base_fo = base[keep].reset_index(drop=True)
    sc_plain = score[keep]
    log(f"F&O universe: {uinfo['universe_rows']:,} rows, {uinfo['universe_rows_per_date_mean']:.1f} per date")
    sessions_, tick, O, adv20 = D.load_prices(base_fo, raw)
    assert sessions_.equals(sessions)
    blocks, check = sb.build_blocks(base_fo, sessions, tick, O, adv20)
    fut, spot, rolls, binfo, scnt = short_paths(blocks, tick, G)
    sblocks = [dataclasses.replace(b, path=P) for b, P in zip(blocks, fut)]
    spblocks = [dataclasses.replace(b, path=P) for b, P in zip(blocks, spot)]
    cblocks, cinfo = close_marked(blocks, sessions, tick, O, raw)          # A2
    check = {**check, **cinfo}
    log(f"blocks {len(blocks)}; long exit/label match {check['exit_mark_matches_label_frac']:.5f}; short paths {scnt}; "
        f"close marks {cinfo}")
    comp = D.cost_components(raw, sessions, tick, adv20)
    eng = E.BookEngine(blocks, sessions, len(tick), H, comp)
    # ---- Nifty 50 close-to-close on the price calendar
    ix = pd.read_parquet(INDEX_PARQUET, columns=["date", "index_name", "close", "div_yield"])
    ix = ix[ix["index_name"] == NIFTY].copy()
    ix["date"] = pd.to_datetime(ix["date"])
    nc = ix.set_index("date")["close"].sort_index()
    nifty_missing = [str(d.date()) for d in sessions if d not in nc.index]
    ncl = nc.reindex(sessions).ffill()
    nifty = (ncl / ncl.shift(1) - 1.0).fillna(0.0).to_numpy(float)
    # ---- scores
    dates = np.unique(base_fo["date"].to_numpy())
    codes = np.searchsorted(dates, base_fo["date"].to_numpy())
    atr, lt = base_fo["atr_pct"].to_numpy(float), base_fo["log_turnover"].to_numpy(float)
    scs = {"plain": E.neutralise(sc_plain, "none", codes, atr, lt, None),
           "neutral": E.neutralise(sc_plain, "vol+size", codes, atr, lt, None)}
    corr = {n: {"spearman_atr_pct": C.per_date_spearman(codes, s, atr),
                "spearman_log_turnover": C.per_date_spearman(codes, s, lt)} for n, s in scs.items()}
    books, sens = {}, {}
    for name, sc in scs.items():
        r = run_book(name, sc, blocks, cblocks, sblocks, spblocks, rolls, binfo, eng, nifty, var_sr)
        r.pop("_mem")
        r["score_corr_within_fo"] = corr[name]
        books[name] = r
        so = run_book(name, sc, blocks, blocks, sblocks, spblocks, rolls, binfo, eng, nifty, var_sr)
        sens[name] = {"long_marks": "engine open-to-open (convention of FO_LS.md 1.3 before amendment A2)",
                      "combined": {v: so["segments"]["combined"][v] for v in VARIANTS},
                      "holdout_net": so["segments"]["holdout"]["net"], "dsr": so["dsr"][str(N_TRIALS)],
                      "months": {k: so["months"][k] for k in ("n_months", "months_positive_excess_over_rf", "months_positive_net")},
                      "pass_mark": so["pass_mark"]}
        sens[name]["tranche_returns_identical_to_primary"] = bool(abs(
            so["segments"]["combined"]["net"]["mean_tranche_net"] - r["segments"]["combined"]["net"]["mean_tranche_net"]) < 1e-12)
        log(f"{name} [open-marks sensitivity]: Sharpe {so['segments']['combined']['net']['sharpe']:+.2f} beta "
            f"{so['segments']['combined']['net']['beta_plain']:+.3f} / Dimson {so['segments']['combined']['net']['beta_dimson']:+.3f} "
            f"-> {'PASS' if so['pass_mark']['pass'] else 'FAIL'}")
        c = r["segments"]["combined"]["net"]
        log(f"{name}: net {c['ann_net_return']:+.4f}/yr (long {c['long_leg_ann']:+.4f}, short {c['short_leg_ann']:+.4f}, "
            f"basis {c['short_leg_basis_ann']:+.4f}) Sharpe {c['sharpe']:+.2f} {[round(x, 2) for x in c['sharpe_ci95']]} "
            f"beta {c['beta_plain']:+.3f} / Dimson {c['beta_dimson']:+.3f} DSR {r['dsr'][str(N_TRIALS)]['dsr']:.3f} "
            f"-> {'PASS' if r['pass_mark']['pass'] else 'FAIL'}")
    month_of = np.array([b.month for b in blocks])
    ew_R = eng.bench["ew_universe"]["R"]
    direction = {mo: ("up" if ew_R[month_of == mo].mean() > 0 else "down") for mo in sorted(set(month_of))}
    ctx = context_books(eng, blocks, scs, codes, base_fo["y_raw_20d"].to_numpy(float), direction)
    # beta estimator check on the cash EW F&O universe (open-to-open marks, beta near 1 expected)
    cal = eng.cal
    xe = cal.seg_series(eng.bench["ew_universe"]["D"], "combined")
    di = cal.pos0 + 2 + cal.cols["combined"]
    ee = cal.expo["combined"]
    allm = [np.arange(len(b.ci)) for b in blocks]
    Lc, _, _ = sb.leg(cblocks, allm, len(tick), H)
    xc = cal.seg_series(cal.to_days(np.diff(Lc, axis=1)), "combined")
    beta_sanity = {"ew_fo_universe_beta_plain": sb.beta_alpha(xe, nifty[di], ee)["beta_vs_benchmark"],
                   "ew_fo_universe_beta_dimson": dimson_beta(xe, nifty[di], nifty[di - 1], ee)["beta_dimson"],
                   "ew_fo_universe_close_marks_beta_plain": sb.beta_alpha(xc, nifty[di], ee)["beta_vs_benchmark"],
                   "ew_fo_universe_close_marks_beta_dimson": dimson_beta(xc, nifty[di], nifty[di - 1], ee)["beta_dimson"],
                   "note": "cash equal-weight F&O universe against the Nifty 50 close-to-close return. With the engine's "
                           "open-to-open marks the same-session beta understates the exposure and the Dimson sum recovers "
                           "it; with interior close marks (amendment A2) the two estimators should agree"}
    log(f"context: top quintile plain excess {ctx['plain|top_quintile']['combined']['20bps']['excess_ann_vs_ew']:+.4f}, "
        f"neutral {ctx['neutral|top_quintile']['combined']['20bps']['excess_ann_vs_ew']:+.4f}; beta check {beta_sanity}")
    # ---- checks and the total-return sensitivity (added after the results of record; FO_LS.md 2.7)
    ichk = independent_short_check(blocks, tick, fut, sessions)
    schk = split_check(G, sessions)
    log(f"independent short-path check {ichk}; split check {schk}")
    DV, FA, dmeta = dividends(sessions, G)
    cblocks_tr = with_dividends(cblocks, tick, G, O, DV)
    fut_tr = short_paths(blocks, tick, G, div_add=FA)[0]
    sblocks_tr = [dataclasses.replace(b, path=P) for b, P in zip(blocks, fut_tr)]
    Ltr, _, _ = sb.leg(cblocks_tr, allm, len(tick), H)
    ndy = ix.set_index("date").reindex(cal.day_dates)["div_yield"]
    dmeta["ew_fo_universe_dividend_credit_ann"] = float((Ltr[:, H] - Lc[:, H]).mean() * PPY / H)
    dmeta["nifty50_div_yield_mean_over_pnl_sessions"] = float(ndy.mean() / 100.0)
    tr = {"note": "added after the results of record existed; changes no convention, book or pass mark",
          "long_leg": "cash dividends with ex-date session t+2..t+21 credited per rupee of entry (not reinvested)",
          "short_leg": "on contracts NSE adjusted for a dividend, the dividend is added back to the ex-date settle",
          "dividends": dmeta}
    for name, sc in scs.items():
        so = run_book(name, sc, blocks, cblocks_tr, sblocks_tr, spblocks, rolls, binfo, eng, nifty, var_sr)
        c, c0 = so["segments"]["combined"]["net"], books[name]["segments"]["combined"]["net"]
        tr[name] = {"combined": {v: {k: so["segments"]["combined"][v][k] for k in
                                     ("ann_net_return", "ann_vol", "sharpe", "sharpe_ci95", "sharpe_rf0", "sharpe_rf0_ci95",
                                      "beta_plain", "beta_dimson", "long_leg_ann", "short_leg_ann", "max_dd")}
                                 for v in VARIANTS},
                    "long_leg_dividend_credit_ann": c["long_leg_ann"] - c0["long_leg_ann"],
                    "short_leg_adjusted_dividend_addback_ann": c["short_leg_ann"] - c0["short_leg_ann"],
                    "dsr": so["dsr"][str(N_TRIALS)], "pass_mark": so["pass_mark"],
                    "months": {k: so["months"][k] for k in ("n_months", "months_positive_excess_over_rf", "months_positive_net")}}
        log(f"{name} [total-return sensitivity]: net {c['ann_net_return']:+.4f} Sharpe {c['sharpe']:+.2f} "
            f"{[round(v, 2) for v in c['sharpe_ci95']]} beta {c['beta_plain']:+.3f} -> "
            f"{'PASS' if so['pass_mark']['pass'] else 'FAIL'}")
    res = {
        "stream": "Q4", "title": "Market-neutral long-short on F&O names via stock futures",
        "plan": "ml/IMPROVEMENT_PLAN_2.md section 2 Q4", "conventions": "ml/results/improve2/fo_ls/FO_LS.md section 1",
        "smoke": a.smoke, "seed": sb.SEED, "n_trials": N_TRIALS, "var_sr_daily": var_sr, "var_sr_source": rel(BOOKS_JSON),
        "rf_annual": RF, "costs": {"long_bps_per_side": 1e4 * C_LONG, "short_bps_per_side": 1e4 * C_SHORT,
                                   "roll_bps": 1e4 * C_ROLL,
                                   "netting": "long netted as the engine; short netted where the exiting and entering tranche "
                                              "hold the same contract, the overlap pays a roll (10 bps) where they hold different "
                                              "contracts; no_netting variant charges every tranche in full"},
        "rules": {"quintile": QUINT, "next_month_if_sessions_to_expiry_lt": NEXT_IF_LT, "hold_sessions": H,
                  "break_tolerance": BREAK_TOL, "beta_estimators": ["plain same-session", "Dimson lag 0 + lag 1"]},
        "inputs": {"preds": rel(PREDS_10Y / f"{MODEL}__beat_mkt_20d.parquet"), "dataset": rel(DATA_10Y / "model_dataset.parquet"),
                   "prices": rel(PRICES), "futures": rel(FO_PARQUET), "index": rel(INDEX_PARQUET), "index_name": NIFTY,
                   "corporate_actions_feed": rel(CA_FEED), "price_break_flags": rel(BREAK_FLAGS), "scores_meta": smeta},
        "calendar": {"n_signal_dates": len(blocks), "first_signal": str(blocks[0].date.date()),
                     "last_signal": str(blocks[-1].date.date()),
                     "last_pnl_session": str(cal.day_dates[-1].date()), "n_months": len(set(month_of))},
        "data": {"universe": uinfo, "futures": G.meta, "short_paths": scnt, "long_paths": check,
                 "nifty_missing_sessions": nifty_missing, "independent_short_check": ichk,
                 "split_bonus_check": schk},
        "amendments": {"A1": "futures/cash break screen kept as a diagnostic, not an exclusion",
                       "A2": "long leg's interior daily marks at adjusted closes (entry and exit at opens unchanged)",
                       "doc": "ml/results/improve2/fo_ls/FO_LS.md section 1.8"},
        "books": books,
        "sensitivity_open_marks": sens,
        "sensitivity_total_return": tr,
        "pass_mark": {"rule": "net annualised Sharpe (rf 5.5%) >= 1.0 with its month-block 95% CI lower bound > 0, and beta to "
                              "the Nifty 50 within +-0.2 on both the plain and the Dimson estimator",
                      **{n: books[n]["pass_mark"] for n in BOOKS}},
        "context": ctx, "beta_sanity": beta_sanity, "runtime_s": time.time() - T0,
    }
    (out / "fo_ls.json").write_text(json.dumps(sb.clean_json(res), indent=1, allow_nan=False) + "\n")
    md = out / "FO_LS.md"
    if a.smoke and not md.exists():
        md.write_text("# Q4 smoke run (three folds; not a result)\n\n")
    write_md(sb.clean_json(res), md)
    log(f"written {rel(out / 'fo_ls.json')} and {rel(md)}")


if __name__ == "__main__":
    main()
