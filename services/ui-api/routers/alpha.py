"""
alpha.py — Glass-Box Alpha Discovery router (Phase 4, Agent 4).

Exposes the *novel alpha engine* (Phase 3, `novel_alpha_engine.py`) to the UI so the
Alpha Discovery Desk can:

  * enumerate the strategy registry + each strategy's PARAM_SPEC (so the UI renders
    knobs from the engine's own contract — never hardcoded ranges), and
  * run a parameterised scan across the FULL ~1500-ticker NSE universe and return the
    matched tickers / signals / realised-edge diagnostics.

Architecture / DuckDB-lock constraint
-------------------------------------
data-service holds a *persistent* read-write DuckDB connection for its whole lifetime.
On Docker Desktop (Mac, virtioFS) a second `duckdb.connect(read_only=True)` from another
process fails with "Conflicting lock is held in PID 0". So this router must NOT open the
DB directly (and never instantiates the engine's `DuckDBDataSource`). Instead it pulls
the full-universe OHLCV frame over HTTP from data-service `GET /db/ohlcv-bulk` (which
owns the lock) and runs the engine's pure-pandas signal math in-process. This keeps
data-service untouched and avoids the lock entirely.

Air-gap: MODE is forced to PAPER; this router only scans/reads. Zero execution.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

DATA_SVC = os.environ.get("DATA_SERVICE_URL", "http://localhost:8001")
MODE = "PAPER"  # air-gap — never live

# Eligibility gates mirror the engine's validated contract (Section 3b / 4).
MIN_BARS = 252
MIN_PRICE_INR = 20.0

# How many calendar days of history to pull for a scan. ~400 trading days comfortably
# exceeds the 252-bar eligibility floor while keeping the bulk payload small.
DEFAULT_SCAN_DAYS = 400
_BULK_TIMEOUT = httpx.Timeout(120.0)


# ── Engine loader (bind-mounted at /app/novel_alpha_engine.py in Docker) ──────────

def _candidate_engine_paths() -> list[Path]:
    candidates: list[Path] = []
    env = os.environ.get("ALPHA_ENGINE_PATH", "")
    if env:
        candidates.append(Path(env))
    candidates.append(Path("/app/novel_alpha_engine.py"))
    # Walk up from this file (services/ui-api/routers/alpha.py) toward the repo root.
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidates.append(parent / "novel_alpha_engine.py")
    candidates.append(Path("/Users/sudheer/MahaKubera_108/SuryaDhana_AI/novel_alpha_engine.py"))
    return candidates


_ENGINE = None  # lazily-imported module handle


def _load_engine():
    """Import novel_alpha_engine.py by path (it is bind-mounted, not pip-installed).

    The engine imports duckdb at module load, but we never call its DuckDBDataSource —
    only the registry / PARAM_SPEC / `generate_signals` pure-pandas math.
    """
    global _ENGINE
    if _ENGINE is not None:
        return _ENGINE
    for p in _candidate_engine_paths():
        if p and p.exists():
            spec = importlib.util.spec_from_file_location("novel_alpha_engine", str(p))
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules["novel_alpha_engine"] = module
                spec.loader.exec_module(module)
                _ENGINE = module
                return _ENGINE
    raise HTTPException(
        status_code=503,
        detail=(
            "novel_alpha_engine.py not found. Phase 3 must run and the engine must be "
            "bind-mounted into the ui-api container (see docker-compose.ui.yml)."
        ),
    )


# ── Data loader (HTTP → data-service, never DuckDB directly) ──────────────────────

async def _load_bulk_ohlcv(days: int) -> pd.DataFrame:
    """Pull full-universe OHLCV from data-service /db/ohlcv-bulk and return a tidy frame.

    data-service already excludes macro `^%` tickers and orders by (ticker, date) —
    the canonical layout the engine's `shift(1)` vectorisation requires.
    """
    try:
        async with httpx.AsyncClient(timeout=_BULK_TIMEOUT) as client:
            r = await client.get(f"{DATA_SVC}/db/ohlcv-bulk", params={"days": days})
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"data-service unreachable: {exc}")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    payload = r.json()
    rows = payload.get("data", [])
    df = pd.DataFrame(rows)
    if df.empty:
        raise HTTPException(status_code=503, detail="data-service returned no OHLCV rows")
    df["date"] = pd.to_datetime(df["date"])
    for col in ("open", "high", "low", "close", "volume", "adjusted_close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.sort_values(["ticker", "date"], kind="mergesort").reset_index(drop=True)


def _apply_eligibility(df: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Apply the validated history/price eligibility gates in pandas.

    Returns (eligible_frame, total_universe, eligible_universe).
    """
    nz = df[df["volume"] > 0]
    total_universe = int(nz["ticker"].nunique())
    grp = nz.groupby("ticker")
    bars = grp.size()
    last_close = grp.apply(lambda g: g.sort_values("date")["close"].iloc[-1])
    eligible = bars.index[(bars >= MIN_BARS) & (last_close >= MIN_PRICE_INR)].tolist()
    out = df[df["ticker"].isin(eligible) & (df["volume"] > 0)].reset_index(drop=True)
    return out, total_universe, len(eligible)


# ── Request / response models ─────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    strategy_id: str = Field(..., description="STRATEGY_ID from the registry")
    params: dict[str, Any] = Field(default_factory=dict, description="PARAM_SPEC overrides")
    days: int = Field(default=DEFAULT_SCAN_DAYS, ge=60, le=1825)
    # 'latest' = only the most recent bar's signals; 'recent' = most recent N signal days;
    # 'all' = every historical signal in the window.
    mode: str = Field(default="recent")
    recent_days: int = Field(default=10, ge=1, le=120)
    max_results: int = Field(default=500, ge=1, le=5000)
    include_diagnostics: bool = Field(default=True)


# `from __future__ import annotations` stringizes the `dict[str, Any]` annotation; when
# this module is imported dynamically by path the `Any` forward-ref isn't in the eval
# namespace until rebuilt. Resolve it explicitly so Pydantic finalises the model.
ScanRequest.model_rebuild()


# ── Endpoints ─────────────────────────────────────────────────────────────────────

@router.get("/mode")
async def alpha_mode() -> dict[str, str]:
    """Air-gap indicator — always PAPER, never live."""
    return {"mode": MODE, "execution": "disabled", "engine": "novel_alpha_engine"}


@router.get("/strategies")
async def list_alpha_strategies() -> dict[str, Any]:
    """Enumerate strategies + PARAM_SPEC straight from the engine (Glass-Box source)."""
    eng = _load_engine()
    registry = eng.list_strategies()
    # Split numeric knobs from boolean flags for nicer UI rendering, using ptype.
    enriched: dict[str, Any] = {}
    for sid, meta in registry.items():
        knobs, flags = {}, {}
        for name, spec in meta["params"].items():
            (flags if spec.get("type") == "bool" else knobs)[name] = spec
        enriched[sid] = {
            "name": meta["name"],
            "params": meta["params"],
            "knobs": knobs,
            "flags": flags,
        }
    return {"mode": MODE, "strategies": enriched, "default": next(iter(registry), None)}


@router.get("/universe")
async def universe_size(days: int = DEFAULT_SCAN_DAYS) -> dict[str, Any]:
    """Report the live universe counts (total vs eligible) — pure observability."""
    df = await _load_bulk_ohlcv(days)
    _, total, eligible = _apply_eligibility(df)
    return {
        "total_universe": total,
        "eligible_universe": eligible,
        "min_bars": MIN_BARS,
        "min_price_inr": MIN_PRICE_INR,
        "as_of": str(df["date"].max().date()),
    }


@router.post("/scan")
async def run_scan(req: ScanRequest) -> dict[str, Any]:
    """Run a parameterised strategy scan across the full eligible NSE universe.

    Returns matched (ticker, date, signal) rows + realised-edge diagnostics. All math
    comes from the engine — the UI only forwards PARAM_SPEC-bounded params.
    """
    eng = _load_engine()
    if req.strategy_id not in eng.STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown strategy '{req.strategy_id}'. "
                   f"Registered: {sorted(eng.STRATEGY_REGISTRY)}",
        )

    t0 = time.perf_counter()
    df = await _load_bulk_ohlcv(req.days)
    df, total_universe, eligible_universe = _apply_eligibility(df)
    sql_latency = time.perf_counter() - t0

    # Instantiate the strategy with UI params. The engine coerces/clamps to PARAM_SPEC
    # and raises ValueError on unknown params or an all-legs-off config.
    try:
        strat = eng.get_strategy(req.strategy_id, **req.params)
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid params: {exc}")

    t1 = time.perf_counter()
    mask = strat.generate_signals(df).fillna(False).astype(bool)
    signal_latency = time.perf_counter() - t1

    # Optional realised-edge diagnostics (forward-looking; never feeds the signal).
    diag = None
    if req.include_diagnostics and hasattr(strat, "forward_diagnostics"):
        try:
            diag = strat.forward_diagnostics(df).set_index(["ticker", "date"])
        except Exception:
            diag = None

    sig = mask.reset_index()
    sig.columns = ["ticker", "date", "signal"]
    fired = sig[sig["signal"]].copy()
    latest_date = df["date"].max()

    # Select the result window.
    if req.mode == "latest":
        fired = fired[fired["date"] == latest_date]
    elif req.mode == "recent":
        recent_signal_dates = (
            sorted(fired["date"].unique())[-req.recent_days:]
            if len(fired) else []
        )
        fired = fired[fired["date"].isin(recent_signal_dates)]
    # mode == 'all' → keep everything

    fired = fired.sort_values("date", ascending=False)

    # Attach the last close + realised edge per matched row.
    last_close = (
        df.sort_values("date").groupby("ticker")["close"].last().to_dict()
    )
    results: list[dict[str, Any]] = []
    for _, row in fired.head(req.max_results).iterrows():
        tkr, dt = row["ticker"], row["date"]
        item: dict[str, Any] = {
            "ticker": tkr,
            "date": str(dt.date()),
            "last_close": float(last_close.get(tkr, np.nan))
            if not np.isnan(last_close.get(tkr, np.nan)) else None,
        }
        if diag is not None and (tkr, dt) in diag.index:
            d = diag.loc[(tkr, dt)]
            for k in ("entry_adj", "exit_adj", "fwd5", "net5"):
                v = d.get(k)
                item[k] = float(v) if v is not None and np.isfinite(v) else None
        results.append(item)

    # Aggregate realised-edge stats over ALL fired rows with a complete forward window.
    edge = None
    if diag is not None and len(fired):
        joined = fired.set_index(["ticker", "date"]).join(diag, how="left")
        net = pd.to_numeric(joined.get("net5"), errors="coerce").dropna()
        if len(net):
            edge = {
                "n_with_forward": int(len(net)),
                "mean_net5_bps": round(float(net.mean()) * 1e4, 2),
                "median_net5_bps": round(float(net.median()) * 1e4, 2),
                "win_rate": round(float((net > 0).mean()), 4),
            }

    tickers = sorted(fired["ticker"].unique().tolist())
    return {
        "mode": MODE,
        "strategy_id": req.strategy_id,
        "strategy_name": eng.STRATEGY_REGISTRY[req.strategy_id].NAME,
        "params": dict(strat.params),
        "universe": {
            "total": total_universe,
            "eligible": eligible_universe,
            "rows_scanned": int(len(df)),
        },
        "as_of": str(latest_date.date()),
        "n_signals_total": int(mask.sum()),
        "n_signals_window": int(len(fired)),
        "tickers": tickers,
        "results": results,
        "edge": edge,
        "latency": {
            "sql_s": round(sql_latency, 3),
            "signal_s": round(signal_latency, 3),
            "total_s": round(time.perf_counter() - t0, 3),
        },
    }


@router.get("/validated")
async def validated_contract() -> dict[str, Any]:
    """Return the validated-alpha Section 3b rules/metrics for display (best-effort)."""
    candidates = [Path("/app/validated_alpha.md")]
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "validated_alpha.md")
    candidates.append(Path("/Users/sudheer/MahaKubera_108/SuryaDhana_AI/validated_alpha.md"))
    for p in candidates:
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="ignore")
            # Extract Section 3b block if present, else first 12k chars.
            idx = text.find("3b")
            section = text[idx: idx + 12000] if idx != -1 else text[:12000]
            return {"found": True, "path": str(p), "section_3b": section}
    return {"found": False, "section_3b": None}
