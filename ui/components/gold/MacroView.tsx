'use client'

/**
 * GOLD › MACRO (reports/gold_program/PLAN.md a.8): why gold moved — the KGX idea, generalised.
 *
 * Panels: mc.drivers (driver strip with the server's supportive / headwind tag and the rule shown, 60-d correlations) ·
 * mc.kgx ("gold or the dollar?" with a rupee leg) · mc.ccy (gold in six currencies) · mc.fed (Fed path) · mc.calendar
 * (US calendar in IST, in-session flag) · mc.move (expected move per lot) · mc.health (driver-health small multiples) ·
 * mc.context (collapsed). The supportive / headwind tag is the one place PLAN §f.3 allows a direction word, and only
 * with the sign rule printed next to it; the tag is the SERVER's (`drivers[].tag`, API_CONTRACT §2.11) — a null tag
 * (GLD tonnes: "contemporaneous; no lead"; GVZ: size, not direction) renders neutral, the client re-tags nothing.
 * Correlations are contemporaneous (H1/H2): never a lead.
 *
 * Data: `/api/gold/macro` (§2.11: `freshness{drivers, fed, gold}`; the calendar rows carry `date` + `title`);
 * `/api/gold/series` for the rebased gold-vs-basket line and the real-yield scatter. The lag chip of every panel is one
 * of the three server blocks (or none, for the schedule panel); every as-of is a date the block itself carries
 * (driver report dates, `fed.as_of`, `move.gvz_date`, the first calendar date, `context.hy_oas_date`) — never the
 * request clock `as_of`.
 *
 * Wave 1c (the critics' round): a driver tile is labelled by the SERIES the server used (`drivers[].series_id`), so the Fed
 * broad index never prints as "DXY" (C-DATA-4, C-TRADER-8); changes print in the server's one `change_unit` (bp for
 * yields — C-BEGINNER-20); percentiles are written out, never as ordinals (C-BEGINNER-19); when the dollar leg is missing
 * the KGX panel says why and hides the identity check (C-BEGINNER-14); driver-health betas carry their units (C-DATA-21).
 */
import { useMemo, type ReactNode } from 'react'
import { Chip, DataTable, Grid, KV, Loading, Meter, Stat, T, type Column } from '@/components/terminal'
import { getGoldMacro, getGoldSeries } from '@/lib/gold/api'
import type { GoldEvent, GoldSeries, GoldSubViewProps, MacroDriver } from '@/lib/gold/types'
import { tipFor } from '@/lib/gold/learn'
import { goToPage } from '@/lib/navigate'
import tooltipsJson from '@/lib/gold/tooltips.json'
import { KgxBar } from './KgxBar'
import { LineChart, SmallMultiple } from './FlowCharts'
import { Attribution, Degraded, Field, GPanel, Term, contextTone, useGoldLoad } from './ViewBits'
import { DRIVER_RULES, LOT_MULTIPLIER, betaText, driverDelta, driverInstrumentNote, driverNote, driverSources, driverTag, driverTileLabel, fedMeanText, inr, istLabel, kgxNoteText, kgxUnavailableNote, kgxWindowCaption, latestDate, num, pct, serverFreshness, showWindowColumn, sigmaPerLot, signed, signedPct, usd, windowColumnsCaption, windowTag, zqLabel } from './goldViewModel'
import { eventSessionTag, pageRealYield, realYieldMismatch } from '@/lib/gold/format'

const BUNDLED = (tooltipsJson as { tooltips: Record<string, string> }).tooltips
const FAMILIES = ['GOLD', 'GOLDM', 'GOLDTEN', 'GOLDGUINEA', 'GOLDPETAL'] as const
const CCY_SYM: Record<string, string> = { USD: '$', INR: '₹', EUR: '€', JPY: '¥', GBP: '£', CNY: '¥' }
/** driver key → tooltip key (payload fields of PLAN d `macro.drivers`) */
const DRIVER_TIP: Record<string, string> = {
  real_10y: 'tips10', real_2y: 'dgs2', nominal_2y: 'dgs2', breakeven_10y: 't10yie', dxy: 'dxy', usdinr: 'usdinr', gvz: 'gvz', brent: 'brent', gld_t: 'etf_tonnes',
}
/** `/macro` calendar rows are this week's events as `{date, time_ist, title, kind, …}` (§2.11), not `/calendar`'s `{event_date, name}` */
type MacroCalRow = Omit<GoldEvent, 'name' | 'event_date'> & { date?: string | null; event_date?: string | null; title?: string | null; name?: string | null }
type MacroFreshKey = 'drivers' | 'fed' | 'gold'
/**
 * The 8 Nov 2026 window fields (C-DATA-04 / F4), carried locally until types.ts takes them (that file belongs to another
 * lane this round): the page's window on each driver tile, the KGX dollar leg's real source, and the currency table's
 * one-window column with the caption block that says what each column means.
 */
type DriverWin = MacroDriver & { window_label?: string | null; window_from?: string | null; window_to?: string | null
                                 window_note?: string | null; trailing_note?: string | null }
type KgxWin = { to_date?: string | null; usd_source?: string | null; usd_from_date?: string | null; usd_to_date?: string | null
                usd_aligned?: boolean | null; basket_label?: string | null; note?: string | null }
type CcyRow = { ccy: string; price: number | null; unit?: string | null; d1?: number | null; d1w?: number | null
                d1m?: number | null; ytd?: number | null; d_window?: number | null; report_date?: string | null }
type CcyWindow = { window?: string | null; label?: string | null; from_date?: string | null; to_date?: string | null
                   trailing?: Record<string, { days?: number | null; from_date?: string | null }> | null; note?: string | null }

const fmtDriver = (d: MacroDriver, v: number | null | undefined, dp?: number) =>
  d.unit === '%' ? pct(v, dp ?? 2) : d.unit === 'bp' ? `${num(v, dp ?? 0)} bp` : d.unit === 't' ? `${num(v, dp ?? 1)} t` : num(v, dp ?? 2)
/** one unit per tile, the server's `change_unit` (bp for yields and vol, % for prices and indices, t for tonnes) */
const fmtDelta = (d: MacroDriver, v: number | null | undefined) => driverDelta(d, v)
const day = (iso: string | null | undefined) => (iso ? istLabel(iso) : null)

export function MacroView(props: GoldSubViewProps) {
  const { layer, catalog } = props
  const tip = useMemo(() => (k: string) => tipFor(props.tooltips, BUNDLED, k), [props.tooltips])
  const macro = useGoldLoad(() => getGoldMacro(props.window), [props.window], 60_000)
  const rebased = useGoldLoad(() => getGoldSeries(['COMEX_GC_FRONT', 'DXY_CLOSE'], { freq: 'D' }), [])
  const scatter = useGoldLoad(() => getGoldSeries(['COMEX_GC_FRONT', 'FRED_DFII10'], { freq: 'M' }), [])
  const m = macro.data
  const fam = props.sel.family
  // the three server blocks (§2.11) or NO DATA: mc.drivers / mc.health / mc.context wear `drivers`, mc.fed wears `fed`,
  // mc.kgx / mc.ccy / mc.move wear `gold`; the calendar is a schedule and wears no lag chip
  const fb = (k: MacroFreshKey) => (m ? serverFreshness(m.freshness?.[k]) : null)
  // each block's own date (never the request clock)
  const driversDate = day(latestDate((m?.drivers ?? []).map(d => d.report_date)))
  const goldDate = day(latestDate([m?.freshness?.gold?.as_of]))
  const fedDate = day(m?.fed?.as_of)
  const moveDate = day(m?.move?.gvz_date)
  const calRows = (m?.calendar ?? []) as MacroCalRow[]
  const calDate = day(calRows[0]?.date ?? calRows[0]?.event_date)
  const ctxDate = day(m?.context?.hy_oas_date)
  // the dollar driver as served (DXY_CLOSE, or the Fed broad index when the DXY series has no points): the KGX note names it
  const dollar = m?.drivers.find(d => d.key === 'dxy') ?? null
  // the 8 Nov window block: the dollar leg's real source and dates (C-DATA-03) and the table's one window (C-DATA-04)
  const kgxWin = (m?.kgx ?? null) as (NonNullable<typeof m>['kgx'] & KgxWin) | null
  // the SERVER's sentence first (it names the series and the dates it read); the client's text is the fallback
  const kgxNote = m?.kgx ? kgxNoteText(kgxWin?.note, kgxUnavailableNote(m.kgx.usd_effect_pct, dollar)) : null
  const ccyWin = ((m as unknown as { currencies_window?: CcyWindow } | null)?.currencies_window) ?? null
  const ccyRows = ((m?.currencies ?? []) as CcyRow[])
  const driverWin = (m?.drivers ?? []) as DriverWin[]
  // the window's own words for the driver grid's visible caption (F4: the definition must not be hover-only) — the
  // currency block's when it has one, else the first driver that resolved a window
  const winWords = ccyWin?.label ?? driverWin.find(d => d.window_label)?.window_label ?? null
  const winFrom = ccyWin?.from_date ?? driverWin.find(d => d.window_from)?.window_from ?? null
  const winTo = ccyWin?.to_date ?? driverWin.find(d => d.window_to)?.window_to ?? null
  // the currency table's window column: dropped when every row would print the figure its 1D column already prints
  const showCcyWindow = ccyRows.some(c => showWindowColumn(signedPct(c.d_window), signedPct(c.d1),
                                                          signedPct(c.d1w), signedPct(c.d1m)))
  // ONE 10-y real yield per page (wave 1e, M-B): the header strip / HEALTH point this tile must equal; a mismatch is said
  const pageRy = useMemo(() => pageRealYield(props.overview?.strip, props.overview?.health), [props.overview])
  // HEALTH's window start (the TREND gauge's), so the KGX caption compares like with like (wave 1e minor)
  const healthFrom = (props.overview?.health?.gauges ?? []).find(g => g.key === 'trend')?.window_from ?? null

  // gold USD vs gold-in-basket, rebased to 100 over the window (gold-in-basket = gold × DXY ÷ DXY₀: the dollar's own move removed)
  const rebasedSeries = useMemo(() => {
    const gc = rebased.data?.series.find(s => s.series_id === 'COMEX_GC_FRONT')?.points ?? []
    const dxy = rebased.data?.series.find(s => s.series_id === 'DXY_CLOSE')?.points ?? []
    if (gc.length < 2 || dxy.length < 2) return null
    const byDate = new Map(dxy.map(p => [p.report_date, p.value]))
    const pts = gc.slice(-252).filter(p => byDate.has(p.report_date))
    if (pts.length < 2) return null
    const g0 = pts[0].value, d0 = byDate.get(pts[0].report_date) as number
    return [
      { key: 'usd', label: 'gold in USD (rebased)', color: T.amber, values: pts.map(p => ({ x: p.report_date, y: (p.value / g0) * 100 })) },
      { key: 'basket', label: 'gold in the DXY basket (rebased)', color: T.cyan, values: pts.map(p => ({ x: p.report_date, y: (p.value / g0) * ((byDate.get(p.report_date) as number) / d0) * 100 })) },
    ]
  }, [rebased.data])

  const calCols: Column<MacroCalRow>[] = [
    { key: 'date', label: 'Date (IST)', render: r => <span style={{ color: T.text }}>{istLabel(r.date ?? r.event_date ?? '')} {r.time_ist ?? ''}</span> },
    { key: 'title', label: 'Release', render: r => <span>{r.title ?? r.name ?? r.kind}{r.country ? <span style={{ color: T.dim }}> · {r.country}</span> : null}</span> },
    { key: 'impact', label: 'Impact', render: r => r.impact ?? '—' },
    { key: 'forecast', label: 'Consensus', align: 'right', title: tip('cal_consensus'), render: r => r.forecast ?? '—' },
    { key: 'previous', label: 'Previous', align: 'right', render: r => r.previous ?? '—' },
    { key: 'actual', label: 'Actual', align: 'right', render: r => r.actual ?? '—' },
    { key: 'in_session', label: 'MCX', title: tip('cal_in_session'), render: r => {
      // untimed rows are 'ALL DAY' / a closure, never 'AFTER CLOSE · gap risk' (wave 1e minor)
      const tag = eventSessionTag({ time_ist: r.time_ist ?? null, kind: r.kind ?? '', name: r.title ?? r.name ?? '', in_session: r.in_session ?? null, after_close: r.after_close ?? null })
      return tag ? <Chip color={tag.text === 'IN SESSION' ? T.cyan : tag.text.startsWith('AFTER CLOSE') ? T.amber : T.muted} style={{ fontSize: 9 }}>{tag.text}</Chip> : '—'
    } },
  ]

  return (
    <div data-gold-b4b="macro" style={{ display: 'grid', gap: 10 }}>
      {/* mc.drivers */}
      <GPanel id="mc.drivers" title="Drivers" badge="context" evidence="G-MACRO H1/H2: contemporaneous betas; the level link broke in 2022" fresh={fb('drivers')} dateOnly={driversDate}
        series={['FRED_DFII10', 'DXY_CLOSE', 'USDINR_CLOSE', 'GVZ_CLOSE', 'FRED_T10YIE', 'FRED_DGS2']} catalog={catalog} layer={layer}
        subtitle={`supportive / headwind = the server's sign rule, printed on each tile, applied to the page's ${windowTag(props.window)} window — the one HEALTH's gauges and the KGX split use, printed as its own column where it differs from 1 d; a description of today, not a forecast`}
        copyB={<>the cost of holding gold (the <Term t="real yield" />) and the dollar (<Term t="DXY" />) explain most days; the rupee is the MCX leg. Changes in bp for yields: 1 bp = 0.01 pp.</>}
        copyP="weekly beta to real yields −9.9 %/100 bp in 2010–21, −5.0 since 2022 (t −4.0, R² 0.06); dollar beta ≈ −1 in every regime (H2). 4-week changes forecast nothing (G-STUDY).">
        <Degraded error={macro.error} what="macro" />
        {!m && !macro.error && <Loading label="Real yields, the dollar, the rupee, volatility" />}
        {m && (
          <>
            <Grid min={180}>
              {driverWin.map(d => {
                const tag = driverTag(d.tag)                                   // the server's tag; null → neutral (no client rule)
                const rule = d.rule ?? DRIVER_RULES[d.key] ?? 'no sign rule'   // the server's rule text; the local table only when absent
                const label = driverTileLabel(d)                                // the series the server used, never the key's nominal name
                // the served label_note verbatim (a fresher twin of the same quantity, or a stand-in of another), the instrument when
                // it is a future, and — on the real yield — whether the header strip prints the same point (wave 1e, M-B)
                const note = driverNote(d)
                const instrument = driverInstrumentNote(d)
                const ryOff = d.key === 'real_10y' ? realYieldMismatch(pageRy, d) : null
                return (
                  <Stat key={d.key} label={<span title={tip(DRIVER_TIP[d.key] ?? d.key)} data-driver-label={d.series_id ?? d.key} data-driver-print={d.key === 'real_10y' && d.value != null ? `${num(d.value, 2)} %${d.report_date ? ` · ${istLabel(d.report_date)}` : ''}` : undefined}>{label}</span>}
                    value={d.state === 'unavailable' && d.value == null ? '—' : fmtDriver(d, d.value)} color={contextTone} big={false}
                    sub={<span>
                      {d.state === 'unavailable' && d.value == null && <span style={{ color: T.amber }}>{d.series_id ?? d.key}: no stored points · </span>}
                      {/* the WINDOW the tag rests on, printed with the number it rests on and the window's own words
                          (C-DATA-04 / F4): the tile used to print only 1d / 1w / 1m while the tag was computed on a
                          trailing 7 or 30 calendar days the panel called "the selected window". The trailing figures keep
                          their place, renamed 7 d / 30 d — `change_over` counts calendar days, not 5 or 21 sessions. */}
                      {/* …and only when it is a DIFFERENT figure from the 1 d one: in the 'D' window the page's window
                          IS the previous session, and printing "D +0.683 · 1d +0.683" is the same number twice (§f.6). */}
                      {showWindowColumn(fmtDelta(d, d.d_window), fmtDelta(d, d.d1), fmtDelta(d, d.d1w), fmtDelta(d, d.d1m)) && <span data-driver-window={d.window_from ?? ''} title={d.window_label ? `${windowTag(props.window)} = ${d.window_label}${d.window_to ? `, to ${istLabel(d.window_to)}` : ''}` : undefined}><b>{windowTag(props.window)} {fmtDelta(d, d.d_window)}</b>
                        {/* the window column ends on gold's close; when this series carries a LATER row (a future-dated
                            weekend FX bar) the tile says so rather than quietly printing two weeks for one quantity */}
                        {d.window_note && <span style={{ color: T.amber }} data-driver-window-cut={d.window_to ?? ''} title={d.window_note}> (to {istLabel(d.window_to)})</span>} · </span>}
                      <span title={tip('d1')}>1d {fmtDelta(d, d.d1)}</span> · <span title={tip('d1w')}>7 d {fmtDelta(d, d.d1w)}</span> · <span title={tip('d1m')}>30 d {fmtDelta(d, d.d1m)}</span>
                      {d.pct_1y != null && <span title={tip('pct_1y')}> · percentile {num(d.pct_1y, 0)} (1 y)</span>}
                      {d.report_date && <span> · {istLabel(d.report_date)}</span>}
                      {instrument && <span style={{ color: T.muted }} data-driver-instrument={d.series_id ?? ''}> · {instrument}</span>}
                      {note && <span style={{ color: note.tone === 'amber' ? T.amber : T.dim }} data-driver-fallback={d.series_id ?? ''}> · {note.text}</span>}
                      {ryOff && <span style={{ color: T.amber }} data-driver-ry-mismatch> · {ryOff}</span>}
                      <br />
                      <span title={tip('corr_60d')}>ρ60d {signed(d.corr_60d, 2)}</span> ·{' '}
                      <span title={`${tip('driver_tag') ?? ''} rule: ${rule}`} data-driver-tag={tag} style={{ color: tag === 'neutral' ? T.dim : T.text, textTransform: 'uppercase', letterSpacing: .6 }}>{tag}</span>
                      <span style={{ color: T.dim }}> ({rule})</span>
                    </span>} />
                )
              })}
            </Grid>
            {m.drivers.length === 0 && <div style={{ color: T.dim, fontSize: 11 }}>no drivers stored yet (21:30 FRED job, 03:10 Treasury / Yahoo job)</div>}
            {/* what each column means, VISIBLE (F4: one of the two definitions lived in a hover tooltip only) */}
            {/* the definition only: each tile names its own window and its own date, which can differ when a series'
                last stored point does (the tile's `title` carries its words, the sub-line its report date) */}
            <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }} data-driver-columns>{windowColumnsCaption(props.window, winWords, winFrom, winTo)} · each tile&apos;s own window start and date are on the tile</div>
            <Attribution sources={driverSources(m.drivers)} />
          </>
        )}
      </GPanel>

      <Grid min={340}>
        {/* mc.kgx */}
        <GPanel id="mc.kgx" title="Gold or the dollar?" badge="arithmetic" evidence="identity" fresh={fb('gold')} dateOnly={goldDate} series={['KGX_PURE_GOLD_PCT', 'KGX_USD_EFFECT_PCT', 'KGX_INR_EFFECT_PCT']} catalog={catalog} layer={layer}
          formula="usd_effect = −Δln(DXY close) over gold's own window; pure = total − usd_effect; inr_effect = Δln(USD/INR)"
          copyB={<>"gold rose $20; $12 was the dollar falling, $8 was buying" — and for MCX, how much was the rupee. <Term t="KGX">What is KGX?</Term></>}
          copyP="the dollar leg is −Δln of the ICE DXY close (DX-Y.NYB, settled 17:00 New York like GC=F), on gold's own two dates — the same number HEALTH's verdict and DOLLAR tile print. The six Yahoo '=X' closes it used to sum are start-of-day prints about a session behind (8 Nov 2026 RCA: 0.09 same-day correlation with the DXY close, 0.84 with the previous day's). The basket itself (EUR 57.6 %, JPY 13.6 %, GBP 11.9 %, CAD 9.1 %, SEK 4.2 %, CHF 3.6 %) is replicable but Europe-heavy; Fed broad weights would add CNY/INR with a weekly lag (open question j.2 #11).">
          {m?.kgx ? <KgxBar period={m.kgx.period} total={m.kgx.total_pct} pure={m.kgx.pure_gold_pct} usdEffect={m.kgx.usd_effect_pct} inrEffect={m.kgx.inr_effect_pct} weights={m.kgx.weights} basketLabel={kgxWin?.basket_label} usdSource={kgxWin?.usd_source} usdAligned={kgxWin?.usd_aligned} note={kgxNote} tips={tip} />
            : <div style={{ color: T.dim, fontSize: 11 }}>KGX block pending (derived at 21:30)</div>}
          {m?.kgx?.from_date && <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }} data-gold-kgx-window>{kgxWindowCaption(kgxWin, healthFrom)}
            {/* when the dollar leg's own two dates are not gold's, the panel says so instead of letting the caption claim them */}
            {kgxWin?.usd_aligned === false && <span style={{ color: T.amber }} data-gold-kgx-usd-dates> · dollar leg {istLabel(kgxWin.usd_from_date)} → {istLabel(kgxWin.usd_to_date)}</span>}</div>}
          {rebasedSeries ? <div style={{ marginTop: 8 }}><LineChart series={rebasedSeries} height={120} dp={0} label="gold vs gold-in-basket, rebased" /></div>
            : <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>rebased 1-y line appears once COMEX_GC_FRONT and DXY_CLOSE have daily history{rebased.error ? ` (${rebased.error})` : ''}</div>}
        </GPanel>

        {/* mc.ccy */}
        <GPanel id="mc.ccy" title="Gold in six currencies" badge="arithmetic" evidence="identity" fresh={fb('gold')} dateOnly={goldDate} series={['GOLD_IN_EUR', 'GOLD_IN_JPY', 'GOLD_IN_GBP', 'GOLD_IN_CNY', 'GOLD_INR_LANDED']} catalog={catalog} pad={0} layer={layer}
          copyB="up in USD but down in EUR = it was the dollar."
          copyP="INR row = landed ₹/10 g before duty (M57); the duty-paid and MCX legs live on PHYSICAL, the trading desk is MCXG.">
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11, fontFamily: T.mono }} title={tip('gold_in_ccy')}>
            {/* the page's window is its own column, the trailing ones are named by their calendar days (C-DATA-04 / F4):
                the headers used to read 1D / 1W / 1M, where "1W" was a trailing 7 calendar days and "W" in the picker was
                week to date — two meanings, one of them hover-only */}
            {/* …and the window column is dropped altogether when it would repeat the 1D one — in the 'D' window the
                page's window IS the previous session, so both columns read −0.573 for USD (§f.6, round-2 checker) */}
            <thead><tr style={{ color: T.muted, fontSize: 10, textAlign: 'right' }}>
              <th style={{ textAlign: 'left', padding: '5px 10px' }}>CCY</th><th>PRICE</th><th title={tip('d1')}>1D</th>
              {showCcyWindow && <th title={ccyWin?.label ? `${windowTag(props.window)} = ${ccyWin.label}` : undefined}>{windowTag(props.window)}</th>}
              <th title={tip('d1w')}>7 D</th><th title={tip('d1m')}>30 D</th><th style={{ padding: '5px 10px' }}>YTD</th>
            </tr></thead>
            <tbody>
              {ccyRows.map(c => (
                <tr key={c.ccy} style={{ borderTop: `1px solid ${T.border}`, textAlign: 'right' }}>
                  <td style={{ textAlign: 'left', padding: '5px 10px', color: T.text }}>{c.ccy}{c.ccy === 'INR' && (
                    <span style={{ fontSize: 10 }}>
                      {' '}<span style={{ color: T.dim }}>landed ₹/10 g ·</span>
                      {' '}<span role="button" tabIndex={0} data-go="mcxgold" onClick={() => goToPage('mcxgold')} onKeyDown={e => { if (e.key === 'Enter') goToPage('mcxgold') }} style={{ color: T.cyan, cursor: 'pointer' }} title="MCX gold desk: session, quotes, contract selector, paper ticket">MCXG ›</span>
                      {' '}<span role="button" tabIndex={0} onClick={() => props.onNavigate('contracts')} onKeyDown={e => { if (e.key === 'Enter') props.onNavigate('contracts') }} style={{ color: T.cyan, cursor: 'pointer' }} title="GOLD › CONTRACTS: the MCX curve and the duty-paid leg">CONTRACTS ›</span>
                    </span>
                  )}</td>
                  <td style={{ color: T.bright }}>{CCY_SYM[c.ccy] ?? ''}{num(c.price, c.ccy === 'JPY' || c.ccy === 'INR' ? 0 : 1)}</td>
                  <td>{signedPct(c.d1)}</td>{showCcyWindow && <td data-ccy-window={c.ccy}>{signedPct(c.d_window)}</td>}<td>{signedPct(c.d1w)}</td><td>{signedPct(c.d1m)}</td><td style={{ padding: '5px 10px' }}>{signedPct(c.ytd)}</td>
                </tr>
              ))}
              {!ccyRows.length && <tr><td colSpan={showCcyWindow ? 7 : 6} style={{ padding: 10, color: T.dim }}>currency table pending</td></tr>}
            </tbody>
          </table>
          <div style={{ fontSize: 10, color: T.dim, padding: '4px 10px 8px' }} data-ccy-columns>
            {windowColumnsCaption(props.window, ccyWin?.label, ccyWin?.from_date, ccyWin?.to_date)}
            {ccyWin?.note ? ` · ${ccyWin.note}` : ''}
          </div>
        </GPanel>
      </Grid>

      <Grid min={340}>
        {/* mc.fed */}
        <GPanel id="mc.fed" title="Fed path" badge="context" evidence="Atlanta Fed MPT; FedWatch = link" fresh={fb('fed')} dateOnly={fedDate} series={['FED_PATH_ATL', 'FRED_EFFR']} catalog={catalog} layer={layer}
          copyB={<>what the market expects the <Term t="FOMC">Fed</Term> to do at each meeting; a cut lowers the cost of holding gold.</>}
          copyP="the full distribution comes from SOFR options (Atlanta Fed MPT, G16); ZQ = 100 − price (G17); the FOMC statement lands at 23:30 IST (00:30 after 1 Nov), after the MCX close.">
          {m?.fed ? (
            <>
              <div style={{ fontSize: 11, color: T.text, marginBottom: 6 }}>
                <span title={tip('effr')}>EFFR {pct(m.fed.effr, 2)}{m.fed.effr_date ? ` (${istLabel(m.fed.effr_date)})` : ''}</span> · <span title={tip('fed_target')}>target {m.fed.target ?? '—'}</span> · <span title={tip('next_fomc_ist')}>next FOMC {m.fed.next_fomc_ist ?? '—'}</span>
                {m.fed.after_mcx_close != null && <> · </>}{m.fed.after_mcx_close != null && <Chip color={m.fed.after_mcx_close ? T.amber : T.cyan} style={{ fontSize: 9, marginLeft: 6 }} title={tip('after_mcx_close')}>{m.fed.after_mcx_close ? 'AFTER MCX CLOSE · gap risk at 09:00' : 'IN SESSION'}</Chip>}
              </div>
              <div style={{ fontSize: 10, color: T.dim, marginBottom: 3 }} data-gold-fed-rows title={tip('fed_p_hike')}>rows: the Atlanta Fed tracker&apos;s horizons (IMM third-Wednesday windows), not FOMC decision dates — the next decision is the one named above</div>
              <div style={{ display: 'grid', gap: 4 }}>
                {m.fed.meetings.map(mt => (
                  <div key={mt.meeting} style={{ display: 'grid', gridTemplateColumns: '90px 1fr 60px 60px 110px', gap: 8, alignItems: 'center', fontSize: 11, fontFamily: T.mono }}>
                    <span style={{ color: T.text }} title="a tracker horizon (IMM window), not a meeting date">to {istLabel(mt.meeting)}</span>
                    <Meter value={(mt.p_cut ?? 0) / 100} color={T.violet} height={6} />
                    <span title={tip('fed_p_cut')} style={{ color: T.muted }}>cut {pct(mt.p_cut, 0)}</span>
                    <span title={tip('fed_p_hike')} style={{ color: T.muted }}>hike {pct(mt.p_hike, 0)}</span>
                    <span title={`${tip('fed_mean_bp') ?? ''} The expected average policy rate to the horizon: a level, not a move.`} style={{ color: T.muted }}>{fedMeanText(mt.mean_bp)}</span>
                  </div>
                ))}
                {m.fed.meetings.length === 0 && <div style={{ color: T.dim, fontSize: 11 }}>no meeting rows stored yet (06:40 Atlanta Fed job)</div>}
              </div>
              {m.fed.zq?.length ? <div style={{ fontSize: 10, color: T.muted, marginTop: 6 }} title={tip('zq_implied')} data-gold-zq>ZQ implied (100 − price): {m.fed.zq.map(z => `${zqLabel(z)} ${pct(z.implied_pct, 2)}${z.note ? ` (${z.note})` : ''}`).join(' · ')}</div> : null}
              <Attribution sources={['Atlanta Fed', 'FRED']} />
            </>
          ) : <div style={{ color: T.dim, fontSize: 11 }}>Fed path pending (06:40 job)</div>}
        </GPanel>

        {/* mc.move */}
        <GPanel id="mc.move" title="Expected move" badge="arithmetic" evidence="GVZ ÷ √252 × price × lot" fresh={fb('gold')} dateOnly={moveDate} series={['GVZ_SIGMA_DAY_PCT', 'ATR14_INR', 'GVZ_CLOSE']} catalog={catalog} layer={layer}
          copyB="how big a normal day is, in rupees per lot you trade: the unit for stops and sizing."
          copyP="implied from GVZ (GLD options, A6/G8) vs realised 20-d; ATR14 in ₹ from MCX bars; the ticket on MCXG prints max lots at 1 % risk from the same ATR.">
          {m?.move ? (
            <>
              <KV items={[
                [<span key="k" title={tip('gvz')}>GVZ</span>, `${num(m.move.gvz, 2)}${m.move.gvz_date ? ` · ${istLabel(m.move.gvz_date)}` : ''}`, T.text],
                [<span key="k" title={tip('sigma_day_pct')}>1σ day</span>, `${pct(m.move.sigma_day_pct, 2)} · ${usd(m.move.usd_oz, 1)}/oz · ${inr(m.move.inr_10g, 0)}/10 g`, T.text],
                [<span key="k" title={tip('realised_vol_20d')}>realised 20-d vol</span>, pct(m.move.realised_20d, 1), T.text],
                [<span key="k" title={tip('atr14_rupees')}>ATR14 ₹/10 g</span>, inr(m.move.atr14_inr, 0), T.text],
              ]} />
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 10, color: T.muted, marginBottom: 2 }} title={tip('move_per_lot')}>1σ day per lot (₹)</div>
                <KV cols={2} items={FAMILIES.map(fm => [
                  <span key={fm} style={{ color: fm === fam ? T.amber : undefined }}>{fm} ×{LOT_MULTIPLIER[fm]}</span>,
                  inr(m.move?.per_lot?.[fm] ?? sigmaPerLot(m.move?.sigma_day_pct, m.move?.inr_10g, fm), 0), fm === fam ? T.amber : T.text,
                ] as [ReactNode, ReactNode, string])} />
              </div>
            </>
          ) : <div style={{ color: T.dim, fontSize: 11 }}>expected-move block pending</div>}
        </GPanel>
      </Grid>

      {/* mc.calendar — a schedule: no lag chip; as of its first row */}
      <GPanel id="mc.calendar" title="US calendar this week (IST)" badge="arithmetic" evidence="schedule" dateOnly={calDate} series={['US_CALENDAR_FF', 'GOLD_EVENTS']} catalog={catalog} pad={0} layer={layer}
        copyB="when the known shocks hit, in IST; after the MCX close means the move shows up as a gap at 09:00."
        copyP="ForexFactory this-week JSON (G19) with consensus and previous; in-session = 18:00–23:30 IST; FOMC 23:30 (00:30 after 1 Nov); BLS / BEA schedules linked."
        right={<span style={{ display: 'flex', gap: 4 }}><a href="https://www.bls.gov/schedule/news_release/" target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}><Chip color={T.cyan} style={{ cursor: 'pointer' }}>BLS ↗</Chip></a><a href="https://www.bea.gov/news/schedule" target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}><Chip color={T.cyan} style={{ cursor: 'pointer' }}>BEA ↗</Chip></a></span>}>
        <DataTable columns={calCols} rows={calRows} rowKey={(r, i) => `${r.date ?? r.event_date}-${r.title ?? r.name}-${i}`} dense empty={<div style={{ padding: 10, color: T.dim, fontSize: 11 }}>no US releases stored for this week (hourly job 09:00–23:00)</div>} />
      </GPanel>

      <Grid min={340}>
        {/* mc.health */}
        <GPanel id="mc.health" title="Driver health" badge="context" evidence="G-MACRO H1" fresh={fb('drivers')} dateOnly={driversDate} series={['FRED_DFII10', 'DXY_CLOSE']} catalog={catalog} subtitle="rolling 1-y correlation of daily changes, by year" layer={layer}
          copyB="whether the usual drivers are still explaining gold this year."
          copyP="since 2022 the real-yield rule explains a third of what it used to (beta −5.0 vs −9.9); the dollar never stopped working (beta ≈ −1 in every regime).">
          {m?.driver_health?.rolling_corr?.length ? (
            <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
              <div><div style={{ fontSize: 10, color: T.muted }} title={tip('rolling_corr')}>vs real yield (10-y)</div><SmallMultiple values={m.driver_health.rolling_corr.map(r => ({ x: r.year, y: r.real_yield }))} width={220} label="corr vs real yield" /></div>
              <div><div style={{ fontSize: 10, color: T.muted }} title={tip('rolling_corr')}>vs DXY</div><SmallMultiple values={m.driver_health.rolling_corr.map(r => ({ x: r.year, y: r.dxy }))} width={220} label="corr vs DXY" /></div>
            </div>
          ) : <div style={{ color: T.dim, fontSize: 11 }}>rolling correlations pending (weekly)</div>}
          {m?.driver_health?.betas_by_regime?.length ? (
            <div style={{ marginTop: 8 }} title={tip('beta_regime')}>
              {/* betas with their units: $/oz per 100 bp of real yield; % of gold per 1 % of DXY (C-DATA-21) */}
              {m.driver_health.betas_by_regime.map((b, i) => <Field key={i} label={String(b.regime ?? b.period ?? i)} value={<span data-beta-row>{Object.entries(b).filter(([k]) => k !== 'regime' && k !== 'period').map(([k, v]) => betaText(k, v)).join(' · ')}</span>} />)}
            </div>
          ) : null}
          {m?.driver_health?.lesson && <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>{m.driver_health.lesson}</div>}
        </GPanel>

        {/* mc.context — collapsed */}
        <GPanel id="mc.context" title="Context" badge="context" evidence="G-MACRO H4: no prediction" fresh={fb('drivers')} dateOnly={ctxDate} series={['GSR', 'GPR_RATIO', 'GPR_MONTHLY', 'FRED_HY_OAS', 'FRED_M2SL']} catalog={catalog} layer={layer}
          copyB="ratios and risk gauges that frame the regime; none of them times anything."
          copyP="gold/silver and gold/platinum with percentiles; GPR (Caldara–Iacoviello) daily / monthly percentile; HY OAS; gold ÷ M2 percentile since 1975; the scatter is a picture, not a model (M63 DO-NOT-PUBLISH).">
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 11, color: T.cyan }}>gold/silver, gold/platinum, GPR, HY OAS, gold/M2, the real-yield scatter</summary>
            <div style={{ marginTop: 8 }}>
              <KV items={[
                [<span key="k" title={tip('gsr')}>gold / silver</span>, `${num(m?.context?.gsr, 1)}${m?.context?.gsr_pct != null ? ` · percentile ${num(m.context.gsr_pct, 0)}` : ''}`, contextTone],
                [<span key="k" title={tip('gpr_pct')}>GPR percentile (monthly · daily)</span>, `${num(m?.context?.gpr_pct_m, 0)} · ${num(m?.context?.gpr_pct_d, 0)}`, contextTone],
                [<span key="k" title={tip('hy_oas')}>HY OAS</span>, `${pct(m?.context?.hy_oas, 2)}${m?.context?.hy_oas_date ? ` · ${istLabel(m.context.hy_oas_date)}` : ''}`, contextTone],
                [<span key="k" title={tip('gold_m2_pct')}>gold / M2 percentile</span>, num(m?.context?.gold_m2_pct, 0), contextTone],
              ]} />
              <ScatterRY data={scatter.data} error={scatter.error} />
            </div>
          </details>
        </GPanel>
      </Grid>
    </div>
  )
}

/** Gold vs 10-y real yield, 5 y of monthly points — a scatter, not a model (M63 is DO-NOT-PUBLISH). */
function ScatterRY({ data, error }: { data: GoldSeries | null; error: string | null }) {
  const gc = data?.series.find(s => s.series_id === 'COMEX_GC_FRONT')?.points ?? []
  const ry = new Map((data?.series.find(s => s.series_id === 'FRED_DFII10')?.points ?? []).map(p => [p.report_date.slice(0, 7), p.value]))
  const pts = gc.slice(-60).map(p => ({ x: ry.get(p.report_date.slice(0, 7)) ?? null, y: p.value, d: p.report_date })).filter(p => p.x != null) as { x: number; y: number; d: string }[]
  if (pts.length < 6) return <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>scatter appears with 5 y of monthly COMEX_GC_FRONT and FRED_DFII10{error ? ` (${error})` : ''}</div>
  const W = 320, H = 150, L = 40, B = 20
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y)
  const lo = Math.min(...xs), hi = Math.max(...xs), ylo = Math.min(...ys), yhi = Math.max(...ys)
  const X = (v: number) => L + ((v - lo) / (hi - lo || 1)) * (W - L - 8)
  const Y = (v: number) => 8 + (H - B - 8) - ((v - ylo) / (yhi - ylo || 1)) * (H - B - 8)
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontSize: 10, color: T.muted }}>gold ($/oz) vs 10-y real yield (%), monthly, last {pts.length} months — the level link broke in 2022</div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="gold vs real yield scatter">
        {pts.map((p, i) => <circle key={p.d} cx={X(p.x)} cy={Y(p.y)} r={2.5} fill={i >= pts.length - 12 ? T.amber : T.violet} opacity={0.8}><title>{`${p.d}: ${p.x.toFixed(2)} % → $${Math.round(p.y)}`}</title></circle>)}
        <text x={L} y={H - 4} fontSize={9} fontFamily={T.mono} fill={T.dim}>{lo.toFixed(1)} %</text>
        <text x={W - 8} y={H - 4} textAnchor="end" fontSize={9} fontFamily={T.mono} fill={T.dim}>{hi.toFixed(1)} %</text>
        <text x={2} y={12} fontSize={9} fontFamily={T.mono} fill={T.dim}>${Math.round(yhi)}</text>
        <text x={2} y={H - B} fontSize={9} fontFamily={T.mono} fill={T.dim}>${Math.round(ylo)}</text>
      </svg>
      <div style={{ fontSize: 10, color: T.dim }}>amber = last 12 months</div>
    </div>
  )
}

export default MacroView
