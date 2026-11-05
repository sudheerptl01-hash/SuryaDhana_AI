//! Files the shell writes into ~/Downloads (`shell_save_download` and WebKit downloads), C2-security-05/11
//! and C1-desktop-native-05:
//!
//! * the name: basename-only sanitizer + extension allowlist (`policy::download_filename`; anything that
//!   could run or unpack gets `.txt` appended);
//! * uniqueness: Finder-style ` (n)` suffixes, checked with `symlink_metadata` (a dangling symlink counts
//!   as taken), then `O_EXCL` create, so a planted symlink is never followed;
//! * every file is tagged `com.apple.quarantine` (on the open descriptor for our own writes; on the path,
//!   without following a symlink, once WebKit finished its download), so Gatekeeper assesses whatever it
//!   is on first open and Archive Utility quarantines extracted content;
//! * limits for all windows together: [`policy::DOWNLOADS_PER_MINUTE`], [`policy::DOWNLOAD_BYTES_PER_HOUR`],
//!   and nothing is written when the volume has less than [`policy::MIN_FREE_DISK_BYTES`] free. WebKit
//!   downloads (whose size is known only when they finish) are charged to the SAME hourly byte budget at
//!   Finished: a file that takes the hour over the budget, or the volume under the free-space floor, is
//!   removed again, and while the budget is used up no new download starts (wave 2, C2-security-11);
//! * feedback: "Saved to Downloads" / "Could not save …" notifications (with the macOS privacy fix for
//!   EPERM), and File ▸ Show Latest Download (⌥⌘L, also in the menu-bar item) reveals the file in Finder.
//!   The notification plugin's click callbacks are not used: on macOS they park one OS thread per
//!   notification until the owner clears it from Notification Center.
//! * one WebKit download per URL at a time (round 3, R-RUST-03: WebKit names both events of a download by
//!   its URL only, so a second concurrent download of the same URL escaped quarantine and the byte budget):
//!   a second request for a URL that is still downloading is refused with "already being saved" ([`Pending`]).

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use crate::policy::{self, ByteBudget, RateLimiter};

/// A WebKit download in flight is forgotten after this long without a Finished event (never blocks a URL for
/// good if WebKit drops one).
pub const PENDING_STALE: Duration = Duration::from_secs(600);
/// A refused request's own (failed) Finished event is expected within this long (WebKit cancels it at once).
pub const REFUSED_STALE: Duration = Duration::from_secs(60);

/// WebKit downloads in flight, by URL (one per URL at a time, see the module docs).
///
/// A request the shell refuses ALSO ends with a Finished event (success = false, the same URL: WebKit cancels
/// it and reports the cancellation), so refusals are counted per URL and their failures are matched to them
/// first. Without that, the refused second click on an export would take the first, still running download's
/// entry, and the first file would end untagged and uncharged after all (round 3 review of R-RUST-03).
#[derive(Debug, Default)]
pub struct Pending {
    map: std::collections::HashMap<String, (PathBuf, Instant)>,
    /// Finished events still owed by refused requests: url -> (count, last refusal).
    refused: std::collections::HashMap<String, (u32, Instant)>,
}

impl Pending {
    fn expire(&mut self, now: Instant) {
        self.map.retain(|_, (_, t)| now.duration_since(*t) < PENDING_STALE);
        self.refused.retain(|_, (_, t)| now.duration_since(*t) < REFUSED_STALE);
    }

    /// Is `url` being downloaded right now (as of `now`)?
    pub fn busy(&mut self, url: &str, now: Instant) -> bool {
        self.expire(now);
        self.map.contains_key(url)
    }

    /// Record the destination of an admitted download of `url`; refused while one is in flight.
    pub fn begin(&mut self, url: &str, path: PathBuf, now: Instant) -> Result<(), &'static str> {
        if self.busy(url, now) {
            return Err("this file is already being saved: wait for it to finish, then try again");
        }
        self.map.insert(url.to_string(), (path, now));
        Ok(())
    }

    /// The shell refused a request for `url` (any reason): its failed Finished event is on its way.
    pub fn refuse(&mut self, url: &str, now: Instant) {
        self.expire(now);
        let e = self.refused.entry(url.to_string()).or_insert((0, now));
        e.0 = e.0.saturating_add(1);
        e.1 = now;
    }

    /// The destination of the download of `url` that just ended (None: a refused or never admitted request).
    /// A failed end is matched to an owed refusal of the same URL first; a successful end is always the
    /// admitted download's (a refused request never succeeds).
    pub fn finish(&mut self, url: &str, success: bool, now: Instant) -> Option<PathBuf> {
        self.expire(now);
        if !success {
            if let Some(e) = self.refused.get_mut(url) {
                e.0 -= 1;
                if e.0 == 0 {
                    self.refused.remove(url);
                }
                return None;
            }
        }
        self.map.remove(url).map(|(p, _)| p)
    }
}

/// Limits and the latest saved file, shared by every window.
pub struct Downloads {
    per_minute: Mutex<RateLimiter>,
    bytes: Mutex<ByteBudget>,
    last: Mutex<Option<PathBuf>>,
}

impl Default for Downloads {
    fn default() -> Self {
        Self {
            per_minute: Mutex::new(RateLimiter::new(policy::DOWNLOADS_PER_MINUTE, Duration::from_secs(60))),
            bytes: Mutex::new(ByteBudget::new(
                policy::DOWNLOAD_BYTES_PER_HOUR,
                Duration::from_secs(3600),
            )),
            last: Mutex::new(None),
        }
    }
}

impl Downloads {
    /// Admit one download of `bytes` (None = unknown yet, WebKit) onto a volume with `free` bytes left
    /// (None = unknown), or say why not.
    pub fn admit(&self, bytes: Option<u64>, free: Option<u64>) -> Result<(), String> {
        let now = Instant::now();
        if let Some(f) = free {
            if f < policy::MIN_FREE_DISK_BYTES {
                return Err(format!(
                    "only {:.1} GB free on the Downloads volume (SuryaDhana keeps at least 5 GB free for the stack)",
                    f as f64 / 1e9
                ));
            }
        }
        if !self.per_minute.lock().unwrap_or_else(|e| e.into_inner()).allow(now) {
            return Err(format!(
                "too many downloads (more than {} a minute); wait a moment",
                policy::DOWNLOADS_PER_MINUTE
            ));
        }
        let mut budget = self.bytes.lock().unwrap_or_else(|e| e.into_inner());
        let room = match bytes {
            Some(b) => budget.spend(now, b),
            // size unknown until it finishes (WebKit): refused only when the hour's budget is used up
            None => !budget.exhausted(now),
        };
        if !room {
            return Err(over_budget());
        }
        Ok(())
    }

    /// A WebKit download finished with `bytes` on a volume with `free` bytes left: charge the hourly byte
    /// budget (always recorded) and say whether the file may stay. Err = remove it (over budget, or it took
    /// the volume under the free-space floor).
    pub fn charge_finished(&self, bytes: u64, free: Option<u64>) -> Result<(), String> {
        let within = self
            .bytes
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .charge(Instant::now(), bytes);
        if !within {
            return Err(format!("{}; the file was removed", over_budget()));
        }
        if let Some(f) = free {
            if f < policy::MIN_FREE_DISK_BYTES {
                return Err(format!(
                    "it left only {:.1} GB free on the Downloads volume (SuryaDhana keeps at least 5 GB free); the file was removed",
                    f as f64 / 1e9
                ));
            }
        }
        Ok(())
    }

    pub fn record(&self, path: &Path) {
        *self.last.lock().unwrap_or_else(|e| e.into_inner()) = Some(path.to_path_buf());
    }

    /// The latest saved file, if it still exists.
    pub fn latest(&self) -> Option<PathBuf> {
        self.last
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
            .filter(|p| std::fs::symlink_metadata(p).is_ok())
    }
}

fn over_budget() -> String {
    format!(
        "more than {} MB downloaded in the last hour; wait a while",
        policy::DOWNLOAD_BYTES_PER_HOUR / (1024 * 1024)
    )
}

fn epoch_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// The quarantine value for a file written now.
pub fn quarantine_now() -> String {
    policy::quarantine_value(epoch_secs())
}

/// A free name in `dir` for `raw` (allowlisted extension; ` (n)` suffix; `symlink_metadata`, so a dangling
/// symlink is taken).
pub fn free_name(dir: &Path, raw: &str) -> Result<String, String> {
    let name = policy::download_filename(raw);
    policy::unique_name(&name, |n| std::fs::symlink_metadata(dir.join(n)).is_ok()).map_err(|e| e.0)
}

/// Write `bytes` as a new file in `dir`: allowlisted unique name, `O_EXCL` create (never follows or
/// overwrites anything), quarantined on the descriptor, synced. Returns the path.
pub fn save_bytes(dir: &Path, raw_name: &str, bytes: &[u8]) -> Result<PathBuf, std::io::Error> {
    std::fs::create_dir_all(dir)?;
    for _ in 0..5 {
        let name = free_name(dir, raw_name).map_err(std::io::Error::other)?;
        let path = dir.join(&name);
        match std::fs::OpenOptions::new().write(true).create_new(true).open(&path) {
            Ok(mut f) => {
                use std::os::fd::AsRawFd;
                if let Err(e) = crate::macos::set_quarantine_fd(f.as_raw_fd(), &quarantine_now()) {
                    // never leave an untagged file behind
                    drop(f);
                    let _ = std::fs::remove_file(&path);
                    return Err(e);
                }
                if let Err(e) = f.write_all(bytes).and_then(|_| f.sync_all()) {
                    drop(f);
                    let _ = std::fs::remove_file(&path);
                    return Err(e);
                }
                return Ok(path);
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(e),
        }
    }
    Err(std::io::Error::other("could not find a free filename"))
}

/// A WebKit download finished at `path`: tag it (never following a final symlink).
pub fn quarantine_finished(path: &Path) -> std::io::Result<()> {
    let meta = std::fs::symlink_metadata(path)?;
    if meta.file_type().is_symlink() {
        return Err(std::io::Error::other("refusing to tag a symlink"));
    }
    crate::macos::set_quarantine_path(path, &quarantine_now())
}

/// Plain-language reason for a failed save (the owner sees it in a notification).
pub fn describe_error(e: &std::io::Error) -> String {
    match e.raw_os_error() {
        Some(libc::EPERM) | Some(libc::EACCES) => "macOS did not allow SuryaDhana to write to Downloads. Allow it in \
             System Settings › Privacy & Security › Files and Folders › SuryaDhana › Downloads Folder."
            .into(),
        Some(libc::ENOSPC) | Some(libc::EDQUOT) => "the disk is full.".into(),
        Some(libc::EROFS) => "the Downloads folder is on a read-only volume.".into(),
        _ => e.to_string(),
    }
}

/// `~/Downloads/x.csv` for display (never the account name); other locations as they are.
pub fn display_path(path: &Path, home: Option<&Path>) -> String {
    match home.and_then(|h| path.strip_prefix(h).ok()) {
        Some(rel) => format!("~/{}", rel.display()),
        None => path.display().to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn one_webkit_download_per_url_at_a_time() {
        // R-RUST-03: the second of two concurrent downloads of one blob / export URL used to overwrite the first
        // one's entry: one file stayed untagged and uncharged, the other was charged (or removed) mid-write
        let t0 = Instant::now();
        let mut p = Pending::default();
        let url = "blob:http://127.0.0.1:8010/1b2c";
        assert!(p.begin(url, PathBuf::from("/d/a.csv"), t0).is_ok());
        let e = p.begin(url, PathBuf::from("/d/a (1).csv"), t0).unwrap_err();
        assert!(e.contains("already being saved"), "{e}");
        assert!(p.busy(url, t0));
        // another URL is independent
        assert!(p
            .begin("http://127.0.0.1:8010/x.csv", PathBuf::from("/d/x.csv"), t0)
            .is_ok());
        // the first one ends: its own path comes back, and the URL can be downloaded again
        assert_eq!(p.finish(url, true, t0), Some(PathBuf::from("/d/a.csv")));
        assert_eq!(p.finish(url, false, t0), None, "nothing in flight: no file");
        assert!(p.begin(url, PathBuf::from("/d/a (1).csv"), t0).is_ok());
        // a download WebKit never finished does not block its URL for good
        assert!(!p.busy(url, t0 + PENDING_STALE));
    }

    #[test]
    fn a_refused_second_request_never_takes_the_running_downloads_entry() {
        // the refused request ends with its own failed Finished event (same URL). It arrives while the first
        // download still runs: it must be matched to the refusal, so the first one's Finished still finds its
        // file (quarantine + byte budget)
        let t0 = Instant::now();
        let url = "blob:http://127.0.0.1:8010/9f";
        let mut p = Pending::default();
        p.begin(url, PathBuf::from("/d/export.csv"), t0).unwrap();
        assert!(p.busy(url, t0));
        p.refuse(url, t0); // the second click
        assert_eq!(p.finish(url, false, t0), None, "the refusal's own end");
        assert!(p.busy(url, t0), "the first download is still tracked");
        assert_eq!(p.finish(url, true, t0), Some(PathBuf::from("/d/export.csv")));
        // order swapped: the first download finishes before the refusal's end is reported
        p.begin(url, PathBuf::from("/d/export (1).csv"), t0).unwrap();
        p.refuse(url, t0);
        assert_eq!(p.finish(url, true, t0), Some(PathBuf::from("/d/export (1).csv")));
        assert_eq!(p.finish(url, false, t0), None);
        assert!(!p.busy(url, t0));
        // two refusals, then the admitted one FAILS: every end is accounted for and the URL is free again
        p.begin(url, PathBuf::from("/d/e2.csv"), t0).unwrap();
        p.refuse(url, t0);
        p.refuse(url, t0);
        let ends: Vec<Option<PathBuf>> = (0..3).map(|_| p.finish(url, false, t0)).collect();
        assert_eq!(ends.iter().filter(|e| e.is_some()).count(), 1, "{ends:?}");
        assert!(!p.busy(url, t0));
        // a refusal whose end WebKit never reports is forgotten (it cannot swallow a later failure for good)
        p.refuse(url, t0);
        p.begin(url, PathBuf::from("/d/e3.csv"), t0).unwrap();
        assert_eq!(
            p.finish(url, false, t0 + REFUSED_STALE),
            Some(PathBuf::from("/d/e3.csv"))
        );
    }

    #[test]
    fn saves_quarantined_allowlisted_and_unique() {
        let dir = tempfile::tempdir().unwrap();
        let a = save_bytes(dir.path(), "../../stocks.csv", b"a,b\n").unwrap();
        assert_eq!(a.file_name().unwrap(), "stocks.csv");
        assert_eq!(std::fs::read(&a).unwrap(), b"a,b\n");
        let q = crate::macos::quarantine_of(&a).expect("quarantine xattr");
        assert!(q.starts_with("0083;") && q.ends_with(";SuryaDhana;"), "{q}");
        let b = save_bytes(dir.path(), "stocks.csv", b"x").unwrap();
        assert_eq!(b.file_name().unwrap(), "stocks (1).csv");
        // an executable-ish payload becomes text
        let z = save_bytes(dir.path(), "NIFTY_levels.zip", b"PK").unwrap();
        assert_eq!(z.file_name().unwrap(), "NIFTY_levels.zip.txt");
        assert!(crate::macos::quarantine_of(&z).is_some());
    }

    #[test]
    fn a_dangling_symlink_is_never_followed_or_overwritten() {
        let dir = tempfile::tempdir().unwrap();
        let outside = tempfile::tempdir().unwrap();
        let target = outside.path().join("pwned.csv");
        std::os::unix::fs::symlink(&target, dir.path().join("report.csv")).unwrap();
        // exists() is false for a dangling symlink; symlink_metadata() is not (C2-security-05 item 5)
        assert!(!dir.path().join("report.csv").exists());
        assert_eq!(free_name(dir.path(), "report.csv").unwrap(), "report (1).csv");
        let p = save_bytes(dir.path(), "report.csv", b"x").unwrap();
        assert_eq!(p.file_name().unwrap(), "report (1).csv");
        assert!(!target.exists(), "the symlink target was written");
        assert!(quarantine_finished(&dir.path().join("report.csv")).is_err());
    }

    #[test]
    fn limits_rate_bytes_and_free_space() {
        let d = Downloads::default();
        let plenty = Some(100 * 1024 * 1024 * 1024);
        assert!(d.admit(Some(1), Some(1024)).unwrap_err().contains("GB free"));
        for _ in 0..policy::DOWNLOADS_PER_MINUTE - 1 {
            assert!(d.admit(Some(1), plenty).is_ok());
        }
        assert!(d.admit(Some(1), None).is_ok());
        assert!(d.admit(Some(1), plenty).unwrap_err().contains("a minute"));
        let d = Downloads::default();
        assert!(d.admit(Some(policy::DOWNLOAD_BYTES_PER_HOUR), plenty).is_ok());
        assert!(d.admit(Some(1), plenty).unwrap_err().contains("200 MB"));
    }

    #[test]
    fn webkit_downloads_are_charged_to_the_same_byte_budget() {
        let plenty = Some(100 * 1024 * 1024 * 1024);
        let mb = 1024 * 1024;
        let d = Downloads::default();
        // round 1 (negative control): admit(None) never touched the budget, so 10 x 150 MB blob downloads a
        // minute were unbounded; now each one's size is charged when it finishes
        assert!(d.admit(None, plenty).is_ok());
        assert!(
            d.charge_finished(150 * mb, plenty).is_ok(),
            "150 MB: inside the 200 MB hour"
        );
        assert!(d.admit(None, plenty).is_ok(), "50 MB of the hour left: may start");
        let e = d.charge_finished(150 * mb, plenty).unwrap_err();
        assert!(e.contains("200 MB") && e.contains("removed"), "{e}");
        // the hour is used up: the next WebKit download is refused before it starts, and so is the bridge path
        assert!(d.admit(None, plenty).unwrap_err().contains("200 MB"));
        assert!(d.admit(Some(1), plenty).unwrap_err().contains("200 MB"));
        // the bridge path spends the same budget the WebKit path sees
        let d = Downloads::default();
        assert!(d.admit(Some(policy::DOWNLOAD_BYTES_PER_HOUR), plenty).is_ok());
        assert!(d.admit(None, plenty).is_err());
        // a finished download that took the volume under the floor is removed
        let d = Downloads::default();
        assert!(d.charge_finished(1, Some(1024)).unwrap_err().contains("GB free"));
    }

    #[test]
    fn latest_and_messages() {
        let d = Downloads::default();
        assert!(d.latest().is_none());
        let dir = tempfile::tempdir().unwrap();
        let p = dir.path().join("x.csv");
        std::fs::write(&p, b"1").unwrap();
        d.record(&p);
        assert_eq!(d.latest(), Some(p.clone()));
        std::fs::remove_file(&p).unwrap();
        assert!(d.latest().is_none(), "a deleted file is not offered");
        assert!(describe_error(&std::io::Error::from_raw_os_error(libc::EPERM)).contains("Files and Folders"));
        assert!(describe_error(&std::io::Error::from_raw_os_error(libc::ENOSPC)).contains("full"));
        assert_eq!(
            display_path(Path::new("/Users/u/Downloads/a.csv"), Some(Path::new("/Users/u"))),
            "~/Downloads/a.csv"
        );
        assert_eq!(
            display_path(Path::new("/tmp/a.csv"), Some(Path::new("/Users/u"))),
            "/tmp/a.csv"
        );
    }
}
