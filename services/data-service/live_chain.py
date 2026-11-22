"""
Live option chain (owner-approved 22 Nov 2026): ``GET /live/option-chain/{symbol}?expiry=&width=``.

Base frame: NSE's option-chain v3 (the shared, cookie-primed, breaker-guarded NseLive client and its 30 s cache — the same
frame /db/option-chain-live serves), else the last cached F&O bhavcopy when NSE does not answer. Live overlay: the Breeze
websocket ticks of the contracts ATM ± ``width`` strikes (the live_ticks engine's F&O kind), written into that frame, then the
UNCHANGED ``option_chain.chain()`` recomputes forward, IVs, max pain and walls: one IV method for EOD, NSE and live.

Rules (binding):
- a strike side is overlaid only from a tick that is fresh (≤ live_ticks.FRESH_S) or vouched quiet (healthy feed, subscribed,
  ``live_quotes.tick_vouched`` against the engine's vouched_since, ≤ live_quotes.QUIET_LIVE_S) and from today's IST session;
  every other side keeps its base value and says so (``source`` nse | eod, ``tick_state`` why not live);
- units: the frame's OI is in SHARES and its volume in CONTRACTS (option_chain M05). A tick's OI is in shares and its ttq in
  shares (the recorded NIFTY 24400 CE tick: ltq 65 = one lot, OI and ttq divisible by 65, ttq × avgPrice = ttv lakh × 1e5),
  so volume = ttq ÷ the contract's lot (the FONSE master's LotSize). OI change = live OI − the previous session's STORED OI
  (the F&O bhavcopy before today), else NSE's own previous OI (OI − change in the NSE frame);
- the band centre recentres with hysteresis: only after spot has been more than RECENTRE_STRIKES strikes from the centre for
  RECENTRE_HOLD_S; the strike step is the commonest gap among the strikes nearest the money;
- expiry: the requested one when the master lists it and its 15:30 IST has not passed, else the near expiry = the first
  master expiry whose 15:30 IST has not passed (read from ICICI's master, never computed); NSE's / the bhavcopy's list only
  when the master has none;
- futures: the near and the same-expiry future are subscribed too; a live future tick enters the frame as the future row
  (chain()'s forward check). While anything is live, an EOD base's stored futures are dropped (yesterday's future would
  override a live parity forward) and the valuation clock is now;
- memoised for MEMO_S per (symbol, expiry, width). Request path: dict reads, the engine's ensure(), the NseLive cache (≤ one
  NSE call per 30 s per path, breaker-guarded) and cached bhavcopy reads — never a Breeze REST call, never Yahoo.
/db/option-chain-live is unchanged: it stays the fallback and the paper book's mark source.

Payload (the UI contract; field list in ``PAYLOAD_DOC``): chain()'s fields, plus per row ``band`` and per side ``source``,
``age_s``, ``tick_state``, ``key``, ``bid`` / ``ask`` / ``bid_qty`` / ``ask_qty`` / ``ltp`` / ``ltt``, and a chain-level ``feed``
block (counts per source, as_of, nse_as_of, the band, the subscription state).
"""
from __future__ import annotations

import functools
import math
import threading
import time
from collections import Counter
from datetime import date, datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import pandas as pd

import live_ticks as lt_mod
import option_chain as oc
from live_quotes import QUIET_LIVE_S, tick_vouched
from shared.logging import get_logger

logger = get_logger("live-chain")

IST = ZoneInfo("Asia/Kolkata")
FRESH_S = lt_mod.FRESH_S
MEMO_S = 1.0
DEFAULT_WIDTH, MAX_WIDTH = 10, 20          # 2 × (2·20 + 1) + 2 futures = 84 ≤ the default option cap of 90
RECENTRE_STRIKES = 1.5
RECENTRE_HOLD_S = 30.0
STEP_SAMPLE = 10                           # strikes nearest the money that set the step
BASE_TTL_S = 600.0                         # the EOD frame / stored previous OI are re-read at most this often
SOURCE_BREEZE, SOURCE_NSE, SOURCE_EOD = "breeze_ws", "nse", "eod"
LIVE_STATES = ("live", "quiet")
SIDES = ("CE", "PE")

PAYLOAD_DOC = {
    "rows[].band": "the strike is in the live band (ATM ± width)",
    "rows[].ce|pe.source": "breeze_ws (live tick overlaid) | nse (NSE option-chain v3) | eod (last F&O bhavcopy)",
    "rows[].ce|pe.price_source": "where the shown PRICE comes from: breeze_ws only when the contract traded today on the "
                                 "socket; an untraded live strike keeps the base frame's price (source still breeze_ws)",
    "rows[].ce|pe.age_s": "seconds since the tick arrived (breeze_ws) or since the base frame's own stamp",
    "rows[].ce|pe.tick_state": "live | quiet | stale | not_vouched | feed_unhealthy | other_session | waiting_first_tick | "
                               "not_subscribed | over_cap | error | feed_off | no_master | outside_band",
    "rows[].ce|pe.key": "the contract key NFO:<SYM>:<YYYY-MM-DD>:<STRIKE>:<CE|PE> (None outside the master)",
    "rows[].ce|pe.oi": "shares (oi_contracts = ÷ lot)", "rows[].ce|pe.volume": "contracts",
    "rows[].ce|pe.bid_qty|ask_qty": "shares (one lot = lot)",
    "feed": "counts, as_of, nse_as_of, eod_date, base, band, underlying, future, expiry, subscription, oi_chg_basis, units",
}


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=64)
def underlying_name(symbol: str) -> str:
    """The live-ticks name of an F&O underlying: the NSE index name for the index symbols (fo_iv.iv_eod.INDEX_NAMES, the one
    table), the symbol itself for a stock."""
    from fo_iv.iv_eod import INDEX_NAMES
    return INDEX_NAMES.get(symbol.upper(), symbol.upper())


def near_expiry(expiries: list[str], now: float) -> Optional[str]:
    """The first expiry whose 15:30 IST has not passed (expiries as the master lists them)."""
    for e in sorted(expiries):
        if not lt_mod.contract_expired(e, now):
            return e
    return None


def strike_step(strikes: list[float], spot: float, n: int = STEP_SAMPLE) -> Optional[float]:
    """The commonest gap among the ``n`` strikes nearest ``spot`` (NIFTY lists 50 near the money and 100 further out)."""
    near = sorted(sorted(strikes, key=lambda k: abs(k - spot))[:n])
    gaps = [round(b - a, 6) for a, b in zip(near, near[1:], strict=False) if b > a]
    if not gaps:
        return None
    c = Counter(gaps)
    best = max(c.values())
    return min(g for g, k in c.items() if k == best)


def nearest(strikes: list[float], x: float) -> float:
    return min(strikes, key=lambda k: (abs(k - x), k))


def band_of(strikes: list[float], centre: float, width: int) -> list[float]:
    """``width`` listed strikes either side of ``centre`` (by position, so a wider gap further out stays ``width`` rows)."""
    i = strikes.index(centre)
    return strikes[max(0, i - width): i + width + 1]


def _ist_date(epoch: float) -> date:
    return datetime.fromtimestamp(epoch, IST).date()


def _iso(epoch: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(epoch, IST).isoformat(timespec="seconds") if epoch else None


def _parse_nse_stamp(stamp: Any) -> Optional[float]:
    """NSE's records.timestamp ('28-Sep-2026 15:40:00', IST) → epoch."""
    try:
        return datetime.strptime(str(stamp).strip(), "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST).timestamp()
    except ValueError:
        return None


def tick_state(tick: Optional[dict], st: Optional[dict], healthy: bool, now: float, engine_state: str) -> str:
    """Why a contract's tick may (live, quiet) or may not overlay its strike side. The quiet rule is live_quotes' rule: a
    healthy feed, a subscribed contract and a tick the socket vouches for (tick_vouched against vouched_since)."""
    st = st or {}
    if not tick or tick.get("ts") is None:
        if st.get("error"):
            return "error"
        if st.get("over_cap"):
            return "over_cap"
        if st.get("subscribed"):
            return "waiting_first_tick"
        return "feed_off" if engine_state == lt_mod.OFF else "not_subscribed"
    ts = float(tick["ts"])
    if _ist_date(ts) != _ist_date(now):
        return "other_session"
    age = max(0.0, now - ts)
    if age <= FRESH_S:
        return "live"
    if not st.get("subscribed"):
        return "not_subscribed"
    if not healthy:
        return "feed_unhealthy"
    if not tick_vouched(ts, st.get("vouched_since")):
        return "not_vouched"
    return "quiet" if age <= QUIET_LIVE_S else "stale"


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


# ── the engine ────────────────────────────────────────────────────────────────────────────────────────────────────────

class LiveChain:
    """One per data-service process. Every dependency is injected (tests drive it on fakes):

    - ``ticks_getter()`` → the LiveTicks engine (or None);
    - ``maps_fn(underlyings)`` → the provider module's FoTokenMaps (``fo_master().maps``);
    - ``nse_fn(symbol, expiry ISO | None)`` → {"payload": option-chain-v3 JSON, "expiries": [ISO], "as_of": NSE's stamp,
      "fetched_at": epoch}; raises when NSE does not answer;
    - ``eod_fn(symbol)`` → {"frame": the symbol's rows of the last F&O bhavcopy, "date": ISO, "lot": int} or None;
    - ``prev_oi_fn(symbol, expiry ISO, session ISO)`` → {"date": ISO, "oi": {(strike, 'CE'|'PE'): shares}} from the last
      stored bhavcopy BEFORE the session, or None."""

    def __init__(self, *, ticks_getter: Callable[[], Any], maps_fn: Callable[[list[str]], Any],
                 nse_fn: Callable[[str, Optional[str]], dict], eod_fn: Callable[[str], Optional[dict]],
                 prev_oi_fn: Callable[[str, str, str], Optional[dict]], clock: Callable[[], float] = time.time) -> None:
        self._ticks_getter = ticks_getter
        self._maps_fn = maps_fn
        self._nse_fn = nse_fn
        self._eod_fn = eod_fn
        self._prev_oi_fn = prev_oi_fn
        self._clock = clock
        self._lock = threading.Lock()
        self._memo: dict[tuple, tuple[float, dict]] = {}
        self._centres: dict[tuple[str, str], dict] = {}
        self._eod_cache: dict[str, tuple[float, Optional[dict]]] = {}
        self._prev_cache: dict[tuple[str, str, str], tuple[float, Optional[dict]]] = {}
        self.computes = 0

    # ── request path ──────────────────────────────────────────────────────────────────────────────────────────────────

    def chain(self, symbol: str, expiry: Optional[str] = None, width: int = DEFAULT_WIDTH) -> dict:
        sym = symbol.upper()
        width = max(1, min(MAX_WIDTH, int(width)))
        key = (sym, expiry, width)
        now = self._clock()
        with self._lock:
            hit = self._memo.get(key)
            if hit is not None and now - hit[0] < MEMO_S:
                return hit[1]
        out = self._compute(sym, expiry, width, now)
        with self._lock:
            self._memo = {k: v for k, v in self._memo.items() if now - v[0] < 10 * MEMO_S}
            self._memo[key] = (now, out)
        return out

    def _ticks(self) -> Any:
        try:
            return self._ticks_getter()
        except Exception:  # noqa: BLE001
            return None

    def _cached(self, cache: dict, key: Any, now: float, fn: Callable[[], Optional[dict]]) -> Optional[dict]:
        with self._lock:
            hit = cache.get(key)
            if hit is not None and now - hit[0] < BASE_TTL_S:
                return hit[1]
        try:
            val = fn()
        except Exception as exc:  # noqa: BLE001 — a missing / unreadable bhavcopy only means no fallback
            logger.warning("live-chain: stored read failed", error=str(exc)[:160])
            val = None
        with self._lock:
            cache[key] = (now, val)
        return val

    def _eod(self, sym: str, now: float) -> Optional[dict]:
        return self._cached(self._eod_cache, sym, now, lambda: self._eod_fn(sym))

    def _prev_oi(self, sym: str, exp: str, session: str, now: float) -> Optional[dict]:
        return self._cached(self._prev_cache, (sym, exp, session), now, lambda: self._prev_oi_fn(sym, exp, session))

    def _band(self, sym: str, exp: str, strikes: list[float], spot: float, now: float) -> dict:
        """The band centre with hysteresis: a recentre only after spot has stayed more than RECENTRE_STRIKES steps away from
        the centre for RECENTRE_HOLD_S."""
        step = strike_step(strikes, spot) or 0.0
        atm = nearest(strikes, spot)
        with self._lock:
            st = self._centres.get((sym, exp))
            if st is None or st["centre"] not in strikes:
                st = {"centre": atm, "recentred_at": now, "pending_from": None}
            elif step and abs(spot - st["centre"]) > RECENTRE_STRIKES * step:
                if st["pending_from"] is None:
                    st = {**st, "pending_from": now}
                elif now - st["pending_from"] >= RECENTRE_HOLD_S:
                    st = {"centre": atm, "recentred_at": now, "pending_from": None}
            elif st["pending_from"] is not None:
                st = {**st, "pending_from": None}
            self._centres[(sym, exp)] = st
        return {"centre": st["centre"], "atm": atm, "step": step, "recentred_at": st["recentred_at"],
                "pending_s": round(now - st["pending_from"], 1) if st["pending_from"] is not None else None}

    # ── the computation ───────────────────────────────────────────────────────────────────────────────────────────────

    def _compute(self, sym: str, expiry_req: Optional[str], width: int, now: float) -> dict:
        self.computes += 1
        now_ist = datetime.fromtimestamp(now, IST)
        today = now_ist.date()
        lt = self._ticks()
        engine_state = getattr(lt, "state", lt_mod.OFF) if lt is not None else lt_mod.OFF

        # 1. the security master: expiries, strikes, lots, futures
        maps, master_error = None, None
        try:
            maps = self._maps_fn([sym])
        except Exception as exc:  # noqa: BLE001 — no master: the chain still serves its base frame, unlabelled live
            master_error = str(exc)[:160] or "F&O master unavailable"
        m_exps = [e for e in (maps.expiries(sym) if maps is not None else []) if not lt_mod.contract_expired(e, now)]
        note: Optional[str] = None
        exp: Optional[str]
        exp_src: Optional[str]
        if expiry_req and expiry_req in m_exps:
            exp, exp_src = expiry_req, "master"
        elif m_exps:
            exp, exp_src = m_exps[0], "master"
            if expiry_req:
                note = f"{expiry_req} is not a live expiry in the security master: showing the near expiry {exp}"
        else:
            exp, exp_src = expiry_req, None
        series = maps.series(sym, exp) if (maps is not None and exp) else []
        lot_master = next((c.lot for c in series if c.lot), None)

        # 2. the base frame: NSE v3, else the last bhavcopy
        base, base_error, nse_as_of, nse_epoch, eod_date, nse_payload = None, None, None, None, None, None
        frame: Optional[pd.DataFrame] = None
        lot = lot_master
        try:
            nse_info = self._nse_fn(sym, exp)
            nse_payload = nse_info.get("payload") or {}
            if lot is None:
                lot = (self._eod(sym, now) or {}).get("lot")
            frame = oc.live_frame(nse_payload, sym, lot, now=now_ist.replace(tzinfo=None))
            if frame.empty:
                raise LookupError("NSE returned an empty chain")
            nse_as_of = nse_info.get("as_of") or (nse_payload.get("records") or {}).get("timestamp")
            nse_epoch = _parse_nse_stamp(nse_as_of) or _f(nse_info.get("fetched_at"))
            base = SOURCE_NSE
            if exp is None:
                exp, exp_src = near_expiry(list(nse_info.get("expiries") or []), now), SOURCE_NSE
        except Exception as exc:  # noqa: BLE001 — NSE down / throttled / no such expiry: the stored bhavcopy instead
            base_error = str(exc)[:160] or type(exc).__name__
            eod = self._eod(sym, now)
            if eod is not None and eod.get("frame") is not None and not eod["frame"].empty:
                frame, base, eod_date = eod["frame"], SOURCE_EOD, eod.get("date")
                if lot is None:
                    lot = eod.get("lot")
                if exp is None:
                    exps = sorted(pd.Timestamp(e).date().isoformat() for e in frame.loc[
                        frame["FinInstrmTp"].isin(oc.OPTION_TYPES), "XpryDt"].unique())
                    exp, exp_src = near_expiry(exps, now) or (exps[0] if exps else None), SOURCE_EOD
        if frame is None or base is None or not exp:
            return {"symbol": sym, "found": False, "live": True, "as_of": _iso(now),
                    "error": f"no option chain for {sym}: NSE {base_error or 'gave nothing'}; no stored F&O bhavcopy row",
                    "feed": {"base": None, "base_error": base_error, "master_error": master_error}}
        if not series and maps is not None:
            series = maps.series(sym, exp)
        df = frame[frame["TckrSymb"] == sym].copy()
        if "ValDt" not in df.columns:
            df["ValDt"] = pd.NaT
        exp_ts = pd.Timestamp(exp)
        opt_mask = df["FinInstrmTp"].isin(oc.OPTION_TYPES) & (df["XpryDt"] == exp_ts)
        frame_spot = _f(df.loc[opt_mask, "UndrlygPric"].dropna().iloc[0]) if df.loc[opt_mask, "UndrlygPric"].notna().any() else None

        # 3. the underlying's live tick (index pins tick at 10 Hz and are subscribed before their chains)
        und = underlying_name(sym)
        healthy = False
        und_tick, und_state = None, "feed_off"
        if lt is not None:
            try:
                healthy = bool(lt.feed_healthy())
                und_tick = lt.snapshot([und]).get(und)
                und_st = {"subscribed": lt.is_subscribed(und), "vouched_since": lt.vouched_since(und)}
                und_state = tick_state(und_tick, und_st, healthy, now, engine_state)
            except Exception as exc:  # noqa: BLE001
                logger.warning("live-chain: underlying snapshot failed", error=str(exc)[:160])
        spot_live = _f(und_tick.get("price")) if (und_tick and und_state in LIVE_STATES) else None

        # 4. the band (master strikes of this expiry) and the contracts to ask for
        by_strike: dict[float, dict[str, Any]] = {}
        for c in series:
            by_strike.setdefault(float(c.strike), {})[c.right] = c
        strikes = sorted(by_strike)
        futs = [c for c in (maps.futures(sym) if maps is not None else []) if not lt_mod.contract_expired(c.expiry, now)]
        fut_rows = list(dict.fromkeys([f for f in (futs[:1] + [c for c in futs if c.expiry == exp]) if f is not None]))
        spot = spot_live or frame_spot
        band_info: dict[str, Any] = {"centre": None, "atm": None, "step": None, "width": width, "strikes": [],
                                     "recentred_at": None, "pending_s": None}
        band: list[float] = []
        if strikes and spot:
            b = self._band(sym, exp, strikes, spot, now)
            band = band_of(strikes, b["centre"], width)
            band_info.update(centre=b["centre"], atm=b["atm"], step=b["step"], strikes=band,
                             recentred_at=_iso(b["recentred_at"]), pending_s=b["pending_s"])
        centre = band_info["centre"]
        side_keys: dict[tuple[float, str], str] = {}
        for k in sorted(band, key=lambda k: (abs(k - (centre or 0.0)), k)):          # ATM outward: first at the cap
            for side in SIDES:
                c = by_strike[k].get(side)
                if c is not None:
                    side_keys[(k, side)] = lt_mod.contract_key(sym, exp, c.strike, side)
        fut_keys = {f.expiry: lt_mod.contract_key(sym, f.expiry, None, "FUT") for f in fut_rows}
        keys = list(fut_keys.values()) + list(side_keys.values())
        snap: dict[str, dict] = {}
        states: dict[str, dict] = {}
        lt_status: dict = {}
        if lt is not None:
            try:
                lt_status = lt.ensure([und] + keys)                     # the underlying first, then the futures, then ATM out
                snap = lt.snapshot(keys) if keys else {}
                states = lt.contract_states(keys) if keys else {}
                healthy = bool(lt.feed_healthy())
                engine_state = getattr(lt, "state", engine_state)
            except Exception as exc:  # noqa: BLE001 — the tick engine failing must not blank the chain
                logger.warning("live-chain: tick engine read failed", error=str(exc)[:160])

        # 5. overlay usable ticks into the frame
        session = today.isoformat()
        prev = self._prev_oi(sym, exp, session, now) if side_keys else None
        prev_oi = (prev or {}).get("oi") or {}
        index_of: dict[tuple[float, str], Any] = {
            (float(k), str(s)): i for i, k, s in zip(df.index[opt_mask], df.loc[opt_mask, "StrkPric"], df.loc[opt_mask, "OptnTp"],
                                                     strict=True)}
        side_info: dict[tuple[float, str], dict] = {}
        new_rows: list[dict] = []
        oi_basis: set[str] = set()
        trad_day = df.loc[opt_mask, "TradDt"].iloc[0] if opt_mask.any() else pd.Timestamp(today)
        for (k, side), key in side_keys.items():
            t, st = snap.get(key), states.get(key)
            state = tick_state(t, st, healthy, now, engine_state) if maps is not None else "no_master"
            info: dict[str, Any] = {"key": key, "state": state, "usable": state in LIVE_STATES,
                                    "error": (st or {}).get("error")}
            side_info[(k, side)] = info
            if not info["usable"] or t is None:
                continue
            c = by_strike[k][side]
            c_lot = c.lot or lot
            i = index_of.get((k, side))
            ltp, oi, ttq = _f(t.get("price")), _f(t.get("oi")), _f(t.get("ttq"))
            vals: dict[str, Any] = {}
            if ltp and ttq and ttq > 0:                                   # traded today: the last trade is the price
                vals["ClsPric"] = vals["SttlmPric"] = ltp
            if ttq is not None and c_lot:
                vals["TtlTradgVol"] = ttq / c_lot                         # shares → contracts
            if oi is not None:
                vals["OpnIntrst"] = oi
                base_prev = prev_oi.get((k, side))
                if base_prev is not None:
                    vals["ChngInOpnIntrst"] = oi - base_prev
                    oi_basis.add("stored_prev_session")
                elif i is not None and base == SOURCE_NSE and _f(df.at[i, "OpnIntrst"]) is not None \
                        and _f(df.at[i, "ChngInOpnIntrst"]) is not None:
                    vals["ChngInOpnIntrst"] = oi - (float(df.at[i, "OpnIntrst"]) - float(df.at[i, "ChngInOpnIntrst"]))
                    oi_basis.add("nse_prev_oi")
                else:
                    vals["ChngInOpnIntrst"] = float("nan")
            info.update(tick=t, lot=c_lot)
            if i is not None:
                for col, v in vals.items():
                    df.at[i, col] = v
            else:
                new_rows.append({"TckrSymb": sym, "FinInstrmTp": "IDO" if c.instrument == "OPTIDX" else "STO",
                                 "TradDt": trad_day, "ValDt": pd.NaT, "XpryDt": exp_ts, "UndrlygPric": frame_spot,
                                 "StrkPric": k, "OptnTp": side, "ClsPric": vals.get("ClsPric"), "SttlmPric": vals.get("SttlmPric"),
                                 "OpnIntrst": vals.get("OpnIntrst"), "ChngInOpnIntrst": vals.get("ChngInOpnIntrst"),
                                 "TtlTradgVol": vals.get("TtlTradgVol", 0.0), "NewBrdLotQty": c_lot})
        fut_live: dict[str, dict] = {}
        for f in fut_rows:
            key = fut_keys[f.expiry]
            t = snap.get(key)
            state = tick_state(t, states.get(key), healthy, now, engine_state)
            if state in LIVE_STATES and t is not None and _f(t.get("price")):
                fut_live[f.expiry] = {"key": key, "price": _f(t.get("price")), "age_s": round(max(0.0, now - t["ts"]), 1),
                                      "state": state, "instrument": f.instrument}
            else:
                fut_live.setdefault(f.expiry, {"key": key, "price": None, "age_s": None, "state": state,
                                               "instrument": f.instrument})
        n_live = sum(1 for v in side_info.values() if v["usable"])
        live_mode = bool(n_live or spot_live or any(v["price"] for v in fut_live.values()))
        if new_rows:
            df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
        if live_mode:
            # only a LIVE future enters the forward check: an EOD base's stored future (yesterday's close) would override a
            # live parity forward whenever the market has moved more than 0.5 % since
            df = df[~df["FinInstrmTp"].isin(oc.FUTURE_TYPES)].copy()
            if base == SOURCE_EOD:
                df["TradDt"] = pd.Timestamp(today)
            for fexp, fl in fut_live.items():
                if fl["price"]:
                    df = pd.concat([df, pd.DataFrame([{
                        "TckrSymb": sym, "FinInstrmTp": "IDF" if fl["instrument"] == "FUTIDX" else "STF",
                        "TradDt": pd.Timestamp(today), "ValDt": pd.NaT, "XpryDt": pd.Timestamp(fexp), "UndrlygPric": None,
                        "StrkPric": 0.0, "OptnTp": "XX", "ClsPric": fl["price"], "SttlmPric": fl["price"], "OpnIntrst": None,
                        "ChngInOpnIntrst": None, "TtlTradgVol": None, "NewBrdLotQty": lot}])], ignore_index=True)
            df["ValDt"] = pd.Timestamp(now_ist.replace(tzinfo=None))
            if spot_live:
                m = df["FinInstrmTp"].isin(oc.OPTION_TYPES) & (df["XpryDt"] == exp_ts)
                df.loc[m, "UndrlygPric"] = spot_live

        # 6. one IV method: the unchanged chain()
        out = oc.chain(df, sym, exp)
        if not out.get("found"):
            return {"symbol": sym, "found": False, "live": True, "as_of": _iso(now), "error": f"{sym}: empty chain",
                    "feed": {"base": base, "base_error": base_error, "master_error": master_error}}
        if out.get("expiry") != exp:
            note = (note + "; " if note else "") + f"the {base} frame has no {exp} rows: showing {out.get('expiry')}"

        # 7. label every side
        base_age = None
        if base == SOURCE_NSE and nse_epoch:
            base_age = round(max(0.0, now - nse_epoch), 1)
        elif base == SOURCE_EOD and eod_date:
            d = date.fromisoformat(str(eod_date)[:10])
            base_age = round(max(0.0, now - datetime(d.year, d.month, d.day, 15, 30, tzinfo=IST).timestamp()), 1)
        nse_book = self._nse_book(nse_payload, sym, exp, lot) if base == SOURCE_NSE else {}
        band_set = set(band)
        counts = {SOURCE_BREEZE: 0, SOURCE_NSE: 0, SOURCE_EOD: 0}
        for row in out["rows"]:
            k = float(row["strike"])
            row["band"] = k in band_set
            for side in SIDES:
                d_ = row[side.lower()]
                si = side_info.get((k, side))
                t = si.get("tick") if si else None
                if si and si["usable"] and t is not None:
                    traded = bool(_f(t.get("price")) and (_f(t.get("ttq")) or 0) > 0)
                    # 23 Nov review: an untraded strike's PRICE stays the base frame's (only OI / book / volume are live)
                    d_["price_source"] = SOURCE_BREEZE if traded else base
                    d_.update(source=SOURCE_BREEZE, age_s=round(max(0.0, now - float(t["ts"])), 1), tick_state=si["state"],
                              key=si["key"], ltp=t.get("price"), bid=t.get("bid"), ask=t.get("ask"),
                              bid_qty=t.get("bid_qty"), ask_qty=t.get("ask_qty"), ltt=_iso(t.get("ltt_epoch")),
                              prev_close=t.get("prev_close"))
                else:
                    nb = nse_book.get((k, side), {})
                    d_["price_source"] = base
                    d_.update(source=base, age_s=base_age, tick_state=si["state"] if si else "outside_band",
                              key=si["key"] if si else self._key_of(by_strike, sym, exp, k, side), ltp=None,
                              bid=nb.get("bid"), ask=nb.get("ask"), bid_qty=nb.get("bid_qty"), ask_qty=nb.get("ask_qty"),
                              ltt=None, prev_close=None)
                    if si and si.get("error"):
                        d_["error"] = si["error"]
                counts[d_["source"]] += 1

        # 8. the feed block
        opt_status = (lt_status or {}).get("options") or {}
        errs = {k: v["error"] for v in side_info.values() for k in [v["key"]] if v.get("error")}
        states_n = Counter(v["state"] for v in side_info.values())
        out.update(live=True, as_of=_iso(now), base=base)
        out["feed"] = {
            "as_of": _iso(now), "nse_as_of": nse_as_of, "eod_date": eod_date, "base": base, "base_error": base_error,
            "base_age_s": base_age, "counts": counts, "master_error": master_error,
            "band": band_info,
            "underlying": {"name": und, "price": spot_live if spot_live else frame_spot,
                           "source": SOURCE_BREEZE if spot_live else base, "tick_state": und_state,
                           "age_s": round(max(0.0, now - float(und_tick["ts"])), 1) if (und_tick and und_tick.get("ts")) else None},
            "futures": [{"expiry": e, **{k: v for k, v in fl.items() if k != "instrument"}} for e, fl in fut_live.items()],
            "expiry": {"chosen": out.get("expiry"), "source": exp_src, "requested": expiry_req, "note": note,
                       "master_expiries": m_exps},
            "subscription": {"engine": engine_state, "enabled": lt_mod.enabled(), "healthy": healthy,
                             "keys": len(keys), "live": n_live,
                             "subscribed": sum(1 for k in keys if (states.get(k) or {}).get("subscribed")),
                             "waiting_first_tick": states_n.get("waiting_first_tick", 0),
                             "over_cap": states_n.get("over_cap", 0), "states": dict(states_n),
                             "errors": dict(list(errs.items())[:10]), "cap": lt_mod.MAX_OPTIONS,
                             "engine_options": {k: opt_status.get(k) for k in ("subscribed", "requested", "over_cap",
                                                                              "collisions", "first_tick_mismatches")}},
            "oi_chg_basis": sorted(oi_basis) or None, "prev_oi_date": (prev or {}).get("date"),
            "lot": lot, "lot_source": "master" if lot_master else ("eod" if lot else None),
            "units": {"oi": "shares", "volume": "contracts (tick ttq in shares ÷ the contract's lot)",
                      "bid_qty": "shares", "ask_qty": "shares", "age_s": "seconds"},
            "rules": {"fresh_s": FRESH_S, "quiet_live_s": QUIET_LIVE_S, "recentre_strikes": RECENTRE_STRIKES,
                      "recentre_hold_s": RECENTRE_HOLD_S, "memo_s": MEMO_S},
        }
        return out

    @staticmethod
    def _key_of(by_strike: dict, sym: str, exp: str, k: float, side: str) -> Optional[str]:
        c = by_strike.get(k, {}).get(side)
        return lt_mod.contract_key(sym, exp, c.strike, side) if c is not None else None

    @staticmethod
    def _nse_book(payload: Optional[dict], sym: str, exp: str, lot: Optional[int]) -> dict[tuple[float, str], dict]:
        """NSE's own best bid / ask per strike side, through fo_iv.intraday's one v3 parser (its field fallbacks)."""
        if not payload:
            return {}
        try:
            from fo_iv.intraday import normalise_nse_v3
            snap = normalise_nse_v3(payload, datetime.now(IST), sym, date.fromisoformat(exp), lot)
        except Exception:  # noqa: BLE001 — bid / ask are optional on an NSE side
            return {}
        out: dict[tuple[float, str], dict] = {}
        for side, rows in (("CE", snap.calls), ("PE", snap.puts)):
            for r in rows:
                if r.get("strike") is not None:
                    out[(float(r["strike"]), side)] = {k: r.get(k) for k in ("bid", "ask", "bid_qty", "ask_qty")}
        return out
