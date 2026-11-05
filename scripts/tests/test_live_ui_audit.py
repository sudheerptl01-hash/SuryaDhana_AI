"""Live program (reports/live_nse) gate in the UI harness: ``ui_audit.py``'s live-freshness assertion.

While NSE is open a chip that reads LIVE for a market feed (Breeze / ICICI / NSE, or a bare LIVE) must carry its age and
be at most 10 s old; with the Breeze feed LIVE every audited page shows at least one such chip; after the close (the live
service's own market state) none reads LIVE; the non-NSE pages (GOLD, MCXG, CMDT) are exempt; when the live service is
not deployed the clock decides open/closed and only the age rule runs. Each rule has a negative control. No live stack:
the market-state GETs go to an injected fake, the browser test renders a fixture page with ``set_content`` (no network)
and is skipped only when no Chromium can start.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ui_audit  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
NOW_MS = datetime(2026, 11, 5, 11, 0, 0, tzinfo=IST).timestamp() * 1000


def _iso(sec_ago: float) -> str:
    return datetime.fromtimestamp(NOW_MS / 1000 - sec_ago, tz=IST).isoformat(timespec="seconds")


def chip(state: str = "live", label: str = "LIVE · BREEZE", *, asof: str | None = None, age_s: Any = None,
         kind: str = "chip") -> dict[str, Any]:
    return {"kind": kind, "state": state, "label": label, "title": "", "asof": asof, "age_s": age_s, "source": None}


def probe(*chips: dict[str, Any]) -> dict[str, Any]:
    return {"now_ms": NOW_MS, "chips": list(chips)}


OPEN_LIVE = {"market": "open", "authoritative": True, "feed": "LIVE"}
OPEN_OFF = {"market": "open", "authoritative": True, "feed": "OFF"}
CLOSED = {"market": "closed", "authoritative": True, "feed": "LIVE"}
CLOSED_CLOCK = {"market": "closed", "authoritative": False, "feed": None}


# ── the age of a chip ───────────────────────────────────────────────────────────────────────────────────────────────
def test_chip_age_reads_the_age_attribute_then_the_asof():
    assert ui_audit.chip_age_s(chip(age_s="3.5"), NOW_MS) == 3.5
    assert ui_audit.chip_age_s(chip(asof=_iso(7)), NOW_MS) == pytest.approx(7, abs=0.01)
    assert ui_audit.chip_age_s(chip(asof="2026-11-05T05:29:53Z"), NOW_MS) == pytest.approx(7, abs=0.01)   # UTC form
    # a naive stamp is IST (the app's own clock), not UTC
    assert ui_audit.chip_age_s(chip(asof="2026-11-05T10:59:50"), NOW_MS) == pytest.approx(10, abs=0.01)
    # negative controls: no age at all, unparsable, negative, NaN
    assert ui_audit.chip_age_s(chip(), NOW_MS) is None
    assert ui_audit.chip_age_s(chip(asof="10:59 IST"), NOW_MS) is None
    assert ui_audit.chip_age_s(chip(age_s="-1"), NOW_MS) is None
    assert ui_audit.chip_age_s(chip(age_s="nan"), NOW_MS) is None
    assert ui_audit.chip_age_s(chip(age_s="x", asof=_iso(2)), NOW_MS) == pytest.approx(2, abs=0.01)   # falls to as-of


def test_the_age_a_label_prints_is_read_and_a_clock_is_not():
    assert ui_audit.label_age_s("LIVE · BREEZE · 2s") == 2.0
    assert ui_audit.label_age_s("LIVE · BREEZE · 3s · 40/52 LIVE") == 3.0
    assert ui_audit.label_age_s("STALE · NSE · 6m") == 360.0 and ui_audit.label_age_s("STALE · NSE · 3h") == 10800.0
    assert ui_audit.label_age_s("DELAYED · NSE · 10:58") is None and ui_audit.label_age_s("LIVE · BREEZE") is None
    assert ui_audit.label_age_s(None) is None
    assert ui_audit.label_age_s("BREEZE LIVE · last trade 100s") == 100.0
    # the header's live chip: '● LIVE' with the age in its hover text
    hdr = chip(label="● LIVE", kind="feed")
    hdr["title"] = "ICICI Breeze websocket · last tick 10:59:59 IST · 1s old"
    assert ui_audit.title_age_s(hdr["title"]) == 1.0 and ui_audit.chip_age_s(hdr, NOW_MS) == 1.0
    assert ui_audit.title_age_s("NSE closed: the last session's close") is None
    assert ui_audit.live_failures("brief", probe(hdr), OPEN_LIVE) == []
    hdr_old = {**hdr, "title": "ICICI Breeze websocket · last tick 10:58:00 IST · 2m old"}
    assert ui_audit.live_failures("brief", probe(hdr_old), OPEN_OFF)
    # order: the attribute beats the label, the label beats the as-of
    assert ui_audit.chip_age_s(chip(label="LIVE · BREEZE · 2s", age_s="4"), NOW_MS) == 4.0
    assert ui_audit.chip_age_s(chip(label="LIVE · BREEZE · 2s", asof=_iso(30)), NOW_MS) == 2.0
    fails = ui_audit.live_failures("watch", probe(chip(label="LIVE · BREEZE · 14s")), OPEN_OFF)
    assert len(fails) == 1 and "14 s old" in fails[0]


def test_only_market_feeds_count_as_live_prices():
    for label in ("LIVE · BREEZE", "LIVE · ICICI", "LIVE · NSE", "● LIVE", "BREEZE LIVE · 2s", "LIVE"):
        assert ui_audit.is_live_market_chip(chip(label=label)), label
    for label in ("LIVE · CONTROLLER", "LIVE · SERVICE PROBES", "LIVE · MCX SESSION CLOCK", "LIVE · YAHOO"):
        assert not ui_audit.is_live_market_chip(chip(label=label)), label
    assert not ui_audit.is_live_market_chip(chip(state="delayed", label="DELAYED · NSE · 10:58"))
    assert not ui_audit.is_live_market_chip(chip(state="closed", label="CLOSE 04 NOV"))
    assert ui_audit.is_live_market_chip(chip(state="LIVE", label="LIVE", kind="price"))        # stock-window marker
    assert ui_audit.is_live_market_chip(chip(state="live", label="● LIVE", kind="feed"))       # header feed chip


# ── the rules ───────────────────────────────────────────────────────────────────────────────────────────────────────
def test_market_open_fresh_live_chip_passes_and_old_or_ageless_fail():
    assert ui_audit.live_failures("movers", probe(chip(asof=_iso(2))), OPEN_LIVE) == []
    assert ui_audit.live_failures("movers", probe(chip(age_s="9.9")), OPEN_LIVE) == []
    old = ui_audit.live_failures("movers", probe(chip(asof=_iso(11)), chip(asof=_iso(1))), OPEN_LIVE)
    assert len(old) == 1 and "11 s old" in old[0]
    ageless = ui_audit.live_failures("movers", probe(chip(label="● LIVE", kind="feed"), chip(asof=_iso(1))), OPEN_LIVE)
    assert len(ageless) == 1 and "no age" in ageless[0]
    # the bound is the argument (the CLI's --live-max-age)
    assert ui_audit.live_failures("movers", probe(chip(asof=_iso(11))), OPEN_LIVE, max_age_s=15) == []


def test_a_quiet_live_chip_says_so_and_is_held_to_the_quiet_bound():
    quiet = chip(label="LIVE · BREEZE · 60s")
    quiet["title"] = "Live feed (BREEZE) · 60s old — quiet: no new trade or quote for 60 s on a healthy feed"
    assert ui_audit.live_failures("watch", probe(quiet, chip(asof=_iso(1))), OPEN_LIVE) == []
    # it never stands in for the page's fresh live pane
    only_quiet = ui_audit.live_failures("watch", probe(quiet), OPEN_LIVE)
    assert len(only_quiet) == 1 and "no pane on watch" in only_quiet[0]
    assert ui_audit.live_failures("watch", probe(chip(label="BREEZE LIVE · last trade 100s")), OPEN_OFF) == []
    too_old = ui_audit.live_failures("watch", probe(chip(label="BREEZE LIVE · last trade 130s")), OPEN_OFF)
    assert len(too_old) == 1 and "quiet LIVE" in too_old[0]
    # negative control: the same 60 s chip that does not say quiet fails
    assert ui_audit.live_failures("watch", probe(chip(label="LIVE · BREEZE · 60s")), OPEN_OFF)


def test_feed_live_requires_one_fresh_live_pane_per_page():
    delayed_only = probe(chip(state="delayed", label="DELAYED · NSE · 10:58", asof=_iso(70)))
    fails = ui_audit.live_failures("brief", delayed_only, OPEN_LIVE)
    assert len(fails) == 1 and "no pane on brief" in fails[0]
    # negative control: with the feed OFF an honest DELAYED page is fine (nothing claims LIVE)
    assert ui_audit.live_failures("brief", delayed_only, OPEN_OFF) == []
    # and a LIVE chip while the feed is OFF still has to be fresh (it cannot be: it fails on its age)
    assert ui_audit.live_failures("brief", probe(chip(asof=_iso(300))), OPEN_OFF)


def test_after_the_close_nothing_reads_live_and_close_passes():
    assert ui_audit.live_failures("desk", probe(chip(state="closed", label="CLOSE 05 NOV", asof="2026-11-05")), CLOSED) == []
    bad = ui_audit.live_failures("desk", probe(chip(asof=_iso(1))), CLOSED)
    assert len(bad) == 1 and "after the close" in bad[0]
    # the clock alone never fails a page after the close (a special session the calendar does not know)
    assert ui_audit.live_failures("desk", probe(chip(asof=_iso(1))), CLOSED_CLOCK) == []


def test_pre_open_unknown_exempt_pages_and_missing_probe_are_skipped():
    stale = probe(chip(asof=_iso(600)))
    assert ui_audit.live_failures("brief", stale, {"market": "pre-open", "authoritative": True, "feed": "LIVE"}) == []
    assert ui_audit.live_failures("brief", stale, {"market": "unknown"}) == []
    for tab in ("gold", "mcxgold", "commodity"):
        assert ui_audit.live_failures(tab, stale, OPEN_LIVE) == [], tab
    assert ui_audit.live_failures("brief", None, OPEN_LIVE) == []
    assert ui_audit.live_failures(None, stale, OPEN_LIVE) == []
    # negative control: the same stale chip on an NSE page fails
    assert ui_audit.live_failures("brief", stale, OPEN_LIVE)


def test_run_level_api_rule():
    good = {**OPEN_LIVE, "probe_quote": {"state": "live", "source": "breeze_ws", "age_s": 0.4}}
    assert ui_audit.api_live_failures(good) == []
    assert ui_audit.api_live_failures({**good, "probe_quote": {"state": "live", "source": "breeze_ws", "age_s": 12}})
    nse = ui_audit.api_live_failures({**good, "probe_quote": {"state": "delayed", "source": "nse_api", "age_s": 60}})
    assert nse and "not live/breeze_ws" in nse[0]
    assert ui_audit.api_live_failures({**OPEN_OFF, "probe_quote": {"state": "delayed", "source": "nse_api"}}) == []
    assert ui_audit.api_live_failures({**CLOSED, "probe_quote": {"state": "closed", "source": "eod"}}) == []
    assert ui_audit.api_live_failures({**CLOSED, "probe_quote": {"state": "live", "source": "breeze_ws"}})
    assert ui_audit.api_live_failures({**CLOSED_CLOCK, "probe_quote": {"state": "live"}}) == []   # not authoritative


# ── the market context: two GETs, the clock as fallback ─────────────────────────────────────────────────────────────
class FakeFetch:
    def __init__(self, answers: dict[str, tuple[int, Any]]):
        self.answers: dict[str, tuple[int, Any]] = answers
        self.urls: list[str] = []

    def __call__(self, url: str, timeout_s: float = 5.0) -> tuple[int, Any]:
        self.urls.append(url)
        for key, ans in self.answers.items():
            if key in url:
                return ans
        return 404, None


def test_live_context_prefers_the_live_service_and_falls_back_to_the_clock():
    f = FakeFetch({"/api/live/quotes": (200, {"market": {"state": "closed", "session_date": "2026-11-05"},
                                              "quotes": {"NIFTY 50": {"state": "closed", "source": "eod"}}}),
                   "/api/live/status": (200, {"state": "LIVE"})})
    ctx = ui_audit.live_context("http://x:8010/", fetch=f, now_ist=datetime(2026, 11, 5, 11, 0, tzinfo=IST))
    assert ctx["market"] == "closed" and ctx["authoritative"] and ctx["feed"] == "LIVE"   # the service wins over the clock
    assert ctx["session_date"] == "2026-11-05" and ctx["probe_quote"]["source"] == "eod"
    assert f.urls == ["http://x:8010/api/live/quotes?symbols=NIFTY%2050", "http://x:8010/api/live/status"]
    # not deployed (404): the clock decides, not authoritative, no feed
    f404 = FakeFetch({})
    ctx2 = ui_audit.live_context("http://x:8010", fetch=f404, now_ist=datetime(2026, 11, 5, 11, 0, tzinfo=IST))
    assert ctx2["market"] == "open" and not ctx2["authoritative"] and ctx2["feed"] is None and len(ctx2["notes"]) == 2
    # a malformed market block is not trusted
    fbad = FakeFetch({"/api/live/quotes": (200, {"market": {"state": "LIVE!"}}), "/api/live/status": (500, None)})
    ctx3 = ui_audit.live_context("http://x:8010", fetch=fbad, now_ist=datetime(2026, 11, 7, 11, 0, tzinfo=IST))
    assert ctx3["market"] == "closed" and not ctx3["authoritative"]                 # Saturday by the clock


def test_clock_market_state_boundaries():
    d = datetime(2026, 11, 5, tzinfo=IST)                                             # a Thursday
    at = lambda h, m: ui_audit.clock_market_state(d.replace(hour=h, minute=m))  # noqa: E731
    assert at(8, 59) == "closed" and at(9, 0) == "pre-open" and at(9, 14) == "pre-open" and at(9, 15) == "open"
    assert at(15, 29) == "open" and at(15, 30) == "closed"
    assert ui_audit.clock_market_state(datetime(2026, 11, 8, 11, 0, tzinfo=IST)) == "closed"   # Sunday


def test_live_gate_refreshes_the_context_at_most_once_a_minute_and_collects_run_failures():
    t = [1000.0]
    f = FakeFetch({"/api/live/quotes": (200, {"market": {"state": "open", "session_date": "2026-11-05"},
                                              "quotes": {"NIFTY 50": {"state": "live", "source": "breeze_ws", "age_s": 30}}}),
                   "/api/live/status": (200, {"state": "LIVE"})})
    gate = ui_audit.LiveGate("http://x:8010", fetch=f, clock=lambda: t[0])
    r1 = gate.tab("brief", probe(chip(asof=_iso(1))))
    t[0] += 30
    gate.tab("movers", probe(chip(asof=_iso(1))))
    assert len(f.urls) == 2                                      # one context for both tabs (≤ 1 refresh / 60 s)
    t[0] += 31
    r3 = gate.tab("gold", probe(chip(asof=_iso(900))))
    assert len(f.urls) == 4 and r3["exempt"] and r3["failures"] == []
    assert r1["market"] == "open" and r1["feed"] == "LIVE" and r1["live_chips"] == 1 and r1["failures"] == []
    run = gate.run_failures()
    assert len(run) == 1 and "age_s 30" in run[0]                # the heartbeat quote is 30 s old with the feed LIVE


# ── the probe reads the chips before it leaves the tab ──────────────────────────────────────────────────────────────
class FakePage:
    def __init__(self):
        self.calls: list[str] = []

    def on(self, *_a: Any) -> None:
        pass

    def evaluate(self, js: str) -> Any:
        self.calls.append("evaluate-live" if js == ui_audit.LIVE_CHIPS_JS else "evaluate")
        return probe(chip(asof=_iso(1)))

    def goto(self, url: str, **_k: Any) -> None:
        self.calls.append(f"goto {url}")

    def wait_for_timeout(self, _ms: int) -> None:
        pass


def test_live_tab_probe_captures_before_leaving_and_only_when_asked():
    page = FakePage()
    p = ui_audit.LiveTabProbe(page, "http://x:8010")
    epoch = p.begin()
    p.leave()
    assert page.calls == ["evaluate-live", "goto about:blank"] and p.live_chips[epoch]["chips"]
    p.leave()                                                     # between tabs (no active epoch): nothing read
    assert page.calls.count("evaluate-live") == 1
    page2 = FakePage()
    off = ui_audit.LiveTabProbe(page2, "http://x:8010", capture_live=False)
    off.begin()
    off.leave()
    assert page2.calls == ["goto about:blank"] and off.live_chips == {}


def test_cli_flags_and_markdown():
    ap = ui_audit.build_parser()
    a = ap.parse_args([])
    assert a.live_check is True and a.live_max_age == 10.0
    b = ap.parse_args(["--no-live-check", "--live-max-age", "5"])
    assert b.live_check is False and b.live_max_age == 5.0
    rep = {"meta": {"base": "b", "started_at": "s", "finished_at": "f", "strict": False, "wait_s": 6, "live_check": True},
           "engines": {}, "ok": False,
           "live": {"max_age_s": 10.0, "api_failures": ["live api: x"],
                    "contexts": [{"market": "open", "authoritative": True, "feed": "LIVE"}]}}
    md = ui_audit.render_markdown(rep)
    assert "## Live freshness" in md and "market open (live service)" in md and "live api: x" in md
    rep_off = {**rep, "live": None, "meta": {**rep["meta"], "live_check": False}}
    assert "off (--no-live-check)" in ui_audit.render_markdown(rep_off)


# ── the DOM script on a real engine (fixture page, no network) ──────────────────────────────────────────────────────
FIXTURE_HTML = """<!doctype html><html><body>
<header><span data-feed="live" data-sd-asof="{fresh}">● LIVE</span></header>
<section data-sd-source="live"><header><span data-sd-chip="live" data-sd-age-s="2.5">LIVE · BREEZE</span></header></section>
<section><header><span data-sd-chip="live">LIVE · NSE</span></header></section>
<section><header><span data-sd-chip="delayed" data-sd-asof="{old}">DELAYED · NSE · 10:58</span></header></section>
<div><span data-sd-price="LIVE" title="Broker websocket ticks">LIVE</span></div>
<section><header><span data-sd-chip="live">LIVE · CONTROLLER</span></header></section>
<header><span data-feed="live" title="ICICI Breeze websocket · last tick 10:59:59 IST · 1s old">● LIVE</span></header>
<section><header><span data-sd-chip="live" title="Live feed (BREEZE) · 3s old"><i></i>LIVE · BREEZE · 3s · 40/52 LIVE</span></header></section>
</body></html>"""


def test_live_chips_js_in_chromium():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - no bundled Chromium on this machine
            pytest.skip(f"no Chromium: {exc}")
        try:
            page = browser.new_page()
            now = datetime.now(IST)
            page.set_content(FIXTURE_HTML.format(fresh=(now - timedelta(seconds=1)).isoformat(),
                                                 old=(now - timedelta(seconds=70)).isoformat()))
            got = page.evaluate(ui_audit.LIVE_CHIPS_JS)
        finally:
            browser.close()
    chips = got["chips"]
    assert [c["kind"] for c in chips] == ["feed", "chip", "chip", "chip", "price", "chip", "feed", "chip"]
    assert [c["state"] for c in chips] == ["live", "live", "live", "delayed", "LIVE", "live", "live", "live"]
    # LV-UI's formats (source.ts sourceChipText, liveModel.ts liveHeaderChip) are read as ages
    assert ui_audit.chip_age_s(chips[6], got["now_ms"]) == 1.0 and ui_audit.chip_age_s(chips[7], got["now_ms"]) == 3.0
    assert chips[1]["age_s"] == "2.5" and chips[0]["asof"] and chips[2]["asof"] is None
    fails = ui_audit.live_failures("brief", got, OPEN_LIVE)
    # the ageless LIVE · NSE chip and the ageless stock-window marker fail; the controller chip is not a market price
    assert len(fails) == 2 and all("no age" in f for f in fails), fails
    assert any("LIVE · NSE" in f for f in fails) and not any("CONTROLLER" in f for f in fails)
