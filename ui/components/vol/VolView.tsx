'use client'

/**
 * DERV › VOL (reports/terminal_v2/PLAN.md 1.1 panel 4, GO alias `VOL`; precedents Bloomberg SKEW / VCA / GV cone /
 * OSA expected move / GV-WVOL screen, Quantsapp IV percentile): for one underlying, the skew history (25Δ with the
 * smile today vs a month ago), the term structure with its slope history, the IV cone, "IV paid vs vol delivered" over
 * the last 12 monthly expiries, the expected-move hit-rate over 60 sessions — and the VOL screener across every
 * underlying (sort / filter / CSV). Levels and identities are `arithmetic`; skew, term, spread and the screener's
 * comparisons are `context` (neutral tone). Nothing here feeds a trade; every sentence describes, does not predict.
 *
 * Every block loads on its own (latest request wins) and degrades alone while B1's tables are not deployed.
 *
 * Fix wave 2 (V-VOL, review 5 Nov 2026): "IV paid vs vol delivered" now reads the server's ledger — NSE MONTHLY expiries,
 * the ATM IV at ≈ 30 DTE, the close-to-close (zero-mean) vol delivered over the option's own life (M02); the screener's
 * spread is labelled close-to-close with the Yang-Zhang one named beside it and RV20 shown for both (M01), BAN from NSE's
 * own list and % MWPL from the merged combined-OI row (M43), a near → next term read where 90 days is not bracketed (m070), "new"
 * where a rank needs more history (m072), a flat-filled IV30 marked ≈ (M43); the smile compares like tenors (m071).
 */
import { useEffect, useMemo, useState } from 'react'
import { BadgeChip, Chip, DataTable, Panel, T, TickerLink, fmtNum, ordinal, sourceOf, type Column } from '@/components/terminal'
import { percentileOf } from '@/components/terminal/source'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { InteractiveSeries } from '@/components/terminal/InteractiveSeries'
import { XYChart } from './charts'
import { getIvCone, getIvHistory, getIvPaidDelivered, getIvSurface, getVolScreen, storeNote, volError, type IvCone, type IvHistory, type IvSurface, type PaidDelivered, type ScreenRow, type ScreenSort, type VolScreen } from './api'
import { expectedMoveHitRate, lastYear, nearestTenor, paidSummary, skippedRuns, termWord } from './volModel'

type Load<X> = { data: X | null; error: string | null }
function useLoad<X>(fn: () => Promise<{ data: X }>, deps: unknown[]): Load<X> {
  const [st, set] = useState<Load<X>>({ data: null, error: null })
  useEffect(() => {
    let alive = true
    set({ data: null, error: null })
    fn().then(r => { if (alive) set({ data: r.data, error: null }) }).catch((e: unknown) => { if (alive) set({ data: null, error: volError(e, 'unavailable') }) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return st
}

const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${fmtNum(v, d)}%`)
const signed = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`)

function Degraded({ what, note }: { what: string; note: string | null }) {
  return <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6 }} data-vol-empty>{what} not stored yet{note ? ` (${note})` : ''} · backfill pending: written nightly by <code>iv_eod</code> once the IV store is deployed; history starts the day the job first runs and backfills from the cached bhavcopies (2019-10 →) on O-T4.</div>
}

function SkewPanel({ hist, surf }: { hist: Load<IvHistory>; surf: Load<IvSurface> }) {
  const rows = hist.data?.ok ? hist.data.rows : []
  const last = rows.length ? rows[rows.length - 1] : null
  const skewPct = percentileOf(lastYear(rows).map(r => r.skew_25d_30), last?.skew_25d_30, 60)
  // m071: like tenors — today's expiry nearest 30 days against the ghost session's expiry nearest 30 days (it compared today's
  // 4-day weekly with a month-old smile of another expiry, so part of the steepness gap was tenor, not regime)
  const near = surf.data?.ok ? nearestTenor(surf.data.expiries, 30) : null
  const ghost = surf.data?.compare ? nearestTenor(surf.data.compare.expiries, 30) : null
  const smile = (e: typeof near) => (e ? [...e.smile].sort((a, b) => a.log_moneyness - b.log_moneyness) : [])
  const todaySmile = smile(near), ghostSmile = smile(ghost)
  const xy = (pts: typeof todaySmile) => pts.map(p => ({ x: p.log_moneyness, y: p.iv, label: `K ${fmtNum(p.strike, 0)}` }))
  return (
    <Panel title="Skew · 25Δ put − call" accent={T.violet} pad={8} badge="context"
      source={sourceOf(hist.data?.as_of ?? null, { source: 'iv_summary_daily', hint: hist.data && !hist.data.ok ? storeNote(hist.data) : hist.error })}
      subtitle={last ? `${signed(last.skew_25d_30)} pts today${skewPct != null ? ` · ${ordinal(skewPct)} percentile of the past year` : ''} · vol points` : undefined}>
      {!rows.length ? <Degraded what="Skew history" note={hist.error ?? storeNote(hist.data)} /> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 3fr) minmax(0, 2fr)', gap: 12 }}>
          <ExpandableChart title="Skew history" height={170}
            legend={<span style={{ color: T.dim }}>violet = 25Δ skew on the 30-day surface · {rows[0].date} → {last!.date}</span>}>
            <InteractiveSeries height={170} ariaLabel="25-delta skew history"
              series={[{ id: 'skew', label: '25Δ skew', color: T.violet, w: 2, format: v => signed(v, 1),
                         points: rows.map(r => ({ t: r.date, v: r.skew_25d_30 })) }]} />
          </ExpandableChart>
          <ExpandableChart title="Smile ≈ 30 d" height={170}
            legend={<span style={{ color: T.dim }}>today{near ? ` (${near.expiry}, ${near.dte} d)` : ''} vs {ghost ? `${surf.data?.compare?.as_of ?? 'a month ago'} (${ghost.expiry}, ${ghost.dte} d, dashed)` : 'a month ago (no like-tenor smile stored)'} · x = log-moneyness</span>}>
            {todaySmile.length >= 3 ? (
              <XYChart height={170} yUnit="%" xLabel="log(K / F)" markX={0} ariaLabel="smile today vs one month ago"
                series={[{ label: 'today', color: T.violet, points: xy(todaySmile), w: 1.6 }, { label: 'ghost', color: T.muted, points: xy(ghostSmile), w: 1.1, dash: '4 3' }]} />
            ) : <div style={{ fontSize: 11, color: T.muted }}>{surf.error ?? storeNote(surf.data) ?? 'the stored surface has too few traded strikes for a smile'}</div>}
          </ExpandableChart>
        </div>
      )}
    </Panel>
  )
}

function TermPanel({ hist, cone }: { hist: Load<IvHistory>; cone: Load<IvCone> }) {
  const rows = hist.data?.ok ? hist.data.rows : []
  const last = rows.length ? rows[rows.length - 1] : null
  const term = cone.data?.ok ? cone.data.term_today.filter(t => t.atm_iv != null) : []
  // the IV cone's 1-year p25–p75 for IV30 as a shaded band on the history (chart plan B10: cone band = area-pair)
  const cone1y = cone.data?.ok ? cone.data.years.find(y => y.years === 1)?.tenors['iv30_cm'] ?? null : null
  const band = cone1y && rows.length
    ? { lo: rows.map(r => ({ t: r.date, v: cone1y.p25 })), hi: rows.map(r => ({ t: r.date, v: cone1y.p75 })) }
    : null
  // M43 honesty carried onto the chart (orders B-VOL.2): sessions whose IV30 was flat-filled from one expiry are marked
  const flatMarks = rows.filter(r => (r.quality_flags ?? '').split(',').includes('cm30_flat')).map(r => ({ t: r.date, kind: 'flat' }))
  return (
    <Panel title="Term structure · ATM IV by expiry" accent={T.amber} pad={8} badge="context"
      source={sourceOf(cone.data?.as_of ?? hist.data?.as_of ?? null, { source: 'iv_expiry_daily', hint: cone.error ?? (cone.data && !cone.data.ok ? storeNote(cone.data) : null) })}
      subtitle={last ? `slope 30→90 ${signed(last.term_slope_30_90)} pts · ${termWord(last.term_slope_30_90)}` : undefined}>
      {!rows.length && !term.length ? <Degraded what="Term structure" note={hist.error ?? storeNote(hist.data)} /> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 3fr)', gap: 12 }}>
          <div>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>today's expiries (stored surface)</div>
            {term.length ? (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }}>
                <thead><tr style={{ color: T.muted, fontSize: 10 }}><th style={{ textAlign: 'left', padding: '3px 6px' }}>EXPIRY</th><th style={{ textAlign: 'right', padding: '3px 6px' }}>DTE</th><th style={{ textAlign: 'right', padding: '3px 6px' }}>ATM IV</th></tr></thead>
                <tbody>{term.map(t => <tr key={t.expiry} style={{ borderTop: `1px solid ${T.border}` }}><td style={{ padding: '3px 6px' }}>{t.expiry}</td><td style={{ padding: '3px 6px', textAlign: 'right' }}>{fmtNum(t.dte, 0)}</td><td style={{ padding: '3px 6px', textAlign: 'right', color: T.text }}>{pct(t.atm_iv, 2)}</td></tr>)}</tbody>
              </table>
            ) : <div style={{ fontSize: 11, color: T.muted }}>no per-expiry rows stored for today</div>}
          </div>
          <ExpandableChart title="Term history" height={170}
            legend={<span style={{ color: T.dim }}>violet = IV30 · amber = IV60 · cyan = IV90 (constant maturity) · dashed = slope 30→90 (left, pts){band ? ' · band = IV30 p25–p75 (1 y cone)' : ''}{flatMarks.length ? ' · ○ = IV30 flat-filled (one expiry 10–60 d)' : ''}</span>}>
            <InteractiveSeries height={170} ariaLabel="term structure history" band={band} markers={flatMarks}
              series={[{ id: 'iv30', label: 'IV30', color: T.violet, w: 2, points: rows.map(r => ({ t: r.date, v: r.iv30_cm })), format: v => `${fmtNum(v, 1)}%` },
                       { id: 'iv60', label: 'IV60', color: T.amber, points: rows.map(r => ({ t: r.date, v: r.iv60_cm })), format: v => `${fmtNum(v, 1)}%` },
                       { id: 'iv90', label: 'IV90', color: T.cyan, points: rows.map(r => ({ t: r.date, v: r.iv90_cm })), format: v => `${fmtNum(v, 1)}%` },
                       { id: 'slope', label: 'slope 30→90', color: T.muted, axis: 'L', dashed: true, points: rows.map(r => ({ t: r.date, v: r.term_slope_30_90 })), format: v => signed(v, 1) }]} />
          </ExpandableChart>
        </div>
      )}
    </Panel>
  )
}

function ConePanel({ cone }: { cone: Load<IvCone> }) {
  const d = cone.data?.ok ? cone.data : null
  const tenors = ['iv30_cm', 'iv60_cm', 'iv90_cm']
  return (
    <Panel title="IV cone · constant-maturity percentiles" accent={T.cyan} pad={8} badge={d?.badge ?? 'context'}
      source={sourceOf(d?.as_of ?? null, { source: 'iv_summary_daily', hint: cone.error ?? storeNote(cone.data) })}
      subtitle="min / 25 / 50 / 75 / max of stored IV by tenor, over 1 / 3 / 5 years; ● = today">
      {!d ? <Degraded what="IV cone" note={cone.error ?? storeNote(cone.data)} /> : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }}>
          <thead><tr style={{ color: T.muted, fontSize: 10 }}>
            <th style={{ textAlign: 'left', padding: '3px 6px' }}>WINDOW</th><th style={{ textAlign: 'left', padding: '3px 6px' }}>TENOR</th>
            {['MIN', 'P25', 'P50', 'P75', 'MAX', 'N'].map(h => <th key={h} style={{ textAlign: 'right', padding: '3px 6px' }}>{h}</th>)}
            <th style={{ textAlign: 'right', padding: '3px 6px' }}>TODAY</th><th style={{ textAlign: 'left', padding: '3px 6px' }}>WHERE</th>
          </tr></thead>
          <tbody>
            {d.years.flatMap(y => tenors.map(t => {
              const c = y.tenors[t]; const today = d.today[t] ?? null
              if (!c) return null
              const pos = today != null && c.max > c.min ? Math.max(0, Math.min(100, ((today - c.min) / (c.max - c.min)) * 100)) : null
              return (
                <tr key={`${y.years}-${t}`} style={{ borderTop: `1px solid ${T.border}` }}>
                  <td style={{ padding: '3px 6px', color: T.muted }}>{y.years} y · {y.sessions} s</td><td style={{ padding: '3px 6px' }}>{t.replace('_cm', '').toUpperCase()}</td>
                  {[c.min, c.p25, c.p50, c.p75, c.max].map((v, i) => <td key={i} style={{ padding: '3px 6px', textAlign: 'right' }}>{pct(v, 1)}</td>)}
                  <td style={{ padding: '3px 6px', textAlign: 'right', color: T.dim }}>{c.n}</td>
                  <td style={{ padding: '3px 6px', textAlign: 'right', color: T.text, fontWeight: 600 }}>{pct(today, 2)}</td>
                  <td style={{ padding: '3px 6px' }}>
                    <span style={{ display: 'inline-block', width: 90, height: 6, background: '#0f141d', position: 'relative', verticalAlign: 'middle' }}>
                      {pos != null && <span style={{ position: 'absolute', left: `calc(${pos}% - 3px)`, top: -1, width: 6, height: 8, background: T.cyan }} />}
                    </span>
                  </td>
                </tr>)
            }))}
          </tbody>
        </table>
      )}
      {d && <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>{d.note}</div>}
    </Panel>
  )
}

function PaidPanel({ hist, symbol }: { hist: Load<IvHistory>; symbol: string }) {
  const rows = hist.data?.ok ? hist.data.rows : []
  const paid = useLoad<PaidDelivered>(() => getIvPaidDelivered(symbol, 12), [symbol])
  const ledger = paid.data?.ok ? paid.data.rows : []
  const skipped = paid.data?.ok ? paid.data.skipped ?? [] : []
  const sum = useMemo(() => paidSummary(ledger), [ledger])
  const hit = useMemo(() => expectedMoveHitRate(rows, 60), [rows])
  const note = paid.error ?? storeNote(paid.data)
  return (
    <Panel title={`IV paid vs vol delivered · ${ledger.length ? `last ${ledger.length}` : 'the'} NSE monthly expiries`} accent={T.violet} pad={8} badge="context"
      source={sourceOf(paid.data?.as_of ?? hist.data?.as_of ?? null, { source: 'iv_expiry_daily + NSE OHLC', hint: note })}
      subtitle={sum.closed ? `NSE monthly expiries · ATM IV at ≈ 30 days to expiry vs the realised vol (close-to-close, zero-mean) from that entry to the expiry close · mean ${signed(sum.mean)} pts over ${sum.closed} closed months · ${sum.paid_above} of ${sum.closed} paid above` : undefined}>
      {!ledger.length ? <Degraded what="The monthly ledger" note={note} /> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 3fr) minmax(220px, 1fr)', gap: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }} data-paid-ledger>
            <thead><tr style={{ color: T.muted, fontSize: 10 }}>
              {['MONTHLY EXPIRY', 'ENTRY (DTE) → EXPIRY', 'IV PAID', 'RV DELIVERED (CC)', 'PAID − DELIVERED'].map((h, i) => <th key={h} style={{ textAlign: i < 2 ? 'left' : 'right', padding: '3px 6px' }}>{h}</th>)}
            </tr></thead>
            <tbody>{ledger.map(l => (
              <tr key={l.expiry} style={{ borderTop: `1px solid ${T.border}` }}>
                <td style={{ padding: '3px 6px' }}>{l.expiry}</td><td style={{ padding: '3px 6px', color: T.muted }}>{l.entry} ({fmtNum(l.entry_dte, 0)} d) → {l.open ? 'open' : `${fmtNum(l.sessions, 0)} s`}</td>
                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{pct(l.iv_paid, 2)}</td>
                <td style={{ padding: '3px 6px', textAlign: 'right' }} title={l.open ? 'still open: nothing delivered yet' : `demeaned σ ${pct(l.rv_demeaned, 2)} · Yang-Zhang ${pct(l.rv_yz, 2)} over the same sessions`}>{l.open ? 'open' : pct(l.rv_delivered, 2)}</td>
                <td style={{ padding: '3px 6px', textAlign: 'right', color: T.text }}>{l.paid_minus_delivered == null ? '—' : `${signed(l.paid_minus_delivered)} pts`}</td>
              </tr>))}</tbody>
          </table>
          <div style={{ border: `1px solid ${T.border}`, padding: '8px 10px', fontFamily: T.mono, fontSize: 11 }}>
            <div style={{ fontSize: 9, letterSpacing: 1.2, color: T.muted, textTransform: 'uppercase' }}>Expected-move hit-rate · 60 sessions</div>
            <div style={{ fontSize: 18, fontWeight: 600, color: T.text, marginTop: 3 }}>{hit.share == null ? '—' : `${fmtNum(hit.share, 0)}%`}</div>
            <div style={{ fontSize: 10, color: T.muted, lineHeight: 1.5 }}>{hit.inside} of {hit.sessions} sessions closed inside ±(IV30 ÷ √252) · a lognormal 1σ band holds {fmtNum(hit.reference, 0)}% by construction</div>
            <div style={{ marginTop: 4 }}><BadgeChip badge="arithmetic" note="a count on stored rows; the reference is the normal distribution's, not a target." /></div>
          </div>
        </div>
      )}
      {skipped.length > 0 && <div style={{ fontSize: 11, color: T.amber, marginTop: 6 }} data-paid-skipped>
        Not in the ledger: {skippedRuns(skipped).join(' · ')}</div>}
      {ledger.length > 0 && <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>{paid.data?.definition ?? ''} · a description of past months; describes, does not predict</div>}
    </Panel>
  )
}

const SORTS: { id: ScreenSort; label: string }[] = [
  { id: 'iv_pctile', label: 'IV PCTILE' }, { id: 'iv_rank', label: 'IV RANK' }, { id: 'iv_minus_rv', label: 'IV − RV' }, { id: 'term_slope', label: 'TERM' }, { id: 'skew', label: 'SKEW' },
]

export function VolScreener({ onPick }: { onPick?: (sym: string) => void }) {
  const [sort, setSort] = useState<ScreenSort>('iv_pctile')
  const [within, setWithin] = useState<number | null>(null)
  const [q, setQ] = useState('')
  const [banOnly, setBanOnly] = useState(false)
  const scr = useLoad<VolScreen>(() => getVolScreen(sort, within), [sort, within])
  const d = scr.data
  const rows = useMemo(() => (d?.ok ? d.rows : []).filter(r => (!q || r.symbol.includes(q.toUpperCase())) && (!banOnly || r.ban)), [d, q, banOnly])
  const banDay = d?.ban_date ? new Date(`${d.ban_date}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : null
  const cols = useMemo<Column<ScreenRow>[]>(() => [
    { key: 'symbol', label: 'Underlying', sort: r => r.symbol, render: r => <><TickerLink symbol={r.symbol} />{r.ban && <span style={{ color: T.red, fontSize: 9, marginLeft: 4 }} title={`in NSE's F&O ban${banDay ? ` for ${banDay}` : ''} (${d?.ban_source ?? 'NSE'}): closing trades only`}>BAN</span>}</> },
    { key: 'spot', label: 'Spot', align: 'right', sort: r => r.spot ?? -1, render: r => fmtNum(r.spot, 2) },
    { key: 'iv30', label: 'IV30', align: 'right', sort: r => r.iv30_cm ?? -1, title: d?.definitions?.iv30_cm,
      render: r => (r.iv30_flat ? <span title="flat from the one expiry inside 10–60 days (no 30-day bracket: the next series had too few traded strikes)">≈{pct(r.iv30_cm, 1)}</span> : pct(r.iv30_cm, 1)) },
    { key: 'rank', label: 'IV rank', align: 'right', sort: r => r.iv_rank_252 ?? -1, title: d?.definitions?.iv_rank_252,
      render: r => (r.iv_rank_252 == null && r.iv30_cm != null ? <span style={{ color: T.dim }} title="a rank needs at least 20 stored sessions (a new F&O name)">new</span> : fmtNum(r.iv_rank_252, 0)) },
    { key: 'pctile', label: 'IV pctile', align: 'right', sort: r => r.iv_pctile_252 ?? -1, title: d?.definitions?.iv_pctile_252,
      render: r => (r.iv_pctile_252 == null && r.iv30_cm != null ? <span style={{ color: T.dim }} title="a percentile needs at least 20 stored sessions">new</span> : fmtNum(r.iv_pctile_252, 0)) },
    { key: 'rv', label: 'RV20 (cc)', align: 'right', sort: r => r.rv20_cc ?? -1, title: d?.definitions?.rv20_cc, render: r => pct(r.rv20_cc, 1) },
    { key: 'spread', label: 'IV − RV (cc)', align: 'right', sort: r => r.iv_minus_rv20 ?? -99, title: d?.definitions?.iv_minus_rv20, render: r => (r.iv_minus_rv20 == null ? '—' : `${signed(r.iv_minus_rv20, 1)}`) },
    { key: 'rvyz', label: 'RV20 (YZ)', align: 'right', sort: r => r.rv20_yz ?? -1, title: d?.definitions?.rv20_yz, render: r => <span style={{ color: T.muted }}>{pct(r.rv20_yz, 1)}</span> },
    { key: 'spreadyz', label: 'IV − RV (YZ)', align: 'right', sort: r => r.iv_minus_rv20_yz ?? -99, title: d?.definitions?.iv_minus_rv20_yz,
      render: r => <span style={{ color: T.muted }}>{r.iv_minus_rv20_yz == null ? '—' : signed(r.iv_minus_rv20_yz, 1)}</span> },
    { key: 'term', label: 'Term 30→90', align: 'right', sort: r => r.term_slope_30_90 ?? -99, title: `${d?.definitions?.term_slope_30_90 ?? ''} "—" for a stock: its third monthly is too thin for an ATM IV, so 90 days is not bracketed (see near→next).`, render: r => (r.term_slope_30_90 == null ? '—' : signed(r.term_slope_30_90, 1)) },
    { key: 'termnn', label: 'Term near→next', align: 'right', sort: r => r.term_near_next ?? -99, title: d?.definitions?.term_near_next,
      render: r => (r.term_near_next == null ? '—' : <span title={`${pct(r.near_atm_iv, 1)} at ${fmtNum(r.near_dte, 0)} d → ${pct(r.next_atm_iv, 1)} at ${fmtNum(r.next_dte, 0)} d`}>{signed(r.term_near_next, 1)} <span style={{ color: T.dim, fontSize: 10 }}>{fmtNum(r.near_dte, 0)}→{fmtNum(r.next_dte, 0)}d</span></span>) },
    { key: 'skew', label: '25Δ skew', align: 'right', sort: r => r.skew_25d_30 ?? -99, title: d?.definitions?.skew_25d_30, render: r => (r.skew_25d_30 == null ? '—' : signed(r.skew_25d_30, 1)) },
    { key: 'results', label: 'Next results', sort: r => r.next_results ?? 'zz', render: r => <span style={{ color: T.muted }}>{r.next_results ?? '—'}{r.results_in_days != null ? ` · ${r.results_in_days}d` : ''}</span> },
    { key: 'mwpl', label: '% MWPL', align: 'right', sort: r => r.mwpl_pct ?? -1, title: 'futures-equivalent open interest as a share of the market-wide position limit (NSE combined-OI files; the ban starts above 95 % and ends below 80 %) · context',
      render: r => (r.mwpl_pct == null ? '—' : <span title={r.mwpl_date ? `NSE combined OI of ${r.mwpl_date}` : undefined}>{pct(r.mwpl_pct, 0)}</span>) },
  ], [d, banDay])
  return (
    <Panel title="VOL screener · every F&O underlying" accent={T.cyan} pad={0} badge="context"
      source={sourceOf(d?.as_of ?? null, { source: 'iv_summary_daily', hint: scr.error ?? storeNote(d) })}
      subtitle={d?.ok ? `${rows.length} of ${d.n} names · sorted by ${sort.replace('_', ' ')} · click a column to re-sort · hover the table for ⤓ CSV` : undefined}
      right={<span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {SORTS.map(s => <Chip key={s.id} color={T.cyan} active={sort === s.id} onClick={() => setSort(s.id)}>{s.label}</Chip>)}
        <Chip color={T.amber} active={within === 10} onClick={() => setWithin(w => (w === 10 ? null : 10))} title="only names reporting within 10 days">RESULTS ≤ 10D</Chip>
        <Chip color={T.red} active={banOnly} onClick={() => setBanOnly(b => !b)} title={`only names in NSE's F&O ban${banDay ? ` for ${banDay}` : ''}`}>BAN{banDay ? ` · ${banDay}` : ''}</Chip>
        <input value={q} onChange={e => setQ(e.target.value)} placeholder="filter…" aria-label="screener filter"
          style={{ background: T.panel, border: `1px solid ${T.border}`, color: T.text, fontFamily: T.mono, fontSize: 11, padding: '3px 6px', width: 90, outline: 'none', textTransform: 'uppercase' }} />
      </span>}>
      {d && !d.ok && <div style={{ padding: 12 }}><Degraded what="The screener" note={storeNote(d)} /></div>}
      {scr.error && <div style={{ padding: 12, fontSize: 11, color: T.amber }}>Unavailable: {scr.error}</div>}
      {d?.ok && <DataTable columns={cols} rows={rows} rowKey={r => r.symbol} dense maxHeight={520} exportName="VOL_screen" onRowClick={onPick ? r => onPick(r.symbol) : undefined}
        empty={<div style={{ padding: 12, fontSize: 11, color: T.muted }}>No rows match.</div>} />}
      {d?.ok && <div style={{ padding: '6px 12px', fontSize: 10, color: T.dim }}>{d.note} · precedent: {d.precedent}</div>}
    </Panel>
  )
}

export function VolView({ symbol, onPick }: { symbol: string; onPick?: (sym: string) => void }) {
  const hist = useLoad<IvHistory>(() => getIvHistory(symbol, 750), [symbol])
  const surf = useLoad<IvSurface>(() => getIvSurface(symbol, '1m'), [symbol])
  const cone = useLoad<IvCone>(() => getIvCone(symbol), [symbol])
  return (
    <div data-derv-view="vol" style={{ display: 'grid', gap: 12 }}>
      <SkewPanel hist={hist} surf={surf} />
      <TermPanel hist={hist} cone={cone} />
      <ConePanel cone={cone} />
      <PaidPanel hist={hist} symbol={symbol} />
      <VolScreener onPick={onPick} />
      <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
        Sources: the IV store (iv_summary_daily, iv_expiry_daily, iv_surface_daily) rebuilt nightly from the stored NSE F&O bhavcopies (Black-76 on the
        put–call-parity forward; r from the dated rate curve; T = calendar time to 15:30 IST on expiry ÷ 365, the same on OMON and OSTR); realised vol from NSE&apos;s
        daily index file and the equity bhavcopy (close-to-close is the estimator of record for IV − RV; Parkinson and Yang-Zhang drop a session whose high / low
        is a bad print); BAN from NSE&apos;s securities-in-ban list; % MWPL from NSE&apos;s combined-OI files. The India VIX level is on the DESK sub-view only. Every panel
        describes where volatility is and was; none forecasts, none feeds the Decision Desk or a ticket.
      </div>
    </div>
  )
}
