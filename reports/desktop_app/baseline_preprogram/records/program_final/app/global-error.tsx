'use client'

/**
 * global-error.tsx: the root error boundary (replaces the root layout while it shows).
 *
 * ChunkLoadError (a lazily loaded tab/modal chunk that the server no longer has, e.g. right after a UI release
 * swap): one guarded automatic reload (components/desktop/chunkRecovery.ts: at most one per 60 s per tab, and
 * only while the server answers; while it does not, it re-checks every 5 s and reloads once it is back).
 * Everything else, and a chunk error that repeats after the reload: today's behavior, the real exception message
 * with a Retry button.
 */
import { useEffect, useState } from 'react'
import { isChunkLoadError, recoverFromChunkError } from '@/components/desktop/chunkRecovery'

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

  return (
    <html lang="en" className="dark" style={{ background: BG, colorScheme: 'dark' }}>
      <body style={{
        background: BG,
        color: '#d6dbe4',
        fontFamily: 'JetBrains Mono, monospace',
        padding: '40px',
        minHeight: '100vh',
      }}>
        <h1 style={{ color: '#ff4d5e', marginBottom: 16, fontSize: 20 }}>
          ⚠ Client-side Exception
        </h1>
        <pre style={{
          background: '#0a0d13',
          border: '1px solid #ff4d5e',
          padding: 24,
          borderRadius: 8,
          overflowX: 'auto',
          fontSize: 13,
          lineHeight: 1.6,
          color: '#ffb000',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}>
          {error?.message || 'Unknown error'}{'\n\n'}
          {error?.stack || '(no stack)'}
        </pre>
        <p style={{ color: '#6f7a8e', marginTop: 16, fontSize: 12 }}>
          digest: {error?.digest ?? 'none'}
        </p>
        <button
          onClick={reset}
          style={{
            marginTop: 24,
            padding: '8px 20px',
            background: 'rgba(245,166,35,0.1)',
            border: '1px solid rgba(245,166,35,0.3)',
            color: '#ffb000',
            borderRadius: 6,
            cursor: 'pointer',
            fontSize: 13,
          }}
        >
          Retry
        </button>
      </body>
    </html>
  )
}
