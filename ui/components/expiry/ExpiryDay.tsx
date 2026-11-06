'use client'

/**
 * OMON › XPRY — the expiry-day view (reports/terminal_v2/PLAN.md 2.4; precedent Opstra / Sensibull expiry-day tools, ORATS
 * implied-vs-realised). On an expiry day it follows the expiring series through the session:
 *  - OI unwind by strike (the change since the first snapshot, both sides) and the totals;
 *  - max pain through the day against the forward;
 *  - today's straddle at the opening ATM strike as % of its first value, against the historical expiry-day curve (median and
 *    middle half of past expiry days, from Breeze 1-minute replays);
 *  - pin-risk strikes: the largest open interest within ±1 % of spot.
 * Every day: the next expiry and the implied-vs-realised scorecard (the last close's straddle against NSE's settlement close,
 * kept like the gold accuracy log: stored numbers, never re-scored; the RV20 move as the naive comparator).
 * `context` (OI, max pain, pin risk, curve) / `arithmetic` (scorecard). No signal, no score; describes, does not predict.
 */
import { useEffect, useState } from 'react'
import { Chip, DataTable, Notice, Panel, Stat, T, fmtNum, sourceOf, type Column } from '@/components/terminal'
import { useActiveSymbol } from '@/lib/activeSymbol'
import { getExpiryDay, storeReason, tapeError } from './api'
import { CALL_COLOR, PUT_COLOR, SessionChart, StrikeBars } from './charts'
import {
  DESCRIBES, TAPE_INDICES, decayVsCurve, expiryWords, fmtOi, fmtSignedOi, minuteLabel, minuteOf, scoreRead, sentence, sinceLabel, tapeSource, unwindRead,
  type ExpiryDay as Xpry, type PinRow, type ScoreRow,
} from './tapeModel'

export function ExpiryDay({ symbol: symbolProp }: { symbol?: string }) {
  const [active, setActive] = useActiveSymbol()
  const initial = (symbolProp ?? active?.symbol ?? 'NIFTY').toUpperCase()
  const [symbol, setSymbol] = useState(initial)
  useEffect(() => { if (symbolProp) setSymbol(symbolProp.toUpperCase()) }, [symbolProp])
  useEffect(() => { if (!symbolProp && active?.symbol && active.symbol !== symbol) setSymbol(active.symbol.toUpperCase()) },
    [active?.symbol])  // eslint-disable-line react-hooks/exhaustive-deps
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
  const curve = d?.curve
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
  const scoreSrc = sourceOf(d?.scorecard.rows[0]?.expiry ?? null, { source: 'iv_surface_daily + NSE index close', maxAgeDays: 10 })
  const curveSrc = curve && curve.n ? sourceOf(curve.expiries?.[curve.expiries.length - 1] ?? null, { source: 'Breeze 1-minute replay', maxAgeDays: 10 })
    : { state: 'offline' as const, source: 'Breeze 1-minute replay', asOf: null, hint: curve?.note ?? 'no replay stored yet' }
  return (
    <div data-xpry={symbol}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 10, color: T.muted, letterSpacing: 1 }}>XPRY · EXPIRY DAY</span>
        {!symbolProp && choices.map(s => <Chip key={s} active={symbol === s} onClick={() => pick(s)}>{s}</Chip>)}
        {symbolProp && <b style={{ fontSize: 11, color: T.amber }}>{symbol}</b>}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 10, color: T.dim }}>{d?.precedent}</span>
      </div>
      {err && <div style={{ marginBottom: 8 }}><Notice color={T.amber}>Expiry view unavailable: {err}</Notice></div>}
      {!err && reason && <div style={{ marginBottom: 8 }}><Notice color={T.amber}>Expiry view unavailable: {reason}</Notice></div>}
      {d && <div style={{ fontSize: 12, color: T.text, marginBottom: 10 }} data-xpry-words>{expiryWords(d)}</div>}

      {d?.is_expiry_day && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 12, marginBottom: 12 }}>
          <Panel title="OI unwind by strike" accent={T.cyan} source={tapeSource(d.chip, now)} badge="context"
            subtitle={live?.snapshots ? `${live.first} → ${live.last} IST · ${live.snapshots} snapshots` : 'no snapshot yet'}>
            {since.late && <div style={{ fontSize: 10, color: T.amber, marginBottom: 4 }}>Change {since.text}.</div>}
            {unwind.length ? <>
              <div style={{ display: 'flex', gap: 14, fontFamily: T.mono, fontSize: 11, marginBottom: 6 }}>
                <span>calls {fmtOi(totals.ceNow, null, false)} <span style={{ color: T.dim }}>({totals.cePct == null ? '—' : `${totals.cePct >= 0 ? '+' : '−'}${Math.abs(totals.cePct).toFixed(1)} %`})</span></span>
                <span>puts {fmtOi(totals.peNow, null, false)} <span style={{ color: T.dim }}>({totals.pePct == null ? '—' : `${totals.pePct >= 0 ? '+' : '−'}${Math.abs(totals.pePct).toFixed(1)} %`})</span></span>
                <span style={{ color: T.dim }}>shares, strikes near spot</span>
              </div>
              <StrikeBars strikes={unwind.map(r => r.strike)} ce={unwind.map(r => r.ce_chg_open)} pe={unwind.map(r => r.pe_chg_open)} mark={live?.spot ?? null} fmt={lotless}
                ariaLabel="OI change since the first snapshot by strike" />
              <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}><span style={{ color: CALL_COLOR }}>calls</span> · <span style={{ color: PUT_COLOR }}>puts</span> · faded = OI leaving · dashed = spot. {sentence(DESCRIBES)}.</div>
            </> : <div style={{ fontSize: 11, color: T.muted }}>The tape has not stored the expiring series yet today (09:15–15:30 IST, every 2 minutes when the budget allows).</div>}
          </Panel>
          <Panel title="Max pain through the day" accent={T.violet} source={tapeSource(d.chip, now)} badge="context"
            subtitle="vs the forward">
            {(live?.path ?? []).length ? <>
              <SessionChart height={170} ariaLabel="max pain and forward through the expiry day"
                series={[{ label: 'forward', color: T.text, x: (live?.path ?? []).map(p => minuteOf(p.ist) ?? 0), y: (live?.path ?? []).map(p => p.forward), w: 1.3 },
                         { label: 'max pain', color: T.violet, x: (live?.path ?? []).map(p => minuteOf(p.ist) ?? 0), y: (live?.path ?? []).map(p => p.max_pain), w: 1.5 }]} />
              <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}><span style={{ color: T.text }}>— forward</span> · <span style={{ color: T.violet }}>— max pain</span>: the strike where option holders&apos; intrinsic value at settlement would be smallest.
                Max pain is arithmetic on the open interest in the snapshot; settlement is not drawn to it. {sentence(DESCRIBES)}.</div>
            </> : <div style={{ fontSize: 11, color: T.muted }}>No path yet.</div>}
          </Panel>
          <Panel title="Straddle decay vs past expiry days" accent={T.amber} source={decay.length ? tapeSource(d.chip, now) : curveSrc} badge="context"
            subtitle={`at ${fmtNum(live?.open_strike, 0)} · % of its first value`}>
            <SessionChart height={180} lUnit="%" ariaLabel="straddle decay against the historical expiry-day curve"
              band={curvePts.length ? { x: curvePts.map(p => p.minute), lo: curvePts.map(p => p.p25), hi: curvePts.map(p => p.p75) } : undefined}
              series={[{ label: 'median of past expiry days', color: T.muted, x: curvePts.map(p => p.minute), y: curvePts.map(p => p.median), dash: '4 3', w: 1.2 },
                       { label: 'today', color: T.amber, x: decayX, y: decay.map(p => p.pct_of_open), w: 1.8 }]} />
            <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}><span style={{ color: T.amber }}>— today</span>: the straddle at the opening ATM strike as % of its first snapshot · <span style={{ color: T.muted }}>┄ median</span> and band (middle half) of {curve?.n ?? 0} past expiry days{curve?.start_minute ? `, each rebased to ${minuteLabel(curve.start_minute)} (today's first snapshot)` : ''}</div>
            <div style={{ fontSize: 11, color: T.text, marginTop: 4 }}>{decayVsCurve(live?.vs_curve) ?? (curve?.n ? 'Today has no snapshot to compare yet.' : 'No past expiry day replayed yet.')}</div>
            <div style={{ fontSize: 10, color: T.dim, marginTop: 2 }}>{curve?.note?.split('; rebased')[0]}</div>
          </Panel>
          <Panel title="Pin risk" accent={T.cyan} source={tapeSource(d.chip, now)} badge="context" subtitle="largest OI within ±1 % of spot">
            <DataTable dense columns={pinCols} rows={live?.pin_risk ?? []} rowKey={r => String(r.strike)} empty="no strike near spot in the snapshot" />
            <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>A settlement near a strike with large open interest leaves writers unsure whether they are
              exercised (index options settle in cash on NSE&apos;s closing value). {sentence(DESCRIBES)}.</div>
          </Panel>
        </div>
      )}

      {!d?.is_expiry_day && d && (
        <div style={{ marginBottom: 12 }}>
          <Panel title="The expiry-day straddle curve" accent={T.amber} source={curveSrc} badge="context"
            subtitle={`median and middle half of ${curve?.n ?? 0} replayed expiry days (straddle at the opening strike, % of its 09:15 value)`}>
            {curvePts.length ? <SessionChart height={170} lUnit="%" ariaLabel="historical expiry-day straddle curve"
              band={{ x: curvePts.map(p => p.minute), lo: curvePts.map(p => p.p25), hi: curvePts.map(p => p.p75) }}
              series={[{ label: 'median', color: T.amber, x: curvePts.map(p => p.minute), y: curvePts.map(p => p.median), w: 1.5 }]} />
              : <div style={{ fontSize: 11, color: T.muted }}>No expiry day replayed yet: the replay is an after-close job (Breeze 1-minute bars of past expiries, O-T16). Today&apos;s line joins it on the next expiry day.</div>}
            <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>{curve?.note}{curve?.note ? '. ' : ''}{sentence(DESCRIBES)}.</div>
          </Panel>
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
    </div>
  )
}
