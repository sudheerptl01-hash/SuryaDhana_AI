'use client'

/**
 * MEMB › "Index members & drivers" (reports/terminal_v2/PLAN.md 1.2; GO aliases DRVR / IMAP / CONTRIB; precedent
 * Bloomberg MEMB / IMAP contribution): who drove NIFTY 50 / NIFTY BANK over a horizon (1D / 5D / 1M / 3M / YTD / since
 * the last driver change), from the nightly point-in-time contribution table — points_i = L_{d−1} × w_i × r_i, additive,
 * so every horizon is a sum; the residual is shown, never hidden.
 *
 *  - `useDrivers(index, horizon)`: the route payload (members feed the MEMB table's horizon PTS column).
 *  - `DriverRegimeStrip`: the neutral-token regime line ("… — describes, does not predict"), `context`.
 *  - `FitChip`: the identity check on the table header, `arithmetic`.
 *  - `SectorContribution`, `MonthlyLeaderboard`, `ConcentrationChart`: the three panels below the table.
 *
 *  - `DriversTabNotice` + `TabGrey` (review M46): the route's `tab` state. `degraded` / `insufficient` print one
 *    note above the table and grey the horizon points, sectors, concentration and the monthly board (each captioned);
 *    `ok` shows everything as before. The regime strip adds the pending challenger (m028).
 *
 * Badges: members / sectors / concentration / fit `arithmetic`; regime, breadth, monthly leader `context`. No colour
 * on the leader; nothing here enters momentum.py, decision_desk.py, a directional alert or a ticket.
 */
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { BadgeChip, Chip, Panel, T, TickerLink, sourceOf } from '@/components/terminal'
import { BarRow, LineChart, type Marker } from '@/components/vol/charts'
import { DRIVER_INDICES, HORIZONS, HORIZON_LABEL, driversError, driversNote, fmtPts, fmtShare, getDriverMonthly, getDriverTimeline,
         getIndexDrivers, type DriverMonthly, type DriverTab, type DriverTimeline, type Horizon, type IndexDrivers } from './api'
import { challengerLine, dayMon, fitChip, monthlyAsOf, regimeLine, tabPanelCaption, tabView } from './driversModel'

export interface Loaded<X> { data: X | null; error: string | null; loading: boolean }

function useGet<X>(fn: (() => Promise<{ data: X }>) | null, deps: unknown[]): Loaded<X> {
  const [st, set] = useState<Loaded<X>>({ data: null, error: null, loading: !!fn })
  useEffect(() => {
    if (!fn) { set({ data: null, error: null, loading: false }); return }
    let alive = true
    set({ data: null, error: null, loading: true })
    fn().then(r => { if (alive) set({ data: r.data, error: null, loading: false }) })
      .catch((e: unknown) => { if (alive) set({ data: null, error: driversError(e), loading: false }) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return st
}

export const isDriverIndex = (index: string): boolean => (DRIVER_INDICES as readonly string[]).includes(index)

/** The drivers payload for an index + horizon (null fetch for an index the job does not compute: O-T12). */
export function useDrivers(index: string, horizon: Horizon): Loaded<IndexDrivers> {
  return useGet<IndexDrivers>(isDriverIndex(index) ? () => getIndexDrivers(index, horizon, 20) : null, [index, horizon])
}

/** Empty / degraded wording, one place: "history starts <date> · backfill pending", never a fake value. */
export function DriversEmpty({ index, error, payload }: { index: string; error: string | null; payload: IndexDrivers | null }) {
  if (!isDriverIndex(index)) {
    return <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6 }}>Drivers are computed for NIFTY 50 and NIFTY BANK; {index} waits for the owner's decision O-T12 (more indices in the first release).</div>
  }
  const why = error ?? driversNote(payload, payload?.members?.length ?? 0)
  return (
    <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6 }} data-drivers-empty>
      No stored contribution rows for {index}{why ? ` (${why})` : ''}. The nightly <code>index_drivers_daily</code> job (19:25 IST, retry 20:35)
      writes them from NSE's daily index file, the stored bhavcopy and the filings; history starts {payload?.history_since ? dayMon(payload.history_since) : 'the day the job first runs'}
      {' '}· backfill pending (2019-10 → today from stored data, owner-approved O-T4).
    </div>
  )
}

export function HorizonPicker({ value, onChange }: { value: Horizon; onChange: (h: Horizon) => void }) {
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }} data-drivers-horizon>
      {HORIZONS.map(h => (
        <Chip key={h} color={T.cyan} active={value === h} onClick={() => onChange(h)}
          title={h === 'since_change' ? 'since the 20-session driver last changed (hysteresis: ≥ 1.3× for 5 sessions)' : `points summed over ${HORIZON_LABEL[h]}`}>
          {HORIZON_LABEL[h]}</Chip>
      ))}
    </span>
  )
}

/** The identity on the members table header: arithmetic, amber only when the fit is degraded. */
export function FitChip({ d }: { d: IndexDrivers | null }) {
  const text = fitChip(d)
  if (!text) return null
  return (
    <span data-drivers-fit title={d?.fit?.note ?? 'Σ member points vs the index move over the window; MAE / R² over 60 sessions. The residual is the part the rebuilt weights do not explain.'}
      style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontFamily: T.mono, fontSize: 10, color: d?.fit?.degraded ? T.amber : T.muted,
               border: `1px solid ${d?.fit?.degraded ? T.amber : T.border}`, padding: '1px 6px', whiteSpace: 'nowrap' }}>
      {text}
    </span>
  )
}

/** M46: the tab's state, printed once above the members table when it is not `ok` (neutral border; never a direction). */
export function DriversTabNotice({ d }: { d: IndexDrivers | null }) {
  const v = tabView(d?.tab)
  if (!v.grey) return null
  return (
    <div data-drivers-tab={v.state} style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '6px 12px', borderBottom: `1px solid ${T.border}`,
                                            borderLeft: `3px solid ${T.amber}`, background: '#0b0a06', fontSize: 11, color: T.text, lineHeight: 1.5 }}>
      <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: 1, color: T.amber, flex: 'none' }}>{v.label}</span>
      <span style={{ flex: 1 }}>{v.caption}. The greyed figures below are the stored arithmetic, shown so the gap stays visible.</span>
      <BadgeChip badge="arithmetic" />
    </div>
  )
}

/** M46: a panel group the tab state greys (opacity + grayscale), with a one-line caption; untouched when `ok`. */
export function TabGrey({ tab, children }: { tab: DriverTab | null | undefined; children: ReactNode }) {
  const v = tabView(tab)
  const cap = tabPanelCaption(v)
  if (!v.grey) return <>{children}</>
  return (
    <div data-drivers-greyed={v.state}>
      <div style={{ fontFamily: T.mono, fontSize: 10, color: T.amber, letterSpacing: 0.5, margin: '0 0 4px 2px' }}>{cap}</div>
      <div style={{ opacity: 0.5, filter: 'grayscale(0.7)' }} title={v.caption ?? undefined}>{children}</div>
    </div>
  )
}

/** DRIVER REGIME: one neutral line, ending "describes, does not predict" (PLAN 1.2; G9). */
export function DriverRegimeStrip({ index, d, tl60 }: { index: string; d: IndexDrivers | null; tl60: DriverTimeline | null }) {
  const line = regimeLine(d?.driver ?? null, tl60, d?.concentration?.top5_abs_share ?? d?.driver?.top5_share ?? null,
    d?.breadth?.ew_minus_cw_pp ?? d?.driver?.ew_minus_cw_pp ?? null, d?.breadth?.word ?? null)
  const challenger = challengerLine(d?.driver?.challenger)       // m028: a raw leader the hysteresis has not adopted yet
  return (
    <div data-driver-regime style={{ display: 'flex', gap: 10, alignItems: 'center', padding: '7px 12px', marginBottom: 12, border: `1px solid ${T.border}`,
                                     borderLeft: `3px solid ${T.muted}`, background: '#080b10', fontSize: 12, color: T.text }}>
      <span style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: 1, color: T.muted, border: `1px solid ${T.border}`, padding: '1px 5px', flex: 'none' }}>
        DRIVER REGIME · {index}</span>
      <span style={{ flex: 1 }}>
        {line ?? `No driver state stored yet for ${index} · backfill pending — describes, does not predict`}
        {challenger && <span data-driver-challenger style={{ display: 'block', color: T.muted, fontSize: 11, marginTop: 2 }}>challenger pending: {challenger}</span>}
      </span>
      <BadgeChip badge={d?.badges?.driver ?? 'context'} />
    </div>
  )
}

export function SectorContribution({ d, error }: { d: IndexDrivers | null; error: string | null }) {
  const rows = useMemo(() => [...(d?.sectors ?? [])].sort((a, b) => Math.abs(b.points) - Math.abs(a.points)), [d])
  const max = Math.max(1, ...rows.map(r => Math.abs(r.points)))
  return (
    <Panel title="Sector contribution" accent={T.cyan} pad={10} badge={d?.badges?.sectors ?? 'arithmetic'}
      source={sourceOf(d?.as_of ?? null, { source: 'index_contribution_daily', hint: error ?? driversNote(d, rows.length) })}
      subtitle={d?.horizon?.from ? `${dayMon(d.horizon.from)} → ${dayMon(d.horizon.to)} · ${d.horizon.sessions} sessions · index points by NSE industry` : 'index points by NSE industry'}>
      {!rows.length ? <div style={{ fontSize: 11, color: T.muted }}>{error ?? 'no sector rows stored yet · backfill pending'}</div> : (
        <div style={{ display: 'grid', gap: 2 }} data-drivers-sectors>
          {rows.map(r => <BarRow key={r.industry} label={<span title={r.industry}>{r.industry}</span>} value={r.points} max={max} unit=" pts" color={T.cyan}
            sub={r.weight_pct != null ? <span style={{ color: T.dim }}> · {r.weight_pct.toFixed(1)}%w</span> : undefined} />)}
        </div>
      )}
    </Panel>
  )
}

export function MonthlyLeaderboard({ index }: { index: string }) {
  const m = useGet<DriverMonthly>(isDriverIndex(index) ? () => getDriverMonthly(index, 12) : null, [index])
  const rows = [...(m.data?.months ?? [])].reverse()
  const flagged = rows.filter(r => r.note)
  return (
    <Panel title="Monthly leaderboard · 12 months" accent={T.amber} pad={0} badge={m.data?.badge ?? 'context'}
      // m025: the data date is the last stored session (the route's as_of), not the first of the last month
      source={sourceOf(monthlyAsOf(m.data), { source: 'index_contribution_daily', maxAgeDays: 40, hint: m.error ?? driversNote(m.data, rows.length) })}
      subtitle="leader by |points| per month · top-3 adds and drags · the index move and what the members explain">
      {!rows.length ? <div style={{ padding: 12, fontSize: 11, color: T.muted }}>{m.loading ? 'Loading…' : m.error ?? 'no months stored yet · backfill pending'}</div> : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }} data-drivers-monthly>
            <thead><tr style={{ color: T.muted, fontSize: 10 }}>
              {['MONTH', 'LEADER', 'LEADER PTS', 'SHARE', 'TOP-3 ADD', 'TOP-3 DRAG', 'INDEX MOVE', 'EXPLAINED'].map((h, i) =>
                <th key={h} style={{ textAlign: i < 2 || i === 4 || i === 5 ? 'left' : 'right', padding: '5px 8px', borderBottom: `1px solid ${T.border}` }}>{h}</th>)}
            </tr></thead>
            <tbody>{rows.map(r => (
              <tr key={r.month} style={{ borderBottom: `1px solid ${T.border}` }}>
                <td style={{ padding: '4px 8px', color: T.muted }}>{r.month}</td>
                {/* no colour on the leader (PLAN 1.2): a name, marked ◆ when it changed from the month before */}
                <td style={{ padding: '4px 8px' }}>{r.leader ? <TickerLink symbol={r.leader} style={{ color: T.text }} /> : '—'}{r.leader_changed && <span title="leader changed from the month before" style={{ color: T.dim }}> ◆</span>}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right' }}>{fmtPts(r.leader_pts)}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: T.muted }}>{fmtShare(r.leader_share, 0)}</td>
                {/* an add is a name that added points, a drag one that took them away: a month with fewer than three of
                    either lists fewer, never a negative "add" */}
                <td style={{ padding: '4px 8px', color: T.muted }}>{r.top3_add.filter(x => x.points > 0).map(x => `${x.symbol} ${fmtPts(x.points, 0)}`).join(' · ') || '—'}</td>
                <td style={{ padding: '4px 8px', color: T.muted }}>{r.top3_drag.filter(x => x.points < 0).map(x => `${x.symbol} ${fmtPts(x.points, 0)}`).join(' · ') || '—'}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right' }}>{fmtPts(r.index_move_pts)}</td>
                {/* m026: a month with a session the weights missed by > 150 pts is marked †; its note names the sessions */}
                <td style={{ padding: '4px 8px', textAlign: 'right', color: r.note ? T.dim : T.muted }} title={r.note ?? undefined} data-drivers-month-flag={r.note ? r.month : undefined}>
                  {fmtPts(r.explained_pts)}{r.note ? ' †' : ''}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      {flagged.length > 0 && <div style={{ padding: '6px 12px 0', fontSize: 10, color: T.muted, lineHeight: 1.5 }} data-drivers-month-notes>
        {flagged.map(r => <div key={r.month}>† {r.month}: {r.note}</div>)}</div>}
      {m.data?.note && rows.length > 0 && <div style={{ padding: '6px 12px', fontSize: 10, color: T.dim }}>{m.data.note}</div>}
    </Panel>
  )
}

export function ConcentrationChart({ index, tl20 }: { index: string; tl20: Loaded<DriverTimeline> }) {
  const p = tl20.data?.points ?? []
  const markers: Marker[] = p.map((x, i) => ({ i, kind: x.changed ? 'change' : '' })).filter(m => m.kind)
  const last = p.length ? p[p.length - 1] : null
  return (
    <Panel title="Concentration & breadth" accent={T.violet} pad={8} badge={tl20.data?.badge ?? 'context'}
      source={sourceOf(tl20.data?.as_of ?? null, { source: 'index_driver_state', hint: tl20.error ?? driversNote(tl20.data, p.length) })}
      subtitle={last ? `20-session window · ${p.length} sessions to ${dayMon(last.date)} · ┆ = driver change (${tl20.data?.changes.length ?? 0})` : `${index} · 20-session window`}>
      {p.length < 2 ? <div style={{ fontSize: 11, color: T.muted }}>{tl20.loading ? 'Loading…' : tl20.error
        ?? (p.length === 1 ? `one session stored (${dayMon(p[0].date)}) · the chart fills nightly · backfill pending` : 'no driver-state rows stored yet · backfill pending')}</div> : (
        <>
          <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>violet = top-5 share of the move · cyan = leader's share (left, %) · dashed = EW − CW return, pp (right) · effective N {last?.effective_n?.toFixed(1) ?? '—'}</div>
          <LineChart dates={p.map(x => x.date)} height={170} lUnit="%" rUnit="" markers={markers} ariaLabel="concentration and breadth"
            series={[{ label: 'top-5 share', color: T.violet, values: p.map(x => (x.top5_share == null ? null : x.top5_share * 100)), w: 1.5 },
                     { label: 'leader share', color: T.cyan, values: p.map(x => (x.leader_share == null ? null : x.leader_share * 100)), w: 1.1 },
                     { label: 'EW − CW', color: T.muted, values: p.map(x => x.ew_minus_cw_pp), axis: 'R', w: 1, dash: '4 3' }]} />
          <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{tl20.data?.note}</div>
        </>
      )}
    </Panel>
  )
}

/** The timelines the regime strip and the chart read (20- and 60-session windows), one fetch each per index. */
export function useTimelines(index: string): { tl20: Loaded<DriverTimeline>; tl60: Loaded<DriverTimeline> } {
  const tl20 = useGet<DriverTimeline>(isDriverIndex(index) ? () => getDriverTimeline(index, 20, 250) : null, [index])
  const tl60 = useGet<DriverTimeline>(isDriverIndex(index) ? () => getDriverTimeline(index, 60, 250) : null, [index])
  return { tl20, tl60 }
}
