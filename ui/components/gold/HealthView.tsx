'use client'

/**
 * HEALTH — "is gold healthy right now?" (PLAN a.2): one rule-based verdict sentence that describes and does not
 * predict (h.verdict), eight gauges with 60-day sparks (h.gauges), today's open — the pre-open desk — with its
 * accuracy strip and headlines (h.open / h.moved / h.accuracy / h.headlines, all inside GoldPreOpen), the 7-day
 * event-risk strip (h.events) and the automated brief when the day has one (h.brief).
 *
 * No score, no composite, no tightness index (PLAN §f.4). Context gauges render in the neutral token with arrows; the
 * only green/red on this view are the TREND tile's price change and the desk's fair-vs-live comparison (§f.3).
 * Every gauge passes the catalog gate (§f.2): a series without a PUBLISH verdict shows "no verdict — not published".
 */
import { useMemo, type ReactNode } from 'react'
import { Chip, Notice, Spark, Stat, T, fmtFixed } from '@/components/terminal'
import { getGoldBrief, getGoldCalendar } from '@/lib/gold/api'
import { HEALTH_SUFFIX, arrow, basisAgreement, basisClockChip, basisTileWords, briefHeader, dayLabel, eventSessionTag, eventStar, fmtInUnit, fmtSignedCount, fmtSignedPctSp,
         gaugeChangeText, hasCompositeScore, healthLine, istNowKey, orderEvents, pageRealYield, percentileText, publishGate, realYieldSeriesWords, stripSettlement,
         trendValuesLine, trendWords, verdictWindowLabel } from '@/lib/gold/format'
import type { GoldEvent, GoldSubViewProps, HealthGauge } from '@/lib/gold/types'
import { usdEffectWords } from './goldViewModel'
import { GoldPreOpen } from './GoldPreOpen'
import { Term } from './ViewBits'
import { BadgeChip, GoldPanel, LagChipEl, NoVerdict, Pending, useGoldLoad, usePageHealth } from './kit'

const HEALTH_MS = 60_000

/**
 * The DOLLAR gauge's 8 Nov 2026 fields (C-DATA-03 / F4), carried locally until types.ts takes them (that file belongs to
 * another lane this round): the dollar's contribution to gold over gold's own window, its two dates, and whether that
 * span really is the window's.
 */
type DollarGauge = HealthGauge & {
  usd_effect_pct?: number | null; usd_effect_from?: string | null; usd_effect_to?: string | null
  usd_effect_source?: string | null; usd_effect_aligned?: boolean | null; usd_effect_note?: string | null
}

/**
 * The eight tiles in order (a.2 h.gauges); a missing gauge keeps its slot as a placeholder. The [B] line wraps the
 * first use of each glossary word on this view in <Term> (dotted underline → the glossary dock; C-BEGINNER-7).
 * `changeUnit` is the fallback unit of the tile's Δ when the server sends no `change_unit` (C-DATA-7).
 */
const TILES: { key: string; label: string; b: ReactNode; p: string; price?: boolean }[] = [
  { key: 'trend', label: 'Trend', price: true, b: 'Where the price sits against its 20-day and 200-day averages and the 52-week high.', p: 'Price vs 20d/200d simple averages; drawdown from the 52-week high; Yahoo GC=F daily closes.' },
  { key: 'real_yield', label: 'Real yield', b: <>The cost of holding gold: a falling <Term t="real yield" /> supports gold. Δ in <Term t="basis point">bp</Term>.</>, p: '10-y TIPS yield: the fresher of the Treasury real curve (UST_REAL_10Y) and FRED DFII10 — the same quantity, the later date wins, the same value the header strip, the H2 clause and MACRO print; T+1; Δ over the window in bp (1 bp = 0.01 %); contemporaneous beta ≈ −5 %/100 bp since 2022, no lead (G-MACRO H1).' },
  { key: 'dollar', label: 'Dollar', b: <>A rising <Term t="DXY">dollar index</Term> is a headwind for gold in dollars: the line below turns that into how much of gold&apos;s own move it accounts for.</>, p: 'ICE dollar index DX-Y.NYB, Δ over the window; the contribution to gold is −Δln(DXY) over gold’s own two dates — the ONE number the verdict’s H2 clause and MACRO’s KGX split also print (8 Nov 2026: the tile read +0.41 % HEADWIND beside a KGX panel saying the dollar added 0.17 %); weekly beta ≈ −1.0 in every regime (H2); both rise in liquidity crises.' },
  { key: 'positioning', label: 'Positioning', b: <>What the funds (<Term t="managed money" />) hold and did this week; the words below are this week&apos;s read.</>, p: 'CFTC managed-money net futures (Tuesday positions, Friday release); Δ w/w; 3-y percentile once history exists. No forecasting power 2006–2026 (G-STUDY).' },
  { key: 'india_basis', label: 'India basis', b: <>The picked MCX contract vs the <Term t="duty-paid landed" /> price of the same purity, both legs at one clock (live while MCX trades, else the settlement) — the same figure as the header strip: above = local demand exceeds importable supply.</>, p: 'the page\'s picked contract (the overview\'s health block, the same load as the header strip); live MCX ÷ duty-paid landed now − 1 while a quote exists, else settle ÷ that session\'s duty-paid − 1; settle = last-30-min VWAP of the Breeze 1-minute bars (else the ICICI band midpoint), both PROXY; landed at the contract\'s purity (GOLD/GOLDM 995, TEN/PETAL/GUINEA 999), a PETAL or GUINEA price scaled to ₹/10 g first; duty 15 % dated 13 May 2026; IBJA premium beside it (M8/M7).' },
  { key: 'shanghai', label: 'Shanghai premium', b: <>Shanghai paying more than London (<Term t="SGE premium" />) means Chinese demand is pulling metal east; the Δ is in $/oz.</>, p: 'SGE PM (CNY/g × 31.1035 ÷ USDCNY) − LBMA PM / COMEX at 14:15 Beijing (M9); read changes and sign flips in $/oz, not the level (7-hour gap).' },
  { key: 'etf', label: 'ETF holdings', b: <>Western investment demand: <Term t="GLD" /> tonnes and the day&apos;s change.</>, p: 'SPDR GLD tonnes (T+1 ≈ 06:00 IST), Δ d/d; contemporaneous with price, no lead (G-STUDY, G-MACRO). Displayed with attribution (O-1).' },
  { key: 'curve', label: 'Curve / roll', b: <>What the <Term t="roll" /> from the front month into the next costs, and when the front month stops being tradeable (<Term t="FND / LTD" />).</>, p: 'Contango DEC→FEB (F2/F1 − 1), annualised × 365/days; days to COMEX first notice (gold_cme_calendar). A cost, not a signal.' },
]

function findGauge(gauges: HealthGauge[], key: string): HealthGauge | null {
  return gauges.find(g => g.key === key) ?? gauges.find(g => g.key.startsWith(key)) ?? gauges.find(g => key.startsWith(g.key)) ?? null
}

function gaugeValue(g: HealthGauge, unit: GoldSubViewProps['unit'], usdinr: number | null): string {
  if (g.value == null) return '—'
  const u = (g.unit ?? '').toLowerCase()
  if (u === 'usd/oz' || u === '$/oz') return fmtInUnit(g.value, unit, usdinr)
  // a basis / premium is a signed spread: '+0.42 %', the same sign the header strip prints (round 2)
  if ((u === '%' || u === 'pct') && g.key === 'india_basis') return fmtSignedPctSp(g.value, 2)
  if (u === '%' || u === 'pct') return `${fmtFixed(g.value, 2)} %`
  if (u === 'contracts') return fmtSignedCount(g.value)                       // Western grouping for contracts (C-TRADER-20)
  if (u === 't' || u === 'tonnes') return `${fmtFixed(g.value, 1)} t`
  if (u === 'bp') return `${fmtFixed(g.value, 0)} bp`
  if (u === 'inr/10g' || u === '₹/10 g') return `₹${fmtFixed(g.value, 0)}`
  return `${fmtFixed(g.value, Math.abs(g.value) >= 100 ? 1 : 2)}${g.unit ? ` ${g.unit}` : ''}`
}

/** The Δ of a tile in the change's OWN unit (lib/gold/format gaugeChangeText): the Shanghai premium's week change is $/oz, the trend's is % of price. */
function gaugeChange(g: HealthGauge, priceTile: boolean): string {
  return gaugeChangeText(g, priceTile)
}

/** 'Wed 04 Nov 19:00' for a calendar row, 'Wed 04 Nov' when it has no time. */
function eventWhen(e: GoldEvent): string {
  return `${dayLabel(e.event_date ?? e.date)}${e.time_ist ? ` ${e.time_ist}` : ''}`
}

/** H1/H2 thresholds arrive as objects (routers/gold.py HEALTH_RULES); never render an object as a React child */
function thresholdLabel(t: number | string | Record<string, number | string | null>): string {
  if (typeof t === 'number') return fmtFixed(t, 2)
  if (typeof t === 'string') return t
  return Object.entries(t).map(([k, v]) => `${k} ${v ?? '—'}`).join(', ')
}

export function HealthView({ sel, unit, window, layer, usdinr, tooltips, catalog, onNavigate, fair, overview, overviewStatus }: GoldSubViewProps) {
  // ONE basis per clock per page (wave 1e, M-A): the overview's health block — the picked contract, the live MCX quote applied
  // during MCX hours, the same load as the header strip; /api/gold/health (with the pick) only when the overview failed
  const health = usePageHealth({ overview, overviewStatus, window, sel }, HEALTH_MS)
  const events = useGoldLoad(() => getGoldCalendar(7), [], 600_000)
  const brief = useGoldLoad(() => getGoldBrief(), [], 900_000)
  const h = health.data
  const composite = useMemo(() => hasCompositeScore(h), [h])
  const line = healthLine(h?.verdict?.line ?? h?.line)
  const head = line.endsWith(HEALTH_SUFFIX) ? line.slice(0, line.length - HEALTH_SUFFIX.length).replace(/[\s·]+$/u, '') : line
  const gauges = h?.gauges ?? []
  // the window the verdict describes is the SERVER's wording (C-TRADER-16: Monday-to-date once the week has started,
  // '5 sessions' otherwise), from the verdict or the TREND gauge it was measured on; the letter is only the request parameter
  const windowLabel = verdictWindowLabel(h)
  const nowKey = istNowKey()
  const eventRows = useMemo(() => orderEvents(events.data?.events ?? [], nowKey), [events.data, nowKey])
  // the settlement block of this page load (wave 1d): the India-basis tile's settlement chip names its source and session
  const settleBlock = useMemo(() => stripSettlement(overview?.strip, fair), [overview?.strip, fair])
  // strip == gauge == verdict, checked on the rendered payloads: a disagreement is said, never printed as two bases
  const agree = useMemo(() => (health.source === 'overview' ? basisAgreement(overview, h) : { ok: true, reason: null }), [health.source, overview, h])
  const ry = useMemo(() => pageRealYield(overview?.strip, h), [overview?.strip, h])
  // the contract the verdict's India-basis clause is about (the page's pick, from the gauge the clause was built on)
  const verdictContract = (h?.gauges ?? []).find(g => g.key === 'india_basis')?.basis_contract ?? null
  const fallbackContract = health.source === 'health' ? ((h?.gauges ?? []).find(g => g.key === 'india_basis')?.basis_contract ?? 'GOLD (the /health default)') : null

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {/* h.verdict */}
      <GoldPanel id="h.verdict" title="Verdict" badge="context" evidence="G-STUDY 26 Oct 2026: no forecasting power" layer={layer} accent={T.amber}
        catalog={catalog} series={['COMEX_GC_FRONT']}
        subtitle={`window ${window}${windowLabel ? ` · ${windowLabel}` : ''}${verdictContract ? ` · India basis on ${verdictContract}` : ''}`}
        freshness={h ? { state: h.freshness?.state ?? 'delayed', age_days: h.freshness?.age_days, source: 'stored series', as_of: h.as_of,
                         reason: h.freshness?.stale?.length ? `stale: ${h.freshness.stale.join(', ')}` : h.freshness?.unavailable?.length ? `unavailable: ${h.freshness.unavailable.join(', ')}` : null } : null}
        maxAgeDays={null}
        copyB={<>What moved and who was behind it, in one breath: the price, the <Term t="real yield" />, the funds (<Term t="managed money" />), the <Term t="MCX basis" /> vs the <Term t="duty-paid landed" /> price, the <Term t="roll" /> cost and <Term t="GLD" />. Each clause is a threshold on a stored series; nothing here is a forecast.</>}
        copyP="Every clause maps to a rule id and a threshold (listed under LEARN › health rules); stale or unavailable gauges add no clause and the driver word is omitted when a leg is missing; there is no score and no composite (PLAN §f.4)."
        right={<Chip color={T.cyan} onClick={() => onNavigate('learn')} title="The rule table behind every clause">RULES · LEARN ›</Chip>}>
        <Pending s={health} label="the verdict">
          {composite && <Notice color={T.red}>The server sent a composite score with the verdict; it is not rendered (PLAN §f.4).</Notice>}
          <div data-gold-verdict style={{ fontFamily: T.display, fontSize: 15, lineHeight: 1.5, color: T.bright, letterSpacing: .4 }}>
            {head}
            {' '}
            <span style={{ color: T.amber, fontFamily: T.mono, fontSize: 11, letterSpacing: 1, marginLeft: 8, textTransform: 'uppercase' }}>· {HEALTH_SUFFIX}</span>
          </div>
          {layer === 'P' && (h?.verdict?.clauses?.length ?? 0) > 0 && (
            <div style={{ marginTop: 8, display: 'grid', gap: 2, fontFamily: T.mono, fontSize: 10, color: T.muted }}>
              {h!.verdict.clauses.map(c => (
                <div key={c.rule_id} style={{ display: 'grid', gridTemplateColumns: '120px 1fr auto', gap: 8, borderBottom: `1px dashed ${T.border}`, padding: '2px 0' }}>
                  <span style={{ color: T.violet }}>{c.rule_id}</span>
                  <span style={{ color: T.text }}>{c.text}</span>
                  <span style={{ color: T.dim }}>{c.series_id ?? ''}{c.value != null ? ` · ${thresholdLabel(c.value)}` : ''}{c.threshold != null ? ` vs ${thresholdLabel(c.threshold)}` : ''}</span>
                </div>
              ))}
            </div>
          )}
        </Pending>
      </GoldPanel>

      {/* h.gauges */}
      <GoldPanel id="h.gauges" title="Eight gauges" subtitle={`window ${window}${windowLabel ? ` · ${windowLabel}` : ''} · 60-day sparks`} badge="context" layer={layer} accent={T.cyan}
        catalog={catalog} series={['COMEX_GC_FRONT']}
        freshness={h ? { state: h.freshness?.state ?? 'delayed', as_of: h.as_of } : null}
        copyB="One line per tile: what the number is and which way helps gold. Arrows show direction; no tile is coloured as a buy or a sell. A tile whose source is offline keeps its last stored value and says so — it is never blank."
        copyP="Each tile: the direction rule, the publisher's lag and the percentile window (1 y / 3 y once history exists; printed only with ≥ 60 observations). Each Δ carries its own unit (bp for yields, $/oz for the Shanghai premium, % for the price). Curve/roll is arithmetic; the rest is context.">
        <Pending s={health} label="the gauges">
          {gauges.length === 0 && <NoVerdict what="the gauges arrive with the first ingest" />}
          {fallbackContract && <div data-gold-health-fallback style={{ fontSize: 10.5, color: T.amber, marginBottom: 6 }}>
            The header strip did not load: these gauges and the verdict come from /api/gold/health — INDIA BASIS is {fallbackContract}&apos;s, not necessarily {sel.family}&apos;s.</div>}
          {!agree.ok && <div data-gold-basis-mismatch style={{ fontSize: 10.5, color: T.amber, marginBottom: 6 }}>⚠ India basis: {agree.reason} — one basis per clock is the rule; reload the strip (↻).</div>}
          <div style={{ display: 'grid', gap: 8, gridTemplateColumns: 'repeat(auto-fit, minmax(290px, 1fr))' }}>
            {TILES.map(t => {
              const g = findGauge(gauges, t.key)
              if (!g) return <div key={t.key}><NoVerdict what={t.label} /></div>
              const gate = publishGate(catalog, g.series_id)
              if (gate === 'no-verdict') return <div key={t.key} data-gold-gauge={t.key}><NoVerdict what={`${t.label} (${g.series_id})`} /></div>
              const priceChange = !!t.price
              const chg = gaugeChange(g, priceChange)
              const dir = g.direction_for_gold
              const val = gaugeValue(g, unit, usdinr)
              const offline = g.state === 'unavailable' || g.state === 'stale'
              // INDIA BASIS names its CLOCK on its chip (wave 1e, M-A): 'LIVE · MCX 09:20 · COMEX 09:10' (each leg's own clock —
              // the COMEX leg is Yahoo's, minutes behind Breeze) or 'SETTLEMENT · VWAP30 PROXY · Thu 05 Nov' (dated by the session,
              // naming the settlement's source; C-BEGINNER-25, wave 1d). Never a settlement chip on a live number or the reverse.
              const basisClock = t.key === 'india_basis' ? (g.clock ?? (g.state === 'live' ? 'now' : 'settlement')) : null
              const chip = t.key === 'india_basis' ? basisClockChip(g, overview, settleBlock) : null
              const settleSrc = g.settlement_source ?? settleBlock.settlement_source
              const sessionChip = chip
                ? <span data-gold-basis-chip={chip.kind} style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1, color: chip.kind === 'live' ? T.green : T.muted, border: `1px solid ${chip.kind === 'live' ? T.green : T.muted}55`, padding: '1px 6px', whiteSpace: 'nowrap' }}
                    title={chip.kind === 'live'
                      ? `live clock: ${g.basis_label ?? 'live MCX vs duty-paid landed now'}${g.basis_contract ? ` · ${g.basis_contract}` : ''}; MCX = the Breeze quote's own minute, COMEX = the cached Yahoo leg's time (the duty-paid landed is computed from it)`
                      : `${g.settle_basis_label ?? g.settlement_session_label ?? 'the settlement'} · ${settleSrc === 'breeze_vwap30' ? 'last-30-min VWAP of the Breeze 1-minute bars' : settleSrc == null ? 'source not stated' : 'ICICI price-band midpoint'}`}>
                    {chip.text}</span>
                : null
              const trendTile = t.key === 'trend'
              const tWords = trendTile ? trendWords(g) : null
              const tValues = trendTile ? trendValuesLine(g) : ''
              // the clock words ONCE: the server's label, the purity only when the label does not already name it (round 2)
              // the ONE dollar effect, from the gauge the server dated (C-DATA-03 / F4)
              const dollarG = t.key === 'dollar' ? (g as DollarGauge) : null
              const usdWords = dollarG ? usdEffectWords(dollarG) : null
              const basisWords = t.key === 'india_basis' ? basisTileWords(basisClock === 'now' ? (g.basis_label ?? 'live MCX vs duty-paid landed now') : (g.settle_basis_label ?? g.basis_label ?? 'at the settlement'), g.basis_reference) : null
              return (
                <div key={t.key} data-gold-gauge={t.key} data-badge={g.badge} data-gauge-state={g.state} style={{ minWidth: 0 }}>
                  <Stat big={false} label={<span title={tooltips[g.key] ?? tooltips[t.key] ?? g.label}>{t.label}</span>}
                    value={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'baseline', flexWrap: 'wrap', minWidth: 0 }}>
                      <span style={offline ? { color: T.muted } : undefined}>{val}</span>
                      {chg && <span style={{ fontSize: 11, color: priceChange && g.change != null ? (g.change > 0 ? T.green : g.change < 0 ? T.red : T.muted) : T.muted, fontWeight: 500 }}>{arrow(g.change ?? g.change_bp)}{chg}</span>}
                      {offline && <span style={{ fontSize: 9.5, color: T.amber, fontFamily: T.mono, letterSpacing: .8 }} title={g.value != null ? 'the last stored value: the source is stale or offline (PLAN a.1: never blank)' : 'no point stored yet'}>{g.value != null ? 'LAST STORED' : 'NO STORED VALUE'}</span>}
                    </span>}
                    sub={<span style={{ display: 'grid', gap: 3, minWidth: 0 }}>
                      {g.spark && g.spark.length > 1 && <Spark values={g.spark} width={160} height={22} color={T.dim} />}
                      <span style={{ color: T.muted, whiteSpace: 'normal' }}>{layer === 'P' ? (g.rule ?? t.p) : (tooltips[`${g.key}_b`] ?? t.b)}</span>
                      {offline && <span data-gauge-offline style={{ color: T.amber, whiteSpace: 'normal', fontSize: 10 }}>
                        {g.state === 'unavailable' ? 'source offline' : 'stale'}{g.report_date ? ` · last ${dayLabel(g.report_date)}` : ''}{g.note ? ` · ${g.note}` : g.state === 'unavailable' && g.value == null ? ' · no stored point yet (the yahoo_daily job writes the series; FRED DTWEXBGS is a different index and is not shown as DXY)' : ''}
                      </span>}
                      {g.words && <span style={{ color: T.text, fontFamily: T.mono, fontSize: 10 }}>{g.words}</span>}
                      {/* TREND prints its VALUES and the words they earn, never only the rule (wave 1d; the analyst: 'uptrend' while below both) */}
                      {trendTile && (tValues || tWords) && <span data-gold-trend-values style={{ color: T.text, fontFamily: T.mono, fontSize: 10, whiteSpace: 'normal' }}>
                        {tValues}{tWords ? <> · <b>{tWords}</b></> : null}</span>}
                      {/* INDIA BASIS: which contract, clock and purity the one value is at (wave 1d / 1e) */}
                      {t.key === 'india_basis' && <span data-gold-basis-clock={basisClock ?? ''} data-gold-basis-contract={g.basis_contract ?? ''} style={{ color: T.muted, fontSize: 10, whiteSpace: 'normal' }}>
                        {g.basis_contract ? <span style={{ color: T.text }}>{g.basis_contract} · </span> : null}{basisWords}</span>}
                      {/* DOLLAR: the dollar's CONTRIBUTION to gold — the one number H2 and MACRO's KGX split print, with
                          its own two dates, and an amber line when that span is not gold's (C-DATA-03 / F4, 8 Nov 2026) */}
                      {usdWords && <span data-gold-usd-effect={dollarG?.usd_effect_source ?? ''} style={{ color: T.text, fontFamily: T.mono, fontSize: 10, whiteSpace: 'normal' }}>
                        {usdWords.text}{usdWords.note ? <span style={{ color: T.amber }} data-gold-usd-effect-off> · {usdWords.note}</span> : null}</span>}
                      {/* REAL YIELD: the series the value came from (the fresher twin, M-B); an older point than the strip's is said */}
                      {t.key === 'real_yield' && <span data-gold-ry-series={g.series_id ?? ''} style={{ color: T.dim, fontSize: 10, whiteSpace: 'normal' }}>
                        {realYieldSeriesWords(g.series_id)}{g.label_note ? ` · ${g.label_note}` : ''}
                        {ry.from === 'strip' && ry.date && g.report_date && ry.date > g.report_date
                          ? <span data-gold-ry-older style={{ color: T.amber }}> · an older point than the header strip&apos;s ({dayLabel(ry.date)}, {realYieldSeriesWords(ry.seriesId)})</span> : null}</span>}
                      {g.last_bar_partial && <span data-gauge-partial style={{ color: T.dim, fontSize: 10 }}>{g.last_bar_note ?? 'today\u2019s bar is a partial Globex day, not a settlement'}</span>}
                      <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', minWidth: 0 }}>
                        {dir && !trendTile && <span style={{ color: T.text, fontFamily: T.mono, fontSize: 9.5, letterSpacing: .8 }}>{dir.toUpperCase()}{layer === 'P' && g.percentile_1y != null ? ` · ${percentileText(g.percentile_1y, '1 y')}` : ''}{layer === 'P' && g.percentile_3y != null ? ` · ${percentileText(g.percentile_3y, '3 y')}` : ''}</span>}
                        {trendTile && layer === 'P' && <span style={{ color: T.dim, fontFamily: T.mono, fontSize: 9.5 }}>rule: {dir ?? g.rule}{g.percentile_1y != null ? ` · ${percentileText(g.percentile_1y, '1 y')}` : ''}</span>}
                        <BadgeChip badge={g.badge} />
                        {sessionChip ?? <LagChipEl freshness={{ state: g.state, source: g.source, as_of: g.release_at, age_days: g.age_days }} maxAgeDays={catalog[g.series_id ?? '']?.max_age_days} />}
                        {!sessionChip && g.report_date && <span style={{ color: T.dim, fontSize: 9.5 }}>{dayLabel(g.report_date)}</span>}
                        {gate === 'unknown' && g.series_id && <span style={{ color: T.dim, fontSize: 9 }} title="the catalog is not loaded; the verdict gate could not be checked">catalog?</span>}
                      </span>
                    </span>} />
                </div>
              )
            })}
          </div>
        </Pending>
      </GoldPanel>

      {/* h.open · h.moved · h.headlines · h.accuracy: the desk, rendered exactly once on the terminal */}
      <GoldPreOpen sel={sel} layer={layer} tooltips={tooltips} catalog={catalog} fair={fair} />

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', alignItems: 'start' }}>
        {/* h.events */}
        <GoldPanel id="h.events" title="Event risk · next 7 days" subtitle={`IST · High → Medium → roll / holiday → Low, then time · ★ High impact or an FOMC decision · ${eventRows.length} rows`} badge="arithmetic" layer={layer} accent={T.violet} pad={0}
          catalog={catalog} series={['GOLD_EVENTS', 'US_CALENDAR_FF', 'CME_CALENDAR']}
          freshness={events.data ? { state: 'delayed', source: 'gold_events', as_of: events.data.as_of ?? null } : null}
          copyB="When the known shocks hit, the biggest first — the whole week, nothing cut off. After the MCX close = gap risk at 09:00 the next morning. A Fed speaker is Low impact and never starred."
          copyP="Impact from the Forex Factory calendar (High / Medium / Low), roll and holiday rows between Medium and Low; rows already behind the IST clock are dropped. FOMC decision 00:30 IST (winter); US CPI/NFP/PCE 18:00/19:00; COT release Sat 01:00/02:00; MCX expiries; COMEX FND/LTD; in-session = 09:00–23:30/23:55 IST.">
          <Pending s={events} label="the calendar">
            {eventRows.length === 0 && <div style={{ padding: 12, fontSize: 11, color: T.muted }}>No events left in the next 7 days (or the calendar is not ingested yet).</div>}
            <div data-gold-events>
              {eventRows.map((e: GoldEvent) => (
                <div key={`${e.event_date ?? e.date}-${e.time_ist ?? ''}-${e.kind}-${e.name}`} data-event-impact={(e.impact ?? '').toLowerCase() || undefined}
                  style={{ display: 'grid', gridTemplateColumns: '112px 56px 1fr auto', gap: 8, padding: '5px 12px', borderBottom: `1px solid ${T.border}`, fontSize: 11 }}>
                  <span style={{ color: T.muted, fontFamily: T.mono }}>{eventWhen(e)}</span>
                  <span style={{ color: (e.impact ?? '').toLowerCase() === 'high' ? T.text : T.dim, fontFamily: T.mono, fontSize: 9.5, letterSpacing: .6 }}>{(e.impact ?? '').toUpperCase()}</span>
                  <span style={{ color: T.text }}>{eventStar(e) ? '★ ' : ''}{e.name}{e.detail ? <span style={{ color: T.dim }}> · {e.detail}</span> : null}</span>
                  {(() => { const tag = eventSessionTag(e); return <span data-event-session={tag?.text ?? ''} style={{ color: tag?.tone === 'amber' ? T.amber : T.dim, fontFamily: T.mono, fontSize: 9.5 }}>{tag?.text ?? ''}</span> })()}
                </div>
              ))}
            </div>
          </Pending>
        </GoldPanel>

        {/* h.brief */}
        <GoldPanel id="h.brief" title="Automated brief" badge="context" layer={layer} accent={T.muted} catalog={catalog} series={['GOLD_BRIEF']}
          subtitle={brief.data?.available ? `${brief.data.report_date ?? ''}${brief.data.generated_at ? ` · written ${brief.data.generated_at.slice(11, 16)}` : ''}` : 'none for today'}
          freshness={brief.data ? { state: brief.data.available ? 'delayed' : 'unavailable', source: 'gold_brief_docs', reason: brief.data.available ? null : 'no brief stored for the day' } : null}
          copyB="The morning note written by the brief job, labelled with its confidence. Reading material, not a plan: no open signal is shown here."
          copyP="Schema-validated document from gold_brief_docs (sha256-deduped); bias and confidence are the writer's own top-level fields, unscored here; the document's open_signal is never rendered (PLAN 0.1 #7).">
          <Pending s={brief} label="the brief">
            {!brief.data?.available && <div style={{ fontSize: 11, color: T.muted }}>No automated brief stored for today.</div>}
            {brief.data?.available && (() => {
              const b = brief.data
              const d = (b.doc ?? {}) as Record<string, unknown>
              const str = (k: string) => (typeof d[k] === 'string' ? (d[k] as string) : null)
              const summary = b.overnight_summary ?? str('overnight_summary')
              const plan = b.open_plan ?? str('open_plan')
              const risks = (b.key_risks_today ?? (Array.isArray(d.key_risks_today) ? (d.key_risks_today as unknown[]).map(String) : [])) as string[]
              return <div style={{ fontSize: 11.5, lineHeight: 1.6, color: T.text }}>
                <div data-gold-brief-head style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, marginBottom: 4 }}>{briefHeader(b, !!(summary || plan || risks.length))}</div>
                {summary && <p style={{ margin: '0 0 6px' }}>{summary}</p>}
                {plan && <p style={{ margin: '0 0 6px', color: T.muted }}>{plan}</p>}
                {risks.length > 0 && <div style={{ color: T.muted }}>Key risks: {risks.join(' · ')}</div>}
                {!summary && !plan && risks.length === 0 && <div style={{ color: T.dim, fontSize: 10.5 }}>The document carries no summary, plan or risk list for this date; with no body to read, its bias and confidence words are not shown.</div>}
              </div>
            })()}
          </Pending>
        </GoldPanel>
      </div>
    </div>
  )
}

export default HealthView
