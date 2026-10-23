"""Scoring, baskets and marks of the paper book (ml/paper/SPEC.md 1, 2.2-2.5).

Signals: for each signal date t >= inception, the month model scores every universe row of t; the ensemble is
the mean of the three members' per-date percentile ranks; ml.books.engine.neutralise("vol+size") on the date's
universe; baskets by ml.strategy_backtest.select (score descending, ticker ascending on ties).

Marks: tranche k (signal session p) enters at the open of p+1 and exits at the open of p+21; slot k mod 20.
Session marks per tranche: entry day open->close, then close->close, exit day close->open (adjusted
equity_features prices, last print carried, entry deferred to a name's next print).  Book return of a session =
mean over the active slots of the slot's compounded marks (an exiting and an entering tranche share a slot on
the roll session); exposure = active slots / 20.  Costs: 20 bps per side on ml.strategy_backtest.trade_fracs
traded weight, and the name-level model ml.books.engine.name_cost_fracs, both with 20 empty predecessor
tranches so that the first 20 tranches are bought in full.

Extension 1 (SPEC.md amendment 10): the expanding-window model's score, neutralised the same way on the same universe,
in its own per-date score file (ml/paper/state/scores_expanding/), and the books challenger_expanding (full-universe top
decile) and capacity_expanding (liquid-tercile top decile), marked by the same code with the same benchmarks and costs.
"""
from __future__ import annotations

import types

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books import data as BD
from ml.books import engine as E
from ml.paper.common import (MARKS_COLS, SIGNALS_COLS, fnum, log, read_csv_rows)
from ml.paper.config import (ALL_BOOK_ORDER, ALL_BOOKS, BOOK_ORDER, BOOKS, COST_BPS, COST_PRICE_START, EXT_BOOK_ORDER,
                             EXT_BOOKS, H, INCEPTION_SIGNAL_DATE, LIQ_CUT, STATE_DIR, ext_block)

SCORES_DIR = STATE_DIR / "scores"
SCORES_EXT_DIR = STATE_DIR / "scores_expanding"       # extension 1: per-date expanding-window scores
MEMBERS3 = ("lgbm", "lambdarank", "catboost")
EXT_SCORE_COLS = ["lgbm_expanding", "neutral_lgbm_expanding"]


# --------------------------------------------------------------------------- signals
def score_date(rows: pd.DataFrame, mm) -> pd.DataFrame:
    """All universe rows of one signal date with every score the books and monitors need."""
    rows = rows.sort_values("ticker", kind="stable").reset_index(drop=True)
    sc = mm.score(rows)
    codes = np.zeros(len(rows), dtype=np.int64)
    out = rows[["date", "ticker", "cs_rank_turnover", "atr_pct", "log_turnover"]].copy()
    for k, v in sc.items():
        out[k] = np.asarray(v, float)
    ranks = [pd.Series(out[m]).rank(pct=True).to_numpy(float) for m in MEMBERS3]
    out["ensemble"] = np.mean(np.column_stack(ranks), axis=1)
    atr, lt = out["atr_pct"].to_numpy(float), out["log_turnover"].to_numpy(float)
    out["neutral_lgbm"] = E.neutralise(out["lgbm"].to_numpy(float), "vol+size", codes, atr, lt, None)
    out["neutral_ensemble"] = E.neutralise(out["ensemble"].to_numpy(float), "vol+size", codes, atr, lt, None)
    out["liquid"] = out["cs_rank_turnover"].to_numpy(float) >= LIQ_CUT
    out["model_month"] = mm.month
    return out


def book_score(sd: pd.DataFrame, book: str) -> np.ndarray:
    b = BOOKS[book]
    if b["scorer"] == "lgbm":
        col = "neutral_lgbm" if b["neutralisation"] == "vol+size" else "lgbm"
    else:
        col = "neutral_ensemble" if b["neutralisation"] == "vol+size" else "ensemble"
    return sd[col].to_numpy(float)


def baskets(sd: pd.DataFrame) -> dict[str, np.ndarray]:
    ci = np.arange(len(sd))                         # rows sorted by ticker: ties broken by ticker ascending
    liq = sd["liquid"].to_numpy(bool)
    out = {}
    for book in BOOK_ORDER:
        idx, _ = sb.select(book_score(sd, book), ci, liq, BOOKS[book]["basket"])
        out[book] = idx
    out["ew_universe"] = np.arange(len(sd))
    out["ew_liquid"] = np.flatnonzero(liq)
    return out


def signal_rows(sd: pd.DataFrame, bk: dict, books=BOOK_ORDER, score_of=None) -> list[dict]:
    rows = []
    d = str(pd.Timestamp(sd["date"].iat[0]).date())
    for book in books:
        idx = bk[book]
        s = (score_of or book_score)(sd, book)
        w = 1.0 / len(idx)
        for r, i in enumerate(idx, 1):
            rows.append({"signal_date": d, "book": book, "ticker": sd["ticker"].iat[i], "rank": r,
                         "score": fnum(s[i]), "weight": fnum(w)})
    return rows


# --------------------------------------------------------------------------- extension 1: expanding-window scores
def score_date_ext(rows: pd.DataFrame, mm) -> pd.DataFrame:
    """All universe rows of one signal date with the expanding-window model's raw and neutralised score."""
    rows = rows.sort_values("ticker", kind="stable").reset_index(drop=True)
    sc = mm.score(rows)
    codes = np.zeros(len(rows), dtype=np.int64)
    out = rows[["date", "ticker", "cs_rank_turnover", "atr_pct", "log_turnover"]].copy()
    out["lgbm_expanding"] = np.asarray(sc["lgbm"], float)
    atr, lt = out["atr_pct"].to_numpy(float), out["log_turnover"].to_numpy(float)
    out["neutral_lgbm_expanding"] = E.neutralise(out["lgbm_expanding"].to_numpy(float), "vol+size", codes, atr, lt, None)
    out["liquid"] = out["cs_rank_turnover"].to_numpy(float) >= LIQ_CUT
    out["model_month"] = mm.month
    return out


def book_score_ext(sd: pd.DataFrame, book: str) -> np.ndarray:
    b = EXT_BOOKS[book]
    assert b["scorer"] == "lgbm_expanding"
    return sd["neutral_lgbm_expanding" if b["neutralisation"] == "vol+size" else "lgbm_expanding"].to_numpy(float)


def baskets_ext(sd: pd.DataFrame) -> dict[str, np.ndarray]:
    ci = np.arange(len(sd))
    liq = sd["liquid"].to_numpy(bool)
    return {book: sb.select(book_score_ext(sd, book), ci, liq, EXT_BOOKS[book]["basket"])[0] for book in EXT_BOOK_ORDER}


def signal_rows_ext(sd: pd.DataFrame, bk: dict) -> list[dict]:
    return signal_rows(sd, bk, EXT_BOOK_ORDER, book_score_ext)


def signal_key(r: dict) -> tuple:
    """Ledger order of a signals row (config.SPEC_EXT['ledger_order'])."""
    return (ext_block(r["signal_date"], r["book"]), r["signal_date"], ALL_BOOK_ORDER.index(r["book"]), int(r["rank"]))


def mark_key(r: dict) -> tuple:
    return (ext_block(r["session"], r["book"]), r["session"], ALL_BOOK_ORDER.index(r["book"]))


# --------------------------------------------------------------------------- tranches from the ledger
def tranches_from_ledger(signals_path, sessions: pd.DatetimeIndex, books=BOOK_ORDER) -> dict[str, list[dict]]:
    rows = read_csv_rows(signals_path)
    by = {}
    for r in rows:
        if r["book"] in books:
            by.setdefault((r["book"], r["signal_date"]), []).append(r["ticker"])
    pos = {str(d.date()): i for i, d in enumerate(sessions)}
    out = {b: [] for b in books}
    for (book, d), tick in sorted(by.items(), key=lambda kv: (kv[0][1], ALL_BOOK_ORDER.index(kv[0][0]))):
        out[book].append({"signal_date": d, "p": pos[d], "tickers": tick})
    return out


def benchmark_tranches(signal_dates: list[str], sessions: pd.DatetimeIndex) -> dict[str, list[dict]]:
    pos = {str(d.date()): i for i, d in enumerate(sessions)}
    out = {"ew_universe": [], "ew_liquid": []}
    for d in signal_dates:
        sd = pd.read_parquet(SCORES_DIR / f"scores_{d}.parquet", columns=["ticker", "liquid"])
        out["ew_universe"].append({"signal_date": d, "p": pos[d], "tickers": sd["ticker"].tolist()})
        out["ew_liquid"].append({"signal_date": d, "p": pos[d], "tickers": sd.loc[sd["liquid"], "ticker"].tolist()})
    return out


# --------------------------------------------------------------------------- prices
def price_grid(feat_prices: pd.DataFrame, sessions: pd.DatetimeIndex, tick: np.ndarray) -> np.ndarray:
    """Interleaved (open, close) grid: row 2s = open of session s, row 2s+1 = close; NaN where no print."""
    x = feat_prices[feat_prices["ticker"].isin(set(tick))]
    O = x.pivot(index="date", columns="ticker", values="open").reindex(index=sessions, columns=tick)
    C = x.pivot(index="date", columns="ticker", values="close").reindex(index=sessions, columns=tick)
    G = np.empty((2 * len(sessions), len(tick)))
    G[0::2], G[1::2] = O.to_numpy(float), C.to_numpy(float)
    return G


def tranche_marks(G: np.ndarray, cols: np.ndarray, e: int, x: int, last: int) -> np.ndarray:
    """Gross marks of one equal-weight buy-and-hold tranche on sessions e..min(x, last)."""
    top = min(2 * x, 2 * last + 1)
    R = G[2 * e: top + 1][:, cols]
    ok = np.isfinite(R)
    has = ok.any(axis=0)
    fv = np.where(has, ok.argmax(axis=0), R.shape[0])
    Rf = pd.DataFrame(R).ffill().to_numpy()
    entry = np.where(has, R[np.minimum(fv, R.shape[0] - 1), np.arange(R.shape[1])], np.nan)
    rel = Rf / entry[None, :]
    tt = np.arange(R.shape[0])[:, None]
    rel = np.where((tt >= fv[None, :]) & has[None, :], rel, 1.0)
    rel = np.where(np.isfinite(rel), rel, 1.0)
    V = rel.mean(axis=1)                      # V[0] = 1 at the entry open
    out = []
    for s in range(e, min(x, last) + 1):
        if s == e:
            out.append(V[1] / V[0] - 1.0)
        elif s < x:
            out.append(V[2 * (s - e) + 1] / V[2 * (s - e) - 1] - 1.0)
        else:
            out.append(V[2 * (x - e)] / V[2 * (x - e) - 1] - 1.0)
    return np.array(out)


# --------------------------------------------------------------------------- costs
def weight_matrix(tr: list[dict], col_of: dict) -> np.ndarray:
    W = np.zeros((H + len(tr), len(col_of)))          # H empty predecessors: the first H tranches buy in full
    for k, t in enumerate(tr):
        W[H + k, [col_of[x] for x in t["tickers"]]] = 1.0 / len(t["tickers"])
    return W


def cost_fracs(tr: list[dict], col_of: dict, comp: dict | None, pos_cost: dict) -> dict:
    W = weight_matrix(tr, col_of)
    tf = sb.trade_fracs(W, H)
    n = len(tr)
    has_succ = np.array([k + H < n for k in range(n)])
    out = {"buy20": tf["buy"][H:], "sell20": np.where(has_succ, tf["sell"][H:], np.nan), "has_succ": has_succ,
           "buy_raw": tf["buy_raw"][H:]}
    if comp is not None:
        blocks = [None] * H + [types.SimpleNamespace(pos=pos_cost[t["signal_date"]]) for t in tr]
        size = np.r_[np.ones(H), [len(t["tickers"]) for t in tr]]
        nl = E.name_cost_fracs(W, blocks, size, comp, H)
        out["buy_nl"] = nl["buy"][H:]
        out["sell_nl"] = np.where(has_succ, nl["sell"][H:], np.nan)
        out["nl_trade_weighted_bps"] = nl["trade_weighted_cost_bps_per_side"]
    return out


def cost_inputs(feat_prices: pd.DataFrame, tick: np.ndarray) -> tuple[dict, pd.DatetimeIndex]:
    raw = feat_prices.loc[feat_prices["date"] >= pd.Timestamp(COST_PRICE_START),
                          ["date", "ticker", "open", "high", "low", "close", "turnover"]]
    sessions = pd.DatetimeIndex(sorted(raw["date"].unique()))
    s = raw[raw["ticker"].isin(set(tick))]
    T = s.pivot(index="date", columns="ticker", values="turnover").reindex(index=sessions, columns=tick)
    adv20 = T.rolling(20, min_periods=10).median()
    comp = BD.cost_components(raw, sessions, tick, adv20)
    comp.pop("own", None)
    return comp, sessions


# --------------------------------------------------------------------------- marks
def book_session_marks(tr: list[dict], G: np.ndarray, col_of: dict, last: int, costs: dict | None) -> pd.DataFrame:
    """Per session: mean over active slots of the slot's compounded gross / net-20 bps / name-level marks."""
    recs = []
    c = COST_BPS / 1e4
    for k, t in enumerate(tr):
        e, x = t["p"] + 1, t["p"] + 1 + H
        if e > last:
            continue
        cols = np.array([col_of[z] for z in t["tickers"]])
        r = tranche_marks(G, cols, e, x, last)
        for j, rr in enumerate(r):
            s = e + j
            g = rr
            n20 = nnl = rr
            if costs is not None:
                if s == e:
                    n20 = (1 - c * costs["buy20"][k]) * (1 + rr) - 1
                    nnl = (1 - costs["buy_nl"][k]) * (1 + rr) - 1 if "buy_nl" in costs else np.nan
                if s == x:
                    if not costs["has_succ"][k]:
                        raise SystemExit(f"tranche {t['signal_date']} exits on session {s} but its successor "
                                         "tranche is missing from the ledger")
                    n20 = (1 + (n20 if s == e else rr)) * (1 - c * costs["sell20"][k]) - 1
                    nnl = ((1 + rr) * (1 - costs["sell_nl"][k]) - 1) if "sell_nl" in costs else np.nan
            recs.append((s, k % H, g, n20, nnl))
    if not recs:
        return pd.DataFrame(columns=["s", "gross", "net20", "netnl", "active"])
    d = pd.DataFrame(recs, columns=["s", "slot", "g", "n20", "nnl"])
    slot = d.groupby(["s", "slot"]).agg(g=("g", lambda v: np.prod(1 + v) - 1), n20=("n20", lambda v: np.prod(1 + v) - 1),
                                        nnl=("nnl", lambda v: np.prod(1 + v) - 1)).reset_index()
    out = slot.groupby("s").agg(gross=("g", "mean"), net20=("n20", "mean"), netnl=("nnl", "mean"),
                                active=("slot", "nunique")).reset_index()
    return out


def compute_marks(signals_path, feat_prices: pd.DataFrame, sessions: pd.DatetimeIndex,
                  books=BOOK_ORDER) -> tuple[pd.DataFrame, dict]:
    """Marks of every book on every session from the first entry open to the last stored session.  ``books``: the
    frozen four (default) or ALL_BOOK_ORDER with extension 1.  The benchmark tranches hold every universe name of
    each signal date, so the extension's names add no column to the price and cost grids: the frozen books' marks do
    not depend on whether the extension is computed."""
    trs = tranches_from_ledger(signals_path, sessions, books)
    sig_dates = [t["signal_date"] for t in trs[BOOK_ORDER[0]]]
    if not sig_dates:
        return pd.DataFrame(columns=MARKS_COLS), {}
    for b in books:
        if b in EXT_BOOKS and [t["signal_date"] for t in trs[b]] != sig_dates:
            raise SystemExit(f"book {b}'s signal dates differ from the frozen books' in the ledger "
                             f"({len(trs[b])} vs {len(sig_dates)}); see ml/paper/RUNBOOK.md section 8")
    bts = benchmark_tranches(sig_dates, sessions)
    tick = np.array(sorted({z for v in list(trs.values()) + list(bts.values()) for t in v for z in t["tickers"]}))
    col_of = {t: i for i, t in enumerate(tick)}
    fp = feat_prices[feat_prices["date"] >= sessions[max(min(t["p"] for t in trs[BOOK_ORDER[0]]) - 1, 0)]]
    G = price_grid(fp, sessions, tick)
    last = len(sessions) - 1
    comp, csess = cost_inputs(feat_prices, tick)
    pos_cost = {str(d.date()): i for i, d in enumerate(csess)}
    info = {"books": {}}
    bench = {b: book_session_marks(bts[b], G, col_of, last, None) for b in ("ew_universe", "ew_liquid")}
    rows = []
    for book in books:
        costs = cost_fracs(trs[book], col_of, comp, pos_cost)
        m = book_session_marks(trs[book], G, col_of, last, costs)
        bm = bench[ALL_BOOKS[book]["benchmark"]].set_index("s")
        info["books"][book] = {"tranches": len(trs[book]),
                               "basket_sizes": [len(t["tickers"]) for t in trs[book]],
                               "turnover_per_rebalance_after_inception": [fnum(x, 6) for x in costs["buy_raw"][H:]]
                               if len(trs[book]) > H else [],
                               "name_level_trade_weighted_bps_per_side": costs.get("nl_trade_weighted_bps")}
        for r in m.itertuples(index=False):
            rows.append({"session": str(sessions[int(r.s)].date()), "book": book, "gross_return": r.gross,
                         "net_return_20bps": r.net20, "benchmark_return": float(bm.loc[r.s, "gross"]),
                         "exposure": int(r.active) / H, "net_return_name_level": r.netnl,
                         "_bench_active": int(bm.loc[r.s, "active"]), "_active": int(r.active)})
    df = pd.DataFrame(rows)
    if len(df):
        assert (df["_bench_active"] == df["_active"]).all(), "book and benchmark slots disagree"
        df["_o"] = df["book"].map({b: i for i, b in enumerate(ALL_BOOK_ORDER)})
        df = df.sort_values(["session", "_o"], kind="stable").drop(columns=["_o", "_bench_active", "_active"])
    info["first_entry_session"] = str(sessions[trs[BOOK_ORDER[0]][0]["p"] + 1].date()) \
        if trs[BOOK_ORDER[0]][0]["p"] + 1 <= last else None
    return df.reset_index(drop=True), info


def marks_ledger_rows(df: pd.DataFrame) -> list[dict]:
    return [{"session": r.session, "book": r.book, "gross_return": fnum(r.gross_return),
             "net_return_20bps": fnum(r.net_return_20bps), "benchmark_return": fnum(r.benchmark_return),
             "exposure": fnum(r.exposure), "net_return_name_level": fnum(r.net_return_name_level)}
            for r in df.itertuples(index=False)]


def inception_summary(signals_path, n_top: int = 10, books=BOOK_ORDER) -> dict:
    rows = read_csv_rows(signals_path)
    if not rows:
        return {}
    first = min(r["signal_date"] for r in rows)
    out = {"signal_date": first}
    sp = SCORES_DIR / f"scores_{first}.parquet"
    if sp.exists():
        sd = pd.read_parquet(sp, columns=["ticker", "liquid", "model_month"])
        out["universe"] = int(len(sd))
        out["liquid_tercile"] = int(sd["liquid"].sum())
        out["model_month"] = str(sd["model_month"].iat[0])
    sx = SCORES_EXT_DIR / f"scores_{first}.parquet"
    if any(b in EXT_BOOKS for b in books) and sx.exists():
        out["model_month_expanding"] = str(pd.read_parquet(sx, columns=["model_month"])["model_month"].iat[0])
    for book in books:
        x = [r for r in rows if r["signal_date"] == first and r["book"] == book]
        x.sort(key=lambda r: int(r["rank"]))
        out[book] = {"size": len(x), "top": [{"rank": int(r["rank"]), "ticker": r["ticker"], "score": float(r["score"])}
                                             for r in x[:n_top]]}
    return out


def basket_overlap(signals_path) -> list[dict]:
    """Per signal date: names each extension book shares with the primary book and with its frozen counterpart."""
    from ml.paper.config import EXT_COUNTERPART
    rows = read_csv_rows(signals_path)
    by = {}
    for r in rows:
        by.setdefault((r["signal_date"], r["book"]), set()).add(r["ticker"])
    out = []
    for d in sorted({r["signal_date"] for r in rows}):
        for book in EXT_BOOK_ORDER:
            if (d, book) not in by:
                continue
            x = by[(d, book)]
            rec = {"signal_date": d, "book": book, "names": len(x)}
            for ref in dict.fromkeys(["primary", EXT_COUNTERPART[book]]):
                y = by.get((d, ref), set())
                rec[f"shared_with_{ref}"] = len(x & y)
                rec[f"share_of_book_shared_with_{ref}"] = len(x & y) / len(x) if x else None
                rec[f"names_of_{ref}"] = len(y)
            out.append(rec)
    return out


def score_agreement(signal_dates: list[str]) -> list[dict]:
    """Per signal date: Spearman correlation of the expanding-window score with the primary model's score on the
    date's universe (raw and neutralised)."""
    out = []
    for d in signal_dates:
        a, b = SCORES_DIR / f"scores_{d}.parquet", SCORES_EXT_DIR / f"scores_{d}.parquet"
        if not (a.exists() and b.exists()):
            continue
        x = pd.read_parquet(a, columns=["ticker", "lgbm", "neutral_lgbm"]).merge(
            pd.read_parquet(b, columns=["ticker"] + EXT_SCORE_COLS), on="ticker", validate="one_to_one")
        sp = lambda u, v: float(pd.Series(x[u].to_numpy()).rank().corr(pd.Series(x[v].to_numpy()).rank()))  # noqa: E731
        out.append({"signal_date": d, "universe": int(len(x)), "spearman_raw": sp("lgbm_expanding", "lgbm"),
                    "spearman_neutral": sp("neutral_lgbm_expanding", "neutral_lgbm")})
    return out


__all__ = ["score_date", "baskets", "signal_rows", "compute_marks", "marks_ledger_rows", "inception_summary",
           "score_agreement", "score_date_ext", "baskets_ext", "signal_rows_ext", "signal_key", "mark_key", "basket_overlap",
           "SIGNALS_COLS", "MARKS_COLS", "INCEPTION_SIGNAL_DATE", "log"]
