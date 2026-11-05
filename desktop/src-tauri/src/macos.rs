//! Thin wrappers over macOS APIs that Tauri does not expose. Every `unsafe` block of the shell lives here,
//! each with its contract; callers get plain Rust types and never an Objective-C exception (calls that can
//! throw run inside `objc2::exception::catch`).
//!
//! * window tabbing off (`NSWindow.allowsAutomaticWindowTabbing = NO`) and `NSBeep()`;
//! * the real notification authorization of this app (UNUserNotificationCenter), and its request;
//! * the Login Items (Background Task Management) status of the Launch-at-Login plist, and opening that
//!   System Settings pane;
//! * `com.apple.quarantine` on files the shell writes; per-process uid / executable (libproc);
//!   the account's real home directory; free bytes on a volume.

use std::ffi::{CStr, CString};
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::mpsc;
use std::time::Duration;

use block2::RcBlock;
use objc2::rc::Retained;
use objc2::runtime::{AnyClass, AnyObject, Bool};
use objc2::{msg_send, MainThreadMarker};
use objc2_foundation::{NSBundle, NSString, NSURL};

/// The bundle identifier (tauri.conf.json `identifier`).
pub const BUNDLE_ID: &str = "ai.suryadhana.terminal";

#[link(name = "UserNotifications", kind = "framework")]
extern "C" {}

// ---------------------------------------------------------------------------------------------
// AppKit
// ---------------------------------------------------------------------------------------------

/// Turn macOS automatic window tabbing off for the whole app (C1-desktop-native-16): the custom 32 px title
/// strip and the traffic-light inset assume no native tab bar, and session restore cannot recreate tabs.
/// tao only ever sets this property to NO, so one call at startup holds for every later window.
pub fn disable_automatic_window_tabbing() -> bool {
    match MainThreadMarker::new() {
        Some(mtm) => {
            objc2_app_kit::NSWindow::setAllowsAutomaticWindowTabbing(false, mtm);
            !objc2_app_kit::NSWindow::allowsAutomaticWindowTabbing(mtm)
        }
        None => false,
    }
}

/// The standard alert sound (e.g. the window limit is reached), instead of a notification.
pub fn beep() {
    objc2_app_kit::NSBeep();
}

// ---------------------------------------------------------------------------------------------
// Bundle identity
// ---------------------------------------------------------------------------------------------

/// True when this process runs from the SuryaDhana `.app` bundle (not `cargo test`, not a bare binary).
/// UNUserNotificationCenter raises an exception without a bundle, so it is never touched otherwise.
pub fn running_as_app_bundle() -> bool {
    let bundle = NSBundle::mainBundle();
    let id_ok = bundle
        .bundleIdentifier()
        .map(|id| id.to_string() == BUNDLE_ID)
        .unwrap_or(false);
    id_ok && bundle.bundlePath().to_string().ends_with(".app")
}

// ---------------------------------------------------------------------------------------------
// Notification authorization (UNUserNotificationCenter)
// ---------------------------------------------------------------------------------------------

/// This app's notification authorization as macOS reports it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NotifAuth {
    NotDetermined,
    Denied,
    /// authorized, provisional or ephemeral: banners are delivered.
    Authorized,
}

impl NotifAuth {
    /// UNAuthorizationStatus raw value -> state.
    pub fn from_raw(v: isize) -> NotifAuth {
        match v {
            1 => NotifAuth::Denied,
            2..=4 => NotifAuth::Authorized,
            _ => NotifAuth::NotDetermined,
        }
    }

    /// The Web Notification vocabulary of contract v1 (`shell_notification_permission`).
    pub fn as_permission(self) -> &'static str {
        match self {
            NotifAuth::Authorized => "granted",
            NotifAuth::Denied => "denied",
            NotifAuth::NotDetermined => "default",
        }
    }
}

fn notification_center() -> Option<Retained<AnyObject>> {
    if !running_as_app_bundle() {
        return None;
    }
    let cls = AnyClass::get(c"UNUserNotificationCenter")?;
    objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        // SAFETY: class method without arguments returning the shared center (autoreleased, retained here).
        let center: Option<Retained<AnyObject>> = unsafe { msg_send![cls, currentNotificationCenter] };
        center
    }))
    .ok()
    .flatten()
}

/// The current authorization (blocks the calling thread for at most `timeout`; never call it on the main
/// thread). None when unknown: not running from the app bundle, the API threw, or it timed out.
pub fn notification_authorization(timeout: Duration) -> Option<NotifAuth> {
    let center = notification_center()?;
    let (tx, rx) = mpsc::channel::<isize>();
    let block = RcBlock::new(move |settings: *mut AnyObject| {
        if settings.is_null() {
            return;
        }
        // SAFETY: `settings` is the non-null UNNotificationSettings the completion handler receives.
        let status: isize = unsafe { msg_send![settings, authorizationStatus] };
        let _ = tx.send(status);
    });
    let sent = objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        // SAFETY: documented selector; the block matches `void (^)(UNNotificationSettings *)`.
        let _: () = unsafe { msg_send![&*center, getNotificationSettingsWithCompletionHandler: &*block] };
    }));
    if sent.is_err() {
        return None;
    }
    rx.recv_timeout(timeout).ok().map(NotifAuth::from_raw)
}

/// Ask macOS for permission (alert + sound + badge). Shows the system prompt only while the state is
/// not determined; afterwards it returns at once. Returns the resulting state (None when unknown).
pub fn request_notification_authorization(timeout: Duration) -> Option<NotifAuth> {
    let center = notification_center()?;
    let (tx, rx) = mpsc::channel::<bool>();
    let block = RcBlock::new(move |granted: Bool, _err: *mut AnyObject| {
        let _ = tx.send(granted.as_bool());
    });
    // UNAuthorizationOptionBadge | Sound | Alert
    let options: usize = 0b111;
    let sent = objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        // SAFETY: documented selector; the block matches `void (^)(BOOL granted, NSError *error)`.
        let _: () =
            unsafe { msg_send![&*center, requestAuthorizationWithOptions: options, completionHandler: &*block] };
    }));
    if sent.is_err() {
        return None;
    }
    rx.recv_timeout(timeout).ok()?;
    notification_authorization(Duration::from_secs(2))
}

// ---------------------------------------------------------------------------------------------
// Login Items (Background Task Management)
// ---------------------------------------------------------------------------------------------

/// What System Settings › General › Login Items says about a legacy LaunchAgent plist.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LoginItemStatus {
    /// Allowed to run in the background.
    Enabled,
    /// The owner switched it off under "Allow in the Background": launchd will not start it.
    RequiresApproval,
    /// Not (yet) known to Background Task Management (e.g. written this session).
    NotRegistered,
    NotFound,
    Unknown,
}

/// `SMAppService.statusForLegacyURL:` (macOS 13+) for the plist at `plist`.
pub fn login_item_status(plist: &Path) -> LoginItemStatus {
    use objc2_service_management::{SMAppService, SMAppServiceStatus};
    let path = NSString::from_str(&plist.display().to_string());
    let url = NSURL::fileURLWithPath(&path);
    let status = objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        // SAFETY: class method taking a file URL; available since macOS 13 (the bundle's minimum).
        unsafe { SMAppService::statusForLegacyURL(&url) }
    }));
    match status {
        Ok(s) if s == SMAppServiceStatus::Enabled => LoginItemStatus::Enabled,
        Ok(s) if s == SMAppServiceStatus::RequiresApproval => LoginItemStatus::RequiresApproval,
        Ok(s) if s == SMAppServiceStatus::NotRegistered => LoginItemStatus::NotRegistered,
        Ok(s) if s == SMAppServiceStatus::NotFound => LoginItemStatus::NotFound,
        _ => LoginItemStatus::Unknown,
    }
}

/// [`login_item_status`] with a time limit (R-RUST-07: the XPC call to backgroundtaskmanagementd is
/// unbounded and runs on the main thread when Launch at Login is toggled). It runs on a helper thread; when it
/// does not answer within `timeout` the LAST known status is returned (Unknown before the first answer), and
/// no second call is started while one is still waiting.
pub fn login_item_status_bounded(plist: &Path, timeout: Duration) -> LoginItemStatus {
    use std::sync::atomic::{AtomicBool, Ordering};
    use std::sync::Mutex;
    static LAST: Mutex<Option<LoginItemStatus>> = Mutex::new(None);
    static WAITING: AtomicBool = AtomicBool::new(false);
    let last = || {
        LAST.lock()
            .unwrap_or_else(|e| e.into_inner())
            .unwrap_or(LoginItemStatus::Unknown)
    };
    if WAITING.swap(true, Ordering::SeqCst) {
        return last();
    }
    let (tx, rx) = mpsc::channel();
    let p = plist.to_path_buf();
    let spawned = std::thread::Builder::new()
        .name("login-item-status".into())
        .spawn(move || {
            let s = login_item_status(&p);
            *LAST.lock().unwrap_or_else(|e| e.into_inner()) = Some(s);
            WAITING.store(false, Ordering::SeqCst);
            let _ = tx.send(s);
        });
    if spawned.is_err() {
        WAITING.store(false, Ordering::SeqCst);
        return last();
    }
    rx.recv_timeout(timeout).unwrap_or_else(|_| last())
}

/// Open System Settings › General › Login Items.
pub fn open_login_items_settings() {
    let _ = objc2::exception::catch(|| {
        // SAFETY: class method without arguments.
        unsafe { objc2_service_management::SMAppService::openSystemSettingsLoginItems() }
    });
}

// ---------------------------------------------------------------------------------------------
// Files: quarantine, free space
// ---------------------------------------------------------------------------------------------

const QUARANTINE_XATTR: &CStr = c"com.apple.quarantine";

/// Tag an open file with `com.apple.quarantine` (no path lookup: immune to a swap of the path).
pub fn set_quarantine_fd(fd: std::os::fd::RawFd, value: &str) -> std::io::Result<()> {
    // SAFETY: valid fd, NUL-terminated name, value pointer/length from a live &str.
    let rc = unsafe { libc::fsetxattr(fd, QUARANTINE_XATTR.as_ptr(), value.as_ptr().cast(), value.len(), 0, 0) };
    if rc == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

/// Tag a path with `com.apple.quarantine` without following a final symlink.
pub fn set_quarantine_path(path: &Path, value: &str) -> std::io::Result<()> {
    let c = CString::new(path.as_os_str().as_bytes())?;
    // SAFETY: NUL-terminated path and name; value pointer/length from a live &str.
    let rc = unsafe {
        libc::setxattr(
            c.as_ptr(),
            QUARANTINE_XATTR.as_ptr(),
            value.as_ptr().cast(),
            value.len(),
            0,
            libc::XATTR_NOFOLLOW,
        )
    };
    if rc == 0 {
        Ok(())
    } else {
        Err(std::io::Error::last_os_error())
    }
}

/// The `com.apple.quarantine` value of a path, if any (self-test and unit tests).
pub fn quarantine_of(path: &Path) -> Option<String> {
    let c = CString::new(path.as_os_str().as_bytes()).ok()?;
    let mut buf = [0u8; 256];
    // SAFETY: NUL-terminated strings; the buffer length is passed.
    let n = unsafe {
        libc::getxattr(
            c.as_ptr(),
            QUARANTINE_XATTR.as_ptr(),
            buf.as_mut_ptr().cast(),
            buf.len(),
            0,
            libc::XATTR_NOFOLLOW,
        )
    };
    (n > 0).then(|| String::from_utf8_lossy(&buf[..n as usize]).to_string())
}

/// Free bytes available to this user on the volume holding `dir`.
pub fn free_bytes(dir: &Path) -> Option<u64> {
    let c = CString::new(dir.as_os_str().as_bytes()).ok()?;
    // SAFETY: zeroed POD out-parameter, NUL-terminated path.
    let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
    let rc = unsafe { libc::statvfs(c.as_ptr(), &mut st) };
    (rc == 0).then(|| (st.f_bavail as u64).saturating_mul(st.f_frsize))
}

// ---------------------------------------------------------------------------------------------
// Processes and accounts
// ---------------------------------------------------------------------------------------------

/// `p_stat` of a zombie (exited, not yet reaped) process (<sys/proc.h> SZOMB).
const SZOMB: u32 = 5;

fn bsd_info(pid: i32) -> Option<libc::proc_bsdinfo> {
    // SAFETY: zeroed POD out-parameter of the size passed.
    let mut info: libc::proc_bsdinfo = unsafe { std::mem::zeroed() };
    let size = std::mem::size_of::<libc::proc_bsdinfo>() as libc::c_int;
    let n = unsafe {
        libc::proc_pidinfo(
            pid,
            libc::PROC_PIDTBSDINFO,
            0,
            (&mut info as *mut libc::proc_bsdinfo).cast(),
            size,
        )
    };
    (n == size).then_some(info)
}

/// Owner uid of `pid` (None: gone, or another user's process the caller may not inspect).
pub fn proc_uid(pid: i32) -> Option<u32> {
    bsd_info(pid).map(|i| i.pbi_uid)
}

/// Owner uid and kernel start time (`pbi_start_tvsec`, `pbi_start_tvusec`) of a LIVE `pid` (None: gone, a
/// zombie, or another user's process the caller may not inspect). pid + start time names one process.
pub fn proc_identity(pid: i32) -> Option<(u32, (u64, u64))> {
    bsd_info(pid)
        .filter(|i| i.pbi_status != SZOMB)
        .map(|i| (i.pbi_uid, (i.pbi_start_tvsec, i.pbi_start_tvusec)))
}

/// Executable path of `pid`.
pub fn proc_exe(pid: i32) -> Option<PathBuf> {
    let mut buf = vec![0u8; libc::PROC_PIDPATHINFO_MAXSIZE as usize];
    // SAFETY: the buffer and its length are passed together.
    let n = unsafe { libc::proc_pidpath(pid, buf.as_mut_ptr().cast(), buf.len() as u32) };
    if n <= 0 {
        return None;
    }
    buf.truncate(n as usize);
    Some(PathBuf::from(std::ffi::OsStr::from_bytes(&buf)))
}

/// `kern.boottime`: the boot's epoch seconds and its microseconds field (`{ sec = 1792906041, usec = 658471 }`).
/// Both are kept because `scripts/stack_watchdog.sh` stamps its lock owner file with whichever of the two its
/// `boot_epoch()` extracts (see `stack::owner_boot_matches`).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BootTime {
    pub sec: u64,
    pub usec: u64,
}

/// System boot time from `kern.boottime`.
pub fn boot_time() -> Option<BootTime> {
    let mut tv: libc::timeval = unsafe { std::mem::zeroed() };
    let mut len = std::mem::size_of::<libc::timeval>();
    // SAFETY: NUL-terminated name; out-buffer and its length are passed together; no new value is set.
    let rc = unsafe {
        libc::sysctlbyname(
            c"kern.boottime".as_ptr(),
            (&mut tv as *mut libc::timeval).cast(),
            &mut len,
            std::ptr::null_mut(),
            0,
        )
    };
    (rc == 0 && tv.tv_sec > 0).then_some(BootTime {
        sec: tv.tv_sec as u64,
        usec: tv.tv_usec.max(0) as u64,
    })
}

/// System boot time (epoch seconds) from `kern.boottime`.
pub fn boot_time_secs() -> Option<u64> {
    boot_time().map(|b| b.sec)
}

/// The command line of a process of this user (its argv joined by spaces, what `ps -o command=` prints), read
/// with `sysctl KERN_PROCARGS2` (round 4b, SECREL-05: the watchdog lock's owner must be the watchdog script, the
/// same check as its own `lock_is_stale`, so a reused pid never passes). None when it cannot be read: the
/// process is gone or a zombie, or it belongs to another user.
pub fn proc_cmdline(pid: i32) -> Option<String> {
    if pid <= 0 {
        return None;
    }
    let mut argmax: libc::c_int = 0;
    let mut len = std::mem::size_of::<libc::c_int>();
    let mut mib = [libc::CTL_KERN, libc::KERN_ARGMAX];
    // SAFETY: a 2-element MIB; the out-buffer and its length are passed together; no new value is set.
    let rc = unsafe {
        libc::sysctl(
            mib.as_mut_ptr(),
            2,
            (&mut argmax as *mut libc::c_int).cast(),
            &mut len,
            std::ptr::null_mut(),
            0,
        )
    };
    if rc != 0 || argmax <= 0 {
        return None;
    }
    let mut buf = vec![0u8; argmax as usize];
    let mut size = buf.len();
    let mut mib = [libc::CTL_KERN, libc::KERN_PROCARGS2, pid];
    // SAFETY: a 3-element MIB; the buffer and its length are passed together; no new value is set.
    let rc = unsafe {
        libc::sysctl(
            mib.as_mut_ptr(),
            3,
            buf.as_mut_ptr().cast(),
            &mut size,
            std::ptr::null_mut(),
            0,
        )
    };
    if rc != 0 {
        return None;
    }
    buf.truncate(size);
    parse_procargs2(&buf)
}

/// Pure: `KERN_PROCARGS2` layout = `int argc`, the executable path, NUL padding, then argc NUL-terminated
/// arguments (the environment follows). Returns the arguments joined by spaces.
pub fn parse_procargs2(buf: &[u8]) -> Option<String> {
    let argc = i32::from_ne_bytes(buf.get(..4)?.try_into().ok()?);
    if argc <= 0 {
        return None;
    }
    let rest = &buf[4..];
    let mut i = rest.iter().position(|&b| b == 0)?; // end of the executable path
    while i < rest.len() && rest[i] == 0 {
        i += 1;
    }
    let args: Vec<String> = rest[i..]
        .split(|&b| b == 0)
        .take(argc as usize)
        .map(|a| String::from_utf8_lossy(a).into_owned())
        .collect();
    (!args.is_empty()).then(|| args.join(" "))
}

// ---------------------------------------------------------------------------------------------
// Printing and the menu bar (round 4b, R9)
// ---------------------------------------------------------------------------------------------

/// `NSEventModifierFlagCommand` / `…Control` / `…Option` / `…Shift`.
pub const MOD_COMMAND: usize = 1 << 20;
pub const MOD_CONTROL: usize = 1 << 18;
pub const MOD_OPTION: usize = 1 << 19;
pub const MOD_SHIFT: usize = 1 << 17;

/// Does the NSWindow that holds this WKWebView show a sheet right now (a print panel, a save panel)? Main
/// thread only (`wkwebview` from `with_webview`). None when the view has no window.
pub fn webview_window_has_sheet(wkwebview: *mut std::ffi::c_void) -> Option<bool> {
    if wkwebview.is_null() {
        return None;
    }
    // SAFETY: a live WKWebView pointer from tauri's with_webview on the main thread; `window` and
    // `attachedSheet` are documented nullable properties, read inside an Objective-C exception guard.
    let obj = unsafe { &*(wkwebview as *const AnyObject) };
    objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        let win: Option<Retained<AnyObject>> = unsafe { msg_send![obj, window] };
        let win = win?;
        let sheet: Option<Retained<AnyObject>> = unsafe { msg_send![&*win, attachedSheet] };
        Some(sheet.is_some())
    }))
    .ok()
    .flatten()
}

/// Self-test only: end the sheet shown on this WKWebView's window with Cancel (`NSModalResponseCancel` = 0,
/// what the print panel's Cancel button sends: the print operation ends, nothing is printed). Returns whether
/// a sheet was there. Main thread only.
pub fn cancel_webview_window_sheet(wkwebview: *mut std::ffi::c_void) -> bool {
    if wkwebview.is_null() {
        return false;
    }
    let Some(mtm) = MainThreadMarker::new() else {
        return false;
    };
    let app = objc2_app_kit::NSApplication::sharedApplication(mtm);
    // SAFETY: as in webview_window_has_sheet; `endSheet:returnCode:` is the documented way to end a sheet begun
    // with the legacy or the block-based API, and orderOut: then removes it; all inside an exception guard.
    let obj = unsafe { &*(wkwebview as *const AnyObject) };
    objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        let win: Option<Retained<AnyObject>> = unsafe { msg_send![obj, window] };
        let Some(win) = win else { return false };
        let sheet: Option<Retained<AnyObject>> = unsafe { msg_send![&*win, attachedSheet] };
        let Some(sheet) = sheet else { return false };
        let cancel: isize = 0;
        let _: () = unsafe { msg_send![&*app, endSheet: &*sheet, returnCode: cancel] };
        let nil: *const AnyObject = std::ptr::null();
        let _: () = unsafe { msg_send![&*sheet, orderOut: nil] };
        true
    }))
    .unwrap_or(false)
}

#[link(name = "AppKit", kind = "framework")]
extern "C" {
    static NSPrintSaveJob: *const AnyObject;
    static NSPrintJobSavingURL: *const AnyObject;
}

/// Self-test only (belt and braces for the print check): make the app's shared print info SAVE the job as a
/// PDF at `pdf` instead of sending it to a printer, so even a confirmed print panel never reaches paper. wry
/// prints with `NSPrintInfo.sharedPrintInfo`. Main thread only. Returns whether it was set.
pub fn selftest_print_to_file(pdf: &Path) -> bool {
    if MainThreadMarker::new().is_none() {
        return false;
    }
    let Some(path) = pdf.to_str() else { return false };
    let Some(cls) = AnyClass::get(c"NSPrintInfo") else {
        return false;
    };
    let ns_path = NSString::from_str(path);
    let url = NSURL::fileURLWithPath(&ns_path);
    objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        // SAFETY: documented class method / property / NSMutableDictionary setter; AppKit's own exported
        // constants (non-null NSString globals); inside an Objective-C exception guard.
        let info: Option<Retained<AnyObject>> = unsafe { msg_send![cls, sharedPrintInfo] };
        let Some(info) = info else { return false };
        let (job, key) = unsafe { (NSPrintSaveJob, NSPrintJobSavingURL) };
        if job.is_null() || key.is_null() {
            return false;
        }
        let _: () = unsafe { msg_send![&*info, setJobDisposition: job] };
        let dict: Option<Retained<AnyObject>> = unsafe { msg_send![&*info, dictionary] };
        let Some(dict) = dict else { return false };
        let _: () = unsafe { msg_send![&*dict, setObject: &*url, forKey: key] };
        true
    }))
    .unwrap_or(false)
}

/// Every key equivalent of the app's menu bar: `(item title, key, modifier mask)`, submenus included (self-test:
/// ⌘P is Print…, nothing takes ⌘F so the page's find bar gets it). Main thread only; empty elsewhere.
pub fn menu_key_equivalents() -> Vec<(String, String, usize)> {
    let Some(mtm) = MainThreadMarker::new() else {
        return vec![];
    };
    let app = objc2_app_kit::NSApplication::sharedApplication(mtm);
    let mut out = vec![];
    let _ = objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        // SAFETY: documented NSApplication / NSMenu / NSMenuItem getters, inside an exception guard.
        let menu: Option<Retained<AnyObject>> = unsafe { msg_send![&*app, mainMenu] };
        if let Some(m) = menu {
            walk_menu(&m, &mut out, 0);
        }
    }));
    out
}

fn walk_menu(menu: &AnyObject, out: &mut Vec<(String, String, usize)>, depth: usize) {
    if depth > 6 {
        return;
    }
    // SAFETY: called from menu_key_equivalents on the main thread inside its exception guard; `menu` is an
    // NSMenu, every getter is documented and nullable results are Options.
    let n: isize = unsafe { msg_send![menu, numberOfItems] };
    for i in 0..n.max(0) {
        let item: Option<Retained<AnyObject>> = unsafe { msg_send![menu, itemAtIndex: i] };
        let Some(item) = item else { continue };
        let title: Option<Retained<NSString>> = unsafe { msg_send![&*item, title] };
        let key: Option<Retained<NSString>> = unsafe { msg_send![&*item, keyEquivalent] };
        let mask: usize = unsafe { msg_send![&*item, keyEquivalentModifierMask] };
        let key = key.map(|k| k.to_string()).unwrap_or_default();
        if !key.is_empty() {
            out.push((title.map(|t| t.to_string()).unwrap_or_default(), key, mask));
        }
        let sub: Option<Retained<AnyObject>> = unsafe { msg_send![&*item, submenu] };
        if let Some(sub) = sub {
            walk_menu(&sub, out, depth + 1);
        }
    }
}

/// Pure: does a key equivalent mean plain ⌘F (Command only, the letter f in either case)?
pub fn is_plain_cmd_f(key: &str, mask: usize) -> bool {
    key.eq_ignore_ascii_case("f") && mask & (MOD_COMMAND | MOD_CONTROL | MOD_OPTION | MOD_SHIFT) == MOD_COMMAND
}

/// Start `program` with `args` as a DETACHED child (round 3, crash-relaunch guard): its own process group
/// (no terminal hang-up reaches it), stdin/stdout/stderr = /dev/null, and NO other inherited file descriptor
/// (`POSIX_SPAWN_CLOEXEC_DEFAULT`): in particular never the single-instance socket, whose inheritance would
/// make every later launch "hand off" to a process that is not the app. Returns the child's pid. The child
/// is not waited for (it outlives this process when the app crashes; launchd reaps it).
pub fn spawn_detached(program: &Path, args: &[&std::ffi::OsStr]) -> std::io::Result<i32> {
    use std::io::{Error, ErrorKind};
    let prog = CString::new(program.as_os_str().as_bytes()).map_err(|_| Error::from(ErrorKind::InvalidInput))?;
    let mut owned = vec![prog.clone()];
    for a in args {
        owned.push(CString::new(a.as_bytes()).map_err(|_| Error::from(ErrorKind::InvalidInput))?);
    }
    let mut argv: Vec<*mut libc::c_char> = owned.iter().map(|c| c.as_ptr() as *mut libc::c_char).collect();
    argv.push(std::ptr::null_mut());
    let envp: Vec<CString> = std::env::vars_os()
        .filter_map(|(k, v)| {
            let mut kv = k.as_bytes().to_vec();
            kv.push(b'=');
            kv.extend_from_slice(v.as_bytes());
            CString::new(kv).ok()
        })
        .collect();
    let mut envv: Vec<*mut libc::c_char> = envp.iter().map(|c| c.as_ptr() as *mut libc::c_char).collect();
    envv.push(std::ptr::null_mut());
    let devnull = c"/dev/null";
    // SAFETY: attr / file actions are initialised before use and destroyed on every path; every pointer passed
    // (argv, envp, path strings) outlives the posix_spawn call; flags are documented Apple values.
    unsafe {
        let mut attr: libc::posix_spawnattr_t = std::ptr::null_mut();
        let mut fa: libc::posix_spawn_file_actions_t = std::ptr::null_mut();
        if libc::posix_spawnattr_init(&mut attr) != 0 {
            return Err(Error::last_os_error());
        }
        if libc::posix_spawn_file_actions_init(&mut fa) != 0 {
            libc::posix_spawnattr_destroy(&mut attr);
            return Err(Error::last_os_error());
        }
        let flags = (libc::POSIX_SPAWN_CLOEXEC_DEFAULT | libc::POSIX_SPAWN_SETPGROUP) as libc::c_short;
        let mut rc = libc::posix_spawnattr_setflags(&mut attr, flags);
        if rc == 0 {
            rc = libc::posix_spawnattr_setpgroup(&mut attr, 0);
        }
        for (fd, oflag) in [(0, libc::O_RDONLY), (1, libc::O_WRONLY), (2, libc::O_WRONLY)] {
            if rc == 0 {
                rc = libc::posix_spawn_file_actions_addopen(&mut fa, fd, devnull.as_ptr(), oflag, 0);
            }
        }
        let mut pid: libc::pid_t = 0;
        if rc == 0 {
            rc = libc::posix_spawn(&mut pid, prog.as_ptr(), &fa, &attr, argv.as_ptr(), envv.as_ptr());
        }
        libc::posix_spawn_file_actions_destroy(&mut fa);
        libc::posix_spawnattr_destroy(&mut attr);
        if rc != 0 {
            return Err(Error::from_raw_os_error(rc));
        }
        Ok(pid)
    }
}

/// `-[NSApplication disableRelaunchOnLogin]` (R-RUST-05): while the Launch-at-Login job owns relaunching,
/// macOS's "Reopen windows when logging back in" must not start a second, unsupervised copy through
/// LaunchServices that races the login job. Main thread only (false elsewhere).
pub fn disable_relaunch_on_login() -> bool {
    match MainThreadMarker::new() {
        Some(mtm) => {
            let app = objc2_app_kit::NSApplication::sharedApplication(mtm);
            objc2::exception::catch(std::panic::AssertUnwindSafe(|| app.disableRelaunchOnLogin())).is_ok()
        }
        None => false,
    }
}

/// The current URL of a WKWebView, nil-safe (round 3). wry 0.57.1's `url_from_webview` (behind tauri's
/// `WebviewWindow::url()`) does `webview.URL().unwrap()`, and WebKit resets `URL` to nil when the page's WebContent
/// process ends: every `url()` call on a crashed window then panicked the MAIN thread and the whole app ended
/// (found by the round-3 self-test that kills the content process). None = no URL (crashed, or nothing loaded).
/// Main thread only (`wkwebview` from `with_webview`).
pub fn wkwebview_url(wkwebview: *mut std::ffi::c_void) -> Option<String> {
    if wkwebview.is_null() {
        return None;
    }
    // SAFETY: a live WKWebView pointer from tauri's with_webview on the main thread; `URL` is a documented
    // nullable property (Option), read inside an Objective-C exception guard.
    let obj = unsafe { &*(wkwebview as *const AnyObject) };
    objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        let url: Option<Retained<NSURL>> = unsafe { msg_send![obj, URL] };
        url.and_then(|u| u.absoluteString()).map(|s| s.to_string())
    }))
    .ok()
    .flatten()
}

/// Self-test only: the pid of a WKWebView's current WebContent process (WebKit SPI `_webProcessIdentifier`,
/// the property Safari's and Playwright's tooling read). `wkwebview` is the `WKWebView *` tauri's
/// `PlatformWebview::inner()` returns. None when unavailable.
pub fn web_content_pid(wkwebview: *mut std::ffi::c_void) -> Option<i32> {
    if wkwebview.is_null() {
        return None;
    }
    // SAFETY: a live WKWebView pointer from tauri on the main thread; the selector is checked first and the
    // call runs inside an Objective-C exception guard.
    let obj = unsafe { &*(wkwebview as *const AnyObject) };
    objc2::exception::catch(std::panic::AssertUnwindSafe(|| {
        let sel = objc2::sel!(_webProcessIdentifier);
        let responds: bool = unsafe { msg_send![obj, respondsToSelector: sel] };
        if !responds {
            return None;
        }
        let pid: libc::pid_t = unsafe { msg_send![obj, _webProcessIdentifier] };
        (pid > 0).then_some(pid)
    }))
    .ok()
    .flatten()
}

/// This user's id.
pub fn uid() -> u32 {
    // SAFETY: getuid has no preconditions and cannot fail.
    unsafe { libc::getuid() }
}

/// The account's home directory from the user database (ignores `$HOME`, which drills override).
pub fn account_home() -> Option<PathBuf> {
    let mut pwd: libc::passwd = unsafe { std::mem::zeroed() };
    let mut buf = vec![0 as libc::c_char; 4096];
    let mut result: *mut libc::passwd = std::ptr::null_mut();
    // SAFETY: all out-parameters are valid for the call; the buffer length is passed.
    let rc = unsafe { libc::getpwuid_r(uid(), &mut pwd, buf.as_mut_ptr(), buf.len(), &mut result) };
    if rc != 0 || result.is_null() || pwd.pw_dir.is_null() {
        return None;
    }
    // SAFETY: pw_dir points into `buf`, NUL-terminated by getpwuid_r.
    let dir = unsafe { CStr::from_ptr(pwd.pw_dir) };
    Some(PathBuf::from(std::ffi::OsStr::from_bytes(dir.to_bytes())))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn auth_mapping() {
        assert_eq!(NotifAuth::from_raw(0), NotifAuth::NotDetermined);
        assert_eq!(NotifAuth::from_raw(1), NotifAuth::Denied);
        for v in [2, 3, 4] {
            assert_eq!(NotifAuth::from_raw(v), NotifAuth::Authorized);
        }
        assert_eq!(NotifAuth::from_raw(99), NotifAuth::NotDetermined);
        assert_eq!(NotifAuth::Authorized.as_permission(), "granted");
        assert_eq!(NotifAuth::Denied.as_permission(), "denied");
        assert_eq!(NotifAuth::NotDetermined.as_permission(), "default");
    }

    #[test]
    fn not_an_app_bundle_under_cargo_test() {
        // the test binary has no SuryaDhana bundle: the notification center is never touched
        assert!(!running_as_app_bundle());
        assert_eq!(notification_authorization(Duration::from_millis(10)), None);
    }

    #[test]
    fn quarantine_round_trip_and_nofollow() {
        let dir = tempfile::tempdir().unwrap();
        let f = dir.path().join("a.csv");
        std::fs::write(&f, b"x").unwrap();
        assert_eq!(quarantine_of(&f), None);
        set_quarantine_path(&f, "0083;00000001;SuryaDhana;").unwrap();
        assert_eq!(quarantine_of(&f).as_deref(), Some("0083;00000001;SuryaDhana;"));
        let g = dir.path().join("b.csv");
        let file = std::fs::File::create(&g).unwrap();
        use std::os::fd::AsRawFd;
        set_quarantine_fd(file.as_raw_fd(), "0083;00000002;SuryaDhana;").unwrap();
        assert!(quarantine_of(&g).unwrap().contains("SuryaDhana"));
        // a dangling symlink is tagged itself (XATTR_NOFOLLOW), never its target
        let link = dir.path().join("link.csv");
        std::os::unix::fs::symlink(dir.path().join("missing"), &link).unwrap();
        let _ = set_quarantine_path(&link, "0083;00000003;SuryaDhana;");
        assert!(!dir.path().join("missing").exists());
    }

    #[test]
    fn process_identity_of_self() {
        let me = std::process::id() as i32;
        assert_eq!(proc_uid(me), Some(uid()));
        let exe = proc_exe(me).unwrap();
        assert_eq!(
            exe.canonicalize().ok(),
            std::env::current_exe().unwrap().canonicalize().ok()
        );
        assert_eq!(proc_uid(-1), None);
        assert!(proc_exe(-1).is_none());
        assert!(proc_cmdline(-1).is_none());
        assert!(account_home().map(|h| h.is_absolute()).unwrap_or(false));
        assert!(free_bytes(Path::new("/")).unwrap_or(0) > 0);
    }

    #[test]
    fn command_lines_and_boot_time_are_read_like_ps_and_sysctl() {
        // a real child: what `ps -o command=` prints for it
        let mut child = std::process::Command::new("/bin/sleep").arg("7.25").spawn().unwrap();
        let pid = child.id() as i32;
        let mut seen = None;
        for _ in 0..50 {
            seen = proc_cmdline(pid);
            if seen.as_deref() == Some("/bin/sleep 7.25") {
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let ps = std::process::Command::new("/bin/ps")
            .args(["-o", "command=", "-p", &pid.to_string()])
            .output()
            .unwrap();
        assert_eq!(seen.as_deref(), Some("/bin/sleep 7.25"));
        assert_eq!(String::from_utf8_lossy(&ps.stdout).trim(), "/bin/sleep 7.25");
        child.kill().unwrap();
        child.wait().unwrap();
        assert_eq!(proc_cmdline(pid), None, "a reaped process has no command line");
        // the layout parser: argc, exec path, NUL padding, args, then the environment (never returned)
        let mut b = 2i32.to_ne_bytes().to_vec();
        b.extend_from_slice(b"/bin/bash\0\0\0\0/bin/bash\0/r/scripts/stack_watchdog.sh\0HOME=/x\0");
        assert_eq!(
            parse_procargs2(&b).as_deref(),
            Some("/bin/bash /r/scripts/stack_watchdog.sh")
        );
        assert_eq!(parse_procargs2(&[1, 0]), None);
        assert_eq!(parse_procargs2(&0i32.to_ne_bytes()), None);
        // kern.boottime: the same two numbers `sysctl -n kern.boottime` prints
        let b = boot_time().unwrap();
        let out = std::process::Command::new("/usr/sbin/sysctl")
            .args(["-n", "kern.boottime"])
            .output()
            .unwrap();
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(
            text.contains(&format!("sec = {},", b.sec)) && text.contains(&format!("usec = {} ", b.usec)),
            "{text} vs {b:?}"
        );
        assert_eq!(boot_time_secs(), Some(b.sec));
    }

    #[test]
    fn plain_cmd_f_is_told_from_the_full_screen_and_other_f_keys() {
        assert!(is_plain_cmd_f("f", MOD_COMMAND));
        assert!(is_plain_cmd_f("F", MOD_COMMAND));
        assert!(
            !is_plain_cmd_f("f", MOD_COMMAND | MOD_CONTROL),
            "⌃⌘F is Enter Full Screen"
        );
        assert!(!is_plain_cmd_f("f", MOD_COMMAND | MOD_SHIFT));
        assert!(!is_plain_cmd_f("f", MOD_COMMAND | MOD_OPTION));
        assert!(!is_plain_cmd_f("p", MOD_COMMAND));
        // device-dependent / function-key bits do not matter
        assert!(is_plain_cmd_f("f", MOD_COMMAND | (1 << 23)));
    }
}
