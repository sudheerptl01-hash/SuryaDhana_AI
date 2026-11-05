"""F1.4 — the CI workflow actually gates what we claim it gates."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows" / "ci.yml"
REQ_CI = ROOT / "requirements-ci.txt"


def test_workflow_parses_and_lists_all_five_suites_plus_tsc():
    import yaml
    doc = yaml.safe_load(WF.read_text())
    assert set(doc["jobs"]) == {"python", "ui", "desktop"}   # desktop: the macOS gates of the desktop program (completeness-05)
    text = WF.read_text()
    for needle in ("pytest tests -q", "pytest scripts/tests -q", "pytest services/ui-api/tests -q",
                   "pytest services/execution-service/tests -q", "cd alpha_lab && python -m pytest tests",
                   "tsc --noEmit", "check_event_loop.py", "requirements-ci.txt"):
        assert needle in text, f"ci.yml missing: {needle}"


def test_requirements_ci_excludes_exactly_the_heavy_trio_and_keeps_other_pins():
    lines = REQ_CI.read_text().splitlines()
    excluded = [ln for ln in lines if ln.startswith("# [ci-excluded]")]
    names = {ln.split("]", 1)[1].split("==")[0].strip() for ln in excluded}
    assert names == {"xgboost", "lightgbm", "stable-baselines3"}
    active = {ln.split("==")[0].strip() for ln in lines if "==" in ln and not ln.startswith("#")}
    # the pins every suite needs at import time
    for pkg in ("fastapi", "duckdb", "pandas", "scikit-learn", "pytest", "apscheduler", "psutil", "scipy"):
        assert pkg in active, f"requirements-ci.txt missing {pkg}"
    # and the main requirements' pins it carries are identical strings
    main = {ln.split("==")[0].strip(): ln.strip() for ln in (ROOT / "requirements.txt").read_text().splitlines()
            if "==" in ln and not ln.strip().startswith("#")}
    for pkg, pin in main.items():
        if pkg in ("xgboost", "lightgbm", "stable-baselines3"):
            continue
        assert pin in REQ_CI.read_text(), f"pin drift for {pkg}"
