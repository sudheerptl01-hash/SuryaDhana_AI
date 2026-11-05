'use client'

/**
 * Command bar — Bloomberg's <GO> line. Open with "/" or Ctrl/⌘+K anywhere outside a text box.
 *
 *   MKT  DESK  BT  PORT …     jump to a page by its function code (also its name: "markets", "backtest")
 *   TCS                       open the stock (chart, levels, ☆ PIN, + WATCHLIST)
 *   TCS TV | TCS YF           open the stock on TradingView / Yahoo Finance
 *   TCS W                     add / remove TCS on the watchlist
 *   TCS OMON · TCS DEAL       the stock's option chain · its block and bulk deals (typing a ticker lists these)
 *   NEWS                      open the News Catalyst Terminal
 *   GP · TOP · MOST · BACK    Bloomberg mnemonics (lib/goAliases.ts): chart studio, news, movers, history back;
 *                             NIFTY / BANKNIFTY offer the index option chain. Mnemonics and exact page codes rank
 *                             above every ticker match (GP never opens GPIL, MOST never the ticker MOST)
 *
 * Arrow keys pick, Enter runs, Shift+Enter (or Shift+click) opens the pick in a NEW WINDOW (contract K4), Esc
 * closes. Typing a ticker character anywhere outside a text box opens the bar seeded with it (type-to-GO,
 * lib/shortcuts.ts). Recent stocks are remembered on this browser. The ? help card teaches the host's keys
 * (⌘ in SuryaDhana.app, Alt in a browser).
 */
import { Z } from '@/lib/z'
import { openTicker } from '@/lib/openTicker'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getSymbols, type SymbolEntry } from '@/lib/api'
import { useWatchlist } from '@/context/AppContext'
import { equityInstrument, tradingViewUrl, yahooUrl } from '@/components/terminal/ChartActions'
import { T } from '@/components/terminal'
import { COMP_KEY, DEAL_KEY, OMON_KEY } from '@/lib/pageKeys'
import { newWindow, openExternal } from '@/lib/platform'
import { setGoldSubInUrl } from '@/lib/gold/prefs'
import { setSubInUrl } from '@/components/terminal/source'
import { GOLD_SUBS, type GoldSub } from '@/lib/gold/types'
import { helpKeys, onMac, typeToGoChar } from '@/lib/shortcuts'
import { useShellState } from '@/components/shell/ShellState'
import { aliasTargets, canGoBack, mergeRanked, sanitizeSymbolRows, type AliasTarget } from '@/lib/goAliases'

export interface CommandPage { id: string; code: string; label: string; hint: string }

type Item =
  | { kind: 'page'; key: string; code: string; label: string; hint: string; id: string }
  | { kind: 'news'; key: string; code: string; label: string; hint: string }
  | { kind: 'help'; key: string; code: string; label: string; hint: string }
  | { kind: 'back'; key: string; code: string; label: string; hint: string }
  | { kind: 'comp'; key: string; code: string; label: string; hint: string; syms: string[] }
  | { kind: 'omon'; key: string; code: string; label: string; hint: string; sym: string }
  | { kind: 'deal'; key: string; code: string; label: string; hint: string; sym: string }
  | { kind: 'stock'; key: string; code: string; label: string; hint: string; t: string; action: Action }

type Action = 'open' | 'tv' | 'yf' | 'watch' | 'des' | 'fa' | 'ern' | 'hp' | 'seag'
const ACTIONS: Record<string, Action> = { DES: 'des', GP: 'open', TV: 'tv', YF: 'yf', Y: 'yf', W: 'watch', WL: 'watch', FA: 'fa', ERN: 'ern', HP: 'hp', SEAG: 'seag' }
const ACTION_LABEL: Record<Action, string> = { open: 'Open stock', tv: 'Open on TradingView ↗', yf: 'Open on Yahoo Finance ↗', watch: 'Toggle watchlist',
  des: 'Profile (DES)', fa: 'Quarterly financials (FA)', ern: 'Results history (ERN)', hp: 'Historical prices (HP)', seag: 'Seasonality by month (SEAG)' }
const RECENT_KEY = 'suryadhana.cmd.recent.v1'
const HISTORY_KEY = 'suryadhana.cmd.history.v1'

/** Recent stocks, newest first. Only strings survive (a corrupt or foreign value used to crash the GO list, R-UI-SHELL-04). */
function loadRecent(): string[] {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]')
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string' && x !== '').slice(0, 8) : []
  } catch { return [] }
}

/** Raw GO inputs, newest first (Bloomberg's command recall). Seeded once from the recent-stocks key. */
function loadHistory(): string[] {
  try {
    const h = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
    if (Array.isArray(h) && h.length) return h.filter((x): x is string => typeof x === 'string').slice(0, 20)
  } catch { /* storage unavailable */ }
  return loadRecent()
}

function pushHistory(entry: string): string[] {
  const next = [entry, ...loadHistory().filter(x => x !== entry)].slice(0, 20)
  try { localStorage.setItem(HISTORY_KEY, JSON.stringify(next)) } catch { /* storage unavailable */ }
  return next
}

/** True while a dialog other than the stock window is open (help card, News Terminal, the GO bar itself, popovers). */
function otherDialogOpen(): boolean {
  try {
    return !!document.querySelector('[role="dialog"]:not([data-sd-stock-window])')
  } catch {
    return false
  }
}

export function CommandBar({ pages, onPage, onTicker, currentTab }: {
  pages: CommandPage[]; onPage: (id: string) => void; onTicker: (t: string) => void
  /** The page this window shows: a stock opened with Shift+Enter gets a new window on this page. */
  currentTab?: string
}) {
  const { desktop } = useShellState()
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const [symbols, setSymbols] = useState<SymbolEntry[] | null>(null)
  const [recent, setRecent] = useState<string[]>([])
  const [hist, setHist] = useState<string[]>([])
  const [help, setHelp] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const histIdx = useRef(-1)            // −1 = not recalling; 0 = newest history entry
  const recalled = useRef('')           // what recall last put in the input ("unchanged" check)
  const { isWatched, addToWatchlist, removeFromWatchlist } = useWatchlist()

  const show = useCallback((seed?: unknown) => {
    setOpen(true); setQ(typeof seed === 'string' ? seed : ''); setSel(0); setRecent(loadRecent()); setHist(loadHistory())
    histIdx.current = -1; recalled.current = ''
  }, [])
  const helpRef = useRef(help)
  helpRef.current = help
  const openRef = useRef(open)
  openRef.current = open

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      const typing = el?.tagName === 'INPUT' || el?.tagName === 'TEXTAREA' || el?.tagName === 'SELECT' || el?.isContentEditable
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); show(); return }
      if (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) { e.preventDefault(); show(); return }
      if (e.key === '?' && !typing) { e.preventDefault(); setHelp(h => !h); return }
      if (e.key === 'Escape') {
        // the help card is on top: Esc closes it, and only it (the stock window under it stays open)
        if (helpRef.current) { e.preventDefault(); setHelp(false) }
        return
      }
      // type-to-GO (C1-trader-ux-09): a ticker character outside any text box opens GO seeded with it
      const ch = typeToGoChar(e, { typing: !!typing, blocked: openRef.current || helpRef.current || otherDialogOpen() })
      if (ch) { e.preventDefault(); show(ch) }
    }
    // 'suryadhana:command' (the GO buttons, the app's Go menu, a retried GO boundary): a string detail seeds the input
    const onCommand = (e: Event) => show((e as CustomEvent<unknown>).detail)
    window.addEventListener('keydown', onKey)
    window.addEventListener('suryadhana:command', onCommand)
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('suryadhana:command', onCommand) }
  }, [show])

  useEffect(() => {
    if (!open) return
    const el = inputRef.current
    el?.focus()
    // a type-to-GO seed: caret after it, so the next keystroke continues the ticker
    try { const n = el?.value.length ?? 0; el?.setSelectionRange(n, n) } catch { /* not a text input */ }
  }, [open])
  useEffect(() => {
    // rows without a ticker are dropped and a missing name reads '' (one bad row used to throw inside the items memo
    // and take GO down for the window, R-UI-SHELL-04)
    if (open && !symbols) {
      getSymbols()
        .then(r => setSymbols(sanitizeSymbolRows<SymbolEntry>(r.data?.data)))
        .catch(() => setSymbols([]))
    }
  }, [open, symbols])

  const bySymbol = useMemo(() => new Map((symbols ?? []).map(s => [s.t, s])), [symbols])

  const items = useMemo<Item[]>(() => {
    const raw = q.trim().toUpperCase()
    const [head, ...rest] = raw.split(/\s+/)
    const action: Action = ACTIONS[rest.join(' ')] ?? 'open'
    const stockItem = (t: string, a: Action = action): Item => {
      const s = bySymbol.get(t)
      const suffix: Record<Action, string> = { open: '', tv: ' TV', yf: ' YF', watch: ' W', des: ' DES', fa: ' FA', ern: ' ERN', hp: ' HP', seag: ' SEAG' }
      return { kind: 'stock', key: `s:${t}:${a}`, code: t + suffix[a], t, action: a, label: s?.n || t,
               hint: a === 'open' ? [s?.s, s?.c].filter(Boolean).join(' · ') : ACTION_LABEL[a] }
    }
    const pageItems: Item[] = pages.map(p => ({ kind: 'page', key: `p:${p.id}`, code: p.code, label: p.label, hint: p.hint, id: p.id }))
    const news: Item = { kind: 'news', key: 'news', code: 'NEWS', label: 'News Catalyst Terminal', hint: 'today\'s scanner picks and headlines' }
    const helpItem: Item = { kind: 'help', key: 'help', code: 'HELP', label: 'Codes and keyboard shortcuts', hint: 'or press ?' }
    if (!raw) {
      return [...recent.map(t => stockItem(t, 'open')), ...pageItems, news, helpItem]
    }
    const omonItem = (sym: string): Item => ({ kind: 'omon', key: `omon:${sym}`, code: `${sym} OMON`, label: `Option chain · ${sym}`, hint: 'end of day · OI, IV, PCR, max pain', sym })
    const dealItem = (sym: string): Item => ({ kind: 'deal', key: `deal:${sym}`, code: `${sym} DEAL`, label: `Block & bulk deals · ${sym}`, hint: 'last 30 days, netted per client', sym })
    // TICKER FUNCTION (Bloomberg order): TCS OMON, TCS DEAL
    if (rest.length === 1 && rest[0] === 'OMON' && head !== 'OMON') return [omonItem(head)]
    if (rest.length === 1 && rest[0] === 'DEAL') return [dealItem(head)]
    if (head === 'DEAL' && rest.length) return [dealItem(rest[0])]
    if (head === 'OMON' && rest.length) {
      return [{ kind: 'omon', key: 'omon', code: 'OMON', label: `Option chain · ${rest[0]}`, hint: 'end of day · OI, IV, PCR, max pain', sym: rest[0] }]
    }
    if (head === 'COMP' && rest.length) {
      const list = rest.filter(Boolean).slice(0, 8)
      return [{ kind: 'comp', key: 'comp', code: 'COMP', label: `Compare ${list.join(', ')}`, hint: 'vs NIFTY 50 · rebased to 100', syms: list }]
    }
    // Bloomberg mnemonics (GP, TOP, MOST, BACK…) and exact page codes rank above every ticker match (CT-09)
    const aliasItem = (a: AliasTarget): Item | null => {
      if (a.kind === 'news') return news
      if (a.kind === 'omon') return omonItem(a.sym)
      if (a.kind === 'back') {
        const st = typeof window !== 'undefined' ? window.history.state : null
        return { kind: 'back', key: 'back', code: 'BACK', label: 'Back',
                 hint: canGoBack(st) ? `previous page or stock window${desktop ? ' (⌘[)' : ''}` : 'nothing to go back to in this window' }
      }
      const item = pageItems.find(i => i.kind === 'page' && i.id === a.id) ?? null
      if (item && a.kind === 'page' && 'sub' in a && typeof a.sub === 'string' && (GOLD_SUBS as readonly string[]).includes(a.sub)) {
        try { setGoldSubInUrl(a.sub as GoldSub) } catch { /* no-op */ }
      }
      // terminal v2 sub-views (VOL → DERV › VOL, DATA → SYS › DATA): the same `?sub=` hand-off for any other page
      if (item && a.kind === 'page' && 'view' in a && typeof a.view === 'string') {
        try { setSubInUrl(a.view) } catch { /* no-op */ }
      }
      return item
    }
    const aliases: Item[] = rest.length ? [] : aliasTargets(raw).map(aliasItem).filter((i): i is Item => i !== null)
    let exactPages: Item[] = []
    let scoredPages: Item[] = []
    if (!rest.length) {
      // C1 flaw #1: startsWith(code|label) hid pages — 'gold' never surfaced MCXG, 'rollover'
      // found nothing. Substring across code, label AND hint, ranked: exact code, code prefix,
      // label prefix, then any substring match.
      const score = (i: { code: string; label: string; hint?: string }) =>
        i.code === raw ? 4 : i.code.startsWith(raw) ? 3 : i.label.toUpperCase().startsWith(raw) ? 2
        : (i.code.includes(raw) || i.label.toUpperCase().includes(raw) || (i.hint ?? '').toUpperCase().includes(raw)) ? 1 : 0
      const pg = [...pageItems, news, helpItem].filter(i => score(i) > 0).sort((a, b) => score(b) - score(a))
      exactPages = pg.filter(i => i.code === raw)
      scoredPages = pg.filter(i => i.code !== raw)
    }
    let tickerLead: Item[] = []
    let tickerRest: Item[] = []
    if (symbols) {
      const exact = bySymbol.get(head)
      const pre = symbols.filter(s => s.t !== head && s.t.startsWith(head)).slice(0, 8)
      const name = rest.length ? [] : symbols.filter(s => !s.t.startsWith(head) && s.n.toUpperCase().includes(raw)).slice(0, 8)
      // a bare ticker also lists what you can do with it
      if (exact) {
        tickerLead = [stockItem(exact.t), ...(rest.length ? [] : [stockItem(exact.t, 'des'), stockItem(exact.t, 'fa'), stockItem(exact.t, 'ern'),
          stockItem(exact.t, 'hp'), stockItem(exact.t, 'seag'), omonItem(exact.t), dealItem(exact.t), stockItem(exact.t, 'tv'), stockItem(exact.t, 'watch')])]
      }
      tickerRest = [...pre.map(s => stockItem(s.t)), ...name.map(s => stockItem(s.t, 'open'))]
    }
    const out = mergeRanked([aliases, exactPages, tickerLead, scoredPages, tickerRest])
    // Anything NSE-shaped that is not in the 1,500-stock directory still opens (movers can sit outside it)
    if (symbols && !out.length && /^[A-Z0-9&-]{2,20}$/.test(head)) out.push(stockItem(head))
    return out.slice(0, 14)
  }, [q, pages, symbols, bySymbol, recent, desktop])

  useEffect(() => { setSel(0) }, [q])
  useEffect(() => {
    listRef.current?.querySelector<HTMLElement>(`[data-i="${sel}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [sel])

  const run = useCallback((it: Item | undefined, inNewWindow = false) => {
    if (!it) return
    // the single execution path records every command: the raw input, or the picked code when input is empty
    setHist(pushHistory(q.trim().toUpperCase() || it.code))
    setOpen(false)
    // BACK <GO>: history back, only while the entry behind is a terminal screen (never out of the terminal)
    if (it.kind === 'back') { if (canGoBack(window.history.state)) window.history.back(); return }
    if (inNewWindow) {
      // Shift+Enter / Shift+click (contract K4): pages and stocks open in another terminal window; the per-page
      // hand-off keys (OMON / DEAL / COMP) are written first, so the new window opens on that selection
      if (it.kind === 'page') return void newWindow(it.id)
      if (it.kind === 'stock' && it.action === 'open') return void newWindow(currentTab, it.t)
      if (it.kind === 'omon') { try { localStorage.setItem(OMON_KEY, it.sym) } catch { /* storage blocked */ } return void newWindow('options') }
      if (it.kind === 'deal') { try { localStorage.setItem(DEAL_KEY, it.sym) } catch { /* storage blocked */ } return void newWindow('deals') }
      if (it.kind === 'comp') {
        try { localStorage.setItem(COMP_KEY, JSON.stringify({ syms: it.syms, period: '1y' })) } catch { /* storage blocked */ }
        return void newWindow('compare')
      }
    }
    if (it.kind === 'page') return onPage(it.id)
    if (it.kind === 'news') return void window.dispatchEvent(new Event('suryadhana:open-news'))
    if (it.kind === 'help') return void setHelp(true)
    if (it.kind === 'omon') {
      try { localStorage.setItem(OMON_KEY, it.sym) } catch { /* storage blocked */ }
      window.dispatchEvent(new Event('suryadhana:omon'))
      return onPage('options')
    }
    if (it.kind === 'deal') {
      try { localStorage.setItem(DEAL_KEY, it.sym) } catch { /* storage blocked */ }
      window.dispatchEvent(new Event('suryadhana:deal'))
      return onPage('deals')
    }
    if (it.kind === 'comp') {
      try { localStorage.setItem(COMP_KEY, JSON.stringify({ syms: it.syms, period: '1y' })) } catch { /* storage blocked */ }
      window.dispatchEvent(new Event('suryadhana:comp'))       // reload if Compare is already open
      return onPage('compare')
    }
    const next = [it.t, ...loadRecent().filter(t => t !== it.t)].slice(0, 8)
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)) } catch { /* storage unavailable */ }
    const inst = equityInstrument(it.t)
    if (it.action === 'tv') openExternal(tradingViewUrl(inst.tv))          // browser: window.open(url, '_blank', 'noopener')
    else if (it.action === 'yf') openExternal(yahooUrl(inst.yahoo))
    else if (it.action === 'watch') (isWatched(it.t) ? removeFromWatchlist(it.t) : addToWatchlist(it.t))
    else if (it.action === 'des') openTicker(it.t, 'profile')
    else if (it.action === 'fa' || it.action === 'ern' || it.action === 'hp' || it.action === 'seag') openTicker(it.t, it.action)
    else onTicker(it.t)
  }, [q, onPage, onTicker, isWatched, addToWatchlist, removeFromWatchlist, currentTab])

  if (help && !open) return <HelpCard pages={pages} desktop={desktop} onClose={() => setHelp(false)} onPage={id => { setHelp(false); onPage(id) }} />
  if (!open) return null
  const kindColor = (i: Item) => (i.kind === 'stock' ? T.amber : i.kind === 'news' || i.kind === 'help' || i.kind === 'back' ? T.violet : i.kind === 'comp' || i.kind === 'omon' ? T.green : T.cyan)
  return (
    <div onMouseDown={() => setOpen(false)} role="dialog" aria-label="Command bar"
      style={{ position: 'fixed', inset: 0, zIndex: Z.commandbar, background: 'rgba(2,3,6,.72)', backdropFilter: 'blur(2px)',
               display: 'flex', justifyContent: 'center', alignItems: 'flex-start', paddingTop: '12vh' }}>
      <div onMouseDown={e => e.stopPropagation()} className="t-fade-up"
        style={{ width: 'min(680px, 94vw)', background: T.panel, border: `1px solid ${T.borderHi}`,
                 borderTop: `2px solid ${T.amber}`, boxShadow: '0 24px 80px rgba(0,0,0,.6)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
          <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: T.bg, background: T.amber, padding: '3px 7px' }}>GO</span>
          <input ref={inputRef} value={q} spellCheck={false}
            onChange={e => { if (e.target.value !== recalled.current) { histIdx.current = -1; recalled.current = '' } setQ(e.target.value) }}
            placeholder="Ticker, company or code  ·  TCS  ·  TCS TV  ·  MKT"
            onKeyDown={e => {
              // ↑/↓ recall previous commands — only when the input is empty, still holds a recalled
              // command, or matches nothing; otherwise the arrows keep navigating the result list.
              const recallMode = q === '' || q === recalled.current || items.length === 0
              if (e.key === 'Escape') { e.preventDefault(); setOpen(false) }
              else if (e.key === 'ArrowUp' && recallMode && hist.length) {
                e.preventDefault()
                const ni = Math.min(histIdx.current + 1, hist.length - 1)
                histIdx.current = ni; recalled.current = hist[ni]; setQ(hist[ni])
              }
              else if (e.key === 'ArrowDown' && histIdx.current >= 0 && recallMode) {
                e.preventDefault()
                const ni = histIdx.current - 1
                histIdx.current = ni
                const v = ni >= 0 ? hist[ni] : ''
                recalled.current = v; setQ(v)
              }
              else if (e.key === 'ArrowDown') { e.preventDefault(); setSel(s => Math.min(s + 1, items.length - 1)) }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setSel(s => Math.max(s - 1, 0)) }
              else if (e.key === 'Enter') { e.preventDefault(); run(items[sel], e.shiftKey) }
            }}
            style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: T.bright,
                     fontFamily: T.mono, fontSize: 16, letterSpacing: .5, textTransform: q ? 'uppercase' : 'none' }} />
          <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim }}>ESC</span>
        </div>
        {!q.trim() && hist.length > 0 && (
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', padding: '8px 14px 0' }}>
            <span style={{ fontFamily: T.display, fontSize: 9, letterSpacing: 1.6, color: T.dim, textTransform: 'uppercase' }}>Recall</span>
            {hist.slice(0, 8).map(h => (
              <button key={h} onMouseDown={e => { e.preventDefault(); e.stopPropagation(); histIdx.current = -1; recalled.current = h; setQ(h) }}
                title={`Fill "${h}" (↑ cycles history)`}
                style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1, color: T.cyan, background: 'none',
                         border: `1px solid ${T.border}`, padding: '2px 7px', cursor: 'pointer' }}>{h}</button>
            ))}
          </div>
        )}
        <div ref={listRef} style={{ maxHeight: '52vh', overflowY: 'auto' }}>
          {!q.trim() && recent.length > 0 && <Section>Recent</Section>}
          {items.map((it, i) => (
            <div key={it.key}>
              {!q.trim() && i === recent.length && <Section>Functions</Section>}
              <div data-i={i} onMouseEnter={() => setSel(i)} onMouseDown={e => run(it, e.shiftKey)}
                style={{ display: 'grid', gridTemplateColumns: '120px 1fr auto', gap: 12, alignItems: 'center',
                         padding: '8px 14px', cursor: 'pointer', borderLeft: `2px solid ${i === sel ? kindColor(it) : 'transparent'}`,
                         background: i === sel ? T.panel3 : 'transparent' }}>
                <span style={{ fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: kindColor(it),
                               overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.code}</span>
                <span style={{ fontSize: 12, color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.label}</span>
                <span style={{ fontSize: 10, color: T.muted, whiteSpace: 'nowrap' }}>{it.hint}</span>
              </div>
            </div>
          ))}
          {q.trim() && items.length === 0 && (
            <div style={{ padding: '18px 14px', fontSize: 12, color: T.muted }}>
              {symbols ? 'No match. Try a ticker (TCS), a company name (tata) or a code (MKT).' : 'Loading symbols…'}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', padding: '7px 14px', borderTop: `1px solid ${T.border}`,
                      fontFamily: T.mono, fontSize: 10, color: T.dim }}>
          <span>↑↓ PICK · ↑ RECALL · ↵ GO · ⇧↵ NEW WINDOW</span>
          <span>‹TICKER› DES · FA · ERN · HP · SEAG · OMON · DEAL · TV · YF · W · VOL · DRVR · DATA</span>
          <span style={{ flex: 1 }} />
          <span>{symbols ? `${symbols.length.toLocaleString('en-IN')} symbols` : '…'}</span>
        </div>
      </div>
    </div>
  )
}

function Section({ children }: { children: string }) {
  return (
    <div style={{ padding: '8px 14px 4px', fontFamily: T.display, fontSize: 10, letterSpacing: 1.6, color: T.dim,
                  textTransform: 'uppercase' }}>{children}</div>
  )
}

function HelpCard({ pages, desktop, onClose, onPage }: { pages: CommandPage[]; desktop: boolean; onClose: () => void; onPage: (id: string) => void }) {
  const keys = helpKeys(desktop, useMemo(onMac, []))
  return (
    <div onMouseDown={onClose} role="dialog" aria-label="Help"
      style={{ position: 'fixed', inset: 0, zIndex: Z.commandbar, background: 'rgba(2,3,6,.72)', display: 'flex', justifyContent: 'center',
               alignItems: 'flex-start', paddingTop: '8vh' }}>
      <div onMouseDown={e => e.stopPropagation()} className="t-fade-up"
        style={{ width: 'min(920px, 94vw)', background: T.panel, border: `1px solid ${T.borderHi}`, borderTop: `2px solid ${T.violet}`,
                 boxShadow: '0 24px 80px rgba(0,0,0,.6)', maxHeight: '84vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderBottom: `1px solid ${T.border}` }}>
          <span style={{ fontFamily: T.mono, fontSize: 11, fontWeight: 700, color: T.bg, background: T.violet, padding: '3px 7px' }}>HELP</span>
          <span style={{ fontFamily: T.display, fontSize: 15, fontWeight: 700, letterSpacing: 1.5, color: T.bright }}>SURYADHANA TERMINAL</span>
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim, cursor: 'pointer' }} onClick={onClose}>ESC</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0 }}>
          <div style={{ padding: '10px 16px', borderRight: `1px solid ${T.border}` }}>
            <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.6, color: T.muted, marginBottom: 6 }}>FUNCTION CODES · CLICK TO OPEN</div>
            {pages.map(p => (
              <div key={p.id} onClick={() => onPage(p.id)} className="nt-row"
                style={{ display: 'grid', gridTemplateColumns: '64px 1fr', gap: 10, padding: '4px 0', cursor: 'pointer', borderBottom: `1px solid ${T.border}` }}>
                <span style={{ fontFamily: T.mono, fontSize: 11.5, fontWeight: 700, color: T.cyan }}>{p.code}</span>
                <span style={{ fontSize: 11.5, color: T.text }}>{p.label} <span style={{ color: T.dim, fontSize: 10 }}>· {p.hint}</span></span>
              </div>
            ))}
          </div>
          <div style={{ padding: '10px 16px' }}>
            <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.6, color: T.muted, marginBottom: 6 }}>
              KEYBOARD · {desktop ? 'SURYADHANA.APP' : 'BROWSER'}</div>
            {keys.map(([k, v]) => (
              <div key={k} style={{ display: 'grid', gridTemplateColumns: '150px 1fr', gap: 10, padding: '5px 0', borderBottom: `1px solid ${T.border}` }}>
                <span style={{ fontFamily: T.mono, fontSize: 11, color: T.amber }}>{k}</span>
                <span style={{ fontSize: 11.5, color: T.text }}>{v}</span>
              </div>
            ))}
            <div style={{ fontFamily: T.display, fontSize: 10, letterSpacing: 1.6, color: T.muted, margin: '14px 0 6px' }}>READING THE SCREENS</div>
            <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.7 }}>
              Amber = tickers and things to act on · green / red = up / down · every number is end-of-day NSE data unless marked
              live · "vs similar" and "excess" mean compared with NSE stocks of similar liquidity · costs are ICICI MoneySaver round trips.
              Research verdicts (RSCH) are pre-registered: PROMISING is not PROVEN. Paper mode: no order is ever sent from this app.
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
