'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned, sessionDayLabel } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18); the session's day (C1-13)
/**
 * BRIEF (BRF) — the morning one-pager: market regime, your book, this week's events for your stocks, the gold
 * open, the latest news picks and the system's health. Every section loads on its own (a slow source never blanks
 * the page) and links to its full page. Pure aggregation of existing endpoints: nothing here computes a signal.
 */
import { RiskChips } from '@/components/RiskChips'
import { useSurveillance } from '@/lib/useSurveillance'
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  getDashboardSummary, getDeskStatus, getICICIConnectionStatus, getMarketEvents, getMarketMonitor,
  getCrashFilter, getInsiderBuys, getMarketHeadlines, getNewsQuotes, getPreOpen, type PreOpen, getFiiDiiCash, type FiiDiiCash, getOptionChainLive, getSetupStatus, type SetupCheck, getFomc, type FomcMeeting, getRbiMpc, getEcoCalendar, type EcoEvent, getGiftNifty, type GiftNifty, getAnnouncementsCore, type FilingCore, getNewsScan, getOptionChain, getNewsTrackRecord, getOpenPositions, getRecentResults, getResultsReacting, type ReactingResult, getMarketInternals, type MarketInternals, getIndexContribution, type IndexContribution as IndexContributionData, getIndexValuation, type IndexValuationRow, getTelemetryStatus,
  type CrashFilter, type Headline, type InsiderBuy, type OptionChain, type RecentResult,
  type CorpEvent, type MarketMonitor as Monitor, heldSymbols } from '@/lib/api'
import { getGoldHealth } from '@/lib/gold/api'
import { brfLine } from '@/lib/gold/format'
import { setGoldSubInUrl } from '@/lib/gold/prefs'
import type { GoldHealth } from '@/lib/gold/types'
import { useWatchlist } from '@/context/AppContext'
import { CashFlows } from '@/components/ParticipantPositioning'
import { usePins } from '@/lib/pins'
import { daysUntil } from '@/lib/useCorpEvents'
import { IndexIntraday } from '@/components/IndexIntraday'
import { useFinancialsLatest } from '@/lib/useFinancials'
import { ECO_KINDS, ecoWhen } from '@/components/EconomicCalendar'
import { spanNote } from '@/lib/quoteSpan'
import { goToPage } from '@/lib/navigate'
import { briefSessionLine, iciciErrorKind } from '@/components/portfolio/iciciState'
import { openTicker } from '@/lib/openTicker'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { AvoidFlag, Chip, EventBadge, PageHeader, Panel, SourceChip, Stat, T, TickerLink, fmtIdx, fmtInr, fmtPct, ordinal, tone, sourceOf, type SourceInfo } from '@/components/terminal'
import { nseSession } from '@/components/desktop/session'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { liveContribution, nseDelayedSource } from '@/components/liveModel'
import { trackVerdict, type TrackRecordData } from '@/components/news/TrackRecord'

type Load<T> = { data: T | null; error: string | null; loading: boolean }

/**
 * Live program (reports/live_nse, defect D5): a panel line fed by an NSE live feed re-polls while the page is open
 * instead of freezing at the visit's first read. `poll.ms` is the cadence (never faster than the route's own server
 * cache); `sessionOnly` (default) polls only while NSE is open; nothing polls while the window is hidden. A failed
 * re-poll keeps the last data (and records the error) instead of blanking the line.
 */
function useLoad<T>(fn: () => Promise<{ data: T }>, deps: unknown[] = [], poll?: { ms: number; sessionOnly?: boolean }): Load<T> & { reload: () => void } {
  const [s, set] = useState<Load<T>>({ data: null, error: null, loading: true })
  const reload = useCallback(() => {
    set(x => ({ ...x, loading: true }))
    fn().then(r => set({ data: r.data, error: null, loading: false }))
      .catch((e: any) => set({ data: null, error: apiError(e, 'unavailable'), loading: false }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  const refresh = useCallback(() => {
    fn().then(r => set({ data: r.data, error: null, loading: false }))
      .catch((e: any) => set(x => ({ ...x, error: apiError(e, 'unavailable'), loading: false })))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { reload() }, [reload])
  const pollMs = poll?.ms ?? 0, sessionOnly = poll?.sessionOnly !== false
  useEffect(() => {
    if (!pollMs) return
    const iv = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      if (sessionOnly && nseSession(Date.now()).state === 'CLOSED') return
      refresh()
    }, pollMs)
    return () => clearInterval(iv)
  }, [refresh, pollMs, sessionOnly])
  return { ...s, reload }
}

const SCORE_COLOR = [T.red, T.red, T.amber, T.green, T.green]
const SCORE_WORD = ['RISK-OFF', 'DEFENSIVE', 'MIXED', 'CONSTRUCTIVE', 'STRONG']
const pct = (v: number | null | undefined, d = 1) => fmtPct(v, d)

function Go({ code, onGo }: { code: string; onGo: () => void }) {
  return <Chip color={T.amber} onClick={onGo} title={`Open the full ${code} page`}>{code} ›</Chip>
}

function Pending({ s, children }: { s: Load<unknown>; children: ReactNode }) {
  if (s.loading && !s.data) return <div style={{ fontSize: 11, color: T.dim, padding: '6px 0' }}>Loading…</div>
  if (s.error && !s.data) return <div style={{ fontSize: 11, color: T.red, padding: '6px 0' }}>Unavailable: {s.error}</div>
  return <>{children}</>
}

function Line({ k, v, c }: { k: ReactNode; v: ReactNode; c?: string }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '5px 0', borderBottom: `1px solid ${T.border}`, fontSize: 11.5 }}>
      <span style={{ color: T.muted }}>{k}</span><span style={{ color: c ?? T.text, fontFamily: T.mono, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{v}</span>
    </div>
  )
}

// a cue that rounds to zero prints 0.0% in grey
const signTone = (v: number, eps: number) => (Math.abs(v) < eps ? T.muted : v > 0 ? T.green : T.red)

// the pages a trader opens before 09:15 (the rest are in the tab strip or on GO)
const QUICK: [string, string, string][] = [
  ['WEI', 'world', 'World markets: overnight cues'], ['ECO', 'eco', 'Economic calendar: CPI, IIP, GDP, RBI, Fed'], ['PRE', 'preopen', 'Pre-open auction (09:00–09:08)'], ['MOV', 'movers', 'Live movers during the session'], ['CF', 'filings', 'Company filings today'],
  ['OMON', 'options', 'NIFTY option monitor'], ['DEAL', 'deals', 'Block & bulk deals'], ['INSD', 'insiders', 'Insider buying'], ['IPO', 'ipo', 'IPOs: open issues, subscription, listings'],
]

// "What's new" strip: each entry opens the function; dismissing stores the version so the next release shows again
const WHATS_NEW_VERSION = '2026-10-14'
const WHATS_NEW: { code: string; hint: string; go: () => void }[] = [
  { code: '⚑ RISK FLAGS', hint: 'NSE surveillance (ASM / GSM / bands / F&O ban): two of your holdings are flagged', go: () => goToPage('watch') },
  { code: 'MEMB', hint: 'index members: weights, points, returns, P/E', go: () => goToPage('memb') },
  { code: 'SEAG', hint: 'seasonality by calendar month', go: () => goToPage('seag') },
  { code: 'ECO', hint: 'CPI, WPI, IIP, GDP, RBI, Fed dates', go: () => goToPage('eco') },
  { code: 'MKT VALUATION', hint: '14 years of index P/E, P/B, yield, and equity vs bonds', go: () => goToPage('markets') },
  { code: 'TCS HP', hint: 'historical prices, dividends, drawdown', go: () => openTicker('TCS', 'hp') },
  { code: 'OMON PRICER', hint: 'click any option price', go: () => goToPage('options') },
  { code: 'SHORTS', hint: 'DEAL → institutional short selling, market-wide', go: () => goToPage('deals') },
  { code: 'LOG', hint: "everything that changed, and why", go: () => goToPage('research', { research: 'docs/IMPROVEMENT_LOG.md' }) },
]

// the five global cues on the Market panel (full board on WEI)
const GLOBAL: [string, string][] = [['^GSPC', 'S&P'], ['^N225', 'NKY'], ['BZ=F', 'Brent'], ['INR=X', '₹/$']]

export function Brief({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const mon = useLoad<Monitor>(getMarketMonitor)
  const desk = useLoad<any>(getDeskStatus)
  const broker = useLoad<any>(getICICIConnectionStatus)
  // P4: why ICICI is not connected; null when connected (a failed status read counts as unknown: the old wording)
  const brokerKind = broker.data?.connected ? null : (iciciErrorKind(broker.data) ?? 'unknown')
  const holdings = useLoad<any>(getOpenPositions)
  const events = useLoad<{ rows: CorpEvent[] }>(() => getMarketEvents())
  // the gold open, as ONE line from /api/gold/health (60 s cache in ui-api, no Breeze on the path; gold program PLAN §b)
  const goldHealth = useLoad<GoldHealth>(() => getGoldHealth('W'))
  const scan = useLoad<any>(() => getNewsScan('latest'))
  const track = useLoad<TrackRecordData>(getNewsTrackRecord)
  const tele = useLoad<any>(getTelemetryStatus)
  const dash = useLoad<any>(getDashboardSummary)
  const crash = useLoad<CrashFilter>(getCrashFilter)
  const reported = useLoad<{ rows: RecentResult[] }>(() => getRecentResults(5))
  // live program (D5): the NSE-fed lines re-poll in session at their server caches' pace, not once per visit
  const internals = useLoad<MarketInternals>(() => getMarketInternals(), [], { ms: 120_000 })
  const contrib = useLoad<IndexContributionData>(() => getIndexContribution('NIFTY 50'), [], { ms: 120_000 })
  const valuation = useLoad<{ timestamp?: string; indices: Record<string, IndexValuationRow>; vs_history?: Record<string, { pctl: number; since: string }>; rel_history?: Record<string, { ratio: number; pctl: number; median: number }> }>(() => getIndexValuation(), [], { ms: 60_000 })
  const reacting = useLoad<{ rows: ReactingResult[]; since: string; phase?: string }>(() => getResultsReacting(), [], { ms: 120_000 })
  // live chain during the session (falls back to the last close), end of day otherwise
  const opt = useLoad<OptionChain>(() => {
    const d = new Date(), m = d.getHours() * 60 + d.getMinutes()
    return d.getDay() >= 1 && d.getDay() <= 5 && m >= 555 && m <= 935 ? getOptionChainLive('NIFTY').catch(() => getOptionChain('NIFTY')) : getOptionChain('NIFTY')
  }, [], { ms: 60_000 })
  const heads = useLoad<{ headlines: Headline[] }>(getMarketHeadlines)
  const insiders = useLoad<{ rows: InsiderBuy[] }>(() => getInsiderBuys(7, 1e7))
  // non-NSE cues (S&P, Nikkei, Brent, ₹/$) through the app's one quotes fetcher (its SWR cache), re-read every 2 min
  const world = useLoad<{ quotes: Record<string, { available: boolean; change_pct?: number; price?: number; prev_date?: string | null; market_date?: string | null }> }>(() => getNewsQuotes(GLOBAL.map(g => g[0])), [], { ms: 120_000, sessionOnly: false })
  const pre = useLoad<PreOpen>(() => getPreOpen('FO'))
  const setup = useLoad<{ checks: SetupCheck[] }>(getSetupStatus)
  const fed = useLoad<{ next: FomcMeeting | null }>(getFomc)
  const rbi = useLoad<{ next: { end: string } | null }>(getRbiMpc)
  const [showNew, setShowNew] = useState(false)
  useEffect(() => { try { setShowNew(localStorage.getItem('suryadhana.whatsnew') !== WHATS_NEW_VERSION) } catch { setShowNew(true) } }, [])
  // dismissed in another window (or on another device, via sync): hide it here too (C3-02)
  useExternalPrefChange('suryadhana.whatsnew', () => {
    try { setShowNew(localStorage.getItem('suryadhana.whatsnew') !== WHATS_NEW_VERSION) } catch { /* keep */ }
  })
  const eco = useLoad<{ today: string; events: EcoEvent[] }>(() => getEcoCalendar(0, 7))
  const gift = useLoad<GiftNifty>(getGiftNifty, [], { ms: 60_000, sessionOnly: false })
  const filings = useLoad<{ items: FilingCore[] }>(() => getAnnouncementsCore())
  // today's move on ICICI holdings: live NSE quotes (Breeze websocket → NSE ≈ 1 min → the last close); the broker's
  // holdings call has no previous close. The old 120 s quotes call runs only while the live service does not answer.
  const holdSyms = heldSymbols(holdings.data).sort().join(',')
  const liveBook = useLiveQuotes(holdSyms ? holdSyms.split(',') : [], { intervalMs: 5_000 })
  const [holdDayOld, setHoldDay] = useState<Record<string, number>>({})
  const [holdPxOld, setHoldPx] = useState<Record<string, number>>({})
  const { holdDay, holdPx } = useMemo(() => {
    if (!liveBook.available) return { holdDay: holdDayOld, holdPx: holdPxOld }
    const day: Record<string, number> = {}, px: Record<string, number> = {}
    for (const [k, q] of Object.entries(liveBook.quotes)) {
      if (q.price != null) px[k] = q.price
      if (q.price != null && q.change_pct != null) day[k] = q.change_pct
    }
    return { holdDay: day, holdPx: px }
  }, [liveBook.available, liveBook.quotes, holdDayOld, holdPxOld])
  const bookChip = liveBook.available && liveBook.source ? <SourceChip info={liveBook.source} style={{ marginLeft: 6 }} /> : null
  useEffect(() => {
    if (!holdSyms || liveBook.available) return
    const get = () => getNewsQuotes(holdSyms.split(',').map(x => `${x}.NS`)).then(r => {
      const o: Record<string, number> = {}, px: Record<string, number> = {}
      for (const x of holdSyms.split(',')) {
        const v = r.data.quotes[`${x}.NS`]
        if (v?.available && v.change_pct != null) o[x] = v.change_pct
        if (v?.available && v.price != null) px[x] = v.price
      }
      setHoldDay(o); setHoldPx(px)
    }).catch(() => {})
    get(); const iv = setInterval(get, 120_000); return () => clearInterval(iv)
  }, [holdSyms, liveBook.available])
  const [setupOpen, setSetupOpen] = useState(false)
  const cash = useLoad<FiiDiiCash>(() => getFiiDiiCash(30))
  // who moved NIFTY on live rows (the weights from the 2-min payload; liveModel.ts) and the Market today panel's own chip
  const contribSyms = useMemo(() => (contrib.data ? [contrib.data.index, ...contrib.data.members.map(x => x.symbol)] : []), [contrib.data])
  const contribLive = useLiveQuotes(contribSyms, { intervalMs: 5_000 })
  const liveContrib = useMemo(() => (contrib.data ? liveContribution(contrib.data, contribLive.quotes) : null), [contrib.data, contribLive.quotes])
  const [todaySrc, setTodaySrc] = useState<SourceInfo | null>(null)
  const { watchlist } = useWatchlist()
  const { pins } = usePins()
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const iv = setInterval(() => setNow(new Date()), 30_000); return () => clearInterval(iv) }, [])

  const mine = useMemo(() => {
    const s = new Set<string>()
    for (const sym of heldSymbols(holdings.data)) s.add(sym)
    for (const p of desk.data?.positions ?? []) s.add(String(p.symbol).toUpperCase())
    for (const w of watchlist) s.add(w.toUpperCase().replace(/\.NS$/, ''))
    for (const p of Object.values(pins)) if (p.pick.symbol?.region === 'IN') s.add(p.pick.symbol.base.toUpperCase())
    return s
  }, [holdings.data, desk.data, watchlist, pins])

  const week = useMemo(() => {
    const rows = (events.data?.rows ?? []).filter(e => { const d = daysUntil(e.event_date); return d >= 0 && d <= 7 })
    return {
      mine: rows.filter(e => mine.has(e.symbol)),
      big: rows.filter(e => !mine.has(e.symbol) && (e.turnover_cr ?? 0) >= 100).slice(0, 10),
      total: rows.length,
    }
  }, [events.data, mine])

  // last quarter of the big names reporting this week (FA cache only: no reads queued from BRIEF)
  const { fin: bigFin } = useFinancialsLatest(week.big.map(e => e.symbol), { prefetch: false })
  // NSE surveillance flags (ASM / GSM / bands / F&O ban) for your holdings: live ICICI book or the last known one
  const risk = useSurveillance([...(holdings.data?.positions ?? []), ...(holdings.data?.last_known?.positions ?? [])]
    .map((p: { symbol?: string }) => String(p.symbol ?? '')).filter(Boolean))
  // 24-hour IST, like the strip clock next to it (CT-13: was '04:03 pm')
  const ist = now.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'long', day: '2-digit', month: 'long', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
  const istHM = Number(now.toLocaleString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }).replace(':', ''))
  const istDay = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' })).getDay()
  // NSE holidays (ECO, from NSE's holiday master): today's status and the next real session
  const todayIso = now.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
  const hol = new Map((eco.data?.events ?? []).filter(e => e.kind === 'HOLIDAY').map(e => [e.date, e.what.split(' · ').pop() ?? 'holiday']))
  const nextSession = (() => {
    const d = new Date(`${todayIso}T12:00:00`)
    for (let i = 0; i < 10; i++) {
      d.setDate(d.getDate() + 1)
      const iso = d.toLocaleDateString('en-CA')
      if (d.getDay() !== 0 && d.getDay() !== 6 && !hol.has(iso)) return d
    }
    return null
  })()
  const fmtSession = (d: Date | null) => d ? d.toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' }) : '—'
  const tomorrowIso = (() => { const d = new Date(`${todayIso}T12:00:00`); d.setDate(d.getDate() + 1); return d.toLocaleDateString('en-CA') })()
  const session = hol.has(todayIso) ? `NSE closed today (${hol.get(todayIso)}) · next session ${fmtSession(nextSession)}`
    : istDay === 0 || istDay === 6 ? `NSE closed (weekend) · next session ${fmtSession(nextSession)}`
    : istHM < 915 ? 'NSE opens 09:15 IST' : istHM < 1530 ? 'NSE open · closes 15:30 IST'
    : (mon.data?.as_of === todayIso ? "NSE closed · today's end-of-day data is in · wrap at 21:00" : 'NSE closed · end-of-day data after ~18:30 IST')
      + (hol.has(tomorrowIso) ? ` · tomorrow is a holiday (${hol.get(tomorrowIso)}): next session ${fmtSession(nextSession)}` : '')

  const m = mon.data, b = m?.breadth
  const d = desk.data, start = d?.meta?.start_capital, nav = d?.latest?.nav
  const ret = start && nav ? (nav / start - 1) * 100 : null
  const navs = d?.nav ?? []
  const niftyRet = navs.length > 1 && navs[0].nifty ? (navs[navs.length - 1].nifty / navs[0].nifty - 1) * 100 : null
  const plan = d?.plans?.[0]
  const hold = holdings.data?.positions ?? []
  const pnl = hold.reduce((a: number, p: any) => a + (p.pnl ?? 0), 0)
  const invested = hold.reduce((a: number, p: any) => a + (p.invested ?? 0), 0)
  const picks = [...(scan.data?.picks ?? [])].sort((a: any, z: any) => (z.conviction_score ?? 0) - (a.conviction_score ?? 0))
  const jobs = [...(tele.data?.scheduler?.jobs ?? [])].sort((a: any, z: any) => (a.next_run_unix ?? 9e12) - (z.next_run_unix ?? 9e12)).slice(0, 6)

  // the gold open in one line (before 09:00 the fair open and the chase verdict; after the captured open this morning's
  // call; on MCX holidays the closure), linking to the GOLD page — the pre-open desk itself lives on GOLD › HEALTH
  // the server's `brf_line` (lines.brf) verbatim — the morning call from the 08:45 snapshot, never a client rule; the
  // client fallback composes the same forms only when the payload has none. Colour (PLAN §f.3): only the OK / WAIT
  // token and the arithmetic miss; the verdict words stay in the neutral token
  const goldLine = brfLine(goldHealth.data, Math.floor(istHM / 100) * 60 + (istHM % 100))
  const goldToneColor = (t: string) => (t === 'green' ? T.green : t === 'red' ? T.red : t === 'amber' ? T.amber : T.muted)

  return (
    <div>
      <PageHeader code="BRF" title={istDay >= 1 && istDay <= 5 && istHM >= 915 && istHM < 1530 ? "Session Brief" : istHM >= 1530 ? "Evening Brief" : istHM < 400 ? "Overnight Brief" : "Morning Brief"} subtitle={`${ist} IST · ${session}`}
        right={<div style={{ display: 'flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <span style={{ fontSize: 10, color: T.dim, marginRight: 2 }}>MORNING PAGES</span>
          {QUICK.map(([code, tab, hint]) => <Chip key={code} color={T.cyan} title={hint} onClick={() => onNavigate(tab)}>{code}</Chip>)}
          <span style={{ width: 8 }} />
          <Chip color={T.amber} onClick={() => { mon.reload(); internals.reload(); reacting.reload(); desk.reload(); crash.reload(); reported.reload(); opt.reload(); heads.reload(); insiders.reload(); world.reload(); gift.reload(); filings.reload(); pre.reload(); cash.reload(); setup.reload(); broker.reload(); holdings.reload(); events.reload(); goldHealth.reload(); scan.reload(); track.reload(); tele.reload(); dash.reload() }}>↻ REFRESH ALL</Chip>
        </div>} />

      {showNew && (
        <div style={{ border: `1px solid ${T.cyan}55`, background: '#06101a', padding: '6px 12px', marginBottom: 8, fontSize: 11.5,
                      display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontFamily: T.display, fontSize: 10.5, letterSpacing: 1.4, color: T.cyan }}>NEW SINCE YOUR LAST VISIT</span>
          {WHATS_NEW.map(w => <Chip key={w.code} color={T.cyan} title={w.hint} onClick={w.go}>{w.code}</Chip>)}
          <span role="button" title="hide until the next release" onClick={() => { setShowNew(false); try { localStorage.setItem('suryadhana.whatsnew', WHATS_NEW_VERSION) } catch { /* private window */ } }}
            style={{ marginLeft: 'auto', color: T.dim, cursor: 'pointer', fontSize: 10.5 }}>✕ GOT IT</span>
        </div>)}
      {(() => {
        // owner-only setup items: shown until done (Desk industry gaps come from the Desk's own watchlist)
        const unknown = (desk.data?.plans?.[0]?.summary?.watchlist ?? []).filter((w: any) => w.sector === 'Unknown').map((w: any) => w.symbol)
        const items: SetupCheck[] = [...(setup.data?.checks ?? []).filter(c => !c.ok),
          ...(unknown.length ? [{ key: 'desk_industry', ok: false, title: 'Desk industry cap',
              detail: `${unknown.length} of the Desk's top 20 have no NSE industry (${unknown.join(', ')}), so the 40% cap cannot count them`,
              fix: 'Approve or edit the proposed map in docs/IMPROVEMENT_LOG.md (Recommendations)' }] : [])]
        if (!items.length) return null
        return (
          <div style={{ border: `1px solid ${T.amber}66`, background: '#120e04', padding: '8px 12px', marginBottom: 12, fontSize: 11.5 }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ fontFamily: T.display, fontSize: 10.5, letterSpacing: 1.4, color: T.amber }}>NEEDS YOU · {items.length}</span>
              {items.map(c => <span key={c.key} style={{ color: T.text }}>⚠ {c.title}</span>)}
              <span role="button" onClick={() => setSetupOpen(o => !o)} style={{ color: T.cyan, cursor: 'pointer', marginLeft: 'auto', fontSize: 10.5 }}>{setupOpen ? 'HIDE' : 'HOW TO FIX ›'}</span>
            </div>
            {setupOpen && items.map(c => (
              <div key={c.key} style={{ marginTop: 6, paddingTop: 6, borderTop: `1px solid ${T.border}` }}>
                <div style={{ color: T.text }}><b>{c.title}</b> <span style={{ color: T.muted }}>· {c.detail}</span></div>
                {c.fix && <div style={{ color: T.dim, fontFamily: T.mono, fontSize: 10.5, marginTop: 2 }}>fix: {c.fix}</div>}
              </div>))}
          </div>
        )
      })()}
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(440px, 1fr))', alignItems: 'start' }}>
        {/* ── market ─────────────────────────────────────────────── */}
        <Panel source={sourceOf(m?.as_of ?? null, { source: 'NSE EOD' })} badge="context" title="Market" subtitle={m ? `NSE EOD ${m.as_of} · ${m.index_name}` : 'NSE breadth'} accent={T.amber}
          right={<Go code="MKT" onGo={() => onNavigate('markets')} />}>
          <Pending s={mon}>
            {m && b && <>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px 10px', marginBottom: 8, flexWrap: 'wrap' }}>
                <span style={{ fontFamily: T.mono, fontSize: 30, fontWeight: 700, color: SCORE_COLOR[m.regime.score] }}>{m.regime.score}/4</span>
                <span style={{ fontFamily: T.display, fontSize: 15, fontWeight: 700, letterSpacing: 1.4, color: SCORE_COLOR[m.regime.score], whiteSpace: 'nowrap' }}>{SCORE_WORD[m.regime.score]}</span>
                <span style={{ fontSize: 11, color: T.muted }}>exposure guide {m.regime.exposure} · {m.regime.days_at_score} sessions at this score</span>
              </div>
              <Line k={`${m.index_name}`} v={<>{fmtIdx(b.index)} <span style={{ color: tone(b.index_chg_pct) }}>{pct(b.index_chg_pct, 2)}</span></>} />
              <Line k="Above 50-DMA / 200-DMA" v={`${b.pct_above50?.toFixed(0)}% / ${b.pct_above200?.toFixed(0)}%`} c={(b.pct_above50 ?? 0) >= 50 ? T.green : T.red} />
              <Line k="Advances / declines" v={`${b.adv} / ${b.dec}`} c={tone((b.adv ?? 0) - (b.dec ?? 0))} />
              <Line k="New highs / lows" v={`${b.new_highs} / ${b.new_lows}`} c={tone((b.new_highs ?? 0) - (b.new_lows ?? 0))} />
              <Line k="Distribution days (25)" v={b.dist_days_25} c={(b.dist_days_25 ?? 0) <= 4 ? T.green : T.red} />
              <Line k="India VIX" v={`${b.vix?.toFixed(2)} · ${ordinal(b.vix_pct)} pct`} c={T.text} />
              {(() => { const v = valuation.data?.indices?.['NIFTY 50'], mid = valuation.data?.indices?.['NIFTY MIDCAP 150'], sm = valuation.data?.indices?.['NIFTY SMALLCAP 250']
                  if (!v?.pe) return null
                  return <Line k={<span style={{ whiteSpace: 'nowrap' }}>Valuation (NSE) <span role="button" onClick={() => onNavigate('markets')} style={{ color: T.cyan, cursor: 'pointer', fontSize: 10 }}>MKT ›</span></span>}
                    v={<span>NIFTY P/E <span style={{ color: T.amber }}>{v.pe.toFixed(1)}×</span>
                      {valuation.data?.vs_history?.['NIFTY 50'] && <span style={{ color: T.dim }}> ({ordinal(valuation.data.vs_history['NIFTY 50'].pctl)} percentile since {valuation.data.vs_history['NIFTY 50'].since.slice(0, 4)})</span>}
                      <span style={{ color: T.dim }}> · P/B {v.pb?.toFixed(1)} · yield {v.dy?.toFixed(1)}%</span>
                      {mid?.pe && <span style={{ color: T.dim }}> · mid {mid.pe.toFixed(0)}× · small {sm?.pe?.toFixed(0)}×</span>}
                      {(() => { const r = valuation.data?.rel_history?.['NIFTY SMALLCAP 250']
                        return r && r.pctl >= 80 ? <span style={{ color: T.amber }} title={`Smallcap 250 P/E ÷ NIFTY 50 P/E; median since 2021 ${r.median}×`}> (small-cap premium {r.ratio}× NIFTY, {ordinal(r.pctl)} pct)</span> : null })()}</span>} /> })()}
              {world.data && (
                <Line k={<span style={{ whiteSpace: 'nowrap' }}>Global cues <span role="button" onClick={() => onNavigate('world')} style={{ color: T.cyan, cursor: 'pointer', fontSize: 10 }}>WEI ›</span></span>}
                      v={<span style={{ fontSize: 11 }}>{gift.data?.implied_gap_pct != null && (
                        <span title={`GIFT NIFTY ${gift.data.last?.toLocaleString('en-IN')} at ${gift.data.time}: the gap it implies for the NIFTY open`}
                              style={{ whiteSpace: 'nowrap' }}><span style={{ color: T.amber }}>GIFT</span> <span style={{ color: signTone(gift.data.implied_gap_pct, 0.05) }}>{fmtPct(gift.data.implied_gap_pct, 2)}</span></span>)}
                        {GLOBAL.map(([sym, label]) => {
                        const v = world.data!.quotes[sym]
                        return v?.available && v.change_pct != null
                          ? <span key={sym} style={{ marginLeft: 7, whiteSpace: 'nowrap' }} title={spanNote(v) ? `change ${spanNote(v)} (holiday or a session the source skipped)` : undefined}>
                              <span style={{ color: T.dim }}>{label}</span> <span style={{ color: signTone(v.change_pct, 0.05) }}>{fmtPct(v.change_pct, 1)}</span>
                              {spanNote(v) && <span style={{ color: T.dim, fontSize: 9.5 }}> {spanNote(v)!.replace('since ', '·')}</span>}</span>
                          : null
                      })}{fed.data?.next && (() => {
                        const d = Math.round((new Date(`${fed.data!.next!.end}T00:00:00`).getTime() - new Date(now.toDateString()).getTime()) / 86_400_000)
                        return d <= 14 ? <span style={{ marginLeft: 7, whiteSpace: 'nowrap', color: d <= 2 ? T.amber : T.dim }}>Fed {d === 0 ? 'today' : d === 1 ? 'tmrw' : `in ${d}d`}</span> : null
                      })()}{rbi.data?.next && (() => {
                        const d = Math.round((new Date(`${rbi.data!.next!.end}T00:00:00`).getTime() - new Date(now.toDateString()).getTime()) / 86_400_000)
                        return d <= 14 ? <span style={{ marginLeft: 7, whiteSpace: 'nowrap', color: d <= 2 ? T.amber : T.dim }}>RBI {d === 0 ? 'today' : d === 1 ? 'tmrw' : `in ${d}d`}</span> : null
                      })()}</span>} />
              )}
              {(() => {   // India data releases in the next 7 days (RBI and Fed already sit on the Global cues line)
                const evs = (eco.data?.events ?? []).filter(e => e.country === 'IN' && e.kind !== 'RBI')
                return evs.length > 0 && (
                  <Line k={<span style={{ whiteSpace: 'nowrap' }}>Data this week <span role="button" onClick={() => onNavigate('eco')} style={{ color: T.cyan, cursor: 'pointer', fontSize: 10 }}>ECO ›</span></span>}
                    v={<span>{evs.slice(0, 3).map((e, i) => {
                      const when = ecoWhen(e.date, eco.data!.today).replace('tomorrow', 'tmrw').replace(/^in (\d+) days$/, 'in $1d')
                      return <span key={`${e.kind}${e.date}`} style={{ whiteSpace: 'nowrap' }} title={`${e.what} · ${e.date} ${e.time ?? ''} IST`}>{i > 0 && <span style={{ color: T.dim }}> · </span>}
                        <span style={{ color: ECO_KINDS[e.kind]?.color ?? T.muted }}>{ECO_KINDS[e.kind]?.label ?? e.kind}</span>
                        <span style={{ color: T.dim }}> {(e.what.split(' · ')[1] ?? '').replace(/ 20\d\d$/, '')}</span>
                        <span style={{ color: e.date <= eco.data!.today ? T.amber : T.muted }}> {when}{i === 0 && e.time ? ` ${e.time}` : ''}</span></span> })}</span>} />)
              })()}
              {cash.data?.summary.latest_date && (
                <Line k={<span style={{ whiteSpace: 'nowrap' }}>FII / DII cash</span>} v={<CashFlows cash={cash.data} compact />} />
              )}
              {pre.data && pre.data.rows.length > 0 && (() => {
                // NSE stamps '09-Oct-2026 09:09:49'; en-GB month names ('Sept') don't always match, so parse instead
                const today = new Date((pre.data.timestamp ?? '').slice(0, 11).replace(/-/g, ' ')).toDateString() === now.toDateString()
                const gaps = pre.data.rows.filter(r => r.change_pct != null && (r.value ?? 0) >= 1e6).sort((a, b) => b.change_pct! - a.change_pct!)
                // the biggest gap each way: the line has to fit the panel width
                const big = [gaps[0], gaps[gaps.length - 1]].filter(r => r && Math.abs(r.change_pct!) >= 1)
                return (
                  <Line k={<span style={{ whiteSpace: 'nowrap' }}>Pre-open F&O <span role="button" onClick={() => onNavigate('preopen')} style={{ color: T.cyan, cursor: 'pointer', fontSize: 10 }}>PRE ›</span></span>}
                        v={<span style={{ fontSize: 11 }}>
                          {!today && <span style={{ color: T.dim }}>last session · </span>}
                          <span style={{ color: T.green }}>{pre.data.advances}</span>/<span style={{ color: T.red }}>{pre.data.declines}</span>
                          {big.map(r => <span key={r.symbol} style={{ marginLeft: 7, whiteSpace: 'nowrap' }}><span style={{ color: T.dim }}>{r.symbol}</span> <span style={{ color: r.change_pct! >= 0 ? T.green : T.red }}>{fmtSigned(r.change_pct!, 1)}%</span></span>)}
                        </span>} />
                )
              })()}
              {opt.data && (
                <Line k={<span>NIFTY options{opt.data.live
                        ? <SourceChip info={nseDelayedSource(opt.data.as_of ?? null, { marketOpen: true, now: now.getTime(), hint: 'NSE option chain (v3), refreshed by NSE about once a minute' })} style={{ marginLeft: 5, fontSize: 8.5 }} />
                        : <span style={{ color: T.dim, fontSize: 9.5 }}> · F&O EOD {opt.data.date}</span>} <span role="button" onClick={() => onNavigate('options')} style={{ color: T.cyan, cursor: 'pointer', fontSize: 10 }}>OMON ›</span></span>}
                      v={<span>±{opt.data.expected_move_pct}% by {new Date(`${opt.data.expiry}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })}
                        <span style={{ color: T.dim }}> · PCR {opt.data.pcr_oi} · walls </span>
                        <span style={{ color: T.red }}>{opt.data.resistance[0]?.toLocaleString('en-IN')}</span>/<span style={{ color: T.green }}>{opt.data.support[0]?.toLocaleString('en-IN')}</span></span>} />
              )}
              <div style={{ fontSize: 10.5, color: T.muted, marginTop: 8 }}>
                {(() => {   // industries over the last month: best three and worst three (both can be negative in a falling market)
                  const ranked = [...m.sectors].filter(s => s.ret_21d_pct != null).sort((a, z) => z.ret_21d_pct! - a.ret_21d_pct!)
                  const item = (s: (typeof ranked)[number]) => <span key={s.industry} style={{ whiteSpace: 'nowrap' }}>{s.industry} <span style={{ color: tone(s.ret_21d_pct) }}>{pct(s.ret_21d_pct)}</span></span>
                  const join = (xs: typeof ranked) => xs.map((s, i) => <span key={s.industry}>{i ? ' · ' : ''}{item(s)}</span>)
                  return <>Industries, 1 month · best: {join(ranked.slice(0, 3))}<br />worst: {join(ranked.slice(-3).reverse())}</>
                })()}
              </div>
            </>}
          </Pending>
        </Panel>

        {/* ── your book ──────────────────────────────────────────── */}
        <Panel source={sourceOf(desk.data?.latest?.date ?? null, { source: 'Desk ledger + ICICI' })} title="Your book" subtitle="Decision Desk (paper) · ICICI account" accent={T.green}
          right={<div style={{ display: 'flex', gap: 4 }}><Go code="DESK" onGo={() => onNavigate('desk')} /><Go code="BRKR" onGo={() => onNavigate('broker')} /></div>}>
          <Pending s={desk}>
            {d && <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8, marginBottom: 8 }}>
                <Stat big={false} label="Desk value" value={fmtInr(nav)} sub={`start ${fmtInr(start)}`} />
                <Stat big={false} label="Desk return" value={pct(ret, 2)} color={tone(ret)} sub={`NIFTY ${pct(niftyRet, 2)} same period`} />
                <Stat big={false} label="Positions" value={d.positions?.length ?? 0} sub={`drawdown ${pct((d.latest?.drawdown ?? 0) * 100, 1)}`} />
              </div>
              {crash.data && (
                <div style={{ border: `1px solid ${crash.data.risk_on ? T.green : T.amber}55`, background: crash.data.risk_on ? '#06140e' : '#120e04',
                              padding: '7px 10px', margin: '2px 0 6px', fontSize: 11.5, lineHeight: 1.6 }}>
                  <span style={{ color: crash.data.risk_on ? T.green : T.amber, fontWeight: 700, letterSpacing: 1 }}>
                    {crash.data.risk_on ? 'CRASH FILTER OFF · INVESTED' : 'CRASH FILTER ON · IN THE LIQUID FUND'}
                  </span>
                  <div style={{ color: T.text }}>
                    NIFTY {fmtIdx(crash.data.nifty)} vs 200-DMA {fmtIdx(crash.data.sma200)}
                    {' '}(<span style={{ color: crash.data.risk_on ? T.green : T.red }}>{fmtSigned(crash.data.gap_pct, 1)}%</span>)
                    {!crash.data.risk_on && <> · needs <b style={{ color: T.amber }}>+{crash.data.move_needed_pct.toFixed(1)}%</b> to turn risk-on · {crash.data.sessions_below} sessions below</>}
                  </div>
                  <div style={{ color: T.muted, fontSize: 10.5 }}>
                    Next monthly signal: close of {new Date(`${crash.data.next_signal_date}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' })} (last weekday of the month; a holiday moves it a day earlier) · orders at the next open
                  </div>
                </div>
              )}
              {plan && <Line k={`Plan ${plan.cycle ?? ''}`} v={`${plan.status} · signal ${plan.summary?.signal_date ?? plan.signal_date ?? '—'} · ${plan.orders?.length ?? 0} orders`} />}
            </>}
          </Pending>
          <div style={{ marginTop: 6 }}>
            {broker.data?.connected
              ? <Pending s={holdings}>
                  <Line k={<span>ICICI holdings ({hold.length}){bookChip}</span>} v={<>{fmtInr(invested)} invested · <span style={{ color: tone(pnl) }}>{pnl >= 0 ? '+' : '−'}{fmtInr(Math.abs(pnl))}</span>
                    {(() => {   // rupee move today: value × chg ÷ (1 + chg) on each holding with a quote
                      const day = hold.reduce((a: number, p: any) => { const c = holdDay[String(p.symbol).toUpperCase()]; return c == null ? a : a + Number(p.current_value ?? 0) * (c / 100) / (1 + c / 100) }, 0)
                      return Object.keys(holdDay).length ? <span style={{ color: tone(day), marginLeft: 8 }}>· today {day >= 0 ? '+' : '−'}{fmtInr(Math.abs(day))}</span> : null
                    })()}</>} />
                  {hold.slice(0, 5).map((p: any) => (
                    <Line key={p.symbol} k={<TickerLink symbol={p.symbol} />} v={<span>
                      {holdDay[String(p.symbol).toUpperCase()] != null && <span style={{ color: tone(holdDay[String(p.symbol).toUpperCase()]), marginRight: 10, fontSize: 10.5 }}>
                        today {pct(holdDay[String(p.symbol).toUpperCase()])}</span>}
                      <span style={{ color: tone(p.pnl_percent) }}>{pct(p.pnl_percent)}</span></span>} />
                  ))}
                </Pending>
              : <>
                  <Line k="ICICI" v={broker.loading ? 'checking…' : holdings.data?.last_known
                    ? `${brokerKind === 'network' ? 'unreachable (network)' : 'not connected'} · last known ${holdings.data.last_known.positions.length} holdings (${String(holdings.data.last_known.as_of).slice(5, 16).replace('T', ' ')})${brokerKind === 'network' ? '' : ' · log in on Broker'}`
                    : brokerKind === 'network' ? 'unreachable (network): holdings hidden, session may still be valid' : 'not connected: holdings hidden'} c={broker.loading ? T.dim : T.amber} />
                  {(() => {   // last-known quantities priced live (Yahoo): what the book is doing while ICICI is logged out
                    const lk = (holdings.data?.last_known?.positions ?? []) as { symbol: string; quantity: number; buy_price: number }[]
                    const rows = lk.map(p => {
                      const sym = String(p.symbol).toUpperCase(), px = holdPx[sym], c = holdDay[sym]
                      const value = px != null ? px * p.quantity : null
                      return { sym, value, cost: p.buy_price * p.quantity, chg: c,
                               pnl: value != null ? value - p.buy_price * p.quantity : null,
                               day: value != null && c != null ? value * (c / 100) / (1 + c / 100) : null }
                    })
                    const priced = rows.filter(r => r.value != null)
                    if (!priced.length) return null
                    const tot = (k: 'value' | 'cost' | 'pnl' | 'day') => priced.reduce((a, r) => a + (r[k] ?? 0), 0)
                    const pnlT = tot('pnl'), dayT = tot('day')
                    return <>
                      <Line k={<span>Last-known book {bookChip ?? <span style={{ color: T.dim, fontSize: 10 }}>· Yahoo prices (live NSE service not answering)</span>}</span>}
                            v={<>{fmtInr(tot('value'))} · <span style={{ color: tone(pnlT) }}>{pnlT >= 0 ? '+' : '−'}{fmtInr(Math.abs(pnlT))} ({pct(pnlT / tot('cost') * 100)})</span>
                              <span style={{ color: tone(dayT), marginLeft: 8 }}>· today {dayT >= 0 ? '+' : '−'}{fmtInr(Math.abs(dayT))}</span></>} />
                      {(() => {   // concentration: the largest holding and the effective number of holdings (1 / Σ w²)
                        const vals = priced.map(r => ({ sym: r.sym, v: r.value! })).sort((a, b) => b.v - a.v)
                        const tot = vals.reduce((a, x) => a + x.v, 0)
                        if (vals.length < 2 || tot <= 0) return null
                        const eff = 1 / vals.reduce((a, x) => a + (x.v / tot) ** 2, 0), top = vals[0].v / tot
                        return <Line k="Concentration" c={top > 0.4 ? T.red : top > 0.25 ? T.amber : T.muted}
                          v={<span title="WTCH → Your book · X-ray">{vals[0].sym} {(top * 100).toFixed(0)}% of the book · behaves like {eff.toFixed(1)} equal positions</span>} />
                      })()}
                      {rows.map(r => (
                        <Line key={r.sym} k={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><TickerLink symbol={r.sym} noFlag /><RiskChips flags={risk[r.sym]} max={1} /></span>} v={<span>
                          {r.chg != null && <span style={{ color: tone(r.chg), marginRight: 10, fontSize: 10.5 }}>today {pct(r.chg)}</span>}
                          {r.pnl != null ? <span style={{ color: tone(r.pnl) }}>{pct(r.pnl / r.cost * 100)}</span> : <span style={{ color: T.dim }}>no quote</span>}</span>} />
                      ))}
                    </>
                  })()}
                </>}
          </div>
        </Panel>

        {/* ── market today (the gold open is one line at the foot) ─ */}
        {(
          <Panel source={todaySrc ?? sourceOf(null, { source: 'NSE' })} title="Market today" subtitle="intraday · vs previous close" accent={T.green}
            right={<Go code="MOV" onGo={() => onNavigate('movers')} />}>
            <IndexIntraday height={210} onSource={setTodaySrc} />
            {(() => {   // breadth through the day (market internals, sampled every 2 min)
              const sm = internals.data?.summary
              if (!sm?.n500_adv) return null
              return <div style={{ fontSize: 10.5, fontFamily: T.mono, color: T.muted, marginTop: 6, borderTop: `1px solid ${T.border}`, paddingTop: 5 }}>
                NIFTY 500 <span style={{ color: T.green }}>{sm.n500_adv} up</span> / <span style={{ color: T.red }}>{sm.n500_dec} down</span>
                {sm.samples > 10 && sm.net_worst != null && <span style={{ color: T.dim }}> · net {fmtSigned(sm.net_worst, 0)} … +{Math.max(0, sm.net_best ?? 0)} {sessionDayLabel(internals.data?.day)}</span>}
                {sm.divergence && <span style={{ color: T.amber, fontWeight: 700 }}> · ⚠ {sm.divergence}</span>}
                <span role="button" onClick={() => onNavigate('movers')} style={{ color: T.cyan, cursor: 'pointer' }}> · internals ›</span>
              </div>
            })()}
            {(() => {   // who moved NIFTY today (points, rebuilt free-float weights; moves from the live quote service)
              const ms = (liveContrib?.members ?? []).filter(m => m.points != null)
              if (ms.length < 5) return null
              const fmt = (m: (typeof ms)[number]) => <span key={m.symbol} style={{ whiteSpace: 'nowrap' }}><TickerLink symbol={m.symbol} />{' '}
                <span style={{ color: m.points! >= 0 ? T.green : T.red }}>{fmtSigned(m.points!, 0)}</span></span>
              const up = ms.slice(0, 3).filter(m => m.points! > 0), dn = [...ms].reverse().slice(0, 2).filter(m => m.points! < 0)
              return <div style={{ fontSize: 10.5, fontFamily: T.mono, color: T.muted, marginTop: 4 }}
                title={liveContrib && liveContrib.liveMembers ? `${liveContrib.liveMembers} of ${liveContrib.members.length} members' moves from the live NSE quote service; weights from filings` : `NSE heatmap + allIndices (${contrib.data?.time ?? 'no stamp'}), re-polled every 2 min`}>
                NIFTY points{liveContrib && liveContrib.liveMembers && contribLive.source ? <> <SourceChip info={contribLive.source} style={{ fontSize: 8.5 }} /></> : contrib.data?.time ? <span style={{ color: T.dim }}> ({contrib.data.time.slice(-5)} NSE)</span> : null} · {up.map((m, i) => <span key={m.symbol}>{i ? ' · ' : ''}{fmt(m)}</span>)}
                {dn.length > 0 && <> · drag {dn.map((m, i) => <span key={m.symbol}>{i ? ' · ' : ''}{fmt(m)}</span>)}</>}
              </div>
            })()}
            <div data-brief-gold style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, borderTop: `1px solid ${T.border}`, paddingTop: 5 }}>
              <span style={{ fontSize: 10.5, fontFamily: T.mono, color: goldHealth.data ? T.muted : T.dim, flex: 1, minWidth: 0, whiteSpace: 'normal', lineHeight: 1.5 }}
                title={goldHealth.data?.verdict?.line ?? goldHealth.error ?? 'gold health'}>
                {goldHealth.loading && !goldHealth.data ? 'Gold: loading…' : goldHealth.error && !goldHealth.data ? `Gold: ${goldHealth.error}`
                  : goldLine.segments.map((s, i) => <span key={i} style={{ color: goldToneColor(s.tone), fontWeight: s.tone === 'muted' ? 400 : 600 }}>{s.text}</span>)}
              </span>
              <Go code="GOLD" onGo={() => { setGoldSubInUrl('health'); onNavigate('gold') }} />
            </div>
          </Panel>
        )}

        {/* ── this week ──────────────────────────────────────────── */}
        <Panel source={{ state: 'delayed', source: 'NSE calendar', asOf: null, hint: 'board meetings and corporate actions, refreshed every 2 min' }} title="This week" subtitle={`next 7 days · ${week.total} corporate events`} accent={T.cyan}
          right={<Go code="EVTS" onGo={() => onNavigate('events')} />}>
          <Pending s={events}>
            <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.green, margin: '2px 0 4px' }}>YOUR STOCKS · {mine.size} TRACKED</div>
            {week.mine.length
              ? week.mine.map(e => <Line key={`${e.symbol}-${e.kind}`} k={<TickerLink symbol={e.symbol} />} v={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                  {e.kind !== 'RESULTS' && e.detail && !/has informed the exchange/i.test(e.detail) && (     // what the meeting is about
                    <span style={{ color: T.muted, fontSize: 10.5, maxWidth: 360, textAlign: 'right' }}>{(() => { const t = e.detail.replace(/^To consider and approve (the )?/i, '').replace(/\b(\w+) s\b/g, "$1's"); return (t[0]?.toUpperCase() ?? '') + t.slice(1, 110) })()}</span>)}
                  <EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} typical={e.typical_move_pct} detail={e.detail} /></span>} />)
              : <div style={{ fontSize: 11, color: T.dim, padding: '4px 0 8px' }}>Nothing announced for your stocks this week.</div>}
            {(() => {   // results filed since the last close: live reaction in session, else what the numbers said (react at 09:15)
              const d = reacting.data
              const live = d?.phase === 'session'
              const all = d?.rows ?? []
              const rows = (live ? all.filter(r => r.change_pct != null || r.reacts_next_session)
                                 : [...all].sort((a, b) => Math.abs(b.pat_yoy ?? 0) - Math.abs(a.pat_yoy ?? 0))).slice(0, 6)
              if (!rows.length) return null
              const profit = (r: ReactingResult) => (r.pat_yoy != null || r.pat_turn)
                ? <span style={{ fontSize: 10, color: T.muted }}> · profit <span style={{ color: r.pat_turn ? (r.pat_turn === 'to profit' ? T.green : T.red) : r.pat_yoy! >= 0 ? T.green : T.red }}>{r.pat_turn ?? fmtPct(r.pat_yoy, 0)}</span>{r.pat_turn ? '' : ' y/y'}</span> : null
              return <>
                <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.amber, margin: '10px 0 4px' }}>
                  {live ? 'RESULTS · REACTING TODAY' : d?.phase === 'preopen' ? 'RESULTS · PRE-OPEN AUCTION' : 'RESULTS SINCE THE LAST CLOSE · REACT AT 09:15'}
                  <span style={{ color: T.dim, letterSpacing: 0 }}> · filed since {d!.since.slice(5)}{live ? ' · live' : ''}</span></div>
                {rows.map(r => (
                  <Line key={r.symbol} k={<><TickerLink symbol={r.symbol} /> <span style={{ color: T.dim, fontSize: 10 }}>filed {r.filed_at.slice(5, 16)}</span>{profit(r)}</>}
                        v={r.change_pct != null ? <><span style={{ color: r.change_pct >= 0 ? T.green : T.red, fontWeight: 700 }}>{fmtPct(r.change_pct, 1)}</span>
                          {d?.phase === 'preopen' && <span style={{ color: T.dim, fontSize: 10 }}> pre-open</span>}
                          {r.vs_typical != null
                            ? <span style={{ color: r.vs_typical >= 1.5 ? T.amber : T.dim, fontSize: 10 }}> · {r.vs_typical.toFixed(1)}× normal (±{r.typical_move_pct!.toFixed(1)}%)</span>
                            : <span style={{ color: T.dim, fontSize: 10 }}> · no results history</span>}</>
                          : <span style={{ color: T.dim, fontSize: 10 }}>{r.reacts_next_session ? 'reacts next session' : 'awaiting the open'}
                              {r.revenue_yoy != null && <> · rev <span style={{ color: r.revenue_yoy >= 0 ? T.green : T.red }}>{fmtPct(r.revenue_yoy, 0)}</span></>}
                              {r.typical_move_pct != null && <> · typically ±{r.typical_move_pct.toFixed(1)}%</>}</span>} />
                ))}
              </>
            })()}
            {(() => {   // results filed today, live from NSE announcements (the nightly capture adds release times later)
              const today = (filings.data?.items ?? []).filter(f => f.category === 'results')
              const seen = new Set<string>(); const uniq = today.filter(f => !seen.has(f.symbol) && seen.add(f.symbol))
              return uniq.length ? <>
                <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.violet, margin: '10px 0 4px' }}>
                  RESULTS FILED TODAY · {uniq.length} <span role="button" onClick={() => onNavigate('filings')} style={{ color: T.cyan, cursor: 'pointer' }}>CF ›</span></div>
                <div style={{ fontSize: 11, lineHeight: 1.7, display: 'flex', flexWrap: 'wrap', columnGap: 12 }}>
                  {uniq.slice(0, 14).map(f => <span key={f.symbol} style={{ whiteSpace: 'nowrap' }}>
                    <TickerLink symbol={f.symbol} /> <span style={{ color: T.dim, fontSize: 10 }}>{(f.time ?? '').slice(11, 16)}</span></span>)}
                  {uniq.length > 14 && <span style={{ color: T.dim }}>+{uniq.length - 14} more</span>}
                </div>
              </> : null
            })()}
            {(() => {
              const done = (reported.data?.rows ?? []).filter(r => r.move_pct != null)
                .sort((a, b) => Math.abs(b.move_pct!) / (b.typical_move_pct || 3) - Math.abs(a.move_pct!) / (a.typical_move_pct || 3)).slice(0, 5)
              return done.length ? <>
                <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.amber, margin: '10px 0 4px' }}>JUST REPORTED · BIGGEST REACTIONS</div>
                {done.map(r => (
                  <Line key={`${r.symbol}-${r.period_end}`} k={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><TickerLink symbol={r.symbol} />{r.avoid && <AvoidFlag r={r} />}</span>}
                        v={<><span style={{ color: r.move_pct! >= 0 ? T.green : T.red, fontWeight: 700 }}>{fmtSigned(r.move_pct!, 1)}%</span>
                          {r.typical_move_pct != null && <span style={{ color: T.dim, fontSize: 10 }}> · {(Math.abs(r.move_pct!) / r.typical_move_pct).toFixed(1)}× normal</span>}</>} />
                ))}
              </> : null
            })()}
            {(insiders.data?.rows ?? []).length > 0 && <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '10px 0 4px' }}>
                <span style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.green }}>INSIDER BUYING · LAST 7 DAYS · ≥ ₹1 CR</span>
                <span role="button" onClick={() => onNavigate('insiders')} style={{ color: T.cyan, cursor: 'pointer', fontSize: 10 }}>INSD ›</span>
              </div>
              {[...(insiders.data?.rows ?? [])].sort((a, b) => b.total_value - a.total_value).slice(0, 4).map(r => (
                <Line key={r.symbol} k={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><TickerLink symbol={r.symbol} />
                  <span style={{ color: T.dim, fontSize: 10, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.categories}</span></span>}
                  v={<span style={{ color: T.green }}>₹{(r.total_value / 1e7).toFixed(r.total_value >= 1e9 ? 0 : 1)} cr
                    <span style={{ color: T.dim, fontSize: 10 }}> · {r.buyers} buyer{r.buyers > 1 ? 's' : ''}</span></span>} />
              ))}
            </>}
            <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.muted, margin: '10px 0 4px' }}>LARGEST NAMES REPORTING</div>
            {week.big.map(e => (
              <Line key={`${e.symbol}-${e.kind}`} k={<><TickerLink symbol={e.symbol} /> <span style={{ color: T.dim, fontSize: 10 }}>₹{Math.round(e.turnover_cr ?? 0)} cr/day</span>
                {e.typical_move_pct != null && <span style={{ color: e.typical_move_pct >= 5 ? T.amber : T.muted, fontSize: 10 }}> · typically ±{e.typical_move_pct.toFixed(1)}%</span>}
                {(() => { const f = bigFin[e.symbol]; if (!f || (f.pat_yoy == null && !f.pat_yoy_turn)) return null
                  return <span style={{ fontSize: 10, color: T.dim }} title="previous quarter's profit vs a year earlier (NSE filing)"> · last Q profit{' '}
                    <span style={{ color: f.pat_yoy_turn ? (f.pat_yoy_turn === 'to profit' ? T.green : T.red) : f.pat_yoy! >= 0 ? T.green : T.red }}>{f.pat_yoy_turn ?? fmtPct(f.pat_yoy, 0)}</span></span> })()}</>}
                    v={<EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} typical={e.typical_move_pct} detail={e.detail} />} />
            ))}
          </Pending>
        </Panel>

        {/* ── news ───────────────────────────────────────────────── */}
        <Panel source={sourceOf(scan.data?.scan_date ?? null, { source: 'news scanner', maxAgeDays: 3 })} badge="context" title="News scanner" subtitle={scan.data ? `scan ${scan.data.scan_date} · ${scan.data.picks?.length ?? 0} picks` : 'latest scan'} accent={T.violet}
          right={<Chip color={T.violet} onClick={() => window.dispatchEvent(new Event('suryadhana:open-news'))}>NEWS ›</Chip>}>
          {track.data && (() => { const v = trackVerdict(track.data); return (
            <div style={{ fontSize: 11, color: v.color, borderLeft: `2px solid ${v.color}`, paddingLeft: 8, marginBottom: 8 }}>
              Track record ({track.data.picks} picks): {v.text}
            </div>) })()}
          <Pending s={scan}>
            {picks.slice(0, 6).map((p: any) => (
              <Line key={p.symbol?.yahoo ?? p.raw_ticker}
                k={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
                  {p.symbol?.region === 'IN' ? <TickerLink symbol={p.symbol.base} /> : <span style={{ color: T.amber, fontWeight: 600 }}>{p.symbol?.base ?? p.raw_ticker}</span>}
                  <span style={{ color: T.muted, fontSize: 10.5, maxWidth: 250, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.catalyst_category}</span>
                </span>}
                v={<span style={{ color: (p.conviction_score ?? 0) >= 6 ? T.green : T.muted }}>conv {p.conviction_score}</span>} />
            ))}
          </Pending>
        </Panel>

        {/* ── headlines ──────────────────────────────────────────── */}
        <Panel source={sourceOf(heads.data?.headlines?.[0]?.published_at ?? null, { source: 'headlines', maxAgeDays: 1 })} title="Headlines" subtitle="last 24 h · Indian markets, RBI, FII flows, results, IPOs, global" accent={T.cyan}>
          <Pending s={heads}>
            {(heads.data?.headlines ?? []).slice(0, 9).map(h => (
              <a key={h.link} href={h.link} target="_blank" rel="noreferrer"
                 style={{ display: 'grid', gridTemplateColumns: '64px 1fr auto', gap: 8, padding: '5px 0', borderBottom: `1px solid ${T.border}`,
                          textDecoration: 'none', fontSize: 11.5 }}>
                <span style={{ fontFamily: T.mono, fontSize: 9, color: T.cyan, letterSpacing: .6, textTransform: 'uppercase', paddingTop: 2 }}>{h.topic}</span>
                <span style={{ color: T.text, lineHeight: 1.4 }}>{h.title} <span style={{ color: T.dim, fontSize: 10 }}>· {h.publisher}</span></span>
                <span style={{ color: T.dim, fontSize: 10, whiteSpace: 'nowrap' }}>{Math.max(1, Math.round((Date.now() - new Date(h.published_at).getTime()) / 3_600_000))}h</span>
              </a>
            ))}
          </Pending>
        </Panel>

        {/* ── system ─────────────────────────────────────────────── */}
        <Panel source={sourceOf(tele.data?.ist_now ?? null, { source: 'controller', live: !!tele.data?.master_controller_online })} title="System" subtitle="data · broker · scheduler" accent={T.muted}
          right={<Go code="SYS" onGo={() => onNavigate('system')} />}>
          <Line k="NSE data through" v={dash.data?.latest_date ?? '—'} />
          {/* P4: an ICICI network outage is not an expired session (error_kind, components/portfolio/iciciState.ts) */}
          <Line k="ICICI session" v={broker.loading ? 'checking…' : briefSessionLine(brokerKind)}
                c={broker.data?.connected ? T.green : T.amber} />
          <Line k="Scheduler" v={tele.data?.master_controller_online ? 'online' : 'offline'} c={tele.data?.master_controller_online ? T.green : T.red} />
          <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.4, color: T.muted, margin: '10px 0 4px' }}>NEXT JOBS</div>
          {jobs.map((j: any) => (
            <Line key={j.id} k={j.name} v={j.next_run_ist ? new Date(j.next_run_ist).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : '—'} />
          ))}
        </Panel>

      </div>
    </div>
  )
}
