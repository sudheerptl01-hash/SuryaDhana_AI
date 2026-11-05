//! Pure security and validation policy (no Tauri types; fully unit-tested).
//!
//! * navigation allowlist for every webview (boot page origin + the configured ui_url origin),
//! * new-window routing (same-origin -> another terminal window, external -> default browser),
//! * argument validation for the IPC commands (filenames, external URLs, tab ids, plain text),
//! * the IST restart-freeze guard (07:45-09:20 and 18:30-21:15 Asia/Kolkata, independent of the Mac's TZ),
//! * sliding-window rate limiters (notifications, downloads, external opens) and a byte budget,
//! * the download extension allowlist and the `com.apple.quarantine` value the shell tags files with,
//! * the trust rule for the process that listens on the terminal port (port-squatting guard: same uid AND a
//!   CPython executable in a Homebrew / python.org location, pure string rule, no file access),
//! * deep-link symbol validation (`shell_new_window {sym}`),
//! * URL redaction for logs (never log query strings: the ICICI login URL carries the API key).

use std::collections::VecDeque;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use time::{OffsetDateTime, UtcOffset};
use url::{Host, Url};

/// Maximum length of a URL accepted by `shell_open_external`.
pub const MAX_EXTERNAL_URL_LEN: usize = 2048;
/// Maximum sanitized download filename length (characters).
pub const MAX_FILENAME_LEN: usize = 120;
/// Maximum decoded download size (bytes).
pub const MAX_DOWNLOAD_BYTES: usize = 50 * 1024 * 1024;
/// Maximum notification title / window title length (characters).
pub const MAX_TITLE_LEN: usize = 120;
/// Maximum notification body length (characters).
pub const MAX_BODY_LEN: usize = 1000;
/// Extensions a file the shell writes into ~/Downloads may keep (case-insensitive). These are what the
/// terminal really exports: CSV / Excel (EQS, BTST), JSON + CSV research data files (RSCH,
/// `/api/research/file`), plus plain text, Markdown, PDF and raster images. Anything else (`.zip`, `.app`,
/// `.command`, `.terminal`, `.pkg`, `.webloc`, `.html`, `.svg`, no extension…) gets `.txt` appended, so a
/// double-click opens it as text instead of running or unpacking it.
pub const DOWNLOAD_EXTENSIONS: [&str; 10] = ["csv", "tsv", "txt", "json", "md", "pdf", "png", "jpg", "jpeg", "xlsx"];
/// Downloads per minute (all windows together; shell_save_download and WebKit downloads).
pub const DOWNLOADS_PER_MINUTE: usize = 10;
/// Decoded bytes the shell may write into ~/Downloads per hour.
pub const DOWNLOAD_BYTES_PER_HOUR: u64 = 200 * 1024 * 1024;
/// Refuse downloads when the Downloads volume has less free space than this.
pub const MIN_FREE_DISK_BYTES: u64 = 5 * 1024 * 1024 * 1024;
/// External browser opens per minute (all windows together).
pub const EXTERNAL_OPENS_PER_MINUTE: usize = 20;
/// Quarantine agent name written into `com.apple.quarantine` (shown by Gatekeeper's first-open prompt).
pub const QUARANTINE_AGENT: &str = "SuryaDhana";

/// Scheme + host of the bundled boot page (macOS custom protocol).
pub const BOOT_SCHEME: &str = "tauri";
pub const BOOT_HOST: &str = "localhost";

/// Validation failure, rendered to the caller as a plain message (never echoes secrets).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyError(pub String);

impl std::fmt::Display for PolicyError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for PolicyError {}

fn err<T>(msg: impl Into<String>) -> Result<T, PolicyError> {
    Err(PolicyError(msg.into()))
}

// ---------------------------------------------------------------------------------------------
// Origins
// ---------------------------------------------------------------------------------------------

/// True for loopback / local hosts: localhost (and *.localhost), 127.0.0.0/8, ::1, 0.0.0.0.
pub fn is_loopback_host(host: &Host<&str>) -> bool {
    match host {
        Host::Domain(d) => {
            let d = d.trim_end_matches('.').to_ascii_lowercase();
            d == "localhost" || d.ends_with(".localhost")
        }
        Host::Ipv4(ip) => ip.is_loopback() || ip.is_unspecified(),
        Host::Ipv6(ip) => {
            ip.is_loopback()
                || ip.is_unspecified()
                || ip
                    .to_ipv4_mapped()
                    .map(|v4| v4.is_loopback() || v4.is_unspecified())
                    .unwrap_or(false)
        }
    }
}

fn is_local_alias(host: &Host<&str>) -> bool {
    match host {
        Host::Domain(d) => d.eq_ignore_ascii_case("localhost"),
        Host::Ipv4(ip) => ip.octets() == [127, 0, 0, 1],
        Host::Ipv6(_) => false,
    }
}

/// Same origin as the terminal (`ui`), treating `localhost` and `127.0.0.1` as equivalent for the same
/// scheme and port. `ui` is assumed validated (http, loopback host) by config.rs.
pub fn same_ui_origin(url: &Url, ui: &Url) -> bool {
    if url.scheme() != ui.scheme() || url.port_or_known_default() != ui.port_or_known_default() {
        return false;
    }
    if !url.username().is_empty() || url.password().is_some() {
        return false;
    }
    match (url.host(), ui.host()) {
        (Some(a), Some(b)) => {
            if is_local_alias(&a) && is_local_alias(&b) {
                return true;
            }
            a.to_string().eq_ignore_ascii_case(&b.to_string())
        }
        _ => false,
    }
}

/// Exactly the configured terminal origin (scheme, host spelling, port; no credentials). The remote IPC
/// capability is granted to this origin only (contract v1: `http://127.0.0.1:8010` and nothing else), so
/// terminal windows are kept on it: an alias spelling (`localhost` <-> `127.0.0.1`) is canonicalized.
pub fn exact_ui_origin(url: &Url, ui: &Url) -> bool {
    url.scheme() == ui.scheme()
        && url.port_or_known_default() == ui.port_or_known_default()
        && url.username().is_empty()
        && url.password().is_none()
        && matches!((url.host_str(), ui.host_str()), (Some(a), Some(b)) if a.eq_ignore_ascii_case(b))
}

/// The same URL on the configured spelling of the terminal origin, when `url` is the terminal origin
/// under its alias spelling (`http://localhost:8010/x` for ui `http://127.0.0.1:8010`); else None.
pub fn canonical_ui_url(url: &Url, ui: &Url) -> Option<Url> {
    if !same_ui_origin(url, ui) || exact_ui_origin(url, ui) {
        return None;
    }
    let mut u = url.clone();
    u.set_host(ui.host_str()).ok()?;
    exact_ui_origin(&u, ui).then_some(u)
}

/// True for the bundled boot page origin (`tauri://localhost`).
pub fn is_boot_origin(url: &Url) -> bool {
    url.scheme() == BOOT_SCHEME && url.host_str() == Some(BOOT_HOST)
}

/// `blob:` URL whose inner origin is the terminal origin.
fn is_ui_blob(url: &Url, ui: &Url) -> bool {
    if url.scheme() != "blob" {
        return false;
    }
    Url::parse(url.path())
        .map(|inner| same_ui_origin(&inner, ui))
        .unwrap_or(false)
}

/// Host suffix match: `host == suffix` or `host` ends with `.suffix` (case-insensitive).
pub fn host_matches_suffix(host: &str, suffix: &str) -> bool {
    let h = host.trim_end_matches('.').to_ascii_lowercase();
    let s = suffix
        .trim()
        .trim_start_matches('.')
        .trim_end_matches('.')
        .to_ascii_lowercase();
    !s.is_empty() && (h == s || h.ends_with(&format!(".{s}")))
}

/// External = http(s), has a host, and that host is not loopback.
pub fn is_external_http(url: &Url) -> bool {
    matches!(url.scheme(), "http" | "https") && url.host().map(|h| !is_loopback_host(&h)).unwrap_or(false)
}

// ---------------------------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------------------------

/// What to do with a navigation request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NavDecision {
    /// Load it in the webview.
    Allow,
    /// The terminal origin under its alias spelling: cancel it and load this canonical URL instead
    /// (the IPC capability only covers the configured spelling).
    Canonical(Url),
    /// Cancel it and open the URL in the default browser instead.
    OpenExternal,
    /// Cancel it (logged).
    Deny(&'static str),
}

/// Inputs to the navigation decision.
#[derive(Debug, Clone)]
pub struct NavContext<'a> {
    /// The configured terminal origin (validated loopback http URL).
    pub ui: &'a Url,
    /// The shell itself initiated a navigation to the boot page for this window moments ago.
    /// The remote terminal can never navigate a window back to the privileged boot page on its own.
    pub boot_permitted: bool,
    /// Host suffixes whose pages may load as embedded frames (e.g. the TradingView chart widget).
    pub frame_hosts: &'a [String],
}

/// Navigation allowlist.
///
/// WKWebView asks the navigation policy for every frame (wry does not expose which frame), so external
/// hosts listed in `frame_hosts` are allowed over **https only** (they are embedded widgets; a cleartext
/// frame could be rewritten by anyone on the network path); a *main-frame* navigation that lands on one
/// is caught after commit by [`main_frame_allowed`] and bounced to the browser.
pub fn navigation_decision(url: &Url, ctx: &NavContext<'_>) -> NavDecision {
    match url.scheme() {
        BOOT_SCHEME => {
            if is_boot_origin(url) && ctx.boot_permitted {
                NavDecision::Allow
            } else if is_boot_origin(url) {
                NavDecision::Deny("boot page navigation not initiated by the shell")
            } else {
                NavDecision::Deny("custom scheme")
            }
        }
        "http" | "https" => {
            if exact_ui_origin(url, ctx.ui) {
                NavDecision::Allow
            } else if let Some(c) = canonical_ui_url(url, ctx.ui) {
                NavDecision::Canonical(c)
            } else if url.host().map(|h| is_loopback_host(&h)).unwrap_or(true) {
                NavDecision::Deny("loopback origin other than the terminal")
            } else if !url.username().is_empty() || url.password().is_some() {
                NavDecision::Deny("credentials in URL")
            } else if url
                .host_str()
                .map(|h| ctx.frame_hosts.iter().any(|s| host_matches_suffix(h, s)))
                .unwrap_or(false)
            {
                if url.scheme() == "https" {
                    NavDecision::Allow
                } else {
                    NavDecision::Deny("cleartext http for an embedded-frame host")
                }
            } else {
                NavDecision::OpenExternal
            }
        }
        "about" => match url.as_str() {
            "about:blank" | "about:srcdoc" => NavDecision::Allow,
            _ => NavDecision::Deny("about: page"),
        },
        "blob" => {
            if is_ui_blob(url, ctx.ui) {
                NavDecision::Allow
            } else {
                NavDecision::Deny("foreign blob")
            }
        }
        "file" => NavDecision::Deny("file: URL"),
        "javascript" => NavDecision::Deny("javascript: URL"),
        "data" => NavDecision::Deny("data: URL"),
        _ => NavDecision::Deny("scheme not allowed"),
    }
}

/// Main-frame guard (checked when a main-frame load commits): only the boot page and the terminal
/// origin may be the top-level document of a SuryaDhana window.
pub fn main_frame_allowed(url: &Url, ui: &Url) -> bool {
    is_boot_origin(url) || exact_ui_origin(url, ui) || url.as_str() == "about:blank"
}

/// What to do with a `window.open` / `target=_blank` request.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NewWindowDecision {
    /// Open another terminal window on this path+query of the terminal origin.
    Terminal(String),
    /// Open in the default browser.
    External,
    /// Refuse (logged).
    Deny(&'static str),
}

/// Route a new-window request.
pub fn new_window_decision(url: &Url, ui: &Url) -> NewWindowDecision {
    if same_ui_origin(url, ui) {
        let mut target = url.path().to_string();
        if let Some(q) = url.query() {
            target.push('?');
            target.push_str(q);
        }
        return NewWindowDecision::Terminal(target);
    }
    if is_external_http(url) {
        if !url.username().is_empty() || url.password().is_some() {
            return NewWindowDecision::Deny("credentials in URL");
        }
        return NewWindowDecision::External;
    }
    match url.scheme() {
        "about" | "blob" => NewWindowDecision::Deny("blank/blob popup"),
        _ => NewWindowDecision::Deny("scheme not allowed"),
    }
}

// ---------------------------------------------------------------------------------------------
// IPC argument validation
// ---------------------------------------------------------------------------------------------

/// Validate a URL for `shell_open_external`: http/https only, <= 2048 chars, a real non-loopback host,
/// no embedded credentials.
pub fn validate_external_url(raw: &str) -> Result<Url, PolicyError> {
    let raw = raw.trim();
    if raw.is_empty() {
        return err("url is empty");
    }
    if raw.len() > MAX_EXTERNAL_URL_LEN {
        return err(format!("url longer than {MAX_EXTERNAL_URL_LEN} characters"));
    }
    let url = Url::parse(raw).map_err(|_| PolicyError("url does not parse".into()))?;
    if !matches!(url.scheme(), "http" | "https") {
        return err("only http and https URLs can be opened");
    }
    let Some(host) = url.host() else {
        return err("url has no host");
    };
    if is_loopback_host(&host) {
        return err("loopback URLs are never opened externally");
    }
    if !url.username().is_empty() || url.password().is_some() {
        return err("URLs with credentials are refused");
    }
    Ok(url)
}

/// Validate a tab id against the 42 pages.
pub fn validate_tab(tab: &str) -> Result<&'static str, PolicyError> {
    crate::pages::by_id(tab)
        .map(|p| p.id)
        .ok_or_else(|| PolicyError("unknown tab id".into()))
}

/// Maximum length of an NSE symbol in a deep link (`shell_new_window {sym}`, `?sym=`).
pub const MAX_SYMBOL_LEN: usize = 20;

/// Validate an NSE ticker for a deep link (contract K4: `^[A-Z0-9&_.-]{1,20}$`, ASCII only). Returned as-is;
/// the caller URL-encodes it (`M&M` -> `M%26M`).
pub fn validate_symbol(sym: &str) -> Result<&str, PolicyError> {
    let ok = !sym.is_empty()
        && sym.len() <= MAX_SYMBOL_LEN
        && sym
            .bytes()
            .all(|b| b.is_ascii_uppercase() || b.is_ascii_digit() || matches!(b, b'&' | b'_' | b'.' | b'-'));
    if ok {
        Ok(sym)
    } else {
        err("sym must be an NSE symbol: 1-20 of A-Z 0-9 & _ . -")
    }
}

/// Plain text with a character limit: control characters (incl. newlines, bidi overrides) are
/// replaced by spaces and whitespace runs collapsed; over-long input is rejected (not truncated).
pub fn validate_plain_text(s: &str, max_chars: usize, what: &str) -> Result<String, PolicyError> {
    if s.chars().count() > max_chars {
        return err(format!("{what} longer than {max_chars} characters"));
    }
    let cleaned: String = s
        .chars()
        .map(|c| if c.is_control() || is_bidi_control(c) { ' ' } else { c })
        .collect();
    Ok(cleaned.split_whitespace().collect::<Vec<_>>().join(" "))
}

/// Like [`validate_plain_text`] but keeps newlines (notification bodies may be multi-line).
pub fn validate_body_text(s: &str, max_chars: usize) -> Result<String, PolicyError> {
    if s.chars().count() > max_chars {
        return err(format!("body longer than {max_chars} characters"));
    }
    let cleaned: String = s
        .chars()
        .map(|c| match c {
            '\n' => '\n',
            c if c.is_control() || is_bidi_control(c) => ' ',
            c => c,
        })
        .collect();
    Ok(cleaned.trim().to_string())
}

fn is_bidi_control(c: char) -> bool {
    matches!(c, '\u{202A}'..='\u{202E}' | '\u{2066}'..='\u{2069}' | '\u{200E}' | '\u{200F}' | '\u{061C}')
}

/// Sanitize a download filename: basename only (any `/` or `\` path is cut), characters outside
/// `[A-Za-z0-9._ -]` become `_`, leading dots/spaces/dashes are stripped (no hidden files, no
/// option-like names), length <= 120 characters keeping the extension. Empty -> `download`.
pub fn sanitize_filename(raw: &str) -> String {
    let base = raw.rsplit(['/', '\\']).next().unwrap_or("");
    let mapped: String = base
        .chars()
        .map(|c| {
            if c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | ' ' | '-') {
                c
            } else {
                '_'
            }
        })
        .collect();
    // collapse runs of spaces, strip leading dots/spaces/dashes and trailing dots/spaces
    let mut collapsed = String::with_capacity(mapped.len());
    let mut prev_space = false;
    for c in mapped.chars() {
        if c == ' ' {
            if !prev_space {
                collapsed.push(c);
            }
            prev_space = true;
        } else {
            collapsed.push(c);
            prev_space = false;
        }
    }
    let trimmed = collapsed
        .trim_start_matches(['.', ' ', '-'])
        .trim_end_matches(['.', ' '])
        .to_string();
    let name = if trimmed.is_empty() {
        "download".to_string()
    } else {
        trimmed
    };
    truncate_keep_ext(&name, MAX_FILENAME_LEN)
}

fn truncate_keep_ext(name: &str, max: usize) -> String {
    if name.chars().count() <= max {
        return name.to_string();
    }
    let (stem, ext) = match name.rfind('.') {
        Some(i) if i > 0 && name.len() - i <= 12 => (&name[..i], &name[i..]),
        _ => (name, ""),
    };
    let keep = max.saturating_sub(ext.chars().count());
    let stem: String = stem.chars().take(keep).collect();
    format!("{}{}", stem.trim_end_matches(['.', ' ']), ext)
}

/// `name`, then `name (1).ext`, `name (2).ext`, ... : the first candidate for which `exists` is false.
/// Gives up after 9,999 tries (returns an error rather than overwrite).
pub fn unique_name(name: &str, exists: impl Fn(&str) -> bool) -> Result<String, PolicyError> {
    if !exists(name) {
        return Ok(name.to_string());
    }
    let (stem, ext) = match name.rfind('.') {
        Some(i) if i > 0 => (&name[..i], &name[i..]),
        _ => (name, ""),
    };
    for n in 1..10_000u32 {
        let suffix = format!(" ({n})");
        let budget = MAX_FILENAME_LEN.saturating_sub(suffix.len() + ext.len());
        let stem_cut: String = stem.chars().take(budget).collect();
        let candidate = format!("{stem_cut}{suffix}{ext}");
        if !exists(&candidate) {
            return Ok(candidate);
        }
    }
    err("could not find a free filename")
}

/// Upper bound on the base64 text length that can decode to `MAX_DOWNLOAD_BYTES` (checked before decoding).
pub fn max_base64_len() -> usize {
    MAX_DOWNLOAD_BYTES.div_ceil(3) * 4 + 4
}

/// True when `name`'s last extension is in [`DOWNLOAD_EXTENSIONS`] (case-insensitive).
pub fn has_allowed_extension(name: &str) -> bool {
    match name.rsplit_once('.') {
        Some((stem, ext)) if !stem.is_empty() => DOWNLOAD_EXTENSIONS.iter().any(|a| a.eq_ignore_ascii_case(ext)),
        _ => false,
    }
}

/// The name a download is saved under: [`sanitize_filename`], then `.txt` appended when the extension is
/// not in the allowlist (`Q3.zip` -> `Q3.zip.txt`, `run.command` -> `run.command.txt`, `notes` ->
/// `notes.txt`). The result is still <= [`MAX_FILENAME_LEN`] characters and keeps the `.txt`.
pub fn download_filename(raw: &str) -> String {
    let name = sanitize_filename(raw);
    if has_allowed_extension(&name) {
        name
    } else {
        truncate_keep_ext(&format!("{name}.txt"), MAX_FILENAME_LEN)
    }
}

/// Value of the `com.apple.quarantine` extended attribute for a file the shell wrote at `epoch_secs`:
/// `flags;hex-timestamp;agent;` (flags 0083 = what browsers set for a downloaded file, so Gatekeeper
/// assesses it on first open and Archive Utility propagates the quarantine into extracted files).
pub fn quarantine_value(epoch_secs: u64) -> String {
    format!("0083;{epoch_secs:08x};{QUARANTINE_AGENT};")
}

// ---------------------------------------------------------------------------------------------
// Port-squatting guard (who answers the terminal port)
// ---------------------------------------------------------------------------------------------

/// The process listening on the terminal port, as the shell sees it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Listener {
    pub pid: i32,
    /// Owner uid (None: unreadable, e.g. the process exited mid-check).
    pub uid: Option<u32>,
    /// Executable path (`proc_pidpath`, the kernel's resolved path), None when unreadable.
    pub exe: Option<PathBuf>,
    /// Kernel start time (`pbi_start_tvsec`, `pbi_start_tvusec`): with the pid it names ONE process (a pid is
    /// reused, a pid + start time never is). None when unreadable.
    pub start: Option<(u64, u64)>,
}

/// One process, exactly: pid + kernel start time (R-RUST-01/02: the trust pin).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ProcId {
    pub pid: i32,
    pub start: (u64, u64),
}

impl Listener {
    /// The listener's exact process identity (None without a start time).
    pub fn id(&self) -> Option<ProcId> {
        self.start.map(|start| ProcId { pid: self.pid, start })
    }
}

fn is_minor(s: &str) -> bool {
    !s.is_empty() && s.len() <= 3 && s.chars().all(|c| c.is_ascii_digit())
}

/// `3.13.15`, `3.13.0_1` (a Homebrew revision): digits and dots, optional `_<digits>`.
fn is_keg_version(s: &str, minor: &str) -> bool {
    let (v, rev) = s.split_once('_').unwrap_or((s, "0"));
    let mut parts = v.split('.');
    parts.next() == Some("3")
        && parts.next() == Some(minor)
        && parts.all(is_minor)
        && rev.chars().all(|c| c.is_ascii_digit())
        && !rev.is_empty()
}

/// `…/Python.framework/Versions/3.N/` + the CPython executable inside it: the framework's re-exec target
/// `Resources/Python.app/Contents/MacOS/Python`, or `bin/python3` / `bin/python3.N` (a run that did not re-exec).
fn framework_tail_ok(rest: &[&str], minor: &str) -> bool {
    let want = format!("3.{minor}");
    match rest {
        ["Python.framework", "Versions", v, tail @ ..] if *v == want => match tail {
            ["Resources", "Python.app", "Contents", "MacOS", "Python"] => true,
            ["bin", exe] => *exe == "python3" || *exe == format!("python3.{minor}"),
            _ => false,
        },
        _ => false,
    }
}

/// Is `exe` (the kernel's resolved executable path of a listener) a CPython in a Homebrew or python.org
/// install location? Pure string rule on path components: nothing is stat'ed or canonicalized (so nothing
/// under ~/Desktop is ever touched), and ANY patch version of a `python@3.N` keg matches, so the ui-api that
/// keeps running after `brew upgrade` (old Cellar path) is still recognized:
/// * `/opt/homebrew` or `/usr/local` + `Cellar/python@3.N/<3.N.x[_r]>/Frameworks/Python.framework/Versions/3.N/…`
/// * the same under `opt/python@3.N/Frameworks/…` (a non-resolved spelling, for completeness)
/// * `/Library/Frameworks/Python.framework/Versions/3.N/…` (python.org installer)
/// * or any of `extra` (config `trusted_python_prefixes`: absolute, component-wise prefixes).
///
/// The Command Line Tools / Xcode / system Python is deliberately NOT included: the stack never uses it, and it
/// is the interpreter any process finds first.
pub fn is_trusted_python_exe(exe: &Path, extra: &[PathBuf]) -> bool {
    if !exe.is_absolute() || exe.components().any(|c| matches!(c, std::path::Component::ParentDir)) {
        return false;
    }
    if extra
        .iter()
        .any(|p| p.is_absolute() && p.components().count() > 1 && exe.starts_with(p))
    {
        return true;
    }
    let comps: Vec<&str> = exe
        .components()
        .skip(1)
        .filter_map(|c| c.as_os_str().to_str())
        .collect();
    let brew_root = match comps.as_slice() {
        ["opt", "homebrew", rest @ ..] | ["usr", "local", rest @ ..] => Some(rest),
        _ => None,
    };
    if let Some(rest) = brew_root {
        return match rest {
            ["Cellar", keg, version, "Frameworks", tail @ ..] => keg
                .strip_prefix("python@3.")
                .filter(|m| is_minor(m))
                .map(|m| is_keg_version(version, m) && framework_tail_ok(tail, m))
                .unwrap_or(false),
            ["opt", keg, "Frameworks", tail @ ..] => keg
                .strip_prefix("python@3.")
                .filter(|m| is_minor(m))
                .map(|m| framework_tail_ok(tail, m))
                .unwrap_or(false),
            _ => false,
        };
    }
    match comps.as_slice() {
        ["Library", "Frameworks", tail @ ..] => match tail {
            ["Python.framework", "Versions", v, ..] => v
                .strip_prefix("3.")
                .filter(|m| is_minor(m))
                .map(|m| framework_tail_ok(tail, m))
                .unwrap_or(false),
            _ => false,
        },
        _ => false,
    }
}

/// Why the terminal port was not trusted.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TrustFail {
    /// Definitive: a listener was positively identified as NOT the stack's ui-api (another program, another
    /// user, or a process this account cannot inspect while the port answers). New windows stay on the boot
    /// page and open terminal windows are pulled back to it.
    Foreign(String),
    /// Inconclusive: the probe failed or timed out, or the listener vanished mid-check (a ui-api restart
    /// races with it). NEVER evicts a window and never blocks opening one (only a definitive verdict
    /// does); it is retried within seconds and shown in the menu-bar item.
    Unknown(String),
    /// Round 3 (R-RUST-02): a LIVE process of this user holds the port, but its executable can no longer be
    /// read (deleted after it started: a binary that unlinked itself, or `brew cleanup` after `brew upgrade`
    /// removed the Python keg), and it is not a process the guard verified before (see [`ProcId`] pins). It
    /// cannot be identified, so it is treated like a refusal: new windows stay on the boot page (which names
    /// `./start-local.sh restart ui-api`) and open terminal windows are pulled back (the process that served
    /// them is gone or was never verified). The running ui-api verified BEFORE its keg was removed stays
    /// trusted through its pin, so `brew upgrade` alone never locks the owner out.
    Unverifiable(String),
}

impl TrustFail {
    pub fn message(&self) -> &str {
        match self {
            TrustFail::Foreign(m) | TrustFail::Unknown(m) | TrustFail::Unverifiable(m) => m,
        }
    }

    /// A verdict that keeps windows off the terminal origin (and pulls open ones back).
    pub fn denies(&self) -> bool {
        matches!(self, TrustFail::Foreign(_) | TrustFail::Unverifiable(_))
    }
}

/// Trust rule for the terminal port. Trusted (`Ok(detail)`) when there is at least one listener and EVERY
/// listener is this user's AND either a CPython executable by [`is_trusted_python_exe`] or, when its
/// executable is unreadable, exactly a process that passed this rule before (`pinned`: pid + kernel start
/// time, so a reused pid never inherits a pin). `invisible` = no listener was visible although the port
/// answered (another account's process): Foreign. A live listener of this user whose executable is unreadable
/// and that is not pinned is [`TrustFail::Unverifiable`]; one that vanished mid-check (uid unreadable) is
/// [`TrustFail::Unknown`].
pub fn listener_trust(
    listeners: &[Listener],
    invisible: bool,
    own_uid: u32,
    extra: &[PathBuf],
    pinned: &[ProcId],
) -> Result<String, TrustFail> {
    if listeners.is_empty() {
        return Err(if invisible {
            TrustFail::Foreign(
                "the port answers, but no process of this account holds it (another user's or root's process)".into(),
            )
        } else {
            TrustFail::Unknown("nothing is listening on the terminal port right now (ui-api restarting?)".into())
        });
    }
    for l in listeners {
        let exe = l
            .exe
            .as_ref()
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| "an unreadable executable".into());
        match l.uid {
            Some(u) if u == own_uid => {}
            Some(u) => {
                return Err(TrustFail::Foreign(format!(
                    "pid {} ({exe}) belongs to uid {u}, not to this user",
                    l.pid
                )))
            }
            None => return Err(TrustFail::Unknown(format!("pid {}: owner unreadable (exited?)", l.pid))),
        }
        match &l.exe {
            Some(p) if is_trusted_python_exe(p, extra) => {}
            Some(_) => {
                return Err(TrustFail::Foreign(format!(
                    "pid {} runs {exe}, which is not a Homebrew / python.org Python (the stack's ui-api is)",
                    l.pid
                )))
            }
            None if l.id().map(|id| pinned.contains(&id)).unwrap_or(false) => {}
            None => {
                return Err(TrustFail::Unverifiable(format!(
                    "pid {} (this user's) holds the port, but its executable no longer exists on disk (deleted \
                     after it started, e.g. Python upgraded by brew) and it was never verified: it cannot be \
                     identified",
                    l.pid
                )))
            }
        }
    }
    let pids: Vec<String> = listeners.iter().map(|l| l.pid.to_string()).collect();
    let exe = listeners
        .iter()
        .find_map(|l| l.exe.as_ref())
        .map(|p| p.display().to_string());
    Ok(match exe {
        Some(e) => format!("pid {} runs {e}", pids.join(", ")),
        None => format!(
            "pid {}: verified earlier; its executable was removed since (Python upgraded?), the same process still runs",
            pids.join(", ")
        ),
    })
}

/// The exact identities of a verdict's listeners (stored as pins after a pass).
pub fn listener_ids(listeners: &[Listener]) -> Vec<ProcId> {
    listeners.iter().filter_map(Listener::id).collect()
}

// ---------------------------------------------------------------------------------------------
// Logging hygiene
// ---------------------------------------------------------------------------------------------

/// Scheme + host + port + path, never query or fragment (query strings can carry API keys / tokens).
pub fn redact_url(url: &Url) -> String {
    match url.scheme() {
        "http" | "https" | "tauri" => {
            let host = url.host_str().unwrap_or("");
            let port = url.port().map(|p| format!(":{p}")).unwrap_or_default();
            let mut path = url.path().to_string();
            if path.len() > 120 {
                path.truncate(120);
                path.push('…');
            }
            let q = if url.query().is_some() { "?…" } else { "" };
            format!("{}://{}{}{}{}", url.scheme(), host, port, path, q)
        }
        other => format!("{other}:…"),
    }
}

/// Redact a raw string that may or may not parse as a URL.
pub fn redact_raw(raw: &str) -> String {
    match Url::parse(raw) {
        Ok(u) => redact_url(&u),
        Err(_) => "<unparseable url>".to_string(),
    }
}

// ---------------------------------------------------------------------------------------------
// IST freeze guard
// ---------------------------------------------------------------------------------------------

/// India Standard Time (UTC+05:30; no DST).
pub fn ist_offset() -> UtcOffset {
    UtcOffset::from_hms(5, 30, 0).expect("valid offset")
}

/// A restart-freeze window (IST wall clock, [start, end) in minutes since midnight).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FreezeWindow {
    pub start_min: u16,
    pub end_min: u16,
    pub label: &'static str,
}

/// ICICI login + pre-open jobs, and the EOD pipeline / Desk / shadow / wrap (CLAUDE.md "Restart freeze windows").
pub const FREEZE_WINDOWS: [FreezeWindow; 2] = [
    FreezeWindow {
        start_min: 7 * 60 + 45,
        end_min: 9 * 60 + 20,
        label: "07:45–09:20 IST (ICICI login + pre-open jobs)",
    },
    FreezeWindow {
        start_min: 18 * 60 + 30,
        end_min: 21 * 60 + 15,
        label: "18:30–21:15 IST (EOD pipeline, Desk, shadow, wrap)",
    },
];

/// The freeze window containing `at` (any timezone; converted to IST), if any. Applies every day.
pub fn freeze_window_at(at: OffsetDateTime) -> Option<FreezeWindow> {
    let ist = at.to_offset(ist_offset());
    let minute = ist.hour() as u16 * 60 + ist.minute() as u16;
    FREEZE_WINDOWS
        .iter()
        .copied()
        .find(|w| minute >= w.start_min && minute < w.end_min)
}

/// Current IST wall-clock time as `HH:MM:SS`.
pub fn ist_clock(at: OffsetDateTime) -> String {
    let ist = at.to_offset(ist_offset());
    format!("{:02}:{:02}:{:02}", ist.hour(), ist.minute(), ist.second())
}

// ---------------------------------------------------------------------------------------------
// Rate limiting
// ---------------------------------------------------------------------------------------------

/// Sliding-window limiter: at most `max` events per `window`.
#[derive(Debug)]
pub struct RateLimiter {
    max: usize,
    window: Duration,
    hits: VecDeque<Instant>,
}

impl RateLimiter {
    pub fn new(max: usize, window: Duration) -> Self {
        Self {
            max,
            window,
            hits: VecDeque::with_capacity(max + 1),
        }
    }

    /// Record an event at `now` if allowed; returns false (and records nothing) when over the limit.
    pub fn allow(&mut self, now: Instant) -> bool {
        while let Some(&t) = self.hits.front() {
            if now.duration_since(t) >= self.window {
                self.hits.pop_front();
            } else {
                break;
            }
        }
        if self.hits.len() >= self.max {
            return false;
        }
        self.hits.push_back(now);
        true
    }
}

/// Sliding-window byte budget: at most `max_bytes` per `window`.
#[derive(Debug)]
pub struct ByteBudget {
    max_bytes: u64,
    window: Duration,
    spent: VecDeque<(Instant, u64)>,
}

impl ByteBudget {
    pub fn new(max_bytes: u64, window: Duration) -> Self {
        Self {
            max_bytes,
            window,
            spent: VecDeque::new(),
        }
    }

    /// Bytes spent inside the window ending at `now` (expired entries are dropped).
    pub fn used(&mut self, now: Instant) -> u64 {
        while let Some(&(t, _)) = self.spent.front() {
            if now.duration_since(t) >= self.window {
                self.spent.pop_front();
            } else {
                break;
            }
        }
        self.spent.iter().map(|(_, b)| *b).sum()
    }

    /// The window has no room left at all (a download of unknown size is refused up front).
    pub fn exhausted(&mut self, now: Instant) -> bool {
        self.used(now) >= self.max_bytes
    }

    /// Spend `bytes` at `now` if the window still has room; returns false (and spends nothing) otherwise.
    pub fn spend(&mut self, now: Instant, bytes: u64) -> bool {
        if self.used(now).saturating_add(bytes) > self.max_bytes {
            return false;
        }
        self.spent.push_back((now, bytes));
        true
    }

    /// Charge `bytes` that were ALREADY written (a WebKit download, whose size is known only when it
    /// finished): always recorded, so later downloads see the spend; returns whether the window still had
    /// room for them (false = over budget: the caller removes the file).
    pub fn charge(&mut self, now: Instant, bytes: u64) -> bool {
        let within = self.used(now).saturating_add(bytes) <= self.max_bytes;
        self.spent.push_back((now, bytes));
        within
    }
}

// ---------------------------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use time::macros::datetime;

    fn ui() -> Url {
        Url::parse("http://127.0.0.1:8010").unwrap()
    }

    fn ctx<'a>(ui: &'a Url, frames: &'a [String], boot: bool) -> NavContext<'a> {
        NavContext {
            ui,
            boot_permitted: boot,
            frame_hosts: frames,
        }
    }

    fn nav(u: &str, boot: bool) -> NavDecision {
        let ui = ui();
        let frames = vec!["tradingview.com".to_string(), "tradingview-widget.com".to_string()];
        navigation_decision(&Url::parse(u).unwrap(), &ctx(&ui, &frames, boot))
    }

    #[test]
    fn same_origin_with_localhost_equivalence() {
        let ui = ui();
        for ok in [
            "http://127.0.0.1:8010/",
            "http://localhost:8010/?tab=desk",
            "http://LOCALHOST:8010/x#y",
        ] {
            assert!(same_ui_origin(&Url::parse(ok).unwrap(), &ui), "{ok}");
        }
        for bad in [
            "http://127.0.0.1:8011/",
            "https://127.0.0.1:8010/",
            "http://127.0.0.2:8010/",
            "http://[::1]:8010/",
            "http://evil.com:8010/",
            "http://user:pw@127.0.0.1:8010/",
            "http://127.0.0.1/",
        ] {
            assert!(!same_ui_origin(&Url::parse(bad).unwrap(), &ui), "{bad}");
        }
        let lh = Url::parse("http://localhost:8010").unwrap();
        assert!(same_ui_origin(&Url::parse("http://127.0.0.1:8010/a").unwrap(), &lh));
    }

    #[test]
    fn exact_origin_and_canonicalization() {
        let ui = ui();
        assert!(exact_ui_origin(
            &Url::parse("http://127.0.0.1:8010/?tab=desk").unwrap(),
            &ui
        ));
        for not_exact in [
            "http://localhost:8010/",
            "http://127.0.0.1:8011/",
            "https://127.0.0.1:8010/",
            "http://u@127.0.0.1:8010/",
        ] {
            assert!(!exact_ui_origin(&Url::parse(not_exact).unwrap(), &ui), "{not_exact}");
        }
        assert_eq!(
            canonical_ui_url(&Url::parse("http://LOCALHOST:8010/?tab=desk#x").unwrap(), &ui).map(|u| u.to_string()),
            Some("http://127.0.0.1:8010/?tab=desk#x".to_string())
        );
        assert_eq!(
            canonical_ui_url(&Url::parse("http://127.0.0.1:8010/").unwrap(), &ui),
            None
        );
        assert_eq!(
            canonical_ui_url(&Url::parse("http://localhost:8011/").unwrap(), &ui),
            None
        );
        assert_eq!(
            canonical_ui_url(&Url::parse("http://evil.com:8010/").unwrap(), &ui),
            None
        );
        // a localhost-configured ui canonicalizes the other way
        let lh = Url::parse("http://localhost:8010").unwrap();
        assert_eq!(
            canonical_ui_url(&Url::parse("http://127.0.0.1:8010/a").unwrap(), &lh).map(|u| u.to_string()),
            Some("http://localhost:8010/a".to_string())
        );
    }

    #[test]
    fn navigation_allowlist() {
        assert_eq!(nav("http://127.0.0.1:8010/?tab=brief", false), NavDecision::Allow);
        assert_eq!(
            nav("http://localhost:8010/_next/x.js", false),
            NavDecision::Canonical(Url::parse("http://127.0.0.1:8010/_next/x.js").unwrap())
        );
        assert_eq!(nav("tauri://localhost/index.html", true), NavDecision::Allow);
        assert!(matches!(
            nav("tauri://localhost/index.html", false),
            NavDecision::Deny(_)
        ));
        assert!(matches!(nav("tauri://evil/index.html", true), NavDecision::Deny(_)));
        assert_eq!(
            nav("https://www.nseindia.com/get-quotes", false),
            NavDecision::OpenExternal
        );
        assert_eq!(nav("http://example.com/", false), NavDecision::OpenExternal);
        // embedded widget frames
        assert_eq!(
            nav("https://s.tradingview.com/widgetembed/?symbol=X", false),
            NavDecision::Allow
        );
        assert_eq!(
            nav("https://www.tradingview-widget.com/embed", false),
            NavDecision::Allow
        );
        assert_eq!(nav("https://nottradingview.com/", false), NavDecision::OpenExternal);
        // embedded-frame hosts over cleartext are refused (C2-security-10)
        assert!(matches!(
            nav("http://s.tradingview.com/widgetembed/?symbol=X", false),
            NavDecision::Deny(_)
        ));
        assert!(matches!(nav("http://tradingview.com/", false), NavDecision::Deny(_)));
        // other loopback services are never navigable
        for u in [
            "http://127.0.0.1:8001/health",
            "http://localhost:8008/",
            "http://[::1]:8010/",
            "http://0.0.0.0:8010/",
            "http://foo.localhost:8010/",
        ] {
            assert!(matches!(nav(u, false), NavDecision::Deny(_)), "{u}");
        }
        for u in [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "data:text/html,<b>x</b>",
            "ftp://x.com/",
            "suryadhana://x",
            "about:config",
            "blob:https://evil.com/uuid",
            "mailto:a@b.c",
        ] {
            assert!(matches!(nav(u, true), NavDecision::Deny(_)), "{u}");
        }
        assert_eq!(nav("about:blank", false), NavDecision::Allow);
        assert_eq!(nav("about:srcdoc", false), NavDecision::Allow);
        assert_eq!(nav("blob:http://127.0.0.1:8010/1b2c", false), NavDecision::Allow);
        assert!(matches!(
            nav("https://user:pw@example.com/", false),
            NavDecision::Deny(_)
        ));
    }

    #[test]
    fn main_frame_guard() {
        let ui = ui();
        assert!(main_frame_allowed(
            &Url::parse("tauri://localhost/index.html?mode=boot").unwrap(),
            &ui
        ));
        assert!(main_frame_allowed(
            &Url::parse("http://127.0.0.1:8010/?tab=sys").unwrap(),
            &ui
        ));
        // the alias spelling has no IPC grant: a main frame that lands there is bounced
        assert!(!main_frame_allowed(
            &Url::parse("http://localhost:8010/?tab=sys").unwrap(),
            &ui
        ));
        assert!(!main_frame_allowed(
            &Url::parse("https://s.tradingview.com/widgetembed/").unwrap(),
            &ui
        ));
        assert!(!main_frame_allowed(&Url::parse("http://127.0.0.1:8001/").unwrap(), &ui));
    }

    #[test]
    fn new_window_routing() {
        let ui = ui();
        assert_eq!(
            new_window_decision(&Url::parse("http://localhost:8010/?tab=desk").unwrap(), &ui),
            NewWindowDecision::Terminal("/?tab=desk".into())
        );
        assert_eq!(
            new_window_decision(
                &Url::parse("https://in.tradingview.com/chart/?symbol=NSE:TCS").unwrap(),
                &ui
            ),
            NewWindowDecision::External
        );
        assert!(matches!(
            new_window_decision(&Url::parse("http://127.0.0.1:8001/").unwrap(), &ui),
            NewWindowDecision::Deny(_)
        ));
        assert!(matches!(
            new_window_decision(&Url::parse("file:///tmp/x").unwrap(), &ui),
            NewWindowDecision::Deny(_)
        ));
        assert!(matches!(
            new_window_decision(&Url::parse("about:blank").unwrap(), &ui),
            NewWindowDecision::Deny(_)
        ));
        assert!(matches!(
            new_window_decision(&Url::parse("javascript:void(0)").unwrap(), &ui),
            NewWindowDecision::Deny(_)
        ));
    }

    #[test]
    fn external_url_validation() {
        assert!(validate_external_url("https://www.nseindia.com/companies-listing").is_ok());
        assert!(validate_external_url(" http://finance.yahoo.com/quote/TCS.NS ").is_ok());
        for bad in [
            "",
            "ftp://x.com",
            "file:///etc/hosts",
            "javascript:alert(1)",
            "http://127.0.0.1:8010/",
            "http://localhost/",
            "http://[::1]/",
            "http://0.0.0.0/",
            "https://u:p@example.com/",
            "not a url",
            "tauri://localhost/index.html",
            "data:text/plain,hi",
        ] {
            assert!(validate_external_url(bad).is_err(), "{bad}");
        }
        let long = format!("https://example.com/{}", "a".repeat(2100));
        assert!(validate_external_url(&long).is_err());
        let ok = format!("https://example.com/{}", "a".repeat(2048 - 20));
        assert_eq!(ok.len(), 2048);
        assert!(validate_external_url(&ok).is_ok());
    }

    #[test]
    fn filename_sanitizer() {
        assert_eq!(sanitize_filename("desk_nav.csv"), "desk_nav.csv");
        assert_eq!(sanitize_filename("../../etc/passwd"), "passwd");
        assert_eq!(sanitize_filename("..\\..\\win.ini"), "win.ini");
        assert_eq!(
            sanitize_filename("/abs/path/report 2026-10-24.csv"),
            "report 2026-10-24.csv"
        );
        assert_eq!(sanitize_filename(".hidden"), "hidden");
        assert_eq!(sanitize_filename("-rf.csv"), "rf.csv");
        assert_eq!(sanitize_filename("a$b`c;d|e.csv"), "a_b_c_d_e.csv");
        let devanagari = "नमस्ते";
        assert_eq!(
            sanitize_filename(&format!("{devanagari}.csv")),
            format!("{}.csv", "_".repeat(devanagari.chars().count()))
        );
        assert_eq!(sanitize_filename(""), "download");
        assert_eq!(sanitize_filename("..."), "download");
        assert_eq!(sanitize_filename("a   b.csv"), "a b.csv");
        assert_eq!(sanitize_filename("x.csv. "), "x.csv");
        let long = format!("{}.csv", "x".repeat(300));
        let s = sanitize_filename(&long);
        assert_eq!(s.chars().count(), 120);
        assert!(s.ends_with(".csv"));
        for c in sanitize_filename("weird\u{0000}\u{202E}name\n.csv").chars() {
            assert!(c.is_ascii_alphanumeric() || "._ -".contains(c));
        }
    }

    #[test]
    fn unique_names() {
        let taken = ["a.csv", "a (1).csv", "noext"];
        let exists = |n: &str| taken.contains(&n);
        assert_eq!(unique_name("b.csv", exists).unwrap(), "b.csv");
        assert_eq!(unique_name("a.csv", exists).unwrap(), "a (2).csv");
        assert_eq!(unique_name("noext", exists).unwrap(), "noext (1)");
        assert!(unique_name("x", |_| true).is_err());
    }

    #[test]
    fn text_validation() {
        assert_eq!(
            validate_plain_text("BRF · SuryaDhana", 120, "title").unwrap(),
            "BRF · SuryaDhana"
        );
        assert_eq!(
            validate_plain_text("a\nb\tc\u{202E}d", 120, "title").unwrap(),
            "a b c d"
        );
        assert!(validate_plain_text(&"x".repeat(121), 120, "title").is_err());
        assert!(validate_plain_text(&"é".repeat(120), 120, "title").is_ok());
        assert_eq!(
            validate_body_text("line1\nline2\u{0007}", 1000).unwrap(),
            "line1\nline2"
        );
        assert!(validate_body_text(&"x".repeat(1001), 1000).is_err());
    }

    #[test]
    fn tab_validation() {
        assert_eq!(validate_tab("desk").unwrap(), "desk");
        assert!(validate_tab("DESK").is_err());
        assert!(validate_tab("desk;rm").is_err());
    }

    #[test]
    fn freeze_guard_edges_in_ist_regardless_of_input_offset() {
        // 07:44:59 IST = 02:14:59 UTC
        assert!(freeze_window_at(datetime!(2026-10-24 02:14:59 UTC)).is_none());
        assert!(freeze_window_at(datetime!(2026-10-24 02:15:00 UTC)).is_some()); // 07:45:00 IST
        assert!(freeze_window_at(datetime!(2026-10-24 03:49:59 UTC)).is_some()); // 09:19:59 IST
        assert!(freeze_window_at(datetime!(2026-10-24 03:50:00 UTC)).is_none()); // 09:20:00 IST
        assert!(freeze_window_at(datetime!(2026-10-24 12:59:59 UTC)).is_none()); // 18:29:59 IST
        assert!(freeze_window_at(datetime!(2026-10-24 13:00:00 UTC)).is_some()); // 18:30:00 IST
        assert!(freeze_window_at(datetime!(2026-10-24 15:44:59 UTC)).is_some()); // 21:14:59 IST
        assert!(freeze_window_at(datetime!(2026-10-24 15:45:00 UTC)).is_none()); // 21:15:00 IST
                                                                                 // The same instants expressed in other offsets (a Mac set to New York / London) give the same answer.
        assert!(freeze_window_at(datetime!(2026-10-24 09:00:00 -4)).is_some()); // 13:00 UTC = 18:30 IST
        assert!(freeze_window_at(datetime!(2026-10-24 08:59:59 -4)).is_none());
        assert!(freeze_window_at(datetime!(2026-10-24 03:15:00 +1)).is_some()); // 02:15 UTC = 07:45 IST
                                                                                // around IST midnight (date rolls over relative to UTC)
        assert!(freeze_window_at(datetime!(2026-10-24 18:30:00 UTC)).is_none()); // 00:00 IST
        let w = freeze_window_at(datetime!(2026-10-24 14:00:00 UTC)).unwrap();
        assert!(w.label.starts_with("18:30"));
        assert_eq!(ist_clock(datetime!(2026-10-24 05:40:05 UTC)), "11:10:05");
    }

    #[test]
    fn rate_limiter_sliding_window() {
        let t0 = Instant::now();
        let mut rl = RateLimiter::new(20, Duration::from_secs(60));
        for i in 0..20 {
            assert!(rl.allow(t0 + Duration::from_millis(i)), "{i}");
        }
        assert!(!rl.allow(t0 + Duration::from_secs(30)));
        assert!(rl.allow(t0 + Duration::from_secs(60))); // first hit expired
        assert!(!rl.allow(t0 + Duration::from_secs(60)));
    }

    #[test]
    fn redaction_never_keeps_query() {
        let u = Url::parse("https://api.icicidirect.com/apiuser/login?api_key=SECRET123").unwrap();
        let r = redact_url(&u);
        assert!(!r.contains("SECRET123"));
        assert_eq!(r, "https://api.icicidirect.com/apiuser/login?…");
        assert_eq!(redact_raw("javascript:steal(document.cookie)"), "javascript:…");
        assert!(!redact_raw("data:text/html,secret").contains("secret"));
        assert_eq!(redact_raw("::"), "<unparseable url>");
    }

    #[test]
    fn loopback_detection() {
        for h in [
            "localhost",
            "LOCALHOST",
            "a.localhost",
            "127.0.0.1",
            "127.8.9.1",
            "0.0.0.0",
        ] {
            let u = Url::parse(&format!("http://{h}/")).unwrap();
            assert!(is_loopback_host(&u.host().unwrap()), "{h}");
        }
        for h in ["[::1]", "[::ffff:127.0.0.1]", "[::]"] {
            let u = Url::parse(&format!("http://{h}/")).unwrap();
            assert!(is_loopback_host(&u.host().unwrap()), "{h}");
        }
        let u = Url::parse("http://example.com/").unwrap();
        assert!(!is_loopback_host(&u.host().unwrap()));
        // decimal / hex IPv4 forms normalise to 127.0.0.1 in the URL parser
        let u = Url::parse("http://2130706433/").unwrap();
        assert!(is_loopback_host(&u.host().unwrap()));
    }

    #[test]
    fn download_names_keep_only_allowlisted_extensions() {
        // what the terminal really exports keeps its name
        for ok in [
            "stocks-2026-10-25.csv",
            "backtest-2026-10-25-10-11-12.xlsx",
            "mc_drawdown.json",
            "REPORT.MD",
            "chart.PNG",
            "notes.txt",
            "filing.pdf",
            "x.jpeg",
            "t.tsv",
        ] {
            assert_eq!(download_filename(ok), ok, "{ok}");
        }
        // everything else becomes text (C2-security-05: no .zip/.app/.command/.terminal in ~/Downloads)
        for (raw, want) in [
            ("NIFTY_levels.zip", "NIFTY_levels.zip.txt"),
            ("run.command", "run.command.txt"),
            ("Shell.terminal", "Shell.terminal.txt"),
            ("Setup.pkg", "Setup.pkg.txt"),
            ("link.webloc", "link.webloc.txt"),
            ("page.html", "page.html.txt"),
            ("logo.svg", "logo.svg.txt"),
            ("x.csv.app", "x.csv.app.txt"),
            ("notes", "notes.txt"),
            ("", "download.txt"),
            ("../../evil.sh", "evil.sh.txt"),
        ] {
            assert_eq!(download_filename(raw), want, "{raw}");
        }
        let long = download_filename(&format!("{}.zip", "a".repeat(300)));
        assert_eq!(long.chars().count(), MAX_FILENAME_LEN);
        assert!(long.ends_with(".txt"), "{long}");
        assert!(!has_allowed_extension(".csv"));
        assert!(!has_allowed_extension("csv"));
    }

    #[test]
    fn quarantine_value_format() {
        assert_eq!(quarantine_value(0x6718_0000), "0083;67180000;SuryaDhana;");
        assert_eq!(quarantine_value(1), "0083;00000001;SuryaDhana;");
    }

    const LIVE_UI_API: &str =
        "/opt/homebrew/Cellar/python@3.13/3.13.15/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python";

    #[test]
    fn trusted_python_locations_survive_a_brew_upgrade() {
        let t = |p: &str| is_trusted_python_exe(Path::new(p), &[]);
        // the live ui-api (25 Oct): the framework Python.app under the Cellar keg
        assert!(t(LIVE_UI_API));
        // simulated `brew upgrade python@3.13` 3.13.15 -> 3.13.16: the still-running ui-api keeps the OLD keg
        // path (and that keg may already be deleted: the rule never looks at the disk), the restarted one the
        // new path; both are trusted, so the upgrade can never produce a false NOT TRUSTED
        let old = LIVE_UI_API;
        let new = LIVE_UI_API.replace("3.13.15", "3.13.16");
        assert!(t(old) && t(&new));
        assert!(!Path::new("/opt/homebrew/Cellar/python@3.13/3.13.99").exists());
        assert!(
            t(&LIVE_UI_API.replace("3.13.15", "3.13.99")),
            "a keg that does not exist on disk"
        );
        assert!(t(&LIVE_UI_API.replace("3.13.15", "3.13.0_1")), "a Homebrew revision");
        // negative control: round 1's rule (`exe.starts_with(prefix)`, prefix = the canonicalized venv python's
        // keg, i.e. the NEW keg after the upgrade) refused the still-running ui-api: a false NOT TRUSTED
        let round1 = |exe: &str, prefix: &str| Path::new(exe).starts_with(prefix);
        let new_prefix = "/opt/homebrew/Cellar/python@3.13/3.13.16/Frameworks/Python.framework/Versions/3.13";
        assert!(
            !round1(old, new_prefix),
            "round 1 judged the running ui-api foreign after brew upgrade"
        );
        assert!(round1(&new, new_prefix));
        // a minor upgrade (python@3.14) and a framework run that did not re-exec
        assert!(t(
            "/opt/homebrew/Cellar/python@3.14/3.14.1/Frameworks/Python.framework/Versions/3.14/Resources/Python.app/Contents/MacOS/Python"
        ));
        assert!(t(
            "/opt/homebrew/Cellar/python@3.13/3.13.15/Frameworks/Python.framework/Versions/3.13/bin/python3.13"
        ));
        assert!(t(
            "/opt/homebrew/opt/python@3.13/Frameworks/Python.framework/Versions/3.13/bin/python3"
        ));
        assert!(t("/usr/local/Cellar/python@3.12/3.12.7/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"));
        // python.org installer
        assert!(t(
            "/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python"
        ));
        assert!(t("/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12"));
    }

    #[test]
    fn untrusted_executables() {
        let t = |p: &str| is_trusted_python_exe(Path::new(p), &[]);
        for bad in [
            // the system / Command Line Tools / Xcode Python (what any process finds first)
            "/usr/bin/python3",
            "/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python",
            "/Applications/Xcode.app/Contents/Developer/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9",
            // a helper app, node, a copied interpreter in a writable place
            "/Applications/Helper.app/Contents/MacOS/Helper",
            "/opt/homebrew/Cellar/node/22.1.0/bin/node",
            "/Users/x/Library/Containers/evil/Data/python3",
            "/tmp/Python.framework/Versions/3.13/bin/python3.13",
            // malformed Homebrew shapes: version / minor mismatch, wrong tail, traversal, relative
            "/opt/homebrew/Cellar/python@3.13/3.12.1/Frameworks/Python.framework/Versions/3.13/bin/python3.13",
            "/opt/homebrew/Cellar/python@3.13/3.13.15/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
            "/opt/homebrew/Cellar/python@3.13/3.13.15/Frameworks/Python.framework/Versions/3.13/bin/evil",
            "/opt/homebrew/Cellar/python@3.13/3.13.15/Frameworks/Python.framework/Versions/3.13/lib/x/Python",
            "/opt/homebrew/Cellar/python@3.13/../../../tmp/Python",
            "/opt/homebrew/Cellar/python@3.x/3.x.1/Frameworks/Python.framework/Versions/3.x/bin/python3",
            "opt/homebrew/Cellar/python@3.13/3.13.15/Frameworks/Python.framework/Versions/3.13/bin/python3",
            "/Library/Frameworks/Python.framework/Versions/2.7/bin/python2.7",
            "/Library/Frameworks/Python.framework/Versions/3.12/bin/sh",
        ] {
            assert!(!t(bad), "{bad}");
        }
        // config trusted_python_prefixes: absolute, component-wise; "/" alone and relative entries are ignored
        let venv = PathBuf::from("/Users/x/Desktop/jupyter_env/bin");
        assert!(is_trusted_python_exe(
            Path::new("/Users/x/Desktop/jupyter_env/bin/python3"),
            std::slice::from_ref(&venv)
        ));
        assert!(!is_trusted_python_exe(
            Path::new("/Users/x/Desktop/jupyter_env/binx/python3"),
            &[venv]
        ));
        assert!(!is_trusted_python_exe(
            Path::new("/usr/bin/python3"),
            &[PathBuf::from("/")]
        ));
        assert!(!is_trusted_python_exe(
            Path::new("/usr/bin/python3"),
            &[PathBuf::from("usr")]
        ));
    }

    #[test]
    fn listener_trust_rule() {
        let stack = Listener {
            pid: 42,
            uid: Some(501),
            exe: Some(PathBuf::from(LIVE_UI_API)),
            start: Some((1_761_380_000, 5)),
        };
        let judge = |l: &[Listener], invisible: bool| listener_trust(l, invisible, 501, &[], &[]);
        let foreign = |l: &[Listener]| matches!(judge(l, false), Err(TrustFail::Foreign(_)));
        let unknown = |l: &[Listener]| matches!(judge(l, false), Err(TrustFail::Unknown(_)));
        let ok = judge(std::slice::from_ref(&stack), false).unwrap();
        assert!(ok.contains("pid 42"), "{ok}");
        // uvicorn --reload: reloader + worker share the socket, both the stack's Python
        assert!(judge(
            &[
                stack.clone(),
                Listener {
                    pid: 43,
                    ..stack.clone()
                }
            ],
            false
        )
        .is_ok());
        // a sandboxed helper app that bound the port first
        let squatter = Listener {
            pid: 66,
            uid: Some(501),
            exe: Some(PathBuf::from("/Applications/Helper.app/Contents/MacOS/Helper")),
            start: Some((1_761_380_100, 0)),
        };
        let e = judge(std::slice::from_ref(&squatter), false).unwrap_err();
        assert!(
            e.message().contains("pid 66") && e.message().contains("Helper.app"),
            "{e:?}"
        );
        assert!(foreign(std::slice::from_ref(&squatter)));
        assert!(e.denies());
        // the system python is NOT the stack's python
        let system = Listener {
            pid: 7,
            uid: Some(501),
            exe: Some(PathBuf::from("/usr/bin/python3")),
            start: None,
        };
        assert!(foreign(&[system]));
        // another user's process is foreign; a mixed set fails on the foreign one
        let other = Listener {
            uid: Some(0),
            ..stack.clone()
        };
        assert!(judge(std::slice::from_ref(&other), false)
            .unwrap_err()
            .message()
            .contains("uid 0"));
        assert!(foreign(&[stack.clone(), squatter]));
        // the port answers but nobody of this account holds it: another account's process (definitive)
        assert!(matches!(judge(&[], true), Err(TrustFail::Foreign(_))));
        // inconclusive: nothing listening (restart), a pid that vanished mid-check (owner unreadable)
        assert!(unknown(&[]));
        let vanished = Listener {
            uid: None,
            exe: None,
            pid: 9,
            start: None,
        };
        assert!(unknown(std::slice::from_ref(&vanished)));
        assert!(!judge(std::slice::from_ref(&vanished), false).unwrap_err().denies());
    }

    #[test]
    fn a_live_listener_with_an_unreadable_executable_is_trusted_only_when_pinned() {
        // R-RUST-02: round 2 mapped "uid readable, executable unreadable" to Unknown, and Unknown never holds a
        // window back: a squatter that unlinked its own binary was served as the terminal origin
        let gone = Listener {
            pid: 57_979,
            uid: Some(501),
            exe: None,
            start: Some((1_761_390_000, 123)),
        };
        let e = listener_trust(std::slice::from_ref(&gone), false, 501, &[], &[]).unwrap_err();
        assert!(matches!(e, TrustFail::Unverifiable(_)), "{e:?}");
        assert!(
            e.denies(),
            "an unidentifiable live listener keeps windows off the terminal origin"
        );
        assert!(e.message().contains("pid 57979"), "{e:?}");
        // the running ui-api verified BEFORE `brew cleanup` deleted its keg: the same pid + start time stays trusted
        let pin = gone.id().unwrap();
        let ok = listener_trust(std::slice::from_ref(&gone), false, 501, &[], &[pin]).unwrap();
        assert!(ok.contains("pid 57979") && ok.contains("verified earlier"), "{ok}");
        // a REUSED pid (same number, another start time) never inherits the pin
        let reused = ProcId {
            pid: 57_979,
            start: (1_761_390_999, 0),
        };
        assert!(matches!(
            listener_trust(std::slice::from_ref(&gone), false, 501, &[], &[reused]),
            Err(TrustFail::Unverifiable(_))
        ));
        // no start time: never matches a pin
        let no_start = Listener {
            start: None,
            ..gone.clone()
        };
        assert!(matches!(
            listener_trust(std::slice::from_ref(&no_start), false, 501, &[], &[pin]),
            Err(TrustFail::Unverifiable(_))
        ));
        // another user's process with an unreadable executable is still Foreign (uid rule first)
        let other = Listener {
            uid: Some(0),
            ..gone.clone()
        };
        assert!(matches!(
            listener_trust(std::slice::from_ref(&other), false, 501, &[], &[pin]),
            Err(TrustFail::Foreign(_))
        ));
        // the ids stored as pins after a pass
        let stack = Listener {
            pid: 42,
            uid: Some(501),
            exe: Some(PathBuf::from(LIVE_UI_API)),
            start: Some((7, 8)),
        };
        assert_eq!(
            listener_ids(&[stack, no_start]),
            vec![ProcId { pid: 42, start: (7, 8) }]
        );
    }

    #[test]
    fn symbols_for_deep_links() {
        for ok in [
            "TCS",
            "M&M",
            "BAJAJ-AUTO",
            "NIFTY_50",
            "L.T",
            "A",
            "ABCDEFGHIJ0123456789",
        ] {
            assert_eq!(validate_symbol(ok).unwrap(), ok, "{ok}");
        }
        for bad in [
            "",
            "tcs",
            "TCS ",
            " TCS",
            "TCS;rm",
            "TCS/../X",
            "<script>",
            "ABCDEFGHIJ01234567890",
            "TCS#x",
            "TCS?x=1",
            "ТCS", // Cyrillic T
        ] {
            assert!(validate_symbol(bad).is_err(), "{bad:?}");
        }
    }

    #[test]
    fn byte_budget_sliding_window() {
        let t0 = Instant::now();
        let mut b = ByteBudget::new(100, Duration::from_secs(3600));
        assert!(b.spend(t0, 60));
        assert!(b.spend(t0, 40));
        assert!(!b.spend(t0 + Duration::from_secs(10), 1));
        assert!(b.spend(t0 + Duration::from_secs(3600), 100)); // both earlier spends expired
        assert!(!b.spend(t0 + Duration::from_secs(3600), 1));
        let mut big = ByteBudget::new(10, Duration::from_secs(1));
        assert!(!big.spend(t0, 11), "a single over-budget spend is refused");
        // charges of already-written bytes (WebKit): always recorded, and they exhaust the window
        let mut w = ByteBudget::new(100, Duration::from_secs(3600));
        assert!(!w.exhausted(t0));
        assert!(w.charge(t0, 70));
        assert!(!w.charge(t0, 40), "over budget: the caller removes that file");
        assert!(
            w.exhausted(t0),
            "and the next download of unknown size is refused up front"
        );
        assert!(!w.spend(t0, 1));
        assert_eq!(w.used(t0 + Duration::from_secs(3600)), 0, "expired after the window");
    }

    #[test]
    fn base64_bound_covers_limit() {
        // 50 MiB encodes to exactly ceil(n/3)*4 characters
        assert!(max_base64_len() >= MAX_DOWNLOAD_BYTES.div_ceil(3) * 4);
    }
}
