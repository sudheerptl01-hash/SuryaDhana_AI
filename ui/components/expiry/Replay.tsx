'use client'

/**
 * XPRY › REPLAY — the expiry replay simulator (FINAL ROUND wave E, E-REPLAY, F-17; PLAN W7).
 *
 * Practice on RECORDED expiry-day tapes (`iv_expiry_replay`, Breeze 1-minute ATM call + put bars backfilled by the
 * PM's after-close job O-T16 — read-only here, via `GET /api/derivatives/replay`): pick a replayed expiry, or RANDOM
 * with the date hidden until the close; the tape steps FORWARD only (no rewind before the close, so a mark is never
 * re-made with hindsight); at any print the user records a practice entry (the straddle, sold or bought, at the
 * printed price) and closes it at a later print or lets it settle at the day's last print.
 *
 * Hard rules (binding):
 *  - PRACTICE entries live in this component + localStorage ONLY — never the paper F&O book (data/paper_fo.sqlite),
 *    never an order, never an alert, never a ticket price. PAPER ONLY stands everywhere anyway; this is one step
 *    further removed: a rehearsal.
 *  - Date-hidden mode leaks nothing until the reveal: the tape rows carry clock times only (routers/expiry.py
 *    re-keys them), and this component shows no expiry date, no strike, no spot and no as-of while hidden — the
 *    session chart falls back to today's date so even the crosshair's day text carries no recorded date.
 *  - Scoring is arithmetic over the stored tape: "your mark vs the actual print" — never a side being right or
 *    wrong, no direction words, no grade, no composite score. A rehearsal on recorded data — describes what
 *    happened, does not predict.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import axios from 'axios'
import { Btn, Chip, DataTable, Notice, Panel, Stat, T, fmtNum, inputSource, type Column, type SourceInfo } from '@/components/terminal'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { tapeError } from './api'
import { CALL_COLOR, ChartWithNotes, PUT_COLOR, SessionChart } from './charts'
import { DESCRIBES, TAPE_INDICES, sentence } from './tapeModel'

// ── payload shapes (routers/expiry.py `shape_replay`) ────────────────────────────────────────────────────

export interface ReplayRow {
  minute: number | null; ist: string | null; straddle: number | null; ce_close: number | null; pe_close: number | null
  ce_oi: number | null; pe_oi: number | null; ce_volume?: number | null; pe_volume?: number | null
}
export interface ReplayExpiry {
  expiry: string; rows: number; first_ist: string | null; last_ist: string | null
  strike: number | null; spot_open: number | null; source: string | null
}
interface ReplayChip { state: string; source: string; as_of: string | null; age_s: number | null; hint: string }
export interface ReplayPayload {
  symbol: string; mode: 'list' | 'tape'; badges: Record<string, string>; note: string; practice: string
  ok: boolean; store_errors?: Record<string, string>; chip?: ReplayChip; n: number
  expiries?: ReplayExpiry[]; empty_note?: string | null
  expiry?: string; strike?: number | null; spot_open?: number | null; source?: string | null; rows?: ReplayRow[]
}

const client = axios.create({ baseURL: '', timeout: 20_000 })
const getReplay = (symbol: string, expiry?: string) =>
  client.get<ReplayPayload>('/api/derivatives/replay', { params: { symbol, expiry } })

// ── practice marks: pure, exported (arithmetic over the stored tape; no judgement words) ────────────────

export type Side = 'sold' | 'bought'
export interface Mark {
  id: number; minute: number; ist: string; side: Side; price: number
  exit_minute?: number; exit_ist?: string; exit_price?: number; exit_kind?: 'closed' | 'last print'
}

/** Signed change ON YOUR MARK (₹ per unit): sold → entry − exit, bought → exit − entry; null while open. */
export function markChange(m: Mark): number | null {
  if (m.exit_price == null) return null
  const d = m.exit_price - m.price
  return m.side === 'bought' ? d : -d
}

/** Minutes between the mark and its close-out print; null while open. */
export function heldMin(m: Mark): number | null {
  return m.exit_minute == null ? null : Math.max(0, m.exit_minute - m.minute)
}

/** The day's last straddle print (a null row is a gap, never filled). */
export function lastPrint(rows: readonly ReplayRow[]): ReplayRow | null {
  for (let k = rows.length - 1; k >= 0; k--) if (rows[k].straddle != null) return rows[k]
  return null
}

/** Open marks settle at the day's last print (exit_kind 'last print'); closed marks pass through untouched. */
export function settleAtClose(marks: readonly Mark[], rows: readonly ReplayRow[]): Mark[] {
  const last = lastPrint(rows)
  if (!last || last.straddle == null) return [...marks]
  return marks.map(m => m.exit_price != null ? m
    : { ...m, exit_minute: last.minute ?? m.minute, exit_ist: last.ist ?? m.ist, exit_price: last.straddle as number, exit_kind: 'last print' as const })
}

/** Net ₹ per unit over all settled marks; null when none settled. */
export function netOf(marks: readonly Mark[]): number | null {
  const cs = marks.map(markChange).filter((v): v is number => v != null)
  return cs.length ? cs.reduce((a, b) => a + b, 0) : null
}

/** The straddle prints between the mark and the close (inclusive): what the tape actually did after your mark. */
export function printedAfter(rows: readonly ReplayRow[], fromMinute: number): { lo: number; hi: number } | null {
  const vals = rows.filter(r => r.minute != null && r.minute >= fromMinute && r.straddle != null).map(r => r.straddle as number)
  return vals.length ? { lo: Math.min(...vals), hi: Math.max(...vals) } : null
}

export const fmtInrSigned = (v: number | null | undefined): string =>
  v == null || !Number.isFinite(v) ? '—' : `${v >= 0 ? '+' : '−'}₹${Math.abs(v).toFixed(2)}`

// ── past rehearsals (localStorage only; every access guarded — storage may be absent or throw) ───────────

const LS_KEY = 'suryadhana.replay.practice.v1'
const LS_CAP = 50
export interface SavedRun { at: string; symbol: string; expiry: string; hidden: boolean; marks: number; net: number | null }

function loadRuns(): SavedRun[] {
  try {
    const raw = window.localStorage.getItem(LS_KEY)
    const v = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(v) ? (v as SavedRun[]).slice(0, LS_CAP) : []
  } catch { return [] }
}

function saveRun(run: SavedRun): SavedRun[] {
  const next = [run, ...loadRuns()].slice(0, LS_CAP)
  try { window.localStorage.setItem(LS_KEY, JSON.stringify(next)) } catch { /* per-browser convenience only */ }
  return next
}

// ── the page ─────────────────────────────────────────────────────────────────────────────────────────────

const SPEEDS = [{ label: '×1', ms: 600 }, { label: '×3', ms: 200 }, { label: '×10', ms: 60 }] as const
const PRACTICE_LINE = 'Practice entries stay in this browser — never the paper F&O book, never an order.'
const noteStyle = { fontSize: 10, color: T.dim, marginTop: 4 } as const

export function Replay({ symbol: symbolProp }: { symbol?: string }) {
  const [symbol, setSymbol] = useState((symbolProp ?? 'NIFTY').toUpperCase())
  useEffect(() => { if (symbolProp) setSymbol(symbolProp.toUpperCase()) }, [symbolProp])
  const [phase, setPhase] = useState<'pick' | 'run' | 'done'>('pick')
  const [list, setList] = useState<ReplayPayload | null>(null)
  const [listErr, setListErr] = useState<string | null>(null)
  const [tape, setTape] = useState<ReplayPayload | null>(null)
  const [tapeErr, setTapeErr] = useState<string | null>(null)
  const [hidden, setHidden] = useState(false)
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speedIdx, setSpeedIdx] = useState(1)
  const [marks, setMarks] = useState<Mark[]>([])
  const [runs, setRuns] = useState<SavedRun[]>([])
  useEffect(() => { setRuns(loadRuns()) }, [])

  useEffect(() => {                                       // a symbol change always lands back on the picker
    let alive = true
    setPhase('pick'); setTape(null); setTapeErr(null); setMarks([]); setPlaying(false)
    setList(null); setListErr(null)
    getReplay(symbol).then(r => { if (alive) setList(r.data) })
      .catch((e: unknown) => { if (alive) setListErr(tapeError(e)) })
    return () => { alive = false }
  }, [symbol])

  const rows = useMemo(() => (tape?.rows ?? []).filter(r => r.minute != null && r.ist != null), [tape])
  const n = rows.length
  const cur = n ? rows[Math.min(i, n - 1)] : null
  const showDate = !hidden || phase === 'done'

  const finishedRef = useRef(false)
  const start = useCallback((expiry: string, hide: boolean) => {
    finishedRef.current = false
    setPhase('run'); setHidden(hide); setI(0); setMarks([]); setPlaying(false); setTape(null); setTapeErr(null)
    getReplay(symbol, expiry).then(r => setTape(r.data)).catch((e: unknown) => { setTapeErr(tapeError(e)); setPhase('pick') })
  }, [symbol])

  const finish = useCallback(() => {
    if (finishedRef.current || phase !== 'run') return
    finishedRef.current = true
    setPlaying(false)
    const settled = settleAtClose(marks, rows)
    setMarks(settled)
    setI(Math.max(0, n - 1))
    setPhase('done')
    if (tape?.expiry) setRuns(saveRun({ at: new Date().toISOString(), symbol, expiry: tape.expiry, hidden, marks: settled.length, net: netOf(settled) }))
  }, [phase, marks, rows, tape?.expiry, symbol, hidden, n])

  useEffect(() => {                                       // playback: forward only
    if (phase !== 'run' || !playing || n === 0) return
    const iv = setInterval(() => setI(prev => Math.min(prev + 1, n - 1)), SPEEDS[speedIdx].ms)
    return () => clearInterval(iv)
  }, [phase, playing, speedIdx, n])
  useEffect(() => { if (phase === 'run' && n > 0 && i >= n - 1) finish() }, [i, n, phase, finish])

  const record = (side: Side) => {
    if (phase !== 'run' || !cur || cur.straddle == null) return
    setMarks(ms => [...ms, { id: Date.now() + ms.length, minute: cur.minute as number, ist: cur.ist as string, side, price: cur.straddle as number }])
  }
  const closeMark = (id: number) => {
    if (phase !== 'run' || !cur || cur.straddle == null) return
    setMarks(ms => ms.map(m => m.id === id && m.exit_price == null
      ? { ...m, exit_minute: cur.minute as number, exit_ist: cur.ist as string, exit_price: cur.straddle as number, exit_kind: 'closed' as const } : m))
  }

  const chartSrc: SourceInfo = {
    state: 'reference', source: 'BREEZE 1-MIN REPLAY', asOf: showDate ? tape?.expiry ?? null : null, ageDays: null,
    hint: showDate ? (tape?.chip?.hint ?? 'one recorded expiry day') : 'a recorded expiry day — date hidden until the close',
  }
  const visible = phase === 'done' ? rows : rows.slice(0, Math.min(i + 1, n))
  const x = visible.map(r => r.minute as number)
  const dayFirst = rows.find(r => r.straddle != null) ?? null
  const dayLast = phase === 'done' ? lastPrint(rows) : null

  const scoreCols: Column<Mark>[] = [
    { key: 'm', label: 'YOUR MARK', render: r => `${r.ist} · ${r.side} @ ₹${fmtNum(r.price, 2)}` },
    { key: 'c', label: 'CLOSE-OUT', render: r => r.exit_price == null ? 'open' : `${r.exit_ist} · ${r.exit_kind} @ ₹${fmtNum(r.exit_price, 2)}` },
    { key: 'h', label: 'HELD', align: 'right', render: r => heldMin(r) == null ? '—' : `${heldMin(r)} min`, sort: r => heldMin(r) },
    { key: 'd', label: 'CHANGE ON YOUR MARK', align: 'right', render: r => fmtInrSigned(markChange(r)), sort: r => markChange(r) },
    { key: 'a', label: 'PRINTED AFTER YOUR MARK', align: 'right', render: r => {
      const w = printedAfter(rows, r.minute)
      return w ? `₹${fmtNum(w.lo, 2)} – ₹${fmtNum(w.hi, 2)}` : '—'
    } },
  ]
  const listCols: Column<ReplayExpiry>[] = [
    { key: 'e', label: 'EXPIRY', render: r => <b>{r.expiry}</b>, sort: r => r.expiry },
    { key: 'w', label: 'TAPE', render: r => `${r.first_ist ?? '—'} → ${r.last_ist ?? '—'} IST` },
    { key: 'n', label: 'PRINTS', align: 'right', render: r => r.rows, sort: r => r.rows },
    { key: 'k', label: 'ATM STRIKE', align: 'right', render: r => fmtNum(r.strike, 0) },
    { key: 'go', label: '', align: 'right', render: r => <Btn size="sm" onClick={() => start(r.expiry, false)}>REPLAY</Btn> },
  ]

  const expiries = list?.expiries ?? []
  const net = netOf(marks)

  return (
    <div data-xpry-replay>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 10, color: T.muted, letterSpacing: 1 }}>REPLAY · PRACTICE ON A RECORDED EXPIRY DAY</span>
        <Chip color={T.amber} title={PRACTICE_LINE}>PRACTICE</Chip>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: T.dim }}>{sentence(DESCRIBES)}</span>
      </div>
      <div style={{ fontSize: 11, color: T.muted, marginBottom: 10 }} data-replay-words>
        A rehearsal on recorded data: the stored 1-minute straddle tape of a past expiry day steps forward in front of
        you; record practice entries at the printed prices and read the arithmetic at the close. {PRACTICE_LINE}
      </div>

      {phase === 'pick' && (
        <>
          <Panel title="Pick a recorded expiry day" accent={T.amber} source={list?.chip ? {
            state: (list.chip.state as SourceInfo['state']) ?? 'reference', source: list.chip.source,
            asOf: list.chip.as_of, ageDays: null, hint: list.chip.hint } : null} badge="context"
            subtitle="Breeze 1-minute replays stored by the after-close job (O-T16)">
            {!symbolProp && (
              <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
                {TAPE_INDICES.map(s => <Chip key={s} active={symbol === s} onClick={() => setSymbol(s)}>{s}</Chip>)}
              </div>
            )}
            {listErr && <Notice color={T.amber}>Replay list unavailable: {listErr}</Notice>}
            {!listErr && list && !list.ok && <Notice color={T.amber}>Replay list unavailable: {Object.values(list.store_errors ?? {}).join('; ') || 'store unavailable'}</Notice>}
            {!listErr && list?.ok && !expiries.length && <div style={{ fontSize: 11, color: T.muted }}>{list.empty_note ?? 'No expiry day replayed yet.'}</div>}
            {expiries.length > 0 && (
              <>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
                  <Btn variant="primary" onClick={() => start(expiries[Math.floor(Math.random() * expiries.length)].expiry, true)}>
                    RANDOM · DATE HIDDEN
                  </Btn>
                  <span style={{ fontSize: 10, color: T.dim }}>one of the {expiries.length} recorded days, its date and strike hidden until the close — the honest drill</span>
                </div>
                <DataTable dense columns={listCols} rows={expiries} rowKey={r => r.expiry} maxHeight={300} empty="no replayed expiry" />
              </>
            )}
            <div style={noteStyle}>{list?.note ?? `a rehearsal on recorded data — ${DESCRIBES}`}. Tapes are read-only history; the backfill job is run by the PM, never from this page.</div>
          </Panel>
          {runs.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Panel title="Past rehearsals (this browser)" accent={T.cyan} badge="arithmetic"
                source={inputSource('your past rehearsals — kept in this browser only (localStorage)')}
                subtitle="localStorage only — not the journal, not the paper book">
                <DataTable dense maxHeight={200} rowKey={r => r.at} empty="none yet"
                  columns={[
                    { key: 'a', label: 'WHEN', render: (r: SavedRun) => r.at.slice(0, 16).replace('T', ' ') },
                    { key: 's', label: 'DAY', render: (r: SavedRun) => `${r.symbol} · ${r.expiry}${r.hidden ? ' · was date-hidden' : ''}` },
                    { key: 'm', label: 'MARKS', align: 'right', render: (r: SavedRun) => r.marks },
                    { key: 'n', label: 'NET / UNIT', align: 'right', render: (r: SavedRun) => fmtInrSigned(r.net) },
                  ] as Column<SavedRun>[]} rows={runs} />
              </Panel>
            </div>
          )}
        </>
      )}

      {phase !== 'pick' && tapeErr && <Notice color={T.amber}>Replay tape unavailable: {tapeErr}</Notice>}
      {phase !== 'pick' && !tapeErr && !tape && <div style={{ fontSize: 11, color: T.muted }}>Loading the recorded tape…</div>}
      {phase !== 'pick' && tape && (!tape.ok || n === 0) && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Notice color={T.amber}>This day&apos;s tape is unavailable: {Object.values(tape.store_errors ?? {}).join('; ') || 'no print stored for it'}</Notice>
          <Btn size="sm" onClick={() => { setPhase('pick'); setTape(null); setMarks([]) }}>BACK TO THE LIST</Btn>
        </div>
      )}

      {phase !== 'pick' && tape && tape.ok && n > 0 && (
        <>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', marginBottom: 8 }}>
            <b style={{ fontSize: 12, color: T.amber }}>{symbol}</b>
            <span style={{ fontSize: 11, color: T.text, fontFamily: T.mono }}>
              {showDate ? `expiry ${tape.expiry} · ATM strike ${fmtNum(tape.strike, 0)}` : 'a recorded expiry day · date hidden'}
            </span>
            <span style={{ fontSize: 11, color: T.muted, fontFamily: T.mono }}>
              {cur ? `${cur.ist} IST · print ${i + 1} of ${n}` : 'no print'}
            </span>
            <span style={{ flex: 1 }} />
            {phase === 'run' && (
              <>
                <Btn size="sm" variant="primary" onClick={() => setPlaying(p => !p)}>{playing ? 'PAUSE' : 'PLAY'}</Btn>
                {SPEEDS.map((s, k) => <Chip key={s.label} active={speedIdx === k} onClick={() => setSpeedIdx(k)}>{s.label}</Chip>)}
                <Btn size="sm" onClick={() => setI(v => Math.min(v + 10, n - 1))}>+10 MIN</Btn>
                <Btn size="sm" onClick={() => setI(v => Math.min(v + 30, n - 1))}>+30 MIN</Btn>
                <Btn size="sm" onClick={finish}>RUN TO THE CLOSE</Btn>
              </>
            )}
            {phase === 'done' && <Btn size="sm" onClick={() => { setPhase('pick'); setTape(null); setMarks([]) }}>ANOTHER DAY</Btn>}
          </div>
          {phase === 'run' && <div style={{ ...noteStyle, marginBottom: 6 }}>The tape steps forward only — no rewind before the close, so a mark is never re-made with hindsight.</div>}

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
            <ExpandableChart title="The straddle tape, as recorded" accent={T.amber} source={chartSrc} badges={[{ label: 'context' }]}
              legend={cur ? `${cur.ist} IST · straddle ₹${fmtNum(cur.straddle, 2)}` : 'no print yet'} height={300}>
              <ChartWithNotes
                chart={<SessionChart height={200} lUnit="" date={showDate ? tape.expiry ?? null : null}
                  ariaLabel="recorded expiry-day straddle tape"
                  series={[
                    { label: 'straddle ₹', color: T.amber, x, y: visible.map(r => r.straddle), w: 1.8 },
                    { label: 'call ₹', color: CALL_COLOR, x, y: visible.map(r => r.ce_close), w: 1, dash: '3 3' },
                    { label: 'put ₹', color: PUT_COLOR, x, y: visible.map(r => r.pe_close), w: 1, dash: '3 3' },
                  ]} />}
                below={<div style={noteStyle}>ATM straddle (call + put at the day&apos;s opening strike), last-trade 1-minute closes as recorded
                  {showDate ? '' : ' · date and strike hidden until the close'} · {DESCRIBES}.</div>} />
            </ExpandableChart>

            <Panel title={phase === 'run' ? 'Record a practice entry' : 'The close'} accent={T.cyan} badge="arithmetic"
              source={inputSource('your practice marks — recorded here only, scored at the close')}
              subtitle={phase === 'run' ? 'at the printed price — PRACTICE only' : 'marks settled at the last print'}>
              {phase === 'run' && cur && (
                <>
                  <div style={{ display: 'flex', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
                    <Btn size="sm" disabled={cur.straddle == null} onClick={() => record('sold')}>RECORD: SOLD @ ₹{fmtNum(cur.straddle, 2)}</Btn>
                    <Btn size="sm" disabled={cur.straddle == null} onClick={() => record('bought')}>RECORD: BOUGHT @ ₹{fmtNum(cur.straddle, 2)}</Btn>
                  </div>
                  {marks.filter(m => m.exit_price == null).map(m => (
                    <div key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, fontFamily: T.mono, marginBottom: 4 }}>
                      <span>{m.ist} · {m.side} @ ₹{fmtNum(m.price, 2)}</span>
                      <Btn size="sm" disabled={cur.straddle == null} onClick={() => closeMark(m.id)}>CLOSE @ ₹{fmtNum(cur.straddle, 2)}</Btn>
                    </div>
                  ))}
                  {!marks.length && <div style={{ fontSize: 11, color: T.muted }}>No mark yet. An entry left open settles at the day&apos;s last print.</div>}
                  <div style={noteStyle}>{PRACTICE_LINE} Logged here only, scored at the close.</div>
                </>
              )}
              {phase === 'done' && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
                    <Stat big={false} label="Marks" value={marks.length} sub="practice entries" />
                    <Stat big={false} label="Net on your marks" value={fmtInrSigned(net)} sub="₹ per unit · lots not applied" />
                  </div>
                  {dayFirst && dayLast && dayFirst.straddle != null && dayLast.straddle != null && (
                    <div style={{ fontSize: 11, color: T.text, marginBottom: 6 }}>
                      The day as recorded: first print ₹{fmtNum(dayFirst.straddle, 2)} ({dayFirst.ist}) → last print ₹{fmtNum(dayLast.straddle, 2)} ({dayLast.ist}),
                      {' '}{fmtNum((dayLast.straddle / dayFirst.straddle - 1) * 100, 1)} % — the decay and the moves you practised against.
                    </div>
                  )}
                  {hidden && <div style={{ fontSize: 11, color: T.amber, marginBottom: 6 }}>Revealed: this was {symbol}, expiry {tape.expiry}, ATM strike {fmtNum(tape.strike, 0)}.</div>}
                  <div style={noteStyle}>Scoring is arithmetic over the stored tape — your mark vs the actual print, per unit. {sentence(DESCRIBES)}.</div>
                </>
              )}
            </Panel>
          </div>

          {phase === 'done' && (
            <Panel title="Your marks vs the actual prints" accent={T.amber} badge="arithmetic" source={chartSrc}
              subtitle="each mark against the recorded tape — a rehearsal, nothing is booked">
              <DataTable dense columns={scoreCols} rows={marks} rowKey={r => String(r.id)} empty="no practice entry was recorded" />
              <div style={noteStyle}>Change on your mark: the ₹ difference between your recorded price and its close-out print, signed on the position
                you recorded (per unit; lots and costs not applied). {`A rehearsal on recorded data — ${DESCRIBES}`}.</div>
            </Panel>
          )}
        </>
      )}
    </div>
  )
}
