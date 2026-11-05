"""COT: the identity c_long = pm_long + sd_long + sd_spread, the typed row for 20 Oct 2026, gold_cot_metrics correctness on
the G-COT CSVs (COT index / z / percentile on REPORTS, not days), the fund-driver and quadrant label rules of G-STUDY
§5.1 and the who-did-what wording (PLAN §h T2, SOURCES.md §10 M11–M24)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest
from _support import G_COT, G_MACRO, read
from gold import cot_metrics, db, ingest_cot, ingest_yahoo

DATASETS = (("disagg_f", "cot_gold_disagg_futures_only.csv"), ("disagg_c", "cot_gold_disagg_combined.csv"),
            ("legacy_f", "cot_gold_legacy_futures_only.csv"), ("legacy_c", "cot_gold_legacy_combined.csv"))


@pytest.fixture
def loaded(store, now):
    for ds, f in DATASETS:
        raw, typed = ingest_cot.parse_csv_text(read(G_COT / f), ds, now=now)
        ingest_cot.ingest(store, ds, raw, typed)
    ingest_yahoo.ingest_daily(store, ingest_yahoo.parse_daily_csv(read(G_MACRO / "data" / "yahoo_GC_F.csv"), "GC=F", now=now))
    return store


def test_commercial_identity_holds_on_every_week(loaded):
    bad = ingest_cot.identity_check(loaded)
    assert bad.empty, bad.head()
    row = db.query_df(loaded, """SELECT l.c_long, d.pm_long, d.sd_long, d.sd_spread FROM gold_cot l JOIN gold_cot d
        ON l.report_date = d.report_date AND l.contract_code = d.contract_code AND l.fut_or_combined = d.fut_or_combined
        WHERE l.report = 'legacy' AND d.report = 'disagg' AND l.contract_code = '088691' AND l.fut_or_combined = 'F'
          AND l.report_date = DATE '2026-10-20'""").iloc[0]
    assert (int(row.c_long), int(row.pm_long), int(row.sd_long), int(row.sd_spread)) == (59531, 19715, 17737, 22079)


def test_the_20_oct_2026_row_matches_the_cftc_release(loaded):
    r = db.query_df(loaded, """SELECT * FROM gold_cot WHERE report = 'disagg' AND fut_or_combined = 'F' AND contract_code = '088691'
                               AND report_date = DATE '2026-10-20'""").iloc[0]
    assert (r.open_interest, r.oi_chg) == (402279, 5934)
    assert (r.mm_long, r.mm_short, r.mm_spread) == (120970, 16764, 38634)
    assert (r.pm_long, r.pm_short, r.sd_long, r.sd_short, r.sd_spread) == (19715, 34498, 17737, 238536, 22079)
    assert (r.or_long, r.or_short, r.nr_long, r.nr_short, r.traders_total) == (116172, 20513, 51407, 15690, 288)
    assert pd.Timestamp(r.release_at) == pd.Timestamp("2026-10-23 19:30") and r.release_source == "rule"
    c = db.query_df(loaded, """SELECT open_interest, mm_long - mm_short AS mm_net FROM gold_cot WHERE report = 'disagg'
                               AND fut_or_combined = 'C' AND contract_code = '088691' AND report_date = DATE '2026-10-20'""").iloc[0]
    assert int(c.open_interest) == 532443 and int(c.mm_net) - (120970 - 16764) == 4479
    counts = db.query_df(loaded, "SELECT report, fut_or_combined, COUNT(*) AS n FROM gold_cot WHERE contract_code = '088691' GROUP BY 1, 2")
    n = {(a, b): int(c) for a, b, c in counts.itertuples(index=False)}
    assert n[("disagg", "F")] == 1063 and n[("disagg", "C")] == 1063 and n[("legacy", "F")] == 1939 and n[("legacy", "C")] == 1648


def test_metrics_agree_with_the_g_cot_weekly_csv(loaded):
    m = cot_metrics.metrics_frame(loaded).set_index("report_date")
    ref = pd.read_csv(G_COT / "cot_gold_metrics_weekly.csv", parse_dates=["date"]).set_index("date")
    ref = ref[ref.index >= "2010-01-01"]
    j = m.join(ref, rsuffix="_ref", how="inner")
    assert len(j) > 800
    assert (j["mm_net"] - j["mm_net_ref"]).abs().max() == 0
    assert (j["mm_net_idx52"] - j["mm_net_idx52_ref"]).abs().max() < 0.5
    assert (j["mm_net_z52"] - j["mm_net_z52_ref"]).abs().max() < 0.05
    # the agent's percentile ranks each week against the FULL sample (look-ahead); ours is expanding (point-in-time) —
    # they coincide only on the last report, where FINDINGS quotes the 49th percentile
    assert abs(float(j["mm_net_pctile_all"].iloc[-1]) - float(j["mm_net_pctile_all_ref"].iloc[-1])) < 1.0
    last = m.loc["2026-10-20"]
    assert round(float(last["mm_net_idx52"])) == 26 and 47.5 <= float(last["mm_net_pctile_all"]) <= 50.5    # FINDINGS: index 26, 49th pct
    assert round(float(last["mm_net_pct_oi"])) == 26 and round(float(last["oi_pctile_all"])) == 22


def test_cot_index_and_z_are_windows_over_reports_not_days():
    s = pd.Series(np.arange(60, dtype=float))
    idx = cot_metrics.cot_index(s, 52)
    assert idx.isna().sum() == 51 and idx.iloc[-1] == 100.0 and idx.iloc[51] == 100.0
    z = cot_metrics.zscore(s, 52)
    assert z.isna().sum() == 51
    p = cot_metrics.expanding_percentile(pd.Series([5.0, 1.0, 3.0, 4.0]))
    assert list(p.round(2)) == [100.0, 50.0, 66.67, 75.0]         # no look-ahead: each value ranked among those seen so far


@pytest.mark.parametrize("dp,dl,ds,label", [
    (1.0, 3000, -500, "new longs"), (1.0, 100, -2000, "short covering"), (1.0, -100, 500, "funds sold into it"),
    (-1.0, -3000, 500, "long liquidation"), (-1.0, 100, 2000, "new shorts"), (-1.0, 500, -200, "funds bought the dip"),
    (None, 1, 1, None),
])
def test_driver_label_rules(dp, dl, ds, label):
    assert cot_metrics.driver_label(dp, dl, ds) == label


@pytest.mark.parametrize("dp,doi,label", [(1.0, 10, "long build-up"), (1.0, -10, "short covering"), (-1.0, 10, "short build-up"),
                                          (-1.0, -10, "long unwinding"), (None, 1, None)])
def test_quadrant_label_uses_the_oi_quadrant_vocabulary_of_the_contract(dp, doi, label):
    assert cot_metrics.quadrant_label(dp, doi) == label           # API_CONTRACT §2.5 / PLAN a.3 d.quadrant, not the fund-driver words
    assert label not in ("new longs", "new shorts", "long liquidation")


def test_who_did_wording():
    assert cot_metrics.who_did(-3777, -894) == ["closed 3,777 longs", "covered 894 shorts"]
    assert cot_metrics.who_did(1200, 300) == ["new 1,200 longs", "new 300 shorts"]
    assert cot_metrics.who_did(0, None) == ["no change"]
    assert "added" not in " ".join(cot_metrics.who_did(5, 5)) and cot_metrics.who_did(None, None) == ["no change"]


def test_summary_is_descriptive_and_carries_the_context_badge(loaded):
    s = cot_metrics.summary(loaded, weeks=52)
    assert s["available"] and s["badge"] == "context" and "does not forecast" in s["footer"]
    assert s["latest"]["report_date"] == "2026-10-20" and s["latest"]["next_release_ist"].startswith("2026-10-31T01:00")
    assert s["open_interest"]["total"] == 402279 and s["open_interest"]["chg"] == 5934
    mm = next(g for g in s["groups"] if g["key"] == "mm")
    assert mm["net"] == 104206 and mm["net_pct_oi"] == 25.9 and mm["who_did"] == ["closed 3,777 longs", "covered 894 shorts"]
    assert s["driver_label"] == "long liquidation"                     # three straight weeks of fund long liquidation (FINDINGS)
    assert s["options_overlay"]["line"] == "options add +4,479 to funds' net; combined OI 532,443"
    assert s["crowd"]["label"].startswith("crowdedness, not a signal") and "score" not in s
    assert len(s["history"]) == 52 and {"report_date", "price", "mm_net", "oi", "cot_index_52"} <= set(s["history"][-1])
    dec = {d["label"]: d for d in s["decomposition"]}
    assert dec["since the 2-year low"]["span"].startswith("2024-11-12") and dec["since the 2-year low"]["d_mm_net"] < -60000
    assert dec["since the high"]["span"].startswith("2026-03-10") and dec["since the high"]["d_or_net"] > 30000
    assert s["drawer"]["raw_block_url"].endswith("deacmxsf.htm") and s["drawer"]["micro_gold"]["oi"] > 0


def test_api_url_and_incremental_since(loaded):
    url, params = ingest_cot.api_url("disagg_f", date(2026, 10, 20))
    assert url.endswith("/72hh-3qpy.json") and "report_date_as_yyyy_mm_dd > '2026-10-20T00:00:00.000'" in params["$where"]
    assert params["$limit"] == "50000" and "'088691'" in params["$where"]
    assert ingest_cot.last_report_date(loaded, "disagg_f") == date(2026, 10, 20)


def test_release_events_cover_every_tuesday_in_ist(now):
    ev = ingest_cot.release_events(2026, now=now)
    assert (ev["kind"] == "COT_RELEASE").all() and len(ev) == 52
    sat = ev[ev["name"].str.contains("20 Oct")].iloc[0]
    assert (sat["event_date"], sat["time_ist"]) == (date(2026, 10, 24), "01:00")
    mon = ev[ev["name"].str.contains("10 Nov")].iloc[0]
    assert (mon["event_date"], mon["time_ist"]) == (date(2026, 11, 17), "02:00")      # Monday release, IST after the US clock change
