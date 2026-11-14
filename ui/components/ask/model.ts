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
  /** R5-ASK2: true when the result ran past the server's list threshold — the row grid IS the answer
   *  (one deterministic cited summary line, no prose); optional so an older server payload still renders. */
  list_shaped?: boolean
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

/** The server's standing offline line (ask_engine.OFFLINE_LINE) — shown from health when analyst_ready is false. */
export const OFFLINE_LINE = 'analyst offline — the data reads still work'

/** R3-ASK: health's snapshot-age block — the snapshot vs its own iv_summary_daily (facts, no judgement). */
export type SnapshotAge = { iv_summary_max: string | null; stale: boolean; note: string | null }

/**
 * R3-ASK empty-state examples (F2-design ask). Describe-only by construction: each asks about STORED data,
 * none carries a direction word or a forecast shape, so none trips the server's G3 refusal.
 * R4-ASK (F3-design: "the empty state advertises questions the analyst can't answer"): every pill below
 * produced a cited answer in the live EVAL2 run (r4-ask/EVAL2.md); the two that answered with 0 rows or an
 * uncomposable 200-row dump (last NIFTY close — symbol-form residue; the expiry list) were demoted.
 */
export const EXAMPLE_QUESTIONS: readonly string[] = [
  'Top 5 stocks by delivery percentage at the last stored session',
  'How many sessions of IV history are stored for NIFTY?',
  'What was the stored India VIX close at the last stored session?',
  'Which 5 stocks had the highest stored traded volume at the last stored session?',
]

/**
 * R3-ASK: the snapshot-age line and its tone. `ok` = the snapshot's iv_summary_daily reaches the snapshot's own
 * date. `amber` = the snapshot predates the newest iv_summary_daily session (it was cut before that day's
 * iv_eod), so IV answers describe the PRIOR session. `loud` = the same staleness while the analyst is also
 * offline (F2-design: louder when degraded) — the panel paints it as a bordered amber strip, not an inline note.
 */
export function snapshotAgeLine(snapshot: AskSnapshot | null, age: SnapshotAge | null | undefined,
                                analystReady: boolean): { text: string; tone: 'ok' | 'amber' | 'loud' } {
  if (!snapshot) return { text: 'no snapshot yet', tone: 'amber' }
  const base = `snapshot ${snapshot.as_of ?? snapshot.file}`
  if (age?.stale) {
    const text = `${base} — ${age.note ?? `cut before the ${snapshot.as_of} iv_eod; iv_summary_daily inside it ends ${age.iv_summary_max}`}`
    return { text, tone: analystReady ? 'amber' : 'loud' }
  }
  return { text: base, tone: 'ok' }
}

/**
 * R4-ASK (F3-design nit): the server audits in UTC; this panel lives in an IST-everywhere product, so the time
 * is converted (UTC + 5:30 — IST is a fixed offset, no DST: arithmetic) and LABELLED. A ts without a zone
 * suffix is treated as the UTC the server writes; an unparseable ts falls back to the raw text, unlabelled.
 */
export function auditTimeIST(ts: string): string {
  const raw = (ts ?? '').trim()
  if (!raw) return ''
  const iso = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : `${raw}Z`
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return raw.replace('T', ' ').slice(0, 16)
  const t = new Date(ms + 330 * 60_000)                      // +5:30
  const p = (n: number) => String(n).padStart(2, '0')
  return `${t.getUTCFullYear()}-${p(t.getUTCMonth() + 1)}-${p(t.getUTCDate())} ` +
         `${p(t.getUTCHours())}:${p(t.getUTCMinutes())} IST`
}

/** One audit line for the empty state: question · row count · time (IST-labelled) — never a payload (G5). */
export function auditLineLabel(r: { ts: string; question: string; rows_returned: number }): string {
  return `${r.question} · ${r.rows_returned} row(s) · ${auditTimeIST(r.ts)}`
}

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

/** R5-ASK2: how many rows a list-shaped answer paints in its grid before pointing at the full set. */
export const LIST_PREVIEW_ROWS = 20

/**
 * R5-ASK2: the top rows a list-shaped answer renders openly (the full set stays under THE QUERY details).
 * Pure: at or under the cap the rows pass through with no note; past it the top `cap` rows return with a
 * factual note naming both counts (a count is arithmetic, not a judgement).
 */
export function listPreview(rows: readonly unknown[][], cap: number = LIST_PREVIEW_ROWS,
                            ): { rows: unknown[][]; note: string | null } {
  if (rows.length <= cap) return { rows: [...rows], note: null }
  return { rows: rows.slice(0, cap),
           note: `top ${cap} of ${rows.length} returned rows — the full set is under THE QUERY below` }
}

/** Cell → text. The grid paints strings only: row content is data, never markup (G4's renderer half). */
export function cellText(v: unknown): string {
  if (v === null || v === undefined) return '—'
  return String(v)
}
