'use client'

/**
 * Find on page for SuryaDhana.app (R9): ⌘F opens a small bar above the status line; typing finds as you type,
 * ↵ / ⌘G next, ⇧↵ / ⇧⌘G previous, Esc (or ✕) closes it. Mounted by PlatformShell in the app only: a browser keeps
 * its own ⌘F. Pure rules: ./find.ts.
 *
 * Mechanics: window.find() (WebKit and Chromium) selects and scrolls to the match. The selection is then copied into a
 * CSS highlight ('sd-find', globals.css) and focus goes back to the bar's input, because typing while the document
 * selection sits in page text inserts nothing. The bar's own labels are CSS-generated content, so a search never
 * matches the bar itself. role="search", not "dialog": type-to-GO and the stock window's Esc keep working.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Z } from '@/lib/z'
import { countMatches, findShortcut, findStatus } from './find'

type WinFind = (q: string, caseSensitive: boolean, backwards: boolean, wrap: boolean, word: boolean, frames: boolean, dialog: boolean) => boolean

interface HighlightApi {
  highlights?: { set(name: string, h: unknown): void; delete(name: string): void }
}

function setHighlight(range: Range | null): void {
  try {
    const css = (globalThis as unknown as { CSS?: HighlightApi }).CSS
    const H = (globalThis as unknown as { Highlight?: new (...r: Range[]) => unknown }).Highlight
    if (!css?.highlights || !H) return
    if (range) css.highlights.set('sd-find', new H(range))
    else css.highlights.delete('sd-find')
  } catch { /* no highlight API: the scroll still shows the match */ }
}

export function FindBar() {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [found, setFound] = useState<boolean | null>(null)
  const [count, setCount] = useState(0)
  const input = useRef<HTMLInputElement>(null)
  const bar = useRef<HTMLDivElement>(null)
  const match = useRef<Range | null>(null)
  const qRef = useRef(q)
  qRef.current = q
  const openRef = useRef(open)
  openRef.current = open

  const refocus = useCallback(() => {
    const el = input.current
    if (!el) return
    el.focus({ preventScroll: true })
    const n = el.value.length
    try { el.setSelectionRange(n, n) } catch { /* not a text input */ }
  }, [])

  /** Find `query` from the current match: `again` = the next / previous one, else (typing) the first from here. */
  const run = useCallback((query: string, backwards: boolean, again: boolean) => {
    const find = (window as unknown as { find?: WinFind }).find
    if (!query || typeof find !== 'function') { setFound(null); setHighlight(null); match.current = null; return }
    const sel = window.getSelection()
    try {
      if (sel) {
        const prev = match.current
        sel.removeAllRanges()
        if (prev && prev.startContainer.isConnected) {
          sel.addRange(prev)
          if (again) { if (backwards) sel.collapseToStart(); else sel.collapseToEnd() } else sel.collapseToStart()
        } else {
          sel.collapse(document.body, 0)
        }
      }
    } catch { /* a detached range: find starts from the top */ }
    let ok = false
    try { ok = find.call(window, query, false, backwards, true, false, false, false) } catch { ok = false }
    const r = ok && sel && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null
    // a "match" inside the bar itself (never expected: its labels are CSS content) does not count
    const inBar = !!(r && bar.current?.contains(r.startContainer))
    match.current = inBar ? null : r
    setHighlight(inBar ? null : r)
    setFound(ok && !inBar)
    try { setCount(countMatches(document.body.innerText || '', query)) } catch { setCount(0) }
    refocus()
  }, [refocus])

  const close = useCallback(() => {
    setOpen(false)
    setHighlight(null)
    match.current = null
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const act = findShortcut(e)
      if (!act) return
      e.preventDefault()
      if (act === 'open') {
        setOpen(true)
        requestAnimationFrame(() => { input.current?.focus({ preventScroll: true }); input.current?.select() })
        return
      }
      if (!qRef.current) { setOpen(true); requestAnimationFrame(() => input.current?.focus({ preventScroll: true })); return }
      if (!openRef.current) setOpen(true)
      run(qRef.current, act === 'prev', true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [run])

  useEffect(() => () => setHighlight(null), [])

  if (!open) return null
  const status = findStatus(q, found, count)
  return (
    <div ref={bar} role="search" aria-label="Find on this page" data-sd-find="" className="sd-find" style={{ zIndex: Z.toast }}>
      <span className="sd-find-tag" aria-hidden />
      <input ref={input} value={q} spellCheck={false} autoComplete="off" placeholder="Find on this page" aria-label="Find on this page"
        onChange={e => { setQ(e.target.value); run(e.target.value, false, false) }}
        onKeyDown={e => {
          if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return }
          if (e.key === 'Enter') { e.preventDefault(); run(q, e.shiftKey, true) }
        }} />
      <span className="sd-find-status" data-status={status} data-tone={found === false ? 'none' : 'ok'} aria-live="polite" aria-label={status || undefined} />
      <button type="button" className="sd-find-btn" data-glyph="↑" aria-label="Previous match (⇧⌘G)" title="Previous match (⇧⌘G)"
        onClick={() => run(q, true, true)} />
      <button type="button" className="sd-find-btn" data-glyph="↓" aria-label="Next match (⌘G)" title="Next match (⌘G)"
        onClick={() => run(q, false, true)} />
      <button type="button" className="sd-find-btn" data-glyph="✕" aria-label="Close find (Esc)" title="Close (Esc)" onClick={close} />
    </div>
  )
}
