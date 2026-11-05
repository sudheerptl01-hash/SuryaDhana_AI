"""TV-DRIVERS — do NIFTY's drivers persist, and does a driver change precede anything?

Pre-registered plan (written before any result): `reports/terminal_v2/studies/drivers/PLAN.md`. Graded: D1 (the 20-session
hysteresis leader's share of the next 20 sessions' |points| minus the weight leader's, sign +, ceiling PASS as description),
D2 (signed persistence s·(R_leader − R_NIFTY) over close T+1 → T+21, sign +, with the long-only cash leg TL-D2), D3r / D3v
(after a thinned leader change: NIFTY's next-20 return, two-sided, and the RV change, sign +; ceiling CONTEXT-ONLY). The
fit gate (members priced ≥ 45, trailing-60 mean |residual| / level ≤ 0.10 %) decides which windows count while today's
members stand in for past ones. Controls: N1 weight-proportional random leader, N2 the leader of 250 sessions earlier, N3
shifted events (void); the weight leader in D2 (cap).

Reads READ-ONLY (`--db`): `index_contribution_daily`, `index_contribution_fit`, `index_driver_state` for NIFTY 50. No network.
Exit 0 ran · 3 not ingested · 4 insufficient (the outputs then carry PENDING rows) · 5 live file busy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as sstats

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal_studies import common as C

STUDY = "TV-DRIVERS"
STUDY_DIR = C.STUDIES_DIR / "drivers"
INDEX = "NIFTY 50"
SPLIT = "2023-04-30"
LAGS = 19
FIT_MAE_PCT = 0.10              # trailing-60 mean |residual| / prev level, %
FIT_WINDOW = 60
MIN_PRICED = 45
MIN_DECISIONS = 500
MIN_EVENTS = 20
THIN = 21
NAMES = {"D1": "20-session leader's share of the next 20 sessions minus the weight leader's (sign +)",
         "D2": "the driver keeps driving: s·(R_leader − R_NIFTY), close T+1 → T+21 (sign +)",
         "D3r": "after a leader change: NIFTY next-20 return minus its mean (two-sided)",
         "D3v": "after a leader change: RV change (RVF − rv20) minus its mean (sign +)"}


def load(con: Any) -> dict[str, Any]:
    for t in ("index_contribution_daily", "index_contribution_fit", "index_driver_state"):
        C.require(con, t, "the drivers backfill, or build_inputs.py --drivers")
    contrib = con.execute("""SELECT date, symbol, points, ret_pct, weight_pct FROM index_contribution_daily
                             WHERE index_name = ? ORDER BY date""", [INDEX]).df()
    fit = con.execute("""SELECT date, actual_points, explained_points, residual_points, index_level, prev_index_level, members_priced, weight_method
                         FROM index_contribution_fit WHERE index_name = ? ORDER BY date""", [INDEX]).df()
    state = con.execute("""SELECT date, window_sessions, leader, raw_leader FROM index_driver_state WHERE index_name = ? ORDER BY date""",
                        [INDEX]).df()
    if contrib.empty or fit.empty or state.empty:
        raise C.DataNotIngested(f"drivers tables for {INDEX} are empty")
    for df in (contrib, fit, state):
        df["date"] = pd.to_datetime(df["date"])
    fit = fit.set_index("date").sort_index()
    return {"contrib": contrib, "fit": fit.reindex(session_calendar(con, fit)), "state": state}


def session_calendar(con: Any, fit: pd.DataFrame) -> pd.DatetimeIndex:
    """Every NIFTY session (NSE's index closes in `index_ohlc_daily`, the NSE daily file preferred) from the first fit row
    on — a session the attribution skipped stays in the calendar as a failing row, so no rolling window silently spans a
    gap. Falls back to the fit dates when no index close is stored."""
    if C.table_exists(con, "index_ohlc_daily"):
        cal = con.execute("SELECT DISTINCT date FROM index_ohlc_daily WHERE symbol = ? AND close > 0 ORDER BY date", [INDEX]).df()
        if not cal.empty:
            days = pd.DatetimeIndex(pd.to_datetime(cal["date"]))
            days = days[(days >= fit.index.min()) & (days <= fit.index.max())]
            return days.union(fit.index)
    return pd.DatetimeIndex(fit.index)


def index_level(con: Any, sessions: pd.DatetimeIndex, fit: pd.DataFrame) -> pd.Series:
    """NIFTY 50 closes on the calendar (`index_ohlc_daily`, nse_daily_file first), filled from the fit rows' index level."""
    lv = fit["index_level"].astype(float)
    if C.table_exists(con, "index_ohlc_daily"):
        df = con.execute("""SELECT date, close FROM index_ohlc_daily WHERE symbol = ? AND close > 0
                            QUALIFY ROW_NUMBER() OVER (PARTITION BY date ORDER BY CASE WHEN source = 'nse_daily_file' THEN 0 ELSE 1 END) = 1""",
                         [INDEX]).df()
        if not df.empty:
            s = pd.Series(df["close"].to_numpy(dtype=float), index=pd.to_datetime(df["date"])).sort_index()
            lv = s.reindex(sessions).combine_first(lv.reindex(sessions))
    return lv.reindex(sessions)


def row_argmax(frame: pd.DataFrame) -> pd.Series:
    """Column label of each row's maximum; None for an all-NaN row (pandas 3 raises there)."""
    v = frame.to_numpy(dtype=float)
    ok = ~np.isnan(v).all(axis=1)
    out = np.full(len(frame), None, dtype=object)
    if ok.any():
        out[ok] = frame.columns.to_numpy()[np.nanargmax(v[ok], axis=1)]
    return pd.Series(out, index=frame.index, dtype=object)


def fit_gate(fit: pd.DataFrame) -> pd.DataFrame:
    g = pd.DataFrame(index=fit.index)
    rel = (fit["residual_points"].abs() / fit["prev_index_level"]) * 100.0
    g["mae60_pct"] = rel.rolling(FIT_WINDOW, min_periods=FIT_WINDOW).mean()
    g["priced_ok"] = fit["members_priced"] >= MIN_PRICED
    g["pass"] = g["priced_ok"] & (g["mae60_pct"] <= FIT_MAE_PCT)
    window = g["pass"].astype(float).rolling(20 + THIN, min_periods=20 + THIN).min().shift(-(THIN))   # sessions T−19 … T+21
    g["decision_ok"] = window == 1.0
    return g


def panels(d: dict[str, Any]) -> dict[str, Any]:
    c = d["contrib"]
    sessions = d["fit"].index
    pts = c.pivot_table(index="date", columns="symbol", values="points", aggfunc="sum").reindex(sessions)
    wts = c.pivot_table(index="date", columns="symbol", values="weight_pct", aggfunc="first").reindex(sessions)
    rets = c.pivot_table(index="date", columns="symbol", values="ret_pct", aggfunc="first").reindex(sessions) / 100.0
    p0 = pts.fillna(0.0)
    w20 = p0.rolling(20, min_periods=20).sum()
    w60 = p0.rolling(60, min_periods=60).sum()
    f20 = p0.rolling(20, min_periods=20).sum().shift(-(C.ENTRY_SHIFT + C.HORIZON))      # sessions T+2 … T+21
    lr = np.log1p(rets)
    r_fwd = (np.expm1(lr.rolling(C.HORIZON, min_periods=C.HORIZON).sum()).shift(-(C.ENTRY_SHIFT + C.HORIZON))) * 100.0
    level = d["level"]
    st = d["state"]
    lead20 = st[st["window_sessions"] == 20].set_index("date")["leader"].reindex(sessions)
    lead60 = st[st["window_sessions"] == 60].set_index("date")["leader"].reindex(sessions)
    return {"sessions": sessions, "pts": pts, "wts": wts, "w20": w20, "w60": w60, "f20": f20, "r_fwd": r_fwd, "level": level,
            "lead20": lead20, "lead60": lead60, "wlead": row_argmax(wts), "raw20": row_argmax(w20.abs().where(w20.abs() > 0)),
            "R_N": C.forward_ret(level), "RVF": C.forward_rv(level), "rv20": C.trailing_rv(level, 20)}


def _pick(frame: pd.DataFrame, who: pd.Series) -> pd.Series:
    """frame[who[t]] at each date t (NaN when who is missing or not a column)."""
    cols = {c: i for i, c in enumerate(frame.columns)}
    v = frame.to_numpy()
    out = np.full(len(frame), np.nan)
    for i, w in enumerate(who.reindex(frame.index).to_numpy()):
        j = cols.get(w) if isinstance(w, str) else None
        if j is not None:
            out[i] = v[i, j]
    return pd.Series(out, index=frame.index)


def share_fwd(p: dict[str, Any], who: pd.Series) -> pd.Series:
    tot = p["f20"].abs().sum(axis=1, min_count=1)
    return _pick(p["f20"].abs(), who) / tot.where(tot > 0)


def d1_series(p: dict[str, Any], who: pd.Series) -> pd.Series:
    return share_fwd(p, who) - share_fwd(p, p["wlead"])


def d2_series(p: dict[str, Any], who: pd.Series, window: pd.DataFrame | None = None, sign_from: pd.Series | None = None) -> tuple[pd.Series, pd.Series]:
    """(s·(R_who − R_NIFTY), s); s = sign of who's trailing points sum (or the given `sign_from`)."""
    w = p["w20"] if window is None else window
    s = np.sign(_pick(w, who)) if sign_from is None else sign_from
    rel = _pick(p["r_fwd"], who) - p["R_N"]
    return s * rel, s


def random_weight_leader(p: dict[str, Any], seed: int = C.SEED) -> pd.Series:
    rng = np.random.default_rng(seed)
    out = []
    for _, row in p["wts"].iterrows():
        r = row.dropna()
        r = r[r > 0]
        out.append(rng.choice(r.index.to_numpy(), p=(r / r.sum()).to_numpy()) if len(r) else None)
    return pd.Series(out, index=p["wts"].index, dtype=object)


def events(p: dict[str, Any], lead: pd.Series, ok: pd.Series) -> pd.DatetimeIndex:
    """Leader-change dates inside the gate, thinned (≥ THIN sessions after the previously kept event)."""
    changed = (lead != lead.shift(1)) & lead.notna() & lead.shift(1).notna()
    cand = [i for i, (c, g) in enumerate(zip(changed.to_numpy(), ok.reindex(lead.index).fillna(False).to_numpy(), strict=True)) if c and g]
    kept: list[int] = []
    for i in cand:
        if not kept or i - kept[-1] >= THIN:
            kept.append(i)
    return pd.DatetimeIndex(lead.index[kept])


def d3(p: dict[str, Any], ev: pd.DatetimeIndex, ok: pd.Series) -> dict[str, dict[str, Any]]:
    okd = ok[ok].index
    mu_r = float(p["R_N"].reindex(okd).mean())
    dv = (p["RVF"] - p["rv20"])
    mu_v = float(dv.reindex(okd).mean())
    return {"D3r": C.mean_by_halves(p["R_N"].reindex(ev) - mu_r, 0, SPLIT, plain=True),
            "D3v": C.mean_by_halves(dv.reindex(ev) - mu_v, 0, SPLIT, plain=True)}


def rank_ic_series(p: dict[str, Any]) -> pd.Series:
    """Per date: Spearman(|W20_i| share, |F20_i| share) − Spearman(weight_i, |F20_i| share) across members."""
    out = []
    for t in p["sessions"]:
        a, b, w = p["w20"].loc[t].abs(), p["f20"].loc[t].abs(), p["wts"].loc[t]
        d = pd.concat([a, b, w], axis=1).dropna()
        if len(d) < 20 or d.iloc[:, 1].sum() <= 0:
            out.append(np.nan)
            continue
        out.append(float(sstats.spearmanr(d.iloc[:, 0], d.iloc[:, 1])[0] - sstats.spearmanr(d.iloc[:, 2], d.iloc[:, 1])[0]))
    return pd.Series(out, index=p["sessions"])


def run(con: Any, cash_cost: float) -> dict[str, Any]:
    d = load(con)
    d["level"] = index_level(con, d["fit"].index, d["fit"])
    gate = fit_gate(d["fit"])
    p = panels(d)
    ok = gate["decision_ok"]
    okd = ok[ok].index
    by_year = gate.groupby(gate.index.year).agg(sessions=("pass", "size"), passing=("pass", "mean"), decision_ok=("decision_ok", "mean"),
                                                mae60_median_pct=("mae60_pct", "median"))
    out: dict[str, Any] = {"sessions": len(gate), "span": [str(gate.index.min().date()), str(gate.index.max().date())],
                           "gated_decisions": len(okd), "weight_methods": sorted(d["fit"]["weight_method"].dropna().unique().tolist()),
                           "fit_by_year": by_year.reset_index().rename(columns={"date": "year"}).to_dict("records")}
    L = p["lead20"]
    s1 = d1_series(p, L).reindex(okd)
    y2, s = d2_series(p, L)
    y2 = y2.reindex(okd)
    out["D1"] = C.mean_by_halves(s1, LAGS, SPLIT)
    out["D2"] = C.mean_by_halves(y2, LAGS, SPLIT)
    rel = (_pick(p["r_fwd"], L) - p["R_N"]).reindex(okd)
    long_only = (rel - cash_cost)[s.reindex(okd) > 0]
    out["TL_D2"] = {**C.mean_by_halves(long_only, LAGS, SPLIT), "cost_rt_pct": cash_cost, "n_tranches": int(long_only.notna().sum())}
    out["TL_D2"]["ok"] = C.traded_leg_ok(out["TL_D2"])
    out["TL_D2_futures_floor"] = C.mean_by_halves(y2 - 2 * C.FLOOR_PCT, LAGS, SPLIT)
    # controls
    rnd = random_weight_leader(p)
    stale = L.shift(C.PLACEBO_LAG)                                   # L(T−250) …
    stale_sign = np.sign(_pick(p["w20"], L)).shift(C.PLACEBO_LAG)     # … with the sign it had then, s(T−250)
    out["controls"] = {"N1_random_weight_leader": {"D1": C.mean_by_halves(d1_series(p, rnd).reindex(okd), LAGS, SPLIT),
                                                   "D2": C.mean_by_halves(d2_series(p, rnd)[0].reindex(okd), LAGS, SPLIT)},
                       "N2_stale_leader_250": {"D2": C.mean_by_halves(d2_series(p, stale, sign_from=stale_sign)[0].reindex(okd), LAGS, SPLIT)}}
    out["cap_weight_leader_D2"] = C.mean_by_halves(d2_series(p, p["wlead"])[0].reindex(okd), LAGS, SPLIT)
    ev = events(p, L, ok)
    out["events"] = [str(x.date()) for x in ev]
    out["D3"] = d3(p, ev, ok) if len(ev) else {}
    pos = np.array([okd.get_loc(x) for x in ev if x in okd]) if len(ev) else np.array([], dtype=int)
    shifted = pd.DatetimeIndex(okd[(pos + len(okd) // 2) % len(okd)]) if len(pos) and len(okd) else pd.DatetimeIndex([])
    out["controls"]["N3_shifted_events"] = d3(p, shifted, ok) if len(shifted) else {}
    # robustness (not graded)
    out["robust"] = {"D1_raw_leader": C.mean_by_halves(d1_series(p, p["raw20"]).reindex(okd), LAGS, SPLIT),
                     "D1_rank_ic": C.mean_by_halves(rank_ic_series(p).reindex(okd), LAGS, SPLIT),
                     "D2_window60": C.mean_by_halves(d2_series(p, p["lead60"], window=p["w60"])[0].reindex(okd), LAGS, SPLIT)}
    ev60 = events(p, p["lead60"], ok)
    out["robust"]["D3_window60"] = d3(p, ev60, ok) if len(ev60) else {}
    out["n_events"] = len(ev)
    latest = L.dropna()
    out["latest_leader"] = {"date": str(latest.index[-1].date()) if len(latest) else None, "leader": latest.iloc[-1] if len(latest) else None}
    frame = pd.DataFrame({"leader20": L, "weight_leader": p["wlead"], "raw_leader20": p["raw20"], "D1": d1_series(p, L), "D2": d2_series(p, L)[0],
                          "s": s, "R_N": p["R_N"], "RVF": p["RVF"], "rv20": p["rv20"]}).join(gate)
    out["_frame"] = frame
    return out


def empty_half_note(st: dict[str, Any]) -> list[str]:
    """A half with no observation cannot meet the both-halves condition: say so (the split is pre-registered, never moved)."""
    empty = [h for h in ("h1", "h2") if not st.get(f"n_{h}")]
    if not empty:
        return []
    return [(f"{' and '.join(e.upper() for e in empty)} empty: the pre-registered split ({SPLIT}) falls outside the gated sample, so "
             "the both-halves condition cannot be met until the point-in-time share-count history reaches back")]


def verdicts(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    enough = res["gated_decisions"] >= MIN_DECISIONS
    for key, sign, ceiling in (("D1", +1, C.PASS_DESC), ("D2", +1, C.PASS)):
        if not enough:
            out[key] = {"verdict": C.PENDING, "notes": [f"{res['gated_decisions']} gated decision dates < {MIN_DECISIONS}"]}
            continue
        st = res[key]
        traded = res["TL_D2"]["ok"] if key == "D2" else None
        v = C.signed_verdict(st["t_full"], st["t_h1"], st["t_h2"], sign, traded_ok=traded, ceiling=ceiling)
        voided = [n for n, cs in res["controls"].items() if key in cs and C.meets(cs[key]["t_full"], cs[key]["t_h1"], cs[key]["t_h2"], sign)]
        capped = []
        if key == "D2":
            w = res["cap_weight_leader_D2"]
            if C.meets(w["t_full"], w["t_h1"], w["t_h2"], sign) and abs(w["t_full"]) >= abs(st["t_full"]):
                capped.append("weight leader")
        final, notes = C.apply_controls(v, voided_by=voided, capped_by=capped)
        notes += C.against_sign_note(st["t_full"], st["t_h1"], st["t_h2"], sign) + empty_half_note(st)
        out[key] = {"verdict": final, "pre_control": v, "notes": notes, "traded_ok": traded}
    for key, sign in (("D3r", 0), ("D3v", +1)):
        if res["n_events"] < MIN_EVENTS or key not in res["D3"]:
            out[key] = {"verdict": C.PENDING, "notes": [f"{res['n_events']} thinned events < {MIN_EVENTS}"]}
            continue
        st = res["D3"][key]
        v = C.signed_verdict(st["t_full"], st["t_h1"], st["t_h2"], sign, ceiling=C.CONTEXT_ONLY)
        n3 = res["controls"].get("N3_shifted_events", {}).get(key)
        voided = ["N3 shifted events"] if n3 and C.meets(n3["t_full"], n3["t_h1"], n3["t_h2"], sign) else []
        final, notes = C.apply_controls(v, voided_by=voided, capped_by=[])
        notes += empty_half_note(st)
        out[key] = {"verdict": final, "pre_control": v, "notes": notes}
    return out


def render(res: dict[str, Any], verd: dict[str, Any], meta: dict[str, Any]) -> tuple[str, str, str]:
    rows = []
    for key in ("D1", "D2", "D3r", "D3v"):
        st = res.get(key) if key in ("D1", "D2") else res["D3"].get(key, {})
        st = st or {"mean_full": float("nan"), "t_full": float("nan"), "n_full": 0}
        extra = ""
        if key == "D2":
            t = res["TL_D2"]
            extra = (f"TL-D2 long-only cash after {C.fmt(t['cost_rt_pct'], 2)} % RT: {C.fmt(t['mean_full'], 3)} % per tranche "
                     f"(t {C.tstr(t['t_full'])}; halves {C.tstr(t['t_h1'])} / {C.tstr(t['t_h2'])})")
        notes = verd[key].get("notes") or []
        if notes:
            extra = (extra + "; " if extra else "") + "; ".join(notes)
        rows.append(C.verdict_row(f"{key} · {NAMES[key]}", st, verd[key]["verdict"], kind="mean", extra=extra))
    fy = pd.DataFrame(res["fit_by_year"])
    lines = [f"# {STUDY} · NIFTY driver persistence and driver changes — report", "",
             (f"Run {meta['run_at']} · inputs `{meta['db']}` · plan `reports/terminal_v2/studies/drivers/PLAN.md` (pre-registered 5 Nov 2026 "
             "08:00 IST, before any result)."), "",
             "## The fit gate first (today's members stand in for past ones; the identity measures the damage)", "",
             (f"Sessions {res['sessions']} ({res['span'][0]} → {res['span'][1]}); gated decision dates {res['gated_decisions']} "
             f"(minimum {MIN_DECISIONS}); weight methods {res['weight_methods']}."), "",
             C.md_table(fy.to_dict("records"), ["year", "sessions", "passing", "decision_ok", "mae60_median_pct"]), "",
             "## Graded statistics (signed; Newey-West 19 lags for D1/D2, plain t over thinned events for D3; halves split 30 Apr 2023)", "",
             "| Statistic | mean full (t, n) | H1 (t) | H2 (t) | verdict | notes |", "|---|---|---|---|---|---|"]
    for key in ("D1", "D2", "D3r", "D3v"):
        st = (res.get(key) if key in ("D1", "D2") else res["D3"].get(key)) or {}
        lines.append(f"| {key} {NAMES[key]} | {C.fmt(st.get('mean_full'), 4)} ({C.tstr(st.get('t_full', float('nan')))}, {st.get('n_full', 0)}) | "
                     f"{C.fmt(st.get('mean_h1'), 4)} ({C.tstr(st.get('t_h1', float('nan')))}) | {C.fmt(st.get('mean_h2'), 4)} "
                     f"({C.tstr(st.get('t_h2', float('nan')))}) | **{verd[key]['verdict']}** | {'; '.join(verd[key].get('notes') or [])} |")
    t, ff = res["TL_D2"], res["TL_D2_futures_floor"]
    lines += ["", "## Traded leg and sensitivity", "",
              (f"- TL-D2 (long the leader in cash when it pushed up, 20 sessions, vs NIFTY, after {C.fmt(t['cost_rt_pct'], 3)} % per round trip): "
              f"{C.fmt(t['mean_full'], 3)} % per tranche (t {C.tstr(t['t_full'])}; halves {C.tstr(t['t_h1'])} / {C.tstr(t['t_h2'])}; "
              f"{t['n_tranches']} tranches) → ok = {t['ok']}."),
              f"- Futures pair at the 0.15 % floor per leg (not graded): {C.fmt(ff['mean_full'], 3)} % (t {C.tstr(ff['t_full'])}).", "",
              "## Controls (t full / H1 / H2)", "", "| Control | statistic | t |", "|---|---|---|"]
    for name, cs in res["controls"].items():
        for k, v in cs.items():
            lines.append(f"| {name} | {k} | {C.tstr(v['t_full'])} / {C.tstr(v['t_h1'])} / {C.tstr(v['t_h2'])} (mean {C.fmt(v['mean_full'], 4)}) |")
    w = res["cap_weight_leader_D2"]
    lines.append(f"| cap: weight leader | D2 | {C.tstr(w['t_full'])} / {C.tstr(w['t_h1'])} / {C.tstr(w['t_h2'])} (mean {C.fmt(w['mean_full'], 4)}) |")
    lines += ["", "## Robustness (not graded)", "", "| Row | mean full (t) | H1 (t) | H2 (t) |", "|---|---|---|---|"]
    for name, v in res["robust"].items():
        items = v.items() if name.startswith("D3") else [(name, v)]
        for nm, s in items:
            lines.append(f"| {name if nm == name else name + ' ' + nm} | {C.fmt(s['mean_full'], 4)} ({C.tstr(s['t_full'])}) | "
                         f"{C.fmt(s['mean_h1'], 4)} ({C.tstr(s['t_h1'])}) | {C.fmt(s['mean_h2'], 4)} ({C.tstr(s['t_h2'])}) |")
    lines += ["", f"Thinned leader-change events ({res['n_events']}): {', '.join(res['events'][:60])}{' …' if len(res['events']) > 60 else ''}",
              "", f"Latest 20-session leader (context): `{json.dumps(C._clean(res['latest_leader']))}`.", ""]
    report = "\n".join(lines)
    findings = "\n".join([f"# {STUDY} · FINDINGS (NIFTY drivers: persistence and changes)", "",
                          (f"Run {meta['run_at']} on `{meta['db']}`. Plan: `reports/terminal_v2/studies/drivers/PLAN.md` (pre-registered "
                          "before any result)."), "", "| Signal | Result (full sample) | Both halves |", "|---|---|---|",
                          *[C.study_row(r) for r in rows], "",
                          ("- **Badge consequence:** the regime strip keeps `context` and its sentence keeps \"describes, does not predict\"; "
                          "nothing from this study enters momentum.py, decision_desk.py, an alert or the ticket. No study result reaches a "
                          "badge without the PM."), ""])
    agg = "\n".join(["| Study · signal (known at release) | Result | Both halves | Verdict |", "|---|---|---|---|",
                     *[C.aggregate_row(STUDY, r) for r in rows]]) + "\n"
    return report, findings, agg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TV-DRIVERS (pre-registered; see the PLAN)")
    ap.add_argument("--db", type=Path, default=C.DEFAULT_INPUTS)
    ap.add_argument("--out-dir", type=Path, default=STUDY_DIR)
    ap.add_argument("--results-dir", type=Path, default=None, help="per-session CSVs (default: the scratch area; never committed)")
    ap.add_argument("--provisional", action="store_true")
    ap.add_argument("--allow-market-hours", action="store_true")
    a = ap.parse_args(argv)
    cash_cost = C.cash_round_trip_pct()
    try:
        with C.open_inputs(a.db, allow_market_hours=a.allow_market_hours) as con:
            res = run(con, cash_cost)
    except C.DataNotIngested as e:
        C.not_ingested(STUDY, str(e), "build_inputs.py --drivers (scratch) or the drivers backfill", "")
    except C.LiveFileBusy as e:
        C.live_busy(STUDY, str(e))
    verd = verdicts(res)
    meta = C.run_meta(STUDY, a.db, a.provisional)
    report, findings, agg = render(res, verd, meta)
    summary = {**meta, "split": SPLIT, "cash_cost_rt_pct": cash_cost, "results": {k: v for k, v in res.items() if not k.startswith("_")},
               "verdicts": verd}
    C.write_outputs(a.out_dir, summary=summary, report_md=report, findings_md=findings, findings_row_md=agg, results={"frame": res["_frame"]},
                    provisional=a.provisional, results_dir=a.results_dir)
    if any(v["verdict"] == C.PENDING for v in verd.values() if v) and res["gated_decisions"] < MIN_DECISIONS:
        C.insufficient(STUDY, f"gated decision dates {res['gated_decisions']} < {MIN_DECISIONS}", "outputs written with PENDING rows")
    print(C.status_line(STUDY, "ran", detail=", ".join(f"{k}={v['verdict']}" for k, v in verd.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
