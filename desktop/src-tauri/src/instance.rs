//! Single instance (replaces tauri-plugin-single-instance): a Unix socket in /tmp; the first instance
//! listens, a second launch connects, says `focus`, and exits 0 within milliseconds, before any window
//! exists.
//!
//! The socket is keyed on the home directory the app runs with. For the account's real home it is the
//! path the plugin used (`/tmp/ai_suryadhana_terminal_si.sock`), so a new build hands off to an older
//! running build during an upgrade. Under another `$HOME` (desktop/scripts/relaunch_drill.sh runs the real
//! app in a temp HOME) the path carries a hash of that HOME, so a drill never reaches, focuses or quits the
//! owner's running app. The self-test takes no lock at all.
//!
//! Round 3 (SECREL-10): /tmp is shared by every account. A socket file there that belongs to ANOTHER user (or a
//! symlink) is never connected to: handing off to it would make every launch, the login job's included, exit at
//! once, and the sticky bit stops this user from removing it. The app then runs without the lock (logged)
//! instead of never starting.

use std::io::{Read, Write};
use std::os::unix::fs::PermissionsExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Message a second (manual) launch sends: the running instance shows its window.
pub const FOCUS: &[u8] = b"focus\n";
/// Message a second launch by the login job sends (`--autostart`, e.g. the RunAtLoad start right after the
/// app reloaded its own Launch-at-Login job): the running instance only logs it and never steals focus.
pub const LOGIN: &[u8] = b"login\n";

/// FNV-1a 64-bit (stable across builds and platforms; not a security boundary).
fn fnv1a(bytes: &[u8]) -> u64 {
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in bytes {
        h ^= u64::from(*b);
        h = h.wrapping_mul(0x0100_0000_01b3);
    }
    h
}

/// Socket path for `identifier` and the home the app runs with (pure).
pub fn socket_path(identifier: &str, home: &Path, account_home: Option<&Path>) -> PathBuf {
    let id = identifier.replace(['.', '-'], "_");
    if account_home == Some(home) {
        PathBuf::from(format!("/tmp/{id}_si.sock"))
    } else {
        let h = fnv1a(home.as_os_str().as_encoded_bytes());
        PathBuf::from(format!("/tmp/{id}_{:08x}_si.sock", (h >> 32) as u32 ^ h as u32))
    }
}

/// WebKit data-store identifier for a home that is not the account's (drills): a stable, well-formed
/// UUID derived from the home path, so a drill's windows never share cookies, caches or localStorage with
/// the owner's running app (WebKit keeps website data under the real ~/Library whatever `$HOME` says).
/// None for the account's own home (the default store, as always).
pub fn isolated_data_store(home: &Path, account_home: Option<&Path>) -> Option<[u8; 16]> {
    if account_home == Some(home) {
        return None;
    }
    let b = home.as_os_str().as_encoded_bytes();
    let a = fnv1a(b).to_be_bytes();
    let mut salted = b.to_vec();
    salted.extend_from_slice(b"/webkit-data-store");
    let c = fnv1a(&salted).to_be_bytes();
    let mut id = [0u8; 16];
    id[..8].copy_from_slice(&a);
    id[8..].copy_from_slice(&c);
    id[6] = (id[6] & 0x0f) | 0x40; // version 4 layout
    id[8] = (id[8] & 0x3f) | 0x80; // RFC 4122 variant
    Some(id)
}

/// `XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX` (NSUUID's uppercase form; the drill deletes that store folder).
pub fn uuid_string(id: &[u8; 16]) -> String {
    let h: Vec<String> = id.iter().map(|b| format!("{b:02X}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        h[0..4].concat(),
        h[4..6].concat(),
        h[6..8].concat(),
        h[8..10].concat(),
        h[10..16].concat()
    )
}

/// Outcome of [`claim`].
#[derive(Debug)]
pub enum Claim {
    /// This is the first instance: serve the listener.
    Primary(UnixListener),
    /// Another instance is running and was told (focus or login): exit now.
    Secondary,
    /// Could neither connect nor bind (e.g. /tmp not writable): run without the lock (logged).
    Unlocked(String),
}

fn hand_off(path: &Path, msg: &[u8]) -> bool {
    match UnixStream::connect(path) {
        Ok(mut s) => {
            let _ = s.set_write_timeout(Some(Duration::from_millis(500)));
            let _ = s.write_all(msg);
            true
        }
        Err(_) => false,
    }
}

/// Become the primary instance or hand off to the running one (`msg` = [`FOCUS`] or [`LOGIN`]).
pub fn claim(path: &Path) -> Claim {
    claim_with(path, FOCUS)
}

/// Pure: may the lock file at a path be used, given its `lstat` (None = there is none)? Only one that this user
/// owns and that is not a symlink (SECREL-10).
pub fn lock_file_problem(meta: Option<(u32, bool)>, own_uid: u32) -> Option<String> {
    match meta {
        None => None,
        Some((_, true)) => Some("it is a symbolic link".into()),
        Some((uid, false)) if uid != own_uid => Some(format!("it belongs to uid {uid}, not to this user")),
        Some(_) => None,
    }
}

fn lock_file_check(path: &Path) -> Option<String> {
    use std::os::unix::fs::MetadataExt;
    let meta = std::fs::symlink_metadata(path)
        .ok()
        .map(|m| (m.uid(), m.file_type().is_symlink()));
    // SAFETY: getuid has no preconditions.
    lock_file_problem(meta, unsafe { libc::getuid() }).map(|why| format!("{}: {why}", path.display()))
}

/// [`claim`] with the message a secondary sends.
pub fn claim_with(path: &Path, msg: &[u8]) -> Claim {
    if let Some(why) = lock_file_check(path) {
        return Claim::Unlocked(format!("not using the single-instance lock {why}"));
    }
    if hand_off(path, msg) {
        return Claim::Secondary;
    }
    // nobody answers: a stale socket file from a crash
    let _ = std::fs::remove_file(path);
    match UnixListener::bind(path) {
        Ok(l) => {
            let _ = std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600));
            Claim::Primary(l)
        }
        Err(e) if e.kind() == std::io::ErrorKind::AddrInUse => {
            // lost a race with a simultaneous launch: hand off to the winner (if it is ours)
            if let Some(why) = lock_file_check(path) {
                return Claim::Unlocked(format!("not using the single-instance lock {why}"));
            }
            if hand_off(path, msg) {
                Claim::Secondary
            } else {
                Claim::Unlocked(format!("{}: {e}", path.display()))
            }
        }
        Err(e) => Claim::Unlocked(format!("{}: {e}", path.display())),
    }
}

/// Serve hand-offs on a background thread: `on_focus` runs for every `focus` message; a `login` message
/// (the login job found this instance already running) is logged and changes nothing.
pub fn serve(listener: UnixListener, on_focus: impl Fn() + Send + 'static) {
    let _ = std::thread::Builder::new()
        .name("single-instance".into())
        .spawn(move || {
            for stream in listener.incoming() {
                let Ok(mut s) = stream else { continue };
                let _ = s.set_read_timeout(Some(Duration::from_millis(500)));
                let mut buf = [0u8; 16];
                let n = s.read(&mut buf).unwrap_or(0);
                if buf[..n].starts_with(b"focus") {
                    on_focus();
                } else if buf[..n].starts_with(b"login") {
                    log::info!(
                        "[app] the login job started a second copy; this instance keeps running (no focus change)"
                    );
                }
            }
        });
}

/// Is a primary instance listening on `path`? (connects and hangs up without a message: the primary ignores it)
pub fn is_running(path: &Path) -> bool {
    UnixStream::connect(path).is_ok()
}

/// Remove the socket at exit (only the primary calls this).
pub fn release(path: &Path) {
    let _ = std::fs::remove_file(path);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;

    #[test]
    fn real_home_keeps_the_plugin_path_other_homes_are_isolated() {
        let real = Path::new("/Users/sudheer");
        assert_eq!(
            socket_path("ai.suryadhana.terminal", real, Some(real)),
            PathBuf::from("/tmp/ai_suryadhana_terminal_si.sock")
        );
        let drill = Path::new("/var/folders/x/T/suryadhana-drill.AbC123");
        let a = socket_path("ai.suryadhana.terminal", drill, Some(real));
        let b = socket_path("ai.suryadhana.terminal", Path::new("/tmp/other-home"), Some(real));
        assert_ne!(a, PathBuf::from("/tmp/ai_suryadhana_terminal_si.sock"));
        assert_ne!(a, b);
        assert_eq!(a, socket_path("ai.suryadhana.terminal", drill, Some(real)), "stable");
        assert!(a.as_os_str().len() < 100, "unix socket path limit");
        // unknown account home: always the hashed form (never collides with the owner's lock)
        assert_ne!(
            socket_path("ai.suryadhana.terminal", real, None),
            PathBuf::from("/tmp/ai_suryadhana_terminal_si.sock")
        );
    }

    #[test]
    fn drill_homes_get_their_own_webkit_store() {
        let real = Path::new("/Users/sudheer");
        assert_eq!(
            isolated_data_store(real, Some(real)),
            None,
            "the owner's app keeps the default store"
        );
        let a = isolated_data_store(Path::new("/var/folders/x/T/drill.1"), Some(real)).unwrap();
        let b = isolated_data_store(Path::new("/var/folders/x/T/drill.2"), Some(real)).unwrap();
        assert_ne!(a, b);
        assert_eq!(
            Some(a),
            isolated_data_store(Path::new("/var/folders/x/T/drill.1"), Some(real))
        );
        let u = uuid_string(&a);
        assert_eq!(u.len(), 36);
        assert_eq!(&u[14..15], "4", "version nibble: {u}");
        assert!(matches!(&u[19..20], "8" | "9" | "A" | "B"), "variant: {u}");
        assert_eq!(uuid_string(&[0xab; 16]), "ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB");
    }

    #[test]
    fn second_claim_hands_off_and_first_gets_focus() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("si.sock");
        let Claim::Primary(l) = claim(&path) else {
            panic!("first claim must be primary")
        };
        let hits = Arc::new(AtomicUsize::new(0));
        let h = hits.clone();
        serve(l, move || {
            h.fetch_add(1, Ordering::SeqCst);
        });
        assert!(matches!(claim(&path), Claim::Secondary));
        for _ in 0..50 {
            if hits.load(Ordering::SeqCst) == 1 {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        assert_eq!(hits.load(Ordering::SeqCst), 1);
        let mode = std::fs::metadata(&path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        release(&path);
        assert!(!path.exists());
    }

    #[test]
    fn a_login_job_secondary_never_steals_focus() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("si.sock");
        let Claim::Primary(l) = claim(&path) else {
            panic!("first claim must be primary")
        };
        let hits = Arc::new(AtomicUsize::new(0));
        let h = hits.clone();
        serve(l, move || {
            h.fetch_add(1, Ordering::SeqCst);
        });
        // the RunAtLoad start after a Launch-at-Login reload: exits as a secondary, no focus
        assert!(matches!(claim_with(&path, LOGIN), Claim::Secondary));
        std::thread::sleep(Duration::from_millis(200));
        assert_eq!(hits.load(Ordering::SeqCst), 0);
        // a manual second launch still focuses (control)
        assert!(matches!(claim(&path), Claim::Secondary));
        for _ in 0..50 {
            if hits.load(Ordering::SeqCst) == 1 {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        assert_eq!(hits.load(Ordering::SeqCst), 1);
        // a liveness probe (the CLI's "is it running?") changes nothing in the primary
        assert!(is_running(&path));
        std::thread::sleep(Duration::from_millis(200));
        assert_eq!(hits.load(Ordering::SeqCst), 1);
        release(&path);
        assert!(!is_running(&path));
    }

    #[test]
    fn a_lock_file_of_another_user_or_a_symlink_is_never_handed_off_to() {
        // SECREL-10: another account binds the predictable /tmp path; every launch used to hand off and exit 0
        assert_eq!(lock_file_problem(None, 501), None);
        assert_eq!(lock_file_problem(Some((501, false)), 501), None);
        assert!(lock_file_problem(Some((502, false)), 501).unwrap().contains("uid 502"));
        assert!(lock_file_problem(Some((501, true)), 501)
            .unwrap()
            .contains("symbolic link"));
        // a real primary somewhere else, reachable only through a symlink planted at the lock path
        let dir = tempfile::tempdir().unwrap();
        let real = dir.path().join("real.sock");
        let Claim::Primary(l) = claim(&real) else {
            panic!("primary")
        };
        let hits = Arc::new(AtomicUsize::new(0));
        let h = hits.clone();
        serve(l, move || {
            h.fetch_add(1, Ordering::SeqCst);
        });
        let planted = dir.path().join("si.sock");
        std::os::unix::fs::symlink(&real, &planted).unwrap();
        match claim(&planted) {
            Claim::Unlocked(why) => assert!(why.contains("symbolic link"), "{why}"),
            other => panic!("expected Unlocked, got {other:?}"),
        }
        std::thread::sleep(Duration::from_millis(200));
        assert_eq!(hits.load(Ordering::SeqCst), 0, "never connected through the symlink");
        // control: the real path of this user's own primary is handed off to as before
        assert!(matches!(claim(&real), Claim::Secondary));
    }

    #[test]
    fn stale_socket_file_is_replaced() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("si.sock");
        {
            let _dead = UnixListener::bind(&path).unwrap(); // dropped: the file stays, nobody listens
        }
        assert!(path.exists());
        assert!(matches!(claim(&path), Claim::Primary(_)));
    }
}
