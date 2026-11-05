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
 * Texts: lib/downloadText.ts, lib/alertText.ts (pure, unit-tested).
 */
import { useEffect } from 'react'
import { useToast } from '@/context/ToastContext'
import { DOWNLOAD_EVENT, type DownloadEventDetail } from '@/lib/platform'
import { downloadToast } from '@/lib/downloadText'
import { ALERT_SAVE_FAILED_EVENT, alertSaveFailedText, type AlertSaveFailure } from '@/lib/alertText'

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
