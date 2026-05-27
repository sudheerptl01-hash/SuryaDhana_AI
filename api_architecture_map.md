# SuryaDhana — API Architecture Map

## Why These Two Service Boundaries Exist

### The Core Institutional Problem

A production trading terminal must serve two fundamentally different workloads simultaneously:
1. **Bulk historical ingestion** (seconds–minutes per batch, CPU/IO bound)
2. **Sub-second live streaming** (microsecond latency, network/event bound)

Mixing these in a single service creates a classic "noisy neighbor" problem: a 1,500-ticker OHLCV refresh consuming 800ms of I/O would delay a live NIFTY tick by the same margin. Institutional terminals (Bloomberg, Reuters Eikon) solve this with separate data planes. We replicate that pattern here.

---

## Group 1: `data-service` (Port 8001) — Historical & Batch Data Plane

**Purpose:** Long-lived, CPU/IO-bound operations that can tolerate latency.  
**Transport:** REST (HTTP). Synchronous + BackgroundTasks where needed.  
**Data store:** DuckDB (file-based OLAP, excellent for time-series scans).  
**Consumers:** `ui-api`, `feature-service`, `ml-service`, internal batch scripts.

### Endpoint Rationale

| Endpoint | Why It Exists |
|---|---|
| `GET /health` | Kubernetes readiness probe + UI service status widget |
| `GET /ready` | Confirms DuckDB is mounted and initialized (distinct from health) |
| `GET /provider/status` | Tells the UI whether ICICI Breeze is connected. Drives the "Provider" chip in the dashboard |
| `POST /provider/configure` | Hot-reloads ICICI credentials without restarting the service. Critical for session token rotation (ICICI tokens expire daily) |
| `POST /fetch/historical` | Bulk backfill: fetches N years of OHLCV for a ticker list. ICICI v2 primary, yfinance v8 fallback. Used on cold-start |
| `POST /fetch/refresh` | Single-ticker incremental refresh: fetches only rows newer than latest DuckDB date. O(days_since_last_sync) |
| `POST /fetch/refresh-batch` | Multi-ticker incremental refresh in a single call. Powers the "Refresh Data" button for 1,500 tickers |
| `GET /ohlcv/{ticker}` | Reads stored OHLCV from DuckDB. Used by charts, backtests, feature computation |
| `GET /live/quote/{ticker}` | On-demand live quote passthrough via ICICI. Used for real-time price display in stock details |
| `GET /live/index/nifty` | Returns latest stored NIFTY quote from DuckDB (the poller writes here every 5s) |
| `GET /live/intraday/{ticker}` | Today's intraday bars via ICICI Breeze. Used for intraday chart mode in StockDetailModal |
| `POST /fetch/icici/daily` | ICICI-specific daily OHLCV with 365-day chunking. Bypasses yfinance for premium accuracy |
| `POST /fetch/fundamentals` | Yahoo Finance fundamentals (PE, MCap, ROCE, etc.). ~0.6s/ticker, must be batched |

### Performance Bottleneck Solved

Without isolation, a `POST /fetch/refresh-batch` for 1,500 tickers running for 3–5 minutes would:
- Block all other requests if the service used synchronous threading
- Create DuckDB write contention with read queries from the UI

The `data-service` solves this by:
1. Running as a **dedicated FastAPI process** — no contention with UI-API or monitoring
2. DuckDB WAL mode + dedicated write connection — reads and writes are concurrent
3. `BackgroundTasks` for fire-and-forget bulk operations
4. `asyncio.Semaphore` for rate limiting (avoids yfinance 429s)

---

## Group 2: `ui-api monitor` (Port 8010) — Live Streaming & Subscription Plane

**Purpose:** Real-time event streaming to the browser. Microsecond-sensitive.  
**Transport:** WebSocket (persistent duplex) + REST for subscription management.  
**Message bus:** Redis pub/sub channel `live.quotes`.  
**Consumers:** Next.js frontend only (browser clients).

### Endpoint Rationale

| Endpoint | Why It Exists |
|---|---|
| `POST /api/monitor/subscribe` | Adds symbol to Redis `monitored.stocks` set. The data-service NIFTY poller checks this set. Persists across WS reconnects |
| `POST /api/monitor/unsubscribe` | Removes from Redis set. Prevents polling symbols no longer watched |
| `GET /api/monitor/list` | Returns current monitored set. Used on page load to restore watchlist state |
| `GET /api/monitor/live/nifty` | HTTP fallback for NIFTY quote (when WS is unavailable or during SSR) |
| `WS /api/monitor/ws/monitor` | **The live streaming core.** Browser connects once; receives real-time tick events for subscribed symbols. Implements per-connection symbol filtering via JSON protocol |
| `GET /api/monitor/embed?symbol=NIFTY` | Returns TradingView widget snippet for embedding third-party charts |

### The WebSocket Architecture

```
[data-service NIFTY poller]
    ↓ every 5s via ICICI Breeze
    → publishes JSON to Redis channel "live.quotes"
    
[ui-api ws_monitor endpoint]
    ← subscribes to Redis "live.quotes" in background thread
    → forwards to all connected browser WebSocket clients
    → per-connection symbol filtering: {"action":"subscribe","symbols":["RELIANCE","TCS"]}
    
[Browser WS Manager (wsManager.ts)]
    ← receives tick events
    → dispatches to AppContext.liveQuotes[]
    → triggers React re-renders only for changed cells
```

### Why REST ≠ WebSocket Here

Polling `/api/data/live/quote/{ticker}` every second for 20 watchlist stocks = 20 HTTP requests/second per user. At 10 concurrent users = 200 req/s of overhead, plus 200 TCP handshakes/s.

WebSocket: 1 persistent connection per user. 10 users = 10 connections. Redis pub/sub delivers ticks once regardless of consumer count. 99% bandwidth reduction.

### Why Separation of `/api/monitor/*` from `/api/data/*`

The monitor endpoints must be **always fast and never blocked by I/O**. If monitor lived inside data-service:
- A 5-minute bulk refresh would compete with the Redis pub/sub reader thread
- The WS handler's `asyncio.get_event_loop()` would contend with data fetch I/O tasks

By hosting monitor in `ui-api` (which is stateless from a data perspective), the live streaming path remains isolated.

---

## Data Flow: End-to-End

```
NSE Market Data
    ↓
ICICI Breeze API
    ↓
data-service (port 8001)
    ├── Background: NIFTY poller (every 5s) → DuckDB + Redis "live.quotes"
    └── On-demand: /fetch/*, /ohlcv/*, /live/quote/*
    
Redis pub/sub
    ↓ "live.quotes" channel
ui-api monitor router
    ↓ WebSocket
Browser (Next.js)
    ├── AppContext.liveQuotes → Stock table flash animation
    ├── LiveMonitorBar → NIFTY ticker + watchlist prices
    └── StockDetailModal → Intraday chart

ui-api (port 8010)
    ├── /api/data/* proxy → data-service (for UI access to data-service)
    ├── /api/dashboard/* → DuckDB direct read
    └── /api/monitor/* → Redis + WebSocket
```

---

## Proxy Layer: `/api/data/*`

The frontend cannot call `http://data-service:8001` directly (Docker DNS only resolves inside containers). To avoid environment-specific URL logic in the frontend:

```
Browser → Next.js /api/* rewrite → ui-api:8010 → /api/data/* → data-service:8001
```

This `data_proxy.py` router transparently forwards all data-service endpoints via httpx, using `DATA_SERVICE_URL` env var (`http://data-service:8001` in Docker, `http://localhost:8001` in dev).

**Security note:** The proxy is not authenticated in development. In production, add bearer token validation at the proxy layer before forwarding to data-service.

---

## Global State Integration Points

| API Event | AppContext Field | UI Effect |
|---|---|---|
| WS tick received | `liveQuotes[symbol]` | StockTable cell flash |
| Watchlist add | WS subscribe + REST subscribe | LiveMonitorBar shows ticker |
| Watchlist remove | WS unsubscribe + REST unsubscribe | LiveMonitorBar hides ticker |
| `/api/data/health` response | `dataServiceStatus` | SystemStatusWidget dot color |
| `/api/data/provider/status` | `providerStatus` | Provider chip in header |
| Fetch error | Toast queue | Error toast (top-right) |
