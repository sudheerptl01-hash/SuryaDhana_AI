'use client'

/**
 * Inline-SVG chart kit for the gold sub-views (no new chart library, PLAN a.1): px-sized via `useChartSize`
 * (C1-trader-ux-17: one SVG unit = one CSS px, round ticks from `axisTicks`), one y-axis per chart (never dual-axis).
 *
 *  - `LineChart`: one or more series on a date axis, optional horizontal bands (20/80) and reference lines;
 *  - `BarChart`: signed bars (flows, Δ) with a zero line;
 *  - `StackedBars`: stacked signed bars by category (net by trader group, ETF flows by region, balance sheet);
 *  - `Gauge`: a 0–100 bar with a marker (the crowd gauge; neutral colour, worded "not a signal" by the caller);
 *  - `SmallMultiple`: a tiny bar strip (rolling correlations by year).
 *
 * Colours: context series use the neutral palette (muted / violet / cyan); green/red are passed explicitly only for
 * price changes and the arithmetic comparisons (PLAN §f.3).
 */
import { type ReactNode } from 'react'
import { CHART_BOX, T, useChartSize } from '@/components/terminal'
import { axisTicks, pickAxisLabels } from '@/components/terminal/chart'
import { MINUS } from './goldViewModel'

export interface XY { x: string; y: number | null }
export interface Series { key: string; label: string; color?: string; values: XY[]; dashed?: boolean; width?: number }

const PAD = { l: 48, r: 10, t: 10, b: 22 }
const fmtTick = (v: number, dp: number) => (v < 0 ? MINUS : '') + Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
const shortDate = (iso: string) => {
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00+05:30` : iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', year: '2-digit' })
}

export const SERIES_COLORS = [T.violet, T.cyan, T.amber, T.muted, T.bright, '#7fb3ff', '#ff9c6b']

/** Shared frame: axis ticks, x labels, hover column. */
function Frame({ w, h, xs, lo, hi, children, bands, refs, dp, label, fmtY }: {
  w: number; h: number; xs: string[]; lo: number; hi: number; children: ReactNode; bands?: [number, number][]; refs?: { y: number; label: string }[]
  dp?: number; label?: string; fmtY?: (v: number) => string
}) {
  const plotW = w - PAD.l - PAD.r, plotH = h - PAD.t - PAD.b
  const span = hi - lo || 1
  const y = (v: number) => PAD.t + plotH - ((v - lo) / span) * plotH
  const x = (i: number) => PAD.l + (xs.length > 1 ? (i / (xs.length - 1)) * plotW : plotW / 2)
  const ticks = axisTicks(lo, hi, plotH, 26)
  const labelIdx = pickAxisLabels(xs.length, plotW / Math.max(1, xs.length - 1), 64, [0, xs.length - 1])
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label} style={{ display: 'block' }}>
      {bands?.map(([a, b], i) => <rect key={i} x={PAD.l} y={Math.min(y(a), y(b))} width={plotW} height={Math.abs(y(a) - y(b))} fill={T.borderHi} opacity={0.25} />)}
      {ticks.ticks.map(t => (
        <g key={t}>
          <line x1={PAD.l} x2={w - PAD.r} y1={y(t)} y2={y(t)} stroke={T.border} strokeDasharray="2 3" />
          <text x={PAD.l - 4} y={y(t) + 3} textAnchor="end" fontSize={9} fontFamily={T.mono} fill={T.dim}>{fmtY ? fmtY(t) : fmtTick(t, dp ?? ticks.dp)}</text>
        </g>
      ))}
      {refs?.map(r => (
        <g key={r.label}>
          <line x1={PAD.l} x2={w - PAD.r} y1={y(r.y)} y2={y(r.y)} stroke={T.amber} strokeDasharray="4 3" opacity={0.8} />
          <text x={w - PAD.r} y={y(r.y) - 3} textAnchor="end" fontSize={9} fontFamily={T.mono} fill={T.amber}>{r.label}</text>
        </g>
      ))}
      {labelIdx.map(i => <text key={i} x={x(i)} y={h - 6} textAnchor={i === 0 ? 'start' : i === xs.length - 1 ? 'end' : 'middle'} fontSize={9} fontFamily={T.mono} fill={T.dim}>{shortDate(xs[i])}</text>)}
      {children}
    </svg>
  )
}

function extent(vals: (number | null | undefined)[], includeZero = false): [number, number] {
  const v = vals.filter((x): x is number => typeof x === 'number' && Number.isFinite(x))
  if (!v.length) return [0, 1]
  let lo = Math.min(...v), hi = Math.max(...v)
  if (includeZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0) }
  if (lo === hi) { lo -= 1; hi += 1 }
  const pad = (hi - lo) * 0.06
  return [lo - pad, hi + pad]
}

export function LineChart({ series, height = 150, bands, refs, dp, label, fmtY, legend = true, baseW = 640 }: {
  series: Series[]; height?: number; bands?: [number, number][]; refs?: { y: number; label: string }[]; dp?: number; label?: string
  fmtY?: (v: number) => string; legend?: boolean; baseW?: number
}) {
  const { ref, w, h } = useChartSize(baseW, height, { minRatio: 0.9, maxRatio: 1.1 })
  const xs = series[0]?.values.map(v => v.x) ?? []
  const [lo, hi] = extent(series.flatMap(s => s.values.map(v => v.y)))
  const plotW = w - PAD.l - PAD.r, plotH = h - PAD.t - PAD.b
  const y = (v: number) => PAD.t + plotH - ((v - lo) / (hi - lo || 1)) * plotH
  const x = (i: number) => PAD.l + (xs.length > 1 ? (i / (xs.length - 1)) * plotW : plotW / 2)
  if (!xs.length) return <div style={{ color: T.dim, fontSize: 11, padding: 8 }}>no history yet</div>
  return (
    <div ref={ref} style={CHART_BOX}>
      {legend && <div style={{ display: 'flex', gap: 12, fontSize: 9.5, color: T.muted, marginBottom: 2, flexWrap: 'wrap' }}>
        {series.map((s, i) => <span key={s.key}><span style={{ display: 'inline-block', width: 10, height: 2, background: s.color ?? SERIES_COLORS[i % SERIES_COLORS.length], verticalAlign: 'middle', marginRight: 4 }} />{s.label}</span>)}
      </div>}
      <Frame w={w} h={h} xs={xs} lo={lo} hi={hi} bands={bands} refs={refs} dp={dp} label={label} fmtY={fmtY}>
        {series.map((s, i) => {
          const d = s.values.map((v, j) => (v.y == null || !Number.isFinite(v.y) ? null : `${x(j)},${y(v.y)}`))
          let path = '', pen = false
          for (const p of d) { if (p == null) { pen = false; continue } path += `${pen ? 'L' : 'M'}${p} `; pen = true }
          return <path key={s.key} d={path} fill="none" stroke={s.color ?? SERIES_COLORS[i % SERIES_COLORS.length]} strokeWidth={s.width ?? 1.4} strokeDasharray={s.dashed ? '3 3' : undefined} />
        })}
      </Frame>
    </div>
  )
}

export function BarChart({ values, height = 110, color, posColor, negColor, dp, label, baseW = 640, fmtY }: {
  values: XY[]; height?: number; color?: string; posColor?: string; negColor?: string; dp?: number; label?: string; baseW?: number; fmtY?: (v: number) => string
}) {
  const { ref, w, h } = useChartSize(baseW, height, { minRatio: 0.9, maxRatio: 1.1 })
  const xs = values.map(v => v.x)
  const [lo, hi] = extent(values.map(v => v.y), true)
  const plotW = w - PAD.l - PAD.r, plotH = h - PAD.t - PAD.b
  const y = (v: number) => PAD.t + plotH - ((v - lo) / (hi - lo || 1)) * plotH
  const bw = Math.max(1, (plotW / Math.max(1, xs.length)) * 0.7)
  const x = (i: number) => PAD.l + (i + 0.5) * (plotW / Math.max(1, xs.length)) - bw / 2
  if (!xs.length) return <div style={{ color: T.dim, fontSize: 11, padding: 8 }}>no history yet</div>
  return (
    <div ref={ref} style={CHART_BOX}>
      <Frame w={w} h={h} xs={xs} lo={lo} hi={hi} dp={dp} label={label} fmtY={fmtY} refs={[{ y: 0, label: '' }]}>
        {values.map((v, i) => v.y == null ? null : (
          <rect key={v.x} x={x(i)} y={Math.min(y(v.y), y(0))} width={bw} height={Math.max(0.5, Math.abs(y(v.y) - y(0)))}
            fill={color ?? (v.y >= 0 ? (posColor ?? T.violet) : (negColor ?? T.muted))} opacity={0.9}>
            <title>{`${shortDate(v.x)}: ${fmtTick(v.y, dp ?? 0)}`}</title>
          </rect>
        ))}
      </Frame>
    </div>
  )
}

export interface StackRow { x: string; parts: Record<string, number | null | undefined> }

/** Stacked signed bars: positives stack up from zero, negatives stack down; one colour per key. */
export function StackedBars({ rows, keys, colors, height = 160, dp, label, baseW = 640, fmtY, legend = true }: {
  rows: StackRow[]; keys: { key: string; label: string }[]; colors?: Record<string, string>; height?: number; dp?: number; label?: string; baseW?: number
  fmtY?: (v: number) => string; legend?: boolean
}) {
  const { ref, w, h } = useChartSize(baseW, height, { minRatio: 0.9, maxRatio: 1.1 })
  const xs = rows.map(r => r.x)
  const tops = rows.map(r => keys.reduce((a, k) => a + Math.max(0, r.parts[k.key] ?? 0), 0))
  const bots = rows.map(r => keys.reduce((a, k) => a + Math.min(0, r.parts[k.key] ?? 0), 0))
  const [lo, hi] = extent([...tops, ...bots], true)
  const plotW = w - PAD.l - PAD.r, plotH = h - PAD.t - PAD.b
  const y = (v: number) => PAD.t + plotH - ((v - lo) / (hi - lo || 1)) * plotH
  const pitch = plotW / Math.max(1, xs.length)
  const bw = Math.max(1, pitch * 0.72)
  const colorOf = (k: string, i: number) => colors?.[k] ?? SERIES_COLORS[i % SERIES_COLORS.length]
  if (!xs.length) return <div style={{ color: T.dim, fontSize: 11, padding: 8 }}>no history yet</div>
  return (
    <div ref={ref} style={CHART_BOX}>
      {legend && <div style={{ display: 'flex', gap: 12, fontSize: 9.5, color: T.muted, marginBottom: 2, flexWrap: 'wrap' }}>
        {keys.map((k, i) => <span key={k.key}><span style={{ display: 'inline-block', width: 8, height: 8, background: colorOf(k.key, i), verticalAlign: 'middle', marginRight: 4 }} />{k.label}</span>)}
      </div>}
      <Frame w={w} h={h} xs={xs} lo={lo} hi={hi} dp={dp} label={label} fmtY={fmtY} refs={[{ y: 0, label: '' }]}>
        {rows.map((r, i) => {
          let up = 0, down = 0
          return keys.map((k, ki) => {
            const v = r.parts[k.key]
            if (v == null || !Number.isFinite(v) || v === 0) return null
            const from = v > 0 ? up : down
            const to = from + v
            if (v > 0) up = to; else down = to
            return <rect key={k.key} x={PAD.l + i * pitch + (pitch - bw) / 2} y={Math.min(y(from), y(to))} width={bw} height={Math.max(0.5, Math.abs(y(to) - y(from)))} fill={colorOf(k.key, ki)} opacity={0.9}>
              <title>{`${shortDate(r.x)} · ${k.label}: ${fmtTick(v, dp ?? 0)}`}</title></rect>
          })
        })}
      </Frame>
    </div>
  )
}

/** 0–100 gauge with a marker; neutral colour. The caller words it ("crowdedness, not a signal"). */
export function Gauge({ value, lo = 0, hi = 100, marks = [20, 80], label, width = 220 }: { value: number | null | undefined; lo?: number; hi?: number; marks?: number[]; label?: string; width?: number }) {
  const h = 26
  const x = (v: number) => 4 + ((Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo || 1)) * (width - 8)
  return (
    <svg width={width} height={h} viewBox={`0 0 ${width} ${h}`} role="img" aria-label={label}>
      <rect x={4} y={10} width={width - 8} height={6} fill={T.border} />
      {marks.map(m => <line key={m} x1={x(m)} x2={x(m)} y1={7} y2={19} stroke={T.borderHi} />)}
      {value != null && Number.isFinite(value) && <>
        <rect x={x(value) - 2} y={5} width={4} height={16} fill={T.muted} />
        <text x={x(value)} y={h - 1} textAnchor="middle" fontSize={9} fontFamily={T.mono} fill={T.muted}>{Math.round(value)}</text>
      </>}
      <text x={4} y={6} fontSize={8} fontFamily={T.mono} fill={T.dim}>{lo}</text>
      <text x={width - 4} y={6} textAnchor="end" fontSize={8} fontFamily={T.mono} fill={T.dim}>{hi}</text>
    </svg>
  )
}

/** A tiny bar strip (e.g. rolling correlation per year, −1…+1). */
export function SmallMultiple({ values, lo = -1, hi = 1, width = 160, height = 44, label }: { values: { x: string | number; y: number | null | undefined }[]; lo?: number; hi?: number; width?: number; height?: number; label?: string }) {
  const n = Math.max(1, values.length)
  const pitch = width / n, bw = Math.max(1, pitch * 0.7)
  const y = (v: number) => 4 + (height - 14) - ((v - lo) / (hi - lo || 1)) * (height - 14)
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} style={{ display: 'block' }}>
      <line x1={0} x2={width} y1={y(0)} y2={y(0)} stroke={T.border} />
      {values.map((v, i) => v.y == null || !Number.isFinite(v.y) ? null : (
        <rect key={String(v.x)} x={i * pitch + (pitch - bw) / 2} y={Math.min(y(v.y), y(0))} width={bw} height={Math.max(0.5, Math.abs(y(v.y) - y(0)))} fill={T.violet} opacity={0.85}>
          <title>{`${v.x}: ${fmtTick(v.y, 2)}`}</title></rect>
      ))}
      {values.length > 0 && <>
        <text x={0} y={height - 1} fontSize={8} fontFamily={T.mono} fill={T.dim}>{String(values[0].x)}</text>
        <text x={width} y={height - 1} textAnchor="end" fontSize={8} fontFamily={T.mono} fill={T.dim}>{String(values[values.length - 1].x)}</text>
      </>}
    </svg>
  )
}
