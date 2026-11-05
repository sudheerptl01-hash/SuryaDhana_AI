//! Start / stop the local stack from the menu bar or the boot page, and read what the stack is doing.
//!
//! The app NEVER runs the stack's Python itself (TCC: the interpreter lives under ~/Desktop, which the
//! launchd watchdog already has permission for; a process started by the app would run under the app's
//! own, per-build privacy grant). It only:
//! * **Start**: removes `<repo>/.pids/paused/{data-service,ui-api,master-controller}` (the "stopped on
//!   purpose" markers `start-local.sh stop` writes) and asks the watchdog LaunchAgent to run now with
//!   `launchctl kickstart gui/<uid>/com.suryadhana.watchdog` — WITHOUT `-k`, so a watchdog run that is
//!   already starting the stack (every login) is never killed (C2-reliability-ops-03): kickstart of a
//!   running job is a no-op, and a run in progress is detected first and left alone. When the agent is not
//!   loaded but its plist is installed, it is loaded with `launchctl bootstrap`; when it is not installed,
//!   Start refuses with the install command instead of spawning `start-local.sh` (C2-reliability-ops-13).
//! * **Stop** (guarded: native confirm dialog in the caller; refused inside the IST freeze windows):
//!   `<repo>/start-local.sh stop`, detached, output appended to `<repo>/.logs/desktop-stack.log`. Stopping
//!   runs no Python: it signals the services and marks each one paused so the watchdog leaves them down.
//!
//! Command construction is pure ([`start_plan`], [`stop_plan`]) and unit-tested; tests never execute it.

use std::fs::OpenOptions;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, SystemTime};

use serde::Serialize;

use crate::policy::{freeze_window_at, FreezeWindow};

/// The watchdog LaunchAgent label (installed by scripts/install_launch_agents.sh).
pub const WATCHDOG_LABEL: &str = "com.suryadhana.watchdog";
/// Services whose paused markers Start clears (the 3-process CORE after the desktop switchover).
pub const CORE_SERVICES: [&str; 3] = ["data-service", "ui-api", "master-controller"];
/// PATH for detached children (launchd/app PATH is minimal; mirrors scripts/stack_watchdog.sh).
pub const CHILD_PATH: &str = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
/// A watchdog lock older than this is from a killed run (stack_watchdog.sh takes it over after 20 min).
pub const WATCHDOG_LOCK_STALE: Duration = Duration::from_secs(20 * 60);
/// A "preflight FAILED" line is current when watchdog.log changed within this long.
pub const PREFLIGHT_FRESH: Duration = Duration::from_secs(15 * 60);

/// One step of a plan. Every step carries the plain-language line the boot page / notification shows.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Step {
    /// Delete these paused markers if present.
    ClearMarkers(Vec<PathBuf>),
    /// Run and wait (short-lived), e.g. `launchctl kickstart`.
    Run {
        program: String,
        args: Vec<String>,
        says: String,
    },
    /// Spawn detached in its own process group, cwd = repo, stdout+stderr appended to `log`.
    Spawn {
        program: String,
        args: Vec<String>,
        cwd: PathBuf,
        log: PathBuf,
        says: String,
    },
    /// Nothing to run; just say this.
    Say(String),
}

/// Paths derived from the repo root.
#[derive(Debug, Clone)]
pub struct StackPaths {
    pub repo: PathBuf,
    pub script: PathBuf,
    pub paused_dir: PathBuf,
    pub log: PathBuf,
    pub watchdog_lock: PathBuf,
    pub watchdog_log: PathBuf,
}

impl StackPaths {
    pub fn new(repo: &Path) -> Self {
        Self {
            repo: repo.to_path_buf(),
            script: repo.join("start-local.sh"),
            paused_dir: repo.join(".pids").join("paused"),
            log: repo.join(".logs").join("desktop-stack.log"),
            watchdog_lock: repo.join(".pids").join("watchdog").join("lock"),
            watchdog_log: repo.join(".logs").join("watchdog.log"),
        }
    }

    /// The repo looks like the SuryaDhana repo (start-local.sh is a regular file inside it).
    pub fn validate(&self) -> Result<(), String> {
        if !self.repo.is_absolute() {
            return Err("repo_root is not an absolute path".into());
        }
        match std::fs::symlink_metadata(&self.script) {
            Ok(m) if m.file_type().is_file() => Ok(()),
            Ok(_) => Err("start-local.sh is not a regular file".into()),
            Err(_) => Err(format!("start-local.sh not found in {}", self.repo.display())),
        }
    }
}

/// `~/Library/LaunchAgents/com.suryadhana.watchdog.plist` for `home`.
pub fn watchdog_plist(home: &Path) -> PathBuf {
    home.join("Library/LaunchAgents")
        .join(format!("{WATCHDOG_LABEL}.plist"))
}

/// What the watchdog agent is doing, as far as Start needs to know.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Watchdog {
    /// launchd has the job (`launchctl print gui/<uid>/com.suryadhana.watchdog` succeeds).
    pub loaded: bool,
    /// A watchdog run is in progress (its lock exists and is fresh).
    pub running: bool,
    /// The agent's plist is installed in ~/Library/LaunchAgents.
    pub plist_installed: bool,
}

/// Plan for Start Stack.
pub fn start_plan(paths: &StackPaths, uid: u32, wd: Watchdog, plist: &Path) -> Result<Vec<Step>, String> {
    let target = format!("gui/{uid}/{WATCHDOG_LABEL}");
    let mut steps = vec![Step::ClearMarkers(
        CORE_SERVICES.iter().map(|s| paths.paused_dir.join(s)).collect(),
    )];
    if wd.loaded && wd.running {
        steps.push(Step::Say(
            "The watchdog is already starting the stack; it was left to finish (usually 1–4 min).".into(),
        ));
    } else if wd.loaded {
        steps.push(Step::Run {
            program: "/bin/launchctl".into(),
            args: vec!["kickstart".into(), target],
            says: "Asked the watchdog to start every stopped core service now (usually 1–4 min).".into(),
        });
    } else if wd.plist_installed {
        steps.push(Step::Run {
            program: "/bin/launchctl".into(),
            args: vec!["bootstrap".into(), format!("gui/{uid}"), plist.display().to_string()],
            says: "Loaded the watchdog LaunchAgent.".into(),
        });
        steps.push(Step::Run {
            program: "/bin/launchctl".into(),
            args: vec!["kickstart".into(), target],
            says: "Asked the watchdog to start every stopped core service now (usually 1–4 min).".into(),
        });
    } else {
        return Err(format!(
            "The watchdog LaunchAgent is not installed, so the app cannot start the stack. In Terminal: \
             cd {} && scripts/install_launch_agents.sh install",
            paths.repo.display()
        ));
    }
    Ok(steps)
}

/// Plan for Stop Stack (the caller has already confirmed and checked the freeze guard).
pub fn stop_plan(paths: &StackPaths) -> Vec<Step> {
    vec![Step::Spawn {
        program: "/bin/bash".into(),
        args: vec![paths.script.display().to_string(), "stop".into()],
        cwd: paths.repo.clone(),
        log: paths.log.clone(),
        says: "Stopping every service and marking it paused (the watchdog leaves paused services down).".into(),
    }]
}

/// Refuse stopping inside an IST freeze window.
pub fn stop_guard(now: time::OffsetDateTime) -> Result<(), FreezeWindow> {
    match freeze_window_at(now) {
        Some(w) => Err(w),
        None => Ok(()),
    }
}

/// Current user id (for the `gui/<uid>` launchd domain).
pub fn current_uid() -> u32 {
    crate::macos::uid()
}

/// Time limit for one `launchctl` call (a hung launchctl must never stall the stack loop or a menu action).
pub const LAUNCHCTL_TIMEOUT: Duration = Duration::from_secs(5);

/// Is the watchdog agent loaded in this user's GUI domain? (bounded: a timeout counts as "not known to be
/// loaded", which only affects the remedy text, never what runs)
pub fn watchdog_loaded(uid: u32) -> bool {
    crate::exec::run_bounded(
        Command::new("/bin/launchctl").args(["print", &format!("gui/{uid}/{WATCHDOG_LABEL}")]),
        LAUNCHCTL_TIMEOUT,
    )
    .map(|b| b.success())
    .unwrap_or(false)
}

/// `launchctl kickstart` of a job that is already running (or racing to run) is not a failure.
pub fn benign_launchctl_error(args: &[String], stderr: &str, code: Option<i32>) -> bool {
    let s = stderr.to_ascii_lowercase();
    match args.first().map(String::as_str) {
        Some("kickstart") => s.contains("already") || code == Some(37),
        // bootstrap of an already-loaded job (EIO 5 / "service already loaded") means it is loaded
        Some("bootstrap") => s.contains("already") || code == Some(5) || code == Some(17),
        _ => false,
    }
}

/// Execute a plan; returns the plain-language summary. Markers outside `<repo>/.pids/paused` are
/// refused (defence in depth).
pub fn execute(paths: &StackPaths, steps: &[Step]) -> Result<String, String> {
    let mut said = Vec::new();
    for step in steps {
        match step {
            Step::ClearMarkers(markers) => {
                let mut cleared = vec![];
                for p in markers {
                    if p.parent() != Some(paths.paused_dir.as_path()) {
                        return Err(format!("refusing to remove {}", p.display()));
                    }
                    match std::fs::remove_file(p) {
                        Ok(()) => cleared.push(p.file_name().unwrap_or_default().to_string_lossy().to_string()),
                        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                        Err(e) => return Err(format!("could not clear {}: {e}", p.display())),
                    }
                }
                if !cleared.is_empty() {
                    said.push(format!(
                        "Cleared the stopped-on-purpose mark of {}.",
                        cleared.join(", ")
                    ));
                }
            }
            Step::Run { program, args, says } => {
                let out = crate::exec::run_bounded(Command::new(program).args(args), LAUNCHCTL_TIMEOUT)
                    .map_err(|e| format!("{program}: {e}"))?;
                if out.timed_out() {
                    log::warn!("[stack] {program} {} timed out", args.join(" "));
                    return Err(format!(
                        "launchd did not answer within {} s. Open the stack logs, or run ./start-local.sh start in Terminal.",
                        LAUNCHCTL_TIMEOUT.as_secs()
                    ));
                }
                let stderr = out.stderr_text();
                if !out.success() && !benign_launchctl_error(args, &stderr, out.code()) {
                    log::warn!("[stack] {program} {} failed: {stderr}", args.join(" "));
                    return Err(format!(
                        "launchd refused ({}). Open the stack logs, or run ./start-local.sh start in Terminal.",
                        if stderr.is_empty() {
                            "no message"
                        } else {
                            stderr.as_str()
                        }
                    ));
                }
                log::info!("[stack] ran {program} {}", args.join(" "));
                said.push(says.clone());
            }
            Step::Spawn {
                program,
                args,
                cwd,
                log,
                says,
            } => {
                if let Some(dir) = log.parent() {
                    std::fs::create_dir_all(dir).map_err(|e| format!("log dir: {e}"))?;
                }
                let f = OpenOptions::new()
                    .create(true)
                    .append(true)
                    .open(log)
                    .map_err(|e| format!("log: {e}"))?;
                let f2 = f.try_clone().map_err(|e| format!("log: {e}"))?;
                let mut cmd = Command::new(program);
                cmd.args(args)
                    .current_dir(cwd)
                    .env("PATH", CHILD_PATH)
                    .env_remove("SURYADHANA_UI_URL")
                    .env_remove("SURYADHANA_SELFTEST_OUT")
                    .stdin(Stdio::null())
                    .stdout(Stdio::from(f))
                    .stderr(Stdio::from(f2));
                #[cfg(unix)]
                {
                    use std::os::unix::process::CommandExt;
                    cmd.process_group(0); // detached from the app's process group: survives app quit
                }
                let child = cmd.spawn().map_err(|e| format!("{program}: {e}"))?;
                ::log::info!(
                    "[stack] started {} (pid {}), log {}",
                    args.join(" "),
                    child.id(),
                    log.display()
                );
                said.push(says.clone());
                // reap in the background so no zombie is left behind
                std::thread::spawn(move || {
                    let mut child = child;
                    let _ = child.wait();
                });
            }
            Step::Say(s) => said.push(s.clone()),
        }
    }
    Ok(said.join(" "))
}

// ---------------------------------------------------------------------------------------------
// Activity probe (read-only file checks; the boot page and notifications use it)
// ---------------------------------------------------------------------------------------------

/// What the stack's own bookkeeping says right now.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Activity {
    /// The watchdog agent is loaded in launchd (None until first probed).
    pub watchdog_loaded: Option<bool>,
    /// Its plist is installed.
    pub watchdog_installed: bool,
    /// A watchdog run is in progress (fresh `.pids/watchdog/lock`).
    pub watchdog_running: bool,
    /// How long that run has been going (the lock's age), for the boot page's elapsed time.
    pub watchdog_run_secs: Option<u64>,
    /// CORE services stopped on purpose (`.pids/paused/<svc>`).
    pub paused: Vec<&'static str>,
    /// The watchdog's last log line says macOS blocked the stack's Python (Desktop-folder privacy).
    pub preflight_failed: bool,
}

impl Activity {
    pub fn is_paused(&self, svc: &str) -> bool {
        self.paused.contains(&svc)
    }

    /// Is the watchdog agent there to act (restart a stopped or hung core service)? Loaded in launchd, or
    /// installed while launchd has not been asked yet; a definite "not loaded" is no.
    pub fn watchdog_active(&self) -> bool {
        self.watchdog_loaded != Some(false) && (self.watchdog_installed || self.watchdog_loaded == Some(true))
    }
}

/// Last non-empty line of a log (reads at most the final 4 KB).
pub fn last_line(path: &Path) -> Option<String> {
    let mut f = std::fs::File::open(path).ok()?;
    let len = f.metadata().ok()?.len();
    f.seek(SeekFrom::Start(len.saturating_sub(4096))).ok()?;
    let mut buf = Vec::new();
    f.read_to_end(&mut buf).ok()?;
    String::from_utf8_lossy(&buf)
        .lines()
        .rev()
        .map(str::trim)
        .find(|l| !l.is_empty())
        .map(str::to_string)
}

/// Age of `path` (mtime) at `now`; a future mtime counts as 0.
fn age(path: &Path, now: SystemTime) -> Option<Duration> {
    std::fs::symlink_metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .map(|t| now.duration_since(t).unwrap_or(Duration::ZERO))
}

fn fresh(path: &Path, max_age: Duration, now: SystemTime) -> bool {
    age(path, now).map(|d| d < max_age).unwrap_or(false)
}

/// Pure (round 4b, SECREL-05): does an owner file's boot field name THIS boot? `scripts/stack_watchdog.sh` writes
/// `echo "$$ $(boot_epoch)"`, and its `boot_epoch()` (`sed -nE 's/.*sec = ([0-9]+).*/\1/p'` on
/// `{ sec = 1792906041, usec = 658471 } …`) is greedy: it matches the LAST `sec = `, so the live watchdog (since
/// 25 Oct 18:12) stamps the boot's MICROSECONDS field (`<pid> 658471`), not its seconds. A corrected script stamps
/// the seconds. Both name this boot; a lock from an earlier boot carries that boot's numbers and matches neither
/// (a reboot repeating the same microseconds value is a one-in-a-million coincidence, and the 20 min age limit
/// and the owner-process check still apply). Round 3 compared with the seconds only, so every real watchdog run
/// read as "not running".
pub fn owner_boot_matches(boot: crate::macos::BootTime, field: u64) -> bool {
    field == boot.sec || field == boot.usec
}

/// Pure (round 3, SECREL-05; round 4b: the real owner format + the owner-command check): is the watchdog lock
/// held by a LIVE run? The same rule as `scripts/stack_watchdog.sh` `lock_is_stale`: the lock directory carries
/// an owner file `<pid> <boot field>` (see [`owner_boot_matches`]); it is held only while it is younger than
/// [`WATCHDOG_LOCK_STALE`], its owner ran in THIS boot and that pid is still the watchdog script (alive, and its
/// command line names `stack_watchdog`: a reused pid is not the watchdog); a lock without an owner file (a run that
/// has just taken it, or a watchdog older than round 3) is held unless it predates this boot. Before round 3 any
/// lock younger than 20 min counted, so a lock left by a power cut showed "the watchdog is starting the stack"
/// (and hid Start) for up to 20 min after the reboot. `owner` = the owner file's text (an unreadable one is ""),
/// `lock_mtime` = epoch seconds, `owner_is_watchdog` = is this pid a live watchdog run.
pub fn watchdog_lock_held(
    age: Duration,
    owner: Option<&str>,
    lock_mtime: Option<u64>,
    boot: Option<crate::macos::BootTime>,
    owner_is_watchdog: impl Fn(i32) -> bool,
) -> bool {
    if age >= WATCHDOG_LOCK_STALE {
        return false;
    }
    match owner {
        Some(text) => {
            let mut it = text.split_whitespace();
            let pid = it.next().and_then(|p| p.parse::<i32>().ok()).filter(|p| *p > 0);
            let owner_boot = it.next().and_then(|b| b.parse::<u64>().ok());
            if let Some(b) = boot {
                if !owner_boot.map(|f| owner_boot_matches(b, f)).unwrap_or(false) {
                    return false;
                }
            }
            pid.map(owner_is_watchdog).unwrap_or(false)
        }
        None => !matches!((lock_mtime, boot), (Some(m), Some(b)) if m < b.sec),
    }
}

/// Is `pid` a live run of the watchdog script? Alive (not a zombie) and its command line names `stack_watchdog`
/// (launchd runs `/bin/bash <repo>/scripts/stack_watchdog.sh`): the watchdog's own `proc_cmd` check.
pub fn is_watchdog_process(pid: i32) -> bool {
    crate::macos::proc_identity(pid).is_some()
        && crate::macos::proc_cmdline(pid)
            .map(|c| c.contains("stack_watchdog"))
            .unwrap_or(false)
}

/// File-based part of the probe (cheap; every few seconds). `watchdog_loaded` is filled by the caller.
pub fn probe_files(paths: &StackPaths, home: &Path, now: SystemTime) -> Activity {
    probe_files_with(paths, home, now, crate::macos::boot_time(), is_watchdog_process)
}

/// [`probe_files`] with the boot time and the owner test given (tests).
pub fn probe_files_with(
    paths: &StackPaths,
    home: &Path,
    now: SystemTime,
    boot: Option<crate::macos::BootTime>,
    owner_is_watchdog: impl Fn(i32) -> bool,
) -> Activity {
    let paused = CORE_SERVICES
        .iter()
        .copied()
        .filter(|s| std::fs::symlink_metadata(paths.paused_dir.join(s)).is_ok())
        .collect();
    let preflight_failed = fresh(&paths.watchdog_log, PREFLIGHT_FRESH, now)
        && last_line(&paths.watchdog_log)
            .map(|l| l.contains("preflight FAILED"))
            .unwrap_or(false);
    let run_age = age(&paths.watchdog_lock, now).filter(|d| {
        let owner_file = paths.watchdog_lock.join("owner");
        let owner = std::fs::symlink_metadata(&owner_file)
            .is_ok()
            .then(|| std::fs::read_to_string(&owner_file).unwrap_or_default());
        let mtime = std::fs::symlink_metadata(&paths.watchdog_lock)
            .and_then(|m| m.modified())
            .ok()
            .and_then(|t| t.duration_since(SystemTime::UNIX_EPOCH).ok())
            .map(|d| d.as_secs());
        watchdog_lock_held(*d, owner.as_deref(), mtime, boot, &owner_is_watchdog)
    });
    Activity {
        watchdog_loaded: None,
        watchdog_installed: watchdog_plist(home).is_file(),
        watchdog_running: run_age.is_some(),
        watchdog_run_secs: run_age.map(|d| d.as_secs()),
        paused,
        preflight_failed,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use time::macros::datetime;

    fn paths() -> StackPaths {
        StackPaths::new(Path::new("/repo"))
    }

    fn wd(loaded: bool, running: bool, plist_installed: bool) -> Watchdog {
        Watchdog {
            loaded,
            running,
            plist_installed,
        }
    }

    const PLIST: &str = "/Users/u/Library/LaunchAgents/com.suryadhana.watchdog.plist";

    #[test]
    fn start_kickstarts_without_k_and_never_kills_a_running_watchdog() {
        let steps = start_plan(&paths(), 501, wd(true, false, true), Path::new(PLIST)).unwrap();
        assert_eq!(
            steps[0],
            Step::ClearMarkers(vec![
                PathBuf::from("/repo/.pids/paused/data-service"),
                PathBuf::from("/repo/.pids/paused/ui-api"),
                PathBuf::from("/repo/.pids/paused/master-controller"),
            ])
        );
        match &steps[1] {
            Step::Run { program, args, .. } => {
                assert_eq!(program, "/bin/launchctl");
                assert_eq!(
                    args,
                    &vec!["kickstart".to_string(), "gui/501/com.suryadhana.watchdog".into()]
                );
            }
            s => panic!("{s:?}"),
        }
        // C2-reliability-ops-03 negative test: no plan ever carries `-k`
        for w in [wd(true, false, true), wd(true, true, true), wd(false, false, true)] {
            for s in start_plan(&paths(), 501, w, Path::new(PLIST)).unwrap() {
                if let Step::Run { args, .. } = s {
                    assert!(!args.iter().any(|a| a == "-k"), "{args:?}");
                }
            }
        }
        // a watchdog run in progress (login) is left alone: nothing is run at all
        let steps = start_plan(&paths(), 501, wd(true, true, true), Path::new(PLIST)).unwrap();
        assert!(matches!(&steps[1], Step::Say(s) if s.contains("already starting")));
        assert_eq!(steps.len(), 2);
    }

    #[test]
    fn start_without_a_loaded_watchdog_uses_launchd_never_start_local() {
        let steps = start_plan(&paths(), 501, wd(false, false, true), Path::new(PLIST)).unwrap();
        assert!(
            matches!(&steps[1], Step::Run { args, .. } if args[0] == "bootstrap" && args[1] == "gui/501" && args[2] == PLIST)
        );
        assert!(matches!(&steps[2], Step::Run { args, .. } if args[0] == "kickstart"));
        // never a spawned start-local.sh / python from the app (C2-reliability-ops-13)
        for s in &steps {
            assert!(!matches!(s, Step::Spawn { .. }), "{s:?}");
        }
        let e = start_plan(&paths(), 501, wd(false, false, false), Path::new(PLIST)).unwrap_err();
        assert!(e.contains("install_launch_agents.sh install"), "{e}");
    }

    #[test]
    fn benign_launchctl_outcomes() {
        let k = vec!["kickstart".to_string()];
        let b = vec!["bootstrap".to_string()];
        assert!(benign_launchctl_error(&k, "service already running", Some(1)));
        assert!(benign_launchctl_error(&k, "", Some(37)));
        assert!(!benign_launchctl_error(&k, "Could not find service", Some(113)));
        assert!(benign_launchctl_error(
            &b,
            "Bootstrap failed: 5: Input/output error",
            Some(5)
        ));
        assert!(!benign_launchctl_error(&["print".into()], "already", Some(1)));
    }

    #[test]
    fn stop_plan_is_start_local_stop() {
        match &stop_plan(&paths())[0] {
            Step::Spawn {
                program,
                args,
                cwd,
                log,
                says,
            } => {
                assert_eq!(program, "/bin/bash");
                assert_eq!(args, &vec!["/repo/start-local.sh".to_string(), "stop".into()]);
                assert_eq!(cwd, &PathBuf::from("/repo"));
                assert_eq!(log, &PathBuf::from("/repo/.logs/desktop-stack.log"));
                assert!(
                    !says.contains("start-local") && !says.contains("/repo"),
                    "plain words: {says}"
                );
            }
            s => panic!("{s:?}"),
        }
    }

    #[test]
    fn stop_refused_in_freeze_windows() {
        assert!(stop_guard(datetime!(2026-10-24 05:40:00 UTC)).is_ok()); // 11:10 IST
        assert!(stop_guard(datetime!(2026-10-24 02:30:00 UTC)).is_err()); // 08:00 IST
        assert!(stop_guard(datetime!(2026-10-24 14:00:00 UTC)).is_err()); // 19:30 IST
        assert!(stop_guard(datetime!(2026-10-24 15:45:00 UTC)).is_ok()); // 21:15 IST
    }

    #[test]
    fn execute_clears_markers_says_plain_words_and_refuses_outside_paused_dir() {
        let dir = tempfile::tempdir().unwrap();
        let p = StackPaths::new(dir.path());
        std::fs::create_dir_all(&p.paused_dir).unwrap();
        std::fs::write(p.paused_dir.join("ui-api"), "x").unwrap();
        let out = execute(
            &p,
            &[
                Step::ClearMarkers(vec![p.paused_dir.join("ui-api"), p.paused_dir.join("data-service")]),
                Step::Say("Done.".into()),
            ],
        )
        .unwrap();
        assert_eq!(out, "Cleared the stopped-on-purpose mark of ui-api. Done.");
        assert!(!p.paused_dir.join("ui-api").exists());
        let victim = dir.path().join("keep.txt");
        std::fs::write(&victim, "x").unwrap();
        assert!(execute(&p, &[Step::ClearMarkers(vec![victim.clone()])]).is_err());
        assert!(victim.exists());
        // nothing raw (no launchctl, no gui/<uid>) in what the user is told
        assert!(!out.contains("launchctl") && !out.contains("gui/"));
    }

    #[test]
    fn validate_requires_start_local_script() {
        let dir = tempfile::tempdir().unwrap();
        let p = StackPaths::new(dir.path());
        assert!(p.validate().is_err());
        std::fs::write(&p.script, "#!/bin/bash\n").unwrap();
        assert!(p.validate().is_ok());
        assert!(StackPaths::new(Path::new("relative")).validate().is_err());
    }

    #[test]
    fn activity_probe_reads_markers_lock_and_preflight() {
        let dir = tempfile::tempdir().unwrap();
        let home = tempfile::tempdir().unwrap();
        let p = StackPaths::new(dir.path());
        let now = SystemTime::now();
        assert_eq!(probe_files(&p, home.path(), now), Activity::default());
        std::fs::create_dir_all(&p.paused_dir).unwrap();
        std::fs::write(p.paused_dir.join("ui-api"), "x").unwrap();
        std::fs::write(p.paused_dir.join("ml-service"), "x").unwrap(); // legacy: not CORE
        std::fs::create_dir_all(&p.watchdog_lock).unwrap();
        std::fs::create_dir_all(p.watchdog_log.parent().unwrap()).unwrap();
        std::fs::write(
            &p.watchdog_log,
            "[x] ok\n[2026-10-22 09:25:17] preflight FAILED: python cannot start from launchd — down: ui-api\n",
        )
        .unwrap();
        std::fs::create_dir_all(home.path().join("Library/LaunchAgents")).unwrap();
        std::fs::write(watchdog_plist(home.path()), "<plist/>").unwrap();
        let a = probe_files(&p, home.path(), now);
        assert_eq!(a.paused, vec!["ui-api"]);
        assert!(a.is_paused("ui-api") && !a.is_paused("data-service"));
        assert!(a.watchdog_running && a.preflight_failed && a.watchdog_installed);
        // wave 2: the run's own age (the lock's mtime), not the app's uptime, is what the boot page shows
        assert!(a.watchdog_run_secs.map(|s| s < 60).unwrap_or(false), "{a:?}");
        let a = probe_files(&p, home.path(), now + Duration::from_secs(95));
        assert!(a.watchdog_running);
        assert!(
            matches!(a.watchdog_run_secs, Some(s) if (90..=100).contains(&s)),
            "{a:?}"
        );
        // a lock / log from long ago is stale
        let later = now + Duration::from_secs(3600);
        let a = probe_files(&p, home.path(), later);
        assert!(!a.watchdog_running && !a.preflight_failed && a.watchdog_run_secs.is_none());
        // a later healthy line clears the preflight state
        std::fs::write(&p.watchdog_log, "[..] preflight FAILED\n[..] ui-api started\n").unwrap();
        assert!(!probe_files(&p, home.path(), SystemTime::now()).preflight_failed);
    }

    #[test]
    fn a_watchdog_lock_left_by_a_dead_run_or_an_earlier_boot_is_not_a_running_watchdog() {
        // SECREL-05: a power cut while a watchdog run held the lock; the Mac is back within minutes. Round 2 read
        // any lock younger than 20 min as "the watchdog is starting the stack" (Start hidden) for up to 20 min.
        let boot = crate::macos::BootTime {
            sec: 1_761_370_000,
            usec: 658_471,
        };
        let alive = |p: i32| p == 4242;
        let m = Duration::from_secs(60);
        // the owner file the LIVE watchdog writes: "<pid> <usec>" (its greedy boot_epoch), held by a live owner
        assert!(watchdog_lock_held(
            m,
            Some("4242 658471\n"),
            Some(boot.sec + 5),
            Some(boot),
            alive
        ));
        // … and the corrected format "<pid> <boot sec>" (compatible both ways)
        assert!(watchdog_lock_held(
            m,
            Some("4242 1761370000\n"),
            Some(boot.sec + 5),
            Some(boot),
            alive
        ));
        assert!(
            !watchdog_lock_held(m, Some("4243 658471"), Some(boot.sec + 5), Some(boot), alive),
            "dead owner (or a pid that is no longer the watchdog)"
        );
        assert!(
            !watchdog_lock_held(m, Some("4242 1761300000"), Some(boot.sec + 5), Some(boot), alive),
            "earlier boot (seconds field)"
        );
        assert!(
            !watchdog_lock_held(m, Some("4242 123456"), Some(boot.sec + 5), Some(boot), alive),
            "earlier boot (microseconds field)"
        );
        assert!(
            !watchdog_lock_held(m, Some("4242"), Some(boot.sec + 5), Some(boot), alive),
            "no boot field"
        );
        assert!(
            !watchdog_lock_held(m, Some(""), Some(boot.sec + 5), Some(boot), alive),
            "unreadable owner file"
        );
        assert!(
            !watchdog_lock_held(m, Some("x 658471"), Some(boot.sec + 5), Some(boot), alive),
            "garbage pid"
        );
        // no owner file yet (a run that has just taken it, or an older watchdog): held unless it predates the boot
        assert!(watchdog_lock_held(m, None, Some(boot.sec + 5), Some(boot), alive));
        assert!(
            !watchdog_lock_held(m, None, Some(boot.sec - 100), Some(boot), alive),
            "from before this boot"
        );
        // boot time unknown: the owner's liveness still decides; no owner file: held (as before)
        assert!(watchdog_lock_held(m, Some("4242 1"), None, None, alive));
        assert!(watchdog_lock_held(m, None, None, None, alive));
        // older than 20 min: stale whatever the owner says (the watchdog's own rule)
        assert!(!watchdog_lock_held(
            WATCHDOG_LOCK_STALE,
            Some("4242 658471"),
            Some(boot.sec),
            Some(boot),
            alive
        ));

        // through the probe with real files
        let dir = tempfile::tempdir().unwrap();
        let home = tempfile::tempdir().unwrap();
        let p = StackPaths::new(dir.path());
        std::fs::create_dir_all(&p.watchdog_lock).unwrap();
        let now = SystemTime::now();
        let this_boot = crate::macos::BootTime {
            sec: now
                .duration_since(SystemTime::UNIX_EPOCH)
                .unwrap()
                .as_secs()
                .saturating_sub(3600),
            usec: 31_337,
        };
        let probe = |owner: &str| {
            std::fs::write(p.watchdog_lock.join("owner"), owner).unwrap();
            probe_files_with(&p, home.path(), now, Some(this_boot), alive).watchdog_running
        };
        assert!(probe("4242 31337\n"), "a live run (live watchdog format)");
        assert!(
            probe(&format!("4242 {}\n", this_boot.sec)),
            "a live run (seconds format)"
        );
        assert!(!probe("777 31337\n"), "its run died (SIGKILL, no EXIT trap)");
        assert!(!probe("4242 1000\n"), "left by the previous boot (power cut)");
    }

    /// The watchdog's own shell functions, cut from scripts/stack_watchdog.sh as it is today: a one-line
    /// `name() { …; }` or a block from `name() {` to the first line that is exactly `}`.
    fn watchdog_functions(names: &[&str]) -> String {
        let script =
            std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../scripts/stack_watchdog.sh"))
                .expect("scripts/stack_watchdog.sh");
        let lines: Vec<&str> = script.lines().collect();
        let mut out = String::new();
        for name in names {
            let head = format!("{name}()");
            let i = lines
                .iter()
                .position(|l| l.starts_with(&head))
                .unwrap_or_else(|| panic!("{name}() not found in scripts/stack_watchdog.sh"));
            if lines[i].contains("; }") {
                out.push_str(lines[i]);
                out.push('\n');
                continue;
            }
            for l in &lines[i..] {
                out.push_str(l);
                out.push('\n');
                if *l == "}" {
                    break;
                }
            }
        }
        out
    }

    /// Run `body` under /bin/bash with the watchdog's lock functions loaded and `LOCK` = `lock`, from a file named
    /// like the real script (`…/scripts/stack_watchdog.sh`: launchd runs `/bin/bash <repo>/scripts/stack_watchdog.sh`).
    fn watchdog_shell(dir: &Path, lock: &Path, body: &str, boot_epoch: Option<&str>) -> std::process::Command {
        let funcs = watchdog_functions(&["boot_epoch", "file_epoch", "proc_cmd", "lock_is_stale", "take_lock"]);
        let sdir = dir.join("scripts");
        std::fs::create_dir_all(&sdir).unwrap();
        let script = sdir.join("stack_watchdog.sh");
        // `boot_epoch`: a replacement definition (a watchdog version still running during a deploy)
        let over = boot_epoch.unwrap_or_default();
        std::fs::write(
            &script,
            format!("LOCK=\"$1\"\nlog() {{ :; }}\n{funcs}\n{over}\n{body}\n"),
        )
        .unwrap();
        let mut c = std::process::Command::new("/bin/bash");
        c.arg(&script).arg(lock).env("PATH", CHILD_PATH);
        c
    }

    /// The watchdog's `boot_epoch()` as deployed 25 Oct 18:12–21:35 (greedy sed: prints the `usec` field). A run of
    /// that version can still hold the lock while a corrected script is deployed.
    const ROUND3_BOOT_EPOCH: &str =
        "boot_epoch() { sysctl -n kern.boottime 2> /dev/null | sed -nE 's/.*sec = ([0-9]+).*/\\1/p'; }";

    #[test]
    fn the_real_watchdog_owner_line_is_read_as_a_running_watchdog() {
        // SECREL-05 (round 4b, the round-3 check's MAJOR): the lock is taken by the REAL take_lock / boot_epoch of
        // scripts/stack_watchdog.sh in a temp dir (never the live lock), and the app must read it exactly as the
        // watchdog's own lock_is_stale does: held while that run is alive, free once it is gone. Both the script
        // as it is now and the round-3 boot_epoch (usec) are exercised.
        real_watchdog_lock_case(None);
        real_watchdog_lock_case(Some(ROUND3_BOOT_EPOCH));
    }

    fn real_watchdog_lock_case(boot_epoch: Option<&str>) {
        let dir = tempfile::tempdir().unwrap();
        let home = tempfile::tempdir().unwrap();
        let p = StackPaths::new(dir.path());
        std::fs::create_dir_all(p.watchdog_lock.parent().unwrap()).unwrap();
        let ready = dir.path().join("ready");
        // the run sleeps in a child (no inherited stdio) whose pid it records, so the test can end it after
        // SIGKILLing the run itself
        let mut run = watchdog_shell(
            dir.path(),
            &p.watchdog_lock,
            &format!(
                "take_lock || exit 7\nsleep 30 > /dev/null 2>&1 < /dev/null &\necho $! > '{0}.child'\n: > '{0}'\nwait",
                ready.display()
            ),
            boot_epoch,
        )
        .spawn()
        .unwrap();
        let t0 = std::time::Instant::now();
        while !ready.exists() && t0.elapsed() < Duration::from_secs(10) {
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(ready.exists(), "the watchdog's take_lock did not run");
        let owner = std::fs::read_to_string(p.watchdog_lock.join("owner")).unwrap();
        let mut it = owner.split_whitespace();
        let pid: i32 = it.next().unwrap().parse().unwrap();
        let field: u64 = it.next().unwrap().parse().unwrap();
        assert_eq!(pid as u32, run.id(), "owner pid = the run ($$)");
        let boot = crate::macos::boot_time().expect("kern.boottime");
        assert!(
            owner_boot_matches(boot, field),
            "the watchdog's boot field {field} names neither {} nor {}",
            boot.sec,
            boot.usec
        );
        if boot_epoch == Some(ROUND3_BOOT_EPOCH) {
            assert_eq!(field, boot.usec, "the round-3 watchdog stamps the usec field");
        }
        assert!(is_watchdog_process(pid), "the run's command line names stack_watchdog");
        let now = SystemTime::now();
        let a = probe_files(&p, home.path(), now);
        assert!(
            a.watchdog_running,
            "a live watchdog run with the real owner line: {owner:?}"
        );
        // the watchdog itself agrees: its lock_is_stale says the lock is NOT stale (exit 1)
        let st = watchdog_shell(dir.path(), &p.watchdog_lock, "lock_is_stale", boot_epoch)
            .status()
            .unwrap();
        assert_eq!(st.code(), Some(1), "watchdog: held");

        // the run ends without its EXIT trap (SIGKILL / power cut): the lock and owner file stay behind
        unsafe {
            libc::kill(pid, libc::SIGKILL);
        }
        run.wait().unwrap();
        if let Some(child) = std::fs::read_to_string(dir.path().join("ready.child"))
            .ok()
            .and_then(|t| t.trim().parse::<i32>().ok())
        {
            unsafe {
                libc::kill(child, libc::SIGKILL);
            }
        }
        assert!(p.watchdog_lock.join("owner").exists());
        assert!(!probe_files(&p, home.path(), now).watchdog_running, "a dead owner");
        let st = watchdog_shell(dir.path(), &p.watchdog_lock, "lock_is_stale", boot_epoch)
            .status()
            .unwrap();
        assert_eq!(st.code(), Some(0), "watchdog: stale");

        // a live process that is NOT the watchdog with the same owner line (pid reuse): neither counts it
        let mut other = std::process::Command::new("/bin/sleep").arg("30").spawn().unwrap();
        std::fs::write(p.watchdog_lock.join("owner"), format!("{} {field}\n", other.id())).unwrap();
        assert!(!is_watchdog_process(other.id() as i32));
        assert!(!probe_files(&p, home.path(), now).watchdog_running, "a reused pid");
        let st = watchdog_shell(dir.path(), &p.watchdog_lock, "lock_is_stale", boot_epoch)
            .status()
            .unwrap();
        assert_eq!(st.code(), Some(0), "watchdog: stale (not a watchdog)");
        other.kill().unwrap();
        other.wait().unwrap();
    }

    #[test]
    fn the_hung_restart_promise_needs_the_watchdog_agent() {
        let a = |loaded: Option<bool>, installed: bool| Activity {
            watchdog_loaded: loaded,
            watchdog_installed: installed,
            ..Activity::default()
        };
        assert!(a(Some(true), true).watchdog_active());
        assert!(
            a(Some(true), false).watchdog_active(),
            "loaded from elsewhere still acts"
        );
        assert!(a(None, true).watchdog_active(), "installed, not probed yet");
        assert!(
            !a(Some(false), true).watchdog_active(),
            "installed but unloaded: nothing runs it"
        );
        assert!(!a(None, false).watchdog_active());
        assert!(!a(Some(false), false).watchdog_active());
    }
}
