// Terminal palette + number formatting for the News Catalyst Terminal.
// This file is the T token source (mirrored by the CSS variables in app/globals.css — keep both in step;
// pages.check.ts §7 verifies the mirror and the dim-contrast floor).
//
// Refined-dark token pass (FINAL ROUND wave C, O-F2): refinement, not redesign — every colour value is
// unchanged except `dim` (#747e92 → #788296), lifted so every text token clears 4.5:1 on every ground
// incl. panel3 (#747e92 was 4.30:1 there; hex hardcodes across pages pin the other values — see
// ~/.suryadhana_pm_scratch/final_round_20261113/c-tokens/CONTRAST.md). Amber is the ONE accent
// (cyan secondary); green/red stay data semantics (price direction, errors), never decoration.

export const T = {
  bg: '#05070a',
  panel: '#0a0d13',
  panel2: '#0e121a',
  border: '#1a2130',
  borderHi: '#2a3448',
  text: '#d6dbe4',
  bright: '#f2f5fa',
  panel3: '#131926',
  muted: '#8691a5',
  dim: '#788296',
  amber: '#ffb000',
  amberDim: '#8a6400',
  green: '#16d98a',
  red: '#ff4d5e',
  cyan: '#39c6ff',
  violet: '#b58bff',
  mono: "'JetBrains Mono', 'SF Mono', Menlo, monospace",
  display: "'Chakra Petch', 'JetBrains Mono', sans-serif",
  // ── type scale (wave C): 12/13/15/18, one mono family for data/body (T.mono); Chakra Petch stays the
  //    display face for page titles / wordmarks only. px numbers — drop straight into inline fontSize.
  fsMicro: 12,
  fsBody: 13,
  fsLead: 15,
  fsTitle: 18,
  // ── spacing grid (wave C): 4/8 px steps. px numbers for inline padding/gap/margin.
  sp1: 4,
  sp2: 8,
  sp3: 12,
  sp4: 16,
  sp5: 24,
  sp6: 32,
  // ── motion (wave C): one duration + easing terminal-wide; 150 ms ease, no flash (O-F2).
  dur: '150ms',
  ease: 'ease',
  motion: '150ms ease',
} as const

const CCY: Record<string, string> = { USD: '$', INR: '₹', GBP: '£', GBp: 'p', EUR: '€' }

export function fmtPrice(v: number | null | undefined, ccy?: string): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const sym = ccy ? CCY[ccy] ?? '' : ''
  const digits = v >= 1000 ? 2 : v >= 1 ? 2 : 4
  const n = v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return ccy === 'GBp' ? `${n}p` : `${sym}${n}`
}

export function fmtChange(v: number | null | undefined, ccy?: string): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  const n = abs.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: abs < 1 ? 3 : 2 })
  const body = ccy === 'GBp' ? `${n}p` : `${ccy ? CCY[ccy] ?? '' : ''}${n}`
  return `${v >= 0 ? '+' : '−'}${body}`
}

export function fmtPct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const r = Number(v.toFixed(digits)) || 0
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toFixed(digits)}%`
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toFixed(digits)
}

export function fmtVol(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (v >= 1e9) return `${(v / 1e9).toFixed(2)}B`
  if (v >= 1e6) return `${(v / 1e6).toFixed(2)}M`
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return String(Math.round(v))
}

export const signColor = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) || v === 0 ? T.muted : v > 0 ? T.green : T.red

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`
  if (s < 86400) return `${Math.round(s / 3600)}h ago`
  return `${Math.round(s / 86400)}d ago`
}

export const convictionColor = (c: number) =>
  c >= 8 ? T.green : c >= 6 ? T.amber : c >= 4 ? T.cyan : T.muted

export const REGION_LABEL: Record<string, string> = { US: 'US', IN: 'INDIA', UK: 'UK', OTHER: 'OTHER' }

export { tradingViewUrl } from '../terminal/ChartActions'
