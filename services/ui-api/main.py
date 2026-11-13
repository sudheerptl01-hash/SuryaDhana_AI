"""
SuryaDhana — UI API Service
Aggregates DuckDB data into UI-friendly payloads for the Next.js dashboard.
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


def _install_default_requests_timeout(seconds: float = 30.0) -> None:
    """Give every `requests` call in this process a timeout unless it sets one.

    breeze-connect (ICICI) issues requests calls WITHOUT a timeout. When ICICI's
    server dropped a connection (socket left in CLOSE_WAIT) the calling thread hung
    forever — freezing the Broker Account endpoints and blocking ui-api shutdown.
    """
    try:
        import requests
    except ImportError:
        return
    original = requests.Session.request
    if getattr(original, "_suryadhana_default_timeout", False):
        return

    def request_with_timeout(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = seconds
        return original(self, method, url, **kwargs)

    request_with_timeout._suryadhana_default_timeout = True  # type: ignore[attr-defined]
    requests.Session.request = request_with_timeout  # type: ignore[method-assign]


_install_default_requests_timeout()

# Load .env from project root (two levels up from services/ui-api/)
try:
    from dotenv import load_dotenv
    candidates = [
        Path(__file__).resolve().parent.parent.parent / ".env",
        Path(__file__).resolve().parent / ".env",
        Path("/app/.env"),
    ]
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate, override=False)
            break
except ImportError:
    pass

# shared/ lives at the repo root locally and is bind-mounted at /app/shared in Docker. Appended (not
# prepended) so no module that resolves today can be shadowed by a repo-root name.
for _p in (Path(__file__).resolve().parents[2], Path(__file__).resolve().parent):
    if (_p / "shared").is_dir() and str(_p) not in sys.path:
        sys.path.append(str(_p))

from shared.http_guard import install_http_guard  # noqa: E402
from shared.metrics import install_observability  # noqa: E402

from routers import dashboard, stocks, analytics, performance, positions, config, pipeline, execution, telemetry, lw_scanner
from routers import monitor
from routers import data_proxy
from routers import health_upstream  # O-F5a (D-BOOT): data-service up/down + db_read_only for the shell strip
from routers import alpha
from routers import ml_workspace
from routers import commodity
from routers import gold_preopen
from routers import gold          # GOLD terminal page (reports/gold_program/PLAN.md §d): /api/gold/*
from routers import markets
from routers import news_scanner
from routers import quotes
from routers import live as live_quotes   # live NSE program (LV-API): /api/live/quotes, /api/live/status
from routers import desk
from routers import research
from routers import ask as ask_analyst  # R2-ASK (RATING §7 R9-R1): RSCH's cited read-only analyst, /api/ask/*
from routers import costs
from routers import alerts as price_alerts
from routers import charts
from routers import derivatives
from routers import expiry
from routers import flow_radar    # FINAL ROUND E-RADAR: DERV › RADAR (/api/derivatives/flow-radar/{symbol})
from routers import data_health   # Terminal v2 PLAN 1.4: GET /api/data/health (B3)
from routers import options_strategy
from routers import fo_book       # PLAN 2.2: the PAPER F&O book /api/options/book/* (W2-BOOK)
from routers import gameplan      # FINAL ROUND wave E (F-11): GPLN Morning Game Plan — /api/gameplan, existing reads only
from routers import mcx
from routers import riskdash
import static_ui  # desktop Layer 1: static terminal UI (ui/dist/current) + /version, /ready, /live
from routers import prefs as ui_prefs
from routers import client_errors
from routers import notifications
from routers._api_gzip import ApiGzipMiddleware
from routers import _loop_watchdog
from routers import _cache_warm


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[ui-api] started")
    # Event-loop stall watchdog (25 Oct 14:40 hang follow-up): a loop that has not run for UI_API_LOOP_STALL_S
    # (5 s) gets a WARNING plus every thread's stack in .logs/ui-api.log; kill -USR1 <pid> dumps on demand.
    watchdog = _loop_watchdog.start_from_env()
    # Log in to Breeze once in the background so the UI's connection-status polls are
    # served from cache instead of waiting ~40 s on the first request.
    positions.warm_breeze_probe()
    analytics.warm_snapshot()
    gold_preopen.warm()
    # PAPER ONLY posture (C2-security-03): a LIVE mode restored from paper_trades.db is switched back
    # to PAPER unless EXECUTION_LIVE_ALLOWED=1. Never fails startup.
    await execution.enforce_paper_only_at_startup()
    # Fill the slow-endpoint SWR caches once, in the background, a few seconds after start (C-PERF-01/-02;
    # routers/_cache_warm.py). Off with UI_API_CACHE_WARM=0 and under pytest.
    cache_warm = _cache_warm.start_from_env()
    yield
    await _cache_warm.stop(cache_warm)
    if watchdog is not None:
        await watchdog.stop()
    print("[ui-api] stopped")


# Swagger /docs and /redoc (desktop review completeness-06): since the terminal UI is served on this same origin
# (:8010), their floating-version jsdelivr scripts (swagger-ui-dist@5, redoc@2, no SRI) would run as terminal-origin
# code (localStorage, the desktop shell's commands). Off unless UI_API_DOCS=1 (.env or the environment, read at
# start). /openapi.json stays: it is data, no script. data-service and master-controller keep their docs.
DOCS_ENABLED = os.environ.get("UI_API_DOCS", "").strip() == "1"

app = FastAPI(
    title="SuryaDhana — UI API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
)

# ── One error contract (F2.4, amendment A2): detail stays a STRING for legacy renderers; a
# structured `error{code,message,hint}` block rides beside it. StarletteHTTPException covers
# both fastapi.HTTPException raises and framework 404s.
@app.exception_handler(StarletteHTTPException)
async def _error_contract_handler(request: Request, exc: StarletteHTTPException):
    from errors import code_for_status, error_block
    d = exc.detail
    if isinstance(d, dict) and "code" in d and "message" in d:       # raised via errors.fail()
        block = error_block(d["code"], str(d["message"]), d.get("hint"))
        message = str(d["message"])
    else:
        message = d if isinstance(d, str) else str(d)
        block = error_block(code_for_status(exc.status_code), message)
    return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code,
                        headers=getattr(exc, "headers", None))


# W7 (bloomberg_verdict.md D8): local validation 422s were the one error family without the
# envelope (raw FastAPI arrays). Handler lives in errors.py; tested in tests/test_w7_fixes.py.
from errors import validation_error_handler
from fastapi.exceptions import RequestValidationError

app.add_exception_handler(RequestValidationError, validation_error_handler)

# No CORS (C2-security-06): the terminal is same-origin on :8010 and the optional Next UI on :3000 proxies
# /api server-side, so no browser page needs cross-origin access.
# Gzip for /api JSON >= 4 KB (C2-performance-08, routers/_api_gzip.py): never streams (SSE, NDJSON), never the
# static UI, never WebSockets.
app.add_middleware(ApiGzipMiddleware)
# Observability contract (Terminal v2 PLAN 1.5, shared/metrics.py): GET /metrics (Prometheus), X-Request-ID in and
# out bound as the structured logger's correlation id, a JSON access line per request except /health, /api/health,
# /live, / and /metrics (uvicorn's plain access log is silenced; SD_ACCESS_LOG=uvicorn keeps it), and the anyio
# worker-thread limit raised to SD_THREAD_LIMIT (64). Sits inside the guard (a rejected Host never counts) and
# outside gzip (latency includes it).
install_observability(app, service="ui-api")
# The Host/Origin guard (shared/http_guard.py, C2-security-01) must stay the OUTERMOST middleware (the last
# add_middleware call wins that place), so put any future add_middleware ABOVE this line.
install_http_guard(app, service="ui-api")

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(stocks.router,    prefix="/api/stocks",    tags=["stocks"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(performance.router, prefix="/api/performance", tags=["performance"])
app.include_router(positions.router, prefix="/api/positions", tags=["positions"])
app.include_router(config.router,   prefix="/api/config",    tags=["config"])
app.include_router(pipeline.router,   prefix="/api/pipeline",   tags=["pipeline"])
app.include_router(execution.router,  prefix="/api/execution",  tags=["execution"])
app.include_router(telemetry.router,  prefix="/api/telemetry",  tags=["telemetry"])
app.include_router(lw_scanner.router, prefix="/api/lw",         tags=["lw-scanner"])
app.include_router(monitor.router,     prefix="/api/monitor",  tags=["monitor"])
# Terminal v2 (PLAN 1.4): the dataset-health view owns /api/data/health; registered BEFORE data_proxy so its old
# data-service /health relay (defined in ui/lib/api.ts, called by no component) no longer shadows it.
app.include_router(data_health.router, prefix="/api/data", tags=["data-health"])
# O-F5a (D-BOOT): the shell's WARMING UP / DB READ-ONLY strip polls this one cached probe instead of
# 43 panels each discovering an outage one raw transport error at a time.
app.include_router(health_upstream.router, prefix="/api/health", tags=["health"])
app.include_router(data_proxy.router,  prefix="/api/data",     tags=["data-proxy"])
app.include_router(alpha.router,       prefix="/api/alpha",    tags=["alpha-discovery"])
app.include_router(ml_workspace.router, prefix="/api/ml",       tags=["ml-workspace"])
app.include_router(commodity.router, prefix="/api/commodity", tags=["commodity"])
app.include_router(gold_preopen.router, prefix="/api/commodity", tags=["commodity"])   # aliases for one release (PLAN §d)
app.include_router(gold.router, prefix="/api/gold", tags=["gold"])                     # GOLD page (43rd): health, COT, contracts…
app.include_router(markets.router, prefix="/api/market", tags=["market"])
app.include_router(news_scanner.router, prefix="/api/news-scanner", tags=["news-scanner"])
app.include_router(quotes.router, prefix="/api/quotes", tags=["quotes"])
app.include_router(live_quotes.router, prefix="/api/live", tags=["live"])
app.include_router(desk.router, prefix="/api/desk", tags=["decision-desk"])
app.include_router(markets.attribution_router, prefix="/api/desk", tags=["decision-desk"])  # PLAN 1.2: /api/desk/attribution (B3)
app.include_router(research.router, prefix="/api/research", tags=["research"])
app.include_router(ask_analyst.router, prefix="/api/ask", tags=["ask"])  # R2-ASK: 8 guardrails in ask_engine.py
app.include_router(costs.router, prefix="/api/costs", tags=["costs"])
app.include_router(price_alerts.router, prefix="/api/alerts", tags=["alerts"])
app.include_router(charts.router, prefix="/api/charts", tags=["charts"])
app.include_router(derivatives.router, prefix="/api/derivatives", tags=["derivatives"])
app.include_router(expiry.router, prefix="/api/derivatives", tags=["expiry"])
app.include_router(flow_radar.router, prefix="/api/derivatives", tags=["flow-radar"])  # E-RADAR: /flow-radar/{symbol} only, no overlap
app.include_router(options_strategy.router, prefix="/api/options", tags=["options-strategy"])
app.include_router(fo_book.router, prefix="/api/options/book", tags=["paper-fo-book"])  # PLAN 2.2 PAPER F&O book (W2-BOOK); /api/risk/fo lives in riskdash
app.include_router(mcx.router, prefix="/api/mcx", tags=["mcx-gold"])
app.include_router(riskdash.router, prefix="/api/risk", tags=["risk"])
app.include_router(gameplan.router, prefix="/api/gameplan", tags=["gameplan"])  # GPLN (wave E, F-11): assembles existing reads; nothing feeds the Desk / S1 / alerts / tickets
app.include_router(ui_prefs.router, prefix="/api/prefs", tags=["prefs"])  # user settings (desktop program D3)
app.include_router(client_errors.router, prefix="/api/client-errors", tags=["client-errors"])  # UI error reports (K1)
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])  # shell feed (K5)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ui-api"}


# Same body under /api (C3-logic-unchanged-09): the UI's health monitor can probe one path that works on
# :8010 and through the :3000 dev server's /api rewrite alike.
@app.get("/api/health")
async def api_health():
    return await health()


# ── Desktop program Layer 1 (reports/desktop_app/PLAN.md §5): /version, /ready, /live, then the static
# terminal UI from ui/dist/current (override: UI_DIST_DIR). mount_static_ui installs the UI as the
# router's not-found fallback, so it never shadows a route above or one added later. Keep it LAST.
app.include_router(static_ui.version_router)
static_ui.mount_static_ui(app)
