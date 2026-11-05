#!/usr/bin/env python3
"""Honest idle measurement of the RUNNING SuryaDhana.app (C-PERF-03, R-RUST-06). It never launches, quits or
signals anything: it only reads kernel accounting (libproc) of processes that already run.

    /Users/sudheer/Desktop/jupyter_env/bin/python desktop/scripts/measure_idle.py --seconds 600 \
        --json reports/desktop_app/perf/idle_<date>.json

How to get a number that means something (AC-13: < 3 % CPU, < 500 MB for one window):
  * the screen UNLOCKED and a terminal window VISIBLE (not hidden to the menu bar, not minimized): with the session
    locked macOS runs WebContent at background priority and WebKit paints nothing, so a locked sample says little
    about a trading day;
  * at least 5 minutes after the app started, and after any ui-api restart or UI release swap (the first minutes
    are page warm-up and cold server caches, not idle);
  * 600 s, then again with 3 windows open (⌘N), on BRF and on EQS.
The script warns when one of these is not met and says so in the JSON (``conditions``).

What it reports, per process of the app (the shell plus the WebKit WebContent / Networking / GPU helpers macOS
attributes to it via ``responsibility_get_pid_responsible_for_pid``, like Activity Monitor) and in total:
CPU % (CPU-time delta / wall time), wakeups per second (idle + interrupt wakeups: the energy cost of timers and
display links), phys_footprint (Activity Monitor's "Memory") peak and mean, RSS; and for the shell process the
busiest threads by name (CVDisplayLink, JavaScriptCore scavenger, tokio-rt-worker, main …), so a regression near
the budget can be attributed instead of read off one aggregate number.

``--pid`` measures a given process tree instead of finding SuryaDhana (e.g. ``--pid $$ --seconds 2`` as a smoke
test of the libproc decoding on any Mac).
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

APP_DEFAULT = "/Applications/SuryaDhana.app"
CPU_BUDGET_PCT = 3.0
MEM_BUDGET_MB = 500.0
SETTLE_S = 300
WEBKIT = "com.apple.WebKit."

_libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
_libc = ctypes.CDLL(None)

PROC_PIDLISTTHREADS = 6
PROC_PIDTHREADINFO = 5
RUSAGE_INFO_V4 = 4


class _Timebase(ctypes.Structure):
    _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]


def _ns_per_tick() -> float:
    tb = _Timebase()
    try:
        _libc.mach_timebase_info(ctypes.byref(tb))
        return tb.numer / tb.denom if tb.denom else 1.0
    except (AttributeError, OSError):
        return 1.0


NS_PER_TICK = _ns_per_tick()


class RUsageV4(ctypes.Structure):
    """struct rusage_info_v4 (<sys/resource.h>); only the leading fields are read."""

    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [(n, ctypes.c_uint64) for n in (
        "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups", "ri_pageins", "ri_wired_size",
        "ri_resident_size", "ri_phys_footprint", "ri_proc_start_abstime", "ri_proc_exit_abstime",
        "ri_child_user_time", "ri_child_system_time", "ri_child_pkg_idle_wkups", "ri_child_interrupt_wkups",
        "ri_child_pageins", "ri_child_elapsed_abstime", "ri_diskio_bytesread", "ri_diskio_byteswritten",
        "ri_cpu_time_qos_default", "ri_cpu_time_qos_maintenance", "ri_cpu_time_qos_background",
        "ri_cpu_time_qos_utility", "ri_cpu_time_qos_legacy", "ri_cpu_time_qos_user_initiated",
        "ri_cpu_time_qos_user_interactive", "ri_billed_system_time", "ri_serviced_system_time",
        "ri_logical_writes", "ri_lifetime_max_phys_footprint", "ri_instructions", "ri_cycles", "ri_billed_energy",
        "ri_serviced_energy", "ri_interval_max_phys_footprint", "ri_runnable_time")] + [
        ("ri_flags", ctypes.c_uint64), ("ri_reserved", ctypes.c_uint64 * 1)]


class ThreadInfo(ctypes.Structure):
    """struct proc_threadinfo (<sys/proc_info.h>)."""

    _fields_ = [("pth_user_time", ctypes.c_uint64), ("pth_system_time", ctypes.c_uint64),
                ("pth_cpu_usage", ctypes.c_int32), ("pth_policy", ctypes.c_int32), ("pth_run_state", ctypes.c_int32),
                ("pth_flags", ctypes.c_int32), ("pth_sleep_time", ctypes.c_int32), ("pth_curpri", ctypes.c_int32),
                ("pth_priority", ctypes.c_int32), ("pth_maxpriority", ctypes.c_int32),
                ("pth_name", ctypes.c_char * 64)]


def rusage(pid: int) -> dict[str, float] | None:
    ru = RUsageV4()
    if _libproc.proc_pid_rusage(ctypes.c_int(pid), ctypes.c_int(RUSAGE_INFO_V4), ctypes.byref(ru)) != 0:
        return None
    return {
        "cpu_ns": (ru.ri_user_time + ru.ri_system_time) * NS_PER_TICK,
        "wakeups": float(ru.ri_pkg_idle_wkups + ru.ri_interrupt_wkups),
        "footprint": float(ru.ri_phys_footprint),
        "rss": float(ru.ri_resident_size),
    }


def threads(pid: int) -> dict[int, tuple[str, float]]:
    """thread handle -> (name, cpu ns) of every thread of ``pid`` (own processes only)."""
    cap = 512
    buf = (ctypes.c_uint64 * cap)()
    n = _libproc.proc_pidinfo(ctypes.c_int(pid), PROC_PIDLISTTHREADS, ctypes.c_uint64(0), buf, ctypes.sizeof(buf))
    out: dict[int, tuple[str, float]] = {}
    for i in range(max(0, n) // 8):
        ti = ThreadInfo()
        got = _libproc.proc_pidinfo(ctypes.c_int(pid), PROC_PIDTHREADINFO, ctypes.c_uint64(buf[i]), ctypes.byref(ti),
                                    ctypes.sizeof(ti))
        if got == ctypes.sizeof(ti):
            name = ti.pth_name.decode(errors="replace") or f"thread-{i}"
            out[int(buf[i])] = (name, float(ti.pth_user_time + ti.pth_system_time))
    return out


def responsible_pid(pid: int) -> int | None:
    try:
        f = _libc.responsibility_get_pid_responsible_for_pid
        f.argtypes, f.restype = [ctypes.c_int], ctypes.c_int
        r = f(pid)
        return r if r > 0 else None
    except (AttributeError, OSError):
        return None


def ps_rows() -> list[tuple[int, int, str, str]]:
    """(pid, elapsed s, comm path, full command) for every process (read-only ``ps``)."""
    out = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,etime=,comm="], capture_output=True, text=True, check=False)
    cmd = subprocess.run(["/bin/ps", "-axww", "-o", "pid=,command="], capture_output=True, text=True, check=False)
    full = {}
    for line in cmd.stdout.splitlines():
        p, _, rest = line.strip().partition(" ")
        if p.isdigit():
            full[int(p)] = rest.strip()
    rows = []
    for line in out.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit():
            rows.append((int(parts[0]), etime_s(parts[1]), parts[2], full.get(int(parts[0]), "")))
    return rows


def etime_s(s: str) -> int:
    days, _, rest = s.strip().rpartition("-")
    nums = [int(x) for x in rest.split(":") if x.isdigit()]
    while len(nums) < 3:
        nums.insert(0, 0)
    h, m, sec = nums[-3:]
    return (int(days) if days.isdigit() else 0) * 86400 + h * 3600 + m * 60 + sec


def find_app(app: str, rows: list[tuple[int, int, str, str]]) -> list[tuple[int, int, str, str]]:
    exe = str(Path(app) / "Contents" / "MacOS" / "SuryaDhana")
    mine = [r for r in rows if r[2] == exe and "--self-test" not in r[3]]
    if mine:
        return mine
    return [r for r in rows if r[2].endswith(".app/Contents/MacOS/SuryaDhana") and "--self-test" not in r[3]]


def screen_locked() -> bool | None:
    try:
        out = subprocess.run(["/usr/sbin/ioreg", "-n", "Root", "-d1"], capture_output=True, text=True, timeout=5,
                             check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return '"CGSSessionScreenIsLocked"=Yes' in out


def visible_windows(pid: int) -> int | None:
    """On-screen windows of ``pid`` (Quartz via PyObjC when available)."""
    try:
        import Quartz  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        info = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
        return sum(1 for w in info if int(w.get("kCGWindowOwnerPID", -1)) == pid and int(w.get("kCGWindowLayer", 1)) == 0)
    except (AttributeError, TypeError, ValueError):
        return None


def ui_api_uptime(rows: list[tuple[int, int, str, str]]) -> int | None:
    """Seconds since the process listening on :8010 started (read-only lsof + ps)."""
    try:
        out = subprocess.run(["/usr/sbin/lsof", "-nP", "-iTCP:8010", "-sTCP:LISTEN", "-t"], capture_output=True,
                             text=True, timeout=10, check=False).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    pids = {int(p) for p in out if p.isdigit()}
    ages = [r[1] for r in rows if r[0] in pids]
    return min(ages) if ages else None


def measure(app_pid: int, seconds: float, interval: float, with_threads: bool) -> dict[str, Any]:
    rows = ps_rows()
    names = {r[0]: r[2] for r in rows}
    helpers = [r[0] for r in rows if WEBKIT in r[2] and responsible_pid(r[0]) == app_pid]
    pids = [app_pid] + helpers
    t0 = time.monotonic()
    start = {p: rusage(p) for p in pids}
    th0 = threads(app_pid) if with_threads else {}
    peaks: dict[int, float] = {p: (start[p] or {}).get("footprint", 0.0) for p in pids}
    sums: dict[int, float] = {p: 0.0 for p in pids}
    samples = 0
    while time.monotonic() - t0 < seconds:
        time.sleep(min(interval, max(0.05, seconds - (time.monotonic() - t0))))
        samples += 1
        for p in pids:
            r = rusage(p)
            if r:
                peaks[p] = max(peaks[p], r["footprint"])
                sums[p] += r["footprint"]
    wall = time.monotonic() - t0
    end = {p: rusage(p) for p in pids}
    th1 = threads(app_pid) if with_threads else {}
    procs = []
    for p in pids:
        a, b = start.get(p), end.get(p)
        if not a or not b:
            continue
        name = Path(names.get(p, str(p))).name
        procs.append({
            "pid": p, "name": name, "role": "shell" if p == app_pid else name.replace(WEBKIT, ""),
            "cpu_pct": round(100 * (b["cpu_ns"] - a["cpu_ns"]) / 1e9 / wall, 3),
            "wakeups_per_s": round((b["wakeups"] - a["wakeups"]) / wall, 1),
            "footprint_mb_peak": round(peaks[p] / 1048576, 1),
            "footprint_mb_mean": round(sums[p] / max(1, samples) / 1048576, 1),
            "rss_mb": round(b["rss"] / 1048576, 1),
        })
    top = []
    for tid, (name, ns1) in th1.items():
        ns0 = th0.get(tid, (name, ns1))[1]
        top.append({"thread": name, "cpu_pct": round(100 * (ns1 - ns0) / 1e9 / wall, 3)})
    agg: dict[str, float] = {}
    for t in top:
        key = "tokio-rt-worker" if t["thread"].startswith("tokio-runtime-worker") or t["thread"].startswith("tokio-rt") else t["thread"]
        agg[key] = agg.get(key, 0.0) + t["cpu_pct"]
    threads_out = sorted(({"thread": k, "cpu_pct": round(v, 3)} for k, v in agg.items()), key=lambda x: -x["cpu_pct"])[:12]
    total_cpu = round(sum(p["cpu_pct"] for p in procs), 3)
    total_fp = round(sum(p["footprint_mb_peak"] for p in procs), 1)
    return {"seconds": round(wall, 1), "samples": samples, "processes": procs, "shell_threads": threads_out,
            "total": {"cpu_pct": total_cpu, "footprint_mb_peak": total_fp,
                      "wakeups_per_s": round(sum(p["wakeups_per_s"] for p in procs), 1)}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--seconds", type=float, default=600.0, help="sampling window (default 600 s)")
    ap.add_argument("--interval", type=float, default=1.0, help="footprint sampling interval (s)")
    ap.add_argument("--app", default=APP_DEFAULT, help="the installed bundle to look for")
    ap.add_argument("--pid", type=int, help="measure this process (and the WebKit helpers it is responsible for)")
    ap.add_argument("--no-threads", action="store_true", help="skip the per-thread breakdown of the shell")
    ap.add_argument("--json", type=Path, help="also write the result here")
    args = ap.parse_args(argv)

    rows = ps_rows()
    if args.pid:
        target = [r for r in rows if r[0] == args.pid] or [(args.pid, 0, str(args.pid), "")]
    else:
        target = find_app(args.app, rows)
    if not target:
        print("SuryaDhana is not running: open it first (this script never launches anything).", file=sys.stderr)
        return 2
    if len(target) > 1:
        print(f"note: {len(target)} SuryaDhana processes; measuring pid {target[0][0]} ({target[0][2]})")
    app_pid, uptime, exe, _ = target[0]
    locked = screen_locked()
    visible = visible_windows(app_pid)
    api_up = ui_api_uptime(rows)
    conditions = {
        "screen_locked": locked, "visible_windows": visible, "app_uptime_s": uptime, "ui_api_uptime_s": api_up,
        "settled": uptime >= SETTLE_S and (api_up is None or api_up >= SETTLE_S),
        "window_s": args.seconds,
    }
    warnings = []
    if locked:
        warnings.append("the screen is LOCKED: WebKit paints nothing and WebContent runs at background priority; "
                        "unlock it and keep a terminal window visible for a meaningful number")
    notes = []
    if visible == 0:
        warnings.append("no visible SuryaDhana window: open one (a window hidden to the menu bar is not the trading-day case)")
    elif visible is None:
        notes.append("window visibility not checked (PyObjC Quartz not installed): keep a terminal window visible")
    if uptime < SETTLE_S:
        warnings.append(f"the app started {uptime} s ago: wait until {SETTLE_S} s (start-up and page warm-up are not idle)")
    if api_up is not None and api_up < SETTLE_S:
        warnings.append(f"ui-api restarted {api_up} s ago: cold server caches inflate the first minutes")
    if args.seconds < 120:
        warnings.append(f"a {args.seconds:g} s window is short: use 600 s for the AC-13 number")
    print(f"measuring pid {app_pid} ({exe}) for {args.seconds:g} s …", flush=True)
    res = measure(app_pid, args.seconds, args.interval, not args.no_threads)
    tot = res["total"]
    verdict = {
        "cpu_ok": tot["cpu_pct"] < CPU_BUDGET_PCT, "memory_ok": tot["footprint_mb_peak"] < MEM_BUDGET_MB,
        "valid": not warnings,
    }
    doc = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "app_pid": app_pid, "exe": exe,
           "conditions": conditions, "warnings": warnings, "notes": notes, "budget": {"cpu_pct": CPU_BUDGET_PCT, "footprint_mb": MEM_BUDGET_MB},
           "verdict": verdict, **res}
    print(f"\n{'process':<22}{'CPU %':>8}{'wakeups/s':>11}{'mem MB (peak)':>15}{'RSS MB':>9}")
    for p in res["processes"]:
        print(f"{p['role'][:21]:<22}{p['cpu_pct']:>8.2f}{p['wakeups_per_s']:>11.1f}{p['footprint_mb_peak']:>15.1f}{p['rss_mb']:>9.1f}")
    print(f"{'TOTAL':<22}{tot['cpu_pct']:>8.2f}{tot['wakeups_per_s']:>11.1f}{tot['footprint_mb_peak']:>15.1f}")
    if res["shell_threads"]:
        print("\nshell threads (CPU %): " + ", ".join(f"{t['thread']} {t['cpu_pct']:.2f}" for t in res["shell_threads"][:8]))
    print(f"\nAC-13 budget: CPU {tot['cpu_pct']:.2f} % (< {CPU_BUDGET_PCT:g} %: {'ok' if verdict['cpu_ok'] else 'OVER'}) · "
          f"memory {tot['footprint_mb_peak']:.0f} MB (< {MEM_BUDGET_MB:g} MB: {'ok' if verdict['memory_ok'] else 'OVER'})")
    for w in warnings:
        print(f"WARNING: {w}")
    for n in notes:
        print(f"note: {n}")
    print("valid idle sample" if not warnings else "NOT a valid idle sample (see the warnings): do not sign AC-13 off with it")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        tmp = args.json.with_suffix(args.json.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        tmp.replace(args.json)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
