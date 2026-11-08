"""The one-command entry for India's monthly gold-import figure (no feed exists: SOURCES.md F14).

Every rule has a negative control, because the only guard against a typo in a hand-typed number is this script.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import gold_india_imports as cli  # noqa: E402


def test_the_row_is_dated_the_month_it_covers_not_the_release_day():
    assert cli.month_end("2026-10") == date(2026, 10, 31)
    assert cli.month_end("2026-02") == date(2026, 2, 28) and cli.month_end("2028-02") == date(2028, 2, 29)
    for bad in ("2026-13", "2026", "oct-2026", ""):
        with pytest.raises(SystemExit):
            cli.month_end(bad)


def test_the_typo_guard_refuses_the_two_mistakes_the_unit_invites():
    # the release prints "USD 1.8 billion"; ₹ crore and US$ million are the two other units in the same sentences
    assert cli.plausible(1.80) is None and cli.plausible(9.61) is None and cli.plausible(2.298) is None
    assert "₹ crore" in (cli.plausible(15_000) or "")          # a crore figure pasted whole
    assert "billions" in (cli.plausible(1800.0) or "") or "₹ crore" in (cli.plausible(1800.0) or "")
    assert "billions" in (cli.plausible(0.0018) or "")          # US$ million pasted as billions
    assert cli.plausible(0) and cli.plausible(-1)               # non-positive is refused


def test_a_month_that_has_not_ended_is_refused(monkeypatch, capsys):
    nxt = (datetime.now(cli.IST).date().replace(day=1) + timedelta(days=40)).strftime("%Y-%m")
    with pytest.raises(SystemExit) as e:
        cli.main(["--month", nxt, "--usd-bn", "1.8"])
    assert "has not ended yet" in str(e.value)


def test_dry_run_builds_the_job_body_the_data_service_contract_expects(capsys):
    assert cli.main(["--month", "2026-09", "--usd-bn", "1.80", "--source", "PTI", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert '"job": "gold_india_imports_manual"' in out and '"groups"' in out and '"india_imports"' in out
    assert '"series_id": "INDIA_GOLD_IMPORTS_USD_BN"' in out and '"report_date": "2026-09-30"' in out
    assert '"value": 1.8' in out
    assert "no machine-readable feed" in out                     # the stored source says why it was typed
