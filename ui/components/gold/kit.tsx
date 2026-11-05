'use client'

/**
 * GOLD page building blocks on top of the terminal kit (PLAN a.1, §f): every panel carries value · source · as-of ·
 * lag chip, a badge from the catalog, an "about" popover from the catalog row and the [B]/[P] micro-copy line.
 * Shared by every sub-view (B4A HEALTH/DAILY/WEEKLY/MONTHLY/CONTRACTS, B4B POSITIONING/PHYSICAL/MACRO, B5 LEARN).
 *
 * Colour rule (PLAN §f.3): `BadgeChip` and `LagChipEl` return tones from lib/gold/format (context = muted); the only
 * green/red on the page are price changes and the arithmetic fair-vs-live comparison.
 */
import { apiError } from '@/lib/errors'
import { useCallback, useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Chip, Dot, Panel, T } from '@/components/terminal'
import { NO_VERDICT, badgeSpec, dayLabel, lagChip, parseIso, publishGate, type Gate, type Tone } from '@/lib/gold/format'
import type { Badge, CatalogRow, Freshness, Layer } from '@/lib/gold/types'

export const toneColor = (tone: Tone): string =>
  tone === 'green' ? T.green : tone === 'red' ? T.red : tone === 'amber' ? T.amber : tone === 'cyan' ? T.cyan
    : tone === 'violet' ? T.violet : tone === 'text' ? T.text : T.muted

/** Evidence badge chip (PLAN §f.1): signal / context / arithmetic / heuristic, text from the catalog. */
export function BadgeChip({ badge, evidence, style }: { badge: Badge | string | null | undefined; evidence?: string | null; style?: CSSProperties }) {
  const b = badgeSpec(badge, evidence)
  return <Chip color={toneColor(b.tone)} title={b.title} style={{ fontSize: 9, padding: '1px 6px', ...style }}>{b.label}</Chip>
}

/** LIVE / DELAYED / STALE / OFFLINE chip for a block (PLAN 0.1 #10), with the as-of in the tooltip. */
export function LagChipEl({ freshness, maxAgeDays, style }: { freshness: Freshness | null | undefined; maxAgeDays?: number | null; style?: CSSProperties }) {
  const c = lagChip(freshness, maxAgeDays)
  const col = toneColor(c.tone)
  return (
    <span title={c.title} data-lag={c.label.split(' ')[0]}
      style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1, color: col,
               border: `1px solid ${col}55`, padding: '1px 6px', whiteSpace: 'nowrap', ...style }}>
      <Dot color={col} pulse={c.tone === 'green'} size={5} />{c.label}
    </span>
  )
}

/** "as of" text for a block: daily data shows its date, intraday shows the IST clock (PLAN 0.1 #10). */
export function asOfText(f: Freshness | null | undefined, reportDate?: string | null): string {
  if (reportDate) return `as of ${dayLabel(reportDate) || reportDate}`
  if (!f?.as_of) return ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(f.as_of)) return `as of ${dayLabel(f.as_of)}`      // a date: the day, not a clock
  const d = parseIso(f.as_of)                                                       // naive store strings are UTC
  if (!d) return `as of ${f.as_of}`
  return `as of ${d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })} IST`
}

/**
 * The §f.2 rendering gate for a panel: every catalog series it reads must carry a PUBLISH-CORE / PUBLISH-CONTEXT row
 * with a badge. 'no-verdict' names the first series that fails; 'unknown' when the catalog is not loaded (the panel
 * renders with a "catalog?" note instead of going blank); 'ok' otherwise. A panel with no series (links, derived-only
 * request-path arithmetic) is 'ok'.
 */
export function panelGate(catalog: Record<string, CatalogRow> | null | undefined, series: readonly string[] | null | undefined): { gate: Gate; series: string | null } {
  if (!series || series.length === 0) return { gate: 'ok', series: null }
  let unknown: string | null = null
  for (const id of series) {
    const g = publishGate(catalog, id)
    if (g === 'no-verdict') return { gate: 'no-verdict', series: id }
    if (g === 'unknown' && !unknown) unknown = id
  }
  return unknown ? { gate: 'unknown', series: unknown } : { gate: 'ok', series: null }
}

/** "no verdict — not published" placeholder (PLAN §f.2) for a series without a catalog verdict. */
export function NoVerdict({ what }: { what?: string }) {
  return (
    <div data-gold-noverdict style={{ padding: '10px 12px', fontSize: 11, color: T.muted, border: `1px dashed ${T.border}`, lineHeight: 1.5 }}>
      <span style={{ fontFamily: T.mono, letterSpacing: 1, textTransform: 'uppercase', color: T.dim }}>{NO_VERDICT}</span>
      {what && <span> · {what}</span>}
    </div>
  )
}

/** A term with the one-line definition on hover (dotted underline = a glossary term, PLAN a.1). */
export function Term({ children, def, style }: { children: ReactNode; def?: string | null; style?: CSSProperties }) {
  if (!def) return <>{children}</>
  return <span title={def} style={{ textDecoration: 'underline dotted', textDecorationColor: T.dim, textUnderlineOffset: 2, cursor: 'help', ...style }}>{children}</span>
}

/** The catalog "about" popover: publisher · cadence · lag · formula · pitfalls · verdict · terms. */
export function About({ row, title }: { row: CatalogRow | null | undefined; title?: string }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLSpanElement>(null)
  useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])
  return (
    <span ref={ref} style={{ position: 'relative', display: 'inline-flex' }}>
      <Chip color={T.cyan} onClick={() => setOpen(o => !o)} title={row ? `About ${row.name}` : 'About this panel'} aria-label="about this data"
        style={{ fontSize: 9, padding: '1px 5px' }}>?</Chip>
      {open && (
        <div role="dialog" aria-label="about this data"
          style={{ position: 'absolute', top: 22, right: 0, width: 340, zIndex: 20, background: T.panel, border: `1px solid ${T.cyan}`, padding: '8px 10px',
                   fontSize: 10.5, color: T.text, lineHeight: 1.5, boxShadow: '0 8px 24px rgba(0,0,0,.6)', textAlign: 'left', whiteSpace: 'normal' }}>
          <div style={{ fontFamily: T.display, fontSize: 11, letterSpacing: 1.2, color: T.cyan, marginBottom: 4 }}>{(title ?? row?.name ?? 'ABOUT').toUpperCase()}</div>
          {!row && <div style={{ color: T.muted }}>No catalog row for this panel yet: the data dictionary is written by the ingest (gold_series_catalog).</div>}
          {row && <>
            <Row k="Publisher" v={<>{row.publisher} <a href={row.url} target="_blank" rel="noreferrer" style={{ color: T.amber }}>↗</a></>} />
            <Row k="Cadence" v={`${row.freq}${row.publish_time_ist ? ` · ${row.publish_time_ist} IST` : ''}`} />
            {row.lag_note && <Row k="Lag" v={row.lag_note} />}
            {row.pro_note && <Row k="Definition" v={row.pro_note} />}
            {row.how_pros_use_it && <Row k="Pros use it" v={row.how_pros_use_it} />}
            <Row k="Verdict" v={<>{row.verdict}{row.verdict_reason ? ` — ${row.verdict_reason}` : ''} · <BadgeChip badge={row.badge} /></>} />
            {row.evidence && <Row k="Evidence" v={row.evidence} />}
            {row.terms && <Row k="Terms" v={row.terms} />}
            <Row k="Series" v={<span style={{ fontFamily: T.mono }}>{row.series_id} · {row.unit}</span>} />
          </>}
        </div>
      )}
    </span>
  )
}

function Row({ k, v }: { k: string; v: ReactNode }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '72px 1fr', gap: 6, padding: '2px 0', borderBottom: `1px dashed ${T.border}` }}>
      <span style={{ color: T.muted, fontSize: 9.5, letterSpacing: .8, textTransform: 'uppercase' }}>{k}</span>
      <span>{v}</span>
    </div>
  )
}

export interface GoldPanelProps {
  /** PLAN panel id (h.verdict, d.24h …): rendered as a data attribute for the audit and the repetition test */
  id: string
  title: ReactNode
  subtitle?: ReactNode
  badge?: Badge | string | null
  evidence?: string | null
  freshness?: Freshness | null
  maxAgeDays?: number | null
  reportDate?: string | null
  catalogRow?: CatalogRow | null
  /** the catalog series ids this panel reads: the §f.2 gate blanks the body ("no verdict — not published") when any
   *  lacks a PUBLISH verdict; the first one's row feeds the About popover when `catalogRow` is not given */
  series?: readonly string[]
  catalog?: Record<string, CatalogRow> | null
  /** [B] plain line / [P] exact definition; the active one shows under the header (PLAN a.1) */
  layer?: Layer
  copyB?: ReactNode
  copyP?: ReactNode
  right?: ReactNode
  accent?: string
  pad?: number
  style?: CSSProperties
  bodyStyle?: CSSProperties
  children?: ReactNode
}

/** A panel with the gold chrome: title · badge · lag chip · about; the micro-copy line; the body. */
export function GoldPanel({ id, title, subtitle, badge, evidence, freshness, maxAgeDays, reportDate, catalogRow, series, catalog, layer = 'B', copyB, copyP,
  right, accent = T.amber, pad = 12, style, bodyStyle, children }: GoldPanelProps) {
  const copy = layer === 'P' ? (copyP ?? copyB) : (copyB ?? copyP)
  const asOf = asOfText(freshness, reportDate)
  const gate = panelGate(catalog, series)
  const row = catalogRow ?? (series?.length && catalog ? (series.map(s => catalog[s]).find(Boolean) ?? null) : null)
  // the subtitle and the as-of live in their own wrapping row under the header: the kit's header never wraps, so a
  // narrow panel with four chips would otherwise squeeze the subtitle into a one-word-per-line column
  return (
    <Panel title={title} accent={accent} pad={0} style={style}
      right={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end', minWidth: 0 }}>
        {right}
        {badge && <BadgeChip badge={badge} evidence={evidence} />}
        {/* an explicit `maxAgeDays={null}` means "no catalog cap": a block whose age is its OLDEST input (the verdict's COT, 5 d)
            must not read STALE against the max_age of its first series (COMEX_GC_FRONT, 4 d) — C-DATA-18 */}
        {freshness !== undefined && <LagChipEl freshness={freshness} maxAgeDays={maxAgeDays === undefined ? row?.max_age_days : maxAgeDays} />}
        <About row={row} title={typeof title === 'string' ? title : undefined} />
      </span>}>
      <div data-gold-panel={id} data-gold-gate={gate.gate} style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {(subtitle || asOf || gate.gate === 'unknown') && (
          <div data-gold-meta style={{ padding: '4px 12px', fontSize: 10, color: T.muted, letterSpacing: .4, lineHeight: 1.5, borderBottom: `1px solid ${T.border}`, background: '#080b10' }}>
            {subtitle}{asOf && <span style={{ color: T.dim }}>{subtitle ? ' · ' : ''}{asOf}</span>}
            {gate.gate === 'unknown' && <span style={{ color: T.dim }} title={`the catalog is not loaded: the PUBLISH verdict of ${gate.series} could not be checked`}>{subtitle || asOf ? ' · ' : ''}catalog?</span>}
          </div>
        )}
        {copy && (
          <div data-gold-copy={layer} style={{ padding: '5px 12px', fontSize: 10.5, color: T.muted, lineHeight: 1.5, borderBottom: `1px solid ${T.border}`, background: '#07090d' }}>
            <span style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1, color: layer === 'P' ? T.violet : T.cyan, marginRight: 6 }}>[{layer}]</span>{copy}
          </div>
        )}
        {gate.gate === 'no-verdict'
          ? <div style={{ padding: Math.max(pad, 8) }}><NoVerdict what={`${gate.series} has no PUBLISH verdict in the catalog (PLAN §f.2)`} /></div>
          : <div style={{ padding: pad, minWidth: 0, ...bodyStyle }}>{children}</div>}
      </div>
    </Panel>
  )
}

/** Small labelled number for strips: label above, value, sub-line. Neutral by default (context metrics). */
export function Cell({ label, value, sub, color = T.text, title, mono = true, style }: {
  label: ReactNode; value: ReactNode; sub?: ReactNode; color?: string; title?: string; mono?: boolean; style?: CSSProperties
}) {
  return (
    <div title={title} style={{ minWidth: 0, ...style }}>
      <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.2, textTransform: 'uppercase', color: T.muted, whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ fontFamily: mono ? T.mono : T.display, fontSize: 14, fontWeight: 600, color, marginTop: 2, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: T.dim, marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</div>}
    </div>
  )
}

export type Load<T> = { data: T | null; error: string | null; loading: boolean; reload: () => void }

/**
 * Load a block on its own (every sub-view panel loads independently, PLAN a.1), latest request wins, optional polling
 * while the document is visible. A failed poll keeps the last data and records the error (degrade-honest).
 */
export function useGoldLoad<T>(fn: () => Promise<{ data: T }>, deps: unknown[], pollMs?: number): Load<T> {
  const [st, set] = useState<{ data: T | null; error: string | null; loading: boolean }>({ data: null, error: null, loading: true })
  const seq = useRef(0)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const reload = useCallback(() => {
    const mine = ++seq.current
    set(s => ({ ...s, loading: true }))
    fnRef.current().then(r => { if (mine === seq.current) set({ data: r.data, error: null, loading: false }) })
      .catch((e: unknown) => { if (mine === seq.current) set(s => ({ data: s.data, error: apiError(e, 'unavailable'), loading: false })) })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { reload() }, [reload])
  useEffect(() => {
    if (!pollMs) return
    const iv = setInterval(() => { if (typeof document === 'undefined' || !document.hidden) reload() }, pollMs)
    return () => clearInterval(iv)
  }, [pollMs, reload])
  useEffect(() => () => { seq.current++ }, [])
  return { ...st, reload }
}

/** Loading / error wrapper that never blanks a panel that already has data. */
export function Pending<T>({ s, label, children }: { s: Load<T>; label?: string; children: ReactNode }) {
  if (s.loading && s.data == null) return <div style={{ fontSize: 11, color: T.dim, padding: '6px 0' }}>Loading{label ? ` ${label}` : ''}…</div>
  if (s.error && s.data == null) return <div style={{ fontSize: 11, color: T.amber, padding: '6px 0' }}>Unavailable: {s.error}</div>
  return <>{children}</>
}

/** A "GOLD › <sub>" style navigation chip. */
export function GoChip({ label, onClick, title }: { label: string; onClick: () => void; title?: string }) {
  return <Chip color={T.amber} onClick={onClick} title={title}>{label} ›</Chip>
}
