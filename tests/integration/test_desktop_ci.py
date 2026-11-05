"""CI covers the desktop program's own gates (desktop review completeness-05) and keeps covering them.

Static: reads .github/workflows/ci.yml and the repo tree. A new plain-node check file, a dropped cargo step or a
CI that quietly opts out of the strict contract tests fails here instead of passing unnoticed.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")   # pyyaml is pinned in requirements-ci.txt

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci() -> dict:
    assert CI.is_file(), ".github/workflows/ci.yml is missing"
    return yaml.safe_load(CI.read_text())


def _runs(ci: dict, job: str) -> str:
    return "\n".join(str(s.get("run", "")) for s in ci["jobs"][job]["steps"])


def _ci_check_files(ci: dict) -> list[str]:
    """Run the ui job's discovery + filter (not the checks) and return the files it would execute."""
    step = next(s for s in ci["jobs"]["ui"]["steps"] if "check.ts" in str(s.get("run", "")))
    script = step["run"].replace('node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON "$f"', 'echo "RUN $f"')
    r = subprocess.run(["/bin/bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    return sorted(line[4:] for line in r.stdout.splitlines() if line.startswith("RUN "))


def test_every_plain_node_check_file_runs_in_ci(ci):
    """Each ui/**/__tests__/*.check.ts that runs on plain node (not via tsx) is executed by the ui job."""
    checks = sorted(p for p in (ROOT / "ui").glob("**/__tests__/*.check.ts") if "node_modules" not in p.parts)
    assert checks, "no check files found"
    plain = sorted(str(p.relative_to(ROOT)) for p in checks if "npx tsx" not in p.read_text()[:600])
    assert {"ui/lib/__tests__/prefs.check.ts", "ui/lib/__tests__/platform.check.ts", "ui/lib/__tests__/alerts.check.ts",
            "ui/components/desktop/__tests__/desktop.check.ts"} <= set(plain)
    assert _ci_check_files(ci) == plain
    node = str(ci["jobs"]["ui"]["steps"][1]["with"]["node-version"])
    assert int(node.split(".")[0]) >= 23, "the .check.ts files need node >= 23.6 (type stripping + registerHooks)"


def test_claude_md_runs_the_same_ui_checks_as_ci_and_lists_every_gate(ci):
    """The gate list a developer runs by hand (CLAUDE.md 'How to run things') covers every plain-node check file CI
    runs: it used to name six files by hand and missed no-dialogs.check.ts and streamProxy.check.ts (round 4)."""
    text = (ROOT / "CLAUDE.md").read_text()
    line = next((ln for ln in text.splitlines() if ln.startswith("for f in ") and ".check.ts" in ln), None)
    assert line, "CLAUDE.md has no UI node-check loop"
    assert 'node "$f"' in line and "find ui" in line, f"not a discovery loop (a hand-written list goes stale): {line}"
    script = line.split("   #", 1)[0].replace('node "$f"', 'echo "RUN $f"')
    r = subprocess.run(["/bin/bash", "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
    listed = sorted(ln[4:] for ln in r.stdout.splitlines() if ln.startswith("RUN "))
    assert listed == _ci_check_files(ci), (listed, r.stderr)
    for name in ("no-dialogs.check.ts", "streamProxy.check.ts", "ws.check.ts", "pages.check.ts", "desktop.check.ts"):
        assert any(p.endswith(name) for p in listed), name
    for gate in ("-m pytest tests -q", "-m pytest scripts/tests -q", "-m pytest services/ui-api/tests -q",
                 "-m pytest services/execution-service/tests -q", "(cd alpha_lab && $P -m pytest tests -q)",
                 "(cd ui && npx tsc --noEmit)", "cargo test", "cargo clippy --all-targets", "cargo fmt --check",
                 "node desktop/scripts/boot_check.mjs", "node --test ui/scripts/*.test.mjs"):
        assert gate in text, gate


def test_the_desktop_job_runs_the_shell_gates_on_macos(ci):
    job = ci["jobs"]["desktop"]
    assert job["runs-on"].startswith("macos"), "the Tauri shell (objc2) and bash 3.2 scripts need a macOS runner"
    runs = _runs(ci, "desktop")
    for needle in ("cargo test --manifest-path desktop/src-tauri/Cargo.toml",
                   "cargo clippy --manifest-path desktop/src-tauri/Cargo.toml",
                   "cargo fmt --manifest-path desktop/src-tauri/Cargo.toml",
                   "node desktop/scripts/boot_check.mjs",
                   "node --test ui/scripts/*.test.mjs",
                   "scripts/tests/test_ops_shell.py",
                   "tests/integration/test_desktop_ops.py",
                   "tests/integration/test_desktop_contract.py",
                   "tests/integration/test_desktop_static.py"):
        assert needle in runs, needle
    static = [s for s in job["steps"] if "test_desktop_static.py" in str(s.get("run", ""))]
    assert static and static[0].get("env", {}).get("DESKTOP_QA_BUILD") == "1", "the real export build must be on"


def test_the_python_job_runs_the_desktop_relevant_suites(ci):
    runs = _runs(ci, "python")
    for needle in ("python -m pytest tests ", "python -m pytest services/ui-api/tests",
                   "python -m pytest reports/desktop_app/baseline_preprogram/tools"):
        assert needle in runs, needle
    # the shell tests are only moved, never dropped: what the python job ignores the desktop job runs
    desktop = _runs(ci, "desktop")
    for ignored in re.findall(r"--ignore=(\S+)", runs):
        assert ignored in desktop, f"{ignored} is ignored on ubuntu but not run on macOS"


def test_ci_never_opts_out_of_the_strict_contract_tests(ci):
    """DESKTOP_CONTRACT_ALLOW_SKIP is for partial checkouts only; the full repository must fail on drift."""
    assert "DESKTOP_CONTRACT_ALLOW_SKIP=1" not in CI.read_text().replace("# DESKTOP_CONTRACT_ALLOW_SKIP", "")
    for job in ci["jobs"].values():
        assert "DESKTOP_CONTRACT_ALLOW_SKIP" not in (job.get("env") or {})
        for step in job["steps"]:
            assert "DESKTOP_CONTRACT_ALLOW_SKIP" not in (step.get("env") or {})
