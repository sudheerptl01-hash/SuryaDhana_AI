/**
 * ASK client (R2-ASK): three same-origin ui-api reads — `/api/ask` (the analyst), `/api/ask/query` (the direct
 * data read that works when the analyst is offline), `/api/ask/health`. The panel never calls data-service or a
 * publisher itself (same shape as gameplan/api.ts).
 */
import axios from 'axios'
import type { AskPayload, ReadPayload } from './model'

const client = axios.create({ baseURL: '', timeout: 90_000 })

export async function askQuestion(question: string): Promise<AskPayload> {
  const r = await client.post<AskPayload>('/api/ask', { question })
  return r.data
}

export async function runRead(sql: string): Promise<ReadPayload> {
  const r = await client.post<ReadPayload>('/api/ask/query', { sql })
  return r.data
}

export type AskHealth = {
  ok: boolean; badge: string; disclosure: string; note: string; provider: string; model: string
  provider_note: string | null; snapshot: { file: string; as_of: string | null } | null
  snapshot_note: string | null; guardrails: string[]
}

export async function askHealth(): Promise<AskHealth> {
  const r = await client.get<AskHealth>('/api/ask/health')
  return r.data
}
