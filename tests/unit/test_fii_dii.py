"""FII/DII cash flows (services/data-service/fii_dii.py): NSE parsing and summaries."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import fii_dii as fd  # noqa: E402

NSE = [{"buyValue": "15626.53", "category": "DII", "date": "09-Oct-2026", "netValue": "4743.26", "sellValue": "10883.27"},
       {"buyValue": "10,373.99", "category": "FII/FPI", "date": "09-Oct-2026", "netValue": "-3568.9", "sellValue": "13942.89"},
       {"category": "OTHER", "date": "09-Oct-2026"}, {"category": "DII", "date": "bad"}]


def test_parse_normalises_categories_and_numbers():
    df = fd.parse(NSE)
    assert list(df["category"]) == ["DII", "FII"]
    assert df.loc[df["category"] == "FII", "buy_cr"].item() == 10373.99
    assert df.loc[df["category"] == "FII", "net_cr"].item() == -3568.9
    assert str(df["date"].iloc[0]) == "2026-10-09"
    assert fd.parse([]).empty


def test_summarize_latest_5d_and_mtd():
    rows = []
    for i, d in enumerate(["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-05", "2026-10-06", "2026-10-07"]):
        rows += [{"date": d, "category": "FII", "net_cr": -100.0 * (i + 1)}, {"date": d, "category": "DII", "net_cr": 50.0}]
    s = fd.summarize(rows)
    assert s["latest_date"] == "2026-10-07" and s["latest"] == {"DII": 50.0, "FII": -600.0}
    assert s["sum_5d"]["FII"] == -(200 + 300 + 400 + 500 + 600) and s["sessions_5d"] == 5
    assert s["mtd"]["FII"] == -(300 + 400 + 500 + 600) and s["sessions_mtd"] == 4
    assert fd.summarize([])["sessions"] == 0


# ── review M09: sums count sessions against the NSE calendar; gaps are named, never skipped silently ─────────────
CAL = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]


def _rows(days):
    out = []
    for d in days:
        out += [{"date": d, "category": "FII", "net_cr": 100.0}, {"date": d, "category": "DII", "net_cr": -10.0}]
    return out


def test_summarize_names_missing_sessions_5_nov_2026():
    """The 5 Nov 2026 state: no rows for 28 Oct, 2 Nov, 3 Nov. The old summary said '5 sessions' over 27 Oct–5 Nov."""
    stored = ["2026-10-27", "2026-10-29", "2026-10-30", "2026-11-04", "2026-11-05"]
    s = fd.summarize(_rows(stored), sessions=CAL)
    assert s["window_5d"] == ["2026-10-30", "2026-11-05"]
    assert s["sessions_5d"] == 3 and s["expected_5d"] == 5 and s["label_5d"] == "3 of 5 sessions"
    assert s["missing_5d"] == ["2026-11-02", "2026-11-03"] and s["complete_5d"] is False
    assert s["sum_5d"]["FII"] == 300.0                    # only the three stored sessions, and the label says so
    assert s["label_mtd"] == "2 of 4 sessions" and s["missing_mtd"] == ["2026-11-02", "2026-11-03"]
    assert s["missing"] == ["2026-10-28", "2026-11-02", "2026-11-03"]
    assert s["note"] and "no archive" in s["note"]


def test_summarize_complete_calendar_is_complete():
    """Negative control: every session stored → complete, no note."""
    s = fd.summarize(_rows(CAL), sessions=CAL)
    assert s["label_5d"] == "5 of 5 sessions" and s["complete_5d"] and s["complete_mtd"]
    assert s["missing"] == [] and s["note"] is None and s["sum_5d"]["FII"] == 500.0


def test_summarize_holiday_is_not_a_gap():
    """A holiday has no bhavcopy, so it is not in the calendar and never counts as missing (2 Oct 2026)."""
    days = ["2026-09-29", "2026-09-30", "2026-10-01", "2026-10-05", "2026-10-06", "2026-10-07"]
    s = fd.summarize(_rows(days), sessions=days)
    assert s["missing"] == [] and s["label_5d"] == "5 of 5 sessions"
    assert s["label_mtd"] == "4 of 4 sessions"


def test_summarize_without_calendar_says_so():
    s = fd.summarize(_rows(["2026-11-04", "2026-11-05"]))
    assert s["calendar"] is None and "calendar unknown" in s["label_5d"] and s["complete_5d"] is False


def test_summarize_flags_a_newer_session_without_figures():
    s = fd.summarize(_rows(CAL[:-1]), sessions=CAL)
    assert s["latest_date"] == "2026-11-04" and s["latest_session"] == "2026-11-05" and s["latest_pending"] is True


NSE_CSV = ("CATEGORY,DATE,BUY VALUE(₹ Crores),SELL VALUE (₹ Crores),NET VALUE (₹ Crores)\n"
           "DII **,02-Nov-2026,20000.00,25000.00,-5000.00\n"
           "FII/FPI *,02-Nov-2026,30000.00,22000.00,8000.00\n")


def _run_backfill(csv_text=None, latest=None):
    stored = {"2026-10-27", "2026-10-29", "2026-10-30", "2026-11-04"}
    written = []

    def upsert(df):
        written.append(df)
        stored.update(df["date"].astype(str))
        return len(df)
    out = fd.backfill(stored, CAL, upsert, fetch_latest=(lambda: fd.parse(latest)) if latest else None, csv_text=csv_text)
    return out, written


def test_backfill_stores_the_latest_day_when_it_fills_a_gap():
    latest = [{"category": "FII/FPI", "date": "05-Nov-2026", "buyValue": "1", "sellValue": "0", "netValue": "1"},
              {"category": "DII", "date": "05-Nov-2026", "buyValue": "0", "sellValue": "1", "netValue": "-1"}]
    out, written = _run_backfill(latest=latest)
    assert out["filled"] == ["2026-11-05"] and len(written) == 1
    assert out["still_missing"] == ["2026-10-28", "2026-11-02", "2026-11-03"] and "no archive" in out["note"]


def test_backfill_imports_a_valid_owner_csv_for_a_gap():
    out, written = _run_backfill(csv_text=NSE_CSV)
    assert out["imported"] == ["2026-11-02"] and out["errors"] == []
    assert "2026-11-02" not in out["still_missing"]
    df = written[0]
    assert sorted(df["category"]) == ["DII", "FII"] and df.loc[df["category"] == "FII", "net_cr"].item() == 8000.0


def test_backfill_rejects_an_inconsistent_csv():
    """Negative control: buy − sell ≠ net → nothing is written, the gap stays and the error names the row."""
    bad = NSE_CSV.replace("8000.00", "8100.00")
    out, written = _run_backfill(csv_text=bad)
    assert written == [] and out["imported"] == [] and "2026-11-02" in out["still_missing"]
    assert any("buy − sell ≠ net" in e for e in out["errors"])


def test_backfill_rejects_a_non_session_date_and_a_foreign_file():
    sunday = NSE_CSV.replace("02-Nov-2026", "08-Nov-2026")
    assert fd.validate_rows(fd.parse_nse_csv(sunday), CAL)
    out, written = _run_backfill(csv_text="date,value\n2026-11-02,1\n")
    assert written == [] and out["errors"] and out["errors"][0].startswith("csv:")
