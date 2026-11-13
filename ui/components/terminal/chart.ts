/**
 * SVG chart helpers for the terminal pages (C1-trader-ux-17). Pure functions through `nearestIndex`, so they
 * run under plain node in ui/components/__tests__/pages.check.ts and terminal/__tests__/interactive.check.ts
 * (the react import below also loads under plain node — it is dependency-free CJS).
 *
 * Charts are drawn in CSS pixels (see `useChartSize` in ./index.tsx): one SVG user unit = one CSS px, so axis
 * text keeps its 9–11 px size at every window width instead of growing with the viewBox. These helpers pick
 * round tick values, thin labels so they never overlap, and give every axis one unit.
 *
 * SVG kit v2 (FINAL ROUND W3, charts/PLAN.md §4) sits at the end: `useChartInteraction(ref, domain)` gives any
 * SVG chart wheel+pinch x-zoom, drag pan, double-click reset and a nearest-point crosshair; `Crosshair` draws
 * the crosshair lines (createElement, no JSX, so this file stays .ts).
 */
import { createElement, useEffect, useRef, useState, type ReactElement } from 'react'

/** Width of `text` in a monospace face at `fontPx` (JetBrains Mono advance ≈ 0.6 em). */
export function textWidth(text: string, fontPx: number): number {
  return Array.from(text).length * fontPx * 0.6
}

/**
 * Chart height for a measured width: the chart keeps the aspect ratio it was designed with (baseW × baseH),
 * clamped to [minRatio, maxRatio] × baseH so very wide or narrow panels stay readable. Integer px.
 */
export function chartHeight(w: number, baseW: number, baseH: number, minRatio = 0.8, maxRatio = 1.6): number {
  if (!(w > 0) || !(baseW > 0)) return Math.round(baseH)
  const h = (baseH * w) / baseW
  return Math.round(Math.min(baseH * maxRatio, Math.max(baseH * minRatio, h)))
}

/** A 'nice' step (1, 2, 2.5 or 5 × 10^k) giving at most `maxTicks` intervals over `span`. */
export function niceStep(span: number, maxTicks = 5): number {
  if (!(span > 0) || !Number.isFinite(span)) return 1
  const raw = span / Math.max(1, maxTicks)
  const mag = 10 ** Math.floor(Math.log10(raw))
  for (const m of [1, 2, 2.5, 5, 10]) {
    if (m * mag >= raw - 1e-12) return m * mag
  }
  return 10 * mag
}

/** Decimals needed to print multiples of `step` exactly (5 → 0, 2.5 → 1, 0.25 → 2). */
export function stepDecimals(step: number): number {
  if (!(step > 0) || !Number.isFinite(step)) return 0
  for (let dp = 0; dp <= 6; dp++) {
    if (Math.abs(Math.round(step * 10 ** dp) - step * 10 ** dp) < 1e-6) return dp
  }
  return 6
}

/** Round tick values inside [lo, hi] (inclusive), at most about `maxTicks` + 1 of them. */
export function niceTicks(lo: number, hi: number, maxTicks = 5): number[] {
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return []
  if (hi < lo) [lo, hi] = [hi, lo]
  if (hi === lo) return [lo]
  const step = niceStep(hi - lo, maxTicks)
  const dp = stepDecimals(step)
  const out: number[] = []
  const eps = step * 1e-9
  for (let v = Math.ceil((lo - eps) / step) * step; v <= hi + eps; v += step) {
    const r = Number(v.toFixed(dp))
    out.push(Object.is(r, -0) ? 0 : r)
    if (out.length > 50) break
  }
  return out
}

/** Round ticks plus the decimals that print them distinctly: niceAxis(10.2, 11.5, 3) → {ticks: [10.5, 11, 11.5], dp: 1}. */
export function niceAxis(lo: number, hi: number, maxTicks = 5): { ticks: number[]; dp: number; step: number } {
  const step = niceStep(Math.abs(hi - lo), maxTicks)
  return { ticks: niceTicks(lo, hi, maxTicks), dp: stepDecimals(step), step }
}

/**
 * Round ticks for a value axis `plotPx` tall that maps [lo, hi] (the PADDED range the chart draws, so a tick in the
 * headroom is used too): about one label per `minGapPx` (3 to 8 of them) and never fewer than 3 when the range has
 * room for them (R11: DERV axes often showed only 2 labels and no negative label on a negative basis).
 */
export function axisTicks(lo: number, hi: number, plotPx: number, minGapPx = 30): { ticks: number[]; dp: number; step: number } {
  const want = Math.max(3, Math.min(8, Math.floor((Number.isFinite(plotPx) ? plotPx : 0) / minGapPx)))
  let a = niceAxis(lo, hi, want)
  for (let k = want + 1; a.ticks.length < 3 && k <= want + 6; k++) a = niceAxis(lo, hi, k)
  return a
}

/** Every k-th item so that labels `pitchPx` apart are at least `minGapPx` apart (k ≥ 1). */
export function labelEvery(pitchPx: number, minGapPx: number): number {
  if (!(pitchPx > 0)) return 1
  return Math.max(1, Math.ceil(minGapPx / pitchPx))
}

/**
 * Indices of categorical items (e.g. option strikes) to label on an axis of `n` items `pitchPx` apart.
 * `must` indices (ATM, OI walls) are always labelled; regular labels sit every k items (aligned to multiples
 * of k, so they land on round strikes) and are dropped when they would crowd a `must` label.
 */
export function pickAxisLabels(n: number, pitchPx: number, minGapPx: number, must: number[] = []): number[] {
  if (n <= 0) return []
  const keep = [...new Set(must.filter(i => Number.isInteger(i) && i >= 0 && i < n))]
  const k = labelEvery(pitchPx, minGapPx)
  const minItems = Math.ceil(minGapPx / Math.max(pitchPx, 1e-9))
  const out = new Set(keep)
  for (let i = 0; i < n; i += k) {
    if (keep.some(m => Math.abs(m - i) < minItems)) continue
    out.add(i)
  }
  return [...out].sort((a, b) => a - b)
}

/**
 * Like pickAxisLabels, for items that carry values (option strikes): regular labels land on ROUND values (multiples
 * of a nice step ≥ k × the value spacing, e.g. every 200 or 250 points on NIFTY), `must` items are always kept, and
 * no regular label is placed closer than `minGapPx` to any label already chosen (greedy, left to right). Items are
 * drawn `pitchPx` apart by index, so gaps are measured by index, which also holds when some values are missing.
 */
export function pickRoundLabels(values: number[], pitchPx: number, minGapPx: number, must: number[] = []): number[] {
  const n = values.length
  if (n <= 0) return []
  const keep = [...new Set(must.filter(i => Number.isInteger(i) && i >= 0 && i < n))]
  const diffs = values.slice(1).map((v, i) => v - values[i]).filter(d => d > 0)
  const unit = diffs.length ? Math.min(...diffs) : 1
  const step = niceStep(labelEvery(pitchPx, minGapPx) * unit, 1)
  const out = [...keep]
  const clear = (i: number) => out.every(j => Math.abs(i - j) * pitchPx >= minGapPx)
  for (let i = 0; i < n; i++) {
    const q = values[i] / step
    if (Math.abs(q - Math.round(q)) < 1e-9 && clear(i)) out.push(i)
  }
  return out.sort((a, b) => a - b)
}

/**
 * Greedy collision avoidance for point labels: each label (centre x, width w) goes to the lowest row in which
 * it does not overlap the previous label by less than `gap` px. Returns the row index per input item (0 =
 * the base row), in input order.
 */
export function staggerRows(items: { x: number; w: number }[], gap = 4): number[] {
  const order = items.map((it, i) => ({ ...it, i })).sort((a, b) => a.x - b.x)
  const rowEnds: number[] = []
  const rows = new Array<number>(items.length).fill(0)
  for (const it of order) {
    const left = it.x - it.w / 2
    let r = rowEnds.findIndex(end => end + gap <= left)
    if (r < 0) { r = rowEnds.length; rowEnds.push(-Infinity) }
    rowEnds[r] = it.x + it.w / 2
    rows[it.i] = r
  }
  return rows
}

/** One unit for a whole rupee axis, chosen from its largest magnitude: Cr, L, K or plain rupees. */
export interface AxisUnit { div: number; suffix: string }
export function rupeeAxisUnit(values: number[]): AxisUnit {
  const m = Math.max(0, ...values.filter(Number.isFinite).map(v => Math.abs(v)))
  if (m >= 1e7) return { div: 1e7, suffix: ' cr' }
  if (m >= 1e5) return { div: 1e5, suffix: 'L' }
  if (m >= 1e3) return { div: 1e3, suffix: 'K' }
  return { div: 1, suffix: '' }
}

/** Format a tick in its axis unit with the decimals the tick step needs (U+2212 minus): −0.5L, 1.25L, 0. */
export function fmtAxisRupees(v: number, unit: AxisUnit, step: number): string {
  const dp = Math.min(2, stepDecimals(step / unit.div))
  const x = v / unit.div
  if (Number(Math.abs(x).toFixed(dp)) === 0) return '₹0'
  const body = Math.abs(x).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return `${x < 0 ? '−' : ''}₹${body}${unit.suffix}`
}

// ── SVG kit v2: interaction math (pure — node-checked) ───────────────────────────────────────────────

/** A visible x-domain in DATA units (spot for a payoff, strike for a smile, DTE for the rollover curve). */
export interface XDomain { min: number; max: number }

/** `view` clamped inside `full` without changing its span (span itself capped at full's). */
export function clampDomain(view: XDomain, full: XDomain): XDomain {
  const fullSpan = full.max - full.min
  let span = Math.min(Math.abs(view.max - view.min), fullSpan)
  if (!(span > 0) || !Number.isFinite(span)) span = fullSpan
  let min = Math.min(view.min, view.max)
  if (min < full.min) min = full.min
  if (min + span > full.max) min = full.max - span
  return { min, max: min + span }
}

/**
 * Zoom `view` by `factor` (< 1 narrows) about `focus` (0..1 across the view, the pointer's position), the span
 * clamped to [minSpan, full span] and the result kept inside `full`.
 */
export function zoomDomain(view: XDomain, full: XDomain, factor: number, focus: number, minSpan: number): XDomain {
  const span = view.max - view.min
  const fullSpan = full.max - full.min
  if (!(span > 0) || !(fullSpan > 0) || !Number.isFinite(factor) || factor <= 0) return clampDomain(view, full)
  const f = Math.max(0, Math.min(1, Number.isFinite(focus) ? focus : 0.5))
  const next = Math.max(Math.min(minSpan > 0 ? minSpan : 0, fullSpan), Math.min(fullSpan, span * factor))
  const anchor = view.min + f * span
  return clampDomain({ min: anchor - f * next, max: anchor + (1 - f) * next }, full)
}

/** Pan `view` by `dxFrac` of its span (+ = later/right), kept inside `full`. */
export function panDomain(view: XDomain, full: XDomain, dxFrac: number): XDomain {
  const span = view.max - view.min
  const dx = Number.isFinite(dxFrac) ? dxFrac * span : 0
  return clampDomain({ min: view.min + dx, max: view.max + dx }, full)
}

/** Index of the finite value in `xs` nearest to `x` (−1 when none). Linear: kit charts hold ≲ a few hundred points. */
export function nearestIndex(xs: readonly number[], x: number): number {
  if (!Number.isFinite(x)) return -1
  let best = -1
  let bestD = Infinity
  for (let i = 0; i < xs.length; i++) {
    const v = xs[i]
    if (!Number.isFinite(v)) continue
    const d = Math.abs(v - x)
    if (d < bestD) { bestD = d; best = i }
  }
  return best
}

// ── SVG kit v2: the interaction hook + crosshair fragment ────────────────────────────────────────────

export interface ChartInteractionOpts {
  /** data-x of each point (same order as the chart draws them) for nearest-point crosshair snapping */
  points?: readonly number[]
  /** smallest zoom span as a fraction of the full domain (default 0.02) */
  minSpanFrac?: number
  /** fired when the snapped point changes (and with nulls when the pointer leaves) */
  onCrosshair?: (i: number | null, x: number | null) => void
}

export interface ChartInteraction {
  /** render with THIS visible x-domain instead of the full one */
  view: XDomain
  /** true once the user zoomed or panned away from the full domain */
  zoomed: boolean
  /** the snapped point: its index in `points` and its data-x (null while the pointer is off the chart) */
  cursor: { i: number; x: number } | null
  /** back to the full domain (double-click does this too) */
  reset: () => void
  /** call every render with the plot box inside the svg (CSS px): events map px → data through it */
  setPlot: (left: number, width: number) => void
}

/**
 * Wheel + pinch x-zoom, drag pan, double-click reset and a nearest-point crosshair for an SVG chart
 * (charts/PLAN.md §4, SVG kit v2). `ref` is the <svg>'s (or its wrapper's) ref object; `domain` is the FULL
 * x-domain of the data. The chart renders its x-scale from the returned `view`, reports its plot box through
 * `setPlot` each render, and prints `cursor`'s values in the panel legend (ExpandableChart's slot) — values are
 * always readable, never tooltip-only. Listeners are native (wheel non-passive, so the page never scrolls
 * while zooming a chart); touch: one pointer drags, two pinch.
 */
export function useChartInteraction(
  ref: { readonly current: Element | null },
  domain: XDomain,
  opts: ChartInteractionOpts = {},
): ChartInteraction {
  const [view, setView] = useState<XDomain>(() => ({ ...domain }))
  const [zoomed, setZoomed] = useState(false)
  const [cursor, setCursor] = useState<{ i: number; x: number } | null>(null)

  // latest values for the native event handlers (attached once)
  const st = useRef({
    view, zoomed, domain, opts,
    plot: { left: 0, width: 1 },
    drag: null as { px: number; view: XDomain; moved: boolean } | null,
    pinch: null as { d: number; view: XDomain } | null,
    pointers: new Map<number, number>(),   // pointerId → clientX
    cursorI: null as number | null,
  })
  st.current.view = view
  st.current.zoomed = zoomed
  st.current.opts = opts

  // a NEW full domain (new data): re-clamp a zoomed view, follow it when not zoomed
  const dKey = `${domain.min}:${domain.max}`
  useEffect(() => {
    st.current.domain = domain
    setView(v => (st.current.zoomed ? clampDomain(v, domain) : { ...domain }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dKey])

  useEffect(() => {
    const el = ref.current
    if (!el || typeof window === 'undefined') return
    const s = st.current

    const frac = (clientX: number): number => {
      const r = el.getBoundingClientRect()
      const { left, width } = s.plot
      return width > 0 ? (clientX - r.left - left) / width : 0.5
    }
    const minSpan = () => (s.domain.max - s.domain.min) * (s.opts.minSpanFrac ?? 0.02)
    const apply = (next: XDomain) => {
      const full = s.domain
      const isFull = Math.abs(next.min - full.min) < 1e-9 && Math.abs(next.max - full.max) < 1e-9
      setView(next)
      setZoomed(!isFull)
    }
    const report = (i: number | null, x: number | null) => {
      if (i === s.cursorI) return
      s.cursorI = i
      setCursor(i == null || x == null ? null : { i, x })
      s.opts.onCrosshair?.(i, x)
    }
    const hover = (clientX: number) => {
      const f = frac(clientX)
      const x = s.view.min + f * (s.view.max - s.view.min)
      const pts = s.opts.points
      if (!pts || !pts.length || f < -0.02 || f > 1.02) { report(null, null); return }
      const i = nearestIndex(pts, x)
      if (i < 0) { report(null, null); return }
      report(i, pts[i])
    }

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const factor = Math.exp((e.deltaY || 0) * (e.ctrlKey ? 0.01 : 0.0022))   // ctrl = trackpad pinch
      apply(zoomDomain(s.view, s.domain, factor, frac(e.clientX), minSpan()))
    }
    const onDown = (e: PointerEvent) => {
      if (e.button !== 0 && e.pointerType === 'mouse') return
      s.pointers.set(e.pointerId, e.clientX)
      try { (el as HTMLElement).setPointerCapture?.(e.pointerId) } catch { /* detached */ }
      if (s.pointers.size === 2) {
        const [a, b] = [...s.pointers.values()]
        s.pinch = { d: Math.max(1, Math.abs(a - b)), view: { ...s.view } }
        s.drag = null
      } else {
        s.drag = { px: e.clientX, view: { ...s.view }, moved: false }
      }
    }
    const onMove = (e: PointerEvent) => {
      if (s.pointers.has(e.pointerId)) s.pointers.set(e.pointerId, e.clientX)
      if (s.pinch && s.pointers.size >= 2) {
        const [a, b] = [...s.pointers.values()]
        const d = Math.max(1, Math.abs(a - b))
        const factor = s.pinch.d / d
        const mid = frac((a + b) / 2)
        apply(zoomDomain(s.pinch.view, s.domain, factor, mid, minSpan()))
        return
      }
      if (s.drag) {
        const dxPx = e.clientX - s.drag.px
        if (Math.abs(dxPx) > 2) s.drag.moved = true
        if (s.drag.moved) {
          apply(panDomain(s.drag.view, s.domain, s.plot.width > 0 ? -dxPx / s.plot.width : 0))
          return
        }
      }
      hover(e.clientX)
    }
    const onUp = (e: PointerEvent) => {
      s.pointers.delete(e.pointerId)
      if (s.pointers.size < 2) s.pinch = null
      if (s.pointers.size === 0) s.drag = null
    }
    const onLeave = () => { s.drag = null; s.pinch = null; s.pointers.clear(); report(null, null) }
    const onDbl = () => { apply({ ...s.domain }) }

    el.addEventListener('wheel', onWheel as EventListener, { passive: false })
    el.addEventListener('pointerdown', onDown as EventListener)
    el.addEventListener('pointermove', onMove as EventListener)
    el.addEventListener('pointerup', onUp as EventListener)
    el.addEventListener('pointercancel', onUp as EventListener)
    el.addEventListener('pointerleave', onLeave as EventListener)
    el.addEventListener('dblclick', onDbl as EventListener)
    return () => {
      el.removeEventListener('wheel', onWheel as EventListener)
      el.removeEventListener('pointerdown', onDown as EventListener)
      el.removeEventListener('pointermove', onMove as EventListener)
      el.removeEventListener('pointerup', onUp as EventListener)
      el.removeEventListener('pointercancel', onUp as EventListener)
      el.removeEventListener('pointerleave', onLeave as EventListener)
      el.removeEventListener('dblclick', onDbl as EventListener)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref.current])

  return {
    view,
    zoomed,
    cursor,
    reset: () => { setView({ ...st.current.domain }); setZoomed(false) },
    setPlot: (left: number, width: number) => { st.current.plot = { left, width: Math.max(1, width) } },
  }
}

/**
 * Crosshair lines for an SVG chart (createElement — this file stays .ts): a dashed vertical at `x`, an optional
 * dashed horizontal at `y`, and a dot where they meet. Coordinates in the chart's CSS px. Render it last so it
 * sits above the series; print the snapped values in the panel legend, never only here.
 */
export function Crosshair({ x, y = null, top, height, left, width, color = '#8691a5' }: {
  x: number | null; y?: number | null; top: number; height: number; left: number; width: number; color?: string
}): ReactElement | null {
  if (x == null || !Number.isFinite(x)) return null
  const kids: ReactElement[] = [
    createElement('line', { key: 'v', x1: x, x2: x, y1: top, y2: top + height, stroke: color, strokeDasharray: '3 3', opacity: 0.8 }),
  ]
  if (y != null && Number.isFinite(y)) {
    kids.push(createElement('line', { key: 'h', x1: left, x2: left + width, y1: y, y2: y, stroke: color, strokeDasharray: '3 3', opacity: 0.8 }))
    kids.push(createElement('circle', { key: 'c', cx: x, cy: y, r: 2.5, fill: color }))
  }
  return createElement('g', { 'data-sd-crosshair': '1', style: { pointerEvents: 'none' } }, kids)
}
