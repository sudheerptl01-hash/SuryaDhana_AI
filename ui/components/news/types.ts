// Shapes returned by /api/news-scanner (see services/ui-api/routers/news_scanner.py)

export interface NewsSymbol {
  yahoo: string
  tv: string
  base: string
  exchange: string
  region: 'US' | 'IN' | 'UK' | 'OTHER'
}

export interface NewsItem { date: string | null; text: string }
export interface Source { url: string; domain: string }

export interface Pick {
  raw_ticker: string
  symbol: NewsSymbol | null
  company_name: string
  exchange: string
  news: NewsItem[]
  news_text: string
  sources: Source[]
  catalyst_category: string | null
  market_consensus_gap: string | null
  reflexivity_thesis: string
  thesis_steps: string[]
  conviction_score: number
}

export interface Rejected {
  raw_ticker: string
  symbols: NewsSymbol[]
  company_name: string
  reason: string
}

export interface Scan {
  file: string
  source_format?: 'json' | 'json-array' | 'csv'
  unresolved_tickers?: string[]
  scan_date: string
  generated_by: string
  input_note?: string
  macro_context: string
  picks: Pick[]
  rejected: Rejected[]
  disclaimer: string
  run_log: string[]
  modified_at: string
  version: number
}

export interface ScanIndex {
  directory: string
  exists: boolean
  scans: { date: string; file: string; picks: number; rejected: number; version: number; error?: string | null }[]
  latest_version: number | null
}

export interface Quote {
  symbol: string
  available: boolean
  name?: string
  currency?: string
  exchange?: string
  price?: number
  prev_close?: number
  prev_date?: string | null     // exchange-local date of the bar the change is measured from
  market_date?: string | null
  change?: number
  change_pct?: number
  day_high?: number
  day_low?: number
  volume?: number
  high_52w?: number
  low_52w?: number
  market_time?: number
  gmtoffset?: number
  timezone?: string
  stale?: boolean
  spark?: number[]
  resolved_symbol?: string
}

export interface Candle { time: number; open: number; high: number; low: number; close: number; volume: number }
export interface Point { time: number; value: number }

export interface ChartStats {
  ret_1d: number | null; ret_5d: number | null; ret_1m: number | null
  ret_3m: number | null; ret_6m: number | null; ret_1y: number | null
  rsi_14: number | null; atr_pct: number | null
  sma20: number | null; sma50: number | null; sma200: number | null
  above_sma50: boolean | null; above_sma200: boolean | null
  avg_volume_20d: number | null; volume_ratio: number | null
  pct_from_52w_high: number | null; pct_from_52w_low: number | null
  history_days: number
}

export interface ChartData {
  symbol: string
  range: string
  interval: string
  intraday: boolean
  quote: Quote
  candles: Candle[]
  sma20: Point[]; sma50: Point[]; sma200: Point[]; rsi: Point[]
  stats: ChartStats
}

export interface Headline {
  title: string
  publisher: string
  link: string
  published_at: string | null
  related: string[]
  thumbnail: string | null
  feed: 'Yahoo Finance' | 'Google News'
}

/** A pick the user pinned — carried across daily scans (stored in localStorage). */
export interface PinnedPick { pick: Pick; scan_date: string; pinned_at: string }
