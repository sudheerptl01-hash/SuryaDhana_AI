'use client'

/**
 * ph.ladder — the India price stack (PLAN a.7): COMEX $/oz → × USD/INR → landed ₹/10 g → + duty 15 % (dated) →
 * duty-paid landed → IBJA 999 PM (premium) → MCX front settle (basis, carry), one bar per step with the step's CLOCK
 * underneath ("now · …" for the live legs, "PM fix · Tue 03 Nov" for IBJA, "Tue 03 Nov settlement" for MCX) and its
 * source. The duty bar prints the rate and the notification on every render (R5); the 995/999 adjustment is stated.
 *
 * Clock rules (wave 1c — C-TRADER-4, C-BEGINNER-2, C-BEGINNER-5, C-DATA-11): the premium printed is the STORED
 * same-minute value for the IBJA date (INDIA_PREMIUM_PCT), printed once with its date; the basis carries the clock it
 * was computed at (the settlement session); nothing here divides a live leg by a fixed one. The [B] line says which
 * bars are "now" and which are yesterday's, and not to divide across them. Arithmetic badge on the ladder; the premium
 * itself is context.
 */
import { CHART_BOX, T, useChartSize } from '@/components/terminal'
import type { LadderStep } from '@/lib/gold/types'
import { dateLabel, inr, istLabel, ladderClock, ladderTsLabel, num, orderLadder, signedPct, usd } from './goldViewModel'

const STEP_TEXT: Record<string, string> = {
  comex: 'COMEX $/oz', usdinr: '× USD/INR', landed: 'landed ₹/10 g', duty: '+ duty', duty_paid: 'duty-paid landed', ibja: 'IBJA 999 PM', mcx: 'MCX front settle',
}

function fmtStep(s: LadderStep): string {
  const k = s.step.toLowerCase()
  if (k.startsWith('comex')) return usd(s.value, 1)
  if (k.startsWith('usdinr')) return num(s.value, 2)
  if (k.startsWith('duty') && !k.startsWith('duty_paid')) return s.value == null ? '—' : `${num(s.value, 0)} %`
  return inr(s.value, 0)
}

export interface PriceLadderProps {
  steps: LadderStep[]
  duty: { pct: number; effective: string; notification?: string | null }
  /** the stored fix-minute premium for the IBJA date (never a cross-clock division); null → "pending" with the reason */
  premium: { value: number; date: string } | null
  /** why the premium is not printed (no stored row for the IBJA date yet) */
  premiumPending?: string | null
  basisPct: number | null
  /** the clock the basis was computed at, e.g. "at the Tue 03 Nov settlement vs that session's duty-paid" */
  basisClock?: string | null
  carryAdjPct?: number | null
  tips: (k: string) => string | undefined
}

export function PriceLadder({ steps, duty, premium, premiumPending, basisPct, basisClock, carryAdjPct, tips }: PriceLadderProps) {
  const ordered = orderLadder(steps)
  const { ref, w } = useChartSize(720, 150, { minRatio: 1, maxRatio: 1 })
  const rupee = ordered.filter(s => /^(landed|duty_paid|ibja|mcx)/.test(s.step.toLowerCase()) && s.value != null)
  const maxR = Math.max(1, ...rupee.map(s => s.value as number))
  const n = Math.max(1, ordered.length)
  const colW = w / n
  const barMaxH = 70
  const h = 150
  const liveSteps = ordered.filter(s => ladderClock(s) === 'now').map(s => STEP_TEXT[s.step.toLowerCase().split(/[^a-z_]/)[0]] ?? s.label)
  const ibja = ordered.find(s => ladderClock(s) === 'fix')
  const mcx = ordered.find(s => ladderClock(s) === 'settlement')
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label="India price ladder">
        {ordered.map((s, i) => {
          const k = s.step.toLowerCase()
          const isRupee = /^(landed|duty_paid|ibja|mcx)/.test(k)
          const bh = isRupee && s.value != null ? Math.max(4, ((s.value as number) / maxR) * barMaxH) : k.startsWith('duty') ? 14 : 24
          const x = i * colW + 6, bw = colW - 12
          const fill = k.startsWith('mcx') ? T.amber : k.startsWith('ibja') ? T.violet : k.startsWith('duty') ? T.cyan : k.startsWith('comex') || k.startsWith('usdinr') ? T.borderHi : T.muted
          const tipKey = k.startsWith('comex') ? 'landed' : k.startsWith('usdinr') ? 'usdinr' : k.startsWith('duty_paid') ? 'duty_paid_landed' : k.startsWith('duty') ? 'duty_rate' : k.startsWith('ibja') ? 'ibja_999' : k.startsWith('mcx') ? 'mcx_basis_pct' : 'landed'
          const clock = ladderClock(s)
          return (
            <g key={s.step} data-ladder-step={s.step} data-ladder-clock={clock}>
              <title>{tips(tipKey) ?? STEP_TEXT[k.split(/[^a-z_]/)[0]] ?? s.step}</title>
              <rect x={x} y={14 + barMaxH - bh} width={bw} height={bh} fill={fill} opacity={clock === 'now' ? 0.85 : 0.6} />
              <text x={x + bw / 2} y={14 + barMaxH - bh - 4} textAnchor="middle" fontSize={10.5} fontFamily={T.mono} fill={T.bright}>{fmtStep(s)}</text>
              <text x={x + bw / 2} y={14 + barMaxH + 14} textAnchor="middle" fontSize={9.5} fontFamily={T.mono} fill={T.text}>{STEP_TEXT[k.split(/[^a-z_]/)[0]] ?? s.step}</text>
              <text x={x + bw / 2} y={14 + barMaxH + 26} textAnchor="middle" fontSize={8.5} fontFamily={T.mono} fill={clock === 'now' ? T.cyan : T.dim}>{ladderTsLabel(s)}</text>
              <text x={x + bw / 2} y={14 + barMaxH + 37} textAnchor="middle" fontSize={8.5} fontFamily={T.mono} fill={T.dim}>{s.source ?? ''}</text>
              {i < ordered.length - 1 && <text x={(i + 1) * colW} y={14 + barMaxH / 2} textAnchor="middle" fontSize={11} fill={T.dim}>→</text>}
            </g>
          )
        })}
      </svg>
      <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 10.5, color: T.text, marginTop: 2 }}>
        <span title={tips('duty_rate')} data-duty-line>duty <b style={{ color: T.cyan }}>{num(duty.pct, 0)} %</b> since {dateLabel(duty.effective)}{duty.notification ? ` · ${duty.notification}` : ''} · <span style={{ color: T.amber }}>confirm at CBIC (O-3)</span></span>
        <span title={tips('india_premium_pct')} data-ladder-premium={premium ? 'stored' : 'pending'}>
          IBJA premium vs duty-paid{' '}
          {premium
            ? <><b style={{ color: T.text }}>{signedPct(premium.value)}</b> <span style={{ color: T.muted }}>· {istLabel(premium.date)}, both legs at the IBJA fix minute (stored)</span></>
            : <span style={{ color: T.muted }}>— {premiumPending ?? 'the stored fix-minute premium for this IBJA date is not in yet (18:10 job)'}</span>}
        </span>
        <span title={tips('mcx_basis_pct')} data-ladder-basis>MCX basis <b style={{ color: T.text }}>{signedPct(basisPct)}</b>{basisClock && basisPct != null ? <span style={{ color: T.muted }}> · {basisClock}</span> : null}{carryAdjPct != null && <span style={{ color: T.muted }}> · carry-adjusted {signedPct(carryAdjPct)}</span>}</span>
        <span style={{ color: T.dim }} title={tips('landed_999_vs_995')}>999 ÷ 995 = 1.00402 applied where the purities differ</span>
      </div>
      <div data-ladder-clock-line style={{ fontSize: 10, color: T.muted, marginTop: 4, lineHeight: 1.5 }}>
        <span style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1, color: T.cyan, marginRight: 6 }}>[B]</span>
        {liveSteps.length ? <>the {liveSteps.length} bars on the left ({liveSteps.join(', ')}) are <b style={{ color: T.cyan }}>now</b>; </> : null}
        {ibja ? <>IBJA is its PM fix of {ibja.ts ? istLabel(ibja.ts) : '—'}; </> : null}
        {mcx ? <>MCX is the {mcx.ts && !/^\d{4}-/.test(mcx.ts) ? mcx.ts : mcx.ts ? `${istLabel(mcx.ts)} settlement` : 'last settlement'}</> : null}
        {' '}— do not divide across clocks: a premium or basis read between a live bar and a fixed one is clock error, not demand (G-INDIA §5.3).
      </div>
    </div>
  )
}
