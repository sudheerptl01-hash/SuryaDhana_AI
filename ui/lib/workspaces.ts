/**
 * Saved workspaces (FINAL ROUND R2, Platform: "Launchpad workspaces with linked symbol groups").
 *
 * A workspace is a NAMED LAYOUT the owner saves and recalls: {strip order, active page, active symbol (+ expiry),
 * that page's sub-view}. Saved under the SYNC prefs key `suryadhana.workspaces.v1` (lib/prefs/keys.ts), so the app,
 * every browser and every window share the same list through the existing per-key LWW prefs sync — no new server
 * surface. Max MAX_WORKSPACES (8). GO commands (components/CommandBar.tsx, the GO-bar handler for these):
 *
 *   LAYOUT SAVE <name>   save the current layout under that name (replaces a same-named one)
 *   LAYOUT <name>        load it (strip + symbol + sub first, then the page switch)
 *   LAYOUT LIST          list the saved layouts (Enter on a row loads it)
 *
 * A compact header menu (components/desktop/WorkspaceMenu.tsx) does the same by mouse.
 *
 * A workspace stores ONLY the seven fields of `Workspace` below (`serializeWorkspaces` builds each object field by
 * field): page ids, a symbol, an expiry day, a sub-view token, a strip order and a timestamp. Never credentials,
 * tokens, the paper book, or anything read from an API — the check's allowlist test pins this.
 *
 * The model half (parse / serialize / capture / upsert / parseLayoutCommand) is pure and unit-tested under plain
 * node by ui/lib/__tests__/workspaces.check.ts; the storage half takes Storage-like ports (the activeSymbolCore
 * pattern) and defaults to window.localStorage / sessionStorage.
 */
import { STRIP_ORDER_EVENT, STRIP_ORDER_KEY, parseStripOrder, stripStorageValue } from '../components/shell/stripOrder'
import { SUB_VIEW_EVENT, withSub } from '../components/terminal/source'
import { normalizeSymbol, readActiveSymbol, writeActiveSymbol } from './activeSymbolCore'
import { PAGE_HANDOFF_EVENT } from './goAliases'

export const WORKSPACES_KEY = 'suryadhana.workspaces.v1'
export const WORKSPACES_EVENT = 'suryadhana:workspaces'
export const MAX_WORKSPACES = 8

export interface Workspace {
  /** Normalized name (upper-case, 1–20 chars), the LAYOUT argument. */
  name: string
  /** Page id (app/page.tsx COMMAND_PAGES). */
  page: string
  /** Strip order to restore, or null = the default strip (strip.order.v1 removed). */
  strip: string[] | null
  /** Active underlying (lib/activeSymbolCore) and its expiry, when one was set. */
  symbol: string | null
  expiry: string | null
  /** The page's `?sub=` sub-view token (DERV › VOL, GOLD › COT …), when one was on. */
  sub: string | null
  /** ISO time of the save (display only; the prefs key itself is LWW as a whole). */
  at: string
}

const NAME_RE = /^[A-Z0-9][A-Z0-9 _.\-]{0,19}$/
const PAGE_RE = /^[a-z]{2,20}$/
const SUB_RE = /^[a-z0-9_-]{1,24}$/
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/
/** Words LAYOUT itself uses: never a workspace name. */
const RESERVED = new Set(['LAYOUT', 'SAVE', 'LIST', 'DEL', 'DELETE'])

interface StorageLike { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem(k: string): void }

function local(): StorageLike | null { try { return typeof window !== 'undefined' ? window.localStorage : null } catch { return null } }
function session(): StorageLike | null { try { return typeof window !== 'undefined' ? window.sessionStorage : null } catch { return null } }
function emit(name: string, detail?: unknown): void {
  try { window.dispatchEvent(detail === undefined ? new Event(name) : new CustomEvent(name, { detail })) } catch { /* no DOM */ }
}

/** Trimmed, space-collapsed, upper-cased name, or null (bad shape or a reserved word). */
export function normalizeWorkspaceName(s: unknown): string | null {
  if (typeof s !== 'string') return null
  const t = s.trim().replace(/\s+/g, ' ').toUpperCase()
  return NAME_RE.test(t) && !RESERVED.has(t) ? t : null
}

/** One stored entry → Workspace, or null when malformed (a corrupt value never crashes GO or the menu). */
function parseWorkspace(v: unknown): Workspace | null {
  if (!v || typeof v !== 'object') return null
  const o = v as Partial<Workspace>
  const name = normalizeWorkspaceName(o.name)
  if (!name || typeof o.page !== 'string' || !PAGE_RE.test(o.page)) return null
  const strip = Array.isArray(o.strip)
    ? o.strip.filter((x): x is string => typeof x === 'string' && PAGE_RE.test(x)).slice(0, 20)
    : null
  return {
    name,
    page: o.page,
    strip: strip && strip.length ? strip : null,
    symbol: normalizeSymbol(o.symbol ?? null),
    expiry: typeof o.expiry === 'string' && ISO_DAY.test(o.expiry) ? o.expiry : null,
    sub: typeof o.sub === 'string' && SUB_RE.test(o.sub) ? o.sub : null,
    at: typeof o.at === 'string' && Number.isFinite(Date.parse(o.at)) ? o.at : '1970-01-01T00:00:00.000Z',
  }
}

/** A stored value → the saved workspaces (junk dropped, names deduped newest-first kept, capped). Never throws. */
export function parseWorkspaces(raw: string | null | undefined): Workspace[] {
  if (!raw) return []
  let v: unknown
  try { v = JSON.parse(raw) } catch { return [] }
  const list = Array.isArray(v) ? v : v && typeof v === 'object' && Array.isArray((v as { list?: unknown }).list) ? (v as { list: unknown[] }).list : null
  if (!list) return []
  const out: Workspace[] = []
  for (const item of list) {
    const w = parseWorkspace(item)
    if (!w || out.some(x => x.name === w.name)) continue
    out.push(w)
    if (out.length >= MAX_WORKSPACES) break
  }
  return out
}

/** The stored JSON: built field by field, so nothing beyond the seven Workspace fields can ever be stored. */
export function serializeWorkspaces(list: readonly Workspace[]): string {
  return JSON.stringify({
    v: 1,
    list: list.slice(0, MAX_WORKSPACES).map(w => ({
      name: w.name, page: w.page, strip: w.strip ? [...w.strip] : null,
      symbol: w.symbol, expiry: w.expiry, sub: w.sub, at: w.at,
    })),
  })
}

export interface WorkspaceSnapshot {
  /** Active page id. */
  page: string
  /** Raw strip.order.v1 value (null / default both read as "default"). */
  stripRaw: string | null
  symbol: string | null
  expiry: string | null
  /** Raw `?sub=` token of the current URL, when any. */
  sub: string | null
}

/** A snapshot + a name → the workspace to store, or null (bad name, or a page outside `known`). */
export function captureWorkspace(name: string, snap: WorkspaceSnapshot, known: readonly string[], now: Date = new Date()): Workspace | null {
  const n = normalizeWorkspaceName(name)
  if (!n || !PAGE_RE.test(snap.page) || !known.includes(snap.page)) return null
  const strip = parseStripOrder(snap.stripRaw, known)
  return {
    name: n,
    page: snap.page,
    strip: stripStorageValue(strip) === null ? null : strip,     // the default order stores as null (one rule, stripOrder.ts)
    symbol: normalizeSymbol(snap.symbol ?? null),
    expiry: typeof snap.expiry === 'string' && ISO_DAY.test(snap.expiry) ? snap.expiry : null,
    sub: typeof snap.sub === 'string' && SUB_RE.test(snap.sub) ? snap.sub : null,
    at: now.toISOString(),
  }
}

export type UpsertResult = { ok: true; list: Workspace[]; replaced: boolean } | { ok: false; reason: string }

/** Add or replace by name; refuses a NEW name once MAX_WORKSPACES are saved (replacing never hits the cap). */
export function upsertWorkspace(list: readonly Workspace[], ws: Workspace): UpsertResult {
  const i = list.findIndex(w => w.name === ws.name)
  if (i >= 0) {
    const next = [...list]
    next[i] = ws
    return { ok: true, list: next, replaced: true }
  }
  if (list.length >= MAX_WORKSPACES) {
    return { ok: false, reason: `${MAX_WORKSPACES} layouts saved: reuse a name (LAYOUT SAVE <name>) or remove one in the LAYOUT menu` }
  }
  return { ok: true, list: [...list, ws], replaced: false }
}

/** Remove by exact (normalized) name; unchanged when absent. */
export function removeWorkspace(list: readonly Workspace[], name: string): Workspace[] {
  const n = normalizeWorkspaceName(name)
  return n ? list.filter(w => w.name !== n) : [...list]
}

/** Exact match by normalized name. */
export function findWorkspace(list: readonly Workspace[], name: string): Workspace | null {
  const n = normalizeWorkspaceName(name)
  return (n && list.find(w => w.name === n)) || null
}

/** Matches for a typed name: exact first, then prefix, then substring (GO's ranking). */
export function matchWorkspaces(list: readonly Workspace[], q: string): Workspace[] {
  const n = q.trim().replace(/\s+/g, ' ').toUpperCase()
  if (!n) return [...list]
  const score = (w: Workspace) => (w.name === n ? 3 : w.name.startsWith(n) ? 2 : w.name.includes(n) ? 1 : 0)
  return list.filter(w => score(w) > 0).sort((a, b) => score(b) - score(a))
}

/** One hint line for a workspace row: page code, symbol, sub-view, when it was saved. Pure (codes injected). */
export function describeWorkspace(w: Workspace, codeOf: (id: string) => string): string {
  const parts = [codeOf(w.page) || w.page.toUpperCase()]
  if (w.symbol) parts.push(w.symbol + (w.expiry ? ` ${w.expiry}` : ''))
  if (w.sub) parts.push(`› ${w.sub.toUpperCase()}`)
  if (w.strip) parts.push('own strip')
  const day = w.at.slice(0, 10)
  return `${parts.join(' · ')}${day > '1970-01-01' ? ` · saved ${day}` : ''}`
}

// ── GO: LAYOUT SAVE <name> · LAYOUT <name> · LAYOUT LIST ─────────────────────────────────────────────────────────────

export type LayoutCommand =
  | { kind: 'layoutList' }
  | { kind: 'layoutSave'; name: string }
  | { kind: 'layoutLoad'; name: string }
  | { kind: 'invalid'; reason: string }

const NAME_HELP = 'a name is 1–20 letters, digits, spaces, . _ -'

/** Parse a GO line starting with LAYOUT, or null when it is not a LAYOUT command. */
export function parseLayoutCommand(raw: string): LayoutCommand | null {
  const toks = raw.trim().toUpperCase().split(/\s+/).filter(Boolean)
  if (!toks.length || toks[0] !== 'LAYOUT') return null
  if (toks.length === 1 || (toks.length === 2 && toks[1] === 'LIST')) return { kind: 'layoutList' }
  if (toks[1] === 'SAVE') {
    const name = normalizeWorkspaceName(toks.slice(2).join(' '))
    return name ? { kind: 'layoutSave', name } : { kind: 'invalid', reason: `LAYOUT SAVE <name>: ${NAME_HELP}` }
  }
  const name = normalizeWorkspaceName(toks.slice(1).join(' '))
  return name ? { kind: 'layoutLoad', name } : { kind: 'invalid', reason: `LAYOUT <name> loads a saved layout (${NAME_HELP}); LAYOUT LIST shows them` }
}

// ── storage glue (window by default; ports for the node check) ───────────────────────────────────────────────────────

/** The saved workspaces on this origin (synced through the prefs engine, keys.ts). */
export function readWorkspaces(shared: StorageLike | null = local()): Workspace[] {
  try { return parseWorkspaces(shared?.getItem(WORKSPACES_KEY)) } catch { return [] }
}

/** Store the list (localStorage write-through syncs it) and tell this window's menus. */
export function writeWorkspaces(list: readonly Workspace[], shared: StorageLike | null = local()): void {
  try {
    if (list.length) shared?.setItem(WORKSPACES_KEY, serializeWorkspaces(list))
    else shared?.removeItem(WORKSPACES_KEY)
  } catch { /* storage blocked: this window only */ }
  emit(WORKSPACES_EVENT)
}

/** The current layout as a snapshot: active page + strip raw + active symbol + the URL's `?sub=`. */
export function snapshotCurrent(page: string, shared: StorageLike | null = local(), win: StorageLike | null = session(),
                                search?: string): WorkspaceSnapshot {
  let stripRaw: string | null = null
  try { stripRaw = shared?.getItem(STRIP_ORDER_KEY) ?? null } catch { stripRaw = null }
  const active = readActiveSymbol(win, shared)
  let sub: string | null = null
  try {
    const s = search ?? (typeof window !== 'undefined' ? window.location.search : '')
    sub = new URLSearchParams(s).get('sub')
  } catch { sub = null }
  return { page, stripRaw, symbol: active?.symbol ?? null, expiry: active?.expiry ?? null, sub }
}

export type SaveResult = { ok: true; name: string; replaced: boolean; count: number } | { ok: false; reason: string }

/** GO `LAYOUT SAVE <name>` / the menu's SAVE: snapshot → capture → upsert → store. */
export function saveCurrentWorkspace(name: string, page: string, known: readonly string[],
                                     shared: StorageLike | null = local(), win: StorageLike | null = session(),
                                     now: Date = new Date(), search?: string): SaveResult {
  const ws = captureWorkspace(name, snapshotCurrent(page, shared, win, search), known, now)
  if (!ws) return { ok: false, reason: `LAYOUT SAVE: ${NAME_HELP}` }
  const up = upsertWorkspace(readWorkspaces(shared), ws)
  if (!up.ok) return { ok: false, reason: up.reason }
  writeWorkspaces(up.list, shared)
  return { ok: true, name: ws.name, replaced: up.replaced, count: up.list.length }
}

/**
 * Restore a workspace into this window: strip order (one rule with the editor), active symbol, then the sub-view
 * hand-off (`?sub=` + SUB_VIEW_EVENT + PAGE_HANDOFF_EVENT, exactly the GO alias path, so page.tsx keeps `?sub=` on
 * the switch). Returns the page id for the caller to open (onPage / goToPage), or null when the page is unknown to
 * this release (an old save): nothing is touched then.
 */
export function loadWorkspace(ws: Workspace, known: readonly string[],
                              shared: StorageLike | null = local(), win: StorageLike | null = session()): string | null {
  if (!known.includes(ws.page)) return null
  const stripValue = stripStorageValue(ws.strip ? ws.strip.filter(id => known.includes(id)) : null)
  try {
    if (stripValue === null) shared?.removeItem(STRIP_ORDER_KEY)
    else shared?.setItem(STRIP_ORDER_KEY, stripValue)
  } catch { /* storage blocked: the strip stays */ }
  emit(STRIP_ORDER_EVENT)
  if (ws.symbol) writeActiveSymbol({ symbol: ws.symbol, expiry: ws.expiry }, win, shared)
  try {
    window.history.replaceState(window.history.state, '', withSub(window.location.search, ws.sub) || window.location.pathname)
  } catch { /* history locked / no DOM */ }
  emit(SUB_VIEW_EVENT, ws.sub)
  if (ws.sub) emit(PAGE_HANDOFF_EVENT)
  return ws.page
}
