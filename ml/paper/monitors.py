"""Monitors of the paper book: ml/PROGRAM_REPORT.md §10 alerts plus the two of §13.7 (thresholds in config.MONITORS).

Every monitor is evaluated "as of" a session s with the information available at s's close: labels count only
when their exit date is <= s; marks only up to s.  A monitor that needs live data that does not exist yet reports
status "warming up (needs ...)"; when its latest complete window predates inception it is computed on the research
record (the frame's matured labels, the ten-year walk-forward scores) with scope "pre-inception".
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books.construct import per_date_spearman
from ml.paper.common import fnum
from ml.paper.config import (BOOK_ORDER, BOOKS, CONTROL_10Y_PREDS, ETF_LIVE, H, INCEPTION_SIGNAL_DATE,
                             MODELS_META_DIR, MONITORS, N_TRIALS_DSR, SEED, VAR_SR_DSR)

LABEL, FWD, CLEAN = "label_beat_mkt_20d", "y_excess_20d", "y_clean_20d"
INCEPTION_MONTH = INCEPTION_SIGNAL_DATE[:7]


def _status(alert: bool) -> str:
    return "ALERT" if alert else "ok"


def _row(s, mon, scope, value, status, detail="") -> dict:
    return {"session": s, "monitor": mon, "scope": scope, "value": fnum(value, 6) if value is not None else "",
            "threshold": fnum(MONITORS[mon]["threshold"], 6), "status": status, "detail": detail}


def nw_t(x: np.ndarray, L: int = 20) -> float:
    from ml.hygiene.common import nw_t as _nw
    return _nw(np.asarray(x, float), L)


def _per_date_ic(dates: np.ndarray, a: np.ndarray, b: np.ndarray, min_n: int = 50) -> pd.Series:
    df = pd.DataFrame({"d": dates, "a": a, "b": b}).dropna()
    out = {}
    for d, g in df.groupby("d", sort=True):
        if len(g) >= min_n:
            out[d] = float(np.corrcoef(g["a"].rank().to_numpy(), g["b"].rank().to_numpy())[0, 1])
    return pd.Series(out, dtype=float)


class Context:
    """Data shared by the monitors of one run."""

    def __init__(self, df: pd.DataFrame, feats: list[str], sessions: pd.DatetimeIndex, scores: dict,
                 marks: pd.DataFrame, ingest_hist: dict, calendar: dict):
        self.df, self.feats, self.sessions = df, feats, sessions
        self.scores = scores                    # signal date (str) -> per-date score frame
        self.marks = marks
        self.ingest = ingest_hist
        self.calendar = calendar
        self.dd = df["date"].to_numpy(dtype="datetime64[ns]")
        self.month_cache: dict = {}
        self.wf = None

    def model_meta(self, month: str) -> dict | None:
        p = MODELS_META_DIR / f"{month}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def matured(self, s: pd.Timestamp) -> np.ndarray:
        ex = self.df["exit_date"].to_numpy(dtype="datetime64[ns]")
        return (self.df[LABEL].notna().to_numpy() & self.df[CLEAN].astype(bool).to_numpy()
                & ~np.isnat(ex) & (ex <= s.to_datetime64()))

    def walk_forward(self) -> pd.DataFrame:
        if self.wf is None:
            lo = self.sessions[-1] - pd.Timedelta(days=400)
            w = pd.read_parquet(CONTROL_10Y_PREDS, columns=["date", "ticker", "score", "fwd", "fold"],
                                filters=[("date", ">=", lo)])
            w["date"] = pd.to_datetime(w["date"])
            self.wf = w
        return self.wf

    def train_window(self, month: str) -> pd.DataFrame:
        if month not in self.month_cache:
            m = self.model_meta(month)
            lo, hi = pd.Timestamp(m["training_window"]["first_date"]), pd.Timestamp(m["training_window"]["last_date"])
            i0, i1 = np.searchsorted(self.dd, lo.to_datetime64(), "left"), np.searchsorted(self.dd, hi.to_datetime64(), "right")
            w = self.df.iloc[i0:i1]
            w = w[w[LABEL].notna() & w[CLEAN].astype(bool)]
            dates = w["date"].to_numpy()
            codes = np.searchsorted(np.unique(dates), dates)
            usual = {f: per_date_spearman(codes, w[f].to_numpy(float), w[FWD].to_numpy(float)) for f in self.feats}
            edges = {}
            for f in self.feats:
                v = w[f].to_numpy(float)
                v = v[np.isfinite(v)]
                edges[f] = np.unique(np.quantile(v, np.linspace(0, 1, 11)[1:-1])) if v.size else np.array([])
            exp = {f: _bin_shares(w[f].to_numpy(float), edges[f]) for f in self.feats}
            self.month_cache[month] = {"usual_ic": usual, "edges": edges, "expected": exp, "rows": len(w)}
        return self.month_cache[month]


def _bin_shares(v: np.ndarray, edges: np.ndarray) -> np.ndarray:
    nan = ~np.isfinite(v)
    b = np.searchsorted(edges, v[~nan], side="right")
    cnt = np.bincount(b, minlength=len(edges) + 1).astype(float)
    cnt = np.r_[cnt, nan.sum()]
    return cnt / max(cnt.sum(), 1.0)


def _psi(a: np.ndarray, e: np.ndarray, floor: float = 0.005) -> float:
    a, e = np.maximum(a, floor), np.maximum(e, floor)
    return float(np.sum((a - e) * np.log(a / e)))


def _complete_months(ctx: Context, s: pd.Timestamp, mature: np.ndarray) -> list[str]:
    """Calendar months (of signal dates) whose every session has matured labels by s."""
    sess = ctx.sessions[ctx.sessions <= s]
    if len(sess) < 22:
        return []
    ps = len(sess) - 1
    mon = sess.strftime("%Y-%m")
    out = []
    for m in sorted(set(mon)):
        last_pos = int(np.flatnonzero(mon == m).max())
        if last_pos + 21 <= ps:                      # the month's last signal date's 20-session label has exited
            out.append(m)
    return out[-6:]


# --------------------------------------------------------------------------- the monitors
def m_delivery(ctx: Context, s: pd.Timestamp, sd: str, mature: np.ndarray, months: list[str]) -> list[dict]:
    from ml.hygiene.delivery import CONTROLS, per_date
    need = months[-2:]
    if len(need) < 2:
        return [_row(sd, "delivery_resid_ic", "pre-inception", None, "warming up (needs 2 complete months of matured labels)")]
    u = ctx.df.loc[mature & ctx.df["date"].dt.strftime("%Y-%m").isin(need).to_numpy(),
                   ["date", "cs_rank_turnover", "deliv_pct_sma_20"] + CONTROLS + [FWD]]
    pdq = per_date(u.sort_values("date"), "deliv_pct_sma_20")
    pdq = pdq[pdq["subset"] == "all"]
    mon = pdq.groupby(pdq["date"].dt.strftime("%Y-%m"))[["resid_ic", "ic"]].mean()
    vals = [float(mon.loc[m, "resid_ic"]) for m in need]
    raw = [float(mon.loc[m, "ic"]) for m in need]
    scope = "live" if need[0] >= INCEPTION_MONTH else ("pre-inception" if need[-1] < INCEPTION_MONTH else "mixed")
    alert = all(v < MONITORS["delivery_resid_ic"]["threshold"] for v in vals)
    return [_row(sd, "delivery_resid_ic", scope, vals[-1], _status(alert),
                 f"months {need[0]} {vals[0]:+.4f}, {need[1]} {vals[1]:+.4f} (raw IC {raw[0]:+.4f}, {raw[1]:+.4f})")]


def m_live_auc(ctx: Context, s: pd.Timestamp, sd: str, mature: np.ndarray, months: list[str]) -> list[dict]:
    from sklearn.metrics import roc_auc_score
    live = [m for m in months if m >= INCEPTION_MONTH]
    out = []
    if not live:
        ctxj = json.loads((CONTROL_10Y_PREDS.parents[1] / "control__beat_mkt_20d.json").read_text())
        last = ctxj["folds"][-1]
        out.append(_row(sd, "live_model_auc", "pre-inception", ctxj["holdout"]["auc"],
                        f"warming up (needs every {INCEPTION_MONTH} signal date's 20-session label; the month's last "
                        "signal date's label exits 21 sessions after it)",
                        f"research walk-forward: fold {last['fold']} {last['auc']:.4f}, holdout 2026-08-03..2026-09-16 "
                        f"{ctxj['holdout']['auc']:.4f}"))
        return out
    lab = ctx.df.loc[mature, ["date", "ticker", LABEL]]
    for m in live[-1:]:
        sc = pd.concat([v[["date", "ticker", "lgbm"]] for k, v in ctx.scores.items() if k[:7] == m and k <= sd])
        j = sc.merge(lab, on=["date", "ticker"])
        auc = float(roc_auc_score(j[LABEL], j["lgbm"])) if j[LABEL].nunique() == 2 else float("nan")
        out.append(_row(sd, "live_model_auc", "live", auc, _status(auc < 0.5), f"month {m}, {len(j)} matured rows"))
    return out


def m_rank_ic(ctx: Context, s: pd.Timestamp, sd: str, mature: np.ndarray) -> list[dict]:
    lo = s - pd.Timedelta(days=365)
    w = ctx.walk_forward()
    w = w[(w["date"] > lo) & (w["date"] <= s)]
    parts = [w[["date", "score", "fwd"]]]
    lab = ctx.df.loc[mature, ["date", "ticker", FWD]]
    live = [v[["date", "ticker", "lgbm"]] for k, v in ctx.scores.items() if k <= sd]
    n_live = 0
    if live:
        j = pd.concat(live).merge(lab, on=["date", "ticker"])
        n_live = int(j["date"].nunique())
        parts.append(j.rename(columns={"lgbm": "score", FWD: "fwd"})[["date", "score", "fwd"]])
    x = pd.concat(parts)
    ic = _per_date_ic(x["date"].to_numpy(), x["score"].to_numpy(float), x["fwd"].to_numpy(float))
    t = nw_t(ic.to_numpy()) if len(ic) > 20 else float("nan")
    scope = "pre-inception" if n_live == 0 else "walk-forward + live"
    st = _status(t < MONITORS["rank_ic_nw_t_12m"]["threshold"]) if math.isfinite(t) else "warming up (needs > 20 dates)"
    return [_row(sd, "rank_ic_nw_t_12m", scope, t, st,
                 f"{len(ic)} matured signal dates in the trailing 12 months ({n_live} live), mean IC "
                 f"{ic.mean():+.4f}; last matured date {str(ic.index.max().date()) if len(ic) else 'none'}")]


def m_logistic(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    cur_m = sd[:7]
    prev_m = (pd.Timestamp(cur_m + "-01") - pd.Timedelta(days=1)).strftime("%Y-%m")
    a, b = ctx.model_meta(cur_m), ctx.model_meta(prev_m)
    if not a or not b or "logistic_coefficients" not in a or "logistic_coefficients" not in b:
        return [_row(sd, "logistic_sign_flips", "live", None, f"warming up (needs the {prev_m} and {cur_m} logistic fits)")]
    ca, cb = a["logistic_coefficients"], b["logistic_coefficients"]
    top = sorted(ca, key=lambda f: -abs(ca[f]))[:5]
    flips = [f for f in top if np.sign(ca[f]) != np.sign(cb.get(f, 0.0))]
    return [_row(sd, "logistic_sign_flips", f"{prev_m} -> {cur_m}", len(flips), _status(len(flips) > 0),
                 "top 5: " + ", ".join(f"{f} {ca[f]:+.4f} (prev {cb.get(f, float('nan')):+.4f})" for f in top))]


def m_psi(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    tw = ctx.train_window(sd[:7])
    sess = ctx.sessions[ctx.sessions <= s][-20:]
    cur = ctx.df[ctx.df["date"].isin(sess)]
    psi = {f: _psi(_bin_shares(cur[f].to_numpy(float), tw["edges"][f]), tw["expected"][f]) for f in ctx.feats}
    worst = sorted(psi, key=lambda f: -psi[f])[:5]
    mx = psi[worst[0]]
    return [_row(sd, "feature_psi", f"trailing 20 sessions vs {sd[:7]} training window", mx,
                 _status(mx > MONITORS["feature_psi"]["threshold"]),
                 "highest: " + ", ".join(f"{f} {psi[f]:.3f}" for f in worst)
                 + f"; features above 0.25: {sum(v > 0.25 for v in psi.values())}")]


def m_inversion(ctx: Context, s: pd.Timestamp, sd: str, mature: np.ndarray, months: list[str]) -> list[dict]:
    if not months:
        return [_row(sd, "feature_inversion", "pre-inception", None, "warming up (needs a complete matured month)")]
    m = months[-1]
    tw = ctx.train_window(sd[:7])
    sel = mature & (ctx.df["date"].dt.strftime("%Y-%m") == m).to_numpy()
    u = ctx.df.loc[sel]
    dates = u["date"].to_numpy()
    codes = np.searchsorted(np.unique(dates), dates)
    inv, n = [], 0
    for f in ctx.feats:
        a, b = tw["usual_ic"][f], per_date_spearman(codes, u[f].to_numpy(float), u[FWD].to_numpy(float))
        if not (np.isfinite(a) and np.isfinite(b)) or a == 0 or b == 0:
            continue
        n += 1
        if np.sign(a) != np.sign(b):
            inv.append(f)
    share = len(inv) / n if n else float("nan")
    scope = "live" if m >= INCEPTION_MONTH else "pre-inception"
    return [_row(sd, "feature_inversion", scope, share, _status(share > MONITORS["feature_inversion"]["threshold"]),
                 f"month {m}: {len(inv)} of {n} features against their training-window sign"
                 + (f" ({', '.join(inv[:8])}{' ...' if len(inv) > 8 else ''})" if inv else ""))]


def m_ensemble_atr(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    m = sd[:7]
    xs = [v for k, v in ctx.scores.items() if k[:7] == m and k <= sd]
    if not xs:
        return [_row(sd, "ensemble_atr_corr", "live", None, "warming up (no live signal date this month)")]
    vals = [float(pd.Series(v["ensemble"].to_numpy()).rank().corr(pd.Series(v["atr_pct"].to_numpy()).rank())) for v in xs]
    mu = float(np.mean(vals))
    return [_row(sd, "ensemble_atr_corr", f"month {m} to date", mu,
                 _status(abs(mu) > MONITORS["ensemble_atr_corr"]["threshold"]),
                 f"{len(vals)} signal dates; per-date range {min(vals):+.3f}..{max(vals):+.3f}")]


def m_neutral(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    v = ctx.scores.get(sd)
    if v is None:
        return []
    out = []
    for col, name in (("neutral_lgbm", "primary"), ("neutral_ensemble", "challenger")):
        r = {c: float(pd.Series(v[col].to_numpy()).rank().corr(pd.Series(v[c].to_numpy()).rank()))
             for c in ("atr_pct", "log_turnover")}
        mx = max(abs(x) for x in r.values())
        out.append(_row(sd, "neutral_score_corr", name, mx, _status(mx > MONITORS["neutral_score_corr"]["threshold"]),
                        f"atr_pct {r['atr_pct']:+.4f}, log_turnover {r['log_turnover']:+.4f}"))
    return out


def m_etf(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    v = ctx.scores.get(sd)
    if v is None:
        return []
    etf = set(pd.read_csv(ETF_LIVE, dtype=str, keep_default_na=False)["symbol"])
    from ml.paper.ingest import RAW_PR
    z = RAW_PR / f"PR{s:%d%m%y}.zip"
    if z.exists():
        from ml.integrity.corporate_actions import read_members
        e2, _ = read_members("etf", dirs=[z.parent])
        e2 = e2[pd.to_datetime(e2["file_date"]) == s] if len(e2) else e2
        etf |= set(e2["SYMBOL"]) if len(e2) else set()
    n = int(v["ticker"].isin(etf).sum())
    return [_row(sd, "universe_etf_count", "signal date", n, _status(n > 0), f"{len(v)} universe names")]


def m_split(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    u = ctx.df.loc[ctx.df["date"] == s, "flag_split_20d"]
    if u.empty:
        return []
    r = float(u.mean())
    return [_row(sd, "split_flag_rate", "signal date", r, _status(r > MONITORS["split_flag_rate"]["threshold"]),
                 f"{int(u.sum())} of {len(u)} universe names")]


def m_paper_ir(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    mk = ctx.marks[pd.to_datetime(ctx.marks["session"]) <= s] if len(ctx.marks) else ctx.marks
    out = []
    for book in BOOK_ORDER:
        x = mk[mk["book"] == book] if len(mk) else mk
        if x is None or len(x) == 0:
            out.append(_row(sd, "paper_active_ir_6m", book, None, "warming up (no marks yet)"))
            continue
        d = pd.to_datetime(x["session"])
        x = x[d > s - pd.Timedelta(days=182)]
        act = x["net_return_20bps"].astype(float).to_numpy() - x["benchmark_return"].astype(float).to_numpy()
        e = x["exposure"].astype(float).to_numpy()
        mon = pd.to_datetime(x["session"]).dt.strftime("%Y-%m").to_numpy()
        uniq = sorted(set(mon))
        codes = np.array([uniq.index(m) for m in mon])
        draws = np.random.default_rng(SEED).integers(0, len(uniq), size=(sb.N_BOOT, len(uniq)))
        if len(x) >= 2 and np.std(act) > 0:
            st = sb.series_stats(act, e, codes, draws, rf=0.0)
            ir, ci = st["sharpe"], st["sharpe_ci95"]
            cum = float(np.prod(1 + e * act) - 1)
        else:
            ir, ci, cum = float("nan"), [float("nan"), float("nan")], float("nan")
        warm = len(uniq) < 6
        if warm:
            out.append(_row(sd, "paper_active_ir_6m", book, None,
                            f"warming up (needs 6 months of marks; {len(x)} sessions in {len(uniq)} month(s))",
                            f"IR not reported before 6 months; cumulative active net 20 bps (fixed capital) {cum:+.4%}; "
                            f"benchmark {BOOKS[book]['benchmark']}"))
            continue
        out.append(_row(sd, "paper_active_ir_6m", book, ir, _status(ci[1] < 0),
                        f"IR {ir:+.2f} CI [{ci[0]:+.2f}, {ci[1]:+.2f}]; cumulative active (fixed capital) {cum:+.4%}; "
                        f"benchmark {BOOKS[book]['benchmark']}"))
    return out


def m_data(ctx: Context, s: pd.Timestamp, sd: str) -> list[dict]:
    wr = None
    for w in ctx.ingest.get("writes", []):
        if sd in w.get("accepted", []):
            wr = w
    if wr is None:
        return [_row(sd, "data_quality", "store", None, "ok", "session ingested before this stream (research data)")]
    a = wr["write"]["after"]
    cont = next((c for c in a["continuity_new_sessions"] if c["date"] == sd), None)
    ca = wr.get("corporate_actions", {})
    unv = [e for e in ca.get("unvalidated_adjustable_events_in_window", []) if e["ex_date"] == sd]
    brk = [e for e in ca.get("price_breaks_in_window", []) if e["ex_date"] == sd]
    alert = (a["eq_be_dup_date_ticker"] > 0 or (cont is not None and cont["share"] > MONITORS["data_quality"]["threshold"])
             or bool(unv) or not wr["write"].get("verified", False))
    closures = [d for d, v in ctx.calendar.get("closures", {}).items() if d <= sd]
    return [_row(sd, "data_quality", "store", cont["share"] if cont else None, _status(alert),
                 f"continuity mismatches {cont['n_mismatch'] if cont else 'n/a'} of {cont['n_with_prev'] if cont else 'n/a'}; "
                 f"duplicate EQ/BE pairs {a['eq_be_dup_date_ticker']}; write verified {wr['write'].get('verified')}; "
                 f"unvalidated split/bonus on this date {len(unv)}; price breaks {len(brk)}; "
                 f"recorded closures to date {closures}")]


def evaluate(ctx: Context, s: pd.Timestamp) -> list[dict]:
    sd = str(s.date())
    mature = ctx.matured(s)
    months = _complete_months(ctx, s, mature)
    rows = []
    rows += m_delivery(ctx, s, sd, mature, months)
    rows += m_live_auc(ctx, s, sd, mature, months)
    rows += m_rank_ic(ctx, s, sd, mature)
    rows += m_logistic(ctx, s, sd)
    rows += m_psi(ctx, s, sd)
    rows += m_paper_ir(ctx, s, sd)
    rows += m_inversion(ctx, s, sd, mature, months)
    rows += m_ensemble_atr(ctx, s, sd)
    rows += m_neutral(ctx, s, sd)
    rows += m_etf(ctx, s, sd)
    rows += m_split(ctx, s, sd)
    rows += m_data(ctx, s, sd)
    return rows


def dsr_paper(marks: pd.DataFrame) -> dict:
    """Deflated Sharpe of each book's daily active net-20 bps series (N = 261, V[SR] = 0.00387)."""
    out = {}
    for book in BOOK_ORDER:
        x = marks[marks["book"] == book] if len(marks) else marks
        if x is None or len(x) < 3:
            out[book] = {"status": "warming up (needs marks)"}
            continue
        act = x["net_return_20bps"].astype(float).to_numpy() - x["benchmark_return"].astype(float).to_numpy()
        e = x["exposure"].astype(float).to_numpy()
        if np.std(act) == 0:
            out[book] = {"status": "warming up (constant series)"}
            continue
        r = sb.dsr_block(act, e, VAR_SR_DSR, N_TRIALS_DSR, f"{book} active net 20 bps", sb.PPY)
        r["status"] = f"{len(x)} sessions: not informative before months of marks"
        out[book] = r
    return out


__all__ = ["Context", "evaluate", "dsr_paper", "H"]
