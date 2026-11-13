'use client'

/**
 * One shared /api/data/health reader per window (FINAL ROUND C-FACE G8 + D-TONE G3, risk/TRUST_GAPS.md):
 * the header's DATA chip, the footer's DATA-date tone and any panel adopting its dataset's catalog verdict all read
 * this store, so the window fetches dataset health once (every 5 min visible, 15 min hidden), not per consumer.
 *
 * This file is the fetch/React half only. The pure faces live in ui/lib/dataHealthCore.ts (`staleChipFace`,
 * `catalogVerdictOf`) and ui/components/terminal/source.ts (`footerDataTone`, the one shared session-aware helper),
 * both unit-tested under plain node by ui/components/__tests__/face_tone.check.ts.
 */
import { useCallback, useSyncExternalStore } from 'react'
import type { DataHealth } from '../components/datahealth/healthModel'
import { applyCatalogVerdict, footerDataTone, type FooterDataTone, type SourceInfo } from '../components/terminal/source'
import { catalogVerdictOf, type HealthStoreSnap } from './dataHealthCore'

export { catalogVerdictOf, staleChipFace, type HealthFetchStatus, type HealthStoreSnap, type StaleChipFace } from './dataHealthCore'
export type { FooterDataTone }

export const HEALTH_POLL_MS = 300_000
export const HEALTH_POLL_HIDDEN_MS = 900_000
const FETCH_TIMEOUT_MS = 20_000

let snap: HealthStoreSnap = { status: 'idle', data: null, lastGoodAt: null, error: null }
const listeners = new Set<() => void>()
let timer: ReturnType<typeof setTimeout> | null = null
let inflight = false

const emit = () => { for (const l of listeners) { try { l() } catch { /* a consumer must not break the poller */ } } }

async function readOnce(): Promise<void> {
  if (inflight) return
  inflight = true
  const ctl = new AbortController()
  const kill = setTimeout(() => ctl.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch('/api/data/health', { signal: ctl.signal, headers: { Accept: 'application/json' } })
    if (r.status === 404) {
      snap = { ...snap, status: 'missing', error: 'the data-health route is not on this ui-api yet (Terminal v2 not deployed)' }
    } else if (!r.ok) {
      snap = { ...snap, status: 'error', error: `HTTP ${r.status}` }
    } else {
      const body = (await r.json().catch(() => null)) as DataHealth | null
      if (body && Array.isArray(body.rows)) snap = { status: 'ok', data: body, lastGoodAt: Date.now(), error: null }
      else snap = { ...snap, status: 'error', error: 'unreadable data-health payload' }
    }
  } catch (e) {
    snap = { ...snap, status: 'error', error: e instanceof Error ? e.message : 'data-health request failed' }
  } finally {
    clearTimeout(kill)
    inflight = false
    emit()
  }
}

function schedule(): void {
  if (timer != null || !listeners.size) return
  const hidden = typeof document !== 'undefined' && document.visibilityState === 'hidden'
  timer = setTimeout(() => {
    timer = null
    void readOnce().finally(() => schedule())
  }, hidden ? HEALTH_POLL_HIDDEN_MS : HEALTH_POLL_MS)
}

function subscribeHealth(cb: () => void): () => void {
  listeners.add(cb)
  if (listeners.size === 1 && snap.status === 'idle') void readOnce().finally(() => schedule())
  else schedule()
  return () => {
    listeners.delete(cb)
    if (!listeners.size && timer != null) { clearTimeout(timer); timer = null }
  }
}

const getSnap = () => snap
const SERVER_SNAP: HealthStoreSnap = { status: 'idle', data: null, lastGoodAt: null, error: null }
const getServerSnap = () => SERVER_SNAP

/** The window's shared data-health snapshot (polls while at least one consumer is mounted). */
export function useDataHealthStore(): HealthStoreSnap {
  return useSyncExternalStore(subscribeHealth, getSnap, getServerSnap)
}

/**
 * The footer's DATA-date tone for the dashboard's latest stored session (D-TONE G3): amber when behind the last NSE
 * session — the health service's holiday-aware `last_session` when it has answered, else the shared Mon–Fri helper.
 */
export function useFooterDataTone(latestDate: string | null | undefined): FooterDataTone {
  const s = useDataHealthStore()
  return footerDataTone(latestDate, s.data?.last_session ?? null)
}

/**
 * D-TONE G3 wiring (FINAL ROUND F-27): one store subscription per component — the returned toner hands a
 * panel's SourceInfo its dataset's `dataset_catalog` verdict (terminal/source.ts `applyCatalogVerdict`:
 * red/gap → the STALE treatment with the face keeping its own date/age text; amber → the hover names the
 * verdict; fresh/live rows and live/input/reference chips are untouched). The window still reads
 * /api/data/health ONCE per TTL: every consumer shares this store's poll — never a per-panel fetch.
 *
 *   const tone = useCatalogTone()
 *   <Panel source={tone(sourceOf(d.as_of, { source: 'NSE EOD' }), 'market_monitor')} …
 */
export function useCatalogTone(): (info: SourceInfo, datasetId: string) => SourceInfo {
  const s = useDataHealthStore()
  return useCallback((info: SourceInfo, datasetId: string): SourceInfo => {
    const v = catalogVerdictOf(s, datasetId)
    return v ? applyCatalogVerdict(info, v.state, v.note) : info
  }, [s])
}

/** Tests only: replace the snapshot without a fetch. */
export function _setHealthSnapForTest(next: HealthStoreSnap): void { snap = next; emit() }
