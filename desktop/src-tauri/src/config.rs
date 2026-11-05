//! User configuration: `~/Library/Application Support/ai.suryadhana.terminal/config.json`.
//!
//! * Created with defaults on first run; missing keys are filled in (file rewritten) on later runs.
//! * Tolerant parse: unknown keys are ignored, an invalid value falls back to its default (logged),
//!   and an unparseable file is left untouched (defaults are used for this run, never overwritten).
//! * Every service URL must be plain `http` on a loopback host (`127.0.0.1` or `localhost`): the shell
//!   grants IPC commands to the `ui_url` origin, so it must never point off-machine.
//! * `SURYADHANA_UI_URL` (environment) overrides `ui_url` for testing (same validation);
//!   `SURYADHANA_STARTUP_GRACE_S` overrides `startup_grace_secs` (0..=900; self-test / drills).
//! * The port-squatting guard (`verify_ui_listener`, default true) opens a terminal window only when every
//!   process listening on the `ui_url` port belongs to this user and is a CPython executable in a Homebrew /
//!   python.org location (trust.rs, policy.rs). It never reads the stack's interpreter path (the venv lives
//!   under ~/Desktop, which macOS privacy protects). `trusted_python_prefixes` (default `[]`) adds absolute
//!   executable-path prefixes for another interpreter layout (pyenv, a venv made with `--copies`); compared as
//!   strings only. The round-1 key `stack_python` is ignored (a warning when it is set).
//! * `startup_grace_secs` (default 180): after a login start (`--autostart`, or within that long of the
//!   system boot) and after Start Stack, the boot page shows "Starting the stack…" instead of the red
//!   down state and offers no Start/Stop actions.
//!
//! Session state (open windows, first-run markers) lives next to it in `state.json` (see windows.rs).

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::Value;
use url::Url;

/// Config file name inside the app config dir.
pub const CONFIG_FILE: &str = "config.json";

pub const DEFAULT_UI_URL: &str = "http://127.0.0.1:8010";
pub const DEFAULT_DATA_SERVICE_URL: &str = "http://127.0.0.1:8001";
pub const DEFAULT_CONTROLLER_URL: &str = "http://127.0.0.1:8008";
/// Default start-up grace (s): the watchdog's login start took 60-223 s in the logs (25 Oct, 24 Oct, 22 Oct).
pub const DEFAULT_STARTUP_GRACE_SECS: u64 = 180;
/// Upper bound for `startup_grace_secs` (and the env override).
pub const MAX_STARTUP_GRACE_SECS: u64 = 900;
/// Maximum number of `trusted_python_prefixes` entries.
pub const MAX_TRUSTED_PREFIXES: usize = 8;

/// Repo root baked at build time (env `SURYADHANA_ROOT`, else the repo containing desktop/).
pub fn default_repo_root() -> PathBuf {
    PathBuf::from(option_env!("SURYADHANA_ROOT_DEFAULT").unwrap_or("/Users/sudheer/MahaKubera_108/SuryaDhana_AI"))
}

/// Host suffixes allowed to load as embedded frames in terminal pages (TradingView chart widget).
pub fn default_frame_hosts() -> Vec<String> {
    vec!["tradingview.com".into(), "tradingview-widget.com".into()]
}

/// Effective, validated configuration.
#[derive(Debug, Clone, PartialEq)]
pub struct Config {
    pub repo_root: PathBuf,
    /// Terminal origin (scheme://host:port, no path).
    pub ui_url: Url,
    pub data_service_url: Url,
    pub controller_url: Url,
    pub nifty_in_menubar: bool,
    pub notify_service_changes: bool,
    pub devtools: bool,
    pub frame_hosts: Vec<String>,
    /// Boot-page start-up grace in seconds (see module docs).
    pub startup_grace_secs: u64,
    /// Extra executable-path prefixes the port-squatting guard trusts (absolute; string compare only).
    pub trusted_python_prefixes: Vec<PathBuf>,
    /// Port-squatting guard on/off (on by default; only for development servers that are not Python).
    pub verify_ui_listener: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            repo_root: default_repo_root(),
            ui_url: Url::parse(DEFAULT_UI_URL).expect("default ui url"),
            data_service_url: Url::parse(DEFAULT_DATA_SERVICE_URL).expect("default ds url"),
            controller_url: Url::parse(DEFAULT_CONTROLLER_URL).expect("default mc url"),
            nifty_in_menubar: true,
            notify_service_changes: true,
            devtools: false,
            frame_hosts: default_frame_hosts(),
            startup_grace_secs: DEFAULT_STARTUP_GRACE_SECS,
            trusted_python_prefixes: vec![],
            verify_ui_listener: true,
        }
    }
}

/// On-disk representation (all keys written, in this order).
#[derive(Debug, Serialize)]
struct ConfigFile<'a> {
    repo_root: String,
    ui_url: &'a str,
    data_service_url: &'a str,
    controller_url: &'a str,
    nifty_in_menubar: bool,
    notify_service_changes: bool,
    devtools: bool,
    frame_hosts: &'a [String],
    startup_grace_secs: u64,
    trusted_python_prefixes: Vec<String>,
    verify_ui_listener: bool,
}

/// Result of loading: the config plus human-readable warnings (logged by the caller).
#[derive(Debug, Clone)]
pub struct Loaded {
    pub config: Config,
    pub warnings: Vec<String>,
    /// True when the file should be (re)written: missing, or parsed but missing keys.
    pub needs_write: bool,
}

/// Validate a service URL: http, loopback host (127.0.0.1 / localhost), no credentials. Returns the
/// origin only (path/query/fragment dropped).
pub fn validate_service_url(raw: &str) -> Result<Url, String> {
    let url = Url::parse(raw.trim()).map_err(|e| format!("not a URL ({e})"))?;
    if url.scheme() != "http" {
        return Err("must use http://".into());
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err("must not contain credentials".into());
    }
    match url.host_str() {
        Some("127.0.0.1") | Some("localhost") => {}
        _ => return Err("host must be 127.0.0.1 or localhost".into()),
    }
    let origin = match url.port() {
        Some(p) => format!("http://{}:{}", url.host_str().unwrap_or("127.0.0.1"), p),
        None => format!("http://{}", url.host_str().unwrap_or("127.0.0.1")),
    };
    Url::parse(&origin).map_err(|e| e.to_string())
}

/// An absolute, non-root path without `..` components (a `trusted_python_prefixes` entry).
fn valid_prefix(s: &str) -> bool {
    let p = Path::new(s);
    p.is_absolute()
        && p.components().count() > 1
        && !p.components().any(|c| matches!(c, std::path::Component::ParentDir))
}

/// Origin string without the trailing slash `Url` adds (`http://127.0.0.1:8010`).
pub fn origin_str(url: &Url) -> String {
    url.as_str().trim_end_matches('/').to_string()
}

/// Test/drill overrides from the environment (never persisted).
#[derive(Debug, Clone, Copy, Default)]
pub struct EnvOverrides<'a> {
    /// `SURYADHANA_UI_URL`
    pub ui_url: Option<&'a str>,
    /// `SURYADHANA_STARTUP_GRACE_S`
    pub startup_grace: Option<&'a str>,
}

/// Parse config JSON text tolerantly. `env_ui_url` is the `SURYADHANA_UI_URL` override, if set.
pub fn parse(text: Option<&str>, env_ui_url: Option<&str>) -> Loaded {
    parse_with(
        text,
        EnvOverrides {
            ui_url: env_ui_url,
            startup_grace: None,
        },
    )
}

/// [`parse`] with every environment override.
pub fn parse_with(text: Option<&str>, env: EnvOverrides<'_>) -> Loaded {
    let env_ui_url = env.ui_url;
    let mut cfg = Config::default();
    let mut warnings = Vec::new();
    let mut needs_write = text.is_none();

    let obj = match text.map(serde_json::from_str::<Value>) {
        None => None,
        Some(Ok(Value::Object(m))) => Some(m),
        Some(Ok(_)) => {
            warnings.push("config.json is not a JSON object; using defaults (file left untouched)".into());
            None
        }
        Some(Err(e)) => {
            warnings.push(format!(
                "config.json does not parse ({e}); using defaults (file left untouched)"
            ));
            None
        }
    };

    if let Some(m) = &obj {
        for key in [
            "repo_root",
            "ui_url",
            "data_service_url",
            "controller_url",
            "nifty_in_menubar",
            "notify_service_changes",
            "devtools",
            "frame_hosts",
            "startup_grace_secs",
            "trusted_python_prefixes",
            "verify_ui_listener",
        ] {
            if !m.contains_key(key) {
                needs_write = true;
            }
        }
        if let Some(v) = m.get("repo_root") {
            match v.as_str().map(str::trim).filter(|s| !s.is_empty()) {
                Some(s) if Path::new(s).is_absolute() => cfg.repo_root = PathBuf::from(s),
                _ => warnings.push("repo_root must be an absolute path; using the default".into()),
            }
        }
        for (key, slot) in [
            ("ui_url", &mut cfg.ui_url),
            ("data_service_url", &mut cfg.data_service_url),
            ("controller_url", &mut cfg.controller_url),
        ] {
            if let Some(v) = m.get(key) {
                match v.as_str().map(validate_service_url) {
                    Some(Ok(u)) => *slot = u,
                    Some(Err(e)) => warnings.push(format!("{key} rejected: {e}; using the default")),
                    None => warnings.push(format!("{key} must be a string; using the default")),
                }
            }
        }
        for (key, slot) in [
            ("nifty_in_menubar", &mut cfg.nifty_in_menubar),
            ("notify_service_changes", &mut cfg.notify_service_changes),
            ("devtools", &mut cfg.devtools),
            ("verify_ui_listener", &mut cfg.verify_ui_listener),
        ] {
            if let Some(v) = m.get(key) {
                match v.as_bool() {
                    Some(b) => *slot = b,
                    None => warnings.push(format!("{key} must be true/false; using the default")),
                }
            }
        }
        if let Some(v) = m.get("frame_hosts") {
            match v.as_array() {
                Some(a) => {
                    cfg.frame_hosts = a
                        .iter()
                        .filter_map(|x| x.as_str())
                        .map(|s| s.trim().trim_start_matches('.').to_ascii_lowercase())
                        .filter(|s| {
                            !s.is_empty()
                                && s.contains('.')
                                && s.chars().all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-')
                        })
                        .take(32)
                        .collect()
                }
                None => warnings.push("frame_hosts must be an array of host suffixes; using the default".into()),
            }
        }
        if let Some(v) = m.get("startup_grace_secs") {
            match v.as_u64() {
                Some(n) if n <= MAX_STARTUP_GRACE_SECS => cfg.startup_grace_secs = n,
                _ => warnings.push(format!(
                    "startup_grace_secs must be an integer 0..={MAX_STARTUP_GRACE_SECS}; using the default"
                )),
            }
        }
        if let Some(v) = m.get("trusted_python_prefixes") {
            match v.as_array() {
                Some(a) => {
                    let mut out = vec![];
                    for x in a {
                        match x.as_str().map(str::trim) {
                            Some(s) if valid_prefix(s) => out.push(PathBuf::from(s)),
                            _ => {
                                warnings.push(format!("trusted_python_prefixes: {x} is not an absolute path; ignored"))
                            }
                        }
                    }
                    out.truncate(MAX_TRUSTED_PREFIXES);
                    cfg.trusted_python_prefixes = out;
                }
                None => warnings.push("trusted_python_prefixes must be an array of absolute paths; using []".into()),
            }
        }
        // round-1 key: the guard no longer resolves the stack's interpreter (it lives under ~/Desktop)
        if m.get("stack_python").map(|v| !v.is_null()).unwrap_or(false) {
            warnings.push(
                "stack_python is no longer used (the port guard never reads ~/Desktop); use trusted_python_prefixes"
                    .into(),
            );
        }
    }

    if let Some(raw) = env_ui_url.map(str::trim).filter(|s| !s.is_empty()) {
        match validate_service_url(raw) {
            Ok(u) => cfg.ui_url = u,
            Err(e) => warnings.push(format!(
                "SURYADHANA_UI_URL rejected: {e}; keeping {}",
                origin_str(&cfg.ui_url)
            )),
        }
    }

    if let Some(raw) = env.startup_grace.map(str::trim).filter(|s| !s.is_empty()) {
        match raw.parse::<u64>() {
            Ok(n) if n <= MAX_STARTUP_GRACE_SECS => cfg.startup_grace_secs = n,
            _ => warnings.push(format!(
                "SURYADHANA_STARTUP_GRACE_S rejected (0..={MAX_STARTUP_GRACE_SECS}); keeping {}",
                cfg.startup_grace_secs
            )),
        }
    }

    // never rewrite a file the user wrote but we could not parse
    if text.is_some() && obj.is_none() {
        needs_write = false;
    }
    Loaded {
        config: cfg,
        warnings,
        needs_write,
    }
}

/// Serialize the config the way it is written to disk (the env override is NOT persisted: the caller
/// passes the file-backed config).
pub fn to_json(cfg: &Config) -> String {
    let ui = origin_str(&cfg.ui_url);
    let ds = origin_str(&cfg.data_service_url);
    let mc = origin_str(&cfg.controller_url);
    let f = ConfigFile {
        repo_root: cfg.repo_root.display().to_string(),
        ui_url: &ui,
        data_service_url: &ds,
        controller_url: &mc,
        nifty_in_menubar: cfg.nifty_in_menubar,
        notify_service_changes: cfg.notify_service_changes,
        devtools: cfg.devtools,
        frame_hosts: &cfg.frame_hosts,
        startup_grace_secs: cfg.startup_grace_secs,
        trusted_python_prefixes: cfg
            .trusted_python_prefixes
            .iter()
            .map(|p| p.display().to_string())
            .collect(),
        verify_ui_listener: cfg.verify_ui_listener,
    };
    serde_json::to_string_pretty(&f).expect("config serializes") + "\n"
}

/// Write `contents` atomically (temp file + rename) with mode 0600.
pub fn write_atomic(path: &Path, contents: &str) -> std::io::Result<()> {
    write_atomic_mode(path, contents, 0o600)
}

/// Write `contents` atomically (temp file in the same directory + rename) with `mode`.
pub fn write_atomic_mode(path: &Path, contents: &str, mode: u32) -> std::io::Result<()> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let tmp = path.with_extension(format!("tmp.{}", std::process::id()));
    {
        let mut f = fs::File::create(&tmp)?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            f.set_permissions(fs::Permissions::from_mode(mode))?;
        }
        f.write_all(contents.as_bytes())?;
        f.sync_all()?;
    }
    fs::rename(&tmp, path)
}

/// Load (and create / complete) the config file in `dir`. `write` = false never touches disk (self-test).
pub fn load(dir: &Path, write: bool) -> Loaded {
    let path = dir.join(CONFIG_FILE);
    let text = fs::read_to_string(&path).ok();
    let env_ui = std::env::var("SURYADHANA_UI_URL").ok();
    let env_grace = std::env::var("SURYADHANA_STARTUP_GRACE_S").ok();
    let loaded = parse_with(
        text.as_deref(),
        EnvOverrides {
            ui_url: env_ui.as_deref(),
            startup_grace: env_grace.as_deref(),
        },
    );
    if write && loaded.needs_write {
        // persist the file-backed values only (without the env override)
        let file_backed = parse(text.as_deref(), None).config;
        if let Err(e) = write_atomic(&path, &to_json(&file_backed)) {
            let mut l = loaded.clone();
            l.warnings.push(format!("could not write {}: {e}", path.display()));
            return l;
        }
    }
    loaded
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_when_missing_and_marks_for_write() {
        let l = parse(None, None);
        assert!(l.needs_write);
        assert!(l.warnings.is_empty());
        assert_eq!(origin_str(&l.config.ui_url), "http://127.0.0.1:8010");
        assert_eq!(origin_str(&l.config.data_service_url), "http://127.0.0.1:8001");
        assert_eq!(origin_str(&l.config.controller_url), "http://127.0.0.1:8008");
        assert!(l.config.nifty_in_menubar && l.config.notify_service_changes && !l.config.devtools);
        assert!(l.config.repo_root.is_absolute());
    }

    #[test]
    fn full_file_round_trips_without_rewrite() {
        let json = to_json(&Config::default());
        let l = parse(Some(&json), None);
        assert!(!l.needs_write, "{:?}", l.warnings);
        assert_eq!(l.config, Config::default());
    }

    #[test]
    fn tolerant_partial_and_bad_values() {
        let l = parse(
            Some(
                r#"{"ui_url":"http://localhost:8095/some/path?x=1","devtools":"yes","nifty_in_menubar":false,"unknown":1}"#,
            ),
            None,
        );
        assert!(l.needs_write);
        assert_eq!(origin_str(&l.config.ui_url), "http://localhost:8095");
        assert!(!l.config.devtools); // bad value -> default
        assert!(!l.config.nifty_in_menubar);
        assert_eq!(l.warnings.len(), 1, "{:?}", l.warnings);
    }

    #[test]
    fn rejects_non_loopback_and_non_http() {
        for bad in [
            "https://127.0.0.1:8010",
            "http://192.168.1.5:8010",
            "http://evil.com:8010",
            "http://user:pw@127.0.0.1:8010",
            "file:///tmp",
            "http://[::1]:8010",
            "http://127.0.0.2:8010",
            "nonsense",
        ] {
            assert!(validate_service_url(bad).is_err(), "{bad}");
            let l = parse(Some(&format!(r#"{{"ui_url":"{bad}"}}"#)), None);
            assert_eq!(origin_str(&l.config.ui_url), DEFAULT_UI_URL, "{bad}");
            assert!(!l.warnings.is_empty());
        }
    }

    #[test]
    fn unparseable_file_is_never_rewritten() {
        for text in ["{not json", "[1,2]", ""] {
            let l = parse(Some(text), None);
            assert!(!l.needs_write, "{text}");
            assert_eq!(l.config, Config::default());
            assert_eq!(l.warnings.len(), 1);
        }
    }

    #[test]
    fn env_override_validated() {
        let l = parse(None, Some("http://127.0.0.1:8095"));
        assert_eq!(origin_str(&l.config.ui_url), "http://127.0.0.1:8095");
        let l = parse(None, Some("http://10.0.0.1:8095"));
        assert_eq!(origin_str(&l.config.ui_url), DEFAULT_UI_URL);
        assert_eq!(l.warnings.len(), 1);
    }

    #[test]
    fn repo_root_must_be_absolute() {
        let l = parse(Some(r#"{"repo_root":"relative/path"}"#), None);
        assert_eq!(l.config.repo_root, default_repo_root());
        let l = parse(Some(r#"{"repo_root":"/opt/sd"}"#), None);
        assert_eq!(l.config.repo_root, PathBuf::from("/opt/sd"));
    }

    #[test]
    fn frame_hosts_are_sanitized() {
        let l = parse(
            Some(r#"{"frame_hosts":[".TradingView.com","bad host","x","ok-host.io",5]}"#),
            None,
        );
        assert_eq!(
            l.config.frame_hosts,
            vec!["tradingview.com".to_string(), "ok-host.io".to_string()]
        );
    }

    #[test]
    fn grace_prefixes_and_listener_keys() {
        let l = parse(
            Some(
                r#"{"startup_grace_secs":60,"trusted_python_prefixes":["/Users/x/.pyenv/versions/3.13.1/bin"],"verify_ui_listener":false}"#,
            ),
            None,
        );
        assert_eq!(l.config.startup_grace_secs, 60);
        assert_eq!(
            l.config.trusted_python_prefixes,
            vec![PathBuf::from("/Users/x/.pyenv/versions/3.13.1/bin")]
        );
        assert!(!l.config.verify_ui_listener);
        let l = parse(
            Some(
                r#"{"startup_grace_secs":99999,"trusted_python_prefixes":["relative/py","/","/a/../b",5,"/ok"],"verify_ui_listener":"no"}"#,
            ),
            None,
        );
        assert_eq!(l.config.startup_grace_secs, DEFAULT_STARTUP_GRACE_SECS);
        assert_eq!(l.config.trusted_python_prefixes, vec![PathBuf::from("/ok")]);
        assert!(l.config.verify_ui_listener);
        assert_eq!(l.warnings.len(), 6, "{:?}", l.warnings);
        // the round-1 key is ignored: never resolved, never stat'ed (it pointed under ~/Desktop)
        let l = parse(
            Some(r#"{"stack_python":"/Users/sudheer/Desktop/jupyter_env/bin/python"}"#),
            None,
        );
        assert!(
            l.warnings.iter().any(|w| w.contains("stack_python is no longer used")),
            "{:?}",
            l.warnings
        );
        assert!(parse(Some(r#"{"stack_python":null}"#), None).warnings.is_empty());
        // the env override wins and is validated
        let l = parse_with(
            None,
            EnvOverrides {
                ui_url: None,
                startup_grace: Some("25"),
            },
        );
        assert_eq!(l.config.startup_grace_secs, 25);
        let l = parse_with(
            None,
            EnvOverrides {
                ui_url: None,
                startup_grace: Some("-1"),
            },
        );
        assert_eq!(l.config.startup_grace_secs, DEFAULT_STARTUP_GRACE_SECS);
        assert_eq!(l.warnings.len(), 1);
        // a full default file round-trips with the new key, and a round-1 file gets it added
        let text = to_json(&Config::default());
        assert!(text.contains("\"trusted_python_prefixes\": []"), "{text}");
        assert!(!text.contains("stack_python"));
        assert!(!parse(Some(&text), None).needs_write);
        let round1 = text.replace("\"trusted_python_prefixes\": [],", "\"stack_python\": null,");
        assert!(round1.contains("stack_python"));
        assert!(parse(Some(&round1), None).needs_write);
    }

    #[test]
    fn load_creates_file_and_respects_write_flag() {
        let dir = tempfile::tempdir().unwrap();
        let l = load(dir.path(), false);
        assert!(l.needs_write);
        assert!(
            !dir.path().join(CONFIG_FILE).exists(),
            "write=false must not touch disk"
        );
        let _ = load(dir.path(), true);
        let text = fs::read_to_string(dir.path().join(CONFIG_FILE)).unwrap();
        let v: Value = serde_json::from_str(&text).unwrap();
        assert_eq!(v["ui_url"], "http://127.0.0.1:8010");
        assert_eq!(v["devtools"], false);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = fs::metadata(dir.path().join(CONFIG_FILE)).unwrap().permissions().mode() & 0o777;
            assert_eq!(mode, 0o600);
        }
    }
}
