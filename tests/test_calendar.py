#!/usr/bin/env python3
"""Offline tests for the session calendar and the continuity check (no network)."""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nse_historical_ingest as ing  # noqa: E402


class TestSpecialSessions(unittest.TestCase):
    def test_weekend_budget_and_muhurat_sessions_included(self):
        days = ing.trading_days(date(2025, 1, 27), date(2025, 2, 7))
        self.assertIn(date(2025, 2, 1), days)        # Saturday, Union Budget
        self.assertNotIn(date(2025, 2, 2), days)     # plain Sunday
        self.assertIn(date(2026, 2, 1), ing.trading_days(date(2026, 1, 30), date(2026, 2, 2)))   # Sunday Budget
        self.assertIn(date(2023, 11, 12), ing.trading_days(date(2023, 11, 10), date(2023, 11, 13)))  # Sunday Muhurat

    def test_saturday_special_live_sessions_included(self):
        for d in (date(2024, 1, 20), date(2024, 3, 2), date(2024, 5, 18)):
            self.assertIn(d, ing.trading_days(d, d))

    def test_muhurat_2025_is_a_session_and_not_a_holiday(self):
        self.assertNotIn("2025-10-21", ing.NSE_TRADING_HOLIDAYS)
        self.assertEqual(ing.trading_days(date(2025, 10, 20), date(2025, 10, 24)),
                         [date(2025, 10, 20), date(2025, 10, 21), date(2025, 10, 23), date(2025, 10, 24)])

    def test_special_sessions_override_a_holiday_set(self):
        # even when a holiday feed lists the Laxmi Pujan day, the Muhurat session stays
        days = ing.trading_days(date(2021, 11, 3), date(2021, 11, 5), holidays={"2021-11-04", "2021-11-05"})
        self.assertEqual(days, [date(2021, 11, 3), date(2021, 11, 4)])

    def test_special_can_be_disabled(self):
        self.assertNotIn(date(2025, 2, 1), ing.trading_days(date(2025, 1, 27), date(2025, 2, 7), special=set()))

    def test_special_sessions_are_not_closures(self):
        self.assertEqual(ing.SPECIAL_SESSIONS & ing.NSE_TRADING_HOLIDAYS, set())

    def test_closures_after_special_or_moved_sessions(self):
        # the archive echoes the previous session's file on these closures
        for d in (date(2021, 11, 5), date(2023, 6, 29), date(2024, 1, 22)):
            self.assertNotIn(d, ing.trading_days(d, d))
        # the moved Bakri Id closure: 2023-06-28 was a trading day
        self.assertIn(date(2023, 6, 28), ing.trading_days(date(2023, 6, 28), date(2023, 6, 28)))


class TestHistoryCalendar(unittest.TestCase):
    def test_2016_2021_sessions_and_closures(self):
        # 70 weekday closures and 6 special sessions -> 1,238 sessions 2016-10..2021-09
        days = ing.trading_days(date(2016, 10, 1), date(2021, 9, 30))
        self.assertEqual(len(days), 1238)
        for d in (date(2016, 10, 30), date(2019, 10, 27), date(2020, 2, 1), date(2020, 11, 14),
                  date(2017, 10, 19), date(2018, 11, 7)):
            self.assertIn(d, days)                     # Muhurat / Budget sessions
        for d in (date(2016, 10, 31), date(2019, 10, 28), date(2020, 11, 16), date(2019, 4, 29)):
            self.assertNotIn(d, days)                  # closures (Balipratipada, election day)
        self.assertIn(date(2020, 7, 13), days)         # an ordinary Monday


class TestContinuityCheck(unittest.TestCase):
    @staticmethod
    def _store(skip: date | None = None) -> ing.DuckDBStore:
        store = ing.DuckDBStore(":memory:")
        rng = np.random.default_rng(3)
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        state = {t: 100.0 for t in tickers}
        for d in ing.trading_days(date(2024, 2, 1), date(2024, 2, 29), special=set()):
            raw = ing._synth_sec_csv(d, tickers, rng, state)   # PREV_CLOSE = prior session close
            if d != skip:
                store.upsert(ing.parse_sec_delivery(raw, d))
        return store

    def test_complete_store_has_no_flag(self):
        store = self._store()
        scan = ing.check_sessions(store.con)
        self.assertFalse(scan["flagged"].any())
        self.assertEqual(float(scan["share"].max()), 0.0)
        store.close()

    def test_missing_session_flags_the_next_one(self):
        store = self._store(skip=date(2024, 2, 14))
        scan = ing.check_sessions(store.con)
        flagged = [d.date() for d in scan.loc[scan["flagged"], "date"]]
        self.assertEqual(flagged, [date(2024, 2, 15)])
        store.close()

    def test_cli_check_sessions_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            for skip, want in ((None, 0), (date(2024, 2, 14), 1)):
                path = str(Path(tmp) / f"s{want}.duckdb")
                src = self._store(skip=skip)
                src.con.execute(f"ATTACH '{path}' AS f")
                src.con.execute("CREATE TABLE f.equity_eod AS SELECT * FROM equity_eod")
                src.con.execute("DETACH f")
                src.close()
                self.assertEqual(ing.main(["--db", path, "--check-sessions"]), want)


if __name__ == "__main__":
    unittest.main(verbosity=2)
