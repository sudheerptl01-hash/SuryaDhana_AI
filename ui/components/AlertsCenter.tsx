'use client'

import { apiError } from '@/lib/errors'
/**
 * ALRT · alerts centre: every server-side price alert (checked every minute in market hours by the scheduler,
 * even with the terminal closed) with the distance to each level, an add / edit form, the alerts that fired,
 * and the full notification inbox (morning / closing notes, moves, filings, results numbers, wraps).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getNewsQuotes, getNotificationFeed, getPriceAlerts, putPriceAlert, type AlertHitSrv, type AlertLevelsSrv, type NotificationItem } from '@/lib/api'
import { Btn, Chip, DataTable, Input, PageHeader, Panel, T, TickerLink, fmtPct, fmtPx, type Column } from '@/components/terminal'
import { unicodeMinus } from '@/lib/format'   // server-built notification text: U+2212 (C1-18)

type Row = { sym: string; lv: AlertLevelsSrv; price: number | null }
const KIND_COLOR: Record<string, string> = { price: T.amber, move: T.cyan, filing: T.violet, wrap: T.green, results: T.green, close: T.cyan, morning: T.amber }

export function AlertsCenter() {
  const [alerts, setAlerts] = useState<Record<string, AlertLevelsSrv>>({})
  const [history, setHistory] = useState<AlertHitSrv[]>([])
  const [prices, setPrices] = useState<Record<string, number | null>>({})
  const [feed, setFeed] = useState<NotificationItem[]>([])
  const [kind, setKind] = useState<string | null>(null)
  const [form, setForm] = useState({ sym: '', above: '', below: '', move: '' })
  const [msg, setMsg] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const a = (await getPriceAlerts()).data
      setAlerts(a.alerts); setHistory(a.history)
      const syms = Object.keys(a.alerts)
      if (syms.length) {
        const q = (await getNewsQuotes(syms.map(s => a.alerts[s].yahoo ?? `${s}.NS`))).data.quotes
        setPrices(Object.fromEntries(syms.map(s => [s, q[a.alerts[s].yahoo ?? `${s}.NS`]?.price ?? null])))
      }
    } catch { /* keep what is shown */ }
    getNotificationFeed(200).then(r => setFeed(r.data.items)).catch(() => {})
  }, [])
  useEffect(() => { load(); const iv = setInterval(load, 60_000); return () => clearInterval(iv) }, [load])

  const save = async (sym: string, above: number | null, below: number | null, move: number | null = null) => {
    try {
      const d = (await putPriceAlert(sym, { above, below, move })).data
      setAlerts(d.alerts); setHistory(d.history)
      setMsg(above == null && below == null && move == null ? `${sym}: alert removed` : `${sym}: alert saved`)
      load()
    } catch (e: any) { setMsg(apiError(e, 'could not save')) }
  }
  const submit = () => {
    const sym = form.sym.trim().toUpperCase().replace(/\.NS$/, '')
    const num = (v: string) => (v.trim() === '' || isNaN(Number(v)) ? null : Number(v))
    if (!/^[A-Z0-9&-]{1,20}$/.test(sym)) { setMsg('enter an NSE symbol'); return }
    if (num(form.above) == null && num(form.below) == null && num(form.move) == null) { setMsg('set a level above, below, or a ± % move'); return }
    save(sym, num(form.above), num(form.below), num(form.move)); setForm({ sym: '', above: '', below: '', move: '' })
  }

  const rows: Row[] = Object.entries(alerts).map(([sym, lv]) => ({ sym, lv, price: prices[sym] ?? null }))
  const dist = (r: Row, lv?: number) => (lv != null && r.price ? (lv / r.price - 1) * 100 : null)
  const cols: Column<Row>[] = [
    { key: 'sym', label: 'Stock', sort: r => r.sym, render: r => <TickerLink symbol={r.sym} /> },
    { key: 'price', label: 'Last', align: 'right', sort: r => r.price ?? -1, render: r => fmtPx(r.price) },
    { key: 'above', label: 'Above', align: 'right', render: r => r.lv.above == null ? <span style={{ color: T.dim }}>—</span>
        : <span><span style={{ color: T.green }}>{r.lv.above.toLocaleString('en-IN')}</span> <span style={{ color: T.dim, fontSize: 10 }}>{fmtPct(dist(r, r.lv.above), 1)}</span></span> },
    { key: 'below', label: 'Below', align: 'right', render: r => r.lv.below == null ? <span style={{ color: T.dim }}>—</span>
        : <span><span style={{ color: T.red }}>{r.lv.below.toLocaleString('en-IN')}</span> <span style={{ color: T.dim, fontSize: 10 }}>{fmtPct(dist(r, r.lv.below), 1)}</span></span> },
    { key: 'move', label: 'Move ±', align: 'right', render: r => r.lv.move == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: T.cyan }} title="fires when today's change vs the official previous close reaches this size, up or down">±{r.lv.move}%</span> },
    { key: 'near', label: 'Nearest level', align: 'right', sort: r => Math.min(...[dist(r, r.lv.above), dist(r, r.lv.below)].filter((x): x is number => x != null).map(Math.abs), 999),
      render: r => { const d = [dist(r, r.lv.above), dist(r, r.lv.below)].filter((x): x is number => x != null).map(Math.abs)
        if (!d.length) return '—'; const m = Math.min(...d)
        return <span style={{ color: m < 2 ? T.amber : T.muted, fontWeight: m < 2 ? 700 : 400 }}>{m.toFixed(1)}% away</span> } },
    { key: 'x', label: '', render: r => <span role="button" onClick={e => { e.stopPropagation(); save(r.sym, null, null) }}
        style={{ color: T.dim, cursor: 'pointer', fontSize: 10 }} title="remove this alert">✕ remove</span> },
  ]
  const kinds = useMemo(() => [...new Set(feed.map(f => f.kind))], [feed])
  const shownFeed = feed.filter(f => !kind || f.kind === kind)

  return (
    <div>
      <PageHeader code="ALRT" title="Alerts"
        subtitle="price alerts checked every minute in market hours by the scheduler (terminal can be closed) · notifications inbox" />
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)', gap: 12, alignItems: 'start' }}>
        <Panel title={`Price alerts · ${rows.length}`} accent={T.amber} pad={0}
          subtitle="green = fires when the price rises through it · red = when it falls through it · cyan = a ± % day move · one-shot: a fired level is cleared">
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: 10, borderBottom: `1px solid ${T.border}`, flexWrap: 'wrap' }}>
            <Input label="Stock" value={form.sym} onChange={v => setForm({ ...form, sym: v })} placeholder="TCS" width={100} />
            <Input label="Above ₹" value={form.above} onChange={v => setForm({ ...form, above: v })} width={90} />
            <Input label="Below ₹" value={form.below} onChange={v => setForm({ ...form, below: v })} width={90} />
            <Input label="Move ±%" value={form.move} onChange={v => setForm({ ...form, move: v })} width={80} />
            <Btn size="sm" onClick={submit}>＋ SET ALERT</Btn>
            {msg && <span style={{ fontSize: 10.5, color: T.muted }}>{msg}</span>}
          </div>
          <DataTable columns={cols} rows={rows} rowKey={r => r.sym} dense empty="No price alerts. Set one above, or with the bell in the Alert column on WTCH." initialSort={{ key: 'near', dir: 'asc' }} />
        </Panel>
        <Panel title={`Fired · ${history.length}`} accent={T.green} pad={0} subtitle="price alerts that triggered (newest first)">
          {/* the server keeps history newest first */}
          <DataTable<AlertHitSrv> dense maxHeight={360} rowKey={(h, i) => `${h.sym}-${h.at}-${i}`} rows={history}
            empty="Nothing has fired yet."
            columns={[
              { key: 'at', label: 'When', render: h => <span style={{ color: T.dim }}>{h.at.replace('T', ' ').slice(0, 16)}</span> },
              { key: 'sym', label: 'Stock', render: h => <TickerLink symbol={h.sym} /> },
              { key: 'side', label: 'Level', render: h => h.side === 'move'
                  ? <span style={{ color: T.cyan }}>move ±{h.level}% <span style={{ color: (h.change_pct ?? 0) >= 0 ? T.green : T.red }}>({fmtPct(h.change_pct, 2)})</span></span>
                  : <span style={{ color: h.side === 'above' ? T.green : T.red }}>{h.side} {h.level.toLocaleString('en-IN')}</span> },
              { key: 'price', label: 'Price', align: 'right', render: h => fmtPx(h.price) },
            ]} />
        </Panel>
      </div>
      <Panel title={`Inbox · ${shownFeed.length}`} accent={T.cyan} pad={0} style={{ marginTop: 12 }}
        subtitle="everything the scheduler told you (Mac notifications + Telegram when set up)"
        right={<div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          <Chip color={T.muted} active={!kind} onClick={() => setKind(null)}>ALL</Chip>
          {kinds.map(k => <Chip key={k} color={KIND_COLOR[k] ?? T.muted} active={kind === k} onClick={() => setKind(kind === k ? null : k)}>{k.toUpperCase()}</Chip>)}
        </div>}>
        <DataTable<NotificationItem> dense maxHeight={480} rowKey={(n, i) => `${n.at}-${i}`} rows={shownFeed} empty="No notifications yet."
          columns={[
            { key: 'at', label: 'When', render: n => <span style={{ color: T.dim, whiteSpace: 'nowrap' }}>{n.at.replace('T', ' ').slice(0, 16)}</span> },
            { key: 'kind', label: 'Kind', render: n => <span style={{ color: KIND_COLOR[n.kind] ?? T.muted, fontSize: 10, letterSpacing: 0.8 }}>{n.kind.toUpperCase()}</span> },
            { key: 'body', label: 'Message', render: n => <span style={{ color: T.text, whiteSpace: 'normal', lineHeight: 1.45, display: 'inline-block', maxWidth: 1100 }}>
                <span style={{ color: T.muted }}>{n.title.replace('SuryaDhana · ', '')}: </span>{unicodeMinus(String(n.body ?? ''))}</span> },
          ]} />
      </Panel>
    </div>
  )
}
