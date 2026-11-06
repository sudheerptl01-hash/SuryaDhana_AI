"""DERV math (W2): basis annualization, term-structure legs, rollover %, PCR, VIX stats —
pure functions + the real SQL run against an in-memory DuckDB with the production schemas.

fo_analytics lives in data-service; its dir goes on sys.path (appended, so ui-api's own
`main` keeps winning name lookups). fo_analytics imports `main` only lazily inside request
handlers, which these tests never call — everything here runs storeless or on a temp DB.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[3]            # repo root (for shared.*)
for p in (str(_ROOT), str(_ROOT / "services" / "data-service")):
    if p not in sys.path:
        sys.path.append(p)

import fo_analytics as fa  # noqa: E402
import routers.derivatives as drv  # noqa: E402


# ── basis ────────────────────────────────────────────────────────────────────────────────

def test_basis_annualization_known_numbers():
    # 2 % over 73 days → 10 % annualized
    assert fa.ann_basis_pct(102.0, 100.0, 73) == pytest.approx(10.0)
    # real NIFTY row, 14 Oct 2026: fut 22648.5, spot 22622.7, 13 dte → ≈ +3.2 % (contango positive)
    assert fa.ann_basis_pct(22648.5, 22622.7, 13) == pytest.approx(3.2, abs=0.02)
    assert fa.basis_pct(22648.5, 22622.7) == pytest.approx(0.114, abs=0.001)
    # backwardation → negative
    assert fa.ann_basis_pct(99.0, 100.0, 365) == pytest.approx(-1.0)


def test_basis_guards():
    assert fa.ann_basis_pct(100.0, 100.0, 1) is None        # expiry-session dte < 2
    assert fa.ann_basis_pct(100.0, 0.0, 30) is None
    assert fa.ann_basis_pct(None, 100.0, 30) is None
    assert fa.basis_pct(100.0, None) is None


# ── term structure ───────────────────────────────────────────────────────────────────────

def _fut_frame():
    d = pd.Timestamp("2026-10-14")
    return pd.DataFrame({
        "TradDt": [d] * 3, "FinInstrmTp": ["IDF"] * 3, "TckrSymb": ["NIFTY"] * 3,
        # deliberately unsorted: far, near, next
        "XpryDt": pd.to_datetime(["2026-12-29", "2026-10-27", "2026-11-23"]),
        "ClsPric": [22903.1, 22648.5, 22756.0], "SttlmPric": [22903.1, 22648.5, 22756.0],
        "UndrlygPric": [22622.7] * 3, "OpnIntrst": [487760, 18451355, 2574910],
        "ChngInOpnIntrst": [26650, 3900, 117780], "TtlTradgVol": [1837, 53505, 5237],
    })


def test_term_legs_order_labels_and_contango_sign():
    legs = fa.term_legs(_fut_frame())
    assert [l["label"] for l in legs] == ["near", "next", "far"]
    assert [l["expiry"] for l in legs] == ["2026-10-27", "2026-11-23", "2026-12-29"]
    assert [l["dte"] for l in legs] == [13, 40, 76]
    # contango: every leg above spot → positive basis, rising with tenor on this curve
    anns = [l["basis_ann_pct"] for l in legs]
    assert all(a > 0 for a in anns)
    assert anns[0] == pytest.approx(3.2, abs=0.02) and anns[2] == pytest.approx(5.95, abs=0.03)
    assert legs[0]["oi"] == 18451355 and legs[0]["volume"] == 53505


# ── rollover ─────────────────────────────────────────────────────────────────────────────

def test_rollover_pct():
    assert fa.rollover_pct(70, 25, 5) == 30.0
    assert fa.rollover_pct(0, 0, 0) is None
    assert fa.rollover_pct(0, 100) == 100.0


def _panel():
    """Two NIFTY cycles: expiry 2026-09-29 (final roll 75 %) then the current 2026-10-27 run."""
    rows = []

    def day(d, legs):  # legs: (expiry, close, oi)
        for exp, close, oi in legs:
            rows.append({"date": d, "symbol": "NIFTY", "expiry": exp, "close": close,
                         "spot": 22000.0, "oi": oi})

    day("2026-09-28", [("2026-09-29", 22010.0, 60.0), ("2026-10-27", 22100.0, 35.0), ("2026-11-23", 22200.0, 5.0)])
    day("2026-09-29", [("2026-09-29", 22001.0, 25.0), ("2026-10-27", 22110.0, 70.0), ("2026-11-23", 22210.0, 5.0)])  # expiry day
    day("2026-10-13", [("2026-10-27", 22120.0, 80.0), ("2026-11-23", 22220.0, 18.0), ("2026-12-29", 22300.0, 2.0)])
    day("2026-10-14", [("2026-10-27", 22130.0, 70.0), ("2026-11-23", 22230.0, 27.0), ("2026-12-29", 22310.0, 3.0)])
    return pd.DataFrame(rows)


def test_rollover_view_history_current_and_curves():
    v = fa.rollover_view(_panel(), "NIFTY", cycles=8)
    # carry into next on expiry day: (22110/22000 − 1) × 365/28 → 6.52 % annualized
    assert v["history"] == [{"expiry": "2026-09-29", "date": "2026-09-29", "roll_pct": 75.0,
                             "carry_next_ann_pct": pytest.approx(6.52, abs=0.01)}]
    cur = v["current"]
    assert cur["date"] == "2026-10-14" and cur["near_expiry"] == "2026-10-27" and cur["dte"] == 13
    assert cur["roll_pct"] == 30.0 and cur["near_oi"] == 70.0 and cur["next_oi"] == 27.0 and cur["far_oi"] == 3.0
    # current cycle curve only (no September sessions), oldest first
    assert [r["date"] for r in v["curve_now"]] == ["2026-10-13", "2026-10-14"]
    # prior-cycle average curve keyed by dte: 2026-09-28 was dte 1 (40 %), expiry day dte 0 (75 %)
    assert {c["dte"]: c["roll_pct"] for c in v["curve_avg"]} == {1: 40.0, 0: 75.0}
    assert v["avg3"] == 75.0


def test_rollover_view_unknown_symbol_is_empty():
    v = fa.rollover_view(_panel(), "TCS")
    assert v["current"] is None and v["history"] == []


# ── PCR / percentile / realized vol ──────────────────────────────────────────────────────

def test_pcr_from_synthetic_oi():
    assert fa.pcr(120.0, 100.0) == 1.2
    assert fa.pcr(50.0, 0.0) is None                      # zero call OI is not "infinitely bullish"
    assert fa.pcr(None, 100.0) is None


def test_percentile_of_last():
    xs = [float(i) for i in range(1, 101)]
    assert fa.percentile_of_last(xs, 100) == 100.0        # max of its window
    assert fa.percentile_of_last(xs, 50) == 100.0
    assert fa.percentile_of_last([*xs, 1.0], 101) == pytest.approx(2.0, abs=0.1)
    assert fa.percentile_of_last(xs[:10], 252) is None    # too short

def test_realized_vol_series_flat_prices_are_zero_vol():
    rv = fa.realized_vol_series(pd.Series([100.0] * 30), window=20)
    assert rv.iloc[-1] == pytest.approx(0.0)


# ── the real SQL against the production schemas (in-memory DuckDB) ───────────────────────

@pytest.fixture()
def conn():
    duckdb = pytest.importorskip("duckdb")
    c = duckdb.connect(":memory:")
    c.execute("""
        CREATE TABLE nse_fo_daily (date DATE NOT NULL, symbol VARCHAR NOT NULL, kind VARCHAR NOT NULL,
            near_expiry DATE, fut_close DOUBLE, fut_settle DOUBLE, fut_oi DOUBLE, fut_oi_chg DOUBLE,
            fut_contracts DOUBLE, fut_value_lakh DOUBLE, call_oi DOUBLE, put_oi DOUBLE,
            call_oi_chg DOUBLE, put_oi_chg DOUBLE, opt_contracts DOUBLE, opt_value_lakh DOUBLE,
            PRIMARY KEY (date, symbol))""")
    c.execute("""
        CREATE TABLE nse_bhavcopy (symbol VARCHAR NOT NULL, series VARCHAR NOT NULL, date DATE NOT NULL,
            prev_close DOUBLE, open DOUBLE, high DOUBLE, low DOUBLE, last DOUBLE, close DOUBLE NOT NULL,
            avg_price DOUBLE, volume BIGINT, turnover_lacs DOUBLE, trades BIGINT, deliv_qty BIGINT,
            deliv_pct DOUBLE, PRIMARY KEY (symbol, series, date))""")
    c.execute("""
        CREATE TABLE market_index_daily (symbol VARCHAR NOT NULL, date DATE NOT NULL, close DOUBLE NOT NULL,
            source VARCHAR NOT NULL, created_at TIMESTAMP, PRIMARY KEY (symbol, date))""")
    yield c
    c.close()


def _seed(conn):
    fo = [("2026-10-13", "NIFTY", "index", "2026-10-27", 22750.0, 14, 100.0, 120.0),
          ("2026-10-14", "NIFTY", "index", "2026-10-27", 22648.5, 13, 100.0, 86.0),
          ("2026-10-14", "RELIANCE", "stock", "2026-10-27", 1182.2, 13, 50.0, 40.0),
          ("2026-10-14", "ZEROCALL", "stock", "2026-10-27", 10.0, 13, 0.0, 5.0)]
    for d, s, k, ne, fc, _dte, c_oi, p_oi in fo:
        conn.execute("INSERT INTO nse_fo_daily (date, symbol, kind, near_expiry, fut_close, fut_oi, call_oi, put_oi) "
                     "VALUES (?, ?, ?, ?, ?, 1000, ?, ?)", [d, s, k, ne, fc, c_oi, p_oi])
    conn.execute("INSERT INTO market_index_daily VALUES ('NIFTY50', '2026-10-13', 22721.95, 'test', NULL),"
                 "('NIFTY50', '2026-10-14', 22622.7, 'test', NULL)")
    conn.execute("INSERT INTO nse_bhavcopy (symbol, series, date, close) VALUES "
                 "('RELIANCE', 'EQ', '2026-10-14', 1174.61), ('RELIANCE', 'BE', '2026-10-14', 999.0)")
    for i in range(60):   # INDIAVIX + NIFTY50 history for q_vix (constant → rv20 = 0)
        d = (pd.Timestamp("2026-07-01") + pd.offsets.BDay(i)).date().isoformat()
        conn.execute("INSERT OR IGNORE INTO market_index_daily VALUES ('INDIAVIX', ?, ?, 'test', NULL)", [d, 14.0 + i * 0.01])
        conn.execute("INSERT OR IGNORE INTO market_index_daily VALUES ('NIFTY50', ?, 22000.0, 'test', NULL)", [d])


def test_q_basis_history_nifty_and_stock_spot_sources(conn):
    _seed(conn)
    rows, source = fa.q_basis_history(conn, "NIFTY", 10)
    assert source == "market_index_daily:NIFTY50" and len(rows) == 2
    last = rows[-1]
    assert last["date"] == "2026-10-14" and last["dte"] == 13
    assert last["basis_ann_pct"] == pytest.approx(3.2, abs=0.02)
    rows, source = fa.q_basis_history(conn, "RELIANCE", 10)
    assert source == "nse_bhavcopy:EQ" and len(rows) == 1
    assert rows[0]["spot"] == 1174.61                      # EQ row, not the BE series
    assert rows[0]["basis_ann_pct"] == pytest.approx((1182.2 / 1174.61 - 1) * 365 / 13 * 100, abs=0.01)
    # negative control: a store without the v2 index_ohlc_daily table → empty, never a CatalogException (it was a 500)
    assert fa.q_basis_history(conn, "BANKNIFTY", 10) == ([], "index_ohlc_daily:NIFTY BANK")
    assert fa.q_basis_history(conn, "ZEROCALL", 10)[0] == []    # a stock with no EQ row stored → empty


def test_q_basis_history_index_spot_from_the_daily_index_file(conn):
    """BANKNIFTY's spot is NSE's daily index file (index_ohlc_daily 'NIFTY BANK'), not NIFTY's and not a stock's."""
    _seed(conn)
    conn.execute("CREATE TABLE index_ohlc_daily (symbol VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE)")
    conn.execute("INSERT INTO nse_fo_daily (date, symbol, kind, fut_close, near_expiry) VALUES ('2026-10-14', 'BANKNIFTY', 'index', 56300.0, '2026-10-27')")
    conn.execute("INSERT INTO index_ohlc_daily VALUES ('NIFTY BANK', '2026-10-14', 56000, 56300, 55900, 56100.0), "
                 "('NIFTY 50', '2026-10-14', 25000, 25100, 24900, 25050.0)")
    rows, source = fa.q_basis_history(conn, "BANKNIFTY", 10)
    assert source == "index_ohlc_daily:NIFTY BANK" and len(rows) == 1
    assert rows[0]["spot"] == 56100.0 and rows[0]["dte"] == 13
    assert rows[0]["basis_ann_pct"] == pytest.approx((56300 / 56100 - 1) * 365 / 13 * 100, abs=0.01)
    # negative control: an index with no row of its own in the file stays empty (never borrows NIFTY 50's close)
    conn.execute("INSERT INTO nse_fo_daily (date, symbol, kind, fut_close, near_expiry) VALUES ('2026-10-14', 'FINNIFTY', 'index', 27000.0, '2026-10-27')")
    assert fa.q_basis_history(conn, "FINNIFTY", 10)[0] == []


def test_q_pcr_history_and_zero_call_guard(conn):
    _seed(conn)
    rows = fa.q_pcr_history(conn, "NIFTY", 10)
    assert [r["date"] for r in rows] == ["2026-10-13", "2026-10-14"]
    assert rows[-1]["pcr"] == pytest.approx(0.86)
    assert fa.q_pcr_history(conn, "ZEROCALL", 10)[0]["pcr"] is None


def test_q_vix_percentiles_and_realized_vol(conn):
    _seed(conn)
    out = fa.q_vix(conn, 100)
    assert out["level"] == pytest.approx(14.59)            # 14.0 + 59 × 0.01 (rising series → top percentile)
    assert out["pctile_1y"] == 100.0
    assert out["rv20"] == pytest.approx(0.0)               # constant NIFTY closes
    assert out["spread"] == pytest.approx(out["level"])
    assert out["rows"][-1]["date"] == out["as_of"]


def test_q_symbols_indices_first(conn):
    _seed(conn)
    rows = fa.q_symbols(conn)
    assert rows[0] == {"symbol": "NIFTY", "kind": "index"}
    assert {r["symbol"] for r in rows} == {"NIFTY", "RELIANCE", "ZEROCALL"}


# ── ui-api router: symbol guard + payload trim ───────────────────────────────────────────

def test_router_symbol_guard_rejects_junk():
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        drv._check_symbol("../etc")
    assert e.value.status_code == 422 and e.value.detail["code"] == "invalid"
    assert drv._check_symbol("m&m") == "M&M"


def test_max_pain_trims_the_per_strike_rows(monkeypatch):
    full = {"symbol": "NIFTY", "date": "2026-10-14", "expiry": "2026-10-19", "expiries": ["2026-10-19"],
            "days_to_expiry": 5, "spot": 22622.7, "future": 22648.5, "atm": 22600.0, "atm_iv": 12.5,
            "pcr_oi": 0.86, "max_pain": 22600.0, "expected_move_pct": 1.5,
            "resistance": [22700.0], "support": [22500.0], "found": True,
            "rows": [{"strike": 22600.0}] * 50, "lot": 75}

    async def fake_get(path, params=None, timeout=30.0):
        assert path == "/db/option-chain/NIFTY"
        return full

    monkeypatch.setattr(drv, "_get", fake_get)
    out = asyncio.run(drv.max_pain("NIFTY"))
    assert out["max_pain"] == 22600.0 and out["pcr_oi"] == 0.86
    assert "rows" not in out and "found" not in out and "lot" not in out
