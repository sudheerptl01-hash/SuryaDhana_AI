#!/usr/bin/env python
"""
NSE free-data catalog — probe every free NSE dataset useful for research and record what
it contains, how to fetch it, and how often it is published.

    python scripts/nse_free_data_catalog.py [--symbol INFY] [--date 2026-09-25]

Two families:
  * Daily report files listed by NSE's "All Reports" page (nsearchives.nseindia.com) —
    downloaded for one trading day, parsed, columns and row counts recorded.
  * JSON APIs behind the website pages (www.nseindia.com/api/...) — market-wide and per
    stock. Most answer plain HTTPS; the few that Akamai blocks are retried through
    headless Chrome.

Output: reports/nse_catalog/  summary.json (+ samples/*.json with the first rows of each).
Read-only public data; about 90 requests, paced at ~1/s.
"""
from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))
from bhavcopy import HEADERS  # noqa: E402  (browser User-Agent NSE expects)

OUT = ROOT / "reports" / "nse_catalog"
API = "https://www.nseindia.com"
PAUSE_S = 0.9


class Probe:
    def __init__(self) -> None:
        self.http = httpx.Client(headers=HEADERS, timeout=45, follow_redirects=True)
        self.api_headers = {**HEADERS, "Accept": "application/json, text/plain, */*",
                            "Referer": "https://www.nseindia.com/"}
        self.results: list[dict] = []
        self._browser = None
        (OUT / "samples").mkdir(parents=True, exist_ok=True)

    # ── helpers ─────────────────────────────────────────────────────────────────
    def save(self, name: str, payload: Any) -> None:
        (OUT / "samples" / f"{name}.json").write_text(json.dumps(payload, indent=1, default=str)[:400_000])

    def record(self, **rec) -> None:
        self.results.append(rec)
        ok = "ok " if rec.get("status") == 200 and rec.get("rows") else "-- "
        print(f"{ok}{rec['name'][:48]:48} {str(rec.get('status')):>4} rows={rec.get('rows', 0):<6} {rec.get('via', '')}"
              f"{'  ' + str(rec.get('error'))[:70] if rec.get('error') else ''}")
        time.sleep(PAUSE_S)

    def browser_get(self, url: str) -> tuple[int, str]:
        """Fetch through real Chrome after a page visit (Akamai cookie), for blocked APIs."""
        from playwright.sync_api import sync_playwright
        if self._browser is None:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(channel="chrome", headless=True)
            self._page = self._browser.new_page(user_agent=HEADERS["User-Agent"])
            self._page.goto("https://www.nseindia.com/get-quotes/equity?symbol=INFY", wait_until="domcontentloaded",
                            timeout=60_000)
            self._page.wait_for_timeout(3000)
        res = self._page.evaluate("""async (u) => { const r = await fetch(u, {credentials: 'include'});
                                     return [r.status, await r.text()]; }""", url)
        return int(res[0]), res[1]

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
            self._pw.stop()

    # ── JSON APIs ───────────────────────────────────────────────────────────────
    def api(self, name: str, path: str, group: str, what: str) -> Any:
        url = API + path
        via, status, text = "https", 0, ""
        try:
            r = self.http.get(url, headers=self.api_headers)
            status, text = r.status_code, r.text
        except httpx.HTTPError as exc:
            text = str(exc)
        if status in (401, 403) or text.lstrip().startswith("<"):
            try:
                status, text = self.browser_get(url)
                via = "chrome"
            except Exception as exc:  # noqa: BLE001
                text = f"browser fetch failed: {exc}"
        payload: Any = None
        try:
            payload = json.loads(text)
        except ValueError:
            pass
        rows, fields = 0, []
        if isinstance(payload, list):
            rows = len(payload)
            fields = list(payload[0].keys()) if rows and isinstance(payload[0], dict) else []
        elif isinstance(payload, dict):
            lists = {k: v for k, v in payload.items() if isinstance(v, list)}
            key = max(lists, key=lambda k: len(lists[k])) if lists else None
            rows = len(lists[key]) if key else 1
            first = lists[key][0] if key and lists[key] else payload
            fields = list(first.keys()) if isinstance(first, dict) else list(payload.keys())
            if key:
                fields = [f"{key}[]: " + ", ".join(fields)]
            fields.append("top: " + ", ".join(payload.keys()))
        self.save(name, payload if payload is not None else text[:2000])
        self.record(name=name, kind="api", group=group, what=what, url=url, status=status, rows=rows,
                    fields=fields, via=via, error=None if payload is not None else text[:120])
        return payload

    # ── archive files ───────────────────────────────────────────────────────────
    def file(self, name: str, url: str, group: str, what: str) -> pd.DataFrame | None:
        try:
            r = self.http.get(url)
            status, blob = r.status_code, r.content
        except httpx.HTTPError as exc:
            self.record(name=name, kind="file", group=group, what=what, url=url, status=0, error=str(exc))
            return None
        df = None
        err = None
        if status == 200:
            try:
                df = parse_blob(url, blob)
            except Exception as exc:  # noqa: BLE001
                err = f"parse: {exc}"
        rows = int(len(df)) if df is not None else 0
        fields = [str(c).strip() for c in df.columns] if df is not None else []
        if df is not None:
            self.save(name, df.head(15).to_dict("records"))
        self.record(name=name, kind="file", group=group, what=what, url=url, status=status, rows=rows,
                    fields=fields, bytes=len(blob) if status == 200 else 0, error=err)
        return df


def parse_blob(url: str, blob: bytes) -> pd.DataFrame:
    low = url.lower()
    if blob[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(blob))
        names = [n for n in z.namelist() if n.lower().endswith((".csv", ".txt", ".dat"))] or z.namelist()
        return parse_blob(names[0], z.read(names[0]))
    if blob[:2] == b"\x1f\x8b":
        return parse_blob(low.removesuffix(".gz"), gzip.decompress(blob))
    if low.endswith((".xls", ".xlsx")):
        return pd.read_excel(io.BytesIO(blob))
    text = blob.decode("utf-8", errors="replace")
    if low.endswith(".dat") and "mto_" in low:          # delivery positions: 4 header lines
        return pd.read_csv(io.StringIO(text), skiprows=4, header=None,
                           names=["record", "sr", "symbol", "series", "traded_qty", "deliverable_qty", "deliv_pct"])
    if "fao_participant" in low:
        return pd.read_csv(io.StringIO(text), skiprows=1)
    return pd.read_csv(io.StringIO(text), sep=None, engine="python", on_bad_lines="skip")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="INFY")
    ap.add_argument("--date", default=None, help="trading day for daily files (default: previous weekday)")
    args = ap.parse_args()
    sym = args.symbol.upper()
    d = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    dd, ddmm, y4 = d.strftime("%d%m%Y"), d.strftime("%d%m%y"), d.strftime("%Y%m%d")
    frm = (d - timedelta(days=30)).strftime("%d-%m-%Y")
    to = d.strftime("%d-%m-%Y")
    p = Probe()
    print(f"NSE free-data probe · symbol {sym} · daily files for {d}\n")

    A = "https://nsearchives.nseindia.com"
    # ── daily files: equities (cash market) ─────────────────────────────────────
    files = [
        ("cm_bhavcopy_full_delivery", f"{A}/products/content/sec_bhavdata_full_{dd}.csv", "equity-eod", "OHLC, VWAP, volume, trades, delivery qty & %"),
        ("cm_udiff_bhavcopy", f"{A}/content/cm/BhavCopy_NSE_CM_0_0_0_{y4}_F_0000.csv.zip", "equity-eod", "Standard UDiFF bhavcopy (ISIN, prev close, settlement)"),
        ("cm_delivery_mto", f"{A}/archives/equities/mto/MTO_{dd}.DAT", "equity-eod", "Security-wise delivery positions"),
        ("cm_bulk_deals", f"{A}/content/equities/bulk.csv", "equity-deals", "Bulk deals (≥0.5% of equity) by named client"),
        ("cm_block_deals", f"{A}/content/equities/block.csv", "equity-deals", "Block-window deals by named client"),
        ("cm_short_selling", f"{A}/archives/equities/shortSelling/shortselling_{dd}.csv", "equity-deals", "Institutional short sales per stock"),
        ("cm_margin_trading", f"{A}/content/equities/mrg_trading_{(d - timedelta(days=1)).strftime('%d%m%y')}.zip", "equity-positions", "Margin trading (MTF) funded positions per stock"),
        ("cm_52wk_high_low", f"{A}/content/CM_52_wk_High_low_{dd}.csv", "equity-eod", "52-week high/low and dates per stock"),
        ("cm_pe_ratio", f"{A}/content/equities/peDetail/PE_{ddmm}.csv", "equity-eod", "Stock P/E ratios (symbol-level)"),
        ("cm_daily_volatility", f"{A}/archives/nsccl/volt/CMVOLT_{dd}.CSV", "equity-risk", "Daily & annualised volatility per stock"),
        ("cm_price_band_changes", f"{A}/content/equities/eq_band_changes_{dd}.csv", "equity-risk", "Circuit band changes effective next day"),
        ("cm_price_band_list", f"{A}/content/equities/sec_list_{dd}.csv", "equity-risk", "Current circuit band per stock"),
        ("cm_surveillance_indicator", f"{A}/content/cm/REG1_IND{ddmm}.csv", "equity-risk", "Surveillance flags per stock (ASM/GSM/ESM etc.)"),
        ("cm_security_master", f"{A}/content/cm/NSE_CM_security_{dd}.csv.gz", "reference", "All listed securities: ISIN, series, lot, band, face value"),
        ("cm_market_activity", f"{A}/archives/equities/mkt/MA{ddmm}.csv", "market", "Market activity summary: turnover, breadth, top traded"),
        ("cm_series_change", f"{A}/content/equities/series_change.csv", "reference", "Stocks moved between series (EQ/BE/BZ…)"),
        ("idx_daily_snapshot", f"{A}/content/indices/ind_close_all_{dd}.csv", "index", "Every index: OHLC, change, P/E, P/B, dividend yield"),
        ("idx_nifty50_top10", f"{A}/content/indices/top10nifty50_{ddmm}.csv", "index", "NIFTY 50 top-10 weights"),
        # ── daily files: derivatives ─────────────────────────────────────────────
        ("fo_udiff_bhavcopy", f"{A}/content/fo/BhavCopy_NSE_FO_0_0_0_{y4}_F_0000.csv.zip", "fo-eod", "Every contract: OHLC, settle, volume, OI, change in OI"),
        ("fo_participant_oi", f"{A}/content/nsccl/fao_participant_oi_{dd}.csv", "fo-positions", "Long/short OI by Client, DII, FII, Pro"),
        ("fo_participant_volume", f"{A}/content/nsccl/fao_participant_vol_{dd}.csv", "fo-positions", "Traded volume by participant type"),
        ("fo_combined_oi", f"{A}/archives/nsccl/mwpl/combineoi_{dd}.zip", "fo-positions", "Combined OI across exchanges vs market-wide limit (MWPL)"),
        ("fo_combined_delta_oi", f"{A}/archives/nsccl/mwpl/combineoi_deleq_{dd}.csv", "fo-positions", "Delta-equivalent OI per underlying"),
        ("fo_clients_3pct_mwpl", f"{A}/content/nsccl/mwpl_cli_{(d - timedelta(days=1 if d.weekday() else 3)).strftime('%d%m%Y')}.xls", "fo-positions", "Clients holding ≥3% of a stock's MWPL"),
        ("fo_ban_list", f"{A}/archives/fo/sec_ban/fo_secban_{(d + timedelta(days=1 if d.weekday() < 4 else 3)).strftime('%d%m%Y')}.csv", "fo-risk", "Stocks in F&O ban (OI > 95% of MWPL)"),
        ("fo_fii_stats", f"{A}/content/fo/fii_stats_{d.strftime('%d-%b-%Y')}.xls", "fo-positions", "FII buy/sell and OI in index & stock F&O"),
        ("fo_category_turnover", f"{A}/archives/fo/cat/fo_cat_turnover_{ddmm}.xls", "fo-positions", "F&O turnover by client category"),
        ("fo_contract_delta", f"{A}/content/nsccl/Contract_Delta_{dd}.csv", "fo-positions", "NCL delta per option contract"),
        ("idx_nifty50_constituents", "https://niftyindices.com/IndexConstituent/ind_nifty50list.csv", "index", "NIFTY 50 members with industry and ISIN (niftyindices.com)"),
        ("fo_top10_clearing_members", f"{A}/content/nsccl/fao_top10cm_to_{dd}.csv", "fo-positions", "Top-10 clearing members' share of volume"),
        ("fo_daily_volatility", f"{A}/archives/nsccl/volt/FOVOLT_{dd}.csv", "fo-risk", "Underlying & futures volatility used for margins"),
        ("fo_settlement_prices", f"{A}/archives/nsccl/sett/FOSett_prce_{dd}.csv", "fo-eod", "Daily settlement price per future"),
        ("fo_lot_sizes", f"{A}/content/fo/fo_mktlots.csv", "reference", "F&O lot sizes by expiry"),
    ]
    for name, url, group, what in files:
        p.file(name, url, group, what)

    # ── JSON APIs: market-wide ──────────────────────────────────────────────────
    apis = [
        ("api_fii_dii_cash", "/api/fiidiiTradeReact", "flows", "FII & DII buy/sell in the cash market (provisional, same day)"),
        ("api_large_deals_today", "/api/snapshot-capital-market-largedeal", "equity-deals", "Today's bulk, block and short deals"),
        ("api_bulk_deals_hist", f"/api/historicalOR/bulk-block-short-deals?optionType=bulk_deals&from={frm}&to={to}", "equity-deals", "Bulk deals history (date range)"),
        ("api_block_deals_hist", f"/api/historicalOR/bulk-block-short-deals?optionType=block_deals&from={frm}&to={to}", "equity-deals", "Block deals history"),
        ("api_short_selling_hist", f"/api/historicalOR/bulk-block-short-deals?optionType=short_selling&from={frm}&to={to}", "equity-deals", "Short-selling history"),
        ("api_pre_open", "/api/market-data-pre-open?key=ALL", "intraday", "Pre-open (09:00–09:08): indicative price, buy/sell qty per stock"),
        ("api_oi_spurts_underlyings", "/api/live-analysis-oi-spurts-underlyings", "fo-positions", "Underlyings with biggest OI change vs price"),
        ("api_oi_spurts_contracts", "/api/live-analysis-oi-spurts-contracts", "fo-positions", "Contracts with biggest OI change"),
        ("api_gainers", "/api/live-analysis-variations?index=gainers", "intraday", "Top gainers by index"),
        ("api_most_active_value", "/api/live-analysis-most-active-securities?index=value", "intraday", "Most active stocks by value"),
        ("api_52wk_high_live", "/api/live-analysis-data-52weekhighstock", "intraday", "Stocks at a new 52-week high today"),
        ("api_price_band_hitters", "/api/live-analysis-price-band-hitter", "intraday", "Stocks at upper/lower circuit"),
        ("api_asm_list", "/api/reportASM", "equity-risk", "Additional Surveillance Measure list (long/short term)"),
        ("api_gsm_list", "/api/reportGSM", "equity-risk", "Graded Surveillance Measure list"),
        ("api_all_indices", "/api/allIndices", "index", "All indices: level, change, P/E, P/B, DY, breadth"),
        ("api_announcements_all", "/api/corporate-announcements?index=equities", "filings", "Latest company filings market-wide (news feed)"),
        ("api_insider_trades_all", f"/api/corporates-pit?index=equities&from_date={frm}&to_date={to}", "filings", "Insider / promoter trades market-wide (SEBI PIT)"),
        ("api_sast_all", "/api/corporate-sast-reg29?index=equities", "filings", "Substantial acquisition disclosures (SAST Reg 29)"),
        ("api_pledge_all", "/api/corporate-pledgedata?index=equities", "filings", "Promoter pledge (encumbrance) data"),
        ("api_event_calendar", "/api/event-calendar?index=equities", "filings", "Upcoming board meetings, results, AGMs"),
        ("api_corporate_actions_all", "/api/corporates-corporateActions?index=equities", "filings", "Dividends, bonus, splits, record dates"),
        ("api_ipo_current", "/api/ipo-current-issue", "ipo", "Open IPOs with subscription"),
        ("api_holidays", "/api/holiday-master?type=trading", "reference", "Trading holidays by segment"),
        ("api_market_status", "/api/marketStatus", "reference", "Market open/closed state"),
        ("api_option_chain_expiries", "/api/option-chain-contract-info?symbol=NIFTY", "fo-positions", "Option-chain expiry list (feeds the v3 chain call)"),
        ("api_most_active_stock_futures", "/api/liveEquity-derivatives?index=stock_fut", "fo-positions", "Most active stock futures"),
    ]
    # ── JSON APIs: per stock ────────────────────────────────────────────────────
    apis += [
        (f"api_quote_{sym}", f"/api/quote-equity?symbol={sym}", "stock", "Quote, price bands, industry, index membership"),
        (f"api_trade_info_{sym}", f"/api/quote-equity?symbol={sym}&section=trade_info", "stock", "Delivery %, order book, market cap, VaR"),
        (f"api_quote_derivative_{sym}", f"/api/quote-derivative?symbol={sym}", "stock", "All F&O contracts with OI and IV"),
        (f"api_history_pvd_{sym}", f"/api/historicalOR/generateSecurityWiseHistoricalData?from={frm}&to={to}&symbol={sym}&type=priceVolumeDeliverable&series=ALL", "stock", "Daily price, volume & delivery history"),
        (f"api_announcements_{sym}", f"/api/corporate-announcements?index=equities&symbol={sym}", "stock", "Company filings with PDF links"),
        (f"api_shareholding_{sym}", f"/api/corporate-share-holdings-master?index=equities&symbol={sym}", "stock", "Quarterly shareholding pattern (promoter/public %, XBRL link)"),
        (f"api_insider_{sym}", f"/api/corporates-pit?index=equities&symbol={sym}", "stock", "Insider trades in this stock"),
        (f"api_corp_actions_{sym}", f"/api/corporates-corporateActions?index=equities&symbol={sym}", "stock", "Corporate actions history"),
        (f"api_board_meetings_{sym}", f"/api/corporate-board-meetings?index=equities&symbol={sym}", "stock", "Board meetings (results dates)"),
        (f"api_financial_results_{sym}", f"/api/corporates-financial-results?index=equities&symbol={sym}&period=Quarterly", "stock", "Quarterly results filings (XBRL links)"),
        (f"api_annual_reports_{sym}", f"/api/annual-reports?index=equities&symbol={sym}", "stock", "Annual reports"),
        (f"api_option_chain_{sym}", f"/api/option-chain-equities?symbol={sym}", "stock", "Stock option chain"),
    ]
    for name, path, group, what in apis:
        payload = p.api(name, path, group, what)
        if name == "api_option_chain_expiries" and isinstance(payload, dict) and payload.get("expiryDates"):
            exp = payload["expiryDates"][0]
            p.api("api_option_chain_v3_nifty", f"/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry={exp}",
                  "fo-positions", "NIFTY option chain for one expiry: OI, change in OI, IV, bid/ask per strike")
    p.close()
    (OUT / "summary.json").write_text(json.dumps({"generated": datetime.now().isoformat(timespec="seconds"),
                                                  "symbol": sym, "trading_day": str(d), "probes": p.results},
                                                 indent=1, default=str))
    ok = sum(1 for r in p.results if r.get("status") == 200 and r.get("rows"))
    print(f"\n{ok}/{len(p.results)} sources returned data · wrote {OUT.relative_to(ROOT)}/summary.json")


if __name__ == "__main__":
    main()
