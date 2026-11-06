/**
 * Every localStorage key the terminal uses, classified SYNC (user settings/data: stored on ui-api
 * and shared by the browser, the desktop app and every window) or LOCAL (per-device bookkeeping,
 * one-shot hand-offs, legacy keys). Inventory with call sites and reasons:
 * reports/desktop_app/prefs_inventory.md. Keep both in sync when a component adds a key — an
 * unlisted key simply stays local (safe default).
 *
 * Pure module (no DOM): imported by the sync engine and by the node check script.
 */

/** Synced keys (exact names). */
export const SYNC_KEYS = [
  'suryadhana.watchlist', //          context/AppContext.tsx — watchlist (string[])
  'newsTerminal.pins.v1', //          lib/pins.ts PIN_KEY — pinned instruments (News Terminal + charts)
  'suryadhana.cmd.recent.v1', //      components/CommandBar.tsx RECENT_KEY — recent tickers
  'suryadhana.cmd.history.v1', //     components/CommandBar.tsx HISTORY_KEY — GO bar command history
  'suryadhana.ticket.v1', //          components/TradeTicket.tsx KEY — saved ticket sizing
  'suryadhana.comp.v1', //            components/Compare.tsx COMP_KEY — compare set + period
  'suryadhana.omon.v1', //            components/OptionChain.tsx OMON_KEY — option-chain underlying
  'suryadhana.rsch.sel.v1', //        components/ResearchLibrary.tsx SEL_KEY — selected study
  'suryadhana.fund.filters.v1', //    components/FundamentalsScreen.tsx SAVED — screen preset + filters
  'suryadhana.fund.hideflagged', //   components/FundamentalsScreen.tsx — hide flagged toggle
  'goldPreOpen.v1', //                components/gold/GoldPreOpen.tsx STORE — pre-open inputs + settings
  'gold.contract.v1', //              lib/gold/prefs.ts CONTRACT_KEY — GOLD/MCXG contract picker {exchange, family, expiry, options}
  'gold.layer.v1', //                 lib/gold/prefs.ts LAYER_KEY — GOLD page [B]/[P] micro-copy layer
  'gold.triggers.v1', //              lib/gold/prefs.ts TRIGGERS_KEY — pre-open desk EUR/USD trigger (moved out of goldPreOpen.v1)
  'suryadhana.whatsnew', //           components/Brief.tsx — dismissed "what's new" version
  'activeSymbol.v1', //               lib/activeSymbol.ts ACTIVE_SYMBOL_KEY — last underlying / expiry / strikes picked (terminal v2 1.3; the per-window copy is sessionStorage)
  'strip.order.v1', //                components/shell/stripOrder.ts STRIP_ORDER_KEY — the owner's page-strip order (page review M37)
] as const

export type SyncKey = (typeof SYNC_KEYS)[number]

/** Keys that deliberately stay in this browser/app only. */
export const LOCAL_KEYS = [
  'suryadhana.deal.symbol', //        components/DealsMonitor.tsx DEAL_KEY — one-shot hand-off, read + removed at once
  'suryadhana.inbox.seen.v1', //      components/AlertsBell.tsx SEEN_KEY — this device's unread marker
  'suryadhana.alerts.seen.v2', //     lib/alerts.ts SEEN_KEY — "hits this browser has shown" (per-device by design)
  'suryadhana.alerts.v1', //          lib/alerts.ts LEGACY_KEY — legacy alerts, migrated to /api/alerts then removed
  'newsTerminal.seenVersion', //      components/news/NewsDock.tsx SEEN_KEY — this device's news badge
  'theme', //                         context/ThemeContext.tsx — legacy key, only ever removed
  'suryadhana.prefs.meta', //         sync bookkeeping: {key: server-confirmed updated_at}
  'suryadhana.prefs.hash', //         sync bookkeeping: {key: hash of the server-confirmed value}
  'suryadhana.prefs.dirty', //        sync bookkeeping: {key: updated_at to upload}
  'suryadhana.prefs.legacy', //       sync bookkeeping: SYNC keys present before sync first ran on this origin
  'suryadhana.prefs.backup', //       local copies of unsynced values the server's copy replaced (recovery)
  'suryadhana.prefs.mode', //         'off' | 'readonly' (QA audits against live) | absent = sync
  'suryadhana.migrate.notice.v1', //  prefs/migration.ts — 'dismissed' | 'imported': the not-imported notice is done here
  'suryadhana.debug.errors', //       components/ErrorCatcher.tsx DEBUG_ERRORS_KEY — '1' = developer error overlay on this device
  'suryadhana.ostr.template.v1', //   lib/goAliases.ts OSTR_TEMPLATE_KEY — one-shot GO hand-off (`NIFTY OSTR IC`), read + removed by OSTR
  'suryadhana.alrt.prefill.v1', //    lib/goAliases.ts ALRT_PREFILL_KEY — one-shot GO hand-off (`ALRT TCS >3200`), read + removed by ALRT
  'suryadhana.migrate.offer.v1', //   components/shell/SettingsImport.tsx — 'seen': the one-time settings-import toast was shown here
] as const

export const PREFS_META_KEY = 'suryadhana.prefs.meta'
export const PREFS_HASH_KEY = 'suryadhana.prefs.hash'
export const PREFS_DIRTY_KEY = 'suryadhana.prefs.dirty'
export const PREFS_LEGACY_KEY = 'suryadhana.prefs.legacy'
export const PREFS_BACKUP_KEY = 'suryadhana.prefs.backup'
export const PREFS_MODE_KEY = 'suryadhana.prefs.mode'

const SYNC_SET: ReadonlySet<string> = new Set<string>(SYNC_KEYS)
const LOCAL_SET: ReadonlySet<string> = new Set<string>(LOCAL_KEYS)

/** Same rule the server enforces (routers/prefs.py KEY_RE). */
export const SERVER_KEY_RE = /^[A-Za-z0-9._:-]{1,128}$/

export function isSyncKey(key: unknown): key is SyncKey {
  return typeof key === 'string' && SYNC_SET.has(key)
}

export type KeyClass = 'sync' | 'local' | 'unknown'

/** Classification for diagnostics; anything not explicitly SYNC is treated as local. */
export function classifyKey(key: string): KeyClass {
  if (SYNC_SET.has(key)) return 'sync'
  if (LOCAL_SET.has(key)) return 'local'
  return 'unknown'
}
