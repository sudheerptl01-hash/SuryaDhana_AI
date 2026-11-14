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

// ── F9-01: the pre-open hour, which F8-04's reorder had handed to IDLE ──────────────────────────────────
// F9 ran the shipped model against Monday 16 Nov with a dead session and found 07:50, 08:15, 09:00 and 09:14
// all returning grey "BRKR IDLE — the token expires at midnight IST by design": true at 2 a.m., misleading at
// 08:30, and the 08:00 login job's failure is only repairable before the 09:15 open. These pin the window.
const DEAD = { breeze_session: false }
// R14-D: this fixture carried NO mcx_window, so every case below ran the unknown-payload fallback instead of
// what the server actually sends — and the two cases asserting "09:00 → BRKR PRE" and "09:14 still warns"
// passed while the shipped chip returned BRKR DOWN at both. A gate written for exactly that window was
// blinded by a field added later. The default now mirrors a real Monday (MCX gold opens 09:00, NSE 09:15),
// and the cases that need a different calendar override it explicitly.
const COUNTS = { errors_today: 133, by_method: { generate_session: 135 },
                 mcx_window: { open_hm: 900, close_hm: 2355 } }
// Each fixture carries the calendar of the day it names, because that is what the server sends: a weekend
// has NO MCX window, an NSE holiday has MCX's own evening one (24 Nov 2026 = 17:00–23:55), and a normal
// Monday has 09:00–23:55. Sharing one default across all three is what let R14-D through.
const WEEKEND = { ...COUNTS, trading_day: false, mcx_window: null }
const HOL = { ...COUNTS, trading_day: false, mcx_window: { open_hm: 1700, close_hm: 2355 } }
const monAt = (hh: number, mm: number) => brokerFace(DEAD, COUNTS, at(2026, 11, 16, hh, mm))   // Mon 16 Nov

check('F9-01 07:50 Monday is still quiet (the 08:00 login has not run yet)', monAt(7, 50)?.tone === 'idle', monAt(7, 50))
check('F9-01 08:15 Monday warns BRKR PRE', monAt(8, 15)?.label === 'BRKR PRE' && monAt(8, 15)?.tone === 'warn', monAt(8, 15))
check('F9-01 09:00 Monday warns BRKR PRE', monAt(9, 0)?.label === 'BRKR PRE', monAt(9, 0))
check('F9-01 09:14 Monday — the last minute it is still fixable — warns', monAt(9, 14)?.label === 'BRKR PRE', monAt(9, 14))
check('F9-01 09:15 Monday escalates to red BRKR DOWN', monAt(9, 15)?.tone === 'bad' && monAt(9, 15)?.label === 'BRKR DOWN', monAt(9, 15))
check('F9-01 the PRE title names the repair the owner can still do',
  (monAt(8, 30)?.title ?? '').includes('/login') && (monAt(8, 30)?.title ?? '').includes('OTP'), monAt(8, 30)?.title)
// the nightly-silence contract still holds: a weekend 08:30 must stay grey, not warn
check('F9-01 Saturday 08:30 stays grey (trading days only)',
  brokerFace(DEAD, WEEKEND, at(2026, 11, 14, 8, 30))?.tone === 'idle', brokerFace(DEAD, WEEKEND, at(2026, 11, 14, 8, 30)))
check('F9-01 Sunday 08:30 stays grey', brokerFace(DEAD, COUNTS, at(2026, 11, 15, 8, 30))?.tone === 'idle')
// and a session that came up normally says nothing at all through the same window
check('F9-01 a healthy session before the open renders nothing',
  brokerFace({ breeze_session: true }, { errors_today: 0 }, at(2026, 11, 16, 8, 30)) === null)

// ── F10-02: a refusal is not an error, and the chip was blind to a whole day of them ────────────────────
// `errors_today` counts calls WHERE ok = 0; refusals live in their own table and never reach it. So if the
// budget refused every call of the day — the exact failure this metering was added to make possible — the
// header stayed silent. One refusal means something asked for data and got none; that is always worth saying.
const MID = at(2026, 11, 16, 11, 0)                                   // Monday, market open
check('F10-02 one refusal speaks up even with a healthy session',
  brokerFace({ breeze_session: true }, { refused_today: 1 }, MID)?.tone === 'warn',
  brokerFace({ breeze_session: true }, { refused_today: 1 }, MID))
check('F10-02 the label names the refusals',
  brokerFace({ breeze_session: true }, { refused_today: 7 }, MID)?.label === 'BRKR 7 REFUSED',
  brokerFace({ breeze_session: true }, { refused_today: 7 }, MID))
check('F10-02 refusals outrank the error count (they are the sharper fact)',
  brokerFace({ breeze_session: true }, { refused_today: 2, errors_today: 50 }, MID)?.label === 'BRKR 2 REFUSED')
check('F10-02 no refusals and few errors is still silence',
  brokerFace({ breeze_session: true }, { refused_today: 0, errors_today: 3 }, MID) === null)

// ── F10-05: the pre-open alarm must follow the exchange calendar, not the weekday ───────────────────────
const PRE_T = at(2026, 11, 24, 8, 30)                                 // Tue 24 Nov 2026 — Guru Nanak Jayanti
check('F10-05 a midweek HOLIDAY does not raise the pre-open alarm',
  brokerFace(DEAD, { ...COUNTS, trading_day: false }, PRE_T)?.tone === 'idle',
  brokerFace(DEAD, { ...COUNTS, trading_day: false }, PRE_T))
check('F10-05 a real trading day still raises it',
  brokerFace(DEAD, { ...COUNTS, trading_day: true }, at(2026, 11, 16, 8, 30))?.label === 'BRKR PRE')
check('F10-05 an unknown calendar falls back to the weekday test (no worse than before)',
  brokerFace(DEAD, COUNTS, at(2026, 11, 16, 8, 30))?.label === 'BRKR PRE')
check('F10-05 …and stays quiet on a weekend even when the calendar is unknown',
  brokerFace(DEAD, WEEKEND, at(2026, 11, 14, 8, 30))?.tone === 'idle')

// ── F11-03: the calendar must gate the RED rung too, not only the amber one ────────────────────────────
// F10-05 was fixed on the pre-open branch and the DOWN branch kept running on sessionExpected's weekday test,
// so on Guru Nanak Jayanti (Tue 24 Nov 2026 — in the holiday master this payload carries) the chip would have
// shown red BRKR DOWN from 09:15 to 23:30 over a shut market. A whole day of false alarm.
check('F11-03 midday on a HOLIDAY is not red', brokerFace(DEAD, HOL, at(2026, 11, 24, 12, 0))?.tone !== 'bad',
  brokerFace(DEAD, HOL, at(2026, 11, 24, 12, 0)))
check('F11-03 …it is the grey idle rung', brokerFace(DEAD, HOL, at(2026, 11, 24, 12, 0))?.tone === 'idle')
// F12 corrected this one: the holiday master the payload carries is NSE's, and MCX is NOT shut whenever NSE
// is. shared/mcx_specs.trading_window(2026-11-24) returns 17:00–23:55 — Guru Nanak Jayanti is an MCX EVENING
// session — so a dead broker session at 22:00 that day is real and must stay red. The first version of this
// case asserted the opposite and would have locked in a silence over live commodity hours.
check('F12 22:00 on an NSE holiday is still RED — MCX trades that evening (17:00–23:55)',
  brokerFace(DEAD, HOL, at(2026, 11, 24, 22, 0))?.tone === 'bad',
  brokerFace(DEAD, HOL, at(2026, 11, 24, 22, 0)))
check('F12 …while 12:00 that day, inside the NSE window only, stays grey',
  brokerFace(DEAD, HOL, at(2026, 11, 24, 12, 0))?.tone === 'idle')
check('F12 a WEEKEND evening is still grey (MCX is shut Sat/Sun)',
  brokerFace(DEAD, WEEKEND, at(2026, 11, 14, 22, 0))?.tone === 'idle')
check('F11-03 the same clock on a TRADING day is still red',
  brokerFace(DEAD, { ...COUNTS, trading_day: true }, at(2026, 11, 24, 12, 0))?.tone === 'bad')
check('F11-03 an unknown calendar still goes red midday on a weekday (no worse than before)',
  brokerFace(DEAD, COUNTS, at(2026, 11, 16, 12, 0))?.tone === 'bad')

// ── F11-04: the REFUSED rung has to fire in the case it was written for ────────────────────────────────
// `generate_session` is itself metered, so an exhausted budget is WHY there is no session — and the first
// version put REFUSED below every !connected rung, where it could never be reached in that exact case.
const REFUSED = { errors_today: 4, refused_today: 9, trading_day: true,
                 mcx_window: { open_hm: 900, close_hm: 2355 } }
check('F11-04 a refused login shows the CAUSE, not a bare "no session"',
  brokerFace(DEAD, REFUSED, at(2026, 11, 16, 12, 0))?.label === 'BRKR 9 REFUSED',
  brokerFace(DEAD, REFUSED, at(2026, 11, 16, 12, 0)))
check('F11-04 it is red during market hours (the session really is gone)',
  brokerFace(DEAD, REFUSED, at(2026, 11, 16, 12, 0))?.tone === 'bad')
check('F11-04 it also fires in the pre-open hour',
  brokerFace(DEAD, REFUSED, at(2026, 11, 16, 8, 30))?.label === 'BRKR 9 REFUSED')
check('F11-04 but NOT on a holiday, where no session is expected at all',
  brokerFace(DEAD, { ...REFUSED, trading_day: false, mcx_window: { open_hm: 1700, close_hm: 2355 } }, at(2026, 11, 24, 12, 0))?.tone === 'idle')
check('F11-04 with a session up, refusals stay the amber rung',
  brokerFace({ breeze_session: true }, REFUSED, at(2026, 11, 16, 12, 0))?.tone === 'warn')
// F11-05: the tooltip must name a page that exists — SYS has only system|data sub-views; BRKR is top-level
check('F11-05 no tooltip points at a SYS sub-view that does not exist',
  !JSON.stringify([brokerFace(DEAD, REFUSED, at(2026, 11, 16, 12, 0)),
                   brokerFace({ breeze_session: true }, REFUSED, at(2026, 11, 16, 12, 0))]).includes('SYS \u203a BRKR'))

// ── F13-06: the MCX window comes from MCX's own calendar, in both directions ───────────────────────────
// The hardcode `weekday && hm <= 2330` had two holes. It went SILENT over 23:30–23:55, which is the window
// whose Breeze 1-minute bars the MCX settlement of record is computed from (gold_mcx_close, 23:58) — so a
// dead session went unflagged exactly when it would cost the settlement. And it painted BRKR DOWN all
// evening on a full MCX closure, which is F10-05 reinstated on the branch F11-03 had just fixed.
// shared/mcx_specs.trading_window: Mon 16 Nov = 09:00–23:55, Tue 24 Nov = 17:00–23:55, Fri 25 Dec = SHUT.
const MON_WIN = { ...COUNTS, trading_day: true, mcx_window: { open_hm: 900, close_hm: 2355 } }
const HOL_WIN = { ...COUNTS, trading_day: false, mcx_window: { open_hm: 1700, close_hm: 2355 } }
const SHUT = { ...COUNTS, trading_day: false, mcx_window: null }

check('F13-06 23:40 Monday is RED — MCX runs to 23:55 and the settlement needs those bars',
  brokerFace(DEAD, MON_WIN, at(2026, 11, 16, 23, 40))?.tone === 'bad',
  brokerFace(DEAD, MON_WIN, at(2026, 11, 16, 23, 40)))
check('F13-06 23:56 Monday, after the close, is grey',
  brokerFace(DEAD, MON_WIN, at(2026, 11, 16, 23, 56))?.tone === 'idle')
check('F13-06 a fully SHUT MCX day is grey all evening, not red',
  brokerFace(DEAD, SHUT, at(2026, 12, 25, 18, 0))?.tone === 'idle',
  brokerFace(DEAD, SHUT, at(2026, 12, 25, 18, 0)))
check('F13-06 …and still grey at 22:00 that day', brokerFace(DEAD, SHUT, at(2026, 12, 25, 22, 0))?.tone === 'idle')
check('F13-06 an NSE holiday with an MCX evening is red inside that evening',
  brokerFace(DEAD, HOL_WIN, at(2026, 11, 24, 22, 0))?.tone === 'bad')
check('F13-06 …and grey BEFORE that evening session opens (16:00 < 17:00)',
  brokerFace(DEAD, HOL_WIN, at(2026, 11, 24, 16, 0))?.tone === 'idle',
  brokerFace(DEAD, HOL_WIN, at(2026, 11, 24, 16, 0)))
check('F13-06 an unknown window falls back to the old weekday heuristic',
  brokerFace(DEAD, { ...COUNTS, trading_day: true }, at(2026, 11, 16, 22, 0))?.tone === 'bad')

// ── R14-D: MCX opens BEFORE NSE, so `expected` turns true at 09:00 and used to preempt the pre-open rung ──
// From 09:00 to 09:14 the chip showed BRKR DOWN — a damage report — instead of BRKR PRE, which is the only
// sentence in the terminal that names a repair the owner can still make before the open. Fifteen minutes,
// on the morning of a login that had failed 188 times the day before.
const MON = { ...COUNTS, trading_day: true }
for (const [h, m] of [[8, 15], [8, 30], [9, 0], [9, 5], [9, 14]] as const) {
  const f = brokerFace(DEAD, MON, at(2026, 11, 16, h, m))
  check(`R14-D ${h}:${String(m).padStart(2, '0')} Monday is BRKR PRE even though MCX is open`,
    f?.label === 'BRKR PRE', f)
}
check('R14-D 09:15 escalates to DOWN once the repair window has closed',
  brokerFace(DEAD, MON, at(2026, 11, 16, 9, 15))?.label === 'BRKR DOWN')
check('R14-D the PRE title still names the repair at 09:00',
  (brokerFace(DEAD, MON, at(2026, 11, 16, 9, 0))?.title ?? '').includes('/login'))
check('R14-D …and says MCX is already trading, because it is',
  (brokerFace(DEAD, MON, at(2026, 11, 16, 9, 0))?.title ?? '').includes('MCX is already trading'))
check('R14-D before MCX opens the same rung does NOT claim it is trading',
  !(brokerFace(DEAD, MON, at(2026, 11, 16, 8, 30))?.title ?? '').includes('MCX is already trading'))

console.log(`brokerChip.check: ${passed} passed, ${failed} failed`)
if (failed > 0) process.exit(1)
