'use client'

import { apiError } from '@/lib/errors'
/**
 * FUND · fundamentals screener: every company whose NSE results filings have been read (FA cache), filtered on
 * the latest quarter's growth, margin and valuation at the last NSE close. A screen, not a signal: nothing here
 * has been back-tested (see RSCH for what has).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { getSurveillance } from '@/lib/api'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { getFundamentalsScreen, type ScreenRow } from '@/lib/api'
import { COMP_KEY } from '@/components/Compare'
import { goToPage } from '@/lib/navigate'
import { Chip, DataTable, ErrorBox, Input, Loading, PageHeader, Panel, Select, T, TickerLink, fiscalQuarter, fmtFixed, fmtPct, median, type Column, ordinal, undatedSource } from '@/components/terminal'   // fmtFixed: U+2212 (C1-18)

type Preset = { id: string; label: string; hint: string; f: Partial<Filters> }
type Filters = { mcapMin: number; peMax: number | null; revMin: number | null; patMin: number | null; marginMin: number | null; industry: string; latestOnly?: boolean; pctlMax?: number | null }
const BASE: Filters = { mcapMin: 0, peMax: null, revMin: null, patMin: null, marginMin: null, industry: '' }
const PRESETS: Preset[] = [
  { id: 'all', label: 'ALL', hint: 'everything read so far', f: {} },
  { id: 'season', label: 'REPORTED THIS QUARTER', hint: 'only companies already on the newest quarter (results season)', f: { latestOnly: true } },
  { id: 'garp', label: 'GROWTH, SANE PRICE', hint: 'revenue & profit ≥ +15% y/y, P/E ≤ 30', f: { revMin: 15, patMin: 15, peMax: 30 } },
  { id: 'fast', label: 'FAST PROFIT GROWTH', hint: 'profit ≥ +30% y/y on revenue ≥ +10%', f: { patMin: 30, revMin: 10 } },
  { id: 'cheap', label: 'LOW P/E', hint: 'P/E ≤ 15, market cap ≥ ₹5,000 cr', f: { peMax: 15, mcapMin: 5000 } },
  { id: 'margin', label: 'HIGH MARGIN', hint: 'net margin ≥ 20%', f: { marginMin: 20 } },
  { id: 'histcheap', label: 'CHEAP VS OWN PAST', hint: 'P/E in the bottom fifth of its own history, profit growing', f: { pctlMax: 20, patMin: 0 } },
  { id: 'large', label: 'LARGE CAPS', hint: 'market cap ≥ ₹50,000 cr', f: { mcapMin: 50000 } },
]
const MCAPS: [number, string][] = [[0, 'ANY SIZE'], [1000, '≥ ₹1K CR'], [5000, '≥ ₹5K CR'], [20000, '≥ ₹20K CR'], [100000, '≥ ₹1L CR']]

const qn = fiscalQuarter

export function FundamentalsScreen() {
  const [rows, setRows] = useState<ScreenRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // the last screen is remembered in this browser (filters only, never data)
  const SAVED = 'suryadhana.fund.filters.v1'
  const [preset, setPreset] = useState<string>(() => { try { return JSON.parse(localStorage.getItem(SAVED) || '{}').preset ?? 'all' } catch { return 'all' } })
  const [f, setF] = useState<Filters>(() => { try { return { ...BASE, ...(JSON.parse(localStorage.getItem(SAVED) || '{}').f ?? {}) } } catch { return BASE } })
  // Multi-window (C3-02): what this window last adopted from storage; that state is not written back (no echo over
  // another window's newer write). Cleared on every save run, so the user's own later edits always save.
  const adoptedScreen = useRef<string | null>(null)
  const adoptedHide = useRef<string | null>(null)
  useEffect(() => {
    const v = JSON.stringify({ preset, f }), echo = adoptedScreen.current
    adoptedScreen.current = null
    if (v === echo) return
    try { localStorage.setItem(SAVED, v) } catch { /* storage blocked */ }
  }, [preset, f])
  const [q, setQ] = useState('')
  // NSE surveillance (ASM / GSM / ESM / IRP, 2–5% bands, trade-to-trade, F&O ban): marked, and optionally hidden
  const [flagged, setFlagged] = useState<Record<string, string[]>>({})
  const [hideFlagged, setHideFlagged] = useState<boolean>(() => { try { return localStorage.getItem('suryadhana.fund.hideflagged') === '1' } catch { return false } })
  useEffect(() => { getSurveillance([], true).then(r => setFlagged(r.data.flagged ?? {})).catch(() => {}) }, [])
  useEffect(() => {
    const v = hideFlagged ? '1' : '0', echo = adoptedHide.current
    adoptedHide.current = null
    if (v === echo) return
    try { localStorage.setItem('suryadhana.fund.hideflagged', v) } catch { /* storage blocked */ }
  }, [hideFlagged])
  // The saved screen changed in another window (or on another device, via sync): show it here too, so this window's
  // next edit starts from it instead of writing its stale copy back over the other window's edit.
  useExternalPrefChange([SAVED, 'suryadhana.fund.hideflagged'], () => {
    try {
      const s = JSON.parse(localStorage.getItem(SAVED) || '{}')
      const nextPreset: string = s.preset ?? 'all'
      const nextF: Filters = { ...BASE, ...(s.f ?? {}) }
      adoptedScreen.current = JSON.stringify({ preset: nextPreset, f: nextF })
      setPreset(nextPreset)
      setF(prev => (JSON.stringify(prev) === JSON.stringify(nextF) ? prev : nextF))
    } catch { /* corrupt or blocked: keep this window's screen */ }
    try {
      const hide = localStorage.getItem('suryadhana.fund.hideflagged') === '1'
      adoptedHide.current = hide ? '1' : '0'
      setHideFlagged(hide)
    } catch { /* storage blocked */ }
  })
  const [picked, setPicked] = useState<string[]>([])           // up to 8 rows to open in COMP
  const togglePick = (sym: string) => setPicked(p => p.includes(sym) ? p.filter(x => x !== sym) : p.length >= 8 ? p : [...p, sym])
  const compare = () => {
    try { localStorage.setItem(COMP_KEY, JSON.stringify({ syms: picked, period: '1y' })) } catch { /* storage blocked */ }
    window.dispatchEvent(new Event('suryadhana:comp'))
    goToPage('compare')
  }

  useEffect(() => {
    getFundamentalsScreen().then(r => setRows(r.data.rows)).catch(e => setError(apiError(e, 'unavailable')))
  }, [])

  const industries = useMemo(() => [...new Set((rows ?? []).map(r => r.industry).filter((x): x is string => !!x))].sort(), [rows])
  // the newest quarter anyone has reported: rows still on an older quarter haven't reported it yet (amber)
  const latestQ = useMemo(() => (rows ?? []).reduce<string | null>((m, r) => (!m || r.period_end > m ? r.period_end : m), null), [rows])
  const reported = (rows ?? []).filter(r => r.period_end === latestQ).length
  const shown = useMemo(() => (rows ?? []).filter(r =>
    (!q || r.symbol.includes(q.toUpperCase())) &&
    (!hideFlagged || !flagged[r.symbol]) &&
    (!f.latestOnly || r.period_end === latestQ) &&
    (f.pctlMax == null || (r.pe_pctl != null && r.pe_pctl <= f.pctlMax)) &&
    (!f.industry || r.industry === f.industry) &&
    ((r.mcap ?? 0) / 1e7 >= f.mcapMin) &&
    (f.peMax == null || (r.pe != null && r.pe <= f.peMax)) &&
    (f.revMin == null || (r.revenue_yoy != null && r.revenue_yoy >= f.revMin)) &&
    (f.patMin == null || (r.pat_yoy != null && r.pat_yoy >= f.patMin) || (f.patMin <= 0 && r.pat_yoy_turn === 'to profit')) &&
    (f.marginMin == null || (r.pat_margin != null && r.pat_margin >= f.marginMin))), [rows, f, q, latestQ, hideFlagged, flagged])

  const apply = (p: Preset) => { setPreset(p.id); setF({ ...BASE, industry: f.industry, ...p.f }) }
  const num = (v: string) => (v.trim() === '' || isNaN(Number(v)) ? null : Number(v))
  const crs = (v: number | null) => v == null ? '—' : Math.round(v / 1e7).toLocaleString('en-IN')
  const g = (v: number | null, turn?: string | null) => turn ? <span style={{ color: turn === 'to profit' ? T.green : T.red }}>{turn}</span>
    : v == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: v >= 0 ? T.green : T.red }}>{fmtPct(v, 1)}</span>

  const cols: Column<ScreenRow>[] = [
    { key: 'pick', label: '', width: 26, render: r => <input type="checkbox" checked={picked.includes(r.symbol)} onChange={() => togglePick(r.symbol)}
        title="pick up to 8, then COMPARE" onClick={e => e.stopPropagation()} style={{ accentColor: T.amber, cursor: 'pointer' }} /> },
    { key: 'sym', label: 'Stock', sort: r => r.symbol, render: r => <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
        <TickerLink symbol={r.symbol} noFlag />
        {flagged[r.symbol] && <span title={`NSE surveillance: ${flagged[r.symbol].join(', ')}`} style={{ color: flagged[r.symbol].some(c => /GSM|ESM|IRP|BAN|T2T|BAND 2/.test(c)) ? T.red : T.amber, fontSize: 10 }}>⚑</span>}</span> },
    { key: 'ind', label: 'Industry', sort: r => r.industry ?? '', render: r => <span style={{ color: T.muted, maxWidth: 200, display: 'inline-block', overflow: 'hidden', textOverflow: 'ellipsis', verticalAlign: 'bottom' }}>{r.industry ?? '—'}</span> },
    { key: 'mcap', label: 'Mcap ₹ cr', align: 'right', sort: r => r.mcap ?? -1, render: r => <span style={{ color: T.muted }}>{crs(r.mcap)}</span> },
    { key: 'pe', label: 'P/E', align: 'right', sort: r => r.pe ?? 1e9, title: 'market cap ÷ last 4 quarters of profit', render: r => r.pe == null ? <span style={{ color: T.dim }}>—</span> : `${fmtFixed(r.pe, 1)}×` },
    { key: 'pctl', label: 'P/E vs own past', align: 'right', sort: r => r.pe_pctl ?? 1e9,
      title: "where today's P/E sits in the company's own daily P/E history (point-in-time, ~2–3 years): 0 = cheapest it has been, 100 = dearest",
      render: r => r.pe_pctl == null ? <span style={{ color: T.dim }}>—</span>
        : <span title={r.pe_median_hist != null ? `its median P/E: ${r.pe_median_hist.toFixed(1)}×` : ''} style={{ color: r.pe_pctl <= 20 ? T.green : r.pe_pctl >= 80 ? T.red : T.muted }}>{ordinal(r.pe_pctl)} pct</span> },
    { key: 'pb', label: 'P/B', align: 'right', sort: r => r.pb ?? 1e9, render: r => r.pb == null ? <span style={{ color: T.dim }}>—</span> : `${fmtFixed(r.pb, 1)}×` },
    { key: 'rev', label: 'Revenue YoY', align: 'right', sort: r => r.revenue_yoy ?? -999, render: r => g(r.revenue_yoy) },
    { key: 'pat', label: 'Profit YoY', align: 'right', sort: r => r.pat_yoy ?? -999, render: r => g(r.pat_yoy, r.pat_yoy_turn) },
    { key: 'mg', label: 'Net margin', align: 'right', sort: r => r.pat_margin ?? -999, render: r => r.pat_margin == null ? '—' : <span style={{ color: T.muted }}>{fmtFixed(r.pat_margin, 1)}%</span> },
    { key: 'q', label: 'Quarter', align: 'right', sort: r => r.period_end, render: r => <span style={{ color: r.period_end === latestQ ? T.text : T.amber }} title={r.period_end === latestQ ? `filed ${r.filed_at.slice(0, 10)}` : 'this quarter is older: the latest results are not out yet (or not read yet)'}>{qn(r.period_end)}</span> },
  ]

  return (
    <div>
      <PageHeader code="FUND" title="Fundamentals screener"
        subtitle={rows ? `${rows.length} companies with results filings read · latest quarter vs a year ago · valuation at the last NSE close` : 'reading the FA cache'} />
      {error && <ErrorBox error={error} />}
      {!rows && !error && <Loading label="Loading fundamentals" />}
      {rows && <>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 8 }}>
          {PRESETS.map(p => <Chip key={p.id} color={T.amber} active={preset === p.id} title={p.hint} onClick={() => apply(p)}>{p.label}</Chip>)}
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: 10 }}>
          <Input label="Stock" value={q} onChange={setQ} placeholder="symbol" width={110} />
          <Select label="Industry" value={f.industry} onChange={v => setF({ ...f, industry: v })} options={[{ value: '', label: 'All industries' }, ...industries.map(i => ({ value: i, label: i }))]} />
          <Input label="P/E ≤" value={f.peMax == null ? '' : String(f.peMax)} onChange={v => { setPreset(''); setF({ ...f, peMax: num(v) }) }} width={70} />
          <Input label="Revenue YoY ≥ %" value={f.revMin == null ? '' : String(f.revMin)} onChange={v => { setPreset(''); setF({ ...f, revMin: num(v) }) }} width={90} />
          <Input label="Profit YoY ≥ %" value={f.patMin == null ? '' : String(f.patMin)} onChange={v => { setPreset(''); setF({ ...f, patMin: num(v) }) }} width={90} />
          <Input label="Net margin ≥ %" value={f.marginMin == null ? '' : String(f.marginMin)} onChange={v => { setPreset(''); setF({ ...f, marginMin: num(v) }) }} width={90} />
          <div style={{ display: 'flex', gap: 4 }}>{MCAPS.map(([v, l]) => <Chip key={v} color={T.cyan} active={f.mcapMin === v} onClick={() => { setPreset(''); setF({ ...f, mcapMin: v }) }}>{l}</Chip>)}</div>
          <Chip color={T.red} active={hideFlagged} onClick={() => setHideFlagged(h => !h)}
            title="hide stocks under NSE surveillance (ASM, GSM, ESM, IRP), with a 2–5% price band, in trade-to-trade, or in the F&O ban">
            {hideFlagged ? '⚑ HIDDEN' : '⚑ HIDE SURVEILLANCE'}{Object.keys(flagged).length ? ` · ${(rows ?? []).filter(r => flagged[r.symbol]).length}` : ''}</Chip>
        </div>
        {(() => {   // industries: medians across every company read (not just the filtered rows)
          const med = median
          const groups = new Map<string, ScreenRow[]>()
          for (const r of rows) if (r.industry) groups.set(r.industry, [...(groups.get(r.industry) ?? []), r])
          const ind = [...groups.entries()].filter(([, v]) => v.length >= 3).map(([k, v]) => ({
            industry: k, n: v.length, mcap: v.reduce((a, r) => a + (r.mcap ?? 0), 0),
            pe: med(v.map(r => r.pe ?? NaN)), pb: med(v.map(r => r.pb ?? NaN)),
            rev: med(v.map(r => r.revenue_yoy ?? NaN)), pat: med(v.map(r => r.pat_yoy ?? NaN)), margin: med(v.map(r => r.pat_margin ?? NaN)) }))
          if (!ind.length) return null
          const icols: Column<(typeof ind)[number]>[] = [
            { key: 'industry', label: 'Industry', sort: r => r.industry, render: r => <span role="button" onClick={() => { setPreset(''); setF({ ...f, industry: f.industry === r.industry ? '' : r.industry }) }}
                style={{ color: f.industry === r.industry ? T.amber : T.text, cursor: 'pointer' }}>{r.industry}</span> },
            { key: 'n', label: 'Cos', align: 'right', sort: r => r.n, render: r => <span style={{ color: T.dim }}>{r.n}</span> },
            { key: 'mcap', label: 'Mcap ₹ cr', align: 'right', sort: r => r.mcap, render: r => <span style={{ color: T.muted }}>{crs(r.mcap)}</span> },
            { key: 'pe', label: 'Median P/E', align: 'right', sort: r => r.pe ?? 1e9, render: r => r.pe == null ? '—' : `${fmtFixed(r.pe, 1)}×` },
            { key: 'pb', label: 'Median P/B', align: 'right', sort: r => r.pb ?? 1e9, render: r => r.pb == null ? '—' : `${fmtFixed(r.pb, 1)}×` },
            { key: 'rev', label: 'Median rev YoY', align: 'right', sort: r => r.rev ?? -999, render: r => g(r.rev) },
            { key: 'pat', label: 'Median profit YoY', align: 'right', sort: r => r.pat ?? -999, render: r => g(r.pat) },
            { key: 'mg', label: 'Median margin', align: 'right', sort: r => r.margin ?? -999, render: r => r.margin == null ? '—' : <span style={{ color: T.muted }}>{fmtFixed(r.margin, 1)}%</span> },
          ]
          return (
            <Panel source={undatedSource('NSE results filings', 'latest quarter per company')} badge="arithmetic" title="Industries" accent={T.cyan} pad={0} style={{ marginBottom: 10 }}
              subtitle={`${ind.length} industries with ≥ 3 companies read · medians of the latest quarter · click one to filter the list below`}>
              <DataTable columns={icols} rows={ind} rowKey={r => r.industry} dense maxHeight={260} initialSort={{ key: 'mcap', dir: 'desc' }} exportName="fund-industries" />
            </Panel>
          )
        })()}
        <Panel source={undatedSource('NSE results filings', 'latest quarter per company')} title={`${shown.length} matches`} accent={T.green} pad={0}
          right={<div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            {picked.length > 0 && <span role="button" onClick={() => setPicked([])} style={{ fontSize: 10, color: T.dim, cursor: 'pointer' }}>clear</span>}
            <Chip color={T.green} active={picked.length >= 2} onClick={picked.length >= 2 ? compare : undefined}
              title={picked.length >= 2 ? `open ${picked.join(', ')} in COMP` : 'tick 2–8 rows to compare'}>COMPARE {picked.length || ''}</Chip>
          </div>}
          subtitle={`of ${rows.length} · ${reported} have reported ${latestQ ? qn(latestQ) : 'the latest quarter'}; amber = still on an older quarter · hover a ticker for the quote`}>
          <DataTable columns={cols} rows={shown} rowKey={r => r.symbol} dense maxHeight={620} initialSort={{ key: 'mcap', dir: 'desc' }} exportName="fund" />
        </Panel>
        <div style={{ fontSize: 10.5, color: T.dim, marginTop: 8, lineHeight: 1.6 }}>
          A screen, not a signal. RSCH › earnings-growth drift tested the idea behind GROWTH presets: strong reported growth beat comparable stocks by ≈ +2% over 60 sessions only in the last 15 months (PROMISING, not proven; selection bias).
          Coverage grows as companies are opened (FA), report results, or in the Saturday sweep. Growth compares the latest
          quarter with the same quarter a year earlier (consolidated where filed); EPS-based ratios are avoided because NSE
          EPS is not adjusted for bonuses / splits.
        </div>
      </>}
    </div>
  )
}
