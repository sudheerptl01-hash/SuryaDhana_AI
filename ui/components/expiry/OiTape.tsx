'use client'

/**
 * OMON › LIVE — the intraday OI / IV tape (reports/terminal_v2/PLAN.md 2.1; precedent Bloomberg OMON intraday, Sensibull OI
 * change, Quantsapp IV live). It supersedes the 15-minute pilot panel (vol/IvLivePath) on OMON's LIVE mode:
 *  - the day's path of the ATM IV (ours, from bid/ask mids; NSE's beside it when the v3 fallback served), the ATM straddle at
 *    the moving ATM and at the opening ATM strike (one instrument: the decay read), PCR and max pain;
 *  - OI by strike: the change since the first snapshot (both sides), OI now, or a time-lapse scrubber over the day's frames;
 *  - the latest stored bid / ask and the change vs the previous session per strike near the forward.
 * `context` (OI, PCR, max pain, straddle path) / `arithmetic` (IV); the chip is DELAYED with the snapshot's age, never LIVE
 * (stored snapshots, not a stream); nothing here feeds a trade. Times are IST.
 */
import { useEffect, useMemo, useState } from 'react'
import { Chip, DataTable, Notice, Panel, T, fmtNum, type Column, type SourceInfo } from '@/components/terminal'
import { getOiTape, storeReason, tapeError } from './api'
import { CALL_COLOR, PUT_COLOR, SessionChart, StrikeBars } from './charts'
import { DESCRIBES, fmtOi, fmtSignedOi, frameAt, sentence, sinceLabel, tapeSeries, tapeSource, type OiTape as Tape, type StrikeRow } from './tapeModel'

type OiView = 'change' | 'now' | 'lapse'

export function OiTape({ symbol, enabled, expiry }: { symbol: string; enabled: boolean; expiry?: string | null }) {
  const [d, setD] = useState<Tape | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [view, setView] = useState<OiView>('change')
  const [contracts, setContracts] = useState(false)
  const [frame, setFrame] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    let alive = true
    const load = () => getOiTape(symbol, { expiry: expiry ?? undefined })
      .then(r => { if (alive) { setD(r.data); setErr(null); setNow(Date.now()) } })
      .catch((e: unknown) => { if (alive) setErr(tapeError(e)) })
    setD(null); setFrame(null); load()
    const iv = setInterval(() => { if (!document.hidden) load() }, 60_000)             // the tape writes every 2 minutes
    const tick = setInterval(() => setNow(Date.now()), 15_000)
    return () => { alive = false; clearInterval(iv); clearInterval(tick) }
  }, [symbol, enabled, expiry])
  const series = useMemo(() => tapeSeries(d?.path ?? []), [d])
  if (!enabled) return null
  const path = d?.path ?? []
  const last = path.length ? path[path.length - 1] : null
  const first = path.length ? path[0] : null
  const src: SourceInfo = tapeSource(d?.chip, now)
  const reason = storeReason(d)
  if (!err && d && d.ok && !last) {
    return <div data-oi-tape="not-covered" style={{ fontSize: 11, color: T.muted, margin: '0 0 10px' }}>
      {symbol} · intraday tape: no snapshot stored today. {sentence(d.coverage)}; {symbol}&apos;s live chain and NSE&apos;s IV are in the chain below.
    </div>
  }
  const since = sinceLabel(d?.first)
  const lot = d?.lot ?? null
  const fmt = (v: number) => (view === 'change' ? fmtSignedOi(v, lot, contracts) : fmtOi(v, lot, contracts))
  const strikes = d?.strikes ?? []
  const axis = strikes.map(r => r.strike)
  const fr = view === 'lapse' ? frameAt(d?.frames ?? [], frame ?? (d?.frames.length ?? 1) - 1) : null
  const ce = view === 'change' ? strikes.map(r => r.ce_chg_open) : view === 'now' ? strikes.map(r => r.ce_oi) : (fr?.ce ?? [])
  const pe = view === 'change' ? strikes.map(r => r.pe_chg_open) : view === 'now' ? strikes.map(r => r.pe_oi) : (fr?.pe ?? [])
  const near = last ? [...strikes].sort((a, b) => Math.abs(a.strike - last.forward) - Math.abs(b.strike - last.forward)).slice(0, 9).sort((a, b) => a.strike - b.strike) : []
  const cols: Column<StrikeRow>[] = [
    { key: 'cb', label: 'CALL BID / ASK', align: 'right', render: r => <span>{fmtNum(r.ce_bid, 2)} / {fmtNum(r.ce_ask, 2)}</span> },
    { key: 'co', label: `CALL OI Δ ${since.late ? 'since 1st' : 'since open'}`, align: 'right', render: r => fmtSignedOi(r.ce_chg_open, lot, contracts) },
    { key: 'cp', label: 'Δ vs prev session', align: 'right', render: r => fmtSignedOi(r.ce_chg_prev, lot, contracts) },
    { key: 'k', label: 'STRIKE', align: 'center', render: r => <b style={{ color: last && Math.abs(r.strike - last.forward) === Math.min(...near.map(n => Math.abs(n.strike - last.forward))) ? T.amber : T.text }}>{r.strike.toLocaleString('en-IN')}</b> },
    { key: 'pp', label: 'Δ vs prev session', align: 'right', render: r => fmtSignedOi(r.pe_chg_prev, lot, contracts) },
    { key: 'po', label: `PUT OI Δ ${since.late ? 'since 1st' : 'since open'}`, align: 'right', render: r => fmtSignedOi(r.pe_chg_open, lot, contracts) },
    { key: 'pb', label: 'PUT BID / ASK', align: 'right', render: r => <span>{fmtNum(r.pe_bid, 2)} / {fmtNum(r.pe_ask, 2)}</span> },
  ]
  const chg = (a: number | null | undefined, b: number | null | undefined, dp = 2) =>
    a == null || b == null ? '' : ` (${a - b >= 0 ? '+' : '−'}${Math.abs(a - b).toFixed(dp)} since ${first?.ist})`
  return (
    <Panel title={`${symbol} · intraday tape`} accent={T.cyan} pad={8} style={{ marginBottom: 12 }} source={src} badge={d?.badges?.tape ?? 'context'}
      subtitle={last ? `${first?.ist} → ${last.ist} IST · ${d?.snapshots} snapshots${d?.median_gap_min ? ` · every ≈ ${d.median_gap_min} min` : ''} · expiry ${d?.expiry} (${d?.dte_calendar}d) · ${d?.source === 'nse' ? 'NSE v3 fallback' : 'Breeze chain'}` : d?.date ?? ''}
      right={<span style={{ display: 'inline-flex', gap: 4 }}>
        <Chip active={!contracts} onClick={() => setContracts(false)} title="OI as the exchange counts it (shares)">SHARES</Chip>
        <Chip active={contracts} onClick={() => setContracts(true)} title={lot ? `÷ lot ${lot}` : 'lot unknown: shares shown'}>CONTRACTS</Chip>
      </span>}>
      {err && <div style={{ fontSize: 11, color: T.amber }}>Tape unavailable: {err}</div>}
      {!err && reason && <div style={{ fontSize: 11, color: T.amber }}>Tape unavailable: {reason}</div>}
      {since.late && last && <div style={{ marginBottom: 6 }}><Notice color={T.amber}>The first snapshot today is {d?.first} IST, not the 09:15 open: &quot;since the open&quot; below means since {d?.first}.</Notice></div>}
      {last && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(230px, 1fr)', gap: 12, alignItems: 'start' }}>
          <div>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>
              <span style={{ color: T.cyan }}>— ATM IV %</span> (left) · <span style={{ color: T.amber }}>— straddle ₹ at the moving ATM</span> · <span style={{ color: T.amber }}>┄ at the opening strike {fmtNum(first?.open_strike, 0)}</span> (right)
            </div>
            <SessionChart height={160} lUnit="%" ariaLabel="intraday ATM IV and straddle"
              series={[{ label: 'ATM IV', color: T.cyan, x: series.x, y: series.iv, w: 1.7 },
                       { label: 'straddle', color: T.amber, x: series.x, y: series.straddle, axis: 'R', w: 1.1 },
                       { label: 'straddle @ open strike', color: T.amber, x: series.x, y: series.straddleOpen, axis: 'R', w: 1, dash: '4 3' }]} />
            <div style={{ fontSize: 10, color: T.muted, margin: '6px 0 4px' }}>
              <span style={{ color: T.text }}>— forward</span> · <span style={{ color: T.violet }}>— max pain</span> (left) · <span style={{ color: T.muted }}>┄ PCR</span> (right)
            </div>
            <SessionChart height={120} ariaLabel="forward, max pain and PCR through the day"
              series={[{ label: 'forward', color: T.text, x: series.x, y: series.fwd, w: 1.3 },
                       { label: 'max pain', color: T.violet, x: series.x, y: series.maxPain, w: 1.3 },
                       { label: 'PCR', color: T.muted, x: series.x, y: series.pcr, axis: 'R', w: 1, dash: '3 3' }]} />
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 11, display: 'grid', gap: 5 }}>
            <div>ATM IV <b style={{ color: T.text }}>{fmtNum(last.atm_iv, 2)}%</b><span style={{ color: T.dim }}>{chg(last.atm_iv, first?.atm_iv)}</span>
              {last.nse_atm_iv != null && <span style={{ color: T.dim }}> · NSE {fmtNum(last.nse_atm_iv, 2)}%</span>}</div>
            <div>straddle <b style={{ color: T.text }}>₹{fmtNum(last.straddle, 2)}</b> <span style={{ color: T.dim }}>@ {fmtNum(last.atm_strike, 0)}</span></div>
            <div>@ opening strike {fmtNum(first?.open_strike, 0)}: <b style={{ color: T.text }}>₹{fmtNum(last.straddle_open_strike, 2)}</b>
              {first?.straddle_open_strike && last.straddle_open_strike ? <span style={{ color: T.dim }}> = {(last.straddle_open_strike / first.straddle_open_strike * 100).toFixed(0)} % of {first.ist}</span> : null}</div>
            <div>PCR (OI) <b style={{ color: T.text }}>{fmtNum(last.pcr, 2)}</b><span style={{ color: T.dim }}>{chg(last.pcr, first?.pcr)}</span></div>
            <div>max pain <b style={{ color: T.text }}>{fmtNum(last.max_pain, 0)}</b> <span style={{ color: T.dim }}>vs forward {fmtNum(last.forward, 1)} · {last.n_strikes} strikes in the snapshot</span></div>
            <div style={{ color: T.dim, fontSize: 10, lineHeight: 1.5, marginTop: 4 }}>
              IV from the bid/ask mid on the parity forward, T = time to 15:30 IST on expiry ({d?.model_version}). Max pain and OI
              describe where writers are positioned; {DESCRIBES}.
            </div>
          </div>
        </div>
      )}
      {last && (
        <div style={{ marginTop: 10 }}>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginBottom: 4 }}>
            <span style={{ fontSize: 10, color: T.muted, letterSpacing: 1 }}>OI BY STRIKE</span>
            <Chip active={view === 'change'} onClick={() => setView('change')}>CHANGE {since.late ? `SINCE ${d?.first}` : 'SINCE OPEN'}</Chip>
            <Chip active={view === 'now'} onClick={() => setView('now')}>OI NOW</Chip>
            <Chip active={view === 'lapse'} onClick={() => setView('lapse')} title="scrub through the day's snapshots">TIME-LAPSE</Chip>
            {view === 'lapse' && (d?.frames.length ?? 0) > 1 && (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10, color: T.muted }}>
                <input type="range" min={0} max={(d?.frames.length ?? 1) - 1} value={frame ?? (d?.frames.length ?? 1) - 1}
                  onChange={e => setFrame(Number(e.target.value))} aria-label="time-lapse frame" style={{ width: 220 }} />
                <b style={{ color: T.text }}>{fr?.ist} IST</b>
              </span>
            )}
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 10, color: T.dim }}><span style={{ color: CALL_COLOR }}>calls</span> · <span style={{ color: PUT_COLOR }}>puts</span> · dashed = forward · faded = a fall</span>
          </div>
          <StrikeBars strikes={axis} ce={ce} pe={pe} mark={last.forward} fmt={fmt} ariaLabel="open interest by strike" />
          <div style={{ marginTop: 8 }}>
            <DataTable dense columns={cols} rows={near} rowKey={r => String(r.strike)} exportName={`${symbol}-tape-${d?.date}`} />
          </div>
          <div style={{ fontSize: 10, color: T.dim, marginTop: 4 }}>
            OI in {contracts && lot ? `contracts (shares ÷ lot ${lot})` : 'shares, the exchange unit'}; bid / ask and the change vs the previous session are the last
            stored snapshot ({last.ist} IST). {sentence(d?.coverage)}. OI build-up has no tested edge on NSE (held-overnight study H2); {DESCRIBES}.
          </div>
        </div>
      )}
    </Panel>
  )
}
