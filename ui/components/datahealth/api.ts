/**
 * `GET /api/data/health` client (reports/terminal_v2/API_CONTRACT.md §5; PLAN 1.4): one row per catalogued dataset with
 * its publisher, expected-by time (IST, trading-day aware), stored as-of, sessions behind and a state
 * fresh | live | amber | red | gap. Pure helpers (`staleCount`, `sortRows`, `rowSentence`, `filterByPage`) live in
 * ./healthModel, unit-tested by ui/components/vol/__tests__/terminal_v2.check.ts.
 */
import axios from 'axios'
import type { DataHealth } from './healthModel'

export * from './healthModel'

const client = axios.create({ baseURL: '', timeout: 20_000 })

export const getDataHealth = (page?: string | null) =>
  client.get<DataHealth>('/api/data/health', { params: { page: page || undefined } })
