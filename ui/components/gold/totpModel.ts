/**
 * Pure model of the BRKR "Auto-login (TOTP)" panel (reports/gold_program/PLAN.md §g): status-chip text per source,
 * the 09:00–15:30 IST rule that disables "force a new login", the .env permission warning, the setup-key input
 * normaliser (bare base32 or an `otpauth://` URI → a base32 string for the preview call), the Keychain one-liner and
 * the wording of the session-check poll.
 *
 * The secret never leaves this module's inputs: `normaliseSetupKey` returns only what the server will be sent, the
 * one-liner never embeds the secret (`-w` prompts), and nothing here touches storage. No imports: the node check
 * (`ui/components/__tests__/gold_views.check.ts`) loads it under plain node.
 */

export type TotpSource = 'env' | 'keychain' | null | undefined

/** `GET /api/positions/totp/status[?reveal=1]` (services/ui-api/routers/positions.py `totp_status`). */
export interface TotpStatus {
  configured: boolean
  source?: TotpSource
  keychain_present?: boolean | null
  /** '0644' / '0600' / 420 … the mode bits of .env as the server reports them */
  env_mode?: string | number | null
  env_mode_ok?: boolean
  auto_login_enabled?: boolean
  /** true, or the ISO start time, while the 08:00 job (or a manual run) is logging in */
  login_running?: boolean | string | null
  otp_pending?: boolean
  last_login?: { at?: string | null; status?: string | null; detail?: string | null } | null
  next_run_ist?: string | null
  block?: { credentials?: boolean | string | null; totp?: boolean | string | null } | null
  /** the server's own Keychain one-liner (never the value) */
  keychain_hint?: string | null
  /** only with ?reveal=1 (computed server-side; never the secret) */
  code?: string | null
  seconds_left?: number | null
  secret_problem?: string | null
  /** when the server supports POST /api/telemetry/icici-refresh {force:true} */
  force_supported?: boolean
}

/** `POST /api/positions/totp/preview {secret}` */
export interface TotpPreview { valid: boolean; digits: number; period: number; algorithm: string; length: number; code: string; seconds_left: number }

/** `POST /api/positions/totp {secret, confirm_code}` */
export interface TotpSaveResult {
  saved: boolean; persisted?: boolean; persisted_reason?: string | null; env_path?: string | null; source?: string
  env_mode?: string | null; env_mode_warning?: string | null; keychain_present?: boolean | null
}

/** `DELETE /api/positions/totp` */
export interface TotpClearResult { cleared: boolean; persisted?: boolean; persisted_reason?: string | null; keychain_still_present?: boolean; keychain_hint?: string | null }

export interface StatusChip { text: string; tone: 'green' | 'amber' | 'cyan' | 'red' | 'muted'; pulse?: boolean }

/** The status strip's chips in display order (PLAN §g "Status strip"). */
export function statusChips(s: TotpStatus | null | undefined): StatusChip[] {
  if (!s) return [{ text: 'TOTP STATUS UNAVAILABLE', tone: 'muted' }]
  const out: StatusChip[] = []
  if (s.block?.totp) out.push({ text: 'TOTP MISMATCH — re-register', tone: 'red' })
  if (s.configured) out.push({ text: `TOTP CONFIGURED · ${s.source === 'keychain' ? 'Keychain' : s.source === 'env' ? '.env' : 'set'}`, tone: 'green' })
  else out.push({ text: 'TOTP NOT SET', tone: 'amber' })
  if (s.login_running) {
    const since = typeof s.login_running === 'string' ? ` · since ${timeIst(s.login_running)}` : ''
    out.push({ text: `AUTO-LOGIN RUNNING${since}`, tone: 'cyan', pulse: true })
  }
  if (s.otp_pending) out.push({ text: 'SMS OTP REQUESTED ON TELEGRAM', tone: 'amber' })
  if (s.block?.credentials) out.push({ text: 'CREDENTIALS BLOCK FILE PRESENT', tone: 'amber' })
  return out
}

/** "08:00 job: enabled · next Mon 08:00 · last: 23 Oct 08:08 refreshed via ui-api". */
export function jobLine(s: TotpStatus | null | undefined): string {
  if (!s) return '08:00 job: status unavailable'
  const parts = [`08:00 job: ${s.auto_login_enabled === false ? 'disabled' : 'enabled'}`]
  if (s.next_run_ist) parts.push(`next ${timeIst(s.next_run_ist, true)}`)
  const l = s.last_login
  if (l?.at) parts.push(`last: ${timeIst(l.at, true)} ${l.status ?? ''}${l.detail ? ` (${l.detail})` : ''}`.trim())
  return parts.join(' · ')
}

/** '.env is 0644 — run chmod 600 .env' when the mode is anything but 0600 (string '0644', '644', 'rw-r--r--' or number 420). */
export function envModeWarning(mode: string | number | null | undefined): string | null {
  if (mode == null || mode === '') return null
  let octal: string
  if (typeof mode === 'number') octal = (mode & 0o777).toString(8).padStart(3, '0')
  else if (/^[-rwx]{9,10}$/.test(mode)) {
    const bits = mode.replace(/^[-d]/, '').split('')
    const trip = (i: number) => (bits[i] === 'r' ? 4 : 0) + (bits[i + 1] === 'w' ? 2 : 0) + (bits[i + 2] === 'x' ? 1 : 0)
    octal = `${trip(0)}${trip(3)}${trip(6)}`
  } else octal = String(mode).replace(/^0o?/, '').slice(-3)
  return octal === '600' ? null : `.env is 0${octal} — run chmod 600 .env`
}

/** IST minutes since midnight. */
export function istMinutes(now: Date = new Date()): number {
  const t = now.toLocaleTimeString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false })
  const [h, m] = t.split(':').map(Number)
  return h * 60 + m
}

/** FORCE A NEW LOGIN is disabled 09:00–15:30 IST (a forced login ends today's session mid-market). */
export function forceLoginDisabledReason(now: Date = new Date()): string | null {
  const m = istMinutes(now)
  return m >= 9 * 60 && m < 15 * 60 + 30 ? 'Disabled 09:00–15:30 IST: a forced login ends today\'s ICICI session during market hours' : null
}

/**
 * Setup-key input → what the preview/save calls send. Accepts bare base32 (any case, spaces or dashes between groups,
 * trailing '=' padding) or an `otpauth://totp/...?secret=...` URI (percent-encoded). Returns null when nothing usable
 * is there; never throws. The server re-parses it (`parse_totp_secret`) and is the authority.
 */
export function normaliseSetupKey(raw: string): string | null {
  const s = raw.trim()
  if (!s) return null
  if (/^otpauth:\/\//i.test(s)) {
    const m = /[?&]secret=([^&#]+)/i.exec(s)
    if (!m) return null
    let v: string
    try { v = decodeURIComponent(m[1]) } catch { v = m[1] }
    return normaliseSetupKey(v)
  }
  const b32 = s.replace(/[\s-]/g, '').toUpperCase().replace(/=+$/, '')
  return /^[A-Z2-7]{16,128}$/.test(b32) ? b32 : null
}

/** Groups of three for the preview code: '482913' → '482 913'. */
export function groupCode(code: string | null | undefined): string {
  if (!code) return '— — —'
  return code.replace(/(\d{3})(?=\d)/g, '$1 ')
}

/** A typed confirmation is six digits (spaces allowed while typing). */
export function confirmLooksComplete(confirm: string): boolean {
  return /^\d{6}$/.test(confirm.replace(/\s/g, ''))
}

/** The Keychain one-liner (prompts for the secret; nothing in argv or shell history). */
export const KEYCHAIN_ONE_LINER = 'security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w'

/** ICICI Direct settings page for the authenticator (Option A of PLAN §g) and the two FAQ links (I1). */
export const ICICI_SETTINGS_URL = 'https://secure.icicidirect.com/customer/settings'
export const ICICI_FAQ_LINKS: readonly { label: string; url: string }[] = [
  { label: 'ICICI Direct: Login Authenticator FAQ', url: 'https://www.icicidirect.com/faqs/login-authenticator' },
  { label: 'Google Authenticator: export / transfer accounts', url: 'https://support.google.com/accounts/answer/1066447' },
]

/** The three owner steps of Option A, verbatim from PLAN §g. */
export const OPTION_A_STEPS: readonly string[] = [
  'icicidirect.com → Settings → Disable Login Authenticator (PIN) → Login Authenticator → Google Authenticator.',
  'Scan the QR on the phone AND copy the "manually enter the provided key" text (that text is the setup key).',
  'Re-add the entry on the phone so the phone and this terminal share one secret; then paste the key below.',
]

export type SessionWatch = 'idle' | 'starting' | 'watching' | 'live' | 'timeout' | 'unsupported' | 'error'

/** The CHECK SESSION button's status line per watch state. */
export function sessionWatchLine(state: SessionWatch, elapsedS = 0, detail?: string | null): string {
  switch (state) {
    case 'idle': return 'Runs the 08:00 login job now: checks today\'s session and logs in only if it has expired.'
    case 'starting': return 'Started — asking master-controller to run the session check…'
    case 'watching': return `Started — watching… ${Math.floor(elapsedS / 60)}m${String(elapsedS % 60).padStart(2, '0')}s (up to 8 min; an SMS OTP prompt would arrive on Telegram)`
    case 'live': return `● LIVE — ICICI session confirmed${detail ? ` (${detail})` : ''}`
    case 'timeout': return 'No confirmation within 8 minutes: check SYS › scheduler logs or send /login to the Telegram bot.'
    case 'unsupported': return 'The scheduler proxy (POST /api/telemetry/icici-refresh) is not in this ui-api release: send /login to the Telegram bot instead.'
    default: return `Could not start the session check${detail ? `: ${detail}` : ''}.`
  }
}

/** Poll cadence and ceiling of the session watch (PLAN §g: every 5 s up to 8 min). */
export const WATCH_EVERY_MS = 5_000
export const WATCH_MAX_MS = 8 * 60_000
/** The preview debounce (PLAN §g: 400 ms). */
export const PREVIEW_DEBOUNCE_MS = 400

function timeIst(iso: string, withDate = false): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const opts: Intl.DateTimeFormatOptions = { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false }
  if (withDate) Object.assign(opts, { weekday: 'short', day: '2-digit', month: 'short' })
  return d.toLocaleString('en-IN', opts)
}
