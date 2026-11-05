//! Build script: Tauri codegen + ACL, plus two values baked into the binary.
//!
//! * `SURYADHANA_BUILD`  - git sha7 of the repo at build time (env `SURYADHANA_GIT_SHA` wins, else
//!   `git rev-parse --short=7 HEAD`, else `unknown`). Exposed to every window as
//!   `window.__SURYADHANA_SHELL__.build`.
//! * `SURYADHANA_ROOT_DEFAULT` - default repo root for config.json (env `SURYADHANA_ROOT` wins, else
//!   the repo that contains this crate: `<repo>/desktop/src-tauri/../..`).
//! * `SURYADHANA_BUILD_ID` - `<sha7>[-dirty]-<src8>-<yyyymmddTHHMMZ>` (completeness-04): the git sha, a dirty
//!   flag (`git status --porcelain -- desktop scripts/build_desktop.sh` not empty), an FNV-1a hash of the shell's
//!   own sources (src/, boot/, Cargo.toml/lock, tauri.conf.json, capabilities) and the UTC build time (env
//!   `SURYADHANA_BUILD_TIME` = epoch seconds wins, for reproducible ids). Two different shell binaries never
//!   share it; About, the tray, `shell_info.build_id`, the boot page, the log and the self-test show it.
//!   Round 3 (R-RUST-08): a `--features devtools` build (Web Inspector on the IPC-granted origin) ends in
//!   `-devtools`, and a non-release profile in `-<profile>`, so neither can pass for a release build
//!   (`scripts/build_desktop.sh --install` refuses a `-devtools` id without `--force`).
//!
//! App commands are declared in an `AppManifest`, so Tauri autogenerates `allow-<command>` /
//! `deny-<command>` permissions and enforces the ACL on every app command: a command is callable only
//! from a window/URL whose capability grants it (capabilities/boot.json for the bundled boot page; the
//! remote terminal capability is added at runtime for the configured ui_url origin, see
//! src/windows.rs). Keep this list identical to the `generate_handler!` list in src/lib.rs.
use std::path::PathBuf;
use std::process::Command;

/// Every app command (shell_* = granted to the remote terminal origin; boot_*/stack_*/open_* = boot page only).
const APP_COMMANDS: &[&str] = &[
    // Contract v1: the 9 commands granted to the remote terminal origin.
    "shell_info",
    "shell_status",
    "shell_notify",
    "shell_notification_permission",
    "shell_request_notification_permission",
    "shell_save_download",
    "shell_open_external",
    "shell_new_window",
    "shell_set_title",
    // Boot-only commands (bundled tauri://localhost boot page).
    "boot_status",
    "stack_start",
    "stack_stop",
    "open_logs",
    "open_terminal",
];

fn git_sha7(repo: &PathBuf) -> String {
    if let Ok(v) = std::env::var("SURYADHANA_GIT_SHA") {
        let v: String = v.trim().chars().filter(|c| c.is_ascii_hexdigit()).take(7).collect();
        if v.len() == 7 {
            return v;
        }
    }
    Command::new("git")
        .args(["rev-parse", "--short=7", "HEAD"])
        .current_dir(repo)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| {
            String::from_utf8_lossy(&o.stdout)
                .trim()
                .chars()
                .take(7)
                .collect::<String>()
        })
        .filter(|s| s.len() == 7 && s.chars().all(|c| c.is_ascii_hexdigit()))
        .unwrap_or_else(|| "unknown".to_string())
}

/// The shell's own sources, relative to the crate dir (hashed into the build id; build.rs re-runs on change).
const SOURCES: &[&str] = &[
    "src",
    "../boot",
    "build.rs",
    "Cargo.toml",
    "Cargo.lock",
    "tauri.conf.json",
    "capabilities",
    "capabilities-runtime",
];

fn fnv1a(h: &mut u64, bytes: &[u8]) {
    for b in bytes {
        *h ^= u64::from(*b);
        *h = h.wrapping_mul(0x0100_0000_01b3);
    }
}

fn collect(dir: &std::path::Path, out: &mut Vec<PathBuf>) {
    if dir.is_file() {
        out.push(dir.to_path_buf());
        return;
    }
    if let Ok(rd) = std::fs::read_dir(dir) {
        for e in rd.flatten() {
            let p = e.path();
            let name = e.file_name().to_string_lossy().to_string();
            if name.starts_with('.') {
                continue;
            }
            if p.is_dir() {
                collect(&p, out);
            } else {
                out.push(p);
            }
        }
    }
}

/// 8 hex digits over (relative path, contents) of every source file, in sorted order.
fn source_hash(crate_dir: &std::path::Path) -> String {
    let mut files = vec![];
    for s in SOURCES {
        collect(&crate_dir.join(s), &mut files);
    }
    files.sort();
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for f in &files {
        let rel = f.strip_prefix(crate_dir).unwrap_or(f);
        fnv1a(&mut h, rel.to_string_lossy().as_bytes());
        fnv1a(&mut h, &[0]);
        fnv1a(&mut h, &std::fs::read(f).unwrap_or_default());
        fnv1a(&mut h, &[0xff]);
    }
    format!("{:08x}", (h >> 32) as u32 ^ h as u32)
}

/// Dirty = uncommitted (or untracked) changes in the shell's sources.
fn git_dirty(repo: &PathBuf) -> bool {
    Command::new("git")
        .args(["status", "--porcelain", "--", "desktop", "scripts/build_desktop.sh"])
        .current_dir(repo)
        .output()
        .ok()
        .filter(|o| o.status.success())
        .map(|o| !String::from_utf8_lossy(&o.stdout).trim().is_empty())
        .unwrap_or(true)
}

/// Days since 1970-01-01 -> (year, month, day) (proleptic Gregorian; H. Hinnant's civil_from_days).
fn civil(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    (yoe + era * 400 + i64::from(m <= 2), m, d)
}

/// `20261025T0930Z` for epoch seconds.
fn stamp(epoch: i64) -> String {
    let (y, m, d) = civil(epoch.div_euclid(86_400));
    let secs = epoch.rem_euclid(86_400);
    format!("{y:04}{m:02}{d:02}T{:02}{:02}Z", secs / 3600, (secs % 3600) / 60)
}

fn main() {
    println!("cargo:rerun-if-env-changed=SURYADHANA_GIT_SHA");
    println!("cargo:rerun-if-env-changed=SURYADHANA_ROOT");
    println!("cargo:rerun-if-env-changed=SURYADHANA_BUILD_TIME");
    for s in SOURCES {
        println!("cargo:rerun-if-changed={s}");
    }

    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let default_repo = manifest_dir
        .parent()
        .and_then(|p| p.parent())
        .map(PathBuf::from)
        .unwrap_or_else(|| manifest_dir.clone());
    let repo_root = std::env::var("SURYADHANA_ROOT")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or(default_repo);

    let sha = git_sha7(&repo_root);
    let git_head = repo_root.join(".git").join("HEAD");
    if git_head.is_file() {
        println!("cargo:rerun-if-changed={}", git_head.display());
    }
    let epoch = std::env::var("SURYADHANA_BUILD_TIME")
        .ok()
        .and_then(|v| v.trim().parse::<i64>().ok())
        .unwrap_or_else(|| {
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_secs() as i64)
                .unwrap_or(0)
        });
    // R-RUST-08: the id carries the feature set and profile that change what the binary allows
    let devtools = std::env::var_os("CARGO_FEATURE_DEVTOOLS").is_some();
    let profile = std::env::var("PROFILE").unwrap_or_else(|_| "release".into());
    let build_id = format!(
        "{sha}{}-{}-{}{}{}",
        if git_dirty(&repo_root) { "-dirty" } else { "" },
        source_hash(&manifest_dir),
        stamp(epoch),
        if devtools { "-devtools" } else { "" },
        if profile == "release" {
            String::new()
        } else {
            format!("-{profile}")
        }
    );
    println!("cargo:rustc-env=SURYADHANA_BUILD={sha}");
    println!("cargo:rustc-env=SURYADHANA_BUILD_ID={build_id}");
    println!("cargo:rustc-env=SURYADHANA_ROOT_DEFAULT={}", repo_root.display());

    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(APP_COMMANDS)),
    )
    .expect("tauri-build failed");
}
