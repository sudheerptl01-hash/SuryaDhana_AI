/**
 * GOLD page presentation rules (PLAN §f, 0.1 #8/#10): the health sentence's suffix, badge rendering, unit conversion,
 * the one-line echoes for WEI / BRF / MCXG, lag chips and session labels.
 *
 * Pure module (no React, no DOM, no kit import): unit-tested under plain node by
 * ui/components/__tests__/gold.check.ts. Numbers are printed through ui/lib/format (U+2212 minus, en-IN grouping);
 * colours are returned as TONE NAMES so the component maps them to the kit tokens (context metrics → 'muted',
 * never green/red: PLAN §f.3).
 */
import { MINUS, fmtFixed, fmtSigned, fmtSignedInr, indianGrouping } from '@/lib/format'
import type { Badge, ComexSpec, FairLeg, Freshness, GoldBrief, GoldEvent, GoldHealth, HealthFair, HealthGauge, Unit } from './types'

export { MINUS }

// ── the verdict sentence ────────────────────────────────────────────────────────────────────────

/** Every health verdict ends with these words (PLAN §f.4, 0.1 #5). */
export const HEALTH_SUFFIX = 'describes, does not predict'
/** What a panel shows when a series has no catalog verdict (PLAN §f.2). */
export const NO_VERDICT = 'no verdict — not published'

/**
 * The verdict line as rendered: never empty (the placeholder instead), always ending with the suffix. The server
 * builds the clauses; this guard keeps the promise on screen even if a clause-only line arrives.
 */
export function healthLine(line: string | null | undefined): string {
  // the server's f-strings print an ASCII hyphen before a negative number ("real yield -4 bp", "GLD -2.9 t"); on screen a
  // signed number wears U+2212 (M rule) — only a hyphen glued to a digit after a space / bracket / start is a sign
  // ("DEC-26→FEB-27" keeps its hyphens)
  const t = (line ?? '').replace(/\s+/g, ' ').trim().replace(/(^|[\s(])-(?=\d)/g, `$1${MINUS}`)
  if (!t) return NO_VERDICT
  const stripped = t.replace(/[\s·.;,—-]+$/u, '')
  if (stripped.toLowerCase().endsWith(HEALTH_SUFFIX)) return stripped
  return `${stripped} · ${HEALTH_SUFFIX}`
}

/** The verdict's head words ("WEAK WEEK, DOLLAR-DRIVEN"): the text before the first ' · ', upper-cased. */
export function verdictWords(line: string | null | undefined, maxChars = 24): string {
  const head = (line ?? '').split(' · ')[0].trim().toUpperCase()
  if (!head || head === NO_VERDICT.toUpperCase()) return ''
  return head.length > maxChars ? `${head.slice(0, maxChars - 1).trimEnd()}…` : head
}

/**
 * The verdict words of a health payload: the server's `verdict.headline` (the head words it prints on its own lines,
 * API_CONTRACT §2.1) first; the first clause of the sentence only as a fallback for a payload without a headline.
 * A headline-less payload whose first clause is a number clause ("FUNDS NET 104,206 …") is NOT a verdict: '' then.
 */
export function healthWords(h: GoldHealth | null | undefined, maxChars = 24): string {
  if (!h) return ''
  const head = h.verdict?.headline?.trim()
  if (head) return verdictWords(head, maxChars)
  const first = verdictWords(h.verdict?.line ?? h.line, maxChars)
  return /\d/.test(first) ? '' : first
}

// ── timestamps (the store's naive ISO strings are UTC: data-service gold/db.py strips tzinfo) ───────

/**
 * Parse an ISO timestamp as the store sends it. A string with no offset and no 'Z' is naive UTC (gold/db.py
 * `isoformat()` after stripping tzinfo), NOT local time: `new Date('2026-10-24T20:00:00')` would read it as local
 * and put the COT release 5.5 h early on an IST machine. Dates ('2026-10-24') stay UTC midnight. Invalid → null.
 */
export function parseIso(iso: string | null | undefined): Date | null {
  if (!iso) return null
  const s = iso.trim()
  const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(s)
  const d = new Date(naive ? `${s.replace(' ', 'T')}Z` : s)
  return Number.isNaN(d.getTime()) ? null : d
}

/** A composite is a defect (PLAN §f.4): any `score` / `of` / `tightness` key on the health payload is rejected. */
export function hasCompositeScore(payload: unknown): boolean {
  if (!payload || typeof payload !== 'object') return false
  const keys = Object.keys(payload as Record<string, unknown>).map(k => k.toLowerCase())
  return keys.some(k => k === 'score' || k === 'of' || k === 'tightness' || k === 'tightness_index' || k === 'composite')
}

// ── the rendering gate (PLAN §f.2) ──────────────────────────────────────────────────────────────

export type Gate = 'ok' | 'no-verdict' | 'unknown'

/**
 * May a number for `seriesId` render? 'ok' when the catalog carries a PUBLISH-CORE / PUBLISH-CONTEXT row with a badge;
 * 'no-verdict' when the catalog is loaded and the series is missing, LINK-ONLY or DO-NOT-PUBLISH; 'unknown' when no
 * catalog is available yet (the panel then renders with a "catalog unavailable" note instead of going blank) or the
 * metric is derived on the request path (no series id).
 */
export function publishGate(catalog: Record<string, { verdict?: string; badge?: string }> | null | undefined, seriesId: string | null | undefined): Gate {
  if (!seriesId) return 'unknown'
  if (!catalog || Object.keys(catalog).length === 0) return 'unknown'
  const row = catalog[seriesId]
  if (!row || !row.badge) return 'no-verdict'
  return row.verdict === 'PUBLISH-CORE' || row.verdict === 'PUBLISH-CONTEXT' ? 'ok' : 'no-verdict'
}

// ── badges (PLAN §f.1) ──────────────────────────────────────────────────────────────────────────

export type Tone = 'muted' | 'cyan' | 'violet' | 'amber' | 'green' | 'red' | 'text'

export interface BadgeSpec { label: string; tone: Tone; title: string }

/** Badge chip text, tone and hover text. `context` is the neutral tone: it never reads as a buy/sell colour. */
export const BADGES: Readonly<Record<Badge, BadgeSpec>> = Object.freeze({
  signal: { label: 'SIGNAL', tone: 'green', title: 'A pre-registered study PASSED as a forecast (|t| ≥ 2 in both halves after costs). None today.' },
  context: { label: 'CONTEXT', tone: 'muted', title: 'Describes what happened (PASS as a description) or context only; no forecasting power was found (G-STUDY 26 Oct 2026).' },
  arithmetic: { label: 'ARITHMETIC', tone: 'cyan', title: 'An identity, cost or spec (fair value, landed cost, carry, tick value). No claim about the future.' },
  heuristic: { label: 'HEURISTIC', tone: 'violet', title: 'A house rule without evidence (the ₹300 chase limit, the headline risk count); the measured error is shown where one exists.' },
})

/** Longest evidence text printed on a badge chip; the full text stays in the chip's title (hover). */
export const EVIDENCE_CHIP_CHARS = 32

export function badgeSpec(badge: Badge | string | null | undefined, evidence?: string | null): BadgeSpec {
  const b = (badge && badge in BADGES ? BADGES[badge as Badge] : BADGES.context)
  if (!evidence) return b
  // the chip names the study (the text up to the first ':'); the finding after it is on hover, so a narrow panel's
  // header never overflows ("CONTEXT · G-STUDY 26 Oct 2026", title "… explains the week — does not forecast")
  const colon = evidence.indexOf(':')
  const head = colon > 0 && colon < EVIDENCE_CHIP_CHARS ? evidence.slice(0, colon) : evidence
  const short = head.length > EVIDENCE_CHIP_CHARS ? `${head.slice(0, EVIDENCE_CHIP_CHARS - 1).trimEnd()}…` : head
  return { ...b, label: `${b.label} · ${short}`, title: `${b.title} ${evidence}` }
}

/** A source name short enough for a chip ('SPDR Gold Shares (displayed with attribution)' → 'SPDR GOLD SHARES…'). */
function chipSource(source: string | null | undefined, max = 18): string {
  if (!source) return ''
  const s = source.toUpperCase()
  return s.length > max ? `${s.slice(0, max - 1).trimEnd()}…` : s
}

/** True when the metric may wear a green/red colour: price changes and the arithmetic fair-vs-live comparison only. */
export function mayColour(badge: Badge | string | null | undefined, isPriceChange = false): boolean {
  return isPriceChange || badge === 'arithmetic'
}

/** Tone for a signed value under the colour rule: price changes green/red; context metrics stay neutral. */
export function changeTone(v: number | null | undefined, allowColour: boolean): Tone {
  if (!allowColour || v == null || !Number.isFinite(v) || v === 0) return 'muted'
  return v > 0 ? 'green' : 'red'
}

/** Direction arrow for a change (allowed on context metrics: PLAN §f.3 permits arrows, not colours). */
export function arrow(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v) || v === 0) return ''
  return v > 0 ? '▲' : '▼'
}

// ── freshness → lag chip (PLAN 0.1 #10) ─────────────────────────────────────────────────────────

export interface LagChip { label: string; tone: Tone; title: string }

/** LIVE / DELAYED / STALE / OFFLINE from a freshness block; STALE also when older than the catalog's max_age_days. */
export function lagChip(f: Freshness | null | undefined, maxAgeDays?: number | null): LagChip {
  if (!f) return { label: 'NO DATA', tone: 'muted', title: 'No freshness block from the server' }
  const ageDays = f.age_days ?? (f.age_s != null ? f.age_s / 86_400 : null)
  const tooOld = maxAgeDays != null && ageDays != null && ageDays > maxAgeDays
  const why = f.reason ? ` — ${f.reason}` : ''
  const src = f.source ? ` · ${f.source}` : ''
  if (f.state === 'unavailable') return { label: 'OFFLINE', tone: 'red', title: `No source is responding${why}` }
  if (f.state === 'stale' || tooOld) return { label: 'STALE', tone: 'amber', title: `Last stored value${src}${ageDays != null ? ` · ${ageDays.toFixed(ageDays < 2 ? 1 : 0)} d old` : ''}${why}` }
  if (f.state === 'live') return { label: `LIVE${f.source ? ` · ${chipSource(f.source)}` : ''}`, tone: 'green', title: `Live feed${src}` }
  return { label: `DELAYED${f.source ? ` · ${chipSource(f.source)}` : ''}`, tone: 'muted', title: `Delayed data${src}${f.as_of ? ` · as of ${f.as_of}` : ''}${why}` }
}

// ── session labels (PLAN 0.1 #8: settlement by session, never the file date) ────────────────────

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** '2026-10-22' → 'Thu 22 Oct' (the day the session belongs to); '' for anything unparsable. */
export function dayLabel(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return ''
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  return `${DAYS[d.getUTCDay()]} ${m[3]} ${MONTHS[+m[2] - 1]}`
}

/** 'Thu 22 Oct settlement' (the label every MCX settlement carries). */
export function sessionLabel(iso: string | null | undefined, serverLabel?: string | null): string {
  if (serverLabel) return serverLabel
  const d = dayLabel(iso)
  return d ? `${d} settlement` : 'settlement'
}

/** 'GCZ26.CMX' → 'GCZ26'; 'GC=F' → 'GC1' (the continuous front is named GC1 everywhere on the page). */
export function comexCode(symbol: string | null | undefined): string {
  if (!symbol) return '—'
  if (symbol === 'GC=F') return 'GC1'
  return symbol.replace(/\.CMX$/, '')
}

/** 'GCZ26' → 'DEC-26' (month code → month name, two-digit year). */
export function comexMonthLabel(symbol: string | null | undefined): string {
  const m = /^[A-Z]{1,2}([FGHJKMNQUVXZ])(\d{2})/.exec(comexCode(symbol))
  if (!m) return comexCode(symbol)
  const mon = { F: 'JAN', G: 'FEB', H: 'MAR', J: 'APR', K: 'MAY', M: 'JUN', N: 'JUL', Q: 'AUG', U: 'SEP', V: 'OCT', X: 'NOV', Z: 'DEC' }[m[1]]
  return `${mon}-${m[2]}`
}

/** '2026-12-04' → 'DEC-26' (an MCX expiry as the contract-month label). */
export function expiryMonthLabel(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})/.exec(iso ?? '')
  return m ? `${MONTHS[+m[2] - 1].toUpperCase()}-${m[1].slice(2)}` : '—'
}

// ── units (page-global picker, a.1) ─────────────────────────────────────────────────────────────

export const GRAMS_PER_OZ = 31.1034768
export const GRAMS_PER_TOLA = 11.6638038

export const UNIT_LABEL: Readonly<Record<Unit, string>> = Object.freeze({
  usd_oz: '$/oz', inr_10g: '₹/10 g', inr_g: '₹/g', usd_g: '$/g', tola: '₹/tola',
})

/** A $/oz price in the chosen unit (₹ units need USD/INR; null when it is missing). */
export function convertUsdOz(usdPerOz: number | null | undefined, unit: Unit, usdinr: number | null | undefined): number | null {
  if (usdPerOz == null || !Number.isFinite(usdPerOz)) return null
  if (unit === 'usd_oz') return usdPerOz
  if (unit === 'usd_g') return usdPerOz / GRAMS_PER_OZ
  if (usdinr == null || !Number.isFinite(usdinr)) return null
  const inrPerGram = (usdPerOz * usdinr) / GRAMS_PER_OZ
  if (unit === 'inr_10g') return inrPerGram * 10
  if (unit === 'inr_g') return inrPerGram
  return inrPerGram * GRAMS_PER_TOLA
}

/** Decimals a unit prints with: 2 dp for prices (exchange precision), 3 for $/g. */
export function unitDp(unit: Unit): number {
  return unit === 'usd_g' ? 3 : 2
}

/** A converted price with its currency glyph: '$4,007.90', '₹1,46,079.00'. */
export function fmtInUnit(usdPerOz: number | null | undefined, unit: Unit, usdinr: number | null | undefined): string {
  const v = convertUsdOz(usdPerOz, unit, usdinr)
  if (v == null) return '—'
  const glyph = unit === 'usd_oz' || unit === 'usd_g' ? '$' : '₹'
  const s = fmtFixed(v, unitDp(unit))
  return s.startsWith(MINUS) ? `${MINUS}${glyph}${s.slice(1)}` : `${glyph}${s}`
}

/** '$4,007.90' — a USD price at 2 dp (en-IN grouping is identical below 1 lakh; above it the page reads ₹ anyway). */
export function fmtUsd(v: number | null | undefined, dp = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = fmtFixed(v, dp)
  return s.startsWith(MINUS) ? `${MINUS}$${s.slice(1)}` : `$${s}`
}

/** Contracts in thousands with a sign: 104206 → '+104.2k', −2883 → '−2.9k', 0 → '0.0k'. */
export function fmtK(v: number | null | undefined, dp = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${fmtSigned(v / 1000, dp)}k`
}

/**
 * A COUNT (contracts, lots, ounces, tonnes, dollars) with Western grouping, U+2212: 105562 → '105,562'. Rupees keep the
 * Indian grouping (`fmtInr0`); nothing else on the gold page does — no gold desk writes '1,05,562' contracts
 * (C-TRADER-20), and the verdict sentence the server builds prints '105,562' (C-BEGINNER-18 / C-DATA-18: one grouping
 * per quantity on a page).
 */
export function fmtCount(v: number | null | undefined, dp = 0): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const r = Number(v.toFixed(dp))
  const s = Math.abs(r).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return r < 0 ? `${MINUS}${s}` : s
}

/** A signed count: '+1,356' / '−2,883' / '0'. */
export function fmtSignedCount(v: number | null | undefined, dp = 0): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const r = Number(v.toFixed(dp))
  if (r === 0) return (0).toFixed(dp)
  return r > 0 ? `+${fmtCount(r, dp)}` : fmtCount(r, dp)
}

/** 1 → '1st', 2 → '2nd', 3 → '3rd', 11–13 → 'th', 93 → '93rd' (C-BEGINNER-19: never '93th'). */
export function ordinal(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const i = Math.round(n)
  const mod100 = Math.abs(i) % 100
  const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[Math.abs(i) % 10] ?? 'th'
  return `${i}${suffix}`
}

/** Observations a percentile needs before it is printed (C-TRADER-23: a percentile over 14 months is noise). */
export const PERCENTILE_MIN_N = 60

/**
 * '93rd percentile (1 y)' — the word is 'percentile', never 'pct' (which the page uses for percent, C-BEGINNER-19);
 * with `n` below PERCENTILE_MIN_N the text says what history exists instead ('history since 2025-09', n = 14).
 */
export function percentileText(p: number | null | undefined, window?: string | null, n?: number | null, since?: string | null): string {
  if (n != null && n < PERCENTILE_MIN_N) return `${n} obs.${since ? ` since ${since}` : ''} — too few for a percentile`
  if (p == null || !Number.isFinite(p)) return '—'
  return `${ordinal(p)} percentile${window ? ` (${window})` : ''}`
}

/** A signed percentage with a thin space before %, U+2212: '+0.4 %', '−2.8 %'. */
export function fmtSignedPctSp(v: number | null | undefined, dp = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${fmtSigned(v, dp)} %`
}

// ── the one-line echoes (PLAN §b; the only off-page repeats of a gold number: WEI, BRF, MCXG) ────

/** The trailing "GOLD ›" of a server line (the chip beside the text renders it). */
export function stripGoChip(line: string): string {
  return line.replace(/\s*·?\s*GOLD\s*›\s*$/u, '').trim()
}

/**
 * WEI's second line under the GC=F row: the SERVER's `line` (`lines.wei`) rendered verbatim minus the "GOLD ›" the
 * chip renders (API_CONTRACT §2.1; the server builds it from the same gauges it logs with). The client composition
 * below is the fallback for a payload without one.
 */
export function weiLine(h: GoldHealth | null | undefined): string {
  if (!h) return 'GOLD · health unavailable'
  const server = (h.lines?.wei ?? h.line ?? '').trim()
  if (server) return stripGoChip(server)
  return weiLineFallback(h)
}

/** Client-composed WEI line (verdict words ≤ 24 chars; basis; COT; roll), used only when the server sent no `line`. */
export function weiLineFallback(h: GoldHealth): string {
  const parts: string[] = ['GOLD']
  const words = healthWords(h)
  if (words) parts.push(words)
  if (h.fair?.basis_pct != null) parts.push(`basis ${fmtSignedPctSp(h.fair.basis_pct, 1)}`)
  const cot = gauge(h, 'positioning')
  if (cot?.value != null) parts.push(`COT MM ${fmtK(cot.value)}${cot.change != null ? ` (${fmtK(cot.change)})` : ''}`)
  const roll = gauge(h, 'curve')
  if (roll?.front && roll.next) parts.push(`roll ${roll.front.replace(/-\d\d$/, '')}→${roll.next.replace(/-\d\d$/, '')}${roll.fnd_date ? ` · FND ${dayLabel(roll.fnd_date).slice(4)}` : roll.days_to_fnd != null ? ` · FND in ${roll.days_to_fnd} d` : ''}`)
  else if (roll?.fnd_date) parts.push(`FND ${dayLabel(roll.fnd_date).slice(4)}`)
  return parts.join(' · ')
}

/** The gauge with `key` (or whose key starts with it), if the server sent one. */
export function gauge(h: GoldHealth | null | undefined, key: string): HealthGauge | null {
  const gs = h?.gauges ?? []
  return gs.find(g => g.key === key) ?? gs.find(g => g.key.startsWith(key)) ?? null
}

export type BrfPhase = 'before_open' | 'after_open' | 'holiday'

/** One coloured run of the BRF line: only the OK / WAIT token and the arithmetic miss / gap may wear a colour. */
export interface BrfSegment { text: string; tone: Tone }

/**
 * BRF's single gold line (PLAN §b): the SERVER's `brf_line` (`lines.brf`) rendered verbatim minus the "GOLD ›" the
 * chip renders. The server builds it from the rule it logs with — before the open `Gold open: fair ₹X (gap −Y) · WAIT
 * · <words>`, after the captured open `Gold opened ₹X vs fair ₹Y (miss ₹Z) · <words>` from the 08:45 SNAPSHOT
 * (`fair.snapshot_fair` / `snapshot_error`, never the live fair value, so the miss does not drift through the day),
 * on an MCX closure `Gold: MCX closed (…)`. `brfLineFallback` composes the same forms when the server sent none.
 */
export function brfLine(h: GoldHealth | null | undefined, istMinutes: number, threshold = 300): { text: string; phase: BrfPhase; tone: Tone; segments: BrfSegment[] } {
  if (!h) return { text: 'Gold: health unavailable', phase: 'before_open', tone: 'muted', segments: [{ text: 'Gold: health unavailable', tone: 'muted' }] }
  const server = (h.lines?.brf ?? h.brf_line ?? '').trim()
  const text = server ? indianGrouping(stripGoChip(server)) : brfLineFallback(h, istMinutes)   // ₹122,271 → ₹1,22,271 (C1-08)
  const phase: BrfPhase = /^Gold: MCX closed/.test(text) ? 'holiday' : /^Gold opened|^Gold: MCX ₹/.test(text) ? 'after_open' : 'before_open'
  const segments = brfSegments(text, threshold)
  const coloured = segments.find(s => s.tone !== 'muted')
  return { text, phase, tone: coloured?.tone ?? 'muted', segments }
}

/**
 * Split a BRF line into runs for rendering (PLAN §f.3: colour only on the arithmetic comparison, never on the context
 * verdict words): the `OK` token green, `WAIT` red, the `(miss ₹…)` group green within the chase limit else amber;
 * everything else — fair, gap, the verdict words, the holiday — is the neutral token.
 */
export function brfSegments(text: string, threshold = 300): BrfSegment[] {
  const out: BrfSegment[] = []
  const parts = text.split(' · ')
  parts.forEach((p, i) => {
    const sep = i < parts.length - 1 ? ' · ' : ''
    if (p === 'OK' || p === 'WAIT') { out.push({ text: p, tone: p === 'OK' ? 'green' : 'red' }); if (sep) out.push({ text: sep, tone: 'muted' }); return }
    const m = /\(miss (?:₹\s?)?([−+-]?)₹?([\d,]+)\)/u.exec(p)      // server "miss ₹−2,880" or client "miss −₹2,880"
    if (m) {
      const miss = Number(`${m[1].replace(MINUS, '-')}${m[2].replace(/,/g, '')}`)
      const at = p.indexOf(m[0])
      if (at > 0) out.push({ text: p.slice(0, at), tone: 'muted' })
      out.push({ text: m[0], tone: Number.isFinite(miss) && Math.abs(miss) <= threshold ? 'green' : 'amber' })
      const rest = p.slice(at + m[0].length) + sep
      if (rest) out.push({ text: rest, tone: 'muted' })
      return
    }
    out.push({ text: p + sep, tone: 'muted' })
  })
  return out
}

/** Client-composed BRF line (the same three forms as the server), used only when the server sent no `brf_line`. */
export function brfLineFallback(h: GoldHealth, istMinutes: number): string {
  const f = h.fair ?? ({} as HealthFair)
  const words = healthWords(h)
  const tail = words ? ` · ${words}` : ''
  const hol = f.mcx_holiday
  if (hol?.closure === 'full' || (hol?.closure === 'morning' && istMinutes < 17 * 60 && f.actual_open == null)) {
    return `Gold: MCX closed (${hol.name}${hol.closure === 'morning' ? `, opens ${(hol.opens_at ?? '').slice(11, 16) || hol.opens_at || '17:00'}` : ''})${tail}`
  }
  if (f.actual_open != null && f.snapshot_fair) {       // the morning call: the 08:45 snapshot, not the live fair value
    const miss = f.snapshot_error
    return `Gold opened ${fmtInr0(f.actual_open)} vs fair ${fmtInr0(f.snapshot_fair)}${miss != null ? ` (miss ${fmtSignedInr(miss)})` : ''}${tail}`
  }
  const fair = f.fair_value
  if (!fair) return `Gold open: fair value unavailable${tail}`
  const gap = f.gap_vs_settlement ?? (f.settlement != null ? fair - f.settlement : null)
  const parts = [`Gold open: fair ${fmtInr0(fair)}${gap != null ? ` (gap ${fmtSigned(gap, 0)})` : ''}`]
  if (f.premium_rupees != null) parts.push(Math.abs(f.premium_rupees) <= 300 ? 'OK' : 'WAIT')
  return parts.join(' · ') + tail
}

// ── fair-model legs ──────────────────────────────────────────────────────────────────────────────

/** The price of a fair-model leg: the server sends `{symbol, price, as_of}` (API_CONTRACT §2.1); a bare number is
 *  tolerated for the legacy MCXG composer only. */
export function legPrice(leg: FairLeg | number | null | undefined): number | null {
  if (leg == null) return null
  if (typeof leg === 'number') return Number.isFinite(leg) ? leg : null
  return typeof leg.price === 'number' && Number.isFinite(leg.price) ? leg.price : null
}

/** The symbol of a fair-model leg (null for the legacy bare-number shape). */
export function legSymbol(leg: FairLeg | number | null | undefined): string | null {
  return leg != null && typeof leg === 'object' && typeof leg.symbol === 'string' && leg.symbol ? leg.symbol : null
}

/** MCXG's one-line overlay (PLAN §b): no implied-premium prose. */
export function mcxOverlayLine(f: HealthFair | null | undefined): string {
  if (!f) return 'COMEX × rupee: unavailable'
  const parts = [
    `COMEX ${comexCode(f.comex_symbol ?? legSymbol(f.comex) ?? 'GC=F')} ${fmtUsd(legPrice(f.comex), 1)}`,
    `₹/$ ${fmtFixed(legPrice(f.usdinr), 2)}`,
    `duty-paid landed ${fmtInr0(f.duty_paid_landed)}`,
    `fair ${fmtInr0(f.fair_value)}`,
    `live vs fair ${f.premium_rupees != null ? fmtSignedInr(f.premium_rupees) : '—'}`,
  ]
  return parts.join(' · ')
}

/** ₹ with no decimals and Indian grouping, U+2212: ₹1,44,181 / −₹5. */
export function fmtInr0(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = fmtFixed(v, 0)
  return s.startsWith(MINUS) ? `${MINUS}₹${s.slice(1)}` : `₹${s}`
}

// ── misc ────────────────────────────────────────────────────────────────────────────────────────

/** Seconds → 'in 3h04m' / 'in 12m' / 'now'. */
export function countdown(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return 'now'
  const h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60)
  return h > 0 ? `${h}h${String(m).padStart(2, '0')}m` : `${m}m`
}

/** ISO instant → 'HH:MM IST' (24 h). */
export function istClock(iso: string | null | undefined): string {
  const d = parseIso(iso)
  if (!d) return '—'
  return `${d.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })} IST`
}

/** ISO instant → 'HH:MMZ' (the gold-api cross-check chip prints UTC). */
export function utcClock(iso: string | null | undefined): string {
  const d = parseIso(iso)
  if (!d) return ''
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}Z`
}

/** Simple returns in % between the first and last finite values of a window. */
export function pctChange(from: number | null | undefined, to: number | null | undefined): number | null {
  if (from == null || to == null || !Number.isFinite(from) || !Number.isFinite(to) || from === 0) return null
  return (to / from - 1) * 100
}

// ── CONTRACTS (c.selector diff strip, c.mcx roll warning) ──────────────────────────────────────

/** The fields the diff strip compares when the family changes (PLAN c.selector, G-INDIA §4.3). */
export const DIFF_KEYS = ['tick_value', 'margin', 'cost_pct', 'liquidity', 'purity', 'hedge_ratio'] as const
export type DiffKey = (typeof DIFF_KEYS)[number]

export interface DiffRow { key: DiffKey; label: string; from: string; to: string; changed: boolean }

interface FamilyLike {
  code: string; purity: string; expiry_rule: string; tick_value: number | null; hedge_ratio_oz?: number | null
  round_trip?: { pct: number | null; total: number | null } | null
  expiries: { oi?: number | null; margin_inr?: number | null; margin_pct?: number | null }[]
}

const front = (f: FamilyLike) => f.expiries.reduce<FamilyLike['expiries'][number] | null>((best, e) => (best == null || (e.oi ?? -1) > (best.oi ?? -1) ? e : best), null)

/** What changes when you switch from family `a` to family `b` (both from `/api/gold/contracts`). */
export function contractDiff(a: FamilyLike | null | undefined, b: FamilyLike | null | undefined): DiffRow[] {
  if (!a || !b) return []
  const fa = front(a), fb = front(b)
  const rows: DiffRow[] = [
    { key: 'tick_value', label: 'tick value', from: fmtInr0(a.tick_value), to: fmtInr0(b.tick_value), changed: a.tick_value !== b.tick_value },
    { key: 'margin', label: 'NRML margin', from: fa?.margin_inr != null ? `${fmtInr0(fa.margin_inr)}${fa.margin_pct != null ? ` (${fmtFixed(fa.margin_pct, 2)} %)` : ''}` : '—',
      to: fb?.margin_inr != null ? `${fmtInr0(fb.margin_inr)}${fb.margin_pct != null ? ` (${fmtFixed(fb.margin_pct, 2)} %)` : ''}` : '—', changed: fa?.margin_inr !== fb?.margin_inr },
    { key: 'cost_pct', label: 'round trip', from: a.round_trip?.pct != null ? `${fmtFixed(a.round_trip.pct, 3)} %` : '—', to: b.round_trip?.pct != null ? `${fmtFixed(b.round_trip.pct, 3)} %` : '—',
      changed: a.round_trip?.pct !== b.round_trip?.pct },
    { key: 'liquidity', label: 'front OI', from: fa?.oi != null ? `${fmtFixed(fa.oi, 0)} lots` : '—', to: fb?.oi != null ? `${fmtFixed(fb.oi, 0)} lots` : '—', changed: fa?.oi !== fb?.oi },
    { key: 'purity', label: 'purity · settlement', from: `${a.purity} · ${a.expiry_rule}`, to: `${b.purity} · ${b.expiry_rule}`, changed: a.purity !== b.purity || a.expiry_rule !== b.expiry_rule },
    { key: 'hedge_ratio', label: 'COMEX hedge', from: a.hedge_ratio_oz != null ? `≈ ${fmtFixed(a.hedge_ratio_oz, 2)} oz` : '—', to: b.hedge_ratio_oz != null ? `≈ ${fmtFixed(b.hedge_ratio_oz, 2)} oz` : '—',
      changed: a.hedge_ratio_oz !== b.hedge_ratio_oz },
  ]
  return rows
}

/** "roll in progress" when the front month's OI is falling faster than the next month's is rising (G-INDIA §4.3). */
export function rollWarning(frontOiChange: number | null | undefined, nextOiChange: number | null | undefined): string | null {
  if (frontOiChange == null || nextOiChange == null || !Number.isFinite(frontOiChange) || !Number.isFinite(nextOiChange)) return null
  if (frontOiChange < 0 && nextOiChange > 0 && Math.abs(frontOiChange) > nextOiChange) return 'roll in progress: front OI falling faster than the next month is rising'
  if (frontOiChange < 0 && nextOiChange > 0) return 'roll under way: positions moving to the next month'
  return null
}

/** Implied annualised carry between two prices `days` apart: (F2/F1 − 1) × 365/days, in %. */
export function annualisedCarry(f1: number | null | undefined, f2: number | null | undefined, days: number | null | undefined): number | null {
  if (f1 == null || f2 == null || days == null || !Number.isFinite(f1) || !Number.isFinite(f2) || f1 === 0 || !(days > 0)) return null
  return (f2 / f1 - 1) * (365 / days) * 100
}

/** Whole calendar days from `from` to `to` (ISO dates); null when either is unparsable. */
export function daysBetween(from: string | null | undefined, to: string | null | undefined): number | null {
  const a = /^(\d{4})-(\d{2})-(\d{2})/.exec(from ?? ''), b = /^(\d{4})-(\d{2})-(\d{2})/.exec(to ?? '')
  if (!a || !b) return null
  return Math.round((Date.UTC(+b[1], +b[2] - 1, +b[3]) - Date.UTC(+a[1], +a[2] - 1, +a[3])) / 86_400_000)
}

/** 'in 12 d' / 'today' / '3 d ago' for a date relative to `today` (ISO). */
export function daysWord(date: string | null | undefined, today: string): string {
  const n = daysBetween(today, date)
  if (n == null) return '—'
  if (n === 0) return 'today'
  return n > 0 ? `in ${n} d` : `${-n} d ago`
}

// ── HEALTH gauges: the change text branches on the change's OWN unit (C-DATA-7 / C-BEGINNER-21 / C-DATA-18) ─────

/**
 * The Δ text of a gauge tile. The server's `change_unit` wins; without one the fallback is the tile's kind: a price
 * tile's change is a % of price, a '$/oz' premium's change is $/oz (the Shanghai premium: '+$47.36/oz W', never
 * '+47.36 %'), a '%' level's change is in bp, contracts / tonnes keep their unit. `change_bp` stands in when `change`
 * is null (the real-yield tile). Empty when nothing is known.
 */
export function gaugeChangeText(g: Pick<HealthGauge, 'change' | 'change_unit' | 'change_window' | 'change_bp' | 'unit' | 'key'>, isPriceTile = false): string {
  const win = g.change_window ? ` ${g.change_window}` : ''
  if (g.change == null && g.change_bp != null && Number.isFinite(g.change_bp)) return `${fmtSigned(g.change_bp, 0)} bp${win}`.trim()
  if (g.change == null || !Number.isFinite(g.change)) return ''
  const cu = (g.change_unit ?? '').toLowerCase()
  const u = (g.unit ?? '').toLowerCase()
  const unit = cu || (isPriceTile ? '%' : u === 'usd/oz' || u === '$/oz' ? '$/oz' : u === '%' || u === 'pct' ? 'bp' : u)
  switch (unit) {
    case '%': case 'pct': return `${fmtSignedPctSp(g.change, 2)}${win}`
    case 'bp': return `${fmtSigned(u === '%' || u === 'pct' ? (cu ? g.change : g.change * 100) : g.change, 0)} bp${win}`
    case 'pp': return `${fmtSigned(g.change, 2)} pp${win}`
    case '$/oz': case 'usd/oz': return `${g.change < 0 ? MINUS : '+'}$${fmtFixed(Math.abs(g.change), 2)}/oz${win}`
    case 'contracts': return `${fmtSignedCount(g.change)} contracts${win}`
    case 't': case 'tonnes': return `${fmtSigned(g.change, 2)} t${win}`
    case 'index': return `${fmtSigned(g.change, 2)}${win}`
    default: return `${fmtSigned(g.change, 2)}${unit ? ` ${unit}` : ''}${win}`
  }
}

// ── h.events: the whole week, ordered by what can move the price (C-TRADER-11 / C-DATA-21) ─────────────────────

const IMPACT_RANK: Record<string, number> = { high: 0, medium: 1, context: 2, low: 3 }

/** 0 = High … 3 = Low; a COMEX / MCX roll date or a holiday ('context') sits between Medium and Low. */
export function eventImpactRank(e: Pick<GoldEvent, 'impact' | 'kind'>): number {
  const k = (e.impact ?? '').toLowerCase()
  if (k in IMPACT_RANK) return IMPACT_RANK[k]
  return /FOMC|CPI|NFP|PCE/i.test(e.kind ?? '') ? 0 : 2
}

/** ★ only on High-impact rows and FOMC DECISIONS (statement / rate), never on a Fed speaker (C-TRADER-11 / C-DATA-9). */
export function eventStar(e: Pick<GoldEvent, 'impact' | 'kind' | 'name'>): boolean {
  if (/speak|speech|testif|remarks/i.test(e.name ?? '')) return false
  if ((e.impact ?? '').toLowerCase() === 'high') return true
  return /^FOMC$/i.test(e.kind ?? '') && /statement|rate|decision|press|minutes|FOMC meeting/i.test(e.name ?? '')
}

/** 'YYYY-MM-DDTHH:MM' of an event in IST (date only → '…T00:00' so a dated row counts as today, not as past). */
function eventKey(e: Pick<GoldEvent, 'event_date' | 'date' | 'time_ist'>): string {
  return `${e.event_date ?? e.date ?? ''}T${e.time_ist ?? '00:00'}`
}

/**
 * The 7-day strip in impact order (High → Medium → roll / holiday → Low), time within each, with rows already behind the
 * IST clock `nowIst` ('YYYY-MM-DDTHH:MM') dropped — an 03:00 bulletin listed at 23:53 is not "next 7 days". Rows without a
 * time stay for their whole day. No cap (the Friday NFP was cut off by a 14-row slice).
 */
export function orderEvents<E extends Pick<GoldEvent, 'event_date' | 'date' | 'time_ist' | 'impact' | 'kind' | 'name'>>(events: readonly E[], nowIst?: string | null): E[] {
  const keep = events.filter(e => {
    if (!nowIst) return true
    if (!e.time_ist) return (e.event_date ?? e.date ?? '') >= nowIst.slice(0, 10)
    return eventKey(e) >= nowIst
  })
  return [...keep].sort((a, b) => eventImpactRank(a) - eventImpactRank(b) || eventKey(a).localeCompare(eventKey(b)) || (a.name ?? '').localeCompare(b.name ?? ''))
}

/** The IST clock as 'YYYY-MM-DDTHH:MM' (what `orderEvents` compares against). */
export function istNowKey(now: Date = new Date()): string {
  const d = now.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
  const t = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
  return `${d}T${t}`
}

// ── h.brief: the headline fields sit at the TOP level of /brief (C-TRADER-15 / C-DATA-12) ───────────────────────

/**
 * 'automated brief · bias neutral · confidence 45 %' from the top-level fields (`doc.synthesis.*` as the fallback for
 * an older document). `open_signal` is a trade-implying word and is NEVER part of the text (PLAN 0.1 #7).
 */
export function briefHeader(b: Pick<GoldBrief, 'bias' | 'confidence' | 'label' | 'doc'> | null | undefined): string {
  if (!b) return 'automated brief'
  const syn = ((b.doc as Record<string, unknown> | null | undefined)?.synthesis ?? {}) as Record<string, unknown>
  const bias = b.bias ?? (typeof syn.bias === 'string' ? syn.bias : null)
  const conf = b.confidence ?? (typeof syn.confidence === 'number' ? syn.confidence : null)
  const parts = ['automated brief', `bias ${bias ?? '—'}`, `confidence ${conf != null && Number.isFinite(conf) ? `${Math.round(conf * 100)} %` : '—'}`]
  return parts.join(' · ')
}

// ── c.spec: the DES card of the MATCHED month (C-BEGINNER-4 / C-TRADER-13 / C-DATA-8) ────────────────────────────

const MONTH_CODE: Record<string, string> = { F: '01', G: '02', H: '03', J: '04', K: '05', M: '06', N: '07', Q: '08', U: '09', V: '10', X: '11', Z: '12' }

/** 'GCZ26.CMX' → '202612' (the PRF `mmy`), null for the continuous front or anything unparsable. */
export function comexMmy(symbol: string | null | undefined): string | null {
  const m = /^[A-Z]{1,2}([FGHJKMNQUVXZ])(\d{2})/.exec(comexCode(symbol))
  return m ? `20${m[2]}${MONTH_CODE[m[1]]}` : null
}

/** '202612' → 'DEC-26'; anything else → '—'. */
export function mmyLabel(mmy: string | null | undefined): string {
  const m = /^(\d{4})(\d{2})$/.exec(mmy ?? '')
  return m ? `${MONTHS[+m[2] - 1].toUpperCase()}-${m[1].slice(2)}` : '—'
}

/** Does the PRF row describe the matched month? (null when either side is unknown: no claim.) */
export function specMatches(spec: Pick<ComexSpec, 'mmy'> | null | undefined, comexMatched: string | null | undefined): boolean | null {
  const want = comexMmy(comexMatched)
  if (!want || !spec?.mmy) return null
  return spec.mmy === want
}

/**
 * The tick in DISPLAY units: the PRF's MinPxIncr is in the file's price units (GC: 1.0 with DisplayFactor 0.1 → $0.10),
 * so the server's `tick_usd` (already scaled) wins, else MinPxIncr × display_factor, else the GC convention (factor 0.1
 * when the increment is ≥ 1 on a GC/MGC row — the glossary's '$0.10 = $10'). The tick VALUE is the increment × the
 * contract multiplier.
 */
export function specTick(spec: Pick<ComexSpec, 'symbol' | 'min_px_incr' | 'tick_value_usd' | 'multiplier' | 'uom_qty' | 'tick_usd' | 'display_factor'> | null | undefined): { tick: number; value: number } | null {
  if (!spec) return null
  const mult = spec.multiplier ?? spec.uom_qty ?? 100
  if (spec.tick_usd != null && Number.isFinite(spec.tick_usd)) return { tick: spec.tick_usd, value: spec.tick_usd * mult }
  if (spec.min_px_incr == null || !Number.isFinite(spec.min_px_incr)) return null
  const factor = spec.display_factor ?? (/^(GC|MGC|1OZ)$/.test(spec.symbol ?? '') && spec.min_px_incr >= 1 ? 0.1 : 1)
  const tick = spec.min_px_incr * factor
  return { tick, value: tick * mult }
}

/** PRF SettlMethod code → words: P physical delivery, C cash-settled. */
export function settlMethodWord(code: string | null | undefined): string {
  const c = (code ?? '').trim().toUpperCase()
  if (!c) return '—'
  if (c === 'P' || c === 'PHYSICAL') return 'physical delivery'
  if (c === 'C' || c === 'CASH') return 'cash-settled'
  return c.toLowerCase()
}

/** PRF UOM code → words: oz_tr → troy oz, g → grams, kg → kilograms. */
export function uomWord(code: string | null | undefined): string {
  const c = (code ?? '').trim().toLowerCase()
  if (!c) return 'oz'
  return ({ oz_tr: 'troy oz', ozt: 'troy oz', oz: 'troy oz', g: 'grams', kg: 'kilograms', mt: 'metric tonnes' } as Record<string, string>)[c] ?? c
}

/** Margin-history rows worth a sparkline: real margins only (≥ $1,000 — the $25 row is another product's), ≥ 3 distinct dates. */
export function marginHistoryPoints(rows: readonly { trade_date: string; margin_usd: number | null }[] | null | undefined): number[] {
  const byDate = new Map<string, number>()
  for (const r of rows ?? []) if (r.margin_usd != null && r.margin_usd >= 1000 && !byDate.has(r.trade_date)) byDate.set(r.trade_date, r.margin_usd)
  if (byDate.size < 3) return []
  return [...byDate.entries()].sort((a, b) => a[0].localeCompare(b[0])).map(([, v]) => v)
}

// ── basis clock labels (C-BEGINNER-5 / C-DATA-11 / C-TRADER-10) ────────────────────────────────────────────────

/**
 * 'basis +1.50 % at the Tue 03 Nov settlement vs that session's duty-paid' — the clock of a settlement basis is stated
 * every time, so nobody divides a settlement by a duty-paid price sampled hours later (the panel's own clock-error
 * warning). A live basis says 'live MCX ₹… vs duty-paid now'.
 */
export function basisClockLabel(basisPct: number | null | undefined, sessionLabel: string | null | undefined): string {
  if (basisPct == null || !Number.isFinite(basisPct)) return 'basis —'
  const when = sessionLabel ? `at the ${sessionLabel}` : 'at the last settlement'
  return `basis ${fmtSignedPctSp(basisPct, 2)} ${when} vs that session's duty-paid`
}

/** Live MCX ÷ duty-paid landed − 1 in % (both legs at the same clock), null when either is missing. */
export function liveBasisPct(mcxLive: number | null | undefined, dutyPaidLanded: number | null | undefined): number | null {
  if (mcxLive == null || dutyPaidLanded == null || !Number.isFinite(mcxLive) || !Number.isFinite(dutyPaidLanded) || dutyPaidLanded === 0) return null
  return (mcxLive / dutyPaidLanded - 1) * 100
}

// ── h.open after the bell (C-TRADER-14 / C-BEGINNER-13) ────────────────────────────────────────────────────────

export const MORNING_CALL_MIN = 9 * 60 + 15

export type MorningCall =
  | { phase: 'pre_open' }
  | { phase: 'closed' }
  | { phase: 'call'; row: { fair_open?: number; actual_open?: number; error?: number; naive_error?: number; actual_source?: string; stale_baseline?: boolean } }
  | { phase: 'open_missing'; row: { fair_open?: number; snapshot_at?: string } }
  | { phase: 'no_snapshot' }

/**
 * What h.open shows for the day once the IST clock passes 09:15 on an MCX session: the morning's CALL when the 08:45
 * snapshot row has its captured open; "the open was not captured" when the snapshot ran but the 09:10 capture did not;
 * "no snapshot today (job missed)" when there is no row for the day. Before 09:15 (or on a full MCX closure / weekend)
 * the pre-open desk shows instead. The pre-open copy ("DON'T CHASE — WAIT") is never shown at 23:53 (C-TRADER-14).
 */
export function morningCall(istMinutes: number, weekday: number, today: string, rows: readonly { date: string; fair_open?: number; actual_open?: number; error?: number; naive_error?: number; actual_source?: string; stale_baseline?: boolean; snapshot_at?: string }[] | null | undefined,
  holidayClosure?: string | null): MorningCall {
  if (weekday === 0 || weekday === 6 || holidayClosure === 'full') return { phase: 'closed' }
  if (istMinutes < MORNING_CALL_MIN) return { phase: 'pre_open' }
  const row = (rows ?? []).find(r => r.date === today) ?? null
  if (!row) return { phase: 'no_snapshot' }
  if (row.actual_open == null) return { phase: 'open_missing', row }
  return { phase: 'call', row }
}

/**
 * The honest [B] line of h.open (C-BEGINNER-13): the chase limit is a house rule; the measured miss and the model-vs-naive
 * verdict come from the accuracy log when it has scored days, else the words say the rule is unproven. Never an action rule.
 */
export function preOpenCopyB(stats: { days?: number | null; median_abs_error?: number | null; mean_abs_error?: number | null; naive_mean_abs_error?: number | null } | null | undefined, threshold = 300): string {
  const head = 'Where MCX ‘should’ open given COMEX and the rupee since the close.'
  const days = stats?.days ?? 0
  if (!days) return `${head} The OK / WAIT strip is a house rule (₹${threshold.toLocaleString('en-IN')}) with no scored mornings yet — arithmetic to read, not advice.`
  const med = stats?.median_abs_error
  const worse = stats?.naive_mean_abs_error != null && stats?.mean_abs_error != null ? stats.mean_abs_error > stats.naive_mean_abs_error : null
  const missed = med != null ? ` that has missed by ${fmtInr0(med)} on a typical morning` : ''
  const vsNaive = worse == null ? '' : worse ? ' and is worse than ‘open = yesterday’s settlement’ so far' : ' and beats ‘open = yesterday’s settlement’ so far'
  return `${head} The OK / WAIT strip is a house rule (₹${threshold.toLocaleString('en-IN')})${missed}${vsNaive} (${days} day${days === 1 ? '' : 's'} scored) — arithmetic to read, not advice.`
}

/**
 * The window the verdict describes, in the SERVER's words (C-TRADER-16): `verdict.window_label`, else the payload's, else
 * the TREND gauge's `window_label` ('week to date (since the Fri 30 Oct close)' / '5 sessions'); null when none is sent.
 */
export function verdictWindowLabel(h: Pick<GoldHealth, 'verdict' | 'window_label' | 'gauges'> | null | undefined): string | null {
  if (!h) return null
  return h.verdict?.window_label ?? h.window_label ?? gauge(h as GoldHealth, 'trend')?.window_label ?? null
}
