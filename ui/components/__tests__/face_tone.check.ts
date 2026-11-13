/**
 * FINAL ROUND C-FACE + D-TONE checks (reports/terminal_final/PLAN.md W6; risk/TRUST_GAPS.md G3/G5/G7/G8), every rule
 * with a negative control:
 *
 *  Q  G5 quiet-LIVE face cue: a quiet row's chip reads 'LIVE·q' on the FACE (the 120 s policy window is untouched —
 *     the qualification logic is b67fb56's); the trade age stays in the hover; a loud row keeps the plain LIVE face;
 *     a pane is 'LIVE·q' only when EVERY live row is quiet.
 *  F  G7 source word on chip faces: 'DELAYED · RISK ENGINE · 15:03', never a bare clock; parentheticals stay
 *     hover-only; short faces unchanged; date faces unchanged.
 *  S  D-TONE session-aware staleness: the default sourceOf rule is NSE-session aware (≥ 2 Mon–Fri sessions behind the
 *     last expected session → STALE), so a 2-session lag no longer reads as a calm 'EOD · <day>'; an explicit
 *     maxAgeDays keeps the plain calendar rule; weekend-safe.
 *  V  applyCatalogVerdict: red/gap → the STALE treatment with the face keeping its own date; amber → hover only;
 *     live/input/reference never downgraded.
 *  C  G8 DataStaleChip faces: fetch error keeps the last good count greyed with '?'; never-good error says 'DATA ?';
 *     404 (not deployed) renders nothing; fresh/stale faces unchanged.
 *  T  footer DATA-date tone: amber when behind the last NSE session (health last_session first, Mon–Fri calendar
 *     fallback, 21:30 IST cutoff, weekend-safe).
 *  W  wiring scans: the chip no longer vanishes on error (no setN(null)); the footer span carries the tone.
 *  X  F-27 (ROUND 3): the catalog verdict is WIRED into the SourceChip path — useCatalogTone in dataHealthStore
 *     (one shared store read per window, no per-panel fetch), the ten catalogued panel files call it with their
 *     dataset ids, a red fixture tones the chip while the face keeps its own date/as-of, a fresh fixture returns
 *     the identical SourceInfo (so a fresh live state renders bit-identically), and gold/ stays untouched.
 *
 * Run with plain node ≥ 22.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/face_tone.check.ts
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type SourceMod = typeof import('../terminal/source')
type LiveMod = typeof import('../../lib/liveQuotes')
type CoreMod = typeof import('../../lib/dataHealthCore')
const S = (await import(new URL('../terminal/source.ts', import.meta.url).href)) as SourceMod
const LQ = (await import(new URL('../../lib/liveQuotes.ts', import.meta.url).href)) as LiveMod
const DH = (await import(new URL('../../lib/dataHealthCore.ts', import.meta.url).href)) as CoreMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const read = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// Fri 13 Nov 2026 15:01 IST (the trust audit's live state)
const NOW = Date.UTC(2026, 10, 13, 9, 31, 0)
const iso = (ms: number) => `${new Date(ms + 330 * 60_000).toISOString().slice(0, 19)}+05:30`
type Row = import('../../lib/liveQuotes').LiveQuote
const row = (over: Partial<Row> = {}): Row => ({
  symbol: 'RELIANCE', price: 1480.5, change: 12.3, change_pct: 0.84, prev_close: 1468.2, open: 1470, day_high: 1485, day_low: 1466,
  volume: 1_234_567, value_cr: 182.4, bid: 1480.4, ask: 1480.6, ltt: iso(NOW - 1_000), source: 'breeze_ws', age_s: 1, state: 'live',
  reason: null, received_at: NOW, ...over,
})
const OPEN = { state: 'open' as const, session_date: '2026-11-13' }

// ── Q. G5 quiet-LIVE face cue ───────────────────────────────────────────────────────────────────────────────────
{
  const quiet = row({ symbol: 'ABB', ltt: iso(NOW - 92_000), age_s: 92, reason: 'quiet: no new trade or quote for 92 s on a healthy feed', quiet: true })
  const qi = LQ.quoteSource(quiet, OPEN, NOW + 1_000)
  check('Q1 a quiet row\'s SourceInfo carries quiet: true (the policy window itself is untouched)', qi.state === 'live' && qi.quiet === true, qi)
  const qLabel = S.sourceChipText(qi, new Date(NOW + 1_000)).label
  check('Q1 the FACE reads LIVE·q (the on-face cue, not hover-only)', qLabel === 'LIVE·q · BREEZE · 1s', qLabel)
  check('Q1 the hover keeps the trade age', /quiet: no trade for \d+m/.test(qi.hint ?? '') && /last trade/.test(qi.hint ?? ''), qi.hint)
  const loud = LQ.quoteSource(row(), OPEN, NOW + 1_000)
  check('Q2 negative: a loud LIVE row keeps the plain LIVE face', loud.quiet !== true && S.sourceChipText(loud, new Date(NOW + 1_000)).label === 'LIVE · BREEZE · 2s',
    S.sourceChipText(loud, new Date(NOW + 1_000)))
  // the pane chip: LIVE·q only when EVERY live row is quiet
  const allQuiet = LQ.liveSourceInfo([quiet, row({ symbol: 'TCS', ltt: iso(NOW - 80_000), age_s: 80, reason: 'quiet: no new trade for 80 s', quiet: true })], OPEN, 'ok', NOW + 1_000)
  check('Q3 a pane of only quiet rows reads LIVE·q', allQuiet?.quiet === true && S.sourceChipText(allQuiet!, new Date(NOW + 1_000)).label.startsWith('LIVE·q'), allQuiet)
  const mixedPane = LQ.liveSourceInfo([quiet, row()], OPEN, 'ok', NOW + 1_000)
  check('Q3 negative: one loud row keeps the plain LIVE pane face', mixedPane?.quiet !== true && S.sourceChipText(mixedPane!, new Date(NOW + 1_000)).label.startsWith('LIVE ·'), mixedPane)
}

// ── F. G7 source word on the face ──────────────────────────────────────────────────────────────────────────────
{
  const now = new Date(NOW)
  const rsk = S.sourceOf(iso(NOW - 120_000), { source: 'risk engine (Desk ledger + broker book)', now, maxAgeDays: 1 })
  check('F1 the face carries the source word, parenthetical hover-only (G7: DELAYED · RISK ENGINE · 15:03)',
    S.sourceChipText(rsk, now).label === 'DELAYED · RISK ENGINE · 14:59', S.sourceChipText(rsk, now))
  check('F1 the hover keeps the full source text', /risk engine \(Desk ledger \+ broker book\)/i.test(S.sourceChipText(rsk, now).title), S.sourceChipText(rsk, now).title)
  const book = S.sourceOf(iso(NOW - 11 * 60_000), { source: 'ICICI book file', now, maxAgeDays: 1 })
  check('F1 a 15-char source word fits the face whole', S.sourceChipText(book, now).label === 'DELAYED · ICICI BOOK FILE · 14:50', S.sourceChipText(book, now))
  check('F2 faceSource trims word-by-word to 18 chars', S.faceSource('ui-api /api/data/health') === 'UI-API' && S.faceSource('NSE F&O bhavcopy') === 'NSE F&O BHAVCOPY'
    && S.faceSource('risk engine (Desk ledger + broker book)') === 'RISK ENGINE' && S.faceSource(null) === '', S.faceSource('ui-api /api/data/health'))
  check('F2 a single over-long word is cut with an ellipsis', S.faceSource('ABCDEFGHIJKLMNOPQRSTU') === 'ABCDEFGHIJKLMNOPQ…', S.faceSource('ABCDEFGHIJKLMNOPQRSTU'))
  check('F3 negative: a short source face is unchanged (YAHOO), and a date face carries the date, not the word',
    S.sourceChipText(S.sourceOf(iso(NOW - 60_000), { source: 'Yahoo', now, maxAgeDays: 1 }), now).label === 'DELAYED · YAHOO · 15:00'
    && S.sourceChipText(S.sourceOf('2026-11-10T15:30:00+05:30', { source: 'NSE', now, maxAgeDays: 9 }), now).label === 'DELAYED · 10 NOV')
}

// ── S. session-aware default staleness (D-TONE G3) ─────────────────────────────────────────────────────────────
{
  const now = new Date(NOW)                                             // Fri 13 Nov 15:01 IST → last expected session Thu 12 Nov
  check('S1 the shared helper: last expected NSE session day', S.lastExpectedNseSessionDay(now) === '2026-11-12'
    && S.lastExpectedNseSessionDay(new Date(Date.UTC(2026, 10, 13, 16, 30))) === '2026-11-13'   // Fri 22:00 IST: today counts after 21:30
    && S.lastExpectedNseSessionDay(new Date(Date.UTC(2026, 10, 14, 6, 0))) === '2026-11-13'     // Sat → Friday
    && S.lastExpectedNseSessionDay(new Date(Date.UTC(2026, 10, 15, 6, 0))) === '2026-11-13'     // Sun → Friday
    && S.lastExpectedNseSessionDay(new Date(Date.UTC(2026, 10, 16, 6, 0))) === '2026-11-13')    // Mon 11:30 IST → Friday
  check('S2 sessions behind: the trust audit\'s live case (ohlcv as-of Mon 9 Nov on Fri 13 Nov)', S.nseSessionsBehind('2026-11-09', now) === 3
    && S.nseSessionsBehind('2026-11-12', now) === 0 && S.nseSessionsBehind('2026-11-11', now) === 1 && S.nseSessionsBehind(null, now) === null)
  check('S3 a 2-session lag reads STALE with the date on the face (was a calm EOD · <day>)',
    S.sourceOf('2026-11-10', { source: 'NSE', now }).state === 'stale'
    && S.sourceChipText(S.sourceOf('2026-11-10', { source: 'NSE', now }), now).label === 'STALE · 10 NOV'
    && /sessions behind/.test(S.sourceOf('2026-11-10', { source: 'NSE', now }).hint ?? ''), S.sourceOf('2026-11-10', { source: 'NSE', now }))
  check('S4 one session behind stays EOD (calm)', S.sourceOf('2026-11-11', { source: 'NSE', now }).state === 'delayed'
    && S.sourceChipText(S.sourceOf('2026-11-11', { source: 'NSE', now }), now).label === 'EOD · 11 NOV')
  check('S5 weekend-safe: Friday data is current all weekend and Monday until the evening pass',
    S.sourceOf('2026-11-13', { now: new Date(Date.UTC(2026, 10, 15, 14, 0)) }).state === 'delayed'       // Sun 19:30 IST
    && S.sourceOf('2026-11-13', { now: new Date(Date.UTC(2026, 10, 16, 6, 0)) }).state === 'delayed')    // Mon 11:30 IST
  check('S6 negative: an explicit maxAgeDays keeps the plain calendar rule', S.sourceOf('2026-11-10', { now, maxAgeDays: 10 }).state === 'delayed'
    && S.sourceOf('2026-11-10', { now, maxAgeDays: null }).state === 'delayed'
    && S.sourceOf('2026-11-01', { now, maxAgeDays: 4 }).state === 'stale')
}

// ── V. applyCatalogVerdict ─────────────────────────────────────────────────────────────────────────────────────
{
  const now = new Date(NOW)
  const eod = S.sourceOf('2026-11-12', { source: 'NSE', now })
  const red = S.applyCatalogVerdict(eod, 'red', '2 sessions behind')
  check('V1 red → the STALE treatment, the face keeps its own date', red.state === 'stale'
    && S.sourceChipText(red, now).label === 'STALE · 12 NOV' && /catalog: red — 2 sessions behind \(SYS › DATA\)/.test(red.hint ?? ''), red)
  const amber = S.applyCatalogVerdict(eod, 'amber', null)
  check('V2 amber → hover names the verdict, the face is unchanged', amber.state === 'delayed'
    && S.sourceChipText(amber, now).label === 'EOD · 12 NOV' && /catalog: amber \(SYS › DATA\)/.test(amber.hint ?? ''), amber)
  check('V3 fresh/live/unknown verdicts change nothing', S.applyCatalogVerdict(eod, 'fresh') === eod && S.applyCatalogVerdict(eod, null) === eod
    && S.applyCatalogVerdict(eod, 'weird') === eod)
  const live = S.sourceOf(iso(NOW), { live: true, source: 'Breeze', now })
  check('V4 negative: a live chip is never downgraded by a catalog verdict', S.applyCatalogVerdict(live, 'red') === live
    && S.applyCatalogVerdict(S.inputSource('your legs'), 'red').state === 'input')
}

// ── C. G8 DataStaleChip faces ──────────────────────────────────────────────────────────────────────────────────
{
  const good: import('../datahealth/healthModel').DataHealth = {
    as_of: iso(NOW), last_session: '2026-11-12', catalog_source: 'dataset_catalog', inputs_unavailable: {}, controller_online: true,
    note: '', summary: { green: 20, amber: 1, red: 1, gaps: 0 },
    rows: [
      { id: 'ohlcv', label: 'NSE EOD closes', pages: ['EQS'], publisher: 'NSE', published_ist: null, expected_by: '21:00', as_of: '2026-11-09',
        lag_sessions: 2, state: 'red', unrecoverable: false, job_id: null, last_run: null, next_run: null, catchup_at: null, note: '', dictionary_anchor: null },
      { id: 'iv_surface_daily', label: 'IV surface', pages: ['OMON'], publisher: 'derived', published_ist: null, expected_by: '21:00', as_of: '2026-11-12',
        lag_sessions: 0, state: 'amber', unrecoverable: false, job_id: null, last_run: null, next_run: null, catchup_at: null, note: '', dictionary_anchor: null },
    ],
  }
  const okSnap = { status: 'ok' as const, data: good, lastGoodAt: NOW, error: null }
  const okFace = DH.staleChipFace(okSnap)
  check('C1 a good read: DATA n STALE, amber, names the bad rows', okFace?.label === 'DATA 2 STALE' && okFace.tone === 'warn' && okFace.n === 2
    && /NSE EOD closes \(red\)/.test(okFace.title), okFace)
  const freshFace = DH.staleChipFace({ ...okSnap, data: { ...good, summary: { green: 22, amber: 0, red: 0, gaps: 0 } } })
  check('C2 all fresh: DATA FRESH, muted', freshFace?.label === 'DATA FRESH' && freshFace.tone === 'ok' && freshFace.n === 0, freshFace)
  const errAfter = DH.staleChipFace({ status: 'error', data: good, lastGoodAt: NOW, error: 'HTTP 503' })
  check('C3 G8: a fetch error keeps the last good count greyed with ? (never silently absent)', errAfter?.label === 'DATA 2 STALE ?'
    && errAfter.tone === 'unknown' && /unreachable/.test(errAfter.title) && /last reading/.test(errAfter.title), errAfter)
  const errNever = DH.staleChipFace({ status: 'error', data: null, lastGoodAt: null, error: 'network' })
  check('C4 G8: never-good error reads DATA ? — distinguishable from DATA FRESH and from not-deployed', errNever?.label === 'DATA ?'
    && errNever.tone === 'unknown' && /unreachable/.test(errNever.title), errNever)
  check('C5 negative: a 404 (pre-v2, not deployed) still renders nothing — the chip never guesses',
    DH.staleChipFace({ status: 'missing', data: null, lastGoodAt: null, error: '404' }) === null
    && DH.staleChipFace({ status: 'idle', data: null, lastGoodAt: null, error: null }) === null)
  const missAfter = DH.staleChipFace({ status: 'missing', data: good, lastGoodAt: NOW, error: '404' })
  check('C6 a 404 AFTER a good read (a rollback) keeps the greyed last count', missAfter?.label === 'DATA 2 STALE ?' && missAfter.tone === 'unknown', missAfter)
  check('C7 catalogVerdictOf reads one row\'s verdict', DH.catalogVerdictOf(okSnap, 'ohlcv')?.state === 'red'
    && DH.catalogVerdictOf(okSnap, 'ohlcv')?.note === '2 sessions behind' && DH.catalogVerdictOf(okSnap, 'nope') === null)
}

// ── T. footer DATA-date tone ───────────────────────────────────────────────────────────────────────────────────
{
  const now = new Date(NOW)                                             // Fri 13 Nov 15:01 IST
  const behind = S.footerDataTone('2026-11-09', '2026-11-12', now)
  check('T1 behind the last NSE session (health last_session) → amber with the honest title', behind.amber === true
    && /stored 2026-11-09/.test(behind.title) && /last NSE session 2026-11-12/.test(behind.title) && /SYS › DATA/.test(behind.title), behind)
  check('T2 current → calm', S.footerDataTone('2026-11-12', '2026-11-12', now).amber === false)
  check('T3 no health answer → the Mon–Fri calendar fallback, weekend-safe', S.footerDataTone('2026-11-09', null, now).amber === true
    && S.footerDataTone('2026-11-13', null, new Date(Date.UTC(2026, 10, 15, 14, 0))).amber === false  // Friday data on Sunday evening
    && /Mon–Fri calendar/.test(S.footerDataTone('2026-11-09', null, now).title))
  check('T4 negative: the health service\'s holiday-aware last_session outranks the calendar',
    S.footerDataTone('2026-11-11', '2026-11-11', now).amber === false                                 // calendar would say 12 Nov
    && S.footerDataTone('2026-11-11', null, now).amber === true)
  check('T5 an unknown date never ambers; an invalid last_session falls back to the calendar',
    S.footerDataTone(null, null, now).amber === false && S.footerDataTone('—', null, now).amber === false
    && S.footerDataTone('2026-11-09', 'garbage', now).amber === true)
}

// ── W. wiring scans ────────────────────────────────────────────────────────────────────────────────────────────
{
  const dv = read('components/datahealth/DataHealthView.tsx')
  check('W1 the chip reads the shared store and no longer vanishes on error', /staleChipFace\(snap\)/.test(dv) && /useDataHealthStore\(\)/.test(dv)
    && !/setN\(null\)/.test(dv))
  check('W1 negative control: the old vanish-on-error pattern is what the scan catches', /setN\(null\)/.test('.catch(() => { if (alive) setN(null) })'))
  const pg = read('app/page.tsx')
  check('W2 the footer DATA date carries the tone + title (D-TONE G3)', /useFooterDataTone\(dashboard\?\.latest_date \?\? null\)/.test(pg)
    && /data-data-behind=\{dataTone\.amber \? '1' : undefined\}/.test(pg) && /title=\{dataTone\.title\}/.test(pg))
  check('W2 the footer keeps its three phone-collapsible segments (M36)', (pg.match(/className="sd-foot-opt"/g) ?? []).length === 3)
  const lv = read('lib/liveQuotes.ts')
  check('W3 the quiet policy window is untouched (no new constant, no qualification change)', !/QUIET_LIVE/.test(lv.replace(/\*.*?QUIET_LIVE_S.*/g, ''))
    || /data-service QUIET_LIVE_S/.test(lv))
}

// ── X. F-27: the catalog verdict wired into the SourceChip path (ROUND 3) ──────────────────────────────────────
{
  const now = new Date(NOW)
  // the end-to-end pure path a wired panel takes: store snapshot → catalogVerdictOf → applyCatalogVerdict → chip text
  const redSnap = {
    status: 'ok' as const, lastGoodAt: NOW, error: null,
    data: {
      as_of: iso(NOW), last_session: '2026-11-12', catalog_source: 'dataset_catalog', inputs_unavailable: {}, controller_online: true,
      note: '', summary: { green: 20, amber: 0, red: 1, gaps: 0 },
      rows: [
        { id: 'market_monitor', label: 'Market monitor', pages: ['MKT'], publisher: 'derived', published_ist: null, expected_by: '19:00',
          as_of: '2026-11-09', lag_sessions: 3, state: 'red', unrecoverable: false, job_id: null, last_run: null, next_run: null, catchup_at: null, note: '', dictionary_anchor: null },
        { id: 'iv_summary_daily', label: 'IV summary', pages: ['OMON'], publisher: 'derived', published_ist: null, expected_by: '21:30',
          as_of: '2026-11-12', lag_sessions: 0, state: 'fresh', unrecoverable: false, job_id: null, last_run: null, next_run: null, catchup_at: null, note: '', dictionary_anchor: null },
      ],
    } as import('../datahealth/healthModel').DataHealth,
  }
  const wire = (info: import('../terminal/source').SourceInfo, datasetId: string) => {
    const v = DH.catalogVerdictOf(redSnap, datasetId)
    return v ? S.applyCatalogVerdict(info, v.state, v.note) : info
  }
  const eod = S.sourceOf('2026-11-12', { source: 'NSE EOD', now, maxAgeDays: 7 })
  const toned = wire(eod, 'market_monitor')
  check('X1 a red catalog verdict tones the wired chip STALE while the face keeps its own date', toned.state === 'stale'
    && S.sourceChipText(toned, now).label === 'STALE · 12 NOV' && /catalog: red — 3 sessions behind \(SYS › DATA\)/.test(toned.hint ?? ''), toned)
  check('X1 the panel keeps its as-of through the toning (data-sd-asof unchanged)', toned.asOf === eod.asOf && toned.asOf === '2026-11-12', toned)
  check('X2 a fresh verdict returns the IDENTICAL SourceInfo — a fresh live state renders bit-identically',
    wire(eod, 'iv_summary_daily') === eod && wire(eod, 'not-in-catalog') === eod)

  // the React half: one shared store read, no per-panel fetch fan-out
  const store = read('lib/dataHealthStore.ts')
  check('X3 useCatalogTone exists and rides the shared store (useDataHealthStore + catalogVerdictOf + applyCatalogVerdict)',
    /export function useCatalogTone\(\)/.test(store) && /const s = useDataHealthStore\(\)/.test(store)
    && /catalogVerdictOf\(s, datasetId\)/.test(store) && /applyCatalogVerdict\(info, v\.state, v\.note\)/.test(store))
  check('X3 the store still fetches /api/data/health in exactly one place (no fan-out)',
    (store.match(/fetch\(/g) ?? []).length === 1 && /fetch\('\/api\/data\/health'/.test(store))

  // the ten wired panel files: each imports the hook and tones with its dataset id (OWNED.txt, r3-tone)
  const WIRED: [string, string][] = [
    ['components/MarketMonitor.tsx', 'market_monitor'],
    ['components/WarehouseHealth.tsx', 'ohlcv'],
    ['components/DataExplorerTab.tsx', 'ml_features'],
    ['components/vol/VolView.tsx', 'iv_summary_daily'],
    ['components/vol/IvStrip.tsx', 'iv_summary_daily'],
    ['components/vol/IvHistoryChart.tsx', 'iv_summary_daily'],
    ['components/DerivativesDesk.tsx', 'nse_fo_daily'],
    ['components/OptionChain.tsx', 'option_chain_eod'],
    ['components/ParticipantPositioning.tsx', 'nse_participant_oi'],
    ['components/DealsMonitor.tsx', 'nse_deals'],
  ]
  for (const [rel, ds] of WIRED) {
    const src = read(rel)
    check(`X4 ${rel} wires catTone(sourceOf(…), '${ds}') through the shared hook`,
      /import \{ useCatalogTone \} from '@\/lib\/dataHealthStore'/.test(src)
      && /const catTone = useCatalogTone\(\)/.test(src)
      && src.includes(`), '${ds}')`) && /catTone\(sourceOf\(/.test(src)
      && !/fetch\('\/api\/data\/health'/.test(src), rel)
  }
  check('X4 VolView also tones its iv_expiry_daily panels', read('components/vol/VolView.tsx').includes(`), 'iv_expiry_daily')`))
  check('X4 DerivativesDesk also tones the VIX panel by vix_daily', read('components/DerivativesDesk.tsx').includes(`), 'vix_daily')`))
  check('X5 negative: gold/ is untouched (its catalog already gates rendering)',
    !fs.readdirSync(path.join(UI, 'components/gold')).some(f => f.endsWith('.tsx') && /useCatalogTone/.test(read(`components/gold/${f}`))))
}

console.log(`face_tone.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
