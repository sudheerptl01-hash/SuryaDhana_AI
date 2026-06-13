"""Phase 5 (D1) backfill tests — idempotency, look-ahead safety, schema contract.

NO network: yfinance fetch is monkeypatched with deterministic Series. NO shared
DB: each test uses a fresh temp DuckDB. Validates that:
  1. splits/dividends land with the exact (ticker, date, value) schema.
  2. Re-running converges (idempotent INSERT OR REPLACE — no row growth).
  3. Future-dated actions are dropped (look-ahead guard).
  4. index_membership + delistings are created in the EXACT shape analytics.py
     queries, and the analytics consumers parse them without error.
  5. delistings stays empty by default (survivorship flag stays live).
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

# Match the backfill scripts: pandas>=3 str dtype is unreadable by duckdb 1.1.1.
try:
    pd.set_option("future.infer_string", False)
except Exception:
    pass

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import backfill_corporate_actions as bca  # noqa: E402
import backfill_index_membership as bim  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _seed_ohlcv(db_path: str, tickers: list[str]) -> None:
    """Minimal ohlcv table so the only_in_ohlcv filter keeps the test tickers."""
    con = duckdb.connect(db_path, read_only=False)
    con.execute(
        """CREATE TABLE IF NOT EXISTS ohlcv (
               ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE,
               close DOUBLE, volume BIGINT)"""
    )
    rows = pd.DataFrame(
        {
            "ticker": tickers,
            "date": [pd.Timestamp("2022-01-03")] * len(tickers),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000,
        }
    )
    con.register("seed", rows)
    con.execute("INSERT INTO ohlcv SELECT ticker, CAST(date AS DATE), open, high, low, close, volume FROM seed")
    con.close()


def _make_universe_csv(tmp_path: Path, tickers: list[str]) -> Path:
    csv = tmp_path / "uni.csv"
    pd.DataFrame(
        {
            "ticker": tickers,
            "company_name": [f"{t} Ltd" for t in tickers],
            "sector": "Test",
            "isin": "INE000000000",
            "index": ["NIFTY500"] * len(tickers),
            "cap_category": "Large Cap",
        }
    ).to_csv(csv, index=False)
    return csv


@pytest.fixture
def fake_actions(monkeypatch):
    """Monkeypatch _fetch_actions with deterministic, INCLUDING a future-dated row."""
    future = pd.Timestamp(date.today()) + pd.Timedelta(days=400)

    def _fake(yf_ticker: str):
        if yf_ticker == "AAA.NS":
            splits = pd.Series(
                [2.0, 5.0],
                index=pd.to_datetime(["2022-06-01", "2023-09-15"]),
            )
            dividends = pd.Series(
                [6.0, 8.0, 99.0],  # last one is future-dated -> must be dropped
                index=pd.to_datetime(["2022-03-01", "2024-02-10", future]),
            )
            return splits, dividends
        if yf_ticker == "BBB.NS":
            splits = pd.Series(dtype="float64")  # no splits
            dividends = pd.Series([3.5], index=pd.to_datetime(["2023-05-05"]))
            return splits, dividends
        return pd.Series(dtype="float64"), pd.Series(dtype="float64")

    monkeypatch.setattr(bca, "_fetch_actions", _fake)
    return _fake


# ── Tests: corporate actions ───────────────────────────────────────────────────

def test_schema_and_rows(tmp_path, fake_actions):
    db = str(tmp_path / "m.duckdb")
    _seed_ohlcv(db, ["AAA", "BBB"])
    csv = str(_make_universe_csv(tmp_path, ["AAA", "BBB"]))

    stats = bca.backfill(db_path=db, universe_csv=csv)

    con = duckdb.connect(db, read_only=True)
    # exact schema contract
    scols = [r[1] for r in con.execute("PRAGMA table_info('splits')").fetchall()]
    dcols = [r[1] for r in con.execute("PRAGMA table_info('dividends')").fetchall()]
    assert scols == ["ticker", "date", "ratio"]
    assert dcols == ["ticker", "date", "amount"]

    # AAA: 2 splits, BBB: 0; AAA divs 2 (future dropped) + BBB 1 = 3
    assert con.execute("SELECT COUNT(*) FROM splits").fetchone()[0] == 2
    assert con.execute("SELECT COUNT(*) FROM dividends").fetchone()[0] == 3
    con.close()
    assert stats.splits_after == 2
    assert stats.dividends_after == 3


def test_look_ahead_future_dated_dropped(tmp_path, fake_actions):
    db = str(tmp_path / "m.duckdb")
    _seed_ohlcv(db, ["AAA"])
    csv = str(_make_universe_csv(tmp_path, ["AAA"]))
    bca.backfill(db_path=db, universe_csv=csv)
    con = duckdb.connect(db, read_only=True)
    maxd = con.execute("SELECT MAX(date) FROM dividends").fetchone()[0]
    con.close()
    # the 99.0 future-dated dividend must NOT be present
    assert maxd <= date.today()
    assert maxd == date(2024, 2, 10)


def test_idempotent_rerun(tmp_path, fake_actions):
    db = str(tmp_path / "m.duckdb")
    _seed_ohlcv(db, ["AAA", "BBB"])
    csv = str(_make_universe_csv(tmp_path, ["AAA", "BBB"]))
    s1 = bca.backfill(db_path=db, universe_csv=csv)
    s2 = bca.backfill(db_path=db, universe_csv=csv)
    s3 = bca.backfill(db_path=db, universe_csv=csv)
    # row counts must not grow across re-runs (INSERT OR REPLACE on PK)
    assert s1.splits_after == s2.splits_after == s3.splits_after == 2
    assert s1.dividends_after == s2.dividends_after == s3.dividends_after == 3


def test_dry_run_writes_nothing(tmp_path, fake_actions):
    db = str(tmp_path / "m.duckdb")
    _seed_ohlcv(db, ["AAA"])
    csv = str(_make_universe_csv(tmp_path, ["AAA"]))
    stats = bca.backfill(db_path=db, universe_csv=csv, dry_run=True)
    con = duckdb.connect(db, read_only=True)
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name='splits'"
    ).fetchone()
    con.close()
    # dry-run must not create/populate the tables
    assert stats.splits_after == 0
    assert exists is None


def test_split_ratio_positive_only(tmp_path, monkeypatch):
    db = str(tmp_path / "m.duckdb")
    _seed_ohlcv(db, ["AAA"])
    csv = str(_make_universe_csv(tmp_path, ["AAA"]))

    def _fake(yf_ticker: str):
        # includes a degenerate 0.0 ratio + NaN amount that must be cleaned out
        splits = pd.Series([0.0, 3.0], index=pd.to_datetime(["2022-01-01", "2022-02-01"]))
        dividends = pd.Series([float("nan"), 4.0], index=pd.to_datetime(["2022-03-01", "2022-04-01"]))
        return splits, dividends

    monkeypatch.setattr(bca, "_fetch_actions", _fake)
    bca.backfill(db_path=db, universe_csv=csv)
    con = duckdb.connect(db, read_only=True)
    assert con.execute("SELECT COUNT(*) FROM splits").fetchone()[0] == 1  # 0.0 dropped
    assert con.execute("SELECT COUNT(*) FROM dividends").fetchone()[0] == 1  # NaN dropped
    con.close()


# ── Tests: index_membership + delistings ───────────────────────────────────────

def test_membership_and_delistings_schema(tmp_path):
    db = str(tmp_path / "m.duckdb")
    csv = str(_make_universe_csv(tmp_path, ["AAA", "BBB", "CCC"]))
    report = bim.run(
        db_path=db, universe_csv=csv, load_membership=False,
        index_name="NIFTY500", effective_from=date(2021, 5, 17),
    )
    con = duckdb.connect(db, read_only=True)
    mcols = [r[1] for r in con.execute("PRAGMA table_info('index_membership')").fetchall()]
    dcols = [r[1] for r in con.execute("PRAGMA table_info('delistings')").fetchall()]
    con.close()
    # analytics.py SELECTs ticker, index_name, effective_from, effective_to
    assert {"ticker", "index_name", "effective_from", "effective_to"}.issubset(set(mcols))
    # _delisting_map SELECTs ticker, delist_date, delist_return_pct
    assert {"ticker", "delist_date", "delist_return_pct"}.issubset(set(dcols))
    # default: empty (honest) — survivorship flag stays live
    assert report["index_membership_after"] == 0
    assert report["delistings_after"] == 0


def test_membership_snapshot_load_is_open_interval(tmp_path):
    db = str(tmp_path / "m.duckdb")
    csv = str(_make_universe_csv(tmp_path, ["AAA", "BBB", "CCC"]))
    report = bim.run(
        db_path=db, universe_csv=csv, load_membership=True,
        index_name="NIFTY500", effective_from=date(2021, 5, 17),
    )
    assert report["membership_loaded"] == 3
    con = duckdb.connect(db, read_only=True)
    # every loaded row must have NULL effective_to (open interval == still a member)
    open_rows = con.execute(
        "SELECT COUNT(*) FROM index_membership WHERE effective_to IS NULL"
    ).fetchone()[0]
    total = con.execute("SELECT COUNT(*) FROM index_membership").fetchone()[0]
    con.close()
    assert open_rows == total == 3


def test_membership_load_idempotent(tmp_path):
    db = str(tmp_path / "m.duckdb")
    csv = str(_make_universe_csv(tmp_path, ["AAA", "BBB"]))
    kw = dict(db_path=db, universe_csv=csv, load_membership=True,
              index_name="NIFTY500", effective_from=date(2021, 5, 17))
    r1 = bim.run(**kw)
    r2 = bim.run(**kw)
    assert r1["index_membership_after"] == r2["index_membership_after"] == 2


def test_analytics_helpers_consume_backfilled_tables(tmp_path):
    """The real analytics.py helpers must parse our tables without raising."""
    UI_API = os.path.join(SCRIPTS_DIR, "..", "services", "ui-api")
    UI_API = os.path.abspath(UI_API)
    if UI_API not in sys.path:
        sys.path.insert(0, UI_API)
    try:
        from routers import analytics as an  # type: ignore
    except Exception:
        pytest.skip("analytics router not importable in this env")

    db = str(tmp_path / "m.duckdb")
    csv = str(_make_universe_csv(tmp_path, ["AAA", "BBB"]))
    bim.run(db_path=db, universe_csv=csv, load_membership=True,
            index_name="NIFTY500", effective_from=date(2021, 5, 17))

    con = duckdb.connect(db, read_only=True)
    # _load_membership_intervals returns a panel; _delisting_map returns {} (empty table)
    mem = an._load_membership_intervals(con, "NIFTY500")
    dmap = an._delisting_map(con)
    con.close()
    assert mem is not None and len(mem) == 2
    assert set(mem.columns) == {"ticker", "effective_from", "effective_to"}
    assert dmap == {}  # empty delistings -> no survivorship adjustment -> flag stays live
