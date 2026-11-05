/**
 * Latest-request-wins guard for page loads (CT-01).
 *
 * A page that reloads when its selection changes (OMON symbol/expiry, OSTR chain, COMP set/period, DEAL window)
 * can have two requests in flight: the one for the old selection and the one for the new. Whichever answers
 * last used to win `setData`, so 'RELIANCE OMON' from another page could end on NIFTY's chain. Each load now
 * takes a token from `begin()` and applies its response only while `isCurrent(token)`: a superseded response
 * is dropped, whatever order the answers arrive in. `cancel()` invalidates every token (unmount).
 *
 * Periodic refreshes (P1, round-3 review): a timer refresh of the SAME selection must not supersede a load that
 * is still in flight. OMON's LIVE chain refreshes every 30 s while a live answer may take up to 40 s (plus the
 * end-of-day fallback): with a fresh token per tick every slow answer was dropped and the page showed
 * 'Loading …' for good. `begin(key)` records the selection a load is for; `busy(key)` is true while the newest
 * load for that key has not settled, so the refresh skips that tick; `settle(token)` marks it done.
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 * React pages hold one in a ref (components/useRequestSeq.ts), never in useMemo (React may drop a memo).
 */
export interface RequestSeq {
  /** start a request (for selection `key`, when given): its token */
  begin(key?: string): number
  /** the token belongs to the newest request (and nothing cancelled it since) */
  isCurrent(token: number): boolean
  /** the newest request is for `key` and has not settled yet (a same-selection refresh should wait for it) */
  busy(key: string): boolean
  /** the request with this token finished (applied, failed or fell back); a no-op for a superseded token */
  settle(token: number): void
  /** drop every request in flight (unmount, or a selection change that should show nothing old) */
  cancel(): void
}

export function createRequestSeq(): RequestSeq {
  let n = 0
  let key: string | null = null
  let open = false
  return {
    begin: (k?: string) => { key = k ?? null; open = true; return ++n },
    isCurrent: (token: number) => token === n,
    busy: (k: string) => open && key === k,
    settle: (token: number) => { if (token === n) open = false },
    cancel: () => { n++; open = false },
  }
}
