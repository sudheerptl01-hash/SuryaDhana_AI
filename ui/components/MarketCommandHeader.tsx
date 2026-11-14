'use client'

/**
 * MarketCommandHeader: the terminal shell (News Catalyst Terminal look, app-wide).
 *
 *   Row 1  ◉ SURYADHANA ▸ PAGE · NIFTY 50 live (O/H/L) · service lights · IST clock · alerts · ⤓ UPDATE DATA
 *   Row 2  macro tape: NIFTY, BANK NIFTY, INDIA VIX, USD/INR, BRENT, GOLD, S&P 500 (60 s)
 *   Row 3  page strip, re-cut for the trader's day (page review M37, components/shell/stripOrder.ts): BRF WTCH CHRT
 *          OMON OSTR DERV MOV EVTS ALRT RSK GOLD MCXG MKT DESK, Alt+1…0 on the first ten in the owner's order
 *          (strip.order.v1, ⚙ ARRANGE THE STRIP under MORE ▾); research / legacy pages under RESEARCH ▾, the rest
 *          under MORE ▾; ⌘1…9 in the app follow the native Go menu
 *
 * Phone (≤ 720 px, globals.css `sd-h-*` / `sd-pstrip*`): row 1 keeps NIFTY whole (brand text, lights, clock and the
 * UPDATE DATA word drop), the tape scrolls, every strip target is 44 px.
 *
 * In SuryaDhana.app (C1-trader-ux-06) the title strip above is the one brand / clock / session / service-light
 * source, so row 1 drops its copies (brand + page name, universe count, DATA / DB lights, session chip, clock) and
 * keeps NIFTY, ICICI, alerts and UPDATE DATA, in a shorter 36 px row. A browser keeps today's full row.
 *
 * Row 1 never overflows (C1-trader-ux-10): every item is nowrap, the brand's page name ellipsizes, the row clips
 * instead of widening the page, and the least important items drop out by width (globals.css t-hide-*).
 *
 * The 1 s clock + session chip is its own memo'd, second-aligned leaf (HeaderClock), so the header no longer
 * re-renders every second (C2-performance-07).
 *
 * Data: NIFTY from the ICICI websocket when it is streaming, else NSE's live index (/api/market/nifty-live, ≈1 min
 * delayed), else the last stored ICICI quote (marked STALE). On a closed market the chip reads CLOSE <day> and
 * while the link is down STALE (C1-trader-ux-13, lib/feedState.ts); a live tick or a fresh NSE print beats the
 * calendar (Muhurat, R-UI-SHELL-03). Polls: stored quote 5 s, NSE 15 s while the market prints and the window is
 * visible, 60 s otherwise (R-UI-SHELL-06 / C-PERF-06); macro tape from /api/news-scanner/quotes (Yahoo, 60 s; 5 min
 * while the window is hidden; it keeps running after the NSE close because GIFT NIFTY, FX and commodities still
 * trade). While the link is down the tape is dimmed and tagged STALE (CT-15).
 *
 * P9 (round 4b): in NSE's regular hours a NIFTY quote more than 5 min old reads ◌ STALE <time> (never ● LIVE / ● NSE
 * on a value that stopped), a stopped ICICI stream gives way to NSE's print, and the tape's NSE and Yahoo halves land
 * independently. P4: the ICICI light's tooltip says why it is red (network outage vs expired session vs missing key).
 */
import { Z } from '@/lib/z'
import { memo, useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent } from 'react'
import { useLiveQuotes, useDataServiceStatus } from '@/context/AppContext'
import { useLiveQuotes as useNseQuotes } from '@/lib/liveQuotes'
import { liveHeaderChip } from '@/components/liveModel'
import { sourceChipText } from '@/components/terminal/source'
import { getNewsQuotes, getGiftNifty, getICICIConnectionStatus, getIndicesLive, type GiftNifty } from '@/lib/api'
import { AlertsBell } from '@/components/AlertsBell'
import { T } from '@/components/terminal'
import { goToPage } from '@/lib/navigate'
import { DataStaleChip } from '@/components/datahealth/DataHealthView'
import { BrokerChip } from '@/components/brkr/BrokerChip'   // F7-05: a dead broker session was invisible
import { DisciplineHeaderChips } from '@/components/risk/HeaderChips'
import { newWindow } from '@/lib/platform'
import { chromePollMs, isFreshPrint, liveQuoteAt, niftySourceChip, nseTimeToEpoch, pickNiftySource } from '@/lib/feedState'
import { iciciLightTitle } from '@/lib/iciciStatus'
import { headerSession, istParts, nseSession } from '@/components/desktop/session'
import { useNseHolidays } from '@/components/desktop/holidays'
import { useSecondTick } from '@/components/desktop/TitleStrip'
import { useUpstreamSnapshot } from '@/components/desktop/ShellNotices'
import { useShellState } from '@/components/shell/ShellState'
import { useFeedState } from '@/components/shell/useFeed'
import { useDocumentHidden, usePolling } from '@/components/shell/usePoll'
import { noteNsePrint } from '@/lib/liveEvidence'
import { MAX_STRIP, addToStrip, isDefaultStrip, moveInStrip, removeFromStrip, slotDigit, slotForDigitCode, slotKeyHint, splitMenus } from '@/components/shell/stripOrder'
import { useStripOrder } from '@/components/shell/useStripOrder'
import { openSettingsImport, useImportOffer } from '@/components/shell/SettingsImport'
import { WorkspaceMenu } from '@/components/desktop/WorkspaceMenu'

// ── IST clock + session state ─────────────────────────────────────────────────

const IST_DATE = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', weekday: 'short', day: '2-digit', month: 'short' })

/**
 * Session chip + IST clock (browser mode). Its own second-aligned tick, memo'd with no props: the rest of the
 * header does not re-render for the clock. The session uses the same holiday-aware rule as the desktop title strip
 * (components/desktop/session.ts) and the shared ECO-calendar fetch, so the two never disagree.
 */
const HeaderClock = memo(function HeaderClock() {
  const now = useSecondTick()
  const p = istParts(now)
  const holidays = useNseHolidays(p.date)
  const s = headerSession(nseSession(now, holidays))
  const color = s.tone === 'green' ? T.green : s.tone === 'amber' ? T.amber : T.muted
  return (
    <div className="sd-h-clock" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 14px', borderLeft: `1px solid ${T.border}`, height: '100%', flex: 'none' }}>
      <span title={s.label === 'MUHURAT' || s.label === 'SPECIAL' ? `NSE special session: ${s.holiday} (timings per NSE circular)`
                    : s.holiday ? `NSE closed: ${s.holiday}` : undefined}
            style={{ fontSize: 10, letterSpacing: 1.2, color, border: `1px solid ${color === T.muted ? T.border : color}`,
                     padding: '2px 6px', whiteSpace: 'nowrap' }}>{s.label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, color: T.bright, whiteSpace: 'nowrap' }}>{p.time}</span>
      <span className="t-hide-xl" style={{ fontSize: 10, color: T.dim, letterSpacing: 1, whiteSpace: 'nowrap' }}>
        {IST_DATE.format(now).toUpperCase()} IST
      </span>
    </div>
  )
})

// ── NIFTY live ────────────────────────────────────────────────────────────────

function NiftyLive() {
  const { liveQuotes, wsConnected } = useLiveQuotes()
  // live program (reports/live_nse): the live NSE quote service first — the Breeze websocket index tick '4.1!NIFTY 50'
  // (≈ 10/s server-side, polled here every 2 s), else NSE's website through the service, else CLOSE <day>. The older
  // sources below (the monitor socket's REST quote, NSE allIndices, the stored quote) apply only while it has no row.
  const svc = useNseQuotes(['NIFTY 50'], { intervalMs: 2_000 })
  const sq = svc.quotes['NIFTY 50']
  const svcRow = sq && sq.price != null && sq.state !== 'unavailable' ? sq : null
  const svcInfo = svcRow ? svc.sourceFor('NIFTY 50') : null
  const svcChip = svcRow ? liveHeaderChip(svcInfo, svcRow.ltt) : null
  const { marketOpen, linkDown } = useFeedState()
  const { desktop } = useShellState()
  const [http, setHttp] = useState<any>(null)
  const [nse, setNse] = useState<any>(null)
  const hidden = useDocumentHidden()
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  // live cadence while NSE prints (calendar, a tick, or a fresh NSE stamp) and the window is visible; 60 s otherwise
  const printing = marketOpen || isFreshPrint(nse?.time, Date.now())
  usePolling(async () => {
    try {
      const res = await fetch('/api/market/nifty-live')
      if (alive.current && res.ok) { const j = await res.json(); setNse(j); noteNsePrint(j?.time) }
    } catch { /* next poll */ }
  }, chromePollMs(15_000, { marketOpen: printing, hidden }))
  usePolling(async () => {
    try {
      const res = await fetch('/api/data/live/index/nifty')
      if (alive.current && res.ok) setHttp(await res.json())
    } catch { /* backend restarting: next poll */ }
  }, svcRow ? 60_000 : chromePollMs(5000, { marketOpen: printing, hidden }))   // the stored quote is only a last resort
  const [flash, setFlash] = useState<'up' | 'down' | null>(null)
  const prev = useRef<number | null>(null)

  const ws = liveQuotes['NIFTY'] || liveQuotes['NSEI']
  const rec = (() => {
    const p = http?.record?.payload
    if (!p) return null
    if (typeof p === 'string') { try { return JSON.parse(p) } catch { return null } }
    return p
  })()
  // source: ICICI stream → NSE live index → last stored ICICI quote (which can be yesterday's); a stream that stopped
  // (its quote more than 5 min behind NSE's print) gives way to NSE (P9, lib/feedState.ts pickNiftySource)
  const wsAt = liveQuoteAt(ws)
  const nseAt = nseTimeToEpoch(nse?.time)
  const src = pickNiftySource({ wsLtp: ws?.ltp, wsAt, nseLast: nse?.last, nseAt, storedLtp: rec?.ltp })
  const ltp: number | null = svcRow ? svcRow.price : src === 'ICICI' ? ws.ltp : src === 'NSE' ? nse.last : rec?.ltp ?? null
  const pc: number | null = svcRow ? svcRow.prev_close : src === 'ICICI' ? ws?.raw?.previous_close ?? null : src === 'NSE' ? nse.previous_close : rec?.previous_close ?? null
  const chg = svcRow ? svcRow.change ?? (ltp != null && pc != null ? ltp - pc : null)
    : src === 'NSE' ? nse.change : ltp != null && pc != null ? ltp - pc : ws?.change ?? null
  const pct = svcRow ? svcRow.change_pct ?? (chg != null && pc ? (chg / pc) * 100 : null)
    : src === 'NSE' ? nse.change_pct
    : ws?.change_pct ?? ws?.raw?.ltp_percent_change ?? rec?.ltp_percent_change ?? (chg != null && pc ? (chg / pc) * 100 : null)
  const o = svcRow ? svcRow.open : src === 'NSE' ? nse.open : ws?.raw?.open ?? rec?.open
  const h = svcRow ? svcRow.day_high : src === 'NSE' ? nse.high : ws?.raw?.high ?? rec?.high
  const l = svcRow ? svcRow.day_low : src === 'NSE' ? nse.low : ws?.raw?.low ?? rec?.low

  useEffect(() => {
    if (ltp == null) return
    if (prev.current != null && ltp !== prev.current) {
      setFlash(ltp > prev.current ? 'up' : 'down')
      const t = setTimeout(() => setFlash(null), 700)
      prev.current = ltp
      return () => clearTimeout(t)
    }
    prev.current = ltp
  }, [ltp])

  const up = (chg ?? 0) >= 0
  const n = (v: any) => v == null ? '—' : Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  // the shown quote's own time: ● LIVE / ● NSE never sit on a value that stopped updating in market hours (P9)
  const quoteAt = src === 'ICICI' ? wsAt : src === 'NSE' ? nseAt : null
  const chip = linkDown ? niftySourceChip({ src, wsConnected, marketOpen, linkDown, asOf: nse?.time ?? null, now: Date.now(), quoteAt })
    : svcChip ?? niftySourceChip({ src, wsConnected, marketOpen, linkDown, asOf: nse?.time ?? null, now: Date.now(), quoteAt })
  const chipColor = chip.tone === 'live' ? T.green : chip.tone === 'delayed' ? T.cyan : T.muted
  return (
    <div className="sd-h-nifty" style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '0 16px', borderLeft: `1px solid ${T.border}`,
                  borderRight: `1px solid ${T.border}`, height: '100%', flex: '0 1 auto', minWidth: 0, overflow: 'hidden', whiteSpace: 'nowrap' }}>
      <span className="sd-h-nifty-k" style={{ fontSize: 10, letterSpacing: 1.4, color: T.muted, whiteSpace: 'nowrap' }}>NIFTY 50</span>
      <span style={{ fontSize: 17, fontWeight: 700, letterSpacing: .3,
                     color: flash === 'up' ? T.green : flash === 'down' ? T.red : T.bright,
                     background: flash ? (flash === 'up' ? 'rgba(22,217,138,.12)' : 'rgba(255,77,94,.12)') : 'transparent',
                     padding: '0 4px', transition: 'background .3s' }}>{n(ltp)}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color: chg == null ? T.muted : up ? T.green : T.red, whiteSpace: 'nowrap' }}>
        {chg == null ? '' : `${up ? '▲' : '▼'} ${Math.abs(chg).toFixed(2)}  ${pct != null ? `${up ? '+' : '−'}${Math.abs(Number(pct)).toFixed(2)}%` : ''}`}
      </span>
      <span className={`${desktop ? 't-hide-md' : 't-hide-xl'} sd-h-ohl`} style={{ fontSize: 10, color: T.dim, display: 'flex', gap: 10, whiteSpace: 'nowrap' }}>
        <span>O <span style={{ color: T.muted }}>{n(o)}</span></span>
        <span>H <span style={{ color: T.muted }}>{n(h)}</span></span>
        <span>L <span style={{ color: T.muted }}>{n(l)}</span></span>
      </span>
      <span title={chip.title} data-feed={chip.tone}
            data-sd-age-s={svcChip && !linkDown && svcInfo?.ageS != null ? svcInfo.ageS.toFixed(1) : undefined}
            data-sd-feed-source={svcChip && !linkDown ? svcInfo?.source ?? undefined : undefined}
            style={{ fontSize: 9, letterSpacing: 1, padding: '2px 6px', whiteSpace: 'nowrap', flex: 'none',
                     border: `1px solid ${chipColor === T.muted ? T.border : chipColor}`, color: chipColor }}>
        {chip.text}</span>
    </div>
  )
}

// ── macro tape ────────────────────────────────────────────────────────────────

// Indian indices come from NSE (`nse` = allIndices name); Yahoo's can lag a whole session after the close
const MACRO: { sym: string; label: string; digits?: number; nse?: string }[] = [
  { sym: '^NSEI', label: 'NIFTY 50', nse: 'NIFTY 50' },
  { sym: '^NSEBANK', label: 'BANK NIFTY', nse: 'NIFTY BANK' },
  { sym: '^INDIAVIX', label: 'INDIA VIX', nse: 'INDIA VIX' },
  { sym: 'INR=X', label: 'USD/INR', digits: 3 },
  { sym: 'BZ=F', label: 'BRENT' },
  { sym: 'GC=F', label: 'GOLD GC1' },      // the continuous COMEX front, named (gold program PLAN §b); the page is GOLD
  { sym: '^GSPC', label: 'S&P 500' },
]

function MacroTape() {
  const [q, setQ] = useState<Record<string, any>>({})
  const [at, setAt] = useState<string>('')
  // D13: one stamp per source, not one for the tape. NSE indices from the live NSE quote service when it answers
  // (Breeze websocket index ticks; INDIA VIX streams too), per-item source + age on hover; allIndices otherwise.
  const [atNse, setAtNse] = useState<string>('')
  const [atYahoo, setAtYahoo] = useState<string>('')
  const tapeLive = useNseQuotes(MACRO.filter(m => m.nse).map(m => m.nse!), { intervalMs: 3_000 })
  const [gift, setGift] = useState<GiftNifty | null>(null)
  const linkDown = useShellState().link === 'down'
  const hidden = useDocumentHidden()
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  // 60 s while visible (unchanged; GIFT NIFTY, FX and commodities trade after the NSE close), 5 min while hidden.
  // P9: NSE's indices and Yahoo's quotes land independently (allSettled semantics), each merged over the last values,
  // so a slow or failing Yahoo never blanks the tape or holds NSE's numbers back, and a failure keeps what was shown.
  usePolling(async () => {
    getGiftNifty().then(r => { if (alive.current) setGift(r.data) }).catch(() => {})
    const hm = () => new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false, hour: '2-digit', minute: '2-digit' })
    const stamp = () => setAt(hm())
    const yahoo = getNewsQuotes(MACRO.filter(m => !m.nse).map(m => m.sym)).then(r => {
      const quotes: Record<string, any> = r.data?.quotes ?? {}
      const got = MACRO.filter(m => !m.nse && quotes[m.sym] != null)
      if (!alive.current || !got.length) return
      setQ(prev => { const next = { ...prev }; for (const m of got) next[m.sym] = quotes[m.sym]; return next })
      stamp(); setAtYahoo(hm())
    })
    const nse = getIndicesLive(MACRO.filter(m => m.nse).map(m => m.nse!)).then(r => {
      const got = MACRO.filter(m => m.nse && r.data?.indices?.[m.nse]?.last != null)
      if (!alive.current || !got.length) return
      setQ(prev => {
        const next = { ...prev }
        for (const m of got) { const v = r.data.indices[m.nse!]; next[m.sym] = { price: v.last, change_pct: v.change_pct, source: 'NSE', time: v.time } }
        return next
      })
      stamp(); setAtNse(r.data?.timestamp ? String(r.data.timestamp).slice(-5) : hm())
    })
    await Promise.allSettled([yahoo, nse])        // a failed source keeps its last values
  }, chromePollMs(60_000, { marketOpen: true, hidden }, 300_000))
  return (
    <div data-sd-tape={linkDown ? 'stale' : 'live'}
      title={linkDown ? `ui-api unreachable: these are the last values received${at ? ` (${at} IST)` : ''}` : undefined}
      style={{ display: 'flex', alignItems: 'center', height: 26, borderBottom: `1px solid ${T.border}`,
               background: '#06080c', overflowX: 'auto', whiteSpace: 'nowrap', opacity: linkDown ? 0.55 : 1 }}>
      <span style={{ background: T.amber, color: T.bg, fontSize: 9, fontWeight: 700, letterSpacing: 1.2,
                     padding: '0 8px', height: '100%', display: 'flex', alignItems: 'center', flex: 'none' }}>MARKETS</span>
      {gift?.last != null && (
        <span title={`GIFT NIFTY (NSE IX${gift.expiry ? `, ${gift.expiry} contract` : ''}) at ${gift.time}: ${gift.implied_gap_pct ?? '—'}% vs NIFTY's last SPOT close. `
                     + 'Not the opening gap: GIFT tracks the near-month future, which trades above spot by the carry (about 0.2 % a month), '
                     + 'so the gap to fair value is lower by about that much (m002).'}
              style={{ display: 'inline-flex', gap: 7, alignItems: 'baseline', padding: '0 14px', borderRight: `1px solid ${T.border}`, fontSize: 11 }}>
          <span style={{ color: T.amber, fontSize: 10, letterSpacing: .8 }}>GIFT NIFTY</span>
          <span style={{ color: T.text }}>{gift.last.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          {gift.implied_gap_pct != null && <span style={{ color: gift.implied_gap_pct >= 0 ? T.green : T.red }}>{gift.implied_gap_pct >= 0 ? '+' : '−'}{Math.abs(gift.implied_gap_pct).toFixed(2)}%{' '}
            vs spot</span>}
        </span>
      )}
      {MACRO.map((m, i) => {
        const lr = m.nse ? tapeLive.quotes[m.nse] : undefined
        const svcRow = lr && lr.price != null && lr.state !== 'unavailable' ? lr : null
        const v = svcRow ? { price: svcRow.price, change_pct: svcRow.change_pct } : q[m.sym]
        const itemTitle = svcRow ? tapeLive.lineFor(m.nse!) ?? undefined
          : m.nse ? (q[m.sym] ? `NSE allIndices${q[m.sym].time ? ` · ${q[m.sym].time}` : atNse ? ` · ${atNse} IST` : ''} (about 1–3 min behind)` : undefined)
          : q[m.sym] ? `Yahoo (non-NSE), about 1 min delayed${atYahoo ? ` · read ${atYahoo} IST` : ''}` : undefined
        const c = v?.change_pct
        const col = c == null ? T.muted : c >= 0 ? T.green : T.red
        // narrow terminals drop tape entries from the right instead of scrolling (720/1024/1280)
        const slice = i >= 6 ? 't-tape-ge6' : i >= 4 ? 't-tape-ge4' : i >= 2 ? 't-tape-ge2' : undefined
        return (
          <span key={m.sym} className={slice} title={itemTitle} data-sd-tape-src={svcRow ? svcRow.source : m.nse ? 'nse_allindices' : 'yahoo'}
                style={{ display: 'inline-flex', gap: 7, alignItems: 'baseline', padding: '0 14px',
                         borderRight: `1px solid ${T.border}`, fontSize: 11 }}>
            <span style={{ color: T.muted, fontSize: 10, letterSpacing: .8 }}>{m.label}</span>
            <span style={{ color: T.text }}>{v?.price != null ? Number(v.price).toLocaleString('en-IN', { maximumFractionDigits: m.digits ?? 2, minimumFractionDigits: m.digits ?? 2 }) : '—'}</span>
            <span style={{ color: col }}>{c == null ? '' : `${c >= 0 ? '+' : '−'}${Math.abs(c).toFixed(2)}%`}</span>
          </span>
        )
      })}
      <span style={{ flex: 1 }} />
      {linkDown
        ? <span style={{ fontSize: 9, color: T.red, letterSpacing: 1, padding: '0 12px', flex: 'none' }}>◌ STALE{at ? ` · ${at} IST` : ''}</span>
        : <span className="t-tape-ge2" style={{ fontSize: 9, color: T.dim, padding: '0 12px', flex: 'none' }}
            title="NSE indices: the live NSE quote service (Breeze websocket) when it answers, else NSE allIndices. USD/INR, Brent, gold and the S&P 500: Yahoo, about 1 min delayed, on their own sessions (the S&P trades 20:00–02:30 IST in winter): the NSE state never describes them">
            {/* m006: the NSE session word (CLOSE · 05 NOV) applies to the NSE indices only, never to the S&P / FX / commodities */}
            {tapeLive.available && tapeLive.source
              ? `NSE ${sourceChipText(tapeLive.source).label}${atYahoo ? ` │ FX · BRENT · GOLD · S&P: YAHOO ${atYahoo} IST` : ''}`
              : at && `NSE${atNse ? ` ${atNse}` : ''} │ FX · BRENT · GOLD · S&P: YAHOO${atYahoo ? ` ${atYahoo}` : ''} IST`}</span>}
    </div>
  )
}

// ── page strip ────────────────────────────────────────────────────────────────

type MorePage = { id: string; code: string; label: string; hint: string }

/** A ▾ menu of pages outside the strip (RESEARCH ▾, MORE ▾; also on GO). Fixed-positioned so the strip's horizontal
 *  scroll doesn't clip it. `extra` rows (ARRANGE STRIP, IMPORT SETTINGS) sit under a rule at the bottom. */
function PageMenu({ title, pages, active, onChange, badges = {}, extra = [], heading }: {
  title: string; pages: MorePage[]; active: string; onChange: (id: string) => void; badges?: Record<string, number | undefined>
  extra?: { key: string; label: string; hint: string; run: () => void }[]; heading: string
}) {
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<{ top: number; right: number }>({ top: 0, right: 0 })
  const btn = useRef<HTMLButtonElement>(null)
  const current = pages.find(p => p.id === active)
  const tag = `menu-${title.toLowerCase()}`
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !(e.target as HTMLElement).closest(`[data-more-menu="${tag}"]`)) setOpen(false)
    }
    window.addEventListener('mousedown', close); window.addEventListener('keydown', close)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', close) }
  }, [open, tag])
  const toggle = () => {
    const r = btn.current?.getBoundingClientRect()
    if (r) setAt({ top: r.bottom, right: Math.max(8, window.innerWidth - r.right) })
    setOpen(o => !o)
  }
  return (
    <>
      <button ref={btn} data-more-menu={tag} onClick={toggle} title={`${heading} (also on GO)`} className="sd-pstrip-tab" aria-expanded={open}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', flex: 'none',
                 background: current ? '#0e131c' : '#0b0f16', border: 'none', borderLeft: `1px solid ${T.borderHi}`, cursor: 'pointer',
                 borderBottom: `2px solid ${current ? T.amber : 'transparent'}` }}>
        <span style={{ fontFamily: T.display, fontSize: 11, fontWeight: 700, letterSpacing: 1, color: current ? T.amber : T.cyan }}>
          {current ? current.code : title} ▾
        </span>
      </button>
      {open && (
        <div data-more-menu={tag} role="menu" aria-label={heading}
          style={{ position: 'fixed', top: at.top, right: at.right, zIndex: Z.dropdown, width: 'min(420px, calc(100vw - 16px))',
                   maxHeight: 'calc(100vh - 140px)', overflowY: 'auto', background: '#0b0f16',
                   border: `1px solid ${T.borderHi}`, boxShadow: '0 12px 32px rgba(0,0,0,.6)', padding: '4px 0' }}>
          <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, padding: '6px 12px' }}>{heading.toUpperCase()} · OR TYPE THE CODE IN ⌕ GO</div>
          {pages.map(p => (
            <button key={p.id} role="menuitem" className="sd-menu-row" onClick={() => { onChange(p.id); setOpen(false) }}
              style={{ display: 'grid', gridTemplateColumns: '52px 1fr auto', gap: 8, width: '100%', textAlign: 'left', padding: '6px 12px',
                       background: p.id === active ? '#121a26' : 'transparent', border: 'none', cursor: 'pointer', alignItems: 'baseline' }}>
              <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: T.amber }}>{p.code}</span>
              <span style={{ minWidth: 0 }}><span style={{ fontSize: 12, color: T.text }}>{p.label}</span>
                <span style={{ display: 'block', fontSize: 10, color: T.dim, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                      title={p.hint}>{p.hint}</span></span>
              {badges[p.id] ? <span style={{ fontSize: 9, color: T.bg, background: T.cyan, padding: '0 5px' }}>{badges[p.id]}</span> : <span />}
            </button>
          ))}
          {extra.length > 0 && <div style={{ borderTop: `1px solid ${T.border}`, margin: '4px 0' }} />}
          {extra.map(x => (
            <button key={x.key} role="menuitem" className="sd-menu-row" onClick={() => { setOpen(false); x.run() }}
              style={{ display: 'grid', gridTemplateColumns: '1fr', width: '100%', textAlign: 'left', padding: '6px 12px',
                       background: 'transparent', border: 'none', cursor: 'pointer' }}>
              <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: T.cyan, letterSpacing: 1 }}>{x.label}</span>
              <span style={{ fontSize: 10, color: T.dim }}>{x.hint}</span>
            </button>
          ))}
        </div>
      )}
    </>
  )
}

/** ARRANGE STRIP: move, add and remove strip pages; stored in the SYNC prefs key strip.order.v1 (every window follows). */
function ArrangeStrip({ strip, pages, onWrite, onClose, desktop }: {
  strip: string[]; pages: MorePage[]; onWrite: (next: readonly string[] | null) => void; onClose: () => void; desktop: boolean
}) {
  const byId = new Map(pages.map(p => [p.id, p]))
  const off = pages.filter(p => !strip.includes(p.id))
  const [pick, setPick] = useState('')
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  const b = (c: string) => ({ fontFamily: T.mono, fontSize: 11, color: c, background: 'transparent', border: `1px solid ${T.border}`,
                              padding: '2px 8px', cursor: 'pointer', minWidth: 30 } as const)
  return (
    <div onMouseDown={onClose} role="dialog" aria-label="Arrange the page strip" data-sd-arrange-strip=""
      style={{ position: 'fixed', inset: 0, zIndex: Z.commandbar, background: 'rgba(2,3,6,.6)', display: 'flex', justifyContent: 'center',
               alignItems: 'flex-start', paddingTop: '8vh' }}>
      <div onMouseDown={e => e.stopPropagation()} className="t-fade-up"
        style={{ width: 'min(520px, 94vw)', maxHeight: '84vh', overflowY: 'auto', background: T.panel, border: `1px solid ${T.borderHi}`,
                 borderTop: `2px solid ${T.cyan}`, boxShadow: '0 24px 80px rgba(0,0,0,.6)', fontFamily: T.mono }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: T.bg, background: T.cyan, padding: '3px 7px' }}>STRIP</span>
          <span style={{ fontFamily: T.display, fontSize: 13, fontWeight: 700, letterSpacing: 1.4, color: T.bright }}>ARRANGE THE PAGE STRIP</span>
          <span style={{ flex: 1 }} />
          <button type="button" onClick={onClose} style={b(T.muted)}>ESC</button>
        </div>
        <div style={{ padding: '6px 14px 2px', fontSize: 11, color: T.muted, lineHeight: 1.5 }}>
          Alt+1 … 0 open the first ten{desktop ? '; ⌘1 … 9 follow the Go menu (the default order)' : ''}. Saved to your settings: every window and the app follow.
        </div>
        <div style={{ padding: '6px 14px' }}>
          {strip.map((id, i) => {
            const p = byId.get(id)
            const d = slotDigit(i)
            return (
              <div key={id} data-sd-strip-row={id} style={{ display: 'grid', gridTemplateColumns: '22px 52px 1fr auto', gap: 8, alignItems: 'center',
                                                          padding: '4px 0', borderBottom: `1px solid ${T.border}` }}>
                <span style={{ fontSize: 10, color: T.dim, textAlign: 'center', border: d ? `1px solid ${T.border}` : 'none' }}>{d ?? ''}</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: T.amber }}>{p?.code ?? id}</span>
                <span style={{ fontSize: 11, color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p?.label ?? ''}</span>
                <span style={{ display: 'flex', gap: 4 }}>
                  <button type="button" className="sd-tap" aria-label={`Move ${p?.code ?? id} left`} disabled={i === 0}
                    onClick={() => onWrite(moveInStrip(strip, id, -1))} style={b(i === 0 ? T.dim : T.cyan)}>↑</button>
                  <button type="button" className="sd-tap" aria-label={`Move ${p?.code ?? id} right`} disabled={i === strip.length - 1}
                    onClick={() => onWrite(moveInStrip(strip, id, 1))} style={b(i === strip.length - 1 ? T.dim : T.cyan)}>↓</button>
                  <button type="button" className="sd-tap" aria-label={`Remove ${p?.code ?? id} from the strip`} disabled={strip.length <= 1}
                    onClick={() => onWrite(removeFromStrip(strip, id))} style={b(T.muted)}>✕</button>
                </span>
              </div>
            )
          })}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '8px 14px 12px' }}>
          <select value={pick} onChange={e => setPick(e.target.value)} aria-label="Page to add"
            style={{ fontFamily: T.mono, fontSize: 11, background: '#080b10', color: T.text, border: `1px solid ${T.border}`, padding: '4px 6px', maxWidth: 260 }}>
            <option value="">add a page…</option>
            {off.map(p => <option key={p.id} value={p.id}>{p.code} · {p.label}</option>)}
          </select>
          <button type="button" className="sd-tap" disabled={!pick || strip.length >= MAX_STRIP}
            onClick={() => { if (pick) { onWrite(addToStrip(strip, pick)); setPick('') } }} style={b(pick ? T.green : T.dim)}>+ ADD</button>
          <span style={{ flex: 1 }} />
          <button type="button" className="sd-tap" disabled={isDefaultStrip(strip)} onClick={() => onWrite(null)} style={b(isDefaultStrip(strip) ? T.dim : T.amber)}>RESET</button>
          <button type="button" className="sd-tap" onClick={onClose} style={{ ...b(T.bg), background: T.cyan, borderColor: T.cyan, fontWeight: 700 }}>DONE</button>
        </div>
      </div>
    </div>
  )
}

function PageStrip({ tabs, pages, active, onChange, desktop, badges }: {
  tabs: { id: string; label: string; badge?: number }[]; pages: MorePage[]; active: string; onChange: (id: string) => void; desktop: boolean
  badges: Record<string, number | undefined>
}) {
  const known = useMemo(() => pages.map(p => p.id), [pages])
  const [strip, writeStrip] = useStripOrder(known)
  const [arranging, setArranging] = useState(false)
  const { offer } = useImportOffer()
  const label = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of pages) m.set(p.id, p.code)
    for (const t of tabs) m.set(t.id, t.label)
    return m
  }, [pages, tabs])
  const menus = useMemo(() => splitMenus(strip, known), [strip, known])
  const byId = useMemo(() => new Map(pages.map(p => [p.id, p])), [pages])
  const research = menus.research.map(id => byId.get(id)).filter((p): p is MorePage => !!p)
  const more = menus.more.map(id => byId.get(id)).filter((p): p is MorePage => !!p)
  // ⌘/Ctrl-click or middle-click on a page tab opens it in a new window (C1-trader-ux-16)
  const open = useCallback((e: ReactMouseEvent, id: string) => {
    if (e.button === 1 || ((e.metaKey || e.ctrlKey) && e.button === 0)) { e.preventDefault(); void newWindow(id); return true }
    return false
  }, [])
  // Alt+1 … 9, Alt+0: the strip's first ten slots, in the owner's order (M37)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.ctrlKey || e.metaKey) return
      const i = slotForDigitCode(e.code)
      if (i < 0) return
      if (strip[i]) { e.preventDefault(); onChange(strip[i]) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [strip, onChange])
  useEffect(() => {
    document.querySelector(`[data-tab="${active}"]`)?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [active])
  const extra = [
    { key: 'arrange', label: '⚙ ARRANGE THE STRIP', hint: 'move, add or remove pages · Alt+1 … 0 follow', run: () => setArranging(true) },
    ...(offer !== 'none' ? [{ key: 'import', label: '⇪ IMPORT SETTINGS', hint: 'watchlist and pins from the old browser terminal', run: () => openSettingsImport() }] : []),
  ]
  return (
    <nav className="sd-pstrip" aria-label="Pages" style={{ display: 'flex', overflowX: 'auto', borderBottom: `1px solid ${T.border}`, background: '#07090d' }}>
      {strip.map((id, i) => {
        const on = id === active
        const key = slotDigit(i)
        const badge = badges[id]
        return (
          <button key={id} data-tab={id} className="sd-pstrip-tab" onClick={e => { if (!open(e, id)) onChange(id) }}
            onAuxClick={e => { open(e, id) }} onMouseDown={e => { if (e.button === 1) e.preventDefault() }}
            title={[byId.get(id)?.code, slotKeyHint(strip, i, desktop), '⌘-click: new window'].filter(Boolean).join(' · ')}
            style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4, padding: '8px 5px', whiteSpace: 'nowrap', flex: '1 0 auto',
                     background: on ? '#0e131c' : 'transparent', border: 'none', cursor: 'pointer',
                     borderBottom: `2px solid ${on ? T.amber : 'transparent'}`, borderRight: `1px solid ${T.border}` }}>
            {key && <span style={{ fontSize: 9, color: on ? T.bg : T.dim, background: on ? T.amber : 'transparent',
                                   border: `1px solid ${on ? T.amber : T.border}`, padding: '0 4px', lineHeight: '14px' }}>{key}</span>}
            <span style={{ fontFamily: T.display, fontSize: 11, fontWeight: 600, letterSpacing: .55,
                           textTransform: 'uppercase', color: on ? T.amber : T.muted }}>{label.get(id) ?? id}</span>
            {badge ? <span style={{ fontSize: 9, color: T.bg, background: T.cyan, padding: '0 5px' }}>{badge}</span> : null}
          </button>
        )
      })}
      <div className="sd-pstrip-end" style={{ position: 'sticky', right: 0, display: 'flex', flex: 'none', background: '#0b0f16' }}>
      {research.length > 0 && <PageMenu title="RESEARCH" heading="Research and legacy pages" pages={research} active={active} onChange={onChange} badges={badges} />}
      {(more.length > 0 || extra.length > 0) && <PageMenu title="MORE" heading="More pages" pages={more} active={active} onChange={onChange} badges={badges} extra={extra} />}
      <WorkspaceMenu active={active} onPage={onChange} />{/* R2 workspaces: saved layouts (lib/workspaces.ts; LAYOUT on GO) */}
      <button className="sd-pstrip-tab" onClick={() => window.dispatchEvent(new Event('suryadhana:command'))} title={`Command bar — type a ticker or function code (/ or ${desktop ? '⌘K' : 'Ctrl+K'})`}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px', flex: 'none',
                 background: '#0b0f16', border: 'none', borderLeft: `1px solid ${T.borderHi}`, cursor: 'pointer' }}>
        <span style={{ fontFamily: T.display, fontSize: 12, fontWeight: 700, letterSpacing: 1.2, color: T.amber }}>⌕ GO</span>
        <span className="sd-h-kbd" style={{ fontSize: 9, color: T.dim, border: `1px solid ${T.border}`, padding: '0 4px', lineHeight: '14px' }}>/</span>
      </button>
      </div>
      {arranging && <ArrangeStrip strip={strip} pages={pages} onWrite={writeStrip} onClose={() => setArranging(false)} desktop={desktop} />}
    </nav>
  )
}

// ── header ────────────────────────────────────────────────────────────────────

interface Props {
  onRefresh: () => void
  refreshing: boolean
  totalStocks: number
  latestDate?: string
  activeTab: string
  /** labels of the default strip pages (page.tsx tabList); a page the owner adds shows its code */
  tabs: { id: string; label: string; badge?: number }[]
  /** every page (COMMAND_PAGES): the strip, RESEARCH ▾ and MORE ▾ are cut from these */
  pages: MorePage[]
  /** counts shown beside a page wherever it sits (EQS active filters, PIPE watchlist) */
  badges?: Record<string, number | undefined>
  onTabChange: (id: string) => void
}

function Light({ name, ok, detail, onClick }: { name: string; ok: boolean | null; detail?: string; onClick?: () => void }) {
  const c = ok === true ? T.green : ok === false ? T.red : T.dim
  return (
    <span title={detail || name} role={onClick ? 'button' : undefined} onClick={onClick}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10, cursor: onClick ? 'pointer' : 'default',
                   letterSpacing: 1.1, color: ok === false ? T.red : T.muted }}>
      <span style={{ width: 6, height: 6, borderRadius: 6, background: c, boxShadow: ok ? `0 0 6px ${c}` : 'none' }} />
      {name}
    </span>
  )
}

/**
 * The ICICI light (P4, UI half). Its colour is data-service's own Breeze session, as before. While it is red the
 * tooltip says WHY, from ui-api's connection-status error_kind (lib/iciciStatus.ts): an ICICI network outage reads
 * 'ICICI unreachable (network) — not a login problem' instead of asking for a login; 'expired' keeps 'send /login'.
 * That status is read only while the light is red: once on the edge, then every 2 min (10 min hidden); ui-api serves
 * it from its probe cache.
 */
function IciciLight({ connected, provider, known }: { connected: boolean; provider: string | null; known: boolean }) {
  const [status, setStatus] = useState<unknown>(null)
  const linkDown = useShellState().link === 'down'
  const hidden = useDocumentHidden()
  const want = known && !connected && !linkDown
  const wantRef = useRef(want)
  wantRef.current = want
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const read = useCallback(() => {
    if (!wantRef.current) return
    getICICIConnectionStatus()
      .then(r => { if (alive.current) setStatus({ connected: r.data?.connected === true, error_kind: r.data?.error_kind,
                                                   needs_api_credentials: r.data?.needs_api_credentials === true }) })
      .catch(() => { if (alive.current) setStatus(null) })
  }, [])
  useEffect(() => { if (want) read(); else setStatus(null) }, [want, read])
  usePolling(read, hidden ? 600_000 : 120_000)
  return (
    <Light name="ICICI" ok={connected} detail={iciciLightTitle(connected, provider, status)}
           onClick={connected ? undefined : () => goToPage('broker')} />
  )
}

export function MarketCommandHeader({ onRefresh, refreshing, totalStocks, latestDate, activeTab, tabs, pages, badges = {}, onTabChange }: Props) {
  const { dataServiceStatus: ds } = useDataServiceStatus()
  const { desktop } = useShellState()
  // pages outside the strip show their function code (WRAP, MOV…): long labels crowd the header row
  const page = tabs.find(t => t.id === activeTab)?.label ?? pages.find(m => m.id === activeTab)?.code ?? activeTab
  return (
    <header data-sd-header={desktop ? 'desktop' : 'browser'}
      style={{ position: 'sticky', top: 'var(--shell-top, 0px)', zIndex: Z.header, background: T.bg, fontFamily: T.mono }}>
      <div className="sd-row1" data-sd-row1 style={{ height: desktop ? 36 : 44, display: 'flex', alignItems: 'center', borderBottom: `1px solid ${T.border}`,
                                 background: '#07090d', overflow: 'hidden', whiteSpace: 'nowrap' }}>
        {!desktop && (
          <div className="sd-h-brand" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '0 16px', height: '100%', flex: '0 1 auto', minWidth: 0 }}>
            <span style={{ fontFamily: T.display, fontWeight: 700, letterSpacing: 2, color: T.amber, fontSize: 14, whiteSpace: 'nowrap',
                           overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 }}>
              ◉ SURYADHANA <span style={{ color: T.dim }}>▸</span> <span style={{ color: T.bright }}>{page.toUpperCase()}</span>
            </span>
            <span className="t-hide-xl" style={{ fontSize: 10, color: T.dim, letterSpacing: 1, whiteSpace: 'nowrap' }}>
              {totalStocks ? `${totalStocks.toLocaleString('en-IN')} NSE` : ''}{latestDate ? ` · DATA ${latestDate}` : ''}
            </span>
          </div>
        )}
        <NiftyLive />
        <span style={{ flex: 1, minWidth: 0 }} />
        <div className="sd-h-lights" style={{ display: 'flex', gap: 12, padding: '0 14px', borderLeft: `1px solid ${T.border}`, height: '100%', alignItems: 'center', flex: 'none' }}>
          {!desktop && <>
            <Light name="DATA" ok={ds.health === 'ok' ? true : ds.health === 'error' ? false : null} detail={`data-service: ${ds.health}`} />
            <span className="t-hide-md"><Light name="DB" ok={ds.ready} detail="DuckDB ready" /></span>
          </>}
          {/* risk cockpit (O-F3, SPEC §3): STAND DOWN chip after acknowledge + amber DISCIPLINE pre-stage;
              T-17 net Δ/Θ of the paper book on OMON/OSTR only */}
          <DisciplineHeaderChips activeTab={activeTab} />
          <IciciLight connected={ds.connected} provider={ds.provider} known={ds.lastChecked != null} />
          {/* terminal v2 PLAN 1.4: DATA n STALE (amber + red + gaps of the catalogued datasets) → SYS › DATA */}
          <DataStaleChip />
          <BrokerChip />
        </div>
        {!desktop && <HeaderClock />}
        <div className="sd-h-actions" style={{ padding: '0 12px', borderLeft: `1px solid ${T.border}`, height: '100%', display: 'flex', alignItems: 'center', gap: 8, flex: 'none' }}>
          <AlertsBell />
          <UpdateDataButton refreshing={refreshing} onConfirm={onRefresh} />
        </div>
      </div>
      <MacroTape />
      <PageStrip tabs={tabs} pages={pages} active={activeTab} onChange={onTabChange} desktop={desktop} badges={badges} />
    </header>
  )
}

// ── UPDATE DATA (C1-trader-ux-12) ───────────────────────────────────────────────

/** IST minutes in the EOD pipeline window (18:30–21:15), when data-service is busy with the nightly jobs. */
export function inEodWindow(epochMs: number): boolean {
  const m = istParts(epochMs).minutes
  return m >= 18 * 60 + 30 && m < 21 * 60 + 15
}

/**
 * The header's universe-wide download (POST /api/dashboard/refresh {universe nse_1500, years 5}). It used to be a
 * bare '↻ REFRESH' next to page-level '↻ REFRESH' buttons that only reload a page, so it now says what it is and
 * asks first, stating scope and duration. While a download runs, the button just reopens the progress panel.
 * Same request as before once confirmed.
 */
function UpdateDataButton({ refreshing, onConfirm }: { refreshing: boolean; onConfirm: () => void }) {
  const [ask, setAsk] = useState(false)
  // O-F5a (D-BOOT): while DuckDB is READ-ONLY the download would 503 — say so and disable START instead
  const readOnly = useUpstreamSnapshot().state === 'readonly'
  // inside the EOD window START DOWNLOAD needs a second, explicit click (CT-04)
  const [armed, setArmed] = useState(false)
  useEffect(() => { if (!ask) setArmed(false) }, [ask])
  const [at, setAt] = useState<{ top: number; right: number }>({ top: 0, right: 0 })
  const btn = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!ask) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); setAsk(false) } }
    const onDown = (e: MouseEvent) => { if (!(e.target as HTMLElement).closest?.('[data-update-data]')) setAsk(false) }
    window.addEventListener('keydown', onKey)
    window.addEventListener('mousedown', onDown)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('mousedown', onDown) }
  }, [ask])
  const click = () => {
    if (refreshing) { onConfirm(); return }        // a download is running: show its progress panel
    const r = btn.current?.getBoundingClientRect()
    if (r) setAt({ top: r.bottom + 6, right: Math.max(8, window.innerWidth - r.right) })
    setAsk(a => !a)
  }
  const eod = ask && inEodWindow(Date.now())
  return (
    <>
      <button ref={btn} data-update-data onClick={click} aria-haspopup="dialog" aria-expanded={ask}
        title={refreshing ? 'A data download is running: show its progress' : 'Download missing daily prices for the 1,500-stock NSE universe (asks first)'}
        style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.2, color: refreshing ? T.muted : T.amber, whiteSpace: 'nowrap',
                 background: 'transparent', border: `1px solid ${ask ? T.amber : T.border}`, padding: '4px 9px', cursor: refreshing ? 'wait' : 'pointer' }}>
        <span className={refreshing ? 't-pulse' : undefined}>⤓</span> <span className="sd-h-word">{refreshing ? 'UPDATING DATA…' : 'UPDATE DATA'}</span>
      </button>
      {ask && (
        <div data-update-data role="dialog" aria-label="Update data"
          style={{ position: 'fixed', top: at.top, right: at.right, zIndex: Z.dropdown, width: 380, background: '#0b0f16',
                   border: `1px solid ${T.borderHi}`, borderTop: `2px solid ${T.amber}`, boxShadow: '0 12px 32px rgba(0,0,0,.6)',
                   padding: '10px 12px', fontFamily: T.mono, whiteSpace: 'normal' }}>
          <div style={{ fontFamily: T.display, fontSize: 11, fontWeight: 700, letterSpacing: 1.4, color: T.amber }}>
            UPDATE DATA · 1,500 NSE STOCKS · UP TO 5 YEARS
          </div>
          <p style={{ margin: '8px 0 0', fontSize: 11, lineHeight: 1.5, color: T.text }}>
            Downloads the missing daily prices (OHLCV) for the whole 1,500-stock universe from Yahoo Finance, up to five
            years back. Only days that are not in the database yet are fetched. It runs in data-service for several
            minutes; progress shows under the header.
          </p>
          <p style={{ margin: '6px 0 0', fontSize: 11, lineHeight: 1.5, color: T.muted }}>
            To reload just this page&apos;s numbers, use the page&apos;s own ↻ REFRESH instead.
          </p>
          {eod && (
            <p style={{ margin: '6px 0 0', fontSize: 11, lineHeight: 1.5, color: T.amber }}>
              The EOD pipeline runs 18:30–21:15 IST: a download now competes with it for data-service.
            </p>
          )}
          {readOnly && (
            <p style={{ margin: '6px 0 0', fontSize: 11, lineHeight: 1.5, color: T.amber }}>
              DB READ-ONLY: the store holds a write lock, so ingest is paused and this download cannot run.
              It re-enables by itself when the lock clears (the header strip shows the state).
            </p>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 10, justifyContent: 'flex-end' }}>
            {/* focus starts on CANCEL: a reflexive Enter / Space never starts a universe-wide download (R-UI-SHELL-12) */}
            <button autoFocus onClick={() => setAsk(false)}
              style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.2, color: T.muted, background: 'transparent',
                       border: `1px solid ${T.border}`, padding: '4px 10px', cursor: 'pointer' }}>CANCEL</button>
            <button data-update-start disabled={readOnly} onClick={() => {
                if (readOnly) return
                if (eod && !armed) { setArmed(true); return }
                setAsk(false); onConfirm()
              }}
              title={readOnly ? 'DuckDB is read-only: ingest would fail until the lock clears'
                : eod && !armed ? 'The EOD pipeline is running: click again to start anyway' : undefined}
              style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: 1.2, color: T.bg,
                       background: readOnly ? T.muted : T.amber, border: `1px solid ${readOnly ? T.muted : T.amber}`,
                       padding: '4px 10px', cursor: readOnly ? 'not-allowed' : 'pointer' }}>
              {readOnly ? 'DB READ-ONLY' : eod ? (armed ? 'CONFIRM: START DURING EOD' : 'START ANYWAY…') : 'START DOWNLOAD'}</button>
          </div>
        </div>
      )}
    </>
  )
}
