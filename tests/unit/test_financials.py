import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "data-service"))

import financials as fin  # noqa: E402

XML = """<xbrli:xbrl>
<xbrli:context id="OneD"><xbrli:entity/><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="FourD"><xbrli:entity/><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<xbrli:context id="Seg1D"><xbrli:entity><xbrldi:explicitMember dimension="x:Axis">m</xbrldi:explicitMember></xbrli:entity><xbrli:period><xbrli:startDate>2026-07-01</xbrli:startDate><xbrli:endDate>2026-09-30</xbrli:endDate></xbrli:period></xbrli:context>
<in-capmkt:RevenueFromOperations contextRef="OneD" unitRef="INR" decimals="-5">731880000000</in-capmkt:RevenueFromOperations>
<in-capmkt:RevenueFromOperations contextRef="FourD" unitRef="INR" decimals="-5">1454630000000</in-capmkt:RevenueFromOperations>
<in-capmkt:ProfitLossForPeriod contextRef="OneD" unitRef="INR">139340000000</in-capmkt:ProfitLossForPeriod>
<in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations contextRef="OneD" unitRef="INRPerShare">38.37</in-capmkt:BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations>
</xbrli:xbrl>"""


def test_parse_takes_the_quarter_not_year_to_date():
    q = fin.parse_xbrl(XML)
    assert (q["period_start"], q["period_end"]) == ("2026-07-01", "2026-09-30")
    assert q["revenue"] == 731880000000 and q["pat"] == 139340000000 and q["eps"] == 38.37
    assert q["bank"] is False and q["pbt"] is None


def test_bank_taxonomy_gives_net_interest_income():
    xml = XML.replace("RevenueFromOperations", "InterestEarned") + \
        '<in-bank:InterestExpended contextRef="OneD">400000000000</in-bank:InterestExpended>'
    q = fin.parse_xbrl(xml)
    assert q["bank"] and q["nii"] == 331880000000


def test_choose_prefers_consolidated_and_latest_revision():
    integrated = [
        {"type": "Integrated Filing- Governance", "qe_Date": "30-SEP-2026", "xbrl": "g.xml"},
        {"type": "Integrated Filing- Financials", "qe_Date": "30-SEP-2026", "consolidated": "Standalone", "broadcast_Date": "08-Oct-2026 22:00:00", "xbrl": "s.xml"},
        {"type": "Integrated Filing- Financials", "qe_Date": "30-SEP-2026", "consolidated": "Consolidated", "broadcast_Date": "08-Oct-2026 22:07:33", "xbrl": "c.xml"},
        {"type": "Integrated Filing- Financials", "qe_Date": "30-SEP-2026", "consolidated": "Consolidated", "broadcast_Date": "10-Oct-2026 10:00:00", "xbrl": "c2.xml"}]
    legacy = [{"period": "Quarterly", "toDate": "31-Dec-2024", "consolidated": "Non-Consolidated", "broadCastDate": "09-Jan-2025 21:39:43", "xbrl": "old.xml"}]
    out = fin.choose_filings(integrated, legacy)
    assert [(f["period_end"], f["xbrl"]) for f in out] == [("2026-09-30", "c2.xml"), ("2024-12-31", "old.xml")]


def test_growth_matches_the_same_quarter_a_year_earlier():
    rows = [{"period_end": "2026-09-30", "revenue": 110.0, "pat": 22.0},
            {"period_end": "2026-06-30", "revenue": 105.0, "pat": 20.0},
            {"period_end": "2025-09-30", "revenue": 100.0, "pat": 25.0}]
    g = fin.with_growth(rows)
    assert g[0]["revenue_yoy"] == 10.0 and g[0]["pat_yoy"] == -12.0
    assert g[0]["revenue_qoq"] == 4.8 and g[0]["pat_margin"] == 20.0
    assert g[1]["revenue_yoy"] is None


def test_profit_sign_change_is_described_not_a_percentage():
    rows = [{"period_end": "2026-09-30", "revenue": 110.0, "pat": -5.0},
            {"period_end": "2025-09-30", "revenue": 100.0, "pat": 4.0}]
    g = fin.with_growth(rows)[0]
    assert g["pat_yoy"] is None and g["pat_yoy_turn"] == "to loss"
    back = fin.with_growth([{"period_end": "2026-09-30", "revenue": 1.0, "pat": 3.0},
                            {"period_end": "2025-09-30", "revenue": 1.0, "pat": -2.0}])[0]
    assert back["pat_yoy_turn"] == "to profit" and back["pat_yoy"] is None


def test_shares_book_and_valuation():
    xml = XML.replace("</xbrli:xbrl>", """
<xbrli:context id="OneI"><xbrli:entity/><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
<in-capmkt:PaidUpValueOfEquityShareCapital contextRef="OneD">3620000000</in-capmkt:PaidUpValueOfEquityShareCapital>
<in-capmkt:FaceValueOfEquityShareCapital contextRef="OneD">1</in-capmkt:FaceValueOfEquityShareCapital>
<in-capmkt:ProfitOrLossAttributableToOwnersOfParent contextRef="OneD">138840000000</in-capmkt:ProfitOrLossAttributableToOwnersOfParent>
<in-capmkt:EquityAttributableToOwnersOfParent contextRef="OneI">1189860000000</in-capmkt:EquityAttributableToOwnersOfParent>
</xbrli:xbrl>""")
    q = fin.parse_xbrl(xml)
    assert q["shares"] == 3620000000 and q["pat_owners"] == 138840000000 and q["book_equity"] == 1189860000000
    rows = [{**q, "period_end": pe} for pe in ("2026-09-30", "2026-06-30", "2026-03-31", "2025-12-31")]
    v = fin.valuation(rows, 2125.0)
    assert round(v["mcap"] / 1e7) == 769250 and v["ttm_profit"] == 4 * 138840000000
    assert v["pe"] == 13.9 and v["pb"] == 6.47
    gap = fin.valuation([rows[0], rows[1], rows[3]], 2125.0)      # a missing quarter: no TTM, no P/E
    assert gap["ttm_profit"] is None and gap["pe"] is None and gap["pb"] == 6.47


def test_zero_owners_profit_falls_back_to_total_profit():
    rows = [{"period_end": pe, "pat": 10.0, "pat_owners": 0.0, "shares": 10.0} for pe in ("2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30")]
    v = fin.valuation(rows, 20.0)
    assert v["ttm_profit"] == 40.0 and v["pe"] == 5.0


def test_shares_survive_a_face_value_typo():
    rows = [{"period_end": "2026-06-30", "pat": 1008.8e6, "eps": 5.16, "shares": 1e5},          # face value filed as 1956
            {"period_end": "2026-03-31", "pat": 1077.9e6, "eps": 5.51, "shares": 195.6e6}]
    assert fin.shares_estimate(rows) == 195.6e6
    only_eps = [{"period_end": "2026-06-30", "pat": 100.0, "eps": 2.0, "shares": None}]
    assert fin.shares_estimate(only_eps) == 50.0


def test_bank_book_value_and_cache_currency():
    xml = XML.replace("RevenueFromOperations", "InterestEarned").replace("</xbrli:xbrl>", """
<xbrli:context id="OneI"><xbrli:entity/><xbrli:period><xbrli:instant>2026-09-30</xbrli:instant></xbrli:period></xbrli:context>
<in-bank:Capital contextRef="OneI">15000000000</in-bank:Capital>
<in-bank:ReservesAndSurplus contextRef="OneI">485000000000</in-bank:ReservesAndSurplus>
</xbrli:xbrl>""")
    assert fin.parse_xbrl(xml)["book_equity"] == 500000000000
    assert fin.cache_current({"schema": fin.SCHEMA, "quarters": [{"bank": False, "pat": 1.0}]})
    assert not fin.cache_current({"schema": fin.SCHEMA, "quarters": [{"bank": True, "pat": 1.0}]})   # bank parsed before the fix
    assert fin.cache_current({"schema": fin.SCHEMA, "bank_schema": fin.BANK_SCHEMA, "quarters": [{"bank": True, "pat": 1.0}]})
    assert not fin.cache_current(None)


def test_life_insurer_taxonomy():
    xml = """<xbrli:xbrl>
<xbrli:context id="OneD"><xbrli:entity/><xbrli:period><xbrli:startDate>2026-04-01</xbrli:startDate><xbrli:endDate>2026-06-30</xbrli:endDate></xbrli:period></xbrli:context>
<in-li:NetPremiumIncome contextRef="OneD">167276300000</in-li:NetPremiumIncome>
<in-li:ProfitLossAfterTaxAndExtraordinaryItems contextRef="OneD">6111900000</in-li:ProfitLossAfterTaxAndExtraordinaryItems>
<in-li:BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized contextRef="OneD">2.83</in-li:BasicAndDilutedEPSAfterExtraordinaryItemsNetOfTaxExpenseForThePeriodNotToBeAnnualized>
</xbrli:xbrl>"""
    q = fin.parse_xbrl(xml)
    assert q["revenue"] == 167276300000 and q["pat"] == 6111900000 and q["eps"] == 2.83
    assert round(fin.shares_estimate([{**q, "shares": None}]) / 1e9, 2) == 2.16      # no face value tag: profit ÷ EPS
    assert not fin.cache_current({"schema": fin.SCHEMA, "quarters": [{"pat": None, "revenue": None}]})


def test_pe_series_is_point_in_time():
    import pandas as pd
    # quarters newest first; each filed ~6 weeks after the quarter end
    ends = ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"]
    filed = ["2026-08-10", "2026-05-10", "2026-02-10", "2025-11-10", "2025-08-10"]
    rows = [{"period_end": e, "filed_at": f + "T18:00:00", "pat": 25.0} for e, f in zip(ends, filed)]
    closes = pd.Series([10.0, 10.0, 12.0], index=pd.to_datetime(["2026-03-01", "2026-06-01", "2026-09-01"]))
    out = fin.pe_series(rows, closes, shares=1000.0)
    # 1 Mar 2026: no four filed quarters yet (Jun-25..Mar-26 is known only from 10 May) → skipped;
    # 1 Jun: 10×1000/100 = 100; 1 Sep: 12×1000/100 = 120
    assert [p["pe"] for p in out["points"]] == [100.0, 120.0]
    assert out["percentile"] == 50.0 and out["now"] == 120.0 and out["since"] == "2026-06-01"
    loss = fin.pe_series([{**r, "pat": -5.0} for r in rows], closes, shares=1000.0)
    assert loss["points"] == []                                          # loss-making: no P/E


def test_fix_scale_repairs_a_filer_unit_error():
    rows = [{"period_end": pe, "revenue": r, "pat": r / 10, "paid_up": 29.4e7 if pe != "2026-03-31" else 29.4e5} for pe, r in
            (("2026-06-30", 8164e7), ("2026-03-31", 60.04e7), ("2025-12-31", 8779e7), ("2025-09-30", 9000e7), ("2025-06-30", 7000e7))]
    fixed = fin.fix_scale(rows)
    bad = [q for q in fixed if q["period_end"] == "2026-03-31"][0]
    assert bad["scale_fixed"] == 100 and round(bad["revenue"] / 1e7) == 6004 and round(bad["pat"] / 1e7) == 600
    assert all("scale_fixed" not in q for q in fixed if q["period_end"] != "2026-03-31")
    g = fin.with_growth(rows)
    assert [q for q in g if q["period_end"] == "2026-06-30"][0]["revenue_qoq"] == 36.0     # vs the repaired quarter
    small = [{"period_end": "2026-06-30", "revenue": 5.0}, {"period_end": "2026-03-31", "revenue": 0.1}]
    assert fin.fix_scale(small) == small                                                     # too few quarters: untouched


def test_fix_scale_leaves_a_genuinely_tiny_quarter():
    # a dormant company restarting: one quarter is tiny, but its share capital is normal → not a unit error
    rows = [{"period_end": pe, "revenue": r, "paid_up": 500e7} for pe, r in
            (("2026-06-30", 60e7), ("2026-03-31", 55e7), ("2025-12-31", 45e7), ("2025-09-30", 40e7), ("2025-06-30", 0.42e7))]
    assert all("scale_fixed" not in q for q in fin.fix_scale(rows))
