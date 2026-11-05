#!/usr/bin/env python
"""
Breeze data catalog — probe every ICICI Breeze *market-data* endpoint for one stock and
record what exists, how far back, how fine, with live samples.

    python scripts/breeze_data_catalog.py --ticker INFY [--ws-seconds 20] [--no-ws]

Output: reports/breeze_catalog/<TICKER>/
    summary.json          every probe: endpoint, params, status, rows, fields, time range
    samples/*.json|csv    raw responses (bars, quotes, option chains, ticks, depth, charges)

Read-only by construction: security master, names, quotes, option chains, historical bars
(cash / futures / options, live and expired contracts), order *preview* (charges, a GET),
the F&O margin *calculator*, and a short websocket sample (ticks, depth, 1-second candles).
It never places/modifies/cancels orders and never reads funds, holdings or positions.
"""
from __future__ import annotations

import argparse
import calendar
import io
import json
import sys
import time
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.icici import extract_session_token  # noqa: E402

MASTER_URL = "https://directlink.icicidirect.com/MotherAppMaster/SecurityMaster.zip"
CALL_GAP_S = 0.75            # ≤ 80 calls/min, ICICI allows 100/min and 5,000/day
TODAY = date.today()


# ── plumbing ──────────────────────────────────────────────────────────────────────

def env_file() -> dict[str, str]:
    out = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def patch_socket_timeout(seconds: float = 20.0) -> None:
    """breeze-connect 1.0.69 hard-codes socketio wait_timeout=3; from this network the live
    stream handshake takes ~3.4 s, so ws_connect() always failed ("Failed to connect to live
    stream"). Give the namespace handshake a realistic budget."""
    import socketio
    if getattr(socketio.Client.connect, "_suryadhana_patched", False):
        return
    original = socketio.Client.connect

    def connect(self, *args, **kwargs):
        kwargs["wait_timeout"] = max(kwargs.get("wait_timeout") or 1, seconds)
        return original(self, *args, **kwargs)

    connect._suryadhana_patched = True  # type: ignore[attr-defined]
    socketio.Client.connect = connect


def connect():
    try:      # breeze_connect downloads ICICI's security master at import, with no timeout: use the cache
        from shared.breeze_cache import install as _breeze_cache_install
        _breeze_cache_install()
    except Exception:  # noqa: BLE001
        pass
    from breeze_connect import BreezeConnect
    patch_socket_timeout()
    env = env_file()
    breeze = BreezeConnect(api_key=env["ICICI_API_KEY"])
    breeze.generate_session(api_secret=env["ICICI_API_SECRET"],
                            session_token=extract_session_token(env["ICICI_SESSION_TOKEN"]))
    return breeze


def iso(d: date, hhmm: str = "09:15") -> str:
    return f"{d.isoformat()}T{hhmm}:00.000Z"


def expiry_iso(ddmmmyyyy: str) -> str:
    return datetime.strptime(ddmmmyyyy.strip(), "%d-%b-%Y").strftime("%Y-%m-%dT06:00:00.000Z")


def monthly_expiry(year: int, month: int) -> date:
    """NSE stock-derivative monthly expiry: last Thursday before Sep-2025, last Tuesday since.
    Holiday shifts are not modelled — probes of expired contracts may need a day's tweak."""
    weekday = calendar.TUESDAY if (year, month) >= (2025, 9) else calendar.THURSDAY
    last = date(year, month, calendar.monthrange(year, month)[1])
    return last - timedelta(days=(last.weekday() - weekday) % 7)


class Catalog:
    def __init__(self, out: Path):
        self.out = out
        (out / "samples").mkdir(parents=True, exist_ok=True)
        self.probes: list[dict] = []
        self.facts: dict[str, Any] = {}

    def save(self, name: str, payload: Any) -> None:
        if isinstance(payload, pd.DataFrame):
            payload.to_csv(self.out / "samples" / f"{name}.csv", index=False)
        else:
            (self.out / "samples" / f"{name}.json").write_text(json.dumps(payload, indent=1, default=str))

    def call(self, name: str, endpoint: str, fn: Callable[[], Any], params: dict) -> Any:
        """Run one API call, record status/rows/fields/time range, save the raw response."""
        t0 = time.perf_counter()
        rec: dict[str, Any] = {"name": name, "endpoint": endpoint, "params": params}
        try:
            resp = fn()
        except Exception as exc:  # the error is information too
            resp = {"Status": "exception", "Error": f"{type(exc).__name__}: {exc}"}
        rec["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        rows = resp.get("Success") if isinstance(resp, dict) else None
        rec["status"] = resp.get("Status") if isinstance(resp, dict) else "?"
        rec["error"] = resp.get("Error") if isinstance(resp, dict) else None
        if isinstance(rows, dict):
            rows = [rows]
        rec["rows"] = len(rows) if isinstance(rows, list) else 0
        if rows:
            rec["fields"] = list(rows[0].keys())
            stamps = [r.get("datetime") for r in rows if isinstance(r, dict) and r.get("datetime")]
            if stamps:
                rec["first"], rec["last"] = min(stamps), max(stamps)
        self.probes.append(rec)
        self.save(name, resp)
        ok = "ok " if rec["rows"] else "-- "
        span = f" {rec.get('first', '')} → {rec.get('last', '')}" if rec.get("first") else ""
        print(f"{ok}{name:34} rows={rec['rows']:<5} {rec['latency_ms']:>5}ms{span}"
              f"{'' if rec['rows'] else '  ' + str(rec['error'])[:90]}")
        time.sleep(CALL_GAP_S)
        return resp

    def write(self) -> None:
        (self.out / "summary.json").write_text(json.dumps(
            {"generated": datetime.now().isoformat(timespec="seconds"), "facts": self.facts,
             "probes": self.probes}, indent=1, default=str))


def bars(resp: Any) -> pd.DataFrame:
    rows = resp.get("Success") if isinstance(resp, dict) else None
    df = pd.DataFrame(rows or [])
    if not df.empty and "datetime" in df:
        df["datetime"] = pd.to_datetime(df["datetime"])
        for c in ("open", "high", "low", "close", "volume", "open_interest"):
            if c in df:
                df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ── probes ────────────────────────────────────────────────────────────────────────

def security_master(cat: Catalog, ticker: str) -> tuple[pd.Series, pd.DataFrame]:
    t0 = time.perf_counter()
    blob = requests.get(MASTER_URL, timeout=120).content
    zf = zipfile.ZipFile(io.BytesIO(blob))
    files = {n: len(zf.read(n).splitlines()) - 1 for n in zf.namelist() if n.endswith(".txt")}

    def frame(name: str) -> pd.DataFrame:
        df = pd.read_csv(io.BytesIO(zf.read(name)), dtype=str)
        df.columns = [c.strip().strip('"') for c in df.columns]
        return df.apply(lambda s: s.str.strip().str.strip('"'))

    nse, fo = frame("NSEScripMaster.txt"), frame("FONSEScripMaster.txt")
    row = nse[nse["ExchangeCode"] == ticker].iloc[0]
    contracts = fo[fo["ShortName"] == row["ShortName"]].copy()
    contracts["StrikePrice"] = pd.to_numeric(contracts["StrikePrice"])
    contracts["_exp"] = pd.to_datetime(contracts["ExpiryDate"], format="%d-%b-%Y")
    contracts = contracts.sort_values(["_exp", "InstrumentName", "StrikePrice", "OptionType"])
    cat.save("security_master_cash", row.dropna().to_dict())
    cat.save("security_master_fno", contracts.drop(columns="_exp").dropna(axis=1, how="all"))
    cat.facts["security_master"] = {
        "url": MASTER_URL, "zip_mb": round(len(blob) / 1e6, 1), "files": files,
        "download_ms": round((time.perf_counter() - t0) * 1000),
        "cash_fields": [c for c in nse.columns], "fno_fields": [c for c in fo.columns],
        "fno_contracts": int(len(contracts)),
    }
    print(f"ok security master                   {files}")
    return row, contracts


def run(ticker: str, ws_seconds: int, use_ws: bool) -> Path:
    out = ROOT / "reports" / "breeze_catalog" / ticker
    cat = Catalog(out)
    breeze = connect()
    print(f"Connected. Probing {ticker}…\n")

    row, contracts = security_master(cat, ticker)
    code = row["ShortName"]
    cat.facts["identity"] = {k: row.get(k) for k in ("Token", "ShortName", "CompanyName", "ISINCode", "FaceValue",
                                                     "ticksize", "52WeeksHigh", "52WeeksLow", "LifeTimeHigh")}
    futs = contracts[contracts["InstrumentName"] == "FUTSTK"]
    opts = contracts[contracts["InstrumentName"] == "OPTSTK"]
    expiries = sorted(opts["_exp"].unique())
    near_exp, next_exp = expiries[0], expiries[1] if len(expiries) > 1 else expiries[0]
    near_x = pd.Timestamp(near_exp).strftime("%d-%b-%Y")
    next_x = pd.Timestamp(next_exp).strftime("%d-%b-%Y")
    lot = int(contracts["LotSize"].iloc[0])
    cat.facts["fno"] = {"lot_size": lot, "futures_expiries": futs["ExpiryDate"].tolist(),
                        "option_expiries": [pd.Timestamp(e).strftime("%d-%b-%Y") for e in expiries],
                        "strikes_per_expiry": opts.groupby("ExpiryDate")["StrikePrice"].nunique().to_dict()}

    cat.call("names_nse", "get_names", lambda: breeze.get_names(exchange_code="NSE", stock_code=ticker),
             {"exchange_code": "NSE", "stock_code": ticker})

    # live quotes
    q = cat.call("quote_cash_nse", "get_quotes", lambda: breeze.get_quotes(
        stock_code=code, exchange_code="NSE", product_type="cash"), {"exchange": "NSE", "product": "cash"})
    cat.call("quote_cash_bse", "get_quotes", lambda: breeze.get_quotes(
        stock_code=code, exchange_code="BSE", product_type="cash"), {"exchange": "BSE", "product": "cash"})
    spot = float((q.get("Success") or [{}])[0].get("ltp") or 0) if isinstance(q, dict) else 0.0
    fq = cat.call("quote_future_near", "get_quotes", lambda: breeze.get_quotes(
        stock_code=code, exchange_code="NFO", product_type="futures", expiry_date=expiry_iso(near_x),
        right="others", strike_price="0"), {"exchange": "NFO", "product": "futures", "expiry": near_x})
    strikes = sorted(opts[opts["_exp"] == near_exp]["StrikePrice"].unique())
    atm = min(strikes, key=lambda k: abs(k - spot)) if spot else strikes[len(strikes) // 2]
    for right in ("call", "put"):
        cat.call(f"quote_option_atm_{right}", "get_quotes", lambda r=right: breeze.get_quotes(
            stock_code=code, exchange_code="NFO", product_type="options", expiry_date=expiry_iso(near_x),
            right=r, strike_price=str(int(atm))), {"expiry": near_x, "right": right, "strike": atm})
    fut_ltp = float((fq.get("Success") or [{}])[0].get("ltp") or 0) if isinstance(fq, dict) else 0.0

    # option chains (whole strip per expiry & side)
    chains = {}
    for label, x in (("near", near_x), ("next", next_x)):
        for right in ("call", "put"):
            chains[(label, right)] = cat.call(
                f"option_chain_{label}_{right}", "get_option_chain_quotes", lambda x=x, r=right:
                breeze.get_option_chain_quotes(stock_code=code, exchange_code="NFO", product_type="options",
                                               expiry_date=expiry_iso(x), right=r),
                {"expiry": x, "right": right})
    if not spot:  # get_quotes has its own daily cap; the chain carries the underlying's LTP
        rows = [r for c in chains.values() if isinstance(c, dict) for r in (c.get("Success") or [])]
        spot = next((float(r["spot_price"]) for r in rows if float(r.get("spot_price") or 0) > 0), 0.0)
        cat.facts["spot_source"] = "option_chain.spot_price (get_quotes capped)" if spot else "unavailable"
        atm = min(strikes, key=lambda k: abs(k - spot)) if spot else atm
    cat.facts["spot_ltp"], cat.facts["future_ltp"], cat.facts["atm_strike"] = spot, fut_ltp, atm

    # last complete session + today's partial session
    d1 = cat.call("hist_cash_1day_recent", "get_historical_data_v2", lambda: breeze.get_historical_data_v2(
        interval="1day", from_date=iso(TODAY - timedelta(days=14)), to_date=iso(TODAY, "15:30"),
        stock_code=code, exchange_code="NSE", product_type="cash"), {"interval": "1day", "days": 14})
    days = sorted({pd.Timestamp(r["datetime"]).date() for r in (d1.get("Success") or [])})
    last_full = max(d for d in days if d < TODAY) if days else TODAY - timedelta(days=3)
    cat.facts["last_full_session"] = str(last_full)

    def hist(name, interval, start, end, product="cash", exchange="NSE", **kw):
        return cat.call(name, "get_historical_data_v2", lambda: breeze.get_historical_data_v2(
            interval=interval, from_date=start, to_date=end, stock_code=kw.get("stock_code", code),
            exchange_code=exchange, product_type=product, expiry_date=kw.get("expiry_date", ""),
            right=kw.get("right", ""), strike_price=kw.get("strike_price", "")),
            {"interval": interval, "from": start, "to": end, "exchange": exchange, "product": product,
             **{k: v for k, v in kw.items() if v}})

    hist("hist_cash_1second", "1second", iso(last_full, "15:00"), iso(last_full, "15:30"))
    hist("hist_cash_1minute", "1minute", iso(last_full), iso(last_full, "15:30"))
    hist("hist_cash_1minute_today", "1minute", iso(TODAY), iso(TODAY, "15:30"))
    hist("hist_cash_5minute_5d", "5minute", iso(last_full - timedelta(days=7)), iso(last_full, "15:30"))
    hist("hist_cash_30minute_1m", "30minute", iso(last_full - timedelta(days=30)), iso(last_full, "15:30"))
    hist("hist_cash_1minute_bse", "1minute", iso(last_full), iso(last_full, "15:30"), exchange="BSE")

    # full daily history in ≤1000-bar chunks (≈ 4 calendar years each)
    daily = []
    start = date(2010, 1, 1)
    while start < TODAY:
        end = min(start + timedelta(days=1400), TODAY)
        r = hist(f"hist_cash_1day_{start.year}", "1day", iso(start), iso(end, "15:30"))
        daily.append(bars(r))
        start = end + timedelta(days=1)
    daily_df = pd.concat([d for d in daily if not d.empty]).drop_duplicates("datetime").sort_values("datetime")
    cat.save("hist_cash_1day_full", daily_df)
    cat.facts["daily_history"] = {"first": str(daily_df["datetime"].min().date()),
                                  "last": str(daily_df["datetime"].max().date()), "bars": int(len(daily_df))}

    # futures and options, live contracts
    xf = expiry_iso(near_x)
    hist("hist_future_1minute", "1minute", iso(last_full), iso(last_full, "15:30"), product="futures",
         exchange="NFO", expiry_date=xf, right="others", strike_price="0")
    hist("hist_future_1day", "1day", iso(TODAY - timedelta(days=100)), iso(TODAY, "15:30"), product="futures",
         exchange="NFO", expiry_date=xf, right="others", strike_price="0")
    hist("hist_option_atm_call_1minute", "1minute", iso(last_full), iso(last_full, "15:30"), product="options",
         exchange="NFO", expiry_date=xf, right="call", strike_price=str(int(atm)))
    hist("hist_option_atm_put_1second", "1second", iso(last_full, "15:00"), iso(last_full, "15:30"),
         product="options", exchange="NFO", expiry_date=xf, right="put", strike_price=str(int(atm)))

    # expired contracts (research on past expiries needs these)
    for y, m in ((2025, 9), (2023, 9), (2020, 9)):
        exp = monthly_expiry(y, m)
        day = exp - timedelta(days=7 if exp.weekday() >= 2 else 6)
        near = daily_df[daily_df["datetime"].dt.date <= day]
        px = float(near["close"].iloc[-1]) if not near.empty else atm
        k = int(round(px / 20) * 20)
        hist(f"hist_expired_future_{exp:%Y%m}", "1minute", iso(day), iso(day, "15:30"), product="futures",
             exchange="NFO", expiry_date=exp.strftime("%Y-%m-%dT06:00:00.000Z"), right="others", strike_price="0")
        hist(f"hist_expired_option_{exp:%Y%m}_call{k}", "1minute", iso(day), iso(day, "15:30"), product="options",
             exchange="NFO", expiry_date=exp.strftime("%Y-%m-%dT06:00:00.000Z"), right="call", strike_price=str(k))

    # index candles (NIFTY 50) through the same endpoint
    hist("hist_index_nifty_1minute", "1minute", iso(last_full), iso(last_full, "15:30"), stock_code="NIFTY")

    # trading costs straight from ICICI (GET preview — no order is created)
    qty = 10
    cat.call("charges_preview_delivery_buy", "preview_order", lambda: breeze.preview_order(
        stock_code=code, exchange_code="NSE", product="cash", order_type="limit", price=f"{spot:.2f}",
        action="buy", quantity=str(qty), expiry_date="", right="", strike_price="", specialflag="N",
        stoploss="", order_rate_fresh=""), {"product": "cash", "action": "buy", "qty": qty, "price": spot})
    cat.call("charges_preview_delivery_sell", "preview_order", lambda: breeze.preview_order(
        stock_code=code, exchange_code="NSE", product="cash", order_type="limit", price=f"{spot:.2f}",
        action="sell", quantity=str(qty), expiry_date="", right="", strike_price="", specialflag="N",
        stoploss="", order_rate_fresh=""), {"product": "cash", "action": "sell", "qty": qty, "price": spot})
    cat.call("margin_future_1lot", "margin_calculator", lambda: breeze.margin_calculator([{
        "strike_price": "0", "quantity": str(lot), "right": "others", "product": "futures", "action": "buy",
        "price": f"{fut_ltp:.2f}", "expiry_date": near_x, "stock_code": code, "cover_order_flow": "N",
        "fresh_order_type": "N", "cover_limit_rate": "0", "cover_sltp_price": "0", "fresh_limit_rate": "0",
        "open_quantity": "0"}], "NFO"), {"product": "futures", "qty": lot, "expiry": near_x})

    if use_ws:
        try:
            websocket_sample(cat, breeze, code, near_x, ws_seconds)
        except Exception as exc:
            cat.probes.append({"name": "ws_connect", "endpoint": "ws_connect", "rows": 0,
                               "error": f"{type(exc).__name__}: {exc}"})
            print(f"-- websocket failed: {exc}")
    cat.write()
    print(f"\nWrote {out.relative_to(ROOT)}/summary.json and {len(list((out / 'samples').iterdir()))} samples")
    return out


def websocket_sample(cat: Catalog, breeze, code: str, near_x: str, seconds: int) -> None:
    """Live ticks, 5-level depth and 1-second candles for a few seconds each (market hours)."""
    streams: dict[str, list] = {"ticks_cash": [], "depth_cash": [], "ticks_future": [], "ohlc_1second": []}
    current = {"key": "ticks_cash"}
    breeze.on_ticks = lambda tick: streams[current["key"]].append({"_recv": time.time(), **tick})
    breeze.ws_connect()
    plans = [
        ("ticks_cash", dict(exchange_code="NSE", stock_code=code, product_type="cash",
                            get_exchange_quotes=True, get_market_depth=False)),
        ("depth_cash", dict(exchange_code="NSE", stock_code=code, product_type="cash",
                            get_exchange_quotes=False, get_market_depth=True)),
        ("ticks_future", dict(exchange_code="NFO", stock_code=code, product_type="futures",
                              expiry_date=expiry_iso(near_x), right="others", strike_price="0",
                              get_exchange_quotes=True, get_market_depth=False)),
        ("ohlc_1second", dict(exchange_code="NSE", stock_code=code, product_type="cash", interval="1second")),
    ]
    for key, kw in plans:
        current["key"] = key
        t0 = time.time()
        try:
            breeze.subscribe_feeds(**kw)
            time.sleep(seconds)
            breeze.unsubscribe_feeds(**kw)
        except Exception as exc:
            streams[key].append({"_error": f"{type(exc).__name__}: {exc}"})
        got = [t for t in streams[key] if "_error" not in t]
        rec = {"name": f"ws_{key}", "endpoint": "subscribe_feeds", "params": {k: v for k, v in kw.items()},
               "rows": len(got), "seconds": round(time.time() - t0, 1),
               "fields": sorted({f for t in got for f in t.keys()} - {"_recv"}),
               "per_second": round(len(got) / max(seconds, 1), 2),
               "error": next((t["_error"] for t in streams[key] if "_error" in t), None)}
        cat.probes.append(rec)
        cat.save(f"ws_{key}", streams[key])
        print(f"{'ok ' if got else '-- '}ws {key:30} rows={len(got):<5} {rec['per_second']}/s"
              f"{'' if got else '  ' + str(rec['error'])[:80]}")
        time.sleep(1)
    try:
        breeze.ws_disconnect()
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--ticker", default="INFY", help="NSE symbol, e.g. INFY, RELIANCE")
    ap.add_argument("--ws-seconds", type=int, default=20)
    ap.add_argument("--no-ws", action="store_true", help="skip the websocket sample")
    args = ap.parse_args()
    run(args.ticker.upper(), args.ws_seconds, not args.no_ws)


if __name__ == "__main__":
    main()
