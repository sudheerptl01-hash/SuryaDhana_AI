'use client'

/**
 * TitleStrip: the desktop app's overlay title bar (PLAN AC-7). Rendered only inside SuryaDhana.app.
 *
 *   [traffic lights · 84 px inset] ◆ SURYADHANA │ DESK · DECISION DESK ········drag········ NSE CLOSED · WEEKEND │ 11:42:07 IST │ ● UI ● DATA ● CTRL │ BUILD 1024·1110 a1b2c3d [NEW BUILD · RELOAD]
 *
 * - Every non-interactive element carries `data-tauri-drag-region` (Tauri v2 only drags on the element that has
 *   the attribute itself, not its children), so the whole strip moves the window while the chip stays clickable.
 * - The clock ticks on the second boundary inside its own component, so the rest of the strip re-renders only
 *   when its props change and the terminal below never re-renders for the clock.
 * - NSE holidays come from the ECO calendar endpoint (NSE's holiday master), refetched when the IST date changes;
 *   without them the session degrades to the weekday rule. The page header uses the same rule and the same
 *   holiday fetch (session.ts, holidays.ts), so strip and header always agree.
 * - In the app this strip is the ONE brand / clock / session / service-light source (C1-trader-ux-06): the page
 *   header drops its copies in desktop mode.
 * - Page zoom (⌘= / ⌘− / ⌘0, contract K3): the native traffic lights do not scale with the page, so the strip is
 *   counter-zoomed (CSS zoom 1 / factor) and keeps its native-title-bar geometry in SCREEN pixels: the 84 px
 *   inset, the 32 px height and the text size. The wordmark therefore never slides under the buttons.
 */
import { memo, useEffect, useState } from 'react'
import { Z } from '@/lib/z'
import type { ShellStatus, Svc } from '@/lib/platform'
import { CLOSING_UNTIL, istParts, nseSession, type NseSession } from './session'
import { useNseHolidays } from './holidays'
import { shortBuild } from './build'
import { clampZoom } from './zoom'
import type { PageMeta } from './pages'

/**
 * Height of the strip; PlatformShell publishes it as --shell-top (with the banner, when shown).
 * 32 px = the native macOS 26 title-bar height (measured: NSWindow titlebar 32 pt, 14 pt buttons centred), so the
 * traffic lights centre on the strip's mid-line with the shell's inset at (14, 18): tao sizes the title-bar
 * container to button height + y = 32.
 */
export const STRIP_HEIGHT = 32
/** Above every in-app layer (lib/z.ts): the strip is window chrome, not page content. */
export const Z_SHELL = Z.toast + 10

export { clampZoom, stripHeightCss } from './zoom'

const DRAG = { 'data-tauri-drag-region': '' } as const

/** Epoch ms, updated exactly on each wall-clock second. */
export function useSecondTick(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const tick = () => {
      const t = Date.now()
      setNow(t)
      timer = setTimeout(tick, 1000 - (t % 1000) + 5)
    }
    timer = setTimeout(tick, 1000 - (Date.now() % 1000) + 5)
    return () => clearTimeout(timer)
  }, [])
  return now
}

const SESSION_CLASS: Record<NseSession['state'], string> = { OPEN: 'is-open', 'PRE-OPEN': 'is-pre', CLOSED: 'is-closed' }

const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`

function sessionDetail(s: NseSession): string {
  if (s.special) {
    // Muhurat & co. (R-UI-SHELL-03 / CT-10): the session's name and window, or that NSE's circular sets it
    const sp = s.special
    const win = sp.from != null && sp.to != null ? `${hhmm(sp.from)}–${hhmm(sp.to)}` : 'timings per NSE circular'
    return s.state === 'OPEN' ? `${sp.label.toLowerCase()} · closes ${sp.to != null ? hhmm(sp.to) : ''}`.trim() : `${sp.label.toLowerCase()} · ${win}`
  }
  if (s.state === 'OPEN') return 'closes 15:30'
  if (s.state === 'PRE-OPEN') return 'opens 09:15'
  if (s.reason === 'HOLIDAY') return s.holiday ?? 'holiday'
  if (s.reason === 'WEEKEND') return 'weekend'
  if (s.reason === 'BEFORE OPEN') return 'pre-open 09:00'
  return s.istMinutes < CLOSING_UNTIL ? 'closing session' : 'after close'   // the header shows CLOSING until 16:00
}

const Clock = memo(function Clock() {
  const now = useSecondTick()
  const p = istParts(now)
  const holidays = useNseHolidays(p.date)
  const s = nseSession(now, holidays)
  const detail = sessionDetail(s)
  return (
    <>
      <span className="sd-strip-seg" {...DRAG} title={`NSE cash market (IST): ${s.state}${s.reason ? ` · ${s.reason.toLowerCase()}` : ''}${s.special ? ` · ${s.special.name}` : ''}`}>
        <span className="sd-strip-k" {...DRAG}>NSE</span>
        <span className={`sd-chip ${s.reason === 'SPECIAL' ? 'is-pre' : SESSION_CLASS[s.state]}`} {...DRAG}>{s.reason === 'SPECIAL' ? 'SPECIAL' : s.state}</span>
        <span className="sd-strip-dim sd-strip-detail" {...DRAG}>{detail}</span>
      </span>
      <span className="sd-strip-seg" {...DRAG} aria-label={`India Standard Time ${p.time}`}>
        <span className="sd-clock" {...DRAG}>{p.time}</span>
        <span className="sd-strip-k" {...DRAG}>IST</span>
      </span>
    </>
  )
})

/**
 * A value (epoch ms) that changes on each wall-clock minute while `on` (PlatformShell: BRF's time-of-day label in the strip
 * and the native window title, CT-13); otherwise it never ticks. Use it as a memo dependency and read the time
 * with Date.now() inside, so the first render after `on` turns true is already current.
 */
export function useMinuteWhile(on: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!on) return
    setNow(Date.now())
    let timer: ReturnType<typeof setTimeout>
    const arm = () => { timer = setTimeout(() => { setNow(Date.now()); arm() }, 60_000 - (Date.now() % 60_000) + 20) }
    arm()
    return () => clearTimeout(timer)
  }, [on])
  return now
}

function dotClass(svc: Svc | undefined, stale: boolean): string {
  if (!svc || stale) return 'sd-dot'
  return svc.up ? 'sd-dot is-up' : 'sd-dot is-down'
}

function svcTitle(name: string, svc: Svc | undefined, stale: boolean): string {
  if (!svc) return `${name}: waiting for the shell`
  if (stale) return `${name}: status is stale (shell poller silent)`
  return `${name}: ${svc.up ? 'up' : 'DOWN'}${svc.up && svc.latency_ms != null ? ` · ${Math.round(svc.latency_ms)} ms` : ''}`
}

const SERVICES: ReadonlyArray<[keyof Pick<ShellStatus, 'ui_api' | 'data_service' | 'master_controller'>, string, string]> = [
  ['ui_api', 'UI', 'ui-api :8010'],
  ['data_service', 'DATA', 'data-service :8001'],
  ['master_controller', 'CTRL', 'master-controller :8008'],
]

export interface TitleStripProps {
  meta: PageMeta
  status: ShellStatus | null
  /** True when the last status is older than the shell's cadence allows (dots go grey). */
  statusStale: boolean
  ownBuild: string | null
  newBuild: string | null
  onReload: () => void
  /** The window's page zoom (K3); the strip counter-zooms to stay native-sized. Default 1. */
  zoom?: number
}

/** The strip itself. Pure presentational; PlatformShell owns all state. */
export const TitleStrip = memo(function TitleStrip({ meta, status, statusStale, ownBuild, newBuild, onReload, zoom = 1 }: TitleStripProps) {
  const z = clampZoom(zoom)
  return (
    <div className="sd-strip" role="banner" aria-label="SuryaDhana window bar" data-zoom={z}
      style={{ zIndex: Z_SHELL, height: STRIP_HEIGHT, ...(z !== 1 ? { zoom: 1 / z } : null) }} {...DRAG}>
      <span className="sd-strip-brand" {...DRAG}>
        <span className="sd-mark" aria-hidden {...DRAG} />
        <span className="sd-wordmark" {...DRAG}>SURYADHANA</span>
      </span>
      <span className="sd-strip-seg sd-strip-page" {...DRAG} title={meta.label ? `${meta.code} · ${meta.label}` : meta.code}>
        <span className="sd-strip-code" {...DRAG}>{meta.code}</span>
        {meta.label && <span className="sd-strip-label" {...DRAG}>{meta.label}</span>}
      </span>
      <span className="sd-strip-drag" {...DRAG} />
      <Clock />
      <span className="sd-strip-seg" {...DRAG}>
        {SERVICES.map(([key, label, name]) => (
          <span key={key} className="sd-svc" title={svcTitle(name, status?.[key], statusStale)} {...DRAG}>
            <span className={dotClass(status?.[key], statusStale)} {...DRAG} />
            <span {...DRAG}>{label}</span>
          </span>
        ))}
      </span>
      <span className="sd-strip-seg sd-strip-last" {...DRAG} title={ownBuild ? `UI release ${ownBuild}` : 'development build'}>
        <span className="sd-strip-k" {...DRAG}>BUILD</span>
        <span className="sd-strip-dim" {...DRAG}>{shortBuild(ownBuild)}</span>
        {newBuild && (
          <button type="button" className="sd-newbuild" onClick={onReload}
            title={`A new UI build is being served (${newBuild}). Reload this window to use it.`}>
            NEW BUILD · RELOAD
          </button>
        )}
      </span>
    </div>
  )
})
