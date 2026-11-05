"""G-EDU verification pass 2: GOLD-specific COT rows + history, GLD CSV, Yahoo retry, cadence/terms text, app numbers.
Read-only; local calls are GET only on endpoints that never touch the broker (mcx/overlay, mcx/specs)."""
from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

OUT = Path(__file__).with_name("verify_pass2.json")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
res: dict = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def get(url: str, headers=UA, timeout=25) -> httpx.Response:
    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as c:
        return c.get(url)


def text_around(html: str, pat: str, width: int = 220, n: int = 4) -> list[str]:
    t = re.sub(r"\s+", " ", re.sub(r"<script.*?</script>|<style.*?</style>", " ", html, flags=re.S | re.I))
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t)
    out = []
    for m in re.finditer(pat, t, re.I):
        out.append(t[max(0, m.start() - width): m.end() + width])
        if len(out) >= n:
            break
    return out


# 1. CFTC disaggregated GOLD (main contract), futures-only + combined, latest 2 with changes
GOLD = "GOLD - COMMODITY EXCHANGE INC."
sel = ",".join(["report_date_as_yyyy_mm_dd", "open_interest_all", "prod_merc_positions_long", "prod_merc_positions_short",
                "swap_positions_long_all", "swap__positions_short_all", "swap__positions_spread_all",
                "m_money_positions_long_all", "m_money_positions_short_all", "m_money_positions_spread",
                "other_rept_positions_long", "other_rept_positions_short", "other_rept_positions_spread",
                "nonrept_positions_long_all", "nonrept_positions_short_all",
                "change_in_open_interest_all", "change_in_m_money_long_all", "change_in_m_money_short_all",
                "change_in_prod_merc_long", "change_in_prod_merc_short", "change_in_swap_long_all", "change_in_swap_short_all",
                "traders_m_money_long_all", "traders_m_money_short_all", "traders_tot_all",
                "conc_gross_le_4_tdr_long", "conc_gross_le_4_tdr_short"])
for key, ds in (("disagg_fut", "72hh-3qpy"), ("disagg_combined", "kh3c-gbw2")):
    url = (f"https://publicreporting.cftc.gov/resource/{ds}.json?$where=market_and_exchange_names='{GOLD}'"
           f"&$order=report_date_as_yyyy_mm_dd DESC&$limit=2&$select={sel}")
    try:
        r = get(url.replace(" ", "%20").replace("'", "%27"))
        res[key] = {"status": r.status_code, "rows": r.json() if r.status_code == 200 else r.text[:300]}
    except Exception as exc:  # noqa: BLE001
        res[key] = {"error": str(exc)[:200]}
    time.sleep(1.5)

# 1b. 60-week managed-money history (futures only) for a COT-index worked example
url = (f"https://publicreporting.cftc.gov/resource/72hh-3qpy.json?$where=market_and_exchange_names='{GOLD}'"
       f"&$order=report_date_as_yyyy_mm_dd DESC&$limit=160&$select=report_date_as_yyyy_mm_dd,open_interest_all,"
       f"m_money_positions_long_all,m_money_positions_short_all,prod_merc_positions_long,prod_merc_positions_short,"
       f"swap_positions_long_all,swap__positions_short_all")
try:
    r = get(url.replace(" ", "%20").replace("'", "%27"))
    rows = r.json() if r.status_code == 200 else []
    hist = []
    for d in rows:
        try:
            hist.append({"date": d["report_date_as_yyyy_mm_dd"][:10], "oi": int(d["open_interest_all"]),
                         "mm_long": int(d["m_money_positions_long_all"]), "mm_short": int(d["m_money_positions_short_all"]),
                         "pm_long": int(d["prod_merc_positions_long"]), "pm_short": int(d["prod_merc_positions_short"]),
                         "sd_long": int(d["swap_positions_long_all"]), "sd_short": int(d["swap__positions_short_all"])})
        except (KeyError, ValueError):
            continue
    hist.sort(key=lambda x: x["date"])
    for h in hist:
        h["mm_net"] = h["mm_long"] - h["mm_short"]
        h["comm_net"] = (h["pm_long"] + h["sd_long"]) - (h["pm_short"] + h["sd_short"])
    res["mm_history"] = {"status": r.status_code, "n": len(hist), "first": hist[0] if hist else None, "last": hist[-1] if hist else None}
    if hist:
        nets = [h["mm_net"] for h in hist]
        last = nets[-1]
        for N in (26, 52, 156):
            w = nets[-N:]
            lo, hi = min(w), max(w)
            res["mm_history"][f"cot_index_{N}w"] = round(100 * (last - lo) / (hi - lo), 1) if hi > lo else None
            res["mm_history"][f"min_{N}w"], res["mm_history"][f"max_{N}w"] = lo, hi
        res["mm_history"]["last_8"] = hist[-8:]
        Path(__file__).with_name("cot_gold_mm_history.csv").write_text(
            "date,oi,mm_long,mm_short,mm_net,pm_long,pm_short,sd_long,sd_short,comm_net\n" +
            "\n".join(f"{h['date']},{h['oi']},{h['mm_long']},{h['mm_short']},{h['mm_net']},{h['pm_long']},{h['pm_short']},{h['sd_long']},{h['sd_short']},{h['comm_net']}" for h in hist))
except Exception as exc:  # noqa: BLE001
    res["mm_history"] = {"error": str(exc)[:200]}
time.sleep(1.5)

# 2. CFTC legacy short-format page: the GOLD block as published
try:
    r = get("https://www.cftc.gov/dea/futures/deacmxsf.htm")
    t = re.sub(r"<[^>]+>", "", r.text)
    i = t.find("GOLD - COMMODITY EXCHANGE INC.")
    res["legacy_gold_block"] = {"status": r.status_code, "block": t[i:i + 1400] if i >= 0 else None}
except Exception as exc:  # noqa: BLE001
    res["legacy_gold_block"] = {"error": str(exc)[:200]}
time.sleep(1.5)

# 3. Release schedule: lines with 2026 dates
try:
    r = get("https://www.cftc.gov/MarketReports/CommitmentsofTraders/ReleaseSchedule/index.htm")
    res["release_schedule"] = {"status": r.status_code, "hits": text_around(r.text, r"(October|November|December) \d{1,2}, 2026", 90, 6)}
except Exception as exc:  # noqa: BLE001
    res["release_schedule"] = {"error": str(exc)[:200]}
time.sleep(1.5)

# 4. GLD archive CSV, tolerant parse
try:
    r = get("https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv")
    txt = r.text
    lines = [ln for ln in txt.splitlines() if ln.strip()]
    hdr_idx = next((i for i, ln in enumerate(lines) if "Date" in ln and "," in ln), None)
    sample = {"status": r.status_code, "bytes": len(r.content), "n_lines": len(lines), "head": lines[:8], "tail": lines[-3:]}
    if hdr_idx is not None:
        sample["header"] = lines[hdr_idx]
        sample["first_data"] = lines[hdr_idx + 1] if hdr_idx + 1 < len(lines) else None
    res["gld_csv"] = sample
except Exception as exc:  # noqa: BLE001
    res["gld_csv"] = {"error": str(exc)[:200]}
time.sleep(1.5)

# 5. cadence / terms text
pages = {
    "kitco_terms": ("https://www.kitco.com/terms-of-use", r"redistribut|commercial use|embed|scrap"),
    "lbma_trade_data": ("https://www.lbma.org.uk/prices-and-data/lbma-trade-data", r"weekly|published|T\+1|delay"),
    "lbma_vault": ("https://www.lbma.org.uk/prices-and-data/london-vault-holdings-data", r"monthly|lag|tonnes|published"),
    "lbma_prices": ("https://www.lbma.org.uk/prices-and-data/precious-metal-prices", r"ICE Benchmark|10:30|15:00|auction|licen"),
    "wgc_etf": ("https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows", r"monthly|weekly|daily|register|login|download"),
    "wgc_cb": ("https://www.gold.org/goldhub/data/gold-reserves-by-country", r"IMF|monthly|lag|updated"),
    "bank_participation": ("https://www.cftc.gov/MarketReports/BankParticipationReports/index.htm", r"monthly|first Tuesday|released"),
    "cot_explanatory": ("https://www.cftc.gov/MarketReports/CommitmentsofTraders/ExplanatoryNotes/index.htm", r"3:30 p\.m\.|Friday|Tuesday|20 or more|reporting level"),
    "disagg_explanatory": ("https://www.cftc.gov/MarketReports/CommitmentsofTraders/DisaggregatedExplanatoryNotes/index.htm", r"Producer/Merchant|Swap Dealer|Managed Money|Other Reportables"),
    "sge_delayed": ("https://en.sge.com.cn/data_DelayedQuotes", r"Au99\.99|Au\(T\+D\)|Au99\.95"),
    "sge_benchmark": ("https://en.sge.com.cn/data_BenchmarkPrice", r"SHAU|Benchmark|10:15|14:15"),
    "ibja": ("https://ibjarates.com/", r"999|995|Fine Gold|AM|PM"),
    "lbma_good_delivery": ("https://www.lbma.org.uk/good-delivery/about-good-delivery", r"350|430|995|fineness|kilobar"),
    "rbi_wss": ("https://www.rbi.org.in/Scripts/WSSView.aspx", r"Gold|Foreign Exchange Reserves"),
    "icici_ilearn_mcx": ("https://www.icicidirect.com/ilearn/commodity/articles/mcx-holiday-list", r"2026|holiday"),
}
for key, (url, pat) in pages.items():
    try:
        r = get(url)
        res[f"text_{key}"] = {"status": r.status_code, "hits": text_around(r.text, pat, 160, 5)}
    except Exception as exc:  # noqa: BLE001
        res[f"text_{key}"] = {"error": str(exc)[:200]}
    time.sleep(1.5)

# 6. Yahoo retry after a pause (429 in pass 1: this machine's app polls Yahoo)
time.sleep(20)
for sym in ("GC=F", "SI=F", "INR=X", "^GVZ", "GCZ26.CMX", "GCG27.CMX", "GCJ27.CMX", "GLD", "GOLDBEES.NS"):
    for host in ("query2", "query1"):
        try:
            r = get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1d")
            if r.status_code == 200:
                j = r.json()["chart"]["result"][0]
                meta = j.get("meta", {})
                ts = j.get("timestamp") or []
                res[f"yahoo_{sym}"] = {"status": 200, "host": host, "price": meta.get("regularMarketPrice"),
                                       "time": datetime.fromtimestamp(meta["regularMarketTime"], tz=timezone.utc).isoformat() if meta.get("regularMarketTime") else None,
                                       "prev_close": meta.get("previousClose") or meta.get("chartPreviousClose"),
                                       "exchange": meta.get("exchangeName"), "currency": meta.get("currency"),
                                       "last_bar": datetime.fromtimestamp(ts[-1], tz=timezone.utc).isoformat() if ts else None}
                break
            res[f"yahoo_{sym}"] = {"status": r.status_code, "host": host}
        except Exception as exc:  # noqa: BLE001
            res[f"yahoo_{sym}"] = {"error": str(exc)[:200]}
        time.sleep(3)
    time.sleep(2)

# 7. App numbers (GET only; these endpoints never call the broker)
for key, url in (("app_overlay", "http://127.0.0.1:8010/api/mcx/overlay?contract=GOLD"),
                 ("app_specs", "http://127.0.0.1:8010/api/mcx/specs")):
    try:
        r = get(url, headers={"User-Agent": "G-EDU-readonly"}, timeout=20)
        j = r.json()
        if key == "app_specs":
            j = {"as_of": j.get("as_of"), "master": j.get("master"),
                 "contracts": [{k: c.get(k) for k in ("code", "lot", "quotation", "tick_value", "purity", "front", "indicative_margin_rupees", "observed_expiries")} for c in j.get("contracts", [])]}
        res[key] = {"status": r.status_code, "body": j}
    except Exception as exc:  # noqa: BLE001
        res[key] = {"error": str(exc)[:200]}

OUT.write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: (v if k in ("mm_history", "disagg_fut", "app_overlay", "gld_csv") or k.startswith("yahoo") else "...") for k, v in res.items()}, indent=1, default=str)[:6000])
print("wrote", OUT)
