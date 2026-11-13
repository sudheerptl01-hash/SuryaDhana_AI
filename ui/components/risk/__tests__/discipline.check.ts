/**
 * B-COCKPIT node check (FINAL ROUND wave B; risk/SPEC.md §§1–5, O-F3): the risk cockpit's pure model —
 * settings parsing, cap math, the 09:15 IST session reset, the trip/acknowledge state machine (simulated
 * through a fake prefs store, never the live terminal), the SPEC §3 banner copy VERBATIM, the checklist
 * note/fit lines and the scenario-strip parsing/tones — plus static scans of the cockpit sources
 * (no direction words in copy, no composite "discipline score", no `signal` badge, O-F3 wording present).
 *
 * Run with plain node ≥ 23.6 (type stripping, no deps):
 *   node ui/components/risk/__tests__/discipline.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type ModelMod = typeof import('../disciplineModel')
const M = (await import(new URL('../disciplineModel.ts', import.meta.url).href)) as ModelMod

const RISK_DIR = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')
const read = (rel: string): string => fs.readFileSync(path.join(RISK_DIR, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

/** epoch ms of an IST wall-clock moment */
const ist = (y: number, mo: number, d: number, h: number, mi: number): number =>
  Date.UTC(y, mo - 1, d, h, mi) - 330 * 60_000

// ── settings (SPEC §1) ───────────────────────────────────────────────────────────────────────────────────────

check('defaults match SPEC §1', JSON.stringify(M.DEFAULT_SETTINGS) === JSON.stringify({
  trading_capital_inr: 1_000_000, daily_loss_cap_pct: 2, daily_loss_warn_pct: 1,
  consecutive_loss_standdown_n: 3, max_trades_per_day: 5, trade_warn_at: 4, revenge_timer_min: 15, enabled: true,
}))
check('absent prefs key → unconfigured (null)', M.parseSettings(null) === null && M.parseSettings('') === null)
check('garbage JSON → unconfigured', M.parseSettings('{nope') === null && M.parseSettings('[1,2]') === null)
const rt = M.parseSettings(M.serializeSettings({ ...M.DEFAULT_SETTINGS, trading_capital_inr: 500_000 }))
check('serialize → parse roundtrip', rt?.trading_capital_inr === 500_000 && rt?.enabled === true)
const sane = M.parseSettings(JSON.stringify({ trading_capital_inr: 'x', daily_loss_cap_pct: -4, enabled: false }))
check('bad fields fall back to defaults, bounds applied', sane?.trading_capital_inr === 1_000_000 && sane?.daily_loss_cap_pct === 0.1 && sane?.enabled === false)
check('capInr: 2 % of ₹10,00,000 = ₹20,000', M.capInr(M.DEFAULT_SETTINGS) === 20_000 && M.warnInr(M.DEFAULT_SETTINGS) === 10_000)
check('inr formats Indian grouping with U+2212', M.inr(1_000_000) === '₹10,00,000' && M.inr(-21_400) === '−₹21,400' && M.inr(null) === '—')

// ── session key: reset at the next session's 09:15 IST (SPEC §1) ────────────────────────────────────────────

check('09:14 IST still belongs to the previous session', M.sessionKey(ist(2026, 11, 17, 9, 14)) === '2026-11-16')
check('09:15 IST starts the new session', M.sessionKey(ist(2026, 11, 17, 9, 15)) === '2026-11-17')
check('an evening trip keeps its session overnight', M.sessionKey(ist(2026, 11, 17, 23, 59)) === '2026-11-17'
  && M.sessionKey(ist(2026, 11, 18, 0, 10)) === '2026-11-17')
check('resetDateOf is the day after the session', M.resetDateOf('2026-11-17') === '2026-11-18')

// ── the day evaluation (arithmetic; trips are loss rules only) ──────────────────────────────────────────────

type DayBook = import('../disciplineModel').DayBook
const day = (over: Partial<DayBook> = {}): DayBook => ({
  date: '2026-11-17', realised_inr: 0, mtm_change_inr: 0, bookings: 0, closes: 0, loss_streak: 0, trades: [], ...over,
})
const S = M.DEFAULT_SETTINGS
const now = ist(2026, 11, 17, 14, 0)

check('dayPnl sums realised + MTM; null only when both unknown',
  M.dayPnl({ realised_inr: -5000, mtm_change_inr: 1200 }) === -3800
  && M.dayPnl({ realised_inr: null, mtm_change_inr: null }) === null
  && M.dayPnl({ realised_inr: null, mtm_change_inr: -100 }) === -100)

const okEval = M.evalDay(S, day({ realised_inr: -5_000 }), now)
check('below warn: no trip, no amber chip', okEval.trip === null && okEval.amberChip === null && okEval.lossInr === 5_000)

const capEval = M.evalDay(S, day({ realised_inr: -15_000, mtm_change_inr: -6_400 }), now)
check('daily cap trip at realised+MTM ≥ cap', capEval.trip?.rule === 'daily_cap')
check('trip detail matches SPEC §1 shape: −₹21,400 vs ₹20,000 cap', capEval.trip?.detail === '−₹21,400 vs ₹20,000 cap', capEval.trip?.detail)

const streakEval = M.evalDay(S, day({ loss_streak: 3 }), now)
check('3 consecutive losses trip the stand-down', streakEval.trip?.rule === 'consec_losses' && streakEval.trip?.losses_n === 3)
check('2 losses do not', M.evalDay(S, day({ loss_streak: 2 }), now).trip === null)

const tradesEval = M.evalDay(S, day({ bookings: 7 }), now)
check('the trade counter NEVER trips (SPEC §1)', tradesEval.trip === null)

const amberEval = M.evalDay(S, day({ realised_inr: -12_000, bookings: 4 }), now)
check('amber chip verbatim: DISCIPLINE · −1.2 % of 2.0 % cap · 4 of 5 trades',
  amberEval.amberChip === 'DISCIPLINE · −1.2 % of 2.0 % cap · 4 of 5 trades', amberEval.amberChip)
check('amber chip absent once tripped (the banner carries it)', capEval.amberChip === null)

check('disabled cockpit evaluates sums but never trips',
  M.evalDay({ ...S, enabled: false }, day({ realised_inr: -50_000, loss_streak: 5 }), now).trip === null)
check('unconfigured (settings null) never trips', M.evalDay(null, day({ realised_inr: -50_000, loss_streak: 5 }), now).trip === null)
check('no day read → empty eval', M.evalDay(S, null, now).pnl === null)

// revenge timer: a single realised loss ≥ half the cap starts the cooling countdown
const lossAt = new Date(now - 5 * 60_000).toISOString()
const revEval = M.evalDay(S, day({ realised_inr: -11_000, trades: [{ at: lossAt, realised_inr: -11_000 }] }), now)
check('cooling timer runs 15 min after a loss ≥ half the cap', revEval.revengeUntil === Date.parse(lossAt) + 15 * 60_000)
check('a smaller loss starts no timer', M.evalDay(S, day({ trades: [{ at: lossAt, realised_inr: -2_000 }] }), now).revengeUntil === null)
check('timer off at 0 min', M.evalDay({ ...S, revenge_timer_min: 0 }, day({ trades: [{ at: lossAt, realised_inr: -11_000 }] }), now).revengeUntil === null)
check('mmss formats the countdown', M.mmss(899_000) === '14:59' && M.mmss(-5) === '0:00')

// ── trip / acknowledge state machine, simulated through a fake prefs store (never the live terminal) ────────

const fakePrefs = new Map<string, string>()
const rec = M.tripRecord(capEval.trip!, now)
fakePrefs.set(M.STANDDOWN_KEY, M.serializeStandDown(rec))
const stored = M.parseStandDown(fakePrefs.get(M.STANDDOWN_KEY))
check('trip record survives the store roundtrip', stored?.rule === 'daily_cap' && stored?.session === '2026-11-17' && stored?.acknowledged === false)
check('record active for its own session', M.standDownActive(stored, now) && M.standDownActive(stored, ist(2026, 11, 18, 9, 14)))
check('record expires at the next session open (09:15 IST)', !M.standDownActive(stored, ist(2026, 11, 18, 9, 15)))
fakePrefs.set(M.STANDDOWN_KEY, M.serializeStandDown({ ...stored!, acknowledged: true }))
const acked = M.parseStandDown(fakePrefs.get(M.STANDDOWN_KEY))
check('acknowledge keeps the record (chip state), never clears it', acked?.acknowledged === true && M.standDownActive(acked, now))
check('garbage stand-down record → null, never a crash', M.parseStandDown('{"rule":"x"}') === null && M.parseStandDown('zz') === null)

// ── banner copy (SPEC §3 VERBATIM) ──────────────────────────────────────────────────────────────────────────

check('daily-cap banner copy verbatim',
  M.bannerMain(stored!) === 'your daily loss cap is reached — ₹21,400 lost of your ₹20,000 cap (2.0 % of capital)', M.bannerMain(stored!))
const consecRec = M.tripRecord(streakEval.trip!, now)
check('consecutive-losses banner copy verbatim', M.bannerMain(consecRec) === '3 losses in a row — your stand-down rule', M.bannerMain(consecRec))
check('banner suffix verbatim: your rule · resets at the next session open',
  M.BANNER_SUFFIX === 'your rule, set in RSK › DISCIPLINE · resets at the next session open')
check('house-rule hover suffix verbatim', M.HOUSE_RULE_SUFFIX === 'a house rule; describes your own limits, does not predict')

// ── checklist (SPEC §5) ─────────────────────────────────────────────────────────────────────────────────────

const cl = M.parseChecklist(JSON.stringify({ session: '2026-11-17', items: { NIFTY: { event: true, iv: true, max_loss: false, margin: false, max_loss_inr: 8000 } } }), '2026-11-17')
check('checklist parses per-symbol items', cl.items.NIFTY?.event === true && cl.items.NIFTY?.max_loss_inr === 8000)
check('a new session resets the one key (rewritten daily)', Object.keys(M.parseChecklist(M.serializeChecklist(cl), '2026-11-18').items).length === 0)
check('journal note shape: checklist: 2/4', M.checklistNote(cl.items.NIFTY) === 'checklist: 2/4')
check('remaining cap = cap − today\'s loss, floored at 0',
  M.remainingCap(S, M.evalDay(S, day({ realised_inr: -7_400 }), now)) === 12_600
  && M.remainingCap(S, capEval) === 0 && M.remainingCap(null, okEval) === null)
const fits = M.maxLossLine(8_000, 12_600)
check('max-loss fits line (arithmetic, SPEC §5 wording)', fits.text === '₹8,000 — fits the ₹12,600 left under your daily cap today' && !fits.warn, fits.text)
const exceeds = M.maxLossLine(15_000, 12_600)
check('max-loss exceeds line turns amber', exceeds.warn && exceeds.text.includes('exceeds the ₹12,600 left'), exceeds.text)

// ── scenario strip (SPEC §4) ────────────────────────────────────────────────────────────────────────────────

const foPayload = {
  as_of: '2026-11-17T14:02:00+05:30', empty: false,
  scenarios: {
    gap: [{ spot_pct: -2, pnl_inr: -9_000 }, { spot_pct: -1, pnl_inr: -4_000 }, { spot_pct: 1, pnl_inr: 3_500 }, { spot_pct: 2, pnl_inr: 6_800 }, { spot_pct: -5, pnl_inr: -30_000 }],
    iv_shock: [{ iv_shift: -5, pnl_inr: 2_100 }, { iv_shift: 5, pnl_inr: -2_400 }],
    theta: [{ days_fwd: 1, pnl_inr: 1_150 }],
    theta_1d_inr: 999, note: 'full revaluation',
  },
}
const sc = M.parseScenarios(foPayload)
check('strip order: SPOT −2/−1/+1/+2 · IV −5/+5 · T −1d', sc.tiles.map(t => t.id).join(',') === 'spot-2,spot-1,spot+1,spot+2,iv-5,iv+5,theta-1d')
check('±1 % gaps picked from M2 payload', sc.tiles[1].pnl === -4_000 && sc.tiles[2].pnl === 3_500)
check('theta row preferred over legacy theta_1d_inr', sc.tiles[6].pnl === 1_150)
const legacy = M.parseScenarios({ scenarios: { gap: [{ spot_pct: -2, pnl_inr: -9_000 }], iv_shock: [], theta_1d_inr: 777 } })
check('pre-M2 payload: ±1 % renders — (null), theta falls back', legacy.tiles[1].pnl === null && legacy.tiles[6].pnl === 777)
check('empty book parses as empty (strip hides)', M.parseScenarios({ empty: true }).empty && M.parseScenarios(null).empty)
check('the hover clock prefers the MARKS’ as-of (mark_source.as_of), payload as_of as fallback',
  M.parseScenarios({ ...foPayload, mark_source: { state: 'delayed', as_of: '2026-11-17T14:00:30+05:30' } }).asOf === '2026-11-17T14:00:30+05:30'
  && M.parseScenarios(foPayload).asOf === '2026-11-17T14:02:00+05:30')
check('tone: loss ≥ remaining cap → red; ≥ half → amber; gains and unconfigured → muted',
  M.scenarioTone(-13_000, 12_600) === 'red' && M.scenarioTone(-7_000, 12_600) === 'amber'
  && M.scenarioTone(-1_000, 12_600) === 'muted' && M.scenarioTone(6_800, 12_600) === 'muted' && M.scenarioTone(-9_000, null) === 'muted')

// ── rules card rows ─────────────────────────────────────────────────────────────────────────────────────────

const rows = M.ruleRows(S, amberEval)
check('rules card: 5 rows, no composite score', rows.length === 5 && rows.every(r => !/score/i.test(r.label)))
check('trade row at warn', rows.find(r => r.id === 'trades')?.state === 'warn')

// ── static scans: labelling rules over the cockpit sources ─────────────────────────────────────────────────

const sources = ['disciplineModel.ts', 'useDiscipline.ts', 'Discipline.tsx', 'StandDownBanner.tsx', 'ScenarioStrip.tsx', 'PreTradeChecklist.tsx', 'HeaderChips.tsx']
const all = sources.map(f => ({ f, src: read(f) }))
for (const { f, src } of all) {
  check(`${f}: no bullish/bearish/opportunity wording`, !/bullish|bearish|opportunit/i.test(src))
  // the docstrings QUOTE the SPEC's wording rule ('never "stop trading", never "don't"'); strip the quoted rule
  // itself, then assert no copy actually says it
  const copy = src.replace(/never "stop trading", never "don['’]t"/gi, '')
  check(`${f}: never "stop trading", never "don't"`, !/stop trading/i.test(copy) && !/don['’]t\b/i.test(copy))
  check(`${f}: no composite "discipline score"`, !/discipline score/i.test(src.replace(/NO composite "discipline score"|no composite "discipline score"/gi, '')))
  check(`${f}: no signal badge`, !/badge=.signal|badge: ?.signal/.test(src))
}
const bannerSrc = read('StandDownBanner.tsx')
check('banner states O-F3 (never blocks)', /never blocks/.test(bannerSrc))
check('banner buttons: ACKNOWLEDGE + REVIEW RULES', /ACKNOWLEDGE/.test(bannerSrc) && /REVIEW RULES/.test(bannerSrc))
const todaySrc = read('Discipline.tsx')
check('TODAY footnote verbatim (always visible)', todaySrc.includes('Counts the PAPER book only — log your real ICICI trades here (OSTR › Book paper) or today'))
check('settings card opens in set-your-capital state', /Set your capital/.test(todaySrc))
const checklistSrc = read('PreTradeChecklist.tsx')
check('checklist never gates the Book button', /NEVER gates the Book button|never gates the Book button/i.test(checklistSrc))

// ── mount wiring (the banner on every page; precedence below the outage banner; strips + chips mounted) ─────

const UI_ROOT = path.resolve(RISK_DIR, '..', '..')
const readUi = (rel: string): string => fs.readFileSync(path.join(UI_ROOT, rel), 'utf8')
const shell = readUi('components/desktop/PlatformShell.tsx')
check('PlatformShell mounts StandDownBanner as a ConnectionBanner sibling', shell.includes('<StandDownBanner top={stripTop} />'))
check('precedence: the stand-down strip yields to LINK DOWN / recovered', /standDown\.banner && phase === 'hidden'/.test(shell))
check('the strip height counts into --shell-top like the connection banner', /phase !== 'hidden' \|\| showStandDown \? BANNER_HEIGHT : 0/.test(shell))
const header = readUi('components/MarketCommandHeader.tsx')
check('header mounts the cockpit chips (STAND DOWN · amber DISCIPLINE · T-17 net Greeks)', header.includes('<DisciplineHeaderChips activeTab={activeTab} />'))
const chips = read('HeaderChips.tsx')
check('net-Greeks chip is OMON/OSTR only', /activeTab === 'options' \|\| activeTab === 'ostrategy'/.test(chips))
const foPanel = readUi('components/fobook/FoRiskPanel.tsx')
check('RSK › F&O gains the DISCIPLINE sub-view tab', /id: 'discipline'/.test(foPanel) && /<Discipline \/>/.test(foPanel))
// PM decision 13 Nov (one number once per page): the strip's home is the paper book; RSK › F&O keeps its own
// scenarios table, which carries the same ±1/±2 % / IV ±5 / T−1 numbers.
check('RSK › F&O does NOT duplicate the strip beside its scenarios table', !/<ScenarioStrip/.test(foPanel))
const paperBook = readUi('components/fobook/PaperBook.tsx')
check('the paper-book card mounts the scenario strip', /<ScenarioStrip \/>/.test(paperBook))
const useDisc = read('useDiscipline.ts')
check('readonly prefs mode never PUTs (QA audits stay read-only)', /readonlyMode\(\)/.test(useDisc) && /suryadhana\.prefs\.mode/.test(useDisc))
check('409 → adopt the server value (LWW, the standard sync rule)', /status === 409/.test(useDisc))

// ── done ────────────────────────────────────────────────────────────────────────────────────────────────────

console.log(`discipline.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
