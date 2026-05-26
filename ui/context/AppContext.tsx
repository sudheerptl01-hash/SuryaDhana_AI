'use client'

import { createContext, useContext, useState, useCallback, ReactNode } from 'react'

// ── ML Config ─────────────────────────────────────────────────────────────────
export interface MLConfig {
  model_type: string
  n_estimators: number
  max_depth: number
  learning_rate: number
  subsample: number
  train_start: string
  train_end: string
}

// ── RL Config ─────────────────────────────────────────────────────────────────
export interface RLConfig {
  total_timesteps: number
  learning_rate: number
  n_steps: number
  batch_size: number
  n_epochs: number
  n_candidates: number
  max_positions: number
  train_start: string
  train_end: string
}

// ── Pipeline state ────────────────────────────────────────────────────────────
export interface PipelineState {
  featuresReady: boolean
  featureInspected: boolean
  modelTrained: boolean
  rlTrained: boolean
}

// ── Context shape ─────────────────────────────────────────────────────────────
interface AppContextType {
  watchlist: string[]
  addToWatchlist: (ticker: string) => void
  removeFromWatchlist: (ticker: string) => void
  clearWatchlist: () => void
  isWatched: (ticker: string) => boolean

  mlConfig: MLConfig
  setMLConfig: (cfg: Partial<MLConfig>) => void

  rlConfig: RLConfig
  setRLConfig: (cfg: Partial<RLConfig>) => void

  pipeline: PipelineState
  setPipeline: (s: Partial<PipelineState>) => void
}

// ── Defaults ──────────────────────────────────────────────────────────────────
const today = new Date()
const fiveYearsAgo = new Date(today)
fiveYearsAgo.setFullYear(today.getFullYear() - 5)
const fmt = (d: Date) => d.toISOString().slice(0, 10)

const DEFAULT_ML: MLConfig = {
  model_type: 'xgboost',
  n_estimators: 300,
  max_depth: 5,
  learning_rate: 0.05,
  subsample: 0.8,
  train_start: fmt(fiveYearsAgo),
  train_end: fmt(today),
}

const DEFAULT_RL: RLConfig = {
  total_timesteps: 100000,
  learning_rate: 0.0003,
  n_steps: 2048,
  batch_size: 64,
  n_epochs: 10,
  n_candidates: 15,
  max_positions: 5,
  train_start: fmt(fiveYearsAgo),
  train_end: fmt(today),
}

const DEFAULT_PIPELINE: PipelineState = {
  featuresReady: false,
  featureInspected: false,
  modelTrained: false,
  rlTrained: false,
}

// ── Context ───────────────────────────────────────────────────────────────────
const AppContext = createContext<AppContextType | undefined>(undefined)

export function AppProvider({ children }: { children: ReactNode }) {
  const [watchlist, setWatchlist] = useState<string[]>([])
  const [mlConfig, setMLConfigState] = useState<MLConfig>(DEFAULT_ML)
  const [rlConfig, setRLConfigState] = useState<RLConfig>(DEFAULT_RL)
  const [pipeline, setPipelineState] = useState<PipelineState>(DEFAULT_PIPELINE)

  const addToWatchlist = useCallback((ticker: string) => {
    setWatchlist(prev => prev.includes(ticker) ? prev : [...prev, ticker])
  }, [])

  const removeFromWatchlist = useCallback((ticker: string) => {
    setWatchlist(prev => prev.filter(t => t !== ticker))
  }, [])

  const clearWatchlist = useCallback(() => setWatchlist([]), [])

  const isWatched = useCallback((ticker: string) => watchlist.includes(ticker), [watchlist])

  const setMLConfig = useCallback((cfg: Partial<MLConfig>) => {
    setMLConfigState(prev => ({ ...prev, ...cfg }))
  }, [])

  const setRLConfig = useCallback((cfg: Partial<RLConfig>) => {
    setRLConfigState(prev => ({ ...prev, ...cfg }))
  }, [])

  const setPipeline = useCallback((s: Partial<PipelineState>) => {
    setPipelineState(prev => ({ ...prev, ...s }))
  }, [])

  return (
    <AppContext.Provider value={{
      watchlist, addToWatchlist, removeFromWatchlist, clearWatchlist, isWatched,
      mlConfig, setMLConfig,
      rlConfig, setRLConfig,
      pipeline, setPipeline,
    }}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}

export function useWatchlist() {
  const { watchlist, addToWatchlist, removeFromWatchlist, clearWatchlist, isWatched } = useApp()
  return { watchlist, addToWatchlist, removeFromWatchlist, clearWatchlist, isWatched }
}

export function useMLConfig() {
  const { mlConfig, setMLConfig } = useApp()
  return { mlConfig, setMLConfig }
}

export function useRLConfig() {
  const { rlConfig, setRLConfig } = useApp()
  return { rlConfig, setRLConfig }
}

export function usePipeline() {
  const { pipeline, setPipeline } = useApp()
  return { pipeline, setPipeline }
}
