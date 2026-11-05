"""G12 (Terminal v2 PLAN 0.8 / 1.7): the CI quality gates exist, are configured as the plan says, pass on the tree, and
fail on a negative control.

* ``.github/workflows/ci.yml``'s python job runs pin drift (strict) right after the install, then ruff and mypy per package
  from their own venv (pinned versions), then the suites, and pip-audit (advisory, own venv);
* ``pyproject.toml``: ruff select F, E9, B, ASYNC, DTZ at line length 130 with a per-file BASELINE of the pre-existing
  findings — no Terminal v2 package path in it, every path in it exists; mypy per package with ``explicit_package_bases``;
* ruff passes on the whole tree with that config, and fails a NEW DTZ / F821 finding (in a new file, and as a new code in
  a baselined file); mypy passes on the three scopes CI runs and fails a seeded type error.

The ruff / mypy runs need the versions the config targets (ruff ≥ 0.16, mypy ≥ 2): the canonical jupyter_env has them.
In CI the suites' env carries requirements.txt's stale pins (ruff 0.6.9, mypy 1.11.2), so those two tests skip there with
that reason — CI's own ruff / mypy steps (lint venv) are the enforcement."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = ROOT / "pyproject.toml"
WF = ROOT / ".github" / "workflows" / "ci.yml"
V2_PATHS = ("services/data-service/fo_iv/", "services/data-service/index_drivers/", "services/data-service/data_health/",
            "shared/metrics.py", "shared/http_client.py", "shared/breeze_budget.py", "services/ui-api/routers/data_health.py",
            "services/ui-api/routers/options_strategy.py", "tests/terminal_v2_gates/", "scripts/tests/test_tv2_",
            "scripts/tests/test_pin_drift.py")
MYPY_SCOPES = (("", ["shared"]),
               ("services/data-service", ["fo_iv", "index_drivers", "data_health"]),
               ("services/ui-api", ["routers/derivatives.py", "routers/data_health.py", "routers/options_strategy.py"]))


def _cfg() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def _version(mod: str) -> tuple[int, ...] | None:
    try:
        out = subprocess.run([sys.executable, "-m", mod, "--version"], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
    return tuple(int(x) for x in m.groups()) if m else None


def _need(mod: str, minimum: tuple[int, ...]) -> None:
    v = _version(mod)
    if v is None or v < minimum:
        pytest.skip(f"{mod} {v} < {minimum}: this env carries requirements.txt's stale lint pins; CI's lint venv step enforces")


def _ruff(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "ruff", "check", *args], cwd=ROOT, input=stdin, capture_output=True, text=True,
                          timeout=180)


def _mypy(cwd: str, targets: list[str]) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "MYPYPATH": str(ROOT)}
    cfg = os.path.relpath(PYPROJECT, ROOT / cwd) if cwd else "pyproject.toml"
    return subprocess.run([sys.executable, "-m", "mypy", "--config-file", cfg, *targets], cwd=ROOT / cwd, env=env,
                          capture_output=True, text=True, timeout=600)


# ── the workflow ────────────────────────────────────────────────────────────────────────────────────────────────

def test_ci_runs_ruff_mypy_pin_drift_and_pip_audit():
    doc = yaml.safe_load(WF.read_text(encoding="utf-8"))
    steps = doc["jobs"]["python"]["steps"]
    names = [str(s.get("name", "")) for s in steps]
    runs = [str(s.get("run", "")) for s in steps]

    def idx(prefix: str) -> int:
        hits = [i for i, n in enumerate(names) if n.startswith(prefix)]
        assert len(hits) == 1, (prefix, names)
        return hits[0]

    install = next(i for i, r in enumerate(runs) if "pip install -r requirements-ci.txt" in r)
    drift, lint, ruff, mypy = idx("pin drift"), idx("lint tools"), idx("ruff"), idx("mypy")
    core, audit = idx("core suite"), idx("pip-audit")
    assert install < drift < lint < ruff < mypy < core < audit, names
    assert steps[drift]["env"]["SD_PIN_DRIFT_STRICT"] == "1" and "scripts/tests/test_pin_drift.py" in runs[drift]
    assert "ruff==0.16.4" in runs[lint] and "mypy==2.3.1" in runs[lint] and '"$RUNNER_TEMP/lint"' in runs[lint]
    assert re.search(r"ruff\" check \.", runs[ruff])
    for cwd, targets in MYPY_SCOPES:                                     # the same scopes the test below runs
        line = next((ln for ln in runs[mypy].splitlines() if " ".join(targets) in ln), None)
        assert line is not None and (not cwd or f"cd {cwd}" in line), (cwd, targets)
    assert steps[mypy]["env"]["MYPYPATH"] == "${{ github.workspace }}"
    assert steps[audit].get("continue-on-error") is True
    assert "pip-audit==2.7.3" in runs[audit] and "-r requirements-ci.txt" in runs[audit]
    assert set(doc["jobs"]) == {"python", "ui", "desktop"}


def test_pyproject_is_the_plan_starter_config_and_the_baseline_only_lists_real_pre_v2_files():
    cfg = _cfg()["tool"]
    ruff = cfg["ruff"]
    assert ruff["line-length"] == 130 and ruff["target-version"] == "py313"
    assert ruff["lint"]["select"] == ["F", "E9", "B", "ASYNC", "DTZ"] and ruff["lint"]["ignore"] == ["ASYNC109"]
    base = ruff["lint"]["per-file-ignores"]
    v2 = [p for p in base if p.startswith(V2_PATHS)]
    assert not v2, f"Terminal v2 code may not be baselined: {v2}"
    gone = [p for p in base if not (ROOT / p).exists()]
    assert not gone, f"baseline paths that no longer exist (delete their lines): {gone}"
    assert all(isinstance(v, list) and v and all(re.fullmatch(r"[A-Z]+[0-9]+", c) for c in v) for v in base.values())
    assert len(base) <= 189, "the baseline may only shrink"
    mypy = cfg["mypy"]
    assert mypy["explicit_package_bases"] is True and mypy["ignore_missing_imports"] is True
    over = [m for o in mypy["overrides"] for m in o["module"]]
    assert over and all((ROOT / (m.replace(".", "/") + ".py")).exists() for m in over), over
    assert not any(m.startswith(("shared.metrics", "shared.http_client", "shared.breeze_budget")) for m in over)


# ── ruff ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_ruff_passes_on_the_tree_with_the_repo_config():
    _need("ruff", (0, 16, 0))
    r = _ruff(".", "--output-format", "concise")
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-1000:])


def test_negative_control_ruff_fails_a_new_dtz_violation():
    _need("ruff", (0, 16, 0))
    bad = "import datetime\n\n\ndef stamp():\n    return datetime.datetime.now()\n"
    r = _ruff("--output-format", "concise", "--stdin-filename", "services/data-service/fo_iv/zz_new_module.py", "-", stdin=bad)
    assert r.returncode == 1 and "DTZ005" in r.stdout, r.stdout
    # a baselined file is not a free pass: a code outside its own list still fails
    base = _cfg()["tool"]["ruff"]["lint"]["per-file-ignores"]
    listed = next(p for p, codes in sorted(base.items()) if "F821" not in codes and p.endswith(".py"))
    r2 = _ruff("--output-format", "concise", "--stdin-filename", listed, "-", stdin="def f():\n    return undefined_name_x\n")
    assert r2.returncode == 1 and "F821" in r2.stdout, (listed, r2.stdout)
    # and the baseline does what it says: the same file's own listed code is ignored
    code = base[listed][0]
    assert code and _ruff("--stdin-filename", listed, "--select", code, "-", stdin="x = 1\n").returncode == 0


# ── mypy ────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("cwd", "targets"), MYPY_SCOPES, ids=["shared", "data-service-v2", "ui-api-v2-routers"])
def test_mypy_passes_per_package(cwd: str, targets: list[str]):
    _need("mypy", (2, 0, 0))
    r = _mypy(cwd, targets)
    assert r.returncode == 0, (r.stdout[-3000:], r.stderr[-500:])


def test_negative_control_mypy_fails_a_seeded_type_error(tmp_path: Path):
    _need("mypy", (2, 0, 0))
    pkg = tmp_path / "seeded_pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "bad.py").write_text("def f(x: int) -> str:\n    return x\n")
    env = {**os.environ, "MYPYPATH": str(tmp_path)}
    cmd = [sys.executable, "-m", "mypy", "--config-file", str(PYPROJECT), "--cache-dir", str(tmp_path / ".mc"), "seeded_pkg"]
    r = subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 1 and "Incompatible return value type" in r.stdout, r.stdout
