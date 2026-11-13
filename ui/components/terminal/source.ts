/**
 * Terminal v2 kit helpers that need no DOM and no React (reports/terminal_v2/PLAN.md §0.1, §0.5):
 *
 *  - `sourceOf(asOf, …)` turns a payload's as-of into the SourceChip state every panel header carries
 *    (LIVE · BREEZE / EOD · <day> / DELAYED · NSE · <age> / STALE <day> / CLOSE · <day> / OFFLINE / GAP): daily data
 *    shows its date as EOD · <day>, never a clock; by default an as-of ≥ STALE_AFTER_SESSIONS NSE sessions behind the
 *    last expected session reads STALE (FINAL ROUND D-TONE G3 — an explicit `maxAgeDays` keeps a plain calendar
 *    bound); no as-of at all reads OFFLINE. Live program (reports/live_nse): an intraday quote's age prints as '48s'
 *    (`ageS`), a pane mixing live and delayed rows adds ' · 40/52 LIVE' (`mix`), a quiet LIVE row reads 'LIVE·q' on
 *    the face (G5), the face always carries the source word (G7), and after the session a price reads CLOSE · <day>.
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

export type SourceState = 'live' | 'delayed' | 'stale' | 'offline' | 'gap' | 'degraded' | 'input' | 'reference' | 'closed'

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
  /**
   * Live program (reports/live_nse): the age in SECONDS of an intraday quote at render time. When set, the chip prints it
   * ('LIVE · BREEZE · 2s', 'DELAYED · NSE · 48s', 'STALE · NSE · 6m') instead of a clock; daily data never sets it.
   */
  ageS?: number | null
  /** a pane mixing live and non-live rows: how many of `total` rows are live (the chip adds ' · 40/52 LIVE') */
  mix?: { live: number; total: number } | null
  /**
   * FINAL ROUND G5 (reports/terminal_final, risk/TRUST_GAPS.md): a LIVE row on a healthy socket whose name simply has
   * not traded lately (data-service QUIET_LIVE_S ≤ 120 s, owner-accepted window — the POLICY is unchanged). The face
   * gets the on-face cue 'LIVE·q'; the hover keeps the trade age (the hint quoteSource already writes).
   */
  quiet?: boolean | null
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

// ── NSE session arithmetic (FINAL ROUND D-TONE, risk/TRUST_GAPS.md G3) ────────────────────────────────
// The one shared session-aware helper: weekend-safe Mon–Fri arithmetic (NSE holidays are NOT known here — the
// /api/data/health catalog is holiday-aware and takes precedence wherever it has answered; see ui/lib/dataHealthStore).

/** Daily (EOD) data is expected to have advanced to today's session by this IST wall-clock time (the evening pass SLO). */
export const EOD_EXPECTED_BY_IST = '21:30'
const EOD_EXPECTED_BY_MIN = 21 * 60 + 30
/** A daily as-of this many NSE sessions behind the last expected one reads STALE (was 4 calendar days, which let a
 *  2-session lag read as a calm 'EOD · <day>' — the 13 Nov trust audit's G3). */
export const STALE_AFTER_SESSIONS = 2

/**
 * The last NSE session day ('YYYY-MM-DD') whose EOD data is expected to be stored at `now`: the previous weekday, or
 * today once the IST clock passes EOD_EXPECTED_BY_IST on a weekday. Weekend-safe (Sat/Sun → Friday); holidays are not
 * known here, so a holiday week can read one session early — honest in the hover, corrected by the catalog when it answers.
 */
export function lastExpectedNseSessionDay(now: Date = new Date()): string {
  const ist = new Date(now.getTime() + 330 * 60_000)
  let t = Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate())
  const minutes = ist.getUTCHours() * 60 + ist.getUTCMinutes()
  const dow = new Date(t).getUTCDay()
  if (!(dow >= 1 && dow <= 5 && minutes >= EOD_EXPECTED_BY_MIN)) {
    do { t -= 86_400_000 } while (new Date(t).getUTCDay() === 0 || new Date(t).getUTCDay() === 6)
  }
  return new Date(t).toISOString().slice(0, 10)
}

/**
 * How many Mon–Fri NSE sessions `asOf` (date or timestamp; its IST day) sits behind the last expected session at
 * `now`. 0 when current (or ahead), null when unparsable. Weekend-safe: Friday data reads 0 behind all weekend and
 * Monday until the evening pass.
 */
export function nseSessionsBehind(asOf: string | null | undefined, now: Date = new Date()): number | null {
  if (!DAY_RE.exec(asOf ?? '')) return null
  const day = /^\d{4}-\d{2}-\d{2}$/.test(asOf as string) ? (asOf as string) : istDay(asOf)
  if (!day) return null
  const last = lastExpectedNseSessionDay(now)
  if (day >= last) return 0
  let t = Date.UTC(+day.slice(0, 4), +day.slice(5, 7) - 1, +day.slice(8, 10))
  const end = Date.UTC(+last.slice(0, 4), +last.slice(5, 7) - 1, +last.slice(8, 10))
  let n = 0
  while (t < end && n < 260) {
    t += 86_400_000
    const dw = new Date(t).getUTCDay()
    if (dw >= 1 && dw <= 5) n++
  }
  return n
}

export interface FooterDataTone {
  /** true = the stored equity EOD date is behind the last NSE session (D-TONE: the footer date turns amber) */
  amber: boolean
  title: string
}

/**
 * The footer's DATA-date tone (D-TONE G3, weekend-safe): behind = stored date < the last NSE session — the data-health
 * service's own `last_session` (holiday-aware) when the caller has one, else this file's Mon–Fri helper (21:30 IST
 * cutoff). Pure; the React side is ui/lib/dataHealthStore's useFooterDataTone.
 */
export function footerDataTone(latestDate: string | null | undefined, lastSessionFromHealth: string | null | undefined, now: Date = new Date()): FooterDataTone {
  const day = /^\d{4}-\d{2}-\d{2}/.exec(latestDate ?? '')?.[0] ?? null
  if (!day) return { amber: false, title: 'last stored equity EOD session (date unknown)' }
  const fromHealth = lastSessionFromHealth && /^\d{4}-\d{2}-\d{2}$/.test(lastSessionFromHealth) ? lastSessionFromHealth : null
  const last = fromHealth ?? lastExpectedNseSessionDay(now)
  const via = fromHealth ? 'per SYS › DATA' : 'Mon–Fri calendar; holidays not counted'
  if (day < last) {
    return { amber: true, title: `equity EOD store is behind: stored ${day} · last NSE session ${last} (${via}) — see SYS › DATA` }
  }
  return { amber: false, title: `last stored equity EOD session · last NSE session ${last} (${via})` }
}

export interface SourceOpts {
  /** the feed name printed on the chip */
  source?: string | null
  /** true while a live feed is ticking (the chip reads LIVE · <source>) */
  live?: boolean
  /**
   * a daily value older than this many calendar days reads STALE. When OMITTED, the default is session-aware
   * (D-TONE G3): an as-of ≥ STALE_AFTER_SESSIONS Mon–Fri sessions behind the last expected NSE session reads STALE,
   * so a 2-session lag no longer passes as a calm 'EOD · <day>'. Pass a number to keep a plain calendar bound
   * (weekly/monthly data), or null for data that is never stale by age.
   */
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
  const { source = null, live = false, gap = false, degraded = false, hint = null, now } = opts
  if (gap) return { state: 'gap', source, asOf: asOf ?? null, ageDays: ageDaysOf(asOf, now), hint }
  if (degraded) return { state: 'degraded', source, asOf: asOf ?? null, ageDays: ageDaysOf(asOf, now), hint }
  if (live) return { state: 'live', source, asOf: asOf ?? null, ageDays: 0, hint }
  const age = ageDaysOf(asOf, now)
  if (age == null) return { state: 'offline', source, asOf: asOf ?? null, ageDays: null, hint: hint ?? 'no as-of in the payload' }
  if ('maxAgeDays' in opts && opts.maxAgeDays !== undefined) {
    // an explicit calendar bound (weekly/monthly data, or null = never stale by age): the pre-G3 rule, unchanged
    if (opts.maxAgeDays != null && age > opts.maxAgeDays) return { state: 'stale', source, asOf: asOf ?? null, ageDays: age, hint }
  } else {
    // D-TONE G3 default: session-aware — ≥ STALE_AFTER_SESSIONS NSE sessions behind the last expected one reads STALE
    const behind = nseSessionsBehind(asOf, now ?? new Date())
    if (behind != null && behind >= STALE_AFTER_SESSIONS) {
      return { state: 'stale', source, asOf: asOf ?? null, ageDays: age,
               hint: hint ?? `${behind} NSE sessions behind the last expected session (Mon–Fri calendar; holidays not counted)` }
    }
  }
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

/** A quote's age for a chip: '0s' … '89s', then minutes ('6m') up to 90 min, then hours ('3h'); '' when unknown. */
export function fmtAgeS(ageS: number | null | undefined): string {
  if (ageS == null || !Number.isFinite(ageS)) return ''
  const a = Math.max(0, ageS)
  if (a < 90) return `${Math.round(a)}s`
  if (a < 90 * 60) return `${Math.round(a / 60)}m`
  return `${Math.round(a / 3600)}h`
}

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
 * The face form of a source word (FINAL ROUND G7: faces always carry the source word — 'DELAYED · RISK ENGINE · 15:03',
 * never a bare clock): any parenthetical is dropped (it stays in the hover) and the name is trimmed word-by-word to
 * 18 characters so the chip stays a chip. '' for no source.
 */
export function faceSource(src: string | null | undefined): string {
  if (!src) return ''
  let s = String(src).toUpperCase().replace(/\s*\(.*$/, '').trim()
  if (s.length <= 18) return s
  const words = s.split(/\s+/)
  while (words.length > 1 && words.join(' ').length > 18) words.pop()
  s = words.join(' ')
  return s.length <= 18 ? s : `${s.slice(0, 17)}…`
}

/**
 * The chip's text and hover text for a SourceInfo. Daily data shows its date ('DELAYED · 04 NOV'); an intraday as-of
 * from today shows the feed and its IST clock ('DELAYED · YAHOO · 10:42' — the source word always on the face, G7);
 * an older timestamp shows its date. A quiet LIVE row (G5) reads 'LIVE·q' on the face; the trade age stays in the hover.
 */
export function sourceChipText(s: SourceInfo, now: Date = new Date()): ChipText {
  const src = s.source ? String(s.source).toUpperCase() : ''
  const face = faceSource(s.source)
  const clock = chipClock(s.asOf)
  const today = clock !== '' && istDay(s.asOf) === istDay(now.toISOString())
  const day = chipDay(istDay(s.asOf))
  const stamp = today ? `${face ? `${face} · ` : ''}${clock}` : day
  const when = s.asOf && !/^\d{4}-\d{2}-\d{2}$/.test(s.asOf) ? `as of ${s.asOf}` : day ? `as of ${day}` : 'no as-of'
  const why = s.hint ? ` — ${s.hint}` : ''
  // live program: an intraday quote's age in seconds replaces the clock ('DELAYED · NSE · 48s'), and a pane mixing
  // live and non-live rows says how many are live (' · 40/52 LIVE')
  const dateOnly = !!s.asOf && /^\d{4}-\d{2}-\d{2}$/.test(s.asOf)
  const age = fmtAgeS(s.ageS)
  const ageTag = age ? ` · ${age}` : ''
  const mix = s.mix && s.mix.total > 0 && s.mix.live > 0 && s.mix.live < s.mix.total ? ` · ${s.mix.live}/${s.mix.total} LIVE` : ''
  const ageWhy = age ? ` · ${age} old` : ''
  // G5: a quiet LIVE face carries its cue ('LIVE·q'); the hover keeps the trade age (the hint)
  const liveWord = s.quiet ? 'LIVE·q' : 'LIVE'
  switch (s.state) {
    case 'live': return { label: `${liveWord}${face ? ` · ${face}` : ''}${ageTag}${mix}`, title: `Live feed${src ? ` (${src})` : ''}${s.quiet ? ' · quiet: no recent trade' : ''}${clock ? ` · last ${clock} IST` : ''}${ageWhy}${why}` }
    case 'delayed': return age
      ? { label: `DELAYED${face ? ` · ${face}` : ''}${ageTag}${mix}`, title: `Delayed quote${src ? ` from ${src}` : ''}${clock ? ` · last ${clock} IST` : ''}${ageWhy}${why}` }
      // live program (honesty rule): daily data cannot be live and says so — EOD + the date it describes
      : dateOnly && day
        ? { label: `EOD · ${day}`, title: `End-of-day data${src ? ` from ${src}` : ''} · as of ${day}: published once a day, not a live feed${why}` }
        : { label: `DELAYED${stamp ? ` · ${stamp}` : face ? ` · ${face}` : ''}`, title: `Stored or delayed data${src ? ` from ${src}` : ''} · ${when}${why}` }
    case 'stale': return age
      ? { label: `STALE${face ? ` · ${face}` : ''}${ageTag}${mix}`, title: `Older than expected${src ? ` (${src})` : ''}${clock ? ` · last ${clock} IST` : ''}${ageWhy}${why}` }
      : { label: `STALE${stamp ? ` · ${stamp}` : ''}`, title: `Older than expected${src ? ` (${src})` : ''} · ${when}${s.ageDays != null ? ` · ${Math.round(s.ageDays)} d old` : ''}${why}` }
    case 'closed': return { label: `CLOSE${day ? ` · ${day}` : ''}`, title: `NSE closed: the last session's close${src ? ` (${src})` : ''}${s.asOf ? ` · ${when}` : ''}${why}` }
    case 'gap': return { label: `GAP${day ? ` · ${day}` : ''}`, title: `No capture for this session${src ? ` (${src})` : ''}${why}` }
    case 'degraded': return { label: 'DEGRADED', title: `Feed connected but erroring${src ? ` (${src})` : ''}; values may be stale${why}` }
    case 'input': return { label: 'INPUT', title: `Computed from ${s.hint ?? 'your inputs'}; no stored or live feed behind this panel` }
    case 'reference': return { label: 'REFERENCE', title: `Fixed reference text (${s.hint ?? 'documentation'}); no data feed behind this panel` }
    default: return { label: 'OFFLINE', title: `No source is responding${src ? ` (${src})` : ''}${why}` }
  }
}

/**
 * D-TONE (G3): a panel whose dataset has a `dataset_catalog` row adopts the catalog's verdict for the chip's tone.
 * red/gap → the STALE treatment (the face keeps its own date/age text: 'STALE · 09 NOV'); amber → the hover names the
 * verdict (the face is unchanged); fresh/live → unchanged. Live/input/reference chips are never downgraded (a live feed
 * is its own evidence). Pure — the caller brings the verdict (ui/lib/dataHealthStore reads /api/data/health).
 */
export function applyCatalogVerdict(info: SourceInfo, verdict: string | null | undefined, note?: string | null): SourceInfo {
  if (!verdict || info.state === 'live' || info.state === 'input' || info.state === 'reference') return info
  if (verdict !== 'red' && verdict !== 'gap' && verdict !== 'amber') return info
  const why = `catalog: ${verdict}${note ? ` — ${note}` : ''} (SYS › DATA)`
  const hint = info.hint ? `${info.hint} · ${why}` : why
  if (verdict === 'red' || verdict === 'gap') return { ...info, state: 'stale', hint }
  return { ...info, hint }
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
