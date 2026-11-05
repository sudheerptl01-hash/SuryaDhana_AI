"""TV-IVRV — do the IV − RV spread and the IV percentile forecast NSE index volatility or returns?

Pre-registered plan (written before any result): `reports/terminal_v2/studies/iv_rv/PLAN.md`. Graded: G1 (seller's
claim: slope of iv30_cm − RVF on S, sign +, with the short-straddle leg TL1), G2 (information claim: partial slope of S in
RVF given rv20, sign +, ceiling CONTEXT-ONLY), G3 (buy-fear claim: slope of the 20-session return on S, sign +, with the
long/flat leg TL2), for S1 = iv30_cm − rv20_cc and S2 = iv_pctile_252, NIFTY graded and BANKNIFTY replication; S3 =
iv_rank_252 reported only. Negative controls N1–N3 void, N4 (the option-free spread rv60 − rv20) caps.

Reads a DuckDB READ-ONLY (`--db`: production tables `iv_summary_daily`, `iv_expiry_daily`, `index_ohlc_daily`; `--aux`:
the study-only `study_fo_contracts` / `study_index_close` from `build_inputs.py --fo`, default = `--db`). No network.
Exit 0 ran · 3 data not yet ingested · 4 insufficient history / a data-quality gate failed · 5 live file busy.
"""
from __future__ import annotations

import argparse
import json
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal_studies import common as C

STUDY = "TV-IVRV"
STUDY_DIR = C.STUDIES_DIR / "iv_rv"
SPLIT = "2023-09-30"
LAGS = 19                       # 20-session overlapping windows
TL1_LAGS = 21                   # straddles held ~21 sessions overlap
MIN_GRADED = 750
MIN_TRANCHES = 300
GATE_IV30_MEDIAN_ABS = 0.05     # vol-pt vs the R-IV prototype (G2 replay rule)
GATE_RV_TOL = 0.01
GATE_RV_SHARE = 0.99
SYMBOLS = ("NIFTY", "BANKNIFTY")
SIGNALS = {"S1": "IV − RV spread (iv30_cm − rv20_cc)", "S2": "IV percentile (iv_pctile_252)", "S3": "IV rank (iv_rank_252)"}
GRADED_SIGNALS = ("S1", "S2")
STAT_NAMES = {"G1": "seller's edge iv30_cm − RVF (sign +)", "G2": "RVF given rv20 (information, sign +)",
              "G3": "next-20-session return (buy fear, sign +)"}
EXPIRY_DTE = (21, 45)
EXPIRY_TARGET = 30
STRIKE_BAND = 0.01


# ── loaders ───────────────────────────────────────────────────────────────────────────────────────────────────────

def load_index_close(con: Any, aux: Any, symbol: str) -> pd.Series:
    """NSE's daily index closes: the study table (CSV + UDiFF underlying), overlaid by production's `index_ohlc_daily`
    rows from the NSE daily file where stored. Never Yahoo."""
    parts: list[pd.Series] = []
    if C.table_exists(aux, "study_index_close"):
        s = aux.execute("SELECT date, close FROM study_index_close WHERE symbol = ? ORDER BY date", [symbol]).df()
        parts.append(pd.Series(s["close"].to_numpy(dtype=float), index=pd.to_datetime(s["date"])))
    if C.table_exists(con, "index_ohlc_daily"):
        p = con.execute("SELECT date, close FROM index_ohlc_daily WHERE symbol = ? AND source = 'nse_daily_file' ORDER BY date",
                        [C.INDEX_NAME[symbol]]).df()
        if not p.empty:
            parts.append(pd.Series(p["close"].to_numpy(dtype=float), index=pd.to_datetime(p["date"])))
    if not parts or all(x.empty for x in parts):
        raise C.DataNotIngested(f"index closes for {symbol} (study_index_close / index_ohlc_daily)")
    out = parts[0]
    for x in parts[1:]:
        out = x.combine_first(out) if not out.empty else x
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[out > 0]


def load_iv(con: Any, symbol: str) -> pd.DataFrame:
    C.require(con, "iv_summary_daily", "the O-T4 IV backfill, or build_inputs.py --fo")
    df = con.execute("""SELECT date, iv30_cm, iv_pctile_252, iv_rank_252, monthly_atm_iv, rv20_cc, quality_flags
                        FROM iv_summary_daily WHERE symbol = ? AND model_version = ? ORDER BY date""", [symbol, C.MODEL_VERSION]).df()
    if df.empty:
        raise C.DataNotIngested(f"iv_summary_daily rows for {symbol} ({C.MODEL_VERSION})")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")


def build_frame(iv: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    """One row per index session: the signals (dated T) and the targets (windows from the close of T+1)."""
    f = pd.DataFrame(index=close.index)
    f["close"] = close
    f["rv20"] = C.trailing_rv(close, 20)
    f["rv60"] = C.trailing_rv(close, 60)
    f["RVF"] = C.forward_rv(close)
    f["RET"] = C.forward_ret(close)
    f = f.join(iv[["iv30_cm", "iv_pctile_252", "iv_rank_252", "monthly_atm_iv", "rv20_cc", "quality_flags"]], how="left")
    bad = f["quality_flags"].fillna("").str.contains("no_cm30")
    base = f["iv30_cm"].where(f["iv30_cm"].notna(), f["monthly_atm_iv"])
    f["n_prior_iv"] = base.notna().astype(int).cumsum().shift(1).fillna(0)
    ok_iv = ~bad & (f["n_prior_iv"] >= C.WARMUP)
    f["S1"] = (f["iv30_cm"] - f["rv20"]).where(ok_iv)
    f["S2"] = f["iv_pctile_252"].where(ok_iv)
    f["S3"] = f["iv_rank_252"].where(ok_iv)
    f["S1star"] = (f["rv60"] - f["rv20"]).where(ok_iv)
    f["VRPR"] = f["iv30_cm"] - f["RVF"]
    return f


def data_gates(f: pd.DataFrame, symbol: str, iv: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {"iv_rows": len(iv), "iv_rows_off_calendar": int((~iv.index.isin(f.index)).sum())}
    if symbol == "NIFTY" and C.R_IV_COMPARE.exists():
        ref = pd.read_csv(C.R_IV_COMPARE, usecols=["date", "iv30_cm"], parse_dates=["date"]).set_index("date")["iv30_cm"]
        both = pd.concat([f["iv30_cm"], ref.rename("ref")], axis=1).dropna()
        med = float((both["iv30_cm"] - both["ref"]).abs().median()) if len(both) else float("nan")
        out["gate_iv30_vs_prototype"] = {"n": len(both), "median_abs_diff": med, "pass": bool(len(both) and med <= GATE_IV30_MEDIAN_ABS)}
    stored = f[["rv20_cc", "rv20"]].dropna()
    if len(stored):
        share = float(((stored["rv20_cc"] - stored["rv20"]).abs() <= GATE_RV_TOL).mean())
        out["gate_rv20_stored_vs_recomputed"] = {"n": len(stored), "share_within": share, "pass": share >= GATE_RV_SHARE}
    else:
        out["gate_rv20_stored_vs_recomputed"] = {"n": 0, "note": "no stored rv20_cc (index_ohlc_daily not backfilled): recomputed", "pass": True}
    out["no_cm30_rows"] = int(f["quality_flags"].fillna("").str.contains("no_cm30").sum())
    return out


# ── graded statistics ─────────────────────────────────────────────────────────────────────────────────────────────

def stat_set(f: pd.DataFrame, s: pd.Series) -> dict[str, dict[str, Any]]:
    """G1–G3 for one signal series aligned to `f`."""
    d = f.assign(_s=s)
    return {"G1": C.slope_by_halves(d["VRPR"], d[["_s"]], "_s", LAGS, SPLIT),
            "G2": C.slope_by_halves(d["RVF"], d[["_s", "rv20"]], "_s", LAGS, SPLIT),
            "G3": C.slope_by_halves(d["RET"], d[["_s"]], "_s", LAGS, SPLIT)}


def graded_rows(f: pd.DataFrame, col: str) -> pd.DataFrame:
    return f[f[col].notna() & f["RVF"].notna() & f["RET"].notna() & f["VRPR"].notna() & f["rv20"].notna()]


def controls(f: pd.DataFrame, col: str) -> dict[str, dict[str, dict[str, Any]]]:
    g = graded_rows(f, col)
    lagged = C.placebo_lag(f[col]).reindex(g.index)
    return {"N1_lag250": stat_set(g, lagged), "N2_circular_shift": stat_set(g, C.circular_shift(g[col])),
            "N3_permutation": stat_set(g, C.permute(g[col]))}


# ── traded legs ───────────────────────────────────────────────────────────────────────────────────────────────────

def straddle_tranches(con: Any, aux: Any, symbol: str, close: pd.Series) -> pd.DataFrame:
    """TL1: for each decision date T the 30-day ATM straddle sold at the close of T+1 and held to expiry (PLAN)."""
    C.require(con, "iv_expiry_daily")
    C.require(aux, "study_fo_contracts", "build_inputs.py --fo")
    ex = con.execute("SELECT date, expiry, dte, forward FROM iv_expiry_daily WHERE symbol = ? AND forward > 0 ORDER BY date, expiry",
                     [symbol]).df()
    if ex.empty:
        raise C.DataNotIngested(f"iv_expiry_daily rows for {symbol}")
    ex["date"], ex["expiry"] = pd.to_datetime(ex["date"]), pd.to_datetime(ex["expiry"])
    ex = ex[(ex["dte"] >= EXPIRY_DTE[0]) & (ex["dte"] <= EXPIRY_DTE[1])].copy()
    ex["gap"] = (ex["dte"] - EXPIRY_TARGET).abs()
    pick = ex.sort_values(["date", "gap", "dte"]).groupby("date", as_index=False).first()[["date", "expiry", "dte", "forward"]]
    aux.register("pick", pick)
    opt = aux.execute("""SELECT c.date, c.expiry, c.strike, c.opt_type, c.close, c.volume FROM study_fo_contracts c
                         JOIN pick p ON c.date = p.date AND c.expiry = p.expiry
                         WHERE c.symbol = ? AND c.instrument = 'OPT' AND c.volume > 0 AND c.close > 0""", [symbol]).df()
    aux.unregister("pick")
    opt["date"], opt["expiry"] = pd.to_datetime(opt["date"]), pd.to_datetime(opt["expiry"])
    wide = opt.pivot_table(index=["date", "expiry", "strike"], columns="opt_type", values="close", aggfunc="first").dropna(subset=["CE", "PE"])
    wide = wide.reset_index().merge(pick, on=["date", "expiry"])
    wide["dist"] = (wide["strike"] / wide["forward"] - 1).abs()
    wide = wide[wide["dist"] <= STRIKE_BAND].sort_values(["date", "dist"]).groupby("date", as_index=False).first()
    entry = wide.set_index("date")
    sessions = close.index
    rows = []
    for i in range(len(sessions) - 1):
        t, e0 = sessions[i], sessions[i + 1]
        if e0 not in entry.index:
            continue
        r = entry.loc[e0]
        settle = close.get(pd.Timestamp(r["expiry"]))
        if settle is None or not np.isfinite(settle):
            continue
        pnl = C.straddle_to_expiry_pnl_pct(r["CE"], r["PE"], r["strike"], r["forward"], float(settle))
        gross = (r["CE"] + r["PE"] - abs(float(settle) - r["strike"])) / r["forward"] * 100
        rows.append({"date": t, "entry": e0, "expiry": r["expiry"], "dte": int(r["dte"]), "strike": r["strike"], "forward": r["forward"],
                     "call": r["CE"], "put": r["PE"], "settle": float(settle), "pnl_pct": pnl, "gross_pct": gross})
    return pd.DataFrame(rows).set_index("date") if rows else pd.DataFrame(columns=["pnl_pct"])


def cond_minus_all(pnl: pd.Series, cond: pd.Series, lags: int, split: str) -> dict[str, Any]:
    """(i) mean P&L of the conditional tranches minus the mean of ALL tranches in the same span (full / each half)."""
    d = pd.concat([pnl.rename("p"), cond.rename("c")], axis=1).dropna()
    h1, h2 = C.half_masks(d.index, split)
    out: dict[str, Any] = {}
    for tag, m in (("full", np.ones(len(d), dtype=bool)), ("h1", h1), ("h2", h2)):
        part = d[m]
        x = part.loc[part["c"] == 1, "p"] - part["p"].mean()
        out[f"mean_{tag}"] = float(x.mean()) if len(x) else float("nan")
        out[f"t_{tag}"] = C.newey_west_t(x, lags) if len(x) >= 4 else float("nan")
        out[f"n_{tag}"] = len(x)
    return out


def tl1(tranches: pd.DataFrame, s: pd.Series) -> dict[str, Any]:
    if tranches.empty:
        return {"n": 0, "ok": False}
    cond = C.top_tercile(s).reindex(tranches.index)
    d = pd.concat([tranches["pnl_pct"], cond.rename("c")], axis=1).dropna()
    diff = cond_minus_all(d["pnl_pct"], d["c"], TL1_LAGS, SPLIT)
    own = C.mean_by_halves(d.loc[d["c"] == 1, "pnl_pct"], TL1_LAGS, SPLIT)
    allm = C.mean_by_halves(d["pnl_pct"], TL1_LAGS, SPLIT)
    ok = C.traded_leg_ok(diff) and C.traded_leg_ok(own)
    return {"n": len(d), "n_conditional": int((d["c"] == 1).sum()), "cond_minus_all": diff, "conditional_after_costs": own,
            "unconditional_after_costs": allm, "ok": bool(ok)}


def tl2(close: pd.Series, s: pd.Series, cost_rt: float) -> dict[str, Any]:
    ind = C.top_tercile(s)
    r_next = close.shift(-2) / close.shift(-1) - 1.0
    d = pd.concat([ind.rename("ind"), r_next.rename("r")], axis=1).dropna()
    if len(d) < 300:
        return {"n": len(d), "ok": False}
    pos = d["ind"].rolling(C.HORIZON, min_periods=1).mean()
    wf = C.evaluate_long_flat(pos, d["r"], h=C.HORIZON, periods_per_year=252, cost_rt=cost_rt, is_end=0, warmup=0)
    t1, t2, cut = C.oos_halves_t(wf, C.HORIZON, split=SPLIT)
    stats = {"t_full": wf.get("OOS_t_excess", float("nan")), "t_h1": t1, "t_h2": t2}
    return {"n": len(d), "cost_rt_pct": cost_rt, "excess_pa_pct": wf.get("OOS_excess_vs_scaled_pa_pct"),
            "exposure_pct": wf.get("OOS_exposure_pct"), "strat_cagr": wf.get("OOS_strat_cagr"), "bh_cagr": wf.get("OOS_bh_cagr"),
            **stats, "split": cut, "ok": C.traded_leg_ok(stats)}


# ── one underlying ────────────────────────────────────────────────────────────────────────────────────────────────

def run_symbol(con: Any, aux: Any, symbol: str, cash_cost: float) -> dict[str, Any]:
    iv = load_iv(con, symbol)
    close = load_index_close(con, aux, symbol)
    f = build_frame(iv, close)
    gates = data_gates(f, symbol, iv)
    out: dict[str, Any] = {"symbol": symbol, "gates": gates, "signals": {}}
    n_graded = len(graded_rows(f, "S2"))
    out["n_graded"] = n_graded
    out["span"] = [str(graded_rows(f, "S2").index.min().date()) if n_graded else None, str(graded_rows(f, "S2").index.max().date()) if n_graded else None]
    if n_graded < MIN_GRADED:
        raise C.InsufficientHistory(f"{symbol}: {n_graded} graded sessions < {MIN_GRADED}")
    tranches = straddle_tranches(con, aux, symbol, close)
    out["tl1_tranches"] = len(tranches)
    for col in SIGNALS:
        g = graded_rows(f, col)
        st = stat_set(g, g[col])
        rec: dict[str, Any] = {"stats": st, "n": len(g)}
        if col in GRADED_SIGNALS:
            rec["controls"] = controls(f, col)
            rec["TL1"] = tl1(tranches, f[col]) if len(tranches) >= MIN_TRANCHES else {"n": len(tranches), "ok": False,
                                                                                   "note": f"< {MIN_TRANCHES} tranches"}
            rec["TL2"] = tl2(close, f[col].where(f.index.isin(g.index)), cash_cost)
            rec["TL2_floor_sensitivity"] = tl2(close, f[col].where(f.index.isin(g.index)), C.FLOOR_PCT)
            if col == "S1":
                gs = graded_rows(f, "S1star")
                rec["N4_option_free"] = stat_set(gs, gs["S1star"])
        out["signals"][col] = rec
    out["_frame"] = f
    out["_tranches"] = tranches
    return out


def verdicts(res: dict[str, dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Apply the PLAN's verdict rule to every graded entry (both underlyings)."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for sym, r in res.items():
        out[sym] = {}
        for col in GRADED_SIGNALS:
            rec = r["signals"][col]
            for g in ("G1", "G2", "G3"):
                st = rec["stats"][g]
                traded = rec["TL1"].get("ok") if g == "G1" else (rec["TL2"].get("ok") if g == "G3" else None)
                ceiling = C.CONTEXT_ONLY if g == "G2" else C.PASS
                v = C.signed_verdict(st["t_full"], st["t_h1"], st["t_h2"], +1, traded_ok=traded, ceiling=ceiling)
                voided = [n for n, cs in rec["controls"].items() if C.meets(cs[g]["t_full"], cs[g]["t_h1"], cs[g]["t_h2"], +1)]
                capped: list[str] = []
                if col == "S1" and g in ("G1", "G2"):
                    n4 = rec["N4_option_free"][g]
                    if C.meets(n4["t_full"], n4["t_h1"], n4["t_h2"], +1) and abs(n4["t_full"]) >= abs(st["t_full"]):
                        capped.append("N4 option-free spread")
                if sym == "NIFTY" and "BANKNIFTY" in res:
                    other = res["BANKNIFTY"]["signals"][col]["stats"][g]["t_full"]
                    if not C._isnan(other) and other <= -C.T_PASS:
                        capped.append("BANKNIFTY replication opposite sign")
                final, notes = C.apply_controls(v, voided_by=voided, capped_by=capped)
                notes += C.against_sign_note(st["t_full"], st["t_h1"], st["t_h2"], +1)
                out[sym][f"{col}.{g}"] = {"verdict": final, "pre_control": v, "notes": notes, "traded_ok": traded}
    return out


# ── report ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _tl_text(rec: dict[str, Any], g: str) -> str:
    if g == "G1":
        t = rec["TL1"]
        if not t.get("n_conditional"):
            return "TL1 n/a"
        d, o = t["cond_minus_all"], t["conditional_after_costs"]
        return (f"TL1 cond − all {C.fmt(d['mean_full'], 3)} %F (t {C.tstr(d['t_full'])}); cond after costs "
                f"{C.fmt(o['mean_full'], 3)} %F (t {C.tstr(o['t_full'])}; halves {C.tstr(o['t_h1'])} / {C.tstr(o['t_h2'])})")
    if g == "G3":
        t = rec["TL2"]
        return (f"TL2 excess {C.fmt(t.get('excess_pa_pct'), 2)} %/yr after {C.fmt(t.get('cost_rt_pct'), 2)} % RT "
                f"(t {C.tstr(t.get('t_full', float('nan')))}; halves {C.tstr(t.get('t_h1', float('nan')))} / {C.tstr(t.get('t_h2', float('nan')))})")
    return "no traded leg (ceiling CONTEXT-ONLY)"


def render(res: dict[str, dict[str, Any]], verd: dict[str, Any], meta: dict[str, Any], cash_cost: float) -> tuple[str, str, str, list[C.Row]]:
    rows: list[C.Row] = []
    for sym in res:
        for col in GRADED_SIGNALS:
            rec = res[sym]["signals"][col]
            for g in ("G1", "G2", "G3"):
                v = verd[sym][f"{col}.{g}"]
                label = f"{sym} · {col} {SIGNALS[col]} → {STAT_NAMES[g]}"
                extra = _tl_text(rec, g) + (f"; {'; '.join(v['notes'])}" if v["notes"] else "")
                rows.append(C.verdict_row(label, rec["stats"][g], v["verdict"], extra=extra))
    lines = [f"# {STUDY} · IV − RV spread and IV percentile vs next-20-session vol and return — report", "",
             (f"Run {meta['run_at']} · inputs `{meta['db']}` · plan `reports/terminal_v2/studies/iv_rv/PLAN.md` (pre-registered "
             "5 Nov 2026 07:57 IST, before any result)."), "", "## Data-quality gates", ""]
    for sym, r in res.items():
        lines.append(f"- **{sym}**: graded sessions {r['n_graded']} ({r['span'][0]} → {r['span'][1]}); TL1 tranches {r['tl1_tranches']}; "
                     f"gates {json.dumps(C._clean(r['gates']))}")
    lines += ["", "## Graded statistics (signed; t is Newey-West; halves split 30 Sep 2023)", "",
              "| Underlying · signal → statistic | b full (t) | H1 b (t) | H2 b (t) | traded leg | verdict | notes |", "|---|---|---|---|---|---|---|"]
    for sym in res:
        for col in GRADED_SIGNALS:
            rec = res[sym]["signals"][col]
            for g in ("G1", "G2", "G3"):
                st, v = rec["stats"][g], verd[sym][f"{col}.{g}"]
                lines.append(f"| {sym} · {col} → {g} | {C.fmt(st['b_full'], 4)} ({C.tstr(st['t_full'])}) | {C.fmt(st['b_h1'], 4)} "
                             f"({C.tstr(st['t_h1'])}) | {C.fmt(st['b_h2'], 4)} ({C.tstr(st['t_h2'])}) | {_tl_text(rec, g)} | "
                             f"**{v['verdict']}** | {'; '.join(v['notes'])} |")
    lines += ["", "## Negative controls (t full / H1 / H2; a control meeting the statistic's condition voids it)", "",
              "| Underlying · signal | control | G1 | G2 | G3 |", "|---|---|---|---|---|"]
    for sym in res:
        for col in GRADED_SIGNALS:
            rec = res[sym]["signals"][col]
            ctl = dict(rec["controls"])
            if "N4_option_free" in rec:
                ctl["N4_option_free (cap)"] = rec["N4_option_free"]
            for name, cs in ctl.items():
                cells = " | ".join(f"{C.tstr(cs[g]['t_full'])} / {C.tstr(cs[g]['t_h1'])} / {C.tstr(cs[g]['t_h2'])}" for g in ("G1", "G2", "G3"))
                lines.append(f"| {sym} · {col} | {name} | {cells} |")
    lines += ["", "## Traded legs", "",
              (f"Cash cost (TL2): {cash_cost:.3f} % per round trip (`shared/trading_costs.py` default model, ₹1,00,000 tranche); "
              f"option schedule (TL1): `FnoCosts` {json.dumps(meta['fno_costs'])}."), "",
              ("| Underlying · signal | TL1 n (cond) | uncond seller %F (t) | cond − all %F (t; H1 / H2) | cond after costs %F (t; H1 / H2) | "
              "TL2 excess %/yr (t; H1 / H2) | TL2 at 0.15 % floor (t) |"), "|---|---|---|---|---|---|---|"]
    for sym in res:
        for col in GRADED_SIGNALS:
            rec = res[sym]["signals"][col]
            t1, t2, ts = rec["TL1"], rec["TL2"], rec["TL2_floor_sensitivity"]
            if t1.get("n_conditional"):
                u, d, o = t1["unconditional_after_costs"], t1["cond_minus_all"], t1["conditional_after_costs"]
                c1 = f"{t1['n']} ({t1['n_conditional']})"
                c2 = f"{C.fmt(u['mean_full'], 3)} ({C.tstr(u['t_full'])})"
                c3 = f"{C.fmt(d['mean_full'], 3)} ({C.tstr(d['t_full'])}; {C.tstr(d['t_h1'])} / {C.tstr(d['t_h2'])})"
                c4 = f"{C.fmt(o['mean_full'], 3)} ({C.tstr(o['t_full'])}; {C.tstr(o['t_h1'])} / {C.tstr(o['t_h2'])})"
            else:
                c1, c2, c3, c4 = str(t1.get("n", 0)), "—", "—", "—"
            c5 = (f"{C.fmt(t2.get('excess_pa_pct'), 2)} ({C.tstr(t2.get('t_full', float('nan')))}; "
                  f"{C.tstr(t2.get('t_h1', float('nan')))} / {C.tstr(t2.get('t_h2', float('nan')))})")
            c6 = f"{C.fmt(ts.get('excess_pa_pct'), 2)} ({C.tstr(ts.get('t_full', float('nan')))})"
            lines.append(f"| {sym} · {col} | {c1} | {c2} | {c3} | {c4} | {c5} | {c6} |")
    lines += ["", "## Robustness (not graded): S3 = IV rank", "", "| Underlying | G1 b (t) | G2 b (t) | G3 b (t) |", "|---|---|---|---|"]
    for sym in res:
        st = res[sym]["signals"]["S3"]["stats"]
        lines.append(f"| {sym} | " + " | ".join(f"{C.fmt(st[g]['b_full'], 4)} ({C.tstr(st[g]['t_full'])})" for g in ("G1", "G2", "G3")) + " |")
    report = "\n".join(lines) + "\n"
    head = f"# {STUDY} · FINDINGS (IV − RV spread, IV percentile → next-20-session vol / return)"
    verdict_counts = pd.Series([v["verdict"] for s in verd.values() for v in s.values()]).value_counts().to_dict()
    findings = "\n".join([head, "", f"Run {meta['run_at']} on `{meta['db']}`. Plan: `reports/terminal_v2/studies/iv_rv/PLAN.md` "
                          "(pre-registered before any result). Verdict counts over the 12 graded entries: "
                          + ", ".join(f"{k} {v}" for k, v in verdict_counts.items()) + ".", "",
                          "| Signal | Result (full sample) | Both halves |", "|---|---|---|",
                          *[C.study_row(r) for r in rows], "",
                          ("- **Badge consequence:** anything but PASS leaves the panels as they are (`arithmetic` for IV / rank / "
                          "percentile, `context` for the spread). No study result reaches a badge without the PM."),
                          "- Every sentence on a panel still ends \"describes, does not predict\".", ""])
    agg = "\n".join(["| Study · signal (known at release) | Result | Both halves | Verdict |", "|---|---|---|---|",
                     *[C.aggregate_row(STUDY, r) for r in rows]]) + "\n"
    return report, findings, agg, rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TV-IVRV (pre-registered; see the PLAN)")
    ap.add_argument("--db", type=Path, default=C.DEFAULT_INPUTS)
    ap.add_argument("--aux", type=Path, default=None, help="study-only inputs (default: --db)")
    ap.add_argument("--out-dir", type=Path, default=STUDY_DIR)
    ap.add_argument("--results-dir", type=Path, default=None, help="per-session CSVs (default: the scratch area; never committed)")
    ap.add_argument("--provisional", action="store_true", help="stamp every output PROVISIONAL (scratch recomputation)")
    ap.add_argument("--allow-market-hours", action="store_true")
    ap.add_argument("--symbols", nargs="*", default=list(SYMBOLS))
    a = ap.parse_args(argv)
    cash_cost = C.cash_round_trip_pct()
    try:
        with ExitStack() as stack:
            con = stack.enter_context(C.open_inputs(a.db, allow_market_hours=a.allow_market_hours))
            aux = con if a.aux is None else stack.enter_context(C.open_inputs(a.aux, allow_market_hours=a.allow_market_hours))
            res = {sym: run_symbol(con, aux, sym, cash_cost) for sym in a.symbols}
    except C.DataNotIngested as e:
        C.not_ingested(STUDY, str(e), "build_inputs.py --fo (scratch) or the O-T4 backfill", "")
    except C.InsufficientHistory as e:
        C.insufficient(STUDY, str(e))
    except C.LiveFileBusy as e:
        C.live_busy(STUDY, str(e))
    failed = [f"{s}: {k}" for s, r in res.items() for k, g in r["gates"].items() if isinstance(g, dict) and g.get("pass") is False]
    if failed:
        C.insufficient(STUDY, "data-quality gate failed", "; ".join(failed))
    verd = verdicts(res)
    meta = C.run_meta(STUDY, a.db, a.provisional)
    report, findings, agg, _rows = render(res, verd, meta, cash_cost)
    results = {f"frame_{s}": r["_frame"] for s, r in res.items()}
    results.update({f"tl1_tranches_{s}": r["_tranches"] for s, r in res.items()})
    summary = {**meta, "cash_cost_rt_pct": cash_cost, "split": SPLIT,
               "results": {s: {k: v for k, v in r.items() if not k.startswith("_")} for s, r in res.items()}, "verdicts": verd}
    C.write_outputs(a.out_dir, summary=summary, report_md=report, findings_md=findings, findings_row_md=agg, results=results,
                    provisional=a.provisional, results_dir=a.results_dir)
    print(C.status_line(STUDY, "ran", detail=", ".join(f"{s}.{k}={v['verdict']}" for s, d in verd.items() for k, v in d.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
