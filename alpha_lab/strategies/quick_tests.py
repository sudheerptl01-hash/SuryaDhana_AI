#!/usr/bin/env python
"""Appendix Q quick tests (alpha_lab/PLAN.md, pre-registered 14 Oct 2026 ~22:20 IST).

Five gross cross-sectional / index diagnostics — NOT strategies:
  Q1 FUT-04 excess carry        H: discount (bottom) quintile LAGS over 20 sessions
  Q2 OPT-08 O/S ₹-proxy         H: top quintile LAGS over 5 and 20 sessions
  Q3 POS-05 variance risk prem  H: high-VRP tercile → HIGHER next 20/60-session returns
  Q4 POS-06 index OI-PCR        both signs allowed (exploratory; best verdict = Lead)
  Q5 EVT-03 F&O entry/exit      descriptive event study, CIs, no gate

Frame: weekly signals (last session of each ISO week), entry next open, NW t lags 1/4/12
for h = 5/20/60. Periods: P-a 2019-10-01→2023-12-31, P-b 2024-01-01→2026-10-13
(Q3: 2009-10-01→2019-12-31 and 2020-01-01→2026-10-13). Pass bar: same sign and |t| ≥ 2 in
BOTH periods = Robust; one period = Lead; robust opposite to H = Rejected-sign.

    PYTHONPATH=alpha_lab python alpha_lab/strategies/quick_tests.py

Writes alpha_lab/reports/quick_tests_RESULTS.md + qt_*.csv. Research only.
"""
from __future__ import annotations

import math
import shutil
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
ROOT = LAB.parent
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402
from lib.momentum import is_etf  # noqa: E402
from lib.nse_panel import load_panel  # noqa: E402
from lib.xs_labels import forward_open_returns  # noqa: E402

RF = 0.065
BASIS_CAP = 0.40
P_A = (pd.Timestamp("2019-10-01"), pd.Timestamp("2023-12-31"))
P_B = (pd.Timestamp("2024-01-01"), pd.Timestamp("2026-10-13"))
Q3_P1 = (pd.Timestamp("2009-10-01"), pd.Timestamp("2019-12-31"))
Q3_P2 = (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-10-13"))
NW_LAGS = {5: 1, 10: 2, 20: 4, 60: 12}
OUT = LAB / "reports"


def nw_t(x, lags: int) -> tuple[float, float, int]:
    """(mean, NW t, n) of a signal-frequency series with overlapping forward windows."""
    a = pd.Series(x, dtype=float).dropna().to_numpy()
    n = len(a)
    if n < 10:
        return (float(np.mean(a)) if n else np.nan), np.nan, n
    m = a.mean()
    e = a - m
    s = e @ e / n
    for k in range(1, min(lags, n - 1) + 1):
        s += 2 * (1 - k / (lags + 1)) * (e[k:] @ e[:-k]) / n
    return float(m), float(m / math.sqrt(s / n)) if s > 0 else np.nan, n


def week_ends(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(idx.to_series().groupby(idx.to_period("W")).max().to_numpy())


def month_ends(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(idx.to_series().groupby(idx.to_period("M")).max().to_numpy())


def in_period(idx: pd.DatetimeIndex, p: tuple[pd.Timestamp, pd.Timestamp]) -> np.ndarray:
    return (idx >= p[0]) & (idx <= p[1])


def verdict_directional(m_a, t_a, m_b, t_b, h_sign: int) -> str:
    """Pass bar vs a directional hypothesis (h_sign = expected sign of the tested mean)."""
    if not (np.isfinite(t_a) and np.isfinite(t_b)):
        return "undecidable (too thin)"
    sgn_a, sgn_b = np.sign(m_a), np.sign(m_b)
    if sgn_a == sgn_b and abs(t_a) >= 2 and abs(t_b) >= 2:
        return "Robust" if sgn_a == h_sign else "Rejected-sign (robust opposite)"
    if sgn_a == sgn_b and (abs(t_a) >= 2 or abs(t_b) >= 2):
        return "Lead" if sgn_a == h_sign else "Lead (opposite sign)"
    return "No effect"


def verdict_exploratory(m_a, t_a, m_b, t_b) -> str:
    if not (np.isfinite(t_a) and np.isfinite(t_b)):
        return "undecidable (too thin)"
    if np.sign(m_a) == np.sign(m_b) and abs(t_a) >= 2 and abs(t_b) >= 2:
        return "Lead (both periods; exploratory cap)"
    if np.sign(m_a) == np.sign(m_b) and (abs(t_a) >= 2 or abs(t_b) >= 2):
        return "Lead (one period)"
    return "No effect"


def load_all() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="qt_"))
    db = ROOT / "data" / "market.duckdb"
    shutil.copy2(db, tmp / "s.duckdb")
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", tmp / "s.duckdb.wal")
    con = duckdb.connect(str(tmp / "s.duckdb"))
    try:
        panel = load_panel(con, start="2010-01-01")
        fo = con.execute("SELECT date, symbol, kind, near_expiry, fut_close, fut_oi, call_oi, put_oi, "
                         "opt_value_lakh FROM nse_fo_daily").df()
        div = con.execute("SELECT ticker AS symbol, date, amount FROM dividends").df()
        nifty = con.execute("SELECT date, close FROM market_index_daily WHERE symbol='NIFTY50' ORDER BY date").df()
        vix = con.execute("SELECT date, close FROM market_index_daily WHERE symbol='INDIAVIX' ORDER BY date").df()
    finally:
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
    fo["date"] = pd.to_datetime(fo["date"])
    fo["near_expiry"] = pd.to_datetime(fo["near_expiry"])
    div["date"] = pd.to_datetime(div["date"])
    s = lambda df: pd.Series(df["close"].to_numpy(float), index=pd.to_datetime(df["date"])).sort_index()  # noqa: E731
    return {"panel": panel, "fo": fo, "div": div, "nifty": s(nifty), "vix": s(vix)}


def main() -> None:  # noqa: C901 — five pre-registered tests, kept in one linear pass
    t0 = time.time()
    log = lambda m: print(f"[{time.time()-t0:5.0f}s] {m}", flush=True)  # noqa: E731
    d = load_all()
    panel, fo = d["panel"], d["fo"]
    close, open_, raw, to = panel["close"], panel["open"], panel["raw_close"], panel["turnover_cr"]
    sessions = close.index
    weeks = week_ends(sessions)
    weeks = weeks[weeks >= pd.Timestamp("2019-10-01")]
    log(f"panel {close.shape}; {len(weeks)} weeks from {weeks[0].date()}")

    fo_s = fo[fo["kind"] == "stock"]
    keep = [c for c in fo_s["symbol"].unique() if c in close.columns]
    fo_s = fo_s[fo_s["symbol"].isin(keep)]
    wide = lambda col: fo_s.pivot_table(index="date", columns="symbol", values=col, aggfunc="last") \
        .reindex(index=sessions, columns=pd.Index(keep))  # noqa: E731
    fut_close_w = wide("fut_close")
    member = fut_close_w.notna().rolling(10, min_periods=1).max().astype(bool)
    log(f"F&O stock symbols matched to panel: {len(keep)}")

    fwd5 = forward_open_returns(open_, 5)
    fwd20 = forward_open_returns(open_, 20)

    def weekly_excess(fwd: pd.DataFrame) -> pd.DataFrame:
        f = fwd.reindex(weeks)[keep].where(member.reindex(weeks))
        return f.sub(f.mean(axis=1), axis=0)

    ex5, ex20 = weekly_excess(fwd5), weekly_excess(fwd20)

    md: list[str] = []
    summary: list[dict] = []

    # ── Q1 excess carry ─────────────────────────────────────────────────────────
    ne_w = wide("near_expiry").reindex(weeks)
    fcl = fut_close_w.reindex(weeks)
    spot = raw.reindex(weeks)[keep]
    days = (ne_w - weeks.to_numpy()[:, None]).apply(lambda s_: s_.dt.days) if hasattr(ne_w, "apply") else None
    days = pd.DataFrame({c: (ne_w[c] - weeks).dt.days for c in ne_w.columns}, index=weeks)
    with np.errstate(invalid="ignore", divide="ignore"):
        basis = (fcl / spot - 1).to_numpy() * (365.0 / days.to_numpy()) - RF
    basis = pd.DataFrame(basis, index=weeks, columns=keep).where(days >= 3)
    n_before = int(basis.notna().sum().sum())
    basis = basis.where(basis.abs() <= BASIS_CAP)
    dropped_cap = n_before - int(basis.notna().sum().sum())
    # strip symbol-weeks with an ex-dividend inside (week, near_expiry]
    div = d["div"][d["div"]["symbol"].isin(keep)]
    div_dates = {s_: np.sort(g["date"].to_numpy()) for s_, g in div.groupby("symbol")}
    stripped = 0
    for c in basis.columns:
        dd = div_dates.get(c)
        if dd is None or not len(dd):
            continue
        nxt = np.searchsorted(dd, weeks.to_numpy(), side="right")
        has_next = nxt < len(dd)
        next_div = np.where(has_next, dd[np.minimum(nxt, len(dd) - 1)], np.datetime64("2100-01-01"))
        inside = has_next & (next_div <= ne_w[c].to_numpy())
        stripped += int((inside & basis[c].notna().to_numpy()).sum())
        basis.loc[inside, c] = np.nan
    basis = basis.where(member.reindex(weeks))
    rank = basis.rank(axis=1, pct=True)
    q_of = lambda r: np.ceil(r * 5).clip(1, 5)  # noqa: E731
    quint = q_of(rank)
    rows_q1 = []
    bot_series = {}
    for h, ex in ((5, ex5), (20, ex20)):
        for q in range(1, 6):
            m = ex.where(quint == q).mean(axis=1)
            rec = {"h": h, "quintile": q, "events": int((quint == q).sum().sum())}
            for pname, p in (("P-a", P_A), ("P-b", P_B)):
                mm, tt, n = nw_t(m[in_period(m.index, p)], NW_LAGS[h])
                rec[f"{pname} mean%"] = round(mm * 100, 3) if np.isfinite(mm) else np.nan
                rec[f"{pname} t"] = round(tt, 2) if np.isfinite(tt) else np.nan
            rows_q1.append(rec)
            if q == 1:
                bot_series[h] = m
    q1_tbl = pd.DataFrame(rows_q1)
    b20 = bot_series[20]
    ma, ta, _ = nw_t(b20[in_period(b20.index, P_A)], 4)
    mb, tb, _ = nw_t(b20[in_period(b20.index, P_B)], 4)
    q1_verdict = verdict_directional(ma, ta, mb, tb, h_sign=-1)
    spread20 = (ex20.where(quint == 5).mean(axis=1) - ex20.where(quint == 1).mean(axis=1))
    sa = nw_t(spread20[in_period(spread20.index, P_A)], 4)
    sb = nw_t(spread20[in_period(spread20.index, P_B)], 4)
    pd.DataFrame({"bottom_h20": b20, "bottom_h5": bot_series[5], "spread_q5_q1_h20": spread20}) \
        .to_csv(OUT / "qt_q1_weekly.csv")
    summary.append({"test": "Q1 excess carry (FUT-04)", "H": "discount quintile lags h20",
                    "P-a": f"{ma*100:+.2f}% (t {ta:.1f})", "P-b": f"{mb*100:+.2f}% (t {tb:.1f})",
                    "verdict": q1_verdict})
    md += ["## Q1 — Excess carry (stock-futures basis − 6.5%), FUT-04",
           f"Weekly quintiles within F&O names; ex-div symbol-weeks stripped: {stripped:,}; "
           f"|basis|>{BASIS_CAP:.0%}/yr dropped: {dropped_cap:,}; days-to-expiry ≥ 3.",
           "", q1_tbl.to_string(index=False), "",
           f"- Bottom (discount) quintile, h20: P-a {ma*100:+.2f}% (t {ta:.2f}) · P-b {mb*100:+.2f}% (t {tb:.2f}) "
           f"→ **{q1_verdict}**",
           f"- Q5−Q1 spread h20: P-a {sa[0]*100:+.2f}% (t {sa[1]:.2f}) · P-b {sb[0]*100:+.2f}% (t {sb[1]:.2f})", ""]
    log("Q1 done")

    # ── Q2 O/S ₹-proxy ──────────────────────────────────────────────────────────
    optv = wide("opt_value_lakh")
    opt5 = optv.rolling(5, min_periods=3).sum().reindex(weeks)
    cash5 = (to[keep] * 100).rolling(5, min_periods=3).sum().reindex(weeks)
    os_ = (opt5 / cash5.where(cash5 > 0)).where(member.reindex(weeks))
    qos = q_of(os_.rank(axis=1, pct=True))
    rows_q2, top_series = [], {}
    for h, ex in ((5, ex5), (20, ex20)):
        for q in (1, 5):
            m = ex.where(qos == q).mean(axis=1)
            rec = {"h": h, "quintile": q}
            for pname, p in (("P-a", P_A), ("P-b", P_B)):
                mm, tt, n = nw_t(m[in_period(m.index, p)], NW_LAGS[h])
                rec[f"{pname} mean%"], rec[f"{pname} t"] = round(mm * 100, 3), round(tt, 2)
            rows_q2.append(rec)
            if q == 5:
                top_series[h] = m
    verd2 = {}
    for h in (5, 20):
        m = top_series[h]
        ma2, ta2, _ = nw_t(m[in_period(m.index, P_A)], NW_LAGS[h])
        mb2, tb2, _ = nw_t(m[in_period(m.index, P_B)], NW_LAGS[h])
        verd2[h] = (ma2, ta2, mb2, tb2, verdict_directional(ma2, ta2, mb2, tb2, h_sign=-1))
    q2_verdict = f"h5: {verd2[5][4]} · h20: {verd2[20][4]}"
    pd.DataFrame({f"top_h{h}": top_series[h] for h in (5, 20)}).to_csv(OUT / "qt_q2_weekly.csv")
    summary.append({"test": "Q2 O/S ₹-proxy (OPT-08)", "H": "top quintile lags h5 & h20",
                    "P-a": f"{verd2[20][0]*100:+.2f}% (t {verd2[20][1]:.1f}) h20",
                    "P-b": f"{verd2[20][2]*100:+.2f}% (t {verd2[20][3]:.1f}) h20", "verdict": q2_verdict})
    md += ["## Q2 — Option-to-stock ₹-volume (O/S proxy), OPT-08",
           "5-session option ₹-value / 5-session cash turnover, weekly quintiles within F&O names.",
           "", pd.DataFrame(rows_q2).to_string(index=False), "",
           f"- Top-quintile verdicts: **{q2_verdict}**", ""]
    log("Q2 done")

    # ── Q3 variance risk premium ────────────────────────────────────────────────
    nifty, vix = d["nifty"], d["vix"]
    lr = np.log(nifty / nifty.shift(1))
    rv21 = lr.rolling(21, min_periods=18).var() * 252
    vrp = ((vix / 100) ** 2).reindex(rv21.index) - rv21
    etf_mask = pd.Series([is_etf(c) for c in close.columns], index=close.columns)
    L = panel["series"].eq("EQ") & raw.ge(20) & to.rolling(20, min_periods=10).median().ge(5) \
        & close.notna().cumsum().ge(250) & ~etf_mask
    ew_ret = close.pct_change(fill_method=None).where(L.shift(1, fill_value=False)).mean(axis=1)
    ew_idx = (1 + ew_ret.fillna(0)).cumprod()
    me = month_ends(nifty.index.intersection(vrp.dropna().index))
    rows_q3, verd3 = [], {}
    q3_store = {}
    for pname, p in (("P1 2009-10→2019-12", Q3_P1), ("P2 2020→2026-10", Q3_P2)):
        mz = me[(me >= p[0]) & (me <= p[1])]
        v = vrp.reindex(mz)
        terc = pd.qcut(v, 3, labels=[1, 2, 3])
        for h in (20, 60):
            fwd_n = nifty.reindex(nifty.index).shift(-h).reindex(mz) / nifty.reindex(mz) - 1
            ew_on = ew_idx.reindex(mz, method="ffill")
            fwd_e = ew_idx.shift(-h).reindex(mz, method="ffill") / ew_on - 1
            for name, fwd in (("NIFTY", fwd_n), ("EW-L", fwd_e)):
                hi, lo = fwd[terc == 3], fwd[terc == 1]
                mh, th, nh = nw_t(hi, max(1, h // 21))
                ml, tl, nl = nw_t(lo, max(1, h // 21))
                diff = mh - ml
                se = math.sqrt((mh / th) ** 2 + (ml / tl) ** 2) if th and tl and np.isfinite(th) and np.isfinite(tl) and th != 0 and tl != 0 else np.nan
                td = diff / se if se and np.isfinite(se) and se > 0 else np.nan
                rows_q3.append({"period": pname, "h": h, "ret of": name, "High%": round(mh * 100, 2),
                                "Low%": round(ml * 100, 2), "High−Low%": round(diff * 100, 2),
                                "t(diff)": round(td, 2) if np.isfinite(td) else np.nan, "n": nh + nl})
                if name == "NIFTY" and h == 20:
                    verd3[pname] = (diff, td)
                q3_store[(pname, h, name)] = (diff, td)
    (p1d, p1t), (p2d, p2t) = verd3["P1 2009-10→2019-12"], verd3["P2 2020→2026-10"]
    q3_verdict = verdict_directional(p1d, p1t, p2d, p2t, h_sign=+1)
    pd.DataFrame({"vrp": vrp.reindex(me)}).to_csv(OUT / "qt_q3_monthly.csv")
    summary.append({"test": "Q3 variance risk premium (POS-05)", "H": "high VRP → higher fwd returns",
                    "P-a": f"{p1d*100:+.2f}pp (t {p1t:.1f}) h20 NIFTY", "P-b": f"{p2d*100:+.2f}pp (t {p2t:.1f})",
                    "verdict": q3_verdict})
    md += ["## Q3 — Variance risk premium (POS-05)",
           "(VIX/100)² − 21-session realised NIFTY variance; monthly terciles within each period; "
           "index close-to-close forward returns (no open series for indices). EW-L leg starts ~2011 (panel history).",
           "", pd.DataFrame(rows_q3).to_string(index=False), "",
           f"- Primary (NIFTY h20 High−Low): **{q3_verdict}**", ""]
    log("Q3 done")

    # ── Q4 index OI-PCR ─────────────────────────────────────────────────────────
    fo_n = fo[(fo["kind"] == "index") & (fo["symbol"] == "NIFTY")].set_index("date").sort_index()
    pcr = (fo_n["put_oi"] / fo_n["call_oi"].where(fo_n["call_oi"] > 0)).reindex(sessions)
    pctl = pcr.rolling(252, min_periods=200).rank(pct=True)
    chg5 = pcr - pcr.shift(5)
    wk4 = weeks[weeks >= pd.Timestamp("2020-10-01")]           # percentile needs ~1y of PCR history
    rows_q4, best = [], []
    q4_csv = {}
    for sig_name, sig in (("level pctl", pctl), ("5-session change", chg5)):
        sv = sig.reindex(wk4)
        for pname, p in (("P-a*", (pd.Timestamp("2020-10-01"), P_A[1])), ("P-b", P_B)):
            mask = in_period(sv.index, p)
            s_ = sv[mask]
            if s_.notna().sum() < 30:
                continue
            terc = pd.qcut(s_, 3, labels=[1, 2, 3], duplicates="drop")
            for h in (5, 10, 20):
                fwd_n = nifty.shift(-h).reindex(s_.index) / nifty.reindex(s_.index) - 1
                hi, lo = fwd_n[terc == 3], fwd_n[terc == 1]
                mh, th, _ = nw_t(hi, NW_LAGS[h])
                ml, tl, _ = nw_t(lo, NW_LAGS[h])
                diff = mh - ml
                se = math.sqrt((mh / th) ** 2 + (ml / tl) ** 2) if th and tl and np.isfinite(th) and np.isfinite(tl) and th != 0 and tl != 0 else np.nan
                td = diff / se if se and np.isfinite(se) and se > 0 else np.nan
                rows_q4.append({"signal": sig_name, "period": pname, "h": h, "High−Low%": round(diff * 100, 2),
                                "t": round(td, 2) if np.isfinite(td) else np.nan})
                best.append((sig_name, h, pname, diff, td))
        q4_csv[sig_name] = sv
    q4_tbl = pd.DataFrame(rows_q4)
    verd4 = "No effect"
    for sig_name in ("level pctl", "5-session change"):
        for h in (5, 10, 20):
            got = {pn: (df_, td_) for sn, hh, pn, df_, td_ in best if sn == sig_name and hh == h}
            if "P-a*" in got and "P-b" in got:
                (da, ta4), (db, tb4) = got["P-a*"], got["P-b"]
                v = verdict_exploratory(da, ta4, db, tb4)
                if v.startswith("Lead (both"):
                    verd4 = f"Lead — {sig_name} h{h} (both periods)"
                    break
                if v.startswith("Lead") and verd4 == "No effect":
                    verd4 = f"Lead (one period) — {sig_name} h{h}"
        if verd4.startswith("Lead —"):
            break
    pd.DataFrame(q4_csv).to_csv(OUT / "qt_q4_weekly.csv")
    summary.append({"test": "Q4 index OI-PCR (POS-06)", "H": "exploratory (both signs)",
                    "P-a": "see table", "P-b": "see table", "verdict": verd4})
    md += ["## Q4 — NIFTY OI put-call ratio (POS-06)",
           "Level percentile (252-session window; usable from 2020-10, so P-a* = 2020-10→2023-12) and 5-session "
           "change; terciles per period; NIFTY close-to-close forward returns. Exploratory: best verdict = Lead.",
           "", q4_tbl.to_string(index=False), "", f"- Verdict: **{verd4}**", ""]
    log("Q4 done")

    # ── Q5 F&O entry/exit events ────────────────────────────────────────────────
    first = fo_s.groupby("symbol")["date"].min()
    last = fo_s.groupby("symbol")["date"].max()
    data_start, data_end = fo_s["date"].min(), fo_s["date"].max()
    entries = first[first > data_start + pd.Timedelta(days=60)]
    exits = last[last < data_end - pd.Timedelta(days=14)]
    ret = close.pct_change(fill_method=None)
    exc = ret.sub(ew_ret, axis=0)
    pos_of = {dte: i for i, dte in enumerate(sessions)}

    def event_rows(ev: pd.Series, kind: str) -> list[dict]:
        rows = []
        for sym, dte in ev.items():
            if sym not in exc.columns:
                continue
            i = sessions.searchsorted(dte)
            if i >= len(sessions):
                continue
            path = exc[sym].to_numpy()
            if kind == "exit":          # must keep trading in cash ≥ 40 of next 60 sessions (else delisting)
                seg = close[sym].to_numpy()[i + 1:i + 61]
                if np.isfinite(seg).sum() < 40:
                    continue
            c20 = np.nansum(path[i + 1:i + 21])
            c60 = np.nansum(path[i + 1:i + 61])
            if not np.isfinite(path[i + 1:i + 61]).any():
                continue
            rows.append({"symbol": sym, "type": kind, "date": sessions[min(i, len(sessions) - 1)],
                         "cum20": c20, "cum60": c60})
        return rows

    ev_rows = event_rows(entries, "entry") + event_rows(exits, "exit")
    ev_df = pd.DataFrame(ev_rows)
    ev_df.to_csv(OUT / "qt_q5_events.csv", index=False)
    md_q5 = ["## Q5 — F&O inclusion / exclusion events (EVT-03)",
             "Cumulative excess vs EW liquid universe, sessions +1…+20 and +1…+60; exits require the stock to keep "
             "trading in cash (≥ 40 of 60 sessions) so delistings are excluded; entry events within 60 days of the "
             "2019-10 data start dropped (left-censoring). Same-date clusters averaged first (NSE revises in batches).",
             ""]
    q5_cells = []
    for kind in ("entry", "exit"):
        g = ev_df[ev_df["type"] == kind]
        by_date = g.groupby("date")[["cum20", "cum60"]].mean()
        n_ev, n_cl = len(g), len(by_date)
        for col, hh in (("cum20", 20), ("cum60", 60)):
            x = by_date[col].to_numpy()
            if len(x) < 3:
                q5_cells.append({"event": kind, "h": hh, "events": n_ev, "clusters": n_cl,
                                 "mean%": np.nan, "CI95": "n too small"})
                continue
            m, se = float(np.mean(x)), float(np.std(x, ddof=1) / math.sqrt(len(x)))
            q5_cells.append({"event": kind, "h": hh, "events": n_ev, "clusters": n_cl,
                             "mean%": round(m * 100, 2),
                             "CI95": f"[{(m-1.96*se)*100:+.2f}, {(m+1.96*se)*100:+.2f}]"})
    md_q5 += [pd.DataFrame(q5_cells).to_string(index=False), "",
              "- Descriptive only (pre-registered: no gate; small n, clustered revision dates).", ""]
    md += md_q5
    ent_m = pd.DataFrame(q5_cells).query("event=='entry' and h==60")["mean%"]
    ext_m = pd.DataFrame(q5_cells).query("event=='exit' and h==60")["mean%"]
    summary.append({"test": "Q5 F&O entry/exit (EVT-03)", "H": "descriptive",
                    "P-a": f"entry +60s: {float(ent_m.iloc[0]) if len(ent_m) else float('nan')}%",
                    "P-b": f"exit +60s: {float(ext_m.iloc[0]) if len(ext_m) else float('nan')}%",
                    "verdict": "descriptive (no gate)"})
    log("Q5 done")

    head = ["# Appendix Q quick tests — results (run once, as pre-registered)",
            f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} by `alpha_lab/strategies/quick_tests.py`. "
            "Gross diagnostics, weekly frame, NW t; NOT strategies and NOT net of costs. "
            "Pass bar fixed in PLAN.md Appendix Q before the run.", "",
            pd.DataFrame(summary).to_string(index=False), "",
            "A 'Robust'/'Lead' here is a candidate for a future pre-registered strategy study — never a live rule.", ""]
    (OUT / "quick_tests_RESULTS.md").write_text("\n".join(head + md) + "\n")
    log("report written → alpha_lab/reports/quick_tests_RESULTS.md")


if __name__ == "__main__":
    main()
