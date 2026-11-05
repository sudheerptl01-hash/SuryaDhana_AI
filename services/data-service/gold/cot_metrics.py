"""COT metrics (SOURCES.md §10 M11–M24): nets per group, Δ week, % of OI, the COT index 26/52/156 (in
REPORTS, never days), z52/z156, the all-history percentile (expanding, point-in-time), the options overlay
(combined − futures-only), the four-quadrant label (price Tue→Tue × ΔOI) and the fund-driver label — the magnitude-aware
rule of ``gold/driver_rule.py`` (the single source of truth; wave 1c, C-TRADER-3 / C-BEGINNER-1 / C-DATA-15):

    down week: "funds bought the dip" if the net rose; else "long liquidation" if ΔL<0 and |ΔL| ≥ max(ΔS,0); else "new shorts"
    up week:   "funds sold into it" if the net fell; else "short covering" if ΔS<0 and |ΔS| ≥ max(ΔL,0); else "new longs"

Every output is descriptive. G-STUDY (26 Oct 2026): FAIL as a forecast at 1/4/13 weeks for every metric; PASS as a
description (same-week Spearman +0.65). The badge is ``context`` and the footer says so.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from gold import db, driver_rule

OZ_PER_CONTRACT = 100.0
OZ_PER_TONNE = 32150.7466
GROUPS: dict[str, tuple[str, str]] = {   # key → (label, column prefix)
    "mm": ("Managed money (funds)", "mm"), "or": ("Other reportables", "or"), "nr": ("Non-reportable (small traders)", "nr"),
    "sd": ("Swap dealers (banks)", "sd"), "pm": ("Producer / merchant", "pm"),
}
CROWD_LABEL = "crowdedness, not a signal — no forecasting power 2006–2026 (G-STUDY)"
FOOTER = ("weekly, Tuesday positions, released Friday 15:30 ET; no daily, no OTC, categories only; "
          "our test found no timing value (G-STUDY 26 Oct 2026) — explains the week, does not forecast")
API_QUERY = ("https://publicreporting.cftc.gov/resource/72hh-3qpy.json?$where=cftc_contract_market_code='088691'"
             "&$order=report_date_as_yyyy_mm_dd DESC&$limit=3")
RAW_BLOCK_URL = "https://www.cftc.gov/dea/futures/deacmxsf.htm"


def cot_index(s: pd.Series, w: int) -> pd.Series:
    lo, hi = s.rolling(w, min_periods=w).min(), s.rolling(w, min_periods=w).max()
    return 100.0 * (s - lo) / (hi - lo).replace(0, np.nan)


def zscore(s: pd.Series, w: int) -> pd.Series:
    return (s - s.rolling(w, min_periods=w).mean()) / s.rolling(w, min_periods=w).std()


def expanding_percentile(s: pd.Series) -> pd.Series:
    """Percentile of each value among all values up to and including it (no look-ahead)."""
    return s.expanding().rank(pct=True) * 100.0


def quadrant_label(dp: float | None, doi: float | None) -> str | None:
    """The OI quadrant (PLAN a.3 d.quadrant, API_CONTRACT §2.5): sign(Δprice Tue→Tue) × sign(ΔOI) →
    long build-up / short covering / short build-up / long unwinding. The fund-driver words live in ``driver_label``."""
    if dp is None or doi is None or pd.isna(dp) or pd.isna(doi):
        return None
    if dp > 0:
        return "long build-up" if doi > 0 else "short covering"
    return "short build-up" if doi > 0 else "long unwinding"


def driver_label(dp: float | None, dl: float | None, ds: float | None) -> str | None:
    """The fund-driver word: delegates to ``gold.driver_rule.driver_label`` (the one rule, mirrored by ui-api)."""
    return driver_rule.driver_label(dp, dl, ds)


def who_did(dl: float | None, ds: float | None) -> list[str]:
    """The week's changes in words (API_CONTRACT §2.5): ``new|closed N longs``, ``new|covered N shorts``, ``no change``."""
    out: list[str] = []
    if dl is not None and not pd.isna(dl) and dl != 0:
        out.append(f"{'new' if dl > 0 else 'closed'} {abs(int(dl)):,} longs")
    if ds is not None and not pd.isna(ds) and ds != 0:
        out.append(f"{'new' if ds > 0 else 'covered'} {abs(int(ds)):,} shorts")
    return out or ["no change"]


def price_at(prices: pd.Series | None, d: date) -> float | None:
    """Last close on or before ``d`` (prices indexed by date, sorted)."""
    if prices is None or prices.empty:
        return None
    idx = prices.index.searchsorted(pd.Timestamp(d), side="right") - 1
    return float(prices.iloc[idx]) if idx >= 0 else None


def compute(panel: pd.DataFrame, prices: pd.Series | None = None) -> pd.DataFrame:
    """Add the metric columns to a futures-only disaggregated panel sorted by report_date (one contract)."""
    if panel.empty:
        return panel
    m = panel.sort_values("report_date").reset_index(drop=True).copy()
    for g in ("mm", "or", "nr", "sd", "pm"):
        m[f"{g}_net"] = m[f"{g}_long"] - m[f"{g}_short"]
        m[f"{g}_net_chg"] = m[f"{g}_net"].diff()
        m[f"{g}_net_pct_oi"] = 100.0 * m[f"{g}_net"] / m["open_interest"].replace(0, np.nan)
    m["comm_net"] = m["pm_net"] + m["sd_net"]
    m["comm_net_chg"] = m["comm_net"].diff()
    m["oi_chg_calc"] = m["open_interest"].diff()
    m["mm_long_chg"], m["mm_short_chg"] = m["mm_long"].diff(), m["mm_short"].diff()
    for w in (26, 52, 156):
        m[f"mm_net_idx{w}"] = cot_index(m["mm_net"], w)
        m[f"comm_net_idx{w}"] = cot_index(m["comm_net"], w)
    m["mm_net_z52"], m["mm_net_z156"] = zscore(m["mm_net"], 52), zscore(m["mm_net"], 156)
    m["mm_net_chg_z52"] = zscore(m["mm_net_chg"], 52)
    m["mm_net_pctile_all"] = expanding_percentile(m["mm_net"])
    m["oi_pctile_all"] = expanding_percentile(m["open_interest"])
    m["mm_net_moz"] = m["mm_net"] * OZ_PER_CONTRACT / 1e6
    m["mm_net_t"] = m["mm_net"] * OZ_PER_CONTRACT / OZ_PER_TONNE
    px = [price_at(prices, pd.Timestamp(d).date()) for d in m["report_date"]]
    m["price"] = px
    m["price_chg_pct"] = pd.Series(px, dtype="float64").pct_change() * 100.0
    m["mm_net_usd_bn"] = m["mm_net"] * OZ_PER_CONTRACT * m["price"] / 1e9
    m["quadrant"] = [quadrant_label(dp, doi) for dp, doi in zip(m["price_chg_pct"], m["oi_chg_calc"])]
    m["driver"] = [driver_label(dp, dl, ds) for dp, dl, ds in zip(m["price_chg_pct"], m["mm_long_chg"], m["mm_short_chg"])]
    return m


def load_panel(store: Any, contract: str = "088691", report: str = "disagg", foc: str = "F") -> pd.DataFrame:
    return db.query_df(store, """
        SELECT * FROM gold_cot WHERE contract_code = ? AND report = ? AND fut_or_combined = ? ORDER BY report_date
    """, [contract, report, foc])


def load_prices(store: Any, symbol: str = "GC=F") -> pd.Series | None:
    df = db.query_df(store, "SELECT trade_date, close FROM gold_daily_bars WHERE symbol = ? ORDER BY trade_date", [symbol])
    if df.empty:
        return None
    s = pd.Series(df["close"].values, index=pd.to_datetime(df["trade_date"]))
    return s[~s.index.duplicated(keep="last")]


def _f(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and np.isnan(v)) or (hasattr(v, "item") and pd.isna(v)):
        return None
    return float(v)


def _i(v: Any) -> int | None:
    f = _f(v)
    return round(f) if f is not None else None


def _decomp(m: pd.DataFrame, i_from: int, i_to: int, gld: pd.Series | None) -> dict[str, Any]:
    a, b = m.iloc[i_from], m.iloc[i_to]
    d_gld = None
    if gld is not None and not gld.empty:
        ga, gb = price_at(gld, pd.Timestamp(a["report_date"]).date()), price_at(gld, pd.Timestamp(b["report_date"]).date())
        d_gld = (gb - ga) if ga is not None and gb is not None else None
    return {"span": f"{pd.Timestamp(a['report_date']).date()} → {pd.Timestamp(b['report_date']).date()}",
            "price_from": _f(a["price"]), "price_to": _f(b["price"]),
            "d_mm_long": _i(b["mm_long"] - a["mm_long"]), "d_mm_short": _i(b["mm_short"] - a["mm_short"]),
            "d_mm_net": _i(b["mm_net"] - a["mm_net"]), "d_comm_net": _i(b["comm_net"] - a["comm_net"]),
            "d_sd_net": _i(b["sd_net"] - a["sd_net"]), "d_pm_net": _i(b["pm_net"] - a["pm_net"]),
            "d_or_net": _i(b["or_net"] - a["or_net"]), "d_nr_net": _i(b["nr_net"] - a["nr_net"]),
            "d_oi": _i(b["open_interest"] - a["open_interest"]), "d_gld_t": _f(d_gld)}


def summary(store: Any, *, weeks: int = 52, contract: str = "088691") -> dict[str, Any]:
    """The /db/gold/cot payload (PLAN §d ``/api/gold/cot`` minus the ui-api-only fields)."""
    panel = load_panel(store, contract)
    if panel.empty:
        return {"available": False, "badge": "context", "footer": FOOTER, "history": [], "groups": []}
    prices = load_prices(store)
    m = compute(panel, prices)
    last, prev = m.iloc[-1], (m.iloc[-2] if len(m) > 1 else None)
    rd = pd.Timestamp(last["report_date"]).date()
    oi = _i(last["open_interest"])
    groups = []
    for key, (label, p) in GROUPS.items():
        lg, sh = _i(last[f"{p}_long"]), _i(last[f"{p}_short"])
        spread = _i(last[f"{p}_spread"]) if f"{p}_spread" in m.columns else None
        dl, ds = _i(last.get(f"chg_{p}_long")), _i(last.get(f"chg_{p}_short"))
        net = (lg or 0) - (sh or 0)
        groups.append({"key": key, "label": label, "long": lg, "short": sh, "spread": spread, "net": net,
                       "net_moz": round(net * OZ_PER_CONTRACT / 1e6, 3), "net_t": round(net * OZ_PER_CONTRACT / OZ_PER_TONNE, 1),
                       "net_usd_bn": (round(net * OZ_PER_CONTRACT * last["price"] / 1e9, 2) if _f(last["price"]) else None),
                       "chg_long": dl, "chg_short": ds, "chg_net": (dl or 0) - (ds or 0) if dl is not None and ds is not None else None,
                       "pct_oi_long": round(100.0 * (lg or 0) / oi, 1) if oi else None,
                       "pct_oi_short": round(100.0 * (sh or 0) / oi, 1) if oi else None,
                       "net_pct_oi": round(100.0 * net / oi, 1) if oi else None,
                       "traders_long": _i(last.get(f"traders_{p}_long")), "traders_short": _i(last.get(f"traders_{p}_short")),
                       "who_did": who_did(dl, ds)})
    hist = m.tail(weeks)
    history = [{"report_date": str(pd.Timestamp(r.report_date).date()), "price": _f(r.price), "mm_net": _i(r.mm_net),
                "or_net": _i(r.or_net), "nr_net": _i(r.nr_net), "sd_net": _i(r.sd_net), "pm_net": _i(r.pm_net),
                "oi": _i(r.open_interest), "cot_index_52": _f(r.mm_net_idx52), "driver": r.driver, "quadrant": r.quadrant}
               for r in hist.itertuples(index=False)]
    combined = load_panel(store, contract, "disagg", "C")
    options_overlay: dict[str, Any] = {"mm_net_options_only": None, "combined_oi": None, "line": None}
    if not combined.empty:
        c = combined.iloc[-1]
        if pd.Timestamp(c["report_date"]).date() == rd:
            mm_c = int(c["mm_long"] - c["mm_short"])
            opt_only = mm_c - int(last["mm_net"])
            options_overlay = {"mm_net_options_only": opt_only, "combined_oi": _i(c["open_interest"]),
                               "line": f"options add {opt_only:+,} to funds' net; combined OI {int(c['open_interest']):,}"}
    gld = None
    g = db.query_df(store, "SELECT report_date, tonnes FROM gold_etf_holdings WHERE fund = 'GLD' ORDER BY report_date")
    if not g.empty:
        gld = pd.Series(g["tonnes"].values, index=pd.to_datetime(g["report_date"]))
    decomposition = []
    if m["price"].notna().sum() > 10:
        two_y = m[pd.to_datetime(m["report_date"]) >= (pd.Timestamp(rd) - pd.Timedelta(days=730))]
        i_low = int(two_y["price"].idxmin()) if two_y["price"].notna().any() else None
        i_high = int(m["price"].idxmax())
        if i_low is not None and i_low < len(m) - 1:
            decomposition.append({"label": "since the 2-year low", **_decomp(m, i_low, len(m) - 1, gld)})
        if i_high < len(m) - 1:
            decomposition.append({"label": "since the high", **_decomp(m, i_high, len(m) - 1, gld)})
    release_at = pd.Timestamp(last["release_at"])
    next_rel = pd.Timestamp(rd) + pd.Timedelta(days=7)
    from gold import pit
    next_rel_utc = pit.cot_release_at(next_rel.date())
    stale_days = (pd.Timestamp(db.utcnow()) - release_at).days
    return {
        "available": True, "contract_code": contract,
        "latest": {"report_date": str(rd), "release_at": db.iso_utc(release_at),
                   "next_release_ist": pd.Timestamp(next_rel_utc, tz="UTC").tz_convert("Asia/Kolkata").isoformat(),
                   "stale": stale_days > 10, "age_days": stale_days},
        "open_interest": {"total": oi, "chg": _i(last["oi_chg"] if _f(last["oi_chg"]) is not None else last["oi_chg_calc"]),
                          "pct_rank": _f(last["oi_pctile_all"])},
        "groups": groups,
        "driver_label": last["driver"], "driver_rule": driver_rule.RULE_TEXT, "quadrant_label": last["quadrant"],
        "week_price_chg_pct": _f(last["price_chg_pct"]),
        "prev_report_date": str(pd.Timestamp(prev["report_date"]).date()) if prev is not None else None,
        "crowd": {"cot_index_26": _f(last["mm_net_idx26"]), "cot_index_52": _f(last["mm_net_idx52"]),
                  "cot_index_156": _f(last["mm_net_idx156"]), "z52": _f(last["mm_net_z52"]), "z156": _f(last["mm_net_z156"]),
                  "percentile_all": _f(last["mm_net_pctile_all"]), "flow_z52": _f(last["mm_net_chg_z52"]), "label": CROWD_LABEL},
        "options_overlay": options_overlay,
        "history": history, "decomposition": decomposition,
        "drawer": {"traders": {"total": _i(last["traders_total"]), "mm_long": _i(last["traders_mm_long"]),
                               "mm_short": _i(last["traders_mm_short"]), "mm_spread": _i(last["traders_mm_spread"]),
                               "avg_mm_long": (round(last["mm_long"] / last["traders_mm_long"]) if _f(last["traders_mm_long"]) else None)},
                   "concentration": {k: _f(last[k]) for k in ("conc_gross4_long", "conc_gross4_short", "conc_gross8_long",
                                                               "conc_gross8_short", "conc_net4_long", "conc_net4_short",
                                                               "conc_net8_long", "conc_net8_short")},
                   "micro_gold": _micro(store, rd), "raw_block_url": RAW_BLOCK_URL, "api_query": API_QUERY},
        "badge": "context", "evidence": "context · G-STUDY 26 Oct 2026: same-week Spearman +0.65, next week −0.02",
        "footer": FOOTER,
    }


def _micro(store: Any, rd: date) -> dict[str, Any] | None:
    r = db.query_df(store, """
        SELECT open_interest, mm_long, mm_short, nr_long, nr_short FROM gold_cot
        WHERE contract_code = '088695' AND report = 'disagg' AND fut_or_combined = 'F' AND report_date = ?
    """, [rd])
    if r.empty:
        return None
    x = r.iloc[0]
    return {"oi": _i(x["open_interest"]), "mm_net": _i(x["mm_long"] - x["mm_short"]), "nr_net": _i(x["nr_long"] - x["nr_short"])}


def metrics_frame(store: Any, contract: str = "088691") -> pd.DataFrame:
    return compute(load_panel(store, contract), load_prices(store))
