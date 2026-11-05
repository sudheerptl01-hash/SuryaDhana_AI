"""G12 pin drift (Terminal v2 PLAN 0.8 / 1.7; R-ARCH §5 "CI pins ≠ prod"): every requirement is pinned with ``==``, the
CI requirements carry the same version as the main file for every package both list, and — in CI, where the job sets
``SD_PIN_DRIFT_STRICT=1`` right after ``pip install -r requirements-ci.txt`` — every installed distribution is exactly
its pin ("``pip freeze`` vs requirements", R-ARCH fix 8).

Locally the strict comparison is skipped and the drift is only reported: the canonical ``jupyter_env`` is shared with other
projects and runs newer versions on purpose (never bulk-install the pins into it — it broke other projects once). That
gap between the pins CI tests and the environment that runs the stack is an owner decision, recorded in the B6 result."""
from __future__ import annotations

import os
import re
from importlib import metadata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQ = ROOT / "requirements.txt"
REQ_CI = ROOT / "requirements-ci.txt"
CI_EXCLUDED = {"xgboost", "lightgbm", "stable-baselines3"}       # documented in requirements-ci.txt ([ci-excluded])
LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(==|>=|<=|~=|!=|>|<)?\s*([^\s#;]*)")


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse(text: str) -> tuple[dict[str, str], list[str]]:
    """{normalised name: pinned version} and the lines that are not an exact ``==`` pin."""
    pins: dict[str, str] = {}
    loose: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http")):
            continue
        m = LINE.match(line)
        if not m:
            loose.append(raw.strip())
            continue
        name, _extras, op, ver = m.groups()
        if op != "==" or not ver:
            loose.append(raw.strip())
            continue
        pins[norm(name)] = ver
    return pins, loose


def drift(pins: dict[str, str], installed: dict[str, str | None]) -> dict[str, tuple[str, str | None]]:
    """Packages whose installed version differs from the pin (None = not installed)."""
    return {n: (v, installed.get(n)) for n, v in pins.items() if installed.get(n) != v}


def installed_versions(names: list[str]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for n in names:
        try:
            out[n] = metadata.version(n)
        except metadata.PackageNotFoundError:
            out[n] = None
    return out


def test_every_requirement_is_pinned_exactly():
    for path in (REQ, REQ_CI):
        _, loose = parse(path.read_text(encoding="utf-8"))
        assert not loose, f"{path.name}: not an exact == pin: {loose}"


def test_ci_pins_equal_the_main_pins():
    main, _ = parse(REQ.read_text(encoding="utf-8"))
    ci, _ = parse(REQ_CI.read_text(encoding="utf-8"))
    differ = {n: (main[n], ci[n]) for n in main.keys() & ci.keys() if main[n] != ci[n]}
    assert not differ, f"requirements.txt vs requirements-ci.txt: {differ}"
    missing = sorted(set(main) - set(ci) - CI_EXCLUDED)
    assert not missing, f"pinned in requirements.txt but absent from requirements-ci.txt: {missing}"


def test_negative_controls_a_loose_line_and_a_drifted_install_are_caught():
    pins, loose = parse("fastapi==0.115.0\nuvicorn[standard]==0.30.6  # web\npandas>=2.0\nnumpy\n# c\n")
    assert pins == {"fastapi": "0.115.0", "uvicorn": "0.30.6"} and loose == ["pandas>=2.0", "numpy"]
    assert drift(pins, {"fastapi": "0.141.1", "uvicorn": "0.30.6"}) == {"fastapi": ("0.115.0", "0.141.1")}
    assert drift({"x-y": "1"}, {}) == {"x-y": ("1", None)}
    assert norm("Python_Telegram.Bot") == "python-telegram-bot"


def test_installed_versions_match_the_ci_pins():
    ci, _ = parse(REQ_CI.read_text(encoding="utf-8"))
    found = drift(ci, installed_versions(sorted(ci)))
    if os.environ.get("SD_PIN_DRIFT_STRICT") != "1":
        pytest.skip(f"local env: {len(found)} of {len(ci)} CI pins differ from what is installed (shared jupyter_env, "
                    "reported not enforced); CI enforces with SD_PIN_DRIFT_STRICT=1")
    assert not found, f"installed ≠ requirements-ci.txt: {found}"
