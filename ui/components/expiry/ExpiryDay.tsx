'use client'

/**
 * OMON › XPRY — the expiry-day cockpit (reports/terminal_v2/PLAN.md 2.4; FINAL ROUND wave B, B-XPRY F-08; precedent
 * Opstra / Sensibull expiry-day tools, ORATS implied-vs-realised). On an expiry day it follows the expiring series
 * through the session, all from the stored 2-minute tape:
 *  - OI unwind by strike (the change since the first snapshot, both sides) and the totals;
 *  - the max-pain drift and the intraday PCR path against the forward;
 *  - the straddle tracker: today's straddle at the opening ATM strike (priced) against the historical expiry-day
 *    decay curve (median and middle half of past expiry days, from Breeze 1-minute replays);
 *  - pin-risk strikes: the largest open interest within ±1 % of spot.
 * Every day: the next expiry, the historical curve (with an honest as-of: the latest REPLAYED expiry, and a note when
 * stored expiries are not replayed yet) and the implied-vs-realised scorecard (stored numbers, never re-scored).
 * Charts are on the interactive kit (wheel zoom · drag pan · crosshair · expand · PNG; charts/PLAN.md §4).
 * `context` (OI, max pain, PCR, pin risk, curve) / `arithmetic` (scorecard). No signal, no score; describes, does not predict.
 */
import { useEffect, useState } from 'react'
import { Chip, DataTable, Notice, Panel, Stat, T, Tabs, fmtNum, sourceOf, type Column } from '@/components/terminal'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { useActiveSymbol } from '@/lib/activeSymbol'
import { getExpiryDay, storeReason, tapeError } from './api'
import { Replay } from './Replay'
import { CALL_COLOR, ChartWithNotes, PUT_COLOR, SessionChart, StrikeBars } from './charts'
import {
  DESCRIBES, TAPE_INDICES, decayVsCurve, expiryWords, fmtOi, fmtSignedOi, minuteLabel, minuteOf, scoreRead, sentence, sinceLabel, tapeSource, unwindRead, weekday,
  type ExpiryDay as Xpry, type PinRow, type ScoreRow,
} from './tapeModel'

/** The curve payload's honesty fields (routers/expiry.py adds them; tapeModel's shape stays untouched). */
type CurveX = Xpry['curve'] & { as_of?: string | null; replay_pending?: string | null }

const note = (color: string = T.dim) => ({ fontSize: 10, color, marginTop: 4, flex: 'none' } as const)

export function ExpiryDay({ symbol: symbolProp }: { symbol?: string }) {
  const [active, setActive] = useActiveSymbol()
  const initial = (symbolProp ?? active?.symbol ?? 'NIFTY').toUpperCase()
  const [symbol, setSymbol] = useState(initial)
  useEffect(() => { if (symbolProp) setSymbol(symbolProp.toUpperCase()) }, [symbolProp])
  useEffect(() => { if (!symbolProp && active?.symbol && active.symbol !== symbol) setSymbol(active.symbol.toUpperCase()) },
    [active?.symbol])  // eslint-disable-line react-hooks/exhaustive-deps
  // E-REPLAY (F-17): the practice simulator mounts as a second tab; the cockpit stays the default view.
  const [view, setView] = useState<'cockpit' | 'replay'>('cockpit')
  const [d, setD] = useState<Xpry | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    let alive = true
    const load = () => getExpiryDay(symbol).then(r => { if (alive) { setD(r.data); setErr(null); setNow(Date.now()) } })
      .catch((e: unknown) => { if (alive) setErr(tapeError(e)) })
    setD(null); load()
    const iv = setInterval(() => { if (!document.hidden) load() }, 60_000)
    return () => { alive = false; clearInterval(iv) }
  }, [symbol])
  const pick = (s: string) => { setSymbol(s); setActive({ symbol: s }) }
  const choices = Array.from(new Set([...TAPE_INDICES, symbol]))
  const live = d?.live
  const unwind = live?.unwind ?? []
  const totals = unwindRead(unwind)
  const lotless = (v: number) => fmtSignedOi(v, null, false)
  const since = sinceLabel(live?.first)
  const curve = d?.curve as CurveX | undefined
  const decay = live?.decay ?? []
  const reason = storeReason(d)
  const scoreCols: Column<ScoreRow>[] = [
    { key: 'e', label: 'EXPIRY', render: r => r.expiry, sort: r => r.expiry },
    { key: 'p', label: 'PRICED ON', render: r => `${r.priced_on} (${r.dte}d)` },
    { key: 'k', label: 'STRIKE', align: 'right', render: r => fmtNum(r.strike, 0) },
    { key: 's', label: 'STRADDLE ₹', align: 'right', render: r => fmtNum(r.straddle, 2) },
    { key: 'i', label: 'PRICED MOVE', align: 'right', render: r => r.implied_move_pct == null ? '—' : `±${r.implied_move_pct.toFixed(2)} %`, sort: r => r.implied_move_pct },
    { key: 'r', label: 'REALISED', align: 'right', render: r => `${r.realised_move_pct >= 0 ? '+' : '−'}${Math.abs(r.realised_move_pct).toFixed(2)} %`, sort: r => r.realised_move_pct },
    { key: 'x', label: 'REALISED ÷ PRICED', align: 'right', render: r => fmtNum(r.ratio, 2), sort: r => r.ratio },
    { key: 'b', label: 'BEYOND?', align: 'center', render: r => r.exceeded == null ? '—' : r.exceeded ? 'beyond' : 'inside' },
    { key: 'n', label: 'RV20 MOVE', align: 'right', render: r => r.naive_move_pct == null ? '—' : `±${r.naive_move_pct.toFixed(2)} %` },
  ]
  const pinCols: Column<PinRow>[] = [
    { key: 'k', label: 'STRIKE', render: r => <b>{r.strike.toLocaleString('en-IN')}</b> },
    { key: 'd', label: 'FROM SPOT', align: 'right', render: r => `${r.distance_pts >= 0 ? '+' : '−'}${Math.abs(r.distance_pts).toFixed(1)} (${r.distance_pct >= 0 ? '+' : '−'}${Math.abs(r.distance_pct).toFixed(2)} %)` },
    { key: 'c', label: 'CALL OI', align: 'right', render: r => fmtOi(r.ce_oi, null, false) },
    { key: 'p', label: 'PUT OI', align: 'right', render: r => fmtOi(r.pe_oi, null, false) },
    { key: 't', label: 'TOTAL', align: 'right', render: r => fmtOi(r.total_oi, null, false) },
  ]
  const curvePts = curve?.points ?? []
  const decayX = decay.map(p => p.minute)
  const path = live?.path ?? []
  const pathX = path.map(p => minuteOf(p.ist) ?? 0)
  const scoreSrc = sourceOf(d?.scorecard.rows[0]?.expiry ?? null, { source: 'iv_surface_daily + NSE index close', maxAgeDays: 10 })
  const curveAsOf = curve?.as_of ?? curve?.expiries?.[curve.expiries.length - 1] ?? null
  const curveSrc = curve && curve.n ? sourceOf(curveAsOf, { source: 'Breeze 1-minute replay', maxAgeDays: 10,
      hint: curve.replay_pending ?? 'the latest replayed expiry; the replay is an after-close job (O-T16)' })
    : { state: 'offline' as const, source: 'Breeze 1-minute replay', asOf: null, hint: curve?.note ?? 'no replay stored yet' }
  const nextWords = !d || d.is_expiry_day || !d.next_expiry ? null
    : `On ${weekday(d.next_expiry)} ${d.next_expiry} this page follows the expiring series live through the session: ` +
      'OI unwind by strike, the max-pain drift, the straddle tracker against the curve below, the intraday PCR path and the ' +
      'pin-risk strikes, from the stored 2-minute tape (09:15–15:30 IST).'
  return (
    <div data-xpry={symbol}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 10, color: T.muted, letterSpacing: 1 }}>XPRY · EXPIRY DAY</span>
        {!symbolProp && choices.map(s => <Chip key={s} active={symbol === s} onClick={() => pick(s)}>{s}</Chip>)}
        {symbolProp && <b style={{ fontSize: 11, color: T.amber }}>{symbol}</b>}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: T.dim }}>{d?.precedent}</span>
      </div>
      <div style={{ marginBottom: 10 }}>
        <Tabs items={[{ id: 'cockpit' as const, label: 'EXPIRY DAY' }, { id: 'replay' as const, label: 'REPLAY · PRACTICE' }]}
          active={view} onChange={setView} />
      </div>
      {view === 'replay' && <Replay symbol={symbol} />}
      {view === 'cockpit' && <>
      {err && <div style={{ marginBottom: 8 }}><Notice color={T.amber}>Expiry view unavailable: {err}</Notice></div>}
      {!err && reason && <div style={{ marginBottom: 8 }}><Notice color={T.amber}>Expiry view unavailable: {reason}</Notice></div>}
      {d && <div style={{ fontSize: 12, color: T.text, marginBottom: 4 }} data-xpry-words>{expiryWords(d)}</div>}
      {nextWords && <div style={{ fontSize: 11, color: T.muted, marginBottom: 10 }} data-xpry-next>{nextWords}</div>}

      {d?.is_expiry_day && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
          <ExpandableChart title="OI unwind by strike" accent={T.cyan} source={tapeSource(d.chip, now)} badges={[{ label: 'context' }]}
            legend={live?.snapshots ? `${live.first} → ${live.last} IST · ${live.snapshots} snapshots` : 'no snapshot yet'}
            height={Math.max(300, unwind.length * 13 + 118)}>
            {({ height: boxH }) => unwind.length ? (
              <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, minWidth: 0 }}>
                {since.late && <div style={{ fontSize: 10, color: T.amber, marginBottom: 4, flex: 'none' }}>Change {since.text}.</div>}
                <div style={{ display: 'flex', gap: 14, fontFamily: T.mono, fontSize: 11, marginBottom: 6, flex: 'none' }}>
                  <span>calls {fmtOi(totals.ceNow, null, false)} <span style={{ color: T.dim }}>({totals.cePct == null ? '—' : `${totals.cePct >= 0 ? '+' : '−'}${Math.abs(totals.cePct).toFixed(1)} %`})</span></span>
                  <span>puts {fmtOi(totals.peNow, null, false)} <span style={{ color: T.dim }}>({totals.pePct == null ? '—' : `${totals.pePct >= 0 ? '+' : '−'}${Math.abs(totals.pePct).toFixed(1)} %`})</span></span>
                  <span style={{ color: T.dim }}>shares, strikes near spot</span>
                </div>
                <div style={{ flex: 1, minHeight: 0 }}>
                  <StrikeBars strikes={unwind.map(r => r.strike)} ce={unwind.map(r => r.ce_chg_open)} pe={unwind.map(r => r.pe_chg_open)}
                    mark={live?.spot ?? null} fmt={lotless} height={Math.max(160, boxH - (since.late ? 96 : 78))}
                    ariaLabel="OI change since the first snapshot by strike" />
                </div>
                <div style={note()}><span style={{ color: CALL_COLOR }}>calls</span> · <span style={{ color: PUT_COLOR }}>puts</span> · faded = OI leaving · dashed = spot. {sentence(DESCRIBES)}.</div>
              </div>
            ) : <div style={{ fontSize: 11, color: T.muted }}>The tape has not stored the expiring series yet today (09:15–15:30 IST, every 2 minutes when the budget allows).</div>}
          </ExpandableChart>
          <ExpandableChart title="Max pain · PCR through the day" accent={T.violet} source={tapeSource(d.chip, now)} badges={[{ label: 'context' }]}
            legend={<span><span style={{ color: T.text }}>— forward</span> · <span style={{ color: T.violet }}>— max pain</span> (L) · ┄ PCR (R)</span>}
            height={Math.max(300, unwind.length * 13 + 118)}>
            {path.length ? (
              <ChartWithNotes
                chart={<SessionChart height={170} date={d.date} ariaLabel="max pain, forward and PCR through the expiry day"
                  series={[{ label: 'forward', color: T.text, x: pathX, y: path.map(p => p.forward), w: 1.3 },
                           { label: 'max pain', color: T.violet, x: pathX, y: path.map(p => p.max_pain), w: 1.5 },
                           { label: 'PCR', color: T.muted, x: pathX, y: path.map(p => p.pcr), axis: 'R', w: 1, dash: '3 3' }]} />}
                below={<div style={note()}>Max pain: the strike where option holders&apos; intrinsic value at settlement would be smallest — arithmetic
                  on the open interest in the snapshot; settlement is not drawn to it. PCR: put OI ÷ call OI in the snapshot. {sentence(DESCRIBES)}.</div>} />
            ) : <div style={{ fontSize: 11, color: T.muted }}>No path yet.</div>}
          </ExpandableChart>
          <ExpandableChart title="Straddle tracker vs past expiry days" accent={T.amber} source={decay.length ? tapeSource(d.chip, now) : curveSrc} badges={[{ label: 'context' }]}
            legend={`priced at ${fmtNum(live?.open_strike, 0)} · % of its first value`} height={320}>
            <ChartWithNotes
              chart={<SessionChart height={170} lUnit="%" date={d.date} ariaLabel="today's straddle against the historical expiry-day curve"
                band={curvePts.length ? { x: curvePts.map(p => p.minute), lo: curvePts.map(p => p.p25), hi: curvePts.map(p => p.p75) } : undefined}
                series={[{ label: 'median of past expiry days', color: T.muted, x: curvePts.map(p => p.minute), y: curvePts.map(p => p.median), dash: '4 3', w: 1.2 },
                         { label: 'today', color: T.amber, x: decayX, y: decay.map(p => p.pct_of_open), w: 1.8 }]} />}
              below={<>
                <div style={note(T.muted)}><span style={{ color: T.amber }}>— today</span>: the straddle at the opening ATM strike as priced, % of its first snapshot · <span style={{ color: T.muted }}>┄ median</span> and band (middle half) of {curve?.n ?? 0} past expiry days{curve?.start_minute ? `, each rebased to ${minuteLabel(curve.start_minute)} (today's first snapshot)` : ''}</div>
                <div style={{ fontSize: 11, color: T.text, marginTop: 4, flex: 'none' }}>{decayVsCurve(live?.vs_curve) ?? (curve?.n ? 'Today has no snapshot to compare yet.' : 'No past expiry day replayed yet.')}</div>
                <div style={note()}>{curve?.note?.split('; rebased')[0]}{curve?.replay_pending ? ` · ${curve.replay_pending}` : ''}</div>
              </>} />
          </ExpandableChart>
          <Panel title="Pin risk" accent={T.cyan} source={tapeSource(d.chip, now)} badge="context" subtitle="largest OI within ±1 % of spot">
            <DataTable dense columns={pinCols} rows={live?.pin_risk ?? []} rowKey={r => String(r.strike)} empty="no strike near spot in the snapshot" />
            <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>A settlement near a strike with large open interest leaves writers unsure whether they are
              exercised (index options settle in cash on NSE&apos;s closing value). {sentence(DESCRIBES)}.</div>
          </Panel>
        </div>
      )}

      {!d?.is_expiry_day && d && (
        <div style={{ marginBottom: 12 }}>
          <ExpandableChart title="The expiry-day straddle curve" accent={T.amber} source={curveSrc} badges={[{ label: 'context' }]}
            legend={`median and middle half of ${curve?.n ?? 0} replayed expiry days · % of the 09:15 straddle`} height={300}>
            {curvePts.length ? (
              <ChartWithNotes
                chart={<SessionChart height={170} lUnit="%" date={d.date} ariaLabel="historical expiry-day straddle curve"
                  band={{ x: curvePts.map(p => p.minute), lo: curvePts.map(p => p.p25), hi: curvePts.map(p => p.p75) }}
                  series={[{ label: 'median', color: T.amber, x: curvePts.map(p => p.minute), y: curvePts.map(p => p.median), w: 1.5 }]} />}
                below={<>
                  <div style={note()}>{curve?.note}{curve?.note ? '. ' : ''}{sentence(DESCRIBES)}.</div>
                  {curve?.replay_pending && <div style={note(T.amber)}>{curve.replay_pending}.</div>}
                </>} />
            ) : <div style={{ fontSize: 11, color: T.muted }}>No expiry day replayed yet: the replay is an after-close job (Breeze 1-minute bars of past expiries, O-T16). The next expiry day&apos;s line joins it once replayed.</div>}
          </ExpandableChart>
        </div>
      )}

      {d && (
        <Panel title="Implied vs realised (past expiries)" accent={T.cyan} source={scoreSrc} badge="arithmetic"
          subtitle="the last close's ATM straddle against NSE's settlement close · the RV20 move as the naive guess">
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginBottom: 8 }}>
            <Stat big={false} label="Expiries scored" value={d.scorecard.stats.n} sub={d.scorecard.stats.n < 20 ? 'fewer than 20: a first read only' : 'priced the session before'} />
            <Stat big={false} label="Move beat the straddle" value={d.scorecard.stats.n ? `${d.scorecard.stats.exceeded_pct?.toFixed(0)} %` : '—'}
              sub={`≈ ${d.scorecard.stats.fair_exceeded_pct?.toFixed(1) ?? '42.5'} % if fairly priced (normal)`} />
            <Stat big={false} label="Median realised ÷ priced" value={fmtNum(d.scorecard.stats.median_ratio, 2)} sub={`mean ${fmtNum(d.scorecard.stats.mean_ratio, 2)}`} />
            <Stat big={false} label="Straddle vs RV20 guess" value={d.scorecard.stats.compared ? `${d.scorecard.stats.implied_closer} of ${d.scorecard.stats.compared}` : '—'}
              sub={`closer · mean miss ${fmtNum(d.scorecard.stats.mean_abs_miss_pct, 2)} % vs ${fmtNum(d.scorecard.stats.naive_mean_abs_miss_pct, 2)} %`} />
          </div>
          <div style={{ fontSize: 11, color: T.text, marginBottom: 8 }} data-xpry-score>{scoreRead(d.scorecard.stats)}</div>
          <DataTable dense columns={scoreCols} rows={d.scorecard.rows} rowKey={r => r.expiry} maxHeight={320} exportName={`${symbol}-expiry-scorecard`}
            empty={d.scorecard.note ?? 'no scored expiry'} />
          <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{d.scorecard.definition}{d.scorecard.definition ? '. ' : ''}The IV tables keep the latest computation per session from the archived
            NSE files (PLAN §0.3); nothing here is re-scored by hand.</div>
        </Panel>
      )}
      </>}
    </div>
  )
}
