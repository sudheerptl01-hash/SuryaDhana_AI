/**
 * Streaming passthrough for the System Telemetry SSE log feed (EventSource).
 *
 * Same fix as the ML/backtest streams: the next.config.js rewrite buffers streaming
 * bodies, so SSE `text/event-stream` frames never reach the browser and the live log
 * tail silently falls back to polling. This GET route handler shadows the rewrite for the
 * telemetry stream only and pipes the backend's event-stream straight through unbuffered.
 * Same-origin, dev + Docker.
 */
import type { NextRequest } from 'next/server'
import { streamProxyHeaders } from '@/lib/streamProxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

export async function GET(req: NextRequest) {
  const upstream = await fetch(
    `${API_BACKEND}/api/telemetry/logs/stream${req.nextUrl.search}`,
    { headers: streamProxyHeaders(req.headers, { accept: 'text/event-stream' }) },  // + browser context (SECREL-01)
  )

  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'text/event-stream',
      'cache-control': 'no-cache, no-transform',
      'x-accel-buffering': 'no',
      connection: 'keep-alive',
    },
  })
}
