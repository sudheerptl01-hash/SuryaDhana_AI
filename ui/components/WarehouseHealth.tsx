'use client'

import { apiError } from '@/lib/errors'
/**
 * WarehouseHealth — "Data Warehouse & ML Health" console.
 *
 * Surfaces three previously-dark DuckDB backend endpoints that had no UI:
 *   • GET /api/data/db/stats       — warehouse coverage, freshness, enrichment
 *   • GET /api/data/db/ml-stats    — ML feature/label rows + class balance
 *   • GET /api/data/db/ohlcv-meta  — per-ticker data-quality grid
 *
 * Aesthetic: NSE void terminal. Chakra Petch labels, JetBrains Mono values,
 * #05070a/#0a0d13 voids, amber/jade/violet/crimson accents. Corner brackets,
 * scanline header, staggered panel reveal.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BadgeChip, Btn, Chip, PageHeader, SourceChip, T, fmtNum, fmtSigned, sourceOf, type SourceInfo } from '@/components/terminal'
import { NseDatasets } from './NseDatasets'
import { CatalogNote } from '@/components/CatalogNote'
import { getDataHealth, staleCount, type DataHealth } from '@/components/datahealth/api'
import { goToPage } from '@/lib/navigate'
import clsx from 'clsx'
import { QuantKPICard } from './QuantKPICard'
import { getWarehouseStats, getWarehouseOhlcvMeta, getWarehouseMlStats } from '@/lib/api'

// ── Types (mirror the backend response contracts) ───────────────────────────────
interface WarehouseStats {
  total_stocks: number
  latest_date: string | null
  days_stale: number | null
  data_range: { from: string | null; to: string | null }
  freshness: { fresh: number; stale: number; very_stale: number; fresh_pct: number }
  enrichment: {
    enriched: number; total: number; enrichment_pct: number
    with_fundamentals: number; with_dividends: number; with_splits: number
  }
  health: { status: string; freshness_pct: number }
}

interface MlStats {
  features: { rows: number; tickers: number; latest_date: string | null }
  labels: {
    rows: number; tickers: number; latest_date: string | null
    up_labels: number; down_labels: number; class_balance_pct: number
    avg_return_pct: number; std_return_pct: number
  }
}

interface OhlcvMetaRow {
  ticker: string
  latest_price: number | null
  price_date: string | null
  total_rows: number
  first_date: string | null
  latest_date: string | null
  years_of_data: number
  data_density_pct: number
  days_since_update: number | null
  sessions_behind?: number | null
  mktcap_cr?: number | null
}

// ── Palette tokens ──────────────────────────────────────────────────────────────
const VOID = '#05070a'
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

// ── Quality classification for a ticker's coverage row ──────────────────────────
type Quality = { label: string; color: string }
// `behind` = trading sessions behind the newest session in the warehouse (0 = current).
function classify(density: number, behind: number | null): Quality {
  const d = behind ?? 999
  if (density >= 90 && d <= 1) return { label: 'EXCELLENT', color: JADE }
  if (density >= 75 && d <= 5) return { label: 'GOOD', color: CYAN }
  if (density >= 50) return { label: 'FAIR', color: AMBER }
  return { label: 'POOR', color: CRIMSON }
}

const fmt = fmtNum

// ── Reusable terminal panel shell ───────────────────────────────────────────────
function Panel({
  title, hint, accent = MUTED, children, className, style, source,
}: {
  title?: string; hint?: string; accent?: string
  children: React.ReactNode; className?: string; style?: React.CSSProperties
  /** PLAN §0.5 / 1.4: the source chip on every panel header */
  source: SourceInfo
}) {
  return (
    <div
      className={clsx('relative overflow-hidden rounded-lg', className)}
      style={{ background: PANEL, border: `1px solid ${BORDER}`, ...style }}
    >
      {/* corner brackets */}
      <span className="pointer-events-none absolute right-1.5 top-1.5 h-2.5 w-2.5 opacity-25"
            style={{ borderTop: `1px solid ${accent}`, borderRight: `1px solid ${accent}` }} />
      <span className="pointer-events-none absolute bottom-1.5 left-1.5 h-2.5 w-2.5 opacity-25"
            style={{ borderBottom: `1px solid ${accent}`, borderLeft: `1px solid ${accent}` }} />
      {title && (
        <div className="flex items-baseline justify-between px-5 pt-4">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.2em]"
              style={{ fontFamily: "'Chakra Petch', sans-serif", color: accent }}>
            {title}
          </h3>
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            {hint && (
              <span className="text-[9px] tracking-wider" style={{ color: MUTED }}>{hint}</span>
            )}
            <SourceChip info={source} />
          </span>
        </div>
      )}
      {children}
    </div>
  )
}

// ── Horizontal coverage bar ─────────────────────────────────────────────────────
function CoverageBar({ label, value, total, color }: { label: string; value: number; total: number; color: string }) {
  const pct = total > 0 ? Math.min(100, (value / total) * 100) : 0
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider"
              style={{ fontFamily: "'Chakra Petch', sans-serif", color: SUB }}>{label}</span>
        <span className="text-[11px] font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: TXT }}>
          {fmt(value)}<span style={{ color: MUTED }}> / {fmt(total)}</span>
          <span className="ml-1.5" style={{ color }}>{pct.toFixed(0)}%</span>
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-sm" style={{ background: '#131926' }}>
        <div className="h-full rounded-sm transition-all duration-700"
             style={{ width: `${pct}%`, background: color, boxShadow: `0 0 8px ${color}66` }} />
      </div>
    </div>
  )
}

// ── Sortable column header ──────────────────────────────────────────────────────
type SortKey = 'ticker' | 'total_rows' | 'years_of_data' | 'data_density_pct' | 'sessions_behind' | 'latest_price'
function Th({
  label, col, sortKey, sortDir, onSort, align = 'right', width,
}: {
  label: string; col: SortKey; sortKey: SortKey; sortDir: 'asc' | 'desc'
  onSort: (k: SortKey) => void; align?: 'left' | 'right'; width?: string
}) {
  const active = sortKey === col
  return (
    <th
      onClick={() => onSort(col)}
      className={clsx('cursor-pointer select-none px-3 py-2 text-[9px] font-semibold uppercase tracking-widest transition-colors',
        align === 'right' ? 'text-right' : 'text-left')}
      style={{ fontFamily: "'Chakra Petch', sans-serif", color: active ? AMBER : MUTED, width }}
    >
      {label}
      <span className="ml-1" style={{ opacity: active ? 1 : 0.25 }}>{active ? (sortDir === 'asc' ? '▲' : '▼') : '↕'}</span>
    </th>
  )
}

// ── Main component ──────────────────────────────────────────────────────────────
export function WarehouseHealth({ isDark = true }: { isDark?: boolean }) {
  const [stats, setStats] = useState<WarehouseStats | null>(null)
  const [ml, setMl] = useState<MlStats | null>(null)
  const [meta, setMeta] = useState<OhlcvMetaRow[]>([])
  const [loading, setLoading] = useState(true)
  const [metaLoading, setMetaLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [syncedAt, setSyncedAt] = useState<Date | null>(null)

  // table controls
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('total_rows')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [visible, setVisible] = useState(80)

  const load = useCallback(async () => {
    setLoading(true)
    setMetaLoading(true)
    setError(null)
    // stats + ml-stats are fast; ohlcv-meta is a heavy scan (cached 5min) — load separately
    try {
      const [s, m] = await Promise.all([getWarehouseStats(), getWarehouseMlStats()])
      setStats(s.data)
      setMl(m.data)
      setSyncedAt(new Date())
    } catch (err: any) {
      setError(apiError(err, 'data-service unreachable'))
    } finally {
      setLoading(false)
    }
    try {
      const om = await getWarehouseOhlcvMeta()
      setMeta(om.data?.data || [])
    } catch {
      /* meta is best-effort — surface stats even if the heavy scan times out */
    } finally {
      setMetaLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const onSort = (k: SortKey) => {
    if (k === sortKey) setSortDir(d => (d === 'asc' ? 'desc' : 'asc'))
    else { setSortKey(k); setSortDir(k === 'ticker' ? 'asc' : 'desc') }
    setVisible(80)
  }

  const filteredSorted = useMemo(() => {
    const q = search.trim().toUpperCase()
    let rows = q ? meta.filter(r => r.ticker.toUpperCase().includes(q)) : meta
    rows = [...rows].sort((a, b) => {
      const av = (a as any)[sortKey] ?? (sortKey === 'ticker' ? '' : -1)
      const bv = (b as any)[sortKey] ?? (sortKey === 'ticker' ? '' : -1)
      const cmp = typeof av === 'string' ? av.localeCompare(bv) : av - bv
      return sortDir === 'asc' ? cmp : -cmp
    })
    return rows
  }, [meta, search, sortKey, sortDir])

  // freshness of every catalogued dataset (trading-day aware), for the header chip (m114)
  const [dataHealth, setDataHealth] = useState<DataHealth | null>(null)
  useEffect(() => { getDataHealth().then(r => setDataHealth(r.data)).catch(() => setDataHealth(null)) }, [syncedAt])

  const totalRows = useMemo(() => meta.reduce((s, r) => s + (r.total_rows || 0), 0), [meta])
  const staleTickers = useMemo(() => meta.filter(r => (r.sessions_behind ?? 0) > 5).length, [meta])

  // ── Loading skeleton ──────────────────────────────────────────────────────────
  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-4">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-5">
          {Array(5).fill(0).map((_, i) => (
            <div key={i} className="h-28 animate-pulse rounded-lg" style={{ background: PANEL, border: `1px solid ${BORDER}` }} />
          ))}
        </div>
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="h-64 animate-pulse rounded-lg" style={{ background: PANEL, border: `1px solid ${BORDER}` }} />
          <div className="h-64 animate-pulse rounded-lg" style={{ background: PANEL, border: `1px solid ${BORDER}` }} />
        </div>
      </div>
    )
  }

  // ── Error state ───────────────────────────────────────────────────────────────
  if (error && !stats) {
    return (
      <Panel source={sourceOf(null, { source: 'data-service', hint: error })} accent={CRIMSON} className="py-20">
        <div className="flex flex-col items-center justify-center gap-5 text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full text-2xl"
               style={{ background: 'rgba(255,59,71,0.08)', border: '1px solid rgba(255,59,71,0.2)' }}>⚠</div>
          <div>
            <p className="text-base font-bold tracking-wider" style={{ fontFamily: "'Chakra Petch', sans-serif", color: TXT }}>
              WAREHOUSE UNREACHABLE
            </p>
            <p className="mt-1 text-xs" style={{ color: MUTED }}>{error} — data-service may be offline</p>
          </div>
          <button onClick={load}
                  className="rounded-lg px-5 py-2 text-xs font-semibold tracking-wider transition-all hover:brightness-125"
                  style={{ background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: AMBER, fontFamily: "'Chakra Petch', sans-serif" }}>
            RETRY
          </button>
        </div>
      </Panel>
    )
  }

  // The warehouse status says whether the tables are POPULATED (coverage); whether they are on time is the data-health
  // catalog's call (the header's DATA n STALE chip, SYS › DATA). Two words for two questions (m114).
  const rawStatus = (stats?.health?.status || 'unknown').toUpperCase()
  const healthStatus = rawStatus === 'HEALTHY' ? 'POPULATED' : rawStatus === 'WARNING' ? 'PARTLY POPULATED' : rawStatus
  const healthColor =
    rawStatus === 'HEALTHY' ? JADE :
    rawStatus === 'WARNING' ? AMBER :
    rawStatus === 'EMPTY' ? MUTED : CRIMSON
  const nStale = dataHealth ? staleCount(dataHealth) : null

  const fresh = stats?.freshness?.fresh ?? 0
  const stale = stats?.freshness?.stale ?? 0
  const aged = stats?.freshness?.very_stale ?? 0
  const freshDen = Math.max(1, fresh + stale + aged)

  const upPct = ml?.labels?.class_balance_pct ?? 0
  const dnPct = 100 - upPct
  const avgRet = ml?.labels?.avg_return_pct ?? 0
  const skew = Math.abs(upPct - 50)

  return (
    <>
    <style>{`
        @keyframes whReveal { from { opacity:0; transform: translateY(8px) } to { opacity:1; transform: translateY(0) } }
        .wh-root > * { animation: whReveal .5s ease-out both }
        .wh-root > *:nth-child(1){ animation-delay:.04s } .wh-root > *:nth-child(2){ animation-delay:.10s }
        .wh-root > *:nth-child(3){ animation-delay:.16s } .wh-root > *:nth-child(4){ animation-delay:.22s }
        @keyframes whScan { 0%{ transform: translateX(-100%) } 100%{ transform: translateX(220%) } }
      `}</style>
    <div className="space-y-3 wh-root">

      <PageHeader code="WHSE" title="Data Warehouse & ML Health"
        status={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <Chip color={healthColor} active title="Coverage: the stored tables are populated. On time or not is the freshness question: see the chip beside it.">{healthStatus}</Chip>
          {nStale != null && (
            <Chip color={nStale > 0 ? AMBER : JADE} onClick={() => goToPage('system')}
              title="Freshness per catalogued dataset (stored vs expected, trading-day aware): SYS › DATA">
              {nStale > 0 ? `DATA ${nStale} STALE` : 'DATA ON TIME'} · SYS ›</Chip>
          )}
        </span>}
        subtitle="DuckDB coverage · per-ticker quality · ML dataset class balance"
        right={<>
          {syncedAt && <span style={{ fontSize: 10, color: MUTED }}>synced {syncedAt.toLocaleTimeString('en-IN', { hour12: false })}</span>}
          <Btn size="sm" onClick={load}>↻ Sync</Btn>
        </>} />

      {/* ── KPI row ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
        <QuantKPICard label="Tickers in DB" value={stats?.total_stocks ?? 0} animate accent="indigo" icon="⊞"
                      subtext={`${fmt(stats?.enrichment?.enrichment_pct, 0)}% enriched`} />
        <QuantKPICard label="OHLCV Rows" value={metaLoading ? '…' : totalRows} animate accent="cyan" icon="≣"
                      subtext={metaLoading ? 'scanning…' : `${fmt(meta.length)} series`} />
        <QuantKPICard label="Latest Session" value={stats?.latest_date ?? '—'} accent={(stats?.freshness?.fresh_pct ?? 0) >= 95 ? 'jade' : 'amber'} icon="▦"
                      subtext={`${stats?.freshness?.fresh_pct ?? '—'}% of tickers current`} />
        <QuantKPICard label="ML Features" value={ml?.features?.rows ?? 0} animate accent="violet" icon="◇"
                      subtext={`${fmt(ml?.features?.tickers)} tickers`} />
        <QuantKPICard label="ML Labels" value={ml?.labels?.rows ?? 0} animate accent="amber" icon="◆"
                      subtext={`bal ${fmt(upPct, 0)}% up`} />
      </div>

      {/* ── Coverage + ML dataset ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">

        {/* Coverage panel */}
        <Panel source={sourceOf(syncedAt ? syncedAt.toISOString() : null, { source: 'data-service' })} title="Warehouse Coverage" hint="enrichment · freshness" accent={JADE}>
          <div className="space-y-4 px-5 pb-5 pt-4">
            <CoverageBar label="Fundamentals snapshot (one undated record each)" value={stats?.enrichment?.with_fundamentals ?? 0} total={stats?.total_stocks ?? 0} color={JADE} />
            <p className="-mt-2 text-[10px] leading-snug" style={{ color: MUTED }}>
              A record exists per ticker, but it is a single undated snapshot, so the 15 fundamental columns of ml_features are NULL on every
              dated row (point-in-time). DEXP shows them empty for that reason.
            </p>
            <CoverageBar label="Dividends" value={stats?.enrichment?.with_dividends ?? 0} total={stats?.total_stocks ?? 0} color={CYAN} />
            <CoverageBar label="Splits" value={stats?.enrichment?.with_splits ?? 0} total={stats?.total_stocks ?? 0} color={VIOLET} />

            {/* Freshness segmented bar */}
            <div className="pt-1">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ fontFamily: "'Chakra Petch', sans-serif", color: SUB }}>
                  Freshness
                </span>
                <span className="text-[11px] font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: JADE }}>
                  {fmt(stats?.freshness?.fresh_pct, 1)}% fresh
                </span>
              </div>
              <div className="flex h-2 w-full overflow-hidden rounded-sm" style={{ background: '#131926' }}>
                <div className="h-full transition-all duration-700" style={{ width: `${(fresh / freshDen) * 100}%`, background: JADE }} />
                <div className="h-full transition-all duration-700" style={{ width: `${(stale / freshDen) * 100}%`, background: AMBER }} />
                <div className="h-full transition-all duration-700" style={{ width: `${(aged / freshDen) * 100}%`, background: CRIMSON }} />
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2">
                {[
                  { k: 'CURRENT', v: fresh, c: JADE, s: 'latest session' },
                  { k: 'BEHIND', v: stale, c: AMBER, s: '1–5 sessions' },
                  { k: 'AGED', v: aged, c: CRIMSON, s: '>5 sessions' },
                ].map(({ k, v, c, s }) => (
                  <div key={k} className="rounded p-2 text-center" style={{ background: `${c}0d`, border: `1px solid ${c}26` }}>
                    <p className="text-lg font-black tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: c }}>{fmt(v)}</p>
                    <p className="text-[8px] font-semibold tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: c }}>{k}</p>
                    <p className="text-[8px]" style={{ color: MUTED }}>{s}</p>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Panel>

        {/* ML dataset panel */}
        <Panel source={sourceOf(ml?.labels?.latest_date ?? null, { source: 'ml_labels (dormant)', maxAgeDays: null })} title="ML Dataset · Class Balance" hint={ml?.labels?.latest_date ? `as of ${ml.labels.latest_date}` : 'no labels yet'} accent={VIOLET}>
          <div className="space-y-4 px-5 pb-5 pt-4">
            <CatalogNote id="reports/ml_labels/FINDINGS.md" fallback="FAIL" showTakeaway={false}>
              These are the production v2 5-day labels (close 5 sessions ahead &gt; +0.15 %); the label study marks them FAIL. The counts
              describe the stored table, not a usable target.
            </CatalogNote>
            <div className="-mt-2 flex items-center gap-2 text-[10px]" style={{ color: MUTED }}>
              <BadgeChip badge="arithmetic" note="Counts and moments of the stored labels." /> labels end 5 sessions before the features: a forward label needs 5 future sessions
            </div>
            {/* feature/label counts */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded p-3" style={{ background: 'rgba(160,96,255,0.05)', border: '1px solid rgba(160,96,255,0.18)' }}>
                <p className="text-[9px] font-semibold tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: MUTED }}>FEATURE ROWS</p>
                <p className="text-2xl font-black tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: VIOLET }}>{fmt(ml?.features?.rows)}</p>
                <p className="text-[9px]" style={{ color: SUB }}>{fmt(ml?.features?.tickers)} tickers · {ml?.features?.latest_date ?? '—'}</p>
              </div>
              <div className="rounded p-3" style={{ background: 'rgba(245,166,35,0.05)', border: '1px solid rgba(245,166,35,0.18)' }}>
                <p className="text-[9px] font-semibold tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: MUTED }}>LABEL ROWS</p>
                <p className="text-2xl font-black tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: AMBER }}>{fmt(ml?.labels?.rows)}</p>
                <p className="text-[9px]" style={{ color: SUB }}>{fmt(ml?.labels?.tickers)} tickers · {ml?.labels?.latest_date ?? '—'}</p>
              </div>
            </div>

            {/* diverging class-balance bar */}
            <div>
              <div className="mb-1.5 flex items-center justify-between text-[10px]">
                <span className="font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: JADE }}>▲ UP {fmt(ml?.labels?.up_labels)}</span>
                <span className="font-semibold uppercase tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: skew > 15 ? CRIMSON : MUTED }}>
                  {skew > 15 ? `SKEW ${skew.toFixed(0)}%` : 'BALANCED'}
                </span>
                <span className="font-bold tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: CRIMSON }}>{fmt(ml?.labels?.down_labels)} DOWN ▼</span>
              </div>
              <div className="relative flex h-6 w-full overflow-hidden rounded-sm" style={{ background: '#131926' }}>
                <div className="flex h-full items-center justify-start pl-2 transition-all duration-700"
                     style={{ width: `${upPct}%`, background: `linear-gradient(90deg, ${JADE}cc, ${JADE}66)` }}>
                  <span className="text-[10px] font-black tabular-nums" style={{ color: VOID }}>{upPct.toFixed(1)}%</span>
                </div>
                <div className="flex h-full items-center justify-end pr-2 transition-all duration-700"
                     style={{ width: `${dnPct}%`, background: `linear-gradient(90deg, ${CRIMSON}66, ${CRIMSON}cc)` }}>
                  <span className="text-[10px] font-black tabular-nums" style={{ color: VOID }}>{dnPct.toFixed(1)}%</span>
                </div>
                {/* center reference line */}
                <div className="absolute inset-y-0 left-1/2 w-px" style={{ background: 'rgba(200,220,240,0.35)' }} />
              </div>
            </div>

            {/* return stats */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded p-3" style={{ background: '#0A1320', border: `1px solid ${BORDER}` }}>
                <p className="text-[9px] font-semibold tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: MUTED }}>AVG LABEL RETURN</p>
                <p className="text-xl font-black tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: avgRet >= 0 ? JADE : CRIMSON }}>
                  {fmtSigned(avgRet, 3)}%
                </p>
              </div>
              <div className="rounded p-3" style={{ background: '#0A1320', border: `1px solid ${BORDER}` }}>
                <p className="text-[9px] font-semibold tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: MUTED }}>RETURN σ (VOL)</p>
                <p className="text-xl font-black tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: SUB }}>
                  {fmt(ml?.labels?.std_return_pct, 3)}%
                </p>
              </div>
            </div>
          </div>
        </Panel>
      </div>

      {/* ── Per-ticker coverage grid ──────────────────────────────────────────── */}
      <Panel source={sourceOf(syncedAt ? syncedAt.toISOString() : null, { source: 'data-service' })} accent={AMBER}>
        <div className="flex flex-wrap items-center justify-between gap-3 px-5 pb-3 pt-4">
          <div className="flex items-baseline gap-3">
            <h3 className="text-[11px] font-semibold uppercase tracking-[0.2em]" style={{ fontFamily: "'Chakra Petch', sans-serif", color: AMBER }}>
              Per-Ticker Data Quality
            </h3>
            <span className="text-[9px] tracking-wider" style={{ color: MUTED }}>
              {metaLoading ? 'scanning warehouse…' : `${fmt(filteredSorted.length)} series · ${staleTickers} aged >5 sessions`}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <input
              value={search}
              onChange={e => { setSearch(e.target.value); setVisible(80) }}
              placeholder="filter ticker…"
              className="w-36 rounded px-2.5 py-1 text-[11px] outline-none transition-colors focus:border-amber-500/50"
              style={{ background: '#0A1320', border: `1px solid ${BORDER}`, color: TXT, fontFamily: "'JetBrains Mono', monospace" }}
            />
          </div>
        </div>

        <div className="max-h-[460px] overflow-auto">
          <table className="w-full border-collapse">
            <thead className="sticky top-0 z-10" style={{ background: '#0A1320', boxShadow: `0 1px 0 ${BORDER}` }}>
              <tr>
                <Th label="Ticker" col="ticker" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="left" width="18%" />
                <Th label="Last ₹" col="latest_price" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <Th label="Rows" col="total_rows" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <th className="px-3 py-2 text-left text-[9px] font-semibold uppercase tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: MUTED, width: '22%' }}>Window</th>
                <Th label="Yrs" col="years_of_data" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <Th label="Density" col="data_density_pct" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <Th label="Lag" col="sessions_behind" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
                <th className="px-3 py-2 text-right text-[9px] font-semibold uppercase tracking-widest" style={{ fontFamily: "'Chakra Petch', sans-serif", color: MUTED }}>Quality</th>
              </tr>
            </thead>
            <tbody>
              {metaLoading && meta.length === 0 ? (
                Array(10).fill(0).map((_, i) => (
                  <tr key={i} style={{ borderTop: `1px solid ${BORDER}` }}>
                    <td colSpan={8} className="px-3 py-2.5">
                      <div className="h-3 w-full animate-pulse rounded" style={{ background: '#131926' }} />
                    </td>
                  </tr>
                ))
              ) : filteredSorted.length === 0 ? (
                <tr><td colSpan={8} className="px-3 py-10 text-center text-xs" style={{ color: MUTED }}>
                  {meta.length === 0 ? 'Warehouse empty — no OHLCV series found.' : `No ticker matches “${search}”.`}
                </td></tr>
              ) : (
                filteredSorted.slice(0, visible).map((r, i) => {
                  const dStale = r.sessions_behind ?? null
                  const q = classify(r.data_density_pct, dStale)
                  return (
                    <tr key={r.ticker} className="transition-colors hover:bg-[#0C1726]"
                        style={{ borderTop: `1px solid ${BORDER}`, background: i % 2 ? 'rgba(10,19,32,0.35)' : 'transparent' }}>
                      <td className="px-3 py-2 text-left text-[11px] font-bold" style={{ fontFamily: "'JetBrains Mono', monospace", color: TXT }}>{r.ticker}</td>
                      <td className="px-3 py-2 text-right text-[11px] tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: SUB }}>{r.latest_price !== null ? fmt(r.latest_price, 2) : '—'}</td>
                      <td className="px-3 py-2 text-right text-[11px] tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: TXT }}>{fmt(r.total_rows)}</td>
                      <td className="px-3 py-2 text-left text-[10px] tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: MUTED }}>
                        {(r.first_date?.slice(0, 7) ?? '—')} <span style={{ color: '#26405C' }}>→</span> {(r.latest_date?.slice(0, 7) ?? '—')}
                      </td>
                      <td className="px-3 py-2 text-right text-[11px] tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: SUB }}>{r.years_of_data}</td>
                      <td className="px-3 py-2">
                        <div className="flex items-center justify-end gap-2">
                          <div className="h-1 w-14 overflow-hidden rounded-sm" style={{ background: '#131926' }}>
                            <div className="h-full rounded-sm" style={{ width: `${Math.min(100, r.data_density_pct)}%`, background: q.color }} />
                          </div>
                          <span className="w-9 text-right text-[10px] tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color: q.color }}>{fmt(r.data_density_pct, 0)}%</span>
                        </div>
                      </td>
                      <td className="px-3 py-2 text-right text-[11px] tabular-nums"
                          style={{ fontFamily: "'JetBrains Mono', monospace", color: dStale === null ? MUTED : dStale > 5 ? CRIMSON : dStale > 0 ? AMBER : JADE }}
                          title={r.latest_date ? `last bar ${r.latest_date}` : undefined}>
                        {dStale === null ? '—' : dStale === 0 ? 'current' : `${dStale} sess`}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <span className="rounded px-1.5 py-0.5 text-[8px] font-bold tracking-wider"
                              style={{ fontFamily: "'Chakra Petch', sans-serif", color: q.color, background: `${q.color}14`, border: `1px solid ${q.color}33` }}>
                          {q.label}
                        </span>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {!metaLoading && filteredSorted.length > visible && (
          <div className="border-t px-5 py-3 text-center" style={{ borderColor: BORDER }}>
            <button onClick={() => setVisible(v => v + 120)}
                    className="rounded px-4 py-1.5 text-[10px] font-semibold tracking-wider transition-all hover:brightness-125"
                    style={{ color: AMBER, background: 'rgba(245,166,35,0.08)', border: '1px solid rgba(245,166,35,0.25)', fontFamily: "'Chakra Petch', sans-serif" }}>
              SHOW MORE · {fmt(filteredSorted.length - visible)} hidden
            </button>
          </div>
        )}
      </Panel>

      <NseDatasets />
    </div>
    </>
  )
}
