'use client'

/**
 * useExternalPrefChange: adopt a SYNC key's changes made outside this component (multi-window, C3-02).
 *
 * Every window of one origin shares localStorage, but a component that read a key on mount keeps its own copy
 * in React state. Without this, window 2 writes its stale copy back on its next edit and silently drops window
 * 1's edit (then the server and every other device get the stale value too). The hook fires on another window's
 * write (native 'storage') and on the sync engine applying a newer server value ('suryadhana:prefs-changed' and
 * its synthetic 'storage' twin, coalesced into one call). The listening rules live in
 * external.ts subscribeExternalPrefChange (unit-tested by ui/lib/__tests__/prefs.check.ts X3).
 *
 * Contract for consumers (what keeps windows from ping-ponging):
 *  - re-read localStorage inside the callback (never trust an event's newValue: a later write may have landed);
 *  - only set state when the parsed value differs from the current one;
 *  - never write a value they just adopted back to storage (it is already there; writing it again could only
 *    overwrite a newer write from another window). Edits the user makes afterwards are written as usual.
 */
import { useEffect, useRef } from 'react'
import { subscribeExternalPrefChange } from './external'

export function useExternalPrefChange(keys: string | readonly string[], onChange: () => void): void {
  const cb = useRef(onChange)
  useEffect(() => {
    cb.current = onChange
  })
  const list = typeof keys === 'string' ? keys : keys.join('\n')
  useEffect(() => {
    let area: Storage | null = null
    try {
      area = window.localStorage
    } catch {
      /* storage blocked: nothing can change it from outside either */
    }
    return subscribeExternalPrefChange(window, list.split('\n'), () => cb.current(), area)
  }, [list])
}
