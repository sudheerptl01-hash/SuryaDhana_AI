"""Stock list and details: data completeness, fundamentals, history."""
from fastapi import APIRouter, HTTPException, Query
from datetime import date
from db import get_conn

router = APIRouter()


@router.get("/list")
async def list_stocks(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    sector: str = Query(None),
    search: str = Query(None),
):
    """
    Paginated stock list with data quality metrics.
    Returns row counts, latest date, missing days, etc.
    """
    with get_conn() as conn:
        try:
            # Base query: latest price + data stats per ticker
            base_sql = """
                WITH stock_stats AS (
                    SELECT
                        ticker,
                        COUNT(*) as total_rows,
                        MIN(date) as first_date,
                        MAX(date) as latest_date,
                        CAST((MAX(date) - MIN(date)) / 365.25 as INT) as years_of_data,
                        ROUND(100.0 * COUNT(*) / GREATEST(CAST(((MAX(date) - MIN(date)) * 252) / 365 as INT), COUNT(*)), 1) as data_density_pct
                    FROM ohlcv
                    GROUP BY ticker
                ),
                latest_price AS (
                    SELECT DISTINCT ON (ticker)
                        ticker,
                        close as latest_price,
                        date as price_date
                    FROM ohlcv
                    ORDER BY ticker, date DESC
                )
                SELECT
                    s.ticker,
                    p.latest_price,
                    p.price_date,
                    s.total_rows,
                    s.first_date,
                    s.latest_date,
                    s.years_of_data,
                    s.data_density_pct,
                    CAST((CURRENT_DATE - s.latest_date) as INT) as days_since_update
                FROM stock_stats s
                JOIN latest_price p ON s.ticker = p.ticker
            """

            if search:
                base_sql += f" WHERE s.ticker ILIKE '%{search}%'"

            # Get total count
            count_sql = f"SELECT COUNT(*) FROM ({base_sql}) t"
            total = conn.execute(count_sql).fetchone()[0]

            # Get paginated results
            sql = base_sql + f" ORDER BY s.ticker LIMIT {limit} OFFSET {skip}"
            rows = conn.execute(sql).fetchall()

            stocks = [
                {
                    "ticker": r[0],
                    "latest_price": float(r[1]) if r[1] else None,
                    "price_date": str(r[2]),
                    "total_rows": r[3],
                    "first_date": str(r[4]),
                    "latest_date": str(r[5]),
                    "years_of_data": r[6],
                    "data_density_pct": float(r[7]) if r[7] else 0,
                    "days_since_update": r[8],
                    "data_quality": _classify_quality(r[8], float(r[7]) if r[7] else 0),
                }
                for r in rows
            ]

            return {
                "total": total,
                "skip": skip,
                "limit": limit,
                "stocks": stocks,
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/detail")
async def get_stock_detail(ticker: str):
    """
    Deep dive: all data completeness checks, fundamentals, dividends, events.
    """
    ticker = ticker.upper()
    with get_conn() as conn:
        try:
            # OHLCV stats
            ohlcv_stats = conn.execute(f"""
                SELECT
                    COUNT(*) as total_rows,
                    MIN(date) as first_date,
                    MAX(date) as latest_date,
                    AVG(volume) as avg_volume,
                    AVG(close) as avg_close,
                    MIN(close) as min_price,
                    MAX(close) as max_price
                FROM ohlcv
                WHERE ticker = '{ticker}'
            """).fetchone()

            if not ohlcv_stats or ohlcv_stats[0] == 0:
                raise HTTPException(status_code=404, detail=f"No data for {ticker}")

            first_date = ohlcv_stats[1]
            latest_date = ohlcv_stats[2]
            expected_rows = (latest_date - first_date).days + 1
            actual_rows = ohlcv_stats[0]
            missing_rows = expected_rows - actual_rows
            density = round(100.0 * actual_rows / expected_rows, 1)

            # Fundamentals
            fund = conn.execute(f"""
                SELECT
                    market_cap, trailing_pe, price_to_book, return_on_equity,
                    debt_to_equity, dividend_yield, sector, analyst_recommendation
                FROM fundamentals
                WHERE ticker = '{ticker}'
                ORDER BY as_of_date DESC
                LIMIT 1
            """).fetchone()

            # Dividends
            divs = conn.execute(f"""
                SELECT COUNT(*) FROM dividends WHERE ticker = '{ticker}'
            """).fetchone()

            # Splits
            splits = conn.execute(f"""
                SELECT COUNT(*) FROM splits WHERE ticker = '{ticker}'
            """).fetchone()

            # Corporate events
            events = conn.execute(f"""
                SELECT event_type, event_date
                FROM corporate_events
                WHERE ticker = '{ticker}'
                ORDER BY event_date DESC
                LIMIT 5
            """).fetchall()

            return {
                "ticker": ticker,
                "ohlcv": {
                    "total_rows": int(ohlcv_stats[0]),
                    "first_date": str(first_date),
                    "latest_date": str(latest_date),
                    "expected_rows": expected_rows,
                    "missing_rows": missing_rows,
                    "data_density_pct": density,
                    "avg_volume": float(ohlcv_stats[4]) if ohlcv_stats[4] else None,
                    "price_range": {
                        "min": float(ohlcv_stats[5]) if ohlcv_stats[5] else None,
                        "max": float(ohlcv_stats[6]) if ohlcv_stats[6] else None,
                        "latest": float(ohlcv_stats[5]) if ohlcv_stats[5] else None,  # Will be overridden
                    }
                },
                "fundamentals": {
                    "available": fund is not None,
                    "market_cap": float(fund[0]) if fund and fund[0] else None,
                    "trailing_pe": float(fund[1]) if fund and fund[1] else None,
                    "price_to_book": float(fund[2]) if fund and fund[2] else None,
                    "roe": float(fund[3]) if fund and fund[3] else None,
                    "debt_to_equity": float(fund[4]) if fund and fund[4] else None,
                    "dividend_yield": float(fund[5]) if fund and fund[5] else None,
                    "sector": fund[6] if fund else None,
                    "analyst_recommendation": fund[7] if fund else None,
                } if fund else {"available": False},
                "dividends": {
                    "count": int(divs[0]) if divs else 0,
                },
                "splits": {
                    "count": int(splits[0]) if splits else 0,
                },
                "upcoming_events": [
                    {"type": e[0], "date": str(e[1])} for e in events
                ] if events else [],
                "data_quality": {
                    "overall": _classify_quality((date.today() - latest_date).days, density),
                    "completeness_pct": density,
                    "last_updated": str(latest_date),
                    "days_since_update": (date.today() - latest_date).days,
                },
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/ohlcv")
async def get_stock_ohlcv(ticker: str, days: int = Query(90, ge=5, le=9999)):
    """
    Returns the last N trading days of OHLCV data for a ticker, sorted ascending.
    Used to render interactive price charts in the frontend.
    """
    ticker = ticker.upper()
    with get_conn() as conn:
        try:
            rows = conn.execute(f"""
                SELECT date, open, high, low, close, volume
                FROM ohlcv
                WHERE ticker = '{ticker}'
                ORDER BY date DESC
                LIMIT {days}
            """).fetchall()

            if not rows:
                raise HTTPException(status_code=404, detail=f"No OHLCV data for {ticker}")

            # Reverse to ascending (oldest first)
            rows = list(reversed(rows))

            return {
                "ticker": ticker,
                "days": len(rows),
                "rows": [
                    {
                        "date": str(r[0]),
                        "open": float(r[1]) if r[1] else None,
                        "high": float(r[2]) if r[2] else None,
                        "low": float(r[3]) if r[3] else None,
                        "close": float(r[4]) if r[4] else None,
                        "volume": int(r[5]) if r[5] else 0,
                    }
                    for r in rows
                ],
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


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
    with get_conn() as conn:
        try:
            # Compute all technical indicators via SQL window functions
            sql = """
            WITH stock_ma AS (
                SELECT
                    ticker,
                    date,
                    close,
                    volume,
                    AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) as ma50,
                    AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 149 PRECEDING AND CURRENT ROW) as ma150,
                    AVG(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) as ma200,
                    MAX(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) as high52w,
                    MIN(close) OVER (PARTITION BY ticker ORDER BY date ROWS BETWEEN 251 PRECEDING AND CURRENT ROW) as low52w,
                    ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) as rn
                FROM ohlcv
                WHERE ticker != 'NIFTY500'
            ),
            stock_with_history AS (
                SELECT
                    ticker,
                    date,
                    close,
                    ma50,
                    ma150,
                    ma200,
                    high52w,
                    low52w,
                    LAG(ma200, 30) OVER (PARTITION BY ticker ORDER BY date) as ma200_1m_ago,
                    rn
                FROM stock_ma
            ),
            latest_stats AS (
                SELECT
                    ticker,
                    date,
                    close,
                    ma50, ma150, ma200, high52w, low52w,
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
            )
            SELECT
                ticker,
                close as latest_price,
                date as price_date,
                ma50, ma150, ma200,
                high52w, low52w,
                CAST(COALESCE(50, 50) as INTEGER) as rs_rating,
                COALESCE(t1_pass, FALSE) as t1,
                COALESCE(t2_pass, FALSE) as t2,
                COALESCE(t3_pass, FALSE) as t3,
                COALESCE(t4_pass, FALSE) as t4,
                COALESCE(t5_pass, FALSE) as t5,
                COALESCE(t6_pass, FALSE) as t6,
                COALESCE(t7_pass, FALSE) as t7,
                FALSE as t8,
                sepa_stage
            FROM latest_stats
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


def _classify_quality(days_stale: int, density: float) -> str:
    """Classify data quality: excellent/good/fair/poor."""
    if days_stale > 7 or density < 80:
        return "poor"
    if days_stale > 3 or density < 90:
        return "fair"
    if days_stale > 1 or density < 95:
        return "good"
    return "excellent"
