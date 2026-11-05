/**
 * Terminal v2 kit helpers that need no DOM and no React (reports/terminal_v2/PLAN.md §0.1, §0.5):
 *
 *  - `sourceOf(asOf, …)` turns a payload's as-of into the SourceChip state every panel header carries
 *    (LIVE · BREEZE / LIVE · NSE / DELAYED <day> / STALE <day> / OFFLINE / GAP): daily data shows its date,
 *    never a clock; a date older than `maxAgeDays` reads STALE; no as-of at all reads OFFLINE.
 *  - `inputSource(what)`: the chip of a panel with no data source behind it (a form, a calculator on your inputs):
 *    INPUT, so every Panel header still says where its numbers come from (PLAN §0.5, G9's static scan).
 *  - `nseStampIso('23-Oct-2026 16:00:00')`: NSE's live-feed timestamps as ISO (IST) for `sourceOf`.
 *  - `BADGES`: the four evidence badges (signal / context / arithmetic / heuristic) with the colour rule —
 *    context is the neutral tone and never a buy / sell colour; `signal` exists for no series today.
 *  - `subFromSearch` / `withSub`: the `?sub=` URL parameter a page's sub-views (DERV › VOL, SYS › DATA) read and
 *    write, kept beside the GOLD page's own `?sub=` (different pages, same parameter).
 *
 * Pure: unit-tested under plain node by ui/components/vol/__tests__/terminal_v2.check.ts.
 */

export type SourceState = 'live' | 'delayed' | 'stale' | 'offline' | 'gap' | 'degraded' | 'input' | 'reference'

export interface SourceInfo {
  state: SourceState
  /** feed or publisher name for the chip ('BREEZE', 'NSE', 'NSE F&O bhavcopy') */
  source?: string | null
  /** the period the data describes: 'YYYY-MM-DD' for daily data, an ISO timestamp for intraday */
  asOf?: string | null
  /** age in calendar days when known (daily data) */
  ageDays?: number | null
  /** why a stale / gap / offline block is in that state */
  hint?: string | null
}

const DAY_RE = /^(\d{4})-(\d{2})-(\d{2})/

/** 'YYYY-MM-DD' (or an ISO timestamp) → 'DD MON' for the chip; '' when unparsable. */
export function chipDay(iso: string | null | undefined): string {
  const m = DAY_RE.exec(iso ?? '')
  if (!m) return ''
  const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const mo = +m[2]
  if (mo < 1 || mo > 12) return ''
  return `${m[3]} ${MONTHS[mo - 1]}`
}

/** Calendar days between an as-of (date or timestamp) and `now`; null when the as-of is unparsable. */
export function ageDaysOf(asOf: string | null | undefined, now: Date = new Date()): number | null {
  const m = DAY_RE.exec(asOf ?? '')
  if (!m) return null
  const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(asOf ?? '')
  const t = isDateOnly ? Date.UTC(+m[1], +m[2] - 1, +m[3]) : Date.parse(asOf as string)
  if (!Number.isFinite(t)) return null
  const nowDay = isDateOnly ? Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()) : now.getTime()
  return Math.max(0, (nowDay - t) / 86_400_000)
}

export interface SourceOpts {
  /** the feed name printed on the chip */
  source?: string | null
  /** true while a live feed is ticking (the chip reads LIVE · <source>) */
  live?: boolean
  /** a daily value older than this many calendar days reads STALE (default 4: a weekend plus one missed session) */
  maxAgeDays?: number | null
  /** an explicit session gap (the capture never ran) */
  gap?: boolean
  /** the feed is up but erroring */
  degraded?: boolean
  hint?: string | null
  now?: Date
}

/** The SourceChip state for a payload's as-of (PLAN §0.5: value · source · as-of · lag chip). */
export function sourceOf(asOf: string | null | undefined, opts: SourceOpts = {}): SourceInfo {
  const { source = null, live = false, maxAgeDays = 4, gap = false, degraded = false, hint = null, now } = opts
  if (gap) return { state: 'gap', source, asOf: asOf ?? null, ageDays: ageDaysOf(asOf, now), hint }
  if (degraded) return { state: 'degraded', source, asOf: asOf ?? null, ageDays: ageDaysOf(asOf, now), hint }
  if (live) return { state: 'live', source, asOf: asOf ?? null, ageDays: 0, hint }
  const age = ageDaysOf(asOf, now)
  if (age == null) return { state: 'offline', source, asOf: asOf ?? null, ageDays: null, hint: hint ?? 'no as-of in the payload' }
  if (maxAgeDays != null && age > maxAgeDays) return { state: 'stale', source, asOf: asOf ?? null, ageDays: age, hint }
  return { state: 'delayed', source, asOf: asOf ?? null, ageDays: age, hint }
}

/** The chip of a panel whose numbers come from what the user typed (no feed, no store): INPUT. */
export function inputSource(what = 'your inputs'): SourceInfo {
  return { state: 'input', source: null, asOf: null, ageDays: null, hint: what }
}

/** A feed whose payload carries no as-of (a calendar, a filings screen): DELAYED · <SOURCE>, never an invented date. */
export function undatedSource(source: string, hint: string | null = null): SourceInfo {
  return { state: 'delayed', source, asOf: null, ageDays: null, hint }
}

/** The chip of a panel that shows fixed reference text (rules, a roadmap, a curriculum): REFERENCE, no data feed. */
export function referenceSource(what: string): SourceInfo {
  return { state: 'reference', source: null, asOf: null, ageDays: null, hint: what }
}

const MON3: Record<string, string> = { JAN: '01', FEB: '02', MAR: '03', APR: '04', MAY: '05', JUN: '06', JUL: '07', AUG: '08', SEP: '09', OCT: '10', NOV: '11', DEC: '12' }

/**
 * NSE feed stamps → ISO with the IST offset: '23-Oct-2026 16:00:00' / '23-OCT-2026' / '2026-10-23 16:00:00' / an ISO
 * string (kept). Null when unparsable (the chip then reads OFFLINE rather than inventing a date).
 */
export function nseStampIso(stamp: string | null | undefined): string | null {
  if (!stamp) return null
  const t = String(stamp).trim()
  if (/^\d{4}-\d{2}-\d{2}$/.test(t)) return t
  if (/^\d{4}-\d{2}-\d{2}T/.test(t) && Number.isFinite(Date.parse(t))) return t
  const iso = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(t)
  if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}T${iso[4]}:${iso[5]}:${iso[6] ?? '00'}+05:30`
  const m = /^(\d{1,2})[- ]([A-Za-z]{3})[- ](\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?/.exec(t)
  if (!m) return null
  const mo = MON3[m[2].toUpperCase()]
  if (!mo) return null
  const day = `${m[3]}-${mo}-${m[1].padStart(2, '0')}`
  return m[4] ? `${day}T${m[4].padStart(2, '0')}:${m[5]}:${m[6] ?? '00'}+05:30` : day
}

export interface ChipText { label: string; title: string }

/** 'HH:MM' IST of an ISO timestamp ('' for a date-only value or an unparsable one): intraday chips show a clock. */
export function chipClock(iso: string | null | undefined): string {
  if (!iso || /^\d{4}-\d{2}-\d{2}$/.test(iso)) return ''
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return ''
  const ist = new Date(t + 5.5 * 3600_000)
  return `${String(ist.getUTCHours()).padStart(2, '0')}:${String(ist.getUTCMinutes()).padStart(2, '0')}`
}

/** The IST calendar day of an as-of (a date stays itself; a timestamp is converted), 'YYYY-MM-DD' or ''. */
function istDay(iso: string | null | undefined): string {
  if (!iso) return ''
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso
  const t = Date.parse(iso)
  return Number.isFinite(t) ? new Date(t + 5.5 * 3600_000).toISOString().slice(0, 10) : ''
}

/**
 * The chip's text and hover text for a SourceInfo. Daily data shows its date ('DELAYED · 04 NOV'); an intraday as-of
 * from today shows the feed and its IST clock ('DELAYED · YAHOO · 10:42'); an older timestamp shows its date.
 */
export function sourceChipText(s: SourceInfo, now: Date = new Date()): ChipText {
  const src = s.source ? String(s.source).toUpperCase() : ''
  const clock = chipClock(s.asOf)
  const today = clock !== '' && istDay(s.asOf) === istDay(now.toISOString())
  const day = chipDay(istDay(s.asOf))
  const stamp = today ? `${src && src.length <= 14 ? `${src} · ` : ''}${clock}` : day
  const when = s.asOf && !/^\d{4}-\d{2}-\d{2}$/.test(s.asOf) ? `as of ${s.asOf}` : day ? `as of ${day}` : 'no as-of'
  const why = s.hint ? ` — ${s.hint}` : ''
  switch (s.state) {
    case 'live': return { label: `LIVE${src ? ` · ${src}` : ''}`, title: `Live feed${src ? ` (${src})` : ''}${clock ? ` · last ${clock} IST` : ''}${why}` }
    case 'delayed': return { label: `DELAYED${stamp ? ` · ${stamp}` : src ? ` · ${src}` : ''}`, title: `Stored or delayed data${src ? ` from ${src}` : ''} · ${when}${why}` }
    case 'stale': return { label: `STALE${stamp ? ` · ${stamp}` : ''}`, title: `Older than expected${src ? ` (${src})` : ''} · ${when}${s.ageDays != null ? ` · ${Math.round(s.ageDays)} d old` : ''}${why}` }
    case 'gap': return { label: `GAP${day ? ` · ${day}` : ''}`, title: `No capture for this session${src ? ` (${src})` : ''}${why}` }
    case 'degraded': return { label: 'DEGRADED', title: `Feed connected but erroring${src ? ` (${src})` : ''}; values may be stale${why}` }
    case 'input': return { label: 'INPUT', title: `Computed from ${s.hint ?? 'your inputs'}; no stored or live feed behind this panel` }
    case 'reference': return { label: 'REFERENCE', title: `Fixed reference text (${s.hint ?? 'documentation'}); no data feed behind this panel` }
    default: return { label: 'OFFLINE', title: `No source is responding${src ? ` (${src})` : ''}${why}` }
  }
}

// ── badges (PLAN §0.1) ────────────────────────────────────────────────────────────────────────────────

export type Badge = 'signal' | 'context' | 'arithmetic' | 'heuristic'
export type BadgeTone = 'green' | 'muted' | 'cyan' | 'violet'

export interface BadgeSpec { label: string; tone: BadgeTone; title: string }

/** Badge text, tone and hover text. `context` is the neutral tone: it never reads as a buy / sell colour. */
export const BADGES: Readonly<Record<Badge, BadgeSpec>> = Object.freeze({
  signal: { label: 'SIGNAL', tone: 'green', title: 'A pre-registered study PASSED as a forecast (|t| ≥ 2 in both halves after costs). No such series exists today in F&O, gold or index attribution.' },
  context: { label: 'CONTEXT', tone: 'muted', title: 'Describes what happened or where things stand; no forecasting power is claimed. Describes, does not predict.' },
  arithmetic: { label: 'ARITHMETIC', tone: 'cyan', title: 'An identity, a definition or a cost (IV from a price, points = level × weight × return, SPAN from the risk file). No claim about the future.' },
  heuristic: { label: 'HEURISTIC', tone: 'violet', title: 'A house rule without evidence; the measured error is printed where one exists.' },
})

export function badgeSpec(badge: Badge | string | null | undefined): BadgeSpec {
  return badge && badge in BADGES ? BADGES[badge as Badge] : BADGES.context
}

/** The sentence every verdict ends with (PLAN §0.1). */
export const DESCRIBES = 'describes, does not predict'

/** `s` with the mandatory ending (idempotent). */
export function describes(s: string): string {
  const t = s.trim().replace(/[.\s]+$/, '')
  return t.toLowerCase().endsWith(DESCRIBES) ? t : `${t} — ${DESCRIBES}`
}

// ── sub-views: `?sub=` ────────────────────────────────────────────────────────────────────────────────

/** The `sub` parameter of a location.search when it is one of `valid`, else null. */
export function subFromSearch(search: string, valid: readonly string[]): string | null {
  try {
    const s = new URLSearchParams(search).get('sub')
    return s && valid.includes(s) ? s : null
  } catch {
    return null
  }
}

/** The search string with `sub` set (or removed when null); every other parameter kept. */
export function withSub(search: string, sub: string | null): string {
  let p: URLSearchParams
  try { p = new URLSearchParams(search) } catch { p = new URLSearchParams() }
  if (sub) p.set('sub', sub); else p.delete('sub')
  const q = p.toString()
  return q ? `?${q}` : ''
}

/** The window event `setSubInUrl` fires, so a page that is already mounted adopts the hand-off (useSubView). */
export const SUB_VIEW_EVENT = 'suryadhana:sub-view'

/** Hand a sub-view to the next page before `goToPage(id)` (the GO bar's VOL / DATA aliases, "VOL ›" chips). */
export function setSubInUrl(sub: string | null): void {
  try {
    window.history.replaceState(window.history.state, '', withSub(window.location.search, sub) || window.location.pathname)
  } catch { /* history locked */ }
  try { window.dispatchEvent(new CustomEvent<string | null>(SUB_VIEW_EVENT, { detail: sub })) } catch { /* no DOM */ }
}

// ── small numeric helpers shared by the v2 panels ─────────────────────────────────────────────────────

/** Share (0–100) of `values` strictly below `today` (a percentile); null with fewer than `minN` values. */
export function percentileOf(values: readonly (number | null | undefined)[], today: number | null | undefined, minN = 20): number | null {
  if (today == null || !Number.isFinite(today)) return null
  const xs = values.filter((v): v is number => v != null && Number.isFinite(v))
  if (xs.length < minN) return null
  return (xs.filter(v => v < today).length / xs.length) * 100
}

/** Where `today` sits between the min (0) and max (100) of `values` (a rank); null with fewer than `minN` values. */
export function rankOf(values: readonly (number | null | undefined)[], today: number | null | undefined, minN = 20): number | null {
  if (today == null || !Number.isFinite(today)) return null
  const xs = values.filter((v): v is number => v != null && Number.isFinite(v))
  if (xs.length < minN) return null
  const lo = Math.min(...xs), hi = Math.max(...xs)
  if (hi === lo) return 50
  return ((today - lo) / (hi - lo)) * 100
}
