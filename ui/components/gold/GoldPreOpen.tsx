'use client'

/**
 * h.open — "Today's open": the Gold Pre-Open desk, moved from CMDT to GOLD › HEALTH (PLAN a.2, §b). Where MCX Gold
 * should open given COMEX and the rupee since the 23:30 close, and whether the opening price is worth chasing:
 *
 *   fair open = MCX settlement × (COMEX now ÷ COMEX at the MCX close) × (USD/INR now ÷ USD/INR at the close)
 *
 * Data: /api/gold/fair (today's /api/commodity/gold-preopen body + `baseline.session_label`, `accuracy`, `holiday`).
 * The verdict strip wears the `heuristic` chip with the measured miss (the ₹300 chase limit is unproven); the model is
 * `arithmetic`. The context table went to MACRO and the manual checks to PHYSICAL / CONTRACTS links (PLAN §5.11);
 * the headlines stay here as h.headlines with the risk-word count (heuristic). Inputs persist for the day under the
 * localStorage key `goldPreOpen.v1` (synced; kept across the move); the EUR/USD trigger lives in `gold.triggers.v1`.
 * The only component on the terminal that renders this desk (repetition test T9).
 */
import { apiError } from '@/lib/errors'
import { fmtSigned, fmtSignedInr } from '@/lib/format'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Chip, Input, Label, Loading, Notice, Panel, Stat, T, fmtInr, fmtNum, indianGrouping, sourceOf, inputSource } from '@/components/terminal'
import { getGoldFair } from '@/lib/gold/api'
import { bandReferenceLine, baselineSettlement, comexCode, dayLabel, fmtInr0, inrLegWords, morningCall, parseIso, preOpenCopyB, sessionLabel, settlementLine, settlementNoteShort, settlementQualityChip } from '@/lib/gold/format'
import { readTriggers, writeTriggers } from '@/lib/gold/prefs'
import type { CatalogRow, GoldContractSel, GoldFair, HealthFair, Layer } from '@/lib/gold/types'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { GoldAccuracyLog, useGoldLog } from './GoldAccuracyLog'
import { Term } from './ViewBits'
import { BadgeChip, GoldPanel, LagChipEl } from './kit'

const REFRESH_MS = 60_000
const todayKey = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
const STORE = 'goldPreOpen.v1'
const TRIGGERS_KEY = 'gold.triggers.v1'

interface Saved { day: string; baseline: string; mcx: string; threshold: string; done: Record<string, boolean> }
const blank = (): Saved => ({ day: todayKey(), baseline: '', mcx: '', threshold: '300', done: {} })

function load(): Saved {
  try {
    const s = JSON.parse(localStorage.getItem(STORE) || 'null') as (Saved & { trigger?: string }) | null
    if (!s) return blank()
    // Day-specific entries (close override, MCX price) reset each day; the chase limit carries over.
    return s.day === todayKey() ? { ...blank(), ...s, done: s.done ?? {} } : { ...blank(), threshold: s.threshold ?? '300' }
  } catch { return blank() }
}
function save(s: Saved) { try { localStorage.setItem(STORE, JSON.stringify(s)) } catch { /* storage unavailable */ } }

const num = (s: string) => { const v = Number(String(s).replace(/[,₹\s]/g, '')); return Number.isFinite(v) && v > 0 ? v : undefined }
const fx = (v: number | null | undefined, d = 2) => fmtNum(v, d)
const ago = (iso: string) => {
  const m = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000))
  return m < 60 ? `${m}m` : m < 1440 ? `${Math.round(m / 60)}h` : `${Math.round(m / 1440)}d`
}
// store timestamps parse through parseIso (a zone-less string is UTC, never browser-local); a bare clock ('23:30') prints as is
const istTime = (iso?: string | null) => {
  if (!iso) return '—'
  const d = parseIso(iso)
  return d ? d.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }) : iso
}

const VERDICT_STYLE: Record<string, { color: string; glyph: string }> = {
  OK: { color: T.green, glyph: '▲' },
  WAIT: { color: T.red, glyph: '■' },
  AWAITING_OPEN: { color: T.amber, glyph: '◷' },
  NEED_PRICE: { color: T.cyan, glyph: '◇' },
  NO_MODEL: { color: T.muted, glyph: '◌' },
}

/** Settlement → +COMEX → +rupee → fair, as a horizontal waterfall (h.moved: the one bar of "what moved"). */
export function Waterfall({ base, comex, inr }: { base: number; comex: number; inr: number }) {
  const fair = base + comex + inr
  const lo = Math.min(base, base + comex, fair), hi = Math.max(base, base + comex, fair)
  const pad = Math.max((hi - lo) * 0.25, 50)
  const x = (v: number) => ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100
  const bar = (from: number, to: number, color: string, label: string, y: number) => (
    <g key={label}>
      <rect x={`${Math.min(x(from), x(to))}%`} y={y} width={`${Math.max(Math.abs(x(to) - x(from)), 0.4)}%`} height={12} fill={color} opacity={0.85} />
      <text x={`${Math.max(x(from), x(to)) + 1}%`} y={y + 10} fill={T.muted} fontSize={10} fontFamily={T.mono}>{label}</text>
    </g>
  )
  return (
    <svg width="100%" height={70} role="img" aria-label="Gap build-up: COMEX part, rupee part, gap" data-gold-panel="h.moved">
      <line x1={`${x(base)}%`} x2={`${x(base)}%`} y1={0} y2={70} stroke={T.borderHi} strokeDasharray="2 3" />
      {bar(base, base + comex, comex >= 0 ? T.green : T.red, `COMEX ${fmtSignedInr(comex)}`, 6)}
      {bar(base + comex, fair, inr >= 0 ? T.green : T.red, `Rupee ${fmtSignedInr(inr)}`, 28)}
      {bar(base, fair, T.amber, `Gap ${fmtSignedInr(fair - base)}`, 50)}
    </svg>
  )
}

export function GoldPreOpen({ sel, layer = 'B', tooltips = {}, catalog = null, fair = null }: { sel?: GoldContractSel; layer?: Layer; tooltips?: Record<string, string>; catalog?: Record<string, CatalogRow> | null; fair?: HealthFair | null }) {
  const [saved, setSaved] = useState<Saved>(blank)
  const [trigger, setTrigger] = useState<string>('1.1161')
  const [data, setData] = useState<GoldFair | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const reqId = useRef(0)

  useEffect(() => { setSaved(load()); setTrigger(readTriggers().eurusd) }, [])
  // Typed in another window (or synced from another device): adopt it, so this window's next tick or edit builds on
  // it instead of writing its own stale copy back (C3-02). Writes happen only in update(), so nothing echoes.
  useExternalPrefChange(STORE, () => {
    const next = load()
    setSaved(s => (JSON.stringify(s) === JSON.stringify(next) ? s : next))
  })
  useExternalPrefChange(TRIGGERS_KEY, () => setTrigger(readTriggers().eurusd))
  const update = (patch: Partial<Saved>) => setSaved(s => { const n = { ...s, ...patch, day: todayKey() }; save(n); return n })
  const updateTrigger = (v: string) => { setTrigger(v); writeTriggers({ eurusd: v }) }

  const params = useMemo(() => ({
    baseline: num(saved.baseline), mcx_price: num(saved.mcx),
    threshold: num(saved.threshold) ?? 300, eurusd_trigger: num(trigger),
    contract: sel?.family, expiry: sel?.expiry ?? undefined,
  }), [saved.baseline, saved.mcx, saved.threshold, trigger, sel?.family, sel?.expiry])

  const fetchData = useCallback(async () => {
    const id = ++reqId.current
    setLoading(true)
    try {
      const r = await getGoldFair(params)
      if (id === reqId.current) { setData(r.data); setError(null) }
    } catch (e: unknown) {
      if (id === reqId.current) setError(apiError(e, 'Gold pre-open model unavailable'))
    } finally {
      if (id === reqId.current) setLoading(false)
    }
  }, [params])

  useEffect(() => {                                   // debounce typing, then refresh every minute
    const t = setTimeout(fetchData, 400)
    const iv = setInterval(fetchData, REFRESH_MS)
    return () => { clearTimeout(t); clearInterval(iv) }
  }, [fetchData])

  const m = data?.model ?? {}
  // the rupee leg, dated: the last INR=X print and whether it moved since the close reference (wave 1e minor)
  const inrWords = inrLegWords(m.inr ?? null)
  const v = data?.verdict
  const vs = VERDICT_STYLE[v?.state ?? 'NO_MODEL']
  const base = data?.baseline.value ?? null
  const mcxNow = data?.mcx_price.value ?? null
  const diff = mcxNow != null && m.fair_open != null ? mcxNow - m.fair_open : null
  const lot = m.lot_pnl_per_rupee ?? 100
  const istNow = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const istMin = istNow.getHours() * 60 + istNow.getMinutes()
  const marketOpen = istNow.getDay() >= 1 && istNow.getDay() <= 5 && istMin >= 9 * 60
  const acc = data?.accuracy
  const missNote = acc && acc.days > 0 ? `measured miss: median ${fmtInr0(acc.median_abs_error)} over ${acc.days} day${acc.days === 1 ? '' : 's'}` : 'no scored days yet'
  const tip = (k: string) => tooltips[k]
  // after 09:15 the pre-open question is settled (C-TRADER-14): the panel shows THIS MORNING'S CALL from the 08:45 snapshot row
  // (fair vs the captured open, model vs naive), "the open was not captured" when the 09:10 job missed, or "no snapshot
  // today (job missed)"; the DON'T CHASE / WAIT strip is a pre-open thing and never shows at 23:53
  const threshold = data?.threshold ?? 300
  const logState = useGoldLog(threshold)
  const logRows = useMemo(() => {
    const rows = [...(logState.log?.rows ?? [])]
    if (data?.today_log && !rows.some(r => r.date === data.today_log!.date)) rows.push(data.today_log)
    return rows
  }, [logState.log, data?.today_log])
  const call = morningCall(istMin, istNow.getDay(), todayKey(), logRows, data?.holiday?.closure ?? null)
  const todayRow = call.phase === 'call' ? call.row : null
  const callDone = call.phase === 'call'
  const stats = logState.log?.stats ?? (acc ? { days: acc.days, median_abs_error: acc.median_abs_error, mean_abs_error: acc.mean_abs_error, naive_mean_abs_error: acc.naive_mean_abs_error } : null)
  // wave 1d: the baseline names its source, session and quality; the band is the master's and names the session it belongs to
  const overridden = num(saved.baseline) != null
  const bl = useMemo(() => baselineSettlement(data, fair, sel?.family), [data, fair, sel?.family])
  const blNote = overridden ? null : settlementNoteShort(bl)
  // the band's value prints once per view: in the header strip's note when the check flags, else here (PLAN §f.6, round 2)
  const bandRef = overridden ? null : bandReferenceLine(bl, blNote?.tone !== 'amber')
  const bandDay = dayLabel(bl?.band_session)
  const bandApplies = dayLabel((data?.contract as { band_applies_to?: string | null } | undefined)?.band_applies_to ?? null)
  // the server's own flagged-check note repeats the strip's numbers: not printed here when the check is shown (PLAN §f.6)
  const notes = (data?.notes ?? []).filter(n => !(blNote && /ICICI band midpoint/i.test(n)))

  return (
    <GoldPanel id="h.open" title="Today's open" accent={T.amber} badge="arithmetic" layer={layer} catalog={catalog}
      series={['PREOPEN_LOG', 'COMEX_GC_FRONT', 'USDINR_CLOSE', 'MCX_CURVE_ICICI']}
      subtitle={data ? `${data.contract.name} ↔ COMEX ${comexCode(data.contract.comex)} · updated ${istTime(data.as_of)} IST · every 60 s` : 'MCX gold fair open from COMEX and the rupee'}
      freshness={data ? (data.freshness ?? { state: 'delayed', source: 'Yahoo', as_of: data.as_of }) : null}
      copyB={<>{preOpenCopyB(stats, threshold)} The <Term t="fair open" /> is arithmetic; the <Term t="chase limit" /> is the house rule.</>}
      copyP={`Multiplicative: settlement × COMEX ratio × USD/INR ratio; references are 30-min averages before the MCX close; settlement = last-30-min VWAP of the Breeze 1-minute bars (PROXY), else the ICICI band midpoint (PROXY; flagged when the two differ > 0.6 %). ${preOpenCopyB(stats, threshold).replace(/^Where MCX .*?close\. /u, '')} After 09:15 the panel shows the 08:45 snapshot against the captured open, never the live fair value.`}
      right={<>
        {loading && <span className="t-pulse" style={{ fontSize: 10, color: T.amber }}>UPDATING</span>}
        <Chip color={T.amber} onClick={fetchData} title="Recompute now">↻</Chip>
      </>}
      bodyStyle={{ display: 'grid', gap: 12 }}>

      {error && <Notice color={T.red}>Pre-open model unavailable: {error}</Notice>}
      {!data && !error && <Loading label="Computing fair open from COMEX, the rupee and the MCX settlement" />}
      {data?.holiday && <Notice color={T.amber}>MCX {data.holiday.closure === 'full' ? 'closed today' : `${data.holiday.closure} closure today`}: {data.holiday.note}</Notice>}
      {data && <>

      {/* 0. after 09:15: this morning's call (the 08:45 snapshot vs the captured open), or why there is none (C-TRADER-14) */}
      {call.phase === 'open_missing' && (
        <div data-gold-call="open-missing" style={{ padding: '10px 14px', border: `1px solid ${T.amber}55`, background: '#080b10', fontSize: 11.5, color: T.text }}>
          <div style={{ fontFamily: T.display, fontSize: 14, fontWeight: 700, letterSpacing: 1.2, color: T.amber }}>THIS MORNING&apos;S CALL · OPEN NOT CAPTURED</div>
          <div style={{ marginTop: 3 }}>The 08:45 snapshot said fair open {fmtInr(call.row.fair_open)}; the 09:10 capture did not run (ICICI session or job missed). Type the MCX open in the accuracy log below to score the day.</div>
        </div>
      )}
      {call.phase === 'no_snapshot' && (
        <div data-gold-call="no-snapshot" style={{ padding: '10px 14px', border: `1px solid ${T.amber}55`, background: '#080b10', fontSize: 11.5, color: T.text }}>
          <div style={{ fontFamily: T.display, fontSize: 14, fontWeight: 700, letterSpacing: 1.2, color: T.amber }}>NO SNAPSHOT TODAY (JOB MISSED)</div>
          <div style={{ marginTop: 3 }}>The 08:45 gold snapshot did not run today, so there is no call to score; the fair value below is the model re-computed now, not a pre-open call. The accuracy log keeps its {stats?.days ?? 0} scored day{(stats?.days ?? 0) === 1 ? '' : 's'}.</div>
        </div>
      )}
      {callDone && todayRow && (
        <div data-gold-call style={{ padding: '10px 14px', border: `1px solid ${Math.abs(todayRow.error ?? 0) <= threshold ? T.green : T.amber}55`, background: '#080b10' }}>
          <div style={{ fontFamily: T.display, fontSize: 14, fontWeight: 700, letterSpacing: 1.2, color: Math.abs(todayRow.error ?? 0) <= threshold ? T.green : T.amber }}>THIS MORNING&apos;S CALL</div>
          <div style={{ fontSize: 11.5, color: T.text, marginTop: 3 }}>
            MCX opened {fmtInr(todayRow.actual_open)} ({todayRow.actual_source ?? '—'}); the 08:45 fair open was {fmtInr(todayRow.fair_open)}
            {todayRow.error != null && <> · miss <b>{fmtSignedInr(todayRow.error)}</b></>}
            {todayRow.naive_error != null && <span style={{ color: T.muted }}> · naive (open = settlement) {fmtSignedInr(todayRow.naive_error)}</span>}
            {todayRow.stale_baseline && <Chip color={T.amber} style={{ marginLeft: 8 }}>STALE BASELINE</Chip>}
          </div>
        </div>
      )}

      {/* 1. verdict (heuristic: the chase limit) — a PRE-OPEN strip: not rendered once the day's call is settled (C-TRADER-14) */}
      {v && call.phase !== 'call' && call.phase !== 'no_snapshot' && call.phase !== 'open_missing' && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '12px 16px', border: `1px solid ${vs.color}`,
                      background: `${vs.color}12`, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 24, color: vs.color, lineHeight: 1 }}>{vs.glyph}</span>
          <div style={{ flex: 1, minWidth: 260 }}>
            {/* server-built sentences: numbers re-grouped the Indian way (₹144,376 → ₹1,44,376), C1-08 */}
            <div style={{ fontFamily: T.display, fontSize: 20, fontWeight: 700, letterSpacing: 1.4, color: vs.color, textTransform: 'uppercase' }}>{indianGrouping(String(v.title ?? ''))}</div>
            <div style={{ fontSize: 11.5, color: T.text, marginTop: 3 }}>{indianGrouping(String(v.detail ?? ''))}</div>
          </div>
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <BadgeChip badge="heuristic" evidence={missNote} />
            {(data.event_risk?.flagged_headlines ?? 0) > 0
              ? <Chip color={T.violet} title={`${data.event_risk.flagged_headlines} headlines mention war, strikes, sanctions, margins or halts (keyword tally, not sentiment; no sizing advice)`}>⚠ EVENT WORDS · {data.event_risk.flagged_headlines}</Chip>
              : <Chip color={T.muted} title="no headline in the last 24 h carries a risk word (keyword tally, not sentiment)">NO EVENT WORDS</Chip>}
          </span>
        </div>
      )}

      {/* wave 1d: the band-vs-VWAP check, visible — amber when the ICICI band belongs to another session */}
      {blNote && <div data-gold-settle-note={blNote.tone} style={{ padding: '6px 10px', border: `1px solid ${blNote.tone === 'amber' ? T.amber : T.border}`, background: blNote.tone === 'amber' ? `${T.amber}10` : 'transparent',
                                                         fontSize: 11, color: blNote.tone === 'amber' ? T.amber : T.muted }} title={tip('settlement_check')}>⚠ {blNote.text}</div>}

      {/* 2. the five numbers */}
      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <Stat label={<span title={tip('baseline')}>Baseline · MCX settlement</span>} value={fmtInr(base)} accent={T.violet}
          sub={<span data-gold-baseline-source data-gold-baseline-quality={overridden ? 'override' : settlementQualityChip(bl?.settlement_quality, bl?.settlement_source)} title={tip('settlement_source')}>{overridden ? 'your typed close (override)' : settlementLine(bl)}</span>} />
        <Stat label={<span title={tip('fair_open')}>{marketOpen ? 'Fair value now (model, not the 08:45 call)' : 'Fair open (model)'}</span>} value={fmtInr(m.fair_open)} accent={T.amber} color={T.amber}
          sub={m.gap_pct != null ? `${fmtSigned(m.gap_pct, 2)}% vs baseline` : '—'} />
        <Stat label={<span title={tip('gap')}>Expected gap</span>} value={fmtSignedInr(m.gap)} color={(m.gap ?? 0) >= 0 ? T.green : T.red} accent={(m.gap ?? 0) >= 0 ? T.green : T.red}
          sub={m.gap != null ? `${fmtSignedInr(m.gap * lot)} per 1 kg lot · ${fmtSignedInr(m.gap * 10)} per Gold Mini` : '—'} />
        <Stat label="MCX now vs fair" value={diff == null ? '—' : fmtSignedInr(diff)} accent={T.cyan}
          color={diff == null ? T.muted : Math.abs(diff) <= (data.threshold ?? 300) ? T.green : T.red}
          sub={mcxNow != null ? `MCX ${fmtInr(mcxNow)} · ${data.mcx_price.source}` : 'enter the MCX price at the open'} />
        <Stat label={<span title={tip('threshold')}>Chase limit</span>} value={fmtInr(data.threshold ?? 300)} accent={T.border}
          sub={m.threshold_in_comex_dollars != null ? `≈ $${m.threshold_in_comex_dollars} on COMEX · ${fmtSignedInr((data.threshold ?? 300) * lot)} per lot` : ''} />
      </div>

      {/* 3. what moved (the one bar) + inputs */}
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 1.6fr) minmax(260px, 1fr)' }}>
        <Panel source={sourceOf(data?.as_of ?? null, { source: 'COMEX + USD/INR', maxAgeDays: 1 })} badge="arithmetic" title="What moved since the MCX close" subtitle={`COMEX ${fmtSignedInr(m.comex_part)} · rupee ${fmtSignedInr(m.inr_part)} → fair ${fmtInr(m.fair_open)}`} accent={T.cyan} pad={10}>
          {base != null && m.comex_part != null && m.inr_part != null
            ? <Waterfall base={base} comex={m.comex_part} inr={m.inr_part} />
            : <div style={{ fontSize: 11, color: T.muted }}>Waiting for COMEX, the rupee and the settlement.</div>}
          <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.6 }}>
            Rule of thumb today: <b style={{ color: T.text }}>₹{fx(m.rs_per_comex_dollar, 1)}</b> per $1 on COMEX ·
            <b style={{ color: T.text }}> ₹{fx(m.rs_per_inr_rupee, 0)}</b> per ₹1 on USD/INR
            {m.comex && <> · COMEX {comexCode(m.comex.symbol)} {fx(m.comex.now, 1)} vs {fx(m.comex.ref, 1)} at the close</>}
            {m.inr && <> · ₹/$ {fx(m.inr.now, 3)} vs {fx(m.inr.ref, 3)}</>}.
            {inrWords && <span data-gold-inr-leg style={{ display: 'block', color: inrWords.flat ? T.amber : T.dim }}>{inrWords.text}</span>}
            {data.contract.band_low != null && <> The master&apos;s MCX band {fmtInr(data.contract.band_low)} – {fmtInr(data.contract.band_high)} (±{data.contract.band_pct}%){bandDay ? <>, set around the {bandDay} settlement{bandApplies ? <>, applied on {bandApplies}</> : null}</> : ' (the session it was set around is not stated)'}.</>}
            {bandRef && <span style={{ color: T.dim }}> {bandRef}.</span>}
          </div>
        </Panel>

        <Panel source={inputSource('your pre-open inputs (synced)')} title="Your inputs" subtitle="saved for today · synced" accent={T.violet} pad={10} bodyStyle={{ display: 'grid', gap: 10 }}>
          <Input label="MCX close override (₹ / 10 g)" value={saved.baseline} onChange={b => update({ baseline: b })}
            placeholder={base != null && !overridden ? `auto: ${fmtInr(base)}` : data.baseline.settlement_from_band ? `auto: ${fmtInr(data.baseline.settlement_from_band)}` : 'e.g. 149400'} />
          <Input label="MCX price now / pre-open (₹)" value={saved.mcx} onChange={x => update({ mcx: x })}
            placeholder={data.mcx_price.source === 'ICICI Breeze' ? `live: ${fmtInr(mcxNow)}` : 'type the opening price'} />
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <Input label="Chase limit (₹)" value={saved.threshold} onChange={x => update({ threshold: x })} />
            <Input label="EUR/USD trigger" value={trigger} onChange={updateTrigger} />
          </div>
          <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.5 }}>
            Leave the close empty to use the {sessionLabel(bl?.settlement_session, bl?.settlement_session_label)} ({settlementLine(bl).replace(/^[^·]*· /u, '')}). Connect ICICI on BRKR and the MCX price fills itself.
          </div>
        </Panel>
      </div>

      {/* 4. headlines (h.headlines) */}
      <GoldPanel id="h.headlines" title="Headlines" subtitle="last 24 h · gold topics" accent={T.amber} pad={0} badge="heuristic" layer={layer} catalog={catalog} series={[]}
        evidence={`${data.event_risk?.flagged_headlines ?? 0} risk words`}
        freshness={{ state: 'delayed', source: 'Google News', as_of: data.as_of }}
        copyB="Last 24 hours; the count is a keyword tally (war, strike, sanction, margin, halt), not sentiment, and carries no sizing advice."
        copyP="Headline topics are a prefs list (gold.triggers.v1); the tally is a house heuristic with no study behind it.">
        <div style={{ maxHeight: 300, overflowY: 'auto' }}>
          {(data.headlines ?? []).length === 0 && <div style={{ padding: 14, color: T.muted, fontSize: 11 }}>No headlines in the last 24 hours.</div>}
          {(data.headlines ?? []).map(h => (
            <a key={h.link} href={h.link} target="_blank" rel="noreferrer"
              style={{ display: 'grid', gridTemplateColumns: '92px 1fr 40px', gap: 10, padding: '6px 12px', textDecoration: 'none',
                       borderBottom: `1px solid ${T.border}`, alignItems: 'baseline' }}>
              <span style={{ fontSize: 9, letterSpacing: .8, color: T.cyan, textTransform: 'uppercase' }}>{h.topic}</span>
              <span style={{ fontSize: 11.5, color: T.text, lineHeight: 1.4 }}>{h.title}
                <span style={{ color: T.dim, fontSize: 10 }}> · {h.publisher}</span></span>
              <span style={{ fontSize: 10, color: T.muted, textAlign: 'right' }}>{ago(h.published_at)}</span>
            </a>
          ))}
        </div>
      </GoldPanel>

      <GoldAccuracyLog threshold={threshold} layer={layer} shared={logState} catalog={catalog} />

      {/* 5. method + data notes */}
      <div style={{ display: 'grid', gap: 6 }}>
        {notes.map(n => <Notice key={n} color={T.amber}>{indianGrouping(n)}</Notice>)}
        <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
          <Label>Method</Label> Fair open = MCX settlement × COMEX ratio × USD/INR ratio, references averaged over the last 30 minutes
          before MCX closed ({istTime(data.baseline.close_time)} IST). Settlement = the volume-weighted average of the last 30 minutes of
          the completed session&apos;s Breeze 1-minute bars (MCX&apos;s own settlement method; a PROXY, not the bhavcopy); without bars, the
          midpoint of the ±3% band in ICICI&apos;s public contract file (PROXY, set around an earlier session). USD/INR before 09:00 is the last stored Yahoo INR=X print (there is no overnight rupee feed: its time is printed under &lsquo;What moved&rsquo;). Research tool, not advice.
          <span style={{ marginLeft: 6 }}><LagChipEl freshness={{ state: 'delayed', source: 'Yahoo' }} /></span>
        </div>
      </div>
      </>}
    </GoldPanel>
  )
}
