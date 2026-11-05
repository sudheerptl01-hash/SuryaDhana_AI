'use client'

/**
 * OVME-style pricer for one contract picked in the OMON chain: Black-76 on the chain's forward (the model behind
 * OMON's implied vols), Greeks, breakeven, chance of finishing in the money, cost per lot, and the payoff of one
 * long lot at expiry and today. IV and days are editable to ask "what if".
 */
import { useEffect, useMemo, useState } from 'react'
import { black76 } from '@/lib/black76'
import type { OptionChain } from '@/lib/api'
import { Btn, Input, Panel, T } from '@/components/terminal'

export type PricerPick = { strike: number; side: 'call' | 'put' }
const n = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }))

export function OptionPricer({ data, pick, onClose }: { data: OptionChain; pick: PricerPick; onClose: () => void }) {
  const row = data.rows.find(r => r.strike === pick.strike)
  const leg = row ? (pick.side === 'call' ? row.ce : row.pe) : null
  // OMON computes IV for out-of-the-money strikes only; put–call parity gives the same IV to both sides of a strike
  const other = row ? (pick.side === 'call' ? row.pe : row.ce) : null
  const chainIv = leg?.iv ?? other?.iv ?? data.atm_iv ?? null
  const ivSource = leg?.iv != null ? 'this contract' : other?.iv != null ? `the ${pick.side === 'call' ? 'put' : 'call'} at this strike (parity)` : 'at-the-money'
  const [ivTxt, setIvTxt] = useState(chainIv != null ? String(chainIv) : '15')
  const [daysTxt, setDaysTxt] = useState(String(Math.max(0, data.days_to_expiry) + 0.5))
  useEffect(() => { setIvTxt(chainIv != null ? String(chainIv) : '15'); setDaysTxt(String(Math.max(0, data.days_to_expiry) + 0.5)) },
    [pick.strike, pick.side, data.expiry, data.symbol])   // eslint-disable-line react-hooks/exhaustive-deps
  const F = data.forward ?? data.spot ?? 0, K = pick.strike
  const iv = Math.max(0.1, Number(ivTxt) || 0) / 100, days = Math.max(0, Number(daysTxt) || 0), yrs = days / 365
  const m = black76(pick.side, F, K, yrs, iv)
  const atChain = chainIv != null ? black76(pick.side, F, K, (Math.max(0, data.days_to_expiry) + 0.5) / 365, chainIv / 100) : null
  const mkt = leg?.price ?? null
  const premium = mkt ?? m.price
  const lot = data.lot ?? 1
  const breakeven = pick.side === 'call' ? K + premium : K - premium

  // payoff of one long lot: at expiry (intrinsic − premium) and today (model value − premium), across ±2.5σ
  const curve = useMemo(() => {
    const sd = F * Math.max(0.02, (data.atm_iv ?? iv * 100) / 100 * Math.sqrt(Math.max(yrs, 1 / 365)))
    const lo = Math.max(1, F - 2.5 * sd), hi = F + 2.5 * sd
    return Array.from({ length: 61 }, (_, i) => {
      const s = lo + (hi - lo) * i / 60
      const exp = (pick.side === 'call' ? Math.max(s - K, 0) : Math.max(K - s, 0)) - premium
      const now = black76(pick.side, s, K, yrs, iv).price - premium
      return { s, exp: exp * lot, now: now * lot }
    })
  }, [F, K, yrs, iv, premium, lot, pick.side, data.atm_iv])
  const W = 560, H = 170, pad = 6
  const ys = curve.flatMap(c => [c.exp, c.now]), ymin = Math.min(...ys), ymax = Math.max(...ys)
  const x = (s: number) => pad + (s - curve[0].s) / (curve[curve.length - 1].s - curve[0].s) * (W - 2 * pad)
  const y = (v: number) => H - pad - (v - ymin) / (ymax - ymin || 1) * (H - 2 * pad)
  const path = (k: 'exp' | 'now') => curve.map((c, i) => `${i ? 'L' : 'M'}${x(c.s).toFixed(1)},${y(c[k]).toFixed(1)}`).join('')

  const kv = (label: string, value: React.ReactNode, title?: string) => (
    <div title={title} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, padding: '3px 0', borderBottom: `1px solid ${T.border}` }}>
      <span style={{ color: T.muted }}>{label}</span><span style={{ color: T.text }}>{value}</span></div>)
  return (
    <Panel title={`Pricer · ${data.symbol} ${K} ${pick.side === 'call' ? 'CE' : 'PE'} · ${data.expiry}`} accent={T.violet} pad={10} style={{ marginBottom: 12 }}
      subtitle="Black-76 on the chain's forward, r 6.5% (the model behind OMON's IVs) · one long lot · edit IV or days to ask what-if"
      right={<Btn size="sm" onClick={onClose}>✕ CLOSE</Btn>}>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.4fr)', gap: 16, fontFamily: T.mono, fontSize: 11.5 }}>
        <div>
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <Input label="IV %" value={ivTxt} onChange={setIvTxt} width={70} />
            <Input label="Days left (+½ expiry day)" value={daysTxt} onChange={setDaysTxt} width={90} />
            <div style={{ alignSelf: 'flex-end', fontSize: 10.5, color: T.dim }}>forward {n(F)} · lot {data.lot ?? '—'} · IV from {ivSource}</div>
          </div>
          {kv('Model price', <span style={{ color: T.amber }}>₹{n(m.price)}</span>)}
          {kv('Market price', mkt != null ? `₹${n(mkt)}` : '—',
              atChain ? `the model at the chain's own IV gives ₹${n(atChain.price)}: they match by construction` : undefined)}
          {kv('Delta', n(m.delta, 3), 'change in the option price per ₹1 move in the underlying')}
          {kv('Gamma', n(m.gamma, 5), 'change in delta per ₹1 move')}
          {kv('Theta / day', <span style={{ color: T.red }}>−₹{n(Math.abs(m.thetaDay))}</span>, 'value lost per calendar day, everything else unchanged')}
          {kv('Vega / vol point', `₹${n(m.vega)}`, 'value change per 1 point of implied volatility')}
          {kv('Breakeven at expiry', n(breakeven), `strike ${pick.side === 'call' ? '+' : '−'} the premium paid`)}
          {kv('Chance to finish in the money', `${(m.probItm * 100).toFixed(0)}%`, 'risk-neutral N(d2): what the price implies, not a forecast')}
          {kv('Cost of one lot', `₹${n(premium * lot, 0)}`, 'premium × lot size, before brokerage and taxes')}
          {kv('Delta exposure per lot', `≈ ₹${n(Math.abs(m.delta) * F * lot, 0)} of the underlying`)}
        </div>
        <div>
          <svg viewBox={`0 0 ${W} ${H + 18}`} style={{ width: '100%', height: 200, display: 'block' }}>
            {ymin < 0 && ymax > 0 && <line x1={0} x2={W} y1={y(0)} y2={y(0)} stroke={T.border} />}
            <line x1={x(F)} x2={x(F)} y1={0} y2={H} stroke={T.amber} strokeDasharray="3 3" />
            <line x1={x(K)} x2={x(K)} y1={0} y2={H} stroke={T.dim} strokeDasharray="2 4" />
            <path d={path('now')} fill="none" stroke={T.cyan} strokeWidth={1.5} />
            <path d={path('exp')} fill="none" stroke={T.violet} strokeWidth={2} />
            <text x={x(F) + 4} y={12} fontSize={10} fill={T.amber}>forward {n(F, 0)}</text>
            <text x={x(K) + 4} y={H - 4} fontSize={10} fill={T.dim}>strike {n(K, 0)}</text>
            <text x={pad} y={H + 14} fontSize={10} fill={T.dim}>{n(curve[0].s, 0)}</text>
            <text x={W - pad} y={H + 14} fontSize={10} fill={T.dim} textAnchor="end">{n(curve[curve.length - 1].s, 0)}</text>
          </svg>
          <div style={{ fontSize: 10.5, color: T.muted }}>
            P&L of one long lot: <span style={{ color: T.violet }}>at expiry</span> · <span style={{ color: T.cyan }}>today ({days} days left)</span>
            {' '}· max loss ₹{n(premium * lot, 0)} (the premium) · range ±2.5 standard deviations
          </div>
        </div>
      </div>
    </Panel>
  )
}
