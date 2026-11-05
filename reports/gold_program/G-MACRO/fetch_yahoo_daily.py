"""Yahoo daily histories with explicit period1/period2 (range=max silently returns MONTHLY bars — verified 26 Oct 2026).
App UA, query2, 6 s between requests."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import verify_sources as vs  # noqa: E402

APP_UA = {"User-Agent": "Mozilla/5.0 (SuryaDhana-GoldDesk)"}
SYMS = ["GC=F", "DX-Y.NYB", "SI=F", "PL=F", "INR=X", "EURUSD=X", "JPY=X", "CNY=X", "GBPUSD=X", "CAD=X", "SEK=X", "CHF=X",
        "^GVZ", "^VIX", "^TNX", "ZQ=F", "GLD", "TIP", "IEF", "GOLDBEES.NS", "CL=F"]
P1 = int(datetime(1990, 1, 1, tzinfo=timezone.utc).timestamp())
P2 = int(time.time())
res_all = []
for sym in SYMS:
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=40, headers=APP_UA, follow_redirects=True) as c:
            r = c.get(url, params={"period1": P1, "period2": P2, "interval": "1d", "includePrePost": "false", "events": "div,splits"})
        ms = round((time.perf_counter() - t0) * 1000)
        j = r.json()
        res = (j.get("chart") or {}).get("result")
        if r.status_code != 200 or not res:
            print(f"[{r.status_code}] {sym} {ms} ms {r.text[:100]!r}")
            res_all.append({"symbol": sym, "status": r.status_code, "latency_ms": ms, "note": r.text[:120]})
            continue
        res = res[0]
        meta = res.get("meta", {})
        q = (res.get("indicators", {}).get("quote") or [{}])[0]
        df = pd.DataFrame({"ts": res.get("timestamp") or [], "open": q.get("open"), "high": q.get("high"), "low": q.get("low"),
                           "close": q.get("close"), "volume": q.get("volume")})
        df = df[df["close"].notna()]
        df["date"] = pd.to_datetime(df["ts"], unit="s", utc=True).dt.tz_convert(meta.get("exchangeTimezoneName") or "UTC").dt.date
        df = df.drop_duplicates("date", keep="last")
        out = vs.DATA / f"yahoo_{sym.replace('=', '_').replace('^', '_').replace('.', '_')}.csv"
        df[["date", "open", "high", "low", "close", "volume"]].to_csv(out, index=False)
        gap = pd.to_datetime(df["date"]).diff().dt.days.median()
        print(f"[200] {sym} {ms} ms rows={len(df)} first={df['date'].iloc[0]} last={df['date'].iloc[-1]} median_gap={gap} price={meta.get('regularMarketPrice')}")
        res_all.append({"symbol": sym, "status": 200, "latency_ms": ms, "n_rows": int(len(df)), "first_date": str(df["date"].iloc[0]),
                        "latest_date": str(df["date"].iloc[-1]), "median_gap_days": float(gap), "latest_value": meta.get("regularMarketPrice"),
                        "exchange": meta.get("exchangeName"), "currency": meta.get("currency"), "tz": meta.get("exchangeTimezoneName")})
    except Exception as exc:  # noqa: BLE001
        print(f"[ERR] {sym} {exc}")
        res_all.append({"symbol": sym, "status": "ERR", "note": str(exc)[:160]})
    finally:
        time.sleep(6)
(vs.OUT / "verification_yahoo_daily.json").write_text(json.dumps(res_all, indent=1, default=str))
print("DONE yahoo daily")
