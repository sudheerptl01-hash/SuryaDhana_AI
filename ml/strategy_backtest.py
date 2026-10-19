#!/usr/bin/env python3
"""Strategy backtest: turn the pilot's out-of-sample scores into portfolios.

Management question: is there a promising return on capital (ROC) in the
pilot's GENUINE out-of-sample signal once costs, turnover, capacity and
multiple testing are accounted for -- and what should be dropped
("bifurcated")?

Engine -- overlapping tranches, exact daily mark-to-market
---------------------------------------------------------
* Signal date t (every session of the OOS windows, 2026-04-01 .. 2026-09-11):
  rank that date's OOS scores and form the day's basket.
* Entry at the OPEN of session t+1, exit at the OPEN of session t+21 -- the
  exact window of the y_raw_20d / y_excess_20d label.
* Capital is split into 20 equal tranches; one tranche rebalances per day.
  Daily portfolio return = equal-weight average of the live tranches' daily
  returns (Jegadeesh-Titman overlapping-portfolio convention; it implicitly
  re-balances the sleeves to equal weight each day).
* Ramp-up / wind-down: in the first and last 19 sessions of a program fewer
  than 20 tranches are live. Every daily statistic (mean, vol, Sharpe,
  bootstrap, skew/kurtosis, DSR) weights a session by its exposure
  e = live tranches / 20, i.e. fixed 1/20 capital per tranche with idle
  capital in cash. Without this the fully-invested live-average series gives
  the first and last tranche 3.6x the weight of a mid-sample tranche (in this
  sample that flips the champion's daily active mean from +4.2% to -5.3%/yr,
  because the first tranches are the adversarial early-April ones). NAV and
  drawdown are those of the fixed-capital program.
* EXACT DAILY MARK-TO-MARKET, not amortisation: every tranche is an
  equal-weighted buy-and-hold basket marked open-to-open from
  ml/data/equity_eod_snapshot.parquet (missing bars forward-filled). These
  marks reproduce y_raw_20d for 99.995% of rows; the exit mark is pinned to
  the label (1 + y_raw_20d) so tranche totals equal the label exactly.
* Truth = the CLEAN dataset (ml/data/model_dataset.parquet, rebuilt after the
  holiday-echo fix) for EVERY model. The frozen pre-fix preds are joined on
  (date, ticker); their own `fwd` column is NOT used: on 78% of rows it
  differs from the clean label (mean |diff| 1.4pp) because those 20-"session"
  windows counted phantom days and, before a phantom day, entered at a stale
  pre-signal open. Signal dates that were phantom days are dropped (NSE was
  closed). Universe = clean-labeled harness rows (y_clean_20d), as in the
  league.

Costs and turnover
------------------
* c in {10, 20, 40} bps PER SIDE (NSE delivery: STT 10 bps/side + stamp,
  exchange, SEBI, GST + brokerage + spread/impact -> ~15-25 bps/side for
  liquid names; 40 bps is a stress level, optimistic for the illiquid tail).
* Netted, steady-state cost model (headline): the tranche exiting at the open
  of session t+1 is the one the new tranche replaces, so only the difference
  is traded. Tranche k pays c x buy_k at entry, buy_k = sum(max(w_k -
  w_{k-20}, 0)) = "fraction of the basket replaced per rebalance" (the
  reported turnover), and c x sell_k at exit, sell_k = sum(max(w_k -
  w_{k+20}, 0)). The 20 tranches at either end of the sample (no neighbour)
  are charged the median steady-state turnover instead of a one-off full
  build/liquidation. Weight drift inside a kept name is ignored.
* Conservative variant "20bps_no_netting": every tranche is fully bought and
  fully sold (2 x 20 bps per tranche, turnover = 100%).
* Long-short: both legs pay the same per-side cost; no borrow fee is charged
  (see the bifurcation note: overnight single-stock shorts on NSE need SLB or
  stock futures, i.e. only the ~200 F&O names).

Metrics (per scorer x basket x cost x segment)
-----------------------------------------------
* Annualised mean return, 252/20 logic made explicit: a tranche is a
  20-session bet, there are 252/20 = 12.6 non-overlapping bets per year, so
  ann_return_252_20 = mean(tranche net 20d return) x 12.6. The daily
  mark-to-market series gives ann_mean_daily = mean(daily) x 252 (the two
  agree up to ramp-up/wind-down weighting), ann_vol = std(daily) x sqrt(252),
  Sharpe = (ann_mean_daily - rf) / ann_vol with rf = 5.5% (approx. 91-day
  T-bill) for absolute long-only returns, rf = 0 for active and long-short
  series. Max drawdown on the daily NAV.
* Hit rate = fraction of tranches whose net 20d return beats the universe
  median (the project's "excess"); hit_rate_vs_ew = vs the equal-weight
  universe (the stricter bar). Average excess vs universe median.
* Month-block bootstrap 95% CI for the Sharpe: calendar months of the daily
  series resampled with replacement, B=1000, seed 108, identical draws for
  every series of a segment (paired).
* Segments by SIGNAL date: cv (Apr-Jul 2026 folds), holdout (2026-08-03 ..
  2026-09-11), combined (all 113 dates; still fully OOS, ~5.5 months of
  signals, P&L runs to 2026-10-14).

Also: universe-median and equal-weight-universe benchmarks, liquid-tercile
capacity test (cs_rank_turnover >= 0.67), regime split by the sign of the
universe-median y_raw_20d per signal month, adversarial-month scan,
Deflated / Probabilistic Sharpe (Bailey & Lopez de Prado), the up_5d label
check, short-leg and illiquid-tail decompositions.

Outputs (ml/results/strategy/ only): strategy.json, champion_monthly.csv,
strategy_flat.csv, tables.md. STRATEGY.md (the verdict) is written by hand
from these outputs.

Run:  cd /home/user/SuryaDhana_AI && python3 -m ml.strategy_backtest
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")  # must precede numpy import

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, rankdata, skew

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"
RESULTS_DIR = ML_DIR / "results"
PREDS_DIR = RESULTS_DIR / "preds"
OUT_DIR = RESULTS_DIR / "strategy"

SEED = 108
HORIZON = 20
PPY = 252
COSTS_BPS = (10, 20, 40)
HEADLINE_COST = 20
RF_ANNUAL = 0.055
LIQ_CUT = 0.67
TOP_FRAC = 0.10
TOP_N = 20
N_BOOT = 1000
PARTICIPATION = 0.05           # capacity: max 5% of 20d median daily turnover per name per trade
N_PROGRAM_CONFIGS = 30         # configurations the program tested on beat_mkt_20d (26 logged + tuning grids)
EULER_GAMMA = 0.5772156649015329
PRICE_START = "2026-01-01"     # snapshot slice (ADV20 warm-up + full label windows)

MODELS = ["lgbm_fs_selected", "lgbm_fs_selected_clean", "random_forest", "xgboost",
          "lr_l2", "baseline_mom", "rl_reinforce", "mlp"]
CHAMPION = "lgbm_fs_selected"
CHAMPION_CLEAN = "lgbm_fs_selected_clean"
ENSEMBLE = "ensemble_rank3"
ENSEMBLE_MEMBERS = ("lgbm_fs_selected", "random_forest", "lr_l2")
HEURISTIC = "heuristic_mom20"
SCORERS = MODELS + [ENSEMBLE, HEURISTIC]
UP5D = "lgbm_fs_selected_up5d"   # diagnostic: champion config trained on the up_5d label
BASKETS = ("top_decile", "top20", "ls_decile", "liq_top_decile", "liq_top20", "liq_ls_decile")
SEGMENTS = ("cv", "holdout", "combined")

# Which hyper-parameter / feature choices looked at which test windows
# (from the result JSON notes): used for the "genuine OOS" caveats.
SELECTION_CONTAMINATION = {
    "lgbm_fs_selected": "feature subset + k chosen on all 4 CV test folds (univariate AUC on CV test rows, "
                        "permutation importance on 2026-06 test rows, k by CV mean): only the holdout is untouched",
    "lgbm_fs_selected_clean": "same fixed config as lgbm_fs_selected: only the holdout is untouched",
    "random_forest": "hyper-parameters tuned on CV folds 2026-04 + 2026-05",
    "xgboost": "hyper-parameters tuned on CV folds 2026-04 + 2026-05",
    "mlp": "hyper-parameters tuned on CV folds 2026-04 + 2026-05",
    "lr_l2": "C tuned on CV folds 2026-04 + 2026-05",
    "baseline_mom": "fixed C=1.0, no tuning (clean on every window)",
    "rl_reinforce": "champion's 10 features + 3 (feature list inherited from CV-selected subset)",
    ENSEMBLE: "inherits lgbm_fs_selected / random_forest / lr_l2 contamination",
    HEURISTIC: "parameter-free (clean on every window)",
}

T0 = time.time()


def log(msg: str) -> None:
    print(f"[strategy +{time.time() - T0:5.0f}s] {msg}", flush=True)


# --------------------------------------------------------------------------- data
def load_base() -> tuple[pd.DataFrame, dict]:
    cols = ["date", "ticker", "log_turnover", "cs_rank_turnover", "cs_rank_mom_20",
            "y_raw_20d", "y_excess_20d", "label_beat_mkt_20d", "y_clean_20d"]
    d = pd.read_parquet(DATA_DIR / "model_dataset.parquet", columns=cols)
    d["date"] = pd.to_datetime(d["date"])
    splits = json.loads((DATA_DIR / "splits.json").read_text())
    wins = [(f["name"], f["test_start"], f["test_end"]) for f in splits["folds"]]
    wins.append(("holdout", splits["holdout"]["test_start"], splits["holdout"]["test_end"]))
    fold = pd.Series(pd.NA, index=d.index, dtype="object")
    for name, a, b in wins:
        fold[(d["date"] >= a) & (d["date"] <= b)] = name
    d["fold"] = fold
    m = d["fold"].notna() & d["label_beat_mkt_20d"].notna() & d["y_clean_20d"].astype(bool)
    base = d[m].sort_values(["date", "ticker"]).reset_index(drop=True)
    base["segment"] = np.where(base["fold"] == "holdout", "holdout", "cv")
    base["mkt_med"] = base["y_raw_20d"] - base["y_excess_20d"]   # universe median y_raw_20d of the date
    base["month"] = base["date"].dt.strftime("%Y-%m")
    return base, splits


def load_scores(base: pd.DataFrame) -> tuple[dict, dict]:
    key = base[["date", "ticker"]]
    scores, coverage = {}, {}

    def join(path: Path) -> np.ndarray:
        p = pd.read_parquet(path, columns=["date", "ticker", "score"])
        p["date"] = pd.to_datetime(p["date"])
        return key.merge(p, on=["date", "ticker"], how="left")["score"].to_numpy(float)

    for m in MODELS:
        scores[m] = join(PREDS_DIR / f"{m}__beat_mkt_20d.parquet")
    scores[UP5D] = join(PREDS_DIR / "lgbm_fs_selected__up_5d.parquet")
    # rank-average ensemble: per-date percentile rank of each member, averaged
    g = base["date"]
    ranks = [pd.Series(scores[m]).groupby(g.values).rank(pct=True).to_numpy() for m in ENSEMBLE_MEMBERS]
    scores[ENSEMBLE] = np.mean(np.vstack(ranks), axis=0)          # NaN if any member missing
    scores[HEURISTIC] = base["cs_rank_mom_20"].to_numpy(float)
    for k, v in scores.items():
        coverage[k] = {"rows_scored": int(np.isfinite(v).sum()), "frac_of_universe": float(np.isfinite(v).mean())}
    return scores, coverage


def load_prices(base: pd.DataFrame):
    s = pd.read_parquet(DATA_DIR / "equity_eod_snapshot.parquet", columns=["date", "ticker", "open", "turnover"])
    s["date"] = pd.to_datetime(s["date"])
    s = s[s["date"] >= PRICE_START]
    sessions = pd.DatetimeIndex(sorted(s["date"].unique()))
    tick = np.array(sorted(base["ticker"].unique()))
    s = s[s["ticker"].isin(tick)]
    O = s.pivot(index="date", columns="ticker", values="open").reindex(index=sessions, columns=tick)
    T = s.pivot(index="date", columns="ticker", values="turnover").reindex(index=sessions, columns=tick)
    adv20 = T.rolling(20, min_periods=10).median()   # PIT: trailing 20 sessions up to and incl. t
    return sessions, tick, O, adv20


@dataclass
class Block:
    date: pd.Timestamp
    pos: int               # session index of the signal date
    segment: str
    fold: str
    month: str
    rows: np.ndarray       # base row indices
    ci: np.ndarray         # ticker column indices
    path: np.ndarray       # (21, n) open-to-open relative price path, path[0] = 1, path[20] = 1 + y_raw_20d
    y_exc: np.ndarray
    med: float             # universe median y_raw_20d (dataset definition)
    liq: np.ndarray        # cs_rank_turnover >= 0.67
    tercile: np.ndarray    # 0 illiquid / 1 mid / 2 liquid (cs_rank_turnover)
    adv: np.ndarray        # 20d median daily turnover (Rs) at t


def build_blocks(base, sessions, tick, O, adv20) -> tuple[list[Block], dict]:
    col_of = {t: j for j, t in enumerate(tick)}
    pos_of = {d: i for i, d in enumerate(sessions)}
    Ov = O.to_numpy(float)
    Of = O.ffill().to_numpy(float)
    Ob = O.bfill().to_numpy(float)
    Av = adv20.to_numpy(float)
    blocks, n_entry_bfill, n_path_check, n_path_match = [], 0, 0, 0
    for date, grp in base.groupby("date", sort=True):
        p = pos_of[date]
        rows = grp.index.to_numpy()
        ci = grp["ticker"].map(col_of).to_numpy()
        entry = Ov[p + 1, ci]
        miss = ~np.isfinite(entry)
        n_entry_bfill += int(miss.sum())
        entry = np.where(miss, Ob[p + 1, ci], entry)
        path = Of[p + 1:p + 1 + HORIZON + 1, ci] / entry[None, :]
        path[0] = 1.0
        y_raw = grp["y_raw_20d"].to_numpy(float)
        ok = np.isfinite(path[HORIZON])
        n_path_check += int(ok.sum())
        n_path_match += int((np.abs(path[HORIZON][ok] - (1 + y_raw[ok])) < 1e-6).sum())
        path[HORIZON] = 1.0 + y_raw                                   # pin exit to the label
        path = pd.DataFrame(path).ffill().fillna(1.0).to_numpy()      # residual gaps
        ctr = grp["cs_rank_turnover"].to_numpy(float)
        blocks.append(Block(
            date=date, pos=p, segment=grp["segment"].iat[0], fold=grp["fold"].iat[0],
            month=grp["month"].iat[0], rows=rows, ci=ci, path=path,
            y_exc=grp["y_excess_20d"].to_numpy(float), med=float(grp["mkt_med"].iat[0]),
            liq=ctr >= LIQ_CUT, tercile=np.where(ctr >= LIQ_CUT, 2, np.where(ctr >= 0.33, 1, 0)),
            adv=Av[p, ci]))
    pos = np.array([b.pos for b in blocks])
    assert np.all(np.diff(pos) == 1), "signal dates must be consecutive sessions"
    check = {"rows": int(sum(len(b.rows) for b in blocks)), "entry_open_backfilled": n_entry_bfill,
             "exit_mark_matches_label_frac": n_path_match / max(n_path_check, 1)}
    return blocks, check


# --------------------------------------------------------------------------- baskets
def select(score: np.ndarray, ci: np.ndarray, liq: np.ndarray, kind: str):
    """Return (long_idx, short_idx|None) local indices for one date."""
    valid = np.isfinite(score)
    if kind.startswith("liq_"):
        valid &= liq
        kind = kind[4:]
    cand = np.flatnonzero(valid)
    if kind == "all":
        return cand, None
    order = cand[np.lexsort((ci[cand], -score[cand]))]       # score desc, ticker asc
    n = order.size
    if kind == "top20":
        return order[:min(TOP_N, n)], None
    k = max(1, int(round(TOP_FRAC * n)))
    if kind == "top_decile":
        return order[:k], None
    if kind == "ls_decile":
        return order[:k], order[-k:]
    if kind == "bottom_decile":
        return order[-k:], None
    raise ValueError(kind)


def leg(blocks: list[Block], members: list[np.ndarray], n_tick: int, H: int):
    n = len(blocks)
    L = np.ones((n, H + 1))
    W = np.zeros((n, n_tick), dtype=np.float64)
    size = np.zeros(n)
    for k, (b, idx) in enumerate(zip(blocks, members)):
        L[k] = b.path[:H + 1, idx].mean(axis=1)
        W[k, b.ci[idx]] = 1.0 / len(idx)
        size[k] = len(idx)
    return L, W, size


def trade_fracs(W: np.ndarray, H: int):
    """buy_k = sum max(w_k - w_{k-H}, 0) (fraction replaced); sell_k = sum max(w_k - w_{k+H}, 0)."""
    n = W.shape[0]
    buy = np.full(n, np.nan)
    sell = np.full(n, np.nan)
    if n > H:
        d = W[H:] - W[:-H]
        buy[H:] = np.clip(d, 0, None).sum(1)
        sell[:-H] = np.clip(-d, 0, None).sum(1)
    churn = np.clip(W[1:] - W[:-1], 0, None).sum(1) if n > 1 else np.array([np.nan])
    ss_buy = float(np.nanmedian(buy)) if np.isfinite(buy).any() else 1.0
    ss_sell = float(np.nanmedian(sell)) if np.isfinite(sell).any() else 1.0
    return {"buy": np.where(np.isfinite(buy), buy, ss_buy), "sell": np.where(np.isfinite(sell), sell, ss_sell),
            "buy_raw": buy, "churn": churn}


def long_net(L, buy, sell, c):
    V = L * (1.0 - c * buy)[:, None]
    V[:, -1] *= (1.0 - c * sell)
    prev = np.concatenate([np.ones((len(L), 1)), V[:, 1:-1]], axis=1)
    return V[:, 1:] / prev - 1.0, V[:, -1] - 1.0


def ls_net(Lp, Sp, tl, ts, c):
    inc = np.diff(Lp, axis=1) - np.diff(Sp, axis=1)
    inc[:, 0] -= c * (tl["buy"] + ts["buy"])
    inc[:, -1] -= c * (tl["sell"] + ts["sell"])
    return inc, inc.sum(1)


def gross_daily(L):
    return L[:, 1:] / L[:, :-1] - 1.0, L[:, -1] - 1.0


# --------------------------------------------------------------------------- calendar / stats
class Calendar:
    """Maps tranche daily returns onto sessions and defines segments + bootstrap draws."""

    def __init__(self, blocks: list[Block], sessions: pd.DatetimeIndex, H: int):
        self.H = H
        self.pos = np.array([b.pos for b in blocks])
        self.pos0 = self.pos[0]
        self.n_days = int(self.pos[-1] - self.pos0 + H)
        self.day_dates = sessions[self.pos0 + 2: self.pos0 + 2 + self.n_days]
        assert len(self.day_dates) == self.n_days, "price calendar too short for the last exit"
        self.seg_of = np.array([b.segment for b in blocks])
        self.masks = {"cv": self.seg_of == "cv", "holdout": self.seg_of == "holdout",
                      "combined": np.ones(len(blocks), bool)}
        rng = np.random.default_rng(SEED)
        self.cols, self.month_codes, self.draws, self.months = {}, {}, {}, {}
        for s, m in self.masks.items():
            k = np.flatnonzero(m)
            c0, c1 = self.pos[k[0]] - self.pos0, self.pos[k[-1]] - self.pos0 + H - 1
            cols = np.arange(c0, c1 + 1)
            mon = self.day_dates[cols].strftime("%Y-%m")
            uniq = sorted(set(mon))
            codes = np.array([uniq.index(x) for x in mon])
            self.cols[s], self.month_codes[s], self.months[s] = cols, codes, uniq
            self.draws[s] = rng.integers(0, len(uniq), size=(N_BOOT, len(uniq)))
            # exposure of each session = live tranches of this segment / H (fixed 1/H capital per tranche)
            live = np.zeros(self.n_days)
            for kk in k:
                c = self.pos[kk] - self.pos0
                live[c:c + H] += 1
            self.expo = getattr(self, "expo", {})
            self.expo[s] = live[cols] / H

    def to_days(self, r: np.ndarray) -> np.ndarray:
        D = np.full((r.shape[0], self.n_days), np.nan)
        cols = (self.pos - self.pos0)[:, None] + np.arange(self.H)[None, :]
        np.put_along_axis(D, cols, r, axis=1)
        return D

    def seg_series(self, D: np.ndarray, seg: str) -> np.ndarray:
        sub = D[self.masks[seg]][:, self.cols[seg]]
        cnt = np.isfinite(sub).sum(0)
        return np.nansum(sub, 0) / np.maximum(cnt, 1)


def wmoments(x: np.ndarray, e: np.ndarray) -> tuple[float, float, float, float, float]:
    """Exposure-weighted mean, std (reliability-weight corrected), skew, Pearson kurtosis, Kish n_eff."""
    E = e.sum()
    mu = float((e * x).sum() / E)
    d = x - mu
    m2 = float((e * d ** 2).sum() / E)
    n_eff = float(E ** 2 / (e ** 2).sum())
    sd = math.sqrt(m2 * n_eff / max(n_eff - 1.0, 1.0))
    g3 = float((e * d ** 3).sum() / E / m2 ** 1.5) if m2 > 0 else float("nan")
    g4 = float((e * d ** 4).sum() / E / m2 ** 2) if m2 > 0 else float("nan")
    return mu, sd, g3, g4, n_eff


def beta_alpha(x: np.ndarray, xb: np.ndarray, e: np.ndarray) -> dict:
    """Exposure-weighted OLS of the daily series on the benchmark's daily series."""
    E = e.sum()
    mx, mb = (e * x).sum() / E, (e * xb).sum() / E
    vb = (e * (xb - mb) ** 2).sum() / E
    beta = float((e * (x - mx) * (xb - mb)).sum() / E / vb) if vb > 0 else float("nan")
    resid = x - beta * xb
    mr = (e * resid).sum() / E
    sr = math.sqrt((e * (resid - mr) ** 2).sum() / E)
    return {"beta_vs_benchmark": beta, "alpha_ann": float(mr * PPY),
            "alpha_ir": float(mr / sr * math.sqrt(PPY)) if sr > 0 else float("nan")}


def series_stats(x: np.ndarray, e: np.ndarray, codes: np.ndarray, draws: np.ndarray, rf: float = 0.0) -> dict:
    """Daily mark-to-market stats. Each session is weighted by its exposure e = live tranches / 20 so that every
    tranche counts equally (a fully-invested live-average series would give the first/last tranche 3.6x weight).
    NAV / drawdown = the fixed-capital program (1/20 per tranche, idle capital in cash at 0)."""
    xe = x - rf / PPY
    mu, sd, _, _, n_eff = wmoments(xe, e)
    mu_raw = mu + rf / PPY
    nav = np.cumprod(1.0 + e * x)
    out = {"n_days": int(len(x)), "n_eff_days": n_eff, "mean_exposure": float(e.mean()),
           "ann_mean_daily": float(mu_raw * PPY), "ann_vol": float(sd * math.sqrt(PPY)),
           "sharpe": float(mu / sd * math.sqrt(PPY)) if sd > 0 else float("nan"),
           "max_dd": float((nav / np.maximum.accumulate(nav) - 1.0).min()),
           "cum_return_fixed_capital": float(nav[-1] - 1.0), "rf_used": rf}
    M = int(codes.max()) + 1
    E_m = np.bincount(codes, weights=e, minlength=M)
    S_m = np.bincount(codes, weights=e * xe, minlength=M)
    Q_m = np.bincount(codes, weights=e * xe ** 2, minlength=M)
    n_m = np.bincount(codes, minlength=M).astype(float)
    E, S, Q, N = E_m[draws].sum(1), S_m[draws].sum(1), Q_m[draws].sum(1), n_m[draws].sum(1)
    m = S / E
    var = np.maximum((Q / E - m ** 2) * N / np.maximum(N - 1, 1), 1e-18)
    sh = m / np.sqrt(var) * math.sqrt(PPY)
    out["sharpe_ci95"] = [float(np.percentile(sh, 2.5)), float(np.percentile(sh, 97.5))]
    out["p_sharpe_gt0"] = float((sh > 0).mean())
    out["n_month_blocks"] = M
    out["ci_note"] = ("degenerate: fewer than 5 month blocks, CI not informative" if M < 5 else "ok")
    return out


def tranche_stats(Rnet, Rgross, med=None, Rbench=None, H=HORIZON) -> dict:
    sd = Rnet.std(ddof=1)
    o = {"n_tranches": int(len(Rnet)), "mean_gross_h": float(Rgross.mean()), "mean_net_h": float(Rnet.mean()),
         "ann_return_252_h": float(Rnet.mean() * PPY / H), "std_net_h": float(sd),
         "sharpe_tranche_naive": float(Rnet.mean() / sd * math.sqrt(PPY / H)) if sd > 0 else float("nan"),
         "hit_rate_net_positive": float((Rnet > 0).mean())}
    if med is not None:
        exc = Rnet - med
        o.update({"excess_vs_median_gross": float((Rgross - med).mean()), "excess_vs_median_net": float(exc.mean()),
                  "hit_rate": float((exc > 0).mean())})
    if Rbench is not None:
        act = Rnet - Rbench
        o.update({"active_vs_ew_net_h": float(act.mean()), "active_ann_252_h": float(act.mean() * PPY / H),
                  "hit_rate_vs_ew": float((act > 0).mean())})
    return o


def capacity(W: np.ndarray, blocks: list[Block], H: int) -> dict:
    """AUM at which the 10th-percentile entering name trades at PARTICIPATION x ADV20."""
    caps, adv_med, small = [], [], []
    for k in range(H, len(blocks)):
        b = blocks[k]
        adv_full = np.full(W.shape[1], np.nan)
        adv_full[b.ci] = b.adv
        dw = W[k] - W[k - H]
        buys = np.flatnonzero(dw > 1e-12)
        held = np.flatnonzero(W[k] > 0)
        if held.size:
            a = adv_full[held]
            adv_med.append(np.nanmedian(a))
            small.append(np.nanmean(a < 5e7))
        if buys.size:
            A = H * PARTICIPATION * adv_full[buys] / dw[buys]
            if np.isfinite(A).any():
                caps.append(np.nanpercentile(A, 10))
    return {"aum_cap_rs_crore_p10name_5pct_adv": float(np.median(caps) / 1e7) if caps else None,
            "median_name_adv20_rs_crore": float(np.median(adv_med) / 1e7) if adv_med else None,
            "share_names_adv20_below_5cr": float(np.mean(small)) if small else None}


# --------------------------------------------------------------------------- programs
class Engine:
    def __init__(self, blocks, sessions, n_tick, H):
        self.blocks, self.n_tick, self.H = blocks, n_tick, H
        self.cal = Calendar(blocks, sessions, H)
        self.med = np.array([b.med for b in blocks]) if H == HORIZON else np.array(
            [np.median(b.path[H] - 1.0) for b in blocks])
        self.bench = {}
        for name, kind in (("ew_universe", "all"), ("ew_liquid", "liq_all")):
            mem = [select(np.zeros(len(b.ci)), b.ci, b.liq, kind)[0] for b in blocks]
            L, W, size = leg(blocks, mem, n_tick, H)
            r, R = gross_daily(L)
            self.bench[name] = {"L": L, "r": r, "R": R, "D": self.cal.to_days(r), "size": size,
                                "turnover": float(np.nanmean(trade_fracs(W, H)["buy_raw"]))}

    def bench_for(self, basket: str) -> str:
        return "ew_liquid" if basket.startswith("liq_") else "ew_universe"

    def run(self, scores: np.ndarray, basket: str, costs=COSTS_BPS, with_capacity=True) -> dict:
        H, blocks, cal = self.H, self.blocks, self.cal
        is_ls = basket.endswith("ls_decile")
        mem = [select(scores[b.rows], b.ci, b.liq, basket) for b in blocks]
        Lp, Wl, size_l = leg(blocks, [m[0] for m in mem], self.n_tick, H)
        tl = trade_fracs(Wl, H)
        out = {"basket_size_mean": float(size_l.mean()),
               "turnover_per_rebalance": float(np.nanmean(tl["buy_raw"])),
               "daily_churn": float(np.nanmean(tl["churn"])), "_mem": mem, "_tranche": {}}
        if is_ls:
            Sp, Ws, _ = leg(blocks, [m[1] for m in mem], self.n_tick, H)
            ts = trade_fracs(Ws, H)
            out["turnover_per_rebalance_short"] = float(np.nanmean(ts["buy_raw"]))
            out["capacity"] = capacity(Wl, blocks, H) if with_capacity else None
            out["capacity_short_leg"] = capacity(Ws, blocks, H) if with_capacity else None
        else:
            out["capacity"] = capacity(Wl, blocks, H) if with_capacity else None
        bname = self.bench_for(basket)
        bench = self.bench[bname]
        out["benchmark"] = bname
        res = {}
        variants = [("gross", 0.0, False)] + [(f"{c}bps", c / 1e4, False) for c in costs] + \
                   [(f"{HEADLINE_COST}bps_no_netting", HEADLINE_COST / 1e4, True)]
        Rgross_l = Lp[:, -1] - 1.0
        for key, c, nonet in variants:
            if is_ls:
                tl_c = {"buy": np.ones_like(tl["buy"]), "sell": np.ones_like(tl["sell"])} if nonet else tl
                ts_c = {"buy": np.ones_like(ts["buy"]), "sell": np.ones_like(ts["sell"])} if nonet else ts
                r, R = ls_net(Lp, Sp, tl_c, ts_c, c)
                Rg = Rgross_l - (Sp[:, -1] - 1.0)
            else:
                buy = np.ones_like(tl["buy"]) if nonet else tl["buy"]
                sell = np.ones_like(tl["sell"]) if nonet else tl["sell"]
                r, R = long_net(Lp, buy, sell, c)
                Rg = Rgross_l
            D = cal.to_days(r)
            res[key] = {}
            for seg in SEGMENTS:
                m = cal.masks[seg]
                x = cal.seg_series(D, seg)
                codes, draws, ex = cal.month_codes[seg], cal.draws[seg], cal.expo[seg]
                xb = cal.seg_series(bench["D"], seg)
                if is_ls:
                    ent = {"tranche": tranche_stats(R[m], Rg[m], H=H),
                           "daily": series_stats(x, ex, codes, draws, rf=0.0),
                           "beta_alpha_vs_benchmark": beta_alpha(x, xb, ex)}
                else:
                    ent = {"tranche": tranche_stats(R[m], Rg[m], self.med[m], bench["R"][m], H=H),
                           "daily": series_stats(x, ex, codes, draws, rf=RF_ANNUAL),
                           "daily_active": series_stats(x - xb, ex, codes, draws, rf=0.0),
                           "beta_alpha_vs_benchmark": beta_alpha(x, xb, ex)}
                res[key][seg] = ent
            out["_tranche"][key] = {"R": R, "Rg": Rg}
        out["results"] = res
        return out


# --------------------------------------------------------------------------- DSR / PSR
def psr(sr: float, sr_star: float, T: int, g3: float, g4: float) -> float:
    den = 1.0 - g3 * sr + (g4 - 1.0) / 4.0 * sr ** 2
    return float(norm.cdf((sr - sr_star) * math.sqrt(T - 1) / math.sqrt(max(den, 1e-12))))


def expected_max_sr(var_sr: float, N: int) -> float:
    return float(math.sqrt(var_sr) * ((1 - EULER_GAMMA) * norm.ppf(1 - 1.0 / N)
                                      + EULER_GAMMA * norm.ppf(1 - 1.0 / (N * math.e))))


def min_trl(sr: float, sr_star: float, g3: float, g4: float, alpha: float = 0.05) -> float:
    if sr <= sr_star:
        return float("inf")
    return float(1 + (1 - g3 * sr + (g4 - 1) / 4 * sr ** 2) * (norm.ppf(1 - alpha) / (sr - sr_star)) ** 2)


def dsr_block(x: np.ndarray, e: np.ndarray, var_sr: float, N: int, label: str, periods_per_year: float) -> dict:
    mu, sd, g3, g4, n_eff = wmoments(x, e)
    sr = float(mu / sd)
    T = int(round(n_eff))
    sr0 = expected_max_sr(var_sr, N)
    return {"series": label, "T_periods": T, "T_note": "Kish effective number of exposure-weighted daily obs",
            "n_days_raw": int(len(x)), "periods_per_year": periods_per_year,
            "sr_per_period": sr, "sr_annualised": sr * math.sqrt(periods_per_year),
            "skew": g3, "kurtosis_pearson": g4, "n_trials": N, "var_sr_across_trials": var_sr,
            "sr0_expected_max_per_period": sr0, "sr0_expected_max_annualised": sr0 * math.sqrt(periods_per_year),
            "psr_vs_0": psr(sr, 0.0, T, g3, g4), "dsr": psr(sr, sr0, T, g3, g4),
            "min_track_record_periods_psr95_vs_0": min_trl(sr, 0.0, g3, g4),
            "min_track_record_periods_dsr95": min_trl(sr, sr0, g3, g4)}


# --------------------------------------------------------------------------- analyses
def date_ic(score: np.ndarray, y: np.ndarray) -> float:
    v = np.isfinite(score)
    if v.sum() < 50:
        return float("nan")
    return float(np.corrcoef(rankdata(score[v]), rankdata(y[v]))[0, 1])


def clean_json(o):
    """NaN/inf -> None, numpy scalars -> Python (strict JSON)."""
    if isinstance(o, dict):
        return {str(k): clean_json(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_json(v) for v in o]
    if isinstance(o, np.ndarray):
        return clean_json(o.tolist())
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    return o


def fmt_pct(x, d=1):
    return "n/a" if x is None or not np.isfinite(x) else f"{100 * x:+.{d}f}%"


def fmt(x, d=2):
    return "n/a" if x is None or not np.isfinite(x) else f"{x:+.{d}f}"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base, splits = load_base()
    log(f"base panel: {len(base):,} rows, {base['date'].nunique()} signal dates")
    scores, coverage = load_scores(base)
    sessions, tick, O, adv20 = load_prices(base)
    blocks, path_check = build_blocks(base, sessions, tick, O, adv20)
    log(f"blocks built; exit-mark/label match {path_check['exit_mark_matches_label_frac']:.5f}")

    eng = Engine(blocks, sessions, len(tick), HORIZON)
    cal = eng.cal

    # ---------------- benchmarks
    bench_out = {}
    for name, bd in eng.bench.items():
        bench_out[name] = {"turnover_per_rebalance": bd["turnover"], "names_mean": float(bd["size"].mean())}
        for seg in SEGMENTS:
            m = cal.masks[seg]
            x = cal.seg_series(bd["D"], seg)
            bench_out[name][seg] = {"tranche": tranche_stats(bd["R"][m], bd["R"][m], eng.med[m], H=HORIZON),
                                    "daily": series_stats(x, cal.expo[seg], cal.month_codes[seg], cal.draws[seg],
                                                          rf=RF_ANNUAL)}
    med_out = {}
    for seg in SEGMENTS:
        mm = eng.med[cal.masks[seg]]
        med_out[seg] = {"mean_20d": float(mm.mean()), "ann_return_252_20": float(mm.mean() * PPY / HORIZON),
                        "hit_rate_positive": float((mm > 0).mean()), "n_tranches": int(len(mm))}
    bench_out["universe_median"] = {"note": "non-tradable reference: the median stock's 20d next-open return per signal "
                                            "date; tranche-level only", **med_out}
    log("benchmarks done")

    # ---------------- main grid
    runs, results = {}, {}
    for sc in SCORERS:
        results[sc] = {}
        for bk in BASKETS:
            r = eng.run(scores[sc], bk)
            runs[(sc, bk)] = r
            results[sc][bk] = {k: v for k, v in r.items() if not k.startswith("_")}
        log(f"{sc}: done")

    # ---------------- up_5d label check (diagnostic; counted as trials)
    diag = {}
    eng5 = Engine(blocks, sessions, len(tick), 5)
    for sc in (CHAMPION, UP5D):
        for bk in ("top_decile", "ls_decile"):
            r20 = eng.run(scores[sc], bk, with_capacity=False)
            r5 = eng5.run(scores[sc], bk, with_capacity=False)
            if sc == UP5D:
                runs[(sc, bk)] = r20
            diag[f"{sc}|{bk}|hold20"] = {k: v for k, v in r20.items() if not k.startswith("_")}
            diag[f"{sc}|{bk}|hold5"] = {k: v for k, v in r5.items() if not k.startswith("_")}
    log("up_5d diagnostics done")

    # ---------------- per-date IC and per-month tables
    month_of = np.array([b.month for b in blocks])
    months = sorted(set(month_of))
    ic = {sc: np.array([date_ic(scores[sc][b.rows], b.y_exc) for b in blocks]) for sc in SCORERS + [UP5D]}
    regime = {}
    for mo in months:
        m = month_of == mo
        regime[mo] = {"mean_universe_median_y_raw_20d": float(eng.med[m].mean()),
                      "state": "up" if eng.med[m].mean() > 0 else "down",
                      "segment": "holdout" if all(cal.seg_of[m] == "holdout") else
                                 ("cv" if all(cal.seg_of[m] == "cv") else "mixed"),
                      "n_signal_dates": int(m.sum()),
                      "ew_universe_mean_20d": float(eng.bench["ew_universe"]["R"][m].mean())}
    hc = f"{HEADLINE_COST}bps"

    # adversarial-month scan: IC and gross L-S spread by month, across the 10 scorers
    adversarial = {}
    for mo in months:
        m = month_of == mo
        ics = {sc: float(np.nanmean(ic[sc][m])) for sc in SCORERS}
        ls = {sc: float(runs[(sc, "ls_decile")]["_tranche"]["gross"]["R"][m].mean()) for sc in SCORERS}
        n_neg_ic = sum(v < 0 for v in ics.values())
        n_neg_ls = sum(v < 0 for v in ls.values())
        adversarial[mo] = {"mean_ic_by_scorer": ics, "gross_ls_spread_by_scorer": ls,
                           "median_ic": float(np.median(list(ics.values()))),
                           "n_scorers_negative_ic": n_neg_ic, "n_scorers_negative_ls": n_neg_ls,
                           "n_scorers": len(SCORERS),
                           "adversarial": bool(n_neg_ic >= len(SCORERS) / 2 or n_neg_ls >= len(SCORERS) / 2),
                           "state": regime[mo]["state"]}

    # regime split: up vs down signal months (tranche level, combined program, 20 bps)
    up_mask = np.array([regime[mo]["state"] == "up" for mo in month_of])
    adv_mask = np.array([adversarial[mo]["adversarial"] for mo in month_of])
    bench_R = eng.bench
    regime_split = {}
    for sc in SCORERS:
        regime_split[sc] = {}
        for bk in BASKETS:
            r = runs[(sc, bk)]
            R = r["_tranche"][hc]["R"]
            if bk.endswith("ls_decile"):
                val = R
                metric = "net_ls_20d"
            else:
                val = R - bench_R[eng.bench_for(bk)]["R"]
                metric = "net_active_vs_ew_20d"
            ent = {"metric": metric}
            for lab, mk in (("up_months", up_mask), ("down_months", ~up_mask),
                            ("adversarial_months", adv_mask), ("non_adversarial_months", ~adv_mask)):
                ent[lab] = {"mean": float(val[mk].mean()) if mk.any() else None,
                            "hit": float((val[mk] > 0).mean()) if mk.any() else None,
                            "n_tranches": int(mk.sum())}
            regime_split[sc][bk] = ent

    # per-month table (champion + clean re-run, top-decile long)
    rows = []
    for sc in (CHAMPION, CHAMPION_CLEAN, ENSEMBLE):
        r = runs[(sc, "top_decile")]
        mem = r["_mem"]
        _, W, _ = leg(blocks, [x[0] for x in mem], len(tick), HORIZON)
        buy_raw = trade_fracs(W, HORIZON)["buy_raw"]
        for mo in months:
            m = month_of == mo
            Rg = r["_tranche"]["gross"]["Rg"][m]
            med = eng.med[m]
            ew = eng.bench["ew_universe"]["R"][m]
            row = {"model": sc, "signal_month": mo, "segment": regime[mo]["segment"],
                   "regime_fwd_median_sign": regime[mo]["state"],
                   "adversarial_month": adversarial[mo]["adversarial"], "n_tranches": int(m.sum()),
                   "universe_median_20d": med.mean(), "ew_universe_20d": ew.mean(),
                   "basket_gross_20d": Rg.mean(), "gross_excess_vs_median": (Rg - med).mean()}
            for c in COSTS_BPS:
                Rn = r["_tranche"][f"{c}bps"]["R"][m]
                row[f"net_excess_vs_median_{c}bps"] = (Rn - med).mean()
            Rn20 = r["_tranche"][hc]["R"][m]
            row["net_active_vs_ew_20bps"] = (Rn20 - ew).mean()
            row["hit_vs_median_net20"] = ((Rn20 - med) > 0).mean()
            row["hit_vs_ew_net20"] = ((Rn20 - ew) > 0).mean()
            row["mean_daily_ic"] = float(np.nanmean(ic[sc][m]))
            row["turnover_per_rebalance"] = float(np.nanmean(buy_raw[m])) if np.isfinite(buy_raw[m]).any() else None
            rows.append(row)
    monthly = pd.DataFrame(rows)
    monthly.to_csv(OUT_DIR / "champion_monthly.csv", index=False, float_format="%.6f")

    # short-leg decomposition and illiquid-tail decomposition (combined, 20 bps)
    decomp = {}
    for sc in SCORERS:
        decomp[sc] = {}
        for pre in ("", "liq_"):
            ls_run = runs[(sc, f"{pre}ls_decile")]
            long_run = runs[(sc, f"{pre}top_decile")]
            bname = eng.bench_for(f"{pre}x")
            ew = eng.bench[bname]["R"]
            mem = ls_run["_mem"]
            Sp, Ws, _ = leg(blocks, [x[1] for x in mem], len(tick), HORIZON)
            ts = trade_fracs(Ws, HORIZON)
            _, Rs_net = long_net(Sp, ts["buy"], ts["sell"], HEADLINE_COST / 1e4)   # bottom decile held long, net
            short_gross = ew - (Sp[:, -1] - 1.0)          # EW - bottom: >0 means shorting it helped
            short_net = ew - (Sp[:, -1] - 1.0) - HEADLINE_COST / 1e4 * (ts["buy"] + ts["sell"])
            long_net_act = long_run["_tranche"][hc]["R"] - ew
            d = {}
            for seg in SEGMENTS:
                m = cal.masks[seg]
                d[seg] = {"long_leg_net_active_20d": float(long_net_act[m].mean()),
                          "short_leg_gross_contrib_20d": float(short_gross[m].mean()),
                          "short_leg_net_contrib_20d": float(short_net[m].mean()),
                          "short_leg_hit": float((short_net[m] > 0).mean()),
                          "ls_net_20d": float(ls_run["_tranche"][hc]["R"][m].mean()),
                          "bottom_decile_net_raw_20d": float(Rs_net[m].mean())}
            decomp[sc][f"{pre or 'full_'}universe"] = d
    tail = {}
    for sc in SCORERS:
        mem = runs[(sc, "top_decile")]["_mem"]
        share = np.zeros((len(blocks), 3))
        exc = np.full((len(blocks), 3), np.nan)
        for k, (b, (idx, _)) in enumerate(zip(blocks, mem)):
            ter = b.tercile[idx]
            ew_mean = (b.path[HORIZON] - 1.0).mean()
            for t in range(3):
                sel = idx[ter == t]
                share[k, t] = len(sel) / len(idx)
                if len(sel):
                    exc[k, t] = (b.path[HORIZON, sel] - 1.0).mean() - ew_mean
        tail[sc] = {lab: {"weight_share": float(share[:, t].mean()),
                          "gross_active_vs_ew_20d_of_members": float(np.nanmean(exc[:, t])),
                          "contribution_to_basket_active_20d": float(np.nanmean(share[:, t] * np.nan_to_num(exc[:, t])))}
                    for t, lab in enumerate(("illiquid_tercile", "mid_tercile", "liquid_tercile"))}

    # ---------------- DSR / PSR
    trial_keys = [(sc, bk) for sc in SCORERS for bk in BASKETS]
    diag_keys = [(UP5D, "top_decile"), (UP5D, "ls_decile")]
    n_grid = len(trial_keys) + len(diag_keys) + 4    # + 4 hold-5 diagnostics
    N_total = n_grid + N_PROGRAM_CONFIGS

    def skill_series(sc, bk, key=hc):
        r = runs[(sc, bk)]
        mem = r["_mem"]
        # rebuild the daily skill series for the combined program
        Lp, Wl, _ = leg(blocks, [x[0] for x in mem], len(tick), HORIZON)
        tl = trade_fracs(Wl, HORIZON)
        c = int(key.replace("bps", "")) / 1e4
        if bk.endswith("ls_decile"):
            Sp, Ws, _ = leg(blocks, [x[1] for x in mem], len(tick), HORIZON)
            rr, _ = ls_net(Lp, Sp, tl, trade_fracs(Ws, HORIZON), c)
            return cal.seg_series(cal.to_days(rr), "combined")
        rr, _ = long_net(Lp, tl["buy"], tl["sell"], c)
        x = cal.seg_series(cal.to_days(rr), "combined")
        xb = cal.seg_series(eng.bench[eng.bench_for(bk)]["D"], "combined")
        return x - xb

    EX = cal.expo["combined"]
    skill = {k: skill_series(*k) for k in trial_keys + diag_keys}
    sr_d = {k: wmoments(v, EX)[0] / wmoments(v, EX)[1] for k, v in skill.items()}
    var_sr = float(np.var([sr_d[k] for k in trial_keys], ddof=1))
    best_key = max(trial_keys, key=lambda k: sr_d[k])

    # absolute (ROC) series of long baskets, rf-adjusted
    def raw_series(sc, bk):
        r = runs[(sc, bk)]
        Lp, Wl, _ = leg(blocks, [x[0] for x in r["_mem"]], len(tick), HORIZON)
        tl = trade_fracs(Wl, HORIZON)
        rr, _ = long_net(Lp, tl["buy"], tl["sell"], HEADLINE_COST / 1e4)
        return cal.seg_series(cal.to_days(rr), "combined") - RF_ANNUAL / PPY

    long_keys = [k for k in trial_keys if not k[1].endswith("ls_decile")]
    raw = {k: raw_series(*k) for k in long_keys}
    sr_raw = {k: wmoments(v, EX)[0] / wmoments(v, EX)[1] for k, v in raw.items()}
    var_sr_raw = float(np.var(list(sr_raw.values()), ddof=1))
    best_raw = max(long_keys, key=lambda k: sr_raw[k])
    ew_raw = cal.seg_series(eng.bench["ew_universe"]["D"], "combined") - RF_ANNUAL / PPY

    # tranche-level cross-check: non-overlapping 20d bets, T_eff = n_tranches / 20
    def tranche_skill(sc, bk):
        r = runs[(sc, bk)]
        R = r["_tranche"][hc]["R"]
        return R if bk.endswith("ls_decile") else R - eng.bench[eng.bench_for(bk)]["R"]

    sr_tr = {k: float(tranche_skill(*k).mean() / tranche_skill(*k).std(ddof=1)) for k in trial_keys}
    var_sr_tr = float(np.var(list(sr_tr.values()), ddof=1))
    xb_tr = tranche_skill(*best_key)
    T_eff = len(xb_tr) / HORIZON
    g3t, g4t = float(skew(xb_tr)), float(kurtosis(xb_tr, fisher=False))
    sr0_tr = expected_max_sr(var_sr_tr, N_total)
    dsr_tranche = {"series": f"{best_key[0]}|{best_key[1]} tranche net skill (20d bets)",
                   "T_effective_nonoverlapping": T_eff, "sr_per_20d": sr_tr[best_key],
                   "sr_annualised": sr_tr[best_key] * math.sqrt(PPY / HORIZON), "skew": g3t, "kurtosis_pearson": g4t,
                   "n_trials": N_total, "var_sr_across_trials": var_sr_tr,
                   "psr_vs_0": psr(sr_tr[best_key], 0.0, max(int(round(T_eff)), 2), g3t, g4t),
                   "dsr": psr(sr_tr[best_key], sr0_tr, max(int(round(T_eff)), 2), g3t, g4t)}

    champ_key = (CHAMPION, "top_decile")
    dsr = {
        "method": "Bailey & Lopez de Prado (2014): PSR(SR*) = Phi((SR-SR*) sqrt(T-1) / sqrt(1 - g3 SR + (g4-1)/4 SR^2)); "
                  "DSR = PSR(SR0), SR0 = sqrt(V[SR_n]) ((1-gamma) Phi^-1(1-1/N) + gamma Phi^-1(1-1/(N e))). "
                  "SR, skew, kurtosis at DAILY frequency of the net (20 bps) daily mark-to-market series, combined OOS "
                  "program; V[SR_n] = variance of the daily SRs of the 60 scorer x basket trials of this grid.",
        "skill_metric": "long baskets: net active return vs equal-weight universe (vs EW liquid tercile for liq_ baskets); "
                        "long-short: net L-S return",
        "n_trials": {"grid_scorer_x_basket": len(trial_keys), "diagnostics_up5d_and_hold5": len(diag_keys) + 4,
                     "program_configs_on_label": N_PROGRAM_CONFIGS, "N_used": N_total,
                     "note": "cost levels are not counted as trials (monotone in cost; 20 bps fixed in advance as the "
                             "realistic level). N_program = 30 is a floor: 26 logged beat_mkt_20d configs + "
                             "hyper-parameter grids of RF/XGB/MLP/LR."},
        "best_skill": dsr_block(skill[best_key], EX, var_sr, N_total, f"{best_key[0]}|{best_key[1]}", PPY),
        "champion_top_decile_skill": dsr_block(skill[champ_key], EX, var_sr, N_total,
                                               f"{CHAMPION}|top_decile (pre-registered champion)", PPY),
        "champion_clean_top_decile_skill": dsr_block(skill[(CHAMPION_CLEAN, "top_decile")], EX, var_sr, N_total,
                                                     f"{CHAMPION_CLEAN}|top_decile", PPY),
        "best_absolute_long_only": dsr_block(raw[best_raw], EX, var_sr_raw, N_total,
                                             f"{best_raw[0]}|{best_raw[1]} raw net minus rf", PPY),
        "ew_universe_absolute_reference": dsr_block(ew_raw, EX, var_sr_raw, N_total,
                                                    "ew_universe raw minus rf (passive, no selection)", PPY),
        "tranche_level_crosscheck": dsr_tranche,
        "sensitivity_dsr_best_skill_by_N": {
            str(n): psr(sr_d[best_key], expected_max_sr(var_sr, n), int(round(wmoments(skill[best_key], EX)[4])),
                        wmoments(skill[best_key], EX)[2], wmoments(skill[best_key], EX)[3])
            for n in (2, 10, 30, 60, N_total, 200)},
        "all_trials_daily_sr_annualised": {f"{k[0]}|{k[1]}": sr_d[k] * math.sqrt(PPY) for k in trial_keys + diag_keys},
    }
    log(f"DSR: best={best_key} SR_ann={sr_d[best_key] * math.sqrt(PPY):.2f} "
        f"PSR0={dsr['best_skill']['psr_vs_0']:.3f} DSR={dsr['best_skill']['dsr']:.3f}")

    # ---------------- reconciliation with the league's frozen labels
    recon = {}
    f = pd.read_parquet(PREDS_DIR / f"{CHAMPION}__beat_mkt_20d.parquet")
    f["date"] = pd.to_datetime(f["date"])
    f["rk"] = f.groupby("date")["score"].rank(ascending=False, method="first")
    f["n"] = f.groupby("date")["score"].transform("size")
    top = f[f["rk"] <= (f["n"] * TOP_FRAC).round()]
    frozen_top = top.groupby(["fold", "date"])["fwd"].mean().groupby("fold").mean()
    clean_top = pd.Series(runs[(CHAMPION, "top_decile")]["_tranche"]["gross"]["Rg"] - eng.med).groupby(
        np.array([b.fold for b in blocks])).mean()
    for fo in frozen_top.index:
        recon[fo] = {"frozen_labels_top_decile_excess": float(frozen_top[fo]),
                     "clean_labels_top_decile_excess": float(clean_top.get(fo, np.nan))}

    # ---------------- assemble JSON
    payload = {
        "generated_at": pd.Timestamp.now().isoformat(timespec="seconds"),
        "generated_by": "ml/strategy_backtest.py (seed 108, OMP_NUM_THREADS=2)",
        "engine": {
            "construction": "20 overlapping tranches, one rebalanced per session; tranche = equal-weight buy-and-hold "
                            "basket from the open of t+1 to the open of t+21 (label window); daily portfolio return = "
                            "equal-weight mean of live tranches' daily returns (JT convention); daily statistics weight "
                            "each session by exposure = live tranches/20 (fixed 1/20 capital per tranche, idle cash) so "
                            "every tranche counts equally; NAV/drawdown = fixed-capital program",
            "mark_to_market": "EXACT daily open-to-open marks from ml/data/equity_eod_snapshot.parquet (forward-filled "
                              "gaps), exit mark pinned to 1 + y_raw_20d; not amortised",
            "path_check": path_check,
            "truth": "clean model_dataset labels for every model; frozen preds joined on (date,ticker), phantom dates "
                     "dropped, frozen `fwd` not used",
            "universe": "clean-labeled harness rows (y_clean_20d), 113 signal dates 2026-04-01..2026-09-11, "
                        "~1,557 names/date; liquid tercile = cs_rank_turnover >= 0.67 (~515 names/date)",
            "baskets": {"top_decile": "long top 10% by score, equal weight (~156 names)",
                        "top20": "long top 20 names", "ls_decile": "long top decile minus short bottom decile, $1/$1",
                        "liq_*": "same, ranked and formed inside the liquid tercile only (~52 names per decile)"},
            "costs": "per side, netted against the tranche being replaced (steady-state; ends imputed with median "
                     "turnover); '20bps_no_netting' = every tranche fully bought and sold",
            "annualisation": "tranche: mean 20d net return x 252/20 (12.6 bets/yr); daily: mean x 252, vol x sqrt(252)",
            "risk_free_for_absolute_sharpe": RF_ANNUAL,
            "segments": "by signal date: cv = 2026-04..07 folds, holdout = 2026-08-03..09-11, combined = all",
            "bootstrap": f"month-block, B={N_BOOT}, seed {SEED}, paired draws across series within a segment",
            "capacity": f"AUM (Rs crore) at which the 10th-percentile entering name trades {PARTICIPATION:.0%} of its "
                        "20-session median daily turnover (median over steady-state tranches)",
        },
        "selection_contamination": SELECTION_CONTAMINATION,
        "coverage": coverage,
        "benchmarks": bench_out,
        "models": results,
        "up5d_label_check": diag,
        "regime": {"months": regime, "adversarial_scan": adversarial, "split": regime_split,
                   "definition": "state = sign of the mean (over signal dates in the month) universe-median y_raw_20d; "
                                 "adversarial = at least half of the 10 scorers have negative mean daily IC or negative "
                                 "gross L-S decile spread in that signal month"},
        "short_leg_decomposition": decomp,
        "illiquid_tail_decomposition_top_decile": tail,
        "deflated_sharpe": dsr,
        "label_reconciliation_champion": recon,
        "rl_own_portfolio_table_reference": json.loads(
            (RESULTS_DIR / "rl_reinforce__beat_mkt_20d.json").read_text()).get("portfolio", {}).get("cv_aggregate"),
        "runtime_seconds": round(time.time() - T0, 1),
    }
    (OUT_DIR / "strategy.json").write_text(json.dumps(clean_json(payload), indent=1, allow_nan=False))

    # ---------------- flat CSV + markdown tables
    flat = []
    for sc, bks in list(results.items()):
        for bk, r in bks.items():
            for ck, segs in r["results"].items():
                for seg, e in segs.items():
                    t, dl = e["tranche"], e["daily"]
                    da = e.get("daily_active", {})
                    flat.append({"scorer": sc, "basket": bk, "cost": ck, "segment": seg,
                                 "ann_return_252_20": t["ann_return_252_h"], "ann_mean_daily": dl["ann_mean_daily"],
                                 "ann_vol": dl["ann_vol"], "sharpe": dl["sharpe"], "sharpe_ci_lo": dl["sharpe_ci95"][0],
                                 "sharpe_ci_hi": dl["sharpe_ci95"][1], "max_dd": dl["max_dd"],
                                 "hit_rate_vs_median": t.get("hit_rate", t["hit_rate_net_positive"]),
                                 "hit_rate_vs_ew": t.get("hit_rate_vs_ew"),
                                 "excess_vs_median_net_20d": t.get("excess_vs_median_net"),
                                 "active_ann_vs_ew": da.get("ann_mean_daily"), "active_ir": da.get("sharpe"),
                                 "active_ir_ci_lo": (da.get("sharpe_ci95") or [None, None])[0],
                                 "active_ir_ci_hi": (da.get("sharpe_ci95") or [None, None])[1],
                                 "active_max_dd": da.get("max_dd"),
                                 "beta_vs_bench": e["beta_alpha_vs_benchmark"]["beta_vs_benchmark"],
                                 "alpha_ann_vs_bench": e["beta_alpha_vs_benchmark"]["alpha_ann"],
                                 "turnover": r["turnover_per_rebalance"],
                                 "names": r["basket_size_mean"]})
    pd.DataFrame(flat).to_csv(OUT_DIR / "strategy_flat.csv", index=False, float_format="%.6f")

    md = []

    def table_long(seg, bk, cost=hc):
        md.append(f"\n### {bk} | {seg} | {cost}\n")
        md.append("| scorer | ann. return | Sharpe (rf 5.5%) [95% CI] | max DD | active vs EW (ann.) | IR [95% CI] | "
                  "beta / alpha (ann.) | turnover | hit vs median | hit vs EW |")
        md.append("|---|---:|---|---:|---:|---|---|---:|---:|---:|")
        for sc in SCORERS:
            e = results[sc][bk]["results"][cost][seg]
            t, dl, da = e["tranche"], e["daily"], e["daily_active"]
            md.append(f"| {sc} | {fmt_pct(t['ann_return_252_h'])} | {fmt(dl['sharpe'])} [{fmt(dl['sharpe_ci95'][0])}, "
                      f"{fmt(dl['sharpe_ci95'][1])}] | {fmt_pct(dl['max_dd'])} | {fmt_pct(da['ann_mean_daily'])} | "
                      f"{fmt(da['sharpe'])} [{fmt(da['sharpe_ci95'][0])}, {fmt(da['sharpe_ci95'][1])}] | "
                      f"{e['beta_alpha_vs_benchmark']['beta_vs_benchmark']:.2f} / "
                      f"{fmt_pct(e['beta_alpha_vs_benchmark']['alpha_ann'])} | "
                      f"{100 * results[sc][bk]['turnover_per_rebalance']:.0f}% | {100 * t['hit_rate']:.0f}% | "
                      f"{100 * t['hit_rate_vs_ew']:.0f}% |")

    def table_ls(seg, bk, cost=hc):
        md.append(f"\n### {bk} | {seg} | {cost}\n")
        md.append("| scorer | ann. return | Sharpe [95% CI] | max DD | turnover (long/short) | hit (net > 0) |")
        md.append("|---|---:|---|---:|---:|---:|")
        for sc in SCORERS:
            e = results[sc][bk]["results"][cost][seg]
            t, dl = e["tranche"], e["daily"]
            md.append(f"| {sc} | {fmt_pct(t['ann_return_252_h'])} | {fmt(dl['sharpe'])} [{fmt(dl['sharpe_ci95'][0])}, "
                      f"{fmt(dl['sharpe_ci95'][1])}] | {fmt_pct(dl['max_dd'])} | "
                      f"{100 * results[sc][bk]['turnover_per_rebalance']:.0f}% / "
                      f"{100 * results[sc][bk]['turnover_per_rebalance_short']:.0f}% | "
                      f"{100 * t['hit_rate_net_positive']:.0f}% |")

    md.append("# Generated tables (ml/strategy_backtest.py)\n")
    md.append("## Benchmarks\n")
    md.append("| benchmark | segment | ann. return | Sharpe (rf 5.5%) [CI] | max DD | turnover |")
    md.append("|---|---|---:|---|---:|---:|")
    for name in ("ew_universe", "ew_liquid"):
        for seg in SEGMENTS:
            e = bench_out[name][seg]
            md.append(f"| {name} | {seg} | {fmt_pct(e['tranche']['ann_return_252_h'])} | {fmt(e['daily']['sharpe'])} "
                      f"[{fmt(e['daily']['sharpe_ci95'][0])}, {fmt(e['daily']['sharpe_ci95'][1])}] | "
                      f"{fmt_pct(e['daily']['max_dd'])} | {100 * bench_out[name]['turnover_per_rebalance']:.0f}% |")
    for seg in SEGMENTS:
        md.append(f"| universe_median (non-tradable) | {seg} | {fmt_pct(med_out[seg]['ann_return_252_20'])} | n/a | n/a | n/a |")
    for seg in ("combined", "cv", "holdout"):
        md.append(f"\n## Segment: {seg}\n")
        for bk in ("top_decile", "top20", "liq_top_decile", "liq_top20"):
            table_long(seg, bk)
        for bk in ("ls_decile", "liq_ls_decile"):
            table_ls(seg, bk)
    md.append("\n## Cost sensitivity, champion and ensemble (combined)\n")
    md.append("| scorer | basket | gross | 10 bps | 20 bps | 40 bps | 20 bps no netting |")
    md.append("|---|---|---:|---:|---:|---:|---:|")
    for sc in (CHAMPION, CHAMPION_CLEAN, ENSEMBLE, "random_forest", "lr_l2", HEURISTIC):
        for bk in ("top_decile", "liq_top_decile", "ls_decile"):
            rr = results[sc][bk]["results"]
            key = "daily_active" if not bk.endswith("ls_decile") else "daily"
            vals = [fmt_pct(rr[c]["combined"][key]["ann_mean_daily"]) + f" ({fmt(rr[c]['combined'][key]['sharpe'])})"
                    for c in ("gross", "10bps", "20bps", "40bps", "20bps_no_netting")]
            md.append(f"| {sc} | {bk} | " + " | ".join(vals) + " |")
    md.append("\n(values: annualised net active return vs EW (long) or net L-S return, with IR/Sharpe in brackets)\n")
    md.append("\n## Regime split (combined, 20 bps, tranche level: mean 20d net active vs EW / net L-S)\n")
    md.append("| month | state | segment | median fwd 20d | EW universe 20d | median IC (10 scorers) | #neg IC | #neg L-S | adversarial |")
    md.append("|---|---|---|---:|---:|---:|---:|---:|---|")
    for mo in months:
        a = adversarial[mo]
        md.append(f"| {mo} | {regime[mo]['state']} | {regime[mo]['segment']} | "
                  f"{fmt_pct(regime[mo]['mean_universe_median_y_raw_20d'])} | {fmt_pct(regime[mo]['ew_universe_mean_20d'])} | "
                  f"{a['median_ic']:+.3f} | {a['n_scorers_negative_ic']} | {a['n_scorers_negative_ls']} | {a['adversarial']} |")
    md.append("\n| scorer | basket | up months | down months | adversarial | non-adversarial |")
    md.append("|---|---|---:|---:|---:|---:|")
    for sc in SCORERS:
        for bk in ("top_decile", "ls_decile", "liq_top_decile"):
            e = regime_split[sc][bk]
            md.append(f"| {sc} | {bk} | " + " | ".join(
                f"{fmt_pct(e[k]['mean'], 2)} (n={e[k]['n_tranches']})" for k in
                ("up_months", "down_months", "adversarial_months", "non_adversarial_months")) + " |")
    md.append("\n## Short-leg decomposition (20 bps, 20d means)\n")
    md.append("| scorer | universe | segment | long leg net active | short leg gross | short leg net | L-S net |")
    md.append("|---|---|---|---:|---:|---:|---:|")
    for sc in SCORERS:
        for uni, dd in decomp[sc].items():
            for seg in SEGMENTS:
                x = dd[seg]
                md.append(f"| {sc} | {uni} | {seg} | {fmt_pct(x['long_leg_net_active_20d'], 2)} | "
                          f"{fmt_pct(x['short_leg_gross_contrib_20d'], 2)} | {fmt_pct(x['short_leg_net_contrib_20d'], 2)} | "
                          f"{fmt_pct(x['ls_net_20d'], 2)} |")
    md.append("\n## Illiquid-tail decomposition of the top-decile basket (combined, gross 20d)\n")
    md.append("| scorer | illiquid share | illiquid active | mid share | mid active | liquid share | liquid active |")
    md.append("|---|---:|---:|---:|---:|---:|---:|")
    for sc in SCORERS:
        t = tail[sc]
        md.append(f"| {sc} | " + " | ".join(
            f"{100 * t[k]['weight_share']:.0f}% | {fmt_pct(t[k]['gross_active_vs_ew_20d_of_members'], 2)}"
            for k in ("illiquid_tercile", "mid_tercile", "liquid_tercile")) + " |")
    md.append("\n## Capacity (combined; AUM at 5% ADV for the 10th-pct entering name)\n")
    md.append("| scorer | basket | names | AUM cap (Rs cr) | median name ADV20 (Rs cr) | share names ADV < Rs 5 cr |")
    md.append("|---|---|---:|---:|---:|---:|")
    for sc in (CHAMPION, CHAMPION_CLEAN, ENSEMBLE, "random_forest", "lr_l2", HEURISTIC):
        for bk in BASKETS:
            cp = results[sc][bk]["capacity"]
            md.append(f"| {sc} | {bk} | {results[sc][bk]['basket_size_mean']:.0f} | "
                      f"{cp['aum_cap_rs_crore_p10name_5pct_adv']:,.0f} | {cp['median_name_adv20_rs_crore']:,.1f} | "
                      f"{100 * cp['share_names_adv20_below_5cr']:.0f}% |")
    md.append("\n## up_5d label check (combined, 20 bps)\n")
    md.append("| scorer | basket | hold | net ann. (active vs EW or L-S) | IR/Sharpe | turnover |")
    md.append("|---|---|---|---:|---:|---:|")
    for k, r in diag.items():
        sc, bk, hold = k.split("|")
        e = r["results"][hc]["combined"]
        key = "daily" if bk == "ls_decile" else "daily_active"
        md.append(f"| {sc} | {bk} | {hold} | {fmt_pct(e[key]['ann_mean_daily'])} | {fmt(e[key]['sharpe'])} | "
                  f"{100 * r['turnover_per_rebalance']:.0f}% |")
    md.append("\n## Deflated Sharpe\n")
    for k in ("best_skill", "champion_top_decile_skill", "champion_clean_top_decile_skill", "best_absolute_long_only",
              "ew_universe_absolute_reference"):
        x = dsr[k]
        md.append(f"- **{k}** `{x['series']}`: SR_ann {x['sr_annualised']:+.2f} (daily {x['sr_per_period']:+.4f}), "
                  f"T={x['T_periods']} days, skew {x['skew']:+.2f}, kurt {x['kurtosis_pearson']:.2f}, N={x['n_trials']}, "
                  f"SR0_ann {x['sr0_expected_max_annualised']:+.2f} -> PSR(0)={x['psr_vs_0']:.3f}, DSR={x['dsr']:.3f}, "
                  f"MinTRL(PSR95 vs 0)={x['min_track_record_periods_psr95_vs_0']:.0f} days, "
                  f"MinTRL(DSR95)={x['min_track_record_periods_dsr95']:.0f} days")
    x = dsr["tranche_level_crosscheck"]
    md.append(f"- **tranche-level cross-check** `{x['series']}`: T_eff={x['T_effective_nonoverlapping']:.1f}, "
              f"SR_ann {x['sr_annualised']:+.2f} -> PSR(0)={x['psr_vs_0']:.3f}, DSR={x['dsr']:.3f}")
    md.append(f"- DSR(best skill) by N: " + ", ".join(f"N={n}: {v:.3f}" for n, v in
                                                       dsr["sensitivity_dsr_best_skill_by_N"].items()))
    md.append("\n## Per-month table: champion top-decile long (also in champion_monthly.csv)\n")
    try:
        md.append(monthly.to_markdown(index=False, floatfmt="+.4f"))
    except ImportError:                      # tabulate not installed
        md.append("```\n" + monthly.to_string(index=False) + "\n```")
    (OUT_DIR / "tables.md").write_text("\n".join(md) + "\n")
    log(f"wrote {OUT_DIR}/strategy.json, champion_monthly.csv, strategy_flat.csv, tables.md")


if __name__ == "__main__":
    main()
