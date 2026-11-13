'use client'

/**
 * h.accuracy — the 08:45 IST fair open against the actual MCX open, day by day (PLAN a.2). Answers: is the model
 * better than "open = yesterday's settlement", and is the ₹300 chase limit the right size? Rows are written by
 * master-controller (snapshot 08:45, ICICI open 09:10); without an ICICI session, type the open here (PAPER: a log
 * row, never an order). `AccuracyStrip` is the compact strip HEALTH shows; the table opens under it.
 * Data: /api/gold/log (gold_preopen_log) — arithmetic badge; ≈20 rows are needed before the limit means anything.
 *
 * D2 (round 2): every checkable row carries its settlement check (`baseline_check`: its baseline vs the last-30-min VWAP of
 * the session it was labelled with); stored numbers are never rewritten — a stale row is FLAGGED and RE-EXPLAINED (the
 * check's own words), and the strip prints the model-vs-naive read both on every row and without the stale rows.
 */
import { apiError } from '@/lib/errors'
import { useCallback, useEffect, useState } from 'react'
import { Btn, Chip, DataTable, Input, Stat, T, type Column } from '@/components/terminal'
import { fmtSignedInr } from '@/lib/format'
import { getGoldLog, setGoldLogActual } from '@/lib/gold/api'
import { accuracyRead, dayLabel, fmtInr0, logCheckWords, onVwap30Line, staleReasonWords } from '@/lib/gold/format'
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
  const acc = accuracyRead(stats, rows)
  const better = acc.better
  const stale = acc.stale
  // the live-only read first (the rows priced off the right session), then the labelled counterfactual (wave 1e minor)
  const clean = stats.excluding_stale
  const cf = onVwap30Line(stats, threshold)
  return (
    <>
    {(clean?.days || cf) ? <div data-gold-acc-live style={{ fontSize: 11, color: T.text, marginBottom: 6, lineHeight: 1.6 }}>
      {clean?.days ? <div>On the right session&apos;s settlement ({clean.days} day{clean.days === 1 ? '' : 's'}): median miss <b>{inr(clean.median_abs_error)}</b> · naive {inr(clean.naive_mean_abs_error)}{clean.days < 20 ? ' — too few days to size anything' : ''}</div> : null}
      {cf ? <div data-gold-acc-counterfactual style={{ color: T.muted }}>{cf}</div> : null}
    </div> : null}
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
      <Stat big={false} label="Days measured" value={stats.days} sub={stats.days < 20 ? 'need ≈20 to size the chase limit' : 'enough for a first read'} />
      <Stat big={false} label="Typical model miss" value={stats.days ? inr(stats.median_abs_error) : '—'}
        sub={stats.days ? `mean ${inr(stats.mean_abs_error)} · p90 ${inr(stats.p90_abs_error)}` : 'median absolute error'} />
      <Stat big={false} label={`Within ₹${threshold.toLocaleString('en-IN')}`} value={stats.days ? `${stats.within_threshold_pct ?? 0}%` : '—'}
        sub={stats.days ? `bias ${fmtSignedInr(stats.bias)} (+ = opens above fair)` : 'share of days'} />
      <Stat big={false} label="Model vs naive (every row)" value={better == null ? '—' : better ? 'BETTER' : 'WORSE'}
        color={better == null ? T.muted : better ? T.green : T.red}
        sub={<span data-gold-acc-clean={acc.cleanDays ?? ''}>{stats.naive_mean_abs_error != null ? `naive = settlement · mean miss ${inr(stats.naive_mean_abs_error)}` : 'naive = settlement'}
          {acc.cleanLine ? <span style={{ display: 'block', color: T.muted }}>{acc.cleanLine}</span> : null}</span>} />
      <Stat big={false} label="Stale baselines" value={stale} color={stale ? T.amber : T.text}
        sub={<span data-gold-acc-stale={stale}>{stale ? `${acc.staleDays.map(d => dayLabel(d)).join(', ')}: priced off another session's settlement (the stored numbers stand; flagged, not re-scored)` : 'none flagged'}
          {acc.unknown > 0 ? <span style={{ display: 'block', color: T.muted }}>{acc.unknown} row{acc.unknown === 1 ? '' : 's'}: check not run yet (no last-30-min VWAP for the labelled session)</span> : null}
          <span style={{ display: 'block', color: T.dim }}>test: {stats.stale_baseline_rule ?? 'the baseline vs the last-30-min VWAP of the session it was labelled with > 0.6 %'}</span></span>} />
    </div>
    </>
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
    { key: 'date', label: 'Day', render: r => <span>{dayLabel(r.date)}{r.stale_baseline && <Chip color={T.amber} style={{ marginLeft: 6, fontSize: 9, padding: '0 4px' }} title={`${staleReasonWords(r.stale_reasons) || logCheckWords(r).text}`}>STALE BASE</Chip>}</span> },
    { key: 'baseline', label: 'Settlement (as logged)', align: 'right', render: r => <span style={{ color: T.muted }} title={r.baseline_session ? `labelled ${dayLabel(r.baseline_session)} settlement · ${r.baseline_source ?? 'source not logged'}` : r.baseline_source ?? undefined}>{inr(r.baseline)}</span> },
    // D2: the row's settlement check, re-explained in its own words; the stored numbers beside it are never rewritten
    { key: 'check', label: 'Check vs VWAP30', align: 'right', render: r => { const c = logCheckWords(r)
      return <span data-gold-log-check={c.state} style={{ color: c.state === 'flagged' ? T.amber : T.muted }} title={c.text}>{c.short}</span> } },
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
    // the counterfactual beside the stored numbers, dimmed and labelled — never the scored miss (D2)
    { key: 're', label: 'Miss on VWAP30 (counterfactual)', align: 'right', render: r => r.re_explained?.error_on_vwap30 != null
      ? <span data-gold-log-re style={{ color: T.dim }} title={r.re_explained.note ?? 'counterfactual: the fair open had the baseline been the labelled session\'s last-30-min VWAP; the recorded miss stays the score'}>{fmtSignedInr(r.re_explained.error_on_vwap30)}</span>
      : <span style={{ color: T.dim }}>—</span> },
  ]

  return (
    <GoldPanel id="h.accuracy" title="Accuracy log" accent={T.green} badge="arithmetic" layer={layer} catalog={catalog} series={['PREOPEN_LOG']}
      subtitle="fair open recorded 08:45 IST vs the actual MCX open · naive = open at yesterday's settlement"
      freshness={log ? { state: 'delayed', source: 'gold_preopen_log', reason: 'daily rows' } : null}
      copyB="Has the 08:45 call been any good? The miss is the actual MCX open minus the fair open."
      copyP="Need ≈20 rows before the chase limit means anything. Rows logged before wave 1d were priced off the ICICI band midpoint, which ran one MCX session stale (every miss ≈ the previous session's gold move, corr 0.98, 5 Nov review). Each row's check compares its logged baseline with the last-30-min VWAP of the session it was labelled with (> 0.6 % = stale), the same test as the settlement check; a row without an expiry takes it from its contract label. The stored baseline, fair open and misses are never rewritten: stale rows are flagged and explained, and the model-vs-naive read is also shown without them."
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
