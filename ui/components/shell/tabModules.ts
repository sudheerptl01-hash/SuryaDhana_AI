/**
 * Code-split page modules, by page id (C2-performance-02).
 *
 * app/page.tsx renders each page through lazyTab(id, pick), which shows a page directly once its module has
 * resolved and only falls back to the dynamic() Suspense path (TabSkeleton + React's 300 ms reveal throttle)
 * when it has not. Tab switches were already fast (the idle warm-up resolves every module after 3 s), but a new,
 * restored or reloaded window opens straight on its ?tab= page, before any warm-up, and paid the throttle.
 * PlatformShell (in the root layout, so it runs while the boot gate shows) therefore calls preloadTab() for the
 * URL's page (and the stock window when ?sym= is set) and waits for it, bounded, before it reveals the terminal.
 *
 * Every import() here is the same webpack chunk page.tsx used before; the promise is cached per id, so the
 * warm-up, the boot preload and the first render all share one request.
 */
type Mod = Record<string, unknown>
type Loader = () => Promise<Mod>

export const TAB_MODULES: Readonly<Record<string, Loader>> = Object.freeze({
  pipeline: () => import('@/components/PipelineStudio'),
  positions: () => import('@/components/LivePortfolio'),
  backtest: () => import('@/components/BacktestPanel'),
  system: () => import('@/components/SystemTelemetry'),
  scanner: () => import('@/components/LWScanner'),
  explorer: () => import('@/components/DataExplorerTab'),
  warehouse: () => import('@/components/WarehouseHealth'),
  discovery: () => import('@/components/AlphaDiscoveryDesk'),
  commodity: () => import('@/components/CommodityTab'),
  mlengine: () => import('@/components/MLEngineWorkspace'),
  glassbox: () => import('@/components/GlassBoxStudio'),
  broker: () => import('@/components/PortfolioSummary'),
  desk: () => import('@/components/DecisionDesk'),
  markets: () => import('@/components/MarketMonitor'),
  research: () => import('@/components/ResearchLibrary'),
  events: () => import('@/components/EventCalendar'),
  watch: () => import('@/components/WatchMonitor'),
  compare: () => import('@/components/Compare'),
  options: () => import('@/components/OptionChain'),
  insiders: () => import('@/components/InsiderMonitor'),
  deals: () => import('@/components/DealsMonitor'),
  preopen: () => import('@/components/PreOpen'),
  ipo: () => import('@/components/IpoMonitor'),
  movers: () => import('@/components/LiveMovers'),
  wrap: () => import('@/components/DailyWrap'),
  filings: () => import('@/components/CompanyFilings'),
  margin: () => import('@/components/MarginMonitor'),
  screen: () => import('@/components/FundamentalsScreen'),
  alerts: () => import('@/components/AlertsCenter'),
  eco: () => import('@/components/EconomicCalendar'),
  memb: () => import('@/components/IndexMembers'),
  holders: () => import('@/components/OwnershipShifts'),
  world: () => import('@/components/WorldMarkets'),
  stocks: () => import('@/components/StockTable'),
  overview: () => import('@/components/SystemStatusWidget'),
  seag: () => import('@/components/Seasonality'),
  charts: () => import('@/components/ChartStudio'),
  derivatives: () => import('@/components/DerivativesDesk'),
  ostrategy: () => import('@/components/StrategyBuilder'),
  mcxgold: () => import('@/components/McxGoldDesk'),
  gold: () => import('@/components/gold/GoldPage'),
  risk: () => import('@/components/RiskDashboard'),
  /** The stock window (opened over any page; ?sym= deep links). */
  stock: () => import('@/components/StockDetailModal'),
})

const resolved = new Map<string, Mod>()
const inflight = new Map<string, Promise<Mod>>()

/** The module for `id` (shared promise; a failed load is dropped so the next call retries). */
export function loadTabModule(id: string): Promise<Mod> {
  const hit = inflight.get(id)
  if (hit) return hit
  const loader = TAB_MODULES[id]
  if (!loader) return Promise.reject(new Error(`unknown page module: ${id}`))
  const p = loader().then(
    (m) => {
      resolved.set(id, m)
      return m
    },
    (e: unknown) => {
      inflight.delete(id)
      throw e
    },
  )
  inflight.set(id, p)
  return p
}

/** The resolved module for `id`, or null while it has not loaded (synchronous: lazyTab's first render). */
export function resolvedTabModule(id: string): Mod | null {
  return resolved.get(id) ?? null
}

/** Start loading `id` (no-op for pages without a split module, e.g. the brief). Never rejects. */
export function preloadTab(id: string | null | undefined): Promise<void> {
  if (!id || !TAB_MODULES[id]) return Promise.resolve()
  return loadTabModule(id).then(() => undefined, () => undefined)
}

/** Every split page module, for the idle warm-up. */
export function tabModuleIds(): string[] {
  return Object.keys(TAB_MODULES).filter((id) => id !== 'stock')
}
