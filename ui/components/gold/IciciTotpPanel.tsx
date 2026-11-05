'use client'

/**
 * BRKR › "Auto-login (TOTP)" (reports/gold_program/PLAN.md §g): the owner registers the ICICI authenticator secret once,
 * the 08:00 job logs in unattended with the six-digit code, no SMS OTP on Telegram.
 *
 *  Status strip   GET /api/positions/totp/status  → TOTP CONFIGURED · Keychain / .env | TOTP NOT SET | AUTO-LOGIN RUNNING |
 *                 TOTP MISMATCH — re-register; the 08:00 job line; ".env is 0644 — run chmod 600 .env"
 *  Step 1         the three Option A lines + OPEN ICICI SETTINGS ↗ (openExternal) + FAQ links
 *  Step 2         one monospace password input (SHOW toggle; base32 or otpauth://), debounced 400 ms →
 *                 POST /api/positions/totp/preview {secret} → "Current code 482 913 · 17 s" with a 30-s bar
 *  Step 3         six-digit confirm + SAVE → POST /api/positions/totp {secret, confirm_code}; the input is cleared
 *                 from React state on success; the Keychain one-liner copy box + DETECT
 *  Step 4         CHECK SESSION / LOG IN IF EXPIRED → POST /api/telemetry/icici-refresh (server-side proxy to the
 *                 controller) → "Started — watching…" → poll /status every 5 s up to 8 min + /connection-status → ● LIVE;
 *                 FORCE A NEW LOGIN (confirm-gated) only when the server advertises `force_supported`, disabled
 *                 09:00–15:30 IST, warned when a credentials block file exists
 *  Remove         DISABLE AUTO-LOGIN (confirm) → DELETE /api/positions/totp; reports keychain_still_present
 *
 * Security (PLAN §g): the secret lives in this component's state only until SAVE, is never written to prefs, local or
 * session storage, never logged, never put in a query string; the calls use the same relative axios client as the
 * rest of the terminal (same-origin ui-api on loopback; no Authorization header, no credentials flag). The server
 * never returns the secret; `preview.code` and `status?reveal=1` return six digits computed server-side.
 */
import axios from 'axios'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Btn, Chip, Dot, Input, Label, Meter, Notice, Panel, T } from '@/components/terminal'
import { apiError } from '@/lib/errors'
import { openExternal } from '@/lib/platform'
import {
  ICICI_FAQ_LINKS, ICICI_SETTINGS_URL, KEYCHAIN_ONE_LINER, OPTION_A_STEPS, PREVIEW_DEBOUNCE_MS, WATCH_EVERY_MS, WATCH_MAX_MS,
  confirmLooksComplete, envModeWarning, forceLoginDisabledReason, groupCode, jobLine, normaliseSetupKey, sessionWatchLine, statusChips,
  type SessionWatch, type TotpClearResult, type TotpPreview, type TotpSaveResult, type TotpStatus,
} from './totpModel'

// the same relative-path client the terminal uses (ui-api serves /api on this origin); nothing is added to the request
const http = axios.create({ baseURL: '', timeout: 15_000 })
const TOTP_URL = '/api/positions/totp'
const REFRESH_PROXY_URL = '/api/telemetry/icici-refresh'
const CONNECTION_URL = '/api/positions/connection-status'
const STATUS_EVERY_MS = 30_000

const TONE: Record<string, string> = { green: T.green, amber: T.amber, cyan: T.cyan, red: T.red, muted: T.muted }

export function IciciTotpPanel({ connected, onSessionLive, onStatus }: {
  connected: boolean
  /** called once the session watch sees ● LIVE (the page then refreshes its holdings) */
  onSessionLive?: () => void
  /** every status read, so the page can hide its "send /login" sentence while a login runs */
  onStatus?: (s: TotpStatus) => void
}) {
  const [status, setStatus] = useState<TotpStatus | null>(null)
  const [statusErr, setStatusErr] = useState<string | null>(null)
  const loadStatus = useCallback(async (reveal = false) => {
    try {
      const r = await http.get<TotpStatus>(`${TOTP_URL}/status`, { params: reveal ? { reveal: 1 } : undefined })
      setStatus(r.data); setStatusErr(null); onStatus?.(r.data)
      return r.data
    } catch (e) { setStatusErr(apiError(e, 'status unavailable')); return null }
  }, [onStatus])
  useEffect(() => {
    void loadStatus()
    const iv = setInterval(() => { if (typeof document === 'undefined' || !document.hidden) void loadStatus() }, STATUS_EVERY_MS)
    return () => clearInterval(iv)
  }, [loadStatus])

  // ── step 2: the setup key → live preview (debounced 400 ms; re-previewed at each rollover) ───────────────
  const [key, setKey] = useState('')
  const [show, setShow] = useState(false)
  const [preview, setPreview] = useState<TotpPreview | null>(null)
  const [previewErr, setPreviewErr] = useState<string | null>(null)
  const [left, setLeft] = useState(0)
  const previewSeq = useRef(0)
  const runPreview = useCallback(async (secret: string) => {
    const mine = ++previewSeq.current
    try {
      const r = await http.post<TotpPreview>(`${TOTP_URL}/preview`, { secret })
      if (mine !== previewSeq.current) return
      setPreview(r.data); setPreviewErr(null); setLeft(r.data.seconds_left)
    } catch (e) {
      if (mine !== previewSeq.current) return
      setPreview(null); setPreviewErr(apiError(e, 'preview unavailable'))
    }
  }, [])
  useEffect(() => {
    const b32 = normaliseSetupKey(key)
    if (!b32) { previewSeq.current++; setPreview(null); setPreviewErr(key.trim() ? 'not a usable key yet: base32 (A–Z, 2–7, 16+ chars) or an otpauth:// URI' : null); return }
    const t = setTimeout(() => { void runPreview(b32) }, PREVIEW_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [key, runPreview])
  useEffect(() => {                       // the 30-s bar counts down locally; at the rollover the server is asked again
    if (!preview) return
    const iv = setInterval(() => setLeft(s => {
      if (s <= 1) { const b32 = normaliseSetupKey(key); if (b32) void runPreview(b32); return preview.period }
      return s - 1
    }), 1000)
    return () => clearInterval(iv)
  }, [preview, key, runPreview])
  useEffect(() => () => { previewSeq.current++ }, [])

  // ── step 3: confirm + save ─────────────────────────────────────────────────────────────────────────────
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const save = async () => {
    const b32 = normaliseSetupKey(key)
    if (!b32 || !confirmLooksComplete(confirm)) return
    setSaving(true); setSaveMsg(null)
    try {
      const r = await http.post<TotpSaveResult>(TOTP_URL, { secret: b32, confirm_code: confirm.replace(/\s/g, '') })
      const d = r.data
      // the secret leaves React state here; nothing was ever persisted client-side
      setKey(''); setConfirm(''); setPreview(null); previewSeq.current++
      const bits = [d.persisted ? `saved to ${d.env_path ?? '.env'}` : `not persisted${d.persisted_reason ? ` (${d.persisted_reason})` : ''}`]
      if (d.env_mode_warning) bits.push(d.env_mode_warning)
      if (d.keychain_present) bits.push('a Keychain copy also exists — the Keychain one wins at 08:00')
      setSaveMsg({ ok: !!d.saved, text: bits.join(' · ') })
      await loadStatus()
    } catch (e) {
      setSaveMsg({ ok: false, text: apiError(e, 'save refused') })
    } finally { setSaving(false) }
  }

  // ── keychain one-liner ─────────────────────────────────────────────────────────────────────────────────
  const oneLiner = status?.keychain_hint || KEYCHAIN_ONE_LINER
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(oneLiner); setCopied(true); setTimeout(() => setCopied(false), 1500) } catch { setCopied(false) }
  }

  // ── reveal the configured secret's current code (server-side; never the secret) ────────────────────────
  const [revealed, setRevealed] = useState<{ code: string | null; left: number; problem?: string | null } | null>(null)
  const reveal = async () => {
    const s = await loadStatus(true)
    if (!s) return
    setRevealed({ code: s.code ?? null, left: s.seconds_left ?? 0, problem: s.secret_problem ?? null })
  }
  useEffect(() => {
    if (!revealed?.code) return
    const iv = setInterval(() => setRevealed(r => (r && r.left > 1 ? { ...r, left: r.left - 1 } : null)), 1000)
    return () => clearInterval(iv)
  }, [revealed?.code])

  // ── step 4: check the session / log in if expired (the scheduler proxy) ───────────────────────────────
  const [watch, setWatch] = useState<SessionWatch>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [watchDetail, setWatchDetail] = useState<string | null>(null)
  const watchTimer = useRef<ReturnType<typeof setInterval> | null>(null)
  const stopWatch = useCallback(() => { if (watchTimer.current) { clearInterval(watchTimer.current); watchTimer.current = null } }, [])
  useEffect(() => stopWatch, [stopWatch])
  const startWatch = () => {
    stopWatch()
    const t0 = Date.now()
    setWatch('watching'); setElapsed(0)
    watchTimer.current = setInterval(async () => {
      const e = Math.floor((Date.now() - t0) / 1000)
      setElapsed(e)
      const s = await loadStatus()
      let live = false
      try { const c = await http.get<{ connected?: boolean; account_name?: string }>(CONNECTION_URL, { timeout: 30_000 }); live = !!c.data?.connected; if (live) setWatchDetail(c.data?.account_name ?? null) } catch { live = false }
      if (live && !(s?.login_running)) { stopWatch(); setWatch('live'); onSessionLive?.(); return }
      if (Date.now() - t0 >= WATCH_MAX_MS) { stopWatch(); setWatch('timeout') }
    }, WATCH_EVERY_MS)
  }
  const checkSession = async (force = false) => {
    setWatch('starting'); setWatchDetail(null)
    try {
      await http.post(REFRESH_PROXY_URL, force ? { force: true } : {}, { params: force ? { force: 1 } : undefined, timeout: 30_000 })
      startWatch()
    } catch (e) {
      // the proxy route is B3's; until it ships the route answers 404/405 and the panel says so instead of pretending
      const httpStatus = axios.isAxiosError(e) ? e.response?.status : undefined
      if (httpStatus === 404 || httpStatus === 405) { setWatch('unsupported'); return }
      setWatch('error'); setWatchDetail(apiError(e, 'request failed'))
    }
  }
  const [forceArmed, setForceArmed] = useState(false)
  const forceReason = forceLoginDisabledReason()

  // ── remove ────────────────────────────────────────────────────────────────────────────────────────────
  const [disableArmed, setDisableArmed] = useState(false)
  const [disableMsg, setDisableMsg] = useState<string | null>(null)
  const disable = async () => {
    setDisableArmed(false)
    try {
      const r = await http.delete<TotpClearResult>(TOTP_URL)
      const d = r.data
      setDisableMsg(`${d.cleared ? 'auto-login disabled (ICICI_TOTP_SECRET cleared in .env)' : 'not cleared'}${d.keychain_still_present ? ` · a Keychain copy is still present — ui-api never deletes it; run: ${d.keychain_hint ?? 'security delete-generic-password -s suryadhana -a ICICI_TOTP_SECRET'}` : ''}`)
      await loadStatus()
    } catch (e) { setDisableMsg(apiError(e, 'disable refused')) }
  }

  const chips = statusChips(status)
  const envWarn = envModeWarning(status?.env_mode)
  const b32 = normaliseSetupKey(key)
  const canSave = !!b32 && !!preview?.valid && confirmLooksComplete(confirm) && !saving
  const step = (n: string, text: string) => <div style={{ marginBottom: 6 }}><Label color={T.amber}>{n} · {text}</Label></div>

  return (
    <Panel title="Auto-login (TOTP)" accent={T.cyan} subtitle="the 08:00 job logs in with the authenticator's six digits — no SMS OTP on Telegram"
      right={<Btn size="sm" onClick={() => loadStatus()} title="Re-read the status">↻</Btn>}>
      <div data-totp-panel data-connected={connected ? '1' : '0'} style={{ display: 'grid', gap: 12 }}>
        {/* status strip */}
        <div data-totp-status>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            {chips.map(c => (
              <Chip key={c.text} color={TONE[c.tone]} active title={c.text}>
                {c.pulse && <Dot color={TONE[c.tone]} pulse size={5} />}{c.pulse ? ' ' : ''}{c.text}
              </Chip>
            ))}
            {statusErr && <span style={{ fontSize: 10.5, color: T.amber }}>status: {statusErr}</span>}
          </div>
          <div style={{ fontSize: 10.5, color: T.muted, marginTop: 6 }}>{jobLine(status)}</div>
          {envWarn && <div data-env-warning style={{ fontSize: 10.5, color: T.amber, marginTop: 4 }}>▲ {envWarn} (a readable .env with the seed is a complete login)</div>}
          {status?.configured && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 6, flexWrap: 'wrap' }}>
              <Btn size="sm" onClick={reveal} title="The six digits the stored secret produces right now, computed by ui-api (the secret itself never leaves the server)">SHOW CURRENT CODE</Btn>
              {revealed && (revealed.problem
                ? <span style={{ fontSize: 10.5, color: T.red }}>{revealed.problem}</span>
                : <span style={{ fontFamily: T.mono, fontSize: 13, color: T.bright }} data-totp-revealed>{groupCode(revealed.code)} <span style={{ fontSize: 10, color: T.muted }}>· {revealed.left} s · compare with the phone</span></span>)}
            </div>
          )}
        </div>

        {/* step 1 */}
        <div data-totp-step="1" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
          {step('1', 'get the setup key (Option A, the official way)')}
          <ol style={{ margin: 0, paddingLeft: 18, fontSize: 11, lineHeight: 1.6, color: T.text }}>
            {OPTION_A_STEPS.map(s => <li key={s}>{s}</li>)}
          </ol>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 6 }}>
            <Btn variant="primary" size="sm" onClick={() => openExternal(ICICI_SETTINGS_URL)} title="Opens ICICI Direct settings in your browser">OPEN ICICI SETTINGS ↗</Btn>
            {ICICI_FAQ_LINKS.map(l => <Chip key={l.url} color={T.cyan} onClick={() => openExternal(l.url)} title={l.url}>{l.label} ↗</Chip>)}
            <span style={{ fontSize: 10, color: T.dim }}>Option B: export from Google Authenticator and decode the otpauth-migration QR offline on this Mac.</span>
          </div>
        </div>

        {/* step 2 */}
        <div data-totp-step="2" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
          {step('2', 'paste the key (base32 or the otpauth:// URI)')}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <div style={{ flex: 1 }} data-totp-input>
              <Input type={show ? 'text' : 'password'} value={key} onChange={setKey} placeholder="JBSW Y3DP EHPK 3PXP …  or  otpauth://totp/…?secret=…" autoComplete="off" aria-label="ICICI authenticator setup key"
                style={{ letterSpacing: show ? 1 : 2 }} />
            </div>
            <Btn size="sm" onClick={() => setShow(s => !s)} title={show ? 'Hide the key' : 'Show the key'}>{show ? 'HIDE' : 'SHOW'}</Btn>
          </div>
          <div style={{ marginTop: 6, fontSize: 11, color: T.text, display: 'grid', gap: 4 }}>
            {preview?.valid ? (
              <>
                <div data-totp-preview>Current code <span style={{ fontFamily: T.mono, fontSize: 14, color: T.bright }}>{groupCode(preview.code)}</span>
                  <span style={{ color: T.muted }}> · {left} s · {preview.digits} digits · {preview.period} s · {preview.algorithm} · key length {preview.length}</span></div>
                <Meter value={left / Math.max(1, preview.period)} color={T.cyan} height={4} />
                <div style={{ fontSize: 10.5, color: T.muted }}>open Google Authenticator: the ICICI entry must show the same six digits; wait for one rollover before you save.</div>
              </>
            ) : previewErr ? <div style={{ fontSize: 10.5, color: T.amber }}>{previewErr}</div>
              : <div style={{ fontSize: 10.5, color: T.dim }}>the code appears here 400 ms after you paste; nothing is stored until SAVE.</div>}
          </div>
        </div>

        {/* step 3 */}
        <div data-totp-step="3" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
          {step('3', 'confirm the six digits from the phone, then save')}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Input value={confirm} onChange={v => setConfirm(v.replace(/[^\d\s]/g, '').slice(0, 7))} placeholder="6 digits from the phone" width={180} aria-label="confirmation code" autoComplete="one-time-code" />
            <Btn variant="go" onClick={save} disabled={!canSave} title={canSave ? 'Saves ICICI_TOTP_SECRET to .env through the guarded writer' : 'Paste a valid key and type the six digits the phone shows'}>{saving ? 'SAVING…' : 'SAVE'}</Btn>
            {saveMsg && <span data-totp-save-msg style={{ fontSize: 11, color: saveMsg.ok ? T.green : T.red }}>{saveMsg.ok ? '✓ ' : '✕ '}{saveMsg.text}</span>}
          </div>
          <div style={{ marginTop: 8, fontSize: 10.5, color: T.muted }}>Keychain (preferred: encrypted, not in repo backups) — run this in Terminal; it prompts for the key, nothing lands in shell history:</div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 4, flexWrap: 'wrap' }}>
            <code data-keychain-one-liner style={{ fontFamily: T.mono, fontSize: 10.5, color: T.cyan, background: '#07090d', border: `1px solid ${T.border}`, padding: '4px 8px', userSelect: 'all' }}>{oneLiner}</code>
            <Btn size="sm" onClick={copy}>{copied ? 'COPIED' : 'COPY'}</Btn>
            <Btn size="sm" onClick={() => loadStatus()} title="Re-read the status: a Keychain item shows as TOTP CONFIGURED · Keychain">DETECT</Btn>
            {status?.keychain_present != null && <span style={{ fontSize: 10.5, color: status.keychain_present ? T.green : T.dim }}>{status.keychain_present ? 'Keychain item found' : 'no Keychain item yet'}</span>}
          </div>
        </div>

        {/* step 4 */}
        <div data-totp-step="4" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
          {step('4', 'test it')}
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <Btn variant="primary" size="sm" onClick={() => checkSession(false)} disabled={watch === 'starting' || watch === 'watching'}
              title="POST /api/telemetry/icici-refresh → master-controller runs the session check; a login happens only if today's session has expired">CHECK SESSION / LOG IN IF EXPIRED</Btn>
            {status?.force_supported && (
              forceArmed
                ? <>
                    <Btn variant="danger" size="sm" onClick={() => { setForceArmed(false); void checkSession(true) }} disabled={!!forceReason} title={forceReason ?? 'Ends today\'s session and logs in again now'}>CONFIRM FORCE LOGIN</Btn>
                    <Btn size="sm" onClick={() => setForceArmed(false)}>CANCEL</Btn>
                  </>
                : <Btn size="sm" onClick={() => setForceArmed(true)} disabled={!!forceReason} title={forceReason ?? 'A fresh login even if the token still works (ends today\'s session)'}>FORCE A NEW LOGIN (ends today's session)</Btn>
            )}
            {status?.force_supported && status.block?.credentials && <span style={{ fontSize: 10.5, color: T.amber }}>▲ a credentials block file exists: a forced login will be refused until it is cleared</span>}
          </div>
          <div data-totp-watch={watch} style={{ fontSize: 11, color: watch === 'live' ? T.green : watch === 'timeout' || watch === 'error' || watch === 'unsupported' ? T.amber : T.muted, marginTop: 6 }}>
            {watch === 'live' && <Dot color={T.green} pulse size={6} />} {sessionWatchLine(watch, elapsed, watchDetail)}
          </div>
        </div>

        {/* remove */}
        <div data-totp-step="remove" style={{ borderTop: `1px solid ${T.border}`, paddingTop: 8, display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          {disableArmed
            ? <>
                <span style={{ fontSize: 11, color: T.amber }}>Clear ICICI_TOTP_SECRET from .env? The 08:00 job falls back to the SMS OTP on Telegram.</span>
                <Btn variant="danger" size="sm" onClick={disable}>CONFIRM DISABLE</Btn>
                <Btn size="sm" onClick={() => setDisableArmed(false)}>CANCEL</Btn>
              </>
            : <Btn size="sm" onClick={() => setDisableArmed(true)} disabled={!status?.configured} title={status?.configured ? 'Writes ICICI_TOTP_SECRET= through the guarded .env writer' : 'Nothing to disable'}>DISABLE AUTO-LOGIN</Btn>}
          {disableMsg && <span style={{ fontSize: 10.5, color: T.muted }}>{disableMsg}</span>}
        </div>

        {status?.block?.totp && (
          <Notice color={T.red}>ICICI rejected the authenticator code on the last run (block file present): the secret no longer matches ICICI. Re-register the authenticator (step 1), save the new key (steps 2–3); unattended runs use the SMS path until the secret changes.</Notice>
        )}
        <div style={{ fontSize: 9.5, color: T.dim, lineHeight: 1.5 }}>
          The key is kept in this page's memory only until SAVE and is never written to preferences or browser storage; the preview call goes to ui-api on this machine and returns six digits, never the key. Deploy order (PLAN §g): secret first (no restart), attended test after 15:40, then leave the 08:00 job alone.
        </div>
      </div>
    </Panel>
  )
}

export default IciciTotpPanel
