'use client'

/**
 * BRKR — the broker-session chip in the header (F7-05, 14 Nov 2026).
 *
 * Why it exists: on 14 Nov the Breeze ledger held 121 `generate_session` calls of which every one failed, and the
 * `errors_today` the API already served had ZERO readers in `ui/`. A dead broker session therefore looked exactly
 * like a healthy one on every page, so the terminal could have let the owner trade a morning believing the quotes
 * were live. This is the one cue that says otherwise, and it sits in the header because that is the only place
 * visible from all 44 pages.
 *
 * Reads only credential-free sources: `/api/positions/breeze-budget` (counters and quotas — verified to carry no
 * url/key/token field) and `/live/status`'s derived booleans. It never touches `/api/positions/connection-status`,
 * whose payload embeds the API key in `login_url`. The face logic lives in `brokerFace.ts` and is node-tested.
 *
 * Quiet by design: nothing renders while a session is healthy, and an expired token outside market hours is IDLE,
 * not an alarm — a chip that cries every night is one the owner learns to ignore, which would restore the very
 * blindness this fixes.
 */
import { useEffect, useState } from 'react'

import { T } from '@/components/terminal'
import { goToPage } from '@/lib/navigate'
import { type BrokerFace, type BudgetSnap, type LiveSnap, brokerFace } from './brokerFace'

const POLL_MS = 60_000                    // once a minute: these are counters, not quotes

async function readJson<Tt>(url: string): Promise<Tt | null> {
  try {
    const r = await fetch(url, { cache: 'no-store' })
    return r.ok ? ((await r.json()) as Tt) : null
  } catch {
    return null                           // a failed read is silence, never a false alarm
  }
}

export function BrokerChip() {
  const [face, setFace] = useState<BrokerFace | null>(null)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      const [budget, live] = await Promise.all([
        readJson<BudgetSnap>('/api/positions/breeze-budget'),
        readJson<LiveSnap>('/api/live/status'),
      ])
      if (alive) setFace(brokerFace(live, budget, new Date()))
    }
    tick()
    const iv = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(iv) }
  }, [])

  if (!face) return null
  const c = face.tone === 'bad' ? T.red : face.tone === 'warn' ? T.amber : T.dim
  return (
    <span role="button" tabIndex={0} data-sd-brkr={face.tone} title={face.title}
      onClick={() => goToPage('broker')} onKeyDown={e => { if (e.key === 'Enter') goToPage('broker') }}
      style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.1, color: c, border: `1px solid ${c}66`,
        padding: '1px 6px', cursor: 'pointer', whiteSpace: 'nowrap' }}>
      {face.label}
    </span>
  )
}
