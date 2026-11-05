/**
 * Streaming passthrough for the walk-forward (WFO) backtest progress NDJSON feed.
 *
 * Same fix as app/api/ml/train/stream and app/api/analytics/backtest/stream: the
 * next.config.js rewrite proxy BUFFERS streaming bodies, freezing the WFO progress UI
 * until the whole multi-window run ends. This route handler shadows the rewrite for the
 * WFO stream only and pipes the backend ReadableStream straight through so each window's
 * progress frame flushes immediately. Same-origin, dev + Docker.
 */
import type { NextRequest } from 'next/server'
import { streamProxyHeaders } from '@/lib/streamProxy'

export const dynamic = 'force-dynamic'
export const runtime = 'nodejs'

const API_BACKEND = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8010'

export async function POST(req: NextRequest) {
  const upstream = await fetch(`${API_BACKEND}/api/analytics/wfo-backtest/stream`, {
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
