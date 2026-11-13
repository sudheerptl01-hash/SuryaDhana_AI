'use client'

/**
 * InteractiveSeries — the ONE lightweight-charts (4.2.3) wrapper for the terminal (FINAL ROUND W3,
 * charts/PLAN.md §4). Replaces per-page createChart copies over time:
 *
 *   <InteractiveSeries
 *     series={[{ id: 'iv30', label: 'IV30', color: T.amber, type: 'line', axis: 'R',
 *                points: [{ t: '2026-11-12', v: 18.2 }], format: pct1 },
 *              { id: 'px', type: 'candles', points: ohlc } ]}
 *     band={{ lo, hi, color }} markers={[{ t, kind: 'results' }]} unitL="%" unitR=""
 *     linkGroup="omon" height={220} onCrosshair={(t, values) => ...} />
 *
 *  - dynamic-imports LWC in an effect (ssr-safe; the chunk loads only on chart pages, as ChartStudio does);
 *  - 4.x API names ONLY (addLineSeries / addAreaSeries / addCandlestickSeries / addHistogramSeries — the pin
 *    stays 4.2.3; 5.x renamed these to addSeries);
 *  - theme applied once from ./chartTheme (the T tokens) — no per-chart theme objects;
 *  - `band` → the area-pair (translucent hi + panel-masked lo, added first so lines draw on top);
 *  - `markers` → LWC markers on the primary series; a null point → a whitespace gap, never interpolated;
 *  - `linkGroup` shares visible range + crosshair ONLY within one trading calendar (`calendar`, default 'nse' —
 *    the spike's cross-calendar misalignment finding). Kit fix 1 (E-DIFF): a peer's crosshair broadcast fills
 *    THIS pane's legend synchronously from its OWN data at exactly t; the point-less echo events LWC fires for
 *    programmatic crosshair moves are ignored, so a snapped neighbour date can never land in the legend when
 *    the panes' date sets differ.
 *  - kit fix 2 (E-DIFF): a chart first fitted at a narrow mount (hidden tab, 0-width flex pass → the 300 px
 *    fallback) refits ONCE on the first real size change, unless the user already zoomed or panned.
 *  - `priceLines` (E-DIFF T-22): labelled horizontal levels on the primary series — the alert overlay. A click
 *    within 6 px of a line fires its onClick; `levelMenu` adds a right-click / long-press "＋ ALERT AT <level>"
 *    that hands the picked level to the caller (the typed-rule builder pre-fill — a level, never a
 *    recommendation, and never an auto-created rule). `alertOverlay={{ symbol, kind }}` wires both from the
 *    alert stores via useAlertOverlay.
 *  - crosshair values go to the surrounding ExpandableChart's legend slot (readable, never tooltip-only) and to
 *    `onCrosshair`; FIT (fitContent) and PNG (takeScreenshot → saveDownload) register on the same shell.
 *  - the TradingView attribution mark stays (licence) — nothing here turns it off.
 *
 * Wheel zoom, drag pan, pinch and kinetic scroll are LWC's own (handleScroll/handleScale from the theme).
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import type { IChartApi, IPriceLine, ISeriesApi, LineStyle, SeriesMarker, SeriesType, Time } from 'lightweight-charts'
import { saveDownload } from '@/lib/platform'
import { ALERTS_EVENT, draftAlert } from '@/lib/alerts'
import { getAlertRules } from '@/lib/alertsClient'
import { ALERT_FOCUS_KEY, alertLinesFor, draftAtLevel, type AlertLineKind, type OverlayRuleLike } from '@/lib/alertOverlay'
import { goToPage } from '@/lib/navigate'
import { BAND_COLOR, BAND_MASK, CANDLE_OPTIONS, MARKER_PALETTE, OVERLAY_COLOR, SERIES_FALLBACK, terminalChartOptions } from './chartTheme'
import { useChartShell } from './ExpandableChart'
import { broadcastCrosshair, broadcastRange, registerLink } from './linkGroups'
import {
  bandAreaOptions, coerceTime, fmtValue, isIntraday, seriesSignature, shapeCandles, shapeLine, timeKey, timeText, toMarkers,
  type BandSpec, type CandlePoint, type MarkerSpec, type SeriesPoint, type SeriesSpec,
} from './interactiveModel'
import { T } from '@/components/news/format'

export type { BandSpec, CandlePoint, MarkerSpec, SeriesPoint, SeriesSpec } from './interactiveModel'

type AnySeries = ISeriesApi<SeriesType>

/** A labelled horizontal level on the primary series (the alert overlay; E-DIFF T-22). */
export interface PriceLineSpec {
  id: string
  price: number
  /** axis-side label text — the rule's own direction-free wording ('ALERT · at or over') */
  title?: string
  color?: string
  /** default true (the CHRT alert-line convention) */
  dashed?: boolean
  /** called when the chart is clicked within 6 px of this line */
  onClick?: () => void
}

/** Right-click / long-press "alert at this level": the kit reports the picked level; the caller pre-fills. */
export interface LevelMenuSpec {
  onCreate: (price: number, lastValue: number | null) => void
}

export interface InteractiveSeriesProps {
  series: SeriesSpec[]
  /** a shaded band (an IV cone's p25–p75) — rendered as the spike-proven area-pair */
  band?: BandSpec | null
  /** vertical event markers (results / expiry / …) */
  markers?: MarkerSpec[]
  /** unit suffix for the left / right price axis when a series has no `format` of its own */
  unitL?: string
  unitR?: string
  /** panes registering the same group share visible range + crosshair (within one `calendar` only) */
  linkGroup?: string
  /** the trading calendar this pane's times live on (default 'nse'); panes only link within one calendar */
  calendar?: string
  height?: number
  /** horizontal levels drawn on the primary series (merged with the alertOverlay's lines) */
  priceLines?: PriceLineSpec[]
  /** the right-click / long-press level menu (overrides the alertOverlay's) */
  levelMenu?: LevelMenuSpec | null
  /** draw this symbol's alert rules as lines + wire the level menu to the typed-rule builder pre-fill */
  alertOverlay?: { symbol: string | null | undefined; kind?: AlertLineKind } | null
  /** the crosshair's time label (null when it leaves) and the value per series id */
  onCrosshair?: (t: string | null, values: Record<string, number | null>) => void
  /** escape hatch: the raw IChartApi once built (price lines, scrubbers — overlay work, not theme changes) */
  onReady?: (chart: IChartApi) => void
  ariaLabel?: string
}

export function InteractiveSeries({ series, band = null, markers = [], unitL = '', unitR = '', linkGroup,
                                    calendar = 'nse', height = 220, priceLines, levelMenu, alertOverlay = null,
                                    onCrosshair, onReady, ariaLabel }: InteractiveSeriesProps) {
  const boxRef = useRef<HTMLDivElement | null>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const [ready, setReady] = useState(0)
  const [menu, setMenu] = useState<{ left: number; top: number; price: number; last: number | null } | null>(null)
  const shell = useChartShell()

  // the alert-store overlay (a no-op without `alertOverlay`); explicit props win / merge
  const ao = useAlertOverlay(alertOverlay?.symbol ?? null, alertOverlay?.kind ?? 'price')
  const effLines = useMemo(() => [...(priceLines ?? []), ...ao.priceLines], [priceLines, ao.priceLines])
  const effMenu = levelMenu !== undefined ? levelMenu : ao.levelMenu

  // latest props for the subscriptions created once in the mount effect
  const live = useRef({ series, band, markers, unitL, unitR, onCrosshair, applying: false, linkId: 0,
                        handles: new Map<string, AnySeries>(), bandHandles: [] as AnySeries[], sig: '', fitted: false,
                        // kit fix 2 state: the width the initial fit saw, whether the one refit ran, user gestures
                        fitW: 0, refitDone: false, userGesture: false,
                        // the alert overlay (E-DIFF T-22)
                        lines: [] as { spec: PriceLineSpec; line: IPriceLine; on: AnySeries }[], linesSig: '', linesOn: null as AnySeries | null,
                        menu: null as LevelMenuSpec | null })
  live.current.series = series
  live.current.band = band
  live.current.markers = markers
  live.current.unitL = unitL
  live.current.unitR = unitR
  live.current.onCrosshair = onCrosshair
  live.current.menu = effMenu ?? null

  // ── build the chart once (dynamic import), destroy on unmount ──────────────────────────────────────
  useEffect(() => {
    let disposed = false
    let ro: ResizeObserver | null = null
    let unregister: (() => void) | null = null
    let detach: (() => void) | null = null
    void (async () => {
      const lw = await import('lightweight-charts')
      const el = boxRef.current
      if (disposed || !el) return
      const chart = lw.createChart(el, { ...terminalChartOptions(), width: el.clientWidth || 300, height: el.clientHeight || height })
      chartRef.current = chart
      const s = live.current

      // keep the canvas at the box's size (the ExpandableChart overlay re-measures through this)
      if (typeof ResizeObserver !== 'undefined') {
        ro = new ResizeObserver(() => {
          const b = boxRef.current
          if (!b || !chartRef.current) return
          chartRef.current.applyOptions({ width: b.clientWidth, height: b.clientHeight })
          // kit fix 2: a chart first fitted while narrow (hidden tab / 0-width mount → the 300 px fallback)
          // keeps whitespace at the real size — refit ONCE on the first real size change, never after the
          // user has zoomed or panned (their view is theirs)
          if (s.fitted && !s.refitDone && !s.userGesture && Math.abs(b.clientWidth - s.fitW) > 8) {
            s.refitDone = true
            chartRef.current.timeScale().fitContent()
          }
        })
        ro.observe(el)
      }

      // link group: one visible range + one crosshair per (group, calendar)
      if (linkGroup) {
        const reg = registerLink(linkGroup, calendar, {
          onRange: r => {
            s.applying = true
            try { chart.timeScale().setVisibleLogicalRange(r) } finally { s.applying = false }
          },
          onCrosshair: t => {
            const first = firstDataHandle(s.handles, s.series)
            s.applying = true
            try {
              if (t == null || !first) {
                chart.clearCrosshairPosition()
                shell?.setLegend(null)
                s.onCrosshair?.(null, {})
                return
              }
              chart.setCrosshairPosition(0, t as Time, first)
              // kit fix 1: fill this pane's legend SYNCHRONOUSLY from its OWN data at exactly t. The echo
              // event setCrosshairPosition fires is point-less and snaps to the nearest bar, which can land a
              // NEIGHBOURING date when the panes' date sets differ — subscribeCrosshairMove below ignores
              // point-less events, so this is the one legend write for a linked move.
              const { values, parts } = legendPartsAt(s.series, t)
              const tl = timeText(t)
              s.onCrosshair?.(tl, values)
              shell?.setLegend(parts.length ? legendNode(tl, parts) : null)
            } finally { s.applying = false }
          },
        })
        s.linkId = reg.id
        unregister = reg.unregister
      }

      chart.timeScale().subscribeVisibleLogicalRangeChange(r => {
        if (!r || s.applying || !s.linkId) return
        broadcastRange(s.linkId, { from: r.from, to: r.to })
      })

      chart.subscribeCrosshairMove(p => {
        const time = (p.time as string | number | undefined) ?? null
        const userEvent = !!p.point // a mouse/touch move; programmatic set/clear (linked echoes) carries no point
        if (!userEvent && time != null) return // stale/snapped echo of a peer broadcast: the legend is already set
        if (time == null) {
          if (userEvent && !s.applying && s.linkId) broadcastCrosshair(s.linkId, null)
          shell?.setLegend(null)
          s.onCrosshair?.(null, {})
          return
        }
        if (!s.applying && s.linkId) broadcastCrosshair(s.linkId, time)
        const values: Record<string, number | null> = {}
        const parts: LegendPartNode[] = []
        for (const spec of s.series) {
          const h = s.handles.get(spec.id)
          const d = h ? (p.seriesData.get(h) as { value?: number; close?: number } | undefined) : undefined
          const v = d == null ? null : d.value ?? d.close ?? null
          values[spec.id] = v
          if (v != null) parts.push({ label: (spec.label ?? spec.id).toUpperCase(), text: fmtValue(v, spec.format), color: spec.color })
        }
        const tLabel = timeText(time)
        s.onCrosshair?.(tLabel, values)
        shell?.setLegend(legendNode(tLabel, parts))
      })

      // the alert overlay's line click (within 6 px of a line → its onClick, e.g. the rule in ALRT)
      chart.subscribeClick(p => {
        if (!p.point) return
        for (const { spec, on } of s.lines) {
          if (!spec.onClick) continue
          const y = on.priceToCoordinate(spec.price)
          if (y != null && Math.abs(y - p.point.y) <= 6) { spec.onClick(); return }
        }
      })

      // user gestures (kit fix 2's guard) + the level menu (right-click / long-press)
      const mark = () => { s.userGesture = true }
      const openMenu = (clientX: number, clientY: number): boolean => {
        const b = boxRef.current
        if (!b || !s.menu || !chartRef.current) return false
        const r = b.getBoundingClientRect()
        const y = clientY - r.top
        const primary = firstDataHandle(s.handles, s.series)
        const raw = primary ? primary.coordinateToPrice(y) : null
        const price = raw == null ? null : Number(raw)
        if (price == null || !Number.isFinite(price)) return false
        setMenu({ left: Math.max(0, Math.min(clientX - r.left, r.width - 200)),
                  top: Math.max(0, Math.min(y, r.height - 56)), price, last: lastValueOf(s.series) })
        return true
      }
      const onCtx = (e: MouseEvent) => { if (s.menu && openMenu(e.clientX, e.clientY)) e.preventDefault() }
      let lp: ReturnType<typeof setTimeout> | null = null
      const lpClear = () => { if (lp) { clearTimeout(lp); lp = null } }
      const onTouch = (e: TouchEvent) => {
        mark()
        const t = e.touches[0]
        if (!t || !s.menu) return
        lpClear()
        const { clientX, clientY } = t
        lp = setTimeout(() => { openMenu(clientX, clientY) }, 500)
      }
      el.addEventListener('wheel', mark, { passive: true })
      el.addEventListener('mousedown', mark)
      el.addEventListener('contextmenu', onCtx)
      el.addEventListener('touchstart', onTouch, { passive: true })
      el.addEventListener('touchmove', lpClear, { passive: true })
      el.addEventListener('touchend', lpClear, { passive: true })
      detach = () => {
        lpClear()
        el.removeEventListener('wheel', mark)
        el.removeEventListener('mousedown', mark)
        el.removeEventListener('contextmenu', onCtx)
        el.removeEventListener('touchstart', onTouch)
        el.removeEventListener('touchmove', lpClear)
        el.removeEventListener('touchend', lpClear)
      }

      onReady?.(chart)
      setReady(n => n + 1)
    })()
    return () => {
      disposed = true
      ro?.disconnect()
      unregister?.()
      detach?.()
      shell?.setLegend(null)
      live.current.handles.clear()
      live.current.bandHandles = []
      live.current.lines = []
      live.current.linesSig = ''
      live.current.linesOn = null
      live.current.sig = ''
      live.current.fitted = false
      live.current.refitDone = false
      chartRef.current?.remove()
      chartRef.current = null
    }
    // the chart is built once per mount; linkGroup/calendar changes need a remount (pass a key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── (re)build series + set data whenever props change ──────────────────────────────────────────────
  useEffect(() => {
    const chart = chartRef.current
    if (!chart || !ready) return
    const s = live.current
    const sig = seriesSignature(series, band)

    if (sig !== s.sig) {
      // shape changed (ids / types / axes / colours / band): rebuild — band areas FIRST so lines draw on top
      for (const h of s.bandHandles) chart.removeSeries(h)
      for (const h of s.handles.values()) chart.removeSeries(h)
      s.bandHandles = []
      s.handles.clear()
      s.sig = sig

      if (band) {
        const axisId = band.axis === 'L' ? 'left' : 'right'
        const pair = bandPairOptions(band.color ?? BAND_COLOR)
        const hi = chart.addAreaSeries({ ...pair.hi, priceScaleId: axisId })
        const lo = chart.addAreaSeries({ ...pair.lo, priceScaleId: axisId })
        s.bandHandles = [hi, lo]
      }
      series.forEach((spec, i) => {
        const color = spec.color ?? SERIES_FALLBACK[i % SERIES_FALLBACK.length]
        const scaleId = spec.overlay ? `overlay-${spec.id}` : spec.axis === 'L' ? 'left' : 'right'
        const priceFormat = spec.format
          ? { type: 'custom' as const, formatter: spec.format, minMove: 0.01 }
          : axisUnit(spec, unitL, unitR)
            ? { type: 'custom' as const, formatter: (v: number) => `${v.toFixed(1)}${axisUnit(spec, unitL, unitR)}`, minMove: 0.01 }
            : undefined
        const common = { priceScaleId: scaleId, ...(priceFormat ? { priceFormat } : null) }
        let h: AnySeries
        const type = spec.type ?? 'line'
        if (type === 'candles') h = chart.addCandlestickSeries({ ...CANDLE_OPTIONS, ...common })
        else if (type === 'histogram') h = chart.addHistogramSeries({ color: spec.color ?? OVERLAY_COLOR, ...common })
        else if (type === 'area') h = chart.addAreaSeries({ lineColor: color, topColor: `${color}33`, bottomColor: `${color}05`, lineWidth: lineW(spec, i), ...common })
        else h = chart.addLineSeries({ color, lineWidth: lineW(spec, i), ...(spec.dashed ? { lineStyle: 2 as LineStyle } : null), ...common })
        if (spec.overlay) chart.priceScale(scaleId).applyOptions({ visible: false, scaleMargins: { top: 0.82, bottom: 0 } })
        s.handles.set(spec.id, h)
      })
      if (series.some(x => x.axis === 'L') || band?.axis === 'L') chart.applyOptions({ leftPriceScale: { visible: true } })
      chart.applyOptions({ timeScale: { timeVisible: isIntraday(series), secondsVisible: false } })
    }

    // data (every run): whitespace rows keep gaps honest
    if (band && s.bandHandles.length === 2) {
      s.bandHandles[0].setData(shapeLine(band.hi) as never[])
      s.bandHandles[1].setData(shapeLine(band.lo) as never[])
    }
    for (const spec of series) {
      const h = s.handles.get(spec.id)
      if (!h) continue
      if ((spec.type ?? 'line') === 'candles') h.setData(shapeCandles(spec.points as CandlePoint[]) as never[])
      else h.setData(shapeLine(spec.points as SeriesPoint[]) as never[])
    }
    const primary = firstDataHandle(s.handles, series)
    if (primary) primary.setMarkers(toMarkers(markers, MARKER_PALETTE) as SeriesMarker<Time>[])
    if (!s.fitted && series.some(x => x.points.length)) {
      chart.timeScale().fitContent()
      s.fitted = true
      s.fitW = boxRef.current?.clientWidth ?? 0   // kit fix 2: remember the width the fit saw
    }
  }, [ready, series, band, markers, unitL, unitR])

  // ── the alert overlay's price lines (on the primary series; redrawn only when they actually change) ──
  useEffect(() => {
    const chart = chartRef.current
    const s = live.current
    if (!chart || !ready) return
    const primary = firstDataHandle(s.handles, series)
    const sig = effLines.map(l => `${l.id}:${l.price}:${l.title ?? ''}:${l.color ?? ''}:${(l.dashed ?? true) ? 1 : 0}`).join('|')
    if (sig === s.linesSig && s.linesOn === primary) return
    for (const { line, on } of s.lines) { try { on.removePriceLine(line) } catch { /* series rebuilt */ } }
    s.lines = []
    s.linesSig = sig
    s.linesOn = primary
    if (!primary) return
    for (const spec of effLines) {
      if (!Number.isFinite(spec.price)) continue
      const line = primary.createPriceLine({ price: spec.price, color: spec.color ?? T.amber, lineWidth: 1,
        lineStyle: ((spec.dashed ?? true) ? 2 : 0) as LineStyle, axisLabelVisible: true, title: spec.title ?? 'ALERT' })
      s.lines.push({ spec, line, on: primary })
    }
  }, [ready, effLines, series])

  // ── the level menu closes on outside pointer / Esc ──────────────────────────────────────────────────
  useEffect(() => {
    if (!menu || typeof window === 'undefined') return
    const close = () => setMenu(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.stopPropagation(); setMenu(null) } }
    window.addEventListener('pointerdown', close, true)
    window.addEventListener('keydown', onKey, true)
    return () => { window.removeEventListener('pointerdown', close, true); window.removeEventListener('keydown', onKey, true) }
  }, [menu])

  // ── FIT / PNG on the surrounding shell ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!shell || !ready) return
    const fit = () => chartRef.current?.timeScale().fitContent()
    const png = () => {
      const chart = chartRef.current
      if (!chart) return
      const stem = (shell.title ?? 'chart').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'chart'
      chart.takeScreenshot().toBlob(b => { if (b) void saveDownload(b, `${stem}-${new Date().toLocaleDateString('en-CA')}.png`) }, 'image/png')
    }
    return shell.registerActions({ fit, png })
  }, [shell, ready])

  const menuFmt = series.find(x => !x.overlay)?.format

  return (
    <div style={{ width: '100%', height: '100%', minHeight: height, minWidth: 0, position: 'relative' }}>
      <div ref={boxRef} role="img" aria-label={ariaLabel ?? 'interactive chart'} data-sd-chart="lwc"
        style={{ position: 'absolute', inset: 0 }} />
      {menu && (
        <div role="menu" data-sd-level-menu onPointerDown={e => e.stopPropagation()}
          style={{ position: 'absolute', left: menu.left, top: menu.top, zIndex: 30, background: '#0a0d13',
                   border: `1px solid ${T.amber}55`, boxShadow: '0 4px 14px rgba(0,0,0,.55)', fontFamily: T.mono,
                   fontSize: 11, minWidth: 190, maxWidth: 260 }}>
          <div role="menuitem" tabIndex={0}
            onClick={() => { const m = live.current.menu; const picked = menu; setMenu(null); m?.onCreate(picked.price, picked.last) }}
            style={{ padding: '7px 10px', color: T.amber, cursor: 'pointer', whiteSpace: 'nowrap' }}>
            ＋ ALERT AT {fmtValue(menu.price, menuFmt)}
          </div>
          <div style={{ padding: '0 10px 7px', color: T.dim, fontSize: 10, lineHeight: 1.4 }}>
            opens the rule builder pre-filled — a level, not a recommendation
          </div>
        </div>
      )}
    </div>
  )
}

// ── the alert-store overlay hook (E-DIFF T-22) ─────────────────────────────────────────────────────────
/**
 * This symbol's alert rules (both stores: typed rules + the legacy one-shot price alerts) as chart lines, plus
 * the "alert at this level" menu wired to the EXISTING typed-rule builder pre-fill (lib/alerts.ts draftAlert —
 * the owner reviews and saves; nothing is auto-created, no new alert kind). A clicked line opens the rule in
 * ALRT. With no symbol it returns nothing and fetches nothing.
 */
export function useAlertOverlay(symbol: string | null | undefined, kind: AlertLineKind = 'price'):
    { priceLines: PriceLineSpec[]; levelMenu: LevelMenuSpec | null } {
  const [rules, setRules] = useState<OverlayRuleLike[]>([])
  useEffect(() => {
    if (!symbol) { setRules([]); return }
    let on = true
    const read = () => { getAlertRules('all').then(r => { if (on) setRules(r.data.rules) }).catch(() => { /* keep what is drawn */ }) }
    read()
    const iv = setInterval(read, 60_000)
    window.addEventListener(ALERTS_EVENT, read)
    return () => { on = false; clearInterval(iv); window.removeEventListener(ALERTS_EVENT, read) }
  }, [symbol])
  return useMemo(() => {
    if (!symbol) return { priceLines: [], levelMenu: null }
    return {
      priceLines: alertLinesFor(rules, symbol, kind).map(l => ({
        id: l.id, price: l.price, title: l.title, color: T.amber, dashed: true,
        onClick: () => {
          try { sessionStorage.setItem(ALERT_FOCUS_KEY, l.id) } catch { /* storage blocked */ }
          goToPage('alerts')
        },
      })),
      levelMenu: {
        onCreate: (price, lastValue) => {
          const d = draftAtLevel(kind, symbol, price, lastValue)
          if (d) draftAlert(d)
        },
      },
    }
  }, [rules, symbol, kind])
}

// ── small helpers (component-local; the pure halves live in interactiveModel.ts) ──────────────────────

interface LegendPartNode { label: string; text: string; color?: string }

function legendNode(tLabel: string, parts: readonly LegendPartNode[]): ReactNode {
  return (
    <span>
      <span style={{ color: T.dim }}>{tLabel}</span>
      {parts.map((x, i) => (
        <span key={i}> · {x.label} <b style={{ color: T.bright, fontWeight: 400 }}>{x.text}</b></span>
      ))}
    </span>
  )
}

/** Each series' value at EXACTLY the broadcast time t (its own data; a date the pane lacks yields null). */
function legendPartsAt(series: readonly SeriesSpec[], t: string | number):
    { values: Record<string, number | null>; parts: LegendPartNode[] } {
  const key = timeKey(t)
  const values: Record<string, number | null> = {}
  const parts: LegendPartNode[] = []
  for (const spec of series) {
    let v: number | null = null
    for (const p of spec.points as (SeriesPoint | CandlePoint)[]) {
      const ct = coerceTime(p.t)
      if (ct == null || timeKey(ct) !== key) continue
      const raw = (spec.type ?? 'line') === 'candles' ? (p as CandlePoint).c : (p as SeriesPoint).v
      v = raw != null && Number.isFinite(raw) ? raw : null                   // the LAST write at t wins (shapeLine's dedupe)
    }
    values[spec.id] = v
    if (v != null && !spec.overlay) parts.push({ label: (spec.label ?? spec.id).toUpperCase(), text: fmtValue(v, spec.format), color: spec.color })
  }
  return { values, parts }
}

/** The primary (first non-overlay) series' last non-null value — the level menu's crossing-side reference. */
function lastValueOf(series: readonly SeriesSpec[]): number | null {
  const spec = series.find(x => !x.overlay)
  if (!spec) return null
  const pts = spec.points as (SeriesPoint | CandlePoint)[]
  for (let i = pts.length - 1; i >= 0; i--) {
    const raw = (spec.type ?? 'line') === 'candles' ? (pts[i] as CandlePoint).c : (pts[i] as SeriesPoint).v
    if (raw != null && Number.isFinite(raw)) return raw
  }
  return null
}

function lineW(spec: SeriesSpec, i: number): 1 | 2 | 3 | 4 {
  const w = spec.w ?? (i === 0 ? 2 : 1)
  return (w >= 4 ? 4 : w >= 3 ? 3 : w >= 2 ? 2 : 1)
}

function axisUnit(spec: SeriesSpec, unitL: string, unitR: string): string {
  return (spec.axis === 'L' ? unitL : unitR) || ''
}

/** The first non-overlay series with a handle: markers + the linked crosshair anchor live on it. */
function firstDataHandle(handles: Map<string, AnySeries>, series: readonly SeriesSpec[]): AnySeries | null {
  for (const spec of series) {
    if (spec.overlay) continue
    const h = handles.get(spec.id)
    if (h) return h
  }
  return null
}

function bandPairOptions(color: string) {
  return bandAreaOptions(color, BAND_MASK)
}
