'use client'

/**
 * ExpandableChart — the shell EVERY kit chart (LWC or SVG) sits in (FINAL ROUND W3, charts/PLAN.md §4):
 * panel header = title · badges · SourceChip · FIT · PNG ⤓ · ⛶ EXPAND · crosshair legend slot; on expand the
 * same child is PORTALED into a fixed-inset overlay (Esc or ⛶ closes, body scroll locked, the child re-measured
 * at the overlay size). No chart logic in here — it composes the existing Panel / Chip / BadgeChip.
 *
 *   <ExpandableChart title="IV30 (CONSTANT MATURITY)" badges={[{ label: 'arithmetic' }]}
 *                    source={sourceInfo} legend={legendNode} actions={{ fit, png, csv }}
 *                    height={220}>{({ width, height }) => <...chart.../>}</ExpandableChart>
 *
 * The legend slot: `legend` is the resting content; a child that reports crosshair values overwrites it live
 * through the shell context (useChartShell().setLegend) — values are always readable there, never tooltip-only.
 * InteractiveSeries registers its own FIT (fitContent) and PNG (takeScreenshot) through the same context, so
 * `actions` is only needed for extras (csv) or for SVG children that implement their own export.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Z } from '@/lib/z'
import { BadgeChip, Chip, Panel, T } from './index'
import type { Badge, SourceInfo } from './source'

// ── shell context (chart children talk to the header through this) ───────────────────────────────────

export interface ChartShellActions { fit?: () => void; png?: () => void; csv?: () => void }

export interface ChartShell {
  /** overwrite the legend slot (null = back to the resting `legend` prop) */
  setLegend: (node: ReactNode) => void
  /** a chart child offers its FIT / PNG handlers; call the returned fn on unmount */
  registerActions: (a: ChartShellActions) => () => void
  /** the shell's title when it is a plain string (PNG file names) */
  title?: string
  expanded: boolean
}

const ShellCtx = createContext<ChartShell | null>(null)

/** The surrounding ExpandableChart, or null when the chart is mounted bare (everything then no-ops). */
export function useChartShell(): ChartShell | null {
  return useContext(ShellCtx)
}

// the legend updates on every crosshair move: it lives in a tiny store so ONLY the slot re-renders, never the chart
interface LegendStore { node: ReactNode; subs: Set<() => void> }

function LegendSlot({ store, resting }: { store: LegendStore; resting?: ReactNode }) {
  const [, bump] = useState(0)
  useEffect(() => {
    const sub = () => bump(x => x + 1)
    store.subs.add(sub)
    return () => { store.subs.delete(sub) }
  }, [store])
  const node = store.node ?? resting
  return (
    <span data-sd-chart-legend style={{ fontFamily: T.mono, fontSize: 10.5, color: T.muted, whiteSpace: 'nowrap',
                                        overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 520, minWidth: 0 }}>
      {node ?? '—'}
    </span>
  )
}

// ── the shell ─────────────────────────────────────────────────────────────────────────────────────────

export interface ChartBadge { label: Badge | string; note?: string | null }
export interface ChartSize { width: number; height: number }

export function ExpandableChart({ title, badges = [], source, legend, actions, height = 220, children, accent, style }: {
  title: ReactNode
  /** evidence badges (context / arithmetic / heuristic — a `signal` badge does not exist) */
  badges?: ChartBadge[]
  /** the panel's SourceChip (`sourceOf(payload.as_of, { source })`); null = no chip yet */
  source?: SourceInfo | null
  /** resting legend content (a crosshair overwrites it live through the shell context) */
  legend?: ReactNode
  /** extra header actions; a chart child's registered FIT/PNG fill the gaps */
  actions?: ChartShellActions
  /** collapsed chart height in px (the overlay re-measures to the window) */
  height?: number
  children: ReactNode | ((size: ChartSize) => ReactNode)
  accent?: string
  style?: CSSProperties
}) {
  const [expanded, setExpanded] = useState(false)
  const [childActions, setChildActions] = useState<ChartShellActions | null>(null)
  const [size, setSize] = useState<ChartSize>({ width: 0, height })
  const bodyRef = useRef<HTMLDivElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)
  const placeholderH = useRef(0)
  const legendStore = useRef<LegendStore>({ node: null, subs: new Set() })

  const setLegend = useCallback((node: ReactNode) => {
    legendStore.current.node = node
    legendStore.current.subs.forEach(f => f())
  }, [])
  const registerActions = useCallback((a: ChartShellActions) => {
    setChildActions(a)
    return () => setChildActions(cur => (cur === a ? null : cur))
  }, [])
  const ctx = useMemo<ChartShell>(() => ({
    setLegend, registerActions, expanded, title: typeof title === 'string' ? title : undefined,
  }), [setLegend, registerActions, expanded, title])

  // measure the chart box (width always; height matters in the overlay, where the box flexes)
  useEffect(() => {
    const el = bodyRef.current
    if (!el) return
    const read = () => {
      const r = el.getBoundingClientRect()
      const w = Math.floor(r.width)
      const h = expanded ? Math.max(200, Math.floor(r.height)) : height
      setSize(prev => (prev.width === w && prev.height === h ? prev : { width: w, height: h }))
    }
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [expanded, height])

  // Esc closes; body scroll locked while the overlay is up
  useEffect(() => {
    if (!expanded || typeof document === 'undefined') return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setExpanded(false) } }
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    window.addEventListener('keydown', onKey, true)
    return () => { document.body.style.overflow = prev; window.removeEventListener('keydown', onKey, true) }
  }, [expanded])

  const fit = actions?.fit ?? childActions?.fit
  const png = actions?.png ?? childActions?.png
  const csv = actions?.csv
  const toggle = () => {
    if (!expanded) placeholderH.current = panelRef.current?.offsetHeight ?? 0
    setExpanded(x => !x)
  }
  const btn = (label: string, onClick: (() => void) | undefined, tip: string, aria: string) =>
    onClick ? <Chip color={T.cyan} onClick={onClick} title={tip} aria-label={aria}
                    style={{ fontSize: 9, padding: '1px 6px' }}>{label}</Chip> : null

  const headerRight = (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
      <LegendSlot store={legendStore.current} resting={legend} />
      {btn('FIT', fit, 'Fit the whole series back into view', 'fit chart')}
      {btn('PNG ⤓', png, 'Save this chart as a PNG image', 'download chart as png')}
      {btn('CSV ⤓', csv, 'Download this chart’s data as CSV', 'download chart data as csv')}
      <Chip color={T.cyan} onClick={toggle} aria-label={expanded ? 'close the expanded chart' : 'expand chart to full page'}
        title={expanded ? 'Close (Esc)' : 'Expand to a full-page view (Esc closes)'}
        style={{ fontSize: 9, padding: '1px 6px' }}>{expanded ? '✕ CLOSE' : '⛶'}</Chip>
    </span>
  )

  const panel = (
    <div ref={panelRef}
      style={expanded
        ? { position: 'fixed', inset: 12, zIndex: Z.modal + 1, display: 'flex', flexDirection: 'column', minHeight: 0 }
        : undefined}>
      <Panel title={title} accent={accent} source={source ?? null}
        right={<>
          {badges.map((b, i) => <BadgeChip key={i} badge={b.label} note={b.note ?? undefined} />)}
          {headerRight}
        </>}
        style={expanded ? { flex: 1, minHeight: 0, borderColor: T.borderHi } : style}
        bodyStyle={expanded ? { flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' } : undefined}>
        <div ref={bodyRef} data-sd-chart-box
          style={expanded ? { flex: 1, minHeight: 0 } : { height, minWidth: 0 }}>
          {typeof children === 'function' ? (size.width > 0 ? children(size) : null) : children}
        </div>
      </Panel>
    </div>
  )

  return (
    <ShellCtx.Provider value={ctx}>
      {expanded
        ? <>
            <div aria-hidden style={{ height: placeholderH.current || height }} />
            {typeof document !== 'undefined' && createPortal(
              <div role="dialog" aria-modal="true" aria-label={typeof title === 'string' ? `${title} — expanded chart` : 'expanded chart'}
                   onClick={e => { if (e.target === e.currentTarget) setExpanded(false) }}
                   style={{ position: 'fixed', inset: 0, zIndex: Z.modal, background: 'rgba(5,7,10,.88)' }}>
                {panel}
              </div>, document.body)}
          </>
        : panel}
    </ShellCtx.Provider>
  )
}
