"""start-local.sh, wave 2 (W2-OPS): the status rows and the log rotation's failure modes.

* prefs row: durable migration provenance (contract K2: GET /api/prefs → migration, kept in the store's meta table),
  so it never flips back to 'not imported' after normal app use; per-record fallback for an older ui-api; a
  timeout on the status Python (a macOS privacy prompt must not hang `status`).
* ui-release row: ui/dist/current next to the release ui-api says it serves (GET /version), with a warning when
  they differ.
* rotate_log fails CLOSED: without a working lsof a log is left alone, never renamed under a live writer.
* START_SET: the Node checks see the same service set start_services starts.
* stack_watchdog.sh: a HUNG core service (its own uvicorn listens, /health does not answer) is restarted after
  two consecutive runs, with diagnostics saved first; freeze windows, a running ICICI login and a port held by
  another program make it alert instead.

Every test runs a COPY of the script in a temp tree with /bin/bash and drives functions by sourcing it. Nothing
starts, stops or probes a live service: stop/start entry points are overridden, ui-api is a fake HTTP server on an
ephemeral port, and PREFS_DB / STATUS_UI_API always point at temp files or that fake. ``DESKTOP_OPS_SCRIPT`` runs
the same tests against another copy of start-local.sh (the negative control against the pre-wave-2 script), and
``DESKTOP_OPS_WATCHDOG`` the watchdog tests against another copy of the watchdog.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = Path(os.environ.get("DESKTOP_OPS_SCRIPT") or ROOT / "start-local.sh")
BASH = "/bin/bash"
STD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
PREFS_SCHEMA = """CREATE TABLE prefs (key TEXT PRIMARY KEY, value TEXT, updated_at INTEGER NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0, bytes INTEGER NOT NULL DEFAULT 0, provisional INTEGER NOT NULL DEFAULT 0,
    origin TEXT, server_at INTEGER NOT NULL) WITHOUT ROWID"""
WL, PINS = "suryadhana.watchlist", "newsTerminal.pins.v1"
APP, OLD = "http://127.0.0.1:8010", "http://localhost:3000"
IMPORT_AT_MS = 1792918500000          # 2026-10-25 14:25 IST

pytestmark = pytest.mark.skipif(not Path(BASH).exists(), reason="needs /bin/bash")


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for d in ("scripts", ".logs", ".pids", "data"):
        (repo / d).mkdir(parents=True)
    shutil.copy2(SCRIPT, repo / "start-local.sh")
    return repo


def sh(repo: Path, script: str, env: dict[str, str] | None = None, timeout: float = 60) -> subprocess.CompletedProcess:
    base = {"HOME": str(repo / "home"), "PATH": STD_PATH, "LANG": "en_US.UTF-8", "NO_COLOR": "1",
            "STATUS_UI_API": "http://127.0.0.1:9"}           # never the live ui-api (port 9: nothing listens)
    return subprocess.run([BASH, "-c", script], cwd=repo, env={**base, **(env or {})}, capture_output=True, text=True,
                          check=False, timeout=timeout)


def source(body: str) -> str:
    """Source the script, point its Python at this interpreter (CI has no jupyter_env), then run ``body``."""
    return f"source ./start-local.sh; PYTHON_BIN={sys.executable}; {body}"


def toolbox(tmp: Path, *, drop: tuple[str, ...] = (), extra: dict[str, str] | None = None) -> str:
    """A PATH holding only the tools the script needs (symlinks), minus ``drop``, plus fake scripts in ``extra``."""
    bin_dir = tmp / f"bin-{len(list(tmp.glob('bin-*')))}"
    bin_dir.mkdir()
    for tool in ("dirname", "mkdir", "grep", "tail", "cut", "tr", "wc", "rm", "mv", "cp", "awk", "cat", "date", "head",
                 "sed", "sleep", "env", "lsof", "curl", "pkill", "pgrep", "timeout", "basename", "printf"):
        if tool in drop:
            continue
        found = shutil.which(tool, path=STD_PATH)
        if found:
            (bin_dir / tool).symlink_to(found)
    for name, body in (extra or {}).items():
        f = bin_dir / name
        f.write_text("#!/bin/bash\n" + body + "\n")
        f.chmod(0o755)
    return str(bin_dir)


# ── rotate_log fails closed ──────────────────────────────────────────────────────────────────────────────────

def _big_log(repo: Path) -> Path:
    log = repo / ".logs" / "big.log"
    log.write_text("x" * 300)
    return log


def _rotated(log: Path) -> bool:
    return not log.exists() or Path(f"{log}.1").exists()


def test_rotation_is_skipped_when_lsof_is_missing(tree, tmp_path):
    log = _big_log(tree)
    r = sh(tree, "./start-local.sh rotate-logs", {"PATH": toolbox(tmp_path, drop=("lsof",)), "LOG_MAX_BYTES": "100"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert log.read_text() == "x" * 300 and not _rotated(log), "a log must never be renamed without knowing its writers"
    assert "not rotating .logs/big.log" in r.stdout and "lsof is not on PATH" in r.stdout


@pytest.mark.parametrize("fake_lsof,why", [
    ("echo 'lsof: WARNING: can not stat() nfs file system' >&2; exit 1", "lsof exited 1"),
    ("exit 2", "lsof exited 2"),
    ("echo 'zzz unexpected'; exit 0", "unexpected lsof output"),
])
def test_rotation_is_skipped_when_lsof_fails(tree, tmp_path, fake_lsof, why):
    log = _big_log(tree)
    path = toolbox(tmp_path, drop=("lsof",), extra={"lsof": fake_lsof})
    r = sh(tree, "./start-local.sh rotate-logs", {"PATH": path, "LOG_MAX_BYTES": "100"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert not _rotated(log) and why in r.stdout, r.stdout


def test_rotation_still_renames_a_log_nobody_has_open(tree, tmp_path):
    """Control: lsof's 'no match' (exit 1, no output at all) is the only 'no writers' answer, and it rotates."""
    log = _big_log(tree)
    path = toolbox(tmp_path, drop=("lsof",), extra={"lsof": "exit 1"})
    r = sh(tree, "./start-local.sh rotate-logs", {"PATH": path, "LOG_MAX_BYTES": "100"})
    assert r.returncode == 0 and not log.exists() and Path(f"{log}.1").read_text() == "x" * 300, r.stdout


# ── START_SET: the prerequisite checks see the set that will start ───────────────────────────────────────────

@pytest.mark.parametrize("cmd,start_set,want", [
    ("start", "", "data-service ui-api master-controller"),
    ("start", "frontend", "frontend"),
    ("restart", "", "data-service ui-api master-controller"),
    ("restart", "ui-api frontend", "ui-api frontend"),
])
def test_prerequisite_checks_see_the_start_set(tree, cmd, start_set, want):
    # SAFETY: stop_services and check_prerequisites are replaced; check_prerequisites exits, so nothing ever starts
    body = ("stop_services() { echo STOPPED; }; check_prerequisites() { echo \"PRE[$1]\"; exit 0; }; "
            f"START_SET='{start_set}' main {cmd}")
    r = sh(tree, source(body))
    assert r.returncode == 0, r.stderr
    assert f"PRE[{want}]" in r.stdout
    assert ("STOPPED" in r.stdout) == (cmd == "restart")


# ── prefs row ────────────────────────────────────────────────────────────────────────────────────────────────

def _store(path: Path, rows: list[tuple[str, int, str | None]], meta: dict[str, str] | None = None,
           meta_cols: tuple[str, str] = ("k", "v")) -> None:
    """A prefs store; ``meta`` adds the K2 meta table (ui-api's columns are k, v; a key/value shape is accepted)."""
    con = sqlite3.connect(str(path), isolation_level=None)
    con.execute(PREFS_SCHEMA)
    for key, provisional, origin in rows:
        con.execute("INSERT INTO prefs VALUES (?, 'secret-value', 1, 0, 12, ?, ?, 1)", (key, provisional, origin))
    if meta is not None:
        k, v = meta_cols
        con.execute(f"CREATE TABLE meta ({k} TEXT PRIMARY KEY, {v} TEXT NOT NULL) WITHOUT ROWID")
        con.executemany("INSERT INTO meta VALUES (?, ?)", list(meta.items()))
    con.close()


def _prefs(tree: Path, env: dict[str, str]) -> str:
    r = sh(tree, source("prefs_status_row"), env)
    assert r.returncode == 0, r.stderr
    assert "secret-value" not in r.stdout, "never prints a value"
    return r.stdout


ALL_APP = [(WL, 0, APP), (PINS, 0, APP), ("rsch.sel", 0, APP)]


@pytest.mark.parametrize("meta,cols", [
    ({"migration": json.dumps({"legacy_import_at": IMPORT_AT_MS, "legacy_origin": OLD, "legacy_keys": 7,
                               "inferred": False})}, ("k", "v")),
    ({"migration": json.dumps({"legacy_import_at": IMPORT_AT_MS, "legacy_origin": OLD, "legacy_keys": 7})}, ("key", "value")),
    ({"legacy_import_at": str(IMPORT_AT_MS), "legacy_origin": OLD, "legacy_keys": "7"}, ("k", "v")),
])
def test_k2_record_keeps_imported_after_every_key_was_edited_in_the_app(tree, tmp_path, meta, cols):
    """The adversarial reviewer's store: migrated, then each key edited in the app (all rows app-origin)."""
    db = tmp_path / "ui_prefs.sqlite"
    _store(db, ALL_APP, meta, cols)
    before = db.stat().st_mtime_ns
    out = _prefs(tree, {"PREFS_DB": str(db)})
    assert out.startswith("prefs") and " imported " in out and "not imported" not in out, out
    assert "watchlist: app · pins: app · imported 7 keys from http://localhost:3000 on 2026-10-25 14:25 IST" in out
    assert "→" not in out and db.stat().st_mtime_ns == before
    assert sorted(p.name for p in tmp_path.glob("ui_prefs*")) == ["ui_prefs.sqlite"], "read-only: no -wal/-shm left behind"


def test_k2_record_says_not_imported_and_what_is_still_open(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    _store(db, [(WL, 1, APP)], meta={})                 # K2-capable store, nothing imported yet
    out = _prefs(tree, {"PREFS_DB": str(db)})
    assert "not imported" in out and "watchlist: default · pins: absent" in out
    assert "before editing the watchlist or pins in the app" in out
    db2 = tmp_path / "two.sqlite"
    _store(db2, ALL_APP, meta={"legacy_import_at": ""})  # both keys already set in the app, still no import
    out = _prefs(tree, {"PREFS_DB": str(db2)})
    assert "not imported" in out and "the watchlist and pins were set in the app (an import keeps them)" in out
    assert "before editing" not in out and "other settings" in out


def test_without_a_k2_record_app_owned_keys_get_no_misleading_instruction(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    _store(db, ALL_APP)                                   # an older ui-api: no meta table
    out = _prefs(tree, {"PREFS_DB": str(db)})
    assert out.split()[1:4] == ["-", "-", "app-owned"], out
    assert "→" not in out and "open http://localhost:3000" not in out
    # only the pins are still open: the instruction names them alone
    db2 = tmp_path / "pins.sqlite"
    _store(db2, [(WL, 0, APP)])
    out = _prefs(tree, {"PREFS_DB": str(db2)})
    assert "not imported" in out and "before editing the pins in the app" in out


def test_a_provisional_row_from_3000_is_not_an_import(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    _store(db, [(WL, 1, OLD)])
    out = _prefs(tree, {"PREFS_DB": str(db)})
    assert "not imported" in out and "watchlist: default" in out


# ── the same rows against ui-api's REAL store (services/ui-api/routers/prefs.py, W2-API's K2 implementation) ──

def _real_store(db: Path):
    sys.path.insert(0, str(ROOT / "scripts"))
    from desktop_qa.scratch_server import load_prefs_module  # a private copy of the router bound to ``db``

    return load_prefs_module(db)


def test_real_store_migrated_then_edited_in_the_app_stays_imported(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    mod = _real_store(db)
    store = mod.get_store()
    if not hasattr(store, "migration"):
        pytest.skip("this ui-api has no K2 migration record yet")
    store.import_items({WL: '["TCS","INFY"]', PINS: '["NIFTY"]', "rsch.sel": '"x"'}, OLD)   # the one-time import
    now = int(time.time() * 1000)
    for key in (WL, PINS, "rsch.sel"):                                                      # then normal app use
        store.write(key, '["EDITED"]', now + 1000, origin=APP)
    mod.close_all()
    out = _prefs(tree, {"PREFS_DB": str(db)})
    assert " imported " in out and "not imported" not in out and "→" not in out, out
    assert "watchlist: app · pins: app · imported 3 keys from http://localhost:3000 on " in out


def test_real_store_never_migrated_says_so(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    mod = _real_store(db)
    store = mod.get_store()
    if not hasattr(store, "migration"):
        pytest.skip("this ui-api has no K2 migration record yet")
    store.write(WL, '["TCS"]', int(time.time() * 1000), origin=APP)
    mod.close_all()
    out = _prefs(tree, {"PREFS_DB": str(db)})
    assert "not imported" in out and "watchlist: app · pins: absent" in out and "before editing the pins" in out


def test_real_store_backfills_an_old_migration_and_status_says_inferred(tree, tmp_path):
    db = tmp_path / "ui_prefs.sqlite"
    _store(db, [(WL, 0, OLD), (PINS, 0, OLD), ("rsch.sel", 1, APP)])   # migrated before K2 existed: no meta table
    mod = _real_store(db)
    store = mod.get_store()
    if not hasattr(store, "migration"):
        pytest.skip("this ui-api has no K2 migration record yet")
    assert store.migration()["inferred"] is True
    mod.close_all()
    out = _prefs(tree, {"PREFS_DB": str(db)})
    assert "imported from http://localhost:3000 (recorded from its 2 records; earliest " in out, out


class _FakeUiApi:
    """Loopback HTTP server standing in for ui-api: /health, /version, /api/prefs (records every path)."""

    def __init__(self) -> None:
        self.version: bytes = b'{"service":"ui-api","ui_build":null,"ui_status":"missing"}'
        self.prefs: dict = {"prefs": {}, "server_time": 1}
        self.paths: list[str] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                fake.paths.append(self.path)
                body = {"/health": b'{"status":"ok"}', "/version": fake.version,
                        "/api/prefs": json.dumps(fake.prefs).encode()}.get(self.path)
                self.send_response(200 if body is not None else 404)
                self.end_headers()
                self.wfile.write(body or b"{}")

            def log_message(self, *_a: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def fake_api() -> Iterator[_FakeUiApi]:
    f = _FakeUiApi()
    try:
        yield f
    finally:
        f.close()


def test_k2_from_ui_api_when_the_store_has_no_meta_table(tree, fake_api):
    _store(tree / "data" / "ui_prefs.sqlite", ALL_APP)   # the store ui-api uses (PREFS_DB not overridden)
    fake_api.prefs["migration"] = {"legacy_import_at": IMPORT_AT_MS, "legacy_origin": OLD, "legacy_keys": 3}
    out = _prefs(tree, {"STATUS_UI_API": fake_api.base})
    assert "imported 3 keys from http://localhost:3000 on 2026-10-25 14:25 IST" in out, out
    assert "/api/prefs" in fake_api.paths


def test_an_explicit_prefs_db_is_never_matched_against_the_running_ui_api(tree, tmp_path, fake_api):
    db = tmp_path / "scratch.sqlite"
    _store(db, ALL_APP)
    fake_api.prefs["migration"] = {"legacy_import_at": IMPORT_AT_MS, "legacy_origin": OLD, "legacy_keys": 3}
    out = _prefs(tree, {"STATUS_UI_API": fake_api.base, "PREFS_DB": str(db)})
    assert "app-owned" in out and "/api/prefs" not in fake_api.paths


@pytest.mark.parametrize("with_gnu_timeout", [True, False])
def test_a_hanging_status_python_times_out(tree, tmp_path, with_gnu_timeout):
    if with_gnu_timeout and not shutil.which("timeout", path=STD_PATH):
        pytest.skip("GNU timeout not installed here (the bash fallback case still runs)")
    db = tmp_path / "ui_prefs.sqlite"
    _store(db, ALL_APP)
    hang = tmp_path / "hang-python"
    hang.write_text("#!/bin/bash\nexec /bin/sleep 30\n")
    hang.chmod(0o755)
    path = toolbox(tmp_path, drop=() if with_gnu_timeout else ("timeout",))
    t0 = time.monotonic()
    r = sh(tree, f"source ./start-local.sh; PYTHON_BIN={hang}; prefs_status_row",
           {"PATH": path, "PREFS_DB": str(db), "STATUS_PY_TIMEOUT": "1"}, timeout=25)
    took = time.monotonic() - t0
    assert r.returncode == 0, r.stderr
    assert "unreadable" in r.stdout and "timed out after 1s" in r.stdout, r.stdout
    assert took < 10, f"status waited {took:.1f}s for a hung Python"


# ── ui-release row ──────────────────────────────────────────────────────────────────────────────────────────

def _release(tree: Path, rid: str) -> None:
    rel = tree / "ui" / "dist" / "releases" / rid
    rel.mkdir(parents=True)
    (rel / "index.html").write_text("<html>")
    (tree / "ui" / "dist" / "current").symlink_to(f"releases/{rid}")


def _row(tree: Path, api: str) -> str:
    r = sh(tree, source("ui_release_row"), {"STATUS_UI_API": api})
    assert r.returncode == 0, r.stderr
    return r.stdout


def _version(rid: str | None, status: str = "ok", spaced: bool = False) -> bytes:
    body = {"service": "ui-api", "api_version": "1.0.0",
            "ui_build": None if rid is None else {"schema": 1, "id": rid, "git_sha": "0ae66db", "build_id": "zz"},
            "ui_status": status}
    return json.dumps(body, separators=(", ", ": ") if spaced else (",", ":")).encode()


@pytest.mark.parametrize("spaced", [False, True])
def test_ui_release_row_matches_what_ui_api_serves(tree, fake_api, spaced):
    _release(tree, "20261025-135500-0ae66db")
    fake_api.version = _version("20261025-135500-0ae66db", spaced=spaced)
    out = _row(tree, fake_api.base)
    assert "ok" in out.split() and "20261025-135500-0ae66db (ui/dist/current) · served by ui-api" in out, out
    assert "→" not in out


def test_ui_release_row_warns_when_ui_api_serves_another_release(tree, fake_api):
    _release(tree, "20261025-135500-0ae66db")
    fake_api.version = _version("20261025-114737-0ae66db")
    out = _row(tree, fake_api.base)
    assert "mismatch" in out and "ui-api serves: 20261025-114737-0ae66db" in out
    assert "→ ui-api is not serving ui/dist/current" in out and "UI_DIST_DIR" in out
    fake_api.version = _version(None, status="missing")
    assert "ui-api serves: no release" in _row(tree, fake_api.base)


def test_ui_release_row_when_ui_api_is_down_or_answers_garbage(tree, fake_api):
    _release(tree, "R1")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{s.getsockname()[1]}"
    assert "R1 (ui/dist/current) · ui-api not answering (/health)" in _row(tree, closed)
    fake_api.version = b"<html>not json</html>"
    assert "R1 (ui/dist/current) · ui-api's GET /version did not answer" in _row(tree, fake_api.base)


def test_ui_release_row_missing_release_but_ui_api_serves_one(tree, fake_api):
    fake_api.version = _version("R9")
    out = _row(tree, fake_api.base)
    assert "missing" in out and "./start-local.sh build-ui · ui-api serves R9 from another directory" in out
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{s.getsockname()[1]}"
    assert _row(tree, closed).rstrip().endswith("missing    ./start-local.sh build-ui")


def test_help_names_the_served_release_check(tree):
    r = sh(tree, "./start-local.sh help")
    assert r.returncode == 0 and "the one ui-api serves" in r.stdout and "Read-only" in r.stdout
    assert "dead-man ping" in r.stdout and "'no answer' = listening but hung" in r.stdout


# ── service rows: a hung listener (R-OPS-10) ─────────────────────────────────────────────────────────────────

def test_a_hung_listener_says_no_answer_without_a_garbage_latency(tree, tmp_path, fake_api):
    """R-OPS-10: curl's '000 <time>' plus the fallback echo printed 'HTTP 000' and '<time>000 -s' for exactly the
    hung case. Now 'no answer' with an explanation; a normal answer keeps its latency."""
    port = _free_port()
    ready = tmp_path / "ready"
    script = tmp_path / "hung.py"
    script.write_text(HUNG_LISTENER)
    hung = subprocess.Popen([sys.executable, str(script), "--port", str(port), str(ready)])
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.05)
        r = sh(tree, source(f"service_row ui-api {port} http://127.0.0.1:{port}/health"), timeout=30)
        row = r.stdout.strip()
        assert r.returncode == 0, r.stderr
        assert re.match(rf"^ui-api\s+{port}\s+{hung.pid}\s+no answer\s+listening, but no answer in 5 s", row), row
        assert "000" not in row
    finally:
        hung.kill()
        hung.wait()
    fport = fake_api.base.rsplit(":", 1)[1]
    up = sh(tree, source(f"service_row ui-api {fport} {fake_api.base}/health")).stdout
    assert re.match(rf"^ui-api\s+{fport}\s+\d+\s+up\s+\d+\.\d+s$", up.strip()), up
    err = sh(tree, source(f"service_row data-service {fport} {fake_api.base}/nope")).stdout
    assert re.match(rf"^data-service\s+{fport}\s+\d+\s+HTTP 404\s+\d+\.\d+s$", err.strip()), err


# ── desktop-app row: the installed copy, other copies, launchd supervision (SECREL-11, SECREL-06) ────────────

def _bundle(tmp: Path) -> Path:
    app = tmp / "Apps" / "SuryaDhana.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
        "<key>CFBundleShortVersionString</key><string>1.0.0</string></dict></plist>")
    return app


def _fake_ps(lines: list[str]) -> str:
    return "cat << 'EOF'\n" + "\n".join(lines) + "\nEOF"


def _fake_launchctl(job_pid: str) -> str:
    if not job_pid:
        return "echo 'Could not find service' >&2; exit 113"
    return f"printf 'gui/501/SuryaDhana = {{\\n\\tstate = running\\n\\tpid = {job_pid}\\n\\tendpoints = {{\\n\\t\\tpid = 1\\n\\t}}\\n}}\\n'"


def _selftest_exe(tree: Path) -> str:
    return f"{tree}/desktop/src-tauri/target/release/bundle/macos/SuryaDhana.app/Contents/MacOS/SuryaDhana"


def _fake_pgrep(guarded_pid: str) -> str:
    """pgrep that finds a crash guard (desktop/src-tauri/src/supervise.rs) watching ``guarded_pid`` only, so the row
    never depends on the processes running on this Mac (the live app's pid may well be 83455)."""
    if not guarded_pid:
        return "exit 1"
    return f'[ "$*" = "-f -- suryadhana-crash-guard {guarded_pid} " ] && {{ echo 77001; exit 0; }}; exit 1'


@pytest.mark.parametrize("job,login,guard,want", [
    ("83455", True, "", "supervised by launchd (relaunched after a crash)"),
    ("", True, "83455", "opened by hand: its crash guard relaunches it through launchd"),
    ("", True, "58496", "opened by hand: not relaunched after a crash"),        # a guard of another copy does not count
    ("", True, "", "opened by hand: not relaunched after a crash"),
    ("", False, "", "not relaunched after a crash (Launch at Login is off)"),
    ("", False, "83455", "not relaunched after a crash (Launch at Login is off)"),  # the guard stands down without it
])
def test_app_row_names_the_installed_copy_and_who_relaunches_it(tree, tmp_path, job, login, guard, want):
    """SECREL-06: launchd's job (KeepAlive), a crash guard (a copy opened by hand, round 3) or nothing; the kickstart
    remedy only when nothing relaunches a copy that Launch at Login could supervise."""
    app = _bundle(tmp_path)
    exe = f"{app}/Contents/MacOS/SuryaDhana"
    ps = [f"58496 {_selftest_exe(tree)} --self-test", f"83455 {exe} --autostart",
          f"90001 grep {exe}", "90002 /usr/bin/awk -v tail=.app/Contents/MacOS/SuryaDhana {}"]
    agents = tree / "home" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    if login:
        (agents / "SuryaDhana.plist").write_text("<plist/>")
    path = toolbox(tmp_path, drop=("pgrep",), extra={"ps": _fake_ps(ps), "launchctl": _fake_launchctl(job),
                                                      "id": "echo 501", "pgrep": _fake_pgrep(guard)})
    r = sh(tree, source("app_status_row"), {"SURYADHANA_APP": str(app), "PATH": path})
    assert r.returncode == 0, r.stderr
    row = r.stdout.splitlines()[0]
    assert re.match(r"^desktop-app\s+-\s+83455\s+running\s", row), row
    assert want in row and f"Launch at Login: {'on' if login else 'off'}" in row
    assert "other copies: 58496 (./desktop/src-tauri/target/release/bundle/macos/SuryaDhana.app)" in row
    assert "90001" not in row and "90002" not in row, "a grep or awk naming the path is not a copy"
    assert ("launchctl kickstart gui/501/SuryaDhana" in r.stdout) == ("not relaunched after a crash" in want and login)


SUPERVISE_RS = ROOT / "desktop" / "src-tauri" / "src" / "supervise.rs"


def _guard_script() -> tuple[str, str]:
    """(GUARD_SH, GUARD_NAME) exactly as desktop/src-tauri/src/supervise.rs defines them."""
    src = SUPERVISE_RS.read_text()
    script = re.search(r'pub const GUARD_SH: &str = r#"(.*?)"#;', src, re.DOTALL)
    name = re.search(r'pub const GUARD_NAME: &str = "([^"]+)";', src)
    assert script and name, "supervise.rs no longer defines GUARD_SH / GUARD_NAME"
    # spawn_guard's argv: sh -c <script> <name> <app pid> <run.json> <plist> <launchctl> <uid>
    assert re.search(r'OsStr::new\("-c"\),\s*OsStr::new\(GUARD_SH\),\s*OsStr::new\(GUARD_NAME\),\s*OsStr::new\(&pid\),',
                     src), "spawn_guard's argument order changed: start-local.sh's pgrep pattern relies on it"
    return script.group(1), name.group(1)


@pytest.mark.skipif(not SUPERVISE_RS.exists(), reason="desktop sources not checked out")
def test_status_finds_a_real_crash_guard_spawned_the_way_the_app_spawns_it(tree, tmp_path):
    """Cross-component: the app's real guard script, started with the app's argv layout, is what start-local.sh's
    pgrep pattern finds; a guard watching another pid is not. Nothing here can reach launchd: the guard's plist path
    does not exist (it exits without calling the stand-in launchctl) and both processes are killed at the end."""
    script, name = _guard_script()
    app = _bundle(tmp_path)
    exe = f"{app}/Contents/MacOS/SuryaDhana"
    agents = tree / "home" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "SuryaDhana.plist").write_text("<plist/>")
    fake_app = subprocess.Popen(["/bin/sleep", "60"])                  # stands in for the app's pid
    unguarded = subprocess.Popen(["/bin/sleep", "60"])                 # negative control: no guard watches it
    guard = subprocess.Popen(["/bin/sh", "-c", script, name, str(fake_app.pid), str(tmp_path / "run.json"),
                              str(tmp_path / "no-such.plist"), "/usr/bin/false", "501"])

    def row(pid: int) -> str:
        path = toolbox(tmp_path, extra={"ps": _fake_ps([f"{pid} {exe}"]), "launchctl": _fake_launchctl(""),
                                        "id": "echo 501"})
        r = sh(tree, source("app_status_row"), {"SURYADHANA_APP": str(app), "PATH": path})
        assert r.returncode == 0, r.stderr
        return r.stdout

    try:
        guarded = row(fake_app.pid)
        assert "opened by hand: its crash guard relaunches it through launchd" in guarded, guarded
        assert "kickstart" not in guarded
        bare = row(unguarded.pid)
        assert "opened by hand: not relaunched after a crash" in bare and "launchctl kickstart" in bare, bare
    finally:
        for p in (guard, fake_app, unguarded):
            p.kill()
            p.wait()


def test_app_row_is_not_fooled_by_a_self_test_copy(tree, tmp_path):
    """SECREL-11: status said 'running /Applications/SuryaDhana.app' for a --self-test copy under desktop/."""
    app = _bundle(tmp_path)
    path = toolbox(tmp_path, extra={"ps": _fake_ps([f"58496 {_selftest_exe(tree)} --self-test"]),
                                    "launchctl": _fake_launchctl(""), "id": "echo 501"})
    r = sh(tree, source("app_status_row"), {"SURYADHANA_APP": str(app), "PATH": path})
    row = r.stdout.splitlines()[0]
    assert re.match(r"^desktop-app\s+-\s+-\s+not running\s", row), row
    assert "other copies: 58496 (./desktop/" in row and "kickstart" not in r.stdout


# ── dead-man ping and reboot-recovery rows (SECREL-02, completeness-final-04) ────────────────────────────────

URL_LINE = "HEALTHCHECK_PING_URL='https://hc-ping.com/1234-secret-uuid'"


@pytest.mark.parametrize("env_line,last,want", [
    ("", None, "not set"),
    (URL_LINE, None, "no ping"),
    (URL_LINE, (60, "ok"), "ok"),
    (URL_LINE, (60, "fail"), "fail sent"),
    (URL_LINE, (60, "error"), "failing"),
    (URL_LINE, (3600, "ok"), "stale"),
])
def test_dead_man_row(tree, env_line, last, want):
    (tree / ".env").write_text(env_line + "\n")
    if last is not None:
        (tree / ".pids" / "watchdog").mkdir(parents=True)
        (tree / ".pids" / "watchdog" / "deadman").write_text(f"{int(time.time()) - last[0]} {last[1]}\n")
    r = sh(tree, source("deadman_status_row"))
    assert r.returncode == 0, r.stderr
    row = r.stdout.splitlines()[0]
    assert re.match(rf"^dead-man-ping\s+-\s+-\s+{want}\s", row), row
    assert "secret-uuid" not in r.stdout, "only the host is ever printed"
    assert ("hc-ping.com" in row) == bool(env_line)
    assert ("RUNBOOK_RESTORE.md 'Off-machine dead-man ping'" in r.stdout) == (want == "not set")


@pytest.mark.parametrize("autorestart,autoinstall,filevault,want,detail", [
    ("0", "1", "FileVault is On.", "check",
     "power-on after a power failure: off · automatic macOS installs: on · FileVault: on: after any reboot"),
    ("1", "0", "FileVault is Off.", "ok", "power-on after a power failure: on · automatic macOS installs: off · FileVault: off"),
])
def test_reboot_recovery_row(tree, tmp_path, autorestart, autoinstall, filevault, want, detail):
    path = toolbox(tmp_path, extra={"pmset": f"printf ' autorestartatconnect 0\\n autorestart          {autorestart}\\n'",
                                    "defaults": f"echo {autoinstall}", "fdesetup": f"echo '{filevault}'"})
    r = sh(tree, source("reboot_recovery_row"), {"PATH": path})
    assert r.returncode == 0, r.stderr
    assert re.match(rf"^reboot-recovery\s+-\s+-\s+{want}\s+{re.escape(detail)}", r.stdout), r.stdout
    assert ("sudo pmset -a autorestart 1" in r.stdout) == (want == "check")


# ── a restart by hand clears the watchdog's hourly hang-restart cap (R-OPS-02) ───────────────────────────────

@pytest.mark.parametrize("by_watchdog", [False, True])
def test_only_a_restart_by_hand_clears_the_hang_restart_cap(tree, by_watchdog):
    hist = tree / ".pids" / "watchdog" / "hang-restarts-ui-api"
    hist.parent.mkdir(parents=True)
    hist.write_text("1\n2\n3\n")
    # SAFETY: stop_one and start_one are replaced, so nothing is stopped or started
    r = sh(tree, source("stop_one() { :; }; start_one() { :; }; main restart ui-api; "
                        'env | grep -c "^SURYADHANA_WATCHDOG=" || true'),
           {"SURYADHANA_WATCHDOG": "1"} if by_watchdog else None)
    assert r.returncode == 0, r.stderr
    assert hist.exists() == by_watchdog
    assert r.stdout.strip().endswith("0"), "the marker never reaches the services' environment"


# ── stack_watchdog.sh: a HUNG core service (listening, /health does not answer) is restarted ──────────────────
#
# 25 Oct 14:40-14:48: the live ui-api kept its listener but answered nothing; the watchdog logged "already running"
# then "FAILED to start" and left it hung. These tests drive a COPY of the watchdog in a temp tree whose
# start-local.sh is a fake that only records its arguments, so nothing here can stop or start a live service.
# Negative control: DESKTOP_OPS_WATCHDOG=<the 12:16 watchdog> runs the same tests against the pre-change script.

WATCHDOG_SRC = Path(os.environ.get("DESKTOP_OPS_WATCHDOG") or ROOT / "scripts" / "stack_watchdog.sh")
FAKE_START_LOCAL = """#!/bin/bash
# stands in for start-local.sh: records the call; start/restart make the service healthy unless FAKE_FAIL=1
here="$(cd "$(dirname "$0")" && pwd)"
echo "$*" >> "$here/start-local.calls"
case "$1" in start|restart) [ "${FAKE_FAIL:-0}" = 1 ] && exit 1; [ -n "$2" ] && touch "$here/up-$2"; rm -f "$here/listen-$2" ;; esac
exit 0
"""
# health, listeners, ownership, CPU, clock, login and diagnostics are stood in; ROOT is the temp tree. is_up and
# listener_pid are stubbed too, so the pre-change watchdog (negative control) never probes a live port either, and
# diag_pystacks only records (a fake pid such as 4242 may be a real process: it is never signalled).
WD_STUBS = ('health_code() { if [ -f "$ROOT/up-$1" ]; then echo 200; else cat "$ROOT/code-$1" 2> /dev/null || echo 000; fi; }; '
            'is_up() { [ "$(health_code "$1")" = 200 ]; }; '
            'listener_pids() { cat "$ROOT/listen-$1" 2> /dev/null; }; '
            'listener_pid() { listener_pids "$1" | head -1; }; '
            'listener_is_ours() { [ ! -f "$ROOT/foreign-$1" ] && [ ! -f "$ROOT/foreign-pid-$2" ]; }; '
            'proc_cmd() { echo "fake-cmd-of-$1"; }; '
            'proc_pcpu() { cat "$ROOT/cpu-$1" 2> /dev/null || echo 0.0; }; '
            'start_local_running() { return 1; }; '
            'login_running() { [ -f "$ROOT/login-running" ]; }; '
            'ist_hm() { cat "$ROOT/now-hm" 2> /dev/null || echo 1200; }; '
            'diag_pystacks() { echo "$1 $2" >> "$ROOT/pystacks.calls"; return 2; }; '
            'diag_sample() { echo "fake sample of $1" > "$2"; }; diag_lsof() { echo "fake lsof of $1" > "$2"; }; ')


@pytest.fixture()
def wd(tmp_path: Path) -> Path:
    repo = tmp_path / "wd"
    for d in ("scripts", ".logs", ".pids"):
        (repo / d).mkdir(parents=True)
    shutil.copy2(WATCHDOG_SRC, repo / "scripts" / "stack_watchdog.sh")
    fake = repo / "start-local.sh"
    fake.write_text(FAKE_START_LOCAL)
    fake.chmod(0o755)
    (repo / ".logs" / "ui-api.log").write_text("".join(f"line {i}\n" for i in range(500)))
    return repo


def wsh(repo: Path, body: str, env: dict[str, str] | None = None, stubs: bool = True,
        timeout: float = 120) -> subprocess.CompletedProcess:
    base = {"HOME": str(repo / "home"), "PATH": STD_PATH, "LANG": "en_US.UTF-8", "WATCHDOG_DEBOUNCE_S": "0",
            "WATCHDOG_PYTHON": sys.executable}
    script = "source scripts/stack_watchdog.sh; " + (WD_STUBS if stubs else "") + body
    return subprocess.run([BASH, "-c", script], cwd=repo, env={**base, **(env or {})}, capture_output=True, text=True,
                          check=False, timeout=timeout)


def wlog(repo: Path) -> str:
    f = repo / ".logs" / "watchdog.log"
    return f.read_text() if f.exists() else ""


def calls(repo: Path) -> list[str]:
    f = repo / "start-local.calls"
    return f.read_text().splitlines() if f.exists() else []


def captures(repo: Path) -> list[Path]:
    d = repo / ".logs" / "hangs"
    return sorted(d.iterdir()) if d.exists() else []


def test_hung_service_is_restarted_on_the_second_consecutive_run_with_diagnostics(wd):
    (wd / "listen-ui-api").write_text("4242")
    r = wsh(wd, "handle_hung ui-api")
    assert r.returncode == 0, r.stderr
    assert "ui-api is listening (pid 4242) but /health did not answer: hung check 1/2" in wlog(wd)
    assert calls(wd) == [] and (wd / ".pids" / "watchdog" / "hung-ui-api").read_text().strip() == "4242 1"
    r = wsh(wd, "handle_hung ui-api")
    assert r.returncode == 0, r.stderr
    assert calls(wd) == ["restart ui-api"]
    log = wlog(wd)
    assert "ui-api hung (2 checks, pid 4242, /health timed out): diagnostics in .logs/hangs/" in log
    assert "ui-api restarted after a hang" in log
    assert "alert: ⚠️ SuryaDhana: ui-api was hung (listening, /health timed out): restarted." in log
    caps = captures(wd)
    assert len(caps) == 1 and caps[0].name.endswith("-ui-api")
    assert {p.name for p in caps[0].iterdir()} == {"summary.txt", "sample-4242.txt", "lsof-4242.txt", "log-tail.txt"}
    tail = (caps[0] / "log-tail.txt").read_text().splitlines()
    assert len(tail) == 200 and tail[-1] == "line 499"
    summary = (caps[0] / "summary.txt").read_text()
    assert "listener pid(s): 4242" in summary and "/health timed out" in summary and "hung runs: 2" in summary
    assert not (wd / ".pids" / "watchdog" / "hung-ui-api").exists(), "the count restarts after every attempt"


def test_an_http_error_from_its_own_listener_is_named_in_the_alert_and_every_listener_is_captured(wd):
    (wd / "listen-ui-api").write_text("4242\n4243\n")         # e.g. the UI_API_RELOAD supervisor + worker
    (wd / "code-ui-api").write_text("503")
    wsh(wd, "handle_hung ui-api; handle_hung ui-api")
    assert calls(wd) == ["restart ui-api"]
    assert "alert: ⚠️ SuryaDhana: ui-api was hung (listening, /health answered HTTP 503): restarted." in wlog(wd)
    (cap,) = captures(wd)
    assert {p.name for p in cap.iterdir()} == {"summary.txt", "log-tail.txt", "sample-4242.txt", "lsof-4242.txt",
                                               "sample-4243.txt", "lsof-4243.txt"}
    assert "listener pid(s): 4242 4243" in (cap / "summary.txt").read_text()


def test_failed_restart_alerts_and_retries_only_after_another_full_count(wd):
    (wd / "listen-ui-api").write_text("4242")
    wsh(wd, "handle_hung ui-api; handle_hung ui-api", {"FAKE_FAIL": "1"})
    assert calls(wd) == ["restart ui-api"]
    assert "ui-api restart after a hang FAILED" in wlog(wd) and "and the restart FAILED" in wlog(wd)
    wsh(wd, "handle_hung ui-api", {"FAKE_FAIL": "1"})
    assert calls(wd) == ["restart ui-api"], "no restart on the very next run"
    wsh(wd, "handle_hung ui-api", {"FAKE_FAIL": "1"})
    assert calls(wd) == ["restart ui-api", "restart ui-api"]


def test_a_service_that_answers_again_just_before_its_restart_is_left_alone(wd):
    (wd / "listen-ui-api").write_text("4242")
    wsh(wd, "handle_hung ui-api")
    (wd / "up-ui-api").touch()                                 # recovers while dead services were being started
    wsh(wd, "handle_hung ui-api")
    assert calls(wd) == [] and not captures(wd)
    assert "ui-api answered /health again before its restart: not restarted" in wlog(wd)
    assert not (wd / ".pids" / "watchdog" / "hung-ui-api").exists()


@pytest.mark.parametrize("hm,frozen", [("0744", False), ("0745", True), ("0800", True), ("0920", True), ("0921", False),
                                       ("1829", False), ("1830", True), ("2115", True), ("2116", False), ("0215", False)])
def test_freeze_windows_cover_data_service_and_master_controller_only(wd, hm, frozen):
    (wd / "now-hm").write_text(hm)
    r = wsh(wd, "for s in data-service master-controller ui-api; do in_freeze $s && echo \"$s frozen\" || echo \"$s free\"; done")
    want = ["data-service frozen", "master-controller frozen"] if frozen else ["data-service free", "master-controller free"]
    assert r.stdout.split("\n")[:3] == [*want, "ui-api free"], r.stdout + r.stderr


def test_inside_a_freeze_window_it_alerts_instead_of_restarting(wd):
    (wd / "now-hm").write_text("1900")
    (wd / "listen-data-service").write_text("777")
    (wd / "listen-ui-api").write_text("4242")
    wsh(wd, "for i in 1 2 3; do handle_hung data-service; handle_hung ui-api; done")
    assert calls(wd) == ["restart ui-api"], "ui-api may be restarted any time; data-service waits for the window"
    log = wlog(wd)
    assert "data-service hung (2 checks, pid 777) inside its restart freeze window: NOT restarted" in log
    assert log.count("alert: ⚠️ SuryaDhana: data-service is hung (listening, /health not answering) but it is inside") == 1, \
        "throttled"
    assert [c.name.endswith("-ui-api") for c in captures(wd)] == [True], "no capture (and no restart) inside the window"
    (wd / "now-hm").write_text("2120")                    # the window is over: the next hung run restarts it
    wsh(wd, "handle_hung data-service")
    assert calls(wd)[-1] == "restart data-service"


def test_a_running_icici_login_defers_the_restart(wd):
    (wd / "listen-master-controller").write_text("888")
    (wd / "login-running").touch()
    wsh(wd, "handle_hung master-controller; handle_hung master-controller; handle_hung master-controller")
    assert calls(wd) == [] and "restart deferred" in wlog(wd) and not captures(wd)
    assert wlog(wd).count("alert: ⚠️ SuryaDhana: master-controller is hung") == 1
    (wd / "login-running").unlink()
    wsh(wd, "handle_hung master-controller")
    assert calls(wd) == ["restart master-controller"]
    assert not (wd / ".pids" / "watchdog" / "login-defer-master-controller").exists()


def test_a_running_login_never_holds_back_ui_api_or_data_service(wd):
    """R-OPS-01: before, a login (or the manual helper left at its prompt) blocked every hung service's restart for
    as long as it ran. The login hands its token to ui-api (or writes .env when ui-api does not answer), so a hung
    ui-api or data-service gains nothing from waiting."""
    (wd / "listen-ui-api").write_text("4242")
    (wd / "listen-data-service").write_text("777")
    (wd / "login-running").touch()
    wsh(wd, "for i in 1 2; do handle_hung ui-api; handle_hung data-service; done")
    assert calls(wd) == ["restart ui-api", "restart data-service"], calls(wd)
    assert "restart deferred" not in wlog(wd)


def test_the_login_deferral_is_capped(wd):
    """R-OPS-01: master-controller waits for a login at most WATCHDOG_LOGIN_DEFER_MAX_MIN (10), then restarts."""
    (wd / "listen-master-controller").write_text("888")
    (wd / "login-running").touch()
    wsh(wd, "handle_hung master-controller; handle_hung master-controller")
    marker = wd / ".pids" / "watchdog" / "login-defer-master-controller"
    assert calls(wd) == [] and marker.exists()
    old = time.time() - 11 * 60
    os.utime(marker, (old, old))                                 # the login has been running for 11 min
    wsh(wd, "handle_hung master-controller")
    assert calls(wd) == ["restart master-controller"]
    assert "an ICICI login has been running for over 10 min, restarting anyway" in wlog(wd)
    assert not marker.exists()


def test_login_detection_matches_a_python_running_the_login_scripts_only(wd, tmp_path):
    detect = "source scripts/stack_watchdog.sh; login_running && echo LOGIN || echo NONE"

    def probe() -> str:
        return subprocess.run([BASH, "-c", detect], cwd=wd, capture_output=True, text=True, check=False,
                              timeout=30).stdout.strip()

    if probe() == "LOGIN":
        pytest.skip("a real ICICI login is running on this machine right now")
    scripts = tmp_path / "x" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("daily_session_refresh.py", "icici_session_helper.py", "session_refresh_notes.py",
                 "test_daily_session_refresh.py", "not_daily_session_refresh.py"):
        (scripts / name).write_text("import time\ntime.sleep(30)\n")
    not_logins = [[sys.executable, str(scripts / "session_refresh_notes.py")],
                  [sys.executable, str(scripts / "test_daily_session_refresh.py")],     # a test file, run directly
                  [sys.executable, str(scripts / "not_daily_session_refresh.py")],
                  [sys.executable, "-c", "import time; time.sleep(30)", str(scripts / "daily_session_refresh.py")],
                  ["/usr/bin/tail", "-f", str(scripts / "daily_session_refresh.py")],    # an editor/viewer on the file
                  # R-OPS-01: the interactive helper waits at its prompt for ever and writes .env only: never a login
                  # that a restart could break
                  [sys.executable, "-u", str(scripts / "icici_session_helper.py")]]
    logins = [[sys.executable, str(scripts / "daily_session_refresh.py"), "--headless"],  # master-controller's form
              [sys.executable, "scripts/daily_session_refresh.py", "--force"]]           # run by hand from the repo
    for argv, want in [(a, "NONE") for a in not_logins] + [(a, "LOGIN") for a in logins]:
        p = subprocess.Popen(argv, cwd=scripts.parent, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(0.4)
            assert p.poll() is None, argv
            assert probe() == want, argv
        finally:
            p.kill()
            p.wait()


def test_listener_ownership_is_the_services_own_uvicorn_or_its_child(wd):
    sleeper = "import time; time.sleep(30)"
    procs = {"ours": [sys.executable, "-c", sleeper, "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8010"],
             "supervisor": [BASH, "-c", "sleep 30; :", "uvicorn", "main:app", "--port", "8010", "--reload"],
             "other": ["/bin/sleep", "30"],
             "near": [sys.executable, "-c", sleeper, "uvicorn", "main:app", "--port", "80100"]}
    running = {k: subprocess.Popen(v) for k, v in procs.items()}
    try:
        time.sleep(0.5)
        worker = subprocess.run(["pgrep", "-P", str(running["supervisor"].pid)], capture_output=True, text=True,
                                check=False).stdout.split()
        assert worker, "the supervisor's child is running"
        pids = {k: p.pid for k, p in running.items()} | {"worker": int(worker[0])}
        body = "; ".join(f'listener_is_ours ui-api {pid} && echo "{k} ours" || echo "{k} not"' for k, pid in pids.items())
        body += f'; listener_is_ours data-service {pids["ours"]} && echo "ds ours" || echo "ds not"'
        r = wsh(wd, body, stubs=False)
        assert r.stdout.split("\n")[:6] == ["ours ours", "supervisor ours", "other not", "near not", "worker ours",
                                            "ds not"], r.stdout + r.stderr
    finally:
        for p in running.values():
            p.kill()
            p.wait()


def test_a_port_held_by_another_program_is_reported_and_never_stopped(wd):
    (wd / "listen-ui-api").write_text("5151")
    (wd / "foreign-ui-api").touch()
    (wd / "up-data-service").touch()
    (wd / "up-master-controller").touch()
    r = wsh(wd, "main; main; main")
    assert r.returncode == 0, r.stderr
    assert [c for c in calls(wd) if c != "rotate-logs"] == [], "neither started nor restarted"
    log = wlog(wd)
    assert "ui-api does not answer /health and port 8010 is held by another program (pid 5151: fake-cmd-of-5151): left alone" in log
    assert log.count("alert: ⚠️ SuryaDhana: ui-api is not answering, and its port 8010 is held by another program") == 1
    assert not (wd / ".pids" / "watchdog" / "hung-ui-api").exists() and not captures(wd)


def test_dry_run_changes_nothing(wd):
    (wd / "listen-ui-api").write_text("4242")
    wsh(wd, "handle_hung ui-api; handle_hung ui-api", {"WATCHDOG_DRY_RUN": "1"})
    assert calls(wd) == [] and not captures(wd)
    assert ("dry run: ui-api hung (2 checks, pid 4242, /health timed out): would capture diagnostics and run "
            "start-local.sh restart ui-api") in wlog(wd)


def _age(path: Path, hours: float) -> None:
    old = time.time() - hours * 3600
    os.utime(path, (old, old))


def test_only_the_newest_ten_captures_are_kept(wd):
    hangs = wd / ".logs" / "hangs"
    for i in range(12):
        (hangs / f"20261025-1200{i:02d}-ui-api").mkdir(parents=True)
        _age(hangs / f"20261025-1200{i:02d}-ui-api", 48)       # older than a day: no storm protection
    (hangs / "README.txt").write_text("notes")                 # not a capture: never pruned
    wsh(wd, "prune_hangs")
    names = sorted(p.name for p in hangs.iterdir() if p.is_dir())
    assert len(names) == 10 and names[0] == "20261025-120002-ui-api" and names[-1] == "20261025-120011-ui-api"
    wsh(wd, "prune_hangs", {"WATCHDOG_HANG_KEEP": "3"})
    assert sorted(p.name for p in hangs.iterdir()) == ["20261025-120009-ui-api", "20261025-120010-ui-api",
                                                       "20261025-120011-ui-api", "README.txt"]


def test_the_first_capture_of_a_hang_storm_is_never_pruned(wd):
    """R-OPS-02: only the newest 10 were kept, so a storm's first (most telling) capture was gone within the hour.
    Each service's first capture of the last 24 h is kept on top of the newest WATCHDOG_HANG_KEEP."""
    hangs = wd / ".logs" / "hangs"
    names = [f"20261025-1200{i:02d}-ui-api" for i in range(12)] + ["20261024-090000-data-service",
                                                                    "20261025-110000-data-service"]
    for n in names:
        (hangs / n).mkdir(parents=True)
    _age(hangs / "20261024-090000-data-service", 30)            # yesterday's: not part of today's storm
    wsh(wd, "prune_hangs", {"WATCHDOG_HANG_KEEP": "3"})
    assert sorted(p.name for p in hangs.iterdir()) == [
        "20261025-110000-data-service", "20261025-120000-ui-api",
        "20261025-120009-ui-api", "20261025-120010-ui-api", "20261025-120011-ui-api"]


def _hang_twice(wd: Path, env: dict[str, str] | None = None, pid: str = "4242") -> None:
    """Two consecutive hung runs of ui-api (the fake start-local.sh marks it healthy after a restart: undo that)."""
    (wd / "up-ui-api").unlink(missing_ok=True)
    (wd / "listen-ui-api").write_text(pid)
    wsh(wd, "handle_hung ui-api; handle_hung ui-api", env)


def test_a_failed_restart_is_alerted_even_right_after_a_restarted_alert(wd):
    """R-OPS-03: both alerts shared the 30 min throttle key hang-<svc>, so 'restart FAILED' after 'restarted' was
    silent while the terminal was down."""
    _hang_twice(wd)
    _hang_twice(wd, {"FAKE_FAIL": "1"}, pid="4343")              # the new instance hangs too; its restart fails
    assert calls(wd) == ["restart ui-api", "restart ui-api"]
    log = wlog(wd)
    assert "alert: ⚠️ SuryaDhana: ui-api was hung (listening, /health timed out): restarted." in log
    assert "alert: 🔴 SuryaDhana: ui-api was hung (listening, /health timed out) and the restart FAILED." in log


def test_hang_restarts_are_capped_per_hour_then_it_only_alerts(wd):
    """R-OPS-02: a service that stayed wedged was restarted every ~4 min for ever, killing in-flight work each time."""
    for _ in range(3):
        _hang_twice(wd)
    assert calls(wd) == ["restart ui-api"] * 3
    _hang_twice(wd)
    _hang_twice(wd)
    assert calls(wd) == ["restart ui-api"] * 3, "no 4th hang restart within the hour"
    log = wlog(wd)
    assert "ui-api hung again (2 checks, pid 4242, /health timed out) after 3 hang restarts in the last 60 min: NOT restarted" in log
    assert log.count("alert: 🔴 SuryaDhana: ui-api keeps hanging: restarted 3 times in the last 60 min") == 1
    hist = wd / ".pids" / "watchdog" / "hang-restarts-ui-api"
    hist.write_text("".join(f"{int(time.time()) - 3700 - i}\n" for i in range(3)))   # all over an hour old now
    _hang_twice(wd)
    assert calls(wd) == ["restart ui-api"] * 4 and len(hist.read_text().split()) == 1


@pytest.mark.parametrize("by_hand", ["paused", "start-local", "new-listener"])
def test_a_stop_or_restart_by_hand_during_the_capture_cancels_the_hang_restart(wd, by_hand):
    """R-OPS-04: the capture takes seconds; Stop Stack in the app, or the boot page's suggested manual restart, in
    that time must win (before, the watchdog restarted anyway and cleared the owner's pause)."""
    act = {"paused": 'mkdir -p "$ROOT/.pids/paused"; touch "$ROOT/.pids/paused/ui-api"',
           "start-local": 'touch "$ROOT/sl-running"',
           "new-listener": 'echo 5151 > "$ROOT/listen-ui-api"'}[by_hand]
    (wd / "listen-ui-api").write_text("4242")
    wsh(wd, f'diag_sample() {{ {act}; echo s > "$2"; }}; start_local_running() {{ [ -f "$ROOT/sl-running" ]; }}; '
            "handle_hung ui-api; handle_hung ui-api")
    assert calls(wd) == [], by_hand
    assert "ui-api hang restart skipped" in wlog(wd) and len(captures(wd)) == 1
    assert (wd / ".pids" / "paused" / "ui-api").exists() == (by_hand == "paused"), "a pause is never cleared"
    assert not (wd / ".pids" / "watchdog" / "hung-ui-api").exists()
    assert not (wd / ".pids" / "watchdog" / "hang-restarts-ui-api").exists(), "no restart was counted"


def test_a_port_shared_with_another_program_is_never_restarted(wd):
    """R-OPS-05: ownership was decided on the first listener only, while `start-local.sh restart` kills them all."""
    (wd / "listen-ui-api").write_text("4242\n5151\n")            # its own uvicorn AND a foreign program
    (wd / "foreign-pid-5151").touch()
    (wd / "up-data-service").touch()
    (wd / "up-master-controller").touch()
    r = wsh(wd, "main")
    assert r.returncode == 0, r.stderr
    assert [c for c in calls(wd) if c != "rotate-logs"] == []
    assert "port 8010 is held by another program (pid 5151: fake-cmd-of-5151): left alone" in wlog(wd)
    assert not (wd / ".pids" / "watchdog" / "hung-ui-api").exists() and not captures(wd)


def test_services_are_probed_on_the_address_they_bind(wd):
    r = wsh(wd, "for s in data-service ui-api master-controller frontend; do health_url $s; done", stubs=False)
    assert r.stdout.split() == ["http://127.0.0.1:8001/health", "http://127.0.0.1:8010/health",
                                "http://127.0.0.1:8008/health", "http://127.0.0.1:3000"]


@pytest.mark.parametrize("svc", ["data-service", "master-controller"])
def test_a_busy_data_service_or_controller_gets_more_time_than_a_wedged_one(wd, svc):
    """R-OPS-06: a long job holding the GIL looks hung too; at high CPU it waits WATCHDOG_BUSY_RUNS (8) runs."""
    (wd / f"listen-{svc}").write_text("777")
    (wd / "cpu-777").write_text("97.3")
    wsh(wd, f"for i in 1 2 3 4 5 6 7; do handle_hung {svc}; done")
    log = wlog(wd)
    assert calls(wd) == [] and f"{svc} is listening (pid 777) but /health did not answer, at 97% CPU: busy" in log
    assert log.count(f"alert: ⚠️ SuryaDhana: {svc} is not answering /health but is busy (97% CPU)") == 1
    wsh(wd, f"handle_hung {svc}")                                # the 8th run in a row: treated as hung
    assert calls(wd) == [f"restart {svc}"]


def test_ui_api_is_restarted_after_two_runs_whatever_its_cpu(wd):
    (wd / "listen-ui-api").write_text("4242")
    (wd / "cpu-4242").write_text("99.0")
    wsh(wd, "handle_hung ui-api; handle_hung ui-api")
    assert calls(wd) == ["restart ui-api"]


def test_the_hang_count_belongs_to_one_listener_and_expires(wd):
    """R-OPS-11: a count left by an instance that was since restarted, or from before a sleep, no longer counts."""
    f = wd / ".pids" / "watchdog" / "hung-ui-api"
    (wd / "listen-ui-api").write_text("4242")
    wsh(wd, "handle_hung ui-api")
    (wd / "listen-ui-api").write_text("5151")                    # restarted by hand meanwhile: another process
    wsh(wd, "handle_hung ui-api")
    assert calls(wd) == [] and f.read_text().split() == ["5151", "1"]
    _age(f, 7 / 60)                                               # 7 min old: a missed run, or the Mac slept
    wsh(wd, "handle_hung ui-api")
    assert calls(wd) == [] and f.read_text().split() == ["5151", "1"]
    wsh(wd, "handle_hung ui-api")                                 # the next consecutive run
    assert calls(wd) == ["restart ui-api"]


# a stand-in service process: optionally registers faulthandler on SIGUSR1 and announces it in its log the way
# ui-api's loop watchdog does, then waits in a named function (so the dump is recognisable)
PY_STACK_PROC = """import faulthandler, signal, sys, time
if sys.argv[1] == "announce":
    faulthandler.register(signal.SIGUSR1, file=sys.stderr, all_threads=True, chain=False)
    print('{"event": "loop_watchdog_started", "stack_dump_signal": "SIGUSR1"}', file=sys.stderr, flush=True)
open(sys.argv[2], "w").write("ready")
def waiting_in_a_wedged_loop():
    time.sleep(60)
waiting_in_a_wedged_loop()
"""


@pytest.mark.parametrize("mode", ["announce", "silent", "other-pid"])
def test_python_stacks_are_requested_only_from_a_process_that_announced_the_handler(wd, tmp_path, mode):
    """R-OPS-07: ui-api's SIGUSR1 faulthandler dump (every Python thread) goes into the capture. A process that did
    not announce the handler after its last start banner, or is not the pidfile's, is never sent SIGUSR1: the
    signal's default action would kill it."""
    log = wd / ".logs" / "ui-api.log"
    log.write_text("older output\n=== 2026-10-25 15:35:49 +0530 start-local.sh: starting ui-api on 127.0.0.1:8010 ===\n")
    ready, script = tmp_path / "ready", tmp_path / "svc.py"
    script.write_text(PY_STACK_PROC)
    with log.open("a") as out:
        p = subprocess.Popen([sys.executable, str(script), "silent" if mode == "silent" else "announce", str(ready)],
                             stdout=out, stderr=out)
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.05)
        time.sleep(0.2)
        (wd / ".pids" / "ui-api.pid").write_text(str(p.pid + 100000 if mode == "other-pid" else p.pid))
        stubs = 'diag_sample() { echo s > "$2"; }; diag_lsof() { echo l > "$2"; }; '
        r = wsh(wd, stubs + f"capture_hang ui-api 000 {p.pid}", stubs=False)
        assert r.returncode == 0, r.stderr
        cap = Path(r.stdout.strip())
        stacks = cap / f"py-stacks-{p.pid}.txt"
        assert p.poll() is None, "the capture never kills the process"
        if mode == "announce":
            text = stacks.read_text()
            assert "most recent call first" in text and "waiting_in_a_wedged_loop" in text
            assert "waiting_in_a_wedged_loop" in (cap / "log-tail.txt").read_text()
        else:
            assert not stacks.exists()
            assert f"py-stacks {p.pid}: not requested" in (cap / "summary.txt").read_text()
    finally:
        p.kill()
        p.wait()


# ── the single-instance lock (SECREL-05) ────────────────────────────────────────────────────────────────────

HEALTHY = 'is_up() { return 0; }; start_local_running() { return 1; }; '


def _dead_pid() -> int:
    p = subprocess.Popen(["/bin/sleep", "0"])
    p.wait()
    return p.pid


@pytest.mark.parametrize("owner,stale", [
    ("dead-pid", True), ("previous-boot", True), ("not-a-watchdog", True), ("no-owner-before-boot", True),
    ("live-watchdog", False), ("no-owner-fresh", False), ("live-watchdog-usec-owner", False),
    ("dead-pid-usec-owner", True),
])
def test_a_lock_whose_run_is_gone_is_taken_over_at_once(wd, owner, stale):
    """SECREL-05: the lock counted as stale only after 20 min, so a lock left by a power cut or a SIGKILL silenced
    every run for up to 20 min after the reboot (and the app showed 'the watchdog is starting the stack').
    'previous-boot' is held by a LIVE process named like a watchdog, so only the boot rule can call it stale (it used
    to be pytest's own pid, stale for 'not a watchdog' whatever the boot). '*-usec-owner': an owner line written
    before the round-4 boot_epoch fix (kern.boottime's usec, 6 digits) is left to the pid checks."""
    lock = wd / ".pids" / "watchdog" / "lock"
    lock.mkdir(parents=True)
    boot = int(time.time()) - 300                                  # the Mac booted 5 min ago (boot_epoch stub)
    holder = None
    try:
        if owner == "dead-pid":
            (lock / "owner").write_text(f"{_dead_pid()} {boot}\n")
        elif owner == "previous-boot":
            holder = subprocess.Popen([BASH, "-c", "sleep 30; :", "stack_watchdog.sh"])
            (lock / "owner").write_text(f"{holder.pid} {boot - 86400}\n")
        elif owner == "not-a-watchdog":
            holder = subprocess.Popen(["/bin/sleep", "30"])
            (lock / "owner").write_text(f"{holder.pid} {boot}\n")
        elif owner == "live-watchdog":
            holder = subprocess.Popen([BASH, "-c", "sleep 30; :", "stack_watchdog.sh"])
            (lock / "owner").write_text(f"{holder.pid} {boot}\n")
        elif owner == "live-watchdog-usec-owner":
            holder = subprocess.Popen([BASH, "-c", "sleep 30; :", "stack_watchdog.sh"])
            (lock / "owner").write_text(f"{holder.pid} 658471\n")
        elif owner == "dead-pid-usec-owner":
            (lock / "owner").write_text(f"{_dead_pid()} 658471\n")
        elif owner == "no-owner-before-boot":
            os.utime(lock, (boot - 100, boot - 100))                 # 6.7 min old: younger than the 20 min rule
        r = wsh(wd, HEALTHY + f"boot_epoch() {{ echo {boot}; }}; main", stubs=False)
        assert r.returncode == 0, r.stderr
        ran = (wd / ".pids" / "watchdog" / "last_all_up").exists()
        assert ran == stale, owner
        if stale:
            assert "removed a stale watchdog lock" in wlog(wd) and not lock.exists(), "released at the end of the run"
        else:
            assert lock.is_dir()
    finally:
        if holder is not None:
            holder.kill()
            holder.wait()


def test_a_run_writes_its_owner_and_never_removes_a_successors_lock(wd):
    r = wsh(wd, 'take_lock && cat "$LOCK/owner"; echo "999999 1" > "$LOCK/owner"; release_lock; '
                '[ -d "$LOCK" ] && echo KEPT', stubs=False)
    first, kept = r.stdout.split("\n")[:2]
    assert first.split()[0].isdigit() and len(first.split()) == 2 and kept == "KEPT"


def _kern_boottime_sec() -> int:
    """kern.boottime's tv_sec through sysctlbyname (what the app's macos::boot_time_secs reads), not through sysctl(8)."""
    import ctypes
    import ctypes.util

    class Timeval(ctypes.Structure):
        _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_int32)]

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    tv, size = Timeval(), ctypes.c_size_t(ctypes.sizeof(Timeval))
    assert libc.sysctlbyname(b"kern.boottime", ctypes.byref(tv), ctypes.byref(size), None, 0) == 0
    return int(tv.tv_sec)


@pytest.mark.skipif(sys.platform != "darwin", reason="kern.boottime is macOS")
def test_the_owner_line_carries_the_boot_epoch_the_app_compares_with(wd):
    """F3-RUST review (major): boot_epoch's greedy sed returned kern.boottime's usec field, so the owner line read
    '<pid> 658471' and the app (stack.rs watchdog_lock_held: owner boot == kern.boottime tv_sec) never counted a
    watchdog run as held. Runs the real boot_epoch and take_lock (no stub), and the app's rule on the line written."""
    boot = _kern_boottime_sec()
    assert boot > 1_600_000_000 and boot <= time.time()
    r = wsh(wd, 'boot_epoch; take_lock && cat "$LOCK/owner"; release_lock', stubs=False)
    assert r.returncode == 0, r.stderr
    printed, owner = r.stdout.splitlines()[:2]
    assert printed == str(boot), (printed, boot)
    _pid, owner_boot = owner.split()
    assert int(owner_boot) == boot, "the round-3 app compares with kern.boottime's seconds: never held otherwise"
    # the app reads the same file (desktop/src-tauri/src/stack.rs watchdog_lock_held; since round 4b it also accepts
    # the pre-fix usec stamp): it must keep comparing with the boot's seconds, which this script now writes
    rs = ROOT / "desktop" / "src-tauri" / "src" / "stack.rs"
    if rs.exists():
        src = rs.read_text()
        assert "watchdog_lock_held" in src and ("boot.sec" in src or "boot_time_secs" in src)


def test_a_reload_supervisor_is_never_sent_usr1(wd, tmp_path):
    """Round 3 review: with UI_API_RELOAD=1, .pids/ui-api.pid names uvicorn's --reload supervisor while the line
    '"stack_dump_signal": "SIGUSR1"' comes from its worker. USR1 (no handler) killed the supervisor, orphaned the hung
    worker on the port, and from then on the watchdog only alerted ('held by another program'). A real supervisor
    stand-in (no handler, '--reload' on its command line) and a real worker child that registered the handler."""
    log = wd / ".logs" / "ui-api.log"
    log.write_text("=== 2026-10-25 21:30:00 +0530 start-local.sh: starting ui-api on 127.0.0.1:8010 ===\n")
    ready, script = tmp_path / "ready", tmp_path / "svc.py"
    script.write_text(PY_STACK_PROC)
    sup_src = tmp_path / "supervisor.py"
    sup_src.write_text("import subprocess, sys, time\n"
                       f"subprocess.Popen([sys.executable, {str(script)!r}, 'announce', {str(ready)!r}])\n"
                       "time.sleep(60)\n")
    with log.open("a") as out:
        sup = subprocess.Popen([sys.executable, str(sup_src), "-m", "uvicorn", "main:app", "--port", "8010", "--reload"],
                               stdout=out, stderr=out)
    worker = None
    try:
        for _ in range(100):
            if ready.exists():
                break
            time.sleep(0.05)
        time.sleep(0.2)
        assert '"stack_dump_signal": "SIGUSR1"' in log.read_text()
        out = subprocess.run(["pgrep", "-P", str(sup.pid)], capture_output=True, text=True, check=False).stdout.split()
        worker = int(out[0])
        (wd / ".pids" / "ui-api.pid").write_text(str(sup.pid))         # start-local.sh records the supervisor
        stubs = 'diag_sample() { echo s > "$2"; }; diag_lsof() { echo l > "$2"; }; '
        r = wsh(wd, stubs + f"capture_hang ui-api 000 {sup.pid} {worker}", stubs=False)
        assert r.returncode == 0, r.stderr
        summary = (Path(r.stdout.strip()) / "summary.txt").read_text()
        assert sup.poll() is None, "the --reload supervisor must survive the capture"
        assert f"py-stacks {sup.pid}: not requested" in summary and f"py-stacks {worker}: not requested" in summary
    finally:
        if worker:
            subprocess.run(["kill", "-9", str(worker)], check=False)
        sup.kill()
        sup.wait()


def test_a_dry_run_leaves_the_hang_restart_record_alone(wd):
    """WATCHDOG_DRY_RUN=1 'changes nothing': the hourly-cap check used to prune .pids/watchdog/hang-restarts-<svc>."""
    rec = wd / ".pids" / "watchdog" / "hang-restarts-ui-api"
    rec.parent.mkdir(parents=True, exist_ok=True)
    old, new = int(time.time()) - 7200, int(time.time()) - 60
    rec.write_text(f"{old}\n{new}\n")
    r = wsh(wd, "recent_hang_restarts ui-api", {"WATCHDOG_DRY_RUN": "1"})
    assert r.stdout.strip() == "1" and rec.read_text() == f"{old}\n{new}\n"
    r = wsh(wd, "recent_hang_restarts ui-api")                       # a real run prunes the old line
    assert r.stdout.strip() == "1" and rec.read_text() == f"{new}\n"


# ── the off-machine dead-man ping (SECREL-02) ───────────────────────────────────────────────────────────────

class _PingServer:
    def __init__(self) -> None:
        self.paths: list[str] = []
        self.status = 200
        srv = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                srv.paths.append(self.path)
                self.send_response(srv.status)
                self.end_headers()
                self.wfile.write(b"OK")

            def log_message(self, *_a: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def test_the_dead_man_ping_reports_health_and_records_its_own_result(wd):
    srv = _PingServer()
    state = wd / ".pids" / "watchdog" / "deadman"
    try:
        (wd / ".env").write_text(f"HEALTHCHECK_PING_URL={srv.base}/uuid-123/\n")
        for s in ("data-service", "ui-api", "master-controller"):
            (wd / f"up-{s}").touch()
        wsh(wd, "main")
        assert srv.paths == ["/uuid-123"] and state.read_text().split()[1] == "ok"
        (wd / "up-ui-api").unlink()                               # unhealthy: a foreign program holds :8010
        (wd / "listen-ui-api").write_text("5151")
        (wd / "foreign-ui-api").touch()
        wsh(wd, "main")
        assert srv.paths[-1] == "/uuid-123/fail" and state.read_text().split()[1] == "fail"
        srv.status = 404                                          # a wrong check id: recorded, so status can say so
        wsh(wd, "main")
        assert state.read_text().split()[1] == "error"
        (wd / ".env").write_text("OTHER=1\n")
        wsh(wd, "main")
        assert not state.exists()
        assert "uuid-123" not in wlog(wd), "the ping URL is never logged"
    finally:
        srv.close()


def test_a_blocked_python_preflight_still_tells_the_dead_man_ping(wd):
    """The stack is down and the watchdog cannot start it (macOS blocks the stack's Python): /fail goes out on that
    run, instead of healthchecks.io noticing only after its grace time without pings."""
    srv = _PingServer()
    try:
        (wd / ".env").write_text(f"HEALTHCHECK_PING_URL={srv.base}/uuid-9\n")
        (wd / "up-data-service").touch()
        (wd / "up-master-controller").touch()                 # ui-api down, nothing listening: it needs a start
        wsh(wd, "main", env={"WATCHDOG_PYTHON": "/usr/bin/false"})
        assert "preflight FAILED" in wlog(wd) and calls(wd) == []
        assert srv.paths == ["/uuid-9/fail"]
        assert (wd / ".pids" / "watchdog" / "deadman").read_text().split()[1] == "fail"
    finally:
        srv.close()


def test_the_documented_hang_timing_is_the_same_everywhere():
    """R-OPS-12: the RUNBOOK, `status` and Telegram /status all give the watchdog's real hang-restart timing (two hung
    runs 2 min apart, each 8 + 30 + 8 s of probes, a last probe, the capture, then the restart): about 3.5–5.5 min."""
    for rel in ("docs/RUNBOOK_RESTORE.md", "start-local.sh", "scripts/master_controller.py", "CLAUDE.md"):
        assert "3.5–5.5 min" in (ROOT / rel).read_text(), rel
    runbook = (ROOT / "docs" / "RUNBOOK_RESTORE.md").read_text()
    assert "2.5–4.5 min" not in runbook and "~4–6 min" not in (ROOT / "scripts" / "master_controller.py").read_text()
    # the desktop side says the same (round 3 review: health.rs, lib.rs, boot.js and the README still said "about
    # 4 min" until patch requests 5-11 landed; nothing enforced it)
    desktop = ("desktop/src-tauri/src/health.rs", "desktop/src-tauri/src/lib.rs", "desktop/boot/boot.js",
               "desktop/README.md")
    for rel in desktop:
        f = ROOT / rel
        if not f.exists():
            continue                                                   # a partial checkout without desktop/
        text = f.read_text()
        assert "3.5–5.5 min" in text and "about 4 min" not in text, rel


def _gh_slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped (letters, digits, '-', '_' and spaces kept), spaces → '-'."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def test_the_runbook_owner_actions_are_written_down_and_every_link_resolves():
    """SECREL-02, completeness-final-01/-04: the owner's one-time steps exist with their exact commands, and every
    in-page link (status, Telegram /status and the RUNBOOK point at these sections) lands on a heading."""
    text = (ROOT / "docs" / "RUNBOOK_RESTORE.md").read_text()
    slugs = {_gh_slug(h) for h in re.findall(r"^#{1,6} +(.+)$", text, flags=re.MULTILINE)}
    links = set(re.findall(r"\]\(#([^)]+)\)", text))
    assert links and links <= slugs, sorted(links - slugs)
    for anchor in ("off-machine-dead-man-ping-healthchecksio", "unattended-reboots-power-cuts-macos-updates-filevault",
                   "version-control-and-off-machine-backup", "first-trading-day-after-a-deploy-checklist"):
        assert anchor in slugs, anchor
    for step in ("| HEALTHCHECK_PING_URL |", "https://hc-ping.com/<uuid>", "sudo pmset -a autorestart 1",
                 "AutomaticallyInstallMacOSUpdates", "sudo fdesetup authrestart", "git remote add origin",
                 "git push -u origin --all && git push origin --tags", "git tag -a desktop-20261025",
                 "sudo tmutil setdestination", "chmod 600 .env", "Stop :3000 **right after** the import"):
        assert step in text, step
    # the names start-local.sh's status rows send the owner to are real headings
    sl = (ROOT / "start-local.sh").read_text()
    for name in ("Off-machine dead-man ping", "Unattended reboots"):
        assert f"RUNBOOK_RESTORE.md '{name}'" in sl and f"## {name}" in text, name


def _icici_admin():
    """services/ui-api/icici_admin.py (the Broker tab's .env writer), loaded by path under a private name."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_desktop_ops_icici_admin", ROOT / "services" / "ui-api" / "icici_admin.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _runbook_env_check() -> str:
    text = (ROOT / "docs" / "RUNBOOK_RESTORE.md").read_text()
    m = re.search(r"/Users/sudheer/Desktop/jupyter_env/bin/python - << 'EOF'\n(.*?)\nEOF\n", text, re.DOTALL)
    assert m, "RUNBOOK §2 lost its .env read-back check"
    return m.group(1)


def test_the_runbook_env_quoting_advice_is_what_the_readers_and_the_broker_tab_do(tmp_path):
    """SECREL-03 (round 3 review, not really fixed): §2 told the owner that python-dotenv reads single-quoted values
    literally and gave ICICI_PASSWORD='pa#ss${x}' as the safe form; python-dotenv expands ${…} in every quoting style,
    so that password reads back as 'pa#ss' and the 08:00 login fails. Every example §2 now gives must read back as it
    says, through python-dotenv and the plain parser, and be the form the Broker tab's writer (icici_admin.
    encode_env_line, P13) picks; the '${' case must be refused there too."""
    from dotenv import dotenv_values

    adm = _icici_admin()
    s2 = _section((ROOT / "docs" / "RUNBOOK_RESTORE.md").read_text(), "## 2. ")
    assert "reads single-quoted values literally" not in s2
    examples = {"ICICI_PASSWORD=pa#ss": "pa#ss", "ICICI_PASSWORD='pa #ss'": "pa #ss",
                'ICICI_PASSWORD="it\'s #1"': "it's #1"}
    for line, value in examples.items():
        assert f"`{line}`" in s2, line
        env = tmp_path / f"e{len(value)}.env"
        env.write_text(line + "\n")
        assert dotenv_values(env)["ICICI_PASSWORD"] == value, line
        assert adm.plain_env_value(line.split("=", 1)[1]) == value, line
        assert adm.encode_env_line("ICICI_PASSWORD", value) == line, "the Broker tab writes the same form"
    bad = "ICICI_PASSWORD='pa#ss${x}'"
    assert f"`{bad}`" in s2 and "reads back as `pa#ss`" in s2
    env = tmp_path / "bad.env"
    env.write_text(bad + "\n")
    assert dotenv_values(env)["ICICI_PASSWORD"] == "pa#ss", "what §2 warns about"
    assert "${" in (adm.env_value_problem("pa#ss${x}", "ICICI_PASSWORD") or ""), "the Broker tab refuses it"
    for key in adm.RAW_READ_ENV_KEYS:
        assert f"`{key}`" in s2, f"{key} must stay unquoted"


def test_the_runbook_env_check_names_misread_keys_and_never_prints_a_value(tmp_path):
    """The §2 read-back check, run as written: OK on the §2 forms (and on .env.example as shipped), names every key
    the readers disagree on, and never prints a value."""
    check = tmp_path / "check.py"
    check.write_text(_runbook_env_check() + "\n")

    def run(env_text: str) -> str:
        (tmp_path / ".env").write_text(env_text)
        r = subprocess.run([sys.executable, str(check)], cwd=tmp_path, capture_output=True, text=True, timeout=60,
                           check=False)
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    good = "ICICI_PASSWORD='pa #ss'\nICICI_CLIENT_ID=pa#ss1\nICICI_MOBILE=\"it's #1\"\nTELEGRAM_CHAT_ID=42\nTICK_PERSIST=1  # c\n"
    assert run(good) == "OK: every reader sees the same values"
    assert run((ROOT / ".env.example").read_text()) == "OK: every reader sees the same values"
    secrets = ("pa#ss", "s3cr3t", "999")
    out = run("ICICI_PASSWORD='pa#ss${x}'\nICICI_API_SECRET='s3cr3t'\nTELEGRAM_CHAT_ID=999 # mine\nICICI_CLIENT_ID=ok\n")
    assert out == "FIX (read differently): ICICI_API_SECRET ICICI_PASSWORD TELEGRAM_CHAT_ID", out
    assert not any(s in out for s in secrets)


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = text.find("\n## ", start + len(heading))
    return text[start:nxt if nxt != -1 else len(text)]


def test_crash_relaunch_is_described_the_same_in_the_runbook_claude_md_and_status():
    """SECREL-06 / R-RUST-05 (round 3 crash guard): RUNBOOK §5, CLAUDE.md and `status` say what the app does now.
    A copy launchd started is relaunched by KeepAlive; a copy opened by hand runs a crash guard; only when neither
    applies (an older build, a guard that could not start) does status give the quit-and-kickstart remedy, and §5
    must still document that remedy (round 4: the round-3 RUNBOOK edit dropped it while status kept pointing there)."""
    runbook = (ROOT / "docs" / "RUNBOOK_RESTORE.md").read_text()
    claude = (ROOT / "CLAUDE.md").read_text()
    sl = (ROOT / "start-local.sh").read_text()
    s5 = _section(runbook, "## 5. ")
    name = re.search(r'pub const GUARD_NAME: &str = "([^"]+)";', SUPERVISE_RS.read_text()).group(1)
    assert f"`{name}`" in s5 and f"`{name}`" in claude and f'"{name} $pid "' in sl, name
    # every supervision phrase the desktop-app row can print is explained in the RUNBOOK's status section
    row = sl[sl.index("app_status_row() {"):sl.index("\n}\n", sl.index("app_status_row() {"))]
    phrases = re.findall(r'sup=" · ([^"]+)"', row)
    assert len(phrases) == 4, phrases
    for p in phrases:
        assert f"`{p}`" in _section(runbook, "## 4. ").replace("\n  ", " "), p
    # the remedy status prints is the one §5 documents, with the fallback when the job is not loaded
    hint = re.search(r"to have launchd supervise it: quit the app \(⌘Q\), then (launchctl kickstart gui/\$\(id -u\)/\w+)",
                     row)
    assert hint and "(RUNBOOK §5)" in row
    assert hint.group(1) in s5 and "launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/SuryaDhana.plist" in s5
    # CLAUDE.md no longer claims a copy opened by hand is unsupervised until the next login (true only before round 3)
    line = next(ln for ln in claude.splitlines() if ln.startswith("**SuryaDhana.app** starts at login"))
    assert "not supervised until the next login" not in line and "crash guard" in line and "RUNBOOK §5" in line


def test_main_restarts_a_hung_service_and_still_starts_a_dead_one(wd):
    """End to end through main(): ui-api hung (listening, unhealthy), data-service dead (no listener),
    master-controller healthy. Before this change the hung one only produced 'FAILED to start'."""
    (wd / "listen-ui-api").write_text("4242")
    (wd / "up-master-controller").touch()
    r = wsh(wd, "main")
    assert r.returncode == 0, r.stderr
    assert calls(wd) == ["start data-service", "rotate-logs"], "run 1: the dead one is started, the hung one counted"
    assert "ui-api is listening (pid 4242) but /health did not answer: hung check 1/2" in wlog(wd)
    assert "ui-api FAILED to start" not in wlog(wd) and "ui-api is down" not in wlog(wd)
    r = wsh(wd, "main")
    assert r.returncode == 0, r.stderr
    assert calls(wd)[2:] == ["restart ui-api"], calls(wd)
    assert "ui-api restarted after a hang" in wlog(wd)
    r = wsh(wd, "main")                                    # everything healthy: nothing to do, no counters left
    assert calls(wd)[3:] == [] and not list((wd / ".pids" / "watchdog").glob("hung-*"))


def test_a_recovered_or_paused_service_loses_its_hang_count(wd):
    (wd / "listen-ui-api").write_text("4242")
    (wd / "up-data-service").touch()
    (wd / "up-master-controller").touch()
    wsh(wd, "main")
    assert (wd / ".pids" / "watchdog" / "hung-ui-api").exists()
    (wd / "up-ui-api").touch()                             # it answers again on its own
    wsh(wd, "main")
    assert not (wd / ".pids" / "watchdog" / "hung-ui-api").exists() and "restart ui-api" not in calls(wd)
    (wd / "up-ui-api").unlink()
    (wd / ".pids" / "paused").mkdir()
    (wd / ".pids" / "paused" / "ui-api").touch()            # stopped on purpose: never counted or restarted
    wsh(wd, "main; main; main")
    assert "restart ui-api" not in calls(wd) and not (wd / ".pids" / "watchdog" / "hung-ui-api").exists()


@pytest.mark.skipif(not Path("/usr/bin/sample").exists(), reason="macOS /usr/bin/sample not available")
def test_real_diagnostics_capture_a_live_process(wd):
    p = subprocess.Popen(["/bin/sleep", "30"])
    try:
        r = wsh(wd, f"capture_hang ui-api 000 {p.pid}", stubs=False)
        assert r.returncode == 0, r.stderr
        cap = Path(r.stdout.strip())
        assert cap.parent == wd / ".logs" / "hangs"
        assert "Analysis of sampling sleep" in (cap / f"sample-{p.pid}.txt").read_text()
        assert "/bin/sleep" in (cap / f"lsof-{p.pid}.txt").read_text()
        assert "sleep 30" in (cap / "summary.txt").read_text()
    finally:
        p.kill()
        p.wait()


# the hung process for the end-to-end test: it listens but never accepts, so a /health connect sits in the backlog
# and nothing ever answers (the 25 Oct symptom). Its command line carries "uvicorn … --port N" like the real one.
HUNG_LISTENER = """import socket, sys, time
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[2])))
s.listen(16)
open(sys.argv[3], "w").write("listening")
time.sleep(300)
"""
E2E_START_LOCAL = """#!/bin/bash
# like start-local.sh for ONE service on the test's own port: `start` says "already running" when the port has a
# listener (start_one), `restart` stops the listener and starts a healthy server (an http.server with /health)
here="$(cd "$(dirname "$0")" && pwd)"; port=$(cat "$here/e2e-port")
echo "$*" >> "$here/start-local.calls"
case "$1" in
  start) lsof -nP -tiTCP:"$port" -sTCP:LISTEN > /dev/null 2>&1 && { echo "$2 already running on $port"; exit 0; }; exit 1 ;;
  restart)
    for p in $(lsof -nP -tiTCP:"$port" -sTCP:LISTEN); do kill -9 "$p"; done
    sleep 0.5
    (cd "$here/www" && nohup "$E2E_PY" -m http.server --bind 127.0.0.1 "$port" > /dev/null 2>&1 < /dev/null &
     echo $! > "$here/healthy.pid")
    for _ in $(seq 1 50); do curl -sf -m 1 "http://127.0.0.1:$port/health" > /dev/null && exit 0; sleep 0.1; done
    exit 1 ;;
esac
exit 0
"""


@pytest.mark.skipif(not Path("/usr/bin/sample").exists(), reason="macOS /usr/bin/sample not available")
def test_end_to_end_a_real_hung_listener_is_captured_and_restarted(wd, tmp_path):
    """Real processes, real curl / lsof / ps / sample, real main(): only the port (an ephemeral one), the fake
    start-local.sh and CORE=ui-api are the test's. Run 1 counts the hang, run 2 captures and restarts it."""
    port = _free_port()
    (wd / "e2e-port").write_text(str(port))
    (wd / "www").mkdir()
    (wd / "www" / "health").write_text("ok")
    fake = wd / "start-local.sh"
    fake.write_text(E2E_START_LOCAL)
    fake.chmod(0o755)
    hung_py = tmp_path / "uvicorn_hung.py"
    hung_py.write_text(HUNG_LISTENER)
    ready = tmp_path / "ready"
    hung = subprocess.Popen([sys.executable, str(hung_py), "--port", str(port), str(ready)])
    stubs = (f'CORE=ui-api; svc_port() {{ echo {port}; }}; health_url() {{ echo "http://127.0.0.1:{port}/health"; }}; '
             'start_local_running() { return 1; }; login_running() { return 1; }; ')
    env = {"WATCHDOG_HEALTH_TIMEOUT_S": "1", "E2E_PY": sys.executable}
    try:
        for _ in range(50):
            if ready.exists():
                break
            time.sleep(0.1)
        r = wsh(wd, stubs + "main", env, stubs=False)
        assert r.returncode == 0, r.stderr
        assert calls(wd) == ["rotate-logs"] and hung.poll() is None, "run 1: counted, not restarted"
        assert f"ui-api is listening (pid {hung.pid}) but /health did not answer: hung check 1/2" in wlog(wd)
        r = wsh(wd, stubs + "main", env, stubs=False)
        assert r.returncode == 0, r.stderr
        assert calls(wd)[1:] == ["restart ui-api"], calls(wd)         # (rotate-logs is hourly)
        hung.wait(timeout=10)                                       # the restart stopped the hung process
        log = wlog(wd)
        assert "ui-api restarted after a hang" in log
        assert "alert: ⚠️ SuryaDhana: ui-api was hung (listening, /health timed out): restarted." in log
        (cap,) = captures(wd)
        summary = (cap / "summary.txt").read_text()
        assert f"listener pid(s): {hung.pid}" in summary and "uvicorn_hung.py --port" in summary
        assert "Call graph" in (cap / f"sample-{hung.pid}.txt").read_text()
        assert f":{port} (LISTEN)" in (cap / f"lsof-{hung.pid}.txt").read_text()
        assert (cap / "log-tail.txt").read_text().splitlines()[-1] == "line 499"
        r = wsh(wd, stubs + "main", env, stubs=False)               # healthy now: nothing more to do
        assert calls(wd)[2:] == [] and not list((wd / ".pids" / "watchdog").glob("hung-*"))
    finally:
        if hung.poll() is None:
            hung.kill()
            hung.wait()
        pidf = wd / "healthy.pid"
        if pidf.exists():
            subprocess.run(["kill", "-9", pidf.read_text().strip()], check=False)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _ipv6_loopback() -> bool:
    try:
        with socket.socket(socket.AF_INET6) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _ipv6_loopback(), reason="no IPv6 loopback")
def test_end_to_end_a_foreign_ipv6_listener_neither_answers_for_nor_dies_with_a_hung_service(wd, tmp_path):
    """R-OPS-05 as the reviewer reproduced it: a hung 'uvicorn … --port P' on 127.0.0.1 plus another program's HTTP
    server on [::1]:P. Before, the localhost probe got the foreign 404 ('answered HTTP 404') and `start-local.sh
    restart` would have killed both. Now: probed on 127.0.0.1 (no answer), both listeners seen, the foreign one makes
    it alert-only, and nothing is restarted or killed. Real processes, curl, lsof and ps; only the port is the test's."""
    port = _free_port()
    (wd / "e2e-port").write_text(str(port))
    fake = wd / "start-local.sh"
    fake.write_text(E2E_START_LOCAL)
    fake.chmod(0o755)
    hung_py = tmp_path / "uvicorn_hung.py"
    hung_py.write_text(HUNG_LISTENER)
    ready = tmp_path / "ready"
    hung = subprocess.Popen([sys.executable, str(hung_py), "--port", str(port), str(ready)])
    www = tmp_path / "www"
    www.mkdir()
    foreign = subprocess.Popen([sys.executable, "-m", "http.server", "--bind", "::1", str(port)], cwd=www,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    stubs = (f'CORE=ui-api; svc_port() {{ echo {port}; }}; '
             'start_local_running() { return 1; }; login_running() { return 1; }; ')
    try:
        for _ in range(100):
            v6 = subprocess.run(["curl", "-s", "-o", "/dev/null", "-m", "1", "-w", "%{http_code}",
                                 f"http://[::1]:{port}/health"], capture_output=True, text=True, check=False).stdout
            if ready.exists() and v6 == "404":
                break
            time.sleep(0.1)
        assert v6 == "404", "the foreign IPv6 server answers"
        r = wsh(wd, stubs + "main; ", {"WATCHDOG_HEALTH_TIMEOUT_S": "1"}, stubs=False)
        assert r.returncode == 0, r.stderr
        r = wsh(wd, stubs + "main; ", {"WATCHDOG_HEALTH_TIMEOUT_S": "1"}, stubs=False)
        assert r.returncode == 0, r.stderr
        assert [c for c in calls(wd) if c != "rotate-logs"] == [], "never restarted"
        assert hung.poll() is None and foreign.poll() is None, "nothing was stopped"
        log = wlog(wd)
        assert f"ui-api does not answer /health and port {port} is held by another program (pid {foreign.pid}:" in log
        assert "answered HTTP 404" not in log and "hung check" not in log
    finally:
        for p in (hung, foreign):
            if p.poll() is None:
                p.kill()
                p.wait()
