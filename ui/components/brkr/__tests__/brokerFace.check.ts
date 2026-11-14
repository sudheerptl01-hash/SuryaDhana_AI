/**
 * The broker-session chip (F7-05). Run: node --experimental-strip-types ui/components/brkr/__tests__/brokerChip.check.ts
 *
 * The defect: 121 failed logins on 14 Nov and `errors_today` had no reader in ui/, so a dead session looked
 * healthy on every page. These pin the face, and above all pin that it stays QUIET when there is nothing to say —
 * a chip that cries every night is a chip the owner learns to ignore, which would reinstate the same blindness.
 */
// The repo's convention for a check that needs RUNTIME values from a project module (see
// desktop/__tests__/upstream.check.ts): import by URL with the .ts extension, which is what Node needs, and type
// it via `typeof import`, which is what tsc needs — a bare '../brokerFace.ts' import fails tsc (TS5097).
type FaceMod = typeof import('../brokerFace')
const M = (await import(new URL('../brokerFace.ts', import.meta.url).href)) as FaceMod
const { brokerFace, sessionExpected, istClock } = M

let passed = 0
let failed = 0
const check = (name: string, ok: boolean, detail?: unknown) => {
  if (ok) { passed++ } else { failed++; console.log(`FAIL ${name}${detail === undefined ? '' : ` :: ${JSON.stringify(detail)}`}`) }
}
/**
 * An IST wall clock for the model.
 *
 * F8-05: this used to return `new Date(y, m-1, d, hh, mm)` — a LOCAL-time Date — and the model read getDay /
 * getHours off it. Both the model and these fixtures therefore shared one wrong assumption, which is why the
 * check could not see the bug: run the terminal from a non-IST machine and the market window slides. The model
 * now takes {day, hm} built from Asia/Kolkata, and `at` constructs that clock from a real UTC instant, so the
 * fixtures no longer agree with the model by accident. `atUtcInstant` below proves it end to end.
 */
const at = (y: number, m: number, d: number, hh: number, mm: number) => {
  // the IST instant (UTC+5:30) for that wall-clock reading, then converted back the way the component does
  const utcMs = Date.UTC(y, m - 1, d, hh, mm) - (5 * 60 + 30) * 60_000
  return istClock(new Date(utcMs))
}

// ── when a session is expected at all ────────────────────────────────────────────────────────────
check('a session is expected during NSE hours on a weekday', sessionExpected(at(2026, 11, 16, 10, 0)))
check('…and through MCX hours', sessionExpected(at(2026, 11, 16, 22, 0)))
check('…but not before the open', !sessionExpected(at(2026, 11, 16, 8, 30)))
check('…and never on a Saturday', !sessionExpected(at(2026, 11, 14, 10, 0)))
check('…nor a Sunday', !sessionExpected(at(2026, 11, 15, 10, 0)))
check('nseOnly stops at 15:30', !sessionExpected(at(2026, 11, 16, 22, 0), true) && sessionExpected(at(2026, 11, 16, 15, 0), true))

// ── the defect itself: a dead session during market hours must SHOUT ────────────────────────────
{
  const face = brokerFace({ state: 'DISCONNECTED', breeze_session: false },
    { errors_today: 119, by_method: { generate_session: 121 } }, at(2026, 11, 16, 9, 20))
  check('a dead session in market hours is BAD', face?.tone === 'bad' && face?.label === 'BRKR DOWN', face)
  check('…and the hover carries the counts a trader needs', !!face && face.title.includes('119') && face.title.includes('121'), face?.title)
  check('…and says what degrades, without advising', !!face && face.title.includes('stored or delayed')
    && !/should|must you|recommend/i.test(face.title), face?.title)
}

// ── the quiet cases: the chip must not become noise ─────────────────────────────────────────────
check('a healthy session says nothing',
  brokerFace({ state: 'LIVE', breeze_session: true }, { errors_today: 0, by_method: {} }, at(2026, 11, 16, 10, 0)) === null)
check('a healthy session with a couple of transient errors still says nothing',
  brokerFace({ state: 'LIVE', breeze_session: true }, { errors_today: 3, by_method: { generate_session: 2 } }, at(2026, 11, 16, 10, 0)) === null)
check('nothing fetched yet → no guess', brokerFace(null, null, at(2026, 11, 16, 10, 0)) === null)
{
  const night = brokerFace({ state: 'DISCONNECTED', breeze_session: false }, { errors_today: 0 }, at(2026, 11, 14, 9, 0))
  check('no session on a Saturday is IDLE, not an alarm', night?.tone === 'idle', night)
  check('…and the hover explains the token expiry rather than implying a fault',
    !!night && night.title.includes('expires at midnight'), night?.title)
}

// ── the early warning: many failures even though a session eventually came up ───────────────────
{
  const warn = brokerFace({ state: 'LIVE', breeze_session: true },
    { errors_today: 40, by_method: { generate_session: 45 } }, at(2026, 11, 16, 10, 0))
  check('repeated login failures warn even with a session up', warn?.tone === 'warn' && warn.label === 'BRKR 40 ERR', warn)
  check('…and name the quota cost', !!warn && warn.title.includes('daily broker quota'), warn?.title)
}

// ── it can never leak a credential, because it never reads one ──────────────────────────────────
{
  const raw = (await import('node:fs')).readFileSync(new URL('../brokerFace.ts', import.meta.url), 'utf8')
  // Strip comments first: the file DISCUSSES connection-status to record why it must never read it, and a prose
  // mention is not a reference. The gate is about code.
  const code = raw.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
  check('the model never READS connection-status (whose payload carries the API key in login_url)',
    !code.includes('connection-status'))
  check('…and reads no credential-shaped field', !/login_url|api_key|session_token|secret/i.test(code))
  check('…while the file still records WHY, so the next author does not re-add it', raw.includes('login_url'))
}

// ── the two scenarios F8 found, pinned as cases rather than as prose ─────────────────────────────────────
// Both were defects in code written on 14 Nov, and both fail QUIETLY: one paints a false alarm at 2 a.m. from
// a non-IST machine, the other makes exactly the nightly noise this model's contract promises to avoid.

// F8-05: Friday 20:30 UTC is Saturday 02:00 in India — markets shut, no session expected, whatever TZ the
// browser runs in. (Before the fix the model read the browser's own getDay/getHours and called this a weekday
// inside market hours, painting a red BRKR DOWN at two in the morning.)
const f805 = istClock(new Date(Date.UTC(2026, 10, 13, 20, 30)))
check('F8-05 the IST weekday of 20:30 UTC Friday is Saturday', f805.day === 6, f805)
check('F8-05 the IST time of 20:30 UTC Friday is 02:00', f805.hm === 200, f805)
check('F8-05 no session is expected at 02:00 IST Saturday', sessionExpected(f805) === false, f805)
const f805face = brokerFace({ breeze_session: false }, { errors_today: 127 }, f805)
check('F8-05 the chip is grey at 02:00 IST Saturday, not a red alarm', f805face?.tone === 'idle', f805face)

// F8-04: the live capture F8 made — a closed Saturday carrying a dead token must be IDLE, not amber.
const f804sat = at(2026, 11, 14, 9, 39)
const f804 = brokerFace({ breeze_session: false }, { errors_today: 127, by_method: { generate_session: 129 } }, f804sat)
check('F8-04 a closed Saturday with 127 failures is IDLE', f804?.tone === 'idle' && f804?.label === 'BRKR IDLE', f804)
// the branch is reordered, not removed: in market hours the same counts still speak up
const f804mon = brokerFace({ breeze_session: true }, { errors_today: 127, by_method: { generate_session: 129 } },
  at(2026, 11, 16, 11, 0))
check('F8-04 the same counts DO warn during market hours', f804mon?.tone === 'warn', f804mon)
check('F8-04 the title does not pin all-method errors on logins',
  f804mon?.title.includes('all methods') === true, f804mon?.title)

console.log(`brokerChip.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
