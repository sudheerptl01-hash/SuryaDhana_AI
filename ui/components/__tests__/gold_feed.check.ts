/**
 * GOLD feed-honesty checks (8 Nov 2026 RCA, lane G-FEED) — every rule with a negative control.
 *
 *  CT-03 / F2 / C-DATA-01  a scheduled COT release that has passed with nothing stored is NAMED, before the `next …`
 *                          label (which keeps meaning the next upcoming release, API_CONTRACT §2.5), and the
 *                          `catch_up_note` the server now sends is rendered instead of sitting unused in types.ts.
 *  CT-04 / F3              the coverage row says where the loaded Forex Factory week ends; amber only when something
 *                          real is missing; HEALTH's "the whole week, nothing cut off" copy is gone.
 *  CT-06                   the tape's ΔOI scope is the SERVER's label, not a hard-coded 'all <FAM> expiries'; WEEKLY
 *                          keeps the family sum in its own column, flagged when it holds an expiring month's run-off;
 *                          a settle chip names which stand-in it is and never appears on an empty cell.
 *  F6                      h.open's model stays GOLD 1 kg and says so, and the pick is priced from `contract_fair`
 *                          (the server's own pick-relative verdict) — see the patch request if HealthView/GoldPreOpen
 *                          has not landed yet.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/gold_feed.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type FeedMod = typeof import('../gold/feedModel')
const F = (await import(new URL('../gold/feedModel.ts', import.meta.url).href)) as FeedMod

const here = path.dirname(new URL(import.meta.url).pathname)
const ui = path.resolve(here, '..', '..')
const read = (rel: string) => fs.readFileSync(path.join(ui, rel), 'utf8')

let failures = 0
function check(name: string, ok: boolean): void {
  if (!ok) failures += 1
  console.log(`${ok ? 'ok  ' : 'FAIL'}  ${name}`)
}

const src = {
  positioning: read('components/gold/PositioningView.tsx'),
  weekly: read('components/gold/WeeklyView.tsx'),
  monthly: read('components/gold/MonthlyView.tsx'),
  bits: read('components/gold/ViewBits.tsx'),
  model: read('components/gold/feedModel.ts'),
  // read, not owned: DAILY's tape still invents its own scope. Asserted below so the gap shows in this suite's output
  // instead of being implied by a check named 'POSITIONING and DAILY' that only ever read PositioningView.
  daily: read('components/gold/DailyView.tsx'),
}
const day = (d: string) => (d === '2026-11-03' ? 'Tue 03 Nov' : d === '2026-11-10' ? 'Tue 10 Nov' : null)

// ══ CT-03 / F2 / C-DATA-01 ═══════════════════════════════════════════════════════════════════════════════════════

const oneDue = { report_date: '2026-10-27', stale: true, next_release_ist: 'Tue 17 Nov 02:00 IST',
                 overdue: [{ report_date: '2026-11-03', at: '2026-11-07T02:00+05:30', ist: 'Sat 07 Nov 02:00 IST' }] }
const twoDue = { ...oneDue, overdue: [...oneDue.overdue, { report_date: '2026-11-10', ist: 'Tue 17 Nov 02:00 IST' }] }
const caughtUp = { report_date: '2026-11-03', stale: false, next_release_ist: 'Tue 17 Nov 02:00 IST', overdue: [] }

check('CT-03: the newest due-but-unstored report is named, with "due", never "released"',
  F.cotOverdueWords(oneDue, day) === 'overdue: Tue 03 Nov report due Sat 07 Nov 02:00 IST — not stored yet')
check('CT-03: more than one missed week is counted',
  F.cotOverdueWords(twoDue, day) === 'overdue: Tue 10 Nov report due Tue 17 Nov 02:00 IST — not stored yet · 2 reports behind')
check('CT-03 negative control: a caught-up store, a missing field and a null payload all say nothing',
  F.cotOverdueWords(caughtUp, day) === null && F.cotOverdueWords({ report_date: '2026-11-03' }, day) === null
  && F.cotOverdueWords(null, day) === null && F.cotOverdueRows({ overdue: 'nope' }).length === 0)
check('CT-03: POSITIONING prints the overdue span and the server\'s catch_up_note (neither was rendered anywhere before)',
  /data-cot-overdue/.test(src.positioning) && /cotOverdueLine\(c\.latest\)/.test(src.positioning)
  && /data-cot-catchup/.test(src.positioning) && /c\.latest\.catch_up_note/.test(src.positioning))
check('CT-03: the overdue clause comes BEFORE `next …` in WEEKLY\'s one-line read, and `next` is still printed',
  src.weekly.indexOf('cotOverdueWords(c.latest, dayLabel)') < src.weekly.indexOf('parts.push(`next ')
  && /next_release_ist/.test(src.weekly))

// ══ CT-04 / F3: the US calendar's coverage ════════════════════════════════════════════════════════════════════════

const stale = { state: 'stale', note: 'US releases loaded through Sat 07 Nov …', covers_through_label: 'Sat 07 Nov', uncovered: ['2026-11-09'] }
const dim = { state: 'delayed', note: 'US releases loaded through Sat 14 Nov …', covers_through_label: 'Sat 14 Nov', uncovered: ['2026-11-16'] }
check('CT-04: the subtitle names where the loaded week ends',
  F.coverageSubtitle(stale) === 'US through Sat 07 Nov' && F.coverageSubtitle({ state: 'live' }) === null && F.coverageSubtitle(null) === null)
check('CT-04: amber only when the window is mostly uncovered or the feed is empty (1–2 days is dim)',
  F.coverageIsAmber(stale) && F.coverageIsAmber({ state: 'unavailable' }) && !F.coverageIsAmber(dim) && !F.coverageIsAmber({ state: 'live' }) && !F.coverageIsAmber(null))
check('CT-04: the coverage row is a shared component keyed on the server\'s state, and prints nothing without a note',
  /export function CoverageNote/.test(src.bits) && /data-coverage-note=\{cov\.state/.test(src.bits) && /if \(!cov\?\.note\) return null/.test(src.bits))
// HealthView's own copyB ("the whole week, nothing cut off") and MacroView's "US calendar this week" title belong to the
// HEALTH/MACRO lane: they are a patch request on this fix, not an assertion here. The views this lane owns must claim no
// completeness of their own, and ViewBits' note must carry the coverage end rather than a bare "this week".
check('CT-04: the views this lane owns claim no complete week of their own',
  !/nothing cut off|the whole week/.test(src.positioning + src.weekly + src.monthly)
  && /covers_through_label/.test(src.model))

// ══ CT-06: the MCX tape's two scopes ═════════════════════════════════════════════════════════════════════════════

const tape = [
  { trade_date: '2026-11-03', doi: 2227, doi_family: -9871, family_mechanical: true, label: 'short build-up' },
  { trade_date: '2026-11-05', doi: 1281, doi_family: 1476, family_mechanical: false, label: 'long build-up' },
  { trade_date: 'bad' as unknown as string, doi: 1 },
]
const doi = F.tapeDoiByDate(tape)
check('CT-06: both scopes are read per session, and the family flag only where the server set it',
  doi.get('2026-11-03')?.doi === 2227 && doi.get('2026-11-03')?.family === -9871 && doi.get('2026-11-03')?.familyMech === true
  && doi.get('2026-11-05')?.familyMech === false && doi.get('bad')?.doi === 1)
check('CT-06 negative control: a row without a date, a null tape and non-numeric fields add nothing',
  F.tapeDoiByDate(null).size === 0 && F.tapeDoiByDate([{ doi: 5 }]).size === 0
  && F.tapeDoiByDate([{ trade_date: 'd', doi: 'x', doi_family: null }]).get('d')?.doi === null)
check('CT-06: the scope label is the server\'s, with the family fallback only when it sent none',
  F.tapeScopeLabel({ tape_oi_scope: 'GOLDM DEC-26' }, 'GOLDM') === 'GOLDM DEC-26'
  && F.tapeScopeLabel({}, 'GOLDTEN') === 'all GOLDTEN expiries' && F.tapeScopeLabel(null, 'GOLD') === 'all GOLD expiries')
check('CT-06: POSITIONING no longer hard-codes the tape\'s scope; it comes from tapeScopeLabel',
  /oiScope=\{tapeScopeLabel\(data, fam\)\}/.test(src.positioning) && !/oiScope=\{`all \$\{fam\} expiries`\}/.test(src.positioning))
check('CT-06: DAILY still invents its own scope — open patch request, NOT covered by this lane\'s fix',
  /oiScope=\{`all \$\{sel\.family\} expiries`\}/.test(src.daily) && !/tapeScopeLabel/.test(src.daily))
check('CT-06: WEEKLY takes BOTH scopes from the server and the family sum keeps its own flagged column',
  /label: `MCX \$\{mcxScope\} OI Δ lots`/.test(src.weekly) && /label: `\$\{mcxFamScope\} Δ lots`/.test(src.weekly)
  && /tapeFamilyScopeLabel\(mcx\.data, sel\.family\)/.test(src.weekly)
  && /data-gold-week-fam-mech/.test(src.weekly) && !/label: `MCX \$\{sel\.family\} OI Δ lots`/.test(src.weekly)
  && !/label: `all \$\{sel\.family\} expiries Δ lots`/.test(src.weekly))
check('CT-06: the family sum\'s scope label is the server\'s too, with the same fallback',
  F.tapeFamilyScopeLabel({ tape_family_scope: 'all GOLDM expiries' }, 'GOLDM') === 'all GOLDM expiries'
  && F.tapeFamilyScopeLabel({}, 'GOLDTEN') === 'all GOLDTEN expiries' && F.tapeFamilyScopeLabel(null, 'GOLD') === 'all GOLD expiries')

// ── round 2 (checker): a session the server had no Breeze bar for ────────────────────────────────────────────────────
const mixed = [
  { trade_date: '2026-11-02', doi: 4227, doi_family: null, label: 'long build-up', fill: null },
  { trade_date: '2026-11-03', doi: null, doi_family: -9871, family_mechanical: true, label: null, fill: 'icici_master',
    note: "no Breeze bar for this session: this contract's own ΔOI is not known" },
]
const mx = F.tapeDoiByDate(mixed)
check('CT-06 (round 2): a master-filled session carries the family sum ONLY, never a per-contract ΔOI',
  mx.get('2026-11-03')?.doi === null && mx.get('2026-11-03')?.family === -9871
  && mx.get('2026-11-03')?.fill === 'icici_master' && /no Breeze bar/.test(mx.get('2026-11-03')!.note ?? ''))
check('CT-06 (round 2) negative control: a Breeze session is not marked as a fill and keeps its own number',
  mx.get('2026-11-02')?.fill === null && mx.get('2026-11-02')?.doi === 4227
  && F.tapeDoiByDate([{ trade_date: 'd' }]).get('d')?.fill === null)
check('CT-06 (round 2): WEEKLY says WHY a per-contract cell is empty and never borrows the family number into it',
  /data-gold-week-fill=\{r\.mcxFill/.test(src.weekly) && /no bar/.test(src.weekly)
  && /mcxFill: md\?\.fill \?\? null/.test(src.weekly) && /mcxOi: md\?\.doi \?\? null/.test(src.weekly)
  && !/mcxOi: md\?\.doi \?\? md\?\.family/.test(src.weekly))
check('CT-06 (round 2): POSITIONING prints the server\'s fill note, so the tape\'s scope label stays true of every tile',
  /data-tape-fill-note/.test(src.positioning) && /tape_fill_note/.test(src.positioning))

// ── round 2 (checker): the tape's own range, stated apart from the ladder's ──────────────────────────────────────────
check('§f.6: the tape\'s first session is named when it differs from the OI ladder\'s `since`',
  F.tapeSinceLabel({ tape_since: '2026-08-13', since: '2026-10-28' }) === '2026-08-13'
  && /tape since \$\{istLabel\(tapeSinceLabel\(data\) as string\)\}/.test(src.positioning)
  && /ladder since \$\{istLabel\(data\.since\)\}/.test(src.positioning))
check('§f.6 negative control: one range is printed when the two agree, or either is missing',
  F.tapeSinceLabel({ tape_since: '2026-10-28', since: '2026-10-28' }) === null
  && F.tapeSinceLabel({ since: '2026-10-28' }) === null && F.tapeSinceLabel(null) === null)

const cells = [
  { settle_or_close: 143950, settle_source: 'breeze_close', quality: 'broker' },
  { settle_or_close: 144091.7, settle_source: 'breeze_vwap30', quality: 'vwap30_proxy' },
  { settle_or_close: 143268, settle_source: 'band_midpoint', quality: 'proxy' },
  { settle_or_close: null, settle_source: null, quality: null },
  { settle_or_close: 143268, settle_source: 'mcx_official', quality: 'official' },
]
check('CT-06: a settle chip names WHICH stand-in it is',
  F.settleStandIn(cells[0])?.text === 'BREEZE CLOSE' && /not MCX's settlement/.test(F.settleStandIn(cells[0])!.why)
  && F.settleStandIn(cells[1])?.text === 'VWAP30 PROXY' && F.settleStandIn(cells[2])?.text === 'BAND PROXY')
check('CT-06 negative control: an empty cell and a real settlement wear no chip at all',
  F.settleStandIn(cells[3]) === null && F.settleStandIn(cells[4]) === null && F.settleStandIn(null) === null)
check('CT-06: the ladder renders the chip through settleStandIn, never on `quality` alone',
  /const chip = settleStandIn\(r\)/.test(src.positioning) && !/r\.quality === 'proxy' && <Chip/.test(src.positioning))

// ══ PLAN §f: nothing here turns context into a direction ══════════════════════════════════════════════════════════

check('§f.3: no direction word enters the new copy or the pure models',
  !/bullish|bearish/i.test(src.model + src.bits)
  && !/bullish|bearish/i.test(src.positioning + src.weekly + src.monthly))
check('§f.6: the overdue line, the coverage note and the tape\'s fill note are each rendered in ONE place per view',
  (src.positioning.match(/data-cot-overdue/g) ?? []).length === 1
  && (src.positioning.match(/data-cot-catchup/g) ?? []).length === 1
  && (src.positioning.match(/data-tape-fill-note/g) ?? []).length === 1
  && (src.bits.match(/data-coverage-note/g) ?? []).length === 1)

console.log(failures ? `\n${failures} check(s) failed` : '\nall gold feed checks passed')
process.exit(failures ? 1 : 0)
