"""Wave 1c (the fix round after the critics, 5 Nov 2026) — every ui-api rule that changed, each with a negative control.

Covers the refs whose fix lives in routers/gold.py: the mirrored fund-driver label (C-TRADER-3 / C-BEGINNER-1 / C-DATA-15),
the driver word omitted when a leg is untested (C-TRADER-7 / C-DATA-2), the dollar tile labelled by the series used
(C-TRADER-8 / C-DATA-4 / C-BEGINNER-6), the IMF ounce scale (C-TRADER-6 / C-BEGINNER-3 / C-DATA-5) and the RBI tonnage
(C-TRADER-22), the India ladder at ONE clock (C-TRADER-4 / C-BEGINNER-2 / C-DATA-11 / C-BEGINNER-5), the Shanghai same-date
pairing (C-TRADER-5 / C-DATA-10), the live MCX header + one basis per page (C-TRADER-10 / C-DATA-13), the Monday-to-date
verdict window (C-TRADER-16), the event strip (C-TRADER-11 / C-DATA-21), the next FOMC decision (C-TRADER-12 / C-DATA-9),
the matched-month PRF card (C-TRADER-13 / C-DATA-8 / C-BEGINNER-4), the brief without trade-implying fields (C-TRADER-15 /
C-DATA-12), the all-history percentile pass-through (C-DATA-14), one carry convention (C-DATA-16), change_unit per gauge
(C-DATA-7 / C-DATA-18 / C-BEGINNER-21), multi-session MCX deltas (C-TRADER-18), n = 1 averages (C-DATA-19 / C-TRADER-21 /
C-BEGINNER-24), the nearest liquid COMEX month on the strip (C-BEGINNER-26 / C-TRADER-9) and offsets on every datetime
(C-TRADER-1 / C-DATA-1 / C-DATA-6). The fixtures, fakes and the pinned clock (Mon 26 Oct 2026 10:00 IST) are test_gold's.
"""

from __future__ import annotations

import importlib.util
import itertools
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from routers import (
    gold,
    mcx,
)
from test_gold import (  # noqa: F401 — the autouse `_offline` fake (no network) and the app
    COT_SUMMARY,
    DB,
    IST,
    NOW,
    REPO,
    _app,
    _fake_db,
    _offline,
    catalog_rows,
)
from test_gold_contract import ROUTES


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


def _cat() -> dict[str, dict[str, Any]]:
    rows = catalog_rows()
    for sid in ("IMF_GOLD_OZ_POL", "IMF_GOLD_OZ_BRA", "IMF_GOLD_OZ_IND", "IMF_GOLD_OZ_USA", "FRED_DTWEXBGS", "SHANGHAI_PREMIUM_PCT"):
        rows.append({**rows[0], "series_id": sid, "verdict": "PUBLISH-CONTEXT", "badge": "context"})
    return {r["series_id"]: r for r in rows}


def _pt(d: str, v: float) -> dict[str, Any]:
    return {"report_date": d, "value": v, "release_at": f"{d}T20:00:00+00:00"}


# ── 1. the fund-driver label mirrors data-service's driver_rule.py byte for byte ────────────────────────────────────


def _data_service_rule() -> Any:
    path = REPO / "services" / "data-service" / "gold" / "driver_rule.py"
    spec = importlib.util.spec_from_file_location("ds_driver_rule", path)
    assert spec and spec.loader, path
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # pure stdlib: no pandas, no duckdb (the module docstring promises it)
    return mod


def test_driver_label_mirrors_data_service_on_every_branch() -> None:
    ds = _data_service_rule()
    assert gold.DRIVER_RULE_TEXT == ds.RULE_TEXT and gold.DRIVER_LABELS == set(ds.ALL_LABELS)
    grid = [-3000.0, -1538.0, -182.0, -1.0, 0.0, 1.0, 182.0, 1538.0, 3000.0, None, True, float("nan")]
    seen: set[str | None] = set()
    for dp, dl, ds_ in itertools.product([-1.64, -1.0, 0.0, 1.0, 1.64, None, True], grid, grid):
        ours, theirs = gold.driver_label(dl, ds_, dp), ds.driver_label(dp, dl, ds_)
        assert ours == theirs, (dp, dl, ds_, ours, theirs)
        seen.add(ours)
    assert seen == gold.DRIVER_LABELS | {None}  # every word reachable, nothing else
    # the week the critics caught, and its mirror
    assert gold.driver_label(1538, 182, -1.64) == "funds bought the dip"
    assert gold.driver_label(-1538, -182, 1.64) == "funds sold into it"
    assert gold.driver_label(-182, -1538, -1.0) == "funds bought the dip"  # both legs closed, covering 8× the liquidation: net +1,356
    assert gold.driver_label(-2000, 2000, -1.0) == "long liquidation"  # a tie between the bearish legs → the closing leg
    # negative controls: NaN / a bool / a missing leg / no move in either leg → no word (never a default)
    assert gold.driver_label(float("nan"), 1, -1.0) is None and gold.driver_label(1, None, -1.0) is None
    assert gold.driver_label(True, 1, -1.0) is None and gold.driver_label(0, 0, -1.0) is None
    assert gold.driver_clause("funds bought the dip") == "bought the dip" and gold.driver_clause(None) is None


def test_cot_route_prints_the_mirrored_label_and_the_rule_text(client: TestClient) -> None:
    body = client.get("/api/gold/cot", params={"weeks": 4}).json()
    assert body["driver_label"] == "long liquidation" and body["driver_rule"] == gold.DRIVER_RULE_TEXT
    assert "bigger of the two legs" in body["driver_rule"]


# ── 2. H2: no driver word when a leg is untested ────────────────────────────────────────────────────────────────────


def test_driver_word_is_omitted_when_either_leg_is_missing() -> None:
    assert gold._driver_word(-2.8, 0.1, 1.0) == "GOLD-SPECIFIC"  # both legs tested, neither explains
    assert gold._driver_word(-2.8, None, 1.0) is None and gold._driver_word(-2.8, 0.1, None) is None
    assert gold._driver_word(-2.8, -1.4, None) == "DOLLAR-DRIVEN"  # a leg that DOES explain still speaks
    assert gold._driver_word(-2.8, None, 8.0) == "YIELD-DRIVEN"
    assert gold.driver_note(-2.8, None, 1.0) == "driver untested: dollar series offline"
    assert gold.driver_note(-2.8, None, None) == "driver untested: dollar series offline, real-yield series offline"
    assert gold.driver_note(-2.8, None, 1.0, "DXY offline (stand-in shown)") == "driver untested: DXY offline (stand-in shown)"
    assert gold.driver_note(0.2, None, None) is None  # too small a move to call anything
    assert gold.driver_note(-2.8, -1.4, None) is None  # the word was produced: no note
    gauges = [{"key": "trend", "state": "delayed", "change": -2.8, "value": 4007.9, "window_label": "5 sessions"}]
    v = gold.verdict_sentence(gauges, "W", {})
    assert v["headline"] == "WEAK WEEK" and "GOLD-SPECIFIC" not in v["line"]
    assert v["clauses"][0]["note"] == "driver untested: dollar series offline, real-yield series offline"
    assert "driver untested" in v["line"] and v["line"].endswith(gold.DESCRIBES)
    v2 = gold.verdict_sentence(gauges + [{"key": "real_yield", "state": "delayed", "change_bp": 1.0}], "W", {"usd_effect_pct": 0.1})
    assert v2["headline"] == "WEAK WEEK, GOLD-SPECIFIC" and v2["clauses"][0]["note"] is None  # negative control


# ── 3. the dollar tile is labelled by the series actually used ──────────────────────────────────────────────────────


def _series_without(ids: set[str], extra_rows: list[dict[str, Any]] | None = None) -> Any:
    async def fake(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/series":
            out = await _fake_db(path, params)
            rows = [r for r in out["rows"] if r["series_id"] not in ids]
            wanted = set(str(params.get("ids", "")).split(","))
            rows += [r for r in (extra_rows or []) if r["series_id"] in wanted]
            return {"rows": rows}
        if path == "/db/gold/bars" and params.get("symbol") == gold.DXY_SYMBOL:
            return {"rows": []}
        if path == "/db/gold/catalog":
            return {"rows": list(_cat().values())}
        return await _fake_db(path, params)

    return fake


def test_dollar_gauge_reads_dxy_bars_then_the_labelled_fed_index_never_dtwexbgs_as_dxy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # (a) the DXY_CLOSE series is present: the gauge says so
    g = next(x for x in client.get("/api/gold/health").json()["gauges"] if x["key"] == "dollar")
    assert g["series_id"] == "DXY_CLOSE" and g["read_from"] == "series DXY_CLOSE" and g["label"] == "Dollar index (DXY)"
    # (b) no series points, but the DX-Y.NYB daily bars are stored: the same catalog row, read from the bars
    bars = [{"trade_date": (NOW.date() - timedelta(days=k)).isoformat(), "close": 99.0 + 0.01 * k} for k in range(40, -1, -1)]

    async def with_bars(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/bars" and params.get("symbol") == gold.DXY_SYMBOL:
            return {"rows": bars}
        return await _series_without({"DXY_CLOSE"})(path, params)

    monkeypatch.setattr(gold, "_db_fetch", with_bars)
    gold._ttl.clear()
    gold.STORE.invalidate()
    h = client.get("/api/gold/health").json()
    g = next(x for x in h["gauges"] if x["key"] == "dollar")
    assert g["series_id"] == "DXY_CLOSE" and g["read_from"] == f"daily bars {gold.DXY_SYMBOL}" and g["value"] == 99.0
    assert "driver untested" not in h["verdict"]["line"]
    # (c) neither: the Fed broad index stands in, LABELLED as such, and the driver word is withheld with the reason
    dtw = [{"series_id": "FRED_DTWEXBGS", "report_date": (NOW.date() - timedelta(days=k)).isoformat(), "value": 121.0 + 0.01 * k,
            "release_at": f"{(NOW.date() - timedelta(days=k)).isoformat()}T20:00:00+00:00"} for k in range(60, 0, -1) if k % 7 == 3]
    monkeypatch.setattr(gold, "_db_fetch", _series_without({"DXY_CLOSE"}, dtw))
    gold._ttl.clear()
    gold.STORE.invalidate()
    h = client.get("/api/gold/health").json()
    g = next(x for x in h["gauges"] if x["key"] == "dollar")
    assert g["series_id"] == "FRED_DTWEXBGS" and g["label"].startswith("Fed broad USD index (DTWEXBGS") and "not DXY" in g["label"]
    assert g["value"] is not None and g["read_from"].endswith("(stand-in)")
    assert "GOLD-SPECIFIC" not in h["verdict"]["line"] and "DOLLAR-DRIVEN" not in h["verdict"]["line"]
    note = next(c for c in h["verdict"]["clauses"] if c["rule_id"] == "H1/H2")["note"]
    assert note is None or "DXY offline" in note  # the move may be < 0.5 % in the fixture; when called, it names the reason
    # the MACRO driver strip labels the same stand-in by what it is
    m = client.get("/api/gold/macro").json()
    d = next(x for x in m["drivers"] if x["key"] == "dxy")
    assert d["series_id"] == "FRED_DTWEXBGS" and d["label"].startswith("Fed broad USD index") and "stand-in" in d["label_note"]
    assert m["driver_health"]["dxy_series"] == "FRED_DTWEXBGS" and "DTWEXBGS" in m["driver_health"]["beta_units"]["beta_dxy"]
    assert m["kgx"]["note"] is None or "USD effect unavailable" in m["kgx"]["note"]
    # (d) nothing at all: a labelled empty tile, never a blank with no reason
    monkeypatch.setattr(gold, "_db_fetch", _series_without({"DXY_CLOSE", "FRED_DTWEXBGS"}))
    gold._ttl.clear()
    gold.STORE.invalidate()
    g = next(x for x in client.get("/api/gold/health").json()["gauges"] if x["key"] == "dollar")
    assert g["value"] is None and g["state"] == "unavailable" and "no stored DXY_CLOSE points" in g["note"]


def test_macro_dxy_driver_is_labelled_dxy_when_dxy_is_used(client: TestClient) -> None:
    m = client.get("/api/gold/macro").json()
    d = next(x for x in m["drivers"] if x["key"] == "dxy")
    assert d["series_id"] == "DXY_CLOSE" and d["label"] == "Dollar index (DXY)" and d["label_note"] is None
    assert m["driver_health"]["dxy_series"] == "DXY_CLOSE"


# ── 4. IMF ounces, the RBI tonnage, the EFP average ─────────────────────────────────────────────────────────────────


def test_official_sector_scales_ounces_to_moz_and_tonnes_and_rbi_uses_the_imf_ounces() -> None:
    series = {
        "IMF_GOLD_OZ_POL": [_pt("2026-07-31", 21_500_000.0), _pt("2026-08-31", 21_634_000.0)],
        "IMF_GOLD_OZ_IND": [_pt("2025-08-31", 27_500_000.0), _pt("2026-08-31", 28_309_311.0)],
        "IMF_GOLD_OZ_USA": [_pt("2026-07-31", 261_499_000.0)],
        "IMF_GOLD_OZ_BRA": [_pt("2026-08-31", 5_544_278.7)],  # B1 rescaled the ×1000 source row
        "RBI_GOLD_RESERVES_USD_MN": [_pt("2026-10-23", 106_000.0)],
        "COMEX_GC_FRONT": [_pt("2026-10-23", 4007.9)],
    }
    cat = _cat()
    cat["RBI_GOLD_RESERVES_USD_MN"] = {**cat["COMEX_GC_FRONT"], "series_id": "RBI_GOLD_RESERVES_USD_MN"}
    out = gold.build_flows([], series, [], [], cat, 12)
    by = {o["country"]: o for o in out["official"]}
    assert by["POL"]["oz_mn"] == 21.634 and by["POL"]["tonnes"] == pytest.approx(672.9, abs=0.1)  # was 21,634,000 Moz / 672,892,617 t
    assert by["POL"]["chg_oz_mn"] == pytest.approx(0.134, abs=0.001) and by["POL"]["chg_t"] == pytest.approx(4.2, abs=0.1)
    assert by["IND"]["tonnes"] == pytest.approx(880.5, abs=0.1) and by["IND"]["chg_12m_oz_mn"] == pytest.approx(0.809, abs=0.001)
    assert by["USA"]["tonnes"] == pytest.approx(8133.5, abs=0.5) and by["BRA"]["tonnes"] == pytest.approx(172.4, abs=0.1)
    assert [o["country"] for o in out["official"]] == ["USA", "IND", "POL", "BRA"]  # Brazil no longer sorts above the USA
    assert by["POL"]["oz"] == 21_634_000.0 and "troy ounces" in by["POL"]["unit_note"]
    rbi = out["rbi"]
    assert rbi["tonnes"] == by["IND"]["tonnes"] and rbi["tonnes_month"] == "2026-08" and rbi["tonnes_est"] is None
    assert rbi["tonnes_source"].startswith("IMF IFS") and "not a price-implied" in rbi["note"]
    # negative control: no IMF row for India → no tonnage (never the price-implied estimate)
    out2 = gold.build_flows([], {k: v for k, v in series.items() if k != "IMF_GOLD_OZ_IND"}, [], [], cat, 12)
    assert out2["rbi"]["tonnes"] is None and out2["rbi"]["tonnes_est"] is None and out2["rbi"]["usd_mn"] == 106_000.0


def test_efp_average_needs_five_prior_sessions() -> None:
    def rows(n: int) -> list[dict[str, Any]]:
        return [{"product": "GOLD", "process_date": (date(2026, 10, 1) + timedelta(days=k)).isoformat(), "round_turns": 3000 + k}
                for k in range(n)]

    one = gold.build_flows([], {}, rows(1), [], _cat(), 12)["otc"]["efp"]
    assert one["today_rt"] == 3000 and one["avg_20d"] is None and one["avg_sessions"] == 0 and "needs 5 prior" in one["avg_note"]
    six = gold.build_flows([], {}, rows(6), [], _cat(), 12)["otc"]["efp"]
    assert six["today_rt"] == 3005 and six["avg_20d"] == 3002 and six["avg_sessions"] == 5 and six["avg_note"] is None
    assert six["since"] == "2026-10-01"


# ── 5. the India ladder at one clock; Shanghai paired on the same date ──────────────────────────────────────────────


FAIR = {
    "contract": "GOLD",
    "expiry": "2026-12-04",
    "comex": {"symbol": "GCZ26.CMX", "price": 4007.9, "as_of": "2026-10-26T09:57:00+05:30"},
    "comex_symbol": "GCZ26.CMX",
    "usdinr": {"symbol": "INR=X", "price": 94.93, "as_of": "2026-10-26T09:57:00+05:30"},
    "landed": 122_300.0,
    "duty_pct": 15.0,
    "duty_effective": "2026-05-13",
    "duty_note": "n",
    "duty_paid_landed": 140_645.0,
    "basis_pct": 1.5,
    "settlement": 146_079.0,
    "settlement_session": "2026-10-22",
    "settlement_session_label": "Thu 22 Oct settlement",
    "settlement_quality": "proxy",
    "mcx_live": None,
    "mcx_live_source": None,
}


def test_india_ladder_prints_the_stored_fix_minute_premium_and_never_a_cross_clock_ratio() -> None:
    cat = _cat()
    series = {
        "IBJA_999_PM": [_pt("2026-10-22", 141_630.0), _pt("2026-10-23", 141_900.0)],
        "INDIA_PREMIUM_PCT": [_pt("2026-10-22", -0.71)],
        "MCX_BASIS_PCT": [_pt("2026-10-22", 1.58)],
    }
    p = gold.build_premiums(FAIR, series, cat)["india"]
    assert p["premium_pct"] == -0.71 and p["premium_date"] == "2026-10-22"  # the stored same-minute number
    assert "fix minute" in p["premium_clock"] and "showing Thu 22 Oct" in p["premium_note"]  # IBJA 23 Oct is newer: said so
    cross_clock = (141_900.0 / (140_645.0 * 999 / 995) - 1) * 100
    assert p["premium_pct"] != pytest.approx(cross_clock, abs=0.05)
    # wave 1d: the desk's own settlement-clock basis (both legs at that session's close, purity-correct) wins over the stored
    # derive row (GC=F daily close, 999, labelled one session late until the relabel)
    assert p["basis_pct"] == 1.5 and p["basis_date"] == "2026-10-22" and "Thu 22 Oct settlement" in p["basis_label"]
    assert p["basis_source"].startswith("desk model")
    # negative control: no desk figure → the stored row of THAT session stands in, labelled as the stored GOLD derive at
    # its purity (D1: landed × 995/1000)
    p0 = gold.build_premiums({**FAIR, "basis_pct": None}, series, cat)["india"]
    assert p0["basis_pct"] == 1.58 and p0["basis_source"] == "data-service derive (stored)" and "(stored)" in p0["basis_label"]
    assert "× 995/1000" in p0["basis_label"] and p0["basis_reference"] == "landed_995"
    assert p["live_basis"] is None
    steps = {s["step"]: s for s in p["ladder"]}
    assert steps["comex"]["clock"] == "now" and steps["duty_paid"]["clock"] == "now" and steps["ibja"]["clock"] == "fix"
    assert steps["mcx"]["clock"] == "settlement" and "(basis +1.50 %" in steps["mcx"]["label"]
    assert "−0.71 %" in steps["ibja"]["label"] and "Thu 22 Oct fix" in steps["ibja"]["label"]
    assert "never divide across them" in p["clock_note"]
    # negative control: nothing stored → no premium, with the reason (never computed from the live bars)
    p2 = gold.build_premiums(FAIR, {"IBJA_999_PM": series["IBJA_999_PM"]}, cat)["india"]
    assert p2["premium_pct"] is None and "no fix-minute premium stored" in p2["premium_note"]
    # a live MCX quote adds the live-clock pair beside the settlement basis — both labelled, neither replaced
    p3 = gold.build_premiums({**FAIR, "mcx_live": 141_200.0, "mcx_live_source": "ICICI Breeze"}, series, cat)["india"]
    assert p3["live_basis"]["value"] == pytest.approx((141_200.0 / 140_645.0 - 1) * 100, abs=0.01)
    assert p3["live_basis"]["clock"] == "now" and p3["basis_pct"] == 1.5


def test_shanghai_premium_pairs_the_same_report_date_only() -> None:
    cat = _cat()
    g = gold.GRAMS_PER_TROY_OZ
    series = {
        "SGE_SHAU_PM": [_pt("2026-10-23", 905.0), _pt("2026-10-26", 930.0)],
        "LBMA_PM_USD": [_pt("2026-10-23", 3960.0)],  # today's PM not stored yet
        "FX_CNY": [_pt("2026-10-23", 7.12), _pt("2026-10-26", 7.11)],
        "SHANGHAI_PREMIUM_USD": [_pt("2026-10-23", -1.55)],
        "SHANGHAI_PREMIUM_PCT": [_pt("2026-10-23", -0.04)],
    }
    sh = gold.build_premiums(FAIR, series, cat)["shanghai"]
    assert sh["premium_usd"] == -1.55 and sh["premium_pct"] == -0.04 and sh["pair_date"] == "2026-10-23"
    assert sh["ts_sge"] == "2026-10-26" and sh["ts_ref"] == "2026-10-23" and sh["note"].startswith("awaiting today's PM")
    assert sh["sge_usd_oz"] == pytest.approx(905.0 * g / 7.12, abs=0.01)  # the stored pair's own legs, not today's SGE
    assert sh["premium_usd"] != pytest.approx(930.0 * g / 7.11 - 3960.0, abs=1.0)  # the cross-date artefact (≈ +$100)
    # positive control: today's London PM stored → paired on the same date, computed, no note
    series["LBMA_PM_USD"].append(_pt("2026-10-26", 4065.0))
    sh2 = gold.build_premiums(FAIR, series, cat)["shanghai"]
    assert sh2["pair_date"] == "2026-10-26" and sh2["note"] is None and sh2["pairing"].startswith("same report date")
    assert sh2["premium_usd"] == pytest.approx(930.0 * g / 7.11 - 4065.0, abs=0.01)
    # negative control: nothing stored and no same-date PM → no number at all
    sh3 = gold.build_premiums(FAIR, {"SGE_SHAU_PM": series["SGE_SHAU_PM"], "FX_CNY": series["FX_CNY"]}, cat)["shanghai"]
    assert sh3["premium_usd"] is None and "never SGE vs an earlier London fix" in sh3["note"]


# ── 6. live MCX on the header; one basis per page; the quote-cache lookup ───────────────────────────────────────────


def _quote(ltp: float, expiry: str = "2026-12-04") -> dict[str, Any]:
    return {
        "available": True,
        "expiry": expiry,
        "as_of": NOW.isoformat(timespec="seconds"),
        "quote": {"ltp": ltp, "source": "ICICI Breeze", "time": NOW.isoformat(timespec="seconds")},
    }


def test_fair_block_finds_the_quote_under_the_resolved_expiry_key() -> None:
    import asyncio

    mcx._cache.set("quote:GOLD:2026-12-04", _quote(146_500.0), ttl=60)
    a = asyncio.run(gold.fair_block())
    assert a["mcx_live"] == 146_500.0 and a["mcx_live_source"] == "ICICI Breeze" and a["desk_verdict_state"] in ("OK", "WAIT")
    assert a["premium_rupees"] == round(146_500.0 - a["fair_value"], 0)
    mcx._cache.clear()
    gold._ttl.clear()
    mcx._cache.set("quote:GOLD:front", _quote(146_600.0, expiry="2027-02-05"), ttl=60)  # a 'front' entry for ANOTHER expiry
    b = asyncio.run(gold.fair_block())
    assert b["mcx_live"] is None and b["desk_verdict_state"] == "NEED_PRICE"


def test_overview_header_shows_live_mcx_and_one_basis_when_the_quote_exists(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def live_quote(contract: str = "GOLD", expiry: str | None = None) -> dict[str, Any]:
        return {**_quote(146_500.0), "contract": contract}

    monkeypatch.setattr(mcx, "mcx_quote", live_quote)
    body = client.get("/api/gold/overview").json()
    s, h = body["strip"], body["health"]
    assert s["mcx_live"] == 146_500.0 and s["mcx_shown"] == "live" and s["mcx_settle"] == 146_080.0  # settlement beneath
    assert s["mcx_live_as_of"].endswith("+05:30") and s["mcx_live_vs_settle_pct"] == pytest.approx(0.288, abs=0.001)
    # wave 1d (D1): GOLD delivers 995 — the live basis divides by the duty-paid landed price × 995/1000 (landed is fine gold)
    dp, dp995 = h["fair"]["duty_paid_landed"], h["fair"]["duty_paid_landed_purity"]
    assert dp995 == pytest.approx(dp * 995 / 1000, abs=1) and h["fair"]["basis_reference"] == "landed_995"
    assert s["basis_clock"] == "now" and s["basis_pct"] == pytest.approx((146_500.0 / dp995 - 1) * 100, abs=0.01)
    assert s["basis_pct"] != pytest.approx((146_500.0 / dp - 1) * 100, abs=0.05)  # negative control: never the fine price
    assert s["basis_pct"] != pytest.approx((146_500.0 / (dp * 995 / 999) - 1) * 100, abs=0.05)  # … nor the old × 995/999
    assert s["basis_reference"] == "landed_995" and s["basis_contract"].startswith("GOLD")
    assert s["basis_live_pct"] == s["basis_pct"] and s["basis_settle_pct"] is not None and s["basis_settle_date"] == "2026-10-22"
    ib = next(g for g in h["gauges"] if g["key"] == "india_basis")
    assert ib["value"] == pytest.approx(s["basis_pct"], abs=0.01) and ib["state"] == "live" and ib["clock"] == "now"
    assert h["fair"]["mcx_live"] == 146_500.0 and h["fair"]["desk_verdict_state"] in ("OK", "WAIT")
    h4 = next(c for c in h["verdict"]["clauses"] if c["rule_id"] == "H4")
    assert h4["value"] == ib["value"]  # the sentence was re-run on the live basis: one number on the page
    assert ("OK" in h["brf_line"]) or ("WAIT" in h["brf_line"])


def test_overview_header_without_a_quote_is_the_settlement_clock(client: TestClient) -> None:
    s = client.get("/api/gold/overview").json()["strip"]
    assert s["mcx_live"] is None and s["mcx_shown"] == "settlement" and s["basis_clock"] == "settlement"
    assert s["basis_pct"] == s["basis_settle_pct"] and s["basis_live_pct"] is None and "duty-paid landed" in s["basis_label"]
    # the matched month: the liquid cycle month, its OWN stored price labelled as a last trade (no bulletin settlement yet)
    assert s["comex_matched"] == "GCZ26.CMX" and s["comex_matched_note"] is None and s["comex_matched_settle"] is None
    assert s["comex_matched_last"] == 4007.9 and "not a settlement" in s["comex_matched_last_label"]
    assert s["comex_matched_last_date"] == "2026-10-23"
    # a GOLDM pick (Nov-26 expiry) is matched to DEC-26, said so — never the serial GCX26 (C-BEGINNER-26)
    o = client.get("/api/gold/overview", params={"contract": "GOLDM"}).json()
    assert o["contract"]["expiry"] == "2026-11-05" and o["contract"]["comex_matched"] == "GCZ26.CMX"
    assert o["contract"]["comex_matched_calendar"] == "GCX26.CMX" and o["strip"]["comex_matched_note"].startswith("nearest liquid")
    assert o["strip"]["instruments"]["matched"] == "COMEX matched month GCZ26.CMX"


def test_apply_live_mcx_is_idempotent_and_skips_an_unpublished_gauge() -> None:
    import asyncio

    h = asyncio.run(gold.build_health("W"))
    assert gold.apply_live_mcx(h, 146_500.0, "ICICI Breeze", NOW.isoformat()) is True
    assert gold.apply_live_mcx(h, 146_900.0, "ICICI Breeze", NOW.isoformat()) is False  # already live: never overwritten
    assert h["fair"]["mcx_live"] == 146_500.0
    assert gold.apply_live_mcx({"fair": {}, "gauges": []}, None, None, None) is False


# ── 7. the verdict window: Monday-to-date once the week has started ─────────────────────────────────────────────────


def test_window_anchor_is_monday_to_date_once_the_week_has_a_session() -> None:
    days = [date(2026, 10, 19) + timedelta(days=k) for k in range(9) if (date(2026, 10, 19) + timedelta(days=k)).weekday() < 5]
    pts = [{"report_date": d.isoformat(), "value": 4000.0 + i, "release_at": None} for i, d in enumerate(days)]  # Mon 19 → Tue 27
    w = gold.window_anchor(pts, "W", date(2026, 10, 27))
    assert w["from_date"] == "2026-10-23" and w["label"] == "week to date (since the Fri 23 Oct close)" and w["sessions"] == 2
    w_wed = gold.window_anchor(pts, "W", date(2026, 10, 28))  # Wednesday, no bar yet today: still the calendar week
    assert w_wed["from_date"] == "2026-10-23" and w_wed["sessions"] == 2
    # negative control: Monday before the first session (no bar this week) → the trailing 5 sessions, labelled so
    pre = gold.window_anchor(pts[:-2], "W", date(2026, 10, 26))
    assert pre["label"] == "5 sessions" and pre["from_date"] == "2026-10-16" if len(pts) > 7 else pre["then"] is None
    m = gold.window_anchor(pts, "M", date(2026, 10, 27))
    assert m["label"] == "30 days" or m["label"].startswith("month to date")
    d = gold.window_anchor(pts, "D", date(2026, 10, 27))
    assert d["label"] == "vs the previous session" and d["from_date"] == "2026-10-26"
    assert gold.window_anchor([], "W", date(2026, 10, 27))["then"] is None


def test_health_trend_window_label_reaches_the_verdict(client: TestClient) -> None:
    h = client.get("/api/gold/health", params={"window": "W"}).json()
    t = next(g for g in h["gauges"] if g["key"] == "trend")
    assert t["window_label"] in ("5 sessions",) or t["window_label"].startswith("week to date")
    assert t["window_label"] in h["verdict"]["line"] and "over the week" not in h["verdict"]["line"]
    assert t["change_unit"] == "%" and t["window_from"] is not None


# ── 8. events: kinds, stars, the next FOMC decision, nothing past ───────────────────────────────────────────────────


def test_event_kinds_stars_and_past() -> None:
    speech = {"kind": "FOMC", "name": "FOMC Member Hammack Speaks", "impact": "Low", "event_date": "2026-11-05", "time_ist": "19:20"}
    stmt = {"kind": "FOMC", "name": "Federal Funds Rate", "impact": "High", "event_date": "2026-12-10", "time_ist": "00:30"}
    minutes = {"kind": "FOMC", "name": "FOMC Meeting Minutes", "impact": "Medium", "event_date": "2026-11-19", "time_ist": "00:30"}
    nfp = {"kind": "US_NFP", "name": "Non-Farm Employment Change", "impact": "High", "event_date": "2026-11-06", "time_ist": "19:00"}
    assert gold.event_kind(speech) == "FOMC_SPEECH" and gold.event_kind(stmt) == "FOMC" and gold.event_kind(minutes) == "FOMC_MINUTES"
    assert gold.event_star(stmt) and gold.event_star(nfp) and not gold.event_star(speech) and not gold.event_star(minutes)
    assert gold.impact_rank(stmt) == 0 == gold.impact_rank(nfp) < gold.impact_rank(minutes) < gold.impact_rank(speech)
    now = datetime(2026, 11, 5, 23, 49, tzinfo=IST)
    assert gold.event_is_past(speech, now) and not gold.event_is_past(nfp, now)
    assert gold.event_is_past({"event_date": "2026-11-05"}, now) is False  # no time: today's undated row still stands
    d = gold.decorate_event(speech, now)
    assert d["kind"] == "FOMC_SPEECH" and d["kind_stored"] == "FOMC" and d["past"] is True and d["star"] is False
    assert gold.decorate_event(nfp, now)["kind_stored"] is None


def test_next_fomc_is_the_decision_never_a_speaker_with_the_statement_time() -> None:
    now = datetime(2026, 11, 5, 23, 49, tzinfo=IST)
    events = [
        {"kind": "FOMC", "name": "FOMC Member Hammack Speaks", "event_date": "2026-11-05", "time_ist": "19:20"},
        {"kind": "FOMC", "name": "FOMC Member Barkin Speaks", "event_date": "2026-11-06", "time_ist": "21:00"},
        {"kind": "FOMC", "name": "FOMC Press Conference", "event_date": "2026-12-10", "time_ist": "01:00"},
        {"kind": "FOMC", "name": "Federal Funds Rate", "event_date": "2026-12-10", "time_ist": "00:30"},
    ]
    n = gold.next_fomc(events, [], now)
    assert n and n["name"] == "Federal Funds Rate" and n["ist"] == "2026-12-10 00:30 IST" and n["date_et"] == "2026-12-09"
    assert n["at"] == "2026-12-10T00:30+05:30" and n["after_mcx_close"] is True and n["source"] == "gold_events"
    # no decision row stored: the Atlanta-Fed meeting date with the statement time computed (winter → 00:30 IST next day)
    n2 = gold.next_fomc(events[:2], ["2026-10-28", "2026-12-09"], now)
    assert n2 and n2["date_et"] == "2026-12-09" and n2["ist"] == "2026-12-10 00:30 IST" and n2["source"].startswith(("Federal Reserve FOMC calendar", "Atlanta Fed"))
    assert gold.fomc_statement_ist(date(2026, 10, 28)).isoformat(timespec="minutes") == "2026-10-28T23:30+05:30"  # summer
    assert gold.fomc_statement_ist(date(2026, 12, 9)).isoformat(timespec="minutes") == "2026-12-10T00:30+05:30"  # winter
    assert gold.next_fomc(events[:2], [], now)["date_et"] == "2026-12-09"   # speeches alone never make a "next FOMC": the published calendar answers


def test_macro_fed_and_calendar_separate_speeches_and_drop_past_rows(client: TestClient) -> None:
    m = client.get("/api/gold/macro").json()
    assert m["fed"]["next_fomc_ist"] == "2026-10-28 23:30 IST" and m["fed"]["after_mcx_close"] is True
    assert m["fed"]["next_fomc"]["name"] == "FOMC statement" and m["fed"]["next_fomc"]["kind"] == "FOMC"
    assert [s["title"] for s in m["fed"]["speakers"]] == ["FOMC Member Hammack Speaks"]
    kinds = {e["title"]: e["kind"] for e in m["calendar"]}
    assert kinds["FOMC Member Hammack Speaks"] == "FOMC_SPEECH" and kinds["FOMC statement"] == "FOMC"
    assert "already released today" not in kinds  # 08:00 today, now 10:00: past
    stars = {e["title"]: e["star"] for e in m["calendar"]}
    assert stars["FOMC statement"] and stars["CPI m/m"] and not stars["FOMC Member Hammack Speaks"]


def test_overview_calendar_is_the_full_week_sorted_by_impact_then_time_with_stars(client: TestClient) -> None:
    cal = client.get("/api/gold/overview").json()["calendar"]
    titles = [e["name"] for e in cal]
    assert titles[:2] == ["FOMC statement", "CPI m/m"]  # rank 0 rows first, by date
    assert "already released today" not in titles and "Non-Farm Payrolls" not in titles  # past · beyond 7 days
    assert all(a["impact_rank"] <= b["impact_rank"] for a, b in itertools.pairwise(cal))
    assert [e["star"] for e in cal[:2]] == [True, True] and not next(e for e in cal if e["kind"] == "FOMC_SPEECH")["star"]
    assert any(e["kind"] == "COT_RELEASE" for e in cal) and all(e["past"] is False for e in cal)
    assert len(cal) >= 5 and all("days" in e for e in cal)


def test_calendar_route_decorates_every_row_and_keeps_the_date_order(client: TestClient) -> None:
    ev = client.get("/api/gold/calendar", params={"days": 14}).json()["events"]
    sp = next(e for e in ev if e["name"] == "FOMC Member Hammack Speaks")
    assert sp["kind"] == "FOMC_SPEECH" and sp["kind_stored"] == "FOMC" and sp["star"] is False
    past = next(e for e in ev if e["name"] == "already released today")
    assert past["past"] is True and past["days"] == 0
    assert all({"star", "impact_rank", "past"} <= set(e) for e in ev)


# ── 9. the matched-month PRF card ───────────────────────────────────────────────────────────────────────────────────


def _prf_row(mmy: str, mat: str, fnd: str, ltd: str, init: float) -> dict[str, Any]:
    return {
        "symbol": "GC", "biz_date": "2026-11-04", "mmy": mmy, "mat_date": mat, "first_notice": fnd, "last_trd": ltd,
        "min_px_incr": 1.0, "tick_incr_reg": 0.1, "multiplier": 100, "uom": "oz_tr", "uom_qty": 100, "settl_method": "P",
        "init_margin": init, "description": "Gold Futures", "sec_type": "FUT",
    }


def test_comex_spec_card_picks_the_matched_month_with_the_display_factor_and_drops_stub_margins() -> None:
    prf = [
        _prf_row("202611", "2026-11-25", "2026-10-30", "2026-11-25", 25.0),
        _prf_row("202612", "2026-12-29", "2026-11-30", "2026-12-29", 25.0),
    ]
    margins = [
        {"symbol": "GC", "expiry": "2026-12-29", "trade_date": "2026-11-03", "margin_ccy": 25.0, "ref_price": 4000.0},
        {"symbol": "GC", "expiry": "2026-12-29", "trade_date": "2026-11-04", "margin_ccy": 21_000.0, "ref_price": 4078.0},
        {"symbol": "GC", "expiry": "2026-11-25", "trade_date": "2026-11-04", "margin_ccy": 20_500.0, "ref_price": 4078.0},
    ]
    today = date(2026, 11, 4)
    c = gold.comex_spec_card(prf, margins, "GCZ26.CMX", today)
    assert c and c["mmy"] == "202612" and c["month"] == "DEC-26" and c["picked_by"] == "matched month"
    assert c["first_notice"] == "2026-11-30" and c["days_to_first_notice"] == 26 and c["last_trade"] == "2026-12-29"
    assert c["tick_usd"] == 0.1 and c["tick_value_usd"] == 10.0 and c["display_factor"] == 0.1  # $0.10 = $10, not $1 = $100
    assert c["settl_method_label"] == "physical delivery" and c["uom_label"] == "troy oz"
    assert c["init_margin_usd"] is None  # the $25 stub is not an outright margin
    assert c["margin_history"] == [{"trade_date": "2026-11-04", "margin_usd": 21_000.0}]  # the $25 row dropped, Nov's row excluded
    assert c["margin_pct_of_notional"] is None and "rows under $1,000 dropped" in c["margin_history_note"]
    # negative control: a month the PRF does not list → the first month still trading, said so
    c2 = gold.comex_spec_card(prf, margins, "GCG27.CMX", today)
    assert c2 and c2["mmy"] == "202611" and c2["picked_by"].startswith("first month still trading") and c2["yahoo_symbol"] is None
    assert gold.prf_row_for_month(prf, None) is None and gold.comex_spec_card([], margins, "GCZ26.CMX", today) is None


def test_fnd_for_month_matches_every_spelling_of_the_month_and_the_prf_fallback() -> None:
    today = date(2026, 11, 4)
    ev_iso = [{"event_date": "2026-11-30", "kind": "COMEX_FND", "name": "COMEX GC 2026-12 first notice day", "contract_month": "2026-12"},
              {"event_date": "2026-10-30", "kind": "COMEX_FND", "name": "COMEX GC 2026-11 first notice day"}]
    assert gold._fnd_for_month(ev_iso, [], (2026, 12), today) == {"fnd_date": "2026-11-30", "ltd_date": None, "days_to_fnd": 26,
                                                                  "source": "gold_events"}
    ev_sym = [{"event_date": "2026-11-30", "kind": "COMEX_FND", "name": "GCZ26 first notice day"}]
    assert gold._fnd_for_month(ev_sym, [], (2026, 12), today)["fnd_date"] == "2026-11-30"
    prf = [_prf_row("202612", "2026-12-29", "2026-11-30", "2026-12-29", 25.0)]
    out = gold._fnd_for_month([], prf, (2026, 12), today)
    assert out["source"] == "CME PRF" and out["ltd_date"] == "2026-12-29" and out["days_to_fnd"] == 26
    # negative control: the Nov serial's FND never answers for the Dec month
    assert gold._fnd_for_month(ev_iso[1:], [], (2026, 12), today)["source"] is None or \
        gold._fnd_for_month(ev_iso[1:], [], (2026, 12), today)["fnd_date"] != "2026-10-30"
    pe = gold.prf_events(prf, today)
    assert [e["name"] for e in pe] == ["COMEX GC 2026-12 first notice day", "COMEX GC 2026-12 last trading day"]
    assert pe[1]["time_ist"] == "23:00" and pe[0]["contract_month"] == "2026-12"


def test_curve_comex_points_carry_first_notice_from_the_prf(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    prf = [_prf_row("202612", "2026-12-29", "2026-11-30", "2026-12-29", 25.0), _prf_row("202702", "2027-02-24", "2027-01-29", "2027-02-24", 25.0)]

    async def with_prf(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/cme/prf":
            return {"rows": prf}
        return await _fake_db(path, params)

    monkeypatch.setattr(gold, "_db_fetch", with_prf)
    pts = client.get("/api/gold/curve", params={"exchange": "COMEX"}).json()["points"]
    assert pts[0]["first_notice"] == "2026-11-30" and pts[0]["days_to_fnd"] == (date(2026, 11, 30) - NOW.date()).days
    assert pts[1]["first_notice"] == "2027-01-29" and pts[1]["last_trade"] == "2027-02-24" and pts[1]["days_to_ltd"] > pts[1]["days_to_fnd"]
    mcx_pts = client.get("/api/gold/curve", params={"exchange": "MCX"}).json()["points"]
    assert all("first_notice" not in p for p in mcx_pts)


# ── 10. the brief: top-level bias/confidence, never a trade-implying field ──────────────────────────────────────────


BRIEF_ROW = {
    "report_date": "2026-10-26",
    "generated_at": "2026-10-26T03:35:00",
    "bias": "neutral",
    "bias_score": 0.1,
    "confidence": 0.45,
    "model_fair_open": 144_181.0,
    "open_signal": "aligned_tradeable",
    "doc": {
        "overnight_summary": "quiet",
        "open_plan": "watch the rupee",
        "key_risks_today": ["FOMC"],
        "data_quality": {"ok": True},
        "gap": {"model_fair_open_inr": 144_181.0, "open_signal": "aligned_tradeable"},
        "synthesis": {"bias": "neutral", "trade_plan": "buy the dip", "positioning": {"cot_read": "long"}},
        "levels": [{"entry": 1, "note": "x"}],
    },
}


def test_brief_strips_every_trade_implying_field_at_every_depth(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def with_brief(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/brief":
            return {"available": True, "report_date": "2026-10-26", "row": BRIEF_ROW, "doc": BRIEF_ROW["doc"]}
        return await _fake_db(path, params)

    monkeypatch.setattr(gold, "_db_fetch", with_brief)
    b = client.get("/api/gold/brief").json()
    assert b["available"] and b["bias"] == "neutral" and b["confidence"] == 0.45 and b["generated_at"].endswith("+05:30")
    assert "open_signal" not in b and "aligned_tradeable" not in client.get("/api/gold/brief").text
    assert "buy the dip" not in client.get("/api/gold/brief").text
    assert b["doc"]["gap"] == {"model_fair_open_inr": 144_181.0} and b["doc"]["synthesis"] == {"bias": "neutral",
                                                                                                "positioning": {"cot_read": "long"}}
    assert b["doc"]["levels"] == [{"note": "x"}] and b["open_plan"] == "watch the rupee" and b["key_risks_today"] == ["FOMC"]
    assert b["stripped_fields"] == ["doc.gap.open_signal", "doc.synthesis.trade_plan", "doc.levels[0].entry", "row.open_signal"]
    o = client.get("/api/gold/overview").json()["brief"]
    assert o["bias"] == "neutral" and o["confidence"] == 0.45 and "open_signal" not in o and o["stripped_fields"]
    assert "aligned_tradeable" not in client.get("/api/gold/overview").text
    # negative control: a clean document is passed through untouched
    clean, found = gold.scrub_trade_fields({"a": 1, "b": {"c": [1, {"d": 2}]}})
    assert clean == {"a": 1, "b": {"c": [1, {"d": 2}]}} and found == []


# ── 11. crowd percentiles: the full-panel figures pass through, a window is labelled ───────────────────────────────


def test_cot_percentiles_pass_through_data_service_or_are_labelled_as_a_window(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    body = client.get("/api/gold/cot", params={"weeks": 4}).json()
    assert body["crowd"]["percentile_all"] == 50.0 and body["crowd"]["percentile_label"].startswith("all-history percentile")
    assert body["open_interest"]["pct_rank"] == 19.5 and body["open_interest"]["pct_rank_label"].startswith("all-history")
    assert body["crowd"]["percentile_window"] is not None and body["crowd"]["window_reports"] == 160
    assert body["crowd"]["window_label"] == "3-y percentile (160 reports)"

    async def no_summary(path: str, params: dict[str, Any]) -> Any:
        out = await _fake_db(path, params)
        return {"rows": out["rows"]} if path == "/db/gold/cot" else out

    monkeypatch.setattr(gold, "_db_fetch", no_summary)
    gold.STORE.invalidate()
    b2 = client.get("/api/gold/cot", params={"weeks": 4}).json()
    assert b2["crowd"]["percentile_all"] is None and b2["crowd"]["percentile_label"] == "3-y percentile (160 reports)"
    assert b2["open_interest"]["pct_rank_label"] == "3-y percentile (160 reports)" and b2["open_interest"]["pct_rank"] is not None


# ── 12. change_unit per gauge; multi-session MCX deltas; n = 1 statistics ──────────────────────────────────────────


def test_gauges_carry_their_change_unit(client: TestClient) -> None:
    g = {x["key"]: x for x in client.get("/api/gold/health").json()["gauges"]}
    assert g["trend"]["change_unit"] == "%" and g["real_yield"]["change_unit"] == "bp" and g["real_yield"]["change_bp"] is not None
    assert g["real_yield"]["change"] == g["real_yield"]["change_bp"]
    assert g["positioning"]["change_unit"] == "contracts" and g["etf"]["change_unit"] == "t" and g["dollar"]["change_unit"] == "%"
    assert g["shanghai"]["change_unit"] is None and g["shanghai"]["value"] is None  # unavailable in the fixture: no unit claimed
    u = gold._gauge("shanghai", "S", "SHANGHAI_PREMIUM_USD", -1.55, "$/oz", 47.36, "W", "2026-11-03", None, 4, "x", None, "r", "context", "e",
                    change_unit="$/oz")
    assert u["change"] == 47.36 and u["change_unit"] == "$/oz"  # $47/oz on the week, never "+47.36 %"


def test_mcx_oi_deltas_say_how_many_sessions_they_span() -> None:
    def row(d: str, oi: int, **kw: Any) -> dict[str, Any]:
        return {"trade_date": d, "exchange": "MCX", "symbol": "GOLD", "expiry": "2026-12-04", "settle": 140_000 + oi, "open_interest": oi,
                "quality": "proxy", **kw}

    out = gold.build_positioning_mcx([row("2026-10-29", 15_605), row("2026-11-03", 16_282), row("2026-11-04", 16_300)], date(2026, 11, 4))
    t = {x["trade_date"]: x for x in out["quadrant_tape"]}
    assert t["2026-11-03"]["doi"] == 677 and t["2026-11-03"]["sessions_spanned"] == 3 and t["2026-11-03"]["multi_session"] is True
    assert t["2026-11-03"]["span_note"] == "over 3 sessions (master skipped 2)"
    assert t["2026-11-04"]["sessions_spanned"] == 1 and t["2026-11-04"]["multi_session"] is False and t["2026-11-04"]["span_note"] is None
    assert t["2026-10-29"]["sessions_spanned"] is None  # no prior row: no delta, no span
    r = {x["trade_date"]: x for x in out["rows"]}
    assert r["2026-11-03"]["sessions_spanned"] == 3 and r["2026-10-29"]["sessions_spanned"] is None
    # data-service's own count (full closures subtracted) wins when the row carries it
    out2 = gold.build_positioning_mcx([row("2026-10-29", 15_605), row("2026-11-03", 16_282, sessions_spanned=2)], date(2026, 11, 4))
    assert out2["quadrant_tape"][-1]["sessions_spanned"] == 2 and out2["quadrant_tape"][-1]["span_note"] == "over 2 sessions (master skipped 1)"
    assert gold.sessions_between(date(2026, 10, 30), date(2026, 11, 2)) == 1 and gold.sessions_between(date(2026, 11, 2), date(2026, 11, 2)) == 0


def test_comex_tape_withholds_averages_and_quadrant_words_without_enough_sessions() -> None:
    def voi(d: date, oi: int, vol: int) -> dict[str, Any]:
        return {"trade_date": d.isoformat(), "product_code": "GC", "fut_or_opt": "F", "open_interest": oi, "oi_change": None,
                "total_volume": vol}

    closes = [{"report_date": (date(2026, 11, 2) + timedelta(days=k)).isoformat(), "value": 4000.0 - 30 * k} for k in range(4)]
    rows = [voi(date(2026, 11, 3), 400_000, 172_512)]
    one = gold.build_positioning_comex(rows, closes, [], [], date(2026, 11, 4))["quadrant_tape"]
    assert one[0]["doi"] is None and one[0]["label"] is None and one[0]["label_note"].startswith("no OI yet")
    assert one[0]["volume_vs_20d"] is None and one[0]["volume_avg_sessions"] == 0 and one[0]["dprice_pct"] == -0.75
    rows = [voi(date(2026, 10, 26) + timedelta(days=k), 400_000 + 100 * k, 170_000 + 1000 * k) for k in range(7)]
    many = gold.build_positioning_comex(rows, closes, [], [], date(2026, 11, 4))["quadrant_tape"]
    assert many[-1]["volume_vs_20d"] is not None and many[-1]["volume_avg_sessions"] == 6 and many[-1]["label_note"] is None
    assert many[4]["volume_vs_20d"] is None and many[5]["volume_vs_20d"] is not None  # the 5th prior session unlocks it


# ── 13. one carry convention; the /curve basis block names its clock ───────────────────────────────────────────────


def test_curve_mcx_basis_block_names_the_clock_and_prints_one_settlement_basis(client: TestClient) -> None:
    b = client.get("/api/gold/curve", params={"exchange": "MCX"}).json()["basis"]
    assert b["basis_clock"] == "settlement" and b["basis_date"] == "2026-10-22" and b["live_basis_pct"] is None
    # wave 1d: the desk's settlement-clock basis (band of its REAL session vs that session's close references, at 995), not
    # the stored derive row (0.4 in the fixture: GC=F daily close, 999)
    assert b["basis_pct"] != 0.4 and b["basis_source"].startswith("desk model") and b["basis_reference"] == "landed_995"
    assert "Thu 22 Oct settlement" in b["basis_label"] and b["ts"].endswith("+05:30")
    h = client.get("/api/gold/health").json()
    ib = next(g for g in h["gauges"] if g["key"] == "india_basis")
    p = client.get("/api/gold/premiums").json()["india"]
    assert ib["value"] == b["basis_pct"] == p["basis_pct"]  # ONE settlement basis on the page


# ── 14. every datetime carries an offset ───────────────────────────────────────────────────────────────────────────


NAIVE_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$")
ANY_DT = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def _walk(obj: Any, path: str = "$") -> Any:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:80]):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj


def test_every_datetime_string_served_carries_an_offset(client: TestClient) -> None:
    seen, naive = 0, []
    for name, path, params in ROUTES:
        body = client.get(path, params=params).json()
        for p, v in _walk(body, name):
            if isinstance(v, str) and ANY_DT.match(v):
                seen += 1
                if NAIVE_DT.match(v):
                    naive.append(f"{p}: {v}")
    assert seen > 50 and naive == [], naive
    assert gold._iso_any("2026-11-04T18:19:57") == "2026-11-04T23:49:57+05:30"  # stored naive UTC → IST with the offset
    assert gold._iso_any("2026-11-04") == "2026-11-04" and gold._iso_any(None) is None and gold._iso_any("x") is None
    assert gold._iso_any("2026-11-04T18:19:57Z") == "2026-11-04T23:49:57+05:30"
    b = client.get("/api/gold/bars", params={"symbol": "GC=F", "interval": "1d"}).json()
    assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", x["ts"]) for x in b["bars"])  # a date stays a date
    c = client.get("/api/gold/cot", params={"weeks": 2}).json()["latest"]
    assert c["release_at"] == "2026-10-24T01:00:00+05:30" and c["release_ist"] == "Sat 24 Oct 01:00 IST"
