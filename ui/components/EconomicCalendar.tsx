'use client'

/**
 * ECO · economic calendar: India's official data releases (CPI, WPI, IIP, core industries, GDP: from MoSPI's and
 * DPIIT's published release calendars), RBI policy decisions and US Fed decisions, in IST, with what is next.
 */
import { useEffect, useMemo, useState } from 'react'
import { getEcoCalendar, type EcoEvent } from '@/lib/api'
import { Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, T, type Column, fmtDay, undatedSource } from '@/components/terminal'

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

const dayDiff = (a: string, b: string) => Math.round((new Date(`${a}T00:00:00`).getTime() - new Date(`${b}T00:00:00`).getTime()) / 86_400_000)
export const ecoWhen = (d: string, today: string) => {
  const n = dayDiff(d, today)
  return n === 0 ? 'today' : n === 1 ? 'tomorrow' : n === -1 ? 'yesterday' : n > 0 ? `in ${n} days` : `${-n} days ago`
}

export function EconomicCalendar() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getEcoCalendar>>['data'] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [kind, setKind] = useState<string | null>(null)
  useEffect(() => {
    getEcoCalendar(30, 120).then(r => setData(r.data)).catch(e => setErr(e?.message || 'calendar unavailable'))
  }, [])
  const rows = useMemo(() => (data?.events ?? []).filter(e => !kind || e.kind === kind), [data, kind])
  if (err) return <ErrorBox error={err} />
  if (!data) return <Loading label="economic calendar" />
  const today = data.today
  const next = data.events.filter(e => e.date >= today).slice(0, 4)
  const cols: Column<EcoEvent>[] = [
    { key: 'date', label: 'Date', sort: e => e.date, render: e => <span style={{ color: e.date === today ? T.amber : e.date < today ? T.dim : T.text, whiteSpace: 'nowrap' }}>{fmtDay(e.date)}</span> },
    { key: 'time', label: 'IST', render: e => <span style={{ color: T.muted }}>{e.time ?? '—'}</span> },
    { key: 'when', label: 'When', render: e => <span style={{ color: e.date < today ? T.dim : dayDiff(e.date, today) <= 2 ? T.amber : T.muted, whiteSpace: 'nowrap' }}>{ecoWhen(e.date, today)}</span> },
    { key: 'ctry', label: '', render: e => <span style={{ color: T.dim, fontSize: 10 }}>{e.country}</span> },
    { key: 'kind', label: 'Type', sort: e => e.kind, render: e => <span style={{ color: ECO_KINDS[e.kind]?.color ?? T.muted, fontSize: 10.5, letterSpacing: 0.8, fontWeight: 700 }}>{ECO_KINDS[e.kind]?.label ?? e.kind}</span> },
    { key: 'what', label: 'Release', render: e => <span style={{ color: e.date < today ? T.muted : T.text }} title={ECO_KINDS[e.kind]?.why}>{e.what}
        {e.moved && <span style={{ color: T.dim, fontSize: 10 }} title="planned on a weekend: released the next working day"> · moved from weekend</span>}</span> },
    { key: 'why', label: 'Why it matters', render: e => <span style={{ color: T.dim, fontSize: 10.5 }}>{ECO_KINDS[e.kind]?.why ?? ''}</span> },
    { key: 'src', label: 'Source', render: e => <span style={{ color: T.dim, fontSize: 10 }}>{e.source}</span> },
  ]
  const kinds = [...new Set(data.events.map(e => e.kind))]
  return (
    <div>
      <PageHeader code="ECO" title="Economic calendar"
        subtitle="India data releases from the official release calendars · RBI and Fed decisions · times in IST" />
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(1, next.length)}, minmax(0, 1fr))`, gap: 8, marginBottom: 12 }}>
        {next.map(e => (
          <div key={`${e.kind}-${e.date}`} style={{ border: `1px solid ${T.border}`, borderTop: `2px solid ${ECO_KINDS[e.kind]?.color ?? T.border}`, background: T.panel, padding: '8px 10px' }}>
            <div style={{ fontSize: 10, letterSpacing: 1.2, color: ECO_KINDS[e.kind]?.color ?? T.muted, fontWeight: 700 }}>{ECO_KINDS[e.kind]?.label ?? e.kind} · {e.country}</div>
            <div style={{ fontSize: 13, color: T.text, margin: '3px 0' }}>{e.what}</div>
            <div style={{ fontSize: 11, fontFamily: T.mono, color: dayDiff(e.date, today) <= 1 ? T.amber : T.muted }}>{fmtDay(e.date)} · {e.time ? `${e.time} IST` : 'all day'} · {ecoWhen(e.date, today)}</div>
          </div>))}
      </div>
      <Panel source={undatedSource('ECO calendar', 'RBI / MOSPI / Fed release schedules, kept daily')} title={`Calendar · ${rows.length}`} accent={T.cyan} pad={0}
        subtitle="last 30 days and the next 4 months · hover a release for why it matters"
        right={<div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Chip color={T.muted} active={!kind} onClick={() => setKind(null)}>ALL</Chip>
          {kinds.map(k => <Chip key={k} color={ECO_KINDS[k]?.color ?? T.muted} active={kind === k} onClick={() => setKind(kind === k ? null : k)}>{ECO_KINDS[k]?.label ?? k}</Chip>)}
        </div>}>
        <DataTable columns={cols} rows={rows} rowKey={e => `${e.kind}-${e.date}`} dense exportName="eco_calendar"
          rowStyle={e => (e.date === today ? { background: 'rgba(245,158,11,0.07)' } : undefined)} />
        <div style={{ padding: '8px 10px', fontSize: 10.5, color: T.dim, lineHeight: 1.5, borderTop: `1px solid ${T.border}` }}>
          {data.note} {Object.entries(data.sources).map(([k, u]) => <a key={k} href={u} target="_blank" rel="noreferrer" style={{ color: T.cyan, marginRight: 10 }}>{k} calendar ↗</a>)}
          {!data.fed_available && <span style={{ color: T.amber }}> · Fed calendar unreachable right now: Fed dates missing.</span>}
          {' '}Market holidays come from NSE; a government release falls on its planned day unless the government is
          also closed (MoSPI published CPI on 14 Sep, an NSE holiday). Dates only: no forecasts or consensus figures (no free source for those).
        </div>
      </Panel>
    </div>
  )
}
