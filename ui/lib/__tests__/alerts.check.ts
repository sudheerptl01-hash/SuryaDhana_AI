/**
 * Price-alert notification checks (C3-logic-unchanged-05 / -07): one notification per check with a count, the
 * same text in the browser and the app, inside the shell's limits; first-visit seen markers.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/lib/__tests__/alerts.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failing check.
 */
import * as fs from 'node:fs'

type AlertTextMod = typeof import('../alertText')
const A = (await import(new URL('../alertText.ts', import.meta.url).href)) as AlertTextMod

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) {
    passed++
    return
  }
  failed++
  console.error(`FAIL ${name}${extra !== undefined ? ` :: ${JSON.stringify(extra)}` : ''}`)
}

function hit(sym: string, side: 'above' | 'below', level: number, price: number) {
  return { sym, side, level, price }
}

// ── single hit: unchanged wording ───────────────────────────────────────────────────────────────
{
  const n = A.alertNotification([hit('TCS', 'above', 2200, 2210.5)])
  check('one hit: same title as before', n?.title === 'SuryaDhana alert', n)
  check('one hit: same body as before', n?.body === `TCS rose above ₹${(2200).toLocaleString('en-IN')} (now ₹${(2210.5).toLocaleString('en-IN')})`, n)
  check('below wording', A.hitText(hit('INFY', 'below', 1400, 1395)).startsWith('INFY fell below ₹'))
  check('no hits -> no notification', A.alertNotification([]) === null)
}

// ── a gap-down open: 25 hits in one check -> ONE notification with a count ─────────────────────
{
  const many = Array.from({ length: 25 }, (_, i) => hit(`SYM${i}`, 'below', 1000 + i, 990 + i))
  const n = A.alertNotification(many)
  check('25 hits -> one notification', !!n)
  check('count in the title', n?.title === 'SuryaDhana · 25 price alerts', n?.title)
  const lines = n?.body.split('\n') ?? []
  check('first five listed by name', lines.slice(0, 5).every((l, i) => l.startsWith(`SYM${i} fell below`)), lines)
  check('the rest counted', lines[5] === '+20 more · open WTCH for the full list', lines[5])
  check('within the shell limits (title ≤ 120, body ≤ 1000)', (n?.title.length ?? 999) <= A.NOTIFY_TITLE_MAX && (n?.body.length ?? 9999) <= A.NOTIFY_BODY_MAX)
  const two = A.alertNotification([hit('A', 'above', 1, 2), hit('B', 'below', 3, 2)])
  check('two hits: both listed, no "more" line', two?.title === 'SuryaDhana · 2 price alerts' && two?.body.split('\n').length === 2, two)
  const long = A.alertNotification(Array.from({ length: 6 }, () => hit('X'.repeat(500), 'above', 1, 2)))
  check('pathological symbols still fit the body limit', (long?.body.length ?? 9999) <= A.NOTIFY_BODY_MAX && (long?.title.length ?? 999) <= A.NOTIFY_TITLE_MAX)
}

// ── first visit: existing history is not news ───────────────────────────────────────────────────
{
  check('marker kept when present', A.initialSeen('2026-10-20T10:00:00+00:00', '2026-10-25T10:00:00+00:00') === '2026-10-20T10:00:00+00:00')
  check('no marker -> newest item', A.initialSeen(null, '2026-10-25T10:00:00+00:00') === '2026-10-25T10:00:00+00:00')
  check('no marker, empty history -> "nothing seen" (the first real hit is still fresh)', A.initialSeen('', undefined) === A.SEEN_NOTHING
    && '2026-10-25T10:00:00+00:00' > A.SEEN_NOTHING && '2026-10-23T21:00:07+05:30' > A.SEEN_NOTHING)
}

// ── call sites (source guards: they fail on the pre-fix code) ───────────────────────────────────
{
  const src = (rel: string) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8')
  const watch = src('../../components/WatchMonitor.tsx')
  check('WatchMonitor sends one notification per check', /notifyHits\(hits\)/.test(watch) && !/notify\(h\)/.test(watch))
  const alerts = src('../alerts.ts')
  check('alerts.check(): no marker -> adopt newest, return nothing', /if \(!seen\) \{ ensureSeen\(d\.history\); return \[\] \}/.test(alerts))
  check('AlertsBell: first visit marks the feed read', /initialSeen\(/.test(src('../../components/AlertsBell.tsx')))
  check('NewsDock: first visit marks the latest scan seen', /first visit: what exists now is not news/.test(src('../../components/news/NewsDock.tsx')))
}

// ── P11 (round 4b): MOVE hits say what moved; a failed save is shown ───────────────────────────────────────────
{
  const mv = A.hitText({ sym: 'TCS', side: 'move', level: 5, price: 3120, change_pct: -6.12 })
  check('move hit: "moved −6.1 % (≥ 5 %)" (true minus), not "fell below ₹5"', mv === `TCS moved −6.1 % (≥ 5 %) (now ₹${(3120).toLocaleString('en-IN')})`, mv)
  check('move hit up: "+7.0 %"', A.hitText({ sym: 'INFY', side: 'move', level: 5, price: 1500, change_pct: 7 }).startsWith('INFY moved +7.0 % (≥ 5 %)'))
  check('move hit without change_pct still names the threshold', A.hitText({ sym: 'X', side: 'move', level: 2.5, price: 10 }).startsWith('X moved (≥ 2.5 %)'))
  const old = (h: { sym: string; side: string; level: number; price: number }) =>
    `${h.sym} ${h.side === 'above' ? 'rose above' : 'fell below'} ₹${h.level.toLocaleString('en-IN')} (now ₹${h.price.toLocaleString('en-IN')})`
  check('negative control: the old wording said "fell below ₹5" for a move hit', old({ sym: 'TCS', side: 'move', level: 5, price: 3120 }).includes('fell below ₹5') && !mv.includes('fell below'))
  check('price levels keep their exact wording', A.hitText(hit('TCS', 'above', 2200, 2210.5)) === old(hit('TCS', 'above', 2200, 2210.5)))
  const n = A.alertNotification([{ sym: 'TCS', side: 'move', level: 5, price: 3120, change_pct: -6.12 }])
  check('the notification uses the move wording too', !!n && n.body.startsWith('TCS moved −6.1 %'), n)
  const t = A.alertSaveFailedText({ sym: 'TCS', error: 'Network Error' })
  check('save failure text names the stock, the reason and the consequence', t === 'Alert for TCS NOT saved: Network Error. Nothing will fire until it is saved.', t)
  check('save failure text: blank reason and multi-line reason are readable', A.alertSaveFailedText({ sym: 'X', error: '' }).includes('ui-api did not answer')
    && !A.alertSaveFailedText({ sym: 'X', error: 'a\n\nb' }).includes('\n'))
  const src = (rel: string) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8')
  const alerts = src('../alerts.ts')
  check('alerts.ts: both setters report a failed save (no silent catch left)', (alerts.match(/reportSaveFailure\(sym, e\)/g) ?? []).length === 2
    && !/catch \{ \/\* surfaced by the next sync \*\/ \}/.test(alerts))
  check('alerts.ts: the event carries apiError text', /ALERT_SAVE_FAILED_EVENT, \{ detail: \{ sym, error: apiError\(e, /.test(alerts))
  check('alerts.ts: a new useAlerts() starts from the last levels read (re-opened form is prefilled)',
    /useState<Record<string, AlertLevels>>\(\(\) => lastAlerts\)/.test(alerts) && (alerts.match(/remember\(d\)/g) ?? []).length >= 4)
  const page = src('../../app/page.tsx')
  check('the toasts are mounted INSIDE ToastProvider (useToast would throw outside it)',
    // terminal v2 PLAN 0.6: the unknown-?tab= toast sits beside them, inside the provider too
    /<ToastProvider>\s*<ErrorCatcher \/>\s*\{[^}]*\}\s*<DownloadToasts \/>\s*<AlertSaveToasts \/>\s*(?:<UnknownTabToast tabs=\{TAB_IDS\} \/>\s*)?<HomeContent \/>\s*<\/ToastProvider>/.test(page))
  const toasts = src('../../components/shell/ShellToasts.tsx')
  check('AlertSaveToasts listens to the save-failed event', /addEventListener\(ALERT_SAVE_FAILED_EVENT, on\)/.test(toasts) && /alertSaveFailedText\(d\)/.test(toasts))
}

if (failed) {
  console.error(`alerts.check: ${failed} failed, ${passed} passed`)
  process.exit(1)
}
console.log(`alerts.check: all ${passed} checks pass`)
