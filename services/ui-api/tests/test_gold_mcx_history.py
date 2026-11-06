"""GOLD › POSITIONING p.mcx.history (6 Nov 2026, owner request "which positions got closed, who are short, who are longs, on a
daily and weekly basis, and choose the contract"): `GET /api/gold/positioning/mcx-history?family=&expiry=&window=D|W|M`.

The data is data-service's `gold_mcx_daily` (ICICI Breeze daily bars per LIVE MCX gold contract, catalog row BREEZE_DAILY,
PUBLISH-CONTEXT · arithmetic). Offline: test_gold's autouse fakes (no network, pinned clock Mon 26 Oct 2026 10:00 IST) with
`_db_fetch` wrapped so `/db/gold/mcx/daily` serves the hand-computed fixture below.

Checks: D / W / M aggregation (each period's last close and OI vs the previous period's, volume summed, ISO weeks, a skipped
session named); the quadrant word comes from the ONE shared rule (`quadrant_label`; negative control: a falling-price /
rising-OI period is "short build-up", never "long build-up"); opened / closed / unchanged from ΔOI; the family's OI split
over its live expiries sums to 100 % and leaves an expired contract out; the default expiry is the front live one; the
BREEZE_DAILY gate; degradation when data-service is away or has no rows; 422s; the 300 s memo.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from routers import gold  # noqa: E402
from test_gold import DB_CALLS, NOW, _app, _fake_db, _offline, catalog_rows  # noqa: E402,F401 — the autouse fakes and the app

URL = "/api/gold/positioning/mcx-history"
NOV, DEC, EXPIRED = "2026-11-30", "2026-12-31", "2026-10-23"   # today is Mon 26 Oct: the 23 Oct contract has expired

# GOLDTEN NOV-26: (trade_date, close ₹/10 g, OI lots, volume lots). 30 Sep is W40 / September; W41 has no rows (the store
# skipped it); Wed 21 Oct is missing (the 22 Oct delta spans two sessions); Tue 20 Oct (Dussehra, morning closure only —
# an MCX session) has no volume.
NOV_BARS: list[tuple[str, float, int, int | None]] = [
    ("2026-09-30", 990.0, 80, 5),
    ("2026-10-12", 1000.0, 100, 10),
    ("2026-10-13", 1010.0, 110, 20),
    ("2026-10-14", 1000.0, 120, 30),     # price down, OI up → short build-up (the negative control)
    ("2026-10-15", 1020.0, 115, 40),     # price up, OI down → short covering
    ("2026-10-16", 1010.0, 105, 50),     # price down, OI down → long unwinding
    ("2026-10-19", 1030.0, 105, 60),     # OI unchanged
    ("2026-10-20", 1040.0, 130, None),
    ("2026-10-22", 1020.0, 140, 80),
    ("2026-10-23", 1000.0, 150, 90),
]


def _row(day: str, expiry: str, close: float, oi: int, vol: int | None, family: str = "GOLDTEN") -> dict[str, Any]:
    return {"trade_date": day, "family": family, "expiry": expiry, "open": close, "high": close + 5, "low": close - 5, "close": close,
            "volume": vol, "open_interest": oi, "source": "breeze_daily", "quality": "broker",
            "release_at": f"{day}T04:05:00+00:00", "first_seen_at": f"{day}T04:05:00+00:00", "unit": "INR/10g"}


def fixture_rows() -> list[dict[str, Any]]:
    rows = [_row(d, NOV, c, oi, v) for d, c, oi, v in NOV_BARS]
    rows += [_row("2026-10-22", DEC, 1030.0, 45, 7), _row("2026-10-23", DEC, 1012.0, 50, 9)]
    rows.append(_row("2026-10-23", EXPIRED, 995.0, 999, 400))     # expired by today: never in the split, never the default
    return rows


def _wrap(rows: list[dict[str, Any]] | None = None, catalog: list[dict[str, Any]] | None = None, down: bool = False) -> Any:
    rows = fixture_rows() if rows is None else rows

    async def db(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/mcx/daily":
            DB_CALLS.append((path, dict(params)))
            if down:
                raise gold.StoreUnavailable("data-service unreachable (ConnectError)")
            return {"rows": [r for r in rows if r["family"] == params.get("family")], "source": "breeze_daily"}
        if path == "/db/gold/catalog" and catalog is not None:
            return {"rows": catalog}
        return await _fake_db(path, params)

    return db


@pytest.fixture
def client() -> Any:
    with TestClient(_app()) as c:
        yield c


def _get(client: TestClient, **params: Any) -> dict[str, Any]:
    r = client.get(URL, params=params)
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _by(periods: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {p["period"]: p for p in periods}


# ══ D / W / M aggregation ══════════════════════════════════════════════════════════════════════════════════════════

def test_daily_periods_are_each_session_against_the_previous_one(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    p = _get(client, family="GOLDTEN", expiry=NOV, window="D")
    assert p["family"] == "GOLDTEN" and p["expiry"] == NOV and p["expiry_label"] == "NOV-26" and p["window"] == "D"
    assert p["badge"] == "arithmetic" and p["catalog_ids"] == ["BREEZE_DAILY"] and p["published"] is True and p["note"] is None
    assert p["unit"] == "₹ per 10 g" and p["oi_unit"] == "lots" and p["since"] == "2026-09-30"
    assert "ok" not in p and p["store_errors"] is None
    d = _by(p["periods"])
    assert [x["period"] for x in p["periods"]] == [b[0] for b in NOV_BARS]               # chronological, one per session
    first = d["2026-09-30"]
    assert first["close_chg_pct"] is None and first["oi_chg"] is None and first["positions"] is None and first["label"] is None
    assert d["2026-10-13"]["close_chg_pct"] == 1.0 and d["2026-10-13"]["oi_chg"] == 10 and d["2026-10-13"]["volume"] == 20
    assert d["2026-10-14"]["close_chg_pct"] == -0.99 and d["2026-10-14"]["oi_chg"] == 10
    assert d["2026-10-15"]["close_chg_pct"] == 2.0 and d["2026-10-15"]["oi_chg"] == -5
    assert d["2026-10-23"]["close"] == 1000.0 and d["2026-10-23"]["oi"] == 150 and d["2026-10-23"]["period_end"] == "2026-10-23"
    assert d["2026-10-20"]["volume"] is None and d["2026-10-20"]["volume_missing"] == 1
    # a skipped session is named, never printed as one day's move: 12 Oct spans 1 Oct + 5–9 Oct + 12 Oct (2 Oct closed)
    assert d["2026-10-12"]["sessions_spanned"] == 7 and "Δ over 7 sessions" in d["2026-10-12"]["note"]
    assert d["2026-10-22"]["sessions_spanned"] == 2 and "Δ over 2 sessions" in d["2026-10-22"]["note"]
    assert d["2026-10-20"]["sessions_spanned"] == 1 and d["2026-10-20"]["note"] is None           # Dussehra: morning closure only
    assert not any(x["partial"] for x in p["periods"]) and not any(x["mechanical"] for x in p["periods"])


def test_weekly_periods_are_iso_weeks_ending_at_their_last_session(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    p = _get(client, family="GOLDTEN", expiry=NOV, window="w")                          # the window is case-insensitive
    assert p["window"] == "W" and [x["period"] for x in p["periods"]] == ["2026-W40", "2026-W42", "2026-W43"]
    w40, w42, w43 = p["periods"]
    assert w40["oi_chg"] is None and w40["label"] is None and w40["sessions"] == 1
    # W42 (12–16 Oct) vs W40's last (30 Sep: 990 / 80): the week's LAST close and OI, volume summed over its five sessions
    assert (w42["period_start"], w42["period_end"], w42["sessions"]) == ("2026-10-12", "2026-10-16", 5)
    assert w42["close"] == 1010.0 and w42["close_chg_pct"] == 2.02 and w42["oi"] == 105 and w42["oi_chg"] == 25
    assert w42["volume"] == 10 + 20 + 30 + 40 + 50 and w42["positions"] == "opened" and w42["label"] == "long build-up"
    assert w42["period_label"] == "W42 · 12 Oct–16 Oct"
    # W43 (19–23 Oct) vs W42's last (1010 / 105): price down, OI up — "short build-up", NOT "long build-up"
    assert w43["close"] == 1000.0 and w43["close_chg_pct"] == -0.99 and w43["oi_chg"] == 45
    assert w43["label"] == "short build-up" and w43["label"] != "long build-up"
    assert w43["volume"] == 60 + 80 + 90 and w43["volume_missing"] == 1 and w43["sessions"] == 4
    assert w43["partial"] is False          # Mon 26 Oct: no session of W43 is left to come
    assert w43["sessions_spanned"] is None  # D only


def test_monthly_periods_and_the_running_month(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    p = _get(client, family="GOLDTEN", expiry=NOV, window="M")
    assert [(x["period"], x["period_label"]) for x in p["periods"]] == [("2026-09", "Sep 2026"), ("2026-10", "Oct 2026")]
    sep, octo = p["periods"]
    assert sep["oi_chg"] is None and sep["positions"] is None and sep["partial"] is False
    assert octo["close"] == 1000.0 and octo["close_chg_pct"] == 1.01 and octo["oi"] == 150 and octo["oi_chg"] == 70
    assert octo["volume"] == 10 + 20 + 30 + 40 + 50 + 60 + 80 + 90 and octo["volume_missing"] == 1 and octo["sessions"] == 9
    assert octo["positions"] == "opened" and octo["label"] == "long build-up"
    assert octo["partial"] is True and "month to date" in octo["note"]          # October still has sessions to come


# ══ the quadrant rule is the shared one; opened / closed from ΔOI ══════════════════════════════════════════════════

def test_labels_come_from_the_shared_quadrant_rule(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    d = _by(_get(client, family="GOLDTEN", expiry=NOV, window="D")["periods"])
    assert d["2026-10-13"]["label"] == "long build-up"
    assert d["2026-10-14"]["label"] == "short build-up"          # negative control: falling price + rising OI
    assert d["2026-10-14"]["label"] != "long build-up"
    assert d["2026-10-15"]["label"] == "short covering" and d["2026-10-16"]["label"] == "long unwinding"
    for x in d.values():                                         # every word IS quadrant_label(Δclose, ΔOI)
        if x["oi_chg"] is not None:
            assert x["label"] == gold.quadrant_label(x["close_chg_pct"], x["oi_chg"])
    # the route has no rule of its own: swap the shared function and every label follows it
    gold._ttl.clear()
    monkeypatch.setattr(gold, "quadrant_label", lambda dp, doi: None if dp is None or doi is None else "SHARED-RULE")
    labels = {x["label"] for x in _get(client, family="GOLDTEN", expiry=NOV, window="W")["periods"] if x["oi_chg"] is not None}
    assert labels == {"SHARED-RULE"}


def test_opened_closed_unchanged_follow_the_oi_change(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    d = _by(_get(client, family="GOLDTEN", expiry=NOV, window="D")["periods"])
    assert [d[k]["positions"] for k in ("2026-10-13", "2026-10-15", "2026-10-16", "2026-10-19")] == ["opened", "closed", "closed", "unchanged"]
    assert all((x["positions"] == "opened") == (x["oi_chg"] is not None and x["oi_chg"] > 0) for x in d.values())
    assert all((x["positions"] == "closed") == (x["oi_chg"] is not None and x["oi_chg"] < 0) for x in d.values())
    assert gold.positions_word(None) is None and gold.positions_word(0) == "unchanged"


def test_expiry_month_periods_are_flagged_mechanical() -> None:
    rows = [_row(d, EXPIRED, c, oi, v) for d, c, oi, v in NOV_BARS]
    out = gold.mcx_history_periods(rows, "D", date(2026, 10, 1), date(2026, 10, 23))
    assert all(x["mechanical"] == (x["period_end"] >= "2026-10-01") for x in out)
    assert "partly mechanical" in (out[-1]["note"] or "") and out[0]["mechanical"] is False


# ══ where the open positions sit: the family's split over its live expiries ═══════════════════════════════════════

def test_the_contract_split_sums_to_100_and_leaves_expired_contracts_out(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    p = _get(client, family="GOLDTEN", window="D")                      # no expiry: the front LIVE expiry
    assert p["expiry"] == NOV and p["expiry_source"].startswith("front")
    assert p["contracts_date"] == "2026-10-23" and p["family_oi"] == 200
    assert [(c["expiry"], c["oi"], c["share_pct"], c["selected"]) for c in p["contracts"]] == [(NOV, 150, 75.0, True), (DEC, 50, 25.0, False)]
    assert abs(sum(c["share_pct"] for c in p["contracts"]) - 100.0) < 0.05
    assert EXPIRED not in {c["expiry"] for c in p["contracts"]}          # 999 lots on an expired contract are not "open"
    dec = _get(client, family="GOLDTEN", expiry=DEC, window="D")         # picking another contract moves only the selection
    assert [c["selected"] for c in dec["contracts"]] == [False, True] and [x["period"] for x in dec["periods"]] == ["2026-10-22", "2026-10-23"]
    assert dec["periods"][-1]["oi_chg"] == 5 and dec["periods"][-1]["positions"] == "opened"


def test_an_expired_contract_is_refused_with_a_reason(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    p = _get(client, family="GOLDTEN", expiry=EXPIRED, window="D")
    assert p["periods"] == [] and "expired" in p["note"] and "live expiries only" in p["note"]
    assert [c["expiry"] for c in p["contracts"]] == [NOV, DEC]


def test_a_family_reads_its_own_rows_only() -> None:
    other = [_row("2026-10-23", NOV, 50000.0, 7, 1, family="GOLDM")]
    out = gold.build_mcx_history(fixture_rows() + other, "GOLDTEN", None, "D", NOW.date(),
                                 {r["series_id"]: r for r in catalog_rows()})
    assert out["family_oi"] == 200 and all(x["close"] != 50000.0 for x in out["periods"])


# ══ the catalog gate and degradation ═════════════════════════════════════════════════════════════════════════════

def test_without_a_publish_verdict_nothing_renders(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    no_row = [r for r in catalog_rows() if r["series_id"] != "BREEZE_DAILY"]
    monkeypatch.setattr(gold, "_db_fetch", _wrap(catalog=no_row))
    p = _get(client, family="GOLDTEN", expiry=NOV, window="D")
    assert p["published"] is False and p["periods"] == [] and p["contracts"] == [] and p["note"] == "no verdict — not published"
    assert p["freshness"]["state"] == "unavailable"


def test_data_service_away_degrades_to_an_empty_ok_false_payload(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap(down=True))
    r = client.get(URL, params={"family": "GOLDTEN", "expiry": NOV, "window": "W"})
    assert r.status_code == 200
    p = r.json()
    assert p["ok"] is False and p["error_info"]["code"] == "upstream_down" and "unreachable" in p["error_info"]["message"]
    assert p["periods"] == [] and p["contracts"] == [] and p["freshness"]["state"] == "unavailable"
    assert "/db/gold/mcx/daily" in (p["store_errors"] or {}) and p["badge"] == "arithmetic"
    assert gold._ttl.get("mcxhist:GOLDTEN:2026-11-30:W") is None          # a degraded answer is never memoised


def test_no_stored_rows_is_a_state_not_a_crash(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap(rows=[]))
    p = _get(client, family="GOLDPETAL", window="M")
    assert p["ok"] is False and p["error_info"]["code"] == "state" and p["periods"] == [] and p["expiry"] is None
    assert p["note"] == "no live GOLDPETAL contract in the stored Breeze daily bars"


def test_bad_input_is_a_422(client: TestClient) -> None:
    assert client.get(URL, params={"family": "SILVER"}).status_code == 422
    assert client.get(URL, params={"family": "GOLD", "expiry": "30-Nov"}).status_code == 422
    assert client.get(URL, params={"family": "GOLD", "window": "Q"}).status_code == 422


def test_answers_are_memoised_for_300_s(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    a = _get(client, family="GOLDTEN", expiry=NOV, window="D")
    n = sum(1 for path, _ in DB_CALLS if path == "/db/gold/mcx/daily")
    b = _get(client, family="GOLDTEN", expiry=NOV, window="D")
    assert a == b and sum(1 for path, _ in DB_CALLS if path == "/db/gold/mcx/daily") == n == 1
    assert gold.MCX_HISTORY_TTL_S == 300.0


def test_the_read_says_who_is_not_visible_and_describes_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _wrap())
    p = _get(client, family="GOLDTEN", window="W")
    assert "OI up = positions opened" in p["read"] and "OI down = positions closed" in p["read"]
    assert "every contract has a long and a short" in p["read"] and "describes, does not predict" in p["read"]
    assert "live expiries only" in p["read"].lower() and "quadrant_label" in p["rule"]
    assert "score" not in p and not any(k in p for k in ("signal", "bias", "direction"))
