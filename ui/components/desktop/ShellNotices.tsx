'use client'

/**
 * Shell notices: the connection banner (ui-api down / reconnected), the browser-mode "new build" pill, the
 * one-time "settings not imported yet" notice and the boot gate. Presentational only; PlatformShell decides when
 * each one shows.
 */
import { memo } from 'react'
import { Z } from '@/lib/z'
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
