'use client'

/**
 * ECO · economic calendar: India's official data releases (CPI, WPI, IIP, core industries, GDP: from MoSPI's and
 * DPIIT's published release calendars), RBI policy decisions and US Fed decisions, in IST, with what is next.
 * Page review 5 Nov 2026 (M28, m012): also the US releases (NFP, CPI…, with ForexFactory's forecast and previous
 * print when served), the F&O expiry dates (holiday-shifted) and exchange special sessions (Muhurat) that the
 * calendar endpoint serves; a past release shows its print when the calendar stores one.
 */
import { useEffect, useMemo, useState } from 'react'
import { getEcoCalendar, type EcoEvent } from '@/lib/api'
import { Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, T, type Column, fmtDay, undatedSource } from '@/components/terminal'
import { ecoFamily, ecoKey, ecoNext, ecoPrint, type EcoFamily } from '@/components/marketPagesModel'

export const ECO_KINDS: Record<string, { color: string; label: string; why: string }> = {
  RBI:  { color: T.amber,  label: 'RBI',  why: 'repo rate and stance: moves banks, NBFCs, rate-sensitive sectors' },
  FED:  { color: T.cyan,   label: 'FED',  why: 'US rates: drives FII flows and the rupee' },
  CPI:  { color: T.red,    label: 'CPI',  why: 'retail inflation: the RBI targets 4% (2–6% band)' },
  WPI:  { color: T.violet, label: 'WPI',  why: 'wholesale prices: input-cost pressure on margins' },
  IIP:  { color: T.green,  label: 'IIP',  why: 'factory, mining and power output' },
  CORE: { color: T.green,  label: 'CORE', why: 'core industries (coal, steel, cement, power…): an early read on IIP' },
  GDP:  { color: T.amber,  label: 'GDP',  why: 'quarterly growth' },
  HOLIDAY: { color: T.muted, label: 'CLOSED', why: 'NSE equity market holiday: no trading, no settlement' },
}

/** The label, colour and why of the kinds the calendar adds (M28): by family when the exact kind is new. */
const FAMILY: Record<EcoFamily, { color: string; label: string; why: string }> = {
  IN_DATA: { color: T.green, label: 'INDIA', why: 'an official India data release' },
  RBI: ECO_KINDS.RBI,
  US_DATA: { color: T.cyan, label: 'US', why: 'a US data release: moves the dollar, US yields, FII flows and gold' },
  FED: { color: T.cyan, label: 'FED', why: 'US Federal Reserve: rates and guidance' },
  EXPIRY: { color: T.violet, label: 'EXPIRY', why: 'NSE F&O expiry (holiday-shifted): pin risk, rollover, the weekly / monthly settlement' },
  SESSION: { color: T.amber, label: 'SESSION', why: 'an exchange special session (Muhurat): unusual hours, thin liquidity' },
  HOLIDAY: ECO_KINDS.HOLIDAY,
  OTHER: { color: T.muted, label: 'OTHER', why: '' },
}
const US_WHY: Record<string, string> = {
  US_NFP: 'US jobs report: the single biggest scheduled mover of the dollar, US yields and gold',
  US_CPI: 'US inflation: sets the Fed path, the dollar and US yields',
}

/** One row's label / colour / why: the known India kinds, then the US-specific ones, then the family. */
export function ecoKindSpec(e: { kind: string; country: string; what?: string }): { color: string; label: string; why: string } {
  if (e.country === 'IN' && ECO_KINDS[e.kind]) return ECO_KINDS[e.kind]
  if (e.kind === 'RBI' || e.kind === 'FED' || e.kind === 'HOLIDAY') return ECO_KINDS[e.kind]
  const fam = FAMILY[ecoFamily({ ...e, date: '', time: null, what: e.what ?? '' })]
  const why = US_WHY[e.kind]
  const label = e.kind === 'US_NFP' ? 'NFP' : e.kind === 'MUHURAT' ? 'MUHURAT' : fam.label
  return { ...fam, label, why: why ?? fam.why }
}

const dayDiff = (a: string, b: string) => Math.round((new Date(`${a}T00:00:00`).getTime() - new Date(`${b}T00:00:00`).getTime()) / 86_400_000)
export const ecoWhen = (d: string, today: string) => {
  const n = dayDiff(d, today)
  return n === 0 ? 'today' : n === 1 ? 'tomorrow' : n === -1 ? 'yesterday' : n > 0 ? `in ${n} days` : `${-n} days ago`
}

type Row = Omit<EcoEvent, 'country'> & { country: string; shifted?: boolean | null; monthly?: boolean | null; items?: { name?: string | null }[] | null; impact?: string | null; forecast?: string | null; previous?: string | null; actual?: string | null; circular?: string | null }
const FAMILY_ORDER: EcoFamily[] = ['IN_DATA', 'RBI', 'US_DATA', 'FED', 'EXPIRY', 'SESSION', 'HOLIDAY', 'OTHER']
const FAMILY_CHIP: Record<EcoFamily, string> = { IN_DATA: 'INDIA DATA', RBI: 'RBI', US_DATA: 'US DATA', FED: 'FED', EXPIRY: 'F&O EXPIRY', SESSION: 'SPECIAL SESSIONS', HOLIDAY: 'HOLIDAYS', OTHER: 'OTHER' }

export function EconomicCalendar() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getEcoCalendar>>['data'] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [fam, setFam] = useState<EcoFamily | null>(null)
  useEffect(() => {
    getEcoCalendar(30, 120).then(r => setData(r.data)).catch(e => setErr(e?.message || 'calendar unavailable'))
  }, [])
  const events = (data?.events ?? []) as unknown as Row[]
  const rows = useMemo(() => events.filter(e => !fam || ecoFamily(e) === fam), [events, fam])
  if (err) return <ErrorBox error={err} />
  if (!data) return <Loading label="economic calendar" />
  const today = data.today
  const next = ecoNext(events, today)
  const hasConsensus = events.some(e => e.forecast != null || e.previous != null || e.actual != null)
  const hasImpact = events.some(e => e.impact != null)
  const cols: Column<Row>[] = [
    { key: 'date', label: 'Date', sort: e => e.date, render: e => <span style={{ color: e.date === today ? T.amber : e.date < today ? T.dim : T.text, whiteSpace: 'nowrap' }}>{fmtDay(e.date)}</span> },
    { key: 'time', label: 'IST', render: e => <span style={{ color: T.muted }}>{e.time ?? '—'}</span> },
    { key: 'when', label: 'When', render: e => <span style={{ color: e.date < today ? T.dim : dayDiff(e.date, today) <= 2 ? T.amber : T.muted, whiteSpace: 'nowrap' }}>{ecoWhen(e.date, today)}</span> },
    { key: 'ctry', label: '', render: e => <span style={{ color: T.dim, fontSize: 10 }}>{e.country === 'USD' ? 'US' : e.country}</span> },
    { key: 'kind', label: 'Type', sort: e => e.kind, render: e => { const k = ecoKindSpec(e); return <span style={{ color: k.color, fontSize: 10.5, letterSpacing: 0.8, fontWeight: 700 }}>{k.label}</span> } },
    { key: 'what', label: 'Release', render: e => <span style={{ color: e.date < today ? T.muted : T.text, display: 'inline-block', maxWidth: 620, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }}
        title={`${e.what}\n${ecoKindSpec(e).why}${e.source ? `\nsource: ${e.source}` : ''}`}>{e.what}
        {(e.moved || e.shifted) && <span style={{ color: T.dim, fontSize: 10 }} title="planned on a weekend or holiday: released the next working day (an expiry: the session before)"> · moved</span>}
        {e.circular && <span style={{ color: T.dim, fontSize: 10 }}> · {e.circular}</span>}</span> },
    ...(hasImpact ? [{ key: 'impact', label: 'Impact', render: (e: Row) => <span style={{ color: (e.impact ?? '').toLowerCase() === 'high' ? T.text : T.dim, fontSize: 10.5 }}>{e.impact ?? ''}</span> }] as Column<Row>[] : []),
    ...(hasConsensus ? [
      { key: 'fc', label: 'Forecast', align: 'right' as const, render: (e: Row) => <span style={{ color: T.muted }}>{e.forecast ?? ''}</span> },
      { key: 'prev', label: 'Previous', align: 'right' as const, render: (e: Row) => <span style={{ color: T.dim }}>{e.previous ?? ''}</span> },
    ] as Column<Row>[] : []),
    // m012: a past release shows its print when the calendar stores one; otherwise it says so (no silent blank)
    // (a future row's forecast is printed once, in its own column: "the same number once per page")
    { key: 'print', label: 'Print', align: 'right', render: e => { const p = ecoPrint(e, today); return <span style={{ color: p.known ? T.bright : T.dim, fontSize: p.known ? 11.5 : 10 }}>{p.known || e.date < today ? p.text : ''}</span> } },
    { key: 'why', label: 'Why it matters', render: e => <span style={{ color: T.dim, fontSize: 10.5, display: 'inline-block', maxWidth: 360, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }} title={ecoKindSpec(e).why}>{ecoKindSpec(e).why}</span> },
    { key: 'src', label: 'Source', render: e => <span style={{ color: T.dim, fontSize: 10, display: 'inline-block', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }} title={e.source ?? ''}>{e.source}</span> },
  ]
  const fams = FAMILY_ORDER.filter(f => events.some(e => ecoFamily(e) === f))
  return (
    <div>
      <PageHeader code="ECO" title="Economic calendar"
        subtitle="India data releases · RBI and Fed decisions · US releases · F&O expiries · special sessions · times in IST" />
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(1, next.length)}, minmax(0, 1fr))`, gap: 8, marginBottom: 12 }}>
        {next.map(e => { const k = ecoKindSpec(e); return (
          <div key={ecoKey(e)} style={{ border: `1px solid ${T.border}`, borderTop: `2px solid ${k.color}`, background: T.panel, padding: '8px 10px' }}>
            <div style={{ fontSize: 10, letterSpacing: 1.2, color: k.color, fontWeight: 700 }}>{k.label === (e.country === 'USD' ? 'US' : e.country) ? k.label : `${k.label} · ${e.country === 'USD' ? 'US' : e.country}`}</div>
            <div style={{ fontSize: 13, color: T.text, margin: '3px 0' }}>{e.what}</div>
            <div style={{ fontSize: 11, fontFamily: T.mono, color: dayDiff(e.date, today) <= 1 ? T.amber : T.muted }}>{fmtDay(e.date)} · {e.time ? `${e.time} IST` : 'all day'} · {ecoWhen(e.date, today)}</div>
          </div>) })}
      </div>
      <Panel source={undatedSource('ECO calendar', 'RBI / MOSPI / DPIIT / Fed release schedules, NSE holidays and expiries, US releases (ForexFactory) when served, kept daily')} title={`Calendar · ${rows.length}`} accent={T.cyan} pad={0}
        right={<div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Chip color={T.muted} active={!fam} onClick={() => setFam(null)}>ALL</Chip>
          {fams.map(f => <Chip key={f} color={FAMILY[f].color} active={fam === f} onClick={() => setFam(fam === f ? null : f)}>{FAMILY_CHIP[f]}</Chip>)}
        </div>}>
        <DataTable columns={cols} rows={rows} rowKey={ecoKey} dense exportName="eco_calendar"
          rowStyle={e => (e.date === today ? { background: 'rgba(245,158,11,0.07)' } : undefined)} />
        <div style={{ padding: '8px 10px', fontSize: 10.5, color: T.dim, lineHeight: 1.5, borderTop: `1px solid ${T.border}` }}>
          Last 30 days and the next 4 months · hover a release for why it matters. {data.note} {Object.entries(data.sources).map(([k, u]) => <a key={k} href={u} target="_blank" rel="noreferrer" style={{ color: T.cyan, marginRight: 10 }}>{k} calendar ↗</a>)}
          {!data.fed_available && <span style={{ color: T.amber }}> · Fed calendar unreachable right now: Fed dates missing.</span>}
          {' '}Market holidays come from NSE; a government release falls on its planned day unless the government is
          also closed (MoSPI published CPI on 14 Sep, an NSE holiday). {hasConsensus
            ? 'Forecast and previous prints are ForexFactory’s for US releases; India releases carry dates only (no free consensus source).'
            : 'Dates only: no forecasts or consensus figures for these rows.'}
          {!events.some(e => ecoFamily(e) === 'US_DATA') && ' US data releases appear here once the calendar endpoint serves them.'}
        </div>
      </Panel>
    </div>
  )
}
