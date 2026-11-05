//! Bounded child processes: every external program the shell runs (`launchctl`, `plutil`) goes through
//! [`run_bounded`], which kills the child when it overruns its time limit, so no probe can ever stall a
//! polling loop, the tray or a menu action (W2: "a hard timeout on every external probe").
//!
//! stdout / stderr are drained on their own threads while waiting (a chatty child can never block on a
//! full pipe), stdin is /dev/null, and the result says whether the limit was hit. Round 3 (R-RUST-07): the
//! drain threads are waited for with a deadline too ([`DRAIN_GRACE`] after the child ended): a grandchild
//! that inherited the pipe and keeps it open can no longer block the caller (its output is then dropped).

use std::io::Read;
use std::process::{Command, ExitStatus, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

/// How long the pipe readers may still take once the child has ended (or was killed).
pub const DRAIN_GRACE: Duration = Duration::from_millis(500);

/// What a bounded run produced.
#[derive(Debug)]
pub struct Bounded {
    /// None when the child was killed at the time limit.
    pub status: Option<ExitStatus>,
    pub stdout: Vec<u8>,
    pub stderr: Vec<u8>,
    pub elapsed: Duration,
}

impl Bounded {
    /// Finished in time with exit status 0.
    pub fn success(&self) -> bool {
        self.status.map(|s| s.success()).unwrap_or(false)
    }

    pub fn timed_out(&self) -> bool {
        self.status.is_none()
    }

    pub fn code(&self) -> Option<i32> {
        self.status.and_then(|s| s.code())
    }

    pub fn stdout_text(&self) -> String {
        String::from_utf8_lossy(&self.stdout).trim().to_string()
    }

    pub fn stderr_text(&self) -> String {
        String::from_utf8_lossy(&self.stderr).trim().to_string()
    }
}

fn drain(r: Option<impl Read + Send + 'static>) -> Option<mpsc::Receiver<Vec<u8>>> {
    let mut r = r?;
    let (tx, rx) = mpsc::channel();
    std::thread::Builder::new()
        .name("bounded-pipe".into())
        .spawn(move || {
            let mut buf = Vec::new();
            // cap what is kept (the shell only ever reads short answers)
            let _ = r.by_ref().take(1024 * 1024).read_to_end(&mut buf);
            // hand the answer over first: a grandchild holding the pipe open may keep the copy below running
            let _ = tx.send(buf);
            let _ = std::io::copy(&mut r, &mut std::io::sink());
        })
        .ok()?;
    Some(rx)
}

/// Run `cmd` (stdin = /dev/null, stdout/stderr captured) for at most `limit`; the child is killed (and
/// reaped) when it overruns. An error means it could not be started at all.
pub fn run_bounded(cmd: &mut Command, limit: Duration) -> std::io::Result<Bounded> {
    let t0 = Instant::now();
    let mut child = cmd
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;
    let out = drain(child.stdout.take());
    let err = drain(child.stderr.take());
    let status = loop {
        match child.try_wait() {
            Ok(Some(s)) => break Some(s),
            Ok(None) if t0.elapsed() < limit => std::thread::sleep(Duration::from_millis(5)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
            Err(e) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(e);
            }
        }
    };
    // bounded: a reader still blocked after the grace (a grandchild keeps the pipe open) is abandoned
    let until = Instant::now() + DRAIN_GRACE;
    let join = |rx: Option<mpsc::Receiver<Vec<u8>>>| {
        rx.and_then(|rx| rx.recv_timeout(until.saturating_duration_since(Instant::now())).ok())
            .unwrap_or_default()
    };
    let stdout = join(out);
    let stderr = join(err);
    Ok(Bounded {
        status,
        stdout,
        stderr,
        elapsed: t0.elapsed(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finishes_captures_and_reports_codes() {
        let b = run_bounded(
            Command::new("/bin/sh").args(["-c", "echo out; echo err >&2; exit 3"]),
            Duration::from_secs(5),
        )
        .unwrap();
        assert!(!b.timed_out() && !b.success());
        assert_eq!(b.code(), Some(3));
        assert_eq!(b.stdout_text(), "out");
        assert_eq!(b.stderr_text(), "err");
        assert!(run_bounded(&mut Command::new("/usr/bin/true"), Duration::from_secs(5))
            .unwrap()
            .success());
        assert!(run_bounded(&mut Command::new("/nonexistent/program"), Duration::from_secs(1)).is_err());
    }

    #[test]
    fn a_hung_child_is_killed_at_the_limit() {
        let t0 = Instant::now();
        let b = run_bounded(Command::new("/bin/sleep").arg("30"), Duration::from_millis(300)).unwrap();
        assert!(b.timed_out(), "{b:?}");
        assert!(t0.elapsed() < Duration::from_secs(5), "killed, not waited for");
    }

    #[test]
    fn a_grandchild_holding_the_pipe_never_blocks_the_caller() {
        // R-RUST-07: the child exits at once but leaves a background grandchild that inherited stdout and
        // keeps it open for 6 s; round 2 joined the reader thread without a bound and waited the full 6 s
        let t0 = Instant::now();
        let b = run_bounded(
            Command::new("/bin/sh").args(["-c", "echo hi; /bin/sleep 6 & exit 0"]),
            Duration::from_secs(5),
        )
        .unwrap();
        assert!(b.success(), "{:?}", b.status);
        assert!(t0.elapsed() < Duration::from_secs(3), "waited {:?}", t0.elapsed());
    }

    #[test]
    fn a_chatty_child_never_blocks_on_a_full_pipe() {
        // 4 MB of output (far above a 64 KB pipe buffer): drained while waiting, only the first MB kept
        let b = run_bounded(
            Command::new("/bin/sh").args(["-c", "head -c 4194304 /dev/zero"]),
            Duration::from_secs(10),
        )
        .unwrap();
        assert!(b.success(), "{:?}", b.status);
        assert_eq!(b.stdout.len(), 1024 * 1024);
    }
}
