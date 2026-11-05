/**
 * One error contract for the terminal (Bloomberg program F2.4 / amendment A2).
 *
 * The backend keeps `detail` as a plain string (legacy-safe) and, when the new handler is
 * involved, adds a SIBLING `error: { code, message, hint? }`. Soft-200 degraded payloads use
 * the same `error` object; older routes still send `{ error: "msg" }` strings or
 * `{ connected: false }`. This module is the ONLY place that knows all of those shapes.
 *
 * Components call `apiError(e, fallback)` for display text, or `normalizeError(e)` when they
 * also want the machine `code`/`hint` (e.g. SourceChip's DEGRADED detail).
 */

export type ErrorCode =
  | 'not_found' | 'upstream_down' | 'degraded' | 'unauthorized' | 'invalid' | 'state' | 'internal'

export interface ApiErrorInfo {
  code: ErrorCode | null
  message: string
  hint?: string
}

const CODES: ReadonlySet<string> = new Set([
  'not_found', 'upstream_down', 'degraded', 'unauthorized', 'invalid', 'state', 'internal'])

type Dict = Record<string, unknown>
const isDict = (v: unknown): v is Dict => typeof v === 'object' && v !== null && !Array.isArray(v)

/** FastAPI validation errors arrive as [{msg, loc, type}, …]. */
function validationText(detail: unknown[]): string {
  return detail
    .map(d => (isDict(d) && typeof d.msg === 'string' ? d.msg : String(d)))
    .join('; ')
}

function fromPayload(data: Dict): ApiErrorInfo | null {
  // 1. The structured sibling (new contract): { error: { code, message, hint? } }
  const err = data.error
  if (isDict(err) && typeof err.message === 'string') {
    const code = typeof err.code === 'string' && CODES.has(err.code) ? (err.code as ErrorCode) : null
    return { code, message: err.message, hint: typeof err.hint === 'string' ? err.hint : undefined }
  }
  // 2. detail: string (FastAPI HTTPException) or validation array
  if (typeof data.detail === 'string' && data.detail) return { code: null, message: data.detail }
  if (Array.isArray(data.detail)) return { code: 'invalid', message: validationText(data.detail) }
  // 3. Legacy soft-200 string: { error: "msg" }
  if (typeof err === 'string' && err) return { code: 'degraded', message: err }
  // 4. Broker family: { connected: false, error?/detail? already handled above }
  if (data.connected === false) return { code: 'state', message: 'not connected' }
  return null
}

/** Any thrown value or payload → { code, message, hint }. Never throws, never returns an object child. */
export function normalizeError(e: unknown, fallback = 'unavailable'): ApiErrorInfo {
  if (typeof e === 'string' && e) return { code: null, message: e }
  if (isDict(e)) {
    // axios error: e.response.data is the payload
    const resp = e.response
    if (isDict(resp) && isDict(resp.data)) {
      const info = fromPayload(resp.data)
      if (info) return info
    }
    // raw payload passed directly (soft-200 bodies)
    const direct = fromPayload(e)
    if (direct) return direct
    if (typeof e.message === 'string' && e.message) return { code: null, message: e.message }
  }
  if (e instanceof Error && e.message) return { code: null, message: e.message }
  return { code: null, message: fallback }
}

/** Display string for error states: the message (components add their own styling). */
export function apiError(e: unknown, fallback = 'unavailable'): string {
  return normalizeError(e, fallback).message
}
