"""C1 trader audit — stage 1: page sweep. Pattern: scripts/ui_audit.py (GET-only browsing)."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
PAGES = ["brief", "world", "eco", "preopen", "watch", "charts", "options", "ostrategy",
         "derivatives", "mcxgold", "risk", "filings", "events", "alerts", "positions",
         "wrap", "backtest", "research", "movers", "markets", "commodity", "desk", "system"]
IGNORE = re.compile(r"Download the React DevTools|\[HMR\]|\[Fast Refresh\]|favicon", re.I)
HONESTY = re.compile(r"(as of[^\n]{0,80}|source[:\s][^\n]{0,60}|stale[^\n]{0,60}|"
                     r"market (closed|open)[^\n]{0,40}|engine (off|on)[^\n]{0,40}|"
                     r"not live[^\n]{0,60}|degraded[^\n]{0,60}|paper[^\n]{0,30}|"
                     r"estimate[^\n]{0,40}|unavailable[^\n]{0,60}|session invalid[^\n]{0,60})", re.I)


def main() -> None:
    tabs = sys.argv[1].split(",") if len(sys.argv) > 1 else PAGES
    results = {}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1680, "height": 1050}, device_scale_factor=1)
        page = ctx.new_page()
        console: list[str] = []
        failed: list[str] = []
        page.on("console", lambda m: console.append(f"{m.type}: {m.text}")
                if m.type == "error" and not IGNORE.search(m.text) else None)
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
        page.on("response", lambda r: failed.append(f"{r.status} {r.request.method} {r.url}")
                if r.status >= 400 and "/api/" in r.url else None)
        page.on("requestfailed", lambda r: failed.append(f"FAILED {r.method} {r.url}")
                if "/api/" in r.url else None)
        for tab in tabs:
            console.clear()
            failed.clear()
            t0 = time.time()
            try:
                page.goto(f"http://localhost:3000/?tab={tab}", wait_until="domcontentloaded", timeout=120_000)
                try:
                    page.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass
                time.sleep(4)
                page.screenshot(path=str(OUT / f"{tab}.png"), full_page=False)
                text = page.inner_text("body")[:30000]
                (OUT / f"{tab}.txt").write_text(text)
                results[tab] = {
                    "ok": True, "load_s": round(time.time() - t0, 1),
                    "console": list(dict.fromkeys(console))[:15],
                    "failed_api": list(dict.fromkeys(failed))[:15],
                    "honesty_markers": list(dict.fromkeys(m.group(0).strip() for m in HONESTY.finditer(text)))[:25],
                    "error_text": bool(re.search(r"Something went wrong|Application error|Unhandled Runtime", text)),
                }
            except Exception as exc:
                results[tab] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                                "console": list(dict.fromkeys(console))[:15],
                                "failed_api": list(dict.fromkeys(failed))[:15]}
            r = results[tab]
            print(f"{tab:12} ok={r['ok']} load={r.get('load_s')}s console={len(r.get('console', []))} "
                  f"apifail={len(r.get('failed_api', []))}{' ERRTEXT' if r.get('error_text') else ''}", flush=True)
        browser.close()
    (OUT / "walk.json").write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
