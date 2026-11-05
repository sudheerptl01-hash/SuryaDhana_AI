/**
 * wsManager.ts — Institutional-grade WebSocket client for live market data.
 *
 * Architecture:
 *  - Singleton instance `monitorWS` connects to /api/monitor/ws/monitor
 *  - Auto-reconnect with exponential back-off (2s → 32s cap)
 *  - Heartbeat ping every 25s to prevent NAT/firewall keepalive drops
 *  - Per-symbol subscription model: send {"action":"subscribe","symbols":[...]}
 *  - Event emitter pattern: callbacks registered via subscribe() / subscribeAll()
 *  - Dispatches to AppContext.liveQuotes via onQuote callback (injected at init)
 */

// ── Types ─────────────────────────────────────────────────────────────────────

export interface LiveQuote {
  symbol:      string
  ltp?:        number   // last traded price
  open?:       number
  high?:       number
  low?:        number
  close?:      number
  change?:     number
  change_pct?: number
  volume?:     number
  bid?:        number
  ask?:        number
  ts?:         number   // unix timestamp
  raw?:        Record<string, any>
}

type QuoteCallback  = (quote: LiveQuote) => void
type AnyCallback    = (data: Record<string, any>) => void
type StatusCallback = (connected: boolean) => void

interface WsMessage {
  symbol?:  string
  payload?: Record<string, any>
  ts?:      number
  ok?:      boolean
  error?:   string
  subscribed?: string[]
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function normaliseQuote(msg: WsMessage): LiveQuote | null {
  const sym = msg.symbol || (msg.payload as any)?.symbol
  if (!sym) return null

  // ICICI Breeze payload shape varies — try common keys
  const p: Record<string, any> = msg.payload || {}
  const ltp = p.ltp ?? p.last_price ?? p.lastPrice ?? p.last ?? p.price

  return {
    symbol:      sym.toUpperCase(),
    ltp:         ltp !== undefined ? Number(ltp) : undefined,
    open:        p.open  !== undefined ? Number(p.open)  : undefined,
    high:        p.high  !== undefined ? Number(p.high)  : undefined,
    low:         p.low   !== undefined ? Number(p.low)   : undefined,
    close:       p.close !== undefined ? Number(p.close) : undefined,
    change:      p.change     !== undefined ? Number(p.change)     : undefined,
    change_pct:  p.change_pct !== undefined ? Number(p.change_pct) : undefined,
    volume:      p.volume     !== undefined ? Number(p.volume)     : undefined,
    bid:         p.bid !== undefined ? Number(p.bid) : undefined,
    ask:         p.ask !== undefined ? Number(p.ask) : undefined,
    ts:          msg.ts ?? p.timestamp,
    raw:         p,
  }
}

// ── Manager class ─────────────────────────────────────────────────────────────

class MonitorWebSocketManager {
  private ws:               WebSocket | null = null
  private url:              string = ''
  private shouldConnect:    boolean = false

  // Subscription state
  private symbolCallbacks:  Map<string, Set<QuoteCallback>> = new Map()
  private globalCallbacks:  Set<AnyCallback> = new Set()
  private statusCallbacks:  Set<StatusCallback> = new Set()
  private subscribedSymbols: Set<string> = new Set()

  // Reconnect
  private reconnectTimer:  ReturnType<typeof setTimeout> | null = null
  private reconnectDelay:  number = 2000
  private readonly maxDelay: number = 32000

  // Heartbeat
  private heartbeatTimer:  ReturnType<typeof setInterval> | null = null
  private readonly hbInterval: number = 25000

  // ── Public API ──────────────────────────────────────────────────────────────

  /** Connect (or reconnect) to the WebSocket endpoint. Safe to call multiple times. */
  connect(url: string, onStatus?: StatusCallback): void {
    this.url = url
    this.shouldConnect = true
    if (onStatus) this.statusCallbacks.add(onStatus)
    this._open()
  }

  /** Gracefully disconnect and stop reconnecting. */
  disconnect(): void {
    this.shouldConnect = false
    this._stopHeartbeat()
    this._cancelReconnect()
    if (this.ws) {
      try { this.ws.close(1000, 'client disconnect') } catch { /* ignore */ }
      this.ws = null
    }
    this._emitStatus(false)
  }

  /**
   * Reconnect at once, with the backoff reset to 2 s (R-UI-SHELL-10): called when the terminal's LINK DOWN → LINK UP
   * edge says ui-api is back, so the live quotes do not wait out a 16–32 s backoff timer. A no-op while a socket is
   * OPEN or CONNECTING, or after disconnect() (nothing to reconnect).
   */
  reconnectNow(): void {
    if (!this.shouldConnect || !this.url) return
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return
    this._cancelReconnect()
    this.reconnectDelay = 2000
    this._open()
  }

  /** True if the socket is currently OPEN. */
  get isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  /**
   * Subscribe a callback to quotes for a specific symbol.
   * Returns an unsubscribe function.
   */
  subscribe(symbol: string, cb: QuoteCallback): () => void {
    const s = symbol.toUpperCase()
    if (!this.symbolCallbacks.has(s)) this.symbolCallbacks.set(s, new Set())
    this.symbolCallbacks.get(s)!.add(cb)
    return () => {
      this.symbolCallbacks.get(s)?.delete(cb)
    }
  }

  /**
   * Subscribe to all incoming messages (raw WS data).
   * Returns an unsubscribe function.
   */
  subscribeAll(cb: AnyCallback): () => void {
    this.globalCallbacks.add(cb)
    return () => this.globalCallbacks.delete(cb)
  }

  /** Add symbols to the WS subscription filter. Sends updated filter to server. */
  addSymbols(symbols: string[]): void {
    const prev = this.subscribedSymbols.size
    symbols.forEach(s => this.subscribedSymbols.add(s.toUpperCase()))
    if (this.subscribedSymbols.size !== prev) this._sendSubscription()
  }

  /** Remove symbols from the WS subscription filter. */
  removeSymbols(symbols: string[]): void {
    symbols.forEach(s => this.subscribedSymbols.delete(s.toUpperCase()))
    this._sendSubscription()
  }

  /** Replace the entire symbol set. */
  setSymbols(symbols: string[]): void {
    const next = new Set(symbols.map(s => s.toUpperCase()))
    const changed =
      next.size !== this.subscribedSymbols.size ||
      [...next].some(s => !this.subscribedSymbols.has(s))
    this.subscribedSymbols = next
    if (changed) this._sendSubscription()
  }

  // ── Private internals ───────────────────────────────────────────────────────

  private _open(): void {
    if (!this.shouldConnect || !this.url) return
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) return

    this._cancelReconnect()

    try {
      const sock = new WebSocket(this.url)
      this.ws = sock

      sock.onopen = () => {
        this.reconnectDelay = 2000
        this._startHeartbeat()
        this._sendSubscription()
        this._emitStatus(true)
      }

      sock.onmessage = (ev) => this._onMessage(ev)

      sock.onclose = (ev) => {
        // A socket that disconnect() closed and a later connect() replaced reports its close late (the close
        // handshake is async): it must not stop the live socket's heartbeat, mark it down or start a reconnect.
        if (this.ws !== sock) return
        this._stopHeartbeat()
        this._emitStatus(false)
        if (this.shouldConnect && ev.code !== 1000) {
          this._scheduleReconnect()
        }
      }

      sock.onerror = () => {
        // onclose fires after onerror — reconnect handled there
      }
    } catch {
      this._scheduleReconnect()
    }
  }

  private _onMessage(ev: MessageEvent): void {
    let data: WsMessage
    try { data = JSON.parse(ev.data) } catch { return }

    // Dispatch to global callbacks
    this.globalCallbacks.forEach(cb => { try { cb(data as any) } catch { /* ignore */ } })

    // Normalise to LiveQuote and dispatch to per-symbol callbacks
    const quote = normaliseQuote(data)
    if (quote?.symbol) {
      const cbs = this.symbolCallbacks.get(quote.symbol)
      cbs?.forEach(cb => { try { cb(quote) } catch { /* ignore */ } })
    }
  }

  private _sendSubscription(): void {
    if (!this.isConnected) return
    const symbols = [...this.subscribedSymbols]
    try {
      this.ws!.send(JSON.stringify({ action: 'subscribe', symbols }))
    } catch { /* WS closed mid-send */ }
  }

  private _startHeartbeat(): void {
    this._stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      if (this.isConnected) {
        try { this.ws!.send(JSON.stringify({ action: 'ping' })) } catch { /* ignore */ }
      }
    }, this.hbInterval)
  }

  private _stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private _scheduleReconnect(): void {
    this._cancelReconnect()
    this.reconnectTimer = setTimeout(() => {
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay)
      this._open()
    }, this.reconnectDelay)
  }

  private _cancelReconnect(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private _emitStatus(connected: boolean): void {
    this.statusCallbacks.forEach(cb => { try { cb(connected) } catch { /* ignore */ } })
  }
}

// ── Singleton export ───────────────────────────────────────────────────────────
export const monitorWS = new MonitorWebSocketManager()

/** Build the correct ws:// or wss:// URL relative to the current page origin. */
export function buildWsUrl(path: string): string {
  if (typeof window === 'undefined') return `ws://localhost:3000${path}`
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}${path}`
}
