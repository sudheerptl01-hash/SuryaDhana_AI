"""gold_data_dictionary: the generator is deterministic, honours SOURCES.md's verdicts and keeps the committed doc current."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gold_data_dictionary as gdd

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable

FIXTURE = """# Gold free-data dictionary (fixture)

Every free source for trading gold on MCX, verified live on **Monday 26 Oct 2026, 03:30–09:40 IST** by ten agents.

## 0. Your questions, answered by dataset

| Owner's question | Dataset (entry) | Measure | Cadence · lag | Verdict |
|---|---|---|---|---|
| Who is long? | CFTC COT (B1) | net by group | weekly | PUBLISH-CORE |

## 1. Verdict vocabulary, badge rules and the counts

**Counts:** PUBLISH-CORE **1** · PUBLISH-CONTEXT **1** · LINK-ONLY **1** · DO-NOT-PUBLISH **1** — **4 entries**. Derived metrics (§10, 2 rows):
PUBLISH-CORE 1 · PUBLISH-CONTEXT 0 · LINK-ONLY 0 · DO-NOT-PUBLISH 1.

## A. Prices and benchmarks

### A1 · Fixture price feed `GC=F`
*What is gold worth right now?*
- **URL:** `https://query2.finance.yahoo.com/v8/finance/chart/GC=F?period1=1&period2=2&interval=1d`
- **Access:** FREE · **Verified:** G-KITCO 200 · 305 ms; **only** the app UA works.
- **Frequency / lag / history:** ≈1 min delayed; daily since Aug 2000.
- **[B]** The world price. **[P]** Last trade, not settlement.
- **Verdict:** PUBLISH-CORE — the stored benchmark. · **Catalog:** `COMEX_GC_FRONT`

### A2 · Fixture licensed page
- **URL:** `https://www.kitco.com/charts/gold` · **Verified (G-KITCO):** 200; terms forbid scraping.
- **Verdict:** LINK-ONLY — never embed or scrape.

## B. Positioning

Preamble paragraph for the section.

### B1 · Fixture COT
- **URL:** `https://publicreporting.cftc.gov/resource/72hh-3qpy.json`
- **Evidence (our own):** FAIL as a forecast. **PASS as description:** Spearman +0.65.
- **Verdict:** PUBLISH-CONTEXT — context only.

### B2 · Fixture dead symbol
- **Verified:** **404** (two agents).
- **Verdict:** DO-NOT-PUBLISH — the symbol does not exist.

## 10. Derived metrics dictionary (what the terminal computes; verdict and badge)

| # | Metric | Formula / definition | Cadence | Evidence | Verdict · badge |
|---|---|---|---|---|---|
| M1 | Fair open | settlement × ratios | live | accuracy log | PUBLISH-CORE · `arithmetic` |
| M2 | Health score | — | — | reads as a forecast | DO-NOT-PUBLISH (a composite) |

## 11. Evidence ledger

| Study | Data | Result | Consequence |
|---|---|---|---|
| G-STUDY | 1,063 reports | FAIL as a forecast; PASS as description | `context` badges |

## 12. Cadence map (IST) — what arrives when

| When (IST) | Arrives | Entry |
|---|---|---|
| Sat 01:00 | CFTC COT | B1 |
"""


def test_fixture_parses_fields_counts_and_prose_bold_tokens():
    src = gdd.parse_sources(FIXTURE)
    assert [e.id for e in src.entries] == ["A1", "A2", "B1", "B2"]
    assert src.counts() == {"PUBLISH-CORE": 1, "PUBLISH-CONTEXT": 1, "LINK-ONLY": 1, "DO-NOT-PUBLISH": 1, "entries": 4}
    assert src.metric_counts() == {"PUBLISH-CORE": 1, "PUBLISH-CONTEXT": 0, "LINK-ONLY": 0, "DO-NOT-PUBLISH": 1, "rows": 2}
    a1 = src.entries[0]
    assert a1.question == "What is gold worth right now?"
    assert a1.fields["access"] == ["FREE"]
    assert a1.fields["verified"] == ["G-KITCO 200 · 305 ms; **only** the app UA works."]  # prose bold stays in the field
    assert a1.fields["beginner"] == ["The world price."] and a1.fields["pro"] == ["Last trade, not settlement."]
    assert a1.fields["catalog"] == ["`COMEX_GC_FRONT`"]
    assert a1.get_hosts() == ["query2.finance.yahoo.com"]
    b1 = src.entries[2]
    assert b1.fields["evidence"] == ["FAIL as a forecast. **PASS as description:** Spearman +0.65."]  # not a label
    assert src.sections[1][2] == "Preamble paragraph for the section."
    assert src.verified_on == "Monday 26 Oct 2026, 03:30–09:40 IST"


def test_render_is_deterministic_and_marks_link_only_and_absent_seed(tmp_path):
    src = gdd.parse_sources(FIXTURE)
    first = gdd.render(src, "absent", [], tmp_path / "catalog_seed.py")
    second = gdd.render(gdd.parse_sources(FIXTURE), "absent", [], tmp_path / "catalog_seed.py")
    assert first == second
    assert "generated from SOURCES.md alone" in first
    assert "- **Verdict:** LINK-ONLY — never embed or scrape." in first
    assert "**DO-NOT-PUBLISH** (1): B2 Fixture dead symbol" in first
    assert "| **total** | | 4 | 2 |" in first
    assert first.endswith("\n") and "\n\n\n" not in first


def test_render_refuses_a_count_mismatch_and_a_forbidden_host_on_a_publish_entry(tmp_path):
    wrong = FIXTURE.replace("PUBLISH-CORE **1** · PUBLISH-CONTEXT **1**", "PUBLISH-CORE **2** · PUBLISH-CONTEXT **0**")
    with pytest.raises(ValueError, match="declares"):
        gdd.render(gdd.parse_sources(wrong))
    leaky = FIXTURE.replace("- **Verdict:** LINK-ONLY — never embed or scrape.", "- **Verdict:** PUBLISH-CONTEXT — leaked.") \
        .replace("PUBLISH-CONTEXT **1** · LINK-ONLY **1**", "PUBLISH-CONTEXT **2** · LINK-ONLY **0**")
    with pytest.raises(ValueError, match="forbidden host"):
        gdd.render(gdd.parse_sources(leaky))
    no_verdict = FIXTURE.replace("- **Verdict:** DO-NOT-PUBLISH — the symbol does not exist.\n", "")
    with pytest.raises(ValueError, match="no verdict line"):
        gdd.parse_sources(no_verdict)


def test_seed_literal_rows_are_read_with_ast_and_a_builder_is_imported_only_as_a_fallback(tmp_path):
    seed = tmp_path / "catalog_seed.py"
    seed.write_text(
        "import os\nos.system('echo must-not-run')\n"   # literal rows exist, so this file is never executed
        "COLUMNS = ('series_id', 'freq')\n"
        "ROWS = [{'series_id': 'ZZ_LAST', 'freq': 'D', 'badge': 'context'}, {'series_id': 'AA_FIRST', 'freq': 'W'}]\n"
        "NESTED = {'group': [{'series_id': 'MM_MID', 'unit': 'bp'}]}\n",
        encoding="utf-8",
    )
    status, rows = gdd.load_seed(seed)
    assert status == "present (3 series rows via literal rows)"
    assert [r["series_id"] for r in rows] == ["AA_FIRST", "MM_MID", "ZZ_LAST"]  # sorted → deterministic
    text = gdd.render(gdd.parse_sources(FIXTURE), status, rows, seed)
    assert "| series_id | freq | unit | badge |" in text and "| AA_FIRST | W |  |  |" in text
    looser = tmp_path / "looser.py"   # A2 is LINK-ONLY in the fixture; a PUBLISH-CORE row on it is a labelling defect
    looser.write_text("ROWS = [{'series_id': 'LEAK', 'source_entry': 'A2', 'verdict': 'PUBLISH-CORE', 'badge': 'context'},"
                      " {'series_id': 'TIGHT', 'source_entry': 'A1', 'verdict': 'PUBLISH-CONTEXT', 'badge': 'context'}]\n", encoding="utf-8")
    l_status, l_rows = gdd.load_seed(looser)
    lenient = gdd.render(gdd.parse_sources(FIXTURE), l_status, l_rows, looser)
    assert "a defect to fix in the seed" in lenient and "`LEAK` is PUBLISH-CORE but its source A2 is LINK-ONLY" in lenient
    assert "stricter than their source entry" in lenient and "`TIGHT` PUBLISH-CONTEXT (source A1 PUBLISH-CORE)" in lenient
    with pytest.raises(ValueError, match="looser than SOURCES.md"):
        gdd.render(gdd.parse_sources(FIXTURE), l_status, l_rows, looser, strict=True)
    assert gdd.load_seed(tmp_path / "missing.py") == ("absent", [])
    unknown = tmp_path / "other.py"
    unknown.write_text("SERIES = ['A', 'B']\n", encoding="utf-8")
    assert gdd.load_seed(unknown)[0].startswith("present but no `series_id` rows recognised")
    built = tmp_path / "built.py"   # no literal rows → build_rows() is imported from this one file and called
    built.write_text("from datetime import datetime\nAT = datetime(2026, 10, 26, 4, 10)\n"
                     "def build_rows():\n    return [{'series_id': 'B_ONE', 'verified_at': AT, 'note': None}]\n", encoding="utf-8")
    b_status, b_rows = gdd.load_seed(built)
    assert b_status == "present (1 series rows via build_rows())" and b_rows == [{"note": "", "series_id": "B_ONE", "verified_at": "2026-10-26T04:10:00"}]
    broken = tmp_path / "broken.py"
    broken.write_text("def build_rows():\n    raise RuntimeError('boom')\n", encoding="utf-8")
    assert gdd.load_seed(broken) == ("present but could not be loaded (RuntimeError: boom)", [])


def test_real_sources_render_twice_identically_and_match_the_declared_counts():
    text = gdd.SOURCES_PATH.read_text(encoding="utf-8")
    src = gdd.parse_sources(text)
    assert src.counts() == {**{k: src.declared_counts[k] for k in gdd.VERDICTS}, "entries": src.declared_counts["entries"]}
    assert src.metric_counts() == {**{k: src.declared_metric_counts[k] for k in gdd.VERDICTS}, "rows": src.declared_metric_counts["rows"]}
    assert gdd.render(src) == gdd.render(gdd.parse_sources(text))
    for entry in src.entries:  # the doc-level mirror of the host allowlist test (PLAN §h T8)
        if entry.verdict.startswith("PUBLISH"):
            assert not any(f in h for h in entry.get_hosts() for f in gdd.FORBIDDEN_HOSTS), entry.id


def test_cli_stdout_equals_build_and_committed_doc_is_current(tmp_path):
    out = subprocess.run([PY, "scripts/gold_data_dictionary.py", "--stdout"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout == gdd.build()
    target = tmp_path / "GOLD_DATA_DICTIONARY.md"
    subprocess.run([PY, "scripts/gold_data_dictionary.py", "--out", str(target)], cwd=ROOT, capture_output=True, text=True, check=True)
    assert target.read_text(encoding="utf-8") == out.stdout
    check = subprocess.run([PY, "scripts/gold_data_dictionary.py", "--check"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert check.returncode == 0, f"docs/GOLD_DATA_DICTIONARY.md is stale — run scripts/gold_data_dictionary.py\n{check.stderr}"
    stale = tmp_path / "stale.md"
    stale.write_text("old\n", encoding="utf-8")
    stale_run = subprocess.run([PY, "scripts/gold_data_dictionary.py", "--check", "--out", str(stale)], cwd=ROOT, capture_output=True, check=False)
    assert stale_run.returncode == 1
