'use client'

/**
 * Theme context. SuryaDhana is a terminal: dark only (Bloomberg-style). The API is
 * kept so existing components that read `isDark` keep working; `isDark` is always true.
 */
import { createContext, useContext, useEffect, ReactNode } from 'react'

interface ThemeContextType {
  isDark: boolean
  setIsDark: (value: boolean) => void
  toggleTheme: () => void
}

const noop = () => {}
const ThemeContext = createContext<ThemeContextType>({ isDark: true, setIsDark: noop, toggleTheme: noop })

export function ThemeProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    document.documentElement.classList.remove('light')
    document.documentElement.classList.add('dark')
    try { localStorage.removeItem('theme') } catch { /* storage unavailable */ }
  }, [])
  return <ThemeContext.Provider value={{ isDark: true, setIsDark: noop, toggleTheme: noop }}>{children}</ThemeContext.Provider>
}

export function useTheme() {
  return useContext(ThemeContext)
}
