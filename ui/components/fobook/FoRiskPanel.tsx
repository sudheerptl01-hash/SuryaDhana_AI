'use client'

/**
 * RSK › F&O (Terminal v2 PLAN 2.2, review M40, W2-BOOK): the PAPER F&O book's risk beside the cash VaR —
 * Greeks exposure (₹ per 1 %, the gamma P&L of a 1 % move, Θ ₹/day, ν ₹/vol pt), the 1-day VaR by delta-gamma
 * (Δ·dS + ½Γ·dS² on each historical day of the underlyings, IV held, one day of theta) with the full Black-76
 * revaluation beside it, IV-shock and gap scenarios (instant revaluation), and SPAN margin utilisation from POST
 * /api/options/margin (BREEZE / NSE SPAN FILE / HEURISTIC, as answered). Backend: GET /api/risk/fo.
 * Every number is arithmetic on the paper book; history describes, does not predict. PAPER ONLY.
 */
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { apiError } from '@/lib/errors'
import { BadgeChip, Btn, ErrorBox, Grid, KV, Label, Loading, Notice, Panel, Stat, T, fmtInr } from '@/components/terminal'
import { getRiskFo, type RiskFo } from './api'
import { bookSource } from './PaperBook'

const pnlColor = (v: number | null | undefined) => v == null || v === 0 ? T.text : v > 0 ? T.green : T.red

export function FoRiskPanel() {
  const [data, setData] = useState<RiskFo | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const load = useCallback(() => {
    let alive = true
    setLoading(true)
    getRiskFo(true).then(r => { if (alive) { setData(r.data); setErr(null) } })
      .catch(e => { if (alive) setErr(e?.response?.status === 404 ? 'RSK › F&O is not on this ui-api yet (deploy pending)' : apiError(e)) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])
  useEffect(() => load(), [load])

  const src = bookSource(data)
  const g = data?.greeks
  const dg = data?.var?.delta_gamma, full = data?.var?.full_revaluation
  const m = data?.margin

  return (
    <Panel title="F&O · paper book risk" accent={T.violet} badge="arithmetic" source={src}
      subtitle={data ? `${data.open_positions} open leg(s) · Greeks, delta-gamma VaR, IV shocks, gaps, SPAN margin` : 'the paper F&O book'}
      right={<Btn size="sm" onClick={load}>{loading ? '…' : '↻'}</Btn>}>
      {err && <ErrorBox error={err} onRetry={load} />}
      {!data && !err && <Loading label="F&O risk" />}
      {data && data.empty && <Notice color={T.muted}>{data.message}</Notice>}
      {data && !data.empty && g && (
        <div style={{ display: 'grid', gap: 10 }} data-rsk-fo>
          <Grid cols={6}>
            <Stat big={false} label="₹ per 1 % move" value={fmtInr(g.total.delta_inr_per_1pct, 0)} sub="Δ × forward × 1 %, all underlyings together" />
            <Stat big={false} label="Γ P&L of a 1 % move" value={fmtInr(g.total.gamma_pnl_1pct_inr, 0)} sub="½·Γ·(1 % of the forward)²" />
            <Stat big={false} label="Θ per day" value={fmtInr(g.total.theta_day, 0)} sub="₹ per calendar day" />
            <Stat big={false} label="Vega" value={fmtInr(g.total.vega, 0)} sub="₹ per IV point, parallel" />
            <Stat big={false} label="VaR95 · 1d (Δ-Γ)" value={fmtInr(dg?.var95_1d_inr, 0)} accent={T.amber}
              sub={full ? `full revaluation ${fmtInr(full.var95_1d_inr, 0)} · ${dg?.sessions ?? 0} sessions` : 'needs return history'} />
            {/* the utilisation carries the MARGIN's badge: heuristic unless every underlying was answered by BREEZE (the
                12 % tier overstates ≈ 4.8×), even inside this arithmetic panel */}
            <Stat big={false} label={<span data-rsk-fo-margin-badge>Margin used {m && <BadgeChip badge={m.badge} note={m.note} />}</span>}
              value={m?.utilisation_pct != null ? `${m.utilisation_pct.toFixed(1)}%` : '—'}
              sub={m ? `${fmtInr(m.total_margin, 0)} of ${fmtInr(m.capital, 0)} · ${m.by_underlying.map(u => u.sources.join('/')).join(', ')}` : 'margin not asked'} />
          </Grid>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
            <div>
              <Label>Value at Risk · 1 day <BadgeChip badge="arithmetic" note={data.var?.note} /></Label>
              {data.var ? <KV items={[
                ['VaR95 / ES95 · delta-gamma', `${fmtInr(dg?.var95_1d_inr, 0)} / ${fmtInr(dg?.es95_1d_inr, 0)}`],
                ['VaR99 / ES99 · delta-gamma', `${fmtInr(dg?.var99_1d_inr, 0)} / ${fmtInr(dg?.es99_1d_inr, 0)}`],
                ['VaR95 / VaR99 · full revaluation', `${fmtInr(full?.var95_1d_inr, 0)} / ${fmtInr(full?.var99_1d_inr, 0)}`],
                ['Sample', `${data.var.from} → ${data.var.to} · ${data.var.covered.join(', ')}${data.var.excluded.length ? ` · excluded ${data.var.excluded.join(', ')}` : ''}`],
              ]} /> : <Notice color={T.amber}>No common return history for the book&apos;s underlyings: VaR not computed.</Notice>}
              <div style={{ fontSize: 10, color: T.dim, marginTop: 4, lineHeight: 1.5 }}>{dg?.method}. Historical simulation of the underlyings&apos; daily moves; IV is held (no IV history is replayed), so a vol spike on a down day is in the IV-shock rows, not here.</div>
            </div>
            <div>
              <Label>Scenarios · instant revaluation <BadgeChip badge="arithmetic" note={data.scenarios?.note} /></Label>
              {data.scenarios && <KV cols={2} items={[
                ...data.scenarios.gap.map(s => [`spot ${s.spot_pct > 0 ? '+' : '−'}${Math.abs(s.spot_pct)} %`, <span key={`g${s.spot_pct}`} style={{ color: pnlColor(s.pnl_inr) }}>{fmtInr(s.pnl_inr, 0)}</span>] as [string, ReactNode]),
                ...data.scenarios.iv_shock.map(s => [`IV ${s.iv_shift > 0 ? '+' : '−'}${Math.abs(s.iv_shift)} pts`, <span key={`v${s.iv_shift}`} style={{ color: pnlColor(s.pnl_inr) }}>{fmtInr(s.pnl_inr, 0)}</span>] as [string, ReactNode]),
                ...data.scenarios.combined.map(s => [`spot ${s.spot_pct > 0 ? '+' : '−'}${Math.abs(s.spot_pct)} % & IV ${s.iv_shift > 0 ? '+' : '−'}${Math.abs(s.iv_shift)}`, <span key={`c${s.spot_pct}${s.iv_shift}`} style={{ color: pnlColor(s.pnl_inr) }}>{fmtInr(s.pnl_inr, 0)}</span>] as [string, ReactNode]),
                ['one day, nothing moves', <span key="t" style={{ color: pnlColor(data.scenarios.theta_1d_inr) }}>{fmtInr(data.scenarios.theta_1d_inr, 0)}</span>],
              ]} />}
              <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{data.scenarios?.note}</div>
            </div>
          </div>
          {m && (
            <div>
              <Label>SPAN margin by underlying <BadgeChip badge={m.badge} note={m.note} /></Label>
              <KV items={m.by_underlying.map(u => [u.symbol, `${fmtInr(u.total_margin, 0)} · ${u.sources.join(' / ')}`] as [string, string])} />
              <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{m.note} · capital: {data.capital.source}</div>
            </div>
          )}
          {(data.notes ?? []).map((t, i) => <div key={i} style={{ fontSize: 10, color: T.amber }}>⚠ {t}</div>)}
          {data.marks_meta.notes.map((t, i) => <div key={`m${i}`} style={{ fontSize: 10, color: T.amber }}>⚠ {t}</div>)}
          <div style={{ fontSize: 10, color: T.dim }}>The book itself (legs, marks, close / roll): OSTR › Paper F&amp;O book. PAPER ONLY — no order route exists.</div>
        </div>
      )}
    </Panel>
  )
}
