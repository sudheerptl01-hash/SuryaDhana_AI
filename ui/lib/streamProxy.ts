/**
 * Upstream headers for the optional Next :3000 server's stream proxies (ui/app/api/**\/route.ts), desktop review
 * SECREL-01 / C2-security-01.
 *
 * Next's `/api` rewrite (next/dist/server/lib/router-utils/proxy-request.js, http-proxy with changeOrigin) forwards
 * EVERY browser request header and sets `X-Forwarded-Host` to the browser's `Host`, so shared/http_guard.py on
 * ui-api sees the browser context: a rebinding `Host` fails the forwarded-host check (400), and a cross-site write
 * fails the `Origin` / `Sec-Fetch-Site` checks (403). The six route handlers that shadow the rewrite for streaming
 * bodies used to send only `content-type` / `accept`, so ui-api saw a trusted no-Origin local client: any web page
 * could POST a training run or backtest through http://127.0.0.1:3000, and a DNS-rebinding page could read the
 * scheduler log stream.
 *
 * `streamProxyHeaders` gives those handlers the same browser context the rewrite forwards, for the headers the guard
 * judges (and nothing else, so no cookie or credential ever leaves the browser's request):
 *   - `x-forwarded-host` = the incoming `Host`, always set and overriding any incoming value (exactly like the
 *     rewrite's `headers: {'x-forwarded-host': req.headers.host || ''}`);
 *   - `origin` and `sec-fetch-site` copied when present (Node's fetch sets its own `sec-fetch-mode: cors`, so the
 *     other Fetch-Metadata headers cannot be forwarded; the guard reads only these two);
 *   - `x-forwarded-for` copied when present (a client behind a proxy in front of :3000 stays remote = read-only).
 * Pure, no imports, no DOM (unit-tested with the real guard by `node ui/lib/__tests__/streamProxy.check.ts`).
 */

/** Browser-context headers forwarded verbatim when the incoming request carries them. */
export const FORWARDED_BROWSER_HEADERS = ['origin', 'sec-fetch-site', 'x-forwarded-for'] as const

/** The part of a Fetch `Headers` this module reads (a NextRequest's `headers` in the route handlers). */
export interface HeaderSource {
  get(name: string): string | null
}

/**
 * Headers for the upstream fetch to ui-api: `base` (the handler's own content-type / accept) plus the browser
 * context the guard needs. `base` never overrides the forwarded context.
 */
export function streamProxyHeaders(incoming: HeaderSource, base: Record<string, string> = {}): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(base)) out[k.toLowerCase()] = v
  for (const name of FORWARDED_BROWSER_HEADERS) {
    const v = incoming.get(name)
    if (v != null) out[name] = v
    else delete out[name]
  }
  out['x-forwarded-host'] = incoming.get('host') ?? ''
  return out
}
