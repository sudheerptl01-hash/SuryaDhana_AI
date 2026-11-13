/**
 * The ONE lightweight-charts theme for the terminal (charts/PLAN.md §4): the T tokens bound to the pure builder
 * in ./interactiveModel. Every InteractiveSeries chart calls `terminalChartOptions()` — no per-page LWC theme
 * objects in new code. C-TOKENS owns keeping this file in lockstep when the token pass lands (wave C): change
 * tokens here / in the T module, never inside a chart component.
 *
 * The TradingView attribution mark (layout.attributionLogo, default true in 4.2.3) is left ON — licence
 * attribution; do not override it here or per chart.
 */
import type { ChartOptions, DeepPartial } from 'lightweight-charts'
import { T } from '@/components/news/format'
import { buildChartTheme } from './interactiveModel'

/** The terminal's chart options (background, grid, dashed crosshair, mono axis text, scroll + scale on). */
export function terminalChartOptions(): DeepPartial<ChartOptions> {
  return buildChartTheme(T)
}

/** Series colours by position when a SeriesSpec names none: amber first (the accent), then cyan, violet, green. */
export const SERIES_FALLBACK: readonly string[] = [T.amber, T.cyan, T.violet, T.green, T.red, T.muted]

/** Candle colours (direction of a PRICE bar is the one place green/red is data, not advice). */
export const CANDLE_OPTIONS = {
  upColor: T.green,
  downColor: T.red,
  wickUpColor: T.green,
  wickDownColor: T.red,
  borderVisible: false,
} as const

/** Marker palette: results violet, expiry muted, anything else cyan (the vol/charts.tsx convention). */
export const MARKER_PALETTE = { results: T.violet, expiry: T.dim, default: T.cyan } as const

/** The band's masking colour (the area-pair's lower fill) — the panel ground the chart sits on. */
export const BAND_MASK: string = T.panel

/** Default band colour (the IV cone's p25–p75): violet, matching the SVG kit. */
export const BAND_COLOR: string = T.violet

/** Overlay-histogram colour (volume under candles) when a SeriesSpec names none. */
export const OVERLAY_COLOR: string = T.borderHi
