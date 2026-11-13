'use client'

import { apiError } from '@/lib/errors'
/**
 * Risk profile of a basket (the Desk's momentum watchlist, your watchlist): equal-weight volatility, beta to NIFTY,
 * max drawdown and average pairwise correlation over the trailing year, industry concentration against the Desk's
 * 40% cap (with the names the cap cannot see because their industry is unknown), and per-stock vol / beta / drawdown.
 * Backward-looking description of the basket, not a forecast of the Desk's returns.
 */
import { useEffect, useMemo, useState } from 'react'
import { getBasketRisk, type BasketRisk as Data, type BasketStock } from '@/lib/api'
import { DataTable, Panel, T, TickerLink, fmtPct, type Column, sourceOf } from '@/components/terminal'

const f0 = (v: number | null | undefined, d = 0) => (v == null ? '—' : v.toFixed(d))

function Fact({ label, value, sub, color = T.text }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ padding: '8px 10px', borderRight: `1px solid ${T.border}`, minWidth: 0 }}>
      <div style={{ fontSize: 10, color: T.muted, letterSpacing: 1 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 17, fontWeight: 700, color, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: T.dim, marginTop: 1 }}>{sub}</div>}
    </div>
  )
}

export function BasketRisk({ symbols, industries, capPct = 40, title = 'Watchlist risk', weights }: {
  symbols: string[]; industries?: Record<string, string>; capPct?: number; title?: string
  /** e.g. holding values: makes the basket value-weighted (default equal weight) */
  weights?: Record<string, number>
}) {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)
  const key = symbols.join(',') + '|' + (weights ? symbols.map(s => Math.round(weights[s] ?? 0)).join(',') : '')
  useEffect(() => {
    if (!symbols.length) return
    setData(null)
    getBasketRisk(symbols, 365, weights ? symbols.map(s => weights[s] ?? 0) : undefined)
      .then(r => setData(r.data)).catch(e => setError(apiError(e, 'unavailable')))
  }, [key])  // eslint-disable-line react-hooks/exhaustive-deps

  const conc = useMemo(() => {
    if (!industries) return []
    const m = new Map<string, number>()
    for (const s of symbols) { const k = industries[s] || 'Unknown'; m.set(k, (m.get(k) ?? 0) + 1) }
    return [...m.entries()].sort((a, b) => (a[0] === 'Unknown' ? 1 : b[0] === 'Unknown' ? -1 : b[1] - a[1]))
  }, [symbols, industries])
  const capN = Math.floor(symbols.length * capPct / 100)
  const unknown = conc.find(c => c[0] === 'Unknown')?.[1] ?? 0
  const b = data?.basket, n = data?.nifty

  const cols: Column<BasketStock>[] = [
    { key: 's', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'v', label: 'Vol', align: 'right', sort: r => r.vol ?? -1, render: r => <span style={{ color: (r.vol ?? 0) > 50 ? T.amber : T.text }}>{f0(r.vol)}%</span> },
    { key: 'b', label: 'Beta', align: 'right', sort: r => r.beta ?? -9, render: r => <span style={{ color: T.text }}>{f0(r.beta, 2)}</span> },
    { key: 'r', label: '1y', align: 'right', sort: r => r.ret ?? -999, render: r => <span style={{ color: (r.ret ?? 0) >= 0 ? T.green : T.red }}>{fmtPct(r.ret, 0)}</span> },
    { key: 'd', label: 'Max DD', align: 'right', sort: r => r.max_dd ?? 0, render: r => <span style={{ color: T.red }}>{fmtPct(r.max_dd, 0)}</span> },
  ]

  return (
    <Panel source={sourceOf(data?.window.end ?? null, { source: 'NSE closes (DuckDB)', hint: error })} badge="arithmetic" title={title} accent={T.violet} pad={0}
      subtitle={data?.window.start ? `${data.basket?.weighting === 'value' ? 'weighted by holding value' : 'equal weight'} · ${data.window.start} → ${data.window.end} · split-adjusted · describes the basket, not a forecast` : 'trailing year'}>
      {error && <div style={{ padding: 10, fontSize: 11, color: T.red }}>{error}</div>}
      {!data && !error && <div style={{ padding: 10, fontSize: 11, color: T.dim }}>Computing…</div>}
      {b && n && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(118px, 1fr))', borderBottom: `1px solid ${T.border}` }}>
          <Fact label="Volatility" value={`${f0(b.vol)}%`} sub={`NIFTY ${f0(n.vol)}% · stocks avg ${f0(b.avg_stock_vol)}%`} color={b.vol > 2 * n.vol ? T.amber : T.text} />
          <Fact label="Beta to NIFTY" value={f0(b.beta, 2)} sub="1.0 = moves with NIFTY" />
          <Fact label="Max drawdown" value={fmtPct(b.max_dd, 0)} sub={`NIFTY ${fmtPct(n.max_dd, 0)}`} color={T.red} />
          <Fact label="Avg correlation" value={f0(b.avg_corr, 2)} sub={b.most_correlated ? `tightest ${b.most_correlated.a}/${b.most_correlated.b} ${b.most_correlated.corr.toFixed(2)}` : undefined} />
          <Fact label="Diversification" value={`${f0(b.diversification, 1)}×`} sub="avg stock vol ÷ basket vol" />
          {b.var95 != null && (() => {      // historical 1-day VaR / expected shortfall; in ₹ when weights are holding values
            const total = weights ? Object.values(weights).reduce((a, v) => a + (v || 0), 0) : 0
            const inr = (pct: number | null | undefined) => total > 0 && pct != null ? ` ≈ ₹${Math.round(total * pct / 100).toLocaleString('en-IN')}` : ''
            return <Fact label="1-day VaR 95%" value={`−${f0(b.var95, 1)}%${inr(b.var95)}`} color={b.var95 > 2 * (n.var95 ?? 99) ? T.amber : T.text}
              sub={`worst 5% of days average −${f0(b.es95, 1)}%${inr(b.es95)} · worst day −${f0(b.worst_day, 1)}% · NIFTY VaR −${f0(n.var95, 1)}%`} />
          })()}
        </div>
      )}
      {conc.length > 0 && (
        <div style={{ padding: '8px 10px', borderBottom: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 10, color: T.muted, letterSpacing: 1, marginBottom: 6 }}>
            INDUSTRY CONCENTRATION · Desk cap {capPct}% = {capN} of {symbols.length}
          </div>
          {conc.map(([ind, k]) => (
            <div key={ind} style={{ display: 'grid', gridTemplateColumns: '170px 1fr 26px', gap: 8, alignItems: 'center', fontSize: 11, marginBottom: 3 }}>
              <span style={{ color: ind === 'Unknown' ? T.amber : T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ind}</span>
              <span style={{ position: 'relative', height: 8, background: T.border }}>
                <span style={{ position: 'absolute', left: 0, top: 0, height: 8, width: `${(k / symbols.length) * 100}%`,
                               background: ind === 'Unknown' ? T.amber : k > capN ? T.red : T.violet }} />
                <span style={{ position: 'absolute', left: `${capPct}%`, top: -2, width: 1, height: 12, background: T.red }} title={`${capPct}% cap`} />
              </span>
              <span style={{ color: T.muted, textAlign: 'right' }}>{k}</span>
            </div>
          ))}
          {unknown > 0 && (
            <div style={{ fontSize: 10, color: T.amber, marginTop: 4 }}>
              {unknown} name{unknown > 1 ? 's have' : ' has'} no NSE industry in the reference list, so the {capPct}% cap cannot count {unknown > 1 ? 'them' : 'it'} (decision pending: see the improvement log).
            </div>
          )}
        </div>
      )}
      {data && <DataTable columns={cols} rows={data.stocks} rowKey={r => r.symbol} dense maxHeight={300} initialSort={{ key: 'v', dir: 'desc' }} />}
    </Panel>
  )
}
