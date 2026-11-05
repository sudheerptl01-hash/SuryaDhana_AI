//! Launch at Login: the shell's own LaunchAgent, `~/Library/LaunchAgents/SuryaDhana.plist` (label
//! `SuryaDhana`, the same file and label tauri-plugin-autostart wrote, so existing installs keep working).
//!
//! What the plist adds over the plugin's (C2-reliability-ops-12, C1-desktop-native-09/13):
//! * `KeepAlive {SuccessfulExit: false}` + `ThrottleInterval`: launchd relaunches the app when it crashes
//!   (a signal or a non-zero exit) but not after ⌘Q / Quit (exit 0). The crash-loop breaker in
//!   `crash.rs` exits 0 after repeated crashes, which ends the respawns.
//! * `AssociatedBundleIdentifiers` = the app's bundle id and `ProcessType` = Interactive: System Settings ›
//!   Login Items shows "SuryaDhana" with its icon, and launchd does not throttle a GUI app.
//! * `StandardErrorPath` in the app's log folder: a panic message survives even before logging is up.
//!
//! The toggle reflects reality: ON = the plist exists AND Background Task Management does not report
//! it as switched off ("Allow in the Background"). When it is switched off there, the menu says so and
//! opens that System Settings pane instead of rewriting a plist launchd would ignore.
//!
//! First run: enabled once, recorded in `<config>/.autostart-initialized` (not in state.json, which the
//! "reset window layout" recipe deletes), so it never turns itself back on after the owner switched it off.
//!
//! **Takes effect now** (wave 2, completeness-03): launchd reads a plist only when it loads it, so after the
//! file is written or removed the shell reconciles launchd ([`launchd_plan`]): ON = `launchctl bootout` of
//! the old job (no-op when not loaded) + `launchctl bootstrap` of the new file (its RunAtLoad start finds this
//! instance running and exits quietly, see instance.rs `LOGIN`); OFF = `bootout`. Never from inside the job
//! itself: when THIS instance is the login job's process (launchd sets `XPC_SERVICE_NAME` to the label),
//! booting the job out would quit the app, so the change is left for the next login and the menu says so.
//! `scripts/build_desktop.sh --install` runs the new binary with `--login-item-sync` (rewrite the entry for
//! the installed copy, unload the stale job) and `--relaunch` starts the app THROUGH launchd, so the crash
//! relaunch is in force at once. Only the account's real home drives launchd: a drill's temp HOME uses the
//! same per-user launchd domain, so it never touches it (it may inject a recording `launchctl` that lives
//! inside its own HOME: `SURYADHANA_LAUNCHCTL`).

use std::fs;
use std::path::{Path, PathBuf};

use crate::config::write_atomic_mode;

/// launchd label and plist file stem (= tauri.conf.json productName, as the plugin used).
pub const LABEL: &str = "SuryaDhana";
/// Argument the login job passes (the boot page's start-up grace keys on it).
pub const AUTOSTART_ARG: &str = "--autostart";
/// Seconds launchd waits before relaunching a crashed app.
pub const THROTTLE_SECS: u32 = 20;
/// First-run marker file in the app config dir.
pub const FIRST_RUN_MARKER: &str = ".autostart-initialized";

/// `<home>/Library/LaunchAgents/SuryaDhana.plist`.
pub fn plist_path(home: &Path) -> PathBuf {
    home.join("Library/LaunchAgents").join(format!("{LABEL}.plist"))
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

/// The plist the shell writes (pure; byte-for-byte stable so an up-to-date file is never rewritten).
pub fn plist_xml(program: &Path, stderr_log: &Path, bundle_id: &str) -> String {
    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- SuryaDhana.app Launch at Login (written by the app; toggle: SuryaDhana > Launch at Login).
     KeepAlive/SuccessfulExit=false: relaunch after a crash, never after Quit. -->
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{label}</string>
  <key>AssociatedBundleIdentifiers</key>
  <array><string>{bundle}</string></array>
  <key>ProgramArguments</key>
  <array><string>{program}</string><string>{arg}</string></array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>ThrottleInterval</key>
  <integer>{throttle}</integer>
  <key>ProcessType</key>
  <string>Interactive</string>
  <key>StandardErrorPath</key>
  <string>{stderr}</string>
</dict>
</plist>
"#,
        label = LABEL,
        bundle = xml_escape(bundle_id),
        program = xml_escape(&program.display().to_string()),
        arg = AUTOSTART_ARG,
        throttle = THROTTLE_SECS,
        stderr = xml_escape(&stderr_log.display().to_string()),
    )
}

/// The program a plist starts (`ProgramArguments[0]`), read with the system `plutil` (bounded: 5 s, R-RUST-07).
pub fn plist_program(plist: &Path) -> Option<PathBuf> {
    let out = crate::exec::run_bounded(
        std::process::Command::new("/usr/bin/plutil")
            .args(["-extract", "ProgramArguments.0", "raw", "-o", "-"])
            .arg(plist),
        std::time::Duration::from_secs(5),
    )
    .ok()
    .filter(|o| o.success())?;
    let s = out.stdout_text();
    (!s.is_empty()).then(|| PathBuf::from(s))
}

/// True for an app inside an Applications folder (`/Applications/…`, `~/Applications/…`).
pub fn is_installed_location(exe: &Path) -> bool {
    exe.components().any(|c| c.as_os_str() == "Applications")
}

/// What to do with an existing Launch-at-Login entry on a normal launch.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Maintenance {
    /// Up to date.
    Keep,
    /// Rewrite it for this program (the old target is gone, or the installed copy takes over from a
    /// build-directory copy).
    Repoint(PathBuf),
    /// Same program, old format (e.g. the plugin's plist without KeepAlive): rewrite in place.
    Upgrade(PathBuf),
}

/// Pure maintenance rule (C1-desktop-native-09):
/// * the target no longer exists (moved, reinstalled elsewhere, deleted build dir) -> repoint here;
/// * the target is a build-directory copy and THIS copy is the installed one -> repoint here (a dev build
///   launched first must not keep starting at login);
/// * an installed target is never replaced by a build-directory copy;
/// * otherwise rewrite only when the text is not what [`plist_xml`] produces for that target.
pub fn maintenance(
    program: Option<&Path>,
    current_exe: &Path,
    current_text: &str,
    expected_for: impl Fn(&Path) -> String,
) -> Maintenance {
    let Some(target) = program else {
        // unreadable / foreign plist: make it ours
        return Maintenance::Repoint(current_exe.to_path_buf());
    };
    if target != current_exe {
        if !target.exists() {
            return Maintenance::Repoint(current_exe.to_path_buf());
        }
        if is_installed_location(current_exe) && !is_installed_location(target) {
            return Maintenance::Repoint(current_exe.to_path_buf());
        }
    }
    if current_text != expected_for(target) {
        Maintenance::Upgrade(target.to_path_buf())
    } else {
        Maintenance::Keep
    }
}

/// First run: enable once? Pure rule over the markers.
/// `marker` = the first-run marker file exists; `legacy` = state.json still carries the old
/// `autostart_initialized: true` (installs from before this marker); `plist_exists` = an entry exists.
pub fn first_run_should_enable(marker: bool, legacy: bool, plist_exists: bool) -> bool {
    !(marker || legacy || plist_exists)
}

/// The Launch-at-Login state the menu shows.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum State {
    Off,
    On,
    /// The plist exists but "Allow in the Background" is off for it: launchd will not start it.
    Blocked,
}

impl State {
    pub fn from_parts(plist_exists: bool, status: crate::macos::LoginItemStatus) -> State {
        match (plist_exists, status) {
            (false, _) => State::Off,
            (true, crate::macos::LoginItemStatus::RequiresApproval) => State::Blocked,
            (true, _) => State::On,
        }
    }

    pub fn checked(self) -> bool {
        self == State::On
    }

    pub fn menu_text(self) -> &'static str {
        match self {
            State::Blocked => "Launch at Login (off in System Settings…)",
            _ => "Launch at Login",
        }
    }
}

/// Outcome of [`LoginAgent::maintain`].
#[derive(Debug)]
pub struct Maintained {
    pub action: Maintenance,
    /// The program the entry pointed at before.
    pub previous: Option<PathBuf>,
    pub result: std::io::Result<()>,
}

/// Launch-at-Login entry of one home directory.
#[derive(Debug, Clone)]
pub struct LoginAgent {
    pub plist: PathBuf,
    pub stderr_log: PathBuf,
}

impl LoginAgent {
    pub fn new(home: &Path, log_dir: &Path) -> Self {
        Self {
            plist: plist_path(home),
            stderr_log: log_dir.join("launchd-stderr.log"),
        }
    }

    pub fn exists(&self) -> bool {
        fs::symlink_metadata(&self.plist).is_ok()
    }

    pub fn state(&self) -> State {
        let exists = self.exists();
        let status = if exists {
            // bounded (R-RUST-07): a wedged backgroundtaskmanagementd must never freeze the main thread
            crate::macos::login_item_status_bounded(&self.plist, std::time::Duration::from_secs(2))
        } else {
            crate::macos::LoginItemStatus::NotFound
        };
        State::from_parts(exists, status)
    }

    /// Write the entry for `program` (atomic, 0644 like every LaunchAgent).
    pub fn write(&self, program: &Path) -> std::io::Result<()> {
        if let Some(dir) = self.stderr_log.parent() {
            fs::create_dir_all(dir)?;
        }
        write_atomic_mode(
            &self.plist,
            &plist_xml(program, &self.stderr_log, crate::macos::BUNDLE_ID),
            0o644,
        )
    }

    pub fn remove(&self) -> std::io::Result<()> {
        match fs::remove_file(&self.plist) {
            Err(e) if e.kind() != std::io::ErrorKind::NotFound => Err(e),
            _ => Ok(()),
        }
    }

    /// Normal launch: repoint / upgrade an existing entry (never creates one).
    pub fn maintain(&self, current_exe: &Path) -> Option<Maintained> {
        if !self.exists() {
            return None;
        }
        let text = fs::read_to_string(&self.plist).unwrap_or_default();
        let previous = plist_program(&self.plist);
        let action = maintenance(previous.as_deref(), current_exe, &text, |p| {
            plist_xml(p, &self.stderr_log, crate::macos::BUNDLE_ID)
        });
        let result = match &action {
            Maintenance::Keep => Ok(()),
            Maintenance::Repoint(p) | Maintenance::Upgrade(p) => self.write(p),
        };
        Some(Maintained {
            action,
            previous,
            result,
        })
    }

    /// Keep `launchd-stderr.log` bounded (it only grows on panics / stderr noise): rotate at 5 MB.
    pub fn rotate_stderr_log(&self) {
        if fs::metadata(&self.stderr_log)
            .map(|m| m.len() > 5 * 1024 * 1024)
            .unwrap_or(false)
        {
            let _ = fs::rename(&self.stderr_log, self.stderr_log.with_extension("log.1"));
        }
    }
}

// ---------------------------------------------------------------------------------------------
// launchd reconciliation (completeness-03)
// ---------------------------------------------------------------------------------------------

/// True when this process was started by launchd as the Launch-at-Login job (`XPC_SERVICE_NAME` = label).
pub fn under_login_job(xpc_service_name: Option<&str>) -> bool {
    xpc_service_name.map(|n| n == LABEL).unwrap_or(false)
}

/// What to tell launchd after the entry changed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LaunchdPlan {
    /// `bootout` (benign when not loaded) then `bootstrap` the plist: the loaded job matches the file now.
    Reload,
    /// `bootout`: the file was removed; the job is unloaded now.
    Unload,
    /// This instance IS the job's process: reloading would quit the app. launchd reads the file at the next
    /// login (the string is what the menu says).
    Defer(&'static str),
    /// launchd is not touched (the string says why: self-test, debug build, a drill's temp HOME).
    Skip(&'static str),
}

/// Pure plan: `plist_exists` = the entry is on after the change; `under_job` = see [`under_login_job`];
/// `tool` = Err(why) when launchd must not be touched at all.
pub fn launchd_plan(plist_exists: bool, under_job: bool, tool: Result<(), &'static str>) -> LaunchdPlan {
    if let Err(why) = tool {
        return LaunchdPlan::Skip(why);
    }
    match (plist_exists, under_job) {
        (true, false) => LaunchdPlan::Reload,
        (false, false) => LaunchdPlan::Unload,
        (false, true) => LaunchdPlan::Defer("Launch at Login (off from the next login)"),
        (true, true) => LaunchdPlan::Defer("Launch at Login (updated: applies at the next login)"),
    }
}

/// The `launchctl` argument lists for a plan (pure).
pub fn launchctl_calls(plan: &LaunchdPlan, uid: u32, plist: &Path) -> Vec<Vec<String>> {
    let job = format!("gui/{uid}/{LABEL}");
    match plan {
        LaunchdPlan::Reload => vec![
            vec!["bootout".into(), job],
            vec!["bootstrap".into(), format!("gui/{uid}"), plist.display().to_string()],
        ],
        LaunchdPlan::Unload => vec![vec!["bootout".into(), job]],
        LaunchdPlan::Defer(_) | LaunchdPlan::Skip(_) => vec![],
    }
}

/// `bootout` of a job that is not loaded (3 = ESRCH "No such process", 113 "Could not find service") and
/// `bootstrap` of one that already is (5 / 17 / "already") are not failures.
pub fn benign_launchctl(args: &[String], code: Option<i32>, stderr: &str) -> bool {
    let s = stderr.to_ascii_lowercase();
    match args.first().map(String::as_str) {
        Some("bootout") => {
            matches!(code, Some(3) | Some(113)) || s.contains("no such process") || s.contains("could not find")
        }
        Some("bootstrap") => matches!(code, Some(5) | Some(17)) || s.contains("already"),
        _ => false,
    }
}

/// Which `launchctl` may be run for `home`: the system one for the account's real home; for any other HOME
/// (a drill) only a program that lives INSIDE that HOME and was named in `SURYADHANA_LAUNCHCTL` (a recorder),
/// never the real one (same launchd domain as the owner's app).
pub fn launchctl_tool(
    home: &Path,
    account_home: Option<&Path>,
    injected: Option<&Path>,
) -> Result<PathBuf, &'static str> {
    if account_home == Some(home) {
        return Ok(PathBuf::from("/bin/launchctl"));
    }
    match injected {
        Some(p)
            if p.is_absolute()
                && p.starts_with(home)
                && !p.components().any(|c| matches!(c, std::path::Component::ParentDir)) =>
        {
            Ok(p.to_path_buf())
        }
        _ => Err("this HOME is not the account's home (a drill)"),
    }
}

/// Execute a plan with `tool` (bounded; each call ≤ 5 s). Returns the log lines (what ran, what failed).
pub fn run_launchd(tool: &Path, plan: &LaunchdPlan, uid: u32, plist: &Path) -> Result<Vec<String>, String> {
    let mut said = vec![];
    for args in launchctl_calls(plan, uid, plist) {
        let out = crate::exec::run_bounded(
            std::process::Command::new(tool).args(&args),
            std::time::Duration::from_secs(5),
        )
        .map_err(|e| format!("{}: {e}", tool.display()))?;
        if out.timed_out() {
            return Err(format!("launchctl {} timed out", args.join(" ")));
        }
        if !out.success() && !benign_launchctl(&args, out.code(), &out.stderr_text()) {
            return Err(format!("launchctl {} failed: {}", args.join(" "), out.stderr_text()));
        }
        said.push(format!(
            "launchctl {}{}",
            args.join(" "),
            if out.success() { "" } else { " (nothing to do)" }
        ));
    }
    Ok(said)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::macos::LoginItemStatus;

    #[test]
    fn launchd_reconcile_plans_never_boot_out_the_running_job() {
        let ok: Result<(), &str> = Ok(());
        // not the job's process: ON reloads (bootout + bootstrap), OFF unloads
        assert_eq!(launchd_plan(true, false, ok), LaunchdPlan::Reload);
        assert_eq!(launchd_plan(false, false, ok), LaunchdPlan::Unload);
        // the job's own process: never bootout (it would quit the app): deferred to the next login
        assert!(matches!(launchd_plan(false, true, ok), LaunchdPlan::Defer(t) if t.contains("next login")));
        assert!(matches!(launchd_plan(true, true, ok), LaunchdPlan::Defer(_)));
        for p in [launchd_plan(false, true, ok), launchd_plan(true, true, ok)] {
            assert!(launchctl_calls(&p, 501, Path::new("/x.plist")).is_empty(), "{p:?}");
        }
        // isolated HOME without a recorder: nothing at all
        assert!(matches!(
            launchd_plan(true, false, Err("isolated")),
            LaunchdPlan::Skip(_)
        ));
        let plist = Path::new("/Users/u/Library/LaunchAgents/SuryaDhana.plist");
        assert_eq!(
            launchctl_calls(&LaunchdPlan::Reload, 501, plist),
            vec![
                vec!["bootout".to_string(), "gui/501/SuryaDhana".into()],
                vec!["bootstrap".to_string(), "gui/501".into(), plist.display().to_string()],
            ]
        );
        assert_eq!(
            launchctl_calls(&LaunchdPlan::Unload, 501, plist),
            vec![vec!["bootout".to_string(), "gui/501/SuryaDhana".into()]]
        );
        // only the app's own label is ever named (never the watchdog or anything else)
        for p in [LaunchdPlan::Reload, LaunchdPlan::Unload] {
            for c in launchctl_calls(&p, 501, plist) {
                assert!(
                    c.iter().all(|a| !a.contains("watchdog") && !a.contains("awake")),
                    "{c:?}"
                );
            }
        }
    }

    #[test]
    fn under_job_detection_and_benign_outcomes() {
        assert!(under_login_job(Some("SuryaDhana")));
        for other in [
            None,
            Some("0"),
            Some("application.ai.suryadhana.terminal.1234.5678"),
            Some("SuryaDhana2"),
        ] {
            assert!(!under_login_job(other), "{other:?}");
        }
        let bo = vec!["bootout".to_string()];
        let bs = vec!["bootstrap".to_string()];
        assert!(benign_launchctl(&bo, Some(3), "Boot-out failed: 3: No such process"));
        assert!(benign_launchctl(&bo, Some(113), ""));
        assert!(!benign_launchctl(&bo, Some(1), "Operation not permitted"));
        assert!(benign_launchctl(
            &bs,
            Some(5),
            "Bootstrap failed: 5: Input/output error"
        ));
        assert!(!benign_launchctl(&bs, Some(1), "nope"));
    }

    #[test]
    fn launchctl_tool_is_the_system_one_only_for_the_real_home() {
        let real = Path::new("/Users/sudheer");
        let drill = Path::new("/var/folders/x/T/suryadhana-drill.ab");
        assert_eq!(
            launchctl_tool(real, Some(real), None),
            Ok(PathBuf::from("/bin/launchctl"))
        );
        // a drill HOME never reaches the real launchd domain
        assert!(launchctl_tool(drill, Some(real), None).is_err());
        assert!(launchctl_tool(drill, Some(real), Some(Path::new("/bin/launchctl"))).is_err());
        assert!(launchctl_tool(
            drill,
            Some(real),
            Some(Path::new("/var/folders/x/T/suryadhana-drill.ab/../evil"))
        )
        .is_err());
        let rec = drill.join("bin/launchctl-recorder");
        assert_eq!(launchctl_tool(drill, Some(real), Some(&rec)), Ok(rec.clone()));
        assert!(
            launchctl_tool(real, None, None).is_err(),
            "unknown account home: not touched"
        );
    }

    #[test]
    fn run_launchd_with_a_recorder() {
        let dir = tempfile::tempdir().unwrap();
        let log = dir.path().join("calls.log");
        let rec = dir.path().join("launchctl");
        std::fs::write(
            &rec,
            format!(
                "#!/bin/sh\necho \"$@\" >> '{}'\ncase \"$1\" in bootout) echo 'Boot-out failed: 3: No such process' >&2; exit 3;; esac\nexit 0\n",
                log.display()
            ),
        )
        .unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&rec, std::fs::Permissions::from_mode(0o755)).unwrap();
        let plist = dir.path().join("SuryaDhana.plist");
        let said = run_launchd(&rec, &LaunchdPlan::Reload, 501, &plist).unwrap();
        assert_eq!(said.len(), 2, "{said:?}");
        assert!(
            said[0].contains("nothing to do"),
            "bootout of a job that is not loaded is benign"
        );
        let calls = std::fs::read_to_string(&log).unwrap();
        assert_eq!(
            calls,
            format!("bootout gui/501/SuryaDhana\nbootstrap gui/501 {}\n", plist.display())
        );
        assert!(run_launchd(&rec, &LaunchdPlan::Defer("x"), 501, &plist)
            .unwrap()
            .is_empty());
    }

    #[test]
    fn plist_has_keepalive_bundle_id_and_escapes() {
        let x = plist_xml(
            Path::new("/Applications/Surya & Dhana.app/Contents/MacOS/SuryaDhana"),
            Path::new("/Users/u/Library/Logs/ai.suryadhana.terminal/launchd-stderr.log"),
            "ai.suryadhana.terminal",
        );
        assert!(x.contains("<key>KeepAlive</key>"));
        assert!(x.contains("<key>SuccessfulExit</key>\n    <false/>"));
        assert!(x.contains("<array><string>ai.suryadhana.terminal</string></array>"));
        assert!(x.contains("<string>Interactive</string>"));
        assert!(x.contains("Surya &amp; Dhana.app"));
        assert!(x.contains("<string>--autostart</string>"));
        assert!(x.contains(&format!("<integer>{THROTTLE_SECS}</integer>")));
        // well-formed for plutil
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("SuryaDhana.plist");
        fs::write(&p, &x).unwrap();
        let ok = std::process::Command::new("/usr/bin/plutil")
            .arg("-lint")
            .arg(&p)
            .status()
            .unwrap();
        assert!(ok.success());
        assert_eq!(
            plist_program(&p),
            Some(PathBuf::from(
                "/Applications/Surya & Dhana.app/Contents/MacOS/SuryaDhana"
            ))
        );
    }

    #[test]
    fn maintenance_rules() {
        let dir = tempfile::tempdir().unwrap();
        let build = dir
            .path()
            .join("target/release/bundle/macos/SuryaDhana.app/Contents/MacOS/SuryaDhana");
        let installed = dir.path().join("Applications/SuryaDhana.app/Contents/MacOS/SuryaDhana");
        for p in [&build, &installed] {
            fs::create_dir_all(p.parent().unwrap()).unwrap();
            fs::write(p, b"").unwrap();
        }
        let expected = |p: &Path| format!("xml for {}", p.display());
        // up to date
        assert_eq!(
            maintenance(Some(&installed), &installed, &expected(&installed), expected),
            Maintenance::Keep
        );
        // the plugin-era plist (no KeepAlive) for the same program: upgrade in place
        assert_eq!(
            maintenance(Some(&installed), &installed, "old plugin xml", expected),
            Maintenance::Upgrade(installed.clone())
        );
        // the target is gone: repoint here
        let gone = dir.path().join("Old.app/Contents/MacOS/SuryaDhana");
        assert_eq!(
            maintenance(Some(&gone), &build, "x", expected),
            Maintenance::Repoint(build.clone())
        );
        // a build-dir copy registered first, then the installed copy runs: the installed one takes over
        assert_eq!(
            maintenance(Some(&build), &installed, &expected(&build), expected),
            Maintenance::Repoint(installed.clone())
        );
        // a build-dir copy never steals the entry from the installed copy (only upgrades its format)
        assert_eq!(
            maintenance(Some(&installed), &build, &expected(&installed), expected),
            Maintenance::Keep
        );
        assert_eq!(
            maintenance(Some(&installed), &build, "old", expected),
            Maintenance::Upgrade(installed.clone())
        );
        // unreadable program: make it ours
        assert_eq!(
            maintenance(None, &build, "", expected),
            Maintenance::Repoint(build.clone())
        );
    }

    #[test]
    fn first_run_enables_only_once() {
        assert!(first_run_should_enable(false, false, false));
        // the owner switched it off, then deleted state.json (README reset recipe): stays off
        assert!(!first_run_should_enable(true, false, false));
        // an install from before the marker existed
        assert!(!first_run_should_enable(false, true, false));
        assert!(!first_run_should_enable(false, false, true));
    }

    #[test]
    fn state_reflects_background_items() {
        assert_eq!(State::from_parts(false, LoginItemStatus::Enabled), State::Off);
        assert_eq!(State::from_parts(true, LoginItemStatus::Enabled), State::On);
        assert_eq!(State::from_parts(true, LoginItemStatus::NotRegistered), State::On);
        assert_eq!(
            State::from_parts(true, LoginItemStatus::RequiresApproval),
            State::Blocked
        );
        assert!(!State::Blocked.checked());
        assert!(State::Blocked.menu_text().contains("System Settings"));
        assert!(State::On.checked());
    }

    #[test]
    fn agent_write_maintain_remove() {
        let home = tempfile::tempdir().unwrap();
        let logs = home.path().join("Library/Logs/ai.suryadhana.terminal");
        let agent = LoginAgent::new(home.path(), &logs);
        assert!(!agent.exists());
        assert!(agent.maintain(Path::new("/x")).is_none(), "never creates an entry");
        let exe = home
            .path()
            .join("Applications/SuryaDhana.app/Contents/MacOS/SuryaDhana");
        fs::create_dir_all(exe.parent().unwrap()).unwrap();
        fs::write(&exe, b"").unwrap();
        agent.write(&exe).unwrap();
        assert!(agent.exists() && logs.is_dir());
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(fs::metadata(&agent.plist).unwrap().permissions().mode() & 0o777, 0o644);
        assert_eq!(agent.maintain(&exe).unwrap().action, Maintenance::Keep);
        // the plugin-era file is upgraded
        fs::write(
            &agent.plist,
            format!(
                "<plist><dict><key>ProgramArguments</key><array><string>{}</string></array></dict></plist>",
                exe.display()
            ),
        )
        .unwrap();
        let m = agent.maintain(&exe).unwrap();
        assert!(matches!(m.action, Maintenance::Upgrade(_)) && m.result.is_ok(), "{m:?}");
        assert_eq!(m.previous.as_deref(), Some(exe.as_path()));
        assert!(fs::read_to_string(&agent.plist).unwrap().contains("KeepAlive"));
        agent.remove().unwrap();
        agent.remove().unwrap(); // idempotent
        assert!(!agent.exists());
    }
}
