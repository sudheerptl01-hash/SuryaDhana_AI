'use client'

/**
 * global-error.tsx: the LAST-RESORT root error boundary (replaces the root layout while it shows).
 *
 * Page render errors no longer get here: every page, the header, the stock window and the GO bar have their own
 * boundary (components/shell/TabErrorBoundary.tsx), so the chrome stays up (C1-trader-ux-01). Only an error in
 * the shell itself (layout, PlatformShell, providers) reaches this page.
 *
 * ChunkLoadError (a lazily loaded chunk that the server no longer has, e.g. right after a UI release swap): one
 * guarded automatic reload (components/desktop/chunkRecovery.ts: at most one per 60 s per tab, and only while
 * the server answers; while it does not, it re-checks every 5 s and reloads once it is back).
 * Everything else, and a chunk error that repeats after the reload: a terminal-styled card with the one-line
 * message, RELOAD and TRY AGAIN, and the stack only behind a DETAILS disclosure (no raw stack by default). The
 * error is reported once to ui-api (lib/clientErrors.ts, K1).
 */
import { useEffect, useState } from 'react'
import { isChunkLoadError, recoverFromChunkError } from '@/components/desktop/chunkRecovery'
import { deliveryText, reportClientError, subscribeClientErrors, type ClientErrorEntry } from '@/lib/clientErrors'

const BG = '#05070a'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  const chunk = isChunkLoadError(error)
  // 'reloading' covers the gap until the guard says no: a stale-chunk reload never flashes the exception card
  const [mode, setMode] = useState<'reloading' | 'waiting' | 'error'>(chunk ? 'reloading' : 'error')
  const [details, setDetails] = useState(false)
  // what became of the report (R-UI-SHELL-09): the card says "reported" only once ui-api accepted it
  const [report, setReport] = useState<ClientErrorEntry | null | undefined>(undefined)
  const [, setDeliveryTick] = useState(0)

  useEffect(() => { setReport(reportClientError(error, { kind: chunk ? 'chunk' : 'global' })) }, [error, chunk])
  useEffect(() => subscribeClientErrors(() => setDeliveryTick(t => t + 1)), [])

  useEffect(() => {
    if (!chunk) return
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const attempt = () => {
      recoverFromChunkError().then(outcome => {
        if (!alive) return
        if (outcome === 'guarded') setMode('error')
        else if (outcome === 'unreachable') { setMode('waiting'); timer = setTimeout(attempt, 5000) }
      })
    }
    attempt()
    return () => { alive = false; if (timer) clearTimeout(timer) }
  }, [chunk])

  if (mode !== 'error') {
    return (
      <html lang="en" className="dark" style={{ background: BG, colorScheme: 'dark' }}>
        <body style={{ background: BG, color: '#6f7a8e', margin: 0, minHeight: '100vh', display: 'flex', alignItems: 'center',
                       justifyContent: 'center', fontFamily: "'JetBrains Mono', ui-monospace, Menlo, monospace", fontSize: 11,
                       letterSpacing: '0.14em', textTransform: 'uppercase' }}>
          <span role="status" aria-live="polite">
            {mode === 'reloading' ? 'Loading the new terminal build…' : 'Server unreachable · reloading when it is back…'}
          </span>
        </body>
      </html>
    )
  }

  const msg = `${error?.name && error.name !== 'Error' ? `${error.name}: ` : ''}${error?.message || 'Unknown error'}`
  const btn = (color: string) => ({
    fontFamily: 'inherit', fontSize: 11, fontWeight: 700, letterSpacing: '.12em', color, background: 'transparent',
    border: `1px solid ${color}`, padding: '6px 14px', cursor: 'pointer',
  })
  return (
    <html lang="en" className="dark" style={{ background: BG, colorScheme: 'dark' }}>
      <body style={{ background: BG, color: '#d6dbe4', margin: 0, minHeight: '100vh', display: 'flex', alignItems: 'flex-start',
                     justifyContent: 'center', fontFamily: "'JetBrains Mono', ui-monospace, Menlo, monospace", paddingTop: '14vh' }}>
        <main role="alert" style={{ width: 'min(720px, calc(100vw - 32px))', background: '#0a0d13', border: '1px solid #1a2130',
                                     borderTop: '2px solid #ff4d5e', padding: '16px 18px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: BG, background: '#ffb000', padding: '2px 7px', letterSpacing: 1 }}>SURYADHANA</span>
            <span style={{ fontSize: 13, fontWeight: 700, letterSpacing: '.16em', color: '#ff4d5e' }}>THE TERMINAL HIT AN UNEXPECTED ERROR</span>
          </div>
          <p style={{ margin: '12px 0 0', fontSize: 12, lineHeight: 1.6 }}>
            The window could not recover on its own. Reload it to continue: your settings and watchlist are kept.
            {report === undefined ? '' : ` ${deliveryText(report)}`}
          </p>
          <p style={{ margin: '8px 0 0', fontSize: 11, color: '#6f7a8e', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
             title={msg}>{msg}</p>
          <div style={{ display: 'flex', gap: 10, marginTop: 16, flexWrap: 'wrap' }}>
            <button onClick={() => window.location.reload()} style={{ ...btn('#ffb000'), color: BG, background: '#ffb000' }}>↻ RELOAD</button>
            <button onClick={reset} style={btn('#ffb000')}>TRY AGAIN</button>
            <button onClick={() => setDetails(d => !d)} aria-expanded={details} style={btn('#6f7a8e')}>{details ? 'DETAILS ▴' : 'DETAILS ▾'}</button>
          </div>
          {details && (
            <pre style={{ marginTop: 12, maxHeight: 280, overflow: 'auto', background: BG, border: '1px solid #2a3448', padding: 12,
                          fontSize: 11, lineHeight: 1.5, color: '#aab3c2', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {msg}{'\n\n'}{error?.stack || '(no stack)'}{'\n\n'}digest: {error?.digest ?? 'none'}
            </pre>
          )}
        </main>
      </body>
    </html>
  )
}
