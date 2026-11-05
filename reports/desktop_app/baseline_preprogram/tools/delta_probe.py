"""Supplementary A/B capture of what scripts/desktop_qa/parity.py does not compare.

parity.py compares same-origin ``/api/*`` calls, console/page errors and a structural fingerprint. The desktop
program's browser-visible changes are mostly elsewhere: the boot gate, the /health and /build-info.json probes, the
self-hosted fonts instead of Google Fonts, the shell's <html> attributes, the prefs bookkeeping in localStorage and the
Tailwind rules that P11 adds. For each base and engine (one browser at a time) this loads ``/?tab=<tab>`` in a fresh
context (prefs mode pinned to 'readonly' before any page script, like every QA tool), waits for the page header, keeps
observing for ``--observe`` seconds, and records:

* every request: same-origin non-/api paths (documents, static, fonts, /health, /build-info.json), /api/prefs*, and
  third-party hosts, each with its status class;
* the boot gate: whether ``[aria-label="Starting SuryaDhana"]`` was ever in the DOM and for how long;
* first contentful paint and when the page header (the code chip) appeared;
* the FontFace set that ended up loaded (family, weight, unicode-range) and the font files fetched (from the
  network capture; Resource Timing is kept as ``font_files_rt`` but misses cross-origin font loads);
* <html> data-sd-shell / --shell-top / inline background, <body> padding-top;
* localStorage key NAMES after the visit (no values);
* the toast-stack CSS: whether the stylesheet has the rules ToastContext needs (P11).

GET-only, enforced: every context aborts any /api request that is not GET/HEAD/OPTIONS before it leaves the
browser (``install_get_only_guard``), so a tab that POSTs on load (OSTR analyze, ALFA scan, MCXG ticket) can be
probed against the live ui-api without sending it a write; the refused requests are listed per side under
``blocked_non_get``. Usage::

    python delta_probe.py --a http://127.0.0.1:8097 --b http://127.0.0.1:8010 --out <dir> [--tab brief] [--observe 15]
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import TimeoutError as PlaywrightTimeout

REPO = Path(__file__).resolve().parents[4]


SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
API_ROUTE = re.compile(r"^[a-z]+://[^/]+/api/")   # any host: the probe never writes, wherever /api lives


def install_get_only_guard(ctx: Any, blocked: list[str]) -> None:
    """Abort every /api request whose method is not GET/HEAD/OPTIONS (recorded in ``blocked``); continue the rest."""

    def handler(route: Any) -> None:
        req = route.request
        if str(req.method).upper() in SAFE_METHODS:
            route.continue_()
            return
        blocked.append(f"{req.method} {urlsplit(req.url).path}")
        route.abort("blockedbyclient")

    ctx.route(API_ROUTE, handler)


def qa_probe() -> ModuleType:
    """scripts/desktop_qa/probe.py (the harness every QA tool shares: readonly prefs context, READY_JS, launcher)."""
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    return importlib.import_module("desktop_qa.probe")

GATE_INIT = """(() => {
  const g = { seen: false, shown_at: null, gone_at: null };
  Object.defineProperty(window, '__sdGate', { value: g });
  const check = () => {
    const el = document.querySelector('[aria-label="Starting SuryaDhana"]');
    const now = performance.now();
    if (el && !g.seen) { g.seen = true; g.shown_at = now; }
    if (!el && g.seen && g.gone_at === null) g.gone_at = now;
  };
  new MutationObserver(check).observe(document, { subtree: true, childList: true });
  document.addEventListener('DOMContentLoaded', check);
})()"""

COLLECT_JS = r"""() => {
  const css = (el, p) => el ? getComputedStyle(el).getPropertyValue(p).trim() : null;
  const fcp = performance.getEntriesByName('first-contentful-paint')[0];
  const fonts = [...document.fonts].filter(f => f.status === 'loaded')
    .map(f => `${f.family.replace(/["']/g, '')} ${f.weight} ${f.style}`
              + (f.unicodeRange && f.unicodeRange !== 'U+0-10FFFF' ? ` [${f.unicodeRange.slice(0, 40)}]` : ''));
  const fontFiles = performance.getEntriesByType('resource').filter(r => /\.woff2?(\?|$)|fonts\.gstatic\.com/.test(r.name))
    .map(r => {
      try { const u = new URL(r.name); return (u.origin === location.origin ? '' : u.host) + u.pathname }
      catch { return r.name }
    });
  // utilities that exist only in context/ToastContext.tsx (D4 P11 adds context/ to Tailwind's content globs)
  const wanted = ['.z-\\[9999\\]', '.right-4', '.pointer-events-auto', '.translate-x-4', '.transition-opacity', '.break-words'];
  const toast = Object.fromEntries(wanted.map(w => [w, false]));
  for (const sh of [...document.styleSheets]) {
    let rules; try { rules = sh.cssRules } catch { continue }
    for (const r of rules) {
      const sel = (r.selectorText || '').split(',').map(x => x.trim());
      for (const w of wanted) if (sel.includes(w)) toast[w] = true;
    }
  }
  const keys = []; try { for (let i = 0; i < localStorage.length; i++) keys.push(localStorage.key(i)) } catch {}
  return {
    gate: window.__sdGate || null,
    fcp_ms: fcp ? Math.round(fcp.startTime) : null,
    html: { sd_shell: document.documentElement.dataset.sdShell || null,
            shell_top: css(document.documentElement, '--shell-top') || null,
            inline_style: document.documentElement.getAttribute('style'),
            class: document.documentElement.className },
    body: { padding_top: css(document.body, 'padding-top'), inline_style: document.body.getAttribute('style') },
    fonts_loaded: [...new Set(fonts)].sort(),
    font_files: [...new Set(fontFiles)].sort(),
    toast_rules_in_css: toast,
    local_storage_keys: keys.sort(),
  };
}"""


def group_key(method: str, url: str, base_origin: str) -> str | None:
    """Bucket for a request; None for same-origin /api/* other than /api/prefs (parity.py compares those)."""
    p = urlsplit(url)
    if f"{p.scheme}://{p.netloc}" != base_origin:
        return f"third-party {p.netloc}"
    path = p.path
    if path.startswith("/api/prefs"):
        return f"{method} /api/prefs" + ("/<key>" if path.rstrip("/").count("/") > 2 else "")
    if path.startswith("/api/"):
        return None
    if path.startswith("/_next/static/"):
        return f"{method} /_next/static/*.{path.rsplit('.', 1)[-1]}"
    return f"{method} {path}"


def visit(browser: Any, base: str, tab: str, code: str, observe_s: float) -> dict[str, Any]:
    probe = qa_probe()
    ctx = probe.new_qa_context(browser, viewport={"width": 1680, "height": 1050})
    blocked: list[str] = []
    install_get_only_guard(ctx, blocked)   # before the first navigation
    ctx.add_init_script(GATE_INIT)
    page = ctx.new_page()
    reqs: list[dict[str, Any]] = []
    t0 = time.perf_counter()

    def on_req(r: Any) -> None:
        if not r.url.startswith(("data:", "blob:", "about:")):
            reqs.append({"method": r.method, "url": r.url, "t_ms": round((time.perf_counter() - t0) * 1000), "status": None})

    def on_resp(resp: Any) -> None:
        for x in reversed(reqs):
            if x["url"] == resp.url and x["status"] is None:
                x["status"] = resp.status
                break

    page.on("request", on_req)
    page.on("response", on_resp)
    page.goto(f"{base}/?tab={tab}", wait_until="domcontentloaded", timeout=120_000)
    ready_ms: int | None = None
    try:
        page.wait_for_function(probe.READY_JS, arg=code, timeout=30_000, polling=50)
        ready_ms = round((time.perf_counter() - t0) * 1000)
    except PlaywrightTimeout:
        print(f"[delta_probe] {base}: the page header {code} did not render within 30 s (ready_ms = null)", file=sys.stderr)
    page.wait_for_timeout(int(observe_s * 1000))
    data = page.evaluate(COLLECT_JS)
    ctx.close()
    origin = f"{urlsplit(base).scheme}://{urlsplit(base).netloc}"
    groups: dict[str, dict[str, Any]] = {}
    api = 0
    for r in reqs:
        k = group_key(r["method"], r["url"], origin)
        if k is None:
            api += 1
            continue
        g = groups.setdefault(k, {"count": 0, "statuses": set(), "first_ms": r["t_ms"]})
        g["count"] += 1
        g["statuses"].add(str(r["status"]) if r["status"] is not None else "pending/failed")
    data["ready_ms"] = ready_ms
    data["blocked_non_get"] = sorted(set(blocked))
    data["api_requests"] = api
    # Font files from the network capture (Resource Timing does not reliably list cross-origin font loads)
    data["font_files_rt"] = data.pop("font_files")
    data["font_files"] = sorted({(u.netloc if f"{u.scheme}://{u.netloc}" != origin else "") + u.path
                                 for u in (urlsplit(r["url"]) for r in reqs)
                                 if u.path.endswith((".woff2", ".woff", ".ttf")) or u.netloc == "fonts.gstatic.com"})
    data["non_api_requests"] = {k: {"count": v["count"], "statuses": sorted(v["statuses"]), "first_ms": v["first_ms"]}
                                for k, v in sorted(groups.items())}
    return data


def to_markdown(report: dict[str, Any]) -> str:
    """Side-by-side A/B table per engine (what README §5.1 shows)."""
    out: list[str] = []
    for engine, e in report["engines"].items():
        a, b = e["a"], e["b"]

        def gate(x: dict[str, Any]) -> str:
            g = x.get("gate") or {}
            if not g.get("seen"):
                return "never in the DOM"
            life = None if g.get("gone_at") is None else round(g["gone_at"] - g["shown_at"])
            return f"shown at {round(g['shown_at'])} ms, gone after {life} ms" if life is not None else "still shown"

        def reqs(x: dict[str, Any]) -> str:
            items = [f"{k} ×{v['count']} ({'/'.join(v['statuses'])})" for k, v in x["non_api_requests"].items()
                     if not k.startswith("GET /_next/static/")]
            static = {k: v["count"] for k, v in x["non_api_requests"].items() if k.startswith("GET /_next/static/")}
            return "<br>".join(items + [f"static: {static}"])

        rows = [
            ("ready (header) ms / FCP ms", f"{a['ready_ms']} / {a['fcp_ms']}", f"{b['ready_ms']} / {b['fcp_ms']}"),
            ("boot gate", gate(a), gate(b)),
            ("`<html>` data-sd-shell · --shell-top · inline style",
             f"{a['html']['sd_shell']} · {a['html']['shell_top']} · {a['html']['inline_style']}",
             f"{b['html']['sd_shell']} · {b['html']['shell_top']} · {b['html']['inline_style']}"),
            ("`<body>` padding-top · inline style", f"{a['body']['padding_top']} · {a['body']['inline_style']}",
             f"{b['body']['padding_top']} · {b['body']['inline_style']}"),
            ("font files fetched (network)", "<br>".join(a["font_files"]) or "none", "<br>".join(b["font_files"]) or "none"),
            ("FontFaces loaded", "<br>".join(a["fonts_loaded"]) or "none", "<br>".join(b["fonts_loaded"]) or "none"),
            ("ToastContext-only CSS rules present", ", ".join(k for k, v in a["toast_rules_in_css"].items() if v) or "none",
             ", ".join(k for k, v in b["toast_rules_in_css"].items() if v) or "none"),
            ("localStorage keys after the visit", ", ".join(a["local_storage_keys"]) or "none",
             ", ".join(b["local_storage_keys"]) or "none"),
            ("/api calls (compared by parity.py)", str(a["api_requests"]), str(b["api_requests"])),
            ("non-GET /api requests refused by the probe", ", ".join(a.get("blocked_non_get", [])) or "none",
             ", ".join(b.get("blocked_non_get", [])) or "none"),
            ("other requests", reqs(a), reqs(b)),
        ]
        meta = report["meta"]
        title = f"**{engine}** ({e['version']}), tab `{meta['tab']}`, observed {meta['observe_s']} s after the page header:"
        out += [title, "", "| | A (pre-program) | B (live) |", "|---|---|---|"]
        out += [f"| {k} | {va.replace('|', '/')} | {vb.replace('|', '/')} |" for k, va, vb in rows]
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="A/B capture of the deltas parity.py does not compare")
    ap.add_argument("--a", required=True)
    ap.add_argument("--b", required=True)
    ap.add_argument("--tab", default="brief")
    ap.add_argument("--code", default="BRF")
    ap.add_argument("--observe", type=float, default=15.0)
    ap.add_argument("--browser", choices=["chromium", "webkit", "both"], default="both")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    probe = qa_probe()
    engines = list(probe.ENGINES) if a.browser == "both" else [a.browser]
    report: dict[str, Any] = {"meta": {"a": a.a, "b": a.b, "tab": a.tab, "observe_s": a.observe}, "engines": {}}
    with sync_playwright() as pw:
        for engine in engines:
            browser = probe.launch_browser(pw, engine)
            try:
                report["engines"][engine] = {"version": browser.version,
                                             "a": visit(browser, a.a.rstrip("/"), a.tab, a.code, a.observe),
                                             "b": visit(browser, a.b.rstrip("/"), a.tab, a.code, a.observe)}
            finally:
                browser.close()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "delta_probe.json").write_text(json.dumps(report, indent=1) + "\n")
    md = to_markdown(report)
    (a.out / "delta_probe.md").write_text(md + "\n")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
