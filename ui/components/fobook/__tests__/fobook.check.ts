/**
 * OSTR v2 + the PAPER F&O book + RSK (W2-BOOK, 6 Nov 2026): the pure model and the source rules, each with a negative control.
 *
 * Run with plain node ≥ 22.6 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/fobook/__tests__/fobook.check.ts
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type Model = typeof import('../ostrModel')
const M = (await import(new URL('../ostrModel.ts', import.meta.url).href)) as Model
type Aliases = typeof import('../../../lib/goAliases')
const GA = (await import(new URL('../../../lib/goAliases.ts', import.meta.url).href)) as Aliases
const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..', '..')
const src = (f: string) => fs.readFileSync(path.join(UI, f), 'utf8')

let failed = 0, passed = 0
function check(name: string, ok: boolean, detail?: unknown): void {
  if (ok) { passed++; return }
  failed++
  console.error(`FAIL ${name}${detail !== undefined ? ` — ${JSON.stringify(detail)}` : ''}`)
}

// a chain shaped like /api/market/option-chain (flat smile so the deltas are easy to check by hand)
function chain(F: number, iv: number, days: number, step: number, width: number, symbol = 'NIFTY'): import('../ostrModel').ChainLike {
  const rows = []
  const lo = Math.round(F * (1 - width) / step) * step, hi = Math.round(F * (1 + width) / step) * step
  for (let k = lo; k <= hi; k += step) rows.push({ strike: k, ce: { price: 10, iv }, pe: { price: 10, iv } })
  return { symbol, date: '2026-11-05', expiry: '2026-11-09', expiries: ['2026-11-09'], days_to_expiry: days, spot: F, future: F, forward: F,
           atm: Math.round(F / step) * step, lot: 65, atm_iv: iv, rows }
}

// ── m060: templates seeded by delta, not by fixed offsets ─────────────────────────────────────────────────────────
{
  const nifty = chain(24545.75, 14.6, 4, 50, 0.06)
  const ic = M.templateSpecs('Iron condor', nifty)
  const shortCall = ic.find(l => l.side === 'sell' && l.kind === 'CE')!.strike!, shortPut = ic.find(l => l.side === 'sell' && l.kind === 'PE')!.strike!
  const sd = 24545.75 * 0.146 * Math.sqrt(4 / 365)                            // 1σ ≈ 375 points (4 days: cal365-1530, M04)
  check('m060 NIFTY weekly condor shorts sit near ±1σ (16Δ)', Math.abs(shortCall - 24545.75 - sd) < 100 && Math.abs(24545.75 - shortPut - sd) < 120, [shortCall, shortPut, sd])
  const wings = ic.filter(l => l.side === 'buy').map(l => l.strike!)
  check('m060 wings outside the shorts', Math.max(...wings) > shortCall && Math.min(...wings) < shortPut, wings)
  const bank = chain(57773.65, 13.9, 18, 100, 0.08, 'BANKNIFTY')
  const bic = M.templateSpecs('Iron condor', bank)
  const bsc = bic.find(l => l.side === 'sell' && l.kind === 'CE')!.strike!
  const bsd = 57773.65 * 0.139 * Math.sqrt(18 / 365)                         // ≈ ±1,780 (the review's 1σ ±1,780)
  check('m060 BANKNIFTY monthly condor short call ≈ +1σ, not +200', Math.abs(bsc - 57773.65 - bsd) < 250, [bsc, bsd])
  check('m060 negative control: the old ±2 strikes (+200) is far inside 1σ', 2 * 100 < bsd / 4)
  const sc = M.templateSpecs('Strangle', nifty)
  const scCall = sc.find(l => l.kind === 'CE')!.strike!
  check('m060 25Δ strangle call is OTM and nearer than the 16Δ short', scCall > 24545.75 && scCall < shortCall, [scCall, shortCall])
  check('m060 the delta of the picked 16Δ strike is ≈ 0.16', Math.abs(M.b76Delta('CE', 24545.75, shortCall, 4, 14.6) - 0.16) < 0.04)
  check('covered call on shares template has an EQ leg', M.templateSpecs('Covered call (shares+CE)', nifty).some(l => l.kind === 'EQ'))
}

// ── m062: net delta in lots and ₹ per 1 % ────────────────────────────────────────────────────────────────────────
{
  const u = M.deltaUnits(-0.13358, 65, 24545.75)
  check('m062 −0.13 units = −0.002 lots, ≈ −₹33 per 1 %', Math.abs(u.lots + 0.002055) < 1e-5 && Math.abs(u.inrPer1pct + 32.79) < 0.05, u)
}

// ── m059: one margin answer, never the heuristic beside a real one ────────────────────────────────────────────────
{
  check('m059 BREEZE answer → real only', M.marginView('BREEZE', null) === 'real')
  check('m059 NSE SPAN FILE → real only', M.marginView('NSE SPAN FILE', null) === 'real')
  check('m059 HEURISTIC → heuristic', M.marginView('HEURISTIC', null) === 'heuristic' && M.marginView(null, 'down') === 'heuristic')
  check('m059 nothing yet → asking', M.marginView(null, null) === 'asking')
  const guarded = (sb: string) => {
    const iReal = sb.indexOf("mView === 'real'"), iHeur = sb.indexOf("mView === 'heuristic'"), iErr = sb.indexOf('data-ostr-heuristic-error')
    const iLine = sb.indexOf('<div>Heuristic est.')
    return iReal > 0 && iHeur > iReal && iLine > iHeur && iErr > iHeur
  }
  check('m059 the heuristic line and its 4.8× sentence live inside the heuristic branch', guarded(src('components/StrategyBuilder.tsx')))
  // the 5 Nov layout: the real chip in a ternary, then the heuristic line and the 4.8× sentence for every answer
  const oldLayout = "{margin && String(margin.source_chip).toUpperCase() !== 'HEURISTIC' ? (<div>REAL</div>) : (<div>HEURISTIC</div>)}\n<div>Heuristic est. …</div>\n<div data-ostr-heuristic-error>4.8×</div>"
  check('m059 negative control: the 5 Nov layout (heuristic printed beside BREEZE) fails the scan', !guarded(oldLayout))
}

// ── M39: multi-expiry bodies (each leg on its own contract) ──────────────────────────────────────────────────────
{
  const legs = [{ side: 'sell' as const, kind: 'CE' as const, strike: 24500, expiry: '2026-11-09', premium: '180.30', iv: '15', lots: '1' },
                { side: 'buy' as const, kind: 'CE' as const, strike: 24500, expiry: '2026-11-17', premium: '278.95', iv: '13.96', lots: '1' },
                { side: 'buy' as const, kind: 'EQ' as const, strike: null, expiry: '2026-11-09', premium: '24536.6', iv: '', lots: '1' }]
  const mb = M.marginLegs(legs, () => 65)
  check('M39 the margin body carries each leg\'s own expiry and no shares', mb.length === 2 && mb[0].expiry === '2026-11-09' && mb[1].expiry === '2026-11-17')
  const bb = M.bookLegs(legs, () => 65, l => (l.expiry === '2026-11-09' ? 24545.75 : 24585), () => 'NSE F&O bhavcopy 2026-11-05')
  check('M40 the book body: F&O legs only, each with its forward and price source', bb.length === 2 && bb[1].forward === 24585 && bb.every(l => l.price_source.startsWith('NSE')))
  check('M39 default name of a calendar', M.defaultName('NIFTY', legs, null) === 'NIFTY calendar 09-Nov/17-Nov', M.defaultName('NIFTY', legs, null))
  check('M39 legDays is the app convention (M04: the chain\'s t_days, else whole days; no half-day)', M.legDays({ days_to_expiry: 4 }) === 4 && M.legDays({ days_to_expiry: -1 }) === 0 && M.legDays({ days_to_expiry: 4, t_days: 3.85 } as never) === 3.85)
  const sb = src('components/StrategyBuilder.tsx')
  check('M39 the analyze body sends per-leg days, forward and expiry', /days: l\.kind === 'CE' \|\| l\.kind === 'PE' \? legDays\(c\) : null/.test(sb)
    && /forward: l\.kind === 'EQ'/.test(sb) && /scenario_days: scenDays, iv_shift: ivShift, grid: true/.test(sb))
  check('M39 T+n and IV sliders, the grid and P(profit) are on the page', sb.includes('data-ostr-sliders') && sb.includes('<PnlGrid grid={analysis.grid}')
    && sb.includes('data-ostr-pop') && /<BadgeChip badge="heuristic"/.test(sb))
  check('M39 save / name a structure', sb.includes('postSaved(symbol, structName()') && sb.includes('loadSavedPick'))
}

// ── round 2 (checker majors / minors, 6 Nov) ─────────────────────────────────────────────────────────────────────
{
  const sb = src('components/StrategyBuilder.tsx')
  // M04 (major 1): one T app-wide — the chain's t_days (fractional live), else whole days; never + 0.5
  check('M04 legDays uses the chain\'s fractional t_days in session', M.legDays({ days_to_expiry: 3, t_days: 3.2292 }) === 3.2292)
  check('M04 legDays never adds a half-day and never goes negative', M.legDays({ days_to_expiry: 4 }) === 4 && M.legDays({ days_to_expiry: 0, t_days: -0.1 }) === 0)
  check('M04 negative control: the retired rule (days + 0.5) is a different T', M.legDays({ days_to_expiry: 4 }) !== 4 + 0.5)
  check('M04 OSTR sends no half-day anywhere', !/\+ 0\.5\b/.test(sb.slice(sb.indexOf("axios.post<Analysis>"), sb.indexOf("{ timeout: 15000 })"))) && !/T_OFFSET_DAYS/.test(src('components/fobook/ostrModel.ts')))
  // each leg sized with its own expiry's lot (minor: lot revisions apply per series)
  check('lot: analyze, margin, book and save use each leg\'s expiry lot', sb.includes('lot_size: lotOf(l), iv:') && sb.includes('marginLegs(legs, lotOf)')
    && sb.includes('bookLegs(legs, lotOf, legForward, priceSource)') && /lot_size: lotOf\(l\), price_source/.test(sb))
  check('lot negative control: the round-1 "main chain lot for every leg" is gone', !sb.includes('bookLegs(legs, () => lot') && !sb.includes('marginLegs(legs, () => lot)') && !/lot_size: lot, (iv|price_source)/.test(sb))
  // one FUT rule (minor): the traded near-month future, else that expiry's parity forward — as the book marks
  const exps = ['2026-11-09', '2026-11-17', '2026-11-24', '2026-12-01', '2026-12-29', '2027-01-25']
  check('FUT monthly expiries', JSON.stringify(M.monthlyExpiries(exps)) === JSON.stringify(['2026-11-24', '2026-12-29', '2027-01-25']))
  const near = M.futSeed({ expiry: '2026-11-24', expiries: exps, future: 24588, forward: 24585 })
  const later = M.futSeed({ expiry: '2026-12-29', expiries: exps, future: 24588, forward: 24701.5 })
  check('FUT near monthly seeds at the traded future', near.price === 24588 && near.basis === 'future')
  check('FUT a later monthly seeds at its parity forward, labelled', later.price === 24701.5 && later.basis === 'parity-forward')
  const round1Rule = (c: { forward: number | null; future: number | null }) => c.forward ?? c.future      // edit(): forward first
  check('FUT negative control: the round-1 edit rule priced the near monthly off the traded future', round1Rule({ forward: 24585, future: 24588 }) !== near.price)
  check('FUT legs offer monthly expiries only and say when the price is a parity forward', sb.includes("l.kind === 'FUT' ? monthlyExpiries(chain.expiries)")
    && sb.includes('put-call-parity forward (no traded future for it in the payload)') && !sb.includes("next.premium = c ? String(c.forward ?? c.future ?? '')"))
  // the base-expiry chips (minor): labelled, and a custom book keeps its legs
  check('base expiry: relabelled, custom legs kept', sb.includes('Base expiry · re-seeds the template') && sb.includes('keepLegs.current = !template && legs.length > 0'))
  check('base expiry negative control: "Expiry (all legs)" is gone', !sb.includes('Expiry (all legs)'))
  // GO `NIFTY OSTR IC` hand-off: every GO template is one of OSTR's; read once on mount and on the event, then removed
  const goTemplates = [...new Set(Object.values(GA.OSTR_TEMPLATES))]
  check('GO every OSTR template code maps to a builder template', goTemplates.every(t => M.pickTemplate(t) === t), goTemplates)
  check('GO negative control: an unknown template is refused', M.pickTemplate('Butterfly') === null && M.pickTemplate(null) === null)
  const now = Date.parse('2026-11-06T10:00:00Z')
  const fresh = GA.parseOstrTemplate(JSON.stringify({ template: 'Iron condor', symbol: 'NIFTY', expiry: '2026-11-27', at: '2026-11-06T09:59:30Z' }), now)
  const stale = GA.parseOstrTemplate(JSON.stringify({ template: 'Iron condor', symbol: 'NIFTY', expiry: null, at: '2026-11-06T09:00:00Z' }), now)
  check('GO a fresh hand-off opens IC on that expiry; a stale one is ignored', fresh?.template === 'Iron condor' && fresh.expiry === '2026-11-27' && stale === null)
  const hand = sb.slice(sb.indexOf('const applyTemplateHandoff'), sb.indexOf('[applyTemplateHandoff])') + 30)
  check('GO OSTR reads the hand-off once on mount and on its event, and removes it', hand.includes('localStorage.getItem(OSTR_TEMPLATE_KEY)')
    && hand.includes('localStorage.removeItem(OSTR_TEMPLATE_KEY)') && hand.includes('parseOstrTemplate(raw, Date.now())') && hand.includes('pickTemplate(')
    && /useEffect\(\(\) => \{\s*applyTemplateHandoff\(\)\s*window\.addEventListener\(OSTR_TEMPLATE_EVENT, applyTemplateHandoff\)/.test(hand)
    && hand.includes('removeEventListener(OSTR_TEMPLATE_EVENT, applyTemplateHandoff)') && hand.includes('pendingSeed.current = null'), hand.slice(0, 120))
  // CONFIRM fills at the previewed prices (minor), labelled; never a silent re-price
  const pb = src('components/fobook/PaperBook.tsx')
  check('confirm: close and roll send the previewed prices and the preview clock', pb.includes('confirm: confirmFills(preview.close.fills), previewed_at: preview.close.as_of')
    && pb.includes('confirm: confirmRoll(preview.roll.legs), previewed_at: preview.roll.as_of') && pb.includes('data-fobook-preview-clock'))
  check('confirm negative control: the round-1 bare re-pricing close is gone', !pb.includes('await closeBook({ position_ids: ids })'))
  check('marks: settlement and expired-unsettled are labelled; expired-intrinsic is gone', pb.includes("mk.mark_method === 'settlement'") && pb.includes("'expired-unsettled'") && !pb.includes('expired-intrinsic'))
  // the same number once per page; badges on derived numbers
  const pg = src('components/fobook/PnlGrid.tsx')
  check('grid ±0 column says each leg\'s IV (not the ATM IV the header prints)', pg.includes("IV_ZERO_HEADER = \"±0 (each leg's IV)\"") && !pg.includes('ivNow') && !sb.includes('ivNow={chain.atm_iv}'))
  const fr = src('components/fobook/FoRiskPanel.tsx')
  check('RSK › F&O margin utilisation carries the margin\'s own badge', /data-rsk-fo-margin-badge>Margin used \{m && <BadgeChip badge=\{m\.badge\}/.test(fr))
}

// ── heat map colours: P&L sign (arithmetic), neutral at zero ─────────────────────────────────────────────────────
{
  check('grid colour: zero is the neutral token', M.heatColor(0, 1000, '#0f0', '#f00', '#111') === '#111')
  check('grid colour: profit green, loss red', M.heatColor(500, 1000, '#00ff00', '#ff0000').startsWith('#00ff00') && M.heatColor(-500, 1000, '#00ff00', '#ff0000').startsWith('#ff0000'))
  check('grid colour: intensity grows with size', M.heatColor(900, 1000, '#00ff00', '#ff0000') > M.heatColor(100, 1000, '#00ff00', '#ff0000'))
  check('grid max |P&L|', M.gridMaxAbs([[1, -7], [3, NaN]]) === 7)
}

// ── PAPER ONLY and the wording rules across every file this builder wrote ────────────────────────────────────────
{
  const files = ['components/StrategyBuilder.tsx', 'components/RiskDashboard.tsx', 'components/fobook/ostrModel.ts', 'components/fobook/api.ts',
                 'components/fobook/PaperBook.tsx', 'components/fobook/FoRiskPanel.tsx', 'components/fobook/PnlGrid.tsx']
  const ORDER = /\b(place_?order|placeOrder|modify_?order|cancel_?order|square_?off)\b|\/api\/execution|\/api\/positions\/order/
  for (const f of files) {
    const s = src(f)
    check(`PAPER ${f}: no order method or order route`, !ORDER.test(s), f)
    check(`wording ${f}: no bullish / bearish`, !/\b(bullish|bearish)\b/i.test(s), f)
  }
  check('PAPER negative control: the order scan catches a planted call', ORDER.test("await client.post('/api/execution/order', body)") && ORDER.test('breeze.place_order('))
  const api = src('components/fobook/api.ts')
  check('PAPER the book client always sends mode "paper"', (api.match(/mode: 'paper'/g) ?? []).length >= 3)
  check('PAPER the book panels say so', src('components/fobook/PaperBook.tsx').includes('PAPER ONLY') && src('components/fobook/FoRiskPanel.tsx').includes('PAPER ONLY'))
  check('PAPER confirmations are in-page (no browser dialog)', !/window\.confirm|\bconfirm\(/.test(src('components/fobook/PaperBook.tsx').replace(/const confirm = |onClick=\{confirm\}/g, ''))
    && src('components/StrategyBuilder.tsx').includes('data-ostr-book-confirm'))
}

// ── RSK: M18 sizing, m106, m107, m108, the F&O section ───────────────────────────────────────────────────────────
{
  const rk = src('components/RiskDashboard.tsx')
  check('M18 RSK sizes the what-if at the Desk share by default, with a selector', rk.includes("useState<SizeMode>('desk')") && rk.includes('<option value="nav">')
    && rk.includes('data-rsk-sizing'))
  check('M18 negative control: the old "equal weight on <NAV>" notice is gone', !rk.includes('WHAT-IF basket: equal weight on {fmtInr(data.book.nav_inr)} —'))
  check('m106 the empty VaR copy names an empty book', rk.includes('The book holds no equity today') && !rk.includes('hint="VaR needs per-ticker history from data-service."'))
  check('m107 the legacy halt is listed apart and labelled', rk.includes('data-rsk-legacy-rules') && rk.includes('legacy −2% halt'))
  check('m108 a partial stress replay says how much it covers', rk.includes('data-rsk-partial') && rk.includes('names_covered'))
  check('M40 RSK shows the F&O book beside the cash VaR', rk.includes('<FoRiskPanel />'))
  check('S5 kept: the broker book chip', rk.includes('<SourceChip info={brokerSrc} />'))
}

console.log(`fobook.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
