/**
 * `/api/derivatives/iv/{symbol}/oi-tape` and `/api/derivatives/expiry-day` (services/ui-api/routers/expiry.py, PLAN 2.1 / 2.4).
 * Read-only; the payloads are stored rows (store, then show — PLAN §0.2).
 */
import axios from 'axios'
import { apiError } from '@/lib/errors'
import type { ExpiryDay, OiTape } from './tapeModel'

const client = axios.create({ baseURL: '', timeout: 20_000 })

export const getOiTape = (symbol: string, opts: { date?: string; expiry?: string } = {}) =>
  client.get<OiTape>(`/api/derivatives/iv/${encodeURIComponent(symbol)}/oi-tape`, { params: { date: opts.date, expiry: opts.expiry } })

export const getExpiryDay = (symbol: string, date?: string, n = 26) =>
  client.get<ExpiryDay>('/api/derivatives/expiry-day', { params: { symbol, date, n } })

export function tapeError(e: unknown, fallback = 'unavailable'): string {
  return apiError(e, fallback)
}

/** The store's own reason when it answered without data (`ok: false`). */
export function storeReason(m: { ok?: boolean; store_errors?: Record<string, string> } | null | undefined): string | null {
  if (!m || m.ok !== false) return null
  const v = Object.values(m.store_errors ?? {})
  return v.length ? v.join('; ') : 'store unavailable'
}
