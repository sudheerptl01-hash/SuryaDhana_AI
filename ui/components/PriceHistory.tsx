'use client'

import { apiError } from '@/lib/errors'
/**
 * HP · historical prices for one NSE stock (Bloomberg HP): every session as traded from the NSE bhavcopy (OHLC,
 * VWAP, volume, ₹ value, trades, delivery %), the day's change on split/bonus-adjusted closes, and the ex-dates
 * inside the window, ex-dividend days (D) and the total return with dividends reinvested (Bloomberg TRA).
 * ⤓ CSV exports the table.
 */
import { useEffect, useMemo, useState } from 'react'
import { getStockActions, getStockHistory, type HistoryRow, type StockActions, type StockHistory } from '@/lib/api'
import { Chip, DataTable, ErrorBox, Loading, T, fmtPct, fmtPx, type Column, fmtNum } from '@/components/terminal'

const WINDOWS: [string, number][] = [['1M', 31], ['3M', 92], ['6M', 183], ['1Y', 366], ['3Y', 1096], ['5Y', 1827]]
const num = (v: number | null | undefined, d = 2) => fmtNum(v, d)

/** Total return with each dividend reinvested on its ex-date: Π (1 + adjusted day change + dividend ÷ previous close
 *  as traded). `rows` newest first, `divs` ex-date → ₹ per share. Exported for tests. */
export function totalReturn(rows: HistoryRow[], divs: Record<string, number>): { pct: number | null; paid: number } {
  const asc = [...rows].reverse()
  let f = 1, paid = 0
  for (let i = 1; i < asc.length; i++) {
    const d = divs[asc[i].date] ?? 0, prev = asc[i - 1].close
    if (asc[i].change_pct == null) continue
    f *= 1 + asc[i].change_pct! / 100 + (d && prev ? d / prev : 0)
    paid += d
  }
  return { pct: asc.length > 1 ? (f - 1) * 100 : null, paid }
}

const actionLabel = (k: number) => (k < 1 ? `split/bonus · price ×${k.toFixed(k < 0.1 ? 3 : 2)}` : `consolidation · price ×${k.toFixed(2)}`)

export function PriceHistory({ ticker }: { ticker: string }) {
  const [days, setDays] = useState(92)
  const [data, setData] = useState<StockHistory | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [acts, setActs] = useState<StockActions | null>(null)
  useEffect(() => {   // dividends: NSE corporate actions (DVD), up to 15 years
    let live = true
    getStockActions(ticker, Math.min(15, Math.ceil(days / 365) + 1)).then(r => { if (live) setActs(r.data) }).catch(() => { if (live) setActs(null) })
    return () => { live = false }
  }, [ticker, days])
  useEffect(() => {
    let live = true
    setData(null); setErr(null)
    getStockHistory(ticker, days).then(r => { if (live) setData(r.data) })
      .catch(e => { if (live) setErr(apiError(e, 'history unavailable')) })
    return () => { live = false }
  }, [ticker, days])
  const avgVol = useMemo(() => {
    const v = (data?.rows ?? []).map(r => r.volume).filter(x => x > 0)
    return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null
  }, [data])
  const s = data?.summary
  const divs = useMemo(() => {
    const out: Record<string, number> = {}
    for (const a of acts?.items ?? []) if (a.kind === 'dividend' && a.rs_per_share && s && a.ex_date > s.from && a.ex_date <= s.to)
      out[a.ex_date] = (out[a.ex_date] ?? 0) + a.rs_per_share
    return out
  }, [acts, s])
  const tr = useMemo(() => (data && Object.keys(divs).length ? totalReturn(data.rows, divs) : null), [data, divs])
  if (err) return <ErrorBox error={err} />
  const cols: Column<HistoryRow>[] = [
    { key: 'date', label: 'Date', sort: r => r.date, render: r => <span style={{ whiteSpace: 'nowrap', color: T.text }}>
        {new Date(`${r.date}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short', year: '2-digit' })}
        {r.action_k != null && <span title={actionLabel(r.action_k)} style={{ color: T.amber, marginLeft: 5 }}>◆</span>}
        {divs[r.date] != null && <span title={`ex-dividend ₹${divs[r.date]} per share`} style={{ color: T.green, marginLeft: 5, fontSize: 10 }}>D ₹{divs[r.date]}</span>}</span> },
    { key: 'open', label: 'Open', align: 'right', render: r => num(r.open) },
    { key: 'high', label: 'High', align: 'right', render: r => num(r.high) },
    { key: 'low', label: 'Low', align: 'right', render: r => num(r.low) },
    { key: 'close', label: 'Close', align: 'right', sort: r => r.close ?? 0, render: r => <span style={{ color: T.bright, fontWeight: 600 }}>{num(r.close)}</span> },
    { key: 'chg', label: 'Chg', align: 'right', sort: r => r.change_pct ?? -999, title: 'on split/bonus-adjusted closes',
      render: r => <span style={{ color: (r.change_pct ?? 0) > 0 ? T.green : (r.change_pct ?? 0) < 0 ? T.red : T.muted }}>{fmtPct(r.change_pct, 2)}</span> },
    { key: 'vwap', label: 'VWAP', align: 'right', render: r => <span style={{ color: T.muted }}>{num(r.vwap)}</span> },
    { key: 'vol', label: 'Volume', align: 'right', sort: r => r.volume, title: 'amber = over 2× the window average',
      render: r => <span style={{ color: avgVol && r.volume > 2 * avgVol ? T.amber : T.text }}>{r.volume.toLocaleString('en-IN')}</span> },
    { key: 'val', label: '₹ cr', align: 'right', sort: r => r.value_cr ?? 0, render: r => <span style={{ color: T.muted }}>{num(r.value_cr)}</span> },
    { key: 'trades', label: 'Trades', align: 'right', sort: r => r.trades ?? 0, render: r => <span style={{ color: T.dim }}>{r.trades?.toLocaleString('en-IN') ?? '—'}</span> },
    { key: 'deliv', label: 'Deliv %', align: 'right', sort: r => r.deliv_pct ?? -1, title: 'share of traded quantity taken for delivery (NSE)',
      render: r => <span style={{ color: s?.avg_deliv_pct != null && r.deliv_pct != null && r.deliv_pct > s.avg_deliv_pct * 1.4 ? T.green : T.muted }}>{r.deliv_pct == null ? '—' : `${r.deliv_pct.toFixed(1)}%`}</span> },
  ]
  return (
    <div style={{ fontFamily: T.mono }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontFamily: T.display, fontSize: 11, letterSpacing: 1.4, color: T.amber, marginRight: 4 }}>HP · {ticker}</span>
        {WINDOWS.map(([l, d]) => <Chip key={l} color={T.amber} active={days === d} onClick={() => setDays(d)}>{l}</Chip>)}
        {s && <span style={{ fontSize: 11, color: T.muted, marginLeft: 8 }}>
          {s.sessions} sessions · <span style={{ color: (s.return_pct ?? 0) >= 0 ? T.green : T.red }}>{fmtPct(s.return_pct, 1)}</span>
          {tr?.pct != null && <span title="dividends reinvested on each ex-date (before tax)"> · with dividends <span style={{ color: tr.pct >= 0 ? T.green : T.red }}>{fmtPct(tr.pct, 1)}</span>
            <span style={{ color: T.dim }}> (₹{fmtPx(tr.paid)}/share paid)</span></span>}
          {' '}· high {num(s.high)} · low {num(s.low)} · {s.up_days} up / {s.down_days} down
          {s.max_dd_pct != null && s.max_dd_pct < 0 && <span title={`deepest fall from a peak inside the window: ${s.dd_peak} → ${s.dd_trough} (adjusted closes)`}>
            {' '}· max drawdown <span style={{ color: T.red }}>{fmtPct(s.max_dd_pct, 1)}</span>
            {s.dd_now_pct != null && <> (now <span style={{ color: s.dd_now_pct > -5 ? T.green : T.red }}>{fmtPct(s.dd_now_pct, 1)}</span> from the peak)</>}</span>}
          {s.avg_value_cr != null && <> · avg ₹{num(s.avg_value_cr)} cr/day</>}
          {s.avg_deliv_pct != null && <> · avg delivery {s.avg_deliv_pct}%</>}
        </span>}
      </div>
      {!data ? <Loading label="price history" /> : (
        <DataTable columns={cols} rows={data.rows} rowKey={r => r.date} dense maxHeight={520} exportName={`${ticker}_HP`} />
      )}
      <div style={{ fontSize: 10, color: T.dim, marginTop: 6, lineHeight: 1.5 }}>
        NSE bhavcopy, end of day. Prices are as traded; the change, period return and high / low use split- and
        bonus-adjusted closes, so an ex-date (◆) is not a crash. D = ex-dividend (NSE corporate actions); "with dividends"
        reinvests each one on its ex-date, before tax. Green delivery % = well above the window average.
        {data && data.actions.length > 0 && <> Ex-dates here: {data.actions.map(a => `${a.date} (${actionLabel(a.k)})`).join(' · ')}.</>}
      </div>
    </div>
  )
}
