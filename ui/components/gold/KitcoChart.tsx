'use client'

/**
 * The two chart renderers of GOLD › DAILY's Kitco-style panel (d.24h, wave 1d):
 *
 *  - `IntradayChart` — the Globex-day 24-hour axis (18:00 ET → 17:00 ET) with the previous day dotted, the previous
 *    session's close dashed, hi/lo, a two-row time axis (IST over NY), the session bands (Sydney/Tokyo · Shanghai · London ·
 *    New York), the MCX bar under the axis and the hatched CME maintenance hour. Also draws d.3day's overlay.
 *  - `TimeChart` — Kitco's longer timeframes (3 days … all) on a real time axis: one line of the stored bars converted per
 *    point with the rupee rate of the point's own time (lib/gold/kitco.ts), the previous close dashed on 3 days, hi/lo
 *    markers and the last value.
 *
 * Both take a per-point converter (`conv(usdPerOz, ms)`), so every unit and the duty toggle share one code path. Inline SVG
 * in CSS px (useChartSize, axisTicks); no library. Arithmetic only: nothing here is a forecast.
 *
 * One number once (PLAN §f.6, D5): the panel's stats row prints the window's high / low with their times, so the charts mark
 * the high and the low WITHOUT repeating the numbers; the dashed previous close prints its value once (the stats row does
 * not); the last value prints once, at the line's end.
 */
import { CHART_BOX, T, useChartSize } from '@/components/terminal'
import { axisTicks, textWidth } from '@/components/terminal/chart'
import { type KPt, fmtKitco, timeTicks } from '@/lib/gold/kitco'
import { axisPos, axisTicksIst, fmtHM, globexOpenIst, istToNy, sessionBands, type Band, type DayPt } from '@/lib/gold/sessions'

export const BAND_FILL: Record<Band['key'], string> = { sydney: '#1a2130', shanghai: '#2a1f3f', london: '#13303a', newyork: '#3a2a12', mcx: '#5a3f00', maintenance: 'transparent' }

/** A $/oz price at an instant → the plotted unit (null = not drawable: no rupee rate or no dated duty for that time). */
export type Conv = (usdPerOz: number, ms?: number) => number | null

function Hatch() {
  return (
    <defs>
      <pattern id="gold-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <line x1="0" y1="0" x2="0" y2="6" stroke={T.borderHi} strokeWidth="1" />
      </pattern>
    </defs>
  )
}

/** The 24-h chart (d.24h's 24 h timeframe) and the 3-day overlay (d.3day) share this renderer. */
export function IntradayChart({ groups, usDst, ukDst, conv, unitLabel, dp, settle, settleValue, settleLabel, showPrev, showBands, mode, live, sge }: {
  groups: { date: string; pts: DayPt[] }[]; usDst: boolean; ukDst: boolean; conv: Conv; unitLabel: string; dp: number
  /** `settleValue`: the previous close ALREADY in the plotted unit (its own date's rupee rate, D5 — the stats' base is the same number);
   *  undefined = convert `settle` at the last bar's instant (a bulletin settlement line) */
  settle: number | null; settleValue?: number | null; settleLabel: string; showPrev: boolean; showBands: boolean; mode: '24h' | '3day'
  live: { price: number; as_of: string } | null; sge: DayPt[] | null
}) {
  const { ref, w, h } = useChartSize(1100, 300, { minRatio: 0.85, maxRatio: 1.2 })
  const padL = 62, padR = 70, padT = 10, padB = 46
  const plotW = Math.max(100, w - padL - padR), plotH = Math.max(80, h - padT - padB)
  const days = mode === '24h' ? groups.slice(-2) : groups.slice(-3)
  const today = days[days.length - 1]
  const prev = mode === '24h' ? days[0] !== today ? days[0] : null : null
  const series = mode === '24h' ? [{ d: today, color: T.amber, dotted: false }, ...(showPrev && prev ? [{ d: prev, color: T.muted, dotted: true }] : [])]
    : days.map((d, i) => ({ d, color: [T.violet, T.cyan, T.amber][i + (3 - days.length)], dotted: false }))
  const lastMs = today?.pts[today.pts.length - 1]?.ms
  const cv = (v: number, ms?: number) => conv(v, ms)
  const vals: number[] = []
  for (const s of series) for (const p of s.d.pts) { const v = cv(p.c, p.ms); if (v != null) vals.push(v) }
  const settleV = settleValue !== undefined ? settleValue : settle != null ? cv(settle, lastMs) : null
  const liveV = live ? cv(live.price, lastMs) : null
  if (settleV != null) vals.push(settleV)
  if (liveV != null) vals.push(liveV)
  if (sge) for (const p of sge) { const v = cv(p.c, p.ms); if (v != null) vals.push(v) }
  const lo0 = vals.length ? Math.min(...vals) : 0, hi0 = vals.length ? Math.max(...vals) : 1
  const padY = Math.max((hi0 - lo0) * 0.08, Math.abs(hi0) * 0.0005)
  const lo = lo0 - padY, hi = hi0 + padY
  const yAxis = axisTicks(lo, hi, plotH, 28)
  const y = (v: number) => padT + plotH - ((v - lo) / (hi - lo || 1)) * plotH
  const x = (pos: number) => padL + (pos / 1440) * plotW
  const path = (pts: DayPt[]) => {
    let out = '', pen = false
    for (const p of pts) { const v = cv(p.c, p.ms); if (v == null) { pen = false; continue } out += `${pen ? 'L' : 'M'}${x(p.pos).toFixed(1)},${y(v).toFixed(1)}`; pen = true }
    return out
  }
  const bands = showBands ? sessionBands({ usDst, ukDst }) : []
  const open = globexOpenIst(usDst)
  const xt = axisTicksIst(usDst, plotW > 700 ? 120 : 180)
  const last = today?.pts[today.pts.length - 1]
  const conv24 = (today?.pts ?? []).map(p => ({ h: cv(p.h, p.ms), l: cv(p.l, p.ms) }))
  const hs = conv24.map(p => p.h).filter((v): v is number => v != null), ls = conv24.map(p => p.l).filter((v): v is number => v != null)
  const hiToday = hs.length ? Math.max(...hs) : null
  const loToday = ls.length ? Math.min(...ls) : null
  const lastV = last ? (liveV ?? cv(last.c, last.ms)) : null
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={mode === '24h' ? '24-hour gold chart' : 'three days overlaid'}>
        <Hatch />
        {bands.filter(b => b.key !== 'mcx').map((b, i) => {
          const p0 = axisPos(b.start, usDst), p1 = b.end >= 1440 ? 1440 - (open % 1440) : axisPos(b.end, usDst)
          const segs = p1 > p0 ? [[p0, p1]] : [[p0, 1440], [0, p1]]
          return segs.map(([a, z], k) => (
            <rect key={`${b.key}-${i}-${k}`} x={x(a)} y={padT} width={Math.max(0, x(z) - x(a))} height={plotH} data-gold-band={b.key}
              fill={b.key === 'maintenance' ? 'url(#gold-hatch)' : BAND_FILL[b.key]} opacity={b.key === 'maintenance' ? 0.6 : 0.35}>
              <title>{b.name} · {fmtHM(b.start)}–{fmtHM(b.end)} IST</title>
            </rect>
          ))
        })}
        {yAxis.ticks.map(t => (
          <g key={t}>
            <line x1={padL} x2={padL + plotW} y1={y(t)} y2={y(t)} stroke={T.border} strokeDasharray="2 4" />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={9.5} fill={T.muted} fontFamily={T.mono}>{fmtKitco(t, yAxis.dp, unitLabel)}</text>
          </g>
        ))}
        <text x={4} y={padT - 1} textAnchor="start" fontSize={9} fill={T.dim} fontFamily={T.mono}>{unitLabel}</text>
        {settleV != null && (
          <g data-gold-prev-close>
            <line x1={padL} x2={padL + plotW} y1={y(settleV)} y2={y(settleV)} stroke={T.cyan} strokeDasharray="6 4" strokeWidth={1} />
            <text x={padL + plotW - 4} y={y(settleV) - 4} textAnchor="end" fontSize={9} fill={T.cyan} fontFamily={T.mono}>{settleLabel} {fmtKitco(settleV, dp, unitLabel)}</text>
          </g>
        )}
        {sge && sge.length > 1 && <path d={path(sge)} fill="none" stroke={T.violet} strokeWidth={1} strokeDasharray="2 3" opacity={0.9} />}
        {series.map(s => s.d.pts.length > 1 && (
          <path key={s.d.date} d={path(s.d.pts)} fill="none" stroke={s.color} strokeWidth={s.dotted ? 1 : 1.5} strokeDasharray={s.dotted ? '2 3' : undefined} />
        ))}
        {mode === '24h' && last && lastV != null && (
          <g>
            <circle cx={x(last.pos)} cy={y(lastV)} r={3} fill={T.amber} />
            <text x={Math.min(x(last.pos) + 6, padL + plotW - textWidth('0,00,000.00', 9.5))} y={y(lastV) - 6} fontSize={9.5} fill={T.amber} fontFamily={T.mono}>{fmtKitco(lastV, dp, unitLabel)}</text>
          </g>
        )}
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
        {/* the high / low are MARKED, their numbers print once in the stats row above the chart (§f.6) */}
        {mode === '24h' && hiToday != null && loToday != null && (
          <g fontSize={9} fontFamily={T.mono} fill={T.dim} data-gold-hilo-marks>
            <text x={padL + plotW + 4} y={y(hiToday) + 3}>◂ high</text>
            <text x={padL + plotW + 4} y={y(loToday) + 3}>◂ low</text>
          </g>
        )}
      </svg>
    </div>
  )
}

/** Kitco's longer timeframes on a real time axis (already-converted points). `prevClose` is drawn dashed when given. */
export function TimeChart({ pts, dp, unitLabel, prevClose, prevCloseLabel, hi, lo, label }: {
  pts: KPt[]; dp: number; unitLabel: string; prevClose: number | null; prevCloseLabel: string
  hi: { v: number; ms: number } | null; lo: { v: number; ms: number } | null; label: string
}) {
  const { ref, w, h } = useChartSize(1100, 300, { minRatio: 0.85, maxRatio: 1.2 })
  const padL = 66, padR = 70, padT = 12, padB = 28
  const plotW = Math.max(100, w - padL - padR), plotH = Math.max(80, h - padT - padB)
  if (pts.length < 2) return <div ref={ref} style={{ ...CHART_BOX, fontSize: 11, color: T.dim, padding: 12 }}>Fewer than two stored points in this window.</div>
  const t0 = pts[0].ms, t1 = pts[pts.length - 1].ms
  const vals = pts.map(p => p.v)
  if (prevClose != null) vals.push(prevClose)
  const lo0 = Math.min(...vals), hi0 = Math.max(...vals)
  const padY = Math.max((hi0 - lo0) * 0.08, Math.abs(hi0) * 0.0005)
  const ylo = lo0 - padY, yhi = hi0 + padY
  const yAxis = axisTicks(ylo, yhi, plotH, 28)
  const x = (ms: number) => padL + ((ms - t0) / Math.max(1, t1 - t0)) * plotW
  const y = (v: number) => padT + plotH - ((v - ylo) / (yhi - ylo || 1)) * plotH
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.ms).toFixed(1)},${y(p.v).toFixed(1)}`).join(' ')
  const area = `${d} L${x(t1).toFixed(1)},${(padT + plotH).toFixed(1)} L${x(t0).toFixed(1)},${(padT + plotH).toFixed(1)} Z`
  const xt = timeTicks(t0, t1, plotW > 700 ? 9 : 5)
  const last = pts[pts.length - 1]
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}>
        {yAxis.ticks.map(t => (
          <g key={t}>
            <line x1={padL} x2={padL + plotW} y1={y(t)} y2={y(t)} stroke={T.border} strokeDasharray="2 4" />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={9.5} fill={T.muted} fontFamily={T.mono}>{fmtKitco(t, yAxis.dp, unitLabel)}</text>
          </g>
        ))}
        <text x={4} y={padT - 2} textAnchor="start" fontSize={9} fill={T.dim} fontFamily={T.mono}>{unitLabel}</text>
        <path d={area} fill={T.amber} opacity={0.06} />
        <path d={d} fill="none" stroke={T.amber} strokeWidth={1.4} />
        {prevClose != null && (
          <g data-gold-prev-close>
            <line x1={padL} x2={padL + plotW} y1={y(prevClose)} y2={y(prevClose)} stroke={T.cyan} strokeDasharray="6 4" strokeWidth={1} />
            <text x={padL + 4} y={y(prevClose) - 4} fontSize={9} fill={T.cyan} fontFamily={T.mono}>{prevCloseLabel} {fmtKitco(prevClose, dp, unitLabel)}</text>
          </g>
        )}
        {hi && <g fontSize={9} fontFamily={T.mono} fill={T.dim} data-gold-hilo-marks><circle cx={x(hi.ms)} cy={y(hi.v)} r={2} fill={T.dim} /><text x={Math.min(x(hi.ms) + 4, padL + plotW - 40)} y={y(hi.v) - 4}>high</text></g>}
        {lo && <g fontSize={9} fontFamily={T.mono} fill={T.dim}><circle cx={x(lo.ms)} cy={y(lo.v)} r={2} fill={T.dim} /><text x={Math.min(x(lo.ms) + 4, padL + plotW - 40)} y={y(lo.v) + 11}>low</text></g>}
        <circle cx={x(last.ms)} cy={y(last.v)} r={3} fill={T.amber} />
        <text x={padL + plotW + 4} y={y(last.v) + 3} fontSize={9.5} fill={T.amber} fontFamily={T.mono}>{fmtKitco(last.v, dp, unitLabel)}</text>
        <line x1={padL} x2={padL + plotW} y1={padT + plotH} y2={padT + plotH} stroke={T.borderHi} />
        {xt.map(t => (
          <g key={t.ms}>
            <line x1={x(t.ms)} x2={x(t.ms)} y1={padT + plotH} y2={padT + plotH + 3} stroke={T.borderHi} />
            <text x={x(t.ms)} y={padT + plotH + 14} textAnchor="middle" fontSize={9.5} fill={T.text} fontFamily={T.mono}>{t.label}</text>
          </g>
        ))}
        <text x={padL - 6} y={padT + plotH + 14} textAnchor="end" fontSize={9} fill={T.muted} fontFamily={T.mono}>IST</text>
      </svg>
    </div>
  )
}
