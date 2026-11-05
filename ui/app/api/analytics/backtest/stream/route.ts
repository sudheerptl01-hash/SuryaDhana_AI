/**
 * Streaming passthrough for the backtest progress NDJSON feed.
 *
 * Same fix as app/api/ml/train/stream: next.config.js rewrites `/api/:path*` to the
 * backend, but the Next.js rewrite proxy BUFFERS streaming bodies — so backtest progress
 * frames never reach the browser until the run ends, which is why the backtest spinner
 * appeared "stuck" even though the backend completed in seconds. This route handler shadows
 * the rewrite for the backtest stream only and pipes the backend ReadableStream straight
 * through, so each progress frame flushes immediately. Same-origin, dev + Docker.
 */
import type { NextRequest } from 'next/server'
import { streamProxyHeaders } from '@/lib/streamProxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

export async function POST(req: NextRequest) {
  const upstream = await fetch(`${API_BACKEND}/api/analytics/backtest/stream`, {
    method: 'POST',
    // browser context (Origin, Sec-Fetch-*, X-Forwarded-Host) like Next's rewrite, so ui-api's guard judges it
    headers: streamProxyHeaders(req.headers, { 'content-type': 'application/json' }),
    body: await req.text(),
    // @ts-expect-error duplex is valid at runtime but missing from the DOM lib types
    duplex: 'half',
  })

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
