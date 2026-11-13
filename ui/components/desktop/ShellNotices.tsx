'use client'

/**
 * Shell notices: the connection banner (ui-api down / reconnected), the data-service WARMING UP / DB READ-ONLY
 * strip (O-F5a, D-BOOT), the browser-mode "new build" pill, the one-time "settings not imported yet" notice and
 * the boot gate. Presentational only except the upstream poller hook; PlatformShell decides when each one shows
 * with precedence LINK DOWN > WARMING UP > DB READ-ONLY > STAND DOWN.
 */
import { memo, useEffect, useState } from 'react'
import { Z } from '@/lib/z'
import { T } from '@/components/news/format'
import { RECONNECTED_EVENT, type ReconnectedDetail } from '@/lib/reconnect'
import {
  latestUpstream, publishUpstream, reduceUpstreamProbe, subscribeUpstream, upstreamDelayMs, upstreamRecovered,
  READONLY_DETAIL, READONLY_MAIN, READONLY_TAG, UPSTREAM_URL, WARMING_DETAIL, WARMING_MAIN, WARMING_TAG,
  type UpstreamProbeResult, type UpstreamSnapshot,
} from './upstream'
import { useSecondTick, Z_SHELL } from './TitleStrip'

/**
 * Banner wording (C1-trader-ux-02): only what is guaranteed. Panels keep the last data they received; pages whose
 * loads failed during the outage are reloaded when the link is back (app/page.tsx on 'suryadhana:reconnected').
 */
export const BANNER_DOWN_DETAIL = 'panels show the last data received · failed pages reload when the link is back'
export const BANNER_UP_DETAIL = 'pages that failed during the outage are reloading'

/** Height of the connection banner; part of --shell-top while it is shown. */
export const BANNER_HEIGHT = 24

export type BannerPhase = 'hidden' | 'down' | 'recovered'

function fmtDuration(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m}:${String(s % 60).padStart(2, '0')} min` : `${Math.floor(m / 60)} h ${m % 60} min`
}

function DownBody({ since, nextProbeAt, onRetry, desktop }: { since: number; nextProbeAt: number | null; onRetry?: () => void; desktop: boolean }) {
  const now = useSecondTick()
  const retryIn = nextProbeAt ? Math.max(0, Math.ceil((nextProbeAt - now) / 1000)) : null
  return (
    <>
      <span className="sd-banner-tag">LINK DOWN</span>
      <span className="sd-banner-main">ui-api unreachable · reconnecting</span>
      <span className="sd-banner-dim">{BANNER_DOWN_DETAIL}</span>
      <span style={{ flex: 1 }} />
      <span className="sd-banner-dim">down {fmtDuration(now - since)}</span>
      {!desktop && retryIn !== null && <span className="sd-banner-dim">next check {retryIn} s</span>}
      {onRetry && <button type="button" className="sd-banner-btn" onClick={onRetry}>RETRY NOW</button>}
    </>
  )
}

export interface ConnectionBannerProps {
  phase: BannerPhase
  /** px from the top of the viewport (below the title strip in the app). */
  top: number
  downSince: number | null
  /** Duration of the last outage, for the recovered message. */
  outageMs: number | null
  nextProbeAt: number | null
  desktop: boolean
  onRetry?: () => void
}

export const ConnectionBanner = memo(function ConnectionBanner({ phase, top, downSince, outageMs, nextProbeAt, desktop, onRetry }: ConnectionBannerProps) {
  if (phase === 'hidden') return null
  const down = phase === 'down'
  return (
    <div role={down ? 'alert' : 'status'} aria-live={down ? 'assertive' : 'polite'}
      className={`sd-banner ${down ? 'is-down' : 'is-ok'}`} style={{ top, height: BANNER_HEIGHT, zIndex: Z_SHELL - 1 }}>
      {down
        ? <DownBody since={downSince ?? Date.now()} nextProbeAt={nextProbeAt} onRetry={onRetry} desktop={desktop} />
        : (
          <>
            <span className="sd-banner-tag">LINK UP</span>
            <span className="sd-banner-main">ui-api reconnected</span>
            {outageMs != null && <span className="sd-banner-dim">back after {fmtDuration(outageMs)}</span>}
            <span className="sd-banner-dim">{BANNER_UP_DETAIL}</span>
          </>
        )}
    </div>
  )
})

// ── data-service upstream strip (O-F5a, RISK §b; D-BOOT) ─────────────────────────────────────────────────────

const UPSTREAM_FETCH_TIMEOUT_MS = 3_000

/** One GET of /api/health/upstream. null = no signal (ui-api unreachable → ConnectionBanner's territory,
 *  or an older ui-api build without the route → never a strip of its own). */
async function probeUpstream(): Promise<UpstreamProbeResult | null> {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  const timer = setTimeout(() => ctl?.abort(), UPSTREAM_FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(UPSTREAM_URL, {
      cache: 'no-store', credentials: 'same-origin', signal: ctl?.signal, headers: { Accept: 'application/json' },
    })
    if (!r.ok) return null
    const b = await r.json() as { data_service?: unknown; db_read_only?: unknown }
    return { dataService: b.data_service === 'up' ? 'up' : 'down', dbReadOnly: b.db_read_only === true }
  } catch {
    return null
  } finally {
    clearTimeout(timer)
  }
}

/**
 * The shell's upstream poller (PlatformShell mounts it once). Publishes every verdict to the module store in
 * ./upstream so any component (UPDATE DATA's read-only reason) can subscribe, and on warming → up it dispatches
 * the SAME reconnected event as a ui-api recovery, so panels whose one-shot load failed while data-service was
 * starting reload through lib/reconnect.ts (pages that poll recover by themselves).
 */
export function useUpstreamHealth(active: boolean): UpstreamSnapshot {
  const [snap, setSnap] = useState<UpstreamSnapshot>(latestUpstream)
  useEffect(() => subscribeUpstream(setSnap), [])
  useEffect(() => {
    if (!active) return
    let alive = true
    let inFlight = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const clear = () => { if (timer) { clearTimeout(timer); timer = null } }
    const schedule = (ms: number) => {
      if (!alive || (typeof document !== 'undefined' && document.hidden)) return
      publishUpstream({ ...latestUpstream(), nextProbeAt: Date.now() + ms })
      timer = setTimeout(run, ms)
    }
    const run = () => {
      if (!alive || inFlight) return
      clear()
      inFlight = true
      void probeUpstream().then(res => {
        inFlight = false
        if (!alive) return
        const prev = latestUpstream()
        const next = reduceUpstreamProbe(prev, res, Date.now())
        publishUpstream(next)
        if (upstreamRecovered(prev, next)) {
          try {
            window.dispatchEvent(new CustomEvent<ReconnectedDetail>(RECONNECTED_EVENT, { detail: { outageMs: Date.now() - prev.since } }))
          } catch { /* no CustomEvent: polling panels recover on their next poll */ }
        }
        schedule(upstreamDelayMs(next))
      })
    }
    const onWake = () => { if (!document.hidden) run() }
    const onVis = () => { if (document.hidden) clear(); else run() }
    window.addEventListener('focus', onWake)
    window.addEventListener('online', onWake)
    document.addEventListener('visibilitychange', onVis)
    run()
    return () => {
      alive = false
      clear()
      window.removeEventListener('focus', onWake)
      window.removeEventListener('online', onWake)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [active])
  return snap
}

/** The latest upstream verdict for any component (read-only disable reasons etc.); no polling of its own. */
export function useUpstreamSnapshot(): UpstreamSnapshot {
  const [snap, setSnap] = useState<UpstreamSnapshot>(latestUpstream)
  useEffect(() => subscribeUpstream(setSnap), [])
  return snap
}

/**
 * WARMING UP / DB READ-ONLY strip: ConnectionBanner's geometry (24 px under the title strip), calm amber, no
 * flashing, 150 ms ease-in (W4). Copy is SPEC verbatim — a fact and a visible self-retry, never a raw transport
 * string, never an instruction.
 */
export const UpstreamStrip = memo(function UpstreamStrip({ kind, top, nextProbeAt }: {
  kind: 'warming' | 'readonly'; top: number; nextProbeAt: number | null
}) {
  const now = useSecondTick()
  const retryIn = nextProbeAt ? Math.max(0, Math.ceil((nextProbeAt - now) / 1000)) : null
  const warming = kind === 'warming'
  return (
    <div role="status" aria-live="polite" data-sd-upstream={kind}
      style={{ position: 'fixed', left: 0, right: 0, top, height: BANNER_HEIGHT, zIndex: Z_SHELL - 1,
               display: 'flex', alignItems: 'center', gap: 12, padding: '0 10px 0 0', overflow: 'hidden',
               whiteSpace: 'nowrap', fontFamily: T.mono, fontSize: 10, letterSpacing: '.08em',
               background: '#100c03', color: T.amber, borderBottom: `1px solid ${T.amber}77`,
               animation: 'sd-upstream-in .15s ease-in both' }}>
      <span style={{ alignSelf: 'stretch', display: 'flex', alignItems: 'center', padding: '0 10px', fontWeight: 700,
                     letterSpacing: '.16em', color: '#05070a', background: T.amber }}>
        {warming ? WARMING_TAG : READONLY_TAG}
      </span>
      <span style={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {warming ? WARMING_MAIN : READONLY_MAIN}
      </span>
      <span style={{ color: T.muted }}>{warming ? WARMING_DETAIL : READONLY_DETAIL}</span>
      <span style={{ flex: 1 }} />
      {retryIn !== null && (
        <span style={{ color: T.muted }}>{warming ? 'retry' : 're-check'} in {retryIn} s</span>
      )}
      <style>{`@keyframes sd-upstream-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }`}</style>
    </div>
  )
})

/** Browser mode: a new UI build is being served. Reload, or dismiss until the next build. */
export function BuildPill({ build, onReload, onDismiss }: { build: string; onReload: () => void; onDismiss: () => void }) {
  return (
    <div className="sd-pill" role="status" aria-live="polite" style={{ zIndex: Z.toast }}>
      <span className="sd-pill-tag">NEW BUILD</span>
      <span className="sd-pill-text" title={build}>a newer terminal build is available</span>
      <button type="button" className="sd-pill-btn" onClick={onReload}>RELOAD</button>
      <button type="button" className="sd-pill-x" aria-label="Dismiss" onClick={onDismiss}>×</button>
    </div>
  )
}

/**
 * Both modes: the owner's settings may still live only in the old browser terminal (lib/prefs/migration.ts decides,
 * and picks the wording: a fact when the server proves nothing was imported, a conditional when it cannot say).
 * Plain text, not a link: the app never opens localhost URLs, and the browser to use is the one the owner used
 * before, which may not be this one. The address is selectable for copying. Dismissed for good with ×.
 * Docked in the page flow above the header (CT-15): it never floats over data rows or dialogs.
 */
export function MigrationNotice({ text, onDismiss }: { text: string; onDismiss: () => void }) {
  const [before, after = ''] = text.split('http://localhost:3000')
  return (
    <div className="sd-note" role="status" aria-live="polite" data-sd-note="">
      <span className="sd-note-tag">SETTINGS</span>
      <span className="sd-note-text">
        {before}<span className="sd-note-url">http://localhost:3000</span>{after}
      </span>
      <button type="button" className="sd-pill-x" aria-label="Dismiss this notice" title="Do not show again" onClick={onDismiss}>×</button>
    </div>
  )
}

/**
 * Boot gate: what the window shows until bootstrapPlatform() resolves (≤ ~1.5 s). Same background as the
 * terminal (no flash); the mark fades in only after 250 ms, so a fast boot shows plain black, never a blink.
 * Rendered on the server too, so the static index.html paints exactly this, and if the page can never hydrate
 * (server gone mid-load, a missing first-load chunk) a hint appears after 8 s without any JavaScript.
 */
export function BootGate() {
  return (
    <div className="sd-gate" aria-busy="true" aria-label="Starting SuryaDhana" style={{ zIndex: Z_SHELL + 10 }}>
      <div className="sd-gate-mark">
        <span className="sd-gate-word"><span className="sd-mark" aria-hidden />SURYADHANA</span>
        <span className="sd-gate-bar" />
        {/* pure CSS reveal after 8 s: shows even when JS never hydrates (e.g. a missing first-load chunk) */}
        <span className="sd-gate-slow">taking longer than usual · check ui-api · ⌘R / F5 reloads</span>
      </div>
    </div>
  )
}
