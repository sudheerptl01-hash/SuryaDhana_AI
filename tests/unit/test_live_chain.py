"""The live option chain (services/data-service/live_chain.py, GET /live/option-chain/{symbol}), offline.

Base frame: NSE's option-chain v3 payload recorded for NIFTY 29-Sep-2026 (reports/nse_catalog/samples/
api_option_chain_v3_nifty.json; its stamp moved to 11:00 so the test clock is after it). Master: SYNTHETIC FONSE rows for
that expiry's strikes (test_live_ticks_options.synthetic, the real 64411 row with its fields replaced). Ticks: breeze_connect-
shaped F&O ticks through the real LiveTicks engine on the fake Breeze. No network, no service, nothing under data/.
"""
from __future__ import annotations

import ast
import copy
import csv
import io
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
_DS = _ROOT / "services" / "data-service"
for _p in (str(_ROOT), str(_DS), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_chain as lc  # noqa: E402
import live_ticks as lt  # noqa: E402
import option_chain as oc  # noqa: E402
import test_live_fixtures as fx  # noqa: E402
import test_live_ticks_options as tto  # noqa: E402
import test_live_ticks_tokens as tt  # noqa: E402
from fo_iv import black76 as b76  # noqa: E402
from providers.icici_breeze_provider import FoMasterIndex  # noqa: E402

ist = tto.ist
SAMPLE = _ROOT / "reports" / "nse_catalog" / "samples" / "api_option_chain_v3_nifty.json"
NSE_STAMP = "28-Sep-2026 11:00:00"
T0 = ist(2026, 9, 28, 11, 0, 30)                    # 30 s after the NSE stamp
EXP, NEXT = "2026-09-29", "2026-10-06"
LOT = 65


def nse_payload(expiry_label: str = "29-Sep-2026") -> dict:
    p = copy.deepcopy(json.loads(SAMPLE.read_text(encoding="utf-8")))
    p["records"]["timestamp"] = NSE_STAMP
    if expiry_label != "29-Sep-2026":                  # the same book re-dated (the expiry-selection test only)
        dmy = datetime.strptime(expiry_label, "%d-%b-%Y").replace(tzinfo=lc.IST).strftime("%d-%m-%Y")
        for d in p["records"]["data"]:
            d["expiryDates"] = expiry_label
            for s in ("CE", "PE"):
                if d.get(s):
                    d[s]["expiryDate"] = dmy
    return p


PAYLOAD = nse_payload()
STRIKES = sorted({float(d["strikePrice"]) for d in PAYLOAD["records"]["data"]})


def _txt(k: float) -> str:
    return lt.strike_text(k)


TOK: dict[tuple[float, str], str] = {}
_rows = [tto.FO_HEADER]
for i, k in enumerate(STRIKES):
    for j, r in enumerate(("CE", "PE")):
        TOK[(k, r)] = str(80000 + 2 * i + j)
        _rows.append(tto.synthetic(TOK[(k, r)], "NIFTY", "29-Sep-2026", _txt(k), r))
for i, k in enumerate((22700.0, 22750.0, 22800.0, 22850.0, 22900.0)):
    for j, r in enumerate(("CE", "PE")):
        _rows.append(tto.synthetic(str(90000 + 2 * i + j), "NIFTY", "06-Oct-2026", _txt(k), r))
FUT_TOKEN = "61000"
_rows.append(tto.synthetic(FUT_TOKEN, "NIFTY", "29-Sep-2026", "0", "XX", inst="FUTIDX"))
MASTER = "\n".join(_rows) + "\n"


def key(k: float, r: str, exp: str = EXP) -> str:
    return lt.contract_key("NIFTY", exp, _txt(k), r)


K_FUT = lt.contract_key("NIFTY", EXP, None, "FUT")


class World:
    """The real LiveTicks engine on the fake Breeze, the real FoMasterIndex on the synthetic master, fake NSE / EOD / stored-OI
    readers, one clock."""

    def __init__(self, now: float = T0, *, nse_ok: bool = True, eod: bool = True, master_ok: bool = True) -> None:
        self.clock = [now]
        self.index = FoMasterIndex(source=lambda: ("file:t", lambda: iter(list(csv.reader(io.StringIO(MASTER))))),
                                   today_fn=lambda: datetime.fromtimestamp(self.clock[0], lc.IST).date().isoformat())
        self.fake = tt.FakeBreeze()
        self.prov = tto.FoProvider(self.fake, self.index)
        # market_hours off: the engine's whole-socket silence rule (> 2 s in session) stays out of these chain tests.
        # Armed (ensure() keeps the state; OFF would make every quiet tick unvouched), but no worker thread: the test
        # drives _step() itself.
        self.lt = lt.LiveTicks(lambda: self.prov, clock=lambda: self.clock[0], enabled_fn=lambda: True,
                               market_hours_fn=lambda: False)
        self.lt._kick = lambda resync=True: self.lt._resync.set() if resync else None   # type: ignore[method-assign]
        self.nse_ok, self.eod_ok, self.master_ok = nse_ok, eod, master_ok
        self.nse_calls: list[tuple[str, str | None]] = []
        self.prev = {(22800.0, "CE"): 182633.0 * LOT}
        self.chain = lc.LiveChain(ticks_getter=lambda: self.lt, maps_fn=self._maps, nse_fn=self._nse, eod_fn=self._eod,
                                  prev_oi_fn=lambda s, e, sess: {"date": "2026-09-25", "oi": dict(self.prev)},
                                  clock=lambda: self.clock[0])

    def _maps(self, unds):
        if not self.master_ok:
            raise OSError("archive unreadable")
        return self.index.maps(unds)

    def _nse(self, sym, exp):
        self.nse_calls.append((sym, exp))
        if not self.nse_ok:
            raise RuntimeError("NSE is throttling us; retrying after 11:10")
        if exp not in (None, EXP, NEXT):
            raise LookupError(f"NSE does not list {exp}")
        label = "06-Oct-2026" if exp == NEXT else "29-Sep-2026"
        return {"payload": nse_payload(label), "expiries": [EXP, NEXT], "as_of": NSE_STAMP, "fetched_at": T0 - 25}

    def _eod(self, sym):
        if not self.eod_ok:
            return None
        df = oc.live_frame(PAYLOAD, "NIFTY", LOT, today=date(2026, 9, 25)).drop(columns=["ValDt"])
        fut = pd.DataFrame([{"TckrSymb": "NIFTY", "FinInstrmTp": "IDF", "TradDt": pd.Timestamp("2026-09-25"),
                             "XpryDt": pd.Timestamp(EXP), "UndrlygPric": None, "StrkPric": 0.0, "OptnTp": "XX",
                             "ClsPric": 23500.0, "SttlmPric": 23500.0, "OpnIntrst": None, "ChngInOpnIntrst": None,
                             "TtlTradgVol": None, "NewBrdLotQty": LOT}])           # a stored future 3 % away: stale
        return {"frame": pd.concat([df, fut], ignore_index=True), "date": "2026-09-25", "lot": LOT}

    def sync(self) -> None:
        self.lt._resync.set()
        assert self.lt._step() is True

    def spot(self, last: float, at: float | None = None) -> None:
        if at is not None:
            self.clock[0] = at
        self.fake.emit({**fx.TICKS["NIFTY 50"], "last": str(last)})

    def option(self, k: float, r: str, *, last: float, oi: int, ttq: int, at: float | None = None, **kw) -> None:
        if at is not None:
            self.clock[0] = at
        self.fake.emit(tto.opt_tick(TOK[(k, r)], last=str(last), expiry="29-Sep-2026", strike=_txt(k),
                                    right="Call" if r == "CE" else "Put", OI=str(oi), ttq=str(ttq), **kw))

    def future(self, last: float) -> None:
        self.fake.emit({**tto.opt_tick(FUT_TOKEN, last=str(last)), "product_type": "Futures", "expiry_date": "29-Sep-2026"})

    def at(self, t: float) -> None:
        self.clock[0] = t


def row(out: dict, k: float) -> dict:
    return next(r for r in out["rows"] if r["strike"] == k)


def warm(w: World) -> dict:
    """First call (ensures the underlying and the band; the engine has not connected yet), then the worker subscribes them."""
    first = w.chain.chain("NIFTY")
    w.sync()
    return first


# ── the overlay, units, payload ───────────────────────────────────────────────────────────────────────────────────────

def test_live_ticks_overlay_their_strike_sides_in_the_frame_units_and_one_iv_method():
    w = World()
    first = warm(w)
    assert first["base"] == "nse" and first["feed"]["counts"]["breeze_ws"] == 0
    assert row(first, 22800.0)["ce"]["tick_state"] == "feed_off"            # the engine was OFF until the worker ran
    assert w.lt.is_subscribed("NIFTY 50") and w.lt.is_subscribed(key(22800.0, "CE")) and w.lt.is_subscribed(K_FUT)
    w.at(T0 + 2)
    w.spot(22795.0)
    w.option(22800.0, "CE", last=90.0, oi=13_000_000, ttq=305_500_000, bPrice="89.9", sPrice="90.1", bQty="1300", sQty="650")
    w.future(22830.0)
    w.at(T0 + 3)
    out = w.chain.chain("NIFTY")
    ce, pe = row(out, 22800.0)["ce"], row(out, 22800.0)["pe"]
    assert ce["source"] == "breeze_ws" and ce["tick_state"] == "live" and ce["age_s"] == 1.0
    assert ce["price"] == 90.0 and ce["key"] == "NFO:NIFTY:2026-09-29:22800:CE"
    assert ce["oi"] == 13_000_000 and ce["oi_contracts"] == 200_000.0                 # shares; ÷ lot = contracts
    assert ce["volume"] == 4_700_000 and ce["volume"] != 305_500_000                   # ttq (shares) ÷ 65 = contracts
    assert ce["oi_chg"] == 13_000_000 - 182633 * LOT                                    # live OI − stored previous OI
    assert (ce["bid"], ce["ask"], ce["bid_qty"], ce["ask_qty"]) == (89.9, 90.1, 1300.0, 650.0)
    assert pe["source"] == "nse" and pe["tick_state"] == "waiting_first_tick" and pe["age_s"] == 33.0
    nse_pe = next(d["PE"] for d in PAYLOAD["records"]["data"] if d["strikePrice"] == 22800)
    assert pe["bid"] == nse_pe["buyPrice1"] and pe["ask"] == nse_pe["sellPrice1"]       # NSE's own book on NSE sides
    assert pe["price"] == nse_pe["lastPrice"] and pe["oi"] == nse_pe["openInterest"] * LOT
    far = row(out, 22000.0)
    assert far["band"] is False and far["ce"]["tick_state"] == "outside_band" and far["ce"]["source"] == "nse"
    assert out["spot"] == 22795.0 and out["future"] == 22830.0                         # the live spot and future in the frame
    assert out["model_version"] == b76.MODEL_VERSION and out["atm_iv"] is not None
    nse_only = oc.chain(oc.live_frame(PAYLOAD, "NIFTY", LOT, now=datetime(2026, 9, 28, 11, 0, 33, tzinfo=lc.IST).replace(tzinfo=None)), "NIFTY")
    assert row(out, 22800.0)["ce"]["iv"] != row(nse_only, 22800.0)["ce"]["iv"]         # recomputed, by chain() itself
    f = out["feed"]
    assert f["base"] == "nse" and f["nse_as_of"] == NSE_STAMP and f["oi_chg_basis"] == ["stored_prev_session"]
    assert f["counts"] == {"breeze_ws": 1, "nse": 2 * len(out["rows"]) - 1, "eod": 0}
    assert f["band"]["centre"] == 22800.0 and f["band"]["step"] == 50.0 and len(f["band"]["strikes"]) == 21
    assert f["band"]["strikes"][0] == 22300.0 and f["band"]["strikes"][-1] == 23300.0
    assert f["underlying"] == {"name": "NIFTY 50", "price": 22795.0, "source": "breeze_ws", "tick_state": "live", "age_s": 1.0}
    assert f["expiry"]["chosen"] == EXP and f["expiry"]["source"] == "master"
    assert f["subscription"]["keys"] == 43 and f["subscription"]["live"] == 1 and f["lot_source"] == "master"
    assert f["futures"][0]["price"] == 22830.0 and f["units"]["volume"].startswith("contracts")


def test_the_payload_shape_is_the_ui_contract():
    w = World()
    warm(w)
    w.at(T0 + 2)
    out = w.chain.chain("NIFTY")
    chain_keys = {"symbol", "found", "date", "expiry", "expiries", "days_to_expiry", "t_years", "t_days", "spot", "future",
                  "forward", "forward_source", "atm", "lot", "atm_iv", "pcr_oi", "max_pain", "units", "resistance", "support",
                  "rows", "model_version", "time_convention"}
    assert chain_keys | {"live", "as_of", "base", "feed"} <= set(out)
    side_keys = {"price", "traded", "oi", "oi_chg", "oi_contracts", "oi_chg_contracts", "volume", "iv", "source", "age_s",
                 "tick_state", "key", "bid", "ask", "bid_qty", "ask_qty", "ltp", "ltt", "prev_close"}
    for r in out["rows"]:
        assert {"strike", "band", "ce", "pe"} <= set(r)
        assert side_keys <= set(r["ce"]) and side_keys <= set(r["pe"])
        for s in ("ce", "pe"):
            assert r[s]["source"] in ("breeze_ws", "nse", "eod")
            assert r[s]["tick_state"] in lc.PAYLOAD_DOC["rows[].ce|pe.tick_state"].replace(" ", "").split("|")
    assert {"as_of", "nse_as_of", "eod_date", "base", "base_error", "base_age_s", "counts", "band", "underlying", "futures",
            "expiry", "subscription", "oi_chg_basis", "prev_oi_date", "lot", "lot_source", "units", "rules"} <= set(out["feed"])
    assert {"engine", "enabled", "healthy", "keys", "live", "subscribed", "waiting_first_tick", "over_cap", "states", "errors",
            "cap"} <= set(out["feed"]["subscription"])
    json.dumps(out)                                                          # serialisable as the route returns it


# ── only fresh or vouched-quiet ticks overlay ─────────────────────────────────────────────────────────────────────────

def test_only_a_fresh_or_vouched_quiet_tick_overlays_and_every_other_side_says_why():
    w = World()
    warm(w)
    now = T0 + 200
    k_quiet, k_stale, k_unvouched, k_fresh = (22800.0, "CE"), (22850.0, "CE"), (22750.0, "CE"), (22900.0, "CE")
    w.option(*k_stale, last=40.0, oi=1, ttq=65, at=now - 130)
    w.option(*k_quiet, last=91.0, oi=1, ttq=65, at=now - 60)
    w.option(*k_unvouched, last=120.0, oi=1, ttq=65, at=now - 60)
    w.lt._subscribed_at[key(*k_unvouched)] = now - 30                         # re-subscribed after its last tick
    w.option(*k_fresh, last=44.0, oi=1, ttq=65, at=now - 2)
    w.spot(22795.0, at=now - 1)                                               # the socket is healthy (heartbeat ≤ 10 s)
    w.at(now)
    out = w.chain.chain("NIFTY")
    got = {k: (row(out, k[0])["ce"]["source"], row(out, k[0])["ce"]["tick_state"]) for k in (k_quiet, k_stale, k_unvouched, k_fresh)}
    assert got == {k_quiet: ("breeze_ws", "quiet"), k_stale: ("nse", "stale"), k_unvouched: ("nse", "not_vouched"),
                   k_fresh: ("breeze_ws", "live")}
    assert row(out, 22800.0)["ce"]["price"] == 91.0 and row(out, 22850.0)["ce"]["price"] != 40.0
    # the feed goes quiet for 11 s: a quiet tick is no longer vouched for by a healthy socket
    w.at(now + 11)
    out2 = w.chain.chain("NIFTY")
    assert (row(out2, 22800.0)["ce"]["source"], row(out2, 22800.0)["ce"]["tick_state"]) == ("nse", "feed_unhealthy")
    # yesterday's tick is never today's price
    w.option(22950.0, "CE", last=30.0, oi=1, ttq=65, at=ist(2026, 9, 27, 15, 29))
    w.at(T0 + 400)
    w.spot(22795.0)
    out3 = w.chain.chain("NIFTY")
    assert row(out3, 22950.0)["ce"]["tick_state"] == "other_session" and row(out3, 22950.0)["ce"]["source"] == "nse"


def test_an_untraded_strike_tick_overlays_the_book_and_oi_but_never_a_price():
    w = World()
    warm(w)
    w.at(T0 + 2)
    w.spot(22795.0)
    w.option(22800.0, "PE", last=0, oi=12_480_000, ttq=0, bPrice="67.5", sPrice="68.0")
    w.at(T0 + 3)
    pe = row(w.chain.chain("NIFTY"), 22800.0)["pe"]
    nse_pe = next(d["PE"] for d in PAYLOAD["records"]["data"] if d["strikePrice"] == 22800)
    assert pe["source"] == "breeze_ws" and pe["ltp"] is None and pe["bid"] == 67.5 and pe["oi"] == 12_480_000
    assert pe["volume"] == 0 and pe["traded"] is False and pe["price"] == nse_pe["lastPrice"]
    assert pe["oi_chg"] == 12_480_000 - (nse_pe["openInterest"] - nse_pe["changeinOpenInterest"]) * LOT   # NSE's prev OI


# ── hysteresis ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_band_recentres_only_after_spot_stays_more_than_1_5_strikes_away_for_30_s():
    w = World()
    warm(w)

    def at(t: float, spot: float) -> dict:
        w.at(t)
        w.spot(spot)
        return w.chain.chain("NIFTY")["feed"]["band"]

    assert at(T0 + 2, 22795.0)["centre"] == 22800.0
    b = at(T0 + 4, 22880.0)                                                   # 1.6 steps away: pending, not moved
    assert b["centre"] == 22800.0 and b["pending_s"] == 0.0
    assert at(T0 + 22, 22880.0)["centre"] == 22800.0                         # 18 s: still not
    b = at(T0 + 25, 22850.0)                                                  # back within 1.5 steps: the clock resets
    assert b["centre"] == 22800.0 and b["pending_s"] is None
    assert at(T0 + 26, 22880.0)["pending_s"] == 0.0
    assert at(T0 + 55, 22880.0)["centre"] == 22800.0                         # 29 s
    b = at(T0 + 57, 22880.0)                                                  # 31 s: recentred on the ATM strike
    assert b["centre"] == 22900.0 and b["strikes"][0] == 22400.0 and b["strikes"][-1] == 23400.0
    assert key(23400.0, "CE") in w.lt._requested_opts and key(23400.0, "PE") in w.lt._requested_opts


def test_strike_step_and_band_helpers():
    strikes = [22000.0, 22100.0, 22200.0, 22250.0, 22300.0, 22350.0, 22400.0, 22450.0, 22500.0, 22600.0, 22800.0]
    assert lc.strike_step(strikes, 22330.0) == 50.0                         # the commonest gap near the money
    assert lc.band_of(strikes, 22300.0, 2) == [22200.0, 22250.0, 22300.0, 22350.0, 22400.0]
    assert lc.band_of(strikes, 22000.0, 2) == [22000.0, 22100.0, 22200.0]   # clipped at the edge
    assert lc.nearest(strikes, 22325.0) == 22300.0


# ── fallbacks ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_nse_down_falls_back_to_the_stored_bhavcopy_and_a_live_overlay_never_trusts_its_future():
    w = World(nse_ok=False)
    out = w.chain.chain("NIFTY")
    assert out["base"] == "eod" and out["feed"]["base_error"].startswith("NSE is throttling us")
    assert {row(out, 22800.0)[s]["source"] for s in ("ce", "pe")} == {"eod"}
    assert out["feed"]["eod_date"] == "2026-09-25" and out["feed"]["base_age_s"] == round(T0 - ist(2026, 9, 25, 15, 30), 1)
    # NEGATIVE CONTROL: the pure EOD chain uses the stored future (yesterday's 23500): the forward jumps 3 %
    assert out["future"] == 23500.0 and out["forward_source"] == "future"
    w.sync()
    w.at(T0 + 2)
    w.spot(22795.0)
    w.option(22800.0, "CE", last=90.0, oi=13_000_000, ttq=305_500_000)
    w.at(T0 + 3)
    live = w.chain.chain("NIFTY")
    assert live["base"] == "eod" and row(live, 22800.0)["ce"]["source"] == "breeze_ws"
    assert live["future"] is None and live["forward_source"] == "put-call parity"   # the stale future is out of the forward
    assert live["date"] == "2026-09-28" and live["feed"]["counts"]["eod"] == 2 * len(live["rows"]) - 1


def test_nothing_to_serve_is_not_found_and_a_missing_master_still_serves_nse_unlabelled_live():
    w = World(nse_ok=False, eod=False)
    out = w.chain.chain("NIFTY")
    assert out["found"] is False and "no stored F&O bhavcopy" in out["error"]
    w2 = World(master_ok=False)
    out2 = w2.chain.chain("NIFTY")
    assert out2["found"] and out2["base"] == "nse" and out2["feed"]["master_error"] == "archive unreadable"
    assert out2["feed"]["expiry"]["source"] == "nse" and out2["expiry"] == EXP and w2.nse_calls == [("NIFTY", None)]
    assert out2["feed"]["subscription"]["keys"] == 0 and {r["ce"]["tick_state"] for r in out2["rows"]} == {"outside_band"}


# ── expiry ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_near_expiry_is_the_masters_first_whose_1530_has_not_passed():
    assert lc.near_expiry([NEXT, EXP], ist(2026, 9, 29, 15, 29, 59)) == EXP
    assert lc.near_expiry([NEXT, EXP], ist(2026, 9, 29, 15, 30, 0)) == NEXT
    w = World(now=ist(2026, 9, 29, 15, 29))
    assert w.chain.chain("NIFTY")["expiry"] == EXP and w.nse_calls[-1] == ("NIFTY", EXP)
    w.at(ist(2026, 9, 29, 15, 31))
    out = w.chain.chain("NIFTY")
    assert out["expiry"] == NEXT and w.nse_calls[-1] == ("NIFTY", NEXT) and out["feed"]["expiry"]["source"] == "master"
    w.at(ist(2026, 9, 29, 15, 33))
    asked = w.chain.chain("NIFTY", EXP)                                       # an expired expiry asked for by name
    assert asked["expiry"] == NEXT and "is not a live expiry" in asked["feed"]["expiry"]["note"]


# ── memo ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_chain_is_memoised_for_one_second_per_symbol_expiry_and_width():
    w = World()
    a = w.chain.chain("NIFTY")
    assert w.chain.chain("nifty") is a and w.chain.computes == 1
    w.at(T0 + 0.9)
    assert w.chain.chain("NIFTY") is a and w.chain.computes == 1
    assert w.chain.chain("NIFTY", width=5) is not a and w.chain.computes == 2   # another width is another chain
    w.at(T0 + 1.0)
    assert w.chain.chain("NIFTY") is not a and w.chain.computes == 3


# ── gates: no Yahoo, no Breeze REST, the route ────────────────────────────────────────────────────────────────────────

def test_live_chain_has_no_yahoo_and_no_breeze_rest_call():
    tree = ast.parse((_DS / "live_chain.py").read_text(encoding="utf-8"))
    idents = {n.id if isinstance(n, ast.Name) else n.attr for n in ast.walk(tree) if isinstance(n, (ast.Name, ast.Attribute))}
    docs = {id(b.body[0].value) for b in ast.walk(tree) if isinstance(b, (ast.Module, ast.FunctionDef, ast.ClassDef))
            and b.body and isinstance(b.body[0], ast.Expr) and isinstance(b.body[0].value, ast.Constant)}
    texts = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]
    assert not [t for t in texts if re.search(r"yahoo|yfinance", t, re.I)]
    assert not ({"yf", "yfinance"} & idents)
    rest = {"get_quotes", "get_option_chain_quotes", "get_historical_data", "get_historical_data_v2"}
    assert not (rest & {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)})


ROUTE_MARK = "LIVECHAIN "
ROUTE_DRIVER = r"""
import importlib.util, json, os, socket, sys
ROOT = __ROOT__
_orig = socket.socket.connect
def _guard(self, addr):
    if self.family == getattr(socket, "AF_UNIX", None):
        return _orig(self, addr)
    raise OSError("live-chain: network refused")
socket.socket.connect = _guard
sys.path[:0] = [ROOT, os.path.join(ROOT, "services", "data-service"), os.path.join(ROOT, "tests", "unit")]
spec = importlib.util.spec_from_file_location("ds_main_livechain", os.path.join(ROOT, "services", "data-service", "main.py"))
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
import test_live_chain as t
w = t.World()
mod._live_chain = w.chain
gone = t.World(nse_ok=False, eod=False)
from fastapi.testclient import TestClient
c = TestClient(mod.app, raise_server_exceptions=False)
h = {"host": "127.0.0.1:8001"}
res = {}
r = c.get("/live/option-chain/NIFTY", params={"width": 5}, headers=h)
body = r.json()
res["ok"] = [r.status_code, sorted(body), len(body.get("feed", {}).get("band", {}).get("strikes", []))]
for name, path, params in (("bad_symbol", "/live/option-chain/NIF;TY", {}), ("bad_expiry", "/live/option-chain/NIFTY", {"expiry": "29-Sep-2026"}),
                           ("wide", "/live/option-chain/NIFTY", {"width": 21}), ("narrow", "/live/option-chain/NIFTY", {"width": 0})):
    res[name] = c.get(path, params=params, headers=h).status_code
mod._live_chain = gone.chain
r = c.get("/live/option-chain/NIFTY", headers=h)
res["gone"] = [r.status_code, r.json().get("detail", "")[:80]]
print(__MARK__ + json.dumps(res), flush=True)
"""


def test_the_route_answers_the_contract_and_validates_its_parameters(tmp_path: Path):
    code = ROUTE_DRIVER.replace("__ROOT__", repr(str(_ROOT))).replace("__MARK__", repr(ROUTE_MARK))
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "LIVE_TICKS": "0", "TICK_PERSIST": "0",
           "TICKS_DIR": str(tmp_path / "ticks"), "BREEZE_BUDGET_DB": str(tmp_path / "breeze_budget.sqlite")}
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=240, env=env, cwd=str(tmp_path))
    line = next((ln for ln in reversed(p.stdout.splitlines()) if ln.startswith(ROUTE_MARK)), None)
    assert line is not None, f"route harness: no result (exit {p.returncode}); stderr: {p.stderr[-2000:]}"
    res = json.loads(line[len(ROUTE_MARK):])
    status, keys, band = res["ok"]
    assert status == 200 and {"rows", "feed", "base", "live", "expiry", "atm_iv"} <= set(keys) and band == 11
    assert (res["bad_symbol"], res["bad_expiry"], res["wide"], res["narrow"]) == (422, 422, 422, 422)
    assert res["gone"][0] == 404 and "no option chain" in res["gone"][1]


def test_every_side_names_where_its_price_comes_from():
    """23 Nov review: an untraded strike in the band said source=breeze_ws while its price was NSE's / the bhavcopy's."""
    import live_chain as lc
    src = Path(lc.__file__).read_text()
    assert 'd_["price_source"] = SOURCE_BREEZE if traded else base' in src and 'd_["price_source"] = base' in src
    assert "rows[].ce|pe.price_source" in lc.PAYLOAD_DOC
