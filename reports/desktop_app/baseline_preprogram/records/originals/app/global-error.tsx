'use client'

/**
 * global-error.tsx — Surfaces the real exception message in production.
 * Remove or harden after diagnosis.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="en">
      <body style={{
        background: '#05070a',
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
