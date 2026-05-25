"""Dashboard summary: KPIs, portfolio health, system status."""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
from datetime import date, timedelta
import csv
import os
import httpx
from db import get_conn

router = APIRouter()

# In-memory progress: ticker -> "pending" | "downloading" | "done" | "error"
_refresh_progress: dict[str, str] = {}
_refresh_active: bool = False
_refresh_meta: dict[str, str | int] = {}


class RefreshRequest(BaseModel):
    universe: str = "nse_1000_midcap_500"
    years: int = 5


def _resolve_universe_path(universe: str) -> tuple[str, str]:
    mapping = {
        "configured": os.environ.get("STOCK_UNIVERSE_PATH", "data/FINAL_100_STOCKS.csv"),
        "final_100": "data/FINAL_100_STOCKS.csv",
        "nse_1000_midcap_500": "data/NSE_1000_MIDCAP_500.csv",
    }
    selected = mapping.get(universe, mapping["nse_1000_midcap_500"])
    label = universe if universe in mapping else "nse_1000_midcap_500"
    return selected, label


@router.get("/summary")
async def get_dashboard_summary():
    """Overview: total stocks, data freshness, portfolio snapshot."""
    with get_conn() as conn:
        try:
            # Stock universe stats
            total_stocks = conn.execute("SELECT COUNT(DISTINCT ticker) FROM ohlcv").fetchone()[0]
            stocks_today = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM ohlcv WHERE date = (SELECT MAX(date) FROM ohlcv)"
            ).fetchone()[0]

            # Data freshness
            latest_date = conn.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]
            today = date.today()
            days_stale = (today - latest_date).days if latest_date else None

            # Date range
            min_date = conn.execute("SELECT MIN(date) FROM ohlcv").fetchone()[0]
            max_date = conn.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]

            return {
                "total_stocks": total_stocks,
                "stocks_with_today_data": stocks_today,
                "latest_date": str(latest_date),
                "days_stale": days_stale,
                "data_range": {
                    "from": str(min_date),
                    "to": str(max_date),
                    "trading_days": None  # Calculated by frontend
                },
                "health": {
                    "status": "healthy" if days_stale <= 1 else ("warning" if days_stale <= 3 else "stale"),
                    "freshness_pct": max(0, 100 - (days_stale or 100) * 25) if days_stale else 100
                }
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


async def _do_refresh_background(universe_path: str, years: int, universe_label: str):
    """Download OHLCV for every universe stock with concurrent batching and per-batch timeouts."""
    global _refresh_active, _refresh_progress, _refresh_meta
    import asyncio

    tickers: list[str] = []
    try:
        with open(universe_path, newline="") as f:
            reader = csv.DictReader(f)
            tickers = [row["ticker"] for row in reader if row.get("ticker")]
    except Exception:
        with get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT ticker FROM ohlcv ORDER BY ticker").fetchall()
            tickers = [r[0] for r in rows]

    if not tickers:
        _refresh_active = False
        return

    _refresh_progress = {t: "pending" for t in tickers}
    _refresh_active = True

    data_service_url = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
    _refresh_meta = {
        "universe": universe_label,
        "universe_path": universe_path,
        "years": years,
    }

    # Smaller batches for finer-grained progress + up to 10 concurrent batches
    batch_size = 10
    batches = [tickers[i : i + batch_size] for i in range(0, len(tickers), batch_size)]
    semaphore = asyncio.Semaphore(10)

    async def _fetch_batch(client: httpx.AsyncClient, batch: list[str]) -> None:
        for t in batch:
            _refresh_progress[t] = "downloading"
        async with semaphore:
            try:
                resp = await client.post(
                    f"{data_service_url}/fetch/refresh-batch",
                    json={"tickers": batch, "years": years},
                    timeout=30.0,
                )
                result = resp.json() if resp.status_code == 200 else {}
                errors = result.get("errors", [])
                failed = {e.split(":")[0].strip() for e in errors if ":" in e}
                for t in batch:
                    _refresh_progress[t] = "error" if t in failed else "done"
            except Exception:
                for t in batch:
                    _refresh_progress[t] = "error"

    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0)) as client:
        await asyncio.gather(*[_fetch_batch(client, b) for b in batches])

    _refresh_active = False


@router.post("/refresh")
async def trigger_refresh(background_tasks: BackgroundTasks, req: RefreshRequest | None = None):
    """Kick off a background OHLCV refresh for all universe stocks. Returns immediately."""
    global _refresh_active
    if _refresh_active:
        return {
            "status": "already_running",
            "tickers": len(_refresh_progress),
            **_refresh_meta,
        }

    request = req or RefreshRequest()
    universe_path, universe_label = _resolve_universe_path(request.universe)

    count = 0
    try:
        with open(universe_path, newline="") as f:
            reader = csv.DictReader(f)
            count = sum(1 for row in reader if row.get("ticker"))
    except Exception:
        with get_conn() as conn:
            count = conn.execute("SELECT COUNT(DISTINCT ticker) FROM ohlcv").fetchone()[0]

    background_tasks.add_task(_do_refresh_background, universe_path, request.years, universe_label)
    return {
        "status": "refresh_started",
        "tickers": count,
        "universe": universe_label,
        "universe_path": universe_path,
        "years": request.years,
    }


@router.get("/refresh-status")
async def get_refresh_status():
    """Real-time per-ticker download progress."""
    total = len(_refresh_progress)
    done = sum(1 for s in _refresh_progress.values() if s == "done")
    downloading = sum(1 for s in _refresh_progress.values() if s == "downloading")
    pending = sum(1 for s in _refresh_progress.values() if s == "pending")
    errors = sum(1 for s in _refresh_progress.values() if s == "error")
    return {
        "active": _refresh_active,
        "total": total,
        "done": done,
        "downloading": downloading,
        "pending": pending,
        "errors": errors,
        "pct": round(done / total * 100, 1) if total else 0,
        "tickers": _refresh_progress,
        **_refresh_meta,
    }


@router.get("/staleness")
async def get_staleness():
    """Per-ticker data staleness — which stocks need a refresh."""
    with get_conn() as conn:
        try:
            rows = conn.execute("""
                SELECT
                    ticker,
                    MAX(date) as latest_date,
                    COUNT(*) as total_rows,
                    CAST(CURRENT_DATE - MAX(date) AS INTEGER) as days_stale
                FROM ohlcv
                GROUP BY ticker
                ORDER BY days_stale DESC, ticker
            """).fetchall()

            result = []
            for r in rows:
                days = int(r[3]) if r[3] is not None else 999
                status = "fresh" if days <= 1 else ("stale" if days <= 7 else "very_stale")
                result.append({
                    "ticker": r[0],
                    "latest_date": str(r[1]),
                    "total_rows": int(r[2]),
                    "days_stale": days,
                    "status": status,
                })

            fresh = sum(1 for r in result if r["status"] == "fresh")
            stale = sum(1 for r in result if r["status"] == "stale")
            very_stale = sum(1 for r in result if r["status"] == "very_stale")

            return {
                "summary": {"fresh": fresh, "stale": stale, "very_stale": very_stale, "total": len(result)},
                "tickers": result,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/enrichment-status")
async def get_enrichment_status():
    """Which stocks have fundamentals/dividends/splits data."""
    with get_conn() as conn:
        try:
            # Counts by table
            total = conn.execute("SELECT COUNT(DISTINCT ticker) FROM ohlcv").fetchone()[0]
            with_fund = conn.execute("SELECT COUNT(DISTINCT ticker) FROM fundamentals").fetchone()[0]
            with_div = conn.execute("SELECT COUNT(DISTINCT ticker) FROM dividends").fetchone()[0]
            with_split = conn.execute("SELECT COUNT(DISTINCT ticker) FROM splits").fetchone()[0]

            return {
                "total_stocks": total,
                "with_fundamentals": with_fund,
                "with_dividends": with_div,
                "with_splits": with_split,
                "enrichment_coverage_pct": round(with_fund / total * 100, 1) if total else 0,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
