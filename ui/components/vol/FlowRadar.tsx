'use client'

/**
 * DERV › RADAR — the options flow radar (FINAL ROUND wave E, E-RADAR; PLAN W7 / F-16; precedent: Sensibull OI change,
 * Quantsapp strike activity — rebuilt as FACTS, never a story). One read, `/api/derivatives/flow-radar/{symbol}`
 * (services/ui-api/routers/flow_radar.py), computed from the EXISTING stored 2-minute tape:
 *  - per strike over a rolling window (15 / 30 / 60 min): the OI change, rendered on the kit's strike ladder
 *    (expiry/charts StrikeBars — SVG v2: wheel zoom over the strike window, drag pan, crosshair prints strike + both
 *    sides) inside an ExpandableChart; and the day's volume ÷ OI only when the store serves per-strike volume;
 *  - the ATM IV, PCR and max-pain change over the same window from the tape's full-resolution path (the IV change is
 *    the floating-ATM path's and says so — per-strike IV is not stored in this read);
 *  - the largest movers as fact lines: "OI rose 41.2 k at 25,900 CE in 28 min — describes, does not predict".
 * Honesty (binding): every badge is `context`; no direction word, no writers/buyers story, context never coloured;
 * when the tape gapped the gap is SHOWN and the span's real length named — never interpolated, never scaled to a
 * per-30-minute rate. Stored snapshots are DELAYED with their age, never LIVE. Nothing here feeds the Decision Desk,
 * the S1 shadow, a directional alert or a ticket price.
 */
import axios from 'axios'
import { useEffect, useState } from 'react'
import { Chip, DataTable, Notice, Panel, T, fmtNum, type Column, type SourceInfo } from '@/components/terminal'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { CALL_COLOR, PUT_COLOR, StrikeBars } from '@/components/expiry/charts'
import { DESCRIBES, fmtSignedOi, sentence, tapeSource, type Badge, type Chip as TapeChip } from '@/components/expiry/tapeModel'
import { apiError } from '@/lib/errors'

const client = axios.create({ baseURL: '', timeout: 20_000 })
const WINDOWS = [15, 30, 60] as const

interface LadderRow {
  strike: number; ce_oi: number | null; pe_oi: number | null; ce_d: number | null; pe_d: number | null
  ce_mid: number | null; pe_mid: number | null; ce_vol_oi: number | null; pe_vol_oi: number | null
}
interface Mover { strike: number; side: 'CE' | 'PE'; oi_delta: number; oi_now: number | null; vol_oi: number | null; line: string }
interface WindowBlock {
  requested_min: number; actual_min: number | null; from_ist: string | null; to_ist: string | null
  gapped: boolean; note: string | null
}
interface PathChange { now: number; then: number; delta: number; from_ist: string; to_ist: string; actual_min: number; label?: string }
interface Radar {
  symbol: string; date: string | null; expiry: string | null; expiries: string[]; lot: number | null; dte_calendar: number | null
  window: WindowBlock; gaps: { from_ist: string; to_ist: string; minutes: number }[]
  ladder: LadderRow[]; movers: Mover[]; forward: number | null
  atm_iv: PathChange | null; pcr: PathChange | null; max_pain: PathChange | null
  vol_oi_available: boolean; vol_oi_note: string | null
  snapshots: number; first: string | null; last: string | null; last_ts: string | null; median_gap_min: number | null
  source: string; frames_note: string; chip: TapeChip; badges: Record<string, Badge>; coverage: string; note: string
  ok: boolean; store_errors: Record<string, string>
}

const signedPts = (v: number, dp = 2) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(dp)}`

export function FlowRadar({ symbol }: { symbol: string }) {
  const [d, setD] = useState<Radar | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [windowMin, setWindowMin] = useState<number>(30)
  const [contracts, setContracts] = useState(false)
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    let alive = true
    const load = () => client.get<Radar>(`/api/derivatives/flow-radar/${encodeURIComponent(symbol)}`, { params: { window_min: windowMin } })
      .then(r => { if (alive) { setD(r.data); setErr(null); setNow(Date.now()) } })
      .catch((e: unknown) => { if (alive) setErr(apiError(e, 'flow radar unavailable')) })
    setD(null); load()
    const iv = setInterval(() => { if (!document.hidden) load() }, 60_000)            // the tape writes every 2 minutes
    return () => { alive = false; clearInterval(iv) }
  }, [symbol, windowMin])

  const src: SourceInfo = tapeSource(d?.chip, now)
  const reason = d && d.ok === false ? Object.values(d.store_errors ?? {}).join('; ') || 'store unavailable' : null
  const w = d?.window
  const lot = d?.lot ?? null
  const ladder = d?.ladder ?? []
  const fmt = (v: number) => fmtSignedOi(v, lot, contracts)
  const span = w?.actual_min != null ? `${w.actual_min} min` : '—'
  const cols: Column<Mover>[] = [
    { key: 'k', label: 'STRIKE', align: 'right', render: r => <b style={{ color: T.text }}>{r.strike.toLocaleString('en-IN')}</b> },
    { key: 's', label: 'SIDE', align: 'center', render: r => <span style={{ color: r.side === 'CE' ? CALL_COLOR : PUT_COLOR }}>{r.side}</span> },
    ...(d?.vol_oi_available ? [{ key: 'v', label: 'VOL ÷ OI (DAY)', align: 'right',
      render: (r: Mover) => fmtNum(r.vol_oi, 2) } as Column<Mover>] : []),
    { key: 'f', label: `THE FACT · ${span}`, align: 'left', render: r => <span style={{ color: T.muted }}>{r.line}</span> },
  ]
  return (
    <Panel title={`${symbol} · flow radar`} accent={T.cyan} pad={8} source={src} badge={d?.badges?.oi_delta ?? 'context'}
      subtitle={d?.snapshots
        ? `rolling ${windowMin} min over the stored 2-minute tape · ${d.first} → ${d.last} IST · ${d.snapshots} snapshots · expiry ${d.expiry} (${d.dte_calendar}d)`
        : d?.date ?? ''}
      right={<span style={{ display: 'inline-flex', gap: 4, flexWrap: 'wrap' }}>
        {WINDOWS.map(m => <Chip key={m} active={windowMin === m} onClick={() => setWindowMin(m)} title="the rolling window the changes span">{m}M</Chip>)}
        <Chip active={!contracts} onClick={() => setContracts(false)} title="OI as the exchange counts it (shares)">SHARES</Chip>
        <Chip active={contracts} onClick={() => setContracts(true)} title={lot ? `÷ lot ${lot}` : 'lot unknown: shares shown'}>CONTRACTS</Chip>
      </span>}>
      {err && <div style={{ fontSize: 11, color: T.amber }}>Flow radar unavailable: {err}</div>}
      {!err && reason && <div style={{ fontSize: 11, color: T.amber }}>Flow radar unavailable: {reason}</div>}
      {!err && !reason && !d && <div style={{ fontSize: 11, color: T.muted }}>Reading the stored tape…</div>}
      {!err && d && d.ok && !d.snapshots && (
        <div style={{ fontSize: 11, color: T.muted }}>
          {symbol} · no snapshot stored today. {sentence(d.coverage)}.
        </div>
      )}
      {d && d.snapshots > 0 && (
        <div style={{ display: 'grid', gap: 8 }}>
          {w?.note && <Notice color={T.amber}>{w.note}</Notice>}
          {(d.gaps?.length ?? 0) > 0 && (
            <Notice color={T.amber}>
              Tape gaps today (shown, never filled): {d.gaps.map(g => `${g.from_ist} → ${g.to_ist} IST (${g.minutes} min)`).join(' · ')}
            </Notice>
          )}
          {/* the window's path facts — neutral tone always: context is never coloured (PLAN §1) */}
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontFamily: T.mono, fontSize: 11, color: T.muted }}>
            {d.atm_iv && <span title={d.atm_iv.label}>ATM IV <b style={{ color: T.text }}>{fmtNum(d.atm_iv.now, 2)}%</b>
              <span style={{ color: T.dim }}> · {signedPts(d.atm_iv.delta)} pts / {d.atm_iv.actual_min} min (floating ATM)</span></span>}
            {d.pcr && <span>PCR (OI) <b style={{ color: T.text }}>{fmtNum(d.pcr.now, 2)}</b>
              <span style={{ color: T.dim }}> · {d.pcr.then.toFixed(2)} at {d.pcr.from_ist}</span></span>}
            {d.max_pain && <span>max pain <b style={{ color: T.text }}>{fmtNum(d.max_pain.now, 0)}</b>
              <span style={{ color: T.dim }}> · {fmtNum(d.max_pain.then, 0)} at {d.max_pain.from_ist}</span></span>}
          </div>
          <ExpandableChart title={`OI change by strike · ${w?.from_ist ?? '—'} → ${w?.to_ist ?? '—'} IST`} accent={T.cyan}
            badges={[{ label: 'context' }]} source={src} height={Math.max(180, ladder.length * 13 + 24)}
            legend={<span><span style={{ color: CALL_COLOR }}>calls</span> · <span style={{ color: PUT_COLOR }}>puts</span> · dashed = forward · faded = a fall · wheel = zoom the strikes</span>}>
            <StrikeBars strikes={ladder.map(r => r.strike)} ce={ladder.map(r => r.ce_d)} pe={ladder.map(r => r.pe_d)}
              mark={d.forward} fmt={fmt} ariaLabel={`open-interest change by strike over the last ${span}`} />
          </ExpandableChart>
          {d.movers.length > 0 && (
            <DataTable dense columns={cols} rows={d.movers} rowKey={r => `${r.strike}-${r.side}`}
              exportName={`${symbol}-flow-radar-${d.date}`} />
          )}
          {!d.vol_oi_available && d.vol_oi_note && <div style={{ fontSize: 10, color: T.dim }}>{d.vol_oi_note}</div>}
          <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5 }}>
            OI in {contracts && lot ? `contracts (shares ÷ lot ${lot})` : 'shares, the exchange unit'}. {d.frames_note}.
            {' '}{sentence(d.coverage)}. OI build-up has no tested edge on NSE (held-overnight study H2); {DESCRIBES}.
          </div>
        </div>
      )}
    </Panel>
  )
}
