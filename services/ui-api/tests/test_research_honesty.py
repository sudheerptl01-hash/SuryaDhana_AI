"""RSCH honesty sweep (5 Nov 43-page review: M22, m093–m096): alpha_lab verdicts in the library, verdict-bearing v2
studies counted as verdicts, engineering records kept apart from studies, the study's own date instead of the file's
mtime, and a generated verdict summary as the first entry. Every rule has a negative control."""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException

import routers.research as rs


@pytest.fixture(scope="module")
def listing() -> dict:
    return rs.list_research()


def _by_id(listing: dict) -> dict[str, dict]:
    return {e["id"]: e for e in listing["data"]}


# ── M22: the strategy lab's verdicts are in the library ─────────────────────────────────────────────────────────────
def test_alpha_lab_verdicts_are_listed(listing):
    rows = _by_id(listing)
    assert rows["alpha_lab/reports/FINDINGS.md"]["verdict"] == "PASS"
    assert "28.0%" in rows["alpha_lab/reports/FINDINGS.md"]["takeaway"] and "15.8%" in rows["alpha_lab/reports/FINDINGS.md"]["takeaway"]
    assert rows["alpha_lab/reports/s1_gateA.md"]["verdict"] == "PASS"
    assert rows["alpha_lab/reports/s1_gateB.md"]["verdict"] == "PASS"
    assert rows["alpha_lab/reports/s1H_gateB.md"]["verdict"] == "FAIL"           # S1H fails Gate B
    assert rows["alpha_lab/reports/s2_RESULTS.md"]["verdict"] == "FAIL"
    s3 = rows["alpha_lab/reports/s3_RESULTS.md"]
    assert s3["verdict"] == "FAIL" and "STAY AWAY" in s3["takeaway"]
    q = rows["alpha_lab/reports/quick_tests_RESULTS.md"]
    assert q["verdict"] == "PROMISING" and "t −4.2" in q["takeaway"] and "−0.49%" in q["takeaway"]
    assert rows["alpha_lab/reports/avoid_rules.md"]["verdict"] == "PASS"
    assert rows["alpha_lab/PLAN.md"]["verdict"] == "REFERENCE"
    # negative control: the dated book printout is a snapshot of one day's research book, never listed
    assert "alpha_lab/reports/today_book.md" not in rows
    with pytest.raises(HTTPException) as e:
        rs.get_doc("alpha_lab/reports/today_book.md")
    assert e.value.status_code == 404


def test_every_alpha_lab_report_has_a_catalog_row():
    root = rs._root()
    for p in (root / "alpha_lab" / "reports").glob("*.md"):
        rel = str(p.relative_to(root))
        assert rel in rs.CATALOG or rel in rs._SKIP_FILES, f"{rel} has no CATALOG row (CLAUDE.md: a row for every report)"


def test_alpha_lab_doc_and_files_are_served_and_guarded():
    doc = rs.get_doc("alpha_lab/reports/s1_gateA.md")
    assert doc["markdown"].startswith("# S1 gateA")
    assert [f["name"] for f in doc["data_files"]] == ["s1_gateA_equity.csv"]        # only this run's file
    assert rs.get_doc("alpha_lab/reports/FINDINGS.md")["data_files"] == []           # the synthesis owns no run file
    assert {f["name"] for f in rs.get_doc("alpha_lab/reports/quick_tests_RESULTS.md")["data_files"]} >= {"qt_q1_weekly.csv"}
    for bad in ("alpha_lab/../.env", "alpha_lab/reports/../../.env", "alpha_lab/run_today.py", "alpha_lab/README.md"):
        with pytest.raises(HTTPException) as e:
            rs.get_doc(bad)
        assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        rs.get_file("alpha_lab/reports/s1_gateA.md", "../../.env")
    assert e.value.status_code == 400


# ── m094: verdict-bearing Terminal v2 studies count as verdicts ─────────────────────────────────────────────────────
def test_v2_studies_carry_their_fail_verdict(listing):
    rows = _by_id(listing)
    for rel in ("reports/terminal_v2/studies/iv_rv/FINDINGS.md", "reports/terminal_v2/studies/drivers/FINDINGS.md",
                "reports/terminal_v2/studies/gex/FINDINGS.md"):
        assert rows[rel]["verdict"] == "FAIL" and rows[rel]["kind"] == "study"
        assert "PROVISIONAL" in rows[rel]["takeaway"]
    # negative control: the study registry itself stays a reference
    assert rows["reports/terminal_v2/STUDIES.md"]["verdict"] == "REFERENCE"


# ── m093: studies, references and engineering records are counted apart ────────────────────────────────────────────
def test_kinds_and_counts(listing):
    rows = _by_id(listing)
    assert rows["reports/bloomberg_program/PLAN.md"]["verdict"] == "ENGINEERING"
    assert rows["reports/bloomberg_program/PLAN.md"]["kind"] == "engineering"
    assert rows["reports/worldclass_program/REPORT.md"]["kind"] == "engineering"
    assert rows["reports/journal/2026-W44.md"]["kind"] == "reference"
    assert rows["reports/phase_b_extended/REPORT.md"]["kind"] == "study"
    entries = [e for e in listing["data"] if e["kind"] != "summary"]
    c = listing["counts"]
    assert c["studies"] == sum(e["kind"] == "study" for e in entries)
    assert c["engineering"] == sum(e["verdict"] == "ENGINEERING" for e in entries) > 0
    assert c["studies"] + c["references"] + c["engineering"] + c["other"] == len(entries)
    assert c["other"] == 0, [e["id"] for e in entries if e["kind"] == "other"]          # nothing is left unlabelled
    # negative control: a REFERENCE row is never counted as a study
    assert rs.kind_of("REFERENCE") == "reference" and rs.kind_of("—") == "other" and rs.kind_of("NO EDGE") == "study"


# ── m095: the study's own date, not the file's mtime ───────────────────────────────────────────────────────────────
def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "doc.md"
    p.write_text(text, encoding="utf-8")
    return p


def test_study_date_rules(tmp_path):
    mod = date(2026, 11, 6)
    p = _write(tmp_path, "# Improvement log: terminal polish sprint (11–15 Oct 2026)\n\nLast updated Thu 5 Nov 2026 22:00 IST\n")
    assert rs.study_date(p, "x.md", mod) == date(2026, 11, 5)                     # the "last updated" line wins
    p = _write(tmp_path, "# Gold program: findings (26 Oct 2026)\n")
    assert rs.study_date(p, "x.md", mod) == date(2026, 10, 26)
    p = _write(tmp_path, "# Sprint (11–15 Oct 2026)\n")
    assert rs.study_date(p, "x.md", mod) == date(2026, 10, 15)                    # a range counts as its last day
    p = _write(tmp_path, "# TV-IVRV\n\nRun 2026-11-05T08:20:03+05:30 on a scratch store.\n")
    assert rs.study_date(p, "x.md", mod) == date(2026, 11, 5)
    p = _write(tmp_path, "# News\n\nGenerated 2026-11-05 21:41. 411 picks (2026-09-25 → 2026-11-04).\n")
    assert rs.study_date(p, "x.md", mod) == date(2026, 11, 5)
    # negative controls: a sample window, a date inside code, a split date and a date after the last edit are not the study's
    p = _write(tmp_path, "# S1 gateA: 2020-01-01 → 2026-10-13\n")
    assert rs.study_date(p, "x.md", mod) is None
    p = _write(tmp_path, "# Phase B\n\nRun: `allocator.py --panel-start 2010-01-01` (~2 min).\n")
    assert rs.study_date(p, "x.md", mod) is None
    p = _write(tmp_path, "# Lab\n\nDiscovery < 2024-07-01, holdout after.\n")
    assert rs.study_date(p, "x.md", mod) is None
    p = _write(tmp_path, "# Plan for 30 Nov 2026\n")
    assert rs.study_date(p, "x.md", mod) is None
    assert rs.study_date(_write(tmp_path, "# No date here\n"), "x.md", mod) is None


def test_entry_uses_the_document_date_not_a_fresh_mtime(listing):
    gold = _by_id(listing)["reports/gold_program/FINDINGS.md"]
    assert gold["updated"].startswith("2026-10-26") and gold["dated_from"] == "document"
    assert gold["modified"] is not None
    gate = _by_id(listing)["alpha_lab/reports/s1_gateA.md"]
    assert gate["updated"].startswith("2026-10-14")                                 # dated override, not the 2020 window


def test_entry_falls_back_to_mtime_when_the_header_has_no_date(tmp_path, monkeypatch):
    (tmp_path / "reports" / "x").mkdir(parents=True)
    f = tmp_path / "reports" / "x" / "NOTE.md"
    f.write_text("# A note without a date\n", encoding="utf-8")
    ts = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc).timestamp()
    os.utime(f, (ts, ts))
    monkeypatch.setenv("RESEARCH_ROOT", str(tmp_path))
    e = rs._entry(rs._root(), "reports/x/NOTE.md")
    assert e["dated_from"] == "file" and e["updated"].startswith("2026-10-01")
    assert e["kind"] == "other" and e["verdict"] == "—"


# ── m096: the page opens on a verdict summary built from the catalog ───────────────────────────────────────────────
def test_summary_is_first_and_built_from_the_catalog(listing):
    first = listing["data"][0]
    assert first["id"] == rs.SUMMARY_ID and first["verdict"] == "SUMMARY" and first["kind"] == "summary"
    doc = rs.get_doc(rs.SUMMARY_ID)
    md = doc["markdown"]
    works = md.split("## What works")[1].split("## Leads")[0]
    fails = md.split("## What fails")[1].split("## What measures")[0]
    assert "`reports/phase_b_extended/REPORT.md`" in works and "`alpha_lab/reports/s1_gateA.md`" in works
    assert "`alpha_lab/reports/s3_RESULTS.md`" in fails and "`reports/earnings_growth_drift/FINDINGS.md`" in fails
    assert "`reports/terminal_v2/R-IV/REPORT.md`" in md.split("## What measures")[1]
    # negative controls: a FAIL never sits under "what works", and references / engineering records are not listed
    assert "`alpha_lab/reports/s3_RESULTS.md`" not in works
    assert "`docs/IMPROVEMENT_LOG.md`" not in md and "`reports/bloomberg_program/PLAN.md`" not in md
    n_pass = sum(e["verdict"] in ("ADOPTED", "PASS") for e in listing["data"])
    assert f"## What works: the verdicts you may act on ({n_pass})" in md
    assert doc["takeaway"].startswith(f"{listing['counts']['forecast_verdicts']} forecast verdicts")


def test_summary_has_no_file_behind_it():
    with pytest.raises(HTTPException) as e:
        rs.get_file(rs.SUMMARY_ID, "package.json")       # would otherwise resolve against the repo root
    assert e.value.status_code == 404


def test_improvement_log_title_is_current(listing):
    row = _by_id(listing)["docs/IMPROVEMENT_LOG.md"]
    assert row["title"].startswith("Improvement log: the operations journal")
    assert "11–14 Oct 2026 terminal sprint. Start here" not in row["takeaway"]
    assert (datetime.now(timezone.utc) - datetime.fromisoformat(row["updated"])) < timedelta(days=400)


# ── M21: a page reads a verdict from the catalog at render time ────────────────────────────────────────────────────
def test_verdict_endpoint_reads_the_catalog():
    v = rs.get_verdict("reports/earnings_growth_drift/FINDINGS.md")
    assert v["verdict"] == "NO EDGE" and "H1 FAIL" in v["takeaway"] and "markdown" not in v
    assert rs.get_verdict("reports/ml_labels/FINDINGS.md")["verdict"] == "FAIL"
    # negative controls: an unknown id and the generated summary are not verdict rows
    for bad in ("reports/nope/FINDINGS.md", rs.SUMMARY_ID, "../.env"):
        with pytest.raises(HTTPException) as e:
            rs.get_verdict(bad)
        assert e.value.status_code == 404
