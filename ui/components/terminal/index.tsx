'use client'

/**
 * SuryaDhana Terminal UI kit: the News Catalyst Terminal's look (void black, amber,
 * Chakra Petch display + JetBrains Mono data, square 1px rules, uppercase micro-labels)
 * packaged as building blocks for every page.
 *
 * Tokens: `T` (components/news/format.ts) and the CSS variables in app/globals.css.
 */
import { Z } from '@/lib/z'
import { isValidElement, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { getFinancialsLatest, getNewsQuotes, getStockHistory, getSurveillance, getSymbols } from '@/lib/api'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { fallbackLine, hoverHistory, rangePos, shortDay, type HoverHistory } from './hoverModel'
import { openTicker } from '@/lib/openTicker'
import { goToPage } from '@/lib/navigate'
import { newWindow, saveDownload } from '@/lib/platform'
import { T } from '@/components/news/format'
import { asciiMinus, fmtPx } from '@/lib/format'
import { chartHeight } from './chart'
import { SUB_VIEW_EVENT, badgeSpec, sourceChipText, subFromSearch, withSub, type Badge, type SourceInfo, type SourceState } from './source'

export { T }
// Exchange-style price formatting (2 dp, en-IN grouping, U+2212 minus) for every page: lib/format (C1-08)
export { MINUS, fmtFixed, fmtIdx, fmtInrPx, fmtPx, fmtSigned, indianGrouping } from '@/lib/format'
// Terminal v2 (reports/terminal_v2/PLAN.md §0): source chips, badges, sub-view URL state — pure helpers in ./source
export { BADGES, DESCRIBES, badgeSpec, describes, fmtAgeS, inputSource, nseStampIso, referenceSource, undatedSource, percentileOf, rankOf, sourceOf, setSubInUrl, subFromSearch, withSub, type Badge, type SourceInfo, type SourceState } from './source'

// ── formatting ──────────────────────────────────────────────────────────────────

export const fmtInr = (v: number | null | undefined, digits = 0): string =>
  v == null || !Number.isFinite(v) ? '—'
    : `${v < 0 ? '−' : ''}₹${Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`

/** Signed percent. A value that rounds to zero prints "0.0%", never "-0.0%" or "+0.0%". */
/** 1 → "1st", 2 → "2nd", 11 → "11th", 23 → "23rd" (percentiles, ranks). */
export const ordinal = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return '—'
  const n = Math.round(v), t = Math.abs(n) % 100
  return `${n}${t >= 11 && t <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[t % 10] ?? 'th'}`
}

/** Percent with `digits` decimals; '+' for gains when `sign`, U+2212 '−' for losses (one minus glyph on
 *  screen, C1-18); a value that rounds to zero prints "0.00%". */
export const fmtPct = (v: number | null | undefined, digits = 2, sign = true): string => {
  if (v == null || !Number.isFinite(v)) return '—'
  const r = Number(v.toFixed(digits)) || 0
  return `${sign && r > 0 ? '+' : r < 0 ? '\u2212' : ''}${Math.abs(r).toFixed(digits)}%`
}

export const fmtCr = (v: number | null | undefined): string => {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a >= 1e7) return `₹${(v / 1e7).toFixed(2)} cr`
  if (a >= 1e5) return `₹${(v / 1e5).toFixed(2)} L`
  return fmtInr(v)
}

/** '2026-10-14' → 'Tue, 14 Oct' (event and calendar rows). */
export const fmtDay = (d: string): string =>
  new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' })

/** Indian fiscal quarter of a quarter-end date: '2026-09-30' → 'Q2 FY27' (April–March years). */
export const fiscalQuarter = (periodEnd: string): string => {
  const d = new Date(periodEnd)
  return `${['Q4', 'Q1', 'Q2', 'Q3'][Math.floor(d.getMonth() / 3)]} FY${String((d.getMonth() >= 3 ? d.getFullYear() + 1 : d.getFullYear()) % 100).padStart(2, '0')}`
}

/** Median of the finite numbers in `xs`, or null when there are none. */
export const median = (xs: number[]): number | null => {
  const a = xs.filter(Number.isFinite).sort((x, y) => x - y)
  return a.length ? (a.length % 2 ? a[(a.length - 1) / 2] : (a[a.length / 2 - 1] + a[a.length / 2]) / 2) : null
}

export const fmtNum = (v: number | null | undefined, digits = 0): string =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })

export const fmtSignedPct = (v: number | null | undefined, digits = 2): string =>
  v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(digits)}%`

export const tone = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) || v === 0 ? T.muted : v > 0 ? T.green : T.red

// ── primitives ──────────────────────────────────────────────────────────────────

export function Label({ children, color = T.muted, style }: { children: ReactNode; color?: string; style?: CSSProperties }) {
  return (
    <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.4, textTransform: 'uppercase', color, ...style }}>
      {children}
    </span>
  )
}

export function Dot({ color = T.green, pulse = false, size = 7 }: { color?: string; pulse?: boolean; size?: number }) {
  return (
    <span className={pulse ? 't-pulse' : undefined}
      style={{ display: 'inline-block', width: size, height: size, borderRadius: size, background: color,
               boxShadow: `0 0 6px ${color}66`, flex: 'none' }} />
  )
}

export function Chip({ children, color = T.muted, active = false, onClick, title, style, 'aria-label': ariaLabel }: {
  children: ReactNode; color?: string; active?: boolean; onClick?: () => void; title?: string; style?: CSSProperties
  'aria-label'?: string
}) {
  const Tag = onClick ? 'button' : 'span'
  return (
    <Tag onClick={onClick} title={title} aria-label={ariaLabel}
      style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1, padding: '3px 8px', borderRadius: 2,
               border: `1px solid ${active ? color : T.border}`, color: active ? T.bg : color,
               background: active ? color : 'transparent', cursor: onClick ? 'pointer' : 'default',
               whiteSpace: 'nowrap', lineHeight: 1.4, display: 'inline-flex', alignItems: 'center', gap: 5, ...style }}>
      {children}
    </Tag>
  )
}

type BtnVariant = 'primary' | 'ghost' | 'danger' | 'go'

export function Btn({ children, onClick, variant = 'ghost', disabled, title, type = 'button', style, size = 'md' }: {
  children: ReactNode; onClick?: () => void; variant?: BtnVariant; disabled?: boolean; title?: string
  type?: 'button' | 'submit'; style?: CSSProperties; size?: 'sm' | 'md'
}) {
  const palette: Record<BtnVariant, { fg: string; bg: string; bd: string }> = {
    primary: { fg: T.bg, bg: T.amber, bd: T.amber },
    go: { fg: T.bg, bg: T.green, bd: T.green },
    danger: { fg: T.bright, bg: T.red, bd: T.red },
    ghost: { fg: T.amber, bg: 'transparent', bd: T.border },
  }
  const p = palette[variant]
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title}
      style={{ fontFamily: T.mono, fontSize: size === 'sm' ? 10 : 11, letterSpacing: 1.2, textTransform: 'uppercase',
               fontWeight: 600, padding: size === 'sm' ? '3px 8px' : '6px 12px', borderRadius: 2,
               border: `1px solid ${p.bd}`, color: p.fg, background: p.bg,
               cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.45 : 1,
               display: 'inline-flex', alignItems: 'center', gap: 6, whiteSpace: 'nowrap', ...style }}>
      {children}
    </button>
  )
}

// ── layout ──────────────────────────────────────────────────────────────────────

/** Page title strip: function code (Bloomberg-style mnemonic) + title + context + actions. */
export function PageHeader({ code, title, subtitle, right, status }: {
  code: string; title: string; subtitle?: ReactNode; right?: ReactNode; status?: ReactNode
}) {
  return (
    <div className="t-fade-up"
      style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', padding: '10px 14px',
               border: `1px solid ${T.border}`, background: 'linear-gradient(90deg, #0b0f16 0%, #07090d 70%)',
               marginBottom: 12 }}>
      <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: 1.5, color: T.bg,
                     background: T.amber, padding: '3px 7px' }}>{code}</span>
      <span style={{ fontFamily: T.display, fontSize: 18, fontWeight: 700, letterSpacing: 1.6, color: T.bright,
                     textTransform: 'uppercase' }}>{title}</span>
      {status}
      {subtitle && <span style={{ fontSize: 11, color: T.muted }}>{subtitle}</span>}
      <span style={{ flex: 1 }} />
      {right}
    </div>
  )
}

/** Bordered section with an amber uppercase title bar. */
export function Panel({ title, subtitle, right, children, pad = 12, style, bodyStyle, accent = T.amber, className, source, badge }: {
  title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children?: ReactNode; pad?: number
  style?: CSSProperties; bodyStyle?: CSSProperties; accent?: string; className?: string
  /** value · source · as-of · lag chip on the header (PLAN §0.5): `sourceOf(payload.as_of, { source })`; null = no chip yet */
  source?: SourceInfo | null
  /** the evidence badge of the panel's derived numbers (PLAN §0.1) */
  badge?: Badge | string | null
}) {
  return (
    <section className={className ?? 't-fade-up'} data-sd-source={source?.state}
      style={{ border: `1px solid ${T.border}`, background: T.panel, display: 'flex', flexDirection: 'column',
               minWidth: 0, ...style }}>
      {(title || right || source || badge) && (
        <header style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px',
                         borderBottom: `1px solid ${T.border}`, background: '#080b10', minHeight: 32 }}>
          <span style={{ width: 3, height: 12, background: accent, flex: 'none' }} />
          {title && <span style={{ fontFamily: T.display, fontSize: 12, fontWeight: 600, letterSpacing: 1.6,
                                   color: accent, textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{title}</span>}
          {subtitle && <span style={{ fontSize: 10, color: T.muted, letterSpacing: .5 }}>{subtitle}</span>}
          <span style={{ flex: 1 }} />
          {right}
          {badge && <BadgeChip badge={badge} />}
          {source && <SourceChip info={source} />}
        </header>
      )}
      <div style={{ padding: pad, minWidth: 0, ...bodyStyle }}>{children}</div>
    </section>
  )
}

export function Grid({ cols = 4, gap = 10, children, min, style }: {
  cols?: number; gap?: number; children: ReactNode; min?: number; style?: CSSProperties
}) {
  return (
    <div style={{ display: 'grid', gap,
                  gridTemplateColumns: min ? `repeat(auto-fit, minmax(${min}px, 1fr))` : `repeat(${cols}, minmax(0, 1fr))`,
                  ...style }}>
      {children}
    </div>
  )
}

/** KPI tile. */
export function Stat({ label, value, sub, color = T.text, accent, big = true }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; color?: string; accent?: string; big?: boolean
}) {
  return (
    <div className="t-fade-up"
      style={{ border: `1px solid ${T.border}`, borderTop: `2px solid ${accent ?? T.border}`, background: T.panel,
               padding: '9px 12px', minWidth: 0 }}>
      <Label>{label}</Label>
      <div style={{ fontFamily: T.mono, fontSize: big ? 22 : 16, fontWeight: 600, color, marginTop: 4,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: T.muted, marginTop: 3 }}>{sub}</div>}
    </div>
  )
}

/** Key → value rows. */
export function KV({ items, cols = 1 }: { items: [ReactNode, ReactNode, string?][]; cols?: number }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, columnGap: 18 }}>
      {items.map(([k, v, c], i) => (
        <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '4px 0',
                              borderBottom: `1px dashed ${T.border}`, fontSize: 11 }}>
          <span style={{ color: T.muted, textTransform: 'uppercase', letterSpacing: .8, fontSize: 10 }}>{k}</span>
          <span style={{ color: c ?? T.text, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{v}</span>
        </div>
      ))}
    </div>
  )
}

export function Meter({ value, color = T.amber, height = 4, track = T.border }: {
  value: number; color?: string; height?: number; track?: string
}) {
  const v = Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0))
  return (
    <div style={{ height, background: track, width: '100%' }}>
      <div style={{ height, width: `${v * 100}%`, background: color, transition: 'width .4s' }} />
    </div>
  )
}

export function Spark({ values, color, width = 120, height = 28, baseline }: {
  values: number[]; color?: string; width?: number; height?: number; baseline?: number
}) {
  const pts = values.filter(Number.isFinite)
  if (pts.length < 2) return <svg width={width} height={height} />
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1
  const c = color ?? (pts[pts.length - 1] >= pts[0] ? T.green : T.red)
  const d = pts.map((v, i) => `${i ? 'L' : 'M'}${(i / (pts.length - 1)) * width},${height - ((v - lo) / span) * (height - 2) - 1}`).join(' ')
  const by = baseline != null ? height - ((baseline - lo) / span) * (height - 2) - 1 : null
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      {by != null && <line x1={0} x2={width} y1={by} y2={by} stroke={T.border} strokeDasharray="3 3" />}
      <path d={d} fill="none" stroke={c} strokeWidth={1.4} />
    </svg>
  )
}

// ── charts: drawn in CSS px ────────────────────────────────────────────────────

const useIsoLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

/**
 * Size an SVG chart to its box so that one SVG user unit is one CSS pixel (C1-trader-ux-17): axis text keeps
 * its 9–11 px size at every window width instead of growing with a viewBox. Put `ref` on a block wrapper
 * (width 100%) and draw `<svg width={w} height={h} viewBox={`0 0 ${w} ${h}`}>`. The height keeps the chart's
 * designed aspect ratio (baseW × baseH), clamped to 0.8–1.6 × baseH (ratios overridable). Until the first
 * measurement (layout effect, before paint) and where ResizeObserver is missing it returns the design size.
 */
export function useChartSize(baseW: number, baseH: number, opts?: { minRatio?: number; maxRatio?: number }) {
  const [el, setEl] = useState<HTMLElement | null>(null)
  const [measured, setMeasured] = useState(0)
  useIsoLayoutEffect(() => {
    if (!el) return
    const read = () => {
      const cw = Math.floor(el.getBoundingClientRect().width)
      if (cw > 0) setMeasured(prev => (prev === cw ? prev : cw))
    }
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [el])
  const w = measured > 0 ? measured : baseW
  return { ref: setEl, w, h: chartHeight(w, baseW, baseH, opts?.minRatio, opts?.maxRatio), measured: measured > 0 }
}

/** Block wrapper for a px-sized chart (pairs with useChartSize). */
export const CHART_BOX: CSSProperties = { width: '100%', minWidth: 0 }

// ── tabs ────────────────────────────────────────────────────────────────────────

export function Tabs<K extends string>({ items, active, onChange }: {
  items: { id: K; label: string; count?: number }[]; active: K; onChange: (id: K) => void
}) {
  return (
    <div style={{ display: 'flex', gap: 2, borderBottom: `1px solid ${T.border}` }}>
      {items.map(it => {
        const on = it.id === active
        return (
          <button key={it.id} onClick={() => onChange(it.id)}
            style={{ fontFamily: T.mono, fontSize: 11, letterSpacing: 1.2, textTransform: 'uppercase',
                     padding: '8px 14px', background: on ? '#0d1119' : 'transparent', cursor: 'pointer',
                     color: on ? T.amber : T.muted, border: 'none', borderBottom: `2px solid ${on ? T.amber : 'transparent'}` }}>
            {it.label}{it.count != null && <span style={{ color: T.dim }}> ({it.count})</span>}
          </button>
        )
      })}
    </div>
  )
}

// ── states ──────────────────────────────────────────────────────────────────────

export function Empty({ title, hint, icon = '◇' }: { title: ReactNode; hint?: ReactNode; icon?: string }) {
  return (
    <div style={{ padding: '28px 12px', textAlign: 'center', color: T.muted }}>
      <div style={{ fontSize: 20, color: T.dim, marginBottom: 6 }}>{icon}</div>
      <div style={{ fontSize: 12, color: T.text, letterSpacing: .8, textTransform: 'uppercase' }}>{title}</div>
      {hint && <div style={{ fontSize: 11, marginTop: 6, maxWidth: 620, marginInline: 'auto', lineHeight: 1.6 }}>{hint}</div>}
    </div>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div style={{ padding: '22px 12px', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 8 }}>
      <div style={{ width: 160, height: 2, background: T.border, overflow: 'hidden', position: 'relative' }}>
        <div className="t-pulse" style={{ position: 'absolute', inset: 0, background: T.amber, width: '40%' }} />
      </div>
      <Label>{label}…</Label>
    </div>
  )
}

/** Any error payload → readable text: FastAPI validation errors arrive as a list of {msg, loc} objects, which
 *  React cannot render directly. */
export function errorText(error: unknown): ReactNode {
  if (error == null || typeof error === 'string' || typeof error === 'number' || isValidElement(error)) return error as ReactNode
  if (Array.isArray(error)) return error.map(e => (e && typeof e === 'object' && 'msg' in e ? String((e as { msg: unknown }).msg) : String(e))).join('; ')
  if (error instanceof Error) return error.message
  try { return JSON.stringify(error) } catch { return String(error) }
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div style={{ border: `1px solid ${T.red}55`, background: 'rgba(255,77,94,.07)', padding: '8px 12px',
                  display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, color: T.red }}>
      <span>▲ {errorText(error)}</span>
      <span style={{ flex: 1 }} />
      {onRetry && <Btn size="sm" onClick={onRetry}>Retry</Btn>}
    </div>
  )
}

export function Notice({ children, color = T.amber }: { children: ReactNode; color?: string }) {
  return (
    <div style={{ borderLeft: `2px solid ${color}`, background: `${color}10`, padding: '8px 12px', fontSize: 12,
                  color: T.text, lineHeight: 1.55 }}>
      {children}
    </div>
  )
}

// ── data table ──────────────────────────────────────────────────────────────────

export interface Column<R> {
  key: string
  label: ReactNode
  align?: 'left' | 'right' | 'center'
  width?: number | string
  sort?: (r: R) => number | string | null | undefined
  render?: (r: R, i: number) => ReactNode
  title?: string
}

/** The table as shown (header labels without sort arrows, each cell's visible text) → a CSV download. */
function downloadCsv(table: HTMLTableElement, name?: string): void {
  // U+2212 on screen → ASCII '-' in the file, so spreadsheets read negatives as numbers
  const clean = (t: string) => asciiMinus(t.replace(/[↕▲▼]/g, '').replace(/\s+/g, ' ').trim())
  const esc = (t: string) => (/[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t)
  const lines = Array.from(table.querySelectorAll('tr')).map(tr =>
    Array.from(tr.querySelectorAll('th,td')).map(c => esc(clean((c as HTMLElement).innerText || ''))).join(','))
    .filter(l => l.replace(/,/g, '').length > 0)
  const stem = (name || document.title.split(/[·|]/)[0] || 'suryadhana').trim().toLowerCase().replace(/[^a-z0-9]+/g, '-')
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  void saveDownload(blob, `${stem}-${new Date().toLocaleDateString('en-CA')}.csv`)   // browser: anchor download; app: ~/Downloads
}

export function DataTable<R>({ columns, rows, rowKey, onRowClick, maxHeight, empty, dense = false, initialSort,
  rowStyle, footer, exportName }: {
  columns: Column<R>[]; rows: R[]; rowKey: (r: R, i: number) => string; onRowClick?: (r: R) => void
  maxHeight?: number | string; empty?: ReactNode; dense?: boolean
  initialSort?: { key: string; dir: 'asc' | 'desc' }; rowStyle?: (r: R) => CSSProperties | undefined; footer?: ReactNode
  /** file name stem for the ⤓ CSV download (default: the page name + date) */
  exportName?: string
}) {
  const [sort, setSort] = useState(initialSort ?? null)
  const sorted = useMemo(() => {
    if (!sort) return rows
    const col = columns.find(c => c.key === sort.key)
    if (!col?.sort) return rows
    const get = col.sort
    return [...rows].sort((a, b) => {
      const x = get(a), y = get(b)
      if (x == null && y == null) return 0
      if (x == null) return 1
      if (y == null) return -1
      const cmp = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y))
      return sort.dir === 'asc' ? cmp : -cmp
    })
  }, [rows, sort, columns])
  const padY = dense ? 4 : 7
  const tableRef = useRef<HTMLTableElement>(null)
  const [hover, setHover] = useState(false)
  // keyboard: click a table, then ↑/↓ (or j/k) move a row cursor, Enter opens the row (its stock), Esc clears
  const [cursor, setCursor] = useState<number | null>(null)
  useEffect(() => { setCursor(null) }, [sorted.length, sort])
  const move = (to: number) => {
    const n = sorted.length
    if (!n) return
    const i = Math.max(0, Math.min(n - 1, to))
    setCursor(i)
    tableRef.current?.tBodies[0]?.rows[i]?.scrollIntoView({ block: 'nearest' })
  }
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest('input, textarea, select')) return
    const k = e.key
    if (k === 'ArrowDown' || k === 'j') { e.preventDefault(); move((cursor ?? -1) + 1) }
    else if (k === 'ArrowUp' || k === 'k') { e.preventDefault(); move((cursor ?? 1) - 1) }
    else if (k === 'Home') { e.preventDefault(); move(0) }
    else if (k === 'End') { e.preventDefault(); move(sorted.length - 1) }
    else if (k === 'Enter' && cursor != null && sorted[cursor]) {
      e.preventDefault()
      if (onRowClick) onRowClick(sorted[cursor])
      else (tableRef.current?.tBodies[0]?.rows[cursor]?.querySelector('.t-ticker-link') as HTMLElement | null)?.click()
    } else if (k === 'Escape' && cursor != null) { e.stopPropagation(); setCursor(null) }
  }
  return (
    <div className="t-table" style={{ position: 'relative', outline: 'none' }} tabIndex={0} onKeyDown={onKey}
         onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
    {hover && rows.length > 0 && (
      <span role="button" title="Download this table as CSV (what is shown, in the current sort)"
        onClick={e => { e.stopPropagation(); if (tableRef.current) downloadCsv(tableRef.current, exportName) }}
        style={{ position: 'absolute', top: 3, right: 4, zIndex: Z.raised + 1, fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1,
                 color: T.cyan, background: '#080b10', border: `1px solid ${T.border}`, padding: '1px 6px', cursor: 'pointer' }}>⤓ CSV</span>
    )}
    <div style={{ overflow: 'auto', maxHeight }}>
      <table ref={tableRef} style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5, fontVariantNumeric: 'tabular-nums' }}>
        <thead>
          <tr>
            {columns.map(c => {
              const on = sort?.key === c.key
              return (
                <th key={c.key} title={c.title}
                  onClick={c.sort ? () => setSort(s => s?.key === c.key ? { key: c.key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
                                                                         : { key: c.key, dir: 'desc' }) : undefined}
                  style={{ position: 'sticky', top: 0, zIndex: Z.raised, background: '#080b10', textAlign: c.align ?? 'left',
                           padding: `7px 10px`, borderBottom: `1px solid ${T.border}`, width: c.width,
                           fontFamily: T.mono, fontSize: 9.5, fontWeight: 500, letterSpacing: 1.2,
                           textTransform: 'uppercase', color: on ? T.amber : T.muted, whiteSpace: 'nowrap',
                           cursor: c.sort ? 'pointer' : 'default', userSelect: 'none' }}>
                  {c.label}{c.sort ? <span style={{ color: on ? T.amber : T.dim }}> {on ? (sort!.dir === 'asc' ? '▲' : '▼') : '↕'}</span> : null}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr><td colSpan={columns.length}>{empty ?? <Empty title="No rows" />}</td></tr>
          ) : sorted.map((r, i) => (
            <tr key={rowKey(r, i)} onClick={onRowClick ? () => onRowClick(r) : undefined} onMouseDown={() => setCursor(i)} className="t-row"
              style={{ cursor: onRowClick ? 'pointer' : 'default', borderBottom: `1px solid ${T.border}`, ...rowStyle?.(r),
                       ...(cursor === i ? { background: '#16202e', boxShadow: `inset 2px 0 0 ${T.amber}` } : null) }}>
              {columns.map(c => (
                <td key={c.key} style={{ padding: `${padY}px 10px`, textAlign: c.align ?? 'left', whiteSpace: 'nowrap',
                                         color: T.text, fontVariantNumeric: 'tabular-nums' }}>
                  {c.render ? c.render(r, i) : String((r as Record<string, unknown>)[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {footer}
      <style>{`.t-row:hover { background: #0f141d; } .t-table:focus-visible { box-shadow: 0 0 0 1px ${T.amber}66; }`}</style>
    </div>
    </div>
  )
}

// ── form controls ───────────────────────────────────────────────────────────────

export function Input({ value, onChange, placeholder, type = 'text', style, autoComplete = 'off', label, width,
                        'aria-label': ariaLabel }: {
  value: string | number; onChange: (v: string) => void; placeholder?: string; type?: string
  style?: CSSProperties; autoComplete?: string; label?: ReactNode; width?: number | string
  'aria-label'?: string
}) {
  const box = (
    <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} type={type}
      autoComplete={autoComplete} aria-label={ariaLabel}
      style={{ width: width ?? '100%', background: '#07090d', color: T.text, border: `1px solid ${T.border}`,
               fontFamily: T.mono, fontSize: 12, padding: '6px 8px', borderRadius: 0, outline: 'none', ...style }} />
  )
  if (!label) return box
  return (
    <label style={{ display: 'grid', gap: 4 }}>
      <Label>{label}</Label>
      {box}
    </label>
  )
}

export function Select<V extends string>({ value, onChange, options, style, label }: {
  value: V; onChange: (v: V) => void; options: { value: V; label: string }[]; style?: CSSProperties; label?: ReactNode
}) {
  const box = (
    <select value={value} onChange={e => onChange(e.target.value as V)}
      style={{ background: '#07090d', color: T.text, border: `1px solid ${T.border}`, fontFamily: T.mono,
               fontSize: 11, padding: '5px 6px', borderRadius: 0, ...style }}>
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
  if (!label) return box
  return <label style={{ display: 'grid', gap: 4 }}><Label>{label}</Label>{box}</label>
}

/** A ticker that opens the stock detail window (chart, levels, ☆ PIN, + WATCHLIST) from any table. */
// ── hover quote card (every TickerLink) ─────────────────────────────────────────────────────────────────────────
// Live half (price, day move, day range, the time + source line): lib/liveQuotes.ts — the Breeze websocket tick, else
// NSE's website (DELAYED, its age), else the last close (CLOSE <day>); never Yahoo once the live service answers.
// Stored half (52-week range, one-month sparkline of DAILY closes, P/E line): NSE bhavcopy + results filings, cached
// per IST day (hoverModel.ts). Only if the live service does not answer at all (404 before its deploy, or down) does
// the card fall back to the old quotes route, and then it prints that route's own source and time, never LIVE.
type HoverFin = { pe: number | null; revenue_yoy: number | null; pat_yoy: number | null; pat_yoy_turn?: string | null; period_end: string; mcap: number | null }
type HoverStored = { name: string | null; hist: HoverHistory | null; fin: HoverFin | null }
type HoverFallback = { price?: number | null; change_pct?: number | null; day_low?: number | null; day_high?: number | null; source?: unknown; state?: unknown
                       age_s?: unknown; market_time?: unknown; gmtoffset?: unknown; available?: boolean }
const storedCache = new Map<string, { day: string; p: Promise<HoverStored> }>()
let directory: Promise<Map<string, string>> | null = null
function symbolName(sym: string): Promise<string | null> {
  if (!directory) {
    directory = getSymbols().then(r => new Map(r.data.data.map(e => [e.t, e.n] as [string, string])))
      .catch(() => { directory = null; return new Map<string, string>() })
  }
  return directory.then(m => m.get(sym) ?? null)
}
function hoverStored(sym: string): Promise<HoverStored> {
  const day = new Date(Date.now() + 330 * 60_000).toISOString().slice(0, 10)
  const hit = storedCache.get(sym)
  if (hit && hit.day === day) return hit.p
  const p = Promise.all([
    getStockHistory(sym, 366).then(r => hoverHistory(r.data)).catch(() => null),   // NSE bhavcopy (EOD)
    getFinancialsLatest([sym]).then(f => f?.data?.latest?.[sym] ?? null).catch(() => null),   // cached filings only
    symbolName(sym),
  ]).then(([hist, fin, name]) => ({ hist, fin: fin as HoverFin | null, name }))
  storedCache.set(sym, { day, p })
  if (storedCache.size > 400) storedCache.delete(storedCache.keys().next().value as string)
  return p
}
const fallbackCache = new Map<string, { at: number; p: Promise<HoverFallback | null> }>()
function hoverFallback(sym: string): Promise<HoverFallback | null> {
  const hit = fallbackCache.get(sym)
  if (hit && Date.now() - hit.at < 30_000) return hit.p
  const p = getNewsQuotes([`${sym}.NS`]).then(r => {
    const raw = r.data?.quotes?.[`${sym}.NS`] as HoverFallback | undefined
    return raw?.available ? raw : null
  }).catch(() => { fallbackCache.delete(sym); return null })
  fallbackCache.set(sym, { at: Date.now(), p })
  return p
}

function HoverCard({ symbol, at }: { symbol: string; at: DOMRect }) {
  const sym = String(symbol ?? '').trim().toUpperCase().replace(/\.NS$/, '')
  const live = useLiveQuotes([sym], { intervalMs: 2_000 })
  const lq = live.quotes[sym]
  const [stored, setStored] = useState<HoverStored | null>(null)
  const [fb, setFb] = useState<HoverFallback | null | undefined>(undefined)
  useEffect(() => { let alive = true; hoverStored(sym).then(v => { if (alive) setStored(v) }); return () => { alive = false } }, [sym])
  // the old route only when the live service has not answered at all (never as a second opinion on a live row)
  const needFallback = live.status === 'missing' || (live.status === 'error' && !lq)
  useEffect(() => {
    if (!needFallback) { setFb(undefined); return }
    let alive = true; hoverFallback(sym).then(v => { if (alive) setFb(v) }); return () => { alive = false }
  }, [sym, needFallback])
  const W = 284
  const left = Math.min(Math.max(8, at.left), window.innerWidth - W - 8)
  const below = at.bottom + 190 < window.innerHeight
  const pos: CSSProperties = below ? { top: at.bottom + 6 } : { bottom: window.innerHeight - at.top + 6 }
  const q = lq && lq.price != null ? lq : null
  const price = q?.price ?? (needFallback ? fb?.price ?? null : null)
  const chg = q ? q.change_pct : needFallback ? fb?.change_pct ?? null : null
  const dayLo = q ? q.day_low : needFallback ? fb?.day_low ?? null : null
  const dayHi = q ? q.day_high : needFallback ? fb?.day_high ?? null : null
  const hist = stored?.hist ?? null
  const pos52 = rangePos(price, hist?.low_52w, hist?.high_52w)
  const info = q ? live.sourceFor(sym) : null
  const lineColor = info?.state === 'live' ? T.green : info?.state === 'offline' ? T.red : info?.state === 'stale' ? T.amber : T.muted
  const waiting = !q && !needFallback && (live.status === 'idle' || live.status === 'loading' || (live.status === 'ok' && !lq))
  const line = q ? live.lineFor(sym) : lq ? live.lineFor(sym) : needFallback ? (fb ? `${fallbackLine(fb)} · live NSE service ${live.status === 'missing' ? 'not deployed' : 'not answering'}` : fb === null ? 'no quote' : null) : null
  return createPortal(
    <div role="tooltip" data-sd-hover={sym} style={{ position: 'fixed', left, width: W, zIndex: Z.commandbar, background: T.panel ?? '#0b0f16', border: `1px solid ${T.amber}`,
                                 boxShadow: '0 8px 24px rgba(0,0,0,.6)', padding: '8px 10px', fontFamily: T.mono, fontSize: 11, pointerEvents: 'none', ...pos }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ color: T.amber, fontWeight: 700 }}>{sym}</span>
        <span style={{ color: T.dim, fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{stored?.name ?? 'NSE'}</span>
      </div>
      {price == null ? <div style={{ color: T.dim, marginTop: 6 }}>{waiting || fb === undefined && needFallback ? 'loading…' : `${line ?? 'no quote'} · click to open`}</div>
        : <>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginTop: 4 }}>
            <span style={{ fontSize: 16, fontWeight: 700, color: T.text }}>{fmtPx(price)}</span>
            <span style={{ color: tone(chg), fontWeight: 700 }}>{fmtPct(chg, 2)}</span>
            <span style={{ flex: 1 }} />
            {hist && hist.spark.length > 1 && <span title={`last ${hist.spark.length} daily closes (NSE bhavcopy, adjusted) to ${hist.last_date ?? '—'}: not today's intraday path`}
              style={{ display: 'inline-flex', flexDirection: 'column', alignItems: 'flex-end' }}>
              <Spark values={hist.spark} width={70} height={20} />
              <span data-sd-spark="daily" style={{ fontSize: 8.5, color: T.dim, letterSpacing: .4 }}>1M DAILY CLOSES</span></span>}
          </div>
          <div style={{ color: T.muted, marginTop: 4, fontSize: 10.5 }}>day {fmtPx(dayLo)} – {fmtPx(dayHi)}</div>
          {hist && <div style={{ color: T.muted, fontSize: 10.5 }} title="52-week range on adjusted NSE closes (bhavcopy, end of day)">52w {fmtPx(hist.low_52w)} – {fmtPx(hist.high_52w)}
            {price != null && hist.high_52w != null && price > hist.high_52w ? <span style={{ color: T.green }}> · above it today</span>
              : price != null && hist.low_52w != null && price < hist.low_52w ? <span style={{ color: T.red }}> · below it today</span>
              : pos52 != null && <span style={{ color: pos52 > 0.9 ? T.green : pos52 < 0.1 ? T.red : T.dim }}> · {(pos52 * 100).toFixed(0)}% of range</span>}
            <span style={{ color: T.dim }}> · EOD {shortDay(hist.last_date)}</span></div>}
          {stored?.fin && (stored.fin.pe != null || stored.fin.revenue_yoy != null) && (() => {
            const f = stored.fin!, qn = fiscalQuarter(f.period_end)
            return <div style={{ color: T.muted, fontSize: 10.5, marginTop: 3, borderTop: `1px solid ${T.border}`, paddingTop: 3 }}>
              {f.pe != null && <>P/E <span style={{ color: T.amber }}>{f.pe.toFixed(1)}×</span> · </>}
              {qn} rev <span style={{ color: tone(f.revenue_yoy) }}>{fmtPct(f.revenue_yoy, 0)}</span> · profit{' '}
              {f.pat_yoy_turn ? <span style={{ color: f.pat_yoy_turn === 'to profit' ? T.green : T.red }}>{f.pat_yoy_turn}</span>
                : <span style={{ color: tone(f.pat_yoy) }}>{fmtPct(f.pat_yoy, 0)}</span>} y/y</div>
          })()}
          <div data-sd-hover-line={info?.state ?? (needFallback ? 'fallback' : 'none')} title={info?.hint ?? undefined}
            style={{ color: q ? lineColor : T.amber, fontSize: 9.5, marginTop: 4 }}>{line ?? '—'}</div>
          <div style={{ color: T.dim, fontSize: 9.5 }}>click for chart & profile</div>
        </>}
    </div>, document.body)
}

// NSE surveillance marks for every ticker in the app: one fetch of all flagged stocks (~860), shared, 30 min
const flagStore: { at: number; map: Record<string, string[]>; loading: boolean; subs: Set<() => void> } = { at: 0, map: {}, loading: false, subs: new Set() }
function useFlagged(): Record<string, string[]> {
  const [, bump] = useState(0)
  useEffect(() => {
    const sub = () => bump(x => x + 1)
    flagStore.subs.add(sub)
    if (!flagStore.loading && Date.now() - flagStore.at > 30 * 60_000) {
      flagStore.loading = true
      getSurveillance([], true).then(r => { flagStore.map = r.data.flagged ?? {}; flagStore.at = Date.now() })
        .catch(() => { flagStore.at = Date.now() }).finally(() => { flagStore.loading = false; flagStore.subs.forEach(f => f()) })
    }
    return () => { flagStore.subs.delete(sub) }
  }, [])
  return flagStore.map
}
const SERIOUS = /GSM|ESM|IRP|BAN|T2T|BAND 2|ASM (LT|ST) [2-9]/

export function TickerLink({ symbol, style, noFlag }: { symbol: string; style?: CSSProperties; noFlag?: boolean }) {
  const flagged = useFlagged()
  const flag = noFlag ? undefined : flagged[symbol]
  const [at, setAt] = useState<DOMRect | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const clear = () => { if (timer.current) clearTimeout(timer.current); timer.current = null; setAt(null) }
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  // ⌘/Ctrl-click or middle-click: the stock in a NEW terminal window on this page (C1-trader-ux-16, contract K4)
  const openInNewWindow = (e: { preventDefault(): void; stopPropagation(): void }) => {
    e.preventDefault(); e.stopPropagation(); clear()
    let tab: string | undefined
    try { tab = new URLSearchParams(window.location.search).get('tab') ?? undefined } catch { tab = undefined }
    void newWindow(tab, String(symbol ?? '').trim().toUpperCase().replace(/\.(NS|BO)$/, ''))
  }
  return (
    <span role="button" tabIndex={0} className="t-ticker-link"
      onClick={e => {
        if (e.button !== 0) return                                    // an engine that also sends click for the middle button
        if (e.metaKey || e.ctrlKey) { openInNewWindow(e); return }
        e.stopPropagation(); clear(); openTicker(symbol)
      }}
      // middle button on mouseup, not auxclick: WebKit builds without auxclick still deliver mouseup (button 1), and
      // Chromium sends both, so handling one of them opens exactly one window
      onMouseUp={e => { if (e.button === 1) openInNewWindow(e) }}
      onMouseDown={e => { if (e.button === 1) e.preventDefault() /* no autoscroll cursor */ }}
      onKeyDown={e => { if (e.key === 'Enter') { e.stopPropagation(); openTicker(symbol) } }}
      onMouseEnter={e => { const el = e.currentTarget; timer.current = setTimeout(() => setAt(el.getBoundingClientRect()), 450) }}
      onMouseLeave={clear}
      style={{ color: T.amber, fontWeight: 600, cursor: 'pointer', ...style }}>{symbol}
      {flag && <span title={`NSE surveillance: ${flag.join(', ')}`} style={{ color: flag.some(c => SERIOUS.test(c)) ? T.red : T.amber, fontSize: 9, marginLeft: 3, fontWeight: 400 }}>⚑</span>}
      {at && <HoverCard symbol={symbol} at={at} />}</span>
  )
}

/** Next corporate event for a stock, e.g. "RESULTS 14 OCT · 3d" (amber within a week). */
export function EventBadge({ kind, date, days, typical, detail }: { kind: string; date: string; days: number; typical?: number | null; detail?: string | null }) {
  const soon = days <= 7
  const c = soon ? T.amber : T.muted
  const label = new Date(`${date}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }).toUpperCase()
  return (
    <span title={`${kind} on ${date}${days === 0 ? ' (today)' : days === 1 ? ' (tomorrow)' : ` (in ${days} days)`}${typical != null ? ` · typically moves ±${typical.toFixed(1)}% on results` : ''}${detail ? `\n${detail}` : ''}`}
      style={{ fontFamily: T.mono, fontSize: 9.5, color: c, border: `1px solid ${c}66`, padding: '1px 5px', whiteSpace: 'nowrap',
               letterSpacing: .5 }}>
      {kind === 'OTHER' ? 'BOARD MTG' : kind} {label}{days <= 1 ? (days === 0 ? ' · TODAY' : ' · TMRW') : ` · ${days}d`}
    </span>
  )
}

/** One-line research verdict that links to the full study in the Research library (RSCH). */
export function ResearchNote({ verdict, children, report }: { verdict: 'FAIL' | 'NO EDGE' | 'PROMISING' | 'PASS' | 'ADOPTED' | 'REFERENCE'; children: ReactNode; report: string }) {
  const c = verdict === 'FAIL' || verdict === 'NO EDGE' ? T.red : verdict === 'PROMISING' ? T.amber : verdict === 'REFERENCE' ? T.cyan : T.green
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 12px', marginBottom: 12, fontSize: 11.5,
                  border: `1px solid ${c}44`, borderLeft: `3px solid ${c}`, background: '#080b10', color: T.text }}>
      <span style={{ fontFamily: T.mono, fontSize: 9.5, fontWeight: 700, letterSpacing: 1, color: c, border: `1px solid ${c}`, padding: '1px 5px', flex: 'none' }}>
        RESEARCH · {verdict}
      </span>
      <span style={{ flex: 1 }}>{children}</span>
      <span role="button" tabIndex={0} onClick={() => goToPage('research', { research: report })}
        onKeyDown={e => { if (e.key === 'Enter') goToPage('research', { research: report }) }}
        style={{ color: T.cyan, cursor: 'pointer', fontSize: 10.5, whiteSpace: 'nowrap' }}>READ THE STUDY ›</span>
    </div>
  )
}

/** Research flag: the stock's last results reaction was ≤ −5% vs NIFTY within 60 sessions. In the post-results
 *  drift study (reports/results_drift) such stocks lagged the market by 1.8–3.7% over the next 60 sessions. */
export function AvoidFlag({ r }: { r: { reaction_date: string | null; vs_nifty_pct: number | null; sessions_since?: number | null } }) {
  const tip = `Results reaction ${r.vs_nifty_pct?.toFixed(1)}% vs NIFTY on ${r.reaction_date} (${r.sessions_since} sessions ago). ` +
    'Research (pre-registered, PASS): after a ≤ −5% results reaction NSE stocks lagged the market by another 1.8–3.7% over ' +
    'the next 60 sessions. Consider waiting. A flag, not a trading rule.'
  return (
    <span title={tip} style={{ fontFamily: T.mono, fontSize: 9.5, fontWeight: 700, color: T.red, border: `1px solid ${T.red}88`,
                               padding: '1px 5px', whiteSpace: 'nowrap', letterSpacing: .5 }}>⚠ BAD RESULTS</span>
  )
}

/** Data-freshness chip for a panel header (PLAN §0.5): LIVE · <feed> / DELAYED <day> / STALE <day> / OFFLINE / GAP /
 *  DEGRADED. Pass `info` from `sourceOf(payload.as_of, { source })`, or the legacy `state` (+ `hint`) the pre-v2 callers
 *  use: live = broker websocket ticking · delayed = Yahoo 60 s refresh · degraded = broker up but erroring ·
 *  offline = no quote source responding. Daily data shows its date, never a clock. */
export function SourceChip({ state, hint, info, style }: { state?: SourceState; hint?: string; info?: SourceInfo | null; style?: CSSProperties }) {
  const LEGACY: Record<SourceState, { label: string; tip: string }> = {
    live: { label: 'LIVE · ICICI', tip: 'Broker websocket ticks (ICICI Breeze), ~2 s refresh' },
    delayed: { label: 'DELAYED · YAHOO', tip: 'Yahoo quotes on a 60 s refresh; broker feed not connected' },
    degraded: { label: 'DEGRADED', tip: 'Broker feed connected but erroring; values may be stale' },
    offline: { label: 'OFFLINE', tip: 'No quote source is responding' },
    stale: { label: 'STALE', tip: 'Older than expected' },
    gap: { label: 'GAP', tip: 'No capture for this session' },
    input: { label: 'INPUT', tip: 'Computed from your inputs; no feed behind this panel' },
    reference: { label: 'REFERENCE', tip: 'Fixed reference text; no data feed behind this panel' },
    closed: { label: 'CLOSE', tip: "NSE closed: the last session's close" },
  }
  const st: SourceState = info?.state ?? state ?? 'offline'
  const color = st === 'live' ? T.green : st === 'delayed' || st === 'input' || st === 'reference' || st === 'closed' ? T.muted : st === 'offline' ? T.red : T.amber
  const text = info ? sourceChipText(info) : { label: LEGACY[st].label, title: LEGACY[st].tip }
  const title = hint ? `${text.title} — ${hint}` : text.title
  return (
    <span title={title} data-sd-chip={st}
      // live program: machine-readable age / as-of for the freshness audit (scripts/ui_audit.py), only when known
      data-sd-age-s={info?.ageS != null && Number.isFinite(info.ageS) ? info.ageS.toFixed(1) : undefined}
      data-sd-asof={info?.asOf ?? undefined} data-sd-feed-source={info?.source ?? undefined}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: T.mono, fontSize: 9.5,
               letterSpacing: 1, color, border: `1px solid ${color}55`, padding: '1px 6px',
               whiteSpace: 'nowrap', ...style }}>
      <Dot color={color} pulse={st === 'live'} size={5} />{text.label}
    </span>
  )
}

/** Evidence badge chip (PLAN §0.1): signal / context / arithmetic / heuristic. Context is the neutral tone. */
export function BadgeChip({ badge, note, style }: { badge: Badge | string | null | undefined; note?: string | null; style?: CSSProperties }) {
  const b = badgeSpec(badge)
  const color = b.tone === 'green' ? T.green : b.tone === 'cyan' ? T.cyan : b.tone === 'violet' ? T.violet : T.muted
  return (
    <Chip color={color} title={note ? `${b.title} ${note}` : b.title} style={{ fontSize: 9, padding: '1px 6px', ...style }}
      aria-label={`evidence badge ${b.label.toLowerCase()}`}>{b.label}</Chip>
  )
}

/**
 * A page's sub-view (DERV › VOL, SYS › DATA) mirrored in `?sub=`: read once on mount (the GO bar's aliases hand it
 * over through the URL, like the GOLD page), written on change, removed when the page unmounts so it never follows
 * the next page.
 */
export function useSubView<K extends string>(valid: readonly K[], initial: K): [K, (k: K) => void] {
  const [sub, setSub] = useState<K>(() => {
    if (typeof window === 'undefined') return initial
    return (subFromSearch(window.location.search, valid) as K | null) ?? initial
  })
  useEffect(() => {
    try {
      const next = withSub(window.location.search, sub === initial ? null : sub)
      if (next !== window.location.search) window.history.replaceState(window.history.state, '', next || window.location.pathname)
    } catch { /* history locked */ }
  }, [sub, initial])
  useEffect(() => () => {
    try { window.history.replaceState(window.history.state, '', withSub(window.location.search, null) || window.location.pathname) } catch { /* ignore */ }
  }, [])
  // a GO alias (VOL / DATA) typed while this page is already open: adopt the hand-off without a remount
  const validKey = valid.join('|')
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<string | null>).detail
      if (typeof d === 'string' && validKey.split('|').includes(d)) setSub(d as K)
    }
    window.addEventListener(SUB_VIEW_EVENT, on)
    return () => window.removeEventListener(SUB_VIEW_EVENT, on)
  }, [validKey])
  return [sub, setSub]
}

/** Shimmer placeholder bar. Width/height in px or any CSS size; respects prefers-reduced-motion
 *  (the shimmer is a background animation — reduced-motion users get a static block). */
export function Skeleton({ h = 12, w = '100%', style }: { h?: number; w?: number | string; style?: CSSProperties }) {
  return (
    <span aria-hidden className="t-shimmer"
      style={{ display: 'block', height: h, width: w, borderRadius: 2,
               background: 'linear-gradient(90deg, #0d1118 25%, #141a24 37%, #0d1118 63%)',
               backgroundSize: '400% 100%', ...style }} />
  )
}

/** Full-tab loading state for lazily loaded pages: a header bar + four ghost panels.
 *  Used as the `loading` component of every per-tab dynamic() import. */
export function TabSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading page">
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '2px 0 14px' }}>
        <Skeleton h={22} w={64} />
        <Skeleton h={14} w={220} />
        <span style={{ flex: 1 }} />
        <Skeleton h={14} w={120} />
      </div>
      <Grid min={320}>
        {[0, 1, 2, 3].map(i => (
          <Panel key={i} title={<Skeleton h={10} w={110} />}>
            <div style={{ display: 'grid', gap: 10, padding: '4px 0' }}>
              <Skeleton h={12} w="86%" /><Skeleton h={12} w="64%" /><Skeleton h={12} w="76%" />
            </div>
          </Panel>
        ))}
      </Grid>
    </div>
  )
}
