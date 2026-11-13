'use client'

/**
 * DAILY — the Kitco chart, done our way (PLAN a.3; wave 1d: Kitco's timeframes and units). d.24h is ONE chart panel with
 * Kitco's timeframes (24 h · 3 days · 30 days · 60 days · 6 months · 1 year · 5 years · 10 years · all) and units (USD/oz,
 * ₹/10 g landed ex-duty or duty-paid, ₹/g, USD/g, USD/kg), the window's high / low / change, the previous close dashed and,
 * on 24 h, the Globex-day axis with the session bands (Sydney/Tokyo · Shanghai · London · New York), the MCX bar and the
 * hatched CME maintenance hour; a "Kitco ↗" link beside it (Kitco is a link only: its terms forbid scraping). Then three
 * days overlaid (d.3day), the SGE Au99.99 line when stored (d.sge), yesterday's OI × price read (d.quadrant) and the last
 * twelve 5-minute bars (d.tape).
 *
 * Data: /api/gold/bars only (GC=F 1-minute and daily bars, INR=X 1-minute and daily bars for the rupee — each point at the
 * rate of its own time; the duty is the page's one dated duty, applied only from its effective date), /api/gold/positioning/daily.
 * The view never calls Yahoo. Chart arithmetic: lib/gold/kitco.ts and lib/gold/sessions.ts, unit-tested by gold.check.ts.
 * Arithmetic badge on the chart, context on the rest; colour only on the price change.
 */
import { useEffect, useMemo, useState } from 'react'
import { Chip, DataTable, T, fmtFixed, fmtSigned, type Column } from '@/components/terminal'
import { getGoldBars, getGoldPositioningDaily, memoGet } from '@/lib/gold/api'
import { UNIT_LABEL, comexCode, comexMonthLabel, convertUsdOz, dayLabel, fmtCount, fmtInUnit, fmtSignedPctSp, istClock, pctChange, unitDp } from '@/lib/gold/format'
import { istDateISO } from '@/lib/format'
import { KITCO_ALL_FROM, KITCO_SHORT_DAYS, KITCO_TIMEFRAMES, KITCO_UNITS, KITCO_UNIT_LABEL, KITCO_URL, dailyCloseIn, dailyFxPoints, dailyFxRows, decimate, dutyMultiplier, fxAsOf,
         fmtKitco, fmtKitcoSigned, isRupee, kitcoConvert, kitcoDp, kitcoLegend, kitcoSeries, kitcoStats, kitcoUnitFromPage, mergeFx, overlayOnScale, timeframe, type DailyFx, type DutyMode, type FxPt, type KitcoTf, type KitcoUnit,
         type KPt } from '@/lib/gold/kitco'
import { barMs, dailyOhlc, dayGroups, fmtHM, istDate, istMinutes, istToNy, legendCloses, prevSessionClose, resample5m, shiftDays,
         ukDstActive, usDstActive, type DayPt } from '@/lib/gold/sessions'
import type { Bar, GoldBars, GoldSubViewProps } from '@/lib/gold/types'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { IntradayChart, TimeChart, type Conv } from './KitcoChart'
import { OiQuadrantTape } from './OiQuadrantTape'
import { LinkTile, Term } from './ViewBits'
import { GoldPanel, NoVerdict, Pending, useGoldLoad } from './kit'

const BARS_MS = 60_000
/** the only COMEX symbol with stored 1-minute bars (gold_bars_intraday: GC=F, INR=X, SGE_AU9999) */
const BARS_SYMBOL = 'GC=F'
type Pt = DayPt
const DAY_MS = 86_400_000
/** a load that is off resolves to null without a request (the long daily and the rupee bars load only when a timeframe / unit needs them) */
const maybe = (on: boolean, f: () => Promise<{ data: GoldBars }>): Promise<{ data: GoldBars | null }> => (on ? f() : Promise.resolve({ data: null }))

export function DailyView({ sel, unit, layer, comexMatched, usdinr, tooltips, catalog, fair, overview }: GoldSubViewProps) {
  const symbol = comexMatched ?? 'GC=F'
  // 1-minute bars are stored for GC=F (and INR=X) only — the 5-minute job fetches the front contract, never the matched
  // month (ingest_yahoo.fetch_intraday); the matched month names the panel and prices `live` (desk cache), the chart is GC=F.
  const bars = useGoldLoad(() => getGoldBars(BARS_SYMBOL, '1m'), [], BARS_MS)
  // the stored DAILY closes of the last sessions: the legend's closes and the dashed reference line come from here
  // (gold_daily_bars, keyed by trade date), never from the end of an IST minute bucket (C-TRADER-2 / C-TRADER-17)
  const today = istDateISO()
  const dailyBars = useGoldLoad(() => getGoldBars(BARS_SYMBOL, '1d', { from: shiftDays(today, -14) }), [today], 15 * 60_000)
  // SGE quotes are written at '1m' (ingest_physical g_sge_quotes); resample5m coarsens on the client when wanted
  const sge = useGoldLoad(() => getGoldBars('SGE_AU9999', '1m'), [], 300_000)
  const quadComex = useGoldLoad(() => getGoldPositioningDaily('COMEX', 20), [], 900_000)
  const quadMcx = useGoldLoad(() => getGoldPositioningDaily('MCX', 20, sel.family), [sel.family], 900_000)   // the picked family (API_CONTRACT §2.6)
  const [showPrev, setShowPrev] = useState(true)
  const [showBands, setShowBands] = useState(true)
  const [res, setRes] = useState<'1m' | '5m'>('1m')

  const data: GoldBars | null = bars.data
  const nowMs = useMemo(() => {
    const last = data?.bars?.[data.bars.length - 1]
    return last ? barMs(last.ts) : Date.now()
  }, [data])
  const usDst = usDstActive(nowMs), ukDst = ukDstActive(nowMs)
  const src = useMemo(() => (res === '5m' ? resample5m(data?.bars ?? []) : (data?.bars ?? [])), [data, res])
  const groups = useMemo(() => dayGroups(src, usDst), [src, usDst])
  const prevGroup = useMemo(() => (data?.prev_day?.length ? dayGroups(data.prev_day.map(p => ({ ts: p.ts, o: p.c, h: p.c, l: p.c, c: p.c })), usDst) : null), [data, usDst])
  const groups24 = useMemo(() => {
    if (!prevGroup?.length || groups.length < 1) return groups
    const today = groups[groups.length - 1]
    const prev = prevGroup[prevGroup.length - 1]
    return prev.date === today.date ? groups : [prev, today]
  }, [groups, prevGroup])
  // ── the SGE overlay (CT-01 / F1): drawn only when the SERVER says the bars are in this chart's unit, only for the
  // COMEX day on screen, and only when it is on the same scale. Raw CNY/g once reached the USD/oz y-domain and stretched
  // it from 868 to 4,100, pressing the COMEX line flat; and between the Monday Globex reopen (04:30 IST) and the SGE open
  // (06:30 IST) `.slice(-1)` drew FRIDAY's Shanghai line on Monday's axis.
  const sgeUnitOk = (sge.data?.unit ?? null) === 'USD/oz'
  const sgeGroups = useMemo(() => (sge.data?.bars?.length ? dayGroups(sge.data.bars, usDst) : []), [sge.data, usDst])
  const sgeLast = sgeGroups.length ? sgeGroups[sgeGroups.length - 1] : null
  const comexDay = groups24.length ? groups24[groups24.length - 1] : null
  const sgeDay = useMemo(() => (comexDay ? sgeGroups.find(g => g.date === comexDay.date) ?? null : null), [sgeGroups, comexDay])
  const sgeFit = useMemo(() => overlayOnScale(sgeUnitOk ? sgeDay?.pts : null, comexDay?.pts, 25), [sgeUnitOk, sgeDay, comexDay])
  const sgePts = sgeFit.pts
  const sgeBar = sgeDay?.pts.length ? sge.data?.bars?.find(b => barMs(b.ts) === sgeDay.pts[sgeDay.pts.length - 1].ms) ?? null : null
  // one sentence per reason the overlay is withheld — never silence, and never a drawn line the axis cannot carry
  const sgeWhyNoOverlay = !sge.data?.bars?.length
    ? `No SGE bars stored for this window yet — the asia job writes them during SGE hours (06:30–13:00 and 17:30–00:00 IST).${sge.data?.since ? ` Stored since ${dayLabel(sge.data.since)}.` : ''}`
    : !sgeUnitOk
      ? `SGE bars arrived ${sge.data?.unit ? `labelled ${sge.data.unit}` : 'with no unit'}${sge.data?.unit_native ? ` (the store keeps ${sge.data.unit_native})` : ''}, not $/oz — not overlaid: a series in another unit would set this chart's axis.`
      : !sgeDay
        ? `Shanghai's last stored session is ${sgeLast ? dayLabel(sgeLast.date) : '—'}, not the COMEX day on screen${comexDay ? ` (${dayLabel(comexDay.date)})` : ''} — not overlaid.`
        : sgeFit.why
          ? `The Shanghai line is ${sgeFit.why} — not overlaid.`
          : sgeDay.pts.length < 2
            ? `Only ${sgeDay.pts.length} SGE bar${sgeDay.pts.length === 1 ? '' : 's'} on ${dayLabel(sgeDay.date)}: a line needs two.`
            // the render gate also needs the payload row behind the session's last point; without it the panel has no
            // native price and no rate to name, so it says that instead of the 'needs two' line it used to fall through to
            : `The last SGE bar of ${dayLabel(sgeDay.date)} could not be matched to its payload row — not overlaid.`
  // the store's partial flag rides along (per bar, or /bars.daily_closes): a pre-close bar is never labelled a final close (wave 1e)
  const daily = useMemo(() => dailyOhlc(dailyBars.data?.bars ?? [], new Set((dailyBars.data?.daily_closes ?? []).filter(d => d.partial).map(d => d.date))), [dailyBars.data])
  const todayDate = groups[groups.length - 1]?.date ?? null
  // the dashed line is the PREVIOUS session's stored daily close, labelled with its date and source; the server's
  // settle_line is drawn only when it is a bulletin settlement (quality 'settlement'), never today's last trade
  const serverSettle = data?.settle_line && /settle/i.test(data.settle_line.quality ?? '') && !/last.?trade/i.test(data.settle_line.quality ?? '') ? data.settle_line : null
  const prevClose = useMemo(() => prevSessionClose(daily, todayDate), [daily, todayDate])
  const settle = serverSettle?.value ?? prevClose?.c ?? null
  const settleLabel = serverSettle ? serverSettle.label : prevClose ? `${dayLabel(prevClose.date)} ${prevClose.partial ? 'close (Yahoo daily, partial: fetched before the Globex close)' : 'close (Yahoo daily, not settlement)'}` : ''
  const live = data?.last ? { price: data.last.price, as_of: data.last.as_of } : null
  const tape = useMemo(() => resample5m(data?.bars ?? []).slice(-12).reverse(), [data])

  // ── the Kitco-style panel (wave 1d): timeframe × unit × duty, every point at its own time's rupee rate ──────────
  const [tf, setTf] = useState<KitcoTf>('24h')
  const [kUnit, setKUnit] = useState<KitcoUnit>(() => kitcoUnitFromPage(unit))
  useEffect(() => { setKUnit(kitcoUnitFromPage(unit)) }, [unit])            // the page unit sets the panel's; a chip overrides it here
  const [duty, setDuty] = useState<DutyMode>('ex_duty')
  const tfDef = timeframe(tf)
  const rupee = isRupee(kUnit)
  const longDaily = tfDef.source === '1d' && (tfDef.days == null || tfDef.days > KITCO_SHORT_DAYS)
  const dailyFrom = longDaily ? KITCO_ALL_FROM : shiftDays(today, -(KITCO_SHORT_DAYS + 10))
  const dailyK = useGoldLoad(() => maybe(tfDef.source === '1d', () => longDaily
    ? memoGet(`kitco:GC=F:1d:${KITCO_ALL_FROM}`, 15 * 60_000, () => getGoldBars(BARS_SYMBOL, '1d', { from: KITCO_ALL_FROM }))
    : getGoldBars(BARS_SYMBOL, '1d', { from: dailyFrom })), [tfDef.source, longDaily, dailyFrom], 15 * 60_000)
  const inrDaily = useGoldLoad(() => maybe(rupee, () => longDaily
    ? memoGet(`kitco:INR=X:1d:${KITCO_ALL_FROM}`, 15 * 60_000, () => getGoldBars('INR=X', '1d', { from: KITCO_ALL_FROM }))
    : getGoldBars('INR=X', '1d', { from: dailyFrom })), [rupee, longDaily, dailyFrom], 15 * 60_000)
  // the 1-minute rupee bars load for every rupee window: the 1-minute points on 24 h / 3 days AND today's last stored minute at
  // the end of a daily window convert at the same minute's rate, so the line's last value is one number on every window
  const inr1m = useGoldLoad(() => maybe(rupee, () => getGoldBars('INR=X', '1m')), [rupee], BARS_MS)
  const fx: FxPt[] = useMemo(() => mergeFx(dailyFxPoints(inrDaily.data?.bars ?? []),
    (inr1m.data?.bars ?? []).filter(b => b.c != null).map(b => ({ ms: barMs(b.ts), v: b.c as number })).sort((a, b) => a.ms - b.ms)), [inrDaily.data, inr1m.data])
  // D5: a DAILY close converts at the INR=X close of its own date (the same rule on every timeframe)
  const fxDaily: DailyFx[] = useMemo(() => dailyFxRows(inrDaily.data?.bars ?? []), [inrDaily.data])
  const dutyRate = useMemo(() => ({ pct: fair?.duty_pct ?? null, effective: fair?.duty_effective ?? null }), [fair?.duty_pct, fair?.duty_effective])
  const kconv: Conv = useMemo(() => (v: number, ms?: number) => {
    const t = ms ?? Date.now()
    const inr = rupee ? (fxAsOf(fx, t) ?? (fx.length ? null : usdinr)) : null
    const mult = rupee ? (duty === 'duty_paid' ? dutyMultiplier(istDate(t), dutyRate) : 1) : 1
    return kitcoConvert(v, kUnit, inr, mult)
  }, [rupee, fx, usdinr, duty, dutyRate, kUnit])
  const kdp = kitcoDp(kUnit)
  const kLabel = `${KITCO_UNIT_LABEL[kUnit]}${rupee ? (duty === 'duty_paid' ? ' duty-paid' : ' landed') : ''}`
  // the plotted window: 3 days from the 1-minute bars, longer windows from the daily closes (+ today's last stored minute)
  const lastBarMs = data?.bars?.length ? barMs(data.bars[data.bars.length - 1].ts) : null
  const rawPts = useMemo(() => {
    if (tfDef.source === '1m') return (data?.bars ?? []).filter(b => b.c != null).map(b => ({ ms: barMs(b.ts), usd: b.c as number }))
    const d: { ms: number; usd: number; date?: string }[] = (dailyK.data?.bars ?? []).filter(b => b.c != null).map(b => ({ ms: Date.parse(`${String(b.ts).slice(0, 10)}T00:00:00Z`), usd: b.c as number, date: String(b.ts).slice(0, 10) }))
    const lastDaily = d[d.length - 1]
    const lastMin = data?.bars?.[data.bars.length - 1]
    // today's last stored MINUTE is a timed point (no `date`): it converts at the latest rate at or before its minute
    if (lastMin?.c != null && lastBarMs != null && (!lastDaily || istDate(lastBarMs) > (lastDaily.date ?? ''))) d.push({ ms: lastBarMs, usd: lastMin.c })
    return d
  }, [tfDef.source, data, dailyK.data, lastBarMs])
  const endMs = rawPts.length ? rawPts[rawPts.length - 1].ms : null
  const startMs = tfDef.days != null && endMs != null ? endMs - tfDef.days * DAY_MS : null
  const kser = useMemo(() => kitcoSeries(rawPts, { unit: kUnit, duty, fx, dutyRate, startMs, fxDaily }), [rawPts, kUnit, duty, fx, dutyRate, startMs, fxDaily])
  // one daily close in the plotted unit at its own date's rate (D5): the dashed line, the stats' base and the legend use it
  const closeIn = useMemo(() => (usd: number, date: string) => dailyCloseIn(usd, date, kUnit, duty, fxDaily, dutyRate), [kUnit, duty, fxDaily, dutyRate])
  // 24 h: today's Globex-day points; the change is vs the previous session's stored close (both in the plotted unit)
  const todayPts: KPt[] = useMemo(() => (groups24[groups24.length - 1]?.pts ?? []).map(p => ({ ms: p.ms, v: kconv(p.c, p.ms) })).filter((p): p is KPt => p.v != null), [groups24, kconv])
  const prevCloseK = prevClose ? closeIn(prevClose.c, prevClose.date) : null  // the close at its own DATE's rate: the same number as on 'all' (D5)
  const intraday = tf === '24h' || tf === '3d'
  const winPts = tf === '24h' ? todayPts : kser.pts
  const kstats0 = useMemo(() => kitcoStats(winPts, intraday ? prevCloseK : null), [winPts, intraday, prevCloseK])
  // 24 h: the window's high / low are the 1-minute bars' highs and lows — the same numbers the chart's hi / lo markers print
  // (one number per quantity on the page, §f.6), converted at each bar's own rupee rate
  // 3 days uses the same 1-minute highs / lows over its window, so a 3-day high is never below the 24 h high (one definition)
  const kstats = useMemo(() => {
    if (!intraday || !kstats0) return kstats0
    let hi = kstats0.hi, lo = kstats0.lo, hiMs = kstats0.hiMs, loMs = kstats0.loMs
    const bump = (hv: number | null | undefined, lv: number | null | undefined, ms: number) => {
      const h = hv != null ? kconv(hv, ms) : null, l = lv != null ? kconv(lv, ms) : null
      if (h != null && h > hi) { hi = h; hiMs = ms }
      if (l != null && l < lo) { lo = l; loMs = ms }
    }
    if (tf === '24h') for (const p of groups24[groups24.length - 1]?.pts ?? []) bump(p.h, p.l, p.ms)
    else for (const b of data?.bars ?? []) { const ms = barMs(b.ts); if (startMs == null || ms >= startMs) bump(b.h, b.l, ms) }
    return { ...kstats0, hi, lo, hiMs, loMs }
  }, [intraday, tf, kstats0, groups24, kconv, data, startMs])
  const longDates = tfDef.source === '1d' && (tfDef.days == null || tfDef.days > 120)
  const whenLabel = (ms: number) => tfDef.source === '1d' ? `${dayLabel(istDate(ms))}${longDates ? ` ${istDate(ms).slice(0, 4)}` : ''}` : tf === '3d' ? `${dayLabel(istDate(ms))} ${fmtHM(istMinutes(ms))}` : fmtHM(istMinutes(ms))
  const drawn = useMemo(() => decimate(kser.pts, 1600), [kser.pts])
  const firstStored = tfDef.source === '1d' ? (dailyK.data?.bars?.[0]?.ts ?? null) : null
  const kLoad = tfDef.source === '1d' ? dailyK : bars
  const kNotes: string[] = []
  if (tf === 'all' && firstStored) kNotes.push(`stored GC=F daily history begins ${dayLabel(String(firstStored))} ${String(firstStored).slice(0, 4)} (Yahoo) — Kitco's all-time chart starts earlier (link)`)
  if (rupee && kser.dropped > 0 && tf !== '24h') {
    const firstFx = fx[0]?.ms
    kNotes.push(duty === 'duty_paid' && dutyRate.effective
      ? `duty-paid applies the dated ${fmtFixed(dutyRate.pct, 0)} % only from ${dayLabel(dutyRate.effective)} ${dutyRate.effective.slice(0, 4)}: the store keeps no duty history, so earlier points are not drawn (${kser.dropped} dropped)`
      : `the rupee line starts ${firstFx ? `${dayLabel(istDate(firstFx))} ${istDate(firstFx).slice(0, 4)}` : 'when INR=X is stored'} (stored INR=X history) — ${kser.dropped} earlier points not drawn`)
  }
  if (rupee && duty === 'duty_paid' && !dutyRate.effective) kNotes.push('no dated duty in this page load: duty-paid cannot be drawn')
  const dp = unitDp(unit)
  const conv = (v: number | null | undefined) => (v == null ? null : convertUsdOz(v, unit, usdinr))
  const tapeCols: Column<Bar>[] = [
    { key: 'ts', label: 'IST · NY', render: b => { const m = istMinutes(barMs(b.ts)); return <span style={{ fontFamily: T.mono }}>{fmtHM(m)} <span style={{ color: T.dim }}>{fmtHM(istToNy(m, usDst))}</span></span> } },
    { key: 'c', label: `last ${UNIT_LABEL[unit]}`, align: 'right', render: b => <span style={{ color: T.bright }}>{fmtFixed(conv(b.c), dp)}</span> },
    { key: 'd', label: 'Δ', align: 'right', render: b => { const d = b.c != null && b.o != null ? (conv(b.c) ?? 0) - (conv(b.o) ?? 0) : null; return <span style={{ color: d == null ? T.muted : d > 0 ? T.green : d < 0 ? T.red : T.muted }}>{fmtSigned(d, dp)}</span> } },
    { key: 'r', label: 'range', align: 'right', render: b => <span style={{ color: T.muted }}>{b.h != null && b.l != null ? fmtFixed((conv(b.h) ?? 0) - (conv(b.l) ?? 0), dp) : '—'}</span> },
    { key: 'v', label: 'volume (contracts)', align: 'right', render: b => <span style={{ color: T.muted }}>{fmtCount(b.v)}</span> },
  ]
  const chartBadge = 'arithmetic'
  const dayCount = groups.length

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <GoldPanel id="d.24h" title={`Gold chart · ${tfDef.label} · COMEX ${tfDef.source === '1m' ? 'GC1' : 'GC1 daily'}`} badge={chartBadge} layer={layer} accent={T.amber}
        catalog={catalog} series={['BARS_1M', 'COMEX_GC_FRONT', ...(rupee ? ['USDINR_CLOSE'] : [])]}
        subtitle={<>{tf === '24h' ? `${res} line · Globex day` : tfDef.source === '1m' ? '1-minute bars, last 3 days' : 'stored daily closes'} · {comexCode(BARS_SYMBOL)} (continuous front; the matched month is {comexMonthLabel(symbol)}){live ? ` · last trade as of ${istClock(live.as_of)}` : ''}{rupee ? (tfDef.source === '1d' ? ' · ₹ at the INR=X close of each date' : ' · ₹ at each minute\'s USD/INR; closes at their date\'s INR=X close') : ''}</>}
        freshness={tfDef.source === '1d' ? (dailyK.data?.freshness ?? null) : data ? (data.freshness ?? { state: live ? 'delayed' : 'stale', source: 'gold_bars_intraday', as_of: live?.as_of ?? null }) : null}
        catalogRow={catalog.COMEX_GC_FRONT ?? null}
        copyB={<>Kitco&apos;s chart, from what this terminal stores: pick a window and a unit. On 24 h the dotted line is yesterday on the same clock, the dashed line the previous session&apos;s close (a Yahoo daily close, not an exchange settlement — see <Term t="settlement by session" />) and the bands show which centre was trading. Rupee prices: each minute at that minute&apos;s dollar rate, each daily close at that day&apos;s closing rate; duty-paid adds the dated import duty. Dollar prices use Western grouping (132,339), rupees Indian (₹1,32,339).</>}
        copyP="GC=F (continuous front future, rolls before first notice) from gold_bars_intraday (1-minute) and gold_daily_bars (daily, Yahoo, not settlement); ₹ = $/oz × USD/INR × 10 ÷ 31.1034768 — a daily close at the INR=X close of its own date (so a date's close is the same rupee number on every window), a 1-minute point at the latest stored 1-minute INR=X at or before it; duty-paid × (1 + duty) only from the duty's effective date (no duty history is stored); USD/kg = $/oz × 1000 ÷ 31.1034768. High/low/change are of the plotted series; change vs the previous stored close on 24 h and 3 days, vs the window's first close otherwise. Axis on 24 h = the Globex day (18:00 ET → 17:00 ET), bands DST-aware (lib/gold/sessions.ts)."
        right={<>
          <a href={KITCO_URL} target="_blank" rel="noreferrer" data-gold-kitco-link title="Kitco's own gold chart — a link only: the terminal never fetches kitco.com (terms; PLAN 0.1 #6)" style={{ textDecoration: 'none' }}><Chip color={T.cyan}>Kitco ↗</Chip></a>
          {tf === '24h' && <>
            <Chip color={T.amber} active={res === '1m'} onClick={() => setRes('1m')}>1m</Chip>
            <Chip color={T.amber} active={res === '5m'} onClick={() => setRes('5m')}>5m</Chip>
            <Chip color={T.muted} active={showPrev} onClick={() => setShowPrev(v => !v)} title="previous day as a dotted overlay">prev day</Chip>
            <Chip color={T.muted} active={showBands} onClick={() => setShowBands(v => !v)} title="Sydney/Tokyo · Shanghai · London · New York · MCX">sessions</Chip>
          </>}
        </>}>
        {/* Kitco's timeframes and units */}
        <div data-gold-kitco-controls style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 6px', alignItems: 'center', marginBottom: 6 }}>
          <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>WINDOW</span>
          {KITCO_TIMEFRAMES.map(t => <Chip key={t.key} color={T.amber} active={tf === t.key} onClick={() => setTf(t.key)} title={t.source === '1m' ? 'stored 1-minute bars' : 'stored daily closes'}>
            <span data-gold-kitco-tf={t.key}>{t.label}</span></Chip>)}
          <span style={{ flex: 1 }} />
          <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>UNIT</span>
          {KITCO_UNITS.map(u => <Chip key={u} color={T.cyan} active={kUnit === u} onClick={() => setKUnit(u)}><span data-gold-kitco-unit={u}>{KITCO_UNIT_LABEL[u]}</span></Chip>)}
          {rupee && <>
            <Chip color={T.violet} active={duty === 'ex_duty'} onClick={() => setDuty('ex_duty')} title="landed: COMEX × USD/INR, no import duty"><span data-gold-kitco-duty="ex_duty">ex-duty</span></Chip>
            <Chip color={T.violet} active={duty === 'duty_paid'} onClick={() => setDuty('duty_paid')} title={`landed × (1 + the dated duty${dutyRate.pct != null ? ` ${fmtFixed(dutyRate.pct, 0)} %` : ''}${dutyRate.effective ? ` since ${dayLabel(dutyRate.effective)}` : ''}; confirm at CBIC, O-3)`}><span data-gold-kitco-duty="duty_paid">duty-paid</span></Chip>
          </>}
        </div>
        {/* the window's numbers: high · low · change · previous close */}
        <div data-gold-kitco-stats style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 16px', fontFamily: T.mono, fontSize: 10.5, color: T.muted, marginBottom: 4 }}>
          {kstats ? <>
            <span>{tfDef.label} high <b style={{ color: T.text }}>{fmtKitco(kstats.hi, kdp, kUnit)}</b> {whenLabel(kstats.hiMs)}</span>
            <span>low <b style={{ color: T.text }}>{fmtKitco(kstats.lo, kdp, kUnit)}</b> {whenLabel(kstats.loMs)}</span>
            <span data-gold-kitco-change>change <b style={{ color: kstats.chg > 0 ? T.green : kstats.chg < 0 ? T.red : T.text }}>{fmtKitcoSigned(kstats.chg, kdp, kUnit)} ({fmtSignedPctSp(kstats.chgPct, 2)})</b>
              {' '}{kstats.baseKind === 'prev_close' ? `vs the ${prevClose ? dayLabel(prevClose.date) : 'previous'} COMEX close (Yahoo daily, the dashed line)` : `vs the window's first close${kser.firstMs ? ` (${dayLabel(istDate(kser.firstMs))} ${istDate(kser.firstMs).slice(0, 4)})` : ''}`}</span>
            {kstats.baseKind === 'prev_close' && overview?.strip?.comex_live_chg_pct != null && <span data-gold-kitco-strip-ref style={{ color: T.dim }} title="two references, two instruments: this panel is GC1 (continuous front) vs its previous daily close; the header strip is the matched month vs the 30-min reference before the last MCX close">
              the header strip&apos;s COMEX Δ is {overview.strip.comex_ref_note ?? 'vs the 30-min reference before the last MCX close'} (matched month)</span>}
            <span style={{ color: T.dim }}>{kLabel}</span>
          </> : <span style={{ color: T.dim }}>no stored points in this window yet</span>}
        </div>
        <Pending s={kLoad} label={tfDef.source === '1m' ? 'intraday bars' : 'daily bars'}>
          {tf === '24h' && dayCount === 0 && <NoVerdict what="no 1-minute bars stored yet — the 5-minute job fills gold_bars_intraday from the day it starts" />}
          {tf === '24h' && dayCount > 0 && <>
            {/* W3 / C2: the ExpandableChart shell (crosshair legend, FIT = zoom reset, ⛶ expand); the chart itself stays SVG v2 */}
            <ExpandableChart title="24 h · Globex day" height={300}>
              {sz => <IntradayChart box={sz} groups={groups24} usDst={usDst} ukDst={ukDst} conv={kconv} unitLabel={kLabel} dp={kdp} settle={settle} settleValue={serverSettle ? undefined : prevCloseK} settleLabel={settleLabel}
                showPrev={showPrev} showBands={showBands} mode="24h" live={live} sge={sgePts} />}
            </ExpandableChart>
            <div data-gold-legend style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 14px', fontFamily: T.mono, fontSize: 10.5, color: T.muted, marginTop: 4 }}>
              {kitcoLegend(groups, daily, live, closeIn, kdp, serverSettle ? null : prevClose?.date ?? null, kUnit).map(l => <span key={l}>{l}</span>)}
              {showBands && <span style={{ color: T.dim }}>bands: Sydney/Tokyo · Shanghai (SGE) · London · New York · hatched = CME maintenance 17:00–18:00 ET</span>}
            </div>
          </>}
          {tf !== '24h' && <ExpandableChart title={`${tfDef.label} · stored closes`} height={300}>
            {sz => <TimeChart box={sz} pts={drawn} dp={kdp} unitLabel={kLabel} prevClose={tf === '3d' ? prevCloseK : null}
              prevCloseLabel={prevClose ? `${dayLabel(prevClose.date)} close` : 'prev close'} label={`gold, ${tfDef.label}, ${kLabel}`}
              hi={kstats ? { v: kstats.hi, ms: kstats.hiMs } : null} lo={kstats ? { v: kstats.lo, ms: kstats.loMs } : null} />}
          </ExpandableChart>}
          {kNotes.length > 0 && <div data-gold-kitco-notes style={{ fontSize: 10, color: T.muted, marginTop: 4, lineHeight: 1.5 }}>{kNotes.map(n => <div key={n}>· {n}</div>)}</div>}
          <div style={{ fontSize: 9.5, color: T.dim, marginTop: 4 }}>COMEX front future (GC=F), not spot: it runs a few dollars above Kitco&apos;s spot price (carry to the front month). Source: the terminal&apos;s store (Yahoo, via data-service), never kitco.com.</div>
        </Pending>
      </GoldPanel>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(440px, 1fr))', alignItems: 'start' }}>
        <GoldPanel id="d.3day" title="3 days overlaid" subtitle="one 24-h IST axis, one colour each" badge="context" layer={layer} accent={T.cyan}
          catalog={catalog} series={['BARS_1M']}
          freshness={data ? (data.freshness ?? { state: 'delayed', source: 'gold_bars_intraday' }) : null}
          copyB="Today's path against the last two days, hour by hour: does the move repeat at the same time of day?"
          copyP="Three CME trade days on the Globex-day axis; no inference is drawn from the overlay (context).">
          <Pending s={bars} label="intraday bars">
            {dayCount < 2 ? <NoVerdict what={`${dayCount} day${dayCount === 1 ? '' : 's'} stored; three are needed`} />
              : <ExpandableChart title="3-day overlay" height={280}>
                  {sz => <IntradayChart box={sz} groups={groups} usDst={usDst} ukDst={ukDst} conv={v => convertUsdOz(v, unit, usdinr)} unitLabel={UNIT_LABEL[unit]} dp={unitDp(unit)} settle={null} settleLabel="" showPrev={false}
                    showBands={showBands} mode="3day" live={null} sge={null} />}
                </ExpandableChart>}
            <div style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, marginTop: 4 }}>
              {groups.slice(-3).map((g, i, a) => <span key={g.date} style={{ marginRight: 12, color: [T.violet, T.cyan, T.amber][i + (3 - a.length)] }}>■ {dayLabel(g.date)}</span>)}
            </div>
          </Pending>
        </GoldPanel>

        <GoldPanel id="d.sge" title="Shanghai (SGE Au99.99)" subtitle="delayed intraday · drawn on the Shanghai day and night sessions" badge="context" layer={layer} accent={T.violet}
          freshness={sge.data ? (sge.data.freshness ?? { state: 'delayed', source: 'SGE delayed quotes' }) : { state: 'unavailable', reason: sge.error ?? 'not stored yet' }}
          catalog={catalog} series={['SGE_DAILY', 'BARS_1M', 'FX_CNY']}
          copyB="Does Shanghai lead or lag the COMEX print? The violet dotted line on the 24-h chart is SGE during its hours, in the same unit as the gold line."
          copyP={`SGE delayed quotations (D4), stored in CNY/g and converted by the server: ${sge.data?.conversion ?? 'CNY/g × 31.1034768 ÷ USDCNY — one vintage per drawn session (the latest on or before that session’s first Shanghai date)'}. ONE rate per session, so the line cannot step on an FX revision at Beijing midnight without a price move. The overlay is drawn only when the payload says $/oz, only for the COMEX day on screen and only when it is within 25 % of that day’s median — a foreign unit never sets this chart’s axis. Displayed with attribution (O-1), never re-served.`}>
          {sgePts && sgePts.length > 1 && sgeDay && sgeBar
            ? <div data-gold-sge-overlay style={{ fontSize: 11, color: T.text }}>{sgePts.length} bars · {dayLabel(sgeDay.date)} · last{' '}
                {sgeBar.c_cny_g != null && <span data-gold-sge-native>¥{fmtFixed(sgeBar.c_cny_g, 2)}/g ≈ </span>}
                <b>{fmtInUnit(sgeBar.c, unit, usdinr)}</b>
                {/* the session's ONE rate, named once: every bar of this drawn session converts at it */}
                {sgeBar.usdcny != null && <span data-gold-sge-rate style={{ color: T.dim }}> — the whole session at USDCNY {fmtFixed(sgeBar.usdcny, 4)}{sgeBar.usdcny_date ? ` of ${dayLabel(sgeBar.usdcny_date)}` : ''}{sge.data?.fx?.series ? ` (${sge.data.fx.series})` : ''}{sge.data?.fx?.partial && sgeBar.usdcny_date === sge.data.fx.report_date ? ', itself a partial print' : ''}</span>}
                {!!sge.data?.dropped_no_fx && <span data-gold-sge-dropped style={{ color: T.dim }}> · {sge.data.dropped_no_fx} row{sge.data.dropped_no_fx === 1 ? '' : 's'} not served (no stored USDCNY on or before their session)</span>}
                {' '}— overlaid above in violet. <span style={{ color: T.dim }}>Source: Shanghai Gold Exchange (sge.com.cn), displayed with attribution.</span></div>
            : <div data-gold-sge-empty style={{ display: 'grid', gap: 6 }}>
                {/* not a verdict question (the series is PUBLISH-CONTEXT): the page says WHY there is no overlay and links the source (C-TRADER-26) */}
                <div style={{ fontSize: 11, color: T.muted }}>{sgeWhyNoOverlay}</div>
                <LinkTile name="SGE delayed quotes" url="https://en.sge.com.cn/data_DelayedQuotes" what="Au99.99 / Au(T+D), delayed" why="the publisher's own page; nothing is fetched by the terminal from here" />
              </div>}
        </GoldPanel>
      </div>

      <GoldPanel id="d.quadrant" title="Yesterday's OI × price read" subtitle={`COMEX product OI (T+1) · MCX ${sel.family} OI (07:35)`} badge="context" evidence="folklore until G-STUDY-2" layer={layer} accent={T.muted}
        catalog={catalog} series={['CME_VOI', 'MCX_CURVE_ICICI']}
        freshness={quadComex.data ? (quadComex.data.freshness ?? { state: 'delayed', source: 'CME FTP daily_volume', reason: quadComex.data.since ? `since ${quadComex.data.since}` : null }) : null}
        copyB={<>Did the move come with new positions (<Term t="open interest" /> up) or closing ones (OI down)? The four <Term t="OI quadrants" />: long build-up / short build-up / short covering / long unwinding. A day with no OI yet says so — it is not &apos;flat&apos;; a Δ that spans missed sessions is labelled with its span.</>}
        copyP="Product OI, all months summed; roll weeks are mechanical (greyed); 'who' needs the weekly COT. The weekly version scored 1 of 12 cells (G-STUDY); the daily version is untested (G-STUDY-2). CME OI lands T+1 ≈ 15:30 IST.">
        <div style={{ display: 'grid', gap: 14 }}>
          <div>
            <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1, color: T.muted, marginBottom: 4 }}>COMEX GC · product OI</div>
            <Pending s={quadComex} label="COMEX OI">
              <OiQuadrantTape tape={quadComex.data?.quadrant_tape ?? []} days={20} tips={k => tooltips[k]} />
            </Pending>
          </div>
          <div>
            <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1, color: T.muted, marginBottom: 4 }}>MCX {quadMcx.data?.family ?? sel.family} · OI (lots){quadMcx.data?.since ? ` · since ${quadMcx.data.since}` : ''}</div>
            <Pending s={quadMcx} label="MCX OI">
              <OiQuadrantTape tape={quadMcx.data?.quadrant_tape ?? []} days={20} tips={k => tooltips[k]} oiScope={`all ${sel.family} expiries`} />
            </Pending>
          </div>
        </div>
      </GoldPanel>

      <GoldPanel id="d.tape" title="Intraday tape" subtitle="last 12 × 5-minute bars" badge="arithmetic" layer={layer} accent={T.border} pad={0}
        catalog={catalog} series={['BARS_1M']}
        freshness={data ? (data.freshness ?? { state: 'delayed', source: 'gold_bars_intraday' }) : null}
        copyB="The last hour, bar by bar." copyP="5-minute buckets of the stored 1-minute bars (open = first, close = last, range = high − low).">
        <DataTable columns={tapeCols} rows={tape} rowKey={b => String(b.ts)} dense empty="No bars stored yet." exportName="gold-intraday-tape" />
      </GoldPanel>
    </div>
  )
}

export default DailyView
