//! Crash visibility and the crash-loop breaker (C1-desktop-native-13, C2-reliability-ops-12).
//!
//! * A panic hook writes the location and message to the app log (and flushes it) before the default hook
//!   prints to stderr, which the login job captures in `launchd-stderr.log`.
//! * `<config>/run.json` marks a running instance; a clean exit removes it. A launch that finds a marker
//!   whose process is gone records an unclean end in `<config>/crashes.json` (last 20 epoch seconds).
//! * The login job relaunches a crashed app (`KeepAlive {SuccessfulExit: false}`). If the app crashes
//!   [`LOOP_CRASHES`] times within [`LOOP_WINDOW_SECS`], a launch by that job (`--autostart`) exits 0
//!   instead of starting, which tells launchd to stop respawning it; the reason is logged, and a manual
//!   launch always runs.
//! * A marker left by a run that started BEFORE the current boot (`kern.boottime`) is a power cut / forced
//!   restart / kernel panic, not an app crash: it is logged as such, never counted towards the crash loop,
//!   and the next login keeps its start-up grace (wave 2: the 16–19 Oct outage was exactly that).
//! * Round 3 (R-RUST-04): the check runs in `lib::run` BEFORE Tauri is built, so a start that fails before
//!   the app exists (log plugin, a full or unwritable disk, a plugin error) is counted too and the breaker
//!   stands the login job down; a login-job start that cannot write its run marker stands down at once
//!   (it could never be counted, so launchd would respawn it forever).

use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::config::write_atomic;

/// Unclean ends within [`LOOP_WINDOW_SECS`] that make a login-job launch stand down.
pub const LOOP_CRASHES: usize = 4;
/// Crash-loop window (seconds).
pub const LOOP_WINDOW_SECS: u64 = 600;
const KEEP: usize = 20;

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// Install the panic hook (idempotent enough: the last call wins).
pub fn install_panic_hook() {
    let default = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        let location = info
            .location()
            .map(|l| format!("{}:{}", l.file(), l.line()))
            .unwrap_or_else(|| "unknown location".into());
        let msg = info
            .payload()
            .downcast_ref::<&str>()
            .map(|s| s.to_string())
            .or_else(|| info.payload().downcast_ref::<String>().cloned())
            .unwrap_or_else(|| "non-string panic payload".into());
        let thread = std::thread::current().name().unwrap_or("unnamed").to_string();
        log::error!("[panic] thread '{thread}' at {location}: {msg}");
        log::logger().flush();
        default(info);
    }));
}

/// `run.json`: the instance that is running now.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RunMarker {
    pub pid: u32,
    pub started: u64,
}

/// Recorded unclean ends.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct CrashHistory {
    #[serde(default)]
    pub unclean_ends: Vec<u64>,
}

impl CrashHistory {
    /// Pure: crashes inside the window ending at `now`.
    pub fn recent(&self, now: u64) -> usize {
        self.unclean_ends
            .iter()
            .filter(|t| now.saturating_sub(**t) < LOOP_WINDOW_SECS)
            .count()
    }

    /// Pure: is this a crash loop at `now`?
    pub fn is_loop(&self, now: u64) -> bool {
        self.recent(now) >= LOOP_CRASHES
    }

    fn push(&mut self, t: u64) {
        self.unclean_ends.push(t);
        if self.unclean_ends.len() > KEEP {
            let cut = self.unclean_ends.len() - KEEP;
            self.unclean_ends.drain(..cut);
        }
    }
}

/// What the startup check decided.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Startup {
    /// The previous run ended without a clean exit during THIS boot (crash, kill -9): a crash relaunch.
    pub previous_unclean: bool,
    /// The previous run's marker is from before this boot (power loss, forced restart, kernel panic):
    /// not a crash relaunch, not counted.
    pub previous_boot: bool,
    /// Unclean ends inside the window (including the previous run).
    pub recent_crashes: usize,
    /// A login-job launch must stand down (exit 0) to stop launchd's respawns.
    pub stand_down: bool,
    /// This run's marker was written (false: the config dir is not writable, e.g. a full disk).
    pub marker_written: bool,
}

/// Files of the crash bookkeeping (in the app config dir).
#[derive(Debug, Clone)]
pub struct CrashFiles {
    pub run: PathBuf,
    pub history: PathBuf,
}

impl CrashFiles {
    pub fn new(config_dir: &Path) -> Self {
        Self {
            run: config_dir.join("run.json"),
            history: config_dir.join("crashes.json"),
        }
    }

    fn load_history(&self) -> CrashHistory {
        std::fs::read_to_string(&self.history)
            .ok()
            .and_then(|t| serde_json::from_str(&t).ok())
            .unwrap_or_default()
    }

    /// At launch: read the previous marker, record an unclean end, decide, then mark this run.
    /// `alive(pid)` says whether a pid is a live process and `boot` is the system boot time (epoch s; None
    /// unknown), both injected for tests.
    pub fn on_start(
        &self,
        login_job: bool,
        now: u64,
        own_pid: u32,
        boot: Option<u64>,
        alive: impl Fn(u32) -> bool,
    ) -> Startup {
        let prev: Option<RunMarker> = std::fs::read_to_string(&self.run)
            .ok()
            .and_then(|t| serde_json::from_str(&t).ok());
        let mut history = self.load_history();
        let dead = matches!(&prev, Some(m) if m.pid != own_pid && !alive(m.pid));
        // a marker older than this boot cannot be a crash of this boot (pids are reused across boots too)
        let previous_boot = dead && matches!((&prev, boot), (Some(m), Some(b)) if m.started < b);
        let previous_unclean = dead && !previous_boot;
        if previous_unclean {
            history.push(now);
            let _ = write_atomic(
                &self.history,
                &(serde_json::to_string(&history).unwrap_or_default() + "\n"),
            );
        }
        let recent = history.recent(now);
        let mut stand_down = login_job && history.is_loop(now);
        let mut marker_written = false;
        if stand_down {
            // the previous end is recorded: drop its marker, so the next (manual) launch does not count it
            // a second time (wave-2 nit)
            let _ = std::fs::remove_file(&self.run);
        } else {
            let marker = RunMarker {
                pid: own_pid,
                started: now,
            };
            // write_atomic creates the config dir on a first launch
            marker_written =
                write_atomic(&self.run, &(serde_json::to_string(&marker).unwrap_or_default() + "\n")).is_ok();
            // R-RUST-04: an unaccounted login-job start could crash-loop forever (nothing counts it)
            if login_job && !marker_written {
                stand_down = true;
            }
        }
        Startup {
            previous_unclean,
            previous_boot,
            recent_crashes: recent,
            stand_down,
            marker_written,
        }
    }

    /// Clean exit: remove this run's marker (only if it is ours).
    pub fn on_clean_exit(&self, own_pid: u32) {
        let ours = std::fs::read_to_string(&self.run)
            .ok()
            .and_then(|t| serde_json::from_str::<RunMarker>(&t).ok())
            .map(|m| m.pid == own_pid)
            .unwrap_or(false);
        if ours {
            let _ = std::fs::remove_file(&self.run);
        }
    }
}

static TERM_PIPE_W: std::sync::atomic::AtomicI32 = std::sync::atomic::AtomicI32::new(-1);

extern "C" fn on_sigterm(_sig: libc::c_int) {
    // async-signal-safe: one write(2) to the self-pipe
    let fd = TERM_PIPE_W.load(std::sync::atomic::Ordering::Relaxed);
    if fd >= 0 {
        // SAFETY: write(2) is async-signal-safe; the buffer is a static byte.
        unsafe {
            libc::write(fd, b"t".as_ptr().cast(), 1);
        }
    }
}

/// SIGTERM (logout, `kill`, `launchctl kill TERM`) = Quit: `on_term` runs on a normal thread (it should
/// save the session and exit 0 like ⌘Q, so launchd's KeepAlive does not treat it as a crash); if the app
/// has not exited `hard_exit_after` later, `before_hard_exit` runs (the clean-exit bookkeeping: the next
/// launch must not see a crash marker) and it exits 0 anyway. The handler only writes to a close-on-exec
/// self-pipe; children get the default disposition back at exec.
pub fn install_sigterm_quit(
    on_term: impl FnOnce() + Send + 'static,
    hard_exit_after: Option<std::time::Duration>,
    before_hard_exit: impl FnOnce() + Send + 'static,
) {
    let mut fds = [0 as libc::c_int; 2];
    // SAFETY: pipe/fcntl/sigaction with valid arguments; failure leaves the default SIGTERM behaviour.
    unsafe {
        if libc::pipe(fds.as_mut_ptr()) != 0 {
            return;
        }
        for fd in fds {
            libc::fcntl(fd, libc::F_SETFD, libc::FD_CLOEXEC);
        }
        TERM_PIPE_W.store(fds[1], std::sync::atomic::Ordering::Relaxed);
        let mut sa: libc::sigaction = std::mem::zeroed();
        sa.sa_sigaction = on_sigterm as *const () as usize;
        sa.sa_flags = libc::SA_RESTART;
        libc::sigemptyset(&mut sa.sa_mask);
        libc::sigaction(libc::SIGTERM, &sa, std::ptr::null_mut());
    }
    let read_fd = fds[0];
    let _ = std::thread::Builder::new().name("sigterm".into()).spawn(move || {
        let mut b = [0u8; 1];
        // SAFETY: blocking read of one byte from our own pipe.
        let n = unsafe { libc::read(read_fd, b.as_mut_ptr().cast(), 1) };
        if n == 1 {
            log::info!("[app] SIGTERM: quitting like ⌘Q");
            on_term();
            if let Some(after) = hard_exit_after {
                std::thread::sleep(after);
                log::warn!("[app] SIGTERM: still running {after:?} later; exiting");
                before_hard_exit();
                log::logger().flush();
                std::process::exit(0);
            }
        }
    });
}

/// Best effort: one line into the app log before the log plugin exists (R-RUST-04: a start that stands down
/// or fails while Tauri is built must still say why where the owner looks, not only in launchd-stderr.log).
pub fn append_app_log(log_dir: &Path, msg: &str) {
    use std::io::Write;
    let _ = std::fs::create_dir_all(log_dir);
    let stamp = time::OffsetDateTime::now_local()
        .unwrap_or_else(|_| time::OffsetDateTime::now_utc())
        .format(time::macros::format_description!(
            "[[[year]-[month]-[day]][[[hour]:[minute]:[second]]"
        ))
        .unwrap_or_default();
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(log_dir.join("suryadhana.log"))
    {
        let _ = writeln!(f, "{stamp}[ERROR][suryadhana_desktop_lib] [app] {msg}");
    }
}

/// Launch-time convenience over [`CrashFiles::on_start`] with the real clock, boot time and process table.
pub fn startup_check(config_dir: &Path, login_job: bool) -> Startup {
    CrashFiles::new(config_dir).on_start(
        login_job,
        now_secs(),
        std::process::id(),
        crate::macos::boot_time_secs(),
        pid_alive,
    )
}

/// True when `pid` is a live process (signal 0).
pub fn pid_alive(pid: u32) -> bool {
    // SAFETY: kill with signal 0 only checks existence/permission.
    pid > 0 && unsafe { libc::kill(pid as libc::pid_t, 0) } == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clean_exit_then_relaunch_is_not_a_crash() {
        let dir = tempfile::tempdir().unwrap();
        let f = CrashFiles::new(dir.path());
        let s = f.on_start(true, 1000, 10, None, |_| false);
        assert!(!s.previous_unclean && !s.stand_down);
        f.on_clean_exit(10);
        assert!(!f.run.exists());
        let s = f.on_start(true, 1010, 11, None, |_| false);
        assert!(!s.previous_unclean, "{s:?}");
    }

    #[test]
    fn a_marker_of_a_live_process_is_not_a_crash() {
        let dir = tempfile::tempdir().unwrap();
        let f = CrashFiles::new(dir.path());
        f.on_start(false, 1000, 10, None, |_| false);
        // a second instance starts while 10 still runs (it will hand off and exit)
        let s = f.on_start(false, 1001, 12, None, |p| p == 10);
        assert!(!s.previous_unclean);
    }

    #[test]
    fn repeated_crashes_make_the_login_job_stand_down() {
        let dir = tempfile::tempdir().unwrap();
        let f = CrashFiles::new(dir.path());
        let mut t = 10_000;
        let mut pid = 100;
        f.on_start(true, t, pid, None, |_| false);
        // crash, relaunch by launchd every ~20 s
        let mut last = None;
        for _ in 0..LOOP_CRASHES {
            t += 20;
            pid += 1;
            last = Some(f.on_start(true, t, pid, None, |_| false));
        }
        let s = last.unwrap();
        assert!(s.previous_unclean && s.stand_down, "{s:?}");
        assert_eq!(s.recent_crashes, LOOP_CRASHES);
        // a manual launch (not the login job) always runs
        // the stand-down removed the run marker: this manual launch does not count that crash again
        assert!(!f.run.exists(), "stand-down leaves no marker behind");
        let s = f.on_start(false, t + 1, pid + 1, None, |_| false);
        assert!(!s.stand_down);
        assert!(!s.previous_unclean, "the same crash is never counted twice");
        assert_eq!(s.recent_crashes, LOOP_CRASHES);
        // ten minutes later the window has passed
        let s = CrashFiles::new(dir.path()).on_start(true, t + LOOP_WINDOW_SECS + 30, pid + 2, None, |_| true);
        assert!(!s.stand_down, "{s:?}");
    }

    #[test]
    fn an_unclean_end_before_this_boot_keeps_the_login_grace() {
        // the 16–19 Oct shape: the app ran (marker started 1000), the Mac lost power, it booted at 5000 and
        // the login job starts the app at 5060
        let dir = tempfile::tempdir().unwrap();
        let f = CrashFiles::new(dir.path());
        f.on_start(true, 1000, 10, Some(900), |_| false);
        let s = f.on_start(true, 5060, 11, Some(5000), |_| false);
        assert!(!s.previous_unclean, "not a crash relaunch: {s:?}");
        assert!(s.previous_boot);
        assert_eq!(s.recent_crashes, 0, "a power cut is not counted towards the crash loop");
        // a real crash during this boot still is one (negative control)
        let s = f.on_start(true, 5100, 12, Some(5000), |_| false);
        assert!(s.previous_unclean && !s.previous_boot, "{s:?}");
        assert_eq!(s.recent_crashes, 1);
        // unknown boot time: treated as before (an unclean end)
        let s = f.on_start(true, 5200, 13, None, |_| false);
        assert!(s.previous_unclean && !s.previous_boot);
    }

    #[test]
    fn sigterm_becomes_a_quit_not_a_kill() {
        let (tx, rx) = std::sync::mpsc::channel();
        install_sigterm_quit(
            move || {
                let _ = tx.send(());
            },
            None,
            || {},
        );
        // SAFETY: raising SIGTERM in this process runs the handler installed above (it only writes a byte).
        unsafe {
            libc::raise(libc::SIGTERM);
        }
        assert!(
            rx.recv_timeout(std::time::Duration::from_secs(3)).is_ok(),
            "the quit callback ran and the test process is still alive"
        );
    }

    #[test]
    fn an_unwritable_config_dir_stands_a_login_start_down_but_never_a_manual_one() {
        // R-RUST-04: a full / read-only config volume: the run marker cannot be written, so a crash could never
        // be counted; the login job stands down instead of being respawned by launchd forever
        let dir = tempfile::tempdir().unwrap();
        let ro = dir.path().join("ro");
        std::fs::create_dir(&ro).unwrap();
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&ro, std::fs::Permissions::from_mode(0o500)).unwrap();
        let f = CrashFiles::new(&ro);
        let s = f.on_start(true, 1000, 10, None, |_| false);
        assert!(!s.marker_written && s.stand_down, "{s:?}");
        let s = f.on_start(false, 1000, 10, None, |_| false);
        assert!(!s.marker_written && !s.stand_down, "a manual launch always runs: {s:?}");
        std::fs::set_permissions(&ro, std::fs::Permissions::from_mode(0o700)).unwrap();
        // control: writable -> the marker is written, no stand-down
        let s = CrashFiles::new(&ro).on_start(true, 1000, 10, None, |_| false);
        assert!(s.marker_written && !s.stand_down, "{s:?}");
        // a missing config dir (first launch ever) is created, not a stand-down
        let fresh = CrashFiles::new(&dir.path().join("new/ai.suryadhana.terminal"));
        assert!(fresh.on_start(true, 1000, 10, None, |_| false).marker_written);
    }

    #[test]
    fn history_is_bounded() {
        let mut h = CrashHistory::default();
        for i in 0..50 {
            h.push(i);
        }
        assert_eq!(h.unclean_ends.len(), KEEP);
        assert_eq!(h.unclean_ends[0], 30);
        assert!(pid_alive(std::process::id()));
        assert!(!pid_alive(0));
    }
}
