//! Window manager: the boot -> terminal lifecycle, multi-window, session restore, navigation guards,
//! downloads and `suryadhana:shell` event delivery.
//!
//! Lifecycle of every window (label `main` or `term-N`):
//! ```text
//!   Boot (bundled tauri://localhost/index.html, black, paints instantly)
//!     └─ ui-api /health up AND GET / serves text/html AND the port listener is not definitively foreign
//!          ──► Loading (navigate to ui_url/?tab=…)
//!          ├─ the ui-origin page COMMITTED (first byte rendered) ──► Terminal
//!          └─ nothing committed within 12 s (connection refused…) ──► Boot (mode "reconnecting"), retried
//! ```
//! A Terminal window is never yanked away when ui-api blips (the UI shows its own banner and recovers), and
//! a committed page is never timed out because a slow iframe (TradingView) or image delays its full load
//! (C1-desktop-native-08). The one exception: if the terminal port is answered by a process the port-squatting
//! guard positively identifies as foreign (or cannot identify at all: round 3), every window goes back to the
//! boot page, which names the process; an inconclusive check never moves a window (wave 2).
//!
//! A crashed page (round 3, completeness-final-03): when a window's WebKit content process ends (a WebKit
//! bug, a GPU-process reset, memory pressure), WebKit calls the shell (`on_web_content_process_terminate`).
//! The window is logged, reloaded at its current URL (or sent to the boot page when the terminal is not
//! reachable) and the owner gets one notice; at most [`CRASH_RELOADS`] automatic reloads per window in
//! [`CRASH_WINDOW`], after that the window stays on the boot page ("PAGE STOPPED", Open terminal now / ⌘R),
//! so a page that crashes on load can never loop.
//!
//! Security: every navigation goes through `policy::navigation_decision`; only the shell itself can
//! send a window to the privileged boot page (one-shot permit), main-frame loads off the allowlist are
//! bounced, new-window requests become terminal windows (same origin) or open in the default browser.
//!
//! Never call a webview API while holding the registry lock (WebKit callbacks re-enter on the main
//! thread and take the same lock).

use std::collections::{BTreeMap, HashMap};
use std::path::Path;
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};
use tauri::webview::{DownloadEvent, NewWindowResponse, PageLoadEvent};
use tauri::{
    AppHandle, LogicalPosition, Manager, Theme, TitleBarStyle, Url, WebviewUrl, WebviewWindow, WebviewWindowBuilder,
    WindowEvent,
};
use tauri_plugin_window_state::{StateFlags, WindowExt as _};

use crate::config::{origin_str, write_atomic};
use crate::health::UiState;
use crate::policy::{
    self, main_frame_allowed, navigation_decision, new_window_decision, redact_url, NavContext, NavDecision,
    NewWindowDecision,
};
use crate::{pages, Shell};

/// Label of the primary window (never destroyed: closing hides it).
pub const MAIN: &str = "main";
/// Label prefix of additional terminal windows.
pub const TERM_PREFIX: &str = "term-";
/// Maximum number of SuryaDhana windows (main included).
pub const MAX_WINDOWS: usize = 8;
/// The bundled boot page.
pub const BOOT_URL: &str = "tauri://localhost/index.html";
/// A load that has not committed after this long is treated as failed.
const LOAD_TIMEOUT: Duration = Duration::from_secs(12);
/// Minimum spacing between navigation attempts per window.
const RETRY_SPACING: Duration = Duration::from_secs(3);
/// How long a shell-initiated boot-page navigation permit stays valid.
const BOOT_PERMIT: Duration = Duration::from_secs(10);
/// Session file schema version.
const SESSION_VERSION: u32 = 1;
/// Leave the boot page only after it has painted (or after this long, whichever comes first).
const BOOT_MIN_SHOW: Duration = Duration::from_millis(1500);
/// Default and minimum content size (logical px). 960 wide lets two windows tile on a 1920 px display.
pub const DEFAULT_SIZE: (f64, f64) = (1600.0, 1000.0);
pub const MIN_SIZE: (f64, f64) = (960.0, 620.0);
/// Offset of a new window from the window it was opened from.
const CASCADE: f64 = 28.0;

/// How a new window is placed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Placement {
    /// Session restore (and main): the window-state plugin's saved geometry for this label.
    Restore,
    /// ⌘N / shell_new_window / window.open: cascade from the focused (else last-used) window on its
    /// display, clamped to that display's work area; an earlier window's geometry under the same label is
    /// NOT reused (C1-desktop-native-15).
    Cascade,
}

/// Where a new window starts.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Start {
    /// The bundled boot page (launch, restore, terminal not reachable).
    Boot,
    /// Straight to the terminal URL (⌘N while the terminal is up: no boot flash).
    Terminal,
}

/// Where a window is in its lifecycle.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Phase {
    Boot,
    Loading,
    Terminal,
}

/// Why a window shows the boot page.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum BootMode {
    Boot,
    Reconnecting,
    /// Its page crashed more than [`CRASH_RELOADS`] times in [`CRASH_WINDOW`]: held on the boot page.
    Crashed,
}

/// Automatic reloads of one window after its content process ended, per [`CRASH_WINDOW`].
pub const CRASH_RELOADS: usize = 3;
/// The window the crash budget counts in.
pub const CRASH_WINDOW: Duration = Duration::from_secs(300);

/// What to do after a window's WebKit content process ended (pure decision, see [`crash_decision`]).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CrashAction {
    /// Reload the window at its current URL (this many crashes in the window so far, this one included).
    Reload(usize),
    /// Over the budget: keep it on the boot page until the owner opens the terminal again.
    Hold(usize),
}

/// Pure: record a content-process termination at `now` and decide. Terminations older than [`CRASH_WINDOW`]
/// are forgotten; the (`CRASH_RELOADS` + 1)th within it holds the window.
pub fn crash_decision(recent: &mut std::collections::VecDeque<Instant>, now: Instant) -> CrashAction {
    while recent
        .front()
        .map(|t| now.duration_since(*t) >= CRASH_WINDOW)
        .unwrap_or(false)
    {
        recent.pop_front();
    }
    recent.push_back(now);
    if recent.len() > CRASH_RELOADS {
        CrashAction::Hold(recent.len())
    } else {
        CrashAction::Reload(recent.len())
    }
}

/// Per-window shell state.
#[derive(Debug, Clone)]
pub struct WinInfo {
    pub phase: Phase,
    pub mode: BootMode,
    /// Path + query on the ui origin to open (e.g. `/?tab=desk`).
    pub target: String,
    boot_permit_until: Option<Instant>,
    loading_since: Option<Instant>,
    last_attempt: Option<Instant>,
    /// UI build id observed when this window's terminal page finished loading.
    pub loaded_build: Option<String>,
    pub zoom: f64,
    /// First time a terminal page finished loading in this window (self-test timing).
    pub first_terminal_at: Option<Instant>,
    /// When the boot page was (re)requested for this window.
    pub boot_since: Instant,
    /// The boot page reported its first painted frame (the navigator waits for it, max BOOT_MIN_SHOW).
    pub boot_painted: bool,
    /// When the ui-origin page of the current load committed (None while still provisional).
    pub committed_at: Option<Instant>,
    /// Recent WebKit content-process terminations of this window (round 3; see [`crash_decision`]).
    pub crashes: std::collections::VecDeque<Instant>,
    /// Held on the boot page after too many crashes: the navigator does not open the terminal by itself.
    pub crash_hold: bool,
    /// The terminal path + query last read from the live page (every status broadcast, so at most ~8 s old).
    /// A crashed window is reloaded HERE: WebKit resets the URL to nil when the content process ends, and the
    /// page changes tabs with history.replaceState, so `target` alone may name an older tab (round 3).
    pub last_seen: Option<String>,
}

impl WinInfo {
    fn new(target: String) -> Self {
        Self {
            phase: Phase::Boot,
            mode: BootMode::Boot,
            target,
            boot_permit_until: Some(Instant::now() + BOOT_PERMIT),
            loading_since: None,
            last_attempt: None,
            loaded_build: None,
            zoom: 1.0,
            first_terminal_at: None,
            boot_since: Instant::now(),
            boot_painted: false,
            committed_at: None,
            crashes: Default::default(),
            crash_hold: false,
            last_seen: None,
        }
    }
}

/// All windows the shell manages.
#[derive(Debug, Default)]
pub struct Registry {
    pub wins: BTreeMap<String, WinInfo>,
    /// The last SuryaDhana window that had focus (menu/tray actions target it while the app is inactive).
    pub last_focused: Option<String>,
}

impl Registry {
    pub fn get(&self, label: &str) -> Option<&WinInfo> {
        self.wins.get(label)
    }

    /// Consume-free check of the boot permit (valid for a few seconds; WebKit may ask twice).
    pub fn boot_permitted(&self, label: &str) -> bool {
        self.wins
            .get(label)
            .and_then(|w| w.boot_permit_until)
            .map(|t| Instant::now() < t)
            .unwrap_or(false)
    }

    /// Lowest free `term-N` label.
    pub fn next_term_label(&self, existing: &[String]) -> String {
        (1..=64)
            .map(|n| format!("{TERM_PREFIX}{n}"))
            .find(|l| !self.wins.contains_key(l) && !existing.contains(l))
            .unwrap_or_else(|| format!("{TERM_PREFIX}{}", self.wins.len() + 1))
    }

    /// Any window waiting for the terminal (drives the 1 s fast poll).
    pub fn any_waiting(&self) -> bool {
        self.wins.values().any(|w| w.phase != Phase::Terminal)
    }
}

// ---------------------------------------------------------------------------------------------
// Session persistence (state.json)
// ---------------------------------------------------------------------------------------------

/// One saved window.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SavedWindow {
    pub label: String,
    /// Current URL (ui origin only; anything else is dropped before saving).
    pub url: String,
    /// Page zoom when not 100 % (View ▸ Zoom In/Out), restored with the window.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub zoom: Option<f64>,
}

/// `state.json`: open windows + first-run markers.
#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct Session {
    #[serde(default)]
    pub version: u32,
    #[serde(default)]
    pub windows: Vec<SavedWindow>,
    /// Legacy first-run marker (read only: the marker now lives in `.autostart-initialized`, which the
    /// "reset window layout" recipe does not delete).
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub autostart_initialized: bool,
}

impl Session {
    pub fn load(path: &Path) -> Session {
        std::fs::read_to_string(path)
            .ok()
            .and_then(|t| serde_json::from_str::<Session>(&t).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        let mut s = self.clone();
        s.version = SESSION_VERSION;
        write_atomic(path, &(serde_json::to_string_pretty(&s).unwrap_or_default() + "\n"))
    }
}

/// Validate a path+query target on the ui origin; falls back to the default page.
pub fn sanitize_target(target: &str) -> String {
    let t = target.trim();
    if t.starts_with('/') && !t.starts_with("//") && !t.contains('\\') && t.len() <= 1024 && !t.contains('#') {
        t.to_string()
    } else {
        format!("/?tab={}", pages::DEFAULT_TAB)
    }
}

/// `/?tab=<tab>` for a validated tab id.
pub fn tab_target(tab: &str) -> String {
    format!("/?tab={}", policy::validate_tab(tab).unwrap_or(pages::DEFAULT_TAB))
}

/// `/?tab=<tab>&sym=<SYM>` for a validated tab and an optional validated NSE symbol (contract K4: the UI
/// opens the stock window for `sym`). The symbol is URL-encoded (`M&M` -> `M%26M`).
pub fn deep_link_target(tab: &str, sym: Option<&str>) -> String {
    let tab = policy::validate_tab(tab).unwrap_or(pages::DEFAULT_TAB);
    let mut q = url::form_urlencoded::Serializer::new(String::new());
    q.append_pair("tab", tab);
    if let Some(s) = sym.and_then(|s| policy::validate_symbol(s).ok()) {
        q.append_pair("sym", s);
    }
    format!("/?{}", q.finish())
}

/// Terminal URL for a target, guaranteed to be on the ui origin.
pub fn terminal_url(ui: &Url, target: &str) -> Url {
    let t = sanitize_target(target);
    match ui.join(&t) {
        Ok(u) if policy::same_ui_origin(&u, ui) => u,
        _ => ui.join(&tab_target(pages::DEFAULT_TAB)).expect("default target joins"),
    }
}

/// Saved URL -> target on the current ui origin (falls back to its `tab` param, then the default page).
pub fn target_from_saved(saved: &str, ui: &Url) -> String {
    let Ok(u) = Url::parse(saved) else {
        return tab_target(pages::DEFAULT_TAB);
    };
    if policy::same_ui_origin(&u, ui) {
        let mut t = u.path().to_string();
        if let Some(q) = u.query() {
            t.push('?');
            t.push_str(q);
        }
        return sanitize_target(&t);
    }
    let tab = u
        .query_pairs()
        .find(|(k, _)| k == "tab")
        .map(|(_, v)| v.to_string())
        .unwrap_or_default();
    tab_target(&tab)
}

/// Tab id in a target / URL query, if valid.
pub fn tab_of(target: &str) -> Option<&'static str> {
    let q = target.split_once('?').map(|(_, q)| q).unwrap_or("");
    url::form_urlencoded::parse(q.as_bytes())
        .find(|(k, _)| k == "tab")
        .and_then(|(_, v)| pages::by_id(&v).map(|p| p.id))
}

/// Restorable windows from a session: `main` first (always), then up to MAX_WINDOWS-1 `term-N`.
pub fn restore_plan(session: &Session, ui: &Url) -> Vec<(String, String)> {
    let mut out = vec![];
    let main = session.windows.iter().find(|w| w.label == MAIN);
    out.push((
        MAIN.to_string(),
        main.map(|w| target_from_saved(&w.url, ui))
            .unwrap_or_else(|| tab_target(pages::DEFAULT_TAB)),
    ));
    let mut seen = vec![MAIN.to_string()];
    for w in &session.windows {
        let valid_label = w
            .label
            .strip_prefix(TERM_PREFIX)
            .map(|n| !n.is_empty() && n.len() <= 2 && n.chars().all(|c| c.is_ascii_digit()))
            .unwrap_or(false);
        if valid_label && !seen.contains(&w.label) && out.len() < MAX_WINDOWS {
            seen.push(w.label.clone());
            out.push((w.label.clone(), target_from_saved(&w.url, ui)));
        }
    }
    out
}

// ---------------------------------------------------------------------------------------------
// Event delivery
// ---------------------------------------------------------------------------------------------

/// JS that dispatches `suryadhana:shell` with a JSON literal (no string interpolation of untrusted text).
pub fn shell_event_js(detail: &serde_json::Value) -> String {
    let json = serde_json::to_string(detail).unwrap_or_else(|_| "null".into());
    let json = json.replace('\u{2028}', "\\u2028").replace('\u{2029}', "\\u2029");
    format!(
        "(function(){{try{{window.dispatchEvent(new CustomEvent('suryadhana:shell',{{detail:{json}}}));}}catch(e){{}}}})();"
    )
}

/// What this shell does beyond contract v1, as `__SURYADHANA_SHELL__.features` (additive; the UI checks a name
/// before it hands a job to the shell, so a newer UI on an older app keeps doing it itself).
/// * `notification_feed` (round 3, K5): the shell posts the stack's notification feed (price alerts etc.) as
///   native banners itself (feed.rs), so a page must not post the same events again (WTCH's alert check).
pub const SHELL_FEATURES: &[&str] = &["notification_feed"];

/// The document-start script for every window (contract v1 detection object, read-only), plus the
/// window's page zoom at creation as `window.__SURYADHANA_ZOOM__` (contract K3; the shell updates the value
/// and sends `{type:'zoom', factor}` whenever it changes and after every terminal page load).
pub fn init_script(zoom: f64) -> String {
    let shell = serde_json::json!({
        "api": 1,
        "version": env!("CARGO_PKG_VERSION"),
        "build": env!("SURYADHANA_BUILD"),
        "platform": "macos",
        "features": SHELL_FEATURES,
    });
    let zoom = if zoom.is_finite() { clamp_zoom(zoom) } else { 1.0 };
    format!(
        "(function(){{try{{if(!('__SURYADHANA_SHELL__' in window)){{Object.defineProperty(window,'__SURYADHANA_SHELL__',{{value:Object.freeze({shell}),writable:false,configurable:false,enumerable:false}});}}window.__SURYADHANA_ZOOM__={zoom};}}catch(e){{}}}})();"
    )
}

/// Page zoom limits (View ▸ Zoom In / Out).
pub const ZOOM_MIN: f64 = 0.5;
pub const ZOOM_MAX: f64 = 2.0;

/// Clamp and round a zoom factor to the menu's 10 % steps.
pub fn clamp_zoom(z: f64) -> f64 {
    ((z * 10.0).round() / 10.0).clamp(ZOOM_MIN, ZOOM_MAX)
}

/// JS that publishes a window's zoom to its page: `window.__SURYADHANA_ZOOM__` and, when `notify`, the
/// additive shell event `{type:'zoom', factor}` (contract K3).
pub fn zoom_js(factor: f64, notify: bool) -> String {
    let set = format!("try{{window.__SURYADHANA_ZOOM__={factor};}}catch(e){{}}");
    if notify {
        format!(
            "{set}{}",
            shell_event_js(&serde_json::json!({"type": "zoom", "factor": factor}))
        )
    } else {
        set
    }
}

/// Self-test windows only: pin the UI's prefs sync to read-only before any page script runs, so a self-test
/// against the live ui-api never writes the owner's prefs store (the QA rule for every browser context that
/// loads the live terminal; `suryadhana.prefs.mode`, ui/lib/prefs/keys.ts). Never used outside --self-test.
pub const SELFTEST_PREFS_READONLY_JS: &str = "(function(){try{if(location.protocol==='http:'||location.protocol==='https:'){localStorage.setItem('suryadhana.prefs.mode','readonly');}}catch(e){}})();";

/// A window's current URL, never panicking (round 3). NEVER call tauri's `WebviewWindow::url()` in the shell:
/// wry 0.57.1 unwraps WKWebView's `URL`, which is nil once the page's WebContent process ended, so a single
/// call on a crashed window panicked the main thread and ended the app (the 8 s status broadcast alone did it
/// within seconds of any WebKit crash). This reads the property itself on the main thread (synchronously when
/// called there) and treats nil as None. Off the main thread it waits at most 2 s, like the getter it replaces.
pub fn webview_url(w: &WebviewWindow) -> Option<Url> {
    let (tx, rx) = std::sync::mpsc::channel::<Option<String>>();
    w.with_webview(move |pw| {
        let _ = tx.send(crate::macos::wkwebview_url(pw.inner()));
    })
    .ok()?;
    url_answer(rx)
}

/// [`webview_url`] for the `Webview` an IPC command comes from (commands.rs).
pub fn webview_url_of(w: &tauri::Webview) -> Option<Url> {
    let (tx, rx) = std::sync::mpsc::channel::<Option<String>>();
    w.with_webview(move |pw| {
        let _ = tx.send(crate::macos::wkwebview_url(pw.inner()));
    })
    .ok()?;
    url_answer(rx)
}

fn url_answer(rx: std::sync::mpsc::Receiver<Option<String>>) -> Option<Url> {
    rx.recv_timeout(Duration::from_secs(2))
        .ok()
        .flatten()
        .and_then(|s| Url::parse(&s).ok())
}

/// Send a `suryadhana:shell` event to one window if (and only if) it is showing the terminal origin.
pub fn send_event(app: &AppHandle, label: &str, detail: &serde_json::Value) -> bool {
    let shell = app.state::<Shell>();
    let Some(w) = app.get_webview_window(label) else {
        return false;
    };
    match webview_url(&w) {
        Some(u) if policy::exact_ui_origin(&u, &shell.cfg.ui_url) => {
            if let Some(info) = shell
                .windows
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .wins
                .get_mut(label)
            {
                info.last_seen = Some(ui_path(&u));
            }
            w.eval(shell_event_js(detail)).is_ok()
        }
        _ => false,
    }
}

/// Pure: path + query of a terminal URL, sanitized like every window target.
pub fn ui_path(u: &Url) -> String {
    let mut t = u.path().to_string();
    if let Some(q) = u.query() {
        t.push('?');
        t.push_str(q);
    }
    sanitize_target(&t)
}

/// Send to every terminal window; returns how many received it.
pub fn broadcast(app: &AppHandle, detail: &serde_json::Value) -> usize {
    let labels: Vec<String> = {
        let shell = app.state::<Shell>();
        let reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        reg.wins
            .iter()
            .filter(|(_, w)| w.phase == Phase::Terminal)
            .map(|(l, _)| l.clone())
            .collect()
    };
    labels.iter().filter(|l| send_event(app, l, detail)).count()
}

/// The focused SuryaDhana window, else the last-used one (while the app is inactive, e.g. a tray click),
/// else `main`.
pub fn focused_label(app: &AppHandle) -> String {
    let wins = app.webview_windows();
    if let Some((l, _)) = wins.iter().find(|(_, w)| w.is_focused().unwrap_or(false)) {
        return l.clone();
    }
    let last = app
        .state::<Shell>()
        .windows
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .last_focused
        .clone();
    match last {
        Some(l) if wins.contains_key(&l) => l,
        _ => MAIN.to_string(),
    }
}

/// Pure: where a cascaded window goes. `anchor` = the source window's outer position, `area` = its
/// display's work area (x, y, w, h), all logical px. Returns (x, y, w, h), fully inside the area when the
/// area allows it; the offset wraps back to the area's corner instead of walking off-screen.
pub fn cascade_rect(
    anchor: (f64, f64),
    area: (f64, f64, f64, f64),
    size: (f64, f64),
    min: (f64, f64),
) -> (f64, f64, f64, f64) {
    let (ax, ay, aw, ah) = area;
    let w = size.0.min(aw).max(min.0.min(aw));
    let h = size.1.min(ah).max(min.1.min(ah));
    let mut x = anchor.0 + CASCADE;
    let mut y = anchor.1 + CASCADE;
    if x + w > ax + aw || x < ax {
        x = ax + CASCADE.min((aw - w).max(0.0));
    }
    if y + h > ay + ah || y < ay {
        y = ay + CASCADE.min((ah - h).max(0.0));
    }
    (x, y, w, h)
}

/// The cascade rectangle for a new window opened from `from` (None when unknown).
fn cascade_from(app: &AppHandle, from: &str) -> Option<(f64, f64, f64, f64)> {
    let w = app.get_webview_window(from)?;
    let scale = w.scale_factor().unwrap_or(1.0);
    let pos = w.outer_position().ok()?.to_logical::<f64>(scale);
    let mon = w.current_monitor().ok().flatten()?;
    let ms = mon.scale_factor();
    let wa = mon.work_area();
    let area = (
        wa.position.x as f64 / ms,
        wa.position.y as f64 / ms,
        wa.size.width as f64 / ms,
        wa.size.height as f64 / ms,
    );
    Some(cascade_rect((pos.x, pos.y), area, DEFAULT_SIZE, MIN_SIZE))
}

/// Go to a page in the focused window (or main): a `goto` event for a loaded terminal, else the
/// window's pending target is updated so it opens there.
pub fn goto(app: &AppHandle, tab: &str) {
    let Ok(tab) = policy::validate_tab(tab) else { return };
    let label = focused_label(app);
    show_window(app, &label);
    let phase = {
        let shell = app.state::<Shell>();
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        match reg.wins.get_mut(&label) {
            Some(w) if w.phase != Phase::Terminal => {
                w.target = tab_target(tab);
                Some(w.phase)
            }
            Some(w) => Some(w.phase),
            None => None,
        }
    };
    if phase == Some(Phase::Terminal) {
        send_event(app, &label, &serde_json::json!({"type": "goto", "tab": tab}));
    }
}

/// Open the GO command bar in the focused terminal window.
pub fn command_bar(app: &AppHandle) {
    let label = focused_label(app);
    send_event(app, &label, &serde_json::json!({"type": "command-bar"}));
}

// ---------------------------------------------------------------------------------------------
// Window creation
// ---------------------------------------------------------------------------------------------

fn nav_context_permitted(app: &AppHandle, label: &str) -> bool {
    let shell = app.state::<Shell>();
    let reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
    reg.boot_permitted(label)
}

/// Build a SuryaDhana window (`target` = path+query on the terminal origin). `Start::Boot` shows the
/// boot page first; `Start::Terminal` loads the terminal directly (a failed load falls back to boot).
pub fn create_window(
    app: &AppHandle,
    label: &str,
    target: &str,
    start: Start,
    placement: Placement,
    zoom: f64,
) -> tauri::Result<WebviewWindow> {
    let shell = app.state::<Shell>();
    let target = sanitize_target(target);
    let zoom = if zoom.is_finite() { clamp_zoom(zoom) } else { 1.0 };
    // the window it is opened from (before the new one takes focus)
    let cascade = match placement {
        Placement::Cascade => cascade_from(app, &focused_label(app)),
        Placement::Restore => None,
    };
    let initial = {
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        let mut info = WinInfo::new(target.clone());
        info.zoom = zoom;
        let url = match start {
            Start::Boot => WebviewUrl::App("index.html".into()),
            Start::Terminal => {
                info.phase = Phase::Loading;
                info.loading_since = Some(Instant::now());
                info.last_attempt = Some(Instant::now());
                info.boot_permit_until = None;
                WebviewUrl::External(terminal_url(&shell.cfg.ui_url, &target))
            }
        };
        reg.wins.insert(label.to_string(), info);
        url
    };
    shell.health.fast_mode.store(true, std::sync::atomic::Ordering::Relaxed);

    let cfg = &shell.cfg;
    let mut builder = WebviewWindowBuilder::new(app, label, initial)
        .title("SuryaDhana")
        .inner_size(DEFAULT_SIZE.0, DEFAULT_SIZE.1)
        .min_inner_size(MIN_SIZE.0, MIN_SIZE.1)
        .prevent_overflow()
        .title_bar_style(TitleBarStyle::Overlay)
        .hidden_title(true)
        // y = 18 centres the 14 pt buttons on the 32 px title strip (D4 Swift probe: centre = y − 2 px)
        .traffic_light_position(LogicalPosition::new(14.0, 18.0))
        .background_color(tauri::window::Color(0, 0, 0, 255))
        .theme(Some(Theme::Dark))
        .initialization_script(if shell.selftest {
            format!("{}{}", init_script(zoom), SELFTEST_PREFS_READONLY_JS)
        } else {
            init_script(zoom)
        })
        .disable_drag_drop_handler()
        .devtools(cfg!(feature = "devtools") && cfg.devtools)
        .incognito(shell.selftest);

    if let Some(id) = shell.data_store {
        builder = builder.data_store_identifier(id);
    }
    match (label == MAIN, cascade) {
        (true, _) => builder = builder.center(),
        (false, Some((x, y, w, h))) => builder = builder.position(x, y).inner_size(w, h),
        (false, None) => builder = builder.center(),
    }

    // ---- navigation allowlist ----
    let app_nav = app.clone();
    let label_nav = label.to_string();
    builder = builder.on_navigation(move |url| {
        let permitted = nav_context_permitted(&app_nav, &label_nav);
        let shell = app_nav.state::<Shell>();
        let ctx = NavContext {
            ui: &shell.cfg.ui_url,
            boot_permitted: permitted,
            frame_hosts: &shell.cfg.frame_hosts,
        };
        match navigation_decision(url, &ctx) {
            NavDecision::Allow => true,
            NavDecision::Canonical(c) => {
                log::info!("[nav] {label_nav}: terminal origin alias -> {}", redact_url(&c));
                if let Some(w) = app_nav.get_webview_window(&label_nav) {
                    let _ = w.navigate(c);
                }
                false
            }
            NavDecision::OpenExternal => {
                log::info!("[nav] {label_nav}: external {} -> default browser", redact_url(url));
                let _ = crate::open_external(&app_nav, url.clone());
                false
            }
            NavDecision::Deny(why) => {
                log::warn!("[nav] {label_nav}: blocked {} ({why})", redact_url(url));
                shell.record_blocked(url);
                false
            }
        }
    });

    // ---- window.open / target=_blank ----
    let app_nw = app.clone();
    builder = builder.on_new_window(move |url, _features| {
        let shell = app_nw.state::<Shell>();
        match new_window_decision(&url, &shell.cfg.ui_url) {
            NewWindowDecision::Terminal(target) => {
                let app2 = app_nw.clone();
                tauri::async_runtime::spawn(async move {
                    if let Err(e) = open_new_terminal(&app2, &target) {
                        log::warn!("[window] new terminal window refused: {e}");
                    }
                });
            }
            NewWindowDecision::External => {
                log::info!("[nav] window.open external {} -> default browser", redact_url(&url));
                let _ = crate::open_external(&app_nw, url.clone());
            }
            NewWindowDecision::Deny(why) => {
                log::warn!("[nav] window.open blocked {} ({why})", redact_url(&url));
                shell.record_blocked(&url);
            }
        }
        NewWindowResponse::Deny
    });

    // ---- downloads (<a download>, blob:, attachment responses) ----
    // Only the terminal origin and its own blob: URLs may download (never data:, which any frame can mint,
    // including the TradingView iframe: C2-security-05); same name allowlist, limits and quarantine as
    // shell_save_download (downloads.rs).
    let app_dl = app.clone();
    let pending: std::sync::Arc<std::sync::Mutex<crate::downloads::Pending>> = Default::default();
    builder = builder.on_download(move |_webview, event| {
        let shell = app_dl.state::<Shell>();
        match event {
            DownloadEvent::Requested { url, destination } => {
                // every refusal is recorded: WebKit still reports a failed Finished for it, under the same
                // URL, which must not take the entry of a download of that URL that is still running
                let mut admit = || -> bool {
                    if !download_source_allowed(&url, &shell.cfg.ui_url) {
                        log::warn!("[download] refused from {}", redact_url(&url));
                        shell.record_blocked(&url);
                        return false;
                    }
                    let suggested = destination
                        .file_name()
                        .map(|s| s.to_string_lossy().to_string())
                        .unwrap_or_default();
                    // R-RUST-03: one download per URL at a time (WebKit's events carry only the URL)
                    if pending
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .busy(url.as_str(), Instant::now())
                    {
                        crate::download_failed(
                            &app_dl,
                            &policy::download_filename(&suggested),
                            "it is already being saved: wait for it to finish, then try again",
                        );
                        return false;
                    }
                    let dir = shell.paths.downloads_dir.clone();
                    if let Err(why) = shell.downloads.admit(None, crate::macos::free_bytes(&dir)) {
                        crate::download_failed(&app_dl, &policy::download_filename(&suggested), &why);
                        return false;
                    }
                    match crate::downloads::free_name(&dir, &suggested) {
                        Ok(n) => {
                            let path = dir.join(n);
                            log::info!("[download] {} -> {}", redact_url(&url), path.display());
                            let begun = pending.lock().unwrap_or_else(|e| e.into_inner()).begin(
                                url.as_str(),
                                path.clone(),
                                Instant::now(),
                            );
                            match begun {
                                Ok(()) => {
                                    *destination = path;
                                    true
                                }
                                Err(why) => {
                                    crate::download_failed(&app_dl, &policy::download_filename(&suggested), why);
                                    false
                                }
                            }
                        }
                        Err(e) => {
                            crate::download_failed(&app_dl, &policy::download_filename(&suggested), &e);
                            false
                        }
                    }
                };
                let admitted = admit();
                if !admitted {
                    pending
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .refuse(url.as_str(), Instant::now());
                }
                admitted
            }
            DownloadEvent::Finished { url, success, .. } => {
                let path =
                    pending
                        .lock()
                        .unwrap_or_else(|e| e.into_inner())
                        .finish(url.as_str(), success, Instant::now());
                let name = path
                    .as_ref()
                    .and_then(|p| p.file_name())
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| "file".into());
                match (success, path) {
                    (true, Some(p)) => {
                        // charge the hourly byte budget now that the size is known (same budget as
                        // shell_save_download); over budget / under the free-space floor = removed again
                        let size = std::fs::symlink_metadata(&p).map(|m| m.len()).unwrap_or(0);
                        let dir = p.parent().map(Path::to_path_buf).unwrap_or_default();
                        let kept = shell
                            .downloads
                            .charge_finished(size, crate::macos::free_bytes(&dir))
                            .and_then(|()| {
                                crate::downloads::quarantine_finished(&p)
                                    .map_err(|e| format!("could not tag it for Gatekeeper ({e}); removed"))
                            });
                        match kept {
                            Ok(()) => crate::download_saved(&app_dl, &p, Some(size)),
                            Err(why) => {
                                // an over-budget or untagged file must not stay behind
                                let _ = std::fs::remove_file(&p);
                                crate::download_failed(&app_dl, &name, &why);
                            }
                        }
                    }
                    // a download the shell refused (or never admitted) ends as a failure too: already logged
                    (_, None) => log::info!(
                        "[download] {} ended without a file (refused or not admitted)",
                        redact_url(&url)
                    ),
                    (false, Some(_)) => crate::download_failed(&app_dl, &name, "the download did not complete"),
                }
                true
            }
            _ => true,
        }
    });

    // ---- page loads: phase tracking + main-frame guard ----
    let app_pl = app.clone();
    builder = builder.on_page_load(move |window, payload| {
        let url = payload.url().clone();
        let label = window.label().to_string();
        let shell = app_pl.state::<Shell>();
        let ui = shell.cfg.ui_url.clone();
        if !main_frame_allowed(&url, &ui) {
            if matches!(payload.event(), PageLoadEvent::Started) {
                log::warn!(
                    "[nav] {label}: main frame left the allowlist ({}); bouncing",
                    redact_url(&url)
                );
                if policy::is_external_http(&url) {
                    let _ = crate::open_external(&app_pl, url.clone());
                }
                let app2 = app_pl.clone();
                tauri::async_runtime::spawn(async move { bounce(&app2, &label) });
            }
            return;
        }
        let is_ui = policy::same_ui_origin(&url, &ui);
        match payload.event() {
            // committed: the terminal page is there (C1-desktop-native-08: the 12 s timeout is about
            // commits; a slow iframe or image must never bounce a rendered terminal back to the boot page)
            PageLoadEvent::Started if is_ui => {
                let build = shell.health.snapshot().status.ui_build;
                let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
                let mut zoom = 1.0;
                if let Some(w) = reg.wins.get_mut(&label) {
                    w.boot_permit_until = None;
                    w.phase = Phase::Terminal;
                    w.mode = BootMode::Boot;
                    w.loading_since = None;
                    w.committed_at = Some(Instant::now());
                    w.loaded_build = build;
                    zoom = w.zoom;
                }
                drop(reg);
                // the new document's zoom variable (the init script carries the creation-time value)
                let _ = window.eval(zoom_js(zoom, false));
                log::info!("[window] {label}: terminal committed {}", redact_url(&url));
            }
            PageLoadEvent::Finished => {
                let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
                let mut zoom = None;
                if let Some(w) = reg.wins.get_mut(&label) {
                    // the permit is one load long: once a page has finished, the boot page is locked again
                    w.boot_permit_until = None;
                    if is_ui {
                        w.phase = Phase::Terminal;
                        w.loading_since = None;
                        w.first_terminal_at.get_or_insert_with(Instant::now);
                        zoom = Some(w.zoom);
                        log::info!("[window] {label}: terminal loaded {}", redact_url(&url));
                    } else if policy::is_boot_origin(&url) && w.phase == Phase::Terminal {
                        w.phase = Phase::Boot;
                    }
                }
                drop(reg);
                // contract K3: every terminal page learns its zoom once it has loaded (listeners exist now)
                if let Some(z) = zoom.filter(|_| policy::exact_ui_origin(&url, &ui)) {
                    let _ = window.eval(zoom_js(z, true));
                }
            }
            _ => {}
        }
    });

    let window = builder.build()?;
    apply_zoom(&window, zoom);
    // session restore of a term-N window: the plugin skips term-N labels at creation (so ⌘N windows never
    // inherit an old window's geometry), the restore applies it here
    if placement == Placement::Restore && label != MAIN {
        let _ = window
            .restore_state(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED | StateFlags::FULLSCREEN);
    }

    // ---- close = hide for main (leaving full screen first); destroy for term-N ----
    let app_ev = app.clone();
    let label_ev = label.to_string();
    let w2 = window.clone();
    window.on_window_event(move |ev| match ev {
        WindowEvent::CloseRequested { api, .. } if label_ev == MAIN => {
            api.prevent_close();
            if w2.is_fullscreen().unwrap_or(false) {
                // hiding a full-screen window leaves an empty black Space behind (C1-desktop-native-14):
                // leave full screen, wait for the transition, then hide
                let _ = w2.set_fullscreen(false);
                let w3 = w2.clone();
                tauri::async_runtime::spawn(async move {
                    for _ in 0..30 {
                        tokio::time::sleep(Duration::from_millis(100)).await;
                        if !w3.is_fullscreen().unwrap_or(false) {
                            break;
                        }
                    }
                    tokio::time::sleep(Duration::from_millis(250)).await;
                    let _ = w3.hide();
                });
                log::info!("[window] main left full screen and is hidden (app keeps running in the menu bar)");
            } else {
                let _ = w2.hide();
                log::info!("[window] main hidden (app keeps running in the menu bar)");
            }
        }
        WindowEvent::Focused(true) => {
            let shell = app_ev.state::<Shell>();
            shell.windows.lock().unwrap_or_else(|e| e.into_inner()).last_focused = Some(label_ev.clone());
        }
        WindowEvent::Destroyed => {
            let shell = app_ev.state::<Shell>();
            shell
                .windows
                .lock()
                .unwrap_or_else(|e| e.into_inner())
                .wins
                .remove(&label_ev);
            log::info!("[window] {label_ev} closed");
            // during quit every window is destroyed: the session was saved before, keep it
            if !shell.quitting.load(std::sync::atomic::Ordering::SeqCst) && !shell.selftest {
                save_session(&app_ev);
            }
        }
        _ => {}
    });
    Ok(window)
}

/// Open another terminal window (⌘N, ⌥⌘N, shell_new_window, same-origin window.open). Errors at the limit.
/// The new window takes the zoom of the window it is opened from (same display, same density).
pub fn open_new_terminal(app: &AppHandle, target: &str) -> Result<String, String> {
    let existing: Vec<String> = app.webview_windows().keys().cloned().collect();
    if existing.len() >= MAX_WINDOWS {
        return Err(format!("window limit reached ({MAX_WINDOWS})"));
    }
    let label = {
        let shell = app.state::<Shell>();
        let reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        reg.next_term_label(&existing)
    };
    let ready = app.state::<Shell>().health.snapshot().ui_ready;
    let zoom = zoom_of(app, &focused_label(app));
    create_window(
        app,
        &label,
        target,
        if ready { Start::Terminal } else { Start::Boot },
        Placement::Cascade,
        zoom,
    )
    .map_err(|e| e.to_string())?;
    if !app.state::<Shell>().selftest {
        save_session(app);
    }
    Ok(label)
}

/// Show, unminimize and focus a window.
pub fn show_window(app: &AppHandle, label: &str) {
    if let Some(w) = app.get_webview_window(label) {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

/// Navigate a window to its terminal target (sets phase Loading).
pub fn navigate_to_terminal(app: &AppHandle, label: &str) -> bool {
    let shell = app.state::<Shell>();
    let target = {
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        let Some(w) = reg.wins.get_mut(label) else { return false };
        w.phase = Phase::Loading;
        w.loading_since = Some(Instant::now());
        w.last_attempt = Some(Instant::now());
        w.boot_permit_until = None;
        w.committed_at = None;
        w.target.clone()
    };
    let url = terminal_url(&shell.cfg.ui_url, &target);
    match app.get_webview_window(label) {
        Some(w) => {
            log::info!("[window] {label}: opening terminal {}", redact_url(&url));
            w.navigate(url).is_ok()
        }
        None => false,
    }
}

/// Send a window back to the boot page (shell-initiated: grants the one-shot permit).
pub fn navigate_to_boot(app: &AppHandle, label: &str, mode: BootMode) {
    let shell = app.state::<Shell>();
    {
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        let Some(w) = reg.wins.get_mut(label) else { return };
        w.phase = Phase::Boot;
        w.mode = mode;
        w.loading_since = None;
        w.boot_permit_until = Some(Instant::now() + BOOT_PERMIT);
    }
    shell.health.fast_mode.store(true, std::sync::atomic::Ordering::Relaxed);
    if let Some(w) = app.get_webview_window(label) {
        let on_boot = webview_url(&w).map(|u| policy::is_boot_origin(&u)).unwrap_or(false);
        if !on_boot {
            {
                let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
                if let Some(info) = reg.wins.get_mut(label) {
                    info.boot_painted = false;
                    info.boot_since = Instant::now();
                }
            }
            let _ = w.navigate(Url::parse(BOOT_URL).expect("boot url"));
        }
    }
}

/// Main frame went somewhere it must not: back to the last terminal target, or the boot page.
fn bounce(app: &AppHandle, label: &str) {
    let ready = app.state::<Shell>().health.snapshot().ui_ready;
    if ready {
        navigate_to_terminal(app, label);
    } else {
        navigate_to_boot(app, label, BootMode::Reconnecting);
    }
}

/// Run after every fast health poll: move waiting windows to the terminal when it is up, send windows
/// whose load never committed back to the boot page ("reconnecting"), and pull every window off the
/// terminal origin when its port fails the port-squatting guard.
pub fn navigator_tick(app: &AppHandle, ui_ready: bool, ui_state: UiState) {
    let shell = app.state::<Shell>();
    let now = Instant::now();
    let hold = shell.hold_boot.load(std::sync::atomic::Ordering::Relaxed);
    let ui_ready = ui_ready && !hold;
    let mut go: Vec<String> = vec![];
    let mut back: Vec<String> = vec![];
    let mut evict: Vec<String> = vec![];
    let waiting = {
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        for (label, w) in reg.wins.iter_mut() {
            if crate::health::evicts(ui_state) && w.phase != Phase::Boot {
                evict.push(label.clone());
                continue;
            }
            let spaced = w
                .last_attempt
                .map(|t| now.duration_since(t) >= RETRY_SPACING)
                .unwrap_or(true);
            match w.phase {
                Phase::Boot
                    if ui_ready
                        && spaced
                        && !w.crash_hold
                        && (w.boot_painted || now.duration_since(w.boot_since) > BOOT_MIN_SHOW) =>
                {
                    go.push(label.clone())
                }
                Phase::Loading
                    if w.committed_at.is_none()
                        && w.loading_since
                            .map(|t| now.duration_since(t) > LOAD_TIMEOUT)
                            .unwrap_or(false) =>
                {
                    back.push(label.clone())
                }
                _ => {}
            }
        }
        reg.any_waiting()
    };
    shell
        .health
        .fast_mode
        .store(waiting, std::sync::atomic::Ordering::Relaxed);
    for l in go {
        navigate_to_terminal(app, &l);
    }
    for l in back {
        log::warn!(
            "[window] {l}: terminal did not load within {}s; back to the boot page",
            LOAD_TIMEOUT.as_secs()
        );
        navigate_to_boot(app, &l, BootMode::Reconnecting);
    }
    for l in evict {
        log::warn!("[window] {l}: the terminal port is held by an unexpected process; back to the boot page");
        navigate_to_boot(app, &l, BootMode::Reconnecting);
    }
}

/// Pure: may a WebKit download come from `url`? Only the terminal origin and its own blob: URLs.
pub fn download_source_allowed(url: &Url, ui: &Url) -> bool {
    policy::same_ui_origin(url, ui)
        || (url.scheme() == "blob"
            && Url::parse(url.path())
                .map(|u| policy::same_ui_origin(&u, ui))
                .unwrap_or(false))
}

/// Persist the open windows (ui-origin URLs only). No-op in self-test isolation without a state file.
pub fn save_session(app: &AppHandle) {
    let shell = app.state::<Shell>();
    let ui = shell.cfg.ui_url.clone();
    let targets: HashMap<String, (String, f64)> = {
        let reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        reg.wins
            .iter()
            .map(|(l, w)| (l.clone(), (w.target.clone(), w.zoom)))
            .collect()
    };
    let mut windows = vec![];
    for (label, w) in app.webview_windows() {
        if !targets.contains_key(&label) {
            continue;
        }
        let (target, zoom) = &targets[&label];
        let url = match webview_url(&w) {
            Some(u) if policy::same_ui_origin(&u, &ui) => u.to_string(),
            _ => terminal_url(&ui, target).to_string(),
        };
        let zoom = ((*zoom - 1.0).abs() > 1e-6).then_some(*zoom);
        windows.push(SavedWindow { label, url, zoom });
    }
    windows.sort_by(|a, b| (a.label != MAIN, &a.label).cmp(&(b.label != MAIN, &b.label)));
    let mut session = Session::load(&shell.paths.state_file);
    session.windows = windows;
    if let Err(e) = session.save(&shell.paths.state_file) {
        log::warn!("[session] save failed: {e}");
    }
}

/// Pure: the next zoom factor for ⌘= (`+0.1`), ⌘- (`-0.1`) or ⌘0 (None = reset to 100 %).
pub fn next_zoom(current: f64, delta: Option<f64>) -> f64 {
    match delta {
        None => 1.0,
        Some(d) => clamp_zoom(current + d),
    }
}

/// Zoom the focused window (View ▸ Zoom In ⌘= / Zoom Out ⌘- / Actual Size ⌘0): WebKit page zoom, kept per
/// window (saved with the session) and published to the page (contract K3) so its title strip can keep the
/// traffic-light inset at a constant screen width.
pub fn zoom(app: &AppHandle, delta: Option<f64>) {
    let label = focused_label(app);
    let shell = app.state::<Shell>();
    let z = {
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        let Some(w) = reg.wins.get_mut(&label) else { return };
        w.zoom = next_zoom(w.zoom, delta);
        w.zoom
    };
    if let Some(w) = app.get_webview_window(&label) {
        let _ = w.set_zoom(z);
    }
    publish_zoom(app, &label, z, true);
    log::info!("[window] {label}: zoom {:.0} %", z * 100.0);
}

/// Apply a window's zoom to its webview (session restore; after creation).
pub fn apply_zoom(w: &WebviewWindow, z: f64) {
    if (z - 1.0).abs() > 1e-6 {
        let _ = w.set_zoom(z);
    }
}

/// Tell a terminal page its zoom (variable always; the event when `notify`). Boot pages are skipped.
pub fn publish_zoom(app: &AppHandle, label: &str, factor: f64, notify: bool) {
    let shell = app.state::<Shell>();
    if let Some(w) = app.get_webview_window(label) {
        if webview_url(&w)
            .map(|u| policy::exact_ui_origin(&u, &shell.cfg.ui_url))
            .unwrap_or(false)
        {
            let _ = w.eval(zoom_js(factor, notify));
        }
    }
}

/// The zoom factor of a window (1.0 when unknown).
pub fn zoom_of(app: &AppHandle, label: &str) -> f64 {
    app.state::<Shell>()
        .windows
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .get(label)
        .map(|w| w.zoom)
        .unwrap_or(1.0)
}

/// Go ▸ Back (⌘[) / Forward (⌘]) in the focused window: the terminal's own page history (C1-trader-ux-09).
/// Only a terminal page is driven; the boot page and a window still loading are left alone, and a step
/// back past the first terminal entry (the boot page) is refused by the navigation policy, so it can never
/// leave the terminal.
pub fn history(app: &AppHandle, back: bool) {
    let label = focused_label(app);
    let shell = app.state::<Shell>();
    let phase = shell
        .windows
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .get(&label)
        .map(|w| w.phase);
    let Some(w) = app.get_webview_window(&label) else {
        return;
    };
    let on_terminal = webview_url(&w)
        .map(|u| policy::exact_ui_origin(&u, &shell.cfg.ui_url))
        .unwrap_or(false);
    if phase != Some(Phase::Terminal) || !on_terminal {
        crate::macos::beep();
        return;
    }
    let _ = w.eval(history_js(back));
}

/// Pure (round 4b, R9): why File ▸ Print… must not print this window, or None when it may. Only a visible,
/// non-minimized window that shows the terminal page is printed: never the boot page (or a window held there
/// after crashes), a window still loading, a hidden one (⌘W hides `main`; a tray click targets it), or one that
/// already shows a sheet (a second ⌘P while the print panel is open). `sheet` = None: no native view.
pub fn print_refusal(
    phase: Option<Phase>,
    visible: bool,
    minimized: bool,
    on_terminal: bool,
    sheet: Option<bool>,
) -> Option<&'static str> {
    if !visible || minimized {
        return Some("the window is hidden or minimized");
    }
    if phase != Some(Phase::Terminal) || !on_terminal {
        return Some("the window does not show the terminal (boot page, or still loading)");
    }
    match sheet {
        Some(false) => None,
        Some(true) => Some("a print or save panel is already open on the window"),
        None => Some("the window has no native view"),
    }
}

/// File ▸ Print… (⌘P) on the focused window (see [`print_window`]).
pub fn print(app: &AppHandle) -> Result<(), &'static str> {
    print_window(app, &focused_label(app))
}

/// Print one window's terminal page through WebKit's own print panel (`WebviewWindow::print`: a sheet on that
/// window, where the owner picks a printer or Save as PDF). Refused (Err with the reason) per [`print_refusal`].
pub fn print_window(app: &AppHandle, label: &str) -> Result<(), &'static str> {
    let shell = app.state::<Shell>();
    let phase = shell
        .windows
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .get(label)
        .map(|w| w.phase);
    let Some(w) = app.get_webview_window(label) else {
        return Err("no such window");
    };
    let visible = w.is_visible().unwrap_or(false);
    let minimized = w.is_minimized().unwrap_or(false);
    let on_terminal = webview_url(&w)
        .map(|u| policy::exact_ui_origin(&u, &shell.cfg.ui_url))
        .unwrap_or(false);
    if let Some(why) = print_refusal(phase, visible, minimized, on_terminal, webview_sheet(&w)) {
        return Err(why);
    }
    w.print().map_err(|e| {
        log::warn!("[print] {label}: {e}");
        "WebKit did not accept the print request"
    })?;
    log::info!("[print] {label}: print panel requested");
    Ok(())
}

/// Does this window show a sheet (print / save panel)? None when it has no native view (see
/// [`crate::macos::webview_window_has_sheet`]); read on the main thread, at most 2 s wait elsewhere.
pub fn webview_sheet(w: &WebviewWindow) -> Option<bool> {
    let (tx, rx) = std::sync::mpsc::channel::<Option<bool>>();
    w.with_webview(move |pw| {
        let _ = tx.send(crate::macos::webview_window_has_sheet(pw.inner()));
    })
    .ok()?;
    rx.recv_timeout(Duration::from_secs(2)).ok().flatten()
}

/// Self-test only: cancel the sheet on this window (the print panel's Cancel). Returns whether one was there.
pub fn cancel_sheet(w: &WebviewWindow) -> bool {
    let (tx, rx) = std::sync::mpsc::channel::<bool>();
    if w.with_webview(move |pw| {
        let _ = tx.send(crate::macos::cancel_webview_window_sheet(pw.inner()));
    })
    .is_err()
    {
        return false;
    }
    rx.recv_timeout(Duration::from_secs(2)).unwrap_or(false)
}

/// Pure: the history step (never past the first terminal entry: `history.length` > 1 is checked in the page).
pub fn history_js(back: bool) -> &'static str {
    if back {
        "(function(){try{if(history.length>1){history.back();}}catch(e){}})();"
    } else {
        "(function(){try{history.forward();}catch(e){}})();"
    }
}

/// Path + query of what a window shows on the terminal origin (its live URL, else its pending target).
pub fn current_target(app: &AppHandle, label: &str) -> Option<String> {
    let shell = app.state::<Shell>();
    let ui = shell.cfg.ui_url.clone();
    let live = app
        .get_webview_window(label)
        .and_then(|w| webview_url(&w))
        .and_then(|u| policy::same_ui_origin(&u, &ui).then(|| ui_path(&u)));
    live.or_else(|| {
        shell
            .windows
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .get(label)
            .map(|w| w.target.clone())
    })
}

/// Where a crashed window is reloaded: its live URL if WebKit still has one, else [`WinInfo::last_seen`], else its
/// target (see [`crash_reload_target`]).
fn reload_target(app: &AppHandle, label: &str) -> Option<String> {
    let shell = app.state::<Shell>();
    let live = app
        .get_webview_window(label)
        .and_then(|w| webview_url(&w))
        .filter(|u| policy::same_ui_origin(u, &shell.cfg.ui_url))
        .map(|u| ui_path(&u));
    let reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
    let w = reg.get(label)?;
    Some(crash_reload_target(live, w.last_seen.as_deref(), &w.target))
}

/// Pure: the live page, else the last one seen, else the window's target.
pub fn crash_reload_target(live: Option<String>, last_seen: Option<&str>, target: &str) -> String {
    live.or_else(|| last_seen.map(str::to_string))
        .unwrap_or_else(|| target.to_string())
}

/// Reload the focused window (boot page reloads keep their permit). On a window held after repeated page
/// crashes, ⌘R is the owner's "try again": the hold is lifted and the terminal opens when it is reachable.
pub fn reload(app: &AppHandle) {
    let label = focused_label(app);
    let shell = app.state::<Shell>();
    let released = {
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        match reg.wins.get_mut(&label) {
            Some(w) if w.crash_hold => {
                w.crash_hold = false;
                true
            }
            Some(w) => {
                if w.phase != Phase::Terminal {
                    w.boot_permit_until = Some(Instant::now() + BOOT_PERMIT);
                }
                false
            }
            None => false,
        }
    };
    if released {
        log::info!("[window] {label}: reload after a crash hold: trying the terminal again");
        if shell.health.snapshot().ui_ready {
            navigate_to_terminal(app, &label);
        }
        return;
    }
    if let Some(w) = app.get_webview_window(&label) {
        let _ = w.reload();
    }
}

/// Lift a window's crash hold (boot page "Open terminal now"). Returns whether it was held.
pub fn release_crash_hold(app: &AppHandle, label: &str) -> bool {
    let shell = app.state::<Shell>();
    let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
    match reg.wins.get_mut(label) {
        Some(w) if w.crash_hold => {
            w.crash_hold = false;
            true
        }
        _ => false,
    }
}

/// WebKit's `webViewWebContentProcessDidTerminate:` for a window (round 3, completeness-final-03). It runs on the
/// main thread INSIDE WebKit's delegate call, so it touches nothing there (no webview call, no lock): the
/// bookkeeping, the log line and the recovery run on the async runtime (a webview call from inside the delegate
/// could re-enter wry while its window table is borrowed).
pub fn content_process_terminated(app: &AppHandle, label: &str) {
    let app2 = app.clone();
    let label = label.to_string();
    let at = Instant::now();
    tauri::async_runtime::spawn(async move {
        let Some((action, phase)) = record_crash(&app2, &label, at) else {
            return;
        };
        tokio::time::sleep(Duration::from_millis(250)).await;
        recover_after_crash(&app2, &label, action, phase);
    });
}

/// Count a content-process termination of `label` at `at`, decide, and log it (None: quitting, or the
/// window is being destroyed).
fn record_crash(app: &AppHandle, label: &str, at: Instant) -> Option<(CrashAction, Phase)> {
    let shell = app.state::<Shell>();
    if shell.quitting.load(std::sync::atomic::Ordering::SeqCst) {
        return None;
    }
    let (action, phase, seen) = {
        let mut reg = shell.windows.lock().unwrap_or_else(|e| e.into_inner());
        let w = reg.wins.get_mut(label)?;
        let action = crash_decision(&mut w.crashes, at);
        if let CrashAction::Hold(_) = action {
            w.crash_hold = true;
        }
        (action, w.phase, w.last_seen.clone().unwrap_or_else(|| w.target.clone()))
    };
    // the live URL is nil by now (WebKit resets it): name the page it showed
    let shown = tab_of(&seen).unwrap_or("?");
    match action {
        CrashAction::Reload(n) => log::warn!(
            "[window] {label}: its WebKit content process ended ({phase:?}, {shown}); reloading it ({n} of {CRASH_RELOADS} automatic reloads per {} min)",
            CRASH_WINDOW.as_secs() / 60
        ),
        CrashAction::Hold(n) => log::error!(
            "[window] {label}: its WebKit content process ended {n} times in {} min ({shown}); not reloading it again automatically (boot page: PAGE STOPPED)",
            CRASH_WINDOW.as_secs() / 60
        ),
    }
    Some((action, phase))
}

fn recover_after_crash(app: &AppHandle, label: &str, action: CrashAction, phase: Phase) {
    let shell = app.state::<Shell>();
    if shell.quitting.load(std::sync::atomic::Ordering::SeqCst) {
        return;
    }
    let code = |t: &str| {
        tab_of(t)
            .and_then(pages::by_id)
            .map(|p| p.code)
            .unwrap_or("the terminal")
    };
    match action {
        CrashAction::Reload(_) => {
            if phase == Phase::Boot {
                force_boot(app, label, BootMode::Boot);
                return;
            }
            // reload where it was: WebKit has reset the live URL to nil, so the page the status broadcast last saw
            // (history.replaceState tab changes included, at most ~8 s old), else its target
            let target = reload_target(app, label);
            if let Some(t) = &target {
                if let Some(w) = shell
                    .windows
                    .lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .wins
                    .get_mut(label)
                {
                    w.target = t.clone();
                }
            }
            if shell.health.snapshot().ui_ready {
                navigate_to_terminal(app, label);
            } else {
                force_boot(app, label, BootMode::Reconnecting);
            }
            shell.notify_throttled(
                app,
                "webcontent-crash",
                Duration::from_secs(600),
                "SuryaDhana reloaded a window",
                &format!(
                    "Its page stopped (the WebKit content process ended) and was reloaded: {}.",
                    code(target.as_deref().unwrap_or(""))
                ),
            );
        }
        CrashAction::Hold(n) => {
            force_boot(app, label, BootMode::Crashed);
            shell.notify_throttled(
                app,
                "webcontent-crash-hold",
                Duration::from_secs(600),
                "A SuryaDhana window stopped reloading",
                &format!(
                    "Its page stopped {n} times in {} min. Choose Open terminal now (or ⌘R) in that window to try again.",
                    CRASH_WINDOW.as_secs() / 60
                ),
            );
        }
    }
}

/// Send a window to the boot page even when it already shows it (a crashed boot page must be reloaded too).
fn force_boot(app: &AppHandle, label: &str, mode: BootMode) {
    let on_boot = app
        .get_webview_window(label)
        .and_then(|w| webview_url(&w))
        .map(|u| policy::is_boot_origin(&u))
        .unwrap_or(false);
    navigate_to_boot(app, label, mode);
    if on_boot {
        let shell = app.state::<Shell>();
        if let Some(info) = shell
            .windows
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .wins
            .get_mut(label)
        {
            info.boot_painted = false;
            info.boot_since = Instant::now();
        }
        if let Some(w) = app.get_webview_window(label) {
            let _ = w.navigate(Url::parse(BOOT_URL).expect("boot url"));
        }
    }
}

/// Origin string of the terminal (for logs and shell_info).
pub fn ui_origin(app: &AppHandle) -> String {
    origin_str(&app.state::<Shell>().cfg.ui_url)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ui() -> Url {
        Url::parse("http://127.0.0.1:8010").unwrap()
    }

    #[test]
    fn targets_are_confined_to_the_ui_origin() {
        let ui = ui();
        assert_eq!(
            terminal_url(&ui, "/?tab=desk").as_str(),
            "http://127.0.0.1:8010/?tab=desk"
        );
        for evil in [
            "//evil.com/x",
            "http://evil.com/",
            "\\\\evil.com",
            "javascript:alert(1)",
            "",
            "/x#frag",
        ] {
            let u = terminal_url(&ui, evil);
            assert!(policy::same_ui_origin(&u, &ui), "{evil} -> {u}");
            assert_eq!(u.as_str(), "http://127.0.0.1:8010/?tab=brief", "{evil}");
        }
        assert_eq!(tab_target("risk"), "/?tab=risk");
        assert_eq!(tab_target("nope"), "/?tab=brief");
    }

    #[test]
    fn saved_urls_map_to_targets() {
        let ui = ui();
        assert_eq!(target_from_saved("http://localhost:8010/?tab=desk", &ui), "/?tab=desk");
        assert_eq!(target_from_saved("http://127.0.0.1:3000/?tab=risk", &ui), "/?tab=risk");
        assert_eq!(target_from_saved("https://evil.com/?tab=system", &ui), "/?tab=system");
        assert_eq!(target_from_saved("https://evil.com/?tab=../x", &ui), "/?tab=brief");
        assert_eq!(target_from_saved("garbage", &ui), "/?tab=brief");
        assert_eq!(tab_of("/?tab=desk&x=1"), Some("desk"));
        assert_eq!(tab_of("/?x=1"), None);
    }

    #[test]
    fn restore_plan_main_first_and_capped() {
        let ui = ui();
        let mut s = Session::default();
        for i in (1..=12).rev() {
            s.windows.push(SavedWindow {
                label: format!("term-{i}"),
                url: format!("http://127.0.0.1:8010/?tab=desk&w={i}"),
                zoom: None,
            });
        }
        s.windows.push(SavedWindow {
            label: "evil-label".into(),
            url: "http://127.0.0.1:8010/".into(),
            zoom: None,
        });
        s.windows.push(SavedWindow {
            label: "term-1".into(),
            url: "http://127.0.0.1:8010/".into(),
            zoom: None,
        }); // dup
        let plan = restore_plan(&s, &ui);
        assert_eq!(plan[0], ("main".to_string(), "/?tab=brief".to_string()));
        assert_eq!(plan.len(), MAX_WINDOWS);
        assert!(plan.iter().all(|(l, _)| l == "main" || l.starts_with("term-")));
        let empty = restore_plan(&Session::default(), &ui);
        assert_eq!(empty, vec![("main".to_string(), "/?tab=brief".to_string())]);
    }

    #[test]
    fn session_round_trip_and_tolerant_load() {
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("state.json");
        assert_eq!(Session::load(&p), Session::default());
        let s = Session {
            version: 0,
            windows: vec![
                SavedWindow {
                    label: "main".into(),
                    url: "http://127.0.0.1:8010/?tab=desk".into(),
                    zoom: None,
                },
                SavedWindow {
                    label: "term-2".into(),
                    url: "http://127.0.0.1:8010/?tab=risk".into(),
                    zoom: Some(1.2),
                },
            ],
            autostart_initialized: true,
        };
        s.save(&p).unwrap();
        let back = Session::load(&p);
        assert_eq!(back.windows, s.windows);
        assert!(back.autostart_initialized);
        assert_eq!(back.version, SESSION_VERSION);
        let text = std::fs::read_to_string(&p).unwrap();
        assert!(
            text.contains("\"zoom\": 1.2") && text.matches("zoom").count() == 1,
            "{text}"
        );
        // a session without the legacy marker never writes it (the marker lives in .autostart-initialized)
        Session::default().save(&p).unwrap();
        assert!(!std::fs::read_to_string(&p).unwrap().contains("autostart_initialized"));
        // old files without zoom still load
        std::fs::write(
            &p,
            r#"{"version":1,"windows":[{"label":"main","url":"http://127.0.0.1:8010/"}]}"#,
        )
        .unwrap();
        assert_eq!(Session::load(&p).windows[0].zoom, None);
        std::fs::write(&p, "{broken").unwrap();
        assert_eq!(Session::load(&p), Session::default());
    }

    #[test]
    fn cascade_stays_on_the_source_display() {
        let area = (0.0, 25.0, 1920.0, 1050.0);
        // from a window at (100, 30): offset by 28, default size fits the area
        assert_eq!(
            cascade_rect((100.0, 30.0), area, DEFAULT_SIZE, MIN_SIZE),
            (128.0, 58.0, 1600.0, 1000.0)
        );
        // near the bottom-right edge: wraps back inside instead of walking off-screen
        let (x, y, w, h) = cascade_rect((400.0, 100.0), area, DEFAULT_SIZE, MIN_SIZE);
        assert!(
            x >= 0.0 && x + w <= 1920.0 && y >= 25.0 && y + h <= 1075.0,
            "{x} {y} {w} {h}"
        );
        // a second display to the right (x 1920..3360): the new window lands there, not next to main
        let right = (1920.0, 0.0, 1440.0, 875.0);
        let (x, y, w, h) = cascade_rect((2000.0, 40.0), right, DEFAULT_SIZE, MIN_SIZE);
        assert!(x >= 1920.0 && x + w <= 3360.0 && y + h <= 875.0, "{x} {y} {w} {h}");
        assert_eq!((w, h), (1440.0, 875.0));
        // a display smaller than the minimum size: the window fills it
        let tiny = (0.0, 0.0, 800.0, 500.0);
        assert_eq!(
            cascade_rect((0.0, 0.0), tiny, DEFAULT_SIZE, MIN_SIZE),
            (0.0, 0.0, 800.0, 500.0)
        );
        // two minimum-width windows tile side by side on 1920
        assert!(2.0 * MIN_SIZE.0 <= 1920.0);
    }

    #[test]
    fn downloads_only_from_the_terminal_origin() {
        let ui = ui();
        for ok in [
            "http://127.0.0.1:8010/api/research/file?id=x",
            "blob:http://127.0.0.1:8010/1b2c",
            "http://localhost:8010/x.csv",
        ] {
            assert!(download_source_allowed(&Url::parse(ok).unwrap(), &ui), "{ok}");
        }
        // C2-security-05: data: URLs (mintable by any frame, e.g. the TradingView iframe) are refused
        for bad in [
            "data:application/zip;base64,UEsDBA==",
            "data:text/csv,a,b",
            "blob:https://s.tradingview.com/uuid",
            "https://evil.example/x.zip",
            "http://127.0.0.1:8001/x",
        ] {
            assert!(!download_source_allowed(&Url::parse(bad).unwrap(), &ui), "{bad}");
        }
    }

    #[test]
    fn event_js_embeds_json_literal_only() {
        let js = shell_event_js(&serde_json::json!({"type": "goto", "tab": "desk\u{2028}');alert(1)//"}));
        assert!(js.starts_with("(function(){try{window.dispatchEvent(new CustomEvent('suryadhana:shell',{detail:{"));
        assert!(!js.contains('\u{2028}'));
        assert!(js.contains(r#""tab":"desk\u2028');alert(1)//""#));
        let init = init_script(1.0);
        assert!(
            !init.contains("prefs.mode"),
            "normal windows never touch the prefs mode"
        );
        // contract K3: the creation-time zoom is published at document start (clamped, finite)
        assert!(init.contains("window.__SURYADHANA_ZOOM__=1;"), "{init}");
        assert!(init_script(1.25).contains("__SURYADHANA_ZOOM__=1.3;"));
        assert!(init_script(9.0).contains("__SURYADHANA_ZOOM__=2;"));
        assert!(init_script(f64::NAN).contains("__SURYADHANA_ZOOM__=1;"));
        assert!(SELFTEST_PREFS_READONLY_JS.contains("'suryadhana.prefs.mode','readonly'"));
        assert!(init.contains("\"api\":1"));
        assert!(init.contains("\"platform\":\"macos\""));
        assert!(init.contains("Object.freeze("));
        // round 3 (K5): the shell announces that it posts the notification feed itself
        assert!(init.contains("\"features\":[\"notification_feed\"]"), "{init}");
    }

    #[test]
    fn zoom_steps_events_and_limits() {
        // ⌘= / ⌘- / ⌘0 in 10 % steps inside 50–200 %
        assert_eq!(next_zoom(1.0, Some(0.1)), 1.1);
        assert_eq!(next_zoom(1.1, Some(0.1)), 1.2);
        assert_eq!(next_zoom(0.5, Some(-0.1)), 0.5);
        assert_eq!(next_zoom(2.0, Some(0.1)), 2.0);
        assert_eq!(next_zoom(1.7, None), 1.0);
        // floating error never accumulates: ten steps up and down land on 1.0 exactly
        let mut z = 1.0;
        for _ in 0..7 {
            z = next_zoom(z, Some(0.1));
        }
        for _ in 0..7 {
            z = next_zoom(z, Some(-0.1));
        }
        assert_eq!(z, 1.0);
        // the additive event (contract K3) is a JSON literal on the shell event channel
        let js = zoom_js(0.8, true);
        assert!(js.contains("window.__SURYADHANA_ZOOM__=0.8;"), "{js}");
        assert!(
            js.contains(r#"{"factor":0.8,"type":"zoom"}"#) || js.contains(r#"{"type":"zoom","factor":0.8}"#),
            "{js}"
        );
        assert!(!zoom_js(0.8, false).contains("dispatchEvent"));
    }

    #[test]
    fn deep_links_carry_a_validated_symbol() {
        assert_eq!(deep_link_target("charts", Some("TCS")), "/?tab=charts&sym=TCS");
        assert_eq!(deep_link_target("desk", Some("M&M")), "/?tab=desk&sym=M%26M");
        assert_eq!(deep_link_target("desk", None), "/?tab=desk");
        // an invalid tab falls back to the landing page; an invalid symbol is dropped (callers reject it first)
        assert_eq!(deep_link_target("nope", Some("TCS")), "/?tab=brief&sym=TCS");
        assert_eq!(deep_link_target("desk", Some("tcs\"><x")), "/?tab=desk");
        let u = terminal_url(&ui(), &deep_link_target("charts", Some("BAJAJ-AUTO")));
        assert_eq!(u.as_str(), "http://127.0.0.1:8010/?tab=charts&sym=BAJAJ-AUTO");
        assert_eq!(tab_of("/?tab=charts&sym=TCS"), Some("charts"));
    }

    #[test]
    fn history_steps_never_leave_the_page_by_themselves() {
        assert!(history_js(true).contains("history.length>1") && history_js(true).contains("history.back()"));
        assert!(history_js(false).contains("history.forward()"));
        // a step back to the first entry of a window (the bundled boot page) is refused by the policy
        let frames: Vec<String> = vec![];
        let u = ui();
        let ctx = NavContext {
            ui: &u,
            boot_permitted: false,
            frame_hosts: &frames,
        };
        assert!(matches!(
            navigation_decision(&Url::parse(BOOT_URL).unwrap(), &ctx),
            NavDecision::Deny(_)
        ));
    }

    #[test]
    fn print_only_a_visible_terminal_window_without_a_sheet() {
        let t = Some(Phase::Terminal);
        assert_eq!(print_refusal(t, true, false, true, Some(false)), None);
        // R9 guards: the boot page / a held window / a window still loading, hidden or minimized windows, a
        // second ⌘P while the print panel is up, and a window without a native view are never printed
        assert!(print_refusal(Some(Phase::Boot), true, false, false, Some(false)).is_some());
        assert!(print_refusal(Some(Phase::Loading), true, false, true, Some(false)).is_some());
        assert!(
            print_refusal(t, true, false, false, Some(false)).is_some(),
            "terminal phase, other origin"
        );
        assert!(
            print_refusal(None, true, false, true, Some(false)).is_some(),
            "not a managed window"
        );
        assert!(print_refusal(t, false, false, true, Some(false))
            .unwrap()
            .contains("hidden"));
        assert!(print_refusal(t, true, true, true, Some(false))
            .unwrap()
            .contains("minimized"));
        assert!(print_refusal(t, true, false, true, Some(true))
            .unwrap()
            .contains("already open"));
        assert!(print_refusal(t, true, false, true, None).is_some());
    }

    #[test]
    fn a_crashing_page_is_reloaded_a_bounded_number_of_times() {
        // completeness-final-03: a window whose WebKit content process ends is reloaded, at most CRASH_RELOADS
        // times per CRASH_WINDOW; the next one holds it on the boot page (a page that crashes on load can
        // never loop); old crashes are forgotten
        let t0 = Instant::now();
        let at = |s: u64| t0 + Duration::from_secs(s);
        let mut recent = std::collections::VecDeque::new();
        assert_eq!(crash_decision(&mut recent, at(0)), CrashAction::Reload(1));
        assert_eq!(crash_decision(&mut recent, at(10)), CrashAction::Reload(2));
        assert_eq!(crash_decision(&mut recent, at(20)), CrashAction::Reload(3));
        assert_eq!(crash_decision(&mut recent, at(30)), CrashAction::Hold(4));
        assert_eq!(crash_decision(&mut recent, at(40)), CrashAction::Hold(5), "still held");
        // ten quiet minutes later: a single crash is reloaded again
        assert_eq!(crash_decision(&mut recent, at(40 + 301)), CrashAction::Reload(1));
        // one crash a day for a week: always reloaded
        let mut daily = std::collections::VecDeque::new();
        for d in 0..7 {
            assert_eq!(crash_decision(&mut daily, at(d * 86_400)), CrashAction::Reload(1));
        }
        assert!(CRASH_RELOADS >= 1 && CRASH_WINDOW >= Duration::from_secs(60));
        // the budget is at most CRASH_RELOADS per minute in the worst case, too
        let mut burst = std::collections::VecDeque::new();
        let reloads = (0..60u64)
            .filter(|s| matches!(crash_decision(&mut burst, at(*s)), CrashAction::Reload(_)))
            .count();
        assert_eq!(reloads, CRASH_RELOADS);
        // reloaded where it was: the live URL is nil after a crash, so the page last seen by the status broadcast
        // (an in-page tab change via history.replaceState), not the window's older target
        assert_eq!(
            crash_reload_target(None, Some("/?tab=chart&sym=TCS"), "/?tab=desk"),
            "/?tab=chart&sym=TCS"
        );
        assert_eq!(crash_reload_target(None, None, "/?tab=desk"), "/?tab=desk");
        assert_eq!(
            crash_reload_target(Some("/?tab=risk".into()), Some("/?tab=chart"), "/?tab=desk"),
            "/?tab=risk"
        );
        assert_eq!(
            ui_path(&Url::parse("http://127.0.0.1:8010/?tab=brief&sym=M%26M").unwrap()),
            "/?tab=brief&sym=M%26M"
        );
        // a held window is never auto-advanced by the navigator; the boot page names the state
        let mut w = WinInfo::new("/?tab=desk".into());
        w.crash_hold = true;
        assert!(w.crash_hold && w.phase == Phase::Boot);
        assert_eq!(
            serde_json::to_value(BootMode::Crashed).unwrap(),
            serde_json::json!("crashed")
        );
    }

    #[test]
    fn registry_labels_and_permits() {
        let mut r = Registry::default();
        r.wins.insert("main".into(), WinInfo::new("/?tab=brief".into()));
        assert!(r.boot_permitted("main"));
        assert!(!r.boot_permitted("term-1"));
        r.wins.get_mut("main").unwrap().boot_permit_until = Some(Instant::now() - Duration::from_secs(1));
        assert!(!r.boot_permitted("main"));
        r.wins.insert("term-1".into(), WinInfo::new("/".into()));
        assert_eq!(r.next_term_label(&["term-2".into()]), "term-3");
        assert!(r.any_waiting());
        for w in r.wins.values_mut() {
            w.phase = Phase::Terminal;
        }
        assert!(!r.any_waiting());
    }
}
