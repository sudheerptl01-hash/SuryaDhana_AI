"""terminal_data_dictionary: the committed doc is current, the validator refuses every rule break, rendering is pure.

The generator imports data-service's catalog modules (it puts ``services/data-service`` on ``sys.path``), so the
catalog-reading paths run in a subprocess here: nothing from data-service leaks into this pytest process.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import terminal_data_dictionary as tdd

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
SCRIPT = ROOT / "scripts" / "terminal_data_dictionary.py"
ANCHORS = {"docs/NSE_DATA_DICTIONARY.md": {"fovolt", "top10"}, "docs/GOLD_DATA_DICTIONARY.md": {"A1"}}


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([PY, str(SCRIPT), *args], capture_output=True, text=True, cwd=str(ROOT), timeout=120, check=False)


def test_committed_dictionary_is_current() -> None:
    res = _run("--check")
    assert res.returncode == 0, (res.stdout + res.stderr)[-800:]
    assert "is current" in res.stdout


def test_selftest_negative_controls_pass() -> None:
    res = _run("--selftest")
    assert res.returncode == 0, (res.stdout + res.stderr)[-800:]
    assert tdd.selftest() == []


def test_check_fails_on_a_stale_copy(tmp_path: Path) -> None:
    stale = tmp_path / "TERMINAL_DATA_DICTIONARY.md"
    stale.write_text((ROOT / "docs" / "TERMINAL_DATA_DICTIONARY.md").read_text(encoding="utf-8") + "\nhand edit\n", encoding="utf-8")
    res = _run("--check", "--out", str(stale))
    assert res.returncode == 1
    assert "STALE" in res.stderr


def test_every_anchor_in_the_nse_dictionary_is_unique() -> None:
    import re

    ids = re.findall(r'<a id="([^"]+)"></a>', (ROOT / "docs" / "NSE_DATA_DICTIONARY.md").read_text(encoding="utf-8"))
    assert len(ids) == len(set(ids)), sorted({i for i in ids if ids.count(i) > 1})


@pytest.mark.parametrize("over, needle", [
    ({"badge": "signal"}, "no pre-registered study"),
    ({"badge": "bullish"}, "unknown badge"),
    ({"verdict": "SHIP-IT"}, "unknown verdict"),
    ({"publisher": "MCX (mcxindia.com)"}, "forbidden host"),
    ({"publisher": "Kitco (kitco.com)"}, "forbidden host"),
    ({"dictionary_anchor": "docs/NSE_DATA_DICTIONARY.md#missing"}, "does not resolve"),
    ({"dictionary_anchor": "docs/TERMINAL_DATA_DICTIONARY.md#not_me"}, "must be its own id"),
    ({"dictionary_anchor": "docs/ELSEWHERE.md#x"}, "unknown document"),
    ({"pages": ""}, "missing pages"),
])
def test_validator_refuses_each_rule_break(over: dict, needle: str) -> None:
    defects = tdd.validate_rows([tdd._good_row(**over)], ANCHORS)
    assert any(needle in d for d in defects), defects


def test_clean_rows_pass_and_render_is_deterministic() -> None:
    rows = [tdd._good_row(), tdd._good_row(id="vix_daily", badge="arithmetic", dictionary_anchor="docs/TERMINAL_DATA_DICTIONARY.md#vix_daily")]
    assert tdd.validate_rows(rows, ANCHORS) == []
    regs: dict[str, tuple[str, list[dict]]] = {"fo_iv": ("present (0 rows)", []), "index_drivers": ("present (0 rows)", [])}
    a = tdd.render("t", rows, regs, {"NSE_HOSTS": ["nsearchives.nseindia.com"]}, ANCHORS)
    b = tdd.render("t", list(rows), regs, {"NSE_HOSTS": ["nsearchives.nseindia.com"]}, ANCHORS)
    assert a == b
    assert "describes, does not predict" in a and "**0 — none exists" in a


def test_render_refuses_a_signal_registry_row() -> None:
    regs = {"fo_iv": ("present (1 rows)", [{"series_id": "X", "badge": "signal", "verdict": "PUBLISH-CORE"}])}
    with pytest.raises(ValueError, match="signal"):
        tdd.render("t", [tdd._good_row()], regs, {}, ANCHORS)
