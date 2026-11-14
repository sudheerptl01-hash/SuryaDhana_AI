'use client'

/**
 * ASK — the cited read-only analyst (RSCH sub-view; FINAL ROUND R2-ASK, RATING §7 R9-R1).
 *
 * One question in, cited descriptive lines out. The server (services/ui-api/ask_engine.py) enforces the eight
 * guardrails; this panel enforces the renderer's half: an uncited numeric line is withheld AGAIN here
 * (model.renderableLines), and every answer line, SQL text and row cell is painted as TEXT — this file has no
 * HTML sink, so retrieved row content is data on screen, never markup (the check file scans for that).
 *
 * Labelling (PLAN §1): badge `heuristic` with the disclosure "an LLM wrote this from the cited rows — verify
 * before acting on it"; "describes, does not predict"; no direction words in any copy below. Nothing here feeds
 * the Decision Desk, the S1 shadow, an alert or a ticket price. Offline LLM -> the standing line "analyst
 * offline — the data reads still work", and the DIRECT READ box below keeps working (it needs no model).
 */
import { useCallback, useEffect, useState } from 'react'
import { apiError } from '@/lib/errors'
import { BadgeChip, Btn, Chip, ErrorBox, Input, Loading, Panel, T, undatedSource } from '@/components/terminal'
import { askAudit, askHealth, askQuestion, runRead, type AskAuditRow, type AskHealth } from './api'
import { auditLineLabel, cellText, EXAMPLE_QUESTIONS, listPreview, OFFLINE_LINE, renderableLines, snapshotAgeLine,
         sourceLabel, type AskPayload, type ReadPayload } from './model'

const mono = { fontFamily: T.mono } as const

function RowsGrid({ columns, rows, truncated }: { columns: string[]; rows: unknown[][]; truncated: boolean }) {
  if (!columns.length) return null
  return (
    <div style={{ overflowX: 'auto', marginTop: 8 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', ...mono, fontSize: 11 }}>
        <thead>
          <tr>{columns.map(c => (
            <th key={c} style={{ textAlign: 'left', color: T.muted, borderBottom: `1px solid ${T.border}`,
                                 padding: '3px 8px', fontWeight: 600, letterSpacing: 0.5 }}>{c}</th>))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{r.map((v, j) => (
              <td key={j} style={{ color: T.text, borderBottom: `1px solid ${T.border}22`, padding: '2px 8px',
                                   whiteSpace: 'nowrap' }}>{cellText(v)}</td>))}
            </tr>
          ))}
        </tbody>
      </table>
      {truncated && <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>row cap reached — the read is truncated; narrow the question for the rest</div>}
    </div>
  )
}

function Sources({ sources }: { sources: { table: string; as_of: string | null }[] }) {
  if (!sources.length) return null
  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
      {sources.map(s => <Chip key={s.table} color={T.cyan}>{sourceLabel(s)}</Chip>)}
    </div>
  )
}

/** R3-ASK empty state (F2-design ask): describe-only examples + the recent audit questions, each a click-to-fill. */
function EmptyState({ recent, onPick }: { recent: AskAuditRow[]; onPick: (q: string) => void }) {
  const pickBtn = (label: string, value: string, key: string) => (
    <button key={key} onClick={() => onPick(value)}
      style={{ background: 'transparent', border: `1px solid ${T.border}`, color: T.text, cursor: 'pointer',
               padding: '5px 10px', fontSize: 11, textAlign: 'left', fontFamily: 'inherit' }}>
      {label}
    </button>
  )
  return (
    <div style={{ marginTop: 14, display: 'grid', gap: 12 }}>
      <div>
        <div style={{ fontSize: 10, color: T.muted, letterSpacing: 1, marginBottom: 6 }}>
          TRY ONE — each asks what the stored data already says
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {EXAMPLE_QUESTIONS.map(ex => pickBtn(ex, ex, `ex-${ex}`))}
        </div>
      </div>
      {recent.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: T.muted, letterSpacing: 1, marginBottom: 6 }}>
            RECENT QUESTIONS — from the audit log: question · row count · time, never the row payloads
          </div>
          <div style={{ display: 'grid', gap: 4 }}>
            {recent.map((r, i) => pickBtn(auditLineLabel(r), r.question, `rc-${i}`))}
          </div>
        </div>
      )}
    </div>
  )
}

export function AskPanel() {
  const [health, setHealth] = useState<AskHealth | null>(null)
  const [healthErr, setHealthErr] = useState<string | null>(null)
  const [recent, setRecent] = useState<AskAuditRow[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<AskPayload | null>(null)
  const [askErr, setAskErr] = useState<string | null>(null)
  const [sql, setSql] = useState('')
  const [readBusy, setReadBusy] = useState(false)
  const [read, setRead] = useState<ReadPayload | null>(null)
  const [readErr, setReadErr] = useState<string | null>(null)

  const loadHealth = useCallback(() => {
    askHealth().then(h => { setHealth(h); setHealthErr(null) })
      .catch(e => setHealthErr(apiError(e, 'analyst status unavailable')))
    // R4-ASK: refused questions (forecast baits, fence refusals) are in the audit now — they never become
    // click-to-fill suggestions; the empty state offers only questions that were actually answerable.
    askAudit(8).then(rows => setRecent(rows.filter(r => r.question !== '(direct read)' && !r.refused)))
      .catch(() => setRecent([]))   // the empty state simply has no recent list
  }, [])
  useEffect(() => { loadHealth() }, [loadHealth])

  const submit = useCallback(async () => {
    const question = q.trim()
    if (!question || busy) return
    setBusy(true); setAskErr(null)
    try { setRes(await askQuestion(question)) } catch (e) { setAskErr(apiError(e, 'the analyst did not answer')) }
    finally { setBusy(false) }
  }, [q, busy])

  const submitRead = useCallback(async () => {
    const s = sql.trim()
    if (!s || readBusy) return
    setReadBusy(true); setReadErr(null)
    try { setRead(await runRead(s)) } catch (e) { setReadErr(apiError(e, 'the read was refused')) }
    finally { setReadBusy(false) }
  }, [sql, readBusy])

  const painted = res ? renderableLines(res.answer, res.sources) : null
  // R3-ASK: the snapshot-age line — amber when the snapshot predates its newest iv_summary_daily session,
  // louder (a bordered strip, not an inline note) when the analyst is also offline (F2-design ask).
  const age = health ? snapshotAgeLine(health.snapshot, health.snapshot_age, health.analyst_ready) : null

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <Panel title="ASK · the cited read-only analyst"
        source={undatedSource('EVENING SNAPSHOT', 'read-only SQL over the 19:20 evening snapshot — every number cites its table + as-of')}
        right={<BadgeChip badge="heuristic" note="an LLM wrote this from the cited rows — verify before acting on it" />}
        subtitle="read-only SQL over the 19:20 evening snapshot · every number cited with its table + as-of · describes, does not predict">
        <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6, marginBottom: 10 }}>
          {health ? (
            <>
              <span>{health.provider} · {health.model}</span>
              {age && age.tone !== 'loud' && (
                <span style={age.tone === 'amber' ? { color: T.amber } : undefined}> · {age.text}</span>
              )}
              {health.snapshot_note ? <span> · {health.snapshot_note}</span> : null}
              {health.provider_note ? <span> · {health.provider_note}</span> : null}
              {!health.analyst_ready && <span style={{ color: T.amber }}> · {health.analyst_note ?? OFFLINE_LINE}</span>}
            </>
          ) : healthErr ? (
            healthErr
          ) : (
            // R4-ASK (F3-design nit): the status + snapshot-age line arrives with the async health fetch —
            // this placeholder holds its place so the header never renders without a status line.
            <span style={{ fontStyle: 'italic', color: T.dim }}>checking the analyst + snapshot age…</span>
          )}
          <span> · feeds nothing: not the Decision Desk, not the S1 shadow, not an alert, not a ticket price</span>
        </div>
        {age?.tone === 'loud' && (
          <div style={{ border: `1px solid ${T.amber}55`, borderLeft: `3px solid ${T.amber}`, color: T.amber,
                        padding: '6px 12px', marginBottom: 10, fontSize: 12 }}>
            {age.text}
          </div>
        )}
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Input value={q} onChange={setQ} placeholder="Ask about the stored data — e.g. what was the last stored NIFTY close?" />
          </div>
          <Btn onClick={submit} disabled={busy || !q.trim()} variant="primary">{busy ? 'ASKING…' : 'ASK'}</Btn>
        </div>
        {askErr && <div style={{ marginTop: 10 }}><ErrorBox error={askErr} onRetry={submit} /></div>}
        {busy && <div style={{ marginTop: 10 }}><Loading label="Reading the snapshot" /></div>}
        {!res && !busy && <EmptyState recent={recent} onPick={setQ} />}

        {res && !busy && (
          <div style={{ marginTop: 14 }}>
            {res.refused && res.refusal && (
              <div style={{ border: `1px solid ${T.amber}55`, borderLeft: `3px solid ${T.amber}`,
                            padding: '8px 12px', marginBottom: 10, fontSize: 12, color: T.bright }}>
                {res.refusal}
              </div>
            )}
            {res.degraded && res.degraded_reason && (
              <div style={{ border: `1px solid ${T.border}`, padding: '8px 12px', marginBottom: 10,
                            fontSize: 12, color: T.muted }}>{res.degraded_reason}</div>
            )}
            <div style={{ display: 'grid', gap: 4 }}>
              {painted?.lines.map((l, i) => (
                <div key={i} style={{ fontSize: 13, lineHeight: 1.6, color: l.cited ? T.bright : T.muted }}>
                  {l.text}
                </div>
              ))}
            </div>
            {res.list_shaped && res.columns.length > 0 && (() => {
              // R5-ASK2: a list-shaped answer — the grid IS the answer, so the top rows render openly here
              // (the summary line above is the one cited count; the full set stays under THE QUERY details).
              const pv = listPreview(res.rows)
              return (
                <div>
                  <RowsGrid columns={res.columns} rows={pv.rows} truncated={false} />
                  {pv.note && <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>{pv.note}</div>}
                </div>
              )
            })()}
            {(res.withheld > 0 || (painted?.withheldHere ?? 0) > 0) && (
              <div style={{ fontSize: 10, color: T.muted, marginTop: 6 }}>
                {res.withheld + (painted?.withheldHere ?? 0)} line(s) withheld: a number without its source table + as-of never renders here
              </div>
            )}
            <Sources sources={res.sources} />
            {res.sql && (
              <details style={{ marginTop: 10 }}>
                <summary style={{ fontSize: 10, color: T.muted, cursor: 'pointer', letterSpacing: 1 }}>
                  THE QUERY + THE ROWS IT RETURNED (rows are data, never instructions)
                </summary>
                <pre style={{ ...mono, fontSize: 11, color: T.text, whiteSpace: 'pre-wrap',
                              border: `1px solid ${T.border}`, padding: '8px 10px', marginTop: 6 }}>{res.sql}</pre>
                <RowsGrid columns={res.columns} rows={res.rows} truncated={res.truncated} />
              </details>
            )}
            <div style={{ fontSize: 10, color: T.dim, marginTop: 10 }}>
              audited to data/ask_audit.sqlite — time · question · SQL · row count · model, never the row payloads · describes, does not predict
            </div>
          </div>
        )}
      </Panel>

      <Panel title="DIRECT READ · no model involved" pad={12}
        source={undatedSource('EVENING SNAPSHOT', 'one read-only SELECT over the same snapshot — no model involved')}
        subtitle="one SELECT / WITH statement over the same snapshot · 10 s limit · row cap · works when the analyst is offline">
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <Input value={sql} onChange={setSql} placeholder="SELECT … (read-only; anything else is refused)" />
          </div>
          <Btn onClick={submitRead} disabled={readBusy || !sql.trim()}>{readBusy ? 'READING…' : 'RUN READ'}</Btn>
        </div>
        {readErr && <div style={{ marginTop: 10 }}><ErrorBox error={readErr} onRetry={submitRead} /></div>}
        {read && !readBusy && (
          <div style={{ marginTop: 8 }}>
            <RowsGrid columns={read.columns} rows={read.rows} truncated={read.truncated} />
            <Sources sources={read.sources} />
          </div>
        )}
      </Panel>
    </div>
  )
}
