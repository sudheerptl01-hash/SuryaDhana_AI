//! Port-squatting guard (C2-security-04, reworked in wave 2): before a window is given the terminal origin
//! (which holds the remote IPC grant), the shell checks WHO listens on the ui port, from kernel facts only.
//!
//! * The listeners are found in-process with libproc (`proc_listallpids` → `PROC_PIDLISTFDS` →
//!   `PROC_PIDFDSOCKETINFO`: TCP sockets in LISTEN state on the port, any local address, IPv4 or IPv6), the
//!   way `lsof -iTCP:<port> -sTCP:LISTEN` does it but without a child process. Each listener's owner uid and
//!   executable come from `proc_pidinfo` / `proc_pidpath`.
//! * Nothing on disk is read, stat'ed or canonicalized: in particular nothing under ~/Desktop, where the
//!   stack's venv lives (macOS privacy / TCC would prompt for, or silently deny, the app's own access).
//! * A non-root process cannot list another user's file descriptors, so another user's (or root's) listener
//!   is invisible. When no listener is visible the guard connects to the port once and lists again: the
//!   port answers but nobody visible holds it = a process of another account ([`Probe::invisible`]); the
//!   port is closed = ui-api is restarting (inconclusive).
//! * The verdict is [`crate::policy::listener_trust`]: same uid AND a CPython executable in a Homebrew or
//!   python.org install location (any patch version, so `brew upgrade` never makes the running ui-api look
//!   foreign). The caller ([`crate::health`]) runs this off the async runtime under a hard timeout, on EVERY
//!   fast poll that finds the port held (round 3, R-RUST-01: no cached pass, so a listener swapped between
//!   two polls is judged at the next poll, ≤ 5 s, ≤ 1 s while a window waits).
//! * A live listener of this user whose executable was deleted is trusted only when it is exactly (pid +
//!   kernel start time) a process that passed before (round 3, R-RUST-02: the running ui-api survives
//!   `brew cleanup`; a squatter that unlinks its own binary is refused).

use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

use crate::macos;
use crate::policy::{listener_ids, listener_trust, Listener, ProcId, TrustFail};

// <sys/proc_info.h> (stable ABI used by lsof / Activity Monitor; offsets checked on macOS 26 with clang and
// by the unit tests below, which find a socket the test itself opened).
const PROC_PIDLISTFDS: libc::c_int = 1;
const PROX_FDTYPE_SOCKET: u32 = 2;
const PROC_PIDFDSOCKETINFO: libc::c_int = 3;
const SOCKINFO_TCP: i32 = 2;
const TSI_S_LISTEN: i32 = 1;
/// sizeof(struct socket_fdinfo)
const SOCKET_FDINFO_SIZE: usize = 792;
/// offsetof(struct socket_fdinfo, psi.soi_kind)
const OFF_SOI_KIND: usize = 256;
/// offsetof(struct socket_fdinfo, psi.soi_proto.pri_tcp.tcpsi_ini.insi_lport) (network byte order, low 16 bits)
const OFF_LPORT: usize = 268;
/// offsetof(struct socket_fdinfo, psi.soi_proto.pri_tcp.tcpsi_state)
const OFF_TCP_STATE: usize = 344;

#[repr(C, align(8))]
struct SocketFdInfo([u8; SOCKET_FDINFO_SIZE]);

fn i32_at(b: &[u8], off: usize) -> i32 {
    i32::from_ne_bytes([b[off], b[off + 1], b[off + 2], b[off + 3]])
}

/// Pure: does a raw `socket_fdinfo` describe a TCP socket listening on `port`?
pub fn is_tcp_listener_on(raw: &[u8], port: u16) -> bool {
    if raw.len() < SOCKET_FDINFO_SIZE {
        return false;
    }
    let lport = u16::from_be((i32_at(raw, OFF_LPORT) as u32 & 0xffff) as u16);
    i32_at(raw, OFF_SOI_KIND) == SOCKINFO_TCP && i32_at(raw, OFF_TCP_STATE) == TSI_S_LISTEN && lport == port
}

/// Every pid on the system (this user can see all pids; their file tables only when they are its own).
fn all_pids() -> Vec<i32> {
    let mut cap = 4096usize;
    loop {
        let mut buf = vec![0 as libc::c_int; cap];
        let bytes = (cap * std::mem::size_of::<libc::c_int>()) as libc::c_int;
        // SAFETY: the buffer and its size in bytes are passed together.
        let n = unsafe { libc::proc_listallpids(buf.as_mut_ptr().cast(), bytes) };
        if n <= 0 {
            return vec![];
        }
        let n = n as usize;
        if n < cap || cap >= 1 << 20 {
            buf.truncate(n.min(cap));
            return buf.into_iter().filter(|p| *p > 0).collect();
        }
        cap *= 4;
    }
}

/// Socket file descriptors of `pid` (empty when its file table is not ours to read).
fn socket_fds(pid: i32) -> Vec<i32> {
    let rec = std::mem::size_of::<libc::proc_fdinfo>();
    let mut cap = 256usize;
    loop {
        // SAFETY: zeroed POD records; the buffer and its size in bytes are passed together.
        let mut buf: Vec<libc::proc_fdinfo> = vec![unsafe { std::mem::zeroed() }; cap];
        let bytes = (cap * rec) as libc::c_int;
        let n = unsafe { libc::proc_pidinfo(pid, PROC_PIDLISTFDS, 0, buf.as_mut_ptr().cast(), bytes) };
        if n <= 0 {
            return vec![];
        }
        let got = n as usize / rec;
        // a full buffer may have been truncated: grow and ask again (bounded)
        if got < cap || cap >= 1 << 16 {
            return buf[..got.min(cap)]
                .iter()
                .filter(|f| f.proc_fdtype == PROX_FDTYPE_SOCKET)
                .map(|f| f.proc_fd)
                .collect();
        }
        cap *= 4;
    }
}

fn listens_on(pid: i32, fd: i32, port: u16) -> bool {
    let mut info = SocketFdInfo([0u8; SOCKET_FDINFO_SIZE]);
    // SAFETY: an 8-aligned buffer of exactly sizeof(struct socket_fdinfo) bytes is passed with that size.
    let n = unsafe {
        libc::proc_pidfdinfo(
            pid,
            fd,
            PROC_PIDFDSOCKETINFO,
            info.0.as_mut_ptr().cast(),
            SOCKET_FDINFO_SIZE as libc::c_int,
        )
    };
    n as usize == SOCKET_FDINFO_SIZE && is_tcp_listener_on(&info.0, port)
}

/// Pids of this user's processes with a TCP socket listening on `port` (any local address).
pub fn listening_pids(port: u16) -> Vec<i32> {
    let mut out: Vec<i32> = all_pids()
        .into_iter()
        .filter(|&pid| socket_fds(pid).into_iter().any(|fd| listens_on(pid, fd, port)))
        .collect();
    out.sort_unstable();
    out.dedup();
    out
}

/// The visible listeners on `port` with owner, kernel start time and executable.
///
/// Round 3 (R-RUST-02): when the executable cannot be read, the guard first makes sure the SAME process
/// (pid + start time, not a zombie) is alive and still holds the listening socket. Only then is it reported
/// with its uid (a live process whose executable was deleted: [`TrustFail::Unverifiable`] unless pinned);
/// a process that exited mid-check is reported without a uid (inconclusive, never a refusal).
pub fn listeners(port: u16) -> Vec<Listener> {
    listening_pids(port)
        .into_iter()
        .map(|pid| {
            let id = macos::proc_identity(pid);
            let exe = macos::proc_exe(pid);
            let alive = match (id, &exe) {
                (Some(_), Some(_)) => true,
                (Some(first), None) => {
                    macos::proc_identity(pid) == Some(first)
                        && socket_fds(pid).into_iter().any(|fd| listens_on(pid, fd, port))
                }
                (None, _) => false,
            };
            let (uid, start) = match id {
                Some((u, s)) if alive => (Some(u), Some(s)),
                _ => (None, None),
            };
            Listener { pid, uid, exe, start }
        })
        .collect()
}

/// What one probe of the port found.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Probe {
    pub listeners: Vec<Listener>,
    /// No visible listener, yet the port accepted a connection: a process of another account holds it.
    pub invisible: bool,
}

/// Probe `port` (blocking, ~10–30 ms; run it off the async runtime).
pub fn probe(port: u16) -> Probe {
    let first = listeners(port);
    if !first.is_empty() {
        return Probe {
            listeners: first,
            invisible: false,
        };
    }
    let addr = SocketAddr::from(([127, 0, 0, 1], port));
    let answers = TcpStream::connect_timeout(&addr, Duration::from_millis(500)).is_ok();
    // list again: a ui-api that bound the port between the two looks is judged normally
    let again = listeners(port);
    Probe {
        invisible: answers && again.is_empty(),
        listeners: again,
    }
}

/// One verification: the verdict, and on a pass the exact identities of the listeners (the caller keeps them
/// as pins: a listener verified once stays trusted while the SAME process runs, even after its executable is
/// removed, e.g. by `brew cleanup`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Verdict {
    pub result: Result<String, TrustFail>,
    pub ids: Vec<ProcId>,
}

/// Verify the ui port: probe it and apply the trust rule (blocking). `pinned` = listeners verified before.
pub fn verify_port(port: u16, extra_prefixes: &[std::path::PathBuf], pinned: &[ProcId]) -> Verdict {
    let p = probe(port);
    let result = listener_trust(&p.listeners, p.invisible, macos::uid(), extra_prefixes, pinned);
    let ids = if result.is_ok() {
        listener_ids(&p.listeners)
    } else {
        vec![]
    };
    Verdict { result, ids }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn raw_socket_info_decoding() {
        let mut raw = vec![0u8; SOCKET_FDINFO_SIZE];
        raw[OFF_SOI_KIND..OFF_SOI_KIND + 4].copy_from_slice(&SOCKINFO_TCP.to_ne_bytes());
        raw[OFF_TCP_STATE..OFF_TCP_STATE + 4].copy_from_slice(&TSI_S_LISTEN.to_ne_bytes());
        let lport = (8010u16.to_be() as u32) as i32;
        raw[OFF_LPORT..OFF_LPORT + 4].copy_from_slice(&lport.to_ne_bytes());
        assert!(is_tcp_listener_on(&raw, 8010));
        assert!(!is_tcp_listener_on(&raw, 8011));
        assert!(!is_tcp_listener_on(&raw[..100], 8010), "short buffer");
        raw[OFF_TCP_STATE..OFF_TCP_STATE + 4].copy_from_slice(&4i32.to_ne_bytes()); // ESTABLISHED
        assert!(!is_tcp_listener_on(&raw, 8010));
    }

    #[test]
    fn listeners_this_test_owns_are_found_v4_and_v6() {
        let v4 = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = v4.local_addr().unwrap().port();
        let found = listeners(port);
        assert_eq!(found.len(), 1, "{found:?}");
        assert_eq!(found[0].pid, std::process::id() as i32);
        assert_eq!(found[0].uid, Some(macos::uid()));
        assert!(found[0].exe.is_some());
        // a client connection to it is not a listener
        let _c = TcpStream::connect(("127.0.0.1", port)).unwrap();
        assert_eq!(listening_pids(port), vec![std::process::id() as i32]);
        if let Ok(v6) = std::net::TcpListener::bind("[::1]:0") {
            let p6 = v6.local_addr().unwrap().port();
            assert_eq!(listening_pids(p6), vec![std::process::id() as i32], "IPv6 listener");
        }
    }

    #[test]
    fn a_listener_is_judged_by_its_executable_never_by_files() {
        let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        // the test binary is not a CPython: foreign, and the pid is named
        let e = verify_port(port, &[], &[]).result.unwrap_err();
        assert!(matches!(e, TrustFail::Foreign(_)), "{e:?}");
        assert!(e.message().contains(&format!("pid {}", std::process::id())), "{e:?}");
        // an extra trusted prefix (config trusted_python_prefixes) covering the test binary makes it trusted,
        // and the pass names this exact process (pid + kernel start time) for the pins
        let dir = std::env::current_exe().unwrap().parent().unwrap().to_path_buf();
        let v = verify_port(port, std::slice::from_ref(&dir), &[]);
        assert!(v.result.is_ok(), "{v:?}");
        assert_eq!(v.ids.len(), 1);
        assert_eq!(v.ids[0].pid, std::process::id() as i32);
        let me = macos::proc_identity(std::process::id() as i32).unwrap();
        assert_eq!(v.ids[0].start, me.1);
        drop(l);
        // nothing listening and the port closed: inconclusive (never evicts, never Foreign)
        let p = probe(port);
        assert!(p.listeners.is_empty() && !p.invisible, "{p:?}");
        let v = verify_port(port, &[dir], &[]);
        assert!(
            matches!(v.result, Err(TrustFail::Unknown(_))) && v.ids.is_empty(),
            "{v:?}"
        );
        let _ = PathBuf::new();
    }

    #[test]
    fn a_live_listener_whose_executable_was_deleted_is_unverifiable_unless_pinned() {
        // R-RUST-02, end to end with real processes: a compiled listener that unlinks its own binary after bind
        let Some(t) = testutil::Squatter::compile() else {
            eprintln!("skipped: no C compiler (xcode-select --install)");
            return;
        };
        let port = testutil::free_port();
        let mut first = t.spawn(port, false);
        // readable executable inside a trusted prefix: a pass that pins this exact process
        let v = verify_port(port, std::slice::from_ref(&t.dir), &[]);
        assert!(v.result.is_ok(), "{v:?}");
        let pins = v.ids.clone();
        assert_eq!(pins.len(), 1);
        // the same process after its executable is removed (brew cleanup of the running keg): still trusted
        // through its pin, refused without it
        std::fs::remove_file(&t.exe).unwrap();
        let found = listeners(port);
        assert_eq!(found.len(), 1, "{found:?}");
        assert!(
            found[0].exe.is_none() && found[0].uid == Some(macos::uid()),
            "{found:?}"
        );
        let v = verify_port(port, std::slice::from_ref(&t.dir), &pins);
        assert!(
            v.result
                .as_ref()
                .map(|d| d.contains("verified earlier"))
                .unwrap_or(false),
            "{v:?}"
        );
        let v = verify_port(port, std::slice::from_ref(&t.dir), &[]);
        assert!(matches!(v.result, Err(TrustFail::Unverifiable(_))), "{v:?}");
        first.kill();
        // a NEW process (another pid) that unlinked its own binary: the old pin does not cover it
        let t2 = testutil::Squatter::compile().unwrap();
        let _second = t2.spawn(port, true);
        let found = listeners(port);
        assert!(found.len() == 1 && found[0].exe.is_none(), "{found:?}");
        let v = verify_port(port, std::slice::from_ref(&t2.dir), &pins);
        assert!(
            matches!(&v.result, Err(e @ TrustFail::Unverifiable(_)) if e.denies()),
            "{v:?}"
        );
    }

    #[test]
    fn probing_is_fast_enough_for_the_poll_loop() {
        let l = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = l.local_addr().unwrap().port();
        let t0 = std::time::Instant::now();
        let _ = probe(port);
        assert!(t0.elapsed() < Duration::from_secs(2), "{:?}", t0.elapsed());
    }
}

/// Test helpers: a compiled C listener (not a Python, so Foreign by the rule unless its directory is a trusted
/// prefix) that answers every request with `200 text/html` "SQUATTER", optionally unlinking its own binary
/// right after bind. Built with the Command Line Tools' `cc` into a temp dir.
#[cfg(test)]
pub mod testutil {
    use std::io::{BufRead, BufReader};
    use std::path::PathBuf;
    use std::process::{Child, Command, Stdio};

    pub const SQUAT_C: &str = r#"
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>
int main(int argc, char **argv) {
  int port = atoi(argv[1]);
  int s = socket(AF_INET, SOCK_STREAM, 0), one = 1;
  setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
  struct sockaddr_in a; memset(&a, 0, sizeof a);
  a.sin_family = AF_INET; a.sin_port = htons(port); a.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  if (bind(s, (struct sockaddr *)&a, sizeof a) || listen(s, 64)) { perror("bind"); return 1; }
  if (argc > 2 && strcmp(argv[2], "unlink") == 0) unlink(argv[0]);
  printf("ready\n"); fflush(stdout);
  const char *r = "HTTP/1.1 200 OK\r\ncontent-type: text/html\r\ncontent-length: 8\r\nconnection: close\r\n\r\nSQUATTER";
  for (;;) {
    int c = accept(s, 0, 0); if (c < 0) continue;
    char buf[4096]; (void)read(c, buf, sizeof buf); (void)write(c, r, strlen(r)); close(c);
  }
}
"#;

    pub struct Squatter {
        pub dir: PathBuf,
        pub exe: PathBuf,
        _tmp: tempfile::TempDir,
    }

    pub struct Running(Child);

    impl Running {
        pub fn kill(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    impl Drop for Running {
        fn drop(&mut self) {
            self.kill();
        }
    }

    impl Squatter {
        /// None when no C compiler is available.
        pub fn compile() -> Option<Squatter> {
            let tmp = tempfile::tempdir().ok()?;
            let src = tmp.path().join("squat.c");
            std::fs::write(&src, SQUAT_C).ok()?;
            let exe = tmp.path().join("squat");
            let ok = Command::new("/usr/bin/cc")
                .arg("-O0")
                .arg("-o")
                .arg(&exe)
                .arg(&src)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status()
                .map(|s| s.success())
                .unwrap_or(false);
            ok.then(|| Squatter {
                dir: tmp.path().canonicalize().unwrap_or_else(|_| tmp.path().to_path_buf()),
                exe: exe.canonicalize().unwrap_or(exe),
                _tmp: tmp,
            })
        }

        /// Start it on `port` (optionally unlinking its binary after bind) and wait until it listens.
        pub fn spawn(&self, port: u16, unlink: bool) -> Running {
            let mut cmd = Command::new(&self.exe);
            cmd.arg(port.to_string());
            if unlink {
                cmd.arg("unlink");
            }
            let mut child = cmd
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .expect("spawn squatter");
            let mut line = String::new();
            let _ = BufReader::new(child.stdout.take().unwrap()).read_line(&mut line);
            assert_eq!(line.trim(), "ready", "squatter did not start");
            Running(child)
        }
    }

    /// A free loopback port (bound then released).
    pub fn free_port() -> u16 {
        std::net::TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port()
    }
}
