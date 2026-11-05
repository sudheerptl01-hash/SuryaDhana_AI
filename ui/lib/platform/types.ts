/**
 * Shell <-> UI contract v1 types (reports/desktop_app/PLAN.md §5, FROZEN).
 *
 * Pure type module: no runtime code, safe to import from anywhere (SSR, workers, check scripts).
 * Changes to these shapes go through the PM (they mirror the Rust structs in desktop/).
 */

/** Marker the shell injects at document start into every window (initialization script). */
export interface ShellMarker {
  readonly api: 1
  /** App semver, e.g. "0.1.0". */
  readonly version: string
  /** Git sha7 the app was built from. */
  readonly build: string
  readonly platform: 'macos'
  /** Round 3 (additive): what the shell does beyond v1, e.g. 'notification_feed' (it posts the stack's notification
   *  feed as native banners itself). Absent on older apps. */
  readonly features?: readonly string[]
}

/** Health of one backend service as last seen by the shell's 5 s poller. */
export interface Svc {
  up: boolean
  latency_ms: number | null
}

/** ICICI Breeze session state (never carries the login_url / API key). */
export type IciciState = 'connected' | 'expired' | 'unknown'

/** Cached poller snapshot returned by `shell_status` and pushed in `{type:'status'}` events. */
export interface ShellStatus {
  /** ISO-8601 timestamp of the poll. */
  at: string
  ui_api: Svc
  data_service: Svc
  master_controller: Svc
  icici: IciciState
  /** Release id of the UI build ui-api currently serves (null when unknown / no build). */
  ui_build: string | null
  nifty: { last: number; change_pct: number } | null
}

/**
 * `shell_info` result. PLAN §5 lists `{version, build, autostart, windows, ui_api_url}`;
 * `windows` is the number of open terminal windows (least-surprise reading of the contract,
 * recorded in the D3 report).
 */
export interface ShellInfo {
  version: string
  build: string
  autostart: boolean
  windows: number
  ui_api_url: string
}

/** Notification permission, same vocabulary as the Web Notification API. */
export type NotificationPermissionState = 'granted' | 'denied' | 'default'

/**
 * `detail` of the `suryadhana:shell` CustomEvent dispatched by the shell into the page.
 * `zoom` (contract K3, additive): the window's page zoom after ⌘= / ⌘− / ⌘0 (also restored with the session); the
 * same factor is set before page scripts as `window.__SURYADHANA_ZOOM__` when it is not 1.
 */
export type ShellEvent =
  | { type: 'status'; status: ShellStatus }
  | { type: 'goto'; tab: string }
  | { type: 'command-bar' }
  | { type: 'build-changed'; build: string }
  | { type: 'zoom'; factor: number }

/** Name of the DOM CustomEvent the shell dispatches on `window`. */
export const SHELL_EVENT = 'suryadhana:shell' as const

/** Remote-origin commands (UI -> Rust). Args/returns per PLAN §5. */
export interface ShellCommands {
  shell_info: { args: undefined; ret: ShellInfo }
  shell_status: { args: undefined; ret: ShellStatus }
  shell_notify: { args: { title: string; body: string }; ret: null }
  shell_notification_permission: { args: undefined; ret: NotificationPermissionState }
  shell_request_notification_permission: { args: undefined; ret: NotificationPermissionState }
  shell_save_download: { args: { filename: string; base64: string }; ret: { path: string } }
  shell_open_external: { args: { url: string }; ret: null }
  /** `sym` (contract K4, additive): NSE symbol ^[A-Z0-9&_.-]{1,20}$; the window opens /?tab=<tab>&sym=<SYM>. */
  shell_new_window: { args: { tab?: string; sym?: string }; ret: { label: string } }
  shell_set_title: { args: { title: string }; ret: null }
}

export type ShellCommand = keyof ShellCommands

/** Options for `bootstrapPlatform`. */
export interface BootstrapOptions {
  /** Max time spent hydrating prefs from the server before rendering anyway (default 1500 ms). */
  hydrateTimeoutMs?: number
  /** Skip prefs hydration + write-through (tests / embedded views). Default false. */
  skipPrefs?: boolean
  /** Base URL of the API (default '' = same origin). */
  apiBase?: string
}
