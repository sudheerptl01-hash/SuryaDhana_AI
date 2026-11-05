"""Market events merge (routers/markets.py) and the research library's file guard (routers/research.py)."""
import pytest
from fastapi import HTTPException

import routers.markets as m
import routers.research as rs


def test_merge_events_collapses_sources_and_keeps_the_filing_link():
    rows = [
        {"symbol": "TCS", "event_date": "2026-10-14", "kind": "RESULTS", "source": "calendar", "tags": "RESULTS,DIVIDEND",
         "company": "Tata Consultancy", "url": None, "first_seen": "2026-10-02", "turnover_cr": 2500},
        {"symbol": "TCS", "event_date": "2026-10-14", "kind": "RESULTS", "source": "board", "tags": "RESULTS",
         "company": None, "url": "https://nsearchives.nseindia.com/x.pdf", "first_seen": "2026-10-05", "turnover_cr": 2500},
        {"symbol": "SMALL", "event_date": "2026-10-14", "kind": "RESULTS", "source": "calendar", "tags": "RESULTS",
         "turnover_cr": 2},
        {"symbol": "TCS", "event_date": "2026-10-16", "kind": "DIVIDEND", "source": "action", "tags": "DIVIDEND",
         "turnover_cr": 2500},
    ]
    out = m.merge_events(rows)
    assert [(r["symbol"], r["event_date"], r["kind"]) for r in out] == [
        ("TCS", "2026-10-14", "RESULTS"), ("SMALL", "2026-10-14", "RESULTS"), ("TCS", "2026-10-16", "DIVIDEND")]
    tcs = out[0]
    assert tcs["sources"] == ["board", "calendar"]
    assert tcs["url"].endswith(".pdf") and tcs["company"] == "Tata Consultancy"
    assert tcs["tags"] == "DIVIDEND,RESULTS" and tcs["first_seen"] == "2026-10-02"


def test_research_lists_catalog_and_rejects_traversal():
    ids = [r["id"] for r in rs.list_research()["data"]]
    assert "reports/phase_b_extended/REPORT.md" in ids
    assert not any("ui_audit" in i for i in ids)
    for bad in ("../.env", "reports/../.env", "/etc/passwd", "docs/../../.env"):
        with pytest.raises(HTTPException) as e:
            rs.get_doc(bad)
        assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        rs.get_file("reports/phase_b/REPORT.md", "../../.env")
    assert e.value.status_code == 400
    doc = rs.get_doc("reports/phase_b/REPORT.md")
    assert doc["verdict"] == "PROMISING" and doc["markdown"].startswith("# ")


def test_merge_events_keeps_the_specific_board_meeting_purpose():
    # AEROFLEX, 14 Oct 2026: the board feed has boilerplate, the calendar says what the meeting is about
    rows = [{"symbol": "AEROFLEX", "event_date": "2026-10-14", "kind": "OTHER", "source": "board", "tags": "",
             "purpose": "Board Meeting Intimation",
             "detail": "AEROFLEX INDUSTRIES LIMITED has informed the Exchange about Board Meeting to be held on 14-Oct-2026 to consider Other business.",
             "url": "https://nsearchives.nseindia.com/x.xml"},
            {"symbol": "AEROFLEX", "event_date": "2026-10-14", "kind": "OTHER", "source": "calendar", "tags": "",
             "purpose": "Other business matters", "detail": "To consider and approve the Company s expansion plans, including further capacity enhancements."}]
    (ev,) = m.merge_events(rows)
    assert ev["detail"].startswith("To consider and approve the Company s expansion plans")
    assert ev["purpose"] == "Other business matters" and ev["url"].endswith("x.xml")      # filing link still from the board feed
