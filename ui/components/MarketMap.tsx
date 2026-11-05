'use client'

/**
 * Market map (Bloomberg IMAP) — the 250 most traded NSE stocks as a treemap: grouped by industry, tile size =
 * 20-day median turnover, colour = return over 1 day / 1 week / 1 month, or LIVE today during the session (NSE
 * heatmap lists, the rest from Yahoo; ≈1 min delayed, refreshed every 60 s). Click a tile for the stock.
 * Squarified layout (Bruls, Huizing & van Wijk 2000), two levels: industries, then stocks inside each.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { CHART_BOX, Chip, Panel, T, fmtPct, useChartSize } from '@/components/terminal'
import { openTicker } from '@/lib/openTicker'
import { getLiveQuotes, getNewsQuotes } from '@/lib/api'

export interface MapRow { symbol: string; industry: string; size: number | null; r1: number | null; r5: number | null; r21: number | null }
interface Rect { x: number; y: number; w: number; h: number }

const BASE_W = 1200, BASE_H = 560, HEADER = 13

/** Squarified treemap of `areas` (already scaled to the rect's area, sorted descending) inside `r`. */
export function squarify(areas: number[], r: Rect): Rect[] {
  const out: Rect[] = []
  let { x, y, w, h } = r
  let i = 0
  const worst = (row: number[], side: number) => {
    const s = row.reduce((a, b) => a + b, 0), mx = Math.max(...row), mn = Math.min(...row)
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn))
  }
  while (i < areas.length && w > 0 && h > 0) {
    const side = Math.min(w, h)
    const row = [areas[i]]
    let j = i + 1
    while (j < areas.length && worst([...row, areas[j]], side) <= worst(row, side)) row.push(areas[j++])
    const s = row.reduce((a, b) => a + b, 0)
    if (w >= h) {
      const cw = s / h
      let yy = y
      for (const a of row) { out.push({ x, y: yy, w: cw, h: a / cw }); yy += a / cw }
      x += cw; w -= cw
    } else {
      const rh = s / w
      let xx = x
      for (const a of row) { out.push({ x: xx, y, w: a / rh, h: rh }); xx += a / rh }
      y += rh; h -= rh
    }
    i = j
  }
  return out
}

function fill(v: number | null, cap: number): string {
  if (v == null || !Number.isFinite(v)) return '#10141c'
  if (Number(v.toFixed(1)) === 0) return '#161b25'      // prints '0.0%': neutral, never a red or green tint (RUP-11)
  const t = Math.min(Math.abs(v) / cap, 1)
  const [r, g, b] = v >= 0 ? [22, 217, 138] : [255, 77, 94]
  const base = [16, 20, 28]
  const mix = (c: number, i: number) => Math.round(base[i] + (c - base[i]) * (0.18 + 0.72 * t))
  return `rgb(${mix(r, 0)},${mix(g, 1)},${mix(b, 2)})`
}

type Period = 'live' | 'r1' | 'r5' | 'r21'
const PERIODS: [Period, string, number][] = [['live', '● LIVE', 3], ['r1', '1D', 3], ['r5', '1W', 6], ['r21', '1M', 12]]

/** Today's change for the map's stocks: NSE heatmap lists first (one shared server cache, every 60 s), Yahoo for
 *  the ~65 names NSE's lists miss. Yahoo prices one chart per symbol (≈25 s cold for 60), so that leg runs in the
 *  background every 5 min in session and once after the close, and the map paints from NSE without waiting. */
function useLiveChanges(symbols: string[], on: boolean) {
  const [live, setLive] = useState<{ chg: Record<string, number>; nse: number; at: Date } | null>(null)
  const yahoo = useRef<{ chg: Record<string, number>; at: number }>({ chg: {}, at: 0 })
  useEffect(() => {
    if (!on) return
    let alive = true
    const publish = (nseChg: Record<string, number>) => {
      const chg = { ...yahoo.current.chg, ...nseChg }
      if (alive) setLive({ chg, nse: Object.keys(nseChg).length, at: new Date() })
    }
    let lastNse: Record<string, number> = {}
    const loadNse = async () => {
      const chg: Record<string, number> = {}
      try {
        const q = (await getLiveQuotes()).data.quotes
        for (const s of symbols) if (q[s]?.change_pct != null) chg[s] = q[s].change_pct!
      } catch { /* Yahoo below covers what it can */ }
      lastNse = chg
      publish(chg)
      return chg
    }
    const loadYahoo = async (nseChg: Record<string, number>) => {
      const stale = Date.now() - yahoo.current.at > (sessionOpen() ? 5 * 60_000 : 6 * 3_600_000)
      if (!stale) return
      yahoo.current.at = Date.now()
      const rest = symbols.filter(s => nseChg[s] == null)
      for (let i = 0; i < rest.length; i += 60) {
        try {
          const q = (await getNewsQuotes(rest.slice(i, i + 60).map(s => `${s}.NS`))).data.quotes
          for (const s of rest.slice(i, i + 60)) { const v = q[`${s}.NS`]; if (v?.available && v.change_pct != null) yahoo.current.chg[s] = v.change_pct }
        } catch { /* keep what we have */ }
      }
      publish(lastNse)
    }
    const tick = () => { loadNse().then(loadYahoo) }
    tick()
    const iv = setInterval(tick, 60_000)
    return () => { alive = false; clearInterval(iv) }
  }, [on, symbols])
  return live
}

function sessionOpen(now = new Date()): boolean {
  const m = now.getHours() * 60 + now.getMinutes()
  return now.getDay() >= 1 && now.getDay() <= 5 && m >= 9 * 60 + 15 && m <= 15 * 60 + 35
}
/** From the open until midnight on a weekday, today's moves are the default (NSE keeps the close after 15:30). */
function todayMatters(now = new Date()): boolean {
  return now.getDay() >= 1 && now.getDay() <= 5 && now.getHours() * 60 + now.getMinutes() >= 9 * 60 + 15
}

export function MarketMap({ rows }: { rows: MapRow[] }) {
  const [period, setPeriod] = useState<Period>(() => (todayMatters() ? 'live' : 'r1'))
  const [hover, setHover] = useState<MapRow | null>(null)
  const cap = PERIODS.find(p => p[0] === period)![2]
  const symbols = useMemo(() => rows.map(r => r.symbol), [rows])
  const live = useLiveChanges(symbols, period === 'live')
  const val = (s: MapRow): number | null => (period === 'live' ? live?.chg[s.symbol] ?? null : s[period])
  // laid out in CSS px (C1-17): tile labels keep their 7.5–11 px size at any panel width
  const { ref, w: W, h: H } = useChartSize(BASE_W, BASE_H, { minRatio: 0.75, maxRatio: 1.1 })

  const tiles = useMemo(() => {
    const groups = new Map<string, MapRow[]>()
    for (const r of rows) if ((r.size ?? 0) > 0) groups.set(r.industry, [...(groups.get(r.industry) ?? []), r])
    const inds = [...groups.entries()].map(([name, list]) => ({ name, list: list.sort((a, b) => b.size! - a.size!), total: list.reduce((a, b) => a + b.size!, 0) }))
      .sort((a, b) => b.total - a.total)
    const all = inds.reduce((a, b) => a + b.total, 0)
    const indRects = squarify(inds.map(g => (g.total / all) * W * H), { x: 0, y: 0, w: W, h: H })
    return inds.map((g, i) => {
      const r = indRects[i]
      const showHead = r.w > 70 && r.h > 34
      const inner = { x: r.x + 1, y: r.y + (showHead ? HEADER : 1), w: Math.max(r.w - 2, 0), h: Math.max(r.h - (showHead ? HEADER + 1 : 2), 0) }
      const stockRects = squarify(g.list.map(s => (s.size! / g.total) * inner.w * inner.h), inner)
      const avg = g.list.reduce((a, s) => a + (val(s) ?? 0) * s.size!, 0) / g.total
      return { ...g, rect: r, showHead, avg, stocks: g.list.map((s, k) => ({ s, r: stockRects[k] })) }
    })
  }, [rows, period, live, W, H])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <Panel title="Market map" accent={T.green} pad={0}
      subtitle={hover
        ? `${hover.symbol} · ${hover.industry}${live?.chg[hover.symbol] != null ? ` · ${todayMatters() ? 'today' : 'last session'} ${fmtPct(live.chg[hover.symbol])}` : ''} · 1D ${fmtPct(hover.r1)} · 1W ${fmtPct(hover.r5)} · 1M ${fmtPct(hover.r21)} · ₹${hover.size} cr/day`
        : period === 'live'
          ? (live ? `${sessionOpen() ? 'LIVE today' : todayMatters() ? 'Session close today' : 'Last session close'} · ${Object.keys(live.chg).length}/${rows.length} stocks priced (${live.nse} from NSE, the rest Yahoo) · ≈1 min delayed · ${live.at.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })} · grey = no live price`
                  : 'LIVE today · reading prices…')
          : `${rows.length} most traded stocks · size = turnover · colour = return (±${cap}% full colour) · click a tile`}
      right={<div style={{ display: 'flex', gap: 4 }}>
        {PERIODS.map(([k, label]) => <Chip key={k} color={T.green} active={period === k} onClick={() => setPeriod(k)}>{k !== 'live' || sessionOpen() ? label : todayMatters() ? 'TODAY' : 'LAST SESSION'}</Chip>)}
      </div>}>
      <div ref={ref} style={CHART_BOX}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block', background: T.bg }} role="img"
           aria-label="Market heatmap" onMouseLeave={() => setHover(null)}>
        {tiles.map(g => (
          <g key={g.name}>
            {g.stocks.map(({ s, r }) => r && (
              <g key={s.symbol} onMouseEnter={() => setHover(s)} onClick={() => openTicker(s.symbol)} style={{ cursor: 'pointer' }}>
                <rect x={r.x + 0.5} y={r.y + 0.5} width={Math.max(r.w - 1, 0)} height={Math.max(r.h - 1, 0)}
                      fill={fill(val(s), cap)} stroke={hover?.symbol === s.symbol ? T.bright : 'none'} />
                {r.w > 34 && r.h > 16 && (
                  <text x={r.x + r.w / 2} y={r.y + r.h / 2 + (r.h > 30 ? -2 : 3)} textAnchor="middle"
                        fontSize={Math.min(13, Math.max(8, r.w / 7))} fontFamily={T.mono} fontWeight={700} fill="#f2f5fa"
                        style={{ pointerEvents: 'none' }}>{s.symbol.length > r.w / 6.5 ? s.symbol.slice(0, Math.floor(r.w / 6.5)) : s.symbol}</text>
                )}
                {r.w > 34 && r.h > 30 && (
                  <text x={r.x + r.w / 2} y={r.y + r.h / 2 + 11} textAnchor="middle" fontSize={Math.min(11, Math.max(7.5, r.w / 8))}
                        fontFamily={T.mono} fill="#f2f5fae0" style={{ pointerEvents: 'none' }}>
                    {val(s) == null ? '' : fmtPct(val(s), 1)}
                  </text>
                )}
              </g>
            ))}
            <rect x={g.rect.x} y={g.rect.y} width={g.rect.w} height={g.rect.h} fill="none" stroke={T.bg} strokeWidth={2} style={{ pointerEvents: 'none' }} />
            {g.showHead && (
              <text x={g.rect.x + 4} y={g.rect.y + 10} fontSize={9} fontFamily={T.display} letterSpacing={0.8} fill={T.muted}
                    style={{ pointerEvents: 'none', textTransform: 'uppercase' }}>
                {/* ~6 px per character at 9 px; leave room for the " +0.0%" suffix (7 characters) */}
                {g.name.length > g.rect.w / 6 - 8 ? `${g.name.slice(0, Math.max(Math.floor(g.rect.w / 6) - 9, 3))}…` : g.name}
                {/* RUP-11: coloured by the value as printed: a −0.03 average reads '0.0%' and is not red */}
                <tspan fill={Number(g.avg.toFixed(1)) > 0 ? T.green : Number(g.avg.toFixed(1)) < 0 ? T.red : T.muted}> {fmtPct(g.avg, 1)}</tspan>
              </text>
            )}
          </g>
        ))}
      </svg>
      </div>
    </Panel>
  )
}
