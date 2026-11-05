"""
Quant idea lab — out-of-the-box stock-selection ideas on NSE data, tested honestly.

Ideas were written down with an economic reason and an EXPECTED DIRECTION before
any result was seen (see IDEAS / EVENTS). Nothing here is tuned.

Cross-sectional factors (weekly):
  signal at the week's last close → buy next open → hold 5 sessions → close.
  Liquid names only (median 20-day turnover ≥ ₹10 Cr, known before entry).
  Long the expected-best decile; excess vs equal-weight liquid universe over the
  same span; cost = 0.15% round trip × weekly name turnover.
Event studies:
  entry at the next session's open (or the pre-announced ex-date), fixed hold,
  excess vs equal-weight liquid universe over the exact same span, t-stats
  clustered by entry week.
Periods: discovery < 2024-07-01, holdout ≥ 2024-07-01.
Verdict rule (pre-registered): STRONG = discovery t ≥ 2.6 (≈ Bonferroni for ~10
ideas) AND holdout net excess > 0 with t ≥ 2; PROMISING = discovery t ≥ 2 AND
holdout same sign with t ≥ 1; otherwise REJECTED.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/quant_idea_lab.py
Outputs: reports/idea_lab/ (factor_results.csv, factor_deciles.csv,
event_results.csv, current_picks.csv, summary.json)
"""
from __future__ import annotations

import json
import logging
import math
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import value_area_study as va  # noqa: E402  (DB path + snapshot helpers)

OUT_DIR = va.ROOT / "reports" / "idea_lab"
HOLDOUT_START = pd.Timestamp("2024-07-01")
COST_PCT = 0.15
LIQUID_CR = 10.0
HOLD = 5

log = logging.getLogger("idea_lab")


@dataclass(frozen=True)
class Idea:
    name: str
    direction: int          # +1: high score is good (long top decile); −1: long bottom decile
    why: str


IDEAS = [
    Idea("overnight_mom_20d", +1, "overnight-return clientele persists (Lou-Polk-Skouras)"),
    Idea("tug_of_war_20d", +1, "overnight minus intraday return: persistent buyer pressure outside market hours"),
    Idea("max_ret_20d", -1, "lottery demand: stocks with a huge single-day spike are overpriced (Bali et al.)"),
    Idea("abnormal_volume_5v60", +1, "high-volume return premium: attention brings new buyers (Gervais et al.)"),
    Idea("quiet_loser_reversal", +1, "a 1-week drop on LOW volume is liquidity noise, not news → reverts"),
    Idea("dividend_yield_ttm", +1, "value via point-in-time dated dividends"),
]


# ── data ────────────────────────────────────────────────────────────────────────

def load() -> dict[str, pd.DataFrame]:
    tmp = Path(tempfile.mkdtemp(prefix="idea_snap_"))
    snap = tmp / "s.duckdb"
    shutil.copy2(va.DB_PATH, snap)
    if Path(f"{va.DB_PATH}.wal").exists():
        shutil.copy2(f"{va.DB_PATH}.wal", f"{snap}.wal")
    try:
        con = duckdb.connect(str(snap))
        px = con.sql("""
            SELECT o.ticker, o.date, o.open, o.high, o.low, o.close, o.volume, o.adjusted_close
            FROM ohlcv o JOIN instruments i USING (ticker)
            WHERE i.instrument_type = 'EQUITY' AND i.ml_eligible AND o.volume > 0
              AND o.high >= o.low AND o.close > 0 AND o.open > 0
        """).df()
        div = con.sql("SELECT ticker, date, amount FROM dividends WHERE amount > 0").df()
        spl = con.sql("SELECT ticker, date, ratio FROM splits WHERE ratio > 0").df()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    px["date"] = pd.to_datetime(px["date"])
    div["date"] = pd.to_datetime(div["date"]).dt.tz_localize(None).dt.normalize()
    spl["date"] = pd.to_datetime(spl["date"]).dt.tz_localize(None).dt.normalize()
    wide = {k: px.pivot(index="date", columns="ticker", values=k).sort_index()
            for k in ("open", "high", "low", "close", "volume", "adjusted_close")}
    wide["div"], wide["splits"] = div, spl
    return wide


def liquid_mask(w: dict) -> pd.DataFrame:
    """Turnover known before the session (shifted), in ₹ Cr."""
    turn = (w["close"] * w["volume"]).rolling(20, min_periods=10).median().shift(1) / 1e7
    return turn >= LIQUID_CR


# ── factors (all use data up to and including the signal close) ─────────────────

def factors(w: dict) -> dict[str, pd.DataFrame]:
    o, c, v, ac = w["open"], w["close"], w["volume"], w["adjusted_close"]
    f = ac / c                                            # total-return factor (dividends)
    ao = o * f
    on = np.log(ao / ac.shift(1))                         # overnight (dividend gaps neutralised)
    intra = np.log(c / o)
    r = ac.pct_change(fill_method=None)
    volr = np.log(v.rolling(5).mean() / v.rolling(60).mean())
    ret5 = ac / ac.shift(5) - 1

    # trailing-365-day dividends per share, dated on the ex-date (point in time)
    d = w["div"]
    dmat = d.pivot_table(index="date", columns="ticker", values="amount", aggfunc="sum")
    dmat = dmat.reindex(index=c.index.union(dmat.index), columns=c.columns).fillna(0.0)
    ttm = dmat.rolling("365D").sum().reindex(c.index)
    return {
        "overnight_mom_20d": on.rolling(20, min_periods=15).sum(),
        "tug_of_war_20d": on.rolling(20, min_periods=15).sum() - intra.rolling(20, min_periods=15).sum(),
        "max_ret_20d": r.rolling(20, min_periods=15).max(),
        "abnormal_volume_5v60": volr,
        "quiet_loser_reversal": (-ret5).where(volr < 0),
        "dividend_yield_ttm": (ttm / c).where(c.notna()),
    }


# ── weekly cross-sectional engine ───────────────────────────────────────────────

def weekly_schedule(idx: pd.DatetimeIndex) -> list[tuple[int, int, int]]:
    """(signal, entry, exit) row indices: signal = last session of each ISO week."""
    wk = idx.to_period("W")
    sig = [i for i in range(len(idx) - 1) if wk[i] != wk[i + 1]]
    return [(s, s + 1, s + HOLD) for s in sig if s + HOLD < len(idx)]


def run_factor(score: pd.DataFrame, w: dict, liq: pd.DataFrame, direction: int, n_dec: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    o, c, ac = w["open"].to_numpy(), w["close"].to_numpy(), w["adjusted_close"].to_numpy()
    f = ac / c
    S, L = score.reindex_like(w["close"]).to_numpy(), liq.to_numpy()
    idx = w["close"].index
    rows, dec_rows = [], []
    prev_top: set[int] = set()
    for s, e, x in weekly_schedule(idx):
        with np.errstate(invalid="ignore", divide="ignore"):
            ret = np.clip(ac[x] / (o[e] * f[e]) - 1, -0.5, 0.5) * 100
        ok = L[e] & np.isfinite(S[s]) & np.isfinite(ret)
        if ok.sum() < 100:
            continue
        uni = ret[L[e] & np.isfinite(ret)].mean()
        sc = S[s][ok] * direction
        rk = pd.Series(sc).rank(pct=True, method="first").to_numpy()
        dec = np.minimum((rk * n_dec).astype(int), n_dec - 1)          # 0..9, 9 = expected best
        rr = ret[ok]
        cols = np.flatnonzero(ok)
        top = set(cols[dec == n_dec - 1])
        turnover = 1.0 if not prev_top else len(top - prev_top) / max(len(top), 1)
        prev_top = top
        gross = rr[dec == n_dec - 1].mean() - uni
        rows.append({"date": idx[s], "n": int(ok.sum()), "top_n": len(top), "gross_excess_pct": gross,
                     "turnover": turnover, "net_excess_pct": gross - COST_PCT * turnover,
                     "bottom_excess_pct": rr[dec == 0].mean() - uni})
        for k in range(n_dec):
            dec_rows.append({"date": idx[s], "decile": k + 1, "excess_pct": rr[dec == k].mean() - uni})
    return pd.DataFrame(rows), pd.DataFrame(dec_rows)


def tstat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / x.std(ddof=1) * math.sqrt(len(x))) if len(x) > 5 and x.std(ddof=1) > 0 else math.nan


def verdict(disc_t: float, hold_mean: float, hold_t: float, disc_mean: float) -> str:
    if disc_mean > 0 and disc_t >= 2.6 and hold_mean > 0 and hold_t >= 2:
        return "STRONG"
    if disc_mean > 0 and disc_t >= 2 and hold_mean > 0 and hold_t >= 1:
        return "PROMISING"
    return "REJECTED"


# ── event studies ───────────────────────────────────────────────────────────────

class Bench:
    """Equal-weight liquid-universe return from open[e] to close[x] (price only)."""

    def __init__(self, w: dict, liq: pd.DataFrame):
        self.O = np.where(liq.to_numpy(), w["open"].to_numpy(), np.nan)
        self.C = w["close"].to_numpy()
        self._cache: dict[tuple[int, int], float] = {}

    def __call__(self, e: int, x: int) -> float:
        k = (e, x)
        if k not in self._cache:
            with np.errstate(invalid="ignore", divide="ignore"):
                self._cache[k] = float(np.nanmean(np.clip(self.C[x] / self.O[e] - 1, -0.5, 0.5)) * 100)
        return self._cache[k]


def event_trades(name: str, cells: list[tuple[int, int, int, int]], w: dict, bench: Bench, liq: np.ndarray) -> pd.DataFrame:
    """cells = (column, signal_row, entry_row, exit_row); price return open→close."""
    O, C = w["open"].to_numpy(), w["close"].to_numpy()
    idx, cols = w["close"].index, w["close"].columns
    out = []
    n = len(idx)
    for j, s, e, x in cells:
        if e < 0 or x >= n or e > x or not np.isfinite(O[e, j]) or not np.isfinite(C[x, j]):
            continue
        ret = (C[x, j] / O[e, j] - 1) * 100
        if abs(ret) > 60:
            continue
        out.append({"event": name, "ticker": cols[j], "signal_date": idx[s], "entry_date": idx[e],
                    "exit_date": idx[x], "liquid": bool(liq[e, j]), "ret_net_pct": ret - COST_PCT,
                    "excess_net_pct": ret - COST_PCT - bench(e, x)})
    return pd.DataFrame(out)


def events(w: dict, liq: pd.DataFrame) -> pd.DataFrame:
    O, H, L, C = (w[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx, cols = w["close"].index, w["close"].columns
    n = len(idx)
    bench = Bench(w, liq)
    L_ = liq.to_numpy()
    prevC = np.vstack([np.full((1, C.shape[1]), np.nan), C[:-1]])
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = C / prevC - 1
    bands = [(0.0485, 0.0505), (0.0985, 0.1005), (0.1985, 0.2005)]
    at_band_up = np.zeros_like(C, dtype=bool)
    at_band_dn = np.zeros_like(C, dtype=bool)
    for lo, hi in bands:
        at_band_up |= (ret >= lo) & (ret <= hi)
        at_band_dn |= (ret <= -lo) & (ret >= -hi)
    uc = at_band_up & ((H - C) / C < 0.0005)                 # closed pinned at the high
    lc = at_band_dn & ((C - L) / C < 0.0005)                 # closed pinned at the low
    frames = []
    for name, mask in (("upper_circuit_lock", uc), ("lower_circuit_lock", lc)):
        rs, cs = np.nonzero(mask)
        for hold, tag in ((1, "1d"), (HOLD, "5d")):
            cells = [(j, s, s + 1, s + hold) for s, j in zip(rs, cs)]
            frames.append(event_trades(f"{name}_{tag}", cells, w, bench, L_))

    pos = pd.Series(np.arange(n), index=idx)
    col = pd.Series(np.arange(len(cols)), index=cols)

    def rows_for(df: pd.DataFrame) -> list[tuple[int, int]]:
        out = []
        for tk, d in zip(df["ticker"], df["date"]):
            if tk not in col.index:
                continue
            i = idx.searchsorted(d)                          # first session on/after the ex-date
            if i < n:
                out.append((int(col[tk]), int(i)))
        return out

    spl = w["splits"][w["splits"]["ratio"] > 1]              # forward splits only
    cells = [(j, i, i, i + 20) for j, i in rows_for(spl)]
    frames.append(event_trades("post_split_drift_20d", cells, w, bench, L_))

    dv = w["div"].copy()
    ex_rows = rows_for(dv)
    frames.append(event_trades("dividend_runup_5d", [(j, i - 5, i - 5, i - 1) for j, i in ex_rows], w, bench, L_))
    frames.append(event_trades("post_ex_dividend_10d", [(j, i, i, i + 9) for j, i in ex_rows], w, bench, L_))
    # the big-dividend subset (≥1% yield on the pre-ex close) — pre-registered
    big = []
    for (j, i), amt in zip(ex_rows, dv.loc[dv["ticker"].isin(col.index), "amount"]):
        if i >= 1 and np.isfinite(C[i - 1, j]) and amt / C[i - 1, j] >= 0.01:
            big.append((j, i - 5, i - 5, i - 1))
    frames.append(event_trades("dividend_runup_5d_yield1pct", big, w, bench, L_))
    return pd.concat([f for f in frames if len(f)], ignore_index=True)


def event_summary(ev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    ev = ev.assign(period=np.where(ev["entry_date"] < HOLDOUT_START, "discovery", "holdout"),
                   wk=ev["entry_date"].dt.to_period("W"))
    for name, g0 in ev.groupby("event"):
        for scope, g1 in (("liquid", g0[g0["liquid"]]), ("all", g0)):
            rec = {"event": name, "scope": scope}
            for per in ("discovery", "holdout"):
                g = g1[g1["period"] == per]
                wm = g.groupby("wk")["excess_net_pct"].mean()
                rec[f"{per}_n"] = len(g)
                rec[f"{per}_net_ret_pct"] = g["ret_net_pct"].mean()
                rec[f"{per}_excess_pct"] = wm.mean()
                rec[f"{per}_t"] = tstat(wm)
                rec[f"{per}_win"] = (g["excess_net_pct"] > 0).mean()
            rec["verdict"] = verdict(rec["discovery_t"], rec["holdout_excess_pct"], rec["holdout_t"],
                                     rec["discovery_excess_pct"])
            rows.append(rec)
    return pd.DataFrame(rows)


# ── the survivor: lower-circuit rebound (deep dive) ─────────────────────────────

BANDS = [(0.0485, 0.0505), (0.0985, 0.1005), (0.1985, 0.2005)]
RELOCK_GAP = -0.048        # next open ≤ −4.8% vs the locked close → re-opened at/near the floor


def lower_circuit_locks(o: np.ndarray, h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    """Closed down by a circuit band (5/10/20%) AND pinned at the day's low."""
    prev = np.vstack([np.full((1, c.shape[1]), np.nan), c[:-1]])
    with np.errstate(invalid="ignore", divide="ignore"):
        r = c / prev - 1
        pinned = (c - l) / c < 0.0005
    at_band = np.zeros_like(c, dtype=bool)
    for lo, hi in BANDS:
        at_band |= (r <= -lo) & (r >= -hi)
    return at_band & pinned


def nse_series() -> pd.Series:
    """Current NSE series per symbol (EQ = intraday allowed; BE/BZ = trade-to-trade)."""
    ref = pd.read_csv(va.ROOT / "data" / "reference" / "nse_equity_list.csv")
    ref.columns = [c.strip() for c in ref.columns]
    return ref.set_index("SYMBOL")["SERIES"].str.strip()


def circuit_rebound(w: dict, liq: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Research record only — strategy REJECTED (see REPORT.md §5). Rule tested:
    yesterday closed locked at the lower circuit; today it re-opens at/near the floor
    → buy at the open, sell at today's close. Reports both the naive same-day exit and
    the realistic exit (all-day locks can't be sold). No watchlist is produced."""
    O, H, L_, C = (w[k].to_numpy() for k in ("open", "high", "low", "close"))
    idx, cols = w["close"].index, w["close"].columns
    liqv = liq.to_numpy()
    ser = nse_series()
    bench = Bench(w, liq)
    lock = lower_circuit_locks(O, H, L_, C)
    turn_df = (w["close"] * w["volume"]).rolling(20, min_periods=10).median() / 1e7   # window ends at the lock day
    turn = turn_df.shift(1).to_numpy()          # indexed by the ENTRY session (= lock-day window)
    rows = []
    for s, j in zip(*np.nonzero(lock)):
        e = s + 1
        if e >= len(idx) or not liqv[e, j] or ser.get(cols[j]) != "EQ":
            continue
        if not (np.isfinite(O[e, j]) and np.isfinite(C[e, j])) or O[e, j] / C[s, j] - 1 > RELOCK_GAP:
            continue
        r = (C[e, j] / O[e, j] - 1) * 100
        # realistic exit: a session locked all day at/below entry (high == low) cannot be
        # sold — carry to the first session that trades a range and sell at its close
        x = e
        while x < len(idx) - 1 and np.isfinite(H[x, j]) and H[x, j] == L_[x, j] and C[x, j] <= O[e, j]:
            x += 1
        r_real = (C[x, j] / O[e, j] - 1) * 100 if np.isfinite(C[x, j]) else np.nan
        rows.append({"date": idx[e], "ticker": cols[j], "ret_net_pct": r - COST_PCT,
                     "excess_net_pct": r - COST_PCT - bench(e, e), "turnover_cr": turn[e, j],
                     "stuck_days": x - e, "real_excess_net_pct": r_real - COST_PCT - bench(e, x)})
    tr = pd.DataFrame(rows)
    tr["period"] = np.where(tr["date"] < HOLDOUT_START, "discovery", "holdout")

    stats = {}
    for per, g in tr.groupby("period"):
        wm = g.groupby(g["date"].dt.to_period("W"))["excess_net_pct"].mean()
        # book: ≤5 names a day at 15% each (project limits), most liquid first; cash otherwise
        day = (g.sort_values("turnover_cr", ascending=False).groupby("date").head(5)
                .groupby("date")["ret_net_pct"].sum() * 0.15 / 100)
        sessions = idx[(idx >= g["date"].min()) & (idx <= g["date"].max())]
        daily = day.reindex(sessions).fillna(0.0)
        eq = (1 + daily).cumprod()
        yrs = (sessions[-1] - sessions[0]).days / 365.25
        stats[per] = {
            "trades": len(g), "names": int(g["ticker"].nunique()),
            "net_ret_pct": round(g["ret_net_pct"].mean(), 3),
            "excess_pct": round(wm.mean(), 3), "t_weekly": round(tstat(wm), 2),
            "realistic_excess_pct": round(g.groupby(g["date"].dt.to_period("W"))["real_excess_net_pct"].mean().mean(), 3),
            "realistic_t_weekly": round(tstat(g.groupby(g["date"].dt.to_period("W"))["real_excess_net_pct"].mean()), 2),
            "stuck_share": round((g["stuck_days"] > 0).mean(), 3),
            "win_rate": round((g["excess_net_pct"] > 0).mean(), 3),
            "book_cagr_pct": round((eq.iloc[-1] ** (1 / yrs) - 1) * 100, 2),
            "book_max_dd_pct": round(((eq / eq.cummax()) - 1).min() * 100, 2),
            "book_sharpe": round(daily.mean() / daily.std() * math.sqrt(252), 2) if daily.std() > 0 else None,
            "days_invested_pct": round((daily != 0).mean() * 100, 1),
        }
    by_year = tr.groupby(tr["date"].dt.year)["excess_net_pct"].agg(["count", "mean"]).round(3)
    stats["by_year"] = {int(k): v for k, v in by_year.to_dict("index").items()}

    return stats, tr


# ── driver ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    w = load()
    liq = liquid_mask(w)
    log.info("panel %s × %s (%.0fs)", *w["close"].shape, time.time() - t0)

    fac = factors(w)
    res, decs, picks = [], [], []
    for idea in IDEAS:
        wk, dc = run_factor(fac[idea.name], w, liq, idea.direction)
        wk["period"] = np.where(wk["date"] < HOLDOUT_START, "discovery", "holdout")
        dc["period"] = np.where(dc["date"] < HOLDOUT_START, "discovery", "holdout")
        rec = {"idea": idea.name, "direction": idea.direction, "why": idea.why}
        for per in ("discovery", "holdout"):
            g = wk[wk["period"] == per]
            rec[f"{per}_weeks"] = len(g)
            rec[f"{per}_gross_pct_wk"] = g["gross_excess_pct"].mean()
            rec[f"{per}_net_pct_wk"] = g["net_excess_pct"].mean()
            rec[f"{per}_t_net"] = tstat(g["net_excess_pct"])
            rec[f"{per}_net_ann_pct"] = ((1 + g["net_excess_pct"].mean() / 100) ** 52 - 1) * 100
            rec[f"{per}_turnover"] = g["turnover"].mean()
            dm = dc[dc["period"] == per].groupby("decile")["excess_pct"].mean()
            rec[f"{per}_monotonic_rho"] = float(pd.Series(dm.index).corr(pd.Series(dm.values), method="spearman"))
        rec["verdict"] = verdict(rec["discovery_t_net"], rec["holdout_net_pct_wk"], rec["holdout_t_net"],
                                 rec["discovery_net_pct_wk"])
        res.append(rec)
        dm = dc.groupby(["period", "decile"])["excess_pct"].mean().unstack("period").reset_index()
        decs.append(dm.assign(idea=idea.name))

        # today's expected-best decile (latest close), liquid names
        last = fac[idea.name].iloc[-1] * idea.direction
        ok = liq.iloc[-1] & last.notna()
        top = last[ok].rank(pct=True) >= 0.9
        turn = ((w["close"] * w["volume"]).rolling(20).median().iloc[-1] / 1e7)
        for tk in last[ok][top].sort_values(ascending=False).index:
            picks.append({"idea": idea.name, "ticker": tk, "score": float(fac[idea.name].iloc[-1][tk]),
                          "close": float(w["close"].iloc[-1][tk]), "turnover_cr": float(turn[tk])})
        log.info("%s done (%.0fs)", idea.name, time.time() - t0)

    fr = pd.DataFrame(res)
    fr.to_csv(OUT_DIR / "factor_results.csv", index=False)
    pd.concat(decs).to_csv(OUT_DIR / "factor_deciles.csv", index=False)

    ev = events(w, liq)
    es = event_summary(ev)
    es.to_csv(OUT_DIR / "event_results.csv", index=False)
    ev.to_csv(OUT_DIR / "event_trades.csv", index=False)
    log.info("events %s (%.0fs)", len(ev), time.time() - t0)

    cr_stats, cr_trades = circuit_rebound(w, liq)
    cr_trades.to_csv(OUT_DIR / "circuit_rebound_trades.csv", index=False)
    log.info("circuit rebound: %s", json.dumps({k: v for k, v in cr_stats.items() if k != "by_year"}, default=str))

    keep = set(fr.loc[fr["verdict"] != "REJECTED", "idea"])
    cp = pd.DataFrame(picks)
    (cp[cp["idea"].isin(keep)] if len(cp) else cp).to_csv(OUT_DIR / "current_picks.csv", index=False)
    summary = {"data_end": str(w["close"].index[-1].date()), "holdout_start": str(HOLDOUT_START.date()),
               "factors": fr.round(4).to_dict("records"), "events": es.round(4).to_dict("records"),
               "circuit_rebound_rejected": cr_stats}
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("done (%.0fs) → %s", time.time() - t0, OUT_DIR)


if __name__ == "__main__":
    main()
