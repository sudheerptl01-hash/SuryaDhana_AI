/**
 * Open any NSE stock in the stock detail window from anywhere in the app, without passing callbacks down:
 *   openTicker('TCS')
 * The page (app/page.tsx) listens for this event and shows StockDetailModal.
 */
export const OPEN_TICKER_EVENT = 'suryadhana:open-ticker'

/** `focus`: open on the Profile tab ('profile'), scrolled to its financials ('fa') / results history ('ern'), or on
 *  historical prices ('hp') / seasonality ('seag'). */
export type TickerFocus = 'profile' | 'fa' | 'ern' | 'hp' | 'seag'

export function openTicker(symbol: string | null | undefined, focus?: TickerFocus): void {
  const s = String(symbol ?? '').trim().toUpperCase().replace(/\.(NS|BO)$/, '')
  if (s) window.dispatchEvent(new CustomEvent<string>(OPEN_TICKER_EVENT, { detail: focus ? `${s}|${focus}` : s }))
}
