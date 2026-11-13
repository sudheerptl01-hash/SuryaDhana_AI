'use client'

/**
 * MEMB › "Within-day contribution" (FINAL round R2-DRIV; RATING R9-I3): who is moving the index through the day —
 * a stacked minute timeline of the top ± contributors (points = previous index close × weight × intraday return from
 * the live tick store's minute closes; 2-min tape fallback per name), with the index's own move as a line, the
 * explained sum dashed, and the residual stated once. Honest gaps: a name with no prints is listed, never filled in;
 * a session whose socket started late simply starts where the prints do.
 *
 * Badges: timeline `context`, members/fit `arithmetic`. Member colours are identification only (a fixed categorical
 * palette); the footer ends "describes, does not predict". Works closed-market from the stored session; in session it
 * refreshes once a minute. Nothing here feeds the Desk, the S1 shadow, a directional alert or a ticket price.
 */
import axios from 'axios'
import { useEffect, useMemo, useRef, useState } from 'react'
import { BadgeChip, Panel, T, sourceOf } from '@/components/terminal'
import type { Badge } from '@/components/terminal/source'
import { driversError, fmtPts } from './api'
import { axisTicks, coverageLine, extentOf, hoverRows, nearestIdx, residualLine, shownSeries, stackAt,
         type IntradayDriversPayload, type ShownSeries } from './intradayModel'

const client = axios.create({ baseURL: '', timeout: 20_000 })
const getIntraday = (index: string) =>
  client.get<IntradayDriversPayload>('/api/market/index-drivers/intraday', { params: { index, interval: '1m', top: 7 } })

const W = 860, H = 232, PAD_L = 46, PAD_R = 10, PAD_T = 8, PAD_B = 20
const tone = (v: number | null | undefined) => (v == null ? T.dim : v > 0 ? T.green : v < 0 ? T.red : T.muted)

export function IntradayDrivers({ index }: { index: string }) {
  const [p, setP] = useState<IntradayDriversPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  const boxRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | null = null
    setP(null); setErr(null); setHover(null)
    const load = () => getIntraday(index)
      .then(r => { if (!alive) return; setP(r.data); setErr(null); if (r.data.live) timer = setTimeout(load, 60_000) })
      .catch((e: unknown) => { if (alive) setErr(driversError(e)) })
    load()
    return () => { alive = false; if (timer) clearTimeout(timer) }
  }, [index])

  const shown: ShownSeries[] = useMemo(() => (p ? shownSeries(p, T.dim) : []), [p])
  const n = p?.minutes?.length ?? 0
  const [lo, hi] = useMemo(() => (p ? extentOf(p, shown) : [0, 0]), [p, shown])
  const span = Math.max(hi - lo, 1e-6)
  const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B
  const x = (i: number) => PAD_L + (n > 1 ? (i / (n - 1)) * plotW : plotW / 2)
  const y = (v: number) => PAD_T + (1 - (v - lo) / span) * plotH
  const barW = Math.max(0.8, n > 1 ? plotW / (n - 1) : plotW)

  const linePath = (vals: (number | null)[] | undefined) => {
    if (!vals) return ''
    let d = ''
    let pen = false
    vals.forEach((v, i) => {
      if (v == null || !Number.isFinite(v)) { pen = false; return }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
      pen = true
    })
    return d
  }

  const storeErrs = Object.values(p?.store_errors ?? {})
  const empty = !!p && (p.ok === false || n === 0 || shown.length === 0)
  const srcHint = err ?? (storeErrs.length ? storeErrs.join(' · ') : undefined)
  const gridTicks = p ? axisTicks(p.minutes) : []
  const yTicks = useMemo(() => {
    const out: number[] = []
    for (let k = 0; k <= 4; k++) out.push(lo + (span * k) / 4)
    return out
  }, [lo, span])
  const hv = hover != null && p ? {
    minute: p.minutes[hover], actual: p.actual_pts?.[hover] ?? null, explained: p.explained_pts?.[hover] ?? null,
    residual: p.residual_pts?.[hover] ?? null, rows: hoverRows(shown, hover, 4),
  } : null
  const resLine = p ? residualLine(p) : null

  return (
    <Panel title={`Within-day contribution · ${index}`} accent={T.cyan} pad={10} badge={(p?.badges?.timeline ?? 'context') as Badge}
      source={sourceOf(p?.as_of ?? null, { source: p?.index_source ?? 'tick store', live: !!p?.live, hint: srcHint })}
      subtitle={p ? `${p.date ?? ''} · top ±7 members stacked per minute · solid line = the index's own move · dashed = Σ member points${p.live ? ' · refreshes each minute' : ' · stored session'}`
        : 'per-minute member points from the live tick store'}>
      {!p && !err && <div style={{ fontSize: 11, color: T.muted }}>Loading the session's prints…</div>}
      {err && <div style={{ fontSize: 11, color: T.muted }} data-intraday-error>{err}</div>}
      {empty && (
        <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6 }} data-intraday-empty>
          No within-day prints stored for this session{storeErrs.length ? ` (${storeErrs.join(' · ')})` : ''}. The timeline
          fills from the live tick store while the socket runs (and from the 2-min tape where a name is unsubscribed);
          a session with no stored prints stays honestly blank.
        </div>
      )}
      {p && !empty && (
        <>
          <div ref={boxRef} style={{ position: 'relative' }}
            onMouseLeave={() => setHover(null)}
            onMouseMove={e => {
              const r = boxRef.current?.getBoundingClientRect()
              if (!r || r.width <= 0) return
              const fx = ((e.clientX - r.left) / r.width) * W
              setHover(nearestIdx((fx - PAD_L) / plotW, n))
            }}>
            <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }} role="img"
              aria-label={`within-day contribution timeline for ${index}`} data-intraday-chart>
              {yTicks.map(v => (
                <g key={v}>
                  <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke={T.border} strokeWidth={Math.abs(v) < 1e-9 ? 1 : 0.5} />
                  <text x={PAD_L - 4} y={y(v) + 3} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{fmtPts(v, 0)}</text>
                </g>
              ))}
              {gridTicks.map(i => (
                <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize={9} fill={T.dim} fontFamily={T.mono}>{p.minutes[i]}</text>
              ))}
              {p.minutes.map((_, i) => stackAt(shown, i).map(s => (
                <rect key={`${i}-${s.symbol}`} x={x(i) - barW / 2} width={barW}
                  y={Math.min(y(s.y0), y(s.y1))} height={Math.max(Math.abs(y(s.y1) - y(s.y0)), 0.3)}
                  fill={s.color} opacity={0.82} shapeRendering="crispEdges" />
              )))}
              <path d={linePath(p.explained_pts)} fill="none" stroke={T.cyan} strokeWidth={1.1} strokeDasharray="4 3" />
              <path d={linePath(p.actual_pts)} fill="none" stroke={T.bright} strokeWidth={1.4} />
              {hover != null && <line x1={x(hover)} x2={x(hover)} y1={PAD_T} y2={H - PAD_B} stroke={T.muted} strokeWidth={0.7} strokeDasharray="2 2" />}
            </svg>
            {hv && (
              <div style={{ position: 'absolute', top: 6, right: 8, background: '#0a0c10', border: `1px solid ${T.border}`,
                            padding: '5px 8px', fontFamily: T.mono, fontSize: 10, color: T.text, pointerEvents: 'none', lineHeight: 1.5 }}
                data-intraday-hover>
                <div style={{ color: T.muted }}>{hv.minute}</div>
                <div>index {fmtPts(hv.actual)} · explained {fmtPts(hv.explained)} · residual {fmtPts(hv.residual)}</div>
                {hv.rows.map(r => <div key={r.symbol}><span style={{ color: r.color }}>■</span> {r.symbol} {fmtPts(r.points)}</div>)}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 12px', marginTop: 6, fontFamily: T.mono, fontSize: 10 }} data-intraday-legend>
            {[...(p.members.add ?? []), ...(p.members.drag ?? [])].map((m, i) => (
              <span key={m.symbol} title={`weight ${m.weight_pct?.toFixed(2) ?? '—'}% · intraday ${m.ret_pct != null ? `${m.ret_pct}%` : '—'} · ${m.source}`}>
                <span style={{ color: shown[i]?.color ?? T.dim }}>■</span> <span style={{ color: T.text }}>{m.symbol}</span>{' '}
                <span style={{ color: tone(m.points) }}>{fmtPts(m.points)}</span>
              </span>
            ))}
            {(p.others_pts ?? []).some(v => v != null && v !== 0) && (
              <span><span style={{ color: T.dim }}>■</span> <span style={{ color: T.muted }}>OTHERS (the remaining priced members)</span></span>
            )}
          </div>
          {resLine && <div style={{ marginTop: 6, fontFamily: T.mono, fontSize: 10, color: T.muted, border: `1px solid ${T.border}`,
                                    display: 'inline-block', padding: '1px 6px' }} data-intraday-residual>{resLine} <BadgeChip badge={(p.badges?.fit ?? 'arithmetic') as Badge} /></div>}
          <div style={{ marginTop: 6, fontSize: 10, color: T.muted }} data-intraday-coverage>{coverageLine(p)}</div>
          <div style={{ marginTop: 4, fontSize: 10, color: T.dim }}>{p.note ?? 'describes, does not predict'}</div>
        </>
      )}
    </Panel>
  )
}
