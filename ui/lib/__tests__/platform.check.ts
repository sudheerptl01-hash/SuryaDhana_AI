/**
 * Platform bridge checks (desktop program D3): URL classification for the link interceptor,
 * click decisions, Blob -> base64, filename sanitizing, and the bridge in BOTH modes — the browser
 * fallbacks (today's behavior) and the desktop path against a fake window.__TAURI_INTERNALS__.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/lib/__tests__/platform.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. The DOM click path is exercised for real in
 * WebKit/Chromium by the D3 Playwright E2E. Exits non-zero on any failing check.
 */
import * as nodeModule from 'node:module'

;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
    try {
      return next(spec, ctx)
    } catch (e) {
      if (/^(\.|\/|file:)/.test(spec) && !/\.[cm]?[jt]sx?$/.test(spec)) return next(`${spec}.ts`, ctx)
      throw e
    }
  },
})

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

// ── a minimal browser-like global environment (installed BEFORE the bridge is imported) ─────────
type AnyRec = Record<string, unknown>
const PAGE = 'http://127.0.0.1:8010/?tab=brief'
const opened: unknown[][] = []
const clicks: Array<{ href: string; download: string }> = []
const win = new EventTarget() as EventTarget & AnyRec
win.location = { href: PAGE, origin: 'http://127.0.0.1:8010' }
win.open = (...args: unknown[]) => {
  opened.push(args)
  return null
}
const doc = new EventTarget() as EventTarget & AnyRec
doc.visibilityState = 'visible'
doc.body = { appendChild: () => {} }
doc.createElement = (tag: string) => {
  const a: AnyRec = { tag, href: '', download: '', remove: () => {} }
  a.click = () => clicks.push({ href: String(a.href), download: String(a.download) })
  return a
}
const g = globalThis as unknown as AnyRec
g.window = win
g.document = doc
const warnings: string[] = []
const origWarn = console.warn
console.warn = (...a: unknown[]) => {
  warnings.push(a.map(String).join(' '))
}

const links = await import('../platform/links')
const enc = await import('../platform/encoding')
const inv = await import('../platform/invoke')
const P = await import('../platform/index')

// ── 1. URL classification ──────────────────────────────────────────────────────────────────────
{
  const c = (href: string, o?: { hasDownloadAttr?: boolean; downloadName?: string | null }) => links.classifyHref(href, PAGE, o)
  check('external https', c('https://www.tradingview.com/chart/?symbol=NSE:TCS').kind === 'external')
  check('protocol-relative is external', c('//finance.yahoo.com/quote/TCS.NS').kind === 'external')
  const login = c('https://api.icicidirect.com/apiuser/login?api_key=SECRET')
  check('broker login url is external (opened, never logged)', login.kind === 'external')
  const t = c('/?tab=desk')
  check('same-origin tab link', t.kind === 'tab' && t.tab === 'desk', t)
  const rel = c('?tab=watch')
  check('relative ?tab= link', rel.kind === 'tab' && rel.tab === 'watch', rel)
  const badTab = c('/?tab=../../etc')
  check('invalid tab id dropped', badTab.kind === 'tab' && badTab.tab === null, badTab)
  const root = c('/')
  check('root link -> tab null', root.kind === 'tab' && root.tab === null)
  const f = c('/api/research/file?id=reports%2Fx&name=report.md')
  check('api file -> download with name param', f.kind === 'download' && f.filename === 'report.md', f)
  const f2 = c('/api/x/y%20z.csv')
  check('api path -> download with decoded basename', f2.kind === 'download' && f2.filename === 'y z.csv', f2)
  const f3 = c('/api/research/file?id=a&name=b.csv', { hasDownloadAttr: true, downloadName: 'chosen.csv' })
  check('download attribute name wins', f3.kind === 'download' && f3.filename === 'chosen.csv', f3)
  for (const u of ['http://localhost:3000/', 'http://127.0.0.1:8001/health', 'http://[::1]:3000/', 'http://foo.localhost/', 'http://127.1.2.3/'])
    check(`loopback other port blocked: ${u}`, c(u).kind === 'blocked', c(u))
  check('same origin absolute', c('http://127.0.0.1:8010/?tab=memb').kind === 'tab')
  for (const u of ['mailto:a@b.c', 'javascript:alert(1)', '#top', '', 'data:text/html,hi', 'file:///etc/passwd', 'tel:123', 'about:blank'])
    check(`ignored: ${u || '(empty)'}`, c(u).kind === 'ignore', c(u))
  check('blob without download attr ignored', c('blob:http://127.0.0.1:8010/1234').kind === 'ignore')
  const b = c('blob:http://127.0.0.1:8010/1234', { hasDownloadAttr: true, downloadName: 'x.csv' })
  check('blob with download attr -> download', b.kind === 'download' && b.filename === 'x.csv', b)
  check('over-long external url blocked', c(`https://example.com/${'a'.repeat(2100)}`).kind === 'blocked')
  check('null href ignored', links.classifyHref(null, PAGE).kind === 'ignore')
  // K4: a terminal link with a stock (?sym=) carries it, validated with the shell's rule
  const sy = c('/?tab=charts&sym=tcs')
  check('K4 same-origin tab + sym link', sy.kind === 'tab' && sy.tab === 'charts' && sy.sym === 'TCS', sy)
  const amp = c('/?tab=desk&sym=M%26M')
  check('K4 M&M survives encoding', amp.kind === 'tab' && amp.sym === 'M&M', amp)
  const badSym = c('/?tab=desk&sym=%3Cscript%3E')
  check('K4 invalid sym dropped', badSym.kind === 'tab' && badSym.tab === 'desk' && !('sym' in badSym), badSym)
  check('K4 terminalPath', P.terminalPath('desk', 'TCS') === '/?tab=desk&sym=TCS' && P.terminalPath('desk') === '/?tab=desk'
    && P.terminalPath() === '/' && P.terminalPath('Bad Tab', 'bad sym') === '/' && P.terminalPath(undefined, 'TCS') === '/?sym=TCS',
    [P.terminalPath('desk', 'TCS'), P.terminalPath(undefined, 'TCS')])
}

// ── 2. click decisions ─────────────────────────────────────────────────────────────────────────
{
  const base = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false, defaultPrevented: false, target: null as string | null, hasDownloadAttr: false, downloadName: null as string | null }
  const d = (o: Partial<typeof base> & { href: string }) => links.decideClick({ ...base, ...o }, PAGE)
  check('_blank external -> external', d({ href: 'https://x.com/', target: '_blank' })?.kind === 'external')
  check('plain external (no target) -> external (never navigate away)', d({ href: 'https://x.com/' })?.kind === 'external')
  check('plain internal click stays in-app', d({ href: '/?tab=desk' }) === null)
  check('_blank internal -> new window', d({ href: '/?tab=desk', target: '_blank' })?.kind === 'tab')
  check('cmd-click internal -> new window', d({ href: '/?tab=desk', metaKey: true })?.kind === 'tab')
  check('middle-click internal -> new window', d({ href: '/?tab=desk', button: 1 })?.kind === 'tab')
  check('shift-click internal -> new window', d({ href: '/?tab=desk', shiftKey: true })?.kind === 'tab')
  check('right-click ignored', d({ href: 'https://x.com/', button: 2 }) === null)
  check('alt-click ignored', d({ href: 'https://x.com/', altKey: true }) === null)
  check('defaultPrevented respected', d({ href: 'https://x.com/', defaultPrevented: true }) === null)
  check('<a download> same-origin -> download', d({ href: '/api/research/file?id=a&name=b.csv', hasDownloadAttr: true, downloadName: 'b.csv' })?.kind === 'download')
  check('loopback link is blocked (prevented, not opened)', d({ href: 'http://localhost:3000/', target: '_blank' })?.kind === 'blocked')
  check('hash link ignored', d({ href: '#x', target: '_blank' }) === null)
}

// ── 3. base64 + filenames ──────────────────────────────────────────────────────────────────────
{
  const b64 = (s: string) => enc.bytesToBase64(new TextEncoder().encode(s))
  check('base64 empty', b64('') === '')
  check('base64 padding', b64('f') === 'Zg==' && b64('fo') === 'Zm8=' && b64('foo') === 'Zm9v')
  check('base64 rfc vector', b64('foobar') === 'Zm9vYmFy')
  const all = new Uint8Array(256).map((_, i) => i)
  check('base64 all byte values', enc.bytesToBase64(all) === Buffer.from(all).toString('base64'))
  const big = new Uint8Array(0x8000 * 3 + 17)
  for (let i = 0; i < big.length; i++) big[i] = (i * 7919) & 0xff
  check('base64 across chunk boundaries', enc.bytesToBase64(big) === Buffer.from(big).toString('base64'))
  const text = 'sym,₹ price\nटाटा,🚀\n'
  const fromBlob = await enc.blobToBase64(enc.toBlob(text, 'text/csv'))
  check('blob text is UTF-8 encoded', Buffer.from(fromBlob, 'base64').toString('utf8') === text)
  check('toBlob default mime', enc.toBlob('x').type === 'text/plain;charset=utf-8')
  check('toBlob keeps a Blob', enc.toBlob(new Blob(['y'], { type: 'a/b' })).type === 'a/b')
  const s = enc.sanitizeFilename
  check('filename kept', s('backtest-2026-10-24-11-10-00.csv') === 'backtest-2026-10-24-11-10-00.csv')
  check('filename path stripped', s('../../etc/passwd') === 'passwd' && s('a/b\\c.csv') === 'c.csv')
  check('filename charset', s('ünï€ode.csv') === '_n_ode.csv', s('ünï€ode.csv'))
  check('filename leading dots', s('.hidden') === 'hidden')
  check('filename fallback', s('') === 'download' && s('...') === 'download')
  const long = s(`${'x'.repeat(200)}.csv`)
  check('filename length cap keeps extension', long.length === 120 && long.endsWith('.csv'), long.length)
}

// ── 4. browser mode: today's behavior ──────────────────────────────────────────────────────────
{
  check('browser: not desktop', P.isDesktop() === false && inv.shellMarker() === null)
  check('browser: shellInfo/status null', (await P.shellInfo()) === null && (await P.shellStatus()) === null)
  P.openExternal('https://www.tradingview.com/x')
  check('browser: openExternal = window.open(url, _blank, noopener)', JSON.stringify(opened.pop()) === JSON.stringify(['https://www.tradingview.com/x', '_blank', 'noopener']))
  await P.newWindow('desk')
  check('browser: newWindow = window.open(/?tab=id)', JSON.stringify(opened.pop()) === JSON.stringify(['/?tab=desk', '_blank']))
  await P.newWindow('Bad Tab!')
  check('browser: invalid tab -> /', JSON.stringify(opened.pop()) === JSON.stringify(['/', '_blank']))
  await P.newWindow('charts', 'TCS')
  check('browser K4: newWindow(tab, sym) = window.open(/?tab=id&sym=SYM)', JSON.stringify(opened.pop()) === JSON.stringify(['/?tab=charts&sym=TCS', '_blank']))
  await P.newWindow('charts', 'not a ticker!')
  check('browser K4: an invalid sym is dropped, never sent', JSON.stringify(opened.pop()) === JSON.stringify(['/?tab=charts', '_blank']))
  P.notify('t', 'b') // no Notification API in node: must not throw
  const shown: unknown[][] = []
  const FakeNotification = function (this: unknown, title: string, opts: unknown) {
    shown.push([title, opts])
  } as unknown as { permission: string }
  FakeNotification.permission = 'denied'
  g.Notification = FakeNotification
  P.notify('SuryaDhana alert', 'TCS rose above ₹2,200')
  check('browser: no notification without permission', shown.length === 0)
  FakeNotification.permission = 'granted'
  P.notify('SuryaDhana alert', 'TCS rose above ₹2,200')
  check('browser: Notification(title, {body}) when granted', JSON.stringify(shown[0]) === JSON.stringify(['SuryaDhana alert', { body: 'TCS rose above ₹2,200' }]))
  check('browser: permission passthrough', (await P.notificationPermission()) === 'granted')
  delete g.Notification
  check('browser: unsupported without the API', (await P.notificationPermission()) === 'unsupported' && (await P.requestNotificationPermission()) === 'unsupported')
  const r = await P.saveDownload('a,b\n1,2', 'export.csv', 'text/csv;charset=utf-8;')
  const last = clicks.pop()
  check('browser: saveDownload clicks an object-URL anchor with the filename', r === null && !!last && last.download === 'export.csv' && last.href.startsWith('blob:'), last)
  await P.downloadUrl('/api/research/file?id=a&name=b.csv', 'b.csv')
  const l2 = clicks.pop()
  check('browser: downloadUrl clicks <a href download>', !!l2 && l2.href === '/api/research/file?id=a&name=b.csv' && l2.download === 'b.csv', l2)
  P.setWindowTitle('DESK') // browser: no-op, must not touch document.title
  check('browser: setWindowTitle leaves document.title alone', (doc as AnyRec).title === undefined)
  check('browser: interceptor not installed', typeof P.installLinkInterceptor() === 'function' && win.open !== undefined && opened.length === 0)
}

// ── 5. desktop mode against a fake __TAURI_INTERNALS__ ─────────────────────────────────────────
{
  const calls: Array<[string, AnyRec]> = []
  const replies: AnyRec = {
    shell_info: { version: '0.1.0', build: 'abc1234', autostart: true, windows: 1, ui_api_url: 'http://127.0.0.1:8010' },
    shell_status: { at: '2026-10-24T05:40:00Z', ui_api: { up: true, latency_ms: 3 }, data_service: { up: true, latency_ms: 5 }, master_controller: { up: false, latency_ms: null }, icici: 'unknown', ui_build: 'r1', nifty: null },
    shell_notification_permission: 'granted',
    shell_request_notification_permission: 'granted',
    shell_save_download: { path: '/Users/x/Downloads/export.csv' },
    shell_new_window: { label: 'term-2' },
  }
  let mode: 'ok' | 'reject' | 'hang' = 'ok'
  win.__TAURI_INTERNALS__ = {
    invoke: (cmd: string, args: AnyRec) => {
      calls.push([cmd, args])
      if (mode === 'reject') return Promise.reject({ message: 'denied by shell' })
      if (mode === 'hang') return new Promise(() => {})
      return Promise.resolve(cmd in replies ? replies[cmd] : null)
    },
  }
  check('marker missing -> still not desktop', P.isDesktop() === false)
  win.__SURYADHANA_SHELL__ = Object.freeze({ api: 2, version: '9', build: 'x', platform: 'macos' })
  check('wrong api version -> not desktop', P.isDesktop() === false)
  win.__SURYADHANA_SHELL__ = Object.freeze({ api: 1, version: '0.1.0', build: 'abc1234', platform: 'macos' })
  check('desktop detected', P.isDesktop() === true && inv.shellMarker()?.build === 'abc1234')
  // K5 (round 3, re-verified 4b): an older app has no `features`; the round-3 app announces 'notification_feed', and
  // WatchMonitor then leaves the price-alert banner to the shell's feed (one native banner, not two)
  check('K5: an older marker has no features (WatchMonitor keeps its own banner)', inv.shellMarker()?.features?.includes('notification_feed') !== true)
  win.__SURYADHANA_SHELL__ = Object.freeze({ api: 1, version: '0.1.0', build: 'abc1234', platform: 'macos', features: Object.freeze(['notification_feed']) })
  check('K5: the features list reaches shellMarker() unchanged', inv.shellMarker()?.features?.includes('notification_feed') === true && P.isDesktop() === true)
  {
    const wm = (await import('node:fs')).readFileSync(new URL('../../components/WatchMonitor.tsx', import.meta.url), 'utf8')
    check('K5: WatchMonitor posts its own banner only without the shell feed (single native path)',
      /if \(!shellMarker\(\)\?\.features\?\.includes\('notification_feed'\)\) notifyHits\(hits\)/.test(wm) && (wm.match(/notifyHits\(/g) ?? []).length === 1)
  }
  win.__SURYADHANA_SHELL__ = Object.freeze({ api: 1, version: '0.1.0', build: 'abc1234', platform: 'macos' })

  const info = await P.shellInfo()
  check('shellInfo via invoke', info?.version === '0.1.0' && calls.pop()?.[0] === 'shell_info')
  const st = await P.shellStatus()
  check('shellStatus via invoke', st?.ui_api.up === true && st.master_controller.latency_ms === null)

  P.notify('T'.repeat(200), 'B'.repeat(2000))
  await Promise.resolve()
  const n = calls.pop()!
  check('notify -> shell_notify with clipped title/body', n[0] === 'shell_notify' && String(n[1].title).length === 120 && String(n[1].body).length === 1000, [n[0], String(n[1].title).length, String(n[1].body).length])
  check('permission via shell', (await P.notificationPermission()) === 'granted' && (await P.requestNotificationPermission()) === 'granted')

  const events: AnyRec[] = []
  win.addEventListener(P.DOWNLOAD_EVENT, (e) => events.push((e as CustomEvent).detail))
  const path = await P.saveDownload('a,b\n1,₹2', 'my report?.csv', 'text/csv')
  const sv = calls.pop()!
  check('saveDownload -> shell_save_download', sv[0] === 'shell_save_download' && sv[1].filename === 'my report_.csv', sv)
  check('saveDownload base64 decodes to the UTF-8 payload', Buffer.from(String(sv[1].base64), 'base64').toString('utf8') === 'a,b\n1,₹2')
  check('saveDownload returns the path + emits ok event', path === '/Users/x/Downloads/export.csv' && events.pop()?.ok === true)
  check('desktop saveDownload never uses an anchor', clicks.length === 0)

  const bytes = new Uint8Array(1000).map((_, i) => (i * 31) & 0xff)
  await P.saveDownload(new Blob([bytes]), 'bin.xlsx')
  const sv2 = calls.pop()!
  check('binary blob round-trips', Buffer.compare(Buffer.from(String(sv2[1].base64), 'base64'), Buffer.from(bytes)) === 0)

  const before = calls.length
  const huge = await P.saveDownload(new Blob([new Uint8Array(enc.MAX_DOWNLOAD_BYTES + 1)]), 'huge.bin')
  check('over 50 MB refused before invoking', huge === null && calls.length === before && events.pop()?.ok === false)

  mode = 'reject'
  const failedSave = await P.saveDownload('x', 'x.csv')
  check('shell rejection -> null, never rejects, error event', failedSave === null && events.pop()?.ok === false)
  check('rejection degrades shellStatus to null', (await P.shellStatus()) === null)
  mode = 'ok'

  g.fetch = async (u: string) => {
    calls.push(['fetch', { u }])
    return new Response('file-body', { status: 200, headers: { 'content-type': 'text/markdown' } })
  }
  const dl = await P.downloadUrl('/api/research/file?id=a&name=b.md', 'b.md')
  const fetchCall = calls[calls.length - 2]
  const saveCall = calls[calls.length - 1]
  check('downloadUrl fetches same-origin then saves', fetchCall?.[0] === 'fetch' && String(fetchCall[1].u).startsWith('http://127.0.0.1:8010/api/research/file') && saveCall?.[0] === 'shell_save_download' && Buffer.from(String(saveCall[1].base64), 'base64').toString() === 'file-body' && dl !== null)
  const n2 = calls.length
  const cross = await P.downloadUrl('https://evil.example/x.csv', 'x.csv')
  check('downloadUrl refuses cross-origin in desktop', cross === null && calls.length === n2)
  g.fetch = async () => new Response('nope', { status: 500 })
  check('downloadUrl HTTP error -> null', (await P.downloadUrl('/api/x.csv', 'x.csv')) === null)

  P.openExternal('https://www.nseindia.com/x')
  await Promise.resolve()
  const oe = calls.pop()!
  check('openExternal -> shell_open_external', oe[0] === 'shell_open_external' && oe[1].url === 'https://www.nseindia.com/x')
  check('openExternal never calls window.open in desktop', opened.length === 0)
  const label = await P.newWindow('watch')
  const nw = calls.pop()!
  check('newWindow -> shell_new_window {tab}', nw[0] === 'shell_new_window' && nw[1].tab === 'watch' && label === 'term-2', nw)
  await P.newWindow('../evil')
  check('newWindow drops an invalid tab', JSON.stringify(calls.pop()?.[1]) === '{}')
  await P.newWindow('charts', 'TCS')
  const nws = calls.pop()!
  check('K4 newWindow -> shell_new_window {tab, sym}', nws[0] === 'shell_new_window' && JSON.stringify(nws[1]) === '{"tab":"charts","sym":"TCS"}', nws)
  await P.newWindow('charts', 'tcs; rm -rf')
  check('K4 desktop: invalid sym never reaches the shell', JSON.stringify(calls.pop()?.[1]) === '{"tab":"charts"}')
  P.setWindowTitle('DESK\u0007 · Decision\nDesk')
  await Promise.resolve()
  const tt = calls.pop()!
  check('setWindowTitle strips control chars', tt[0] === 'shell_set_title' && tt[1].title === 'DESK  · Decision Desk', tt)

  mode = 'hang'
  let kind = ''
  try {
    await inv.invokeShell('shell_status', undefined, 30)
  } catch (e) {
    kind = e instanceof inv.ShellError ? e.kind : 'other'
  }
  check('invoke timeout -> ShellError(timeout)', kind === 'timeout', kind)
  mode = 'reject'
  let msg = ''
  try {
    await inv.invokeShell('shell_info')
  } catch (e) {
    msg = e instanceof inv.ShellError ? `${e.kind}:${e.message}` : 'other'
  }
  check('invoke rejection normalized', msg === 'rejected:denied by shell', msg)
  mode = 'ok'
  check('rejectionMessage variants', inv.rejectionMessage('s') === 's' && inv.rejectionMessage({ error: 'e' }) === 'e' && inv.rejectionMessage(undefined) === 'shell command failed')

  // shell -> UI events
  const got: unknown[] = []
  const un = P.onShellEvent((e) => {
    got.push(e)
    if (e.type === 'command-bar') throw new Error('handler bug')
  })
  const fire = (detail: unknown) => win.dispatchEvent(new CustomEvent(P.SHELL_EVENT, { detail }))
  fire({ type: 'goto', tab: 'desk' })
  fire({ type: 'goto', tab: 'Bad Tab' })
  fire({ type: 'nope' })
  fire(null)
  fire({ type: 'status', status: replies.shell_status })
  fire({ type: 'build-changed', build: 'r2' })
  fire({ type: 'command-bar' })
  fire({ type: 'zoom', factor: 1.25 })                 // K3
  fire({ type: 'zoom', factor: 'big' })
  fire({ type: 'zoom', factor: Number.NaN })
  fire({ type: 'zoom', factor: 0 })
  un()
  fire({ type: 'goto', tab: 'watch' })
  check('onShellEvent delivers only valid events, survives handler errors, unsubscribes', got.length === 5 && (got[0] as AnyRec).tab === 'desk', got)
  check('K3 zoom event delivered with its factor; malformed ones dropped', (got[4] as AnyRec).type === 'zoom' && (got[4] as AnyRec).factor === 1.25, got[4])

  // window.open override (desktop link interceptor)
  g.Element = class {}
  const uninstall = P.installLinkInterceptor()
  check('interceptor install is idempotent', P.installLinkInterceptor() === uninstall)
  ;(win.open as (u: string) => unknown)('https://in.tradingview.com/chart/?symbol=NSE:TCS')
  await Promise.resolve()
  check('window.open external -> shell_open_external', calls.pop()?.[0] === 'shell_open_external')
  ;(win.open as (u: string) => unknown)('/?tab=desk')
  await Promise.resolve()
  const nw2 = calls.pop()!
  check('window.open same-origin -> shell_new_window', nw2[0] === 'shell_new_window' && nw2[1].tab === 'desk', nw2)
  const n3 = calls.length
  ;(win.open as (u: string) => unknown)('http://localhost:3000/')
  check('window.open loopback blocked', calls.length === n3 && opened.length === 0)
  ;(win.open as (u: string) => unknown)('about:blank')
  check('window.open ignore-class falls through to the original', opened.length === 1 && (opened.pop() as unknown[])[0] === 'about:blank')
  uninstall()
  ;(win.open as (u: string) => unknown)('https://x.example/')
  check('uninstall restores window.open', (opened.pop() as unknown[] | undefined)?.[0] === 'https://x.example/')

  // bootstrap: idempotent, never rejects, bounded (no localStorage in node -> prefs skipped)
  const t0 = Date.now()
  const p1 = P.bootstrapPlatform({ hydrateTimeoutMs: 200 })
  const p2 = P.bootstrapPlatform()
  check('bootstrapPlatform is idempotent', p1 === p2)
  await p1
  check('bootstrapPlatform resolves within the bound', Date.now() - t0 < 600, Date.now() - t0)
}

// ── third-party frames are sandboxed (C2-security-05 item 4) ───────────────────────────────────
/**
 * Every JSX opening tag `<name …>` / `<name … />` in `src`, whole: braces, quotes and template literals are
 * tracked, so `=>` inside an attribute expression does not end the tag (round-1 leftover: the old regex only
 * matched self-closing iframes, so `<iframe …></iframe>` without a sandbox passed).
 */
function openingTags(src: string, name: string): string[] {
  const out: string[] = []
  const re = new RegExp(`<${name}\\b`, 'g')
  for (let m = re.exec(src); m; m = re.exec(src)) {
    let depth = 0
    let quote: string | null = null
    let i = m.index + m[0].length
    for (; i < src.length; i++) {
      const ch = src[i]
      if (quote) { if (ch === '\\') i++; else if (ch === quote) quote = null; continue }
      if (ch === '"' || ch === "'" || ch === '`') { quote = ch; continue }
      if (ch === '{') depth++
      else if (ch === '}') depth--
      else if (ch === '>' && depth === 0) break
    }
    out.push(src.slice(m.index, i + 1))
  }
  return out
}
{
  // negative controls for the scanner itself
  const sample = `<iframe src="a"></iframe> <iframe onLoad={() => go(1)} sandbox="allow-scripts" src="b" /> <iframe title='x>y' src="c">`
  const tags = openingTags(sample, 'iframe')
  check('iframe scanner finds non-self-closing tags', tags.length === 3, tags)
  check('iframe scanner: a plain <iframe …></iframe> without sandbox is caught', !/\bsandbox=/.test(tags[0]), tags[0])
  check('iframe scanner: `=>` inside an attribute does not end the tag', /\bsandbox=/.test(tags[1]) && tags[1].endsWith('/>'), tags[1])
  check('iframe scanner: `>` inside a quoted attribute does not end the tag', tags[2].includes('src="c"'), tags[2])
}
{
  const fs = await import('node:fs')
  const path = await import('node:path')
  const uiRoot = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..')
  const frames: string[] = []
  const walk = (dir: string) => {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      if (e.name === 'node_modules' || e.name.startsWith('.') || e.name === '__tests__') continue
      const p = path.join(dir, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.tsx$/.test(e.name)) {
        for (const tag of openingTags(fs.readFileSync(p, 'utf8'), 'iframe')) frames.push(`${path.relative(uiRoot, p)}: ${tag}`)
      }
    }
  }
  for (const d of ['app', 'components']) walk(path.join(uiRoot, d))
  check('every <iframe> in the UI has a sandbox', frames.length > 0 && frames.every((f) => /\bsandbox=/.test(f)), frames)
  const chart = fs.readFileSync(path.join(uiRoot, 'components/news/NewsChart.tsx'), 'utf8')
  const tv = /TRADINGVIEW_SANDBOX = '([^']*)'/.exec(chart)?.[1] ?? ''
  const tokens = tv.split(/\s+/).filter(Boolean).sort()
  check('TradingView sandbox = exactly the reviewed tokens',
    tokens.join(' ') === 'allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts', tokens)
  check('TradingView frame can neither download nor navigate the top window', !/allow-downloads|allow-top-navigation/.test(tv))
}

console.warn = origWarn
check('no warning ever contains a URL or payload', warnings.every((w) => !/https?:\/\/|SECRET|file-body|₹/.test(w)), warnings)

if (failed) {
  console.error(`platform.check: ${failed} failed, ${passed} passed`)
  process.exit(1)
}
console.log(`platform.check: all ${passed} checks pass`)
