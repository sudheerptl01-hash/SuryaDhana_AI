/**
 * Honesty sweep checks (H-HONESTY, 6 Nov 2026; the 5 Nov 43-page review M19–M24, M29 and the ALFA / BTST / FUND / PIPE /
 * LWSC / RSCH / GBOX / MLEN / DEXP / WHSE minors). Pure helpers run under plain node; page wiring is checked on the
 * source. Every rule has a negative control.
 *
 * Run: node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/components/__tests__/honesty.check.ts
 */
import * as fs from 'node:fs'
import * as path from 'node:path'

type BtstMod = typeof import('../btstDefaults')
type FundMod = typeof import('../fundScreenRules')
type DexpMod = typeof import('../dexpRules')
type KitMod = typeof import('../honestyKit')
const B = (await import(new URL('../btstDefaults.ts', import.meta.url).href)) as BtstMod
const F = (await import(new URL('../fundScreenRules.ts', import.meta.url).href)) as FundMod
const D = (await import(new URL('../dexpRules.ts', import.meta.url).href)) as DexpMod
const K = (await import(new URL('../honestyKit.ts', import.meta.url).href)) as KitMod

const UI = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
const src = (f: string) => fs.readFileSync(path.join(UI, f), 'utf8')
let pass = 0, fail = 0
const check = (name: string, ok: boolean, detail?: unknown) => {
  if (ok) { pass++; return }
  fail++
  console.error(`FAIL ${name}${detail !== undefined ? ` :: ${JSON.stringify(detail)}` : ''}`)
}

// ── BTST (M20 / m092): Desk-like defaults, the real round trip, no silent stop ─────────────────────────────────────
{
  check('B1 Desk-like defaults: 20 names, 21 sessions, no stop, the −20 % breaker, no legacy daily halt',
    B.DESK_LIKE.maxPositions === 20 && B.DESK_LIKE.holdSessions === 21 && B.DESK_LIKE.stopMode === 'none'
    && B.DESK_LIKE.ddHaltPct === 20 && B.DESK_LIKE.dailyHalt === false)
  check('B1 the round trip → bps, rounded up to 0.1 bps', B.frictionFromRoundTrip(0.9122) === 91.3 && B.frictionFromRoundTrip(1.0019) === 100.2,
    [B.frictionFromRoundTrip(0.9122), B.frictionFromRoundTrip(1.0019)])
  check('B1 never below the 15 bps floor; no number from a broken ticket', B.frictionFromRoundTrip(0.05) === 15
    && B.frictionFromRoundTrip(null) === null && B.frictionFromRoundTrip(0) === null && B.frictionFromRoundTrip(Number.NaN) === null)
  check('B1 position size = capital ÷ names', B.positionValue(10_000_000, 20) === 500_000 && B.positionValue(10_000_000, 0) === 10_000_000)
  const none = B.stopPayload('none', 2, 2), atr = B.stopPayload('atr', 2, 2), fixed = B.stopPayload('fixed', 2, 3)
  check('B2 no stop sends BOTH stop fields null (the API ATR stop cannot switch on silently)', none.atr_stop_mult === null && none.stop_loss_pct === null)
  check('B2 negative control: k·ATR and fixed % do send a stop', atr.atr_stop_mult === 2 && atr.stop_loss_pct === 2 && fixed.atr_stop_mult === null && fixed.stop_loss_pct === 3)
  check('B3 the legacy setup is called out, the Desk-like one is not',
    B.looksLegacy({ holdSessions: B.LEGACY_DEFAULTS.holdSessions, maxPositions: B.LEGACY_DEFAULTS.maxPositions, frictionBps: B.LEGACY_DEFAULTS.frictionBps })
    && !B.looksLegacy({ holdSessions: 21, maxPositions: 20, frictionBps: 91.3 }) && B.looksLegacy({ holdSessions: 21, maxPositions: 20, frictionBps: 15 }))
  const bt = src('components/BacktestPanel.tsx')
  check('B4 BTST reads the cost from the shared model (/api/costs/ticket), not a constant', bt.includes('getTradeTicket({ value, price: 1 })')
    && bt.includes('frictionFromRoundTrip(r.data.round_trip_pct)') && !bt.includes('useState(15)'))
  check('B4 BTST sends the stop and the daily halt explicitly', bt.includes('atr_stop_mult: stops.atr_stop_mult') && bt.includes('daily_loss_halt_pct: dailyHalt ? 2 : null'))
  check('B4 the legacy defaults FAIL banner and the P(up · 5d) FAIL marker', bt.includes('<ResearchNote verdict="FAIL" report="reports/handbook_swing/REPORT.md">')
    && bt.includes('RSCH · FAIL</span>') && bt.includes('Run the Desk-like baseline'))
}

// ── FUND (M21, m080–m082, m003) ───────────────────────────────────────────────────────────────────────────────────
{
  const coal = F.outlierReason({ revenue_yoy: 199.6, pat_yoy: 261.2, period_end: '2026-09-30' })
  const siem = F.outlierReason({ revenue_yoy: 8.4, pat_yoy: 406.2, period_end: '2026-06-30' })
  const tcs = F.outlierReason({ revenue_yoy: 11.2, pat_yoy: 14.9, period_end: '2026-09-30' })
  const paytm = F.outlierReason({ revenue_yoy: 28.5, pat_yoy: 971.4, period_end: '2026-09-30' })
  check('F1 implausible growth is flagged (COALINDIA, SIEMENS, a +971 % profit)', !!coal && !!siem && !!paytm && coal!.includes('verify on FA'), [coal, siem])
  check('F1 negative control: an ordinary quarter is not flagged', tcs === null && F.outlierReason({ revenue_yoy: null, pat_yoy: null, period_end: '' }) === null)
  check('F1 a fall prints U+2212', (F.outlierReason({ revenue_yoy: -54.2, pat_yoy: 26.5, period_end: '' }) ?? '').includes('−54.2'))
  check('F2 two quarters behind = stale (merged / delisted)', F.staleRow('2024-06-30', '2026-09-30') && F.staleRow('2026-03-31', '2026-09-30'))
  check('F2 negative control: one quarter behind in results season is not stale', !F.staleRow('2026-06-30', '2026-09-30') && !F.staleRow('2026-09-30', '2026-09-30') && !F.staleRow('2024-06-30', null))
  const fs_ = src('components/FundamentalsScreen.tsx')
  check('F3 the footer reads the verdict from the catalog at render time', fs_.includes('<CatalogLine id="reports/earnings_growth_drift/FINDINGS.md" />')
    && !fs_.includes('(PROMISING, not proven; selection bias)'))
  check('F4 MATCHES carries a badge; the P/E percentile is not coloured cheap-green / dear-red', fs_.includes('badge="arithmetic" title={`${shown.length} matches`}')
    && !fs_.includes('r.pe_pctl <= 20 ? T.green'))
  check('F5 stale rows hidden by default, outliers marked', fs_.includes('const [showStale, setShowStale] = useState(false)') && fs_.includes('data-fund-outlier'))
}

// ── DEXP (M29, m115) ──────────────────────────────────────────────────────────────────────────────────────────────
{
  const rows = Array.from({ length: 12 }, (_, i) => ({ ticker: `T${i}`, date: '2026-11-05', ret_1d: i / 100, return_lag_1d: i / 100,
    ret_5d: i / 50, return_lag_5d: i / 50, return_lag_2d: i / 70, trailing_pe: null, profit_margins: null }))
  const dups = D.duplicateColumns(['ticker', 'date', 'ret_1d', 'ret_5d', 'return_lag_1d', 'return_lag_2d', 'return_lag_5d', 'trailing_pe', 'profit_margins'], rows)
  check('D1 RETURN_LAG_1D / 5D are reported as repeats of RET_1D / 5D', dups.return_lag_1d === 'ret_1d' && dups.return_lag_5d === 'ret_5d', dups)
  check('D1 negative controls: a different column, an all-null column and a short page are not duplicates', !dups.return_lag_2d && !dups.profit_margins
    && Object.keys(D.duplicateColumns(['ret_1d', 'return_lag_1d'], rows.slice(0, 5))).length === 0)
  check('D2 the 15 fundamental columns are named', D.FUNDAMENTAL_FEATURES.length === 15 && D.FUNDAMENTAL_FEATURES.includes('trailing_pe'))
  const dx = src('components/DataExplorerTab.tsx')
  check('D3 DEXP calls no Yahoo fetch route (the three buttons are gone)', !/fetchRefreshBatch|fetchHistorical|fetchFundamentals|\/api\/data\/fetch\//.test(dx))
  check('D3 no "LIVE FEED" chip on the EOD grid; badges present', !dx.includes('LIVE FEED · {provider') && dx.includes('<BadgeChip badge="arithmetic"') && dx.includes('<BadgeChip badge="context"'))
  check('D4 feature values are not coloured as signals', !dx.includes("'text-emerald-300'") && !dx.includes("val > 70) return 'text-red-400'"))
}

// ── ALFA (M19, m089–m091): no Yahoo on the request path, intervals, real costs ──────────────────────────────────────
{
  const al = src('components/AlphaDiscoveryDesk.tsx')
  check('A1 ALFA calls no Yahoo fetch route and drops the clipping status widget', !/fetchRefreshBatch|\/api\/data\/fetch\//.test(al) && !al.includes('<SystemStatusWidget'))
  check('A2 window and history tiles with intervals; no "friction-adj" label', al.includes('<EdgeTile label="WINDOW · NET 5D"') && al.includes('<EdgeTile label="HISTORY · NET 5D"')
    && !al.includes('sub="friction-adj"') && al.includes('mean_net5_ci95_bps'))
  check('A3 CHG % falls back to the last close-to-close change, marked EOD', al.includes('r.eod_change_pct ?? null') && al.includes("> EOD</span>"))
  check('A4 one count on the page (no "Refresh Matched (25)" beside "Monitor All (32)")', !al.includes('↻ Refresh Matched') && !al.includes('refreshMatched') && al.includes('Monitor all {scan?.tickers.length ?? 0} names'))
}

// ── PIPE / LWSC / RSCH-fed banners, GBOX, MLEN, WHSE ─────────────────────────────────────────────────────────────
{
  const pipe = src('components/PipelineStudio.tsx')
  check('P1 PIPE carries the RESEARCH · FAIL banner from the catalog', pipe.includes('<CatalogNote id="reports/ml_labels/FINDINGS.md" fallback="FAIL"'))
  check('P2 the date range is the data span, the last-bar range is labelled as such', pipe.includes("label: 'Data span (first → last bar)'") && pipe.includes("label: 'Last bar, oldest → newest ticker'")
    && !pipe.includes("label: 'Date Range'"))
  check('P3 no "(70 indicators)" over 24 chips; no "All requirements met"', !pipe.includes('indicators)</p>') && !pipe.includes("'All requirements met'"))
  const lw = src('components/LWScanner.tsx')
  check('L1 LWSC shows STALE and the FDR line; the star means q < 0.05', lw.includes('data-lw-stale') && lw.includes('row.cycle_significant_fdr') && lw.includes('<BadgeChip badge="heuristic"'))
  check('L1 negative control: the raw "p < 0.05 → *" rule is gone', !lw.includes('{row.cycle_pvalue < 0.05 && <span className="ml-1 text-amber-400 text-xs" title="p < 0.05">*</span>}'))
  const gb = src('components/GlassBoxStudio.tsx')
  check('G1 GBOX renders on open, cites the volume-profile verdict, badges each lens, states the RRG window', gb.includes('rendered.current[mode] = true')
    && gb.includes('<CatalogNote id="reports/value_area/REPORT.md" fallback="NO EDGE"') && (gb.match(/badge="context"/g) ?? []).length >= 3
    && gb.includes('-session normalisation'))
  check('G2 unambiguous dates', K.longDate('2026-02-05') === '5 Feb 2026' && K.longDate('2026-11-05') === '5 Nov 2026' && K.longDate('bad') === 'bad')
  const ml = src('components/MLEngineWorkspace.tsx')
  check('M1 MLEN names its labels (v2 5-day, FAIL) and guards a production run in a freeze window', ml.includes('data-mlen-labels') && ml.includes('v2 5-day labels')
    && ml.includes("mode === 'production' && !override ? inFreezeWindowIST() : null"))
  check('M2 freeze windows in IST', K.inFreezeWindowIST(new Date('2026-11-06T03:00:00Z')) !== null              // 08:30 IST
    && K.inFreezeWindowIST(new Date('2026-11-06T14:00:00Z')) !== null                                          // 19:30 IST
    && K.inFreezeWindowIST(new Date('2026-11-06T05:30:00Z')) === null                                          // 11:00 IST (negative control)
    && K.inFreezeWindowIST(new Date('2026-11-06T02:14:00Z')) === null)                                         // 07:44 IST, one minute before
  const wh = src('components/WarehouseHealth.tsx')
  check('W1 WHSE says POPULATED, not HEALTHY, and shows the catalog stale count', wh.includes("rawStatus === 'HEALTHY' ? 'POPULATED'") && wh.includes('DATA ${nStale} STALE'))
  check('W2 the fundamentals bar says snapshot; the ML panel carries the label verdict', wh.includes('Fundamentals snapshot (one undated record each)')
    && wh.includes('<CatalogNote id="reports/ml_labels/FINDINGS.md" fallback="FAIL"'))
  const fr = K.catalogFreshness({ state: 'amber', lag_sessions: 2, note: 'late', expected_by: '21:00' })
  check('W3 catalog freshness for the gold / IV / index tables', fr.text === 'AMBER · 2 sess' && fr.tone === 'warn' && fr.title.includes('21:00')
    && K.catalogFreshness({ state: 'fresh', lag_sessions: 0 }).tone === 'ok' && K.catalogFreshness({ state: 'gap', lag_sessions: 4 }).text === 'GAP · 4 sess'
    && K.catalogFreshness({ state: 'red', lag_sessions: 9 }).text === '⚠ STALE · 9 sess')
  check('W3 the dataset table reads the catalog first', src('components/NseDatasets.tsx').includes('const h = health[r.table]'))
}

// ── RSCH layout (6 Nov audit): a long report scrolls in its own pane and the first visit opens a study ──────────────────
{
  const rl = src('components/ResearchLibrary.tsx')
  check('R1 the report pane scrolls on its own (the 2,100-line journal made the page 41,600 px tall)',
    rl.includes("data-rsch-doc-scroll style={{ maxHeight: 'calc(100vh - 230px)', overflowY: 'auto'"))
  check('R1 negative control: the markdown is not rendered straight into an unbounded Panel body',
    !rl.includes('pad={18}>\n              {doc.takeaway'))
  check('R2 the first visit opens the newest study with a verdict, not rows[0]',
    rl.includes('rows.find(r => STUDY_VERDICTS.has(r.verdict)) ?? rows[0]') && !rl.includes(': rows[0]?.id ?? null))'))
}

console.log(`honesty.check: ${pass} passed, ${fail} failed`)
if (fail) process.exit(1)
