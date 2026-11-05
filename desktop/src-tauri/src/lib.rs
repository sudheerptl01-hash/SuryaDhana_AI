//! SuryaDhana desktop shell (Tauri v2): the native window + menu-bar control panel for the local
//! SuryaDhana stack. The stack itself (data-service, ui-api, master-controller) stays a set of
//! launchd-supervised services that run whether or not this app is open.
//!
//! Module map:
//! * `config`    - config.json (validated loopback URLs, tolerant parse)
//! * `health`    - poller + the `ShellStatus` contract type, notification and status-event cadence rules
//! * `windows`   - boot -> terminal lifecycle, multi-window, session restore, navigation/download guards
//! * `menu`      - native menu bar + action dispatcher; `tray` - menu-bar item
//! * `commands`  - IPC commands (9 contract shell_* commands for the terminal origin; boot-only commands)
//! * `policy`    - pure validation/allowlist/freeze-guard/trust logic; `pages` - the 42 function codes
//! * `stack`     - start/stop the stack via the watchdog LaunchAgent (never Python), stack activity probe
//! * `downloads` - files written into ~/Downloads (allowlist, quarantine, limits, feedback)
//! * `trust`     - port-squatting guard (who listens on the terminal port)
//! * `autostart` - Launch at Login LaunchAgent (KeepAlive after a crash, Login Items status)
//! * `crash`     - panic hook, unclean-exit marker, crash-loop breaker; `instance` - single instance
//! * `supervise` - crash relaunch for a copy opened by hand (a detached crash guard; round 3)
//! * `macos`     - the few AppKit / UserNotifications / ServiceManagement / libproc calls Tauri lacks
//! * `exec`      - bounded child processes (every `launchctl` / `plutil` call has a hard time limit)
//! * `feed`      - K5: the stack's notification feed as native banners (price alerts etc., round 3)
//! * `selftest`  - `--self-test <out.json>`: introspection run used by scripts/build_desktop.sh --test
//!
//! Command line (no window, exit at once): `--version` prints the build id; `--login-item-sync [--start]`
//! rewrites an existing Launch-at-Login entry for this copy and reloads it in launchd (scripts/build_desktop.sh
//! --install / --rollback).

pub mod autostart;
pub mod commands;
pub mod config;
pub mod crash;
pub mod downloads;
pub mod exec;
pub mod feed;
pub mod health;
pub mod instance;
pub mod macos;
pub mod menu;
pub mod pages;
pub mod policy;
pub mod selftest;
pub mod stack;
pub mod supervise;
pub mod tray;
pub mod trust;
pub mod windows;

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, Url};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_opener::OpenerExt;
use tauri_plugin_window_state::StateFlags;

use crate::health::{HealthHub, StatusCadence, SvcNotifier, Transition, Update, SERVICE_NAMES};

/// `<sha7>[-dirty]-<source hash>-<UTC build time>` (build.rs): shown in About, the tray, `shell_info.build_id`,
/// the boot page, the log and the self-test, so two different shell binaries never look identical.
pub const BUILD_ID: &str = env!("SURYADHANA_BUILD_ID");
use crate::policy::RateLimiter;
use crate::windows::{Registry, Session};

/// Resolved filesystem locations (isolated temp dirs in self-test mode).
#[derive(Debug, Clone)]
pub struct Paths {
    pub config_dir: PathBuf,
    pub state_file: PathBuf,
    pub window_state_file: PathBuf,
    pub log_dir: PathBuf,
    pub downloads_dir: PathBuf,
    /// The home directory the app runs with (`$HOME`; a temp dir in drills).
    pub home: PathBuf,
    /// K5 notification feed: cursor file (+ the sink heartbeat file; none in self-test).
    pub feed: feed::FeedPaths,
}

/// Why the boot page shows "Starting the stack…" instead of the down state.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StartingReason {
    /// The app was started by the login job (or right after the Mac booted): the watchdog is bringing the
    /// stack up at the same time.
    Login,
    /// Start Stack was chosen moments ago.
    StartRequested,
    /// A watchdog run is in progress.
    Watchdog,
}

/// Pure: is the stack (probably) starting right now, and why? Within the start-up `grace` after a login
/// start or a Start request, or while a watchdog run holds its lock, the boot page never shows the red
/// down state and never offers Start/Stop (C1-desktop-native-01, C2-reliability-ops-03). The login / Start
/// grace needs the watchdog LaunchAgent (installed or loaded): without it nothing starts the stack, so the
/// down state with its install command shows at once (wave 2).
pub fn startup_phase(
    app_uptime: Duration,
    login_start: bool,
    since_start_request: Option<Duration>,
    watchdog_running: bool,
    watchdog_present: bool,
    grace: Duration,
) -> Option<StartingReason> {
    if watchdog_present && since_start_request.map(|d| d < grace).unwrap_or(false) {
        Some(StartingReason::StartRequested)
    } else if watchdog_present && login_start && app_uptime < grace {
        Some(StartingReason::Login)
    } else if watchdog_running {
        Some(StartingReason::Watchdog)
    } else {
        None
    }
}

/// Pure: a login start = launched by the login job (`--autostart`) and not a relaunch after a crash, or
/// launched within the start-up grace of the Mac's boot.
pub fn is_login_start(
    autostart_arg: bool,
    relaunched_after_crash: bool,
    since_boot: Option<Duration>,
    grace: Duration,
) -> bool {
    (autostart_arg && !relaunched_after_crash) || since_boot.map(|d| d < grace).unwrap_or(false)
}

/// Shared app state (managed by Tauri).
pub struct Shell {
    pub cfg: config::Config,
    pub paths: Paths,
    /// Self-test isolation: no autostart changes, no single-instance, no real notifications / browser
    /// opens (recorded instead), incognito webviews, temp state, temp log.
    pub selftest: bool,
    pub health: Arc<HealthHub>,
    pub windows: Mutex<Registry>,
    pub ui_notify_limiter: Mutex<RateLimiter>,
    /// Default-browser opens (page links + shell_open_external), all windows together.
    pub external_limiter: Mutex<RateLimiter>,
    /// System Settings › Notifications opened by a permission request: at most once a minute.
    pub notif_settings_limiter: Mutex<RateLimiter>,
    /// A notification-permission request is waiting for the macOS prompt (requests are serialized).
    pub notif_request_busy: AtomicBool,
    /// This instance is the Launch-at-Login job's process (launchd `XPC_SERVICE_NAME` = the label).
    pub under_login_job: bool,
    /// A Launch-at-Login change launchd applies only at the next login (the menu text says so).
    pub autostart_pending: Mutex<Option<&'static str>>,
    pub downloads: downloads::Downloads,
    shell_notify_last: Mutex<HashMap<String, Instant>>,
    pub tray: Mutex<Option<tray::TrayHandles>>,
    pub menu: Mutex<Option<menu::MenuHandles>>,
    cadence: Mutex<StatusCadence>,
    notifier: Mutex<SvcNotifier>,
    /// Self-test recorders (redacted URLs / titles only).
    pub opened_external: Mutex<Vec<String>>,
    pub blocked: Mutex<Vec<String>>,
    pub notifications: Mutex<Vec<String>>,
    pub started: Instant,
    pub started_epoch_ms: f64,
    /// Epoch ms of the first boot-page paint reported by any window (self-test / perf evidence).
    pub boot_paint_epoch_ms: Mutex<Option<f64>>,
    /// Self-test only: keep windows on the boot page until the boot-page checks ran (max 3 s).
    pub hold_boot: AtomicBool,
    pub quitting: AtomicBool,
    /// This launch is a login start (see [`is_login_start`]).
    pub login_start: bool,
    /// When Start Stack was last chosen (boot page or menu bar).
    pub start_requested: Mutex<Option<Instant>>,
    /// Launch at Login entry of this home.
    pub agent: autostart::LoginAgent,
    /// The single-instance socket this (primary) instance owns.
    pub instance_socket: Option<PathBuf>,
    /// Crash bookkeeping (None in self-test).
    pub crash_files: Option<crash::CrashFiles>,
    /// A private WebKit data store when `$HOME` is not the account's home (drills; see instance.rs).
    pub data_store: Option<[u8; 16]>,
    /// Who relaunches this copy after a crash (round 3: login job, crash guard, or nothing; tray line).
    pub supervision: Mutex<supervise::Supervision>,
    /// Round 4b: macOS's notification permission for this app as last read (None = not read yet / unknown).
    /// Drives the tray's "Notifications are off" line, the boot page footer and the feed's sink heartbeat.
    pub notif_auth: Mutex<Option<macos::NotifAuth>>,
}

impl Shell {
    /// The tray handles, cloned out of their lock. NEVER call a tray/menu method while holding `self.tray`
    /// or `self.menu`: from a non-main thread the call blocks until the main thread runs it, and the main
    /// thread may be waiting for that same lock (the 25 Oct drill deadlock: the poller updated the tray
    /// under the lock while setup refreshed the Launch-at-Login check mark).
    pub fn tray_handles(&self) -> Option<tray::TrayHandles> {
        self.tray.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// The menu handles, cloned out of their lock (same rule as [`Shell::tray_handles`]).
    pub fn menu_handles(&self) -> Option<menu::MenuHandles> {
        self.menu.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// Native notification (internal: service changes, downloads). Recorded, not shown, in self-test.
    pub fn notify(&self, app: &AppHandle, title: &str, body: &str) {
        if self.selftest {
            self.notifications
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .push(title.to_string());
            return;
        }
        if let Err(e) = app.notification().builder().title(title).body(body).show() {
            log::warn!("[notify] failed: {e}");
        }
    }

    /// Notification with a per-key minimum interval (flapping protection).
    pub fn notify_throttled(&self, app: &AppHandle, key: &str, min_gap: Duration, title: &str, body: &str) {
        {
            let mut m = self.shell_notify_last.lock().unwrap_or_else(|e| e.into_inner());
            if m.get(key).map(|t| t.elapsed() < min_gap).unwrap_or(false) {
                log::info!("[notify] throttled {key}");
                return;
            }
            m.insert(key.to_string(), Instant::now());
        }
        self.notify(app, title, body);
    }

    /// Record a blocked navigation (self-test evidence; redacted).
    pub fn record_blocked(&self, url: &Url) {
        let mut v = self.blocked.lock().unwrap_or_else(|e| e.into_inner());
        if v.len() < 200 {
            v.push(policy::redact_url(url));
        }
    }

    /// The start-up grace from config.json / the env override.
    pub fn grace(&self) -> Duration {
        Duration::from_secs(self.cfg.startup_grace_secs)
    }

    /// Why the stack is starting right now, if it is (see [`startup_phase`]).
    pub fn starting(&self, stack: &stack::Activity) -> Option<StartingReason> {
        let since = self
            .start_requested
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .map(|t| t.elapsed());
        startup_phase(
            self.started.elapsed(),
            self.login_start,
            since,
            stack.watchdog_running,
            stack.watchdog_installed || stack.watchdog_loaded == Some(true),
            self.grace(),
        )
    }
}

/// Open an external http(s) URL in the default browser (recorded instead in self-test). Rate-limited for
/// all windows together (C2-security-11): a page cannot flood the browser with tabs.
pub fn open_external(app: &AppHandle, url: Url) -> Result<(), String> {
    let shell = app.state::<Shell>();
    if !policy::is_external_http(&url) {
        log::warn!("[nav] refused to open non-external {}", policy::redact_url(&url));
        return Err("not an external http(s) URL".into());
    }
    if !shell
        .external_limiter
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .allow(Instant::now())
    {
        log::warn!(
            "[nav] refused to open {}: more than {} browser opens a minute",
            policy::redact_url(&url),
            policy::EXTERNAL_OPENS_PER_MINUTE
        );
        return Err(format!(
            "rate limited ({} browser opens per minute)",
            policy::EXTERNAL_OPENS_PER_MINUTE
        ));
    }
    if shell.selftest {
        shell
            .opened_external
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .push(url.to_string());
        return Ok(());
    }
    app.opener().open_url(url.as_str(), None::<&str>).map_err(|e| {
        log::warn!("[nav] could not open {}: {e}", policy::redact_url(&url));
        "the default browser could not be opened".to_string()
    })
}

/// Which logs folder to open.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LogsTarget {
    App,
    Stack,
}

/// Open a logs folder in Finder.
pub fn open_folder(app: &AppHandle, which: LogsTarget) {
    let shell = app.state::<Shell>();
    let dir = match which {
        LogsTarget::App => shell.paths.log_dir.clone(),
        LogsTarget::Stack => shell.cfg.repo_root.join(".logs"),
    };
    let _ = std::fs::create_dir_all(&dir);
    if shell.selftest {
        return;
    }
    if let Err(e) = app.opener().open_path(dir.display().to_string(), None::<&str>) {
        log::warn!("[logs] open {} failed: {e}", dir.display());
    }
}

/// Open docs/RUNBOOK_RESTORE.md with the default app.
pub fn open_runbook(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let p = shell.cfg.repo_root.join("docs").join("RUNBOOK_RESTORE.md");
    if !p.is_file() {
        shell.notify(app, "Runbook not found", &p.display().to_string());
        return;
    }
    if let Err(e) = app.opener().open_path(p.display().to_string(), None::<&str>) {
        log::warn!("[help] runbook open failed: {e}");
    }
}

/// Tray ▸ "Notifications are off — …" (round 4b): System Settings › Notifications at SuryaDhana. Opened ONLY by a
/// click on that line (never by itself, never from a page); recorded instead in self-test.
pub fn open_notification_settings(app: &AppHandle) {
    let shell = app.state::<Shell>();
    if shell.selftest {
        shell
            .opened_external
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .push("system-settings:notifications".into());
        return;
    }
    log::info!("[notify] opening System Settings › Notifications › SuryaDhana (tray click)");
    if let Err(e) = app.opener().open_url(commands::NOTIFICATION_SETTINGS_URL, None::<&str>) {
        log::warn!("[notify] could not open the Notifications settings: {e}");
    }
}

/// How often macOS's notification permission is read again (it changes only in System Settings).
pub const NOTIF_AUTH_EVERY: Duration = Duration::from_secs(60);

/// Read macOS's notification permission (round 4b) and apply a change: one log line, the tray hint. An unknown
/// answer (timed out, not running from the bundle) changes nothing.
pub async fn refresh_notification_auth(app: &AppHandle) {
    let now = tokio::task::spawn_blocking(|| macos::notification_authorization(Duration::from_secs(2)))
        .await
        .unwrap_or(None);
    let Some(now) = now else {
        return;
    };
    let shell = app.state::<Shell>();
    let prev = shell.notif_auth.lock().unwrap_or_else(|e| e.into_inner()).replace(now);
    if prev == Some(now) {
        return;
    }
    if now == macos::NotifAuth::Denied {
        log::warn!(
            "[notify] macOS has notifications OFF for SuryaDhana: no banners (alerts, service changes, downloads). \
             The menu-bar item says so; its line opens System Settings › Notifications › SuryaDhana on a click"
        );
    } else {
        log::info!("[notify] notification permission: {}", now.as_permission());
    }
    if let Some(t) = shell.tray_handles() {
        let shown = t.notif_hint_shown.load(Ordering::SeqCst);
        tray::set_notif_hint(&t, tray::notif_hint_wanted(Some(now), shown));
    }
}

/// File ▸ Show Latest Download: reveal the latest saved file in Finder (C1-desktop-native-05).
pub fn reveal_latest_download(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let Some(p) = shell.downloads.latest() else {
        macos::beep();
        return;
    };
    if shell.selftest {
        return;
    }
    if let Err(e) = app.opener().reveal_item_in_dir(&p) {
        log::warn!("[download] reveal failed: {e}");
    }
}

/// A file was saved into Downloads (both paths): remember it, enable the menu items, tell the owner.
pub fn download_saved(app: &AppHandle, path: &Path, bytes: Option<u64>) {
    let shell = app.state::<Shell>();
    shell.downloads.record(path);
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_default();
    log::info!(
        "[download] saved {}{}",
        downloads::display_path(path, Some(&shell.paths.home)),
        bytes.map(|b| format!(" ({b} bytes)")).unwrap_or_default()
    );
    if let Some(m) = shell.menu_handles() {
        let _ = m.latest_download.set_enabled(true);
    }
    if let Some(t) = shell.tray_handles() {
        let _ = t.latest_download.set_enabled(true);
    }
    shell.notify(
        app,
        "Saved to Downloads",
        &format!("{name}\nFile ▸ Show Latest Download (⌥⌘L) shows it in Finder."),
    );
}

/// A save into Downloads failed or was refused (both paths): log and tell the owner why.
pub fn download_failed(app: &AppHandle, name: &str, why: &str) {
    let shell = app.state::<Shell>();
    log::warn!("[download] {name}: {why}");
    shell.notify_throttled(
        app,
        "download-failed",
        Duration::from_secs(5),
        &format!("Could not save {}", if name.is_empty() { "the file" } else { name }),
        why,
    );
}

// ---------------------------------------------------------------------------------------------
// Launch at Login
// ---------------------------------------------------------------------------------------------

/// Current Launch-at-Login state (plist + Login Items status).
pub fn autostart_state(app: &AppHandle) -> autostart::State {
    app.state::<Shell>().agent.state()
}

/// True when Launch at Login is on and allowed (contract `shell_info.autostart`).
pub fn autostart_enabled(app: &AppHandle) -> bool {
    autostart_state(app).checked()
}

/// Bring the menu and tray check marks / texts in line with reality (and a change pending until the next
/// login).
pub fn refresh_autostart_checks(app: &AppHandle) {
    let st = autostart_state(app);
    let shell = app.state::<Shell>();
    let pending = *shell.autostart_pending.lock().unwrap_or_else(|e| e.into_inner());
    let text = match (st, pending) {
        (autostart::State::Blocked, _) => st.menu_text(),
        (_, Some(p)) => p,
        _ => st.menu_text(),
    };
    if let Some(m) = shell.menu_handles() {
        let _ = m.autostart.set_checked(st.checked());
        let _ = m.autostart.set_text(text);
    }
    if let Some(t) = shell.tray_handles() {
        let _ = t.autostart.set_checked(st.checked());
        let _ = t.autostart.set_text(text);
        let line = shell.supervision.lock().unwrap_or_else(|e| e.into_inner()).text();
        let _ = t.supervision.set_text(line);
    };
}

/// Round 3 (SECREL-06 / R-RUST-05): make sure a crash of THIS copy is followed by a relaunch. The login job's
/// own process has launchd's KeepAlive; a copy opened by hand that the Launch-at-Login entry starts gets a
/// detached crash guard (supervise.rs). Idempotent (one guard per process); refreshes the tray line.
pub fn supervise_this_copy(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let already = matches!(
        *shell.supervision.lock().unwrap_or_else(|e| e.into_inner()),
        supervise::Supervision::Guarded(_) | supervise::Supervision::LoginJob
    );
    if already {
        return;
    }
    let tool = launchd_tool(&shell);
    let state = autostart_state(app);
    let this_copy = match (current_exe(), shell.agent.exists()) {
        (Some(exe), true) => autostart::plist_program(&shell.agent.plist)
            .map(|p| p == exe)
            .unwrap_or(false),
        _ => false,
    };
    let decision = supervise::decide(
        autostart_untouchable(&shell),
        shell.under_login_job,
        state,
        this_copy,
        tool.is_ok(),
    );
    let next = match (decision, tool, &shell.crash_files) {
        (supervise::Decision::LoginJob, _, _) => supervise::Supervision::LoginJob,
        (supervise::Decision::Guard, Ok(tool), Some(cf)) => {
            match supervise::spawn_guard(std::process::id(), &cf.run, &shell.agent.plist, &tool, macos::uid()) {
                Ok(pid) => {
                    log::info!(
                        "[app] crash relaunch: this copy was not started by the login job; crash guard pid {pid} \
                         asks launchd to start SuryaDhana again if it ends without a clean exit"
                    );
                    supervise::Supervision::Guarded(pid)
                }
                Err(e) => {
                    log::warn!("[app] crash relaunch: could not start the crash guard: {e}");
                    supervise::Supervision::Off("the crash guard could not start")
                }
            }
        }
        (supervise::Decision::Guard, _, _) => supervise::Supervision::Off("no crash bookkeeping"),
        (supervise::Decision::Off(why), _, _) => supervise::Supervision::Off(why),
    };
    if let supervise::Supervision::Off(why) = &next {
        log::info!("[app] crash relaunch for this copy: off ({why})");
    }
    *shell.supervision.lock().unwrap_or_else(|e| e.into_inner()) = next;
    // the login item owns relaunching at login: macOS must not ALSO reopen this copy through LaunchServices
    if state == autostart::State::On && !shell.selftest && !macos::disable_relaunch_on_login() {
        log::debug!("[app] could not disable relaunch on login");
    }
    refresh_autostart_checks(app);
}

/// The `launchctl` this instance may run (None = launchd is never touched: self-test, debug build, a
/// drill's temp HOME without its own recorder).
fn launchd_tool(shell: &Shell) -> Result<PathBuf, &'static str> {
    if autostart_untouchable(shell) {
        return Err("self-test / debug build / SURYADHANA_NO_AUTOSTART");
    }
    let injected = std::env::var_os("SURYADHANA_LAUNCHCTL").map(PathBuf::from);
    autostart::launchctl_tool(&shell.paths.home, macos::account_home().as_deref(), injected.as_deref())
}

/// After the Launch-at-Login entry was written or removed: make launchd's loaded job match the file NOW
/// (completeness-03), on a background thread (each launchctl call is bounded). Never boots out the job this
/// instance runs under: that change is left for the next login and the menu says so.
pub fn reconcile_launchd(app: &AppHandle, why: &'static str) {
    let shell = app.state::<Shell>();
    let tool = launchd_tool(&shell);
    let plan = autostart::launchd_plan(
        shell.agent.exists(),
        shell.under_login_job,
        tool.as_ref().map(|_| ()).map_err(|e| *e),
    );
    match &plan {
        autostart::LaunchdPlan::Skip(r) => {
            log::info!("[autostart] {why}: launchd not touched ({r})");
            return;
        }
        autostart::LaunchdPlan::Defer(text) => {
            log::info!(
                "[autostart] {why}: this instance runs under the login job; launchd applies the change at the next login"
            );
            *shell.autostart_pending.lock().unwrap_or_else(|e| e.into_inner()) = Some(text);
            refresh_autostart_checks(app);
            return;
        }
        _ => {}
    }
    let Ok(tool) = tool else { return };
    let plist = shell.agent.plist.clone();
    let app2 = app.clone();
    let _ = std::thread::Builder::new().name("launchd".into()).spawn(move || {
        match autostart::run_launchd(&tool, &plan, stack::current_uid(), &plist) {
            Ok(lines) => {
                log::info!(
                    "[autostart] {why}: launchd now matches the entry ({})",
                    lines.join("; ")
                );
                *app2
                    .state::<Shell>()
                    .autostart_pending
                    .lock()
                    .unwrap_or_else(|e| e.into_inner()) = None;
            }
            Err(e) => {
                log::warn!("[autostart] {why}: could not reload the job in launchd: {e} (applies at the next login)")
            }
        }
        refresh_autostart_checks(&app2);
    });
}

fn current_exe() -> Option<PathBuf> {
    std::env::current_exe().and_then(|p| p.canonicalize()).ok()
}

/// Menu/tray toggle for Launch at Login. Blocked in System Settings -> open that pane instead.
pub fn toggle_autostart(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let st = autostart_state(app);
    if shell.selftest {
        refresh_autostart_checks(app);
        return;
    }
    let res = match st {
        autostart::State::Blocked => {
            log::info!("[autostart] off in System Settings › Login Items; opening that pane");
            macos::open_login_items_settings();
            Ok(())
        }
        autostart::State::On => shell.agent.remove().map(|_| log::info!("[autostart] disabled")),
        autostart::State::Off => match current_exe() {
            Some(exe) => shell
                .agent
                .write(&exe)
                .map(|_| log::info!("[autostart] enabled for {}", exe.display())),
            None => Err(std::io::Error::other("cannot resolve the app's own path")),
        },
    };
    let changed = res.is_ok() && st != autostart::State::Blocked;
    if let Err(e) = res {
        log::warn!("[autostart] toggle failed: {e}");
        shell.notify(app, "Launch at Login", &format!("Could not change it: {e}"));
    }
    if changed && st == autostart::State::Off {
        // Launch at Login was just turned on: a copy opened by hand gets its crash guard now (the guard also
        // stands down by itself when the entry is removed again)
        supervise_this_copy(app);
    }
    if changed {
        *shell.autostart_pending.lock().unwrap_or_else(|e| e.into_inner()) = None;
        if shell.under_login_job && st == autostart::State::Off {
            // back on while the login job that runs this instance is still loaded: nothing to reload
            log::info!("[autostart] Launch at Login on again: the login job running this instance is still loaded");
        } else {
            reconcile_launchd(app, "Launch at Login toggled");
        }
    }
    refresh_autostart_checks(app);
}

fn autostart_untouchable(shell: &Shell) -> bool {
    shell.selftest
        || cfg!(debug_assertions)
        || std::env::var("SURYADHANA_NO_AUTOSTART")
            .map(|v| v == "1")
            .unwrap_or(false)
}

/// First run: enable Launch at Login once (AC-5). Skipped in self-test, debug builds, and when
/// SURYADHANA_NO_AUTOSTART=1. The marker lives outside state.json, so deleting state.json (README's
/// "reset window layout") never turns it back on after the owner switched it off (C1-desktop-native-09).
fn first_run_autostart(app: &AppHandle) {
    let shell = app.state::<Shell>();
    if autostart_untouchable(&shell) {
        return;
    }
    let marker = shell.paths.config_dir.join(autostart::FIRST_RUN_MARKER);
    let legacy = Session::load(&shell.paths.state_file).autostart_initialized;
    let should = autostart::first_run_should_enable(marker.exists(), legacy, shell.agent.exists());
    if should {
        match current_exe().map(|exe| shell.agent.write(&exe)) {
            Some(Ok(())) => {
                log::info!("[autostart] enabled on first run (toggle: menu SuryaDhana > Launch at Login)");
                reconcile_launchd(app, "first-run Launch at Login");
            }
            Some(Err(e)) => log::warn!("[autostart] first-run enable failed: {e}"),
            None => log::warn!("[autostart] first-run enable failed: cannot resolve the app's own path"),
        }
    }
    if !marker.exists() {
        if let Err(e) = config::write_atomic(&marker, &format!("{}\n", health::now_iso())) {
            log::warn!("[autostart] could not write the first-run marker: {e}");
        }
    }
    refresh_autostart_checks(app);
}

/// Every normal launch: keep an existing Launch-at-Login entry pointing at the right copy and in the
/// current format (KeepAlive etc.; the plugin-era plist is upgraded once). Never creates one.
fn maintain_autostart(app: &AppHandle) {
    let shell = app.state::<Shell>();
    if autostart_untouchable(&shell) {
        return;
    }
    shell.agent.rotate_stderr_log();
    let Some(exe) = current_exe() else { return };
    let Some(m) = shell.agent.maintain(&exe) else { return };
    let prev = m.previous.as_ref().map(|p| p.display().to_string()).unwrap_or_default();
    match (&m.action, &m.result) {
        (autostart::Maintenance::Keep, _) => {}
        (autostart::Maintenance::Repoint(p), Ok(())) => {
            if m.previous.as_ref().map(|q| !q.exists()).unwrap_or(true) {
                log::info!(
                    "[autostart] Launch at Login pointed at a missing app ({prev}); now {}",
                    p.display()
                );
            } else {
                log::info!(
                    "[autostart] Launch at Login now starts the installed copy {} (was {prev})",
                    p.display()
                );
            }
            reconcile_launchd(app, "Launch at Login entry repointed");
        }
        (autostart::Maintenance::Upgrade(p), Ok(())) => {
            log::info!(
                "[autostart] Launch at Login entry updated (relaunch after a crash) for {}",
                p.display()
            );
            reconcile_launchd(app, "Launch at Login entry upgraded");
        }
        (_, Err(e)) => log::warn!("[autostart] could not update the Launch at Login entry: {e}"),
    }
    refresh_autostart_checks(app);
}

// ---------------------------------------------------------------------------------------------
// Stack control
// ---------------------------------------------------------------------------------------------

/// Start the stack (watchdog kickstart, launchd bootstrap). Returns a plain-language summary.
pub fn stack_start(app: &AppHandle) -> Result<String, String> {
    let shell = app.state::<Shell>();
    let paths = stack::StackPaths::new(&shell.cfg.repo_root);
    paths.validate()?;
    let uid = stack::current_uid();
    let plist = stack::watchdog_plist(&shell.paths.home);
    let activity = stack::probe_files(&paths, &shell.paths.home, SystemTime::now());
    let wd = stack::Watchdog {
        loaded: stack::watchdog_loaded(uid),
        running: activity.watchdog_running,
        plist_installed: plist.is_file(),
    };
    log::info!("[stack] start requested ({wd:?})");
    let hung: Vec<&str> = shell
        .health
        .snapshot()
        .stalled
        .iter()
        .zip(SERVICE_NAMES)
        .filter(|(s, _)| s.is_some())
        .map(|(_, n)| n)
        .collect();
    let out = stack::start_plan(&paths, uid, wd, &plist)
        .and_then(|plan| stack::execute(&paths, &plan))
        .map(|said| {
            if hung.is_empty() {
                said
            } else {
                // Start (start-local.sh start) skips a running service, so it cannot help a hung one; the
                // watchdog's hang rule (W2-OPS) or a restart does
                format!(
                    "{said} {} {} running but not responding: Start does not restart it ({}). In Terminal: \
                     ./start-local.sh restart {}",
                    health::join_names(&hung),
                    if hung.len() == 1 { "is" } else { "are" },
                    if wd.loaded || wd.plist_installed {
                        "the watchdog restarts a hung service after two failed checks, about 3.5–5.5 min after it hangs"
                    } else {
                        "the watchdog agent is not loaded, so nothing restarts it automatically"
                    },
                    hung.join(" / ")
                )
            }
        });
    match &out {
        Ok(s) => {
            log::info!("[stack] start: {s}");
            *shell.start_requested.lock().unwrap_or_else(|e| e.into_inner()) = Some(Instant::now());
        }
        Err(e) => log::warn!("[stack] start failed: {e}"),
    }
    shell.health.poke();
    out
}

/// Stop the stack after the freeze guard; the caller has confirmed.
pub fn stack_stop_confirmed(app: &AppHandle) -> Result<String, String> {
    let shell = app.state::<Shell>();
    if let Err(w) = stack::stop_guard(time::OffsetDateTime::now_utc()) {
        return Err(format!("Refused: inside the restart-freeze window {}", w.label));
    }
    let paths = stack::StackPaths::new(&shell.cfg.repo_root);
    paths.validate()?;
    log::info!("[stack] stop confirmed by the user");
    *shell.start_requested.lock().unwrap_or_else(|e| e.into_inner()) = None;
    let out = stack::execute(&paths, &stack::stop_plan(&paths));
    match &out {
        Ok(s) => log::info!("[stack] stop: {s}"),
        Err(e) => log::warn!("[stack] stop failed: {e}"),
    }
    shell.health.poke();
    out
}

/// Ask for confirmation with a native dialog (async; resolves to true on "Stop Stack").
pub async fn confirm_stop(app: &AppHandle) -> bool {
    let (tx, rx) = tokio::sync::oneshot::channel();
    app.dialog()
        .message(
            "Stop data-service, ui-api and master-controller?\n\nThey are marked paused, so the watchdog will NOT restart them \
             until you choose Start Stack. Scheduled jobs (EOD pipeline, Desk, shadow, backups, Telegram) will not run while stopped.",
        )
        .title("Stop the SuryaDhana stack")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Stop Stack".into(), "Cancel".into()))
        .show(move |ok| {
            let _ = tx.send(ok);
        });
    rx.await.unwrap_or(false)
}

/// Tray/menu Start Stack: run it and report with a notification.
pub fn stack_start_action(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let app2 = app.clone();
        let res = tokio::task::spawn_blocking(move || stack_start(&app2))
            .await
            .unwrap_or_else(|_| Err("Start Stack failed".into()));
        let shell = app.state::<Shell>();
        match res {
            Ok(s) => shell.notify(&app, "Starting the stack", &s),
            Err(e) => shell.notify(&app, "Start Stack failed", &e),
        }
    });
}

/// Tray/menu Stop Stack…: freeze guard, confirm, run.
pub fn stack_stop_action(app: &AppHandle) {
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        if let Err(w) = stack::stop_guard(time::OffsetDateTime::now_utc()) {
            app.dialog()
                .message(format!(
                    "Stopping the stack is refused inside the restart-freeze window {}.\n\nTry again after the window ends.",
                    w.label
                ))
                .title("Stop Stack refused")
                .kind(MessageDialogKind::Info)
                .show(|_| {});
            return;
        }
        if app.state::<Shell>().selftest {
            return;
        }
        if !confirm_stop(&app).await {
            log::info!("[stack] stop cancelled");
            return;
        }
        let res = stack_stop_confirmed(&app);
        let shell = app.state::<Shell>();
        match res {
            Ok(s) => shell.notify(&app, "Stopping the stack", &s),
            Err(e) => shell.notify(&app, "Stop Stack failed", &e),
        }
    });
}

/// SuryaDhana ▸ Settings… (⌘,): the app's settings are config.json (wave 2: replaces round 1's item that
/// opened the SYS telemetry page, which has no settings). A native dialog says what is in it and what is in
/// the menus; "Edit config.json…" opens it in TextEdit. Changes apply at the next launch.
pub fn open_settings(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let path = shell.paths.config_dir.join(config::CONFIG_FILE);
    if shell.selftest {
        return;
    }
    let app2 = app.clone();
    app.dialog()
        .message(settings_text(&path))
        .title("SuryaDhana Settings")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom(
            "Edit config.json…".into(),
            "Close".into(),
        ))
        .show(move |edit| {
            if !edit {
                return;
            }
            if !path.is_file() {
                let cfg = app2.state::<Shell>().cfg.clone();
                let _ = config::write_atomic(&path, &config::to_json(&cfg));
            }
            if let Err(e) = app2.opener().open_path(path.display().to_string(), Some("TextEdit")) {
                log::warn!("[settings] could not open {}: {e}", path.display());
                let _ = app2.opener().reveal_item_in_dir(&path);
            }
        });
}

/// The Settings dialog's text (pure).
pub fn settings_text(path: &Path) -> String {
    format!(
        "SuryaDhana keeps its settings in config.json:\n\n\
         • ui_url, data_service_url, controller_url: the local stack (loopback http only)\n\
         • nifty_in_menubar, notify_service_changes: the menu-bar NIFTY and service banners\n\
         • startup_grace_secs: how long the boot screen shows \"Starting the stack\" after login\n\
         • frame_hosts, verify_ui_listener, trusted_python_prefixes: embedded charts and the port guard\n\n\
         In the menus: Launch at Login (SuryaDhana menu) and page zoom (View, ⌘= ⌘- ⌘0, remembered per window).\n\n\
         Saved changes apply the next time SuryaDhana starts (⌘Q, then open it again).\n\n{}",
        downloads::display_path(path, std::env::var_os("HOME").map(PathBuf::from).as_deref())
    )
}

/// Help ▸ Keyboard Shortcuts: the native app's ⌘ keys (C1-trader-ux-09: the desktop help taught Alt+1…0).
pub fn show_shortcuts(app: &AppHandle) {
    if app.state::<Shell>().selftest {
        return;
    }
    app.dialog()
        .message(menu::shortcuts_text())
        .title("SuryaDhana keyboard shortcuts")
        .kind(MessageDialogKind::Info)
        .show(|_| {});
}

/// Save state and quit (⌘Q / tray Quit).
pub fn quit(app: &AppHandle) {
    let shell = app.state::<Shell>();
    if !shell.selftest {
        windows::save_session(app);
    }
    shell.quitting.store(true, Ordering::SeqCst);
    log::info!("[app] quit");
    app.exit(0);
}

// ---------------------------------------------------------------------------------------------
// Health -> UI, tray, notifications
// ---------------------------------------------------------------------------------------------

/// Send a `status` event to every terminal window when the cadence says so (on change at most every
/// 5 s, heartbeat at least every 8 s). Called after every poll and by a 1 s ticker.
pub fn broadcast_status_if_due(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let snap = shell.health.snapshot();
    let due = shell
        .cadence
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .due(&snap.status.change_key(), Instant::now());
    if due {
        windows::broadcast(app, &serde_json::json!({"type": "status", "status": snap.status}));
    }
}

fn service_notes(app: &AppHandle, shell: &Shell, notes: &health::Notes, stalled: [bool; 3], watchdog: bool) {
    if !shell.cfg.notify_service_changes {
        return;
    }
    if !notes.down.is_empty() {
        let names: Vec<&str> = notes.down.iter().map(|i| SERVICE_NAMES[*i]).collect();
        let hung: Vec<bool> = notes.down.iter().map(|i| stalled[*i]).collect();
        // a hung service (port held, /health timing out) is "not responding", restarted by the watchdog's hang
        // rule when the agent is there (W2-OPS), else only by hand
        let (title, body) = health::down_note(&names, &hung, watchdog);
        shell.notify(app, &title, &body);
    }
    if !notes.up.is_empty() {
        let names: Vec<&str> = notes.up.iter().map(|i| SERVICE_NAMES[*i]).collect();
        let title = match names.as_slice() {
            [one] => format!("{one} is back up"),
            many => format!("{} are back up", health::join_names(many)),
        };
        shell.notify(app, &title, "Answering /health again.");
    }
}

/// React to a health update: navigator, tray, status broadcast, notifications, build-changed.
pub fn on_health_update(app: &AppHandle, update: Update) {
    let shell = app.state::<Shell>();
    let snap = shell.health.snapshot();

    windows::navigator_tick(app, snap.ui_ready, snap.ui_state);

    if update.tray_dirty || snap.polls <= 2 {
        if let Some(t) = shell.tray_handles() {
            tray::update(&t, &snap, &shell.cfg);
        }
    }

    broadcast_status_if_due(app);

    if let Some(build) = &update.build_changed {
        log::info!("[ui] served build changed -> {build}");
        let labels: Vec<String> = {
            let reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
            reg.wins
                .iter()
                .filter(|(_, w)| {
                    w.phase == windows::Phase::Terminal && w.loaded_build.as_deref() != Some(build.as_str())
                })
                .map(|(l, _)| l.clone())
                .collect()
        };
        for l in labels {
            windows::send_event(app, &l, &serde_json::json!({"type": "build-changed", "build": build}));
        }
    }

    let mut idx = vec![];
    for (name, t) in &update.transitions {
        log::info!(
            "[health] {name} {}{}",
            if *t == Transition::WentDown { "DOWN" } else { "UP" },
            if snap.stack.is_paused(name) {
                " (paused: stopped on purpose)"
            } else {
                ""
            }
        );
        if let Some(i) = SERVICE_NAMES.iter().position(|n| n == name) {
            idx.push((i, *t));
        }
    }
    let up = [
        snap.status.ui_api.up,
        snap.status.data_service.up,
        snap.status.master_controller.up,
    ];
    let paused = SERVICE_NAMES.map(|n| snap.stack.is_paused(n));
    let notes = shell
        .notifier
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .observe(Instant::now(), &idx, up, paused);
    service_notes(
        app,
        &shell,
        &notes,
        snap.stalled.map(|x| x.is_some()),
        snap.stack.watchdog_active(),
    );

    if update.icici_expired {
        log::info!("[health] ICICI session connected -> expired");
        shell.notify_throttled(
            app,
            "icici",
            Duration::from_secs(600),
            "ICICI session expired",
            "Send /login in Telegram to refresh the Breeze session.",
        );
    }
}

/// Add the remote capability for the configured terminal origin (never panics the app).
fn add_remote_capability(app: &AppHandle, ui: &Url) {
    let origin = config::origin_str(ui);
    let json = include_str!("../capabilities-runtime/terminal-remote.json").replace("__UI_ORIGIN__", &origin);
    let app2 = app.clone();
    let res = std::panic::catch_unwind(std::panic::AssertUnwindSafe(move || app2.add_capability(json)));
    match res {
        Ok(Ok(())) => {
            log::info!("[acl] remote capability granted to {origin} only: 9 shell commands + window drag")
        }
        Ok(Err(e)) => log::error!("[acl] remote capability rejected: {e}"),
        Err(_) => log::error!("[acl] remote capability panicked while resolving"),
    }
}

fn resolve_paths(app: &AppHandle, st: Option<&selftest::Options>) -> Paths {
    let home = dirs_home();
    let real_config = app
        .path()
        .app_config_dir()
        .unwrap_or_else(|_| home.join("Library/Application Support/ai.suryadhana.terminal"));
    let log_dir = app
        .path()
        .app_log_dir()
        .unwrap_or_else(|_| home.join("Library/Logs/ai.suryadhana.terminal"));
    match st {
        // self-test: everything it writes stays in its temp dir, including the log (C2-reliability-ops-11)
        Some(o) => Paths {
            config_dir: real_config,
            state_file: o.temp_dir.join("state.json"),
            window_state_file: o.temp_dir.join("window-state.json"),
            log_dir: o.log_dir(),
            downloads_dir: o.temp_dir.join("Downloads"),
            home,
            feed: feed::FeedPaths {
                cursor: o.temp_dir.join(feed::CURSOR_FILE),
                alive: None,
            },
        },
        None => Paths {
            state_file: real_config.join("state.json"),
            window_state_file: real_config.join(".window-state.json"),
            feed: feed::FeedPaths {
                cursor: real_config.join(feed::CURSOR_FILE),
                alive: Some(real_config.join(feed::ALIVE_FILE)),
            },
            config_dir: real_config,
            log_dir,
            downloads_dir: app.path().download_dir().unwrap_or_else(|_| home.join("Downloads")),
            home,
        },
    }
}

fn dirs_home() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("/tmp"))
}

fn epoch_ms() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64() * 1000.0)
        .unwrap_or(0.0)
}

/// Dock click / `open -a` with no visible window: bring back the last-used window (unminimizing it),
/// else main (C1-desktop-native-15).
fn reopen(app: &AppHandle) {
    let last = app
        .state::<Shell>()
        .windows
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .last_focused
        .clone();
    if let Some(w) = last.as_deref().and_then(|l| app.get_webview_window(l)) {
        if w.is_minimized().unwrap_or(false) || w.is_visible().unwrap_or(false) {
            windows::show_window(app, w.label());
            return;
        }
    }
    windows::show_window(app, windows::MAIN);
}

/// `SuryaDhana --version`: one line, no window.
pub fn version_text() -> String {
    format!("SuryaDhana {} ({BUILD_ID})", env!("CARGO_PKG_VERSION"))
}

/// `--login-item-sync [--start]` (scripts/build_desktop.sh --install / --rollback): when a Launch-at-Login
/// entry exists, rewrite it for THIS copy in the current format (KeepAlive …) and make launchd match it:
/// `bootout` the stale job (the script has quit the app already); with `--start` also `bootstrap` it, which
/// starts this copy under launchd now (crash relaunch in force at once). No entry = Launch at Login is off:
/// nothing is created. Never runs while the app runs from this HOME (the script quits it first). Returns the
/// exit code.
fn login_item_sync(start: bool) -> i32 {
    let home = dirs_home();
    // never reload the job under a running instance of this HOME (bootout would quit it): quit it first
    if instance::is_running(&instance::socket_path(
        macos::BUNDLE_ID,
        &home,
        macos::account_home().as_deref(),
    )) {
        eprintln!("SuryaDhana is running (this HOME): quit it first (⌘Q), then run --login-item-sync again");
        return 2;
    }
    let log_dir = home.join("Library/Logs/ai.suryadhana.terminal");
    let agent = autostart::LoginAgent::new(&home, &log_dir);
    if !agent.exists() {
        println!("Launch at Login is off (no {}): nothing to do", agent.plist.display());
        return 0;
    }
    let Some(exe) = current_exe() else {
        eprintln!("cannot resolve this copy's executable");
        return 1;
    };
    if let Err(e) = agent.write(&exe) {
        eprintln!("could not rewrite {}: {e}", agent.plist.display());
        return 1;
    }
    println!("Launch at Login entry rewritten for {}", exe.display());
    let injected = std::env::var_os("SURYADHANA_LAUNCHCTL").map(PathBuf::from);
    let tool = match autostart::launchctl_tool(&home, macos::account_home().as_deref(), injected.as_deref()) {
        Ok(t) => t,
        Err(why) => {
            println!("launchd not touched: {why}");
            return 0;
        }
    };
    let plan = if start {
        autostart::LaunchdPlan::Reload
    } else {
        autostart::LaunchdPlan::Unload
    };
    match autostart::run_launchd(&tool, &plan, macos::uid(), &agent.plist) {
        Ok(lines) => {
            println!("{}", lines.join("\n"));
            if !start {
                println!("launchd loads the new entry at the next login (or: --login-item-sync --start)");
            }
            0
        }
        Err(e) => {
            eprintln!("launchd: {e}");
            1
        }
    }
}

/// Entry point (called by main.rs).
pub fn run() {
    let args: Vec<String> = std::env::args().collect();
    if args.iter().any(|a| a == "--version") {
        println!("{}", version_text());
        return;
    }
    if args.iter().any(|a| a == "--login-item-sync") {
        std::process::exit(login_item_sync(args.iter().any(|a| a == "--start")));
    }
    crash::install_panic_hook();
    let started = Instant::now();
    let started_epoch_ms = epoch_ms();
    let st_opts = selftest::Options::from_env_and_args();
    let selftest_on = st_opts.is_some();
    let autostart_arg = std::env::args().any(|a| a == autostart::AUTOSTART_ARG);

    // single instance, before anything else exists (the self-test takes no lock)
    let mut instance_socket = None;
    let mut instance_listener = None;
    let mut instance_note = None;
    if !selftest_on {
        let home = dirs_home();
        let path = instance::socket_path(macos::BUNDLE_ID, &home, macos::account_home().as_deref());
        // a login-job start that finds the app already running (e.g. the RunAtLoad start right after the app
        // reloaded its own job) exits without stealing focus
        let msg = if autostart_arg {
            instance::LOGIN
        } else {
            instance::FOCUS
        };
        match instance::claim_with(&path, msg) {
            instance::Claim::Primary(l) => {
                instance_listener = Some(l);
                instance_socket = Some(path);
            }
            instance::Claim::Secondary => {
                eprintln!("SuryaDhana is already running: asked it to show its window");
                std::process::exit(0);
            }
            instance::Claim::Unlocked(why) => instance_note = Some(why),
        }
    }

    // R-RUST-04: crash bookkeeping BEFORE Tauri exists, so a start that fails while the app is being built is
    // counted too (and a login job that cannot even write its run marker stands down instead of looping)
    let early_config_dir = dirs_home().join("Library/Application Support").join(macos::BUNDLE_ID);
    let early_crash = if selftest_on {
        None
    } else {
        if !(cfg!(debug_assertions)
            || std::env::var("SURYADHANA_NO_AUTOSTART")
                .map(|v| v == "1")
                .unwrap_or(false))
        {
            // keep launchd-stderr.log bounded even when the app never gets as far as its setup
            autostart::LoginAgent::new(&dirs_home(), &dirs_home().join("Library/Logs").join(macos::BUNDLE_ID))
                .rotate_stderr_log();
        }
        let s = crash::startup_check(&early_config_dir, autostart_arg);
        if s.stand_down {
            let why = if s.marker_written {
                format!(
                    "{} crashes in {} min: not starting from the login job again (launchd stops relaunching after \
                     a clean exit). Open SuryaDhana by hand.",
                    s.recent_crashes,
                    crash::LOOP_WINDOW_SECS / 60
                )
            } else {
                format!(
                    "the login job could not write its run marker in {} (disk full or not writable?): not starting \
                     unaccounted (a crash could never be counted). Open SuryaDhana by hand.",
                    early_config_dir.display()
                )
            };
            eprintln!("SuryaDhana: {why}");
            crash::append_app_log(&dirs_home().join("Library/Logs").join(macos::BUNDLE_ID), &why);
            if let Some(p) = &instance_socket {
                instance::release(p);
            }
            std::process::exit(0);
        }
        Some(s)
    };

    let window_state_file = st_opts
        .as_ref()
        .map(|o| o.temp_dir.join("window-state.json").display().to_string())
        .unwrap_or_else(|| tauri_plugin_window_state::DEFAULT_FILENAME.to_string());

    let log_target = match &st_opts {
        Some(o) => tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Folder {
            path: o.log_dir(),
            file_name: Some("suryadhana".into()),
        }),
        None => tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
            file_name: Some("suryadhana".into()),
        }),
    };
    let mut log_builder = tauri_plugin_log::Builder::new()
        .clear_targets()
        .target(log_target)
        .max_file_size(5 * 1024 * 1024)
        .rotation_strategy(tauri_plugin_log::RotationStrategy::KeepSome(5))
        .timezone_strategy(tauri_plugin_log::TimezoneStrategy::UseLocal)
        .level(log::LevelFilter::Info)
        .level_for("tao", log::LevelFilter::Warn)
        .level_for("reqwest", log::LevelFilter::Warn)
        .level_for("hyper_util", log::LevelFilter::Warn);
    if selftest_on || cfg!(debug_assertions) {
        log_builder = log_builder.target(tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stderr));
    }

    // brand-new ⌘N windows reuse term-N labels: their old geometry is applied only on session restore
    let mut window_state = tauri_plugin_window_state::Builder::new()
        .with_state_flags(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED | StateFlags::FULLSCREEN)
        .with_filename(window_state_file);
    for n in 1..=64 {
        window_state = window_state.skip_initial_state(&format!("{}{n}", windows::TERM_PREFIX));
    }

    let st_for_setup = st_opts.clone();
    let socket_for_setup = instance_socket.clone();
    let app = tauri::Builder::default()
        .plugin(log_builder.build())
        .plugin(window_state.build())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .invoke_handler(tauri::generate_handler![
            commands::shell_info,
            commands::shell_status,
            commands::shell_notify,
            commands::shell_notification_permission,
            commands::shell_request_notification_permission,
            commands::shell_save_download,
            commands::shell_open_external,
            commands::shell_new_window,
            commands::shell_set_title,
            commands::boot_status,
            commands::stack_start,
            commands::stack_stop,
            commands::open_logs,
            commands::open_terminal,
        ])
        .on_menu_event(menu::on_menu_event)
        // round 3 (completeness-final-03): a window whose WebKit content process ended is logged, reloaded at
        // its current URL (bounded) and announced; without this hook the shell never learnt of it
        .on_web_content_process_terminate(|webview| {
            let app = webview.app_handle().clone();
            let label = webview.label().to_string();
            if app.try_state::<Shell>().is_some() {
                windows::content_process_terminated(&app, &label);
            }
        })
        .setup(move |app| {
            let handle = app.handle().clone();
            let paths = resolve_paths(&handle, st_for_setup.as_ref());
            let loaded = config::load(&paths.config_dir, !selftest_on);
            for w in &loaded.warnings {
                log::warn!("[config] {w}");
            }
            let cfg = loaded.config.clone();
            if let Some(o) = &st_for_setup {
                let _ = std::fs::create_dir_all(o.temp_dir.join("Downloads"));
            }
            log::info!(
                "[app] SuryaDhana {} ({}) starting{}{} · ui {} · repo {}",
                env!("CARGO_PKG_VERSION"),
                BUILD_ID,
                if selftest_on { " in SELF-TEST mode" } else { "" },
                if autostart_arg { " by the login job" } else { "" },
                config::origin_str(&cfg.ui_url),
                cfg.repo_root.display()
            );
            if let Some(why) = &instance_note {
                log::warn!("[app] running without the single-instance lock: {why}");
            }

            // crash bookkeeping (not in self-test; checked before Tauri was built, R-RUST-04): logged here
            let (crash_files, relaunched_after_crash) = match &early_crash {
                None => (None, false),
                Some(s) => {
                if s.previous_boot {
                    log::info!(
                        "[app] the previous run ended with the previous boot (power loss / forced restart): not a crash; \
                         a login start keeps its start-up grace"
                    );
                }
                if s.previous_unclean {
                    log::warn!(
                        "[app] the previous run ended without a clean exit ({} in the last {} min)",
                        s.recent_crashes,
                        crash::LOOP_WINDOW_SECS / 60
                    );
                }
                if !s.marker_written {
                    log::warn!(
                        "[app] could not write the run marker in {}: a crash of this run cannot be counted",
                        early_config_dir.display()
                    );
                }
                (Some(crash::CrashFiles::new(&early_config_dir)), s.previous_unclean)
                }
            };
            let since_boot = macos::boot_time_secs().map(|b| {
                Duration::from_secs(
                    (SystemTime::now()
                        .duration_since(UNIX_EPOCH)
                        .map(|d| d.as_secs())
                        .unwrap_or(0))
                    .saturating_sub(b),
                )
            });
            let login_start = is_login_start(
                autostart_arg,
                relaunched_after_crash,
                since_boot,
                Duration::from_secs(cfg.startup_grace_secs),
            );
            if login_start {
                log::info!(
                    "[app] login start: the boot page shows 'Starting the stack' for up to {} s (when the watchdog agent is installed)",
                    cfg.startup_grace_secs
                );
            }
            let data_store = if selftest_on {
                None // incognito webviews already
            } else {
                instance::isolated_data_store(&paths.home, macos::account_home().as_deref())
            };
            if let Some(id) = &data_store {
                log::info!(
                    "[window] HOME is not the account's home: private WebKit data store {}",
                    instance::uuid_string(id)
                );
            }
            if let Some(p) = &socket_for_setup {
                log::info!("[app] single-instance lock {}", p.display());
            }
            if !macos::disable_automatic_window_tabbing() {
                log::warn!("[window] could not turn automatic window tabbing off");
            }

            app.manage(Shell {
                cfg: cfg.clone(),
                paths: paths.clone(),
                selftest: selftest_on,
                health: HealthHub::new(),
                windows: Mutex::new(Registry::default()),
                ui_notify_limiter: Mutex::new(RateLimiter::new(20, Duration::from_secs(60))),
                external_limiter: Mutex::new(RateLimiter::new(
                    policy::EXTERNAL_OPENS_PER_MINUTE,
                    Duration::from_secs(60),
                )),
                notif_settings_limiter: Mutex::new(RateLimiter::new(1, commands::NOTIFICATION_SETTINGS_MIN_GAP)),
                notif_request_busy: AtomicBool::new(false),
                under_login_job: autostart::under_login_job(std::env::var("XPC_SERVICE_NAME").ok().as_deref()),
                autostart_pending: Mutex::new(None),
                downloads: downloads::Downloads::default(),
                shell_notify_last: Mutex::new(HashMap::new()),
                tray: Mutex::new(None),
                menu: Mutex::new(None),
                cadence: Mutex::new(StatusCadence::default()),
                notifier: Mutex::new(SvcNotifier::default()),
                opened_external: Mutex::new(vec![]),
                blocked: Mutex::new(vec![]),
                notifications: Mutex::new(vec![]),
                started,
                started_epoch_ms,
                boot_paint_epoch_ms: Mutex::new(None),
                hold_boot: AtomicBool::new(selftest_on),
                quitting: AtomicBool::new(false),
                login_start,
                start_requested: Mutex::new(None),
                agent: autostart::LoginAgent::new(&paths.home, &paths.log_dir),
                instance_socket: socket_for_setup.clone(),
                crash_files,
                data_store,
                supervision: Mutex::new(supervise::Supervision::Off("checking")),
                notif_auth: Mutex::new(None),
            });

            // 1. the remote capability must exist before any terminal page can load
            add_remote_capability(&handle, &cfg.ui_url);

            // 2. windows first (boot paint latency): main, then the restored terminal windows
            let session = Session::load(&paths.state_file);
            let plan = windows::restore_plan(&session, &cfg.ui_url);
            for (label, target) in &plan {
                // page zoom is part of the session (contract K3: restored and published to the page)
                let zoom = session
                    .windows
                    .iter()
                    .find(|w| &w.label == label)
                    .and_then(|w| w.zoom)
                    .filter(|z| z.is_finite())
                    .unwrap_or(1.0);
                if let Err(e) = windows::create_window(
                    &handle,
                    label,
                    target,
                    windows::Start::Boot,
                    windows::Placement::Restore,
                    zoom,
                ) {
                    log::error!("[window] could not create {label}: {e}");
                }
            }
            log::info!("[window] restored {} window(s)", plan.len());

            // 3. menu bar + tray
            let autostart_now = autostart::LoginAgent::new(&paths.home, &paths.log_dir).state();
            match menu::build(&handle, cfg.devtools, autostart_now) {
                Ok((m, h)) => {
                    if let Err(e) = handle.set_menu(m) {
                        log::error!("[menu] set_menu failed: {e}");
                    }
                    *handle.state::<Shell>().menu.lock().unwrap_or_else(|e| e.into_inner()) = Some(h);
                }
                Err(e) => log::error!("[menu] build failed: {e}"),
            }
            match tray::build(&handle, autostart_now, cfg.nifty_in_menubar) {
                Ok(t) => *handle.state::<Shell>().tray.lock().unwrap_or_else(|e| e.into_inner()) = Some(t),
                Err(e) => log::error!("[tray] build failed: {e}"),
            }

            // 4. health pollers drive everything else; a 1 s ticker keeps the status heartbeat <= 9 s
            let hub = handle.state::<Shell>().health.clone();
            let h2 = handle.clone();
            health::spawn_pollers(hub, cfg.clone(), paths.home.clone(), move |u| on_health_update(&h2, u));
            let h_tick = handle.clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    broadcast_status_if_due(&h_tick);
                }
            });
            // K5 (round 3): the stack's notification feed as native banners, whatever page is open
            feed::spawn(handle.clone(), paths.feed.clone());
            // round 4b: macOS's notification permission (tray hint, boot footer, the feed's sink heartbeat)
            let h_auth = handle.clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_secs(1)).await;
                loop {
                    refresh_notification_auth(&h_auth).await;
                    tokio::time::sleep(NOTIF_AUTH_EVERY).await;
                }
            });

            // 5. periodic session save (window URLs change via history.replaceState without page loads) and
            //    Launch-at-Login status (System Settings can change it behind the app's back)
            if !selftest_on {
                let h3 = handle.clone();
                tauri::async_runtime::spawn(async move {
                    loop {
                        tokio::time::sleep(Duration::from_secs(60)).await;
                        windows::save_session(&h3);
                        refresh_autostart_checks(&h3);
                    }
                });
            }

            first_run_autostart(&handle);
            maintain_autostart(&handle);
            supervise_this_copy(&handle);

            if let Some(l) = instance_listener.take() {
                let h5 = handle.clone();
                instance::serve(l, move || {
                    log::info!("[app] second launch -> focusing the main window");
                    let h6 = h5.clone();
                    let _ = h5.run_on_main_thread(move || reopen(&h6));
                });
            }

            if !selftest_on {
                let h7 = handle.clone();
                let crash_files = handle.state::<Shell>().crash_files.clone();
                let socket = socket_for_setup.clone();
                crash::install_sigterm_quit(
                    move || {
                        let h8 = h7.clone();
                        let _ = h7.run_on_main_thread(move || quit(&h8));
                    },
                    Some(Duration::from_secs(5)),
                    // the hard fallback is still a clean quit: no crash marker, no stale lock (wave-2 nit)
                    move || {
                        if let Some(c) = &crash_files {
                            c.on_clean_exit(std::process::id());
                        }
                        if let Some(p) = &socket {
                            instance::release(p);
                        }
                    },
                );
            }

            if let Some(o) = st_for_setup.clone() {
                selftest::spawn(handle.clone(), o);
            }
            Ok(())
        })
        .build(tauri::generate_context!());
    let app = match app {
        Ok(a) => a,
        Err(e) => {
            // R-RUST-04: the run marker stays (an unclean end): the next start counts it, and the crash-loop
            // breaker stands the login job down after 4 in 10 min instead of a respawn every 20 s forever
            eprintln!("SuryaDhana could not start: {e}");
            crash::append_app_log(
                &dirs_home().join("Library/Logs").join(macos::BUNDLE_ID),
                &format!("could not start: {e}"),
            );
            if let Some(p) = &instance_socket {
                instance::release(p);
            }
            std::process::exit(1);
        }
    };

    app.run(|app, event| match event {
        RunEvent::Reopen {
            has_visible_windows, ..
        } => {
            if !has_visible_windows {
                reopen(app);
            }
        }
        RunEvent::ExitRequested { .. } => {
            // save while the windows still exist (Destroyed events during shutdown must not shrink it)
            if let Some(shell) = app.try_state::<Shell>() {
                if !shell.quitting.swap(true, Ordering::SeqCst) && !shell.selftest {
                    windows::save_session(app);
                }
            }
        }
        RunEvent::Exit => {
            if let Some(shell) = app.try_state::<Shell>() {
                // R-RUST-10: logout / shutdown / Dock "Quit" end through AppKit's terminate, which never sends
                // ExitRequested: save the session here unless ⌘Q / ExitRequested already did
                if !shell.quitting.swap(true, Ordering::SeqCst) && !shell.selftest {
                    windows::save_session(app);
                }
                if let Some(c) = &shell.crash_files {
                    c.on_clean_exit(std::process::id());
                }
                // round 4b: no app = no banner sink: the scheduler's own banner comes back at once, not 3 min later
                if let Some(a) = &shell.paths.feed.alive {
                    feed::retire_alive(a);
                }
                if let Some(p) = &shell.instance_socket {
                    instance::release(p);
                }
            }
            if let Some(code) = selftest::exit_code() {
                std::process::exit(code);
            }
        }
        _ => {}
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    const G: Duration = Duration::from_secs(180);

    #[test]
    fn login_start_rules() {
        // the login job (and not a crash relaunch)
        assert!(is_login_start(true, false, Some(Duration::from_secs(86_400)), G));
        assert!(!is_login_start(true, true, Some(Duration::from_secs(86_400)), G));
        // a manual launch right after the Mac booted
        assert!(is_login_start(false, false, Some(Duration::from_secs(60)), G));
        // a manual launch on a long-running Mac
        assert!(!is_login_start(false, false, Some(Duration::from_secs(4000)), G));
        assert!(!is_login_start(false, false, None, G));
    }

    #[test]
    fn startup_phase_hides_down_state_only_while_starting() {
        let s = |up: u64, login: bool, req: Option<u64>, wd: bool| {
            startup_phase(
                Duration::from_secs(up),
                login,
                req.map(Duration::from_secs),
                wd,
                true,
                G,
            )
        };
        // C1-desktop-native-01 / C2-reliability-ops-03: at login, 15 s in, the stack is "starting", not down
        assert_eq!(s(15, true, None, false), Some(StartingReason::Login));
        assert_eq!(s(179, true, None, false), Some(StartingReason::Login));
        assert_eq!(s(181, true, None, false), None, "after the grace the down state shows");
        // a manual launch on a down stack shows the down state as before (after 15 s)
        assert_eq!(s(15, false, None, false), None);
        // Start Stack restarts the grace; a watchdog run in progress also counts
        assert_eq!(s(4000, false, Some(10), false), Some(StartingReason::StartRequested));
        assert_eq!(s(4000, false, Some(200), false), None);
        assert_eq!(s(4000, false, None, true), Some(StartingReason::Watchdog));
        assert_eq!(s(10, true, Some(5), true), Some(StartingReason::StartRequested));
        // a zero grace disables the grace states (the watchdog lock still counts)
        assert_eq!(
            startup_phase(Duration::ZERO, true, Some(Duration::ZERO), false, true, Duration::ZERO),
            None
        );
    }

    #[test]
    fn no_login_grace_without_the_watchdog_agent() {
        // wave 2 (adversarial check): at login with NO watchdog LaunchAgent nothing starts the stack, so the
        // grace must not hide Start/Stop and the install command; round 1 returned Login here
        let up = Duration::from_secs(15);
        assert_eq!(startup_phase(up, true, None, false, false, G), None);
        assert_eq!(
            startup_phase(up, true, Some(Duration::from_secs(5)), false, false, G),
            None
        );
        // control: with the agent installed (or loaded) the login grace stays
        assert_eq!(
            startup_phase(up, true, None, false, true, G),
            Some(StartingReason::Login)
        );
        // a watchdog run holding its lock is itself proof that the agent runs
        assert_eq!(
            startup_phase(up, false, None, true, false, G),
            Some(StartingReason::Watchdog)
        );
    }

    #[test]
    fn settings_text_and_version() {
        let t = settings_text(Path::new(
            "/Users/u/Library/Application Support/ai.suryadhana.terminal/config.json",
        ));
        for k in [
            "ui_url",
            "startup_grace_secs",
            "verify_ui_listener",
            "Launch at Login",
            "zoom",
            "next time",
        ] {
            assert!(t.contains(k), "{k}: {t}");
        }
        assert!(!t.contains("SYS"), "Settings is not the SYS telemetry page any more");
        assert!(version_text().contains(BUILD_ID) && version_text().starts_with("SuryaDhana "));
        // the build id: <sha7>[-dirty]-<8 hex>-<yyyymmddTHHMMZ>[-devtools][-<profile>] (R-RUST-08: a devtools or
        // debug binary never looks like a release one; `cargo test` runs the debug profile)
        let mut parts: Vec<&str> = BUILD_ID.split('-').collect();
        if !cfg!(debug_assertions) {
            assert!(!BUILD_ID.ends_with("-debug"), "{BUILD_ID}");
        } else {
            assert_eq!(parts.pop(), Some("debug"), "a debug build says so: {BUILD_ID}");
        }
        let says_devtools = parts.last() == Some(&"devtools");
        assert_eq!(
            says_devtools,
            cfg!(feature = "devtools"),
            "the id says -devtools exactly for a devtools build: {BUILD_ID}"
        );
        if says_devtools {
            parts.pop();
        }
        assert!(parts.len() == 3 || parts.len() == 4, "{BUILD_ID}");
        assert!(parts[0] == env!("SURYADHANA_BUILD"), "{BUILD_ID}");
        let src = parts[parts.len() - 2];
        assert!(
            src.len() == 8 && src.chars().all(|c| c.is_ascii_hexdigit()),
            "{BUILD_ID}"
        );
        let ts = parts[parts.len() - 1];
        assert!(
            ts.len() == 14 && ts.ends_with('Z') && ts.as_bytes()[8] == b'T',
            "{BUILD_ID}"
        );
    }
}
