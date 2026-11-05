//! IPC commands.
//!
//! **Contract v1 (granted to the remote terminal origin only, see capabilities-runtime/terminal-remote.json):**
//! `shell_info`, `shell_status`, `shell_notify`, `shell_notification_permission`,
//! `shell_request_notification_permission`, `shell_save_download`, `shell_open_external`,
//! `shell_new_window`, `shell_set_title`.
//!
//! **Boot-only (bundled boot page, capabilities/boot.json):** `boot_status`, `stack_start`,
//! `stack_stop`, `open_logs`, `open_terminal`.
//!
//! The ACL is the primary gate; each command re-checks its caller's origin (defence in depth) and
//! validates every argument in Rust. Validation failures are logged (without argument contents that
//! could carry secrets) and returned as plain error strings.

use std::time::{Duration, Instant};

use base64::Engine;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Manager, Webview};

use crate::health::{Desk, Icici, IciciView, Nifty, QuoteState, ShellStatus, TrustView, UiState};
use crate::policy::{self, MAX_BODY_LEN, MAX_TITLE_LEN};
use crate::stack::Activity;
use crate::windows::{self, BootMode, Phase};
use crate::{pages, Shell, StartingReason};

type CmdResult<T> = Result<T, String>;

fn reject<T>(cmd: &str, why: impl Into<String>) -> CmdResult<T> {
    let why = why.into();
    log::warn!("[ipc] {cmd} rejected: {why}");
    Err(why)
}

/// Defence in depth: the caller must be a terminal page on the configured ui origin.
fn require_ui(cmd: &str, webview: &Webview, shell: &Shell) -> CmdResult<()> {
    match windows::webview_url_of(webview) {
        Some(u) if policy::exact_ui_origin(&u, &shell.cfg.ui_url) => Ok(()),
        _ => reject(cmd, "caller is not the terminal origin"),
    }
}

/// Defence in depth: the caller must be the bundled boot page.
///
/// One expected race is not a warning: the shell navigates a boot window to the terminal while the boot
/// page's last 1 s `boot_status` poll is in flight; that call arrives after the webview URL changed, so it is
/// refused (as it must be) but logged at debug level. boot.js also stops polling once the page is hidden.
fn require_boot(cmd: &str, webview: &Webview, shell: &Shell) -> CmdResult<()> {
    match windows::webview_url_of(webview) {
        Some(u) if policy::is_boot_origin(&u) => Ok(()),
        Some(u) if cmd == "boot_status" && policy::exact_ui_origin(&u, &shell.cfg.ui_url) => {
            log::debug!("[ipc] boot_status refused: the window already navigated to the terminal");
            Err("caller is not the boot page".into())
        }
        _ => reject(cmd, "caller is not the boot page"),
    }
}

// ---------------------------------------------------------------------------------------------
// Contract v1 commands
// ---------------------------------------------------------------------------------------------

/// `shell_info` result. `build_id` is additive to contract v1 (completeness-04): sha + dirty flag + source
/// hash + build time, so two different shell binaries never report the same identity.
#[derive(Debug, Serialize)]
pub struct ShellInfo {
    pub version: String,
    pub build: String,
    pub build_id: String,
    pub autostart: bool,
    pub windows: usize,
    pub ui_api_url: String,
}

#[tauri::command]
pub fn shell_info(app: AppHandle, webview: Webview) -> CmdResult<ShellInfo> {
    let shell = app.state::<Shell>();
    require_ui("shell_info", &webview, &shell)?;
    Ok(ShellInfo {
        version: env!("CARGO_PKG_VERSION").into(),
        build: env!("SURYADHANA_BUILD").into(),
        build_id: crate::BUILD_ID.into(),
        autostart: crate::autostart_enabled(&app),
        windows: app.webview_windows().len(),
        ui_api_url: windows::ui_origin(&app),
    })
}

/// Cached poller value; never blocks on the network.
#[tauri::command]
pub fn shell_status(app: AppHandle, webview: Webview) -> CmdResult<ShellStatus> {
    let shell = app.state::<Shell>();
    require_ui("shell_status", &webview, &shell)?;
    Ok(shell.health.snapshot().status)
}

#[tauri::command]
pub fn shell_notify(app: AppHandle, webview: Webview, title: String, body: String) -> CmdResult<()> {
    let shell = app.state::<Shell>();
    require_ui("shell_notify", &webview, &shell)?;
    let title = policy::validate_plain_text(&title, MAX_TITLE_LEN, "title").or_else(|e| reject("shell_notify", e.0))?;
    let body = policy::validate_body_text(&body, MAX_BODY_LEN).or_else(|e| reject("shell_notify", e.0))?;
    if title.is_empty() {
        return reject("shell_notify", "title is empty");
    }
    if !shell
        .ui_notify_limiter
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .allow(Instant::now())
    {
        return reject("shell_notify", "rate limited (20 notifications per minute)");
    }
    shell.notify(&app, &title, &body);
    Ok(())
}

/// The notification plugin reports `Granted` unconditionally on macOS; the shell asks macOS itself
/// (UNUserNotificationCenter), so WTCH never claims "desktop notifications on" while System Settings has
/// them off (C1-desktop-native-10). Unknown (API unavailable / timed out) is `default`, never `granted`.
pub fn notification_permission_now() -> &'static str {
    crate::macos::notification_authorization(Duration::from_secs(2))
        .map(|a| a.as_permission())
        .unwrap_or("default")
}

#[tauri::command]
pub async fn shell_notification_permission(app: AppHandle, webview: Webview) -> CmdResult<&'static str> {
    {
        let shell = app.state::<Shell>();
        require_ui("shell_notification_permission", &webview, &shell)?;
    }
    Ok(tokio::task::spawn_blocking(notification_permission_now)
        .await
        .unwrap_or("default"))
}

/// System Settings › Notifications, at this app.
pub const NOTIFICATION_SETTINGS_URL: &str =
    "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id=ai.suryadhana.terminal";

/// System Settings › Notifications is opened at most this often by `shell_request_notification_permission`
/// (wave 2: a looping page must never keep pulling System Settings to the front).
pub const NOTIFICATION_SETTINGS_MIN_GAP: Duration = Duration::from_secs(60);

/// What a permission request does after macOS answered (pure): open System Settings only for `denied`,
/// and only when the rate limiter allows it.
pub fn should_open_notification_settings(result: &str, limiter_allows: bool) -> bool {
    result == "denied" && limiter_allows
}

/// Shows the macOS permission prompt while the state is undetermined (the UI's ENABLE button). macOS
/// never prompts again once the owner decided, so when it says `denied` the request opens System Settings ›
/// Notifications at SuryaDhana instead (the only place it can be changed), at most once a minute. Requests
/// are serialized: while one waits for the macOS prompt, further calls just report the current state (at
/// most one blocking-pool thread ever waits on it). Returns the resulting state.
#[tauri::command]
pub async fn shell_request_notification_permission(app: AppHandle, webview: Webview) -> CmdResult<&'static str> {
    {
        let shell = app.state::<Shell>();
        require_ui("shell_request_notification_permission", &webview, &shell)?;
        if shell.selftest {
            return Ok(notification_permission_now());
        }
        if shell.notif_request_busy.swap(true, std::sync::atomic::Ordering::SeqCst) {
            log::info!("[notify] permission request already waiting for macOS; reporting the current state");
            return Ok(tokio::task::spawn_blocking(notification_permission_now)
                .await
                .unwrap_or("default"));
        }
    }
    let r = tokio::task::spawn_blocking(|| {
        crate::macos::request_notification_authorization(Duration::from_secs(55))
            .map(|a| a.as_permission())
            .unwrap_or("default")
    })
    .await
    .unwrap_or("default");
    let shell = app.state::<Shell>();
    shell
        .notif_request_busy
        .store(false, std::sync::atomic::Ordering::SeqCst);
    // the limiter is consulted (and charged) only when macOS says denied
    let allowed = r == "denied"
        && shell
            .notif_settings_limiter
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .allow(Instant::now());
    log::info!("[notify] permission request -> {r}");
    if should_open_notification_settings(r, allowed) {
        use tauri_plugin_opener::OpenerExt;
        if let Err(e) = app.opener().open_url(NOTIFICATION_SETTINGS_URL, None::<&str>) {
            log::warn!("[notify] could not open the Notifications settings: {e}");
        }
    } else if r == "denied" {
        log::info!("[notify] System Settings › Notifications was opened less than a minute ago; not again");
    }
    Ok(r)
}

/// `shell_save_download` result. `path` is for display: `~/Downloads/<name>` (never the account name).
#[derive(Debug, Serialize)]
pub struct SavedPath {
    pub path: String,
}

/// Write a file the UI generated (CSV / Excel export, research data file) into ~/Downloads: sanitized,
/// allowlisted, unique name, quarantined, rate- and size-limited; the owner gets a notification either way.
#[tauri::command]
pub async fn shell_save_download(
    app: AppHandle,
    webview: Webview,
    filename: String,
    base64: String,
) -> CmdResult<SavedPath> {
    let shell = app.state::<Shell>();
    require_ui("shell_save_download", &webview, &shell)?;
    let shown = policy::download_filename(&filename);
    let fail = |why: String| -> CmdResult<SavedPath> {
        crate::download_failed(&app, &shown, &why);
        reject("shell_save_download", why)
    };
    if base64.len() > policy::max_base64_len() {
        return fail("the file is larger than 50 MB".into());
    }
    let Ok(bytes) = base64::engine::general_purpose::STANDARD.decode(base64.trim().as_bytes()) else {
        return reject("shell_save_download", "content is not valid base64");
    };
    if bytes.len() > policy::MAX_DOWNLOAD_BYTES {
        return fail("the file is larger than 50 MB".into());
    }
    let dir = shell.paths.downloads_dir.clone();
    if let Err(why) = shell
        .downloads
        .admit(Some(bytes.len() as u64), crate::macos::free_bytes(&dir))
    {
        return fail(why);
    }
    let dir2 = dir.clone();
    let res = tokio::task::spawn_blocking(move || {
        crate::downloads::save_bytes(&dir2, &filename, &bytes).map(|p| (p, bytes.len()))
    })
    .await
    .map_err(|e| std::io::Error::other(e.to_string()))
    .and_then(|r| r);
    match res {
        Ok((path, n)) => {
            crate::download_saved(&app, &path, Some(n as u64));
            Ok(SavedPath {
                path: crate::downloads::display_path(&path, Some(&shell.paths.home)),
            })
        }
        Err(e) => fail(crate::downloads::describe_error(&e)),
    }
}

#[tauri::command]
pub fn shell_open_external(app: AppHandle, webview: Webview, url: String) -> CmdResult<()> {
    let shell = app.state::<Shell>();
    require_ui("shell_open_external", &webview, &shell)?;
    let u = policy::validate_external_url(&url).or_else(|e| reject("shell_open_external", e.0))?;
    log::info!("[nav] shell_open_external {}", policy::redact_url(&u));
    crate::open_external(&app, u).or_else(|e| reject("shell_open_external", e))
}

/// `shell_new_window` result.
#[derive(Debug, Serialize)]
pub struct NewWindow {
    pub label: String,
}

/// `{tab?, sym?}` (contract K4: `sym` is an NSE symbol `^[A-Z0-9&_.-]{1,20}$`, validated here; the window
/// opens `ui_url/?tab=<tab>&sym=<SYM>` and the UI shows that stock's window).
#[tauri::command]
pub async fn shell_new_window(
    app: AppHandle,
    webview: Webview,
    tab: Option<String>,
    sym: Option<String>,
) -> CmdResult<NewWindow> {
    {
        let shell = app.state::<Shell>();
        require_ui("shell_new_window", &webview, &shell)?;
    }
    let tab = match tab.as_deref() {
        None | Some("") => pages::DEFAULT_TAB,
        Some(t) => policy::validate_tab(t).or_else(|e| reject("shell_new_window", e.0))?,
    };
    let sym = match sym.as_deref() {
        None | Some("") => None,
        Some(s) => Some(policy::validate_symbol(s).or_else(|e| reject("shell_new_window", e.0))?),
    };
    let label = windows::open_new_terminal(&app, &windows::deep_link_target(tab, sym))
        .or_else(|e| reject("shell_new_window", e))?;
    Ok(NewWindow { label })
}

#[tauri::command]
pub fn shell_set_title(app: AppHandle, webview: Webview, title: String) -> CmdResult<()> {
    let shell = app.state::<Shell>();
    require_ui("shell_set_title", &webview, &shell)?;
    let title =
        policy::validate_plain_text(&title, MAX_TITLE_LEN, "title").or_else(|e| reject("shell_set_title", e.0))?;
    webview
        .window()
        .set_title(if title.is_empty() { "SuryaDhana" } else { &title })
        .map_err(|e| e.to_string())
}

// ---------------------------------------------------------------------------------------------
// Boot-only commands
// ---------------------------------------------------------------------------------------------

/// One service row on the boot page.
#[derive(Debug, Serialize)]
pub struct ServiceRow {
    pub name: &'static str,
    pub port: Option<u16>,
    pub role: &'static str,
    pub up: bool,
    pub latency_ms: Option<f64>,
    /// `up` · `down` · `not_responding` (port held, /health timing out: hung, see health::StallTracker)
    pub state: &'static str,
    /// Seconds it has been not responding.
    pub stalled_secs: Option<u64>,
}

/// Pure: the row state of a service.
pub fn row_state(up: bool, stalled: bool) -> &'static str {
    match (up, stalled) {
        (true, _) => "up",
        (false, true) => "not_responding",
        (false, false) => "down",
    }
}

/// Pure: may the boot page show "Starting the stack"? Never while the terminal is reachable, and never for a
/// ui-api that holds its port but is not answering (it is running, hung: nothing is starting it; PM 25 Oct).
pub fn starting_applies(ui_ready: bool, ui_state: UiState) -> bool {
    !ui_ready && ui_state != UiState::NotResponding
}

/// Active restart-freeze window.
#[derive(Debug, Serialize)]
pub struct Freeze {
    pub label: &'static str,
}

/// The start-up grace the boot page shows instead of the down state.
#[derive(Debug, Serialize)]
pub struct Starting {
    pub reason: StartingReason,
    /// Seconds since the login start (app start) / Start was chosen / the watchdog run began (its lock).
    pub elapsed_secs: u64,
    pub grace_secs: u64,
}

/// Pure: the elapsed time the boot page shows for a starting reason (wave 2: a watchdog run is timed by its
/// own lock, never by the app's uptime, so a run hours into a session is not "taking longer than usual").
pub fn starting_elapsed(
    reason: StartingReason,
    app_uptime: Duration,
    since_start_request: Option<Duration>,
    watchdog_run_secs: Option<u64>,
) -> Duration {
    match reason {
        StartingReason::StartRequested => since_start_request.unwrap_or_default(),
        StartingReason::Watchdog => Duration::from_secs(watchdog_run_secs.unwrap_or(0)),
        StartingReason::Login => app_uptime,
    }
}

/// Everything the boot page renders (boot-only: not part of the frozen UI contract).
#[derive(Debug, Serialize)]
pub struct BootStatus {
    pub version: String,
    pub build: String,
    pub build_id: String,
    pub label: String,
    pub mode: BootMode,
    pub phase: Phase,
    pub target_tab: Option<&'static str>,
    pub target_code: Option<&'static str>,
    pub ui_url: String,
    pub services: Vec<ServiceRow>,
    pub icici: Icici,
    /// Round 4b (P4): the session with its reason: connected | expired | unreachable | credentials | unknown
    /// (`icici` stays the 3-state value for an older boot page).
    pub icici_view: IciciView,
    pub ui_build: Option<String>,
    pub ui_ready: bool,
    /// Why the terminal can (not) open: `api_down` vs `no_release` (build-ui / rollback) vs `untrusted`…
    pub ui_state: UiState,
    pub ui_detail: String,
    /// The port-squatting guard's last verdict (`{state, detail}`).
    pub trust: TrustView,
    pub nifty: Option<Nifty>,
    pub nifty_state: QuoteState,
    pub desk: Option<Desk>,
    /// Seconds the terminal has been unreachable (None while reachable or before the first poll).
    pub down_secs: Option<u64>,
    pub polls: u64,
    pub freeze: Option<Freeze>,
    pub ist: String,
    pub repo_ok: bool,
    pub selftest: bool,
    /// Set while the stack is (probably) starting: no red down state, no Start/Stop.
    pub starting: Option<Starting>,
    /// Watchdog / paused markers / macOS privacy preflight.
    pub stack: Activity,
    /// The repo root (for the remedy commands shown on the page).
    pub repo: String,
    /// Round 3: this window is held on the boot page after repeated page crashes (mode `crashed`).
    pub crash_hold: bool,
    /// Content-process terminations of this window in the last 5 min.
    pub recent_crashes: usize,
    /// Round 4b: macOS's notification permission for the app (granted | denied | default | unknown); the boot
    /// page's footer says where to turn them on while it is `denied`.
    pub notifications: &'static str,
}

/// `paint`: epoch ms of the boot page's first painted frame (sent once by boot.js); the navigator
/// leaves the boot page only after it has painted.
#[tauri::command]
pub fn boot_status(
    app: AppHandle,
    webview: Webview,
    refresh: Option<bool>,
    paint: Option<f64>,
) -> CmdResult<BootStatus> {
    let shell = app.state::<Shell>();
    require_boot("boot_status", &webview, &shell)?;
    if refresh.unwrap_or(false) {
        shell.health.poke();
    }
    let label = webview.window().label().to_string();
    if let Some(p) = paint.filter(|p| p.is_finite() && *p > 0.0) {
        shell
            .boot_paint_epoch_ms
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get_or_insert(p);
        if let Some(w) = shell
            .windows
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .wins
            .get_mut(&label)
        {
            w.boot_painted = true;
        }
    }
    let snap = shell.health.snapshot();
    let (mode, phase, target, crash_hold, recent_crashes) = {
        let reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        reg.get(&label)
            .map(|w| {
                let recent = w.crashes.iter().filter(|t| t.elapsed() < windows::CRASH_WINDOW).count();
                (w.mode, w.phase, w.target.clone(), w.crash_hold, recent)
            })
            .unwrap_or((
                BootMode::Boot,
                Phase::Boot,
                windows::tab_target(pages::DEFAULT_TAB),
                false,
                0,
            ))
    };
    let tab = windows::tab_of(&target);
    let st = &snap.status;
    let cfg = &shell.cfg;
    // ShellStatus / stalled order: ui-api 0, data-service 1, master-controller 2
    let stall = |i: usize| snap.stalled[i].map(|t| t.elapsed().as_secs());
    let row = |name, port, role, svc: &crate::health::Svc, i: usize| ServiceRow {
        name,
        port,
        role,
        up: svc.up,
        latency_ms: svc.latency_ms,
        state: row_state(svc.up, stall(i).is_some()),
        stalled_secs: if svc.up { None } else { stall(i) },
    };
    let services = vec![
        row(
            "data-service",
            cfg.data_service_url.port(),
            "DuckDB owner · NSE ingest · live ticks",
            &st.data_service,
            1,
        ),
        row(
            "ui-api",
            cfg.ui_url.port(),
            "terminal backend · API · UI",
            &st.ui_api,
            0,
        ),
        row(
            "master-controller",
            cfg.controller_url.port(),
            "IST scheduler · Telegram · jobs",
            &st.master_controller,
            2,
        ),
    ];
    let notifications = shell
        .notif_auth
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .map(|a| a.as_permission())
        .unwrap_or("unknown");
    let now = time::OffsetDateTime::now_utc();
    let starting = if !starting_applies(snap.ui_ready, snap.ui_state) {
        None
    } else {
        shell.starting(&snap.stack).map(|reason| {
            let requested = shell
                .start_requested
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .map(|t| t.elapsed());
            let since = starting_elapsed(reason, shell.started.elapsed(), requested, snap.stack.watchdog_run_secs);
            Starting {
                reason,
                elapsed_secs: since.as_secs(),
                grace_secs: shell.cfg.startup_grace_secs,
            }
        })
    };
    Ok(BootStatus {
        version: env!("CARGO_PKG_VERSION").into(),
        build: env!("SURYADHANA_BUILD").into(),
        build_id: crate::BUILD_ID.into(),
        label,
        mode,
        phase,
        target_tab: tab,
        target_code: tab.and_then(pages::by_id).map(|p| p.code),
        ui_url: windows::ui_origin(&app),
        services,
        icici: st.icici,
        icici_view: snap.icici_view,
        ui_build: st.ui_build.clone(),
        ui_ready: snap.ui_ready,
        ui_state: snap.ui_state,
        ui_detail: snap.ui_detail.clone(),
        trust: snap.trust.clone(),
        nifty: st.nifty,
        nifty_state: snap.quote_state,
        desk: snap.desk.clone(),
        down_secs: snap.unready_since.map(|t| t.elapsed().as_secs()),
        polls: snap.polls,
        freeze: policy::freeze_window_at(now).map(|w| Freeze { label: w.label }),
        ist: policy::ist_clock(now),
        repo_ok: crate::stack::StackPaths::new(&cfg.repo_root).validate().is_ok(),
        selftest: shell.selftest,
        starting,
        stack: snap.stack.clone(),
        repo: cfg.repo_root.display().to_string(),
        crash_hold,
        recent_crashes,
        notifications,
    })
}

#[tauri::command]
pub async fn stack_start(app: AppHandle, webview: Webview) -> CmdResult<String> {
    {
        let shell = app.state::<Shell>();
        require_boot("stack_start", &webview, &shell)?;
        if shell.selftest {
            return reject("stack_start", "disabled in self-test");
        }
    }
    let app2 = app.clone();
    tokio::task::spawn_blocking(move || crate::stack_start(&app2))
        .await
        .unwrap_or_else(|_| Err("Start Stack failed".into()))
        .or_else(|e| reject("stack_start", e))
}

#[tauri::command]
pub async fn stack_stop(app: AppHandle, webview: Webview) -> CmdResult<String> {
    {
        let shell = app.state::<Shell>();
        require_boot("stack_stop", &webview, &shell)?;
        if shell.selftest {
            return reject("stack_stop", "disabled in self-test");
        }
    }
    if let Err(w) = crate::stack::stop_guard(time::OffsetDateTime::now_utc()) {
        return reject(
            "stack_stop",
            format!("Refused: inside the restart-freeze window {}", w.label),
        );
    }
    if !crate::confirm_stop(&app).await {
        return Err("cancelled".into());
    }
    crate::stack_stop_confirmed(&app).or_else(|e| reject("stack_stop", e))
}

/// `open_logs` argument: which folder (default: the stack's `.logs`, the useful one when it is down).
#[derive(Debug, Deserialize, Clone, Copy)]
#[serde(rename_all = "lowercase")]
pub enum LogsArg {
    App,
    Stack,
}

#[tauri::command]
pub fn open_logs(app: AppHandle, webview: Webview, target: Option<LogsArg>) -> CmdResult<()> {
    require_boot("open_logs", &webview, &app.state::<Shell>())?;
    crate::open_folder(
        &app,
        match target.unwrap_or(LogsArg::Stack) {
            LogsArg::App => crate::LogsTarget::App,
            LogsArg::Stack => crate::LogsTarget::Stack,
        },
    );
    Ok(())
}

#[tauri::command]
pub fn open_terminal(app: AppHandle, webview: Webview, tab: Option<String>) -> CmdResult<Value> {
    let shell = app.state::<Shell>();
    require_boot("open_terminal", &webview, &shell)?;
    let label = webview.window().label().to_string();
    if let Some(t) = tab.as_deref().filter(|t| !t.is_empty()) {
        let t = policy::validate_tab(t).or_else(|e| reject("open_terminal", e.0))?;
        if let Some(w) = shell
            .windows
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .wins
            .get_mut(&label)
        {
            w.target = windows::tab_target(t);
        }
    }
    // the owner's "try again" after repeated page crashes (boot page: PAGE STOPPED)
    if windows::release_crash_hold(&app, &label) {
        log::info!("[window] {label}: Open terminal now after a crash hold");
    }
    let snap = shell.health.snapshot();
    if !snap.ui_ready {
        shell.health.poke();
        return Err(match snap.ui_state {
            UiState::NoRelease => "ui-api has no terminal UI release to serve yet (./start-local.sh build-ui).".into(),
            UiState::NotResponding => format!(
                "{} (./start-local.sh restart ui-api if it does not recover).",
                snap.ui_detail
            ),
            UiState::Untrusted => format!("Not opening the terminal port: {}", snap.ui_detail),
            UiState::Unverifiable => format!(
                "Not opening the terminal port: {} (./start-local.sh restart ui-api).",
                snap.ui_detail
            ),
            _ => "The terminal is not reachable yet (ui-api down or the UI not served).".into(),
        });
    }
    windows::navigate_to_terminal(&app, &label);
    Ok(serde_json::json!({"label": label}))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn watchdog_runs_are_timed_by_their_lock_not_the_app_uptime() {
        let hours = Duration::from_secs(5 * 3600);
        // the adversarial check's case: the app has run for hours, a watchdog run (restarting a crashed
        // ui-api) began 40 s ago: the page shows 40 s (round 1 showed ~300 min "taking longer than usual")
        assert_eq!(
            starting_elapsed(StartingReason::Watchdog, hours, None, Some(40)),
            Duration::from_secs(40)
        );
        assert_eq!(
            starting_elapsed(
                StartingReason::StartRequested,
                hours,
                Some(Duration::from_secs(12)),
                Some(40)
            ),
            Duration::from_secs(12)
        );
        assert_eq!(
            starting_elapsed(StartingReason::Login, Duration::from_secs(30), None, None),
            Duration::from_secs(30)
        );
        assert_eq!(
            starting_elapsed(StartingReason::Watchdog, hours, None, None),
            Duration::ZERO
        );
    }

    #[test]
    fn a_hung_ui_api_never_shows_starting() {
        // PM 25 Oct: ui-api held :8010 with its event loop blocked; a watchdog run / login grace was active
        assert!(!starting_applies(false, UiState::NotResponding));
        assert!(
            starting_applies(false, UiState::ApiDown),
            "control: a closed port may be starting"
        );
        assert!(!starting_applies(true, UiState::Ready));
        assert_eq!(row_state(false, true), "not_responding");
        assert_eq!(row_state(false, false), "down");
        assert_eq!(row_state(true, true), "up");
    }

    #[test]
    fn denied_opens_system_settings_at_most_once_a_minute() {
        let mut rl = policy::RateLimiter::new(1, NOTIFICATION_SETTINGS_MIN_GAP);
        let t0 = Instant::now();
        let mut opened = 0;
        // a looping page calls the request 100 times in 10 s while macOS says denied
        for i in 0..100u64 {
            let allows = rl.allow(t0 + Duration::from_millis(i * 100));
            if should_open_notification_settings("denied", allows) {
                opened += 1;
            }
        }
        assert_eq!(opened, 1, "round 1 opened System Settings on every call");
        assert!(
            rl.allow(t0 + NOTIFICATION_SETTINGS_MIN_GAP + Duration::from_secs(1)),
            "again after a minute"
        );
        assert!(!should_open_notification_settings("granted", true));
        assert!(!should_open_notification_settings("default", true));
    }
}
