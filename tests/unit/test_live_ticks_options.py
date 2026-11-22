"""F&O contracts on the live-ticks engine (22 Nov 2026), offline.

Fixtures: a few rows of ICICI's FONSEScripMaster.txt and one row of NSEScripMaster.txt, copied verbatim from the cached
SecurityMaster.zip of 22 Nov 2026 (rows marked SYNTHETIC are built from the real 64411 row and say what they stand for), the
recorded 5 Nov option tick (test_live_fixtures.TICKS['NIFTY 24400 CE 09-Nov'], token 39999) and the fake Breeze of
test_live_ticks_tokens. No network, no service, nothing under data/.
"""
from __future__ import annotations

import csv
import io
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "services/data-service"), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_ticks as lt  # noqa: E402
import test_live_fixtures as fx  # noqa: E402
import test_live_ticks_tokens as tt  # noqa: E402
import providers.icici_breeze_provider as provmod  # noqa: E402
from providers.icici_breeze_provider import FoMasterIndex, parse_fo_master_tokens, parse_nse_master_tokens  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))


def ist(y: int, mo: int, d: int, h: int = 11, mi: int = 0, s: int = 0) -> float:
    return datetime(y, mo, d, h, mi, s, tzinfo=IST).timestamp()


# ── the master fixture (verbatim rows of the 22 Nov 2026 archive) ─────────────────────────────────────────────────────────
FO_HEADER = ('"Token","InstrumentName","ShortName","Series","ExpiryDate","StrikePrice","OptionType","CALevel","PermittedToTrade",'
             '"IssueCapital","WarningQty","FreezeQty","CreditRating","NormalMarketStatus","OddLotMarketStatus","SpotMarketStatus",'
             '"AuctionMarketStatus","NormalMarketEligibility","OddLotMarketEligibility","SpotMarketEligibility",'
             '"AuctionMarketEligibility","IssueRate","IssueStartDate","InterestPaymentDate","IssueMaturityDate","MarginPercentage",'
             '"MinimumLotQty","LotSize","TickSize","CompanyName","ListingDate","ExpulsionDate","ReAdmissionDate","RecordDate",'
             '"LowPriceRange","HighPriceRange","SecurityExpiryDate","NoDeliveryStartDate","NoDeliveryEndDate","MF","AON",'
             '"ParticipantInMarketIndex","BookClsStartDate","BookClsEndDate","ExcerciseStartDate","ExcerciseEndDate","OldToken",'
             '"AssetInstrument","AssetName","AssetToken","IntrinsicValue","ExtrinsicValue","ExcerciseStyle","EGM","AGM","Interest",'
             '"Bonus","Rights","Dividends","ExAllowed","ExRejectionAllowed","PlAllowed","IsThisAsset","IsCorpAdjusted",'
             '"LocalUpdateDatetime","DeleteFlag","Remarks","BasePrice","ExchangeCode"')
_TAIL = ',"","","","","","",0,"","",0,0,0,"","","","","","","","NFO","","","","","","","",'
R_64411 = ('"64411","OPTIDX","NIFTY","OPTION","23-Nov-2026","24350","CE",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",27040,0,65,5,'
           '"NIFTY 50","","","","",516.55,1833.15,"","","","1-Mon"' + _TAIL + '2551430,"NIFTY 50"')
R_64412 = ('"64412","OPTIDX","NIFTY","OPTION","23-Nov-2026","24350","PE",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",1452100,0,65,5,'
           '"NIFTY 50","","","","",0.05,23.7,"","","","1-Mon"' + _TAIL + '2551430,"NIFTY 50"')
R_61471 = ('"61471","FUTIDX","NIFTY","FUTURE","23-Nov-2026","0","XX",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",8745165,0,65,10,'
           '"NIFTY 50","","","","",22979.7,28086.3,"","","","1-Mon"' + _TAIL + '2553300,"NIFTY 50"')
R_35000 = ('"35000","OPTIDX","CNXBAN","OPTION","29-Dec-2026","69400","CE",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",0,0,30,5,'
           '"NIFTY BANK","","","","",0.05,368.3,"","","","2-Mon"' + _TAIL + '5463305,"NIFTY BANK"')
R_123654 = ('"123654","OPTSTK","PIDIND","OPTION","23-Nov-2026","1800","CE",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",1000,0,500,5,'
            '"PIDILITE INDUSTRIES LTD","","","","",0.05,20.05,"","","","1-Mon"' + _TAIL + '158050,"PIDILITIND"')
R_35242 = ('"35242","OPTSTK","BANBAN","OPTION","29-Dec-2026","207.5","CE",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",0,0,3600,1,'
           '"BANDHAN BANK LIMITED","","","","",0.01,22.77,"","","","2-Mon"' + _TAIL + '15580,"BANDHANBNK"')
R_39999_NOW = ('"39999","OPTSTK","BANBAR","OPTION","29-Dec-2026","380","CE",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",0,0,2925,1,'
               '"BANK OF BARODA","","","","",0.01,20.1,"","","","2-Mon"' + _TAIL + '27500,"BANKBARODA"')
R_47633 = ('"47633","OPTIDX","NIFTY","OPTION","01-Dec-2026","24350","CE",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",2470,0,65,5,'
           '"NIFTY 50","","","","",579.5,1834.4,"","","","1-Wek"' + _TAIL + '2551430,"NIFTY 50"')
R_61473_NIFNEX = ('"61473","FUTIDX","NIFNEX","FUTURE","23-Nov-2026","0","XX",0,0,0,0,0,"",0,0,0,0,"","","","",0,"","","",15000,0,25,20,'
                  '"NIFTY NEXT 50","","","","",65456.6,80002.2,"","","","1-Mon"' + _TAIL + '7272940,"NIFTY NEXT 50"')
# NSEScripMaster.txt: the cash row that shares token 123654 with PIDILITIND 23-Nov 1800 CE
R_NSE_SURYAPHARM = ('"123654","SURPHA","BE","SURYA PHARMACEUTICAL LIMITED",0.01,1,"","",0,1,"INE249G01020",0,0,35.68,0.55,"","","",0,0,0,'
                    '0.2,0.1,"",0,"","","",0,"","","","","","","","","","","","","","","","","","","","","","","0",0,0,0,"","","","","",'
                    '"SURYAPHARM"')


def synthetic(token: str, short: str, expiry: str, strike: str, right: str, exch: str = "NIFTY 50", inst: str = "OPTIDX") -> str:
    """SYNTHETIC: the real 64411 row with its Token / ShortName / ExpiryDate / StrikePrice / OptionType / ExchangeCode replaced."""
    cols = next(csv.reader(io.StringIO(R_64411)))
    cols[0], cols[1], cols[2], cols[4], cols[5], cols[6], cols[-1] = token, inst, short, expiry, strike, right, exch
    buf = io.StringIO()
    csv.writer(buf, quoting=csv.QUOTE_NONNUMERIC).writerow(cols)
    return buf.getvalue().strip()


# SYNTHETIC: token 39999's meaning on 5 Nov 2026, from the SDK's own annotation of the recorded tick (NIFTY 09-Nov 24400 CE)
R_39999_OLD = synthetic("39999", "NIFTY", "09-Nov-2026", "24400", "CE")
# SYNTHETIC: an expired contract still listed by a stale master (17-Nov-2026 expiry)
R_EXPIRED = synthetic("99001", "NIFTY", "17-Nov-2026", "24350", "CE")
LADDER = [str(k) for k in range(24000, 24750, 50) if k != 24350]   # SYNTHETIC: 14 NIFTY 23-Nov strikes (24350 is real)
R_LADDER = [synthetic(str(70000 + 2 * i + j), "NIFTY", "23-Nov-2026", k, r) for i, k in enumerate(LADDER)
            for j, r in enumerate(("CE", "PE"))]

MASTER_NOW = "\n".join([FO_HEADER, R_64411, R_64412, R_61471, R_35000, R_123654, R_35242, R_39999_NOW, R_47633,
                        R_61473_NIFNEX, R_EXPIRED, *R_LADDER]) + "\n"
MASTER_OLD = "\n".join([FO_HEADER, R_39999_OLD, R_64411, R_61471]) + "\n"
CASH = fx.MASTER + R_NSE_SURYAPHARM + "\n"
CASH_EQ, CASH_IDX = parse_nse_master_tokens(csv.reader(io.StringIO(CASH)))

K_64411 = "NFO:NIFTY:2026-11-23:24350:CE"
K_64412 = "NFO:NIFTY:2026-11-23:24350:PE"
K_FUT = "NFO:NIFTY:2026-11-23:FUT"
K_BANK = "NFO:BANKNIFTY:2026-12-29:69400:CE"
K_PIDI = "NFO:PIDILITIND:2026-11-23:1800:CE"
K_BAND = "NFO:BANDHANBNK:2026-12-29:207.5:CE"
K_BOB = "NFO:BANKBARODA:2026-12-29:380:CE"
K_OLD = "NFO:NIFTY:2026-11-09:24400:CE"
K_EXPIRED = "NFO:NIFTY:2026-11-17:24350:CE"


def rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_the_fixture_rows_are_the_masters_shape():
    hdr = rows(FO_HEADER)[0]
    assert len(hdr) == 69 and hdr[-1] == "ExchangeCode"
    assert all(len(r) == len(hdr) for r in rows(MASTER_NOW) + rows(MASTER_OLD)), "a fixture row lost or gained a column"


def make_index(text: str = MASTER_NOW, day: str = "2026-11-22", sid: str = "file:v1") -> tuple[FoMasterIndex, dict]:
    state = {"text": text, "day": day, "sid": sid}
    idx = FoMasterIndex(source=lambda: (state["sid"], lambda: iter(rows(state["text"]))), today_fn=lambda: state["day"])
    return idx, state


class FoProvider(tt.FakeProvider):
    """test_live_ticks_tokens.FakeProvider + the F&O master (the REAL FoMasterIndex over the fixture rows) + the cash row of
    SURYAPHARM."""

    def __init__(self, breeze: tt.FakeBreeze, index: FoMasterIndex) -> None:
        super().__init__(breeze)
        self.index = index

    def fo_token_maps(self, underlyings):
        return self.index.maps(underlyings)

    def _resolve_ws_token(self, name: str) -> str:
        if name.upper() in CASH_EQ:
            return "4.1!" + CASH_EQ[name.upper()]
        return super()._resolve_ws_token(name)


def engine(clock: list[float], index: FoMasterIndex, breeze: tt.FakeBreeze | None = None, holdings=(), pins=()):
    fake = breeze or tt.FakeBreeze()
    prov = FoProvider(fake, index)
    obj = lt.LiveTicks(lambda: prov, prev_close_fn=lambda syms: {}, holdings_fn=lambda: list(holdings), clock=lambda: clock[0],
                       enabled_fn=lambda: False, market_hours_fn=lambda: True, pins_fn=lambda: list(pins))
    return obj, prov, fake


def sync(obj) -> None:
    obj._resync.set()
    assert obj._step() is True


def opt_tick(token: str, *, last: str = "142.7", expiry: str | None = None, strike: str | None = None, right: str | None = None,
             **kw) -> dict:
    """An F&O tick shaped like breeze_connect's (the recorded 5 Nov tick's fields), on another token."""
    t = {**fx.TICKS["NIFTY 24400 CE 09-Nov"], "symbol": f"4.1!{token}", "last": last}
    for k, v in (("expiry_date", expiry), ("strike_price", strike), ("right", right)):
        if v is None:
            t.pop(k, None)
        else:
            t[k] = v
    if expiry is None and strike is None and right is None:
        t.pop("product_type", None)
    t.update(kw)
    return t


# ── keys ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_contract_keys_round_trip_and_never_normalise():
    for key in (K_64411, K_FUT, K_BAND, "NFO:M&M:2026-11-23:3000:PE", "NFO:BAJAJ-AUTO:2026-11-23:9000:CE"):
        assert lt.canonical(key) == key and lt.canonical(key.lower()) == key and lt.canonical(f"  {key} ") == key
        p = lt.contract_parts(key)
        assert p is not None and lt.contract_key(p.symbol, p.expiry, p.strike, p.right) == key
        assert lt.is_contract(key) and not lt.is_index(key)
    assert lt.contract_parts(K_BAND) == ("BANDHANBNK", "2026-12-29", "207.5", "CE")
    assert lt.contract_parts(K_FUT) == ("NIFTY", "2026-11-23", None, "FUT")
    assert lt.strike_text(24350.0) == "24350" and lt.strike_text(207.5) == "207.5" and lt.strike_text("24350") == "24350"
    # negative controls: never an index, never "fixed up"
    for bad in ("NFO:NIFTY:23-Nov-2026:24350:CE", "NFO:NIFTY:2026-02-30:24350:CE", "NFO:NIFTY:2026-11-23:24350:XX",
                "NFO:NIFTY 50:2026-11-23:24350:CE", "NFO:NIFTY:2026-11-23:FUT:CE", "NFO:NIFTY:2026-11-23", "NFO:"):
        assert lt.canonical(bad) is None and not lt.is_contract(bad), bad
    assert lt.canonical("NFO:NIFTY:2026-11-23:24350.0:CE") == "NFO:NIFTY:2026-11-23:24350.0:CE"   # well-formed; the master refuses
    # the cash and index paths are unchanged
    assert lt.canonical("reliance.ns") == "RELIANCE" and lt.canonical("nifty") == "NIFTY 50" and lt.is_index("NIFTY 50")
    assert lt.canonical("A:B") is None


# ── the master ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_fo_master_maps_tokens_by_nse_symbol_with_the_index_codes_inverted():
    got, skipped = parse_fo_master_tokens(rows(MASTER_NOW))
    by_key = {(c.symbol, c.expiry, c.strike, c.right): c for c in got.values()}
    assert by_key[("NIFTY", "2026-11-23", "24350", "CE")].token == "64411"
    assert by_key[("NIFTY", "2026-11-23", None, "FUT")].token == "61471"
    assert by_key[("BANKNIFTY", "2026-12-29", "69400", "CE")].token == "35000"        # CNXBAN → BANKNIFTY
    assert by_key[("BANDHANBNK", "2026-12-29", "207.5", "CE")].ws_token == "4.1!35242"   # the decimal strike as written
    assert by_key[("PIDILITIND", "2026-11-23", "1800", "CE")].lot == 500               # stock rows: ExchangeCode
    assert by_key[("NIFTY", "2026-11-23", "24350", "CE")].lot == 65
    assert not any(c.symbol in ("CNXBAN", "NIFTY BANK", "NIFNEX", "NIFTY NEXT 50") for c in got.values())
    assert skipped == {"index code NIFNEX not in BREEZE_INDEX_CODES": 1}               # never guessed, counted
    from fo_iv.intraday import BREEZE_INDEX_CODES
    assert provmod.breeze_index_symbols() == {v: k for k, v in BREEZE_INDEX_CODES.items()}   # derived, not retyped
    only, _ = parse_fo_master_tokens(rows(MASTER_NOW), ["BANKNIFTY"])
    assert {c.symbol for c in only.values()} == {"BANKNIFTY"}
    none, why = parse_fo_master_tokens(rows(MASTER_NOW)[1:])                            # no header: no column guessing
    assert none == {} and why == {"no header row": 1}


def test_fo_index_parses_per_underlying_and_rebuilds_on_a_new_day_or_archive():
    idx, state = make_index()
    m1 = idx.maps(["NIFTY"])
    assert idx.parses == 1 and m1.get("NIFTY", "2026-11-23", "24350", "CE").token == "64411"
    assert idx.maps(["NIFTY"]) is m1 and idx.parses == 1                       # same day, same archive: no re-parse
    m2 = idx.maps(["NIFTY", "BANKNIFTY"])
    assert idx.parses == 2 and m2.version == m1.version and m2.get("BANKNIFTY", "2026-12-29", "69400", "CE")   # only the new one
    assert m2.expiries("NIFTY") == ["2026-11-17", "2026-11-23", "2026-12-01"]  # as the master lists them
    state["day"] = "2026-11-23"
    m3 = idx.maps(["NIFTY"])
    assert idx.parses == 3 and m3.version != m1.version and m3.symbols == frozenset({"NIFTY"})
    state["sid"] = "file:v2"
    assert idx.maps(["NIFTY"]).version == ("2026-11-23", "file:v2") and idx.parses == 4


def test_provider_fo_token_maps_reads_the_cached_archive_and_its_mtime_is_the_version(monkeypatch, tmp_path):
    import shared.breeze_cache as bcache
    monkeypatch.setattr(provmod, "_FO_INDEX", None)
    monkeypatch.delitem(sys.modules, "breeze_connect.breeze_connect", raising=False)
    zp = tmp_path / "SecurityMaster.zip"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("FONSEScripMaster.txt", MASTER_OLD)
    monkeypatch.setattr(bcache, "CACHE", zp)
    prov = provmod.ICICIBreezeProvider("k", "s", "t")
    old = prov.fo_token_maps(["NIFTY"])
    assert old.get("NIFTY", "2026-11-09", "24400", "CE").token == "39999" and old.version[1].startswith("file:")
    with zipfile.ZipFile(zp, "w") as z:                                        # the daily refresh rewrites the archive
        z.writestr("FONSEScripMaster.txt", MASTER_NOW)
    import os
    os.utime(zp, ns=(zp.stat().st_atime_ns, zp.stat().st_mtime_ns + 10**9))
    new = prov.fo_token_maps(["NIFTY", "BANKBARODA"])
    assert new.version != old.version and new.get("BANKBARODA", "2026-12-29", "380", "CE").token == "39999"
    assert new.get("NIFTY", "2026-11-09", "24400", "CE") is None
    assert "breeze_connect.breeze_connect" not in sys.modules                 # never imports the SDK (its import downloads)


# ── resolution through the engine ─────────────────────────────────────────────────────────────────────────────────────

def test_engine_resolves_contracts_from_the_master_after_the_index_pin_and_refuses_a_respelt_strike():
    clock = [ist(2026, 11, 20)]
    idx, _ = make_index()
    obj, prov, fake = engine(clock, idx)
    obj.ensure(["NIFTY 50", K_64411, K_BANK, K_BAND, "NFO:NIFTY:2026-11-23:24350.0:CE", "NFO:NIFTY:23-Nov-2026:24350:CE"])
    sync(obj)
    toks = fake.subscribed_tokens()
    assert {"4.1!NIFTY 50", "4.1!64411", "4.1!35000", "4.1!35242"} <= set(toks)
    assert toks.index("4.1!NIFTY 50") < toks.index("4.1!64411")                 # the underlying joins before its chain
    assert obj.is_subscribed(K_BANK) and obj.is_subscribed(K_BAND)
    st = obj.status()["options"]
    err = st["sub_errors"]["NFO:NIFTY:2026-11-23:24350.0:CE"]
    assert "not in the F&O security master" in err and "'24350'" in err      # refused, with the master's spelling
    assert st["requested"] == 4                                               # the DD-Mon key never entered the ledger
    assert obj.status()["subscribed"] == 1 and st["subscribed"] == 3           # the equity count is unchanged by contracts
    assert not any("False" in t for t in toks)                               # never the SDK's silent '4.1!False'


def test_a_provider_without_an_fo_master_refuses_contracts_and_keeps_equities():
    clock = [ist(2026, 11, 20)]
    fake = tt.FakeBreeze()
    prov = tt.FakeProvider(fake)                                              # no fo_token_maps
    obj = lt.LiveTicks(lambda: prov, clock=lambda: clock[0], enabled_fn=lambda: False, market_hours_fn=lambda: True)
    obj.ensure(["TATASTEEL", K_64411])
    sync(obj)
    assert obj.is_subscribed("TATASTEEL") and not obj.is_subscribed(K_64411)
    assert "no F&O security master" in obj.status()["options"]["sub_errors"][K_64411]


# ── collisions ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_contract_on_a_subscribed_equitys_token_is_refused_and_the_negative_control_subscribes():
    assert CASH_EQ["SURYAPHARM"] == "123654"                                  # the real collision of the 22 Nov masters
    clock = [ist(2026, 11, 20)]
    idx, _ = make_index()
    obj, prov, fake = engine(clock, idx)
    obj.ensure(["SURYAPHARM", K_PIDI])
    sync(obj)
    assert obj.is_subscribed("SURYAPHARM") and not obj.is_subscribed(K_PIDI)
    st = obj.status()["options"]
    assert st["collisions"] == 1 and "SURYAPHARM's cash-market token" in st["sub_errors"][K_PIDI]
    assert fake.subscribed_tokens().count("4.1!123654") == 1
    # NEGATIVE CONTROL: no equity on the token → the contract subscribes on it
    obj2, _, fake2 = engine(clock, make_index()[0])
    obj2.ensure([K_PIDI])
    sync(obj2)
    assert obj2.is_subscribed(K_PIDI) and "4.1!123654" in fake2.subscribed_tokens()
    assert obj2.status()["options"]["collisions"] == 0


def test_an_equity_takes_its_token_back_from_a_contract_and_ticks_of_the_other_shape_are_never_stored():
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    obj.ensure([K_PIDI])
    sync(obj)
    assert obj.is_subscribed(K_PIDI)
    clock[0] += 1
    obj.ensure(["SURYAPHARM"])
    sync(obj)
    assert obj.is_subscribed("SURYAPHARM") and not obj.is_subscribed(K_PIDI)
    assert "now SURYAPHARM's cash-market token" in obj.status()["options"]["sub_errors"][K_PIDI]
    assert not any(c[0] == "unsubscribe" and "4.1!123654" in c[1] for c in fake.calls)    # the equity keeps the joined token
    fake.emit(opt_tick("123654", last="9.5"))                                # an F&O-shaped tick on the equity's token
    assert "SURYAPHARM" not in obj.snapshot() and obj.kind_mismatch_ticks == 1
    fake.emit({**fx.TICKS["TATASTEEL"], "symbol": "4.1!123654", "last": "0.15", "close": "0.14"})
    assert obj.snapshot(["SURYAPHARM"])["SURYAPHARM"]["price"] == 0.15     # a cash tick is stored as before


# ── the recorded option tick ──────────────────────────────────────────────────────────────────────────────────────────

class _Store:
    def __init__(self) -> None:
        self.appended: list[str] = []

    def append(self, sym, tick) -> bool:
        self.appended.append(sym)
        return True


def test_the_recorded_option_tick_keeps_oi_and_quantities_unclamped_and_is_not_persisted():
    clock = [ist(2026, 11, 5, 10, 20, 53)]
    idx, _ = make_index(MASTER_OLD, day="2026-11-05")
    obj, prov, fake = engine(clock, idx)
    obj.ensure(["TATASTEEL", K_OLD])
    sync(obj)
    assert obj.is_subscribed(K_OLD) and "4.1!39999" in fake.subscribed_tokens()
    store = _Store()
    obj._store = store
    rec = fx.TICKS["NIFTY 24400 CE 09-Nov"]
    fake.emit(rec)
    fake.emit(fx.TICKS["TATASTEEL"])
    t = obj.snapshot([K_OLD])[K_OLD]
    assert t["oi"] == 9_375_925 and t["kind"] == "option" and t["verified"] is True
    assert t["chg_pct"] == pytest.approx((142.7 / 31.7 - 1) * 100, abs=1e-3) and "hint" not in t   # +350 %, never clamped
    assert (t["bid_qty"], t["ask_qty"], t["ltq"], t["bid"], t["ask"]) == (1690.0, 195.0, 65.0, 142.45, 142.65)
    assert (t["upper_circuit"], t["lower_circuit"], t["avg_price"], t["ttv_lakh"]) == (651.1, 0.05, 136.34, 117645.09)
    assert t["oi_chg_tick"] is None and t["prev_close"] == 31.7 and t["contract"]["strike"] == "24400"
    # the units, from the tick's own arithmetic: one lot = ltq = 65; OI and ttq are whole lots; ttq × avgPrice = ttv lakh × 1e5
    assert t["oi"] % 65 == 0 and t["ttq"] % 65 == 0 and t["ttq"] * t["avg_price"] == pytest.approx(t["ttv_lakh"] * 1e5, rel=1e-6)
    assert store.appended == ["TATASTEEL"]                                    # option ticks skip the frozen tick store
    # NEGATIVE CONTROL: the same +350 % on the equity path is clamped (A5) — the clamp is why contracts need their own path
    fake.emit({**fx.TICKS["TATASTEEL"], "last": "809.69"})
    eq = obj.snapshot(["TATASTEEL"])["TATASTEEL"]
    assert eq["chg_pct"] is None and eq["hint"] == "possible corporate action"


def test_an_untraded_contract_tick_keeps_its_book_and_reports_no_price():
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    obj.ensure([K_64412])
    sync(obj)
    fake.emit(opt_tick("64412", last="0", ttq="0", expiry="23-Nov-2026", strike="24350", right="Put"))
    t = obj.snapshot([K_64412])[K_64412]
    assert t["price"] is None and t["chg_pct"] is None and t["bid"] == 142.45 and t["oi"] == 9_375_925 and t["ttq"] == 0.0


# ── caps ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def ladder_keys() -> list[str]:
    return [f"NFO:NIFTY:2026-11-23:{k}:{r}" for k in LADDER for r in ("CE", "PE")]


def test_option_cap_from_env_is_clamped_like_the_symbol_cap():
    assert lt.options_cap_from_env(None) == lt.options_cap_from_env("") == 90
    assert lt.options_cap_from_env("150") == 150 and lt.options_cap_from_env(" 200 ") == 200
    assert lt.options_cap_from_env("500") == 200 and lt.options_cap_from_env("-3") == 0 and lt.options_cap_from_env("lots") == 90
    assert 0 <= lt.MAX_OPTIONS <= 200


def test_options_never_evict_equities_holdings_or_pins_and_equity_demand_never_evicts_contracts(monkeypatch):
    monkeypatch.setattr(lt, "MAX_OPTIONS", 4)
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0], holdings=["RELIANCE"], pins=["NIFTY 50", "NIFTY BANK"])
    keys = ladder_keys()[:10]
    obj.ensure(keys)
    for i in range(lt.MAX_SYMBOLS + 50):                                    # more equity demand than its own cap
        clock[0] += 0.01
        obj.ensure([f"S{i:03d}"])
    sync(obj)
    st = obj.status()
    assert st["subscribed"] == lt.MAX_SYMBOLS                                 # the equity cap, untouched by contracts
    assert obj.is_subscribed("RELIANCE") and obj.is_subscribed("NIFTY 50") and obj.is_subscribed("NIFTY BANK")
    assert [k for k in keys if obj.is_subscribed(k)] == keys[:4]              # earlier in the request = nearer ATM = first
    assert st["options"]["subscribed"] == 4 and st["options"]["over_cap"] == 6
    subs = [t for c in fake.calls if c[0] == "subscribe" for t in c[1]]
    assert len(subs) == lt.MAX_SYMBOLS + 4


def test_a_chain_still_asked_for_keeps_its_slots_and_yields_once_it_stops(monkeypatch):
    monkeypatch.setattr(lt, "MAX_OPTIONS", 4)
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    a, b = ladder_keys()[:4], ladder_keys()[10:14]
    obj.ensure(a)
    sync(obj)
    assert all(obj.is_subscribed(k) for k in a)
    clock[0] += 5
    obj.ensure(a)
    clock[0] += 0.5
    obj.ensure(b)                                                             # b is the more recent request
    sync(obj)
    assert all(obj.is_subscribed(k) for k in a) and not any(obj.is_subscribed(k) for k in b)   # no thrash
    assert obj.contract_states(b)[b[0]]["over_cap"] is True
    clock[0] += lt.OPTION_HOLD_S + 1
    obj.ensure(b)                                                             # a has not been asked for since
    sync(obj)
    assert all(obj.is_subscribed(k) for k in b) and not any(obj.is_subscribed(k) for k in a)
    dropped = [t for c in fake.calls if c[0] == "unsubscribe" for t in c[1]]
    assert len(dropped) == 4


def test_a_zero_option_cap_turns_contracts_off(monkeypatch):
    monkeypatch.setattr(lt, "MAX_OPTIONS", 0)
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    obj.ensure(["TATASTEEL", K_64411])
    sync(obj)
    assert obj.is_subscribed("TATASTEEL") and not obj.is_subscribed(K_64411) and obj.status()["options"]["requested"] == 0


# ── the daily rebuild and token reuse ─────────────────────────────────────────────────────────────────────────────────

def test_the_daily_rebuild_moves_a_reused_token_to_its_new_contract():
    clock = [ist(2026, 11, 5, 10, 20, 53)]
    idx, state = make_index(MASTER_OLD, day="2026-11-05", sid="file:old")
    obj, prov, fake = engine(clock, idx)
    obj.ensure([K_OLD])
    sync(obj)
    fake.emit(fx.TICKS["NIFTY 24400 CE 09-Nov"])
    assert obj.snapshot([K_OLD])[K_OLD]["oi"] == 9_375_925
    # NEGATIVE CONTROL: same day, same archive → no re-parse, no churn
    parses, calls = idx.parses, len(fake.calls)
    sync(obj)
    assert idx.parses == parses and len(fake.calls) == calls
    # 22 Nov: the refreshed master says 39999 = BANKBARODA 29-Dec 380 CE; the NIFTY contract expired on 9 Nov
    clock[0] = ist(2026, 11, 22, 11)
    state.update(text=MASTER_NOW, day="2026-11-22", sid="file:new")
    obj.ensure([K_BOB])
    sync(obj)
    assert not obj.is_subscribed(K_OLD) and K_OLD not in obj.snapshot()     # its cached tick may be another instrument's
    assert obj.is_subscribed(K_BOB) and obj._token_to_syms["4.1!39999"] == {K_BOB}
    assert not any(c[0] == "unsubscribe" and "4.1!39999" in c[1] for c in fake.calls)       # reused, so never dropped
    # the old contract's tick arriving now on 39999 carries the SDK's NIFTY annotation: the first-tick check drops it
    fake.emit(fx.TICKS["NIFTY 24400 CE 09-Nov"])
    assert K_BOB not in obj.snapshot() and obj.first_tick_mismatches == 1
    assert "expiry 2026-11-09, expected 2026-12-29" in obj.status()["options"]["sub_errors"][K_BOB]


# ── the first-tick check ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_first_tick_that_contradicts_the_contract_drops_it_and_the_worker_unsubscribes():
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    obj.ensure([K_64411])
    sync(obj)
    fake.emit(opt_tick("64411", expiry="01-Dec-2026", strike="24350", right="Call"))
    assert K_64411 not in obj.snapshot() and obj.first_tick_mismatches == 1
    assert obj._resync.is_set()
    sync(obj)
    assert ("unsubscribe", ["4.1!64411"]) in fake.calls and not obj.is_subscribed(K_64411)
    assert "first tick does not match the contract: expiry 2026-12-01" in obj.status()["options"]["sub_errors"][K_64411]
    fake.emit(opt_tick("64411", expiry="23-Nov-2026", strike="24350", right="Call"))
    assert K_64411 not in obj.snapshot() and obj.unmapped_ticks == 1          # no name holds the token any more


@pytest.mark.parametrize("tick, why", [
    ({"strike_price": "24400"}, "strike 24400, expected 24350"),
    ({"right": "Put"}, "right PE, expected CE"),
    ({"product_type": "Futures"}, "product Futures, expected options"),
    ({"exchange": "NSE Equity"}, "a cash-market tick arrived on this F&O token"),
])
def test_each_annotation_field_is_checked(tick, why):
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    obj.ensure([K_64411])
    sync(obj)
    fake.emit({**opt_tick("64411", expiry="23-Nov-2026", strike="24350", right="Call"), **tick})
    assert K_64411 not in obj.snapshot() and why in obj.status()["options"]["sub_errors"][K_64411]


def test_a_matching_or_unannotated_first_tick_is_kept_and_a_later_cash_tick_is_not_stored():
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    obj.ensure([K_64411, K_FUT])
    sync(obj)
    fake.emit(opt_tick("64411", expiry="23-Nov-2026", strike="24350", right="Call"))
    fake.emit({**opt_tick("61471", last="24410.5"), "product_type": "Futures", "expiry_date": "23-Nov-2026"})
    snap = obj.snapshot()
    assert snap[K_64411]["verified"] and snap[K_FUT]["kind"] == "future" and snap[K_FUT]["price"] == 24410.5
    assert obj.first_tick_mismatches == 0 and obj.unannotated_first_ticks == 0
    obj2, _, fake2 = engine(clock, make_index()[0])
    obj2.ensure([K_64411])
    sync(obj2)
    fake2.emit(opt_tick("64411"))                                            # F&O-shaped, no annotation (a colliding token)
    assert K_64411 in obj2.snapshot() and obj2.unannotated_first_ticks == 1
    clock[0] += 1
    fake.emit({**fx.TICKS["TATASTEEL"], "symbol": "4.1!64411"})               # a cash-shaped tick after verification
    assert obj.snapshot([K_64411])[K_64411]["price"] == 142.7 and obj.kind_mismatch_ticks == 1


def test_a_reconnect_rechecks_every_contract_on_its_next_first_tick():
    clock = [ist(2026, 11, 20)]
    obj, prov, fake = engine(clock, make_index()[0])
    obj.ensure([K_64411])
    sync(obj)
    fake.emit(opt_tick("64411", expiry="23-Nov-2026", strike="24350", right="Call"))
    assert K_64411 in obj._verified
    prov._breeze = tt.FakeBreeze()                                           # re-login: a new client, a new socket
    obj._step()
    obj._step()
    assert obj.is_subscribed(K_64411) and K_64411 not in obj._verified


# ── expiry ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_contract_expires_at_1530_ist_and_is_refused_or_dropped_then():
    assert not lt.contract_expired("2026-11-23", ist(2026, 11, 23, 15, 29, 59))
    assert lt.contract_expired("2026-11-23", ist(2026, 11, 23, 15, 30, 0))
    clock = [ist(2026, 11, 23, 15, 29)]
    obj, prov, fake = engine(clock, make_index(day="2026-11-23")[0])
    obj.ensure([K_64411, K_EXPIRED])
    sync(obj)
    assert obj.is_subscribed(K_64411) and not obj.is_subscribed(K_EXPIRED)
    assert "expired: 2026-11-17" in obj.status()["options"]["sub_errors"][K_EXPIRED]
    clock[0] = ist(2026, 11, 23, 15, 31)
    obj.ensure([K_64411])
    sync(obj)
    assert not obj.is_subscribed(K_64411) and ("unsubscribe", ["4.1!64411"]) in fake.calls
    # the expiry is the master's: 23 Nov 2026 is a Monday (24 Nov is a holiday), so a computed weekday rule would be wrong
    m = make_index()[0].maps(["NIFTY"])
    assert "2026-11-23" in m.expiries("NIFTY") and "2026-11-24" not in m.expiries("NIFTY")
