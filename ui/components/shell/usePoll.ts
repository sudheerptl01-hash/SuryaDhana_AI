'use client'

/**
 * Header chrome polling (R-UI-SHELL-06 / C-PERF-06). The cadence comes from lib/feedState.ts chromePollMs: the live
 * interval while the market prints and the window is visible, IDLE_POLL_MS otherwise. A window coming back into
 * view polls at once, so a slowed poll never shows an old value for longer than the switch back.
 */
import { useEffect, useRef, useState } from 'react'

/** document.hidden, as state (false outside a browser). */
export function useDocumentHidden(): boolean {
  const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.visibilityState === 'hidden')
  useEffect(() => {
    const on = () => setHidden(document.visibilityState === 'hidden')
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])
  return hidden
}

/**
 * Run `poll` on mount, then every `delayMs` (re-armed when the delay changes, without an extra poll), and at once
 * when the window becomes visible again.
 */
export function usePolling(poll: () => unknown, delayMs: number): void {
  const fn = useRef(poll)
  fn.current = poll
  useEffect(() => { fn.current() }, [])
  useEffect(() => {
    const id = setInterval(() => fn.current(), delayMs)
    return () => clearInterval(id)
  }, [delayMs])
  useEffect(() => {
    const on = () => { if (document.visibilityState === 'visible') fn.current() }
    document.addEventListener('visibilitychange', on)
    return () => document.removeEventListener('visibilitychange', on)
  }, [])
}

/**
 * Run `fn` when the window gains focus (a window that stayed visible behind another app gets no visibilitychange).
 * The caller throttles (P9: the dashboard summary refreshes at most once a minute from focus + visibility + timer).
 */
export function useOnFocus(fn: () => unknown): void {
  const ref = useRef(fn)
  ref.current = fn
  useEffect(() => {
    const on = () => ref.current()
    window.addEventListener('focus', on)
    return () => window.removeEventListener('focus', on)
  }, [])
}
