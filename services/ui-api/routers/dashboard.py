"""Dashboard: KPIs, data refresh, portfolio health, system status."""
from __future__ import annotations

import csv
import io
import os
import asyncio
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from db import get_conn

router = APIRouter()

# ── In-memory refresh state ────────────────────────────────────────────────────
_refresh_progress: dict[str, str] = {}
_refresh_active: bool = False
_refresh_meta: dict = {}


# ── Path helpers ───────────────────────────────────────────────────────────────

def _get_data_dir() -> Path:
    """Resolve the data directory regardless of Docker vs local dev."""
    db_url = os.environ.get("DATABASE_URL", "")
    if db_url:
        return Path(db_url).parent
    # Local dev: routers/ → ui-api/ → services/ → project root → data/
    return Path(__file__).resolve().parents[3] / "data"


def _resolve_universe_path(universe: str = "") -> tuple[Optional[str], str]:
    """
    Auto-discover the best available universe CSV.
    Preference order: NSE_1500 > NSE_1000_MIDCAP_500 > nifty500_universe.
    Returns (absolute_path_or_None, label).
    """
    data_dir = _get_data_dir()

    # Preference: NSE_1500 → NSE_1000 → nifty500 (fallback only)
    candidates = [
        (data_dir / "NSE_1500.csv",            "nse_1500"),
        (data_dir / "NSE_1000_MIDCAP_500.csv", "nse_1000"),
        (data_dir / "nifty500_universe.csv",   "nse_500"),
    ]

    # If caller specified an exact universe, try that first
    explicit: dict[str, Path] = {
        "nse_1500":  data_dir / "NSE_1500.csv",
        "nse_1000":  data_dir / "NSE_1000_MIDCAP_500.csv",
        "nse_500":   data_dir / "nifty500_universe.csv",
        # Legacy aliases
        "nse_1000_midcap_500": data_dir / "NSE_1000_MIDCAP_500.csv",
        "nifty500":            data_dir / "nifty500_universe.csv",
    }
    if universe in explicit and explicit[universe].exists():
        return str(explicit[universe]), universe

    # Auto-discover best available
    for path, label in candidates:
        if path.exists():
            return str(path), label

    return None, ""


def _load_tickers_from_csv(universe_path: str) -> list[str]:
    try:
        with open(universe_path, newline="") as f:
            reader = csv.DictReader(f)
            return [row["ticker"].strip() for row in reader if row.get("ticker", "").strip()]
    except Exception:
        return []


def _load_tickers_from_db() -> list[str]:
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT ticker FROM ohlcv ORDER BY ticker"
            ).fetchall()
            return [r[0] for r in rows]
    except Exception:
        return []


# ── Bootstrap: fetch Nifty 500 from NSE if no CSV exists ──────────────────────

NSE_INDEX_BASE = "https://niftyindices.com/IndexConstituent"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://www.niftyindices.com/",
}


async def _fetch_nse_index_csv(filename: str) -> list[dict]:
    """Download one NSE constituent CSV from niftyindices.com. Returns rows list."""
    url = f"{NSE_INDEX_BASE}/{filename}"
    async with httpx.AsyncClient(timeout=20, headers=NSE_HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        reader = csv.DictReader(io.StringIO(resp.text))
        index_label = filename.replace("ind_", "").replace("list.csv", "").upper()
        rows = []
        for row in reader:
            series = row.get("Series", "").strip()
            symbol = row.get("Symbol", "").strip()
            if series == "EQ" and symbol:
                rows.append({
                    "ticker":       symbol,
                    "company_name": row.get("Company Name", symbol).strip(),
                    "sector":       row.get("Industry", "Unknown").strip(),
                    "isin":         row.get("ISIN Code", "").strip(),
                    "index":        index_label,
                    "cap_category": "Large Cap",  # overridden by caller when needed
                })
        return rows


# ── Refresh background worker ──────────────────────────────────────────────────

class RefreshRequest(BaseModel):
    universe: str = "nse_1500"   # NSE_1500.csv preferred; falls back to nse_1000 or nifty500
    years: int = 5
    tickers: list[str] = []      # when provided, refresh ONLY these (e.g. the watchlist) — skips the full universe


async def _do_refresh_background(
    tickers: list[str],
    years: int,
    universe_label: str,
) -> None:
    """
    Smart incremental OHLCV refresh.

    - Tickers with NO data in DB  → full 5-year fetch via data-service
    - Tickers with STALE data     → delta fetch (last_date+1 → today)
    - Tickers already current     → skipped

    All actual downloading happens inside data-service, which uses yfinance
    with .NS suffix for real NSE data (or ICICI Breeze when configured).
    """
    global _refresh_active, _refresh_progress, _refresh_meta

    _refresh_active = True
    _refresh_progress = {t: "pending" for t in tickers}

    data_service_url = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")

    # Batch size 5, max 3 concurrent — avoids yfinance 429 rate-limits
    batch_size = 5
    semaphore = asyncio.Semaphore(3)
    batches = [tickers[i: i + batch_size] for i in range(0, len(tickers), batch_size)]

    async def _fetch_batch(client: httpx.AsyncClient, batch: list[str]) -> None:
        for t in batch:
            _refresh_progress[t] = "downloading"
        async with semaphore:
            for attempt in range(2):
                try:
                    resp = await client.post(
                        f"{data_service_url}/fetch/refresh-batch",
                        json={"tickers": batch, "years": years},
                        timeout=120.0,
                    )
                    if resp.status_code != 200:
                        raise RuntimeError(f"refresh-batch HTTP {resp.status_code}")
                    result = resp.json()
                    statuses = result.get("statuses", {})
                    errors = result.get("errors", [])
                    failed = {e.split(":")[0].strip() for e in errors if ":" in e}
                    for t in batch:
                        s = statuses.get(t.upper())
                        if s == "current":
                            _refresh_progress[t] = "current"  # Yahoo confirmed nothing new
                        elif s in ("updated", "backfilled", "readjusted"):
                            _refresh_progress[t] = "done"
                        elif s == "no_data" or t in failed or s == "error":
                            _refresh_progress[t] = "error"   # never report "current" on an empty fetch
                        else:
                            _refresh_progress[t] = "done"
                    return
                except Exception:
                    if attempt == 0:
                        await asyncio.sleep(3)
                    else:
                        for t in batch:
                            _refresh_progress[t] = "error"

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        await asyncio.gather(*[_fetch_batch(client, b) for b in batches])

    _refresh_active = False


# ── Endpoints ──────────────────────────────────────────────────────────────────

_EMPTY_SUMMARY = {
    "total_stocks":           0,
    "stocks_with_today_data": 0,
    "latest_date":            None,
    "days_stale":             None,
    "data_range":             {"from": None, "to": None},
    "health":                 {"status": "empty", "freshness_pct": 0},
}


DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")


@router.get("/summary")
async def get_dashboard_summary():
    """
    Landing page KPIs: stock counts, per-ticker freshness buckets,
    enrichment coverage, data range.

    Delegates DuckDB reads to data-service over HTTP to avoid the
    virtioFS concurrent-lock limitation on Docker Desktop Mac
    (data-service holds the persistent RW connection).
    """
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(f"{DATA_SVC}/db/stats")
        if resp.status_code != 200:
            return {**_EMPTY_SUMMARY}

        stats = resp.json()
        total_stocks = stats.get("total_stocks", 0)

        if total_stocks == 0:
            return {**_EMPTY_SUMMARY}

        # Universe size from best CSV
        universe_path, universe_label = _resolve_universe_path()
        universe_size = len(_load_tickers_from_csv(universe_path)) if universe_path else 0

        return {
            "total_stocks":   total_stocks,
            "universe_size":  universe_size,
            "universe_label": universe_label or "none",
            "coverage_pct":   round(total_stocks / universe_size * 100, 1) if universe_size else 0,
            "latest_date":    stats.get("latest_date"),
            "days_stale":     stats.get("days_stale"),
            "data_range":     stats.get("data_range", {}),
            "freshness":      stats.get("freshness", {}),
            "enrichment":     stats.get("enrichment", {}),
            "health":         stats.get("health", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/bootstrap-universe")
async def bootstrap_universe():
    """
    Cold-start bootstrap: fetch NSE 1500 constituent list from niftyindices.com.

    Pulls all 9 named index CSVs (Nifty 500, LargeMidcap 250, Midcap 150/50,
    Smallcap 250/100/50, Microcap 250, Nifty 1000) and deduplicates.
    Saves to data/NSE_1500.csv — the primary universe file for all refresh ops.
    """
    data_dir = _get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    # All 9 NSE named index files — covers ~750-1000 unique large/mid/small/micro cap tickers
    index_files = [
        ("ind_nifty500list.csv",           "NIFTY500",         "Large Cap"),
        ("ind_niftylargemidcap250list.csv", "NIFTYLARGEMIDCAP", "Large/Mid Cap"),
        ("ind_niftymidcap150list.csv",      "NIFTYMIDCAP150",   "Mid Cap"),
        ("ind_niftymidcap50list.csv",       "NIFTYMIDCAP50",    "Mid Cap"),
        ("ind_niftysmallcap250list.csv",    "NIFTYSMALLCAP250", "Small Cap"),
        ("ind_niftysmallcap100list.csv",    "NIFTYSMALLCAP100", "Small Cap"),
        ("ind_niftysmallcap50list.csv",     "NIFTYSMALLCAP50",  "Small Cap"),
        ("ind_niftymicrocap250list.csv",    "NIFTYMICROCAP250", "Micro Cap"),
        ("ind_nifty1000list.csv",           "NIFTY1000",        "Large/Mid Cap"),
    ]

    seen: set[str] = set()
    all_rows: list[dict] = []
    fetched_indices: list[str] = []

    for fname, index_label, cap_cat in index_files:
        try:
            rows = await _fetch_nse_index_csv(fname)
            added = 0
            for r in rows:
                r["cap_category"] = cap_cat
                if r["ticker"] not in seen:
                    seen.add(r["ticker"])
                    all_rows.append(r)
                    added += 1
            fetched_indices.append(f"{index_label}({added})")
        except Exception:
            pass  # non-fatal: some indices may be temporarily unavailable

    if not all_rows:
        raise HTTPException(
            status_code=503,
            detail="Could not fetch any NSE index data from niftyindices.com. Check internet connection.",
        )

    # Primary universe file: NSE_1500.csv
    out_path = data_dir / "NSE_1500.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["ticker", "company_name", "sector", "isin", "index", "cap_category"])
        writer.writeheader()
        writer.writerows(all_rows)

    return {
        "status":    "bootstrapped",
        "tickers":   len(all_rows),
        "file":      str(out_path),
        "indices":   fetched_indices,
        "message":   f"Saved {len(all_rows)} NSE stocks to NSE_1500.csv. Call POST /dashboard/refresh to download 5yr OHLCV.",
    }


@router.post("/refresh")
async def trigger_refresh(
    background_tasks: BackgroundTasks,
    req: Optional[RefreshRequest] = None,
):
    """
    Smart OHLCV refresh.

    1. Auto-discovers best available universe CSV (NSE_1500 > NSE_1000 > nifty500).
    2. If no CSV → falls back to tickers already in DuckDB (delta-only refresh).
    3. If neither CSV nor DB → returns no_universe status with setup instructions.
    4. For each ticker: full 5yr download if no history, else delta-only.
    """
    global _refresh_active, _refresh_meta

    if _refresh_active:
        return {
            "status": "already_running",
            "tickers": len(_refresh_progress),
            **_refresh_meta,
        }

    request = req or RefreshRequest()

    # Scoped refresh: when explicit tickers are supplied (e.g. the watchlist),
    # refresh ONLY those and skip the full-universe load entirely.
    if request.tickers:
        scoped = sorted({t.strip().upper() for t in request.tickers if t.strip()})
        if not scoped:
            return {"status": "no_tickers", "tickers": 0, "message": "No valid tickers supplied for scoped refresh"}
        _refresh_meta = {
            "universe": "watchlist", "universe_path": "watchlist",
            "years": request.years, "started_at": str(date.today()),
        }
        background_tasks.add_task(_do_refresh_background, scoped, request.years, "watchlist")
        return {"status": "refresh_started", "tickers": len(scoped), "universe": "watchlist", "years": request.years}

    universe_path, universe_label = _resolve_universe_path(request.universe)

    # 1 — Try CSV
    tickers: list[str] = []
    if universe_path:
        tickers = _load_tickers_from_csv(universe_path)

    # 2 — Fall back to DB if CSV missing/empty
    if not tickers:
        tickers = _load_tickers_from_db()

    # 3 — Empty: guide the user
    if not tickers:
        return {
            "status": "no_universe",
            "tickers": 0,
            "universe": universe_label or "none",
            "message": (
                "No universe CSV found and the database is empty. "
                "Call POST /dashboard/bootstrap-universe first (downloads Nifty 500 list), "
                "then retry refresh. For 1500 stocks run: "
                "python scripts/nifty500_pipeline.py --mode universe1500"
            ),
        }

    _refresh_meta = {
        "universe":      universe_label,
        "universe_path": universe_path or "db",
        "years":         request.years,
        "started_at":    str(date.today()),
    }

    background_tasks.add_task(
        _do_refresh_background, tickers, request.years, universe_label
    )

    return {
        "status":      "refresh_started",
        "tickers":     len(tickers),
        "universe":    universe_label,
        "years":       request.years,
    }


@router.get("/refresh-status")
async def get_refresh_status():
    """Real-time per-ticker download progress."""
    total       = len(_refresh_progress)
    done        = sum(1 for s in _refresh_progress.values() if s == "done")
    current     = sum(1 for s in _refresh_progress.values() if s == "current")
    downloading = sum(1 for s in _refresh_progress.values() if s == "downloading")
    pending     = sum(1 for s in _refresh_progress.values() if s == "pending")
    errors      = sum(1 for s in _refresh_progress.values() if s == "error")
    completed   = done + current
    return {
        "active":      _refresh_active,
        "total":       total,
        "done":        done,
        "current":     current,
        "downloading": downloading,
        "pending":     pending,
        "errors":      errors,
        "pct":         round(completed / total * 100, 1) if total else 0,
        "tickers":     _refresh_progress,
        **_refresh_meta,
    }


_enrich_active: bool = False
_enrich_progress: dict = {}


async def _do_enrich_background(tickers: list[str]) -> None:
    global _enrich_active, _enrich_progress
    _enrich_active = True
    _enrich_progress = {"total": len(tickers), "done": 0, "errors": 0, "pct": 0}

    data_service_url = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
    batch_size = 50
    batches = [tickers[i: i + batch_size] for i in range(0, len(tickers), batch_size)]

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        for batch in batches:
            try:
                resp = await client.post(
                    f"{data_service_url}/fetch/fundamentals",
                    json={"tickers": batch},
                    timeout=300.0,
                )
                if resp.status_code == 200:
                    result = resp.json()
                    _enrich_progress["done"]   += result.get("fetched", 0)
                    _enrich_progress["errors"] += len(result.get("errors", []))
                else:
                    _enrich_progress["errors"] += len(batch)
            except Exception:
                _enrich_progress["errors"] += len(batch)
            _enrich_progress["pct"] = round(
                _enrich_progress["done"] / _enrich_progress["total"] * 100, 1
            )

    _enrich_active = False


@router.post("/enrich")
async def trigger_enrich(background_tasks: BackgroundTasks):
    """
    Fetch PE, market cap, NP QTR, Sales QTR, ROCE for all tickers in DB.
    Runs in background; poll /dashboard/enrich-progress for status.
    """
    global _enrich_active

    if _enrich_active:
        return {"status": "already_running", **_enrich_progress}

    tickers = _load_tickers_from_db()
    if not tickers:
        return {"status": "no_data", "message": "Run data refresh first."}

    background_tasks.add_task(_do_enrich_background, tickers)
    return {"status": "enrich_started", "tickers": len(tickers)}


@router.get("/enrich-progress")
async def get_enrich_progress():
    return {"active": _enrich_active, **_enrich_progress}


@router.get("/staleness")
def get_staleness():
    """Per-ticker data staleness — which stocks need a refresh.

    Sync on purpose (design review A3 family): zero awaits, full-table DuckDB
    aggregate — FastAPI's threadpool keeps it off the event loop.
    """
    with get_conn() as conn:
        try:
            rows = conn.execute("""
                SELECT
                    ticker,
                    MAX(date)  AS latest_date,
                    COUNT(*)   AS total_rows,
                    CAST(CURRENT_DATE - MAX(date) AS INTEGER) AS days_stale
                FROM ohlcv
                GROUP BY ticker
                ORDER BY days_stale DESC, ticker
            """).fetchall()

            result = []
            for r in rows:
                days   = int(r[3]) if r[3] is not None else 999
                status = "fresh" if days <= 1 else ("stale" if days <= 7 else "very_stale")
                result.append({
                    "ticker":      r[0],
                    "latest_date": str(r[1]),
                    "total_rows":  int(r[2]),
                    "days_stale":  days,
                    "status":      status,
                })

            fresh      = sum(1 for r in result if r["status"] == "fresh")
            stale      = sum(1 for r in result if r["status"] == "stale")
            very_stale = sum(1 for r in result if r["status"] == "very_stale")

            return {
                "summary": {
                    "fresh":      fresh,
                    "stale":      stale,
                    "very_stale": very_stale,
                    "total":      len(result),
                },
                "tickers": result,
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/enrichment-status")
async def get_enrichment_status():
    """Coverage report: which stocks have fundamentals/dividends/splits."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            resp = await client.get(f"{DATA_SVC}/db/stats")
        if resp.status_code != 200:
            return {"total_stocks": 0, "with_fundamentals": 0, "with_dividends": 0,
                    "with_splits": 0, "enrichment_coverage_pct": 0}
        stats = resp.json()
        enr = stats.get("enrichment", {})
        total = stats.get("total_stocks", 0)
        return {
            "total_stocks":            total,
            "with_fundamentals":       enr.get("with_fundamentals", 0),
            "with_dividends":          enr.get("with_dividends", 0),
            "with_splits":             enr.get("with_splits", 0),
            "enrichment_coverage_pct": enr.get("enrichment_pct", 0),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/universe-status")
def get_universe_status():
    """Report which universe CSVs exist and which DB tickers are present.

    Sync on purpose (design review A3 family): the body has zero awaits and does
    CSV + DuckDB reads — as a sync route FastAPI runs it in the threadpool instead
    of blocking the event loop.
    """
    data_dir = _get_data_dir()

    def _csv_count(path: Path) -> int:
        if not path.exists():
            return 0
        return len(_load_tickers_from_csv(str(path)))

    nse1500_path  = data_dir / "NSE_1500.csv"
    nse1000_path  = data_dir / "NSE_1000_MIDCAP_500.csv"
    nse500_path   = data_dir / "nifty500_universe.csv"

    csvs = {
        "nse_1500": {"exists": nse1500_path.exists(), "tickers": _csv_count(nse1500_path)},
        "nse_1000": {"exists": nse1000_path.exists(), "tickers": _csv_count(nse1000_path)},
        "nse_500":  {"exists": nse500_path.exists(),  "tickers": _csv_count(nse500_path)},
    }

    db_tickers = 0
    try:
        with get_conn() as conn:
            db_tickers = conn.execute(
                "SELECT COUNT(DISTINCT ticker) FROM ohlcv"
            ).fetchone()[0]
    except Exception:
        pass

    best_csv, best_label = _resolve_universe_path()
    best_count = csvs.get(best_label, {}).get("tickers", 0) if best_label else 0

    return {
        "csvs":       csvs,
        "best_csv":   best_label or None,
        "best_count": best_count,
        "db_tickers": db_tickers,
        "ready":      best_count > 0 or db_tickers > 0,
    }
