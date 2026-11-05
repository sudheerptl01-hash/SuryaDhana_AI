"""G3 (Terminal v2 PLAN 1.7): the drivers' arithmetic on a synthetic point-in-time fixture in a temp DuckDB — PIT (no
``shares_filed_at`` / ``promoter_public_at`` after the date), the identity (Σ weights = 100 ± 0.01, Σ points = explained), a
KOTAKBANK-style 1:5 split day within ±5 % of the true return, the 1 Feb 2026 special session present with
``index_close_source = nse_daily_file``, the 60-session MAE gate (``fit.degraded``), calibration equal to the official top-10
to 0.01 pp, the hysteresis fixture (many raw changes → few), NIFTY BANK capping, the parsers of the two files."""
from __future__ import annotations

# ruff: noqa: DTZ001
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from data_health import db  # noqa: E402
from index_drivers import compute, ingest, jobs, reads, weights  # noqa: E402

FIX = ROOT / "tests" / "unit" / "fixtures" / "terminal_v2"
NOW = datetime(2026, 11, 5, 0, 0)
SYMS = {"ALPHA": "Financial Services", "BETA": "Information Technology", "GAMMA": "Oil Gas & Consumable Fuels", "DELTA": "Automobile"}
SHARES = {"ALPHA": 1_000_000_000.0, "BETA": 400_000_000.0, "GAMMA": 700_000_000.0, "DELTA": 300_000_000.0}
PROMOTER = {"ALPHA": 0.0, "BETA": 13.0, "GAMMA": 50.0, "DELTA": 40.0}
SPLIT_DAY = date(2026, 1, 14)          # DELTA 1:5 (the KOTAKBANK fixture date)
SPECIAL = date(2026, 2, 1)             # the Sunday Budget session
START, END = date(2025, 10, 1), date(2026, 3, 31)


def _sessions() -> list[date]:
    days = [d for d in pd.date_range(START, END).date if d.weekday() < 5]
    days.append(SPECIAL)
    return sorted(days)


def _build(store, financials_root: Path) -> dict:
    """A 4-name index whose level is built EXACTLY from the PIT weights, so the attribution identity must hold."""
    rng = np.random.default_rng(3)
    sessions = _sessions()
    prices = {s: 100.0 * (i + 1) for i, s in enumerate(SYMS)}
    rows, idx_rows, level = [], [], 10_000.0
    sh_rows = [{"symbol": s, "period_end": date(2025, 9, 30), "broadcast_ts": "15-OCT-2025 10:00:00", "promoter_pct": PROMOTER[s]} for s in SYMS]
    sh_rows.append({"symbol": "BETA", "period_end": date(2025, 12, 31), "broadcast_ts": "20-JAN-2026 10:00:00", "promoter_pct": 20.0})   # a later filing
    splits = pd.DataFrame([{"ticker": "DELTA", "date": SPLIT_DAY, "ratio": 5.0}])
    financials_root.mkdir(parents=True, exist_ok=True)
    # XBRL filings report the period-end share count (pre-split for DELTA's Dec quarter, filed after the 14 Jan split):
    # the PIT rule scales by splits dated after the period end; the Sep filing is public from 21 Oct (filed 20 Oct 17:00)
    for s in SYMS:
        quarters = [{"period_end": "2025-09-30", "filed_at": "2025-10-20T17:00:00", "shares": SHARES[s], "face_value": 1.0, "paid_up": SHARES[s]},
                    {"period_end": "2025-06-30", "filed_at": "2025-07-20T17:00:00", "shares": SHARES[s] * 0.9, "face_value": 1.0, "paid_up": SHARES[s] * 0.9},
                    {"period_end": "2025-12-31", "filed_at": "2026-01-25T17:00:00", "shares": SHARES[s], "face_value": 1.0}]
        (financials_root / f"{s}.json").write_text(json.dumps({"symbol": s, "quarters": quarters}))
    for i, d in enumerate(sessions):
        rets = {s: float(rng.normal(0, 0.012)) for s in SYMS}
        prev = dict(prices)
        split_today = d == SPLIT_DAY
        shares_now = {s: SHARES[s] * (0.9 if d <= date(2025, 10, 20) else 1.0) * (5 if (s == "DELTA" and d >= SPLIT_DAY) else 1) for s in SYMS}
        promo = {s: (20.0 if (s == "BETA" and d >= date(2026, 1, 20)) else (PROMOTER[s] if d >= date(2025, 10, 15) else 0.0)) for s in SYMS}
        w_raw = {s: shares_now[s] * (prev[s] / (5 if (split_today and s == "DELTA") else 1)) * (1 - promo[s] / 100) for s in SYMS}
        tot = sum(w_raw.values())
        w = {s: v / tot for s, v in w_raw.items()}
        for s in SYMS:
            new = prev[s] * (1 + rets[s]) / (5 if (split_today and s == "DELTA") else 1)
            stored_prev = prev[s]                                            # NSE's prev_close is NOT adjusted on the ex-date
            rows.append({"symbol": s, "series": "EQ", "date": d, "prev_close": stored_prev, "open": new, "high": new * 1.01, "low": new * 0.99,
                         "last": new, "close": new, "avg_price": new, "volume": 1000, "turnover_lacs": 1.0, "trades": 10, "deliv_qty": 100, "deliv_pct": 10.0})
            prices[s] = new
        if i > 0:
            level = level * (1 + sum(w[s] * rets[s] for s in SYMS))
        idx_rows.append({"symbol": "NIFTY 50", "date": d, "open": level, "high": level, "low": level, "close": level, "source": "nse_daily_file", "first_seen_at": NOW})
    store.upsert_bhavcopy(pd.DataFrame(rows))
    db.upsert(store, "splits", splits, ["ticker", "date", "ratio"], {"date": "DATE", "ratio": "DOUBLE"})
    db.upsert(store, "nse_shareholding", pd.DataFrame(sh_rows), ["symbol", "period_end", "broadcast_ts", "promoter_pct"], {"period_end": "DATE", "promoter_pct": "DOUBLE"})
    db.upsert(store, "index_ohlc_daily", pd.DataFrame(idx_rows), ["symbol", "date", "open", "high", "low", "close", "source", "first_seen_at"],
              {"date": "DATE", "first_seen_at": "TIMESTAMP", **{c: "DOUBLE" for c in ("open", "high", "low", "close")}})
    members = pd.DataFrame([{"symbol": s, "industry": ind, "isin": None, "company": s} for s, ind in SYMS.items()])
    ingest.write_constituents(store, "NIFTY 50", members, START, source="fixture", now=NOW)
    return {"sessions": sessions}


@pytest.fixture
def store(tmp_path: Path):
    from storage.duckdb_store import DuckDBStore

    s = DuckDBStore(str(tmp_path / "drivers.duckdb"))
    yield s
    s.close()


def test_pit_identity_split_special_session_and_fit(store, tmp_path):
    fx = _build(store, tmp_path / "financials")
    res = jobs.compute_index(store, "NIFTY 50", fx["sessions"][1:], financials_root=tmp_path / "financials", now=NOW)
    assert res["days"] == len(fx["sessions"]) - 1 and res["written"]["fit"] >= 120 and not res["skipped"], res
    w = store.read("SELECT date, symbol, weight_pct, shares_filed_at, promoter_public_at FROM index_weights_daily WHERE method = 'rebuilt'")
    w["date"] = w["date"].map(db.to_date)
    w["promoter_public_at"] = w["promoter_public_at"].map(db.to_date)
    # PIT: no input dated after the session it is used on (a missing filing → promoter 0 %, public_at NULL)
    assert (pd.to_datetime(w["shares_filed_at"]).dt.date <= w["date"]).all()
    pub = w.dropna(subset=["promoter_public_at"])
    assert len(pub) > 400 and (pub["promoter_public_at"] <= pub["date"]).all()
    assert w[w["date"] < date(2025, 10, 15)]["promoter_public_at"].isna().all()          # before the first filing was public: none used
    # the later BETA shareholding filing (public 20 Jan) is used from 20 Jan, not before (negative control)
    beta = w[w["symbol"] == "BETA"].set_index("date")
    assert beta.loc[date(2026, 1, 19), "promoter_public_at"] == date(2025, 10, 15) and beta.loc[date(2026, 1, 20), "promoter_public_at"] == date(2026, 1, 20)
    # identity: Σ weights = 100 ± 0.01 and Σ points = explained, residual ≈ 0 because the level was built from these weights
    sums = w.groupby("date")["weight_pct"].sum()
    assert (sums - 100).abs().max() < 0.01
    fit = store.read("SELECT * FROM index_contribution_fit ORDER BY date")
    pts = store.read("SELECT date, SUM(points) AS s FROM index_contribution_daily GROUP BY date").set_index("date")["s"]
    assert (fit.set_index("date")["explained_points"] - pts).abs().max() < 1e-3          # rounding: points 6 dp, the fit row 4 dp
    assert fit["residual_points"].abs().max() < 0.5, fit["residual_points"].abs().max()
    # the split day: DELTA's return is the true one (within ±5 %), prev_close unadjusted notwithstanding
    c = store.read("SELECT symbol, date, ret_pct, flag FROM index_contribution_daily WHERE symbol = 'DELTA' AND date = ?", [SPLIT_DAY]).iloc[0]
    true_ret = (store.read_one("SELECT close FROM nse_bhavcopy WHERE symbol = 'DELTA' AND date = ?", [SPLIT_DAY])[0] * 5
                / store.read_one("SELECT close FROM nse_bhavcopy WHERE symbol = 'DELTA' AND date = ?", [SPLIT_DAY - timedelta(days=1)])[0] - 1) * 100
    assert abs(c["ret_pct"] - true_ret) < 5 and c["flag"] is None
    # the Sunday special session is present with the NSE daily file as the source
    sp = fit[fit["date"].map(db.to_date) == SPECIAL]
    assert len(sp) == 1 and sp.iloc[0]["index_close_source"] == "nse_daily_file"
    # the fit gate: this fixture is not degraded; a frame with huge residuals is (negative control)
    st = reads.fit_stats(store, "NIFTY 50", END)
    assert st["degraded"] is False and st["mae_60s"] < 1 and st["r2_60s"] > 0.99
    bad = pd.DataFrame([{"index_name": "BAD", "date": d, "actual_points": 100.0, "explained_points": 0.0, "residual_points": 100.0, "index_level": 1.0,
                         "prev_index_level": 1.0, "index_close_source": "x", "weight_method": "rebuilt", "members_priced": 1, "members_total": 1,
                         "computed_at": NOW} for d in fx["sessions"][:70]])
    db.upsert(store, "index_contribution_fit", bad, list(bad.columns), {"date": "DATE", "computed_at": "TIMESTAMP"})
    assert reads.fit_stats(store, "BAD", END)["degraded"] is True
    # the read payload
    out = reads.drivers(store, "NIFTY 50", "1m")
    assert out["as_of"] == END.isoformat() and len(out["members"]) == 4 and out["badges"]["driver"] == "context" and out["badges"]["members"] == "arithmetic"
    assert abs(out["explained_pts"] - out["index_move_pts"]) < 1 and out["fit"]["degraded"] is False
    assert out["regime_sentence"] and out["regime_sentence"].endswith("describes, does not predict")
    assert {s["industry"] for s in out["sectors"]} == set(SYMS.values())
    tl = reads.timeline(store, "NIFTY 50", window=20)
    assert tl["rows"] and tl["verdict"].endswith("describes, does not predict")
    mo = reads.monthly(store, "NIFTY 50", months=12)
    assert mo["rows"] and all(r["leader"] in SYMS for r in mo["rows"])


def test_calibration_equals_the_official_top10_to_a_hundredth(store, tmp_path):
    _build(store, tmp_path / "financials")
    day = date(2026, 3, 30)
    official = {"ALPHA": 45.0, "BETA": 20.0}
    top = pd.DataFrame([{"symbol": s, "weight_pct": v, "date": day} for s, v in official.items()])
    ingest.write_top10(store, top, day, now=NOW)
    jobs.compute_index(store, "NIFTY 50", [day, date(2026, 3, 31)], financials_root=tmp_path / "financials", now=NOW)
    cal = store.read("SELECT symbol, weight_pct, iwf_correction FROM index_weights_daily WHERE method = 'rebuilt_calibrated' AND date = ?", [day]).set_index("symbol")
    for s, v in official.items():
        assert abs(cal.loc[s, "weight_pct"] - v) < 0.01 and cal.loc[s, "iwf_correction"] is not None
    assert abs(cal["weight_pct"].sum() - 100) < 0.01
    # the next day carries the corrections forward (no file) and the method is still calibrated
    nxt = store.read("SELECT method, weight_pct FROM index_weights_daily WHERE date = ? AND method = 'rebuilt_calibrated'", [date(2026, 3, 31)])
    assert len(nxt) == 4 and abs(nxt["weight_pct"].sum() - 100) < 0.01
    fit = store.read("SELECT weight_method FROM index_contribution_fit WHERE date = ?", [day]).iloc[0]["weight_method"]
    assert fit == "rebuilt_calibrated"
    # negative control (point-in-time): a session BEFORE the first top-10 file is plain rebuilt — the 30 Mar calibration is
    # never carried backwards into 27 Mar, even when 27 Mar is computed after it
    jobs.compute_index(store, "NIFTY 50", [date(2026, 3, 27)], financials_root=tmp_path / "financials", now=NOW)
    before = store.read("SELECT weight_method FROM index_contribution_fit WHERE date = ?", [date(2026, 3, 27)])
    assert len(before) == 1 and before.iloc[0]["weight_method"] == "rebuilt"
    assert store.read("SELECT COUNT(*) AS n FROM index_weights_daily WHERE date = ? AND method = 'rebuilt_calibrated'",
                      [date(2026, 3, 27)]).iloc[0]["n"] == 0


def test_hysteresis_turns_many_raw_changes_into_few():
    rng = np.random.default_rng(11)
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(120)]
    a = 100 + rng.normal(0, 12, 120)                                           # two names trading the raw lead every few sessions
    b = 100 + rng.normal(0, 12, 120)
    c = 20 + rng.normal(0, 3, 120)
    roll = pd.DataFrame({"A": a, "B": b, "C": c}, index=pd.Index(days)).abs()
    raw_changes = int((roll.idxmax(axis=1) != roll.idxmax(axis=1).shift(1)).sum()) - 1
    out = compute.hysteresis_leaders(roll, 1.3, 5)
    hyst_changes = int((out["leader"] != out["leader"].shift(1)).sum()) - 1
    assert raw_changes >= 15 and hyst_changes <= 3, (raw_changes, hyst_changes)
    assert out["tenure_sessions"].iloc[-1] >= 1 and set(out["raw_leader"]) <= {"A", "B", "C"}
    # a genuine regime change: B 2× A for 5 sessions → the leader moves on the 5th session, not before (negative control)
    roll2 = pd.DataFrame({"A": [100.0] * 20, "B": [50.0] * 10 + [200.0] * 10}, index=pd.Index(days[:20]))
    o2 = compute.hysteresis_leaders(roll2, 1.3, 5)
    assert list(o2["leader"].iloc[9:15]) == ["A", "A", "A", "A", "A", "B"] and o2["changed_from"].iloc[-1] == "A" and o2["change_date"].iloc[-1] == days[14]


def test_bank_capping_and_member_fallback():
    w = {"A": 0.5, "B": 0.2, "C": 0.15, "D": 0.1, "E": 0.05}
    capped = weights.apply_caps(w, 0.33, 0.62)
    assert abs(sum(capped.values()) - 1) < 1e-9 and max(capped.values()) <= 0.33 + 1e-9
    assert sum(sorted(capped.values(), reverse=True)[:3]) <= 0.62 + 1e-6
    assert weights.apply_caps({"A": 0.3, "B": 0.3, "C": 0.3, "D": 0.1}, 0.5, 0.95) == {"A": 0.3, "B": 0.3, "C": 0.3, "D": 0.1}   # negative control: nothing to cap


def test_the_two_file_parsers():
    top = ingest.parse_top10((FIX / "top10nifty50_041126.csv").read_bytes(), date(2026, 11, 4))
    assert len(top) == 10 and abs(top["weight_pct"].sum() - 53.13) < 0.01 and top.iloc[0]["symbol"] == "HDFCBANK"
    n50 = ingest.parse_constituents((FIX / "ind_nifty50list.csv").read_bytes())
    nb = ingest.parse_constituents((FIX / "ind_niftybanklist.csv").read_bytes())
    assert len(n50) == 50 and len(nb) == 14 and "HDFCBANK" in set(n50["symbol"]) and n50["industry"].notna().all()
    with pytest.raises(ValueError):
        ingest.parse_top10(b"SYMBOL,WEIGHTAGE(%)\nX,99\n", date(2026, 11, 4))                       # not ten rows
    with pytest.raises(ValueError):
        ingest.parse_constituents(b"a,b\n1,2\n")
