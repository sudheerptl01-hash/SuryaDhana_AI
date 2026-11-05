'use client'

/**
 * Market session + link state for live chips (C1-trader-ux-13). One minute-aligned tick per consumer and the shared
 * NSE holiday fetch (components/desktop/holidays.ts), so it costs no extra request. Pure wording lives in
 * lib/feedState.ts.
 *
 * Data beats the calendar (R-UI-SHELL-03): `marketOpen` is true while the calendar says the session runs OR a
 * monitor-socket tick arrived in the last 90 s (lib/liveEvidence.ts), so the socket chips (watchlist bar, ALFA)
 * never say SOCKET OK · NO TICKS while ticks flow on a day the calendar calls closed. `calendarOpen` is the
 * calendar alone.
 */
import { useEffect, useState } from 'react'
import { istParts, nseSession } from '@/components/desktop/session'
import { useNseHolidays } from '@/components/desktop/holidays'
import { isLiveTick } from '@/lib/feedState'
import { lastLiveTickAt, subscribeLiveEvidence } from '@/lib/liveEvidence'
import { useShellState } from './ShellState'

/** Epoch ms, refreshed on every IST minute boundary. */
function useMinuteTick(): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>
    const arm = () => {
      timer = setTimeout(() => {
        setNow(Date.now())
        arm()
      }, 60_000 - (Date.now() % 60_000) + 20)
    }
    arm()
    return () => clearTimeout(timer)
  }, [])
  return now
}

/** True from 09:00 to 15:30 IST on a trading day (pre-open prints count as live). */
export function useMarketOpen(): boolean {
  const now = useMinuteTick()
  const holidays = useNseHolidays(istParts(now).date)
  return nseSession(now, holidays).state !== 'CLOSED'
}

/** True while a monitor tick arrived in the last 90 s; re-evaluated on the first tick and every minute. */
export function useTicking(): boolean {
  const now = useMinuteTick()
  const [, setEdge] = useState(0)
  useEffect(() => subscribeLiveEvidence(() => setEdge(n => n + 1)), [])
  return isLiveTick(lastLiveTickAt(), Math.max(now, Date.now()))
}

/** `{marketOpen, linkDown, calendarOpen}` for lib/feedState.ts chips (marketOpen = calendar OR live ticks). */
export function useFeedState(): { marketOpen: boolean; linkDown: boolean; calendarOpen: boolean } {
  const calendarOpen = useMarketOpen()
  const ticking = useTicking()
  const { link } = useShellState()
  return { marketOpen: calendarOpen || ticking, linkDown: link === 'down', calendarOpen }
}
