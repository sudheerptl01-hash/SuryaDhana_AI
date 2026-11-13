'use client'

/**
 * FOBK › DEBRIEF (E-JRNL, F-12): the weekly debrief of the paper book (GET /api/options/book/debrief).
 *  - per closed structure the realised money split Θ / Δ / ν / residual — labelled "arithmetic · approximation"
 *    with the server's method one-liner shown (first-order at the entry Greeks; the residual carries gamma and
 *    every higher-order term, so the parts sum to the realised gross exactly);
 *  - the shape-template tally (win = realised net > 0) over this book's few trades;
 *  - discipline FACTS compared against the owner's OWN rules from RSK › DISCIPLINE (prefs) — trades per day vs the
 *    owner's max, days within the owner's daily loss cap, the stand-down record when one fell in the window.
 * NO composite score of any kind exists here (SPEC §7). PAPER ONLY — counts the paper book, names no order route.
 */
import { useCallback, useEffect, useState } from 'react'
import client from '@/lib/api'
import { apiError } from '@/lib/errors'
import { BadgeChip, Btn, Chip, ErrorBox, Loading, Notice, Panel, T, fmtInr } from '@/components/terminal'
import { inputSource } from '@/components/terminal/source'
import { capInr } from '@/components/risk/disciplineModel'
import { useDiscipline } from '@/components/risk/useDiscipline'

interface AttributionLeg {
  position_id: number; kind: string; side: string; strike: number | null; expiry: string
  gross_inr: number; costs_inr: number; realised_inr: number
  theta_inr: number | null; delta_inr: number | null; vega_inr: number | null; residual_inr: number
  complete: boolean; notes?: string[]; exit_mark_as_of?: string | null; exit_mark_method?: string | null
}
interface DebriefStructure {
  structure_id: number; name: string; symbol: string; template: string; closed_at: string; opened_at: string
  gross_inr: number; costs_inr: number; realised_inr: number
  attribution: { theta_inr: number; delta_inr: number; vega_inr: number; residual_inr: number; complete: boolean; notes: string[]; legs: AttributionLeg[] }
}
interface TemplateRow { template: string; n: number; wins: number; realised_inr: number; win_rate_pct: number | null }
interface DayRow { date: string; realised_inr: number; mtm_change_inr: number | null; bookings: number; closes: number; rolls: number; notes: string[] }
interface DebriefPayload {
  from: string; to: string; as_of: string; structures: DebriefStructure[]; by_template: TemplateRow[]; days: DayRow[]
  attribution_label: string; attribution_method: string; template_note: string; facts_note: string
  badge: string; realised_basis: string; paper_only: true; note: string
}

const nf = (v: number | null | undefined, d = 0) =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { maximumFractionDigits: d })
const pnlColor = (v: number | null | undefined) => v == null || v === 0 ? T.text : v > 0 ? T.green : T.red
const istToday = () => new Date(Date.now() + 330 * 60_000).toISOString().slice(0, 10)
const shiftDays = (iso: string, days: number) => new Date(new Date(`${iso}T00:00:00Z`).getTime() + days * 86_400_000).toISOString().slice(0, 10)

const td = { padding: '3px 6px', textAlign: 'right' as const, fontVariantNumeric: 'tabular-nums' as const }
const th = { color: T.dim, fontWeight: 400 as const, textAlign: 'right' as const, padding: '3px 6px' }

/** a Θ/Δ/ν cell: neutral tone (a decomposition, not a verdict); null = unassigned, sits in the residual */
function SplitCell({ v, unassigned }: { v: number | null; unassigned?: string }) {
  if (v == null) return <td style={{ ...td, color: T.dim }} title={unassigned ?? 'unassigned: its input was not stored — this part sits in the residual'}>—ᴿ</td>
  return <td style={{ ...td, color: T.text }}>{fmtInr(v, 0)}</td>
}

export function Debrief() {
  const [to, setTo] = useState(istToday())
  const [data, setData] = useState<DebriefPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const d = useDiscipline()

  const load = useCallback(() => {
    let alive = true
    setLoading(true)
    client.get<DebriefPayload>('/api/options/book/debrief', { params: { to }, timeout: 30_000 })
      .then(r => { if (alive) { setData(r.data); setErr(null) } })
      .catch(e => { if (alive) setErr(e?.response?.status === 404 ? 'the debrief route is not on this ui-api yet (deploy pending)' : apiError(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [to])
  useEffect(() => load(), [load])

  // discipline FACTS against the owner's own rules (client-side: the rules live in prefs, SPEC §1)
  const s = d.settings
  const days = data?.days ?? []
  const tradedDays = days.filter(x => x.closes + x.bookings + x.rolls > 0)
  const cap = s ? capInr(s) : null
  const withinCap = cap != null ? tradedDays.filter(x => x.realised_inr > -cap).length : null
  const maxTrades = s?.max_trades_per_day ?? null
  const busiest = tradedDays.reduce((a, x) => Math.max(a, x.bookings + x.closes + x.rolls), 0)
  const standdownInWindow = data && d.standdown && d.standdown.session >= data.from && d.standdown.session <= data.to ? d.standdown : null

  return (
    <Panel title="Weekly debrief" accent={T.violet} badge="arithmetic"
      source={inputSource('your own recorded paper closes (ui-api SQLite); the split is arithmetic over the stored entry Greeks and marks')}
      subtitle={data ? `${data.from} → ${data.to} · closed paper structures, their money split and the week's facts · PAPER ONLY` : 'PAPER ONLY'}
      right={<div style={{ display: 'flex', gap: 6 }}>
        <Btn size="sm" onClick={() => setTo(t => shiftDays(t, -7))} aria-label="previous week">‹ WEEK</Btn>
        <Btn size="sm" onClick={() => setTo(istToday())} disabled={to === istToday()}>THIS WEEK</Btn>
        <Btn size="sm" onClick={() => setTo(t => shiftDays(t, 7) > istToday() ? istToday() : shiftDays(t, 7))} disabled={to === istToday()} aria-label="next week">WEEK ›</Btn>
        <Btn size="sm" onClick={load}>{loading ? '…' : '↻'}</Btn>
      </div>}>
      {err && <ErrorBox error={err} onRetry={load} />}
      {!data && !err && <Loading label="debrief" />}
      {data && (
        <div style={{ display: 'grid', gap: 12 }} data-fobook-debrief>
          {/* ── closed structures: the Θ/Δ/ν split ── */}
          {data.structures.length === 0
            ? <Notice color={T.muted}>No paper structure closed between {data.from} and {data.to}. Closes land here with their realised money split Θ / Δ / ν.</Notice>
            : <div style={{ display: 'grid', gap: 6 }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>CLOSED STRUCTURES · money split</span>
                  <BadgeChip badge="arithmetic" note={data.attribution_method} />
                  <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim }} title={data.attribution_method}>{data.attribution_label}</span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }}>
                    <thead><tr>
                      <th style={{ ...th, textAlign: 'left' }}>Structure</th><th style={{ ...th, textAlign: 'left' }}>Template</th>
                      <th style={th}>Closed</th><th style={th}>Θ</th><th style={th}>Δ</th><th style={th}>ν</th>
                      <th style={th} title="gamma and every higher-order / cross term — the gross minus the assigned parts">residual</th>
                      <th style={th}>costs</th><th style={th}>realised</th>
                    </tr></thead>
                    <tbody>
                      {data.structures.map(x => (
                        <tr key={x.structure_id} style={{ borderTop: `1px solid ${T.border}` }}>
                          <td style={{ ...td, textAlign: 'left', color: T.amber }} title={x.attribution.notes.join(' · ') || undefined}>
                            {x.symbol} <span style={{ color: T.muted }}>{x.name}</span>{!x.attribution.complete && <span style={{ color: T.dim }} title="a part's input was not stored; it sits in the residual"> ᴿ</span>}
                          </td>
                          <td style={{ ...td, textAlign: 'left', color: T.muted }}>{x.template}</td>
                          <td style={{ ...td, color: T.dim }}>{String(x.closed_at).slice(0, 10)}</td>
                          <SplitCell v={x.attribution.theta_inr} />
                          <SplitCell v={x.attribution.delta_inr} />
                          <SplitCell v={x.attribution.vega_inr} />
                          <td style={{ ...td, color: T.muted }}>{fmtInr(x.attribution.residual_inr, 0)}</td>
                          <td style={{ ...td, color: T.muted }}>{fmtInr(x.costs_inr, 0)}</td>
                          <td style={{ ...td, color: pnlColor(x.realised_inr), fontWeight: 600 }}>{fmtInr(x.realised_inr, 0)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5 }}>
                  {data.attribution_label}: {data.attribution_method}
                </div>
              </div>}

          {/* ── template tally ── */}
          {data.by_template.length > 0 && (
            <div style={{ display: 'grid', gap: 4 }}>
              <span style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>BY TEMPLATE</span>
              <table style={{ borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11, maxWidth: 520 }}>
                <thead><tr><th style={{ ...th, textAlign: 'left' }}>Template</th><th style={th}>closed</th><th style={th}>wins</th><th style={th}>win rate</th><th style={th}>realised</th></tr></thead>
                <tbody>{data.by_template.map(t => (
                  <tr key={t.template} style={{ borderTop: `1px solid ${T.border}` }}>
                    <td style={{ ...td, textAlign: 'left', color: T.text }}>{t.template}</td>
                    <td style={td}>{t.n}</td><td style={td}>{t.wins}</td>
                    <td style={td}>{t.win_rate_pct != null ? `${nf(t.win_rate_pct, 1)}%` : '—'}</td>
                    <td style={{ ...td, color: pnlColor(t.realised_inr) }}>{fmtInr(t.realised_inr, 0)}</td>
                  </tr>))}
                </tbody>
              </table>
              <div style={{ fontSize: 10, color: T.dim }}>{data.template_note}</div>
            </div>
          )}

          {/* ── discipline facts (owner's own rules from RSK › DISCIPLINE; facts only, no score — SPEC §7) ── */}
          <div style={{ display: 'grid', gap: 4 }}>
            <span style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>DISCIPLINE FACTS <Chip color={T.muted} style={{ fontSize: 9, padding: '1px 5px' }} title={data.facts_note}>your own rules</Chip></span>
            <div style={{ fontFamily: T.mono, fontSize: 11, color: T.text, display: 'grid', gap: 2 }}>
              <span>{tradedDays.length} traded day(s) in the window · busiest day {busiest} action(s){maxTrades != null ? ` vs your ${maxTrades}/day rule` : ''}</span>
              {cap != null && withinCap != null
                ? <span>{withinCap} of {tradedDays.length} traded day(s) ended within your daily loss cap ({fmtInr(cap, 0)})</span>
                : <span style={{ color: T.dim }}>set your capital in RSK › DISCIPLINE to compare these facts against your own caps</span>}
              {standdownInWindow && (
                <span style={{ color: T.amber }}>stand down tripped {standdownInWindow.session}: {standdownInWindow.detail} — your rule, set in RSK › DISCIPLINE</span>
              )}
            </div>
            <div style={{ fontSize: 10, color: T.dim }}>{data.facts_note}. Counts the PAPER book only — log your real ICICI trades here (OSTR › Book paper) or these facts are incomplete.</div>
          </div>

          <div style={{ fontSize: 10, color: T.dim }}>{data.note}. Realised figures are {data.realised_basis}. Describes, does not predict.</div>
        </div>
      )}
    </Panel>
  )
}
