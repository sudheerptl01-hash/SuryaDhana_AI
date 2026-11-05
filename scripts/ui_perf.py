#!/usr/bin/env python3
"""ui_perf.py: SuryaDhana terminal performance harness (desktop program, PLAN AC-13).

Measures, per browser engine (Chromium and/or WebKit, the engine of the macOS app's WKWebView):

* **Cold load of /** in a fresh context (empty cache): TTFB, FCP, DOMContentLoaded, load, app-ready
  (terminal chrome rendered and the initial "Connecting to SuryaDhana services" state gone), JS/CSS bytes on the
  wire and decoded, gzip-equivalent JS (what AC-13's "first-load JS <= 300 kB gz" means), request count.
* **In-app tab switch latency for all 43 pages**, using the app's own navigation (the `suryadhana:goto` event that
  `lib/navigate.ts` goToPage() dispatches). A switch is done when the page title shows the tab's code (set in a
  passive effect after React commits), the lazy-tab skeleton (`[aria-busy][aria-label="Loading page"]`) is gone and
  the tab's own network is idle for --idle-ms (default 500 ms). Background pollers of the chrome (header quotes,
  service status...) and long-lived streams (SSE, WebSocket) are excluded from the idle rule, but listed.
  p50/p95 over --runs.
* JS heap (Chromium: CDP Performance.getMetrics; WebKit has no API: null), long tasks (Chromium PerformanceObserver)
  and an engine-neutral event-loop lag monitor (both engines).
* Optional post-load idle window (--post-load-wait S): after the cold load settles the page sits idle for S seconds
  and the harness records what the app does on its own meanwhile (requests, JS fetched, event-loop lag, long tasks),
  e.g. the cost of idle-time prefetching. It also keeps that background work out of the first tab samples.
* Optional static bundle analysis of an export dir (--bundle-dir): first-load JS set from index.html and the largest
  chunks, raw and gzip.

Safety (PLAN §2): the live stack is read-only for this tool. Every non-GET request to /api is aborted by default
(--allow-writes disables that), and the run is strictly sequential: one browser, one page at a time. Each context
also pins the UI's settings sync to --prefs-mode (default readonly, like ui_audit/parity): it hydrates from
/api/prefs but never writes, so a run against live :8010 neither uploads page defaults into the owner's settings
store nor fills the measurements with blocked prefs writes (desktop review C3-logic-unchanged-08).

Usage:
    P=/Users/sudheer/Desktop/jupyter_env/bin/python
    $P scripts/ui_perf.py --base http://127.0.0.1:8010 --browser both --runs 3 --label live_8010
    $P scripts/ui_perf.py --base http://127.0.0.1:8093 --browser webkit --tabs brief,desk,charts --runs 5
    $P scripts/ui_perf.py --bundle-dir /path/to/export --label export   # bundle analysis only (no browser)
    $P scripts/ui_perf.py --summarize a.json b.csv                         # markdown tables from raw JSON or CSV

Outputs: <out-dir>/perf_<label>.csv (one row per sample) and <json-dir>/perf_<label>.json (raw, incl. waterfalls),
plus a markdown summary on stdout (and <out-dir>/perf_<label>_summary.md with --write-summary).
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import json
import re
import statistics
import sys
import time
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

REPO = Path(__file__).resolve().parents[1]
PAGE_TSX = REPO / "ui" / "app" / "page.tsx"
DEFAULT_OUT = REPO / "reports" / "desktop_app"

#: PLAN §6 AC-13 budgets (the ones a browser harness can measure; RSS/CPU come from the app's --self-test).
BUDGETS: dict[str, float] = {
    "tab_switch_p95_ms": 400.0,
    "first_load_js_gz_kb": 300.0,
    "boot_to_interactive_ms": 2500.0,
}

#: Long-lived requests that never "finish" (SSE, streamed fetches, websockets) never block network idle.
STREAM_RE = re.compile(r"/stream(?:/|\?|$)|/ws/|/rl-stream/|/ml-stream/")
#: Resource types that are never part of "network idle".
STREAM_TYPES = {"eventsource", "websocket"}

GOTO_EVENT = "suryadhana:goto"
SKELETON_SELECTOR = '[aria-busy="true"][aria-label="Loading page"]'
CONNECTING_TEXT = "Connecting to SuryaDhana services"


# ── page list (single source of truth: ui/app/page.tsx) ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class PageDef:
    """One terminal page: id (?tab=), Bloomberg-style function code and label, as in COMMAND_PAGES."""

    id: str
    code: str
    label: str


def load_pages(path: Path = PAGE_TSX) -> list[PageDef]:
    """Parse COMMAND_PAGES out of page.tsx and cross-check it against TAB_IDS (both must list the same ids; the count
    follows page.tsx — 43 since the gold program's GOLD page — so nothing here needs an edit when a page is added)."""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"const COMMAND_PAGES: CommandPage\[\] = \[(.*?)\n\]", src, re.DOTALL)
    if not m:
        raise SystemExit(f"COMMAND_PAGES not found in {path}")
    rows = re.findall(r"\{\s*id:\s*'([^']+)',\s*code:\s*'([^']+)',\s*label:\s*'((?:[^'\\]|\\.)*)'", m.group(1))
    pages = [PageDef(i, c, lbl.replace("\\'", "'")) for i, c, lbl in rows]
    t = re.search(r"const TAB_IDS: Tab\[\] = \[(.*?)\]", src, re.DOTALL)
    if t:
        ids = re.findall(r"'([^']+)'", t.group(1))
        if sorted(ids) != sorted(p.id for p in pages):
            raise SystemExit(f"TAB_IDS and COMMAND_PAGES disagree: {sorted(set(ids) ^ {p.id for p in pages})}")
    return pages


# ── in-page instrumentation ─────────────────────────────────────────────────────────────────────────────────

INIT_SCRIPT = r"""
(() => {
  if (window.__sdPerf) return;
  const P = { lags: [], longtasks: [], switch: null };
  window.__sdPerf = P;
  try { performance.setResourceTimingBufferSize(50000) } catch (e) {}
  // Engine-neutral main-thread blocking monitor: a 50 ms heartbeat; a gap > 100 ms means the thread was busy.
  let last = performance.now();
  setInterval(() => {
    const now = performance.now(), gap = now - last;
    if (gap > 100 && document.visibilityState === 'visible') P.lags.push([Math.round(last), Math.round(gap - 50)]);
    last = now;
  }, 50);
  try {
    new PerformanceObserver(list => {
      for (const e of list.getEntries()) P.longtasks.push([Math.round(e.startTime), Math.round(e.duration)]);
    }).observe({ type: 'longtask', buffered: true });
  } catch (e) { P.longtasks = null }   // WebKit: no Long Tasks API
})();
"""

SWITCH_JS = r"""
([tab, code, skel, evt]) => {
  const P = window.__sdPerf;
  const t0 = performance.now();
  const S = { tab, t0, t0Epoch: performance.timeOrigin + t0, readyAt: null, frames: 0 };
  P.switch = S;
  const ready = () => document.title.startsWith(code + ' ') && !document.querySelector(skel)
    && new URLSearchParams(location.search).get('tab') === tab;
  const tick = () => {
    if (P.switch !== S) return;
    S.frames++;
    if (S.frames >= 2 && ready()) { S.readyAt = performance.now() - t0; return }
    requestAnimationFrame(tick);
  };
  window.dispatchEvent(new CustomEvent(evt, { detail: tab }));
  requestAnimationFrame(tick);
  return { t0Epoch: S.t0Epoch };
}
"""

TIMING_JS = r"""
() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  // WebKit can report 0 for domContentLoadedEventEnd in PerformanceNavigationTiming: fall back to Navigation Timing L1
  const L1 = performance.timing, l1 = (k) => (L1 && L1[k] > 0 ? L1[k] - L1.navigationStart : null);
  const pos = (v, k) => (v > 0 ? v : l1(k));
  const paint = Object.fromEntries(performance.getEntriesByType('paint').map(p => [p.name, p.startTime]));
  const mem = performance.memory ? { used: performance.memory.usedJSHeapSize, total: performance.memory.totalJSHeapSize } : null;
  return {
    ttfb: pos(nav.responseStart, 'responseStart'), dcl: pos(nav.domContentLoadedEventEnd, 'domContentLoadedEventEnd'),
    load: pos(nav.loadEventEnd, 'loadEventEnd'),
    fcp: paint['first-contentful-paint'] ?? null, fp: paint['first-paint'] ?? null, mem,
    nodes: document.getElementsByTagName('*').length,
  };
}
"""


# ── network log (Playwright events; browser-side epoch timing) ─────────────────────────────────────────────

@dataclass
class Rec:
    """One request seen by the page."""

    req: Any
    url: str
    path: str
    method: str
    rtype: str
    host: str
    mono_start: float
    mono_end: float | None = None
    failed: str | None = None
    status: int | None = None
    blocked: bool = False

    @property
    def stream(self) -> bool:
        return self.rtype in STREAM_TYPES or bool(STREAM_RE.search(self.path))

    def epoch_window(self) -> tuple[float | None, float | None]:
        """(start, end) in browser epoch ms from Playwright's resource timing, when available."""
        try:
            t = self.req.timing
        except Exception:  # noqa: BLE001 - timing is best effort
            return None, None
        st = t.get("startTime")
        end = t.get("responseEnd")
        if not st or st <= 0:
            return None, None
        return st, (st + end) if end is not None and end >= 0 else None


class NetLog:
    """Collects every request of a page with monotonic (Python) and epoch (browser) timestamps."""

    def __init__(self, page: Any) -> None:
        self.recs: list[Rec] = []
        self._by_req: dict[int, Rec] = {}
        page.on("request", self._on_request)
        page.on("requestfinished", self._on_finished)
        page.on("requestfailed", self._on_failed)
        page.on("response", self._on_response)

    def _on_request(self, r: Any) -> None:
        u = urlsplit(r.url)
        rec = Rec(r, r.url, u.path + (("?" + u.query) if u.query else ""), r.method, r.resource_type, u.netloc,
                  time.monotonic())
        self.recs.append(rec)
        self._by_req[id(r)] = rec

    def _on_response(self, resp: Any) -> None:
        rec = self._by_req.get(id(resp.request))
        if rec:
            rec.status = resp.status

    def _on_finished(self, r: Any) -> None:
        rec = self._by_req.get(id(r))
        if rec:
            rec.mono_end = time.monotonic()

    def _on_failed(self, r: Any) -> None:
        rec = self._by_req.get(id(r))
        if rec:
            rec.mono_end = time.monotonic()
            rec.failed = (r.failure or "failed")[:120]

    def since(self, mono: float) -> list[Rec]:
        return [r for r in self.recs if r.mono_start >= mono]


def wait_network_idle(page: Any, net: NetLog, start_mono: float, idle_ms: int, timeout_s: float,
                      ignore_paths: set[str], extra_ready: Any = None) -> tuple[bool, float]:
    """Pump the event loop until no relevant request started after `start_mono` is in flight for `idle_ms`.

    Returns (settled, waited_s). Streams and the chrome's background pollers (`ignore_paths`) do not count.
    `extra_ready()` (optional) must also be true before idle is accepted.
    """
    deadline = start_mono + timeout_s
    while True:
        now = time.monotonic()
        rel = [r for r in net.since(start_mono) if not r.stream and r.path.split("?")[0] not in ignore_paths]
        inflight = [r for r in rel if r.mono_end is None]
        last = max([start_mono] + [r.mono_start for r in rel] + [r.mono_end for r in rel if r.mono_end])
        if not inflight and (now - last) * 1000 >= idle_ms and (extra_ready is None or extra_ready()):
            return True, now - start_mono
        if now > deadline:
            return False, now - start_mono
        page.wait_for_timeout(25)


# ── measurements ────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class ColdSample:
    browser: str
    run: int
    ttfb_ms: float | None
    fcp_ms: float | None
    dcl_ms: float | None
    load_ms: float | None
    ready_ms: float | None
    settled: bool
    requests: int
    js_files: int
    js_wire_kb: float
    js_decoded_kb: float
    js_gz_kb: float
    css_wire_kb: float
    css_decoded_kb: float
    font_requests: int
    font_offorigin: int
    heap_used_mb: float | None
    longtask_ms: float | None
    lag_ms: float
    idle_window_s: float = 0.0
    idle_requests: int | None = None
    idle_js_requests: int | None = None
    idle_js_kb: float | None = None
    idle_lag_ms: float | None = None
    idle_longtask_ms: float | None = None
    failed: list[str] = field(default_factory=list)


@dataclass
class TabSample:
    browser: str
    run: int
    tab: str
    code: str
    switch_ms: float | None
    ready_ms: float | None
    net_ms: float | None
    settled: bool
    requests: int
    api_requests: int
    chunk_requests: int
    chunk_kb: float
    dominant: str | None
    dominant_ms: float | None
    lag_ms: float
    longtask_ms: float | None
    #: hosts other than the terminal's own origin that this switch talked to (fonts, CDNs, embeds)
    offorigin_hosts: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    waterfall: list[dict[str, Any]] = field(default_factory=list)


def _kb(n: float) -> float:
    return round(n / 1024, 1)


def _body_sizes(rec: Rec) -> tuple[int, int, int]:
    """(wire, decoded, gzip-equivalent) bytes of a finished response; zeros when unavailable."""
    try:
        resp = rec.req.response()
    except Exception:  # noqa: BLE001
        return 0, 0, 0
    if resp is None:
        return 0, 0, 0
    try:
        body = resp.body()
    except Exception:  # noqa: BLE001
        body = b""
    wire = 0
    try:
        wire = int(rec.req.sizes().get("responseBodySize") or 0)
    except Exception:  # noqa: BLE001
        wire = 0
    if wire <= 0:
        try:
            wire = int(resp.headers.get("content-length") or 0) or len(body)
        except Exception:  # noqa: BLE001
            wire = len(body)
    gz = len(gzip.compress(body, compresslevel=6)) if body else 0
    return wire, len(body), gz


def install_write_guard(context: Any, blocked: list[str]) -> None:
    """Abort every non-GET/HEAD /api request: the live stack is read-only for this tool (PLAN §2)."""

    def handler(route: Any) -> None:
        req = route.request
        if req.method not in ("GET", "HEAD", "OPTIONS"):
            blocked.append(f"{req.method} {urlsplit(req.url).path}")
            route.abort("blockedbyclient")
        else:
            route.continue_()

    context.route(re.compile(r".*/api/.*"), handler)


def app_ready_js() -> str:
    return (f"() => !!document.querySelector('header') && !document.body.innerText.includes({json.dumps(CONNECTING_TEXT)})"
            f" && !document.querySelector({json.dumps(SKELETON_SELECTOR)})")


def sample_background_paths(page: Any, net: NetLog, seconds: float) -> set[str]:
    """Request paths (no query) seen while the page sits idle for `seconds`: the chrome's pollers."""
    t = time.monotonic()
    page.wait_for_timeout(int(seconds * 1000))
    return {r.path.split("?")[0] for r in net.since(t) if not r.stream}


def lag_total(page: Any, since_perf_ms: float) -> tuple[float, float | None]:
    """(event-loop lag ms, long-task ms or None) recorded after `since_perf_ms` (page performance.now clock)."""
    lags, lts = page.evaluate("() => [window.__sdPerf.lags, window.__sdPerf.longtasks]")
    lag = sum(d for s, d in lags if s >= since_perf_ms)
    lt = None if lts is None else float(sum(d for s, d in lts if s >= since_perf_ms))
    return float(lag), lt


def _qa_probe() -> Any:
    """scripts/desktop_qa/probe (the QA harness's browser-context helpers), made importable from this script."""
    scripts = str(REPO / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from desktop_qa import probe

    return probe


def new_perf_context(browser: Any, viewport: dict[str, int], prefs_mode: str = "readonly") -> Any:
    """A fresh context with the prefs-sync mode pinned (probe.new_qa_context) and the perf instrumentation."""
    context = _qa_probe().new_qa_context(browser, prefs_mode=prefs_mode, viewport=viewport, ignore_https_errors=False)
    context.add_init_script(INIT_SCRIPT)
    return context


def measure_cold(browser_name: str, browser: Any, base: str, run: int, idle_ms: int, viewport: dict[str, int],
                 allow_writes: bool, blocked: list[str], post_load_wait_s: float = 0.0,
                 prefs_mode: str = "readonly") -> tuple[ColdSample, Any, Any, NetLog]:
    """Fresh context, cold load of /, wait for app-ready and network idle, then the optional idle window.

    Returns the sample and the live page (the tab sweep continues on it)."""
    context = new_perf_context(browser, viewport, prefs_mode)
    if not allow_writes:
        install_write_guard(context, blocked)
    page = context.new_page()
    net = NetLog(page)
    origin = urlsplit(base).netloc
    t = time.monotonic()
    page.goto(base.rstrip("/") + "/", wait_until="load", timeout=60_000)
    ready_ms = None
    try:
        page.wait_for_function(app_ready_js(), timeout=30_000, polling=50)
        ready_ms = page.evaluate("() => performance.now()")
    except Exception:  # noqa: BLE001 - app never became ready inside the timeout
        ready_ms = None
    settled, _ = wait_network_idle(page, net, t, idle_ms, 30.0, set())
    tm = page.evaluate(TIMING_JS)
    js = [r for r in net.recs if r.rtype == "script" or r.path.split("?")[0].endswith(".js")]
    css = [r for r in net.recs if r.rtype == "stylesheet" or r.path.split("?")[0].endswith(".css")]
    fonts = [r for r in net.recs if r.rtype == "font" or re.search(r"\.(woff2?|ttf|otf)(\?|$)", r.url)]
    jw = jd = jg = cw = cd = 0
    for r in js:
        w, d, g = _body_sizes(r)
        jw, jd, jg = jw + w, jd + d, jg + g
    for r in css:
        w, d, _ = _body_sizes(r)
        cw, cd = cw + w, cd + d
    heap = None
    if browser_name == "chromium":
        try:
            cdp = context.new_cdp_session(page)
            cdp.send("Performance.enable")
            metrics = {m["name"]: m["value"] for m in cdp.send("Performance.getMetrics")["metrics"]}
            heap = round(metrics.get("JSHeapUsedSize", 0) / 2**20, 1)
        except Exception:  # noqa: BLE001
            heap = (tm.get("mem") or {}).get("used")
            heap = round(heap / 2**20, 1) if heap else None
    lag, lt = lag_total(page, 0)
    failed = [f"{r.method} {r.path} {r.failed}" for r in net.recs if r.failed and not r.stream]
    idle: dict[str, Any] = {}
    if post_load_wait_s > 0:
        perf0 = page.evaluate("() => performance.now()")
        mono0 = time.monotonic()
        page.wait_for_timeout(int(post_load_wait_s * 1000))
        recs = [r for r in net.since(mono0) if not r.stream]
        js_idle = [r for r in recs if r.rtype == "script" or r.path.split("?")[0].endswith(".js")]
        il, ilt = lag_total(page, perf0)
        idle = {"idle_window_s": post_load_wait_s, "idle_requests": len(recs), "idle_js_requests": len(js_idle),
                "idle_js_kb": _kb(sum(_body_sizes(r)[0] for r in js_idle)), "idle_lag_ms": il, "idle_longtask_ms": ilt}
    s = ColdSample(
        browser=browser_name, run=run,
        ttfb_ms=_r(tm.get("ttfb")), fcp_ms=_r(tm.get("fcp")), dcl_ms=_r(tm.get("dcl")), load_ms=_r(tm.get("load")),
        ready_ms=_r(ready_ms), settled=settled, requests=len([r for r in net.recs if not r.stream]),
        js_files=len(js), js_wire_kb=_kb(jw), js_decoded_kb=_kb(jd), js_gz_kb=_kb(jg),
        css_wire_kb=_kb(cw), css_decoded_kb=_kb(cd), font_requests=len(fonts),
        font_offorigin=len([r for r in fonts if urlsplit(r.url).netloc != origin]),
        heap_used_mb=heap, longtask_ms=lt, lag_ms=lag, failed=failed, **idle,
    )
    return s, context, page, net


def _r(v: Any) -> float | None:
    return None if v is None else round(float(v), 1)


def active_tab(page: Any) -> str:
    return page.evaluate("() => new URLSearchParams(location.search).get('tab') || 'brief'")


def measure_tab(browser_name: str, page: Any, net: NetLog, p: PageDef, run: int, idle_ms: int, timeout_s: float,
                background: set[str], hop: PageDef | None = None, origin: str = "") -> TabSample:
    """Switch to `p` with the app's own GOTO event and time it (see module docstring for the 'done' rule).

    A switch to the page that is already active is not a switch (and on a fresh load the metadata <title> still
    says "SuryaDhana Terminal"), so the harness first hops to `hop` (unmeasured) in that case.
    """
    if hop is not None and active_tab(page) == p.id:
        page.evaluate("([t, evt]) => window.dispatchEvent(new CustomEvent(evt, { detail: t }))", [hop.id, GOTO_EVENT])
        wait_network_idle(page, net, time.monotonic(), idle_ms, timeout_s, background)
    perf_t0 = page.evaluate("() => performance.now()")
    mono0 = time.monotonic()
    t0 = page.evaluate(SWITCH_JS, [p.id, p.code, SKELETON_SELECTOR, GOTO_EVENT])
    t0_epoch = float(t0["t0Epoch"])

    def ready() -> bool:
        return page.evaluate("() => window.__sdPerf.switch && window.__sdPerf.switch.readyAt !== null")

    settled, _ = wait_network_idle(page, net, mono0, idle_ms, timeout_s, background, extra_ready=ready)
    ready_ms = page.evaluate("() => window.__sdPerf.switch ? window.__sdPerf.switch.readyAt : null")
    recs = [r for r in net.since(mono0)]
    rel = [r for r in recs if not r.stream and r.path.split("?")[0] not in background]
    waterfall: list[dict[str, Any]] = []
    net_end = 0.0
    dominant, dominant_ms, chunk_kb = None, None, 0.0
    for r in recs:
        st, en = r.epoch_window()
        start_ms = (st - t0_epoch) if st else (r.mono_start - mono0) * 1000
        end_ms = (en - t0_epoch) if en else ((r.mono_end - mono0) * 1000 if r.mono_end else None)
        dur = (end_ms - start_ms) if end_ms is not None else None
        bg = r.path.split("?")[0] in background
        waterfall.append({"path": r.path[:160], "host": r.host if r.host != origin else "", "type": r.rtype,
                          "method": r.method, "start": _r(start_ms),
                          "dur": _r(dur), "status": r.status, "stream": r.stream, "background": bg,
                          "failed": r.failed})
        if r in rel and end_ms is not None:
            net_end = max(net_end, end_ms)
            if r.rtype in ("xhr", "fetch") and (dominant_ms is None or (dur or 0) > dominant_ms):
                dominant, dominant_ms = r.path.split("?")[0], dur
        if r.rtype == "script" and r in rel:
            with contextlib.suppress(Exception):   # sizes() is best effort (request may be gone)
                chunk_kb += float(r.req.sizes().get("responseBodySize") or 0) / 1024
    ready_r = _r(ready_ms)
    switch = None if ready_r is None else round(max(ready_r, net_end), 1)
    lag, lt = lag_total(page, perf_t0)
    return TabSample(
        browser=browser_name, run=run, tab=p.id, code=p.code, switch_ms=switch if settled else None,
        ready_ms=ready_r, net_ms=_r(net_end), settled=settled,
        requests=len([r for r in recs if not r.stream]),
        api_requests=len([r for r in rel if "/api/" in r.path]),
        chunk_requests=len([r for r in rel if r.rtype == "script"]), chunk_kb=round(chunk_kb, 1),
        dominant=dominant, dominant_ms=_r(dominant_ms), lag_ms=lag, longtask_ms=lt,
        offorigin_hosts=sorted({r.host for r in recs if origin and r.host and r.host != origin}),
        failed=[f"{r.method} {r.path[:120]} {r.failed}" for r in rel if r.failed],
        waterfall=sorted(waterfall, key=lambda w: (w["start"] or 0)),
    )


# ── bundle analysis (no browser) ────────────────────────────────────────────────────────────────────────────

def bundle_report(export_dir: Path) -> dict[str, Any]:
    """First-load JS/CSS of index.html and the largest chunks of a static export dir, raw and gzip-6."""
    index = (export_dir / "index.html").read_text(encoding="utf-8")
    # <script noModule> (Next's legacy polyfills) is never fetched by a module-capable engine: not first-load JS
    nomodule = set(re.findall(r'<script[^>]*src="(/_next/static/[^"]+\.js)"[^>]*noModule', index, re.IGNORECASE))
    first = sorted(set(re.findall(r'(?:src|href)="(/_next/static/[^"]+\.(?:js|css))"', index)) - nomodule)

    def sz(rel: str) -> tuple[int, int]:
        b = (export_dir / rel.lstrip("/")).read_bytes()
        return len(b), len(gzip.compress(b, compresslevel=6))

    first_rows: list[dict[str, Any]] = [{"file": f, "raw_kb": _kb(sz(f)[0]), "gz_kb": _kb(sz(f)[1])} for f in first]
    chunks: list[dict[str, Any]] = []
    for f in (export_dir / "_next" / "static").rglob("*"):
        if f.suffix in (".js", ".css") and f.is_file():
            raw, gz = sz("/" + str(f.relative_to(export_dir)))
            chunks.append({"file": "/" + str(f.relative_to(export_dir)), "raw_kb": _kb(raw), "gz_kb": _kb(gz)})
    chunks.sort(key=lambda c: -c["raw_kb"])
    js_first = [r for r in first_rows if r["file"].endswith(".js")]
    return {
        "dir": str(export_dir),
        "first_load_js_raw_kb": round(sum(r["raw_kb"] for r in js_first), 1),
        "first_load_js_gz_kb": round(sum(r["gz_kb"] for r in js_first), 1),
        "first_load_css_gz_kb": round(sum(r["gz_kb"] for r in first_rows if r["file"].endswith(".css")), 1),
        "first_load": first_rows,
        "nomodule_excluded": sorted(nomodule),
        "total_js_raw_kb": round(sum(c["raw_kb"] for c in chunks if c["file"].endswith(".js")), 1),
        "total_js_gz_kb": round(sum(c["gz_kb"] for c in chunks if c["file"].endswith(".js")), 1),
        "js_files": len([c for c in chunks if c["file"].endswith(".js")]),
        "largest": chunks[:15],
    }


# ── statistics + summary ───────────────────────────────────────────────────────────────────────────────────

def pct(values: Iterable[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100); None for an empty list."""
    v = sorted(x for x in values if x is not None)
    if not v:
        return None
    k = max(0, min(len(v) - 1, round(q / 100 * len(v) + 0.5) - 1))
    return round(v[k], 1)


def summarize(results: list[dict[str, Any]]) -> str:
    """Markdown tables (cold load, per-browser tab-switch distribution, top-10 slowest tabs) for raw results."""
    out: list[str] = []
    for res in results:
        meta = res["meta"]
        out.append(f"### {meta['label']} · {meta['base']} · runs={meta['runs']} · {meta['started']}\n")
        if res.get("bundle"):
            b = res["bundle"]
            out.append(f"Bundle: first-load JS **{b['first_load_js_gz_kb']} kB gz** ({b['first_load_js_raw_kb']} kB raw, "
                       f"{len([r for r in b['first_load'] if r['file'].endswith('.js')])} files) · all JS {b['total_js_gz_kb']} kB gz "
                       f"in {b['js_files']} files\n")
        cold = res.get("cold", [])
        if cold:
            out.append("| engine | TTFB | FCP | DCL | load | app ready | requests | JS wire / decoded / gz kB | CSS kB | fonts (off-origin) | heap MB |")
            out.append("|---|---|---|---|---|---|---|---|---|---|---|")
            for br in sorted({c["browser"] for c in cold}):
                cs = [c for c in cold if c["browser"] == br]

                def med(k: str, cs: list[dict[str, Any]] = cs) -> float | None:
                    return pct([c[k] for c in cs if c[k] is not None], 50)

                out.append(f"| {br} | {med('ttfb_ms')} | {med('fcp_ms')} | {med('dcl_ms')} | {med('load_ms')} | {med('ready_ms')} | "
                           f"{med('requests')} | {med('js_wire_kb')} / {med('js_decoded_kb')} / {med('js_gz_kb')} | "
                           f"{med('css_decoded_kb')} | {med('font_requests')} ({med('font_offorigin')}) | {med('heap_used_mb')} |")
            out.append("")
        tabs = res.get("tabs", [])
        if tabs:
            out.append("| engine | samples | settled | switch p50 | p95 | max | ready p95 | over 400 ms (tabs) |")
            out.append("|---|---|---|---|---|---|---|---|")
            for br in sorted({t["browser"] for t in tabs}):
                ts = [t for t in tabs if t["browser"] == br]
                sw = [t["switch_ms"] for t in ts if t["switch_ms"] is not None]
                per_tab: dict[str, list[float | None]] = {}
                for t in ts:
                    per_tab.setdefault(t["tab"], []).append(t["switch_ms"])
                over = sorted(k for k, v in per_tab.items() if (pct([x for x in v if x is not None], 95) or 1e9) > BUDGETS["tab_switch_p95_ms"])
                out.append(f"| {br} | {len(ts)} | {len(sw)} | {pct(sw, 50)} | {pct(sw, 95)} | {max(sw) if sw else None} | "
                           f"{pct([t['ready_ms'] for t in ts if t['ready_ms'] is not None], 95)} | {len(over)} |")
            out.append("")
            for br in sorted({t["browser"] for t in tabs}):
                ts = [t for t in tabs if t["browser"] == br]
                agg: dict[str, dict[str, Any]] = {}
                for t in ts:
                    a = agg.setdefault(t["tab"], {"code": t["code"], "sw": [], "ready": [], "dom": {}, "api": [], "unsettled": 0})
                    if t["switch_ms"] is None:
                        a["unsettled"] += 1
                    else:
                        a["sw"].append(t["switch_ms"])
                    if t["ready_ms"] is not None:
                        a["ready"].append(t["ready_ms"])
                    a["api"].append(t["api_requests"])
                    if t["dominant"]:
                        a["dom"].setdefault(t["dominant"], []).append(t["dominant_ms"] or 0)
                rows = sorted(agg.items(), key=lambda kv: -(pct(kv[1]["sw"], 95) or 1e9))[:10]
                out.append(f"Top 10 slowest tabs · {br}\n")
                out.append("| tab | code | switch p50 | p95 | ready p95 | API calls | dominant call (median ms) | unsettled |")
                out.append("|---|---|---|---|---|---|---|---|")
                for tab, a in rows:
                    dom = max(a["dom"].items(), key=lambda kv: statistics.median(kv[1]))[0] if a["dom"] else "—"
                    dms = round(statistics.median(a["dom"][dom]), 1) if a["dom"] else None
                    out.append(f"| {tab} | {a['code']} | {pct(a['sw'], 50)} | {pct(a['sw'], 95)} | {pct(a['ready'], 95)} | "
                               f"{statistics.median(a['api'])} | `{dom}` ({dms}) | {a['unsettled']} |")
                out.append("")
        hosts = sorted({(t["tab"], h) for t in tabs for h in (t.get("offorigin_hosts") or [])})
        if hosts:
            out.append(f"Off-origin hosts contacted during tab switches: {hosts}\n")
        if res.get("blocked_writes"):
            out.append(f"Blocked non-GET /api requests: {sorted(set(res['blocked_writes']))}\n")
    return "\n".join(out)


# ── driver ─────────────────────────────────────────────────────────────────────────────────────────────────

def run_engine(pw: Any, name: str, args: argparse.Namespace, pages: list[PageDef], res: dict[str, Any]) -> None:
    launcher = getattr(pw, name)
    origin = urlsplit(args.base).netloc
    browser = launcher.launch(headless=not args.headed)
    try:
        for run in range(1, args.runs + 1):
            cold, context, page, net = measure_cold(name, browser, args.base, run, args.idle_ms,
                                                    {"width": args.width, "height": args.height}, args.allow_writes,
                                                    res["blocked_writes"], args.post_load_wait, args.prefs_mode)
            res["cold"].append(asdict(cold))
            print(f"[{name} run {run}] cold: fcp={cold.fcp_ms} ready={cold.ready_ms} js_gz={cold.js_gz_kb}kB "
                  f"req={cold.requests} fonts={cold.font_requests}/{cold.font_offorigin} off-origin"
                  + (f" idle({cold.idle_window_s}s): req={cold.idle_requests} js={cold.idle_js_requests}/{cold.idle_js_kb}kB "
                     f"lag={cold.idle_lag_ms} lt={cold.idle_longtask_ms}" if cold.idle_window_s else ""), flush=True)
            if pages:
                all_pages = {q.id: q for q in load_pages()}
                hop, hop_alt = all_pages.get("research"), all_pages.get("eco")
                if not res["background"].get(name):
                    # chrome pollers = paths seen idle on two different pages (intersection drops page-specific calls)
                    a = sample_background_paths(page, net, args.bg_seconds)
                    first = pages[0] if pages[0].id != "brief" else (pages[1] if len(pages) > 1 else pages[0])
                    measure_tab(name, page, net, first, 0, args.idle_ms, args.tab_timeout, set(), hop=hop, origin=origin)
                    b = sample_background_paths(page, net, args.bg_seconds)
                    res["background"][name] = sorted(a & b)
                    print(f"[{name}] background pollers: {res['background'][name]}", flush=True)
                bg = set(res["background"][name])
                order = pages if run % 2 else list(reversed(pages))   # alternate order: no position bias
                for p in order:
                    s = measure_tab(name, page, net, p, run, args.idle_ms, args.tab_timeout, bg,
                                    hop=hop if p.id != "research" else hop_alt, origin=origin)
                    res["tabs"].append(asdict(s))
                    flag = "" if s.settled else "  (NOT SETTLED)"
                    print(f"[{name} run {run}] {p.code:5s} switch={s.switch_ms} ready={s.ready_ms} net={s.net_ms} "
                          f"api={s.api_requests} dom={s.dominant}({s.dominant_ms}){flag}", flush=True)
                if name == "chromium":
                    try:
                        cdp = context.new_cdp_session(page)
                        cdp.send("HeapProfiler.collectGarbage")
                        cdp.send("Performance.enable")
                        m = {x["name"]: x["value"] for x in cdp.send("Performance.getMetrics")["metrics"]}
                        res["heap_after_sweep"].append({"browser": name, "run": run,
                                                        "js_heap_used_mb": round(m.get("JSHeapUsedSize", 0) / 2**20, 1),
                                                        "nodes": m.get("Nodes"), "listeners": m.get("JSEventListeners")})
                    except Exception as e:  # noqa: BLE001
                        res["heap_after_sweep"].append({"browser": name, "run": run, "error": str(e)[:120]})
            context.close()
    finally:
        browser.close()


def write_csv(path: Path, res: dict[str, Any]) -> None:
    cols = ["kind", "browser", "run", "tab", "code", "switch_ms", "ready_ms", "net_ms", "settled", "requests",
            "api_requests", "chunk_requests", "chunk_kb", "dominant", "dominant_ms", "ttfb_ms", "fcp_ms", "dcl_ms",
            "load_ms", "js_files", "js_wire_kb", "js_decoded_kb", "js_gz_kb", "css_decoded_kb", "font_requests",
            "font_offorigin", "heap_used_mb", "lag_ms", "longtask_ms", "idle_window_s", "idle_requests",
            "idle_js_requests", "idle_js_kb", "idle_lag_ms", "idle_longtask_ms", "offorigin_hosts", "failed"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for c in res["cold"]:
            w.writerow({**c, "kind": "cold", "failed": " | ".join(c["failed"])})
        for t in res["tabs"]:
            w.writerow({**t, "kind": "tab", "failed": " | ".join(t["failed"]),
                        "offorigin_hosts": " ".join(t.get("offorigin_hosts") or [])})


_CSV_INT = {"run", "requests", "api_requests", "chunk_requests", "js_files", "font_requests", "font_offorigin",
            "idle_requests", "idle_js_requests"}
_CSV_STR = {"kind", "browser", "tab", "code", "dominant", "failed", "offorigin_hosts"}


def load_results(path: Path) -> dict[str, Any]:
    """Raw results from a perf_<label>.json, or rebuilt from a perf_<label>.csv (no waterfalls/heap sweep/bundle)."""
    if path.suffix != ".csv":
        return json.loads(path.read_text(encoding="utf-8"))
    res: dict[str, Any] = {"meta": {"label": path.stem.removeprefix("perf_"), "base": "(from CSV)", "runs": 0,
                                    "started": time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))},
                           "cold": [], "tabs": [], "background": {}, "heap_after_sweep": [], "blocked_writes": [],
                           "bundle": None}
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            rec: dict[str, Any] = {}
            for k, v in row.items():
                if k in _CSV_STR:
                    rec[k] = v or None
                elif k == "settled":
                    rec[k] = v == "True"
                elif v in ("", None):
                    rec[k] = None
                else:
                    rec[k] = int(float(v)) if k in _CSV_INT else float(v)
            rec["failed"] = [x for x in (row.get("failed") or "").split(" | ") if x]
            rec["offorigin_hosts"] = (row.get("offorigin_hosts") or "").split()
            (res["cold"] if row["kind"] == "cold" else res["tabs"]).append(rec)
    res["meta"]["runs"] = max([c["run"] for c in res["cold"]] or [0])
    return res


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://127.0.0.1:3000",
                    help="terminal origin (default :3000, the pre-switchover baseline; the live terminal is "
                         "http://127.0.0.1:8010)")
    ap.add_argument("--browser", choices=["chromium", "webkit", "both"], default="both")
    ap.add_argument("--tabs", default="all", help="'all', 'none' (cold load only) or comma-separated tab ids")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--idle-ms", type=int, default=500)
    ap.add_argument("--tab-timeout", type=float, default=20.0, help="seconds before a tab counts as not settled")
    ap.add_argument("--bg-seconds", type=float, default=7.0, help="idle sampling window for chrome pollers")
    ap.add_argument("--post-load-wait", type=float, default=0.0,
                    help="seconds the page sits idle after the cold load before the tab sweep (records idle activity)")
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=1000)
    ap.add_argument("--label", default="run")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT, help="CSV/summary destination")
    ap.add_argument("--json-dir", type=Path, default=None, help="raw JSON destination (default: --out-dir)")
    ap.add_argument("--bundle-dir", type=Path, default=None, help="static export dir to analyse (index.html + _next)")
    ap.add_argument("--allow-writes", action="store_true", help="do NOT abort non-GET /api requests (never on live)")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--write-summary", action="store_true")
    ap.add_argument("--summarize", nargs="+", type=Path, default=None,
                    help="print the summary of raw JSON (or CSV) result files and exit")
    ap.add_argument("--prefs-mode", choices=_qa_probe().PREFS_MODES, default="readonly",
                    help="the UI's settings-sync mode in every context (default readonly: never writes the "
                         "owner's live /api/prefs); 'sync' only against a scratch server")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)

    if args.summarize:
        print(summarize([load_results(p) for p in args.summarize]))
        return 0

    all_pages = load_pages()
    if args.tabs == "all":
        pages = all_pages
    elif args.tabs == "none":
        pages = []
    else:
        want = [t.strip() for t in args.tabs.split(",") if t.strip()]
        known = {p.id: p for p in all_pages}
        bad = [t for t in want if t not in known]
        if bad:
            ap.error(f"unknown tab ids: {bad}")
        pages = [known[t] for t in want]

    res: dict[str, Any] = {
        "meta": {"label": args.label, "base": args.base, "runs": args.runs, "idle_ms": args.idle_ms,
                 "viewport": [args.width, args.height], "started": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                 "post_load_wait_s": args.post_load_wait, "prefs_mode": args.prefs_mode,
                 "pages": len(pages), "budgets": BUDGETS},
        "cold": [], "tabs": [], "background": {}, "heap_after_sweep": [], "blocked_writes": [], "bundle": None,
    }
    if args.bundle_dir:
        res["bundle"] = bundle_report(args.bundle_dir)
    engines = ["chromium", "webkit"] if args.browser == "both" else [args.browser]
    if args.runs > 0 and (pages or args.tabs == "none"):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            for name in engines:   # strictly one engine at a time: modest load on the live ui-api
                run_engine(pw, name, args, pages, res)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_dir = args.json_dir or args.out_dir
    json_dir.mkdir(parents=True, exist_ok=True)
    (json_dir / f"perf_{args.label}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if res["cold"] or res["tabs"]:
        write_csv(args.out_dir / f"perf_{args.label}.csv", res)
    summary = summarize([res])
    if args.write_summary:
        (args.out_dir / f"perf_{args.label}_summary.md").write_text(summary + "\n", encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
