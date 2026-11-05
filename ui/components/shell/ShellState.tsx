'use client'

/**
 * What the platform shell knows, for the terminal below it (C1-trader-ux-02 / -06 / -13 / -14). PlatformShell
 * (components/desktop/PlatformShell.tsx) is the single writer; the terminal reads it with useShellState():
 *
 *  - `desktop`: inside SuryaDhana.app (the title strip is then the one brand / clock / session / service-light
 *    source, so the page header drops its copies);
 *  - `link`: 'down' exactly while the connection banner says LINK DOWN (desktop: the shell's status; browser:
 *    the /api/health monitor); the footer and the live chips follow it instead of their own first-load flag;
 *  - `downSince`: epoch ms the outage began (null while up);
 *  - `zoom`: the window's page zoom (desktop, contract K3; 1 in a browser);
 *  - `reconnects`: bumped on every LINK DOWN → LINK UP (the reconnected event carries the same moment).
 */
import { createContext, useContext } from 'react'

export interface ShellState {
  desktop: boolean
  link: 'up' | 'down'
  downSince: number | null
  zoom: number
  reconnects: number
}

export const DEFAULT_SHELL_STATE: ShellState = Object.freeze({ desktop: false, link: 'up', downSince: null, zoom: 1, reconnects: 0 })

export const ShellStateContext = createContext<ShellState>(DEFAULT_SHELL_STATE)

export function useShellState(): ShellState {
  return useContext(ShellStateContext)
}
