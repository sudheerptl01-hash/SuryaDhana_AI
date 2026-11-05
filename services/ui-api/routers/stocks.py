"""Stock list and details: data completeness, fundamentals, history."""
import asyncio
import csv
import os
import re
from functools import lru_cache
from fastapi import APIRouter, HTTPException, Query

from errors import fail

from routers._upstream import upstream_detail
from datetime import date
import httpx
from db import get_conn

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")


def _parse_index_metadata(raw_index: str | None) -> dict:
    index_name = (raw_index or "").strip()
    # Split on "|" first so "NIFTY1000|NIFTYMIDCAP300" is handled correctly
    segments = [s.strip() for s in index_name.split("|")]

    nifty_bucket = None
    midcap_bucket = None

    for seg in segments:
        normalized = re.sub(r"[^A-Z0-9]", "", seg.upper())
        if m := re.match(r"^NIFTY(\d+)$", normalized):
            if nifty_bucket is None:
                nifty_bucket = m.group(1)
        if m := re.match(r"^NIFTYMIDCAP(\d+)$", normalized):
            if midcap_bucket is None:
                midcap_bucket = m.group(1)

    return {
        "index_name": index_name or None,
        "nifty_bucket": nifty_bucket,
        "midcap_bucket": midcap_bucket,
    }


@lru_cache(maxsize=1)
def _load_universe_metadata() -> dict[str, dict]:
    # Docker: WORKDIR=/app, data mounted at /app/data
    # Local dev: routers/ is under <project>/services/ui-api/routers/
    _here = os.path.dirname(os.path.abspath(__file__))
    _app_data  = os.path.join(_here, "..", "data")           # Docker: /app/data
    _proj_data = os.path.join(_here, "..", "..", "..", "data")  # Local: <project>/data
    candidates = [
        os.environ.get("STOCK_UNIVERSE_PATH", "").strip(),
        os.path.join(_app_data,  "NSE_1500.csv"),
        os.path.join(_proj_data, "NSE_1500.csv"),
        os.path.join(_app_data,  "NSE_1000_MIDCAP_500.csv"),
        os.path.join(_proj_data, "NSE_1000_MIDCAP_500.csv"),
        os.path.join(_app_data,  "nifty500_universe.csv"),
        os.path.join(_proj_data, "nifty500_universe.csv"),
    ]

    metadata: dict[str, dict] = {}
    seen_paths: set[str] = set()
    for path in candidates:
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        if not os.path.exists(path):
            continue

        with open(path, newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                ticker = (row.get("ticker") or "").strip().upper()
                if not ticker or ticker in metadata:
                    continue  # first CSV wins — don't overwrite higher-priority source
                # Support both new format (isin) and old format (isec_code)
                isin = (row.get("isin") or row.get("isec_code") or "").strip() or None
                metadata[ticker] = {
                    "company_name": (row.get("company_name") or "").strip() or None,
                    "sector_name": (row.get("sector") or "").strip() or None,
                    "isin": isin,
                    "cap_category": (row.get("cap_category") or "").strip() or None,
                    **_parse_index_metadata(row.get("index")),
                }
    _fill_reference_names(metadata, [_app_data, _proj_data])
    return metadata


def _fill_reference_names(metadata: dict[str, dict], data_dirs: list[str]) -> None:
    """The universe CSV has company names / industries for only ~500 of 1,500 stocks. Fill the gaps from NSE's own
    reference files: reference/nse_industry.csv (name + industry, Nifty Total Market) and
    reference/nse_equity_list.csv (EQUITY_L.csv: every listed company's name)."""
    for d in data_dirs:
        ind_path = os.path.join(d, "reference", "nse_industry.csv")
        eq_path = os.path.join(d, "reference", "nse_equity_list.csv")
        if not os.path.exists(eq_path) and not os.path.exists(ind_path):
            continue
        if os.path.exists(ind_path):
            with open(ind_path, newline="") as fh:
                for row in csv.DictReader(fh):
                    sym = (row.get("Symbol") or "").strip().upper()
                    m = metadata.get(sym)
                    if m is None:
                        continue
                    if not m.get("company_name") or m["company_name"].upper() == sym:   # CSV stores the ticker as "name"
                        m["company_name"] = (row.get("Company Name") or "").strip() or None
                    if m.get("sector_name") in (None, "", "Unknown") and (row.get("Industry") or "").strip():
                        m["sector_name"] = row["Industry"].strip()
        if os.path.exists(eq_path):
            with open(eq_path, newline="") as fh:
                for row in csv.DictReader(fh):
                    sym = (row.get("SYMBOL") or "").strip().upper()
                    m = metadata.get(sym)
                    if m is not None and (not m.get("company_name") or m["company_name"].upper() == sym):
                        m["company_name"] = (row.get("NAME OF COMPANY") or "").strip() or None
        return


@router.get("/symbols")
async def list_symbols():
    """Lightweight symbol directory for the command bar's type-ahead: ticker, name, sector, cap. Local CSV only."""
    meta = _load_universe_metadata()
    return {"data": [{"t": t, "n": m.get("company_name") or t, "s": None if m.get("sector_name") in (None, "Unknown") else m["sector_name"], "c": m.get("cap_category")}
                     for t, m in sorted(meta.items())]}


@router.get("/list")
async def list_stocks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=2000),
    search: str = Query(None),
    cap_category: str = Query(None),
    nifty_bucket: str = Query(None),
    midcap_bucket: str = Query(None),
):
    """
    Paginated stock list sourced from the universe CSV (all stocks), with OHLCV
    stats and financial metrics attached where available.

    OHLCV + metrics data is fetched from data-service (/db/ohlcv-meta) instead
    of opening a second DuckDB connection — data-service holds the persistent
    RW lock on virtioFS (Docker Desktop Mac), so a concurrent RO connection
    always falls back to the empty in-memory stub.
    """
    try:
        # ── Step 1: Fetch OHLCV + metrics from data-service ───────────────────
        ohlcv_map: dict[str, dict] = {}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                resp = await client.get(f"{DATA_SVC}/db/ohlcv-meta")
            if resp.status_code == 200:
                rows = resp.json().get("data", [])
                ohlcv_map = {r["ticker"]: r for r in rows}
        except Exception:
            pass  # leave ohlcv_map empty — stocks will show "no_data"

        # ── Step 2: Merge universe CSV + OHLCV + metrics ──────────────────────
        universe_meta = _load_universe_metadata()

        all_stocks: list[dict] = []
        for ticker, meta in universe_meta.items():
            # Search filter (ticker or company name)
            if search:
                term = search.lower()
                if term not in ticker.lower() and term not in (meta.get("company_name") or "").lower():
                    continue

            # CSV-level filters
            if cap_category and meta.get("cap_category") != cap_category:
                continue
            if nifty_bucket and meta.get("nifty_bucket") != nifty_bucket:
                continue
            if midcap_bucket and meta.get("midcap_bucket") != midcap_bucket:
                continue

            stock: dict = {"ticker": ticker, **meta}

            ohlcv = ohlcv_map.get(ticker)
            if ohlcv:
                days_stale = ohlcv.get("days_since_update")
                if days_stale is None:
                    days_stale = 999
                density = ohlcv.get("data_density_pct") or 0.0
                behind = ohlcv.get("sessions_behind")
                stock.update({
                    "latest_price":     ohlcv.get("latest_price"),
                    "price_date":       ohlcv.get("price_date"),
                    "total_rows":       ohlcv.get("total_rows", 0),
                    "first_date":       ohlcv.get("first_date"),
                    "latest_date":      ohlcv.get("latest_date"),
                    "years_of_data":    ohlcv.get("years_of_data", 0),
                    "data_density_pct": density,
                    "days_since_update": days_stale,
                    "sessions_behind":  behind,
                    "data_quality":     _classify_quality(days_stale, density, behind),
                    "has_ohlcv":        True,
                    # financial metrics (may be None for unenriched tickers)
                    "cmp":          ohlcv.get("cmp"),
                    "pe_ratio":     ohlcv.get("pe_ratio"),
                    "mktcap_cr":    ohlcv.get("mktcap_cr"),
                    "div_yld_pct":  ohlcv.get("div_yld_pct"),
                    "np_qtr_cr":    ohlcv.get("np_qtr_cr"),
                    "qtr_pft_var":  ohlcv.get("qtr_pft_var"),
                    "sales_qtr_cr": ohlcv.get("sales_qtr_cr"),
                    "qtr_sal_var":  ohlcv.get("qtr_sal_var"),
                    "roce_pct":     ohlcv.get("roce_pct"),
                })
            else:
                stock.update({
                    "latest_price": None, "price_date": None,
                    "total_rows": 0, "first_date": None, "latest_date": None,
                    "years_of_data": 0, "data_density_pct": 0,
                    "days_since_update": None, "data_quality": "no_data",
                    "has_ohlcv": False,
                })

            all_stocks.append(stock)

        # Sort: stocks with OHLCV first, then by ticker
        all_stocks.sort(key=lambda s: (not s.get("has_ohlcv", False), s["ticker"]))

        total = len(all_stocks)
        paginated = all_stocks[skip: skip + limit]

        return {"total": total, "skip": skip, "limit": limit, "stocks": paginated}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/profile")
async def get_stock_profile(ticker: str):
    """Security page (DES): adjusted price stats, delivery, ownership, insiders, deals, F&O, MTF, events."""
    sym = ticker.upper().removesuffix(".NS")
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/security/{sym}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=r.json().get("detail", r.text[:200]) if r.headers.get(
            "content-type", "").startswith("application/json") else r.text[:200])
    return r.json()


@router.get("/{ticker}/results")
async def get_stock_results(ticker: str):
    """How the stock moved on each of its last 12 quarterly results (ERN). First call per week asks NSE (~2 s)."""
    sym = ticker.upper().removesuffix(".NS")
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/security/{sym}/results")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 200))
    return r.json()


@router.get("/{ticker}/pe-history")
async def get_stock_pe_history(ticker: str):
    """Point-in-time daily trailing P/E (GE) with its median and quartiles."""
    sym = ticker.upper().removesuffix(".NS")
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/security/{sym}/pe-history")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 200))
    return r.json()


@router.get("/{ticker}/actions")
async def get_stock_actions(ticker: str, years: int = 5):
    """Dividends, bonuses, splits, buybacks (DVD) and the TTM dividend yield."""
    sym = ticker.upper().removesuffix(".NS")
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/security/{sym}/actions", params={"years": max(1, min(years, 15))})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 200))
    return r.json()


@router.get("/{ticker}/history")
async def get_stock_history(ticker: str, days: int = 90):
    """HP: daily bars as traded with delivery %, change on adjusted closes, split / bonus ex-dates."""
    sym = ticker.upper().removesuffix(".NS")
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/security/{sym}/history", params={"days": max(5, min(days, 3700))})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 200))
    return r.json()


@router.get("/{ticker}/filings")
async def get_stock_filings(ticker: str, days: int = 30):
    """The company's NSE announcements (CN), last `days` days, categorised."""
    sym = ticker.upper().removesuffix(".NS")
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/security/{sym}/filings", params={"days": max(1, min(days, 365))})
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 200))
    return r.json()


@router.get("/{ticker}/financials")
async def get_stock_financials(ticker: str):
    """Quarterly revenue / profit / EPS from NSE results XBRL (FA). First call per company reads ~12 filings (~6 s)."""
    sym = ticker.upper().removesuffix(".NS")
    if not re.fullmatch(r"[A-Z0-9&\-]{1,20}", sym):
        raise HTTPException(status_code=422, detail="Bad symbol")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.get(f"{DATA_SVC}/db/security/{sym}/financials")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail=f"data-service unreachable: {exc}") from exc
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail=upstream_detail(r, 200))
    return r.json()


@router.get("/{ticker}/detail")
async def get_stock_detail(ticker: str):
    """
    Deep dive: data completeness + metrics for one ticker.

    Sourced from data-service `/db/ohlcv-meta` over HTTP — ui-api must NOT open
    its own DuckDB connection (virtioFS concurrent-lock on Docker Desktop Mac
    makes ui-api fall back to an empty in-memory stub, which previously made this
    endpoint 500 for every ticker). data-service owns the RW lock and the real data.
    """
    ticker = ticker.upper()

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
            resp = await client.get(f"{DATA_SVC}/db/ohlcv-meta")
        resp.raise_for_status()
        rows = resp.json().get("data", [])
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"data-service unreachable: {exc}")

    row = next((r for r in rows if str(r.get("ticker", "")).upper() == ticker), None)
    if row is None:
        fail(404, "not_found", f"Unknown ticker {ticker}",
             hint="Try the GO bar search — e.g. `TCS` or `GO TCS`")

    total_rows = int(row.get("total_rows") or 0)
    first_date = row.get("first_date")
    latest_date = row.get("latest_date")
    density = round(float(row.get("data_density_pct") or 0.0), 1)
    days_stale_raw = row.get("days_since_update")
    days_stale = int(days_stale_raw) if days_stale_raw is not None else None

    # Best-effort expected/missing trading-day estimate (~252 sessions/year).
    expected_rows: int | None = None
    missing_rows = 0
    try:
        if first_date and latest_date:
            fd = date.fromisoformat(str(first_date)[:10])
            ld = date.fromisoformat(str(latest_date)[:10])
            expected_rows = int((ld - fd).days * 252 / 365) or total_rows
            missing_rows = max(0, expected_rows - total_rows)
    except (ValueError, TypeError):
        pass

    pe = row.get("pe_ratio")
    div_yld_pct = row.get("div_yld_pct")
    mcap_cr = row.get("mktcap_cr")
    roce_pct = row.get("roce_pct")
    latest_price = row.get("latest_price") if row.get("latest_price") is not None else row.get("cmp")
    has_fund = any(v is not None for v in (pe, div_yld_pct, mcap_cr, roce_pct))

    return {
        "ticker": ticker,
        **_load_universe_metadata().get(ticker, {}),
        "ohlcv": {
            "total_rows": total_rows,
            "first_date": str(first_date) if first_date else None,
            "latest_date": str(latest_date) if latest_date else None,
            "expected_rows": expected_rows,
            "missing_rows": missing_rows,
            "data_density_pct": density,
            "avg_volume": None,
            "price_range": {"min": None, "max": None, "latest": latest_price},
        },
        "fundamentals": {
            "available": True,
            # Metrics sourced from stock_metrics (the live fundamentals table).
            "market_cap_cr": float(mcap_cr) if mcap_cr is not None else None,
            "trailing_pe": float(pe) if pe is not None else None,
            "price_to_book": None,
            "roe": None,                                  # not stored; ROCE != ROE
            "roce": float(roce_pct) if roce_pct is not None else None,
            "debt_to_equity": None,
            # modal renders dividend_yield as a fraction (×100); div_yld_pct is already a %.
            "dividend_yield": (float(div_yld_pct) / 100.0) if div_yld_pct is not None else None,
            "sector": None,
            "analyst_recommendation": None,
        } if has_fund else {"available": False},
        "dividends": {"count": 0},
        "splits": {"count": 0},
        "upcoming_events": [],
        "data_quality": {
            "overall": _classify_quality(days_stale if days_stale is not None else 999, density),
            "completeness_pct": density,
            "last_updated": str(latest_date) if latest_date else None,
            "days_since_update": days_stale if days_stale is not None else 0,
        },
    }


@router.get("/{ticker}/ohlcv")
async def get_stock_ohlcv(ticker: str, days: int = Query(90, ge=5, le=9999)):
    """
    Returns the last N trading days of OHLCV data for a ticker, sorted ascending.
    Used to render interactive price charts in the frontend.
    """
    # Production-review fix (contract C1, 14 Oct 2026): this route used to open DuckDB directly
    # (violating the data-service-owns-the-lock rule its own module header states) with the ticker
    # f-string-interpolated into SQL, and it returned 404 for every ticker because ui-api's local
    # connection does not see the live table. It now proxies data-service /ohlcv/{ticker}, which
    # owns the lock, and keeps the exact response shape the frontend chart expects.
    ticker = ticker.upper()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(f"{DATA_SVC}/ohlcv/{ticker}")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"data-service OHLCV unavailable: {exc}")
    # D7: an unknown ticker is NOT an upstream failure. The old raise_for_status() turned the
    # upstream 404 into `upstream_down` and leaked the internal URL (+ MDN link) on the wire.
    if resp.status_code == 404:
        fail(404, "not_found", f"No OHLCV data for {ticker}",
             hint="Try the GO bar search — e.g. `TCS` or `GO TCS`")
    if resp.status_code >= 400:  # real upstream trouble — surface its detail, never its URL
        raise HTTPException(status_code=502,
                            detail=f"data-service OHLCV error ({resp.status_code}): {upstream_detail(resp, 200)}")
    try:
        data = resp.json().get("data") or []
    except ValueError:
        raise HTTPException(status_code=502, detail="data-service OHLCV returned non-JSON")
    if not data:
        fail(404, "not_found", f"No OHLCV data for {ticker}",
             hint="Try the GO bar search — e.g. `TCS` or `GO TCS`")
    rows = data[-days:]                                   # data arrives oldest-first
    return {
        "ticker": ticker,
        "days": len(rows),
        "rows": [
            {
                "date": str(r.get("date")),
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": int(r.get("volume") or 0),
            }
            for r in rows
        ],
    }


@router.get("/screener")
async def screener(
    t1: bool = Query(False),
    t2: bool = Query(False),
    t3: bool = Query(False),
    t4: bool = Query(False),
    t5: bool = Query(False),
    t6: bool = Query(False),
    t7: bool = Query(False),
    t8: bool = Query(False),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """
    T1-T8 Minervini TREND TEMPLATE screener + SEPA stage classification.

    T1: Price > 150-day & 200-day MA
    T2: 150-day MA > 200-day MA
    T3: 200-day MA trending upward ≥1 month
    T4: 50-day MA > 150-day & 200-day MA
    T5: Price > 50-day MA
    T6: Price ≥30% above 52-week low
    T7: Price within 25% of 52-week high
    T8: Relative Strength (RS) ≥70 vs Nifty 500
    """
    # Delegate screener to data-service to avoid DuckDB concurrent-lock
    try:
        params = {
            "t1": t1, "t2": t2, "t3": t3, "t4": t4,
            "t5": t5, "t6": t6, "t7": t7, "t8": t8,
            "skip": skip, "limit": limit,
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.get(f"{DATA_SVC}/db/screener", params=params)
        if resp.status_code == 200:
            return resp.json()
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Legacy DuckDB path (unreachable — the delegate above always returns or raises;
    # kept for reference). Off the event loop per design review A3: the full-universe
    # window-function scan takes seconds and would freeze every other request.
    return await asyncio.to_thread(
        _screener_legacy_duckdb, t1, t2, t3, t4, t5, t6, t7, t8, skip, limit
    )


def _screener_legacy_duckdb(
    t1: bool, t2: bool, t3: bool, t4: bool, t5: bool, t6: bool, t7: bool, t8: bool,
    skip: int, limit: int,
) -> dict:
    """Legacy local-DuckDB screener. Sync — only ever call via asyncio.to_thread (A3)."""
    with get_conn() as conn:
        try:
            # Compute all technical indicators via SQL window functions
            sql = """
            WITH recent_ohlcv AS (
                SELECT ticker, date, close
                FROM ohlcv
                WHERE ticker != 'NIFTY500'
                QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) <= 260
            ),
            stock_ma AS (
                SELECT
                    ticker,
                    date,
                    close,
                    AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) as ma50,
                    AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) as ma150,
                    AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) as ma200,
                    MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) as high52w,
                    MIN(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) as low52w,
                    LAG(close, 63)  OVER (PARTITION BY ticker ORDER BY date) as close_3m_ago,
                    LAG(close, 126) OVER (PARTITION BY ticker ORDER BY date) as close_6m_ago,
                    LAG(close, 189) OVER (PARTITION BY ticker ORDER BY date) as close_9m_ago,
                    LAG(close, 252) OVER (PARTITION BY ticker ORDER BY date) as close_12m_ago,
                    ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                FROM recent_ohlcv
            ),
            stock_with_history AS (
                SELECT *,
                    LAG(ma200, 30) OVER (PARTITION BY ticker ORDER BY date) as ma200_1m_ago
                FROM stock_ma
            ),
            latest_stats AS (
                SELECT
                    ticker,
                    date,
                    close,
                    ma50, ma150, ma200, high52w, low52w,
                    close_3m_ago, close_6m_ago, close_9m_ago, close_12m_ago,
                    ma200_1m_ago,
                    (close > ma150 AND close > ma200) as t1_pass,
                    (ma150 > ma200) as t2_pass,
                    (ma200 > COALESCE(ma200_1m_ago, ma200)) as t3_pass,
                    (ma50 > ma150 AND ma50 > ma200) as t4_pass,
                    (close > ma50) as t5_pass,
                    (close >= low52w * 1.30) as t6_pass,
                    (close >= high52w * 0.75) as t7_pass,
                    (CASE
                        WHEN (close > ma50) AND (ma50 > ma150) AND (ma150 > ma200) THEN 'Stage 3: Uptrend'
                        WHEN (close > ma200) AND (ma150 > ma200) AND (ma50 < ma150) THEN 'Stage 2: Breakout'
                        WHEN (close < ma200) OR (ma150 < ma200) THEN 'Stage 4: Decline'
                        ELSE 'Stage 1: Base'
                    END) as sepa_stage
                FROM stock_with_history
                WHERE rn = 1
            ),
            rs_scores AS (
                SELECT
                    ticker,
                    (0.4 * COALESCE((close - close_3m_ago)  / NULLIF(close_3m_ago,  0), 0)
                   + 0.2 * COALESCE((close - close_6m_ago)  / NULLIF(close_6m_ago,  0), 0)
                   + 0.2 * COALESCE((close - close_9m_ago)  / NULLIF(close_9m_ago,  0), 0)
                   + 0.2 * COALESCE((close - close_12m_ago) / NULLIF(close_12m_ago, 0), 0)) as composite_rs
                FROM latest_stats
            ),
            rs_ranked AS (
                SELECT
                    ticker,
                    GREATEST(1, LEAST(99,
                        CAST(PERCENT_RANK() OVER (ORDER BY composite_rs) * 98 + 1 AS INTEGER)
                    )) as rs_rating
                FROM rs_scores
            )
            SELECT
                s.ticker,
                s.close as latest_price,
                s.date as price_date,
                s.ma50, s.ma150, s.ma200,
                s.high52w, s.low52w,
                COALESCE(r.rs_rating, 50) as rs_rating,
                COALESCE(s.t1_pass, FALSE) as t1,
                COALESCE(s.t2_pass, FALSE) as t2,
                COALESCE(s.t3_pass, FALSE) as t3,
                COALESCE(s.t4_pass, FALSE) as t4,
                COALESCE(s.t5_pass, FALSE) as t5,
                COALESCE(s.t6_pass, FALSE) as t6,
                COALESCE(s.t7_pass, FALSE) as t7,
                (COALESCE(r.rs_rating, 0) >= 70) as t8,
                s.sepa_stage
            FROM latest_stats s
            LEFT JOIN rs_ranked r ON s.ticker = r.ticker
            """

            # Apply filter conditions
            filters = []
            if t1: filters.append("t1 = true")
            if t2: filters.append("t2 = true")
            if t3: filters.append("t3 = true")
            if t4: filters.append("t4 = true")
            if t5: filters.append("t5 = true")
            if t6: filters.append("t6 = true")
            if t7: filters.append("t7 = true")
            if t8: filters.append("t8 = true")

            where_clause = ""
            if filters:
                where_clause = f" WHERE {' AND '.join(filters)}"

            # Count total
            count_sql = f"SELECT COUNT(*) FROM ({sql}) screened{where_clause}"
            total = conn.execute(count_sql).fetchone()[0]

            # Get paginated results
            final_sql = f"SELECT * FROM ({sql}) screened{where_clause} ORDER BY ticker LIMIT {limit} OFFSET {skip}"
            rows = conn.execute(final_sql).fetchall()

            results = [
                {
                    "ticker": r[0],
                    "latest_price": float(r[1]),
                    "price_date": str(r[2]),
                    "ma50": float(r[3]) if r[3] else None,
                    "ma150": float(r[4]) if r[4] else None,
                    "ma200": float(r[5]) if r[5] else None,
                    "high52w": float(r[6]) if r[6] else None,
                    "low52w": float(r[7]) if r[7] else None,
                    "rs_rating": int(r[8]),
                    "filters": {
                        "t1": bool(r[9]),
                        "t2": bool(r[10]),
                        "t3": bool(r[11]),
                        "t4": bool(r[12]),
                        "t5": bool(r[13]),
                        "t6": bool(r[14]),
                        "t7": bool(r[15]),
                        "t8": bool(r[16]),
                    },
                    "sepa_stage": r[17],
                }
                for r in rows
            ]

            return {"total": total, "skip": skip, "limit": limit, "results": results}

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


def _classify_quality(days_stale: int, density: float, sessions_behind: int | None = None) -> str:
    """Classify data quality: excellent/good/fair/poor.

    When ``sessions_behind`` (trading sessions behind the newest DB session) is known it
    replaces calendar-day staleness, so Friday's close still reads as current on Sunday.
    """
    if sessions_behind is not None:
        # map sessions onto the calendar-day thresholds below: 0 → 0d, 1 → 2d, 2-3 → ≤4d …
        days_stale = 0 if sessions_behind == 0 else sessions_behind + 1
    if days_stale > 7 or density < 80:
        return "poor"
    if days_stale > 3 or density < 90:
        return "fair"
    if days_stale > 1 or density < 95:
        return "good"
    return "excellent"
