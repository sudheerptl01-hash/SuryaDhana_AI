'use client'

/**
 * Price alerts (WTCH): "tell me when TCS goes above 2,200 or below 2,050".
 * Levels live on the server (ui-api /api/alerts, data/price_alerts.json). The master controller checks them every
 * minute in market hours and announces a crossing on the Mac (and Telegram when configured), so alerts fire with the
 * terminal closed; while WTCH is open it also triggers a check on every quote refresh. A crossed level fires once
 * and is removed. Not a broker order. Levels saved in this browser by the old version are moved to the server once.
 *
 * P11 (round 4b): a save that fails (ui-api down, a refused write, a validation error) is no longer silent: it fires
 * ALERT_SAVE_FAILED_EVENT, which the terminal shows as a toast (components/shell/ShellToasts.tsx), and the setter
 * resolves false. The last levels read are shared by every useAlerts() of the window, so a re-opened alert form
 * starts from the saved levels instead of empty boxes.
 */
import { useCallback, useEffect, useState } from 'react'
import { getPriceAlerts, putPriceAlert, runPriceAlerts, type AlertHitSrv, type AlertLevelsSrv } from '@/lib/api'
import { apiError } from '@/lib/errors'
import { notify as platformNotify } from '@/lib/platform'
import { ALERT_SAVE_FAILED_EVENT, alertNotification, initialSeen, type AlertSaveFailure } from '@/lib/alertText'

const LEGACY_KEY = 'suryadhana.alerts.v1'
const SEEN_KEY = 'suryadhana.alerts.seen.v2'
export const ALERTS_EVENT = 'suryadhana:alerts'

export type AlertLevels = AlertLevelsSrv
export type AlertHit = AlertHitSrv

// In-page copy of the marker: when storage is blocked the page still remembers what it showed (it used to replay
// the whole history on every check).
let seenMem = ''
function readSeen(): string { try { return localStorage.getItem(SEEN_KEY) || seenMem } catch { return seenMem } }
function writeSeen(at: string): void { seenMem = at; try { localStorage.setItem(SEEN_KEY, at) } catch { /* private window */ } }
/** First visit on this device: existing hits are not news (see initialSeen). Returns the marker in force. */
function ensureSeen(history: AlertHit[]): string {
  const cur = readSeen()
  if (cur) return cur
  const at = initialSeen(cur, history[0]?.at)
  writeSeen(at)
  return at
}

async function migrateLegacy(server: Record<string, AlertLevels>): Promise<boolean> {
  let legacy: Record<string, { above?: number; below?: number }> = {}
  try { legacy = JSON.parse(localStorage.getItem(LEGACY_KEY) || '{}') } catch { return false }
  const todo = Object.entries(legacy).filter(([sym]) => !server[sym])
  for (const [sym, lv] of todo) {
    try { await putPriceAlert(sym, { above: lv.above ?? null, below: lv.below ?? null }) } catch { return false }
  }
  try { localStorage.removeItem(LEGACY_KEY) } catch { /* ignore */ }
  return todo.length > 0
}

// The last server answer seen by any useAlerts() of this window: a newly mounted form (the stock window's ALERT chip,
// re-opened) starts from it instead of {} (P11: its boxes used to open empty and stay empty).
let lastAlerts: Record<string, AlertLevels> = {}
let lastHistory: AlertHit[] = []
function remember(d: { alerts: Record<string, AlertLevels>; history: AlertHit[] }): void {
  lastAlerts = d.alerts ?? {}
  lastHistory = d.history ?? []
}

/** Tell the terminal that a save did not reach the server (P11). Never throws. */
function reportSaveFailure(sym: string, e: unknown): void {
  try {
    window.dispatchEvent(new CustomEvent<AlertSaveFailure>(ALERT_SAVE_FAILED_EVENT, { detail: { sym, error: apiError(e, 'ui-api did not answer') } }))
  } catch { /* no window */ }
}

export function useAlerts() {
  const [alerts, setAlerts] = useState<Record<string, AlertLevels>>(() => lastAlerts)
  const [history, setHistory] = useState<AlertHit[]>(() => lastHistory)

  const sync = useCallback(async (migrate = false) => {
    try {
      let d = (await getPriceAlerts()).data
      if (migrate && await migrateLegacy(d.alerts)) d = (await getPriceAlerts()).data
      remember(d)
      setAlerts(d.alerts); setHistory(d.history)
      ensureSeen(d.history)                                            // first visit: old hits are not news
    } catch { /* ui-api down: keep what we have */ }
  }, [])

  useEffect(() => {
    sync(true)
    const on = () => { sync() }
    window.addEventListener(ALERTS_EVENT, on)
    const iv = setInterval(on, 30_000)
    return () => { window.removeEventListener(ALERTS_EVENT, on); clearInterval(iv) }
  }, [sync])

  /** Resolves true once the server stored the levels; false (and a toast, P11) when the save failed. */
  const setLevel = useCallback(async (sym: string, side: 'above' | 'below', value: number | null, yahoo?: string): Promise<boolean> => {
    const cur = { ...(alerts[sym] ?? {}) }
    const next = { above: cur.above ?? null, below: cur.below ?? null, [side]: value && value > 0 ? value : null }
    try {
      const d = (await putPriceAlert(sym, { above: next.above, below: next.below, yahoo: yahoo ?? cur.yahoo })).data
      remember(d)
      setAlerts(d.alerts); setHistory(d.history)
      window.dispatchEvent(new Event(ALERTS_EVENT))
      return true
    } catch (e) {
      reportSaveFailure(sym, e)
      return false
    }
  }, [alerts])

  /** Set (or clear, with nulls) any of the three levels in one call. `move` is an absolute % move vs prev close.
   *  Resolves true once stored; false (and a toast, P11) when the save failed. */
  const setLevels = useCallback(async (
    sym: string, levels: { above: number | null; below: number | null; move?: number | null }, yahoo?: string,
  ): Promise<boolean> => {
    try {
      const d = (await putPriceAlert(sym, { ...levels, yahoo: yahoo ?? alerts[sym]?.yahoo })).data
      remember(d)
      setAlerts(d.alerts); setHistory(d.history)
      window.dispatchEvent(new Event(ALERTS_EVENT))
      return true
    } catch (e) {
      reportSaveFailure(sym, e)
      return false
    }
  }, [alerts])

  /** Set (or clear, with nulls) both price levels in one call. Kept for existing callers (WatchMonitor). */
  const setBoth = useCallback((sym: string, above: number | null, below: number | null, yahoo?: string) =>
    setLevels(sym, { above, below }, yahoo), [setLevels])

  /** Ask the server to check now, then return hits this browser has not shown yet (fired here or by the scheduler). */
  const check = useCallback(async (): Promise<AlertHit[]> => {
    if (Object.keys(alerts).length) { try { await runPriceAlerts() } catch { /* scheduler will catch it */ } }
    let d: { alerts: Record<string, AlertLevels>; history: AlertHit[] }
    try { d = (await getPriceAlerts()).data } catch { return [] }
    remember(d)
    setAlerts(d.alerts); setHistory(d.history)
    // No marker yet (a new origin such as the desktop app, racing the mount sync above): adopt the newest hit as
    // seen instead of replaying the whole history as new toasts and notifications (C3-logic-unchanged-05).
    const seen = readSeen()
    if (!seen) { ensureSeen(d.history); return [] }
    const fresh = d.history.filter(h => h.at > seen)
    if (fresh[0]) writeSeen(fresh[0].at)
    return fresh
  }, [alerts])

  return { alerts, history, setLevel, setLevels, setBoth, check }
}

export function notify(hit: AlertHit): void {
  notifyHits([hit])
}

/**
 * One notification for one check's fresh hits (a count + the first few when there are several), the same in the
 * browser (Notification when granted) and the app (native macOS notification): see lib/alertText.ts.
 */
export function notifyHits(hits: AlertHit[]): void {
  const n = alertNotification(hits)
  if (n) platformNotify(n.title, n.body)
}
