'use client'

/**
 * Building blocks specific to the B4B gold sub-views (POSITIONING, PHYSICAL, MACRO, LEARN), layered on the page kit
 * (`./kit.tsx`: GoldPanel · BadgeChip · LagChipEl · useGoldLoad · Pending · NoVerdict) so every panel on GOLD wears
 * the same chrome — title · badge · lag chip · about popover · [B]/[P] copy line — and the same data attributes
 * (`data-gold-panel`) the audit and the repetition test key on.
 *
 *  - `GPanel`: GoldPanel + the §f.2 rendering gate (`series` → catalog verdicts) + the formula line for the [P] layer;
 *  - `Attribution`: the visible attribution line on WGC / SPDR / IBJA / SGE panels (owner decision O-1: displayed on
 *    this private terminal, never re-served or exported);
 *  - `Term`: a dotted-underlined glossary term (title = the short definition; click → the glossary side panel);
 *  - `LinkTile` / `LinkOnlyExplainer`: a LINK-ONLY source (opens in the browser; nothing is fetched by the stack);
 *  - `Field`, `Degraded`, `contextTone`: small helpers.
 *
 * Context metrics never get green/red here: `contextTone` is the neutral token (PLAN §f.3).
 */
import { type CSSProperties, type ReactNode } from 'react'
import { Chip, T } from '@/components/terminal'
import { publishGate } from '@/lib/gold/format'
import { coverageIsAmber, type FeedCoverage } from './feedModel'
import type { Badge, CatalogRow, Freshness, Layer } from '@/lib/gold/types'
import glossaryJson from '@/lib/gold/glossary.json'
import { indexGlossary, lookupTerm, type GlossaryEntry } from '@/lib/gold/learn'
import { GoldPanel, NoVerdict } from './kit'
import { openGlossary } from './GlossaryPanel'

export { BadgeChip, Cell, GoChip, LagChipEl, NoVerdict, Pending, useGoldLoad, type Load } from './kit'

/** The neutral token every context metric renders in (PLAN §f.3). */
export const contextTone = T.muted

// The server's shapes (API_CONTRACT.md §2 as implemented by routers/gold.py) are carried by ui/lib/gold/types.ts since
// wave 1b (`india.freshness` / `shanghai.freshness`, `wgc_india_holdings_t`, `drivers[].report_date`, `family`), so the
// views read types.ts directly; nothing here widens them.

export type AttributionSource = 'WGC' | 'SPDR' | 'IBJA' | 'SGE' | 'LBMA' | 'IMF' | 'CFTC' | 'CME' | 'FRED' | 'RBI' | 'Atlanta Fed' | 'US Treasury' | 'Yahoo'
const ATTRIB: Record<AttributionSource, string> = {
  WGC: 'World Gold Council (Goldhub) — displayed with attribution on this private terminal; not re-served or exported (O-1)',
  SPDR: 'SPDR® Gold Trust (spdrgoldshares.com) — displayed with attribution on this private terminal; not re-served or exported (O-1)',
  IBJA: 'India Bullion and Jewellers Association (ibjarates.com) — displayed with attribution on this private terminal; not re-served or exported (O-1)',
  SGE: 'Shanghai Gold Exchange (sge.com.cn) — displayed with attribution on this private terminal; not re-served or exported (O-1)',
  LBMA: 'LBMA (lbma.org.uk) — public headline / monthly file, attributed',
  IMF: 'IMF IRFCL (api.imf.org) — public data, attributed',
  CFTC: 'CFTC Commitments of Traders (publicreporting.cftc.gov) — US public domain',
  CME: 'CME Group daily files (ftp.cmegroup.com) — public FTP, paced; www.cmegroup.com is never fetched',
  FRED: 'FRED, Federal Reserve Bank of St. Louis — free with attribution',
  RBI: 'Reserve Bank of India Weekly Statistical Supplement — public',
  'Atlanta Fed': 'Federal Reserve Bank of Atlanta Market Probability Tracker — licence to be read by eye (O-10)',
  'US Treasury': 'U.S. Department of the Treasury, daily par yield / real yield curve rates (home.treasury.gov) — US public domain',
  Yahoo: 'Yahoo Finance chart data through the app\'s one cached fetcher (DX-Y.NYB, INR=X, ^GVZ, BZ=F …) — delayed, last trade',
}

/** The visible attribution line (one per source) under a panel that shows a publisher's numbers. */
export function Attribution({ sources, extra }: { sources: AttributionSource[]; extra?: ReactNode }) {
  return (
    <div data-attribution={sources.join(',')} style={{ fontSize: 10, color: T.dim, lineHeight: 1.5, marginTop: 8, borderTop: `1px dashed ${T.border}`, paddingTop: 4 }}>
      {sources.map(s => <div key={s}>Source: {ATTRIB[s]}</div>)}
      {extra}
    </div>
  )
}

const GLOSSARY_INDEX = indexGlossary((glossaryJson as { terms: GlossaryEntry[] }).terms)

/** A glossary term: dotted underline, the short definition as the title, click opens the glossary side panel (§e). */
export function Term({ t, children }: { t: string; children?: ReactNode }) {
  const e = lookupTerm(GLOSSARY_INDEX, t)
  const onOpen = () => openGlossary(e?.term ?? t)
  return (
    <span role="link" tabIndex={0} data-term={e?.term ?? t} title={e?.short ?? `glossary: ${t}`} onClick={onOpen}
      onKeyDown={ev => { if (ev.key === 'Enter') onOpen() }}
      style={{ textDecoration: 'underline dotted', textUnderlineOffset: 2, cursor: 'help', color: 'inherit' }}>{children ?? t}</span>
  )
}

export interface GPanelProps {
  /** PLAN panel id (p.hero, ph.ladder, mc.kgx …) */
  id: string
  title: ReactNode
  subtitle?: ReactNode
  badge?: Badge
  evidence?: string | null
  /** the block's freshness; `null` = no block from the server yet (NO DATA chip); omit for static panels (no chip) */
  fresh?: Freshness | null
  /** daily data shows its report date, never a clock (PLAN 0.1 #10) */
  dateOnly?: string | null
  /**
   * catalog ids the panel's numbers come from, the panel's primary series FIRST: its row supplies the badge chip and the
   * about popover; the §f.2 gate shows "no verdict — not published" when any id lacks a PUBLISH row once the catalog is loaded
   */
  series?: string[]
  /** a LINK-ONLY / static panel: the catalog row for the about popover (the reason it is a link) without the number gate */
  about?: string
  catalog?: Record<string, CatalogRow>
  /** the exact formula, appended to the [P] copy line */
  formula?: string | null
  layer?: Layer
  copyB?: ReactNode
  copyP?: ReactNode
  right?: ReactNode
  accent?: string
  pad?: number
  bodyStyle?: CSSProperties
  style?: CSSProperties
  children?: ReactNode
}

/**
 * A gold panel with the page chrome plus the catalog gate. The badge chip is the catalog's badge for the panel's primary
 * series (`series[0]`); the literal `badge` prop only stands in until the catalog has loaded (and is what the node check
 * compares against the seed). Context panels get the muted accent, arithmetic the amber one.
 */
export function GPanel({ id, title, subtitle, badge, evidence, fresh, dateOnly, series, about, catalog, formula, layer = 'B', copyB, copyP, right, children,
  accent, pad, bodyStyle, style }: GPanelProps) {
  const ids = series ?? []
  const loaded = !!catalog && Object.keys(catalog).length > 0
  const primary = (ids[0] ? catalog?.[ids[0]] : undefined) ?? (about ? catalog?.[about] : undefined) ?? null
  // PLAN §f.2: every id the panel reads needs a PUBLISH-CORE / PUBLISH-CONTEXT row with a badge; a missing row is no verdict
  const blocked = loaded ? ids.filter(s => publishGate(catalog, s) !== 'ok') : []
  const shownBadge = primary?.badge ?? badge
  const pCopy = formula ? <>{copyP ?? copyB}{(copyP ?? copyB) ? ' · ' : ''}<span style={{ fontFamily: T.mono, color: T.cyan }}>{formula}</span></> : copyP
  return (
    <GoldPanel id={id} title={title} subtitle={subtitle} badge={shownBadge} evidence={evidence ?? primary?.evidence} freshness={fresh} reportDate={dateOnly}
      catalogRow={primary} maxAgeDays={primary?.max_age_days} layer={layer} copyB={copyB} copyP={pCopy} right={right}
      accent={accent ?? (shownBadge === 'context' ? T.borderHi : T.amber)} pad={pad} bodyStyle={bodyStyle} style={style}>
      {blocked.length ? <NoVerdict what={`${id}: ${blocked.map(s => `${s} ${catalog?.[s]?.verdict ?? 'no catalog row'}`).join(', ')}`} /> : children}
    </GoldPanel>
  )
}

/** A LINK-ONLY source tile: name, what it is, why it is a link; opens in the browser, nothing is fetched. */
export function LinkTile({ name, url, what, why }: { name: string; url: string; what?: string; why?: string }) {
  return (
    <a href={url} target="_blank" rel="noreferrer" data-link-only
      style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, alignItems: 'center', padding: '6px 10px', textDecoration: 'none',
               border: `1px solid ${T.border}`, color: T.text }}>
      <span>
        <span style={{ fontSize: 12, color: T.text }}>{name}</span>
        {what && <span style={{ fontSize: 10, color: T.muted }}> · {what}</span>}
        {why && <div style={{ fontSize: 10, color: T.dim }}>{why}</div>}
      </span>
      <Chip color={T.cyan} style={{ cursor: 'pointer' }}>↗ OPEN</Chip>
    </a>
  )
}

export function LinkOnlyExplainer({ children }: { children?: ReactNode }) {
  return (
    <div data-link-only-explainer style={{ fontSize: 10, color: T.dim, lineHeight: 1.5, marginBottom: 6 }}>
      LINK-ONLY: the publisher blocks scripts or its terms forbid automated access, so nothing is fetched by the stack; the tile opens the page in your browser.{children ? <> {children}</> : null}
    </div>
  )
}

/** Label → value row with an optional tooltip from the field name. Neutral by default. */
export function Field({ label, value, tip, mono = true, color }: { label: ReactNode; value: ReactNode; tip?: string; mono?: boolean; color?: string }) {
  return (
    <div title={tip} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '3px 0', borderBottom: `1px dashed ${T.border}`, fontSize: 11 }}>
      <span style={{ color: T.muted, fontSize: 10, textTransform: 'uppercase', letterSpacing: .8 }}>{label}</span>
      <span style={{ color: color ?? T.text, fontFamily: mono ? T.mono : undefined, fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>{value}</span>
    </div>
  )
}

/**
 * What a feed's own window covers, when the panel asks for more than it can serve.
 *
 * Critics CT-04 / F3 (8 Nov 2026): HEALTH's event-risk panel and MACRO's US calendar both run a now + 7 days window,
 * while the only US source (Forex Factory) serves one New York Sun–Sat week at a time. From roughly Thursday to the
 * source's Sunday roll most of the next US week is missing, and the panels read "the whole week, nothing cut off".
 * The server now returns `us_coverage` / `calendar_coverage` ({state, note, covers_through_label, uncovered}); this row
 * prints its note — amber while the window is mostly uncovered, dim for a day or two, nothing when it fits.
 */
export function CoverageNote({ cov, links }: { cov?: FeedCoverage | null; links?: ReactNode }) {
  if (!cov?.note) return null
  const amber = coverageIsAmber(cov)
  return (
    <div data-coverage-note={cov.state ?? ''} style={{ fontSize: 11, color: amber ? T.amber : T.dim, lineHeight: 1.5, marginBottom: 6 }}>
      {amber ? '▲ ' : ''}{cov.note}{links ? <> {links}</> : null}
    </div>
  )
}

export { coverageSubtitle, type FeedCoverage } from './feedModel'

/** Error line that keeps the panel's last values visible (degrade-honest, never blank). */
export function Degraded({ error, what }: { error: string | null; what: string }) {
  if (!error) return null
  return <div data-degraded style={{ fontSize: 11, color: T.amber, marginBottom: 8 }}>▲ {what} unavailable: {error} — showing the last stored values where there are any.</div>
}
