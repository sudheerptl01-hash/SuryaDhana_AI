'use client'

/**
 * BRKR › the day's broker budget — who spent it, and what is left.
 *
 * Why it exists: the BRKR chip's hover said "The BRKR page shows which caller spent the quota" and the BRKR
 * page showed no such thing (F12). `/api/positions/breeze-budget` has carried `by_caller`, `by_method`,
 * `remaining_day` and `refused_today` all along with no reader anywhere in `ui/`, so a chip that sent the
 * owner here to find a cause sent them to a page that could not give one.
 *
 * It reads only that endpoint, which is credential-free: counters and quotas, never a url, key or token. It
 * never touches `/api/positions/connection-status`, whose payload embeds the API key in `login_url`.
 *
 * Facts only: calls made, quota, and what remains. No advice, no colour on a number that is merely large —
 * amber is reserved for a caller over its own quota and for refusals, which mean something asked for data and
 * got none.
 */
import { useEffect, useState } from 'react'

import { T } from '@/components/terminal'

type Budget = {
  used_day?: number | null; cap_day?: number | null; remaining_day?: number | null
  used_minute?: number | null; cap_minute?: number | null
  refused_today?: number | null; errors_today?: number | null
  by_caller?: Record<string, number> | null
  quotas?: Record<string, number> | null
  day_ist?: string | null
  last_call?: { at?: string | null; caller?: string | null; method?: string | null; ok?: boolean | null } | null
}

const POLL_MS = 60_000

export function BudgetPanel() {
  const [b, setB] = useState<Budget | null>(null)
  const [err, setErr] = useState(false)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const r = await fetch('/api/positions/breeze-budget', { cache: 'no-store' })
        if (!alive) return
        if (!r.ok) { setErr(true); return }
        setB((await r.json()) as Budget)
        setErr(false)
      } catch { if (alive) setErr(true) }
    }
    tick()
    const iv = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  if (err) return <div style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>Broker budget unavailable.</div>
  if (!b) return null

  const callers = Object.entries(b.by_caller ?? {}).sort((x, y) => y[1] - x[1])
  const quotas = b.quotas ?? {}
  const used = b.used_day ?? 0
  const cap = b.cap_day ?? 0
  const pct = cap ? Math.round((used / cap) * 100) : null
  const refused = b.refused_today ?? 0

  return (
    <div style={{ fontFamily: T.mono, fontSize: 11 }}>
      <div style={{ fontSize: 10, letterSpacing: 1.2, color: T.muted, marginBottom: 6 }}>
        BROKER BUDGET{b.day_ist ? ` · ${b.day_ist}` : ''}
      </div>
      <div style={{ marginBottom: 6 }}>
        <b style={{ color: T.text }}>{used}</b> of {cap} calls today
        {pct == null ? '' : ` (${pct}%)`} · <b style={{ color: T.text }}>{b.remaining_day ?? '—'}</b> left
        {b.used_minute == null ? '' : ` · ${b.used_minute}/${b.cap_minute} this minute`}
      </div>
      {refused > 0 && (
        <div style={{ color: T.amber, marginBottom: 6 }}>
          {refused} call{refused === 1 ? '' : 's'} refused today — something asked for data and got none.
        </div>
      )}
      {/* F13: failures were counted by the ledger and shown nowhere here, although this is the page the chip
          sends the owner to when it says "N ERR". A refusal and a failure are different facts: refused means
          the budget said no, failed means ICICI did. */}
      {(b.errors_today ?? 0) > 0 && (
        <div style={{ color: T.muted, marginBottom: 6 }}>
          {b.errors_today} broker call{b.errors_today === 1 ? '' : 's'} failed today (all methods).
        </div>
      )}
      {callers.length === 0 ? (
        <div style={{ color: T.dim }}>No broker calls recorded today.</div>
      ) : (
        <table style={{ borderCollapse: 'collapse', width: '100%' }} data-brkr-budget>
          <thead>
            <tr style={{ color: T.muted, fontSize: 10, letterSpacing: 1 }}>
              <th style={{ textAlign: 'left', padding: '2px 8px 2px 0' }}>CALLER</th>
              <th style={{ textAlign: 'right', padding: '2px 8px' }}>CALLS</th>
              <th style={{ textAlign: 'right', padding: '2px 0' }}>QUOTA</th>
            </tr>
          </thead>
          <tbody>
            {callers.map(([name, n]) => {
              const q = quotas[name]
              // amber only when a caller is over ITS OWN quota — a big number under quota is not a problem
              const over = q != null && n > q
              return (
                <tr key={name}>
                  <td style={{ padding: '2px 8px 2px 0', color: T.muted }}>{name}</td>
                  <td style={{ padding: '2px 8px', textAlign: 'right', color: over ? T.amber : T.text }}>{n}</td>
                  <td style={{ padding: '2px 0', textAlign: 'right', color: T.dim }}>{q ?? '—'}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
      {b.last_call?.at && (
        <div style={{ color: T.dim, marginTop: 6 }}>
          last: {b.last_call.caller} · {b.last_call.method} · {b.last_call.at.slice(11, 19)}
          {/* truthy, not `=== false`: the API may send 0/1 rather than a JSON boolean, and a strict
              comparison would silently call a failed call successful */}
          {b.last_call.ok ? '' : ' · failed'}
        </div>
      )}
    </div>
  )
}
