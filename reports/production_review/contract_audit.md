# Backend ↔ frontend contract audit (agent CON, 14 Oct 2026 ~22:00 IST)

Scope: ui (Next 3000) ↔ ui-api (8010) ↔ data-service (8001), live. Method: full inventories (api.ts 140 client
calls + 208 literal `/api/*` references across ui; openapi 207 ui-api paths / 94 data-service paths), template-aware
diff, 152 ui-api GET routes live-hit 3× warm (`endpoint_latency.csv`), field-level key diff on 10 critical
endpoints, error-shape census. No commits, GET-only traffic, POST/PUT existence verified via openapi only.

## Headline
**The contract is in better shape than most production systems**: 0 frontend calls hit a missing backend route,
139 of 146 attempted GETs return 200 live, and all 10 field-level checks match their TypeScript interfaces
key-for-key (monitor, profile, valuation, desk, results-reacting, positions, surveillance, research, alerts,
indices-live). One real backend-chain break found (stocks OHLCV), 5 pipeline endpoints 503 by state, 9 routes are
dead-code candidates, and error shapes split into three families that the UI must know about.

## 1. Frontend → backend: nothing missing
Every ui reference resolves. The four that first looked missing are POST routes called by raw `fetch` or served by
Next API handlers that proxy server-side (`ui/app/api/**/route.ts` → `${API_BACKEND}`):
`/api/ml/train/stream` (POST SSE), `/api/ml/stop`, `/api/analytics/{backtest,wfo-backtest}/stream` (POST SSE),
`/api/analytics/factor-profile` (POST), plus `/api/monitor/ws/monitor` (WebSocket; exists at
`services/ui-api/routers/monitor.py:108`, invisible to openapi by design). Next rewrite (`ui/next.config.js`)
forwards everything else to 8010; app-route handlers correctly take precedence for the SSE endpoints.

## 2. Live verification (endpoint_latency.csv)
152 GETs: **200 × 139 · non-200 × 7 · skipped × 6** (SSE/live-job/desk-preview-300s, all annotated).

| Non-200 | Status | Classification |
|---|---|---|
| /api/pipeline/{calibration,confusion-matrix,roc-curve,score-distribution} | 503 "Train model first" | STATE, not bug — no model trained in this env; UI shows the detail string |
| /api/pipeline/model-params | 503 "No model loaded" | STATE |
| /api/pipeline/features-explorer | 422 on my `page_size=5` | AUDIT ARTIFACT — `page_size≥10` returns 200 |
| /api/stocks/{ticker}/ohlcv | **404 for EVERY ticker** | **REAL BUG — see finding C1** |

Warm latency is healthy: p50 across all 200s ≈ 8 ms; only 6 routes exceed 300 ms (worst `/api/lw/screener`
1.71 s @ days=120, then results-implied-moves 594 ms, gold-preopen 560 ms, db/screener 321 ms,
stocks/screener 288 ms). Payload outliers: fundamentals-screen 529 KB, ipo 125 KB — candidates for
trimming/pagination (handed to agent SCALE).

## 3. Findings

| # | Severity | Finding | Fix |
|---|---|---|---|
| C1 | **DEGRADES** | `GET /api/stocks/{t}/ohlcv` 404s for all tickers: ui-api calls data-service **`/db/ohlcv/{t}`**, which doesn't exist; the real route is **`/ohlcv/{t}`** (verified 200 direct). Breaks the price chart in `StockDetailModal.tsx` (legacy dashboard) for every stock. Terminal pages are unaffected (they use `/api/data/ohlcv/{t}` + profile/history). | services/ui-api/routers/stocks.py ohlcv handler: drop the `/db` prefix in the DATA_SVC URL. One line. |
| C2 | DEGRADES | 5 pipeline-model GETs 503 until a model is trained; ModelLab/TrainingTerminal surface raw `detail` text rather than a designed empty state. | Frontend empty-state copy ("No trained model yet — run Train") on 503 from these 5 routes. |
| C3 | DEAD-CODE | 8 routes with no ui, script, or service consumer: `/api/dashboard/data-check`, `/api/data/db/screener` (duplicate of `/api/stocks/screener` output, 17 KB identical payloads), `/api/ml/health`, `/api/ml/runs`, `/api/monitor/embed`, `/api/execution/order/scheduled`, `/api/positions/refresh-session`, `/api/stocks/reload-universe`. | Delete or mark deprecated; each is attack/maintenance surface. (Checked dynamic consumers: gold `capture-open`/`snapshot` and `desk/daily`, `fii-dii-cash/refresh`, alerts PUT/run etc. ARE used by master-controller/daily_wrap — not dead.) |
| C4 | COSMETIC | `/api/data/fetch/icici/daily` is an intentional 410-Gone tombstone (api.ts comment documents it). | Keep; add `deprecated: true` in openapi so it stops looking like live surface. |
| C5 | COSMETIC | `/api/market/live-quotes` + `/api/alerts/feed` referenced only via api.ts exports whose component callers exist (MarketMap LIVE mode, header bell) — flagged initially because usage goes through intermediate constants. No action. | — |
| C6 | DEGRADES (risk) | **Error-shape split, 3 families**: (a) `HTTPException {detail}` — markets 85×, pipeline 33×, stocks 32×, data_proxy 21×; (b) soft-200 `{error: ...}` — pipeline 35×, positions 11×, dashboard 9×, telemetry 5×, lw 4×, gold 4×; (c) `{connected: false, ...}` — positions/data-live (16×). A component expecting (a) silently renders nothing on (b) because the request succeeds. The soft-200 `{error}` family is the silent-failure vector. | Convention: soft-200 errors only for degraded-but-usable data (connected:false pattern), everything else raises; add a shared `apiError(res)` helper in ui/lib that normalises all three. |
| C7 | COSMETIC | openapi `required` query params match frontend callers everywhere checked (surveillance `symbols`, financials-latest `symbols`, research/file `id,name`); no param-name mismatches found. | — |

## 4. Field-level checks (10 critical endpoints)
All key sets match their declared TS interfaces (api.ts) and consuming components — including nested
`monitor.regime.components[]`, `profile.price.returns{1W..1Y}`, `valuation.vs_history/rel_history`,
`open-positions.last_known` fallback (present only when disconnected, exactly as `heldSymbols()` expects).
No silent-undefined risks found beyond C2's 503 family. This is the benefit of the typed-client discipline:
**keep adding interfaces in api.ts for every new endpoint — it is working.**

## 5. The five fixes that matter
1. **C1** stocks.py ohlcv URL (`/db/ohlcv/` → `/ohlcv/`) — restores every legacy-dashboard chart.
2. **C6** error-shape convention + one shared normaliser in ui/lib (prevents the next silent blank panel).
3. **C3** delete the 8 dead routes (−400 lines of unowned surface).
4. **C2** designed empty-states for untrained-model 503s.
5. Trim `fundamentals-screen` (529 KB) and `ipo` (125 KB) payloads or paginate (with agent SCALE).

Counts: BREAKS-UI 0 · DEGRADES 3 (C1, C2, C6) · COSMETIC 3 · DEAD-CODE 8 routes · live 200-rate 95% ·
field-mismatches 0.
