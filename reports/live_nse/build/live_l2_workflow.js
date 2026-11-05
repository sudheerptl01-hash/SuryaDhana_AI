export const meta = {
  name: 'suryadhana-live-nse-l2',
  description: 'Live NSE round 2: close the four gaps the first round left (COMP history, results-reacting pricing, OSTR live chain seed, WTCH/news-dock NSE base layer), each adversarially checked',
  phases: [{ title: 'Build', detail: 'L2-API and L2-UI in parallel, a checker after each' }],
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


const STATE = `
## State after round 1 (read first)
Round 1 (wf_df86c180-058) is integrated and green, committed 69bf2e9 (not deployed; deploy tonight 21:37 IST with LIVE_TICKS=1).
Reports: ${LN}/L-INVENTORY/REPORT.md (92 panes), ${LN}/L-CAPACITY/REPORT.md, ${LN}/build/build.md (round-1 results + checks). The
live hook is ui/lib/liveQuotes.ts (useLiveQuotes, quoteSource/lineFor, overlayQuote, isStaleEod — an in-session EOD row's change
is yesterday's and is never today's move), ui/components/liveModel.ts; ui-api routers/live.py; data-service live_quotes.py.
Gates: tests/integration/test_live_gates.py (76) — keep them green and add to them for what you change.
`

const BUILDERS = [
  { id: 'L2-API', owns: 'services/ui-api/routers/{markets.py,news_scanner.py,live.py} (+ their tests under services/ui-api/tests/), services/data-service/main.py (one new GET route block only), tests/unit/test_live_*.py (new files only)',
    brief: `(1) A batch stored-close route for history panes: data-service GET /db/closes?symbols=A,B&days=N (from nse_bhavcopy, EQ/BE
series, split/bonus-adjusted the way shared/nse_panel does it, PIT: only sessions already stored) and ui-api GET /api/market/closes
(SWR 10 min) returning {as_of, source:'nse_bhavcopy', series:{SYM:[{date, close}]}}. (2) EVTS/BRF 'results reacting' (markets.py)
prices filers outside NSE's heatmap through Yahoo on the server: price them from /api/live/quotes (Breeze tick / NSE / stored close
with state), never Yahoo for an NSE symbol; keep the response keys, add source/age/state. (3) Verify and fix the news-scanner
quotes base layer for '.NS' symbols: name, 22-session spark and 52-week high/low must come from stored NSE data (bhavcopy), not
Yahoo, with the live price from the live service; prove with a fake transport that no Yahoo host is contacted for '.NS'. Tests
with negative controls; ui-api suite green.` },
  { id: 'L2-UI', owns: 'ui/components/{CompareView*,Compare*,StrategyBuilder.tsx,WatchMonitor.tsx,news/**} and the files those panes import that only they use, ui/lib/api.ts (new getters only), ui/components/__tests__/live.check.ts (additions only)',
    brief: `(1) COMP history from /api/market/closes (L2-API's route; build against the contract above, fixtures until it exists): label
'NSE closes · <last date>'; Yahoo only for non-NSE symbols the page already supports. (2) OSTR seeded from the live option chain in
session: when the market is open, the strategy builder takes spot/forward and leg prices from the live chain route the app already
has (find it: option-chain-live / option-chain-v3 via data-service nse_live) with its timestamp and a SourceChip (DELAYED · NSE ·
age — NSE's chain runs 34-92 s behind: never LIVE), the EOD chain after the close labelled CLOSE <date>; never change pricing math.
(3) WTCH and the news dock: NSE rows take spark/52-week/name from the NSE base layer (L2-API) and the live price from the hook; no
Yahoo request for an NSE row. tsc, every node check, live gates; screenshots of COMP, OSTR, WTCH against fixtures (scratch
server), read them.` },
]

const buildPrompt = (b) => COMMON + CONTRACT + STATE + '\n## Your brief (' + b.id + ')\nYou own: ' + b.owns + '\n' + b.brief + "\n\nReturn the structured result with builder='" + b.id + "'."
const checkPrompt = (b, r) => COMMON + CONTRACT + STATE + '\n## Your role: adversarial check of ' + b.id + ' (read-only; same hard rules)\nVerify every claim against the files and by re-running the tests; the contract, the honesty rules (no fake live, EOD labelled, never Yahoo for an NSE symbol), secrets hygiene, ownership, and that nothing reached the live stack. REJECT only for unresolved blockers/majors.\n\n' + b.id + ' result:\n' + JSON.stringify(r, null, 1)
const built = await parallel(BUILDERS.map((b) => () => agent(buildPrompt(b), { label: 'build:' + b.id, phase: 'Build', schema: RESULT_SCHEMA })
  .then((r) => r ? agent(checkPrompt(b, r), { label: 'check:' + b.id, phase: 'Build', schema: CHECK_SCHEMA }).then((c) => ({ build: r, check: c })) : null)))
return { built }
