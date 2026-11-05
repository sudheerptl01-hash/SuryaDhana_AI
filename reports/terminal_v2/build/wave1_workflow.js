export const meta = {
  name: 'suryadhana-terminal-v2-wave1',
  description: 'Terminal v2 Wave 0 (code items) + Wave 1: B7 arch first, then B1 data ∥ B3 api, then B2 controller, then B4 ui ∥ B5 docs, then B6 gates, then B8 studies; adversarial checker after every builder',
  phases: [
    { title: 'Arch', detail: 'B7: DuckDB read concurrency, shared HTTP client, /metrics + request ids, Redis/SecretStr hardening, snapshot policy' },
    { title: 'Data+API', detail: 'B1 fo_iv / index_drivers / data_health packages + DDL + jobs; B3 routers + breeze budget + margin' },
    { title: 'Controller', detail: 'B2: 22:45 + 08:35 passes, iv_eod / iv_intraday / index_drivers_daily jobs, catch-up, data-health alerts' },
    { title: 'UI+Docs', detail: 'B4 OMON/DERV›VOL/MEMB drivers/SYS›DATA/SourceChip/active-symbol store; B5 dictionaries, LEARN, CLAUDE.md, log' },
    { title: 'Gates', detail: 'B6: G1–G12' },
    { title: 'Studies', detail: 'B8: pre-registered study PLANs + registry rows' },
  ],
}

const ROOT = '/Users/sudheer/MahaKubera_108/SuryaDhana_AI'
const TV = `${ROOT}/reports/terminal_v2`
const SCRATCH = '/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/d05b13ef-dfd0-414a-bf06-771267e4c16a/scratchpad'
const P = '/Users/sudheer/Desktop/jupyter_env/bin/python'

const COMMON = `
You are a builder on the SuryaDhana "Terminal v2" program. Binding documents, read them first and obey them: ${TV}/PLAN.md
(§0 binding principles are acceptance criteria; §1 ownership table; Wave 0 code items 0.4–0.9 and Wave 1 sections 1.1–1.8
are your spec; the owner decisions O-T1…O-T31 not yet answered take the plan's recommended default and your result lists
which default you took), ${TV}/RATING.md, the seven research reports ${TV}/R-*/REPORT.md (verified sources, prototypes
under R-IV/iv_proto.py and R-DRIVERS/evidence/drivers_proto.py — reuse their math), ${ROOT}/CLAUDE.md, and for the
patterns to copy: the GOLD program (reports/gold_program/PLAN.md §c, services/data-service/gold/{hosts,pit,schema,
catalog_seed,jobs,api}.py, services/ui-api/routers/gold.py, ui/components/gold/, tests/gold/, tests/integration/
test_gold_gates.py) — point-in-time rows, catalog-gated rendering, host allowlist, badges, "describes, does not predict".
Today the GOLD page is deployed (UI release 20261104-230634); the live stack runs on :8001/:8010/:8008.

## Hard rules
- Edit ONLY the paths your ownership row in PLAN.md §1 gives you. Anything else is a patch request (file, old, new, why) in
  your result — the PM applies them. B1 and B7 share storage/duckdb_store.py by contract: B7 lands read()/write() + the RW lock
  first (phase Arch); B1 then adds DDL through that API and never edits B7's lock code.
- LIVE STACK OFF LIMITS: no restarts, no start-local.sh start/stop/restart, never write data/ or data/market.duckdb (temp DuckDB
  in tests; read-only copies under ${SCRATCH}/<you>/ for prototypes), no POST/PUT/DELETE to :8010/:8001/:8008, no Telegram, never
  start/kill an ICICI login, never touch ui/dist, ui/.next, /Applications, ~/Library/LaunchAgents; build_ui.sh only --out ${SCRATCH}/<you>/.
- NO Yahoo Finance calls (query1/query2, yfinance) from this machine; fixtures only. Every new fetcher goes through the
  allowlisted, paced client (lift gold/hosts.py's pattern to shared/ as PLAN §0.6 says) — never mcxindia.com, www.cmegroup.com,
  kitco, investing, stooq, goldprice, LBMA price pages. Live NSE/niftyindices probes: a handful, paced ≥ 1.2 s, browser UA.
- Breeze: read-only methods only, only through the budget ledger (B3 writes it; others call it), only when a session is live;
  never print tokens, .env values or TOTP secrets.
- Trading rules frozen (shared/momentum.py, decision_desk.py, trading_costs.py, alpha_lab gates); nothing you build feeds the
  Decision Desk, the S1 shadow, a directional alert or a ticket price. PAPER ONLY. Every derived number carries a badge;
  no composite score; context never coloured bullish/bearish; verdict sentences end "describes, does not predict"; the same
  number once per page; no new npm dependency; no pip install; ${P} only.
- Tests with negative controls for every rule you implement; ruff --line-length 130 clean on your files; mypy clean on new
  packages; tsc clean; the existing suites must stay green (run the ones your files touch: tests, scripts/tests,
  services/ui-api/tests, the node checks, cargo if you touch desktop/).
- Scratch only in ${SCRATCH}/<your-id>/. Do NOT use SendMessage. Return the structured result; "resolved" lists every spec
  item of your section with an outcome.
`

const RESULT_SCHEMA = {
  type: 'object',
  properties: {
    builder: { type: 'string' }, summary: { type: 'string' },
    resolved: { type: 'array', items: { type: 'object', properties: {
      item: { type: 'string' }, outcome: { type: 'string', enum: ['done', 'partial', 'deferred', 'not-applicable'] }, what_changed: { type: 'string' },
      files: { type: 'array', items: { type: 'string' } }, tests: { type: 'string' }, reason_if_not_done: { type: 'string' } },
      required: ['item', 'outcome', 'what_changed', 'files', 'tests'] } },
    files_changed: { type: 'array', items: { type: 'string' } },
    tests_run: { type: 'array', items: { type: 'object', properties: { command: { type: 'string' }, result: { type: 'string' } }, required: ['command', 'result'] } },
    patch_requests: { type: 'array', items: { type: 'object', properties: { file: { type: 'string' }, old: { type: 'string' }, new: { type: 'string' }, why: { type: 'string' } }, required: ['file', 'old', 'new', 'why'] } },
    contract_notes: { type: 'array', items: { type: 'string' } },
    defaults_taken: { type: 'array', items: { type: 'string' } },
    deploy_notes: { type: 'array', items: { type: 'string' } },
    open_issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['builder', 'summary', 'resolved', 'files_changed', 'tests_run', 'patch_requests', 'contract_notes', 'defaults_taken', 'deploy_notes', 'open_issues'],
}
const CHECK_SCHEMA = {
  type: 'object',
  properties: {
    builder: { type: 'string' }, verdict: { type: 'string', enum: ['ACCEPT', 'ACCEPT-WITH-NOTES', 'REJECT'] },
    problems: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['blocker', 'major', 'minor'] }, file: { type: 'string' }, issue: { type: 'string' },
      evidence: { type: 'string' }, fix: { type: 'string' } }, required: ['severity', 'file', 'issue', 'evidence', 'fix'] } },
    claimed_done_but_not: { type: 'array', items: { type: 'string' } }, notes: { type: 'string' },
  },
  required: ['builder', 'verdict', 'problems', 'claimed_done_but_not', 'notes'],
}

const BUILDERS = {
  B7: { id: 'B7-ARCH', phase: 'Arch', brief: `PLAN Wave 0 items 0.7 (Redis bind/auth via start-local.sh start_redis, SecretStr on the five secret
fields in shared/config.py, a test that repr(Settings()) leaks nothing) and 0.1's code half (scripts/db_backup.py --offsite hook
that copies the .zst to a path from OFFSITE_BACKUP_DIR when set; the owner decides the target), and Wave 1.5 in full: DuckDBStore
read()/write() on per-call cursors behind a readers-writer lock with the 42 store._conn bypasses retired, the anyio limiter
raised, Yahoo removed from /db/market-monitor's locked request path (NSE ind_close_all row stored nightly instead — coordinate the
DDL name with B1 via contract_notes: table index_ohlc_daily per PLAN 1.1), shared/http_client.py (one AsyncClient per process,
limits, per-route timeouts, per-upstream circuit breaker + stale-serve) adopted by ui-api's upstream proxies, Prometheus /metrics
on all three services + X-Request-ID middleware + JSON access log excluding /health /live /, the snapshot policy (one evening
read-only snapshot, orphan prune at start). Perf test = the R-ARCH §2.3 harness (10 concurrent history reads wall ≤ 2× single).
You own storage/duckdb_store.py, services/ui-api/main.py middleware, shared/{logging,metrics,http_client,config}.py,
start-local.sh (Redis lines only), scripts/db_backup.py. Everything must keep the live stack's behaviour identical from the UI.` },
  B1: { id: 'B1-DATA', phase: 'Data+API', brief: `PLAN 1.1 (fo_iv package: schema.py DDL for iv_surface_daily, iv_expiry_daily,
iv_summary_daily, vix_daily, index_ohlc_daily, iv_event_log, iv_intraday, rate_curve, nse_fo_volt, nse_contract_delta,
nse_combined_oi; iv_eod.py with the adopted method — Black-76 on the parity forward, untraded strikes → no IV, 25Δ/10Δ by
inverting delta, constant-maturity 30/60/90, rank AND percentile, RV cc/Parkinson/YZ, FOVOLT, model_version + r on every row;
legacy_parser.py for the 2019-10→2024-07 files; intraday.py for the 15-minute Breeze pilot writing parquet parts + iv_intraday;
catalog_seed.py), 1.2 (index_drivers package: constituents/weights/contribution/fit/driver_state tables, the rebuilt-and-
calibrated weights from stored filings + the top-10 file, hysteresis leader, breadth, NIFTY 50 + NIFTY BANK), 1.4's data half
(data_health package: dataset_catalog seeded from R-DATA §3's 45 rows + the new ones, ingest_log with sha256 /
If-Modified-Since, the added NSE evening ingests in nse_positions.py), Wave 0 0.5's ingest_log and 0.9's gap rows, and the
/jobs/* + /db/* endpoints in main.py for all of it (job names: iv_eod, iv_intraday, iv_weekly, index_drivers_daily,
data_health_refresh; backfill plan endpoint like gold's). Reproduce R-IV's prototype: the G2 gate (23 cached Oct-2026 files →
iv_compare_NIFTY.csv within 0.05 vol-pt). Use B7's store.read()/write() API (phase Arch landed before you; read the diff).` },
  B3: { id: 'B3-API', phase: 'Data+API', brief: `PLAN 1.1 API (/api/derivatives/iv/{symbol}, /surface, /cone, /events, /intraday,
/api/derivatives/vol-screen), 1.2 API (/api/market/index-drivers, /timeline, /monthly, /api/desk/attribution), 1.3's
POST /api/options/margin (Breeze margin_calculator when live → NSE SPAN file parser → the 12 % heuristic with its measured 4.8×
error printed; source chip), 1.4's GET /api/data/health, shared/breeze_budget.py (SQLite ledger, per-minute/per-day counters,
per-caller quotas, hard stop at the cap; default cap 700/day for the chain poller per O-T6's pilot) adopted by every Breeze
caller you own, the RSCH CATALOG rows, and the three honesty fixes' server side if any (0.6). Write ${TV}/API_CONTRACT.md
(generated from the code like the gold one, with a test that keeps them in sync). All reads from DuckDB / SWR caches; a test
proves zero outbound calls on the request path under a fake transport. Build against B1's table names (contract_notes if B1 is
not there yet: write to the names in PLAN 1.1/1.2 and fixtures).` },
  B2: { id: 'B2-CTRL', phase: 'Controller', brief: `PLAN Wave 0 0.5 (18:30 equity-only, the new 22:45 pass, the 08:35 sweep) and 0.9
(start-up catch-up extended to the listed jobs, gap rows), Wave 1 jobs (iv_eod as the last step of the 20:30 pass with the 22:45
retry and a Telegram info line on a miss; iv_intraday every 15 min 09:20–15:30 on trading days, skipped without a live session or
past the budget; iv_weekly Sat 03:00; index_drivers_daily 19:25 with the 20:35 retry; the hourly data-health check with one
Telegram line per transition and an 08:35 digest), the watchdog's second heartbeat, DATASET_MAX_AGE_DAYS retired in favour of
expected_by. Nothing inside 07:45–09:20 / 18:30–21:15 except the light stored-data compute jobs PLAN §0.10 allows. Tests in
scripts/tests (missed_jobs, the passes, freeze-window deferral). Read B1's actual /jobs contract and B3's /api/data/health shape
from the tree.` },
  B4: { id: 'B4-UI', phase: 'UI+Docs', brief: `PLAN 0.6 (IV rank → IV percentile wording + both chips defined, PCR uncoloured, VIX accent
neutral, unknown ?tab= toast, MOV panel titles), 1.1 panels (OMON history chart from iv30_cm with VIX overlay and markers, chain
header term/skew/straddle/IV-vs-RV strip, Greeks columns, DERV › VOL sub-view with GO alias VOL incl. the screener, EVTS crush
ledger, stock-window IV strip, OMON › LIVE 15-min path with SourceChip), 1.2 panels (MEMB → "Index members & drivers" with the
horizon selector, DRIVER REGIME strip, sector bar, monthly leaderboard, concentration/breadth chart, fit chip; GO aliases DRVR /
IMAP / CONTRIB; DESK "Book vs NIFTY"), 1.3's UI (real-margin chip on OSTR, chain-first OMON with "OPEN IN OSTR" through the new
ui/lib/activeSymbol.ts prefs-synced per-window store, context columns), 1.4's UI (SYS › DATA sub-view with GO alias DATA, the
DATA n STALE header chip, SourceChip on every panel header of every page). Build against B3's contract (API_CONTRACT.md in the
tree; fixtures when a route is missing). tsc, the node checks, and browser screenshots of every changed view with fixtures
routed, read them. No new page: sub-views only (O-T14 default).` },
  B5: { id: 'B5-DOCS', phase: 'UI+Docs', brief: `PLAN 1.6: docs/NSE_DATA_DICTIONARY.md verified rows (top-10 weights file, constituent
lists, FOVOLT, Contract_Delta, combineoi_deleq, SPAN file, historicalOR/vixhistory, the legacy F&O format, the dead
equity-stockIndices, the 22:05/22:12 publication times), docs/TERMINAL_DATA_DICTIONARY.md generated from dataset_catalog by a
script with --check, the LEARN entries (IV rank vs percentile, constant-maturity IV, parity forward, 25Δ skew, Parkinson /
Yang-Zhang, FOVOLT, SPAN vs exposure margin, points attribution + residual, hysteresis) as glossary + tooltip assets with a
validator like G-EDU's, CLAUDE.md (fix the /metrics claim, list the new tables/jobs/pages, extend the freeze-window note, the
restart-order rule stays), docs/RUNBOOK_RESTORE.md additions, the docs/IMPROVEMENT_LOG.md entry describing only what IS in the
tree (read the other builders' files; never claim unshipped items).` },
  B6: { id: 'B6-GATES', phase: 'Gates', brief: `PLAN 1.7 gates G1–G12 as code (G13 is the owner's): tests/unit/test_iv_eod.py,
the G2 replay, tests/test_index_drivers.py, tests/test_data_health.py, tests/test_hosts_allowlist_terminal.py (static scan: hosts ⊆
PLAN §0.6, no query1/query2/yfinance in new code, Yahoo absent from /db/market-monitor), the ui-api route tests incl. zero
outbound calls, the concurrency and observability tests, the UI *.check.ts additions (IV percentile + rank defined, neutral
token on context panels, regime strip suffix, SourceChip on every Panel, VIX once per page, unknown ?tab= toast),
scripts/ui_audit.py TABS + ui_perf budgets, scripts/tests for the new jobs, and CI (.github/workflows/ci.yml ruff/mypy/pin-drift/
pip-audit steps, pyproject.toml starter with the PLAN 0.8 rule set; fix F821 in providers/direct_yahoo_provider.py:219 and the two
ASYNC230 only if they are in files nobody else owns — else patch requests). Every gate must FAIL on a negative control.` },
  B8: { id: 'B8-STUDIES', phase: 'Studies', brief: `PLAN §1 B8 + Wave 3.3's precondition: ${TV}/studies/<id>/PLAN.md pre-registered BEFORE any
result for (a) IV-rank mean reversion / IV-RV spread as a forecast of realised vol (the thing every vendor implies), (b) index
driver persistence (does the leader's share persist 20 sessions ahead?), (c) GEX proxy vs next-day range; a ${TV}/STUDIES.md
registry (id, hypothesis, status, FINDINGS path), scripts/terminal_studies/*.py runnable on the stored tables once B1's backfill
exists (today: on the R-IV / R-DRIVERS prototype outputs, labelled provisional), RSCH CATALOG rows via patch request to B3.
Verdict rule: signed, |t| ≥ 2 in both halves, after costs; anything else is context. Never let a study result reach a badge
without the PM.` },
}

const buildPrompt = (b) => `${COMMON}

## Your brief (${b.id})
${b.brief}

Return the structured result with builder='${b.id}'.`
const checkPrompt = (b, r) => `${COMMON}

## Your role: adversarial check of ${b.id} (read-only; same hard rules)
Verify every "resolved" claim against the files and by re-running the tests named; check PLAN §0 principle by principle,
point-in-time correctness, the host allowlist, secrets hygiene, ownership (did the builder edit files it does not own?), and
that nothing reached the live stack. REJECT only for unresolved majors; list "claimed done but not" precisely.

${b.id} result:
${JSON.stringify(r, null, 1)}`

const run = (b) => agent(buildPrompt(b), { label: `build:${b.id}`, phase: b.phase, schema: RESULT_SCHEMA })
  .then((r) => r ? agent(checkPrompt(b, r), { label: `check:${b.id}`, phase: b.phase, schema: CHECK_SCHEMA }).then((c) => ({ build: r, check: c })) : null)

const out = {}
out.B7 = await run(BUILDERS.B7)
;[out.B1, out.B3] = await parallel([() => run(BUILDERS.B1), () => run(BUILDERS.B3)])
out.B2 = await run(BUILDERS.B2)
;[out.B4, out.B5] = await parallel([() => run(BUILDERS.B4), () => run(BUILDERS.B5)])
out.B6 = await run(BUILDERS.B6)
out.B8 = await run(BUILDERS.B8)
return out
