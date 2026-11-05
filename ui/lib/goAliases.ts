/**
 * Bloomberg mnemonics for the GO bar (C1-trader-ux-09 remainder, R-UI-SHELL-07 / CT-09). Pure, no DOM, no imports
 * (unit-tested by `node ui/components/desktop/__tests__/desktop.check.ts`); components/CommandBar.tsx turns the
 * targets into GO items and ranks them, with exact page codes, above every ticker match.
 *
 * Without these, Bloomberg muscle memory landed on unrelated tickers: GP opened GPIL, TOP opened SHOPERSTOP, MOST a
 * ticker called MOST, and BACK the Backtest lab (now that real Back exists).
 */

export type AliasTarget =
  | { kind: 'page'; id: string; sub?: string; view?: string }   // `sub`: a GOLD sub-view handed over through the URL (gold program PLAN a.1);
                                                                // `view`: another page's sub-view (`?sub=`), terminal_v2 PLAN 1.1 / 1.4
  | { kind: 'news' }
  | { kind: 'back' }
  | { kind: 'omon'; sym: string }

/** Single-word mnemonic → what it opens, in rank order. Page ids are app/page.tsx COMMAND_PAGES ids. */
export const GO_ALIASES: Readonly<Record<string, readonly AliasTarget[]>> = Object.freeze({
  GP: [{ kind: 'page', id: 'charts' }],          // graph price
  GIP: [{ kind: 'page', id: 'charts' }],         // graph intraday price
  TOP: [{ kind: 'news' }],                       // top news
  N: [{ kind: 'news' }],
  MOST: [{ kind: 'page', id: 'movers' }],        // most active
  BACK: [{ kind: 'back' }],                      // history back (⌘[ in the app)
  BRIEF: [{ kind: 'page', id: 'brief' }],
  NIFTY: [{ kind: 'omon', sym: 'NIFTY' }, { kind: 'page', id: 'memb' }],
  BANKNIFTY: [{ kind: 'omon', sym: 'BANKNIFTY' }, { kind: 'page', id: 'memb' }],
  FINNIFTY: [{ kind: 'omon', sym: 'FINNIFTY' }],
  // gold program (reports/gold_program/PLAN.md a.1): the spot code and the COMEX root open the GOLD page; the four
  // sub-view mnemonics open it on PHYSICAL / MACRO / LEARN / POSITIONING (CommandBar hands `sub` over in the URL)
  XAU: [{ kind: 'page', id: 'gold' }],
  GC: [{ kind: 'page', id: 'gold' }],
  GPHY: [{ kind: 'page', id: 'gold', sub: 'physical' }],
  GMAC: [{ kind: 'page', id: 'gold', sub: 'macro' }],
  LRN: [{ kind: 'page', id: 'gold', sub: 'learn' }],
  COT: [{ kind: 'page', id: 'gold', sub: 'positioning' }],
  // terminal v2 (reports/terminal_v2/PLAN.md 1.1 / 1.2 / 1.4; O-T14 default: sub-views, no new page): VOL opens
  // DERV on its VOL sub-view, DRVR / IMAP / CONTRIB open MEMB ("Index members & drivers"), DATA opens SYS on DATA
  VOL: [{ kind: 'page', id: 'derivatives', view: 'vol' }],
  DRVR: [{ kind: 'page', id: 'memb' }],
  IMAP: [{ kind: 'page', id: 'memb' }],
  CONTRIB: [{ kind: 'page', id: 'memb' }],
  DATA: [{ kind: 'page', id: 'system', view: 'data' }],
})

/** Targets for a GO query: only a single word that is exactly a mnemonic (case-insensitive). */
export function aliasTargets(query: string): readonly AliasTarget[] {
  const q = query.trim().toUpperCase()
  if (!q || /\s/.test(q)) return []
  return Object.prototype.hasOwnProperty.call(GO_ALIASES, q) ? GO_ALIASES[q] : []
}

/**
 * True when Back stays inside the terminal: the current history entry was pushed by the terminal (app/page.tsx tags
 * every entry it pushes with {sd: 1, pushed: true}), so the entry behind it is a terminal screen too. The first
 * entry of a window (pushed: false) has nothing of ours behind it: Back from there would leave the terminal.
 */
export function canGoBack(state: unknown): boolean {
  if (!state || typeof state !== 'object') return false
  const s = state as { sd?: unknown; pushed?: unknown }
  return s.sd === 1 && s.pushed === true
}

/** Concatenate ranked groups, keeping the first item of each key (an alias and a scored page can be the same item). */
export function mergeRanked<T extends { key: string }>(groups: ReadonlyArray<ReadonlyArray<T>>): T[] {
  const seen = new Set<string>()
  const out: T[] = []
  for (const g of groups) {
    for (const it of g) {
      if (seen.has(it.key)) continue
      seen.add(it.key)
      out.push(it)
    }
  }
  return out
}

/**
 * GO's symbol list as the server sent it, made safe for the ranking code (R-UI-SHELL-04 / P15): rows without a
 * string ticker are dropped, and a missing or non-string company name (`n`) reads ''. One bad row used to throw
 * (`s.n.toUpperCase()` on a null name) inside the items memo and take GO down for the whole window.
 */
export function sanitizeSymbolRows<T extends { t?: unknown; n?: unknown }>(rows: unknown): Array<T & { t: string; n: string }> {
  if (!Array.isArray(rows)) return []
  const out: Array<T & { t: string; n: string }> = []
  for (const r of rows) {
    if (!r || typeof r !== 'object') continue
    const row = r as T
    if (typeof row.t !== 'string' || row.t === '') continue
    out.push({ ...row, t: row.t, n: typeof row.n === 'string' ? row.n : '' })
  }
  return out
}
