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
 */
import { useEffect, useMemo, useState } from 'react'
import { apiError } from '@/lib/errors'
import { BadgeChip, Chip, DataTable, Panel, T, TickerLink, fmtNum, ordinal, sourceOf, type Column } from '@/components/terminal'
import { percentileOf } from '@/components/terminal/source'
import { LineChart } from './charts'
import { getIvCone, getIvHistory, getIvSurface, getVolScreen, storeNote, type IvCone, type IvHistory, type IvSurface, type ScreenRow, type ScreenSort, type VolScreen } from './api'
import { expectedMoveHitRate, ivPaidLedger, termWord } from './volModel'

type Load<X> = { data: X | null; error: string | null }
function useLoad<X>(fn: () => Promise<{ data: X }>, deps: unknown[]): Load<X> {
  const [st, set] = useState<Load<X>>({ data: null, error: null })
  useEffect(() => {
    let alive = true
    set({ data: null, error: null })
    fn().then(r => { if (alive) set({ data: r.data, error: null }) }).catch((e: unknown) => { if (alive) set({ data: null, error: apiError(e, 'unavailable') }) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return st
}

const pct = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${fmtNum(v, d)}%`)
const signed = (v: number | null | undefined, d = 2) => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`)

function Degraded({ what, note }: { what: string; note: string | null }) {
  return <div style={{ fontSize: 11, color: T.muted, lineHeight: 1.6 }}>{what} not stored yet{note ? ` (${note})` : ''}: written nightly by <code>iv_eod</code> once the IV store is deployed; histories begin the day the job starts and backfill from the cached files on O-T4.</div>
}

function SkewPanel({ hist, surf }: { hist: Load<IvHistory>; surf: Load<IvSurface> }) {
  const rows = hist.data?.ok ? hist.data.rows : []
  const last = rows.length ? rows[rows.length - 1] : null
  const skewPct = percentileOf(rows.map(r => r.skew_25d_30), last?.skew_25d_30, 60)
  const near = surf.data?.ok ? (surf.data.expiries.find(e => e.near) ?? surf.data.expiries[0]) : null
  const ghost = surf.data?.compare?.expiries?.[0] ?? null
  const smile = (e: typeof near) => (e ? [...e.smile].sort((a, b) => a.log_moneyness - b.log_moneyness) : [])
  const todaySmile = smile(near), ghostSmile = smile(ghost)
  const xs = [...new Set([...todaySmile, ...ghostSmile].map(p => p.log_moneyness))].sort((a, b) => a - b)
  const at = (pts: typeof todaySmile) => xs.map(x => pts.find(p => Math.abs(p.log_moneyness - x) < 1e-9)?.iv ?? null)
  return (
    <Panel title="Skew · 25Δ put − call" accent={T.violet} pad={8} badge="context"
      source={sourceOf(hist.data?.as_of ?? null, { source: 'iv_summary_daily', hint: hist.data && !hist.data.ok ? storeNote(hist.data) : hist.error })}
      subtitle={last ? `${signed(last.skew_25d_30)} pts today${skewPct != null ? ` · ${ordinal(skewPct)} percentile of the past year` : ''} · vol points` : undefined}>
      {!rows.length ? <Degraded what="Skew history" note={hist.error ?? storeNote(hist.data)} /> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 3fr) minmax(0, 2fr)', gap: 12 }}>
          <div>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>violet = 25Δ skew on the 30-day surface · {rows[0].date} → {last!.date}</div>
            <LineChart dates={rows.map(r => r.date)} height={170} zero lUnit="" ariaLabel="25-delta skew history"
              series={[{ label: '25Δ skew', color: T.violet, values: rows.map(r => r.skew_25d_30), w: 1.5 }]} />
          </div>
          <div>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>smile today{near ? ` (${near.expiry})` : ''} vs {ghost ? `${surf.data?.compare?.as_of ?? 'a month ago'} (dashed)` : 'a month ago'} · x = log-moneyness</div>
            {todaySmile.length >= 3 ? (
              <LineChart dates={xs.map(x => x.toFixed(4))} height={170} lUnit="%" ariaLabel="smile today vs one month ago"
                series={[{ label: 'today', color: T.violet, values: at(todaySmile), w: 1.6 }, { label: 'ghost', color: T.muted, values: at(ghostSmile), w: 1.1, dash: '4 3' }]} />
            ) : <div style={{ fontSize: 11, color: T.muted }}>{surf.error ?? storeNote(surf.data) ?? 'the stored surface has too few traded strikes for a smile'}</div>}
          </div>
        </div>
      )}
    </Panel>
  )
}

function TermPanel({ hist, cone }: { hist: Load<IvHistory>; cone: Load<IvCone> }) {
  const rows = hist.data?.ok ? hist.data.rows : []
  const last = rows.length ? rows[rows.length - 1] : null
  const term = cone.data?.ok ? cone.data.term_today.filter(t => t.atm_iv != null) : []
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
                <thead><tr style={{ color: T.muted, fontSize: 9.5 }}><th style={{ textAlign: 'left', padding: '3px 6px' }}>EXPIRY</th><th style={{ textAlign: 'right', padding: '3px 6px' }}>DTE</th><th style={{ textAlign: 'right', padding: '3px 6px' }}>ATM IV</th></tr></thead>
                <tbody>{term.map(t => <tr key={t.expiry} style={{ borderTop: `1px solid ${T.border}` }}><td style={{ padding: '3px 6px' }}>{t.expiry}</td><td style={{ padding: '3px 6px', textAlign: 'right' }}>{fmtNum(t.dte, 0)}</td><td style={{ padding: '3px 6px', textAlign: 'right', color: T.text }}>{pct(t.atm_iv, 2)}</td></tr>)}</tbody>
              </table>
            ) : <div style={{ fontSize: 11, color: T.muted }}>no per-expiry rows stored for today</div>}
          </div>
          <div>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>violet = IV30 · amber = IV60 · cyan = IV90 (constant maturity) · dashed = slope 30→90 (right, pts)</div>
            <LineChart dates={rows.map(r => r.date)} height={170} lUnit="%" ariaLabel="term structure history"
              series={[{ label: 'IV30', color: T.violet, values: rows.map(r => r.iv30_cm), w: 1.4 }, { label: 'IV60', color: T.amber, values: rows.map(r => r.iv60_cm), w: 1 },
                       { label: 'IV90', color: T.cyan, values: rows.map(r => r.iv90_cm), w: 1 }, { label: 'slope', color: T.muted, values: rows.map(r => r.term_slope_30_90), axis: 'R', w: 1, dash: '3 3' }]} />
          </div>
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
          <thead><tr style={{ color: T.muted, fontSize: 9.5 }}>
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

function PaidPanel({ hist }: { hist: Load<IvHistory> }) {
  const rows = hist.data?.ok ? hist.data.rows : []
  const ledger = useMemo(() => ivPaidLedger(rows, 12), [rows])
  const hit = useMemo(() => expectedMoveHitRate(rows, 60), [rows])
  const closed = ledger.filter(l => l.paid_minus_delivered != null)
  const avg = closed.length ? closed.reduce((s, l) => s + (l.paid_minus_delivered ?? 0), 0) / closed.length : null
  return (
    <Panel title="IV paid vs vol delivered · last 12 monthly expiries" accent={T.violet} pad={8} badge="context"
      source={sourceOf(hist.data?.as_of ?? null, { source: 'iv_summary_daily', hint: hist.error ?? storeNote(hist.data) })}
      subtitle={closed.length ? `monthly ATM IV at the start of each series vs the 20-day Yang-Zhang realised vol at its end · mean difference ${signed(avg)} pts over ${closed.length} closed months` : undefined}>
      {!rows.length ? <Degraded what="The monthly ledger" note={hist.error ?? storeNote(hist.data)} /> : (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 3fr) minmax(220px, 1fr)', gap: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }}>
            <thead><tr style={{ color: T.muted, fontSize: 9.5 }}>
              {['MONTHLY EXPIRY', 'FROM → TO', 'IV PAID', 'RV DELIVERED', 'PAID − DELIVERED'].map((h, i) => <th key={h} style={{ textAlign: i < 2 ? 'left' : 'right', padding: '3px 6px' }}>{h}</th>)}
            </tr></thead>
            <tbody>{ledger.map(l => (
              <tr key={l.expiry} style={{ borderTop: `1px solid ${T.border}` }}>
                <td style={{ padding: '3px 6px' }}>{l.expiry}</td><td style={{ padding: '3px 6px', color: T.muted }}>{l.from} → {l.to} ({l.sessions} s)</td>
                <td style={{ padding: '3px 6px', textAlign: 'right' }}>{pct(l.iv_paid, 2)}</td><td style={{ padding: '3px 6px', textAlign: 'right' }}>{l.rv_delivered == null ? 'open' : pct(l.rv_delivered, 2)}</td>
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
      {rows.length > 0 && <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>a description of past months; describes, does not predict</div>}
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
  const cols = useMemo<Column<ScreenRow>[]>(() => [
    { key: 'symbol', label: 'Underlying', sort: r => r.symbol, render: r => <><TickerLink symbol={r.symbol} />{r.ban && <span style={{ color: T.red, fontSize: 9, marginLeft: 4 }}>BAN</span>}</> },
    { key: 'spot', label: 'Spot', align: 'right', sort: r => r.spot ?? -1, render: r => fmtNum(r.spot, 2) },
    { key: 'iv30', label: 'IV30', align: 'right', sort: r => r.iv30_cm ?? -1, title: d?.definitions?.iv30_cm, render: r => pct(r.iv30_cm, 1) },
    { key: 'rank', label: 'IV rank', align: 'right', sort: r => r.iv_rank_252 ?? -1, title: d?.definitions?.iv_rank_252, render: r => fmtNum(r.iv_rank_252, 0) },
    { key: 'pctile', label: 'IV pctile', align: 'right', sort: r => r.iv_pctile_252 ?? -1, title: d?.definitions?.iv_pctile_252, render: r => fmtNum(r.iv_pctile_252, 0) },
    { key: 'rv', label: 'RV20 (YZ)', align: 'right', sort: r => r.rv20_yz ?? -1, render: r => pct(r.rv20_yz, 1) },
    { key: 'spread', label: 'IV − RV', align: 'right', sort: r => r.iv_minus_rv20 ?? -99, title: d?.definitions?.iv_minus_rv20, render: r => (r.iv_minus_rv20 == null ? '—' : `${signed(r.iv_minus_rv20, 1)}`) },
    { key: 'term', label: 'Term 30→90', align: 'right', sort: r => r.term_slope_30_90 ?? -99, title: d?.definitions?.term_slope_30_90, render: r => (r.term_slope_30_90 == null ? '—' : signed(r.term_slope_30_90, 1)) },
    { key: 'skew', label: '25Δ skew', align: 'right', sort: r => r.skew_25d_30 ?? -99, title: d?.definitions?.skew_25d_30, render: r => (r.skew_25d_30 == null ? '—' : signed(r.skew_25d_30, 1)) },
    { key: 'results', label: 'Next results', sort: r => r.next_results ?? 'zz', render: r => <span style={{ color: T.muted }}>{r.next_results ?? '—'}{r.results_in_days != null ? ` · ${r.results_in_days}d` : ''}</span> },
    { key: 'mwpl', label: '% MWPL', align: 'right', sort: r => r.mwpl_pct ?? -1, title: 'open interest as a share of the market-wide position limit (ban at 95 %)', render: r => (r.mwpl_pct == null ? '—' : pct(r.mwpl_pct, 0)) },
  ], [d])
  return (
    <Panel title="VOL screener · every F&O underlying" accent={T.cyan} pad={0} badge="context"
      source={sourceOf(d?.as_of ?? null, { source: 'iv_summary_daily', hint: scr.error ?? storeNote(d) })}
      subtitle={d?.ok ? `${rows.length} of ${d.n} names · sorted by ${sort.replace('_', ' ')} · click a column to re-sort · hover the table for ⤓ CSV` : undefined}
      right={<span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
        {SORTS.map(s => <Chip key={s.id} color={T.cyan} active={sort === s.id} onClick={() => setSort(s.id)}>{s.label}</Chip>)}
        <Chip color={T.amber} active={within === 10} onClick={() => setWithin(w => (w === 10 ? null : 10))} title="only names reporting within 10 days">RESULTS ≤ 10D</Chip>
        <Chip color={T.red} active={banOnly} onClick={() => setBanOnly(b => !b)} title="only names in the F&O ban">BAN</Chip>
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
      <PaidPanel hist={hist} />
      <VolScreener onPick={onPick} />
      <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
        Sources: the IV store (iv_summary_daily, iv_expiry_daily, iv_surface_daily) rebuilt nightly from the stored NSE F&O bhavcopies (Black-76 on the
        put–call-parity forward; r from the dated rate curve; T = calendar days / 365 at the 15:30 close); realised vol from NSE's daily index file. The India VIX
        level is on the DESK sub-view only. Every panel describes where volatility is and was; none forecasts, none feeds the Decision Desk or a ticket.
      </div>
    </div>
  )
}
