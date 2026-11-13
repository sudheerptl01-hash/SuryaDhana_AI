/**
 * E-DIFF (FINAL ROUND T-22 + F-19b) — pure halves of the alert overlay and the BRF "since your last look" diff.
 *
 * Alert overlay: typed alert rules (and the legacy one-shot price alerts, which /api/alerts/rules?origin=all
 * already serves as rule-shaped rows) that reference a symbol + a level become labelled price lines on that
 * symbol's charts — `price:{SYM}` rules on price charts (CHRT), `iv30:{SYM}` rules on the OMON IV history line.
 * A line is a level, never a recommendation: its wording is the rule's own direction-free op word ("at or
 * over"), and creating one from a chart only PRE-FILLS the existing typed-rule builder (lib/alerts.ts
 * `draftAlert`) — the owner reviews and saves; nothing is auto-created, no new alert kind exists, and nothing
 * here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price (PAPER ONLY).
 *
 * BRF what-changed: the morning one-pager snapshots a few of its figures per visit (browser storage, per-device
 * by design — the whatsnew-strip pattern) and shows "old → new" with the previous look's date, plus new
 * corporate events for the owner's stocks and alert fires since. Facts only, neutral tones, no score.
 *
 * Pure module (type-only imports, no DOM): unit-tested under plain node by
 * ui/components/__tests__/alertOverlay.check.ts and type-checked by `cd ui && npx tsc --noEmit`.
 */
import type { AlertOp, AlertRuleDraft } from './alertsEngine'

// ── storage keys (literals live here, callers import; both classified LOCAL in lib/prefs/keys.ts) ───────────
/** sessionStorage, one-shot: the rule id a chart's alert line was clicked on; ALRT reads + removes it. */
export const ALERT_FOCUS_KEY = 'suryadhana.alerts.focus.v1'
/** per-device local storage: the BRF snapshot of the previous visit (never synced — a look is per device). */
export const BRIEF_LASTLOOK_KEY = 'suryadhana.brief.lastlook.v1'

// ── which rules draw as lines ────────────────────────────────────────────────────────────────────────────────

/** The series kinds a chart can draw as a horizontal level (the y-axis must BE the rule's unit). */
export type AlertLineKind = 'price' | 'iv30'

export type LevelOp = 'above' | 'below' | 'cross_up' | 'cross_down'
export const LEVEL_OPS: readonly LevelOp[] = ['above', 'below', 'cross_up', 'cross_down']

/** The ops' own direction-free words — parity with lib/alertsEngine OP_LABEL is asserted by the node check. */
export const LEVEL_OP_WORD: Readonly<Record<LevelOp, string>> = {
  above: 'at or over', below: 'at or under', cross_up: 'crosses from under', cross_down: 'crosses from over',
}

/** The slice of an AlertRule the overlay needs (both stores' rows carry it). */
export interface OverlayRuleLike {
  id: string
  series: string
  op: string
  value?: number | null
  status: string
  origin?: string
}

export interface AlertLine {
  id: string
  price: number
  /** the rule's own wording ("ALERT · at or over"), never a direction or a recommendation */
  title: string
  op: LevelOp
  /** true = a legacy one-shot price alert — origin 'price', shown merged in ALRT as `one-shot · legacy` */
  legacy: boolean
}

export function normSymbol(s: string | null | undefined): string {
  return String(s ?? '').trim().toUpperCase().replace(/\.NS$/, '')
}

/**
 * Every active / snoozed rule of `kind` on `symbol` with a level op and a finite value, as chart lines,
 * ascending by price. Both stores arrive in one list (origin 'rule' + the legacy origin 'price' rows).
 */
export function alertLinesFor(rules: readonly OverlayRuleLike[], symbol: string, kind: AlertLineKind = 'price'): AlertLine[] {
  const want = `${kind}:${normSymbol(symbol)}`
  const out: AlertLine[] = []
  for (const r of rules) {
    if (r.series !== want) continue
    if (r.status !== 'active' && r.status !== 'snoozed') continue
    if (!LEVEL_OPS.includes(r.op as LevelOp)) continue
    const v = r.value
    if (typeof v !== 'number' || !Number.isFinite(v)) continue
    if (kind === 'price' && v <= 0) continue
    const op = r.op as LevelOp
    const legacy = r.origin === 'price'
    out.push({ id: r.id, price: v, op, legacy, title: `ALERT · ${LEVEL_OP_WORD[op]}${legacy ? ' · one-shot' : ''}` })
  }
  return out.sort((a, b) => a.price - b.price)
}

// ── creating a rule from a chart level ───────────────────────────────────────────────────────────────────────

/** A picked level rounded to the unit's honest step: price → the NSE 0.05 tick, iv30 → 0.1 vol pt. */
export function roundLevel(kind: AlertLineKind, price: number): number {
  if (!Number.isFinite(price)) return NaN
  if (kind === 'iv30') return Math.round(price * 10) / 10
  return Math.round(Math.round(price / 0.05) * 0.05 * 100) / 100
}

/**
 * "Alert at this level" → a typed-rule draft for the existing builder (lib/alerts.ts draftAlert opens ALRT
 * with it filled; the owner saves). The op states the crossing side as a fact of geometry — the level sits
 * over or under the series' last value — in the catalogue's own direction-free words; with no last value it
 * falls back to `above` (at or over). One-shot by default, like a drawn level. Null when the level is unusable.
 */
export function draftAtLevel(kind: AlertLineKind, symbol: string, price: number, lastValue?: number | null): AlertRuleDraft | null {
  const sym = normSymbol(symbol)
  const value = roundLevel(kind, price)
  if (!sym || !Number.isFinite(value) || (kind === 'price' && value <= 0)) return null
  const op: AlertOp = lastValue != null && Number.isFinite(lastValue)
    ? (value >= lastValue ? 'cross_up' : 'cross_down')
    : 'above'
  return { series: `${kind}:${sym}`, op, value, repeat: 'once', channel: 'both' }
}

/** The level whose screen coordinate sits within `tol` px of `y` (closest wins); null when none is near. */
export function nearestLevel(levels: readonly number[], y: number,
                             coordOf: (price: number) => number | null | undefined, tol = 6): number | null {
  let best: number | null = null
  let bestD = tol + 1e-9
  for (const p of levels) {
    const c = coordOf(p)
    if (c == null || !Number.isFinite(c)) continue
    const d = Math.abs(c - y)
    if (d <= tol && d < bestD) { best = p; bestD = d }
  }
  return best
}

// ── BRF "since your last look" (F-19b) ──────────────────────────────────────────────────────────────────────

export interface BriefSnapshot {
  /** IST wall clock 'YYYY-MM-DDTHH:mm:ss' (comparable with the servers' IST stamps) */
  at: string
  /** label → the value as BRF printed it (text compare: old → new is exactly what the owner saw) */
  nums: Record<string, string>
  /** keys of this week's corporate events for the owner's stocks ('SYM·KIND·DATE') */
  events: string[]
}

export interface BriefChangeLine {
  label: string
  /** a number that moved: old text → new text */
  from?: string
  to?: string
  /** a counted fact (new events, alert fires) rendered as one neutral sentence */
  text?: string
}

/** The moment `d` as an IST wall-clock stamp ('2026-11-13T18:42:07'). */
export function istStamp(d: Date): string {
  return d.toLocaleString('sv-SE', { timeZone: 'Asia/Kolkata' }).replace(' ', 'T')
}

/** '2026-11-12T18:42:07' → '12 Nov 18:42' (the strip's "since" label). */
export function sinceLabel(at: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/.exec(String(at ?? ''))
  if (!m) return String(at ?? '')
  const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  return `${Number(m[3])} ${MON[Number(m[2]) - 1] ?? m[2]} ${m[4]}:${m[5]}`
}

/** A stored snapshot → the shape, or null (a corrupt value never breaks BRF). */
export function parseBriefSnapshot(raw: string | null | undefined): BriefSnapshot | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw) as Partial<BriefSnapshot> | null
    if (!o || typeof o.at !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(o.at)) return null
    const nums: Record<string, string> = {}
    if (o.nums && typeof o.nums === 'object') {
      for (const [k, v] of Object.entries(o.nums)) if (typeof v === 'string') nums[k.slice(0, 40)] = v.slice(0, 60)
    }
    const events = Array.isArray(o.events) ? o.events.filter((e): e is string => typeof e === 'string').slice(0, 400) : []
    return { at: o.at.slice(0, 19), nums, events }
  } catch {
    return null
  }
}

/**
 * What changed since the previous look: numbers that moved (old → new, text compare), new events for the
 * owner's stocks, and alert fires after the previous look. Facts only — no tone, no direction, no score.
 * Empty when there was no previous look or nothing changed.
 */
export function briefChanges(prev: BriefSnapshot | null, cur: BriefSnapshot, fireTimes: readonly string[] = []): BriefChangeLine[] {
  if (!prev || !prev.at || prev.at >= cur.at) return []
  const out: BriefChangeLine[] = []
  for (const [label, now] of Object.entries(cur.nums)) {
    const old = prev.nums[label]
    if (old != null && old !== now) out.push({ label, from: old, to: now })
  }
  const known = new Set(prev.events)
  const fresh = cur.events.filter(e => !known.has(e))
  if (fresh.length) {
    const names = [...new Set(fresh.map(e => e.split('·')[0]).filter(Boolean))]
    const shown = names.slice(0, 3).join(', ')
    out.push({ label: 'events', text: `${fresh.length} new event${fresh.length > 1 ? 's' : ''} for your stocks${shown ? ` (${shown}${names.length > 3 ? ', …' : ''})` : ''}` })
  }
  const fires = fireTimes.filter(t => typeof t === 'string' && t > prev.at).length
  if (fires) out.push({ label: 'alerts', text: `${fires} alert fire${fires > 1 ? 's' : ''}` })
  return out
}
