"""NSE corporate events (services/data-service/nse_events.py): classification and feed parsing."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
import nse_events as ne  # noqa: E402


@pytest.mark.parametrize("text,kind,tags", [
    ("Financial Results", "RESULTS", "RESULTS"),
    ("Financial Results/Dividend", "RESULTS", "RESULTS,DIVIDEND"),
    ("Interim Dividend - Rs 5 Per Share", "DIVIDEND", "DIVIDEND"),
    ("Face Value Split (Sub-Division) - From Rs 5/- Per Share To Re 1/- Per Share", "SPLIT", "SPLIT"),
    ("Rights 2:25 @ Premium Rs 17/-", "RIGHTS", "RIGHTS"),
    ("Bonus 1:1", "BONUS", "BONUS"),
    ("Buy Back of shares", "BUYBACK", "BUYBACK"),
    ("Fund Raising/Other business matters", "FUND RAISE", "FUND RAISE"),
    ("Other business matters", "OTHER", ""),
])
def test_classify(text, kind, tags):
    assert ne.classify(text) == (kind, tags)


def test_parse_calendar_and_dates():
    rows = ne.parse_calendar([
        {"symbol": "adroitind ", "company": "Adroit Industries", "purpose": "Financial Results",
         "bm_desc": "Board Meeting to be held on 12-Oct-2026 …", "date": "12-Oct-2026"},
        {"symbol": "BAD", "purpose": "Financial Results", "date": "-"},          # no date → dropped
    ])
    assert len(rows) == 1
    r = rows[0]
    assert (r["symbol"], r["event_date"], r["kind"], r["source"]) == ("ADROITIND", "2026-10-12", "RESULTS", "calendar")


def test_parse_actions_keeps_record_date_and_skips_debt_series():
    rows = ne.parse_actions([
        {"symbol": "OLAELEC", "series": "EQ", "comp": "Ola Electric", "subject": "Rights 2:25 @ Premium Rs 17/-",
         "exDate": "13-Oct-2026", "recDate": "13-Oct-2026", "caBroadcastDate": None},
        {"symbol": "SOMENCD", "series": "N1", "subject": "Interest Payment", "exDate": "13-Oct-2026"},
    ])
    assert [r["symbol"] for r in rows] == ["OLAELEC"]
    assert rows[0]["record_date"] == "2026-10-13" and rows[0]["kind"] == "RIGHTS"


def test_parse_board_rejects_non_https_attachments():
    rows = ne.parse_board([{"bm_symbol": "X", "bm_date": "14-Oct-2026", "bm_desc": "Quarterly results",
                            "attachment": "javascript:alert(1)", "bm_timestamp": "11-Oct-2026 13:37:34"}])
    assert rows[0]["url"] is None and rows[0]["kind"] == "RESULTS"


class _Store:
    def __init__(self):
        self.frames = []

    def upsert_nse_events(self, df):
        self.frames.append(df)
        return len(df)


class _Client:
    """Feeds: calendar OK, board fails, actions OK — one failure must not lose the others."""
    def get(self, url, params=None):
        import httpx
        req = httpx.Request("GET", url)
        if url.endswith("corporate-board-meetings"):
            return httpx.Response(503, request=req)
        if url.endswith("event-calendar"):
            return httpx.Response(200, request=req, json=[
                {"symbol": "TCS", "purpose": "Financial Results", "date": "09-Oct-2026"},
                {"symbol": "TCS", "purpose": "Financial Results", "date": "09-Oct-2026"}])   # duplicate
        return httpx.Response(200, request=req, json=[
            {"symbol": "TCS", "series": "EQ", "subject": "Interim Dividend - Rs 11", "exDate": "16-Oct-2026"}])


def test_ingest_survives_a_failed_feed_and_dedupes():
    store = _Store()
    out = ne.ingest_events(store, client=_Client(), sleep_s=0)
    assert out["calendar"] == 2 and out["action"] == 1          # parsed rows, before de-duplication
    assert [f["feed"] for f in out["failures"]] == ["board"]
    assert out["upserted"] == 2                                   # duplicate calendar row collapsed
