/**
 * Pure faces of the window's shared /api/data/health reader (FINAL ROUND C-FACE G8 + D-TONE G3,
 * risk/TRUST_GAPS.md). Import-free at runtime (type-only imports), so
 * ui/components/__tests__/face_tone.check.ts runs it under plain node; the fetch/React half is
 * ui/lib/dataHealthStore.ts.
 *
 *  - G8: a fetch error must NOT render as "absent" — the header DATA chip keeps the last good count greyed with '?',
 *    and "health endpoint unreachable" is distinguishable from "DATA FRESH" and from "not deployed" (404 → nothing,
 *    as before: the chip never guesses about a pre-v2 ui-api).
 *  - G3: `catalogVerdictOf` hands a panel its dataset's catalog verdict so the chip can adopt it
 *    (terminal/source.ts `applyCatalogVerdict`).
 */
import type { DataHealth, HealthRow } from '../components/datahealth/healthModel'

export type HealthFetchStatus = 'idle' | 'ok' | 'error' | 'missing'

export interface HealthStoreSnap {
  status: HealthFetchStatus
  /** the last GOOD payload (kept through later errors — G8), null until one arrives */
  data: DataHealth | null
  /** epoch ms the last good payload arrived */
  lastGoodAt: number | null
  error: string | null
}

export interface StaleChipFace {
  label: string
  title: string
  /** ok = muted (fresh) · warn = amber (n stale) · unknown = dim grey (endpoint unreachable, G8) */
  tone: 'ok' | 'warn' | 'unknown'
  /** machine-readable count for the audit; null when unknown */
  n: number | null
}

/** Rows that are not fresh: amber + red + gaps (healthModel.staleCount's rule, kept import-free here). */
const countStale = (d: DataHealth): number =>
  d.summary ? (d.summary.amber ?? 0) + (d.summary.red ?? 0) + (d.summary.gaps ?? 0)
    : (d.rows ?? []).filter(r => r.state === 'amber' || r.state === 'red' || r.state === 'gap').length

const ORDER: Record<string, number> = { gap: 0, red: 1, amber: 2 }

const hhmmIst = (epochMs: number): string => {
  const ist = new Date(epochMs + 330 * 60_000)
  return `${String(ist.getUTCHours()).padStart(2, '0')}:${String(ist.getUTCMinutes()).padStart(2, '0')}`
}

const badNames = (d: DataHealth): string => {
  const bad = (d.rows ?? []).filter(x => x.state === 'gap' || x.state === 'red' || x.state === 'amber')
    .sort((a, b) => (ORDER[a.state] ?? 9) - (ORDER[b.state] ?? 9) || (b.lag_sessions ?? -1) - (a.lag_sessions ?? -1) || a.label.localeCompare(b.label))
  return bad.length ? `Not fresh: ${bad.slice(0, 6).map(x => `${x.label} (${x.state})`).join(', ')}${bad.length > 6 ? ` +${bad.length - 6}` : ''}`
    : 'Every catalogued dataset is fresh'
}

/**
 * The header DATA chip's face for a snapshot (G8). Null = render nothing: only while the route is missing (404,
 * pre-v2 "not deployed") or nothing has been asked yet — never because a fetch failed.
 */
export function staleChipFace(s: HealthStoreSnap): StaleChipFace | null {
  if (!s.data) {
    if (s.status === 'error') {
      return { label: 'DATA ?', n: null, tone: 'unknown',
               title: 'dataset health unreachable — freshness unknown · click for SYS › DATA' }
    }
    return null                                                       // idle (not asked yet) or 404 (not deployed): the chip never guesses
  }
  const n = countStale(s.data)
  if (s.status === 'error' || s.status === 'missing') {
    // the last good count, greyed, with the honest '?' — never silently absent, never passed off as current
    return { label: `${n > 0 ? `DATA ${n} STALE` : 'DATA FRESH'} ?`, n, tone: 'unknown',
             title: `dataset health unreachable — showing the last reading${s.lastGoodAt ? ` (${hhmmIst(s.lastGoodAt)} IST)` : ''} · click for SYS › DATA` }
  }
  return { label: n > 0 ? `DATA ${n} STALE` : 'DATA FRESH', n, tone: n > 0 ? 'warn' : 'ok',
           title: `${badNames(s.data)} · click for SYS › DATA` }
}

/** The catalog verdict ('fresh' | 'amber' | 'red' | 'gap' | 'live') of one dataset row, null when unknown. */
export function catalogVerdictOf(s: HealthStoreSnap | null, datasetId: string): { state: string; note: string | null } | null {
  const row: HealthRow | undefined = s?.data?.rows?.find(r => r.id === datasetId)
  return row ? { state: String(row.state), note: row.lag_sessions != null && row.lag_sessions > 0 ? `${row.lag_sessions} sessions behind` : null } : null
}
