'use client'

/**
 * GOLD — the gold terminal page (PLAN a.1; the 43rd page). One page for every gold panel: the header strip is the
 * only place live prices appear; the page-global pickers (exchange × family × expiry, unit, window, [B]/[P]) are
 * prefs-synced (`gold.contract.v1`, shared with MCXG; `gold.layer.v1`) and mirrored in the URL
 * (`?tab=gold&sub=health&c=GOLDM&exp=2026-12-04&unit=inr10g&win=W`), so a link reproduces the view.
 *
 * Sub-views load on their own (like BRF panels), each with its own freshness chips: HEALTH · DAILY · WEEKLY ·
 * MONTHLY · CONTRACTS are built here (B4A); POSITIONING · PHYSICAL · MACRO (B4B) and LEARN (B5) are code-split
 * modules of the same contract (ui/lib/gold/types.ts GoldSubViewProps), loaded when their tab is opened; a module that
 * fails to load shows "unavailable", never a blank. Nothing on this page feeds the Decision Desk, the S1 shadow,
 * alerts or a ticket price (PLAN 0.1 #7).
 */
import dynamic from 'next/dynamic'
import { apiError } from '@/lib/errors'
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType } from 'react'
import { Chip, Loading, PageHeader, T, Tabs } from '@/components/terminal'
import { getGoldContracts, getGoldOverview, loadCatalog, loadTooltips } from '@/lib/gold/api'
import { autoExpiry, delayedIfOld, istClock } from '@/lib/gold/format'
import { buildGoldSearch, parseGoldUrl, stripGoldSearch, useGoldContract, useGoldLayer } from '@/lib/gold/prefs'
import { GOLD_SUBS, type CatalogRow, type ContractFamily, type GoldContractSel, type GoldOverview, type GoldSub, type GoldSubViewProps, type Unit, type Window } from '@/lib/gold/types'
import { ContractsView } from './ContractsView'
import { DailyView } from './DailyView'
import { GlossaryPanel } from './GlossaryPanel'
import { HealthView } from './HealthView'
import { HeaderStrip, Pickers } from './HealthStrip'
import { MonthlyView } from './MonthlyView'
import { WeeklyView } from './WeeklyView'
import { LagChipEl } from './kit'

const OVERVIEW_MS = 60_000
const CONTRACTS_MS = 300_000

export const SUB_LABEL: Record<GoldSub, string> = {
  health: 'Health', daily: 'Daily', weekly: 'Weekly', monthly: 'Monthly', positioning: 'Positioning', physical: 'Physical',
  macro: 'Macro', contracts: 'Contracts', learn: 'Learn',
}

function Unavailable({ sub }: { sub: GoldSub }) {
  return (
    <div data-gold-unavailable={sub} style={{ padding: '28px 12px', textAlign: 'center', color: T.muted, border: `1px dashed ${T.border}` }}>
      <div style={{ fontSize: 12, color: T.text, letterSpacing: .8, textTransform: 'uppercase' }}>{SUB_LABEL[sub]} · unavailable</div>
      <div style={{ fontSize: 11, marginTop: 6, lineHeight: 1.6 }}>This sub-view's module did not load; reload the page, or open it from the GO bar (GOLD).</div>
    </div>
  )
}

// Code-split sub-views built by the other gold builders (same props contract); one chunk each, loaded on first open.
const split = (sub: GoldSub, load: () => Promise<ComponentType<GoldSubViewProps> | undefined>) =>
  dynamic<GoldSubViewProps>(
    () => load().then(C => ({ default: C ?? (() => <Unavailable sub={sub} />) })).catch(() => ({ default: () => <Unavailable sub={sub} /> })),
    { loading: () => <Loading label={`loading ${SUB_LABEL[sub]}`} />, ssr: false },
  )
const PositioningView = split('positioning', () => import('./PositioningView').then(m => m.PositioningView))
const PhysicalView = split('physical', () => import('./PhysicalView').then(m => m.PhysicalView))
const MacroView = split('macro', () => import('./MacroView').then(m => m.MacroView))
const LearnView = split('learn', () => import('./LearnView').then(m => m.LearnView))

const VIEWS: Record<GoldSub, ComponentType<GoldSubViewProps>> = {
  health: HealthView, daily: DailyView, weekly: WeeklyView, monthly: MonthlyView, contracts: ContractsView,
  positioning: PositioningView, physical: PhysicalView, macro: MacroView, learn: LearnView,
}

export function GoldPage() {
  // ── page state: URL → state on mount; state → URL on change; prefs for the shared bits ──────────────
  const initial = useMemo(() => (typeof window === 'undefined' ? {} : parseGoldUrl(window.location.search)), [])
  const [sub, setSub] = useState<GoldSub>(initial.sub ?? 'health')
  const [unit, setUnit] = useState<Unit>(initial.unit ?? 'usd_oz')
  // the window defaults to the week: WEI and BRF read /health?window=W, so the verdict words agree across pages
  const [win, setWin] = useState<Window>(initial.window ?? 'W')
  const [stored, updateStored] = useGoldContract()
  const [layer, setLayer] = useGoldLayer()
  // a deep link's `?c=`/`?exp=` is a PAGE-LOCAL override of the synced selection: opening a shared link must not
  // rewrite prefs gold.contract.v1 (and so the MCXG desk's contract) on every window and device. The override ends
  // when the user picks a contract here, which writes the prefs as before.
  const [override, setOverride] = useState<Partial<GoldContractSel> | null>(() =>
    initial.family || initial.expiry ? { ...(initial.family ? { family: initial.family } : {}), ...(initial.expiry ? { expiry: initial.expiry } : {}) } : null)
  const sel = useMemo<GoldContractSel>(() => (override ? { ...stored, ...override } : stored), [stored, override])
  const updateSel = useCallback((patch: Partial<GoldContractSel>) => { setOverride(null); updateStored(patch) }, [updateStored])
  useEffect(() => {
    try {
      const next = buildGoldSearch(window.location.search, { sub, family: sel.family, expiry: sel.expiry, unit, window: win })
      if (next !== window.location.search) window.history.replaceState(window.history.state, '', next)
    } catch { /* history locked */ }
  }, [sub, sel.family, sel.expiry, unit, win])
  useEffect(() => () => {                  // leaving the page: the gold parameters do not follow the next page
    try { window.history.replaceState(window.history.state, '', stripGoldSearch(window.location.search)) } catch { /* ignore */ }
  }, [])

  // ── reference payloads, once per window ───────────────────────────────────────────────────────────
  const [tooltips, setTooltips] = useState<Record<string, string>>({})
  const [catalog, setCatalog] = useState<Record<string, CatalogRow>>({})
  useEffect(() => {
    let alive = true
    loadTooltips().then(t => { if (alive) setTooltips(t) })
    loadCatalog().then(c => { if (alive) setCatalog(c) })
    return () => { alive = false }
  }, [])

  // ── the contract families for the pickers (5 min) ─────────────────────────────────────────────────
  const [families, setFamilies] = useState<ContractFamily[] | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => getGoldContracts(sel.exchange).then(r => { if (alive) setFamilies(r.data?.families ?? []) }).catch(() => { if (alive) setFamilies(f => f ?? []) })
    load()
    const iv = setInterval(load, CONTRACTS_MS)
    return () => { alive = false; clearInterval(iv) }
  }, [sel.exchange])

  // the page's expiry when none is picked (wave 1e minor): the OI front, unless it is in its tender period — then the next
  // month, with the reason on the pickers; the OI front stays selectable. The URL and prefs keep 'front (by OI)'.
  const auto = useMemo(() => autoExpiry(families?.find(f => f.code === sel.family) ?? null), [families, sel.family])
  const pageSel = useMemo<GoldContractSel>(() => (sel.expiry || !auto.expiry ? sel : { ...sel, expiry: auto.expiry }), [sel, auto.expiry])

  // ── the overview (header strip): 60 s, per contract, latest request wins ──────────────────────────
  const [overview, setOverview] = useState<GoldOverview | null>(null)
  const [ovError, setOvError] = useState<string | null>(null)
  const [ovLoading, setOvLoading] = useState(true)
  const ovSeq = useRef(0)
  const loadOverview = useCallback(() => {
    const mine = ++ovSeq.current
    setOvLoading(true)
    getGoldOverview({ contract: pageSel.family, expiry: pageSel.expiry, window: win })
      .then(r => { if (mine === ovSeq.current) { setOverview(r.data); setOvError(null) } })
      .catch((e: unknown) => { if (mine === ovSeq.current) setOvError(apiError(e, 'overview unavailable')) })
      .finally(() => { if (mine === ovSeq.current) setOvLoading(false) })
  }, [pageSel.family, pageSel.expiry, win])
  useEffect(() => {
    loadOverview()
    const iv = setInterval(() => { if (!document.hidden) loadOverview() }, OVERVIEW_MS)
    return () => { ovSeq.current++; clearInterval(iv) }
  }, [loadOverview])

  const comexMatched = overview?.contract.comex_matched ?? null
  const usdinr = overview?.strip.usdinr ?? null
  // ONE fair block per page load (C-TRADER-19 / PLAN §f.6): the overview's health.fair (landed, duty-paid landed, basis,
  // settlement, the live legs) feeds every sub-view, so the same rupee prints on HEALTH, PHYSICAL and CONTRACTS
  const fair = overview?.health?.fair ?? null
  const onNavigate = useCallback((s: GoldSub) => setSub(s), [])
  // the overview's load state (wave 1e, M-A): HEALTH / LEARN render overview.health and read /api/gold/health only once the
  // overview has failed — a page whose strip shows GOLDTEN never prints GOLD's basis in the gauge while the overview loads
  const overviewStatus: GoldSubViewProps['overviewStatus'] = overview ? 'ok' : ovError ? 'error' : 'loading'
  const viewProps: GoldSubViewProps = { sel: pageSel, unit, window: win, layer, comexMatched, usdinr, tooltips, catalog, fair, overview, overviewStatus, onNavigate, onSel: updateSel }
  const View = VIEWS[sub]

  // the live COMEX leg comes from the desk's cache: its freshness is `fair`'s when the strip has no block of its own
  // a leg minutes behind real-time MCX reads DELAYED with its age, never LIVE (wave 1e minor: the Yahoo leg ~10 min behind Breeze)
  const stripFresh = delayedIfOld(overview?.freshness?.strip ?? overview?.freshness?.comex_live ?? overview?.freshness?.fair ?? null)
  return (
    <div data-gold-page data-gold-sub={sub}>
      <PageHeader code="GOLD" title="Gold terminal"
        subtitle={<>spot, COMEX, MCX, positioning (COT), physical, macro, contracts, health check, pre-open fair value
          {overview?.as_of && <span style={{ color: T.dim }}> · {istClock(overview.as_of)}</span>}</>}
        right={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
          {stripFresh !== null && <LagChipEl freshness={stripFresh} />}
          <Chip color={T.muted} title="PAPER ONLY: nothing on this page feeds the Decision Desk, the S1 shadow, an alert or a ticket price (PLAN 0.1 #7)">PAPER · CONTEXT</Chip>
          <Chip color={T.amber} onClick={loadOverview} title="Re-read the header strip now">↻</Chip>
        </span>} />
      <HeaderStrip overview={overview} sel={pageSel} loading={ovLoading} error={ovError} />
      <Pickers sel={sel} onSel={updateSel} families={families} unit={unit} onUnit={setUnit} window={win} onWindow={setWin} layer={layer} onLayer={setLayer}
        comexMatched={comexMatched} autoExpiry={auto} />
      <div style={{ marginBottom: 10 }}>
        <Tabs items={GOLD_SUBS.map(s => ({ id: s, label: SUB_LABEL[s] }))} active={sub} onChange={setSub} />
      </div>
      <div key={sub} data-gold-view={sub}>
        <View {...viewProps} />
      </div>
      <GlossaryPanel />
    </div>
  )
}

export default GoldPage
