"""Two windows of one origin keep both edits (scripts/desktop_qa/e2e_multiwin.py; desktop review C3-logic-unchanged-02).

The always-on tests are pure (no browser, no network): the CLI, the refusal to run against anything but a scratch
prefs store, and that a crashing scenario is reported as a FAIL. The real E2E (two pages in ONE browser context per
engine: watchlist, MCXG gold desk, COMP compare set) is opt-in, because it needs a scratch server:

    $P scripts/desktop_qa/scratch_server.py --ui <export> --port 8093 --block-mutations --prefs-db <scratch>/p.sqlite
    DESKTOP_QA_E2E_BASE=http://127.0.0.1:8093 $P -m pytest tests/integration/test_desktop_e2e_multiwin.py -q

(optional: DESKTOP_QA_E2E_ENGINES=chromium, DESKTOP_QA_E2E_SCENARIOS=compare).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from desktop_qa import e2e_multiwin as e2e


def test_cli_defaults_run_every_scenario_in_both_engines():
    a = e2e.build_parser().parse_args(["--base", "http://127.0.0.1:8093", "--out", "x"])
    assert a.engines == "chromium,webkit"
    assert a.scenarios.split(",") == ["watchlist", "gold", "compare"] == list(e2e.SCENARIOS)


def test_unknown_scenario_is_refused_before_any_request(monkeypatch, tmp_path):
    monkeypatch.setattr(e2e, "http", lambda *a, **k: pytest.fail("no request may be sent"))
    assert e2e.main(["--base", "http://127.0.0.1:8093", "--out", str(tmp_path), "--scenarios", "compare,bogus"]) == 2


@pytest.mark.parametrize("health", [{"prefs": "forwarded"}, {"status": "ok"},
                                    urllib.error.HTTPError("http://127.0.0.1:8010/__qa/health", 404, "Not Found", {}, None),
                                    urllib.error.URLError("refused")])
def test_refuses_anything_but_a_local_scratch_prefs_store(monkeypatch, tmp_path, health):
    def fake_http(_base, _method, path, _body=None):
        assert path == "/__qa/health", "nothing but the health probe before the refusal"
        if isinstance(health, Exception):
            raise health
        return health

    ran: list[str] = []
    monkeypatch.setattr(e2e, "http", fake_http)
    monkeypatch.setitem(e2e.SCENARIOS, "compare", lambda *a: ran.append("compare") or {})
    assert e2e.main(["--base", "http://127.0.0.1:8010", "--out", str(tmp_path / "o"), "--scenarios", "compare"]) == 2
    assert not ran and not (tmp_path / "o").exists()


def test_a_crashing_scenario_is_a_fail_and_the_others_still_run(monkeypatch, tmp_path):
    monkeypatch.setattr(e2e, "http", lambda *_a, **_k: {"prefs": "local:/tmp/p.sqlite"})

    def boom(engine, _base, _out):
        raise TimeoutError(f"{engine}: selector never appeared")

    monkeypatch.setitem(e2e.SCENARIOS, "watchlist", boom)
    monkeypatch.setitem(e2e.SCENARIOS, "compare", lambda engine, _b, _o: {"engine": engine, "scenario": "compare", "ok": True})
    code = e2e.main(["--base", "http://127.0.0.1:8093", "--out", str(tmp_path), "--engines", "chromium",
                     "--scenarios", "watchlist,compare"])
    assert code == 1
    rows = json.loads((tmp_path / "multiwin.json").read_text())
    assert [(r["scenario"], r["ok"]) for r in rows] == [("watchlist", False), ("compare", True)]
    assert "selector never appeared" in rows[0]["error"]


BASE = os.environ.get("DESKTOP_QA_E2E_BASE", "")


@pytest.mark.skipif(not BASE, reason="opt-in: DESKTOP_QA_E2E_BASE=<a scratch_server.py --prefs-db base> runs the real E2E")
def test_two_windows_keep_both_edits(tmp_path):
    engines = os.environ.get("DESKTOP_QA_E2E_ENGINES", "chromium,webkit")
    scenarios = os.environ.get("DESKTOP_QA_E2E_SCENARIOS", ",".join(e2e.SCENARIOS))
    assert e2e.main(["--base", BASE, "--out", str(tmp_path), "--engines", engines, "--scenarios", scenarios]) == 0, \
        (tmp_path / "multiwin.json").read_text()
