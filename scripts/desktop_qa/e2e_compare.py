"""C3-02 (COMP leftover) E2E: two pages in ONE browser context (= two windows of one origin sharing localStorage).

compare: page 1 adds WIPRO to the compare set, page 2 (open since before the edit) later removes INFY.
Both edits must survive in both pages, in localStorage and on the (scratch) prefs server, and nothing ping-pongs.
Prefs mode 'sync' ONLY against a scratch server whose /api/prefs is a local scratch SQLite file (scratch_server.py --prefs-db).

    $P scripts/desktop_qa/scratch_server.py --ui <export> --port 8093 --block-mutations --prefs-db <scratch>/prefs.sqlite
    $P scripts/desktop_qa/e2e_compare.py --base http://127.0.0.1:8093 --out <dir> [--engines chromium,webkit]
Every WebSocket is mocked (probe.new_qa_context, never forwarded): the run opens 0 live sockets.
Exit 0 = every engine passed, 1 = a lost edit (or any other failed assertion), 2 = refused.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from desktop_qa.probe import launch_browser, new_qa_context

KEY = "suryadhana.comp.v1"
SEED = {"syms": ["TCS", "INFY", "HCLTECH"], "period": "1y"}
WANT = ["TCS", "HCLTECH", "WIPRO"]
INPUT = 'input[placeholder="Add ticker + Enter"]'
CHIPS_JS = """() => [...document.querySelectorAll('span[role="button"]')].filter(b => b.textContent === '✕')
    .map(b => (b.previousElementSibling?.textContent || '').replace(' (no data)', '').trim()).filter(Boolean)"""


def http(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def server_syms(base: str) -> list[str] | None:
    rec = http(base, "GET", "/api/prefs")["prefs"].get(KEY)
    return json.loads(rec["value"]).get("syms") if rec and not rec["deleted"] else None


def local_syms(page) -> list[str] | None:
    raw = page.evaluate(f"() => localStorage.getItem('{KEY}')")
    return json.loads(raw).get("syms") if raw else None


def wait_chips(page, pred, timeout_s: float) -> list[str]:
    end = time.time() + timeout_s
    got = page.evaluate(CHIPS_JS)
    while time.time() < end and not pred(got):
        page.wait_for_timeout(200)
        got = page.evaluate(CHIPS_JS)
    return got


def run_compare(engine: str, base: str, out: Path) -> dict:
    http(base, "PUT", f"/api/prefs/{KEY}", {"value": json.dumps(SEED), "updated_at": int(time.time() * 1000), "origin": "e2e-seed"})
    res: dict = {"engine": engine, "scenario": "compare", "ok": False, "steps": []}
    with sync_playwright() as pw:
        browser = launch_browser(pw, engine)
        try:
            mocked: list[str] = []      # every WebSocket mocked by new_qa_context: 0 live sockets
            ctx = new_qa_context(browser, prefs_mode="sync", ws_mocked=mocked, viewport={"width": 1440, "height": 900})
            p1, p2 = ctx.new_page(), ctx.new_page()
            for p in (p1, p2):
                p.goto(base + "/?tab=compare", wait_until="domcontentloaded", timeout=60_000)
                p.wait_for_selector(INPUT, timeout=30_000)
            c1 = wait_chips(p1, lambda c: c == SEED["syms"], 15)
            c2 = wait_chips(p2, lambda c: c == SEED["syms"], 15)
            res["steps"].append({"hydrated": [c1, c2]})
            p1.fill(INPUT, "WIPRO")                                # page 1 adds
            p1.press(INPUT, "Enter")
            c2 = wait_chips(p2, lambda c: "WIPRO" in c, 8)
            res["steps"].append({"p2_after_p1_add": c2})
            p2.wait_for_timeout(1000)
            p2.evaluate("""() => { const b = [...document.querySelectorAll('span[role="button"]')]
                .find(x => x.textContent === '✕' && (x.previousElementSibling?.textContent || '').startsWith('INFY')); b && b.click() }""")
            c1 = wait_chips(p1, lambda c: "INFY" not in c, 8)         # page 2 removes INFY later
            res["steps"].append({"p1_after_p2_remove": c1})
            p1.wait_for_timeout(3500)  # debounce + flush (300 ms, max 2 s) and any refetch
            f1, f2 = p1.evaluate(CHIPS_JS), p2.evaluate(CHIPS_JS)
            l1, l2, srv = local_syms(p1), local_syms(p2), server_syms(base)
            res.update({"chips": [f1, f2], "localStorage": [l1, l2], "server": srv})
            p1.screenshot(path=str(out / f"compare-{engine}-page1.png"))
            p2.screenshot(path=str(out / f"compare-{engine}-page2.png"))
            ok = f1 == WANT and f2 == WANT and l1 == WANT and l2 == WANT and srv == WANT
            p1.wait_for_timeout(4000)                                  # no ping-pong: quiet afterwards
            res["server_after_quiet"] = server_syms(base)
            res["ok"] = ok and res["server_after_quiet"] == WANT
            res["ws_mocked"] = len(mocked)
            ctx.close()
        finally:
            browser.close()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--engines", default="chromium,webkit")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    qa = http(a.base, "GET", "/__qa/health")
    if not str(qa.get("prefs", "")).startswith("local:"):
        print("refusing: the server's /api/prefs is not a local scratch store", file=sys.stderr)
        return 2
    results = [run_compare(e, a.base, a.out) for e in a.engines.split(",")]
    (a.out / "compare_multiwin.json").write_text(json.dumps(results, indent=2))
    for r in results:
        detail = {k: v for k, v in r.items() if k not in ("engine", "scenario", "ok", "steps")}
        print(f"[{r['engine']}] {r['scenario']}: {'PASS' if r['ok'] else 'FAIL'} {json.dumps(detail, default=str)[:600]}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
