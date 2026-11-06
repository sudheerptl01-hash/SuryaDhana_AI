/**
 * Black-76 option maths on the forward, with the same assumptions OMON's implied vols use (the put–call-parity
 * forward, r = 6.5 %, no separate dividend term: the forward already carries it). Greeks are per unit of the
 * underlying: delta ≈ ∂price/∂spot, gamma per point, theta per calendar day, vega per 1 volatility point.
 *
 * Time (M04, review 5 Nov 2026): T is the app's one convention — calendar time to 15:30 IST on the expiry day ÷ 365
 * (`T_DAYS_IN_YEAR`), i.e. the option chain's `t_days` ÷ 365: whole days at end of day, fractional intraday, no half-day.
 * The IV store, the OMON chain and its Greeks, and OSTR all pass that T, so one expiry has one ATM IV everywhere.
 */
export const T_DAYS_IN_YEAR = 365
/** years from the chain's `t_days` (calendar days to 15:30 IST on expiry) */
export const tYears = (tDays: number | null | undefined) => Math.max(0, tDays ?? 0) / T_DAYS_IN_YEAR

/** standard normal CDF (erf via Abramowitz–Stegun 7.1.26 refined; |error| < 1.5e-7) */
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2)
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(x * x) / 2)
  return x >= 0 ? (1 + y) / 2 : (1 - y) / 2
}
export const normPdf = (x: number) => Math.exp(-x * x / 2) / Math.sqrt(2 * Math.PI)

export interface B76 { price: number; delta: number; gamma: number; thetaDay: number; vega: number; probItm: number }

/** `side` call/put · F forward · K strike · T years · sigma decimal (0.15) · r decimal */
export function black76(side: 'call' | 'put', F: number, K: number, T: number, sigma: number, r = 0.065): B76 {
  const df = Math.exp(-r * T)
  if (T <= 0 || sigma <= 0) {                                     // at expiry: intrinsic only
    const intrinsic = side === 'call' ? Math.max(F - K, 0) : Math.max(K - F, 0)
    return { price: intrinsic, delta: side === 'call' ? (F > K ? 1 : 0) : (F < K ? -1 : 0), gamma: 0, thetaDay: 0, vega: 0,
             probItm: side === 'call' ? (F > K ? 1 : 0) : (F < K ? 1 : 0) }
  }
  const sT = sigma * Math.sqrt(T)
  const d1 = (Math.log(F / K) + sigma * sigma * T / 2) / sT, d2 = d1 - sT
  const price = side === 'call' ? df * (F * normCdf(d1) - K * normCdf(d2)) : df * (K * normCdf(-d2) - F * normCdf(-d1))
  const delta = side === 'call' ? normCdf(d1) : normCdf(d1) - 1
  const gamma = normPdf(d1) / (F * sT)
  const vega = F * df * normPdf(d1) * Math.sqrt(T) / 100
  const theta = -F * df * normPdf(d1) * sigma / (2 * Math.sqrt(T)) + r * price      // per year
  return { price, delta, gamma, thetaDay: theta / 365, vega, probItm: side === 'call' ? normCdf(d2) : normCdf(-d2) }
}
