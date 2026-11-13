'use client'

/**
 * Header bell: the notifications the scheduler sent (price alerts, holdings moves, filings by your stocks, the nightly
 * wrap), so a Mac notification that was dismissed is not lost. Unread = newer than the last time the list was opened
 * in this browser. Polls every 60 s. First visit on a device (no marker yet, e.g. the desktop app's new origin):
 * what the feed already holds counts as read, so it does not show up to 30 old items as unread (C3-05).
 */
import { Z } from '@/lib/z'
import { useEffect, useRef, useState } from 'react'
import { getNotificationFeed, type NotificationItem } from '@/lib/api'
import { initialSeen } from '@/lib/alertText'
import { T } from '@/components/terminal'
import { goToPage } from '@/lib/navigate'
import { BellGlyph } from '@/components/shell/Glyphs'

const SEEN_KEY = 'suryadhana.inbox.seen.v1'
const KIND_COLOR: Record<string, string> = { price: T.amber, move: T.cyan, filing: T.violet, wrap: T.green, results: T.green, close: T.cyan, morning: T.amber }

export function AlertsBell() {
  const [items, setItems] = useState<NotificationItem[]>([])
  const [open, setOpen] = useState(false)
  const [seen, setSeen] = useState<string>(() => { try { return localStorage.getItem(SEEN_KEY) ?? '' } catch { return '' } })
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const get = () => getNotificationFeed(30).then(r => {
      const list = r.data.items
      setItems(list)
      setSeen(cur => {
        if (cur) return cur
        const at = initialSeen(cur, list[0]?.at)
        try { localStorage.setItem(SEEN_KEY, at) } catch { /* private window: this page still remembers */ }
        return at
      })
    }).catch(() => {})
    get(); const iv = setInterval(get, 60_000); return () => clearInterval(iv)
  }, [])
  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false) }
    window.addEventListener('mousedown', close)
    return () => window.removeEventListener('mousedown', close)
  }, [open])
  const unread = items.filter(i => i.at > seen).length
  const toggle = () => {
    if (!open && items[0]) { try { localStorage.setItem(SEEN_KEY, items[0].at) } catch { /* private window */ } ; setSeen(items[0].at) }
    setOpen(o => !o)
  }
  return (
    <div ref={box} style={{ position: 'relative' }}>
      <button onClick={toggle} title="Notifications sent by the scheduler"
        style={{ background: 'transparent', border: `1px solid ${unread ? T.amber : T.border}`, color: unread ? T.amber : T.muted,
                 fontFamily: T.mono, fontSize: 10, padding: '4px 8px', cursor: 'pointer', letterSpacing: 1,
                 display: 'inline-flex', alignItems: 'center', gap: 4 }}
        aria-label={unread ? `Notifications: ${unread} unread` : 'Notifications'}>
        <BellGlyph size={11} />{unread ? ` ${unread}` : ''}
      </button>
      {open && (
        <div style={{ position: 'absolute', right: 0, top: 30, width: 420, maxHeight: 460, overflowY: 'auto', zIndex: Z.dropdown, background: '#0b0f16',
                      border: `1px solid ${T.borderHi}`, boxShadow: '0 12px 32px rgba(0,0,0,.6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 9, color: T.dim, letterSpacing: 1, padding: '7px 12px', borderBottom: `1px solid ${T.border}` }}>
            <span>NOTIFICATIONS · notes, alerts, moves, filings, results, the nightly wrap</span>
            <span role="button" onClick={() => { setOpen(false); goToPage('alerts') }} style={{ color: T.cyan, cursor: 'pointer', whiteSpace: 'nowrap' }}>ALL · ALRT ›</span>
          </div>
          {items.length === 0 && <div style={{ padding: 14, fontSize: 11, color: T.dim }}>Nothing sent yet.</div>}
          {items.map((i, k) => (
            <div key={`${i.at}-${k}`} style={{ padding: '7px 12px', borderBottom: `1px solid ${T.border}`, fontSize: 11 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ color: KIND_COLOR[i.kind] ?? T.text, fontSize: 10, letterSpacing: 0.8 }}>{i.kind.toUpperCase()}</span>
                <span style={{ color: T.dim, fontSize: 10 }}>{new Date(i.at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })}</span>
              </div>
              <div style={{ color: T.text, marginTop: 2 }}>{i.body}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
