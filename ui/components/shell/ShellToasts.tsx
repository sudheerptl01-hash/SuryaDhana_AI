'use client'

/**
 * Window-event toasts that must render INSIDE ToastProvider (app/page.tsx mounts them next to <ErrorCatcher/>;
 * PlatformShell sits outside the provider, where useToast() would throw).
 *
 *  - DownloadToasts (R8): in SuryaDhana.app an export is saved by the shell into ~/Downloads and reported with the
 *    'suryadhana:download' event; notifications may be denied, so the page says "Saved to ~/Downloads/<file> · ⌥⌘L"
 *    or why the save was refused (rate cap, size, a failed fetch). Browser downloads fire no event: unchanged.
 *  - AlertSaveToasts (P11): a price-alert save that did not reach the server (lib/alerts.ts) says so, instead of the
 *    form closing as if it had worked.
 *  - WorkspaceSaveToasts (R3-NITS, F2-TRADER): LAYOUT SAVE confirms itself in a toast — the only confirmation used
 *    to be LAYOUT LIST.
 * Texts: lib/downloadText.ts, lib/alertText.ts, lib/workspaces.ts (pure, unit-tested).
 */
import { useEffect } from 'react'
import { useToast } from '@/context/ToastContext'
import { DOWNLOAD_EVENT, type DownloadEventDetail } from '@/lib/platform'
import { downloadToast } from '@/lib/downloadText'
import { ALERT_SAVE_FAILED_EVENT, alertSaveFailedText, type AlertSaveFailure } from '@/lib/alertText'
import { WORKSPACE_SAVED_EVENT, workspaceSavedText, type WorkspaceSavedDetail } from '@/lib/workspaces'
import { unknownTab, unknownTabText } from '@/lib/deepLink'
import { OWN_BUILD } from '@/components/desktop/build'

/**
 * Terminal v2 PLAN 0.6: a `?tab=` naming no page of this release (an old window, a link from a newer build) says so in
 * a toast instead of landing silently on BRF. Read once, on mount, from the address the window opened with.
 */
export function UnknownTabToast({ tabs }: { tabs: readonly string[] }): null {
  const { addToast } = useToast()
  useEffect(() => {
    let tab: string | null = null
    try { tab = unknownTab(window.location.search, tabs) } catch { tab = null }
    if (tab) addToast(unknownTabText(tab, OWN_BUILD), 'warning', 12000)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return null
}

export function DownloadToasts(): null {
  const { addToast } = useToast()
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<DownloadEventDetail>).detail
      if (!d || typeof d !== 'object' || typeof d.ok !== 'boolean') return
      const t = downloadToast(d)
      addToast(t.text, t.type, t.ttl)
    }
    window.addEventListener(DOWNLOAD_EVENT, on)
    return () => window.removeEventListener(DOWNLOAD_EVENT, on)
  }, [addToast])
  return null
}

/** LAYOUT SAVE / the menu's SAVE confirmation (lib/workspaces.ts emits on a successful store). */
export function WorkspaceSaveToasts(): null {
  const { addToast } = useToast()
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<WorkspaceSavedDetail>).detail
      if (!d || typeof d !== 'object' || typeof d.name !== 'string') return
      addToast(workspaceSavedText(d), 'success', 6000)
    }
    window.addEventListener(WORKSPACE_SAVED_EVENT, on)
    return () => window.removeEventListener(WORKSPACE_SAVED_EVENT, on)
  }, [addToast])
  return null
}

export function AlertSaveToasts(): null {
  const { addToast } = useToast()
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<AlertSaveFailure>).detail
      if (!d || typeof d !== 'object') return
      addToast(alertSaveFailedText(d), 'error', 15000)
    }
    window.addEventListener(ALERT_SAVE_FAILED_EVENT, on)
    return () => window.removeEventListener(ALERT_SAVE_FAILED_EVENT, on)
  }, [addToast])
  return null
}
