'use client'

import { apiError } from '@/lib/errors'
/**
 * Market Monitor (MKT) — "how is the Indian market today", Bloomberg-style, from NSE's own EOD files.
 * Regime score 0–4 (SuryaDhana Scanner Handbook, Stage 2), breadth, a one-year breadth chart with the regime
 * strip, an industry heatmap and six mover lists. Rows open the stock detail (chart, ☆ PIN, + WATCHLIST…).
 * Data: /api/market/monitor ← data-service /db/market-monitor (services/data-service/market_monitor.py).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getMarketMonitor, getRecentResults, type MarketMonitor as Data, type MarketMover, type MarketSector, type RecentResult } from '@/lib/api'
import { CHART_BOX, Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, Stat, T, type Column, fmtIdx, fmtPct, fmtNum, fmtSigned, ordinal, tone, useChartSize, sourceOf } from '@/components/terminal'
import { labelEvery, niceAxis } from '@/components/terminal/chart'
import { MarketMap } from './MarketMap'
import { sessionDayLabel, unicodeMinus } from '@/lib/format'
import { RotationChart } from './RotationChart'
import { ParticipantPositioning } from './ParticipantPositioning'
import { IndexValuation, YieldGapPanel } from './IndexValuation'

const SCORE_COLOR = [T.red, T.red, T.amber, T.green, T.green]
const SCORE_WORD = ['RISK-OFF', 'DEFENSIVE', 'MIXED', 'CONSTRUCTIVE', 'STRONG']

const pct = fmtPct
const num = fmtNum

/** Heat colour for a return: green/red with intensity up to ±cap %. */
function heat(v: number | null | undefined, cap = 6): string {
  if (v == null || !Number.isFinite(v)) return 'transparent'
  const a = Math.min(Math.abs(v) / cap, 1) * 0.55 + 0.06
  return v >= 0 ? `rgba(22,217,138,${a})` : `rgba(255,77,94,${a})`
}

function RegimeGauge({ d }: { d: Data }) {
  const s = d.regime.score
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
        <span style={{ fontFamily: T.mono, fontSize: 44, fontWeight: 700, color: SCORE_COLOR[s], lineHeight: 1 }}>{s}</span>
        <span style={{ fontFamily: T.mono, fontSize: 14, color: T.muted }}>/ 4</span>
        <span style={{ fontFamily: T.display, fontSize: 18, fontWeight: 700, letterSpacing: 1.6, color: SCORE_COLOR[s] }}>{SCORE_WORD[s]}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4 }}>
        {[0, 1, 2, 3].map(i => (
          <div key={i} style={{ height: 8, background: i < s ? SCORE_COLOR[s] : T.border }} />
        ))}
      </div>
      <div style={{ fontSize: 11, color: T.text, lineHeight: 1.6 }}>
        Exposure guide <b style={{ color: SCORE_COLOR[s] }}>{d.regime.exposure}</b> · {d.regime.setups}
        <div style={{ color: T.muted, fontSize: 10 }}>
          {d.regime.changed_from !== s ? `changed from ${d.regime.changed_from} ${sessionDayLabel(d.as_of)}` : `at ${s} for ${d.regime.days_at_score} sessions`}
        </div>
      </div>
      <div style={{ display: 'grid', gap: 6 }}>
        {d.regime.components.map(c => (
          <div key={c.key} style={{ display: 'grid', gridTemplateColumns: '18px 1fr', gap: 8, alignItems: 'start' }}>
            <span style={{ color: c.ok ? T.green : T.red, fontFamily: T.mono, fontSize: 13 }}>{c.ok ? '✓' : '✕'}</span>
            <div>
              <div style={{ fontSize: 11, color: c.ok ? T.text : T.muted }}>{c.label}</div>
              <div style={{ fontSize: 10, color: T.dim, fontFamily: T.mono }}>{unicodeMinus(String(c.detail ?? ""))}</div>{/* server sentence: U+2212 (C1-18) */}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Index (left axis) + % of stocks above the 50/200-DMA (right axis, 0–100) with a regime strip. */
function BreadthChart({ d }: { d: Data }) {
  // CSS px (C1-17): fixed 260 px height (the regime strip sits at fixed offsets), width = the panel
  const { ref, w: W, h: H } = useChartSize(1000, 260, { minRatio: 1, maxRatio: 1 })
  const h = d.history
  const padL = 54, padR = 40, top = 10, chartH = 200, stripY = 222
  const idx = h.map(p => p.index ?? NaN)
  const lo = Math.min(...idx.filter(Number.isFinite)), hi = Math.max(...idx.filter(Number.isFinite))
  const x = (i: number) => padL + (i / Math.max(h.length - 1, 1)) * (W - padL - padR)
  const yI = (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * chartH
  const yP = (v: number) => top + (1 - v / 100) * chartH
  const path = (vals: (number | null)[], y: (v: number) => number) =>
    vals.map((v, i) => (v == null || !Number.isFinite(v) ? '' : `${i === 0 || vals[i - 1] == null ? 'M' : 'L'}${x(i).toFixed(1)},${y(v).toFixed(1)}`)).join('')
  const months = h.map((p, i) => ({ i, m: p.date.slice(0, 7) })).filter((p, i, a) => i === 0 || p.m !== a[i - 1].m)
  const every = Math.max(2, labelEvery(months.length > 1 ? (W - padL - padR) / months.length : W, 56))
  const idxAxis = niceAxis(lo, hi, 3)
  return (
    <div ref={ref} style={CHART_BOX}>
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label="Breadth history">
      {[0, 25, 50, 75, 100].map(v => (
        <g key={v}>
          <line x1={padL} x2={W - padR} y1={yP(v)} y2={yP(v)} stroke={v === 50 ? T.borderHi : T.border} strokeDasharray={v === 50 ? '4 4' : '2 4'} />
          <text x={W - padR + 6} y={yP(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono}>{v}%</text>
        </g>
      ))}
      {idxAxis.ticks.map(v => (
        <text key={v} x={padL - 6} y={yI(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="end">{num(v, idxAxis.dp)}</text>
      ))}
      <path d={path(h.map(p => p.pct_above200), yP)} fill="none" stroke={T.violet} strokeWidth={1.4} opacity={0.9} />
      <path d={path(h.map(p => p.pct_above50), yP)} fill="none" stroke={T.cyan} strokeWidth={1.4} opacity={0.9} />
      <path d={path(idx, yI)} fill="none" stroke={T.amber} strokeWidth={2} />
      {h.map((p, i) => (
        <rect key={p.date} x={x(i) - 0.5} y={stripY} width={(W - padL - padR) / h.length + 0.6} height={12}
          fill={SCORE_COLOR[p.score]} opacity={0.25 + p.score * 0.15}>
          <title>{`${p.date}: regime ${p.score}`}</title>
        </rect>
      ))}
      <text x={padL - 6} y={stripY + 10} fill={T.dim} fontSize={9} fontFamily={T.mono} textAnchor="end">REGIME</text>
      {months.filter((_, k) => k % every === 0).filter(p => x(p.i) + 40 <= W).map(p => (
        <text key={p.m} x={x(p.i)} y={H - 6} fill={T.dim} fontSize={10} fontFamily={T.mono}>
          {new Date(`${p.m}-01`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })}
        </text>
      ))}
    </svg>
    </div>
  )
}

function MoverTable({ title, rows, onSelect, sortKey, accent, results, day = 'today', asOf = null }: {
  /** the EOD session the movers describe (PLAN §0.5 source chip) */
  asOf?: string | null
  title: string; rows: MarketMover[]; onSelect: (s: string) => void; sortKey: 'chg_pct' | 'turnover_cr' | 'vol_x'; accent: string
  results?: Map<string, RecentResult>
  /** the EOD session the lists are from: 'today' or 'on 23 Oct' (P16 MKT wording) */
  day?: string
}) {
  const cols: Column<MarketMover>[] = [
    { key: 'symbol', label: 'Stock', render: r => {
      const res = results?.get(r.symbol)
      return <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
        <span style={{ color: T.amber, fontWeight: 600 }} title={r.industry}>{r.symbol}</span>
        {res && <span title={`Results released ${res.released_at} (${res.timing}); this is the reaction session`}
                      style={{ fontSize: 9, color: T.violet, border: `1px solid ${T.violet}88`, padding: '0 3px' }}>RESULTS</span>}
      </span>
    } },
    { key: 'close', label: 'Close', align: 'right', render: r => num(r.close, 2) },
    { key: 'chg_pct', label: 'Chg', align: 'right', sort: r => r.chg_pct, render: r => <span style={{ color: tone(r.chg_pct) }}>{pct(r.chg_pct)}</span> },
    sortKey === 'vol_x'
      ? { key: 'vol_x', label: 'Vol ×', align: 'right', sort: r => r.vol_x, render: r => <span style={{ color: T.cyan }}>{num(r.vol_x, 1)}×</span> }
      : { key: 'turnover_cr', label: '₹ cr', align: 'right', sort: r => r.turnover_cr, render: r => num(r.turnover_cr, 0) },
    { key: 'from_52w_high_pct', label: 'vs 52w H', align: 'right', render: r => <span style={{ color: T.muted }}>{pct(r.from_52w_high_pct, 1)}</span> },
  ]
  return (
    <Panel title={title} accent={accent} pad={0} source={sourceOf(asOf, { source: 'NSE EOD' })}>
      <DataTable columns={cols} rows={rows} rowKey={r => r.symbol} dense onRowClick={r => onSelect(r.symbol)} empty={`None ${day}`} />
    </Panel>
  )
}

export function MarketMonitor({ onSelectTicker }: { onSelectTicker: (s: string) => void }) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recent, setRecent] = useState<RecentResult[]>([])
  useEffect(() => { getRecentResults(7).then(r => setRecent(r.data.rows)).catch(() => {}) }, [])
  const [industry, setIndustry] = useState<string | null>(null)
  const [sectorSort, setSectorSort] = useState<'ret_1d_pct' | 'ret_5d_pct' | 'ret_21d_pct' | 'ret_63d_pct'>('ret_21d_pct')

  const load = useCallback(async () => {
    try { setData((await getMarketMonitor()).data); setError(null) }
    catch (e: any) { setError(apiError(e, 'Market monitor unavailable')) }
  }, [])
  useEffect(() => { load(); const iv = setInterval(load, 10 * 60_000); return () => clearInterval(iv) }, [load])

  const sectors = useMemo(() => [...(data?.sectors ?? [])].sort((a, b) => (b[sectorSort] ?? -1e9) - (a[sectorSort] ?? -1e9)), [data, sectorSort])
  const b = data?.breadth ?? {}
  const resultsToday = useMemo(() => new Map(recent.filter(r => r.reaction_date === data?.as_of).map(r => [r.symbol, r])), [recent, data?.as_of])
  const sectorCols: Column<MarketSector>[] = [
    { key: 'industry', label: 'Industry', render: r => <span style={{ color: T.text }}>{r.industry}</span> },
    { key: 'stocks', label: 'N', align: 'right', render: r => <span style={{ color: T.dim }}>{r.stocks}</span> },
    ...(['ret_1d_pct', 'ret_5d_pct', 'ret_21d_pct', 'ret_63d_pct'] as const).map((k, i) => ({
      key: k, label: ['1D', '1W', '1M', '3M'][i], align: 'right' as const, sort: (r: MarketSector) => r[k],
      render: (r: MarketSector) => (
        <span style={{ display: 'inline-block', minWidth: 62, padding: '2px 6px', background: heat(r[k], [2, 4, 8, 15][i]),
                       color: T.bright, fontFamily: T.mono }}>{pct(r[k], 1)}</span>
      ),
    })),
    { key: 'pct_above50', label: '> 50-DMA', align: 'right', sort: r => r.pct_above50,
      // L-15: breadth is context — emphasis by brightness only, never green/red
      render: r => <span style={{ color: (r.pct_above50 ?? 0) >= 50 ? T.text : T.muted }}>{num(r.pct_above50)}%</span> },
  ]

  if (error && !data) return <div><PageHeader code="MKT" title="Market Monitor" /><ErrorBox error={error} onRetry={load} /></div>
  if (!data) return <div><PageHeader code="MKT" title="Market Monitor" /><Loading label="Reading NSE breadth" /></div>
  const s = data.regime.score
  // P16 / C1-13: MKT is end of day; on a weekend, a holiday or before the EOD files it names the session ('on 23 Oct')
  const day = sessionDayLabel(data.as_of)
  return (
    <div>
      <PageHeader code="MKT" title="Market Monitor"
        subtitle={`NSE breadth · regime · sectors · movers · EOD ${new Date(data.as_of).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })} · ${num(b.universe)} stocks`}
        status={<Chip color={SCORE_COLOR[s]} active>REGIME {s}/4 · {SCORE_WORD[s]}</Chip>}
        right={<Chip color={T.amber} onClick={load}>↻ REFRESH</Chip>} />
      <div style={{ display: 'grid', gap: 12 }}>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(300px, 1fr) minmax(0, 2.4fr)' }}>
          {/* m023: a short subtitle (the long one wrapped into a narrow four-line column beside the chips) */}
          <Panel source={sourceOf(data.as_of, { source: 'NSE EOD' })} badge="context" title="Market regime" subtitle="not a signal" accent={T.muted}>
            <div style={{ fontSize: 10, color: T.dim, marginBottom: 6 }}>Scanner Handbook stage 2 · a health gauge</div>
            <RegimeGauge d={data} />
          </Panel>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', alignContent: 'start' }}>
            {/* C1-08 / CT-05: index level and its 200-DMA at NSE's 2 decimals, the same as BRF (was 0 dp: 21,428 vs 21,427.60) */}
            <Stat label={data.index_name} value={fmtIdx(b.index)} color={tone(b.index_chg_pct)} accent={T.amber}
              sub={`${pct(b.index_chg_pct)} ${day} · 200-DMA ${fmtIdx(b.index_sma200)}`} />
            {/* m007 / m019: the universe named (BRF and MOV read the Nifty 500's own members) */}
            {/* L-15 sweep: breadth figures are context — neutral tone; the sub-lines keep the thresholds in words */}
            <Stat label={`Advances / declines · ${num(b.universe)} liquid`} value={`${num(b.adv)} / ${num(b.dec)}`}
              sub={`ratio ${b.dec ? ((b.adv ?? 0) / b.dec).toFixed(2) : '—'} · not the Nifty 500`} />
            <Stat label="Above 50-DMA" value={pct(b.pct_above50, 0, false)} accent={T.cyan}
              sub={`20-DMA ${pct(b.pct_above20, 0, false)} (${pct(b.pct_above20_chg, 1)} ${day})`} />
            <Stat label="Above 200-DMA" value={pct(b.pct_above200, 0, false)} accent={T.violet}
              sub="the long-term trend" />
            <Stat label="New 52w highs / lows" value={`${num(b.new_highs)} / ${num(b.new_lows)}`}
              sub={`10-day avg net ${fmtSigned(b.nh_nl_10d, 0)}`} />
            <Stat label="Market Monitor ±4%" value={`${num(b.up4)} / ${num(b.dn4)}`}
              sub={`5d ${num(b.mm_ratio5, 2)} · 10d ${num(b.mm_ratio10, 2)} (≥ 1.5 bullish)`} />
            <Stat label="Distribution days" value={`${num(b.dist_days_25)} / 25`}
              sub="≥ 5 = institutions selling" />
            <Stat label="India VIX" value={num(b.vix, 2)} accent={T.muted}
              sub={`${ordinal(b.vix_pct)} percentile of the past year`} />
          </div>
        </div>

        <IndexValuation />
        <YieldGapPanel />
        <Panel source={sourceOf(data.as_of, { source: 'NSE EOD' })} badge="context" title="One year of breadth" accent={T.cyan}
          subtitle="amber = index (left axis) · cyan = % above 50-DMA · violet = % above 200-DMA (right axis) · strip = regime score">
          <BreadthChart d={data} />
        </Panel>

        {data.map && data.map.length > 0 && <MarketMap rows={data.map} />}
        {data.rotation && data.rotation.length > 0 && <RotationChart rows={data.rotation} />}
        <ParticipantPositioning />

        <Panel source={sourceOf(data.as_of, { source: 'NSE EOD' })} badge="arithmetic" title="Industry table" subtitle="equal-weighted returns of liquid stocks in each NSE industry · click an industry for its stocks" accent={T.amber} pad={0}
          right={<div style={{ display: 'flex', gap: 4 }}>
            {(['ret_1d_pct', 'ret_5d_pct', 'ret_21d_pct', 'ret_63d_pct'] as const).map((k, i) => (
              <Chip key={k} color={T.amber} active={sectorSort === k} onClick={() => setSectorSort(k)}>{['1D', '1W', '1M', '3M'][i]}</Chip>
            ))}
          </div>}>
          <DataTable columns={sectorCols} rows={sectors} rowKey={r => r.industry} dense maxHeight={420}
            onRowClick={r => setIndustry(industry === r.industry ? null : r.industry)}
            rowStyle={r => (r.industry === industry ? { background: T.panel3, boxShadow: `inset 2px 0 0 ${T.amber}` } : undefined)} />
          {industry && (() => {
            const members = (data.map ?? []).filter(m => m.industry === industry)
            return (
              <div style={{ borderTop: `1px solid ${T.border}` }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', background: '#080b10' }}>
                  <span style={{ fontFamily: T.display, fontSize: 11, letterSpacing: 1.4, color: T.amber }}>{industry.toUpperCase()}</span>
                  <span style={{ fontSize: 10, color: T.muted }}>{members.length} of the 250 most traded stocks · click a stock for its profile</span>
                  <span style={{ flex: 1 }} />
                  <Chip color={T.muted} onClick={() => setIndustry(null)}>✕ CLOSE</Chip>
                </div>
                <DataTable dense maxHeight={360} rows={members} rowKey={m => m.symbol} onRowClick={m => onSelectTicker(m.symbol)}
                  initialSort={{ key: 'size', dir: 'desc' }}
                  empty="None of this industry's stocks is among the 250 most traded"
                  columns={[
                    { key: 'symbol', label: 'Stock', render: m => <span style={{ color: T.amber, fontWeight: 600 }}>{m.symbol}</span> },
                    ...(['r1', 'r5', 'r21'] as const).map((k, i) => ({
                      key: k, label: ['1D', '1W', '1M'][i], align: 'right' as const, sort: (m: NonNullable<Data['map']>[number]) => m[k] ?? -999,
                      render: (m: NonNullable<Data['map']>[number]) => <span style={{ display: 'inline-block', minWidth: 58, padding: '1px 6px', background: heat(m[k], [3, 6, 12][i]), color: T.bright }}>{pct(m[k], 1)}</span>,
                    })),
                    { key: 'size', label: '₹ cr/day', align: 'right', sort: m => m.size ?? 0, render: m => <span style={{ color: T.muted }}>{num(m.size)}</span> },
                  ]} />
              </div>
            )
          })()}
        </Panel>

        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))' }}>
          <MoverTable title="Top gainers" rows={data.movers.gainers} onSelect={onSelectTicker} sortKey="turnover_cr" accent={T.green} results={resultsToday} day={day} asOf={data.as_of} />
          <MoverTable title="Top losers" rows={data.movers.losers} onSelect={onSelectTicker} sortKey="turnover_cr" accent={T.red} results={resultsToday} day={day} asOf={data.as_of} />
          <MoverTable title="Most active (₹ turnover)" rows={data.movers.most_active} onSelect={onSelectTicker} sortKey="turnover_cr" accent={T.amber} results={resultsToday} day={day} asOf={data.as_of} />
          <MoverTable title="Volume shockers (≥ 3× avg)" rows={data.movers.volume_shockers} onSelect={onSelectTicker} sortKey="vol_x" accent={T.cyan} results={resultsToday} day={day} asOf={data.as_of} />
          <MoverTable title="New 52-week highs" rows={data.movers.new_highs} onSelect={onSelectTicker} sortKey="turnover_cr" accent={T.green} results={resultsToday} day={day} asOf={data.as_of} />
          <MoverTable title="New 52-week lows" rows={data.movers.new_lows} onSelect={onSelectTicker} sortKey="turnover_cr" accent={T.red} results={resultsToday} day={day} asOf={data.as_of} />
        </div>
        <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
          Universe: EQ-series stocks ≥ ₹20 with a 20-day median turnover ≥ ₹1 cr, ETFs excluded (movers need ≥ ₹5 cr). Prices adjusted for splits and
          bonuses, delisted stocks included. Regime score from the SuryaDhana Scanner Handbook; in its backtest, breakouts bought on
          score-4 days did worst, so read it as market health, not a buy signal. Click any stock for its chart.
        </div>
      </div>
    </div>
  )
}
