'use client'

/**
 * UI error surfaces (C1-trader-ux-01, completeness-02).
 *
 * Every uncaught error, unhandled rejection and caught render error is recorded and reported to ui-api by
 * lib/clientErrors.ts (POST /api/client-errors, K1). Two ways to see them on screen:
 *
 *  - UiErrorChip (always): a compact '⚠ N UI ERRORS' segment in the status line, shown only when this window has
 *    recorded an error (on any page it showed since it loaded). Click: a small list (message, page, time, whether
 *    ui-api got the report) with COPY DETAILS (stacks included) and CLEAR.
 *    It never covers the trading screen.
 *  - ErrorCatcher (developer flag only): the old full overlay with stacks, now behind `next dev` or
 *    localStorage 'suryadhana.debug.errors' = '1'. It used to be mounted for everyone with a header saying
 *    "DIAGNOSTIC TOOL. Remove once the root cause is identified".
 */

import { Z } from '@/lib/z'
import { useEffect, useState, useSyncExternalStore } from 'react'
import { clearClientErrors, clientErrorLog, clientErrorsVersion, subscribeClientErrors, type ClientErrorEntry } from '@/lib/clientErrors'

export const DEBUG_ERRORS_KEY = 'suryadhana.debug.errors'

let snapshot: readonly ClientErrorEntry[] = []
let version = -1
function getSnapshot(): readonly ClientErrorEntry[] {
  const v = clientErrorsVersion()
  if (v !== version) { version = v; snapshot = [...clientErrorLog()] }
  return snapshot
}
const EMPTY: readonly ClientErrorEntry[] = []

function useClientErrors(): readonly ClientErrorEntry[] {
  return useSyncExternalStore(subscribeClientErrors, getSnapshot, () => EMPTY)
}

function debugFlag(): boolean {
  if (process.env.NODE_ENV !== 'production') return true
  try { return window.localStorage.getItem(DEBUG_ERRORS_KEY) === '1' } catch { return false }
}

function detailsText(errors: readonly ClientErrorEntry[]): string {
  return errors.map(e => [
    `[${new Date(e.at).toISOString()}] ${e.report.kind ?? 'error'} · ${e.report.tab || '-'} · ${e.report.build || 'dev'}`,
    e.report.message, e.report.stack ?? '',
  ].join('\n')).join('\n\n')
}

const ist = (ms: number) => new Date(ms).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })

/** Per-entry delivery wording (R-UI-SHELL-09): 'reported' only once ui-api accepted the report. */
const DELIVERY_LABEL: Record<ClientErrorEntry['delivery'], string> = {
  sending: 'REPORTING…', reported: 'REPORTED', failed: 'NOT REPORTED (SEND FAILED)', 'not-sent': 'NOT REPORTED',
}

/** Status-line chip: '⚠ N UI ERRORS' while this window has recorded errors. */
export function UiErrorChip() {
  const errors = useClientErrors()
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); setOpen(false) } }
    const onDown = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest?.('[data-ui-errors]')) setOpen(false) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('mousedown', onDown) }
  }, [open])
  if (!errors.length) return null
  const last = errors[errors.length - 1]
  const copy = () => {
    try { void navigator.clipboard?.writeText(detailsText(errors)).then(() => setCopied(true), () => undefined) } catch { /* selectable below */ }
  }
  return (
    <span data-ui-errors style={{ position: 'relative' }}>
      <button type="button" className="sd-foot-btn" onClick={() => { setOpen(o => !o); setCopied(false) }}
        title={`Last: ${last.report.message}`} style={{ color: '#ff8a94', borderColor: 'rgba(255,77,94,.5)' }}>
        ⚠ {errors.length} UI ERROR{errors.length > 1 ? 'S' : ''}
      </button>
      {open && (
        <div role="dialog" aria-label="UI errors"
          style={{ position: 'absolute', bottom: 20, right: 0, width: 460, maxHeight: 320, overflowY: 'auto', zIndex: Z.dropdown,
                   background: '#0b0f16', border: '1px solid #2a3448', borderTop: '2px solid #ff4d5e', boxShadow: '0 12px 32px rgba(0,0,0,.6)',
                   padding: '8px 10px', fontSize: 10.5, letterSpacing: '.02em', textTransform: 'none', color: '#d6dbe4', whiteSpace: 'normal' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
            <span style={{ color: '#ff4d5e', fontWeight: 700, letterSpacing: '.14em' }}>UI ERRORS IN THIS WINDOW</span>
            <span style={{ flex: 1 }} />
            <button type="button" className="sd-foot-btn" style={{ color: '#ffb000', borderColor: '#2a3448' }} onClick={copy}>
              {copied ? 'COPIED ✓' : 'COPY DETAILS'}</button>
            <button type="button" className="sd-foot-btn" style={{ color: '#6f7a8e', borderColor: '#2a3448' }}
              onClick={() => { clearClientErrors(); setOpen(false) }}>CLEAR</button>
          </div>
          {[...errors].reverse().map((e, i) => (
            <div key={`${e.at}-${i}`} style={{ padding: '5px 0', borderTop: '1px solid #1a2130' }}>
              <div style={{ color: '#6f7a8e', fontSize: 9.5 }}>
                {ist(e.at)} IST · {(e.report.kind ?? 'error').toUpperCase()} · {e.report.tab || '—'} · {DELIVERY_LABEL[e.delivery]}
              </div>
              <div style={{ color: '#ffb000', wordBreak: 'break-word' }}>{e.report.message}</div>
            </div>
          ))}
        </div>
      )}
    </span>
  )
}

/** The developer overlay (full stacks). Renders nothing unless the debug flag is on. */
export function ErrorCatcher() {
  const errors = useClientErrors()
  const [enabled, setEnabled] = useState(false)
  const [hiddenBefore, setHiddenBefore] = useState(0)
  useEffect(() => { setEnabled(debugFlag()) }, [])
  const shown = errors.filter(e => e.at > hiddenBefore).slice(-5)
  if (!enabled || shown.length === 0) return null

  return (
    <div
      style={{
        position: 'fixed',
        top: 'calc(var(--shell-top, 0px) + 12px)',
        left: '50%',
        transform: 'translateX(-50%)',
        zIndex: Z.toast,
        background: '#0D0609',
        border: '1px solid #ff4d5e',
        padding: '16px 20px',
        maxWidth: 680,
        width: 'calc(100vw - 32px)',
        boxShadow: '0 0 40px rgba(255,59,71,0.25)',
        fontFamily: "'JetBrains Mono', 'Courier New', monospace",
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ color: '#ff4d5e', fontWeight: 700, fontSize: 11, letterSpacing: 2, textTransform: 'uppercase' }}>
          ⚠ Uncaught Client Exception ({shown.length}) · debug overlay
        </span>
        <button
          onClick={() => setHiddenBefore(Date.now())}
          style={{ background: 'rgba(255,59,71,0.1)', border: '1px solid rgba(255,59,71,0.3)', color: '#ff4d5e', padding: '2px 8px',
                   cursor: 'pointer', fontSize: 11, fontFamily: 'inherit' }}
        >
          Dismiss
        </button>
      </div>
      {shown.map((e, i) => (
        <div key={`${e.at}-${i}`} style={{ borderTop: i > 0 ? '1px solid rgba(255,59,71,0.2)' : 'none', paddingTop: i > 0 ? 12 : 0, marginTop: i > 0 ? 12 : 0 }}>
          <p style={{ color: '#ffb000', fontWeight: 600, fontSize: 12, marginBottom: 6 }}>
            [{(e.report.kind ?? 'error').toUpperCase()}] {e.report.message}
          </p>
          {e.report.stack && (
            <pre style={{ color: '#aab3c2', fontSize: 10, whiteSpace: 'pre-wrap', wordBreak: 'break-all', maxHeight: 200, overflowY: 'auto', margin: 0, lineHeight: 1.5 }}>
              {e.report.stack}
            </pre>
          )}
        </div>
      ))}
    </div>
  )
}
