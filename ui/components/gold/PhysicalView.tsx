'use client'

/**
 * GOLD › PHYSICAL (reports/gold_program/PLAN.md a.7): premiums, flows, official sector, the OTC window.
 *
 * Panels: ph.ladder (the India price stack, arithmetic) · ph.india (premium history, context) · ph.shanghai (both
 * timestamps) · ph.etf (GLD tonnes + flows, WGC regions, the WGC India tonnes) · ph.official (IMF + RBI) · ph.otc (LBMA
 * turnover, London vaults, CME EFP) · ph.comex.stocks (LINK-ONLY until O-2) · ph.links. WGC / SPDR / IBJA / SGE numbers
 * carry a visible attribution line and are never re-served (O-1). Context metrics use the neutral token.
 *
 * Data: `/api/gold/premiums` (API_CONTRACT §2.9: `freshness` sits inside `india{}` and `shanghai{}`), `/api/gold/flows`
 * (§2.10: `freshness{etf, wgc_weekly, official, rbi, otc}`, India's ETF tonnes as the top-level `wgc_india_holdings_t`).
 * The lag chip is always the server's block or NO DATA; every as-of is a date the server returned. The monthly physical
 * series (SGE withdrawals, imports, Swiss, AMFI) and the WGC balance sheet are MONTHLY's panels (m.physical, m.balance)
 * and are not repeated here (PLAN §f.6); the premium / basis numbers print once, on the ladder.
 *
 * Wave 1c (the critics' round): the ladder prints the STORED fix-minute premium for the IBJA date and labels every bar's
 * clock ("now" / "PM fix" / "settlement") — a premium divided across clocks is never shown (C-TRADER-4, C-BEGINNER-2,
 * C-BEGINNER-5, C-DATA-11); the Shanghai premium prints only for a same-date pair, else the last stored same-day value
 * with "awaiting today's PM" and the real clock gap (C-TRADER-5, C-DATA-10); the official-sector table guards the IMF
 * scale (Moz, t) and excludes a row whose unit is wrong at the source — and the holders table lives here only, MONTHLY
 * keeps the net-purchase bars (C-TRADER-6, C-BEGINNER-3, C-DATA-5, C-TRADER-19); the RBI line drops the price-implied
 * tonnes beside the IMF ounces (C-TRADER-22); the OTC labels carry one unit each (C-TRADER-21, C-DATA-20).
 */
import { useMemo } from 'react'
import { DataTable, Grid, KV, Loading, Stat, T, type Column } from '@/components/terminal'
import { getGoldFlows, getGoldPremiums } from '@/lib/gold/api'
import type { GoldSubViewProps } from '@/lib/gold/types'
import { basisPurityShort, dayLabel, settlementLine, shanghaiReconcile, stripSettlement } from '@/lib/gold/format'
import { tipFor } from '@/lib/gold/learn'
import tooltipsJson from '@/lib/gold/tooltips.json'
import { PriceLadder } from './PriceLadder'
import { BarChart, LineChart, StackedBars, type StackRow } from './FlowCharts'
import { Attribution, Degraded, GPanel, LinkOnlyExplainer, LinkTile, Term, contextTone, useGoldLoad } from './ViewBits'
import { avgLabel, dateLabel, istLabel, latestDate, monthLabel, num, officialTable, pct, serverFreshness, shanghaiPairing, signed, storedPremiumOn, usd, type OfficialRow } from './goldViewModel'

const BUNDLED = (tooltipsJson as { tooltips: Record<string, string> }).tooltips
type FlowsFreshKey = 'etf' | 'wgc_weekly' | 'official' | 'rbi' | 'otc'

/** ph.links — linked sources with no free feed (the pre-open desk's manual-check list, moved and reduced). */
const LINKS = [
  { name: 'Sprott Physical Gold Trust (PHYS)', url: 'https://sprott.com/investment-strategies/physical-bullion-trusts/gold/', what: 'closed-end trust tonnes', why: 'no free feed' },
  { name: 'US Mint bullion sales', url: 'https://www.usmint.gov/about/production-sales-figures/bullion-sales', what: 'coin demand, monthly', why: 'HTML tables, link only' },
  { name: 'Swiss customs (SwissImpex)', url: 'https://www.swissimpex.admin.ch/', what: 'refinery flows to India / China', why: 'the monthly zip is ingested; the dashboard is a link' },
  { name: 'LBMA Good Delivery list', url: 'https://www.lbma.org.uk/good-delivery/gold-current-list', what: 'accredited refiners', why: 'reference' },
  { name: 'WGC Gold Demand Trends', url: 'https://www.gold.org/goldhub/research/gold-demand-trends', what: 'quarterly report', why: 'registration; the balance sheet JSON feeds MONTHLY' },
  { name: 'SAFE (China official reserves)', url: 'https://www.safe.gov.cn/en/OfficialReserveAssets/index.html', what: 'PBoC ~7th of the month', why: 'no table in the HTML; IMF carries it a month later' },
  { name: 'HK Census & Statistics (gold trade with China)', url: 'https://www.censtatd.gov.hk/en/scode230.html', what: 'HK → mainland flows', why: 'table id to capture (O-11)' },
  { name: 'Kitco gold charts', url: 'https://www.kitco.com/charts/gold', what: 'the chart the owner named', why: 'personal viewing only; never embedded or scraped' },
]

export function PhysicalView(props: GoldSubViewProps) {
  const { layer, catalog } = props
  const tip = useMemo(() => (k: string) => tipFor(props.tooltips, BUNDLED, k), [props.tooltips])
  // the page's PICK reaches /premiums (wave 1e minor: the ladder printed GOLD's settle with GOLDTEN picked)
  const prem = useGoldLoad(() => getGoldPremiums(365, { contract: props.sel.family, expiry: props.sel.expiry }), [props.sel.family, props.sel.expiry], 5 * 60_000)
  const flows = useGoldLoad(() => getGoldFlows(24), [], 10 * 60_000)
  const p = prem.data
  const f = flows.data
  const india = p?.india
  const sh = p?.shanghai
  // /flows.etf is ONE row per fund (the latest) carrying its last 30 points in `cumulative_30d` (API_CONTRACT §2.10)
  const gldLast = (f?.etf ?? []).find(r => r.fund === 'GLD')
  const iau = (f?.etf ?? []).find(r => r.fund === 'IAU')
  const gld = [...(gldLast?.cumulative_30d ?? [])].sort((a, b) => a.report_date.localeCompare(b.report_date))
  const gldDelta = gld.map((r, i) => ({ x: r.report_date, y: i > 0 && r.tonnes != null && gld[i - 1].tonnes != null ? r.tonnes - (gld[i - 1].tonnes as number) : null }))
  const cum30 = gld.length > 1 && gld[0].tonnes != null && gld[gld.length - 1].tonnes != null ? (gld[gld.length - 1].tonnes as number) - (gld[0].tonnes as number) : null
  const weekly = f?.wgc_weekly ?? []
  const regions = Array.from(new Set(weekly.map(w => w.region))).filter(r => !/^global$/i.test(r))      // NA · EU · ASIA · OTHER (§2.10)
  const weeks = Array.from(new Set(weekly.map(w => w.week_ending))).sort().slice(-26)
  const regionStack: StackRow[] = weeks.map(wk => ({ x: wk, parts: Object.fromEntries(regions.map(r => [r, weekly.find(w => w.week_ending === wk && w.region === r)?.flow_t ?? null])) }))
  const lastWeek = weeks[weeks.length - 1] ?? null
  const offCols: Column<OfficialRow>[] = [
    { key: 'country', label: 'Country', render: r => <span style={{ color: T.text }}>{r.country}</span> },
    { key: 'month', label: 'Data month', render: r => r.month },
    { key: 'oz_mn', label: 'Moz', align: 'right', title: tip('official_oz'), render: r => num(r.oz_mn, 2), sort: r => r.oz_mn ?? 0 },
    { key: 'tonnes', label: 'Tonnes', align: 'right', title: '1 Moz = 31.1034768 t', render: r => num(r.tonnes, 0), sort: r => r.tonnes ?? 0 },
    { key: 'chg_oz_mn', label: 'Δ Moz m/m', align: 'right', title: tip('official_chg'), render: r => signed(r.chg_oz_mn, 2), sort: r => r.chg_oz_mn ?? 0 },
  ]
  // IMF rows in Moz / t whatever the server's scale (raw ounces are scaled by 1e6, tonnes recomputed); out-of-range rows are excluded with the reason
  const official = useMemo(() => officialTable(f?.official ?? []), [f?.official])
  const pboc = official.rows.find(r => /CHN|China/i.test(r.country))
  const imfMonth = official.rows.length ? official.rows.map(r => r.month).sort().slice(-1)[0] : null        // the newest data month in the table
  // the lag chip is the server's block for that key or NO DATA — never a client-invented state (PLAN 0.1 #10, §f.7)
  const fr = (k: FlowsFreshKey) => (f ? serverFreshness(f.freshness?.[k]) : null)
  const indiaFresh = p ? serverFreshness(india?.freshness) : null
  const shanghaiFresh = p ? serverFreshness(sh?.freshness) : null
  const ibjaTs = india?.ladder?.find(s => /^ibja/i.test(s.step))?.ts ?? india?.premium_date ?? null
  const lastHist = latestDate((india?.history ?? []).map(h => h.report_date))
  // the ladder's premium: the stored fix-minute value for the IBJA date (INDIA_PREMIUM_PCT) — never india.premium_pct,
  // which divides the IBJA fix by a LIVE duty-paid price (the clock error the panel's own note warns about)
  const premiumStored = storedPremiumOn(india?.history, india?.premium_date ?? ibjaTs)
  const mcxStep = india?.ladder?.find(s => /^mcx/i.test(s.step))
  // wave 1d: the MCX settle names its source (last-30-min VWAP of the Breeze bars, else the ICICI band midpoint) and the
  // basis names the purity of the landed price it divides by
  // wave 1e minor: the source and session come from the MCX STEP itself (`settlement_source` / `ts`), for whichever contract the
  // page picked — never 'source not stated' when the step names it; the page's settlement block only when it is the same contract
  const stepContract = /MCX\s+(\S+)/u.exec(mcxStep?.label ?? '')?.[1] ?? props.sel.family
  const settleBlock = props.fair && (props.fair.contract ?? 'GOLD') === stepContract ? stripSettlement(props.overview?.contract?.mcx === stepContract ? props.overview?.strip : null, props.fair) : null
  const settleSrc = mcxStep?.settlement_source ?? india?.settlement_source ?? settleBlock?.settlement_source ?? null
  const stepSession = /^\d{4}-/.test(mcxStep?.ts ?? '') ? mcxStep?.ts ?? null : null
  const basisClock = `${stepSession ? `at the ${dayLabel(stepSession)} settlement vs that session's duty-paid (the close reference)` : mcxStep?.ts ? `at the ${mcxStep.ts} vs that session's duty-paid (the close reference)` : 'at the last settlement vs that session\'s duty-paid'}` +
    ` · settle ${settlementLine({ ...(settleBlock ?? {}), settlement: mcxStep?.value ?? settleBlock?.settlement ?? null, settlement_source: settleSrc,
      settlement_quality: mcxStep?.settlement_quality ?? settleBlock?.settlement_quality ?? null, settlement_session: stepSession ?? settleBlock?.settlement_session ?? null,
      settlement_session_label: mcxStep?.ts_label ?? (stepSession ? null : settleBlock?.settlement_session_label ?? null) })} · ${basisPurityShort(mcxStep?.basis_reference ?? india?.basis_reference)}`
  // M-C: the printed legs must reproduce the printed premium (server `reconciles`, re-checked here to the cent)
  const shRec = shanghaiReconcile(sh)
  // Shanghai: the premium prints only for a same-date pair; otherwise the last stored same-day value and what it waits for
  const pairing = sh ? shanghaiPairing(sh.ts_sge, sh.ts_ref, sh.london_pm_usd == null && sh.comex_at_1415_bj != null) : null
  // the last same-date pair: the server's own (premium_usd of pair_date — recomputed from the printed legs, wave 1e M-C), else
  // the history's last stored point; the legs printed beside it are that pair's, so the premium equals them to the cent
  const shStored = sh?.pair_date && sh.premium_usd != null
    ? { report_date: sh.pair_date, premium_usd: sh.premium_usd, premium_pct: sh.premium_pct ?? null }
    : ([...(sh?.history ?? [])].reverse().find(h => h.premium_usd != null) ?? null)

  return (
    <div data-gold-b4b="physical" style={{ display: 'grid', gap: 10 }}>
      {/* ph.ladder */}
      <GPanel id="ph.ladder" title="The India price stack" badge="arithmetic" evidence="identity: landed → duty-paid → IBJA → MCX" fresh={indiaFresh} dateOnly={ibjaTs ? istLabel(ibjaTs, true) : null}
        series={['GOLD_INR_LANDED', 'GOLD_INR_DUTY_PAID', 'IBJA_999_PM', 'USDINR_FBIL']} catalog={catalog} layer={layer}
        formula="landed ₹/10 g = COMEX $/oz × USD/INR × 10 ÷ 31.1034768 (fine gold); duty-paid = landed × (1 + 0.15); premium = IBJA 999 PM ÷ (duty-paid × 999/1000) − 1; basis = MCX ÷ (duty-paid × P/1000) − 1, P = the contract's purity (GOLD / GOLDM 995, TEN / PETAL / GUINEA 999)"
        copyB={<>what a rupee gold price is made of and where demand shows up: above the <Term t="duty-paid landed" /> price = local demand exceeds importable supply; below = discount. The <Term t="basis" /> is the MCX futures over that landed price.</>}
        copyP={<>synchronise the timestamps or the premium is clock error (G-INDIA §5.3: NY close vs the IBJA afternoon board gave +0.9 %; Reuters saw ≈ +$3). Inputs are sampled at the IBJA PM minute with the <Term t="FBIL reference rate" />. Landed is per FINE gold: a price of purity P compares with landed × P/1000 (PM decision D1) — never a 999 ÷ 995 ratio.</>}>
        <Degraded error={prem.error} what="premiums" />
        {!p && !prem.error && <Loading label="Building the rupee price from COMEX, the rupee, the duty, IBJA and MCX" />}
        {india && (
          <>
            <PriceLadder steps={india.ladder} duty={india.duty} premium={premiumStored}
              premiumPending={india.premium_date ? `the stored fix-minute premium for ${istLabel(india.premium_date)} is not in yet (the 18:10 job writes INDIA_PREMIUM_PCT)` : 'no IBJA PM fix stored yet'}
              basisPct={india.basis_pct} basisClock={basisClock} carryAdjPct={india.carry_adj_pct} tips={tip} />
            <Attribution sources={['IBJA']} />
          </>
        )}
      </GPanel>

      <Grid min={340}>
        {/* ph.india — the history line and the WGC reference; the premium / basis of the day print once, on the ladder (§f.6) */}
        <GPanel id="ph.india" title="India premium history" badge="context" evidence="GS-PREMIUM pending" fresh={indiaFresh} dateOnly={lastHist ? istLabel(lastHist) : null}
          series={['INDIA_PREMIUM_PCT', 'MCX_BASIS_PCT', 'WGC_PREMIUM_IN']} catalog={catalog} layer={layer}
          copyB="above landed = local demand exceeds importable supply; below = discount (post-duty-hike inventory, smuggling, weak demand)."
          copyP="IBJA 999 PM ÷ duty-paid landed − 1 at the IBJA fix minute (M7); MCX basis = front settle ÷ duty-paid − 1 (M8); a read across the duty step is a duty change, not demand.">
          {india?.history?.length ? (
            <LineChart series={[
              { key: 'prem', label: 'IBJA premium vs duty-paid landed %', color: T.violet, values: india.history.map(h => ({ x: h.report_date, y: h.premium_pct ?? null })) },
              { key: 'basis', label: 'MCX basis %', color: T.cyan, values: india.history.map(h => ({ x: h.report_date, y: h.basis_pct ?? null })) },
            ]} height={140} dp={1} refs={[{ y: 0, label: 'parity' }]} label="India premium" />
          ) : <div style={{ color: T.dim, fontSize: 11 }} title={tip('since')}>history starts the day the 18:10 job starts (the panel prints that date once rows exist)</div>}
          <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }} title={tip('duty_effective')}>duty step: 6 → 15 % on {india ? dateLabel(india.duty.effective) : '13 May 2026'} (a premium read across the step is a duty change, not demand)</div>
          <KV items={[
            [<span key="k" title={tip('premium_usd')}>WGC weekly India premium (reference)</span>, p?.reference?.wgc_india != null ? `${usd(p.reference.wgc_india, 1)}/oz · wk ${istLabel(p.reference.wgc_india_week ?? null)}` : '—', contextTone],
          ]} />
          {p?.reference?.reuters_url && <div style={{ fontSize: 10, marginTop: 4 }}><a href={p.reference.reuters_url} target="_blank" rel="noreferrer" style={{ color: T.cyan }}>Reuters weekly survey (sanity line, paywalled) ↗</a></div>}
          <Attribution sources={['IBJA', 'WGC']} />
        </GPanel>

        {/* ph.shanghai */}
        <GPanel id="ph.shanghai" title="Shanghai premium" badge="context" evidence="GS-P3 pending" fresh={shanghaiFresh} dateOnly={sh?.ts_sge ? istLabel(sh.ts_sge, true) : null}
          series={['SHANGHAI_PREMIUM_USD', 'SGE_SHAU_PM']} catalog={catalog} layer={layer}
          formula="SGE PM (CNY/g) × 31.1034768 ÷ USDCNY − LBMA PM (or COMEX at 14:15 Beijing)"
          copyB="positive = China pulling metal (import quotas permitting); read the sign flips and the changes, not the level."
          copyP="SGE PM 14:15 Beijing (06:15 UTC) vs LBMA PM 15:00 London: 8 h 45 min apart with the UK on GMT, 7 h 45 min in British summer time; COMEX at 14:15 Beijing is the like-for-like leg. The premium is printed only when both legs carry the same date. Yahoo CNY misses days: PBOC / FRED DEXCHUS fallback (R9).">
          {sh && sh.sge_pm_cny_g != null && pairing ? (
            <>
              <Grid min={120}>
                {pairing.sameDate
                  ? <Stat label={<span title={tip('sge_premium_usd')}>premium $/oz</span>} value={<span data-shanghai-premium="same-date">{signed(sh.premium_usd, 1)}</span>} color={contextTone} big={false} sub={<span title={tip('sge_premium_pct')}>{pct(sh.premium_pct, 2)} · both legs {istLabel(pairing.sgeDate)}</span>} />
                  : <Stat label={<span title={tip('sge_premium_usd')}>premium $/oz (last same-day pair)</span>} value={<span data-shanghai-premium="stored">{shStored ? signed(shStored.premium_usd, 2) : '—'}</span>} color={contextTone} big={false}
                      sub={<span title={tip('sge_premium_pct')}>{shStored ? `${pct(shStored.premium_pct, 2)} · ${istLabel(shStored.report_date)} (${sh.premium_source === 'legs' ? 'from the printed legs' : 'stored'})` : 'no stored same-day pair yet'} · awaiting the {sh.london_pm_usd != null ? 'LBMA PM' : 'reference'} of {istLabel(pairing.sgeDate)}</span>} />}
                {/* the CNY/g is dated by ITS OWN date (sge_pm_date — the pair date's leg), never by the newest SGE timestamp (the 5 Nov review:
                    a Tuesday price labelled Thursday); a newer SGE print stands alone, without a '=' to a $/oz of another date */}
                <Stat label="SGE Au99.99 PM" value={<span data-sge-date={sh.sge_pm_date ?? sh.pair_date ?? pairing.sgeDate ?? ''}>{num(sh.sge_pm_cny_g, 2)} CNY/g</span>} color={contextTone} big={false}
                  sub={<span>= {usd(sh.sge_usd_oz, 1)} at USDCNY {num(sh.usdcny, 4)} ({sh.usdcny_source ?? 'source —'}{sh.usdcny_date ? ` · ${istLabel(sh.usdcny_date)}` : ''}{sh.usdcny_as_of ? ` · stored ${istLabel(sh.usdcny_as_of, true)}` : ''}) · {istLabel(sh.sge_pm_date ?? sh.pair_date ?? pairing.sgeDate)}
                    {sh.sge_latest_cny_g != null && sh.sge_latest_date && sh.sge_latest_date !== (sh.sge_pm_date ?? sh.pair_date) && <span data-sge-latest style={{ display: 'block', color: T.dim }}>newer SGE print {num(sh.sge_latest_cny_g, 2)} CNY/g · {istLabel(sh.sge_latest_date)} (its $/oz waits for that date&apos;s London PM)</span>}</span>} />
                <Stat label="reference leg" value={usd(sh.london_pm_usd ?? sh.comex_at_1415_bj, 1)} color={contextTone} big={false} sub={`${sh.london_pm_usd != null ? 'LBMA PM (WGC-served, PROVISIONAL until O-1)' : 'COMEX at 14:15 Beijing'} · ${istLabel(pairing.refDate)}`} />
              </Grid>
              {/* M-C: the premium printed must equal SGE $/oz − the reference leg printed beside it (to $0.10) */}
              {shRec.ok === false && <div data-shanghai-reconcile="mismatch" style={{ fontSize: 10.5, color: T.amber, marginTop: 6 }}>
                ⚠ the printed legs do not reproduce this premium: SGE $/oz − reference = {signed(shRec.legs, 2)} $/oz — the premium was derived with another USDCNY vintage; read the sign from the legs until it is re-derived</div>}
              {sh.recompute_note && <div data-shanghai-recompute style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{sh.recompute_note}</div>}
              <div data-two-timestamps data-shanghai-pairing={pairing.sameDate ? 'same-date' : 'cross-date'} style={{ fontSize: 10, color: pairing.sameDate ? T.muted : T.amber, marginTop: 6 }}>
                <span title={tip('ts_sge')}>SGE {istLabel(sh.ts_sge, true)}</span> · <span title={tip('ts_ref')}>reference {istLabel(sh.ts_ref, true)}</span> — {pairing.gap}
                {!pairing.sameDate && <span>; the two legs are on different dates, so no premium is divided across them (a cross-date pair after a big day is an artefact, not Shanghai)</span>}
              </div>
              {sh.history?.length ? <div style={{ marginTop: 6 }}><LineChart series={[{ key: 'sp', label: 'Shanghai premium $/oz', color: T.violet, values: sh.history.map(h => ({ x: h.report_date, y: h.premium_usd ?? null })) }]} height={120} dp={0} refs={[{ y: 0, label: '' }]} label="Shanghai premium" /></div> : null}
              {p?.reference?.wgc_china != null && <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>WGC weekly China premium (reference): {usd(p.reference.wgc_china, 1)}/oz · wk {istLabel(p.reference.wgc_china_week ?? null)}</div>}
              <Attribution sources={['SGE', 'WGC']} />
            </>
          ) : <div style={{ color: T.dim, fontSize: 11 }}>Shanghai block not yet available{prem.error ? '' : ' (the SGE PM benchmark arrives with the 16:10 IST job)'}{sh?.clock_note && !/7-hour/.test(sh.clock_note) ? ` — ${sh.clock_note}` : ''}</div>}
        </GPanel>
      </Grid>

      {/* ph.etf */}
      <GPanel id="ph.etf" title="ETF holdings and flows" badge="context" evidence="G-STUDY / G-MACRO / GS-P1: moves with the price, does not lead it (26 Oct 2026)" fresh={fr('etf')} dateOnly={gldLast ? istLabel(gldLast.report_date) : null}
        series={['GLD_TONNES', 'IAU_TONNES', 'WGC_ETF_FLOW_T_GLOBAL', 'WGC_ETF_HOLD_T_IN']} catalog={catalog} layer={layer}
        copyB="Western investment demand; a divergence (price up, tonnes down) means the buying is outside the ETFs — central banks, Asia."
        copyP="GLD daily tonnes from the SPDR archive (E1, ≈06:00 IST T+1); WGC weekly flows (E5) for the week ended Friday; 4-week Δ tonnes FAIL as a forecast, same-week R² 16 % (G-STUDY).">
        <Degraded error={flows.error} what="flows" />
        {!f && !flows.error && <Loading label="ETF holdings" />}
        {f && (
          <div style={{ display: 'grid', gap: 10 }}>
            <Grid min={160}>
              <Stat label={<span title={tip('etf_tonnes')}>GLD tonnes</span>} value={num(gldLast?.tonnes, 2)} color={contextTone} big={false} sub={<span title={tip('etf_chg_1d')}>Δ day {signed(gldLast?.chg_1d, 2)} t · 5 d {signed(gldLast?.chg_5d, 1)} t</span>} />
              <Stat label={<span title={tip('etf_chg_1m')}>GLD change over the last {gld.length} stored points</span>} value={cum30 != null ? `${signed(cum30, 1)} t` : '—'} color={contextTone} big={false} sub={`1 m ${signed(gldLast?.chg_1m, 1)} t · YTD ${signed(gldLast?.chg_ytd, 1)} t`} />
              <Stat label={<span title={tip('etf_tonnes')}>IAU tonnes</span>} value={num(iau?.tonnes, 1)} color={contextTone} big={false} sub={iau ? istLabel(iau.report_date) : '—'} />
              {/* India's ETF tonnes are the top-level `wgc_india_holdings_t` (WGC country table, weekly); regions carry no India row (§2.10) */}
              <Stat label={<span title={tip('etf_flow_t')}>WGC India ETF tonnes</span>} value={<span data-wgc-india>{num(f.wgc_india_holdings_t, 1)}</span>} color={contextTone} big={false} sub={lastWeek ? `WGC country table · wk ${istLabel(lastWeek)}` : 'WGC country table (weekly, Mon)'} />
            </Grid>
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
              <div><div style={{ fontSize: 10, color: T.muted }}>GLD tonnes (last {gld.length} stored points)</div>
                {gld.length ? <LineChart series={[{ key: 'gld', label: 'GLD t', color: T.violet, values: gld.map(r => ({ x: r.report_date, y: r.tonnes })) }]} height={120} dp={0} legend={false} label="GLD tonnes" /> : <div style={{ color: T.dim, fontSize: 11 }}>no GLD rows</div>}</div>
              <div><div style={{ fontSize: 10, color: T.muted }} title={tip('etf_chg_1d')}>GLD daily Δ tonnes</div>
                {gld.length > 1 ? <BarChart values={gldDelta.slice(1)} height={120} dp={1} label="GLD daily change" /> : null}</div>
              <div><div style={{ fontSize: 10, color: T.muted }} title={tip('wgc_region_flow')}>WGC weekly flows by region, tonnes (26 weeks)</div>
                {regionStack.length ? <StackedBars rows={regionStack} keys={regions.map(r => ({ key: r, label: r }))} height={130} dp={1} label="WGC flows by region" /> : <div style={{ color: T.dim, fontSize: 11 }}>WGC weekly rows pending (Mon ≈ 11:30 job, gated on O-1)</div>}</div>
            </div>
            <Attribution sources={['SPDR', 'WGC']} />
          </div>
        )}
      </GPanel>

      <Grid min={340}>
        {/* ph.official — as of the newest IMF data month in the table; the RBI week prints on its own row */}
        <GPanel id="ph.official" title="Official sector" badge="context" evidence="GS-P5 pending (not yet pre-registered)" fresh={fr('official')} dateOnly={imfMonth ? `data month ${monthLabel(imfMonth)}` : null} series={['IMF_GOLD_OZ_IND', 'RBI_GOLD_RESERVES_USD_MN']} catalog={catalog} pad={0} layer={layer}
          copyB="who is buying at the official level and in which data month; explains the regime, never the week."
          copyP="IMF ounces (E12) for quantity; RBI's weekly value changes are almost all price (its valuation convention sits below spot, F11).">
          {/* the holders table renders here only (PLAN a.7); MONTHLY's m.official keeps the net-purchase bars (PLAN a.5, §f.6) */}
          <DataTable columns={offCols} rows={official.rows} rowKey={r => `${r.country}-${r.month}`} dense initialSort={{ key: 'oz_mn', dir: 'desc' }}
            empty={<div style={{ padding: 10, color: T.dim, fontSize: 11 }}>IMF rows pending (monthly ~25th, 1–2 month lag)</div>} />
          <div style={{ padding: '8px 12px' }}>
            {official.excluded.length > 0 && (
              <div data-official-excluded style={{ fontSize: 10, color: T.amber, marginBottom: 6, lineHeight: 1.5 }}>
                excluded: {official.excluded.map(r => `${r.country} (${r.month}) — ${r.excluded}`).join('; ')}
              </div>
            )}
            {official.rows.some(r => r.scaled) && <div data-official-scaled style={{ fontSize: 9.5, color: T.dim, marginBottom: 6 }}>IMF values arrived in troy ounces and are shown in Moz (÷ 1e6) and tonnes (× 31.1034768) here</div>}
            <KV items={[
              [<span key="k" title={tip('pboc_streak')}>PBoC latest</span>, pboc ? `${num(pboc.oz_mn, 2)} Moz = ${num(pboc.tonnes, 0)} t (${monthLabel(pboc.month)}) · Δ ${signed(pboc.chg_oz_mn, 2)} Moz m/m` : '—', contextTone],
              [<span key="k" title={tip('rbi_gold_usd')}>RBI gold (WSS)</span>, f?.rbi?.usd_mn != null ? `$${num(f.rbi.usd_mn, 0)} mn · wk ${istLabel(f.rbi.week ?? null)}` : '—', contextTone],
              [<span key="k" title={tip('rbi_gold_share')}>RBI gold share of reserves</span>, f?.rbi?.share_pct != null ? `${pct(f.rbi.share_pct, 1)} · tonnes: the IMF IND row above (RBI publishes value, not weight)` : '—', contextTone],
            ]} />
            <Attribution sources={['IMF', 'RBI']} />
          </div>
        </GPanel>

        {/* ph.otc */}
        <GPanel id="ph.otc" title="OTC window" badge="context" evidence="activity, not positions" fresh={fr('otc')} dateOnly={f?.otc?.week_ending ? istLabel(f.otc.week_ending) : null} series={['LBMA_OTC_TURNOVER_USD_BN', 'LBMA_VAULT_GOLD_T', 'CME_EFRP']} catalog={catalog} layer={layer}
          copyB={<>there is no COT for London. The <Term t="loco London">OTC</Term> market is where most gold trades; this is how much traded and how much sits in the vaults, never who holds it.</>}
          copyP={<>gross turnover, not netted between reporting entities (E14); vault file ~3–4 weeks after month-end (E15); <Term t="EFP price vs volume">EFP volume</Term> from the CME EFRP file (C2) — the EFP price is not free.</>}>
          <KV items={[
            // one unit, the catalog's own name for the series (USD bn, the weekly headline; never "bn/day" — C-TRADER-21, C-DATA-20)
            [<span key="k" title={tip('lbma_turnover_usd_bn')} data-otc-turnover-label>{catalog?.LBMA_OTC_TURNOVER_USD_BN?.name ?? 'LBMA OTC turnover, gold (12-wk MA)'}</span>, f?.otc?.lbma_turnover_usd_bn != null ? `$${num(f.otc.lbma_turnover_usd_bn, 1)} bn · week ending ${istLabel(f.otc.week_ending ?? null)}` : '—', contextTone],
            [<span key="k" title={tip('vault_tonnes')}>London vaults</span>, f?.otc?.vault_t != null ? `${num(f.otc.vault_t, 0)} t · ${f.otc.vault_month ? monthLabel(f.otc.vault_month) : ''}` : '—', contextTone],
            [<span key="k" title={tip('efp_rt')}>CME EFP</span>, f?.otc?.efp?.today_rt != null ? `${num(f.otc.efp.today_rt, 0)} round turns · ${istLabel(f.otc.efp.date ?? null)} · ${avgLabel(f.otc.efp.today_rt, f.otc.efp.avg_20d)}` : '—', contextTone],
            [<span key="k" title={tip('efp_pct_volume')}>EFP share of volume</span>, pct(f?.otc?.efp?.pct_of_volume, 1), contextTone],
          ]} />
          <Attribution sources={['LBMA', 'CME']} />
        </GPanel>
      </Grid>

      <Grid min={340}>
        {/* ph.comex.stocks — LINK-ONLY: the catalog row (COMEX_WAREHOUSE, O-2) supplies the about popover and the reason */}
        <GPanel id="ph.comex.stocks" title="COMEX warehouse stocks and deliveries" series={[]} about="COMEX_WAREHOUSE" catalog={catalog} subtitle="LINK-ONLY until O-2" layer={layer}>
          <LinkOnlyExplainer>www.cmegroup.com blocks scripts and its Data Terms forbid automated downloads; the owner decides whether a once-daily browser download is acceptable personal use (O-2). Until then: registered / eligible / pledged and the coverage ratio are read on the CME page.</LinkOnlyExplainer>
          <div style={{ display: 'grid', gap: 6 }}>
            <LinkTile name="Gold warehouse stocks (XLS)" url="https://www.cmegroup.com/delivery_reports/Gold_Stocks.xls" what="registered · eligible · pledged, daily" why={tip('registered_oz')} />
            <LinkTile name="Metals issues and stops (PDF)" url="https://www.cmegroup.com/delivery_reports/MetalsIssuesAndStopsReport.pdf" what="delivery notices MTD" why={tip('coverage_ratio')} />
          </div>
        </GPanel>

        {/* ph.links */}
        <GPanel id="ph.links" title="Linked sources (no free feed)" series={[]} catalog={catalog} layer={layer}>
          <LinkOnlyExplainer />
          <div style={{ display: 'grid', gap: 6 }}>
            {LINKS.map(l => <LinkTile key={l.url} {...l} />)}
          </div>
        </GPanel>
      </Grid>
      <div style={{ fontSize: 10, color: T.dim }}>Monthly physical series (SGE withdrawals, India imports, Swiss exports, AMFI) and the WGC balance sheet live on MONTHLY (m.physical, m.balance); the official-sector holders table lives here and MONTHLY keeps the net-purchase bars — nothing is repeated.</div>
    </div>
  )
}

export default PhysicalView
