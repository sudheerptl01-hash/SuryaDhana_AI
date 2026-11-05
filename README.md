# SuryaDhana — NSE trading terminal (paper)

A Bloomberg-style terminal + quant research stack for NSE stocks, run by one operator on this Mac.
**Paper only — nothing here places live orders.** (Terminal look: the first-impression screenshot in
`~/.gstack/projects/SuryaDhana_AI/designs/design-audit-20261014/screenshots/`.)

## Quick start (warm machine)

```bash
./start-local.sh start      # data-service :8001 · ui-api :8010 · master-controller :8008 · UI :3000
./start-local.sh status     # per-service health + latency
./start-local.sh stop
```

Terminal: http://localhost:3000 — 15 tabs (BRIEF, WATCH, MKT, DESK, RSCH…) + the **GO** command bar
(press `/`, type a ticker or function code; `?` lists everything).

## The three surfaces

1. **Terminal** on :3000 — the daily workspace.
2. **Telegram bot** — `/brief`, `/book`, `/quote TCS`, `/alert`, `/login` (ICICI OTP from your phone), `/shadow`.
3. **Research library** — the RSCH tab: every study with verdict and evidence (`reports/*/FINDINGS.md`).

## Where things live

- `CLAUDE.md` — the map: running stack, trading rules (frozen), test-suite commands, conventions.
- `GETTING_STARTED.md` — fresh-machine setup; `docs/RUNBOOK_RESTORE.md` — backup/restore of the 4.4 GB
  DuckDB (`data/market.duckdb`, git-ignored).
- `docs/IMPROVEMENT_LOG.md` — the operations journal (newest first).
- `docs/PRODUCT_STRATEGY.md` — the product plan; `alpha_lab/` — strategy lab + the S1 paper shadow.
- Tests: five suites + `tsc` — exact commands in CLAUDE.md "How to run things".

## Safety

Decision Desk and the S1 shadow run in PAPER mode; ICICI is used for data and paper fills only. Trading
rules change only with the owner's review (see CLAUDE.md "Trading Rules").
