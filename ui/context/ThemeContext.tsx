'use client'

import { createContext, useContext, useState, useEffect, ReactNode } from 'react'

interface ThemeContextType {
  isDark: boolean
  setIsDark: (value: boolean) => void
  toggleTheme: () => void
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [isDark, setIsDarkState] = useState(true)
  const [mounted, setMounted] = useState(false)

  // Load theme from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('theme')
    if (saved !== null) {
      setIsDarkState(saved === 'dark')
    } else {
      setIsDarkState(true) // Default to dark
    }
    setMounted(true)
  }, [])

  // Save theme to localStorage whenever it changes
  const setIsDark = (value: boolean) => {
    setIsDarkState(value)
    localStorage.setItem('theme', value ? 'dark' : 'light')
  }

  const toggleTheme = () => {
    setIsDark(!isDark)
  }

  // Apply theme to document
  useEffect(() => {
    if (mounted) {
      if (isDark) {
        document.documentElement.classList.remove('light')
        document.documentElement.classList.add('dark')
      } else {
        document.documentElement.classList.remove('dark')
        document.documentElement.classList.add('light')
      }
    }
  }, [isDark, mounted])

  if (!mounted) return null

  return (
    <ThemeContext.Provider value={{ isDark, setIsDark, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme() {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return context
}
