'use client'

/**
 * Trade ticket — before you buy: shares for an amount, ICICI's real round-trip charges (itemised), the move you need
 * just to break even, an ATR stop with the rupee risk, and the tax on a +10 % gain. Arithmetic only; nothing is sent.
 */
import { useEffect, useRef, useState } from 'react'
import { getTradeTicket, type TradeTicket as Ticket } from '@/lib/api'
import { Input, T, fmtInr } from '@/components/terminal'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'

const inr = fmtInr
const KEY = 'suryadhana.ticket.v1'

interface Sizing { amount: string; mult: string; capital: string }
const DEFAULTS: Sizing = { amount: '50000', mult: '2', capital: '500000' }

/** The saved sizing over `base`: a saved field replaces the base one only when it is set (as before). */
function readSizing(base: Sizing): Sizing {
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || '{}')
    return { amount: s.amount || base.amount, mult: s.mult || base.mult, capital: s.capital || base.capital }
  } catch { return base /* defaults */ }
}

export function TradeTicket({ price, atrPct }: { price: number; atrPct: number | null }) {
  // Read before the first render (client-only: PlatformShell renders the terminal after boot), so the defaults are
  // never written over the saved sizing on mount, where another window would adopt them.
  const [initial] = useState(() => {
    let raw: string | null = null
    try { raw = localStorage.getItem(KEY) } catch { /* storage unavailable */ }
    return { raw, sizing: readSizing(DEFAULTS) }
  })
  const [amount, setAmount] = useState(initial.sizing.amount)
  const [mult, setMult] = useState(initial.sizing.mult)
  const [capital, setCapital] = useState(initial.sizing.capital)
  const [t, setT] = useState<Ticket | null>(null)
  // Multi-window (C3-02): the stored string this window last read or wrote; an equal state is never written again
  // (no echo over another window's newer write). Starts as the raw stored value, so the first save is as before.
  const stored = useRef<string | null>(initial.raw)
  const current = useRef<Sizing>(initial.sizing)
  current.current = { amount, mult, capital }
  useExternalPrefChange(KEY, () => {          // another window (or the server, via sync) changed the saved sizing
    const next = readSizing(current.current)
    stored.current = JSON.stringify(next)
    setAmount(next.amount); setMult(next.mult); setCapital(next.capital)
  })
  useEffect(() => {
    const value = Number(amount.replace(/[,₹\s]/g, '')), stop_atr = Number(mult), cap = Number(capital.replace(/[,₹\s]/g, ''))
    if (!(value > 0) || !(price > 0)) return
    const saved = JSON.stringify({ amount, mult, capital })
    if (saved !== stored.current) {
      try { localStorage.setItem(KEY, saved); stored.current = saved } catch { /* private window */ }
    }
    const id = setTimeout(() => {
      getTradeTicket({ value, price, atr_pct: atrPct, stop_atr: stop_atr > 0 ? stop_atr : 2, capital: cap > 0 ? cap : undefined })
        .then(r => setT(r.data)).catch(() => setT(null))
    }, 250)
    return () => clearTimeout(id)
  }, [amount, mult, capital, price, atrPct])

  const row = (k: string, v: React.ReactNode, c?: string) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0', borderBottom: `1px solid ${T.border}`, fontSize: 12 }}>
      <span style={{ color: T.muted }}>{k}</span><span style={{ fontFamily: T.mono, color: c ?? T.text }}>{v}</span>
    </div>
  )
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 70px 1fr', gap: 6, marginBottom: 8 }}>
        <Input label="Amount ₹" value={amount} onChange={setAmount} />
        <Input label="Stop ×ATR" value={mult} onChange={setMult} />
        <Input label="Your capital ₹" value={capital} onChange={setCapital} />
      </div>
      {!t ? <div style={{ fontSize: 11, color: T.dim }}>Enter an amount.</div> : <>
        {row('Shares', `${t.shares} × ${inr(t.price, 2)} = ${inr(t.notional)}`)}
        {row('Round trip (buy + sell)', <>{inr(t.round_trip.total, 0)} <span style={{ color: (t.round_trip_pct ?? 0) > 1 ? T.red : T.amber }}>({t.round_trip_pct?.toFixed(2)}%)</span></>)}
        <div style={{ fontSize: 10, color: T.dim, padding: '2px 0 4px' }}>
          brokerage {inr(t.round_trip.brokerage)} · STT {inr(t.round_trip.stt)} · GST {inr(t.round_trip.gst)} · DP {inr(t.round_trip.dp)} · stamp + exchange + SEBI {inr(t.round_trip.stamp + t.round_trip.exchange + t.round_trip.sebi + t.round_trip.ipft)}
        </div>
        {row('Breakeven move', `+${t.breakeven_move_pct?.toFixed(2)}%`, T.amber)}
        {t.stop && row(`Stop (${t.stop.atr_multiple}×ATR, −${t.stop.distance_pct}%)`, inr(t.stop.price, 2), T.red)}
        {t.stop && row('Loss if the stop is hit', <>{inr(t.stop.loss_if_hit)}{t.stop.loss_pct_of_capital != null && <span style={{ color: t.stop.loss_pct_of_capital > 1 ? T.red : T.muted }}> · {t.stop.loss_pct_of_capital}% of capital</span>}</>)}
        {row('Tax on a +10% gain', <>{inr(t.tax_on_10pct_gain.short_term)} <span style={{ color: T.dim }}>if sold within 1 yr · {inr(t.tax_on_10pct_gain.long_term_with_exemption)} after</span></>)}
        <div style={{ fontSize: 10, color: T.dim, marginTop: 6, lineHeight: 1.5 }}>
          {t.profile} · positions under {inr(t.min_position_for_1pct)} cost more than 1% round trip · intraday would cost {inr(t.intraday_round_trip.total)} · nothing is sent to the broker
        </div>
      </>}
    </div>
  )
}
