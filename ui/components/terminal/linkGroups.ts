/**
 * Link-group registry for the interactive chart kit (charts/PLAN.md §4): panes registering the same group share
 * one visible logical range and one crosshair — the spike's linking, in one module. Spike finding, enforced here:
 * panes sync ONLY within one trading calendar (an NSE pane and a COMEX pane misalign on logical-range linking),
 * so a member's peers are the members with the SAME group AND the SAME calendar.
 *
 * Pure (no React, no LWC, no imports): unit-tested under plain node by terminal/__tests__/interactive.check.ts.
 * A broadcast never re-enters (receivers whose chart events fire synchronously cannot echo a broadcast back),
 * and components keep their own `applying` guard for asynchronous echoes.
 */

export interface LinkRange { from: number; to: number }

export interface LinkHandlers {
  /** another pane's visible logical range (apply with timeScale().setVisibleLogicalRange) */
  onRange?: (range: LinkRange) => void
  /** another pane's crosshair time; null = cleared (apply with set/clearCrosshairPosition) */
  onCrosshair?: (time: string | number | null) => void
}

interface Member { id: number; group: string; calendar: string; h: LinkHandlers }

const members = new Map<number, Member>()
let seq = 0
let broadcasting = false

export interface LinkRegistration { id: number; unregister: () => void }

/** Join `group` within `calendar`; keep the returned id for broadcasts and call unregister on unmount. */
export function registerLink(group: string, calendar: string, h: LinkHandlers): LinkRegistration {
  const id = ++seq
  members.set(id, { id, group, calendar, h })
  return { id, unregister: () => { members.delete(id) } }
}

function peersOf(fromId: number): Member[] {
  const me = members.get(fromId)
  if (!me) return []
  const out: Member[] = []
  for (const m of members.values()) {
    if (m.id !== fromId && m.group === me.group && m.calendar === me.calendar) out.push(m)
  }
  return out
}

/** Push this pane's visible range to its peers (same group, same calendar). Re-entrant calls are dropped. */
export function broadcastRange(fromId: number, range: LinkRange): void {
  if (broadcasting) return
  broadcasting = true
  try { for (const m of peersOf(fromId)) m.h.onRange?.(range) } finally { broadcasting = false }
}

/** Push this pane's crosshair time (null = cleared) to its peers. Re-entrant calls are dropped. */
export function broadcastCrosshair(fromId: number, time: string | number | null): void {
  if (broadcasting) return
  broadcasting = true
  try { for (const m of peersOf(fromId)) m.h.onCrosshair?.(time) } finally { broadcasting = false }
}

/** How many peers a member currently has (debug + the node check). */
export function linkPeerCount(fromId: number): number {
  return peersOf(fromId).length
}

/** Test helper: forget every member (the node check isolates its cases with this). */
export function _resetLinks(): void {
  members.clear()
}
