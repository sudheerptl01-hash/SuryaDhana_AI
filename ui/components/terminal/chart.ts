/**
 * SVG chart helpers for the terminal pages (C1-trader-ux-17). Pure functions, no React, no imports, so they
 * run under plain node in ui/components/__tests__/pages.check.ts.
 *
 * Charts are drawn in CSS pixels (see `useChartSize` in ./index.tsx): one SVG user unit = one CSS px, so axis
 * text keeps its 9–11 px size at every window width instead of growing with the viewBox. These helpers pick
 * round tick values, thin labels so they never overlap, and give every axis one unit.
 */

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
