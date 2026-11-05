"""G-CME live probe: fetch candidate free CME/COMEX gold sources, record status/latency/sample, save bodies.
Read-only, public endpoints only, ~1.5 s between requests, browser-like UA. Usage: probe.py <batch-name>"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent / "samples"
OUT.mkdir(exist_ok=True)
LOG = Path(__file__).resolve().parent / "probe_log.jsonl"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
           "Referer": "https://www.cmegroup.com/"}


def probe(name: str, url: str, params: dict | None = None, headers: dict | None = None,
          save_as: str | None = None, timeout: float = 40.0) -> dict:
    h = {**HEADERS, **(headers or {})}
    t0 = time.perf_counter()
    rec: dict = {"name": name, "url": url, "params": params}
    try:
        with httpx.Client(timeout=timeout, headers=h, follow_redirects=True, http2=False) as c:
            r = c.get(url, params=params)
        dt = time.perf_counter() - t0
        body = r.content
        ctype = r.headers.get("content-type", "")
        rec.update({"status": r.status_code, "latency_s": round(dt, 2), "content_type": ctype,
                    "bytes": len(body), "final_url": str(r.url),
                    "last_modified": r.headers.get("last-modified"), "server": r.headers.get("server")})
        fn = save_as or (name + (".json" if "json" in ctype else ".pdf" if "pdf" in ctype else
                                 ".xls" if "excel" in ctype or "octet" in ctype else ".html" if "html" in ctype else ".txt"))
        (OUT / fn).write_bytes(body)
        rec["saved"] = fn
        head = body[:300]
        try:
            rec["head"] = head.decode("utf-8", "replace") if not fn.endswith((".pdf", ".xls", ".zip")) else f"<binary {len(body)} B>"
        except Exception:  # noqa: BLE001
            rec["head"] = "<undecodable>"
    except Exception as exc:  # noqa: BLE001
        rec.update({"status": None, "error": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "latency_s": round(time.perf_counter() - t0, 2)})
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(f"{rec.get('status')} {rec.get('latency_s')}s {rec.get('bytes', '-')}B {name} :: {rec.get('error') or rec.get('head', '')[:140]!r}")
    time.sleep(1.5)
    return rec


BATCHES: dict[str, list[tuple]] = {
    "cme_core": [
        ("gc_settle_json", "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/Settlements/437/FUT",
         {"tradeDate": "10/23/2026", "strategy": "DEFAULT", "pageSize": "500"}),
        ("gc_settle_tradedates", "https://www.cmegroup.com/CmeWS/mvc/Settlements/Futures/TradeDate/437", None),
        ("gc_voi_json", "https://www.cmegroup.com/CmeWS/mvc/Volume/Details/F/437/20261023/P",
         {"tradeDate": "20261023", "pageSize": "500"}),
        ("gc_calendar_json", "https://www.cmegroup.com/CmeWS/mvc/ProductCalendar/Future/437", None),
        ("gc_quotes_json", "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/437/G", {"quoteCodes": "", "_": str(int(time.time() * 1000))}),
    ],
    "cme_bulletin": [
        ("bulletin_s62_current", "https://www.cmegroup.com/daily_bulletin/current/Section62_Metals_Futures_Products.pdf", None),
        ("bulletin_s63_current", "https://www.cmegroup.com/daily_bulletin/current/Section63_Metals_Options_Products.pdf", None),
        ("bulletin_prelim_voi_s62", "https://www.cmegroup.com/daily_bulletin/preliminary_voi/Section62_Metals_Futures_Products.pdf", None),
        ("ftp_root", "https://www.cmegroup.com/ftp/", None),
        ("ftp_pub_settle", "https://www.cmegroup.com/ftp/pub/settle/", None),
        ("ftp_bulletin", "https://www.cmegroup.com/ftp/bulletin/", None),
        ("ftp_pub_bulletin", "https://www.cmegroup.com/ftp/pub/bulletin/", None),
    ],
    "cme_delivery": [
        ("gold_stocks_xls", "https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls", None),
        ("silver_stocks_xls", "https://www.cmegroup.com/delivery_reports/Silver_stocks.xls", None),
        ("issues_stops_pdf", "https://www.cmegroup.com/delivery_reports/MetalsIssuesAndStopsReport.pdf", None),
        ("issues_stops_ytd_pdf", "https://www.cmegroup.com/delivery_reports/MetalsIssuesAndStopsYTDReport.pdf", None),
        ("delivery_notices_page", "https://www.cmegroup.com/clearing/operations-and-deliveries/nymex-delivery-notices.html", None),
    ],
    "cme_block_options": [
        ("block_trades_page", "https://www.cmegroup.com/tools-information/blocktrades.html", None),
        ("block_search_v2", "https://www.cmegroup.com/CmeWS/mvc/BlockTrade/V2/Search",
         {"exchange": "COMEX", "assetClass": "Metals", "pageSize": "50", "pageNumber": "1", "sortField": "tradeDate", "sortAsc": "false"}),
        ("og_option_settle", "https://www.cmegroup.com/CmeWS/mvc/Settlements/Options/Settlements/192/OOF",
         {"tradeDate": "10/23/2026", "strategy": "DEFAULT", "pageSize": "500"}),
        ("og_option_voi", "https://www.cmegroup.com/CmeWS/mvc/Volume/Details/O/192/20261023/P",
         {"tradeDate": "20261023", "pageSize": "500"}),
        ("product_slate_gold", "https://www.cmegroup.com/CmeWS/mvc/ProductSlate/V2/List",
         {"pageNumber": "1", "sortAsc": "false", "sortField": "oi", "searchString": "gold", "pageSize": "50"}),
        ("cvol_page", "https://www.cmegroup.com/market-data/cme-group-benchmark-administration/cme-cvol.html", None),
    ],
    "cme_specs": [
        ("gc_specs", "https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html", None),
        ("mgc_specs", "https://www.cmegroup.com/markets/metals/precious/e-micro-gold.contractSpecs.html", None),
        ("oz1_specs", "https://www.cmegroup.com/markets/metals/precious/1-ounce-gold.contractSpecs.html", None),
        ("qo_specs", "https://www.cmegroup.com/markets/metals/precious/e-mini-gold.contractSpecs.html", None),
        ("si_specs", "https://www.cmegroup.com/markets/metals/precious/silver.contractSpecs.html", None),
        ("gc_volume_page", "https://www.cmegroup.com/markets/metals/precious/gold.volume.html", None),
        ("cme_robots", "https://www.cmegroup.com/robots.txt", None),
    ],
    "context_asia": [
        ("shfe_daily_kx", "https://www.shfe.com.cn/data/dailydata/kx/kx20261023.dat", None, {"Referer": "https://www.shfe.com.cn/"}),
        ("shfe_daily_new", "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20261023.dat", None, {"Referer": "https://www.shfe.com.cn/"}),
        ("sge_delayed_quotes", "https://en.sge.com.cn/data_DelayedQuotes", None, {"Referer": "https://en.sge.com.cn/"}),
        ("sge_benchmark_cn", "https://www.sge.com.cn/sjzx/mrhqsj", None, {"Referer": "https://www.sge.com.cn/"}),
        ("dgcx_home", "https://www.dgcx.ae/", None, {}),
        ("jpx_gold", "https://www.jpx.co.jp/english/markets/derivatives/precious-metals/index.html", None, {}),
        ("bist_pm", "https://www.borsaistanbul.com/en/sayfa/3200/precious-metals-and-diamond-market", None, {}),
        ("stooq_xauusd", "https://stooq.com/q/d/l/", {"s": "xauusd", "i": "d"}, {}),
        ("stooq_xagusd", "https://stooq.com/q/d/l/", {"s": "xagusd", "i": "d"}, {}),
        ("kitco_robots", "https://www.kitco.com/robots.txt", None, {}),
    ],
}

if __name__ == "__main__":
    for b in sys.argv[1:]:
        print(f"=== batch {b}")
        for item in BATCHES[b]:
            name, url, params = item[0], item[1], item[2]
            hdr = item[3] if len(item) > 3 else None
            probe(name, url, params, hdr)
