"""R-UI probe: time-to-first-useful-number per page, mobile viewport shots, GO / stock-window / help flows.

GET-only: the UI's prefs sync is pinned to 'readonly' through the project's own QA context helper, so nothing the
page does writes the owner's settings. Pages are visited one at a time (the terminal itself paces its own calls).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path('/Users/sudheer/MahaKubera_108/SuryaDhana_AI')
sys.path.insert(0, str(ROOT / 'scripts'))
from desktop_qa.probe import launch_browser, new_qa_context  # noqa: E402
from desktop_qa.pages import load_page_source  # noqa: E402

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.')
OUT.mkdir(parents=True, exist_ok=True)
BASE = 'http://127.0.0.1:8010'
MOBILE_TABS = ['brief', 'watch', 'markets', 'options', 'ostrategy', 'gold', 'desk', 'alerts', 'charts', 'derivatives']
# PORT / BRKR: never screenshot with any URL/login text; we skip them in mobile shots entirely.
NUM_RE = re.compile(r'\d[\d,]*\.\d|\b\d{2,}\b')

# first useful number = a numeric token (price/percent/count) inside the page area, excluding the chrome
TTFN_JS = """
() => {
  const el = document.querySelector('.sd-page');
  if (!el) return null;
  const t = el.innerText || '';
  const m = t.match(/\\d[\\d,]*\\.\\d|\\b\\d{2,}\\b/);
  return m ? m[0] : null;
}
"""
EMPTY_JS = """
() => {
  const el = document.querySelector('.sd-page');
  const t = (el && el.innerText) || '';
  const lines = t.split('\\n').map(s => s.trim()).filter(Boolean);
  const dash = (t.match(/—/g) || []).length;
  const unavailable = (t.match(/unavailable|not available|no data|nothing|failed|offline|stale|since 2026/gi) || []).length;
  return { chars: t.length, lines: lines.length, dashes: dash, degraded_words: unavailable,
           words: t.split(/\\s+/).length, scrollH: document.documentElement.scrollHeight };
}
"""


def ttfn(page, tab: str, timeout_s: float = 20.0) -> dict:
    t0 = time.perf_counter()
    page.goto(f'{BASE}/?tab={tab}', wait_until='domcontentloaded', timeout=60_000)
    first = None
    first_ms = None
    deadline = t0 + timeout_s
    while time.perf_counter() < deadline:
        try:
            v = page.evaluate(TTFN_JS)
        except Exception:  # noqa: BLE001
            v = None
        if v:
            first, first_ms = v, int((time.perf_counter() - t0) * 1000)
            break
        time.sleep(0.02)
    page.wait_for_timeout(4000)
    stats = page.evaluate(EMPTY_JS)
    return {'tab': tab, 'first_number': first, 'ttfn_ms': first_ms, **stats}


def main() -> None:
    from playwright.sync_api import sync_playwright
    src = load_page_source()
    tabs = list(src.tab_ids)
    results = {'ttfn': [], 'mobile': [], 'flows': []}
    with sync_playwright() as pw:
        browser = launch_browser(pw, 'chromium', chromium_channel='chrome')
        # 1. desktop TTFN (one warm pass first so chunks are cached like a real session)
        ctx = new_qa_context(browser, prefs_mode='readonly', viewport={'width': 1680, 'height': 1050}, device_scale_factor=1)
        page = ctx.new_page()
        page.goto(f'{BASE}/?tab=brief', wait_until='domcontentloaded'); page.wait_for_timeout(4000)
        for tab in tabs:
            r = ttfn(page, tab)
            results['ttfn'].append(r)
            print(f"[ttfn] {tab:12} first={str(r['first_number']):>12} at {r['ttfn_ms']} ms · lines={r['lines']} dashes={r['dashes']} degraded={r['degraded_words']} scrollH={r['scrollH']}", flush=True)
        # 2. flows on desktop: GO bar, GO with 'TCS', stock window, help card, OMON via GO, 'TCS OMON'
        page.goto(f'{BASE}/?tab=watch', wait_until='domcontentloaded'); page.wait_for_timeout(2500)
        page.keyboard.press('/'); page.wait_for_timeout(400)
        page.screenshot(path=str(OUT / 'flow_go_empty.png'))
        page.keyboard.type('TCS'); page.wait_for_timeout(700)
        page.screenshot(path=str(OUT / 'flow_go_tcs.png'))
        t0 = time.perf_counter(); page.keyboard.press('Enter')
        page.wait_for_selector('[data-sd-stock-window]', timeout=15_000)
        # first number in the stock window
        win_ms = None
        while time.perf_counter() - t0 < 15:
            txt = page.evaluate("() => (document.querySelector('[data-sd-stock-window]')||{}).innerText || ''")
            if re.search(r'₹\s?\d|\d[\d,]*\.\d\d', txt):
                win_ms = int((time.perf_counter() - t0) * 1000); break
            time.sleep(0.02)
        page.wait_for_timeout(2500)
        page.screenshot(path=str(OUT / 'flow_stock_tcs.png'))
        results['flows'].append({'flow': 'GO TCS → stock window first price', 'ms': win_ms})
        print(f"[flow] stock window first price {win_ms} ms", flush=True)
        page.keyboard.press('Escape'); page.wait_for_timeout(300)
        page.keyboard.press('?'); page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / 'flow_help.png'))
        page.keyboard.press('Escape'); page.wait_for_timeout(300)
        page.keyboard.press('/'); page.keyboard.type('TCS OMON'); page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / 'flow_go_tcs_omon.png'))
        page.keyboard.press('Escape')
        # MORE menu
        try:
            page.click('[data-more-menu]', timeout=3000); page.wait_for_timeout(400)
            page.screenshot(path=str(OUT / 'flow_more_menu.png'))
            page.keyboard.press('Escape')
        except Exception as e:  # noqa: BLE001
            print('more menu:', e)
        # narrow desktop (1280) and laptop (1100) widths on DESK + OMON
        for w, h in ((1280, 800), (1100, 700)):
            page.set_viewport_size({'width': w, 'height': h})
            for tab in ('desk', 'options', 'markets'):
                page.goto(f'{BASE}/?tab={tab}', wait_until='domcontentloaded'); page.wait_for_timeout(3500)
                page.screenshot(path=str(OUT / f'narrow_{w}_{tab}.png'))
        ctx.close()
        # 3. mobile (iPhone-ish) viewport
        mctx = new_qa_context(browser, prefs_mode='readonly', viewport={'width': 390, 'height': 844}, device_scale_factor=2)
        mctx.add_init_script("")
        mp = mctx.new_page()
        for tab in MOBILE_TABS:
            t0 = time.perf_counter()
            mp.goto(f'{BASE}/?tab={tab}', wait_until='domcontentloaded', timeout=60_000)
            mp.wait_for_timeout(4000)
            st = mp.evaluate(EMPTY_JS)
            sw = mp.evaluate('() => document.documentElement.scrollWidth')
            mp.screenshot(path=str(OUT / f'mobile_{tab}.png'))
            results['mobile'].append({'tab': tab, 'scrollWidth': sw, **st})
            print(f"[mobile] {tab:12} scrollWidth={sw} (viewport 390) scrollH={st['scrollH']}", flush=True)
        mctx.close()
        browser.close()
    (OUT / 'probe.json').write_text(json.dumps(results, indent=2))
    print('done')


if __name__ == '__main__':
    main()
