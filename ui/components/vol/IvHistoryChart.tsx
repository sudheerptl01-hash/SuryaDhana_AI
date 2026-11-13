'use client'

/**
 * OMON › history (reports/terminal_v2/PLAN.md 1.1 panel 1; precedent Bloomberg HIVG / "IVOL %ile / rank", Sensibull IV
 * chart, tastytrade IVR): `iv30_cm` (constant-maturity, no expiry saw-tooth) with the monthly fixed-expiry line and the
 * India VIX overlay (one source: vix_daily; the VIX appears on this chart and nowhere else on OMON), results / expiry
 * markers, and the two chips "IV percentile 60 · IV rank 21 (252 sessions, iv30_cm)" — each defined on hover, never
 * one for the other (R-IV §3: the old "IV rank 73" was a percentile).
 *
 * FINAL ROUND W3 (B-OMON, charts/PLAN.md B1): the chart is lightweight-charts through the kit — InteractiveSeries in
 * an ExpandableChart shell (wheel zoom, drag pan, crosshair values in the header legend, FIT / PNG / ⛶ expand),
 * linkGroup `omon`. VIX rides the right axis as the overlay. Sessions whose IV30 was flat-filled from one expiry
 * (`cm30_flat` in `quality_flags`) are marked on the line (L-10 — the flag is already served, no server change).
 * T-21: the percentile / rank pair carries a one-line "how they differ" note, badge `arithmetic`.
 *
 * Until B1's tables are deployed the route answers `ok: false`: the panel then draws the legacy near-expiry ATM series
 * (relabelled: its number is a PERCENTILE on the saw-tooth series) and says why. Badges: IV / rank / percentile
 * `arithmetic`; the VIX overlay `arithmetic`. Describes, does not predict.
 */
import { useEffect, useState } from 'react'
import { BadgeChip, Chip, Panel, T, fmtNum, sourceOf } from '@/components/terminal'
import { percentileOf } from '@/components/terminal/source'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { InteractiveSeries, type MarkerSpec, type SeriesSpec } from '@/components/terminal/InteractiveSeries'
import { getIvHistory, getOptionHistoryLegacy, storeNote, volError, type IvHistory, type OptionHistoryLegacy } from './api'

export interface IvHistoryState { v2: IvHistory | null; legacy: OptionHistoryLegacy | null; error: string | null; loading: boolean }

/** Both sources, latest request wins; the legacy chart is the fallback while the v2 store is not deployed. */
export function useIvHistory(symbol: string, days = 750): IvHistoryState {
  const [st, set] = useState<IvHistoryState>({ v2: null, legacy: null, error: null, loading: true })
  useEffect(() => {
    let alive = true
    set({ v2: null, legacy: null, error: null, loading: true })
    getIvHistory(symbol, days).then(r => {
      if (!alive) return
      if (r.data.ok && r.data.rows.length >= 20) { set({ v2: r.data, legacy: null, error: null, loading: false }); return }
      const why = storeNote(r.data) ?? (r.data.rows.length ? `only ${r.data.rows.length} stored sessions` : 'no stored sessions')
      if (!['NIFTY', 'BANKNIFTY'].includes(symbol)) { set({ v2: r.data, legacy: null, error: why, loading: false }); return }
      getOptionHistoryLegacy(symbol, 260).then(l => { if (alive) set({ v2: r.data, legacy: l.data, error: why, loading: false }) })
        .catch(() => { if (alive) set({ v2: r.data, legacy: null, error: why, loading: false }) })
    }).catch((e: unknown) => {
      if (!alive) return
      const msg = volError(e, 'IV history unavailable')
      if (!['NIFTY', 'BANKNIFTY'].includes(symbol)) { set({ v2: null, legacy: null, error: msg, loading: false }); return }
      getOptionHistoryLegacy(symbol, 260).then(l => { if (alive) set({ v2: null, legacy: l.data, error: msg, loading: false }) })
        .catch(() => { if (alive) set({ v2: null, legacy: null, error: msg, loading: false }) })
    })
    return () => { alive = false }
  }, [symbol, days])
  return st
}

const dayLabel = (d: string | null | undefined) => (d ? new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }) : '—')

/** T-21: one line on how the pair differs — on both chips' hovers and as the pair's `arithmetic` badge note. */
const PCT_VS_RANK = 'Percentile = the share of days below today; rank = position in the 1-year min–max range — they differ when the distribution is skewed.'

const pctFmt = (v: number) => `${v.toFixed(1)}%`

export function IvHistoryChart({ symbol, state, collapsed = false, onToggle }: { symbol: string; state: IvHistoryState; collapsed?: boolean; onToggle?: () => void }) {
  const { v2, legacy, error, loading } = state
  const toggle = onToggle ? <Chip color={T.muted} onClick={onToggle} title={collapsed ? 'show the history chart' : 'collapse the chart to a strip'}>{collapsed ? 'HISTORY ▾' : 'HISTORY ▴'}</Chip> : null
  if (loading) return <Panel source={sourceOf(null, { source: 'iv_summary_daily', hint: 'loading' })} title={`${symbol} implied volatility · history`} accent={T.violet} pad={8} right={toggle} style={{ marginBottom: 12 }}><div style={{ fontSize: 11, color: T.dim }}>Loading the stored IV series…</div></Panel>

  if (v2 && v2.ok && v2.rows.length >= 20) {
    const rows = v2.rows
    const last = rows[rows.length - 1]
    // the stored rank / percentile (written by iv_eod over the full 252-session window) wins; the recomputed pair is
    // the fallback when the stored columns are empty (a backfill in progress)
    const stored = v2.rank.stored
    const rank = stored.iv_rank_252 ?? v2.rank.iv_rank_252
    const pctile = stored.iv_pctile_252 ?? v2.rank.iv_pctile_252
    const win = Math.min(v2.rank.window_sessions, rows.length)
    const vixByDate = new Map(v2.vix.map(v => [v.date, v.close]))
    const hasVix = rows.some(r => vixByDate.get(r.date) != null)
    const since = dayLabel(v2.since)
    const chips = (
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        <Chip color={T.violet} title={`${v2.definitions.iv_pctile_252 ?? 'IV percentile'} ${PCT_VS_RANK} Window: ${win} sessions on ${v2.rank.on}.`} aria-label="IV percentile">
          IV PERCENTILE {pctile != null ? fmtNum(pctile, 0) : '—'}</Chip>
        <Chip color={T.violet} title={`${v2.definitions.iv_rank_252 ?? 'IV rank'} ${PCT_VS_RANK} Window: ${win} sessions on ${v2.rank.on}.`} aria-label="IV rank">
          IV RANK {rank != null ? fmtNum(rank, 0) : '—'}</Chip>
        <BadgeChip badge="arithmetic" note={PCT_VS_RANK} />
        <span style={{ fontSize: 10, color: T.dim, fontFamily: T.mono }}>({win} sessions, {v2.rank.on})</span>
        {toggle}
      </span>
    )
    if (collapsed) {
      return (
        <Panel title={`${symbol} implied volatility · history`} accent={T.violet} pad={6} style={{ marginBottom: 12 }}
          source={sourceOf(v2.as_of, { source: 'NSE F&O bhavcopy' })} badge={v2.badges.iv} right={chips}>
          {/* the strip names the window and the overlay; the IV levels themselves are in the chain header strip (one number,
              one place: PLAN §0.4), so the collapsed chart repeats none of them */}
          <div style={{ fontSize: 11, color: T.muted, fontFamily: T.mono, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>IV30 (constant maturity) · ~1-month ATM line{hasVix ? ' · India VIX overlay' : ''} · results / series-roll markers</span>
            <span style={{ color: T.dim }}>{since} → {dayLabel(v2.as_of)} · {v2.sessions} sessions · ~1-month series {last.monthly_expiry ?? '—'} (first expiry 20–60 d)</span>
          </div>
        </Panel>
      )
    }
    // open: lightweight-charts through the kit (B1) — results markers always; expiry (series-roll) markers only on a
    // window short enough for them to read (≤ 320 sessions); cm30_flat sessions marked on the IV30 line (L-10)
    const markers: MarkerSpec[] = [
      ...v2.events.filter(e => e.kind !== 'expiry' || rows.length <= 320).map(e => ({ t: e.date, kind: e.kind })),
      ...rows.filter(r => String(r.quality_flags ?? '').includes('cm30_flat')).map(r => ({ t: r.date, kind: 'cm30_flat' })),
    ]
    const hasFlat = markers.some(m => m.kind === 'cm30_flat')
    const series: SeriesSpec[] = [
      { id: 'iv30', label: 'IV30', color: T.violet, axis: 'L', w: 2, format: pctFmt, points: rows.map(r => ({ t: r.date, v: r.iv30_cm })) },
      { id: 'm1atm', label: '~1M ATM IV', color: T.amber, axis: 'L', w: 1, format: pctFmt, points: rows.map(r => ({ t: r.date, v: r.monthly_atm_iv })) },
      ...(hasVix ? [{ id: 'vix', label: 'India VIX', color: T.green, axis: 'R' as const, w: 1, dashed: true, format: (v: number) => v.toFixed(2),
                      points: rows.map(r => ({ t: r.date, v: vixByDate.get(r.date) ?? null })) }] : []),
    ]
    return (
      <ExpandableChart title={`${symbol} implied volatility · history`} accent={T.violet} style={{ marginBottom: 12 }} height={276}
        source={sourceOf(v2.as_of, { source: 'NSE F&O bhavcopy' })}
        badges={[{ label: v2.badges.iv }, ...(hasVix ? [{ label: v2.badges.vix, note: "India VIX from NSE's daily index file (vix_daily)." }] : [])]}
        legend={<span>{since} → {dayLabel(v2.as_of)} · {v2.sessions} sessions</span>}>
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: T.muted, flex: '1 1 260px', minWidth: 0 }}>
              violet = IV30 (constant maturity) · amber = ~1-month ATM IV (first expiry 20–60 d){hasVix ? ' · green (right axis) = India VIX' : ''} ·
              ● results · ▪ ~1-month series roll{hasFlat ? ' · cyan ● = IV30 flat-filled from one expiry (cm30_flat)' : ''} ·
              model {v2.model_version ?? '—'} · r {v2.r_source} · wheel zoom · drag pan · crosshair values in the header
            </span>
            {chips}
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <InteractiveSeries height={170} linkGroup="omon" unitL="%" series={series} markers={markers}
              alertOverlay={{ symbol, kind: 'iv30' }}
              ariaLabel="IV history with VIX overlay (wheel zoom, drag pan, crosshair)" />
          </div>
          <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{v2.note}</div>
        </div>
      </ExpandableChart>
    )
  }

  if (legacy && legacy.rows.length >= 20) {
    const iv = legacy.rows.map(r => r.atm_iv).filter((v): v is number => v != null)
    const now = iv[iv.length - 1]
    // the honest label (Wave 0.6): this number is the share of the past year BELOW today — a percentile on the
    // near-expiry saw-tooth series, not a rank. The server-side pair wins when the legacy route carries it.
    const pct = legacy.iv_pctile_252 ?? percentileOf(iv, now)
    const rank = legacy.iv_rank_252 ?? null
    const chips = (
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        <Chip color={T.violet} title={`IV percentile: the share of the past year's sessions whose near-expiry ATM IV was below today's. On the near-expiry series it rises into every expiry (the saw-tooth); the constant-maturity series replaces it once the IV store is deployed. ${PCT_VS_RANK}`} aria-label="IV percentile">
          IV PERCENTILE {pct != null ? fmtNum(pct, 0) : '—'}</Chip>
        <Chip color={T.violet} title={`IV rank: where today's IV sits between the past year's minimum (0) and maximum (100). Served by the IV store (iv_summary_daily) once deployed; not computable from the legacy series here. ${PCT_VS_RANK}`} aria-label="IV rank">
          IV RANK {rank != null ? fmtNum(rank, 0) : '—'}</Chip>
        <BadgeChip badge="arithmetic" note={PCT_VS_RANK} />
        {toggle}
      </span>
    )
    if (collapsed) {
      return (
        <Panel title={`${symbol} implied volatility · history`} accent={T.violet} pad={6} style={{ marginBottom: 12 }}
          source={sourceOf(legacy.rows[legacy.rows.length - 1]?.date, { source: 'NSE F&O bhavcopy' })} badge="arithmetic" right={chips}>
          <div style={{ fontSize: 11, color: T.muted, fontFamily: T.mono }}>near-expiry ATM IV (legacy series) · {legacy.rows[0].date} → {legacy.rows[legacy.rows.length - 1].date}{error ? <span style={{ color: T.amber }}> · IV store: {error} · backfill pending</span> : null}</div>
        </Panel>
      )
    }
    return (
      <ExpandableChart title={`${symbol} implied volatility · history`} accent={T.violet} style={{ marginBottom: 12 }} height={248}
        source={sourceOf(legacy.rows[legacy.rows.length - 1]?.date, { source: 'NSE F&O bhavcopy' })} badges={[{ label: 'arithmetic' }]}
        legend={<span>{legacy.rows[0].date} → {legacy.rows[legacy.rows.length - 1].date} · legacy near-expiry series</span>}>
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
          <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start', flexWrap: 'wrap', marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: T.muted, flex: '1 1 260px', minWidth: 0 }}>
              near-expiry ATM IV now {fmtNum(now, 2)}% · violet = IV (left) · amber = put/call OI (right) · legacy series (near expiry only: it rises into each expiry)
              {error && <span style={{ color: T.amber }}> · IV store: {error}</span>}
            </span>
            {chips}
          </div>
          <div style={{ flex: 1, minHeight: 0 }}>
            <InteractiveSeries height={150} linkGroup="omon" unitL="%"
              series={[{ id: 'atm_iv', label: 'ATM IV', color: T.violet, axis: 'L', w: 2, format: pctFmt, points: legacy.rows.map(r => ({ t: r.date, v: r.atm_iv })) },
                       { id: 'pcr', label: 'PCR', color: T.amber, axis: 'R', w: 1, format: (v: number) => v.toFixed(2), points: legacy.rows.map(r => ({ t: r.date, v: r.pcr })) }]}
              ariaLabel="IV and PCR history, legacy series (wheel zoom, drag pan, crosshair)" />
          </div>
        </div>
      </ExpandableChart>
    )
  }
  return (
    <Panel title={`${symbol} implied volatility · history`} accent={T.violet} pad={8} style={{ marginBottom: 12 }} right={toggle}
      source={sourceOf(null, { source: 'iv_summary_daily', hint: error ?? 'no stored series' })}>
      <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6 }}>
        No stored IV history for {symbol} yet{error ? ` (${error})` : ''}. The nightly <code>iv_eod</code> job writes <code>iv_summary_daily</code> for every F&O
        underlying from the stored bhavcopies; histories begin the day the job starts and backfill from the cached files on O-T4.
      </div>
    </Panel>
  )
}
