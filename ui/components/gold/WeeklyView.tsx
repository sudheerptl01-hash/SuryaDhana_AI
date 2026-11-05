'use client'

/**
 * WEEKLY — this week in context (PLAN a.4): 60 sessions of daily candles for the COMEX front (GC) with the MCX settle
 * on the right axis, 20/50-day lines and volume, Mondays shaded (w.candles); the Mon ▸ Fri audit table with one unit per
 * column — $/oz for COMEX, lots for MCX OI, ₹/10 g for IBJA, tonnes for GLD — and a CSV export (w.table); a 26-week heat
 * grid of daily Δ % with the week total (w.grid); and the weekly "who did what" strip, the one-line echo of
 * POSITIONING's hero (w.whodid; allowed by PLAN a.4 as the same data rendered once per view).
 *
 * Data: /api/gold/bars (interval 1d, the stored COMEX_GC_FRONT daily bars), /api/gold/positioning/daily (COMEX product
 * OI Δ; MCX OI Δ and the proxy settle per session), /api/gold/series (IBJA 999 PM, GLD tonnes), /api/gold/cot (latest).
 * Candles are the vendored lightweight-charts (dynamic import, one lazy chunk); the grid is a CSS grid; price changes may
 * wear green/red (PLAN §f.3), everything else is the neutral token. Arithmetic on the candles and the table, context on the
 * grid and the COT strip. Nothing here feeds a trade.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { IChartApi } from 'lightweight-charts'
import { Chip, DataTable, T, fmtFixed, fmtSigned, type Column } from '@/components/terminal'
import { getGoldBars, getGoldCot, getGoldFlows, getGoldPositioningDaily, getGoldSeries } from '@/lib/gold/api'
import { NO_VERDICT, dayLabel, fmtCount, fmtInr0, fmtSignedCount, fmtSignedPctSp, fmtUsd, parseIso, publishGate } from '@/lib/gold/format'
import { istDateISO } from '@/lib/format'
import { dailyChanges, dailyOhlc, istDate, shiftDays, sma, weekRows, weekdayIndex, type Ohlc } from '@/lib/gold/sessions'
import type { DailyPositioningRow, GoldCot, GoldSubViewProps } from '@/lib/gold/types'
import { Term } from './ViewBits'
import { GoldPanel, NoVerdict, Pending, useGoldLoad } from './kit'

/** `/bars` takes Yahoo symbols as data-service stores them (API_CONTRACT §2.4): the continuous front, labelled GC1. */
const DAILY_SYMBOL = 'GC=F'
const BARS_MS = 15 * 60_000
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

export interface LinePts { date: string; value: number }

/**
 * Candles via the vendored lightweight-charts: left axis = the candles and their moving averages, right axis = an
 * optional overlay in another unit (the MCX settle in ₹/10 g), volume below, Mondays shaded through a full-height
 * histogram on a hidden scale. Rebuilt when the data changes; the chart follows the box width.
 */
export function LwCandles({ candles, lines = [], overlay, log = false, height = 320, mondays = true, volume = true, dp = 1, overlayLabel }: {
  candles: Ohlc[]; lines?: { color: string; values: (number | null)[]; dotted?: boolean }[]; overlay?: LinePts[] | null
  log?: boolean; height?: number; mondays?: boolean; volume?: boolean; dp?: number; overlayLabel?: string
}) {
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let disposed = false
    let chart: IChartApi | null = null
    let ro: ResizeObserver | null = null
    void (async () => {
      const lw = await import('lightweight-charts')
      const el = box.current
      if (disposed || !el || candles.length === 0) return
      chart = lw.createChart(el, {
        width: el.clientWidth, height,
        layout: { background: { type: lw.ColorType.Solid, color: 'transparent' }, textColor: T.muted, fontFamily: T.mono, fontSize: 10 },
        grid: { vertLines: { visible: false }, horzLines: { color: T.border } },
        crosshair: { mode: lw.CrosshairMode.Magnet },
        timeScale: { borderColor: T.borderHi, timeVisible: false, secondsVisible: false },
        leftPriceScale: { visible: true, borderColor: T.borderHi, mode: log ? lw.PriceScaleMode.Logarithmic : lw.PriceScaleMode.Normal, scaleMargins: { top: 0.06, bottom: volume ? 0.22 : 0.06 } },
        rightPriceScale: { visible: !!overlay?.length, borderColor: T.borderHi, scaleMargins: { top: 0.06, bottom: volume ? 0.22 : 0.06 } },
        handleScale: { axisPressedMouseMove: true }, handleScroll: true,
      })
      const c = chart.addCandlestickSeries({
        priceScaleId: 'left', upColor: T.green, downColor: T.red, borderVisible: false, wickUpColor: T.green, wickDownColor: T.red,
        priceLineColor: T.dim, priceFormat: { type: 'price', precision: dp, minMove: 10 ** -dp },
      })
      c.setData(candles.map(k => ({ time: k.date, open: k.o, high: k.h, low: k.l, close: k.c })))
      for (const l of lines) {
        const s = chart.addLineSeries({ priceScaleId: 'left', color: l.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
                                        ...(l.dotted ? { lineStyle: lw.LineStyle.Dotted } : {}) })
        s.setData(candles.map((k, i) => ({ time: k.date, value: l.values[i] })).filter((p): p is { time: string; value: number } => p.value != null && Number.isFinite(p.value)))
      }
      if (overlay?.length) {
        const o = chart.addLineSeries({ priceScaleId: 'right', color: T.amber, lineWidth: 1, lineStyle: lw.LineStyle.Dashed, priceLineVisible: false, title: overlayLabel ?? '',
                                        priceFormat: { type: 'price', precision: 0, minMove: 1 } })
        o.setData(overlay.map(p => ({ time: p.date, value: p.value })))
      }
      if (volume) {
        const v = chart.addHistogramSeries({ priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false, color: `${T.muted}66` })
        v.setData(candles.map(k => ({ time: k.date, value: k.v, color: k.c >= k.o ? `${T.green}55` : `${T.red}55` })))
        chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 }, visible: false })
      }
      if (mondays) {
        const m = chart.addHistogramSeries({ priceScaleId: 'mon', color: 'rgba(255,255,255,0.045)', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false })
        m.setData(candles.filter(k => weekdayIndex(k.date) === 0).map(k => ({ time: k.date, value: 1 })))
        chart.priceScale('mon').applyOptions({ scaleMargins: { top: 0, bottom: 0 }, visible: false })
      }
      chart.timeScale().fitContent()
      if (typeof ResizeObserver !== 'undefined') {
        ro = new ResizeObserver(() => { if (chart && el.clientWidth > 0) chart.applyOptions({ width: el.clientWidth }) })
        ro.observe(el)
      }
    })()
    return () => { disposed = true; ro?.disconnect(); chart?.remove(); chart = null }
  }, [candles, lines, overlay, log, height, mondays, volume, dp, overlayLabel])
  return <div ref={box} data-gold-candles style={{ width: '100%', minWidth: 0, height }} />
}

/** The MCX proxy settle per session for a family: the highest-OI contract of each trade date. */
export function mcxFrontSettle(rows: readonly DailyPositioningRow[] | null | undefined, family: string): LinePts[] {
  const best = new Map<string, DailyPositioningRow>()
  for (const r of rows ?? []) {
    if (r.settle_or_close == null) continue
    const sym = (r.symbol_or_product ?? '').toUpperCase()
    if (sym !== family.toUpperCase()) continue
    const cur = best.get(r.trade_date)
    if (!cur || (r.open_interest ?? -1) > (cur.open_interest ?? -1)) best.set(r.trade_date, r)
  }
  return [...best.values()].sort((a, b) => a.trade_date.localeCompare(b.trade_date)).map(r => ({ date: r.trade_date, value: r.settle_or_close as number }))
}

/** Daily OI change per trade date, all products / contracts of an exchange summed (the "which positions got closed" column). */
export function oiChangeByDate(rows: readonly DailyPositioningRow[] | null | undefined, family?: string): Map<string, number> {
  const out = new Map<string, number>()
  for (const r of rows ?? []) {
    if (r.oi_change == null) continue
    if (family && (r.symbol_or_product ?? '').toUpperCase() !== family.toUpperCase()) continue
    out.set(r.trade_date, (out.get(r.trade_date) ?? 0) + r.oi_change)
  }
  return out
}

/**
 * The weekly "who did what" line (w.whodid): the same words POSITIONING's hero prints, once. Contracts in Western
 * grouping (C-TRADER-20); the release is the server's IST label (`release_ist`) — the naive `release_at` is UTC and its
 * date part is the ET day, not the IST one (C-DATA-6).
 */
export function whoDidLine(c: GoldCot | null | undefined): string {
  if (!c || !c.latest || c.ok === false) return 'COT · not stored yet'   // the documented empty-store shape (API_CONTRACT §2.5): `latest: null`
  const mm = (c.groups ?? []).find(g => g.key === 'mm')
  const parts = ['COT']
  if (mm?.net != null) parts.push(`funds (MM) net ${fmtSignedCount(mm.net)}${mm.chg_net != null ? ` (${fmtSignedCount(mm.chg_net)} w/w)` : ''}`)
  if (mm?.who_did?.length) parts.push(mm.who_did.join(', '))
  if (c.driver_label) parts.push(`driver: ${c.driver_label}`)
  if (c.open_interest?.total != null) parts.push(`OI ${fmtCount(c.open_interest.total)}${c.open_interest.chg != null ? ` (${fmtSignedCount(c.open_interest.chg)})` : ''}`)
  parts.push(`as of ${dayLabel(c.latest.report_date) || c.latest.report_date}`)
  const released = c.latest.release_ist ?? (() => { const d = parseIso(c.latest.release_at); return d ? `${dayLabel(istDate(d))} IST` : null })()
  if (released) parts.push(`released ${released}`)
  // `next_release_ist` is a label ("Sat 07 Nov 01:00 IST"); an ISO instant in its place is formatted, never printed raw
  if (c.latest.next_release_ist) parts.push(`next ${/^\d{4}-\d{2}-\d{2}T/.test(c.latest.next_release_ist) ? istStamp(c.latest.next_release_ist) : c.latest.next_release_ist}`)
  return parts.join(' · ')
}

/** 'Sat 07 Nov 01:00 IST' for an ISO instant (zone-less = UTC through parseIso); the raw string when unparsable. */
export function istStamp(iso: string): string {
  const d = parseIso(iso)
  if (!d) return iso
  return `${dayLabel(istDate(d))} ${d.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })} IST`
}

/** The IST date of a COT release instant (the Friday 15:30 ET release is Saturday in IST). */
export function releaseIstDate(releaseAt: string | null | undefined): string | null {
  const d = parseIso(releaseAt)
  return d ? istDate(d) : null
}

interface WeekTableRow { date: string; day: string; k: Ohlc | null; chg: number | null; comexOi: number | null; mcxOi: number | null; ibja: number | null; gld: number | null; cot: string | null }

export function WeeklyView({ sel, layer, tooltips, catalog, onNavigate }: GoldSubViewProps) {
  const today = istDateISO()
  const bars = useGoldLoad(() => getGoldBars(DAILY_SYMBOL, '1d', { from: shiftDays(today, -230) }), [today], BARS_MS)
  const comex = useGoldLoad(() => getGoldPositioningDaily('COMEX', 90), [], BARS_MS)
  const mcx = useGoldLoad(() => getGoldPositioningDaily('MCX', 90, sel.family), [sel.family], BARS_MS)   // THAT family's rows (API_CONTRACT §2.6)
  const series = useGoldLoad(() => getGoldSeries(['IBJA_999_PM', 'GLD_TONNES'], { freq: 'D', from: shiftDays(today, -70) }), [today], BARS_MS)
  // GLD tonnes also live in gold_etf_holdings (/flows etf[].cumulative_30d): the fallback when /series serves no
  // GLD_TONNES points (C-TRADER-25 / C-DATA-3), joined on report_date like the series
  const flows = useGoldLoad(() => getGoldFlows(1), [], BARS_MS)
  const cot = useGoldLoad(() => getGoldCot({ weeks: 8 }), [], BARS_MS)
  const [showMcx, setShowMcx] = useState(true)
  const [weekBack, setWeekBack] = useState(0)

  const daily = useMemo(() => dailyOhlc(bars.data?.bars ?? []), [bars.data])
  const last60 = useMemo(() => daily.slice(-60), [daily])
  const smaLines = useMemo(() => {
    const closes = daily.map(k => k.c)
    const n = daily.length, off = Math.max(0, n - 60)
    return [{ color: T.cyan, values: sma(closes, 20).slice(off) }, { color: T.amber, values: sma(closes, 50).slice(off) }]
  }, [daily])
  const settle = useMemo(() => (showMcx ? mcxFrontSettle(mcx.data?.rows, sel.family).filter(p => last60.length && p.date >= last60[0].date) : null), [mcx.data, sel.family, showMcx, last60])
  const changes = useMemo(() => dailyChanges(daily), [daily])
  const comexOi = useMemo(() => oiChangeByDate(comex.data?.rows), [comex.data])
  const mcxOi = useMemo(() => oiChangeByDate(mcx.data?.rows, sel.family), [mcx.data, sel.family])
  const ibja = useMemo(() => new Map((series.data?.series.find(s => s.series_id === 'IBJA_999_PM')?.points ?? []).map(p => [p.report_date, p.value])), [series.data])
  const gld = useMemo(() => {
    const fromSeries = series.data?.series.find(s => s.series_id === 'GLD_TONNES')?.points ?? []
    const fromFlows = (flows.data?.etf ?? []).find(r => r.fund === 'GLD')?.cumulative_30d ?? []
    const pts = fromSeries.length ? fromSeries : fromFlows.filter(p => p.tonnes != null).map(p => ({ report_date: p.report_date, value: p.tonnes as number }))
    const out = new Map<string, number>()
    for (let i = 1; i < pts.length; i++) out.set(pts[i].report_date, pts[i].value - pts[i - 1].value)
    return out
  }, [series.data, flows.data])
  const weeks = useMemo(() => weekRows(daily, 27), [daily])
  const week = weeks.length ? weeks[Math.max(0, weeks.length - 1 - weekBack)] : null
  const cotLatest = cot.data?.latest ?? null   // null until the Saturday COT job has stored a report (§2.5)
  // the COT cell sits on the IST day of the release (Saturday 01:00/02:00 IST → the Friday row is the ET day: use the IST date minus nothing — the row is the trade date the report was released into)
  const cotRelease = releaseIstDate(cotLatest?.release_at) ?? cotLatest?.release_at?.slice(0, 10) ?? null
  const cotCell = cot.data ? whoDidLine(cot.data).split(' · ').slice(1, 3).join(' · ') : null
  const tableRows: WeekTableRow[] = week ? week.days.map((k, i) => {
    const date = shiftDays(week.monday, i)
    // a Saturday IST release lands on the Friday row (the last session of that week)
    const cotHere = cotRelease != null && (cotRelease === date || (i === 4 && cotRelease === shiftDays(date, 1)))
    return { date, day: DAY_NAMES[i], k, chg: changes.get(date) ?? null, comexOi: comexOi.get(date) ?? null, mcxOi: mcxOi.get(date) ?? null,
             ibja: ibja.get(date) ?? null, gld: gld.get(date) ?? null, cot: cotHere ? cotCell : null }
  }) : []
  // a daily volume identical to the previous session's is a stale partial-day value, not a coincidence (C-TRADER-25 / C-DATA-20)
  const dupVolume = (r: WeekTableRow): boolean => {
    if (!r.k?.v) return false
    const i = daily.findIndex(k => k.date === r.k!.date)
    return i > 0 && daily[i - 1].v === r.k.v
  }
  const tip = (k: string) => tooltips[k]
  // optional columns pass the §f.2 gate on their own series: a series without a PUBLISH verdict hides its column
  const colOk = (id: string) => publishGate(catalog, id) !== 'no-verdict'
  const gated = (id: string, cell: ReactNode) => (colOk(id) ? cell : <span style={{ color: T.dim }} title={`${NO_VERDICT} (${id})`}>—</span>)
  const cols: Column<WeekTableRow>[] = [
    { key: 'day', label: 'Day', render: r => <span style={{ color: r.k ? T.text : T.dim }}>{r.day} <span style={{ color: T.dim }}>{r.date.slice(5)}</span></span> },
    { key: 'o', label: 'open $/oz', align: 'right', render: r => fmtFixed(r.k?.o, 1) },
    { key: 'h', label: 'high $/oz', align: 'right', render: r => fmtFixed(r.k?.h, 1) },
    { key: 'l', label: 'low $/oz', align: 'right', render: r => fmtFixed(r.k?.l, 1) },
    { key: 'c', label: 'close $/oz', align: 'right', render: r => <span style={{ color: T.bright }}>{fmtFixed(r.k?.c, 1)}</span> },
    { key: 'chg', label: 'Δ %', align: 'right', sort: r => r.chg, render: r => <span style={{ color: r.chg == null ? T.dim : r.chg > 0 ? T.green : r.chg < 0 ? T.red : T.muted }}>{fmtSignedPctSp(r.chg, 2)}</span> },
    { key: 'range', label: 'range %', align: 'right', render: r => (r.k && r.k.c ? `${fmtFixed(((r.k.h - r.k.l) / r.k.c) * 100, 2)} %` : '—') },
    { key: 'v', label: 'COMEX vol', align: 'right', render: r => (r.k?.v ? <span style={{ color: dupVolume(r) ? T.dim : T.text }} title={dupVolume(r) ? 'identical to the previous session: a stale partial-day Yahoo value, re-fetched by the 03:10 job' : undefined}>{fmtCount(r.k.v)}{dupVolume(r) ? ' ?' : ''}</span> : '—') },
    { key: 'comexOi', label: 'COMEX OI Δ', align: 'right', title: tip('oi_change'), render: r => gated('CME_VOI', <span style={{ color: T.muted }}>{fmtSignedCount(r.comexOi)}</span>) },
    { key: 'mcxOi', label: `MCX ${sel.family} OI Δ lots`, align: 'right', title: tip('mcx_oi_by_expiry'), render: r => gated('MCX_CURVE_ICICI', <span style={{ color: T.muted }}>{fmtSignedCount(r.mcxOi)}</span>) },
    { key: 'ibja', label: 'IBJA 999 PM ₹/10 g', align: 'right', title: tip('ibja_999'), render: r => gated('IBJA_999_PM', <>{fmtInr0(r.ibja)}</>) },
    { key: 'gld', label: 'GLD Δ t', align: 'right', title: tip('etf_chg_1d'), render: r => gated('GLD_TONNES', <span style={{ color: T.muted }}>{fmtSigned(r.gld, 2)}</span>) },
    { key: 'cot', label: 'COT (Fri release)', render: r => gated('COT_DISAGG_F', <span style={{ color: T.muted, whiteSpace: 'normal' }}>{r.cot ?? '—'}</span>) },
  ]
  const n = daily.length
  const grid = useMemo(() => weeks.slice(-26), [weeks])
  const maxAbs = useMemo(() => Math.max(0.5, ...grid.flatMap(w => w.days.map(d => Math.abs((d && changes.get(d.date)) ?? 0)))), [grid, changes])
  const shade = (v: number | null) => {
    if (v == null) return 'transparent'
    const a = Math.min(1, Math.abs(v) / maxAbs)
    return v > 0 ? `rgba(22,217,138,${(0.12 + a * 0.55).toFixed(2)})` : v < 0 ? `rgba(255,77,94,${(0.12 + a * 0.55).toFixed(2)})` : 'transparent'
  }

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {/* w.candles */}
      <GoldPanel id="w.candles" title="60 sessions · COMEX GC front" badge="arithmetic" layer={layer} accent={T.amber} pad={8}
        subtitle={<>daily candles $/oz · 20 d <span style={{ color: T.cyan }}>cyan</span> · 50 d <span style={{ color: T.amber }}>amber</span>{showMcx ? <> · MCX {sel.family} settle ₹/10 g dashed, right axis (PROXY)</> : null} · Mondays shaded</>}
        freshness={bars.data ? (bars.data.freshness ?? { state: 'delayed', source: 'gold_daily_bars', as_of: daily[n - 1]?.date ?? null }) : null}
        reportDate={daily[n - 1]?.date ?? null} catalog={catalog} series={['COMEX_GC_FRONT', 'MCX_CURVE_ICICI']}
        copyB="This week against the last twelve: candles are the COMEX front future in dollars, the dashed line is what MCX settled at in rupees."
        copyP="Yahoo GC=F continuous front (rolls before first notice) stored daily; 20/50-day simple averages; the MCX line is the ICICI band-midpoint settlement of the highest-OI contract, labelled PROXY until official bhavcopy rows exist (O-8)."
        right={<Chip color={T.amber} active={showMcx} onClick={() => setShowMcx(v => !v)} title="MCX proxy settle on the right axis">MCX ₹</Chip>}>
        <Pending s={bars} label="daily bars">
          {last60.length < 2 ? <NoVerdict what="daily bars are stored from the day the overnight job starts (gold_daily_bars)" />
            : <LwCandles candles={last60} lines={smaLines} overlay={settle} dp={1} overlayLabel={`MCX ${sel.family} ₹/10 g`} height={320} />}
        </Pending>
      </GoldPanel>

      {/* w.table */}
      <GoldPanel id="w.table" title="This week · Mon ▸ Fri" badge="arithmetic" layer={layer} accent={T.cyan} pad={0} catalog={catalog} series={['COMEX_GC_FRONT']}
        subtitle={week ? `week of ${dayLabel(week.monday)}${week.total_pct != null ? ` · week ${fmtSignedPctSp(week.total_pct, 2)}` : ''}` : 'no week stored yet'}
        freshness={bars.data ? (bars.data.freshness ?? { state: 'delayed', source: 'gold_daily_bars' }) : null}
        copyB={<>One row per session, one unit per column: dollars for COMEX, lots for MCX open interest, rupees for the <Term t="IBJA rate" />, tonnes for <Term t="GLD" />. The CSV button on hover exports it.</>}
        copyP="OI Δ columns are exchange product OI (COMEX T+1 from the CME FTP file; MCX from the 07:35 ICICI master), all months summed — an MCX Δ that spans missed sessions is the server's multi-session delta; the COT cell appears on the Friday row of the IST release (Saturday 01:00/02:00 IST). A volume marked '?' repeats the previous session's (stale partial-day value)."
        right={<>
          <Chip color={T.muted} onClick={() => setWeekBack(b => Math.min(weeks.length - 1, b + 1))} title="previous week">‹</Chip>
          <Chip color={T.muted} onClick={() => setWeekBack(b => Math.max(0, b - 1))} title="next week">›</Chip>
        </>}>
        <Pending s={bars} label="daily bars">
          <DataTable columns={cols} rows={tableRows} rowKey={r => r.date} dense exportName="gold-week" empty="No sessions stored for this week yet." />
        </Pending>
      </GoldPanel>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', alignItems: 'start' }}>
        {/* w.grid */}
        <GoldPanel id="w.grid" title="26 weeks · daily Δ %" badge="context" layer={layer} accent={T.violet} catalog={catalog} series={['COMEX_GC_FRONT']}
          freshness={bars.data ? (bars.data.freshness ?? { state: 'delayed', source: 'gold_daily_bars' }) : null}
          copyB="Each row is a week, Monday to Friday, with the week's total on the right. Green and red are price changes, nothing else."
          copyP="Close-to-close changes of the stored COMEX front daily bars; the week total is the Friday close against the close before the week; context only (no seasonality claim is made here).">
          <Pending s={bars} label="daily bars">
            {grid.length === 0 ? <NoVerdict what="needs stored daily bars" /> : (
              <div data-gold-weekgrid style={{ display: 'grid', gridTemplateColumns: '78px repeat(5, minmax(0, 1fr)) 64px', gap: 2, fontFamily: T.mono, fontSize: 10 }}>
                <span />
                {DAY_NAMES.map(d => <span key={d} style={{ color: T.dim, textAlign: 'center' }}>{d}</span>)}
                <span style={{ color: T.dim, textAlign: 'right' }}>week</span>
                {grid.map(w => (
                  <WeekLine key={w.week} w={w} changes={changes} shade={shade} />
                ))}
              </div>
            )}
          </Pending>
        </GoldPanel>

        {/* w.whodid */}
        <GoldPanel id="w.whodid" title="Who did what this week" badge="context" evidence="G-STUDY 26 Oct 2026: explains the week — does not forecast" layer={layer} accent={T.muted}
          catalog={catalog} series={['COT_DISAGG_F']}
          freshness={cot.data ? (cot.data.freshness ?? (cotLatest ? { state: cotLatest.stale ? 'stale' : 'delayed', source: 'CFTC', as_of: cotLatest.release_at ?? null } : { state: 'unavailable', source: 'CFTC', reason: 'not stored yet' })) : null}
          reportDate={cotLatest?.report_date ?? null}
          copyB={<>The funds&apos; (<Term t="managed money" />) net bet from the weekly <Term t="COT" /> report and what they did this week, in one line; the full decomposition is on POSITIONING. The driver word is the bigger of the two moves; when price fell and the net still rose, funds bought the dip.</>}
          copyP="Managed-money net = long − short (spreads excluded), Tuesday positions released Friday 15:30 ET (Saturday IST); the words follow SOURCES.md M14 (closed longs / covered shorts / added …); contracts in Western grouping."
          right={<Chip color={T.amber} onClick={() => onNavigate('positioning')} title="the weekly who-is-long / who-is-short view">POSITIONING ›</Chip>}>
          <Pending s={cot} label="the COT report">
            <div data-gold-whodid style={{ fontFamily: T.mono, fontSize: 11, color: T.text, lineHeight: 1.6 }}>{whoDidLine(cot.data)}</div>
            {cot.data?.crowd?.label && <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{cot.data.crowd.label}</div>}
          </Pending>
        </GoldPanel>
      </div>
    </div>
  )
}

function WeekLine({ w, changes, shade }: { w: ReturnType<typeof weekRows>[number]; changes: Map<string, number | null>; shade: (v: number | null) => string }) {
  return (
    <>
      <span style={{ color: T.muted, alignSelf: 'center' }}>{dayLabel(w.monday).slice(4)}</span>
      {w.days.map((d, i) => {
        const v = d ? (changes.get(d.date) ?? null) : null
        return (
          <span key={i} title={d ? `${dayLabel(d.date)} · close ${fmtUsd(d.c, 1)} · ${fmtSignedPctSp(v, 2)}` : 'no session'}
            style={{ background: shade(v), color: v == null ? T.dim : T.bright, textAlign: 'center', padding: '3px 0', border: `1px solid ${T.border}` }}>
            {v == null ? '·' : fmtSigned(v, 1)}
          </span>
        )
      })}
      <span style={{ textAlign: 'right', alignSelf: 'center', color: w.total_pct == null ? T.dim : w.total_pct > 0 ? T.green : w.total_pct < 0 ? T.red : T.muted }}>{fmtSignedPctSp(w.total_pct, 1)}</span>
    </>
  )
}

export default WeeklyView
