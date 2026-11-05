/**
 * Price-alert texts and the per-check notification (WTCH). Pure, no imports: unit-tested by
 * `node ui/lib/__tests__/alerts.check.ts`.
 *
 * One check (a quote refresh on WTCH) can find several fresh hits, e.g. a gap-down open crossing 25 levels at
 * once. They go out as ONE native notification with a count, identical in the browser and in SuryaDhana.app
 * (C3-logic-unchanged-07: the app's shell refuses more than 20 notifications a minute, so per-hit notifications
 * were silently dropped there while the browser showed them all). Within the shell's limits: title ≤ 120 and
 * body ≤ 1000 characters, so neither path clips differently.
 */

export interface HitLike {
  sym: string
  side: string
  level: number
  price: number
  /** A MOVE hit's actual % change vs the previous close (the server sets it; `level` is then the threshold %). */
  change_pct?: number | null
}

export const NOTIFY_TITLE_MAX = 120
export const NOTIFY_BODY_MAX = 1000
/** Hits listed by name in a batched notification; the rest are counted. */
export const NOTIFY_LIST_MAX = 5

/** "+6.1 %" / "−6.1 %" (true minus), one decimal. */
function signedPct(v: number): string {
  return `${v < 0 ? '−' : '+'}${Math.abs(v).toFixed(1)} %`
}

/**
 * One hit. Price levels are worded exactly as the single-hit notification always was; a ±% MOVE hit (P11) says what
 * moved and its threshold, "TCS moved −6.1 % (≥ 5 %) (now ₹3,120)", instead of "fell below ₹5".
 */
export function hitText(hit: HitLike): string {
  const now = `(now ₹${hit.price.toLocaleString('en-IN')})`
  if (hit.side === 'move') {
    const ch = typeof hit.change_pct === 'number' && Number.isFinite(hit.change_pct) ? `${signedPct(hit.change_pct)} ` : ''
    return `${hit.sym} moved ${ch}(≥ ${hit.level.toLocaleString('en-IN')} %) ${now}`
  }
  return `${hit.sym} ${hit.side === 'above' ? 'rose above' : 'fell below'} ₹${hit.level.toLocaleString('en-IN')} ${now}`
}

/** Fired on `window` when saving alert levels failed (lib/alerts.ts); the terminal shows it as a toast (P11). */
export const ALERT_SAVE_FAILED_EVENT = 'suryadhana:alert-save-failed' as const
export interface AlertSaveFailure {
  sym: string
  /** What went wrong, already readable (lib/errors.ts apiError). */
  error: string
}

/** The toast for a failed save: the levels were NOT stored, so nothing will fire. */
export function alertSaveFailedText(f: AlertSaveFailure): string {
  const why = (f.error || 'ui-api did not answer').replace(/\s+/g, ' ').trim().slice(0, 200)
  return `Alert for ${f.sym || 'this stock'} NOT saved: ${why}. Nothing will fire until it is saved.`
}

/** The single notification for one check's fresh hits (null when there are none). */
export function alertNotification(hits: readonly HitLike[]): { title: string; body: string } | null {
  if (!hits.length) return null
  if (hits.length === 1) return { title: 'SuryaDhana alert', body: clip(hitText(hits[0]), NOTIFY_BODY_MAX) }
  const shown = hits.slice(0, NOTIFY_LIST_MAX).map(h => clip(hitText(h), 160))
  const rest = hits.length - shown.length
  const lines = rest > 0 ? [...shown, `+${rest} more · open WTCH for the full list`] : shown
  return { title: `SuryaDhana · ${hits.length} price alerts`, body: clip(lines.join('\n'), NOTIFY_BODY_MAX) }
}

/** Seen-marker value meaning "nothing seen yet": sorts below every ISO-8601 timestamp the server writes. */
export const SEEN_NOTHING = '1970-01-01T00:00:00'

/**
 * First visit on this device (no seen marker yet, e.g. the desktop app's new origin): what already exists is not
 * news, so the marker starts at the newest item (C3-logic-unchanged-05); an empty history starts it at
 * SEEN_NOTHING so the first real hit still counts as fresh. With a marker, it is returned unchanged.
 */
export function initialSeen(marker: string | null | undefined, newestAt: string | null | undefined): string {
  if (marker) return marker
  return newestAt || SEEN_NOTHING
}

function clip(s: string, max: number): string {
  return s.length <= max ? s : `${s.slice(0, max - 1)}…`
}
