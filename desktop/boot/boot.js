// SuryaDhana boot screen. Data only via IPC (boot-only commands); no network, no remote scripts.
// The shell moves this window to the terminal automatically once ui-api is up, serves the UI release and
// its port listener passed the shell's port-squatting check.
//
// States (body[data-state]): checking · loading · starting (login / Start / watchdog run: amber, no
// Start/Stop) · norelease (ui-api up, no UI release: build-ui / rollback commands, no Start/Stop) ·
// untrusted (an unexpected process holds the terminal port) · unverifiable (a process of this user holds it
// but its executable is gone and it was never verified: restart ui-api) · crashed (this window's page
// stopped several times in a few minutes, the WebKit content process ended: not reloaded automatically any
// more; "Open terminal now") · notresponding (ui-api holds its port but
// /health keeps timing out: hung; wins over "starting") · tcc (macOS blocks the stack's Python) ·
// waiting / reconnecting (first 15 s) · notserved (ui-api up, GET / is not the terminal) · stopped (every
// down service was stopped on purpose) · down.
'use strict';

// First painted frame (two rAFs after the first script run). Reported to the shell once: the shell
// leaves the boot page only after it has painted, and --self-test measures it.
requestAnimationFrame(function () {
  requestAnimationFrame(function () {
    window.__BOOT_PAINT__ = performance.now();
    if (typeof window.__sdOnPaint === 'function') window.__sdOnPaint();
  });
});

(function () {
  var internals = window.__TAURI_INTERNALS__;
  var $ = function (id) { return document.getElementById(id); };
  var DOWN_ACTIONS_AFTER_S = 15;
  var busy = false;
  var last = null;
  var lastState = null;
  var stopped = false;
  var timers = [];

  // ---- IST clock (independent of the Mac's timezone) ----
  var timeFmt = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  var dateFmt = new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', weekday: 'short', day: '2-digit', month: 'short' });
  function tick() {
    var now = new Date();
    $('clock').textContent = timeFmt.format(now);
    $('date').textContent = dateFmt.format(now).toUpperCase();
  }
  tick();
  timers.push(setInterval(tick, 1000));

  var shell = window.__SURYADHANA_SHELL__;
  if (shell) { $('ver').textContent = 'v' + shell.version + ' · ' + shell.build; }

  if (!internals || typeof internals.invoke !== 'function') {
    document.body.dataset.state = 'down';
    $('progress').textContent = 'This page runs inside SuryaDhana.app only.';
    return;
  }
  function invoke(cmd, args) { return internals.invoke(cmd, args || {}); }

  // The shell is navigating this window to the terminal: stop every timer so no poll arrives after the
  // window changed origin (the shell refuses boot commands from the terminal origin).
  window.addEventListener('pagehide', function () {
    stopped = true;
    timers.forEach(function (t) { clearInterval(t); });
  });

  // ---- formatting ----
  function grp(n, d) {
    var s = Math.abs(n).toFixed(d), parts = s.split('.'), i = parts[0], out = '';
    while (i.length > 3) { out = ',' + i.slice(-3) + out; i = i.slice(0, -3); }
    return (n < 0 ? '-' : '') + i + out + (parts[1] ? '.' + parts[1] : '');
  }
  function inr(n) { // Indian grouping 5,02,085
    var s = String(Math.round(Math.abs(n))), last3 = s.slice(-3), head = s.slice(0, -3), out = '';
    while (head.length > 2) { out = ',' + head.slice(-2) + out; head = head.slice(0, -2); }
    return (n < 0 ? '-' : '') + '₹' + (head ? head + out + ',' : '') + last3;
  }
  function mmss(sec) {
    var m = Math.floor(sec / 60), s = sec % 60;
    return m > 0 ? m + ' min ' + (s < 10 ? '0' : '') + s + ' s' : s + ' s';
  }
  function setText(id, text, cls) {
    var el = $(id);
    el.textContent = text;
    el.className = (el.classList.contains('copy') ? 'copy ' : '') + (cls || '');
  }

  function isPaused(s, name) { return !!(s.stack && s.stack.paused && s.stack.paused.indexOf(name) >= 0); }
  // the watchdog LaunchAgent exists (installed or loaded): only then can a login / Start grace be real
  function watchdogPresent(s) { return !!(s.stack && (s.stack.watchdog_loaded || s.stack.watchdog_installed)); }

  // ---- which state ----
  function stateOf(s) {
    if (s.polls === 0) return 'checking';
    // round 3: the shell stopped reloading this window after repeated page crashes; it waits for the owner
    if (s.mode === 'crashed' && s.crash_hold) return 'crashed';
    if (s.ui_ready) return 'loading';
    if (s.ui_state === 'no_release') return 'norelease';
    if (s.ui_state === 'untrusted') return 'untrusted';
    if (s.ui_state === 'unverifiable') return 'unverifiable';
    // a ui-api that holds its port but does not answer is running (hung): never "starting", never "down"
    if (s.ui_state === 'not_responding') return 'notresponding';
    var apiDown = !s.services.some(function (x) { return x.name === 'ui-api' && x.up; });
    if (apiDown && s.stack && s.stack.preflight_failed) return 'tcc';
    // a login / Start grace without a watchdog agent would hide the only remedy (the shell does not send one;
    // this is the page's own guard): a watchdog run holding its lock is proof enough
    if (s.starting && (s.starting.reason === 'watchdog' || watchdogPresent(s))) return 'starting';
    var down = s.down_secs != null ? s.down_secs : 0;
    if (down <= DOWN_ACTIONS_AFTER_S) return s.mode === 'reconnecting' ? 'reconnecting' : 'waiting';
    if (!apiDown && s.ui_state === 'not_served') return 'notserved';
    var downSvcs = s.services.filter(function (x) { return !x.up; });
    if (downSvcs.length && downSvcs.every(function (x) { return isPaused(s, x.name); })) return 'stopped';
    return 'down';
  }

  function startingLine(s) {
    var st = s.starting, el = st ? mmss(st.elapsed_secs) : '';
    var steps = s.services.map(function (x) {
      return x.name + (x.up ? ' ✓' : x.state === 'not_responding' ? ' ⚠' : ' …');
    }).join('  →  ');
    var why = !st ? 'Starting the stack' :
      st.reason === 'login' ? 'Starting the stack after login' :
      st.reason === 'start_requested' ? 'Starting the stack (requested)' : 'The watchdog is starting the stack';
    var over = st && st.elapsed_secs > st.grace_secs;
    return why + ' · ' + steps + ' · ' + el + (over ? ' (taking longer than usual: check the logs)' : ' (usually 1–4 min)');
  }

  // ---- render ----
  function render(s) {
    last = s;
    var state = stateOf(s);
    var heading = {
      checking: 'BOOT SEQUENCE', loading: 'BOOT SEQUENCE', waiting: 'BOOT SEQUENCE', reconnecting: 'RECONNECTING',
      starting: 'STARTING THE STACK', norelease: 'NO TERMINAL UI RELEASE', untrusted: 'TERMINAL PORT NOT TRUSTED',
      unverifiable: 'TERMINAL PORT NOT VERIFIED', crashed: 'PAGE STOPPED',
      notresponding: 'UI-API NOT RESPONDING',
      tcc: 'macOS IS BLOCKING THE STACK', notserved: 'TERMINAL NOT SERVED', stopped: 'STACK STOPPED', down: s.mode === 'reconnecting' ? 'RECONNECTING' : 'STACK DOWN'
    }[state];
    $('mode').textContent = heading + (s.target_code ? ' · ' + s.target_code : '');
    $('ver').textContent = 'v' + s.version + ' · ' + (s.build_id || s.build);
    $('build').textContent = s.ui_url;
    $('hint').textContent = s.label === 'main'
      ? '⌘N new window · ⌘K GO bar · ⌘1–⌘9 pages · closing this window keeps SuryaDhana running in the menu bar'
      : '⌘N new window · ⌘K GO bar · ⌘1–⌘9 pages · closing this window closes it; SuryaDhana keeps running in the menu bar';

    s.services.forEach(function (svc) {
      var row = document.querySelector('[data-svc="' + svc.name + '"]');
      if (!row) return;
      row.querySelector('.p').textContent = svc.port == null ? '—' : String(svc.port);
      var st = row.querySelector('.s');
      if (s.polls === 0) { st.textContent = '● …'; st.className = 's pend'; }
      else if (svc.up) { st.textContent = '● UP'; st.className = 's up'; }
      else if (svc.state === 'not_responding') { st.textContent = '◌ NOT RESPONDING'; st.className = 's hung'; }
      else if (isPaused(s, svc.name)) { st.textContent = '○ STOPPED'; st.className = 's paused'; }
      else if (state === 'starting') { st.textContent = '◌ STARTING'; st.className = 's starting'; }
      else { st.textContent = '○ DOWN'; st.className = 's down'; }
      row.querySelector('.l').textContent = svc.up && svc.latency_ms != null ? svc.latency_ms.toFixed(0) + ' ms' : '—';
    });

    if (s.ui_ready) setText('ui', s.ui_build ? 'served · build ' + s.ui_build : 'served (no build-info.json)', 'ok');
    else if (s.polls === 0) setText('ui', 'checking…', '');
    else setText('ui', 'not reachable — ' + (s.ui_detail || 'waiting'), state === 'starting' ? 'dim' : 'bad');

    // round 4b (P4): icici_view carries ui-api's reason; an older shell sends only icici
    var iv = s.icici_view || s.icici;
    if (iv === 'connected') setText('icici', 'CONNECTED', 'ok');
    else if (iv === 'expired') setText('icici', 'EXPIRED — send /login in Telegram', 'bad');
    else if (iv === 'unreachable') setText('icici', 'UNREACHABLE (network) — not a login problem; retried by itself', 'warn');
    else if (iv === 'credentials') setText('icici', 'API KEY / SECRET missing or rejected — fix it on BRKR', 'bad');
    else setText('icici', 'unknown', 'dim');

    if (s.nifty) {
      var up = s.nifty.change_pct >= 0;
      var closed = s.nifty_state === 'closed' ? '  · CLOSED' : '';
      setText('nifty', grp(s.nifty.last, 2) + '  ' + (up ? '▲' : '▼') + Math.abs(s.nifty.change_pct).toFixed(2) + '%' + closed, up ? 'ok' : 'bad');
    } else setText('nifty', s.nifty_state === 'stale' ? '— (quote stale: data-service not answering?)' : '—', 'dim');

    if (s.desk) setText('desk', inr(s.desk.nav) + '  ' + (s.desk.return_pct >= 0 ? '+' : '') + s.desk.return_pct.toFixed(2) + '%  (' + s.desk.date + ')', s.desk.return_pct >= 0 ? 'ok' : 'bad');
    else setText('desk', '—', 'dim');

    var down = s.down_secs != null ? s.down_secs : 0;
    var progress, remedy = '';
    var wdOk = watchdogPresent(s);
    switch (state) {
      case 'checking': progress = 'Checking services…'; break;
      case 'loading': {
        // O-F5a (D-BOOT): ui-api is up so the terminal opens, but say when data-service is still behind —
        // the terminal itself shows a WARMING UP strip until it answers (no action needed here).
        var dsBehind = s.services.some(function (x) { return x.name === 'data-service' && !x.up; });
        progress = 'Loading terminal' + (s.target_code ? ' · ' + s.target_code : '') + '…' +
          (dsBehind ? ' data-service is still starting; the terminal shows WARMING UP until it answers.' : '');
        break;
      }
      case 'starting': progress = startingLine(s); break;
      case 'norelease':
        progress = 'ui-api is running, but there is no terminal UI release to serve. Build one (about 15 s), or bring back the previous release; the window opens by itself once it is there.';
        remedy = 'cd ' + s.repo + '\n./start-local.sh build-ui              # build and publish a new UI release\n./start-local.sh build-ui --rollback   # or: bring back the previous release';
        break;
      case 'untrusted':
        progress = 'SuryaDhana did not open the terminal: the program answering ' + s.ui_url + ' is not the stack\'s ui-api. ' + (s.ui_detail || '');
        remedy = 'Quit that program, then restart ui-api:\ncd ' + s.repo + '\n./start-local.sh restart ui-api';
        break;
      case 'unverifiable':
        progress = 'SuryaDhana did not open the terminal: the process answering ' + s.ui_url + ' cannot be verified. ' +
          (s.ui_detail || '') + '. If Python was just upgraded (brew upgrade), restarting ui-api fixes it; this window opens by itself afterwards.';
        remedy = 'cd ' + s.repo + '\n./start-local.sh restart ui-api';
        break;
      case 'crashed':
        progress = 'This window\'s page stopped ' + (s.recent_crashes || 'several') + ' times in 5 min (its WebKit content process ended), ' +
          'so SuryaDhana stopped reloading it automatically. Open the terminal again when you are ready (⌘R works too). ' +
          'If it keeps stopping, check memory pressure in Activity Monitor and the app log (Help ▸ Open App Logs Folder).';
        break;
      case 'notresponding': {
        var ui = s.services.filter(function (x) { return x.name === 'ui-api'; })[0] || {};
        // the watchdog's hang rule (scripts/stack_watchdog.sh, W2-OPS 25 Oct): two failed runs in a row -> restart
        var wdOn = !!(s.stack && s.stack.watchdog_loaded !== false && watchdogPresent(s));
        progress = 'ui-api holds port ' + (ui.port == null ? '' : ui.port) + ' but has not answered /health for ' +
          mmss(ui.stalled_secs || 0) + ' (its event loop is probably blocked). ' +
          (wdOn ? 'The watchdog restarts a hung ui-api once it has failed two checks in a row (about 3.5–5.5 min after it hung, ' +
                  'after saving diagnostics to .logs/hangs/); '
                : 'The watchdog agent is not loaded, so nothing restarts it automatically; ') +
          'this window opens by itself as soon as it answers. To restart it now:';
        remedy = 'cd ' + s.repo + '\n./start-local.sh restart ui-api';
        break;
      }
      case 'tcc':
        progress = 'macOS is blocking the stack\'s Python (it lives in ~/Desktop), so the watchdog cannot start the services. Fix it once at this Mac:';
        remedy = 'System Settings › Privacy & Security › Files and Folders\n  → allow "Python" access to the Desktop folder (or click Allow on a waiting prompt)\nThe watchdog retries every 2 min.';
        break;
      case 'notserved':
        progress = 'ui-api answers, but ' + s.ui_url + '/ is not the terminal yet: ' + (s.ui_detail || 'unknown') + '. The window opens by itself when it is; the logs say why.';
        break;
      case 'stopped': progress = 'The stack was stopped on purpose (marked paused): the watchdog leaves it down. Start it again when you need it.'; break;
      case 'down':
        progress = 'Terminal unreachable for ' + mmss(down) + '. The watchdog checks every 2 min and restarts stopped core services (usually 1–4 min). Start the stack now, or check the logs.';
        if (!wdOk && s.stack && s.stack.watchdog_loaded === false) {
          remedy = 'The watchdog LaunchAgent is not installed. In Terminal:\ncd ' + s.repo + '\nscripts/install_launch_agents.sh install';
        }
        break;
      default:
        progress = (s.mode === 'reconnecting' ? 'Reconnecting' : 'Waiting for ui-api') + '… (' + down + ' s)';
    }
    document.body.dataset.state = state;
    if ($('progress').textContent !== progress) $('progress').textContent = progress;
    var rem = $('remedy');
    rem.hidden = !remedy;
    if (rem.textContent !== remedy) rem.textContent = remedy;

    // actions: Start/Stop only in the down / stopped states; never while starting, never for a missing
    // release or an untrusted listener (neither can fix those)
    var withActions = ['down', 'stopped', 'norelease', 'untrusted', 'unverifiable', 'notresponding', 'tcc', 'notserved', 'crashed'].indexOf(state) >= 0;
    var startable = (state === 'down' || state === 'stopped') && wdOk;
    var anyUp = s.services.some(function (x) { return x.up; });
    $('actions').hidden = !withActions;
    $('btn-start').hidden = !startable;
    $('btn-start').disabled = busy || !s.repo_ok || s.selftest;
    $('btn-stop').hidden = !(state === 'down' && anyUp);
    $('open-now').hidden = !((s.ui_ready && s.phase === 'boot') || state === 'crashed');
    if (withActions && lastState !== state) {
      // VoiceOver / keyboard: put focus on the primary action when the actions appear
      var primary = startable ? $('btn-start') : state === 'crashed' ? $('btn-open') : $('btn-retry');
      try { primary.focus({ preventScroll: true }); } catch (e) { /* not focusable yet */ }
    }
    lastState = state;

    var fz = $('freeze');
    if (s.freeze) { fz.hidden = false; fz.textContent = 'RESTART FREEZE ' + s.freeze.label; }
    else fz.hidden = true;

    // round 4b: macOS has SuryaDhana's notifications off: a quiet footer line (no button: System Settings opens
    // only from the menu-bar item's line, on a click)
    var nf = $('notif');
    if (s.notifications === 'denied') {
      nf.hidden = false;
      nf.textContent = 'Notifications are off — System Settings › Notifications › SuryaDhana';
    } else nf.hidden = true;
  }

  function showMessage(text, isError) {
    var m = $('message');
    m.hidden = !text;
    m.textContent = text || '';
    m.className = 'message copy' + (isError ? ' bad' : '');
  }

  function poll(refresh) {
    if (stopped) return Promise.resolve();
    return invoke('boot_status', refresh ? { refresh: true } : {})
      .then(function (s) { if (!stopped) render(s); })
      .catch(function (e) { if (!stopped) showMessage('Shell status unavailable: ' + e, true); });
  }

  // ---- actions ----
  $('btn-start').addEventListener('click', function () {
    busy = true; this.disabled = true;
    showMessage('Asking the watchdog to start the stack…');
    invoke('stack_start')
      .then(function (r) { showMessage(r); })
      .catch(function (e) { showMessage('Start failed: ' + e, true); })
      .finally(function () { busy = false; poll(true); });
  });
  $('btn-logs').addEventListener('click', function () {
    invoke('open_logs', { target: 'stack' }).catch(function (e) { showMessage('Could not open logs: ' + e, true); });
  });
  $('btn-retry').addEventListener('click', function () { showMessage(''); poll(true); });
  $('btn-stop').addEventListener('click', function () {
    invoke('stack_stop')
      .then(function (r) { showMessage(r); })
      .catch(function (e) { if (String(e) !== 'cancelled') showMessage(String(e), true); })
      .finally(function () { poll(true); });
  });
  $('btn-open').addEventListener('click', function () {
    invoke('open_terminal', last && last.target_tab ? { tab: last.target_tab } : {})
      .catch(function (e) { showMessage(String(e), true); });
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.metaKey && !e.ctrlKey && !(e.target instanceof HTMLButtonElement)) { poll(true); }
  });

  window.__sdOnPaint = function () {
    if (stopped) return;
    invoke('boot_status', { paint: performance.timeOrigin + window.__BOOT_PAINT__ }).then(render).catch(function () {});
  };
  if (window.__BOOT_PAINT__ != null) window.__sdOnPaint();

  // Re-render now (used by --self-test: WebKit throttles timers of hidden pages, e.g. while the screen is locked).
  window.__sdBootRefresh = function () { return poll(false); };

  poll(false);
  timers.push(setInterval(function () { poll(false); }, 1000));
})();
