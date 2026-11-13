'use client'

/**
 * The risk cockpit's shared client state (B-COCKPIT, risk/SPEC.md §§1–3).
 *
 * One module-level store feeds every mount (DISCIPLINE panel, the terminal-wide stand-down banner, the header
 * chips, the scenario strip's tones, the pre-trade checklist), so the day read is polled ONCE per window, not
 * once per component.
 *
 *  - Settings / stand-down / checklist live in the three prefs keys (disciplineModel.ts) through the GENERIC
 *    prefs API: GET /api/prefs on first use + window focus, PUT /api/prefs/{key} {value, updated_at} on change
 *    (LWW; a 409 means a newer value is stored — the server's copy is adopted, the standard sync rule).
 *    The keys are deliberately NOT in lib/prefs/keys.ts SYNC_KEYS: this module is their one reader/writer, and
 *    an unlisted key stays local in the generic engine (safe default). A localStorage mirror gives instant
 *    state on reload; the server stays the source of truth.
 *  - `suryadhana.prefs.mode` = 'readonly' (QA audits against the live terminal) is honoured: the cockpit then
 *    never PUTs — trips and edits change this window's memory only.
 *  - The guard: after every day read the rules are evaluated (disciplineModel.evalDay) and a newly called trip
 *    is written ONCE per session. Acknowledge collapses the banner to the header chip; nothing unlocks,
 *    because nothing is locked (O-F3: the cockpit never blocks anything).
 *
 * PAPER ONLY: everything here reads the paper book and the prefs store; no order path exists or is named.
 */
import { useEffect, useState } from 'react'
import client from '@/lib/api'
import { goToPage } from '@/lib/navigate'
import { setSubInUrl } from '@/components/terminal/source'
import {
  CHECKLIST_KEY, DISCIPLINE_KEY, STANDDOWN_KEY,
  evalDay, parseSettings, parseStandDown, remainingCap, serializeSettings, serializeStandDown, sessionKey,
  standDownActive, tripRecord,
  type DayBook, type DayEval, type DisciplineSettings, type StandDownRecord,
} from './disciplineModel'

const DAY_POLL_MS = 60_000
const PREFS_REFETCH_MIN_MS = 30_000
const KEYS = [DISCIPLINE_KEY, STANDDOWN_KEY, CHECKLIST_KEY] as const

export interface DisciplineStore {
  /** prefs answered at least once (server or mirror) */
  loaded: boolean
  /** null = unconfigured: the card opens in "set your capital" state (SPEC §1) */
  settings: DisciplineSettings | null
  standdown: StandDownRecord | null
  checklistRaw: string | null
  day: DayBook | null
  /** 'pending' = the /day route is not on this ui-api yet (deploy pending); else an error line */
  dayErr: string | null
  dayLoading: boolean
}

const store: DisciplineStore = { loaded: false, settings: null, standdown: null, checklistRaw: null, day: null, dayErr: null, dayLoading: false }
const subs = new Set<() => void>()
let snapshot: DisciplineStore = { ...store }
let dayTimer: ReturnType<typeof setInterval> | null = null
let prefsAt = 0
let prefsInFlight = false
let listenersInstalled = false

function notify(): void {
  snapshot = { ...store }
  subs.forEach(fn => { try { fn() } catch { /* a dead subscriber never breaks the rest */ } })
}

// ── localStorage mirror (instant state on reload; server remains the source of truth) ───────────────────────

function mirrorGet(key: string): string | null {
  try { return window.localStorage.getItem(key) } catch { return null }
}
function mirrorSet(key: string, value: string | null): void {
  try {
    if (value == null) window.localStorage.removeItem(key)
    else window.localStorage.setItem(key, value)
  } catch { /* storage blocked: memory only */ }
}

function readonlyMode(): boolean {
  try { return window.localStorage.getItem('suryadhana.prefs.mode') === 'readonly' } catch { return false }
}

function applyRaw(key: string, raw: string | null): void {
  if (key === DISCIPLINE_KEY) store.settings = parseSettings(raw)
  else if (key === STANDDOWN_KEY) store.standdown = parseStandDown(raw)
  else if (key === CHECKLIST_KEY) store.checklistRaw = raw
}

// ── prefs: GET all (the generic route has no per-key GET), PUT per key with LWW ──────────────────────────────

async function fetchPrefs(force = false): Promise<void> {
  if (prefsInFlight || (!force && Date.now() - prefsAt < PREFS_REFETCH_MIN_MS)) return
  prefsInFlight = true
  try {
    const r = await client.get<{ prefs?: Record<string, { value?: unknown; deleted?: unknown }> }>('/api/prefs', { timeout: 10_000 })
    prefsAt = Date.now()
    const prefs = r.data?.prefs ?? {}
    for (const key of KEYS) {
      const rec = prefs[key]
      const raw = rec && rec.deleted !== true && typeof rec.value === 'string' ? rec.value : null
      applyRaw(key, raw)
      mirrorSet(key, raw)
    }
    store.loaded = true
    notify()
  } catch {
    // server unreachable or prefs store down: the mirror (already applied) carries the window
    if (!store.loaded) { store.loaded = true; notify() }
  } finally {
    prefsInFlight = false
  }
}

/** PUT one key; on 409 the server's newer value is adopted (never retried over it). Readonly mode: memory only. */
export async function putPref(key: string, value: string): Promise<void> {
  applyRaw(key, value)
  mirrorSet(key, value)
  notify()
  if (readonlyMode()) return
  try {
    let origin: string | undefined
    try { origin = window.location.origin } catch { origin = undefined }
    await client.put(`/api/prefs/${encodeURIComponent(key)}`, { value, updated_at: Date.now(), origin }, { timeout: 10_000 })
  } catch (e) {
    const resp = (e as { response?: { status?: number; data?: { current?: { value?: unknown; deleted?: unknown } } } })?.response
    if (resp?.status === 409) {
      const cur = resp.data?.current
      const raw = cur && cur.deleted !== true && typeof cur.value === 'string' ? cur.value : null
      applyRaw(key, raw)
      mirrorSet(key, raw)
      notify()
    }
    // other failures: the local value stands for this window; the next prefs GET reconciles
  }
}

// ── the day read (SPEC M1) + the guard ───────────────────────────────────────────────────────────────────────

async function fetchDay(): Promise<void> {
  if (store.dayLoading) return
  store.dayLoading = true
  notify()
  try {
    const r = await client.get<DayBook>('/api/options/book/day', { timeout: 20_000 })
    store.day = r.data ?? null
    store.dayErr = null
    runGuard()
  } catch (e) {
    const st = (e as { response?: { status?: number } })?.response?.status
    store.dayErr = st === 404 ? 'pending' : 'day read unavailable'
  } finally {
    store.dayLoading = false
    notify()
  }
}

/** Write a newly called trip once per session (SPEC §1's stand-down record). Never clears or rewrites one. */
function runGuard(): void {
  const s = store.settings
  if (!s || !s.enabled) return
  const now = Date.now()
  if (standDownActive(store.standdown, now)) return
  const ev = evalDay(s, store.day, now)
  if (!ev.trip) return
  const rec = tripRecord(ev.trip, now)
  void putPref(STANDDOWN_KEY, serializeStandDown(rec))
}

// ── subscription lifecycle ───────────────────────────────────────────────────────────────────────────────────

function start(): void {
  if (!listenersInstalled) {
    listenersInstalled = true
    for (const key of KEYS) applyRaw(key, mirrorGet(key))   // instant state from the mirror
    try {
      window.addEventListener('focus', () => { void fetchPrefs(); if (document.visibilityState === 'visible') void fetchDay() })
    } catch { /* no window */ }
  }
  void fetchPrefs(true)
  void fetchDay()
  if (!dayTimer) {
    dayTimer = setInterval(() => {
      try { if (document.visibilityState === 'hidden') return } catch { /* no document */ }
      void fetchDay()
    }, DAY_POLL_MS)
  }
}

function stop(): void {
  if (dayTimer) { clearInterval(dayTimer); dayTimer = null }
}

function subscribe(fn: () => void): () => void {
  subs.add(fn)
  if (subs.size === 1) start()
  return () => {
    subs.delete(fn)
    if (subs.size === 0) stop()
  }
}

// ── public actions ───────────────────────────────────────────────────────────────────────────────────────────

export function saveSettings(s: DisciplineSettings): void {
  void putPref(DISCIPLINE_KEY, serializeSettings(s))
}

/** Collapse the banner to the header chip for the rest of the session. Nothing unlocks — nothing is locked. */
export function acknowledgeStandDown(): void {
  const rec = store.standdown
  if (!rec || rec.acknowledged) return
  void putPref(STANDDOWN_KEY, serializeStandDown({ ...rec, acknowledged: true }))
}

export function saveChecklistRaw(raw: string): void {
  void putPref(CHECKLIST_KEY, raw)
}

export function refreshDay(): void {
  void fetchDay()
}

// ── hooks ────────────────────────────────────────────────────────────────────────────────────────────────────

export interface DisciplineView extends DisciplineStore {
  /** the arithmetic over today's day read under the owner's rules */
  ev: DayEval
  /** ₹ left under the daily cap today; null when unconfigured */
  remainingCapInr: number | null
  /** the current discipline session (resets 09:15 IST) */
  session: string
  /** the stand-down record counts for the current session */
  tripped: boolean
}

/** The cockpit state, shared across every mount in the window. */
export function useDiscipline(): DisciplineView {
  const [snap, setSnap] = useState<DisciplineStore>(snapshot)
  useEffect(() => subscribe(() => setSnap(snapshot)), [])
  const now = Date.now()
  const ev = evalDay(snap.settings, snap.day, now)
  return {
    ...snap,
    ev,
    remainingCapInr: remainingCap(snap.settings, ev),
    session: sessionKey(now),
    tripped: snap.settings?.enabled !== false && standDownActive(snap.standdown, now) && snap.settings != null,
  }
}

/** Cheap derived flags for PlatformShell: whether the terminal-wide STAND DOWN banner occupies its strip. */
export function useStandDownState(): { banner: boolean; chip: boolean; record: StandDownRecord | null } {
  const d = useDiscipline()
  const active = d.tripped && d.standdown != null
  return {
    banner: active && !d.standdown!.acknowledged,
    chip: active && d.standdown!.acknowledged,
    record: active ? d.standdown : null,
  }
}

export const navigateToDiscipline = (): void => {
  // hand the sub-view over exactly like the GO aliases do, then switch the page
  try { setSubInUrl('discipline') } catch { /* no DOM */ }
  try { goToPage('risk') } catch { /* no DOM */ }
}
