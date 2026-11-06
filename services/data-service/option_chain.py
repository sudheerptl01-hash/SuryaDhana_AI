"""
End-of-day option chain (Bloomberg OMON) from NSE's F&O bhavcopy (UDiFF format, cached under
data/nse_archive/fo/<year>/BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip by the EOD pipeline).

For an underlying (NIFTY, BANKNIFTY, or any F&O stock) and an expiry: per strike call/put close, open interest,
OI change and volume, plus implied volatility, put/call OI ratio, max pain, and the strikes with the largest call / put OI
(where option writers sit). Everything is the last published session (or NSE's live chain through ``live_frame``).

One method with the IV store (M04, review 5 Nov 2026): the forward, the per-strike IVs and the ATM IV come from
``fo_iv.black76`` — the parity forward with the store's future fallback, Black-76 on traded prices only, the ATM IV
interpolated at the forward — and T follows ``black76.TIME_CONVENTION`` (calendar time to 15:30 IST on expiry ÷ 365; whole
days at end of day, the snapshot clock intraday; the old +0.5-day expiry session is gone), so the chain tile and the
stored ladder print one ATM IV for one expiry. ``t_years`` / ``t_days`` are in the payload for the chain Greeks and OSTR.

Units (M05): the UDiFF file's OI and OI change are in SHARES and its volume in CONTRACTS; the payload keeps those raw
fields and adds ``oi_contracts`` / ``oi_chg_contracts`` (÷ lot) plus ``units`` so every reader can print one unit.
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

from fo_iv import black76 as b76

# The chain's r must equal the IV store's (fo_iv.iv_eod.DEFAULT_R, the rate_curve seed) or one expiry gets two ATM IVs again
# (M04). Both are the dated 6.5 % constant until the owner decides O-T5; when rate_curve gets a new row, the chain must read
# iv_eod.rate_for(store, day) instead. Pinned by tests/unit/test_vvol_fixes.py::test_one_clock_and_one_rate_literals_are_pinned.
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


FWD_SOURCE_LABEL = {"pcp": "put-call parity", "future": "future", "spot": "spot"}
WALL_REACH = 2.0          # a wall strike outside the ±width window widens it, up to WALL_REACH × width (m048)


def valuation_of(frame: pd.DataFrame, trade_day: pd.Timestamp) -> date | datetime:
    """The valuation instant: the live frame's ``ValDt`` (the snapshot clock, IST) when present, else the session date (its
    15:30 close) — ``black76.t_years`` turns either into T."""
    if "ValDt" in frame.columns and frame["ValDt"].notna().any():
        return pd.Timestamp(frame["ValDt"].dropna().iloc[0]).to_pydatetime()
    return pd.Timestamp(trade_day).date()


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
    fut_same = fut[fut["XpryDt"] == exp]
    fut_exp = float(fut_same["ClsPric"].iloc[0]) if len(fut_same) and pd.notna(fut_same["ClsPric"].iloc[0]) and fut_same["ClsPric"].iloc[0] > 0 else None
    t = b76.t_years(pd.Timestamp(exp).date(), valuation_of(o, trade_day))
    lot = int(o["NewBrdLotQty"].dropna().iloc[0]) if o["NewBrdLotQty"].notna().any() else None

    def side(kind: str) -> pd.DataFrame:
        x = o[o["OptnTp"] == kind].drop_duplicates("StrkPric").set_index("StrkPric")
        traded = x["TtlTradgVol"].fillna(0) > 0
        px = np.where(traded, x["ClsPric"], x["SttlmPric"])
        return pd.DataFrame({"price": px, "close": x["ClsPric"], "oi": x["OpnIntrst"], "oi_chg": x["ChngInOpnIntrst"], "volume": x["TtlTradgVol"],
                             "traded": traded}, index=x.index)

    ce, pe = side("CE"), side("PE")
    strikes = np.array(sorted(set(ce.index) | set(pe.index)), dtype=float)
    ce, pe = ce.reindex(strikes), pe.reindex(strikes)
    ce["traded"], pe["traded"] = ce["traded"].fillna(False).astype(bool), pe["traded"].fillna(False).astype(bool)
    call_oi, put_oi = ce["oi"].fillna(0).to_numpy(), pe["oi"].fillna(0).to_numpy()
    mp = max_pain(strikes, call_oi, put_oi)
    s_ref = spot or fut_near or float(strikes[len(strikes) // 2])
    atm = float(strikes[int(np.argmin(np.abs(strikes - s_ref)))])

    def traded_px(frame: pd.DataFrame, k: float) -> float | None:
        r = frame.loc[k]
        if not bool(r["traded"]) or pd.isna(r["close"]) or float(r["close"]) <= 0:
            return None
        return float(r["close"])

    # the store's forward (black76.choose_forward: parity at the first of the 3 strikes nearest spot where both sides traded,
    # the same-expiry future beyond 0.5 %, else the future, else spot·e^{rT}) and its IVs (traded prices, OTM + 3 % ITM)
    both = [k for k in strikes if k in ce.index and k in pe.index and pd.notna(ce.loc[k, "volume"]) and pd.notna(pe.loc[k, "volume"])]
    pairs = {float(k): (traded_px(ce, k), traded_px(pe, k)) for k in both}
    if t > 0:
        forward, fsrc, fwd_flags = b76.choose_forward(pairs, s_ref, t, RISK_FREE, fut_exp)
        ivmap = b76.strike_ivs(pairs, forward, t, RISK_FREE)
    else:                                    # past 15:30 on expiry day: intrinsic only, no IV
        forward, fsrc, fwd_flags, ivmap = (fut_exp or s_ref), ("future" if fut_exp else "spot"), ["expired"], {}
    kk = sorted(ivmap)
    atm_iv_dec = b76.atm_iv_at_forward(kk, [ivmap[k][0] for k in kk], forward) if len(kk) >= 2 else None
    tops_c = [float(strikes[i]) for i in np.argsort(-call_oi)[:3] if call_oi[i] > 0]
    tops_p = [float(strikes[i]) for i in np.argsort(-put_oi)[:3] if put_oi[i] > 0]
    lo_k, hi_k = s_ref * (1 - width_pct / 100), s_ref * (1 + width_pct / 100)
    for w in (tops_c[:1] + tops_p[:1]):      # m048: the wall's own row is always on the page when it is within reach
        if abs(w / s_ref - 1) * 100 <= width_pct * WALL_REACH:
            lo_k, hi_k = min(lo_k, w), max(hi_k, w)
    rows: list[dict[str, Any]] = []

    def to_c(v: Any) -> float | None:
        return None if v is None or pd.isna(v) or not lot else round(float(v) / lot, 1)

    for k in strikes:
        if not (lo_k - 1e-9 <= k <= hi_k + 1e-9):
            continue
        c, p = ce.loc[k], pe.loc[k]
        iv = ivmap.get(float(k))
        civ, piv = (iv[1], iv[2]) if iv else (None, None)
        f = lambda v, d=2: None if pd.isna(v) else round(float(v), d)  # noqa: E731
        rows.append({"strike": float(k),
                     "ce": {"price": f(c["price"]), "traded": bool(c["traded"]), "oi": f(c["oi"], 0), "oi_chg": f(c["oi_chg"], 0),
                            "oi_contracts": to_c(c["oi"]), "oi_chg_contracts": to_c(c["oi_chg"]), "volume": f(c["volume"], 0),
                            "iv": round(civ * 100, 2) if civ else None},
                     "pe": {"price": f(p["price"]), "traded": bool(p["traded"]), "oi": f(p["oi"], 0), "oi_chg": f(p["oi_chg"], 0),
                            "oi_contracts": to_c(p["oi"]), "oi_chg_contracts": to_c(p["oi_chg"]), "volume": f(p["volume"], 0),
                            "iv": round(piv * 100, 2) if piv else None}})
    atm_iv = round(atm_iv_dec * 100, 2) if atm_iv_dec else None
    tot_c, tot_p = float(call_oi.sum()), float(put_oi.sum())
    return {
        "symbol": sym, "found": True, "date": trade_day.strftime("%Y-%m-%d"), "expiry": exp.strftime("%Y-%m-%d"),
        "expiries": [pd.Timestamp(e).strftime("%Y-%m-%d") for e in expiries],
        "days_to_expiry": int((pd.Timestamp(exp).normalize() - pd.Timestamp(trade_day).normalize()).days),
        "t_years": round(t, 8), "t_days": round(t * 365.0, 4), "time_convention": b76.TIME_CONVENTION, "time_convention_note": b76.TIME_CONVENTION_NOTE,
        "model_version": b76.MODEL_VERSION, "r": RISK_FREE,
        "spot": spot, "future": fut_near, "forward": round(forward, 2), "forward_source": FWD_SOURCE_LABEL.get(fsrc, fsrc), "forward_flags": fwd_flags,
        "atm": atm, "lot": lot, "atm_iv": atm_iv,
        "expected_move_pct": round(atm_iv * math.sqrt(t), 2) if atm_iv else None,
        "pcr_oi": round(tot_p / tot_c, 2) if tot_c else None, "max_pain": mp,
        "call_oi_total": tot_c, "put_oi_total": tot_p,
        "call_oi_total_contracts": round(tot_c / lot, 0) if lot else None, "put_oi_total_contracts": round(tot_p / lot, 0) if lot else None,
        "units": {"oi": "shares", "oi_chg": "shares", "volume": "contracts", "oi_contracts": "contracts", "oi_chg_contracts": "contracts",
                  "price": "₹ per unit (traded close; NSE settlement when untraded, traded = false)"},
        "resistance": tops_c, "support": tops_p, "rows": rows,
    }


INDEX_SYMBOLS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


def live_frame(payload: dict, symbol: str, lot: Optional[int], today: Optional[date] = None, now: Optional[datetime] = None) -> pd.DataFrame:
    """NSE live option chain (api/option-chain-v3) → rows shaped like the F&O bhavcopy, so `chain()` computes IVs,
    max pain and walls exactly as for end of day. Live OI is in contracts: × lot to match the bhavcopy's shares.
    ``ValDt`` carries the snapshot clock (IST; ``now``, else the wall clock when ``today`` is not given) so T is the
    fractional time to 15:30 on expiry (black76.TIME_CONVENTION); a test that passes ``today`` alone values at its close."""
    sym = symbol.upper()
    kind = "IDO" if sym in INDEX_SYMBOLS else "STO"
    rec = (payload or {}).get("records") or {}
    if now is None and today is None:
        now = datetime.now(b76.IST).replace(tzinfo=None)
    day = pd.Timestamp(today or (now.date() if now else date.today()))
    val = pd.Timestamp(now) if now is not None else pd.NaT
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
            rows.append({"TckrSymb": sym, "FinInstrmTp": kind, "TradDt": day, "ValDt": val, "XpryDt": exp,
                         "UndrlygPric": x.get("underlyingValue") or rec.get("underlyingValue"),
                         "StrkPric": float(d.get("strikePrice") or x.get("strikePrice")), "OptnTp": side,
                         "ClsPric": px, "SttlmPric": px, "OpnIntrst": float(x.get("openInterest") or 0) * mult,
                         "ChngInOpnIntrst": float(x.get("changeinOpenInterest") or 0) * mult,
                         "TtlTradgVol": vol, "NewBrdLotQty": lot})
    return pd.DataFrame(rows, columns=["TckrSymb", "FinInstrmTp", "TradDt", "ValDt", "XpryDt", "UndrlygPric", "StrkPric", "OptnTp",
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
