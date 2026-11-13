'use client'

/**
 * MLEngineWorkspace — live XGBoost direction-model training desk (Pillar 3).
 *
 * State machine:  IDLE → TRAINING → { COMPLETED | TERMINATED_BY_USER | ERROR }
 *
 *  • Run Sample Dataset      — 5 liquid names / 6 months, ≤80 rounds (health check)
 *  • Run Production Engine    — configurable universe + horizon, full rounds
 *  • STOP ENGINE (kill-switch)— instant cancellation; preserves the partial model
 *
 * Telemetry streams over NDJSON (see lib/mlTraining): epoch / log-loss / AUC / Gini
 * render live into a dual-axis convergence chart. MODE = PAPER at all times.
 *
 * 5 Nov 2026 review (m116): the page says which labels a run trains on (the production v2 5-day labels, which the
 * label study marks FAIL; services/ui-api/routers/ml_workspace.py `horizon_days = 5`), shows what a typical result
 * looks like before any run, and asks in place before a production run inside a restart freeze window (07:45–09:20,
 * 18:30–21:15 IST), when the EOD pipeline needs the CPU and the DuckDB lock.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BadgeChip, T } from '@/components/terminal'   // T.muted for axis text (RUP-06: one muted grey)
import clsx from 'clsx'
import {
  ComposedChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Legend, ReferenceLine,
} from 'recharts'
import {
  streamTraining, stopRun,
  type EpochEvent, type StartEvent, type ResultEvent,
} from '@/lib/mlTraining'
import { trailingRange } from '@/lib/format'
import { inFreezeWindowIST } from './honestyKit'

type Status = 'IDLE' | 'TRAINING' | 'COMPLETED' | 'TERMINATED_BY_USER' | 'ERROR'


interface Props { isDark?: boolean }

const STATUS_STYLE: Record<Status, { label: string; dot: string; text: string }> = {
  IDLE:               { label: 'IDLE',               dot: 'bg-slate-500',                 text: 'text-slate-400' },
  TRAINING:           { label: 'TRAINING',           dot: 'bg-amber-400 animate-pulse',   text: 'text-amber-300' },
  COMPLETED:          { label: 'COMPLETED',          dot: 'bg-emerald-500',               text: 'text-emerald-300' },
  TERMINATED_BY_USER: { label: 'TERMINATED_BY_USER', dot: 'bg-rose-500',                  text: 'text-rose-300' },
  ERROR:              { label: 'ERROR',              dot: 'bg-rose-600',                  text: 'text-rose-400' },
}

function fmt(n: number | null | undefined, d = 4) {
  return n === null || n === undefined || Number.isNaN(n) ? '—' : n.toFixed(d)
}

export function MLEngineWorkspace({ isDark = true }: Props) {
  const [status, setStatus] = useState<Status>('IDLE')
  const [runId, setRunId] = useState<string | null>(null)
  const [start, setStart] = useState<StartEvent | null>(null)
  const [epochs, setEpochs] = useState<EpochEvent[]>([])
  const [result, setResult] = useState<ResultEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [phase, setPhase] = useState<'none' | 'finalizing' | 'revealed'>('none')
  const abortRef = useRef<AbortController | null>(null)

  // Production config
  const [tickers, setTickers] = useState('')
  // default: the last 3 years up to today (IST); it used to be a fixed 2023-01-01 → 2025-12-31 (C1-18)
  const [fromDate, setFromDate] = useState(() => trailingRange(36).from)
  const [toDate, setToDate] = useState(() => trailingRange(36).to)
  const [nEstimators, setNEstimators] = useState(300)
  const [maxDepth, setMaxDepth] = useState(5)
  const [learningRate, setLearningRate] = useState(0.05)

  const live = epochs.length ? epochs[epochs.length - 1] : null
  const total = start?.total_rounds ?? nEstimators
  const pct = live ? Math.min(100, (live.iteration / Math.max(1, total)) * 100) : 0
  const rate = live && live.elapsed > 0 ? live.iteration / live.elapsed : 0
  const etaSec = live && rate > 0 ? Math.max(0, (total - live.iteration) / rate) : null

  const [freezeAsk, setFreezeAsk] = useState<string | null>(null)
  const launch = useCallback(async (mode: 'sample' | 'production', override = false) => {
    const win = mode === 'production' && !override ? inFreezeWindowIST() : null
    if (win) { setFreezeAsk(win); return }
    setFreezeAsk(null)
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setStatus('TRAINING'); setRunId(null); setStart(null); setEpochs([]); setResult(null); setError(null); setPhase('none')

    const params = mode === 'sample'
      ? { mode } as const
      : {
          mode,
          tickers: tickers.split(/[,\s]+/).map(t => t.trim().toUpperCase()).filter(Boolean),
          from_date: fromDate, to_date: toDate,
          n_estimators: nEstimators, max_depth: maxDepth, learning_rate: learningRate,
        } as const

    try {
      await streamTraining(params, {
        signal: ac.signal,
        onAccepted: e => setRunId(e.run_id),
        onStart: e => setStart(e),
        onEpoch: e => setEpochs(prev => [...prev, e]),
        onResult: e => { setResult(e); setStatus(e.status) },
        onError: d => { setError(d); setStatus('ERROR') },
      })
    } catch (err: any) {
      if (ac.signal.aborted) return
      setError(err?.message || 'Training stream failed'); setStatus('ERROR')
    }
  }, [tickers, fromDate, toDate, nEstimators, maxDepth, learningRate])

  const kill = useCallback(async () => {
    if (runId) await stopRun(runId)          // graceful: backend stops at next round, keeps the model
    // Do NOT abort the fetch yet — let the stream deliver the TERMINATED_BY_USER result.
  }, [runId])

  // Completion choreography — a brief "finalizing" loader, then reveal the result panel.
  useEffect(() => {
    if (!result) return
    setPhase('finalizing')
    const t = setTimeout(() => setPhase('revealed'), 1100)
    return () => clearTimeout(t)
  }, [result])

  const isTraining = status === 'TRAINING'
  const chartData = useMemo(() => epochs.map(e => ({
    iteration: e.iteration,
    train_logloss: e.train_logloss,
    valid_logloss: e.valid_logloss,
    valid_auc: e.valid_auc,
    gini: e.gini,
  })), [epochs])

  const ss = STATUS_STYLE[status]
  const card = 'rounded-lg border border-slate-700/60 bg-slate-900/40'

  return (
    <div className="font-mono text-slate-200 space-y-4">
      <style dangerouslySetInnerHTML={{ __html: MLW_CSS }} />
      {/* ── Command bar ─────────────────────────────────────────────────────── */}
      <div className={clsx(card, 'p-4')}>
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-bold tracking-[0.18em] text-slate-400">RUN CONTROLS</span>
            <span className="px-1.5 py-0.5 text-[9px] font-bold tracking-wider border" style={{ color: '#39c6ff', borderColor: '#39c6ff55', background: '#39c6ff12' }}>PAPER</span>
          </div>
          <div className="flex items-center gap-2 ml-auto">
            <span className={clsx('h-2 w-2 rounded-full', ss.dot)} />
            <span className={clsx('text-[11px] font-bold tracking-wider', ss.text)}>{ss.label}</span>
            {runId && <span className="text-[9px] text-slate-600">#{runId.slice(0, 8)}</span>}
          </div>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button
            onClick={() => launch('sample')} disabled={isTraining}
            className="px-3 py-1.5 rounded text-[11px] font-bold bg-slate-800 border border-slate-600 text-slate-100 hover:border-sky-500/60 disabled:opacity-40 disabled:cursor-not-allowed">
            ▶ Run Sample Dataset
          </button>
          <button
            onClick={() => launch('production')} disabled={isTraining}
            className="px-3 py-1.5 rounded text-[11px] font-bold bg-emerald-600/20 border border-emerald-500/50 text-emerald-200 hover:bg-emerald-600/30 disabled:opacity-40 disabled:cursor-not-allowed">
            ▶ Run Production Engine
          </button>
          <button
            onClick={kill} disabled={!isTraining}
            className="px-3 py-1.5 rounded text-[11px] font-bold bg-rose-600/20 border border-rose-500/60 text-rose-200 hover:bg-rose-600/40 disabled:opacity-30 disabled:cursor-not-allowed">
            ■ STOP ENGINE
          </button>
          <span className="text-[10px] text-slate-500">
            Sample = 5 liquid names · 6 months · ≤80 rounds. Kill-switch preserves the model trained so far.
          </span>
        </div>
        {freezeAsk && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]" data-mlen-freeze>
            <span className="text-amber-300">Inside the {freezeAsk} freeze window: a production run competes with the scheduled jobs for the CPU and the DuckDB lock.</span>
            <button onClick={() => launch('production', true)} className="px-2 py-0.5 rounded border border-amber-500/60 text-amber-200">Run anyway</button>
            <button onClick={() => setFreezeAsk(null)} className="px-2 py-0.5 rounded border border-slate-600 text-slate-400">Later</button>
          </div>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-400" data-mlen-labels>
          <BadgeChip badge="arithmetic" note="Training metrics of a classifier: no forecast of returns is claimed." />
          <span>Labels: the production <b className="text-slate-200">v2 5-day labels</b> (close 5 sessions ahead &gt; +0.15 %, ±2 % barrier),
            the ones the label study marks <b className="text-rose-300">FAIL</b>. The better 20-session excess-rank labels are not what this
            engine trains on. An earlier out-of-sample check put the 5-day AUC near 0.48 (a coin flip is 0.50), and even an AUC of 0.55
            would not survive a ~1 % round trip at weekly turnover.</span>
        </div>

        {/* Production config */}
        <div className="mt-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          <label className="col-span-2 sm:col-span-3 lg:col-span-2 flex flex-col gap-1">
            <span className="text-[9px] uppercase tracking-wider text-slate-500">Tickers (blank = universe)</span>
            <input value={tickers} onChange={e => setTickers(e.target.value)} disabled={isTraining}
              placeholder="RELIANCE TCS INFY …"
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-[11px] text-slate-200 focus:border-sky-500 outline-none disabled:opacity-50" />
          </label>
          <Field label="From" value={fromDate} onChange={setFromDate} type="date" disabled={isTraining} />
          <Field label="To" value={toDate} onChange={setToDate} type="date" disabled={isTraining} />
          <Field label="Rounds" value={nEstimators} onChange={v => setNEstimators(+v)} type="number" disabled={isTraining} />
          <Field label="Max Depth" value={maxDepth} onChange={v => setMaxDepth(+v)} type="number" disabled={isTraining} />
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-600/50 bg-rose-950/30 px-4 py-2 text-[11px] text-rose-300">
          ⚠ {error}
        </div>
      )}

      {/* ── Live training HUD: progress + ETA + throughput ──────────────────── */}
      {(isTraining || live) && (
        <div className={clsx(card, 'p-4 relative overflow-hidden')}>
          {isTraining && <div className="mlw-scan" />}
          <div className="flex items-end justify-between mb-2">
            <div className="flex items-baseline gap-2">
              <span className={clsx('text-[11px] font-bold tracking-wider',
                isTraining ? 'text-amber-300' : phase === 'finalizing' ? 'text-sky-300' : 'text-emerald-300')}>
                {isTraining ? 'TRAINING' : phase === 'finalizing' ? 'FINALIZING' : 'RUN COMPLETE'}
              </span>
              <span className="text-[10px] text-slate-500">round</span>
              <span className="tabular-nums text-lg font-black text-sky-300">{live?.iteration ?? 0}</span>
              <span className="text-[10px] text-slate-600">/ {total}</span>
            </div>
            <span className={clsx('tabular-nums text-2xl font-black', pct >= 100 ? 'text-emerald-300' : 'text-slate-100')}>
              {pct.toFixed(0)}<span className="text-sm text-slate-500">%</span>
            </span>
          </div>
          <div className="h-3 w-full rounded-full bg-slate-800/80 overflow-hidden border border-slate-700/50">
            <div
              className={clsx('h-full relative overflow-hidden transition-[width] duration-300 ease-out', isTraining && 'mlw-shimmer')}
              style={{ width: `${Math.max(2, pct)}%`, background: 'linear-gradient(90deg,#0ea5e9,#34d399 60%,#a3e635)' }} />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[10px] text-slate-400">
            <span>throughput <b className="text-slate-200 tabular-nums">{rate.toFixed(1)}</b> rounds/s</span>
            <span>ETA <b className="text-slate-200 tabular-nums">{etaSec != null && isTraining ? fmtTime(etaSec) : '—'}</b></span>
            <span>elapsed <b className="text-slate-200 tabular-nums">{live ? fmtTime(live.elapsed) : '0s'}</b></span>
            {live?.valid_auc != null && (
              <span>live AUC <b className={clsx('tabular-nums',
                live.valid_auc >= 0.55 ? 'text-emerald-300' : live.valid_auc >= 0.5 ? 'text-amber-300' : 'text-rose-300')}>
                {live.valid_auc.toFixed(4)}</b></span>
            )}
          </div>
        </div>
      )}

      {/* ── Live telemetry grid ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <Metric label="Iteration" value={live ? `${live.iteration}` : '0'}
          sub={start ? `/ ${start.total_rounds}` : ''} accent="text-slate-100" />
        <Metric label="Train LogLoss" value={fmt(live?.train_logloss)} accent="text-sky-300" />
        <Metric label="Valid LogLoss" value={fmt(live?.valid_logloss)} accent="text-indigo-300" />
        <Metric label="Valid AUC" value={fmt(live?.valid_auc)} accent="text-emerald-300" />
        <Metric label="Gini (2·AUC−1)" value={fmt(live?.gini)} accent="text-amber-300" />
        <Metric label="Elapsed" value={live ? `${live.elapsed.toFixed(1)}s` : '0s'} accent="text-slate-300" />
      </div>

      {/* dataset banner */}
      {start && (
        <div className={clsx(card, 'px-4 py-2 text-[10px] text-slate-400 flex flex-wrap gap-x-5 gap-y-1')}>
          <span>samples <b className="text-slate-200">{start.n_samples.toLocaleString('en-IN')}</b></span>
          <span>train <b className="text-slate-200">{start.n_train.toLocaleString('en-IN')}</b> ({start.train_span[0]} → {start.train_span[1]})</span>
          <span>valid <b className="text-slate-200">{start.n_valid.toLocaleString('en-IN')}</b> ({start.valid_span[0]} → {start.valid_span[1]})</span>
          <span>features <b className="text-slate-200">{start.n_features}</b></span>
          <span>up-rate <b className="text-slate-200">{(start.up_rate * 100).toFixed(1)}%</b></span>
          <span className="text-slate-600">· chronological split, no shuffle (look-ahead safe)</span>
        </div>
      )}

      {/* ── Convergence chart (dual axis) ───────────────────────────────────── */}
      <div className={clsx(card, 'p-3')}>
        <div className="flex items-center justify-between mb-2">
          <span className="text-[11px] font-bold tracking-wide text-slate-300">CONVERGENCE — Log-Loss (L) vs AUC / Gini (R)</span>
          <span className="text-[9px] text-slate-600">{chartData.length} rounds</span>
        </div>
        <div className="h-72">
          {chartData.length === 0 ? (
            <div className="h-full flex items-center justify-center text-[11px] text-slate-600">
              {isTraining ? 'Awaiting first boosting round…' : 'Launch a run to stream the convergence curve. Read VALID AUC: near 0.50 means no ranking skill; train log-loss falling while valid log-loss rises means overfitting.'}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="#1a2130" />
                <XAxis dataKey="iteration" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448"
                  label={{ value: 'boosting round', position: 'insideBottom', dy: 10, fontSize: 9, fill: '#475569' }} />
                <YAxis yAxisId="loss" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448"
                  domain={['auto', 'auto']} width={44} />
                <YAxis yAxisId="rank" orientation="right" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448"
                  domain={[0, 1]} width={36} />
                <Tooltip contentStyle={{ background: '#0a0e17', border: '1px solid #1a2130', fontSize: 11, fontFamily: 'monospace' }}
                  labelStyle={{ color: '#8a94a6' }} />
                <Legend wrapperStyle={{ fontSize: 9 }} />
                <ReferenceLine yAxisId="rank" y={0.5} stroke="#475569" strokeDasharray="4 4"
                  label={{ value: 'AUC 0.5', fontSize: 9, fill: '#475569', position: 'right' }} />
                <Line yAxisId="loss" type="monotone" dataKey="train_logloss" name="train log-loss"
                  stroke="#38bdf8" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                <Line yAxisId="loss" type="monotone" dataKey="valid_logloss" name="valid log-loss"
                  stroke="#818cf8" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                <Line yAxisId="rank" type="monotone" dataKey="valid_auc" name="valid AUC"
                  stroke="#34d399" dot={false} strokeWidth={1.5} isAnimationActive={false} />
                <Line yAxisId="rank" type="monotone" dataKey="gini" name="Gini"
                  stroke="#ffb000" dot={false} strokeWidth={1.5} strokeDasharray="3 3" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      {/* ── Finalizing loader (brief, before the reveal) ────────────────────── */}
      {result && phase === 'finalizing' && (
        <div className={clsx(card, 'p-8 flex flex-col items-center justify-center gap-3')}>
          <div className="mlw-spinner" />
          <div className="text-[12px] font-bold tracking-[0.2em] text-slate-300">
            {result.status === 'TERMINATED_BY_USER' ? 'PRESERVING PARTIAL MODEL…' : 'FINALIZING MODEL…'}
          </div>
          <div className="text-[10px] text-slate-500 tabular-nums">
            {result.rounds_completed}/{result.rounds_requested} rounds · computing confusion matrix + feature gain
          </div>
        </div>
      )}

      {/* ── Result panel ────────────────────────────────────────────────────── */}
      {result && phase === 'revealed' && (
        <div className={clsx(card, 'p-4 mlw-reveal')}>
          <div className="flex items-center gap-2 mb-3">
            <span className="relative inline-flex h-2 w-2 items-center justify-center">
              {result.status === 'COMPLETED' && <span className="mlw-burst" />}
              <span className={clsx('h-2 w-2 rounded-full', STATUS_STYLE[result.status].dot)} />
            </span>
            <span className={clsx('text-[12px] font-bold tracking-wide', STATUS_STYLE[result.status].text)}>
              {result.status === 'TERMINATED_BY_USER' ? 'TERMINATED BY USER — partial model preserved' : 'TRAINING COMPLETE'}
            </span>
            <span className="ml-auto text-[10px] text-slate-500">
              {result.rounds_completed}/{result.rounds_requested} rounds · {result.mode}
            </span>
          </div>

          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mb-4">
            <Metric label="Valid AUC" value={fmt(result.valid_auc)} accent="text-emerald-300" big />
            <Metric label="Gini" value={fmt(result.gini)} accent="text-amber-300" big />
            <Metric label="Accuracy" value={result.accuracy != null ? `${(result.accuracy * 100).toFixed(1)}%` : '—'} accent="text-sky-300" big />
            <Metric label="Valid LogLoss" value={fmt(result.valid_logloss)} accent="text-indigo-300" big />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Confusion matrix */}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Confusion (validation)</div>
              <div className="grid grid-cols-2 gap-1 max-w-[260px] text-[11px]">
                <ConfCell label="True ↑ (TP)" v={result.confusion.tp} tone="emerald" />
                <ConfCell label="False ↑ (FP)" v={result.confusion.fp} tone="rose" />
                <ConfCell label="False ↓ (FN)" v={result.confusion.fn} tone="rose" />
                <ConfCell label="True ↓ (TN)" v={result.confusion.tn} tone="emerald" />
              </div>
              {result.model_path && (
                <div className="mt-2 text-[9px] text-slate-600 break-all">model: {result.model_path}</div>
              )}
            </div>

            {/* Feature importance */}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 mb-1.5">Top features (gain)</div>
              <div className="space-y-1">
                {result.feature_importance.slice(0, 10).map((f, i) => {
                  const max = result.feature_importance[0]?.gain || 1
                  return (
                    <div key={f.feature} className="flex items-center gap-2 text-[10px]">
                      <span className="w-28 truncate text-slate-300">{i + 1}. {f.feature}</span>
                      <div className="flex-1 h-2 bg-slate-800 rounded overflow-hidden">
                        <div className="h-full bg-gradient-to-r from-sky-500/70 to-emerald-500/70"
                          style={{ width: `${Math.max(2, (f.gain / max) * 100)}%` }} />
                      </div>
                      <span className="w-12 text-right tabular-nums text-slate-500">{f.gain}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function Field({ label, value, onChange, type, disabled }:
  { label: string; value: string | number; onChange: (v: string) => void; type: string; disabled?: boolean }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[9px] uppercase tracking-wider text-slate-500">{label}</span>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} disabled={disabled}
        className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-[11px] text-slate-200 focus:border-sky-500 outline-none disabled:opacity-50" />
    </label>
  )
}

function Metric({ label, value, sub, accent, big }:
  { label: string; value: string; sub?: string; accent: string; big?: boolean }) {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/50 px-3 py-2">
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className={clsx('tabular-nums font-bold', accent, big ? 'text-xl' : 'text-base')}>
        {value}<span className="ml-1 text-[10px] font-normal text-slate-600">{sub}</span>
      </div>
    </div>
  )
}

function ConfCell({ label, v, tone }: { label: string; v: number; tone: 'emerald' | 'rose' }) {
  return (
    <div className={clsx('rounded border px-2 py-1.5',
      tone === 'emerald' ? 'border-emerald-700/40 bg-emerald-950/20' : 'border-rose-700/40 bg-rose-950/20')}>
      <div className="text-[9px] text-slate-500">{label}</div>
      <div className={clsx('tabular-nums font-bold', tone === 'emerald' ? 'text-emerald-300' : 'text-rose-300')}>{v.toLocaleString('en-IN')}</div>
    </div>
  )
}

function fmtTime(s: number): string {
  if (!Number.isFinite(s)) return '—'
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  const r = Math.round(s % 60)
  return `${m}m ${r.toString().padStart(2, '0')}s`
}

// Self-contained keyframes for the training HUD / completion choreography (no deps).
const MLW_CSS = `
@keyframes mlwSpin { to { transform: rotate(360deg); } }
.mlw-spinner { width:36px; height:36px; border-radius:9999px; border:3px solid rgba(148,163,184,0.18); border-top-color:#34d399; animation: mlwSpin 0.8s linear infinite; }
@keyframes mlwShimmer { 0% { transform: translateX(-100%); } 100% { transform: translateX(240%); } }
.mlw-shimmer::after { content:''; position:absolute; top:0; bottom:0; left:0; width:45%; background:linear-gradient(90deg,transparent,rgba(255,255,255,0.5),transparent); animation: mlwShimmer 1.1s ease-in-out infinite; }
@keyframes mlwReveal { from { opacity:0; transform: translateY(10px) scale(0.99); } to { opacity:1; transform:none; } }
.mlw-reveal { animation: mlwReveal 0.5s cubic-bezier(0.2,0.8,0.2,1) both; }
@keyframes mlwPing { 0% { transform: scale(1); opacity:0.75; } 80%,100% { transform: scale(3.2); opacity:0; } }
.mlw-burst { position:absolute; height:0.5rem; width:0.5rem; border-radius:9999px; background:#34d399; animation: mlwPing 1s ease-out 2; }
@keyframes mlwScan { 0% { left:-40%; } 100% { left:100%; } }
.mlw-scan { position:absolute; top:0; height:2px; width:40%; background:linear-gradient(90deg,transparent,#38bdf8,transparent); animation: mlwScan 1.8s linear infinite; }
`
