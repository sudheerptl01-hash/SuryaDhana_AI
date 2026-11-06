/**
 * The typed alert engine's UI half (lib/alertsEngine.ts; PLAN 2.3, review M41 / m084 / m085): the builder's form ↔ rule
 * body, the presets, the direction-word scan (and its parity with the server's vocabulary), the fired inbox grouping,
 * the create-alert hand-off, and the inbox hints for a stale FII figure or an unlabelled breadth universe. Every rule
 * with a negative control.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/lib/__tests__/alertsEngine.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'

type EngineMod = typeof import('../alertsEngine')
const A = (await import(new URL('../alertsEngine.ts', import.meta.url).href)) as EngineMod
const ROOT = new URL('../../../', import.meta.url)

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// the catalogue as GET /api/alerts/series serves it (a subset, same shape)
const K = (kind: string, params: string[], ops: string[], extra: Partial<Kind> = {}): Kind => ({
  kind, label: `{symbol} ${kind}`, unit: '%', badge: 'arithmetic', cadence: 'eod', params, optional: [], ops: ops as any, source: 's', group: 'options',
  definition: 'd', example: 'e', history: true, category: false, ...extra,
})
const KINDS = [
  K('price', ['symbol'], ['above', 'below', 'cross_up', 'cross_down', 'change_pct'], { unit: '₹', cadence: 'live', history: false }),
  K('iv_pctile', ['symbol'], ['above', 'below', 'cross_up', 'cross_down'], { unit: 'pctile' }),
  K('iv30', ['symbol'], ['above', 'below', 'cross_up', 'cross_down', 'change_pct', 'pctile_above', 'pctile_below']),
  K('oi_strike', ['symbol', 'strike', 'side'], ['above', 'below', 'cross_up', 'cross_down', 'change_pct'], { optional: ['expiry'], unit: 'contracts' }),
  K('oi_wall', ['symbol', 'side'], ['changed', 'above', 'below', 'cross_up', 'cross_down'], { optional: ['expiry'], unit: 'strike' }),
  K('fo_ban', ['symbol'], ['cross_up', 'cross_down', 'changed'], { unit: 'flag' }),
  K('fii_net', [], ['above', 'below', 'pctile_above', 'pctile_below'], { unit: '₹ cr' }),
  K('vix', [], ['change_pct', 'above'], { unit: '', cadence: 'live' }),
  K('nifty_driver', ['index'], ['changed'], { unit: 'label', category: true }),
  K('gold_health', [], ['changed'], { unit: 'label', category: true }),
  K('data_stale', ['dataset'], ['above', 'cross_up', 'cross_down', 'changed', 'below'], { unit: 'flag' }),
  K('results_days', ['symbol'], ['below', 'above'], { unit: 'days' }),
  K('iv_rv', ['symbol'], ['below', 'above'], { unit: 'vol pts' }),
  K('skew25', ['symbol'], ['pctile_above', 'above'], { unit: 'vol pts' }),
  K('rollover', ['symbol'], ['above', 'below']),
  K('rollover_pace', ['symbol'], ['above', 'below', 'cross_up', 'cross_down'], { unit: 'pp', history: false }),
  K('basis', ['symbol'], ['above', 'below']),
]
type Form = import('../alertsEngine').DraftForm
type Kind = import('../alertsEngine').SeriesKind
function form(o: Partial<Form>): Form {
  return { kind: 'iv_pctile', params: { symbol: 'NIFTY' }, op: 'above', value: '80', window: '', cooldown: '', repeat: 'repeat', channel: 'both', note: '', ...o }
}

// ── series ids and the builder ─────────────────────────────────────────────────────────────────────────────────
{
  check('ids: params in order, optional appended', A.seriesId(KINDS[3] as any, { symbol: 'NIFTY', strike: 24500, side: 'CE', expiry: '2026-11-24' }) === 'oi_strike:NIFTY:24500:CE:2026-11-24')
  check('ids: a missing required param → null', A.seriesId(KINDS[3] as any, { symbol: 'NIFTY', side: 'CE' }) === null)
  const ok = A.draftFromForm(form({ params: { symbol: 'nifty' } }), KINDS as any)
  check('form → draft: symbol upper-cased, numbers parsed', ok.draft?.series === 'iv_pctile:NIFTY' && ok.draft?.value === 80 && ok.problem === '', ok)
  const oi = A.draftFromForm(form({ kind: 'oi_strike', op: 'change_pct', value: '25', params: { symbol: 'NIFTY', strike: '24500', side: 'ce' } }), KINDS as any)
  check('form → draft: a strike rule', oi.draft?.series === 'oi_strike:NIFTY:24500:CE', oi)
  check('form → draft: changed takes no value', A.draftFromForm(form({ kind: 'oi_wall', op: 'changed', value: '', params: { symbol: 'NIFTY', side: 'PE' } }), KINDS as any).draft?.value === null)
  check('form → draft: a flag op may omit its value (the server uses 0.5)', A.draftFromForm(form({ kind: 'fo_ban', op: 'cross_up', value: '' }), KINDS as any).draft !== null)
  const bad: [string, Partial<Form>][] = [
    ['no value', { value: '' }], ['op not of the kind', { kind: 'fo_ban', op: 'above' }], ['percentile > 100', { kind: 'iv30', op: 'pctile_above', value: '120' }],
    ['bad symbol', { params: { symbol: 'TATA MOTORS' } }], ['bad strike', { kind: 'oi_strike', params: { symbol: 'NIFTY', strike: 'x', side: 'CE' } }],
    ['bad expiry', { kind: 'oi_wall', op: 'changed', params: { symbol: 'NIFTY', side: 'CE', expiry: '24-11-2026' } }],
    ['direction word in the note', { note: 'buy calls on the breakout' }], ['unknown kind', { kind: 'nope' }],
  ]
  for (const [why, o] of bad) check(`form → draft refuses: ${why}`, A.draftFromForm(form(o), KINDS as any).draft === null, o)
  check('negative control: the same form with a plain note passes', A.draftFromForm(form({ note: 'results on 9 Nov' }), KINDS as any).draft?.note === 'results on 9 Nov')
  const back = A.formFromDraft({ series: 'oi_strike:NIFTY:24500:CE', op: 'change_pct', value: 25 }, KINDS as any)
  check('draft → form round trip', back?.kind === 'oi_strike' && back.params.strike === '24500' && back.params.side === 'CE' && back.value === '25' && back.op === 'change_pct')
  check('draft → form: unknown series → null', A.formFromDraft({ series: 'bogus:X', op: 'above', value: 1 }, KINDS as any) === null)
}

// ── presets: valid against the catalogue, direction-free ─────────────────────────────────────────────────────────
{
  const broken = A.PRESETS.filter(p => { const f = A.formFromDraft(p.draft('TCS'), KINDS as any); return !f || A.draftFromForm(f, KINDS as any).draft === null })
  check('every preset becomes a valid rule', broken.length === 0, broken.map(p => p.id))
  check('presets cover IV, OI, ban, results, VIX, FII, driver, gold, data', ['ivp80', 'wallce', 'banin', 'banout', 'res5', 'vix10', 'fii95', 'driver', 'gold', 'stale'].every(id => A.PRESETS.some(p => p.id === id)))
}

// ── direction words ───────────────────────────────────────────────────────────────────────────────────────────
{
  const texts = [...Object.values(A.OP_LABEL), ...Object.values(A.CHANNEL_LABEL), ...A.PRESETS.map(p => p.label)]
  const dirty = texts.filter(t => A.directionWords(t).length)
  check('no op label, channel or preset carries a direction word', dirty.length === 0, dirty)
  check('negative control: the scan sees them', A.directionWords('Bullish BREAKOUT, buy now').join(',') === 'breakout,bullish,buy' && A.directionWords('IV likely to rise')[0] === 'likely to rise')
  check('position names are allowed', A.directionWords('short strangle breakeven · short-option minimum').length === 0)
  // parity with the server's vocabulary (services/ui-api/alert_engine.py DIRECTION_PATTERNS)
  const py = fs.readFileSync(new URL('services/ui-api/alert_engine.py', ROOT), 'utf8')
  const block = py.split('DIRECTION_PATTERNS: tuple[str, ...] = (')[1]?.split('\n)')[0] ?? ''
  const server = [...block.matchAll(/r"([^"]+)"/g)].map(m => m[1].replace(/\\\\/g, '\\'))
  check('the UI vocabulary equals the server one', server.length > 20 && server.length === A.DIRECTION_PATTERNS.length && server.every((p, i) => p === A.DIRECTION_PATTERNS[i]), { server, ui: A.DIRECTION_PATTERNS })
  const allowed = [...(py.split('ALLOWED_PHRASES: tuple[str, ...] = (')[1]?.split(')')[0] ?? '').matchAll(/"([^"]+)"/g)].map(m => m[1])
  check('the allowed phrases equal the server ones', allowed.length >= 14 && JSON.stringify(allowed) === JSON.stringify(A.ALLOWED_PHRASES), allowed)
  const noteBlock = py.split('NOTE_PATTERNS: tuple[str, ...] = (')[1]?.split('\n)')[0] ?? ''
  const noteServer = [...noteBlock.matchAll(/r"([^"]+)"/g)].map(m => m[1].replace(/\\\\/g, '\\'))
  check('the note-only patterns equal the server ones', noteServer.length === 5 && JSON.stringify(noteServer) === JSON.stringify(A.NOTE_PATTERNS), { noteServer, ui: A.NOTE_PATTERNS })
  // round-2 review: position names pass on both sides, predictive notes do not (the server's note_words)
  const okNotes = ['LONG straddle wing', 'long strangle breakeven', 'long call 25000 · short put 24000', 'under the expected move', 'short straddle adjusted']
  const badNotes = ['bounce expected', 'goes higher from here', 'IV heading lower', 'go long straddle', 'higher highs', 'it could fall']
  check('notes: position names pass, long and short alike', okNotes.every(n => A.noteWords(n).length === 0), okNotes.map(n => [n, A.noteWords(n)]))
  check('notes: predictive phrasing is refused', badNotes.every(n => A.noteWords(n).length > 0), badNotes.map(n => [n, A.noteWords(n)]))
  check('notes: the builder refuses a predictive note', A.draftFromForm(form({ note: 'bounce expected' }), KINDS as any).draft === null)
  check('negative control: the plain direction scan alone passes "bounce expected" (why notes need the second list)', A.directionWords('bounce expected').length === 0)
  // the ALRT page's own static strings
  const page = fs.readFileSync(new URL('ui/components/AlertsCenter.tsx', ROOT), 'utf8')
  const literals = [...page.matchAll(/(?:label|subtitle|title|empty)="([^"]+)"/g)].map(m => m[1])
  const pageDirty = literals.filter(t => A.directionWords(t).length)
  check('ALRT labels, titles and empty texts are direction-free', literals.length > 10 && pageDirty.length === 0, pageDirty)
  check('ALRT draws no rule state in green / red (context is never coloured as direction)', !/satisfied \? T\.green|satisfied \? T\.red|T\.green : T\.red/.test(page))
  check('negative control: the colour scan sees the old fired-panel colouring', /T\.green : T\.red/.test("color: (h.change_pct ?? 0) >= 0 ? T.green : T.red"))
}

// ── fired inbox grouping ──────────────────────────────────────────────────────────────────────────────────────
{
  const f = (seq: number, symbol: string | null, at: string) => ({ seq, origin: 'rule' as const, rule_id: 'r', series: 's', kind: 'k', symbol, at, as_of: null, text: 't', channel: 'both', badge: 'context' })
  const g = A.groupFires([f(1, 'NIFTY', '2026-11-06T09:30'), f(2, 'TCS', '2026-11-06T10:04'), f(3, 'NIFTY', '2026-11-06T10:05'), f(4, null, '2026-11-06T08:00')])
  check('groups by symbol, newest group first, newest fire first', g.map(x => `${x.symbol}:${x.count}`).join(',') === 'NIFTY:2,TCS:1,—:1' && g[0].fires[0].seq === 3, g)
  check('state words are neutral', A.ruleStateText({ status: 'snoozed', snooze_until: '2026-11-06T11:30:00+05:30', state: {} }) === 'snoozed to 11:30'
    && A.ruleStateText({ status: 'active', snooze_until: null, state: { last_error: 'x' } }) === 'no reading' && A.ruleStateText({ status: 'fired', snooze_until: null, state: {} }) === 'fired (one-shot)')
  check('values in the server units', A.fmtAlertValue(14974.68, '₹ cr') === '+₹14,975 cr' && A.fmtAlertValue(-3.4, 'vol pts') === '−3.40 vol pts' && A.fmtAlertValue(1, 'days') === '1 day' && A.fmtAlertValue('ICICIBANK', 'label') === 'ICICIBANK' && A.fmtAlertValue(null, '%') === '—')
}

// ── chart alert lines (CHRT) ──────────────────────────────────────────────────────────────────────────────────
{
  const rules = [
    { series: 'price:TCS', op: 'above' as const, value: 3300, status: 'active' as const },
    { series: 'price:TCS', op: 'cross_down' as const, value: 2900, status: 'snoozed' as const },
    { series: 'price:TCS', op: 'change_pct' as const, value: 3, status: 'active' as const },         // a move %, not a level
    { series: 'price:TCS', op: 'below' as const, value: 3100, status: 'fired' as const },            // spent
    { series: 'price:INFY', op: 'above' as const, value: 1600, status: 'active' as const },
    { series: 'price:TCS', op: 'above' as const, value: 3300, status: 'active' as const },
  ]
  check('chart lines: the live level rules on the symbol, unique, ascending', JSON.stringify(A.alertLevelsFor(rules, 'tcs.ns')) === '[2900,3300]')
  check('chart lines negative control: another symbol draws its own only', JSON.stringify(A.alertLevelsFor(rules, 'INFY')) === '[1600]' && A.alertLevelsFor(rules, 'SBIN').length === 0)
}

// ── the hand-off ──────────────────────────────────────────────────────────────────────────────────────────────
{
  const d = A.parseDraft(JSON.stringify({ series: 'price:NIFTY', op: 'cross_up', value: 25000, channel: 'telegram' }))
  check('a stored draft parses', d?.series === 'price:NIFTY' && d.op === 'cross_up' && d.value === 25000 && d.channel === 'telegram' && d.repeat === 'repeat')
  check('negative control: junk never crashes ALRT', A.parseDraft('{not json') === null && A.parseDraft(JSON.stringify({ series: 'x', op: 'explode' })) === null && A.parseDraft(null) === null)
  const lib = fs.readFileSync(new URL('ui/lib/alerts.ts', ROOT), 'utf8')
  check('lib/alerts.ts exports draftAlert + createAlert for other pages', /export function draftAlert\(draft: AlertRuleDraft\)/.test(lib) && /export async function createAlert\(draft: AlertRuleDraft\)/.test(lib) && lib.includes("goToPage('alerts')"))
}

// ── inbox hints (m084 stale FII / DII; m085 breadth universe) ───────────────────────────────────────────────────
{
  const stale = A.noteHints('morning', '2026-10-30T08:50:00+05:30', 'GIFT NIFTY implies +0.3% · FII +4,240 cr / DII -1,250 cr (2026-10-27) · 69 reported')
  check('m084: the 30 Oct note quoting 27 Oct FII / DII is flagged (2 weekdays: 28, 29 Oct), holidays not counted without the master', stale.length === 1 && stale[0].startsWith('FII / DII here are from 2026-10-27: 2 weekdays older') && stale[0].includes('NSE holidays not counted'), stale)
  // round-2 review: with NSE's holiday master the hint counts sessions
  const cover = { days: new Set(['2026-11-10']), from: '2026-07-01' }
  const sess = A.noteHints('morning', '2026-10-30T08:50:00+05:30', 'FII +4,240 cr / DII -1,250 cr (2026-10-27) · 69 reported', cover)
  check('m084: with the holiday master it counts NSE sessions', sess.length === 1 && sess[0].startsWith('FII / DII here are from 2026-10-27: 2 NSE sessions older') && !sess[0].includes('weekday'), sess)
  const afterHoliday = A.noteHints('morning', '2026-11-11T08:50:00+05:30', 'FII +1 cr / DII +2 cr (2026-11-09)', cover)
  check('m084: the morning after a weekday holiday quoting the previous session is not flagged', afterHoliday.length === 0, afterHoliday)
  const noCover = A.noteHints('morning', '2026-11-11T08:50:00+05:30', 'FII +1 cr / DII +2 cr (2026-11-09)')
  check('m084 negative control: without the master the same note reads 1 weekday (holidays not counted)', noCover.length === 1 && noCover[0].includes('1 weekday older') && noCover[0].includes('NSE holidays not counted'), noCover)
  check('m084: a span before the master\'s coverage falls back to weekdays', A.daysBetween('2026-06-01', '2026-06-04', cover).sessions === false && A.daysBetween('2026-11-09', '2026-11-11', cover).n === 0)
  const fresh = A.noteHints('morning', '2026-11-05T08:50:00+05:30', 'FII +7,284 cr / DII −3,712 cr (2026-11-04) · 139 reported')
  check('m084 negative control: the previous session is not flagged', fresh.length === 0, fresh)
  check('m084: a Monday note quoting Friday is not flagged', A.noteHints('morning', '2026-11-09T08:50:00+05:30', 'FII +1 cr / DII +2 cr (2026-11-06)').length === 0)
  const wrap = A.noteHints('wrap', '2026-10-30T21:00:00+05:30', 'Market wrap 2026-10-30: NIFTY +0.51% · breadth 239/1,148 · FII +₹3,599 cr · regime 0/4')
  check('m085: the wrap breadth names its universe and the count the note carries (239 + 1,148)', wrap.length === 1 && wrap[0].includes('liquid NSE universe') && wrap[0].includes('NIFTY 500') && wrap[0].includes('1,387 counted in this note'), wrap)
  const wrap2 = A.noteHints('wrap', '2026-11-05T21:08:04+05:30', 'NIFTY +2.40% · breadth 950/440 · FII +₹14,975 cr · regime 0/4')
  check('m085 negative control: another note carries its own count (no constant)', wrap2.length === 1 && wrap2[0].includes('1,390 counted') && !/about 1,400/.test(wrap2[0]), wrap2)
  check('m085: no hard-coded universe size in the source', !/about 1,400 stocks/.test(fs.readFileSync(new URL('ui/lib/alertsEngine.ts', ROOT), 'utf8')))
  check('m085 negative control: the close note (labelled NIFTY 500) gets no hint', A.noteHints('close', '2026-10-30T15:40:00+05:30', 'NIFTY 500 breadth 120 up / 379 down').length === 0)
  check('no double hint once the note says it (the m084 / m085 source patches)',
    A.noteHints('morning', '2026-10-30T08:50:00+05:30', 'FII +4,240 cr / DII -1,250 cr (2026-10-27) — 2 weekdays older than the previous session').length === 0
    && A.noteHints('wrap', '2026-11-05T21:08:00+05:30', 'NIFTY +2.40% · breadth 950/440 (liquid NSE universe) · FII +₹14,975 cr').length === 0)
  const page = fs.readFileSync(new URL('ui/components/AlertsCenter.tsx', ROOT), 'utf8')
  check('ALRT renders the hints under each inbox message, with the holiday master', page.includes('noteHints(n.kind, n.at, String(n.body ?? \'\'), cover)') && page.includes('holidaysFromEco(d.events)') && page.includes("d.holidays_known === true || (d.holidays_known === undefined && days.size > 0)"))
}

// ── phone layout (M36: ALRT was 601 px wide at a 390 px viewport) ───────────────────────────────────────────────
{
  const page = fs.readFileSync(new URL('ui/components/AlertsCenter.tsx', ROOT), 'utf8')
  check('M36: the two top panels stack below 460 px (auto-fit), never a fixed two-column split', page.includes("repeat(auto-fit, minmax(min(100%, 460px), 1fr))") && !page.includes("gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)'"))
  const tables = (page.match(/<DataTable/g) ?? []).length
  const wrapped = (page.match(/<div style=\{SCROLL_X\}>\s*<DataTable/g) ?? []).length
  check('M36: every table scrolls inside its panel', tables >= 4 && wrapped === tables, { tables, wrapped })
}

// ── round-2 review: units, the iv_rv label, the Rules badge, one banner, the GO hand-off ─────────────────────────
{
  check('values: OI in contracts, pace in pp', A.fmtAlertValue(89536, 'contracts') === '89,536 contracts' && A.fmtAlertValue(1234.5, 'contracts') === '1,234.5 contracts'
    && A.fmtAlertValue(13.2, 'pp') === '+13.2 pp' && A.fmtAlertValue(-4, 'pp') === '−4.0 pp')
  const ivrv = A.PRESETS.find(p => p.id === 'ivrv')
  check('the IV − RV preset names the close-to-close estimator its column holds (V-VOL M01)', !!ivrv && ivrv.label.includes('(cc)') && !/yang|zhang|\bYZ\b/i.test(ivrv.label), ivrv?.label)
  check('negative control: the estimator scan sees a Yang-Zhang label', /yang|zhang|\bYZ\b/i.test('IV − RV20 (YZ) ≤ −3 vol pts'))
  const page = fs.readFileSync(new URL('ui/components/AlertsCenter.tsx', ROOT), 'utf8')
  const rulesPanel = /<Panel title=\{`Rules · \$\{rules\.length\}`\}[^>]*>/s.exec(page)?.[0] ?? ''
  check('the Rules panel carries no single badge (its rows mix arithmetic and context)', rulesPanel.length > 0 && !/\bbadge=/.test(rulesPanel), rulesPanel)
  check('negative control: the round-1 panel line is caught', /\bbadge=/.test('<Panel title={`Rules · ${rules.length}`} accent={T.amber} pad={0} style={{ marginTop: 12 }} badge="arithmetic">'))
  const lib = fs.readFileSync(new URL('ui/lib/alerts.ts', ROOT), 'utf8')
  check('one banner: the page stays silent while the scheduler dispatches (page_notify)', /export function notifyHits\(hits: AlertHit\[\]\): void \{\n\s+if \(!pageNotify\) return/.test(lib)
    && lib.includes('notePageNotify((await runPriceAlerts()).data)') && /pageNotify = v !== false/.test(lib))
}

// ── the GO hand-off `ALRT TCS >3200` (U-PLATFORM writes it; ALRT reads it once) ───────────────────────────────────
{
  type GoMod = typeof import('../goAliases')
  const G = (await import(new URL('../goAliases.ts', import.meta.url).href)) as GoMod
  const now = Date.parse('2026-11-06T10:00:00+05:30')
  const written = (o: object) => JSON.stringify({ ...o, at: new Date(now - 5_000).toISOString() })   // what CommandBar.tsx stores
  const stock = A.prefillTarget(G.parseAlertPrefill(written({ symbol: 'TCS', op: 'above', level: 3200 }), now))
  check('GO: `ALRT TCS >3200` fills the price form at or over 3200', stock?.target === 'price' && stock.sym === 'TCS' && stock.above === '3200' && stock.below === '', stock)
  const below = A.prefillTarget(G.parseAlertPrefill(written({ symbol: 'INFY', op: 'below', level: 1450.5 }), now))
  check('GO: `<` fills the at-or-under box', below?.target === 'price' && below.below === '1450.5' && below.above === '', below)
  const ix = A.prefillTarget(G.parseAlertPrefill(written({ symbol: 'NIFTY', op: 'above', level: 25000 }), now))
  check('GO: an index fills the typed builder (price:NIFTY above 25000, one-shot)', ix?.target === 'rule' && ix.draft.series === 'price:NIFTY' && ix.draft.op === 'above' && ix.draft.value === 25000 && ix.draft.repeat === 'once', ix)
  const f = ix?.target === 'rule' ? A.formFromDraft(ix.draft, KINDS as any) : null
  check('GO: the index draft is a valid builder form', !!f && A.draftFromForm(f, KINDS as any).draft?.series === 'price:NIFTY')
  const stale = JSON.stringify({ symbol: 'TCS', op: 'above', level: 3200, at: new Date(now - 10 * 60_000).toISOString() })
  check('GO negative control: a stale or malformed hand-off fills nothing', A.prefillTarget(G.parseAlertPrefill(stale, now)) === null
    && A.prefillTarget(G.parseAlertPrefill('{junk', now)) === null && A.prefillTarget(G.parseAlertPrefill(written({ symbol: 'TCS', op: 'above', level: -1 }), now)) === null)
  const page = fs.readFileSync(new URL('ui/components/AlertsCenter.tsx', ROOT), 'utf8')
  check('ALRT reads the GO key once (then removes it) and listens to its event', page.includes('localStorage.getItem(ALRT_PREFILL_KEY)') && page.includes('localStorage.removeItem(ALRT_PREFILL_KEY)')
    && page.includes('prefillTarget(parseAlertPrefill(raw, Date.now()))') && page.includes('window.addEventListener(ALRT_PREFILL_EVENT, adoptPrefill)'))
  const bar = fs.readFileSync(new URL('ui/components/CommandBar.tsx', ROOT), 'utf8')
  check('the writer: CommandBar stores {symbol, op, level, at} under the same key', /handOff\(ALRT_PREFILL_KEY, \{ symbol: cmd\.sym, op: cmd\.op, level: cmd\.level, at: new Date\(\)\.toISOString\(\) \}, ALRT_PREFILL_EVENT\)/.test(bar))
}

console.log(`alertsEngine.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
