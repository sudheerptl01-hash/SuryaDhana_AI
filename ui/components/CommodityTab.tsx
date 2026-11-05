'use client'

import { apiError } from '@/lib/errors'
/**
 * CommodityTab — "Commodity Desk".
 *
 * Surfaces the data sources from docs/PROGRAMMATIC_DATA_ACCESS.md into one tab:
 *   • PRICE board  — global futures (WTI/Brent/gold/silver/copper/Henry-Hub gas)
 *                    via /api/commodity/overview (Yahoo, no key) — the tradeable leg.
 *   • DETAIL chart — /api/commodity/price/{symbol} history for the selected contract.
 *   • FUNDAMENTALS — EIA energy stocks/production + FRED commodity/macro indices
 *                    (FRED through the keyless fredgraph.csv; EIA degrades to a "set the free key" hint).
 *
 * Gold (gold program PLAN §b): the fair-open panel moved to GOLD › HEALTH; the gold tile keeps its place on the board
 * with a GOLD › chip, and its detail chart links to GOLD › WEEKLY. The 43rd page GOLD holds every gold panel.
 *
 * Aesthetic mirrors WarehouseHealth: NSE void terminal — Chakra Petch labels,
 * JetBrains Mono values, void panels, jade/amber/violet accents, corner brackets.
 *
 * ⚠️ Live LATEST values shown for viewing. Backtested commodity factors must use
 * point-in-time vintages (ALFRED for FRED) — see the doc §3.
 */

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Chip, PageHeader, SourceChip, T, fmtPct, sourceOf, type SourceInfo } from '@/components/terminal'
import { ChartActions, futuresInstrument } from '@/components/terminal/ChartActions'
import { goToPage } from '@/lib/navigate'
import { setGoldSubInUrl } from '@/lib/gold/prefs'
import {
  getCommodityOverview,
  getCommodityHistory,
  type CommodityOverview,
  type CommodityQuote,
  type CommodityHistory,
  type CommodityFundamentalsLeg,
} from '@/lib/api'

// ── Palette tokens ──────────────────────────────────────────────────────────────
const PANEL = '#0a0d13'
const BORDER = '#1a2130'
const TXT = '#d6dbe4'
const MUTED = T.muted
const SUB = '#aab3c2'
const JADE = '#16d98a'
const AMBER = '#ffb000'
const VIOLET = '#b58bff'
const CRIMSON = '#ff4d5e'
const CYAN = '#4ACFE8'

const POLL_MS = 60_000

const fmt = (n: number | null | undefined, dp = 2) =>
  n === null || n === undefined || isNaN(n)
    ? '—'
    : n.toLocaleString('en-US', { maximumFractionDigits: dp, minimumFractionDigits: dp })

const fmtTime = (epoch: number | null | undefined) =>
  !epoch ? '—' : new Date(epoch * 1000).toLocaleString('en-IN', { hour12: false })

// ── Panel shell (corner brackets) ───────────────────────────────────────────────
function Panel({
  title, hint, accent = MUTED, children, className, style, source,
}: {
  title?: string; hint?: string; accent?: string
  children: React.ReactNode; className?: string; style?: React.CSSProperties
  /** PLAN §0.5 / 1.4: the source chip (staleness never only in prose) */
  source: SourceInfo
}) {
  return (
    <div
      className={`relative overflow-hidden rounded-lg ${className ?? ''}`}
      style={{ background: PANEL, border: `1px solid ${BORDER}`, ...style }}
    >
      <span className="pointer-events-none absolute right-1.5 top-1.5 h-2.5 w-2.5 opacity-25"
            style={{ borderTop: `1px solid ${accent}`, borderRight: `1px solid ${accent}` }} />
      <span className="pointer-events-none absolute bottom-1.5 left-1.5 h-2.5 w-2.5 opacity-25"
            style={{ borderBottom: `1px solid ${accent}`, borderLeft: `1px solid ${accent}` }} />
      {title && (
        <div className="flex items-baseline justify-between px-4 pt-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.2em]"
              style={{ fontFamily: "'Chakra Petch', sans-serif", color: accent }}>{title}</h3>
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            {hint && <span className="text-[9px] tracking-wider" style={{ color: MUTED }}>{hint}</span>}
            <SourceChip info={source} />
          </span>
        </div>
      )}
      {children}
    </div>
  )
}

// ── Inline SVG sparkline (dependency-free) ──────────────────────────────────────
function Sparkline({ data, color, w = 120, h = 34 }: { data: number[]; color: string; w?: number; h?: number }) {
  if (!data || data.length < 2) return <div style={{ width: w, height: h }} />
  const min = Math.min(...data)
  const max = Math.max(...data)
  const span = max - min || 1
  const step = w / (data.length - 1)
  const pts = data.map((v, i) => `${(i * step).toFixed(1)},${(h - ((v - min) / span) * h).toFixed(1)}`).join(' ')
  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline points={pts} fill="none" stroke={color} strokeWidth={1.4}
                strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

// ── Inline SVG line chart for the selected contract ─────────────────────────────
function useWidth(initial = 760): [(el: HTMLDivElement | null) => void, number] {
  const [w, setW] = useState(initial)
  const ref = useCallback((el: HTMLDivElement | null) => {
    if (!el) return
    const ro = new ResizeObserver(entries => setW(Math.max(200, Math.round(entries[0].contentRect.width))))
    ro.observe(el)
  }, [])
  return [ref, w]
}

function DetailChart({ closes, color, unit }: { closes: number[]; color: string; unit: string }) {
  const [boxRef, W] = useWidth()
  return <div ref={boxRef} style={{ width: '100%' }}><DetailChartSvg closes={closes} color={color} unit={unit} W={W} /></div>
}

function DetailChartSvg({ closes, color, unit, W }: { closes: number[]; color: string; unit: string; W: number }) {
  const H = 260, PAD = 8
  if (!closes || closes.length < 2) {
    return <div className="flex h-[260px] items-center justify-center text-[11px]" style={{ color: MUTED }}>no series</div>
  }
  const min = Math.min(...closes)
  const max = Math.max(...closes)
  const span = max - min || 1
  const step = (W - PAD * 2) / (closes.length - 1)
  const y = (v: number) => PAD + (H - PAD * 2) - ((v - min) / span) * (H - PAD * 2)
  const line = closes.map((v, i) => `${(PAD + i * step).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const area = `${PAD},${H - PAD} ${line} ${(PAD + (closes.length - 1) * step).toFixed(1)},${H - PAD}`
  const gridVals = [max, (max + min) / 2, min]
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" style={{ height: H }}>
      {gridVals.map((g, i) => (
        <g key={i}>
          <line x1={PAD} x2={W - PAD} y1={y(g)} y2={y(g)} stroke={BORDER} strokeWidth={1} strokeDasharray="2 4" />
          <text x={W - PAD} y={y(g) - 3 < 10 ? y(g) + 11 : y(g) - 3} textAnchor="end" fontSize={9}
                fill={MUTED} fontFamily="'JetBrains Mono', monospace">{fmt(g)} {unit}</text>
        </g>
      ))}
      <polyline points={area} fill={color} opacity={0.08} stroke="none" />
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.6} strokeLinejoin="round" />
    </svg>
  )
}

// ── Fundamentals leg (FRED / EIA) ───────────────────────────────────────────────
function FundamentalsLeg({ title, accent, leg, envVar }: {
  title: string; accent: string; leg: CommodityFundamentalsLeg; envVar?: string
}) {
  return (
    <Panel title={title} accent={accent} hint={leg.available ? undefined : envVar ? 'key required' : 'unavailable'}
      source={leg.available ? sourceOf(leg.series.map(x => x.latest?.date ?? '').filter(Boolean).sort().pop() ?? null, { source: title.split(' ')[0], maxAgeDays: 45 })
        : sourceOf(null, { source: title.split(' ')[0], hint: leg.reason ?? (envVar ? `${envVar} not set` : 'did not answer') })}>
      <div className="p-4">
        {!leg.available ? (
          <div className="rounded-md border border-dashed px-3 py-4 text-[11px] leading-relaxed"
               style={{ borderColor: BORDER, color: SUB }}>
            <span style={{ color: AMBER }}>◷ {envVar ? 'Not enabled.' : 'Unavailable.'}</span>{' '}
            {leg.reason ?? (envVar ? `Set ${envVar} in .env to enable.` : 'The keyless FRED CSV did not answer; retry in a minute.')}
            {envVar && (
              <div className="mt-2 font-mono text-[10px]" style={{ color: MUTED }}>
                export {envVar}=… &nbsp;(free key) → restart ui-api
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {leg.series.map((s) => {
              const pts = s.points?.map((p) => p.value) ?? []
              const up = pts.length >= 2 && pts[pts.length - 1] >= pts[0]
              return (
                <div key={s.id} className="rounded-md px-3 py-2" style={{ background: '#040A14', border: `1px solid ${BORDER}` }}>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase tracking-wider" style={{ fontFamily: "'Chakra Petch', sans-serif", color: SUB }}>{s.label}</span>
                    <Sparkline data={pts} color={up ? JADE : CRIMSON} w={70} h={20} />
                  </div>
                  <div className="mt-1 flex items-baseline justify-between">
                    <span className="text-[15px] font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: TXT }}>
                      {s.error ? '—' : fmt(s.latest?.value)}
                    </span>
                    <span className="text-[9px]" style={{ color: MUTED }}>
                      {s.error ? <span style={{ color: CRIMSON }}>err</span> : `${s.unit} · ${s.latest?.date ?? ''}`}
                    </span>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Panel>
  )
}

// ── Main component ───────────────────────────────────────────────────────────────
export function CommodityTab(_props: { isDark?: boolean }) {
  const [data, setData] = useState<CommodityOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [history, setHistory] = useState<CommodityHistory | null>(null)
  const [histLoading, setHistLoading] = useState(false)

  const loadOverview = useCallback(async () => {
    try {
      const res = await getCommodityOverview()
      setData(res.data)
      setErr(null)
      if (!selected && res.data.futures.length) setSelected(res.data.futures[0].symbol)
    } catch (e: any) {
      setErr(apiError(e, 'failed to load commodity overview'))
    } finally {
      setLoading(false)
    }
  }, [selected])

  useEffect(() => {
    loadOverview()
    const id = setInterval(loadOverview, POLL_MS)
    return () => clearInterval(id)
  }, [loadOverview])

  useEffect(() => {
    if (!selected) return
    let cancelled = false
    setHistLoading(true)
    getCommodityHistory(selected, '6mo', '1d')
      .then((res) => { if (!cancelled) setHistory(res.data) })
      .catch(() => { if (!cancelled) setHistory(null) })
      .finally(() => { if (!cancelled) setHistLoading(false) })
    return () => { cancelled = true }
  }, [selected])

  const selectedQuote = useMemo(
    () => data?.futures.find((f) => f.symbol === selected) ?? null,
    [data, selected],
  )
  const closes = useMemo(
    () => (history?.candles ?? []).map((c) => c.c).filter((c): c is number => c !== null),
    [history],
  )

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-700/50 bg-slate-900/60 p-8 text-center text-sm" style={{ color: SUB }}>
        Loading commodity desk…
      </div>
    )
  }

  const staleN = (data?.futures ?? []).filter(q => q.stale).length
  const boardSrc: SourceInfo = sourceOf(data?.as_of ? new Date(data.as_of * 1000).toISOString() : null,
    { source: 'Yahoo (USD futures)', maxAgeDays: 4, degraded: staleN > 0, hint: staleN ? `${staleN} of ${data?.futures.length ?? 0} quotes stale` : null })

  return (
    <div>
      {/* Header */}
      <PageHeader code="CMDT" title="Commodities"
        subtitle="global futures (USD) · EIA energy fundamentals · FRED context · gold lives on GOLD"
        right={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: MUTED }}>updated {fmtTime(data?.as_of)}</span>
          {/* PLAN 1.4: the board's own chip — STALE when any quote is stale (was a muted colour only) */}
          <SourceChip info={boardSrc} />
        </span>} />

      {err && (
        <div className="mb-3 rounded-md px-3 py-2 text-[11px]" style={{ background: '#1a0b0d', border: `1px solid ${CRIMSON}`, color: CRIMSON }}>
          {err}
        </div>
      )}

      {/* Futures board */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-6">
        {(data?.futures ?? []).map((q: CommodityQuote) => {
          const up = (q.change_pct ?? 0) >= 0
          const accent = q.stale ? MUTED : up ? JADE : CRIMSON
          const isSel = q.symbol === selected
          return (
            <button
              key={q.symbol}
              onClick={() => setSelected(q.symbol)}
              className="group rounded-lg px-3 py-2.5 text-left transition"
              style={{
                background: isSel ? '#0A1525' : PANEL,
                border: `1px solid ${isSel ? accent : BORDER}`,
              }}
            >
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase tracking-wider" style={{ fontFamily: "'Chakra Petch', sans-serif", color: SUB }}>{q.label}</span>
                {q.symbol === 'GC=F'
                  ? <span role="button" tabIndex={0} data-gold-chip title="Open the gold terminal (health, positioning, physical, macro, contracts)"
                      onClick={e => { e.stopPropagation(); setGoldSubInUrl('health'); goToPage('gold') }}
                      onKeyDown={e => { if (e.key === 'Enter') { e.stopPropagation(); setGoldSubInUrl('health'); goToPage('gold') } }}
                      style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, letterSpacing: 1, color: AMBER, border: `1px solid ${AMBER}`, padding: '1px 5px' }}>GOLD ›</span>
                  : <span className="text-[8px]" style={{ color: MUTED }}>{q.category}</span>}
              </div>
              <div className="mt-1 text-[18px] font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: q.stale ? MUTED : TXT }}>
                {fmt(q.price)}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-semibold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: accent }}>
                  {q.change_pct === null ? '—' : fmtPct(q.change_pct, 2)}
                </span>
                <Sparkline data={q.spark} color={accent} w={56} h={18} />
              </div>
              <div className="mt-0.5 text-[8px]" style={{ color: MUTED }}>{q.unit}{q.stale && <span style={{ color: AMBER, marginLeft: 6, letterSpacing: 1 }} data-cmdt-stale title={`last quote ${fmtTime(q.as_of)}`}>STALE</span>}</div>
            </button>
          )
        })}
      </div>

      {/* Detail chart for selected contract */}
      <Panel
        title={selectedQuote ? `${selectedQuote.label} · 6M` : 'Detail'}
        accent={CYAN}
        hint={selectedQuote ? `${selectedQuote.unit} · ${selectedQuote.symbol}` : ''}
        source={sourceOf(selectedQuote?.as_of ? new Date(selectedQuote.as_of * 1000).toISOString() : null, { source: 'Yahoo (USD futures)', maxAgeDays: 4, hint: selectedQuote?.stale ? 'quote marked stale by the feed' : null })}
        className="mb-4"
      >
        <div className="px-3 pb-3 pt-1">
          {selectedQuote && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <ChartActions instrument={futuresInstrument(selectedQuote.symbol)} name={selectedQuote.label} from="Commodity" />
              {selectedQuote.symbol === 'GC=F' && (
                <Chip color={AMBER} onClick={() => { setGoldSubInUrl('weekly'); goToPage('gold') }} title="60 sessions of candles with the MCX settle, the week table and the 26-week grid">GOLD › WEEKLY</Chip>
              )}
            </div>
          )}
          {histLoading ? (
            <div className="flex h-[260px] items-center justify-center text-[11px]" style={{ color: MUTED }}>loading series…</div>
          ) : (
            <DetailChart
              closes={closes}
              color={(selectedQuote?.change_pct ?? 0) >= 0 ? JADE : CRIMSON}
              unit={selectedQuote?.unit ?? ''}
            />
          )}
        </div>
      </Panel>

      {/* Fundamentals legs */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {data?.fundamentals?.fred && (
          <FundamentalsLeg title="FRED · Commodity / Macro" accent={VIOLET} leg={data.fundamentals.fred} />
        )}
        {data?.fundamentals?.eia && (
          <FundamentalsLeg title="EIA · Energy Fundamentals" accent={AMBER} leg={data.fundamentals.eia} envVar="EIA_API_KEY" />
        )}
      </div>

      {/* Discipline footnote */}
      <div className="mt-4 rounded-md px-3 py-2 text-[10px] leading-relaxed" style={{ background: '#040A14', border: `1px solid ${BORDER}`, color: MUTED }}>
        <span style={{ color: SUB }}>Note:</span> live LATEST values shown for viewing — correct for a dashboard.
        Any <em>backtested</em> commodity factor must use point-in-time vintages (ALFRED for FRED legs) to avoid
        look-ahead bias. Price feed: global futures (Yahoo, USD). See <code>docs/PROGRAMMATIC_DATA_ACCESS.md</code>.
      </div>
    </div>
  )
}

export default CommodityTab
