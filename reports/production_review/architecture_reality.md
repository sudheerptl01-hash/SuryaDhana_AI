# Architecture reality check (PM pass, 14 Oct 2026 ~21:30)

What the docs promise vs what actually runs on this Mac, measured live.

## Documented vs running

| Service (CLAUDE.md table) | Port | Status now | Reality |
|---|---|---|---|
| api-gateway | 8000 | **down** | never part of the local stack; nothing calls it |
| data-service | 8001 | up, **1.32 GB RSS** | the real data spine: DuckDB owner, NSE live, panels |
| feature-service | 8002 | **down** | legacy 5-day ML pipeline (autopilot OFF) |
| ml-service | 8003 | **down** | legacy |
| rl-service | 8004 | **down** | legacy |
| risk-service | 8005 | **down** | legacy |
| execution-service | 8006 | **down** | superseded: Breeze logic lives in ui-api/positions + scripts/live_execution (paper) |
| monitoring-service | 8007 | **down** | superseded by master-controller alerts + Telegram bot |
| master-controller | 8008 | up, 53 MB | scheduler (IST jobs), Telegram bot, telemetry |
| ui-api | 8010 | up (2 procs) | the frontend's single backend; proxies data-service |
| Next.js terminal | 3000 | up, 78 MB | prod build; /api/* rewrites → ui-api |

**The real spine is 4 processes:** Next → ui-api → data-service, with master-controller running jobs/bot on the side.
Seven of the eleven documented components are dormant code.

## Findings

1. **CLAUDE.md is architecturally stale (doc-severity HIGH).** The service table presents the 8-service design as
   current, and the "16-Week Roadmap" still shows Phase 1 ⏳ while the repo is years past it (Decision Desk
   adopted, terminal shipped, paper shadow live). A newcomer — or an agent — plans against the wrong map.
   *Fix:* rewrite the table as "running stack" + "dormant legacy (autopilot OFF)" and replace the roadmap with a
   pointer to docs/PRODUCT_STRATEGY.md + IMPROVEMENT_LOG.md.
2. **Dormant services decision needed (owner's call).** feature/ml/rl/risk/execution/monitoring services carry
   tests, Dockerfiles and compose entries but haven't run in months. Options: (a) archive to `legacy/` with a
   README (keeps history, cuts cognitive load and CI surface), (b) keep as-is documented as dormant, (c) revive
   behind the gateway when live trading returns. Recommend (a)/(b); do not delete — the Phase-6 OMS work is real.
3. **Single point of failure + memory concentration:** data-service holds ~1.3 GB (cached panels, NSE sessions,
   DuckDB). One process, one Mac. Acceptable for one operator; for a multi-user "Bloomberg" it needs: stateless
   ui-api replicas behind the (currently dead) gateway, a cache tier (Redis — already in the stack docs, unused
   locally), and read-only parquet/DuckDB replicas for research reads. SCALE report carries the numbers.
4. **Frontend↔backend topology matches** at the spine level: every UI call goes to ui-api (:8010) directly or via
   Next rewrites; no component talks to :8001 directly (CON report verifies per-endpoint).
5. **Disk:** 123 GB free; DB 4.4 GB; `ui/.next` is 717 MB (mostly webpack dev cache) — safe to prune
   (`ui/.next/cache`) whenever; it regenerates.
