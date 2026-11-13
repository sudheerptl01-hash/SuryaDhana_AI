'use client'

/**
 * Scenario strip over the OPEN paper book (risk/SPEC.md §4), mounted on the paper-book card (OSTR) and on
 * RSK › F&O: `SPOT −2 · −1 · +1 · +2 %` (IV unchanged) │ `IV −5 · +5 pts` (spot unchanged) │ `T −1d`.
 *
 * Each tile is the ₹ P&L of a full Black-76 revaluation of the open legs vs current marks, read from
 * GET /api/risk/fo `scenarios` (M2 adds the ±1 % gaps and the theta row; older payloads fall back to
 * theta_1d_inr and show — for ±1 %). Tone muted/amber/red by |loss| vs the daily cap REMAINING today — the tie
 * to the cockpit — never a direction colour (gains stay muted). Badge `arithmetic`. Empty book → hides.
 *
 * `data`: a caller that already holds the /api/risk/fo payload (RSK › F&O) passes it; without it the strip
 * fetches its own (margin=false — the SPAN ask is not needed here).
 */
import { useEffect, useRef, useState } from 'react'
import client from '@/lib/api'
import { BadgeChip, Label, T } from '@/components/terminal'
import { inr, parseScenarios, remainingCap, scenarioTone, type ScenarioStripData } from './disciplineModel'
import { useDiscipline } from './useDiscipline'

const toneColor = { muted: T.muted, amber: T.amber, red: T.red } as const

export function ScenarioStrip({ data }: { data?: unknown }) {
  const d = useDiscipline()
  const [fetched, setFetched] = useState<unknown>(null)
  const alive = useRef(true)
  const selfFetch = data === undefined
  useEffect(() => {
    alive.current = true
    if (!selfFetch) return
    client.get('/api/risk/fo', { params: { margin: false }, timeout: 30_000 })
      .then(r => { if (alive.current) setFetched(r.data) })
      .catch(() => { if (alive.current) setFetched(null) })
    return () => { alive.current = false }
  }, [selfFetch])
  const payload = selfFetch ? fetched : data
  if (payload == null) return null
  const sc: ScenarioStripData = parseScenarios(payload)
  if (sc.empty) return null
  const remaining = remainingCap(d.settings, d.ev)
  const clock = sc.asOf ? sc.asOf.slice(11, 16) : null
  return (
    <div data-sd-scenario-strip style={{ display: 'flex', alignItems: 'stretch', gap: 6, flexWrap: 'wrap' }}>
      {sc.tiles.map((tile, i) => {
        const sep = i > 0 && sc.tiles[i - 1].group !== tile.group
        const tone = scenarioTone(tile.pnl, remaining)
        return (
          <span key={tile.id} style={{ display: 'inline-flex', alignItems: 'stretch', gap: 6 }}>
            {sep && <span aria-hidden style={{ width: 1, background: T.border, margin: '2px 0' }} />}
            <span data-sd-scenario={tile.id} data-sd-tone={tone}
              title={`Full revaluation of the open legs; marks as of ${sc.asOf ?? '—'}${remaining != null ? ` · tone vs the ${inr(remaining)} left under your daily cap today` : ''}`}
              style={{ display: 'inline-flex', flexDirection: 'column', gap: 1, padding: '4px 8px', minWidth: 72,
                       border: `1px solid ${tone === 'muted' ? T.border : toneColor[tone]}`, background: T.panel2 }}>
              <span style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1, color: T.dim }}>{tile.label}</span>
              <span style={{ fontFamily: T.mono, fontSize: 12, fontVariantNumeric: 'tabular-nums', color: toneColor[tone] }}>
                {inr(tile.pnl)}</span>
            </span>
          </span>
        )
      })}
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, paddingLeft: 2 }}>
        <BadgeChip badge="arithmetic" note={sc.note ?? 'instant revaluation of the open legs'} />
        {clock && <Label>marks {clock}</Label>}
      </span>
    </div>
  )
}
