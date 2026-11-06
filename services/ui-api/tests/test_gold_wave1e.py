"""GOLD wave 1e (6 Nov 2026): the final critics' majors on the API side (C-DATA-3 / C-TRADER-3, PUBLISH-WITH-FIXES) — every
rule with a negative control. Offline: test_gold's data-service fake, pinned clock and Yahoo fake; no broker, no network.

M-A  one India basis per clock per page for the PICKED contract: /health takes contract / expiry and folds the live MCX quote
     exactly as /overview does, only while MCX trades; the gauge's chip names its clock; strip == gauge == H4.
M-B  one real yield per page: MACRO's fresher-twin rule on the HEALTH tile, its dated H2 clause and the header strip.
M-C  the Shanghai premium equals its printed legs: SGE $/oz − LBMA PM = premium (to $0.1) on PHYSICAL and the HEALTH tile.
M-D  the Sun 8 Nov 2026 Muhurat session (14:20–15:30, MCX/TRD/590/2026) is a SESSION: Mon 9 Nov 08:45's baseline is Sunday's
     last-30-min VWAP (15:00–15:30), and the 08:45 snapshot says so when it has to fall back to an older session.
M-E  server-side minors: Breeze time read as IST, OHLC sanity + the store's partial flag on /bars, tender age, ZQ label,
     Brent instrument, untimed events.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import routers.gold_preopen as gp  # noqa: E402
from routers import gold, mcx  # noqa: E402
from shared import mcx_specs as specs  # noqa: E402
from test_gold import CLOSE_AT, NOW, _app, _fake_db, _offline  # noqa: E402,F401 — the autouse fakes (no network) and the app

IST = gp.IST
FRI, SAT, SUN, MON, TUE = (date(2026, 11, d) for d in (6, 7, 8, 9, 10))
DEC26 = date(2026, 12, 4)


def at(d: date, h: int, m: int) -> datetime:
    return datetime(d.year, d.month, d.day, h, m, tzinfo=IST)


@pytest.fixture
def client() -> Any:
    with TestClient(_app()) as c:
        yield c


def _ok(value: float, session: date, expiry: date = DEC26) -> dict[str, Any]:
    return {"status": "ok", "value": value, "bars": 30, "volume": 160.0, "method": "volume-weighted", "window": "15:00–15:30 IST",
            "last_close": value, "session": session.isoformat(), "source": "breeze_vwap30", "stock_code": "GOLD",
            "expiry": expiry.isoformat()}


# ══ M-D: the Muhurat special session ══════════════════════════════════════════════════════════════════════════════

def test_muhurat_is_a_trading_window_and_an_ordinary_sunday_is_not() -> None:
    win = specs.trading_window(SUN)
    assert win is not None and (f"{win[0]:%H:%M}", f"{win[1]:%H:%M}") == ("14:20", "15:30")
    assert specs.is_session_day(SUN) and specs.special_session_on(SUN)["circular"] == "MCX/TRD/590/2026"
    st = specs.session_state(at(SUN, 14, 30))
    assert st["is_open"] is True and st["special"]["name"].startswith("Muhurat") and st["weekend"] is True
    assert specs.session_state(at(SAT, 12, 0))["opens_at"] == "2026-11-08T14:20:00+05:30"     # Saturday → the Sunday window
    # negative controls: Saturday, an ordinary Sunday and Sunday after 15:30 are shut; expiry rules ignore the special day
    assert specs.trading_window(SAT) is None and specs.trading_window(date(2026, 11, 15)) is None
    assert specs.session_state(at(SUN, 15, 31))["is_open"] is False
    assert specs.special_session_on(date(2026, 11, 15)) is None and not specs._expiry_business_day(SUN)
    # the literal the desktop drift check reads is still there
    assert '"date": "2026-11-08"' in Path(specs.__file__).read_text(encoding="utf-8")


def test_the_session_chain_counts_the_muhurat_session() -> None:
    assert gp.previous_session(MON) == SUN and gp.previous_session(SUN) == FRI
    assert gp.previous_session(TUE) == MON
    assert gp.band_session(MON) == FRI and gp.band_applies_to(MON) == SUN       # Mon file: band OF Sunday, centred on Friday
    assert gp.band_session(TUE) == SUN                                          # Tue file: centred on the Muhurat settlement
    assert gp.latest_completed_session(at(MON, 8, 45)) == SUN                   # THE morning: Sunday is the latest session
    assert gp.latest_completed_session(at(SUN, 15, 0)) == FRI                   # the session is still running
    assert gp.latest_completed_session(at(SUN, 15, 33)) == SUN                  # close + the 2-min grace
    assert gp.session_close_at(SUN).strftime("%H:%M") == "15:30"
    # negative controls: an ordinary week skips the weekend (Mon 16 Nov → Fri 13 Nov)
    assert gp.previous_session(date(2026, 11, 16)) == date(2026, 11, 13)
    assert gp.latest_completed_session(at(date(2026, 11, 16), 8, 45)) == date(2026, 11, 13)
    assert gold.sessions_between(FRI, MON) == 2 and gold.sessions_between(date(2026, 11, 13), date(2026, 11, 16)) == 1


def test_the_vwap_window_of_a_short_session_is_its_last_30_minutes() -> None:
    bars = [{"datetime": f"2026-11-08 {h:02d}:{m:02d}:00", "close": 150_000.0 + 10 * (h * 60 + m - 860), "volume": 2}
            for h, m in ((14, x) for x in range(20, 60)) for _ in [0]] + \
           [{"datetime": f"2026-11-08 15:{m:02d}:00", "close": 151_000.0 + m, "volume": 3} for m in range(0, 30)]
    vw = gp.vwap_last_minutes(bars, gp.session_close_at(SUN))
    assert vw is not None and vw["window"] == "15:00–15:30 IST" and vw["bars"] == 30
    assert vw["value"] == pytest.approx(151_000.0 + 14.5, abs=0.05)             # only the 15:00–15:29 bars, volume-weighted
    # negative control: the usual 23:25–23:55 window finds nothing on the Muhurat Sunday
    assert gp.vwap_last_minutes(bars, gp.mcx_close_time(SUN)) is None


def test_mcx_day_and_the_snapshot_gate_on_the_muhurat_sunday() -> None:
    d = gp.mcx_day(SUN)
    assert d["trading"] is True and d["closure"] is None and d["opens_at"] == "2026-11-08T14:20+05:30"
    assert "MCX/TRD/590/2026" in d["note"] and d["special"]["opens"] == "14:20"
    with pytest.raises(HTTPException) as e:
        gp.snapshot_gate(at(SUN, 8, 45), force=False)                           # no 09:00 open to call on the Sunday
    assert e.value.status_code == 409
    gp.snapshot_gate(at(SUN, 8, 45), force=True)
    gp.snapshot_gate(at(MON, 8, 45), force=False)                               # Monday's 08:45 runs as usual
    # negative control: an ordinary Sunday is a weekend, closed
    assert gp.mcx_day(date(2026, 11, 15))["closure"] == "weekend" and gp.mcx_day(date(2026, 11, 15))["trading"] is False


def test_the_calendar_and_the_mcx_session_route_carry_the_muhurat_window(client: TestClient) -> None:
    rows = [e for e in gold.computed_events(FRI, 7) if e["kind"] == "MCX_SPECIAL"]
    assert len(rows) == 1 and rows[0]["time_ist"] == "14:20" and "14:20–15:30" in rows[0]["time_note"]
    body = client.get("/api/mcx/session").json()
    assert body["special_sessions"][0]["closes"] == "15:30" and body["special_sessions"][0]["date"] == "2026-11-08"


class _Frozen(datetime):
    NOW = at(MON, 8, 40)

    @classmethod
    def now(cls, tz: Any = None) -> datetime:   # type: ignore[override]
        return cls.NOW if tz is None else cls.NOW.astimezone(tz)


def _snapshot_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    import test_gold_preopen as tgp

    monkeypatch.setenv("GOLD_LOG_PATH", str(tmp_path / name))
    real_client = gp.httpx.AsyncClient
    gp._cache.clear()
    gp._settle_cache.clear()
    monkeypatch.setattr(gp, "_load_mcx_master", lambda: (tgp.HEADER + tgp.ROWS, MON))
    monkeypatch.setattr(gp, "_breeze_mcx_quote", lambda expiry: None)
    monkeypatch.setattr(gp, "_breeze_mcx_open", lambda expiry, day: None)
    monkeypatch.setattr(gp, "_refresh_treasury_in_background", lambda: None)
    monkeypatch.setattr(gp, "datetime", _Frozen)
    transport = gp.httpx.MockTransport(tgp._Upstream())
    monkeypatch.setattr(gp.httpx, "AsyncClient", lambda *a, **k: real_client(*a, **{**k, "transport": transport}))


def test_monday_0845_baseline_is_the_muhurat_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _snapshot_setup(tmp_path, monkeypatch, "log.json")
    gp._settle_cache.set(gp._settle_key("GOLD", DEC26, SUN), _ok(151_014.5, SUN))
    gp._settle_cache.set(gp._settle_key("GOLD", DEC26, FRI), _ok(149_800.0, FRI))
    row = asyncio.run(gp.gold_snapshot(force=False))
    assert row["baseline"] == 151_014.5 and row["baseline_session"] == "2026-11-08" and row["baseline_source_kind"] == "breeze_vwap30"
    assert row["stale_baseline"] is False and row["baseline_older_than_expected"] is False
    assert row["baseline_expected_session"] == "2026-11-08" and "baseline_note" not in row
    gp._cache.clear()
    gp._settle_cache.clear()


def test_monday_0845_flags_a_baseline_older_than_the_muhurat_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _snapshot_setup(tmp_path, monkeypatch, "log2.json")
    gp._settle_cache.set(gp._settle_key("GOLD", DEC26, FRI), _ok(149_800.0, FRI))   # no VWAP stored or read for Sunday
    row = asyncio.run(gp.gold_snapshot(force=False))
    assert row["baseline_session"] == "2026-11-06" and row["baseline"] == 149_800.0      # Friday's VWAP stands in, labelled
    assert row["stale_baseline"] is True and row["baseline_older_than_expected"] is True
    assert row["baseline_expected_session"] == "2026-11-08"
    note = row["baseline_note"]
    assert note.startswith("baseline session older than expected") and "Sun 08 Nov settlement" in note and "Muhurat" in note
    assert "Fri 06 Nov settlement" in note
    gp._cache.clear()
    gp._settle_cache.clear()


# ══ M-A: one basis per clock per page, for the picked contract ═══════════════════════════════════════════════════

def _live_quote(contract: str, ltp: float, expiry: str, time_str: str) -> dict[str, Any]:
    return {"available": True, "expiry": expiry, "contract": contract, "as_of": NOW.isoformat(timespec="seconds"),
            "quote": {"ltp": ltp, "source": "ICICI Breeze (1-min bars)", "time": time_str}}


def test_health_takes_the_contract_and_folds_the_live_quote_like_the_overview(client: TestClient,
                                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def live(contract: str = "GOLD", expiry: str | None = None) -> dict[str, Any]:
        calls.append(contract)
        return _live_quote(contract, 146_000.0, "2026-10-30", "2026-10-26 09:56:00")   # Breeze's zone-less IST minute

    monkeypatch.setattr(mcx, "mcx_quote", live)
    h = client.get("/api/gold/health", params={"contract": "GOLDTEN"}).json()
    o = client.get("/api/gold/overview", params={"contract": "GOLDTEN"}).json()
    ib = next(g for g in h["gauges"] if g["key"] == "india_basis")
    h4 = next(c for c in h["verdict"]["clauses"] if c["rule_id"] == "H4")
    oib = next(g for g in o["health"]["gauges"] if g["key"] == "india_basis")
    assert ib["clock"] == "now" and ib["basis_contract"].startswith("GOLDTEN") and ib["basis_reference"] == "landed_999"
    # strip == gauge == verdict, and /health?contract= == /overview?contract=.health
    assert o["strip"]["basis_pct"] == ib["value"] == h4["value"] == oib["value"]
    assert h4["clock"] == "now" and "(live) on GOLDTEN" in h4["text"]
    assert ib["clock_label"] == "LIVE · GOLDTEN OCT-26 · 09:56 IST" == oib["clock_label"]
    # the Breeze minute is IST, never in the future (C-DATA-3: '14:46 +05:30' for the 09:16 bar)
    assert h["live_quote"]["as_of"] == "2026-10-26T09:56:00+05:30" == o["strip"]["mcx_live_as_of"]
    assert gold._dt(o["strip"]["mcx_live_as_of"]) <= gold._dt(o["as_of"])
    assert gold._iso_any("2026-10-26 09:56:00") == "2026-10-26T15:26:00+05:30"     # negative control: the old reading
    assert "GOLDTEN" in calls
    # the default stays GOLD (the WEI / BRF echo, polled): no broker read of its own — only a quote the cache holds is folded
    calls.clear()
    h0 = client.get("/api/gold/health").json()
    g0 = next(g for g in h0["gauges"] if g["key"] == "india_basis")
    assert g0["basis_contract"].startswith("GOLD ") and g0["basis_reference"] == "landed_995"
    assert calls == [] and h0["live_quote"]["applied"] is False


def test_outside_mcx_hours_health_reads_no_quote_and_stays_at_the_settlement_clock(client: TestClient,
                                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def live(contract: str = "GOLD", expiry: str | None = None) -> dict[str, Any]:
        calls.append(contract)
        return _live_quote(contract, 146_000.0, "2026-10-30", "2026-10-26 23:29:00")

    monkeypatch.setattr(mcx, "mcx_quote", live)
    closed = at(date(2026, 10, 26), 23, 45)                                     # after the 23:30 close (US daylight time)
    monkeypatch.setattr(gold, "_now_ist", lambda: closed)
    # tonight's settlement is known (a fresh settlement-clock gauge, so the H4 clause is printed)
    gp._settle_cache.set(gp._settle_key("GOLDTE", date(2026, 10, 30), date(2026, 10, 26)),
                         _ok(145_900.0, date(2026, 10, 26), date(2026, 10, 30)))
    h = client.get("/api/gold/health", params={"contract": "GOLDTEN"}).json()
    ib = next(g for g in h["gauges"] if g["key"] == "india_basis")
    assert calls == [] and h["live_quote"]["applied"] is False and h["live_quote"]["is_open"] is False
    assert ib["clock"] == "settlement" and ib["clock_label"].startswith("SETTLEMENT · ")
    h4 = next(c for c in h["verdict"]["clauses"] if c["rule_id"] == "H4")
    assert h4["value"] == ib["value"] and "(live)" not in h4["text"]
    # the overview reads its quote in every state but never folds a frozen LTP after the close (the same fold)
    o = client.get("/api/gold/overview", params={"contract": "GOLDTEN"}).json()
    assert o["health"]["live_quote"]["applied"] is False and o["strip"]["basis_clock"] == "settlement"


def test_a_broker_time_in_the_future_is_dropped_not_served() -> None:
    now = at(date(2026, 11, 6), 9, 17)
    q = _live_quote("GOLD", 142_556.0, "2026-12-04", "2026-11-06T14:46:00+05:30")    # the stamp the critics captured
    out = gold.fold_live_quote(None, q, now)
    assert out["as_of"] is None and out["mcx_live"] == 142_556.0
    ok = gold.fold_live_quote(None, _live_quote("GOLD", 142_556.0, "2026-12-04", "2026-11-06 09:16:00"), now)
    assert ok["as_of"] == "2026-11-06T09:16:00+05:30"
    assert gold._iso_ist("06-Nov-2026 09:16:00") == "2026-11-06T09:16:00+05:30" and gold._iso_ist("2026-11-06") == "2026-11-06"
    assert gold._iso_ist("not a time") is None


def test_basis_clock_label_names_the_clock() -> None:
    assert gold.basis_clock_label("now", "GOLD DEC-26", "2026-11-06T09:16:00+05:30", None, None) == "LIVE · GOLD DEC-26 · 09:16 IST"
    assert gold.basis_clock_label("settlement", "GOLD DEC-26", None, "breeze_vwap30", "2026-11-05") == \
        "SETTLEMENT · VWAP30 PROXY · Thu 05 Nov"
    assert gold.basis_clock_label("settlement", None, None, "band_midpoint", "2026-11-04") == "SETTLEMENT · BAND PROXY · Wed 04 Nov"
    assert gold.basis_clock_label(None, None, None, None, None) is None


# ══ M-B: one real yield per page ═══════════════════════════════════════════════════════════════════════════════

def _with_fresher_ust(drop_fred_after: str = "2026-10-22") -> Any:
    async def db(path: str, params: dict[str, Any]) -> Any:
        out = await _fake_db(path, params)
        if path != "/db/gold/series":
            return out
        ids = set(str(params.get("ids", "")).split(","))
        rows = [r for r in out["rows"] if not (r["series_id"] == "FRED_DFII10" and r["report_date"] > drop_fred_after)]
        if "UST_REAL_10Y" in ids:
            d0 = NOW.date()
            for k in range(40, -1, -1):
                d = d0 - timedelta(days=k)
                if d.weekday() < 5:
                    rows.append({"series_id": "UST_REAL_10Y", "report_date": d.isoformat(), "value": round(2.40 + 0.002 * k, 4),
                                 "release_at": f"{d.isoformat()}T21:00:00+00:00"})
        return {"rows": rows}

    return db


def test_the_real_yield_is_one_value_one_date_per_page(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _with_fresher_ust())
    h = client.get("/api/gold/health").json()
    ry = next(g for g in h["gauges"] if g["key"] == "real_yield")
    assert ry["series_id"] == "UST_REAL_10Y" and ry["report_date"] == "2026-10-26" and ry["value"] == 2.4
    assert ry["label_note"] == "UST_REAL_10Y: fresher than FRED_DFII10 (last 2026-10-22)" and ry["primary_series_id"] == "FRED_DFII10"
    h2 = next(c for c in h["verdict"]["clauses"] if c["rule_id"] == "H2")
    assert h2["series_id"] == h2["real_yield_series_id"] == "UST_REAL_10Y" and h2["real_yield_date"] == "2026-10-26"
    assert "(to Mon 26 Oct)" in h2["text"] and h2["real_yield_change_bp"] == ry["change_bp"]
    o = client.get("/api/gold/overview").json()
    assert o["strip"]["real_10y"] == ry["value"] and o["strip"]["real_10y_date"] == ry["report_date"]
    assert o["strip"]["real_10y_series_id"] == "UST_REAL_10Y"
    m = next(d for d in client.get("/api/gold/macro").json()["drivers"] if d["key"] == "real_10y")
    assert m["series_id"] == "UST_REAL_10Y" and m["value"] == ry["value"] and m["report_date"] == ry["report_date"]
    assert m["label_note"] == ry["label_note"]


def test_the_primary_real_yield_stays_when_it_is_as_fresh(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _with_fresher_ust(drop_fred_after="2026-12-31"))   # FRED to Mon 26 Oct as well
    h = client.get("/api/gold/health").json()
    ry = next(g for g in h["gauges"] if g["key"] == "real_yield")
    assert ry["series_id"] == "FRED_DFII10" and ry["label_note"] is None
    o = client.get("/api/gold/overview").json()
    assert o["strip"]["real_10y_series_id"] == "FRED_DFII10" and o["strip"]["real_10y"] == ry["value"]
    # pure rule: not a twin → the primary even when the alternate is newer; unpublished alternate → the primary
    series = {"A": [{"report_date": "2026-10-22", "value": 1.0}], "B": [{"report_date": "2026-10-26", "value": 2.0}]}
    cat = {"A": {"verdict": "PUBLISH-CORE", "badge": "context"}, "B": {"verdict": "PUBLISH-CORE", "badge": "context"}}
    assert gold.pick_twin(series, "A", "B", cat, True)[0] == "B" and gold.pick_twin(series, "A", "B", cat, False)[0] == "A"
    assert gold.pick_twin(series, "A", "B", {"A": cat["A"]}, True)[0] == "A"


# ══ M-C: the Shanghai premium equals its printed legs ═════════════════════════════════════════════════════════

G = gold.GRAMS_PER_TROY_OZ


def _with_shanghai() -> Any:
    """The 6 Nov shape: SGE 4 Nov 865.47 CNY/g, LBMA PM 4,037.8, CNY=X 4 Nov first 6.6643 then REVISED to 6.6701 at 03:10;
    the stored derive (+1.50) used the first vintage."""
    async def db(path: str, params: dict[str, Any]) -> Any:
        out = await _fake_db(path, params)
        if path != "/db/gold/series":
            return out
        ids = set(str(params.get("ids", "")).split(","))
        extra = [
            ("SGE_SHAU_PM", "2026-11-03", 870.10, "2026-11-03T08:00:00+00:00"),
            ("SGE_SHAU_PM", "2026-11-04", 865.47, "2026-11-04T08:00:00+00:00"),
            ("SGE_SHAU_PM", "2026-11-05", 885.89, "2026-11-05T08:00:00+00:00"),
            ("LBMA_PM_USD", "2026-11-03", 4061.0, "2026-11-03T16:00:00+00:00"),
            ("LBMA_PM_USD", "2026-11-04", 4037.8, "2026-11-04T16:00:00+00:00"),
            ("FX_CNY", "2026-11-03", 6.6600, "2026-11-03T21:40:00+00:00"),
            ("FX_CNY", "2026-11-04", 6.6643, "2026-11-04T15:30:00+00:00"),
            ("FX_CNY", "2026-11-04", 6.6701, "2026-11-05T21:40:00+00:00"),       # the 03:10 revision
            ("SHANGHAI_PREMIUM_USD", "2026-11-03", round(870.10 * G / 6.66 - 4061.0, 2), "2026-11-03T16:00:00+00:00"),
            ("SHANGHAI_PREMIUM_USD", "2026-11-04", 1.50, "2026-11-05T16:00:00+00:00"),
        ]
        rows = out["rows"] + [{"series_id": s, "report_date": d, "value": v, "release_at": r} for s, d, v, r in extra if s in ids]
        return {"rows": rows}

    return db


def test_the_shanghai_premium_reproduces_from_its_printed_legs(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _with_shanghai())
    sh = client.get("/api/gold/premiums").json()["shanghai"]
    assert sh["pair_date"] == "2026-11-04" and sh["usdcny"] == 6.6701 and sh["sge_pm_cny_g"] == 865.47
    assert sh["sge_usd_oz"] == pytest.approx(865.47 * G / 6.6701, abs=0.01) and sh["london_pm_usd"] == 4037.8
    assert abs(sh["sge_usd_oz"] - sh["london_pm_usd"] - sh["premium_usd"]) < 0.1 and sh["reconciles"] is True
    assert sh["premium_usd"] == pytest.approx(-2.0, abs=0.05) and sh["premium_usd_stored"] == 1.5
    assert "earlier USDCNY vintage" in sh["recompute_note"] and sh["usdcny_as_of"] == "2026-11-06T03:10:00+05:30"
    assert sh["note"].startswith("awaiting today's PM")                         # SGE 5 Nov is in, its London PM is not
    assert sh["history"][-1]["premium_usd"] == sh["premium_usd"] and sh["history"][-1]["source"] == "legs"
    # the HEALTH tile prints the same number (one Shanghai premium per page)
    tile = next(g for g in client.get("/api/gold/health").json()["gauges"] if g["key"] == "shanghai")
    assert tile["value"] == pytest.approx(sh["premium_usd"], abs=0.005) and tile["premium_source"] == "legs"
    # negative control: the stored derive does NOT reproduce from the printed legs (the critics' −$2.0 vs +$1.50)
    assert abs(sh["sge_usd_oz"] - sh["london_pm_usd"] - sh["premium_usd_stored"]) > 3.0


def test_shanghai_pairs_keep_the_stored_derive_where_a_leg_is_missing() -> None:
    pts = lambda *xs: [{"report_date": d, "value": v, "release_at": None} for d, v in xs]  # noqa: E731
    pairs = gold.shanghai_pairs(pts(("2026-11-03", 870.0)), pts(), pts(("2026-11-03", 6.66)), pts(("2026-11-03", -1.55)))
    assert [(p["source"], p["premium_usd"]) for p in pairs] == [("stored", -1.55)]
    two = gold.shanghai_pairs(pts(("2026-11-03", 870.0)), pts(("2026-11-03", 4061.0)), pts(("2026-11-02", 6.65)), pts())
    assert two[0]["usdcny_date"] == "2026-11-02" and two[0]["premium_usd"] == pytest.approx(870.0 * G / 6.65 - 4061.0, abs=0.01)


# ══ M-E: server-side minors ═════════════════════════════════════════════════════════════════════════════════════

def test_ohlc_sanity_withholds_an_impossible_open_and_keeps_the_store_partial_flag() -> None:
    bar = gold.ohlc_sane({"ts": "2026-11-05", "o": 3940.8, "h": 4155.8, "l": 4067.0, "c": 4098.4, "v": 1.0})
    assert bar["o"] is None and bar["o_raw"] == 3940.8 and "open outside" in bar["ohlc_note"] and bar["c"] == 4098.4
    rows = gold._bar_rows({"rows": [{"trade_date": "2026-11-05", "open": 3940.8, "high": 4155.8, "low": 4067.0, "close": 4098.4,
                                     "volume": 1, "partial": True}]})
    assert rows[0]["partial"] is True and rows[0]["o"] is None
    # negative control: a possible bar is untouched
    ok = {"ts": "2026-11-04", "o": 3980.0, "h": 4090.0, "l": 3970.0, "c": 4072.2, "v": 1.0}
    assert gold.ohlc_sane(ok) == ok


def test_tender_age_never_reads_as_starts_today() -> None:
    st = gold.tender_state(date(2026, 11, 1), date(2026, 11, 30), FRI)
    assert st["in_tender"] is True and st["days_to_tender"] == 0 and st["days_in_tender"] == 5
    assert st["tender_note"] == "in tender since Sun 01 Nov (5 d)"
    # negative control: before the tender the age is None and the count is positive
    pre = gold.tender_state(date(2026, 12, 1), date(2026, 12, 31), FRI)
    assert pre["in_tender"] is False and pre["days_in_tender"] is None and pre["days_to_tender"] == 25


def test_zq_is_labelled_by_what_it_can_be() -> None:
    rolled = gold.zq_rows([{"report_date": "2026-11-05", "value": 95.95}], 3.88)[0]
    assert rolled["rolled_suspect"] is True and rolled["month"] == "likely DEC-26 (ZQ=F rolled)" and rolled["implied_pct"] == 4.05
    # negative controls: consistent with EFFR → the observation month; a decision in the month → no roll claim
    plain = gold.zq_rows([{"report_date": "2026-11-05", "value": 96.12}], 3.88)[0]
    assert plain["rolled_suspect"] is False and plain["month"] == "NOV-26"
    dec = gold.zq_rows([{"report_date": "2026-12-01", "value": 95.95}], 3.88)[0]
    assert dec["rolled_suspect"] is False and dec["month"] == "DEC-26"
    assert gold.zq_rows([], 3.88) == []


def test_brent_future_is_named_as_a_future_and_untimed_events_say_so() -> None:
    assert gold.MACRO_SERIES_LABEL["BRENT_FRONT"].startswith("Brent front future")
    assert "not dated Brent spot" in gold.MACRO_INSTRUMENT["BRENT_FRONT"]
    assert gold.MACRO_SAME_LEVEL[("FRED_DCOILBRENTEU", "BRENT_FRONT")] is False
    assert gold.untimed_label({"name": "Dhanteras", "time_ist": None}) == "all day"
    assert gold.untimed_label({"kind": "MCX_HOLIDAY", "name": "MCX morning closure: Diwali-Balipratipada"}).startswith(
        "MCX morning session closed")
    assert gold.untimed_label({"name": "US NFP", "time_ist": "19:00"}) is None   # a timed row keeps its time


def test_a_lagging_comex_print_is_chipped_delayed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(client_: Any, symbol: str, rng: str = "5d", interval: str = "5m") -> dict[str, Any]:
        ref = 4060.4 if symbol.startswith("GC") else 94.90
        return {"symbol": symbol, "bars": [(CLOSE_AT - timedelta(minutes=10), ref)], "price": ref, "time": NOW - timedelta(minutes=11)}

    monkeypatch.setattr(gp, "_yahoo_bars", slow)
    f = client.get("/api/gold/fair").json()["freshness"]
    assert f["state"] == "delayed" and f["delay_min"] == 11 and f["chip"] == "COMEX ≈11 min delayed (Yahoo)"


def test_the_band_is_checked_against_its_own_sessions_vwap_not_the_next_ones() -> None:
    """6 Nov: band 1,43,234 (Wed 04 Nov) vs Thu 05 Nov VWAP 1,44,091.7 printed −0.60 % against a 0.6 % limit — Thursday's
    move. The real validation is the band vs WEDNESDAY's VWAP (1,43,236.8: 0.00 %)."""
    wed, thu, fri = date(2026, 11, 4), date(2026, 11, 5), date(2026, 11, 6)
    thu_v = {**_ok(144_091.7, thu), "status": "ok"}
    wed_v = {**_ok(143_236.8, wed), "status": "ok"}
    cross = gp.settlement_block(143_234.0, fri, thu_v, thu)                    # no Wednesday VWAP known
    assert cross["settlement_check"]["flagged"] is False and cross["settlement_check"]["band_vs_vwap30_pct"] is None
    assert cross["session_move_pct"] == pytest.approx((144_091.7 / 143_234.0 - 1) * 100, abs=0.01)
    assert cross["session_move_label"].startswith("Wed 04 Nov → Thu 05 Nov settlement move")
    same = gp.settlement_block(143_234.0, fri, thu_v, thu, wed_v)
    assert same["settlement_check"]["same_session"] is True and same["settlement_check"]["band_vs_vwap30_pct"] == -0.0
    assert same["settlement"] == 144_091.7                                     # the settlement itself is unchanged
    # negative control: a band 1 % off its own session's VWAP is flagged
    assert gp.settlement_block(144_700.0, fri, thu_v, thu, wed_v)["settlement_check"]["flagged"] is True
