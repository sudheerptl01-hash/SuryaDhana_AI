export const meta = {
  name: 'suryadhana-terminal-v2-wave1-continue',
  description: 'Terminal v2 wave 1, second half: fix the backend re-check majors, build the UI, docs/LEARN and pre-registered studies in parallel (each adversarially checked), then the gates builder',
  phases: [
    { title: 'Build', detail: 'F-BACKEND (B1/B2/B3 majors), B4-UI, B5-DOCS, B8-STUDIES in parallel, a checker after each' },
    { title: 'Gates', detail: 'B6-GATES: PLAN 1.7 G1-G12 as code, then its checker' },
  ],
}

const ROOT = '/Users/sudheer/MahaKubera_108/SuryaDhana_AI'
const TV = ROOT + '/reports/terminal_v2'
const SCRATCH = '/Users/sudheer/.suryadhana_pm_scratch/v2'
const P = '/Users/sudheer/Desktop/jupyter_env/bin/python'

const COMMON = `
You are a builder on the SuryaDhana "Terminal v2" program, wave 1, second half. Binding documents (read first, obey):
${TV}/PLAN.md (§0 binding principles incl. the 5 Nov PM amendment under §0.3 on vintages; §1 ownership; Wave 0 items 0.4-0.9
and Wave 1 sections 1.1-1.8 are the spec; unanswered owner decisions O-T1..O-T31 take the plan's recommended default and you
list the defaults you took), ${TV}/RATING.md, the research reports ${TV}/R-*/REPORT.md, ${ROOT}/CLAUDE.md.

STATE OF THE TREE (5 Nov 2026 ~07:45 IST): the first half of wave 1 landed — B7-ARCH (DuckDBStore readers-writer lock with
read()/reader()/write()/writer(), shared/metrics.py /metrics + X-Request-ID + JSON access log, shared/http_client.py allowlisted
paced client + per-process AsyncClient with breaker and stale-serve, Redis bind/auth in start-local.sh, SecretStr settings,
db_backup --offsite), B1-DATA (services/data-service/{fo_iv,index_drivers,data_health}/ packages, DDL, jobs, /jobs/* and /db/*
routes, nse_positions.py evening ingests), B3-API (routers/{derivatives,markets,data_health,options_strategy}.py routes,
shared/breeze_budget.py ledger, ${TV}/API_CONTRACT.md with a sync test), B2-CTRL (master_controller.py: 22:45 nse_evening_pass,
08:35 morning_sweep, iv_eod/iv_intraday/iv_weekly/index_drivers_daily/data_health_check jobs, extended catch-up). Their results,
adversarial checks and every patch request are in ${SCRATCH}/wave1_results.json (keys build:<id>, check:<id>); the PM applied
76 of 84 patch requests (${TV}/build/wave1_patch_apply.json). The GOLD page is deployed (UI release 20261105-041017); the live
stack runs the PRE-v2 code: nothing of Terminal v2 is deployed, no IV/drivers backfill has run, the new tables are empty.
The repo is now pushed to a PUBLIC GitHub remote: never write a credential, token, .env value, account number, holdings or a
screenshot of PORT/BRKR/RSK/DESK into any file; the PM commits and pushes — you never run git commit/push/reset/checkout.

RESUME NOTE (read first): the first attempt at B4-UI and B5-DOCS ran 07:10-07:20 IST and was cut off by a usage cap
mid-edit. HALF-APPLIED files from it — audit each, then finish or redo: B4-UI: ui/components/terminal/{source.ts,index.tsx},
ui/components/CommandBar.tsx, ui/lib/{activeSymbol.ts,goAliases.ts}, ui/components/vol/{api.ts,volModel.ts,charts.tsx,
ChainStrip.tsx,IvHistoryChart.tsx,CrushLedger.tsx,IvLivePath.tsx,IvStrip.tsx,VolView.tsx} (tsc fails now at
vol/volModel.ts:106: string not assignable to 'buy' | 'sell' — fix it). B5-DOCS: docs/NSE_DATA_DICTIONARY.md,
docs/TERMINAL_DATA_DICTIONARY.md, reports/terminal_v2/LEARN/build_assets.py. B6-GATES and B8-STUDIES never started.
Other known state: ruff on the new packages is down to 3 findings (fo_iv/api.py:171 S110 try-except-pass; fo_iv/reads.py:143
and index_drivers/jobs.py:82 'x == x' NaN tests → use math.isnan / pd.isna) — F-BACKEND fixes them. The full core suite
(tests/) was green before v2 in ~130 s; on this tree tests/arch/test_metrics_middleware.py::
test_access_log_excludes_health_root_live_but_logs_failures fails only in the full run (order-dependent: passes alone) —
B6-GATES finds the cross-test leak (likely logging/handler or anyio limiter state installed by an earlier test) and fixes it in
the test or via a patch request to shared/metrics.py's owner (the PM).
Separately, a full run of tests/ on this tree pinned one CPU for > 10 min without finishing (every new test file passes in seconds on its own, so it is a cross-test interaction); the PM is locating it now and will fix it or leave a note in ${SCRATCH}/core_suite_note.md before B6 starts — B6 reads that file first and must leave the full core suite finishing in about the old time (~2-3 min) and green.

## Hard rules
- Edit ONLY the paths your ownership line gives you. Anything else is a patch request {file, old, new, why} in your result
  (old = a unique exact substring of the CURRENT file); the PM applies them.
- LIVE STACK OFF LIMITS: GET only, paced (<= 2/s); no restarts, no start-local.sh start/stop/restart/build-ui, never write
  data/ or data/market.duckdb (temp DuckDB in tests; the live file is locked by data-service), no POST/PUT/DELETE to
  :8010/:8001/:8008, no Telegram, never start or kill an ICICI login, never touch ui/dist, ui/.next, /Applications,
  ~/Library/LaunchAgents. UI builds only with scripts/build_ui.sh --out ${SCRATCH}/<your-id>/export. It is inside the IST
  freeze window 07:45-09:20 until 09:20: irrelevant to you (you restart nothing) but do not schedule anything.
- NO Yahoo Finance calls (query1/query2, yfinance) from this machine; fixtures or stored data only. Every new fetcher goes
  through shared/http_client.py (allowlist). NSE / niftyindices probes: a handful at most, paced >= 1.2 s.
- Breeze: read-only methods, only through shared/breeze_budget.py, only if a session is live; never print tokens or .env values.
- Trading rules frozen (shared/momentum.py, decision_desk.py, trading_costs.py, alpha_lab gates); nothing you build feeds the
  Decision Desk, the S1 shadow, a directional alert or a ticket price. PAPER ONLY. Every derived number carries a badge
  (signal/context/arithmetic/heuristic; no 'signal' exists); no composite score; context never coloured bullish/bearish;
  verdict sentences end "describes, does not predict"; the same number once per page; no new npm dependency; no pip install;
  ${P} only.
- Tests with negative controls for every rule you implement; ruff --line-length 130 clean and mypy clean on your new code;
  tsc clean; run every suite your files touch (tests, scripts/tests, services/ui-api/tests, the ui node checks) and report
  the exact counts.
- Scratch only in ${SCRATCH}/<your-id>/ (create it). Do NOT use SendMessage. Return the structured result; "resolved" lists
  every item of your brief with an outcome.
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

const BUILDERS = [
  { id: 'F-BACKEND', phase: 'Build', owns: 'services/ui-api/routers/{positions,markets,data_health,derivatives}.py, services/ui-api/tests/test_terminal_v2_*.py + test_breeze_budget.py, scripts/master_controller.py + scripts/tests/test_terminal_v2_controller.py, services/data-service/{nse_positions.py,bhavcopy.py}, services/data-service/{fo_iv,index_drivers,data_health}/** and their tests under tests/ (tests/unit/test_iv_*.py, tests/test_index_drivers*.py, tests/test_data_health*.py if they exist), ' + TV + '/API_CONTRACT.md',
    brief: `Resolve every major and every "claimed done but not" in the checks of B1-DATA, B2-CTRL and B3-API (${SCRATCH}/wave1_results.json,
keys check:B1-DATA, check:B2-CTRL, check:B3-API), plus their minors where cheap. In particular: (1) B3: the trades route's
breeze.get_order_list and _get_breeze_client's generate_session go through the budget ledger (_breeze_call), with a test that
the call records one ledger entry and a negative control that a day cap of 0 refuses before the SDK runs; GET
/api/market/option-history/{symbol} uses the shared client (_get_json) with the UpstreamError mapping, is added to the
loopback test, and API_CONTRACT §8 is regenerated (TERMINAL_CONTRACT_WRITE=1); _expected_at becomes trading-day aware (T-1
files and morning slots after weekends/holidays use the NSE holiday calendar; a Monday 20:00 MTF row is not amber), with tests.
(2) B2: plan_sweep and the start-up catch-up re-fetch the evening and IV input files (nse_participant_vol, nse_fii_stats,
nse_mwpl_clients, nse_combined_oi, nse_fo_volt, nse_contract_delta, index_ohlc_daily, nse_bhavcopy) for missed sessions through
B1's /jobs/ingest-nse-files (NseFilesRequest: datasets, from, to, revalidate) — read B1's actual route; drop or fix the dead
nse_evening_pass branch; tests with a missed-session fixture and a negative control. (3) B1: apply the PLAN §0.3 PM amendment
(derived tables keep the latest computation; say so in the fo_iv/index_drivers docstrings and catalog notes, remove the false
"never overwrites" claims); bhavcopy re-publication: release_at = the publisher's Last-Modified (RFC 1123 GMT → aware UTC),
the revised body archived beside the first (cache_root), the first 18:30 sighting stamped too (B1 patch request #76 in
${TV}/build/wave1_patch_requests.json was not applicable as written: implement its intent), the catalog row says how
revisions are versioned; extend the bare-http scan to nse_positions.py's new code paths or document the exemption. Re-run
the suites your files touch and report counts.` },
  { id: 'B4-UI', phase: 'Build', owns: 'ui/** (components, lib, app, the *.check.ts node checks under ui/components/__tests__ that cover your views; never ui/dist, ui/.next, ui/node_modules)',
    brief: `PLAN 0.6 (OMON "IV rank" → "IV percentile (share of the past year below today)" with both chips defined on hover; PCR no
longer coloured green >= 1; DERV VIX accent neutral; unknown ?tab= shows a toast naming the release instead of silently
landing on BRF; MOV's two INTRADAY panels get distinct titles), 1.1 panels (OMON history chart from iv30_cm with the India VIX
overlay and results/expiry markers; chain header strip: term near/next/far + 30/60/90, 25-delta skew with its 1-y percentile,
straddle vs its history, IV vs RV20 cc/Parkinson/YZ/FOVOLT; Greeks columns on the chain; DERV > VOL sub-view with GO alias VOL
incl. the skew/term/cone/IV-vs-RV panels and the VOL screener table; EVTS IV-crush ledger; stock-window IV strip; OMON > LIVE
15-minute path with a SourceChip LIVE Breeze / LIVE NSE / OFFLINE), 1.2 panels (MEMB → "Index members & drivers": horizon
selector 1d/5d/1m/3m/YTD/since-change, the DRIVER REGIME strip in the neutral token ending "describes, does not predict",
sector contribution bar, monthly leaderboard, concentration & breadth chart, the fit chip; GO aliases DRVR / IMAP / CONTRIB;
DESK "Book vs NIFTY" honest when in cash; MOV keeps the live today panel with a "history on MEMB" footer), 1.3 UI (OSTR margin
chip with source BREEZE / NSE SPAN FILE / HEURISTIC and the heuristic's measured 4.8x error printed; chain-first OMON with
"OPEN IN OSTR" carrying symbol + expiry + strikes through a new ui/lib/activeSymbol.ts prefs-synced per-window store; context
columns delta-equivalent OI / % MWPL / NSE delta), 1.4 UI (SYS > DATA sub-view with GO alias DATA: RAG table sorted by lag,
filter by page, honest wording; the "DATA n STALE" header chip linking to it; a SourceChip on every Panel header of every page,
staleness never only in prose — fix RSK, WRAP, CMDT, WTCH). Build against ${TV}/API_CONTRACT.md and the routes in
services/ui-api/routers/{derivatives,markets,data_health,options_strategy}.py; when a route has no data yet (tables empty until
the backfill) the panel shows an honest empty state ("history starts <date> · backfill pending"), never a fake value. No new page
(sub-views only, O-T14 default); keep the 43-page gates green (pages.ts, desktop.check, pages.check). Run tsc and every plain-node
check; build a scratch export and take browser screenshots of every changed view against the live ui-api (read-only GETs; IV
routes may 404/empty on the live pre-v2 stack — route those to fixtures from services/ui-api/tests/_terminal_v2_fixtures.py
through a local scratch server), read them, and list them in your result.` },
  { id: 'B5-DOCS', phase: 'Build', owns: 'docs/** (NSE_DATA_DICTIONARY.md verified rows, a generated TERMINAL_DATA_DICTIONARY.md, RUNBOOK_RESTORE.md, IMPROVEMENT_LOG.md), CLAUDE.md, ' + TV + '/LEARN/** (new), scripts/terminal_data_dictionary.py (exists: B1 wrote it; you own it now)',
    brief: `PLAN 1.6: docs/NSE_DATA_DICTIONARY.md verified rows (the NIFTY top-10 weights file, the constituent lists, FOVOLT,
Contract_Delta, combineoi_deleq, the SPAN file, historicalOR/vixhistory, the legacy F&O bhavcopy format, the dead
equity-stockIndices, the measured 20:10 / 19:23 / 17:01 / 22:05 / 22:12 publication times; B1 sent the row data as patch
request #77 in ${TV}/build/wave1_patch_requests.json which did not apply — use its content); docs/TERMINAL_DATA_DICTIONARY.md
generated from the dataset_catalog by scripts/terminal_data_dictionary.py with a --check mode and a scripts/tests test (like the
gold dictionary); the LEARN layer for v2 as ${TV}/LEARN/glossary.json + tooltips.json + a validator (IV rank vs percentile,
constant-maturity IV, the put-call-parity forward, 25-delta skew, Parkinson / Yang-Zhang, FOVOLT, SPAN vs exposure margin,
points attribution and its residual, hysteresis, delta-equivalent OI, MWPL) — each entry one line <= 200 chars, no direction
words; CLAUDE.md: fix the /metrics claim to what B7 shipped, list the new packages/tables/routes/jobs (read the code, never the
plan), keep the restart-order and freeze-window rules, add the public-repo rule (never commit data/, logs, screenshots or
secrets; the PM's secret scan before a push); RUNBOOK additions (Redis password via Keychain item suryadhana-redis or
REDIS_PASSWORD, db_backup --offsite, the dead-man ping, the data-health page); the IMPROVEMENT_LOG entry describing ONLY what is
in the tree now (read the other builders' files; say plainly what is built but not deployed). Coordinate tooltip keys with
B4-UI through the files (B4 reads ${TV}/LEARN/tooltips.json if present; if B4 bundles its own copy, the validator checks they
match).` },
  { id: 'B8-STUDIES', phase: 'Build', owns: TV + '/studies/** (new), ' + TV + '/STUDIES.md (new), scripts/terminal_studies/** (new), tests/test_terminal_studies.py (new)',
    brief: `PLAN §1 B8 + Wave 3.3's precondition: write ${TV}/studies/<id>/PLAN.md pre-registered BEFORE any result for (a) IV-RV
spread and IV percentile as forecasts of next-20-session realised vol and of the next-20-session index return (the claim every
vendor implies), (b) index-driver persistence (does the 20-session leader's share persist 20 sessions ahead? does a driver
change precede anything?), (c) a GEX-style dealer-gamma proxy vs next-day range; each PLAN fixes the data (stored tables or the
cached F&O bhavcopies under data/nse_archive/fo/ read-only, or the R-IV / R-DRIVERS prototype outputs), the exact statistic,
the walk-forward split, the cost model (shared/trading_costs.py), the verdict rule (signed, |t| >= 2 in the full sample AND
both halves, after costs; else CONTEXT) and the negative controls. Then scripts/terminal_studies/*.py runnable on the stored
tables once the backfill exists; today run what is possible on the prototype outputs / cached files (read-only copies only,
never the live DuckDB file) and label results PROVISIONAL. ${TV}/STUDIES.md registry (id, hypothesis, status, PLAN path,
FINDINGS path). RSCH CATALOG rows go as patch requests to services/ui-api/routers/research.py. No study result reaches a badge
without the PM.` },
]
const B6 = { id: 'B6-GATES', phase: 'Gates', owns: 'tests/** (new gate files only + edits to tests/integration/test_gold_gates.py counts), scripts/ui_audit.py (TABS), scripts/ui_perf.py (budgets), scripts/tests/** (new files), ui/components/__tests__/terminal_v2.check.ts (new), .github/workflows/ci.yml, pyproject.toml (new)',
  brief: `PLAN 1.7 gates G1-G12 as code (G13 is the owner's), on the tree as the four Build-phase builders left it (their results
follow): G1 tests/unit/test_iv_eod.py facts (parity forward on the 3 Nov NIFTY fixture, untraded strikes → no IV, expiry-day
rows excluded from near, iv30_cm bracketing, rank vs percentile on a synthetic series, the legacy parser on fo01APR2022bhav,
model_version + r on every row) unless B1/F-BACKEND already cover them (then cite and add only what is missing); G2 the replay
of cached Oct-2026 files vs ${TV}/R-IV/iv_compare_NIFTY.csv within 0.05 vol-pt and corr >= 0.99 vs option_history.json (skip
with a clear reason when the cached files are absent on a CI runner); G3 drivers PIT/identity/split/1-Feb/fit/calibration/
hysteresis; G4 data-health catalog coverage (every ingest job and every page data source has a row; expected_by trading-day
aware; GAP rows; ingest_log sha256 dedupe; If-Modified-Since revision); G5 the static host/Yahoo scan over the new packages and
routers + Yahoo absent from /db/market-monitor; G6 the ui-api routes incl. zero outbound calls under a fake transport and the
margin fallback order; G7 concurrency (10 reads wall <= 2x single; /health <= 10 ms during the burst); G8 /metrics on the three
services + X-Request-ID + access log exclusions; G9 the UI static checks (IV percentile + rank defined, neutral token on context
panels, the regime strip suffix, SourceChip on every Panel, VIX once per page, unknown ?tab= toast) as a plain-node
terminal_v2.check.ts; G10 ui_audit TABS + ui_perf budgets updated (OMON chain ready <= 400 ms) — code only, the PM runs them;
G11 scripts/tests for the new jobs (missed_jobs, passes, iv_intraday skip without a session / past the budget, freeze-window
deferral); G12 CI: ruff/mypy/pin-drift/pip-audit steps in .github/workflows/ci.yml and a starter pyproject.toml (ruff select
F, E9, B, ASYNC, DTZ at line-length 130; mypy per package) that pass on the tree — scope rules so the existing code passes
(list what you excluded and why) rather than editing others' files. Every gate must FAIL on a negative control. Run all five
suites + tsc + the node checks at the end and report exact counts.` }

const buildPrompt = (b, extra) => COMMON + '\n## Your brief (' + b.id + ')\nYou own: ' + b.owns + '\n' + b.brief + (extra || '') + "\n\nReturn the structured result with builder='" + b.id + "'."
const checkPrompt = (b, r) => COMMON + '\n## Your role: adversarial check of ' + b.id + ' (read-only; same hard rules)\nVerify every "resolved" claim against the files and by re-running the tests named; check PLAN §0 principle by principle, point-in-time correctness and the vintage amendment, the host allowlist, secrets hygiene (public repo), ownership (did the builder edit files it does not own?), and that nothing reached the live stack. REJECT only for unresolved blockers/majors; list "claimed done but not" precisely.\n\n' + b.id + ' result:\n' + JSON.stringify(r, null, 1)

const run = (b, extra) => agent(buildPrompt(b, extra), { label: 'build:' + b.id, phase: b.phase, schema: RESULT_SCHEMA })
  .then((r) => r ? agent(checkPrompt(b, r), { label: 'check:' + b.id, phase: b.phase, schema: CHECK_SCHEMA }).then((c) => ({ build: r, check: c })) : null)

const built = await parallel(BUILDERS.map((b) => () => run(b)))
const summary = built.map((x, i) => x ? { builder: BUILDERS[i].id, summary: x.build.summary, files_changed: x.build.files_changed, check: x.check ? x.check.verdict : null, open_issues: x.build.open_issues } : { builder: BUILDERS[i].id, failed: true })
const gates = await run(B6, '\n\nBuild-phase results (summaries):\n' + JSON.stringify(summary, null, 1))
return { built, gates }
