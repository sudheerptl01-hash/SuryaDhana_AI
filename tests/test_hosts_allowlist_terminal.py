"""G5 (Terminal v2 PLAN 1.7 / §0.6 / §0.7): a static scan of fo_iv/, index_drivers/, data_health/ and nse_positions.py — every
URL host literal is in the shared allowlist (and never Yahoo), the forbidden publishers are absent, no ``yfinance`` /
``query1`` / ``query2`` caller exists in the new code, every publisher fetch goes through ``shared.http_client.PacedClient``
(no bare ``httpx.get`` / ``requests``; in nse_positions.py the Terminal v2 section is scanned and the pre-v2 clients there
and in bhavcopy.py are pinned by count — the documented exemption), and the client refuses a forbidden host before any
socket opens."""
from __future__ import annotations

import re
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from shared import http_client as hc  # noqa: E402

DS = ROOT / "services" / "data-service"
URL_HOST = re.compile(r"(?:https?|ftp)://([A-Za-z0-9.\-]+)")
PACKAGES = ("fo_iv", "index_drivers", "data_health")


def _sources() -> list[Path]:
    out = [DS / "nse_positions.py"]
    for pkg in PACKAGES:
        out.extend(sorted((DS / pkg).glob("*.py")))
    return out


def test_the_three_packages_exist():
    for pkg in PACKAGES:
        assert (DS / pkg / "__init__.py").exists(), pkg


def test_every_url_host_literal_is_allowlisted_and_never_yahoo():
    offenders = []
    for p in _sources():
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for h in URL_HOST.findall(line):
                h = h.lower()
                if h in hc.YAHOO_HOSTS or h not in hc.ALLOWED_HOSTS and h not in hc.INTERNAL_HOSTS:
                    offenders.append((p.name, lineno, h))
    assert not offenders, offenders


def test_forbidden_publishers_and_yahoo_callers_are_absent():
    for p in _sources():
        text = p.read_text(encoding="utf-8")
        for frag in hc.FORBIDDEN_HOST_FRAGMENTS:
            assert frag not in text, (p.name, frag)
        assert "yfinance" not in text and "query1.finance" not in text and "query2.finance" not in text, p.name
        assert "/v8/finance/chart" not in text, p.name


def test_no_bare_http_client_in_the_new_packages():
    """Publisher fetches go through the paced client the caller injects (``http.get``); never ``httpx.get`` / ``requests``."""
    bad = []
    for pkg in PACKAGES:
        for p in sorted((DS / pkg).glob("*.py")):
            text = p.read_text(encoding="utf-8")
            if re.search(r"\brequests\.(get|post)\(", text) or re.search(r"\bhttpx\.(get|post)\(", text) or "httpx.Client(" in text:
                bad.append(p.name)
    assert not bad, bad


BARE_HTTP = (re.compile(r"\brequests\.(get|post)\("), re.compile(r"\bhttpx\.(get|post)\("), re.compile(r"httpx\.Client\("))
V2_BANNER = "# Terminal v2 (PLAN 1.1 / 1.4 / Wave 0 0.5; builder B1-DATA)"
# The documented exemption (check:B1-DATA): the PRE-v2 ingests in these two files build their own httpx.Client (the 18:30
# bhavcopy, the F&O / participant-OI / MTF files, the deals API) — legacy paths, hosts nsearchives / www.nseindia.com only,
# pinned here by count so that ANY new bare client in either file fails this test.
LEGACY_BARE_CLIENTS = {"nse_positions.py": 2, "bhavcopy.py": 1}


def _bare_hits(text: str) -> int:
    return sum(len(rx.findall(text)) for rx in BARE_HTTP)


def test_nse_positions_v2_section_has_no_bare_http_and_the_legacy_clients_are_pinned():
    """nse_positions.py's Terminal v2 section (the evening files, the bhavcopy revision pass, the VIX backfill) fetches only
    through the injected PacedClient (``http.get`` / ``fetch_logged``); the legacy section and bhavcopy.py keep their
    pre-existing clients, counted."""
    text = (DS / "nse_positions.py").read_text(encoding="utf-8")
    assert text.count(V2_BANNER) == 1, "the Terminal v2 banner moved: re-anchor the scan"
    legacy, v2 = text.split(V2_BANNER, 1)
    assert _bare_hits(v2) == 0, "a bare httpx / requests call in nse_positions.py's Terminal v2 section"
    assert "fetch_logged(" in v2 and "http.get(" in v2
    assert _bare_hits(legacy) == LEGACY_BARE_CLIENTS["nse_positions.py"]
    assert _bare_hits((DS / "bhavcopy.py").read_text(encoding="utf-8")) == LEGACY_BARE_CLIENTS["bhavcopy.py"]
    # negative control: the scan sees a bare call when one is there
    assert _bare_hits(v2 + "\n    r = httpx.get(url)\n") == 1 and _bare_hits("requests.post(u)") == 1


def test_paced_client_refuses_before_any_socket_and_sends_if_modified_since():
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return httpx.Response(200, text="ok")

    c = hc.PacedClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    for url in ("https://www.mcxindia.com/x", "https://www.cmegroup.com/x", "https://www.kitco.com/x", "https://query2.finance.yahoo.com/v8/finance/chart/GC=F"):
        with pytest.raises(hc.HostNotAllowed):
            c.get(url)
    assert calls == []
    r = c.get_if_modified("https://nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_04112026.csv", last_modified="Wed, 04 Nov 2026 11:31:10 GMT")
    assert r.status_code == 200 and calls[-1].headers["If-Modified-Since"] == "Wed, 04 Nov 2026 11:31:10 GMT"
    assert "Mozilla" in calls[-1].headers["User-Agent"]                      # browser UA for NSE


def test_nse_file_urls_are_on_nsearchives_or_niftyindices():
    import nse_positions
    from index_drivers import ingest

    for u in (nse_positions.FOVOLT_URL, nse_positions.CONTRACT_DELTA_URL, nse_positions.COMBINED_OI_DELEQ_URL, nse_positions.INDEX_CLOSE_URL,
              nse_positions.PARTICIPANT_VOL_URL, nse_positions.FII_STATS_URL, nse_positions.MWPL_CLI_URL, ingest.TOP10_URL):
        assert hc.host_of(u) == "nsearchives.nseindia.com", u
    for u in ingest.CONSTITUENT_URLS.values():
        assert hc.host_of(u) == "niftyindices.com", u
    assert hc.host_of(nse_positions.VIX_HISTORY_URL) == "www.nseindia.com"
