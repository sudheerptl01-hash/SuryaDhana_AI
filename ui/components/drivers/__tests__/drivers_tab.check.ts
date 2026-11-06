/**
 * MEMB drivers tab honesty (review M46 / m025 / m027 / m028, D-DATA 6 Nov), every rule with a negative control:
 *
 *  T  the route's `tab` state: degraded / insufficient grey the horizon points, sectors, concentration and the monthly
 *     board, with one note above the table and a caption on each greyed panel; `ok` (or an older ui-api with no tab)
 *     changes nothing. The degraded note prints no MAE (the fit chip does: the same number once per page).
 *  C  the pending challenger line in the regime strip ends "describes, does not predict", once.
 *  F  members' heuristic flags (⚑ on P/E, profit y/y, revenue y/y; the heuristic badge and the route's rule).
 *  M  the monthly board's SourceChip date is the route's as_of (the last stored session), not the month's first day.
 *
 * Run with plain node ≥ 22.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/drivers/__tests__/drivers_tab.check.ts
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type DriversMod = typeof import('../driversModel')
type SourceMod = typeof import('../../terminal/source')
const D = (await import(new URL('../driversModel.ts', import.meta.url).href)) as DriversMod
const S = (await import(new URL('../../terminal/source.ts', import.meta.url).href)) as SourceMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

// ── T. tab state ───────────────────────────────────────────────────────────────────────────────────
{
  // the live NIFTY BANK payload on 6 Nov 2026 (drivers_NIFTY_BANK_ytd.json): 2 sessions stored
  const insufficient = { state: 'insufficient', sessions: 2, sentence: 'only 2 sessions of attribution stored (since 2026-11-04): the backfill has not run, so horizons longer than that are not shown in full' }
  const vi = D.tabView(insufficient)
  check('T1 insufficient greys the tab and prints the route sentence', vi.grey && vi.state === 'insufficient' && vi.label === 'HISTORY INSUFFICIENT' && vi.caption === insufficient.sentence, vi)
  const degraded = { state: 'degraded', sessions: 60, sentence: 'the weights miss the index by 37 pts a day on average over 60 sessions (bar 25): members\' points are approximate; the residual is shown' }
  const vd = D.tabView(degraded)
  check('T1 degraded greys the tab', vd.grey && vd.label === 'FIT DEGRADED', vd)
  check('T1 the degraded note does not repeat the MAE the fit chip prints (same number once per page)', !/\b37\b/.test(vd.caption ?? '') && !/\b60\b/.test(vd.caption ?? ''), vd.caption)
  check('T1 negative control: the route sentence itself carries the MAE', /\b37\b/.test(degraded.sentence))
  const ok = D.tabView({ state: 'ok', sessions: 120, sentence: 'weights explain the index within 9 pts a day over 120 sessions' })
  check('T2 ok changes nothing', !ok.grey && ok.caption === null && ok.state === 'ok')
  check('T2 an older ui-api (no tab) changes nothing', !D.tabView(undefined).grey && !D.tabView(null).grey && !D.tabView({}).grey)
  check('T2 an unknown state is not greyed', !D.tabView({ state: 'bogus' }).grey)
  check('T3 a greyed panel is captioned, an ok one is not', D.tabPanelCaption(vi) === 'HISTORY INSUFFICIENT · read with the note above the table' && D.tabPanelCaption(ok) === null)
  check('T3 an insufficient tab without a sentence still says why', (D.tabView({ state: 'insufficient' }).caption ?? '').includes('backfill has not run'))
}

// ── C. challenger ──────────────────────────────────────────────────────────────────────────────────
{
  // live 6 Nov 2026 09:07 IST: ICICIBANK leads the raw 20-session points, 1 of 5 sessions
  const route = { symbol: 'ICICIBANK', sessions_leading: 1, sessions_needed: 4,
    sentence: 'ICICIBANK leads the raw 20-session points; the label changes after 5 consecutive sessions (1 so far) — describes, does not predict' }
  const line = D.challengerLine(route) ?? ''
  check('C1 the challenger line ends the describes clause exactly once', line.endsWith(S.DESCRIBES) && line.split(S.DESCRIBES).length === 2, line)
  const bare = D.challengerLine({ symbol: 'HDFCBANK', sessions_leading: 2, sessions_needed: 3 }) ?? ''
  check('C1 without a route sentence it is built and still ends that way', bare.startsWith('HDFCBANK leads the raw points (2 of 5') && bare.endsWith(S.DESCRIBES), bare)
  check('C1 negative control: no challenger, no line', D.challengerLine(null) === null && D.challengerLine({ symbol: null }) === null)
  check('C2 no direction words in the challenger line', !/\b(bullish|bearish|buy|sell)\b/i.test(line + bare))
}

// ── F. flags ───────────────────────────────────────────────────────────────────────────────────────
{
  const coal = ['pat_yoy_outlier', 'revenue_yoy_outlier']
  check('F1 flag words', JSON.stringify(D.flagWords(coal)) === JSON.stringify(['profit y/y beyond ±200 %', 'revenue y/y beyond ±200 %']) && D.flagWords(['pe_distorted'])[0] === 'P/E outside 3–150×')
  check('F1 each flag marks its own cell', D.flagCell(coal, 'pat') && D.flagCell(coal, 'rev') && !D.flagCell(coal, 'pe') && D.flagCell(['pe_distorted'], 'pe'))
  check('F1 negative control: no flags mark nothing', !D.flagCell([], 'pe') && !D.flagCell(undefined, 'pat') && D.flagWords(null).length === 0)
  check('F1 an unknown code passes through in words', D.flagWords(['new_rule_x'])[0] === 'new rule x')
}

// ── M. monthly as-of ───────────────────────────────────────────────────────────────────────────────
{
  const now = { as_of: '2026-11-05', as_of_month: '2026-11', months: [{ month: '2026-10' }, { month: '2026-11' }] }
  check('M1 the route as_of (last stored session) is the chip date', D.monthlyAsOf(now) === '2026-11-05')
  const oldClient = `${now.months[now.months.length - 1].month}-01`.slice(0, 10)
  check('M1 negative control: the old client derivation read 01 NOV', oldClient === '2026-11-01' && oldClient !== D.monthlyAsOf(now))
  check('M1 an older ui-api (as_of = the month) falls back to the month', D.monthlyAsOf({ as_of: '2026-11', months: [{ month: '2026-11' }] }) === '2026-11-01')
  check('M1 nothing stored: no date', D.monthlyAsOf({ as_of: null, months: [] }) === null && D.monthlyAsOf(null) === null)
}

// ── W. wiring (static) ─────────────────────────────────────────────────────────────────────────────
{
  const dv = src('components/drivers/DriversView.tsx')
  const im = src('components/IndexMembers.tsx')
  check('W1 the tab note renders the state on MEMB', /data-drivers-tab=\{v\.state\}/.test(dv) && im.includes('<DriversTabNotice d={drv.data} />'))
  check('W1 sectors / concentration and the monthly board sit in TabGrey', /<TabGrey tab=\{tab\}>\s*<div[^>]*>\s*<SectorContribution[\s\S]{0,120}<ConcentrationChart/.test(im)
    && im.includes('<TabGrey tab={tab}><MonthlyLeaderboard index={index} /></TabGrey>'))
  check('W1 the horizon PTS and share columns grey with the tab', (im.match(/greyCell\(<span/g) ?? []).length === 2 && im.includes('const tv = tabView(tab)'))
  check('W2 the regime strip prints the challenger through challengerLine', /data-driver-challenger/.test(dv) && dv.includes('challengerLine(d?.driver?.challenger)'))
  check('W3 flags on P/E, profit and revenue with the heuristic badge and the rule', ["flagged(r, 'pe'", "flagged(r, 'pat'", "flagged(r, 'rev'"].every(k => im.includes(k))
    && im.includes("<BadgeChip badge={ext.flag_badge ?? 'heuristic'} />") && im.includes('ext.flag_rule'))
  check('W4 the monthly chip reads monthlyAsOf, the old month-first-day expression is gone', dv.includes('sourceOf(monthlyAsOf(m.data)') && !dv.includes('.month}-01`.slice(0, 10)'))
  check('W5 MEMB names where today\'s explained points come from', im.includes('ext.explained_source ??') && im.includes('they explain ${fmtSigned(d.explained_points, 1)} of'))
  check('W6 the greyed views draw no green / red (context stays neutral)', !/T\.(green|red)\b/.test(dv))
  check('W6 negative control: the scan sees a T.green', /T\.(green|red)\b/.test('color: T.green'))
}

console.log(`drivers_tab.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
