/**
 * GPLN client (wave E, F-11): one read — `GET /api/gameplan?symbol=` on ui-api (same-origin, like vol/api.ts).
 * The server assembles everything from existing stores; the page never calls a publisher or data-service itself.
 */
import axios from 'axios'
import type { GamePlanPayload } from './model'

const client = axios.create({ baseURL: '', timeout: 30_000 })

export const GAMEPLAN_SYMBOLS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'] as const
export type GamePlanSymbol = (typeof GAMEPLAN_SYMBOLS)[number]

export async function getGamePlan(symbol: GamePlanSymbol): Promise<GamePlanPayload> {
  const r = await client.get<GamePlanPayload>('/api/gameplan', { params: { symbol } })
  return r.data
}
