//! `--self-test <out.json>` (or env `SURYADHANA_SELFTEST_OUT`): run the real app, introspect it from the
//! inside (including the remote terminal page in WKWebView) and write
//! `{passed, checks:[{name, ok, detail, ms}], meta}`; exit 0 when every check passed, else 1, always
//! within 60 s (a watchdog thread writes whatever finished and exits 1 at 58 s).
//!
//! Isolation (lib.rs + windows.rs honour `Shell::selftest`): temp state.json / window-state file /
//! Downloads dir / app log (copied next to the report as `<out>.app.log`, never the owner's
//! ~/Library/Logs/ai.suryadhana.terminal), incognito webviews, no single-instance lock, autostart is only
//! *read*, notifications and external-browser opens are recorded instead of performed, stack start/stop are
//! refused, nothing is ever sent to Telegram.
//!
//! Run modes (scripts/build_desktop.sh --test; the terminal origin is `SURYADHANA_UI_URL`):
//! * a scratch UI server: the full check list;
//! * a closed port: the boot page's down state (actions after 15 s);
//! * a closed port with `--autostart` (and `SURYADHANA_STARTUP_GRACE_S=<s>`): the start-up grace state
//!   (no red, no Start/Stop) and the down state after the grace;
//! * a server answering /health 200, GET / 503 and /ready `ui: missing`: the "no UI release" state;
//! * a server run by another interpreter: the port-squatting refusal;
//! * a listener that never answers (a hung ui-api: port held, `/health` timing out): "not responding",
//!   also with `--autostart` (it must win over the start-up grace).
//!
//! JS reporting path: `Webview::eval_with_callback` (self-test only). Scripts always return a JSON
//! *string* (wry's NSJSONSerialization of arbitrary values can panic), parsed twice on the Rust side.

use std::path::PathBuf;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, Url, WebviewWindow};
use tauri_plugin_window_state::{AppHandleExt as _, StateFlags};

use crate::health::{TrustView, UiState};

use crate::windows::{self, Phase, MAIN};
use crate::{menu, policy, tray, Shell};

static EXIT_CODE: OnceLock<i32> = OnceLock::new();

/// Exit code decided by a finished self-test (used by the RunEvent::Exit handler).
pub fn exit_code() -> Option<i32> {
    EXIT_CODE.get().copied()
}

/// Self-test options.
#[derive(Debug, Clone)]
pub struct Options {
    pub out: PathBuf,
    pub temp_dir: PathBuf,
}

impl Options {
    /// `--self-test <path>`, `--self-test=<path>` or `SURYADHANA_SELFTEST_OUT=<path>`.
    pub fn from_env_and_args() -> Option<Options> {
        let args: Vec<String> = std::env::args().collect();
        let mut out = None;
        for (i, a) in args.iter().enumerate() {
            if a == "--self-test" {
                out = Some(
                    args.get(i + 1)
                        .cloned()
                        .unwrap_or_else(|| "suryadhana-selftest.json".into()),
                );
            } else if let Some(p) = a.strip_prefix("--self-test=") {
                out = Some(p.to_string());
            }
        }
        let out = out.or_else(|| {
            std::env::var("SURYADHANA_SELFTEST_OUT")
                .ok()
                .filter(|s| !s.trim().is_empty())
        })?;
        let temp_dir = std::env::temp_dir().join(format!("suryadhana-selftest-{}", std::process::id()));
        let _ = std::fs::create_dir_all(&temp_dir);
        Some(Options {
            out: PathBuf::from(out),
            temp_dir,
        })
    }

    /// Where the self-test's app log goes (C2-reliability-ops-11).
    pub fn log_dir(&self) -> PathBuf {
        self.temp_dir.join("logs")
    }

    /// The copy of the app log kept next to the report.
    pub fn log_copy(&self) -> PathBuf {
        let mut s = self.out.as_os_str().to_owned();
        s.push(".app.log");
        PathBuf::from(s)
    }
}

#[derive(Debug, Clone, Serialize)]
struct Check {
    name: String,
    ok: bool,
    detail: String,
    ms: Option<f64>,
    /// Present (true) only when the check could not be measured in this environment (e.g. the screen is
    /// locked, so WebKit paints nothing). A skipped check does not fail the run, and it is listed in
    /// `meta.skipped` so a reader never mistakes it for a measured pass.
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    skipped: bool,
}

#[derive(Debug, Default)]
struct Report {
    checks: Vec<Check>,
    meta: serde_json::Map<String, Value>,
    written: bool,
}

type Shared = Arc<Mutex<Report>>;

fn add(r: &Shared, name: &str, ok: bool, detail: impl Into<String>, ms: Option<f64>) {
    let detail = detail.into();
    log::info!(
        "[selftest] {} {name}: {detail}{}",
        if ok { "PASS" } else { "FAIL" },
        ms.map(|m| format!(" ({m:.0} ms)")).unwrap_or_default()
    );
    r.lock().unwrap_or_else(|e| e.into_inner()).checks.push(Check {
        name: name.into(),
        ok,
        detail,
        ms: ms.map(|m| (m * 10.0).round() / 10.0),
        skipped: false,
    });
}

/// A check that cannot be measured here: recorded as `ok` + `skipped`, and listed in `meta.skipped`.
fn skip(r: &Shared, name: &str, detail: impl Into<String>) {
    let detail = detail.into();
    log::info!("[selftest] SKIP {name}: {detail}");
    let mut rep = r.lock().unwrap_or_else(|e| e.into_inner());
    rep.checks.push(Check {
        name: name.into(),
        ok: true,
        detail,
        ms: None,
        skipped: true,
    });
    let entry = rep.meta.entry("skipped").or_insert_with(|| json!([]));
    if let Some(a) = entry.as_array_mut() {
        a.push(json!(name));
    }
}

fn write_report(r: &Shared, out: &PathBuf) -> bool {
    let mut rep = r.lock().unwrap_or_else(|e| e.into_inner());
    if rep.written {
        return rep.checks.iter().all(|c| c.ok);
    }
    let passed = !rep.checks.is_empty() && rep.checks.iter().all(|c| c.ok);
    let doc = json!({"passed": passed, "checks": rep.checks, "meta": rep.meta});
    let text = serde_json::to_string_pretty(&doc).unwrap_or_default() + "\n";
    if let Some(dir) = out.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Err(e) = std::fs::write(out, text) {
        log::error!("[selftest] could not write {}: {e}", out.display());
    }
    rep.written = true;
    passed
}

/// Evaluate `body` (a JS function body that returns a JSON-serializable value) in a webview.
async fn eval_json(w: &WebviewWindow, body: &str, timeout: Duration) -> Option<Value> {
    let js = format!(
        "(function(){{try{{return JSON.stringify((function(){{{body}}})());}}catch(e){{return JSON.stringify({{__err:String(e)}});}}}})()"
    );
    let (tx, rx) = tokio::sync::oneshot::channel::<String>();
    let tx = Arc::new(Mutex::new(Some(tx)));
    let res = w.eval_with_callback(js, move |s| {
        if let Some(tx) = tx.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = tx.send(s);
        }
    });
    if res.is_err() {
        return None;
    }
    let raw = tokio::time::timeout(timeout, rx).await.ok()?.ok()?;
    let inner: String = serde_json::from_str(&raw).ok()?;
    serde_json::from_str(&inner).ok()
}

/// Poll `body` until `pred` holds or `timeout` passes; returns the last value and elapsed ms.
async fn poll_js(
    w: &WebviewWindow,
    body: &str,
    timeout: Duration,
    every: Duration,
    pred: impl Fn(&Value) -> bool,
) -> (Option<Value>, f64) {
    let t0 = Instant::now();
    let mut last = None;
    while t0.elapsed() < timeout {
        if let Some(v) = eval_json(w, body, Duration::from_millis(800)).await {
            let done = pred(&v);
            last = Some(v);
            if done {
                break;
            }
        }
        tokio::time::sleep(every).await;
    }
    (last, t0.elapsed().as_secs_f64() * 1000.0)
}

/// True when the console session's screen is locked (`ioreg` IOConsoleUsers → CGSSessionScreenIsLocked).
fn screen_locked() -> bool {
    std::process::Command::new("/usr/sbin/ioreg")
        .args(["-n", "Root", "-d1"])
        .output()
        .map(|o| String::from_utf8_lossy(&o.stdout).contains("\"CGSSessionScreenIsLocked\"=Yes"))
        .unwrap_or(false)
}

fn rss_kb(pid: u32) -> Option<u64> {
    let out = std::process::Command::new("/bin/ps")
        .args(["-o", "rss=", "-p", &pid.to_string()])
        .output()
        .ok()?;
    String::from_utf8_lossy(&out.stdout).trim().parse().ok()
}

/// `ps` etime (`[[dd-]hh:]mm:ss`) -> seconds.
fn etime_secs(s: &str) -> Option<u64> {
    let s = s.trim();
    let (days, rest) = match s.split_once('-') {
        Some((d, r)) => (d.parse::<u64>().ok()?, r),
        None => (0, s),
    };
    let parts: Vec<u64> = rest
        .split(':')
        .map(|p| p.parse::<u64>())
        .collect::<Result<_, _>>()
        .ok()?;
    let (h, m, sec) = match parts.as_slice() {
        [m, s] => (0, *m, *s),
        [h, m, s] => (*h, *m, *s),
        _ => return None,
    };
    Some(days * 86_400 + h * 3_600 + m * 60 + sec)
}

/// macOS "responsible process" of `pid` (how Activity Monitor attributes WKWebView's XPC helpers to the
/// app). `responsibility_get_pid_responsible_for_pid` is exported by libSystem but not in the public
/// headers, so it is looked up at runtime (None when unavailable).
fn responsible_pid(pid: i32) -> Option<i32> {
    type F = unsafe extern "C" fn(libc::pid_t) -> libc::pid_t;
    static SYM: OnceLock<Option<F>> = OnceLock::new();
    let f = SYM.get_or_init(|| {
        // SAFETY: dlsym with RTLD_DEFAULT and a NUL-terminated name; the symbol has this C signature.
        let p = unsafe {
            libc::dlsym(
                libc::RTLD_DEFAULT,
                c"responsibility_get_pid_responsible_for_pid".as_ptr(),
            )
        };
        (!p.is_null()).then(|| unsafe { std::mem::transmute::<*mut libc::c_void, F>(p) })
    });
    // SAFETY: plain syscall-style call on a pid; returns -1 on error.
    f.map(|f| unsafe { f(pid) }).filter(|r| *r > 0)
}

/// RSS of the WebKit helper processes (WebContent / Networking / GPU) that belong to this app. They are
/// XPC services (parent = launchd), so they are attributed by macOS responsibility when available, else
/// by start time (started after this app; that fallback can only err high). Returns (count, kB, method).
fn webkit_helpers_rss_kb(own_pid: u32) -> Option<(usize, u64, &'static str)> {
    let own = std::process::Command::new("/bin/ps")
        .args(["-o", "etime=", "-p", &own_pid.to_string()])
        .output()
        .ok()?;
    let own_secs = etime_secs(&String::from_utf8_lossy(&own.stdout))?;
    let out = std::process::Command::new("/bin/ps")
        .args(["-A", "-o", "pid=,rss=,etime=,comm="])
        .output()
        .ok()?;
    // Launched from Finder/launchd the app is its own responsible process; launched from a terminal the
    // terminal is, and WebKit then attributes the helpers to it: accept that pid too, for helpers that
    // started after this app.
    let own_resp = responsible_pid(own_pid as i32);
    let exact = own_resp.is_some();
    let mut n = 0;
    let mut kb = 0;
    for line in String::from_utf8_lossy(&out.stdout).lines() {
        let mut it = line.split_whitespace();
        let (Some(pid), Some(rss), Some(et)) = (it.next(), it.next(), it.next()) else {
            continue;
        };
        let comm: String = it.collect::<Vec<_>>().join(" ");
        if !(comm.contains("/WebKit.framework/") && comm.contains("com.apple.WebKit.")) {
            continue;
        }
        let (Ok(pid), Ok(rss)) = (pid.parse::<i32>(), rss.parse::<u64>()) else {
            continue;
        };
        let started_after = etime_secs(et).map(|secs| secs <= own_secs).unwrap_or(false);
        let mine = if exact {
            let r = responsible_pid(pid);
            r == Some(own_pid as i32) || (r.is_some() && r == own_resp && started_after)
        } else {
            started_after
        };
        if mine {
            n += 1;
            kb += rss;
        }
    }
    Some((
        n,
        kb,
        if exact {
            "macOS responsibility"
        } else {
            "start time (approximate)"
        },
    ))
}

/// Start the self-test task and its 58 s watchdog.
pub fn spawn(app: AppHandle, opts: Options) {
    let report: Shared = Arc::new(Mutex::new(Report::default()));
    {
        let r = report.clone();
        let out = opts.out.clone();
        std::thread::spawn(move || {
            std::thread::sleep(Duration::from_secs(58));
            add(&r, "deadline", false, "self-test did not finish within 58 s", None);
            write_report(&r, &out);
            std::process::exit(1);
        });
    }
    tauri::async_runtime::spawn(async move {
        run(app.clone(), report.clone(), &opts).await;
        let passed = write_report(&report, &opts.out);
        let code = if passed { 0 } else { 1 };
        let _ = EXIT_CODE.set(code);
        log::info!(
            "[selftest] finished: {} -> {}",
            if passed { "PASSED" } else { "FAILED" },
            opts.out.display()
        );
        log::logger().flush();
        let _ = std::fs::copy(opts.log_dir().join("suryadhana.log"), opts.log_copy());
        let _ = std::fs::remove_dir_all(&opts.temp_dir);
        app.exit(code);
        // belt and braces: if the event loop does not exit promptly
        tokio::time::sleep(Duration::from_secs(3)).await;
        std::process::exit(code);
    });
}

async fn run(app: AppHandle, r: Shared, opts: &Options) {
    let shell = app.state::<Shell>();
    let t_start = shell.started;
    let deadline = t_start + Duration::from_secs(50);
    {
        let mut rep = r.lock().unwrap_or_else(|e| e.into_inner());
        rep.meta.insert("version".into(), json!(env!("CARGO_PKG_VERSION")));
        rep.meta.insert("build".into(), json!(env!("SURYADHANA_BUILD")));
        rep.meta.insert("build_id".into(), json!(crate::BUILD_ID));
        rep.meta.insert("ui_url".into(), json!(windows::ui_origin(&app)));
        rep.meta.insert("pid".into(), json!(std::process::id()));
        rep.meta.insert("started_at".into(), json!(crate::health::now_iso()));
        rep.meta
            .insert("isolated_state_dir".into(), json!(opts.temp_dir.display().to_string()));
    }
    let autostart_before = Some(crate::autostart_state(&app).checked());

    // ---- 1. boot page paint ----
    let Some(main) = wait_window(&app, MAIN, Duration::from_secs(5)).await else {
        shell.hold_boot.store(false, std::sync::atomic::Ordering::Relaxed);
        add(&r, "main_window", false, "main window was not created", None);
        return;
    };
    // WebKit does not render occluded / background windows (rAF is paused), so bring the window to the
    // front: a launch from Finder or the Dock activates the app the same way.
    let _ = main.set_focus();

    // The boot page reports its first painted frame (epoch ms) through boot_status; the navigator waits
    // for it before leaving the boot page, so this is measured even when the stack is up and fast.
    let t_wait = Instant::now();
    let mut painted = None;
    while t_wait.elapsed() < Duration::from_secs(5) {
        if let Some(p) = *shell.boot_paint_epoch_ms.lock().unwrap_or_else(|e| e.into_inner()) {
            painted = Some(p);
            break;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let locked = screen_locked();
    r.lock()
        .unwrap_or_else(|e| e.into_inner())
        .meta
        .insert("screen_locked".into(), json!(locked));
    match painted {
        Some(p) => {
            let ms = p - shell.started_epoch_ms;
            add(&r, "boot_page_painted", ms < 500.0, format!("boot page first frame painted {ms:.0} ms after process start (budget 500 ms)"), Some(ms));
        }
        // WebKit renders nothing while the login session is locked (no frames, rAF paused): not measurable
        None if locked => skip(&r, "boot_page_painted", "the screen is locked: WebKit paints no frames while the session is locked (re-run unlocked to measure the < 500 ms budget)"),
        None => add(&r, "boot_page_painted", false, "the boot page never reported a painted frame within 5 s", None),
    }
    let st = eval_json(
        &main,
        "return {href: location.href, state: document.body ? document.body.dataset.state : null}",
        Duration::from_secs(2),
    )
    .await;
    add(
        &r,
        "boot_page_state (info)",
        true,
        format!("{}", st.unwrap_or(Value::Null)),
        None,
    );
    // Paint-independent proxy (measurable even with the screen locked): when the boot document had been
    // parsed and boot.js had run (Navigation Timing domContentLoadedEventEnd), relative to process start.
    let nav = eval_json(
        &main,
        "var n=performance.getEntriesByType('navigation')[0]; return {origin: performance.timeOrigin, dcl: n ? n.domContentLoadedEventEnd : null, href: location.href}",
        Duration::from_secs(2),
    )
    .await
    .unwrap_or(Value::Null);
    match (
        nav["origin"].as_f64(),
        nav["dcl"].as_f64(),
        nav["href"].as_str().map(|h| h.starts_with("tauri:")),
    ) {
        (Some(o), Some(d), Some(true)) if d > 0.0 => {
            let ms = o + d - shell.started_epoch_ms;
            r.lock()
                .unwrap_or_else(|e| e.into_inner())
                .meta
                .insert("boot_dom_ready_ms".into(), json!((ms * 10.0).round() / 10.0));
            add(
                &r,
                "boot_page_dom_ready (info)",
                true,
                format!(
                    "boot document parsed and boot.js ran {ms:.0} ms after process start (paint-independent proxy)"
                ),
                Some(ms),
            );
        }
        _ => add(
            &r,
            "boot_page_dom_ready (info)",
            true,
            format!("not measured: {nav}"),
            None,
        ),
    }

    // CSP enforcement on the boot page: a dynamically injected inline script must NOT run.
    let csp = eval_json(
        &main,
        "if(!location.href.startsWith('tauri:')) return {skip:true}; window.__csp_probe=0; var s=document.createElement('script'); s.textContent='window.__csp_probe=1'; document.head.appendChild(s); return {skip:false, ran: window.__csp_probe===1}",
        Duration::from_secs(2),
    )
    .await;
    match csp {
        Some(v) if v["skip"] == json!(true) => add(
            &r,
            "boot_csp",
            false,
            "main left the boot page before the CSP probe",
            None,
        ),
        Some(v) => add(
            &r,
            "boot_csp",
            v["ran"] == json!(false),
            format!(
                "inline script injection {}",
                if v["ran"] == json!(false) {
                    "blocked by CSP"
                } else {
                    "EXECUTED (CSP missing)"
                }
            ),
            None,
        ),
        None => add(&r, "boot_csp", false, "could not evaluate on the boot page", None),
    }

    // round 4b (R9): File ▸ Print… never prints the boot page (the menu beeps)
    let refused = windows::print_window(&app, MAIN);
    add(
        &r,
        "print_refused_on_boot_page",
        refused.is_err() && windows::webview_sheet(&main) != Some(true),
        format!("Print… on the boot page: {refused:?}"),
        None,
    );

    // the boot page's state a few seconds in (the start-up grace check compares it with the later state)
    let t_early = Instant::now();
    while t_early.elapsed() < Duration::from_secs(3) && shell.health.snapshot().polls < 2 {
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    let _ = eval_json(
        &main,
        "if (window.__sdBootRefresh) window.__sdBootRefresh(); return true",
        Duration::from_secs(2),
    )
    .await;
    tokio::time::sleep(Duration::from_millis(400)).await;
    let early = eval_json(&main, BOOT_VIEW_JS, Duration::from_secs(2))
        .await
        .unwrap_or(Value::Null);
    r.lock()
        .unwrap_or_else(|e| e.into_inner())
        .meta
        .insert("boot_early".into(), early.clone());

    // release the boot-page hold (self-test only) and measure how long it held the navigator
    let held_ms = t_start.elapsed().as_secs_f64() * 1000.0;
    shell.hold_boot.store(false, std::sync::atomic::Ordering::Relaxed);
    shell.health.poke();

    // ---- 2. terminal load ----
    let wait_until = (Instant::now() + Duration::from_secs(30)).min(deadline);
    let mut loaded_at = None;
    while Instant::now() < wait_until {
        let at = shell
            .windows
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(MAIN)
            .and_then(|w| w.first_terminal_at);
        if let Some(at) = at {
            loaded_at = Some(at);
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    let snap = shell.health.snapshot();
    let Some(loaded_at) = loaded_at else {
        add(
            &r,
            "terminal_loaded",
            false,
            format!(
                "terminal not loaded within 30 s: ui-api {}, ui_ready {} ({})",
                if snap.status.ui_api.up { "up" } else { "down" },
                snap.ui_ready,
                snap.ui_detail
            ),
            None,
        );
        down_state_checks(&app, &main, &r, deadline, &early).await;
        common_checks(&app, &r, autostart_before).await;
        return;
    };
    // a definitive pass (an inconclusive verdict also opens the terminal, but must not count as verified)
    add(
        &r,
        "listener_verified",
        snap.ui_state == UiState::Ready && matches!(snap.trust, TrustView::Trusted(_) | TrustView::Off),
        format!(
            "port-squatting guard verdict {:?} (verify_ui_listener={}; kernel facts only, no file access)",
            snap.trust, shell.cfg.verify_ui_listener
        ),
        None,
    );
    let load_ms = loaded_at.duration_since(t_start).as_secs_f64() * 1000.0;
    let release = (held_ms).min(load_ms);
    add(
        &r,
        "terminal_loaded",
        true,
        format!(
            "terminal page finished loading {load_ms:.0} ms after process start; the self-test held the boot page for its own checks until {held_ms:.0} ms, so boot -> terminal took {:.0} ms",
            load_ms - release
        ),
        Some(load_ms),
    );
    {
        let mut rep = r.lock().unwrap_or_else(|e| e.into_inner());
        rep.meta
            .insert("boot_hold_ms".into(), json!((held_ms * 10.0).round() / 10.0));
        rep.meta.insert(
            "boot_to_terminal_ms".into(),
            json!(((load_ms - release) * 10.0).round() / 10.0),
        );
    }
    let (v, ms) = poll_js(
        &main,
        "return {tabs: document.querySelectorAll('[data-tab]').length, title: document.title}",
        Duration::from_secs(10),
        Duration::from_millis(50),
        |v| v["tabs"].as_u64().unwrap_or(0) > 0,
    )
    .await;
    let tabs = v.as_ref().and_then(|v| v["tabs"].as_u64()).unwrap_or(0);
    let interactive_ms = loaded_at.duration_since(t_start).as_secs_f64() * 1000.0 + ms;
    add(
        &r,
        "terminal_interactive",
        tabs > 0,
        format!(
            "{tabs} page tabs rendered ~{interactive_ms:.0} ms after process start; title {:?}",
            v.as_ref().map(|v| v["title"].clone()).unwrap_or(Value::Null)
        ),
        Some(interactive_ms),
    );

    // ---- 3. detection object ----
    let s = eval_json(
        &main,
        "var s=window.__SURYADHANA_SHELL__; return {s: s||null, frozen: !!s && Object.isFrozen(s), writable: (function(){try{window.__SURYADHANA_SHELL__=1;}catch(e){} return window.__SURYADHANA_SHELL__===1})(), invoke: typeof (window.__TAURI_INTERNALS__ && window.__TAURI_INTERNALS__.invoke), href: location.href}",
        Duration::from_secs(3),
    )
    .await
    .unwrap_or(Value::Null);
    let shell_ok = s["s"]["api"] == json!(1)
        && s["s"]["version"] == json!(env!("CARGO_PKG_VERSION"))
        && s["s"]["build"] == json!(env!("SURYADHANA_BUILD"))
        && s["s"]["platform"] == json!("macos")
        && s["s"]["features"]
            .as_array()
            .map(|f| f.iter().any(|x| x == "notification_feed"))
            .unwrap_or(false)
        && s["frozen"] == json!(true)
        && s["writable"] == json!(false);
    add(
        &r,
        "shell_object_in_terminal",
        shell_ok,
        format!(
            "__SURYADHANA_SHELL__={} frozen={} overwritable={}",
            s["s"], s["frozen"], s["writable"]
        ),
        None,
    );
    let ro = eval_json(
        &main,
        "return localStorage.getItem('suryadhana.prefs.mode')",
        Duration::from_secs(2),
    )
    .await
    .unwrap_or(Value::Null);
    add(
        &r,
        "prefs_readonly_in_selftest",
        ro == json!("readonly"),
        format!("suryadhana.prefs.mode = {ro} (a self-test never writes the prefs store it is pointed at)"),
        None,
    );
    add(
        &r,
        "tauri_internals_invoke_in_terminal",
        s["invoke"] == json!("function"),
        format!("typeof __TAURI_INTERNALS__.invoke = {}", s["invoke"]),
        None,
    );

    // ---- 4. IPC from the remote page ----
    let kick = r#"
      window.__SDST = {}; var I = window.__TAURI_INTERNALS__; var st = window.__SDST;
      function call(key, cmd, args){ var t=performance.now(); return I.invoke(cmd, args||{}).then(function(r){ st[key]={ok:true, r:r, ms:performance.now()-t}; }, function(e){ st[key]={ok:false, e:String(e), ms:performance.now()-t}; }); }
      call('info','shell_info'); call('status','shell_status'); call('perm','shell_notification_permission');
      call('deny_boot','boot_status'); call('deny_stop','stack_stop'); call('deny_start','stack_start'); call('deny_open','open_terminal',{tab:'desk'}); call('deny_logs','open_logs');
      call('deny_plugin','plugin:autostart|is_enabled'); call('deny_event','plugin:event|listen',{event:'x', target:{kind:'Any'}, handler:0});
      call('bad_url','shell_open_external',{url:'http://127.0.0.1:8001/health'}); call('bad_tab','shell_new_window',{tab:'nope'});
      call('bad_sym','shell_new_window',{tab:'desk', sym:'tcs;rm'});
      call('long_title','shell_notify',{title:'x'.repeat(121), body:'b'}); call('ok_external','shell_open_external',{url:'https://example.com/suryadhana-selftest?k=v'});
      call('save','shell_save_download',{filename:'../../evil name?.csv', base64: btoa('a,b\n1,2\n')});
      call('save_zip','shell_save_download',{filename:'NIFTY_levels.zip', base64: btoa('PK')});
      call('save_cmd','shell_save_download',{filename:'run.command', base64: btoa('echo hi')});
      return {started:true};"#;
    let started = eval_json(&main, kick, Duration::from_secs(3)).await;
    let expect = 18usize;
    let (res, _) = poll_js(
        &main,
        "return window.__SDST || {}",
        Duration::from_secs(8),
        Duration::from_millis(50),
        |v| v.as_object().map(|o| o.len() >= expect).unwrap_or(false),
    )
    .await;
    let res = res.unwrap_or(Value::Null);
    if started.is_none() {
        add(
            &r,
            "ipc_round_trip_remote",
            false,
            "could not start the IPC probe in the terminal page",
            None,
        );
    } else {
        let info = &res["info"];
        let ok = info["ok"] == json!(true)
            && info["r"]["version"] == json!(env!("CARGO_PKG_VERSION"))
            && info["r"]["build_id"] == json!(crate::BUILD_ID);
        add(
            &r,
            "ipc_round_trip_remote",
            ok,
            format!(
                "shell_info from {} -> {}",
                windows::ui_origin(&app),
                if ok { info["r"].to_string() } else { info.to_string() }
            ),
            info["ms"].as_f64(),
        );
        let st = &res["status"];
        let keys: Vec<String> = st["r"]
            .as_object()
            .map(|o| o.keys().cloned().collect())
            .unwrap_or_default();
        let mut sorted = keys.clone();
        sorted.sort();
        let want = [
            "at",
            "data_service",
            "icici",
            "master_controller",
            "nifty",
            "ui_api",
            "ui_build",
        ];
        add(
            &r,
            "shell_status_contract",
            st["ok"] == json!(true) && sorted == want,
            format!("keys {sorted:?}"),
            st["ms"].as_f64(),
        );
        for k in [
            "deny_boot",
            "deny_stop",
            "deny_start",
            "deny_open",
            "deny_logs",
            "deny_plugin",
            "deny_event",
        ] {
            let v = &res[k];
            let denied = v["ok"] == json!(false);
            add(
                &r,
                &format!("remote_denied_{}", k.trim_start_matches("deny_")),
                denied,
                if denied {
                    format!(
                        "rejected: {}",
                        v["e"].as_str().unwrap_or("").chars().take(160).collect::<String>()
                    )
                } else {
                    format!("NOT rejected: {v}")
                },
                None,
            );
        }
        let val = |k: &str| res[k]["ok"] == json!(false);
        add(
            &r,
            "validation_rejects_bad_args",
            val("bad_url") && val("bad_tab") && val("long_title") && val("bad_sym"),
            format!(
                "loopback url: {} · bad tab: {} · 121-char title: {} · bad sym: {}",
                res["bad_url"]["e"], res["bad_tab"]["e"], res["long_title"]["e"], res["bad_sym"]["e"]
            ),
            None,
        );
        let opened = shell.opened_external.lock().unwrap_or_else(|e| e.into_inner()).clone();
        add(
            &r,
            "open_external_routed",
            res["ok_external"]["ok"] == json!(true)
                && opened.iter().any(|u| u.contains("example.com/suryadhana-selftest")),
            format!(
                "recorded (not opened in self-test): {}",
                opened
                    .iter()
                    .map(|u| policy::redact_raw(u))
                    .collect::<Vec<_>>()
                    .join(", ")
            ),
            None,
        );
        let save = &res["save"];
        let path = save["r"]["path"].as_str().unwrap_or("");
        let p = PathBuf::from(path);
        let content_ok = std::fs::read_to_string(&p).map(|c| c == "a,b\n1,2\n").unwrap_or(false);
        let inside = p.parent() == Some(shell.paths.downloads_dir.as_path());
        let quarantined = crate::macos::quarantine_of(&p);
        add(
            &r,
            "save_download",
            save["ok"] == json!(true)
                && content_ok
                && inside
                && quarantined.is_some()
                && p.file_name().map(|n| n == "evil name_.csv").unwrap_or(false),
            format!(
                "{} (content ok: {content_ok}, inside Downloads: {inside}, quarantine: {quarantined:?})",
                if path.is_empty() {
                    save.to_string()
                } else {
                    path.to_string()
                }
            ),
            save["ms"].as_f64(),
        );
        let dl = shell.paths.downloads_dir.clone();
        let zip_ok = res["save_zip"]["ok"] == json!(true)
            && dl.join("NIFTY_levels.zip.txt").is_file()
            && !dl.join("NIFTY_levels.zip").exists();
        let cmd_ok = res["save_cmd"]["ok"] == json!(true)
            && dl.join("run.command.txt").is_file()
            && !dl.join("run.command").exists();
        add(
            &r,
            "download_extension_allowlist",
            zip_ok && cmd_ok,
            format!(
                "NIFTY_levels.zip -> {} · run.command -> {}",
                res["save_zip"]["r"]["path"].as_str().unwrap_or("?"),
                res["save_cmd"]["r"]["path"].as_str().unwrap_or("?")
            ),
            None,
        );
        let saved_note = shell
            .notifications
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .iter()
            .any(|n| n == "Saved to Downloads");
        add(
            &r,
            "download_feedback",
            saved_note && shell.downloads.latest().is_some(),
            format!(
                "'Saved to Downloads' notification: {saved_note}; File ▸ Show Latest Download target: {:?}",
                shell
                    .downloads
                    .latest()
                    .map(|p| p.file_name().map(|n| n.to_string_lossy().to_string()))
            ),
            None,
        );
        let perm = res["perm"]["r"].as_str().unwrap_or("");
        add(
            &r,
            "notification_permission",
            res["perm"]["ok"] == json!(true) && ["granted", "denied", "default"].contains(&perm),
            format!(
                "shell_notification_permission = {perm:?} (macOS UNUserNotificationCenter; same as the native check: {})",
                perm == crate::commands::notification_permission_now()
            ),
            None,
        );
    }

    // ---- 4b. downloads: the WebKit path (on_download) and the UI bridge path ----
    // (i) WebKit: a DETACHED <a download> + blob: click. The UI's bridge intercepts anchor clicks with a
    //     document-level capture listener, which a detached anchor never reaches, so this exercises the
    //     shell's on_download handler (destination, sanitized unique name, "finished" notification).
    // (ii) Bridge: the same click on an anchor IN the document. The platform bridge (when the UI build has
    //     it) turns it into shell_save_download; either way the file must land in Downloads (info).
    let dl_dir = shell.paths.downloads_dir.clone();
    let find_file = |prefix: &'static str| {
        let dir = dl_dir.clone();
        move || {
            std::fs::read_dir(&dir).ok().and_then(|rd| {
                rd.flatten().map(|e| e.path()).find(|p| {
                    p.file_name()
                        .map(|n| n.to_string_lossy().starts_with(prefix))
                        .unwrap_or(false)
                        && std::fs::metadata(p).map(|m| m.len() > 0).unwrap_or(false)
                })
            })
        }
    };
    let blob_click = |name: &str, attach: bool| {
        format!(
            "var a=document.createElement('a'); a.href=URL.createObjectURL(new Blob(['x,y\\n1,2\\n'],{{type:'text/csv'}})); a.download={}; {} return true",
            json!(name),
            if attach { "document.body.appendChild(a); a.click(); a.remove();" } else { "a.click();" }
        )
    };
    // data: downloads are refused (any frame can mint them, e.g. the TradingView iframe: C2-security-05)
    let _ = eval_json(
        &main,
        "var a=document.createElement('a'); a.href='data:application/zip;base64,UEsDBA=='; a.download='data_payload.zip'; a.click(); return true",
        Duration::from_secs(2),
    )
    .await;
    let _ = eval_json(&main, &blob_click("webkit export.csv", false), Duration::from_secs(2)).await;
    let t_dl = Instant::now();
    let webkit_file = find_file("webkit export");
    let mut dl_file = None;
    while dl_file.is_none() && t_dl.elapsed() < Duration::from_secs(6) {
        dl_file = webkit_file();
        if dl_file.is_none() {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
    let dl_ms = t_dl.elapsed().as_secs_f64() * 1000.0;
    // the file appears before WebKit reports the download finished: give the Finished event up to 2 s
    let t_note = Instant::now();
    let mut finished_note = false;
    while dl_file.is_some() && t_note.elapsed() < Duration::from_secs(2) {
        finished_note = shell
            .notifications
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .iter()
            .filter(|n| *n == "Saved to Downloads")
            .count()
            >= 4; // 3 from shell_save_download above + this one
        if finished_note {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    match dl_file {
        Some(f) => {
            let q = crate::macos::quarantine_of(&f);
            add(
                &r,
                "webkit_download",
                finished_note && q.is_some(),
                format!(
                    "detached <a download> blob saved by on_download to {} (finished notification: {finished_note}, quarantine: {q:?})",
                    f.display()
                ),
                Some(dl_ms),
            )
        }
        None => add(
            &r,
            "webkit_download",
            false,
            format!("no file from the detached blob download in {}", dl_dir.display()),
            None,
        ),
    }
    let data_files: Vec<String> = std::fs::read_dir(&dl_dir)
        .map(|rd| {
            rd.flatten()
                .map(|e| e.file_name().to_string_lossy().to_string())
                .filter(|n| n.starts_with("data_payload"))
                .collect()
        })
        .unwrap_or_default();
    let data_blocked = shell
        .blocked
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .any(|u| u.starts_with("data:"));
    let spurious = shell
        .notifications
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .any(|n| n.starts_with("Could not save"));
    add(
        &r,
        "webkit_download_data_url_refused",
        data_files.is_empty() && data_blocked && !spurious,
        format!(
            "data: <a download> -> files {data_files:?}; refused by on_download: {data_blocked}; failure notification for the refusal: {spurious}"
        ),
        None,
    );
    let notes_before = shell
        .notifications
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .filter(|n| *n == "Saved to Downloads")
        .count();
    let _ = eval_json(&main, &blob_click("bridge export.csv", true), Duration::from_secs(2)).await;
    let t_br = Instant::now();
    let bridge_file = find_file("bridge export");
    let mut br = None;
    while br.is_none() && t_br.elapsed() < Duration::from_secs(6) {
        br = bridge_file();
        if br.is_none() {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }
    }
    tokio::time::sleep(Duration::from_millis(300)).await;
    let notes_after = shell
        .notifications
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .filter(|n| *n == "Saved to Downloads")
        .count();
    let via = if notes_after > notes_before {
        "a saved download (bridge -> shell_save_download, or WebKit on_download without the bridge)"
    } else {
        "no saved-download notification"
    };
    match br {
        Some(f) => add(
            &r,
            "bridge_download (info)",
            true,
            format!("in-document <a download> saved to {} via {via}", f.display()),
            Some(t_br.elapsed().as_secs_f64() * 1000.0),
        ),
        None => add(
            &r,
            "bridge_download (info)",
            true,
            "in-document <a download> produced no file (UI handled it otherwise)".to_string(),
            None,
        ),
    }

    // R-RUST-03 (round 3): two clicks on ONE blob URL at once (a double-clicked export): WebKit names both
    // downloads by the URL only, so the shell admits one at a time; whatever lands must be quarantined (checked
    // below with every other file) and a refused second one says why
    let _ = eval_json(
        &main,
        "var u=URL.createObjectURL(new Blob([new Array(400001).join('x')],{type:'text/csv'})); for (var i=0;i<2;i++){var a=document.createElement('a'); a.href=u; a.download='double click.csv'; a.click();} return true",
        Duration::from_secs(2),
    )
    .await;
    tokio::time::sleep(Duration::from_millis(1500)).await;
    let doubles = std::fs::read_dir(&dl_dir)
        .map(|rd| {
            rd.flatten()
                .filter(|e| e.file_name().to_string_lossy().starts_with("double click"))
                .count()
        })
        .unwrap_or(0);
    let refused_second = shell
        .notifications
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .any(|n| n == "Could not save double click.csv");
    add(
        &r,
        "webkit_download_same_url_twice (info)",
        true,
        format!(
            "two clicks on one blob URL: {doubles} file(s) saved; second refused while the first was in flight: {refused_second} (both files would be quarantined below either way)"
        ),
        None,
    );

    // every file the shell wrote into Downloads carries com.apple.quarantine
    let untagged: Vec<String> = std::fs::read_dir(&dl_dir)
        .map(|rd| {
            rd.flatten()
                .map(|e| e.path())
                .filter(|p| crate::macos::quarantine_of(p).is_none())
                .map(|p| p.file_name().unwrap_or_default().to_string_lossy().to_string())
                .collect()
        })
        .unwrap_or_default();
    let count = std::fs::read_dir(&dl_dir).map(|rd| rd.count()).unwrap_or(0);
    add(
        &r,
        "downloads_quarantined",
        untagged.is_empty() && count >= 4,
        format!("{count} file(s) in Downloads; without com.apple.quarantine: {untagged:?}"),
        None,
    );

    // ---- 5. shell -> UI events ----
    let t_events = Instant::now();
    let _ = eval_json(&main, "window.__SDEV=[]; window.__SDST_AT=[]; window.addEventListener('suryadhana:shell', function(e){ window.__SDEV.push(e.detail); if (e.detail && e.detail.type==='status') window.__SDST_AT.push(Date.now()); }); return true", Duration::from_secs(2)).await;
    let snap = shell.health.snapshot();
    windows::send_event(&app, MAIN, &json!({"type": "status", "status": snap.status}));
    windows::goto(&app, "desk");
    let (ev, ms) = poll_js(
        &main,
        "return {ev: window.__SDEV || [], href: location.href}",
        Duration::from_secs(3),
        Duration::from_millis(50),
        |v| {
            let types: Vec<&str> = v["ev"]
                .as_array()
                .map(|a| a.iter().filter_map(|e| e["type"].as_str()).collect())
                .unwrap_or_default();
            types.contains(&"status") && types.contains(&"goto")
        },
    )
    .await;
    // contract K3: ⌘= / ⌘0 publish the window's zoom to the page (event + variable)
    windows::zoom(&app, Some(0.1));
    let (zv, _) = poll_js(
        &main,
        "return {ev: (window.__SDEV||[]).filter(function(e){return e && e.type==='zoom'}), v: window.__SURYADHANA_ZOOM__}",
        Duration::from_secs(3),
        Duration::from_millis(50),
        |v| v["ev"].as_array().map(|a| !a.is_empty()).unwrap_or(false),
    )
    .await;
    windows::zoom(&app, None);
    let (zr, _) = poll_js(
        &main,
        "return {ev: (window.__SDEV||[]).filter(function(e){return e && e.type==='zoom'}), v: window.__SURYADHANA_ZOOM__}",
        Duration::from_secs(3),
        Duration::from_millis(50),
        |v| v["ev"].as_array().map(|a| a.len() >= 2).unwrap_or(false),
    )
    .await;
    let zv = zv.unwrap_or(Value::Null);
    let zr = zr.unwrap_or(Value::Null);
    let zoom_ok = zv["ev"][0]["factor"].as_f64() == Some(1.1)
        && zr["ev"][1]["factor"].as_f64() == Some(1.0)
        && zr["v"].as_f64() == Some(1.0)
        && windows::zoom_of(&app, MAIN) == 1.0;
    add(
        &r,
        "zoom_published",
        zoom_ok,
        format!(
            "zoom in -> {} ; actual size -> {} (window.__SURYADHANA_ZOOM__ = {})",
            zv["ev"], zr["ev"], zr["v"]
        ),
        None,
    );
    let ev = ev.unwrap_or(Value::Null);
    let types: Vec<String> = ev["ev"]
        .as_array()
        .map(|a| a.iter().filter_map(|e| e["type"].as_str().map(String::from)).collect())
        .unwrap_or_default();
    add(
        &r,
        "shell_events_delivered",
        types.contains(&"status".into()) && types.contains(&"goto".into()),
        format!("received {types:?}"),
        Some(ms),
    );
    tokio::time::sleep(Duration::from_millis(600)).await;
    let href = eval_json(&main, "return location.href", Duration::from_secs(2))
        .await
        .unwrap_or(Value::Null);
    let bridged = href.as_str().map(|h| h.contains("tab=desk")).unwrap_or(false);
    add(
        &r,
        "ui_bridge_goto (info)",
        true,
        if bridged {
            "UI handled goto -> tab=desk".to_string()
        } else {
            format!("UI did not switch page (no platform bridge in this UI build?): {href}")
        },
        None,
    );

    // ---- 6. new window via shell_new_window ----
    // contract K4: a deep link with a stock symbol (M&M: the & must arrive URL-encoded)
    let _ = eval_json(&main, "window.__SDNW=null; window.__TAURI_INTERNALS__.invoke('shell_new_window',{tab:'risk', sym:'M&M'}).then(function(r){window.__SDNW={ok:true,r:r}},function(e){window.__SDNW={ok:false,e:String(e)}}); return true", Duration::from_secs(2)).await;
    let t_nw = Instant::now();
    let (nw, _) = poll_js(
        &main,
        "return window.__SDNW",
        Duration::from_secs(5),
        Duration::from_millis(50),
        |v| !v.is_null(),
    )
    .await;
    let nw = nw.unwrap_or(Value::Null);
    match nw["r"]["label"].as_str().map(String::from) {
        Some(label) => {
            let mut loaded = None;
            while t_nw.elapsed() < Duration::from_secs(15) && Instant::now() < deadline {
                let phase = shell
                    .windows
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .get(&label)
                    .map(|w| w.phase);
                if phase == Some(Phase::Terminal) {
                    loaded = Some(t_nw.elapsed().as_secs_f64() * 1000.0);
                    break;
                }
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            let url = app
                .get_webview_window(&label)
                .and_then(|w| crate::windows::webview_url(&w))
                .map(|u| u.to_string())
                .unwrap_or_default();

            // session persistence (AC-7), against the isolated state files: save the live window set the
            // way ⌘Q / the 60 s timer do, read it back, plan the restore, and save the per-label geometry
            windows::save_session(&app);
            let saved = windows::Session::load(&shell.paths.state_file);
            let plan = windows::restore_plan(&saved, &shell.cfg.ui_url);
            let saved_term = saved
                .windows
                .iter()
                .any(|w| w.label == label && w.url.contains("tab=risk"));
            let saved_main = saved.windows.first().map(|w| w.label == MAIN).unwrap_or(false);
            let plan_ok = plan.first().map(|(l, _)| l == MAIN).unwrap_or(false)
                && plan.iter().any(|(l, t)| *l == label && t.contains("tab=risk"));
            let geo = app.save_window_state(StateFlags::all());
            let geo_text = std::fs::read_to_string(&shell.paths.window_state_file).unwrap_or_default();
            let geo_ok = geo.is_ok() && geo_text.contains("\"main\"") && geo_text.contains(&format!("\"{label}\""));
            add(
                &r,
                "session_persistence",
                saved_main && saved_term && plan_ok && geo_ok,
                format!(
                    "saved windows {:?} -> restore plan {:?}; geometry per label saved: {geo_ok}",
                    saved
                        .windows
                        .iter()
                        .map(|w| format!(
                            "{} {} tab={}",
                            w.label,
                            policy::redact_raw(&w.url),
                            windows::tab_of(&w.url).unwrap_or("?")
                        ))
                        .collect::<Vec<_>>(),
                    plan
                ),
                None,
            );

            if let Some(w) = app.get_webview_window(&label) {
                let _ = w.close();
            }
            let t_close = Instant::now();
            while app.get_webview_window(&label).is_some() && t_close.elapsed() < Duration::from_secs(5) {
                tokio::time::sleep(Duration::from_millis(50)).await;
            }
            let closed = app.get_webview_window(&label).is_none();
            add(
                &r,
                "new_window_open_close",
                loaded.is_some() && closed && url.contains("tab=risk&sym=M%26M"),
                format!(
                    "{label} loaded {url} in {:?} ms; closed: {closed}",
                    loaded.map(|m| m.round())
                ),
                loaded,
            );
        }
        None => add(
            &r,
            "new_window_open_close",
            false,
            format!("shell_new_window failed: {nw}"),
            None,
        ),
    }

    // status heartbeat (C1-desktop-native-03): with nothing changing, events still arrive at <= 10 s
    // spacing (ui/components/desktop/status.ts SHELL_STATUS_MAX_INTERVAL_MS)
    while t_events.elapsed() < Duration::from_secs(19) && Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    let at = eval_json(&main, "return window.__SDST_AT || []", Duration::from_secs(2))
        .await
        .unwrap_or(Value::Null);
    let stamps: Vec<f64> = at
        .as_array()
        .map(|a| a.iter().filter_map(Value::as_f64).collect())
        .unwrap_or_default();
    let max_gap = stamps.windows(2).map(|w| w[1] - w[0]).fold(0.0, f64::max);
    let span = t_events.elapsed().as_secs_f64();
    add(
        &r,
        "status_heartbeat",
        stamps.len() >= 2 && max_gap <= 10_500.0,
        format!(
            "{} status events in {span:.0} s, largest gap {:.1} s (contract: <= 10 s)",
            stamps.len(),
            max_gap / 1000.0
        ),
        Some(max_gap),
    );

    // ---- 6a. File ▸ Print… (round 4b, R9) ----
    print_check(&app, &main, &r, opts).await;

    // ---- 6b. a crashed page recovers (round 3, completeness-final-03) ----
    // SIGKILL the main window's WebKit content process (what a WebKit crash, a GPU-process reset or a kill under
    // memory pressure does); the shell must log it, reload the window at its URL and tell the owner once.
    crash_recovery_check(&app, &main, &r, deadline).await;

    // ---- 7. navigation guards (last: they try to move the page) ----
    let on_terminal = |app: &AppHandle| {
        app.get_webview_window(MAIN)
            .and_then(|w| crate::windows::webview_url(&w))
            .map(|u| policy::same_ui_origin(&u, &app.state::<Shell>().cfg.ui_url))
            .unwrap_or(false)
    };
    let before_ext = shell.opened_external.lock().unwrap_or_else(|e| e.into_inner()).len();
    let before_blocked = shell.blocked.lock().unwrap_or_else(|e| e.into_inner()).len();
    let mut stayed = vec![];
    for target in [
        "https://example.org/suryadhana-nav-test?secret=1",
        "file:///etc/hosts",
        "tauri://localhost/index.html",
        "http://127.0.0.1:8001/health",
        "javascript:void(0)",
    ] {
        let _ = eval_json(
            &main,
            &format!("location.href = {}; return true", json!(target)),
            Duration::from_secs(2),
        )
        .await;
        tokio::time::sleep(Duration::from_millis(500)).await;
        stayed.push((policy::redact_raw(target), on_terminal(&app)));
    }
    let _ = eval_json(
        &main,
        "window.open('https://example.net/suryadhana-popup-test','_blank'); return true",
        Duration::from_secs(2),
    )
    .await;
    tokio::time::sleep(Duration::from_millis(800)).await;
    let still = on_terminal(&app) && stayed.iter().all(|(_, s)| *s);
    let ext: Vec<String> = shell.opened_external.lock().unwrap_or_else(|e| e.into_inner())[before_ext..]
        .iter()
        .map(|u| policy::redact_raw(u))
        .collect();
    let blocked: Vec<String> = shell.blocked.lock().unwrap_or_else(|e| e.into_inner())[before_blocked..].to_vec();
    let ext_ok = ext.iter().any(|u| u.contains("example.org")) && ext.iter().any(|u| u.contains("example.net"));
    // file: and javascript: are refused by WebKit itself before the policy is asked; the boot page and
    // other loopback services must be refused by the shell's policy.
    let blocked_ok = blocked.iter().any(|u| u.starts_with("tauri://")) && blocked.iter().any(|u| u.contains(":8001"));
    add(&r, "navigation_guard", still && ext_ok && blocked_ok, format!("main stayed on the terminal after each attempt: {stayed:?}; opened in browser: {ext:?}; blocked by policy: {blocked:?}"), None);
    // The terminal origin under its alias spelling (localhost <-> 127.0.0.1) has no IPC grant: the shell
    // must load the canonical spelling instead, where IPC works.
    let ui = shell.cfg.ui_url.clone();
    let alias_host = if ui.host_str() == Some("localhost") {
        "127.0.0.1"
    } else {
        "localhost"
    };
    let alias = format!(
        "http://{alias_host}:{}/?tab=system",
        ui.port_or_known_default().unwrap_or(80)
    );
    let _ = eval_json(
        &main,
        &format!("location.href = {}; return true", json!(alias)),
        Duration::from_secs(2),
    )
    .await;
    let t_alias = Instant::now();
    let mut alias_url = String::new();
    while t_alias.elapsed() < Duration::from_secs(8) && Instant::now() < deadline {
        let phase = shell
            .windows
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(MAIN)
            .map(|w| w.phase);
        alias_url = crate::windows::webview_url(&main)
            .map(|u| u.to_string())
            .unwrap_or_default();
        if phase == Some(Phase::Terminal) && alias_url.contains("tab=system") {
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    let (ipc_after, _) = poll_js(
        &main,
        "if(!window.__SDA){window.__SDA={p:true}; window.__TAURI_INTERNALS__.invoke('shell_info').then(function(r){window.__SDA={ok:true}},function(e){window.__SDA={ok:false,e:String(e)}});} return window.__SDA",
        Duration::from_secs(4),
        Duration::from_millis(100),
        |v| v.get("ok").is_some(),
    )
    .await;
    let canonical = Url::parse(&alias_url)
        .map(|u| policy::exact_ui_origin(&u, &ui))
        .unwrap_or(false);
    let ipc_ok = ipc_after.as_ref().map(|v| v["ok"] == json!(true)).unwrap_or(false);
    add(
        &r,
        "alias_origin_canonicalized",
        canonical && alias_url.contains("tab=system") && ipc_ok,
        format!(
            "{} -> {} (exact configured origin: {canonical}); shell_info there: {}",
            policy::redact_raw(&alias),
            policy::redact_raw(&alias_url),
            ipc_after.unwrap_or(Value::Null)
        ),
        Some(t_alias.elapsed().as_secs_f64() * 1000.0),
    );
    // Go ▸ Back (⌘[) never leaves the terminal: the step before the first terminal entry is the boot page,
    // which the policy refuses without a shell permit
    windows::history(&app, true);
    tokio::time::sleep(Duration::from_millis(900)).await;
    windows::history(&app, true);
    tokio::time::sleep(Duration::from_millis(900)).await;
    let after_back = crate::windows::webview_url(&main)
        .map(|u| u.to_string())
        .unwrap_or_default();
    let still_terminal = Url::parse(&after_back)
        .map(|u| policy::exact_ui_origin(&u, &ui))
        .unwrap_or(false);
    add(
        &r,
        "history_back_stays_in_terminal",
        still_terminal,
        format!("after two Back steps main shows {}", policy::redact_raw(&after_back)),
        None,
    );
    let wins = app.webview_windows().len();
    add(
        &r,
        "no_stray_windows",
        wins == 1,
        format!("{wins} window(s) open after the guard tests"),
        None,
    );

    feed_check(&app, &r, deadline).await;
    common_checks(&app, &r, autostart_before).await;
}

/// Round 4b (R9): Print… on the terminal window opens WebKit's print panel as a sheet on that window; a second
/// ⌘P while it is up is refused; Cancel closes it and nothing is printed. Belt and braces: the app's shared print
/// info is first set to SAVE as a PDF in the self-test's temp dir, so even a confirmed panel never reaches paper.
async fn print_check(app: &AppHandle, main: &WebviewWindow, r: &Shared, opts: &Options) {
    let pdf = opts.temp_dir.join("print-check.pdf");
    let (tx, rx) = std::sync::mpsc::channel::<bool>();
    let pdf2 = pdf.clone();
    let hop = app.run_on_main_thread(move || {
        let _ = tx.send(crate::macos::selftest_print_to_file(&pdf2));
    });
    let to_file = hop.is_ok() && rx.recv_timeout(Duration::from_secs(2)).unwrap_or(false);
    if !to_file {
        // never open a print panel that could reach a printer
        add(
            r,
            "print_panel",
            false,
            "could not point the print job at a temp PDF; print not tried",
            None,
        );
        return;
    }
    let t0 = Instant::now();
    let first = windows::print_window(app, MAIN);
    let mut sheet_ms = None;
    while first.is_ok() && t0.elapsed() < Duration::from_secs(5) {
        if windows::webview_sheet(main) == Some(true) {
            sheet_ms = Some(t0.elapsed().as_secs_f64() * 1000.0);
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    let second = windows::print_window(app, MAIN);
    let cancelled = sheet_ms.is_some() && windows::cancel_sheet(main);
    let t1 = Instant::now();
    let mut gone = false;
    while t1.elapsed() < Duration::from_secs(4) {
        if windows::webview_sheet(main) == Some(false) {
            gone = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    tokio::time::sleep(Duration::from_millis(300)).await;
    let printed = pdf.exists();
    add(
        r,
        "print_panel",
        first.is_ok() && sheet_ms.is_some() && second.is_err() && cancelled && gone && !printed,
        format!(
            "Print… on the terminal: {first:?}; print panel as a sheet on the window: {}; a second Print… while it is up: {second:?}; Cancel: {cancelled}, sheet gone: {gone}; job file written: {printed} (must be false)",
            sheet_ms
                .map(|m| format!("yes after {m:.0} ms"))
                .unwrap_or_else(|| "NO".into())
        ),
        sheet_ms,
    );
}

/// The `WKWebView`'s current WebContent pid (main thread hop; None when the SPI is unavailable).
async fn content_pid(w: &WebviewWindow) -> Option<i32> {
    let (tx, rx) = tokio::sync::oneshot::channel::<Option<i32>>();
    let tx = Mutex::new(Some(tx));
    w.with_webview(move |pw| {
        let pid = crate::macos::web_content_pid(pw.inner());
        if let Some(tx) = tx.lock().unwrap_or_else(|e| e.into_inner()).take() {
            let _ = tx.send(pid);
        }
    })
    .ok()?;
    tokio::time::timeout(Duration::from_secs(2), rx).await.ok()?.ok()?
}

/// completeness-final-03: kill the page's content process; the window must come back by itself.
async fn crash_recovery_check(app: &AppHandle, main: &WebviewWindow, r: &Shared, deadline: Instant) {
    let shell = app.state::<Shell>();
    let Some(pid) = content_pid(main).await else {
        skip(
            r,
            "webcontent_crash_recovers",
            "WebKit's _webProcessIdentifier is not available: the page's content process cannot be found",
        );
        return;
    };
    // the page it shows: after the kill the window must come back to the SAME tab (WebKit resets the URL to nil,
    // so the shell reloads the page its status broadcast last saw)
    let before = eval_json(main, "return location.search", Duration::from_secs(2))
        .await
        .and_then(|v| v.as_str().map(str::to_string))
        .unwrap_or_default();
    let tab_before = windows::tab_of(&before);
    let t_kill = Instant::now();
    // SAFETY: SIGKILL to this app's own WebContent helper (same user); no memory is touched.
    let rc = unsafe { libc::kill(pid, libc::SIGKILL) };
    let state = |app: &AppHandle| {
        app.state::<Shell>()
            .windows
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(MAIN)
            .map(|w| (w.crashes.len(), w.phase, w.committed_at, w.crash_hold))
    };
    let mut recovered = None;
    while t_kill.elapsed() < Duration::from_secs(12) && Instant::now() < deadline {
        if let Some((n, phase, committed, _)) = state(app) {
            if n >= 1 && phase == Phase::Terminal && committed.map(|c| c > t_kill).unwrap_or(false) {
                recovered = Some(t_kill.elapsed().as_secs_f64() * 1000.0);
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    // the reloaded page runs scripts again, in a new content process
    let (alive, _) = poll_js(
        main,
        "return {href: location.href, tabs: document.querySelectorAll('[data-tab]').length}",
        Duration::from_secs(5),
        Duration::from_millis(100),
        |v| v["tabs"].as_u64().unwrap_or(0) > 0,
    )
    .await;
    let new_pid = content_pid(main).await;
    let tab_after = alive
        .as_ref()
        .and_then(|v| v["href"].as_str())
        .and_then(|h| h.split_once('?').map(|(_, q)| format!("?{q}")))
        .and_then(|q| windows::tab_of(&q));
    let noted = shell
        .notifications
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .any(|n| n == "SuryaDhana reloaded a window");
    let st = state(app);
    let ok = rc == 0
        && recovered.is_some()
        && alive
            .as_ref()
            .map(|v| v["tabs"].as_u64().unwrap_or(0) > 0)
            .unwrap_or(false)
        && new_pid.is_some()
        && new_pid != Some(pid)
        && noted
        && tab_before.is_some()
        && tab_after == tab_before
        && st.map(|(_, _, _, hold)| !hold).unwrap_or(false);
    add(
        r,
        "webcontent_crash_recovers",
        ok,
        format!(
            "killed WebContent pid {pid} (kill rc {rc}); window back on the terminal after {:?} ms in content process {new_pid:?}; same page: {tab_before:?} -> {tab_after:?}; page alive: {}; 'SuryaDhana reloaded a window' notice: {noted}; registry {st:?}",
            recovered.map(|m| m.round()),
            alive.unwrap_or(Value::Null)
        ),
        recovered,
    );
}

/// K5: the stack's notification feed becomes native banners: nothing old on a first start, the new event
/// once, an event older than 30 min never. Strict against desktop/scripts/stub_backend.py (its feed is
/// recognisable); against another backend it reports what it saw (info).
async fn feed_check(app: &AppHandle, r: &Shared, deadline: Instant) {
    let shell = app.state::<Shell>();
    let url = match shell.cfg.ui_url.join(crate::feed::FEED_PATH) {
        Ok(u) => u,
        Err(_) => return,
    };
    let first = shell.health.get_json_status(&url, Duration::from_secs(3)).await;
    let stub = matches!(&first, Ok((200, Some(v))) if v.to_string().contains("SELFTEST replay"));
    let titles = |app: &AppHandle| -> Vec<String> {
        app.state::<Shell>()
            .notifications
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .iter()
            .filter(|n| n.contains("SELFTEST") || n.contains("more SuryaDhana alert"))
            .cloned()
            .collect()
    };
    if !stub {
        add(
            r,
            "feed_notifications (info)",
            true,
            format!(
                "{} answered {:?}: not the stub feed, so only reported; feed banners recorded: {:?}",
                crate::feed::FEED_PATH,
                first.as_ref().map(|(c, _)| *c),
                titles(app)
            ),
            None,
        );
        return;
    }
    // the stub announces its fresh event only once the shell holds a cursor (second poll, ~15 s apart)
    while !titles(app).iter().any(|t| t == "SELFTEST feed alert") && Instant::now() < deadline {
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    // a few more polls see the fresh event again (the server's 60 s overlap): it must not be announced twice
    let t_more = Instant::now();
    let until = deadline.checked_sub(Duration::from_secs(4)).unwrap_or(deadline);
    while t_more.elapsed() < Duration::from_secs(16) && Instant::now() < until {
        tokio::time::sleep(Duration::from_millis(250)).await;
    }
    let seen = titles(app);
    let cursor = crate::feed::Cursor::load(&shell.paths.feed.cursor);
    let cur_ok = cursor
        .as_ref()
        .map(|c| c.since.is_some() && c.has("n-selftest-fresh") && c.has("n-selftest-wrap"))
        .unwrap_or(false);
    let ok = seen == vec!["SELFTEST feed alert".to_string()]
        && cur_ok
        && shell.paths.feed.alive.is_none()
        && shell.paths.feed.cursor.starts_with(std::env::temp_dir());
    add(
        r,
        "feed_notifications",
        ok,
        format!(
            "banners from the feed: {seen:?} (expected exactly the fresh one, once: never the 2 old events of the first start, never the 2-hour-old one, never the inbox-only wrap, never twice through the 60 s overlap); cursor since {:?}, {} seen id(s), kept in the self-test's temp dir",
            cursor.as_ref().and_then(|c| c.since),
            cursor.as_ref().map(|c| c.seen.len()).unwrap_or(0)
        ),
        None,
    );
}

/// What the boot page shows (state, visible actions, red heading, texts).
const BOOT_VIEW_JS: &str = "var a=document.getElementById('actions'); var vis=function(id){var e=document.getElementById(id); return !!e && !e.hidden && !(a && a.hidden && a.contains(e));}; var h=document.getElementById('mode'); return {state: document.body.dataset.state, actions: !!a && !a.hidden, start: vis('btn-start'), stop: vis('btn-stop'), red: !!h && getComputedStyle(h).color === 'rgb(239, 68, 68)', rows: document.querySelectorAll('[data-svc]').length, progress: (document.getElementById('progress')||{}).textContent, message: (document.getElementById('message')||{}).textContent, remedy: (document.getElementById('remedy')||{}).textContent || ''}";

/// Checks when the terminal never loaded: the boot page must explain why — the start-up grace (no red,
/// no Start/Stop), the missing UI release (build-ui / rollback, no Start/Stop), the port-squatting
/// refusal, or the down state with its actions after 15 s.
async fn down_state_checks(app: &AppHandle, main: &WebviewWindow, r: &Shared, deadline: Instant, early: &Value) {
    let shell = app.state::<Shell>();
    let snap = shell.health.snapshot();
    let refresh = || async {
        let _ = eval_json(
            main,
            "if (window.__sdBootRefresh) window.__sdBootRefresh(); return true",
            Duration::from_secs(2),
        )
        .await;
        tokio::time::sleep(Duration::from_millis(800)).await;
        eval_json(main, BOOT_VIEW_JS, Duration::from_secs(2))
            .await
            .unwrap_or(Value::Null)
    };
    // PM 25 Oct: a ui-api that holds its port but does not answer is NOT RESPONDING, never "starting" (even
    // inside the login grace or a watchdog run) and never offers Start
    if snap.ui_state == UiState::NotResponding {
        let v = refresh().await;
        let ok = v["state"] == json!("notresponding")
            && v["start"] == json!(false)
            && v["remedy"]
                .as_str()
                .map(|t| t.contains("./start-local.sh restart ui-api"))
                .unwrap_or(false);
        add(
            r,
            "boot_not_responding_state",
            ok,
            format!(
                "login start: {} · boot page state={} start_visible={} progress={} remedy={}",
                shell.login_start, v["state"], v["start"], v["progress"], v["remedy"]
            ),
            None,
        );
        return;
    }
    if shell.login_start {
        let ok = early["state"] == json!("starting")
            && early["start"] == json!(false)
            && early["stop"] == json!(false)
            && early["red"] == json!(false);
        add(
            r,
            "boot_startup_grace",
            ok,
            format!(
                "login start, {} s grace: early boot page state={} start_visible={} stop_visible={} red={} progress={}",
                shell.cfg.startup_grace_secs,
                early["state"],
                early["start"],
                early["stop"],
                early["red"],
                early["progress"]
            ),
            None,
        );
        if shell.cfg.startup_grace_secs > 25 {
            return; // the grace outlives the self-test: the down state is not reachable here
        }
        while shell.starting(&shell.health.snapshot().stack).is_some() && Instant::now() < deadline {
            tokio::time::sleep(Duration::from_millis(200)).await;
        }
    }
    match snap.ui_state {
        UiState::NoRelease => {
            let v = refresh().await;
            let ok = v["state"] == json!("norelease")
                && v["start"] == json!(false)
                && v["stop"] == json!(false)
                && v["remedy"]
                    .as_str()
                    .map(|t| t.contains("build-ui") && t.contains("--rollback"))
                    .unwrap_or(false);
            add(
                r,
                "boot_no_release_state",
                ok,
                format!(
                    "boot page state={} start_visible={} stop_visible={} remedy={}",
                    v["state"], v["start"], v["stop"], v["remedy"]
                ),
                None,
            );
            return;
        }
        UiState::Untrusted => {
            let v = refresh().await;
            let ok = v["state"] == json!("untrusted")
                && v["start"] == json!(false)
                && crate::windows::webview_url(main)
                    .map(|u| crate::policy::is_boot_origin(&u))
                    .unwrap_or(false);
            add(
                r,
                "boot_untrusted_listener",
                ok,
                format!(
                    "boot page state={} detail={:?} message={}",
                    v["state"], snap.ui_detail, v["message"]
                ),
                None,
            );
            return;
        }
        // round 3 (R-RUST-02): a listener whose executable was deleted and that was never verified
        UiState::Unverifiable => {
            let v = refresh().await;
            let ok = v["state"] == json!("unverifiable")
                && v["start"] == json!(false)
                && v["remedy"]
                    .as_str()
                    .map(|t| t.contains("./start-local.sh restart ui-api"))
                    .unwrap_or(false)
                && crate::windows::webview_url(main)
                    .map(|u| crate::policy::is_boot_origin(&u))
                    .unwrap_or(false);
            add(
                r,
                "boot_unverifiable_listener",
                ok,
                format!(
                    "boot page state={} detail={:?} remedy={}",
                    v["state"], snap.ui_detail, v["remedy"]
                ),
                None,
            );
            return;
        }
        _ => {}
    }
    let need = Duration::from_secs(17);
    while shell
        .health
        .snapshot()
        .unready_since
        .map(|t| t.elapsed() < need)
        .unwrap_or(true)
        && Instant::now() < deadline
    {
        tokio::time::sleep(Duration::from_millis(200)).await;
    }
    // ask the page to re-render now (its 1 s timer is throttled while the window is hidden / screen locked)
    let v = refresh().await;
    let ok = v["state"] == json!("down") && v["actions"] == json!(true) && v["rows"].as_u64() == Some(3);
    add(
        r,
        "boot_down_state",
        ok,
        format!(
            "boot page state={} actions_visible={} service_rows={} progress={}",
            v["state"], v["actions"], v["rows"], v["progress"]
        ),
        None,
    );
}

async fn common_checks(app: &AppHandle, r: &Shared, autostart_before: Option<bool>) {
    let shell = app.state::<Shell>();
    if let Some(m) = app.menu() {
        let (tabs, edit_ok, shortcuts) = menu::introspect(&m);
        add(
            r,
            "menu_go_42_pages",
            tabs == 42 && shortcuts == 9,
            format!("{tabs} distinct pages in Go submenus, {shortcuts} ⌘1–⌘9 items"),
            None,
        );
        add(
            r,
            "menu_edit_clipboard",
            edit_ok,
            "predefined Cut/Copy/Paste/Select All present",
            None,
        );
    } else {
        add(r, "menu_go_42_pages", false, "no app menu", None);
    }
    // round 4b (R9): the real NSMenu key equivalents: ⌘P is Print…, and nothing takes plain ⌘F (the page's find
    // bar gets it; ⌃⌘F is Enter Full Screen)
    let (tx, rx) = std::sync::mpsc::channel();
    let keys = match app.run_on_main_thread(move || {
        let _ = tx.send(crate::macos::menu_key_equivalents());
    }) {
        Ok(()) => rx.recv_timeout(Duration::from_secs(2)).unwrap_or_default(),
        Err(_) => vec![],
    };
    let cmd_p: Vec<&String> = keys
        .iter()
        .filter(|(_, k, m)| k == "p" && m & 0x1E_0000 == crate::macos::MOD_COMMAND)
        .map(|(t, _, _)| t)
        .collect();
    let cmd_f: Vec<&String> = keys
        .iter()
        .filter(|(_, k, m)| crate::macos::is_plain_cmd_f(k, *m))
        .map(|(t, _, _)| t)
        .collect();
    add(
        r,
        "menu_print_and_find_keys",
        !keys.is_empty() && cmd_p == vec!["Print…"] && cmd_f.is_empty(),
        format!(
            "{} key equivalents in the menu bar; ⌘P -> {cmd_p:?}; plain ⌘F -> {cmd_f:?} (must be none: the page's find bar)",
            keys.len()
        ),
        None,
    );
    let tray_ok = app.tray_by_id(tray::TRAY_ID).is_some();
    let title = shell
        .tray_handles()
        .map(|t| t.last_title.lock().unwrap_or_else(|e| e.into_inner()).clone())
        .unwrap_or_default();
    add(
        r,
        "tray_present",
        tray_ok,
        format!("menu-bar item present, title {title:?}"),
        None,
    );
    let after = Some(crate::autostart_state(app).checked());
    add(
        r,
        "autostart_state (read-only)",
        after == autostart_before,
        format!(
            "launch at login: {} (unchanged by the self-test: {})",
            after
                .map(|b| if b { "enabled" } else { "disabled" })
                .unwrap_or("unknown"),
            after == autostart_before
        ),
        None,
    );
    let perm = tokio::task::spawn_blocking(crate::commands::notification_permission_now)
        .await
        .unwrap_or("default");
    add(
        r,
        "notification_permission_state",
        true,
        format!(
            "macOS reports {perm:?} for this app (UNUserNotificationCenter; 'default' = not decided yet / unknown)"
        ),
        None,
    );
    let snap = shell.health.snapshot();
    // round 4b: the menu-bar item's ICICI line follows ui-api's error_kind (P4), its title lets a fresh NSE print
    // beat the calendar (R10), and its notification hint follows macOS's answer
    if let Some(t) = shell.tray_handles() {
        let line = t.icici.text().unwrap_or_default();
        let want = tray::icici_line(snap.icici_view);
        let outage_ok = snap.icici_view != crate::health::IciciView::Unreachable
            || (!line.contains("/login") && !line.contains("expired"));
        add(
            r,
            "tray_icici_line",
            line == want && outage_ok,
            format!("{line:?} for {:?} (contract {:?})", snap.icici_view, snap.status.icici),
            None,
        );
        let fresh = snap
            .quote
            .map(|q| crate::health::fresh_print(q.at, time::OffsetDateTime::now_utc()))
            .unwrap_or(false);
        let title = t.last_title.lock().unwrap_or_else(|e| e.into_inner()).clone();
        let detail = format!(
            "quote {:?} at {:?}: {:?}; menu-bar title {title:?}",
            snap.quote.map(|q| q.nifty.last),
            snap.quote.and_then(|q| q.at),
            snap.quote_state
        );
        if fresh {
            add(
                r,
                "tray_fresh_print_is_live",
                snap.quote_state == crate::health::QuoteState::Live
                    && (!shell.cfg.nifty_in_menubar || !title.contains("closed")),
                format!("an NSE print from the last 3 min (special session rule): {detail}"),
                None,
            );
        } else {
            add(
                r,
                "tray_fresh_print_is_live (info)",
                true,
                format!("no fresh print to judge: {detail}"),
                None,
            );
        }
        let auth = *shell.notif_auth.lock().unwrap_or_else(|e| e.into_inner());
        let shown = t.notif_hint_shown.load(std::sync::atomic::Ordering::SeqCst);
        let opened = shell
            .opened_external
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .iter()
            .any(|u| u.contains("system-settings"));
        add(
            r,
            "notification_hint",
            shown == (auth == Some(crate::macos::NotifAuth::Denied)) && !opened,
            format!(
                "macOS says {:?}; tray line {:?} {}; System Settings opened without a click: {opened}",
                auth.map(|a| a.as_permission()),
                tray::NOTIF_HINT_TEXT,
                if shown { "shown" } else { "not shown" }
            ),
            None,
        );
    } else {
        add(r, "tray_icici_line", false, "no tray handles", None);
    }
    add(
        r,
        "health_snapshot (info)",
        true,
        format!(
            "ui-api {} · data-service {} · master-controller {} · icici {:?} · ui_build {:?} · nifty {:?} · polls {}",
            snap.status.ui_api.up,
            snap.status.data_service.up,
            snap.status.master_controller.up,
            snap.status.icici,
            snap.status.ui_build,
            snap.status.nifty,
            snap.polls
        ),
        None,
    );
    let freeze = policy::freeze_window_at(time::OffsetDateTime::now_utc());
    add(
        r,
        "freeze_guard (info)",
        true,
        format!(
            "IST {} · {}",
            policy::ist_clock(time::OffsetDateTime::now_utc()),
            freeze
                .map(|w| format!("inside {}", w.label))
                .unwrap_or_else(|| "outside the freeze windows".into())
        ),
        None,
    );
    let rss = rss_kb(std::process::id());
    add(
        r,
        "app_process_rss",
        rss.map(|k| k < 500 * 1024).unwrap_or(false),
        format!(
            "{} MB (shell process only)",
            rss.map(|k| format!("{:.1}", k as f64 / 1024.0))
                .unwrap_or_else(|| "?".into())
        ),
        None,
    );
    // AC-13 budget: one window < 500 MB total (shell + its WebKit helpers; attribution by start time)
    match (rss, webkit_helpers_rss_kb(std::process::id())) {
        (Some(own), Some((n, wk, how))) => {
            let total = (own + wk) as f64 / 1024.0;
            r.lock()
                .unwrap_or_else(|e| e.into_inner())
                .meta
                .insert("total_rss_mb".into(), json!((total * 10.0).round() / 10.0));
            add(
                r,
                "app_total_rss",
                total < 500.0,
                format!("{total:.1} MB = shell {:.1} MB + {n} WebKit helper process(es) {:.1} MB (attributed by {how}; budget 500 MB; measured right after the checks, not idle)", own as f64 / 1024.0, wk as f64 / 1024.0),
                None,
            );
        }
        _ => add(r, "app_total_rss", false, "could not read process RSS via ps", None),
    }
    let notes = shell.notifications.lock().unwrap_or_else(|e| e.into_inner()).clone();
    let log_isolated = shell.paths.log_dir.starts_with(std::env::temp_dir())
        && !shell.paths.log_dir.to_string_lossy().contains("Library/Logs");
    add(
        r,
        "isolation",
        !shell.paths.state_file.starts_with(&shell.paths.config_dir) && log_isolated,
        format!(
            "state/window-state/Downloads/app log in a temp dir (log isolated: {log_isolated}); notifications recorded not shown: {notes:?}"
        ),
        None,
    );
}

async fn wait_window(app: &AppHandle, label: &str, timeout: Duration) -> Option<WebviewWindow> {
    let t0 = Instant::now();
    while t0.elapsed() < timeout {
        if let Some(w) = app.get_webview_window(label) {
            return Some(w);
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn etime_parsing() {
        assert_eq!(etime_secs("00:07"), Some(7));
        assert_eq!(etime_secs(" 01:02:03 "), Some(3723));
        assert_eq!(etime_secs("2-00:00:01"), Some(172_801));
        assert_eq!(etime_secs("x"), None);
        assert_eq!(etime_secs("1:2:3:4"), None);
    }

    #[test]
    fn responsibility_lookup_is_safe() {
        // our own process is responsible for itself (or the symbol is unavailable: None); never panics
        let me = std::process::id() as i32;
        if let Some(r) = responsible_pid(me) {
            assert!(r > 0);
        }
        assert_eq!(responsible_pid(-5), None);
    }

    #[test]
    fn skipped_checks_serialize_only_when_true() {
        let r: Shared = Arc::new(Mutex::new(Report::default()));
        add(&r, "a", true, "measured", Some(1.0));
        skip(&r, "b", "not measurable");
        let rep = r.lock().unwrap();
        let a = serde_json::to_value(&rep.checks[0]).unwrap();
        let b = serde_json::to_value(&rep.checks[1]).unwrap();
        assert!(a.get("skipped").is_none());
        assert_eq!(b["skipped"], json!(true));
        assert_eq!(b["ok"], json!(true));
        assert_eq!(rep.meta["skipped"], json!(["b"]));
    }
}
