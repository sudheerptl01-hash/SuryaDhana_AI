"""PLAN §0.6 / §0.7 for ``shared/``: the terminal-wide allowlist contains the gold list and the NSE / niftyindices /
Breeze hosts; every URL host literal under ``shared/`` is allowlisted; the forbidden publishers appear only in the
forbidden tuple; no ``yfinance`` import and no Yahoo chart call lives in ``shared/``; the gold package's own list is a
subset (the two cannot drift apart)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from shared import http_client as hc  # noqa: E402

URL_HOST = re.compile(r"(?:https?|ftp)://([A-Za-z0-9.\-]+)")
SHARED = ROOT / "shared"


# http_guard.py is the INBOUND Host/Origin guard, not a fetcher; its docstrings cite example hosts (testserver, a
# tailnet name). Every other module under shared/ that names a URL host must name an allowlisted one.
_NOT_FETCHERS = {"__init__.py", "http_guard.py"}


def _sources() -> list[Path]:
    return sorted(p for p in SHARED.glob("*.py") if p.name not in _NOT_FETCHERS)


def test_plan_hosts_present():
    for h in ("nsearchives.nseindia.com", "www.nseindia.com", "niftyindices.com", "www.niftyindices.com",
              "api.icicidirect.com", "breezeapi.icicidirect.com", "ftp.cmegroup.com", "fred.stlouisfed.org",
              "api.stlouisfed.org"):
        assert h in hc.ALLOWED_HOSTS, h
    assert hc.INTERNAL_HOSTS >= {"127.0.0.1", "localhost"}


def test_gold_allowlist_is_a_subset_of_the_shared_one():
    from gold import hosts as gold_hosts
    assert set(gold_hosts.ALLOWED_HOSTS) <= set(hc.ALLOWED_HOSTS)
    assert set(gold_hosts.FORBIDDEN_HOST_FRAGMENTS) <= set(hc.FORBIDDEN_HOST_FRAGMENTS)


def test_every_url_host_literal_under_shared_is_allowlisted():
    offenders = []
    for p in _sources():
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for h in URL_HOST.findall(line):
                if h.lower() not in hc.ALLOWED_HOSTS and h.lower() not in hc.INTERNAL_HOSTS and "example" not in h:
                    offenders.append((p.name, lineno, h))
    assert not offenders, offenders


def test_forbidden_publishers_are_never_fetched():
    """A forbidden host may be named in prose (mcx_specs.py says mcxindia.com answers 403) but never in a URL."""
    hits = []
    for p in _sources():
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for h in URL_HOST.findall(line):
                if any(frag in h.lower() for frag in hc.FORBIDDEN_HOST_FRAGMENTS):
                    hits.append((p.name, lineno, h))
    assert not hits, hits
    assert all(not hc.is_allowed(f"https://{frag}/x") for frag in hc.FORBIDDEN_HOST_FRAGMENTS)


def test_no_yahoo_caller_under_shared():
    for p in _sources():
        text = p.read_text(encoding="utf-8")
        assert "import yfinance" not in text and "from yfinance" not in text, p.name
        assert "/v8/finance/chart" not in text, f"{p.name} carries a Yahoo chart call"
