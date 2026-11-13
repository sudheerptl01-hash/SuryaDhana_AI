'use client'

/**
 * mcxg.fairopen — the 08:45 IST fair open against the actual MCX open, drawn day by day (FINAL ROUND W3 / C-GOLD;
 * the MCXG desk's first interactive chart). Reads the EXISTING /api/gold/log (gold_preopen_log) — the same store the
 * HEALTH accuracy log scores — and draws the two recorded numbers per day: the model's 08:45 fair open and the actual
 * MCX open. A day whose open was never captured is an honest gap, never interpolated. Arithmetic over stored rows;
 * it describes, does not predict. The full log with each row's settlement checks stays on GOLD › HEALTH (one scored
 * table on the terminal); this chart prints no miss statistics, so no number repeats between the two pages' panels.
 *
 * Self-contained for the MCXG page (which does not hold the gold catalog): it loads the catalog itself so the
 * §f.2 gate and the About popover work the same as on GOLD.
 */
import { useEffect, useState } from 'react'
import { T } from '@/components/terminal'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { InteractiveSeries, type SeriesPoint } from '@/components/terminal/InteractiveSeries'
import { getGoldLog, loadCatalog } from '@/lib/gold/api'
import { dayLabel, fmtInr0 } from '@/lib/gold/format'
import type { CatalogRow } from '@/lib/gold/types'
import { GoldPanel, NoVerdict, Pending, useGoldLoad } from './kit'

const LOG_MS = 15 * 60_000

export function FairOpenHistory({ threshold = 300, days = 60 }: { threshold?: number; days?: number }) {
  const log = useGoldLoad(() => getGoldLog(threshold, days), [threshold, days], LOG_MS)
  const [catalog, setCatalog] = useState<Record<string, CatalogRow> | null>(null)
  useEffect(() => {
    let alive = true
    loadCatalog().then(c => { if (alive) setCatalog(c) }).catch(() => { /* the gate renders 'catalog?' */ })
    return () => { alive = false }
  }, [])
  const rows = (log.data?.rows ?? []).slice().sort((a, b) => a.date.localeCompare(b.date))
  const drawable = rows.filter(r => r.fair_open != null)
  const stale = rows.filter(r => r.stale_baseline).length
  const fair: SeriesPoint[] = drawable.map(r => ({ t: r.date, v: r.fair_open ?? null }))
  const actual: SeriesPoint[] = drawable.map(r => ({ t: r.date, v: r.actual_open ?? null }))
  const last = drawable.length ? drawable[drawable.length - 1] : null

  return (
    <GoldPanel id="mcxg.fairopen" title="Pre-open baseline vs MCX print · history" badge="arithmetic" accent={T.green} pad={8}
      catalog={catalog} series={['PREOPEN_LOG']}
      freshness={log.data ? { state: 'delayed', source: 'gold_preopen_log', reason: 'one row per trading day' } : null}
      reportDate={last?.date ?? null}
      subtitle={`${drawable.length} recorded day${drawable.length === 1 ? '' : 's'} · fair open snapshot 08:45 IST, actual from ICICI at 09:10 (or typed on GOLD › HEALTH) · describes, does not predict`}
      copyB="The morning model's 08:45 fair-open call and what MCX actually opened at, day by day. A missing open is a gap in the line, never filled in. The scored log — misses, the naive baseline, each row's settlement checks — lives on GOLD › HEALTH."
      copyP={`fair open = COMEX × USD/INR, duty-paid landed, anchored to the previous settlement (gold_preopen_log); stored numbers are never rewritten${stale ? `; ${stale} row${stale === 1 ? '' : 's'} carry a stale-baseline flag on the HEALTH log and are drawn here exactly as stored` : ''}. Wheel = zoom, drag = pan, FIT = whole series.`}>
      <Pending s={log} label="the pre-open log">
        {drawable.length < 2
          ? <NoVerdict what="fewer than two recorded mornings (the 08:45 job writes one row per trading day)" />
          : <ExpandableChart title="fair open 08:45 vs actual MCX open" height={180}
              legend={<span><span style={{ color: T.text }}>— actual open</span> · <span style={{ color: T.amber }}>– – fair 08:45</span></span>}>
              <InteractiveSeries height={180} ariaLabel="fair open vs actual open history" series={[
                { id: 'actual', label: 'actual open', color: T.text, format: fmtInr0, points: actual },
                { id: 'fair', label: 'fair 08:45', color: T.amber, dashed: true, format: fmtInr0, points: fair },
              ]} />
            </ExpandableChart>}
        {last && <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>last recorded morning: {dayLabel(last.date)}{last.contract ? ` · ${last.contract}` : ''}{last.actual_open == null ? ' · its open is not captured yet' : ''}</div>}
      </Pending>
    </GoldPanel>
  )
}

export default FairOpenHistory
