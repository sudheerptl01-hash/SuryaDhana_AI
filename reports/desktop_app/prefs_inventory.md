# Prefs inventory: every localStorage key in `ui/` (D3, 24 Oct 2026)

**Scope.** `ui/app`, `ui/components`, `ui/context` and `ui/lib` were searched for `localStorage` and `sessionStorage`
(outside `lib/prefs`, `lib/platform` and the check scripts). 19 files mention localStorage, matching the PLAN's list of 19;
18 of them use it. `news/types.ts` only mentions it in a comment, and `ThemeContext` only ever removes the legacy `theme`
key. Every key constant was resolved to its literal string. No app code uses sessionStorage, except D4's
`chunkRecovery.ts` reload guard, which is per-tab by design and is never synced. Re-verified 24 Oct, 15:55 IST.

**Source of truth.** The table is mirrored in `ui/lib/prefs/keys.ts` (`SYNC_KEYS` / `LOCAL_KEYS`). A regression guard in
`ui/lib/__tests__/prefs.check.ts` re-scans the UI sources: any key literal it finds that is in neither list fails the check.
A new key stays **local** until someone classifies it, which is the safe default.

**SYNC** means the key is stored on ui-api (`/api/prefs`, SQLite `data/ui_prefs.sqlite`) and shared by the browser, the
desktop app and every window, with last-write-wins per key. **LOCAL** means the key stays in that browser or app instance
only.

## SYNC (12 keys): user settings and data

| Key | Defined in (constant) | Also written / read by | Value | Why SYNC |
|---|---|---|---|---|
| `suryadhana.watchlist` | `context/AppContext.tsx` (`WATCHLIST_KEY`) | read on mount, written on every change | `string[]` JSON | The owner's watchlist. Losing it between the browser and the app is the core problem this solves |
| `newsTerminal.pins.v1` | `lib/pins.ts` (`PIN_KEY`) | `usePins` everywhere: charts, News Terminal, WATCH. It listens to `suryadhana:pins` and `storage` | `{yahoo: PinnedPick}` JSON | The pin list is user data |
| `suryadhana.cmd.recent.v1` | `components/CommandBar.tsx` (`RECENT_KEY`) | GO bar | `string[]` (≤ 8) | "Recents", explicitly in scope |
| `suryadhana.cmd.history.v1` | `components/CommandBar.tsx` (`HISTORY_KEY`) | GO bar | `string[]` | Command history follows the user, like recents |
| `suryadhana.ticket.v1` | `components/TradeTicket.tsx` (`KEY`) | trade ticket | `{amount, mult, capital}` | Saved ticket sizing is a user setting |
| `suryadhana.comp.v1` | `components/Compare.tsx` (`COMP_KEY`) | written by CommandBar, FundamentalsScreen and WatchMonitor ("COMPARE HELD"); read by Compare (on mount and on `suryadhana:comp`) | `{syms, period}` | The compare set. It is also a hand-off channel, but the value persists because the reader never deletes it, so it acts as a page preference |
| `suryadhana.omon.v1` | `components/OptionChain.tsx` (`OMON_KEY`) | written by CommandBar and StockProfile; read by OptionChain (on mount and on `suryadhana:omon`) | symbol | The option chain's underlying is a page preference. The reader keeps the value |
| `suryadhana.rsch.sel.v1` | `components/ResearchLibrary.tsx` (`SEL_KEY`) | `lib/navigate.ts` (`goToPage(…, {research})`) | study id | The selected study is a page preference |
| `suryadhana.fund.filters.v1` | `components/FundamentalsScreen.tsx` (`SAVED`) | screen | `{preset, f}` | Saved screen filters are a page preference |
| `suryadhana.fund.hideflagged` | `components/FundamentalsScreen.tsx` (literal) | screen | `'1'`/`'0'` | A page preference |
| `goldPreOpen.v1` | `components/GoldPreOpen.tsx` (`STORE`) | MCXG pre-open desk | `{day, baseline, mcx, threshold, trigger, done}` | The owner types these pre-open inputs and settings by hand, and they should show in every window. The day-reset logic stays inside the component, unchanged |
| `suryadhana.whatsnew` | `components/Brief.tsx` (literal) | BRIEF banner | version string | The user dismissed the banner explicitly, so they should not see it again in the app |
| `activeSymbol.v1` | `lib/activeSymbolCore.ts` (`ACTIVE_SYMBOL_KEY`) | OMON "OPEN IN OSTR", OSTR symbol picker | `{symbol, expiry, strikes[≤4], at}` | Terminal v2 PLAN 1.3: the last underlying / expiry / strikes picked seeds a new window and OSTR; the per-window copy (`activeSymbol.window.v1`) stays in sessionStorage |

## LOCAL (7 app keys + 6 bookkeeping keys)

| Key | Defined in | Value | Why LOCAL |
|---|---|---|---|
| `suryadhana.deal.symbol` | `components/DealsMonitor.tsx` (`DEAL_KEY`), written by CommandBar | symbol | A one-shot hand-off: it is read and **removed** immediately. Syncing it would create a tombstone on every use and could deliver the hand-off to another window |
| `suryadhana.inbox.seen.v1` | `components/AlertsBell.tsx` (`SEEN_KEY`) | ISO time | This device's unread marker for the inbox badge. It is per-device bookkeeping that advances automatically |
| `suryadhana.alerts.seen.v2` | `lib/alerts.ts` (`SEEN_KEY`) | ISO time | Per device by design: the code says it tracks "hits **this browser** has not shown yet". If it synced, one device showing a notification would suppress it on another. It is also written on every alert check |
| `suryadhana.alerts.v1` | `lib/alerts.ts` (`LEGACY_KEY`) | legacy alert levels | `alerts.ts` already migrates these to `/api/alerts` and then removes the key. Syncing it would re-import the old alerts into every new origin |
| `newsTerminal.seenVersion` | `components/news/NewsDock.tsx` (`SEEN_KEY`) | number | This device's news badge |
| `suryadhana.migrate.notice.v1` | `lib/prefs/migration.ts` (`MIGRATE_NOTICE_KEY`) | `'dismissed'` / `'imported'` | Per origin: the one-time "settings not imported yet" notice is done here. Syncing it would hide the notice on an origin that has not migrated |
| `theme` | `context/ThemeContext.tsx` | n/a | A legacy key that is only ever removed. The terminal is dark-only |
| `suryadhana.prefs.meta` | `lib/prefs/keys.ts` | `{key: updated_at}` | Sync bookkeeping: the server-confirmed timestamp per key |
| `suryadhana.prefs.hash` | `lib/prefs/keys.ts` | `{key: hash}` | Sync bookkeeping: a hash of the server-confirmed value, used to detect transient writes |
| `suryadhana.prefs.dirty` | `lib/prefs/keys.ts` | `{key: updated_at}` | The upload queue. It persists, so it survives reloads and offline periods |
| `suryadhana.prefs.legacy` | `lib/prefs/keys.ts` | `string[]` | The SYNC keys that held a value before sync first ran on this origin. It is snapshotted once, before first render |
| `suryadhana.prefs.backup` | `lib/prefs/keys.ts` | `{key: {value, at}}` | A local copy of any unsynced value that the server's copy replaced. It is kept for recovery and never synced |
| `suryadhana.prefs.mode` | `lib/prefs/keys.ts` | `'readonly'` / `'off'` | The QA and ops switch. `readonly` hydrates but never writes (use it for audits against live). `off` disables sync |

## How sync behaves (summary; the code has the details)

- **Before first render**, `bootstrapPlatform()` runs `hydratePrefs` within a 1.5 s budget, and D4's `PlatformShell` gates
  rendering on it. Hydration does `GET /api/prefs` and then makes a per-key LWW plan (`lib/prefs/merge.ts`):
  - Values the server holds that are newer are written into localStorage with the original Storage methods, so they are
    never re-uploaded.
  - Keys that are newer locally are queued for upload.
  - Never-synced values go up through a **fill-only import**.
  
  If the budget runs out, the app renders from its local values and sync retries in the background, dispatching
  `suryadhana:prefs-changed` when it applies late data.
- **Writes.** `Storage.prototype.setItem/removeItem` is wrapped, but only calls on `window.localStorage` for SYNC keys
  are observed. A real change is queued, debounced (300 ms, at most 2 s), and sent as `PUT` or `DELETE` (a tombstone).
  Failed sends retry with backoff (1 s up to 60 s, with jitter). On `pagehide` or when the page is hidden, the queue is
  flushed with `fetch keepalive`.
- **Focus, visible, online** each trigger a re-read from the server (throttled to once every 3 s). Applied keys dispatch
  `suryadhana:prefs-changed {keys}` and a synthetic `storage` event, so `lib/pins.ts` refreshes the same way it does for
  another tab.
- **Multi-window.** All windows of one origin share localStorage. The window that writes is the one that uploads. The
  sync engine itself never listens to native `storage` events, so windows cannot ping-pong through it. The components
  that cache a SYNC key (AppContext watchlist, pins, TradeTicket, GoldPreOpen, FundamentalsScreen, Brief) adopt other
  windows' writes and the engine's server-applied values through `useExternalPrefChange`
  (`ui/lib/prefs/useExternalChange.ts`), and never write an adopted value back (C3-02, 25 Oct). The navigation hand-off
  keys (`suryadhana.omon.v1`, `suryadhana.comp.v1`, `suryadhana.rsch.sel.v1`) are re-read on every mount but not
  live-adopted, so side-by-side windows keep their own view. If two windows send the same queued write, the server
  treats the identical replay as idempotent.
- **Safety: an empty origin can never wipe the server.** A device that never synced a key cannot overwrite it through
  LWW.
  - **Legacy** values (the snapshot) always go through the legacy import. The server lets a legacy value replace only a
    *provisional* value.
  - Every other never-synced value (a component persisting its default on first mount, such as the watchlist's `[]`)
    either adopts the server copy, or, when the server has no copy, goes up as a **provisional** import that a later
    legacy import still replaces.
  - Whenever the server's copy replaces an unsynced local value, the local value is kept in `suryadhana.prefs.backup`.
- **Server limits.** Keys must match `^[A-Za-z0-9._:-]{1,128}$`. Each value is ≤ 256 KB (UTF-8). Live values total
  ≤ 5 MB, and there are ≤ 500 live keys. Tombstones are pruned after 90 days. Timestamps more than 24 h in the future are
  refused.

## Migration order (PM)

1. The one-time migration runs in **each browser that holds the old data** (the old `:3000` origin), but only once that
   browser runs a build with this code. So the PM needs a `:3000` build with the sync code, loaded once in the owner's
   usual browser.
2. The order is safe either way:
   - If the old browser runs first, its legacy values are imported, and the app hydrates them on its first launch.
   - If the app runs first, its defaults are only provisional, and the old browser's legacy import replaces them.
   - The one case where the old browser's value does **not** win is when the owner deliberately edits a key in the app
     before the old browser has migrated. That is last-write-wins working as designed. The old value is not lost: it
     stays in that browser's `suryadhana.prefs.backup`.
3. QA tools that drive the live `:8010` (T's 42-page audit) should set `localStorage['suryadhana.prefs.mode'] = 'readonly'`
   in an init script. Otherwise their fresh contexts can write to the owner's live preferences, for example through a
   page that persists a selection on mount.
