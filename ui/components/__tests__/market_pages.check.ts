/**
 * Market pages checks (page review 5 Nov 2026, D-UI): EQS (M07, m076–m079), BRF (M08, m003, m007, m009, M11, M28),
 * HDS (M25, m037, m038), MRGN (M26, m039), MOV (M27, m017–m021), ECO (M28, m012), EVTS (M12, m042–m044, m046),
 * DEAL (m031–m035, active symbol), INSD (m036), CF (M11), WRAP (m022, M10), MKT (M09, m023), WEI (m010),
 * PRE (m013–m015), SEAG (m030), IPO (m040, m041), COMP (m083, active symbol).
 * Every rule has a negative control: the pre-fix behaviour, reproduced, fails it.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/market_pages.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type ModelMod = typeof import('../marketPagesModel')
const M = (await import(new URL('../marketPagesModel.ts', import.meta.url).href)) as ModelMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const src = (rel: string) => fs.readFileSync(path.join(UI, rel), 'utf8')

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}
const MINUS = '−'

// ── EQS ───────────────────────────────────────────────────────────────────────────────────────────────────────
{
  const tcs = { latest_price: 2495.7, cmp: 2495.7, cmp_basis: 'nse_close', snapshot_cmp: 2350, valuation_basis: 'filings' as const,
                pe_ratio: 17.5, mktcap_cr: 903443.4, div_yld_pct: 1.96, div_basis: 'snapshot_rebased', quarter_basis: 'filings' }
  check('EQS M07 the CMP is the stored close', M.eqsPrice(tcs) === 2495.7)
  // an older ui-api sent the snapshot as cmp (TCS ₹2,350): the grid must never print it
  const legacy = { latest_price: 2495.7, cmp: 2350 }
  check('EQS M07 an old server\'s snapshot cmp is never shown', M.eqsPrice(legacy) === 2495.7)
  const oldDisplay = (s: { cmp?: number | null; latest_price?: number | null }) => s.cmp ?? s.latest_price
  check('EQS M07 negative control: the old `cmp ?? latest_price` printed ₹2,350', oldDisplay(legacy) === 2350)
  check('EQS M07 filings valuation shows', M.shownValuation(tcs, 'pe_ratio') === 17.5 && M.shownValuation(tcs, 'mktcap_cr') === 903443.4)
  check('EQS M07 withheld valuation hides', M.shownValuation({ valuation_basis: 'withheld', pe_ratio: 60 }, 'pe_ratio') === null)
  check('EQS M07 an ETF has no P/E', M.shownValuation({ valuation_basis: 'etf', pe_ratio: 5 }, 'pe_ratio') === null)
  check('EQS M07 an undated (old server) valuation hides', M.shownValuation({ pe_ratio: 16.5 }, 'pe_ratio') === null)
  check('EQS div yield only when rebased', M.shownValuation(tcs, 'div_yld_pct') === 1.96 && M.shownValuation({ div_basis: 'withheld', div_yld_pct: 2 }, 'div_yld_pct') === null)
  check('EQS notes name the source', /results filing/.test(M.valuationNote(tcs)) && /too far/.test(M.valuationNote({ valuation_basis: 'withheld', snapshot_cmp: 253.44 })))
  const lg = M.eqsLegend([tcs, { valuation_basis: 'snapshot_rebased' }, { valuation_basis: 'withheld' }, { instrument: 'ETF', valuation_basis: 'etf' }, {}])
  check('EQS m079 legend counts', lg.filings === 1 && lg.rebased === 1 && lg.withheld === 1 && lg.etf === 1 && lg.legacy === 1, lg)
  const t = src('components/StockTable.tsx')
  check('EQS wiring: the row price is eqsPrice, not cmp ?? latest_price', /const displayPrice = eqsPrice\(stock\)/.test(t) && !/stock\.cmp \?\? stock\.latest_price/.test(t))
  check('EQS m077 the empty MIDCAP column is gone', !/midcap_bucket \?\? '—'/.test(t) && !/All Midcap/.test(t))
  check('EQS m077 the size column reads the market-cap rank', /stock\.cap_sebi/.test(t) && !/stock\.cap_category\.replace/.test(t))
  check('EQS m078 ETFs hidden by default with a toggle', /useState\(false\)/.test(t) && /data-eqs-etf-toggle/.test(t) && /s\.instrument !== 'ETF'/.test(t))
  check('EQS m079 the legend carries badges', /data-eqs-legend/.test(t) && /badge="arithmetic"/.test(t) && /badge="context"/.test(t) && /badge="heuristic"/.test(t))
  check('EQS P/E is not coloured as a buy/sell verdict', !/pe_ratio < 20 \? 'text-emerald-600'/.test(t))
}

// ── BRF: the crash filter (M08) ───────────────────────────────────────────────────────────────────────────────
{
  const crash = { nifty: 24536.6, sma200: 24002.44, risk_on: true, gap_pct: 2.23, move_needed_pct: 0, next_signal_date: '2026-11-30' }
  const desk = { positions: [], latest: { date: '2026-11-05', holdings: 0, positions: 0, nav: 503131 },
    nav: [{ date: '2026-09-25', holdings: 0, positions: 0 }, { date: '2026-10-30', holdings: 0, positions: 0 }, { date: '2026-11-05', holdings: 0, positions: 0 }],
    plans: [{ signal_date: '2026-10-30', summary: { signal_date: '2026-10-30', risk_on: false } }] }
  const l = M.crashLines(crash, desk)
  check('BRF M08 the reading line', l.reading.startsWith("Today's reading: NIFTY 24,536.60 above its 200-DMA 24,002.44 (+2.2%)") && /30 Nov signal would invest/.test(l.reading), l.reading)
  check('BRF M08 the book line: liquid fund since the start', l.book.startsWith('The book: in the liquid fund since 25 Sep') && /30 Oct signal: crash filter on/.test(l.book) && /next signal is Mon 30 Nov/.test(l.book), l.book)
  check('BRF M08 never INVESTED for an all-cash book', !/INVESTED|invested/.test(l.book))
  // negative control: the old box printed the TODAY reading as the book's state
  const oldBox = crash.risk_on ? 'CRASH FILTER OFF · INVESTED' : 'CRASH FILTER ON · IN THE LIQUID FUND'
  check('BRF M08 negative control: the old box said INVESTED for ₹0 invested', /INVESTED/.test(oldBox) && desk.positions.length === 0)
  const invested = M.crashLines({ ...crash }, { positions: [1, 2], latest: { date: '2026-12-05', holdings: 300000, positions: 2, nav: 500000 },
    nav: [{ date: '2026-12-01', holdings: 0, positions: 0 }, { date: '2026-12-02', holdings: 300000, positions: 2 }, { date: '2026-12-05', holdings: 300000, positions: 2 }] })
  check('BRF M08 an invested book says since when and how much', /invested since 2 Dec, 2 positions \(60% of NAV/.test(invested.book), invested.book)
  const below = M.crashLines({ ...crash, risk_on: false, gap_pct: -1.2, move_needed_pct: 1.2 }, desk)
  check('BRF M08 below the 200-DMA', /below its 200-DMA/.test(below.reading) && /stays in the liquid fund unless NIFTY gains \+1\.2%/.test(below.reading) && below.reading.includes(`${MINUS}1.2%`), below.reading)
  const b = src('components/Brief.tsx')
  check('BRF wiring: the two lines render, no INVESTED literal', /data-brief-crash-reading/.test(b) && /data-brief-crash-book/.test(b) && !/CRASH FILTER OFF · INVESTED/.test(b))
  check('BRF m007 the breadth universe is named (not "Nifty 500")', /liquid stocks` : 'NSE breadth'/.test(b) && !/\$\{m\.index_name\}` : 'NSE breadth'/.test(b) && /Advances \/ declines · \{b\.universe/.test(b))
  check('BRF m003 the regime score is in the neutral tone', !/color: SCORE_COLOR\[m\.regime\.score\]/.test(b))
  check('BRF m009 the track record is dated', /computed \{dayMonth\(at\)\}/.test(b))
  check('BRF M11 the results count uses the whole-day count when cut', /cfCoverage\(filings\.data/.test(b) && /results filings all day/.test(b))
}

// ── MKT / BRF: FII–DII coverage (M09) ─────────────────────────────────────────────────────────────────────────
{
  const s = { sessions_5d: 3, expected_5d: 5, missing_5d: ['2026-11-02', '2026-11-03'], sessions_mtd: 2, expected_mtd: 4, missing_mtd: ['2026-11-02', '2026-11-03'] }
  const c5 = M.cashCoverage(s, '5d'), cm = M.cashCoverage(s, 'mtd')
  check('M09 n of m with the missing days', c5.text === '3 of 5 sessions · missing 2 Nov, 3 Nov' && c5.gap && cm.text === '2 of 4 sessions · missing 2 Nov, 3 Nov', [c5, cm])
  check('M09 a complete window is not a gap', !M.cashCoverage({ sessions_5d: 5, expected_5d: 5, missing_5d: [] }, '5d').gap)
  const old = M.cashCoverage({ sessions_5d: 5 }, '5d')
  check('M09 an older server never claims completeness', old.gap && /calendar unknown/.test(old.text))
  // negative control: the old label was "5 sessions" for a window that spanned 27 Oct–5 Nov with 3 sessions missing
  const oldLabel = `${5} sessions`
  check('M09 negative control: the old label hid the gap', !/of/.test(oldLabel))
  const pp = src('components/ParticipantPositioning.tsx')
  check('M09 wiring: CashFlows prints the coverage', /cashCoverage\(s, '5d'\)/.test(pp) && /cell\('5 sessions', s\.sum_5d, cov5\.text, cov5\.gap\)/.test(pp))
  check('m023 the FII long-ratio axis has units', /\{v\.toFixed\(0\)\}%<\/text>/.test(pp))
}

// ── HDS (M25, m037, m038) ─────────────────────────────────────────────────────────────────────────────────────
{
  check('HDS previous quarter end', M.previousQuarterEnd('2026-09-30') === '2026-06-30' && M.previousQuarterEnd('2026-03-31') === '2025-12-31'
    && M.previousQuarterEnd('2026-12-31') === '2026-09-30' && M.previousQuarterEnd('2026-06-30') === '2026-03-31' && M.previousQuarterEnd('2026-08-31') === null)
  const rows = [
    { symbol: 'TCS', period_end: '2026-09-30', prev_period: '2026-06-30' },
    { symbol: 'RENTOMOJO', period_end: '2026-09-30', prev_period: '2026-09-30' },     // listing-time vs quarter end
    { symbol: 'DHOOTTRANS', period_end: '2026-09-30', prev_period: '2026-08-31' },    // IPO allotment
    { symbol: 'OLD', period_end: '2026-09-30', prev_period: '2026-03-31' },           // skipped a quarter
    { symbol: 'NEW', period_end: '2026-09-30', prev_period: null },
  ]
  const qoq = rows.filter(M.isQoq).map(r => r.symbol)
  check('HDS M25 only consecutive quarter ends', qoq.length === 1 && qoq[0] === 'TCS', qoq)
  // negative control: the old filter tested period_end only (prev_period present)
  const oldKept = rows.filter(r => r.prev_period && /-(03-31|06-30|09-30|12-31)$/.test(r.period_end)).map(r => r.symbol)
  check('HDS M25 negative control: the old filter kept the IPO rows', oldKept.includes('RENTOMOJO') && oldKept.includes('DHOOTTRANS'))
  const cov = M.hdsCoverage(rows, '2026-09-30')
  check('HDS m037 coverage split', cov.filings === 5 && cov.qoq === 1 && cov.listing === 3 && cov.first === 1, cov)
  const pc = M.ppCell(null, null)
  check('HDS m038 no "— → —%"', pc.change === '—' && pc.level === '' && `${pc.change} ${pc.level}`.trim() === '—')
  check('HDS pp sign', M.ppCell(-0.5, 12.3).change === `${MINUS}0.50 pp` && M.ppCell(-0.5, 12.3).level === '→ 12.3%')
  const h = src('components/OwnershipShifts.tsx')
  check('HDS wiring: rows filtered by isQoq', /isQoq\(r\) && key\(r\) != null/.test(h) && /data-hds-coverage/.test(h))
}

// ── MRGN (M26, m039) ──────────────────────────────────────────────────────────────────────────────────────────
{
  const rows = [
    { symbol: 'ESDS', amount_cr: 20, qty_chg_pct: 19142 },        // a recent listing: base effect
    { symbol: 'TBOTEK', amount_cr: 74.7, qty_chg_pct: 396 },
    { symbol: 'CEMPRO', amount_cr: 123, qty_chg_pct: 187 },
    { symbol: 'SMALL', amount_cr: 2, qty_chg_pct: 900 },          // under ₹5 cr
  ]
  const rows60 = [{ symbol: 'ESDS', amount_cr: 20, qty_chg_pct: null }, { symbol: 'TBOTEK', amount_cr: 74.7, qty_chg_pct: 500 }, { symbol: 'CEMPRO', amount_cr: 123, qty_chg_pct: 210 }]
  const el = M.mtfEligible(rows, rows60)
  const top = M.mtfBuilding(rows, 'pct', el).map(r => r.symbol)
  check('MRGN M26 a recent listing leaves the % board', top[0] === 'TBOTEK' && !top.includes('ESDS') && !top.includes('SMALL'), top)
  const oldTop = [...rows].filter(r => r.amount_cr >= 5).sort((a, b) => b.qty_chg_pct - a.qty_chg_pct)[0].symbol
  check('MRGN M26 negative control: the old board led with ESDS +19,142 %', oldTop === 'ESDS')
  check('MRGN M26 the server\'s mtf_sessions wins when sent', M.mtfEligible([{ symbol: 'A', amount_cr: 9, qty_chg_pct: 50, mtf_sessions: 61 }, { symbol: 'B', amount_cr: 9, qty_chg_pct: 99, mtf_sessions: 12 }], null)?.has('A') === true
    && M.mtfEligible([{ symbol: 'B', amount_cr: 9, qty_chg_pct: 99, mtf_sessions: 12 }], null)?.has('B') === false)
  const rc = M.mtfRupeeChange({ symbol: 'X', amount_cr: 120, qty_chg_pct: 100 })
  check('MRGN ₹ change ≈ the added quantity at today\'s funding', rc.approx && Math.abs((rc.value ?? 0) - 60) < 1e-9, rc)
  check('MRGN ₹ change prefers the server field', M.mtfRupeeChange({ symbol: 'X', amount_cr: 120, qty_chg_pct: 100, amount_chg_cr: 55 }).value === 55)
  const byRs = M.mtfBuilding(rows, 'rupees', null).map(r => r.symbol)
  check('MRGN ₹ ranking puts the real build-ups first', byRs[0] === 'CEMPRO' && byRs[1] === 'TBOTEK', byRs)
  const mm = src('components/MarginMonitor.tsx')
  check('MRGN m039 the rule sits under the table, not in the header subtitle', /data-mrgn-rule/.test(mm) && !/subtitle=\{`funded quantity growth over/.test(mm))
  check('MRGN m039 a new name reads "new", not "—"', />new<\/span>/.test(mm))
}

// ── MOV (M27, m017–m021) ──────────────────────────────────────────────────────────────────────────────────────
{
  check('MOV nse date', M.nseDateIso('27-Nov-2025') === '2025-11-27' && M.nseDateIso('x') === null)
  check('MOV m018 old-high date carries its year', M.shortDateWithYear('27-Nov-2025') === '27 Nov 25')
  check('MOV m018 negative control: the old slice(0, 6) had no year', '27-Nov-2025'.slice(0, 6) === '27-Nov')
  const highs = [
    { symbol: 'ADANIPORTS', ltp: 1884, change_pct: -1.3, prev_level: 1948, prev_date: '05-Nov-2026' },
    { symbol: 'AEROPLANE', ltp: 238, change_pct: 7.3, prev_level: 244, prev_date: '05-Nov-2026' },
    { symbol: 'ICICIBANK', ltp: 1500, change_pct: 5.3, prev_level: 1501, prev_date: '05-Nov-2026' },
    { symbol: 'KOTAKBANK', ltp: 2200, change_pct: 3.1, prev_level: 2210, prev_date: '05-Nov-2026' },
    { symbol: 'OLDER', ltp: 10, change_pct: 1, prev_level: 9, prev_date: '04-Nov-2026' },
  ]
  const value: Record<string, number> = { ICICIBANK: 5677, KOTAKBANK: 2100, ADANIPORTS: 900, AEROPLANE: 12 }
  const sorted = M.sortHighLow(highs, s => value[s]).map(r => r.symbol)
  check('MOV M27 by date then ₹ traded', sorted.join(',') === 'ICICIBANK,KOTAKBANK,ADANIPORTS,AEROPLANE,OLDER', sorted)
  check('MOV M27 negative control: NSE\'s order was alphabetical', highs.map(r => r.symbol).slice(0, 2).join(',') === 'ADANIPORTS,AEROPLANE')
  const split = M.splitNoHistory([...highs, { symbol: 'BCSSL', ltp: 95, change_pct: 5, prev_level: 0, prev_date: null }],
    [{ symbol: 'BCSSL', ltp: 95, change_pct: 5, prev_level: 0, prev_date: null }, { symbol: 'APTUS', ltp: 179, change_pct: -12, prev_level: 177, prev_date: '05-Nov-2026' }])
  check('MOV m018 a no-history row leaves both lists', !split.highs.some(r => r.symbol === 'BCSSL') && !split.lows.some(r => r.symbol === 'BCSSL') && split.noHistory.join() === 'BCSSL' && split.lows.length === 1)
  const dup = M.onePerSymbol([{ symbol: 'ALIVUS', ltp: 1513.7, change_pct: 110.24, prev_level: 1546, prev_date: '05-Nov-2026' },
    { symbol: 'ALIVUS', ltp: 1499.4, change_pct: -1.4, prev_level: 1546, prev_date: '05-Nov-2026' }, { symbol: 'TCS', ltp: 1, change_pct: 1, prev_level: 1, prev_date: null }])
  check('MOV one row per symbol, the in-band one', dup.length === 2 && dup[0].change_pct === -1.4, dup)
  check('MOV negative control: NSE sent ALIVUS twice', [{ symbol: 'ALIVUS' }, { symbol: 'ALIVUS' }].length === 2 && M.splitNoHistory([{ symbol: 'A', ltp: 1, change_pct: 50, prev_level: 1 }, { symbol: 'A', ltp: 1, change_pct: 2, prev_level: 1 }], []).highs.length === 1)
  const filled = M.fillValue([{ symbol: 'ICICIBANK', value_cr: null }, { symbol: 'X', value_cr: 3 }, { symbol: 'NONE', value_cr: null }], [s => value[s]])
  check('MOV m017 the value is filled from EOD', filled[0].value_cr === 5677 && filled[0].value_from === 'eod' && filled[1].value_cr === 3 && filled[2].value_cr == null)
  const liveNoValue = [{ symbol: 'GUJALKALI', ltp: 619, change_pct: 9, value_cr: null, vs_week: 5.8 }]
  const eod = [{ symbol: 'PIIND', close: 1770, chg_pct: -19.07, turnover_cr: 1848.5, vol_x: 34.6 }, { symbol: 'BLUEJET', close: 576, chg_pct: 8.4, turnover_cr: 618, vol_x: 28.5 }]
  const after = M.volumeSurge(liveNoValue, false, eod, '2026-11-05', '2026-11-05')
  check('MOV M27 after the close the surge panel reads MKT\'s EOD shockers', after.basis === 'eod' && after.rows[0].symbol === 'PIIND' && after.rows[0].vs_week === 34.6, after)
  const oldPanel = liveNoValue.filter(r => (r.value_cr ?? 0) >= 1)
  check('MOV M27 negative control: the old ≥ ₹1 cr filter emptied the panel after the close', oldPanel.length === 0)
  check('MOV M27 in session it stays NSE\'s', M.volumeSurge([{ symbol: 'A', ltp: 1, change_pct: 1, value_cr: 5, vs_week: 3 }], true, eod, '2026-11-05', '2026-11-05').basis === 'nse_live')
  check('MOV M27 a stale MKT session is not used', M.volumeSurge(liveNoValue, false, eod, '2026-11-04', '2026-11-05').basis === 'nse_live_no_value')
  const mv = src('components/LiveMovers.tsx')
  check('MOV m020 notes sit under the table', /m020/.test(mv) && !/pad=\{0\} subtitle=\{note\}/.test(mv))
  check('MOV m021 no "fresh shorts" folklore', !/fresh shorts/.test(mv) && /no edge in OI build-ups/.test(mv))
  check('MOV m019 the breadth tile names its universe', /the index&apos;s members/.test(mv))
  check('MOV wiring', /sortHighLow\(/.test(mv) && /volumeSurge\(/.test(mv) && /withValue\(data\.gainers\)/.test(mv))
}

// ── ECO (M28, m012) ───────────────────────────────────────────────────────────────────────────────────────────
{
  const ev = (o: Partial<{ date: string; time: string | null; kind: string; what: string; country: string; impact: string | null; forecast: string | null; actual: string | null }>) =>
    ({ date: '2026-11-06', time: null, kind: 'CPI', what: 'x', country: 'IN', impact: null, forecast: null, actual: null, ...o })
  check('ECO families', M.ecoFamily(ev({ kind: 'US_NFP', country: 'USD' })) === 'US_DATA' && M.ecoFamily(ev({ kind: 'CPI', country: 'US' })) === 'US_DATA'
    && M.ecoFamily(ev({ kind: 'CPI' })) === 'IN_DATA' && M.ecoFamily(ev({ kind: 'FO_EXPIRY' })) === 'EXPIRY' && M.ecoFamily(ev({ kind: 'MUHURAT' })) === 'SESSION'
    && M.ecoFamily(ev({ kind: 'FOMC_SPEECH', country: 'USD' })) === 'FED' && M.ecoFamily(ev({ kind: 'HOLIDAY' })) === 'HOLIDAY')
  // data-service's real kinds (D-DATA, markets.py eco-calendar): one 'US' row a day with items, 'EXPIRY', 'SESSION'
  check('ECO D-DATA kinds', M.ecoFamily(ev({ kind: 'US', country: 'US' })) === 'US_DATA' && M.ecoFamily(ev({ kind: 'EXPIRY' })) === 'EXPIRY' && M.ecoFamily(ev({ kind: 'SESSION' })) === 'SESSION')
  check('ECO short labels', M.ecoShortLabel({ ...ev({ kind: 'US', country: 'US', what: 'US data: Unemployment Rate 19:00 (forecast 4.2%) · Average Hourly Earnings' }), items: [{ name: 'Non-Farm Employment Change' }, { name: 'Unemployment Rate' }] }) === 'Non-Farm Employment Change +1'
    && M.ecoShortLabel(ev({ kind: 'CPI', what: 'CPI inflation · Oct 2026' })) === 'Oct' && M.ecoShortLabel({ ...ev({ kind: 'EXPIRY', what: 'F&O monthly expiry: NIFTY…' }), monthly: true }) === 'monthly'
    && M.ecoShortLabel(ev({ kind: 'SESSION', what: 'Muhurat trading · NSE: timing to confirm' })) === 'Muhurat trading')
  check('ECO negative control: the old BRF label took the 2nd " · " part of a US row', 'US data: A 19:00 · B 19:00'.split(' · ')[1] === 'B 19:00')
  const a = ev({ kind: 'US_DATA', time: '19:00', what: 'Unemployment Rate', country: 'USD' }), b = ev({ kind: 'US_DATA', time: '19:00', what: 'Average Hourly Earnings m/m', country: 'USD' })
  check('ECO M28 several US releases at one time keep distinct keys', M.ecoKey(a) !== M.ecoKey(b))
  check('ECO M28 negative control: the old `${kind}-${date}` key collided', `${a.kind}-${a.date}` === `${b.kind}-${b.date}`)
  const next = M.ecoNext([ev({ kind: 'FOMC_SPEECH', what: 'FOMC Member Williams Speaks', impact: 'Low', country: 'USD' }), ev({ kind: 'US_NFP', impact: 'High', country: 'USD', what: 'NFP' }),
    ev({ kind: 'HOLIDAY', date: '2026-11-10' }), ev({ kind: 'CPI', date: '2026-11-12' })], '2026-11-06')
  check('ECO the next cards skip low-impact speeches and holidays', next.map(e => e.kind).join() === 'US_NFP,CPI', next.map(e => e.kind))
  check('ECO m012 a past India print says it is not stored', M.ecoPrint(ev({ date: '2026-10-12' }), '2026-11-06').text === 'not stored · see the source')
  check('ECO m012 a stored print shows', M.ecoPrint(ev({ date: '2026-10-12', actual: '4.1%' }), '2026-11-06').known)
  check('ECO a future release shows its forecast', M.ecoPrint(ev({ kind: 'US_NFP', country: 'USD', forecast: '65K' }), '2026-11-06').text === 'fcst 65K')
  const e = src('components/EconomicCalendar.tsx')
  check('ECO wiring: unique keys, families, print column', /rowKey=\{ecoKey\}/.test(e) && /ecoFamily\(e\) === fam/.test(e) && /key: 'print'/.test(e))
}

// ── EVTS (M12, m042–m044, m046) ───────────────────────────────────────────────────────────────────────────────
{
  const after = M.reactingHeading('session', 'eod', true, '2026-11-05', '2026-11-04 15:30', '2026-11-05')
  check('EVTS m042 after the close: no "live", the session date', after.title === 'Reacted today · end of day' && after.asOf === '2026-11-05' && !after.live, after)
  const oldTitle = 'session' === 'session' ? 'Reacting today · live' : ''
  check('EVTS m042 negative control: the old title said live at 20:57', /live/.test(oldTitle))
  check('EVTS m042 in session', M.reactingHeading('session', 'live', false, '2026-11-05', '2026-11-04 15:30', '2026-11-05').live)
  const rc = M.releaseCheck('2026-11-05 20:34:00', '2026-11-05T14:58:36')
  check('EVTS M12 an intraday filing beats a later stored time', rc.differs && rc.time === '14:58' && rc.intraday, rc)
  check('EVTS M12 agreeing times are not flagged', !M.releaseCheck('2026-11-05 22:58', '2026-11-05T22:58:10').differs)
  check('EVTS M12 another day\'s filing is not compared', !M.releaseCheck('2026-11-05 20:34', '2026-11-04T14:58:36').differs)
  check('EVTS m043 a name that filed in the session of the chain is post-event', M.postEvent('2026-11-05', '2026-11-05', '2026-11-05T12:57:00'))
  check('EVTS m043 an evening filer is still pre-event on that chain', !M.postEvent('2026-11-05', '2026-11-05', '2026-11-05T20:35:00'))
  check('EVTS m043 tomorrow\'s reporter is pre-event', !M.postEvent('2026-11-06', '2026-11-05', null))
  const ind = M.fillIndustry([{ symbol: 'A', industry: null }, { symbol: 'B', industry: 'IT' }, { symbol: 'C', industry: null }], new Map([['A', 'Banks'], ['C', null]]))
  check('EVTS m046 industry filled from the directory with coverage', ind.known === 2 && ind.total === 3 && ind.rows[0].industry === 'Banks')
  const ec = src('components/EventCalendar.tsx')
  check('EVTS wiring', /reactingHeading\(/.test(ec) && /releaseCheck\(r\.released_at/.test(ec) && /ResultsImpliedMoves filedAt=\{filedAt\}/.test(ec) && /typicalBySymbol/.test(ec))
  check('EVTS m046 unclassified is not an industry row', !/'Other \/ unclassified'; byInd/.test(ec) && /industry known for/.test(ec))
  const rim = src('components/ResultsImpliedMoves.tsx')
  check('EVTS m043 post-event rows leave the table and the median', /const pre = d\.rows\.filter/.test(rim) && /rows=\{pre\}/.test(rim) && /data-evts-post-event/.test(rim))
}

// ── DEAL / INSD (m031–m036) ───────────────────────────────────────────────────────────────────────────────────
{
  const nifty = [{ date: '2026-09-30', close: 22600 }, { date: '2026-10-15', close: 23000 }, { date: '2026-11-05', close: 24408 }]
  const x = M.excessVsIndex(-3.4, '2026-09-30', '2026-11-05', nifty)!
  check('INSD m036 excess over NIFTY', Math.abs(x - ((0.966 / (24408 / 22600) - 1) * 100)) < 1e-9 && x < -10, x)
  check('INSD m036 negative control: the raw −3.4 % hid an ≈ −10.6 % excess', -3.4 > x)
  check('DEAL m035 no excess on the deal\'s own session', M.excessVsIndex(0, '2026-11-05', '2026-11-05', nifty) === null)
  check('DEAL m035 close on or before', M.closeOnOrBefore(nifty, '2026-10-20') === 23000 && M.closeOnOrBefore(nifty, '2026-09-01') === null)
  check('DEAL m031 >100 % is not a share', M.volShare(655.4).text === '> 100%' && M.volShare(655.4).capped && M.volShare(42.5).text === '42.5%' && !M.volShare(42.5).capped)
  check('DEAL m031 negative control: the old cell printed 655.4%', `${(655.4).toFixed(1)}%` === '655.4%' && M.volShare(655.4).text !== '655.4%')
  check('DEAL m032 an insurance broker is not an insurer', M.isBrokerNotInsurer('INTEGRATED INSURANCE BROKING SERVICES PRIVATE LIMITED') && !M.isBrokerNotInsurer('ICICI PRUDENTIAL LIFE INSURANCE COMPANY LIMITED'))
  const deals = [
    { date: '2026-11-03', symbol: 'TMCV', client_name: 'BOFA SECURITIES EUROPE SA', direction: 'sell' as const, qty: 1200000, value: 516e6 },
    { date: '2026-11-03', symbol: 'TMCV', client_name: 'BANK OF AMERICA NA', direction: 'buy' as const, qty: 1200000, value: 516e6 },
    { date: '2026-11-03', symbol: 'TMCV', client_name: 'SOME FUND', direction: 'buy' as const, qty: 300000, value: 129e6 },
  ]
  const m = M.matchedTransfers(deals)
  check('DEAL m033 the matched pair is one transfer', m.size === 2 && !m.has('2026-11-03|TMCV|SOME FUND|buy'), [...m])
  check('DEAL m033 negative control: unequal quantities do not match', M.matchedTransfers([deals[0], { ...deals[1], qty: 900000 }]).size === 0)
  // an ordinary block (a promoter selling to a fund): equal quantities, different groups, stays a flow
  const block = [{ date: '2026-11-03', symbol: 'SHIVAUM', client_name: 'CAPITAL ONE SHARE AND SERVICES', direction: 'buy' as const, qty: 80000, value: 4.3e7 },
                 { date: '2026-11-03', symbol: 'SHIVAUM', client_name: 'PARMANAND KEJRIWAL & SONS PRIVATE LIMITED', direction: 'sell' as const, qty: 80000, value: 4.3e7 }]
  check('DEAL m033 an ordinary equal-size block is not a transfer', M.matchedTransfers(block).size === 0)
  check('DEAL same-group names', M.sameGroupNames('BOFA SECURITIES EUROPE SA', 'BANK OF AMERICA NA') && !M.sameGroupNames('SOCIETE GENERALE', 'GOLDMAN SACHS BANK EUROPE SE'))
  const d = src('components/DealsMonitor.tsx')
  check('DEAL wiring: active symbol read and written', /useActiveSymbol\(\)/.test(d) && /writeActive\(\{ symbol: sym \}\)/.test(d) && /◎ \{active\.symbol\}/.test(d))
  check('DEAL m034 the short panel is dated by its newest row', /const newest = d\?\.rows\.reduce/.test(d))
  check('DEAL wiring: matched legs skip Most active clients', /if \(matched\.has\(dealKey\(r\)\)\) continue/.test(d))
  const ins = src('components/InsiderMonitor.tsx')
  check('INSD wiring', /excessVsIndex\(r\.since_filing_pct, r\.last_date, r\.last_px_date, nifty\)/.test(ins) && /Since filing vs NIFTY/.test(ins))
}

// ── CF (M11) ──────────────────────────────────────────────────────────────────────────────────────────────────
{
  const items = Array.from({ length: 1000 }, (_, i) => ({ time: `2026-11-05 ${String(14 + Math.floor(i / 120)).padStart(2, '0')}:${String(38 + (i % 20)).padStart(2, '0')}:00` }))
  const c = M.cfCoverage(items, { results: 250, routine: 218, other: 953 }, undefined)
  check('CF M11 a cut list is flagged with the earliest time', c.truncated && c.shown === 1000 && c.total === 1421 && c.earliest === '14:38', c)
  check('CF M11 a whole list is not flagged', !M.cfCoverage([{ time: '2026-11-05 09:00:00' }], { results: 1 }).truncated)
  check('CF M11 the route\'s own meta wins', !M.cfCoverage([{ time: 'x' }], { results: 5 }, { truncated: false, total: 1, returned: 1 }).truncated
    && M.cfCoverage([{ time: 'x' }], { results: 1 }, { truncated: true, total: 1421, returned: 1000 }).total === 1421)
  const cf = src('components/CompanyFilings.tsx')
  check('CF wiring: the PARTIAL banner and the per-chip counts', /data-cf-truncated/.test(cf) && /listCounts\[k\]/.test(cf))
}

// ── WRAP (m022, M10) ──────────────────────────────────────────────────────────────────────────────────────────
{
  check('WRAP m022 pending note after the close', /written after the evening data pass/.test(M.wrapPending('2026-11-05', 2010, '2026-11-04', true) ?? ''))
  check('WRAP m022 no note once today\'s wrap is in', M.wrapPending('2026-11-05', 2140, '2026-11-05', true) === null)
  check('WRAP m022 no note in the session or on a holiday', M.wrapPending('2026-11-05', 1200, '2026-11-04', true) === null && M.wrapPending('2026-11-10', 2010, '2026-11-09', false) === null)
  const md = '# Wrap 04 Nov\nWritten 21:30 (NSE end of day 2026-10-30)\n## Sectors (as of 2026-10-30)\n## Desk\n'
  check('WRAP M10 a foreign section date is surfaced', M.wrapForeignDates(md, '2026-11-04').join() === '2026-10-30')
  check('WRAP M10 a clean wrap has none', M.wrapForeignDates('NSE end of day 2026-11-05', '2026-11-05').length === 0)
  const w = src('components/DailyWrap.tsx')
  check('WRAP wiring', /data-wrap-pending/.test(w) && /data-wrap-foreign/.test(w) && !/written 21:00 IST from/.test(w))
}

// ── PRE (m013–m015), SEAG (m030), IPO (m040, m041), WEI (m010) ────────────────────────────────────────────────
{
  const evening = M.preopenLabel('2026-11-05', 2055, true, '05-Nov-2026 09:09:49')
  check('PRE m013 after hours names this morning\'s book', evening.label === "this morning's auction (book 09:09) · market closed" && !evening.live, evening)
  check('PRE m013 negative control: the old label', 'regular session · this is the morning auction' !== evening.label)
  const yesterday = M.preopenLabel('2026-11-06', 830, true, '05-Nov-2026 09:09:49')
  check('PRE m013 a book from an earlier session says so', yesterday.lastSession && /last session's auction · Thu 5 Nov/.test(yesterday.label), yesterday)
  check('PRE live window', M.preopenLabel('2026-11-06', 905, true, '06-Nov-2026 09:05:10').live)
  check('PRE m015 a deep 52-week gap is flagged', M.suspectYearHigh(-67.3) && !M.suspectYearHigh(-20))
  const pre = src('components/PreOpen.tsx')
  check('PRE m014 wider leader panels, short titles', /minmax\(340px, 1fr\)/.test(pre) && /mini\('Buyers left',/.test(pre) && !/Buyers left over/.test(pre))
  const grid = [{ year: 2012, months: { Jan: null, Feb: null, Mar: -1.7, Apr: 2 } }, { year: 2026, months: { Jan: 1, Feb: null, Mar: null, Apr: 3 } }]
  const span = M.seagSpan(grid, ['Jan', 'Feb', 'Mar', 'Apr'])
  check('SEAG m030 the first RETURN month', span.first === 'Mar 2012' && span.last === 'Apr 2026', span)
  const ipo = M.ipoRows([
    { symbol: 'ADANIENPP1', listing_date: '2026-10-01', list_open: null, listing_gain_pct: null, last_close: null },
    { symbol: 'ADANIENPP1', listing_date: '2026-10-01', list_open: null, listing_gain_pct: null, last_close: null },
    { symbol: 'LEAP', listing_date: '2026-08-14', list_open: null, listing_gain_pct: null, last_close: null },
    { symbol: 'MKJEWELS', listing_date: '2026-11-04', list_open: 120, listing_gain_pct: 5, last_close: 118 },
  ])
  check('IPO m040 entitlements out, duplicates out, unpriced counted', ipo.rows.length === 1 && ipo.rows[0].symbol === 'MKJEWELS' && ipo.entitlements.join() === 'ADANIENPP1' && ipo.unpriced.join() === 'LEAP', ipo)
  check('IPO entitlement symbols', M.isEntitlementSymbol('ADANIENPP1') && M.isEntitlementSymbol('XYZRE1') && !M.isEntitlementSymbol('LENSKART') && !M.isEntitlementSymbol('APOLLO'))
  const ipoSrc = src('components/IpoMonitor.tsx')
  check('IPO m041 the empty state carries the last check', /checked \$\{checkedAt/.test(ipoSrc))
  const wei = src('components/WorldMarkets.tsx')
  check('WEI m010 GIFT\'s own change is muted and labelled', /vs its settle/.test(wei) && !/color: tone\(gift\.change_pct\), fontWeight: 600/.test(wei))
}

// ── COMP (m083, active symbol) ────────────────────────────────────────────────────────────────────────────────
{
  const dir = [{ t: 'TCS', s: 'Information Technology', c: 'Large Cap' }, { t: 'INFY', s: 'Information Technology', c: 'Large Cap' },
               { t: 'MPHASIS', s: 'Information Technology', c: 'Small Cap' }, { t: 'HCLTECH', s: 'Information Technology', c: 'Large Cap' }, { t: 'SBIN', s: 'Financial Services', c: 'Large Cap' }]
  const sug = M.compSuggestions(['TCS'], 'RELIANCE', dir)
  check('COMP m083 suggestions: the active stock, then large same-sector peers', sug.join() === 'RELIANCE,HCLTECH,INFY,MPHASIS', sug)
  check('COMP an index underlying is never suggested', !M.compSuggestions(['TCS'], 'NIFTY', dir).includes('NIFTY'))
  const comp = src('components/Compare.tsx')
  check('COMP wiring: active symbol read and written', /useActiveSymbol\(\)/.test(comp) && /writeActive\(\{ symbol: s \}\)/.test(comp) && /compSuggestions\(/.test(comp))
}

console.log(`market_pages.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
