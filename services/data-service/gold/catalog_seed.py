"""The catalog seed (PLAN §c.2): every series_id the GOLD page reads, with the verdict, badge and
``max_age_days`` taken from ``reports/gold_program/SOURCES.md`` (entry ids in ``source_entry``).

Labelling rules (PLAN §f) are enforced by this table: a number renders only if its series_id has a row whose
verdict is PUBLISH-CORE or PUBLISH-CONTEXT and whose badge is one of signal | context | arithmetic | heuristic.
No row carries ``signal`` today — no pre-registered study passed as a forecast (G-STUDY, 26 Oct 2026).
Dormant / blocked datasets keep a LINK-ONLY row with the reason, so the panel can say why it is empty.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

VERIFIED_AT = datetime(2026, 10, 26, 4, 10)  # noqa: DTZ001 — UTC-naive like every gold timestamp; the research agents' verification window (SOURCES.md)
VERIFIED_BY = "G-COT/G-CME/G-PHYSICAL/G-MACRO/G-INDIA/G-KITCO (26 Oct 2026)"

BADGES = ("signal", "context", "arithmetic", "heuristic")
VERDICTS = ("PUBLISH-CORE", "PUBLISH-CONTEXT", "LINK-ONLY", "DO-NOT-PUBLISH")
G_STUDY_CONTEXT = "context · G-STUDY 26 Oct 2026: no forecasting power 2006–2026; PASS as description"
NO_FORECAST = "FAIL as a forecast (G-STUDY 26 Oct 2026); contemporaneous explainer only"


def _row(series_id: str, name: str, entry: str, publisher: str, url: str, freq: str, unit: str, verdict: str, badge: str,
         max_age_days: int, *, resample: str = "last", job: str | None = None, publish_time_ist: str | None = None,
         lag_note: str | None = None, access: str = "FREE", terms: str | None = None, reason: str | None = None,
         evidence: str | None = None, beginner: str | None = None, pro: str | None = None, pros: str | None = None) -> dict[str, Any]:
    assert verdict in VERDICTS, series_id
    assert badge in BADGES, series_id
    return {"series_id": series_id, "name": name, "source_entry": entry, "publisher": publisher, "url": url, "freq": freq,
            "unit": unit, "publish_time_ist": publish_time_ist, "lag_note": lag_note, "access": access, "terms": terms,
            "verdict": verdict, "verdict_reason": reason, "badge": badge, "evidence": evidence, "beginner_note": beginner,
            "pro_note": pro, "how_pros_use_it": pros, "resample": resample, "ingest_job": job, "max_age_days": max_age_days,
            "verified_at": VERIFIED_AT, "verified_by": VERIFIED_BY}


YAHOO = "Yahoo Finance (unofficial chart API)"
YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?period1=&period2=&interval=1d"
YAHOO_TERMS = "Yahoo ToS: personal use, no redistribution; app UA on query2; period1/period2 never range=max"
FRED = "FRED, Federal Reserve Bank of St. Louis"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"
FRED_TERMS = "FRED legal: free with attribution; keyless CSV path"
WGC = "World Gold Council (Goldhub chart API)"
WGC_TERMS = "WGC T&Cs: personal/non-commercial; displayed with attribution, never re-served (owner decision O-1)"
SGE_TERMS = "SGE lists licensed distributors; view-only, attributed"
IMF_TERMS = "IMF PUBLIC_OPEN licence with citation"

# Yahoo daily bars (A1–A6, G17) — stored in gold_daily_bars, catalogued as series for the freshness/badge gate.
YAHOO_DAILY: dict[str, tuple[str, str, str, str]] = {   # series_id → (symbol, name, entry, unit)
    "COMEX_GC_FRONT": ("GC=F", "COMEX gold front future (continuous, last trade)", "A1", "USD/oz"),
    "COMEX_SI_FRONT": ("SI=F", "COMEX silver front future", "A3", "USD/oz"),
    "NYMEX_PL_FRONT": ("PL=F", "NYMEX platinum front future", "A3", "USD/oz"),
    "GLD_CLOSE": ("GLD", "SPDR Gold Shares close", "A4", "USD"),
    "GOLDBEES_CLOSE": ("GOLDBEES.NS", "Nippon GOLDBEES ETF close (rupee gold with 17-y history)", "A4", "INR"),
    "USDINR_CLOSE": ("INR=X", "USD/INR (Yahoo)", "A5", "INR per USD"),
    "DXY_CLOSE": ("DX-Y.NYB", "US dollar index (DXY)", "A5", "index"),
    "FX_EURUSD": ("EURUSD=X", "EUR/USD", "A5", "USD per EUR"),
    "FX_JPY": ("JPY=X", "USD/JPY", "A5", "JPY per USD"),
    "FX_GBPUSD": ("GBPUSD=X", "GBP/USD", "A5", "USD per GBP"),
    "FX_CAD": ("CAD=X", "USD/CAD", "A5", "CAD per USD"),
    "FX_SEK": ("SEK=X", "USD/SEK", "A5", "SEK per USD"),
    "FX_CHF": ("CHF=X", "USD/CHF", "A5", "CHF per USD"),
    "FX_CNY": ("CNY=X", "USD/CNY", "A5", "CNY per USD"),
    "GVZ_CLOSE": ("^GVZ", "CBOE gold ETF volatility (GVZ)", "A6", "vol %"),
    "VIX_CLOSE": ("^VIX", "CBOE VIX", "A6", "vol %"),
    "TNX_CLOSE": ("^TNX", "CBOE 10-y Treasury yield × 10", "A6", "% ×10"),
    "ZQ_FRONT": ("ZQ=F", "30-day fed funds future, front", "G17", "100 − rate"),
    "WTI_FRONT": ("CL=F", "NYMEX WTI front future", "A3", "USD/bbl"),
    # wave 1d (MACRO Brent 9 days stale on FRED): the Brent front future, a daily bar the 03:10 job stores from its next run
    "BRENT_FRONT": ("BZ=F", "Brent crude front future (NYMEX BZ, last trade)", "A3", "USD/bbl"),
}

FRED_DAILY = {   # series_id → (fred id, name, entry, unit, badge)
    "FRED_DFII5": ("DFII5", "5-y TIPS real yield", "G3", "%", "context"),
    "FRED_DFII7": ("DFII7", "7-y TIPS real yield", "G3", "%", "context"),
    "FRED_DFII10": ("DFII10", "10-y TIPS real yield (the opportunity cost of gold)", "G3", "%", "context"),
    "FRED_DFII20": ("DFII20", "20-y TIPS real yield", "G3", "%", "context"),
    "FRED_DFII30": ("DFII30", "30-y TIPS real yield", "G3", "%", "context"),
    "FRED_DGS2": ("DGS2", "2-y Treasury yield", "G5", "%", "context"),
    "FRED_DGS10": ("DGS10", "10-y Treasury yield", "G5", "%", "context"),
    "FRED_T10Y2Y": ("T10Y2Y", "10y–2y slope", "G5", "pp", "context"),
    "FRED_T10YIE": ("T10YIE", "10-y breakeven inflation", "G4", "%", "context"),
    "FRED_T5YIFR": ("T5YIFR", "5y5y forward inflation", "G4", "%", "context"),
    "FRED_GVZCLS": ("GVZCLS", "GVZ close (FRED archive)", "G8", "vol %", "context"),
    "FRED_VIXCLS": ("VIXCLS", "VIX close (FRED archive)", "G8", "vol %", "context"),
    "FRED_EFFR": ("EFFR", "Effective fed funds rate", "G6", "%", "context"),
    "FRED_SOFR": ("SOFR", "SOFR", "G6", "%", "context"),
    "FRED_DFEDTARU": ("DFEDTARU", "Fed funds target, upper", "G6", "%", "context"),
    "FRED_DCOILBRENTEU": ("DCOILBRENTEU", "Brent crude (FRED, 3–4 d behind)", "G9", "USD/bbl", "context"),
    "FRED_HY_OAS": ("BAMLH0A0HYM2", "US high-yield OAS", "G12", "%", "context"),
    "FRED_RRPONTSYD": ("RRPONTSYD", "Fed overnight reverse repo", "G10", "USD bn", "context"),
}
FRED_WEEKLY = {
    "FRED_DTWEXBGS": ("DTWEXBGS", "Broad trade-weighted dollar (H.10, weekly lag)", "G7", "index"),
    "FRED_DEXCHUS": ("DEXCHUS", "USD/CNY (H.10; the PBOC-parity fallback)", "G7", "CNY per USD"),
    "FRED_WALCL": ("WALCL", "Fed balance sheet, total assets", "G10", "USD mn"),
    "FRED_WTREGEN": ("WTREGEN", "Treasury General Account", "G10", "USD bn"),
    "FRED_WM2NS": ("WM2NS", "M2, weekly NSA", "G10", "USD bn"),
}
FRED_MONTHLY = {
    "FRED_M2SL": ("M2SL", "M2 money stock", "G10", "USD bn"),
    "FRED_CPIAUCSL": ("CPIAUCSL", "CPI-U", "G11", "index"),
    "FRED_CPILFESL": ("CPILFESL", "Core CPI", "G11", "index"),
    "FRED_PCEPILFE": ("PCEPILFE", "Core PCE price index", "G11", "index"),
    "FRED_PAYEMS": ("PAYEMS", "Non-farm payrolls", "G11", "thousands"),
    "FRED_UNRATE": ("UNRATE", "Unemployment rate", "G11", "%"),
    "FRED_EXPINF10YR": ("EXPINF10YR", "Cleveland Fed 10-y expected inflation", "G4", "%"),
    "FRED_MICH": ("MICH", "Michigan 1-y inflation expectations", "G4", "%"),
}

TREASURY_REAL = {"UST_REAL_5Y": "5 YR", "UST_REAL_7Y": "7 YR", "UST_REAL_10Y": "10 YR", "UST_REAL_20Y": "20 YR", "UST_REAL_30Y": "30 YR"}
TREASURY_NOM = {"UST_NOM_3M": "3 Mo", "UST_NOM_2Y": "2 Yr", "UST_NOM_10Y": "10 Yr", "UST_NOM_30Y": "30 Yr"}

IMF_COUNTRIES = ("IND", "CHN", "RUS", "TUR", "POL", "USA", "DEU", "ITA", "FRA", "JPN", "NLD", "CHE", "GBR", "KAZ", "UZB", "SAU",
                 "PRT", "ESP", "AUT", "BRA")
WGC_SD = ("mine", "recycled", "hedging", "jewellery", "technology", "bar_coin", "etf", "central_banks", "otc_other", "lbma_avg_price")
IBJA_PURITIES = ("999", "995", "916", "750", "585")

DERIVED = {   # series_id → (name, unit, badge, formula note)
    "GOLD_INR_LANDED": ("Landed cost ₹/10 g (no duty)", "INR/10g", "arithmetic",
                        "M5: G × INR ÷ 31.1034768 × 10 — the price of FINE gold (COMEX quotes per fine oz); purity P = × P/1000 (D1)"),
    "GOLD_INR_DUTY_PAID": ("Duty-paid landed ₹/10 g", "INR/10g", "arithmetic", "M6: landed × (1 + duty), duty dated"),
    "INDIA_PREMIUM_PCT": ("India dealer premium vs duty-paid landed (IBJA 999 PM)", "%", "context",
                          "M7: IBJA 999 PM ÷ (duty-paid landed × 0.999) − 1 (D1: landed is fine gold)"),
    "MCX_BASIS_PCT": ("MCX front settle vs duty-paid landed", "%", "context",
                      "M8: MCX GOLD front settlement proxy of the session ÷ (that session's duty-paid landed × 0.995) − 1 (995 fine, D1)"),
    "MCX_BASIS_CARRY_ADJ_PCT": ("MCX basis minus carry to expiry", "%", "context", "M8: MCX_BASIS_PCT − carry to expiry (995 fine, D1)"),
    "SHANGHAI_PREMIUM_USD": ("Shanghai premium $/oz (SGE PM vs London/COMEX)", "USD/oz", "context", "M9"),
    "SHANGHAI_PREMIUM_PCT": ("Shanghai premium %", "%", "context", "M9"),
    "COMEX_CARRY_ANN_PCT": ("COMEX front→next implied carry, annualised", "% p.a.", "arithmetic", "M31: (F2/F1 − 1) × 365/days"),
    "KGX_USD_EFFECT_PCT": ("Gold change due to the dollar (DXY weights)", "%", "arithmetic", "M56: −Σ wᵢ Δln fᵢ"),
    "KGX_PURE_GOLD_PCT": ("Gold change net of the dollar", "%", "arithmetic", "M56: gold + usd_move"),
    "KGX_INR_EFFECT_PCT": ("Rupee leg of the MCX move", "%", "arithmetic", "M56 rupee leg"),
    "GOLD_IN_INR": ("Gold in INR (landed ₹/10 g)", "INR/10g", "arithmetic", "M57"),
    "GOLD_IN_EUR": ("Gold in EUR", "EUR/oz", "arithmetic", "M57"),
    "GOLD_IN_JPY": ("Gold in JPY", "JPY/oz", "arithmetic", "M57"),
    "GOLD_IN_GBP": ("Gold in GBP", "GBP/oz", "arithmetic", "M57"),
    "GOLD_IN_CNY": ("Gold in CNY", "CNY/g", "arithmetic", "M57"),
    "GSR": ("Gold/silver ratio", "ratio", "context", "M42"),
    "GPR_RATIO": ("Gold/platinum ratio", "ratio", "context", "M42"),
    "GVZ_SIGMA_DAY_PCT": ("1σ day from GVZ", "%", "arithmetic", "M60: GVZ ÷ √252"),
    "ATR14_INR": ("ATR(14) of MCX GOLD front, ₹/10 g", "INR/10g", "arithmetic", "M60/M69"),
    "COMEX_GC_OI_PUTCALL": ("OG put/call OI ratio", "ratio", "context", "M36"),
}


def build_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sid, (sym, name, entry, unit) in YAHOO_DAILY.items():
        verdict = "PUBLISH-CORE" if entry in ("A1", "A5", "A6") else "PUBLISH-CONTEXT"   # A3/A4/G17 are PUBLISH-CONTEXT in SOURCES.md
        rows.append(_row(sid, name, entry, YAHOO, YAHOO_URL.format(symbol=sym), "D", unit, verdict, "arithmetic", 4,
                         job="yahoo_daily", publish_time_ist="03:10 overnight (prior US session)", terms=YAHOO_TERMS,
                         lag_note="≈1 min delayed; last trade, not settlement; GC=F rolls a few days before first notice",
                         evidence="it is the price; no forecast claim", pros="GC1 Comdty GP/GIP",
                         beginner="the world's benchmark gold price is the COMEX front future, not spot" if sid == "COMEX_GC_FRONT" else None,
                         access="FREE"))
    for sid, col in TREASURY_REAL.items():
        rows.append(_row(sid, f"US Treasury real yield {col}", "G1", "US Treasury",
                         "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
                         "?type=daily_treasury_real_yield_curve&field_tdr_date_value={year}", "D", "%", "PUBLISH-CORE", "context", 4,
                         job="treasury", publish_time_ist="02:00–03:00 IST (posts 15:30–16:30 ET)", evidence=NO_FORECAST,
                         beginner="what a safe dollar pays after inflation — gold's opportunity cost",
                         pro="H1: weekly beta −9.9 %/100 bp 2010–21, −5.0 since 2022; level fit sign-flipped after 2022"))
    for sid, col in TREASURY_NOM.items():
        rows.append(_row(sid, f"US Treasury nominal yield {col}", "G2", "US Treasury",
                         "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{year}/all"
                         "?type=daily_treasury_yield_curve&field_tdr_date_value={year}", "D", "%", "PUBLISH-CORE", "arithmetic", 4,
                         job="treasury", publish_time_ist="02:00–03:00 IST", pro="nominal = real + breakeven (identity verified to 0.0 bp)"))
    for sid, (fid, name, entry, unit, badge) in FRED_DAILY.items():
        verdict = "PUBLISH-CORE" if entry in ("G3", "G5", "G8") else "PUBLISH-CONTEXT"
        rows.append(_row(sid, name, entry, FRED, FRED_URL.format(id=fid), "D", unit, verdict, badge, 5, job="fred_daily",
                         publish_time_ist="≈01:45 IST, one US business day late", terms=FRED_TERMS, evidence=NO_FORECAST))
    for sid, (fid, name, entry, unit) in FRED_WEEKLY.items():
        rows.append(_row(sid, name, entry, FRED, FRED_URL.format(id=fid), "W", unit, "PUBLISH-CONTEXT", "context", 10,
                         job="fred_weekly", publish_time_ist="Mon 16:15 ET (H.10); Thu (H.4.1)", terms=FRED_TERMS))
    for sid, (fid, name, entry, unit) in FRED_MONTHLY.items():
        rows.append(_row(sid, name, entry, FRED, FRED_URL.format(id=fid), "M", unit, "PUBLISH-CONTEXT", "context", 45,
                         job="fred_monthly", publish_time_ist="~5th", terms=FRED_TERMS))
    rows.append(_row("GPR_MONTHLY", "Geopolitical Risk index, monthly (Caldara & Iacoviello)", "G23", "matteoiacoviello.com",
                     "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls", "M", "index", "PUBLISH-CONTEXT", "context", 45,
                     job="gpr", terms="free with citation (Caldara & Iacoviello 2022 AER)", evidence="H4: GPR change → next month t 1.0"))
    rows.append(_row("GPR_DAILY", "Geopolitical Risk index, daily", "G24", "matteoiacoviello.com",
                     "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls", "D", "index", "PUBLISH-CONTEXT", "context", 10,
                     job="gpr", publish_time_ist="weekly file", terms="free with citation"))
    rows.append(_row("WB_GOLD_MONTHLY_AVG", "World Bank Pink Sheet gold monthly average (1960→)", "G26", "World Bank CMO",
                     "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx",
                     "M", "USD/oz", "PUBLISH-CONTEXT", "context", 45, job="worldbank", terms="CC BY-4.0",
                     evidence="seasonality grid only: no month passes both halves (G-MACRO H3, G-STUDY §4.4)"))
    rows.append(_row("GLD_TONNES", "SPDR Gold Shares tonnes in trust (daily since 2004)", "E1", "SPDR Gold Shares (State Street / WGTS)",
                     "https://api.spdrgoldshares.com/api/v1/historical-archive?product=gld&exchange=NYSE&lang=en", "D", "tonnes",
                     "PUBLISH-CORE", "context", 5, job="etf_holdings", publish_time_ist="≈06:00 IST T+1",
                     terms="issuer disclaimer: no reproduction/redistribution — display-only with attribution (O-1)",
                     evidence="G-STUDY: 4-week change forecasts nothing (t ≤ 1.0); same-week R² 16 %",
                     beginner="when investors buy GLD shares the trust buys bars: tonnes up = Western investment demand"))
    rows.append(_row("IAU_TONNES", "iShares Gold Trust tonnes in trust", "E3", "iShares",
                     "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund", "D", "tonnes", "PUBLISH-CONTEXT", "context", 5,
                     job="etf_holdings", lag_note="regex of the product page; the CSV endpoint is dead"))
    for sid, name in {"WGC_ETF_FLOW_T_GLOBAL": "Global gold-ETF flow", "WGC_ETF_FLOW_T_NA": "North America ETF flow",
                      "WGC_ETF_FLOW_T_EU": "Europe ETF flow", "WGC_ETF_FLOW_T_ASIA": "Asia ETF flow",
                      "WGC_ETF_FLOW_T_OTHER": "Other ETF flow"}.items():
        rows.append(_row(sid, f"{name} (weekly, tonnes)", "E5", WGC,
                         "https://fsapi.gold.org/api/v11/charts/etfv2/revised/flows-chart2", "W", "tonnes", "PUBLISH-CORE", "context", 10,
                         resample="sum", job="wgc_etf", publish_time_ist="Mon ≈11:30 for the week ended Fri", terms=WGC_TERMS,
                         evidence="no verified OOS timing value (GS-P2 proposed)"))
    rows.append(_row("WGC_ETF_HOLD_T_GLOBAL", "Global gold-ETF holdings (tonnes)", "E5", WGC,
                     "https://fsapi.gold.org/api/v11/charts/etfv2/revised/holdings-chart2", "W", "tonnes", "PUBLISH-CORE", "context", 10,
                     job="wgc_etf", terms=WGC_TERMS))
    for sid, name in {"WGC_ETF_HOLD_T_NA": "North America gold-ETF holdings", "WGC_ETF_HOLD_T_EU": "Europe gold-ETF holdings",
                      "WGC_ETF_HOLD_T_ASIA": "Asia gold-ETF holdings", "WGC_ETF_HOLD_T_OTHER": "Other gold-ETF holdings"}.items():
        rows.append(_row(sid, f"{name} (weekly, tonnes)", "E5", WGC,
                         "https://fsapi.gold.org/api/v11/charts/etfv2/revised/holdings-chart2", "W", "tonnes", "PUBLISH-CONTEXT",
                         "context", 10, job="wgc_etf", terms=WGC_TERMS))
    rows.append(_row("WGC_ETF_FLOW_USD_MN_GLOBAL", "Global gold-ETF flow (weekly, US$ mn)", "E5", WGC,
                     "https://fsapi.gold.org/api/v11/charts/etfv2/revised/flows-chart2", "W", "USD mn", "PUBLISH-CONTEXT", "context", 10,
                     resample="sum", job="wgc_etf", terms=WGC_TERMS))
    rows.append(_row("WGC_ETF_HOLD_T_IN", "India gold-ETF holdings (tonnes, WGC country table)", "E5", WGC,
                     "https://fsapi.gold.org/api/v11/charts/etfv2/revised/archive-tablegroup/all", "W", "tonnes", "PUBLISH-CORE",
                     "context", 10, job="wgc_etf", terms=WGC_TERMS))
    for sid, name in {"WGC_PREMIUM_IN": "India local premium (WGC weekly)", "WGC_PREMIUM_CN": "China local premium (WGC weekly)"}.items():
        rows.append(_row(sid, name, "E8", WGC, "https://fsapi.gold.org/api/v11/charts/local-gold-price-premiums", "D", "USD/oz",
                         "PUBLISH-CONTEXT", "context", 10, job="wgc_premiums", terms=WGC_TERMS,
                         lag_note="the chart is daily-spaced (255 points/yr); the weekly view resamples with last"))
    for cat in WGC_SD:
        rows.append(_row(f"WGC_SD_{cat.upper()}", f"WGC balance sheet: {cat.replace('_', ' ')}", "E7", WGC,
                         "https://fsapi.gold.org/api/v11/charts/supply-and-demand/43", "Q", "tonnes" if cat != "lbma_avg_price" else "USD/oz",
                         "PUBLISH-CONTEXT", "context", 120, job="wgc_sd", publish_time_ist="~5 weeks after quarter end", terms=WGC_TERMS,
                         pro="supply ≡ demand by construction; 'OTC and other' is a balancing item; revised every quarter"))
    for iso in IMF_COUNTRIES:
        rows.append(_row(f"IMF_GOLD_OZ_{iso}", f"Official monetary gold, {iso} (fine troy oz, IMF IRFCL)", "E12", "IMF IRFCL (SDMX)",
                         "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL,12.0.0/", "M", "oz", "PUBLISH-CORE", "context", 60,
                         job="imf_official", publish_time_ist="~25th, 1–2 month lag", terms=IMF_TERMS,
                         beginner="How many troy ounces the central bank holds; ÷ 1,000,000 for millions of ounces, × 31.1035 ÷ 1,000,000 for tonnes",
                         pro="VALUE IS IN TROY OUNCES (units; the CSV's SCALE=6 is a display attribute, not a multiplier): Moz = value / 1e6, "
                             "t = value × 31.1034768 / 1e6. A country whose ounces disagree with its own USD value by ×1000 is rescaled at "
                             "ingest (quality 'rescaled_x1000'); above 300 Moz is rejected. Stale months repeat the last value — check "
                             "TIME_PERIOD; China reports late"))
        rows.append(_row(f"IMF_GOLD_USD_{iso}", f"Official monetary gold value, {iso} (USD, IMF IRFCL)", "E12", "IMF IRFCL (SDMX)",
                         "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IRFCL,12.0.0/", "M", "USD", "PUBLISH-CONTEXT", "context", 60,
                         job="imf_official", terms=IMF_TERMS))
    for sid, name in {"LBMA_AM_USD": "LBMA Gold Price AM (USD, via WGC chart)", "LBMA_PM_USD": "LBMA Gold Price PM (USD, via WGC chart)",
                      "SGE_AM_CNY_WGC": "SGE benchmark AM (CNY/g, via WGC chart)", "SGE_PM_CNY_WGC": "SGE benchmark PM (CNY/g, via WGC chart)",
                      "MCX_AM_INR_WGC": "MCX AM reference (INR, via WGC chart)"}.items():
        rows.append(_row(sid, name, "A9", WGC, "https://fsapi.gold.org/api/goldprice/v13/chart/main?period=1y", "D",
                         "USD/oz" if "USD" in sid else ("CNY/g" if "CNY" in sid else "INR/10g"), "PUBLISH-CONTEXT", "context", 4,
                         job="lbma_wgc", publish_time_ist="21:30", terms=WGC_TERMS + "; the LBMA price inside is IBA-licensed",
                         reason="PROVISIONAL until O-1; reference marks and premium bases only"))
    rows.append(_row("SGE_SHAU_AM", "Shanghai Gold Benchmark AM (SHAU)", "A11", "Shanghai Gold Exchange",
                     "https://en.sge.com.cn/graph/DayilyJzj", "D", "CNY/g", "PUBLISH-CORE", "context", 4, job="sge_benchmark",
                     publish_time_ist="07:45", terms=SGE_TERMS))
    rows.append(_row("SGE_SHAU_PM", "Shanghai Gold Benchmark PM (SHAU)", "A11", "Shanghai Gold Exchange",
                     "https://en.sge.com.cn/graph/DayilyJzj", "D", "CNY/g", "PUBLISH-CORE", "context", 4, job="sge_benchmark",
                     publish_time_ist="11:45 (14:15 Beijing)", terms=SGE_TERMS,
                     pro="PM is 14:15 Beijing vs LBMA PM 15:00 London — a 7-hour gap; compare like with like"))
    rows.append(_row("SGE_WITHDRAWALS_KG", "SGE monthly gold withdrawals", "D5", "Shanghai Gold Exchange",
                     "https://en.sge.com.cn/data_MonthlyReport", "M", "kg", "PUBLISH-CONTEXT", "context", 45, job="sge_monthly",
                     publish_time_ist="~10–12th", terms=SGE_TERMS))
    rows.append(_row("SGE_DELIVERY_RATIO", "SGE monthly delivery ratio", "D5", "Shanghai Gold Exchange",
                     "https://en.sge.com.cn/data_MonthlyReport", "M", "%", "PUBLISH-CONTEXT", "context", 45, job="sge_monthly"))
    rows.append(_row("LBMA_OTC_TURNOVER_USD_BN", "LBMA trade reporting weekly turnover, gold (12-wk MA)", "E14", "LBMA",
                     "https://www.lbma.org.uk/prices-and-data/lbma-trade-data", "W", "USD bn", "PUBLISH-CONTEXT", "context", 10,
                     job="lbma_turnover", publish_time_ist="Friday-dated",
                     lag_note=("regex of the headline; gross, not netted. The page shows ONE period and updates irregularly: on Thu 5 Nov "
                               "2026 22:11 IST it still showed the period ending Fri 16 Oct (verified); every new period is kept")))
    rows.append(_row("LBMA_VAULT_GOLD_T", "London vault holdings, gold", "E15", "LBMA",
                     "https://www.lbma.org.uk/prices-and-data/london-vault-holdings-data", "M", "tonnes", "PUBLISH-CONTEXT", "context", 45,
                     job="lbma_vault", publish_time_ist="~20–25th"))
    rows.append(_row("LBMA_VAULT_SILVER_T", "London vault holdings, silver", "E15", "LBMA",
                     "https://www.lbma.org.uk/prices-and-data/london-vault-holdings-data", "M", "tonnes", "PUBLISH-CONTEXT", "context", 45,
                     job="lbma_vault"))
    rows.append(_row("LBMA_OTC_TURNOVER_SILVER_USD_BN", "LBMA trade reporting weekly turnover, silver (12-wk MA)", "E14", "LBMA",
                     "https://www.lbma.org.uk/prices-and-data/lbma-trade-data", "W", "USD bn", "PUBLISH-CONTEXT", "context", 10,
                     job="lbma_turnover"))
    for p in IBJA_PURITIES:
        for fix in ("AM", "PM"):
            rows.append(_row(f"IBJA_{p}_{fix}", f"IBJA {p} gold rate, {fix}", "F10", "India Bullion & Jewellers Association",
                             "https://ibjarates.com/", "D", "INR/10g", "PUBLISH-CORE", "context", 4,
                             job="ibja_am" if fix == "AM" else "ibja_pm", publish_time_ist="13:45" if fix == "AM" else "18:10",
                             terms="/terms 404 — UNVERIFIED; the official API is paid; display-only (O-1)",
                             pro="without 3 % GST and making charges; 999 vs 995 (MCX is 995)"))
    rows.append(_row("IBJA_SILVER_999_PM", "IBJA silver 999 PM", "F10", "IBJA", "https://ibjarates.com/", "D", "INR/kg",
                     "PUBLISH-CONTEXT", "context", 4, job="ibja_pm"))
    rows.append(_row("IBJA_SILVER_999_AM", "IBJA silver 999 AM", "F10", "IBJA", "https://ibjarates.com/", "D", "INR/kg",
                     "PUBLISH-CONTEXT", "context", 4, job="ibja_am"))
    rows.append(_row("USDINR_FBIL", "RBI/FBIL USD-INR reference rate", "F13", "Reserve Bank of India",
                     "https://www.rbi.org.in/Scripts/ReferenceRateArchive.aspx", "D", "INR per USD", "PUBLISH-CONTEXT", "arithmetic", 4,
                     job="inr_ref", publish_time_ist="13:45", lag_note="timestamped rupee for landed cost / premiums; live rupee stays INR=X"))
    rows.append(_row("GOLD_IMPORT_DUTY_PCT", "Customs duty on gold (BCD + AIDC), dated steps", "F9", "CBIC (Notification 16/2026-Customs)",
                     "https://www.cbic.gov.in/", "D", "%", "PUBLISH-CORE", "arithmetic", 400, job="duty", publish_time_ist="on change",
                     reason="15 % since 2026-05-13 rests on secondary sources — owner confirms at CBIC (O-3)",
                     beginner="Indian gold = world gold + 15 % at the border; a duty change jumps the MCX price"))
    for sid, name in {"RBI_GOLD_RESERVES_USD_MN": "RBI gold reserves (US$ mn)", "RBI_GOLD_RESERVES_INR_CR": "RBI gold reserves (₹ cr)",
                      "RBI_RESERVES_TOTAL_USD_MN": "RBI total foreign-exchange reserves (US$ mn)"}.items():
        rows.append(_row(sid, name, "F11", "Reserve Bank of India (WSS)",
                         "https://www.rbi.org.in/Scripts/BS_viewWssExtract.aspx?SelectedDate=mm/dd/yyyy", "W", "USD mn" if "USD" in sid else "INR cr",
                         "PUBLISH-CONTEXT", "context", 10, job="rbi_wss", publish_time_ist="Fri 18:00",
                         pro="RBI's valuation convention (US$105.8 bn ÷ 28.31 Moz ≈ $3,737/oz) — use IMF ounces for quantity"))
    rows.append(_row("INDIA_GOLD_IMPORTS_USD_BN", "India monthly gold imports (US$ bn, PIB/Commerce)", "F14", "Ministry of Commerce via PIB",
                     "https://pib.gov.in/allRel.aspx", "M", "USD bn", "PUBLISH-CONTEXT", "context", 45, job="india_imports",
                     publish_time_ist="~16th", lag_note="release URL pattern UNVERIFIED — ingest by regex or by hand; keep the PRID"))
    rows.append(_row("SWISS_GOLD_EXPORT_IN_KG", "Swiss gold exports to India (BAZG open data)", "E19", "Swiss customs (BAZG)",
                     "https://ocean.nivel.bazg.admin.ch/open-data-reports/TN8_EXP_en/TN8_EXP_en.zip", "M", "kg", "PUBLISH-CONTEXT", "context", 45,
                     job="swiss", publish_time_ist="~22nd", terms="open use with attribution", lag_note="692 MB zip streamed and filtered"))
    for sid, name in {"AMFI_GOLD_ETF_NET_CR": "AMFI gold-ETF net flow (₹ cr)", "AMFI_GOLD_ETF_AUM_CR": "AMFI gold-ETF month-end AUM (₹ cr)",
                      "AMFI_GOLD_ETF_FOLIOS": "AMFI gold-ETF folios", "AMFI_GOLD_ETF_SCHEMES": "AMFI gold-ETF scheme count",
                      "AMFI_GOLD_ETF_AVG_AUM_CR": "AMFI gold-ETF average AUM for the month (₹ cr)"}.items():
        rows.append(_row(sid, name, "F16", "AMFI", "https://portal.amfiindia.com/spages/am{mon}{yyyy}repo.xls", "M",
                         "INR cr" if "CR" in sid else "count", "PUBLISH-CONTEXT", "context", 45, job="amfi", publish_time_ist="~11th",
                         evidence="G-INDIA-1: flows chase returns (ρ +0.25), do not predict (ρ +0.12, p 0.31)"))
    for sid, (name, unit, badge, note) in DERIVED.items():
        rows.append(_row(sid, name, "§10", "SuryaDhana (derived)", "derived", "D", unit,
                         "PUBLISH-CORE" if badge == "arithmetic" else "PUBLISH-CONTEXT", badge, 4, job="derive", pro=note,
                         evidence="identity" if badge == "arithmetic" else "no forecasting evidence; context"))
    # table-backed datasets (verdict gate + freshness for the typed tables)
    rows.append(_row("COT_DISAGG_F", "CFTC COT disaggregated, futures-only (COMEX gold 088691)", "B1", "CFTC (Socrata)",
                     "https://publicreporting.cftc.gov/resource/72hh-3qpy.json", "W", "contracts", "PUBLISH-CORE", "context", 9, job="cot",
                     publish_time_ist="Sat 01:00 (02:00 from 7 Nov 2026); Tuesday positions", terms="US public domain; robots ai-train=no",
                     evidence=G_STUDY_CONTEXT, reason="explains the week — does not forecast",
                     beginner="who is on which side by TYPE of trader; every long has a short",
                     pro="commercial long (legacy) = producer long + swap long + swap spread; categories self-declared (Form 40)",
                     pros="CFTC <GO>; managed-money net vs price and the week-on-week change"))
    rows.append(_row("COT_DISAGG_C", "CFTC COT disaggregated, futures + options combined", "B2", "CFTC (Socrata)",
                     "https://publicreporting.cftc.gov/resource/kh3c-gbw2.json", "W", "contracts", "PUBLISH-CONTEXT", "context", 9,
                     job="cot", evidence="options-only positioning: no information (G-STUDY t ≤ 0.2)", reason="one line in the drawer"))
    rows.append(_row("COT_LEGACY_F", "CFTC COT legacy, futures-only (1986→)", "B3", "CFTC (Socrata)",
                     "https://publicreporting.cftc.gov/resource/6dca-aqww.json", "W", "contracts", "PUBLISH-CORE", "context", 9, job="cot",
                     reason="ingest for the 1986–2006 history and the concentration ratios; never a panel of its own"))
    rows.append(_row("COT_LEGACY_C", "CFTC COT legacy, combined (1995→)", "B4", "CFTC (Socrata)",
                     "https://publicreporting.cftc.gov/resource/jun7-fc8e.json", "W", "contracts", "PUBLISH-CONTEXT", "context", 9, job="cot"))
    rows.append(_row("CME_VOI", "CME daily volume and open interest by product (COMEX GC/MGC/1OZ/QO/OG, SI)", "C1", "CME Group (FTP)",
                     "ftp://ftp.cmegroup.com/daily_volume/daily_volume.xlsx", "D", "contracts", "PUBLISH-CORE", "context", 4, job="cme_voi",
                     publish_time_ist="≈14:00–15:30 IST, T+1 (confirm in week one)", terms="anonymous FTP; no terms file in the tree",
                     beginner="OI down = positions closed; rising price + rising OI = new longs",
                     pro="product OI, all months summed; roll weeks and expiry/exercise days are mechanical",
                     evidence="daily quadrant untested (G-STUDY-2 proposed); weekly version 1 of 12 cells"))
    rows.append(_row("CME_EFRP", "CME EFRP transaction breakdown (EFP/EFR prints)", "C2", "CME Group (FTP)",
                     "ftp://ftp.cmegroup.com/efrp/efrp_transaction_breakdown/efrp-report.csv", "D", "round turns", "PUBLISH-CONTEXT",
                     "context", 4, job="cme_efrp", pro="volume, never the EFP price"))
    rows.append(_row("CME_CALENDAR", "CME product calendar (first notice, last trade, delivery windows)", "C3", "CME Group (FTP)",
                     "ftp://ftp.cmegroup.com/span/util/product-calendar-new.xml", "W", "dates", "PUBLISH-CORE", "arithmetic", 10,
                     job="cme_calendar", publish_time_ist="Sun 04:00 weekly", lag_note="38 MB XML, iterparse"))
    rows.append(_row("CME_PRF", "COMEX product reference (specs, settlement method, tick, initial margin)", "C4", "CME Group (FTP)",
                     "ftp://ftp.cmegroup.com/pub/fprf/csv/cmeg.comex.fut.prf.csv.zip", "D", "spec", "PUBLISH-CORE", "arithmetic", 4,
                     job="cme_prf", pro="the field named MaintMargin cannot be the maintenance margin (open question j.2 #6)"))
    rows.append(_row("MCX_CURVE_ICICI", "MCX gold family settlement (band midpoint) and OI per expiry, ICICI master", "F1", "ICICI Direct",
                     "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip", "D", "INR/10g", "PUBLISH-CORE", "arithmetic", 4,
                     job="mcx_master", publish_time_ist="07:35 (retry 08:35)",
                     lag_note=("PROXY settlement (band midpoint). The file published on D carries the OI of S1 = the previous "
                               "session and the band in force DURING S1, centred on the settlement of the session BEFORE S1 "
                               "(verified 5 Nov 2026 against Breeze VWAP30); reads re-key the midpoint to that session"),
                     pro="OI sits in the shifted MarginPercentage column; the Monday file carries Friday's OI and Thursday's settlement"))
    # wave 1d (the 5 Nov blocker): the settlement proxy MCX's own method implies — one template row per family; the stored
    # ids are per contract month (MCX_GOLD_202612_VWAP30 → this row, reads.catalog_row)
    for fam, unit in (("GOLD", "INR/10g"), ("GOLDM", "INR/10g"), ("GOLDTEN", "INR/10g"), ("GOLDPETAL", "INR/1g"),
                      ("GOLDGUINEA", "INR/8g")):
        rows.append(_row(f"MCX_{fam}_VWAP30", f"MCX {fam} settlement proxy: last-30-min VWAP of Breeze 1-minute bars (per contract month)",
                         "F2", "ICICI Breeze (computed)", "https://api.icicidirect.com/breezeapi/documents/index.html", "D", unit,
                         "PUBLISH-CORE", "arithmetic", 4, job="mcx_close_vwap30", publish_time_ist="23:58 after the MCX close",
                         access="FREE-REGISTRATION",
                         lag_note="PROXY of MCX's settlement method (VWAP of the last 30 minutes); never called the settlement",
                         evidence="identity over the session's 1-minute bars; Tue 03 Nov 1,39,448 vs the next band midpoint 1,39,452",
                         beginner="yesterday's MCX settlement, estimated the way MCX computes it",
                         pro="Σ close·lots ÷ Σ lots over the bars starting in [close − 30 min, close); 23:25–23:55 IST in US winter"))
        rows.append(_row(f"MCX_{fam}_VWAP30_LOTS", f"MCX {fam} lots traded in the settlement window (per contract month)", "F2",
                         "ICICI Breeze (computed)", "https://api.icicidirect.com/breezeapi/documents/index.html", "D", "lots",
                         "PUBLISH-CORE", "arithmetic", 4, job="mcx_close_vwap30", publish_time_ist="23:58 after the MCX close",
                         access="FREE-REGISTRATION", lag_note="a thin window (a few lots) makes a noisy proxy"))
    rows.append(_row("MCX_MARGIN_ZERODHA", "MCX NRML margins (Zerodha mirror)", "F8", "Zerodha", "https://zerodha.com/margin-calculator/Commodity/",
                     "D", "INR", "PUBLISH-CONTEXT", "arithmetic", 4, job="margins", publish_time_ist="daily, dated on the page",
                     lag_note="exchange NRML (SPAN + exposure); ICICI's plan-dependent margin may differ"))
    rows.append(_row("COMEX_CURVE_YAHOO", "COMEX per-month last prices (Yahoo GCZ26.CMX …)", "A2", YAHOO,
                     "https://query2.finance.yahoo.com/v8/finance/chart/GCZ26.CMX?range=5d&interval=1d", "D", "USD/oz", "PUBLISH-CORE",
                     "arithmetic", 4, job="yahoo_curve", lag_note="LAST TRADE, not settlement, until bulletin settlements are allowed (O-2)"))
    rows.append(_row("BARS_1M", "COMEX GC 1-minute bars (7-day window) + INR=X + SGE delayed", "A1", YAHOO,
                     "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=7d&interval=1m&includePrePost=true", "I", "USD/oz",
                     "PUBLISH-CORE", "arithmetic", 1, job="intraday_bars", publish_time_ist="every 5 min", terms=YAHOO_TERMS))
    rows.append(_row("SGE_DAILY", "SGE daily market data (Au99.99 spot, Au(T+D) deferred: close, VWAP, OI, direction)", "D3",
                     "Shanghai Gold Exchange", "https://en.sge.com.cn/data/data_daily_international_new", "D", "CNY/g", "PUBLISH-CORE",
                     "context", 4, job="sge_daily", publish_time_ist="16:10", terms=SGE_TERMS,
                     pro="Direction = who pays the deferred fee: 'Short to Long' = shorts pay = physical tightness"))
    rows.append(_row("SHFE_DAILY", "SHFE gold futures daily (au, per delivery month)", "D1", "Shanghai Futures Exchange",
                     "https://www.shfe.com.cn/data/tradedata/future/dailydata/kxYYYYMMDD.dat", "D", "CNY/g", "PUBLISH-CONTEXT", "context", 4,
                     job="shfe", lag_note="non-trading days return a 404 HTML page → not an error"))
    # wave 1c (C-BEGINNER-16 / C-DATA-17): the three Asia ids the POSITIONING p.asia panel reads as single-value series —
    # served by reads.series from gold_asia_daily (ASIA_SERIES), so a catalog row exists for every id the page prints
    rows.append(_row("SGE_AUTD_OI", "SGE Au(T+D) deferred open interest (kg)", "D3", "Shanghai Gold Exchange",
                     "https://en.sge.com.cn/data/data_daily_international_new", "D", "kg", "PUBLISH-CONTEXT", "context", 4, job="sge_daily",
                     publish_time_ist="16:10", terms=SGE_TERMS, reason=NO_FORECAST,
                     beginner="How much Shanghai deferred gold is open; it describes the day, it does not forecast",
                     pro="Au(T+D) OI from the SGE daily table (gold_asia_daily, contract Au(T+D)); read with the direction"))
    rows.append(_row("SGE_AUTD_DIRECTION", "SGE Au(T+D) deferred-fee direction (+1 longs pay shorts · −1 shorts pay longs · 0 none)", "D3",
                     "Shanghai Gold Exchange", "https://en.sge.com.cn/data/data_daily_international_new", "D", "direction", "PUBLISH-CONTEXT",
                     "context", 4, job="sge_daily", publish_time_ist="16:10", terms=SGE_TERMS, reason=NO_FORECAST,
                     beginner="Who pays the deferred fee today: shorts paying (−1) means more buyers want the metal than sellers can deliver",
                     pro="encoded from the table's Direction text: 'Long to Short' = +1 (longs pay), 'Short to Long' = −1 (shorts pay = physical "
                         "tightness), '—' = 0; never coloured, never a signal"))
    rows.append(_row("SHFE_AU_FRONT_OI", "SHFE gold most-active contract open interest (lots)", "D1", "Shanghai Futures Exchange",
                     "https://www.shfe.com.cn/data/tradedata/future/dailydata/kxYYYYMMDD.dat", "D", "lots", "PUBLISH-CONTEXT", "context", 4,
                     job="shfe", lag_note="non-trading days return a 404 HTML page → not an error", reason=NO_FORECAST,
                     beginner="Open positions in the Shanghai gold future most people trade (the 'main' month, not the nearest one)",
                     pro="the max-OI au contract on the day (China's 主力合约 convention; the nearest month is in delivery and thin); "
                         "from gold_asia_daily exchange SHFE"))
    rows.append(_row("FED_PATH_ATL", "Atlanta Fed Market Probability Tracker (per-meeting P(cut)/P(hike)/mean)", "G16", "Federal Reserve Bank of Atlanta",
                     "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/data/market-probability-tracker/mpt_histdata.xlsx",
                     "D", "probability", "PUBLISH-CORE", "context", 5, job="atlanta_fed", terms="LICENSE sheet not machine-readable — owner reads it (O-10)"))
    rows.append(_row("US_CALENDAR_FF", "US economic calendar (this week) in IST", "G19", "Forex Factory (faireconomy)",
                     "https://nfs.faireconomy.media/ff_calendar_thisweek.json", "D", "events", "PUBLISH-CORE", "arithmetic", 7, job="calendar_us",
                     publish_time_ist="hourly 09:00–23:00", terms="personal use, cache, no hammering"))
    rows.append(_row("GOLD_EVENTS", "Gold calendar (COT releases, COMEX FND/LTD, MCX expiries/holidays, festivals, Budget)", "B10/C3/F19",
                     "SuryaDhana (compiled)", "derived", "D", "events", "PUBLISH-CONTEXT", "arithmetic", 7, job="events"))
    rows.append(_row("GOLD_BRIEF", "Daily automated pre-open brief (gold_premarket/YYYYMMDD.json)", "H1", "SuryaDhana desk (scheduled task)",
                     "gold_premarket/", "D", "document", "PUBLISH-CONTEXT", "context", 3, job="brief",
                     reason="schema-validated; shown as 'automated brief, confidence X'"))
    rows.append(_row("PREOPEN_LOG", "Fair-open accuracy log", "H2", "SuryaDhana (08:45 snapshot + open capture)", "data/gold_preopen/log.json",
                     "D", "INR/10g", "PUBLISH-CORE", "arithmetic", 5, job="preopen_log",
                     evidence="3 scored mornings: model mean miss ₹2,496 vs naive ₹2,147; 0 % within ₹300 → the verdict wears heuristic"))
    rows.append(_row("XAU_CROSSCHECK", "gold-api.com real-time XAU cross-check (not stored)", "A12", "gold-api.com",
                     "https://api.gold-api.com/price/XAU", "I", "USD/oz", "PUBLISH-CONTEXT", "context", 1, job=None,
                     terms="free, commercial use permitted, ≤ 1 call/min, no accuracy guarantee"))
    # dormant / blocked datasets: the panel shows the link and the reason
    rows.append(_row("MCX_CATEGORY_OI", "MCX category-wise OI (monthly workbook)", "F4", "MCX", "https://www.mcxindia.com/market-data",
                     "M", "lots", "LINK-ONLY", "context", 45, job=None, access="BLOCKED",
                     reason="DORMANT: 403 Akamai to every scripted client; needs the O-8 browser-session collector"))
    rows.append(_row("MCX_BHAVCOPY", "MCX official daily bhavcopy (settlement, volume, OI)", "F3", "MCX",
                     "https://www.mcxindia.com/market-data/bhavcopy", "D", "INR/10g", "LINK-ONLY", "arithmetic", 4, job=None, access="BLOCKED",
                     reason="DORMANT: 403 Akamai bot wall (O-8); the ICICI master band midpoint stands in (quality=proxy)"))
    rows.append(_row("BREEZE_DAILY", "ICICI Breeze daily bars with OI per MCX expiry", "F2", "ICICI Breeze",
                     "https://api.icicidirect.com/breezeapi/documents/index.html", "D", "INR/10g", "PUBLISH-CONTEXT", "arithmetic", 4,
                     job=None, access="FREE-REGISTRATION",
                     reason="PUBLISH as description (O-8, owner-authorised 6 Nov 2026; live-verified: 5 Breeze codes, 15 contracts, OI "
                     "equals the ICICI master's roll ratio): which MCX gold positions were opened or closed per contract by day / "
                     "week / month is OI × price arithmetic, the same rule as the published OI quadrant tape; G-STUDY: positioning "
                     "FAILS as a forecast, PASSES as a description. Live expiries only (OI unreliable for old contracts)"))
    rows.append(_row("COMEX_WAREHOUSE", "COMEX warehouse stocks (registered / eligible / pledged)", "C8", "CME Group (www)",
                     "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls", "D", "oz", "LINK-ONLY", "context", 4, job=None,
                     access="BLOCKED", reason="www.cmegroup.com 403 to this IP (O-2); never fetched by the stack"))
    rows.append(_row("CME_BULLETIN_SETTLE", "CME Daily Bulletin per-month settlements (Section 62)", "C7", "CME Group (www)",
                     "https://www.cmegroup.com/daily_bulletin/current/Section62_Metals_Futures_Products.pdf", "D", "USD/oz", "LINK-ONLY",
                     "arithmetic", 4, job=None, access="BLOCKED", reason="403 (O-2); Yahoo per-month last trade stands in, labelled LAST TRADE"))
    seen: set[str] = set()
    for r in rows:
        assert r["series_id"] not in seen, f"duplicate catalog id {r['series_id']}"
        seen.add(r["series_id"])
    return rows


def seed_frame() -> pd.DataFrame:
    return pd.DataFrame(build_rows())


def seed(store: Any) -> int:
    """Idempotent: INSERT OR REPLACE every row (the catalog is code, not data)."""
    from gold import db
    return db.upsert(store, "gold_series_catalog", seed_frame())


def max_age_for(series_id: str) -> int | None:
    for r in build_rows():
        if r["series_id"] == series_id:
            return int(r["max_age_days"])
    return None
