export const meta = {
  name: 'suryadhana-live-nse',
  description: 'Live NSE data in every pane: survey every page and the Breeze tick capacity during market hours, then build the live quote service, API, UI adoption and gates (each adversarially checked)',
  phases: [
    { title: 'Survey', detail: 'L-INVENTORY (every page x pane x source x measured lag), L-CAPACITY (Breeze websocket scale + NSE live endpoints), read-only, parallel' },
    { title: 'Build', detail: 'LV-DATA, LV-API, LV-UI, LV-GATES in parallel against one contract, a checker after each' },
  ],
}

const ROOT = '/Users/sudheer/MahaKubera_108/SuryaDhana_AI'
const LN = ROOT + '/reports/live_nse'
const SCRATCH = '/Users/sudheer/.suryadhana_pm_scratch/live'
const P = '/Users/sudheer/Desktop/jupyter_env/bin/python'

const COMMON = `
You work on the SuryaDhana terminal (${ROOT}; read ${ROOT}/CLAUDE.md first). The owner's goal, verbatim (5 Nov 2026 10:10 IST):
"i need all the data to be live from the nse if i can get in all panes and all pages". Context: (1) the owner hovered tickers and
saw stale data — the hover card (TickerLink → HoverCard in ui/components/terminal/index.tsx) reads YAHOO via
/api/news-scanner/quotes (SWR cache: a display read is up to 60 s old, typically ~58 s; plus a 60 s client cache; no timestamp
shown; the sparkline is 22 DAILY closes). (2) WHO MOVED THE INDEX reads NSE's website APIs through data-service nse_live.py
(allIndices 15 s, heatmap-symbols 60 s caches; panel re-polls 2 min). (3) The PM probed the ICICI Breeze websocket at 10:00 today
(market open, separate process, read-only): ONE ws_connect carried the NIFTY 50 index + all 50 members — 6,850 ticks in 120 s
(~57/s; index ~10/s; members every 0.5-3.6 s), lag ltt→received median 0.65 s, p90 1.25 s, no REST quota used. Ticks are keyed
symbol "4.1!<NSE token>" (index "4.1!NIFTY 50"), NOT the isec code given to subscribe_feeds; map with
breeze.get_names(exchange_code='NSE', stock_code=SYM)['isec_token_level1'] (first token: HDFCBANK '4.1!1333 1462 17320' →
'4.1!1333'). Tick fields: avgPrice bPrice bQty change(% vs prev close) close(prev close) exchange high last low lowerCktLm ltq
ltt("Thu Nov  5 10:02:23 2026") open sPrice sQty stock_name symbol totalBuyQt totalSellQ trend ttq ttv upperCktLm. The probe
scripts: /Users/sudheer/.suryadhana_pm_scratch/breeze_tick_probe.py and breeze_tick_fields.py (reuse their pattern). The existing
tick engine services/data-service/live_ticks.py (default OFF via LIVE_TICKS) maps ticks by stock_code/isec → every tick lands
under "4.1!…" and no consumer finds it (the Sep "L1 ticks silent" note); MAX_SYMBOLS = 50 < index + 50 members.
Prior plans/evidence: reports/terminal_v2/PLAN.md (§0 binding principles — badges, store-then-show, SourceChip on every panel,
Breeze budget ledger shared/breeze_budget.py, host allowlist shared/http_client.py, freeze windows), reports/terminal_v2/R-DATA/
REPORT.md (45-row freshness matrix), R-UI/REPORT.md (page-by-page audit), R-ARCH/REPORT.md (push vs poll, backpressure),
reports/bloomberg_program/ (tick engine design + its verdicts), memory facts in CLAUDE.md. Terminal v2 wave 1 is COMMITTED but not
deployed (deploy tonight 21:37 IST); you build on the tree as it is.

## Honesty rules (binding)
Live means exchange data seconds old. Data NSE publishes only end-of-day or periodically (bhavcopy history, F&O bhavcopy,
participant OI, FII/DII, results, shareholding, deals, MTF, IV store, drivers history) CANNOT be live: never fake it; those panes
carry a SourceChip saying EOD + the publish date. Every live number shows its source (BREEZE LIVE / NSE LIVE / DELAYED age /
STALE / CLOSED) and age; after the close the last price is labelled CLOSE with the session date. Yahoo is never the source of an
NSE stock's live price on any page once a live NSE source answers (Yahoo stays only for non-NSE symbols: US, FX, commodities
the app already fetches through its single fetchers — never add a Yahoo caller).

## Hard rules
- LIVE STACK: GET only, paced (≤ 2/s); never restart anything, never start/stop services, never build-ui, never write data/ or
  data/market.duckdb, no POST/PUT/DELETE to :8010/:8001/:8008, no Telegram, never start or kill an ICICI login, never touch
  ui/dist, ui/.next, /Applications. Breeze: read-only market-data methods only (generate_session once per probe process,
  get_names, ws_connect/subscribe_feeds/unsubscribe_feeds/ws_disconnect, get_quotes ≤ 5 calls), never orders; never print .env
  values, tokens or session keys. NSE website APIs: at most a handful of GETs per endpoint, ≥ 1.2 s apart, through the existing
  cookie-primed client pattern (nse_live.py) — an Akamai ban would break the live terminal for everyone. NO Yahoo calls.
- The repo is pushed to a PUBLIC GitHub remote: never write credentials, account numbers, holdings, or PORT/BRKR/RSK/DESK
  screenshots into tracked files; the PM commits — you never run git commit/push/reset/checkout.
- Edit ONLY your owned paths; anything else is a patch request {file, old (unique exact substring of the current file), new,
  why}. ${P} only; no pip installs; no new npm deps; tests with negative controls; ruff --line-length 130, mypy (new code), tsc,
  the ui node checks and every suite you touch must end green (report exact counts).
- Scratch only in ${SCRATCH}/<your-id>/ (create it). Do NOT use SendMessage. Return the structured result.
`

const SURVEY_SCHEMA = {
  type: 'object',
  properties: {
    id: { type: 'string' }, report_path: { type: 'string' }, summary: { type: 'string' },
    rows: { type: 'array', items: { type: 'object', properties: {
      page: { type: 'string' }, pane: { type: 'string' }, current_source: { type: 'string' }, measured_lag: { type: 'string' },
      live_capable: { type: 'string', enum: ['yes-breeze', 'yes-nse-api', 'eod-only', 'periodic', 'n/a'] }, target_source: { type: 'string' },
      ui_file: { type: 'string' }, api_route: { type: 'string' } }, required: ['page', 'pane', 'current_source', 'live_capable', 'target_source'] } },
    facts: { type: 'array', items: { type: 'string' } },
    risks: { type: 'array', items: { type: 'string' } },
  },
  required: ['id', 'report_path', 'summary', 'rows', 'facts', 'risks'],
}
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
    deploy_notes: { type: 'array', items: { type: 'string' } },
    open_issues: { type: 'array', items: { type: 'string' } },
  },
  required: ['builder', 'summary', 'resolved', 'files_changed', 'tests_run', 'patch_requests', 'contract_notes', 'deploy_notes', 'open_issues'],
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

const CONTRACT = `
## The live contract (PM-fixed; every builder builds to it; contract_notes for any deviation, never a silent one)
data-service (LV-DATA):
- GET /live/quotes?symbols=A,B (≤ 300 NSE symbols incl. indices 'NIFTY 50', 'NIFTY BANK', 'INDIA VIX', ...) →
  {as_of, market: {state: 'open'|'pre-open'|'closed', session_date}, quotes: {SYM: {price, change, change_pct, prev_close, open,
  day_high, day_low, volume, value_cr, bid, ask, ltt (ISO with +05:30), source: 'breeze_ws'|'nse_api'|'eod', age_s, state:
  'live'|'delayed'|'stale'|'closed'|'unavailable', reason?}}}. Order of sources per symbol: the Breeze websocket tick (≤ 5 s old
  = live) → NSE website (heatmap/allIndices/equity quote endpoints that work; ≤ 90 s = delayed) → the last EOD close ('closed' after
  the session / 'stale' during it) — never Yahoo. Requesting a symbol ENSURES its subscription (union with TTL, as live_ticks.py
  does), the index + NIFTY 50 + NIFTY BANK members + holdings + watchlist pinned while the market is open.
- GET /live/status → {state OFF|CONNECTING|LIVE|DEGRADED|DISCONNECTED, subscribed, ticks_per_min, last_tick_age_s, cap,
  breeze_session: bool, nse_fallback: {ok, last_ok_at}}.
- live_ticks.py: token mapping fixed (isec_token_level1 first token → SYM, index streams included), cap raised to what L-CAPACITY
  measured safe (≤ 300), LIVE_TICKS default still OFF in code; the PM flips .env at deploy.
ui-api (LV-API):
- GET /api/live/quotes (same shape; ≤ 2 s SWR; single flight) and GET /api/live/status; /api/news-scanner/quotes for '.NS'
  symbols answers from /api/live/quotes (same body keys it has today + source/age/state), Yahoo only for non-NSE symbols.
- Optional push: a typed channel 'quotes' on the existing monitor WebSocket with a per-client bounded queue (drop-oldest) — polling
  at 2-5 s stays the baseline; never more than one data-service request per symbol batch per 2 s app-wide.
ui (LV-UI): one hook ui/lib/liveQuotes.ts (useLiveQuotes(symbols, {intervalMs}) → quote map + SourceInfo), adopted by every pane the
L-INVENTORY report marks yes-breeze / yes-nse-api, a SourceChip with source + age on each, EOD panes labelled with their date.
`

const SURVEYS = [
  { id: 'L-INVENTORY', brief: `Inventory EVERY page (the 43 in ui/components/desktop/pages.ts) and every pane on it that shows a price,
change, volume, breadth, OI, IV or a derived number: its UI file, its API route(s), the upstream source (Yahoo / NSE website API /
Breeze REST / Breeze ws / DuckDB EOD table / file), its cache TTLs end to end (server + client poll), and its MEASURED lag right now
(market is open: GET each route once, read as_of/time fields, compare with the clock; ≤ 2 GETs/s). Classify live_capable
(yes-breeze: an NSE-listed price the websocket can carry; yes-nse-api: an NSE live aggregate such as allIndices, heatmap,
market status, option-chain-v3, pre-open, most-active; eod-only; periodic; n/a) and the target source. Rank the work by how often
the owner sees the pane (BRF, WTCH, MOV, MKT, the hover card, the stock window, DESK, CHRT intraday, OMON/DERV underlying, tape
header first). Write ${LN}/L-INVENTORY/REPORT.md (executive summary first + the full table) and return rows[].` },
  { id: 'L-CAPACITY', brief: `Measure, during market hours, what the live sources can carry. (1) Breeze websocket scale: in ONE separate probe
process (never the live stack; the live tick engine is OFF so nothing competes), subscribe in steps of 50 → 100 → 200 → 300 NSE
cash symbols (NIFTY 50, NIFTY NEXT 50, NIFTY BANK, then liquid NIFTY 500 names from the stored universe) plus the indices
(NIFTY 50, NIFTY BANK, INDIA VIX if it streams — find the right stock_code/exchange for indices), 120 s per step: ticks/s, share
of symbols that ticked, inter-tick gaps, lag, any subscribe error or disconnect; stop at the first sign of throttling and report
the safe cap. Also: F&O streams (NIFTY near-future and an ATM option: exchange_code NFO, product_type futures/options with
expiry/strike/right) — do they tick, keyed how? (2) Breeze session rules: does a second process's generate_session or ws_connect
disturb another (test only if safe: open two probe clients, never touch the live stack's session)? (3) NSE website live endpoints
the app can use as fallback (allIndices, heatmap-symbols per index, marketStatus, quote-equity is 403 — confirm or find the
working equity quote path, live-analysis gainers/losers/most-active, option-chain-v3): a handful of paced GETs each, their update
cadence (compare two reads 30-60 s apart) and failure modes. Write ${LN}/L-CAPACITY/REPORT.md with the numbers and the
recommended cap, cadences and fallback order; return facts[] and risks[].` },
]

const BUILDERS = [
  { id: 'LV-DATA', owns: 'services/data-service/{live_ticks.py,nse_live.py,live_quotes.py (new)} + the /live/* routes in services/data-service/main.py (route block only), services/data-service/providers/icici_breeze_provider.py (token resolution only), tests/unit/test_live_*.py (new)',
    brief: `Implement the data-service half of the contract: fix live_ticks.py's token mapping (recorded-tick fixtures from the PM's probe
fields above; negative control: the old isec-keyed lookup finds nothing), the cap from L-CAPACITY, index streams, the pinned set,
live_quotes.py composing breeze_ws → nse_api → eod per symbol with source/age/state, the NSE fallback poller reusing nse_live.py's
client (cadence from L-CAPACITY, never faster), /live/quotes and /live/status. The watchdog/strike logic stays. Everything works
with LIVE_TICKS unset (NSE + EOD only) and with it set. Tests: mapping, cap/eviction, source order, closed-session labelling,
a fake Breeze client end to end, no Yahoo, no Breeze REST quote on the request path.` },
  { id: 'LV-API', owns: 'services/ui-api/routers/{live.py (new),news_scanner.py,quotes.py}, services/ui-api/main.py (router include line only), services/ui-api/tests/test_live_*.py (new)',
    brief: `Implement the ui-api half: /api/live/quotes + /api/live/status through shared/http_client.py (process-wide client, SWR ≤ 2 s,
single flight, stale-serve with state), the news-scanner quotes path answering '.NS' symbols from the live service (keep its
body keys; add source/age/state; Yahoo only for non-NSE), the existing /api/quotes/ticks (quotes.py) aligned to the same source,
the optional 'quotes' WebSocket channel with bounded per-client queues (or a documented reason to defer it). Tests incl. zero Yahoo
calls for '.NS' symbols under a fake transport and the fallback states.` },
  { id: 'LV-UI', owns: 'ui/lib/liveQuotes.ts (new), ui/components/** (adoption edits), ui/components/__tests__/live.check.ts (new)',
    brief: `Adopt the live hook across the panes L-INVENTORY ranked (do the top of the ranking fully before the tail; the hover card,
WTCH, MOV, BRF, MKT, the stock window, DESK, the tape header, CHRT's intraday last-price line, OMON/DERV underlying first): live
price/change with a SourceChip (source + age), the hover card's time + source line replacing "Yahoo · ≈1 min delayed", its
sparkline labelled as daily closes (or today's intraday path if the tick store gives it cheaply), EOD panes labelled EOD + date.
No page structure changes; keep every existing node check and the 43-page gates green; tsc; screenshots of the changed views
against fixtures (scratch server, read-only) — read them.` },
  { id: 'LV-GATES', owns: 'tests/integration/test_live_gates.py (new), scripts/ui_audit.py (live assertions only), scripts/tests/test_live_*.py (new)',
    brief: `Gates for the live program with negative controls: static — no Yahoo call reachable for an NSE symbol's display price
(scan the routers), every live pane in the inventory renders a SourceChip (scan the UI), the cap/pins/eviction rules, the token
mapping from recorded ticks; behavioural — /live/quotes source order under fake sources, CLOSE labelling after 15:30, stale
detection; ui_audit: a live-freshness assertion (a live pane's age ≤ 10 s while the market is open, skipped when closed). Run
everything and report counts.` },
]

const surveyPrompt = (s) => COMMON + '\n## Your id: ' + s.id + ' (Survey, read-only)\n' + s.brief + "\nReturn the JSON with id='" + s.id + "' and report_path='" + LN + '/' + s.id + "/REPORT.md'."
const buildPrompt = (b, survey) => COMMON + CONTRACT + '\n## Your brief (' + b.id + ')\nYou own: ' + b.owns + '\n' + b.brief + '\n\nSurvey results (read the two reports in full too):\n' + JSON.stringify(survey, null, 1) + "\n\nReturn the structured result with builder='" + b.id + "'."
const checkPrompt = (b, r) => COMMON + CONTRACT + '\n## Your role: adversarial check of ' + b.id + ' (read-only; same hard rules)\nVerify every claim against the files and by re-running the tests; the contract, the honesty rules (no fake live, EOD labelled, never Yahoo for an NSE live price), secrets hygiene, ownership, and that nothing reached the live stack. REJECT only for unresolved blockers/majors.\n\n' + b.id + ' result:\n' + JSON.stringify(r, null, 1)

const survey = await parallel(SURVEYS.map((s) => () => agent(surveyPrompt(s), { label: 'survey:' + s.id, phase: 'Survey', schema: SURVEY_SCHEMA })))
const brief = survey.map((s, i) => s ? { id: s.id, summary: s.summary, facts: s.facts, risks: s.risks, rows: s.rows.slice(0, 120) } : { id: SURVEYS[i].id, failed: true })
const built = await parallel(BUILDERS.map((b) => () => agent(buildPrompt(b, brief), { label: 'build:' + b.id, phase: 'Build', schema: RESULT_SCHEMA })
  .then((r) => r ? agent(checkPrompt(b, r), { label: 'check:' + b.id, phase: 'Build', schema: CHECK_SCHEMA }).then((c) => ({ build: r, check: c })) : null)))
return { survey, built }
