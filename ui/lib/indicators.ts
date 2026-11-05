/**
 * indicators.ts — reusable technical-indicator engine for all charts.
 *
 * Wraps the `technicalindicators` package behind a small, typed contract so any
 * lightweight-charts surface (stock modal, scanner, …) can render a fully
 * customizable indicator stack: price-pane overlays (MAs, Bollinger, VWAP) and
 * a synced oscillator sub-pane (RSI, MACD, Stochastic, ATR, CCI).
 *
 * Design goals:
 *   • Add new indicators by extending INDICATOR_DEFS only — no chart code edits.
 *   • Every indicator is parameterised (period, stdDev, …) and colour-customizable.
 *   • Outputs are pre-aligned to the chart's own time axis (right-aligned by index)
 *     so overlays line up regardless of warm-up length or bar count.
 */
import {
  SMA, EMA, WMA, BollingerBands, VWAP,
  RSI, MACD, Stochastic, ATR, CCI,
} from 'technicalindicators'

// ── Public types ─────────────────────────────────────────────────────────────

export type IndicatorKind =
  | 'sma' | 'ema' | 'wma' | 'bbands' | 'vwap'        // price-pane overlays
  | 'rsi' | 'macd' | 'stochastic' | 'atr' | 'cci'     // oscillator sub-pane

export type Pane = 'price' | 'oscillator'

export interface ParamSpec {
  key: string
  label: string
  min: number
  max: number
  step?: number
}

export interface IndicatorDef {
  kind: IndicatorKind
  label: string
  pane: Pane
  params: ParamSpec[]
  defaultParams: Record<string, number>
  defaultColor: string
  /** Fixed value bounds for the oscillator scale, when meaningful (e.g. RSI 0-100). */
  range?: [number, number]
  /** Reference guide lines drawn in the oscillator pane (e.g. RSI 30/70). */
  guides?: number[]
}

export interface IndicatorConfig {
  id: string
  kind: IndicatorKind
  params: Record<string, number>
  color: string
  visible: boolean
}

export interface Bar {
  time: any
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface LinePoint { time: any; value: number }

export interface IndicatorLine {
  id: string            // unique per drawn line: `${cfg.id}:${sub}`
  cfgId: string
  label: string
  color: string
  pane: Pane
  lineWidth: number
  /** 0 = solid, 1 = dotted, 2 = dashed (lightweight-charts LineStyle). */
  lineStyle: number
  data: LinePoint[]
}

// ── Registry — extend this to add indicators ─────────────────────────────────

export const INDICATOR_DEFS: Record<IndicatorKind, IndicatorDef> = {
  sma: {
    kind: 'sma', label: 'SMA — Simple MA', pane: 'price', defaultColor: '#3b82f6',
    params: [{ key: 'period', label: 'Period', min: 2, max: 400, step: 1 }],
    defaultParams: { period: 50 },
  },
  ema: {
    kind: 'ema', label: 'EMA — Exponential MA', pane: 'price', defaultColor: '#10b981',
    params: [{ key: 'period', label: 'Period', min: 2, max: 400, step: 1 }],
    defaultParams: { period: 21 },
  },
  wma: {
    kind: 'wma', label: 'WMA — Weighted MA', pane: 'price', defaultColor: '#f59e0b',
    params: [{ key: 'period', label: 'Period', min: 2, max: 400, step: 1 }],
    defaultParams: { period: 30 },
  },
  bbands: {
    kind: 'bbands', label: 'Bollinger Bands', pane: 'price', defaultColor: '#14b8a6',
    params: [
      { key: 'period', label: 'Period', min: 2, max: 200, step: 1 },
      { key: 'stdDev', label: 'Std Dev', min: 1, max: 4, step: 0.5 },
    ],
    defaultParams: { period: 20, stdDev: 2 },
  },
  vwap: {
    kind: 'vwap', label: 'VWAP (cumulative)', pane: 'price', defaultColor: '#eab308',
    params: [],
    defaultParams: {},
  },
  rsi: {
    kind: 'rsi', label: 'RSI', pane: 'oscillator', defaultColor: '#a855f7',
    params: [{ key: 'period', label: 'Period', min: 2, max: 100, step: 1 }],
    defaultParams: { period: 14 }, range: [0, 100], guides: [30, 70],
  },
  macd: {
    kind: 'macd', label: 'MACD', pane: 'oscillator', defaultColor: '#3b82f6',
    params: [
      { key: 'fast', label: 'Fast', min: 2, max: 100, step: 1 },
      { key: 'slow', label: 'Slow', min: 3, max: 200, step: 1 },
      { key: 'signal', label: 'Signal', min: 2, max: 100, step: 1 },
    ],
    defaultParams: { fast: 12, slow: 26, signal: 9 }, guides: [0],
  },
  stochastic: {
    kind: 'stochastic', label: 'Stochastic %K/%D', pane: 'oscillator', defaultColor: '#f59e0b',
    params: [
      { key: 'period', label: '%K Period', min: 2, max: 100, step: 1 },
      { key: 'signal', label: '%D Smooth', min: 1, max: 50, step: 1 },
    ],
    defaultParams: { period: 14, signal: 3 }, range: [0, 100], guides: [20, 80],
  },
  atr: {
    kind: 'atr', label: 'ATR — Avg True Range', pane: 'oscillator', defaultColor: '#06b6d4',
    params: [{ key: 'period', label: 'Period', min: 2, max: 100, step: 1 }],
    defaultParams: { period: 14 },
  },
  cci: {
    kind: 'cci', label: 'CCI', pane: 'oscillator', defaultColor: '#ec4899',
    params: [{ key: 'period', label: 'Period', min: 2, max: 100, step: 1 }],
    defaultParams: { period: 20 }, guides: [-100, 100],
  },
}

export const INDICATOR_ORDER: IndicatorKind[] = [
  'sma', 'ema', 'wma', 'bbands', 'vwap', 'rsi', 'macd', 'stochastic', 'atr', 'cci',
]

// ── Helpers ──────────────────────────────────────────────────────────────────

let _seq = 0
function uid(): string {
  _seq += 1
  return `ind_${Date.now().toString(36)}_${_seq}_${Math.random().toString(36).slice(2, 6)}`
}

/** Translate an indicator config into a short legend label, e.g. "SMA 50" or "BB 20·2". */
export function indicatorLabel(cfg: IndicatorConfig): string {
  const p = cfg.params
  switch (cfg.kind) {
    case 'sma': return `SMA ${p.period}`
    case 'ema': return `EMA ${p.period}`
    case 'wma': return `WMA ${p.period}`
    case 'bbands': return `BB ${p.period}·${p.stdDev}`
    case 'vwap': return 'VWAP'
    case 'rsi': return `RSI ${p.period}`
    case 'macd': return `MACD ${p.fast}/${p.slow}/${p.signal}`
    case 'stochastic': return `Stoch ${p.period}/${p.signal}`
    case 'atr': return `ATR ${p.period}`
    case 'cci': return `CCI ${p.period}`
    default: return cfg.kind
  }
}

/** Make a fresh config for `kind`, optionally overriding params/colour. */
export function makeIndicator(
  kind: IndicatorKind,
  params?: Record<string, number>,
  color?: string,
): IndicatorConfig {
  const def = INDICATOR_DEFS[kind]
  return {
    id: uid(),
    kind,
    params: { ...def.defaultParams, ...(params || {}) },
    color: color || def.defaultColor,
    visible: true,
  }
}

/** Default chart stack: the four classic moving averages, each colour-coded. */
export function defaultIndicators(): IndicatorConfig[] {
  return [
    makeIndicator('sma', { period: 20 }, '#f59e0b'),
    makeIndicator('sma', { period: 50 }, '#3b82f6'),
    makeIndicator('sma', { period: 150 }, '#a855f7'),
    makeIndicator('sma', { period: 200 }, '#ef4444'),
  ]
}

/** Right-align a value array onto the bars' time axis (skip NaN/undefined warm-up). */
function alignArray(values: Array<number | undefined>, bars: Bar[]): LinePoint[] {
  const offset = bars.length - values.length
  const out: LinePoint[] = []
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v == null || Number.isNaN(v)) continue
    const bar = bars[offset + i]
    if (bar) out.push({ time: bar.time, value: v })
  }
  return out
}

function alignObjects<T>(arr: T[], bars: Bar[], pick: (o: T) => number | undefined): LinePoint[] {
  const offset = bars.length - arr.length
  const out: LinePoint[] = []
  for (let i = 0; i < arr.length; i++) {
    const v = pick(arr[i])
    if (v == null || Number.isNaN(v)) continue
    const bar = bars[offset + i]
    if (bar) out.push({ time: bar.time, value: v })
  }
  return out
}

/** Lighten/darken a hex colour toward a target by `amt` (0-1) for band edges / %D. */
function shade(hex: string, amt: number): string {
  const m = hex.replace('#', '')
  if (m.length !== 6) return hex
  const n = parseInt(m, 16)
  const r = Math.round(((n >> 16) & 255) + (255 - ((n >> 16) & 255)) * amt)
  const g = Math.round(((n >> 8) & 255) + (255 - ((n >> 8) & 255)) * amt)
  const b = Math.round((n & 255) + (255 - (n & 255)) * amt)
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`
}

function line(
  cfg: IndicatorConfig, sub: string, label: string, color: string,
  pane: Pane, data: LinePoint[], lineWidth = 2, lineStyle = 0,
): IndicatorLine {
  return { id: `${cfg.id}:${sub}`, cfgId: cfg.id, label, color, pane, lineWidth, lineStyle, data }
}

// ── Computation ──────────────────────────────────────────────────────────────

/**
 * Compute one indicator config into one or more drawable lines.
 * Returns [] when there is insufficient history for the chosen period.
 */
export function computeIndicator(cfg: IndicatorConfig, bars: Bar[]): IndicatorLine[] {
  if (!cfg.visible || bars.length < 2) return []
  const close = bars.map(b => b.close)
  const high = bars.map(b => b.high)
  const low = bars.map(b => b.low)
  const volume = bars.map(b => b.volume || 0)
  const p = cfg.params
  const lbl = indicatorLabel(cfg)

  try {
    switch (cfg.kind) {
      case 'sma':
        return [line(cfg, 'm', lbl, cfg.color, 'price',
          alignArray(SMA.calculate({ period: p.period, values: close }), bars))]
      case 'ema':
        return [line(cfg, 'm', lbl, cfg.color, 'price',
          alignArray(EMA.calculate({ period: p.period, values: close }), bars))]
      case 'wma':
        return [line(cfg, 'm', lbl, cfg.color, 'price',
          alignArray(WMA.calculate({ period: p.period, values: close }), bars))]
      case 'vwap':
        return [line(cfg, 'v', lbl, cfg.color, 'price',
          alignArray(VWAP.calculate({ high, low, close, volume }), bars))]
      case 'bbands': {
        const bb = BollingerBands.calculate({ period: p.period, stdDev: p.stdDev, values: close })
        const edge = shade(cfg.color, 0.0)
        return [
          line(cfg, 'u', `${lbl} ↑`, edge, 'price', alignObjects(bb, bars, o => o.upper), 1, 2),
          line(cfg, 'm', lbl, cfg.color, 'price', alignObjects(bb, bars, o => o.middle), 2, 0),
          line(cfg, 'l', `${lbl} ↓`, edge, 'price', alignObjects(bb, bars, o => o.lower), 1, 2),
        ]
      }
      case 'rsi':
        return [line(cfg, 'r', lbl, cfg.color, 'oscillator',
          alignArray(RSI.calculate({ period: p.period, values: close }), bars))]
      case 'atr':
        return [line(cfg, 'a', lbl, cfg.color, 'oscillator',
          alignArray(ATR.calculate({ period: p.period, high, low, close }), bars))]
      case 'cci':
        return [line(cfg, 'c', lbl, cfg.color, 'oscillator',
          alignArray(CCI.calculate({ period: p.period, high, low, close }), bars))]
      case 'macd': {
        const m = MACD.calculate({
          values: close, fastPeriod: p.fast, slowPeriod: p.slow, signalPeriod: p.signal,
          SimpleMAOscillator: false, SimpleMASignal: false,
        })
        return [
          line(cfg, 'macd', `${lbl}`, cfg.color, 'oscillator', alignObjects(m, bars, o => o.MACD), 2, 0),
          line(cfg, 'sig', `${lbl} signal`, shade(cfg.color, 0.45), 'oscillator',
            alignObjects(m, bars, o => o.signal), 1, 2),
        ]
      }
      case 'stochastic': {
        const s = Stochastic.calculate({ high, low, close, period: p.period, signalPeriod: p.signal })
        return [
          line(cfg, 'k', `${lbl} %K`, cfg.color, 'oscillator', alignObjects(s, bars, o => o.k), 2, 0),
          line(cfg, 'd', `${lbl} %D`, shade(cfg.color, 0.45), 'oscillator',
            alignObjects(s, bars, o => o.d), 1, 2),
        ]
      }
      default:
        return []
    }
  } catch {
    return []
  }
}

/** Compute every config; returns price-pane and oscillator-pane lines separately. */
export function computeAll(configs: IndicatorConfig[], bars: Bar[]): {
  price: IndicatorLine[]
  oscillator: IndicatorLine[]
} {
  const price: IndicatorLine[] = []
  const oscillator: IndicatorLine[] = []
  for (const cfg of configs) {
    for (const ln of computeIndicator(cfg, bars)) {
      (ln.pane === 'oscillator' ? oscillator : price).push(ln)
    }
  }
  return { price, oscillator }
}
