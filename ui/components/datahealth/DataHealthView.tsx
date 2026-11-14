'use client'

/**
 * SYS › DATA (reports/terminal_v2/PLAN.md 1.4; GO alias DATA): every catalogued dataset with a RAG state, sorted worst
 * first and by sessions behind, filterable by the page that reads it, in honest wording ("stored 30 Oct · expected by
 * 21:00 · 3 sessions behind · catch-up 19:30 tomorrow"); counts, never a composite score. The header's
 * `DATA n STALE` chip (DataStaleChip) links here. Source: GET /api/data/health (60 s SWR on ui-api; it reads
 * data-service's meta endpoints, the catalog and the controller's schedule — never a publisher).
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Chip, DataTable, Panel, T, sourceOf, type Column } from '@/components/terminal'
import { setSubInUrl } from '@/components/terminal/source'
import { goToPage } from '@/lib/navigate'
import { staleChipFace, useDataHealthStore } from '@/lib/dataHealthStore'
import { filterByPage, getDataHealth, rowSentence, sortRows, staleCount, type DataHealth, type HealthRow } from './api'

const STATE_COLOR: Record<string, string> = { gap: T.red, red: T.red, amber: T.amber, live: T.green, fresh: T.muted }

function StateChip({ s }: { s: string }) {
  const c = STATE_COLOR[s] ?? T.dim
  return <span data-health-state={s} style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: 1, color: c, border: `1px solid ${c}88`, padding: '1px 6px' }}>
    {s.toUpperCase()}</span>
}

const errText = (e: unknown): string => {
  const st = (e as { response?: { status?: number } } | null)?.response?.status
  if (st === 404) return 'the data-health route is not on this ui-api yet (Terminal v2 not deployed)'
  return e instanceof Error ? e.message : 'unavailable'
}

export function DataHealthView() {
  const [d, setD] = useState<DataHealth | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [page, setPage] = useState<string | null>(null)
  const load = useCallback(() => {
    getDataHealth().then(r => { setD(r.data); setErr(null) }).catch((e: unknown) => setErr(errText(e)))
  }, [])
  useEffect(() => {
    load()
    const iv = setInterval(() => { if (!document.hidden) load() }, 120_000)
    return () => clearInterval(iv)
  }, [load])
  const pages = useMemo(() => [...new Set((d?.rows ?? []).flatMap(r => r.pages ?? []))].sort(), [d])
  const rows = useMemo(() => sortRows(filterByPage(d?.rows ?? [], page)), [d, page])
  const cols = useMemo<Column<HealthRow>[]>(() => [
    { key: 'state', label: 'State', sort: r => ({ gap: 0, red: 1, amber: 2, live: 3, fresh: 4 } as Record<string, number>)[r.state] ?? 9, render: r => <StateChip s={r.state} /> },
    { key: 'label', label: 'Dataset', sort: r => r.label, render: r => <span title={r.id}><span style={{ color: T.text }}>{r.label}</span> <span style={{ color: T.dim, fontSize: 10 }}>{r.id}</span></span> },
    { key: 'lag', label: 'Behind', align: 'right', sort: r => r.lag_sessions ?? -1, title: 'sessions behind the last session whose data is due',
      // F9-07: this read "2 s" / "1844 s" for SESSIONS, in a terminal where `s` is seconds on every
      // SourceChip, age_s and last_tick_age_s — so "2 s behind" looked fresh when it meant two trading
      // sessions stale, on the one page whose whole job is to say how stale things are.
      render: r => r.lag_sessions == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: r.lag_sessions > 0 ? T.text : T.dim }}>{r.lag_sessions} sess</span> },
    { key: 'asof', label: 'Stored as of', sort: r => r.as_of ?? '', render: r => <span style={{ color: r.as_of ? T.text : T.dim }}>{r.as_of ?? 'nothing'}</span> },
    { key: 'exp', label: 'Expected by', render: r => <span style={{ color: T.muted }}>{r.expected_by ?? '—'}{r.published_ist ? ` (pub. ${r.published_ist})` : ''}</span> },
    { key: 'pages', label: 'Pages', render: r => <span style={{ color: T.muted }}>{(r.pages ?? []).join(' ')}</span> },
    { key: 'pub', label: 'Publisher', sort: r => r.publisher, render: r => <span style={{ color: T.muted }}>{r.publisher}</span> },
    { key: 'job', label: 'Job · last run', render: r => <span style={{ color: T.muted }}>{r.job_id ?? '—'}{r.last_run?.ts ? ` · ${r.last_run.ts.slice(5, 16).replace('T', ' ')} ${r.last_run.status ?? ''}` : r.last_run ? ' · never run' : ''}</span> },
    // F11-06: the page printed only the LAST run's word, so a job that crashed and was re-run later read
    // FRESH — which is what nse_results did on 14 Nov after dying twice the evening before, on the one page
    // whose whole job is data trust. A dash, never a 0, when the store cannot speak for the period.
    { key: 'fails', label: 'Crashes', align: 'right', sort: r => r.job_failures ?? -1,
      title: 'runs of this dataset\u2019s job that ended in an error or were re-queued after a crash, within the window the job store still holds',
      // R15-E: `0` and `—` were both T.dim, and `0 || '·'` rendered the clean case as a middot — so "this
      // job ran and did not crash" looked exactly like "this store has never seen this job". Those are the
      // two meanings this column exists to separate, so they must not share a glyph OR a colour.
      render: r => r.job_failures == null
        ? <span style={{ color: T.dim }} title="this job has not entered the durable queue, so there is nothing to count">—</span>
        : r.job_failures > 0
          ? <span style={{ color: T.amber }}>{r.job_failures}</span>
          : <span style={{ color: T.muted }} title="this job ran and did not crash in the counted window">0</span> },
    { key: 'note', label: 'What it means', render: r => <span style={{ color: T.text, whiteSpace: 'normal', display: 'inline-block', minWidth: 260 }}>{rowSentence(r)}</span> },
  ], [])
  const n = staleCount(d)
  return (
    <div style={{ display: 'grid', gap: 12 }} data-sys-view="data">
      <Panel title="Data health · every dataset" accent={T.cyan} pad={0} badge={d?.badge ?? 'context'}
        source={sourceOf(d?.as_of ?? null, { source: 'ui-api /api/data/health', maxAgeDays: 1, hint: err })}
        subtitle={d ? `${d.summary.green} fresh · ${d.summary.amber} amber · ${d.summary.red} red · ${d.summary.gaps} gaps · last session ${d.last_session ?? '—'} · catalog: ${d.catalog_source}${d.failures_since ? ` · crash counting began ${d.failures_since.slice(0, 10)} ${d.failures_since.slice(11, 16)}` : ''}` : undefined}
        right={<span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap', justifyContent: 'flex-end' }} data-health-pages>
          <Chip color={T.muted} active={!page} onClick={() => setPage(null)}>ALL</Chip>
          {pages.map(p => <Chip key={p} color={T.cyan} active={page === p} onClick={() => setPage(q => (q === p ? null : p))} title={`datasets ${p} reads`}>{p}</Chip>)}
        </span>}>
        {err && <div style={{ padding: 12, fontSize: 11, color: T.amber }}>Unavailable: {err}.</div>}
        {!d && !err && <div style={{ padding: 12, fontSize: 11, color: T.dim }}>Loading…</div>}
        {d && <DataTable columns={cols} rows={rows} rowKey={r => r.id} dense maxHeight={640} exportName="SYS_data_health"
          empty={<div style={{ padding: 12, fontSize: 11, color: T.muted }}>No dataset is read by {page}.</div>} />}
        {d && (
          <div style={{ padding: '6px 12px', fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
            {n ? `${n} dataset${n === 1 ? '' : 's'} not fresh. ` : 'Every catalogued dataset is fresh. '}
            {d.note} {Object.keys(d.inputs_unavailable ?? {}).length > 0 && <span style={{ color: T.amber }}>Inputs not answering: {Object.entries(d.inputs_unavailable).map(([k, v]) => `${k} (${v})`).join(', ')}.</span>}
            {!d.controller_online && <span style={{ color: T.amber }}> The master controller is offline: next-run times are unknown.</span>}
          </div>
        )}
      </Panel>
    </div>
  )
}

/** Open SYS on its DATA sub-view (the header chip, the GO alias). */
export function openDataView(): void {
  setSubInUrl('data')
  goToPage('system')
}

/**
 * The header's `DATA n STALE` chip (PLAN 1.4): n = amber + red + gaps from the window's shared /api/data/health store
 * (ui/lib/dataHealthStore, 5 min visible / 15 min hidden); a click opens SYS › DATA. Renders nothing ONLY while the
 * route is not deployed (pre-v2 404) — the chip never guesses. FINAL ROUND G8: a fetch error keeps the last good count
 * greyed with '?' ("health endpoint unreachable" is no longer indistinguishable from "fresh" or from "not deployed").
 */
export function DataStaleChip() {
  const snap = useDataHealthStore()
  const face = staleChipFace(snap)
  if (!face) return null
  const c = face.tone === 'warn' ? T.amber : face.tone === 'ok' ? T.muted : T.dim
  return (
    <span role="button" tabIndex={0} data-data-stale={face.n ?? '?'} data-data-health={snap.status} title={face.title}
      onClick={openDataView} onKeyDown={e => { if (e.key === 'Enter') openDataView() }}
      style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.1, color: c, border: `1px solid ${c}66`, padding: '1px 6px', cursor: 'pointer', whiteSpace: 'nowrap' }}>
      {face.label}
    </span>
  )
}
