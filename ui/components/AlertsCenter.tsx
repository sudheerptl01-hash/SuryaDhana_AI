'use client'

import { apiError } from '@/lib/errors'
/**
 * ALRT · alerts centre. Price alerts (checked every minute in market hours by the scheduler, even with the terminal
 * closed), the typed alert RULES over any stored series (Terminal v2 PLAN 2.3 / review M41: IV percentile and rank,
 * IV − RV, skew, straddle, OI at a strike, the OI wall, basis, rollover, F&O ban, results in N days, FII / DII, VIX,
 * the NIFTY driver, gold health, a stale dataset) with repeat / cooldown / snooze and a Mac / Telegram channel, the
 * FIRED inbox grouped by symbol, and the scheduler's notification inbox.
 *
 * An alert describes a level, never a direction: no rule colour reads as good or bad news, every fire carries its
 * badge, date and source, and nothing here feeds the Decision Desk, the S1 shadow or a ticket price (PAPER ONLY).
 * Other pages open the builder with lib/alerts.ts `draftAlert(...)`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getEcoCalendar, getNewsQuotes, getNotificationFeed, getPriceAlerts, putPriceAlert, type AlertHitSrv, type AlertLevelsSrv, type NotificationItem } from '@/lib/api'
import { BadgeChip, Btn, Chip, DataTable, Input, Notice, PageHeader, Panel, Select, SourceChip, T, TickerLink, fmtPx, type Column, sourceOf, inputSource, undatedSource } from '@/components/terminal'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { unicodeMinus } from '@/lib/format'   // server-built notification text: U+2212 (C1-18)
import { useActiveSymbol } from '@/lib/activeSymbol'
import { ALRT_PREFILL_EVENT, ALRT_PREFILL_KEY, parseAlertPrefill } from '@/lib/goAliases'
import { holidaysFromEco } from '@/components/desktop/session'
import { alertRuleAction, getAlertDryRun, getAlertFires, getAlertRules, getAlertSeries, postAlertRule } from '@/lib/alertsClient'
import { ALERT_FOCUS_KEY } from '@/lib/alertOverlay'
import {
  ALERT_DRAFT_EVENT, ALERT_DRAFT_KEY, CHANNEL_LABEL, OP_LABEL, PRESETS, draftFromForm, fmtAlertValue, formFromDraft, groupFires, noteHints,
  INDEX_NAMES, parseDraft, prefillTarget, ruleStateText, type AlertChannel, type HolidayCover, type AlertFire, type AlertOp, type AlertRepeat, type AlertRule, type AlertRuleDraft,
  type DraftForm, type DryRow, type SeriesKind,
} from '@/lib/alertsEngine'

type Row = { sym: string; lv: AlertLevelsSrv; price: number | null }
/** An alert on an NSE stock (no Yahoo code, or a '.NS' one): priced by the live NSE quote service. */
const isNse = (lv: AlertLevelsSrv | undefined): boolean => !lv?.yahoo || /\.NS$/i.test(lv.yahoo)
const KIND_COLOR: Record<string, string> = { price: T.amber, move: T.cyan, filing: T.violet, wrap: T.cyan, results: T.violet, close: T.cyan, morning: T.amber, rule: T.amber }
/** Symbols the fired inbox groups by that are not stocks (no stock window behind them). */
const NOT_A_STOCK = new Set(['FII', 'DII', 'GOLD', 'DATA', 'INDIAVIX', 'NIFTY', 'BANKNIFTY', 'NIFTYIT', '—'])
const SCROLL_X = { overflowX: 'auto' as const, maxWidth: '100%' }

/** The Fired panel's chip. An empty fire log that loaded is not "no source is responding" (5 Nov live audit: ALRT read
 *  OFFLINE with zero alerts set): it is undated, with what the scheduler does; OFFLINE stays for a load that failed. */
export function firedSource(lastAt: string | null, loaded: boolean) {
  if (lastAt) return sourceOf(lastAt, { source: 'alert scheduler', maxAgeDays: null })
  if (loaded) return undatedSource('alert scheduler', 'no alert has fired yet · alerts are checked every minute in market hours on live NSE quotes')
  return sourceOf(null, { source: 'alert scheduler', maxAgeDays: null, hint: 'the alerts store did not answer' })
}

const EMPTY_FORM: DraftForm = { kind: 'iv_pctile', params: {}, op: 'above', value: '', window: '', cooldown: '', repeat: 'repeat', channel: 'both', note: '' }
const PARAM_LABEL: Record<string, string> = { symbol: 'Symbol', strike: 'Strike', side: 'CE / PE', expiry: 'Expiry (opt.)', index: 'Index', dataset: 'Dataset' }

export function AlertsCenter() {
  const [alerts, setAlerts] = useState<Record<string, AlertLevelsSrv>>({})
  const [priceHistory, setPriceHistory] = useState<AlertHitSrv[]>([])
  const [loaded, setLoaded] = useState(false)
  const [prices, setPrices] = useState<Record<string, number | null>>({})
  const [feed, setFeed] = useState<NotificationItem[]>([])
  const [kind, setKind] = useState<string | null>(null)
  const [form, setForm] = useState({ sym: '', above: '', below: '', move: '' })
  const [msg, setMsg] = useState<string | null>(null)
  const liveOkRef = useRef(false)
  const [active, setActive] = useActiveSymbol()

  // typed engine state
  const [kinds, setKinds] = useState<SeriesKind[] | null>(null)
  const [engineDown, setEngineDown] = useState<string | null>(null)
  const [rules, setRules] = useState<AlertRule[]>([])
  const [fires, setFires] = useState<AlertFire[]>([])
  const [dry, setDry] = useState<Record<string, DryRow>>({})
  const [dryAt, setDryAt] = useState<string | null>(null)
  const [rf, setRf] = useState<DraftForm>(EMPTY_FORM)
  const [ruleMsg, setRuleMsg] = useState<string | null>(null)
  // F-PROBE/F-TRADER: ＋ADD RULE with an empty VALUE was a silent no-op — the problem now renders
  // inline beside the button (role=alert), not only in the strip below the QUICK row
  const [ruleProblem, setRuleProblem] = useState<string | null>(null)
  const builderRef = useRef<HTMLDivElement | null>(null)

  const loadRules = useCallback(async () => {
    try {
      // E-DIFF T-22 merge view: BOTH stores in one table — the legacy one-shot price alerts arrive as
      // origin 'price' rows (ids px:SYM:side) and render labelled `one-shot · legacy`; no store migration
      const [r, f] = await Promise.all([getAlertRules('all'), getAlertFires(200)])
      setRules(r.data.rules); setFires(f.data.fires); setEngineDown(null)
    } catch (e) { setEngineDown(apiError(e, 'ui-api did not answer')) }
    getAlertDryRun().then(d => { setDry(Object.fromEntries(d.data.rows.map(x => [x.id, x]))); setDryAt(d.data.as_of) }).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    try {
      const a = (await getPriceAlerts()).data
      setAlerts(a.alerts); setPriceHistory(a.history); setLoaded(true)
      // live program: NSE names are priced by the live NSE quote service below (useLiveQuotes); the quotes call is only
      // for non-NSE alerts, and for every alert while the live service does not answer
      const syms = Object.keys(a.alerts).filter(s => !liveOkRef.current || !isNse(a.alerts[s]))
      if (syms.length) {
        const q = (await getNewsQuotes(syms.map(s => a.alerts[s].yahoo ?? `${s}.NS`))).data.quotes
        setPrices(p => ({ ...p, ...Object.fromEntries(syms.map(s => [s, q[a.alerts[s].yahoo ?? `${s}.NS`]?.price ?? null])) }))
      }
    } catch { /* keep what is shown */ }
    getNotificationFeed(200).then(r => setFeed(r.data.items)).catch(() => {})
    loadRules()
  }, [loadRules])
  useEffect(() => { load(); const iv = setInterval(load, 60_000); return () => clearInterval(iv) }, [load])
  useEffect(() => {
    getAlertSeries().then(r => setKinds(r.data.kinds)).catch(e => { setKinds([]); setEngineDown(apiError(e, 'ui-api did not answer')) })
  }, [])

  // the create-alert hand-off from other pages (lib/alerts.ts draftAlert): stored for a page that was not open, an
  // event for one that was
  const adoptDraft = useCallback((d: AlertRuleDraft | null) => {
    if (!d || !kinds?.length) return false
    const f = formFromDraft(d, kinds)
    if (!f) { setRuleMsg(`unknown series ${d.series}`); return false }
    setRf(f); setRuleMsg('filled from the page you came from: check it, then ADD RULE')
    try { sessionStorage.removeItem(ALERT_DRAFT_KEY) } catch { /* ignore */ }
    builderRef.current?.scrollIntoView?.({ block: 'center' })
    return true
  }, [kinds])
  useEffect(() => {
    if (!kinds?.length) return
    let raw: string | null = null
    try { raw = sessionStorage.getItem(ALERT_DRAFT_KEY) } catch { /* blocked */ }
    adoptDraft(parseDraft(raw))
    const on = (e: Event) => { adoptDraft(parseDraft(JSON.stringify((e as CustomEvent<AlertRuleDraft>).detail))) }
    window.addEventListener(ALERT_DRAFT_EVENT, on)
    return () => window.removeEventListener(ALERT_DRAFT_EVENT, on)
  }, [kinds, adoptDraft])
  // the GO hand-off `ALRT TCS >3200` (components/CommandBar.tsx writes lib/goAliases.ts ALRT_PREFILL_KEY, ≤ 120 s old):
  // read once on mount and on its event; it only FILLS a form (the price form for a stock, the typed builder for an
  // index), the owner saves
  const adoptPrefill = useCallback(() => {
    let raw: string | null = null
    try { raw = localStorage.getItem(ALRT_PREFILL_KEY) } catch { return }
    if (!raw) return
    const t = prefillTarget(parseAlertPrefill(raw, Date.now()))
    if (t?.target === 'rule' && kinds === null) return                    // the catalogue is loading: the next run adopts it
    try { localStorage.removeItem(ALRT_PREFILL_KEY) } catch { /* ignore */ }
    if (!t) return
    if (t.target === 'price') {
      setForm({ sym: t.sym, above: t.above, below: t.below, move: t.move })
      setMsg(`filled from GO: ${t.sym} ${t.above ? `at or over ₹${t.above}` : `at or under ₹${t.below}`} · check it, then SET ALERT`)
      return
    }
    const f = kinds?.length ? formFromDraft(t.draft, kinds) : null
    if (!f) { setRuleMsg('GO asked for an index level, but the typed alert engine did not answer'); return }
    setRf(f); setRuleMsg(`filled from GO: ${t.draft.series} ${OP_LABEL[t.draft.op]} ${t.draft.value} (one-shot) · check it, then ADD RULE`)
    builderRef.current?.scrollIntoView?.({ block: 'center' })
  }, [kinds])
  useEffect(() => {
    adoptPrefill()
    window.addEventListener(ALRT_PREFILL_EVENT, adoptPrefill)
    return () => window.removeEventListener(ALRT_PREFILL_EVENT, adoptPrefill)
  }, [adoptPrefill])
  // NSE holidays for the inbox's "N sessions older" hint (m084): the eco calendar's holiday master, 120 days back
  const [cover, setCover] = useState<HolidayCover | null>(null)
  useEffect(() => {
    getEcoCalendar(120, 1).then(r => {
      const d = r.data as typeof r.data & { holidays_known?: boolean }
      const days = holidaysFromEco(d.events)
      // known: ui-api says so, or (an older ui-api without the flag) its HOLIDAY rows, which only NSE's master supplies
      const known = d.holidays_known === true || (d.holidays_known === undefined && days.size > 0)
      if (!known || !/^\d{4}-\d{2}-\d{2}$/.test(d.today)) return          // unknown holidays: the hint counts weekdays
      const from = new Date(Date.parse(`${d.today}T00:00:00Z`) - 120 * 86_400_000).toISOString().slice(0, 10)
      setCover({ days: new Set(days.keys()), from })
    }).catch(() => {})
  }, [])
  // the builder starts on the active underlying (the shared symbol context)
  useEffect(() => {
    if (active?.symbol) setRf(f => (f.params.symbol ? f : { ...f, params: { ...f.params, symbol: active.symbol } }))
  }, [active?.symbol])

  const save = async (sym: string, above: number | null, below: number | null, move: number | null = null) => {
    try {
      const d = (await putPriceAlert(sym, { above, below, move })).data
      setAlerts(d.alerts); setPriceHistory(d.history)
      setMsg(above == null && below == null && move == null ? `${sym}: alert removed` : `${sym}: alert saved`)
      load()
    } catch (e: any) { setMsg(apiError(e, 'could not save')) }
  }
  const submit = () => {
    const sym = form.sym.trim().toUpperCase().replace(/\.NS$/, '')
    const num = (v: string) => (v.trim() === '' || isNaN(Number(v)) ? null : Number(v))
    if (!/^[A-Z0-9&-]{1,20}$/.test(sym)) { setMsg('enter an NSE symbol'); return }
    if (num(form.above) == null && num(form.below) == null && num(form.move) == null) { setMsg('set a level above, below, or a ± % move'); return }
    save(sym, num(form.above), num(form.below), num(form.move)); setForm({ sym: '', above: '', below: '', move: '' })
    setActive({ symbol: sym })
  }

  const kindSpec = useMemo(() => kinds?.find(k => k.kind === rf.kind) ?? null, [kinds, rf.kind])
  // an index's price is in points, not ₹ (the server's unit_for)
  const valueUnit = kindSpec?.kind === 'price' && INDEX_NAMES.has(String(rf.params.symbol ?? '').trim().toUpperCase()) ? 'points' : kindSpec?.unit
  const setKindTo = (k: string) => {
    const spec = kinds?.find(x => x.kind === k)
    setRf(f => ({ ...f, kind: k, op: spec && !spec.ops.includes(f.op) ? spec.ops[0] : f.op,
                  params: { symbol: f.params.symbol ?? active?.symbol ?? '', ...(spec?.params.includes('side') ? { side: f.params.side ?? 'CE' } : {}),
                            ...(spec?.params.includes('index') ? { index: 'NIFTY' } : {}), ...(spec?.params.includes('dataset') ? { dataset: f.params.dataset ?? 'any' } : {}) } }))
  }
  const addRule = async () => {
    if (!kinds) return
    const { draft, problem } = draftFromForm(rf, kinds)
    if (!draft) { setRuleProblem(problem || 'check the fields above'); return }
    setRuleProblem(null)
    try {
      const r = (await postAlertRule(draft)).data
      setRuleMsg(`saved: ${r.summary ?? r.series}`)
      if (rf.params.symbol) setActive({ symbol: rf.params.symbol.trim().toUpperCase() })
      setRf(f => ({ ...f, value: '', note: '' }))
      loadRules()
    } catch (e) { setRuleMsg(apiError(e, 'could not save the rule')) }
  }
  const act = async (id: string, action: 'snooze' | 'resume' | 'pause' | 'delete', minutes?: number) => {
    try { await alertRuleAction(id, action, minutes); loadRules() } catch (e) { setRuleMsg(apiError(e, `could not ${action}`)) }
  }
  // a merged legacy row's ✕: the price store's own write (PUT /api/alerts/{sym}), clearing just that side
  const removeLegacy = (r: AlertRule) => {
    const sym = r.symbol ?? ''
    const side = String(r.id).split(':')[2]
    const lv = alerts[sym] ?? {}
    save(sym, side === 'above' ? null : lv.above ?? null, side === 'below' ? null : lv.below ?? null, side === 'move' ? null : lv.move ?? null)
  }
  // E-DIFF T-22: a chart's alert line was clicked — point the owner at that rule (sessionStorage one-shot)
  useEffect(() => {
    if (!rules.length) return
    let raw: string | null = null
    try { raw = sessionStorage.getItem(ALERT_FOCUS_KEY) } catch { return }
    if (!raw) return
    try { sessionStorage.removeItem(ALERT_FOCUS_KEY) } catch { /* ignore */ }
    const r = rules.find(x => x.id === raw)
    if (r) {
      setRuleMsg(`from the chart line: ${r.label ?? r.series} ${r.condition ?? ''} — the rule is in the table below`)
      builderRef.current?.scrollIntoView?.({ block: 'center' })
    }
  }, [rules])
  const preset = (id: string) => {
    const p = PRESETS.find(x => x.id === id)
    if (!p || !kinds) return
    const sym = (rf.params.symbol || active?.symbol || 'NIFTY').trim().toUpperCase()
    const f = formFromDraft(p.draft(sym), kinds)
    if (f) { setRf(f); setRuleMsg(`${p.label}: check the fields, then ADD RULE`) }
  }

  const nseAlerts = useMemo(() => Object.keys(alerts).filter(s => isNse(alerts[s])), [alerts])
  const liveA = useLiveQuotes(nseAlerts, { intervalMs: 3_000 })
  liveOkRef.current = liveA.available
  const livePx = (sym: string): number | null => { const q = liveA.quotes[sym]; return q && q.price != null && q.state !== 'unavailable' ? q.price : null }
  const rows: Row[] = Object.entries(alerts).map(([sym, lv]) => ({ sym, lv, price: (isNse(lv) ? livePx(sym) : null) ?? prices[sym] ?? null }))
  const dist = (r: Row, lv?: number) => (lv != null && r.price ? (lv / r.price - 1) * 100 : null)
  const pctTxt = (v: number | null) => (v == null ? '' : `${v < 0 ? '−' : '+'}${Math.abs(v).toFixed(1)} %`)
  const cols: Column<Row>[] = [
    { key: 'sym', label: 'Stock', sort: r => r.sym, render: r => <TickerLink symbol={r.sym} /> },
    { key: 'price', label: 'Last', align: 'right', sort: r => r.price ?? -1, render: r => {
        const info = isNse(r.lv) && livePx(r.sym) != null ? liveA.sourceFor(r.sym) : null
        return <span title={info ? liveA.lineFor(r.sym) ?? undefined : isNse(r.lv) ? 'quotes route (the live NSE quote service is not answering)' : 'Yahoo (non-NSE symbol), about 1 min delayed'}>{fmtPx(r.price)}</span> } },
    { key: 'above', label: 'At or over', align: 'right', render: r => r.lv.above == null ? <span style={{ color: T.dim }}>—</span>
        : <span><span style={{ color: T.text }}>{r.lv.above.toLocaleString('en-IN')}</span> <span style={{ color: T.dim, fontSize: 10 }}>{pctTxt(dist(r, r.lv.above))}</span></span> },
    { key: 'below', label: 'At or under', align: 'right', render: r => r.lv.below == null ? <span style={{ color: T.dim }}>—</span>
        : <span><span style={{ color: T.text }}>{r.lv.below.toLocaleString('en-IN')}</span> <span style={{ color: T.dim, fontSize: 10 }}>{pctTxt(dist(r, r.lv.below))}</span></span> },
    { key: 'move', label: 'Move ±', align: 'right', render: r => r.lv.move == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: T.cyan }} title="fires when today's change vs the official previous close reaches this size, either way">±{r.lv.move}%</span> },
    { key: 'near', label: 'Nearest level', align: 'right', sort: r => Math.min(...[dist(r, r.lv.above), dist(r, r.lv.below)].filter((x): x is number => x != null).map(Math.abs), 999),
      render: r => { const d = [dist(r, r.lv.above), dist(r, r.lv.below)].filter((x): x is number => x != null).map(Math.abs)
        if (!d.length) return '—'; const m = Math.min(...d)
        return <span style={{ color: m < 2 ? T.amber : T.muted, fontWeight: m < 2 ? 700 : 400 }}>{m.toFixed(1)}% away</span> } },
    { key: 'x', label: '', render: r => <span role="button" onClick={e => { e.stopPropagation(); save(r.sym, null, null) }}
        style={{ color: T.dim, cursor: 'pointer', fontSize: 10 }} title="remove this alert">✕ remove</span> },
  ]

  const ruleCols: Column<AlertRule>[] = [
    { key: 'rule', label: 'Rule', sort: r => r.label ?? r.series, render: r => (
        <span style={{ whiteSpace: 'normal', display: 'inline-block', maxWidth: 360, lineHeight: 1.4 }}>
          <span style={{ color: T.text }}>{r.label ?? r.series}</span> <span style={{ color: T.muted }}>{r.condition}</span>
          {r.note && <span style={{ color: T.dim, display: 'block', fontSize: 10 }}>note: {r.note}</span>}
        </span>) },
    { key: 'now', label: 'Now', align: 'right', render: r => {
        if (r.origin === 'price') {   // a merged legacy row: the live quote its minute-check compares against
          const sym = r.symbol ?? ''
          const p = (isNse(alerts[sym]) ? livePx(sym) : null) ?? prices[sym] ?? null
          return p != null ? <span title="the quote the minute-check compares against (live NSE service, else the quotes route)">{fmtPx(p)}</span> : <span style={{ color: T.dim }}>—</span>
        }
        const d = dry[r.id]
        if (!d) return <span style={{ color: T.dim }}>—</span>
        if (d.value == null) return <span style={{ color: T.dim, fontSize: 10 }} title={d.reason ?? undefined}>no reading</span>
        return <span title={`${d.source}${d.metric != null && d.metric !== d.value ? ` · compared: ${d.metric}` : ''}`}>
          {unicodeMinus(fmtAlertValue(d.value, d.unit))} <span style={{ color: T.dim, fontSize: 10 }}>{d.as_of ? String(d.as_of).slice(0, 10) : ''}</span></span> } },
    { key: 'holds', label: 'Condition', render: r => { const d = dry[r.id]
        // neutral tones only: a rule holding is not good or bad news (PLAN §0.1)
        if (!d || d.satisfied == null) return <span style={{ color: T.dim, fontSize: 10 }}>{d?.reason ? 'not measurable yet' : '—'}</span>
        return <span style={{ color: d.satisfied ? T.amber : T.muted, fontSize: 11 }}>{d.satisfied ? 'holds now' : 'not now'}</span> } },
    { key: 'badge', label: 'Badge', render: r => <BadgeChip badge={r.badge ?? 'arithmetic'} /> },
    { key: 'state', label: 'State', render: r => r.origin === 'price'
        ? <span style={{ color: T.muted, fontSize: 11 }}>{ruleStateText(r)}<span style={{ color: T.dim }}> · one-shot · legacy</span></span>
        : <span style={{ color: r.status === 'active' ? T.text : T.muted, fontSize: 11 }}>{ruleStateText(r)}
        <span style={{ color: T.dim }}> · {r.repeat === 'once' ? 'one-shot' : r.cooldown_min ? `repeat, ${r.cooldown_min} min apart` : 'repeat'} · {CHANNEL_LABEL[(r.channel ?? 'both') as AlertChannel]}</span></span> },
    { key: 'last', label: 'Last fired', sort: r => r.last_fired_at ?? '', render: r => <span style={{ color: T.dim }}>{r.last_fired_at ? r.last_fired_at.replace('T', ' ').slice(0, 16) : '—'}</span> },
    { key: 'act', label: '', render: r => r.origin === 'price'
      ? <span role="button" style={{ color: T.dim, cursor: 'pointer', fontSize: 10 }}
          title="remove this price alert — the legacy store's own write, same as ✕ remove in the Price alerts panel" onClick={() => removeLegacy(r)}>✕</span>
      : (
        <span style={{ display: 'inline-flex', gap: 8, fontSize: 10 }}>
          {r.status === 'active' && <span role="button" style={{ color: T.muted, cursor: 'pointer' }} title="silence for an hour (a level still crossed fires after it)" onClick={() => act(r.id, 'snooze', 60)}>snooze 1h</span>}
          {r.status !== 'active' && <span role="button" style={{ color: T.amber, cursor: 'pointer' }} title="watch again (re-armed)" onClick={() => act(r.id, 'resume')}>resume</span>}
          {r.status === 'active' && <span role="button" style={{ color: T.muted, cursor: 'pointer' }} title="stop watching until resumed" onClick={() => act(r.id, 'pause')}>pause</span>}
          <span role="button" style={{ color: T.dim, cursor: 'pointer' }} title="delete this rule (its fires stay in the inbox)" onClick={() => act(r.id, 'delete')}>✕</span>
        </span>) },
  ]

  // the fired inbox: price hits + typed fires, newest first (one list), then grouped by symbol
  const history = useMemo(() => [...fires].sort((a, b) => (a.at < b.at ? 1 : a.at > b.at ? -1 : b.seq - a.seq)), [fires])
  const groups = useMemo(() => groupFires(history).slice(0, 24), [history])
  const firedCount = fires.length || priceHistory.length

  const kinds_ = useMemo(() => [...new Set(feed.map(f => f.kind))], [feed])
  const shownFeed = feed.filter(f => !kind || f.kind === kind)
  const groupLabel = (k: SeriesKind) => `${k.group} · ${k.name ?? k.label.replace(/\{(\w+)\}\s?/g, '')}`.replace(/\s+/g, ' ').trim()

  return (
    <div style={{ minWidth: 0 }}>
      <PageHeader code="ALRT" title="Alerts"
        subtitle="price alerts and typed rules over stored series, checked by the scheduler (terminal can be closed) · fired inbox · notifications" />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 460px), 1fr))', gap: 12, alignItems: 'start' }}>
        <Panel source={inputSource('your alert levels (the server checks them every minute in session)')} title={`Price alerts · ${rows.length}`} accent={T.amber} pad={0}
          right={liveA.available && liveA.source ? <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center', fontSize: 10, color: T.dim }}>PRICES <SourceChip info={liveA.source} /></span> : undefined}
          subtitle="one-shot: a fired level is cleared">
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: 10, borderBottom: `1px solid ${T.border}`, flexWrap: 'wrap' }}>
            <Input label="Stock" value={form.sym} onChange={v => setForm({ ...form, sym: v })} placeholder={active?.symbol ?? 'TCS'} width={100} />
            <Input label="At or over ₹" value={form.above} onChange={v => setForm({ ...form, above: v })} width={90} />
            <Input label="At or under ₹" value={form.below} onChange={v => setForm({ ...form, below: v })} width={90} />
            <Input label="Move ±%" value={form.move} onChange={v => setForm({ ...form, move: v })} width={80} />
            <Btn size="sm" onClick={submit}>＋ SET ALERT</Btn>
            {msg && <span style={{ fontSize: 11, color: T.muted }}>{msg}</span>}
          </div>
          {/* F-PROBE (one number once per page): the legacy levels used to print here AND as the merged
              origin-'price' rows in the Rules table below — the E-DIFF T-22 merge left this list behind.
              The merged table is now the one list; this fallback renders only while the typed engine is
              down (an older ui-api, or the engine erroring), so the levels never show twice. */}
          {engineDown && <div style={SCROLL_X}>
            <DataTable columns={cols} rows={rows} rowKey={r => r.sym} dense empty="No price alerts. Set one above, or with the bell in the Alert column on WTCH." initialSort={{ key: 'near', dir: 'asc' }} />
          </div>}
        </Panel>
        <Panel source={firedSource(history[0]?.at ?? null, loaded)} title={`Fired · ${firedCount}`} accent={T.cyan} pad={0} subtitle="by symbol, newest first">
          {engineDown && priceHistory.length > 0 && !fires.length
            ? <div style={SCROLL_X}><DataTable<AlertHitSrv> dense maxHeight={360} rowKey={(h, i) => `${h.sym}-${h.at}-${i}`} rows={priceHistory} empty="Nothing has fired yet."
                columns={[
                  { key: 'at', label: 'When', render: h => <span style={{ color: T.dim }}>{h.at.replace('T', ' ').slice(0, 16)}</span> },
                  { key: 'sym', label: 'Stock', render: h => <TickerLink symbol={h.sym} /> },
                  { key: 'side', label: 'Level', render: h => h.side === 'move'
                      ? <span style={{ color: T.cyan }}>move ±{h.level}% ({unicodeMinus(pctTxt(h.change_pct ?? null))})</span>
                      : <span style={{ color: T.text }}>{h.side === 'above' ? 'at or over' : 'at or under'} {h.level.toLocaleString('en-IN')}</span> },
                  { key: 'price', label: 'Price', align: 'right', render: h => fmtPx(h.price) },
                ]} /></div>
            : groups.length === 0
              ? <div style={{ padding: 10, fontSize: 11, color: T.muted }}>Nothing has fired yet.</div>
              : <div style={{ maxHeight: 420, overflow: 'auto' }}>
                  {groups.map(g => (
                    <div key={g.symbol} style={{ borderBottom: `1px solid ${T.border}`, padding: '6px 10px' }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'baseline', marginBottom: 3 }}>
                        {NOT_A_STOCK.has(g.symbol) ? <span style={{ color: T.text, fontWeight: 600 }}>{g.symbol}</span> : <TickerLink symbol={g.symbol} />}
                        <span style={{ color: T.dim, fontSize: 10 }}>{g.count} fire{g.count > 1 ? 's' : ''} · last {g.last_at.replace('T', ' ').slice(0, 16)}</span>
                      </div>
                      {g.fires.slice(0, 5).map(f => (
                        <div key={f.seq} style={{ display: 'flex', gap: 8, alignItems: 'baseline', fontSize: 11, lineHeight: 1.45, flexWrap: 'wrap' }}>
                          <span style={{ color: T.dim, whiteSpace: 'nowrap' }}>{f.at.replace('T', ' ').slice(5, 16)}</span>
                          <span style={{ color: T.text, flex: '1 1 220px', minWidth: 0, overflowWrap: 'anywhere' }}>{unicodeMinus(f.text)}</span>
                          <BadgeChip badge={f.badge ?? 'arithmetic'} />
                        </div>
                      ))}
                      {g.count > 5 && <div style={{ color: T.dim, fontSize: 10 }}>+{g.count - 5} earlier</div>}
                    </div>
                  ))}
                </div>}
        </Panel>
      </div>

      {/* no panel-level badge: the table mixes arithmetic and context series, so each row carries its own (Badge column) */}
      <Panel title={`Rules · ${rules.length}`} accent={T.amber} pad={0} style={{ marginTop: 12 }}
        source={dryAt ? sourceOf(dryAt, { source: 'stored series (dry run)', maxAgeDays: null }) : inputSource('your rules over stored series')}
        subtitle="typed rules + the one-shot price alerts in one table (display-level merge, both stores) · never a direction · badge per row">
        {engineDown && <div style={{ padding: 10 }}><Notice color={T.muted}>The typed alert engine did not answer ({engineDown}). It serves after ui-api restarts on this release; the price alerts above work as before.</Notice></div>}
        <div ref={builderRef} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: 10, borderBottom: `1px solid ${T.border}`, flexWrap: 'wrap' }}>
          <Select label="Series" value={rf.kind} onChange={setKindTo}
            options={(kinds ?? []).map(k => ({ value: k.kind, label: groupLabel(k) }))} style={{ maxWidth: 260 }} />
          {kindSpec && [...kindSpec.params, ...kindSpec.optional].map(p => p === 'side'
            ? <Select key={p} label={PARAM_LABEL[p]} value={(rf.params.side ?? 'CE') as 'CE' | 'PE'} onChange={v => setRf({ ...rf, params: { ...rf.params, side: v } })}
                options={[{ value: 'CE', label: 'CE (calls)' }, { value: 'PE', label: 'PE (puts)' }]} />
            : p === 'index'
              ? <Select key={p} label={PARAM_LABEL[p]} value={(rf.params.index ?? 'NIFTY') as 'NIFTY' | 'BANKNIFTY'} onChange={v => setRf({ ...rf, params: { ...rf.params, index: v } })}
                  options={[{ value: 'NIFTY', label: 'NIFTY (NIFTY 50)' }, { value: 'BANKNIFTY', label: 'BANKNIFTY (NIFTY BANK)' }]} />
              : <Input key={p} label={PARAM_LABEL[p] ?? p} value={rf.params[p] ?? ''} width={p === 'expiry' ? 110 : p === 'dataset' ? 130 : 90}
                  placeholder={p === 'symbol' ? (active?.symbol ?? 'NIFTY') : p === 'expiry' ? 'YYYY-MM-DD' : p === 'dataset' ? 'any' : ''}
                  onChange={v => setRf({ ...rf, params: { ...rf.params, [p]: v } })} />)}
          <Select label="Condition" value={rf.op} onChange={v => setRf({ ...rf, op: v as AlertOp })}
            options={(kindSpec?.ops ?? []).map(o => ({ value: o, label: OP_LABEL[o] }))} />
          {rf.op !== 'changed' && <Input label={rf.op === 'change_pct' ? 'Move %' : rf.op.startsWith('pctile') ? 'Percentile' : `Value${valueUnit && valueUnit !== 'flag' ? ` (${valueUnit})` : ''}`}
            value={rf.value} onChange={v => setRf({ ...rf, value: v })} width={80} placeholder={kindSpec?.unit === 'flag' ? '0.5' : ''} />}
          {(rf.op === 'change_pct' || rf.op.startsWith('pctile')) && <Input label="Window (sessions)" value={rf.window} onChange={v => setRf({ ...rf, window: v })} width={80}
            placeholder={rf.op === 'change_pct' ? '1' : '252'} />}
          <Select label="Repeat" value={rf.repeat} onChange={v => setRf({ ...rf, repeat: v as AlertRepeat })}
            options={[{ value: 'repeat', label: 'repeat' }, { value: 'once', label: 'one-shot' }]} />
          {rf.repeat === 'repeat' && <Input label="Cooldown (min)" value={rf.cooldown} onChange={v => setRf({ ...rf, cooldown: v })} width={80} placeholder="30" />}
          <Select label="Channel" value={rf.channel} onChange={v => setRf({ ...rf, channel: v as AlertChannel })}
            options={(['both', 'mac', 'telegram'] as AlertChannel[]).map(c => ({ value: c, label: CHANNEL_LABEL[c] }))} />
          <Input label="Note (optional)" value={rf.note} onChange={v => setRf({ ...rf, note: v })} width={180} />
          <Btn size="sm" onClick={addRule} disabled={!kinds?.length}>＋ ADD RULE</Btn>
          {ruleProblem && <span role="alert" style={{ fontSize: 11, color: T.amber, alignSelf: 'center' }}>not saved — {ruleProblem}</span>}
        </div>
        <div style={{ padding: '6px 10px', borderBottom: `1px solid ${T.border}`, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: T.dim, letterSpacing: 1 }}>QUICK</span>
          {PRESETS.map(p => <Chip key={p.id} color={T.muted} onClick={() => preset(p.id)} title={p.needs === 'symbol' ? `on ${rf.params.symbol || active?.symbol || 'NIFTY'}` : undefined}>{p.label}</Chip>)}
        </div>
        {(kindSpec || ruleMsg) && <div style={{ padding: '6px 10px', fontSize: 11, color: T.muted, lineHeight: 1.45, borderBottom: `1px solid ${T.border}`, overflowWrap: 'anywhere' }}>
          {ruleMsg && <div style={{ color: T.amber }}>{ruleMsg}</div>}
          {kindSpec && <div>{kindSpec.definition} · <span style={{ color: T.dim }}>{kindSpec.source} · {kindSpec.cadence === 'live' ? 'checked every minute in session' : kindSpec.cadence === 'hourly' ? 'checked hourly' : 'stored daily: checked after each EOD step'}</span> <BadgeChip badge={kindSpec.badge} /></div>}
        </div>}
        <div style={SCROLL_X}>
          <DataTable columns={ruleCols} rows={rules} rowKey={r => r.id} dense
            empty="No rules yet. Pick a QUICK rule or build one above; OMON, CHRT and OSTR open this builder from a strike, a level or a breakeven." />
        </div>
      </Panel>

      <Panel source={sourceOf(feed[0]?.at ?? null, { source: 'scheduler inbox', maxAgeDays: null })} title={`Inbox · ${shownFeed.length}`} accent={T.cyan} pad={0} style={{ marginTop: 12 }}
        subtitle="what the scheduler told you">
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', padding: '6px 10px', borderBottom: `1px solid ${T.border}` }}>
          <Chip color={T.muted} active={!kind} onClick={() => setKind(null)}>ALL</Chip>
          {kinds_.map(k => <Chip key={k} color={KIND_COLOR[k] ?? T.muted} active={kind === k} onClick={() => setKind(kind === k ? null : k)}>{k.toUpperCase()}</Chip>)}
        </div>
        <div style={SCROLL_X}>
          <DataTable<NotificationItem> dense maxHeight={480} rowKey={(n, i) => `${n.at}-${i}`} rows={shownFeed} empty="No notifications yet."
            columns={[
              { key: 'at', label: 'When', render: n => <span style={{ color: T.dim, whiteSpace: 'nowrap' }}>{n.at.replace('T', ' ').slice(0, 16)}</span> },
              { key: 'kind', label: 'Kind', render: n => <span style={{ color: KIND_COLOR[n.kind] ?? T.muted, fontSize: 10, letterSpacing: 0.8 }}>{n.kind.toUpperCase()}</span> },
              { key: 'body', label: 'Message', render: n => <span style={{ color: T.text, whiteSpace: 'normal', lineHeight: 1.45, display: 'inline-block', maxWidth: 1100, overflowWrap: 'anywhere' }}>
                  <span style={{ color: T.muted }}>{n.title.replace('SuryaDhana · ', '')}: </span>{unicodeMinus(String(n.body ?? ''))}
                  {noteHints(n.kind, n.at, String(n.body ?? ''), cover).map(h => <span key={h} style={{ display: 'block', color: T.dim, fontSize: 10 }}>⚠ {h}</span>)}</span> },
            ]} />
        </div>
      </Panel>
    </div>
  )
}
