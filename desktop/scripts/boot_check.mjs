// Boot-page state checks: runs desktop/boot/boot.js in a vm with a minimal DOM and a fake shell IPC, feeds
// it BootStatus payloads (the Rust struct in src-tauri/src/commands.rs) and asserts what the owner sees.
//
//   node desktop/scripts/boot_check.mjs        (exit 0 = all checks passed; no npm dependencies)
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(here, '..', 'boot', 'boot.js'), 'utf8');
const HTML = readFileSync(join(here, '..', 'boot', 'index.html'), 'utf8');

let failures = 0;
let passes = 0;
function check(name, cond, detail = '') {
  if (cond) passes++;
  else {
    failures++;
    console.log(`FAIL ${name}${detail ? ': ' + detail : ''}`);
  }
}

// ---- a minimal DOM built from the ids / data-svc rows in index.html ----
function makeEl(id) {
  const listeners = {};
  const el = {
    id, textContent: '', hidden: /id="(actions|open-now|message|remedy|btn-stop|freeze|notif)"/.test(`id="${id}"`) ? true : false,
    className: '', disabled: false, dataset: {}, focused: 0,
    classList: { contains: (c) => (' ' + el.className + ' ').includes(' ' + c + ' ') },
    addEventListener: (ev, fn) => { (listeners[ev] ||= []).push(fn); },
    click() { (listeners.click || []).forEach((f) => f.call(el, { target: el })); },
    focus() { el.focused++; },
    querySelector: (sel) => el.children[sel],
    children: {},
  };
  return el;
}
function makeDocument() {
  const ids = [...HTML.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
  const byId = Object.fromEntries(ids.map((i) => [i, makeEl(i)]));
  for (const cls of ['copy']) for (const i of ['ui', 'progress', 'message', 'remedy']) if (byId[i]) byId[i].className = cls;
  const rows = {};
  for (const m of HTML.matchAll(/data-svc="([^"]+)"/g)) {
    const r = makeEl('row-' + m[1]);
    r.children = { '.p': makeEl('p'), '.s': makeEl('s'), '.l': makeEl('l') };
    rows[m[1]] = r;
  }
  const docListeners = {};
  return {
    byId,
    rows,
    body: { dataset: { state: 'checking' } },
    getElementById: (id) => byId[id] || null,
    querySelector: (sel) => {
      const m = /\[data-svc="([^"]+)"\]/.exec(sel);
      return m ? rows[m[1]] || null : null;
    },
    addEventListener: (ev, fn) => { (docListeners[ev] ||= []).push(fn); },
  };
}

// ---- BootStatus fixtures ----
const svc = (name, port, up) => ({ name, port, role: '', up, latency_ms: up ? 2 : null });
function status(over = {}) {
  return {
    version: '1.0.0', build: 'abc1234', label: 'main', mode: 'boot', phase: 'boot',
    target_tab: 'brief', target_code: 'BRF', ui_url: 'http://127.0.0.1:8010',
    services: [svc('data-service', 8001, false), svc('ui-api', 8010, false), svc('master-controller', 8008, false)],
    icici: 'unknown', ui_build: null, ui_ready: false, ui_state: 'api_down', ui_detail: 'ui-api /health not answering',
    nifty: null, nifty_state: 'none', desk: null, down_secs: 40, polls: 12, freeze: null, ist: '10:58:10',
    repo_ok: true, selftest: false, starting: null,
    stack: { watchdog_loaded: true, watchdog_installed: true, watchdog_running: false, paused: [], preflight_failed: false },
    repo: '/Users/x/SuryaDhana_AI',
    ...over,
  };
}

async function run(s) {
  const document = makeDocument();
  const calls = [];
  let current = s;
  const winListeners = {};
  const window = {
    __TAURI_INTERNALS__: {
      invoke: (cmd, args) => {
        calls.push([cmd, args]);
        if (cmd === 'boot_status') return Promise.resolve(current);
        if (cmd === 'stack_start') return Promise.resolve('Asked the watchdog to start every stopped core service now (usually 1–4 min).');
        return Promise.resolve(null);
      },
    },
    __SURYADHANA_SHELL__: { api: 1, version: '1.0.0', build: 'abc1234', platform: 'macos' },
    addEventListener: (ev, fn) => { (winListeners[ev] ||= []).push(fn); },
  };
  const intervals = [];
  const ctx = {
    window, document, Intl, Promise, String, Math, console,
    performance: { now: () => 1, timeOrigin: 1 },
    requestAnimationFrame: () => 0,
    setInterval: (fn) => { intervals.push(fn); return intervals.length; },
    clearInterval: (i) => { intervals[i - 1] = null; },
    HTMLButtonElement: function () {},
  };
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx);
  await new Promise((r) => setImmediate(r));
  const view = () => {
    const d = document.byId;
    return {
      state: document.body.dataset.state,
      heading: d.mode.textContent,
      progress: d.progress.textContent,
      remedy: d.remedy.hidden ? '' : d.remedy.textContent,
      actions: !d.actions.hidden,
      start: !d.actions.hidden && !d['btn-start'].hidden,
      stop: !d.actions.hidden && !d['btn-stop'].hidden,
      retryFocus: d['btn-retry'].focused,
      startFocus: d['btn-start'].focused,
      hint: d.hint.textContent,
      nifty: d.nifty.textContent,
      icici: d.icici.textContent,
      iciciClass: d.icici.className,
      notif: d.notif.hidden ? '' : d.notif.textContent,
      ver: d.ver.textContent,
      rowState: (n) => document.rows[n].children['.s'].textContent,
    };
  };
  const set = async (next) => { current = next; await window.__sdBootRefresh(); };
  return { view, set, calls, document, winListeners, intervals, window };
}

// ---- 1. login start (C1-desktop-native-01 / C2-reliability-ops-03) ----
{
  const t = await run(status({ down_secs: 40, starting: { reason: 'login', elapsed_secs: 40, grace_secs: 180 } }));
  const v = t.view();
  check('login grace: state starting', v.state === 'starting', v.state);
  check('login grace: no Start, no Stop', !v.start && !v.stop, JSON.stringify(v));
  check('login grace: no action bar at all', !v.actions);
  check('login grace: heading is not the down heading', v.heading.startsWith('STARTING THE STACK'), v.heading);
  check('login grace: per-service progress', /data-service …  →  ui-api …  →  master-controller …/.test(v.progress), v.progress);
  check('login grace: says 1–4 min', v.progress.includes('usually 1–4 min'), v.progress);
  check('login grace: rows show STARTING, not DOWN', v.rowState('ui-api').includes('STARTING'), v.rowState('ui-api'));
  // services come up one by one
  await t.set(status({ down_secs: 70, starting: { reason: 'login', elapsed_secs: 70, grace_secs: 180 },
    services: [svc('data-service', 8001, true), svc('ui-api', 8010, false), svc('master-controller', 8008, false)] }));
  check('login grace: data-service ✓', t.view().progress.includes('data-service ✓'), t.view().progress);
  // after the grace: the down state with its actions, focus on Start
  await t.set(status({ down_secs: 200, starting: null }));
  const d = t.view();
  check('after grace: down', d.state === 'down' && d.start && d.actions, JSON.stringify(d));
  check('after grace: focus moves to Start', d.startFocus === 1, String(d.startFocus));
  check('after grace: no raw command text', !/launchctl|kickstart|gui\//.test(d.progress + d.remedy), d.progress);
}

// ---- 2. a watchdog run in progress / a Start that was just requested ----
{
  const t = await run(status({ down_secs: 300, starting: { reason: 'watchdog', elapsed_secs: 9000, grace_secs: 180 } }));
  check('watchdog run: starting, no Start', t.view().state === 'starting' && !t.view().start);
  check('watchdog run: says the watchdog is starting', t.view().progress.startsWith('The watchdog is starting the stack'));
  const r = await run(status({ down_secs: 30, starting: { reason: 'start_requested', elapsed_secs: 30, grace_secs: 180 } }));
  check('start requested: starting', r.view().state === 'starting' && r.view().progress.startsWith('Starting the stack (requested)'));
}

// ---- 3. missing UI release (C2-reliability-ops-04): remedy, never Start/Stop ----
{
  const t = await run(status({
    ui_state: 'no_release', ui_detail: 'ui-api is up but has no terminal UI release to serve',
    services: [svc('data-service', 8001, true), svc('ui-api', 8010, true), svc('master-controller', 8008, true)],
  }));
  const v = t.view();
  check('no release: state', v.state === 'norelease', v.state);
  check('no release: build-ui + rollback commands', v.remedy.includes('./start-local.sh build-ui') && v.remedy.includes('--rollback'), v.remedy);
  check('no release: no Start, no Stop', !v.start && !v.stop, JSON.stringify(v));
  check('no release: focus on Retry', v.retryFocus === 1);
}

// ---- 4. port squatting (C2-security-04) ----
{
  const t = await run(status({
    ui_state: 'untrusted', ui_detail: 'pid 66 runs /Applications/Helper.app/Contents/MacOS/Helper, not the stack\'s Python',
    services: [svc('data-service', 8001, true), svc('ui-api', 8010, true), svc('master-controller', 8008, true)],
  }));
  const v = t.view();
  check('untrusted: state', v.state === 'untrusted', v.state);
  check('untrusted: names the pid and executable', v.progress.includes('pid 66') && v.progress.includes('Helper.app'), v.progress);
  check('untrusted: no Start', !v.start);
}

// ---- 4a. round 3 (R-RUST-02): a live listener whose executable is gone, never verified ----
{
  const t = await run(status({
    ui_state: 'unverifiable', ui_detail: 'pid 57979 (this user\'s) holds the port, but its executable no longer exists on disk',
    services: [svc('data-service', 8001, true), svc('ui-api', 8010, true), svc('master-controller', 8008, true)],
  }));
  const v = t.view();
  check('unverifiable: state', v.state === 'unverifiable', v.state);
  check('unverifiable: heading', v.heading.startsWith('TERMINAL PORT NOT VERIFIED'), v.heading);
  check('unverifiable: names the pid and the brew-upgrade case', v.progress.includes('pid 57979') && v.progress.includes('brew upgrade'), v.progress);
  check('unverifiable: restart command, no Start', v.remedy.includes('./start-local.sh restart ui-api') && !v.start && v.actions, JSON.stringify(v));
}

// ---- 4a2. round 3 (completeness-final-03): a window held after repeated page crashes ----
{
  const up3 = [svc('data-service', 8001, true), svc('ui-api', 8010, true), svc('master-controller', 8008, true)];
  const t = await run(status({ mode: 'crashed', crash_hold: true, recent_crashes: 4, ui_ready: true, ui_state: 'ready', services: up3 }));
  const v = t.view();
  check('crashed: state (wins over loading while held)', v.state === 'crashed', v.state);
  check('crashed: heading', v.heading.startsWith('PAGE STOPPED'), v.heading);
  check('crashed: says how often and what to do', v.progress.includes('stopped 4 times in 5 min') && v.progress.includes('⌘R'), v.progress);
  check('crashed: Open terminal now shown and focused, no Start', !t.document.byId['open-now'].hidden && t.document.byId['btn-open'].focused === 1 && !v.start, JSON.stringify(v));
  t.document.byId['btn-open'].click();
  await new Promise((r) => setImmediate(r));
  check('crashed: Open terminal now asks the shell (open_terminal)', t.calls.some((c) => c[0] === 'open_terminal'), JSON.stringify(t.calls.map((c) => c[0])));
  // control: the hold lifted (or an old payload without it) is the normal loading state
  const c = await run(status({ mode: 'crashed', crash_hold: false, ui_ready: true, ui_state: 'ready', phase: 'loading', services: up3 }));
  check('crashed without hold: loading (control)', c.view().state === 'loading', c.view().state);
}

// ---- 4b. PM 25 Oct: ui-api holds its port but /health times out (hung) — never "starting" ----
{
  const hungRows = [svc('data-service', 8001, true), { ...svc('ui-api', 8010, false), state: 'not_responding', stalled_secs: 70 }, svc('master-controller', 8008, true)];
  // the live case: a watchdog run was in progress (its lock) while ui-api was hung
  const t = await run(status({ ui_state: 'not_responding', ui_detail: 'ui-api holds :8010 but has not answered /health for 1 min 10 s', services: hungRows,
    stack: { watchdog_loaded: true, watchdog_installed: true, watchdog_running: true, watchdog_run_secs: 30, paused: [], preflight_failed: false },
    starting: { reason: 'watchdog', elapsed_secs: 30, grace_secs: 180 } }));
  const v = t.view();
  check('hung ui-api: not responding, not starting', v.state === 'notresponding', v.state);
  check('hung ui-api: heading', v.heading.startsWith('UI-API NOT RESPONDING'), v.heading);
  check('hung ui-api: row says NOT RESPONDING', v.rowState('ui-api').includes('NOT RESPONDING'), v.rowState('ui-api'));
  check('hung ui-api: how long, and that the watchdog restarts it (W2-OPS rule)',
    v.progress.includes('1 min 10 s') && v.progress.includes('watchdog restarts a hung ui-api') && !v.progress.includes('never restarts'), v.progress);
  check('hung ui-api: restart command', v.remedy.includes('./start-local.sh restart ui-api'), v.remedy);
  check('hung ui-api: no Start (cannot help), Logs/Retry shown', !v.start && v.actions, JSON.stringify(v));
  // during a login grace too
  const l = await run(status({ ui_state: 'not_responding', services: hungRows, starting: { reason: 'login', elapsed_secs: 40, grace_secs: 180 } }));
  check('hung ui-api at login: not starting', l.view().state === 'notresponding', l.view().state);
  // no watchdog agent: never promise an automatic restart; the manual command, still no Start
  const n = await run(status({ ui_state: 'not_responding', services: hungRows,
    stack: { watchdog_loaded: false, watchdog_installed: false, watchdog_running: false, paused: [], preflight_failed: false } }));
  const nv = n.view();
  check('hung ui-api, no watchdog agent: says nothing restarts it, gives the command, no Start',
    nv.state === 'notresponding' && nv.progress.includes('nothing restarts it automatically') && !nv.progress.includes('watchdog restarts') &&
    nv.remedy.includes('./start-local.sh restart ui-api') && !nv.start, JSON.stringify(nv));
  // control: a closed port during the grace is still "starting"
  const c = await run(status({ starting: { reason: 'login', elapsed_secs: 40, grace_secs: 180 } }));
  check('closed port at login: starting (control)', c.view().state === 'starting', c.view().state);
}

// ---- 5. TCC preflight failure, paused stack, not-served ----
{
  const t = await run(status({ stack: { watchdog_loaded: true, watchdog_installed: true, watchdog_running: false, paused: [], preflight_failed: true } }));
  check('tcc: state + steps', t.view().state === 'tcc' && t.view().remedy.includes('Files and Folders'), t.view().remedy);
  const p = await run(status({ stack: { watchdog_loaded: true, watchdog_installed: true, watchdog_running: false, paused: ['data-service', 'ui-api', 'master-controller'], preflight_failed: false } }));
  check('stopped on purpose: state stopped with Start', p.view().state === 'stopped' && p.view().start, JSON.stringify(p.view()));
  check('stopped on purpose: rows say STOPPED', p.view().rowState('ui-api').includes('STOPPED'));
  const n = await run(status({ ui_state: 'not_served', ui_detail: 'GET / returned HTTP 500',
    services: [svc('data-service', 8001, true), svc('ui-api', 8010, true), svc('master-controller', 8008, true)] }));
  check('not served: state, no Start', n.view().state === 'notserved' && !n.view().start, JSON.stringify(n.view()));
}

// ---- 6. watchdog not installed: the install command instead of a useless Start ----
{
  const t = await run(status({ stack: { watchdog_loaded: false, watchdog_installed: false, watchdog_running: false, paused: [], preflight_failed: false } }));
  check('no watchdog: no Start', !t.view().start);
  check('no watchdog: install command', t.view().remedy.includes('scripts/install_launch_agents.sh install'), t.view().remedy);
}

// ---- 6b. wave 2: a login grace without the watchdog agent never hides the install command ----
{
  const noWd = { watchdog_loaded: false, watchdog_installed: false, watchdog_running: false, paused: [], preflight_failed: false };
  const t = await run(status({ down_secs: 40, stack: noWd, starting: { reason: 'login', elapsed_secs: 40, grace_secs: 180 } }));
  check('login without watchdog: down, not starting', t.view().state === 'down', t.view().state);
  check('login without watchdog: install command shown', t.view().remedy.includes('scripts/install_launch_agents.sh install'), t.view().remedy);
  // a watchdog run (its lock) is still a starting state even before launchctl answered
  const w = await run(status({ down_secs: 40, stack: { ...noWd, watchdog_loaded: null, watchdog_running: true }, starting: { reason: 'watchdog', elapsed_secs: 40, grace_secs: 180 } }));
  check('watchdog lock alone: starting', w.view().state === 'starting', w.view().state);
  check('watchdog run: elapsed is the run time', w.view().progress.includes('40 s') && !w.view().progress.includes('longer than usual'), w.view().progress);
}

// ---- 6c. build identity (completeness-04) ----
{
  const t = await run(status({ build_id: 'abc1234-dirty-3f2a91c4-20261025T0930Z' }));
  check('version line shows the build id', t.view().ver === 'v1.0.0 · abc1234-dirty-3f2a91c4-20261025T0930Z', t.view().ver);
  const o = await run(status());
  check('older shell payload: sha fallback', o.view().ver === 'v1.0.0 · abc1234', o.view().ver);
}

// ---- 7. first 15 s, manual launch, reconnecting ----
{
  const t = await run(status({ down_secs: 5 }));
  check('first seconds: waiting without actions', t.view().state === 'waiting' && !t.view().actions);
  const r = await run(status({ down_secs: 5, mode: 'reconnecting' }));
  check('reconnecting', r.view().state === 'reconnecting');
}

// ---- 8. per-window footer, NIFTY closed/stale ----
{
  const m = await run(status({ nifty: { last: 22600, change_pct: -0.39 }, nifty_state: 'closed' }));
  check('main footer', m.view().hint.includes('closing this window keeps SuryaDhana running'), m.view().hint);
  check('nifty closed marker', m.view().nifty.includes('CLOSED'), m.view().nifty);
  const w = await run(status({ label: 'term-3', nifty: null, nifty_state: 'stale' }));
  check('term-N footer', w.view().hint.includes('closing this window closes it'), w.view().hint);
  check('nifty stale', w.view().nifty.includes('stale'), w.view().nifty);
}

// ---- 9. PM drill: after pagehide no boot_status call is sent any more ----
{
  const t = await run(status({ ui_ready: true, ui_state: 'ready', phase: 'loading' }));
  check('loading state', t.view().state === 'loading');
  const before = t.calls.filter((c) => c[0] === 'boot_status').length;
  (t.winListeners.pagehide || []).forEach((f) => f());
  t.intervals.forEach((f) => f && f());
  await t.window.__sdBootRefresh();
  const after = t.calls.filter((c) => c[0] === 'boot_status').length;
  check('pagehide stops polling', after === before, `${before} -> ${after}`);
  check('pagehide clears the timers', t.intervals.every((f) => f === null));
}

// ---- 10. Start click shows the plain-language summary ----
{
  const t = await run(status());
  t.document.byId['btn-start'].click();
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));
  const msg = t.document.byId.message.textContent;
  check('start: plain summary', msg.startsWith('Asked the watchdog') && !msg.includes('launchctl'), msg);
}


// ---- round 4b (P4): ui-api's error_kind on the ICICI line ----
{
  const t = await run(status({ icici: 'unknown', icici_view: 'unreachable' }));
  const v = t.view();
  check('icici outage: unreachable (network), never /login', v.icici.startsWith('UNREACHABLE (network)') && !v.icici.includes('/login') && !/expired/i.test(v.icici), v.icici);
  check('icici outage: amber, not red', v.iciciClass.includes('warn'), v.iciciClass);
  await t.set(status({ icici: 'expired', icici_view: 'expired' }));
  check('icici expired: unchanged wording', t.view().icici === 'EXPIRED — send /login in Telegram', t.view().icici);
  await t.set(status({ icici: 'unknown', icici_view: 'credentials' }));
  check('icici credentials: BRKR, not /login', t.view().icici.includes('BRKR') && !t.view().icici.includes('/login'), t.view().icici);
  // an older shell (no icici_view): the 3-state field as before
  await t.set(status({ icici: 'expired' }));
  check('icici: older shell payload still renders', t.view().icici === 'EXPIRED — send /login in Telegram', t.view().icici);
  await t.set(status({ icici: 'connected', icici_view: 'connected' }));
  check('icici connected', t.view().icici === 'CONNECTED', t.view().icici);
}

// ---- round 4b: notifications denied for the app: one quiet footer line, never an action ----
{
  const t = await run(status({ notifications: 'denied' }));
  const v = t.view();
  check('notifications denied: footer hint', v.notif === 'Notifications are off — System Settings › Notifications › SuryaDhana', v.notif);
  check('notifications denied: nothing is invoked for it', !t.calls.some(([c]) => /notif|settings|open_url/i.test(c)), JSON.stringify(t.calls.map((c) => c[0])));
  for (const n of ['granted', 'default', 'unknown', undefined]) {
    await t.set(status({ notifications: n }));
    check(`notifications ${n}: no hint`, t.view().notif === '', t.view().notif);
  }
}

console.log(`${failures ? 'FAILED' : 'PASSED'} ${passes}/${passes + failures} boot-page checks`);
process.exit(failures ? 1 : 0);
