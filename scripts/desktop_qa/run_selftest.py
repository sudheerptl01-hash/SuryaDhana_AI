"""Desktop E2E driver for SuryaDhana.app (reports/desktop_app/PLAN.md AC-4, AC-5, AC-7, AC-13).

Checks (each PASS / FAIL / SKIP, with evidence):

* ``bundle``        the .app exists; Info.plist ``CFBundleIdentifier == ai.suryadhana.terminal``; bundle size
                    < ``--max-mb`` (25 MiB)
* ``codesign``      ``codesign --verify --deep --strict`` passes (ad-hoc is fine; the signature kind is reported)
* ``autostart``     the login LaunchAgent written by tauri-plugin-autostart (read only): plist path, label,
                    program, whether it points at THIS app, ``launchctl print gui/<uid>/<label>`` loaded state.
                    ``--expect-autostart on|off|any`` (default any = report only)
* ``self_test``     ``<app>/Contents/MacOS/<exe> --self-test <out.json>`` with a timeout; the JSON must say every
                    check is ok (accepted shapes: D2's ``{"passed":bool,"checks":[{"name","ok","detail","ms"}],
                    "meta":{}}``, ``{"ok":bool,"checks":[...]}``, ``{"checks":{name:{"ok":bool}}}`` or
                    ``{"checks":{name:bool}}``; if the file is not written the last JSON object on stdout is used).
                    D2's self-test runs isolated (temp state, no single-instance lock, autostart only read).
* ``single_instance`` + ``idle_resources`` (opt-in, ``--live``: they need a NORMAL launch). The launch sets
                    ``SURYADHANA_NO_AUTOSTART=1`` so the app's first-run "enable Launch at Login" never runs
                    from the harness (``--allow-autostart-change`` to drop it). A normal launch still saves the
                    app's own window/session state under ~/Library/Application Support/ai.suryadhana.terminal
                    (reported). Both launches go through LaunchServices (``open -n -g --env ...``) like a login
                    item, so the app is its own "responsible process" (a Terminal-spawned child is not, and
                    its WebKit helpers would be attributed to Terminal). Launch A, wait ``--warmup`` s, sample
                    RSS + phys_footprint + CPU of A and its WebKit XPC processes (WebContent / Networking / GPU,
                    attributed exactly via macOS ``responsibility_get_pid_responsible_for_pid``) for ``--idle``
                    s, then launch B and assert B exits on its own while A stays the only instance.

``--ui-url URL`` sets ``SURYADHANA_UI_URL`` for every launch (D2's override of the terminal origin, default
http://127.0.0.1:8010): before switchover the live ui-api does not serve the static UI yet, so the self-test's
remote-page checks need a scratch same-origin server (``scratch_server.py``) instead.

Safety: refuses to launch anything while another SuryaDhana process is running (the owner's app is never
touched); every process it starts is tracked and terminated in ``finally`` (SIGTERM, then SIGKILL), plus a
sweep for any process of THIS bundle's executable that appeared during the run. The LaunchAgent state is
snapshotted before/after a live run and differences are reported (never modified).

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/run_selftest.py [--app PATH] [--live] [--out DIR]
Exit code: 0 = no FAIL (SKIPs allowed unless --require-app), 1 = a FAIL, 2 = bad arguments.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
IDENTIFIER = "ai.suryadhana.terminal"
APP_NAME = "SuryaDhana.app"
CANDIDATES = (
    ROOT / "desktop" / "src-tauri" / "target" / "release" / "bundle" / "macos" / APP_NAME,
    ROOT / "desktop" / "src-tauri" / "target" / "debug" / "bundle" / "macos" / APP_NAME,
    Path("/Applications") / APP_NAME,
    Path.home() / "Applications" / APP_NAME,
)
LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
STACK_AGENTS = {"com.suryadhana.watchdog", "com.suryadhana.awake"}   # the stack's own agents, not the app's
WEBKIT_XPC_PREFIX = "com.apple.WebKit."


@dataclass
class Check:
    name: str
    status: str = "SKIP"           # PASS | FAIL | SKIP | WARN
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status, "detail": self.detail, "evidence": self.evidence}


# ── discovery / static facts ─────────────────────────────────────────────────────────────────────

def find_app(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_dir() else None
    return next((p for p in CANDIDATES if p.is_dir()), None)


def read_info_plist(app: Path) -> dict[str, Any]:
    with open(app / "Contents" / "Info.plist", "rb") as f:
        return plistlib.load(f)


def bundle_bytes(app: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(app):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


def check_bundle(app: Path, max_mb: float) -> tuple[Check, dict[str, Any]]:
    c = Check("bundle")
    try:
        info = read_info_plist(app)
    except Exception as exc:
        c.status, c.detail = "FAIL", f"Info.plist unreadable: {exc}"
        return c, {}
    size = bundle_bytes(app)
    exe = info.get("CFBundleExecutable")
    c.evidence = {"path": str(app), "identifier": info.get("CFBundleIdentifier"), "executable": exe,
                  "version": info.get("CFBundleShortVersionString"), "min_macos": info.get("LSMinimumSystemVersion"),
                  "bytes": size, "mib": round(size / 1048576, 2), "max_mib": max_mb}
    problems = []
    if info.get("CFBundleIdentifier") != IDENTIFIER:
        problems.append(f"identifier {info.get('CFBundleIdentifier')!r} != {IDENTIFIER!r}")
    if size >= max_mb * 1048576:
        problems.append(f"bundle {size / 1048576:.1f} MiB >= {max_mb} MiB")
    if not exe or not (app / "Contents" / "MacOS" / exe).is_file():
        problems.append(f"executable {exe!r} missing")
    c.status, c.detail = ("FAIL", "; ".join(problems)) if problems else ("PASS", f"{size / 1048576:.1f} MiB, {IDENTIFIER}")
    return c, info


def check_codesign(app: Path) -> Check:
    c = Check("codesign")
    r = subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
                       capture_output=True, text=True, timeout=120, check=False)
    d = subprocess.run(["codesign", "-dv", "--verbose=2", str(app)], capture_output=True, text=True, timeout=60,
                       check=False)
    meta = {k.strip(): v.strip() for line in d.stderr.splitlines() if "=" in line for k, v in [line.split("=", 1)]}
    c.evidence = {"verify_rc": r.returncode, "verify_out": (r.stderr or r.stdout).strip()[-400:],
                  "signature": meta.get("Signature") or ("adhoc" if "adhoc" in d.stderr else None),
                  "identifier": meta.get("Identifier"), "team": meta.get("TeamIdentifier"),
                  "flags": next((x for x in d.stderr.split() if x.startswith("flags=")), None)}
    c.status = "PASS" if r.returncode == 0 else "FAIL"
    c.detail = "valid on disk, satisfies its Designated Requirement" if r.returncode == 0 else c.evidence["verify_out"]
    return c


def launch_agent_state(app: Path | None, exe: str | None) -> list[dict[str, Any]]:
    """LaunchAgents that launch a SuryaDhana .app (not the stack's watchdog/awake agents). Read only."""
    out = []
    target = str((app / "Contents" / "MacOS" / exe).resolve()) if app and exe else None
    for p in sorted(LAUNCH_AGENTS.glob("*.plist")):
        try:
            with open(p, "rb") as f:
                pl = plistlib.load(f)
        except Exception:
            continue
        label = str(pl.get("Label", ""))
        args = pl.get("ProgramArguments") or ([pl["Program"]] if pl.get("Program") else [])
        prog = str(args[0]) if args else ""
        if label in STACK_AGENTS:
            continue
        if ".app/Contents/MacOS/" not in prog or ("suryadhana" not in prog.lower() and "suryadhana" not in label.lower()):
            continue
        loaded = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True,
                                text=True, timeout=10, check=False).returncode == 0
        out.append({"plist": str(p), "label": label, "program": prog, "args": [str(a) for a in args[1:]],
                    "run_at_load": bool(pl.get("RunAtLoad")), "loaded": loaded,
                    "points_to_this_app": bool(target) and os.path.realpath(prog) == target,
                    "mtime": datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).astimezone()
                    .isoformat(timespec="seconds")})
    return out


def check_autostart(app: Path, exe: str | None, expect: str) -> Check:
    c = Check("autostart")
    agents = launch_agent_state(app, exe)
    mine = [a for a in agents if a["points_to_this_app"]]
    c.evidence = {"agents": agents, "expect": expect}
    on = bool(mine) and all(a["run_at_load"] for a in mine)
    if expect == "any":
        c.status = "PASS"
        c.detail = f"report only: {'enabled' if on else 'not enabled'} ({len(agents)} SuryaDhana app agent(s))"
    elif expect == "on":
        ok = on and any(a["loaded"] for a in mine)
        c.status = "PASS" if ok else "FAIL"
        c.detail = "plist points at this app, RunAtLoad, loaded" if ok else f"expected autostart on: {agents or 'no plist'}"
    else:
        c.status = "PASS" if not mine else "FAIL"
        c.detail = "no login agent for this app" if not mine else f"expected off but found {mine}"
    return c


# ── processes ────────────────────────────────────────────────────────────────────────────────────

def _psutil() -> Any:
    import psutil
    return psutil


def suryadhana_processes(exe_name: str | None = None) -> list[dict[str, Any]]:
    """Every running SuryaDhana app process (any bundle location)."""
    ps = _psutil()
    out = []
    for p in ps.process_iter(["pid", "name", "exe", "status"]):
        if p.info.get("status") == ps.STATUS_ZOMBIE:   # exited, merely not reaped yet: not a running instance
            continue
        exe = p.info.get("exe") or ""
        if ("SuryaDhana.app/Contents/MacOS/" in exe) or (exe_name and p.info.get("name") == exe_name
                                                          and ".app/Contents/MacOS/" in exe):
            out.append({"pid": p.pid, "exe": exe})
    return out


def responsible_pid(pid: int) -> int | None:
    """macOS 'responsible process' of ``pid`` (how Activity Monitor attributes WebKit XPC services)."""
    try:
        f = ctypes.CDLL(None).responsibility_get_pid_responsible_for_pid
        f.argtypes, f.restype = [ctypes.c_int], ctypes.c_int
        r = f(pid)
        return r if r > 0 else None
    except Exception:
        return None


class _RUsage(ctypes.Structure):
    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
        "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups", "ri_pageins", "ri_wired_size",
        "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime", "ri_proc_exit_abstime",
        "ri_child_user_time", "ri_child_system_time", "ri_child_pkg_idle_wkups", "ri_child_interrupt_wkups",
        "ri_child_pageins", "ri_child_elapsed_abstime", "ri_diskio_bytesread", "ri_diskio_byteswritten")]


def phys_footprint(pid: int) -> int | None:
    """Activity Monitor's 'Memory' (phys_footprint) via proc_pid_rusage(RUSAGE_INFO_V2)."""
    try:
        lib = ctypes.CDLL("/usr/lib/libproc.dylib")
        lib.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
        ru = _RUsage()
        return int(ru.ri_phys_footprint) if lib.proc_pid_rusage(pid, 2, ctypes.byref(ru)) == 0 else None
    except Exception:
        return None


def app_process_tree(app_pid: int) -> list[Any]:
    """The app, its children, and the WebKit XPC services macOS attributes to it."""
    ps = _psutil()
    procs: dict[int, Any] = {}
    try:
        root = ps.Process(app_pid)
        procs[root.pid] = root
        for ch in root.children(recursive=True):
            procs[ch.pid] = ch
    except ps.Error:
        return []
    for p in ps.process_iter(["name"]):
        if (p.info.get("name") or "").startswith(WEBKIT_XPC_PREFIX) and responsible_pid(p.pid) == app_pid:
            procs[p.pid] = p
    return list(procs.values())


def sample_resources(app_pid: int, seconds: float, interval: float = 1.0) -> dict[str, Any]:
    """Peak/mean RSS + footprint and mean CPU% (cumulative CPU-time delta / wall) over ``seconds``."""
    ps = _psutil()
    t_start = time.monotonic()
    cpu0: dict[int, float] = {}
    for p in app_process_tree(app_pid):
        try:
            ct = p.cpu_times()
            cpu0[p.pid] = ct.user + ct.system
        except ps.Error:
            pass
    rss_series, fp_series, last_tree = [], [], []
    while time.monotonic() - t_start < seconds:
        tree = app_process_tree(app_pid)
        if not tree:
            break
        rss = fp = 0
        rows = []
        for p in tree:
            try:
                r = p.memory_info().rss
                f = phys_footprint(p.pid) or 0
                rss, fp = rss + r, fp + f
                rows.append({"pid": p.pid, "name": p.name(), "rss_mb": round(r / 1048576, 1), "footprint_mb": round(f / 1048576, 1)})
            except ps.Error:
                continue
        rss_series.append(rss)
        fp_series.append(fp)
        last_tree = rows
        time.sleep(interval)
    wall = time.monotonic() - t_start
    cpu_total = 0.0
    for p in app_process_tree(app_pid):
        try:
            ct = p.cpu_times()
            cpu_total += (ct.user + ct.system) - cpu0.get(p.pid, ct.user + ct.system)
        except ps.Error:
            pass
    mb = lambda xs: round(max(xs) / 1048576, 1) if xs else None  # noqa: E731
    return {"seconds": round(wall, 1), "samples": len(rss_series), "processes": last_tree,
            "rss_mb_peak": mb(rss_series), "rss_mb_mean": round(sum(rss_series) / len(rss_series) / 1048576, 1) if rss_series else None,
            "footprint_mb_peak": mb(fp_series), "cpu_pct_mean": round(100 * cpu_total / wall, 2) if wall > 0 else None,
            "note": "CPU% = cumulative CPU-time delta / wall time over the window (processes alive at both ends)"}


class Launcher:
    """Starts app processes and guarantees they are gone afterwards.

    Two launch paths:

    * ``start`` (exec): a direct child in its own session (stdout captured, exit code known). Used for
      ``--self-test``. macOS then treats the LAUNCHING process (e.g. Terminal) as "responsible" for the app.
    * ``start_open`` (LaunchServices, ``open -n -g --env ...``): launched like Finder / a login item, so the
      app is its own responsible process and its WebKit XPC helpers are attributed to it, and the
      single-instance plugin sees a real second launch. The pid is found by executable path.
    """

    def __init__(self, exe_path: Path, env: dict[str, str] | None = None) -> None:
        self.exe_path = exe_path
        self.app_path = exe_path.parents[2] if len(exe_path.parents) > 2 else exe_path
        self.extra_env = dict(env or {})
        self.env = {**os.environ, **self.extra_env}
        self.procs: list[subprocess.Popen[bytes]] = []
        self.pids: list[int] = []
        self.preexisting = {p["pid"] for p in suryadhana_processes()}

    def start(self, *args: str, log: Path | None = None) -> subprocess.Popen[bytes]:
        out = open(log, "ab") if log else None  # noqa: SIM115 - handed to the child, closed right after spawn
        try:
            p = subprocess.Popen([str(self.exe_path), *args], stdout=out or subprocess.DEVNULL,
                                 stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True,
                                 env=self.env)
        finally:
            if out is not None:
                out.close()   # the child holds its own descriptor
        self.procs.append(p)
        return p

    def _mine(self) -> list[int]:
        target = os.path.realpath(self.exe_path)
        return [r["pid"] for r in suryadhana_processes() if os.path.realpath(r["exe"]) == target]

    def start_open(self, *args: str, log: Path | None = None, find_timeout_s: float = 15.0) -> int | None:
        """``open -n -g`` the bundle; returns the new process's pid (None if none appeared)."""
        known = set(self._mine()) | self.preexisting | set(self.pids)
        cmd = ["open", "-n", "-g"]
        for k, v in self.extra_env.items():
            cmd += ["--env", f"{k}={v}"]
        if log is not None:
            cmd += ["--stdout", str(log), "--stderr", str(log)]
        cmd.append(str(self.app_path))
        if args:
            cmd += ["--args", *args]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
        deadline = time.monotonic() + find_timeout_s
        while time.monotonic() < deadline:
            new = [pid for pid in self._mine() if pid not in known]
            if new:
                self.pids.append(new[0])
                return new[0]
            time.sleep(0.05)
        return None

    def cleanup(self) -> list[int]:
        """Terminate everything we started, then any new process of this executable. Returns killed pids."""
        killed: list[int] = []
        for p in self.procs:              # own children: terminate, then REAP (no zombies left behind)
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait(timeout=5)
                killed.append(p.pid)
        for pid in self.pids + [x for x in self._mine() if x not in self.preexisting]:
            if pid not in killed and _terminate(pid):
                killed.append(pid)
        return killed


def _terminate(pid: int, grace_s: float = 5.0) -> bool:
    """SIGTERM, wait up to ``grace_s``, then SIGKILL a process that is not our child. True if it was alive."""
    ps = _psutil()
    try:
        proc = ps.Process(pid)
        if proc.status() == ps.STATUS_ZOMBIE:
            return False
        proc.terminate()
    except ps.NoSuchProcess:
        return False
    try:
        proc.wait(timeout=grace_s)
    except ps.TimeoutExpired:
        with contextlib.suppress(ps.NoSuchProcess):
            proc.kill()
            proc.wait(timeout=grace_s)
    return True


def _alive(pid: int | None) -> bool:
    ps = _psutil()
    if pid is None:
        return False
    try:
        return ps.Process(pid).status() != ps.STATUS_ZOMBIE
    except ps.NoSuchProcess:
        return False


# ── self-test JSON ───────────────────────────────────────────────────────────────────────────────

def last_json_object(text: str) -> Any:
    """The last top-level JSON object in ``text`` (self-test reports may follow log lines)."""
    dec = json.JSONDecoder()
    found, i = None, 0
    while True:
        j = text.find("{", i)
        if j < 0:
            return found
        try:
            obj, end = dec.raw_decode(text, j)
            found, i = obj, end
        except ValueError:
            i = j + 1


def evaluate_selftest(report: Any) -> tuple[bool, list[str], int]:
    """(all_ok, failing check names / problems, number of checks) for an accepted self-test JSON shape."""
    if not isinstance(report, dict):
        return False, ["self-test output is not a JSON object"], 0
    checks = report.get("checks")
    items: list[tuple[str, bool]] = []
    if isinstance(checks, list):
        for i, c in enumerate(checks):
            if isinstance(c, dict):
                items.append((str(c.get("name") or c.get("id") or i), c.get("ok") is True
                              or str(c.get("status", "")).lower() in ("ok", "pass")))
    elif isinstance(checks, dict):
        for k, v in checks.items():
            items.append((str(k), v is True or (isinstance(v, dict) and (v.get("ok") is True
                                                                       or str(v.get("status", "")).lower() in ("ok", "pass")))))
    problems = [name for name, ok in items if not ok]
    if not items:
        problems.append("no checks in the self-test report")
    for key in ("ok", "passed"):   # D2 writes "passed"; either top-level verdict must be true when present
        if key in report and report[key] is not True:
            problems.append(f"top-level {key} is not true")
    return not problems, problems, len(items)


def check_self_test(exe_path: Path, timeout_s: float, workdir: Path, env: dict[str, str] | None = None) -> Check:
    c = Check("self_test")
    c.evidence["launch_env"] = dict(env or {})
    out_json = workdir / "selftest.json"
    out_json.unlink(missing_ok=True)
    log = workdir / "selftest_stdout.log"
    log.unlink(missing_ok=True)
    launcher = Launcher(exe_path, env=env)
    t0 = time.monotonic()
    try:
        proc = launcher.start("--self-test", str(out_json), log=log)
        try:
            rc = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            rc = None
    finally:
        killed = launcher.cleanup()     # a hung or straggling self-test never outlives this check
    elapsed = round(time.monotonic() - t0, 2)
    stdout = log.read_text(errors="replace") if log.is_file() else ""
    c.evidence["cleanup_terminated"] = killed
    if rc is None:
        c.status, c.detail = "FAIL", f"timed out after {timeout_s:g}s (terminated)"
        c.evidence["stdout_tail"] = stdout[-1500:]
        return c
    report = None
    if out_json.is_file():
        try:
            report = json.loads(out_json.read_text())
        except ValueError as exc:
            c.evidence["json_error"] = str(exc)
    if report is None:
        report = last_json_object(stdout)
    ok, problems, n = evaluate_selftest(report)
    c.evidence.update({"exit_code": rc, "elapsed_s": elapsed, "checks": n, "report_file": str(out_json),
                       "report": report, "stdout_tail": stdout[-1500:]})
    if rc != 0:
        problems.insert(0, f"exit code {rc}")
    c.status = "PASS" if ok and rc == 0 else "FAIL"
    c.detail = f"{n} checks ok in {elapsed}s" if c.status == "PASS" else "; ".join(problems)[:500]
    return c


# ── live (normal launch) checks ──────────────────────────────────────────────────────────────────

def live_checks(app: Path, exe_path: Path, exe_name: str | None, args: argparse.Namespace, workdir: Path) -> list[Check]:
    """Normal launches through LaunchServices (``open -n -g``), the way a login item starts the app."""
    si, res = Check("single_instance"), Check("idle_resources")
    before = launch_agent_state(app, exe_name)
    env = {} if args.allow_autostart_change else {"SURYADHANA_NO_AUTOSTART": "1"}
    env.update(_ui_env(args))
    launcher = Launcher(exe_path, env=env)
    try:
        a = launcher.start_open(log=workdir / "instance_a.log")
        if a is None:
            si.status = res.status = "FAIL"
            si.detail = res.detail = "first launch (open -n) produced no process within 15 s"
            return [si, res]
        time.sleep(args.warmup)
        if not _alive(a):
            si.status = res.status = "FAIL"
            si.detail = res.detail = f"first instance (pid {a}) exited during the {args.warmup:g}s warm-up"
            return [si, res]
        resp = responsible_pid(a)
        res.evidence = sample_resources(a, args.idle)
        res.evidence["responsible_pid"] = resp
        rss, cpu = res.evidence.get("rss_mb_peak"), res.evidence.get("cpu_pct_mean")
        problems = []
        if rss is None or rss >= args.max_rss_mb:
            problems.append(f"peak RSS {rss} MB (budget < {args.max_rss_mb})")
        if cpu is None or cpu >= args.max_cpu_pct:
            problems.append(f"mean CPU {cpu}% (budget < {args.max_cpu_pct})")
        helpers = [p for p in res.evidence.get("processes", []) if p["name"].startswith(WEBKIT_XPC_PREFIX)]
        res.status = "FAIL" if problems else ("PASS" if helpers else "WARN")
        res.detail = ("; ".join(problems) or (
            f"peak RSS {rss} MB · footprint {res.evidence.get('footprint_mb_peak')} MB · CPU {cpu}% over "
            f"{res.evidence['seconds']}s · app + {len(helpers)} WebKit helper(s)"
            + ("" if helpers else f" (no helper attributed: responsible pid {resp} != app {a})"))) + (
            f" · a START-UP sample ({args.warmup:g} s after launch), not idle: AC-13's idle number comes from "
            "desktop/scripts/measure_idle.py on the running app (screen unlocked, >= 5 min after launch)")
        res.evidence["sample_kind"] = "startup"
        b = launcher.start_open(log=workdir / "instance_b.log")
        deadline = time.monotonic() + args.second_timeout
        while b is not None and _alive(b) and time.monotonic() < deadline:
            time.sleep(0.1)
        b_exited = b is None or not _alive(b)
        alive_a = _alive(a)
        target = os.path.realpath(exe_path)
        running = [p for p in suryadhana_processes(exe_name) if os.path.realpath(p["exe"]) == target]
        si.evidence = {"launch": "open -n -g (LaunchServices)", "launch_env": env, "a_pid": a, "b_pid": b,
                       "b_seen": b is not None, "b_exited": b_exited, "a_alive": alive_a, "instances_running": running}
        ok = b_exited and alive_a and len(running) == 1
        si.status = "PASS" if ok else "FAIL"
        si.detail = ((f"second launch (pid {b}) exited on its own; pid {a} is the only instance" if b is not None else
                      "second launch was absorbed before a process could be observed; one instance running")
                     if ok else f"b_exited={b_exited} a_alive={alive_a} running={len(running)}")
    finally:
        killed = launcher.cleanup()
        leftovers = [p for p in suryadhana_processes(exe_name) if p["pid"] not in launcher.preexisting]
        after = launch_agent_state(app, exe_name)
        for c in (si, res):
            c.evidence.setdefault("cleanup", {"terminated": killed, "leftover_processes": leftovers})
        si.evidence["launch_agents_before"], si.evidence["launch_agents_after"] = before, after
        if not args.allow_autostart_change and _agents_key(before) != _agents_key(after):
            si.status = "FAIL"
            si.detail += "; the login LaunchAgent changed during a SURYADHANA_NO_AUTOSTART=1 launch"
        if leftovers:
            si.status = "FAIL"
            si.detail += f"; stray processes after cleanup: {leftovers}"
    return [si, res]


def _ui_env(args: argparse.Namespace) -> dict[str, str]:
    return {"SURYADHANA_UI_URL": args.ui_url} if args.ui_url else {}


def _agents_key(agents: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return sorted((a["plist"], a["label"], a["program"], a["run_at_load"], a["mtime"]) for a in agents)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="SuryaDhana.app E2E driver (--self-test, signing, size, autostart, live)")
    ap.add_argument("--app", default=None, help=f"path to {APP_NAME} (default: D2 build output, then /Applications)")
    ap.add_argument("--require-app", action="store_true", help="FAIL (not SKIP) when no app is found")
    ap.add_argument("--timeout", type=float, default=90.0, help="self-test timeout seconds")
    ap.add_argument("--max-mb", type=float, default=25.0, help="bundle size budget (MiB)")
    ap.add_argument("--expect-autostart", choices=["on", "off", "any"], default="any")
    ap.add_argument("--live", action="store_true", help="also run single-instance + 30 s idle resource sampling")
    ap.add_argument("--warmup", type=float, default=12.0)
    ap.add_argument("--idle", type=float, default=30.0)
    ap.add_argument("--second-timeout", type=float, default=15.0)
    ap.add_argument("--max-rss-mb", type=float, default=500.0)
    ap.add_argument("--max-cpu-pct", type=float, default=3.0)
    ap.add_argument("--allow-autostart-change", action="store_true",
                    help="--live launches WITHOUT SURYADHANA_NO_AUTOSTART=1 (lets first-run enable Launch at Login)")
    ap.add_argument("--ui-url", default=None,
                    help="SURYADHANA_UI_URL for the launches (e.g. a scratch server http://127.0.0.1:8092 before "
                         "switchover); default = the app's own (http://127.0.0.1:8010)")
    ap.add_argument("--skip-self-test", action="store_true")
    ap.add_argument("--out", default=None, help="directory for selftest_report.json (+ the app's self-test JSON)")
    args = ap.parse_args(argv)

    started = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    workdir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="suryadhana-selftest-"))
    workdir.mkdir(parents=True, exist_ok=True)
    checks: list[Check] = []
    app = find_app(args.app)
    if app is None:
        c = Check("bundle", "FAIL" if args.require_app else "SKIP",
                  f"no {APP_NAME} at {args.app or ', '.join(str(p) for p in CANDIDATES)} (D2 has not built it yet?)")
        checks.append(c)
    else:
        bundle, info = check_bundle(app, args.max_mb)
        checks.append(bundle)
        exe_name = info.get("CFBundleExecutable")
        exe_path = app / "Contents" / "MacOS" / (exe_name or "")
        checks.append(check_codesign(app))
        checks.append(check_autostart(app, exe_name, args.expect_autostart))
        running = suryadhana_processes(exe_name)
        if running:
            msg = f"another SuryaDhana is running {running}; not launching (never alongside a running app)"
            checks += [Check("self_test", "SKIP", msg)] + ([Check("single_instance", "SKIP", msg),
                                                             Check("idle_resources", "SKIP", msg)] if args.live else [])
        elif not exe_path.is_file():
            checks.append(Check("self_test", "FAIL", f"executable missing: {exe_path}"))
        else:
            checks.append(Check("self_test", "SKIP", "--skip-self-test") if args.skip_self_test
                          else check_self_test(exe_path, args.timeout, workdir, env=_ui_env(args)))
            if args.live:
                checks += live_checks(app, exe_path, exe_name, args, workdir)
    report = {"started_at": started, "finished_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
              "app": str(app) if app else None, "ui_url": args.ui_url, "checks": [c.as_dict() for c in checks],
              "ok": not any(c.status == "FAIL" for c in checks),
              "skipped": [c.name for c in checks if c.status == "SKIP"]}
    (workdir / "selftest_report.json").write_text(json.dumps(report, indent=2, default=str))
    for c in checks:
        print(f"{c.name:16} {c.status:5} {c.detail}")
    print(f"report: {workdir / 'selftest_report.json'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
