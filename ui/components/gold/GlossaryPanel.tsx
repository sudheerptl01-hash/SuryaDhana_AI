'use client'

/**
 * Glossary side panel (PLAN §e): a right-hand drawer with a search box, reachable from every dotted-underlined
 * `Term` and from the `?` of each panel; `see_also` entries are links inside the panel. Rendered inline by LEARN
 * (`<GlossaryPanel inline />`) and docked once per page by GoldPage (`<GlossaryPanel />`), which every B4B view's
 * `Term` reaches through the event below.
 *
 * Wave 1c (C-BEGINNER-10/11/17/22): while the search box is empty the "start here" dozen (troy ounce → real yield) is
 * pinned above the alphabet; the search matches G-EDU's `aliases` ("MM", "OI", "FND"); an alias list prints under the
 * term; the long line prints only when it says more than the short one; Escape closes the dock.
 *
 * Opening is an event (`GLOSSARY_EVENT`) so any view can call `openGlossary(term)` without a context. The bundled
 * `ui/lib/gold/glossary.json` is the source of truth (copied from G-EDU, cross-references validated by the node
 * check); the server copy (`/api/gold/learn/glossary`) is the same file served by B3, so no fetch is needed here.
 */
import { useEffect, useMemo, useState } from 'react'
import { Chip, Input, Label, T } from '@/components/terminal'
import { Z } from '@/lib/z'
import glossaryJson from '@/lib/gold/glossary.json'
import { indexGlossary, longIfDifferent, lookupTerm, searchGlossary, startHereEntries, type GlossaryEntry } from '@/lib/gold/learn'

export const GLOSSARY_EVENT = 'suryadhana:gold-glossary'
const TERMS = (glossaryJson as { terms: GlossaryEntry[] }).terms
const INDEX = indexGlossary(TERMS)
const START = startHereEntries(INDEX)
export const GLOSSARY_COUNT = TERMS.length

/** Open the glossary on `term` (or just open it when no term). */
export function openGlossary(term?: string): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent<string | undefined>(GLOSSARY_EVENT, { detail: term }))
}

function Entry({ e, onPick }: { e: GlossaryEntry; onPick: (t: string) => void }) {
  const long = longIfDifferent(e)
  return (
    <div data-glossary-term={e.term} style={{ padding: '8px 0', borderBottom: `1px solid ${T.border}` }}>
      <div style={{ fontFamily: T.display, fontSize: 13, fontWeight: 600, color: T.amber, letterSpacing: .6 }}>
        {e.term}
        {e.aliases && e.aliases.length > 0 && <span data-glossary-aliases style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 400, color: T.dim, letterSpacing: 0, marginLeft: 6 }}>also {e.aliases.join(' · ')}</span>}
      </div>
      <div style={{ fontSize: 12, color: T.text, lineHeight: 1.5, marginTop: 2 }}>{e.short}</div>
      {long && <div data-glossary-long style={{ fontSize: 11, color: T.muted, lineHeight: 1.5, marginTop: 4 }}>{long}</div>}
      {e.see_also && e.see_also.length > 0 && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
          <span style={{ fontSize: 9, color: T.dim, alignSelf: 'center' }}>see also</span>
          {e.see_also.map(s => <Chip key={s} color={T.cyan} onClick={() => onPick(s)} style={{ fontSize: 9 }}>{s}</Chip>)}
        </div>
      )}
    </div>
  )
}

export function GlossaryPanel({ inline = false }: { inline?: boolean }) {
  const [open, setOpen] = useState(inline)
  const [q, setQ] = useState('')
  const [focus, setFocus] = useState<string | null>(null)
  useEffect(() => {
    const on = (ev: Event) => {
      const term = (ev as CustomEvent<string | undefined>).detail
      setOpen(true)
      if (term) { setFocus(lookupTerm(INDEX, term)?.term ?? term); setQ('') }
    }
    window.addEventListener(GLOSSARY_EVENT, on)
    return () => window.removeEventListener(GLOSSARY_EVENT, on)
  }, [])
  // Escape closes the dock (C-BEGINNER-22); the inline LEARN copy has nothing to close
  useEffect(() => {
    if (inline || !open) return
    const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [inline, open])
  const results = useMemo(() => searchGlossary(TERMS, q, q ? 40 : TERMS.length), [q])
  const focused = focus ? lookupTerm(INDEX, focus) : undefined
  // a clicked term sits first; the start-here dozen sits above the alphabet whenever the box is empty (also in the dock
  // after a term click, so "4GC" is never the second entry — C-BEGINNER-10)
  const pinned = !q ? START.filter(e => e.term !== focused?.term) : []
  const list = focused && !q ? [focused, ...results.filter(r => r.term !== focused.term)] : results
  const rest = pinned.length ? list.filter(e => !pinned.includes(e)) : list
  if (!open) return null
  const body = (
    <>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Label color={T.amber}>Glossary · {TERMS.length} terms</Label>
        <span style={{ flex: 1 }} />
        {!inline && <Chip color={T.muted} onClick={() => setOpen(false)} aria-label="close glossary" title="close (Esc)">✕</Chip>}
      </div>
      <Input value={q} onChange={v => { setQ(v); if (v) setFocus(null) }} placeholder="search a term or a shorthand (MM, OI, FND, w/w, bp)" aria-label="glossary search" />
      <div style={{ overflowY: 'auto', marginTop: 6, maxHeight: inline ? 560 : 'calc(100vh - 110px)' }}>
        {list.length === 0 && <div style={{ color: T.dim, fontSize: 11, padding: 8 }}>no term matches “{q}”</div>}
        {focused && !q && <Entry key={`focus-${focused.term}`} e={focused} onPick={t => { setFocus(t); setQ('') }} />}
        {pinned.length > 0 && (
          <div data-glossary-start-here>
            <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1, color: T.cyan, textTransform: 'uppercase', padding: '4px 0' }}>start here · {pinned.length} terms in reading order</div>
            {pinned.map(e => <Entry key={`start-${e.term}`} e={e} onPick={t => { setFocus(t); setQ('') }} />)}
            <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1, color: T.dim, textTransform: 'uppercase', padding: '8px 0 4px' }}>all terms, A–Z</div>
          </div>
        )}
        {rest.filter(e => !(focused && !q && e.term === focused.term)).map(e => <Entry key={e.term} e={e} onPick={t => { setFocus(t); setQ('') }} />)}
      </div>
    </>
  )
  if (inline) return <div data-glossary-inline style={{ border: `1px solid ${T.border}`, background: T.panel, padding: 10 }}>{body}</div>
  return (
    <aside data-glossary-dock role="complementary" aria-label="Gold glossary"
      style={{ position: 'fixed', top: 0, right: 0, bottom: 0, width: 360, maxWidth: '92vw', zIndex: Z.overlay, background: T.panel,
               borderLeft: `1px solid ${T.borderHi}`, boxShadow: '-8px 0 24px rgba(0,0,0,.55)', padding: 12, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {body}
    </aside>
  )
}
