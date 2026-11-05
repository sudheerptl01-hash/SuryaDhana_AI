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
