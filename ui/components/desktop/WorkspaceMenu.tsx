'use client'

/**
 * WorkspaceMenu (FINAL ROUND R2): the compact header menu for saved workspaces/layouts — the mouse half of GO's
 * `LAYOUT SAVE <name>` / `LAYOUT <name>` / `LAYOUT LIST` (lib/workspaces.ts). It sits in the page strip's sticky
 * end (MarketCommandHeader), styled like RESEARCH ▾ / MORE ▾.
 *
 * A row loads its workspace (strip order, active symbol, sub-view, then the page switch); ✕ asks once (SURE?) and
 * removes it; the bottom row saves the CURRENT layout under a typed name (replaces a same-named one; max 8). The
 * list lives in the SYNC prefs key `suryadhana.workspaces.v1`, so every window, the app and every browser share it;
 * the menu re-reads on WORKSPACES_EVENT (this window) and on another window's / the server's write
 * (lib/prefs/useExternalChange). A workspace stores layout only — never credentials or book contents.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Z } from '@/lib/z'
import { T } from '@/components/terminal'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { MAX_WORKSPACES, WORKSPACES_EVENT, WORKSPACES_KEY, describeWorkspace, loadWorkspace, normalizeWorkspaceName,
  readWorkspaces, removeWorkspace, saveCurrentWorkspace, writeWorkspaces, type Workspace } from '@/lib/workspaces'
import { PAGE_META } from '@/components/desktop/pages'

const codeOf = (id: string): string => PAGE_META[id]?.code ?? id.toUpperCase()

export function WorkspaceMenu({ active, onPage }: { active: string; onPage: (id: string) => void }) {
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<{ top: number; right: number }>({ top: 0, right: 0 })
  const [list, setList] = useState<Workspace[]>([])
  const [name, setName] = useState('')
  const [sure, setSure] = useState<string | null>(null)
  const btn = useRef<HTMLButtonElement>(null)
  const reload = useCallback(() => setList(readWorkspaces()), [])
  useEffect(() => {
    reload()
    window.addEventListener(WORKSPACES_EVENT, reload)
    return () => window.removeEventListener(WORKSPACES_EVENT, reload)
  }, [reload])
  useExternalPrefChange(WORKSPACES_KEY, reload)
  useEffect(() => {
    if (!open) return
    setSure(null)
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === 'Escape' : !(e.target as HTMLElement).closest('[data-ws-menu]')) setOpen(false)
    }
    window.addEventListener('mousedown', close); window.addEventListener('keydown', close)
    return () => { window.removeEventListener('mousedown', close); window.removeEventListener('keydown', close) }
  }, [open])
  const toggle = () => {
    const r = btn.current?.getBoundingClientRect()
    if (r) setAt({ top: r.bottom, right: Math.max(8, window.innerWidth - r.right) })
    setOpen(o => !o)
  }
  const known = Object.keys(PAGE_META)
  const normalized = normalizeWorkspaceName(name)
  const replacing = !!(normalized && list.some(w => w.name === normalized))
  const canSave = !!normalized && (replacing || list.length < MAX_WORKSPACES)
  const save = () => {
    if (!normalized || !canSave) return
    const r = saveCurrentWorkspace(normalized, active, known)
    if (r.ok) setName('')
  }
  const load = (w: Workspace) => {
    const page = loadWorkspace(w, known)
    setOpen(false)
    if (page) onPage(page)
  }
  const del = (w: Workspace) => {
    if (sure !== w.name) { setSure(w.name); return }
    writeWorkspaces(removeWorkspace(list, w.name))
    setSure(null)
  }
  return (
    <>
      <button ref={btn} data-ws-menu onClick={toggle} aria-expanded={open} className="sd-pstrip-tab"
        title={`Saved workspaces: strip + page + symbol + view (${list.length}/${MAX_WORKSPACES}) · LAYOUT SAVE <name> on GO`}
        style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 10px', flex: 'none',
                 background: '#0b0f16', border: 'none', borderLeft: `1px solid ${T.borderHi}`, cursor: 'pointer' }}>
        <span style={{ fontFamily: T.display, fontSize: 11, fontWeight: 700, letterSpacing: 1, color: T.cyan }}>⊞ LAYOUT ▾</span>
      </button>
      {open && (
        <div data-ws-menu role="menu" aria-label="Saved workspaces"
          style={{ position: 'fixed', top: at.top, right: at.right, zIndex: Z.dropdown, width: 'min(380px, calc(100vw - 16px))',
                   maxHeight: 'calc(100vh - 140px)', overflowY: 'auto', background: '#0b0f16', fontFamily: T.mono,
                   border: `1px solid ${T.borderHi}`, boxShadow: '0 12px 32px rgba(0,0,0,.6)', padding: '4px 0' }}>
          <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, padding: '6px 12px' }}>
            WORKSPACES {list.length}/{MAX_WORKSPACES} · LAYOUT ‹NAME› ON GO LOADS ONE
          </div>
          {list.length === 0 && (
            <div style={{ padding: '6px 12px 8px', fontSize: 11, color: T.muted, lineHeight: 1.5 }}>
              None saved yet. A workspace is a named layout: the strip order, the page you are on, its symbol and
              sub-view. Save the current one below, or type LAYOUT SAVE ‹NAME› in GO.
            </div>
          )}
          {list.map(w => (
            <div key={w.name} data-ws-row={w.name} style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'center', gap: 6, padding: '0 12px' }}>
              <button role="menuitem" className="sd-menu-row" onClick={() => load(w)} title={`Load ${w.name} (GO: LAYOUT ${w.name})`}
                style={{ display: 'block', textAlign: 'left', padding: '6px 0', background: 'transparent', border: 'none', cursor: 'pointer', minWidth: 0 }}>
                <span style={{ fontSize: 11, fontWeight: 700, color: T.amber, letterSpacing: .5 }}>{w.name}</span>
                <span style={{ display: 'block', fontSize: 10, color: T.dim, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {describeWorkspace(w, codeOf)}
                </span>
              </button>
              <button type="button" aria-label={`Remove workspace ${w.name}`} onClick={() => del(w)}
                title={sure === w.name ? 'Click again to remove' : `Remove ${w.name}`}
                style={{ fontFamily: T.mono, fontSize: 10, color: sure === w.name ? T.amber : T.muted, background: 'transparent',
                         border: `1px solid ${sure === w.name ? T.amber : T.border}`, padding: '2px 7px', cursor: 'pointer', flex: 'none' }}>
                {sure === w.name ? 'SURE?' : '✕'}
              </button>
            </div>
          ))}
          <div style={{ borderTop: `1px solid ${T.border}`, margin: '4px 0' }} />
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', padding: '6px 12px 8px' }}>
            <input value={name} onChange={e => setName(e.target.value)} spellCheck={false} aria-label="Workspace name"
              placeholder="name this layout…" maxLength={20}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); save() } e.stopPropagation() }}
              style={{ flex: 1, minWidth: 0, fontFamily: T.mono, fontSize: 11, background: '#080b10', color: T.text,
                       border: `1px solid ${T.border}`, padding: '4px 6px', textTransform: name ? 'uppercase' : 'none' }} />
            <button type="button" disabled={!canSave} onClick={save}
              title={!normalized ? 'A name is 1–20 letters, digits, spaces, . _ -'
                : replacing ? `Replaces the saved ${normalized}` : `Saves the current layout (${codeOf(active)}) as ${normalized}`}
              style={{ fontFamily: T.mono, fontSize: 10, fontWeight: 700, letterSpacing: 1, color: canSave ? T.bg : T.dim,
                       background: canSave ? T.cyan : 'transparent', border: `1px solid ${canSave ? T.cyan : T.border}`,
                       padding: '4px 9px', cursor: canSave ? 'pointer' : 'not-allowed', flex: 'none' }}>
              {replacing ? 'REPLACE' : 'SAVE'}
            </button>
          </div>
          {!canSave && !!name && !normalized && (
            <div style={{ padding: '0 12px 8px', fontSize: 10, color: T.muted }}>1–20 letters, digits, spaces, . _ - (SAVE / LIST are reserved)</div>
          )}
          {!canSave && !!normalized && (
            <div style={{ padding: '0 12px 8px', fontSize: 10, color: T.muted }}>{MAX_WORKSPACES} saved: reuse a name to replace it, or remove one above</div>
          )}
        </div>
      )}
    </>
  )
}
