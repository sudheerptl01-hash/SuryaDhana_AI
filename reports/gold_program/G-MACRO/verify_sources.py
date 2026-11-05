"""
G-MACRO live source verification (read-only, public, rate-limited).

Every source the brief names is fetched ONCE with a GET, and we record: HTTP status, latency, the
real field names / a sample of rows, the latest date carried, and any parsing trap. Full daily
histories needed by the G-STUDY (gold, real yields, DXY, FX, VIX ...) are saved as CSV in ./data/.

Run:  /Users/sudheer/Desktop/jupyter_env/bin/python verify_sources.py
Out:  verification.json, data/*.csv, samples/*.txt
"""
from __future__ import annotations

import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

OUT = Path(__file__).resolve().parent
DATA = OUT / "data"
SAMPLES = OUT / "samples"
DATA.mkdir(exist_ok=True)
SAMPLES.mkdir(exist_ok=True)

SLEEP = 1.5
BROWSER_UA = {"User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
              "Accept-Language": "en-US,en;q=0.9"}
RESULTS: list[dict] = []


def rec(name: str, url: str, **kw) -> dict:
    row = {"name": name, "url": url, "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **kw}
    RESULTS.append(row)
    status = row.get("status")
    print(f"[{status}] {name}  {row.get('latency_ms')} ms  latest={row.get('latest_date')}  {row.get('note', '')[:120]}", flush=True)
    return row


def get(url: str, headers: dict | None = None, params: dict | None = None, timeout: float = 40.0,
        follow: bool = True) -> tuple[httpx.Response | None, float, str]:
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0), headers=headers or {}, follow_redirects=follow) as c:
            r = c.get(url, params=params)
        return r, round((time.perf_counter() - t0) * 1000), ""
    except Exception as exc:  # noqa: BLE001
        return None, round((time.perf_counter() - t0) * 1000), f"{type(exc).__name__}: {str(exc)[:160]}"
    finally:
        time.sleep(SLEEP)


def save_sample(name: str, text: str, n: int = 1500) -> None:
    (SAMPLES / f"{name}.txt").write_text(text[:n], encoding="utf-8", errors="replace")


# ── 1. FRED fredgraph.csv (no key) ─────────────────────────────────────────────
# NOTE (from gold_preopen.py): FRED stalls browser-UA requests; a plain client is fast.
FRED_SERIES = {
    # real yields
    "DFII10": "10y TIPS real yield", "DFII5": "5y TIPS real yield", "DFII30": "30y TIPS real yield",
    "DFII7": "7y TIPS real yield", "DFII20": "20y TIPS real yield",
    # breakevens / inflation expectations
    "T10YIE": "10y breakeven inflation", "T5YIE": "5y breakeven", "T5YIFR": "5y5y forward inflation expectation",
    "EXPINF10YR": "Cleveland Fed 10y expected inflation (monthly)", "EXPINF1YR": "Cleveland Fed 1y expected inflation",
    "MICH": "Michigan 1y inflation expectation (monthly)",
    # nominal yields
    "DGS2": "2y Treasury", "DGS10": "10y Treasury", "DGS30": "30y Treasury", "DGS3MO": "3m bill", "T10Y2Y": "10y-2y slope",
    # policy rate
    "DFF": "Effective fed funds (daily)", "EFFR": "EFFR (NY Fed via FRED)", "FEDFUNDS": "Fed funds monthly avg",
    "DFEDTARU": "Fed target range upper", "DFEDTARL": "Fed target range lower", "SOFR": "SOFR",
    # dollar
    "DTWEXBGS": "Broad USD index (goods+services)", "DTWEXAFEGS": "USD vs advanced economies",
    "DEXINUS": "USD/INR (H.10 noon)", "DEXUSEU": "EUR/USD (H.10)", "DEXJPUS": "USD/JPY (H.10)", "DEXCHUS": "USD/CNY (H.10)",
    # volatility
    "VIXCLS": "VIX close", "GVZCLS": "CBOE gold ETF vol index (GVZ)", "OVXCLS": "CBOE oil vol index",
    # oil
    "DCOILWTICO": "WTI spot", "DCOILBRENTEU": "Brent spot",
    # money / liquidity
    "M2SL": "US M2 (monthly, SA)", "WM2NS": "US M2 weekly (NSA)", "WALCL": "Fed total assets (weekly)",
    "RRPONTSYD": "Reverse repo (daily)", "WTREGEN": "Treasury General Account (weekly)", "BOGMBASE": "Monetary base",
    # macro prints
    "CPIAUCSL": "CPI all items SA", "CPILFESL": "Core CPI", "PCEPI": "PCE price index", "PCEPILFE": "Core PCE",
    "PAYEMS": "Nonfarm payrolls", "UNRATE": "Unemployment rate",
    # risk appetite
    "BAMLH0A0HYM2": "HY OAS",
    # gold on FRED (LBMA licence: check whether still served)
    "GOLDAMGBD228NLBM": "LBMA gold AM (USD)", "GOLDPMGBD228NLBM": "LBMA gold PM (USD)",
    # foreign M2 (for gold vs global liquidity)
    "MYAGM2EZM196N": "Euro area M2", "MANMM101CNM189S": "China M2 (OECD MEI)", "MYAGM2JPM189N": "Japan M2",
}
FULL_HISTORY = {"DFII10", "DFII5", "DFII30", "T10YIE", "DGS10", "DGS2", "DTWEXBGS", "VIXCLS", "GVZCLS", "DFF",
                "DCOILWTICO", "M2SL", "WALCL", "GOLDAMGBD228NLBM", "GOLDPMGBD228NLBM", "DEXINUS", "DEXUSEU",
                "DEXJPUS", "DEXCHUS", "BAMLH0A0HYM2", "T5YIFR", "RRPONTSYD", "WTREGEN"}


def verify_fred() -> None:
    for sid, label in FRED_SERIES.items():
        params = {"id": sid}
        if sid not in FULL_HISTORY:
            params["cosd"] = "2026-08-01"
        r, ms, err = get("https://fred.stlouisfed.org/graph/fredgraph.csv", params=params)
        if r is None:
            rec(f"FRED {sid}", f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", publisher="FRED (St. Louis Fed)",
                status="ERR", latency_ms=ms, note=err, label=label)
            continue
        txt = r.text
        rows = []
        for line in txt.strip().splitlines()[1:]:
            d, _, v = line.partition(",")
            try:
                rows.append((d, float(v)))
            except ValueError:
                continue
        header = txt.splitlines()[0] if txt else ""
        latest = rows[-1] if rows else None
        note = ""
        if r.status_code != 200 or not rows:
            note = f"HTTP {r.status_code}; body starts: {txt[:120]!r}"
        if sid in FULL_HISTORY and rows:
            pd.DataFrame(rows, columns=["date", sid]).to_csv(DATA / f"fred_{sid}.csv", index=False)
        save_sample(f"fred_{sid}", txt[:400] + "\n...\n" + txt[-400:])
        rec(f"FRED {sid}", f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", publisher="FRED (St. Louis Fed)",
            label=label, status=r.status_code, latency_ms=ms, header=header, n_rows=len(rows),
            first_date=rows[0][0] if rows else None, latest_date=latest[0] if latest else None,
            latest_value=latest[1] if latest else None, note=note)


def verify_fred_api_gate() -> None:
    r, ms, err = get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": "DFII10", "file_type": "json", "limit": "3", "sort_order": "desc"})
    rec("FRED REST API without key (gate check)", "https://api.stlouisfed.org/fred/series/observations?series_id=DFII10",
        publisher="FRED", status=r.status_code if r else "ERR", latency_ms=ms,
        note=(r.text[:200] if r else err))
    # ALFRED vintage endpoint (also key-gated) — same gate
    r, ms, err = get("https://api.stlouisfed.org/fred/series/observations",
                     params={"series_id": "CPIAUCSL", "file_type": "json", "realtime_start": "2024-01-01", "limit": "3"})
    rec("ALFRED vintages without key (gate check)", "https://api.stlouisfed.org/fred/series/observations?realtime_start=...",
        publisher="FRED/ALFRED", status=r.status_code if r else "ERR", latency_ms=ms, note=(r.text[:200] if r else err))


# ── 2. US Treasury daily yield curves (public domain) ──────────────────────────
def verify_treasury() -> None:
    base = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all"
    for kind, typ in (("real", "daily_treasury_real_yield_curve"), ("nominal", "daily_treasury_yield_curve")):
        url = f"{base}?type={typ}&field_tdr_date_value=2026"
        r, ms, err = get(url, headers=BROWSER_UA, timeout=90)
        if r is None:
            rec(f"US Treasury daily {kind} yield curve CSV", url, publisher="US Treasury", status="ERR", latency_ms=ms, note=err)
            continue
        try:
            df = pd.read_csv(io.StringIO(r.text))
            df["Date"] = pd.to_datetime(df["Date"], format="%m/%d/%Y")
            df = df.sort_values("Date")
            df.to_csv(DATA / f"treasury_{kind}_2026.csv", index=False)
            latest = df.iloc[-1]
            rec(f"US Treasury daily {kind} yield curve CSV", url, publisher="US Treasury", status=r.status_code, latency_ms=ms,
                header=",".join(df.columns), n_rows=len(df), latest_date=str(latest["Date"].date()),
                latest_row={k: (None if pd.isna(v) else float(v)) for k, v in latest.drop("Date").items()},
                note="one file per calendar year; columns differ between real (5/7/10/20/30 YR) and nominal curves")
        except Exception as exc:  # noqa: BLE001
            save_sample(f"treasury_{kind}", r.text)
            rec(f"US Treasury daily {kind} yield curve CSV", url, publisher="US Treasury", status=r.status_code, latency_ms=ms,
                note=f"parse failed: {exc}; body starts {r.text[:120]!r}")


# ── 3. Yahoo Finance v8 chart (no key; unofficial) ─────────────────────────────
YAHOO = {
    "DX-Y.NYB": "ICE US Dollar Index", "GC=F": "COMEX gold front future", "SI=F": "COMEX silver", "PL=F": "NYMEX platinum",
    "PA=F": "NYMEX palladium", "^TNX": "US 10y yield (CBOE index, x10)", "^FVX": "US 5y yield", "^TYX": "US 30y yield",
    "^IRX": "US 13-week bill", "^VIX": "VIX", "^GVZ": "CBOE gold vol index", "^OVX": "CBOE oil vol index",
    "INR=X": "USD/INR", "EURUSD=X": "EUR/USD", "JPY=X": "USD/JPY", "CNY=X": "USD/CNY", "GBPUSD=X": "GBP/USD",
    "CAD=X": "USD/CAD", "CHF=X": "USD/CHF", "SEK=X": "USD/SEK", "AUD=X": "USD/AUD?", "AUDUSD=X": "AUD/USD",
    "CL=F": "WTI", "BZ=F": "Brent", "GLD": "SPDR Gold Shares", "IAU": "iShares Gold Trust",
    "ZQ=F": "30-day fed funds future (front)", "ZQZ26.CBT": "Fed funds Dec-2026", "ZQH27.CBT": "Fed funds Mar-2027",
    "SR3Z26.CME": "3m SOFR future Dec-2026", "ZT=F": "2y T-note future", "ZN=F": "10y T-note future",
    "TIP": "iShares TIPS ETF", "IEF": "iShares 7-10y Treasury ETF",
    "XAUUSD=X": "spot gold? (test)", "GOLDBEES.NS": "Nippon India Gold BeES (NSE)", "GOLDIETF.NS": "ICICI Pru Gold ETF (NSE)",
    "^NSEI": "NIFTY 50 (control)",
}
YAHOO_FULL = {"GC=F", "SI=F", "PL=F", "DX-Y.NYB", "^VIX", "^GVZ", "INR=X", "EURUSD=X", "JPY=X", "CNY=X", "GBPUSD=X",
              "CAD=X", "CHF=X", "SEK=X", "AUDUSD=X", "^TNX", "CL=F", "GLD", "GOLDBEES.NS", "TIP", "IEF", "ZQ=F"}


def verify_yahoo() -> None:
    for sym, label in YAHOO.items():
        full = sym in YAHOO_FULL
        params = {"range": "max" if full else "5d", "interval": "1d" if full else "5m", "includePrePost": "false"}
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        r, ms, err = get(url, headers=BROWSER_UA, params=params)
        if r is None:
            rec(f"Yahoo {sym}", url, publisher="Yahoo Finance (unofficial chart API)", label=label, status="ERR", latency_ms=ms, note=err)
            continue
        try:
            j = r.json()
            res = (j.get("chart") or {}).get("result")
            if not res:
                rec(f"Yahoo {sym}", url, publisher="Yahoo Finance", label=label, status=r.status_code, latency_ms=ms,
                    note=f"no result: {json.dumps((j.get('chart') or {}).get('error'))[:200]}")
                continue
            res = res[0]
            meta = res.get("meta", {})
            ts = res.get("timestamp") or []
            q = (res.get("indicators", {}).get("quote") or [{}])[0]
            closes = q.get("close") or []
            df = pd.DataFrame({"ts": ts, "open": q.get("open"), "high": q.get("high"), "low": q.get("low"), "close": closes,
                               "volume": q.get("volume")})
            df = df[df["close"].notna()]
            df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            if full:
                df["date"] = df["date"].dt.tz_convert(meta.get("exchangeTimezoneName") or "UTC").dt.date
                df[["date", "open", "high", "low", "close", "volume"]].to_csv(DATA / f"yahoo_{sym.replace('=', '_').replace('^', '_').replace('.', '_')}.csv", index=False)
            latest_ts = meta.get("regularMarketTime")
            rec(f"Yahoo {sym}", url, publisher="Yahoo Finance (unofficial chart API)", label=label, status=r.status_code, latency_ms=ms,
                n_rows=int(len(df)), first_date=str(df["date"].iloc[0]) if len(df) else None,
                latest_date=str(df["date"].iloc[-1]) if len(df) else None,
                latest_value=meta.get("regularMarketPrice"), regular_market_time=datetime.fromtimestamp(latest_ts, tz=timezone.utc).isoformat() if latest_ts else None,
                meta_keys=sorted(k for k in meta.keys())[:30], currency=meta.get("currency"), exchange=meta.get("exchangeName"),
                note=f"range={params['range']} interval={params['interval']}; fields: timestamp, indicators.quote[0].{{open,high,low,close,volume}}, meta.regularMarketPrice/previousClose/chartPreviousClose")
        except Exception as exc:  # noqa: BLE001
            save_sample(f"yahoo_{sym}", r.text)
            rec(f"Yahoo {sym}", url, publisher="Yahoo Finance", label=label, status=r.status_code, latency_ms=ms, note=f"parse failed: {exc}; body {r.text[:120]!r}")


# ── 4. Release calendars: BLS, BEA, Fed, ForexFactory ──────────────────────────
def verify_calendars() -> None:
    for name, url in (("BLS CPI release schedule page", "https://www.bls.gov/schedule/news_release/cpi.htm"),
                      ("BLS Employment Situation (NFP) schedule page", "https://www.bls.gov/schedule/news_release/empsit.htm"),
                      ("BLS schedule home", "https://www.bls.gov/schedule/")):
        r, ms, err = get(url, headers=BROWSER_UA)
        if r is None:
            rec(name, url, publisher="US BLS", status="ERR", latency_ms=ms, note=err)
            continue
        import re
        dates = re.findall(r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d\d", r.text)
        save_sample(name.replace(" ", "_"), r.text)
        rec(name, url, publisher="US BLS", status=r.status_code, latency_ms=ms, n_rows=len(dates),
            sample_rows=dates[:6], latest_date=dates[-1] if dates else None,
            note="HTML page; dates parsed with a regex; BLS blocks bare clients (needs a browser-like UA)")
    # BLS public API v1 (no key, 25 req/day, 10 years max)
    url = "https://api.bls.gov/publicAPI/v1/timeseries/data/CUUR0000SA0"
    r, ms, err = get(url, headers=BROWSER_UA)
    if r is not None:
        try:
            j = r.json()
            series = (j.get("Results") or {}).get("series") or []
            rows = (series[0].get("data") if series else []) or []
            rec("BLS public API v1 (no key) CPI-U NSA CUUR0000SA0", url, publisher="US BLS", status=r.status_code, latency_ms=ms,
                n_rows=len(rows), sample_rows=rows[:3], latest_date=f"{rows[0]['year']}-{rows[0]['period']}" if rows else None,
                note=f"status={j.get('status')} message={j.get('message')}")
        except Exception as exc:  # noqa: BLE001
            rec("BLS public API v1 (no key) CPI", url, publisher="US BLS", status=r.status_code, latency_ms=ms, note=f"parse: {exc}; {r.text[:150]!r}")
    else:
        rec("BLS public API v1 (no key) CPI", url, publisher="US BLS", status="ERR", latency_ms=ms, note=err)
    # BEA release schedule
    url = "https://www.bea.gov/news/schedule"
    r, ms, err = get(url, headers=BROWSER_UA)
    if r is not None:
        import re
        hits = re.findall(r"Personal Income and Outlays[^<]{0,80}", r.text)
        save_sample("bea_schedule", r.text)
        rec("BEA release schedule page (PCE = Personal Income and Outlays)", url, publisher="US BEA", status=r.status_code, latency_ms=ms,
            n_rows=len(hits), sample_rows=hits[:4], note="HTML; BEA API (apps.bea.gov/api) needs a free UserID key")
    else:
        rec("BEA release schedule page", url, publisher="US BEA", status="ERR", latency_ms=ms, note=err)
    # Fed FOMC calendar (already in the app: markets.py parse_fomc)
    url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
    r, ms, err = get(url, headers=BROWSER_UA)
    if r is not None:
        import re
        n = len(re.findall(r"fomc-meeting__date", r.text))
        rec("Fed FOMC calendar page (already parsed by markets.py)", url, publisher="Federal Reserve Board", status=r.status_code, latency_ms=ms,
            n_rows=n, note="HTML; app already parses; '*' marks SEP meetings")
    else:
        rec("Fed FOMC calendar page", url, publisher="Federal Reserve Board", status="ERR", latency_ms=ms, note=err)
    # ForexFactory weekly calendar JSON (consensus / actual / previous)
    for name, url in (("ForexFactory calendar this week (JSON)", "https://nfs.faireconomy.media/ff_calendar_thisweek.json"),
                      ("ForexFactory calendar next week (JSON)", "https://nfs.faireconomy.media/ff_calendar_nextweek.json")):
        r, ms, err = get(url, headers=BROWSER_UA)
        if r is None:
            rec(name, url, publisher="Forex Factory (Fair Economy)", status="ERR", latency_ms=ms, note=err)
            continue
        try:
            j = r.json()
            usd = [e for e in j if e.get("country") == "USD"]
            hi = [e for e in usd if e.get("impact") == "High"]
            save_sample(name.replace(" ", "_"), json.dumps(j[:5], indent=1))
            rec(name, url, publisher="Forex Factory (Fair Economy)", status=r.status_code, latency_ms=ms, n_rows=len(j),
                header=",".join(sorted(j[0].keys())) if j else "", sample_rows=hi[:6],
                latest_date=max((e.get("date") or "")[:10] for e in j) if j else None,
                note="fields: title,country,date(ISO with -04:00 offset),impact,forecast,previous,actual(?); terms: personal use, cache, no hammering")
        except Exception as exc:  # noqa: BLE001
            save_sample(name.replace(" ", "_"), r.text)
            rec(name, url, publisher="Forex Factory", status=r.status_code, latency_ms=ms, note=f"parse: {exc}; {r.text[:150]!r}")


# ── 5. Fed policy expectations: CME FedWatch (web only), fed funds futures ─────
def verify_fed_expectations() -> None:
    url = "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("CME FedWatch tool page", url, publisher="CME Group", status=r.status_code if r else "ERR", latency_ms=ms,
        note=(f"HTML {len(r.text)} chars; the probabilities are rendered client-side from CME's internal API (no documented free API); "
              f"CME terms forbid scraping/redistribution" if r else err))
    url = "https://www.cmegroup.com/CmeWS/mvc/Quotes/Future/305/G"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("CME internal quotes endpoint (fed funds, undocumented)", url, publisher="CME Group", status=r.status_code if r else "ERR",
        latency_ms=ms, note=(r.text[:160].replace("\n", " ") if r else err))
    url = "https://www.atlantafed.org/cenfis/market-probability-tracker"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("Atlanta Fed Market Probability Tracker page", url, publisher="Atlanta Fed", status=r.status_code if r else "ERR", latency_ms=ms,
        note=(f"HTML {len(r.text)} chars; chart data loaded client-side; look for a download link" if r else err))


# ── 6. Geopolitical Risk index (Caldara-Iacoviello) ────────────────────────────
def verify_gpr() -> None:
    for name, url in (("GPR monthly index (xls)", "https://www.matteoiacoviello.com/gpr_files/data_gpr_export.xls"),
                      ("GPR daily recent (xls)", "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls")):
        r, ms, err = get(url, headers=BROWSER_UA, timeout=60)
        if r is None:
            rec(name, url, publisher="Caldara & Iacoviello (matteoiacoviello.com)", status="ERR", latency_ms=ms, note=err)
            continue
        try:
            df = pd.read_excel(io.BytesIO(r.content))
            tag = "monthly" if "monthly" in name else "daily"
            df.to_csv(DATA / f"gpr_{tag}.csv", index=False)
            dcol = next((c for c in df.columns if str(c).lower() in ("month", "date", "day")), df.columns[0])
            rec(name, url, publisher="Caldara & Iacoviello", status=r.status_code, latency_ms=ms, n_rows=len(df),
                header=",".join(map(str, df.columns))[:300], latest_date=str(df[dcol].iloc[-1])[:10],
                sample_rows=df.tail(2).astype(str).to_dict("records"),
                note="free with citation: Caldara & Iacoviello (2022) AER; monthly back to 1900 (GPRH) / 1985 (GPR); daily file recent window")
        except Exception as exc:  # noqa: BLE001
            rec(name, url, publisher="Caldara & Iacoviello", status=r.status_code, latency_ms=ms, note=f"parse: {exc}; content-type {r.headers.get('content-type')}")


# ── 7. ETF holdings as a driver ────────────────────────────────────────────────
def verify_etf() -> None:
    url = "https://www.spdrgoldshares.com/assets/dynamic/GLD/GLD_US_archive_EN.csv"
    r, ms, err = get(url, headers=BROWSER_UA, timeout=60)
    if r is not None and r.status_code == 200:
        txt = r.text
        save_sample("spdr_gld_archive", txt[:800] + "\n...\n" + txt[-600:])
        lines = [ln for ln in txt.splitlines() if ln.strip()]
        # find header row containing 'Date'
        hdr_idx = next((i for i, ln in enumerate(lines) if ln.lower().startswith("date")), None)
        rows = lines[hdr_idx + 1:] if hdr_idx is not None else []
        rec("SPDR GLD daily holdings archive CSV", url, publisher="State Street / SPDR Gold Trust", status=r.status_code, latency_ms=ms,
            header=lines[hdr_idx] if hdr_idx is not None else lines[0][:200], n_rows=len(rows), sample_rows=rows[-3:],
            latest_date=(rows[-1].split(",")[0] if rows else None),
            note="daily tonnes + NAV since 2004; website terms: personal, non-commercial; preamble lines before the header")
        (DATA / "spdr_gld_archive.csv").write_text(txt, encoding="utf-8")
    else:
        rec("SPDR GLD daily holdings archive CSV", url, publisher="SPDR", status=r.status_code if r else "ERR", latency_ms=ms, note=err or r.text[:150])
    url = "https://www.ishares.com/us/products/239561/ishares-gold-trust-fund/1467271812596.ajax?fileType=csv&fileName=IAU_holdings&dataType=fund"
    r, ms, err = get(url, headers=BROWSER_UA, timeout=60)
    if r is not None:
        save_sample("ishares_iau", r.text)
        rec("iShares IAU holdings CSV (ajax)", url, publisher="BlackRock iShares", status=r.status_code, latency_ms=ms,
            sample_rows=r.text.splitlines()[:12], note="snapshot (today's ounces), not a history")
    else:
        rec("iShares IAU holdings CSV", url, publisher="iShares", status="ERR", latency_ms=ms, note=err)
    url = "https://www.gold.org/goldhub/data/gold-etfs-holdings-and-flows"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("WGC Goldhub ETF holdings & flows page", url, publisher="World Gold Council", status=r.status_code if r else "ERR", latency_ms=ms,
        note=(f"HTML {len(r.text)} chars; downloads need a free Goldhub registration; WGC terms: no redistribution" if r else err))


# ── 8. LBMA prices (JSON) ──────────────────────────────────────────────────────
def verify_lbma() -> None:
    for name, url in (("LBMA gold PM price JSON", "https://prices.lbma.org.uk/json/gold_pm.json"),
                      ("LBMA gold AM price JSON", "https://prices.lbma.org.uk/json/gold_am.json"),
                      ("LBMA silver price JSON", "https://prices.lbma.org.uk/json/silver.json")):
        r, ms, err = get(url, headers=BROWSER_UA, timeout=60)
        if r is None:
            rec(name, url, publisher="LBMA", status="ERR", latency_ms=ms, note=err)
            continue
        try:
            j = r.json()
            rows = [{"d": x["d"], "v": x["v"]} for x in j]
            tag = url.rsplit("/", 1)[-1].replace(".json", "")
            pd.DataFrame([{"date": x["d"], **{f"v{i}": v for i, v in enumerate(x["v"])}} for x in j]).to_csv(DATA / f"lbma_{tag}.csv", index=False)
            rec(name, url, publisher="LBMA (prices.lbma.org.uk)", status=r.status_code, latency_ms=ms, n_rows=len(rows),
                first_date=rows[0]["d"], latest_date=rows[-1]["d"], sample_rows=rows[-2:],
                note="v = [USD, GBP, EUR]; LBMA terms: free for personal/non-commercial use, no redistribution, attribution required")
        except Exception as exc:  # noqa: BLE001
            save_sample(name.replace(" ", "_"), r.text)
            rec(name, url, publisher="LBMA", status=r.status_code, latency_ms=ms, note=f"parse: {exc}; {r.text[:150]!r}")


# ── 9. Kitco (link-only candidate) ─────────────────────────────────────────────
def verify_kitco() -> None:
    url = "https://www.kitco.com/charts/gold"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("Kitco gold charts page", url, publisher="Kitco Metals", status=r.status_code if r else "ERR", latency_ms=ms,
        note=(f"HTML {len(r.text)} chars; data rendered client-side from Kitco's own API; Kitco terms forbid scraping/republishing" if r else err))
    url = "https://www.kitco.com/robots.txt"
    r, ms, err = get(url, headers=BROWSER_UA)
    if r is not None:
        save_sample("kitco_robots", r.text)
    rec("Kitco robots.txt", url, publisher="Kitco", status=r.status_code if r else "ERR", latency_ms=ms, note=(r.text[:300].replace("\n", " | ") if r else err))


# ── 10. Other: Cleveland Fed, NY Fed, WGC gold price in currencies ─────────────
def verify_misc() -> None:
    url = "https://www.clevelandfed.org/indicators-and-data/inflation-expectations"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("Cleveland Fed inflation expectations page", url, publisher="Cleveland Fed", status=r.status_code if r else "ERR", latency_ms=ms,
        note=("HTML; same numbers are on FRED as EXPINF1YR..EXPINF30YR (monthly)" if r else err))
    url = "https://www.gold.org/goldhub/data/gold-prices"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("WGC Goldhub gold prices page (gold in currencies)", url, publisher="World Gold Council", status=r.status_code if r else "ERR", latency_ms=ms,
        note=("HTML; downloads need a free Goldhub registration" if r else err))
    url = "https://www.gold.org/goldhub/gold-focus/2024/03/gold-market-commentary"  # existence check only
    url = "https://www.gold.org/goldhub/research/gold-return-attribution-model"
    r, ms, err = get(url, headers=BROWSER_UA)
    rec("WGC GRAM (Gold Return Attribution Model) page", url, publisher="World Gold Council", status=r.status_code if r else "ERR", latency_ms=ms,
        note=("HTML; the professional driver-decomposition framework (monthly, free to read)" if r else err))


if __name__ == "__main__":
    steps = [verify_fred, verify_fred_api_gate, verify_treasury, verify_yahoo, verify_calendars, verify_fed_expectations,
             verify_gpr, verify_etf, verify_lbma, verify_kitco, verify_misc]
    only = sys.argv[1:]
    for fn in steps:
        if only and fn.__name__ not in only:
            continue
        print(f"\n=== {fn.__name__} ===", flush=True)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"!! {fn.__name__} crashed: {exc}", flush=True)
        (OUT / "verification.json").write_text(json.dumps(RESULTS, indent=1, default=str), encoding="utf-8")
    print(f"\nDONE: {len(RESULTS)} checks -> {OUT / 'verification.json'}")
