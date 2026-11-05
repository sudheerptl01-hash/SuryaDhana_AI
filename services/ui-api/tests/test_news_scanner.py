"""News Catalyst Terminal backend: symbol normalisation, news/thesis parsing, scan I/O."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import news_scanner as ns  # noqa: E402


@pytest.mark.parametrize("raw, exchange, yahoo, tv, region", [
    ("ELMT", "NASDAQ", "ELMT", "NASDAQ:ELMT", "US"),
    ("AESI", "NYSE", "AESI", "NYSE:AESI", "US"),
    ("UPL.NS", "NSE", "UPL.NS", "NSE:UPL", "IN"),
    ("LCC (NSE)", "NSE", "LCC.NS", "NSE:LCC", "IN"),
    ("TUN.L", "LSE AIM", "TUN.L", "LSE:TUN", "UK"),
    ("RELIANCE.BO", None, "RELIANCE.BO", "BSE:RELIANCE", "IN"),
    ("DABUR", "NSE", "DABUR.NS", "NSE:DABUR", "IN"),
    ("INFY", None, "INFY.NS", "NSE:INFY", "IN"),                 # bare ticker → India default
    ("INFY", "NSE / BSE", "INFY.NS", "NSE:INFY", "IN"),          # dual listing → NSE
    ("NSE:INFY", None, "INFY.NS", "NSE:INFY", "IN"),
    ("543210", None, "543210.BO", "BSE:543210", "IN"),           # BSE scrip code
    ("GRAB", "NASDAQ", "GRAB", "NASDAQ:GRAB", "US"),             # explicit foreign exchange kept
])
def test_normalise_symbol(raw, exchange, yahoo, tv, region):
    s = ns.normalise_symbol(raw, exchange)
    assert (s["yahoo"], s["tv"], s["region"]) == (yahoo, tv, region)


def test_normalise_symbol_rejects_garbage():
    assert ns.normalise_symbol("") is None
    assert ns.normalise_symbol("../../etc/passwd") is None


def test_split_news_dated_and_undated_items():
    items = ns.split_news("Sep 22, 2026: offtake deal. | Sep 24, 2026: stake buy. | Sep 2026: orders won.")
    assert [i["date"] for i in items] == ["Sep 22, 2026", "Sep 24, 2026", "Sep 2026"]
    assert items[0]["text"] == "offtake deal."
    assert ns.split_news("S&P revised outlook to Positive")[0] == {"date": None, "text": "S&P revised outlook to Positive"}
    assert ns.split_news("Sep 23-25, 2026: block deal")[0]["date"] == "Sep 23-25, 2026"


def test_split_thesis_numbered_steps():
    steps = ns.split_thesis("1) Secured ore. 2) Sell-side re-underwrites. 3) Funds add exposure.")
    assert steps == ["Secured ore.", "Sell-side re-underwrites.", "Funds add exposure."]
    assert ns.split_thesis("Weak standalone catalyst.") == ["Weak standalone catalyst."]


@pytest.mark.parametrize("name, clean", [
    ("Cipher Digital Inc. (formerly Cipher Mining)", "Cipher Digital"),
    ("Transport Corporation of India Ltd", "Transport Corporation of India"),
    ("The Elmet Group Co.", "Elmet Group"),
    ("Tungsten West plc", "Tungsten West"),
    ("UPL Limited", "UPL"),
])
def test_clean_company_name(name, clean):
    assert ns.clean_company_name(name) == clean


def test_scan_listing_and_reading(tmp_path, monkeypatch):
    scan = {
        "scan_date": "2026-09-25",
        "stage1_picks": [
            {"ticker": "LOW", "exchange": "NYSE", "news": "Sep 1, 2026: x", "sources": ["https://www.ex.com/a"],
             "reflexivity_thesis": "1) a. 2) b.", "conviction_score": 2},
            {"ticker": "HIGH.NS", "exchange": "NSE", "news": "Sep 2, 2026: y", "sources": [],
             "reflexivity_thesis": "1) c.", "conviction_score": 9},
        ],
        "rejected_stage2_stage3": [{"ticker": "BE / ILMN", "reason": "announced"}],
    }
    (tmp_path / "20260925.json").write_text(json.dumps(scan))
    (tmp_path / "notes.json").write_text("{}")              # ignored: not YYYYMMDD
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))

    listing = ns.list_scans()
    assert [s["date"] for s in listing["scans"]] == ["20260925"]
    assert listing["scans"][0]["picks"] == 2

    out = ns.get_scan("latest")
    assert [p["symbol"]["yahoo"] for p in out["picks"]] == ["HIGH.NS", "LOW"]   # conviction-sorted
    assert out["picks"][1]["sources"][0]["domain"] == "ex.com"
    # no exchange given → the India-only default (NSE); explicit exchanges always win
    assert [s["yahoo"] for s in out["rejected"][0]["symbols"]] == ["BE.NS", "ILMN.NS"]


def test_partially_written_scan_is_flagged_not_hidden(tmp_path, monkeypatch):
    (tmp_path / "20260926.json").write_text('{"scan_date": "2026-09-26", "stage1_picks": [')   # mid-write
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))
    assert ns.list_scans()["scans"][0]["picks"] == -1
    with pytest.raises(ns.HTTPException) as e:
        ns.get_scan("20260926")
    assert e.value.status_code == 422



# ── the scanner's format since 22 Oct 2026: "stage1_candidates" + "rejected" (F4-OPS PR-F4-OPS-1) ────────────

SCAN_SINCE_22_OCT = {   # the shape of new_scnner/20261022.json, 20261023.json and 20261025.json
    "scan_date": "2026-10-22", "generated_at": "2026-10-22T07:40:00+05:30", "universe": "NSE", "methodology": "m",
    "note": "n", "count": 2,
    "stage1_candidates": [
        {"ticker": "PCJEWELLER.NS", "yahoo_ticker": "PCJEWELLER.NS", "company_name": "PC Jeweller Ltd",
         "exchange": "NSE", "conviction_score": 7, "catalyst_category": "Debt resolution", "news_date": "2026-10-21",
         "news": "Oct 21, 2026: lenders sign", "market_consensus_gap": "gap",
         "reflexivity_thesis": "1) a. 2) b. 3) c.", "source_urls": ["https://www.nseindia.com/x", "https://bse.in/y"]},
        {"ticker": "HINDPETRO.NS", "yahoo_ticker": "HINDPETRO.NS", "company_name": "Hindustan Petroleum",
         "exchange": "NSE", "conviction_score": 5, "reflexivity_thesis": "1) d.", "source_urls": []},
    ],
    "rejected": [{"company": "Yes Bank (YESBANK.NS)", "reason": "already priced in", "stage": 2},
                 {"company": "Swiggy (SWIGGY.NS)", "reason": "no catalyst", "stage": 3}],
}


def test_scans_since_22_oct_read_their_stage1_candidates(tmp_path, monkeypatch):
    (tmp_path / "20261022.json").write_text(json.dumps(SCAN_SINCE_22_OCT))
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))
    assert ns.list_scans()["scans"][0] | {"version": 0} == {"date": "20261022", "file": "20261022.json", "version": 0,
                                                            "error": None, "picks": 2, "rejected": 2}
    out = ns.get_scan("latest")
    assert [p["symbol"]["yahoo"] for p in out["picks"]] == ["PCJEWELLER.NS", "HINDPETRO.NS"]   # conviction-sorted
    pc = out["picks"][0]
    assert pc["company_name"] == "PC Jeweller Ltd" and pc["conviction_score"] == 7
    assert [s["domain"] for s in pc["sources"]] == ["nseindia.com", "bse.in"]           # "source_urls"
    assert pc["thesis_steps"] == ["a.", "b.", "c."] and out["unresolved_tickers"] == []
    # the track record reads picks through the same loader (scripts/news_scan_performance.py)
    assert [p["ticker"] for p in ns.load_scan_file(tmp_path / "20261022.json")["picks"]] == ["PCJEWELLER.NS", "HINDPETRO.NS"]


def test_rejected_rows_without_a_ticker_are_named_by_company(tmp_path, monkeypatch):
    (tmp_path / "20261022.json").write_text(json.dumps(SCAN_SINCE_22_OCT))
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))
    rejected = ns.get_scan("latest")["rejected"]
    assert [(r["raw_ticker"], r["company_name"], r["reason"]) for r in rejected] == [
        ("Yes Bank (YESBANK.NS)", "Yes Bank (YESBANK.NS)", "already priced in"),
        ("Swiggy (SWIGGY.NS)", "Swiggy (SWIGGY.NS)", "no catalyst")]
    assert len({r["raw_ticker"] for r in rejected}) == len(rejected)          # the terminal's row keys are unique
    assert all(r["symbols"] == [] for r in rejected)
    # a rejected row WITH a ticker is unchanged
    assert ns._normalise_rejected({"ticker": "BE / ILMN", "reason": "x"})["raw_ticker"] == "BE / ILMN"


def test_stage1_picks_keeps_priority_and_stage1_candidates_beats_the_generic_keys(tmp_path):
    f = tmp_path / "20261024.json"
    f.write_text(json.dumps({"stage1_picks": [{"ticker": "A.NS"}], "stage1_candidates": [{"ticker": "B.NS"}]}))
    assert [p["ticker"] for p in ns.load_scan_file(f)["picks"]] == ["A.NS"]                 # older scans unchanged
    f.write_text(json.dumps({"data": [{"ticker": "C.NS"}], "stage1_candidates": [{"ticker": "B.NS"}]}))
    assert [p["ticker"] for p in ns.load_scan_file(f)["picks"]] == ["B.NS"]


# ── formats the scanner prompt can emit ─────────────────────────────────────────

PROMPT_ARRAY = [   # the prompt's OUTPUT JSON SCHEMA: a bare array, no news/sources keys
    {"ticker": "INFY.NS", "company_name": "Infosys Limited", "exchange": "NSE",
     "catalyst_category": "SEBI PIT Accumulation", "market_consensus_gap": "gap",
     "reflexivity_thesis": "1. EPS upgrades 2. DII buying 3. re-rating", "conviction_score": 7},
    {"ticker": "LCC", "company_name": "LCC Projects Ltd", "exchange": "NSE",
     "catalyst_category": "L1 Tender Status", "conviction_score": "5/10"},
]


def test_prompt_schema_bare_json_array(tmp_path, monkeypatch):
    (tmp_path / "20260927.json").write_text(json.dumps(PROMPT_ARRAY))
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))
    assert ns.list_scans()["scans"][0]["picks"] == 2
    out = ns.get_scan("latest")
    assert out["source_format"] == "json-array" and out["scan_date"] == "2026-09-27"
    infy = out["picks"][0]
    assert infy["symbol"]["yahoo"] == "INFY.NS" and infy["conviction_score"] == 7
    assert infy["thesis_steps"] == ["EPS upgrades", "DII buying", "re-rating"]
    assert infy["news"] == [] and infy["sources"] == []           # absent fields → empty, not a crash
    assert out["picks"][1]["conviction_score"] == 5                 # "5/10" coerced


def test_csv_scan_with_renamed_columns(tmp_path, monkeypatch):
    (tmp_path / "20260928.csv").write_text(
        "Ticker,Company,Exchange,News,Sources,Catalyst Category,Conviction\n"
        'TCI.NS,Transport Corporation of India,NSE,"Sep 25, 2026: board to consider buyback, stock +15%",'
        '"https://a.com/x; https://b.com/y",Promoter Accumulation,4\n'
    )
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))
    out = ns.get_scan("20260928")
    p = out["picks"][0]
    assert out["source_format"] == "csv"
    assert p["symbol"]["yahoo"] == "TCI.NS" and p["company_name"] == "Transport Corporation of India"
    assert p["news"][0]["date"] == "Sep 25, 2026" and "buyback" in p["news"][0]["text"]
    assert [s["domain"] for s in p["sources"]] == ["a.com", "b.com"]
    assert p["conviction_score"] == 4


def test_json_preferred_over_csv_for_same_date(tmp_path, monkeypatch):
    (tmp_path / "20260929.json").write_text(json.dumps(PROMPT_ARRAY))
    (tmp_path / "20260929.csv").write_text("ticker,company_name\nX.NS,X\n")
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))
    assert [s["file"] for s in ns.list_scans()["scans"]] == ["20260929.json"]


def test_news_as_list_of_objects():
    items = ns.split_news([{"date": "2026-09-25", "headline": "Emerged L1"}, "Sep 26, 2026: LoA received"])
    assert items == [{"date": "2026-09-25", "text": "Emerged L1"}, {"date": "Sep 26, 2026", "text": "LoA received"}]


def test_broken_newest_file_falls_back_to_previous_scan(tmp_path, monkeypatch):
    (tmp_path / "20260925.json").write_text(json.dumps(PROMPT_ARRAY))
    (tmp_path / "20260926.json").write_text("[{\"ticker\": ")                  # LLM still writing
    monkeypatch.setenv("NEWS_SCANNER_DIR", str(tmp_path))
    listing = ns.list_scans()["scans"]
    assert listing[0]["picks"] == -1 and listing[0]["error"]
    assert ns.get_scan("latest")["file"] == "20260925.json"


def test_nse_bse_alternate_symbol():
    assert ns._alt_symbol("ABC.NS") == "ABC.BO" and ns._alt_symbol("ABC.BO") == "ABC.NS"
    assert ns._alt_symbol("GRAB") is None
