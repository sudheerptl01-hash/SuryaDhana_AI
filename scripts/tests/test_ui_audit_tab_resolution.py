"""`--tabs` must never audit a page the caller did not ask for.

8 Nov 2026: `--tabs GOLD` (right page, wrong case) reported "GOLD PASS" while actually auditing the BRIEF page — the
router falls back to the brief for an unknown `?tab=`, and an id missing from the page source carries no ready code, so
the ready check passes at once. These tests pin the fix and would fail on the old pass-through behaviour.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui_audit import resolve_tabs  # noqa: E402

IDS = ["brief", "watch", "gold", "mcxgold", "desk"]


def test_a_known_id_resolves_and_case_does_not_matter():
    assert resolve_tabs("gold", IDS) == ["gold"]
    assert resolve_tabs("GOLD", IDS) == ["gold"]          # the exact mistake that caused the false pass
    assert resolve_tabs("Gold,DESK", IDS) == ["gold", "desk"]


def test_an_unknown_id_stops_the_run_instead_of_auditing_the_fallback_page():
    with pytest.raises(SystemExit) as e:
        resolve_tabs("gld", IDS)
    msg = str(e.value)
    assert "unknown tab id" in msg and "gld" in msg
    assert "known ids" in msg and "gold" in msg


def test_a_near_miss_suggests_the_real_id():
    with pytest.raises(SystemExit) as e:
        resolve_tabs("mcx", IDS)
    assert "mcxgold" in str(e.value)


def test_all_and_set_names_are_unchanged():
    assert resolve_tabs("all", IDS) == IDS
    assert resolve_tabs("ALL", IDS) == IDS


def test_it_does_not_block_a_run_when_the_page_source_could_not_be_read():
    # negative control: with no known ids there is nothing to validate against, so the old behaviour stands
    assert resolve_tabs("whatever", []) == ["whatever"]
