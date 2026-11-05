"""EIA without a key (5 Nov 2026): the CMDT EIA panel read OFFLINE "EIA_API_KEY not set". EIA publishes the same series
as a keyless public file; the board now falls back to it, checks the file's Sourcekey, and labels the source."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

import routers.commodity as cm

FIXTURE = Path(__file__).parent / "fixtures" / "eia_MCRFPUS2m.xls"   # EIA's public monthly file, downloaded 5 Nov 2026


def test_the_public_file_parses_into_the_v2_shape() -> None:
    pts = cm._parse_eia_xls(FIXTURE.read_bytes(), "MCRFPUS2", "monthly", length=60)
    assert len(pts) == 60 and pts[-1] == {"date": "2026-08", "value": 13965.0}
    assert all(len(p["date"]) == 7 for p in pts) and pts[0]["date"] < pts[-1]["date"]


def test_a_file_of_another_series_is_refused() -> None:
    """Negative control: a moved or renamed series must never fill another series' panel."""
    with pytest.raises(ValueError, match="expected 'WCESTUS1'"):
        cm._parse_eia_xls(FIXTURE.read_bytes(), "WCESTUS1", "weekly")


def _stub_board(monkeypatch: pytest.MonkeyPatch, *, key: str, xls: Any, rest: Any) -> None:
    monkeypatch.setattr(cm, "EIA_API_KEY", key)
    monkeypatch.setattr(cm, "_eia_series_xls", xls)
    monkeypatch.setattr(cm, "_eia_series", rest)
    monkeypatch.setattr(cm, "_cache_get", lambda k: None)
    monkeypatch.setattr(cm, "_cache_set", lambda k, v, ttl: None)

    async def chart(symbol: str, rng: str, interval: str) -> dict[str, Any]:
        raise RuntimeError("no network in tests")

    async def fred(series_id: str, limit: int = 120) -> list[dict[str, Any]]:
        return []
    monkeypatch.setattr(cm, "_yahoo_chart", chart)
    monkeypatch.setattr(cm, "_fred_series", fred)


def test_without_a_key_the_board_uses_the_public_file_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    async def xls(facet: str, freq: str, length: int = 60) -> list[dict[str, Any]]:
        calls.append(facet)
        return [{"date": "2026-10-30", "value": 409760.0}] if freq == "weekly" else [{"date": "2026-08", "value": 13965.0}]

    async def rest(*a: Any, **k: Any) -> list[dict[str, Any]]:
        raise AssertionError("the keyed REST path must not run without a key")
    _stub_board(monkeypatch, key="", xls=xls, rest=rest)
    eia = asyncio.run(cm.commodity_overview())["fundamentals"]["eia"]
    assert eia["available"] is True and "keyless" in eia["source"] and "reason" not in eia
    assert sorted(calls) == ["MCRFPUS2", "WCESTUS1"] and eia["series"][0]["latest"] == {"date": "2026-10-30", "value": 409760.0}


def test_negative_controls_both_paths_down_is_unavailable_and_a_key_uses_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    async def down(*a: Any, **k: Any) -> list[dict[str, Any]]:
        raise RuntimeError("HTTP 503")
    _stub_board(monkeypatch, key="", xls=down, rest=down)
    eia = asyncio.run(cm.commodity_overview())["fundamentals"]["eia"]
    assert eia["available"] is False and "public file did not answer" in eia["reason"]       # never fabricated numbers

    used: list[str] = []

    async def rest(route: str, facet: str, freq: str, length: int = 60) -> list[dict[str, Any]]:
        used.append(facet)
        return [{"date": "2026-10-30", "value": 1.0}]
    _stub_board(monkeypatch, key="k", xls=down, rest=rest)
    eia = asyncio.run(cm.commodity_overview())["fundamentals"]["eia"]
    assert eia["available"] is True and eia["source"] == "EIA v2 API" and sorted(used) == ["MCRFPUS2", "WCESTUS1"]
