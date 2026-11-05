"""One-tab browser probe shared by ``scripts/ui_audit.py`` and ``scripts/desktop_qa/parity.py``.

A ``TabProbe`` attaches to one Playwright page and tags every event with the *epoch* (the tab being probed)
at the time it started, so a stream that is torn down when the harness navigates away is attributed to the
tab that opened it and recognised as navigation-caused (see ``netpolicy``). After each tab the probe goes to
``about:blank`` (``leave``), which ends that tab's polling before the next one loads (no cross-talk, and
the live ui-api sees at most one page's traffic at a time).

Per tab it records: timing (navigation, content-ready, network-idle, Navigation Timing / FCP), console
errors and warnings, page errors, crashes, every request (method, URL, status or failure, epoch), WebSockets,
and a structural fingerprint of the rendered page (page code, panel titles, headings, tables, charts, error
boxes) with live numbers masked.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .netpolicy import (
    APP_ERROR_TEXT,
    IGNORE_CONSOLE,
    RESOURCE_LOAD_CONSOLE,
    classify_request_failure,
    endpoint_key,
    expected_delta,
    is_platform_seam,
    is_stream_path,
    normalize_text,
    origin_of,
    status_class,
)

ENGINES = ("chromium", "webkit")

# The page is "content-ready" when the per-tab code-split chunk has replaced the TabSkeleton and the page has
# rendered its own PageHeader whose amber code chip equals the page's function code (all 42 pages render one;
# ui/components/terminal PageHeader = div.t-fade-up > span:first-child). document.title is NOT used: on the
# 15 Oct prod build it stays "SuryaDhana Terminal" (Next metadata re-asserts it).
READY_JS = """(code) => {
  if (document.readyState === 'loading') return false;
  if (document.querySelector('[aria-busy="true"][aria-label="Loading page"]')) return false;
  if (!code) return true;
  return [...document.querySelectorAll('div.t-fade-up > span:first-child')]
    .some(s => (s.textContent || '').trim() === code);
}"""
SKELETON_JS = """() => !!document.querySelector('[aria-busy="true"][aria-label="Loading page"]')"""

NAV_TIMING_JS = """() => {
  const n = performance.getEntriesByType('navigation')[0];
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  const res = performance.getEntriesByType('resource');
  const js = res.filter(r => r.initiatorType === 'script' || /\\.js(\\?|$)/.test(r.name));
  const r1 = x => (x == null ? null : Math.round(x));
  return n ? { ttfb_ms: r1(n.responseStart), dcl_ms: r1(n.domContentLoadedEventEnd), load_ms: r1(n.loadEventEnd),
               fcp_ms: fcp ? r1(fcp.startTime) : null, resources: res.length, js_files: js.length,
               js_transfer_kb: r1(js.reduce((a, r) => a + (r.transferSize || 0), 0) / 1024) } : null;
}"""

# Structural fingerprint: what the page is made of, not the live values in it. Texts are normalised in
# Python (numbers masked); here we only collect them.
FINGERPRINT_JS = """() => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  const vis = el => { const r = el.getBoundingClientRect(); if (r.width <= 0 || r.height <= 0) return false;
                      const cs = getComputedStyle(el); return cs.visibility !== 'hidden' && cs.display !== 'none'; };
  const headers = [...document.querySelectorAll('div.t-fade-up')].filter(d => d.children.length >= 2
      && d.children[0].tagName === 'SPAN' && /^[A-Z0-9]{2,6}$/.test(norm(d.children[0].textContent)));
  const pageHeaders = headers.filter(vis).map(d => norm(d.children[0].textContent) + ' ' + norm(d.children[1].textContent));
  const panels = [...document.querySelectorAll('section > header')].filter(vis).map(h =>
      [...h.querySelectorAll(':scope > span')].map(s => norm(s.textContent)).find(Boolean) || '');
  const headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].filter(vis).map(h => norm(h.textContent));
  const tables = [...document.querySelectorAll('table')].filter(vis);
  const tableHeaders = tables.map(t => [...t.querySelectorAll('thead th')].map(th => norm(th.textContent)).join(' | '));
  const canvases = [...document.querySelectorAll('canvas')].filter(vis).length;
  const recharts = [...document.querySelectorAll('.recharts-wrapper')].filter(vis).length;
  const iframes = [...document.querySelectorAll('iframe')].filter(vis).map(f => { try { return new URL(f.src, location.href).host } catch { return '' } });
  const errorBoxes = [...document.querySelectorAll('div')].filter(d => d.firstElementChild
      && d.firstElementChild.tagName === 'SPAN' && (d.firstElementChild.textContent || '').startsWith('▲')
      && getComputedStyle(d).backgroundColor.replace(/\\s/g, '') === 'rgba(255,77,94,0.07)' && vis(d)).map(d => norm(d.textContent));
  const skeleton = !!document.querySelector('[aria-busy="true"][aria-label="Loading page"]');
  const loading = [...document.querySelectorAll('.t-pulse')].filter(vis).length;
  return { title: document.title, page_headers: pageHeaders, panels, headings, tables: tables.length,
           table_headers: tableHeaders, canvas: canvases, recharts, iframes, error_boxes: errorBoxes,
           skeleton, loading_bars: loading, body_text_len: (document.body && document.body.innerText || '').length };
}"""


# The UI's settings sync (ui/lib/prefs/sync.ts) reads its mode from localStorage on every page load. A fresh
# audit context against the LIVE ui-api would otherwise upload its defaults and selections into the owner's
# real preferences (data/ui_prefs.sqlite). 'readonly' hydrates from the server but never writes; 'off' skips
# sync entirely; 'sync' leaves the page alone (use it only against a scratch server).
PREFS_MODES = ("readonly", "off", "sync")
PREFS_MODE_KEY = "suryadhana.prefs.mode"


def prefs_mode_script(mode: str) -> str | None:
    """Init script pinning the UI's prefs-sync mode before any page script runs; None for 'sync'."""
    if mode not in PREFS_MODES:
        raise ValueError(f"unknown prefs mode {mode!r} (expected one of {PREFS_MODES})")
    if mode == "sync":
        return None
    return f"try {{ window.localStorage.setItem({PREFS_MODE_KEY!r}, {mode!r}) }} catch (e) {{}}"


ANY_URL = re.compile(r".*")


def mock_websockets(ctx: Any, seen: list[str] | None = None) -> None:
    """Mock every WebSocket the context's pages open: the handler never calls ``connect_to_server``, so the page
    sees an open, silent socket and nothing reaches a server (0 live monitor sockets, the QA rule since the 25 Oct
    14:40 ui-api wedge). Each mocked URL is appended to ``seen`` when given."""
    def handler(ws: Any) -> None:
        if seen is not None:
            seen.append(ws.url)

    ctx.route_web_socket(ANY_URL, handler)


def new_qa_context(browser: Any, *, prefs_mode: str = "readonly", live_websockets: bool = False,
                   ws_mocked: list[str] | None = None, **kwargs: Any) -> Any:
    """browser.new_context(**kwargs) with the prefs-mode init script installed (see PREFS_MODES) and every WebSocket
    mocked (R-OPS-09: parity, ui_audit, e2e_multiwin and ui_perf used to open live monitor sockets). Opt out with
    ``live_websockets=True`` (only against a scratch backend); ``ws_mocked`` collects the mocked URLs."""
    ctx = browser.new_context(**kwargs)
    script = prefs_mode_script(prefs_mode)
    if script:
        ctx.add_init_script(script)
    if not live_websockets:
        mock_websockets(ctx, ws_mocked)
    return ctx


def launch_browser(pw: Any, engine: str, *, chromium_channel: str | None = "chrome", headless: bool = True) -> Any:
    """Launch Chromium (system Chrome channel by default, like the original audit; bundled fallback) or WebKit."""
    if engine == "chromium":
        if chromium_channel:
            try:
                return pw.chromium.launch(channel=chromium_channel, headless=headless)
            except Exception:  # noqa: BLE001, S110 - channel not installed → Playwright's bundled Chromium
                pass
        return pw.chromium.launch(headless=headless)
    if engine == "webkit":
        return pw.webkit.launch(headless=headless)
    raise ValueError(f"unknown engine {engine!r} (expected one of {ENGINES})")


@dataclass
class _Req:
    epoch: int
    method: str
    url: str
    resource_type: str
    t_start: float
    status: int | None = None
    t_response: float | None = None   # when the response headers arrived
    failure: str | None = None
    left_tab: bool = False
    done: bool = False


@dataclass
class _Ws:
    epoch: int
    url: str
    errors: list[str] = field(default_factory=list)
    frames_received: int = 0
    frames_sent: int = 0
    closed: bool = False


class TabProbe:
    """Collects page events across tabs, attributing each to the tab (epoch) that caused it."""

    def __init__(self, page: Any, base: str) -> None:
        self.page = page
        self.base = base.rstrip("/")
        self.base_origin = origin_of(self.base)
        self.active: int | None = None   # epoch of the tab currently shown (None between tabs)
        self.last = 0                    # most recent epoch (console events in the gap belong to it)
        self.reqs: dict[Any, _Req] = {}
        self.console: list[tuple[int, str, str, str]] = []   # (epoch, type, text, source url)
        self.page_errors: list[tuple[int, str]] = []
        self.crashes: list[int] = []
        self.ws: list[_Ws] = []
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_failed)
        page.on("requestfinished", self._on_finished)
        page.on("console", self._on_console)
        page.on("pageerror", lambda e: self.page_errors.append((self._epoch(), str(e))))
        page.on("crash", lambda *_: self.crashes.append(self._epoch()))
        page.on("websocket", self._on_ws)

    # ── event handlers ────────────────────────────────────────────────────────────────────────────
    def _epoch(self) -> int:
        return self.active if self.active is not None else self.last

    def _on_request(self, r: Any) -> None:
        if r.url.startswith(("about:", "data:", "blob:")):
            return
        self.reqs[r] = _Req(self._epoch(), r.method, r.url, r.resource_type, time.perf_counter())

    def _on_response(self, resp: Any) -> None:
        rec = self.reqs.get(resp.request)
        if rec is not None:
            rec.status = resp.status
            rec.t_response = time.perf_counter()

    def _on_finished(self, r: Any) -> None:
        rec = self.reqs.get(r)
        if rec is not None:
            rec.done = True

    def _on_failed(self, r: Any) -> None:
        rec = self.reqs.get(r)
        if rec is None:
            return
        rec.failure = r.failure or "unknown failure"
        rec.left_tab = self.active != rec.epoch
        rec.done = True

    def _on_console(self, m: Any) -> None:
        if m.type in ("error", "warning") and not IGNORE_CONSOLE.search(m.text or ""):
            try:   # for "Failed to load resource" both engines report the failed resource's URL here
                url = str((m.location or {}).get("url") or "")
            except Exception:  # noqa: BLE001 - a console message without a usable location
                url = ""
            self.console.append((self._epoch(), m.type, m.text or "", url))

    def _on_ws(self, ws: Any) -> None:
        rec = _Ws(self._epoch(), ws.url)
        self.ws.append(rec)
        ws.on("socketerror", lambda err: rec.errors.append(str(err)))
        ws.on("framereceived", lambda _p: setattr(rec, "frames_received", rec.frames_received + 1))
        ws.on("framesent", lambda _p: setattr(rec, "frames_sent", rec.frames_sent + 1))
        ws.on("close", lambda _w: setattr(rec, "closed", True))

    # ── driving ───────────────────────────────────────────────────────────────────────────────────
    def begin(self) -> int:
        self.last += 1
        self.active = self.last
        return self.active

    def leave(self, flush_ms: int = 250) -> None:
        """Navigate away (about:blank) so the tab's streams/polls end and late events are attributed."""
        self.active = None
        try:
            self.page.goto("about:blank", wait_until="load", timeout=15_000)
            self.page.wait_for_timeout(flush_ms)
        except Exception:  # noqa: BLE001, S110 - the page may already be closed or crashed; leaving is best effort
            pass

    BODY_GRACE_S = 1.0

    def pending_api(self, epoch: int) -> list[str]:
        """First-party, non-stream requests of ``epoch`` still in flight: no response yet, or a response whose
        body is still arriving within ``BODY_GRACE_S``. A response the page never reads to the end (e.g. a
        404 HTML page behind a fetch that only looks at the status) is not waited for: the app already has
        its answer, and leaving cannot change what it saw."""
        now = time.perf_counter()
        return [r.url for r in self.reqs.values()
                if r.epoch == epoch and not r.done and origin_of(r.url) == self.base_origin
                and not is_stream_path(_path(r.url))
                and (r.t_response is None or now - r.t_response < self.BODY_GRACE_S)]

    def drain(self, epoch: int, timeout_s: float) -> list[str]:
        """Wait (≤ ``timeout_s``) for the tab's in-flight ordinary requests to finish, so leaving the tab does
        not abort them (an abort the harness causes is not an app failure). Returns what is still pending."""
        deadline = time.perf_counter() + max(0.0, timeout_s)
        pending = self.pending_api(epoch)
        while pending and time.perf_counter() < deadline:
            self.page.wait_for_timeout(100)
            pending = self.pending_api(epoch)
        return pending

    def visit(self, tab: str, *, code: str | None, nav_timeout_s: float = 180, ready_timeout_s: float = 30,
              idle_timeout_s: float = 21, dwell_s: float = 6, drain_timeout_s: float = 15, fingerprint: bool = True,
              screenshot_dir: Path | None = None, full_page: bool = True, shot_prefix: str = "",
              min_total_s: float = 0.0) -> dict[str, Any]:
        """Load ``<base>/?tab=<tab>``, wait for content-ready + network-idle (capped) + dwell, collect evidence,
        drain in-flight requests, leave.

        ``min_total_s`` keeps the page open until that many seconds after navigation started, so two bases
        are observed for the same window (interval polls, e.g. a hidden 10 s poller, fire on both or neither).

        Returns the *visit* facts (timing, fingerprint, screenshots, navigation error). Events are summarised
        separately by ``summarize(epoch)`` once the tab has been left.
        """
        epoch = self.begin()
        url = f"{self.base}/?tab={tab}"
        out: dict[str, Any] = {"epoch": epoch, "tab": tab, "url": url, "error": None, "skeleton_at_end": None,
                               "pending_at_leave": [],
                               "timing": {"nav_ms": None, "ready_ms": None, "ready": False, "idle_ms": None,
                                          "total_ms": None}}
        t0 = time.perf_counter()
        ms = lambda: round((time.perf_counter() - t0) * 1000)
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=int(nav_timeout_s * 1000))
            out["timing"]["nav_ms"] = ms()
            try:
                self.page.wait_for_function(READY_JS, arg=code, timeout=int(ready_timeout_s * 1000), polling=50)
                out["timing"].update(ready=True, ready_ms=ms())
            except Exception:  # noqa: BLE001, S110 - not ready in time: reported via timing.ready=False
                pass
            try:
                self.page.wait_for_load_state("networkidle", timeout=int(idle_timeout_s * 1000))
                out["timing"]["idle_ms"] = ms()
            except Exception:  # noqa: BLE001, S110 - never idle: the dwell below still runs
                pass
            if dwell_s > 0:
                self.page.wait_for_timeout(int(dwell_s * 1000))
            if min_total_s > 0 and ms() < min_total_s * 1000:
                self.page.wait_for_timeout(int(min_total_s * 1000 - ms()))
            out["timing"]["total_ms"] = ms()
            out["skeleton_at_end"] = bool(self._eval(SKELETON_JS))
            out["nav_timing"] = self._eval(NAV_TIMING_JS)
            body = self._eval("() => (document.body && document.body.innerText || '').slice(0, 20000)") or ""
            out["app_error"] = bool(APP_ERROR_TEXT.search(body))
            if fingerprint:
                out["fingerprint"] = normalize_fingerprint(self._eval(FINGERPRINT_JS))
            if screenshot_dir is not None:
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                shot = screenshot_dir / f"{shot_prefix}{tab}.png"
                self.page.screenshot(path=str(shot), full_page=False)
                out["screenshot"] = str(shot)
                if full_page:
                    self.page.screenshot(path=str(screenshot_dir / f"{shot_prefix}{tab}-full.png"), full_page=True)
            out["pending_at_leave"] = self.drain(epoch, drain_timeout_s)
        except Exception as exc:  # noqa: BLE001 - navigation timeout, crash, closed target … (reported, not raised)
            out["error"] = f"{type(exc).__name__}: {exc}"[:500]
            out["timing"]["total_ms"] = ms()
        finally:
            self.leave()
        return out

    def _eval(self, js: str) -> Any:
        try:
            return self.page.evaluate(js)
        except Exception:  # noqa: BLE001 - a closed or navigating page: no value
            return None

    # ── summarising ───────────────────────────────────────────────────────────────────────────────
    def summarize(self, epoch: int) -> dict[str, Any]:
        """Events of one tab, classified with ``netpolicy`` (pure function of what was collected)."""
        console_errors = _dedupe(t for e, k, t, _u in self.console if e == epoch and k == "error")
        console_warnings = _dedupe(t for e, k, t, _u in self.console if e == epoch and k == "warning")
        console_detail = [{"text": t, "url": u, "seam": bool(u) and is_platform_seam(u)}
                          for t, u in dict.fromkeys((t, u) for e, k, t, u in self.console if e == epoch and k == "error")][:50]
        page_errors = _dedupe(t for e, t in self.page_errors if e == epoch)
        failed: list[dict[str, Any]] = []
        allowed: list[dict[str, Any]] = []
        third: list[dict[str, Any]] = []
        api: dict[str, dict[str, Any]] = {}
        for rec in self.reqs.values():
            if rec.epoch != epoch:
                continue
            verdict = None
            if (rec.status is not None and rec.status >= 400) or rec.failure:
                verdict = classify_request_failure(url=rec.url, base_origin=self.base_origin,
                                                   status=rec.status if rec.status and rec.status >= 400 else None,
                                                   failure_text=rec.failure, left_tab=rec.left_tab)
                item = {"method": rec.method, "url": rec.url, "status": rec.status, "failure": rec.failure,
                        "resource_type": rec.resource_type, "kind": verdict.kind, "reason": verdict.reason}
                item["seam"] = origin_of(rec.url) == self.base_origin and is_platform_seam(_path(rec.url))
                (failed if verdict.failure else third if verdict.kind.startswith("third_party") else allowed).append(item)
            if origin_of(rec.url) == self.base_origin and _path(rec.url).startswith("/api/"):
                key = endpoint_key(rec.method, rec.url)
                slot = api.setdefault(key, {"count": 0, "statuses": set(), "paths": set(), "expected": set()})
                slot["count"] += 1
                slot["expected"].add(expected_delta(rec.method, rec.url))   # None = not an expected program delta
                if rec.status is not None:
                    slot["statuses"].add(status_class(rec.status))
                elif rec.failure:
                    slot["statuses"].add(status_class(None, verdict.kind if verdict else None))
                else:
                    slot["statuses"].add("PENDING")
                if len(slot["paths"]) < 5:
                    slot["paths"].add(endpoint_key(rec.method, rec.url, template=False))
        api_out: dict[str, dict[str, Any]] = {}
        for k, v in sorted(api.items()):
            api_out[k] = {"count": v["count"], "statuses": sorted(v["statuses"]), "paths": sorted(v["paths"])}
            if len(v["expected"]) == 1 and None not in v["expected"]:   # EVERY call of this endpoint was one
                api_out[k]["expected_delta"] = next(iter(v["expected"]))
        ws_out = [{"url": w.url, "errors": w.errors, "frames_received": w.frames_received,
                   "frames_sent": w.frames_sent, "closed": w.closed} for w in self.ws if w.epoch == epoch]
        return {"console_errors": console_errors, "console_warnings": console_warnings, "page_errors": page_errors,
                "console_detail": console_detail,
                "crashed": epoch in self.crashes, "failed_requests": failed, "allowed_aborts": allowed,
                "third_party_failures": third, "api": api_out,
                "non_get_api": sorted(k for k in api_out if not k.startswith("GET ")),
                "websockets": ws_out}


def normalize_fingerprint(fp: dict[str, Any] | None) -> dict[str, Any] | None:
    """Mask live numbers in every text field of a raw fingerprint (structure stays, values go)."""
    if not fp:
        return None
    out = dict(fp)
    for k in ("title",):
        out[k] = normalize_text(fp.get(k))
    for k in ("page_headers", "panels", "headings", "table_headers", "error_boxes"):
        out[k] = [normalize_text(x) for x in fp.get(k) or []]
    return out


def failure_lines(visit: dict[str, Any], events: dict[str, Any], *, strict: bool) -> list[str]:
    """Human-readable failure list for one tab (the audit's pass/fail rule, in one place)."""
    lines: list[str] = []
    if visit.get("error"):
        lines.append(f"navigation: {visit['error']}")
    elif visit.get("skeleton_at_end"):
        lines.append("not_ready: the tab's code-split chunk never replaced the loading skeleton")
    elif not visit["timing"].get("ready"):
        lines.append("not_ready: the page's own header (code chip) did not render within the ready timeout")
    if visit.get("app_error"):
        lines.append("app_error: error overlay text on the page")
    if events.get("crashed"):
        lines.append("crash: page crashed")
    lines += [f"page_error: {t[:300]}" for t in events["page_errors"]]
    lines += [f"console_error: {t[:300]}" for t in events["console_errors"]]
    lines += [f"failed_request: {f['method']} {f['url']} → {f['reason']}" for f in events["failed_requests"]]
    for w in events["websockets"]:
        if w["errors"] and origin_of(w["url"].replace("ws", "http", 1)) == origin_of(visit["url"]):
            lines.append(f"websocket_error: {w['url']} {w['errors'][:2]}")
    if strict:
        lines += [f"console_warning: {t[:300]}" for t in events["console_warnings"]]
        lines += [f"third_party: {f['method']} {f['url']} → {f['reason']}" for f in events["third_party_failures"]]
        fp = visit.get("fingerprint") or {}
        lines += [f"error_box: {t}" for t in fp.get("error_boxes") or []]
    return lines


def non_seam_failures(failures: list[str], failed_requests: list[dict[str, Any]],
                      console_detail: list[dict[str, Any]] | None) -> list[str]:
    """``failures`` minus platform-seam requests (netpolicy.PLATFORM_SEAM_PATHS) and the generic
    "Failed to load resource" console line when every occurrence of it came from a seam URL. Used to tell
    "only the platform probes failed on this base" apart from a page failure; it never changes pass/fail."""
    seam_lines = {f"failed_request: {f['method']} {f['url']} → {f['reason']}" for f in failed_requests if f.get("seam")}
    by_text: dict[str, list[bool]] = {}
    for x in console_detail or []:
        by_text.setdefault(x["text"], []).append(bool(x.get("seam")))
    seam_only = {f"console_error: {t[:300]}" for t, flags in by_text.items()
                 if all(flags) and RESOURCE_LOAD_CONSOLE.search(t or "")}
    return [line for line in failures if line not in seam_lines and line not in seam_only]


def _dedupe(items: Any) -> list[str]:
    return list(dict.fromkeys(items))[:50]


def _path(url: str) -> str:
    from urllib.parse import urlsplit
    return urlsplit(url).path
