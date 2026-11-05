"""TV-GEX — does a GEX-style dealer-gamma proxy forecast NIFTY's next-day range?

Pre-registered plan (written before any result): `reports/terminal_v2/studies/gex/PLAN.md` (Terminal v2 PLAN Wave 3.3's
precondition). Proxy from the first three NIFTY expiries (±15 %): Black-76 gamma × OI(units) × F² × 1 % per strike, σ from
the strike's own IV or interpolated in log-moneyness. X1 = NGS (C1, vendor convention: dealers long calls / short puts;
sign of b registered −), X2 = TGL (C2, "writers are short": the short-gamma load vs its 252-session prior median; sign +).
Graded regression Y(T+1) = a + b·X + Ȳ5 + Ȳ20 + iv30_cm + expiry-day dummy, Newey-West t (5 lags); traded legs: the near
ATM straddle sold at the close of T+1, bought back at the close of T+2, conditional on the proxy's tercile, after the F&O
schedule. Negative controls N1–N3 void; N4 (put-call OI share) and N5 (OI load) cap.

Reads READ-ONLY: `--db` (`iv_surface_daily`, `iv_expiry_daily`, `iv_summary_daily`, optional `index_ohlc_daily`), `--aux`
(`study_fo_contracts` from `build_inputs.py --fo`), the participant-OI files (cross-check). No network.
Exit 0 ran · 3 data not yet ingested · 4 insufficient history · 5 live file busy.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal_studies import common as C

STUDY = "TV-GEX"
STUDY_DIR = C.STUDIES_DIR / "gex"
SYMBOL = "NIFTY"
SPLIT = "2023-03-31"
LAGS = 5
TL_LAGS = 1
MIN_GRADED = 750
MIN_TRANCHES = 300
MIN_IV_STRIKES = 4
MONEYNESS = 0.15
N_EXPIRIES = 3
NEAR_MIN_DTE = 3
STRIKE_BAND = 0.01
ZG_GRID = np.linspace(0.90, 1.10, 81)
SIGNS = {"X1": -1, "X2": +1}
NAMES = {"X1": "NGS (C1 vendor convention: dealers long calls, short puts) → next-day range, sign −",
         "X2": "TGL (C2 'writers are short': short-gamma load) → next-day range, sign +"}


# ── the proxy ─────────────────────────────────────────────────────────────────────────────────────────────────────

def black76_gamma(f: np.ndarray, k: np.ndarray, t: np.ndarray, sigma: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Γ = e^{−rT} φ(d1) / (F σ √T); identical for calls and puts. NaN where inputs are not positive."""
    with np.errstate(all="ignore"):
        sq = sigma * np.sqrt(t)
        d1 = (np.log(f / k) + 0.5 * sigma * sigma * t) / sq
        g = np.exp(-r * t) * np.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi) / (f * sq)
    return np.where((f > 0) & (k > 0) & (t > 0) & (sigma > 0), g, np.nan)


def strike_sigmas(g: pd.DataFrame) -> pd.DataFrame | None:
    """One expiry of one day (rows per strike × side) → per strike: σ (decimal) from its own IV (mean of the sides) or
    interpolated in log-moneyness between IV-bearing strikes (flat beyond the wings); None below MIN_IV_STRIKES."""
    per = g.groupby("strike", as_index=False).agg(iv=("iv", "mean"), forward=("forward", "first"), t=("t_years", "first"), r=("r", "first"))
    per["lm"] = np.log(per["strike"] / per["forward"])
    known = per.dropna(subset=["iv"]).sort_values("lm")
    if len(known) < MIN_IV_STRIKES:
        return None
    per["sigma"] = np.interp(per["lm"], known["lm"].to_numpy(), known["iv"].to_numpy()) / 100.0
    own = per["iv"].notna()
    per.loc[own, "sigma"] = per.loc[own, "iv"] / 100.0
    return per


def day_proxy(day_rows: pd.DataFrame) -> dict[str, Any]:
    """One session's surface rows (first three expiries) → the proxies of the PLAN for that day."""
    parts = []
    skipped = 0
    for _, g in day_rows.groupby("expiry", sort=True):
        g = g[(g["t_years"] > 0) & ((g["strike"] / g["forward"] - 1).abs() <= MONEYNESS)]
        per = strike_sigmas(g)
        if per is None:
            skipped += 1
            continue
        oi = g.pivot_table(index="strike", columns="opt_type", values="oi", aggfunc="sum").reindex(per["strike"]).fillna(0.0)
        per = per.set_index("strike")
        per["oi_ce"] = oi.get("CE", pd.Series(0.0, index=oi.index)).to_numpy()
        per["oi_pe"] = oi.get("PE", pd.Series(0.0, index=oi.index)).to_numpy()
        parts.append(per.reset_index())
    if not parts:
        return {"n_expiries": 0, "skipped_expiries": skipped}
    p = pd.concat(parts, ignore_index=True)
    f, k, t, s, r = (p[c].to_numpy(dtype=float) for c in ("forward", "strike", "t", "sigma", "r"))
    gam = black76_gamma(f, k, t, s, r)
    scale = f * f * 0.01
    dg_ce = np.nansum(gam * p["oi_ce"].to_numpy() * scale)
    dg_pe = np.nansum(gam * p["oi_pe"].to_numpy() * scale)
    oi_ce, oi_pe = float(p["oi_ce"].sum()), float(p["oi_pe"].sum())
    tot = dg_ce + dg_pe
    # zero-gamma: every forward scaled by x (σ, T fixed: sticky strike); first sign change nearest x = 1
    xs = ZG_GRID[:, None]
    gg = black76_gamma(f[None, :] * xs, k[None, :], t[None, :], s[None, :], r[None, :])
    net = np.nansum(gg * (p["oi_ce"].to_numpy() - p["oi_pe"].to_numpy())[None, :] * (f[None, :] * xs) ** 2 * 0.01, axis=1)
    zg = float("nan")
    sgn = np.sign(net)
    cross = np.where(sgn[:-1] * sgn[1:] < 0)[0]
    if len(cross):
        j = cross[np.argmin(np.abs(ZG_GRID[cross] - 1.0))]
        x0, x1, y0, y1 = ZG_GRID[j], ZG_GRID[j + 1], net[j], net[j + 1]
        zg = float(x0 - y0 * (x1 - x0) / (y1 - y0))
    return {"n_expiries": len(parts), "skipped_expiries": skipped, "dg_ce_cr": dg_ce / 1e7, "dg_pe_cr": dg_pe / 1e7,
            "gex_net_cr": (dg_ce - dg_pe) / 1e7, "dg_total_cr": tot / 1e7, "NGS": (dg_ce - dg_pe) / tot if tot > 0 else float("nan"),
            "oi_ce": oi_ce, "oi_pe": oi_pe, "NOS": (oi_ce - oi_pe) / (oi_ce + oi_pe) if (oi_ce + oi_pe) > 0 else float("nan"),
            "zero_gamma_x": zg, "zero_gamma_dist_pct": (1.0 - zg) * 100 if math.isfinite(zg) else float("nan")}


def load_proxy(con: Any) -> pd.DataFrame:
    C.require(con, "iv_surface_daily", "the IV backfill or build_inputs.py --fo")
    surf = con.execute("""SELECT date, expiry, strike, opt_type, iv, oi, forward, t_years, r FROM iv_surface_daily
                          WHERE symbol = ? AND model_version = ? AND oi > 0 ORDER BY date, expiry, strike""", [SYMBOL, C.MODEL_VERSION]).df()
    if surf.empty:
        raise C.DataNotIngested(f"iv_surface_daily rows for {SYMBOL}")
    surf["date"] = pd.to_datetime(surf["date"])
    rows = []
    for d, g in surf.groupby("date", sort=True):
        rows.append({"date": d, **day_proxy(g)})
    px = pd.DataFrame(rows).set_index("date").sort_index()
    tot = px["dg_total_cr"]
    px["TGL"] = np.log(tot / tot.rolling(C.WARMUP, min_periods=C.WARMUP).median().shift(1))
    oi = px["oi_ce"] + px["oi_pe"]
    px["OILOAD"] = np.log(oi / oi.rolling(C.WARMUP, min_periods=C.WARMUP).median().shift(1))
    return px


# ── target, controls, calendar ────────────────────────────────────────────────────────────────────────────────────

def load_range(aux: Any) -> tuple[pd.Series, set[pd.Timestamp]]:
    """Y = 100 ln(H/L) of the most-traded NIFTY future per session; and the NIFTY option expiry dates."""
    C.require(aux, "study_fo_contracts", "build_inputs.py --fo")
    fut = aux.execute("""SELECT date, expiry, high, low, volume FROM study_fo_contracts
                         WHERE symbol = ? AND instrument = 'FUT' AND high > 0 AND low > 0 AND volume > 0""", [SYMBOL]).df()
    if fut.empty:
        raise C.DataNotIngested("NIFTY futures high / low in study_fo_contracts")
    fut["date"] = pd.to_datetime(fut["date"])
    top = fut.sort_values(["date", "volume"]).groupby("date").tail(1).set_index("date").sort_index()
    y = 100.0 * np.log(top["high"] / top["low"])
    ex = aux.execute("SELECT DISTINCT expiry FROM study_fo_contracts WHERE symbol = ? AND instrument = 'OPT'", [SYMBOL]).df()
    expiries = {pd.Timestamp(e) for e in pd.to_datetime(ex["expiry"])}
    return y.rename("Y"), expiries


def build_frame(px: pd.DataFrame, y: pd.Series, expiries: set[pd.Timestamp], iv30: pd.Series) -> pd.DataFrame:
    f = pd.DataFrame(index=y.index)
    f["Y"] = y
    f["Y1"] = y.shift(-1)                                  # the range of session T+1
    f["Y2"] = y.shift(-2)
    f["Ybar5"] = y.rolling(5, min_periods=5).mean()
    f["Ybar20"] = y.rolling(20, min_periods=20).mean()
    nxt = pd.Series(f.index, index=f.index).shift(-1)
    f["EXP1"] = nxt.map(lambda d: 1.0 if pd.notna(d) and pd.Timestamp(d) in expiries else 0.0)
    f["EXP2"] = pd.Series(f.index, index=f.index).shift(-2).map(lambda d: 1.0 if pd.notna(d) and pd.Timestamp(d) in expiries else 0.0)
    f = f.join(iv30.rename("iv30"), how="left").join(px, how="left")
    return f


CONTROLS = ["Ybar5", "Ybar20", "iv30", "EXP1"]


def regress(f: pd.DataFrame, x: pd.Series, target: str = "Y1", controls: list[str] | None = None) -> dict[str, Any]:
    ctl = CONTROLS if controls is None else controls
    if target == "Y2":
        ctl = [c if c != "EXP1" else "EXP2" for c in ctl]
    d = f[[target, *ctl]].assign(_x=x)
    return C.slope_by_halves(d[target], d[["_x", *ctl]], "_x", LAGS, SPLIT)


# ── traded legs ───────────────────────────────────────────────────────────────────────────────────────────────────

def one_session_tranches(con: Any, aux: Any, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """For each T: the near ATM straddle (dte ≥ 3 on T+1) sold at the close of T+1, bought back at the close of T+2."""
    C.require(con, "iv_expiry_daily")
    ex = con.execute("SELECT date, expiry, dte, forward FROM iv_expiry_daily WHERE symbol = ? AND dte >= ? AND forward > 0",
                     [SYMBOL, NEAR_MIN_DTE]).df()
    ex["date"], ex["expiry"] = pd.to_datetime(ex["date"]), pd.to_datetime(ex["expiry"])
    pick = ex.sort_values(["date", "dte"]).groupby("date", as_index=False).first()
    aux.register("pick", pick)
    opt0 = aux.execute("""SELECT c.date, c.expiry, c.strike, c.opt_type, c.close FROM study_fo_contracts c JOIN pick p
                          ON c.date = p.date AND c.expiry = p.expiry
                          WHERE c.symbol = ? AND c.instrument = 'OPT' AND c.volume > 0 AND c.close > 0""", [SYMBOL]).df()
    aux.unregister("pick")
    opt0["date"], opt0["expiry"] = pd.to_datetime(opt0["date"]), pd.to_datetime(opt0["expiry"])
    w = opt0.pivot_table(index=["date", "expiry", "strike"], columns="opt_type", values="close", aggfunc="first").dropna(subset=["CE", "PE"])
    w = w.reset_index().merge(pick[["date", "expiry", "forward", "dte"]], on=["date", "expiry"])
    w["dist"] = (w["strike"] / w["forward"] - 1).abs()
    entry = w[w["dist"] <= STRIKE_BAND].sort_values(["date", "dist"]).groupby("date", as_index=False).first()
    pos = {d: i for i, d in enumerate(sessions)}
    entry["e1"] = entry["date"].map(lambda d: sessions[pos[d] + 1] if d in pos and pos[d] + 1 < len(sessions) else pd.NaT)
    entry["T"] = entry["date"].map(lambda d: sessions[pos[d] - 1] if d in pos and pos[d] >= 1 else pd.NaT)
    entry = entry.dropna(subset=["e1", "T"])
    aux.register("ent", entry[["e1", "expiry", "strike"]].rename(columns={"e1": "date"}))
    ex1 = aux.execute("""SELECT c.date, c.expiry, c.strike, c.opt_type, c.close, c.settle, c.volume FROM study_fo_contracts c JOIN ent e
                         ON c.date = e.date AND c.expiry = e.expiry AND c.strike = e.strike
                         WHERE c.symbol = ? AND c.instrument = 'OPT'""", [SYMBOL]).df()
    aux.unregister("ent")
    ex1["date"], ex1["expiry"] = pd.to_datetime(ex1["date"]), pd.to_datetime(ex1["expiry"])
    ex1["px"] = np.where((ex1["volume"] > 0) & (ex1["close"] > 0), ex1["close"], ex1["settle"])
    ex1["from_settle"] = ~((ex1["volume"] > 0) & (ex1["close"] > 0))
    x = ex1.pivot_table(index=["date", "expiry", "strike"], columns="opt_type", values=["px", "from_settle"], aggfunc="first")
    x.columns = [f"{a}_{b}" for a, b in x.columns]
    x = x.reset_index().rename(columns={"date": "e1"})
    m = entry.merge(x, on=["e1", "expiry", "strike"], how="inner").dropna(subset=["px_CE", "px_PE"])
    m["pnl_pct"] = [C.straddle_one_session_pnl_pct(a, b, c, d, f) for a, b, c, d, f in
                    zip(m["CE"], m["PE"], m["px_CE"], m["px_PE"], m["forward"], strict=True)]
    m["exit_from_settle"] = m["from_settle_CE"].astype(bool) | m["from_settle_PE"].astype(bool)
    return m.set_index("T").sort_index()


def traded_leg(tranches: pd.DataFrame, cond: pd.Series) -> dict[str, Any]:
    from terminal_studies.tv_ivrv import cond_minus_all

    c = cond.reindex(tranches.index)
    d = pd.concat([tranches["pnl_pct"], c.rename("c")], axis=1).dropna()
    if (d["c"] == 1).sum() < MIN_TRANCHES:
        return {"n": len(d), "n_conditional": int((d["c"] == 1).sum()), "ok": False, "note": f"< {MIN_TRANCHES} conditional tranches"}
    diff = cond_minus_all(d["pnl_pct"], d["c"], TL_LAGS, SPLIT)
    own = C.mean_by_halves(d.loc[d["c"] == 1, "pnl_pct"], TL_LAGS, SPLIT)
    allm = C.mean_by_halves(d["pnl_pct"], TL_LAGS, SPLIT)
    return {"n": len(d), "n_conditional": int((d["c"] == 1).sum()), "cond_minus_all": diff, "conditional_after_costs": own,
            "unconditional_after_costs": allm, "ok": bool(C.traded_leg_ok(diff) and C.traded_leg_ok(own))}


# ── participant cross-check ───────────────────────────────────────────────────────────────────────────────────────

def load_participants(root: Path = C.PARTICIPANT_ROOT) -> pd.DataFrame:
    rows = []
    for p in sorted(root.glob("*/fao_participant_oi_*.csv")):
        try:
            d = pd.to_datetime(p.stem.rsplit("_", 1)[-1], format="%d%m%Y")
            df = pd.read_csv(p, skiprows=1)
        except (ValueError, pd.errors.ParserError, OSError):
            continue
        df.columns = [str(c).strip() for c in df.columns]
        if "Client Type" not in df.columns:
            continue
        df["Client Type"] = df["Client Type"].astype(str).str.strip()
        for who in ("Pro", "FII", "Client"):
            r = df[df["Client Type"] == who]
            if r.empty:
                continue
            r0 = r.iloc[0]
            try:
                rows.append({"date": d, "who": who, "call_long": float(r0["Option Index Call Long"]), "put_long": float(r0["Option Index Put Long"]),
                             "call_short": float(r0["Option Index Call Short"]), "put_short": float(r0["Option Index Put Short"])})
            except (KeyError, ValueError, TypeError):
                continue
    return pd.DataFrame(rows)


def participant_check(part: pd.DataFrame, f: pd.DataFrame) -> dict[str, Any]:
    if part.empty:
        return {"n": 0, "note": "participant files not found"}
    out: dict[str, Any] = {}
    for who, g in part.groupby("who"):
        g = g.set_index("date").sort_index()
        net_call, net_put = g["call_long"] - g["call_short"], g["put_long"] - g["put_short"]
        long_gamma = (g["call_long"] + g["put_long"]) > (g["call_short"] + g["put_short"])
        both = pd.concat([long_gamma.rename("lg"), f["NGS"]], axis=1, sort=True).dropna()
        agree = float(((both["NGS"] > 0) == both["lg"].astype(bool)).mean()) if len(both) else float("nan")
        out[str(who)] = {"n": len(g), "share_net_short_calls": float((net_call < 0).mean()), "share_net_short_puts": float((net_put < 0).mean()),
                         "share_net_long_gamma": float(long_gamma.mean()), "agreement_with_C1_sign": agree}
    return out


# ── study ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def run(con: Any, aux: Any) -> dict[str, Any]:
    px = load_proxy(con)
    y, expiries = load_range(aux)
    C.require(con, "iv_summary_daily")
    iv = con.execute("SELECT date, iv30_cm FROM iv_summary_daily WHERE symbol = ? AND model_version = ?", [SYMBOL, C.MODEL_VERSION]).df()
    iv30 = pd.Series(iv["iv30_cm"].to_numpy(dtype=float), index=pd.to_datetime(iv["date"]))
    f = build_frame(px, y, expiries, iv30)
    n1 = int(f[["Y1", "NGS", *CONTROLS]].dropna().shape[0])
    n2 = int(f[["Y1", "TGL", *CONTROLS]].dropna().shape[0])
    if min(n1, n2) < MIN_GRADED:
        raise C.InsufficientHistory(f"graded sessions X1 {n1}, X2 {n2} < {MIN_GRADED}")
    tranches = one_session_tranches(con, aux, pd.DatetimeIndex(f.index))
    out: dict[str, Any] = {"n_sessions": len(f), "span": [str(f.index.min().date()), str(f.index.max().date())],
                           "n_graded": {"X1": n1, "X2": n2}, "tranches": len(tranches),
                           "exit_from_settle_share": float(tranches["exit_from_settle"].mean()) if len(tranches) else float("nan"),
                           "skipped_expiry_days": int((f["skipped_expiries"] > 0).sum()) if "skipped_expiries" in f else 0}
    for xid, col, placebo, cond in (("X1", "NGS", "NOS", C.top_tercile(f["NGS"])), ("X2", "TGL", "OILOAD", C.bottom_tercile(f["TGL"]))):
        rec: dict[str, Any] = {"stat": regress(f, f[col])}
        g = f[["Y1", col, *CONTROLS]].dropna()
        rec["controls"] = {"N1_lag250": regress(f, C.placebo_lag(f[col])),
                           "N2_circular_shift": regress(f, C.circular_shift(g[col]).reindex(f.index)),
                           "N3_permutation": regress(f, C.permute(g[col]).reindex(f.index))}
        rec["cap_control"] = {"name": placebo, **regress(f, f[placebo])}
        rec["robust_T2"] = regress(f, f[col], target="Y2")
        rec["robust_no_iv"] = regress(f, f[col], controls=["Ybar5", "Ybar20", "EXP1"])
        rec["traded"] = traded_leg(tranches, cond)
        out[xid] = rec
    out["participants"] = participant_check(load_participants(), f)
    if C.table_exists(con, "index_ohlc_daily"):
        io = con.execute("SELECT count(*) FROM index_ohlc_daily WHERE symbol = 'NIFTY 50' AND high > 0 AND low > 0").fetchone()
        out["index_range_rows"] = int(io[0]) if io else 0
    out["latest"] = {k: (None if pd.isna(v) else float(v)) for k, v in f[["NGS", "TGL", "gex_net_cr", "zero_gamma_dist_pct"]].dropna(how="all").iloc[-1].items()}
    out["_frame"], out["_tranches"] = f, tranches
    return out


def verdicts(res: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for xid, sign in SIGNS.items():
        rec = res[xid]
        st = rec["stat"]
        v = C.signed_verdict(st["t_full"], st["t_h1"], st["t_h2"], sign, traded_ok=rec["traded"].get("ok"), ceiling=C.PASS)
        voided = [n for n, cs in rec["controls"].items() if C.meets(cs["t_full"], cs["t_h1"], cs["t_h2"], sign)]
        cap = rec["cap_control"]
        capped = [f"{'N4' if xid == 'X1' else 'N5'} {cap['name']}"] if (C.meets(cap["t_full"], cap["t_h1"], cap["t_h2"], sign)
                                                                          and abs(cap["t_full"]) >= abs(st["t_full"])) else []
        final, notes = C.apply_controls(v, voided_by=voided, capped_by=capped)
        notes += C.against_sign_note(st["t_full"], st["t_h1"], st["t_h2"], sign)
        out[xid] = {"verdict": final, "pre_control": v, "notes": notes, "traded_ok": rec["traded"].get("ok"),
                    "badge_consequence": "may move from heuristic to context (PM + owner)" if final == C.PASS else "stays heuristic"}
    return out


def _leg_text(t: dict[str, Any]) -> str:
    if "cond_minus_all" not in t:
        return f"traded leg n/a ({t.get('note', '')})"
    d, o = t["cond_minus_all"], t["conditional_after_costs"]
    return (f"leg cond − all {C.fmt(d['mean_full'], 4)} %F (t {C.tstr(d['t_full'])}); cond after costs {C.fmt(o['mean_full'], 4)} %F "
            f"(t {C.tstr(o['t_full'])}; halves {C.tstr(o['t_h1'])} / {C.tstr(o['t_h2'])})")


def render(res: dict[str, Any], verd: dict[str, Any], meta: dict[str, Any]) -> tuple[str, str, str]:
    rows = []
    for xid in SIGNS:
        rec, v = res[xid], verd[xid]
        extra = _leg_text(rec["traded"]) + (f"; {'; '.join(v['notes'])}" if v["notes"] else "")
        rows.append(C.verdict_row(f"{xid} · {NAMES[xid]}", rec["stat"], v["verdict"], extra=extra))
    lines = [f"# {STUDY} · dealer-gamma proxy vs NIFTY's next-day range — report", "",
             (f"Run {meta['run_at']} · inputs `{meta['db']}` · plan `reports/terminal_v2/studies/gex/PLAN.md` (pre-registered 5 Nov 2026 "
             "08:00 IST, before any result)."), "",
             (f"Sessions {res['n_sessions']} ({res['span'][0]} → {res['span'][1]}); graded X1 {res['n_graded']['X1']}, X2 {res['n_graded']['X2']}; "
             f"one-session straddle tranches {res['tranches']} (exit priced from the settle price: {C.fmt(res['exit_from_settle_share'] * 100, 1)} %); "
             f"days with a skipped expiry (< 4 IV strikes): {res['skipped_expiry_days']}; index OHLC rows stored: {res.get('index_range_rows', 0)} "
             "(the range is the most-traded NIFTY future's high / low)."), "",
             "## Graded regressions (Y = 100 ln(H/L) of T+1; controls Ȳ5, Ȳ20, iv30_cm, expiry-day dummy; Newey-West 5 lags; halves split 31 Mar 2023)", "",
             "| Proxy | b full (t) | H1 b (t) | H2 b (t) | R² | traded leg | verdict | notes |", "|---|---|---|---|---|---|---|---|"]
    for xid in SIGNS:
        st, v = res[xid]["stat"], verd[xid]
        lines.append(f"| {xid} {NAMES[xid]} | {C.fmt(st['b_full'], 4)} ({C.tstr(st['t_full'])}) | {C.fmt(st['b_h1'], 4)} ({C.tstr(st['t_h1'])}) | "
                     f"{C.fmt(st['b_h2'], 4)} ({C.tstr(st['t_h2'])}) | {C.fmt(st['r2_full'], 3)} | {_leg_text(res[xid]['traded'])} | "
                     f"**{v['verdict']}** | {'; '.join(v['notes'])} |")
    lines += ["", "## Controls and robustness (t full / H1 / H2)", "", "| Proxy | row | t |", "|---|---|---|"]
    for xid in SIGNS:
        rec = res[xid]
        for name, cs in {**rec["controls"], f"cap: {rec['cap_control']['name']}": rec["cap_control"],
                         "robust: range of T+2": rec["robust_T2"], "robust: without iv30_cm": rec["robust_no_iv"]}.items():
            lines.append(f"| {xid} | {name} | {C.tstr(cs['t_full'])} / {C.tstr(cs['t_h1'])} / {C.tstr(cs['t_h2'])} (b {C.fmt(cs['b_full'], 4)}) |")
    lines += ["", "## Traded legs (near ATM straddle, close T+1 → close T+2, % of the forward after the F&O schedule)", ""]
    for xid in SIGNS:
        t = res[xid]["traded"]
        if "unconditional_after_costs" in t:
            u = t["unconditional_after_costs"]
            lines.append(f"- **{xid}**: n {t['n']} (conditional {t['n_conditional']}); unconditional seller {C.fmt(u['mean_full'], 4)} %F "
                         f"(t {C.tstr(u['t_full'])}); {_leg_text(t)}.")
        else:
            lines.append(f"- **{xid}**: {_leg_text(t)}.")
    lines += ["", "## Participant cross-check (not graded)", "", f"```\n{json.dumps(C._clean(res['participants']), indent=1)}\n```", "",
              f"Latest proxy reading (context only): `{json.dumps(C._clean(res['latest']))}`.", ""]
    report = "\n".join(lines)
    findings = "\n".join([f"# {STUDY} · FINDINGS (GEX-style proxy → next-day range)", "",
                          (f"Run {meta['run_at']} on `{meta['db']}`. Plan: `reports/terminal_v2/studies/gex/PLAN.md` (pre-registered before "
                          "any result; Terminal v2 PLAN Wave 3.3's precondition)."), "",
                          "| Signal | Result (full sample) | Both halves |", "|---|---|---|", *[C.study_row(r) for r in rows], "",
                          "- **Badge consequence:** " + "; ".join(f"{x}: {verd[x]['badge_consequence']}" for x in SIGNS)
                          + ". The proxy can never be `signal` while the dealers' sign is an assumption. No study result reaches a badge "
                          "without the PM.", ""])
    agg = "\n".join(["| Study · signal (known at release) | Result | Both halves | Verdict |", "|---|---|---|---|",
                     *[C.aggregate_row(STUDY, r) for r in rows]]) + "\n"
    return report, findings, agg


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TV-GEX (pre-registered; see the PLAN)")
    ap.add_argument("--db", type=Path, default=C.DEFAULT_INPUTS)
    ap.add_argument("--aux", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=STUDY_DIR)
    ap.add_argument("--results-dir", type=Path, default=None, help="per-session CSVs (default: the scratch area; never committed)")
    ap.add_argument("--provisional", action="store_true")
    ap.add_argument("--allow-market-hours", action="store_true")
    a = ap.parse_args(argv)
    try:
        with ExitStack() as stack:
            con = stack.enter_context(C.open_inputs(a.db, allow_market_hours=a.allow_market_hours))
            aux = con if a.aux is None else stack.enter_context(C.open_inputs(a.aux, allow_market_hours=a.allow_market_hours))
            res = run(con, aux)
    except C.DataNotIngested as e:
        C.not_ingested(STUDY, str(e), "build_inputs.py --fo (scratch) or the O-T4 backfill", "")
    except C.InsufficientHistory as e:
        C.insufficient(STUDY, str(e))
    except C.LiveFileBusy as e:
        C.live_busy(STUDY, str(e))
    verd = verdicts(res)
    meta = C.run_meta(STUDY, a.db, a.provisional)
    report, findings, agg = render(res, verd, meta)
    summary = {**meta, "split": SPLIT, "results": {k: v for k, v in res.items() if not k.startswith("_")}, "verdicts": verd}
    C.write_outputs(a.out_dir, summary=summary, report_md=report, findings_md=findings, findings_row_md=agg,
                    results={"frame": res["_frame"], "tranches": res["_tranches"]}, provisional=a.provisional, results_dir=a.results_dir)
    print(C.status_line(STUDY, "ran", detail=", ".join(f"{k}={v['verdict']}" for k, v in verd.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
