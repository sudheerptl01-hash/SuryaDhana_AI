'use client'

import { Z } from '@/lib/z'
import { apiError } from '@/lib/errors'
import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { ThemeProvider, useTheme } from '@/context/ThemeContext'
import { AppProvider, useWatchlist } from '@/context/AppContext'
import {
  getDashboardSummary,
  getEnrichmentStatus,
  listStocks,
  screenStocks,
  triggerRefresh,
  refreshWatchlist,
  getRefreshStatus,
  bootstrapUniverse,
  triggerEnrich,
  getEnrichProgress,
  getDeskStatus,
  getCrashFilter,
  type CrashFilter,
} from '@/lib/api'
import { getArchiveMeta } from '@/lib/api'
import { goToPage } from '@/lib/navigate'
import { LiveMonitorBar } from '@/components/LiveMonitorBar'
import { MarketCommandHeader, inEodWindow } from '@/components/MarketCommandHeader'
import { ToastProvider } from '@/context/ToastContext'
import { ErrorCatcher, UiErrorChip } from '@/components/ErrorCatcher'
import { AlertSaveToasts, DownloadToasts, UnknownTabToast, WorkspaceSaveToasts } from '@/components/shell/ShellToasts'
import { useDocumentHidden, useOnFocus, usePolling } from '@/components/shell/usePoll'
import { refreshVerdict } from '@/lib/refreshStatus'
import { NewsDock } from '@/components/news/NewsDock'
import { CommandBar, type CommandPage } from '@/components/CommandBar'
import { SettingsImport } from '@/components/shell/SettingsImport'
import { crashLines } from '@/components/marketPagesModel'
import { PAGE_HANDOFF_EVENT, stripStaleSub } from '@/lib/goAliases'
import { SUB_VIEW_EVENT } from '@/components/terminal/source'
import { Brief } from '@/components/Brief'
import { TabErrorBoundary } from '@/components/shell/TabErrorBoundary'
import { useShellState } from '@/components/shell/ShellState'
import { loadTabModule, resolvedTabModule, tabModuleIds } from '@/components/shell/tabModules'
import { buildSearch, closeStockAction, isTerminalState, normalizeSym, parseLocation, type TerminalHistoryState } from '@/lib/deepLink'
import { RECONNECTED_EVENT, needsReloadAfterOutage, reconnectDelayMs } from '@/lib/reconnect'
import { GO_COMMAND_EVENT, footerHint, goOpenAfterRetry, onMac } from '@/lib/shortcuts'
import { useFooterDataTone } from '@/lib/dataHealthStore'
import { newWindow } from '@/lib/platform'
import dynamic from 'next/dynamic'

// ── per-tab code splitting (F4.9): BRIEF and the chrome load eagerly; every other tab's chunk
// is fetched when it is first opened, with a TabSkeleton while in flight. ssr:false — the
// terminal is a client app and these pages poll live endpoints on mount.
// Perf (desktop program D4, reports/desktop_app/perf_baseline.md): a suspending dynamic() boundary shows the
// skeleton and React then holds the reveal for its 300 ms fallback throttle, even for a 10 ms chunk. So each
// tab renders its module directly once it has resolved (first visit, the idle warm-up in HomeContent, or the boot
// preload PlatformShell runs for the URL's page while the boot gate shows, C2-performance-02): no Suspense, no
// skeleton, no 300 ms floor. Chosen once per mount (no remount, no state loss). Loaders: components/shell/tabModules.ts.
type AnyComponent = React.ComponentType<any>
const lazyTab = (id: string, pick: (m: Record<string, unknown>) => unknown) => {
  const get = (m: Record<string, unknown>) => pick(m) as AnyComponent
  const Lazy = dynamic(() => loadTabModule(id).then(get), { loading: () => <TabSkeleton />, ssr: false })
  const Tab = (props: any) => {
    const [C] = useState<AnyComponent>(() => { const m = resolvedTabModule(id); return m ? get(m) : Lazy })
    return <C {...props} />
  }
  return Tab
}
const PipelineStudio = lazyTab('pipeline', m => m.PipelineStudio)
const LivePortfolio = lazyTab('positions', m => m.LivePortfolio)
const BacktestPanel = lazyTab('backtest', m => m.BacktestPanel)
const SystemTelemetry = lazyTab('system', m => m.SystemTelemetry)
const LWScanner = lazyTab('scanner', m => m.LWScanner)
const DataExplorerTab = lazyTab('explorer', m => m.DataExplorerTab)
const WarehouseHealth = lazyTab('warehouse', m => m.WarehouseHealth)
const AlphaDiscoveryDesk = lazyTab('discovery', m => m.AlphaDiscoveryDesk)
const CommodityTab = lazyTab('commodity', m => m.CommodityTab)
const MLEngineWorkspace = lazyTab('mlengine', m => m.MLEngineWorkspace)
const GlassBoxStudio = lazyTab('glassbox', m => m.GlassBoxStudio)
const PortfolioSummary = lazyTab('broker', m => m.PortfolioSummary)
const DecisionDesk = lazyTab('desk', m => m.DecisionDesk)
const MarketMonitor = lazyTab('markets', m => m.MarketMonitor)
const ResearchLibrary = lazyTab('research', m => m.ResearchLibrary)
const EventCalendar = lazyTab('events', m => m.EventCalendar)
const WatchMonitor = lazyTab('watch', m => m.WatchMonitor)
const Compare = lazyTab('compare', m => m.Compare)
const OptionChain = lazyTab('options', m => m.OptionChain)
const InsiderMonitor = lazyTab('insiders', m => m.InsiderMonitor)
const DealsMonitor = lazyTab('deals', m => m.DealsMonitor)
const PreOpen = lazyTab('preopen', m => m.PreOpen)
const IpoMonitor = lazyTab('ipo', m => m.IpoMonitor)
const LiveMovers = lazyTab('movers', m => m.LiveMovers)
const DailyWrap = lazyTab('wrap', m => m.DailyWrap)
const CompanyFilings = lazyTab('filings', m => m.CompanyFilings)
const MarginMonitor = lazyTab('margin', m => m.MarginMonitor)
const FundamentalsScreen = lazyTab('screen', m => m.FundamentalsScreen)
const AlertsCenter = lazyTab('alerts', m => m.AlertsCenter)
const EconomicCalendar = lazyTab('eco', m => m.EconomicCalendar)
const IndexMembers = lazyTab('memb', m => m.IndexMembers)
const OwnershipShifts = lazyTab('holders', m => m.OwnershipShifts)
const WorldMarkets = lazyTab('world', m => m.WorldMarkets)
const StockTable = lazyTab('stocks', m => m.StockTable)
const SystemStatusWidget = lazyTab('overview', m => m.SystemStatusWidget)
const SeasonalityPage = lazyTab('seag', m => m.SeasonalityPage)
const ChartStudio = lazyTab('charts', m => m.ChartStudio)
const DerivativesDesk = lazyTab('derivatives', m => m.DerivativesDesk)
const StrategyBuilder = lazyTab('ostrategy', m => m.StrategyBuilder)
const McxGoldDesk = lazyTab('mcxgold', m => m.McxGoldDesk)
const GoldPage = lazyTab('gold', m => m.GoldPage)
const RiskDashboard = lazyTab('risk', m => m.RiskDashboard)
const GamePlan = lazyTab('gameplan', m => m.GamePlan)
// the stock window opens over any tab; its chunk loads on first open (or during the boot gate for a ?sym= link)
const StockDetailModalLazy = dynamic(() => loadTabModule('stock').then(m => m.StockDetailModal as AnyComponent),
  { loading: () => <Loading label="stock window" />, ssr: false })
function StockDetailModal(props: any) {
  const [C] = useState<AnyComponent>(() => (resolvedTabModule('stock')?.StockDetailModal as AnyComponent | undefined) ?? StockDetailModalLazy)
  return <C {...props} />
}

import { OPEN_TICKER_EVENT, type TickerFocus } from '@/lib/openTicker'
import { GOTO_EVENT } from '@/lib/navigate'
import { Btn, Chip, ErrorBox, Grid, KV, Loading, Meter, PageHeader, Panel, ResearchNote, Stat, T, TabSkeleton, fmtInr, fmtSignedPct, tone, sourceOf, referenceSource } from '@/components/terminal'

type Tab = 'brief' | 'watch' | 'charts' | 'compare' | 'screen' | 'alerts' | 'eco' | 'seag' | 'memb' | 'options' | 'ostrategy' | 'derivatives' | 'insiders' | 'deals' | 'preopen' | 'ipo' | 'movers' | 'wrap' | 'filings' | 'margin' | 'holders' | 'world' | 'desk' | 'markets' | 'events' | 'overview' | 'stocks' | 'backtest' | 'positions' | 'broker' | 'pipeline' | 'scanner' | 'discovery' | 'commodity' | 'mcxgold' | 'gold' | 'glassbox' | 'mlengine' | 'explorer' | 'warehouse' | 'research' | 'risk' | 'system' | 'gameplan'

const FILTERS_INIT = { t1: false, t2: false, t3: false, t4: false, t5: false, t6: false, t7: false, t8: false }

const TAB_IDS: Tab[] = ['brief', 'watch', 'charts', 'compare', 'screen', 'alerts', 'eco', 'seag', 'memb', 'options', 'ostrategy', 'derivatives', 'insiders', 'deals', 'preopen', 'ipo', 'movers', 'wrap', 'filings', 'margin', 'holders', 'world', 'desk', 'markets', 'events', 'overview', 'stocks', 'backtest', 'positions', 'broker', 'pipeline', 'scanner',
  'discovery', 'commodity', 'mcxgold', 'gold', 'glassbox', 'mlengine', 'explorer', 'warehouse', 'research', 'risk', 'system', 'gameplan']

// Bloomberg-style function codes for the command bar ("/" or Ctrl/⌘+K)
const COMMAND_PAGES: CommandPage[] = [
  { id: 'brief',     code: 'BRF',   label: 'Morning brief',         hint: 'market, book, events, gold, news, system' },
  { id: 'gameplan',  code: 'GPLN',  label: 'Morning game plan',     hint: 'overnight moves, prior-session levels, OI walls & max pain, IV regime, today\'s events, focus list — assembled, dated, badged' },
  { id: 'watch',     code: 'WTCH',  label: 'Watch monitor',         hint: 'watchlist, pins, holdings: live quotes' },
  { id: 'charts',    code: 'CHRT',  label: 'Chart studio',          hint: 'candles, indicators, intraday VWAP' },
  { id: 'world',     code: 'WEI',   label: 'World markets',         hint: 'global indices, FX, commodities, rates' },
  { id: 'eco',       code: 'ECO',   label: 'Economic calendar',     hint: 'CPI, WPI, IIP, GDP releases · RBI and Fed decisions' },
  { id: 'memb',      code: 'MEMB',  label: 'Index members',         hint: 'members & drivers: who moved NIFTY 50 / BANK over 1D–YTD (DRVR · IMAP · CONTRIB), weights, returns, P/E' },
  { id: 'seag',      code: 'SEAG',  label: 'Seasonality',           hint: 'average return by month · NIFTY, sectors, any stock' },
  { id: 'preopen',   code: 'PRE',   label: 'Pre-open auction',      hint: '09:00–09:08: IEP, gaps, order imbalance' },
  { id: 'movers',    code: 'MOV',   label: 'Live movers',           hint: 'intraday gainers, volume surges, 52w highs, sectors' },
  { id: 'filings',   code: 'CF',    label: 'Company filings',       hint: 'today\'s NSE announcements: results, orders, ratings…' },
  { id: 'options',   code: 'OMON',  label: 'Option monitor',        hint: 'live chain in market hours: OI walls, IV, PCR, max pain' },
  { id: 'derivatives', code: 'DERV', label: 'Derivatives desk',     hint: 'basis, rollover, PCR, VIX · VOL: IV skew, term, cone, screener' },
  { id: 'ostrategy', code: 'OSTR',  label: 'Options strategies',    hint: 'payoffs, Greeks, breakevens' },
  { id: 'deals',     code: 'DEAL',  label: 'Block & bulk deals',    hint: 'named-client deals, netted, MF/insurer tagged' },
  { id: 'margin',    code: 'MRGN',  label: 'Margin monitor',        hint: 'MTF leverage build-ups and crowding' },
  { id: 'screen',    code: 'FUND',  label: 'Fundamentals screener', hint: 'P/E, growth, margin from NSE results filings' },
  { id: 'alerts',    code: 'ALRT',  label: 'Alerts',                hint: 'price alerts, fired history, notification inbox' },
  { id: 'holders',   code: 'HDS',   label: 'Ownership shifts',      hint: 'quarterly MF / FPI / promoter / retail changes' },
  { id: 'insiders',  code: 'INSD',  label: 'Insider monitor',       hint: 'promoter & director market buys' },
  { id: 'ipo',       code: 'IPO',   label: 'IPO monitor',           hint: 'open issues, subscription, listing scorecard' },
  { id: 'wrap',      code: 'WRAP',  label: 'Daily market wrap',     hint: 'end-of-day summary archive (21:00)' },
  { id: 'compare',   code: 'COMP',  label: 'Compare stocks',        hint: 'rebased performance, risk, correlation' },
  { id: 'desk',      code: 'DESK',  label: 'Decision Desk',         hint: 'monthly momentum allocator · paper' },
  { id: 'markets',   code: 'MKT',   label: 'Market Monitor',        hint: 'regime · breadth · sectors · movers' },
  { id: 'events',    code: 'EVTS',  label: 'Corporate calendar',    hint: 'results, dividends, splits, bonuses' },
  { id: 'overview',  code: 'OVRV',  label: 'Overview',              hint: 'universe and data health' },
  { id: 'stocks',    code: 'EQS',   label: 'Stocks / screener',     hint: 'T1–T8 filters, 1,500 NSE stocks' },
  { id: 'backtest',  code: 'BTST',  label: 'Backtest lab',          hint: 'walk-forward, real ICICI costs' },
  { id: 'positions', code: 'PORT',  label: 'Portfolio',             hint: 'LEGACY engine book (dormant) — live paper NAV is on DESK' },
  { id: 'broker',    code: 'BRKR',  label: 'Broker (ICICI)',        hint: 'holdings, positions, funds' },
  { id: 'pipeline',  code: 'PIPE',  label: 'Pipeline / watchlist',  hint: 'daily jobs and watchlist' },
  { id: 'scanner',   code: 'LWSC',  label: 'LW scanner',            hint: 'Larry Williams setups' },
  { id: 'discovery', code: 'ALFA',  label: 'Alpha discovery',       hint: 'hypothesis gauntlet' },
  { id: 'commodity', code: 'CMDT',  label: 'Commodities',           hint: 'global futures (USD) · EIA energy · FRED context' },
  { id: 'mcxgold',   code: 'MCXG',  label: 'MCX gold desk',         hint: 'session, quotes, contract selector, paper ticket' },
  { id: 'gold',      code: 'GOLD',  label: 'Gold terminal',         hint: 'spot, COMEX, MCX, positioning (COT), physical, macro, contracts, health check, pre-open fair value' },
  { id: 'glassbox',  code: 'GBOX',  label: 'Glass-Box studio',      hint: 'factor research, correlations' },
  { id: 'mlengine',  code: 'MLEN',  label: 'ML engine',             hint: 'models, labels, SHAP' },
  { id: 'explorer',  code: 'DEXP',  label: 'Data explorer',         hint: 'query DuckDB tables' },
  { id: 'warehouse', code: 'WHSE',  label: 'Warehouse health',      hint: 'NSE datasets and freshness' },
  { id: 'research',  code: 'RSCH',  label: 'Research library',      hint: 'every study and its verdict' },
  { id: 'risk',      code: 'RSK',   label: 'Risk dashboard',        hint: 'VaR, beta, stress, drawdown ladder' },
  { id: 'system',    code: 'SYS',   label: 'System telemetry',      hint: 'services, jobs, latency · DATA: freshness of every dataset' },
]

const PAGE_CODE: Record<string, string> = Object.fromEntries(COMMAND_PAGES.map(p => [p.id, p.code]))

/** P9: how often a visible window re-reads the dashboard summary (footer DATA date, OVRV). */
const DASHBOARD_REFRESH_MS = 10 * 60_000

/** A failed GO bar retries on its open command or the next key press (R-UI-SHELL-04)… */
const GO_RETRY_EVENTS = [GO_COMMAND_EVENT, 'keydown'] as const
/** …and, once it is back, opens for that attempt (⌘K, '/', the GO button, or a ticker letter as the seed). */
function goReplay(e: Event): Event | null {
  const k = e as KeyboardEvent
  const el = (e.target ?? null) as HTMLElement | null
  const typing = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || !!el.isContentEditable)
  let blocked = false
  try { blocked = !!document.querySelector('[role="dialog"]:not([data-sd-stock-window])') } catch { /* no DOM */ }
  const open = goOpenAfterRetry({ type: e.type, key: k.key ?? '', ctrlKey: !!k.ctrlKey, metaKey: !!k.metaKey, altKey: !!k.altKey,
    shiftKey: !!k.shiftKey, isComposing: !!k.isComposing, repeat: !!k.repeat, defaultPrevented: !!k.defaultPrevented }, { typing, blocked })
  if (!open) return null
  if (e.type === 'keydown') e.preventDefault()
  return new CustomEvent<string | null>(GO_COMMAND_EVENT, { detail: open.seed })
}

/** Where the terminal opens: ?tab= (else the brief) and ?sym= (the stock window), read once on the client. */
function initialLocation(): { tab: Tab; sym: string | null } {
  if (typeof window === 'undefined') return { tab: 'brief', sym: null }
  const loc = parseLocation(window.location.search, TAB_IDS, 'brief')
  return { tab: loc.tab as Tab, sym: loc.sym }
}

function HomeContent() {
  // Deep links (?tab=<id>&sym=<SYM>, K4): read in the initializer, so a new / restored / reloaded window renders its
  // page on the first render (PlatformShell renders the terminal only on the client, after its boot gate).
  const [view, setViewState] = useState<Tab>(() => initialLocation().tab)   // landing page: the morning brief
  const viewRef = useRef(view)
  viewRef.current = view
  const { desktop, link, downSince } = useShellState()
  const mac = useMemo(onMac, [])           // browser Back / Forward hint: ⌘[ ⌘] on a Mac (R-UI-SHELL-08)
  const { isDark, toggleTheme } = useTheme()
  const { watchlist, addToWatchlist, removeFromWatchlist, isWatched } = useWatchlist()
  const [dashboard, setDashboard] = useState<any>(null)
  // FINAL ROUND D-TONE (G3): the footer's DATA date turns amber when behind the last NSE session (weekend-safe;
  // the health service's holiday-aware last_session when it answers, else the shared Mon–Fri helper)
  const dataTone = useFooterDataTone(dashboard?.latest_date ?? null)
  const [enrichment, setEnrichment] = useState<any>(null)

  const [allStocks, setAllStocks] = useState<any[]>([])
  const [displayStocks, setDisplayStocks] = useState<any[]>([])
  const [totalStocks, setTotalStocks] = useState(0)
  const [isFiltered, setIsFiltered] = useState(false)
  const [filteredTotal, setFilteredTotal] = useState(0)

  const [selectedTicker, setSelectedTicker] = useState<string | null>(() => initialLocation().sym)

  const [tickerFocus, setTickerFocus] = useState<TickerFocus | null>(null)
  // Browser tab title follows the page code (BRF · SuryaDhana, OMON · SuryaDhana …)
  useEffect(() => {
    const code = COMMAND_PAGES.find(p => p.id === view)?.code
    document.title = code ? `${code} · SuryaDhana` : 'SuryaDhana Terminal'
  }, [view])

  // ── page history (C1-trader-ux-09): every page switch and every stock window is its own history entry, so
  // Back / Forward (browser, ⌘[ / ⌘] in the app) move between screens instead of leaving the terminal ──────────
  useEffect(() => {
    // tag the entry the terminal was opened on (URL unchanged): closing a deep-linked stock window replaces it
    const loc = parseLocation(window.location.search, TAB_IDS, 'brief')
    const st: TerminalHistoryState = { sd: 1, tab: loc.tab, sym: loc.sym, pushed: false }
    try { window.history.replaceState(st, '') } catch { /* history locked: navigation still works in place */ }
    const onPop = () => {
      const l = parseLocation(window.location.search, TAB_IDS, 'brief')
      setViewState(l.tab as Tab)
      setTickerFocus(null)
      setSelectedTicker(l.sym)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  // a sub-view hand-off (GO VOL / DATA / GOLD COT, a page's "VOL ›" chip) keeps `?sub=` on the next switch; a plain
  // switch to another page drops the previous page's stale `?sub=` (lib/goAliases.ts stripStaleSub)
  const lastHandoffAt = useRef(0)
  useEffect(() => {
    const on = () => { lastHandoffAt.current = Date.now() }
    window.addEventListener(PAGE_HANDOFF_EVENT, on)
    window.addEventListener(SUB_VIEW_EVENT, on)
    return () => { window.removeEventListener(PAGE_HANDOFF_EVENT, on); window.removeEventListener(SUB_VIEW_EVENT, on) }
  }, [])
  const setView = useCallback((t: Tab) => {
    setSelectedTicker(null)                     // leaving a page closes the stock window
    setTickerFocus(null)
    setViewState(t)
    const cur = window.history.state
    if (isTerminalState(cur) && cur.tab === t && !cur.sym) return
    const st: TerminalHistoryState = { sd: 1, tab: t, sym: null, pushed: true }
    const search = stripStaleSub(window.location.search, viewRef.current, t, Date.now() - lastHandoffAt.current)
    try { window.history.pushState(st, '', buildSearch(search, t, null)) } catch { /* in place */ }
  }, [])
  const openStock = useCallback((ticker: string, focus: TickerFocus | null = null) => {
    if (!ticker) return
    setTickerFocus(focus)
    setSelectedTicker(ticker)
    const sym = normalizeSym(ticker)
    if (!sym) return                              // not an NSE symbol (an index name…): open in place, no history entry
    const cur = window.history.state
    const tab = viewRef.current
    try {
      if (isTerminalState(cur) && cur.sym) {      // a stock window is already open: swap the symbol in place
        window.history.replaceState({ ...cur, sym } satisfies TerminalHistoryState, '', buildSearch(window.location.search, tab, sym))
      } else {
        const st: TerminalHistoryState = { sd: 1, tab, sym, pushed: true }
        window.history.pushState(st, '', buildSearch(window.location.search, tab, sym))
      }
    } catch { /* history locked */ }
  }, [])
  const closeStock = useCallback(() => {
    setSelectedTicker(null)
    setTickerFocus(null)
    const cur = window.history.state
    if (closeStockAction(cur, isTerminalState(cur) ? cur.sym : null) === 'back') { window.history.back(); return }
    if (new URLSearchParams(window.location.search).has('sym')) {
      const st: TerminalHistoryState = { sd: 1, tab: viewRef.current, sym: null, pushed: isTerminalState(cur) ? cur.pushed : false }
      try { window.history.replaceState(st, '', buildSearch(window.location.search, viewRef.current, null)) } catch { /* in place */ }
    }
  }, [])

  // Any component can open a stock with openTicker('TCS') (lib/openTicker.ts)
  useEffect(() => {
    const onOpen = (e: Event) => {
      const [t, f] = String((e as CustomEvent<string>).detail ?? '').split('|')
      if (t) openStock(t, (f as TickerFocus) || null)
    }
    window.addEventListener(OPEN_TICKER_EVENT, onOpen)
    return () => window.removeEventListener(OPEN_TICKER_EVENT, onOpen)
  }, [openStock])
  useEffect(() => {
    const onGo = (e: Event) => {
      const t = (e as CustomEvent<string>).detail as Tab
      if (TAB_IDS.includes(t)) setView(t)
    }
    window.addEventListener(GOTO_EVENT, onGo)
    return () => window.removeEventListener(GOTO_EVENT, onGo)
  }, [setView])
  const [filterLoading, setFilterLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [showRefreshPanel, setShowRefreshPanel] = useState(false)
  const [refreshStatus, setRefreshStatus] = useState<any>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  // UPDATE DATA outcome (CT-04): the start request failed / the progress poll failed. Never 'complete' without a status.
  const [triggerError, setTriggerError] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [bootstrapping, setBootstrapping] = useState(false)
  const [bootstrapResult, setBootstrapResult] = useState<any>(null)
  const [stocksPage, setStocksPage] = useState(0)
  const [technicalFilters, setTechnicalFilters] = useState(FILTERS_INIT)
  const [enriching, setEnriching] = useState(false)
  const [enrichProgress, setEnrichProgress] = useState<any>(null)

  // ── Universe data, loaded where it is used (C1-trader-ux-03) ─────────────────────────────────────────────
  // The 42 pages used to wait on 3 bootstrap calls (dashboard summary, enrichment status and the 0.9 MB
  // 1,500-stock list), and one failing call blocked every page behind "Backend unreachable". Now every page
  // renders at once; the small dashboard summary (header + status line + OVRV) loads in the background and
  // retries while it fails, the stock list loads only for EQS and the enrichment status only for OVRV, each with
  // its own error in place. A real ui-api outage is the connection banner's job (PlatformShell).
  const [dashError, setDashError] = useState<string | null>(null)
  const lastDashAt = useRef(0)
  const loadDashboard = useCallback(async () => {
    lastDashAt.current = Date.now()
    try {
      const dash = await getDashboardSummary()
      setDashboard(dash.data)
      setDashError(null)
    } catch (err: any) {
      setDashError(apiError(err, 'universe stats unavailable'))
    }
  }, [])
  // P9: a window left open for days kept the footer's DATA date and OVRV from its first load. The summary now also
  // refreshes every 10 min (30 min while hidden), when the window is shown again or gains focus (at most once a
  // minute), and after every outage (below).
  const hiddenDoc = useDocumentHidden()
  const pollDashboard = useCallback(() => { if (Date.now() - lastDashAt.current >= 60_000) void loadDashboard() }, [loadDashboard])
  usePolling(pollDashboard, hiddenDoc ? 30 * 60_000 : DASHBOARD_REFRESH_MS)
  useOnFocus(pollDashboard)
  useEffect(() => {
    if (!dashError) return
    const id = setTimeout(() => { loadDashboard() }, 15_000)
    return () => clearTimeout(id)
  }, [dashError, loadDashboard])

  const [stocksState, setStocksState] = useState<'idle' | 'loading' | 'ok' | 'error'>('idle')
  const [stocksError, setStocksError] = useState<string | null>(null)
  const loadStocks = useCallback(async () => {
    setStocksState('loading')
    setStocksError(null)
    try {
      const stocksRes = await listStocks(0, 1500)
      const stocks = stocksRes.data?.stocks || []
      const total = stocksRes.data?.total || stocks.length
      setAllStocks(stocks)
      setDisplayStocks(stocks)
      setTotalStocks(total)
      setStocksPage(0)
      setStocksState('ok')
    } catch (err: any) {
      setStocksError(apiError(err, 'stock list unavailable'))
      setStocksState('error')
      console.error('Failed to load the stock list:', err)
    }
  }, [])
  useEffect(() => { if (view === 'stocks' && stocksState === 'idle') loadStocks() }, [view, stocksState, loadStocks])
  useEffect(() => {
    if (stocksState !== 'error' || view !== 'stocks') return
    const id = setTimeout(() => { loadStocks() }, 15_000)
    return () => clearTimeout(id)
  }, [stocksState, view, loadStocks])
  const enrichAsked = useRef(false)
  useEffect(() => {
    if (view !== 'overview' || enrichAsked.current) return
    enrichAsked.current = true
    getEnrichmentStatus().then(r => setEnrichment(r.data)).catch(() => { enrichAsked.current = false })
  }, [view])

  // Perf (D4): warm every lazy tab module in idle time so first visits skip the skeleton (see lazyTab above)
  useEffect(() => {
    if ((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData) return
    let cancelled = false
    const ids = tabModuleIds()
    const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number }
    const idle = (cb: () => void) => (w.requestIdleCallback ? w.requestIdleCallback(cb, { timeout: 2000 }) : setTimeout(cb, 120))
    const next = (i: number) => {
      if (cancelled || i >= ids.length) return
      idle(() => { if (!cancelled) loadTabModule(ids[i]).catch(() => undefined).finally(() => next(i + 1)) })
    }
    const start = setTimeout(() => next(0), 3000)
    return () => { cancelled = true; clearTimeout(start) }
  }, [])

  // ── After an outage (C1-trader-ux-02): pages whose loads failed reload; healthy pages keep their state ────────
  // R-UI-SHELL-05: the page and the stock window have their OWN reload epochs, each bumped only when that surface's
  // own text shows a failed load (a healthy BTST page under a stock window whose intraday panel failed keeps its
  // results), only the page content is scanned (never the LINK DOWN notice beside it), and each window waits a
  // random 0–2 s first, so windows that come back together do not hit a just-recovered ui-api in the same instant.
  const mainRef = useRef<HTMLElement>(null)
  const [pageEpoch, setPageEpoch] = useState(0)
  const [stockEpoch, setStockEpoch] = useState(0)
  const retryRefs = useRef({ dashError, stocksState, loadDashboard, loadStocks })
  retryRefs.current = { dashError, stocksState, loadDashboard, loadStocks }
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null
    const onReconnected = () => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => {
        timer = null
        const pageEl = mainRef.current?.querySelector<HTMLElement>(`.sd-page[data-page="${viewRef.current}"]`)
        const page = pageEl?.innerText ?? ''
        const stock = document.querySelector('[data-sd-stock-window]')?.textContent ?? ''
        if (needsReloadAfterOutage(page)) setPageEpoch(e => e + 1)
        if (needsReloadAfterOutage(stock)) setStockEpoch(e => e + 1)
        const r = retryRefs.current
        r.loadDashboard()                         // P9: always, so the footer's DATA date and OVRV catch up after an outage
        if (r.stocksState === 'error') r.loadStocks()
      }, reconnectDelayMs())
    }
    window.addEventListener(RECONNECTED_EVENT, onReconnected)
    return () => { window.removeEventListener(RECONNECTED_EVENT, onReconnected); if (timer) clearTimeout(timer) }
  }, [])
  // R-UI-SHELL-04: a failed GO bar retries on the next ⌘K / '/' / type-to-GO (and the footer says so)
  const [goFailed, setGoFailed] = useState(false)

  // PipelineStudio keeps its training state across page switches once visited, and is not mounted (nor polling the
  // dormant RL pipeline) in windows that never open PIPE (C2-performance-06).
  const [pipelineSeen, setPipelineSeen] = useState(view === 'pipeline')
  useEffect(() => { if (view === 'pipeline') setPipelineSeen(true) }, [view])

  // ── Screener filter ───────────────────────────────────────────────────────
  const applyTechnicalFilters = useCallback(async (filters: typeof FILTERS_INIT) => {
    setTechnicalFilters(filters)
    const anyActive = Object.values(filters).some(Boolean)

    if (!anyActive) {
      setIsFiltered(false)
      setDisplayStocks(allStocks)
      return
    }

    setFilterLoading(true)
    try {
      const byTicker = new Map(allStocks.map((stock) => [stock.ticker, stock]))
      // Page through ALL matches (backend caps a page at 500). Fetching only the first
      // 200 while the header showed the full total silently hid the rest.
      const PAGE = 500
      const first = await screenStocks(filters, 0, PAGE)
      const total: number = first.data?.total ?? 0
      let rows: any[] = first.data?.results || []
      for (let skip = PAGE; skip < total; skip += PAGE) {
        const next = await screenStocks(filters, skip, PAGE)
        rows = rows.concat(next.data?.results || [])
      }
      const res = { data: { total, results: rows } }
      const results = (res.data?.results || []).map((r: any) => ({
        // Neutral fallbacks ONLY when the universe list has no record for the ticker;
        // the real data-quality fields from allStocks must win (they used to be
        // overwritten with a fabricated "excellent / 95% / 0 days" on every row).
        total_rows: 0,
        first_date: '',
        years_of_data: 0,
        data_density_pct: 0,
        days_since_update: null,
        data_quality: 'unknown',
        ...(byTicker.get(r.ticker) || {}),
        ticker: r.ticker,
        latest_price: r.latest_price,
        price_date: r.price_date,
        latest_date: r.price_date,
        ma50: r.ma50,
        ma150: r.ma150,
        ma200: r.ma200,
        rs_rating: r.rs_rating,
        sepa_stage: r.sepa_stage,
        filters: r.filters,
      }))
      setIsFiltered(true)
      setFilteredTotal(res.data?.total || results.length)
      setDisplayStocks(results)
    } catch (err) {
      console.error('Screener error:', err)
    } finally {
      setFilterLoading(false)
    }
  }, [allStocks])

  // ── Load more ─────────────────────────────────────────────────────────────
  const loadMoreStocks = async () => {
    const nextPage = stocksPage + 1
    setStocksPage(nextPage)
    const res = await listStocks(nextPage * 100, 100)
    const newBatch = res.data?.stocks || []
    const combined = [...allStocks, ...newBatch]
    setAllStocks(combined)
    if (!isFiltered) setDisplayStocks(combined)
  }

  // ── Bootstrap universe (cold-start: fetch Nifty 500 list from NSE) ─────────
  const handleBootstrap = async () => {
    setBootstrapping(true)
    setBootstrapResult(null)
    setRefreshError(null)
    try {
      const res = await bootstrapUniverse()
      setBootstrapResult(res.data)
      // Auto-trigger OHLCV refresh after successful bootstrap
      if (res.data?.status === 'bootstrapped') {
        setTimeout(() => handleRefresh(), 500)
      }
    } catch (err: any) {
      setRefreshError(apiError(err, 'Bootstrap failed. Check your internet connection.'))
    } finally {
      setBootstrapping(false)
    }
  }

  // ── Refresh: smart incremental OHLCV download (the header's ⤓ UPDATE DATA, after its confirm) ─────────────
  // Progress of a running download: every 3 s until ui-api says it is done, then the window's own data reloads.
  // A failed poll says PROGRESS UNAVAILABLE (the download may still be running), never 'complete'; COMPLETE needs
  // positive evidence (lib/refreshStatus.ts: after a ui-api restart the status is empty → STATUS UNKNOWN) (CT-04).
  // ONE poll chain at a time: a double-clicked ↻ CHECK AGAIN no longer starts two chains that both re-arm every 3 s.
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pollBusy = useRef(false)
  const expectedTotal = useRef<number | null>(null)       // stocks the start request reported (refreshVerdict)
  const schedulePoll = (ms: number) => {
    if (pollTimer.current) clearTimeout(pollTimer.current)
    pollTimer.current = setTimeout(() => { pollTimer.current = null; void pollRefresh() }, ms)
  }
  useEffect(() => () => { if (pollTimer.current) clearTimeout(pollTimer.current) }, [])
  const pollRefresh = async (): Promise<void> => {
    if (pollBusy.current) return
    pollBusy.current = true
    try {
      const res = await getRefreshStatus()
      setRefreshStatus(res.data)
      setStatusError(null)
      if (res.data?.active) {
        setRefreshing(true)
        schedulePoll(3000)
      } else {
        setRefreshing(false)
        // Re-fetch what this window shows after completion (the stock list / enrichment only once loaded)
        await loadDashboard()
        if (retryRefs.current.stocksState !== 'idle') await loadStocks()
        if (enrichAsked.current) getEnrichmentStatus().then(r => setEnrichment(r.data)).catch(() => {})
      }
    } catch (err: any) {
      setStatusError(apiError(err, 'progress unavailable'))
      setRefreshing(false)
    } finally {
      pollBusy.current = false
    }
  }

  const handleRefresh = async () => {
    if (refreshing) {
      setShowRefreshPanel(true)
      return
    }
    setRefreshing(true)
    setShowRefreshPanel(true)
    setRefreshStatus(null)
    setRefreshError(null)
    setTriggerError(null)
    setStatusError(null)
    expectedTotal.current = null
    try {
      const triggerRes = await triggerRefresh({ universe: 'nse_1500', years: 5 })
      const data = triggerRes.data
      expectedTotal.current = typeof data?.tickers === 'number' && data.tickers > 0 ? data.tickers : null

      // Backend signals no universe exists — show setup guidance
      if (data?.status === 'no_universe') {
        setRefreshError(data.message || 'No universe data found. Bootstrap first.')
        setRefreshing(false)
        return
      }
      schedulePoll(2000)
    } catch (err: any) {
      // the request itself failed (ui-api 5xx, data-service down, a guard 403, a timeout): say so, with RETRY (CT-04)
      console.error('Refresh error:', err)
      setTriggerError(apiError(err, 'the update request failed'))
      setRefreshing(false)
    }
  }

  // ── Enrich fundamentals (PE, MCap, NP QTR, Sales, ROCE) ─────────────────
  const handleEnrich = async () => {
    if (enriching) return
    setEnriching(true)
    setEnrichProgress(null)
    try {
      await triggerEnrich()
      const poll = async () => {
        try {
          const res = await getEnrichProgress()
          setEnrichProgress(res.data)
          if (res.data?.active) {
            setTimeout(poll, 5000)
          } else {
            setEnriching(false)
            const dash = await getDashboardSummary()
            setDashboard(dash.data)
          }
        } catch { setEnriching(false) }
      }
      setTimeout(poll, 2000)
    } catch { setEnriching(false) }
  }

  const activeFilterCount = Object.values(technicalFilters).filter(Boolean).length
  const displayCount = isFiltered ? filteredTotal : totalStocks

  // The page strip's DEFAULT order (page review 5 Nov M37: the trader's day; the owner re-orders it under MORE ▾ →
  // ARRANGE, stored in strip.order.v1, components/shell/stripOrder.ts DEFAULT_STRIP must equal these ids). Alt+1 … 0
  // = the first ten; desktop/src-tauri/src/pages.rs gives ⌘1 … 9 to the first nine. Research / legacy pages live
  // under RESEARCH ▾ (stripOrder.ts RESEARCH_PAGES), everything else under MORE ▾; all 43 stay on GO.
  const tabList = [
    { id: 'brief',     label: 'Brief' },
    { id: 'watch',     label: 'Watch' },
    { id: 'charts',    label: 'Charts' },
    { id: 'options',   label: 'Options' },
    { id: 'ostrategy', label: 'Strategy' },
    { id: 'derivatives', label: 'Deriv' },
    { id: 'movers',    label: 'Movers' },
    { id: 'events',    label: 'Events' },
    { id: 'alerts',    label: 'Alerts' },
    { id: 'risk',      label: 'Risk' },
    { id: 'gold',      label: 'Gold' },
    { id: 'mcxgold',   label: 'MCX Gold' },
    { id: 'markets',   label: 'Markets' },
    { id: 'desk',      label: 'Desk' },
  ]
  const stripBadges = { stocks: activeFilterCount || undefined, pipeline: watchlist.length || undefined }

  const renderPage = (): React.ReactNode => {
    switch (view) {
      case 'overview':
        return (
          <OverviewTab
            dashboard={dashboard}
            dashError={dashError}
            onRetryDashboard={loadDashboard}
            enrichment={enrichment}
            totalStocks={totalStocks}
            isDark={isDark}
            enriching={enriching}
            enrichProgress={enrichProgress}
            onEnrich={handleEnrich}
          />
        )
      case 'stocks':
        return (
          <StocksTab
            latestDate={dashboard?.latest_date ?? null}
            displayStocks={displayStocks}
            displayCount={displayCount}
            isFiltered={isFiltered}
            filterLoading={filterLoading}
            listLoading={stocksState === 'loading' || stocksState === 'idle'}
            listError={stocksState === 'error' ? stocksError : null}
            onRetryList={loadStocks}
            technicalFilters={technicalFilters}
            allStocksCount={allStocks.length}
            totalStocks={totalStocks}
            onFilterChange={applyTechnicalFilters}
            onRowClick={openStock}
            onLoadMore={loadMoreStocks}
            isDark={isDark}
            watchlist={watchlist}
            onWatchToggle={(ticker: string) => isWatched(ticker) ? removeFromWatchlist(ticker) : addToWatchlist(ticker)}
          />
        )
      case 'backtest': return <BacktestPanel isDark={isDark} watchlist={watchlist} />
      case 'positions': return <LivePortfolio isDark={isDark} />
      case 'broker': return <PortfolioSummary />
      case 'brief': return <Brief onNavigate={id => setView(id as Tab)} />
      case 'gameplan': return <GamePlan />
      case 'watch': return <WatchMonitor />
      case 'compare': return <Compare />
      case 'charts': return <ChartStudio />
      case 'options': return <OptionChain />
      case 'ostrategy': return <StrategyBuilder />
      case 'insiders': return <InsiderMonitor />
      case 'deals': return <DealsMonitor />
      case 'preopen': return <PreOpen />
      case 'ipo': return <IpoMonitor />
      case 'movers': return <LiveMovers />
      case 'wrap': return <DailyWrap />
      case 'filings': return <CompanyFilings />
      case 'margin': return <MarginMonitor />
      case 'screen': return <FundamentalsScreen />
      case 'alerts': return <AlertsCenter />
      case 'eco': return <EconomicCalendar />
      case 'seag': return <SeasonalityPage />
      case 'memb': return <IndexMembers />
      case 'holders': return <OwnershipShifts />
      case 'world': return <WorldMarkets />
      case 'desk': return <DecisionDesk isDark={isDark} />
      case 'risk': return <RiskDashboard isDark={isDark} />
      case 'markets': return <MarketMonitor onSelectTicker={openStock} />
      case 'derivatives': return <DerivativesDesk onSelectTicker={openStock} />
      case 'events': return <EventCalendar onSelectTicker={openStock} />
      case 'scanner': return <LWScanner />
      case 'discovery': return <AlphaDiscoveryDesk isDark={isDark} />
      case 'commodity': return <CommodityTab isDark={isDark} />
      case 'mcxgold': return <McxGoldDesk />
      case 'gold': return <GoldPage />
      case 'glassbox':
        return (
          <>
            <PageHeader code="GBOX" title="Glass-Box Studio"
                        subtitle="Relative rotation · rolling correlation + squeeze · volume profile" />
            <GlassBoxStudio isDark={isDark} />
          </>
        )
      case 'mlengine':
        return (
          <>
            <PageHeader code="MLEN" title="ML Engine"
                        subtitle="Live XGBoost direction-model training · streaming convergence · kill-switch" />
            <ResearchNote verdict="FAIL" report="reports/ml_labels/FINDINGS.md">
              The best labels (20-session excess rank) beat the old 5-day labels, but the ML top-20 book still trails plain
              Desk momentum after costs, and NSE flow features add nothing. Train here for research, not for trading.
            </ResearchNote>
            <MLEngineWorkspace isDark={isDark} />
          </>
        )
      case 'explorer':
        return (
          <>
            <PageHeader code="DEXP" title="Data Explorer"
                        subtitle="Paginated feature grid · sort · filter by ticker · data health" />
            <DataExplorerTab />
          </>
        )
      case 'warehouse': return <WarehouseHealth isDark={isDark} />
      case 'research': return <ResearchLibrary />
      case 'system': return <SystemTelemetry isDark={isDark} />
      case 'pipeline': return null            // mounted below, kept alive once visited
      default: return null
    }
  }

  const code = PAGE_CODE[view] ?? view.toUpperCase()
  const pageKey = `${view}:${pageEpoch}`
  // chrome boundaries retry on every page switch too, not only after an outage (R-UI-SHELL-04)
  const chromeKey = `${pageEpoch}:${view}`
  const linkDown = link === 'down'
  const downAt = downSince ? new Date(downSince).toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false }) : null
  return (
    <div style={{ minHeight: 'calc(100vh - var(--shell-top, 0px))', background: 'var(--t-bg)', color: 'var(--t-text)', paddingBottom: 30 }}>
      {/* ── NSE Operations Center Command Header (own boundary: a header crash never takes the page) ── */}
      <TabErrorBoundary name="HEADER" variant="bar" resetKey={chromeKey}>
        <MarketCommandHeader
          onRefresh={handleRefresh}
          refreshing={refreshing}
          totalStocks={dashboard?.total_stocks ?? totalStocks}
          latestDate={dashboard?.latest_date}
          activeTab={view}
          tabs={tabList}
          pages={COMMAND_PAGES}
          badges={stripBadges}
          onTabChange={(id) => setView(id as Tab)}
        />
      </TabErrorBoundary>

      {/* ── UPDATE DATA progress / setup panel (terminal kit, CT-04): says FAILED or PROGRESS UNAVAILABLE when that is
             what happened, never 'complete' without positive evidence from ui-api's progress (CT-04) ── */}
      {showRefreshPanel && (
        <RefreshPanel
          refreshing={refreshing}
          bootstrapping={bootstrapping}
          status={refreshStatus}
          setupError={refreshError}
          triggerError={triggerError}
          statusError={statusError}
          expectedTotal={expectedTotal.current}
          bootstrapResult={bootstrapResult}
          onBootstrap={handleBootstrap}
          onRetry={handleRefresh}
          onRecheck={() => { void pollRefresh() }}
          onClose={() => { setShowRefreshPanel(false); setRefreshError(null); setBootstrapResult(null); setTriggerError(null); setStatusError(null) }}
        />
      )}

      {/* ── Live Monitor Bar ────────────────────────────────────────────── */}
      <TabErrorBoundary name="WATCHLIST BAR" variant="silent" resetKey={chromeKey}>
        <LiveMonitorBar isDark={isDark} />
      </TabErrorBoundary>

      {/* ── Main Content: every page renders at once, inside its own error boundary (C1-trader-ux-01/-03) ── */}
      <main ref={mainRef} className="sd-main" data-link={linkDown ? 'down' : 'up'} style={{ padding: '12px 14px' }}>
        {linkDown && (
          <div className="sd-linkdown" role="status" aria-live="polite">
            <b>LINK DOWN</b>
            <span>{downAt ? `since ${downAt} IST · ` : ''}the panels below show the last data received before the outage;
              pages that failed reload when ui-api is back</span>
          </div>
        )}
        <div className="sd-page" key={pageKey} data-page={view}>
          <TabErrorBoundary name={code} tab={view} resetKey={pageKey}>
            {renderPage()}
          </TabErrorBoundary>
        </div>
        {pipelineSeen && (
          <div className="sd-page" style={{ display: view === 'pipeline' ? 'block' : 'none' }}>
            <TabErrorBoundary name="PIPE" tab="pipeline" resetKey={pageEpoch}>
              <PipelineStudio isDark={isDark} watchlist={watchlist} />
            </TabErrorBoundary>
          </div>
        )}
      </main>

      {/* ── Status line (Bloomberg-style) ─────────────────────────────── */}
      <footer style={{ position: 'fixed', bottom: 0, left: 0, right: 0, height: 22, zIndex: Z.footer, display: 'flex',
                       alignItems: 'center', gap: 14, padding: '0 12px', fontSize: 10, letterSpacing: 1.1, whiteSpace: 'nowrap',
                       borderTop: '1px solid var(--t-border)', background: '#07090d', color: 'var(--t-muted)' }}>
        <span className="sd-foot-chip" data-link={linkDown ? 'down' : 'up'} style={{ color: linkDown ? 'var(--t-red)' : 'var(--t-green)' }}
              title={linkDown ? 'ui-api unreachable: reconnecting' : 'terminal connected'}>
          ● {linkDown ? 'OFFLINE · LINK DOWN' : 'READY'}</span>
        <span className="sd-foot-opt" title={dataTone.title} data-data-behind={dataTone.amber ? '1' : undefined}
              style={dataTone.amber ? { color: 'var(--t-amber)' } : undefined}>DATA {dashboard?.latest_date ?? '—'}</span>
        <span className="sd-foot-opt">{(dashboard?.total_stocks ?? totalStocks).toLocaleString('en-IN')} STOCKS</span>
        {dashError && !linkDown && (
          <span className="sd-foot-chip" style={{ color: 'var(--t-amber)' }} title={`${dashError} · retrying every 15 s`}>◌ UNIVERSE STATS UNAVAILABLE</span>
        )}
        <span style={{ flex: 1 }} />
        <UiErrorChip />
        {/* News Catalyst Terminal: docked as a status-line segment on every tab */}
        <TabErrorBoundary name="NEWS" variant="silent" cue="NEWS" resetKey={chromeKey}>
          <NewsDock />
        </TabErrorBoundary>
        <button onClick={() => window.dispatchEvent(new Event('suryadhana:command'))}
          title={goFailed ? 'The GO bar stopped after an error: click (or press / or ⌘K) to retry'
            : `Command bar (/ or ${desktop ? '⌘K' : 'Ctrl+K'}, or just type a ticker)`}
          style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--t-amber)',
                   font: 'inherit', letterSpacing: 'inherit' }}>{goFailed ? '◌ GO UNAVAILABLE · RETRY' : '/ GO'}</button>
        <span className="t-hide-md">{footerHint(desktop, mac)}</span>
        <span style={{ color: 'var(--t-dim)' }}>{desktop ? 'NSE · PAPER' : <><span className="sd-foot-opt">SURYADHANA TERMINAL · </span>NSE · PAPER</>}</span>
      </footer>

      <TabErrorBoundary name="GO" variant="silent" resetKey={chromeKey} retryOn={GO_RETRY_EVENTS} replay={goReplay}
        onFailedChange={setGoFailed}>
        <CommandBar pages={COMMAND_PAGES} onPage={id => setView(id as Tab)} onTicker={t => openStock(t)} currentTab={view} />
      </TabErrorBoundary>

      {/* M35: the one-time settings-import toast + dialog (replaces the permanent "not imported yet" banner) */}
      <TabErrorBoundary name="SETTINGS IMPORT" variant="silent" resetKey={chromeKey}>
        <SettingsImport />
      </TabErrorBoundary>

      {selectedTicker && (
        <TabErrorBoundary key={`stock:${stockEpoch}`} name="STOCK WINDOW" tab={view} resetKey={`${selectedTicker}:${stockEpoch}`}
          variant="modal" onDismiss={closeStock}>
          <StockDetailModal ticker={selectedTicker} focus={tickerFocus} onClose={closeStock}
            onNewWindow={() => { void newWindow(view, normalizeSym(selectedTicker) ?? undefined) }} />
        </TabErrorBoundary>
      )}
    </div>
  )
}

// ── UPDATE DATA panel (CT-04) ─────────────────────────────────────────────────────
// What the header's UPDATE DATA did, in the terminal kit: the headline is what is KNOWN (the request failed, progress
// is unavailable, the download is running, ui-api reported every stock's outcome); it never says 'complete' without
// that evidence (lib/refreshStatus.ts). The manual setup commands sit behind a disclosure instead of in the panel.

interface RefreshPanelProps {
  refreshing: boolean
  bootstrapping: boolean
  status: any
  setupError: string | null
  triggerError: string | null
  statusError: string | null
  /** Stocks the start request reported (null: this window did not start it, or the reply had no count). */
  expectedTotal: number | null
  bootstrapResult: any
  onBootstrap: () => void
  onRetry: () => void
  onRecheck: () => void
  onClose: () => void
}

/** The panel's headline: [text, colour]. Exported shape is internal; the wording is the user-visible contract. */
function refreshHeadline(p: RefreshPanelProps): [string, string] {
  if (p.bootstrapping) return ['BOOTSTRAPPING THE NSE 500 UNIVERSE · niftyindices.com', T.amber]
  if (p.setupError) return ['SETUP REQUIRED · NO STOCK DATA FOUND', T.amber]
  if (p.triggerError) return [`UPDATE FAILED · ${p.triggerError}`, T.red]
  if (p.statusError) return [`PROGRESS UNAVAILABLE · ${p.statusError} · the download may still be running in ui-api`, T.amber]
  if (p.refreshing) {
    return [p.status?.total > 0 ? `DOWNLOADING DAILY PRICES · ${(p.status.pct ?? 0)}%` : 'STARTING THE DOWNLOAD…', T.amber]
  }
  if (p.status) {
    // COMPLETE only with positive evidence (CT-04): every stock has an outcome; ui-api's own count of failed stocks
    // makes it complete but not clean. An empty status (ui-api restarted mid-download) is STATUS UNKNOWN.
    const v = refreshVerdict(p.status, p.expectedTotal)
    if (v.kind === 'complete') {
      return v.failed > 0 ? [`UPDATE COMPLETE · ${v.failed.toLocaleString('en-IN')} FAILED`, T.amber] : ['UPDATE COMPLETE', T.green]
    }
    if (v.kind === 'unknown') return [`UPDATE STATUS UNKNOWN · ${v.reason}`, T.amber]
  }
  return ['UPDATE STATUS UNKNOWN', T.muted]
}

const TICKER_TONE: Record<string, string> = { done: T.green, downloading: T.amber, error: T.red }

function RefreshPanel(p: RefreshPanelProps) {
  const [headline, color] = refreshHeadline(p)
  const st = p.status
  // ↻ RETRY UPDATE starts the same 1,500-stock download: inside the EOD window (18:30–21:15) it needs a second,
  // explicit click, like the header's START (CT-04 adversarial check)
  const [armed, setArmed] = useState(false)
  const lost = !p.refreshing && !p.triggerError && !p.statusError && !p.setupError && !!st && refreshVerdict(st, p.expectedTotal).kind === 'unknown'
  const canRetry = !!p.triggerError || lost
  useEffect(() => { if (!canRetry) setArmed(false) }, [canRetry])
  const retry = () => {
    if (inEodWindow(Date.now()) && !armed) { setArmed(true); return }
    setArmed(false)
    p.onRetry()
  }
  const btn = (c: string) => ({ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.2, color: c, background: 'transparent',
                               border: `1px solid ${c}`, padding: '3px 9px', cursor: 'pointer' } as const)
  return (
    <section role="status" aria-live="polite" aria-label="Update data" data-sd-refresh-panel=""
      style={{ background: '#080b10', borderBottom: `1px solid ${T.border}`, borderTop: `2px solid ${color}`, padding: '8px 14px',
               fontFamily: T.mono, fontSize: 11, color: T.text }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: 1.2, color: T.bg, background: T.amber, padding: '2px 7px' }}>
          UPDATE DATA</span>
        <span style={{ color, fontWeight: 700, letterSpacing: 1 }}>{headline}</span>
        {st && !p.setupError && Number(st.total) > 0 && (
          <span style={{ color: T.muted, fontSize: 11 }}>
            {(st.done ?? 0).toLocaleString('en-IN')} downloaded · {(st.current ?? 0).toLocaleString('en-IN')} already current
            · {st.downloading ?? 0} active · {st.pending ?? 0} pending{st.errors > 0 ? ` · ${st.errors} errors` : ''}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {canRetry && (
          <button type="button" data-sd-refresh-retry="" onClick={retry} style={btn(T.amber)}
            title={armed ? 'The EOD pipeline is running (18:30–21:15 IST): click again to start the download anyway' : undefined}>
            {armed ? 'CONFIRM: RETRY DURING EOD' : '↻ RETRY UPDATE'}</button>
        )}
        {p.statusError && <button type="button" onClick={p.onRecheck} style={btn(T.amber)}>↻ CHECK AGAIN</button>}
        <button type="button" onClick={p.onClose} style={btn(T.muted)}>CLOSE</button>
      </div>

      {p.setupError && (
        <div style={{ marginTop: 8, padding: '8px 10px', border: `1px solid ${T.amber}55`, background: '#0b0f16' }}>
          <div style={{ fontSize: 11, color: T.amber }}>The database is empty and no universe list was found ({p.setupError}).</div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
            <button type="button" onClick={p.onBootstrap} disabled={p.bootstrapping}
              style={{ ...btn(T.green), cursor: p.bootstrapping ? 'wait' : 'pointer', opacity: p.bootstrapping ? 0.6 : 1 }}>
              {p.bootstrapping ? '↻ FETCHING…' : '▶ QUICK BOOTSTRAP (NIFTY 500)'}</button>
            <details style={{ fontSize: 11, color: T.muted }}>
              <summary style={{ cursor: 'pointer' }}>manual setup (terminal)</summary>
              <div style={{ marginTop: 4, color: T.text, userSelect: 'text' }}>
                scripts/nifty500_pipeline.py --mode universe1500<br />scripts/nifty500_pipeline.py --mode initial
              </div>
            </details>
          </div>
          {p.bootstrapResult && (
            <div style={{ marginTop: 6, fontSize: 11, color: T.green }}>
              ✓ {p.bootstrapResult.tickers} tickers loaded: downloading their daily prices now…</div>
          )}
        </div>
      )}

      {st?.total > 0 && !p.setupError && (
        <div style={{ marginTop: 8 }}><Meter value={(Number(st.pct) || 0) / 100} color={p.refreshing ? T.amber : T.green} height={3} /></div>
      )}

      {st?.tickers && Object.keys(st.tickers).length > 0 && !p.setupError && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 96, overflowY: 'auto', marginTop: 8 }}>
          {Object.entries(st.tickers as Record<string, string>).map(([t, v]) => (
            <span key={t} title={v} style={{ fontSize: 10, letterSpacing: .4, padding: '0 4px', border: `1px solid ${T.border}`,
                                             color: TICKER_TONE[v] ?? T.dim }}>{t}</span>
          ))}
        </div>
      )}

      {!st && p.refreshing && (
        <div style={{ marginTop: 6, fontSize: 11, color: T.muted }}>
          Daily prices from Yahoo Finance: only the days missing from the database are fetched. Progress appears in a few seconds.
        </div>
      )}
    </section>
  )
}

// ── Overview Tab ──────────────────────────────────────────────────────────────
const ROADMAP: { phase: string; label: string; detail: string; status: 'done' | 'active' | 'next' | 'later' }[] = [
  { phase: 'A', label: 'Costs · data · tax', detail: 'Real ICICI costs, NSE bhavcopy 2010→ (survivorship-free)', status: 'done' },
  { phase: 'B', label: 'Strategy research', detail: 'Momentum beats NIFTY after costs+tax, 2011–2026', status: 'done' },
  { phase: 'C', label: 'Decision Desk (paper)', detail: 'Monthly brief · paper fills · emergency stop', status: 'active' },
  { phase: 'D', label: 'India-specific signals', detail: 'Delivery %, bulk/block deals, insider buys, news scoring', status: 'next' },
  { phase: 'E', label: 'Small live', detail: 'After ≥ 3 months of paper inside the tracking band', status: 'later' },
]

// M08 (OVRV part): the crash filter as the same two labelled lines as BRF (components/marketPagesModel.ts crashLines):
// today's reading (what a signal on it would do) and where the book is and since when. The old single line read the
// 30 Oct plan ("ON · liquid fund") while BRF read today's number ("OFF · INVESTED") for one all-cash book.
function DeskSnapshot() {
  const [d, setD] = useState<any>(null)
  const [cf, setCf] = useState<CrashFilter | null>(null)
  useEffect(() => { getDeskStatus().then(r => setD(r.data)).catch(() => setD(null)) }, [])
  useEffect(() => { getCrashFilter().then(r => setCf(r.data)).catch(() => setCf(null)) }, [])
  const nav = d?.latest?.nav ?? d?.meta?.start_capital
  const start = d?.meta?.start_capital
  const plan = d?.plans?.[0]
  const lines = cf ? crashLines(cf, d) : null
  return (
    <Panel source={sourceOf(d?.latest?.date ?? null, { source: 'Desk ledger' })} title="Decision Desk" subtitle="paper book · monthly momentum"
      right={<Chip color={T.amber} active>PAPER</Chip>}>
      {!d ? <Loading label="Loading book" /> : (
        <KV items={[
          ['Book value', fmtInr(nav)],
          ['Return', fmtSignedPct(start ? (nav / start - 1) * 100 : null), tone(nav - start)],
          ['Positions', `${d.positions?.length ?? 0} / 20`],
          ['Latest brief', plan ? `${plan.plan_id} · ${plan.status}` : 'after month-end (19:30 IST)'],
          ["Crash filter · today's reading", lines ? lines.reading.replace(/^Today's reading: /, '') : '—'],
          ['Crash filter · book', lines ? lines.book.replace(/^The book: /, '') : '—'],
          ['Last marked', d.meta?.last_mark ?? '—'],
        ]} />
      )}
    </Panel>
  )
}

function OverviewTab({ dashboard, dashError, onRetryDashboard, totalStocks, enriching, enrichProgress, onEnrich }: any) {
  // R-UI-SHELL-02: until the dashboard summary has loaded, OVRV shows '—' and LOADING, never invented zeros
  // ('Universe 0', '0% CURRENT', '▶ Enrich now'); after a failure it shows only the error with RETRY.
  const loaded = !!dashboard
  const fresh = dashboard?.freshness?.fresh ?? 0
  const behind = dashboard?.freshness?.stale ?? 0
  const aged = dashboard?.freshness?.very_stale ?? 0
  const freshPct = dashboard?.freshness?.fresh_pct ?? 0
  const enriched = dashboard?.enrichment?.enriched ?? 0
  const enrichTotal = dashboard?.enrichment?.total ?? totalStocks
  const enrichPct = dashboard?.enrichment?.enrichment_pct ?? 0
  // quarterly financials read straight from NSE results filings (FA cache): companies covered
  const [faCount, setFaCount] = useState<number | null>(null)
  useEffect(() => { getArchiveMeta().then(r => setFaCount(r.data['archive:financials']?.rows ?? 0)).catch(() => {}) }, [])
  const universeSize = dashboard?.universe_size ?? 0
  const coveragePct = dashboard?.coverage_pct ?? 0
  const universeLabel = (dashboard?.universe_label ?? 'nse_500').replace('nse_', 'NSE ').toUpperCase()
  const dbCount = dashboard?.total_stocks ?? totalStocks
  const pct = (n: number) => (n / Math.max(dbCount, 1)) * 100
  const statusColor = { done: T.green, active: T.amber, next: T.cyan, later: T.dim }
  const statusMark = { done: '✓', active: '▶', next: '›', later: '○' }
  const num = (n: number) => (loaded ? n.toLocaleString('en-IN') : '—')
  const pending = dashError ? 'unavailable' : 'loading…'

  return (
    <div>
      <PageHeader code="OVRV" title="Overview"
        subtitle={loaded ? `${universeLabel} universe · data through ${dashboard?.latest_date ?? '—'}` : `universe summary ${pending}`} />
      {dashError && !loaded && (
        <div style={{ marginBottom: 10 }}>
          <ErrorBox error={`universe stats unavailable: ${dashError} (retrying every 15 s)`} onRetry={onRetryDashboard} />
        </div>
      )}
      <div style={{ display: 'grid', gap: 10 }}>
        {(loaded || !dashError) && (
          <Grid cols={5}>
            <Stat label="Universe" value={num(universeSize)} sub={loaded ? universeLabel : pending} accent={T.cyan} />
            <Stat label="In database" value={num(dbCount)} sub={loaded ? `${coveragePct}% coverage` : pending} accent={T.violet} />
            <Stat label="Latest session" value={dashboard?.latest_date ?? '—'} sub={loaded ? `${freshPct}% of stocks current` : pending}
                  accent={!loaded ? T.dim : freshPct >= 95 ? T.green : T.amber} color={T.bright} />
            {/* m024: this is the screener's Yahoo price cache, not the research history (NSE bhavcopy 2010→) */}
            <Stat label="Price cache from" value={dashboard?.data_range?.from?.slice(0, 7) ?? '—'}
                  sub={loaded ? `→ ${dashboard?.data_range?.to ?? '—'} · Yahoo, for EQS · research: NSE bhavcopy 2010→` : pending} />
            <Stat label="Fundamentals" value={loaded ? `${enrichPct}%` : '—'}
                  sub={loaded ? `${enriched.toLocaleString('en-IN')} of ${enrichTotal.toLocaleString('en-IN')} enriched` : pending} accent={T.violet} />
          </Grid>
        )}

        {(loaded || !dashError) && (
          <Panel source={sourceOf(dashboard?.latest_date ?? null, { source: 'DuckDB EOD' })} title="Data freshness" subtitle={loaded ? `${dbCount.toLocaleString('en-IN')} stocks · measured in trading sessions behind the latest close`
                                                         : 'measured in trading sessions behind the latest close'}
            right={loaded
              ? <Chip color={freshPct >= 95 ? T.green : freshPct >= 80 ? T.amber : T.red} active>{freshPct}% CURRENT</Chip>
              : <Chip color={T.muted}>LOADING</Chip>}>
            {!loaded ? <Loading label="Loading the universe summary" /> : (
              <>
                <div style={{ display: 'flex', height: 6, background: T.border, marginBottom: 12 }}>
                  <div style={{ width: `${pct(fresh)}%`, background: T.green }} />
                  <div style={{ width: `${pct(behind)}%`, background: T.amber }} />
                  <div style={{ width: `${pct(aged)}%`, background: T.red }} />
                </div>
                <Grid cols={3}>
                  <Stat label="At latest session" value={fresh.toLocaleString('en-IN')} color={T.green} sub="updated at the last close" big={false} />
                  <Stat label="1–5 sessions behind" value={behind.toLocaleString('en-IN')} color={T.amber} sub="missed a recent refresh" big={false} />
                  <Stat label="> 5 sessions behind" value={aged.toLocaleString('en-IN')} color={T.red} sub="suspended / delisted / renamed" big={false} />
                </Grid>
              </>
            )}
          </Panel>
        )}

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 10 }}>
          <DeskSnapshot />
          <Panel source={referenceSource('docs/PRODUCT_STRATEGY.md')} title="Roadmap" subtitle="product plan">
            <div style={{ display: 'grid', gap: 6 }}>
              {ROADMAP.map(r => (
                <div key={r.phase} style={{ display: 'grid', gridTemplateColumns: '22px 1fr', gap: 8, padding: '6px 8px',
                                            borderLeft: `2px solid ${statusColor[r.status]}`, background: '#080b10' }}>
                  <span style={{ color: statusColor[r.status], fontWeight: 700 }}>{statusMark[r.status]}</span>
                  <div>
                    <div style={{ fontSize: 11, color: T.bright }}>
                      <span style={{ color: statusColor[r.status] }}>{r.phase}</span> · {r.label}
                      <span style={{ fontSize: 9, color: statusColor[r.status], marginLeft: 8, letterSpacing: 1 }}>{r.status.toUpperCase()}</span>
                    </div>
                    <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>{r.detail}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <SystemStatusWidget />
        </div>

        {(loaded || !dashError) && (
          <Panel source={sourceOf(dashboard?.latest_date ?? null, { source: 'fundamentals snapshot' })} title="Fundamentals enrichment" subtitle="PE · market cap · quarterly profit & sales · ROCE (snapshot, not point-in-time)"
            right={<Btn size="sm" onClick={onEnrich} disabled={enriching || !loaded}
                        title={loaded ? undefined : 'Waiting for the universe summary: the enrichment state is not known yet'}>
                     {enriching ? 'Enriching…' : !loaded ? '… ENRICH' : enriched === 0 ? '▶ Enrich now' : '↻ Re-enrich'}</Btn>}>
            {loaded && <Meter value={enrichPct / 100} color={T.violet} />}
            <div style={{ fontSize: 11, color: T.muted, marginTop: 6 }}>
              {loaded ? <>{enriched.toLocaleString('en-IN')} of {enrichTotal.toLocaleString('en-IN')} stocks have the snapshot (STOCKS columns).</>
                      : <>Snapshot coverage: {pending}.</>}
              {faCount != null && <> Quarterly financials from NSE&apos;s own results filings: <span style={{ color: T.text }}>{faCount.toLocaleString('en-IN')} companies</span>
                {' '}<span role="button" onClick={() => goToPage('screen')} style={{ color: T.cyan, cursor: 'pointer' }}>FUND ›</span></>}
            </div>
            {enriching && enrichProgress && (
              <div style={{ fontSize: 10, color: T.violet, marginTop: 6 }}>
                {enrichProgress.done?.toLocaleString()} / {enrichProgress.total?.toLocaleString()} · {enrichProgress.pct}%
              </div>
            )}
          </Panel>
        )}
      </div>
    </div>
  )
}

// ── Stocks Tab ────────────────────────────────────────────────────────────────
function StocksTab({
  displayStocks, displayCount, isFiltered, filterLoading, technicalFilters,
  allStocksCount, totalStocks, onFilterChange, onRowClick, onLoadMore, isDark = true,
  watchlist = [], onWatchToggle, listError, onRetryList, listLoading = false, latestDate = null,
}: any) {
  const eodSrc = sourceOf(latestDate, { source: 'DuckDB EOD' })   // PLAN §0.5: the screener's as-of on every panel
  // Scoped refresh — updates ONLY the watchlist tickers (not the full universe)
  const [wlBusy, setWlBusy] = useState(false)
  const [wlMsg, setWlMsg]   = useState('')
  const doRefreshWatchlist = async () => {
    if (!watchlist.length || wlBusy) return
    setWlBusy(true); setWlMsg(`Queuing ${watchlist.length}…`)
    try {
      await refreshWatchlist(watchlist)
      const poll = async (n = 0) => {
        try {
          const s = (await getRefreshStatus()).data
          const done = (s.done ?? 0) + (s.current ?? 0)
          if (s.active && n < 40) { setWlMsg(`${done}/${s.total} updated…`); setTimeout(() => poll(n + 1), 1500) }
          else { setWlMsg(`✓ ${done || watchlist.length}/${s.total || watchlist.length} updated`); setWlBusy(false) }
        } catch { setWlMsg('✓ refresh queued'); setWlBusy(false) }
      }
      setTimeout(() => poll(), 1200)
    } catch (e: any) {
      setWlMsg('⚠ ' + (apiError(e, 'refresh failed'))); setWlBusy(false)
    }
  }

  const FILTERS = [
    { key: 't1', label: 'T1', desc: 'Price > 150/200 MA' },
    { key: 't2', label: 'T2', desc: '150 MA > 200 MA' },
    { key: 't3', label: 'T3', desc: '200 MA Uptrend 1M+' },
    { key: 't4', label: 'T4', desc: '50 MA > 150/200 MA' },
    { key: 't5', label: 'T5', desc: 'Price > 50 MA' },
    { key: 't6', label: 'T6', desc: 'Price ≥30% above 52W low' },
    { key: 't7', label: 'T7', desc: 'Price within 25% of 52W high' },
    { key: 't8', label: 'T8', desc: 'RS Rating ≥70' },
  ]

  const toggle = (key: string) => {
    const next = { ...technicalFilters, [key]: !technicalFilters[key] }
    onFilterChange(next)
  }

  const clearAll = () => onFilterChange({ t1: false, t2: false, t3: false, t4: false, t5: false, t6: false, t7: false, t8: false })
  // One click, one screener query (eight separate clicks used to fire eight).
  const selectAll = () => onFilterChange({ t1: true, t2: true, t3: true, t4: true, t5: true, t6: true, t7: true, t8: true })
  const activeCount = Object.values(technicalFilters).filter(Boolean).length
  const allOn = activeCount === FILTERS.length

  return (
    <div>
      <PageHeader code="EQS" title="Stocks"
        subtitle={isFiltered ? `${displayCount} match ${activeCount} Minervini filter${activeCount > 1 ? 's' : ''}`
          : listLoading && !allStocksCount ? 'loading the NSE universe…' : `${allStocksCount.toLocaleString('en-IN')} of ${totalStocks.toLocaleString('en-IN')} NSE stocks`}
        right={activeCount > 0 ? <Btn size="sm" onClick={clearAll}>Clear filters ({activeCount})</Btn> : undefined} />
      <div style={{ display: 'grid', gap: 10 }}>
        <Panel source={eodSrc} badge="heuristic" title="Minervini trend template" subtitle="all active filters must pass · T1+T2 = Stage-2 trend · a trend description, not a tested signal"
          right={<Btn size="sm" variant={allOn ? 'ghost' : 'primary'} onClick={allOn ? clearAll : selectAll}
                   disabled={filterLoading}
                   title={allOn ? 'Turn every filter off' : 'Turn on T1–T8 at once: the full Minervini trend template'}>
                   {allOn ? '□ Clear all' : '■ Select all T1–T8'}
                 </Btn>}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(8, minmax(0, 1fr))', gap: 6 }}>
            {FILTERS.map(({ key, label, desc }) => {
              const on = (technicalFilters as any)[key]
              return (
                <button key={key} onClick={() => toggle(key)}
                  style={{ textAlign: 'left', padding: '8px 10px', cursor: 'pointer', border: `1px solid ${on ? T.amber : T.border}`,
                           background: on ? 'rgba(255,176,0,.12)' : '#080b10', fontFamily: T.mono }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: on ? T.amber : T.text }}>{on ? '■' : '□'} {label}</div>
                  <div style={{ fontSize: 10, color: on ? T.amber : T.muted, marginTop: 3, lineHeight: 1.35 }}>{desc}</div>
                </button>
              )
            })}
          </div>
        </Panel>

        {watchlist.length > 0 && (
          <Panel source={eodSrc} title={`Watchlist (${watchlist.length})`} subtitle="syncs to Backtest & Pipeline" accent={T.cyan}
            right={<>
              {wlMsg && <span style={{ fontSize: 10, color: T.cyan }}>{wlMsg}</span>}
              <Btn size="sm" onClick={doRefreshWatchlist} disabled={wlBusy}>{wlBusy ? 'Refreshing…' : `↻ Refresh ${watchlist.length}`}</Btn>
            </>}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {watchlist.map((t: string) => (
                <Chip key={t} color={T.cyan}>{t}
                  <span onClick={() => onWatchToggle(t)} style={{ color: T.dim, cursor: 'pointer' }} title="Remove">×</span>
                </Chip>
              ))}
            </div>
          </Panel>
        )}

        <Panel source={eodSrc} badge="context" title={isFiltered ? 'Screener results' : 'All stocks'} pad={0}
          subtitle={isFiltered ? `${displayCount} matched` : `${allStocksCount} of ${totalStocks} loaded · click a row for the chart`}
          right={filterLoading ? <span style={{ fontSize: 10, color: T.amber }} className="t-pulse">FILTERING…</span>
            : listLoading ? <span style={{ fontSize: 10, color: T.amber }} className="t-pulse">LOADING…</span> : undefined}>
          {listError && !allStocksCount
            ? <div style={{ padding: 12 }}><ErrorBox error={`stock list unavailable: ${listError} (retrying every 15 s)`} onRetry={onRetryList} /></div>
            : <StockTable stocks={displayStocks} onRowClick={onRowClick} loading={filterLoading || listLoading} isDark={isDark} watchlist={watchlist} onWatchToggle={onWatchToggle} />}
          {!isFiltered && allStocksCount < totalStocks && (
            <div style={{ padding: 12, textAlign: 'center', borderTop: `1px solid ${T.border}` }}>
              <Btn onClick={onLoadMore}>Load more ({totalStocks - allStocksCount} remaining)</Btn>
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}

export default function Home() {
  return (
    <ThemeProvider>
      <AppProvider>
        <ToastProvider>
          <ErrorCatcher />
          {/* R8: desktop saves ('Saved to … · ⌥⌘L' / why it failed) and failed alert saves (P11) as toasts */}
          <DownloadToasts />
          <AlertSaveToasts />
          <WorkspaceSaveToasts />
          <UnknownTabToast tabs={TAB_IDS} />
          <HomeContent />
        </ToastProvider>
      </AppProvider>
    </ThemeProvider>
  )
}

