"""The DATA page sentence says each fact once (F7-04, 14 Nov 2026).

e103b44 made the "cannot be recovered later" clause reachable — the sentence whose three-round absence had critics
recommending a fix for a gold row that was unrecoverable by design. The round after, a reviewer found the layer
above: data-service's note says "N session(s) behind the expected one" while `_sentence` has already said
"N sessions behind", and the dedup guard was a substring test that cannot see the same fact rephrased. The only
red row on the page therefore stated its lag twice, once in unpolished prose.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services" / "ui-api"))

from routers.data_health import _restates_lag, _sentence  # noqa: E402

AS_OF, BY = date(2026, 11, 11), "09:15"


def test_a_note_that_only_rephrases_the_lag_is_dropped() -> None:
    out = _sentence(AS_OF, BY, 2, "red", "2 session(s) behind the expected one")
    assert out == "stored 11 Nov · expected by 09:15 · 2 sessions behind"
    assert out.count("behind") == 1


def test_a_note_that_adds_a_real_fact_is_kept() -> None:
    clause = "cannot be recovered later (session-bound capture)"
    assert _sentence(AS_OF, BY, 2, "red", clause).endswith(clause)       # the e103b44 sentence still reaches the page


def test_a_different_lag_number_is_never_swallowed() -> None:
    """The guard must drop a RESTATEMENT, not any sentence mentioning sessions — a disagreement is information."""
    assert not _restates_lag("3 sessions behind", "stored 11 Nov · 2 sessions behind")
    out = _sentence(AS_OF, BY, 2, "red", "3 sessions behind per the catalog")
    assert "3 sessions behind per the catalog" in out


def test_notes_without_a_lag_are_untouched() -> None:
    for extra in ("waiting for the 20:30 pass", "weekend: MCX closed", ""):
        assert not _restates_lag(extra, "stored 11 Nov · 2 sessions behind")


def test_the_sentence_still_works_with_no_extra_and_no_data() -> None:
    assert _sentence(AS_OF, BY, 2, "red") == "stored 11 Nov · expected by 09:15 · 2 sessions behind"
    assert _sentence(None, None, None, "gap") == "nothing stored"
