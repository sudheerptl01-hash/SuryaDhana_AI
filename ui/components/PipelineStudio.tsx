'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  ResponsiveContainer,
} from 'recharts'
import {
  createChart, ColorType, CrosshairMode, LineStyle,
  type IChartApi, type ISeriesApi,
} from 'lightweight-charts'
import {
  getPipelineServiceHealth,
  triggerFeatureGeneration,
  getPipelineJobStatus,
  triggerTrainingConfig,
  getFeatureImportance,
  getModelMetrics,
  getRLStatus,
  triggerRLTraining,
  getRLTrainingMetrics,
  getDataQuality,
  getFeatureStats,
  getFeatureCorrelations,
} from '@/lib/api'
import { ModelLab, ConfigModal } from './ModelLab'

// ── TradingView-style line/area chart (lightweight-charts) ────────────────────
interface LWLineChartProps {
  data: { time: number | string; value: number }[]
  color?: string
  height?: number
  label?: string
  fmt?: (v: number) => string
}

function LWLineChart({ data, color = '#f59e0b', height = 280, label, fmt }: LWLineChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)
  const seriesRef    = useRef<ISeriesApi<'Area'> | null>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: '#64748b' },
      grid:   { vertLines: { color: '#1e293b', style: LineStyle.Dashed }, horzLines: { color: '#1e293b', style: LineStyle.Dashed } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1e293b', scaleMargins: { top: 0.1, bottom: 0.05 } },
      timeScale: { borderColor: '#1e293b', timeVisible: false },
      handleScroll: true,
      handleScale:  true,
    })
    const series = chart.addAreaSeries({
      lineColor:    color,
      topColor:     color + '44',
      bottomColor:  color + '00',
      lineWidth:    2,
      priceFormat:  fmt
        ? { type: 'custom', formatter: fmt, minMove: 0.0001 }
        : { type: 'price', precision: 4, minMove: 0.0001 },
    })
    chartRef.current  = chart
    seriesRef.current = series

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.resize(containerRef.current.clientWidth, height)
    })
    ro.observe(containerRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [color, height])

  useEffect(() => {
    if (!seriesRef.current || !data?.length) return
    const pts = data
      .map((d, i) => ({ time: (i + 1) as any, value: typeof d.value === 'number' ? d.value : 0 }))
      .filter(d => isFinite(d.value))
    if (pts.length) seriesRef.current.setData(pts)
  }, [data])

  return (
    <div className="relative">
      {label && <p className="absolute top-0 left-0 text-[10px] font-bold text-slate-400 uppercase tracking-widest z-10">{label}</p>}
      <div ref={containerRef} style={{ height }} />
    </div>
  )
}

// ── PPO RL Config Modal ───────────────────────────────────────────────────────
interface RLConfigModalProps {
  isDark: boolean
  onLaunch: (payload: Record<string, any>) => void
  onClose: () => void
}

function RLConfigModal({ isDark, onLaunch, onClose }: RLConfigModalProps) {
  const today = new Date().toISOString().slice(0, 10)
  const fiveYearsAgo = new Date(new Date().setFullYear(new Date().getFullYear() - 5)).toISOString().slice(0, 10)

  const [totalTimesteps, setTotalTimesteps] = useState(100000)
  const [learningRate, setLearningRate]     = useState(0.0003)
  const [nSteps, setNSteps]                 = useState(2048)
  const [batchSize, setBatchSize]           = useState(64)
  const [nEpochs, setNEpochs]               = useState(10)
  const [nCandidates, setNCandidates]       = useState(15)
  const [maxPositions, setMaxPositions]     = useState(5)
  const [trainStart, setTrainStart]         = useState(fiveYearsAgo)
  const [trainEnd, setTrainEnd]             = useState(today)

  const tx = isDark ? 'text-slate-50'  : 'text-slate-950'
  const mu = isDark ? 'text-slate-500' : 'text-slate-500'
  const div = `border-t ${isDark ? 'border-slate-800' : 'border-slate-200'} pt-6`

  const Slider = ({ label, val, setVal, min, max, step = 1, fmt }: {
    label: string; val: number; setVal: (v: number) => void; min: number; max: number; step?: number; fmt?: (v: number) => string
  }) => (
    <div>
      <div className="flex justify-between mb-1">
        <label className={`text-[11px] font-medium ${mu}`}>{label}</label>
        <span className={`text-[11px] font-mono font-bold ${tx}`}>{fmt ? fmt(val) : val.toLocaleString()}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={val}
        onChange={e => setVal(parseFloat(e.target.value))}
        className="w-full h-1.5 appearance-none rounded-full bg-slate-700 accent-amber-500 cursor-pointer"
      />
      <div className="flex justify-between">
        <span className={`text-[9px] ${mu}`}>{min.toLocaleString()}</span>
        <span className={`text-[9px] ${mu}`}>{max.toLocaleString()}</span>
      </div>
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className={`${isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-slate-200'} border rounded-2xl shadow-2xl w-full max-w-xl max-h-[92vh] overflow-y-auto`}>
        <div className={`flex justify-between items-center px-8 py-5 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'}`}>
          <div>
            <h2 className={`${tx} text-lg font-bold tracking-tight`}>Configure PPO Agent</h2>
            <p className={`${mu} text-xs mt-0.5`}>Stable-Baselines3 Proximal Policy Optimization</p>
          </div>
          <button onClick={onClose} className={`${mu} text-xl hover:text-white transition-colors`}>✕</button>
        </div>

        <div className="px-8 py-6 space-y-6">
          <div>
            <p className="text-rose-400 text-[10px] font-bold uppercase tracking-widest mb-3">Training Date Range</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={`text-[11px] font-medium ${mu} block mb-1`}>Start Date</label>
                <input type="date" value={trainStart} max={trainEnd}
                  onChange={e => setTrainStart(e.target.value)}
                  className={`w-full px-3 py-2 text-xs rounded-lg border font-mono ${isDark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-white border-slate-300 text-slate-800'}`}
                />
              </div>
              <div>
                <label className={`text-[11px] font-medium ${mu} block mb-1`}>End Date</label>
                <input type="date" value={trainEnd} min={trainStart} max={new Date().toISOString().slice(0, 10)}
                  onChange={e => setTrainEnd(e.target.value)}
                  className={`w-full px-3 py-2 text-xs rounded-lg border font-mono ${isDark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-white border-slate-300 text-slate-800'}`}
                />
              </div>
            </div>
            <p className={`${mu} text-[10px] mt-1`}>
              Window: {Math.round((new Date(trainEnd).getTime() - new Date(trainStart).getTime()) / (86400000 * 30))} months
            </p>
          </div>

          <div className={div}>
            <p className="text-amber-400 text-[10px] font-bold uppercase tracking-widest mb-4">Training Budget</p>
            <div className="grid grid-cols-2 gap-6">
              <Slider label="Total Timesteps" val={totalTimesteps} setVal={setTotalTimesteps} min={10000} max={500000} step={10000} />
              <Slider label="N Candidates (stocks)" val={nCandidates} setVal={setNCandidates} min={5} max={50} />
            </div>
          </div>

          <div className={div}>
            <p className="text-violet-400 text-[10px] font-bold uppercase tracking-widest mb-4">PPO Hyperparameters</p>
            <div className="grid grid-cols-2 gap-6">
              <Slider label="Learning Rate" val={learningRate} setVal={setLearningRate} min={0.00001} max={0.01} step={0.00001} fmt={v => v.toExponential(1)} />
              <Slider label="N Steps (rollout)" val={nSteps} setVal={setNSteps} min={256} max={4096} step={256} />
              <Slider label="Batch Size" val={batchSize} setVal={setBatchSize} min={32} max={512} step={32} />
              <Slider label="N Epochs" val={nEpochs} setVal={setNEpochs} min={3} max={20} />
            </div>
          </div>

          <div className={div}>
            <p className="text-teal-400 text-[10px] font-bold uppercase tracking-widest mb-4">Portfolio Constraints</p>
            <div className="grid grid-cols-2 gap-6">
              <Slider label="Max Positions" val={maxPositions} setVal={setMaxPositions} min={1} max={10} />
            </div>
          </div>
        </div>

        <div className={`flex justify-end gap-3 px-8 py-5 border-t ${isDark ? 'border-slate-800' : 'border-slate-200'}`}>
          <button onClick={onClose} className={`px-6 py-2.5 text-sm font-semibold rounded-xl ${isDark ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'} transition`}>Cancel</button>
          <button
            onClick={() => onLaunch({ total_timesteps: totalTimesteps, learning_rate: learningRate, n_steps: nSteps, batch_size: batchSize, n_epochs: nEpochs, n_candidates: nCandidates, max_positions: maxPositions, train_start: trainStart, train_end: trainEnd })}
            className="px-6 py-2.5 text-sm font-bold bg-amber-500 hover:bg-amber-400 text-black rounded-xl transition active:scale-95"
          >▶  Launch PPO Training</button>
        </div>
      </div>
    </div>
  )
}

interface ServiceHealth { service: string; status: 'LIVE' | 'DOWN'; model_loaded?: boolean; message?: string }
interface JobStatus { job_id: string; status: string; progress: number; total: number; elapsed_secs: number; errors_count: number }
interface FeatureImportanceItem { feature: string; importance: number; rank: number }
interface ModelMetrics { accuracy: number; f1_score: number; log_loss: number; auc_roc: number; model_version: string }
interface RLStatus { is_trained: boolean; episode_count: number; avg_reward: number; status: string }
interface DataQuality {
  ohlcv: { total_tickers: number; total_candles: number; min_date: string; max_date: string; avg_candles_per_ticker: number; candle_distribution: { bucket: string; count: number }[]; stale_tickers: { ticker: string; last_date: string }[] }
  features: { tickers_processed: number; total_rows: number; coverage_pct: number; sparse_tickers: number; avg_rows_per_ticker: number }
  labels: { total_labels: number; up_labels: number; down_labels: number; class_balance_pct: number; avg_return_pct: number; std_return_pct: number }
  readiness: { has_ohlcv: boolean; has_features: boolean; has_labels: boolean; ready_to_train: boolean; feature_col_count: number }
}

// ── Feature Inspector Tab (Pillar 2) ─────────────────────────────────────────
function FeatureInspectorTab({
  isDark, card, tx, mu, featureStats, featureCorr, loading,
  sort, approved, watchlist, onLoad, onSortChange, onApprove,
}: {
  isDark: boolean; card: string; tx: string; mu: string
  featureStats: any; featureCorr: any; loading: boolean
  sort: { col: string; asc: boolean }; approved: boolean; watchlist: string[]
  onLoad: () => void; onSortChange: (col: string) => void; onApprove: () => void
}) {
  const features: any[] = featureStats?.features || []
  const corrMatrix: Record<string, Record<string, number>> = featureCorr?.correlation_matrix || {}
  const corrFeatures: string[] = featureCorr?.features || []

  const sorted = [...features].sort((a, b) => {
    const va = a[sort.col] ?? 0
    const vb = b[sort.col] ?? 0
    return sort.asc ? va - vb : vb - va
  })

  const highNaN = features.filter(f => (f.null_pct ?? 0) > 20).length
  const highCorr = Object.entries(corrMatrix).reduce((acc, [f1, row]) => {
    return acc + Object.entries(row).filter(([f2, v]) => f1 < f2 && Math.abs(v) > 0.9).length
  }, 0)
  const canApprove = features.length > 0 && highNaN === 0

  const Th = ({ col, label }: { col: string; label: string }) => (
    <th
      onClick={() => onSortChange(col)}
      className={`px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap ${mu} hover:text-slate-300`}
    >
      {label} {sort.col === col ? (sort.asc ? '↑' : '↓') : '↕'}
    </th>
  )

  return (
    <div className="space-y-6">
      {/* Header with load button */}
      <div className="flex items-start justify-between">
        <div>
          <h2 className={`${tx} text-xl font-bold`}>Pre-Flight Feature Inspector</h2>
          <p className={`${mu} text-xs mt-1`}>Audit NaN rates, variance, and correlations before training. Gate training on a clean inspection.</p>
          {watchlist.length > 0 && (
            <p className="text-xs mt-1 text-emerald-400">
              Watchlist: {watchlist.join(', ')} — inspection scoped to these tickers
            </p>
          )}
        </div>
        <div className="flex gap-3">
          <button
            onClick={onLoad}
            disabled={loading}
            className={`px-5 py-2.5 text-xs font-bold rounded-xl transition-all active:scale-95 ${
              loading ? 'bg-slate-700 text-slate-400 cursor-not-allowed' : 'bg-amber-500 hover:bg-amber-400 text-black'
            }`}
          >
            {loading ? '⟳ Loading…' : features.length > 0 ? '↻ Refresh Stats' : '⚡ Load Feature Stats'}
          </button>
          <button
            onClick={onApprove}
            disabled={!canApprove || approved}
            title={!canApprove ? (features.length === 0 ? 'Load stats first' : `Fix ${highNaN} features with >20% NaNs`) : ''}
            className={`px-5 py-2.5 text-xs font-bold rounded-xl transition-all active:scale-95 ${
              approved ? 'bg-emerald-900/60 text-emerald-400 border border-emerald-700/50' :
              canApprove ? 'bg-emerald-600 hover:bg-emerald-500 text-white' :
              'bg-slate-700 text-slate-500 cursor-not-allowed'
            }`}
          >
            {approved ? '✓ Approved — Proceed' : '✓ Approve & Go to Training'}
          </button>
        </div>
      </div>

      {/* Summary KPIs */}
      {features.length > 0 && (
        <div className="grid grid-cols-4 gap-4">
          {[
            { label: 'Total Features', value: features.length, color: 'text-amber-400' },
            { label: 'High NaN (>20%)', value: highNaN, color: highNaN > 0 ? 'text-rose-400' : 'text-emerald-400' },
            { label: 'High Correlation (>0.9)', value: highCorr, color: highCorr > 5 ? 'text-amber-400' : 'text-emerald-400' },
            { label: 'Inspection Status', value: canApprove ? 'CLEAN' : 'ISSUES', color: canApprove ? 'text-emerald-400' : 'text-rose-400' },
          ].map(k => (
            <div key={k.label} className={`${card} border rounded-xl p-4`}>
              <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-1`}>{k.label}</p>
              <p className={`${k.color} text-2xl font-black font-mono`}>{k.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Feature stats table */}
      {features.length > 0 && (
        <div className={`${card} border rounded-xl overflow-hidden`}>
          <div className={`px-6 py-3 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'}`}>
            <p className={`${tx} text-xs font-bold uppercase tracking-widest`}>Feature Quality Grid — click headers to sort</p>
          </div>
          <div className="overflow-auto max-h-[420px]">
            <table className="w-full text-[11px]">
              <thead className={`sticky top-0 ${isDark ? 'bg-slate-900' : 'bg-slate-100'}`}>
                <tr>
                  <th className={`px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider ${mu}`}>Feature</th>
                  <Th col="null_pct"  label="NaN %" />
                  <Th col="mean"      label="Mean" />
                  <Th col="std"       label="Std Dev" />
                  <Th col="min"       label="Min" />
                  <Th col="max"       label="Max" />
                  <Th col="variance"  label="Variance" />
                </tr>
              </thead>
              <tbody className={`divide-y ${isDark ? 'divide-slate-800/50' : 'divide-slate-100'}`}>
                {sorted.map((f: any) => {
                  const nanPct = f.null_pct ?? 0
                  const isHighNaN = nanPct > 20
                  return (
                    <tr key={f.feature} className={isHighNaN ? (isDark ? 'bg-rose-950/30' : 'bg-rose-50') : ''}>
                      <td className={`px-3 py-1.5 font-mono font-bold ${isHighNaN ? 'text-rose-400' : tx}`}>{f.feature}</td>
                      <td className={`px-3 py-1.5 font-mono ${isHighNaN ? 'text-rose-400 font-bold' : mu}`}>
                        <div className="flex items-center gap-1.5">
                          <div className={`h-1 w-12 rounded-full ${isDark ? 'bg-slate-700' : 'bg-gray-200'} overflow-hidden`}>
                            <div className={`h-full ${nanPct > 20 ? 'bg-rose-500' : nanPct > 5 ? 'bg-amber-400' : 'bg-emerald-500'}`} style={{ width: `${Math.min(nanPct, 100)}%` }} />
                          </div>
                          {nanPct.toFixed(1)}%
                        </div>
                      </td>
                      <td className={`px-3 py-1.5 font-mono ${mu}`}>{(f.mean ?? 0).toFixed(4)}</td>
                      <td className={`px-3 py-1.5 font-mono ${mu}`}>{(f.std ?? 0).toFixed(4)}</td>
                      <td className={`px-3 py-1.5 font-mono ${mu}`}>{(f.min ?? 0).toFixed(4)}</td>
                      <td className={`px-3 py-1.5 font-mono ${mu}`}>{(f.max ?? 0).toFixed(4)}</td>
                      <td className={`px-3 py-1.5 font-mono ${mu}`}>{(f.variance ?? 0).toFixed(6)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Correlation heatmap */}
      {corrFeatures.length > 0 && (
        <div className={`${card} border rounded-xl overflow-hidden`}>
          <div className={`px-6 py-3 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'}`}>
            <p className={`${tx} text-xs font-bold uppercase tracking-widest`}>
              Correlation Heatmap — top {corrFeatures.length} features
            </p>
            <p className={`${mu} text-[10px] mt-0.5`}>Red = high positive, Blue = high negative correlation. Pairs &gt;0.9 may be redundant.</p>
          </div>
          <div className="overflow-auto max-h-[400px] p-4">
            <div style={{ display: 'grid', gridTemplateColumns: `80px repeat(${corrFeatures.length}, 32px)`, gap: 1 }}>
              {/* Header row */}
              <div />
              {corrFeatures.map((f, i) => (
                <div key={i} style={{ writingMode: 'vertical-lr', transform: 'rotate(180deg)' }}
                  className={`text-[8px] font-mono ${mu} h-20 flex items-center justify-center truncate`} title={f}>
                  {f.slice(0, 10)}
                </div>
              ))}
              {/* Data rows */}
              {corrFeatures.map((rowF, ri) => (
                <React.Fragment key={rowF}>
                  <div className={`text-[8px] font-mono ${mu} truncate flex items-center pr-1`} title={rowF}>{rowF.slice(0, 12)}</div>
                  {corrFeatures.map((colF, ci) => {
                    const v = corrMatrix[rowF]?.[colF] ?? corrMatrix[colF]?.[rowF] ?? (ri === ci ? 1 : 0)
                    const abs = Math.abs(v)
                    const bg = v > 0
                      ? `rgba(16,185,129,${0.1 + v * 0.85})`
                      : `rgba(244,63,94,${0.1 + abs * 0.85})`
                    return (
                      <div key={colF} title={`${rowF} ↔ ${colF}: ${v.toFixed(2)}`}
                        style={{ width: 32, height: 32, backgroundColor: bg, borderRadius: 2 }}
                        className="flex items-center justify-center">
                        {abs > 0.5 && <span className="text-[7px] font-mono text-white font-bold">{v.toFixed(1)}</span>}
                      </div>
                    )
                  })}
                </React.Fragment>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!loading && features.length === 0 && (
        <div className={`${card} border rounded-2xl py-20 text-center`}>
          <p className="text-5xl mb-4">🔬</p>
          <p className={`${tx} text-lg font-semibold`}>No feature data loaded</p>
          <p className={`${mu} text-sm mt-2`}>Click "Load Feature Stats" to inspect engineered features before training.</p>
          <p className={`${mu} text-xs mt-1`}>Run Phase 3 (Feature Engineering) first if data is empty.</p>
        </div>
      )}
    </div>
  )
}

export function PipelineStudio({ isDark, watchlist = [] }: { isDark: boolean; watchlist?: string[] }) {
  const [activeTab, setActiveTab] = useState<'quality' | 'inspector' | 'features' | 'model' | 'rl'>('quality')
  const [serviceHealth, setServiceHealth] = useState<Record<string, ServiceHealth>>({})
  const [featureJob, setFeatureJob] = useState<JobStatus | null>(null)
  const [modelJob, setModelJob] = useState<JobStatus | null>(null)
  const [featureImportance, setFeatureImportance] = useState<FeatureImportanceItem[]>([])
  const [modelMetrics, setModelMetrics] = useState<ModelMetrics | null>(null)
  const [rlStatus, setRlStatus] = useState<RLStatus | null>(null)
  const [importanceMode, setImportanceMode] = useState<'mdi' | 'shap'>('mdi')
  const [trainingMetrics, setTrainingMetrics] = useState<any>(null)
  const [isTraining, setIsTraining] = useState(false)
  const [dataQuality, setDataQuality] = useState<DataQuality | null>(null)
  const [showTrainModal, setShowTrainModal] = useState(false)
  const [showRLModal, setShowRLModal] = useState(false)
  const [featureStats, setFeatureStats] = useState<any>(null)
  const [featureCorr, setFeatureCorr] = useState<any>(null)
  const [inspectorLoading, setInspectorLoading] = useState(false)
  const [inspectorSort, setInspectorSort] = useState<{ col: string; asc: boolean }>({ col: 'null_pct', asc: false })
  const [inspectorApproved, setInspectorApproved] = useState(false)

  const bg = isDark ? 'bg-slate-950' : 'bg-white'
  const card = isDark ? 'bg-slate-900/80 border-slate-800' : 'bg-slate-50 border-slate-200'
  const tx = isDark ? 'text-slate-50' : 'text-slate-950'
  const mu = isDark ? 'text-slate-500' : 'text-slate-500'
  const grid = isDark ? '#334155' : '#e2e8f0'
  const axis = isDark ? '#64748b' : '#94a3b8'
  const tooltipBg = isDark ? '#1e293b' : '#ffffff'
  const tooltipBorder = isDark ? '#475569' : '#e2e8f0'

  // Initial load
  useEffect(() => {
    const load = async () => {
      try { setServiceHealth((await getPipelineServiceHealth()).data) } catch {}
      try { setModelMetrics((await getModelMetrics()).data) } catch {}
      try { setFeatureImportance((await getFeatureImportance()).data || []) } catch {}
      try { setDataQuality((await getDataQuality()).data) } catch {}
    }
    load()
  }, [])

  // Poll feature job
  useEffect(() => {
    if (!featureJob || featureJob.status === 'done' || featureJob.status === 'error') return
    const id = setInterval(async () => {
      try {
        const res = await getPipelineJobStatus(featureJob.job_id)
        setFeatureJob(res.data)
        if (res.data.status === 'done') {
          // Reload feature importance + data quality after completion
          try { setFeatureImportance((await getFeatureImportance()).data || []) } catch {}
          try { setDataQuality((await getDataQuality()).data) } catch {}
        }
      } catch {}
    }, 2000)
    return () => clearInterval(id)
  }, [featureJob?.job_id, featureJob?.status])

  // Poll model training job
  useEffect(() => {
    if (!modelJob || modelJob.status === 'done' || modelJob.status === 'error') return
    const id = setInterval(async () => {
      try {
        const res = await getPipelineJobStatus(modelJob.job_id)
        setModelJob(res.data)
        if (res.data.status === 'done') {
          try { setModelMetrics((await getModelMetrics()).data) } catch {}
          try { setFeatureImportance((await getFeatureImportance()).data || []) } catch {}
        }
      } catch {}
    }, 3000)
    return () => clearInterval(id)
  }, [modelJob?.job_id, modelJob?.status])

  // Poll RL metrics
  useEffect(() => {
    const id = setInterval(async () => {
      try {
        const res = await getRLTrainingMetrics()
        setTrainingMetrics(res.data)
        setIsTraining(res.data?.status === 'training')
      } catch {}
    }, 2000)
    return () => clearInterval(id)
  }, [])

  // Poll RL status
  useEffect(() => {
    const id = setInterval(async () => {
      try { setRlStatus((await getRLStatus()).data) } catch {}
    }, 10000)
    return () => clearInterval(id)
  }, [])

  const handleRunFeatures = async () => {
    try {
      const res = await triggerFeatureGeneration()
      setFeatureJob(res.data)
    } catch (e) { console.error(e) }
  }

  const handleTrainModel = async (payload: Record<string, any>) => {
    setShowTrainModal(false)
    try {
      const res = await triggerTrainingConfig(payload)
      setModelJob(res.data)
    } catch (e) { console.error(e) }
  }

  const handleRLTrain = async (payload: Record<string, any>) => {
    setShowRLModal(false)
    try { await triggerRLTraining(payload) } catch (e) { console.error(e) }
  }

  const svcStatus = (name: string) => {
    const h = serviceHealth[name]
    if (!h) return { label: '—', cls: mu }
    return h.status === 'LIVE'
      ? { label: '● LIVE', cls: 'text-emerald-500' }
      : { label: '● DOWN', cls: 'text-red-500' }
  }

  const CATEGORY_COLOR: Record<string, string> = {
    rsi: '#f59e0b', macd: '#f59e0b', stoch: '#f59e0b', roc: '#f59e0b', williams: '#f59e0b', return_lag: '#f59e0b', is_green: '#f59e0b',
    sma: '#14b8a6', ema: '#14b8a6', price_vs: '#14b8a6', uptrend: '#14b8a6',
    volume: '#8b5cf6', obv: '#8b5cf6', mfi: '#8b5cf6', cmf: '#8b5cf6',
    bb: '#64748b', atr: '#64748b', hist_vol: '#64748b', high_low: '#64748b', close_pos: '#64748b', gap: '#64748b',
  }
  const featureColor = (f: string) => {
    const k = Object.keys(CATEGORY_COLOR).find(k => f.toLowerCase().startsWith(k))
    return k ? CATEGORY_COLOR[k] : '#f59e0b'
  }

  const ttStyle = { backgroundColor: tooltipBg, border: `1px solid ${tooltipBorder}`, borderRadius: '6px', fontSize: 12 }

  const isFeatureRunning = featureJob?.status === 'running'
  const isModelRunning = modelJob?.status === 'running'

  // ── SIDEBAR (shared across feature/model tabs) ─────────────────────────────
  const Sidebar = () => (
    <div className={`${card} border rounded-xl p-6 space-y-8 h-fit`}>
      {/* Service Health */}
      <div>
        <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-4`}>Service Health</p>
        <div className="space-y-2.5">
          {['data-service', 'feature-service', 'ml-service', 'rl-service'].map(s => {
            const { label, cls } = svcStatus(s)
            return (
              <div key={s} className="flex justify-between items-center">
                <span className={`${mu} text-xs`}>{s}</span>
                <span className={`${cls} text-xs font-semibold font-mono`}>{label}</span>
              </div>
            )
          })}
        </div>
      </div>

      {/* Phase 3 */}
      <div className="border-t border-slate-800 pt-6">
        <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-4`}>Phase 3 — Features</p>
        <button
          onClick={handleRunFeatures}
          disabled={isFeatureRunning}
          className={`w-full px-4 py-2.5 text-xs font-bold rounded-lg transition-all active:scale-95 ${
            isFeatureRunning
              ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
              : 'bg-amber-500 hover:bg-amber-400 text-black'
          }`}
        >
          {isFeatureRunning ? '⟳  Computing…' : '▶  Run Feature Pipeline'}
        </button>
        {featureJob && (
          <div className="mt-4 space-y-2">
            <div className={`flex justify-between text-[11px] font-mono ${mu}`}>
              <span>{featureJob.progress} / {featureJob.total} stocks</span>
              <span className={featureJob.status === 'done' ? 'text-emerald-400' : featureJob.status === 'error' ? 'text-red-400' : 'text-amber-400'}>
                {featureJob.status === 'done' ? '✓ Done' : featureJob.status === 'error' ? '✗ Error' : `${Math.round(featureJob.elapsed_secs)}s`}
              </span>
            </div>
            <div className={`w-full h-1.5 ${isDark ? 'bg-slate-800' : 'bg-slate-200'} rounded-full overflow-hidden`}>
              <div
                className={`h-full rounded-full transition-all duration-500 ${featureJob.status === 'error' ? 'bg-red-500' : 'bg-amber-500'}`}
                style={{ width: `${featureJob.total > 0 ? (featureJob.progress / featureJob.total) * 100 : 0}%` }}
              />
            </div>
            {featureJob.errors_count > 0 && (
              <p className="text-[10px] text-red-400 font-mono">{featureJob.errors_count} errors</p>
            )}
          </div>
        )}
      </div>

      {/* Phase 4 */}
      <div className="border-t border-slate-800 pt-6">
        <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-4`}>Phase 4 — ML Model</p>
        <button
          onClick={() => !isModelRunning && setShowTrainModal(true)}
          disabled={isModelRunning}
          className={`w-full px-4 py-2.5 text-xs font-bold rounded-lg transition-all active:scale-95 ${
            isModelRunning
              ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
              : 'bg-violet-600 hover:bg-violet-500 text-white'
          }`}
        >
          {isModelRunning ? '⟳  Training…' : '⚙  Configure & Train XGBoost ↗'}
        </button>
        {modelJob && (
          <div className="mt-4 space-y-2">
            <div className={`flex justify-between text-[11px] font-mono ${mu}`}>
              <span>XGBoost</span>
              <span className={modelJob.status === 'done' ? 'text-emerald-400' : modelJob.status === 'error' ? 'text-red-400' : 'text-violet-400'}>
                {modelJob.status === 'done' ? '✓ Trained' : modelJob.status === 'error' ? '✗ Failed' : `${Math.round(modelJob.elapsed_secs)}s`}
              </span>
            </div>
            <div className={`w-full h-1.5 ${isDark ? 'bg-slate-800' : 'bg-slate-200'} rounded-full overflow-hidden`}>
              <div
                className={`h-full rounded-full transition-all duration-500 ${modelJob.status === 'error' ? 'bg-red-500' : 'bg-violet-500'}`}
                style={{ width: `${modelJob.status === 'done' ? 100 : modelJob.status === 'running' ? Math.min(modelJob.progress + 5, 95) : 0}%` }}
              />
            </div>
            {modelJob.status === 'error' && (
              <p className="text-[10px] text-red-400 font-mono">Run Phase 3 first if no training data</p>
            )}
          </div>
        )}
        <div className={`mt-4 text-[11px] font-mono ${mu} space-y-1`}>
          <div className="flex justify-between">
            <span>Status</span>
            <span className={tx}>{modelMetrics?.model_version || 'untrained'}</span>
          </div>
          {modelMetrics && modelMetrics.accuracy > 0 && (
            <div className="flex justify-between">
              <span>Accuracy</span>
              <span className="text-emerald-400">{(modelMetrics.accuracy * 100).toFixed(1)}%</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )

  return (
    <div className={`${bg} rounded-xl`}>
      {/* Training Modals */}
      {showTrainModal && (
        <ConfigModal
          isDark={isDark}
          initialModelType="xgboost"
          onLaunch={handleTrainModel}
          onClose={() => setShowTrainModal(false)}
        />
      )}
      {showRLModal && (
        <RLConfigModal
          isDark={isDark}
          onLaunch={handleRLTrain}
          onClose={() => setShowRLModal(false)}
        />
      )}

      {/* Header */}
      <div className={`border-b ${isDark ? 'border-slate-800' : 'border-slate-200'} px-8 py-6`}>
        <h1 className={`${tx} text-2xl font-semibold tracking-tight`}>Quantitative Pipeline</h1>
        <p className={`${mu} text-sm mt-1`}>Data quality · Feature engineering · Model training · RL optimization</p>
      </div>

      {/* Tab Bar */}
      <div className={`px-8 flex gap-0 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'} overflow-x-auto`}>
        {([
          { key: 'quality',    label: 'Data Quality' },
          { key: 'inspector',  label: '🔬 Feature Inspector' },
          { key: 'features',   label: 'Feature Engineering' },
          { key: 'model',      label: 'Model Studio' },
          { key: 'rl',         label: 'RL Agent' },
        ] as const).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`px-5 py-3.5 text-xs font-semibold uppercase tracking-wider transition-colors border-b-2 ${
              activeTab === key
                ? 'border-amber-500 text-amber-500'
                : `border-transparent ${mu} hover:text-slate-300`
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      <div className="p-8">

        {/* ── FEATURE INSPECTOR TAB ─────────────────────────────────────── */}
        {activeTab === 'inspector' && (
          <FeatureInspectorTab
            isDark={isDark}
            card={card}
            tx={tx}
            mu={mu}
            featureStats={featureStats}
            featureCorr={featureCorr}
            loading={inspectorLoading}
            sort={inspectorSort}
            approved={inspectorApproved}
            watchlist={watchlist}
            onLoad={async () => {
              setInspectorLoading(true)
              try {
                const [s, c] = await Promise.all([getFeatureStats(), getFeatureCorrelations()])
                setFeatureStats(s.data)
                setFeatureCorr(c.data)
              } catch {}
              finally { setInspectorLoading(false) }
            }}
            onSortChange={(col) => setInspectorSort(prev => ({ col, asc: prev.col === col ? !prev.asc : false }))}
            onApprove={() => { setInspectorApproved(true); setActiveTab('features') }}
          />
        )}

        {/* ── FEATURES TAB ─────────────────────────────────────────────── */}
        {activeTab === 'features' && (
          <div className="grid grid-cols-[300px_1fr] gap-8">
            <Sidebar />
            <div className="space-y-6">
              {/* KPI row */}
              <div className="grid grid-cols-4 gap-4">
                {[
                  { label: 'Stocks', value: dataQuality?.ohlcv.total_tickers || featureJob?.total || '—' },
                  { label: 'Features Built', value: dataQuality?.features.tickers_processed || '—' },
                  { label: 'Model', value: modelMetrics?.model_version || 'untrained' },
                  { label: 'Coverage', value: dataQuality ? `${dataQuality.features.coverage_pct}%` : '—' },
                ].map((k, i) => (
                  <div key={i} className={`${card} border rounded-xl p-4`}>
                    <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-2`}>{k.label}</p>
                    <p className={`${tx} text-xl font-bold font-mono`}>{String(k.value)}</p>
                  </div>
                ))}
              </div>

              {/* Feature Importance */}
              <div className={`${card} border rounded-xl p-6`}>
                <div className="flex justify-between items-center mb-5">
                  <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Feature Importance — Top 20</h3>
                  <div className="flex gap-2">
                    {(['mdi', 'shap'] as const).map(m => (
                      <button
                        key={m}
                        onClick={() => setImportanceMode(m)}
                        className={`px-3 py-1 text-[10px] font-bold uppercase rounded-md transition ${
                          importanceMode === m
                            ? 'bg-amber-500 text-black'
                            : isDark ? 'bg-slate-800 text-slate-400 hover:bg-slate-700' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                        }`}
                      >
                        {m}
                      </button>
                    ))}
                  </div>
                </div>

                {featureImportance.length > 0 ? (
                  <ResponsiveContainer width="100%" height={360}>
                    <BarChart layout="vertical" data={featureImportance.slice(0, 20)} margin={{ top: 0, right: 24, left: 150, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="4 2" stroke={grid} vertical={false} />
                      <XAxis type="number" domain={[0, 1]} stroke={axis} tick={{ fontSize: 11 }} />
                      <YAxis dataKey="feature" type="category" width={145} stroke={axis} tick={{ fontSize: 11, fontFamily: 'monospace' }} />
                      <Tooltip contentStyle={ttStyle} formatter={(v: any) => [(v as number).toFixed(4), 'Importance']} />
                      <Bar dataKey="importance" radius={[0, 3, 3, 0]}>
                        {featureImportance.slice(0, 20).map((e, i) => (
                          <Cell key={i} fill={featureColor(e.feature)} opacity={0.9} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className={`py-16 text-center ${mu}`}>
                    <p className="text-3xl mb-3">📊</p>
                    <p className="text-sm font-medium">No model trained yet</p>
                    <p className="text-xs mt-1">Run Phase 3 → Phase 4 to generate feature importance</p>
                  </div>
                )}

                {/* Legend */}
                {featureImportance.length > 0 && (
                  <div className="flex gap-6 mt-4 pt-4 border-t border-slate-800">
                    {[
                      { color: '#f59e0b', label: 'Momentum' },
                      { color: '#14b8a6', label: 'Trend' },
                      { color: '#8b5cf6', label: 'Volume' },
                      { color: '#64748b', label: 'Volatility' },
                    ].map(l => (
                      <div key={l.label} className="flex items-center gap-1.5">
                        <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: l.color }} />
                        <span className={`text-[10px] ${mu} font-medium`}>{l.label}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Classification Metrics */}
              <div className={`${card} border rounded-xl p-6`}>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>Out-of-Sample Metrics</h3>
                <div className="grid grid-cols-4 gap-4">
                  {[
                    { label: 'Accuracy', value: modelMetrics?.accuracy || 0, color: 'text-emerald-400', threshold: 0.55 },
                    { label: 'F1-Score', value: modelMetrics?.f1_score || 0, color: 'text-amber-400', threshold: 0.5 },
                    { label: 'Log-Loss', value: modelMetrics?.log_loss || 0, color: 'text-violet-400', threshold: 0 },
                    { label: 'AUC-ROC', value: modelMetrics?.auc_roc || 0, color: 'text-teal-400', threshold: 0.6 },
                  ].map((m, i) => (
                    <div key={i} className={`${isDark ? 'bg-slate-950' : 'bg-slate-100'} rounded-lg p-4 text-center`}>
                      <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-2`}>{m.label}</p>
                      <p className={`text-2xl font-bold font-mono ${m.value > 0 ? m.color : mu}`}>
                        {m.value > 0 ? m.value.toFixed(3) : '—'}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── MODEL LAB TAB ─────────────────────────────────────────────── */}
        {activeTab === 'model' && (
          <div className="grid grid-cols-[300px_1fr] gap-8">
            <Sidebar />
            <ModelLab
              isDark={isDark}
              featureImportance={featureImportance}
              modelMetrics={modelMetrics}
              onMetricsRefresh={async () => {
                try { setModelMetrics((await getModelMetrics()).data) } catch {}
                try { setFeatureImportance((await getFeatureImportance()).data || []) } catch {}
              }}
            />
          </div>
        )}

        {/* ── RL AGENT TAB ─────────────────────────────────────────────── */}
        {activeTab === 'rl' && (
          <div className="grid grid-cols-[280px_1fr] gap-8">
            {/* RL Sidebar */}
            <div className={`${card} border rounded-xl p-6 space-y-8 h-fit`}>
              {/* Agent status */}
              <div>
                <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-4`}>Agent Status</p>
                <div className="flex items-center gap-2.5 mb-3">
                  <span className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${isTraining ? 'bg-amber-400 animate-pulse' : rlStatus?.is_trained ? 'bg-emerald-400' : 'bg-slate-500'}`} />
                  <span className={`text-xs font-semibold ${isTraining ? 'text-amber-400' : rlStatus?.is_trained ? 'text-emerald-400' : mu}`}>
                    {isTraining ? 'Training in progress…' : rlStatus?.is_trained ? 'Agent trained & ready' : 'Untrained — awaiting run'}
                  </span>
                </div>
                {rlStatus && (
                  <div className="space-y-1.5">
                    {[
                      { label: 'Episodes', value: String(rlStatus.episode_count || 0) },
                      { label: 'Avg Reward', value: (rlStatus.avg_reward || 0).toFixed(4), color: (rlStatus.avg_reward || 0) > 0 ? 'text-emerald-400' : 'text-rose-400' },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="flex justify-between items-center text-xs">
                        <span className={mu}>{label}</span>
                        <span className={`font-mono font-semibold ${color || tx}`}>{value}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* PPO Launch */}
              <div className="border-t border-slate-800 pt-6">
                <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-4`}>PPO Agent</p>
                <button
                  onClick={() => !isTraining && setShowRLModal(true)}
                  disabled={isTraining}
                  className={`w-full px-4 py-2.5 text-xs font-bold rounded-lg transition-all active:scale-95 ${
                    isTraining
                      ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                      : 'bg-amber-500 hover:bg-amber-400 text-black'
                  }`}
                >
                  {isTraining ? '⟳  Training…' : '⚙  Configure & Train PPO ↗'}
                </button>
                <p className={`${mu} text-[10px] mt-3`}>Stable-Baselines3 · Portfolio environment · Sortino-optimized reward</p>
              </div>

              {/* Latest snapshot */}
              {trainingMetrics?.metrics?.length > 0 && (() => {
                const latest = trainingMetrics.metrics[trainingMetrics.metrics.length - 1]
                return (
                  <div className="border-t border-slate-800 pt-6 space-y-2">
                    <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-3`}>Latest Checkpoint</p>
                    {[
                      { label: 'Timesteps', value: `${((latest.timestep || 0) / 1000).toFixed(0)}K`, color: 'text-amber-400' },
                      { label: 'Avg Reward', value: (latest.avg_reward || 0).toFixed(4), color: (latest.avg_reward || 0) > 0 ? 'text-emerald-400' : 'text-rose-400' },
                      { label: 'Portfolio', value: `${(latest.portfolio_value || 1).toFixed(3)}x`, color: 'text-violet-400' },
                      { label: 'Sortino', value: (latest.sortino_ratio || 0).toFixed(2), color: 'text-teal-400' },
                    ].map(({ label, value, color }) => (
                      <div key={label} className="flex justify-between items-center text-xs">
                        <span className={mu}>{label}</span>
                        <span className={`font-mono font-bold ${color}`}>{value}</span>
                      </div>
                    ))}
                  </div>
                )
              })()}
            </div>

            {/* RL Main Panel */}
            <div className="space-y-6">
              {/* KPI row */}
              {trainingMetrics?.metrics?.length > 0 && (() => {
                const latest = trainingMetrics.metrics[trainingMetrics.metrics.length - 1]
                return (
                  <div className="grid grid-cols-4 gap-4">
                    {[
                      { label: 'Timesteps', value: `${((latest.timestep || 0) / 1000).toFixed(0)}K`, bg: 'bg-amber-500/10', fg: 'text-amber-400' },
                      { label: 'Episodes', value: String(latest.episode || 0), bg: 'bg-slate-700/30', fg: tx },
                      { label: 'Avg Reward', value: (latest.avg_reward || 0).toFixed(4), bg: (latest.avg_reward || 0) > 0 ? 'bg-emerald-500/10' : 'bg-rose-500/10', fg: (latest.avg_reward || 0) > 0 ? 'text-emerald-400' : 'text-rose-400' },
                      { label: 'Sortino', value: (latest.sortino_ratio || 0).toFixed(2), bg: 'bg-violet-500/10', fg: 'text-violet-400' },
                    ].map(({ label, value, bg, fg }) => (
                      <div key={label} className={`${card} border rounded-xl p-4 ${bg}`}>
                        <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-2`}>{label}</p>
                        <p className={`text-2xl font-bold font-mono ${fg}`}>{value}</p>
                      </div>
                    ))}
                  </div>
                )
              })()}

              {trainingMetrics?.metrics?.length > 0 ? (
                /* Side-by-side TradingView-style charts */
                <div className="grid grid-cols-2 gap-6">
                  <div className={`${card} border rounded-xl p-6`}>
                    <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>Reward Convergence</h3>
                    <LWLineChart
                      height={280}
                      color="#f59e0b"
                      data={trainingMetrics.metrics.map((m: any) => ({ time: m.episode ?? m.timestep ?? 0, value: m.avg_reward ?? 0 }))}
                      fmt={v => v.toFixed(4)}
                    />
                  </div>
                  <div className={`${card} border rounded-xl p-6`}>
                    <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>Portfolio Value</h3>
                    <LWLineChart
                      height={280}
                      color="#10b981"
                      data={trainingMetrics.metrics.map((m: any) => ({ time: m.episode ?? m.timestep ?? 0, value: m.portfolio_value ?? 1.0 }))}
                      fmt={v => v.toFixed(3) + 'x'}
                    />
                  </div>
                </div>
              ) : (
                <div className={`${card} border rounded-xl p-20 text-center ${mu}`}>
                  <p className="text-5xl mb-4">🤖</p>
                  <p className="text-sm font-semibold mb-1">PPO Agent — Awaiting Training</p>
                  <p className="text-xs">Click <span className="text-amber-400 font-semibold">⚙ Configure & Train PPO ↗</span> in the sidebar to begin. Reward and portfolio curves appear in real-time.</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── DATA QUALITY TAB ─────────────────────────────────────────── */}
        {activeTab === 'quality' && (
          <div className="space-y-6">
            {/* Readiness Checklist */}
            <div className={`${card} border rounded-xl p-6`}>
              <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>Pipeline Readiness</h3>
              <div className="grid grid-cols-4 gap-4">
                {[
                  { label: 'OHLCV Data', ok: dataQuality?.readiness.has_ohlcv, desc: `${dataQuality?.ohlcv.total_candles?.toLocaleString() || 0} candles` },
                  { label: 'Features', ok: dataQuality?.readiness.has_features, desc: `${dataQuality?.features.tickers_processed || 0} tickers processed` },
                  { label: 'Labels', ok: dataQuality?.readiness.has_labels, desc: `${dataQuality?.labels.total_labels?.toLocaleString() || 0} labels` },
                  { label: 'Ready to Train', ok: dataQuality?.readiness.ready_to_train, desc: dataQuality?.readiness.ready_to_train ? 'All requirements met' : 'Run Phase 3 first' },
                ].map(({ label, ok, desc }, i) => (
                  <div key={i} className={`rounded-xl p-4 border ${ok ? 'border-emerald-500/30 bg-emerald-500/5' : 'border-slate-700 bg-slate-800/30'}`}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`text-base ${ok ? 'text-emerald-400' : 'text-slate-500'}`}>{ok ? '✓' : '○'}</span>
                      <span className={`text-xs font-bold ${ok ? 'text-emerald-300' : mu}`}>{label}</span>
                    </div>
                    <p className={`text-[11px] ${mu} font-mono`}>{desc}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Two-column: OHLCV stats + Label Distribution */}
            <div className="grid grid-cols-2 gap-6">
              {/* OHLCV Coverage */}
              <div className={`${card} border rounded-xl p-6`}>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>OHLCV Coverage</h3>
                <div className="space-y-3 mb-6">
                  {[
                    { label: 'Total Tickers', value: dataQuality?.ohlcv.total_tickers || '—' },
                    { label: 'Total Candles', value: dataQuality?.ohlcv.total_candles?.toLocaleString() || '—' },
                    { label: 'Avg / Ticker', value: dataQuality?.ohlcv.avg_candles_per_ticker?.toLocaleString() || '—' },
                    { label: 'Date Range', value: dataQuality ? `${dataQuality.ohlcv.min_date} → ${dataQuality.ohlcv.max_date}` : '—' },
                  ].map(({ label, value }, i) => (
                    <div key={i} className="flex justify-between items-center text-xs">
                      <span className={mu}>{label}</span>
                      <span className={`${tx} font-mono font-semibold`}>{String(value)}</span>
                    </div>
                  ))}
                </div>

                {dataQuality?.ohlcv.candle_distribution && (
                  <>
                    <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-3`}>Candle Count Distribution</p>
                    <ResponsiveContainer width="100%" height={160}>
                      <BarChart data={dataQuality.ohlcv.candle_distribution} margin={{ top: 0, right: 0, left: -20, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="4 2" stroke={grid} vertical={false} />
                        <XAxis dataKey="bucket" stroke={axis} tick={{ fontSize: 10 }} />
                        <YAxis stroke={axis} tick={{ fontSize: 10 }} />
                        <Tooltip contentStyle={ttStyle} formatter={(v: any) => [v, 'Tickers']} />
                        <Bar dataKey="count" fill="#f59e0b" opacity={0.8} radius={[3, 3, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </>
                )}
              </div>

              {/* Label Distribution */}
              <div className={`${card} border rounded-xl p-6`}>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>Label Distribution</h3>

                {dataQuality?.labels.total_labels ? (
                  <>
                    <div className="space-y-3 mb-6">
                      {[
                        { label: 'Total Labels', value: dataQuality.labels.total_labels.toLocaleString() },
                        { label: 'Up (Bullish)', value: dataQuality.labels.up_labels.toLocaleString(), color: 'text-emerald-400' },
                        { label: 'Down (Bearish)', value: dataQuality.labels.down_labels.toLocaleString(), color: 'text-rose-400' },
                        { label: 'Class Balance', value: `${dataQuality.labels.class_balance_pct}% up`, color: Math.abs(dataQuality.labels.class_balance_pct - 50) < 10 ? 'text-emerald-400' : 'text-amber-400' },
                        { label: 'Avg 5D Return', value: `${dataQuality.labels.avg_return_pct > 0 ? '+' : ''}${dataQuality.labels.avg_return_pct.toFixed(3)}%` },
                        { label: 'Std Dev Return', value: `±${dataQuality.labels.std_return_pct.toFixed(3)}%` },
                      ].map(({ label, value, color }, i) => (
                        <div key={i} className="flex justify-between items-center text-xs">
                          <span className={mu}>{label}</span>
                          <span className={`font-mono font-semibold ${color || tx}`}>{value}</span>
                        </div>
                      ))}
                    </div>

                    {/* Class balance visual */}
                    <div className="mt-4">
                      <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-2`}>Class Balance</p>
                      <div className="flex h-4 rounded-full overflow-hidden">
                        <div
                          className="bg-emerald-500 transition-all"
                          style={{ width: `${dataQuality.labels.class_balance_pct}%` }}
                        />
                        <div
                          className="bg-rose-500 transition-all"
                          style={{ width: `${100 - dataQuality.labels.class_balance_pct}%` }}
                        />
                      </div>
                      <div className="flex justify-between text-[10px] mt-1">
                        <span className="text-emerald-400 font-mono">{dataQuality.labels.class_balance_pct}% UP</span>
                        <span className="text-rose-400 font-mono">{(100 - dataQuality.labels.class_balance_pct).toFixed(1)}% DOWN</span>
                      </div>
                      {Math.abs(dataQuality.labels.class_balance_pct - 50) > 10 && (
                        <p className="text-amber-400 text-[10px] mt-2 font-mono">⚠ Class imbalance detected — consider weighting or resampling</p>
                      )}
                    </div>
                  </>
                ) : (
                  <div className={`py-10 text-center ${mu}`}>
                    <p className="text-3xl mb-3">🏷</p>
                    <p className="text-sm font-medium">No labels yet</p>
                    <p className="text-xs mt-1">Run Phase 3 to generate 5-day forward return labels</p>
                  </div>
                )}
              </div>
            </div>

            {/* Feature Coverage */}
            <div className={`${card} border rounded-xl p-6`}>
              <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>Feature Engineering Coverage</h3>
              <div className="grid grid-cols-5 gap-4 mb-6">
                {[
                  { label: 'Tickers Processed', value: dataQuality?.features.tickers_processed || 0 },
                  { label: 'Total Feature Rows', value: dataQuality?.features.total_rows?.toLocaleString() || '0' },
                  { label: 'Coverage', value: `${dataQuality?.features.coverage_pct || 0}%` },
                  { label: 'Sparse Tickers (<100 rows)', value: dataQuality?.features.sparse_tickers || 0 },
                  { label: 'Avg Rows / Ticker', value: dataQuality?.features.avg_rows_per_ticker || '—' },
                ].map(({ label, value }, i) => (
                  <div key={i} className={`${isDark ? 'bg-slate-950' : 'bg-slate-100'} rounded-lg p-4 text-center`}>
                    <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-2`}>{label}</p>
                    <p className={`${tx} text-xl font-bold font-mono`}>{String(value)}</p>
                  </div>
                ))}
              </div>

              {/* Coverage bar */}
              {dataQuality && (
                <>
                  <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-2`}>
                    Feature Pipeline Coverage ({dataQuality.features.tickers_processed} / {dataQuality.ohlcv.total_tickers} tickers)
                  </p>
                  <div className={`h-3 ${isDark ? 'bg-slate-800' : 'bg-slate-200'} rounded-full overflow-hidden`}>
                    <div
                      className="h-full bg-amber-500 rounded-full transition-all duration-700"
                      style={{ width: `${dataQuality.features.coverage_pct}%` }}
                    />
                  </div>
                  <p className={`${mu} text-[10px] font-mono mt-1`}>{dataQuality.features.coverage_pct}% complete — {dataQuality.ohlcv.total_tickers - dataQuality.features.tickers_processed} tickers pending</p>
                </>
              )}

              <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mt-6 mb-3`}>Feature Catalog ({dataQuality?.readiness.feature_col_count || 38} indicators)</p>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { name: 'RSI-14', cat: 'momentum' }, { name: 'RSI-7', cat: 'momentum' }, { name: 'RSI-28', cat: 'momentum' },
                  { name: 'MACD', cat: 'momentum' }, { name: 'MACD Signal', cat: 'momentum' }, { name: 'Stoch-K', cat: 'momentum' },
                  { name: 'ROC-5', cat: 'momentum' }, { name: 'ROC-20', cat: 'momentum' }, { name: 'Williams-R', cat: 'momentum' },
                  { name: 'SMA Ratio', cat: 'trend' }, { name: 'EMA Ratio', cat: 'trend' }, { name: 'Price/SMA20', cat: 'trend' },
                  { name: 'Uptrend 20/50', cat: 'trend' }, { name: 'Uptrend 50/200', cat: 'trend' },
                  { name: 'BB Width', cat: 'volatility' }, { name: 'BB %B', cat: 'volatility' }, { name: 'ATR%', cat: 'volatility' },
                  { name: 'Hist Vol', cat: 'volatility' }, { name: 'H/L Ratio', cat: 'volatility' },
                  { name: 'Volume Ratio', cat: 'volume' }, { name: 'OBV/SMA', cat: 'volume' }, { name: 'MFI-14', cat: 'volume' },
                  { name: 'CMF-20', cat: 'volume' }, { name: 'Vol Spike', cat: 'volume' },
                ].map(({ name, cat }) => {
                  const catColor: Record<string, string> = {
                    momentum: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
                    trend: 'bg-teal-500/15 text-teal-300 border-teal-500/30',
                    volatility: 'bg-slate-500/20 text-slate-300 border-slate-500/30',
                    volume: 'bg-violet-500/15 text-violet-300 border-violet-500/30',
                  }
                  return (
                    <span key={name} className={`text-[10px] px-2 py-0.5 rounded-md border font-mono ${catColor[cat] || ''}`}>
                      {name}
                    </span>
                  )
                })}
              </div>
            </div>

            {/* Stale tickers */}
            {dataQuality?.ohlcv.stale_tickers && dataQuality.ohlcv.stale_tickers.length > 0 && (
              <div className={`${card} border rounded-xl p-6`}>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-4`}>Stale Data — Oldest 10 Tickers</h3>
                <div className="grid grid-cols-5 gap-3">
                  {dataQuality.ohlcv.stale_tickers.map(({ ticker, last_date }) => (
                    <div key={ticker} className={`${isDark ? 'bg-slate-950' : 'bg-slate-100'} rounded-lg p-3`}>
                      <p className={`${tx} text-xs font-bold font-mono`}>{ticker}</p>
                      <p className={`${mu} text-[10px] mt-0.5`}>{last_date}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
