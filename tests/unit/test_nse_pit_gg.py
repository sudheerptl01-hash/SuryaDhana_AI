"""Insider trades from NSE's single-filing PIT feed (since 5 May 2026) and the future-date guard on the old feed."""
import sys
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))
import nse_filings as nf  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "pit_reliance_20260522.xml"


def test_parse_pit_xbrl_real_filing():
    rows = nf.parse_pit_xbrl(FIXTURE.read_text(), "RELIANCE", "384", "22-May-2026 22:07:04")
    assert len(rows) == 1
    r = rows[0]
    assert r["record_id"] == "gg|384|Disclosure1" and r["person"] == "Anish Shah"
    assert r["txn_type"] == "Buy" and r["mode"] == "Inheritance" and r["qty"] == 880 and r["value"] == 1196580
    assert r["from_date"] == "2026-05-20" and r["intimation_date"] == "2026-05-22"     # dated by the broadcast


def test_old_feed_never_dates_after_the_broadcast():
    df = nf.parse_insider([{"did": 1, "acqName": "X", "intimDt": "29-May-2028", "date": "30-May-2025 18:46",
                            "secAcq": "10", "acqfromDt": "08-May-2025"}], "DMART")
    assert df.iloc[0]["intimation_date"] == "2025-05-30"


class _Store:
    def __init__(self):
        self.frames = []

    def known_pit_gg_apps(self):
        return {"1"}

    def upsert_insider_trades(self, df):
        self.frames.append(df)
        return len(df)


class _Client:
    def get(self, url, params=None):
        req = httpx.Request("GET", url)
        if url.endswith("corporates-pit-gg"):
            return httpx.Response(200, request=req, json={"data": [
                {"appId": "1", "symbol": "OLD", "xmlFileName": "https://x/old.xml", "broadcastDateTime": "01-Oct-2026 10:00:00"},
                {"appId": "384", "symbol": "RELIANCE", "xmlFileName": "https://x/rel.xml", "broadcastDateTime": "22-May-2026 22:07:04"}]})
        return httpx.Response(200, request=req, text=FIXTURE.read_text())


def test_ingest_skips_known_filings_and_stores_new(tmp_path):
    from datetime import date
    store = _Store()
    out = nf.ingest_pit_gg(store, date(2026, 10, 1), date(2026, 10, 12), client=_Client(), xbrl_cache=tmp_path, sleep_s=0)
    assert out["skipped_known"] == 1 and out["parsed"] == 1 and out["rows"] == 1
    assert list(pd.concat(store.frames)["symbol"]) == ["RELIANCE"]


def test_old_feed_rejects_pre_2000_typos():
    df = nf.parse_insider([{"did": 2, "acqName": "Y", "intimDt": "23-Jan-1925", "date": "24-Jan-2025 10:00",
                            "secAcq": "5", "acqfromDt": "20-Jan-2025"}], "X")
    assert df.iloc[0]["intimation_date"] == "2025-01-24"


def test_parse_pit_xbrl_unescapes_entities():
    xml = FIXTURE.read_text().replace("Anish Shah", "Odd &amp; Even Trades")
    assert nf.parse_pit_xbrl(xml, "RELIANCE", "384", "22-May-2026 22:07:04")[0]["person"] == "Odd & Even Trades"
