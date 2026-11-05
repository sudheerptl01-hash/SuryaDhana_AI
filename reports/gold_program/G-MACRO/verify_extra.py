"""Supplementary verification: FRED H.10 FX legs for the KGX basket, LBMA platinum/palladium, and a SPARSE
Yahoo retry (the first pass got HTTP 429 on every symbol from this IP) using the app's own User-Agent
(gold_preopen.py: "Mozilla/5.0 (SuryaDhana-GoldDesk)") and both hosts, 6 s apart."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_sources as vs  # noqa: E402

vs.RESULTS.clear()
OUT = vs.OUT / "verification_extra.json"

# 1. FRED H.10 FX (daily, ~1 week lag) — full history for the KGX basket + gold in currencies
extra_fred = {"DEXUSUK": "GBP/USD (H.10)", "DEXCAUS": "USD/CAD (H.10)", "DEXSDUS": "USD/SEK (H.10)", "DEXSZUS": "USD/CHF (H.10)"}
vs.FRED_SERIES.clear()
vs.FRED_SERIES.update(extra_fred)
vs.FULL_HISTORY.update(extra_fred)
vs.verify_fred()

# 2. LBMA platinum / palladium
for name, url in (("LBMA platinum AM JSON", "https://prices.lbma.org.uk/json/platinum_am.json"),
                  ("LBMA palladium AM JSON", "https://prices.lbma.org.uk/json/palladium_am.json")):
    r, ms, err = vs.get(url, headers=vs.BROWSER_UA, timeout=60)
    if r is None or r.status_code != 200:
        vs.rec(name, url, publisher="LBMA", status=r.status_code if r else "ERR", latency_ms=ms, note=err or r.text[:120])
        continue
    try:
        j = r.json()
        import pandas as pd
        tag = url.rsplit("/", 1)[-1].replace(".json", "")
        pd.DataFrame([{"date": x["d"], **{f"v{i}": v for i, v in enumerate(x["v"])}} for x in j]).to_csv(vs.DATA / f"lbma_{tag}.csv", index=False)
        vs.rec(name, url, publisher="LBMA", status=r.status_code, latency_ms=ms, n_rows=len(j), first_date=j[0]["d"], latest_date=j[-1]["d"],
               sample_rows=j[-2:], note="v = [USD, GBP, EUR]")
    except Exception as exc:  # noqa: BLE001
        vs.rec(name, url, publisher="LBMA", status=r.status_code, latency_ms=ms, note=f"parse: {exc}")

# 2b. Key-free long gold histories that do not depend on Yahoo or LBMA
import io
import pandas as pd
url = "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx"
r, ms, err = vs.get(url, headers=vs.BROWSER_UA, timeout=90)
if r is not None and r.status_code == 200:
    try:
        x = pd.read_excel(io.BytesIO(r.content), sheet_name="Monthly Prices", header=None)
        # row 4 (0-based) holds the series names, row 5 units; data from row 6; col 0 = '1960M01'
        names = x.iloc[4].tolist()
        gold_col = next(i for i, n in enumerate(names) if str(n).strip().lower() == "gold")
        silver_col = next((i for i, n in enumerate(names) if str(n).strip().lower() == "silver"), None)
        plat_col = next((i for i, n in enumerate(names) if str(n).strip().lower() == "platinum"), None)
        body = x.iloc[6:, [0, gold_col] + [c for c in (silver_col, plat_col) if c is not None]].copy()
        body.columns = ["month", "gold"] + [n for n, c in (("silver", silver_col), ("platinum", plat_col)) if c is not None]
        body = body[body["month"].astype(str).str.match(r"^\d{4}M\d{2}$")]
        body["date"] = pd.to_datetime(body["month"].astype(str), format="%YM%m") + pd.offsets.MonthEnd(0)
        body = body.drop(columns=["month"]).set_index("date").astype(float)
        body.to_csv(vs.DATA / "worldbank_cmo_monthly.csv")
        vs.rec("World Bank CMO 'Pink Sheet' monthly prices xlsx", url, publisher="World Bank", status=r.status_code, latency_ms=ms, n_rows=len(body),
               first_date=str(body.index[0].date()), latest_date=str(body.index[-1].date()), latest_value=float(body["gold"].iloc[-1]),
               header="sheet 'Monthly Prices': 1960M01→, gold $/troy oz (monthly average of LBMA PM), silver, platinum ...",
               note="free, no key; CC BY-4.0; monthly AVERAGES (not month-end) — fine for seasonality, not for daily work")
    except Exception as exc:  # noqa: BLE001
        vs.rec("World Bank CMO monthly xlsx", url, publisher="World Bank", status=r.status_code, latency_ms=ms, note=f"parse: {exc}")
else:
    vs.rec("World Bank CMO monthly xlsx", url, publisher="World Bank", status=r.status_code if r else "ERR", latency_ms=ms, note=err or r.text[:100])

for sym, label in (("xauusd", "spot gold USD/oz"), ("xagusd", "spot silver"), ("xptusd", "spot platinum"), ("usdinr", "USD/INR"), ("dx.f", "DXY continuous future?")):
    url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
    r, ms, err = vs.get(url, headers=vs.BROWSER_UA, timeout=60)
    if r is None or r.status_code != 200:
        vs.rec(f"Stooq {sym} daily CSV", url, publisher="Stooq", status=r.status_code if r else "ERR", latency_ms=ms, note=err or r.text[:100])
        continue
    try:
        df = pd.read_csv(io.StringIO(r.text))
        if "Date" not in df.columns or df.empty:
            vs.rec(f"Stooq {sym} daily CSV", url, publisher="Stooq", status=r.status_code, latency_ms=ms, note=f"unexpected body: {r.text[:120]!r}")
            continue
        df.to_csv(vs.DATA / f"stooq_{sym.replace('.', '_')}.csv", index=False)
        vs.rec(f"Stooq {sym} daily CSV", url, publisher="Stooq (stooq.com)", label=label, status=r.status_code, latency_ms=ms, n_rows=len(df),
               header=",".join(df.columns), first_date=str(df["Date"].iloc[0]), latest_date=str(df["Date"].iloc[-1]), latest_value=float(df["Close"].iloc[-1]),
               note="free, no key; daily OHLC; terms: personal use, daily download cap (~200/day) then it serves 'Exceeded the daily hits limit'")
    except Exception as exc:  # noqa: BLE001
        vs.rec(f"Stooq {sym} daily CSV", url, publisher="Stooq", status=r.status_code, latency_ms=ms, note=f"parse: {exc}; {r.text[:100]!r}")

# 3. Sparse Yahoo retry: the app's UA, query2 then query1, 6 s apart, only the symbols the study needs most
vs.SLEEP = 6.0
APP_UA = {"User-Agent": "Mozilla/5.0 (SuryaDhana-GoldDesk)"}
for sym in ["GC=F", "DX-Y.NYB", "^GVZ", "ZQ=F", "PL=F", "SI=F", "INR=X", "EURUSD=X", "JPY=X", "CNY=X", "GBPUSD=X", "CAD=X", "SEK=X", "CHF=X",
            "^TNX", "^VIX", "TIP", "IEF", "GLD", "GOLDBEES.NS", "XAUUSD=X", "ZQZ26.CBT", "CL=F"]:
    ok = False
    for host in ("query2", "query1"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}"
        full = sym in vs.YAHOO_FULL
        params = {"range": "max" if full else "5d", "interval": "1d" if full else "5m", "includePrePost": "false"}
        r, ms, err = vs.get(url, headers=APP_UA, params=params)
        if r is None:
            vs.rec(f"Yahoo {sym} (retry, {host}, app UA)", url, publisher="Yahoo Finance", status="ERR", latency_ms=ms, note=err)
            continue
        if r.status_code != 200:
            vs.rec(f"Yahoo {sym} (retry, {host}, app UA)", url, publisher="Yahoo Finance", status=r.status_code, latency_ms=ms,
                   note=r.text[:80].replace("\n", " "))
            continue
        try:
            import pandas as pd
            from datetime import datetime, timezone
            j = r.json()
            res = (j.get("chart") or {}).get("result")
            if not res:
                vs.rec(f"Yahoo {sym} (retry, {host}, app UA)", url, publisher="Yahoo Finance", status=r.status_code, latency_ms=ms,
                       note=f"no result: {json.dumps((j.get('chart') or {}).get('error'))[:200]}")
                ok = True
                break
            res = res[0]
            meta = res.get("meta", {})
            ts = res.get("timestamp") or []
            q = (res.get("indicators", {}).get("quote") or [{}])[0]
            df = pd.DataFrame({"ts": ts, "open": q.get("open"), "high": q.get("high"), "low": q.get("low"), "close": q.get("close"), "volume": q.get("volume")})
            df = df[df["close"].notna()]
            df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True)
            if full:
                df["date"] = df["date"].dt.tz_convert(meta.get("exchangeTimezoneName") or "UTC").dt.date
                df[["date", "open", "high", "low", "close", "volume"]].to_csv(vs.DATA / f"yahoo_{sym.replace('=', '_').replace('^', '_').replace('.', '_')}.csv", index=False)
            lt = meta.get("regularMarketTime")
            vs.rec(f"Yahoo {sym} (retry, {host}, app UA)", url, publisher="Yahoo Finance (unofficial chart API)", label=vs.YAHOO.get(sym, ""),
                   status=r.status_code, latency_ms=ms, n_rows=int(len(df)), first_date=str(df["date"].iloc[0]) if len(df) else None,
                   latest_date=str(df["date"].iloc[-1]) if len(df) else None, latest_value=meta.get("regularMarketPrice"),
                   regular_market_time=datetime.fromtimestamp(lt, tz=timezone.utc).isoformat() if lt else None,
                   currency=meta.get("currency"), exchange=meta.get("exchangeName"), note=f"range={params['range']} interval={params['interval']}")
            ok = True
            break
        except Exception as exc:  # noqa: BLE001
            vs.rec(f"Yahoo {sym} (retry, {host}, app UA)", url, publisher="Yahoo Finance", status=r.status_code, latency_ms=ms, note=f"parse: {exc}")
    OUT.write_text(json.dumps(vs.RESULTS, indent=1, default=str), encoding="utf-8")
    if not ok:
        time.sleep(4)
OUT.write_text(json.dumps(vs.RESULTS, indent=1, default=str), encoding="utf-8")
print("DONE extra", len(vs.RESULTS))
