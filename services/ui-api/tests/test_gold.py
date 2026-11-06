"""GOLD page API (reports/gold_program/PLAN.md §d, gate T1) — data-service mocked with the research agents' saved samples.

Fixtures: the CFTC disaggregated report (G-STUDY/data, 1,063 weekly rows → the gold_cot table shape), GC=F daily closes
(G-STUDY/data/yahoo_GC_F_1d.csv), a catalog with PUBLISH-* rows and one LINK-ONLY row (the rendering gate), the ICICI
master and Yahoo fakes of test_mcx. Nothing here reaches the network: `_db_fetch` is replaced, the master loader and the
ONE Yahoo fetcher are faked, news/FRED/Breeze are stubbed. The clock is pinned to Mon 26 Oct 2026 10:00 IST so the
freshness states are deterministic.

Checks (T1): the verdict ends "describes, does not predict", carries NO `score`, stale gauges contribute no clause; the
catalog gate; D/W/M resampling and the point-in-time as-of read; holiday gating of snapshot/capture (20 Oct morning closure);
the session label; the duty leg and the deprecated alias; the /api/commodity aliases; GOLDTEN in /contracts; the COT
"who did what" from the 20 Oct 2026 report (OI 402,279; MM net 104,206; closed 3,777 longs / covered 894 shorts; long
liquidation); T9 (no new Yahoo fetcher in gold.py); event-loop purity of the new routes.
"""

from __future__ import annotations

import asyncio
import csv
import re
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routers.gold_preopen as gp
from routers import (
    gold,
    mcx,
)

from shared import mcx_specs as specs

IST = specs.IST
NOW = datetime(2026, 10, 26, 10, 0, tzinfo=IST)
REPO = Path(__file__).resolve().parents[3]
STUDY = REPO / "reports" / "gold_program" / "G-STUDY" / "data"

# ── the ICICI master + Yahoo fakes (as test_mcx.py) ────────────────────────────────────────────────────────────
HEADER = (
    '"Token","InstrumentName","ShortName","Series","CompanyName","TickSize","LotSize","ExpiryDate","OptionType",'
    '"StrikePrice","StartDate","EndDate","ExpiryMonth","MarketLot","MarginPercentage","LowerCktLimit","UpperCktLimit",'
    '"OpenInterest","LifeTimeLow","LifeTimeHigh","LowPriceRange","HighPriceRange","QuantityUnit","PriceUnit",'
    '"DeliveryUnit","Exchange","ExchangeCode"\n'
)
ROWS = (
    '"495213","FUTSTK","GOLD","FUTURE","GOLD",100,1,"04-Dec-2026","XX",0,"","","","",16574,"","","","","",141700,150460,"KGS","RS/10GRMS","KGS","","GOLD"\n'
    '"559933","FUTSTK","GOLD","FUTURE","GOLD",100,1,"05-Feb-2027","XX",0,"","","","",519,"","","","","",143200,152000,"KGS","RS/10GRMS","KGS","","GOLD"\n'
    '"111","FUTSTK","GOLDMI","FUTURE","GOLDM",100,1,"05-Nov-2026","XX",0,"","","","",900,"","","","","",141000,149700,"KGS","RS/10GRMS","KGS","","GOLDM"\n'
    '"444","FUTSTK","GOLDTE","FUTURE","GOLDTEN",100,1,"30-Oct-2026","XX",0,"","","","",25655,"","","","","",141500,150000,"KGS","RS/10GRMS","KGS","","GOLDTEN"\n'
    '"222","FUTSTK","GOLDPETAL","FUTURE","GOLDPETAL",100,1,"30-Oct-2026","XX",0,"","","","",50,"","","","","",14200,15070,"KGS","RS/1GRMS","KGS","","GOLDPETAL"\n'
    '"333","FUTSTK","GOLDGUINEA","FUTURE","GOLDGUINEA",100,1,"30-Oct-2026","XX",0,"","","","",10,"","","","","",113600,120600,"KGS","RS/8GRMS","KGS","","GOLDGUINEA"\n'
)
MASTER = HEADER + ROWS
PUBLISHED = date(2026, 10, 26)  # Monday's file: its band midpoint is the Thu 22 Oct settlement — two sessions back, the
# band being the band OF Fri 23 Oct (wave 1d, gold_preopen.band_session; PLAN 0.1 #8)
CLOSE_AT = datetime(2026, 10, 22, 23, 30, tzinfo=IST)
COMEX_REF, COMEX_NOW = 4060.4, 4007.9
INR_REF, INR_NOW = 94.90, 94.93
YAHOO_CALLS: list[str] = []


async def _fake_yahoo(client: Any, symbol: str, rng: str = "5d", interval: str = "5m") -> dict[str, Any]:
    YAHOO_CALLS.append(symbol)
    ref, now = (
        (COMEX_REF, COMEX_NOW) if symbol.startswith("GC") else (INR_REF, INR_NOW) if symbol.startswith("INR") else (100.0, 100.5)
    )
    return {"symbol": symbol, "bars": [(CLOSE_AT - timedelta(minutes=10), ref)], "price": now, "time": NOW - timedelta(minutes=3)}


# ── the data-service fake: the agents' samples in the table shapes of PLAN c.1 ─────────────────────────────────
COT_MAP = {  # gold_cot column → Socrata column (disaggregated)
    "open_interest": "open_interest_all",
    "oi_chg": "change_in_open_interest_all",
    "pm_long": "prod_merc_positions_long",
    "pm_short": "prod_merc_positions_short",
    "sd_long": "swap_positions_long_all",
    "sd_short": "swap__positions_short_all",
    "sd_spread": "swap__positions_spread_all",
    "mm_long": "m_money_positions_long_all",
    "mm_short": "m_money_positions_short_all",
    "mm_spread": "m_money_positions_spread",
    "or_long": "other_rept_positions_long",
    "or_short": "other_rept_positions_short",
    "or_spread": "other_rept_positions_spread",
    "nr_long": "nonrept_positions_long_all",
    "nr_short": "nonrept_positions_short_all",
    "chg_pm_long": "change_in_prod_merc_long",
    "chg_pm_short": "change_in_prod_merc_short",
    "chg_sd_long": "change_in_swap_long_all",
    "chg_sd_short": "change_in_swap_short_all",
    "chg_sd_spread": "change_in_swap_spread_all",
    "chg_mm_long": "change_in_m_money_long_all",
    "chg_mm_short": "change_in_m_money_short_all",
    "chg_mm_spread": "change_in_m_money_spread",
    "chg_or_long": "change_in_other_rept_long",
    "chg_or_short": "change_in_other_rept_short",
    "chg_or_spread": "change_in_other_rept_spread",
    "chg_nr_long": "change_in_nonrept_long_all",
    "chg_nr_short": "change_in_nonrept_short_all",
    "traders_total": "traders_tot_all",
    "traders_mm_long": "traders_m_money_long_all",
    "traders_mm_short": "traders_m_money_short_all",
    "traders_mm_spread": "traders_m_money_spread_all",
    "traders_sd_long": "traders_swap_long_all",
    "traders_sd_short": "traders_swap_short_all",
    "traders_pm_long": "traders_prod_merc_long_all",
    "traders_pm_short": "traders_prod_merc_short_all",
    "traders_or_long": "traders_other_rept_long_all",
    "traders_or_short": "traders_other_rept_short",
    "conc_gross4_long": "conc_gross_le_4_tdr_long",
    "conc_gross4_short": "conc_gross_le_4_tdr_short",
    "conc_gross8_long": "conc_gross_le_8_tdr_long",
    "conc_gross8_short": "conc_gross_le_8_tdr_short",
    "conc_net4_long": "conc_net_le_4_tdr_long_all",
    "conc_net4_short": "conc_net_le_4_tdr_short_all",
    "conc_net8_long": "conc_net_le_8_tdr_long_all",
    "conc_net8_short": "conc_net_le_8_tdr_short_all",
}


def _num(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cot_rows(kind: str, n: int = 170) -> list[dict[str, Any]]:
    """The last n weekly reports of the saved Socrata CSV in gold_cot's columns (release_at by the Friday rule)."""
    path = STUDY / f"cftc_socrata_disagg_{kind}_gold_088691.csv"
    out = []
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            rd = date.fromisoformat(r["report_date_as_yyyy_mm_dd"][:10])
            friday = rd + timedelta(days=(4 - rd.weekday()) % 7 or 7)
            row = {
                "report_date": rd.isoformat(),
                "contract_code": "088691",
                "fut_or_combined": "F" if kind == "fut" else "C",
                "report": "disagg",
                "release_at": datetime(friday.year, friday.month, friday.day, 19, 30, tzinfo=timezone.utc).isoformat(),
                "source": "cftc_socrata",
            }
            row.update({k: _num(r.get(src, "")) for k, src in COT_MAP.items()})
            out.append(row)
    return out[-n:]


def gc_bars(n: int = 700) -> list[dict[str, Any]]:
    out = []
    with (STUDY / "yahoo_GC_F_1d.csv").open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.append(
                {
                    "trade_date": r["date"],
                    "symbol": "GC=F",
                    "open": _num(r["open"]),
                    "high": _num(r["high"]),
                    "low": _num(r["low"]),
                    "close": _num(r["close"]),
                    "volume": _num(r["volume"]),
                    "source": "yahoo",
                }
            )
    return out[-n:]


def catalog_rows() -> list[dict[str, Any]]:
    def row(sid: str, verdict: str = "PUBLISH-CORE", badge: str = "context", max_age: int = 5, **kw: Any) -> dict[str, Any]:
        return {
            "series_id": sid,
            "name": sid.replace("_", " ").title(),
            "source_entry": "A1",
            "publisher": "fixture",
            "url": "https://example.test",
            "freq": "D",
            "unit": "",
            "verdict": verdict,
            "badge": badge,
            "max_age_days": max_age,
            "resample": kw.get("resample", "last"),
            "lag_note": None,
            "terms": None,
            "evidence": None,
        }

    return [
        row("COMEX_GC_FRONT", badge="arithmetic", max_age=4),
        row("COT_DISAGG_F", max_age=9),
        row("GLD_TONNES"),
        row("FRED_DFII10"),
        row("UST_REAL_10Y"),
        row("DXY_CLOSE", badge="arithmetic"),
        row("USDINR_CLOSE", badge="arithmetic"),
        row("MCX_BASIS_PCT"),
        row("INDIA_PREMIUM_PCT"),
        row("SHANGHAI_PREMIUM_USD"),
        row("COMEX_CARRY_ANN_PCT", badge="arithmetic"),
        row("IBJA_999_PM", max_age=4),
        row("SGE_SHAU_PM", max_age=4),
        row("FX_CNY", badge="arithmetic"),
        row("LBMA_PM_USD"),
        row("WGC_ETF_FLOW_T_GLOBAL", resample="sum"),
        row("FX_EURUSD", badge="arithmetic"),
        row("FX_JPY", badge="arithmetic"),
        row("GVZ_CLOSE"),
        row("XAU_CROSSCHECK", badge="arithmetic"),
        row("CME_BULLETIN_SETTLE", verdict="LINK-ONLY"),
        row("GOLD_IMPORT_DUTY_PCT", badge="arithmetic", max_age=400),
        row("BREEZE_DAILY", verdict="PUBLISH-CONTEXT", badge="arithmetic", max_age=4),   # p.mcx.history (O-8, 6 Nov 2026)
    ]


def mcx_daily_rows() -> list[dict[str, Any]]:
    """gold_mcx_daily (O-8) as data-service serves it: GOLD DEC-26 and FEB-27 Breeze daily bars on every MCX session
    from Mon 28 Sep to Fri 23 Oct 2026 (OI and volume in lots; one session without a volume, as Breeze returned 12 Oct)."""
    out: list[dict[str, Any]] = []
    d, k = date(2026, 9, 28), 0
    while d <= date(2026, 10, 23):
        if specs.is_session_day(d):
            for exp, base, oi0 in (("2026-12-04", 121000.0, 15000), ("2027-02-05", 122300.0, 900)):
                close = base + 180.0 * (k % 4) - 70.0 * k
                out.append({
                    "trade_date": d.isoformat(), "family": "GOLD", "expiry": exp, "open": close - 50, "high": close + 120,
                    "low": close - 140, "close": close, "volume": None if k == 9 else 4000 + 150 * k,
                    "open_interest": oi0 + (40 * k if k % 3 else -25 * k), "source": "breeze_daily", "quality": "broker",
                    "release_at": f"{d.isoformat()}T04:05:00+00:00", "first_seen_at": f"{d.isoformat()}T04:05:00+00:00",
                    "unit": "INR/10g",
                })
            k += 1
        d += timedelta(days=1)
    return out


def series_rows() -> list[dict[str, Any]]:
    """Long rows for /db/gold/series: daily points for the last 420 days incl. a REVISED vintage of FRED_DFII10 (PIT test)."""
    out = []
    d0 = NOW.date()
    for k in range(420, -1, -1):
        d = d0 - timedelta(days=k)
        if d.weekday() >= 5:
            continue
        rel = datetime(d.year, d.month, d.day, 20, 15, tzinfo=timezone.utc).isoformat()
        out.append({"series_id": "FRED_DFII10", "report_date": d.isoformat(), "value": 2.66 - 0.0005 * k, "release_at": rel})
        out.append({"series_id": "DXY_CLOSE", "report_date": d.isoformat(), "value": 99.0 + 0.004 * k, "release_at": rel})
        out.append({"series_id": "USDINR_CLOSE", "report_date": d.isoformat(), "value": 94.9 - 0.002 * k, "release_at": rel})
        out.append({"series_id": "FX_EURUSD", "report_date": d.isoformat(), "value": 1.16 - 0.0001 * k, "release_at": rel})
        out.append({"series_id": "FX_JPY", "report_date": d.isoformat(), "value": 152.0 + 0.01 * k, "release_at": rel})
        out.append({"series_id": "GVZ_CLOSE", "report_date": d.isoformat(), "value": 22.0, "release_at": rel})
        out.append({"series_id": "WGC_ETF_FLOW_T_GLOBAL", "report_date": d.isoformat(), "value": 1.0, "release_at": rel})
        out.append({"series_id": "CME_BULLETIN_SETTLE", "report_date": d.isoformat(), "value": 4000.0, "release_at": rel})
        if k < 30:
            out.append({"series_id": "MCX_BASIS_PCT", "report_date": d.isoformat(), "value": 0.4, "release_at": rel})
            out.append({"series_id": "INDIA_PREMIUM_PCT", "report_date": d.isoformat(), "value": -0.3, "release_at": rel})
            out.append({"series_id": "IBJA_999_PM", "report_date": d.isoformat(), "value": 141630.0, "release_at": rel})
    # the revision: 22 Oct's real yield re-published on 24 Oct with a different value (release_at later)
    out.append(
        {"series_id": "FRED_DFII10", "report_date": "2026-10-22", "value": 2.70, "release_at": "2026-10-24T20:15:00+00:00"}
    )
    return out


def _db_payloads() -> dict[str, Any]:
    today = NOW.date()
    gc = gc_bars()
    etf = [
        {
            "report_date": (today - timedelta(days=k)).isoformat(),
            "fund": "GLD",
            "tonnes": 1045.64 + (3 - k) * 2.0,
            "release_at": None,
        }
        for k in range(60, -1, -1)
        if (today - timedelta(days=k)).weekday() < 5
    ]
    curve = [
        {
            "trade_date": "2026-10-23",
            "exchange": "COMEX",
            "symbol": "GC",
            "expiry": "2026-12-29",
            "settle": 4007.9,
            "open_interest": 300000,
            "source": "yahoo",
            "quality": "proxy",
        },
        {
            "trade_date": "2026-10-23",
            "exchange": "COMEX",
            "symbol": "GC",
            "expiry": "2027-02-24",
            "settle": 4049.0,
            "open_interest": 80000,
            "source": "yahoo",
            "quality": "proxy",
        },
    ]
    events = [
        {"event_date": "2026-11-30", "time_ist": "00:00", "kind": "COMEX_FND", "name": "GCZ26 first notice day", "country": "US"},
        {
            "event_date": "2026-10-28",
            "time_ist": "23:30",
            "kind": "FOMC",
            "name": "FOMC statement",
            "country": "US",
            "impact": "high",
        },
        {"event_date": "2026-11-06", "time_ist": "19:00", "kind": "US_NFP", "name": "Non-Farm Payrolls", "country": "US", "impact": "High"},
        # wave 1c: data-service tags every "FOMC …" Forex-Factory title as kind FOMC — a speech is NOT the next decision
        {"event_date": "2026-10-27", "time_ist": "19:20", "kind": "FOMC", "name": "FOMC Member Hammack Speaks", "country": "US",
         "impact": "Low"},
        {"event_date": "2026-10-30", "time_ist": "18:00", "kind": "US_CPI", "name": "CPI m/m", "country": "US", "impact": "High"},
        {"event_date": "2026-10-26", "time_ist": "08:00", "kind": "US_DATA", "name": "already released today", "country": "US",
         "impact": "Medium"},
    ]
    voi = []
    oi = 400000
    for k in range(40, -1, -1):
        d = today - timedelta(days=k)
        if d.weekday() >= 5:
            continue
        oi += -1500 if k % 3 else 2200
        voi.append(
            {
                "trade_date": d.isoformat(),
                "exchange": "COMEX",
                "product_code": "GC",
                "fut_or_opt": "F",
                "open_interest": oi,
                "oi_change": None,
                "total_volume": 180000 + 5000 * (k % 4),
            }
        )
        voi.append(
            {"trade_date": d.isoformat(), "exchange": "COMEX", "product_code": "OG", "fut_or_opt": "C", "open_interest": 300000}
        )
        voi.append(
            {"trade_date": d.isoformat(), "exchange": "COMEX", "product_code": "OG", "fut_or_opt": "P", "open_interest": 210000}
        )
    return {
        "/db/gold/catalog": {"rows": catalog_rows()},
        "/db/gold/bars": {"rows": gc},
        "/db/gold/cot:F": {"rows": cot_rows("fut")},
        "/db/gold/cot:C": {"rows": cot_rows("com")},
        "/db/gold/etf": {"rows": etf},
        "/db/gold/curve": {"rows": curve},
        "/db/gold/events": {"rows": events},
        "/db/gold/series": {"rows": series_rows()},
        "/db/gold/cme/voi": {"rows": voi},
        "/db/gold/cme/efrp": {"rows": []},
        "/db/gold/fed-path": {"rows": []},
        "/db/gold/brief": {"rows": []},
        "/db/gold/margins": {
            "rows": [
                {
                    "trade_date": "2026-10-23",
                    "exchange": "MCX",
                    "symbol": "GOLD",
                    "expiry": "2026-12-04",
                    "source": "zerodha_nrml",
                    "margin_ccy": 1050000.0,
                    "margin_pct": 7.2,
                }
            ]
        },
        "/db/gold/cme/prf": {"rows": []},
        "/db/gold/mcx/daily": {"rows": mcx_daily_rows(), "source": "breeze_daily", "quality": "broker"},
    }


DB = _db_payloads()
DB_CALLS: list[tuple[str, dict[str, Any]]] = []
# the all-history percentiles data-service computes over 1986→ (cot_metrics.summary): passed through, never recomputed here
COT_SUMMARY: dict[str, Any] = {
    "crowd": {"percentile_all": 50.0, "cot_index_52": 1.0},
    "open_interest": {"total": 402279, "chg": 5934, "pct_rank": 19.5},
    "driver_rule": "data-service rule text (the fixture)",
}


async def _fake_db(path: str, params: dict[str, Any]) -> Any:
    DB_CALLS.append((path, dict(params)))
    if path == "/db/gold/cot":
        if params.get("contract") not in (None, "088691"):
            return {"rows": []}  # no micro-gold rows in the fixture
        key = f"/db/gold/cot:{params.get('fut_or_combined', 'F')}"
        rows = DB[key]["rows"]
        out: dict[str, Any] = {"rows": rows[-int(params.get("weeks", 52)) :]}
        if params.get("fut_or_combined", "F") == "F":  # data-service merges its FULL-panel summary beside the rows
            out.update(COT_SUMMARY)
        return out
    if path == "/db/gold/series":
        ids = set(str(params.get("ids", "")).split(","))
        return {"rows": [r for r in DB[path]["rows"] if r["series_id"] in ids]}
    if path == "/db/gold/curve/history" or (path == "/db/gold/curve" and params.get("exchange") == "MCX"):
        return {"rows": []}
    if path == "/db/gold/mcx/daily":   # data-service filters by family / expiry / from (gold/reads.py mcx_daily)
        rows = [r for r in DB[path]["rows"]
                if (not params.get("family") or r["family"] == params["family"])
                and (not params.get("expiry") or r["expiry"] == params["expiry"])
                and (not params.get("from") or r["trade_date"] >= str(params["from"]))]
        return {**DB[path], "rows": rows, "count": len(rows)}
    if path not in DB:
        raise gold.StoreUnavailable("fixture: no such read (404)")
    return DB[path]


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """No network, pinned clock, empty caches."""
    YAHOO_CALLS.clear()
    DB_CALLS.clear()
    for c in (mcx._cache, gp._cache, gp._settle_cache, gold._ttl):
        c.clear()
    gp._settle_calls.clear()          # the per-key Breeze call cap (wave 1d round 2) starts empty in every test
    gold.STORE.invalidate()
    monkeypatch.setattr(gold, "_db_fetch", _fake_db)
    monkeypatch.setattr(gold, "_now_ist", lambda: NOW)
    monkeypatch.setattr(gp, "_load_mcx_master", lambda: (MASTER, PUBLISHED))
    monkeypatch.setattr(gp, "_yahoo_bars", _fake_yahoo)
    monkeypatch.setattr(gp, "_fred_fetch", _no_rows)
    monkeypatch.setattr(gp, "_headlines_fetch", _no_news)
    monkeypatch.setattr(gp, "_breeze_mcx_quote", lambda expiry: None)
    monkeypatch.setattr(gp, "_breeze_mcx_open", lambda expiry, day: None)
    monkeypatch.setattr(gp, "_refresh_treasury_in_background", lambda: None)
    monkeypatch.setattr(gp, "prefs_triggers", lambda: {"eurusd_trigger": None, "topics": ["Gold"]})
    monkeypatch.setattr(
        mcx,
        "_breeze_quote",
        lambda code, expiry, today, after_open: {"available": False, "quote": None, "reason": "offline test", "attempted": False},
    )
    yield
    for c in (mcx._cache, gp._cache, gp._settle_cache, gold._ttl):
        c.clear()
    gold.STORE.invalidate()


async def _no_rows(series: str) -> list[Any]:
    return []


async def _no_news(client: Any, label: str, query: str, must: str, hours: int) -> list[Any]:
    return []


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(gold.router, prefix="/api/gold")
    app.include_router(gp.router, prefix="/api/commodity")
    app.include_router(mcx.router, prefix="/api/mcx")
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# health: the verdict, the gauges, the lines
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_health_verdict_is_descriptive_and_has_no_score(client: TestClient) -> None:
    r = client.get("/api/gold/health", params={"window": "W"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "score" not in body and "score" not in body["verdict"]
    assert body["verdict"]["line"].endswith(gold.DESCRIBES)
    assert not re.search(r"\b(bullish|bearish|buy|sell)\b", body["verdict"]["line"], re.IGNORECASE)
    keys = [g["key"] for g in body["gauges"]]
    assert keys == ["trend", "real_yield", "dollar", "positioning", "india_basis", "shanghai", "etf", "curve_roll"]
    pos = next(g for g in body["gauges"] if g["key"] == "positioning")
    assert pos["value"] == 104206 and pos["change"] == -2883 and pos["badge"] == "context"
    assert "G-STUDY" in pos["evidence"]
    for g in body["gauges"]:
        assert g["badge"] in ("context", "arithmetic", "heuristic")
        assert g["state"] in ("live", "delayed", "stale", "unavailable")
    assert body["line"].startswith("GOLD · ") and body["line"].endswith("GOLD ›")
    assert body["brf_line"].endswith("GOLD ›") and body["lines"] == {"wei": body["line"], "brf": body["brf_line"]}
    assert r.headers.get("X-Cache") in ("miss", "hit", "stale", "bypass")
    # memoised for 60 s: the second call is served from the TTL cache with the same headers
    r2 = client.get("/api/gold/health", params={"window": "W"})
    assert r2.json()["as_of"] == body["as_of"]


def test_stale_and_unavailable_gauges_contribute_no_clause() -> None:
    gauges = [
        {"key": "trend", "state": "delayed", "change": -2.8, "value": 4007.9},
        {"key": "positioning", "state": "stale", "value": 104206, "change": -2883, "change_pct": -2.7},
        {"key": "india_basis", "state": "unavailable", "value": 0.4},
        {"key": "etf", "state": "delayed", "change": -12.0},
    ]
    v = gold.verdict_sentence(gauges, "W", {"usd_effect_pct": -1.4, "driver_label": "long liquidation"})
    ids = {c["rule_id"] for c in v["clauses"]}
    assert "H3" not in ids and "H4" not in ids and "H6" in ids
    assert v["line"].startswith("WEAK WEEK, DOLLAR-DRIVEN") and v["line"].endswith(gold.DESCRIBES)
    assert "score" not in v
    empty = gold.verdict_sentence([{"key": "trend", "state": "stale", "change": 1.0}], "D", {})
    assert empty["clauses"][0]["rule_id"] == "H0" and empty["line"].endswith(gold.DESCRIBES)


def test_week_and_driver_labels() -> None:
    assert gold._week_label(-2.8, "W") == "WEAK WEEK" and gold._week_label(2.5, "M") == "STRONG MONTH"
    assert gold._week_label(0.2, "D") == "FLAT DAY" and gold._week_label(1.0, "W") == "FIRM WEEK"
    assert gold._driver_word(-2.8, -1.4, 2.0) == "DOLLAR-DRIVEN"  # the dollar explains ≥ 40 % of the move
    assert gold._driver_word(-2.8, -0.2, 8.0) == "YIELD-DRIVEN"  # real yield up 8 bp against gold
    assert gold._driver_word(-2.8, 0.1, 1.0) == "GOLD-SPECIFIC"
    assert gold._driver_word(0.2, -1.0, 9.0) is None  # too small a move to call


def test_brf_line_forms() -> None:
    base = {"verdict": {"headline": "WEAK WEEK, DOLLAR-DRIVEN"}}
    pre = gold.brf_line({**base, "fair": {"fair_value": 144181.0, "gap_vs_settlement": -1898.0, "premium_rupees": 900.0}})
    assert pre.startswith("Gold open: fair ₹144,181 (gap −1,898) · WAIT · WEAK WEEK, DOLLAR-DRIVEN") and pre.endswith("GOLD ›")
    post = gold.brf_line({**base, "fair": {"actual_open": 142058.0, "snapshot_fair": 144938.0, "snapshot_error": -2880.0}})
    assert post.startswith("Gold opened ₹142,058 vs fair ₹144,938 (miss ₹−2,880)")
    hol = gold.brf_line(
        {
            **base,
            "fair": {
                "fair_value": 1.0,
                "mcx_holiday": {"name": "Dussehra", "closure": "morning", "opens_at": "2026-10-20T17:00"},
            },
        }
    )
    assert hol == "Gold: MCX closed (Dussehra, opens 17:00) · GOLD ›"


def test_fair_block_uses_the_cached_fetcher_once_and_no_breeze() -> None:
    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        a = await gold.fair_block()
        b = await gold.fair_block()
        return a, b

    a, b = asyncio.run(run())
    assert YAHOO_CALLS.count("GCZ26.CMX") == 1 and YAHOO_CALLS.count("INR=X") == 1  # one fetch per symbol, shared
    assert a["fair_value"] == b["fair_value"] and a["mcx_live"] is None  # no quote in cache → no Breeze
    assert a["duty_pct"] == 15.0 and a["duty_effective"] == "2026-05-13"
    assert a["settlement_session"] == "2026-10-22" and a["settlement_session_label"] == "Thu 22 Oct settlement"
    assert a["implied_premium_pct"] is not None and a["basis_pct"] is not None  # the deprecated alias rides along
    assert a["badge"] == "arithmetic" and a["comex_symbol"] == "GCZ26.CMX"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# series: PIT as-of, D/W/M resampling, the rendering gate
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_asof_returns_the_vintage_not_the_revision() -> None:
    pts = [
        {"report_date": "2026-10-22", "value": 2.66, "release_at": "2026-10-22T20:15:00+00:00"},
        {"report_date": "2026-10-22", "value": 2.70, "release_at": "2026-10-24T20:15:00+00:00"},
        {"report_date": "2026-10-23", "value": 2.65, "release_at": "2026-10-23T20:15:00+00:00"},
    ]
    asof = datetime(2026, 10, 23, 12, 0, tzinfo=IST)
    assert [p["value"] for p in gold.asof_filter(pts, asof)] == [2.66]  # 23 Oct's own point not public at noon IST
    assert [p["value"] for p in gold.asof_filter(pts, None)] == [2.70, 2.65]  # latest vintage per date


def test_resampling_D_W_M() -> None:
    pts = [
        {"report_date": (date(2026, 9, 28) + timedelta(days=k)).isoformat(), "value": float(k + 1), "release_at": None}
        for k in range(26)
        if (date(2026, 9, 28) + timedelta(days=k)).weekday() < 5
    ]
    assert gold.resample_points(pts, "D") == pts
    w = gold.resample_points(pts, "W")
    assert [p["report_date"] for p in w][:2] == ["2026-10-02", "2026-10-09"] and w[0]["value"] == 5.0 and w[0]["n"] == 5
    assert gold.resample_points(pts, "W", "sum")[0]["value"] == 15.0
    assert gold.resample_points(pts, "W", "mean")[0]["value"] == 3.0
    m = gold.resample_points(pts, "M")
    assert [p["report_date"] for p in m] == ["2026-09-30", "2026-10-31"] and m[0]["value"] == 3.0


def test_series_route_applies_gate_asof_and_freq(client: TestClient) -> None:
    r = client.get("/api/gold/series", params={"ids": "FRED_DFII10,CME_BULLETIN_SETTLE,NOPE", "freq": "W", "from": "2026-09-01"})
    assert r.status_code == 200, r.text
    body = r.json()
    by_id = {s["series_id"]: s for s in body["series"]}
    assert (
        body["freq"] == "W"
        and by_id["FRED_DFII10"]["points"]
        and all(gold._d(p["report_date"]).weekday() == 4 for p in by_id["FRED_DFII10"]["points"])
    )
    assert by_id["CME_BULLETIN_SETTLE"]["published"] is False and by_id["CME_BULLETIN_SETTLE"]["points"] == []
    assert by_id["CME_BULLETIN_SETTLE"]["note"] == "no verdict — not published"
    assert by_id["NOPE"]["points"] == [] and by_id["NOPE"]["freshness"]["state"] == "unavailable"
    # the revision of 22 Oct is invisible as of 23 Oct
    r2 = client.get(
        "/api/gold/series",
        params={"ids": "FRED_DFII10", "from": "2026-10-20", "to": "2026-10-22", "asof": "2026-10-23T12:00:00+05:30"},
    )
    pts = r2.json()["series"][0]["points"]
    assert pts[-1]["report_date"] == "2026-10-22" and pts[-1]["value"] == pytest.approx(2.66 - 0.0005 * 4)
    r3 = client.get("/api/gold/series", params={"ids": "FRED_DFII10", "from": "2026-10-22", "to": "2026-10-22"})
    assert r3.json()["series"][0]["points"][-1]["value"] == 2.70
    assert client.get("/api/gold/series", params={"ids": "X", "asof": "yesterday"}).status_code == 422


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# holiday gating, the session label, the duty leg, the aliases
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_snapshot_and_capture_follow_the_mcx_calendar() -> None:
    from fastapi import HTTPException

    dussehra_morning = datetime(2026, 10, 20, 8, 45, tzinfo=IST)  # morning closure: no 08:45 snapshot
    with pytest.raises(HTTPException) as e:
        gp.snapshot_gate(dussehra_morning, force=False)
    assert e.value.status_code == 409 and "Dussehra" in str(e.value.detail)
    with pytest.raises(HTTPException):
        gp.capture_gate(datetime(2026, 10, 20, 9, 10, tzinfo=IST))  # nothing to capture before 17:00
    gp.capture_gate(datetime(2026, 10, 20, 17, 10, tzinfo=IST))  # the 17:10 capture is fine
    with pytest.raises(HTTPException):
        gp.snapshot_gate(datetime(2026, 10, 2, 8, 45, tzinfo=IST), force=False)  # full holiday
    gp.snapshot_gate(datetime(2026, 10, 26, 8, 45, tzinfo=IST), force=False)
    with pytest.raises(HTTPException):
        gp.snapshot_gate(datetime(2026, 10, 26, 9, 5, tzinfo=IST), force=False)  # already open
    gp.snapshot_gate(datetime(2026, 10, 26, 9, 5, tzinfo=IST), force=True)


def test_session_label_comes_from_the_session_never_the_file_date() -> None:
    assert gp.previous_session(date(2026, 10, 23)) == date(2026, 10, 22)
    assert gp.session_label(date(2026, 10, 22)) == "Thu 22 Oct settlement"
    assert gp.previous_session(date(2026, 10, 26)) == date(2026, 10, 23)  # Monday's file → Friday
    assert gp.previous_session(date(2026, 10, 5)) == date(2026, 10, 1)  # Fri 2 Oct full holiday → Thu 1 Oct


def test_duty_leg_is_dated_and_the_alias_survives_one_release() -> None:
    m = gp.fair_open(146079, 4060.4, 4007.9, 94.90, 94.93, duty_pct=15.0)
    landed = 4060.4 * 94.90 / gp.GRAMS_PER_TROY_OZ * 10
    assert m["landed"] == round(landed, 0) and m["duty_pct"] == 15.0
    assert m["duty_paid_landed"] == round(landed * 1.15, 0)
    assert m["basis_pct"] == pytest.approx((146079 / (landed * 1.15) - 1) * 100, abs=0.02)
    assert m["implied_premium_pct"] == pytest.approx((146079 / landed - 1) * 100, abs=0.02)  # deprecated alias
    assert gp.duty_rate()["effective"] == "2026-05-13" and "16/2026" in gp.duty_rate()["notification"]
    assert gp.DUTY_HISTORY == (("2024-07-24", 6.0), ("2026-05-13", 15.0))


def test_fair_route_and_the_commodity_alias_agree(client: TestClient) -> None:
    a = client.get("/api/gold/fair")
    b = client.get("/api/commodity/gold-preopen")
    assert a.status_code == 200 and b.status_code == 200, (a.text, b.text)
    fa, fb = a.json(), b.json()
    assert fa["baseline"]["session_label"] == "Thu 22 Oct settlement" == fb["baseline"]["session_label"]
    assert fa["verdict"]["badge"] == "heuristic" and fa["accuracy"]["days"] == 0 and fa["holiday"] is None
    assert fa["duty"]["pct"] == 15.0 and fa["model"]["fair_open"] == fb["model"]["fair_open"]
    assert fa["badge"] == "arithmetic" and fa["freshness"]["state"] in ("live", "delayed")
    c = client.get("/api/gold/fair", params={"contract": "GOLDM"})
    assert c.status_code == 200 and c.json()["contract_fair"]["contract"] == "GOLDM"
    assert client.get("/api/gold/fair", params={"contract": "SILVER"}).status_code == 422
    assert client.get("/api/gold/log").status_code == 200 and client.get("/api/commodity/gold-preopen/log").status_code == 200


def test_log_actual_writes_the_row(client: TestClient) -> None:
    r = client.post("/api/gold/log/actual", json={"date": "2026-10-23", "open": 142058})
    assert r.status_code == 200 and r.json()["actual_open"] == 142058.0
    rows = client.get("/api/gold/log").json()["rows"]
    assert rows[0]["date"] == "2026-10-23" and rows[0]["stale_baseline"] is False and "inputs_json" in rows[0]


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# contracts (GOLDTEN), curve, positioning, COT
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_contracts_include_goldten_with_economics(client: TestClient) -> None:
    r = client.get("/api/gold/contracts")
    assert r.status_code == 200, r.text
    body = r.json()
    codes = [f["code"] for f in body["families"]]
    assert codes[:5] == ["GOLD", "GOLDM", "GOLDTEN", "GOLDGUINEA", "GOLDPETAL"]
    ten = next(f for f in body["families"] if f["code"] == "GOLDTEN")
    assert (
        ten["lot"] == "10 g" and ten["purity"] == "999" and "last calendar day" in ten["expiry_rule"] and ten["tick_value"] == 1.0
    )
    assert (
        ten["breeze_code"] == "GOLDTE"
        and ten["expiries"][0]["expiry"] == "2026-10-30"
        and ten["expiries"][0]["source"] == "observed"
    )
    assert ten["expiries"][0]["oi"] == 25655 and ten["hedge_ratio_oz"] == pytest.approx(0.3215, abs=0.001)
    gold_f = next(f for f in body["families"] if f["code"] == "GOLD")
    dec = gold_f["expiries"][0]
    assert dec["expiry"] == "2026-12-04" and dec["comex_matched"] == "GCZ26.CMX" and dec["margin_source"] == "zerodha_nrml"
    # ONE carry convention on the page (C-DATA-16): annualised vs the FRONT, as /curve — the front row itself carries none
    feb = gold_f["expiries"][1]
    assert dec["margin_pct"] == 7.2 and dec["margin_date"] == "2026-10-23" and dec["carry_pct"] is None
    assert feb["carry_pct"] == gold.annualised_carry_pct(dec["settle"], feb["settle"], (date(2027, 2, 5) - date(2026, 12, 4)).days)
    assert feb["carry_convention"].startswith("annualised vs the front")
    assert gold_f["round_trip"]["pct"] < 0.05 and gold_f["one_pct_move_inr"] == round(146080 * 100 / 100, 0)
    assert body["master"]["session_label"] == "Thu 22 Oct settlement" and "margin_pct" in body["diff_keys"]
    assert body["other_exchanges"][0]["available"] is False
    assert client.get("/api/gold/contracts", params={"exchange": "COMEX"}).json()["comex_spec"] is None  # prf not stored


def test_curve_points_and_carry() -> None:
    pts = gold.curve_points(DB["/db/gold/curve"], NOW.date())
    assert [p["expiry"] for p in pts] == ["2026-12-29", "2027-02-24"] and pts[0]["spread_vs_front"] == 0.0
    assert pts[1]["spread_vs_front"] == pytest.approx(41.1, abs=0.01)
    assert pts[1]["annualised_carry_pct"] == pytest.approx((4049.0 / 4007.9 - 1) * 365 / 57 * 100, abs=0.01)
    assert gold.annualised_carry_pct(4007.9, 4049.0, 57) == pts[1]["annualised_carry_pct"]
    assert gold.annualised_carry_pct(4007.9, None, 57) is None


def test_curve_route_mcx_carries_the_basis_block(client: TestClient) -> None:
    r = client.get("/api/gold/curve", params={"exchange": "MCX"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["points"] == []
        and body["basis"]["duty_pct"] == 15.0
        and body["basis"]["mcx_front_session_label"] == "Thu 22 Oct settlement"
    )
    assert body["basis"]["basis_pct"] is not None and body["price_label"].startswith("ICICI band-midpoint")
    c = client.get("/api/gold/curve", params={"exchange": "COMEX"}).json()
    assert c["points"][0]["flags"] == ["PROXY", "LAST TRADE"] and "last trade" in c["price_label"]


def test_cot_from_the_20_oct_report(client: TestClient) -> None:
    r = client.get("/api/gold/cot", params={"weeks": 52})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["latest"]["report_date"] == "2026-10-20" and body["latest"]["stale"] is False
    assert body["open_interest"]["total"] == 402279 and body["open_interest"]["chg"] == 5934
    mm = next(g for g in body["groups"] if g["key"] == "mm")
    assert mm["long"] == 120970 and mm["short"] == 16764 and mm["net"] == 104206
    assert mm["chg_long"] == -3777 and mm["chg_short"] == -894 and mm["chg_net"] == -2883
    assert mm["who_did"] == ["closed 3,777 longs", "covered 894 shorts"]
    assert mm["net_pct_oi"] == pytest.approx(25.9, abs=0.1) and mm["net_moz"] == pytest.approx(10.42, abs=0.01)
    assert body["driver_label"] == "long liquidation" and body["week_price_chg_pct"] < 0
    assert body["quadrant_label"] == "short build-up"  # price down, OI up
    assert body["crowd"]["label"] == gold.CROWD_LABEL and body["crowd"]["cot_index_52"] is not None
    assert body["badge"] == "context" and "does not forecast" in body["evidence"] and body["footer"] == gold.COT_FOOTER
    assert len(body["history"]) == 52 and body["history"][-1]["mm_net"] == 104206
    assert body["options_overlay"]["mm_net_options_only"] is not None and "combined OI" in body["options_overlay"]["line"]
    assert body["drawer"]["identity_check"] in (True, None) and body["drawer"]["raw_block_url"].endswith("deacmxsf.htm")
    assert {d["span"] for d in body["decomposition"]} <= {"since the 2-year low", "since the high"}
    # the NEXT release (after the current report's own release), as PLAN a.6 p.hero prints it — not the one just past
    latest = body["latest"]
    assert latest["release_ist"] == "Sat 24 Oct 01:00 IST" and latest["next_report_date"] == "2026-10-27"  # 15:30 ET Fri
    assert latest["next_release_ist"] == "Sat 31 Oct 01:00 IST" and latest["next_release_at"] == "2026-10-31T01:00+05:30"
    assert datetime.fromisoformat(latest["next_release_at"]) > datetime.fromisoformat(latest["release_at"])
    assert latest["next_release_source"] == "rule"
    assert all(k in body["groups"][0] for k in ("pct_oi_long", "pct_oi_short", "traders_long"))
    assert re.search(r"\b(bullish|bearish)\b", r.text, re.IGNORECASE) is None


def test_cot_digest_composes_from_the_payload(client: TestClient) -> None:
    """The controller's Saturday line (scripts/master_controller.compose_cot_digest) reads this shape."""
    pytest.importorskip("apscheduler", reason="master_controller imports apscheduler")
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import master_controller as mc
    except Exception as exc:  # noqa: BLE001 — the controller pulls in Telegram/scheduler deps; skip when absent
        pytest.skip(f"master_controller not importable here: {type(exc).__name__}")
    line = mc.compose_cot_digest(client.get("/api/gold/cot", params={"weeks": 4}).json())
    # `release_at` carries the IST offset now (C-DATA-6/20): Fri 15:30 ET IS Sat 24 Oct in IST, the clock the digest keeps
    assert line.startswith("COT 20 Oct (Tue positions, released Sat 24 Oct)") and "funds net +104.2k (−2.9k w/w)" in line
    assert "long liquidation" in line and "OI 402,279 (+5,934)" in line and line.endswith("explains the week — does not forecast")
    assert "next Sat 31 Oct 01:00 IST" in line, "the digest names the NEXT release, not the one it reports"


def test_cot_degrades_when_nothing_is_stored(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty(path: str, params: dict[str, Any]) -> Any:
        return {"rows": []}

    monkeypatch.setattr(gold, "_db_fetch", empty)
    r = client.get("/api/gold/cot")
    assert r.status_code == 200 and r.json()["ok"] is False and r.json()["error_info"]["code"] == "state"
    assert r.json()["freshness"]["state"] == "unavailable"


def test_driver_label_rule_matches_g_study() -> None:
    """The magnitude-aware rule (wave 1c, mirrored from data-service driver_rule.py): the label is the BIGGER leg."""
    assert gold.driver_label(-3777, -894, -0.8) == "long liquidation"
    assert gold.driver_label(5000, -1000, 1.2) == "new longs"
    assert gold.driver_label(500, -3000, 1.2) == "short covering"
    assert gold.driver_label(-500, 200, 1.2) == "funds sold into it"
    assert gold.driver_label(-100, 4000, -1.0) == "new shorts"
    assert gold.driver_label(2000, 100, -1.0) == "funds bought the dip"  # was 'new shorts' (any new short on a down week)
    assert gold.driver_label(1538, 182, -1.64) == "funds bought the dip"  # the 27 Oct 2026 week the critics caught
    assert gold.driver_label(2000, -100, -1.0) == "funds bought the dip"
    assert gold.driver_label(0, 0, 0.0) is None and gold.driver_label(None, 1, 1.0) is None  # no price change → no word
    assert gold.who_did(0, 0) == ["no change"] and gold.who_did(1200, 300) == ["new 1,200 longs", "new 300 shorts"]
    assert gold.quadrant_label(1.0, 10) == "long build-up" and gold.quadrant_label(-1.0, 10) == "short build-up"
    assert gold.quadrant_label(1.0, -10) == "short covering" and gold.quadrant_label(-1.0, -10) == "long unwinding"


def test_positioning_daily_comex_tape_and_mechanical_flag(client: TestClient) -> None:
    r = client.get("/api/gold/positioning/daily", params={"exchange": "COMEX", "days": 30})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] and body["rows"][-1]["symbol_or_product"] in ("GC", "OG:C", "OG:P")
    tape = body["quadrant_tape"]
    assert tape and all(t["label"] in ("long build-up", "short build-up", "short covering", "long unwinding", None) for t in tape)
    assert body["put_call_oi_ratio"] == 0.7 and body["roll"]["front"] == "DEC-26" and body["roll"]["next"] == "FEB-27"
    assert body["roll"]["days_to_tender_or_fnd"] == (date(2026, 11, 30) - NOW.date()).days and body["since"] is not None
    assert body["badge"] == "context" and "folklore" in body["evidence"]
    assert body["freshness"]["state"] == "delayed"
    m = client.get("/api/gold/positioning/daily", params={"exchange": "MCX"}).json()
    assert m["exchange"] == "MCX" and m["rows"] == [] and m["badge"] == "arithmetic"


def test_positioning_mcx_builder_from_curve_rows() -> None:
    rows = []
    for k, (settle, oi_dec, oi_feb) in enumerate(((146000, 16000, 500), (146500, 16400, 520), (146200, 16100, 600))):
        d = date(2026, 10, 21) + timedelta(days=k)
        rows.append(
            {
                "trade_date": d.isoformat(),
                "exchange": "MCX",
                "symbol": "GOLD",
                "expiry": "2026-12-04",
                "settle": settle,
                "open_interest": oi_dec,
                "quality": "proxy",
            }
        )
        rows.append(
            {
                "trade_date": d.isoformat(),
                "exchange": "MCX",
                "symbol": "GOLD",
                "expiry": "2027-02-05",
                "settle": settle + 1100,
                "open_interest": oi_feb,
                "quality": "proxy",
            }
        )
    out = gold.build_positioning_mcx(rows, date(2026, 10, 26))
    assert out["since"] == "2026-10-21" and len(out["rows"]) == 6
    assert out["quadrant_tape"][1]["label"] == "long build-up" and out["quadrant_tape"][2]["label"] == "long unwinding"
    assert out["quadrant_tape"][2]["doi"] == (16100 - 16400) + (600 - 520)
    assert (
        out["roll"]["front"] == "DEC-26"
        and out["roll"]["ratio"] == round(16100 / 600, 2)
        and out["roll"]["tender_start"] == "2026-12-01"  # the 1st of the expiry month (contract spec), not expiry − 4 (C-TRADER-28)
        and out["roll"]["days_unit"] == "calendar days"
    )


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# premiums, flows, macro, calendar, catalog, brief, learn, overview, invalidate
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_premiums_ladder_and_fineness_adjustment(client: TestClient) -> None:
    r = client.get("/api/gold/premiums")
    assert r.status_code == 200, r.text
    body = r.json()
    steps = [s["step"] for s in body["india"]["ladder"]]
    assert steps == ["comex", "usdinr", "landed", "duty", "duty_paid", "ibja", "mcx"]
    # ONE premium at ONE clock: the stored fix-minute INDIA_PREMIUM_PCT (−0.3 in the fixture), never the PM fix divided by a
    # landed price computed now (C-TRADER-4 / C-BEGINNER-2 / C-DATA-11)
    duty_paid = next(s for s in body["india"]["ladder"] if s["step"] == "duty_paid")["value"]
    assert body["india"]["premium_pct"] == -0.3 and body["india"]["premium_date"] == NOW.date().isoformat()
    assert body["india"]["premium_pct"] != pytest.approx((141630 / (duty_paid * 999 / 995) - 1) * 100, abs=0.01)
    assert "fix" in body["india"]["premium_clock"] and body["india"]["live_basis"] is None
    ibja_step = next(s for s in body["india"]["ladder"] if s["step"] == "ibja")
    assert ibja_step["clock"] == "fix" and "−0.30 %" in ibja_step["label"] and duty_paid_step_is_now(body)
    assert "16/2026" in body["india"]["duty"]["notification"] and body["india"]["duty"]["history"][-1]["pct"] == 15.0
    assert body["india"]["badge"] == {"ladder": "arithmetic", "premium": "context"}
    assert body["shanghai"]["sge_pm_cny_g"] is None and body["shanghai"]["freshness"]["state"] == "unavailable"
    assert body["reference"]["reuters_url"].startswith("https://www.reuters.com")


def duty_paid_step_is_now(body: dict[str, Any]) -> bool:
    step = next(s for s in body["india"]["ladder"] if s["step"] == "duty_paid")
    return step["clock"] == "now" and str(step["ts"]).endswith("+05:30")


def test_flows_shape(client: TestClient) -> None:
    r = client.get("/api/gold/flows", params={"months": 12})
    assert r.status_code == 200, r.text
    body = r.json()
    gld = next(e for e in body["etf"] if e["fund"] == "GLD")
    assert (
        gld["tonnes"] == pytest.approx(1051.64) and gld["chg_1d"] == 6.0 and len(gld["cumulative_30d"]) == 30
    )  # Fri → Mon: 3 × 2 t
    assert body["wgc_weekly"] and body["wgc_weekly"][-1]["region"] == "OTHER" or body["wgc_weekly"][0]["region"] == "GLOBAL"
    assert body["otc"]["efp"]["today_rt"] is None and body["rbi"]["usd_mn"] is None and body["badge"] == "context"
    assert "never re-served" in body["attribution"] and body["freshness"]["etf"]["state"] == "delayed"


def test_macro_drivers_kgx_and_move(client: TestClient) -> None:
    r = client.get("/api/gold/macro", params={"window": "W"})
    assert r.status_code == 200, r.text
    body = r.json()
    keys = [d["key"] for d in body["drivers"]]
    assert keys[:4] == ["real_10y", "nominal_2y", "breakeven_10y", "dxy"] and "gld_t" in keys
    ry = next(d for d in body["drivers"] if d["key"] == "real_10y")
    assert ry["tag"] in ("supportive", "headwind") and ry["rule"].startswith("falling = supportive") and ry["badge"] == "context"
    assert body["kgx"]["period"] == "W" and body["kgx"]["badge"] == "arithmetic"
    if body["kgx"]["total_pct"] is not None and body["kgx"]["usd_effect_pct"] is not None:
        assert body["kgx"]["pure_gold_pct"] == pytest.approx(body["kgx"]["total_pct"] - body["kgx"]["usd_effect_pct"], abs=0.01)
    inr = next(c for c in body["currencies"] if c["ccy"] == "INR")
    assert inr["unit"].startswith("₹/10 g") and inr["price"] > 100000
    assert (
        body["move"]["sigma_day_pct"] == pytest.approx(22 / 252**0.5, abs=0.01)
        and body["move"]["per_lot"]["GOLD"] > body["move"]["per_lot"]["GOLDM"]
    )
    assert body["fed"]["next_fomc_ist"].startswith("2026-10-28") and body["fed"]["after_mcx_close"] is True
    assert (
        any(e["kind"] == "FOMC" for e in body["calendar"]) and body["driver_health"]["betas_by_regime"][-1]["regime"] == "2022–26"
    )
    assert "score" not in body and body["badge"] == "context"


def test_kgx_split_identity() -> None:
    gold_pts = [{"report_date": "2026-10-19", "value": 4100.0}, {"report_date": "2026-10-26", "value": 4018.0}]
    fx = {
        "FX_EURUSD": [{"report_date": "2026-10-19", "value": 1.17}, {"report_date": "2026-10-26", "value": 1.16}],
        "FX_JPY": [{"report_date": "2026-10-19", "value": 150.0}, {"report_date": "2026-10-26", "value": 152.0}],
        "USDINR_CLOSE": [{"report_date": "2026-10-19", "value": 94.5}, {"report_date": "2026-10-26", "value": 94.93}],
    }
    k = gold.kgx_split(gold_pts, fx, 7)
    assert k["total_pct"] == pytest.approx(-2.0, abs=0.01) and k["usd_effect_pct"] < 0  # dollar up → negative effect
    assert k["pure_gold_pct"] == pytest.approx(k["total_pct"] - k["usd_effect_pct"], abs=0.001)
    assert k["inr_effect_pct"] == pytest.approx((94.93 / 94.5 - 1) * 100, abs=0.01) and set(k["weights"]) == {
        "FX_EURUSD",
        "FX_JPY",
    }


def test_calendar_merges_stored_and_computed_rows(client: TestClient) -> None:
    r = client.get("/api/gold/calendar", params={"days": 45})
    assert r.status_code == 200, r.text
    ev = r.json()["events"]
    kinds = {e["kind"] for e in ev}
    assert {"FOMC", "US_NFP", "COMEX_FND", "MCX_EXPIRY", "MCX_HOLIDAY", "COT_RELEASE", "MCX_SPECIAL"} <= kinds
    assert any(e["name"] == "MCX GOLD DEC-26 expiry" and e["event_date"] == "2026-12-04" for e in ev)
    assert any("Guru Nanak" in e["name"] for e in ev) and all("days" in e for e in ev)
    fomc = next(e for e in ev if e["kind"] == "FOMC")
    assert fomc["after_close"] is False and fomc["in_session"] is True and fomc["days"] == 2
    cot = next(e for e in ev if e["kind"] == "COT_RELEASE")
    assert cot["event_date"] == "2026-10-31" and cot["time_ist"] == "01:00"
    assert ev == sorted(ev, key=lambda e: (e["event_date"], e.get("time_ist") or ""))


def test_catalog_brief_and_learn(client: TestClient) -> None:
    c = client.get("/api/gold/catalog").json()
    assert c["count"] == len(catalog_rows()) and c["verdicts"]["LINK-ONLY"] == 1 and c["badges"]["signal"] == 0
    b = client.get("/api/gold/brief").json()
    assert b["available"] is False
    g = client.get("/api/gold/learn/glossary", params={"q": "contango"}).json()
    assert g["count"] >= 129 and g["terms"] and g["terms"][0]["term"].lower().startswith("contango")
    assert g["dangling_see_also"] == []
    t = client.get("/api/gold/learn/tooltips").json()
    assert t["count"] >= 90 and isinstance(t["tooltips"], dict) and "h.verdict" in t["panels"]
    assert client.get("/api/gold/learn/glossary", params={"q": "x" * 81}).status_code == 422


def test_overview_frame(client: TestClient) -> None:
    r = client.get("/api/gold/overview", params={"contract": "GOLD"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["contract"]["comex_matched"] == "GCZ26.CMX"
        and body["contract"]["expiry"] == "2026-12-04"
        and body["contract"]["comex_front"] == "GC=F"
    )
    s = body["strip"]
    assert s["comex_live"] == COMEX_NOW and s["usdinr"] == INR_NOW and s["cot_mm_net"] == 104206 and s["cot_mm_chg"] == -2883
    assert s["mcx_settle_session_label"] == "Thu 22 Oct settlement" and s["real_10y"] == pytest.approx(2.66, abs=0.01)
    assert set(s["instruments"]) == {"spot", "front", "matched", "mcx"} and len({*s["instruments"].values()}) == 4
    assert body["health"]["verdict"]["line"].endswith(gold.DESCRIBES) and "score" not in body["health"]
    assert body["quote"]["available"] is False and body["session"]["mcx"]["is_open"] is True and "comex" in body["session"]
    assert body["brief"]["available"] is False and body["calendar"] and body["freshness"]["cot"]["state"] == "delayed"
    assert "_served" not in body
    assert client.get("/api/gold/overview", params={"contract": "COPPER"}).status_code == 422
    assert client.get("/api/gold/overview", params={"expiry": "soon"}).status_code == 422


def test_invalidate_clears_the_stores(client: TestClient) -> None:
    client.get("/api/gold/health")
    assert len(gold._ttl) > 0
    r = client.post("/api/gold/invalidate")
    assert r.status_code == 200 and r.json()["invalidated"] == "all" and len(gold._ttl) == 0 and len(gold.STORE) == 0


def test_bars_settle_line_matches_the_symbols_delivery_month(client: TestClient) -> None:
    """The matched-month chart gets ITS month's line (GCG27 → FEB-27), never the front's; an unstored month gets none."""
    feb = client.get("/api/gold/bars", params={"symbol": "GCG27.CMX", "interval": "1d"}).json()
    assert feb["matched_last"]["value"] == 4049.0 and feb["matched_last"]["label"].startswith("FEB-27")
    assert feb["matched_last"]["is_settlement"] is False and "not a settlement" in feb["matched_last"]["label"]
    dec = client.get("/api/gold/bars", params={"symbol": "GCZ26.CMX", "interval": "1d"}).json()
    assert dec["matched_last"]["value"] == 4007.9 and dec["matched_last"]["label"].startswith("DEC-26")
    assert client.get("/api/gold/bars", params={"symbol": "GCH27.CMX", "interval": "1d"}).json()["matched_last"] is None
    # the dashed line is the PREVIOUS session's stored daily close, never the live last (C-TRADER-2 / C-TRADER-17): the
    # fixture's curve points are Yahoo last trades, so none of them is a settlement line
    assert dec["settle_line"]["is_settlement"] is False and "close (Yahoo daily bar)" in dec["settle_line"]["label"]
    assert dec["settle_line"]["value"] == dec["prev_close"]["close"] and dec["prev_close"]["date"] < dec["day"]
    assert gold.symbol_expiry_month("GCZ26.CMX") == (2026, 12) and gold.symbol_expiry_month("GC=F") is None
    assert gold.symbol_expiry_month("INR=X") is None and gold.symbol_expiry_month("GCQ27") == (2027, 8)


def test_bars_route_reads_the_store_only(client: TestClient) -> None:
    r = client.get("/api/gold/bars", params={"symbol": "GC=F", "interval": "1d"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bars"] and body["instrument"].startswith("COMEX front GC1") and body["matched_last"]["value"] == 4007.9
    assert body["settle_line"]["quality"] == "close" and body["daily_closes"] and body["daily_closes"][-1]["partial"] is False
    assert [b["name"] for b in body["sessions"]][-1] == "MCX" and body[
        "last"
    ] is None  # nothing in the SWR cache: no fetch started
    assert YAHOO_CALLS == []


def test_freshness_states() -> None:
    assert gold.freshness(None, 4, "x")["state"] == "unavailable"
    assert gold.freshness((NOW - timedelta(days=1)).isoformat(), 4, "x")["state"] == "delayed"
    assert gold.freshness((NOW - timedelta(days=9)).isoformat(), 4, "x")["state"] == "stale"
    assert gold.freshness(NOW.isoformat(), 4, "x", live=True)["state"] == "live"
    assert gold.freshness("2026-10-23", 4, "x")["as_of"] == "2026-10-23"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# T9: no new Yahoo fetcher; T1: event-loop purity of the new routes
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_gold_router_has_no_yahoo_fetcher_of_its_own() -> None:
    src = Path(gold.__file__).read_text(encoding="utf-8")
    assert "finance.yahoo.com" not in src and "_yahoo_bars(" not in src
    assert not re.search(r"(?<![\w.])_yahoo_bars_cached", src)  # only ever through gold_preopen's fetcher
    assert not re.search(r"^\s*(async )?def _yahoo", src, re.MULTILINE)  # no fetcher defined here
    assert "BreezeConnect" not in src and "get_quotes" not in src  # Breeze only via mcx's cached path
    for host in ("cmegroup.com", "mcxindia.com", "kitco.com", "prices.lbma.org.uk", "stooq", "goldprice.org", "investing.com"):
        assert host not in src.replace("www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html", ""), (
            host
        )  # FedWatch is a LINK


def _health_latencies_while(client: TestClient, path: str, params: dict[str, Any], n: int = 20) -> list[float]:
    done = threading.Event()

    def _heavy() -> None:
        try:
            client.get(path, params=params)
        finally:
            done.set()

    t = threading.Thread(target=_heavy, daemon=True)
    t.start()
    time.sleep(0.05)
    lat = []
    for _ in range(n):
        t0 = time.perf_counter()
        assert client.get("/health").status_code == 200
        lat.append(time.perf_counter() - t0)
    done.wait(timeout=15)
    t.join(timeout=15)
    return sorted(lat)


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/gold/health", {}),
        ("/api/gold/overview", {}),
        ("/api/gold/cot", {}),
        ("/api/gold/contracts", {}),
        ("/api/gold/learn/glossary", {"q": "basis"}),
        ("/api/gold/macro", {}),
        ("/api/gold/fair", {}),
    ],
)
def test_new_routes_keep_the_event_loop_free(monkeypatch: pytest.MonkeyPatch, path: str, params: dict[str, Any]) -> None:
    """A slow data-service (0.5 s per read, awaited) and a slow master loader (0.4 s, blocking in a thread) must not stall
    /health."""

    async def slow_db(p: str, q: dict[str, Any]) -> Any:
        await asyncio.sleep(0.5)
        return await _fake_db(p, q)

    monkeypatch.setattr(gold, "_db_fetch", slow_db)
    monkeypatch.setattr(gp, "_load_mcx_master", lambda: (time.sleep(0.4), (MASTER, PUBLISHED))[1])
    monkeypatch.setattr(
        gold, "_load_learn", lambda name: (time.sleep(0.3), {"terms": [{"term": "basis", "short": "x"}], "tooltips": {}})[1]
    )
    with TestClient(_app()) as client:
        lat = _health_latencies_while(client, path, params)
    p95 = lat[max(0, round(0.95 * len(lat)) - 1)]
    assert p95 < 0.1, f"/health p95 {p95 * 1000:.0f} ms while {path} ran"


# ── wave 1b (fix round): the adversarial check's items, each with a negative control ─────────────────────────


def test_cot_release_calendar_is_holiday_aware() -> None:
    """Friday 15:30 ET; the Monday after a federal holiday that falls Wed–Fri of the report week (the CFTC's published
    2026 schedule is pinned); a Monday holiday does NOT shift the Friday; IST labels follow US DST."""
    assert gold.cot_release_date(date(2026, 10, 20)) == (date(2026, 10, 23), "rule")  # a plain week (EDT)
    assert gold.cot_release_at_ist(date(2026, 10, 20)).isoformat(timespec="minutes") == "2026-10-24T01:00+05:30"
    assert gold.cot_release_date(date(2026, 11, 3)) == (date(2026, 11, 6), "rule")  # first week on EST
    assert gold.cot_release_label(gold.cot_release_at_ist(date(2026, 11, 3))) == "Sat 07 Nov 02:00 IST"
    assert gold.cot_release_date(date(2026, 11, 10)) == (date(2026, 11, 16), "published")  # Veterans Day Wed 11 Nov
    assert gold.cot_release_label(gold.cot_release_at_ist(date(2026, 11, 10))) == "Tue 17 Nov 02:00 IST"
    assert gold.cot_release_date(date(2026, 11, 24)) == (date(2026, 11, 30), "published")  # Thanksgiving
    assert gold.cot_release_date(date(2026, 12, 22)) == (date(2026, 12, 28), "published")  # Christmas Friday
    assert gold.cot_release_date(date(2026, 6, 16)) == (date(2026, 6, 22), "published")  # Juneteenth Friday
    assert gold.cot_release_date(date(2026, 1, 20)) == (date(2026, 1, 23), "rule")  # MLK Monday: no shift (negative)
    assert gold.cot_release_date(date(2027, 11, 23)) == (date(2027, 11, 29), "rule")  # 2027 Thanksgiving by the rule alone
    assert gold.cot_release_date(date(2027, 7, 6)) == (date(2027, 7, 9), "rule")  # 4 July 2027 is a Sunday → Mon 5th: before Tue
    # the NEXT release is after the current report's release AND after now (a stale store still names an upcoming one)
    nxt = gold.next_cot_release(date(2026, 10, 20), NOW, "2026-10-23T19:30:13Z")
    assert nxt == {"report_date": "2026-10-27", "at": "2026-10-31T01:00+05:30", "ist": "Sat 31 Oct 01:00 IST", "source": "rule"}
    stale = gold.next_cot_release(date(2026, 10, 20), datetime(2026, 11, 4, 22, 0, tzinfo=IST), "2026-10-23T19:30:13Z")
    assert stale["report_date"] == "2026-11-03" and stale["ist"] == "Sat 07 Nov 02:00 IST"
    hol = gold.next_cot_release(date(2026, 11, 3), datetime(2026, 11, 7, 3, 0, tzinfo=IST), "2026-11-06T20:30:00Z")
    assert hol["report_date"] == "2026-11-10" and hol["ist"] == "Tue 17 Nov 02:00 IST" and hol["source"] == "published"


def test_cot_release_calendar_matches_data_service() -> None:
    """ui-api's calendar (the NEXT release) and data-service's (the stored release_at, gold/pit.py) must never disagree."""
    ds = REPO / "services" / "data-service"
    sys.path.insert(0, str(ds))
    try:
        import importlib

        pit = importlib.import_module("gold.pit")
    except Exception as exc:  # noqa: BLE001 — the data-service package pulls in duckdb/pandas; skip where absent
        pytest.skip(f"data-service gold.pit not importable here: {type(exc).__name__}")
    finally:
        sys.path.remove(str(ds))
    d = date(2024, 1, 2)
    mismatches = []
    while d <= date(2027, 12, 28):
        if d not in pit.COT_RELEASE_OVERRIDES:  # the shutdown / cyber catch-up tables are history, not a schedule
            ours, theirs = gold.cot_release_date(d), pit.cot_release_date(d)
            if ours[0] != theirs[0]:
                mismatches.append((d.isoformat(), ours[0].isoformat(), theirs[0].isoformat()))
        d += timedelta(days=7)
    assert mismatches == []
    assert gold.COT_RELEASE_PUBLISHED == pit.COT_RELEASE_PUBLISHED


def test_calendar_cot_release_rows_carry_the_holiday_shift(client: TestClient) -> None:
    r = client.get("/api/gold/calendar", params={"days": 30})
    cot = [e for e in r.json()["events"] if e["kind"] == "COT_RELEASE"]
    by_date = {e["event_date"]: e for e in cot}
    assert "2026-10-31" in by_date and by_date["2026-10-31"]["time_ist"] == "01:00"
    assert "2026-11-07" in by_date and by_date["2026-11-07"]["time_ist"] == "02:00"  # EST from 1 Nov
    assert "2026-11-17" in by_date and "holiday" in by_date["2026-11-17"]["detail"]  # Veterans Day → Mon 16 Nov ET
    assert "2026-11-14" not in by_date, "the Friday the CFTC does not publish on must not be listed"


def test_health_h3_fund_driver_label_equals_cot(client: TestClient) -> None:
    """The verdict's H3 clause and the POSITIONING hero apply the G-STUDY §5.2 rule to the same week's price."""
    cot = client.get("/api/gold/cot", params={"weeks": 4}).json()
    health = client.get("/api/gold/health").json()
    pos = next(g for g in health["gauges"] if g["key"] == "positioning")
    assert pos["driver_label"] == cot["driver_label"] == "long liquidation"
    assert pos["week_price_chg_pct"] == cot["week_price_chg_pct"]
    h3 = next(c for c in health["verdict"]["clauses"] if c["rule_id"] == "H3")
    assert "long liquidation" in h3["text"]
    # negative control: without the week's price there is NO word (the rule needs the direction); with it, a dip-buy week
    assert gold.driver_label(2000, -100, None) is None and gold.driver_label(2000, -100, -1.0) == "funds bought the dip"


def test_cot_combined_mode_keeps_the_overlay_sign_and_micro_mode(client: TestClient) -> None:
    f = client.get("/api/gold/cot", params={"weeks": 4, "fut_or_combined": "F"}).json()
    DB_CALLS.clear()
    c = client.get("/api/gold/cot", params={"weeks": 4, "fut_or_combined": "C"}).json()
    assert c["fut_or_combined"] == "C" and c.get("ok") is not False
    assert c["options_overlay"]["mm_net_options_only"] == f["options_overlay"]["mm_net_options_only"]
    assert f["options_overlay"]["mm_net_options_only"] > 0 and "options add" in c["options_overlay"]["line"]
    assert c["options_overlay"]["mm_net_combined"] == f["options_overlay"]["mm_net_combined"]
    mm_c = next(g for g in c["groups"] if g["key"] == "mm")
    assert mm_c["net"] == f["options_overlay"]["mm_net_combined"], "C mode's hero net IS the combined net"
    micro_calls = [p for path, p in DB_CALLS if path == "/db/gold/cot" and p.get("contract") == gold.MICRO_GOLD_CODE]
    assert micro_calls and all(p["fut_or_combined"] == "C" for p in micro_calls)


def test_empty_catalog_publishes_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """PLAN f.2 strict: no catalog (data-service down before the memo filled, seed not run) → no number, with the reason."""

    async def no_catalog(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/catalog":
            raise gold.StoreUnavailable("fixture: catalog down")
        return await _fake_db(path, params)

    monkeypatch.setattr(gold, "_db_fetch", no_catalog)
    s = client.get("/api/gold/series", params={"ids": "FRED_DFII10,DXY_CLOSE"}).json()
    assert all(row["published"] is False and row["points"] == [] for row in s["series"])
    assert s["series"][0]["note"] == "catalog unavailable — not published"
    h = client.get("/api/gold/health").json()
    assert all(g["value"] is None for g in h["gauges"]), "no gauge renders a number without a catalog"
    assert h["verdict"]["line"].endswith(gold.DESCRIBES)
    p = client.get("/api/gold/premiums").json()
    assert p["india"]["premium_pct"] is None
    # positive control: with the catalog back, the same reads publish
    monkeypatch.setattr(gold, "_db_fetch", _fake_db)
    gold._ttl.clear()
    gold.STORE.invalidate()
    s2 = client.get("/api/gold/series", params={"ids": "FRED_DFII10"}).json()
    assert s2["series"][0]["published"] is True and s2["series"][0]["points"]


def test_contracts_oi_change_joins_the_stored_mcx_curve(client: TestClient) -> None:
    fam, pub = mcx._master_gold_family()
    built = gold.build_contracts(fam, pub, {}, [], NOW.date(), {("GOLD", "2026-12-04"): -1234.0})
    g = next(f for f in built["families"] if f["code"] == "GOLD")
    assert g["expiries"][0]["expiry"] == "2026-12-04" and g["expiries"][0]["oi_change"] == -1234.0
    assert g["expiries"][1]["oi_change"] is None, "an expiry the curve does not carry stays null (honest fallback)"
    assert gold._mcx_oi_changes({"rows": [{"symbol": "gold", "expiry": "2026-12-04", "oi_change": 5}, {"symbol": "GOLDM"}]}) == {
        ("GOLD", "2026-12-04"): 5.0
    }
    body = client.get("/api/gold/contracts").json()  # the fixture's MCX curve is empty → null, and the read was made
    assert all(e["oi_change"] is None for f in body["families"] for e in f["expiries"])
    assert any(path == "/db/gold/curve" and p.get("exchange") == "MCX" for path, p in DB_CALLS)


def test_brf_line_prints_the_desk_verdict_not_only_the_premium() -> None:
    base = {"verdict": {"headline": "WEAK WEEK"}, "fair": {"fair_value": 144181.0, "gap_vs_settlement": -1898.0}}
    ok = gold.brf_line({**base, "fair": {**base["fair"], "desk_verdict_state": "OK", "premium_rupees": 900.0}})
    assert ok.startswith("Gold open: fair ₹144,181 (gap −1,898) · OK ·"), "the desk's rule wins over the raw premium"
    waiting = gold.brf_line({**base, "fair": {**base["fair"], "desk_verdict_state": "AWAITING_OPEN"}})
    assert " OK " not in waiting and " WAIT " not in waiting, "no OK/WAIT word before the rule has a price"
    wait = gold.brf_line({**base, "fair": {**base["fair"], "desk_verdict_state": "WAIT"}})
    assert "· WAIT ·" in wait


def test_health_fair_carries_the_desk_verdict_state(client: TestClient) -> None:
    fair = client.get("/api/gold/health").json()["fair"]
    assert fair["desk_verdict_state"] in ("OK", "WAIT", "AWAITING_OPEN", "NEED_PRICE")
    assert fair["desk_verdict_state"] == "NEED_PRICE", "Mon 26 Oct 10:00 IST: MCX is open, no live quote in the cache"


def test_trend_gauge_reads_three_years_for_the_percentile(client: TestClient) -> None:
    body = client.get("/api/gold/health").json()
    trend = next(g for g in body["gauges"] if g["key"] == "trend")
    assert trend["percentile_3y"] is not None and 0 <= trend["percentile_3y"] <= 100
    bars_from = [p["from"] for path, p in DB_CALLS if path == "/db/gold/bars" and p.get("symbol") == gold.GC_FRONT]
    assert (NOW.date() - timedelta(days=gold.TREND_BARS_DAYS)).isoformat() in bars_from


def test_live_basis_is_never_computed_from_a_frozen_quote_outside_mcx_hours(monkeypatch) -> None:
    """Wave-1c re-check major: a cached Breeze LTP after the 23:30/23:55 close (or before 09:00) divided by a duty-paid
    landed price that keeps moving with COMEX is the cross-clock ratio the critics rejected; live_basis must be None then."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from routers import gold as g

    fair = {"mcx_live": 143249.0, "duty_paid_landed": 142625.0, "mcx_live_source": "ICICI Breeze"}
    ist = ZoneInfo("Asia/Kolkata")
    closed = datetime(2026, 10, 27, 2, 0, tzinfo=ist)          # Tue 02:00 IST: MCX closed, cache still holds Mon's LTP
    pre_open = datetime(2026, 10, 27, 8, 45, tzinfo=ist)       # logged in, not yet open
    open_ = datetime(2026, 10, 27, 11, 0, tzinfo=ist)          # trading
    assert g.mcx_is_open(open_) and not g.mcx_is_open(closed) and not g.mcx_is_open(pre_open)
    assert g.live_basis(fair, now=closed) is None and g.live_basis(fair, now=pre_open) is None
    lb = g.live_basis(fair, now=open_)
    assert lb and lb["clock"] == "now" and abs(lb["value"] - 0.44) < 0.01
    # negative control for the gate itself: without a quote there is no live basis even while open
    assert g.live_basis({"duty_paid_landed": 142625.0}, now=open_) is None
    # apply_live_mcx (the overview fold) uses the same gate through its caller: a health built while closed keeps the
    # settlement clock on the gauge
    health = {"fair": {"fair_value": 144806.0, "duty_paid_landed": 142625.0}, "gauges": [{"key": "india_basis", "value": 1.5, "clock": "settlement"}], "window": "W", "_extras": {}}
    monkeypatch.setattr(g, "_now_ist", lambda: closed)
    assert g.apply_live_mcx(health, 143249.0, "ICICI Breeze", None) is True   # the fold itself is unconditional …
    assert health["gauges"][0]["clock"] == "settlement"                      # … but live_basis refused, so the gauge kept its clock


def test_next_fomc_is_the_published_decision_day_not_the_atlanta_imm_horizon() -> None:
    """Re-review C-DATA-9 / C-TRADER-12: with no decision row stored, the Fed's calendar (9 Dec 2026) wins over the
    Atlanta tracker's quarterly third-Wednesday horizons (16 Dec 2026)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from routers import gold as g

    now = datetime(2026, 11, 5, 4, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    nxt = g.next_fomc([], ["2026-12-16", "2027-03-17"], now)
    assert nxt and nxt["date_et"] == "2026-12-09" and nxt["ist"].startswith("2026-12-10 00:30") and "Federal Reserve" in nxt["source"]
    # a stored decision row still wins (negative control for the calendar branch)
    row = {"kind": "FOMC", "name": "Federal Funds Rate", "event_date": "2026-12-09", "time_ist": "00:30"}
    if g.is_fomc_decision(row):
        assert g.next_fomc([row], ["2026-12-16"], now)["source"] == "gold_events"
    # past the published horizon the tracker is the fallback, and says so
    far = datetime(2028, 6, 1, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert "Atlanta" in g.next_fomc([], ["2028-06-21"], far)["source"]


def test_health_line_never_cuts_the_headline_mid_word() -> None:
    from routers import gold as g

    line = g.health_line({"headline": "STRONG WEEK, GOLD-SPECIFIC"}, [], None)
    assert line.startswith("GOLD · STRONG WEEK, GOLD-SPECIFIC") and "GOLD-SPECIF ·" not in line
    long = g.health_line({"headline": "WEAK WEEK, DOLLAR-DRIVEN AND SOMETHING LONGER"}, [], None)
    assert long.startswith("GOLD · WEAK WEEK, DOLLAR-DRIVEN") and "SOMETH" not in long and "AN ·" not in long
