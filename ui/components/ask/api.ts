/**
 * ASK client (R2-ASK; R3-ASK adds the audit tail): four same-origin ui-api reads — `/api/ask` (the analyst),
 * `/api/ask/query` (the direct data read that works when the analyst is offline), `/api/ask/health`,
 * `/api/ask/audit` (recent questions for the empty state — ts · question · row count · model, never payloads).
 * The panel never calls data-service or a publisher itself (same shape as gameplan/api.ts).
 */
import axios from 'axios'
import type { AskPayload, ReadPayload, SnapshotAge } from './model'

const client = axios.create({ baseURL: '', timeout: 90_000 })

// R4-ASK (F3-design nit): the server's two LLM calls are each allowed ASK_LLM_TIMEOUT_S (150 s in ops) plus the
// 10 s query — a 90 s client would abandon an answer the server finishes. The ask POST alone waits that out.
const ASK_CLIENT_TIMEOUT_MS = 320_000

export async function askQuestion(question: string): Promise<AskPayload> {
  const r = await client.post<AskPayload>('/api/ask', { question }, { timeout: ASK_CLIENT_TIMEOUT_MS })
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
  // R3-ASK: `ok` stays about the reads; the analyst's own availability is this separate pair
  analyst_ready: boolean; analyst_note: string | null
  snapshot_age: SnapshotAge | null
}

export async function askHealth(): Promise<AskHealth> {
  const r = await client.get<AskHealth>('/api/ask/health')
  return r.data
}

/** One recent audit line — never a row payload (G5: ts · question · sql · row count · model · refused only). */
export type AskAuditRow = { ts: string; question: string; sql: string | null; rows_returned: number; model: string
                            refused?: boolean }

export async function askAudit(limit = 8): Promise<AskAuditRow[]> {
  const r = await client.get<{ ok: boolean; rows: AskAuditRow[] }>('/api/ask/audit', { params: { limit } })
  return r.data.rows ?? []
}
