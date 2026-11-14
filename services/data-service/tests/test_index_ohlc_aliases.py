"""/db/index-ohlc resolves an F&O underlying code to the index name the store actually keys (14 Nov 2026).

Why: the store follows NSE's own file naming ("NIFTY 50"), so `/db/index-ohlc/NIFTY` answered 200 with ZERO rows —
a silent empty that cost the game-plan page its prior-session tile (found by the F4 critic, patched there) and then
misled the F5 critic's own probe. Resolving it in the read fixes every caller at once. An exact match always wins,
so a real index whose name equals a code can never be shadowed by the alias table.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from fo_iv import reads  # noqa: E402


class _Store:
    """Answers the one SQL the read issues, from a dict of symbol → rows."""

    def __init__(self, data: dict[str, list[tuple[str, float]]]) -> None:
        self.data, self.asked = data, []

    def read(self, *a, **k):  # pragma: no cover - the records_sql path is patched in the fixture
        raise AssertionError("unused")


@pytest.fixture()
def store(monkeypatch: pytest.MonkeyPatch):
    held = {"NIFTY 50": [{"date": "2026-11-13", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "source": "f"}],
            "NIFTY BANK": [{"date": "2026-11-13", "open": 10.0, "high": 20.0, "low": 5.0, "close": 15.0, "source": "f"}],
            "FINNIFTY": [{"date": "2026-11-12", "open": 7.0, "high": 8.0, "low": 6.0, "close": 7.5, "source": "f"}]}
    asked: list[str] = []

    def fake_records_sql(_store, _sql, params, _dates):
        asked.append(str(params[0]))
        return list(held.get(str(params[0]), []))
    monkeypatch.setattr(reads.db, "records_sql", fake_records_sql)
    return asked


def test_an_fo_code_resolves_to_the_stored_index_name(store):
    out = reads.index_ohlc(object(), "NIFTY")
    assert out["symbol"] == "NIFTY 50" and len(out["rows"]) == 1 and out["as_of"] == "2026-11-13"
    assert store == ["NIFTY", "NIFTY 50"]                      # the exact name is tried FIRST, then the alias
    assert reads.index_ohlc(object(), "banknifty")["symbol"] == "NIFTY BANK"


def test_the_stored_name_still_works_and_costs_one_query(store):
    out = reads.index_ohlc(object(), "NIFTY 50")
    assert out["symbol"] == "NIFTY 50" and len(out["rows"]) == 1
    assert store == ["NIFTY 50"]                               # no alias lookup when the exact name answered


def test_an_exact_match_is_never_shadowed_by_the_alias_table(store):
    # FINNIFTY is BOTH an F&O code and (here) a stored name: the stored rows win, the alias is never consulted
    out = reads.index_ohlc(object(), "FINNIFTY")
    assert out["symbol"] == "FINNIFTY" and out["as_of"] == "2026-11-12" and store == ["FINNIFTY"]


def test_an_unknown_symbol_stays_an_honest_empty(store):
    out = reads.index_ohlc(object(), "NOT_AN_INDEX")
    assert out["rows"] == [] and out["as_of"] is None and out["symbol"] == "NOT_AN_INDEX"


def test_the_alias_table_covers_the_traded_underlyings():
    for code in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"):
        assert code in reads.INDEX_ALIASES, code
    assert reads.INDEX_ALIASES["NIFTY"] == "NIFTY 50" and reads.INDEX_ALIASES["BANKNIFTY"] == "NIFTY BANK"
