/**
 * The GOLD page's synced preferences (keys listed in ui/lib/prefs/keys.ts SYNC_KEYS, PLAN a.1):
 *   gold.contract.v1  {exchange, family, expiry, options}   the page-global contract picker, shared with MCXG
 *   gold.layer.v1     'B' | 'P'                              beginner / pro micro-copy
 *   gold.triggers.v1  {eurusd}                               the pre-open desk's EUR/USD trigger (was goldPreOpen.v1)
 *
 * The read / write helpers are pure (they take the storage), so the node check exercises them; the hooks wrap them
 * with the multi-window rule of lib/prefs/useExternalChange (re-read on an external write, never echo an adopted
 * value). The URL carries the same selection (`?sub=&c=&exp=&unit=&win=`) so a link reproduces the view.
 */
import { useCallback, useEffect, useState } from 'react'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { GOLD_FAMILIES, GOLD_SUBS, GOLD_UNITS, type Family, type GoldContractSel, type GoldSub, type Layer, type Unit, type Window } from './types'

export const CONTRACT_KEY = 'gold.contract.v1'
export const LAYER_KEY = 'gold.layer.v1'
export const TRIGGERS_KEY = 'gold.triggers.v1'

export const DEFAULT_SEL: GoldContractSel = Object.freeze({ exchange: 'MCX', family: 'GOLD', expiry: null, options: false })
export const DEFAULT_TRIGGERS = Object.freeze({ eurusd: '1.1161' })

interface StorageLike { getItem(k: string): string | null; setItem(k: string, v: string): void }

function storage(): StorageLike | null {
  try { return typeof window !== 'undefined' ? window.localStorage : null } catch { return null }
}

export function isFamily(x: unknown): x is Family {
  return typeof x === 'string' && (GOLD_FAMILIES as readonly string[]).includes(x)
}
export function isUnit(x: unknown): x is Unit {
  return typeof x === 'string' && (GOLD_UNITS as readonly string[]).includes(x)
}
export function isSub(x: unknown): x is GoldSub {
  return typeof x === 'string' && (GOLD_SUBS as readonly string[]).includes(x)
}
export function isWindow(x: unknown): x is Window {
  return x === 'D' || x === 'W' || x === 'M'
}
const ISO_DAY = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/

/** Parse a stored selection; anything malformed falls back field by field to the default. */
export function parseContractSel(raw: string | null | undefined): GoldContractSel {
  if (!raw) return { ...DEFAULT_SEL }
  try {
    const o = JSON.parse(raw) as Partial<GoldContractSel> | null
    if (!o || typeof o !== 'object') return { ...DEFAULT_SEL }
    return {
      exchange: o.exchange === 'NSE' || o.exchange === 'BSE' ? o.exchange : 'MCX',
      family: isFamily(o.family) ? o.family : DEFAULT_SEL.family,
      expiry: typeof o.expiry === 'string' && ISO_DAY.test(o.expiry) ? o.expiry : null,
      options: o.options === true,
    }
  } catch {
    return { ...DEFAULT_SEL }
  }
}

export function readContractSel(area: StorageLike | null = storage()): GoldContractSel {
  try { return parseContractSel(area?.getItem(CONTRACT_KEY)) } catch { return { ...DEFAULT_SEL } }
}

export function writeContractSel(sel: GoldContractSel, area: StorageLike | null = storage()): void {
  try { area?.setItem(CONTRACT_KEY, JSON.stringify(sel)) } catch { /* storage unavailable */ }
}

export function parseLayer(raw: string | null | undefined): Layer {
  return raw === 'P' ? 'P' : 'B'
}
export function readLayer(area: StorageLike | null = storage()): Layer {
  try { return parseLayer(area?.getItem(LAYER_KEY)) } catch { return 'B' }
}
export function writeLayer(layer: Layer, area: StorageLike | null = storage()): void {
  try { area?.setItem(LAYER_KEY, layer) } catch { /* storage unavailable */ }
}

export interface Triggers { eurusd: string }
export function parseTriggers(raw: string | null | undefined): Triggers {
  if (!raw) return { ...DEFAULT_TRIGGERS }
  try {
    const o = JSON.parse(raw) as Partial<Triggers> | null
    return { eurusd: o && typeof o.eurusd === 'string' && o.eurusd.trim() ? o.eurusd : DEFAULT_TRIGGERS.eurusd }
  } catch { return { ...DEFAULT_TRIGGERS } }
}
export function readTriggers(area: StorageLike | null = storage()): Triggers {
  try { return parseTriggers(area?.getItem(TRIGGERS_KEY)) } catch { return { ...DEFAULT_TRIGGERS } }
}
export function writeTriggers(t: Triggers, area: StorageLike | null = storage()): void {
  try { area?.setItem(TRIGGERS_KEY, JSON.stringify(t)) } catch { /* storage unavailable */ }
}

const sameSel = (a: GoldContractSel, b: GoldContractSel) =>
  a.exchange === b.exchange && a.family === b.family && a.expiry === b.expiry && a.options === b.options

/** The shared contract selection: read on mount, adopted from other windows, written on every edit. */
export function useGoldContract(): [GoldContractSel, (patch: Partial<GoldContractSel>) => void] {
  const [sel, setSel] = useState<GoldContractSel>(() => ({ ...DEFAULT_SEL }))
  useEffect(() => { setSel(readContractSel()) }, [])
  useExternalPrefChange(CONTRACT_KEY, () => {
    const next = readContractSel()
    setSel(s => (sameSel(s, next) ? s : next))
  })
  const update = useCallback((patch: Partial<GoldContractSel>) => {
    setSel(s => {
      // merge on write: another window's newer selection is the base, not this window's copy (C3-02)
      const base = readContractSel()
      const n: GoldContractSel = { ...base, ...patch }
      if (patch.family && patch.family !== base.family && patch.expiry === undefined) n.expiry = null   // a new family resets the expiry
      writeContractSel(n)
      return sameSel(s, n) ? s : n
    })
  }, [])
  return [sel, update]
}

/** The [B]/[P] layer, synced. */
export function useGoldLayer(): [Layer, (l: Layer) => void] {
  const [layer, setLayer] = useState<Layer>('B')
  useEffect(() => { setLayer(readLayer()) }, [])
  useExternalPrefChange(LAYER_KEY, () => setLayer(readLayer()))
  const set = useCallback((l: Layer) => { writeLayer(l); setLayer(l) }, [])
  return [layer, set]
}

// ── URL state (`?tab=gold&sub=health&c=GOLDM&exp=2026-12-04&unit=inr10g&win=W`) ─────────────────

export interface GoldUrlState { sub?: GoldSub; family?: Family; expiry?: string | null; unit?: Unit; window?: Window }

const UNIT_PARAM: Record<Unit, string> = { usd_oz: 'usdoz', inr_10g: 'inr10g', inr_g: 'inrg', usd_g: 'usdg', tola: 'tola' }
const PARAM_UNIT: Record<string, Unit> = Object.fromEntries(Object.entries(UNIT_PARAM).map(([u, p]) => [p, u as Unit]))

/** The gold view parameters of a location.search string (unknown values are ignored). */
export function parseGoldUrl(search: string): GoldUrlState {
  let p: URLSearchParams
  try { p = new URLSearchParams(search) } catch { return {} }
  const out: GoldUrlState = {}
  const sub = p.get('sub'); if (isSub(sub)) out.sub = sub
  const c = p.get('c')?.toUpperCase(); if (isFamily(c)) out.family = c
  const exp = p.get('exp'); if (exp && ISO_DAY.test(exp)) out.expiry = exp
  const unit = p.get('unit'); if (unit && PARAM_UNIT[unit]) out.unit = PARAM_UNIT[unit]
  const win = p.get('win'); if (isWindow(win)) out.window = win
  return out
}

/** The search string with the gold parameters applied (others, incl. `tab`, kept). Omitted keys are removed. */
export function buildGoldSearch(current: string, st: GoldUrlState): string {
  let p: URLSearchParams
  try { p = new URLSearchParams(current) } catch { p = new URLSearchParams() }
  const set = (k: string, v: string | null | undefined) => { if (v) p.set(k, v); else p.delete(k) }
  set('sub', st.sub)
  set('c', st.family)
  set('exp', st.expiry ?? null)
  set('unit', st.unit ? UNIT_PARAM[st.unit] : null)
  set('win', st.window)
  return `?${p.toString()}`
}

/** The search string with every gold parameter removed (on leaving the page). */
export function stripGoldSearch(current: string): string {
  return buildGoldSearch(current, {})
}

/** Hand a sub-view to the GOLD page before `goToPage('gold')` (other pages' "GOLD ›" chips). */
export function setGoldSubInUrl(sub: GoldSub): void {
  try {
    window.history.replaceState(window.history.state, '', buildGoldSearch(window.location.search, { ...parseGoldUrl(window.location.search), sub }))
  } catch { /* history locked */ }
}
