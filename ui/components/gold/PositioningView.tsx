'use client'

/**
 * GOLD › POSITIONING (reports/gold_program/PLAN.md a.6): who is long, who is short — weekly CFTC COT + daily exchange OI.
 *
 * Panels: p.hero · p.whois · p.history · p.crowd · p.decomp · p.daily.comex · p.daily.mcx · p.mcx.history · p.mcx.category
 * (dormant, O-8) · p.asia · p.drawer. Every number is `context` (G-STUDY 26 Oct 2026: FAIL as a forecast at every horizon;
 * PASS as a description, same-week Spearman +0.65) except the MCX OI ladder and the per-contract opened / closed table
 * (`arithmetic`). No colour on any of it; no COT index presented as a signal; the crowd gauge is worded "crowdedness, not a
 * signal". Nothing here feeds a trade (PLAN 0.1 #7).
 *
 * Data: `/api/gold/cot` (B3, API_CONTRACT §2.5), `/api/gold/positioning/daily?exchange=COMEX|MCX&family=` (§2.6),
 * `/api/gold/positioning/mcx-history?family=&expiry=&window=` (§2.6b, the page's pick and D / W / M window).
 * Each block loads on its own and keeps its last good value on error.
 *
 * Honesty rules carried here (wave 1b): the lag chip is the block's own `freshness` from the server or NO DATA — never a
 * client-invented state; every as-of is the report date the server returned, never the request clock; the history range
 * never asks for more than the route allows (`COT_WEEKS_MAX`); the MCX ladder shows the selected family's rows or says
 * why it cannot; catalog ids are the seed's (services/data-service/gold/catalog_seed.py) so the §f.2 gate and the about
 * popover are real.
 *
 * Wave 1c (the critics' round): the release is printed as the server's `release_ist` LABEL, never a converted
 * `release_at` (a naive-UTC instant read as IST put it 5 h 30 early — C-DATA-6); every percentile names the window the
 * server computed it over ("of the last 160 reports", never "all-history" for a 3-y window — C-DATA-14) and never an
 * ordinal; the roll distances are calendar days, as the server counts them (C-TRADER-28); p.asia requests no series id
 * the catalog does not carry and prints no "no verdict" rows (C-BEGINNER-16, C-DATA-17) — it waits for an `/api/gold/asia`
 * read of `gold_asia_daily`; contract counts use Western grouping (C-TRADER-20).
 */
import { useMemo, useState } from 'react'
import { Chip, DataTable, Grid, KV, Loading, Stat, T, type Column } from '@/components/terminal'
import { getGoldCot, getGoldMcxHistory, getGoldPositioningDaily } from '@/lib/gold/api'
import type { CotDecompRow, DailyPositioningRow, GoldMcxHistory, GoldPositioningDaily, GoldSubViewProps, Layer, McxHistoryContract, McxHistoryPeriod, Window } from '@/lib/gold/types'
import { tipFor } from '@/lib/gold/learn'
import tooltipsJson from '@/lib/gold/tooltips.json'
import { CotWhoIsLong } from './CotWhoIsLong'
import { OiQuadrantTape, QuadrantTag } from './OiQuadrantTape'
import { Gauge, LineChart, StackedBars, type StackRow } from './FlowCharts'
import { Attribution, Degraded, Field, GPanel, LinkOnlyExplainer, LinkTile, Term, contextTone, useGoldLoad } from './ViewBits'
import {
  ALL_HISTORY_MIN_REPORTS, COT_RANGES, CROWD_LABEL, MINUS, type CotRange, concentrationLines, contractsToMoz, contractsToTonnes, contractsToUsdBn, cotRangeLabel,
  fundDriverLabel, inr, istLabel, num, pct, percentileLabel, serverFreshness, signed, signedPct, whoDidWords, oiQuadrantWords, tenderWords } from './goldViewModel'

const BUNDLED = (tooltipsJson as { tooltips: Record<string, string> }).tooltips
const GROUP_KEYS = [{ key: 'mm', label: 'managed money' }, { key: 'or', label: 'other reportables' }, { key: 'nr', label: 'non-reportable' }, { key: 'sd', label: 'swap dealers' }, { key: 'pm', label: 'producer / merchant' }]
const CFTC_SHORT = 'https://www.cftc.gov/dea/futures/deacmxsf.htm'
const EVIDENCE = 'G-STUDY 26 Oct 2026: explains, does not forecast'
/** The catalog row every COT panel hangs off (seed: PUBLISH-CORE · context); the about popover describes the CFTC report. */
const COT_ID = 'COT_DISAGG_F'
/** why ΔOI can be missing on the newest COMEX session (the tape never says 'flat' for it — C-BEGINNER-24) */
const CME_OI_LAG = 'no OI yet: the CME daily file lands T+1 ≈ 15:30 IST'
const MCX_OI_LAG = 'no OI for this session: the 07:35 master had no row for it'
type Tip = (k: string) => string | undefined

/**
 * Optional server fields read without widening types.ts: `crowd.percentile_label` / `crowd.window_label` /
 * `crowd.percentile_window` and `open_interest.pct_rank_label` (B3, wave 1c — the all-history percentile is data-service's
 * expanding figure and may be null; the window percentile is labelled with its own window, C-DATA-14).
 */
const serverStr = (o: unknown, key: string): string | null => {
  const v = o && typeof o === 'object' ? (o as Record<string, unknown>)[key] : null
  return typeof v === 'string' && v ? v : null
}
const serverNum = (o: unknown, key: string): number | null => {
  const v = o && typeof o === 'object' ? (o as Record<string, unknown>)[key] : null
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}
/** the percentile the server could compute and the window it names: all-history when data-service sent it, else the fetched window */
function crowdPercentile(crowd: unknown, nReports: number | null): { value: number | null; label: string | null } {
  const all = serverNum(crowd, 'percentile_all')
  if (all != null) return { value: all, label: serverStr(crowd, 'percentile_label') ?? (nReports != null && nReports < ALL_HISTORY_MIN_REPORTS ? null : 'all-history percentile') }
  const win = serverNum(crowd, 'percentile_window')
  return { value: win, label: serverStr(crowd, 'window_label') ?? serverStr(crowd, 'percentile_label') }
}
/** the release build hides a panel whose feed ui-api does not serve yet (PLAN §f.2: placeholder in dev, hidden in release) */
const RELEASE_BUILD = process.env.NODE_ENV === 'production'
/** GC volume ÷ its 20-d average needs a few sessions stored, or the ratio is 1.00× by construction (C-DATA-19) */
const VOL_AVG_MIN_SESSIONS = 5

/** Today's IST date (YYYY-MM-DD): the tender words compare the tender start with it. */
function todayIst(): string {
  return new Date(Date.now() + 5.5 * 3_600_000).toISOString().slice(0, 10)
}

export function PositioningView(props: GoldSubViewProps) {
  const { layer, catalog } = props
  const tip = useMemo<Tip>(() => (k: string) => tipFor(props.tooltips, BUNDLED, k), [props.tooltips])
  const [range, setRange] = useState<CotRange>('1y')
  const fam = (props.sel.family || 'GOLD').toUpperCase()
  const cot = useGoldLoad(() => getGoldCot({ weeks: COT_RANGES[range] }), [range], 5 * 60_000)
  const comex = useGoldLoad(() => getGoldPositioningDaily('COMEX', 60), [], 10 * 60_000)
  // `?exchange=MCX&family=` (API_CONTRACT §2.6): the server filters and labels rows by the family it was asked for; the
  // selection travels with every request and the load re-runs when it changes
  const mcx = useGoldLoad(() => getGoldPositioningDaily('MCX', 60, fam), [fam], 10 * 60_000)
  // p.mcx.history follows the page's PICK (family + expiry, the auto-resolved front when none is picked) and its D / W / M window
  const mcxHist = useGoldLoad(() => getGoldMcxHistory({ family: fam, expiry: props.sel.expiry, window: props.window }), [fam, props.sel.expiry, props.window], 10 * 60_000)
  const onPick = props.onSel ? (expiry: string) => props.onSel?.({ expiry }) : undefined

  const c = cot.data
  const mm = c?.groups.find(g => g.key === 'mm')
  const price = c?.history?.[c.history.length - 1]?.price ?? null
  const driver = c?.driver_label ?? fundDriverLabel(mm?.chg_long, mm?.chg_short, c?.week_price_chg_pct)
  const words = mm ? (mm.who_did?.length ? mm.who_did : whoDidWords(mm.chg_long, mm.chg_short)) : []
  const hist = c?.history ?? []
  const stack: StackRow[] = hist.map(r => ({ x: r.report_date, parts: { mm: r.mm_net, or: r.or_net, nr: r.nr_net, sd: r.sd_net, pm: r.pm_net } }))
  // the chip is the server's `freshness` block or NO DATA (PLAN 0.1 #10, §f.7): the client never invents a state
  const cotFresh = c ? serverFreshness(c.freshness) : null
  const cotDate = c?.latest?.report_date ? istLabel(c.latest.report_date) : null          // the report date, never a clock
  const conc = concentrationLines(c?.drawer?.concentration)
  const nReports = c?.crowd?.n_reports ?? null
  const crowdPct = crowdPercentile(c?.crowd, nReports)
  const oiPctLabel = serverStr(c?.open_interest, 'pct_rank_label')

  const decompCols: Column<CotDecompRow>[] = [
    { key: 'span', label: 'Span', title: tip('decomp_span'), render: r => <span style={{ color: T.text }}>{r.span}</span> },
    { key: 'px', label: 'Price $/oz', align: 'right', render: r => `${num(r.price_from, 0)} → ${num(r.price_to, 0)}` },
    { key: 'd_mm_long', label: 'Δ fund long', align: 'right', title: tip('delta_long'), render: r => signed(r.d_mm_long) },
    { key: 'd_mm_short', label: 'Δ fund short', align: 'right', title: tip('delta_short'), render: r => signed(r.d_mm_short) },
    { key: 'd_mm_net', label: 'Δ fund net', align: 'right', title: tip('mm_net'), render: r => signed(r.d_mm_net) },
    { key: 'd_comm_net', label: 'Δ commercial net', align: 'right', title: tip('sd_net'), render: r => `${signed(r.d_comm_net)} (sd ${signed(r.d_sd_net)} · pm ${signed(r.d_pm_net)})` },
    { key: 'd_or_net', label: 'Δ other rept.', align: 'right', title: tip('or_net'), render: r => signed(r.d_or_net) },
    { key: 'd_nr_net', label: 'Δ small specs', align: 'right', title: tip('nr_net'), render: r => signed(r.d_nr_net) },
    { key: 'd_oi', label: 'ΔOI', align: 'right', title: tip('oi_change'), render: r => signed(r.d_oi) },
    { key: 'd_gld_t', label: 'ΔGLD t', align: 'right', title: tip('d_gld_t'), render: r => signed(r.d_gld_t, 1) },
  ]

  return (
    <div data-gold-b4b="positioning" style={{ display: 'grid', gap: 10 }}>
      <div style={{ fontSize: 11.5, color: T.muted, lineHeight: 1.6 }}>
        <i>Who</i> is answered weekly by the CFTC's <Term t="COT" /> with a 3-day lag (Tuesday positions, Friday release); <i>what got opened or closed</i> is answered
        daily by exchange <Term t="open interest" />, which never says who. {layer === 'P' && <span>Categories are self-declared (Form 40); a reclassification looks like a flow; reporting level 200 contracts.</span>}
      </div>

      {/* p.hero */}
      <GPanel id="p.hero" title="Managed money this week" badge="context" evidence={EVIDENCE} fresh={cotFresh} dateOnly={cotDate}
        series={[COT_ID]} catalog={catalog} layer={layer} formula="net = long − short (spreads excluded); Moz = × 100 ÷ 1e6; t = × 100 × 31.1034768 ÷ 1e6"
        copyB="the funds' bet and what they did this week: net = longs minus shorts; a negative Δlong means they closed longs, a negative Δshort means they covered shorts. The fund-driver label is the bigger of the two moves; when price fell and the net still rose, funds bought the dip."
        copyP="right ≈ 3 weeks in 4 as narration and the next-week correlation is ≈ 0 (G-STUDY). The 2024-11 → 2026-03 doubling happened while funds cut net length: the marginal buyer is outside this report."
        right={c?.latest?.stale ? <Chip color={T.amber} title={tip('stale')}>STALE · catch-up pending</Chip> : null}>
        <Degraded error={cot.error} what="COT" />
        {!c && !cot.error && <Loading label="Reading the latest Commitments of Traders" />}
        {c && !c.latest && <div style={{ color: T.dim, fontSize: 11 }}>{c.error_info?.message ?? 'no COT report stored yet (the Saturday 02:30 job seeds 2006→)'}</div>}
        {c && mm && (
          <>
            <Grid min={190}>
              <Stat label={<span title={tip('mm_net')}><Term t="managed money">Managed-money</Term> <Term t="net position">net</Term></span>} value={signed(mm.net)} color={contextTone} big={false}
                sub={<span><span title={tip('net_moz')}>{num(mm.net_moz ?? contractsToMoz(mm.net), 2)} Moz</span> · <span title={tip('net_t')}>{num(mm.net_t ?? contractsToTonnes(mm.net), 0)} t</span> · <span title={tip('net_usd_bn')}>${num(mm.net_usd_bn ?? contractsToUsdBn(mm.net, price), 1)} bn</span></span>} />
              <Stat label={<span title={tip('cot_mm_chg')}>Change on the week</span>} value={signed(mm.chg_net)} color={contextTone} big={false}
                sub={<span title={tip('who_did')} data-who-did>{words.length ? words.join(' / ') : 'unchanged'}</span>} />
              <Stat label={<span title={tip('driver_label')}>Fund-driver label</span>} value={<span data-driver-label style={{ fontSize: 14 }}>{driver ?? '—'}</span>} color={contextTone} big={false}
                sub={<span><span title={tip('week_price_chg')}>week price {signedPct(c.week_price_chg_pct)}</span> · <span title={tip('quadrant_label')} data-oi-quadrant>{oiQuadrantWords(c.quadrant_label, c.open_interest.chg)}</span></span>} />
              <Stat label={<span title={tip('oi_all')}>Open interest</span>} value={num(c.open_interest.total)} color={contextTone} big={false}
                sub={<span title={tip('oi_change')} data-oi-pctile>Δ {signed(c.open_interest.chg)}{c.open_interest.pct_rank != null ? ` · ${percentileLabel(c.open_interest.pct_rank, nReports, oiPctLabel)}` : ''}</span>} />
            </Grid>
            <div style={{ fontSize: 10.5, color: T.muted, marginTop: 8 }}>
              {/* release_ist / next_release_ist are LABELS the server prints (API_CONTRACT §2.5) — never a converted release_at (C-DATA-6) */}
              <span title={tip('cot_as_of')}>as of {istLabel(c.latest?.report_date ?? null)}</span> · <span title={tip('cot_release')} data-cot-release>released {c.latest?.release_ist ?? '—'}</span> · <span title={tip('next_release_ist')}>next {c.latest?.next_release_ist ?? '—'}</span>
            </div>
            <Attribution sources={['CFTC']} />
          </>
        )}
      </GPanel>

      {/* p.whois */}
      <GPanel id="p.whois" title="Who is long · who is short" badge="context" evidence={EVIDENCE} fresh={cotFresh} dateOnly={cotDate} series={[COT_ID]} catalog={catalog} layer={layer}
        copyB={<>every long has a short; <Term t="swap dealer">swap dealers</Term> are the banks' hedge of the OTC and ETF book, <Term t="producer / merchant">producers</Term> hedge mine output and inventory.</>}
        copyP={<>categories are self-declared and a reclassification looks like a flow; the legacy identity commercial long = producer long + swap long + swap spread holds on every row (B1 check). <Term t="other reportables" /> (+95k net) is an opaque bucket: no inference about who they are.</>}>
        {c?.groups?.length ? <CotWhoIsLong groups={c.groups} oi={c.open_interest.total} tips={tip} /> : !cot.error && !c ? <Loading label="Trader groups" /> : <div style={{ color: T.dim, fontSize: 11 }}>no groups stored</div>}
      </GPanel>

      {/* p.history */}
      <GPanel id="p.history" title="History" badge="context" evidence={EVIDENCE} fresh={cotFresh} dateOnly={cotDate} series={[COT_ID, 'COMEX_GC_FRONT']} catalog={catalog} layer={layer}
        subtitle={<span data-cot-range>{cotRangeLabel(hist.length, hist[0]?.report_date)} · three stacked panels, one y-axis each — never dual-axis</span>}
        copyB="where the funds' bet sits against the price over time; the bands mark the 20th and 80th positions of the last year."
        copyP="the index is 100 × (net − min) ÷ (max − min) over 52 reports (M17): FAIL as a timing rule in 2006–2026 — crowded weeks did better at 4 weeks, not worse (G-STUDY). Hover a bar for the week's decomposition."
        right={<span style={{ display: 'flex', gap: 3 }}>{(Object.keys(COT_RANGES) as CotRange[]).map(r => <Chip key={r} color={T.muted} active={range === r} onClick={() => setRange(r)} title={r === 'all' ? `everything stored (the route serves at most ${COT_RANGES.all} reports)` : `${COT_RANGES[r]} reports`}>{r}</Chip>)}</span>}>
        {hist.length === 0 ? <div style={{ color: T.dim, fontSize: 11 }}>no history returned{cot.error ? '' : ' yet (the COT backfill seeds 2006→)'}</div> : (
          <div style={{ display: 'grid', gap: 8 }}>
            <div><div style={{ fontSize: 10, color: T.muted }}>GC front, $/oz (Tuesday close)</div>
              <LineChart series={[{ key: 'px', label: 'GC', color: T.amber, values: hist.map(r => ({ x: r.report_date, y: r.price ?? null })) }]} height={120} dp={0} legend={false} label="gold price" /></div>
            <div><div style={{ fontSize: 10, color: T.muted }} title={tip('net_by_group')}>net position by group, contracts</div>
              <StackedBars rows={stack} keys={GROUP_KEYS} height={170} dp={0} label="net by group" fmtY={v => `${v < 0 ? MINUS : ''}${Math.round(Math.abs(v) / 1000)}k`} /></div>
            <div><div style={{ fontSize: 10, color: T.muted }} title={tip('cot_index_52w')}>managed-money COT index (52 w) with 20 / 80 bands — crowdedness, not a signal</div>
              <LineChart series={[{ key: 'idx', label: 'COT index 52w', color: T.violet, values: hist.map(r => ({ x: r.report_date, y: r.cot_index_52 ?? null })) }]} height={110} dp={0} bands={[[0, 20], [80, 100]]} legend={false} label="COT index" /></div>
          </div>
        )}
      </GPanel>

      <Grid min={320}>
        {/* p.crowd */}
        <GPanel id="p.crowd" title="Crowdedness" badge="context" evidence="G-STUDY: no forecasting power" fresh={cotFresh} dateOnly={cotDate} series={[COT_ID]} catalog={catalog} layer={layer}
          copyB="how far the funds' net sits from its own recent range. A high reading says the crowd is already in; it does not say when it leaves."
          copyP="COT index ≥ 90 vs ≤ 10: +1.08 % vs +0.63 % at 4 weeks (t +0.4 / −0.5) — crowded weeks did better, the lore is not supported (G-STUDY); z = (net − mean) ÷ sd over 52 / 156 reports.">
          {c?.crowd ? (
            <>
              <Gauge value={c.crowd.cot_index_52} label="52-week COT index" />
              <KV items={[
                [<span key="k" title={tip('cot_index_52w')}>COT index 52 w</span>, num(c.crowd.cot_index_52, 0), contextTone],
                [<span key="k" title={tip('cot_index_156w')}>COT index 156 w</span>, num(c.crowd.cot_index_156, 0), contextTone],
                [<span key="k" title={tip('cot_z52')}>z52 / z156</span>, `${signed(c.crowd.z52, 1)} / ${signed(c.crowd.z156, 1)}`, contextTone],
                [<span key="k" title={tip('net_pct_oi')}>net % OI</span>, pct(mm?.net_pct_oi, 1), contextTone],
                [<span key="k" title={tip('cot_pctile_all')}>net percentile</span>, <span key="v" data-crowd-pctile>{percentileLabel(crowdPct.value, nReports, crowdPct.label)}</span>, contextTone],
              ]} />
              <div data-crowd-label style={{ fontSize: 10.5, color: T.muted, marginTop: 6 }}>{c.crowd.label || CROWD_LABEL}</div>
            </>
          ) : <div style={{ color: T.dim, fontSize: 11 }}>{CROWD_LABEL}</div>}
        </GPanel>

        {/* p.asia — SHFE front OI Δ and the SGE Au(T+D) direction live in gold_asia_daily (D1 / D3, the 16:10 job), which
            ui-api does not serve yet (no /api/gold/asia; data-service has /db/gold/asia). The dev build shows the shell
            named by the catalog rows; the RELEASE build hides the panel (PLAN §f.2) — it requests no series id the catalog
            lacks and prints no "no verdict" placeholder (C-BEGINNER-16, C-DATA-17) */}
        {!RELEASE_BUILD && <GPanel id="p.asia" title="Shanghai positioning" badge="context" fresh={null} dateOnly={null}
          series={['SGE_DAILY', 'SHFE_DAILY']} catalog={catalog} layer={layer}
          subtitle="SHFE au front OI Δ · SGE Au(T+D) OI and settlement direction"
          copyB="Short to Long = shorts pay the deferred fee = more demand to take metal than to deliver it."
          copyP="D1 kx files (SHFE) and the D3 date-range table (SGE); no study yet (GS-P3 after history).">
          <div data-asia-pending style={{ display: 'grid', gap: 6 }}>
            <Field label={catalog?.SHFE_DAILY?.name ?? 'SHFE gold futures daily (au, front month)'} tip={tip('shfe_oi')} value={<span style={{ color: T.dim }}>front OI and Δ — stored daily, not yet served to this panel</span>} />
            <Field label={catalog?.SGE_DAILY?.name ?? 'SGE daily market data (Au99.99, Au(T+D))'} tip={tip('sge_td_direction')} value={<span style={{ color: T.dim }}>Au(T+D) OI and settlement direction — stored daily, not yet served to this panel</span>} />
            <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.5 }}>the 16:10 IST job writes both into `gold_asia_daily`; the numbers appear here once ui-api serves them (`/api/gold/asia`, B3) — nothing is estimated in the meantime. The SGE PM benchmark itself prints on PHYSICAL (ph.shanghai), not twice.</div>
          </div>
          <Attribution sources={['SGE']} />
        </GPanel>}
      </Grid>

      {/* p.decomp */}
      <GPanel id="p.decomp" title="Rally / decline decomposition" badge="context" evidence={EVIDENCE} fresh={cotFresh} dateOnly={cotDate} series={[COT_ID, 'GLD_TONNES']} catalog={catalog} pad={0} layer={layer}
        copyB="who was adding and who was leaving during the rally and the decline, in contracts and tonnes."
        copyP="2024-11 → 2026-03 ($2,606 → $5,242): managed money −66,900 net, COMEX OI −122,000, commercials covered 62,600 shorts, GLD +202 t; the −21 % since the high: funds flat (+5,800), commercials −32,600, other reportables +30,900 (G-STUDY).">
        <DataTable columns={decompCols} rows={c?.decomposition ?? []} rowKey={r => r.span} dense empty={<div style={{ padding: 12, color: T.dim, fontSize: 11 }}>decomposition rows appear once the history endpoint returns spans (since the last 2-year low; since the high)</div>} />
      </GPanel>

      {/* p.daily.comex */}
      <DailyComex data={comex.data} error={comex.error} tip={tip} layer={layer} catalog={catalog} />

      {/* p.daily.mcx */}
      <DailyMcx data={mcx.data} error={mcx.error} tip={tip} layer={layer} catalog={catalog} family={fam} />

      {/* p.mcx.history */}
      <McxHistory data={mcxHist.data} error={mcxHist.error} tip={tip} layer={layer} catalog={catalog} family={fam} expiry={props.sel.expiry} window={props.window} onPick={onPick} />

      <Grid min={320}>
        {/* p.mcx.category — dormant: the catalog row (LINK-ONLY, O-8) supplies the about popover; no number gate */}
        <GPanel id="p.mcx.category" title="Who holds MCX gold (monthly)" badge="context" series={[]} about="MCX_CATEGORY_OI" catalog={catalog} subtitle="dormant until a collector exists (O-8)" layer={layer}>
          <LinkOnlyExplainer>The MCX category-wise OI workbook (FPI / DFI / prop / hedgers / others, long vs short) sits behind a bot wall; the schema `gold_mcx_category_oi` is fixed, the panel fills when the owner approves a browser-session collector.</LinkOnlyExplainer>
          <LinkTile name="MCX participant-wise open interest" url="https://www.mcxindia.com/market-data/participant-wise-open-interest" what="monthly workbook" why="mcxindia.com is never fetched by the stack" />
          <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }} title={tip('mcx_category_oi')}>open question j.2 #1: daily or month-end rows?</div>
        </GPanel>

        {/* p.drawer */}
        <GPanel id="p.drawer" title="Details" badge="context" fresh={cotFresh} dateOnly={cotDate} series={[COT_ID]} catalog={catalog} layer={layer}>
          <details>
            <summary style={{ cursor: 'pointer', fontSize: 11, color: T.cyan }}>trader counts, concentration, micro gold, options overlay, the raw CFTC block</summary>
            {c && (
              <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
                {c.groups.filter(g => ['mm', 'sd', 'pm', 'or'].includes(g.key)).map(g => (
                  <Field key={g.key} label={`${g.label} · traders L / S`} tip={`${tip('traders_long') ?? ''} ${tip('traders_short') ?? ''}`.trim()}
                    value={`${num(g.traders_long)} / ${num(g.traders_short)} · avg long ${g.traders_long && g.long ? num(g.long / g.traders_long, 0) : '—'} · avg short ${g.traders_short && g.short ? num(g.short / g.traders_short, 0) : '—'}`} />
                ))}
                {/* drawer.concentration{gross4_long … net8_short} as the server names it (API_CONTRACT §2.5) */}
                <Field label="concentration (top 4 / 8, net % of OI)" tip={tip('conc_gross_le_4')} value={<span data-conc-net>{conc.net}</span>} />
                <Field label="concentration (top 4 / 8, gross % of OI)" tip={tip('conc_gross_le_4')} value={<span data-conc-gross>{conc.gross}</span>} />
                <Field label="micro gold (MGC) funds net" tip={tip('micro_gold')} value={fmtMicro(c.drawer?.micro_gold)} />
                <Field label="options overlay" tip={tip('options_overlay')} value={<span data-options-overlay>{c.options_overlay?.line ?? `options add ${signed(c.options_overlay?.mm_net_options_only)} to funds' net; combined OI ${num(c.options_overlay?.combined_oi)}`}</span>} />
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                  <a href={String(c.drawer?.raw_block_url ?? CFTC_SHORT)} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}><Chip color={T.cyan} style={{ cursor: 'pointer' }}>↗ RAW CFTC BLOCK (deacmxsf.htm)</Chip></a>
                  {typeof c.drawer?.api_query === 'string' && <code style={{ fontFamily: T.mono, fontSize: 9.5, color: T.dim, wordBreak: 'break-all' }}>{c.drawer.api_query}</code>}
                </div>
                <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.5 }}>{c.footer ?? 'weekly, Tuesday positions, released Friday 15:30 ET; no daily, no OTC, categories only; our test found no timing value'}</div>
              </div>
            )}
          </details>
        </GPanel>
      </Grid>
    </div>
  )
}

function fmtMicro(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') return signed(v)
  if (typeof v === 'object') { const o = v as Record<string, unknown>; return `${signed(o.mm_net as number)} (OI ${num(o.open_interest as number)})` }
  return String(v)
}

interface DailyProps { data: GoldPositioningDaily | null; error: string | null; tip: Tip; layer: Layer; catalog: GoldSubViewProps['catalog'] }

/** p.daily.comex — COMEX OI by product (T+1), ΔOI with price, the 20-day quadrant tape, volume vs 20-d, churn, P/C OI. */
function DailyComex({ data, error, tip, layer, catalog }: DailyProps) {
  const rows = data?.rows ?? []
  const products = Array.from(new Set(rows.map(r => r.symbol_or_product))).filter(p => !/^OG/.test(p)).slice(0, 5)
  const dates = Array.from(new Set(rows.map(r => r.trade_date))).sort()
  const stack: StackRow[] = dates.map(d => ({ x: d, parts: Object.fromEntries(products.map(p => [p, rows.find(r => r.trade_date === d && r.symbol_or_product === p)?.open_interest ?? null])) }))
  const gc = rows.filter(r => r.symbol_or_product === 'GC').sort((a, b) => a.trade_date.localeCompare(b.trade_date))
  const last = gc[gc.length - 1]
  const vol20 = gc.slice(-20).map(r => r.volume).filter((v): v is number => v != null)
  // the average needs VOL_AVG_MIN_SESSIONS sessions: with one row stored the ratio is 1.00× by construction (C-DATA-19)
  const avg20 = vol20.length >= VOL_AVG_MIN_SESSIONS ? vol20.reduce((a, b) => a + b, 0) / vol20.length : null
  const calls = rows.filter(r => /^OG.*C/i.test(r.symbol_or_product)).slice(-1)[0]
  const puts = rows.filter(r => /^OG.*P/i.test(r.symbol_or_product)).slice(-1)[0]
  const lastDate = last?.trade_date ?? dates[dates.length - 1] ?? null
  const pcRatio = data?.put_call_oi_ratio ?? (calls?.open_interest && puts?.open_interest ? puts.open_interest / calls.open_interest : null)
  return (
    <GPanel id="p.daily.comex" title="COMEX open interest by product (daily, T+1)" badge="context" evidence="folklore until G-STUDY-2" fresh={data ? serverFreshness(data.freshness) : null} dateOnly={lastDate ? istLabel(lastDate) : null}
      series={['CME_VOI']} catalog={catalog} subtitle={data?.since ? `since ${istLabel(data.since)}` : 'GC · MGC · 1OZ · QO · OG, all months summed'} layer={layer}
      copyB={<>"which positions got closed yesterday": OI down = positions closed; the tape names the <Term t="OI quadrants">quadrant</Term> each day.</>}
      copyP="T+1 from the CME FTP daily_volume file; mechanical on expiry / exercise days (greyed); the weekly version scored 1 of 12 cells in G-STUDY — the daily version is untested until G-STUDY-2.">
      <Degraded error={error} what="COMEX daily OI" />
      {!data && !error && <Loading label="CME daily volume and open interest" />}
      {data && (
        <div style={{ display: 'grid', gap: 10 }}>
          <Grid min={170}>
            <Stat label={<span title={tip('oi_by_product')}>GC open interest</span>} value={num(last?.open_interest)} color={contextTone} big={false}
              sub={<span title={tip('oi_change')}>Δ {signed(last?.oi_change)} · {lastDate ? istLabel(lastDate) : '—'}</span>} />
            <Stat label={<span title={tip('volume_vs_20d')}>GC volume vs 20-d avg</span>} value={<span data-vol-ratio={avg20 ? 'ok' : 'pending'}>{last?.volume != null && avg20 ? `${num(last.volume / avg20, 2)}×` : '—'}</span>} color={contextTone} big={false}
              sub={avg20 ? `volume ${num(last?.volume)} · avg over ${vol20.length} sessions` : `volume ${num(last?.volume)} · average from ${VOL_AVG_MIN_SESSIONS} sessions (${vol20.length} stored)`} />
            <Stat label={<span title={tip('churn')}>volume / OI churn</span>} value={last?.volume != null && last.open_interest ? num(last.volume / last.open_interest, 2) : '—'} color={contextTone} big={false} />
            <Stat label={<span title={tip('pc_oi')}>options P/C OI</span>} value={num(pcRatio, 2)} color={contextTone} big={false}
              sub={calls && puts ? `puts ${num(puts.open_interest)} · calls ${num(calls.open_interest)}` : 'OG rows pending'} />
          </Grid>
          {stack.length > 0 && <StackedBars rows={stack} keys={products.map(p => ({ key: p, label: p }))} height={150} dp={0} label="OI by product" fmtY={v => `${Math.round(v / 1000)}k`} />}
          <OiQuadrantTape tape={data.quadrant_tape ?? []} tips={tip} missingOiNote={CME_OI_LAG} />
          {data.roll && <div style={{ fontSize: 10.5, color: T.muted }}><span title={tip('roll_ratio')}>roll: front {data.roll.front ?? '—'} · next {data.roll.next ?? '—'} · ratio {num(data.roll.ratio, 2)}</span> · <span title={tip('fnd')} data-days-to-fnd>{data.roll.days_to_tender_or_fnd != null ? `${num(data.roll.days_to_tender_or_fnd, 0)} days to FND${data.roll.fnd_date ? ` (${istLabel(data.roll.fnd_date)})` : ''}` : 'FND not in the stored calendar yet (Sunday 04:00 CME calendar job)'}</span> (product OI until bulletin settlements are allowed, C7)</div>}
          <Attribution sources={['CME']} />
        </div>
      )}
    </GPanel>
  )
}

/**
 * p.daily.mcx — MCX OI per contract and expiry (lots) for the SELECTED family, ΔOI, roll ratio, days to tender, 60-day
 * stacked bars; "since …". The rows are the family's own (`symbol_or_product` = the family code the server was asked
 * for, §2.6); when the server answered for another family the panel says so instead of showing its rows.
 */
function DailyMcx({ data, error, tip, layer, catalog, family }: DailyProps & { family: string }) {
  const fam = (family || 'GOLD').toUpperCase()
  const served = data?.family ? String(data.family).toUpperCase() : null
  const mismatch = !!served && served !== fam
  const rows = mismatch ? [] : (data?.rows ?? []).filter(r => r.symbol_or_product.toUpperCase() === fam)
  const dates = Array.from(new Set(rows.map(r => r.trade_date))).sort()
  const expiries = Array.from(new Set(rows.map(r => r.expiry ?? ''))).filter(Boolean).sort().slice(0, 6)
  const stack: StackRow[] = dates.map(d => ({ x: d, parts: Object.fromEntries(expiries.map(e => [e, rows.find(r => r.trade_date === d && r.expiry === e)?.open_interest ?? null])) }))
  const lastDate = dates[dates.length - 1] ?? null
  const ladder = rows.filter(r => r.trade_date === lastDate).sort((a, b) => (a.expiry ?? '').localeCompare(b.expiry ?? ''))
  const cols: Column<DailyPositioningRow>[] = [
    { key: 'expiry', label: 'Expiry', render: r => <span style={{ color: T.text }}>{r.expiry ? istLabel(r.expiry) : '—'}</span> },
    { key: 'open_interest', label: 'OI (lots)', align: 'right', title: tip('mcx_oi_by_expiry'), render: r => num(r.open_interest) },
    { key: 'oi_change', label: 'ΔOI (this expiry)', align: 'right', title: tip('oi_change'), render: r => signed(r.oi_change) },
    { key: 'settle', label: 'Settle ₹/10 g', align: 'right', title: tip('settlement_from_band'), render: r => <span>{inr(r.settle_or_close)} {r.quality === 'proxy' && <Chip color={T.amber} style={{ fontSize: 8 }}>PROXY</Chip>}</span> },
  ]
  return (
    <GPanel id="p.daily.mcx" title={`MCX ${fam} open interest by expiry (07:35)`} badge="arithmetic" evidence="ICICI master: lots per contract" fresh={data && !mismatch ? serverFreshness(data.freshness) : null} dateOnly={lastDate ? istLabel(lastDate) : null}
      series={['MCX_CURVE_ICICI']} catalog={catalog} subtitle={data?.since && !mismatch ? `since ${istLabel(data.since)}` : 'history starts the day the job started'} layer={layer}
      copyB="where MCX liquidity sits and when it moves: the front month's OI falls into the tender period while the next month's rises."
      copyP="proxy settlement (band midpoint) until official bhavcopy rows exist (O-8); no volume until the Breeze daily path is verified (F3).">
      <Degraded error={error} what="MCX daily OI" />
      {!data && !error && <Loading label="MCX open interest" />}
      {data && mismatch && (
        <div data-mcx-family-mismatch style={{ fontSize: 11, color: T.amber }}>
          the server answered for {served}, not {fam} (the request's family parameter did not reach it — API_CONTRACT §2.6) — no rows shown rather than another family's under this title
        </div>
      )}
      {data && !mismatch && (
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'minmax(0, 1.4fr) minmax(260px, 1fr)' }}>
          <div>
            {stack.length > 0 ? <StackedBars rows={stack} keys={expiries.map(e => ({ key: e, label: istLabel(e) }))} height={160} dp={0} label="MCX OI by expiry" /> : <div data-mcx-no-rows style={{ color: T.dim, fontSize: 11 }}>no rows for {fam} yet{data.since ? ` — since ${istLabel(data.since)}` : ' (the 07:35 master job writes one row per expiry per session)'}</div>}
            {data.roll && <div style={{ fontSize: 10.5, color: T.muted, marginTop: 6 }}><span title={tip('roll_ratio')}>roll ratio front ÷ next {num(data.roll.ratio, 2)}</span> · <span title={tip('days_to_tender')} data-days-to-tender>{tenderWords(data.roll.days_to_tender_or_fnd, data.roll.tender_start ? istLabel(data.roll.tender_start) : null, data.roll, todayIst())}</span>{data.roll.tender_start && !data.roll.in_tender && (data.roll.days_to_tender_or_fnd ?? 0) > 0 ? <span title={tip('tender_start')}> · tender from {istLabel(data.roll.tender_start)} (computed; the MCX circular is the legal source)</span> : null}</div>}
            {data.quadrant_tape?.length ? <div style={{ marginTop: 8 }}><OiQuadrantTape tape={data.quadrant_tape} tips={tip} missingOiNote={MCX_OI_LAG} oiScope={`all ${fam} expiries`} /></div> : null}
          </div>
          <DataTable columns={cols} rows={ladder} rowKey={r => `${r.symbol_or_product}-${r.expiry}`} dense empty={<div style={{ padding: 8, color: T.dim, fontSize: 11 }}>ladder empty</div>} />
        </div>
      )}
    </GPanel>
  )
}

/** The catalog row p.mcx.history is gated on (catalog_seed.py: PUBLISH-CONTEXT · arithmetic, owner decision O-8). */
const MCX_HISTORY_ID = 'BREEZE_DAILY'
const PERIOD_HEAD: Record<Window, string> = { D: 'Session', W: 'ISO week', M: 'Month' }
const WINDOW_WORDS: Record<Window, string> = { D: 'by session', W: 'by ISO week, each to its last session', M: 'by calendar month' }
/** [B] one-liners for the positions column: OI says that positions opened or closed, never which side. */
const POSITIONS_READ: Record<string, string> = {
  opened: 'OI rose: new positions, a new long AND a new short',
  closed: 'OI fell: positions closed, a long and a short left together',
  unchanged: 'OI unchanged: positions changed hands, none opened or closed on net',
}

interface McxHistoryProps {
  data: GoldMcxHistory | null; error: string | null; tip: Tip; layer: Layer; catalog: GoldSubViewProps['catalog']
  family: string; expiry: string | null; window: Window; onPick?: (expiry: string) => void
}

/**
 * p.mcx.history — which positions in the PICKED MCX contract (the page's family + expiry) were opened or closed per session,
 * ISO week or month (the page's D / W / M window), from ICICI Breeze daily OI × close; each period's quadrant word is the
 * server's (the daily tape's rule, drawn with the tape's own cell — `QuadrantTag`); the family's OI split across its live
 * expiries shows where the open positions sit (click = pick that contract for the page). Exchange OI never says who: every
 * lot has a long and a short. Badge `arithmetic`, a description: no green / red anywhere, the newest period first.
 */
function McxHistory({ data, error, tip, layer, catalog, family, expiry, window, onPick }: McxHistoryProps) {
  const fam = (family || 'GOLD').toUpperCase()
  const served = data?.family ? String(data.family).toUpperCase() : null
  // the panel shows the page's PICK or says why not: an answer for another family / expiry / window never shows under this title
  const mismatch = !!data && ((!!served && served !== fam) || (!!expiry && !!data.expiry && data.expiry !== expiry) || (!!data.window && data.window !== window))
  const periods = mismatch ? [] : [...(data?.periods ?? [])].reverse()
  const contracts = mismatch ? [] : (data?.contracts ?? [])
  const lastEnd = periods[0]?.period_end ?? null
  const unit = data?.unit ?? '₹'
  const cols: Column<McxHistoryPeriod>[] = [
    { key: 'period', label: PERIOD_HEAD[window], render: r => (
      <span data-period={r.period} title={`${r.sessions} session${r.sessions === 1 ? '' : 's'} · ${istLabel(r.period_start)} → ${istLabel(r.period_end)} · volume ${num(r.volume)} lots${r.volume_missing ? ` (${r.volume_missing} without volume)` : ''}${r.note ? `\n${r.note}` : ''}`}>
        <span style={{ color: T.text }}>{r.period_label}</span>
        {r.partial && <span data-period-partial style={{ color: T.dim }}> · to date</span>}
        {r.sessions_spanned != null && r.sessions_spanned > 1 && <div data-period-span style={{ fontSize: 9, color: T.amber }}>Δ over {r.sessions_spanned} sessions</div>}
      </span>) },
    { key: 'close', label: `Close ${unit}`, align: 'right', title: tip('mcx_daily_close'), render: r => inr(r.close) },
    { key: 'close_chg_pct', label: 'Δ %', align: 'right', render: r => signedPct(r.close_chg_pct) },
    { key: 'oi', label: 'OI (lots)', align: 'right', render: r => num(r.oi) },
    { key: 'oi_chg', label: 'ΔOI', align: 'right', title: tip('oi_change'), render: r => signed(r.oi_chg) },
    { key: 'positions', label: 'Positions', title: tip('positions_opened_closed'), render: r => (
      <span data-positions={r.positions ?? ''} title={r.positions ? POSITIONS_READ[r.positions] : 'the first stored period: nothing earlier to compare with'} style={{ color: r.positions ? T.text : T.dim }}>{r.positions ?? '—'}</span>) },
    { key: 'label', label: 'Quadrant', title: tip('quadrant'), render: r => <QuadrantTag label={r.label} /> },
  ]
  return (
    <GPanel id="p.mcx.history" title={`MCX ${fam}${data?.expiry_label && !mismatch ? ` ${data.expiry_label}` : ''} · positions opened / closed — by contract`} badge="arithmetic"
      evidence="G-STUDY: positioning describes, it does not forecast" series={[MCX_HISTORY_ID]} catalog={catalog} layer={layer}
      fresh={data && !mismatch ? serverFreshness(data.freshness) : null} dateOnly={lastEnd ? istLabel(lastEnd) : null}
      subtitle={`${WINDOW_WORDS[window]}${data?.since && !mismatch ? ` · since ${istLabel(data.since)}` : ''} · live expiries only · newest first`}
      formula="Δ% = close(end) ÷ close(previous end) − 1 · ΔOI = OI(end) − OI(previous end), lots · quadrant = the daily tape's rule (M28)"
      copyB="which positions in the picked contract were opened or closed: OI up = new positions, OI down = positions closed. Every lot has a long and a short, so this never says who is long or short; the quadrant word names the period's mix of price and OI. The D / W / M picker above switches session, week or month."
      copyP="ICICI Breeze daily bars (a broker bar, not MCX's bhavcopy), OI in lots per expiry, live contracts only; W = ISO week to its last stored session, M = calendar month, each period's last close and OI against the previous period's, volume summed. Expiry-month periods are greyed: OI falls as positions roll. G-STUDY: positioning describes, it does not forecast.">
      <Degraded error={error} what="MCX daily history" />
      {!data && !error && <Loading label="MCX daily OI × close by contract" />}
      {data && mismatch && (
        <div data-mcx-history-mismatch style={{ fontSize: 11, color: T.amber }}>
          the server answered for {served} {data.expiry_label ?? '—'} ({data.window}), not the page's {fam} {expiry ?? 'front'} ({window}) — nothing shown rather than another contract's rows under this title
        </div>
      )}
      {data && !mismatch && (
        <div style={{ display: 'grid', gap: 10 }}>
          {data.ok === false && <div data-mcx-history-degraded style={{ fontSize: 11, color: T.dim }}>{data.error_info?.message ?? 'MCX daily history unavailable'}{data.error_info?.hint ? ` — ${data.error_info.hint}` : ''}</div>}
          {data.note && <div data-mcx-history-note style={{ fontSize: 11, color: T.dim }}>{data.note}</div>}
          <OiSplit contracts={contracts} date={data.contracts_date} family={fam} tip={tip} onPick={onPick} />
          <DataTable columns={cols} rows={periods} rowKey={r => r.period} dense maxHeight={320} exportName={`gold-mcx-${fam.toLowerCase()}-${(data.expiry_label ?? 'front').toLowerCase()}-${window}`}
            rowStyle={r => (r.mechanical ? { opacity: 0.55 } : undefined)}
            empty={<div data-mcx-history-empty style={{ padding: 8, color: T.dim, fontSize: 11 }}>no stored periods for {fam} {data.expiry_label ?? ''} yet</div>} />
          <div data-mcx-history-read style={{ fontSize: 10, color: T.muted, lineHeight: 1.5 }} title={data.rule}>{data.read}</div>
          <div style={{ fontSize: 9.5, color: T.dim }}>Source: {data.source} · greyed = expiry month (mechanical) · <span title={tip('since')}>history since the first stored bar</span></div>
        </div>
      )}
    </GPanel>
  )
}

/** Where the family's open positions sit: each live expiry's share of the family's OI on its newest session (lots on hover). */
function OiSplit({ contracts, date, family, tip, onPick }: { contracts: McxHistoryContract[]; date: string | null; family: string; tip: Tip; onPick?: (expiry: string) => void }) {
  if (!contracts.length) return null
  return (
    <div data-mcx-oi-split>
      <div style={{ fontSize: 10, color: T.muted, marginBottom: 3 }} title={tip('oi_share')}>
        where {family}'s open positions sit{date ? ` on ${istLabel(date)}` : ''}: share of the family's OI by live expiry{onPick ? ' · click an expiry to pick it for the page' : ''}
      </div>
      <div style={{ display: 'flex', height: 20, border: `1px solid ${T.border}` }}>
        {contracts.map(c => {
          const pickable = !!onPick && !c.selected
          return (
            <div key={c.expiry} data-split-expiry={c.expiry} data-split-selected={c.selected ? '1' : '0'} role={pickable ? 'button' : undefined} tabIndex={pickable ? 0 : undefined}
              onClick={pickable ? () => onPick?.(c.expiry) : undefined}
              onKeyDown={pickable ? e => { if (e.key === 'Enter') onPick?.(c.expiry) } : undefined}
              title={`${c.expiry_label ?? istLabel(c.expiry)}: ${num(c.oi)} lots · ${pct(c.share_pct, 1)} of ${family}'s open interest${c.selected ? ' · the picked contract' : pickable ? ' · click to pick this contract for the page' : ''}`}
              style={{ flex: `${Math.max(c.share_pct ?? 0, 0.01)} 1 0`, minWidth: 54, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden',
                       background: c.selected ? T.panel3 : T.panel2, borderRight: `1px solid ${T.border}`, boxShadow: c.selected ? `inset 0 0 0 1px ${T.amber}` : undefined,
                       cursor: pickable ? 'pointer' : 'default' }}>
              <span style={{ fontSize: 9, fontFamily: T.mono, color: c.selected ? T.bright : T.muted, whiteSpace: 'nowrap' }}>{c.expiry_label ?? c.expiry} {pct(c.share_pct, 0)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default PositioningView
