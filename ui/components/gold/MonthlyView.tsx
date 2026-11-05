'use client'

/**
 * MONTHLY — the long view (PLAN a.5): monthly candles since 2000 on a log axis with a ₹ toggle (m.candles); the return
 * ladder 3 d … 15 y in $, in landed ₹/10 g and in the DXY basket (m.ladder); the seasonality grid with the G-STUDY /
 * G-MACRO H3 caption (m.season, the shared SeasonalityGrid); central-bank net purchases by country with each data month
 * (m.official); monthly physical flows (m.physical); the WGC quarterly balance sheet as stacked bars (m.balance); and the
 * collapsed liquidity block: gold/M2, HY OAS, GPR and inflation-expectation percentiles (m.liquidity).
 *
 * Data: /api/gold/bars interval 1d since 2000 (resampled to months here), /api/gold/series (USD/INR and DXY daily for the
 * ladder, the World Bank monthly average for the pre-2000 seasonality splice, the monthly macro set), /api/gold/flows.
 * Everything is context except the candles and the ladder (arithmetic); nothing is coloured as a buy or a sell and no
 * month is called a signal ("no month passes in both halves", G-STUDY).
 */
import { useMemo, useState } from 'react'
import { Chip, DataTable, KV, Spark, T, fmtFixed, fmtSigned, type Column } from '@/components/terminal'
import { getGoldBars, getGoldFlows, getGoldSeries, memoGet } from '@/lib/gold/api'
import { GRAMS_PER_OZ, PERCENTILE_MIN_N, dayLabel, fmtInr0, fmtSignedPctSp, fmtUsd, percentileText } from '@/lib/gold/format'
import { istDateISO } from '@/lib/format'
import { dailyOhlc, percentileOf, resampleOhlc, returnOver, seasonality, type Ohlc } from '@/lib/gold/sessions'
import type { GoldFlows, GoldSeriesRow, GoldSubViewProps, SeriesPoint } from '@/lib/gold/types'
import { SeasonalityGrid } from './SeasonalityGrid'
import { Term } from './ViewBits'
import { LwCandles } from './WeeklyView'
import { GoldPanel, NoVerdict, Pending, useGoldLoad } from './kit'

/** `/bars` takes Yahoo symbols as data-service stores them (API_CONTRACT §2.4): the continuous front, labelled GC1. */
const DAILY_SYMBOL = 'GC=F'
const SINCE = '2000-01-01'
/** The 26-year payloads (~1.5 MB) are memoised per window for 30 min: a tab revisit remounts the view for free. */
const MEMO_MS = 30 * 60_000
const LADDER: { label: string; days: number }[] = [
  { label: '3 d', days: 3 }, { label: '7 d', days: 7 }, { label: '30 d', days: 30 }, { label: '60 d', days: 60 }, { label: '6 m', days: 182 },
  { label: '1 y', days: 365 }, { label: '5 y', days: 1826 }, { label: '10 y', days: 3652 }, { label: '15 y', days: 5478 },
]
const BALANCE_DEMAND = ['jewellery', 'technology', 'bar_coin', 'etf', 'central_banks', 'otc_other']
const BALANCE_SUPPLY = ['mine', 'recycled', 'hedging']
const BALANCE_COLOR: Record<string, string> = { jewellery: T.amber, technology: T.cyan, bar_coin: T.violet, etf: T.green, central_banks: '#7fb3ff', otc_other: T.muted, mine: T.amber, recycled: T.cyan, hedging: T.muted }

/** Series points → a date-keyed map (the last value per date wins). */
function pointMap(row: GoldSeriesRow | undefined): Map<string, number> {
  return new Map((row?.points ?? []).map(p => [p.report_date, p.value]))
}

/** The last value on or before `date` from a sorted date-keyed series (null before the first point). */
function valueOnOrBefore(pts: SeriesPoint[], date: string): number | null {
  let lo = 0, hi = pts.length - 1, best = -1
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (pts[mid].report_date <= date) { best = mid; lo = mid + 1 } else hi = mid - 1 }
  return best >= 0 ? pts[best].value : null
}

/** Daily candles rescaled by a daily factor series (USD/INR → landed ₹/10 g; DXY → gold in the basket). */
export function rescaleDaily(daily: readonly Ohlc[], factor: SeriesPoint[], fn: (px: number, f: number) => number): Ohlc[] {
  const out: Ohlc[] = []
  for (const k of daily) {
    const f = valueOnOrBefore(factor, k.date)
    if (f == null) continue
    out.push({ date: k.date, o: fn(k.o, f), h: fn(k.h, f), l: fn(k.l, f), c: fn(k.c, f), v: k.v })
  }
  return out
}

export const landedInr10g = (usdOz: number, usdinr: number) => (usdOz * usdinr * 10) / GRAMS_PER_OZ
export const inBasket = (usdOz: number, dxy: number) => (usdOz * dxy) / 100

/** World Bank monthly averages (1971→) spliced in front of the GC monthly closes for the seasonality grid. */
export function spliceMonthly(wb: SeriesPoint[], gc: readonly Ohlc[]): Ohlc[] {
  const first = gc[0]?.date.slice(0, 7) ?? '9999-99'
  const head: Ohlc[] = wb.filter(p => p.report_date.slice(0, 7) < first).map(p => ({ date: p.report_date, o: p.value, h: p.value, l: p.value, c: p.value, v: 0 }))
  return [...head, ...gc]
}

interface OfficialRow { country: string; month: string; oz_mn?: number | null; tonnes?: number | null; chg_oz_mn?: number | null; chg_12m_oz_mn?: number | null }

/** Tonnes per million troy ounces. */
const T_PER_MOZ = GRAMS_PER_OZ
/** No central bank holds more than ~300 Moz (USA 261.5): a larger `oz_mn` is raw ounces or a unit error at source — flagged, never drawn (C-TRADER-6 / C-DATA-5). */
export const OFFICIAL_MOZ_SANE = 1000

export interface NetPurchaseBar { country: string; month: string; t_mm: number | null; t_12m: number | null; unitError: boolean }

/** m.official (PLAN a.5): NET PURCHASES per country — Δ m/m and Δ 12 m in tonnes — from /flows official[]. The holders table is PHYSICAL's (a.7 ph.official): it renders once per page. */
/** The newest data month among the bars (YYYY-MM → its first day, ISO), null when none: the panel's date. */
export function latestMonth(bars: readonly { month?: string | null }[]): string | null {
  const ms = bars.map(b => (b.month ?? '').slice(0, 7)).filter(m => /^\d{4}-\d{2}$/.test(m)).sort()
  return ms.length ? `${ms[ms.length - 1]}-01` : null
}

export function netPurchaseBars(rows: readonly OfficialRow[]): NetPurchaseBar[] {
  return rows.map(r => {
    const unitError = r.oz_mn != null && Math.abs(r.oz_mn) > OFFICIAL_MOZ_SANE
    return {
      country: r.country, month: r.month, unitError,
      t_mm: unitError || r.chg_oz_mn == null || Math.abs(r.chg_oz_mn) > OFFICIAL_MOZ_SANE ? null : r.chg_oz_mn * T_PER_MOZ,
      t_12m: unitError || r.chg_12m_oz_mn == null || Math.abs(r.chg_12m_oz_mn) > OFFICIAL_MOZ_SANE ? null : r.chg_12m_oz_mn * T_PER_MOZ,
    }
  }).sort((a, b) => Math.abs(b.t_mm ?? 0) - Math.abs(a.t_mm ?? 0) || a.country.localeCompare(b.country))
}

function NetPurchases({ bars }: { bars: NetPurchaseBar[] }) {
  const max = Math.max(1, ...bars.map(b => Math.abs(b.t_mm ?? 0)))
  const shown = bars.filter(b => !b.unitError)
  const flagged = bars.filter(b => b.unitError)
  return (
    <div data-gold-netpurchases style={{ display: 'grid', gap: 3, padding: '8px 12px', fontFamily: T.mono, fontSize: 10.5 }}>
      <div style={{ display: 'grid', gridTemplateColumns: '48px 64px minmax(0, 1fr) 76px 76px', gap: 8, color: T.dim, fontSize: 9.5, letterSpacing: .6 }}>
        <span>CTRY</span><span>MONTH</span><span>Δ m/m (t)</span><span style={{ textAlign: 'right' }}>Δ m/m t</span><span style={{ textAlign: 'right' }}>Δ 12 m t</span>
      </div>
      {shown.map(b => (
        <div key={`${b.country}-${b.month}`} style={{ display: 'grid', gridTemplateColumns: '48px 64px minmax(0, 1fr) 76px 76px', gap: 8, alignItems: 'center' }}>
          <span style={{ color: T.text }}>{b.country}</span>
          <span style={{ color: T.muted }}>{b.month}</span>
          <span style={{ position: 'relative', height: 8, background: '#0b0f16' }} title={`${b.country} ${b.month}: ${b.t_mm != null ? `${fmtFixed(b.t_mm, 1)} t m/m` : 'no m/m change'}`}>
            <span style={{ position: 'absolute', top: 0, bottom: 0, left: b.t_mm != null && b.t_mm < 0 ? `${50 - (Math.abs(b.t_mm) / max) * 50}%` : '50%', width: `${(Math.abs(b.t_mm ?? 0) / max) * 50}%`, background: T.muted }} />
            <span style={{ position: 'absolute', top: -2, bottom: -2, left: '50%', borderLeft: `1px solid ${T.borderHi}` }} />
          </span>
          <span style={{ textAlign: 'right', color: T.text }}>{fmtSigned(b.t_mm, 1)}</span>
          <span style={{ textAlign: 'right', color: T.muted }}>{fmtSigned(b.t_12m, 1)}</span>
        </div>
      ))}
      {flagged.length > 0 && <div data-gold-official-flagged style={{ color: T.amber, fontSize: 10, marginTop: 4 }}>not drawn — unit error at source (value is not in million oz): {flagged.map(f => f.country).join(', ')}</div>}
      {shown.length === 0 && flagged.length === 0 && <div style={{ color: T.dim }}>no IMF rows stored yet (the morning job fetches them when due)</div>}
    </div>
  )
}

/** '2026-06-30' → 'Q2 26' (a WGC quarter end as its quarter). */
export function quarterLabel(period: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(period)
  return m ? `Q${Math.ceil(+m[2] / 3)} ${m[1].slice(2)}` : period
}

function BalanceBars({ rows }: { rows: NonNullable<GoldFlows['balance_sheet']> }) {
  const periods = useMemo(() => [...new Set(rows.map(r => r.period))].sort().slice(-24), [rows])
  const by = useMemo(() => {
    const m = new Map<string, Record<string, number>>()
    for (const r of rows) { if (r.tonnes == null) continue; const p = m.get(r.period) ?? {}; p[r.series] = (p[r.series] ?? 0) + r.tonnes; m.set(r.period, p) }
    return m
  }, [rows])
  const max = Math.max(1, ...periods.map(p => { const x = by.get(p) ?? {}; return Math.max(BALANCE_DEMAND.reduce((a, k) => a + (x[k] ?? 0), 0), BALANCE_SUPPLY.reduce((a, k) => a + (x[k] ?? 0), 0)) }))
  const H = 150
  const step = max > 1500 ? 500 : max > 600 ? 200 : 100
  const ticks = Array.from({ length: Math.floor(max / step) }, (_, i) => (i + 1) * step)
  const every = Math.max(1, Math.ceil(periods.length / 8))
  return (
    <div data-gold-balance>
      <div style={{ display: 'grid', gridTemplateColumns: '44px 1fr', gap: 4 }}>
      {/* the tonnage axis (the 5 Nov review: no y-axis, only the end quarters labelled) */}
      <div data-gold-balance-axis style={{ position: 'relative', height: H, fontSize: 9, fontFamily: T.mono, color: T.dim }}>
        {ticks.map(t => <span key={t} style={{ position: 'absolute', right: 2, bottom: `${(t / max) * 100}%`, transform: 'translateY(50%)' }}>{fmtFixed(t, 0)} t</span>)}
        <span style={{ position: 'absolute', right: 2, bottom: 0 }}>0</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${periods.length}, minmax(0, 1fr))`, gap: 3, alignItems: 'end', height: H,
                    backgroundImage: `repeating-linear-gradient(to top, ${T.border} 0 1px, transparent 1px ${(step / max) * H}px)` }}>
        {periods.map(p => {
          const x = by.get(p) ?? {}
          const demand = BALANCE_DEMAND.reduce((a, k) => a + (x[k] ?? 0), 0), supply = BALANCE_SUPPLY.reduce((a, k) => a + (x[k] ?? 0), 0)
          return (
            <div key={p} title={`${p} · demand ${fmtFixed(demand, 0)} t · supply ${fmtFixed(supply, 0)} t\n${BALANCE_DEMAND.map(k => `${k} ${fmtFixed(x[k] ?? 0, 0)}`).join(' · ')}`}
              style={{ display: 'flex', flexDirection: 'column-reverse', height: `${(demand / max) * 100}%`, borderTop: `2px solid ${T.bright}`, position: 'relative' }}>
              {BALANCE_DEMAND.map(k => <div key={k} style={{ height: `${demand ? ((x[k] ?? 0) / demand) * 100 : 0}%`, background: BALANCE_COLOR[k], opacity: 0.8 }} />)}
              <div style={{ position: 'absolute', left: 0, right: 0, top: `${100 - (supply / Math.max(demand, 1)) * 100}%`, borderTop: `1px dashed ${T.cyan}` }} />
            </div>
          )
        })}
      </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `44px repeat(${periods.length}, minmax(0, 1fr))`, gap: 3, fontSize: 8.5, color: T.dim, fontFamily: T.mono, marginTop: 2 }}>
        <span />
        {periods.map((p, i) => <span key={p} style={{ textAlign: 'center', whiteSpace: 'nowrap', overflow: 'hidden' }}>{i % every === 0 || i === periods.length - 1 ? quarterLabel(p) : ''}</span>)}
      </div>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', fontSize: 9.5, color: T.muted, marginTop: 4 }}>
        {BALANCE_DEMAND.map(k => <span key={k}><span style={{ display: 'inline-block', width: 8, height: 8, background: BALANCE_COLOR[k], marginRight: 3 }} />{k.replace('_', ' ')}</span>)}
        <span><span style={{ display: 'inline-block', width: 12, borderTop: `1px dashed ${T.cyan}`, marginRight: 3, verticalAlign: 'middle' }} />supply (mine + recycled + hedging)</span>
      </div>
    </div>
  )
}

export function MonthlyView({ layer, usdinr, tooltips, catalog }: GoldSubViewProps) {
  const today = istDateISO()
  const bars = useGoldLoad(() => memoGet(`bars:${DAILY_SYMBOL}:1d:${SINCE}`, MEMO_MS, () => getGoldBars(DAILY_SYMBOL, '1d', { from: SINCE })), [], 0)
  const fx = useGoldLoad(() => memoGet(`series:USDINR_CLOSE,DXY_CLOSE:D:${SINCE}`, MEMO_MS, () => getGoldSeries(['USDINR_CLOSE', 'DXY_CLOSE'], { freq: 'D', from: SINCE })), [], 0)
  const wb = useGoldLoad(() => memoGet('series:WB_GOLD_MONTHLY_AVG:M', MEMO_MS, () => getGoldSeries(['WB_GOLD_MONTHLY_AVG'], { freq: 'M' })), [], 0)
  const liq = useGoldLoad(() => memoGet('series:liquidity:M', MEMO_MS, () => getGoldSeries(['FRED_M2SL', 'FRED_WM2NS', 'FRED_HY_OAS', 'GPR_MONTHLY', 'FRED_EXPINF10YR', 'FRED_T5YIFR'], { freq: 'M' })), [], 0)
  const flows = useGoldLoad(() => memoGet('flows:24', MEMO_MS, () => getGoldFlows(24)), [], 0)
  const [log, setLog] = useState(true)
  const [inr, setInr] = useState(false)
  const [liqOpen, setLiqOpen] = useState(false)

  const daily = useMemo(() => dailyOhlc(bars.data?.bars ?? []), [bars.data])
  const usdinrPts = useMemo(() => fx.data?.series.find(s => s.series_id === 'USDINR_CLOSE')?.points ?? [], [fx.data])
  const dxyPts = useMemo(() => fx.data?.series.find(s => s.series_id === 'DXY_CLOSE')?.points ?? [], [fx.data])
  const dailyInr = useMemo(() => (usdinrPts.length ? rescaleDaily(daily, usdinrPts, landedInr10g) : []), [daily, usdinrPts])
  const dailyBasket = useMemo(() => (dxyPts.length ? rescaleDaily(daily, dxyPts, inBasket) : []), [daily, dxyPts])
  const monthly = useMemo(() => resampleOhlc(inr ? dailyInr : daily, 'M'), [daily, dailyInr, inr])
  const monthlyUsd = useMemo(() => resampleOhlc(daily, 'M'), [daily])
  const wbPts = useMemo(() => wb.data?.series.find(s => s.series_id === 'WB_GOLD_MONTHLY_AVG')?.points ?? [], [wb.data])
  const seasonRows = useMemo(() => seasonality(spliceMonthly(wbPts, monthlyUsd)), [wbPts, monthlyUsd])
  const seasonSince = wbPts[0]?.report_date.slice(0, 4) ?? monthlyUsd[0]?.date.slice(0, 4)
  const tip = (k: string) => tooltips[k]

  const ladderRows = useMemo(() => LADDER.map(h => ({
    label: h.label, usd: returnOver(daily, h.days), inr: returnOver(dailyInr, h.days), basket: returnOver(dailyBasket, h.days),
    spark: daily.slice(-Math.max(5, Math.min(daily.length, Math.round(h.days * 5 / 7)))).map(k => k.c),
  })), [daily, dailyInr, dailyBasket])
  const ladderCols: Column<(typeof ladderRows)[number]>[] = [
    { key: 'label', label: 'Horizon', render: r => <span style={{ color: T.text }}>{r.label}</span> },
    { key: 'usd', label: 'gold $/oz', align: 'right', render: r => <span style={{ color: r.usd == null ? T.dim : r.usd > 0 ? T.green : r.usd < 0 ? T.red : T.muted }}>{fmtSignedPctSp(r.usd, 1)}</span> },
    ...(usdinrPts.length ? [{ key: 'inr', label: 'landed ₹/10 g', align: 'right' as const, title: tip('landed'), render: (r: (typeof ladderRows)[number]) => <span style={{ color: r.inr == null ? T.dim : r.inr > 0 ? T.green : r.inr < 0 ? T.red : T.muted }}>{fmtSignedPctSp(r.inr, 1)}</span> }] : []),
    ...(dxyPts.length ? [{ key: 'basket', label: 'in the DXY basket', align: 'right' as const, title: tip('kgx_pure_gold'), render: (r: (typeof ladderRows)[number]) => <span style={{ color: r.basket == null ? T.dim : r.basket > 0 ? T.green : r.basket < 0 ? T.red : T.muted }}>{fmtSignedPctSp(r.basket, 1)}</span> }] : []),
    { key: 'spark', label: 'path', render: r => (r.spark.length > 2 ? <Spark values={r.spark} width={90} height={18} color={T.dim} /> : null) },
  ]

  const official = (flows.data?.official ?? []) as OfficialRow[]
  const purchases = useMemo(() => netPurchaseBars(official), [official])
  const pboc = useMemo(() => {
    const cn = official.filter(r => /CHN|China/i.test(r.country)).sort((a, b) => a.month.localeCompare(b.month))
    let streak = 0
    for (let i = cn.length - 1; i >= 0 && (cn[i].chg_oz_mn ?? 0) > 0; i--) streak++
    return cn.length ? { streak, month: cn[cn.length - 1].month } : null
  }, [official])
  const pm = flows.data?.physical_monthly
  const liqRow = (id: string) => liq.data?.series.find(s => s.series_id === id)
  // percentiles print only with ≥ PERCENTILE_MIN_N observations; fewer → 'n obs. since …' (C-TRADER-23 / C-BEGINNER-19)
  const liqItems = useMemo((): [string, string, string?][] => {
    const m2 = liqRow('FRED_M2SL') ?? liqRow('FRED_WM2NS')
    const m2pts = m2?.points ?? []
    const ratio: { date: string; v: number }[] = []
    for (const k of monthlyUsd) { const v = valueOnOrBefore(m2pts, k.date); if (v) ratio.push({ date: k.date, v: k.c / v }) }
    const last = ratio[ratio.length - 1]
    const pct = (row: GoldSeriesRow | undefined) => {
      const pts = row?.points ?? []
      const v = pts[pts.length - 1]?.value
      if (v == null) return '—'
      return `${fmtFixed(v, 2)} · ${percentileText(percentileOf(pts.map(p => p.value), v), null, pts.length, pts[0]?.report_date.slice(0, 7))}`
    }
    return [
      ['gold / M2', last ? (ratio.length >= PERCENTILE_MIN_N ? `${fmtFixed(last.v, 3)} · ${percentileText(percentileOf(ratio.map(r => r.v), last.v), `${ratio.length} months`)}` : `${fmtFixed(last.v, 3)} · ${ratio.length} months since ${ratio[0].date.slice(0, 7)} — too few for a percentile`) : '—'],
      ['HY OAS (%; × 100 = bp)', pct(liqRow('FRED_HY_OAS'))],
      ['GPR monthly', pct(liqRow('GPR_MONTHLY'))],
      ['10-y inflation expectation (Cleveland Fed)', pct(liqRow('FRED_EXPINF10YR'))],
      ['5y5y forward inflation', pct(liqRow('FRED_T5YIFR'))],
    ]
  }, [liq.data, monthlyUsd])
  // the ₹ and basket columns need the stored USD/INR and DXY daily history: hidden with one reason until it exists (C-BEGINNER-15)
  const haveInr = usdinrPts.length > 0, haveBasket = dxyPts.length > 0
  const ladderNote = !haveInr || !haveBasket
    ? `${!haveInr && !haveBasket ? 'the ₹ and DXY-basket columns' : !haveInr ? 'the ₹ column' : 'the DXY-basket column'} fill as the USD/INR${!haveBasket ? ' and DXY' : ''} daily history accrues${usdinrPts[0] || dxyPts[0] ? ` (stored since ${[usdinrPts[0]?.report_date, dxyPts[0]?.report_date].filter(Boolean).sort()[0]})` : ' (no daily points stored yet: the yahoo_daily job writes them)'}`
    : null

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {/* m.candles */}
      <GoldPanel id="m.candles" title="Monthly candles since 2000" badge="arithmetic" layer={layer} accent={T.amber} pad={8}
        subtitle={<>{inr ? 'landed ₹/10 g (no duty, month-end USD/INR)' : '$/oz'} · {log ? 'log' : 'linear'} axis · COMEX front (continuous)</>}
        freshness={bars.data ? (bars.data.freshness ?? { state: 'delayed', source: 'gold_daily_bars', as_of: daily[daily.length - 1]?.date ?? null }) : null}
        reportDate={daily[daily.length - 1]?.date ?? null} catalog={catalog} series={inr ? ['COMEX_GC_FRONT', 'USDINR_CLOSE'] : ['COMEX_GC_FRONT']}
        copyB="The whole move since 2000, one candle per month. The ₹ toggle shows what the same ounce cost to land in India before duty."
        copyP="Daily GC=F closes resampled to calendar months (open = first, close = last); log axis so 2001 and 2026 moves read as percentages; the ₹ series multiplies each day by that day's stored USD/INR close × 10/31.1035 (no duty, no premium)."
        right={<>
          <Chip color={T.amber} active={log} onClick={() => setLog(v => !v)} title="logarithmic price axis">LOG</Chip>
          <Chip color={T.amber} active={inr} onClick={() => setInr(v => !v)} title="landed ₹/10 g (needs the stored USD/INR history)">₹</Chip>
        </>}>
        <Pending s={bars} label="daily bars since 2000">
          {monthly.length < 2 ? <NoVerdict what={inr && !usdinrPts.length ? 'the USD/INR history is not stored yet' : 'daily bars since 2000 are stored by the one-off Yahoo history pull (PLAN c.4)'} />
            : <LwCandles candles={monthly} log={log} dp={inr ? 0 : 1} height={300} mondays={false} volume={false} />}
        </Pending>
      </GoldPanel>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(440px, 1fr))', alignItems: 'start' }}>
        {/* m.ladder */}
        <GoldPanel id="m.ladder" title="Return ladder" badge="context" layer={layer} accent={T.cyan} pad={0} catalog={catalog} series={['COMEX_GC_FRONT', 'USDINR_CLOSE', 'DXY_CLOSE']}
          subtitle={`to ${daily.length ? dayLabel(daily[daily.length - 1].date) : '—'}${usdinr != null ? ` · USD/INR now ${fmtFixed(usdinr, 2)}` : ''}`}
          freshness={bars.data ? (bars.data.freshness ?? { state: 'delayed', source: 'gold_daily_bars' }) : null}
          copyB={<>How gold did over each horizon in dollars, as the <Term t="landed price" /> in India (₹/10 g before duty), and with the dollar&apos;s own move taken out (the <Term t="DXY" /> basket).</>}
          copyP="Simple returns from the close on or before the horizon's start to the last close; ₹ = $/oz × USD/INR × 10/31.1035 per day; basket = $/oz × DXY/100 (Kitco's gold-in-currencies idea with DXY weights, G-KITCO §1.3).">
          <Pending s={bars} label="daily bars">
            <DataTable columns={ladderCols} rows={ladderRows} rowKey={r => r.label} dense exportName="gold-return-ladder" empty="No daily history stored yet." />
            {ladderNote && <div data-gold-ladder-note style={{ padding: '6px 12px', fontSize: 10, color: T.dim, borderTop: `1px solid ${T.border}` }}>{ladderNote}</div>}
          </Pending>
        </GoldPanel>

        {/* m.season */}
        <GoldPanel id="m.season" title="Seasonality" badge="context" evidence="G-STUDY / G-MACRO H3: no month passes in both halves" layer={layer} accent={T.violet}
          subtitle={seasonSince ? `since ${seasonSince}` : undefined}
          freshness={bars.data ? (bars.data.freshness ?? { state: 'delayed', source: 'gold_daily_bars' }) : null}
          catalog={catalog} series={['WB_GOLD_MONTHLY_AVG', 'COMEX_GC_FRONT']}
          copyB={<>The average month, month by month, with how often it was positive (the <Term t="hit rate" />). Hover a cell for the spread of outcomes — it dwarfs the average; no month is a rule.</>}
          copyP="World Bank monthly averages (1971→) spliced with GC=F monthly closes; mean, hit rate, p10/p90 and the t-stat per calendar month; walk-forward best-6-months +0.3 %/yr (G-STUDY): context, never a rule.">
          <Pending s={bars} label="monthly history">
            {seasonRows.every(r => r.n === 0) ? <NoVerdict what="needs monthly history" />
              : <SeasonalityGrid rows={seasonRows} since={seasonSince} source={wbPts.length ? 'World Bank + GC=F' : 'GC=F'} tips={tip} />}
          </Pending>
        </GoldPanel>

        {/* m.official */}
        <GoldPanel id="m.official" title="Official sector · net purchases" badge="context" layer={layer} accent={T.muted} pad={0}
          subtitle={<>Δ m/m and Δ 12 m in tonnes per central bank{pboc ? <> · <Term t="PBoC" /> streak {pboc.streak} month{pboc.streak === 1 ? '' : 's'} (to {pboc.month})</> : null} · holdings table on PHYSICAL</>}
          // the panel is dated by its NEWEST data month (the 5 Nov review: 'as of Wed 01 Jul' from the oldest country while most rows were 2026-09)
          freshness={flows.data ? { ...(flows.data.freshness?.official ?? { state: 'delayed' as const, source: 'IMF IRFCL' }), ...(latestMonth(purchases) ? { as_of: latestMonth(purchases) } : {}) } : null}
          catalog={catalog} series={['IMF_GOLD_OZ_CHN', 'IMF_GOLD_OZ_IND']}
          copyB={<>Who among the central banks bought or sold last month and over the year, each bar with the month the data describes (the IMF publishes one to two months late). How much each holds is the table on PHYSICAL — the same table is not printed twice.</>}
          copyP="IMF IRFCL monetary gold by country: Δ m/m and Δ 12 m converted from million troy ounces to tonnes (1 Moz = 31.1035 t); a row whose stored level exceeds 1,000 Moz is a unit error at the source and is flagged, not drawn; the PBoC streak counts consecutive positive months. Holdings (ph.official, PLAN a.7) and the RBI WSS row live on PHYSICAL (PLAN §f.6: once per page).">
          <Pending s={flows} label="official-sector rows">
            <NetPurchases bars={purchases} />
          </Pending>
        </GoldPanel>

        {/* m.physical */}
        <GoldPanel id="m.physical" title="Physical flows · monthly" badge="context" layer={layer} accent={T.muted}
          catalog={catalog} series={['SGE_WITHDRAWALS_KG', 'INDIA_GOLD_IMPORTS_USD_BN', 'SWISS_GOLD_EXPORT_IN_KG', 'AMFI_GOLD_ETF_NET_CR', 'AMFI_GOLD_ETF_AUM_CR']}
          freshness={flows.data ? (flows.data.freshness?.physical_monthly ?? { state: 'delayed', source: 'SGE · PIB · Swiss customs · AMFI' }) : null}
          copyB={<>Where metal moved last month: <Term t="SGE withdrawals" />, India&apos;s import bill, Swiss exports to India, Indian gold-ETF money.</>}
          copyP="SGE monthly withdrawals (kg); PIB trade release (imports $bn); Swiss customs 7108 to India (kg); AMFI gold-ETF net flow and AUM with the tonnes estimate at the month's landed price. Displayed with attribution (O-1).">
          <Pending s={flows} label="monthly flows">
            {!pm ? <NoVerdict what="monthly flows are fetched when due by the 06:40 job" /> : (
              <KV items={[
                ['SGE withdrawals', pm.sge_withdrawals_kg != null ? `${fmtFixed(pm.sge_withdrawals_kg / 1000, 1)} t` : '—'],
                ['India gold imports', pm.india_imports_usd_bn != null ? `$${fmtFixed(pm.india_imports_usd_bn, 2)} bn` : '—'],
                ['Swiss exports to India', pm.swiss_exports_in_kg != null ? `${fmtFixed(pm.swiss_exports_in_kg / 1000, 1)} t` : '—'],
                ['AMFI gold-ETF net flow', pm.amfi?.net_cr != null ? `₹${fmtFixed(pm.amfi.net_cr, 0)} cr` : '—'],
                ['AMFI gold-ETF AUM', pm.amfi?.aum_cr != null ? `₹${fmtFixed(pm.amfi.aum_cr, 0)} cr${pm.amfi.tonnes_est != null ? ` ≈ ${fmtFixed(pm.amfi.tonnes_est, 1)} t` : ''}` : '—'],
              ]} />
            )}
            <div style={{ fontSize: 9.5, color: T.dim, marginTop: 6 }}>Sources: Shanghai Gold Exchange, PIB, Swiss Federal Customs, AMFI — displayed with attribution on this private terminal; not re-served.</div>
          </Pending>
        </GoldPanel>
      </div>

      {/* m.balance */}
      <GoldPanel id="m.balance" title="Supply and demand · WGC quarterly" badge="context" layer={layer} accent={T.amber}
        freshness={flows.data ? (flows.data.freshness?.balance_sheet ?? { state: 'delayed', source: 'World Gold Council' }) : null}
        catalog={catalog} series={['WGC_SD_JEWELLERY', 'WGC_SD_TECHNOLOGY', 'WGC_SD_BAR_COIN', 'WGC_SD_ETF', 'WGC_SD_CENTRAL_BANKS', 'WGC_SD_OTC_OTHER', 'WGC_SD_MINE', 'WGC_SD_RECYCLED', 'WGC_SD_HEDGING']}
        copyB="Each bar is a quarter of demand by use; the dashed line is that quarter's supply (mine, recycled, hedging). A quarter where the bar rises above the line was balanced by OTC and stock changes."
        copyP="WGC Gold Demand Trends balance sheet, tonnes per quarter since 2010; categories as published (jewellery, technology, bar & coin, ETFs, central banks, OTC & other); revised quarters are new rows (point-in-time). Displayed with attribution (O-1).">
        <Pending s={flows} label="the balance sheet">
          {(flows.data?.balance_sheet ?? []).length === 0 ? <NoVerdict what="the WGC quarterly balance sheet is gated on O-1 and fetched when due" />
            : <BalanceBars rows={flows.data!.balance_sheet!} />}
          <div style={{ fontSize: 9.5, color: T.dim, marginTop: 6 }}>Source: World Gold Council (Goldhub) — displayed with attribution on this private terminal; not re-served or exported.</div>
        </Pending>
      </GoldPanel>

      {/* m.liquidity (collapsed) */}
      <GoldPanel id="m.liquidity" title="Liquidity and inflation context" badge="context" layer={layer} accent={T.border}
        catalog={catalog} series={['FRED_M2SL', 'FRED_HY_OAS', 'GPR_MONTHLY', 'FRED_EXPINF10YR', 'FRED_T5YIFR']}
        freshness={liq.data ? { state: 'delayed', source: 'FRED · GPR' } : null}
        copyB={<>Slow-moving context: how expensive gold is against the money supply, how stressed credit is, how tense the world is, what inflation is expected to be — each as a <Term t="percentile" /> of its own stored history, printed only once 60 observations exist.</>}
        copyP="Gold/M2 percentile over the stored months; HY OAS (ICE BofA) level and percentile; GPR monthly (Caldara–Iacoviello) percentile; Cleveland Fed 10-y expected inflation and the 5y5y forward; nothing here forecasts (G-MACRO)."
        right={<Chip color={T.muted} onClick={() => setLiqOpen(o => !o)}>{liqOpen ? 'COLLAPSE' : 'EXPAND'}</Chip>}>
        {liqOpen ? <Pending s={liq} label="monthly series"><KV items={liqItems} cols={2} /></Pending>
          : <div style={{ fontSize: 10.5, color: T.muted }}>{liqItems.map(([k, v]) => `${k}: ${v}`).join(' · ')}</div>}
      </GoldPanel>
      <div style={{ fontSize: 9.5, color: T.dim }}>Prices: {fmtUsd(daily[daily.length - 1]?.c, 1)} last stored close{usdinr != null && daily.length ? ` ≈ ${fmtInr0(landedInr10g(daily[daily.length - 1].c, usdinr))} landed ₹/10 g at today's USD/INR (no duty)` : ''}.</div>
    </div>
  )
}

export default MonthlyView
