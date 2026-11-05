'use client'

/**
 * QuantKPICard — Bloomberg-box style metric tile.
 *
 * Aesthetic: NSE data terminal.  Chakra Petch labels, JetBrains Mono values.
 * Accent line on the left edge.  Subtle corner brackets.  Hover: scanline brighten.
 */

import { useEffect, useRef, useState } from 'react'

// Accent palette — maps to the terminal color system
const ACCENT: Record<string, { border: string; glow: string; text: string; bg: string }> = {
  amber:  { border: '#ffb000', glow: 'rgba(245,166,35,0.12)', text: '#ffb000',   bg: 'rgba(245,166,35,0.05)' },
  jade:   { border: '#16d98a', glow: 'rgba(0,200,150,0.10)',  text: '#16d98a',   bg: 'rgba(0,200,150,0.05)'  },
  crimson:{ border: '#ff4d5e', glow: 'rgba(255,59,71,0.10)',  text: '#ff4d5e',   bg: 'rgba(255,59,71,0.04)'  },
  indigo: { border: '#6080FF', glow: 'rgba(96,128,255,0.10)', text: '#7A9AFF',   bg: 'rgba(96,128,255,0.04)' },
  violet: { border: '#b58bff', glow: 'rgba(160,96,255,0.10)', text: '#b58bff',   bg: 'rgba(160,96,255,0.04)' },
  cyan:   { border: '#00BFDF', glow: 'rgba(0,191,223,0.10)',  text: '#4ACFE8',   bg: 'rgba(0,191,223,0.04)'  },
  slate:  { border: '#6f7a8e', glow: 'rgba(61,88,114,0.10)',  text: '#aab3c2',   bg: 'rgba(61,88,114,0.04)'  },
  rose:   { border: '#FF6080', glow: 'rgba(255,96,128,0.10)', text: '#FF8080',   bg: 'rgba(255,96,128,0.04)' },
}

// Animated counter for number transitions
function useCountUp(target: number, duration = 600) {
  const [display, setDisplay] = useState(target)
  const prev = useRef(target)
  const raf  = useRef<number | undefined>(undefined)

  useEffect(() => {
    const start    = prev.current
    const end      = target
    const delta    = end - start
    const startMs  = performance.now()
    if (Math.abs(delta) < 0.01 || isNaN(delta)) { setDisplay(target); return }

    const step = (now: number) => {
      const t = Math.min((now - startMs) / duration, 1)
      const eased = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t  // ease-in-out quad
      setDisplay(start + delta * eased)
      if (t < 1) raf.current = requestAnimationFrame(step)
      else { setDisplay(end); prev.current = end }
    }
    raf.current = requestAnimationFrame(step)
    return () => { if (raf.current) cancelAnimationFrame(raf.current) }
  }, [target, duration])

  return display
}

interface QuantKPIProps {
  label:    string
  value:    string | number
  subtext?: string
  trend?:   'up' | 'down' | 'stable' | null
  accent?:  keyof typeof ACCENT
  icon?:    string       // simple emoji/symbol
  prefix?:  string       // e.g. '₹'
  suffix?:  string       // e.g. '%' or 'M'
  animate?: boolean      // counter animation for numeric values
  size?:    'sm' | 'md' | 'lg'
}

export function QuantKPICard({
  label, value, subtext, trend, accent = 'amber', icon,
  prefix = '', suffix = '', animate = false, size = 'md',
}: QuantKPIProps) {
  // Terminal Stat tile (components/terminal Stat look): top accent rule, micro-label, mono value
  const { border, text: accentText } = ACCENT[accent] ?? ACCENT.amber
  const numericValue = typeof value === 'number' ? value : NaN
  const isNumeric = Number.isFinite(numericValue)
  const animated = useCountUp(isNumeric ? numericValue : 0, 800)
  const displayValue = isNumeric && animate
    ? `${prefix}${animated.toLocaleString('en-IN', { maximumFractionDigits: 1 })}${suffix}`
    : isNumeric ? `${prefix}${numericValue.toLocaleString('en-IN')}${suffix}` : value
  const trendIcon = trend === 'up' ? '▲' : trend === 'down' ? '▼' : trend === 'stable' ? '→' : null
  const trendColor = trend === 'up' ? '#16d98a' : trend === 'down' ? '#ff4d5e' : '#aab3c2'
  const fontSize = size === 'sm' ? 16 : size === 'lg' ? 30 : 22
  return (
    <div className="t-fade-up"
      style={{ border: '1px solid #1a2130', borderTop: `2px solid ${border}`, background: '#0a0d13', padding: '9px 12px', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontFamily: 'var(--t-mono)', fontSize: 10, letterSpacing: 1.4, textTransform: 'uppercase', color: 'var(--t-muted)' }}>{label}</span>
        <span style={{ flex: 1 }} />
        {icon && <span style={{ fontSize: 10, color: accentText, opacity: .7 }}>{icon}</span>}
      </div>
      <div style={{ fontFamily: 'var(--t-mono)', fontSize, fontWeight: 600, color: '#f2f5fa', marginTop: 4,
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {displayValue}
        {trendIcon && <span style={{ fontSize: 11, marginLeft: 6, color: trendColor }}>{trendIcon}</span>}
      </div>
      {subtext && <div style={{ fontSize: 10, color: 'var(--t-muted)', marginTop: 3 }}>{subtext}</div>}
    </div>
  )
}
