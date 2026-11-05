"""C1 trader audit — stage 2: interactions (GO bar, CHRT, MCXG ticket, RSK what-if, WTCH, OSTR)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
R: dict = {}


def shot(page, name):
    page.screenshot(path=str(OUT / f"{name}.png"), full_page=False)


def main() -> None:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1680, "height": 1050}, device_scale_factor=1)
        page = ctx.new_page()

        # ---- 1. GO bar discoverability ----
        page.goto("http://localhost:3000/?tab=brief", wait_until="domcontentloaded", timeout=120_000)
        time.sleep(5)
        for query, name in [("chrt", "go_chrt"), ("gold", "go_gold"), ("risk", "go_risk"),
                            ("straddle", "go_straddle"), ("rollover", "go_rollover"), ("RELIANCE", "go_reliance")]:
            page.keyboard.press("Escape")
            time.sleep(0.3)
            page.keyboard.press("/")
            time.sleep(0.5)
            page.keyboard.type(query, delay=40)
            time.sleep(1.2)
            shot(page, name)
            try:
                R[name] = page.inner_text("body")[-2500:]
            except Exception:
                pass
        # open RELIANCE from GO bar (Enter on first hit)
        page.keyboard.press("Enter")
        time.sleep(4)
        shot(page, "go_reliance_enter")
        R["go_reliance_enter_text"] = page.inner_text("body")[:6000]

        # ---- 2. CHRT interactions ----
        page.goto("http://localhost:3000/?tab=charts", wait_until="domcontentloaded", timeout=120_000)
        time.sleep(5)
        # symbol switch via the symbol box
        try:
            box = page.get_by_placeholder("symbol", exact=False).first
            box.click()
            box.fill("TCS")
            time.sleep(1.0)
            page.keyboard.press("Enter")
            time.sleep(3)
            shot(page, "chrt_tcs")
        except Exception as e:
            R["chrt_symbol_err"] = str(e)[:200]
        # weekly timeframe
        try:
            page.get_by_text("W", exact=True).first.click()
            time.sleep(2.5)
            shot(page, "chrt_weekly")
        except Exception as e:
            R["chrt_w_err"] = str(e)[:200]
        # intraday 5m — expect honest degrade
        try:
            page.get_by_text("5m", exact=True).first.click()
            time.sleep(2.5)
            shot(page, "chrt_5m")
            R["chrt_5m_text"] = page.inner_text("body")[:5000]
        except Exception as e:
            R["chrt_5m_err"] = str(e)[:200]
        # crosshair hover on daily
        try:
            page.get_by_text("D", exact=True).first.click()
            time.sleep(2.0)
            page.mouse.move(800, 450)
            time.sleep(0.8)
            shot(page, "chrt_crosshair")
        except Exception as e:
            R["chrt_cross_err"] = str(e)[:200]

        # ---- 3. MCXG paper ticket (scroll) ----
        page.goto("http://localhost:3000/?tab=mcxgold", wait_until="domcontentloaded", timeout=120_000)
        time.sleep(5)
        page.mouse.wheel(0, 1400)
        time.sleep(1.5)
        shot(page, "mcxg_ticket")
        R["mcxg_full_text"] = page.inner_text("body")[:14000]

        # ---- 4. RSK what-if ----
        page.goto("http://localhost:3000/?tab=risk", wait_until="domcontentloaded", timeout=120_000)
        time.sleep(4)
        try:
            wi = page.get_by_placeholder("what-if", exact=False).first
            wi.click()
            wi.fill("RELIANCE,TCS,HDFCBANK,INFY")
            page.keyboard.press("Enter")
            time.sleep(8)
            shot(page, "risk_whatif")
            page.mouse.wheel(0, 900)
            time.sleep(1)
            shot(page, "risk_whatif2")
            R["risk_whatif_text"] = page.inner_text("body")[:14000]
        except Exception as e:
            R["risk_whatif_err"] = str(e)[:300]

        # ---- 5. WTCH add ticker ----
        page.goto("http://localhost:3000/?tab=watch", wait_until="domcontentloaded", timeout=120_000)
        time.sleep(4)
        try:
            add = page.get_by_placeholder("Add ticker", exact=False).first
            add.click()
            add.fill("RELIANCE")
            page.keyboard.press("Enter")
            time.sleep(5)
            shot(page, "watch_reliance")
            R["watch_text"] = page.inner_text("body")[:7000]
        except Exception as e:
            R["watch_err"] = str(e)[:300]

        # ---- 6. OSTR iron condor ----
        page.goto("http://localhost:3000/?tab=ostrategy", wait_until="domcontentloaded", timeout=120_000)
        time.sleep(5)
        try:
            page.get_by_text("Iron condor", exact=False).first.click()
            time.sleep(3)
            shot(page, "ostr_condor")
            R["ostr_condor_text"] = page.inner_text("body")[:9000]
        except Exception as e:
            R["ostr_condor_err"] = str(e)[:300]

        browser.close()
    (OUT / "interact.json").write_text(json.dumps(R, indent=1))
    print("done:", ", ".join(sorted(R.keys())))


if __name__ == "__main__":
    main()
