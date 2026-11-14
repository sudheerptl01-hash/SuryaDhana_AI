"""Ops shell scripts (desktop review round 1, FX-OPS): start-local.sh, scripts/stack_watchdog.sh, scripts/build_ui.sh.

Every test runs a COPY of the real script inside a temp repo tree with /bin/bash (macOS bash 3.2), and drives the
functions by sourcing the script (both scripts run main only when executed). Nothing here starts, stops or probes
a live service: health checks, pgrep and Telegram are overridden or unreachable (the temp tree has no .env).
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = "/bin/bash"
SCRIPTS = {
    "start-local.sh": ROOT / "start-local.sh",
    "scripts/stack_watchdog.sh": ROOT / "scripts" / "stack_watchdog.sh",
    "scripts/build_ui.sh": ROOT / "scripts" / "build_ui.sh",
}
PREFS_SCHEMA = """CREATE TABLE prefs (key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0, provisional INTEGER NOT NULL DEFAULT 0,
    origin TEXT, server_at INTEGER NOT NULL) WITHOUT ROWID"""


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    """A throwaway repo: the two scripts, .logs/.pids, no .env (so Telegram can never be configured)."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".logs").mkdir()
    (repo / ".pids").mkdir()
    for rel in ("start-local.sh", "scripts/stack_watchdog.sh"):
        shutil.copy2(SCRIPTS[rel], repo / rel)
    return repo


def sh(repo: Path, script: str, env: dict[str, str] | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    """Run a bash snippet in `repo` with a minimal, deterministic environment."""
    base = {"HOME": str(repo / "home"), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "LANG": "en_US.UTF-8", "NO_COLOR": "1"}
    return subprocess.run([BASH, "-c", script], cwd=repo, env={**base, **(env or {})}, capture_output=True, check=False,
                          text=True, timeout=timeout)


# ── structure: parse under bash 3.2, safe last line, sourceable ─────────────────────────────────────────────

@pytest.mark.parametrize("rel", sorted(SCRIPTS))
def test_scripts_parse_under_bin_bash(rel):
    r = subprocess.run([BASH, "-n", str(SCRIPTS[rel])], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stderr


@pytest.mark.parametrize("rel,last", [
    ("start-local.sh", r'if \[ "\$\{BASH_SOURCE\[0\]\}" = "\$0" \]; then main "\$@"; exit \$\?; fi'),
    ("scripts/stack_watchdog.sh", r'if \[ "\$\{BASH_SOURCE\[0\]\}" = "\$0" \]; then main; exit \$\?; fi'),
    ("scripts/build_ui.sh", r"esac; exit \$\?"),
])
def test_scripts_end_with_one_line_that_exits(rel, last):
    """bash reads a running script incrementally: the final command and its exit sit on one line, so a run never
    reads past it even if the file is replaced while it runs (C2-reliability-ops-01)."""
    lines = [ln for ln in SCRIPTS[rel].read_text().splitlines() if ln.strip()]
    assert re.fullmatch(last, lines[-1]), lines[-1]


def test_sourcing_runs_no_command(tree):
    r = sh(tree, "source ./start-local.sh && source scripts/stack_watchdog.sh && echo SOURCED")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "SOURCED"           # no header, no status table, no watchdog run
    assert not (tree / ".pids" / "watchdog" / "lock").exists()


# ── C2-reliability-ops-10: the Python services never need Node ───────────────────────────────────────────────

def test_python_service_start_needs_no_npm_but_frontend_does(tree):
    (tree / ".env").write_text("")
    env = {"PATH": "/usr/bin:/bin"}               # no Homebrew: npm is not on PATH
    ok = sh(tree, 'source ./start-local.sh; check_prerequisites "data-service ui-api master-controller"', env)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "npm" not in ok.stdout
    fe = sh(tree, 'source ./start-local.sh; check_prerequisites "frontend"', env)
    assert fe.returncode == 1 and "npm is not installed" in fe.stdout
    r = sh(tree, 'source ./start-local.sh; needs_node "ui-api" || echo no; needs_node "ui-api frontend" && echo yes')
    assert r.stdout.split() == ["no", "yes"]


# ── C2-reliability-ops-07 / C3-04 / C2-security-12: loopback only ────────────────────────────────────────────

def test_ui_api_binds_loopback_only_and_ui_api_host_is_ignored(tree):
    text = SCRIPTS["start-local.sh"].read_text()
    assert '--host 127.0.0.1 --port "$port"' in text and '--host "$host"' not in text
    assert "getifaddr" not in text, "the LAN URL line is gone"
    r = sh(tree, "source ./start-local.sh", {"UI_API_HOST": "0.0.0.0"})
    assert r.returncode == 0 and "UI_API_HOST is no longer supported" in r.stderr
    (tree / ".env").write_text("UI_API_HOST=192.168.31.62\n")
    assert "no longer supported" in sh(tree, "source ./start-local.sh").stderr
    (tree / ".env").write_text("UI_API_HOST=127.0.0.1\n")
    assert sh(tree, "source ./start-local.sh").stderr == ""


# ── C2-reliability-ops-05: append + size-based rotation ──────────────────────────────────────────────────────

def test_start_appends_a_banner_and_keeps_the_crashed_instance_output(tree):
    log = tree / ".logs" / "ui-api.log"
    log.write_text("Traceback (most recent call last): boom\n")
    r = sh(tree, "source ./start-local.sh; open_service_log ui-api 8010")
    assert r.returncode == 0 and r.stdout.strip() == str(log)
    text = log.read_text()
    assert text.startswith("Traceback") and re.search(r"=== .* start-local\.sh: starting ui-api on 127\.0\.0\.1:8010 ===", text)
    src = SCRIPTS["start-local.sh"].read_text()
    assert src.count('>> "$log" 2>&1 < /dev/null &') == 3, "uvicorn, next start and next dev all append"
    assert '> "$PROJECT_ROOT/.logs/$name.log"' not in src and '> "$PROJECT_ROOT/.logs/frontend.log"' not in src


def test_rotate_logs_renames_copytruncates_or_skips(tree):
    logs = tree / ".logs"
    for i in (1, 2, 3):
        (logs / f"idle.log.{i}").write_text(f"gen{i}")
    for name in ("idle", "append", "trunc"):
        (logs / f"{name}.log").write_text(name[0] * 300)
    (logs / "small.log").write_text("tiny")
    holders = [
        subprocess.Popen([BASH, "-c", "exec 3>>append.log; sleep 20"], cwd=logs),             # O_APPEND writer
        subprocess.Popen([BASH, "-c", "exec 3<>trunc.log; sleep 20"], cwd=logs),              # writer without O_APPEND
    ]
    try:
        time.sleep(0.5)
        r = sh(tree, "./start-local.sh rotate-logs", {"LOG_MAX_BYTES": "100"})
    finally:
        for p in holders:
            p.kill()
            p.wait()
    assert r.returncode == 0, r.stdout + r.stderr
    # idle: renamed; generations shifted, the oldest (.3) dropped
    assert not (logs / "idle.log").exists() and (logs / "idle.log.1").read_text() == "i" * 300
    assert [(logs / f"idle.log.{i}").read_text() for i in (2, 3)] == ["gen1", "gen2"]
    # append writer: copied then truncated in place (the writer's next line lands at the new end)
    assert (logs / "append.log").stat().st_size == 0 and (logs / "append.log.1").read_text() == "a" * 300
    # writer without O_APPEND: left alone (a truncation would leave a sparse hole) and reported
    assert (logs / "trunc.log").read_text() == "t" * 300 and not (logs / "trunc.log.1").exists()
    assert "not rotating .logs/trunc.log" in r.stdout
    assert (logs / "small.log").read_text() == "tiny" and not (logs / "small.log.1").exists()
    quiet = sh(tree, "./start-local.sh rotate-logs", {"LOG_MAX_BYTES": "100000"})
    assert quiet.returncode == 0 and quiet.stdout == "", "nothing over the cap: no output (the watchdog log stays quiet)"


# ── C2-reliability-ops-02 / C3-logic-unchanged-01: the prefs status row ──────────────────────────────────────

def _store(path: Path, rows: list[tuple[str, int, str | None]], keep_open: bool = False) -> sqlite3.Connection | None:
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(PREFS_SCHEMA)
    for key, provisional, origin in rows:
        con.execute("INSERT INTO prefs VALUES (?, 'secret-value', 1, 0, 12, ?, ?, 1)", (key, provisional, origin))
    if keep_open:
        return con
    con.close()
    return None


def _prefs_row(tree: Path, db: Path) -> str:
    r = sh(tree, "source ./start-local.sh; prefs_status_row", {"PREFS_DB": str(db)})
    assert r.returncode == 0, r.stderr
    assert "secret-value" not in r.stdout, "never prints a value"
    return r.stdout


def test_prefs_row_imported_from_the_browser_terminal(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    con = _store(db, [("suryadhana.watchlist", 0, "http://localhost:3000"), ("newsTerminal.pins.v1", 0, "http://localhost:3000"),
                      ("goldPreOpen.day", 1, "http://127.0.0.1:8010")], keep_open=True)   # ui-api running: -wal exists
    try:
        before = [p.stat().st_mtime_ns for p in (db, Path(f"{db}-wal"))]
        out = _prefs_row(tree, db)
        after = [p.stat().st_mtime_ns for p in (db, Path(f"{db}-wal"))]
    finally:
        con.close()
    assert re.search(r"^prefs\s+-\s+-\s+imported\s+3 keys \(1 defaults\) · watchlist: browser · pins: browser · 2 from the browser terminal", out)
    assert "→" not in out and after == before, "read-only: neither the store nor its -wal was written"


def test_prefs_row_not_imported_says_what_to_do(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    _store(db, [("suryadhana.watchlist", 1, "http://127.0.0.1:8010"), ("rsch.sel", 0, "http://127.0.0.1:8010")])
    out = _prefs_row(tree, db)
    assert re.search(r"^prefs .* not imported\s+2 keys \(1 defaults\) · watchlist: default · pins: absent$", out, re.MULTILINE)
    assert "before editing the watchlist or pins in the app" in out and "http://localhost:3000" in out
    # the store was closed (no -wal): read immutably, no side files left behind
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("ui_prefs")) == ["ui_prefs.sqlite"]


def test_prefs_row_absent_and_unreadable(tree, tmp_path):
    assert re.search(r"^prefs .* none\s+no settings store yet", _prefs_row(tree, tmp_path / "missing.sqlite"))
    bad = tmp_path / "bad.sqlite"
    bad.write_bytes(b"not a database" * 300)
    assert re.search(r"^prefs .* unreadable .*bad\.sqlite: DatabaseError", _prefs_row(tree, bad))


# ── desktop-app row (informational) ──────────────────────────────────────────────────────────────────────────

def test_app_row_reports_bundle_version_and_launch_at_login(tree, tmp_path):
    app = tmp_path / "SuryaDhana.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        "<key>CFBundleShortVersionString</key><string>9.8.7</string></dict></plist>")
    agents = tree / "home" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    r = sh(tree, "source ./start-local.sh; app_status_row", {"SURYADHANA_APP": str(app)})
    assert re.search(r"^desktop-app .*(running|not running)\s+\S*SuryaDhana\.app 9\.8\.7 · Launch at Login: off", r.stdout)
    (agents / "SuryaDhana.plist").write_text("<plist/>")
    r = sh(tree, "source ./start-local.sh; app_status_row", {"SURYADHANA_APP": str(app)})
    assert "Launch at Login: on" in r.stdout
    r = sh(tree, "source ./start-local.sh; app_status_row", {"SURYADHANA_APP": str(tmp_path / "nope.app")})
    assert re.search(r"^desktop-app .* absent\s+SuryaDhana\.app not installed", r.stdout)


# ── watchdog: C2-reliability-ops-04 (UI release alert) and hourly rotation ──────────────────────────────────

WATCHDOG = "source scripts/stack_watchdog.sh; "


def test_watchdog_alerts_once_per_6h_when_the_ui_release_is_missing(tree):
    up = "is_up() { [ \"$1\" = ui-api ]; }; "
    for _ in range(2):
        r = sh(tree, WATCHDOG + up + "check_ui_release")
        assert r.returncode == 0, r.stderr
    log = (tree / ".logs" / "watchdog.log").read_text()
    assert log.count("ui/dist/current has no UI release") == 1, "logged hourly"
    assert log.count("alert: ⚠️ SuryaDhana: the terminal UI is missing") == 1, "Telegram at most every 6 h"
    assert (tree / ".pids" / "watchdog" / "throttle-uibuild-tg").exists()
    # an expired 6 h throttle alerts again
    old = time.time() - 7 * 3600
    os.utime(tree / ".pids" / "watchdog" / "throttle-uibuild-tg", (old, old))
    sh(tree, WATCHDOG + up + "check_ui_release")
    assert (tree / ".logs" / "watchdog.log").read_text().count("alert: ") == 2


def test_watchdog_stays_quiet_with_a_release_or_with_ui_api_down(tree):
    sh(tree, WATCHDOG + "is_up() { return 1; }; check_ui_release")              # ui-api down: its own alert path
    (tree / "ui" / "dist" / "current").mkdir(parents=True)
    (tree / "ui" / "dist" / "current" / "index.html").write_text("<html>")
    sh(tree, WATCHDOG + "is_up() { return 0; }; check_ui_release")              # release present
    assert not (tree / ".logs" / "watchdog.log").exists()


def test_watchdog_rotates_logs_hourly_and_never_during_a_start(tree):
    big = tree / ".logs" / "data-service.log"
    big.write_text("d" * 500)
    env = {"LOG_MAX_BYTES": "100"}
    busy = sh(tree, WATCHDOG + "start_local_running() { return 0; }; rotate_logs", env)
    assert busy.returncode == 0 and big.stat().st_size == 500, "a start-local.sh run is in progress: no rotation"
    r = sh(tree, WATCHDOG + "start_local_running() { return 1; }; rotate_logs", env)
    assert r.returncode == 0 and (tree / ".logs" / "data-service.log.1").read_text() == "d" * 500
    assert "rotated .logs/data-service.log" in (tree / ".logs" / "watchdog.log").read_text()
    big.write_text("e" * 500)
    sh(tree, WATCHDOG + "start_local_running() { return 1; }; rotate_logs", env)
    assert big.read_text() == "e" * 500, "throttled: at most once an hour"


def test_watchdog_main_with_a_healthy_stack(tree):
    r = sh(tree, WATCHDOG + "is_up() { return 0; }; start_local_running() { return 1; }; main")
    assert r.returncode == 0, r.stderr
    state = tree / ".pids" / "watchdog"
    assert (state / "last_all_up").exists() and not (state / "lock").exists()
    log = (tree / ".logs" / "watchdog.log").read_text()
    assert "is down" not in log and "alert: ⚠️ SuryaDhana: the terminal UI is missing" in log


# ── watchdog: READ-ONLY data-service self-heal and the lock-safe start (13 Nov 2026 cold-boot incident) ──────

RECORDER = "#!/bin/bash\necho \"$@\" >> .logs/calls.txt\nexit 0\n"
STUBS = ("timeout() { shift; \"$@\"; }; tg() { log \"alert: $*\"; }; wait_ready() { return 0; }; "
         "is_up() { return 0; }; ready_code() { echo 503; }; ready_says_read_only() { return 0; }; ")


def test_watchdog_heals_a_read_only_data_service_in_the_lock_safe_order(tree):
    (tree / "start-local.sh").write_text(RECORDER)
    r = sh(tree, WATCHDOG + STUBS + "in_freeze() { return 1; }; heal_read_only; echo RC=$?")
    assert "RC=0" in r.stdout, r.stderr
    calls = (tree / ".logs" / "calls.txt").read_text().splitlines()
    assert calls == ["stop ui-api", "restart data-service", "start ui-api"], calls
    assert (tree / ".pids" / "watchdog" / "throttle-rolock").exists(), "one heal per 50 min: the throttle marker"
    log = (tree / ".logs" / "watchdog.log").read_text()
    assert "READ-ONLY" in log and "healed — /ready 200" in log
    # a second pass inside the throttle window must not restart anything again
    r2 = sh(tree, WATCHDOG + STUBS + "in_freeze() { return 1; }; heal_read_only; echo RC=$?")
    assert "RC=0" in r2.stdout
    assert (tree / ".logs" / "calls.txt").read_text().splitlines() == calls, "throttled: no second restart"


def test_watchdog_never_restarts_a_read_only_data_service_inside_a_freeze_window(tree):
    (tree / "start-local.sh").write_text(RECORDER)
    r = sh(tree, WATCHDOG + STUBS + "in_freeze() { return 0; }; heal_read_only; echo RC=$?")
    assert "RC=0" in r.stdout, r.stderr
    assert not (tree / ".logs" / "calls.txt").exists(), "freeze window: nothing restarted"
    log = (tree / ".logs" / "watchdog.log").read_text()
    assert "freeze window" in log and "alert: " in log, "the owner is told instead"


def test_watchdog_starts_a_dead_data_service_lock_safe_while_ui_api_is_up(tree):
    (tree / "start-local.sh").write_text(RECORDER)
    r = sh(tree, WATCHDOG + "timeout() { shift; \"$@\"; }; is_up() { return 0; }; wait_ready() { return 0; }; "
           "start_data_service_lock_safe; echo RC=$?")
    assert "RC=0" in r.stdout, r.stderr
    calls = (tree / ".logs" / "calls.txt").read_text().splitlines()
    assert calls == ["stop ui-api", "start data-service", "start ui-api"], calls
    log = (tree / ".logs" / "watchdog.log").read_text()
    assert "lock-safe" in log and "ready (writable)" in log


def test_watchdog_lock_safe_start_restarts_ui_api_even_when_data_service_fails(tree):
    (tree / "start-local.sh").write_text("#!/bin/bash\necho \"$@\" >> .logs/calls.txt\n"
                                         "case \"$*\" in 'start data-service') exit 1 ;; esac\nexit 0\n")
    r = sh(tree, WATCHDOG + "timeout() { shift; \"$@\"; }; is_up() { return 0; }; wait_ready() { return 0; }; "
           "start_data_service_lock_safe; echo RC=$?")
    assert "RC=1" in r.stdout, "the failure is reported"
    calls = (tree / ".logs" / "calls.txt").read_text().splitlines()
    assert calls == ["stop ui-api", "start data-service", "start ui-api"], "ui-api comes back on the failure path too"


# ── start-local.sh enforces the restart freeze windows (F6-07, 14 Nov 2026) ──────────────────────────────────
# The windows lived only in documents and in the watchdog's own in_freeze(); a human or an agent running
# `restart data-service` at 09:00 was stopped by nothing — and on 14 Nov that is exactly what happened (benign
# only because it was a Saturday with no login due). These pin the refusal, the watchdog's exemption, and the
# recorded override.

FREEZE = "source ./start-local.sh >/dev/null 2>&1; "


@pytest.mark.parametrize("hm,svc,blocked", [
    ("0800", "data-service", True),          # inside 07:45–09:20
    ("0800", "master-controller", True),
    ("0800", "ui-api", False),               # ui-api has no window
    ("1900", "data-service", True),          # inside 18:30–21:15
    ("2115", "data-service", True),          # the end is included
    ("2116", "data-service", False),         # one minute past it
    ("0744", "data-service", False),         # one minute before
    ("1200", "data-service", False),         # midday: free
])
def test_in_freeze_window_matches_the_documented_windows(tree, hm, svc, blocked):
    stub = f'date() {{ echo "{hm}"; }}; '      # TZ=... date "+%H%M" → our stub
    r = sh(tree, FREEZE + stub + f'in_freeze_window {svc} && echo BLOCKED || echo FREE')
    assert ("BLOCKED" if blocked else "FREE") in r.stdout, (hm, svc, r.stdout, r.stderr)


def test_a_restart_inside_a_window_is_refused_and_says_how_to_override(tree):
    r = sh(tree, FREEZE + 'date() { echo "0800"; }; CALLED_BY_WATCHDOG=0; refuse_in_freeze restart data-service')
    assert r.returncode == 3, r.stdout
    assert "Refusing to restart data-service" in r.stdout and "FREEZE_OVERRIDE=1" in r.stdout
    assert "07:45-09:20" in r.stdout and "18:30-21:15" in r.stdout      # it names both windows


def test_the_watchdog_is_never_blocked_by_the_guard(tree):
    """The watchdog has its own freeze logic and its own alert-and-wait path; second-guessing it here would stop
    a hang restart that its own rules already allow."""
    r = sh(tree, FREEZE + 'date() { echo "0800"; }; CALLED_BY_WATCHDOG=1; refuse_in_freeze restart data-service; echo RC=$?')
    assert "RC=0" in r.stdout and "Refusing" not in r.stdout


def test_the_override_is_loud_rather_than_silent(tree):
    r = sh(tree, FREEZE + 'date() { echo "0800"; }; CALLED_BY_WATCHDOG=0; FREEZE_OVERRIDE=1 '
                          'refuse_in_freeze restart data-service; echo RC=$?')
    assert "RC=0" in r.stdout and "FREEZE_OVERRIDE=1" in r.stdout and "inside a freeze window" in r.stdout


def test_a_service_outside_the_freeze_list_is_never_refused(tree):
    for svc in ("ui-api", "frontend"):
        r = sh(tree, FREEZE + f'date() {{ echo "0800"; }}; CALLED_BY_WATCHDOG=0; refuse_in_freeze stop {svc}; echo RC=$?')
        assert "RC=0" in r.stdout and "Refusing" not in r.stdout, svc


def test_the_bare_restart_and_stop_forms_face_the_freeze_window_too(tree):
    """F7-03: the guard covered `restart <svc>` but not bare `restart`, which restarts data-service AND
    master-controller — and bare `stop` would have left both down and PAUSED through the 08:00 login."""
    src = (tree / "start-local.sh").read_text()
    stop_branch = src.split("    stop)")[1].split(";;")[0]
    restart_branch = src.split("    restart)")[1].split(";;")[0]
    for name, branch in (("stop", stop_branch), ("restart", restart_branch)):
        else_part = branch.split("else", 1)[1]
        assert "refuse_in_freeze" in else_part, f"the bare `{name}` form is unguarded"
        assert "data-service" in else_part and "master-controller" in else_part, f"bare `{name}` misses a service"
