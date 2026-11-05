"""
probe_commodity_feed.py — Feasibility probe for a SuryaDhana "Commodity" tab.

PURPOSE
-------
De-risk the single hardest part of the proposed Commodity tab: the *data-fetch
layer*. The doc `docs/PROGRAMMATIC_DATA_ACCESS.md` catalogues FRED/EIA/etc. for
commodity FUNDAMENTALS / MACRO CONTEXT — but trading a commodity needs an actual
tradeable PRICE series for the instrument itself, which that doc does not cover.

This probe proves three independent fetch paths end to end, each isolated so the
absence of an API key never fakes a number:

  1. PRICE FEED (free proxy, NO KEY)  — global commodity futures via yfinance
     (WTI crude `CL=F`, Brent `BZ=F`, COMEX gold `GC=F`, silver `SI=F`,
      copper `HG=F`, natural gas `NG=F`). This is the live tradeable-context
     series. yfinance is already this project's historical price provider.
  2. FUNDAMENTALS (EIA, KEY REQUIRED) — crude/natural-gas inventories & prod.
     Skipped cleanly with a wiring note if `EIA_API_KEY` is absent.
  3. MACRO CONTEXT (FRED, KEY REQUIRED) — commodity/energy price *indices*, USD,
     rates. Skipped cleanly with a wiring note if `FRED_API_KEY` is absent.

NON-NEGOTIABLES honoured:
  * MODE is observational/read-only — nothing here trades or writes the DB.
  * NO hardcoded secrets — every key is read from the environment.
  * NO fabricated data — a missing key prints the exact wiring and exits that leg.
  * Canonical Python: /Users/sudheer/Desktop/jupyter_env/bin/python

This is an untracked sidecar probe, NOT production code. The production version
would live behind a ui-api router (e.g. services/ui-api/routers/commodity.py)
with Redis caching and PIT/ALFRED discipline for any *backtested* factor.

Run:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/probe_commodity_feed.py
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

# ── Config (surfaced at top; no magic numbers buried in logic) ────────────────

LOOKBACK_DAYS: int = 30
PRICE_FEED_TICKERS: dict[str, str] = {
    "CL=F": "WTI Crude (NYMEX, USD/bbl)",
    "BZ=F": "Brent Crude (ICE, USD/bbl)",
    "GC=F": "COMEX Gold (USD/oz)",
    "SI=F": "COMEX Silver (USD/oz)",
    "HG=F": "COMEX Copper (USD/lb)",
    "NG=F": "Henry Hub Nat Gas (USD/MMBtu)",
}
# EIA v2 series — weekly US crude inventory (ex-SPR) is the canonical surprise driver.
EIA_SERIES_ID: str = "PET.WCRSTUS1.W"            # weekly US crude stocks, thousand bbl
EIA_V2_URL: str = (
    "https://api.eia.gov/v2/petroleum/stoc/wstk/data/"
    "?frequency=weekly&data[0]=value&facets[series][]=WCRSTUS1"
    "&sort[0][column]=period&sort[0][direction]=desc&length=8"
)
# FRED series — Global price of energy index (IMF, via FRED) as macro context.
FRED_SERIES_IDS: tuple[str, ...] = ("PNRGINDEXM", "DCOILWTICO", "DTWEXBGS")

SEP = "─" * 78


@dataclass
class LegResult:
    """Outcome of one fetch leg, for the final summary line."""
    name: str
    ok: bool
    detail: str


def _print_header(title: str) -> None:
    print(f"\n{SEP}\n{title}\n{SEP}")


# ── Leg 1: PRICE FEED via yfinance (no key) — the tradeable context series ─────

def fetch_price_feed() -> LegResult:
    """Pull recent daily closes for global commodity futures via yfinance.

    Returns a LegResult; prints a tail dataframe of the latest closes so the
    fetch path is visibly proven. yfinance needs no API key.
    """
    _print_header("LEG 1 — PRICE FEED (global futures via yfinance, NO KEY)")
    try:
        import yfinance as yf
    except ImportError:
        msg = "yfinance not importable in this env — install into the canonical env"
        print(f"  SKIP: {msg}")
        return LegResult("price_feed", False, msg)

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=LOOKBACK_DAYS)
    symbols = list(PRICE_FEED_TICKERS)
    try:
        raw = yf.download(
            symbols, start=str(start), end=str(end),
            progress=False, auto_adjust=False, group_by="ticker",
        )
    except Exception as exc:  # network / provider hiccup
        print(f"  FAIL: yfinance download error: {exc}")
        return LegResult("price_feed", False, str(exc))

    if raw is None or len(raw) == 0:
        print("  FAIL: empty frame returned (market closed / symbols unavailable)")
        return LegResult("price_feed", False, "empty frame")

    # Normalise to a [date x symbol] close panel across the MultiIndex columns.
    closes = {}
    for sym in symbols:
        try:
            col = raw[sym]["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw["Close"]
            closes[sym] = col
        except Exception:
            continue
    panel = pd.DataFrame(closes).dropna(how="all")
    if panel.empty:
        print("  FAIL: no Close columns resolved from yfinance frame")
        return LegResult("price_feed", False, "no close columns")

    panel = panel.rename(columns={k: f"{k}" for k in panel.columns})
    print(f"  Fetched {panel.shape[0]} sessions x {panel.shape[1]} instruments "
          f"({start} → {end}). Latest closes:")
    latest = panel.tail(3).round(2)
    with pd.option_context("display.max_columns", None, "display.width", 200):
        print(latest.to_string())
    # Echo the instrument legend so the desk knows what each symbol is.
    print("\n  Legend:")
    for sym in panel.columns:
        print(f"    {sym:<6} {PRICE_FEED_TICKERS.get(sym, '?')}")
    last_row = panel.dropna(how="all").iloc[-1]
    n_live = int(last_row.notna().sum())
    return LegResult("price_feed", True,
                     f"{n_live}/{len(symbols)} instruments with a live latest close")


# ── Leg 2: FUNDAMENTALS via EIA v2 (key required) ─────────────────────────────

def fetch_eia_fundamentals() -> LegResult:
    """Pull weekly US crude inventories from EIA v2. Requires EIA_API_KEY.

    No key ⇒ print the exact wiring and skip (never fabricate a number).
    """
    _print_header("LEG 2 — FUNDAMENTALS (EIA v2 weekly crude stocks, KEY REQUIRED)")
    api_key = os.environ.get("EIA_API_KEY")
    if not api_key:
        print("  SKIP: EIA_API_KEY not set in environment.")
        print("  Wiring (when the key is provisioned):")
        print("    export EIA_API_KEY=...   # free, register at eia.gov/opendata")
        print(f"    GET {EIA_V2_URL}&api_key=$EIA_API_KEY")
        print(f"    series_id={EIA_SERIES_ID} → weekly US crude stocks (thousand bbl)")
        return LegResult("eia_fundamentals", False, "no EIA_API_KEY (wiring shown)")

    import requests
    try:
        resp = requests.get(f"{EIA_V2_URL}&api_key={api_key}", timeout=20)
        resp.raise_for_status()
        data = resp.json().get("response", {}).get("data", [])
    except Exception as exc:
        print(f"  FAIL: EIA request error: {exc}")
        return LegResult("eia_fundamentals", False, str(exc))

    if not data:
        print("  FAIL: EIA returned no rows")
        return LegResult("eia_fundamentals", False, "no rows")
    df = pd.DataFrame(data)[["period", "value"]].head(6)
    print(f"  Latest weekly US crude inventory prints ({EIA_SERIES_ID}):")
    print(df.to_string(index=False))
    return LegResult("eia_fundamentals", True, f"{len(data)} weekly prints fetched")


# ── Leg 3: MACRO CONTEXT via FRED (key required) ──────────────────────────────

def fetch_fred_macro() -> LegResult:
    """Pull commodity/energy macro context indices from FRED. Requires FRED_API_KEY.

    No key (or no fredapi) ⇒ print the exact wiring and skip. For any *backtested*
    factor, the production path MUST use ALFRED vintages (PIT), not FRED-latest.
    """
    _print_header("LEG 3 — MACRO CONTEXT (FRED energy/USD indices, KEY REQUIRED)")
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        print("  SKIP: FRED_API_KEY not set in environment.")
        print("  Wiring (when the key is provisioned):")
        print("    pip install fredapi   # into the canonical env")
        print("    export FRED_API_KEY=...")
        print(f"    series: {', '.join(FRED_SERIES_IDS)} "
              "(energy index, WTI, broad USD)")
        print("    NOTE: for any BACKTESTED factor use ALFRED vintages (PIT), "
              "not FRED-latest — see PROGRAMMATIC_DATA_ACCESS.md §3.")
        return LegResult("fred_macro", False, "no FRED_API_KEY (wiring shown)")

    try:
        from fredapi import Fred
    except ImportError:
        print("  SKIP: fredapi not installed.")
        print("    /Users/sudheer/Desktop/jupyter_env/bin/pip install fredapi")
        return LegResult("fred_macro", False, "fredapi missing (wiring shown)")

    fred = Fred(api_key=api_key)
    out: dict[str, Optional[float]] = {}
    for sid in FRED_SERIES_IDS:
        try:
            s = fred.get_series(sid)
            out[sid] = float(s.dropna().iloc[-1]) if len(s.dropna()) else None
        except Exception as exc:
            out[sid] = None
            print(f"    {sid}: error {exc}")
    print("  Latest FRED-latest values (NOT PIT — live-view only):")
    for sid, val in out.items():
        print(f"    {sid:<12} {val}")
    n_ok = sum(1 for v in out.values() if v is not None)
    return LegResult("fred_macro", n_ok > 0, f"{n_ok}/{len(FRED_SERIES_IDS)} series fetched")


def main() -> None:
    print("SuryaDhana — Commodity feed feasibility probe")
    print(f"  python: {os.sys.executable}")
    print(f"  now (UTC): {datetime.now(timezone.utc).isoformat(timespec='seconds')}")

    results = [fetch_price_feed(), fetch_eia_fundamentals(), fetch_fred_macro()]

    _print_header("SUMMARY")
    for r in results:
        flag = "OK  " if r.ok else "SKIP/FAIL"
        print(f"  [{flag}] {r.name:<18} {r.detail}")
    price_ok = results[0].ok
    print()
    if price_ok:
        print("  VERDICT: the PRICE feed (free, no-key) path works end to end — "
              "the Commodity tab is feasible on the yfinance proxy today.")
    else:
        print("  VERDICT: price feed did not return data this run "
              "(market closed or network). Re-run during/after a session.")
    print("  EIA/FRED legs require keys; wiring is shown above, no data fabricated.")


if __name__ == "__main__":
    main()
