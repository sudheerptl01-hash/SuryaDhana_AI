'use client'

import React, { useEffect, useState, useCallback, useRef } from 'react'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import { T } from '@/components/terminal'   // T.muted for axis text (RUP-06: one muted grey)
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell,
  LineChart, Line, ReferenceLine, ResponsiveContainer,
} from 'recharts'
import {
  getConfusionMatrix, getRocCurve, getScoreDistribution, getCalibration,
  getModelParams, getShapGlobal, getPDP, getFeatureStats,
  getFeatureCorrelations, getFeatureDistribution,
  triggerTrainingConfig, getPipelineJobStatus, getModelMetrics, getFeatureImportance,
  getModelCatalog, getModelRegistry, activateModel, deleteModel,
  getShapBeeswarm, getShapWaterfall, ML_TRAIN_STREAM_URL,
} from '@/lib/api'
import { TrainingTerminal } from './TrainingTerminal'

type ModelLabTab = 'overview' | 'explainability' | 'diagnostics' | 'features' | 'correlations' | 'catalog'

interface Props {
  isDark: boolean
  featureImportance: Array<{ feature: string; importance: number; rank: number }>
  modelMetrics: { accuracy: number; f1_score: number; log_loss: number; auc_roc: number; model_version: string } | null
  onMetricsRefresh: () => void
}

// ── Feature categories ────────────────────────────────────────────────────────
const FEATURE_CATEGORIES: Record<string, string[]> = {
  Trend:     ['sma_ratio_20_50','ema_ratio_12_26','price_vs_sma20','price_vs_sma50','uptrend_20_50','uptrend_50_200'],
  Momentum:  ['macd','macd_signal','macd_hist','rsi_14','rsi_28','rsi_7','stoch_k','stoch_d','roc_5','roc_10','roc_20','williams_r','return_lag_1d','return_lag_2d','return_lag_3d','return_lag_5d','return_lag_10d','is_green_candle'],
  Volatility:['bb_width','bb_pct','atr_14_pct','hist_vol_20','high_low_ratio','close_position','gap_pct'],
  Volume:    ['volume_ratio','obv_sma_20','mfi_14','cmf_20','volume_spike'],
  Calendar:  ['day_of_week','month'],
}
const ALL_FEATURES = Object.values(FEATURE_CATEGORIES).flat()

const CAT_COLORS: Record<string, string> = {
  Trend: '#14b8a6', Momentum: '#ffb000', Volatility: '#6f7a8e', Volume: '#8b5cf6', Calendar: '#ec4899',
}

// ── Color helpers ─────────────────────────────────────────────────────────────
const CATEGORY_COLOR: Record<string, string> = {
  rsi: '#ffb000', macd: '#ffb000', stoch: '#ffb000', roc: '#ffb000',
  williams: '#ffb000', return_lag: '#ffb000', is_green: '#ffb000',
  sma: '#14b8a6', ema: '#14b8a6', price_vs: '#14b8a6', uptrend: '#14b8a6',
  volume: '#8b5cf6', obv: '#8b5cf6', mfi: '#8b5cf6', cmf: '#8b5cf6',
  bb: '#6f7a8e', atr: '#6f7a8e', hist_vol: '#6f7a8e',
  high_low: '#6f7a8e', close_pos: '#6f7a8e', gap: '#6f7a8e',
  day_of: '#ec4899', month: '#ec4899',
}
const featColor = (f: string) => {
  const k = Object.keys(CATEGORY_COLOR).find(k => f.toLowerCase().startsWith(k))
  return k ? CATEGORY_COLOR[k] : '#ffb000'
}

function corrColor(v: number): string {
  const c = Math.max(-1, Math.min(1, v))
  if (c > 0) return `rgba(16,185,129,${0.15 + c * 0.75})`
  return `rgba(244,63,94,${0.15 + (-c) * 0.75})`
}

function shapDotColor(norm: number): string {
  // blue → white → red  (SHAP beeswarm convention)
  if (norm < 0.5) {
    const t = norm * 2
    return `rgb(${Math.round(t * 170)},${Math.round(130 + t * 50)},${Math.round(220 - t * 30)})`
  }
  const t = (norm - 0.5) * 2
  return `rgb(${Math.round(170 + t * 85)},${Math.round(180 - t * 130)},${Math.round(190 - t * 155)})`
}

// ── Model type metadata (mirrors backend catalog) ─────────────────────────────
const MODEL_TYPES = [
  { key: 'xgboost',            label: 'XGBoost',         color: '#ffb000' },
  { key: 'lightgbm',           label: 'LightGBM',        color: '#10b981' },
  { key: 'random_forest',      label: 'Random Forest',   color: '#8b5cf6' },
  { key: 'extra_trees',        label: 'Extra Trees',     color: '#06b6d4' },
  { key: 'gradient_boosting',  label: 'Grad. Boosting',  color: '#f97316' },
  { key: 'logistic_regression',label: 'Logistic Reg.',   color: '#ec4899' },
]

// ── SVG Beeswarm component ────────────────────────────────────────────────────
function BeeswarmPlot({ data, isDark }: { data: any; isDark: boolean }) {
  const features: string[] = data.features || []
  const points: Array<{ feature: string; feature_idx: number; shap_value: number; feature_norm: number; jitter: number }> = data.data || []
  const xMax = Math.max(data.global_max_shap * 1.15, 0.005)

  const leftPad = 148, rightPad = 20, topPad = 8, rowH = 26
  const vbW = 820
  const vbH = features.length * rowH + topPad + 36
  const chartW = vbW - leftPad - rightPad
  const zeroX = leftPad + chartW / 2
  const toX = (v: number) => leftPad + ((v + xMax) / (2 * xMax)) * chartW

  const mu = isDark ? T.muted : '#8a94a6'
  const gridCol = isDark ? '#1a2130' : '#f1f5f9'

  return (
    <svg viewBox={`0 0 ${vbW} ${vbH}`} width="100%" style={{ fontFamily: 'monospace', display: 'block' }}>
      {/* Horizontal grid lines */}
      {features.map((_, i) => (
        <line key={i}
          x1={leftPad} x2={vbW - rightPad}
          y1={topPad + i * rowH + rowH / 2}
          y2={topPad + i * rowH + rowH / 2}
          stroke={gridCol} strokeWidth="1"
        />
      ))}

      {/* Zero reference line */}
      <line x1={zeroX} x2={zeroX} y1={topPad - 4} y2={vbH - 28} stroke="#ffb000" strokeWidth="1.5" strokeDasharray="4,3" />

      {/* Dots */}
      {points.map((p, i) => (
        <circle
          key={i}
          cx={toX(p.shap_value)}
          cy={topPad + p.feature_idx * rowH + rowH / 2 + p.jitter * 8}
          r={3.2}
          fill={shapDotColor(p.feature_norm)}
          opacity={0.75}
        >
          <title>{p.feature}: SHAP={fmtSigned(p.shap_value, 4)}, val={p.feature_norm > 0.5 ? 'High' : 'Low'}</title>
        </circle>
      ))}

      {/* Feature name labels */}
      {features.map((f, i) => (
        <text key={i}
          x={leftPad - 6} y={topPad + i * rowH + rowH / 2 + 4}
          textAnchor="end" fontSize={10} fill={featColor(f)}
          fontFamily="monospace"
        >
          {f.length > 18 ? f.substring(0, 18) + '…' : f}
        </text>
      ))}

      {/* X-axis ticks */}
      {[-xMax, -xMax / 2, 0, xMax / 2, xMax].map((v, i) => (
        <g key={i}>
          <line x1={toX(v)} x2={toX(v)} y1={vbH - 28} y2={vbH - 22} stroke={mu} strokeWidth="1" />
          <text x={toX(v)} y={vbH - 12} textAnchor="middle" fontSize={9} fill={mu}>
            {v === 0 ? '0' : `${fmtSigned(v, 3)}`}
          </text>
        </g>
      ))}
      <text x={vbW / 2} y={vbH - 2} textAnchor="middle" fontSize={9} fill={mu}>
        SHAP value — impact on P(UP) ↑
      </text>

      {/* Color legend */}
      <defs>
        <linearGradient id="shapGrad" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%"   stopColor="rgb(0,130,220)" />
          <stop offset="50%"  stopColor="rgb(170,180,190)" />
          <stop offset="100%" stopColor="rgb(255,50,35)" />
        </linearGradient>
      </defs>
      <rect x={vbW - rightPad - 80} y={topPad} width={80} height={8} rx={3} fill="url(#shapGrad)" opacity={0.9} />
      <text x={vbW - rightPad - 80} y={topPad + 18} fontSize={8} fill={mu}>Low</text>
      <text x={vbW - rightPad - 6} y={topPad + 18} textAnchor="end" fontSize={8} fill={mu}>High</text>
      <text x={vbW - rightPad - 40} y={topPad + 18} textAnchor="middle" fontSize={8} fill={mu}>Feature value</text>
    </svg>
  )
}

// ── Config Modal (exported so PipelineStudio sidebar can open it directly) ─────
export interface ConfigModalProps {
  isDark: boolean
  initialModelType: string
  onLaunch: (payload: Record<string, any>) => void
  onClose: () => void
}

export function ConfigModal({ isDark, initialModelType, onLaunch, onClose }: ConfigModalProps) {
  const today = new Date().toISOString().slice(0, 10)
  const fiveYearsAgo = new Date(new Date().setFullYear(new Date().getFullYear() - 5)).toISOString().slice(0, 10)

  const [modelType, setModelType]       = useState(initialModelType)
  const [trainingMode, setTrainingMode] = useState<'new' | 'warmstart'>('new')
  const [trainStart, setTrainStart]     = useState(fiveYearsAgo)
  const [trainEnd, setTrainEnd]         = useState(today)
  const [selFeats, setSelFeats]         = useState<Set<string>>(new Set(ALL_FEATURES))
  const [showFeatSel, setShowFeatSel]   = useState(false)
  const [n_estimators, setN]            = useState(300)
  const [max_depth, setD]               = useState(5)
  const [learning_rate, setLR]          = useState(0.05)
  const [subsample, setSub]             = useState(0.8)
  const [colsample_bytree, setCol]      = useState(0.8)
  const [min_child_weight, setMCW]      = useState(5)
  const [gamma, setGamma]               = useState(0.1)
  const [reg_alpha, setAlpha]           = useState(0.1)
  const [reg_lambda, setLambda]         = useState(1.0)
  const [scale_pos_weight, setSPW]      = useState(1)
  const [rows_per_ticker, setRPT]       = useState(200)
  const [run_walk_forward, setWFO]      = useState(false)

  const tx = isDark ? 'text-slate-50'  : 'text-slate-950'
  const mu = isDark ? 'text-slate-500' : 'text-slate-500'

  const toggleFeat = (f: string) => setSelFeats(prev => {
    const next = new Set(prev)
    if (next.has(f)) next.delete(f); else next.add(f)
    return next
  })
  const toggleCat = (cat: string) => {
    const catFeats = FEATURE_CATEGORIES[cat]
    const allOn = catFeats.every(f => selFeats.has(f))
    setSelFeats(prev => {
      const next = new Set(prev)
      catFeats.forEach(f => allOn ? next.delete(f) : next.add(f))
      return next
    })
  }
  const isCatActive = (cat: string) => FEATURE_CATEGORIES[cat].some(f => selFeats.has(f))
  const isCatFull   = (cat: string) => FEATURE_CATEGORIES[cat].every(f => selFeats.has(f))
  const isXGB = modelType === 'xgboost' || modelType === 'lightgbm' || modelType === 'gradient_boosting'

  const Slider = ({ label, val, setVal, min, max, step = 1, fmt }: {
    label: string; val: number; setVal: (v: number) => void; min: number; max: number; step?: number; fmt?: (v: number) => string
  }) => (
    <div>
      <div className="flex justify-between mb-1">
        <label className={`text-[11px] font-medium ${mu}`}>{label}</label>
        <span className={`text-[11px] font-mono font-bold ${tx}`}>{fmt ? fmt(val) : val}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={val}
        onChange={e => setVal(parseFloat(e.target.value))}
        className="w-full h-1.5 appearance-none rounded-full bg-slate-700 accent-amber-500 cursor-pointer"
      />
      <div className="flex justify-between">
        <span className={`text-[9px] ${mu}`}>{min}</span>
        <span className={`text-[9px] ${mu}`}>{max}</span>
      </div>
    </div>
  )

  const mt = MODEL_TYPES.find(m => m.key === modelType)

  const launch = () => {
    const payload: Record<string, any> = {
      model_type: modelType,
      rows_per_ticker,
      run_walk_forward,
      warm_start: trainingMode === 'warmstart',
      train_start: trainStart,
      train_end: trainEnd,
      selected_features: selFeats.size < ALL_FEATURES.length ? [...selFeats] : undefined,
    }
    if (isXGB) {
      Object.assign(payload, { n_estimators, max_depth, learning_rate, subsample, colsample_bytree, min_child_weight, gamma, reg_alpha, reg_lambda, scale_pos_weight })
    }
    onLaunch(payload)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className={`${isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-slate-200'} border rounded-2xl shadow-2xl w-full max-w-2xl max-h-[92vh] overflow-y-auto`}>
        {/* Header */}
        <div className={`flex justify-between items-center px-8 py-5 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'}`}>
          <div>
            <h2 className={`${tx} text-lg font-bold tracking-tight`}>Configure Training Run</h2>
            <p className={`${mu} text-xs mt-0.5`}>
              {mt && <span className="font-bold" style={{ color: mt.color }}>{mt.label}</span>}
              {' '}— select features and hyperparameters
            </p>
          </div>
          <button onClick={onClose} className={`${mu} text-xl hover:text-white transition-colors`}>✕</button>
        </div>

        <div className="px-8 py-6 space-y-7">

          {/* Date Range — Training window */}
          <div>
            <p className="text-rose-400 text-[10px] font-bold uppercase tracking-widest mb-3">Training Date Range</p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={`text-[11px] font-medium ${mu} block mb-1`}>Start Date</label>
                <input
                  type="date"
                  value={trainStart}
                  max={trainEnd}
                  onChange={e => setTrainStart(e.target.value)}
                  className={`w-full px-3 py-2 text-xs rounded-lg border font-mono ${isDark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-white border-slate-300 text-slate-800'}`}
                />
              </div>
              <div>
                <label className={`text-[11px] font-medium ${mu} block mb-1`}>End Date</label>
                <input
                  type="date"
                  value={trainEnd}
                  min={trainStart}
                  max={new Date().toISOString().slice(0, 10)}
                  onChange={e => setTrainEnd(e.target.value)}
                  className={`w-full px-3 py-2 text-xs rounded-lg border font-mono ${isDark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-white border-slate-300 text-slate-800'}`}
                />
              </div>
            </div>
            <p className={`${mu} text-[10px] mt-1.5`}>
              Window: {Math.round((new Date(trainEnd).getTime() - new Date(trainStart).getTime()) / (1000 * 60 * 60 * 24 * 30))} months · Never use future data
            </p>
          </div>

          {/* Training Mode — Bloomberg-style segmented control */}
          <div>
            <p className="text-cyan-400 text-[10px] font-bold uppercase tracking-widest mb-3">Training Mode</p>
            <div className={`flex rounded-lg border overflow-hidden ${isDark ? 'border-slate-700' : 'border-slate-200'}`}>
              {([
                { key: 'new',       label: 'Train New Model',      desc: 'Full fit from scratch' },
                { key: 'warmstart', label: 'Update Existing Model', desc: 'Incremental warm start' },
              ] as const).map(opt => (
                <button
                  key={opt.key}
                  onClick={() => setTrainingMode(opt.key)}
                  className={`flex-1 px-4 py-3 text-left transition-all ${
                    trainingMode === opt.key
                      ? 'bg-cyan-500/15 border-r border-cyan-500/30'
                      : isDark
                        ? 'bg-slate-800/50 hover:bg-slate-700/50 border-r border-slate-700'
                        : 'bg-slate-50 hover:bg-slate-100 border-r border-slate-200'
                  } last:border-r-0`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`text-[11px] font-bold ${trainingMode === opt.key ? 'text-cyan-400' : mu}`}>
                      {trainingMode === opt.key ? '◉' : '○'}
                    </span>
                    <div>
                      <p className={`text-[11px] font-bold ${trainingMode === opt.key ? 'text-cyan-300' : tx}`}>{opt.label}</p>
                      <p className={`text-[9px] ${mu}`}>{opt.desc}</p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Model Type */}
          <div>
            <p className="text-amber-400 text-[10px] font-bold uppercase tracking-widest mb-3">Model Type</p>
            <div className="grid grid-cols-3 gap-2">
              {MODEL_TYPES.map(m => (
                <button
                  key={m.key}
                  onClick={() => setModelType(m.key)}
                  className={`px-3 py-2.5 text-[11px] font-bold rounded-lg border transition text-left ${
                    modelType === m.key
                      ? 'border-transparent'
                      : isDark ? 'border-slate-700 text-slate-400 hover:border-slate-600' : 'border-slate-200 text-slate-500 hover:border-slate-300'
                  }`}
                  style={modelType === m.key ? { backgroundColor: m.color + '22', borderColor: m.color, color: m.color } : {}}
                >
                  {modelType === m.key ? '● ' : '○ '}{m.label}
                </button>
              ))}
            </div>
          </div>

          {/* Hyperparameters (boosting models only) */}
          {isXGB && (
            <>
              <div className={`border-t ${isDark ? 'border-slate-800' : 'border-slate-200'} pt-6`}>
                <p className="text-violet-400 text-[10px] font-bold uppercase tracking-widest mb-4">Model Architecture</p>
                <div className="grid grid-cols-2 gap-6">
                  <Slider label="Trees / Iterations (n_estimators)" val={n_estimators} setVal={setN} min={50} max={1000} step={50} />
                  <Slider label="Max Tree Depth" val={max_depth} setVal={setD} min={2} max={10} />
                  <Slider label="Learning Rate (eta)" val={learning_rate} setVal={setLR} min={0.005} max={0.3} step={0.005} fmt={v => v.toFixed(3)} />
                  <Slider label="Class Weight (pos/neg ratio)" val={scale_pos_weight} setVal={setSPW} min={0.5} max={5} step={0.1} fmt={v => v.toFixed(1)} />
                </div>
              </div>
              <div className={`border-t ${isDark ? 'border-slate-800' : 'border-slate-200'} pt-6`}>
                <p className="text-teal-400 text-[10px] font-bold uppercase tracking-widest mb-4">Regularization</p>
                <div className="grid grid-cols-2 gap-6">
                  <Slider label="Subsample" val={subsample} setVal={setSub} min={0.4} max={1.0} step={0.05} fmt={v => v.toFixed(2)} />
                  <Slider label="Col Sample per Tree" val={colsample_bytree} setVal={setCol} min={0.4} max={1.0} step={0.05} fmt={v => v.toFixed(2)} />
                  <Slider label="Min Child Weight" val={min_child_weight} setVal={setMCW} min={1} max={30} />
                  <Slider label="Gamma (min split loss)" val={gamma} setVal={setGamma} min={0} max={5} step={0.1} fmt={v => v.toFixed(1)} />
                  <Slider label="L1 Reg (alpha)" val={reg_alpha} setVal={setAlpha} min={0} max={2} step={0.05} fmt={v => v.toFixed(2)} />
                  <Slider label="L2 Reg (lambda)" val={reg_lambda} setVal={setLambda} min={0} max={5} step={0.1} fmt={v => v.toFixed(1)} />
                </div>
              </div>
            </>
          )}

          {/* Training Strategy */}
          <div className={`border-t ${isDark ? 'border-slate-800' : 'border-slate-200'} pt-6`}>
            <p className="text-slate-400 text-[10px] font-bold uppercase tracking-widest mb-4">Training Strategy</p>
            <div className="grid grid-cols-2 gap-6">
              <Slider label="Rows per Ticker" val={rows_per_ticker} setVal={setRPT} min={50} max={500} step={25} />
              <div className="flex items-center gap-4 pt-4">
                <label className={`text-[11px] font-medium ${mu}`}>Walk-Forward</label>
                <button
                  onClick={() => setWFO(v => !v)}
                  className={`relative w-10 h-5 rounded-full transition-colors ${run_walk_forward ? 'bg-amber-500' : 'bg-slate-700'}`}
                >
                  <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${run_walk_forward ? 'translate-x-5' : 'translate-x-0.5'}`} />
                </button>
                <span className={`text-[10px] font-mono ${run_walk_forward ? 'text-amber-400' : mu}`}>
                  {run_walk_forward ? 'ON (slower)' : 'OFF'}
                </span>
              </div>
            </div>
          </div>

          {/* Feature Selection */}
          <div className={`border-t ${isDark ? 'border-slate-800' : 'border-slate-200'} pt-6`}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <p className="text-rose-400 text-[10px] font-bold uppercase tracking-widest">Feature Selection</p>
                <p className={`${mu} text-[10px] mt-0.5`}>{selFeats.size} / {ALL_FEATURES.length} features selected</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setSelFeats(new Set(ALL_FEATURES))}
                  className={`px-3 py-1 text-[10px] font-bold rounded-lg ${isDark ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'} transition`}
                >All</button>
                <button
                  onClick={() => setSelFeats(new Set())}
                  className={`px-3 py-1 text-[10px] font-bold rounded-lg ${isDark ? 'bg-slate-800 text-slate-400 hover:bg-slate-700' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'} transition`}
                >None</button>
                <button
                  onClick={() => setShowFeatSel(v => !v)}
                  className={`px-3 py-1 text-[10px] font-bold rounded-lg border transition ${
                    showFeatSel
                      ? 'bg-rose-500/20 border-rose-500/40 text-rose-400'
                      : isDark ? 'border-slate-700 text-slate-400 hover:border-slate-600' : 'border-slate-200 text-slate-500'
                  }`}
                >{showFeatSel ? 'Hide' : 'Expand'}</button>
              </div>
            </div>

            {/* Category toggles */}
            <div className="flex gap-2 flex-wrap mb-3">
              {Object.entries(FEATURE_CATEGORIES).map(([cat, feats]) => (
                <button
                  key={cat}
                  onClick={() => toggleCat(cat)}
                  className="px-3 py-1.5 text-[10px] font-bold rounded-lg border transition"
                  style={{
                    borderColor: isCatActive(cat) ? CAT_COLORS[cat] + '80' : isDark ? '#2a3448' : '#e2e8f0',
                    backgroundColor: isCatActive(cat) ? CAT_COLORS[cat] + '20' : 'transparent',
                    color: isCatActive(cat) ? CAT_COLORS[cat] : isDark ? T.muted : '#8a94a6',
                  }}
                >
                  {isCatFull(cat) ? '●' : isCatActive(cat) ? '◐' : '○'} {cat} ({feats.filter(f => selFeats.has(f)).length}/{feats.length})
                </button>
              ))}
            </div>

            {/* Individual feature chips */}
            {showFeatSel && (
              <div className={`${isDark ? 'bg-slate-950' : 'bg-slate-50'} rounded-xl p-4 max-h-52 overflow-y-auto`}>
                {Object.entries(FEATURE_CATEGORIES).map(([cat, feats]) => (
                  <div key={cat} className="mb-3 last:mb-0">
                    <p className="text-[9px] font-bold uppercase tracking-widest mb-2" style={{ color: CAT_COLORS[cat] }}>{cat}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {feats.map(f => (
                        <button
                          key={f}
                          onClick={() => toggleFeat(f)}
                          className="px-2 py-0.5 text-[9px] font-mono rounded-md border transition"
                          style={{
                            borderColor: selFeats.has(f) ? CAT_COLORS[cat] + '80' : isDark ? '#2a3448' : '#e2e8f0',
                            backgroundColor: selFeats.has(f) ? CAT_COLORS[cat] + '25' : 'transparent',
                            color: selFeats.has(f) ? CAT_COLORS[cat] : isDark ? T.muted : '#8a94a6',
                          }}
                        >
                          {f}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Quick Presets (boosting models only) */}
          {isXGB && (
            <div className={`border-t ${isDark ? 'border-slate-800' : 'border-slate-200'} pt-5`}>
              <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-3`}>Quick Presets</p>
              <div className="flex gap-3">
                {[
                  { label: 'Conservative', p: { n_estimators: 200, max_depth: 3, learning_rate: 0.03, subsample: 0.7, gamma: 0.5, reg_lambda: 2.0 } },
                  { label: 'Balanced',     p: { n_estimators: 300, max_depth: 5, learning_rate: 0.05, subsample: 0.8, gamma: 0.1, reg_lambda: 1.0 } },
                  { label: 'Aggressive',   p: { n_estimators: 500, max_depth: 7, learning_rate: 0.08, subsample: 0.9, gamma: 0,   reg_lambda: 0.5 } },
                ].map(({ label, p }) => (
                  <button
                    key={label}
                    onClick={() => { setN(p.n_estimators); setD(p.max_depth); setLR(p.learning_rate); setSub(p.subsample); setGamma(p.gamma); setLambda(p.reg_lambda) }}
                    className={`px-4 py-2 text-[11px] font-bold rounded-lg border transition ${
                      isDark ? 'border-slate-700 text-slate-300 hover:border-amber-500/50 hover:text-amber-400' : 'border-slate-300 text-slate-600 hover:border-amber-500 hover:text-amber-600'
                    }`}
                  >{label}</button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className={`flex justify-end gap-3 px-8 py-5 border-t ${isDark ? 'border-slate-800' : 'border-slate-200'}`}>
          <button
            onClick={onClose}
            className={`px-6 py-2.5 text-sm font-semibold rounded-xl ${isDark ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'} transition`}
          >Cancel</button>
          <button
            onClick={launch}
            className="px-6 py-2.5 text-sm font-bold bg-amber-500 hover:bg-amber-400 text-black rounded-xl transition active:scale-95"
          >{trainingMode === 'warmstart' ? '↺  Update Model' : '▶  Launch Training'}</button>
        </div>
      </div>
    </div>
  )
}

export function ModelLab({ isDark, featureImportance, modelMetrics, onMetricsRefresh }: Props) {
  const [activeTab, setActiveTab]           = useState<ModelLabTab>('overview')
  const [showConfigModal, setShowConfigModal] = useState(false)
  const [defaultModelType, setDefaultModelType] = useState('xgboost')

  // Analysis state
  const [confMatrix, setConfMatrix]         = useState<any>(null)
  const [rocCurve, setRocCurve]             = useState<any>(null)
  const [scoreDist, setScoreDist]           = useState<any>(null)
  const [calibration, setCalibration]       = useState<any>(null)
  const [modelParams, setModelParams]       = useState<any>(null)
  const [shapGlobal, setShapGlobal]         = useState<any>(null)
  const [shapLoading, setShapLoading]       = useState(false)
  const [beeswarmData, setBeeswarmData]     = useState<any>(null)
  const [beeswarmLoading, setBeeswarmLoading] = useState(false)
  const [waterfallData, setWaterfallData]   = useState<any>(null)
  const [waterfallLoading, setWaterfallLoading] = useState(false)
  const [waterfallIdx, setWaterfallIdx]     = useState(0)
  const [featureStats, setFeatureStats]     = useState<any[]>([])
  const [statsSort, setStatsSort]           = useState<{ col: string; asc: boolean }>({ col: 'feature', asc: true })
  const [correlations, setCorrelations]     = useState<any>(null)
  const [corrLoading, setCorrLoading]       = useState(false)
  const [selectedFeat, setSelectedFeat]     = useState('')
  const [featDist, setFeatDist]             = useState<any>(null)
  const [pdpData, setPdpData]               = useState<any>(null)
  const [pdpFeature, setPdpFeature]         = useState('')
  const [pdpLoading, setPdpLoading]         = useState(false)
  const [importanceMode, setImportanceMode] = useState<'mdi' | 'shap'>('mdi')
  const [localFI, setLocalFI]               = useState(featureImportance)
  const [trainingJob, setTrainingJob]       = useState<any>(null)
  const [terminalJobId, setTerminalJobId]   = useState<string | null>(null)
  // Catalog
  const [modelCatalog, setModelCatalog]     = useState<Record<string, any>>({})
  const [modelRegistry, setModelRegistry]   = useState<any[]>([])
  const [catalogLoading, setCatalogLoading] = useState(false)

  const bg   = isDark ? 'bg-slate-950' : 'bg-white'
  const card = isDark ? 'bg-slate-900/80 border-slate-800' : 'bg-slate-50 border-slate-200'
  const inset = isDark ? 'bg-slate-950' : 'bg-slate-100'
  const tx   = isDark ? 'text-slate-50' : 'text-slate-950'
  const mu   = isDark ? 'text-slate-500' : 'text-slate-500'
  const grid = isDark ? '#2a3448' : '#e2e8f0'
  const axis = isDark ? T.muted : '#8a94a6'
  const ttStyle = {
    backgroundColor: isDark ? '#1a2130' : '#f2f5fa',
    border: `1px solid ${isDark ? '#475569' : '#e2e8f0'}`,
    borderRadius: '6px', fontSize: 11,
  }

  // Load overview data on mount
  useEffect(() => {
    const load = async () => {
      try { setConfMatrix((await getConfusionMatrix()).data) } catch {}
      try { setScoreDist((await getScoreDistribution()).data) } catch {}
      try { setModelParams((await getModelParams()).data) } catch {}
    }
    load()
  }, [])

  useEffect(() => { setLocalFI(featureImportance) }, [featureImportance])

  useEffect(() => {
    if (activeTab === 'diagnostics') {
      if (!rocCurve) getRocCurve().then(r => setRocCurve(r.data)).catch(() => {})
      if (!calibration) getCalibration().then(r => setCalibration(r.data)).catch(() => {})
    }
    if (activeTab === 'features' && featureStats.length === 0) {
      getFeatureStats().then(r => setFeatureStats(r.data?.features || [])).catch(() => {})
    }
    if (activeTab === 'correlations' && !correlations) {
      setCorrLoading(true)
      getFeatureCorrelations()
        .then(r => { setCorrelations(r.data); setCorrLoading(false) })
        .catch(() => setCorrLoading(false))
    }
    if (activeTab === 'catalog') {
      setCatalogLoading(true)
      Promise.all([
        getModelCatalog().then(r => setModelCatalog(r.data || {})).catch(() => {}),
        getModelRegistry().then(r => setModelRegistry(r.data || [])).catch(() => {}),
      ]).finally(() => setCatalogLoading(false))
    }
  }, [activeTab])

  useEffect(() => {
    if (importanceMode === 'shap' && !shapGlobal && activeTab === 'explainability') {
      setShapLoading(true)
      getShapGlobal().then(r => { setShapGlobal(r.data); setShapLoading(false) }).catch(() => setShapLoading(false))
    }
  }, [importanceMode, activeTab])

  useEffect(() => {
    if (!trainingJob || trainingJob.status === 'done' || trainingJob.status === 'error') return
    const id = setInterval(async () => {
      try {
        const res = await getPipelineJobStatus(trainingJob.job_id)
        setTrainingJob(res.data)
        if (res.data.status === 'done') {
          onMetricsRefresh()
          try { setConfMatrix((await getConfusionMatrix()).data) } catch {}
          try { setScoreDist((await getScoreDistribution()).data) } catch {}
          try { setModelParams((await getModelParams()).data) } catch {}
          try { const fi = await getFeatureImportance(); setLocalFI(fi.data || []) } catch {}
          setShapGlobal(null); setBeeswarmData(null); setWaterfallData(null)
          // Refresh registry
          getModelRegistry().then(r => setModelRegistry(r.data || [])).catch(() => {})
        }
      } catch {}
    }, 3000)
    return () => clearInterval(id)
  }, [trainingJob?.job_id, trainingJob?.status])

  const handleLaunchTraining = async (payload: Record<string, any>) => {
    try {
      const res = await triggerTrainingConfig(payload)
      setTrainingJob(res.data)
      if (res.data?.job_id) setTerminalJobId(res.data.job_id)
      setShowConfigModal(false)
    } catch (e) { console.error(e) }
  }

  const handleFeatDistLoad = async (feat: string) => {
    if (!feat) return
    setSelectedFeat(feat)
    try { const res = await getFeatureDistribution(feat); setFeatDist(res.data) } catch {}
  }

  const handlePDP = async (feat: string) => {
    if (!feat || feat === pdpFeature) return
    setPdpFeature(feat); setPdpLoading(true)
    try { const res = await getPDP(feat); setPdpData(res.data) } catch {}
    setPdpLoading(false)
  }

  const handleLoadBeeswarm = async () => {
    setBeeswarmLoading(true)
    try { const res = await getShapBeeswarm(200, 15); setBeeswarmData(res.data) } catch {}
    setBeeswarmLoading(false)
  }

  const handleLoadWaterfall = async (idx: number) => {
    setWaterfallLoading(true)
    try { const res = await getShapWaterfall(idx); setWaterfallData(res.data) } catch {}
    setWaterfallLoading(false)
  }

  const sortedStats = [...featureStats].sort((a, b) => {
    const av = a[statsSort.col], bv = b[statsSort.col]
    if (typeof av === 'string') return statsSort.asc ? av.localeCompare(bv) : bv.localeCompare(av)
    return statsSort.asc ? av - bv : bv - av
  })

  const SortTh = ({ col, label }: { col: string; label: string }) => (
    <th
      className={`px-3 py-2 text-left text-[10px] font-bold uppercase tracking-widest cursor-pointer select-none whitespace-nowrap ${statsSort.col === col ? 'text-amber-400' : mu}`}
      onClick={() => setStatsSort(s => s.col === col ? { col, asc: !s.asc } : { col, asc: true })}
    >
      {label} {statsSort.col === col ? (statsSort.asc ? '↑' : '↓') : ''}
    </th>
  )

  const ModelNotTrained = ({ label = 'model' }: { label?: string }) => (
    <div className={`py-16 text-center ${mu}`}>
      <p className="text-3xl mb-4 font-mono opacity-40">◌</p>
      <p className="text-sm font-semibold">Train the {label} first</p>
      <p className="text-xs mt-2 opacity-70">Click "Configure & Train" above, then come back here</p>
    </div>
  )

  const isTraining = trainingJob?.status === 'running'

  return (
    <div className="space-y-0">
      {showConfigModal && (
        <ConfigModal
          key={defaultModelType}
          isDark={isDark}
          initialModelType={defaultModelType}
          onLaunch={handleLaunchTraining}
          onClose={() => setShowConfigModal(false)}
        />
      )}

      {/* Header: sub-tab bar + Configure button */}
      <div className="flex items-center justify-between mb-6">
        <div className={`flex gap-0 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'} flex-1 overflow-x-auto`}>
          {([
            { key: 'overview',       label: 'Overview' },
            { key: 'explainability', label: 'Explainability' },
            { key: 'diagnostics',    label: 'Diagnostics' },
            { key: 'features',       label: 'Feature Analysis' },
            { key: 'correlations',   label: 'Correlations' },
            { key: 'catalog',        label: 'Model Catalog' },
          ] as const).map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`px-4 py-2.5 text-[11px] font-bold uppercase tracking-wider transition-colors border-b-2 whitespace-nowrap ${
                activeTab === key
                  ? 'border-violet-500 text-violet-400'
                  : `border-transparent ${mu} hover:text-slate-300`
              }`}
            >{label}</button>
          ))}
        </div>
        <div className="flex items-center gap-3 pl-6 pb-0.5 flex-shrink-0">
          {trainingJob && (
            <div className={`flex items-center gap-2 text-[11px] font-mono ${isTraining ? 'text-violet-400' : trainingJob.status === 'done' ? 'text-emerald-400' : 'text-red-400'}`}>
              {isTraining && <span className="w-2 h-2 rounded-full bg-violet-400 animate-pulse inline-block" />}
              {isTraining ? `Training… ${trainingJob.progress}%` : trainingJob.status === 'done' ? '✓ Trained' : '✗ Failed'}
            </div>
          )}
          <button
            onClick={() => { setDefaultModelType('xgboost'); setShowConfigModal(true) }}
            disabled={isTraining}
            className={`px-4 py-2 text-[11px] font-bold rounded-lg transition active:scale-95 whitespace-nowrap ${
              isTraining ? 'bg-slate-700 text-slate-400 cursor-not-allowed' : 'bg-violet-600 hover:bg-violet-500 text-white'
            }`}
          >⚙  Configure & Train</button>
        </div>
      </div>

      {/* ── OVERVIEW ──────────────────────────────────────────────────────── */}
      {activeTab === 'overview' && (
        <div className="space-y-6">
          <div className="grid grid-cols-4 gap-4">
            {[
              { label: 'Accuracy', value: modelMetrics?.accuracy, color: 'text-emerald-400', note: modelMetrics?.accuracy ? (modelMetrics.accuracy >= 0.55 ? '✓ Target met' : '✗ Below 55%') : '' },
              { label: 'F1 Score', value: modelMetrics?.f1_score, color: 'text-amber-400', note: '' },
              { label: 'AUC-ROC',  value: modelMetrics?.auc_roc,  color: 'text-violet-400', note: modelMetrics?.auc_roc ? (modelMetrics.auc_roc >= 0.6 ? '✓ Good discrimination' : '⚠ Near random') : '' },
              { label: 'Log Loss', value: modelMetrics?.log_loss,  color: 'text-teal-400',   note: '' },
            ].map((m, i) => (
              <div key={i} className={`${card} border rounded-xl p-5`}>
                <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-2`}>{m.label}</p>
                <p className={`text-3xl font-bold font-mono ${m.value && m.value > 0 ? m.color : mu}`}>
                  {m.value && m.value > 0 ? m.value.toFixed(3) : '—'}
                </p>
                {m.note && <p className={`text-[10px] mt-1.5 ${m.note.startsWith('✓') ? 'text-emerald-400' : 'text-amber-400'}`}>{m.note}</p>}
              </div>
            ))}
          </div>

          {confMatrix && (
            <div className="grid grid-cols-4 gap-4">
              {[
                { label: 'Precision',    value: confMatrix.precision,   color: 'text-blue-400',   desc: 'Of UP calls, % correct' },
                { label: 'Recall',       value: confMatrix.recall,      color: 'text-indigo-400', desc: 'Of actual UPs, % caught' },
                { label: 'Specificity',  value: confMatrix.specificity, color: 'text-pink-400',   desc: 'Of actual DOWNs, % predicted DOWN' },
                { label: 'Val Samples',  value: confMatrix.total,       color: tx,                desc: 'OOS validation set size' },
              ].map((m, i) => (
                <div key={i} className={`${inset} rounded-xl p-4`}>
                  <p className={`${mu} text-[10px] font-bold uppercase tracking-widest mb-1`}>{m.label}</p>
                  <p className={`text-xl font-bold font-mono ${m.color}`}>
                    {typeof m.value === 'number' && m.value > 0 ? (m.label === 'Val Samples' ? m.value.toLocaleString('en-IN') : m.value.toFixed(3)) : '—'}
                  </p>
                  <p className={`text-[9px] ${mu} mt-0.5 leading-tight`}>{m.desc}</p>
                </div>
              ))}
            </div>
          )}

          <div className="grid grid-cols-2 gap-6">
            {/* Confusion Matrix */}
            <div className={`${card} border rounded-xl p-6`}>
              <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-5`}>Confusion Matrix</h3>
              {confMatrix ? (
                <>
                  <div className="relative">
                    <div className="absolute -left-6 top-1/2 -translate-y-1/2 -rotate-90">
                      <span className={`text-[9px] ${mu} font-bold uppercase tracking-widest whitespace-nowrap`}>Actual</span>
                    </div>
                    <div className="space-y-1 ml-2">
                      <div className="grid grid-cols-[80px_1fr_1fr] gap-1 mb-2">
                        <div />
                        <div className={`text-center text-[10px] font-bold ${mu} uppercase tracking-widest`}>Pred DOWN</div>
                        <div className={`text-center text-[10px] font-bold ${mu} uppercase tracking-widest`}>Pred UP</div>
                      </div>
                      {[
                        { label: 'Actual DOWN', cells: [
                          { val: confMatrix.tn, label: 'TN', bg: 'bg-slate-700/60', fg: 'text-slate-200', sub: 'True Negative' },
                          { val: confMatrix.fp, label: 'FP', bg: 'bg-rose-500/20',  fg: 'text-rose-300',  sub: 'False Positive' },
                        ]},
                        { label: 'Actual UP', cells: [
                          { val: confMatrix.fn, label: 'FN', bg: 'bg-amber-500/20',   fg: 'text-amber-300',  sub: 'False Negative' },
                          { val: confMatrix.tp, label: 'TP', bg: 'bg-emerald-500/20', fg: 'text-emerald-300', sub: 'True Positive' },
                        ]},
                      ].map(row => (
                        <div key={row.label} className="grid grid-cols-[80px_1fr_1fr] gap-1">
                          <div className={`flex items-center justify-end pr-3 text-[10px] font-bold ${mu} uppercase tracking-widest`}>{row.label}</div>
                          {row.cells.map(cell => (
                            <div key={cell.label} className={`${cell.bg} rounded-lg p-4 text-center`}>
                              <p className={`text-xs font-bold ${mu} mb-1`}>{cell.label}</p>
                              <p className={`text-2xl font-bold font-mono ${cell.fg}`}>{cell.val?.toLocaleString('en-IN')}</p>
                              <p className={`text-[9px] ${mu} mt-0.5`}>{cell.sub}</p>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className={`mt-4 pt-4 border-t ${isDark ? 'border-slate-800' : 'border-slate-200'} text-center`}>
                    <span className={`text-[10px] ${mu}`}>Total: </span>
                    <span className={`text-[10px] font-mono font-bold ${tx}`}>{confMatrix.total?.toLocaleString('en-IN')}</span>
                    <span className={`text-[10px] ${mu} mx-3`}>|</span>
                    <span className={`text-[10px] ${mu}`}>Prec: </span>
                    <span className="text-[10px] font-mono font-bold text-blue-400">{confMatrix.precision?.toFixed(3)}</span>
                    <span className={`text-[10px] ${mu} mx-3`}>|</span>
                    <span className={`text-[10px] ${mu}`}>Recall: </span>
                    <span className="text-[10px] font-mono font-bold text-indigo-400">{confMatrix.recall?.toFixed(3)}</span>
                  </div>
                </>
              ) : <ModelNotTrained />}
            </div>

            {/* Score Distribution */}
            <div className={`${card} border rounded-xl p-6`}>
              <div className="flex justify-between items-center mb-5">
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Score Distribution</h3>
                <span className={`text-[10px] ${mu}`}>P(UP) on val set</span>
              </div>
              {scoreDist?.histogram?.length > 0 ? (
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={scoreDist.histogram} margin={{ top: 0, right: 8, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="4 2" stroke={grid} vertical={false} />
                    <XAxis dataKey="score" stroke={axis} tick={{ fontSize: 10, fontFamily: 'monospace' }} tickFormatter={(v: number) => v.toFixed(2)} />
                    <YAxis stroke={axis} tick={{ fontSize: 10 }} />
                    <Tooltip contentStyle={ttStyle} formatter={(v: any) => [v, 'Samples']} labelFormatter={(l: any) => `P(UP)=${Number(l).toFixed(2)}`} />
                    <ReferenceLine x={0.5} stroke="#ffb000" strokeDasharray="4 2" label={{ value: 'thresh', position: 'insideTopRight', fontSize: 9, fill: '#ffb000' }} />
                    <Bar dataKey="count" radius={[2, 2, 0, 0]}>
                      {scoreDist.histogram.map((d: any, i: number) => (
                        <Cell key={i} fill={d.score >= 0.5 ? '#ffb000' : '#6f7a8e'} opacity={0.8} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : <ModelNotTrained />}
            </div>
          </div>

          {modelParams && (
            <div className={`${card} border rounded-xl p-6`}>
              <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-4`}>Active Model Parameters</h3>
              <div className="grid grid-cols-5 gap-3">
                {[
                  ['n_estimators','Trees'], ['max_depth','Max Depth'], ['learning_rate','Eta'],
                  ['subsample','Row Sample'], ['colsample_bytree','Col Sample'],
                  ['min_child_weight','Min Child W.'], ['gamma','Gamma'],
                  ['reg_alpha','L1 (α)'], ['reg_lambda','L2 (λ)'], ['scale_pos_weight','Pos Weight'],
                ].map(([key, label]) => {
                  const v = modelParams.classifier?.[key]
                  return (
                    <div key={key} className={`${inset} rounded-lg p-3`}>
                      <p className={`${mu} text-[9px] font-bold uppercase tracking-widest mb-1`}>{label}</p>
                      <p className={`${tx} text-base font-bold font-mono`}>
                        {v !== undefined ? (typeof v === 'number' && v < 1 ? v.toFixed(3) : String(v)) : '—'}
                      </p>
                    </div>
                  )
                })}
              </div>
              <p className={`${mu} text-[10px] mt-3`}>
                Type: <span className="font-mono text-amber-400">{modelParams.model_type || 'xgboost'}</span>
                {' · '}Features: {modelParams.feature_count}
                {' · '}Version: {modelMetrics?.model_version || '—'}
              </p>
            </div>
          )}

          <TrainingTerminal
            jobId={terminalJobId}
            streamUrl={ML_TRAIN_STREAM_URL}
            title="ML TRAINING LOG"
            onDone={(status) => {
              if (status === 'done') {
                getModelMetrics().then(r => onMetricsRefresh?.()).catch(() => {})
              }
            }}
          />
        </div>
      )}

      {/* ── EXPLAINABILITY ────────────────────────────────────────────────── */}
      {activeTab === 'explainability' && (
        <div className="space-y-6">
          {/* Feature Importance */}
          <div className={`${card} border rounded-xl p-6`}>
            <div className="flex justify-between items-center mb-6">
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Feature Importance — Top 20</h3>
                <p className={`${mu} text-[11px] mt-1`}>
                  {importanceMode === 'mdi' ? 'MDI: Mean Decrease in Impurity' : 'SHAP: Mean |SHAP| across 300 validation samples'}
                </p>
              </div>
              <div className="flex gap-2">
                {(['mdi', 'shap'] as const).map(m => (
                  <button key={m} onClick={() => setImportanceMode(m)}
                    className={`px-4 py-1.5 text-[10px] font-bold uppercase tracking-widest rounded-lg transition ${
                      importanceMode === m ? 'bg-amber-500 text-black' : isDark ? 'bg-slate-800 text-slate-400 hover:bg-slate-700' : 'bg-slate-100 text-slate-500 hover:bg-slate-200'
                    }`}
                  >{m.toUpperCase()}</button>
                ))}
              </div>
            </div>

            {importanceMode === 'mdi' && localFI.length > 0 && (
              <ResponsiveContainer width="100%" height={460}>
                <BarChart layout="vertical" data={localFI.slice(0, 20)} margin={{ top: 0, right: 24, left: 160, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="4 2" stroke={grid} vertical={false} />
                  <XAxis type="number" domain={[0, 'auto']} stroke={axis} tick={{ fontSize: 10 }} />
                  <YAxis dataKey="feature" type="category" width={155} stroke={axis} tick={{ fontSize: 11, fontFamily: 'monospace' }} />
                  <Tooltip contentStyle={ttStyle} formatter={(v: any) => [(v as number).toFixed(4), 'MDI Importance']} />
                  <Bar dataKey="importance" radius={[0, 3, 3, 0]}>
                    {localFI.slice(0, 20).map((e, i) => <Cell key={i} fill={featColor(e.feature)} opacity={0.9} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}

            {importanceMode === 'shap' && (
              shapLoading ? (
                <div className={`py-16 text-center ${mu}`}>
                  <div className="w-8 h-8 border-2 border-amber-500/40 border-t-amber-500 rounded-full animate-spin mx-auto mb-4" />
                  <p className="text-sm">Computing SHAP values…</p>
                </div>
              ) : shapGlobal?.shap_values?.length > 0 ? (
                <ResponsiveContainer width="100%" height={460}>
                  <BarChart layout="vertical" data={shapGlobal.shap_values} margin={{ top: 0, right: 24, left: 160, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="4 2" stroke={grid} vertical={false} />
                    <XAxis type="number" domain={[0, 'auto']} stroke={axis} tick={{ fontSize: 10 }} />
                    <YAxis dataKey="feature" type="category" width={155} stroke={axis} tick={{ fontSize: 11, fontFamily: 'monospace' }} />
                    <Tooltip contentStyle={ttStyle} formatter={(v: any) => [(v as number).toFixed(5), 'Mean |SHAP|']} />
                    <Bar dataKey="shap_importance" radius={[0, 3, 3, 0]}>
                      {shapGlobal.shap_values.map((e: any, i: number) => <Cell key={i} fill={featColor(e.feature)} opacity={0.9} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className={`py-16 text-center ${mu}`}>
                  <p className="text-3xl mb-3" style={{ color: 'var(--t-dim)' }}>◇</p>
                  <p className="text-sm">SHAP not yet computed</p>
                  <p className="text-xs mt-1 opacity-70">Switch to SHAP tab to trigger</p>
                </div>
              )
            )}

            <div className={`flex gap-6 mt-5 pt-4 border-t ${isDark ? 'border-slate-800' : 'border-slate-200'}`}>
              {[{ color: '#ffb000', label: 'Momentum' }, { color: '#14b8a6', label: 'Trend' }, { color: '#8b5cf6', label: 'Volume' }, { color: '#6f7a8e', label: 'Volatility' }, { color: '#ec4899', label: 'Calendar' }].map(l => (
                <div key={l.label} className="flex items-center gap-1.5">
                  <div className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: l.color }} />
                  <span className={`text-[10px] ${mu}`}>{l.label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* SHAP Beeswarm */}
          <div className={`${card} border rounded-xl p-6`}>
            <div className="flex justify-between items-center mb-5">
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>SHAP Beeswarm</h3>
                <p className={`${mu} text-[11px] mt-1`}>Per-sample SHAP values — each dot is one validation observation. Color = feature value magnitude.</p>
              </div>
              <button
                onClick={handleLoadBeeswarm}
                disabled={beeswarmLoading}
                className={`px-4 py-2 text-[11px] font-bold rounded-lg transition ${
                  beeswarmLoading ? 'bg-slate-700 text-slate-400 cursor-wait' : 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                }`}
              >
                {beeswarmLoading ? '⟳ Computing…' : beeswarmData ? '↻ Refresh' : '▶ Compute'}
              </button>
            </div>

            {beeswarmLoading && (
              <div className={`py-14 text-center ${mu}`}>
                <div className="w-8 h-8 border-2 border-amber-500/40 border-t-amber-500 rounded-full animate-spin mx-auto mb-4" />
                <p className="text-sm">Computing 200 × 15 SHAP values…</p>
                <p className="text-xs mt-1 opacity-70">~15–40 seconds depending on model</p>
              </div>
            )}

            {!beeswarmLoading && beeswarmData?.data?.length > 0 && (
              <>
                <BeeswarmPlot data={beeswarmData} isDark={isDark} />
                <p className={`${mu} text-[10px] mt-3`}>
                  {beeswarmData.sample_size} validation samples · {beeswarmData.features?.length} features · max |SHAP| = {beeswarmData.global_max_shap?.toFixed(4)}
                </p>
              </>
            )}

            {!beeswarmLoading && !beeswarmData && (
              <div className={`py-14 text-center ${mu}`}>
                <p className="text-3xl mb-3" style={{ color: 'var(--t-dim)' }}>◇</p>
                <p className="text-sm">Click "Compute" to generate per-sample SHAP beeswarm</p>
                <p className="text-xs mt-1 opacity-70">Requires a trained model with validation data</p>
              </div>
            )}
          </div>

          {/* SHAP Waterfall */}
          <div className={`${card} border rounded-xl p-6`}>
            <div className="flex justify-between items-center mb-5">
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>SHAP Waterfall — Single Prediction</h3>
                <p className={`${mu} text-[11px] mt-1`}>How each feature pushes the prediction from base value to final P(UP). Green = increases P(UP), Red = decreases.</p>
              </div>
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => { const i = Math.max(0, waterfallIdx - 1); setWaterfallIdx(i); handleLoadWaterfall(i) }}
                    className={`w-7 h-7 flex items-center justify-center rounded-lg ${isDark ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-100 hover:bg-slate-200'} text-sm transition`}
                  >◀</button>
                  <span className={`text-[11px] font-mono ${mu}`}>Sample {waterfallIdx}</span>
                  <button
                    onClick={() => { const i = waterfallIdx + 1; setWaterfallIdx(i); handleLoadWaterfall(i) }}
                    className={`w-7 h-7 flex items-center justify-center rounded-lg ${isDark ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-100 hover:bg-slate-200'} text-sm transition`}
                  >▶</button>
                </div>
                <button
                  onClick={() => handleLoadWaterfall(waterfallIdx)}
                  disabled={waterfallLoading}
                  className={`px-4 py-2 text-[11px] font-bold rounded-lg transition ${
                    waterfallLoading ? 'bg-slate-700 text-slate-400 cursor-wait' : 'bg-violet-500/20 text-violet-400 hover:bg-violet-500/30'
                  }`}
                >
                  {waterfallLoading ? '⟳ Computing…' : waterfallData ? '↻ Refresh' : '▶ Compute'}
                </button>
              </div>
            </div>

            {waterfallLoading && (
              <div className={`py-12 text-center ${mu}`}>
                <div className="w-6 h-6 border-2 border-violet-500/40 border-t-violet-500 rounded-full animate-spin mx-auto mb-3" />
                <p className="text-sm">Computing SHAP waterfall…</p>
              </div>
            )}

            {!waterfallLoading && waterfallData?.contributions?.length > 0 && (() => {
              const { base_value, final_prediction, contributions } = waterfallData
              const bars = contributions.slice(0, 15)
              return (
                <>
                  <div className={`flex justify-between items-center mb-4 p-3 rounded-lg ${isDark ? 'bg-slate-950' : 'bg-slate-100'}`}>
                    <div className="text-center">
                      <p className={`${mu} text-[9px] font-bold uppercase tracking-widest`}>Base Value</p>
                      <p className={`font-mono font-bold text-lg ${tx}`}>{(base_value * 100).toFixed(1)}%</p>
                      <p className={`${mu} text-[9px]`}>E[P(UP)]</p>
                    </div>
                    <div className="flex-1 mx-4">
                      <div className="h-1 rounded-full bg-slate-700 relative">
                        <div className="absolute top-1/2 -translate-y-1/2 h-3 w-0.5 bg-slate-500" style={{ left: `${base_value * 100}%` }} />
                        <div className="absolute top-1/2 -translate-y-1/2 h-3 w-0.5 bg-amber-400" style={{ left: `${Math.min(final_prediction * 100, 100)}%` }} />
                        <div className="h-full rounded-full bg-gradient-to-r from-slate-500 to-amber-400" style={{ width: `${Math.abs(final_prediction - base_value) * 100}%`, marginLeft: `${Math.min(base_value, final_prediction) * 100}%` }} />
                      </div>
                    </div>
                    <div className="text-center">
                      <p className={`${mu} text-[9px] font-bold uppercase tracking-widest`}>Final P(UP)</p>
                      <p className={`font-mono font-bold text-lg ${final_prediction > 0.5 ? 'text-emerald-400' : 'text-rose-400'}`}>{(final_prediction * 100).toFixed(1)}%</p>
                      <p className={`text-[9px] ${final_prediction > 0.5 ? 'text-emerald-400' : 'text-rose-400'}`}>{final_prediction > 0.5 ? '↑ UP signal' : '↓ DOWN signal'}</p>
                    </div>
                  </div>

                  <ResponsiveContainer width="100%" height={Math.max(300, bars.length * 28 + 60)}>
                    <BarChart layout="vertical" data={bars} margin={{ top: 0, right: 80, left: 155, bottom: 24 }}>
                      <CartesianGrid strokeDasharray="4 2" stroke={grid} horizontal={false} />
                      <XAxis type="number" stroke={axis} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${fmtSigned(v * 100, 1)}%`}
                        label={{ value: 'SHAP contribution to P(UP)', position: 'insideBottom', offset: -12, fontSize: 10, fill: axis }} />
                      <YAxis dataKey="feature" type="category" width={150} stroke={axis} tick={{ fontSize: 10, fontFamily: 'monospace' }} />
                      <ReferenceLine x={0} stroke="#475569" strokeWidth={1.5} />
                      <Tooltip contentStyle={ttStyle}
                        formatter={(v: any, _: any, props: any) => [
                          `${fmtSigned(Number(v) * 100, 2)}%`,
                          `SHAP (val=${props.payload?.feature_value?.toFixed(3)})`
                        ]}
                      />
                      <Bar dataKey="shap" radius={[0, 3, 3, 0]}>
                        {bars.map((b: any, i: number) => <Cell key={i} fill={b.shap >= 0 ? '#10b981' : '#f43f5e'} opacity={0.85} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </>
              )
            })()}

            {!waterfallLoading && !waterfallData && (
              <div className={`py-12 text-center ${mu}`}>
                <p className="text-3xl mb-3" style={{ color: 'var(--t-dim)' }}>◇</p>
                <p className="text-sm">Click "Compute" to explain a single validation prediction</p>
                <p className="text-xs mt-1 opacity-70">Use ◀▶ to step through different samples</p>
              </div>
            )}
          </div>

          {/* PDP */}
          <div className={`${card} border rounded-xl p-6`}>
            <div className="flex justify-between items-center mb-5">
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Partial Dependence Plot</h3>
                <p className={`${mu} text-[11px] mt-1`}>How model's avg P(UP) changes as a single feature varies (all others held at observed values)</p>
              </div>
              <select value={pdpFeature} onChange={e => handlePDP(e.target.value)}
                className={`text-xs font-mono px-3 py-2 rounded-lg border ${isDark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-white border-slate-300 text-slate-700'}`}
              >
                <option value="">Select feature…</option>
                {localFI.slice(0, 20).map(f => <option key={f.feature} value={f.feature}>{f.feature}</option>)}
              </select>
            </div>

            {pdpLoading && (
              <div className={`py-12 text-center ${mu}`}>
                <div className="w-6 h-6 border-2 border-violet-500/40 border-t-violet-500 rounded-full animate-spin mx-auto mb-3" />
                <p className="text-sm">Computing PDP for {pdpFeature}…</p>
              </div>
            )}
            {!pdpLoading && pdpData ? (
              <>
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={pdpData.grid.map((g: number, i: number) => ({ x: g, y: pdpData.avg_prediction[i] }))} margin={{ top: 10, right: 24, left: 0, bottom: 10 }}>
                    <CartesianGrid strokeDasharray="4 2" stroke={grid} vertical={false} />
                    <XAxis dataKey="x" stroke={axis} tick={{ fontSize: 10, fontFamily: 'monospace' }} tickFormatter={(v: number) => v.toFixed(2)} label={{ value: pdpData.feature, position: 'insideBottom', offset: -5, fontSize: 11, fill: axis }} />
                    <YAxis stroke={axis} tick={{ fontSize: 10 }} domain={[0, 1]} tickFormatter={(v: number) => (v * 100).toFixed(0) + '%'} />
                    <Tooltip contentStyle={ttStyle} formatter={(v: any) => [`${(v * 100).toFixed(1)}%`, 'Avg P(UP)']} labelFormatter={(l: any) => `${pdpData.feature}=${Number(l).toFixed(3)}`} />
                    <ReferenceLine y={0.5} stroke="#ffb000" strokeDasharray="3 3" label={{ value: '50%', position: 'right', fontSize: 10, fill: '#ffb000' }} />
                    <Line type="monotone" dataKey="y" stroke="#8b5cf6" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
                <div className={`flex gap-6 text-[10px] font-mono ${mu} mt-2`}>
                  <span>Range: [{pdpData.feature_min?.toFixed(3)}, {pdpData.feature_max?.toFixed(3)}]</span>
                  <span>Median: {pdpData.feature_p50?.toFixed(3)}</span>
                </div>
              </>
            ) : !pdpLoading && (
              <div className={`py-12 text-center ${mu}`}>
                <p className="text-2xl mb-3 font-mono opacity-40">◌</p>
                <p className="text-sm">Select a feature above to compute its PDP</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── DIAGNOSTICS ───────────────────────────────────────────────────── */}
      {activeTab === 'diagnostics' && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-6">
            <div className={`${card} border rounded-xl p-6`}>
              <div className="flex justify-between items-center mb-5">
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>ROC Curve</h3>
                {rocCurve?.auc && <span className="text-[11px] font-mono font-bold text-violet-400">AUC = {rocCurve.auc.toFixed(3)}</span>}
              </div>
              {rocCurve?.points?.length > 0 ? (
                <ResponsiveContainer width="100%" height={300}>
                  <LineChart data={rocCurve.points} margin={{ top: 10, right: 24, left: 0, bottom: 20 }}>
                    <CartesianGrid strokeDasharray="4 2" stroke={grid} />
                    <XAxis dataKey="fpr" stroke={axis} tick={{ fontSize: 10 }} label={{ value: 'False Positive Rate', position: 'insideBottom', offset: -12, fontSize: 10, fill: axis }} domain={[0, 1]} />
                    <YAxis stroke={axis} tick={{ fontSize: 10 }} label={{ value: 'True Positive Rate', angle: -90, position: 'insideLeft', fontSize: 10, fill: axis }} domain={[0, 1]} />
                    <Tooltip contentStyle={ttStyle} formatter={(v: any) => [(v as number).toFixed(3)]} labelFormatter={(l: any) => `FPR=${Number(l).toFixed(3)}`} />
                    <Line type="monotone" data={[{ fpr: 0, tpr: 0 }, { fpr: 1, tpr: 1 }]} dataKey="tpr" stroke="#475569" strokeWidth={1} strokeDasharray="4 4" dot={false} isAnimationActive={false} legendType="none" />
                    <Line type="monotone" dataKey="tpr" stroke="#8b5cf6" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                  </LineChart>
                </ResponsiveContainer>
              ) : <ModelNotTrained />}
              {rocCurve?.auc && (
                <p className={`${mu} text-[10px] mt-3`}>
                  {rocCurve.auc >= 0.7 ? '✓ Good (≥0.70)' : rocCurve.auc >= 0.6 ? '○ Moderate (0.60–0.70)' : '✗ Near-random (<0.60)'}
                </p>
              )}
            </div>

            <div className={`${card} border rounded-xl p-6`}>
              <div className="flex justify-between items-center mb-5">
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Calibration Curve</h3>
                <span className={`text-[10px] ${mu}`}>Reliability diagram</span>
              </div>
              {calibration?.points?.length > 0 ? (
                <>
                  <ResponsiveContainer width="100%" height={300}>
                    <LineChart
                      data={[...calibration.points, { mean_pred: 0, frac_pos: 0, perfect: 0 }, { mean_pred: 1, frac_pos: 1, perfect: 1 }].sort((a: any, b: any) => a.mean_pred - b.mean_pred)}
                      margin={{ top: 10, right: 24, left: 0, bottom: 20 }}
                    >
                      <CartesianGrid strokeDasharray="4 2" stroke={grid} />
                      <XAxis dataKey="mean_pred" stroke={axis} tick={{ fontSize: 10 }} label={{ value: 'Mean Predicted Probability', position: 'insideBottom', offset: -12, fontSize: 10, fill: axis }} domain={[0, 1]} />
                      <YAxis stroke={axis} tick={{ fontSize: 10 }} label={{ value: 'Fraction Positives', angle: -90, position: 'insideLeft', fontSize: 10, fill: axis }} domain={[0, 1]} />
                      <Tooltip contentStyle={ttStyle} formatter={(v: any, name: string) => [(v as number).toFixed(3), name === 'frac_pos' ? 'Actual' : 'Perfect']} />
                      <Line type="monotone" dataKey="perfect" stroke="#475569" strokeWidth={1} strokeDasharray="4 4" dot={false} isAnimationActive={false} legendType="none" />
                      <Line type="monotone" dataKey="frac_pos" stroke="#ffb000" strokeWidth={2.5} dot={{ fill: '#ffb000', r: 4 }} isAnimationActive={false} connectNulls />
                    </LineChart>
                  </ResponsiveContainer>
                  <p className={`${mu} text-[10px] mt-3`}>Dashed = perfect calibration. Deviation = over/under-confidence.</p>
                </>
              ) : <ModelNotTrained />}
            </div>
          </div>

          <div className={`${card} border rounded-xl p-6`}>
            <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-4`}>Diagnostic Interpretation Guide</h3>
            <div className="grid grid-cols-3 gap-6">
              {[
                { title: 'ROC Curve', color: 'text-violet-400', points: ['AUC 0.5 = random | AUC 1.0 = perfect', 'Target: AUC ≥ 0.60 for directional prediction', 'Curve hugging top-left = strong model'] },
                { title: 'Calibration Curve', color: 'text-amber-400', points: ['Perfect = points on diagonal', 'Above diagonal = under-confident', 'Below diagonal = over-confident'] },
                { title: 'Score Distribution', color: 'text-teal-400', points: ['Bimodal = confident predictions', 'Uniform = random classifier', 'Spike at 0.5 = poor discrimination'] },
              ].map(({ title, color, points }) => (
                <div key={title}>
                  <p className={`${color} text-[11px] font-bold mb-3`}>{title}</p>
                  <ul className="space-y-1.5">
                    {points.map((pt, i) => (
                      <li key={i} className={`text-[11px] ${mu} flex gap-2`}><span className="text-slate-600 flex-shrink-0">·</span><span>{pt}</span></li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── FEATURE ANALYSIS ──────────────────────────────────────────────── */}
      {activeTab === 'features' && (
        <div className="space-y-6">
          <div className={`${card} border rounded-xl overflow-hidden`}>
            <div className={`px-6 py-4 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'} flex justify-between items-center`}>
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Univariate Statistics</h3>
                <p className={`${mu} text-[11px] mt-0.5`}>Click column header to sort · Target Corr = Pearson ρ with 5-day label</p>
              </div>
              <span className={`text-[11px] font-mono ${mu}`}>{featureStats.length} features</span>
            </div>
            {featureStats.length > 0 ? (
              <div className="overflow-x-auto max-h-96 overflow-y-auto">
                <table className="w-full text-[11px]">
                  <thead className={`${isDark ? 'bg-slate-900' : 'bg-slate-100'} sticky top-0 z-10`}>
                    <tr>
                      <SortTh col="feature" label="Feature" />
                      <SortTh col="mean" label="Mean" />
                      <SortTh col="std" label="Std" />
                      <SortTh col="p50" label="Median" />
                      <SortTh col="p25" label="P25" />
                      <SortTh col="p75" label="P75" />
                      <SortTh col="skew" label="Skew" />
                      <SortTh col="kurtosis" label="Kurt" />
                      <SortTh col="nan_pct" label="NaN%" />
                      <SortTh col="target_corr" label="Target ρ" />
                    </tr>
                  </thead>
                  <tbody className={`divide-y ${isDark ? 'divide-slate-800/50' : 'divide-slate-100'}`}>
                    {sortedStats.map((f: any) => (
                      <tr key={f.feature}
                        className={`cursor-pointer transition-colors ${selectedFeat === f.feature ? (isDark ? 'bg-amber-500/10' : 'bg-amber-50') : (isDark ? 'hover:bg-slate-800/50' : 'hover:bg-slate-50')}`}
                        onClick={() => handleFeatDistLoad(f.feature)}
                      >
                        <td className="px-3 py-2.5"><span className="font-mono font-semibold" style={{ color: featColor(f.feature) }}>{f.feature}</span></td>
                        {['mean','std','p50','p25','p75'].map(col => (
                          <td key={col} className={`px-3 py-2.5 font-mono text-right ${tx}`}>{f[col].toFixed(3)}</td>
                        ))}
                        <td className={`px-3 py-2.5 font-mono text-right ${Math.abs(f.skew) > 2 ? 'text-amber-400' : tx}`}>{f.skew.toFixed(2)}</td>
                        <td className={`px-3 py-2.5 font-mono text-right ${Math.abs(f.kurtosis) > 5 ? 'text-amber-400' : tx}`}>{f.kurtosis.toFixed(1)}</td>
                        <td className={`px-3 py-2.5 font-mono text-right ${f.nan_pct > 10 ? 'text-rose-400' : mu}`}>{f.nan_pct.toFixed(1)}%</td>
                        <td className={`px-3 py-2.5 font-mono text-right font-bold ${Math.abs(f.target_corr) > 0.05 ? (f.target_corr > 0 ? 'text-emerald-400' : 'text-rose-400') : mu}`}>
                          {fmtSigned(f.target_corr, 4)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className={`py-12 text-center ${mu}`}>
                <p className="text-2xl mb-3 font-mono opacity-40">▦</p>
                <p className="text-sm">Run Phase 3 to compute feature statistics</p>
              </div>
            )}
          </div>

          <div className={`${card} border rounded-xl p-6`}>
            <div className="flex justify-between items-center mb-5">
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Distribution Viewer</h3>
                <p className={`${mu} text-[11px] mt-0.5`}>UP vs DOWN label distribution — click any row above to select</p>
              </div>
              <select value={selectedFeat} onChange={e => handleFeatDistLoad(e.target.value)}
                className={`text-xs font-mono px-3 py-2 rounded-lg border ${isDark ? 'bg-slate-800 border-slate-700 text-slate-200' : 'bg-white border-slate-300 text-slate-700'}`}
              >
                <option value="">Select feature…</option>
                {featureStats.map((f: any) => <option key={f.feature} value={f.feature}>{f.feature}</option>)}
              </select>
            </div>
            {featDist ? (
              <>
                <ResponsiveContainer width="100%" height={260}>
                  <BarChart data={featDist.bins.map((b: number, i: number) => ({ bin: b, up: featDist.up[i], down: featDist.down[i] }))} margin={{ top: 0, right: 24, left: -10, bottom: 20 }}>
                    <CartesianGrid strokeDasharray="4 2" stroke={grid} vertical={false} />
                    <XAxis dataKey="bin" stroke={axis} tick={{ fontSize: 9, fontFamily: 'monospace' }} tickFormatter={(v: number) => v.toFixed(2)} label={{ value: selectedFeat, position: 'insideBottom', offset: -12, fontSize: 10, fill: axis }} />
                    <YAxis stroke={axis} tick={{ fontSize: 10 }} tickFormatter={(v: number) => `${v.toFixed(0)}%`} />
                    <Tooltip contentStyle={ttStyle} formatter={(v: any, name: string) => [`${(v as number).toFixed(1)}%`, name === 'up' ? '↑ UP' : '↓ DOWN']} />
                    <Bar dataKey="up" fill="#10b981" opacity={0.7} radius={[2, 2, 0, 0]} />
                    <Bar dataKey="down" fill="#f43f5e" opacity={0.7} radius={[2, 2, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </>
            ) : (
              <div className={`py-12 text-center ${mu}`}>
                <p className="text-2xl mb-3 font-mono opacity-40">◌</p>
                <p className="text-sm">Select a feature to see its UP/DOWN distribution</p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── CORRELATIONS ──────────────────────────────────────────────────── */}
      {activeTab === 'correlations' && (
        <div className="space-y-6">
          <div className={`${card} border rounded-xl p-6`}>
            <div className="flex justify-between items-center mb-6">
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Feature Correlation Heatmap</h3>
                <p className={`${mu} text-[11px] mt-1`}>Pearson correlation · 8,000-row sample</p>
              </div>
              <div className="flex items-center gap-1 text-[10px]">
                <div className="w-8 h-3 rounded" style={{ background: 'linear-gradient(to right, rgba(244,63,94,0.9), rgba(100,116,139,0.3), rgba(16,185,129,0.9))' }} />
                <span className={mu}>–1 · 0 · +1</span>
              </div>
            </div>

            {corrLoading && (
              <div className={`py-16 text-center ${mu}`}>
                <div className="w-8 h-8 border-2 border-teal-500/40 border-t-teal-500 rounded-full animate-spin mx-auto mb-4" />
                <p className="text-sm">Computing correlation matrix…</p>
              </div>
            )}

            {!corrLoading && correlations ? (() => {
              const feats = correlations.features as string[]
              const matrix = correlations.matrix as number[][]
              const cellSize = Math.min(22, Math.floor(680 / feats.length))
              return (
                <div className="overflow-x-auto">
                  <div className="inline-block">
                    <div className="flex" style={{ paddingLeft: `${Math.max(80, feats.reduce((a, f) => Math.max(a, f.length * 6), 0))}px` }}>
                      {feats.map((f, i) => (
                        <div key={i} style={{ width: cellSize, writingMode: 'vertical-rl', fontSize: 9, whiteSpace: 'nowrap', paddingBottom: 4 }} className={`${mu} font-mono`} title={f}>
                          {f.length > 10 ? f.substring(0, 10) + '…' : f}
                        </div>
                      ))}
                    </div>
                    {matrix.map((row, ri) => (
                      <div key={ri} className="flex items-center">
                        <div className={`${mu} font-mono text-right pr-2 flex-shrink-0`} style={{ width: Math.max(80, feats[ri].length * 6), fontSize: 9, whiteSpace: 'nowrap' }} title={feats[ri]}>
                          {feats[ri].length > 14 ? feats[ri].substring(0, 14) + '…' : feats[ri]}
                        </div>
                        {row.map((val, ci) => (
                          <div key={ci}
                            style={{ width: cellSize, height: cellSize, backgroundColor: corrColor(val), border: '1px solid rgba(0,0,0,0.1)' }}
                            title={`${feats[ri]} × ${feats[ci]}: ${val.toFixed(3)}`}
                            className="flex-shrink-0"
                          />
                        ))}
                      </div>
                    ))}
                  </div>
                </div>
              )
            })() : !corrLoading && (
              <div className={`py-12 text-center ${mu}`}>
                <p className="text-2xl mb-3 font-mono opacity-40">▦</p>
                <p className="text-sm">Run Phase 3 to compute correlations</p>
              </div>
            )}
          </div>

          {correlations && (() => {
            const feats = correlations.features as string[]
            const matrix = correlations.matrix as number[][]
            const pairs: Array<{ a: string; b: string; corr: number }> = []
            for (let i = 0; i < feats.length; i++)
              for (let j = i + 1; j < feats.length; j++) {
                const v = matrix[i][j]
                if (!isNaN(v)) pairs.push({ a: feats[i], b: feats[j], corr: v })
              }
            const top = pairs.sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr)).slice(0, 15)
            return (
              <div className={`${card} border rounded-xl p-6`}>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest mb-4`}>Top 15 Correlated Feature Pairs</h3>
                <div className="space-y-2">
                  {top.map((p, i) => (
                    <div key={i} className="flex items-center gap-4">
                      <span className={`${mu} text-[10px] w-4 font-mono`}>{i + 1}</span>
                      <span className="font-mono text-[11px]" style={{ color: featColor(p.a) }}>{p.a}</span>
                      <span className={`${mu} text-[10px]`}>↔</span>
                      <span className="font-mono text-[11px]" style={{ color: featColor(p.b) }}>{p.b}</span>
                      <div className="flex-1 h-1.5 rounded-full bg-slate-800 overflow-hidden ml-2">
                        <div className="h-full rounded-full" style={{ width: `${Math.abs(p.corr) * 100}%`, backgroundColor: p.corr > 0 ? '#10b981' : '#f43f5e' }} />
                      </div>
                      <span className={`font-mono text-[11px] font-bold w-14 text-right ${p.corr > 0.8 || p.corr < -0.8 ? 'text-rose-400' : p.corr > 0.6 || p.corr < -0.6 ? 'text-amber-400' : tx}`}>
                        {fmtSigned(p.corr, 3)}
                      </span>
                    </div>
                  ))}
                </div>
                <p className={`${mu} text-[10px] mt-4`}>⚠ Pairs with |ρ| &gt; 0.80 are highly collinear — consider removing one</p>
              </div>
            )
          })()}
        </div>
      )}

      {/* ── MODEL CATALOG ─────────────────────────────────────────────────── */}
      {activeTab === 'catalog' && (
        <div className="space-y-6">
          {catalogLoading && (
            <div className={`py-16 text-center ${mu}`}>
              <div className="w-8 h-8 border-2 border-violet-500/40 border-t-violet-500 rounded-full animate-spin mx-auto mb-4" />
              <p className="text-sm">Loading model catalog…</p>
            </div>
          )}

          {/* Catalog cards */}
          {!catalogLoading && Object.keys(modelCatalog).length > 0 && (
            <div className="grid grid-cols-3 gap-4">
              {Object.entries(modelCatalog).map(([key, info]: [string, any]) => {
                const mt = MODEL_TYPES.find(m => m.key === key)
                return (
                  <div key={key} className={`${card} border rounded-xl p-5 flex flex-col ${info.trained ? 'border-violet-500/30' : ''}`}>
                    <div className="flex justify-between items-start mb-3">
                      <div>
                        <h4 className={`${tx} font-bold text-sm`}>{info.name}</h4>
                        <span className={`text-[10px] font-mono font-bold uppercase tracking-widest`} style={{ color: mt?.color || '#ffb000' }}>{info.type}</span>
                      </div>
                      {info.trained && (
                        <div className="flex flex-col items-end gap-1">
                          <span className="px-2 py-0.5 text-[9px] font-bold bg-violet-500/20 text-violet-400 rounded-full">✓ Trained</span>
                          {info.best_auc > 0 && <span className="text-[9px] font-mono text-violet-300">AUC {info.best_auc?.toFixed(3)}</span>}
                        </div>
                      )}
                    </div>
                    <p className={`text-[11px] ${mu} mb-3 leading-relaxed flex-1`}>{info.description}</p>
                    <div className="space-y-1 mb-4">
                      {info.pros?.slice(0, 2).map((p: string, i: number) => (
                        <p key={i} className="text-[10px] text-emerald-400 flex gap-1.5"><span>+</span><span>{p}</span></p>
                      ))}
                      {info.cons?.slice(0, 1).map((c: string, i: number) => (
                        <p key={i} className="text-[10px] text-rose-400/70 flex gap-1.5"><span>−</span><span>{c}</span></p>
                      ))}
                    </div>
                    <button
                      onClick={() => { setDefaultModelType(key); setShowConfigModal(true) }}
                      className="py-2 text-[11px] font-bold rounded-lg transition w-full"
                      style={{ backgroundColor: (mt?.color || '#8b5cf6') + '25', color: mt?.color || '#8b5cf6' }}
                    >
                      Train {info.name}
                    </button>
                  </div>
                )
              })}
            </div>
          )}

          {/* Empty catalog fallback */}
          {!catalogLoading && Object.keys(modelCatalog).length === 0 && (
            <div className={`${card} border rounded-xl py-16 text-center ${mu}`}>
              <p className="text-4xl mb-4" style={{ color: 'var(--t-dim)' }}>◇</p>
              <p className="text-sm font-semibold">Model catalog unavailable</p>
              <p className="text-xs mt-2 opacity-70">ml-service may not be running — check service health</p>
            </div>
          )}

          {/* Registry comparison table */}
          <div className={`${card} border rounded-xl overflow-hidden`}>
            <div className={`px-6 py-4 border-b ${isDark ? 'border-slate-800' : 'border-slate-200'} flex justify-between items-center`}>
              <div>
                <h3 className={`${tx} text-xs font-bold uppercase tracking-widest`}>Model Comparison Registry</h3>
                <p className={`${mu} text-[11px] mt-0.5`}>All trained models in this session — activate to use for inference</p>
              </div>
              <div className="flex gap-3">
                <span className={`text-[11px] font-mono ${mu}`}>{modelRegistry.length} model(s)</span>
                <button
                  onClick={() => getModelRegistry().then(r => setModelRegistry(r.data || [])).catch(() => {})}
                  className={`px-3 py-1 text-[10px] font-bold rounded-lg ${isDark ? 'bg-slate-800 text-slate-300 hover:bg-slate-700' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'} transition`}
                >↻ Refresh</button>
              </div>
            </div>

            {modelRegistry.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead className={`${isDark ? 'bg-slate-900' : 'bg-slate-100'}`}>
                    <tr>
                      {['Model', 'Type', 'Accuracy', 'AUC-ROC', 'F1', 'Features', 'Trained At', 'Status', 'Actions'].map(h => (
                        <th key={h} className={`px-4 py-3 text-left ${mu} uppercase tracking-widest text-[9px] font-bold whitespace-nowrap`}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className={`divide-y ${isDark ? 'divide-slate-800/50' : 'divide-slate-100'}`}>
                    {modelRegistry.map((m: any) => {
                      const mt = MODEL_TYPES.find(t => t.key === m.model_type)
                      return (
                        <tr key={m.model_id} className={m.is_active ? (isDark ? 'bg-violet-500/5' : 'bg-violet-50') : ''}>
                          <td className="px-4 py-3">
                            <span className={`font-bold ${tx}`}>{m.display_name}</span>
                            <span className={`block font-mono text-[9px] ${mu} truncate max-w-[120px]`}>{m.model_id}</span>
                          </td>
                          <td className="px-4 py-3">
                            <span className="px-2 py-0.5 text-[9px] font-bold rounded-full" style={{ backgroundColor: (mt?.color || '#8b5cf6') + '25', color: mt?.color || '#8b5cf6' }}>
                              {m.model_type}
                            </span>
                          </td>
                          <td className={`px-4 py-3 font-mono font-bold ${(m.metrics?.accuracy || 0) >= 0.55 ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {m.metrics?.accuracy?.toFixed(3) || '—'}
                          </td>
                          <td className={`px-4 py-3 font-mono font-bold ${(m.metrics?.auc_roc || 0) >= 0.6 ? 'text-violet-400' : 'text-amber-400'}`}>
                            {m.metrics?.auc_roc?.toFixed(3) || '—'}
                          </td>
                          <td className={`px-4 py-3 font-mono ${tx}`}>{m.metrics?.f1_score?.toFixed(3) || '—'}</td>
                          <td className={`px-4 py-3 font-mono ${mu}`}>{m.n_features}</td>
                          <td className={`px-4 py-3 font-mono ${mu} text-[9px] whitespace-nowrap`}>
                            {(() => { const d = new Date(m.trained_at); return m.trained_at && !isNaN(d.getTime()) ? d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : (m.trained_at || '—') })()}
                          </td>
                          <td className="px-4 py-3">
                            {m.is_active
                              ? <span className="px-2 py-1 text-[9px] font-bold bg-violet-500/20 text-violet-400 rounded-full">ACTIVE</span>
                              : <span className={`text-[9px] ${mu}`}>idle</span>}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex gap-2">
                              <button
                                onClick={() => { setDefaultModelType(m.model_type); setShowConfigModal(true) }}
                                className="px-2.5 py-1 text-[9px] font-bold rounded bg-amber-500/20 text-amber-400 hover:bg-amber-500/40 transition whitespace-nowrap"
                              >Retrain</button>
                              {!m.is_active && (
                                <button
                                  onClick={async () => {
                                    try { await activateModel(m.model_id) } catch {}
                                    getModelRegistry().then(r => setModelRegistry(r.data || [])).catch(() => {})
                                    onMetricsRefresh()
                                  }}
                                  className="px-2.5 py-1 text-[9px] font-bold rounded bg-violet-600/30 text-violet-400 hover:bg-violet-600/50 transition whitespace-nowrap"
                                >Activate</button>
                              )}
                              {!m.is_active && (
                                <button
                                  onClick={async () => {
                                    try { await deleteModel(m.model_id) } catch {}
                                    getModelRegistry().then(r => setModelRegistry(r.data || [])).catch(() => {})
                                  }}
                                  className="px-2.5 py-1 text-[9px] font-bold rounded bg-rose-500/20 text-rose-400 hover:bg-rose-500/40 transition"
                                >Delete</button>
                              )}
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className={`py-14 text-center ${mu}`}>
                <p className="text-3xl mb-3" style={{ color: 'var(--t-dim)' }}>◇</p>
                <p className="text-sm">No models trained yet this session</p>
                <p className="text-xs mt-2 opacity-70">Train a model using "Configure & Train" to compare results</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
