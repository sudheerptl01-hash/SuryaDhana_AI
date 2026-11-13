'use client'

/**
 * Header chips of the risk cockpit (risk/SPEC.md §3 + wave-B T-17), mounted by MarketCommandHeader:
 *
 *  - STAND DOWN chip: after the owner ACKNOWLEDGEs the banner, a persistent red-outline chip for the rest of
 *    the session (resets at the next session's 09:15 IST); click → RSK › DISCIPLINE.
 *  - amber pre-stage chip (no banner): `DISCIPLINE · −1.2 % of 2.0 % cap · 4 of 5 trades` once the warn
 *    thresholds are crossed; click → RSK › DISCIPLINE.
 *  - T-17 net-Greeks chip, OMON / OSTR only: net Δ ₹/1 % and Θ ₹/day of the PAPER F&O book from
 *    GET /api/risk/fo totals (arithmetic on the open legs — no claim about the future); click → RSK.
 *    Hidden while the book is empty or the route is not deployed.
 *
 * All chips are the owner's own numbers and rules reported back — no direction words, no advice.
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import client from '@/lib/api'
import { goToPage } from '@/lib/navigate'
import { T } from '@/components/news/format'
import { inr, resetDateOf } from './disciplineModel'
import { navigateToDiscipline, useDiscipline, useStandDownState } from './useDiscipline'

const chipStyle = (color: string): CSSProperties => ({
  display: 'inline-flex', alignItems: 'center', gap: 5, fontFamily: T.mono, fontSize: 9, letterSpacing: 1,
  color, border: `1px solid ${color}`, padding: '2px 6px', whiteSpace: 'nowrap', background: 'transparent',
  cursor: 'pointer', lineHeight: 1.3,
})

function StandDownChip() {
  const { chip, record } = useStandDownState()
  if (!chip || !record) return null
  return (
    <button type="button" data-sd-standdown-chip onClick={navigateToDiscipline}
      title={`${record.detail} — your rule, set in RSK › DISCIPLINE · resets at the next session open (09:15 IST, ${resetDateOf(record.session)})`}
      style={chipStyle(T.red)}>
      STAND DOWN
    </button>
  )
}

function DisciplineAmberChip() {
  const d = useDiscipline()
  if (d.tripped || !d.settings?.enabled || !d.ev.amberChip) return null
  return (
    <button type="button" data-sd-discipline-chip onClick={navigateToDiscipline}
      title="Your own warn thresholds (RSK › DISCIPLINE) — a house rule; describes your own limits, does not predict"
      style={chipStyle(T.amber)}>
      {d.ev.amberChip}
    </button>
  )
}

// ── T-17: net Δ/Θ of the paper book, OMON/OSTR only ─────────────────────────────────────────────────────────

interface FoTotals { delta_inr_per_1pct: number | null; theta_day: number | null; open: number }

const GREEKS_POLL_MS = 120_000

function NetGreeksChip() {
  const [t, setT] = useState<FoTotals | null>(null)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    let timer: ReturnType<typeof setInterval> | null = null
    const read = async () => {
      try {
        if (document.visibilityState === 'hidden') return
        const r = await client.get('/api/risk/fo', { params: { margin: false }, timeout: 30_000 })
        if (!alive.current) return
        const d = r.data as { empty?: boolean; open_positions?: number; greeks?: { total?: { delta_inr_per_1pct?: number; theta_day?: number } } }
        if (d?.empty || !d?.greeks?.total) { setT(null); return }
        setT({ delta_inr_per_1pct: d.greeks.total.delta_inr_per_1pct ?? null, theta_day: d.greeks.total.theta_day ?? null, open: d.open_positions ?? 0 })
      } catch { if (alive.current) setT(null) }
    }
    void read()
    timer = setInterval(() => { void read() }, GREEKS_POLL_MS)
    return () => { alive.current = false; if (timer) clearInterval(timer) }
  }, [])
  if (!t) return null
  return (
    <button type="button" data-sd-netgreeks-chip onClick={() => goToPage('risk')}
      title={`Net Greeks of the PAPER F&O book (${t.open} open leg(s)) — arithmetic on the open legs, marks as served by /api/risk/fo · click → RSK › F&O. PAPER ONLY.`}
      style={chipStyle(T.muted)}>
      <span style={{ color: T.violet }}>PAPER</span>
      <span>Δ {inr(t.delta_inr_per_1pct)}/1%</span>
      <span>Θ {inr(t.theta_day)}/d</span>
    </button>
  )
}

/** The header mount: STAND DOWN + amber DISCIPLINE chips everywhere; the net-Greeks chip on OMON/OSTR only. */
export function DisciplineHeaderChips({ activeTab }: { activeTab: string }) {
  const fo = activeTab === 'options' || activeTab === 'ostrategy'
  return (
    <>
      {fo && <NetGreeksChip />}
      <DisciplineAmberChip />
      <StandDownChip />
    </>
  )
}
