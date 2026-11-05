'use client'

import { apiError } from '@/lib/errors'
/**
 * RiskDashboard (RSK): portfolio VaR & ES (hist-sim), beta & risk decomposition,
 * sector concentration vs the 40% rule, honest historical stress replays and the
 * drawdown ladder vs the −20% HARD / −2% daily rules (read-only — the rules live
 * in CLAUDE.md and shared/momentum.py).
 *
 * Backend: GET /api/risk/dashboard (services/ui-api/routers/riskdash.py; math in
 * risk_math.py). Book = Desk paper positions + last-known broker holdings (file
 * as-of surfaced). `symbols=` runs an equal-weight WHAT-IF basket for pre-trade
 * checks; the ladder below it stays the real book.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import client, { getDeskStatus } from '@/lib/api'
import { openTicker } from '@/lib/openTicker'
import {
  Btn, Chip, DataTable, Empty, ErrorBox, Grid, KV, Label, Loading, Meter, Notice, PageHeader, Panel, Stat, T,
  fmtInr, fmtSignedPct, tone, type Column, CHART_BOX, useChartSize } from '@/components/terminal'
import { staggerRows, textWidth } from '@/components/terminal/chart'

type Sev = 'ok' | 'warn' | 'crit' | 'na'
interface Excl { symbol: string; reason: string }
interface Holding {
  symbol: string; sources: string[]; sector: string; qty: number | null; value_inr: number
  weight_pct: number | null; beta: number | null; risk_contrib_pct: number | null; in_var_panel: boolean; note: string
}
interface HistBin { x0: number; x1: number; n: number }
interface VarBlock {
  lookback_sessions: number; sessions_used: number; from: string | null; to: string | null
  var95_1d_pct: number | null; var99_1d_pct: number | null; es95_1d_pct: number | null; es99_1d_pct: number | null
  var95_1d_inr: number | null; var99_1d_inr: number | null; es95_1d_inr: number | null; es99_1d_inr: number | null
  var95_5d_pct: number | null; var99_5d_pct: number | null; var95_5d_inr: number | null; var99_5d_inr: number | null
  pct_of_book: { var95_1d: number | null; var99_1d: number | null; var95_5d: number | null; var99_5d: number | null }
  coverage_value_pct: number; excluded: Excl[]; histogram: HistBin[]; policy: string[]
}
interface SectorRow { sector: string; value_inr: number; value_pct: number; positions: number; count_pct: number; breach: boolean }
interface Stress {
  id: string; label: string; start: string; end: string; nifty_pct: number | null; portfolio_pct: number | null
  pnl_inr: number; covered_value_pct: number; worst: { symbol: string; window_return_pct: number } | null; excluded: Excl[]
}
interface Ladder {
  nav: number | null; peak: number | null; drawdown_pct: number | null; stop_nav: number | null
  further_fall_to_stop_pct: number | null; today_return_pct: number | null; room_before_halt_pct: number | null
  emergency_stop_pct: number; daily_halt_pct: number; source: string; today_basis: string; stopped: boolean
  points: { date: string; drawdown_pct: number }[]; rules: string[]
}
interface RiskData {
  as_of: string; mode: 'book' | 'what_if'
  book: {
    nav_inr: number; equity_value_inr: number; desk_nav_inr: number; desk_cash_inr: number
    desk_positions: number; broker_positions: number; broker_equity_inr: number
    broker_as_of: string | null; broker_stale_hours: number | null; stopped: boolean; paper: boolean
  }
  holdings: Holding[]; var: VarBlock
  beta: { portfolio: number | null; index: string; window_sessions: number; method: string; portfolio_sigma_1d_pct: number | null }
  sectors: { cap_pct: number; rule: string; rows: SectorRow[] }
  stress: Stress[]; ladder: Ladder
  severity: { var: Sev; beta: Sev; sector: Sev; dd: Sev; thresholds: Record<string, string> }
  notes: string[]; ok?: boolean; error_info?: { code: string; message: string; hint?: string }
}

const SEV_COLOR: Record<Sev, string> = { ok: T.green, warn: T.amber, crit: T.red, na: T.dim }
const SEV_LABEL: Record<Sev, string> = { ok: 'OK', warn: 'WARN', crit: 'CRIT', na: '—' }

function SevChip({ name, sev, title }: { name: string; sev: Sev; title?: string }) {
  return <Chip color={SEV_COLOR[sev]} active={sev !== 'na'} title={title}>{name} {SEV_LABEL[sev]}</Chip>
}

/** Daily portfolio return histogram with the VaR95/99 loss markers (hand-rolled SVG, kit style). */
function ReturnHistogram({ bins, var95, var99 }: { bins: HistBin[]; var95: number | null; var99: number | null }) {
  const { ref, w, h } = useChartSize(640, 150)   // CSS px (C1-17): 9 px labels at any width
  if (!bins.length) return <Empty title="No return sample" hint="VaR needs per-ticker history from data-service." icon="◌" />
  const L = 8, R = 8, TOP = 8, B = 18
  const lo = bins[0].x0, hi = bins[bins.length - 1].x1, span = hi - lo || 1
  const nMax = Math.max(...bins.map(b => b.n)) || 1
  const x = (v: number) => L + ((v - lo) / span) * (w - L - R)
  const y = (n: number) => TOP + (1 - n / nMax) * (h - TOP - B)
  // VaR95 and VaR99 often sit a few px apart: the second label drops to its own row instead of overlapping
  const marks = [{ v: var95, color: T.amber, label: 'VaR95' }, { v: var99, color: T.red, label: 'VaR99' }]
    .filter(m => m.v != null && -m.v / 100 >= lo && -m.v / 100 <= hi)
  const rows = staggerRows(marks.map(m => ({ x: x(-m.v! / 100) + 3 + textWidth(m.label, 9) / 2, w: textWidth(m.label, 9) })), 4)
  const marker = (i: number) => {
    const { v, color, label } = marks[i]
    const vx = -v! / 100
    return (
      <g key={label}>
        <line x1={x(vx)} x2={x(vx)} y1={TOP} y2={h - B} stroke={color} strokeDasharray="4 3" strokeWidth={1.2} />
        <text x={x(vx) + 3} y={TOP + 9 + rows[i] * 11} fontSize={9} fill={color} fontFamily={T.mono}>{label}</text>
      </g>
    )
  }
  return (
    <div ref={ref} style={CHART_BOX}>
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }} role="img" aria-label="Daily portfolio return histogram">
      {bins.map((b, i) => (
        <rect key={i} x={x(b.x0) + 0.5} width={Math.max(0.5, x(b.x1) - x(b.x0) - 1)} y={y(b.n)} height={h - B - y(b.n)}
          fill={b.x1 <= 0 ? `${T.red}99` : `${T.green}77`} />
      ))}
      <line x1={x(0)} x2={x(0)} y1={TOP} y2={h - B} stroke={T.borderHi} />
      {marks.map((_, i) => marker(i))}
      <text x={L} y={h - 5} fontSize={9} fill={T.dim} fontFamily={T.mono}>{(lo * 100).toFixed(1)}%</text>
      <text x={w - R} y={h - 5} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{(hi * 100).toFixed(1)}%</text>
    </svg>
    </div>
  )
}

/** Horizontal ladder 0 → −25% from peak: current drawdown vs warn/crit zones and the −20% HARD stop. */
function DrawdownLadder({ ladder }: { ladder: Ladder }) {
  const dd = ladder.drawdown_pct
  const SCALE = 25 // % shown
  const pos = (v: number) => `${Math.min(100, Math.max(0, (-v / SCALE) * 100))}%`
  const zones = [
    { from: 0, to: 10, color: `${T.green}33` }, { from: 10, to: 15, color: `${T.amber}33` },
    { from: 15, to: 20, color: `${T.red}33` }, { from: 20, to: SCALE, color: `${T.red}55` },
  ]
  return (
    <div>
      <div style={{ position: 'relative', height: 26, border: `1px solid ${T.border}`, background: T.panel }}>
        {zones.map((z, i) => (
          <div key={i} style={{ position: 'absolute', top: 0, bottom: 0, left: `${(z.from / SCALE) * 100}%`,
            width: `${((z.to - z.from) / SCALE) * 100}%`, background: z.color }} />
        ))}
        <div title="−20% HARD emergency stop" style={{ position: 'absolute', top: 0, bottom: 0, left: pos(-20), width: 2, background: T.red }} />
        {dd != null && (
          <div title={`current drawdown ${fmtSignedPct(dd, 1)}`} style={{ position: 'absolute', top: -3, bottom: -3, left: pos(dd),
            width: 3, background: T.text, boxShadow: `0 0 6px ${T.text}` }} />
        )}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 9, color: T.dim, fontFamily: T.mono, marginTop: 3 }}>
        <span>0% (peak)</span><span>−10%</span><span>−15%</span><span style={{ color: T.red }}>−20% HARD STOP</span><span>−25%</span>
      </div>
    </div>
  )
}

export function RiskDashboard(_: { isDark?: boolean }) {
  const [data, setData] = useState<RiskData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [basket, setBasket] = useState('')          // applied what-if CSV ('' = live book)
  const [draft, setDraft] = useState('')

  const load = useCallback(async (symbols: string, refresh = false) => {
    setLoading(true)
    try {
      const r = await client.get('/api/risk/dashboard', {
        params: { ...(symbols ? { symbols } : {}), ...(refresh ? { refresh: true } : {}) }, timeout: 120000 })
      setData(r.data); setError(null)
    } catch (e: unknown) { setError(apiError(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load(basket) }, [load, basket])

  const loadWatchlist = async () => {
    try {
      const s = (await getDeskStatus()).data
      const plan = s?.plans?.find((p: any) => p.kind === 'REBALANCE' || p.kind === 'EMERGENCY_EXIT')
      const wl: string[] = (plan?.summary?.watchlist ?? []).map((w: any) => w.symbol)
      if (wl.length) { setDraft(wl.join(',')); setBasket(wl.join(',')) }
    } catch { /* desk unavailable: keep the manual input */ }
  }

  const v = data?.var
  const sev = data?.severity
  const ladder = data?.ladder
  const maxSector = data?.sectors.rows.reduce<SectorRow | null>((a, r) => (!a || r.count_pct > a.count_pct ? r : a), null)
  const allCash = data != null && data.mode === 'book' && data.holdings.length === 0

  const holdCols: Column<Holding>[] = [
    { key: 'symbol', label: 'Stock', sort: h => h.symbol, render: h => <span style={{ color: T.amber, fontWeight: 600 }}>{h.symbol}</span> },
    { key: 'src', label: 'Book', sort: h => h.sources.join(), render: h => <span style={{ color: T.muted }}>{h.sources.join(' + ')}</span> },
    { key: 'sector', label: 'Industry', sort: h => h.sector, render: h => <span style={{ color: T.muted }}>{h.sector}</span> },
    { key: 'value', label: 'Value', align: 'right', sort: h => h.value_inr, render: h => fmtInr(h.value_inr) },
    { key: 'w', label: 'Weight', align: 'right', sort: h => h.weight_pct ?? 0, render: h => h.weight_pct != null ? `${h.weight_pct.toFixed(1)}%` : '—' },
    { key: 'beta', label: `β ${data?.beta.window_sessions ?? 250}d`, align: 'right', sort: h => h.beta ?? -9,
      title: 'vs NIFTY50, cov/var of daily returns',
      render: h => h.beta != null ? <span style={{ color: h.beta > 1.5 ? T.red : h.beta > 1.2 ? T.amber : T.text }}>{h.beta.toFixed(2)}</span> : <span style={{ color: T.dim }}>—</span> },
    { key: 'rc', label: 'Risk share', align: 'right', sort: h => h.risk_contrib_pct ?? 0,
      title: 'marginal contribution to portfolio stdev (Euler); shares sum to 100%',
      render: h => h.risk_contrib_pct != null ? `${h.risk_contrib_pct.toFixed(1)}%` : <span style={{ color: T.dim }}>—</span> },
    { key: 'note', label: 'Note', render: h => <span style={{ color: h.in_var_panel ? T.muted : T.amber, whiteSpace: 'normal' }}>{h.note || (h.in_var_panel ? '' : 'excluded from VaR')}</span> },
  ]

  const sectorCols: Column<SectorRow>[] = [
    { key: 'sector', label: 'NSE industry', sort: r => r.sector, render: r => <span style={{ color: r.breach ? T.red : T.text }}>{r.sector}</span> },
    { key: 'pos', label: 'Positions', align: 'right', sort: r => r.positions, render: r => r.positions },
    { key: 'cnt', label: '% of positions', align: 'right', sort: r => r.count_pct, render: r => (
      <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, minWidth: 140 }}>
        <div style={{ flex: 1 }}><Meter value={r.count_pct / (data?.sectors.cap_pct || 40)} color={r.breach ? T.red : r.count_pct >= 0.8 * (data?.sectors.cap_pct || 40) ? T.amber : T.green} /></div>
        <span style={{ color: r.breach ? T.red : T.text }}>{r.count_pct.toFixed(0)}%</span>
      </div>) },
    { key: 'vpct', label: '% of value', align: 'right', sort: r => r.value_pct, render: r => `${r.value_pct.toFixed(1)}%` },
    { key: 'val', label: 'Value', align: 'right', sort: r => r.value_inr, render: r => fmtInr(r.value_inr) },
    { key: 'flag', label: 'Cap', render: r => r.breach ? <Chip color={T.red} active>BREACH &gt; {data?.sectors.cap_pct ?? 40}%</Chip> : <span style={{ color: T.dim }}>within cap</span> },
  ]

  const stressCols: Column<Stress>[] = [
    { key: 'label', label: 'Scenario', render: s => (
      <div><div style={{ color: T.text, fontWeight: 600 }}>{s.label}</div>
        <div style={{ color: T.dim, fontSize: 10, fontFamily: T.mono }}>{s.start} → {s.end}</div></div>) },
    { key: 'nifty', label: 'NIFTY', align: 'right', sort: s => s.nifty_pct ?? 0,
      render: s => <span style={{ color: tone(s.nifty_pct) }}>{fmtSignedPct(s.nifty_pct, 1)}</span> },
    { key: 'port', label: 'This book', align: 'right', sort: s => s.portfolio_pct ?? 0,
      title: 'P&L over the covered value: each holding’s ACTUAL return in the window',
      render: s => <span style={{ color: tone(s.portfolio_pct), fontWeight: 700 }}>{fmtSignedPct(s.portfolio_pct, 1)}</span> },
    { key: 'pnl', label: 'P&L', align: 'right', sort: s => s.pnl_inr, render: s => <span style={{ color: tone(s.pnl_inr) }}>{fmtInr(s.pnl_inr)}</span> },
    { key: 'cov', label: 'Covered', align: 'right', sort: s => s.covered_value_pct,
      title: 'share of book value with history in the window; the rest is excluded, never guessed',
      render: s => <span style={{ color: s.covered_value_pct < 70 ? T.amber : T.muted }}>{s.covered_value_pct.toFixed(0)}%</span> },
    { key: 'worst', label: 'Worst holding', render: s => s.worst
      ? <span><span style={{ color: T.amber, fontWeight: 600 }}>{s.worst.symbol}</span> <span style={{ color: T.red }}>{fmtSignedPct(s.worst.window_return_pct, 1)}</span></span>
      : <span style={{ color: T.dim }}>—</span> },
    { key: 'excl', label: 'Excluded', align: 'right', sort: s => s.excluded.length,
      render: s => s.excluded.length
        ? <span style={{ color: T.amber }} title={s.excluded.map(e => `${e.symbol}: ${e.reason}`).join('\n')}>{s.excluded.length} ⓘ</span>
        : <span style={{ color: T.dim }}>0</span> },
  ]

  const varRows: [ReactNode, ReactNode, string?][] = v ? [
    ['VaR95 · 1 day', <span key="a" style={{ color: T.text }}>{fmtInr(v.var95_1d_inr)} <Label>({v.var95_1d_pct ?? '—'}% eq · {v.pct_of_book.var95_1d ?? '—'}% of book)</Label></span>],
    ['VaR99 · 1 day', <span key="b" style={{ color: T.text }}>{fmtInr(v.var99_1d_inr)} <Label>({v.var99_1d_pct ?? '—'}% eq · {v.pct_of_book.var99_1d ?? '—'}% of book)</Label></span>],
    ['ES95 / ES99 · 1 day', <span key="c" style={{ color: T.text }}>{fmtInr(v.es95_1d_inr)} / {fmtInr(v.es99_1d_inr)} <Label>(mean of the tail days)</Label></span>],
    ['VaR95 · 5 day', <span key="d" style={{ color: T.text }}>{fmtInr(v.var95_5d_inr)} <Label>(√5 × 1d — approximation)</Label></span>],
    ['VaR99 · 5 day', <span key="e" style={{ color: T.text }}>{fmtInr(v.var99_5d_inr)} <Label>(√5 × 1d — approximation)</Label></span>],
    ['Sample', <Label key="f">{v.sessions_used} sessions · {v.from ?? '—'} → {v.to ?? '—'} · {v.coverage_value_pct}% of value covered</Label>],
  ] : []

  return (
    <div>
      <PageHeader code="RSK" title="Risk dashboard"
        status={<>
          <Chip color={T.amber} active>PAPER</Chip>
          {data?.book.stopped ? <Chip color={T.red} active>EMERGENCY STOP</Chip> : null}
          {data?.mode === 'what_if' ? <Chip color={T.cyan} active>WHAT-IF</Chip> : null}
          {sev && <>
            <SevChip name="VAR" sev={sev.var} title={sev.thresholds.var} />
            <SevChip name="BETA" sev={sev.beta} title={sev.thresholds.beta} />
            <SevChip name="SECTOR" sev={sev.sector} title={sev.thresholds.sector} />
            <SevChip name="DD" sev={sev.dd} title={sev.thresholds.dd} />
          </>}
        </>}
        subtitle={<>hist-sim VaR · beta vs NIFTY50 · stress replays · ladder vs the −20% HARD stop
          {data?.book.broker_as_of ? <> · broker book as of {data.book.broker_as_of.slice(0, 16).replace('T', ' ')}{(data.book.broker_stale_hours ?? 0) > 24 ? ' (stale)' : ''}</> : null}</>}
        right={<>
          <input value={draft} onChange={e => setDraft(e.target.value)} placeholder="what-if: SYM1,SYM2,…" spellCheck={false}
            style={{ background: 'transparent', border: `1px solid ${T.border}`, color: T.text, fontFamily: T.mono,
                     fontSize: 11, padding: '5px 8px', width: 220 }} />
          <Btn onClick={() => setBasket(draft.trim())} disabled={!draft.trim() || loading}>▶ What-if</Btn>
          <Btn onClick={loadWatchlist} title="equal-weight the Desk's momentum watchlist">Desk watchlist</Btn>
          {basket && <Btn onClick={() => { setBasket(''); setDraft('') }}>✕ Live book</Btn>}
          <Btn onClick={() => load(basket, true)}>{loading ? 'Loading…' : '↻ Refresh'}</Btn>
        </>} />
      {error && <div style={{ marginBottom: 10 }}><ErrorBox error={error} onRetry={() => load(basket)} /></div>}
      {loading && !data ? <Loading label="Measuring the book" /> : data && (
        <div style={{ display: 'grid', gap: 10 }}>
          <Grid cols={6}>
            <Stat label="VaR95 · 1d" value={fmtInr(v?.var95_1d_inr)} color={SEV_COLOR[sev?.var ?? 'na']}
              sub={v?.pct_of_book.var95_1d != null ? `${v.pct_of_book.var95_1d}% of book` : 'needs holdings'} accent={T.amber} />
            <Stat label="VaR99 · 1d" value={fmtInr(v?.var99_1d_inr)} sub={v?.es99_1d_inr != null ? `ES99 ${fmtInr(v.es99_1d_inr)}` : '—'} />
            <Stat label="Portfolio beta" value={data.beta.portfolio ?? '—'} color={SEV_COLOR[sev?.beta ?? 'na']}
              sub={`vs ${data.beta.index} · ${data.beta.window_sessions}d`} />
            <Stat label="Max industry" value={maxSector ? `${maxSector.count_pct.toFixed(0)}%` : '—'} color={SEV_COLOR[sev?.sector ?? 'na']}
              sub={maxSector ? `${maxSector.sector} · cap ${data.sectors.cap_pct}%` : `cap ${data.sectors.cap_pct}%`} />
            <Stat label="Drawdown" value={fmtSignedPct(ladder?.drawdown_pct, 1)} color={SEV_COLOR[sev?.dd ?? 'na']}
              sub={ladder?.further_fall_to_stop_pct != null ? `${ladder.further_fall_to_stop_pct.toFixed(1)}% to the −20% stop` : '—'} />
            <Stat label="Book NAV" value={fmtInr(data.book.nav_inr)} sub={`equity at risk ${fmtInr(data.book.equity_value_inr)}`} />
          </Grid>

          {allCash && (
            <Notice color={T.amber}>
              The book is ALL CASH today ({fmtInr(data.book.desk_cash_inr)} in the liquid fund) — nothing at market risk.
              Run a <b>what-if basket</b> (input above, or “Desk watchlist”) to measure what the Desk would hold.
            </Notice>
          )}
          {data.mode === 'what_if' && (
            <Notice color={T.cyan}>
              WHAT-IF basket: equal weight on {fmtInr(data.book.nav_inr)} — a pre-trade check, not the live book.
              The drawdown ladder below still tracks the real ledger.
            </Notice>
          )}
          {data.notes.map((n, i) => <Notice key={i} color={T.amber}>{n}</Notice>)}

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)', gap: 10 }}>
            <Panel title="Value at Risk · historical simulation" subtitle={`last ${v?.sessions_used ?? 0} sessions at current weights`}
              right={v?.excluded.length ? <Label color={T.amber}>{v.excluded.length} excluded</Label> : undefined}>
              <div style={{ display: 'grid', gap: 10 }}>
                <ReturnHistogram bins={v?.histogram ?? []} var95={v?.var95_1d_pct ?? null} var99={v?.var99_1d_pct ?? null} />
                <KV items={varRows} />
                {v?.excluded.length ? (
                  <div style={{ fontSize: 10, color: T.amber }}>
                    Excluded from VaR: {v.excluded.map(e => `${e.symbol} (${e.reason})`).join(' · ')}
                  </div>) : null}
                <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.6 }}>{(v?.policy ?? []).map((p, i) => <div key={i}>· {p}</div>)}</div>
              </div>
            </Panel>
            <div style={{ display: 'grid', gap: 10, alignContent: 'start' }}>
              <Panel title="Drawdown ladder" subtitle={ladder?.source}>
                <div style={{ display: 'grid', gap: 10 }}>
                  {ladder && <DrawdownLadder ladder={ladder} />}
                  <KV items={[
                    ['From peak', <span key="1" style={{ color: tone(ladder?.drawdown_pct) }}>{fmtSignedPct(ladder?.drawdown_pct, 2)} <Label>(peak {fmtInr(ladder?.peak)})</Label></span>],
                    ['Emergency stop', <span key="2" style={{ color: T.text }}>NAV {fmtInr(ladder?.stop_nav)} <Label>(−20% from peak · HARD)</Label></span>],
                    ['Distance to stop', <span key="3" style={{ color: (ladder?.further_fall_to_stop_pct ?? 99) < 5 ? T.red : T.text }}>
                      {ladder?.further_fall_to_stop_pct != null ? `a further −${ladder.further_fall_to_stop_pct.toFixed(1)}%` : '—'}</span>],
                    ['Today', <span key="4" style={{ color: tone(ladder?.today_return_pct) }}>{fmtSignedPct(ladder?.today_return_pct, 2)} <Label>({ladder?.today_basis})</Label></span>],
                    ['Room before −2% halt', <span key="5" style={{ color: (ladder?.room_before_halt_pct ?? 9) <= 0.5 ? T.red : T.text }}>
                      {ladder?.room_before_halt_pct != null ? `${ladder.room_before_halt_pct.toFixed(2)}%` : '—'}</span>],
                  ]} />
                  <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.6 }}>
                    {(ladder?.rules ?? []).map((r, i) => <div key={i}>· {r}</div>)}
                    <div style={{ color: T.dim, marginTop: 4 }}>The owner-approved trading rules, displayed here and never modified from this page.</div>
                  </div>
                </div>
              </Panel>
            </div>
          </div>

          <Panel title="Holdings risk" subtitle={`beta vs ${data.beta.index} · risk share = marginal contribution to portfolio σ (sums to 100%)`} pad={0}
            right={data.beta.portfolio_sigma_1d_pct != null ? <Label>portfolio σ {data.beta.portfolio_sigma_1d_pct}%/day</Label> : undefined}>
            {data.holdings.length
              ? <DataTable columns={holdCols} rows={data.holdings} rowKey={h => h.symbol} dense maxHeight={420}
                  onRowClick={h => openTicker(h.symbol)} exportName="risk-holdings" />
              : <Empty title="No equity positions" hint="Desk paper book and broker holdings are both empty." icon="◇" />}
          </Panel>

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.2fr)', gap: 10 }}>
            <Panel title="Sector concentration" subtitle={data.sectors.rule} pad={0}>
              {data.sectors.rows.length
                ? <DataTable columns={sectorCols} rows={data.sectors.rows} rowKey={r => r.sector} dense />
                : <Empty title="No sector exposure" icon="◇" />}
            </Panel>
            <Panel title="Stress replays · honest history" subtitle="each holding’s ACTUAL window return — no Monte-Carlo, no extrapolation" pad={0}>
              <DataTable columns={stressCols} rows={data.stress} rowKey={s => s.id} dense />
            </Panel>
          </div>

          <div style={{ fontSize: 10, color: T.dim }}>
            As of {data.as_of.replace('T', ' ')} · book = Desk paper ledger + broker last-known holdings
            {data.book.broker_as_of ? ` (file as of ${data.book.broker_as_of.replace('T', ' ')})` : ''} · payload cached 120 s · PAPER only.
          </div>
        </div>
      )}
    </div>
  )
}
