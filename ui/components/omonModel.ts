/**
 * OMON presentation model (RUP-01 / CT-02, CT-01).
 *
 * OI walls: the page's OI WALLS stat, the chain highlight and BRF all use the server's walls,
 * `resistance[0]` / `support[0]` = the strikes with the most call / put open interest over ALL strikes of the
 * expiry (data-service option_chain.py `top()`). The chain's `rows` are only a ±6 % (indices) / ±12 % (stocks)
 * window around spot, so the biggest bar in the chart is NOT the wall whenever the wall sits outside that
 * window (NIFTY 24,000 vs an in-window maximum of 23,500 on 23 Oct 2026). `wallMarks` places the server's walls
 * on the plotted strikes: on their bar when the strike is plotted, or as an edge marker ('CALL WALL 24,000 →')
 * when it is outside the window. The in-window maximum is never labelled as a wall.
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */

export type WallSide = 'call' | 'put'

export type WallMark =
  /** the wall strike is plotted: label its bar */
  | { side: WallSide; strike: number; at: 'bar'; index: number }
  /** the wall strike is above / below every plotted strike: edge marker with an arrow */
  | { side: WallSide; strike: number; at: 'right' | 'left' }
  /** inside the plotted range but not one of its strikes (a strike with no open interest in the window): position */
  | { side: WallSide; strike: number; at: 'between'; pos: number }

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

function place(side: WallSide, strike: number, strikes: readonly number[]): WallMark {
  const index = strikes.indexOf(strike)
  if (index >= 0) return { side, strike, at: 'bar', index }
  if (strike > strikes[strikes.length - 1]) return { side, strike, at: 'right' }
  if (strike < strikes[0]) return { side, strike, at: 'left' }
  const hi = strikes.findIndex(k => k > strike)
  const lo = hi - 1
  return { side, strike, at: 'between', pos: lo + (strike - strikes[lo]) / (strikes[hi] - strikes[lo]) }
}

/**
 * The call and put walls placed on the plotted strikes (ascending). `resistance` / `support` are the server's
 * lists (biggest first); an empty or missing list means there is no wall on that side (no open interest).
 */
export function wallMarks(strikes: readonly number[], resistance?: readonly number[] | null, support?: readonly number[] | null): WallMark[] {
  if (!strikes.length) return []
  const out: WallMark[] = []
  const call = resistance?.[0], put = support?.[0]
  if (finite(call)) out.push(place('call', call, strikes))
  if (finite(put)) out.push(place('put', put, strikes))
  return out
}

/** Edge-marker text: the wall is outside the plotted strikes, so say which way and at what strike. */
export function edgeLabel(m: WallMark, fmt: (v: number) => string): string {
  const name = m.side === 'call' ? 'CALL WALL' : 'PUT WALL'
  if (m.at === 'right') return `${name} ${fmt(m.strike)} →`
  if (m.at === 'left') return `← ${name} ${fmt(m.strike)}`
  return name
}

/** Index of the at-the-money strike among the plotted strikes: the server's ATM (the chain table's highlight),
 *  else the first strike at or above the forward; −1 when neither is plotted. */
export function atmIndex(strikes: readonly number[], atm?: number | null, forward?: number | null): number {
  if (finite(atm)) {
    const i = strikes.indexOf(atm)
    if (i >= 0) return i
  }
  return finite(forward) ? strikes.findIndex(k => k >= forward) : -1
}

/** The underlying OMON opens on: the GO hand-off key (`RELIANCE OMON` writes it before the page mounts), else NIFTY. */
export function omonInitialSymbol(stored: string | null | undefined): string {
  const s = typeof stored === 'string' ? stored.trim().toUpperCase() : ''
  return /^[A-Z0-9&-]{1,20}$/.test(s) ? s : 'NIFTY'
}
