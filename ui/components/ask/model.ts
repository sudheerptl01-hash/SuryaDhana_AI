/**
 * ASK pure model (FINAL ROUND R2-ASK; RATING §7 R9-R1) — types + the renderer-side guardrails, dependency-free so
 * `node ui/components/ask/__tests__/ask.check.ts` imports it directly.
 *
 * Guardrail G7 lives here a second time on purpose: the SERVER already withholds an uncited numeric line
 * (services/ui-api/ask_engine.py `cited_lines`), and the renderer refuses one again (`renderableLines`) so a
 * payload from an older server, a cache or a test stub can never put an unsourced number on the page.
 * Guardrail G4's renderer half: everything in `answer`, `rows` and `sql` is rendered as TEXT — the panel has no
 * HTML sink (the check file scans AskPanel.tsx for that).
 */

export type AnswerLine = { text: string; cited: boolean }
export type AskSource = { table: string; as_of: string | null }
export type AskSnapshot = { file: string; as_of: string | null }

export type AskPayload = {
  ok: boolean
  badge: string                     // always "heuristic"
  disclosure: string                // "an LLM wrote this from the cited rows — verify before acting on it"
  note: string                      // "describes, does not predict"
  feeds_nothing: string
  question: string
  refused: boolean
  refusal: string | null
  degraded: boolean
  degraded_reason: string | null
  provider: string
  model: string
  provider_note: string | null
  snapshot: AskSnapshot | null
  sql: string | null
  columns: string[]
  rows: unknown[][]
  truncated: boolean
  sources: AskSource[]
  answer: AnswerLine[]
  withheld: number
}

export type ReadPayload = {
  ok: boolean
  sql: string
  columns: string[]
  rows: unknown[][]
  truncated: boolean
  sources: AskSource[]
  snapshot: AskSnapshot | null
}

/** The exact withheld line the server uses; the renderer emits the same one for its own refusals. */
export const WITHHELD_TEXT = '— withheld: a numeric claim without its source table + as-of'

const CITE_RE_G = /\[([A-Za-z0-9_]+)(?:\s*·[^\]]*)?\]/g
const CITE_RE = /\[[A-Za-z0-9_]+(?:\s*·[^\]]*)?\]/
const NUM_RE = /[\d\p{Nd}]/u  // R2-REDTEAM MINOR-2: Arabic-Indic / fullwidth numerals count too

/**
 * G7, renderer side: a line that carries a number must cite one of the payload's own source tables; otherwise it
 * renders as the withheld line. Lines the server already withheld stay withheld. Returns the lines to paint and
 * how many this pass withheld on top of the server's count.
 */
export function renderableLines(lines: readonly AnswerLine[], sources: readonly AskSource[],
                                ): { lines: AnswerLine[]; withheldHere: number } {
  const known = new Set(sources.map(s => s.table.toLowerCase()))
  const out: AnswerLine[] = []
  let withheldHere = 0
  for (const l of lines) {
    const text = (l.text ?? '').trim()
    if (!text) continue
    if (text === WITHHELD_TEXT) { out.push({ text, cited: false }); continue }
    if (NUM_RE.test(text)) {
      const cites = [...text.matchAll(CITE_RE_G)].map(m => m[1].toLowerCase())
      if (!cites.some(c => known.has(c))) { out.push({ text: WITHHELD_TEXT, cited: false }); withheldHere++; continue }
    }
    out.push({ text, cited: CITE_RE.test(text) })
  }
  return { lines: out, withheldHere }
}

/** One source chip's label: `table · as-of date` (or `· undated` when the table has no date column). */
export function sourceLabel(s: AskSource): string {
  return `${s.table} · ${s.as_of ? `as-of ${s.as_of}` : 'undated'}`
}

/** The status strip under the header: provider, model, snapshot day — each a fact, none a judgement. */
export function statusParts(p: Pick<AskPayload, 'provider' | 'model' | 'snapshot' | 'degraded' | 'degraded_reason'>,
                            ): string[] {
  const parts = [`${p.provider} · ${p.model}`]
  parts.push(p.snapshot ? `snapshot ${p.snapshot.as_of ?? p.snapshot.file}` : 'no snapshot yet')
  if (p.degraded && p.degraded_reason) parts.push(p.degraded_reason)
  return parts
}

/** Cell → text. The grid paints strings only: row content is data, never markup (G4's renderer half). */
export function cellText(v: unknown): string {
  if (v === null || v === undefined) return '—'
  return String(v)
}
