'use client'

/**
 * Per-page error boundary (C1-trader-ux-01). One bad field in one API response used to replace the whole window
 * with a minified stack trace (the title strip, header, GO bar and navigation went with it). Now a render error
 * stays inside the page that threw:
 *
 *  - variant 'page' (each of the 42 pages, the stock window): a terminal-styled panel "<CODE> FAILED TO RENDER"
 *    with RETRY, a details disclosure (message + stacks, hidden by default) and COPY; the chrome stays mounted;
 *  - variant 'modal' (the stock window): the same panel inside the window's backdrop, with CLOSE (Esc works too);
 *  - variant 'bar' (the page header): a one-line bar with RETRY, so navigation and the GO bar keep working;
 *  - variant 'silent' (GO bar, news dock, watchlist bar): renders nothing, or its `cue` (a one-line RETRY button
 *    for the status line), and retries on the next reset.
 *
 * Reset: on `resetKey` change (app/page.tsx keys every boundary by page, so switching pages retries it), on the
 * reconnected event after an outage, and on any window event in `retryOn` (the GO bar: its own open command and
 * the next key press, R-UI-SHELL-04; `replay` maps that event to one the child handles once it is back, e.g. the
 * GO bar's open command, so one ⌘K or one typed ticker letter is enough). `onFailedChange` tells the page when the boundary fails and recovers (the status line's GO cue).
 * Every caught error is reported once to ui-api (lib/clientErrors.ts, K1); the panel says what became of the
 * report (sent, failed, not sent) instead of always claiming it was logged (R-UI-SHELL-09).
 * A ChunkLoadError (a page chunk the server no longer has after a release swap) gets the same guarded reload
 * as app/global-error.tsx instead of the error panel.
 */
import { Component, type CSSProperties, type ErrorInfo, type ReactNode } from 'react'
import { Z } from '@/lib/z'
import { deliveryText, reportClientError, subscribeClientErrors, type ClientErrorEntry } from '@/lib/clientErrors'
import { RECONNECTED_EVENT, reconnectDelayMs } from '@/lib/reconnect'
import { isChunkLoadError, recoverFromChunkError } from '@/components/desktop/chunkRecovery'

const C = {
  panel: '#0a0d13', border: '#1a2130', borderHi: '#2a3448', text: '#d6dbe4', bright: '#f2f5fa', muted: '#6f7a8e',
  red: '#ff4d5e', amber: '#ffb000', bg: '#05070a', mono: "var(--t-mono, 'JetBrains Mono', Menlo, monospace)",
  display: "var(--t-display, 'Chakra Petch', sans-serif)",
}

export interface TabErrorBoundaryProps {
  /** Page code shown in the fallback (BRF, DESK, …) or a chrome name (HEADER, STOCK WINDOW). */
  name: string
  /** Page id for the report's `tab` field (defaults to the URL's ?tab=). */
  tab?: string
  /** Any change clears a caught error (page id, reload epoch). */
  resetKey?: unknown
  variant?: 'page' | 'modal' | 'bar' | 'silent'
  /** variant 'modal': close the window that crashed. */
  onDismiss?: () => void
  /** variant 'silent': a one-line RETRY cue rendered in place while failed (e.g. 'NEWS' in the status line). */
  cue?: string
  /** Window events that retry a failed boundary (e.g. the GO bar's 'suryadhana:command' and 'keydown'). */
  retryOn?: readonly string[]
  /**
   * For a `retryOn` event that retried the boundary: the event to dispatch on window once the child is mounted again
   * (null: nothing), so the user's attempt is not lost (the GO bar: ⌘K / '/' / a ticker letter → its open command).
   */
  replay?: (e: Event) => Event | null
  /** Called with true when the boundary catches an error and with false when it recovers. */
  onFailedChange?: (failed: boolean) => void
  children: ReactNode
}

interface State {
  error: Error | null
  componentStack: string
  details: boolean
  copied: boolean
  /** ChunkLoadError recovery in progress. */
  chunk: 'reloading' | 'waiting' | null
  /** What reportClientError returned for this error (undefined until componentDidCatch ran). */
  report: ClientErrorEntry | null | undefined
}

const INITIAL: State = { error: null, componentStack: '', details: false, copied: false, chunk: null, report: undefined }

function asError(e: unknown): Error {
  if (e instanceof Error) return e
  try {
    return new Error(typeof e === 'string' ? e : JSON.stringify(e))
  } catch {
    return new Error('unknown error')
  }
}

export class TabErrorBoundary extends Component<TabErrorBoundaryProps, State> {
  state: State = INITIAL
  private alive = false
  private chunkTimer: ReturnType<typeof setTimeout> | null = null
  private offReports: (() => void) | null = null
  /** What `replay` returned for the event that retried this boundary: dispatched once the child is mounted again. */
  private replayPending: Event | null = null
  private replaying = false
  private replayTimer: ReturnType<typeof setTimeout> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null

  static getDerivedStateFromError(error: unknown): Partial<State> {
    const e = asError(error)
    return { error: e, details: false, copied: false, chunk: isChunkLoadError(e) ? 'reloading' : null }
  }

  componentDidMount(): void {
    this.alive = true
    window.addEventListener(RECONNECTED_EVENT, this.onReconnected)
    window.addEventListener('keydown', this.onKey)
    for (const t of this.props.retryOn ?? []) window.addEventListener(t, this.onRetryEvent)
    // the report's delivery settles after the POST: re-render the panel's sentence then
    this.offReports = subscribeClientErrors(() => { if (this.alive && this.state.error && this.state.report) this.forceUpdate() })
  }

  componentWillUnmount(): void {
    this.alive = false
    window.removeEventListener(RECONNECTED_EVENT, this.onReconnected)
    window.removeEventListener('keydown', this.onKey)
    for (const t of this.props.retryOn ?? []) window.removeEventListener(t, this.onRetryEvent)
    this.offReports?.()
    if (this.chunkTimer) clearTimeout(this.chunkTimer)
    if (this.replayTimer) clearTimeout(this.replayTimer)
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
  }

  /** `retryOn`: a failed boundary retries on the user's next attempt (GO: ⌘K / '/' / type-to-GO). */
  private onRetryEvent = (e: Event): void => {
    if (!this.state.error || this.state.chunk || this.replaying) return
    let next: Event | null = null
    try { next = this.props.replay?.(e) ?? null } catch { next = null }
    this.replayPending = next
    this.reset()
  }

  /** variant 'modal': Esc closes the crashed window, as it closes a working one. */
  private onKey = (e: KeyboardEvent): void => {
    if (e.key !== 'Escape' || e.defaultPrevented || !this.state.error || this.props.variant !== 'modal' || !this.props.onDismiss) return
    e.preventDefault()
    this.props.onDismiss()
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    const e = asError(error)
    this.replayPending = null
    this.props.onFailedChange?.(true)
    if (isChunkLoadError(e)) {
      const report = reportClientError(e, { kind: 'chunk', tab: this.props.tab })
      this.setState({ componentStack: info?.componentStack ?? '', report })
      this.recoverChunk()
      return
    }
    const report = reportClientError(e, { kind: 'render', tab: this.props.tab, componentStack: info?.componentStack ?? null })
    this.setState({ componentStack: info?.componentStack ?? '', report })
  }

  componentDidUpdate(prev: TabErrorBoundaryProps, prevState: State): void {
    if (this.state.error && !Object.is(prev.resetKey, this.props.resetKey)) this.reset()
    if (prevState.error && !this.state.error) {
      this.props.onFailedChange?.(false)
      const next = this.replayPending
      this.replayPending = null
      // after the child's effects re-attached its listeners (React flushes them before this timer fires)
      if (next) {
        this.replayTimer = setTimeout(() => {
          this.replayTimer = null
          if (!this.alive || this.state.error) return
          this.replaying = true
          try { window.dispatchEvent(next) } finally { this.replaying = false }
        }, 30)
      }
    }
  }

  private recoverChunk(): void {
    recoverFromChunkError().then((outcome) => {
      if (!this.alive) return
      if (outcome === 'guarded') this.setState({ chunk: null })
      else if (outcome === 'unreachable') {
        this.setState({ chunk: 'waiting' })
        this.chunkTimer = setTimeout(() => this.recoverChunk(), 5000)
      }
    })
  }

  /** After an outage: retry, after the same per-window random delay as the page reloads (R-UI-SHELL-05). */
  private onReconnected = (): void => {
    if (!this.state.error || this.state.chunk || this.reconnectTimer) return
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      if (this.alive && this.state.error && !this.state.chunk) this.reset()
    }, reconnectDelayMs())
  }

  reset = (): void => {
    if (this.chunkTimer) clearTimeout(this.chunkTimer)
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    this.setState(INITIAL)
  }

  private copy = (): void => {
    const e = this.state.error
    if (!e) return
    const text = [`${this.props.name} failed to render`, `${e.name}: ${e.message}`, e.stack ?? '', this.state.componentStack].join('\n')
    const done = () => { if (this.alive) this.setState({ copied: true }) }
    try {
      void navigator.clipboard?.writeText(text).then(done, () => undefined)
    } catch {
      /* clipboard unavailable: the details stay selectable */
    }
  }

  render(): ReactNode {
    const { error, chunk } = this.state
    if (!error) return this.props.children
    const variant = this.props.variant ?? 'page'
    if (variant === 'silent') {
      if (!this.props.cue) return null
      return (
        <button type="button" className="sd-foot-btn" onClick={this.reset} title={`${this.props.name} failed: ${error.message || 'error'} · click to retry`}
          style={{ color: C.amber, borderColor: 'rgba(255,176,0,.45)' }}>◌ {this.props.cue} · RETRY</button>
      )
    }
    if (chunk) {
      return (
        <div role="status" aria-live="polite" style={{ padding: '18px 14px', fontFamily: C.mono, fontSize: 11, letterSpacing: '.14em',
                                                        textTransform: 'uppercase', color: C.muted }}>
          {chunk === 'reloading' ? 'Loading the new terminal build…' : 'Server unreachable · reloading when it is back…'}
        </div>
      )
    }
    const msg = `${error.name && error.name !== 'Error' ? `${error.name}: ` : ''}${error.message || 'unknown error'}`
    if (variant === 'bar') {
      return (
        <div role="alert" style={{ display: 'flex', alignItems: 'center', gap: 12, height: 30, padding: '0 12px', background: '#170609',
                                   borderBottom: `1px solid ${C.red}`, fontFamily: C.mono, fontSize: 11, color: C.text, whiteSpace: 'nowrap',
                                   overflow: 'hidden' }}>
          <span style={{ color: C.red, fontWeight: 700, letterSpacing: '.14em' }}>{this.props.name} FAILED TO RENDER</span>
          <span style={{ color: C.muted, overflow: 'hidden', textOverflow: 'ellipsis' }}>{msg}</span>
          <span style={{ flex: 1 }} />
          <button type="button" onClick={this.reset} style={btn(C.red)}>RETRY</button>
        </div>
      )
    }
    const panel = (
      <section role="alert" aria-label={`${this.props.name} failed to render`} data-sd-error="render"
        style={{ background: C.panel, border: `1px solid ${C.border}`, borderTop: `2px solid ${C.red}`, padding: '12px 14px',
                 fontFamily: C.mono, color: C.text, margin: '4px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{ fontFamily: C.mono, fontSize: 11, fontWeight: 700, color: C.bg, background: C.amber, padding: '2px 7px', letterSpacing: 1 }}>
            {this.props.name}
          </span>
          <span style={{ fontFamily: C.display, fontSize: 13, fontWeight: 700, letterSpacing: '.16em', color: C.red }}>FAILED TO RENDER</span>
          <span style={{ flex: 1 }} />
          <button type="button" onClick={this.reset} style={btn(C.amber)}>↻ RETRY</button>
          {variant === 'modal' && this.props.onDismiss && (
            <button type="button" onClick={this.props.onDismiss} style={btn(C.muted)}>✕ CLOSE</button>
          )}
          <button type="button" onClick={() => this.setState(s => ({ details: !s.details }))} aria-expanded={this.state.details}
            style={btn(C.muted)}>{this.state.details ? 'DETAILS ▴' : 'DETAILS ▾'}</button>
        </div>
        <p style={{ margin: '10px 0 0', fontSize: 12, color: C.text, lineHeight: 1.5 }}>
          This page hit an unexpected error and was stopped. The rest of the terminal keeps working: switch pages, use GO,
          or retry this one. {this.state.report === undefined ? '' : deliveryText(this.state.report)}
        </p>
        <p style={{ margin: '6px 0 0', fontSize: 11, color: C.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
           title={msg}>{msg}</p>
        {this.state.details && (
          <div style={{ marginTop: 10 }}>
            <pre style={{ margin: 0, maxHeight: 240, overflow: 'auto', background: C.bg, border: `1px solid ${C.borderHi}`, padding: 10,
                          fontSize: 10, lineHeight: 1.5, color: '#aab3c2', whiteSpace: 'pre-wrap', wordBreak: 'break-word', userSelect: 'text' }}>
              {msg}{'\n\n'}{error.stack ?? '(no stack)'}{this.state.componentStack ? `\n\ncomponent stack:${this.state.componentStack}` : ''}
            </pre>
            <button type="button" onClick={this.copy} style={{ ...btn(C.muted), marginTop: 6 }}>{this.state.copied ? 'COPIED ✓' : 'COPY DETAILS'}</button>
          </div>
        )}
      </section>
    )
    if (variant !== 'modal') return panel
    return (
      <div role="dialog" aria-modal="true" aria-label={`${this.props.name} failed`} data-sd-stock-window=""
        onClick={e => { if (e.target === e.currentTarget) this.props.onDismiss?.() }}
        style={{ position: 'fixed', inset: 0, top: 'var(--shell-top, 0px)', zIndex: Z.modal, background: 'rgba(5,7,10,.7)',
                 display: 'flex', alignItems: 'flex-start', justifyContent: 'center', paddingTop: '10vh' }}>
        <div style={{ width: 'min(760px, calc(100vw - 32px))' }}>{panel}</div>
      </div>
    )
  }
}

function btn(color: string): CSSProperties {
  return { fontFamily: C.mono, fontSize: 10, fontWeight: 700, letterSpacing: '.12em', color, background: 'transparent',
           border: `1px solid ${color}`, padding: '3px 9px', cursor: 'pointer' }
}
