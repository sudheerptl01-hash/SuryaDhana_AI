'use client'

/**
 * h.accuracy — the 08:45 IST fair open against the actual MCX open, day by day (PLAN a.2). Answers: is the model
 * better than "open = yesterday's settlement", and is the ₹300 chase limit the right size? Rows are written by
 * master-controller (snapshot 08:45, ICICI open 09:10); without an ICICI session, type the open here (PAPER: a log
 * row, never an order). `AccuracyStrip` is the compact strip HEALTH shows; the table opens under it.
 * Data: /api/gold/log (gold_preopen_log) — arithmetic badge; ≈20 rows are needed before the limit means anything.
 */
import { apiError } from '@/lib/errors'
import { useCallback, useEffect, useState } from 'react'
import { Btn, Chip, DataTable, Input, Stat, T, type Column } from '@/components/terminal'
import { fmtSignedInr } from '@/lib/format'
import { getGoldLog, setGoldLogActual } from '@/lib/gold/api'
import { dayLabel, fmtInr0 } from '@/lib/gold/format'
import type { CatalogRow, GoldLog, GoldLogRowX, GoldLogStatsX } from '@/lib/gold/types'
import { GoldPanel } from './kit'

const inr = (v?: number | null) => fmtInr0(v)

export function useGoldLog(threshold: number): { log: GoldLog | null; error: string | null; reload: () => void } {
  const [log, setLog] = useState<GoldLog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(() => {
    if (threshold <= 0) return                       // a parent holds the log (GoldPreOpen): no second fetch
    getGoldLog(threshold).then(r => { setLog(r.data); setError(null) }).catch((e: unknown) => setError(apiError(e, 'log unavailable')))
  }, [threshold])
  useEffect(() => { reload() }, [reload])
  return { log, error, reload }
}

/** The compact strip: days, median/mean/p90 miss, % within the limit, bias, model vs naive, stale-baseline flags. */
export function AccuracyStrip({ stats, rows, threshold }: { stats: GoldLogStatsX; rows: GoldLogRowX[]; threshold: number }) {
  const better = stats.naive_mean_abs_error != null && stats.mean_abs_error != null ? stats.mean_abs_error < stats.naive_mean_abs_error : null
  const stale = rows.filter(r => r.stale_baseline).length
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
      <Stat big={false} label="Days measured" value={stats.days} sub={stats.days < 20 ? 'need ≈20 to size the chase limit' : 'enough for a first read'} />
      <Stat big={false} label="Typical model miss" value={stats.days ? inr(stats.median_abs_error) : '—'}
        sub={stats.days ? `mean ${inr(stats.mean_abs_error)} · p90 ${inr(stats.p90_abs_error)}` : 'median absolute error'} />
      <Stat big={false} label={`Within ₹${threshold.toLocaleString('en-IN')}`} value={stats.days ? `${stats.within_threshold_pct ?? 0}%` : '—'}
        sub={stats.days ? `bias ${fmtSignedInr(stats.bias)} (+ = opens above fair)` : 'share of days'} />
      <Stat big={false} label="Model vs naive" value={better == null ? '—' : better ? 'BETTER' : 'WORSE'}
        color={better == null ? T.muted : better ? T.green : T.red}
        sub={stats.naive_mean_abs_error != null ? `naive = settlement · mean miss ${inr(stats.naive_mean_abs_error)}` : 'naive = settlement'} />
      <Stat big={false} label="Stale baselines" value={stale} color={stale ? T.amber : T.text}
        sub={stale ? 'rows priced off an older settlement (flagged)' : 'none flagged'} />
    </div>
  )
}

export function GoldAccuracyLog({ threshold, layer = 'B', shared, catalog = null }: {
  threshold: number; layer?: 'B' | 'P'; shared?: { log: GoldLog | null; error: string | null; reload: () => void }; catalog?: Record<string, CatalogRow> | null
}) {
  const own = useGoldLog(shared ? 0 : threshold)   // threshold 0 = the desk already holds the log; this fetch is skipped
  const { log, error, reload } = shared ?? own
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [msg, setMsg] = useState<string | null>(null)
  const [open, setOpen] = useState(false)
  const rows = log?.rows ?? []
  const stats = log?.stats ?? { days: 0 }

  const save = async (date: string) => {
    const v = Number((draft[date] ?? '').replace(/[,₹\s]/g, ''))
    if (!v) return
    try { await setGoldLogActual(date, v); setMsg(null); setDraft(d => ({ ...d, [date]: '' })); reload() }
    catch (e: unknown) { setMsg(apiError(e, 'Could not save')) }
  }

  const cols: Column<GoldLogRowX>[] = [
    { key: 'date', label: 'Day', render: r => <span>{dayLabel(r.date)}{r.stale_baseline && <Chip color={T.amber} style={{ marginLeft: 6, fontSize: 8.5, padding: '0 4px' }} title="baseline was an older session's settlement">STALE BASE</Chip>}</span> },
    { key: 'baseline', label: 'Settlement', align: 'right', render: r => <span style={{ color: T.muted }} title={r.baseline_session ? `${dayLabel(r.baseline_session)} settlement` : undefined}>{inr(r.baseline)}</span> },
    { key: 'fair_open', label: 'Fair open 08:45', align: 'right', render: r => <span style={{ color: T.amber }}>{inr(r.fair_open)}</span> },
    { key: 'actual_open', label: 'Actual open', align: 'right', render: r => r.actual_open != null
      ? <span title={r.actual_source}>{inr(r.actual_open)}</span>
      : (
        <span style={{ display: 'inline-flex', gap: 4 }} onClick={e => e.stopPropagation()}>
          <Input value={draft[r.date] ?? ''} onChange={v => setDraft(d => ({ ...d, [r.date]: v }))} placeholder="type open" width={96} aria-label={`actual open ${r.date}`} />
          <Btn size="sm" onClick={() => save(r.date)}>SAVE</Btn>
        </span>
      ) },
    { key: 'error', label: 'Model miss', align: 'right', sort: r => Math.abs(r.error ?? 0),
      render: r => <span style={{ color: r.error == null ? T.dim : Math.abs(r.error) <= threshold ? T.green : T.red, fontWeight: 600 }}>{fmtSignedInr(r.error)}</span> },
    { key: 'naive_error', label: 'Naive miss', align: 'right', render: r => <span style={{ color: T.muted }}>{fmtSignedInr(r.naive_error)}</span> },
  ]

  return (
    <GoldPanel id="h.accuracy" title="Accuracy log" accent={T.green} badge="arithmetic" layer={layer} catalog={catalog} series={['PREOPEN_LOG']}
      subtitle="fair open recorded 08:45 IST vs the actual MCX open · naive = open at yesterday's settlement"
      freshness={log ? { state: 'delayed', source: 'gold_preopen_log', reason: 'daily rows' } : null}
      copyB="Has the 08:45 call been any good? The miss is the actual MCX open minus the fair open."
      copyP="Need ≈20 rows before the chase limit means anything; the 15 Oct row looks like a stale baseline (band-midpoint settlement from an older file)."
      right={<><Btn size="sm" onClick={() => setOpen(o => !o)}>{open ? 'HIDE TABLE' : 'FULL LOG ›'}</Btn><Btn size="sm" onClick={reload}>↻</Btn></>}>
      {error && !log && <div style={{ fontSize: 11, color: T.amber }}>Unavailable: {error}</div>}
      <AccuracyStrip stats={stats} rows={rows} threshold={threshold} />
      {msg && <div style={{ padding: '6px 0 0', fontSize: 11, color: T.red }}>{msg}</div>}
      {open && (
        <div style={{ marginTop: 10 }}>
          <DataTable columns={cols} rows={rows} rowKey={r => r.date} dense maxHeight={280} exportName="gold-accuracy-log"
            empty="First snapshot at 08:45 IST on the next trading day (master-controller). The open is filled from ICICI at 09:10, or type it here." />
        </div>
      )}
    </GoldPanel>
  )
}
