#!/usr/bin/env python3
"""Offline tests for nse_historical_ingest layers 2-4 (no network)."""
import io
import sys
import unittest
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nse_historical_ingest as ing  # noqa: E402


def _sec_csv(d: date) -> bytes:
    # Headers padded with spaces like the real NSE file; ' - ' delivery null.
    rows = [
        {"SYMBOL": "RELIANCE", " SERIES": "EQ", " DATE1": d.strftime("%d-%b-%Y"),
         " PREV_CLOSE": 100, " OPEN_PRICE": 101, " HIGH_PRICE": 105,
         " LOW_PRICE": 99, " LAST_PRICE": 104, " CLOSE_PRICE": 104,
         " AVG_PRICE": 102.5, " TTL_TRD_QNTY": 1000, " TURNOVER_LACS": 1.04,
         " NO_OF_TRADES": 50, " DELIV_QTY": 600, " DELIV_PER": 60.0},
        {"SYMBOL": "XYZFUT", " SERIES": "N1", " DATE1": d.strftime("%d-%b-%Y"),
         " PREV_CLOSE": 10, " OPEN_PRICE": 10, " HIGH_PRICE": 10,
         " LOW_PRICE": 10, " LAST_PRICE": 10, " CLOSE_PRICE": 10,
         " AVG_PRICE": 10, " TTL_TRD_QNTY": 5, " TURNOVER_LACS": 0.0005,
         " NO_OF_TRADES": 1, " DELIV_QTY": " -", " DELIV_PER": " -"},
    ]
    return pd.DataFrame(rows).to_csv(index=False).encode()


def _pr_zip(d: date) -> bytes:
    df = pd.DataFrame({
        "SYMBOL": ["RELIANCE"], "SERIES": ["EQ"], "OPEN": [101.0],
        "HIGH": [105.0], "LOW": [99.0], "CLOSE": [104.0], "LAST": [104.0],
        "PREVCLOSE": [100.0], "TOTTRDQTY": [1000], "TOTTRDVAL": [104000.0],
        "TIMESTAMP": [d.strftime("%d-%b-%Y")], "TOTALTRADES": [50],
        "ISIN": ["INE002A01018"],
    })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"cm{d:%d%b%Y}bhav.csv".upper(), df.to_csv(index=False))
    return buf.getvalue()


class TestParsing(unittest.TestCase):
    def test_sec_delivery_schema_and_values(self):
        df = ing.parse_sec_delivery(_sec_csv(date(2024, 1, 2)), date(2024, 1, 2))
        self.assertEqual(list(df.columns), ing.EOD_COLUMNS)
        self.assertEqual(len(df), 1)  # non-equity N1 series dropped
        row = df.iloc[0]
        self.assertEqual(row["ticker"], "RELIANCE")
        self.assertAlmostEqual(row["close"], 104.0)
        self.assertAlmostEqual(row["turnover"], 1.04 * 1e5)  # lacs -> rupees
        self.assertAlmostEqual(row["deliv_pct"], 60.0)

    def test_pr_zip_extraction_and_isin(self):
        df = ing.parse_pr_zip(_pr_zip(date(2024, 1, 2)), date(2024, 1, 2))
        self.assertEqual(df.iloc[0]["isin"], "INE002A01018")
        self.assertEqual(df.iloc[0]["source"], "pr_bhavcopy")

    def test_merge_enriches_isin(self):
        sec = ing.parse_sec_delivery(_sec_csv(date(2024, 1, 2)), date(2024, 1, 2))
        pr = ing.parse_pr_zip(_pr_zip(date(2024, 1, 2)), date(2024, 1, 2))
        merged = ing.merge_sources(sec, pr)
        self.assertEqual(merged.iloc[0]["isin"], "INE002A01018")
        self.assertEqual(merged.iloc[0]["source"], "sec_delivery")  # OHLC kept


class TestStorageAndFeatures(unittest.TestCase):
    def test_upsert_is_idempotent(self):
        store = ing.DuckDBStore(":memory:")
        df = ing.parse_sec_delivery(_sec_csv(date(2024, 1, 2)), date(2024, 1, 2))
        store.upsert(df)
        store.upsert(df)  # second time must not duplicate
        n = store.con.execute("SELECT count(*) FROM equity_eod").fetchone()[0]
        self.assertEqual(n, 1)
        self.assertEqual(store.last_date(), date(2024, 1, 2))
        store.close()

    def test_build_features_produces_labels(self):
        store = ing.DuckDBStore(":memory:")
        rng = np.random.default_rng(1)
        state = {"AAA": 100.0}
        for d in ing.trading_days(date(2024, 1, 1), date(2024, 3, 31)):
            raw = ing._synth_sec_csv(d, ["AAA"], rng, state)
            store.upsert(ing.parse_sec_delivery(raw, d))
        n = ing.build_features(store.con)
        self.assertGreater(n, 0)
        cols = store.con.execute("PRAGMA table_info('equity_features')").df()["name"].tolist()
        for expected in ("rsi_14", "atr_pct", "fwd_ret_3d", "label_up_3d", "deliv_pct_z_20"):
            self.assertIn(expected, cols)
        store.close()


class TestDateHelpers(unittest.TestCase):
    def test_trading_days_excludes_weekends(self):
        days = ing.trading_days(date(2024, 1, 1), date(2024, 1, 7))
        self.assertTrue(all(d.weekday() < 5 for d in days))
        self.assertEqual(len(days), 5)  # Mon-Fri of that week


if __name__ == "__main__":
    unittest.main(verbosity=2)
