"""C3-02 E2E: two pages in ONE browser context (= two windows of one origin sharing localStorage).

watchlist: page 1 adds HDFCBANK, page 2 (open since before the edit) later removes INFY.
gold:      page 1 sets the MCXG chase limit to 400, page 2 (open since before) later ticks a manual check.
compare:   page 1 adds WIPRO to the COMP set, page 2 (open since before) later removes INFY (FX-UI adversarial check:
           suryadhana.comp.v1 is a SYNC key edited step by step, so it lost page 1's edit like the watchlist did).
Both edits must survive in both pages, in localStorage and on the (scratch) prefs server. Prefs mode 'sync' is used ONLY against
a scratch server whose /api/prefs is a local scratch SQLite file (scratch_server.py --prefs-db).

Serve a scratch export with a scratch prefs store first, e.g.:
    $P scripts/desktop_qa/scratch_server.py --ui <export> --port 8093 --block-mutations --prefs-db <scratch>/prefs.sqlite
then:
    $P scripts/desktop_qa/e2e_multiwin.py --base http://127.0.0.1:8093 --out <dir> [--engines chromium,webkit] \
        [--scenarios watchlist,gold,compare]
Refuses a server whose /api/prefs is not local (never touches the live store). Engines run one after the other.
Exit 0 = every engine passed, 1 = a lost edit (or any other failed assertion), 2 = refused.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desktop_qa.probe import launch_browser, new_qa_context

KEY = "suryadhana.watchlist"
SEED = ["RELIANCE", "TCS", "INFY"]
WANT = ["RELIANCE", "TCS", "HDFCBANK"]


def http(base: str, method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def server_list(base: str) -> list[str] | None:
    rec = http(base, "GET", "/api/prefs")["prefs"].get(KEY)
    return json.loads(rec["value"]) if rec and not rec["deleted"] else None


def rows(page) -> list[str]:
    """Symbols of the WATCH-sourced rows the page renders (the rows with a remove button)."""
    return page.evaluate("""() => [...document.querySelectorAll('span[title="Remove from watchlist"]')]
        .map(x => (x.closest('tr')?.innerText || '').trim().split(/\\s+/)[0])""")


def wait_rows(page, pred, timeout_s: float) -> list[str]:
    end = time.time() + timeout_s
    got = rows(page)
    while time.time() < end and not pred(got):
        page.wait_for_timeout(200)
        got = rows(page)
    return got


def run_watchlist(engine: str, base: str, out: Path) -> dict:
    # reset the scratch store's watchlist (a newer LWW write)
    http(base, "PUT", f"/api/prefs/{KEY}", {"value": json.dumps(SEED), "updated_at": int(time.time() * 1000), "origin": "e2e-seed"})
    res: dict = {"engine": engine, "scenario": "watchlist", "ok": False, "steps": []}
    with sync_playwright() as pw:
        browser = launch_browser(pw, engine)
        try:
            ctx = new_qa_context(browser, prefs_mode="sync", viewport={"width": 1440, "height": 900})
            p1, p2 = ctx.new_page(), ctx.new_page()
            for p in (p1, p2):
                p.goto(base + "/?tab=watch", wait_until="domcontentloaded", timeout=60_000)
                p.wait_for_selector('input[placeholder="Add ticker + Enter"]', timeout=30_000)
            r1 = wait_rows(p1, lambda r: set(SEED) <= set(r), 15)
            r2 = wait_rows(p2, lambda r: set(SEED) <= set(r), 15)
            res["steps"].append({"hydrated": [r1, r2]})
            # page 1 adds
            p1.fill('input[placeholder="Add ticker + Enter"]', "HDFCBANK")
            p1.press('input[placeholder="Add ticker + Enter"]', "Enter")
            r2 = wait_rows(p2, lambda r: "HDFCBANK" in r, 8)
            res["steps"].append({"p2_after_p1_add": r2})
            p2.wait_for_timeout(1000)
            # page 2 removes INFY later
            p2.locator("tr", has_text="INFY").locator('span[title="Remove from watchlist"]').first.click()
            r1 = wait_rows(p1, lambda r: "INFY" not in r, 8)
            res["steps"].append({"p1_after_p2_remove": r1})
            p1.wait_for_timeout(3500)  # debounce + flush (300 ms, max 2 s) and any refetch
            ls1 = json.loads(p1.evaluate(f"() => localStorage.getItem('{KEY}')") or "null")
            ls2 = json.loads(p2.evaluate(f"() => localStorage.getItem('{KEY}')") or "null")
            srv = server_list(base)
            f1, f2 = rows(p1), rows(p2)
            res.update({"localStorage": [ls1, ls2], "server": srv, "rows": [f1, f2]})
            p1.screenshot(path=str(out / f"multiwin-{engine}-page1.png"))
            p2.screenshot(path=str(out / f"multiwin-{engine}-page2.png"))
            ok = (ls1 == WANT and ls2 == WANT and srv == WANT
                  and set(WANT) <= set(f1) and "INFY" not in f1 and set(WANT) <= set(f2) and "INFY" not in f2)
            # no ping-pong: the server value stays put and no further writes happen for a while
            p1.wait_for_timeout(4000)
            res["server_after_quiet"] = server_list(base)
            res["ok"] = ok and res["server_after_quiet"] == WANT
            ctx.close()
        finally:
            browser.close()
    return res


GOLD = "goldPreOpen.v1"


def ist_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + 5.5 * 3600))


def gold_local(page) -> dict:
    return json.loads(page.evaluate(f"() => localStorage.getItem('{GOLD}')") or "{}")


def gold_server(base: str) -> dict:
    rec = http(base, "GET", "/api/prefs")["prefs"].get(GOLD)
    return json.loads(rec["value"]) if rec and not rec["deleted"] else {}


def run_gold(engine: str, base: str, out: Path) -> dict:
    seed = {"day": ist_today(), "baseline": "", "mcx": "", "threshold": "300", "trigger": "1.1161", "done": {}}
    http(base, "PUT", f"/api/prefs/{GOLD}", {"value": json.dumps(seed), "updated_at": int(time.time() * 1000), "origin": "e2e-seed"})
    res: dict = {"engine": engine, "scenario": "gold", "ok": False}
    limit = 'label:has-text("Chase limit") input'
    with sync_playwright() as pw:
        browser = launch_browser(pw, engine)
        try:
            ctx = new_qa_context(browser, prefs_mode="sync", viewport={"width": 1440, "height": 900})
            p1, p2 = ctx.new_page(), ctx.new_page()
            for p in (p1, p2):
                p.goto(base + "/?tab=commodity", wait_until="domcontentloaded", timeout=60_000)
                p.wait_for_selector(limit, timeout=30_000)
                p.wait_for_selector('input[type="checkbox"][aria-label$=" checked"]', timeout=30_000)
            p1.fill(limit, "400")                                 # page 1: a setting
            end = time.time() + 8
            while time.time() < end and p2.locator(limit).input_value() != "400":
                p2.wait_for_timeout(200)
            res["p2_limit_after_p1"] = p2.locator(limit).input_value()
            p2.wait_for_timeout(800)
            box = p2.locator('input[type="checkbox"][aria-label$=" checked"]').first
            res["check_name"] = box.get_attribute("aria-label")
            box.click()                                           # page 2: a different edit, later
            p1.wait_for_timeout(3500)
            l1, l2, srv = gold_local(p1), gold_local(p2), gold_server(base)
            p1_box = p1.locator(f'input[aria-label="{res["check_name"]}"]').is_checked()
            res.update({"local": [l1, l2], "server": srv, "p1_checkbox_adopted": p1_box,
                        "p2_limit": p2.locator(limit).input_value()})
            p1.screenshot(path=str(out / f"multiwin-gold-{engine}-page1.png"))
            both = all(d.get("threshold") == "400" and any(d.get("done", {}).values()) for d in (l1, l2, srv))
            res["ok"] = both and p1_box and res["p2_limit"] == "400"
            ctx.close()
        finally:
            browser.close()
    return res


COMP = "suryadhana.comp.v1"
COMP_SEED = {"syms": ["TCS", "INFY", "HCLTECH"], "period": "1y"}
COMP_WANT = ["TCS", "HCLTECH", "WIPRO"]
COMP_INPUT = 'input[placeholder="Add ticker + Enter"]'
# The compare chips: <span><span/><span>SYM[ (no data)]</span><span role="button">✕</span></span> (ui/components/Compare.tsx)
COMP_CHIPS_JS = """() => [...document.querySelectorAll('span[role="button"]')]
    .filter(b => b.textContent.trim() === '✕' && b.parentElement && b.parentElement.children.length === 3)
    .map(b => (b.previousElementSibling?.textContent || '').replace(/ \\(no data\\)$/, '').trim())"""
COMP_REMOVE_JS = """(sym) => {
    const b = [...document.querySelectorAll('span[role="button"]')].find(x => x.textContent.trim() === '✕'
        && (x.previousElementSibling?.textContent || '').replace(/ \\(no data\\)$/, '').trim() === sym)
    if (!b) return false
    b.click()
    return true
}"""


def comp_chips(page) -> list[str]:
    return page.evaluate(COMP_CHIPS_JS)


def comp_local(page) -> list[str] | None:
    raw = page.evaluate(f"() => localStorage.getItem('{COMP}')")
    return (json.loads(raw) or {}).get("syms") if raw else None


def comp_server(base: str) -> list[str] | None:
    rec = http(base, "GET", "/api/prefs")["prefs"].get(COMP)
    return json.loads(rec["value"]).get("syms") if rec and not rec["deleted"] else None


def wait_chips(page, pred, timeout_s: float) -> list[str]:
    end = time.time() + timeout_s
    got = comp_chips(page)
    while time.time() < end and not pred(got):
        page.wait_for_timeout(200)
        got = comp_chips(page)
    return got


def run_compare(engine: str, base: str, out: Path) -> dict:
    http(base, "PUT", f"/api/prefs/{COMP}", {"value": json.dumps(COMP_SEED), "updated_at": int(time.time() * 1000),
                                            "origin": "e2e-seed"})
    res: dict = {"engine": engine, "scenario": "compare", "ok": False, "steps": []}
    with sync_playwright() as pw:
        browser = launch_browser(pw, engine)
        try:
            ctx = new_qa_context(browser, prefs_mode="sync", viewport={"width": 1440, "height": 900})
            p1, p2 = ctx.new_page(), ctx.new_page()
            for p in (p1, p2):
                p.goto(base + "/?tab=compare", wait_until="domcontentloaded", timeout=60_000)
                p.wait_for_selector(COMP_INPUT, timeout=30_000)
            seed = COMP_SEED["syms"]
            res["steps"].append({"hydrated": [wait_chips(p1, lambda c: c == seed, 15), wait_chips(p2, lambda c: c == seed, 15)]})
            p1.fill(COMP_INPUT, "WIPRO")                          # page 1 adds
            p1.press(COMP_INPUT, "Enter")
            res["steps"].append({"p2_after_p1_add": wait_chips(p2, lambda c: "WIPRO" in c, 8)})
            p2.wait_for_timeout(1000)
            res["steps"].append({"p2_removed_infy": p2.evaluate(COMP_REMOVE_JS, "INFY")})   # page 2 removes, later
            res["steps"].append({"p1_after_p2_remove": wait_chips(p1, lambda c: "INFY" not in c, 8)})
            p1.wait_for_timeout(3500)                              # debounce + flush and any refetch
            l1, l2, srv = comp_local(p1), comp_local(p2), comp_server(base)
            c1, c2 = comp_chips(p1), comp_chips(p2)
            res.update({"localStorage": [l1, l2], "server": srv, "chips": [c1, c2]})
            p1.screenshot(path=str(out / f"multiwin-compare-{engine}-page1.png"))
            p2.screenshot(path=str(out / f"multiwin-compare-{engine}-page2.png"))
            ok = l1 == COMP_WANT and l2 == COMP_WANT and srv == COMP_WANT and c1 == COMP_WANT and c2 == COMP_WANT
            p1.wait_for_timeout(4000)                              # no ping-pong: the server value stays put
            res["server_after_quiet"] = comp_server(base)
            res["ok"] = ok and res["server_after_quiet"] == COMP_WANT
            ctx.close()
        finally:
            browser.close()
    return res


SCENARIOS = {"watchlist": run_watchlist, "gold": run_gold, "compare": run_compare}


def prefs_store_is_local(base: str) -> bool:
    """True only for a scratch_server.py whose /api/prefs is a local scratch SQLite file (never the live store)."""
    try:
        qa = http(base, "GET", "/__qa/health")
    except Exception:  # noqa: BLE001 - not a scratch server (the live ui-api has no /__qa/health): refuse
        return False
    return str(qa.get("prefs", "")).startswith("local:")


def run_scenario(name: str, engine: str, base: str, out: Path) -> dict:
    """One scenario; a crash (selector timeout, closed page) is a FAIL with its error, and the others still run."""
    try:
        return SCENARIOS[name](engine, base, out)
    except Exception as exc:  # noqa: BLE001 - reported as this scenario's failure
        return {"engine": engine, "scenario": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:400]}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="two windows of one origin: both edits must survive (scratch prefs only)")
    ap.add_argument("--base", required=True, help="a scratch_server.py started with --prefs-db (never the live :8010)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--engines", default="chromium,webkit")
    ap.add_argument("--scenarios", default=",".join(SCENARIOS), help=f"comma list of {', '.join(SCENARIOS)}")
    return ap


def main(argv: list[str] | None = None) -> int:
    a = build_parser().parse_args(argv)
    scenarios = [s.strip() for s in a.scenarios.split(",") if s.strip()]
    unknown = [s for s in scenarios if s not in SCENARIOS]
    if unknown or not scenarios:
        print(f"unknown scenario(s) {unknown} (expected some of {', '.join(SCENARIOS)})", file=sys.stderr)
        return 2
    if not prefs_store_is_local(a.base):
        print("refusing: the server's /api/prefs is not a local scratch store (scratch_server.py --prefs-db)", file=sys.stderr)
        return 2
    a.out.mkdir(parents=True, exist_ok=True)
    results = []
    for e in a.engines.split(","):
        results += [run_scenario(s, e, a.base, a.out) for s in scenarios]
    (a.out / "multiwin.json").write_text(json.dumps(results, indent=2))
    for r in results:
        detail = {k: v for k, v in r.items() if k not in ("engine", "scenario", "ok", "steps")}
        print(f"[{r['engine']}] {r['scenario']}: {'PASS' if r['ok'] else 'FAIL'} {json.dumps(detail, default=str)[:600]}")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
