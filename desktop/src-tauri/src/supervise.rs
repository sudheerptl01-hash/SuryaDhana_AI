//! Crash relaunch for EVERY copy (round 3, SECREL-06 / R-RUST-05).
//!
//! launchd's `KeepAlive {SuccessfulExit: false}` relaunches only the process the Launch-at-Login job started.
//! A copy opened by hand (Dock, Finder, Spotlight after ⌘Q, or the copy running when Launch at Login is turned
//! on) is not that process, so a crash used to leave no app, no menu-bar item and no notifications until the
//! next login. Now such a copy starts a tiny crash guard: a detached `/bin/sh` loop (its own process group, no
//! inherited descriptors, `/dev/null` stdio; see [`crate::macos::spawn_detached`]) that checks every
//! [`GUARD_POLL_SECS`] s whether the app is still alive. When the app is gone:
//! * its run marker (`run.json`, crash.rs) still names it = it did not exit cleanly (crash, kill -9): the guard
//!   asks launchd to start the Launch-at-Login job (`launchctl kickstart gui/<uid>/SuryaDhana`, or `bootstrap`
//!   when the job is not loaded). From then on the app runs as the job's process, under KeepAlive, and the
//!   crash-loop breaker counts every further crash;
//! * the marker is gone (⌘Q / Quit / logout: a clean exit) or Launch at Login was turned off meanwhile: the
//!   guard exits and nothing is started.
//!
//! The guard costs one sleeping shell (`/bin/sleep` every 15 s, no CPU otherwise). It is started only for a
//! copy that the Launch-at-Login entry starts (the same executable), never in the self-test, a debug build,
//! with `SURYADHANA_NO_AUTOSTART=1` or for a drill's temp HOME without its own recording `launchctl`.
//!
//! `-[NSApplication disableRelaunchOnLogin]` is called while the entry exists, so macOS's "Reopen windows when
//! logging back in" never starts a second, LaunchServices copy that races the login job.

use std::ffi::OsStr;
use std::path::Path;

/// How often the guard checks whether the app is alive (crash relaunch within this + launch time).
pub const GUARD_POLL_SECS: u32 = 15;
/// `$0` of the guard's shell (visible in `ps`, used by drills to find it).
pub const GUARD_NAME: &str = "suryadhana-crash-guard";

/// The guard script. Arguments: app pid, run.json, Launch-at-Login plist, launchctl, uid. Everything is
/// passed as positional parameters (never interpolated into the script). The job label is
/// [`crate::autostart::LABEL`].
pub const GUARD_SH: &str = r#"trap '' HUP INT
pid="$1"; run="$2"; plist="$3"; tool="$4"; uid="$5"
while /bin/kill -0 "$pid" 2>/dev/null; do /bin/sleep 15; done
[ -f "$plist" ] || exit 0
/usr/bin/grep -q "\"pid\":$pid[,}]" "$run" 2>/dev/null || exit 0
"$tool" kickstart "gui/$uid/SuryaDhana" 2>/dev/null || "$tool" bootstrap "gui/$uid" "$plist"
"#;

/// Who relaunches this copy after a crash (the tray's status line).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Supervision {
    /// This process IS the Launch-at-Login job's: launchd's KeepAlive.
    LoginJob,
    /// A crash guard watches this copy (pid of the guard).
    Guarded(i32),
    /// Nothing does (why).
    Off(&'static str),
}

impl Supervision {
    /// The tray / menu line.
    pub fn text(&self) -> String {
        match self {
            Supervision::LoginJob => "Relaunch after a crash: on (login item)".into(),
            Supervision::Guarded(_) => "Relaunch after a crash: on (crash guard for this copy)".into(),
            Supervision::Off(why) => format!("Relaunch after a crash: off ({why})"),
        }
    }
}

/// What to do for this copy at start-up (pure).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Decision {
    LoginJob,
    Guard,
    Off(&'static str),
}

/// Pure rule. `untouchable` = self-test / debug build / SURYADHANA_NO_AUTOSTART; `state` = Launch at Login;
/// `entry_is_this_copy` = the entry starts this executable; `tool_ok` = launchd may be driven from this HOME.
pub fn decide(
    untouchable: bool,
    under_login_job: bool,
    state: crate::autostart::State,
    entry_is_this_copy: bool,
    tool_ok: bool,
) -> Decision {
    use crate::autostart::State;
    if under_login_job {
        return Decision::LoginJob;
    }
    if untouchable {
        return Decision::Off("self-test or development build");
    }
    match state {
        State::Off => Decision::Off("Launch at Login is off"),
        State::Blocked => Decision::Off("Launch at Login is off in System Settings"),
        State::On if !entry_is_this_copy => Decision::Off("Launch at Login starts another copy"),
        State::On if !tool_ok => Decision::Off("this HOME does not drive launchd"),
        State::On => Decision::Guard,
    }
}

/// Start the guard for `app_pid` (detached; returns the guard's pid).
pub fn spawn_guard(app_pid: u32, run_json: &Path, plist: &Path, launchctl: &Path, uid: u32) -> std::io::Result<i32> {
    let pid = app_pid.to_string();
    let uid = uid.to_string();
    let args: [&OsStr; 8] = [
        OsStr::new("-c"),
        OsStr::new(GUARD_SH),
        OsStr::new(GUARD_NAME),
        OsStr::new(&pid),
        run_json.as_os_str(),
        plist.as_os_str(),
        launchctl.as_os_str(),
        OsStr::new(&uid),
    ];
    crate::macos::spawn_detached(Path::new("/bin/sh"), &args)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::autostart::State;
    use std::time::{Duration, Instant};

    #[test]
    fn only_a_copy_the_login_entry_starts_is_guarded() {
        assert_eq!(decide(false, true, State::On, true, true), Decision::LoginJob);
        assert_eq!(
            decide(true, true, State::On, true, true),
            Decision::LoginJob,
            "launchd's own process"
        );
        assert_eq!(decide(false, false, State::On, true, true), Decision::Guard);
        assert!(matches!(decide(true, false, State::On, true, true), Decision::Off(_)));
        assert!(matches!(decide(false, false, State::Off, true, true), Decision::Off(w) if w.contains("off")));
        assert!(
            matches!(decide(false, false, State::Blocked, true, true), Decision::Off(w) if w.contains("System Settings"))
        );
        assert!(matches!(decide(false, false, State::On, false, true), Decision::Off(w) if w.contains("another copy")));
        assert!(matches!(decide(false, false, State::On, true, false), Decision::Off(_)));
        assert!(Supervision::Guarded(1).text().contains("on"));
        assert!(Supervision::Off("Launch at Login is off")
            .text()
            .contains("off (Launch at Login is off)"));
        assert_eq!(GUARD_SH.matches(crate::autostart::LABEL).count(), 1, "the job label");
        assert!(GUARD_SH.contains(&format!("sleep {GUARD_POLL_SECS}")));
    }

    /// The guard's shell logic with the real /bin/sh, a stand-in "app" (a sleep) and a recording launchctl.
    fn run_guard(crash: bool, plist_present: bool) -> String {
        let dir = tempfile::tempdir().unwrap();
        let calls = dir.path().join("calls");
        let tool = dir.path().join("launchctl");
        std::fs::write(&tool, format!("#!/bin/sh\necho \"$@\" >> '{}'\n", calls.display())).unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&tool, std::fs::Permissions::from_mode(0o755)).unwrap();
        let plist = dir.path().join("SuryaDhana.plist");
        if plist_present {
            std::fs::write(&plist, "x").unwrap();
        }
        let mut app = std::process::Command::new("/bin/sleep").arg("1").spawn().unwrap();
        let run = dir.path().join("run.json");
        std::fs::write(&run, format!("{{\"pid\":{},\"started\":1}}\n", app.id())).unwrap();
        // a fast copy of the script (sleep 15 -> 0.2) so the test takes about a second
        let script = GUARD_SH.replace("/bin/sleep 15", "/bin/sleep 0.2");
        let mut g = std::process::Command::new("/bin/sh")
            .arg("-c")
            .arg(&script)
            .arg(GUARD_NAME)
            .arg(app.id().to_string())
            .arg(&run)
            .arg(&plist)
            .arg(&tool)
            .arg("501")
            .spawn()
            .unwrap();
        if !crash {
            std::fs::remove_file(&run).unwrap(); // a clean exit removes the marker
        }
        let _ = app.wait();
        let t0 = Instant::now();
        while g.try_wait().unwrap().is_none() && t0.elapsed() < Duration::from_secs(10) {
            std::thread::sleep(Duration::from_millis(50));
        }
        assert!(g.try_wait().unwrap().is_some(), "the guard exits once the app is gone");
        std::fs::read_to_string(&calls).unwrap_or_default()
    }

    #[test]
    fn the_guard_relaunches_only_after_an_unclean_end() {
        assert_eq!(
            run_guard(true, true),
            "kickstart gui/501/SuryaDhana\n",
            "crash: the login job starts the app"
        );
        assert_eq!(run_guard(false, true), "", "clean quit: nothing is started");
        assert_eq!(
            run_guard(true, false),
            "",
            "Launch at Login turned off meanwhile: nothing is started"
        );
    }

    #[test]
    fn the_detached_guard_inherits_no_descriptor() {
        // the single-instance socket must never live on in the guard (later launches would hand off to it)
        let dir = tempfile::tempdir().unwrap();
        let out = dir.path().join("fds");
        let f = std::fs::File::open("/dev/null").unwrap();
        use std::os::fd::AsRawFd;
        // SAFETY: duplicate onto the lowest free descriptor >= 200, WITHOUT FD_CLOEXEC (what a careless library
        // might leak); nothing else is touched
        let leaked = unsafe { libc::fcntl(f.as_raw_fd(), libc::F_DUPFD, 200) };
        assert!(leaked >= 200);
        let leaked_s = leaked.to_string();
        let script = format!("ls /dev/fd > '{}'", out.display());
        let args = [OsStr::new("-c"), OsStr::new(&script)];
        let pid = crate::macos::spawn_detached(Path::new("/bin/sh"), &args).unwrap();
        let t0 = Instant::now();
        while std::fs::read_to_string(&out).map(|s| s.is_empty()).unwrap_or(true)
            && t0.elapsed() < Duration::from_secs(5)
        {
            std::thread::sleep(Duration::from_millis(20));
        }
        // SAFETY: reap our own child.
        unsafe {
            libc::waitpid(pid, std::ptr::null_mut(), 0);
        }
        let fds: Vec<String> = std::fs::read_to_string(&out)
            .unwrap()
            .split_whitespace()
            .map(String::from)
            .collect();
        assert!(!fds.contains(&leaked_s), "descriptor {leaked} leaked: {fds:?}");
        assert!(
            fds.contains(&"0".to_string()) && fds.contains(&"2".to_string()),
            "{fds:?}"
        );
        // negative control: a plain Command child does inherit it
        let ctl = std::process::Command::new("/bin/sh")
            .arg("-c")
            .arg("ls /dev/fd")
            .output()
            .unwrap();
        assert!(String::from_utf8_lossy(&ctl.stdout)
            .split_whitespace()
            .any(|x| x == leaked_s));
        // SAFETY: closing the descriptor this test created.
        unsafe {
            libc::close(leaked);
        }
    }
}
