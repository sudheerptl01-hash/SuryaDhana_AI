#!/usr/bin/env python3
"""Tests for promoter_data parsing/output logic (no network required).

These feed NSE-shaped JSON payloads through the defensive parser and assert
that promoter/public/pledged values are extracted correctly. Run with:

    python3 -m unittest tests/test_parsing.py -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import promoter_data as pd  # noqa: E402


# A representative NSE shareholding-pattern payload (category rows with a
# percentage field), plus identifying/period fields at the top level.
SHP_PAYLOAD = {
    "companyName": "Reliance Industries Ltd",
    "asOnDate": "31-Mar-2025",
    "data": {
        "shareHolding": [
            {"category": "Promoter & Promoter Group", "percentageOfShares": "50.30"},
            {"category": "Public", "percentageOfShares": "49.70"},
        ]
    },
}

# A quote-equity style payload carrying a pledged/encumbered percentage.
QUOTE_PAYLOAD = {
    "info": {"companyName": "Reliance Industries Ltd", "symbol": "RELIANCE"},
    "promoterInfo": {"pledgedPercentage": "0.96", "label": "Pledge / encumbrance"},
}


class TestShareholdingParser(unittest.TestCase):
    def test_extracts_promoter_public_company_period(self):
        rec = pd.PromoterRecord(symbol="RELIANCE")
        pd._parse_shareholding(SHP_PAYLOAD, rec)
        self.assertAlmostEqual(rec.promoter_pct, 50.30)
        self.assertAlmostEqual(rec.public_pct, 49.70)
        self.assertEqual(rec.company, "Reliance Industries Ltd")
        self.assertEqual(rec.period, "31-Mar-2025")

    def test_pledge_extraction_from_quote(self):
        pct = pd._find_pct(QUOTE_PAYLOAD, ("pledge", "encumber"))
        self.assertAlmostEqual(pct, 0.96)

    def test_missing_data_stays_none(self):
        rec = pd.PromoterRecord(symbol="EMPTY")
        pd._parse_shareholding({"foo": "bar"}, rec)
        self.assertIsNone(rec.promoter_pct)
        self.assertIsNone(rec.public_pct)

    def test_to_float_handles_commas_and_symbols(self):
        self.assertAlmostEqual(pd._to_float("1,234.5%"), 1234.5)
        self.assertAlmostEqual(pd._to_float("50.30"), 50.30)
        self.assertIsNone(pd._to_float(None))
        self.assertIsNone(pd._to_float("n/a"))


class TestDemoAndOutput(unittest.TestCase):
    def test_demo_loader_returns_known_symbols(self):
        recs = pd.load_demo_records(["RELIANCE", "TCS"])
        self.assertEqual(len(recs), 2)
        self.assertAlmostEqual(recs[0].promoter_pct, 50.30)
        self.assertTrue(recs[0].source.startswith("DEMO"))

    def test_demo_loader_flags_unknown_symbol(self):
        recs = pd.load_demo_records(["NOTREAL"])
        self.assertEqual(recs[0].error, "not in sample set")

    def test_csv_roundtrip(self):
        recs = pd.load_demo_records(["RELIANCE", "TCS"])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.csv"
            pd.write_csv(recs, out)
            text = out.read_text()
            self.assertIn("symbol,company,period", text)
            self.assertIn("RELIANCE", text)

    def test_json_roundtrip(self):
        recs = pd.load_demo_records(["RELIANCE"])
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.json"
            pd.write_json(recs, out)
            data = json.loads(out.read_text())
            self.assertEqual(data[0]["symbol"], "RELIANCE")


class TestSymbolResolution(unittest.TestCase):
    def test_default_is_nifty50(self):
        ns = type("NS", (), {"symbols": None, "symbols_file": None})()
        self.assertEqual(len(pd.resolve_symbols(ns)), 50)

    def test_explicit_symbols_uppercased(self):
        ns = type("NS", (), {"symbols": ["reliance", "tcs"], "symbols_file": None})()
        self.assertEqual(pd.resolve_symbols(ns), ["RELIANCE", "TCS"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
