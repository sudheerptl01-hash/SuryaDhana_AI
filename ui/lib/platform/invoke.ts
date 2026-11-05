/**
 * Detection + typed, timeout-bounded `invoke` into the Tauri shell.
 *
 * No npm dependency: the shell's IPC entry point is `window.__TAURI_INTERNALS__.invoke(cmd, args)`
 * (what `@tauri-apps/api/core` itself calls). Only the 9 remote commands of PLAN §5 are typed here;
 * the Rust side re-validates every argument, so nothing here is a security boundary — it is
 * ergonomics + error normalization.
 *
 * SSR-safe: every function checks `typeof window` before touching globals.
 */
import type { ShellCommand, ShellCommands, ShellMarker } from './types'

interface TauriInternals {
  invoke: (cmd: string, args?: Record<string, unknown>, options?: unknown) => Promise<unknown>
}

type ShellWindow = Window & {
  __SURYADHANA_SHELL__?: Partial<ShellMarker>
  __TAURI_INTERNALS__?: Partial<TauriInternals>
}

function shellWindow(): ShellWindow | null {
  return typeof window === 'undefined' ? null : (window as ShellWindow)
}

/** The frozen marker injected by the shell, or null in a browser / during SSR. */
export function shellMarker(): ShellMarker | null {
  const w = shellWindow()
  const m = w?.__SURYADHANA_SHELL__
  if (!m || m.api !== 1) return null
  return m as ShellMarker
}

/**
 * True iff running inside SuryaDhana.app: the contract marker says api 1 AND the Tauri IPC
 * internals exist (PLAN §5 "Detection"). Never throws.
 */
export function isDesktop(): boolean {
  try {
    const w = shellWindow()
    return !!w && w.__SURYADHANA_SHELL__?.api === 1 && typeof w.__TAURI_INTERNALS__?.invoke === 'function'
  } catch {
    return false
  }
}

/** Why a shell call failed. `unavailable` = not running in the desktop shell. */
export type ShellErrorKind = 'unavailable' | 'timeout' | 'rejected'

/** Normalized error for every failed shell call. */
export class ShellError extends Error {
  readonly kind: ShellErrorKind
  readonly command: string
  constructor(kind: ShellErrorKind, command: string, message: string) {
    super(message)
    this.name = 'ShellError'
    this.kind = kind
    this.command = command
  }
}

/** Default per-call timeout. Commands are cheap (cached status, tiny args) except downloads. */
export const DEFAULT_INVOKE_TIMEOUT_MS = 5000

/** Best-effort human message from whatever the Rust command rejected with (string | {message} | other). */
export function rejectionMessage(reason: unknown): string {
  if (typeof reason === 'string' && reason) return reason
  if (reason && typeof reason === 'object') {
    const r = reason as { message?: unknown; error?: unknown }
    if (typeof r.message === 'string' && r.message) return r.message
    if (typeof r.error === 'string' && r.error) return r.error
    try {
      return JSON.stringify(reason).slice(0, 300)
    } catch {
      /* fall through */
    }
  }
  return 'shell command failed'
}

type ArgsOf<C extends ShellCommand> = ShellCommands[C]['args']
type RetOf<C extends ShellCommand> = ShellCommands[C]['ret']

/**
 * Invoke a contract command. Rejects with ShellError (never anything else): `unavailable` in a
 * browser, `timeout` after `timeoutMs`, `rejected` when Rust returned Err (message preserved).
 */
export function invokeShell<C extends ShellCommand>(
  command: C,
  ...rest: ArgsOf<C> extends undefined ? [args?: undefined, timeoutMs?: number] : [args: ArgsOf<C>, timeoutMs?: number]
): Promise<RetOf<C>> {
  const [args, timeoutMs = DEFAULT_INVOKE_TIMEOUT_MS] = rest as [Record<string, unknown> | undefined, number | undefined]
  const w = shellWindow()
  const inv = isDesktop() ? w?.__TAURI_INTERNALS__?.invoke : undefined
  if (!inv) return Promise.reject(new ShellError('unavailable', command, 'not running in the desktop shell'))
  return new Promise<RetOf<C>>((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      reject(new ShellError('timeout', command, `${command} timed out after ${timeoutMs} ms`))
    }, timeoutMs)
    let p: Promise<unknown>
    try {
      p = Promise.resolve(inv.call(w!.__TAURI_INTERNALS__, command, args ?? {}))
    } catch (e) {
      p = Promise.reject(e)
    }
    p.then(
      (v) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolve(v as RetOf<C>)
      },
      (e) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        reject(new ShellError('rejected', command, rejectionMessage(e)))
      },
    )
  })
}
