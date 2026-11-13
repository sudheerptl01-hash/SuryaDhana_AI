'use client'

/**
 * In-app settings import (page review 5 Nov 2026, M35 / m004): replaces the permanent "watchlist and pins not imported
 * yet" banner with
 *   - a ONE-TIME toast (bottom right, never in the page flow, so BRF's first row is no longer pushed down), and
 *   - an import dialog, also reachable from GO (`IMPORT` / `SETTINGS`) and MORE ▾ for as long as the server proves
 *     nothing was imported.
 * The dialog's START asks ui-api for a one-shot page on the old terminal's address (routers/prefs.py
 * POST /api/prefs/legacy-import). The owner opens that link in the browser used before; the page reads the same SYNC
 * keys the sync code's legacy import reads and imports them on the owner's click there, fill-only (a value set in the
 * app is never replaced). This window then re-reads the server (refetchPrefsNow) and the pages pick the values up.
 * Logic and wording: lib/prefs/legacyImport.ts (pure, unit-tested by desktop.check.ts).
 */
import { Z } from '@/lib/z'
import { useCallback, useEffect, useRef, useState } from 'react'
import { T } from '@/components/terminal'
import { useToast } from '@/context/ToastContext'
import { useShellState } from '@/components/shell/ShellState'
import { MIGRATE_NOTICE_KEY } from '@/lib/prefs/migration'
import { PREFS_SERVER_EVENT, prefsServerInfo, prefsSyncStatus, refetchPrefsNow } from '@/lib/prefs/sync'
import { OFFER_KEY, OPEN_IMPORT_EVENT, importKeys, importOffer, importStatusText, offerText, parseImportStatus, type ImportPageStatus } from '@/lib/prefs/legacyImport'

const API = '/api/prefs/legacy-import'

/** A ui-api from before the in-app import answers 404 / 405 on its route: say so, not a bare status code. */
const notOffered = (status: number) => (status === 404 || status === 405
  ? 'this ui-api predates the in-app import (it arrives with the next ui-api restart); until then RUNBOOK §8 works'
  : `HTTP ${status}`)

function readLocal(k: string): string | null {
  try { return window.localStorage.getItem(k) } catch { return null }
}
function writeLocal(k: string, v: string): void {
  try { window.localStorage.setItem(k, v) } catch { /* storage blocked */ }
}

/** Hide the old docked banner for good on this origin: this toast + dialog replace it (PlatformShell re-reads on 'storage'). */
function retireOldBanner(): void {
  const cur = readLocal(MIGRATE_NOTICE_KEY)
  if (cur === 'dismissed' || cur === 'imported') return
  writeLocal(MIGRATE_NOTICE_KEY, 'dismissed')
  try { window.dispatchEvent(new StorageEvent('storage', { key: MIGRATE_NOTICE_KEY })) } catch { /* no StorageEvent */ }
}

/** The offer state, re-evaluated after every server read. 'none' | 'toast' | 'quiet'. */
export function useImportOffer(): { offer: 'toast' | 'quiet' | 'none'; proven: boolean } {
  const [s, setS] = useState<{ offer: 'toast' | 'quiet' | 'none'; proven: boolean }>({ offer: 'none', proven: false })
  useEffect(() => {
    const evaluate = () => {
      const server = prefsServerInfo()
      const offer = importOffer({ pageOrigin: window.location.origin, mode: prefsSyncStatus()?.mode ?? 'off', offerMarker: readLocal(OFFER_KEY), server })
      if (offer !== 'none') retireOldBanner()
      setS({ offer, proven: !!server?.legacyImport && server.legacyImport.at == null })
    }
    evaluate()
    window.addEventListener(PREFS_SERVER_EVENT, evaluate)
    return () => window.removeEventListener(PREFS_SERVER_EVENT, evaluate)
  }, [])
  return s
}

export function openSettingsImport(): void {
  try { window.dispatchEvent(new Event(OPEN_IMPORT_EVENT)) } catch { /* no DOM */ }
}

export function SettingsImport() {
  const { offer, proven } = useImportOffer()
  const [toast, setToast] = useState(false)
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (offer !== 'toast') return
    setToast(true)
    writeLocal(OFFER_KEY, 'seen')                  // one time: GO IMPORT and MORE ▾ stay afterwards
    const id = setTimeout(() => setToast(false), 30_000)
    return () => clearTimeout(id)
  }, [offer])
  useEffect(() => {
    const on = () => { setToast(false); setOpen(true) }
    window.addEventListener(OPEN_IMPORT_EVENT, on)
    return () => window.removeEventListener(OPEN_IMPORT_EVENT, on)
  }, [])
  return (
    <>
      {toast && !open && (
        <div role="status" aria-live="polite" data-sd-import-offer=""
          style={{ position: 'fixed', right: 14, bottom: 32, zIndex: Z.toast, maxWidth: 'min(420px, calc(100vw - 28px))', display: 'flex',
                   alignItems: 'stretch', background: '#0b0f16', border: `1px solid ${T.borderHi}`, borderLeft: `3px solid ${T.amber}`,
                   boxShadow: '0 12px 32px rgba(0,0,0,.6)', fontFamily: T.mono, fontSize: 11 }}>
          <div style={{ padding: '8px 10px', color: T.text, lineHeight: 1.45 }}>
            <span style={{ color: T.amber, fontWeight: 700, letterSpacing: 1.2 }}>SETTINGS · </span>{offerText(proven)}
            <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
              <button type="button" onClick={() => { setToast(false); setOpen(true) }} className="sd-tap"
                style={{ font: 'inherit', fontWeight: 700, letterSpacing: 1.1, color: T.bg, background: T.amber, border: 'none', padding: '4px 10px', cursor: 'pointer' }}>
                IMPORT…</button>
              <button type="button" onClick={() => setToast(false)} className="sd-tap"
                style={{ font: 'inherit', letterSpacing: 1.1, color: T.muted, background: 'transparent', border: `1px solid ${T.border}`, padding: '4px 10px', cursor: 'pointer' }}
                title="Later: GO IMPORT or MORE ▾ open it again">LATER</button>
            </div>
          </div>
        </div>
      )}
      {open && <ImportDialog onClose={() => setOpen(false)} />}
    </>
  )
}

function ImportDialog({ onClose }: { onClose: () => void }) {
  const { desktop } = useShellState()
  const { addToast } = useToast()
  const [st, setSt] = useState<ImportPageStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState(false)
  const alive = useRef(true)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const announced = useRef(false)

  const read = useCallback(async () => {
    try {
      const r = await fetch(API, { cache: 'no-store' })
      const s = parseImportStatus(r.ok ? await r.json() : { state: 'failed', detail: notOffered(r.status) })
      if (alive.current) setSt(s)
      return s
    } catch {
      return null
    }
  }, [])
  useEffect(() => { void read() }, [read])
  // poll while the page waits for the other browser; on done, re-read the prefs so this window has the values
  useEffect(() => {
    if (st?.state !== 'waiting') return
    const id = setInterval(() => { void read() }, 2000)
    return () => clearInterval(id)
  }, [st?.state, read])
  useEffect(() => {
    if (st?.state !== 'done' || announced.current) return
    announced.current = true
    void refetchPrefsNow()
    if (st.imported.length) addToast(`Settings imported: ${st.imported.length} from the old browser terminal`, 'success', 8000)
  }, [st, addToast])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); onClose() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const start = async () => {
    setBusy(true)
    try {
      const r = await fetch(API, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ keys: importKeys() }) })
      const body = await r.json().catch(() => ({}))
      if (alive.current) setSt(parseImportStatus(r.ok || r.status === 409 ? body : { state: 'failed', detail: notOffered(r.status) }))
    } catch (e) {
      if (alive.current) setSt(parseImportStatus({ state: 'failed', detail: e instanceof Error ? e.message : 'network error' }))
    } finally {
      if (alive.current) setBusy(false)
    }
  }
  const stop = async () => {
    try { await fetch(`${API}/stop`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }) } catch { /* next read says */ }
    void read()
  }
  const copy = async (url: string) => {
    try { await navigator.clipboard.writeText(url); setCopied(true); setTimeout(() => setCopied(false), 2500) } catch { setCopied(false) }
  }
  const btn = (c: string, solid = false) => ({ fontFamily: T.mono, fontSize: 11, fontWeight: 700, letterSpacing: 1.2, color: solid ? T.bg : c,
    background: solid ? c : 'transparent', border: `1px solid ${c}`, padding: '6px 12px', cursor: 'pointer' } as const)
  const waiting = st?.state === 'waiting' && st.url
  return (
    <div onMouseDown={onClose} role="dialog" aria-label="Import settings" data-sd-import-dialog=""
      style={{ position: 'fixed', inset: 0, zIndex: Z.commandbar, background: 'rgba(2,3,6,.72)', display: 'flex', justifyContent: 'center',
               alignItems: 'flex-start', paddingTop: '10vh' }}>
      <div onMouseDown={e => e.stopPropagation()} className="t-fade-up"
        style={{ width: 'min(640px, 94vw)', background: T.panel, border: `1px solid ${T.borderHi}`, borderTop: `2px solid ${T.amber}`,
                 boxShadow: '0 24px 80px rgba(0,0,0,.6)', fontFamily: T.mono, color: T.text, maxHeight: '84vh', overflowY: 'auto' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px', borderBottom: `1px solid ${T.border}` }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: T.bg, background: T.amber, padding: '3px 7px' }}>SETTINGS</span>
          <span style={{ fontFamily: T.display, fontSize: 13, fontWeight: 700, letterSpacing: 1.4, color: T.bright }}>IMPORT FROM THE OLD BROWSER TERMINAL</span>
          <span style={{ flex: 1 }} />
          <button type="button" onClick={onClose} aria-label="Close" style={{ ...btn(T.muted), padding: '2px 8px', fontWeight: 400 }}>ESC</button>
        </div>
        <div style={{ padding: '12px 14px', fontSize: 12, lineHeight: 1.6 }}>
          <p style={{ margin: 0, color: T.muted }}>
            Your watchlist, pins and page settings from before the app live only in the browser that opened
            http://localhost:3000. START opens a one-time import page on that address (served by ui-api for 10 minutes; no
            dev server). Open its link in that browser and click IMPORT there: only settings you have not set in the app are
            filled, nothing you set here is replaced.
          </p>
          <div style={{ marginTop: 10, color: st?.state === 'done' ? T.green : st?.state === 'failed' || st?.state === 'port_busy' ? T.amber : T.text }}
            data-sd-import-state={st?.state ?? 'loading'}>
            {st ? importStatusText(st, Date.now()) : 'Reading the import state…'}
          </div>
          {waiting && (
            <div style={{ marginTop: 10, padding: '8px 10px', border: `1px solid ${T.border}`, background: '#080b10' }}>
              <div style={{ fontSize: 10, letterSpacing: 1.2, color: T.dim }}>OPEN IN THE BROWSER YOU USED BEFORE</div>
              <div style={{ marginTop: 4, color: T.amber, wordBreak: 'break-all', userSelect: 'all', WebkitUserSelect: 'all' }}>{st!.url}</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                <button type="button" className="sd-tap" onClick={() => void copy(st!.url!)} style={btn(T.amber, true)}>{copied ? '✓ COPIED' : 'COPY LINK'}</button>
                {/* the app never opens loopback URLs in a browser (desktop policy): copy + paste there; a browser window can open it */}
                {!desktop && <button type="button" className="sd-tap" onClick={() => { window.open(st!.url!, '_blank', 'noopener') }} style={btn(T.cyan)}>OPEN IN THIS BROWSER</button>}
                <button type="button" className="sd-tap" onClick={() => void stop()} style={btn(T.muted)}>STOP</button>
              </div>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 12, justifyContent: 'flex-end' }}>
            {!waiting && st?.state !== 'done' && (
              <button type="button" className="sd-tap" data-sd-import-start="" disabled={busy} onClick={() => void start()}
                style={{ ...btn(T.amber, true), opacity: busy ? 0.6 : 1, cursor: busy ? 'wait' : 'pointer' }}>
                {busy ? 'STARTING…' : st && ['expired', 'stopped', 'closed', 'port_busy'].includes(st.state) ? '↻ START AGAIN' : 'START THE IMPORT PAGE'}</button>
            )}
            <button type="button" className="sd-tap" onClick={onClose} style={btn(T.muted)}>CLOSE</button>
          </div>
        </div>
      </div>
    </div>
  )
}
