'use client'

/**
 * GPLN — Morning Game Plan (terminal_final PLAN W7 / F-11, wave E).
 *
 * Six tiles assembled by ONE ui-api read (/api/gameplan): overnight moves (GIFT + COMEX gold), the prior
 * session's range, the stored chain's OI walls + max pain, the IV regime vs the prior session, today's events
 * and the owner's focus list (watchlist + overnight alert fires). Facts assembled, the trader decides.
 *
 * Honesty rules (PLAN §1, binding): every tile carries the payload's badge and its OWN as-of on a SourceChip;
 * no direction words; context is never coloured; the page states "assembled from stored/live reads — describes,
 * does not predict". Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.
 * A dead read degrades its tile alone (calm line, no raw transport text — the server normalizes).
 *
 * The 08:50 Telegram digest (scripts/morning_gameplan.py) renders this same payload as text lines.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { Chip, Grid, Loading, PageHeader, Panel, T, sourceOf, type SourceInfo } from '@/components/terminal'
import { GAMEPLAN_SYMBOLS, getGamePlan, type GamePlanSymbol } from './api'
import {
  PAGE_NOTE, TILE_TITLES, day, dedupeEcoRows, num, pct, pts, tileChipPlan, watchlistLine,
  type CorpBlock, type EcoRow, type FireRow, type GamePlanPayload, type GiftBlock, type GoldBlock, type Tile,
} from './model'

const POLL_MS = 120_000

/** The kit chip for one tile (model owns the plan; terminal/source.ts owns the chip states). */
function tileChip(tile: Tile | undefined): SourceInfo {
  const p = tileChipPlan(tile)
  if (p.dead) return { state: 'offline', source: p.source, asOf: p.asOf, ageDays: null, hint: p.hint }
  return sourceOf(p.asOf, { source: p.source })
}

/** The calm body of a tile whose read failed (the server already normalized the error text). */
function DeadTile({ tile }: { tile: Tile | undefined }) {
  return (
    <div style={{ color: T.muted, fontSize: 11, padding: '6px 0' }}>
      ● {tile?.error ?? 'no read yet'} — retries by itself
    </div>
  )
}

function Row({ k, v, title }: { k: React.ReactNode; v: React.ReactNode; title?: string }) {
  return (
    <div title={title} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '3px 0',
                                borderBottom: `1px solid ${T.border}22`, fontSize: 12 }}>
      <span style={{ color: T.muted, fontSize: 11, letterSpacing: 0.6, textTransform: 'uppercase' }}>{k}</span>
      <span style={{ fontFamily: T.mono, color: T.text, textAlign: 'right' }}>{v}</span>
    </div>
  )
}

export function GamePlan() {
  const [symbol, setSymbol] = useState<GamePlanSymbol>('NIFTY')
  const [data, setData] = useState<GamePlanPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const alive = useRef(true)

  const load = useCallback((sym: GamePlanSymbol) => {
    setLoading(true)
    getGamePlan(sym)
      .then(p => { if (alive.current) { setData(p); setError(null) } })
      .catch(() => { if (alive.current) setError('the game plan read did not answer — retries by itself') })
      .finally(() => { if (alive.current) setLoading(false) })
  }, [])

  useEffect(() => {
    alive.current = true
    load(symbol)
    const t = window.setInterval(() => load(symbol), POLL_MS)
    return () => { alive.current = false; window.clearInterval(t) }
  }, [symbol, load])

  const tiles = data?.tiles
  const overnight = tiles?.overnight
  const levels = tiles?.levels
  const oi = tiles?.oi
  const iv = tiles?.iv
  const events = tiles?.events
  const focus = tiles?.focus

  const gift = (overnight?.gift ?? null) as GiftBlock | null
  const gold = (overnight?.gold ?? null) as GoldBlock | null
  const ivToday = (iv?.today ?? null) as Record<string, number | string | null> | null
  const ivChange = (iv?.change ?? null) as Record<string, number | null> | null
  const eco = dedupeEcoRows(events?.eco as EcoRow[] | undefined, oi?.expiry as string | null | undefined)
  const corp = (events?.corporate ?? null) as CorpBlock | null
  const fires = (focus?.fires ?? null) as { since?: string; count?: number; rows?: FireRow[] } | null

  return (
    <div>
      <PageHeader code="GPLN" title="Morning Game Plan"
                  subtitle={`${PAGE_NOTE} · nothing here feeds the Desk, the S1 shadow, alerts or a ticket`}
                  right={(
                    <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                      {GAMEPLAN_SYMBOLS.map(s => (
                        <Chip key={s} active={s === symbol} color={s === symbol ? T.amber : T.muted}
                              onClick={() => setSymbol(s)}>{s}</Chip>
                      ))}
                      <Chip color={T.amber} onClick={() => load(symbol)}>↻</Chip>
                    </span>
                  )} />
      {error && <div style={{ color: T.muted, fontSize: 11, margin: '8px 0' }}>● {error}</div>}
      {!data && loading && <Loading label="assembling the game plan" />}
      {data && (
        <Grid cols={3} min={320} gap={10}>
          <Panel title={TILE_TITLES.overnight} badge={overnight?.badge} source={tileChip(overnight)}>
            {!overnight?.ok ? <DeadTile tile={overnight} /> : (
              <>
                <Row k="GIFT NIFTY" v={gift?.last != null ? num(gift.last) : '—'}
                     title="GIFT NIFTY last (NSE copy via data-service)" />
                <Row k="implied open gap" v={pct(gift?.implied_gap_pct)}
                     title="the gap GIFT implies for the NIFTY open — a published derivation, not a forecast of the day" />
                <Row k={`COMEX gold · ${day(gold?.last_date) || '—'}${gold?.partial ? ' (in-progress)' : ''}`}
                     v={`${num(gold?.last, 1)} · ${pct(gold?.change_pct)}`}
                     title={`stored daily bar vs prior close ${day(gold?.prev_date)}`} />
              </>
            )}
          </Panel>

          <Panel title={TILE_TITLES.levels} badge={levels?.badge} source={tileChip(levels)}>
            {!levels?.ok ? <DeadTile tile={levels} /> : (
              <>
                <Row k={`close · ${day(levels.session as string)}`}
                     v={`${num(levels.close as number)} (${pct(levels.change_pct as number)})`} />
                <Row k="high" v={num(levels.high as number)} />
                <Row k="low" v={num(levels.low as number)} />
                <div style={{ color: T.muted, fontSize: 10, marginTop: 6 }}>{String(levels.note ?? '')}</div>
              </>
            )}
          </Panel>

          <Panel title={TILE_TITLES.oi} badge={oi?.badge} source={tileChip(oi)}>
            {!oi?.ok ? <DeadTile tile={oi} /> : (
              <>
                <Row k="expiry" v={`${day(oi.expiry as string)} · ${oi.days_to_expiry ?? '—'} DTE`} />
                <Row k="max pain" v={num(oi.max_pain as number)} />
                <Row k="PCR (OI)" v={num(oi.pcr_oi as number, 2)} />
                <Row k="ATM IV · expected move" v={`${num(oi.atm_iv as number, 1)} · ${pct(oi.expected_move_pct as number, 1)}`}
                     title="near-expiry ATM IV and the move it prices to expiry — a definition, not a forecast" />
                <Row k="largest call OI" v={((oi.call_walls as number[]) ?? []).slice(0, 3).map(x => num(x)).join(' / ') || '—'}
                     title={String(oi.walls_note ?? '')} />
                <Row k="largest put OI" v={((oi.put_walls as number[]) ?? []).slice(0, 3).map(x => num(x)).join(' / ') || '—'}
                     title={String(oi.walls_note ?? '')} />
              </>
            )}
          </Panel>

          <Panel title={TILE_TITLES.iv} badge={iv?.badge} source={tileChip(iv)}>
            {!iv?.ok ? <DeadTile tile={iv} /> : (() => {
              const definitions = (iv.definitions ?? {}) as Record<string, string>   // hover text comes from the route (G9.1)
              return (
              <>
                <Row k="IV30 (constant maturity)"
                     v={`${num(ivToday?.iv30_cm as number, 1)} (${pts(ivChange?.iv30_cm)} vs prior)`} />
                <Row k="IV percentile (252s)" v={num(ivToday?.iv_pctile_252 as number)}
                     title={definitions.iv_pctile_252 ?? ''} />
                <Row k="IV rank (252s)" v={num(ivToday?.iv_rank_252 as number)}
                     title={definitions.iv_rank_252 ?? ''} />
                <Row k="IV − RV20" v={pts(ivToday?.iv_minus_rv20 as number)}
                     title={String(iv.spread_estimator ?? 'close-to-close')} />
                <div style={{ color: T.muted, fontSize: 10, marginTop: 6 }}>{String(iv.spread_estimator ?? '')}</div>
              </>
              )
            })()}
          </Panel>

          <Panel title={TILE_TITLES.events} badge={events?.badge} source={tileChip(events)}>
            {!events?.ok ? <DeadTile tile={events} /> : (
              <>
                {eco.length === 0 && <div style={{ color: T.muted, fontSize: 11 }}>no calendar rows today / tomorrow</div>}
                {eco.slice(0, 6).map((e, i) => (
                  <Row key={i} k={`${e.kind ?? ''} · ${day(e.date)}${e.time ? ` ${e.time}` : ''}`} v={e.what ?? ''} />
                ))}
                {corp && (
                  <div style={{ color: T.muted, fontSize: 11, marginTop: 6 }}>
                    corporate calendar: {corp.count ?? 0} rows today
                    {(corp.rows ?? []).length > 0 && ` — ${(corp.rows ?? []).slice(0, 6).map(r => r.symbol).filter(Boolean).join(', ')}`}
                  </div>
                )}
              </>
            )}
          </Panel>

          <Panel title={TILE_TITLES.focus} badge={focus?.badge} source={tileChip(focus)}>
            {!focus?.ok ? <DeadTile tile={focus} /> : (
              <>
                <Row k="watchlist" v={watchlistLine(focus.watchlist as string[])} />
                <Row k={`alert fires since ${day(fires?.since) || 'prior close'} 15:30`} v={String(fires?.count ?? 0)} />
                {(fires?.rows ?? []).slice(0, 6).map((f, i) => (
                  <div key={i} style={{ color: T.muted, fontSize: 11, padding: '2px 0' }}>
                    {f.text ?? `${f.symbol ?? ''} ${f.series ?? ''}`}
                  </div>
                ))}
                <div style={{ color: T.muted, fontSize: 10, marginTop: 6 }}>{String(focus.note ?? '')}</div>
              </>
            )}
          </Panel>
        </Grid>
      )}
      <div style={{ color: T.muted, fontSize: 10, marginTop: 10, letterSpacing: 0.4 }}>
        {PAGE_NOTE} · {data?.feeds ?? 'nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price'}
      </div>
    </div>
  )
}
