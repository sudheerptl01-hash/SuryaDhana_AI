'use client'

/**
 * ☆ PIN · + WATCHLIST · ALERT (bell glyph) · ↗ TRADINGVIEW · ↗ YAHOO — the News Terminal's chart actions, for every
 * chart in the app that shows one instrument.
 *
 *   <ChartActions ticker="RELIANCE" name="Reliance Industries" from="Stocks" />
 *   <ChartActions instrument={futuresInstrument('GC=F')} name="Gold" from="Commodity" />
 *
 * PIN adds the instrument to the shared pin list (News Terminal → PINNED: chart + headlines).
 * WATCHLIST is the SuryaDhana watchlist (Stocks / Backtest / Pipeline); Indian equities only.
 */
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { useWatchlist } from '@/context/AppContext'
import { pinFor, usePins } from '@/lib/pins'
import { useAlerts } from '@/lib/alerts'
import type { NewsSymbol } from '@/components/news/types'
import { Chip, Input, T } from './index'
import { BellGlyph } from '@/components/shell/Glyphs'
import { alertFormFill, type AlertFields } from '@/components/pageModels'

/** NSE (default) or BSE equity from an app ticker: 'RELIANCE', 'M&M', 'TCS.NS', '500325.BO', 'NSE:INFY'. */
export function equityInstrument(ticker: string): NewsSymbol {
  let base = ticker.trim().toUpperCase().replace(/^(NSE|BSE)\s*:\s*/, '')
  let exchange = /^\d+$/.test(base) ? 'BSE' : 'NSE'
  if (base.endsWith('.NS')) base = base.slice(0, -3)
  else if (base.endsWith('.BO')) { base = base.slice(0, -3); exchange = 'BSE' }
  // TradingView spells & and - as _ in NSE/BSE symbols (M&M → NSE:M_M, BAJAJ-AUTO → NSE:BAJAJ_AUTO)
  return { base, exchange, region: 'IN', yahoo: `${base}${exchange === 'BSE' ? '.BO' : '.NS'}`,
           tv: `${exchange}:${base.replace(/[&-]/g, '_')}` }
}

/** Yahoo continuous futures ('GC=F') → TradingView continuous contract ('GC1!'). */
export function futuresInstrument(yahoo: string): NewsSymbol {
  const root = yahoo.replace(/=F$/i, '').toUpperCase()
  return { base: root, exchange: 'FUTURES', region: 'OTHER', yahoo, tv: `${root}1!` }
}

export const tradingViewUrl = (tv: string) => `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(tv)}`
export const yahooUrl = (yahoo: string) => `https://finance.yahoo.com/quote/${encodeURIComponent(yahoo)}`

/** Price-alert form for one stock (mounted only when opened: useAlerts polls the server while it is mounted).
 *  layout 'inline' sits in a panel-header row; 'row' takes the full width of its container (stock window). */
function AlertForm({ inst, onClose, layout = 'inline' }: { inst: NewsSymbol; onClose: () => void; layout?: 'inline' | 'row' }) {
  const { alerts, setLevels } = useAlerts()
  const cur = alerts[inst.base]
  // P11: the form mounts before useAlerts' first server read, so the saved levels arrive after the first render. Every
  // box the user has not typed in takes them (pageModels.alertFormFill); typed text is never overwritten.
  const [fields, setFields] = useState<AlertFields>(() => alertFormFill({ up: '', down: '', move: '' }, {}, cur))
  const touched = useRef<Partial<Record<keyof AlertFields, boolean>>>({})
  useEffect(() => { setFields(f => alertFormFill(f, touched.current, cur)) }, [cur?.above, cur?.below, cur?.move])   // eslint-disable-line react-hooks/exhaustive-deps
  const edit = (k: keyof AlertFields) => (v: string) => { touched.current[k] = true; setFields(f => ({ ...f, [k]: v })) }
  const { up, down, move } = fields
  const setUp = edit('up'), setDown = edit('down'), setMove = edit('move')
  const num = (v: string) => { const x = Number(v.replace(/[,₹%\s]/g, '')); return x > 0 ? x : null }
  const save = () => { setLevels(inst.base, { above: num(up), below: num(down), move: num(move) }, inst.yahoo); onClose() }
  const field = (label: string, value: string, set: (v: string) => void, placeholder: string, title: string) => (
    <span title={title}>
      <Input label={label} value={value} onChange={set} placeholder={placeholder} width={layout === 'row' ? 96 : 84}
        aria-label={`${label} alert level for ${inst.base}`} style={{ fontSize: 11, padding: '3px 6px' }} />
    </span>
  )
  return (
    <span role="group" aria-label={`Price alert for ${inst.base}`}
      style={{ display: layout === 'row' ? 'flex' : 'inline-flex', flexWrap: 'wrap', gap: '4px 8px',
               alignItems: 'end', border: `1px solid ${T.amber}66`, padding: '4px 8px', background: '#120e04',
               ...(layout === 'row' ? { width: '100%', boxSizing: 'border-box' } : null) }}>
      <span style={{ fontSize: 10, color: T.amber, whiteSpace: 'nowrap', alignSelf: 'center' }}>ALERT {inst.base}</span>
      {field('ABOVE ₹', up, setUp, 'e.g. 3450', 'Fires once when the price rises above this level')}
      {field('BELOW ₹', down, setDown, 'e.g. 3180', 'Fires once when the price falls below this level')}
      {field('MOVE %', move, setMove, 'e.g. 5', 'Fires once when the stock moves this % from the official previous close, either way')}
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', alignSelf: 'center' }}>
        <Chip color={T.green} aria-label={`Save alert levels for ${inst.base}`} onClick={save}>SET</Chip>
        {cur && <Chip color={T.red} aria-label={`Clear all alert levels for ${inst.base}`}
          onClick={() => { setLevels(inst.base, { above: null, below: null, move: null }); onClose() }}>CLEAR</Chip>}
        <Chip color={T.muted} aria-label="Close the alert editor" onClick={onClose}
          style={{ minWidth: 24, minHeight: 24, justifyContent: 'center', padding: '3px 5px' }}>✕</Chip>
      </span>
    </span>
  )
}

export function ChartActions({ ticker, instrument, name, from, style, alertLayout = 'inline' }: {
  ticker?: string | null
  instrument?: NewsSymbol
  name?: string | null
  from: string                  // where the pin was made, shown in the News Terminal
  style?: CSSProperties
  /** 'inline': the alert form replaces the ALERT chip in this row. 'row': it opens on a full-width
   *  line under the chips, so a tight header row (stock window) is never pushed off-screen. */
  alertLayout?: 'inline' | 'row'
}) {
  const { pins, toggle } = usePins()
  const [alertOpen, setAlertOpen] = useState(false)
  const { addToWatchlist, removeFromWatchlist, isWatched } = useWatchlist()
  const inst = instrument ?? (ticker ? equityInstrument(ticker) : null)
  if (!inst) return null
  const pinned = !!pins[inst.yahoo]
  const watched = inst.region === 'IN' && isWatched(inst.base)
  const link = (href: string, label: string, color: string, title: string) => (
    <a href={href} target="_blank" rel="noreferrer" title={title} style={{ textDecoration: 'none' }}>
      <Chip color={color} style={{ cursor: 'pointer' }}>{label}</Chip>
    </a>
  )
  const row = (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', ...(alertLayout === 'row' ? null : style) }}
         onClick={e => e.stopPropagation()}>
      <Chip color={T.amber} active={pinned} onClick={() => toggle(inst.yahoo, () => pinFor(inst, name || inst.base, from))}
        title={pinned ? 'Unpin' : 'Pin: listed under PINNED in the News Terminal (Shift+N) with chart and headlines'}>
        {pinned ? '★ PINNED' : '☆ PIN'}
      </Chip>
      {inst.region === 'IN' && (
        <Chip color={T.green} active={watched}
          onClick={() => (watched ? removeFromWatchlist(inst.base) : addToWatchlist(inst.base))}
          title={watched ? 'Remove from the SuryaDhana watchlist' : 'Add to the SuryaDhana watchlist (Stocks / Backtest / Pipeline)'}>
          {watched ? '✓ IN WATCHLIST' : '+ WATCHLIST'}
        </Chip>
      )}
      {inst.region === 'IN' && (alertOpen && alertLayout === 'inline'
        ? <AlertForm inst={inst} onClose={() => setAlertOpen(false)} />
        : <Chip color={T.amber} active={alertOpen} onClick={() => setAlertOpen(o => !o)}
            title="Price alert: a Mac notification when the stock crosses your level (checked every minute in market hours, even with the terminal closed)">
            <BellGlyph /> ALERT</Chip>)}
      {link(tradingViewUrl(inst.tv), '↗ TRADINGVIEW', T.cyan, `Open ${inst.tv} on TradingView`)}
      {link(yahooUrl(inst.yahoo), '↗ YAHOO', T.violet, `Open ${inst.yahoo} on Yahoo Finance`)}
    </div>
  )
  if (alertLayout === 'inline') return row
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0, ...style }}
         onClick={e => e.stopPropagation()}>
      {row}
      {inst.region === 'IN' && alertOpen && <AlertForm inst={inst} layout="row" onClose={() => setAlertOpen(false)} />}
    </div>
  )
}
