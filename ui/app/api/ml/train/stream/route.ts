/**
 * Streaming passthrough for the ML training NDJSON feed.
 *
 * Why this exists: next.config.js rewrites `/api/:path*` to the backend, but the
 * Next.js rewrite proxy BUFFERS streaming response bodies — so the per-boosting-round
 * `epoch` frames never reach the browser until the whole run ends (the live convergence
 * chart / progress HUD freeze at round 0). This route handler shadows the rewrite for the
 * streaming endpoint only and pipes the backend's ReadableStream straight through, so each
 * frame flushes the instant the backend emits it. Same-origin (no CORS), works in dev and
 * Docker. Non-streaming endpoints keep using the rewrite.
 */
import type { NextRequest } from 'next/server'
import { streamProxyHeaders } from '@/lib/streamProxy'

export const dynamic = 'force-dynamic'   // never cache / prerender
export const runtime = 'nodejs'          // node fetch can stream the upstream body

const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

export async function POST(req: NextRequest) {
  const upstream = await fetch(`${API_BACKEND}/api/ml/train/stream`, {
    method: 'POST',
    // browser context (Origin, Sec-Fetch-*, X-Forwarded-Host) like Next's rewrite, so ui-api's guard judges it
    headers: streamProxyHeaders(req.headers, { 'content-type': 'application/json' }),
    body: await req.text(),
    // Node's fetch requires duplex for a request that may stream; harmless here.
    // @ts-expect-error duplex is valid at runtime but missing from the DOM lib types
    duplex: 'half',
  })

  // Return the upstream body unbuffered. The anti-buffering headers tell any
  // intermediate proxy (and the browser) not to coalesce the chunks.
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      'content-type': upstream.headers.get('content-type') || 'application/x-ndjson',
      'cache-control': 'no-cache, no-transform',
      'x-accel-buffering': 'no',
      connection: 'keep-alive',
    },
  })
}
