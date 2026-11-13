/**
 * Unit checks for the upstream (data-service) strip model (O-F5a, D-BOOT). No test framework in ui/, so this
 * file is type-checked by `tsc --noEmit` and executed directly by Node 25 (erasable TypeScript, no build step):
 *
 *     node ui/components/desktop/__tests__/upstream.check.ts
 *
 * Covers: the probe reducer (warming / readonly / ok / unknown), the 5→10→15 s backoff, the strip-kind map and
 * its precedence contract, the recovery predicate that drives panel reloads, the module store, and the SPEC
 * copy (verbatim strings; no direction words; no raw transport text).
 */
import type { UpstreamProbeResult, UpstreamSnapshot, UpstreamState } from '../upstream'

// imported by URL with the .ts extension (what Node needs) and typed via typeof import (what tsc needs),
// exactly like desktop.check.ts
type UpstreamMod = typeof import('../upstream')
const U = (await import(new URL('../upstream.ts', import.meta.url).href)) as UpstreamMod

let failures = 0
let passes = 0
function check(name: string, cond: boolean, detail = ''): void {
  if (cond) { passes++; return }
  failures++
  console.error(`FAIL ${name}${detail ? ` — ${detail}` : ''}`)
}
const eq = (name: string, got: unknown, want: unknown) =>
  check(name, JSON.stringify(got) === JSON.stringify(want), `got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`)

const UP: UpstreamProbeResult = { dataService: 'up', dbReadOnly: false }
const RO: UpstreamProbeResult = { dataService: 'up', dbReadOnly: true }
const DOWN: UpstreamProbeResult = { dataService: 'down', dbReadOnly: false }

// ── reducer ───────────────────────────────────────────────────────────────────────────────────────────────
{
  const t0 = 1_000_000
  const s0 = U.initialUpstream(t0)
  eq('initial is unknown', [s0.state, s0.downCount], ['unknown', 0])

  const ok1 = U.reduceUpstreamProbe(s0, UP, t0 + 1)
  eq('up+writable → ok', [ok1.state, ok1.downCount, ok1.since], ['ok', 0, t0 + 1])
  const ok2 = U.reduceUpstreamProbe(ok1, UP, t0 + 20)
  eq('steady ok keeps since', ok2.since, t0 + 1)

  const w1 = U.reduceUpstreamProbe(ok2, DOWN, t0 + 30)
  const w2 = U.reduceUpstreamProbe(w1, DOWN, t0 + 35)
  const w3 = U.reduceUpstreamProbe(w2, DOWN, t0 + 45)
  eq('down → warming, counting', [w1.state, w1.downCount, w2.downCount, w3.downCount], ['warming', 1, 2, 3])
  eq('warming keeps its since', [w1.since, w3.since], [t0 + 30, t0 + 30])

  const ro = U.reduceUpstreamProbe(w3, RO, t0 + 60)
  eq('up+read-only → readonly, count reset', [ro.state, ro.downCount, ro.since], ['readonly', 0, t0 + 60])
  const roOk = U.reduceUpstreamProbe(ro, UP, t0 + 90)
  eq('lock cleared → ok', [roOk.state, roOk.since], ['ok', t0 + 90])

  const un = U.reduceUpstreamProbe(roOk, null, t0 + 100)
  eq('failed probe → unknown (ConnectionBanner territory, never a strip)', [un.state, un.downCount], ['unknown', 0])
  check('unknown asks for no strip', U.upstreamStripKind(un) === null)
}

// ── backoff / cadence ─────────────────────────────────────────────────────────────────────────────────────
{
  const w = (downCount: number): UpstreamSnapshot => ({ state: 'warming', downCount, since: 0, nextProbeAt: null })
  eq('warming backoff 5→10→15 s, capped', [1, 2, 3, 4, 9].map(n => U.upstreamDelayMs(w(n))),
    [5_000, 10_000, 15_000, 15_000, 15_000])
  eq('readonly re-probes every 30 s', U.upstreamDelayMs({ state: 'readonly', downCount: 0, since: 0, nextProbeAt: null }), 30_000)
  eq('ok stays cheap (15 s)', U.upstreamDelayMs({ state: 'ok', downCount: 0, since: 0, nextProbeAt: null }), 15_000)
  eq('unknown retries in 10 s', U.upstreamDelayMs({ state: 'unknown', downCount: 0, since: 0, nextProbeAt: null }), 10_000)
}

// ── strip kinds + precedence contract ─────────────────────────────────────────────────────────────────────
{
  const snap = (state: UpstreamState): UpstreamSnapshot => ({ state, downCount: 0, since: 0, nextProbeAt: null })
  eq('strip kinds', (['unknown', 'ok', 'warming', 'readonly'] as const).map(s => U.upstreamStripKind(snap(s))),
    [null, null, 'warming', 'readonly'])
  // PlatformShell's precedence lines (LINK DOWN > WARMING UP > DB READ-ONLY > STAND DOWN): assert on the source
}

// ── recovery predicate (drives the reconnect-event panel reload) ──────────────────────────────────────────
{
  const snap = (state: UpstreamState): UpstreamSnapshot => ({ state, downCount: 0, since: 0, nextProbeAt: null })
  check('warming → ok recovers', U.upstreamRecovered(snap('warming'), snap('ok')))
  check('warming → readonly recovers (reads are back)', U.upstreamRecovered(snap('warming'), snap('readonly')))
  check('readonly → ok is not a recovery (reads worked throughout)', !U.upstreamRecovered(snap('readonly'), snap('ok')))
  check('unknown → ok is not a recovery (ConnectionBanner owns that path)', !U.upstreamRecovered(snap('unknown'), snap('ok')))
  check('warming → warming is not a recovery', !U.upstreamRecovered(snap('warming'), snap('warming')))
}

// ── module store ──────────────────────────────────────────────────────────────────────────────────────────
{
  const seen: UpstreamState[] = []
  const off = U.subscribeUpstream(s => seen.push(s.state))
  U.publishUpstream({ state: 'warming', downCount: 1, since: 1, nextProbeAt: null })
  eq('latestUpstream follows publish', U.latestUpstream().state, 'warming')
  off()
  U.publishUpstream({ state: 'ok', downCount: 0, since: 2, nextProbeAt: null })
  eq('unsubscribed listener stops', seen, ['warming'])
  eq('store still advanced', U.latestUpstream().state, 'ok')
}

// ── SPEC copy (RISK §b, verbatim; labelling rules) ────────────────────────────────────────────────────────
{
  eq('WARMING tag', U.WARMING_TAG, 'WARMING UP')
  eq('WARMING main', U.WARMING_MAIN, 'market data service is starting')
  eq('WARMING detail', U.WARMING_DETAIL, 'panels fill in as it answers')
  eq('READONLY tag', U.READONLY_TAG, 'DB READ-ONLY')
  eq('READONLY main', U.READONLY_MAIN, 'showing stored data; tonight’s ingest is paused until the lock clears')
  eq('READONLY detail', U.READONLY_DETAIL, 'the watchdog fixes start order')
  const all = [U.WARMING_TAG, U.WARMING_MAIN, U.WARMING_DETAIL, U.READONLY_TAG, U.READONLY_MAIN, U.READONLY_DETAIL].join(' · ')
  check('no direction words in the strip copy',
    !/\b(buy|sell|bullish|bearish|should|opportunity|setup|bias)\b/i.test(all), all)
  check('no raw transport text in the strip copy', !/connection attempts|ConnectError|httpx|50[23]/i.test(all))
  check("no instruction to the owner ('don't' / 'stop')", !/\bdon'?t\b|\bstop\b/i.test(all))
}

// ── source assertions: PlatformShell precedence + ShellNotices strip wiring ───────────────────────────────
{
  const { readFileSync } = await import('node:fs')
  const shell = readFileSync(new URL('../PlatformShell.tsx', import.meta.url), 'utf8')
  check('strip only while the connection banner is hidden (LINK DOWN outranks it)',
    /phase === 'hidden' \? upstreamStripKind\(upstream\) : null/.test(shell))
  check('STAND DOWN sits below the upstream strip',
    /standDown\.banner && phase === 'hidden' && upstreamKind === null/.test(shell))
  check('the strip adds its height to --shell-top',
    /upstreamKind !== null \|\| phase !== 'hidden' \|\| showStandDown \? BANNER_HEIGHT : 0/.test(shell))
  const notices = readFileSync(new URL('../ShellNotices.tsx', import.meta.url), 'utf8')
  check('recovery dispatches the SAME reconnected event as a ui-api outage',
    /upstreamRecovered\(prev, next\)/.test(notices) && /RECONNECTED_EVENT/.test(notices))
  check('strip is calm: role status, no alert, no flashing',
    /role="status" aria-live="polite" data-sd-upstream/.test(notices) && !/infinite/.test(notices))
  check('404 / failed probe yields no signal (old ui-api builds never show a strip)',
    /if \(!r\.ok\) return null/.test(notices))
}

if (failures) { console.error(`${failures} of ${passes + failures} checks failed`); process.exit(1) }
console.log(`upstream.check: all ${passes} checks pass`)
