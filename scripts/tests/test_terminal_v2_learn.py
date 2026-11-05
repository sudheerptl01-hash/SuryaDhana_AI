"""Terminal v2 LEARN assets: the committed glossary / tooltips match their builder and pass every rule (PLAN 1.6)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEARN = ROOT / "reports" / "terminal_v2" / "LEARN"
PY = sys.executable


def _validator():
    spec = importlib.util.spec_from_file_location("v2_validate_learn", LEARN / "validate_learn.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_validator_passes_on_the_committed_assets() -> None:
    res = subprocess.run([PY, str(LEARN / "validate_learn.py")], capture_output=True, text=True, cwd=str(ROOT), timeout=120,
                         check=False)
    assert res.returncode == 0, (res.stdout + res.stderr)[-1500:]


def test_selftest_catches_every_synthetic_defect() -> None:
    assert _validator().selftest() == []


def test_required_entries_and_the_rank_percentile_pair() -> None:
    g = json.loads((LEARN / "glossary.json").read_text(encoding="utf-8"))
    names = {t["term"] for t in g["terms"]}
    for req in ("IV rank", "IV percentile", "constant-maturity IV", "put-call-parity forward", "25Δ skew", "Parkinson volatility",
                "Yang-Zhang volatility", "FOVOLT", "SPAN margin", "exposure margin", "points attribution", "attribution residual",
                "hysteresis", "delta-equivalent OI", "MWPL"):
        assert req in names, req
    by = {t["term"]: t for t in g["terms"]}
    assert "Not the percentile" in by["IV rank"]["short"] and "Not the rank" in by["IV percentile"]["short"]


def test_every_line_is_one_line_of_at_most_200_chars() -> None:
    g = json.loads((LEARN / "glossary.json").read_text(encoding="utf-8"))
    t = json.loads((LEARN / "tooltips.json").read_text(encoding="utf-8"))
    texts = [x["short"] for x in g["terms"]] + [x["long"] for x in g["terms"]] + list(t["tooltips"].values())
    assert all(len(s) <= 200 and "\n" not in s for s in texts)


def test_direction_words_are_caught_and_the_exchange_term_is_not() -> None:
    v = _validator()
    assert v.direction_words("FIIs turned bearish") == ["bearish"]
    assert v.direction_words("price up + OI up = long build-up") != []
    assert v.direction_words("IV will rise into results") != []
    assert v.direction_words("SPAN adds a short-option minimum") == []
    assert v.direction_words("put OI ÷ call OI, a context ratio") == []


def test_a_bundled_ui_copy_must_match(tmp_path: Path) -> None:
    v = _validator()
    g = json.loads((LEARN / "glossary.json").read_text(encoding="utf-8"))
    t = json.loads((LEARN / "tooltips.json").read_text(encoding="utf-8"))
    ui = tmp_path / "ui" / "lib" / "vol"
    ui.mkdir(parents=True)
    (ui / "tooltips.json").write_text(json.dumps(t), encoding="utf-8")
    assert v.check_bundled(g, t, v.bundled_copies(tmp_path / "ui")) == []
    drift = dict(t, tooltips={**t["tooltips"], "iv30_cm": "edited by hand"})
    (ui / "tooltips.json").write_text(json.dumps(drift), encoding="utf-8")
    copies = v.bundled_copies(tmp_path / "ui")
    assert copies == [ui / "tooltips.json"]
    defects = v.check_bundled(g, t, copies)
    assert len(defects) == 1 and "differs" in defects[0]
    (ui / "glossary.json").write_text(json.dumps({"agent": "someone-else", "terms": []}), encoding="utf-8")
    assert v.bundled_copies(tmp_path / "ui") == [ui / "tooltips.json"]   # only B5-DOCS copies are compared
