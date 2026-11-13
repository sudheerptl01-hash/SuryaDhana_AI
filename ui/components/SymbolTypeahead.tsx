'use client'

/**
 * SymbolTypeahead (FINAL ROUND B-OSTR, WAVE_ORDERS §B-OSTR item 4): the F&O underlying picker as a
 * filter-as-you-type input over the same list the old 224-option control held — recent symbols first,
 * ↑/↓ to move, Enter selects the highlighted match (typing "BAN" + Enter picks BANKNIFTY in 3 keys),
 * Esc closes. Recents reuse the GO bar's classified SYNC key `suryadhana.cmd.recent.v1` (CommandBar's
 * recent-stocks list: string[], newest first, cap 8) — one recents concept terminal-wide, no new key; every
 * access wrapped in try/catch (the list renders fine without storage). Pure UI: no feed, no store, no order path.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { T } from '@/components/terminal'
import { Z } from '@/lib/z'

const RECENTS_KEY = 'suryadhana.cmd.recent.v1'
const RECENTS_MAX = 8
const LIST_MAX = 12

function readRecents(): string[] {
  try {
    const raw = localStorage.getItem(RECENTS_KEY)
    const arr = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(arr) ? arr.filter((s): s is string => typeof s === 'string').slice(0, RECENTS_MAX) : []
  } catch { return [] }
}

function writeRecent(sym: string): void {
  try {
    const next = [sym, ...readRecents().filter(s => s !== sym)].slice(0, RECENTS_MAX)
    localStorage.setItem(RECENTS_KEY, JSON.stringify(next))
  } catch { /* private window / blocked storage: recents are a convenience only */ }
}

/** Matches ranked: starts-with before contains, then alphabetical; the query is case-insensitive. */
export function rankMatches(options: readonly string[], query: string, recents: readonly string[], max = LIST_MAX): string[] {
  const q = query.trim().toUpperCase()
  const uniq = [...new Set(options.map(o => o.toUpperCase()))]
  if (!q) {
    const rec = recents.filter(r => uniq.includes(r))
    return [...rec, ...uniq.filter(o => !rec.includes(o))].slice(0, max)
  }
  const starts = uniq.filter(o => o.startsWith(q)).sort()
  const contains = uniq.filter(o => !o.startsWith(q) && o.includes(q)).sort()
  return [...starts, ...contains].slice(0, max)
}

export function SymbolTypeahead({ value, options, onPick, width = 148, 'aria-label': ariaLabel = 'underlying symbol' }: {
  value: string
  options: readonly string[]
  onPick: (symbol: string) => void
  width?: number
  'aria-label'?: string
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [hi, setHi] = useState(0)
  const [recents, setRecents] = useState<string[]>([])
  const boxRef = useRef<HTMLDivElement | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => { setRecents(readRecents()) }, [])
  const matches = useMemo(() => rankMatches(options, query, recents), [options, query, recents])
  useEffect(() => { setHi(0) }, [query, open])

  // click-away closes (the input keeps the picked value on its face while closed)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (boxRef.current && e.target instanceof Node && !boxRef.current.contains(e.target)) { setOpen(false); setQuery('') }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const pick = (sym: string) => {
    setOpen(false)
    setQuery('')
    writeRecent(sym)
    setRecents(r => [sym, ...r.filter(s => s !== sym)].slice(0, RECENTS_MAX))
    if (sym !== value) onPick(sym)
  }

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open && (e.key === 'ArrowDown' || e.key === 'Enter')) { setOpen(true); return }
    if (e.key === 'ArrowDown') { e.preventDefault(); setHi(h => Math.min(h + 1, matches.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi(h => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); if (matches[hi]) pick(matches[hi]) }
    else if (e.key === 'Escape') { setOpen(false); setQuery(''); inputRef.current?.blur() }
  }

  return (
    <div ref={boxRef} style={{ position: 'relative', width }} data-symbol-typeahead>
      <input
        ref={inputRef}
        value={open ? query : value}
        placeholder={value}
        aria-label={ariaLabel}
        role="combobox"
        aria-expanded={open}
        spellCheck={false}
        onFocus={() => setOpen(true)}
        onChange={e => { setOpen(true); setQuery(e.target.value.toUpperCase()) }}
        onKeyDown={onKey}
        style={{ width: '100%', boxSizing: 'border-box', fontFamily: T.mono, fontSize: 11, letterSpacing: 1,
                 padding: '5px 8px', background: T.panel2, color: T.text, border: `1px solid ${open ? T.amber : T.border}`,
                 outline: 'none', textTransform: 'uppercase' }} />
      {open && matches.length > 0 && (
        <div role="listbox" aria-label="matching underlyings"
          style={{ position: 'absolute', top: '100%', left: 0, right: 0, zIndex: Z.modal, marginTop: 2,
                   background: T.panel, border: `1px solid ${T.border}`, maxHeight: 264, overflowY: 'auto',
                   boxShadow: '0 8px 20px rgba(0,0,0,.45)' }}>
          {!query && recents.length > 0 && (
            <div style={{ fontFamily: T.mono, fontSize: 8.5, color: T.dim, letterSpacing: 1.2, padding: '4px 8px 2px' }}>RECENT FIRST</div>
          )}
          {matches.map((m, i) => (
            <div key={m} role="option" aria-selected={i === hi}
              onMouseDown={e => { e.preventDefault(); pick(m) }}
              onMouseEnter={() => setHi(i)}
              style={{ fontFamily: T.mono, fontSize: 11, letterSpacing: 1, padding: '5px 8px', cursor: 'pointer',
                       color: i === hi ? T.bg : m === value ? T.amber : T.text,
                       background: i === hi ? T.amber : 'transparent' }}>
              {m}{!query && recents.includes(m) && i < recents.length ? <span style={{ color: i === hi ? T.bg : T.dim, fontSize: 9 }}> · recent</span> : null}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
