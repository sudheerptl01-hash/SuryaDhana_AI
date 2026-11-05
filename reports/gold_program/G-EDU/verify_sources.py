"""G-EDU source verification: fetch each reference live, record status / latency / sample / latest date.

Read-only, public sources, browser-like UA, 1.5 s between requests. Output: verify_results.json next to this file.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT = Path(__file__).with_name("verify_results.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/json,text/csv,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
PLAIN = {"User-Agent": "python-httpx"}   # FRED stalls browser UAs (project finding)

SOURCES: list[dict] = [
    # --- CFTC ---
    {"id": "cftc_cot_explanatory", "url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm", "kind": "html"},
    {"id": "cftc_cot_disagg_notes", "url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/DisaggregatedExplanatoryNotes/index.htm", "kind": "html"},
    {"id": "cftc_cot_release_schedule", "url": "https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm", "kind": "html"},
    {"id": "cftc_legacy_comex_short", "url": "https://www.cftc.gov/dea/futures/deacmxsf.htm", "kind": "html"},
    {"id": "cftc_disagg_other_long", "url": "https://www.cftc.gov/dea/futures/other_lf.htm", "kind": "html"},
    {"id": "cftc_socrata_disagg_fut", "url": "https://publicreporting.cftc.gov/resource/72hh-3qpy.json?commodity_name=GOLD&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=3", "kind": "json"},
    {"id": "cftc_socrata_disagg_combined", "url": "https://publicreporting.cftc.gov/resource/kh3c-gbw2.json?commodity_name=GOLD&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=2", "kind": "json"},
    {"id": "cftc_socrata_legacy_fut", "url": "https://publicreporting.cftc.gov/resource/6dca-aqww.json?commodity_name=GOLD&$order=report_date_as_yyyy_mm_dd%20DESC&$limit=2", "kind": "json"},
    {"id": "cftc_disagg_history_zip", "url": "https://www.cftc.gov/files/dea/history/fut_disagg_txt_2026.zip", "kind": "head"},
    {"id": "cftc_bank_participation", "url": "https://www.cftc.gov/MarketReports/BankParticipationReports/index.htm", "kind": "html"},
    # --- CME ---
    {"id": "cme_gold_specs", "url": "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html", "kind": "html"},
    {"id": "cme_gold_options_specs", "url": "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.options.html", "kind": "html"},
    {"id": "cme_gold_stocks_xls", "url": "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls", "kind": "head"},
    {"id": "cme_fedwatch", "url": "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html", "kind": "html"},
    # --- LBMA ---
    {"id": "lbma_prices", "url": "https://www.lbma.org.uk/prices-and-data/precious-metal-prices", "kind": "html"},
    {"id": "lbma_trade_data", "url": "https://www.lbma.org.uk/prices-and-data/lbma-trade-data", "kind": "html"},
    {"id": "lbma_vault_holdings", "url": "https://www.lbma.org.uk/prices-and-data/london-vault-holdings-data", "kind": "html"},
    {"id": "lbma_good_delivery", "url": "https://www.lbma.org.uk/good-delivery/about-good-delivery", "kind": "html"},
    {"id": "lbma_gd_rules", "url": "https://www.lbma.org.uk/good-delivery/gold-good-delivery-list", "kind": "html"},
    # --- WGC ---
    {"id": "wgc_etf_flows", "url": "https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows", "kind": "html"},
    {"id": "wgc_cb_reserves", "url": "https://www.gold.org/goldhub/data/gold-reserves-by-country", "kind": "html"},
    {"id": "wgc_demand_trends", "url": "https://www.gold.org/goldhub/research/gold-demand-trends", "kind": "html"},
    {"id": "wgc_gold_prices", "url": "https://www.gold.org/goldhub/data/gold-prices", "kind": "html"},
    # --- FRED / Treasury ---
    {"id": "fred_dfii10_csv", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10&cosd=2026-09-01", "kind": "csv", "headers": PLAIN},
    {"id": "fred_t10yie_csv", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10YIE&cosd=2026-09-01", "kind": "csv", "headers": PLAIN},
    {"id": "fred_dgs10_csv", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd=2026-09-01", "kind": "csv", "headers": PLAIN},
    {"id": "fred_dtwexbgs_csv", "url": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTWEXBGS&cosd=2026-09-01", "kind": "csv", "headers": PLAIN},
    {"id": "treasury_real_yield_csv", "url": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_real_yield_curve&field_tdr_date_value=2026", "kind": "csv", "timeout": 60},
    # --- ETFs ---
    {"id": "spdr_gld_page", "url": "https://www.spdrgoldshares.com/usa/", "kind": "html"},
    {"id": "spdr_gld_archive_csv", "url": "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv", "kind": "csv"},
    {"id": "ishares_iau", "url": "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund", "kind": "html"},
    # --- Asia ---
    {"id": "sge_delayed_quotes", "url": "https://en.sge.com.cn/data_DelayedQuotes", "kind": "html"},
    {"id": "sge_benchmark", "url": "https://en.sge.com.cn/data_BenchmarkPrice", "kind": "html"},
    {"id": "shfe_english", "url": "https://www.shfe.com.cn/eng/", "kind": "html"},
    # --- India ---
    {"id": "mcx_gold_product", "url": "https://www.mcxindia.com/products/bullion/gold", "kind": "html"},
    {"id": "mcx_market_data_bhav", "url": "https://www.mcxindia.com/market-data/bhavcopy", "kind": "html"},
    {"id": "ibja_rates", "url": "https://ibjarates.com/", "kind": "html"},
    {"id": "ibja_org", "url": "https://www.ibja.co/", "kind": "html"},
    {"id": "rbi_wss", "url": "https://www.rbi.org.in/Scripts/WSSView.aspx", "kind": "html"},
    {"id": "fbil", "url": "https://www.fbil.org.in/", "kind": "html"},
    {"id": "icici_security_master", "url": "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip", "kind": "head"},
    {"id": "dgcis_tradestat", "url": "https://tradestat.commerce.gov.in/", "kind": "html"},
    {"id": "amfi", "url": "https://www.amfiindia.com/", "kind": "html"},
    # --- Charts / retail references ---
    {"id": "kitco_gold_charts", "url": "https://www.kitco.com/charts/gold", "kind": "html"},
    {"id": "kitco_terms", "url": "https://www.kitco.com/terms-of-use", "kind": "html"},
    {"id": "yahoo_gc_chart", "url": "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?range=5d&interval=1d", "kind": "json"},
    {"id": "yahoo_gcz26_chart", "url": "https://query1.finance.yahoo.com/v8/finance/chart/GCZ26.CMX?range=5d&interval=1d", "kind": "json"},
    {"id": "yahoo_inr_chart", "url": "https://query1.finance.yahoo.com/v8/finance/chart/INR=X?range=5d&interval=1d", "kind": "json"},
    {"id": "yahoo_si_chart", "url": "https://query1.finance.yahoo.com/v8/finance/chart/SI=F?range=5d&interval=1d", "kind": "json"},
    # --- Academic / reference ---
    {"id": "erb_harvey_golden_dilemma", "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2078535", "kind": "html"},
    {"id": "baur_lucey_safe_haven", "url": "https://papers.ssrn.com/sol3/papers.cfm?abstract_id=952289", "kind": "html"},
    {"id": "fed_gold_real_rates_note", "url": "https://www.federalreserve.gov/econres/notes/feds-notes/", "kind": "html"},
]


def _title(text: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:160] if m else ""


def _csv_sample(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if r]
    if not rows:
        return {"rows": 0}
    header, body = rows[0], rows[1:]
    dates = [r[0] for r in body if r and re.match(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\d{2}-\w{3}-\d{4}", r[0])]
    return {"rows": len(body), "header": header[:12], "first": body[0][:8] if body else None,
            "last": body[-1][:8] if body else None, "latest_date_guess": (sorted(dates)[-1] if dates else None)}


def fetch(src: dict) -> dict:
    headers = src.get("headers", UA)
    t0 = time.perf_counter()
    rec = {"id": src["id"], "url": src["url"], "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    try:
        with httpx.Client(timeout=httpx.Timeout(src.get("timeout", 25)), headers=headers, follow_redirects=True) as c:
            if src["kind"] == "head":
                r = c.head(src["url"])
                if r.status_code >= 400:
                    r = c.get(src["url"], headers={**headers, "Range": "bytes=0-2047"})
            else:
                r = c.get(src["url"])
        rec["status"] = r.status_code
        rec["final_url"] = str(r.url)
        rec["latency_s"] = round(time.perf_counter() - t0, 2)
        rec["content_type"] = r.headers.get("content-type", "")
        rec["bytes"] = len(r.content) if src["kind"] != "head" else r.headers.get("content-length")
        rec["last_modified"] = r.headers.get("last-modified")
        if src["kind"] == "html":
            rec["title"] = _title(r.text)
            rec["snippet"] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))[:240]
        elif src["kind"] == "json":
            try:
                j = r.json()
                if isinstance(j, list):
                    rec["sample"] = j[:1]
                    rec["n"] = len(j)
                    rec["keys"] = sorted(j[0].keys())[:60] if j else []
                elif isinstance(j, dict) and "chart" in j:
                    res = (j["chart"].get("result") or [{}])[0]
                    meta = res.get("meta", {})
                    rec["sample"] = {k: meta.get(k) for k in ("symbol", "regularMarketPrice", "regularMarketTime", "currency", "exchangeName")}
                    ts = res.get("timestamp") or []
                    rec["latest_bar"] = datetime.fromtimestamp(ts[-1], tz=timezone.utc).isoformat() if ts else None
                else:
                    rec["sample"] = str(j)[:300]
            except ValueError:
                rec["sample"] = r.text[:300]
        elif src["kind"] == "csv":
            if "text/html" in rec["content_type"]:
                rec["title"] = _title(r.text)
                rec["note"] = "HTML returned where CSV expected"
            else:
                rec["csv"] = _csv_sample(r.text)
    except Exception as exc:  # noqa: BLE001 — record, never hide
        rec["status"] = None
        rec["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        rec["latency_s"] = round(time.perf_counter() - t0, 2)
    return rec


def main() -> None:
    results = []
    for i, src in enumerate(SOURCES):
        rec = fetch(src)
        results.append(rec)
        print(f"[{i+1:02d}/{len(SOURCES)}] {rec['id']:<32} {str(rec.get('status')):>4}  {rec.get('latency_s')}s  {rec.get('title') or rec.get('error') or rec.get('latest_bar') or ''}"[:150], flush=True)
        time.sleep(1.5)
    OUT.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
