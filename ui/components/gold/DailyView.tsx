'use client'

/**
 * DAILY — the Kitco chart, done our way (PLAN a.3): the matched COMEX month over the Globex day on one 24-h axis
 * (d.24h) with the previous day as a dotted overlay, the last settlement as a dashed line, hi/lo, a two-row time
 * axis (IST over NY), session bands (Sydney/Tokyo · Shanghai · London · New York), the MCX bar under the axis and the
 * hatched CME maintenance hour; three days overlaid (d.3day); the SGE Au99.99 line on the Shanghai band when stored
 * (d.sge); yesterday's OI × price read for COMEX and MCX (d.quadrant); the last twelve 5-minute bars (d.tape).
 *
 * Data: /api/gold/bars (1-minute bars from gold_bars_intraday; the live last from ui-api's SWR cache — the view never
 * calls Yahoo), /api/gold/positioning/daily. Everything inline SVG in CSS px (useChartSize, axisTicks); the chart's
 * axis and bar arithmetic (dayGroups, resample5m, DST bands) is lib/gold/sessions.ts, unit-tested under node by
 * ui/components/__tests__/gold.check.ts. Arithmetic badge on the chart, context on the rest.
 */
import { useMemo, useState } from 'react'
import { CHART_BOX, Chip, DataTable, T, fmtFixed, fmtSigned, useChartSize, type Column } from '@/components/terminal'
import { axisTicks, textWidth } from '@/components/terminal/chart'
import { getGoldBars, getGoldPositioningDaily } from '@/lib/gold/api'
import { UNIT_LABEL, comexCode, comexMonthLabel, convertUsdOz, dayLabel, fmtCount, fmtInUnit, fmtSignedPctSp, istClock, pctChange, unitDp } from '@/lib/gold/format'
import { istDateISO } from '@/lib/format'
import { axisPos, axisTicksIst, barMs, dailyOhlc, dayGroups, fmtHM, globexOpenIst, istMinutes, istToNy, legendCloses, prevSessionClose, resample5m, sessionBands, shiftDays,
         ukDstActive, usDstActive, type Band, type DayPt } from '@/lib/gold/sessions'
import type { Bar, GoldBars, GoldSubViewProps, Unit } from '@/lib/gold/types'
import { OiQuadrantTape } from './OiQuadrantTape'
import { LinkTile, Term } from './ViewBits'
import { GoldPanel, NoVerdict, Pending, useGoldLoad } from './kit'

const BARS_MS = 60_000
/** the only COMEX symbol with stored 1-minute bars (gold_bars_intraday: GC=F, INR=X, SGE_AU9999) */
const BARS_SYMBOL = 'GC=F'
const BAND_FILL: Record<Band['key'], string> = { sydney: '#1a2130', shanghai: '#2a1f3f', london: '#13303a', newyork: '#3a2a12', mcx: '#5a3f00', maintenance: 'transparent' }

type Pt = DayPt

function Hatch() {
  return (
    <defs>
      <pattern id="gold-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="6" stroke={T.borderHi} strokeWidth="1" />
      </pattern>
    </defs>
  )
}

/** The 24-h chart (d.24h) and the 3-day overlay (d.3day) share this renderer. */
function IntradayChart({ groups, usDst, ukDst, unit, usdinr, settle, settleLabel, showPrev, showBands, mode, live, sge }: {
  groups: { date: string; pts: Pt[] }[]; usDst: boolean; ukDst: boolean; unit: Unit; usdinr: number | null
  settle: number | null; settleLabel: string; showPrev: boolean; showBands: boolean; mode: '24h' | '3day'
  live: { price: number; as_of: string } | null; sge: Pt[] | null
}) {
  const { ref, w, h } = useChartSize(1100, 300, { minRatio: 0.85, maxRatio: 1.2 })
  const padL = 62, padR = 70, padT = 10, padB = 46
  const plotW = Math.max(100, w - padL - padR), plotH = Math.max(80, h - padT - padB)
  const conv = (v: number) => convertUsdOz(v, unit, usdinr) ?? v
  const days = mode === '24h' ? groups.slice(-2) : groups.slice(-3)
  const today = days[days.length - 1]
  const prev = mode === '24h' ? days[0] !== today ? days[0] : null : null
  const series = mode === '24h' ? [{ d: today, color: T.amber, dotted: false }, ...(showPrev && prev ? [{ d: prev, color: T.muted, dotted: true }] : [])]
    : days.map((d, i) => ({ d, color: [T.violet, T.cyan, T.amber][i + (3 - days.length)], dotted: false }))
  const vals: number[] = []
  for (const s of series) for (const p of s.d.pts) vals.push(conv(p.c))
  if (settle != null) vals.push(conv(settle))
  if (live) vals.push(conv(live.price))
  if (sge) for (const p of sge) vals.push(conv(p.c))
  const lo0 = vals.length ? Math.min(...vals) : 0, hi0 = vals.length ? Math.max(...vals) : 1
  const padY = Math.max((hi0 - lo0) * 0.08, hi0 * 0.0005)
  const lo = lo0 - padY, hi = hi0 + padY
  const yAxis = axisTicks(lo, hi, plotH, 28)
  const y = (v: number) => padT + plotH - ((v - lo) / (hi - lo || 1)) * plotH
  const x = (pos: number) => padL + (pos / 1440) * plotW
  const path = (pts: Pt[]) => pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.pos).toFixed(1)},${y(conv(p.c)).toFixed(1)}`).join(' ')
  const bands = showBands ? sessionBands({ usDst, ukDst }) : []
  const open = globexOpenIst(usDst)
  const xt = axisTicksIst(usDst, plotW > 700 ? 120 : 180)
  const dp = unitDp(unit)
  const last = today?.pts[today.pts.length - 1]
  const hiToday = today ? Math.max(...today.pts.map(p => p.h)) : null
  const loToday = today ? Math.min(...today.pts.map(p => p.l)) : null
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={mode === '24h' ? '24-hour gold chart' : 'three days overlaid'}>
        <Hatch />
        {/* session bands (behind) */}
        {bands.filter(b => b.key !== 'mcx').map((b, i) => {
          const p0 = axisPos(b.start, usDst), p1 = b.end >= 1440 ? 1440 - (open % 1440) : axisPos(b.end, usDst)
          const segs = p1 > p0 ? [[p0, p1]] : [[p0, 1440], [0, p1]]
          return segs.map(([a, z], k) => (
            <rect key={`${b.key}-${i}-${k}`} x={x(a)} y={padT} width={Math.max(0, x(z) - x(a))} height={plotH}
              fill={b.key === 'maintenance' ? 'url(#gold-hatch)' : BAND_FILL[b.key]} opacity={b.key === 'maintenance' ? 0.6 : 0.35}>
              <title>{b.name} · {fmtHM(b.start)}–{fmtHM(b.end)} IST</title>
            </rect>
          ))
        })}
        {/* y grid + labels (one unit per axis) */}
        {yAxis.ticks.map(t => (
          <g key={t}>
            <line x1={padL} x2={padL + plotW} y1={y(t)} y2={y(t)} stroke={T.border} strokeDasharray="2 4" />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={9.5} fill={T.muted} fontFamily={T.mono}>{fmtFixed(t, yAxis.dp)}</text>
          </g>
        ))}
        <text x={padL - 6} y={padT - 1} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{UNIT_LABEL[unit]}</text>
        {/* settle line */}
        {settle != null && (
          <g>
            <line x1={padL} x2={padL + plotW} y1={y(conv(settle))} y2={y(conv(settle))} stroke={T.cyan} strokeDasharray="6 4" strokeWidth={1} />
            <text x={padL + plotW - 4} y={y(conv(settle)) - 4} textAnchor="end" fontSize={9} fill={T.cyan} fontFamily={T.mono}>{settleLabel} {fmtFixed(conv(settle), dp)}</text>
          </g>
        )}
        {/* SGE overlay */}
        {sge && sge.length > 1 && <path d={path(sge)} fill="none" stroke={T.violet} strokeWidth={1} strokeDasharray="2 3" opacity={0.9} />}
        {/* series */}
        {series.map(s => s.d.pts.length > 1 && (
          <path key={s.d.date} d={path(s.d.pts)} fill="none" stroke={s.color} strokeWidth={s.dotted ? 1 : 1.5} strokeDasharray={s.dotted ? '2 3' : undefined} />
        ))}
        {/* live last */}
        {mode === '24h' && last && (
          <g>
            <circle cx={x(last.pos)} cy={y(conv(live?.price ?? last.c))} r={3} fill={T.amber} />
            <text x={Math.min(x(last.pos) + 6, padL + plotW - textWidth('0,000.00', 9.5))} y={y(conv(live?.price ?? last.c)) - 6} fontSize={9.5} fill={T.amber} fontFamily={T.mono}>
              {fmtFixed(conv(live?.price ?? last.c), dp)}
            </text>
          </g>
        )}
        {/* x axis: IST over NY */}
        <line x1={padL} x2={padL + plotW} y1={padT + plotH} y2={padT + plotH} stroke={T.borderHi} />
        {xt.map(t => (
          <g key={t.pos}>
            <line x1={x(t.pos)} x2={x(t.pos)} y1={padT + plotH} y2={padT + plotH + 3} stroke={T.borderHi} />
            <text x={x(t.pos)} y={padT + plotH + 13} textAnchor="middle" fontSize={9.5} fill={T.text} fontFamily={T.mono}>{fmtHM(t.ist)}</text>
            <text x={x(t.pos)} y={padT + plotH + 24} textAnchor="middle" fontSize={9} fill={T.dim} fontFamily={T.mono}>{fmtHM(istToNy(t.ist, usDst))}</text>
          </g>
        ))}
        <text x={padL - 6} y={padT + plotH + 13} textAnchor="end" fontSize={9} fill={T.muted} fontFamily={T.mono}>IST</text>
        <text x={padL - 6} y={padT + plotH + 24} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>NY</text>
        {/* MCX bar under the axis */}
        {showBands && bands.filter(b => b.key === 'mcx').map((b, i) => {
          const p0 = axisPos(b.start, usDst), p1 = axisPos(b.end, usDst)
          const segs = p1 > p0 ? [[p0, p1]] : [[p0, 1440], [0, p1]]
          return segs.map(([a, z], k) => (
            <g key={`mcx-${i}-${k}`}>
              <rect x={x(a)} y={padT + plotH + 30} width={Math.max(0, x(z) - x(a))} height={6} fill={BAND_FILL.mcx} />
              {k === 0 && <text x={x(a) + 3} y={padT + plotH + 44} fontSize={9} fill={T.amber} fontFamily={T.mono}>MCX {fmtHM(b.start)}–{fmtHM(b.end)} IST</text>}
            </g>
          ))
        })}
        {/* hi / lo markers (24h) */}
        {mode === '24h' && hiToday != null && loToday != null && (
          <g fontSize={9} fontFamily={T.mono} fill={T.dim}>
            <text x={padL + plotW + 4} y={y(conv(hiToday)) + 3}>hi {fmtFixed(conv(hiToday), dp)}</text>
            <text x={padL + plotW + 4} y={y(conv(loToday)) + 3}>lo {fmtFixed(conv(loToday), dp)}</text>
          </g>
        )}
      </svg>
    </div>
  )
}

/**
 * The legend under the 24-h chart (C-TRADER-2 / C-DATA-1): finished sessions at their STORED DAILY CLOSE (gold_daily_bars;
 * a Yahoo daily close, not an exchange settlement), today at the live last, each Δ vs the stored close of the session
 * before. Never the last minute of an IST bucket.
 */
function legendRows(groups: { date: string; pts: Pt[] }[], daily: ReturnType<typeof dailyOhlc>, live: { price: number } | null, unit: Unit, usdinr: number | null): string[] {
  const dp = unitDp(unit)
  const conv = (v: number) => fmtFixed(convertUsdOz(v, unit, usdinr) ?? v, dp)
  return legendCloses(groups, daily, live, 3).map(r => {
    if (r.px == null) return `${dayLabel(r.date)} ${r.kind} —`
    const chg = r.prevClose != null ? r.px - r.prevClose : null
    const pct = pctChange(r.prevClose, r.px)
    const what = r.kind === 'last' ? 'last' : r.bucketFallback ? 'last stored minute (no daily bar yet)' : 'close (Yahoo daily, not settlement)'
    return `${dayLabel(r.date)} ${what} ${conv(r.px)}${chg != null ? ` ${chg >= 0 ? '▲' : '▼'}${fmtFixed(Math.abs(chg), dp)} (${fmtSignedPctSp(pct, 2)} vs the previous stored close)` : ' (previous close not stored)'}`
  })
}

export function DailyView({ sel, unit, layer, comexMatched, usdinr, tooltips, catalog }: GoldSubViewProps) {
  const symbol = comexMatched ?? 'GC=F'
  // 1-minute bars are stored for GC=F (and INR=X) only — the 5-minute job fetches the front contract, never the matched
  // month (ingest_yahoo.fetch_intraday); the matched month names the panel and prices `live` (desk cache), the chart is GC=F.
  const bars = useGoldLoad(() => getGoldBars(BARS_SYMBOL, '1m'), [], BARS_MS)
  // the stored DAILY closes of the last sessions: the legend's closes and the dashed reference line come from here
  // (gold_daily_bars, keyed by trade date), never from the end of an IST minute bucket (C-TRADER-2 / C-TRADER-17)
  const today = istDateISO()
  const dailyBars = useGoldLoad(() => getGoldBars(BARS_SYMBOL, '1d', { from: shiftDays(today, -14) }), [today], 15 * 60_000)
  // SGE quotes are written at '1m' (ingest_physical g_sge_quotes); resample5m coarsens on the client when wanted
  const sge = useGoldLoad(() => getGoldBars('SGE_AU9999', '1m'), [], 300_000)
  const quadComex = useGoldLoad(() => getGoldPositioningDaily('COMEX', 20), [], 900_000)
  const quadMcx = useGoldLoad(() => getGoldPositioningDaily('MCX', 20, sel.family), [sel.family], 900_000)   // the picked family (API_CONTRACT §2.6)
  const [showPrev, setShowPrev] = useState(true)
  const [showBands, setShowBands] = useState(true)
  const [res, setRes] = useState<'1m' | '5m'>('1m')

  const data: GoldBars | null = bars.data
  const nowMs = useMemo(() => {
    const last = data?.bars?.[data.bars.length - 1]
    return last ? barMs(last.ts) : Date.now()
  }, [data])
  const usDst = usDstActive(nowMs), ukDst = ukDstActive(nowMs)
  const src = useMemo(() => (res === '5m' ? resample5m(data?.bars ?? []) : (data?.bars ?? [])), [data, res])
  const groups = useMemo(() => dayGroups(src, usDst), [src, usDst])
  const prevGroup = useMemo(() => (data?.prev_day?.length ? dayGroups(data.prev_day.map(p => ({ ts: p.ts, o: p.c, h: p.c, l: p.c, c: p.c })), usDst) : null), [data, usDst])
  const groups24 = useMemo(() => {
    if (!prevGroup?.length || groups.length < 1) return groups
    const today = groups[groups.length - 1]
    const prev = prevGroup[prevGroup.length - 1]
    return prev.date === today.date ? groups : [prev, today]
  }, [groups, prevGroup])
  const sgePts = useMemo(() => (sge.data?.bars?.length ? dayGroups(sge.data.bars, usDst).slice(-1)[0]?.pts ?? null : null), [sge.data, usDst])
  const daily = useMemo(() => dailyOhlc(dailyBars.data?.bars ?? []), [dailyBars.data])
  const todayDate = groups[groups.length - 1]?.date ?? null
  // the dashed line is the PREVIOUS session's stored daily close, labelled with its date and source; the server's
  // settle_line is drawn only when it is a bulletin settlement (quality 'settlement'), never today's last trade
  const serverSettle = data?.settle_line && /settle/i.test(data.settle_line.quality ?? '') && !/last.?trade/i.test(data.settle_line.quality ?? '') ? data.settle_line : null
  const prevClose = useMemo(() => prevSessionClose(daily, todayDate), [daily, todayDate])
  const settle = serverSettle?.value ?? prevClose?.c ?? null
  const settleLabel = serverSettle ? serverSettle.label : prevClose ? `${dayLabel(prevClose.date)} close (Yahoo daily, not settlement)` : ''
  const live = data?.last ? { price: data.last.price, as_of: data.last.as_of } : null
  const tape = useMemo(() => resample5m(data?.bars ?? []).slice(-12).reverse(), [data])
  const dp = unitDp(unit)
  const conv = (v: number | null | undefined) => (v == null ? null : convertUsdOz(v, unit, usdinr))
  const tapeCols: Column<Bar>[] = [
    { key: 'ts', label: 'IST · NY', render: b => { const m = istMinutes(barMs(b.ts)); return <span style={{ fontFamily: T.mono }}>{fmtHM(m)} <span style={{ color: T.dim }}>{fmtHM(istToNy(m, usDst))}</span></span> } },
    { key: 'c', label: `last ${UNIT_LABEL[unit]}`, align: 'right', render: b => <span style={{ color: T.bright }}>{fmtFixed(conv(b.c), dp)}</span> },
    { key: 'd', label: 'Δ', align: 'right', render: b => { const d = b.c != null && b.o != null ? (conv(b.c) ?? 0) - (conv(b.o) ?? 0) : null; return <span style={{ color: d == null ? T.muted : d > 0 ? T.green : d < 0 ? T.red : T.muted }}>{fmtSigned(d, dp)}</span> } },
    { key: 'r', label: 'range', align: 'right', render: b => <span style={{ color: T.muted }}>{b.h != null && b.l != null ? fmtFixed((conv(b.h) ?? 0) - (conv(b.l) ?? 0), dp) : '—'}</span> },
    { key: 'v', label: 'volume (contracts)', align: 'right', render: b => <span style={{ color: T.muted }}>{fmtCount(b.v)}</span> },
  ]
  const legend = legendRows(groups, daily, live, unit, usdinr)
  const chartBadge = 'arithmetic'
  const dayCount = groups.length

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <GoldPanel id="d.24h" title={`24 hours · COMEX ${comexMonthLabel(symbol)}`} badge={chartBadge} layer={layer} accent={T.amber}
        catalog={catalog} series={['BARS_1M', 'COMEX_GC_FRONT']}
        subtitle={<>{res} line · {comexCode(symbol)}{data?.instrument ? ` · ${data.instrument}` : ''}{live ? ` · live ${fmtInUnit(live.price, unit, usdinr)} ${istClock(live.as_of)}` : ''}</>}
        freshness={data ? (data.freshness ?? { state: live ? 'delayed' : 'stale', source: 'gold_bars_intraday', as_of: live?.as_of ?? null }) : null}
        catalogRow={catalog.COMEX_GC_FRONT ?? null}
        copyB={<>When in the day the move happened and which centre was trading. The dotted line is yesterday on the same clock; the dashed line is the previous session&apos;s close (a Yahoo daily close, not an exchange settlement — see <Term t="settlement by session" />). The legend&apos;s closes are the stored daily bars; today is &apos;last&apos;.</>}
        copyP="GC=F rolls before first notice (the roll, see CONTRACTS); the dashed line is the bulletin settlement when C7 is allowed, else the previous session's stored Yahoo daily close labelled as such. Bar timestamps are UTC instants placed on the IST clock. Axis = the Globex day (18:00 ET → 17:00 ET); bands from lib/gold/sessions.ts, DST-aware."
        right={<>
          <Chip color={T.amber} active={res === '1m'} onClick={() => setRes('1m')}>1m</Chip>
          <Chip color={T.amber} active={res === '5m'} onClick={() => setRes('5m')}>5m</Chip>
          <Chip color={T.muted} active={showPrev} onClick={() => setShowPrev(v => !v)} title="previous day as a dotted overlay">prev day</Chip>
          <Chip color={T.muted} active={showBands} onClick={() => setShowBands(v => !v)} title="Sydney/Tokyo · Shanghai · London · New York · MCX">sessions</Chip>
        </>}>
        <Pending s={bars} label="intraday bars">
          {dayCount === 0 && <NoVerdict what="no 1-minute bars stored yet — the 5-minute job fills gold_bars_intraday from the day it starts" />}
          {dayCount > 0 && <>
            <IntradayChart groups={groups24} usDst={usDst} ukDst={ukDst} unit={unit} usdinr={usdinr} settle={settle} settleLabel={settleLabel}
              showPrev={showPrev} showBands={showBands} mode="24h" live={live} sge={sgePts} />
            <div data-gold-legend style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 14px', fontFamily: T.mono, fontSize: 10.5, color: T.muted, marginTop: 4 }}>
              {legend.map(l => <span key={l}>{l}</span>)}
              {showBands && <span style={{ color: T.dim }}>bands: Sydney/Tokyo · Shanghai (SGE) · London · New York · hatched = CME maintenance 17:00–18:00 ET</span>}
            </div>
          </>}
        </Pending>
      </GoldPanel>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(440px, 1fr))', alignItems: 'start' }}>
        <GoldPanel id="d.3day" title="3 days overlaid" subtitle="one 24-h IST axis, one colour each" badge="context" layer={layer} accent={T.cyan}
          catalog={catalog} series={['BARS_1M']}
          freshness={data ? (data.freshness ?? { state: 'delayed', source: 'gold_bars_intraday' }) : null}
          copyB="Today's path against the last two days, hour by hour: does the move repeat at the same time of day?"
          copyP="Three CME trade days on the Globex-day axis; no inference is drawn from the overlay (context).">
          <Pending s={bars} label="intraday bars">
            {dayCount < 2 ? <NoVerdict what={`${dayCount} day${dayCount === 1 ? '' : 's'} stored; three are needed`} />
              : <IntradayChart groups={groups} usDst={usDst} ukDst={ukDst} unit={unit} usdinr={usdinr} settle={null} settleLabel="" showPrev={false}
                  showBands={showBands} mode="3day" live={null} sge={null} />}
            <div style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, marginTop: 4 }}>
              {groups.slice(-3).map((g, i, a) => <span key={g.date} style={{ marginRight: 12, color: [T.violet, T.cyan, T.amber][i + (3 - a.length)] }}>■ {dayLabel(g.date)}</span>)}
            </div>
          </Pending>
        </GoldPanel>

        <GoldPanel id="d.sge" title="Shanghai (SGE Au99.99)" subtitle="delayed intraday · drawn on the Shanghai band" badge="context" layer={layer} accent={T.violet}
          freshness={sge.data ? (sge.data.freshness ?? { state: 'delayed', source: 'SGE delayed quotes' }) : { state: 'unavailable', reason: sge.error ?? 'not stored yet' }}
          catalog={catalog} series={['SGE_DAILY']}
          copyB="Does Shanghai lead or lag the COMEX print? The violet dotted line on the 24-h chart is SGE during its hours."
          copyP="SGE delayed quotations (D4), CNY/g converted to $/oz by the server; displayed with attribution (O-1), never re-served.">
          {sgePts && sgePts.length > 1
            ? <div style={{ fontSize: 11, color: T.text }}>{sgePts.length} bars today · last {fmtInUnit(sgePts[sgePts.length - 1].c, unit, usdinr)} — overlaid above in violet. <span style={{ color: T.dim }}>Source: Shanghai Gold Exchange (sge.com.cn), displayed with attribution.</span></div>
            : <div data-gold-sge-empty style={{ display: 'grid', gap: 6 }}>
                {/* not a verdict question (the series is PUBLISH-CONTEXT): the bars are not stored yet, so the page links the source instead (C-TRADER-26) */}
                <div style={{ fontSize: 11, color: T.muted }}>No SGE bars stored for today yet — the asia job writes them during SGE hours (06:30–13:00 and 17:30–00:00 IST).</div>
                <LinkTile name="SGE delayed quotes" url="https://en.sge.com.cn/data_DelayedQuotes" what="Au99.99 / Au(T+D), delayed" why="the publisher's own page; nothing is fetched by the terminal from here" />
              </div>}
        </GoldPanel>
      </div>

      <GoldPanel id="d.quadrant" title="Yesterday's OI × price read" subtitle={`COMEX product OI (T+1) · MCX ${sel.family} OI (07:35)`} badge="context" evidence="folklore until G-STUDY-2" layer={layer} accent={T.muted}
        catalog={catalog} series={['CME_VOI', 'MCX_CURVE_ICICI']}
        freshness={quadComex.data ? (quadComex.data.freshness ?? { state: 'delayed', source: 'CME FTP daily_volume', reason: quadComex.data.since ? `since ${quadComex.data.since}` : null }) : null}
        copyB={<>Did the move come with new positions (<Term t="open interest" /> up) or closing ones (OI down)? The four <Term t="OI quadrants" />: long build-up / short build-up / short covering / long unwinding. A day with no OI yet says so — it is not &apos;flat&apos;; a Δ that spans missed sessions is labelled with its span.</>}
        copyP="Product OI, all months summed; roll weeks are mechanical (greyed); 'who' needs the weekly COT. The weekly version scored 1 of 12 cells (G-STUDY); the daily version is untested (G-STUDY-2). CME OI lands T+1 ≈ 15:30 IST.">
        <div style={{ display: 'grid', gap: 14 }}>
          <div>
            <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1, color: T.muted, marginBottom: 4 }}>COMEX GC · product OI</div>
            <Pending s={quadComex} label="COMEX OI">
              <OiQuadrantTape tape={quadComex.data?.quadrant_tape ?? []} days={20} tips={k => tooltips[k]} />
            </Pending>
          </div>
          <div>
            <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1, color: T.muted, marginBottom: 4 }}>MCX {quadMcx.data?.family ?? sel.family} · OI (lots){quadMcx.data?.since ? ` · since ${quadMcx.data.since}` : ''}</div>
            <Pending s={quadMcx} label="MCX OI">
              <OiQuadrantTape tape={quadMcx.data?.quadrant_tape ?? []} days={20} tips={k => tooltips[k]} />
            </Pending>
          </div>
        </div>
      </GoldPanel>

      <GoldPanel id="d.tape" title="Intraday tape" subtitle="last 12 × 5-minute bars" badge="arithmetic" layer={layer} accent={T.border} pad={0}
        catalog={catalog} series={['BARS_1M']}
        freshness={data ? (data.freshness ?? { state: 'delayed', source: 'gold_bars_intraday' }) : null}
        copyB="The last hour, bar by bar." copyP="5-minute buckets of the stored 1-minute bars (open = first, close = last, range = high − low).">
        <DataTable columns={tapeCols} rows={tape} rowKey={b => String(b.ts)} dense empty="No bars stored yet." exportName="gold-intraday-tape" />
      </GoldPanel>
    </div>
  )
}

export default DailyView
