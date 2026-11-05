"""
End-of-day option chain (Bloomberg OMON) from NSE's F&O bhavcopy (UDiFF format, cached under
data/nse_archive/fo/<year>/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip by the EOD pipeline).

For an underlying (NIFTY, BANKNIFTY, or any F&O stock) and an expiry: per strike call/put close, open interest,
OI change and volume, plus implied volatility (Black–Scholes, r = 6.5 %, no dividends: an approximation for
stocks), put/call OI ratio, max pain, and the strikes with the largest call / put OI (where option writers sit).
Everything is the last published session; there is no live data here.
"""
from __future__ import annotations

import math
import re
import zipfile
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

RISK_FREE = 0.065
FILE_RE = re.compile(r"BhavCopy_NSE_FO_0_0_0_(\d{8})_F_0000\.csv\.zip$")
OPTION_TYPES = {"IDO", "STO"}     # index options, stock options
FUTURE_TYPES = {"IDF", "STF"}


def files(root: Path) -> list[tuple[date, Path]]:
    """UDiFF F&O bhavcopies under root, oldest first."""
    out = []
    for p in root.glob("*/BhavCopy_NSE_FO_0_0_0_*_F_0000.csv.zip"):
        m = FILE_RE.search(p.name)
        if m:
            d = m.group(1)
            out.append((date(int(d[:4]), int(d[4:6]), int(d[6:])), p))
    return sorted(out)


@lru_cache(maxsize=4)
def load(path: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        df = pd.read_csv(z.open(z.namelist()[0]), low_memory=False)
    keep = ["TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "ClsPric", "SttlmPric",
            "UndrlygPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty"]
    df = df[keep].copy()
    df["XpryDt"] = pd.to_datetime(df["XpryDt"])
    df["TradDt"] = pd.to_datetime(df["TradDt"])
    return df


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs_price(s: float, k: float, t: float, vol: float, call: bool, r: float = RISK_FREE) -> float:
    if t <= 0 or vol <= 0:
        return max(0.0, (s - k) if call else (k - s))
    d1 = (math.log(s / k) + (r + vol * vol / 2) * t) / (vol * math.sqrt(t))
    d2 = d1 - vol * math.sqrt(t)
    if call:
        return s * _norm_cdf(d1) - k * math.exp(-r * t) * _norm_cdf(d2)
    return k * math.exp(-r * t) * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def implied_vol(price: float, s: float, k: float, t: float, call: bool) -> Optional[float]:
    """Bisection on Black–Scholes; None when the price is below intrinsic or above the no-arbitrage bound."""
    if price <= 0 or t <= 0 or s <= 0 or k <= 0:
        return None
    intrinsic = max(0.0, (s - k * math.exp(-RISK_FREE * t)) if call else (k * math.exp(-RISK_FREE * t) - s))
    if price < intrinsic + 1e-6 or price >= (s if call else k):
        return None
    lo, hi = 1e-4, 5.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if bs_price(s, k, t, mid, call) > price:
            hi = mid
        else:
            lo = mid
    v = (lo + hi) / 2
    return v if 0.005 < v < 4.9 else None


def max_pain(strikes: np.ndarray, call_oi: np.ndarray, put_oi: np.ndarray) -> Optional[float]:
    """Expiry price at which option holders' total payoff (what writers pay) is smallest."""
    if len(strikes) == 0 or (call_oi.sum() + put_oi.sum()) == 0:
        return None
    pay = [(call_oi * np.maximum(0, s - strikes)).sum() + (put_oi * np.maximum(0, strikes - s)).sum() for s in strikes]
    return float(strikes[int(np.argmin(pay))])


def underlyings(df: pd.DataFrame) -> list[str]:
    return sorted(df.loc[df["FinInstrmTp"].isin(OPTION_TYPES), "TckrSymb"].unique().tolist())


def chain(df: pd.DataFrame, symbol: str, expiry: Optional[str] = None, width_pct: Optional[float] = None) -> dict[str, Any]:
    sym = symbol.upper()
    opts = df[(df["TckrSymb"] == sym) & df["FinInstrmTp"].isin(OPTION_TYPES)]
    if width_pct is None:                    # indices list strikes 50 points apart: ±6 % is ~50 rows; stocks ±12 %
        width_pct = 6.0 if (opts["FinInstrmTp"] == "IDO").any() else 12.0
    if opts.empty:
        return {"symbol": sym, "found": False}
    trade_day = opts["TradDt"].iloc[0]
    expiries = sorted(opts["XpryDt"].unique())
    exp = pd.Timestamp(expiry) if expiry else expiries[0]
    if exp not in set(expiries):
        exp = expiries[0]
    o = opts[opts["XpryDt"] == exp]
    spot = float(o["UndrlygPric"].dropna().iloc[0]) if o["UndrlygPric"].notna().any() else None
    fut = df[(df["TckrSymb"] == sym) & df["FinInstrmTp"].isin(FUTURE_TYPES)].sort_values("XpryDt")
    fut_near = float(fut["ClsPric"].iloc[0]) if len(fut) else None
    t = max((exp - trade_day).days, 0) / 365 + 0.5 / 365          # half a day for the expiry session
    lot = int(o["NewBrdLotQty"].dropna().iloc[0]) if o["NewBrdLotQty"].notna().any() else None

    def side(kind: str) -> pd.DataFrame:
        x = o[o["OptnTp"] == kind].set_index("StrkPric")
        px = np.where(x["TtlTradgVol"] > 0, x["ClsPric"], x["SttlmPric"])
        return pd.DataFrame({"price": px, "oi": x["OpnIntrst"], "oi_chg": x["ChngInOpnIntrst"], "volume": x["TtlTradgVol"],
                             "traded": x["TtlTradgVol"] > 0}, index=x.index)

    ce, pe = side("CE"), side("PE")
    strikes = np.array(sorted(set(ce.index) | set(pe.index)), dtype=float)
    ce, pe = ce.reindex(strikes), pe.reindex(strikes)
    call_oi, put_oi = ce["oi"].fillna(0).to_numpy(), pe["oi"].fillna(0).to_numpy()
    mp = max_pain(strikes, call_oi, put_oi)
    s_ref = spot or fut_near or float(strikes[len(strikes) // 2])
    atm = float(strikes[int(np.argmin(np.abs(strikes - s_ref)))])
    # Options price off the forward, not spot: take it from put–call parity at the ATM strike when both sides
    # traded (F = K + (C − P)·e^{rT}), else the near future, else spot. IVs use S_eff = F·e^{−rT} (Black-76).
    c_atm, p_atm = ce.loc[atm], pe.loc[atm]
    if bool(c_atm["traded"]) and bool(p_atm["traded"]) and pd.notna(c_atm["price"]) and pd.notna(p_atm["price"]):
        forward = atm + (float(c_atm["price"]) - float(p_atm["price"])) * math.exp(RISK_FREE * t)
        fwd_source = "put-call parity"
    else:
        forward, fwd_source = (fut_near, "future") if fut_near else (s_ref * math.exp(RISK_FREE * t), "spot")
    s_eff = forward * math.exp(-RISK_FREE * t)
    rows: list[dict[str, Any]] = []
    for k in strikes:
        if abs(k / s_ref - 1) * 100 > width_pct:
            continue
        c, p = ce.loc[k], pe.loc[k]
        # IV only where the option is out of (or within 3 % of) the money: deep in-the-money prices are stale and noisy
        civ = implied_vol(float(c["price"]), s_eff, float(k), t, True) \
            if pd.notna(c["price"]) and c["traded"] and k >= forward * 0.97 else None
        piv = implied_vol(float(p["price"]), s_eff, float(k), t, False) \
            if pd.notna(p["price"]) and p["traded"] and k <= forward * 1.03 else None
        f = lambda v, d=2: None if pd.isna(v) else round(float(v), d)  # noqa: E731
        rows.append({"strike": float(k),
                     "ce": {"price": f(c["price"]), "oi": f(c["oi"], 0), "oi_chg": f(c["oi_chg"], 0), "volume": f(c["volume"], 0),
                            "iv": round(civ * 100, 1) if civ else None},
                     "pe": {"price": f(p["price"]), "oi": f(p["oi"], 0), "oi_chg": f(p["oi_chg"], 0), "volume": f(p["volume"], 0),
                            "iv": round(piv * 100, 1) if piv else None}})
    atm_row = next((r for r in rows if r["strike"] == atm), None)
    atm_iv = None
    if atm_row:
        ivs = [v for v in (atm_row["ce"]["iv"], atm_row["pe"]["iv"]) if v]
        atm_iv = round(sum(ivs) / len(ivs), 1) if ivs else None
    tot_c, tot_p = float(call_oi.sum()), float(put_oi.sum())
    top = lambda arr, n=3: [float(strikes[i]) for i in np.argsort(-arr)[:n] if arr[i] > 0]  # noqa: E731
    return {
        "symbol": sym, "found": True, "date": trade_day.strftime("%Y-%m-%d"), "expiry": exp.strftime("%Y-%m-%d"),
        "expiries": [pd.Timestamp(e).strftime("%Y-%m-%d") for e in expiries], "days_to_expiry": int((exp - trade_day).days),
        "spot": spot, "future": fut_near, "forward": round(forward, 2), "forward_source": fwd_source,
        "atm": atm, "lot": lot, "atm_iv": atm_iv,
        "expected_move_pct": round(atm_iv * math.sqrt(t), 2) if atm_iv else None,
        "pcr_oi": round(tot_p / tot_c, 2) if tot_c else None, "max_pain": mp,
        "call_oi_total": tot_c, "put_oi_total": tot_p,
        "resistance": top(call_oi), "support": top(put_oi), "rows": rows,
    }


INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def live_frame(payload: dict, symbol: str, lot: Optional[int], today: Optional[date] = None) -> pd.DataFrame:
    """NSE live option chain (api/option-chain-v3) → rows shaped like the F&O bhavcopy, so `chain()` computes IVs,
    max pain and walls exactly as for end of day. Live OI is in contracts: × lot to match the bhavcopy's shares."""
    sym = symbol.upper()
    kind = "IDO" if sym in INDEX_SYMBOLS else "STO"
    rec = (payload or {}).get("records") or {}
    day = pd.Timestamp(today or date.today())
    mult = lot or 1
    rows = []
    for d in rec.get("data") or []:
        for side in ("CE", "PE"):
            x = d.get(side)
            if not x:
                continue
            try:
                exp = pd.Timestamp(datetime.strptime(str(x.get("expiryDate") or d.get("expiryDates")), "%d-%m-%Y"))
            except ValueError:
                try:
                    exp = pd.Timestamp(datetime.strptime(str(d.get("expiryDates")), "%d-%b-%Y"))
                except ValueError:
                    continue
            vol = float(x.get("totalTradedVolume") or 0)
            px = x.get("lastPrice")
            rows.append({"TckrSymb": sym, "FinInstrmTp": kind, "TradDt": day, "XpryDt": exp,
                         "UndrlygPric": x.get("underlyingValue") or rec.get("underlyingValue"),
                         "StrkPric": float(d.get("strikePrice") or x.get("strikePrice")), "OptnTp": side,
                         "ClsPric": px, "SttlmPric": px, "OpnIntrst": float(x.get("openInterest") or 0) * mult,
                         "ChngInOpnIntrst": float(x.get("changeinOpenInterest") or 0) * mult,
                         "TtlTradgVol": vol, "NewBrdLotQty": lot})
    return pd.DataFrame(rows, columns=["TckrSymb", "FinInstrmTp", "TradDt", "XpryDt", "UndrlygPric", "StrkPric", "OptnTp",
                                       "ClsPric", "SttlmPric", "OpnIntrst", "ChngInOpnIntrst", "TtlTradgVol", "NewBrdLotQty"])


HISTORY_SYMBOLS = ("NIFTY", "BANKNIFTY")


def update_history(root: Path, cache: Path, symbols: tuple[str, ...] = HISTORY_SYMBOLS) -> dict[str, list[dict[str, Any]]]:
    """Daily near-expiry ATM IV, PCR (OI) and max pain per symbol, one row per cached bhavcopy. Incremental: dates
    already in `cache` (JSON) are skipped, so after the first build (~1 min for ~550 files) a day costs one file.
    Expiries within 2 days are skipped in favour of the next one (expiry-day IV is noise)."""
    import json
    hist: dict[str, list[dict[str, Any]]] = {}
    if cache.is_file():
        try:
            hist = json.loads(cache.read_text())
        except ValueError:
            hist = {}
    done = {s: {r["date"] for r in hist.get(s, [])} for s in symbols}
    changed = False
    for day, path in files(root):
        iso = day.isoformat()
        if all(iso in done[s] for s in symbols):
            continue
        try:
            df = load(str(path))
        except Exception:  # noqa: BLE001 — a corrupt file must not stop the history
            continue
        for s in symbols:
            if iso in done[s]:
                continue
            opts = df[(df["TckrSymb"] == s) & df["FinInstrmTp"].isin(OPTION_TYPES)]
            if opts.empty:
                continue
            exps = sorted(e for e in opts["XpryDt"].unique() if (pd.Timestamp(e) - opts["TradDt"].iloc[0]).days > 2)
            if not exps:
                continue
            c = chain(df, s, pd.Timestamp(exps[0]).strftime("%Y-%m-%d"))
            if c.get("found"):
                hist.setdefault(s, []).append({"date": iso, "spot": c["spot"], "atm_iv": c["atm_iv"], "pcr": c["pcr_oi"],
                                               "max_pain": c["max_pain"], "expiry": c["expiry"]})
                done[s].add(iso)
                changed = True
    if changed:
        for s in hist:
            hist[s].sort(key=lambda r: r["date"])
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(hist))
        tmp.replace(cache)
    return hist


def implied_event_move(expected_move_pct: float, trading_days: int, daily_vol_pct: float) -> dict[str, Optional[float]]:
    """Split the options' priced move to expiry into normal days + one event (results) day:
    event σ² = expected_move² − (trading_days − 1) × normal daily σ². Returns the event's σ and its expected
    absolute move (σ × √(2/π) ≈ 0.80 σ, comparable with an average absolute results-day move). An approximation:
    normal-day volatility is taken from the stock's recent realised moves."""
    if not expected_move_pct or trading_days < 1 or daily_vol_pct is None:
        return {"event_sigma_pct": None, "event_abs_move_pct": None}
    rest = expected_move_pct ** 2 - max(trading_days - 1, 0) * daily_vol_pct ** 2
    sigma = math.sqrt(rest) if rest > 0 else 0.0
    return {"event_sigma_pct": round(sigma, 2), "event_abs_move_pct": round(sigma * math.sqrt(2 / math.pi), 2)}


def implied_event_move_term(em1: float, n1: int, em2: float, n2: int) -> dict[str, Optional[float]]:
    """Term-structure version (both expiries after the results): normal daily variance = (em2² − em1²) ÷ (n2 − n1),
    event variance = em1² − (n1 − 1) × normal. Uses the options' own normal-day volatility, so the volatility risk
    premium largely cancels (the realised-volatility version overstates the event). None when inconsistent."""
    if not em1 or not em2 or n2 <= n1 or n1 < 1:
        return {"event_sigma_pct": None, "event_abs_move_pct": None, "normal_daily_pct": None}
    normal = (em2 ** 2 - em1 ** 2) / (n2 - n1)
    if normal <= 0:
        return {"event_sigma_pct": None, "event_abs_move_pct": None, "normal_daily_pct": None}
    rest = em1 ** 2 - (n1 - 1) * normal
    sigma = math.sqrt(rest) if rest > 0 else 0.0
    return {"event_sigma_pct": round(sigma, 2), "event_abs_move_pct": round(sigma * math.sqrt(2 / math.pi), 2),
            "normal_daily_pct": round(math.sqrt(normal), 2)}
