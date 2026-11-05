'use client'

/**
 * NewsDock — the NEWS segment of the status line (footer), on every tab. Shows the latest
 * scan's date and pick count, and pulses amber when a scan file newer than the last one you
 * opened appears in new_scnner/. Click (or Shift+N) opens the News Catalyst Terminal.
 * Lives IN the footer row (no floating pill), so it never covers page content.
 * First visit on a device (no marker yet, e.g. the desktop app's new origin): the scans that already exist are
 * not new, so the dock does not pulse for a scan the owner already opened in the browser (C3-05). When the first
 * successful poll finds no scan at all, the marker starts at 0, so the first scan that appears later IS new and
 * pulses (round-1 leftover; the same rule as the alerts' SEEN_NOTHING).
 * The NEW pulse runs three times and then stays a steady amber dot (C2-performance-03: an endless pulse kept every
 * idle window repainting); a newer scan restarts it. prefers-reduced-motion: no pulse (globals.css .nd-dot-new).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { getNewsScans } from '@/lib/api'
import { NewsTerminal } from './NewsTerminal'
import type { ScanIndex } from './types'
import { T } from './format'
import { useDocumentHidden, usePolling } from '@/components/shell/usePoll'

const SEEN_KEY = 'newsTerminal.seenVersion'

export function NewsDock() {
  const [open, setOpen] = useState(false)
  const [index, setIndex] = useState<ScanIndex | null>(null)
  const [seen, setSeen] = useState<number>(0)
  const marked = useRef<boolean | null>(null)          // null = not read yet; false = no marker on this device

  useEffect(() => {
    try {
      const raw = localStorage.getItem(SEEN_KEY)
      marked.current = raw !== null
      setSeen(Number(raw || 0))
    } catch { marked.current = true /* storage unavailable: keep the old behaviour */ }
  }, [])

  const poll = useCallback(async () => {
    try {
      const d = (await getNewsScans()).data
      setIndex(d)
      if (marked.current === false && d) {   // first visit: what exists now is not news; no scan yet → 0
        const v = Number(d.latest_version) || 0
        marked.current = true
        setSeen(v)
        try { localStorage.setItem(SEEN_KEY, String(v)) } catch { /* storage unavailable */ }
      }
    } catch { /* backend restarting — retry next tick */ }
  }, [])

  // 60 s while the window is visible (unchanged), 5 min while it is hidden, at once when it is shown again
  // (R-UI-SHELL-06 / C-PERF-06: windows hidden to the menu bar no longer poll the chrome at the visible cadence)
  usePolling(poll, useDocumentHidden() ? 300_000 : 60_000)

  const openTerminal = useCallback(() => {
    setOpen(true)
    const v = index?.latest_version ?? 0
    marked.current = true
    setSeen(v)
    try { localStorage.setItem(SEEN_KEY, String(v)) } catch { /* storage unavailable */ }
  }, [index])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName
      if (e.shiftKey && (e.key === 'N' || e.key === 'n') && tag !== 'INPUT' && tag !== 'TEXTAREA') {
        e.preventDefault(); openTerminal()
      }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('suryadhana:open-news', openTerminal)      // fired by the command bar (NEWS <GO>)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('suryadhana:open-news', openTerminal)
    }
  }, [openTerminal])

  const latest = index?.scans[0]
  const isNew = !open && !!index?.latest_version && index.latest_version > seen
  const label = latest ? `${latest.date.replace(/(\d{4})(\d{2})(\d{2})/, '$3-$2')}` : '—'

  // one footer segment, three states: quiet · unread (amber pulse + count) · open (active)
  return (
    <>
      <button onClick={openTerminal}
        title={`News Catalyst Terminal (Shift+N) · latest scan ${label}${latest ? ` · ${latest.picks} picks` : ''}${isNew ? ' · NEW' : ''}`}
        style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '1px 7px', cursor: 'pointer',
                 background: open ? '#120e04' : 'none', font: 'inherit', letterSpacing: 'inherit',
                 border: `1px solid ${isNew || open ? `${T.amber}88` : 'transparent'}`, borderRadius: 2,
                 color: isNew ? T.text : T.muted }}>
        <span key={isNew ? `new-${index?.latest_version}` : 'quiet'} className={isNew ? 'nd-dot-new' : undefined}
              style={{ width: 6, height: 6, borderRadius: 3, background: isNew ? T.amber : T.green }} />
        <span style={{ color: T.amber, fontWeight: 700 }}>NEWS</span>
        <span>{label}</span>
        {latest && latest.picks >= 0 && (
          <span style={{ background: isNew ? T.amber : 'transparent', color: isNew ? T.bg : T.muted,
                         border: isNew ? 'none' : `1px solid ${T.border}`, fontWeight: 700, padding: '0 5px',
                         borderRadius: 2, lineHeight: '13px' }}>
            {latest.picks}
          </span>
        )}
        {isNew && <span style={{ color: T.amber, fontWeight: 700 }}>NEW</span>}
      </button>
      <NewsTerminal open={open} onClose={() => setOpen(false)} />
    </>
  )
}
