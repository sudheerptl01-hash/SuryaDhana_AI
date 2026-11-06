'use client'

/**
 * OMON › history (reports/terminal_v2/PLAN.md 1.1 panel 1; precedent Bloomberg HIVG / "IVOL %ile / rank", Sensibull IV
 * chart, tastytrade IVR): `iv30_cm` (constant-maturity, no expiry saw-tooth) with the monthly fixed-expiry line and the
 * India VIX overlay (one source: vix_daily; the VIX appears on this chart and nowhere else on OMON), results / expiry
 * markers, and the two chips "IV percentile 60 · IV rank 21 (252 sessions, iv30_cm)" — each defined on hover, never
 * one for the other (R-IV §3: the old "IV rank 73" was a percentile).
 *
 * Until B1's tables are deployed the route answers `ok: false`: the panel then draws the legacy near-expiry ATM series
 * (relabelled: its number is a PERCENTILE on the saw-tooth series) and says why. Badges: IV / rank / percentile
 * `arithmetic`; the VIX overlay `arithmetic`. Describes, does not predict.
 */
import { useEffect, useState } from 'react'
import { BadgeChip, Chip, Panel, T, fmtNum, sourceOf } from '@/components/terminal'
import { percentileOf } from '@/components/terminal/source'
import { LineChart, type Marker } from './charts'
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
    const dateIdx = new Map(rows.map((r, i) => [r.date, i]))
    // results markers always; expiry markers only on a window short enough for them to read (≤ 320 sessions)
    const markers: Marker[] = v2.events.map(e => ({ i: dateIdx.get(e.date) ?? -1, kind: e.kind })).filter(m => m.i >= 0 && (m.kind !== 'expiry' || rows.length <= 320))
    const vixByDate = new Map(v2.vix.map(v => [v.date, v.close]))
    const vix = rows.map(r => vixByDate.get(r.date) ?? null)
    const hasVix = vix.some(v => v != null)
    const since = dayLabel(v2.since)
    // m051: the amber line is the first expiry 20–60 days out — a weekly when one falls in the window — not NSE's monthly
    const subtitle = `${since} → ${dayLabel(v2.as_of)} · ${v2.sessions} sessions · violet = IV30 (constant maturity) · amber = ~1-month ATM IV (first expiry 20–60 d)${hasVix ? ' · green = India VIX' : ''} · ┆ results · ┊ ~1-month series roll · model ${v2.model_version ?? '—'} · r ${v2.r_source}`
    return (
      <Panel title={`${symbol} implied volatility · history`} accent={T.violet} pad={collapsed ? 6 : 8} style={{ marginBottom: 12 }}
        source={sourceOf(v2.as_of, { source: 'NSE F&O bhavcopy' })} badge={v2.badges.iv}
        right={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Chip color={T.violet} title={`${v2.definitions.iv_pctile_252 ?? 'IV percentile'} Window: ${win} sessions on ${v2.rank.on}.`} aria-label="IV percentile">
            IV PERCENTILE {pctile != null ? fmtNum(pctile, 0) : '—'}</Chip>
          <Chip color={T.violet} title={`${v2.definitions.iv_rank_252 ?? 'IV rank'} Window: ${win} sessions on ${v2.rank.on}.`} aria-label="IV rank">
            IV RANK {rank != null ? fmtNum(rank, 0) : '—'}</Chip>
          <span style={{ fontSize: 9.5, color: T.dim, fontFamily: T.mono }}>({win} sessions, {v2.rank.on})</span>
          {toggle}
        </span>}>
        {collapsed ? (
          // the strip names the window and the overlay; the IV levels themselves are in the chain header strip (one number,
          // one place: PLAN §0.4), so the collapsed chart repeats none of them
          <div style={{ fontSize: 10.5, color: T.muted, fontFamily: T.mono, display: 'flex', gap: 14, flexWrap: 'wrap' }}>
            <span>IV30 (constant maturity) · ~1-month ATM line{hasVix ? ' · India VIX overlay' : ''} · results / series-roll markers</span>
            <span style={{ color: T.dim }}>{since} → {dayLabel(v2.as_of)} · {v2.sessions} sessions · ~1-month series {last.monthly_expiry ?? '—'} (first expiry 20–60 d)</span>
          </div>
        ) : (
          <>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 6 }}>{subtitle}</div>
            <LineChart dates={rows.map(r => r.date)} height={190} lUnit="%" markers={markers} ariaLabel="IV history with VIX overlay"
              series={[
                { label: 'IV30', color: T.violet, values: rows.map(r => r.iv30_cm), w: 1.7 },
                { label: '~1-month ATM IV', color: T.amber, values: rows.map(r => r.monthly_atm_iv), w: 1.1 },
                ...(hasVix ? [{ label: 'India VIX', color: T.green, values: vix, w: 1.1, dash: '4 3' }] : []),
              ]} />
            <div style={{ fontSize: 10, color: T.dim, marginTop: 4, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              <span>{v2.note}</span>
              {hasVix && <BadgeChip badge={v2.badges.vix} note="India VIX from NSE's daily index file (vix_daily)." />}
            </div>
          </>
        )}
      </Panel>
    )
  }

  if (legacy && legacy.rows.length >= 20) {
    const iv = legacy.rows.map(r => r.atm_iv).filter((v): v is number => v != null)
    const now = iv[iv.length - 1]
    // the honest label (Wave 0.6): this number is the share of the past year BELOW today — a percentile on the
    // near-expiry saw-tooth series, not a rank. The server-side pair wins when the legacy route carries it.
    const pct = legacy.iv_pctile_252 ?? percentileOf(iv, now)
    const rank = legacy.iv_rank_252 ?? null
    return (
      <Panel title={`${symbol} implied volatility · history`} accent={T.violet} pad={collapsed ? 6 : 8} style={{ marginBottom: 12 }}
        source={sourceOf(legacy.rows[legacy.rows.length - 1]?.date, { source: 'NSE F&O bhavcopy' })} badge="arithmetic"
        right={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <Chip color={T.violet} title="IV percentile: the share of the past year's sessions whose near-expiry ATM IV was below today's. On the near-expiry series it rises into every expiry (the saw-tooth); the constant-maturity series replaces it once the IV store is deployed." aria-label="IV percentile">
            IV PERCENTILE {pct != null ? fmtNum(pct, 0) : '—'}</Chip>
          <Chip color={T.violet} title="IV rank: where today's IV sits between the past year's minimum (0) and maximum (100). Served by the IV store (iv_summary_daily) once deployed; not computable from the legacy series here." aria-label="IV rank">
            IV RANK {rank != null ? fmtNum(rank, 0) : '—'}</Chip>
          {toggle}
        </span>}>
        {collapsed ? (
          <div style={{ fontSize: 10.5, color: T.muted, fontFamily: T.mono }}>near-expiry ATM IV (legacy series) · {legacy.rows[0].date} → {legacy.rows[legacy.rows.length - 1].date}{error ? <span style={{ color: T.amber }}> · IV store: {error} · backfill pending</span> : null}</div>
        ) : (
          <>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 6 }}>
              near-expiry ATM IV now {fmtNum(now, 2)}% · violet = IV (left) · amber = put/call OI (right) · legacy series (near expiry only: it rises into each expiry)
              {error && <span style={{ color: T.amber }}> · IV store: {error}</span>}
            </div>
            <LineChart dates={legacy.rows.map(r => r.date)} height={170} lUnit="%" ariaLabel="IV and PCR history (legacy)"
              series={[{ label: 'ATM IV', color: T.violet, values: legacy.rows.map(r => r.atm_iv), w: 1.7 },
                       { label: 'PCR', color: T.amber, values: legacy.rows.map(r => r.pcr), axis: 'R', w: 1.1 }]} />
          </>
        )}
      </Panel>
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
