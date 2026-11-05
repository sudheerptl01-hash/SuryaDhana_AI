/**
 * Streaming passthrough for the Training Terminal's RL job SSE feed (EventSource).
 *
 * The Training Terminal connects to `/api/pipeline/rl-stream/<jobId>`; the next.config.js
 * rewrite buffers the `text/event-stream` body so the live RL training log never streams.
 * This dynamic GET route handler shadows the rewrite and pipes the backend event-stream
 * straight through unbuffered. Same-origin, dev + Docker.
 */
import type { NextRequest } from 'next/server'
import { streamProxyHeaders } from '@/lib/streamProxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

export async function GET(req: NextRequest, { params }: { params: Promise<{ job_id: string }> }) {
  const { job_id } = await params
  const upstream = await fetch(
    `${API_BACKEND}/api/pipeline/rl-stream/${encodeURIComponent(job_id)}${req.nextUrl.search}`,
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
