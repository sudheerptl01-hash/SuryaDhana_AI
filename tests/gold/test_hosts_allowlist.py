"""T8 — the host allowlist (PLAN §c.6): a static scan of the package for URL hosts, the wrapper's refusal before any
socket opens, the forbidden publishers, the FRED keyless rule, UA selection, pacing and the 429 back-off."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from _support import DATA_SERVICE
from gold import hosts

PKG = DATA_SERVICE / "gold"
URL_HOST = re.compile(r"(?:https?|ftp)://([A-Za-z0-9.\-]+)")
PLAN_ALLOWED = {
    "query1.finance.yahoo.com", "query2.finance.yahoo.com", "publicreporting.cftc.gov", "www.cftc.gov", "ftp.cmegroup.com",
    "home.treasury.gov", "fred.stlouisfed.org", "api.spdrgoldshares.com", "www.ishares.com", "fsapi.gold.org", "api.imf.org",
    "cdn.lbma.org.uk", "www.lbma.org.uk", "en.sge.com.cn", "www.sge.com.cn", "www.shfe.com.cn", "ibjarates.com", "www.rbi.org.in",
    "directlink.icicidirect.com", "zerodha.com", "portal.amfiindia.com", "pib.gov.in", "ocean.nivel.bazg.admin.ch",
    "www.atlantafed.org", "nfs.faireconomy.media", "www.bea.gov", "www.matteoiacoviello.com", "thedocs.worldbank.org",
    "api.gold-api.com", "news.google.com",
}


def _sources() -> list[Path]:
    return sorted(p for p in PKG.glob("*.py") if p.name != "__init__.py")


def test_the_constant_is_exactly_the_plan_allowlist():
    assert set(hosts.ALLOWED_HOSTS) == PLAN_ALLOWED
    assert hosts.INTERNAL_HOSTS == {"127.0.0.1", "localhost"}


def test_every_fetched_host_literal_is_allowlisted():
    offenders = []
    for p in _sources():
        if p.name in ("catalog_seed.py", "hosts.py"):          # the data dictionary carries LINK-ONLY urls; hosts.py the forbidden list
            continue
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for h in URL_HOST.findall(line):
                if h.lower() not in hosts.ALLOWED_HOSTS and h.lower() not in hosts.INTERNAL_HOSTS:
                    offenders.append((p.name, lineno, h))
    assert not offenders, offenders


def test_forbidden_publishers_never_appear_outside_the_link_rows():
    for p in _sources():
        if p.name in ("catalog_seed.py", "hosts.py"):
            continue
        text = p.read_text(encoding="utf-8")
        for frag in hosts.FORBIDDEN_HOST_FRAGMENTS:
            assert frag not in text, (p.name, frag)
    seed = (PKG / "catalog_seed.py").read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(seed):
        if any(f in line for f in hosts.FORBIDDEN_HOST_FRAGMENTS):
            window = " ".join(seed[i:i + 4])                       # the _row(...) call: verdict sits on the next line
            assert "LINK-ONLY" in window, line


def test_fred_rest_api_is_never_used_without_a_key():
    for p in _sources():
        assert "api.stlouisfed.org" not in p.read_text(encoding="utf-8"), p.name


def test_assert_allowed_refuses_before_any_socket():
    with pytest.raises(hosts.HostNotAllowed):
        hosts.assert_allowed("https://www.cmegroup.com/x")
    with pytest.raises(hosts.HostNotAllowed):
        hosts.assert_allowed("https://www.kitco.com/charts/gold")
    assert hosts.assert_allowed("ftp://ftp.cmegroup.com/daily_volume/daily_volume.xlsx") == "ftp.cmegroup.com"
    assert hosts.assert_allowed("http://127.0.0.1:8010/api/gold/health") == "127.0.0.1"
    assert hosts.is_allowed("https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10") and not hosts.is_allowed("https://stooq.com/q")


def test_client_never_opens_a_socket_for_a_refused_host():
    import httpx

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, text="ok")

    client = hosts.GoldHttp(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    with pytest.raises(hosts.HostNotAllowed):
        client.get("https://prices.lbma.org.uk/json/gold_pm.json")
    with pytest.raises(hosts.HostNotAllowed):
        client.stream_to_file("https://www.mcxindia.com/x.zip", "/dev/null")
    assert calls == []
    r = client.get("https://fred.stlouisfed.org/graph/fredgraph.csv", params={"id": "DFII10"})
    assert r.status_code == 200 and calls == ["https://fred.stlouisfed.org/graph/fredgraph.csv?id=DFII10"]


def test_user_agents_follow_the_plan():
    assert hosts.user_agent_for("query2.finance.yahoo.com") == hosts.APP_UA == "Mozilla/5.0 (SuryaDhana-GoldDesk)"
    assert hosts.user_agent_for("fred.stlouisfed.org") is None          # FRED stalls on every UA naming the app: library default
    assert hosts.user_agent_for("api.imf.org") == hosts.PLAIN_UA
    assert "User-Agent" not in hosts._base_headers("fred.stlouisfed.org") and hosts._base_headers("api.imf.org")["User-Agent"] == hosts.PLAIN_UA
    assert hosts.user_agent_for("www.lbma.org.uk") == hosts.BROWSER_UA


def test_pacing_and_429_backoff():
    import httpx

    status = {"code": 200}
    clock = {"t": 1000.0}
    slept: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status["code"], text="x")

    client = hosts.GoldHttp(transport=httpx.MockTransport(handler), sleep=lambda s: slept.append(s), clock=lambda: clock["t"])
    client.get("https://query2.finance.yahoo.com/v8/finance/chart/GC=F")
    client.get("https://query2.finance.yahoo.com/v8/finance/chart/SI=F")
    assert slept and slept[-1] == pytest.approx(hosts.YAHOO_GAP_S)        # one Yahoo call per symbol 6 s apart
    status["code"] = 429
    client.get("https://query2.finance.yahoo.com/v8/finance/chart/PL=F")
    with pytest.raises(RuntimeError, match="backing off"):
        client.get("https://query2.finance.yahoo.com/v8/finance/chart/GLD")
    clock["t"] += 5 * 60 + 1
    status["code"] = 200
    client.get("https://query2.finance.yahoo.com/v8/finance/chart/GLD")       # after 5 min the host is open again


def test_ftp_fetch_rejects_http_urls_and_other_hosts():
    with pytest.raises(ValueError, match="ftp://"):
        hosts.ftp_fetch("https://ftp.cmegroup.com/x")
    with pytest.raises(hosts.HostNotAllowed):
        hosts.ftp_fetch("ftp://ftp.example.org/x")


def test_ftp_client_parses_cme_229_reply_to_pasv() -> None:
    """CME answers PASV with the EPSV ``229`` form; stock ftplib raises error_reply (R-DATA §6: 0 rows ever)."""
    import socket as _socket

    from gold import hosts

    class Fake(hosts._PassiveFtp):
        def __init__(self, reply: str) -> None:
            self.af = _socket.AF_INET
            self.trust_server_pasv_ipv4_address = False
            self._reply = reply

            class _Sock:
                @staticmethod
                def getpeername() -> tuple[str, int]:
                    return ("192.0.2.10", 21)

            self.sock = _Sock()

        def sendcmd(self, cmd: str) -> str:
            assert cmd == "PASV"
            return self._reply

    assert Fake("229 Extended Passive Mode Entered (|||53267|)").makepasv() == ("192.0.2.10", 53267)
    assert Fake("227 Entering Passive Mode (192,0,2,10,208,19)").makepasv() == ("192.0.2.10", 208 * 256 + 19)
    import ftplib

    with pytest.raises(ftplib.error_reply):
        ftplib.FTP.makepasv(Fake("229 Extended Passive Mode Entered (|||53267|)"))  # negative control: stock ftplib


def test_fred_breaker_stops_after_three_consecutive_failures() -> None:
    """R-DATA §6: 18 × 20 s timeouts burned 378 s per run while FRED stalled; the run now gives up after three."""
    import httpx
    from gold import ingest_macro

    calls: list[tuple[str, float | None]] = []

    class StallingHttp:
        def get(self, url: str, *, timeout_s: float | None = None, **_: object) -> object:
            calls.append((url, timeout_s))
            raise httpx.ReadTimeout("stalled")

    out = ingest_macro.fetch_fred(store=None, http=StallingHttp(), group="daily")
    assert len(calls) == ingest_macro.FRED_BREAKER_AFTER and all(t == ingest_macro.FRED_TIMEOUT_S for _, t in calls)
    statuses = [v["status"] for v in out.values()]
    assert statuses[:3] == ["error"] * 3 and len(out) > 3 and set(statuses[3:]) == {"skipped"}
