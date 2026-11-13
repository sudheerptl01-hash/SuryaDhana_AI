'use client'

/**
 * PlatformShell: wraps the whole terminal (ui/app/layout.tsx). PLAN §4 D4, contract §5.
 *
 * Both modes (browser and SuryaDhana.app):
 *  - awaits bootstrapPlatform() (prefs hydration + write-through, desktop link interceptor) before the terminal
 *    mounts, bounded at BOOT_CEILING_MS; until then the BootGate (black, same token as the terminal) shows;
 *  - connection banner while ui-api is down, cleared on recovery (desktop: from shell status events;
 *    browser: a cheap /health monitor, see health.ts);
 *  - "new build" notice (desktop: build-changed events / status.ui_build; browser: /build-info.json watch);
 *  - one-time "settings not imported yet" notice until the old browser origin has migrated (lib/prefs/migration.ts);
 *  - ChunkLoadError raised outside React rendering → one guarded reload (chunkRecovery.ts);
 *  - client error reporting: window 'error' / 'unhandledrejection' → POST /api/client-errors (lib/clientErrors.ts, K1);
 *  - the shell state for the terminal (components/shell/ShellState.tsx): desktop mode, link up/down, zoom; on
 *    LINK DOWN → LINK UP it dispatches 'suryadhana:reconnected' (lib/reconnect.ts) so failed pages reload;
 *  - boot preload (C2-performance-02): the URL's page module (and the stock window for ?sym=) loads while the boot
 *    gate shows, so a new, restored or reloaded window renders its page directly, without the 300 ms Suspense
 *    reveal throttle (components/shell/tabModules.ts).
 * Desktop only (isDesktop()):
 *  - TitleStrip (overlay title bar with drag region, page code, IST clock, NSE session, service dots, build);
 *  - find on page (R9): ⌘F opens FindBar (window.find()), ⌘G / ⇧⌘G next / previous, Esc closes; a browser keeps its
 *    own ⌘F, so the bar is never mounted there;
 *  - native window title "<CODE> · <label> — SuryaDhana" via setWindowTitle;
 *  - shell events: goto → goToPage(), command-bar → the CommandBar's own 'suryadhana:command' event,
 *    zoom (K3) → the strip keeps its native-title-bar geometry in SCREEN pixels at every page zoom.
 *
 * Layout: the shell publishes its height as the CSS variable --shell-top on <html> (strip 32 screen px = 32 / zoom CSS
 * px, + banner 24 px when shown; 0 in a browser without a banner). globals.css pads <body> by it, and the app's own fixed/sticky chrome
 * offsets by `var(--shell-top, 0px)`, so nothing is ever drawn under the strip or the traffic lights.
 */
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  bootstrapPlatform,
  isDesktop,
  onShellEvent,
  setWindowTitle,
  shellStatus,
  type ShellEvent,
  type ShellStatus,
} from '@/lib/platform'
import { goToPage } from '@/lib/navigate'
import { PREFS_SERVER_EVENT, prefsServerInfo, prefsSyncStatus } from '@/lib/prefs/sync'
import { MIGRATE_NOTICE_KEY, migrationNoticeState, migrationNoticeText, type MigrationNoticeState } from '@/lib/prefs/migration'
import { installClientErrorReporting, reportClientError } from '@/lib/clientErrors'
import { parseLocation } from '@/lib/deepLink'
import { RECONNECTED_EVENT, type ReconnectedDetail } from '@/lib/reconnect'
import { ShellStateContext, type ShellState } from '@/components/shell/ShellState'
import { preloadTab } from '@/components/shell/tabModules'
import { TitleStrip, clampZoom, stripHeightCss, useMinuteWhile } from './TitleStrip'
import { BANNER_HEIGHT, BootGate, BuildPill, ConnectionBanner, MigrationNotice, UpstreamStrip, useUpstreamHealth, type BannerPhase } from './ShellNotices'
import { upstreamStripKind } from './upstream'
import { StandDownBanner, useStandDownState } from '@/components/risk/StandDownBanner'
import { FindBar } from './FindBar'
import { isStatusStale, statusFreshAt, STATUS_PULL_MS } from './status'
import { HealthMonitor, type HealthSnapshot } from './health'
import { isNewBuild, OWN_BUILD, startBuildWatch } from './build'
import { isChunkLoadError, recoverFromChunkError } from './chunkRecovery'
import { installLocationWatcher, onLocationChange } from './location'
import { DEFAULT_TAB, PAGE_META, pageMeta, stripLabel, tabFromSearch, windowTitle } from './pages'
import { istParts } from './session'

/** Hard ceiling on the boot gate (bootstrapPlatform has its own 1.5 s + 250 ms bound; this is defence in depth). */
export const BOOT_CEILING_MS = 1800
/** The CommandBar opens on this window event (components/CommandBar.tsx). */
export const COMMAND_EVENT = 'suryadhana:command'
/** Desktop: without any status event this long after boot, fall back to the browser health monitor. */
const STATUS_FALLBACK_MS = 12_000
/** Desktop: a down status must persist this long before the banner shows (one poll blip never flashes it). */
const DESKTOP_DOWN_GRACE_MS = 4_000
/** How long the green "reconnected" banner stays. */
const RECOVERED_MS = 2_500
/** Boot preload of the URL's page module: never holds the gate longer than this (the ceiling bounds it too). */
export const BOOT_PRELOAD_MAX_MS = 900

/** The zoom the shell set before page scripts (K3), 1 when absent or invalid. */
function initialZoom(): number {
  try {
    const z = (window as Window & { __SURYADHANA_ZOOM__?: unknown }).__SURYADHANA_ZOOM__
    return typeof z === 'number' ? clampZoom(z) : 1
  } catch {
    return 1
  }
}

function setShellTop(px: number, mode: 'desktop' | 'browser'): void {
  const root = document.documentElement
  root.style.setProperty('--shell-top', `${px}px`)
  root.dataset.sdShell = mode
}

export function PlatformShell({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false)
  const [desktop, setDesktop] = useState(false)
  const [tab, setTab] = useState(DEFAULT_TAB)
  const [status, setStatus] = useState<ShellStatus | null>(null)
  /** When the shown status was true (the poller's `at`, see status.ts); 0 = none yet. */
  const [statusAt, setStatusAt] = useState(0)
  const [fallback, setFallback] = useState(false)
  const [health, setHealth] = useState<HealthSnapshot | null>(null)
  const [newBuild, setNewBuild] = useState<string | null>(null)
  const [dismissed, setDismissed] = useState<string | null>(null)
  const [phase, setPhase] = useState<BannerPhase>('hidden')
  const [downSince, setDownSince] = useState<number | null>(null)
  const [outageMs, setOutageMs] = useState<number | null>(null)
  const [, setStaleTick] = useState(0)
  const [migration, setMigration] = useState<MigrationNoticeState>('hide')
  const [zoom, setZoom] = useState(1)
  const [reconnects, setReconnects] = useState(0)
  const readyRef = useRef(false)
  /** Arrival time of the last status (pushed or pulled): drives the shell_status pull. */
  const statusRxRef = useRef(0)
  const pending = useRef<ShellEvent[]>([])
  const monitorRef = useRef<HealthMonitor | null>(null)
  const statusAtRef = useRef(0)
  statusAtRef.current = statusAt

  // ── boot: detect the shell, publish the layout offset, then bootstrap the platform ───────────────────────
  // The URL's page module loads in parallel (bounded by BOOT_PRELOAD_MAX_MS), so the first render shows the page
  // itself, not the skeleton + React's 300 ms Suspense throttle (C2-performance-02).
  useLayoutEffect(() => {
    const d = isDesktop()
    setDesktop(d)
    if (d) setZoom(initialZoom())
  }, [])
  useEffect(() => {
    let alive = true
    let booted = false
    let preloaded = false
    const done = () => { if (alive) setReady(true) }
    const maybe = () => { if (booted && preloaded) { clearTimeout(ceiling); done() } }
    const ceiling = setTimeout(done, BOOT_CEILING_MS)
    const { tab: first, sym } = parseLocation(window.location.search, Object.keys(PAGE_META), DEFAULT_TAB)
    const preload = Promise.all([preloadTab(first), sym ? preloadTab('stock') : Promise.resolve()])
    const preloadCap = new Promise<void>(r => setTimeout(r, BOOT_PRELOAD_MAX_MS))
    Promise.race([preload, preloadCap]).finally(() => { preloaded = true; maybe() })
    bootstrapPlatform().catch(() => undefined).finally(() => { booted = true; maybe() })
    return () => { alive = false; clearTimeout(ceiling) }
  }, [])

  // ── client error reporting (K1): every uncaught error / rejection, once, rate-limited ───────────────────
  useEffect(() => installClientErrorReporting(isChunkLoadError), [])

  // ── shell events (desktop): queued until the terminal has mounted its listeners ─────────────────────────
  const handle = useCallback((ev: ShellEvent) => {
    if (ev.type === 'status') {
      const rx = Date.now()
      statusRxRef.current = rx
      setStatus(ev.status)
      setStatusAt(statusFreshAt(ev.status.at, rx))
      if (isNewBuild(ev.status.ui_build)) setNewBuild(ev.status.ui_build)
      return
    }
    if (ev.type === 'build-changed') {
      if (ev.build && ev.build !== OWN_BUILD) setNewBuild(ev.build)
      return
    }
    if (ev.type === 'zoom') {
      setZoom(clampZoom(ev.factor))
      return
    }
    if (!readyRef.current) { pending.current.push(ev); return }
    if (ev.type === 'goto') goToPage(ev.tab)
    else if (ev.type === 'command-bar') window.dispatchEvent(new Event(COMMAND_EVENT))
  }, [])

  useEffect(() => {
    if (!desktop) return
    const off = onShellEvent(handle)
    shellStatus().then(s => { if (s) handle({ type: 'status', status: s }) })
    return off
  }, [desktop, handle])

  useEffect(() => {
    readyRef.current = ready
    if (!ready || !pending.current.length) return
    // children's effects (page.tsx GOTO listener, CommandBar) ran before this parent effect: safe to replay
    const queued = pending.current.splice(0)
    queued.forEach(handle)
  }, [ready, handle])

  // ── desktop: status staleness → grey dots; no status at all → browser health monitor as fallback ────────
  // No push for STATUS_PULL_MS → pull the shell's cached status, so a slow heartbeat never greys the dots
  // (C1-desktop-native-03); a stopped poller still goes stale because freshness is the poller's own `at`.
  useEffect(() => {
    if (!desktop) return
    const bootAt = Date.now()
    if (!statusRxRef.current) statusRxRef.current = bootAt
    let pulling = false
    const id = setInterval(() => {
      const now = Date.now()
      setStaleTick(t => t + 1)
      if (!pulling && now - statusRxRef.current >= STATUS_PULL_MS) {
        pulling = true
        shellStatus().then(st => { if (st) handle({ type: 'status', status: st }) }).finally(() => { pulling = false })
      }
      setFallback(prev => {
        const silent = statusAtRef.current === 0 ? now - bootAt > STATUS_FALLBACK_MS : isStatusStale(statusAtRef.current, now)
        return prev === silent ? prev : silent
      })
    }, 5000)
    return () => clearInterval(id)
  }, [desktop, handle])

  // ── browser (or desktop fallback): ui-api health monitor ───────────────────────────────────────────────
  useEffect(() => {
    if (!ready || (desktop && !fallback)) { setHealth(null); return }
    const m = new HealthMonitor()
    monitorRef.current = m
    const off = m.subscribe(setHealth)
    m.start()
    return () => { off(); m.stop(); monitorRef.current = null }
  }, [ready, desktop, fallback])

  // ── connection state → banner phase ────────────────────────────────────────────────────────────────────
  const useShellSignal = desktop && !fallback
  const down: boolean | null = useShellSignal
    ? (status ? !status.ui_api.up : null)
    : (health ? health.state === 'down' : null)

  useEffect(() => {
    if (down === true) {
      if (phase === 'down') return
      const since = useShellSignal ? Date.now() : (health?.since ?? Date.now())
      const t = setTimeout(() => { setDownSince(since); setPhase('down') }, useShellSignal ? DESKTOP_DOWN_GRACE_MS : 0)
      return () => clearTimeout(t)
    }
    if (down === false && phase === 'down') {
      const outage = downSince ? Date.now() - downSince : null
      setOutageMs(outage)
      setPhase('recovered')
      setReconnects(n => n + 1)
      // the terminal reloads pages whose loads failed during the outage (app/page.tsx, lib/reconnect.ts)
      try {
        window.dispatchEvent(new CustomEvent<ReconnectedDetail>(RECONNECTED_EVENT, { detail: { outageMs: outage } }))
      } catch { /* no CustomEvent: pages recover on their next poll */ }
      return
    }
    if (phase === 'recovered') {
      const t = setTimeout(() => setPhase('hidden'), RECOVERED_MS)
      return () => clearTimeout(t)
    }
    return undefined
  }, [down, phase, downSince, useShellSignal, health?.since])

  // ── data-service strip (O-F5a, D-BOOT): WARMING UP while data-service starts, DB READ-ONLY while the store
  // holds a stale lock. One poller for the whole shell; precedence LINK DOWN > WARMING UP > DB READ-ONLY.
  const upstream = useUpstreamHealth(ready)
  const upstreamKind = phase === 'hidden' ? upstreamStripKind(upstream) : null

  // ── risk cockpit (O-F3, SPEC §3): the STAND DOWN banner is a ConnectionBanner sibling with the same
  // geometry, with precedence BELOW the outage messages (LINK DOWN / recovered / WARMING UP / DB READ-ONLY
  // outrank a discipline message).
  const standDown = useStandDownState()
  const showStandDown = ready && standDown.banner && phase === 'hidden' && upstreamKind === null

  // ── layout offset: strip + banner (the single writer of --shell-top; before paint, so no shift) ─────────
  // The strip is window chrome: 32 SCREEN px at every page zoom (K3), i.e. 32 / zoom CSS px of the page.
  const stripTop = desktop ? stripHeightCss(zoom) : 0
  const shellTop = stripTop + (upstreamKind !== null || phase !== 'hidden' || showStandDown ? BANNER_HEIGHT : 0)
  useLayoutEffect(() => { setShellTop(shellTop, desktop ? 'desktop' : 'browser') }, [shellTop, desktop])

  // ── desktop: current page for the strip + native window title ──────────────────────────────────────────
  useEffect(() => {
    if (!desktop) return
    installLocationWatcher()
    const read = () => setTab(tabFromSearch(window.location.search))
    read()
    const off = onLocationChange(read)
    const id = setInterval(read, 1000) // safety net if something bypasses the history wrapper
    return () => { off(); clearInterval(id) }
  }, [desktop])
  const pageMetaNow = useMemo(() => pageMeta(tab, typeof document !== 'undefined' ? document.title : ''), [tab])
  // BRF's label follows the page's own time-of-day title (Session / Evening / Overnight / Morning brief) in the strip
  // and the native window title, re-checked each minute only while BRF is shown (CT-13)
  const briefMinute = useMinuteWhile(desktop && tab === 'brief')
  const meta = useMemo(() => {
    const p = istParts(Date.now())
    const label = stripLabel(pageMetaNow, p.weekday, p.minutes)
    return label === pageMetaNow.label ? pageMetaNow : { code: pageMetaNow.code, label }
  }, [pageMetaNow, briefMinute])   // briefMinute: only re-runs this each minute while BRF is shown
  const lastTitle = useRef('')
  useEffect(() => {
    if (!desktop || !ready) return
    const t = windowTitle(meta)
    if (t === lastTitle.current) return
    lastTitle.current = t
    setWindowTitle(t)
  }, [desktop, ready, meta])

  // ── browser: new-build watch ───────────────────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!ready || desktop) return
    return startBuildWatch(id => setNewBuild(id))
  }, [ready, desktop])

  // ── both modes: one-time "settings not imported yet" notice (C3-01) ──────────────────────────────────────
  // Re-evaluated after every server read (boot hydration, focus refetch) and when another window dismissed it.
  useEffect(() => {
    if (!ready) return
    const evaluate = () => {
      let marker: string | null = null
      try { marker = window.localStorage.getItem(MIGRATE_NOTICE_KEY) } catch { /* storage blocked */ }
      const st = migrationNoticeState({
        pageOrigin: window.location.origin, mode: prefsSyncStatus()?.mode ?? 'off', marker, server: prefsServerInfo(),
      })
      if (st === 'imported') {
        try { window.localStorage.setItem(MIGRATE_NOTICE_KEY, 'imported') } catch { /* storage blocked */ }
      }
      setMigration(st)
    }
    const onStorage = (e: StorageEvent) => { if (e.key === MIGRATE_NOTICE_KEY || e.key === null) evaluate() }
    evaluate()
    window.addEventListener(PREFS_SERVER_EVENT, evaluate)
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener(PREFS_SERVER_EVENT, evaluate)
      window.removeEventListener('storage', onStorage)
    }
  }, [ready])
  const dismissMigration = useCallback(() => {
    try { window.localStorage.setItem(MIGRATE_NOTICE_KEY, 'dismissed') } catch { /* storage blocked: hidden for this page */ }
    setMigration('hide')
  }, [])

  // ── ChunkLoadError outside render (render-time ones reach the page's error boundary or global-error.tsx) ──
  useEffect(() => {
    const onRejection = (e: PromiseRejectionEvent) => {
      if (!isChunkLoadError(e.reason)) return
      reportClientError(e.reason, { kind: 'chunk' })
      void recoverFromChunkError()
    }
    window.addEventListener('unhandledrejection', onRejection)
    return () => window.removeEventListener('unhandledrejection', onRejection)
  }, [])

  const reload = useCallback(() => window.location.reload(), [])
  const retry = useCallback(() => monitorRef.current?.probeNow(), [])

  const link: ShellState['link'] = phase === 'down' ? 'down' : 'up'
  const shellState = useMemo<ShellState>(() => ({ desktop, link, downSince: link === 'down' ? downSince : null, zoom, reconnects }),
    [desktop, link, downSince, zoom, reconnects])

  if (!ready) return <BootGate />

  const statusStale = !status || isStatusStale(statusAt, Date.now())
  const notice = migrationNoticeText(migration)
  return (
    <ShellStateContext.Provider value={shellState}>
      {desktop && (
        <TitleStrip meta={meta} status={status} statusStale={statusStale} ownBuild={OWN_BUILD}
          newBuild={newBuild} onReload={reload} zoom={zoom} />
      )}
      <ConnectionBanner phase={phase} top={stripTop} downSince={downSince} outageMs={outageMs}
        nextProbeAt={health?.nextProbeAt ?? null} desktop={useShellSignal}
        onRetry={useShellSignal ? undefined : retry} />
      {ready && upstreamKind !== null && (
        <UpstreamStrip kind={upstreamKind} top={stripTop} nextProbeAt={upstream.nextProbeAt} />
      )}
      {showStandDown && <StandDownBanner top={stripTop} />}
      {!desktop && newBuild && newBuild !== dismissed && (
        <BuildPill build={newBuild} onReload={reload} onDismiss={() => setDismissed(newBuild)} />
      )}
      {notice && <MigrationNotice text={notice} onDismiss={dismissMigration} />}
      {children}
      {desktop && <FindBar />}
    </ShellStateContext.Provider>
  )
}
