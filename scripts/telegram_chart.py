#!/usr/bin/env python
"""Telegram /chart renderer: the deployed CHRT page (or the GOLD DAILY view) as a PNG for the bot (RATING R9-P4).

/chart SYMBOL [D|W|M] renders http://127.0.0.1:8010 headless with Playwright under the QA read-only prefs pattern
(scripts/desktop_qa/probe.py: prefs never written back, every WebSocket mocked), screenshots the chart canvas region
and hands back (png_path, caption). The caption is source + as-of only — no direction words, no advice.

Hard rules honoured here:
- page whitelist = {CHRT, GOLD DAILY} only; BRKR / PORT / RSK (and their page names as "symbols") are refused;
- one render at a time (a lock file with a stale takeover);
- 20 s render budget, PNG capped at 1 MB (the viewport steps down before giving up);
- read-only: GETs against the live terminal, nothing stored server-side, prefs sync pinned to 'readonly'.

The /chart bot command in scripts/master_controller.py calls ``chart_for_telegram`` off-thread (PM-applied patch);
``python scripts/telegram_chart.py TCS W --out /tmp/t.png`` renders one by hand.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]

BASE_URL = os.getenv("TELEGRAM_CHART_BASE", "http://127.0.0.1:8010")
OUT_DIR = Path(os.getenv("TELEGRAM_CHART_DIR", str(ROOT / "data" / "telegram_charts")))
LOCK_FILE = Path(os.getenv("TELEGRAM_CHART_LOCK", str(ROOT / "data" / ".telegram_chart.lock")))
LOCK_STALE_S = 180.0            # a crashed render's lock is taken over after this long
RENDER_TIMEOUT_S = 20.0         # the whole render budget (navigation + paint + capture)
MAX_BYTES = 1_000_000           # Telegram photo kept small: ≤ 1 MB
KEEP_LAST = 20                  # old PNGs pruned so data/telegram_charts never grows unbounded

INTERVALS = ("D", "W", "M")     # the CHRT EOD timeframe chips (aria-label="timeframe D|W|M")
CHARTS_TAB = "charts"
GOLD_DAILY_TAB = "gold&sub=daily"
PAGE_WHITELIST = frozenset({CHARTS_TAB, GOLD_DAILY_TAB})
# Never rendered for the bot, whatever the input looks like (the brief's hard rule):
FORBIDDEN_WORDS = frozenset({"BRKR", "BROKER", "PORT", "PORTFOLIO", "POSITIONS", "RSK", "RISK"})
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9&.\-]{0,19}$")
# viewport steps: recapture smaller until the PNG fits MAX_BYTES
VIEWPORTS = ((1600, 900), (1280, 720), (1000, 600))
IST = timezone(timedelta(hours=5, minutes=30))

USAGE = ("Usage: /chart SYMBOL [D|W|M] — the CHRT page as a PNG. "
         "Examples: /chart TCS · /chart NIFTY W · /chart GOLD (the GOLD DAILY view).")


@dataclass(frozen=True)
class ChartRequest:
    """One whitelisted render: which tab, which symbol, which EOD timeframe."""
    symbol: str
    interval: str   # D | W | M (always D for the gold view)
    tab: str        # CHARTS_TAB or GOLD_DAILY_TAB


def parse_command(text: str) -> ChartRequest | str:
    """'/chart TCS W' → ChartRequest; anything off the whitelist → the usage / refusal line (a str)."""
    tokens = (text or "").split()
    if not tokens or tokens[0].split("@")[0].lower() != "/chart":
        return USAGE
    args = tokens[1:]
    if not args or len(args) > 2:
        return USAGE
    symbol = args[0].upper()
    interval = args[1].upper() if len(args) == 2 else "D"
    if symbol in FORBIDDEN_WORDS:
        return f"{symbol} is not a chartable symbol here. {USAGE}"
    if not SYMBOL_RE.fullmatch(symbol):
        return USAGE
    if symbol == "GOLD":
        if interval != "D":
            return "GOLD renders the gold DAILY view — /chart GOLD (no timeframe argument)."
        req = ChartRequest(symbol="GOLD", interval="D", tab=GOLD_DAILY_TAB)
    else:
        if interval not in INTERVALS:
            return USAGE
        req = ChartRequest(symbol=symbol, interval=interval, tab=CHARTS_TAB)
    assert req.tab in PAGE_WHITELIST  # structural: nothing outside {CHRT, GOLD DAILY} ever renders
    return req


def caption_line(req: ChartRequest, as_of: str) -> str:
    """The photo caption: symbol · page/timeframe · as-of · source. Descriptive only — no direction words."""
    if req.tab == GOLD_DAILY_TAB:
        head, src = "GOLD · DAILY", "SuryaDhana terminal (gold desk stored series; display only)"
    else:
        head, src = f"{req.symbol} · CHRT · {req.interval}", ("SuryaDhana terminal (stored NSE EOD panel; live quote "
                                                             "only in session)")
    return f"{head} · as of {as_of} · source: {src} · context — describes, does not predict"


class RenderLock:
    """One render at a time: an O_EXCL lock file with pid + timestamp; a stale lock (crashed render) is taken over."""

    def __init__(self, path: Path = LOCK_FILE, stale_s: float = LOCK_STALE_S) -> None:
        self.path = path
        self.stale_s = stale_s
        self._held = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (0, 1):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, json.dumps({"pid": os.getpid(), "at": time.time()}).encode())
                os.close(fd)
                self._held = True
                return True
            except FileExistsError:
                try:
                    at = float(json.loads(self.path.read_text()).get("at") or 0)
                except (OSError, ValueError, TypeError):
                    at = 0.0
                if attempt == 0 and time.time() - at > self.stale_s:
                    try:
                        self.path.unlink()
                    except OSError:
                        return False
                    continue
                return False
        return False

    def release(self) -> None:
        if self._held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self._held = False

    def __enter__(self) -> "RenderLock":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# ── the headless render (playwright imported lazily: unit tests stub ``render``) ──────────────────────────────────

def _symbol_script(symbol: str) -> str:
    """Init script: the page opens on this symbol (the active-symbol convention CHRT reads; capture.py's pattern)."""
    rec = json.dumps({"symbol": symbol, "expiry": None, "strikes": [],
                      "at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace("+00:00", "Z")})
    return ("(() => { try { "
            f"sessionStorage.setItem('activeSymbol.window.v1', {json.dumps(rec)}); "
            f"localStorage.setItem('suryadhana.omon.v1', {json.dumps(symbol)}); "
            "} catch (e) {} })()")


# Union of the main chart surface and everything near it (LWC paints the panes AND the price/time axes as their own
# narrow canvases — all must be in the box; the gold views draw SVG charts with role="img") + padding, clamped to
# the viewport.
CHART_SURFACE_SELECTOR = 'canvas, svg[role="img"]'
CANVAS_BOX_JS = """() => {
    const cs = [...document.querySelectorAll('canvas, svg[role="img"]')].map(c => c.getBoundingClientRect())
        .filter(r => r.width >= 24 && r.height >= 24 && r.bottom > 0 && r.right > 0
                     && r.top < window.innerHeight && r.left < window.innerWidth);
    if (!cs.length) return null;
    const main = cs.reduce((a, b) => (a.width * a.height >= b.width * b.height ? a : b));
    const rs = cs.filter(r => r.left < main.right + 90 && r.right > main.left - 90
                              && r.top < main.bottom + 600 && r.bottom > main.top - 600);
    const pad = 12;
    const x1 = Math.max(0, Math.min(...rs.map(r => r.left)) - pad);
    const y1 = Math.max(0, Math.min(...rs.map(r => r.top)) - pad);
    const x2 = Math.min(window.innerWidth, Math.max(...rs.map(r => r.right)) + pad);
    const y2 = Math.min(window.innerHeight, Math.max(...rs.map(r => r.bottom)) + pad);
    if (x2 - x1 < 50 || y2 - y1 < 50) return null;
    return {x: x1, y: y1, width: x2 - x1, height: y2 - y1};
}"""


def _left_ms(deadline: float, floor_ms: int = 500) -> int:
    return max(floor_ms, int((deadline - time.monotonic()) * 1000))


def render(req: ChartRequest, out_path: Path, *, base: str = BASE_URL,
           timeout_s: float = RENDER_TIMEOUT_S, engine: str = "chromium") -> dict[str, Any]:
    """Render ``req`` against the live terminal and write the PNG to ``out_path`` (≤ MAX_BYTES or RuntimeError).

    Read-only by construction: QA context (prefs 'readonly', WebSockets mocked), GET navigation only.
    Returns {path, bytes, as_of, viewport}.
    """
    if req.tab not in PAGE_WHITELIST:     # belt + braces: parse_command already guarantees it
        raise ValueError(f"tab {req.tab!r} is not whitelisted")
    deadline = time.monotonic() + timeout_s
    from playwright.sync_api import sync_playwright  # lazy: the bot process imports this module cheaply
    from desktop_qa.probe import launch_browser, new_qa_context

    with sync_playwright() as pw:
        browser = launch_browser(pw, engine, chromium_channel=None)
        try:
            w0, h0 = VIEWPORTS[0]
            ctx = new_qa_context(browser, prefs_mode="readonly",
                                 viewport={"width": w0, "height": h0}, device_scale_factor=1)
            ctx.add_init_script(_symbol_script(req.symbol))
            page = ctx.new_page()
            page.goto(f"{base}/?tab={req.tab}", wait_until="domcontentloaded", timeout=_left_ms(deadline))
            page.wait_for_selector(CHART_SURFACE_SELECTOR, state="visible", timeout=_left_ms(deadline))
            if req.tab == CHARTS_TAB and req.interval != "D":
                chip = page.query_selector(f'[aria-label="timeframe {req.interval}"]')
                if chip:
                    chip.click()
            page.wait_for_timeout(min(2500, _left_ms(deadline)))   # let the series paint / refit
            size = None
            for w, h in VIEWPORTS:
                if (w, h) != (w0, h0) or size is not None:
                    page.set_viewport_size({"width": w, "height": h})
                    page.wait_for_timeout(min(1500, _left_ms(deadline)))
                box = page.evaluate(CANVAS_BOX_JS)
                page.screenshot(path=str(out_path), full_page=False, clip=box or None,
                                timeout=_left_ms(deadline))
                size = out_path.stat().st_size
                if size <= MAX_BYTES:
                    return {"path": out_path, "bytes": size, "viewport": [w, h],
                            "as_of": datetime.now(IST).strftime("%d %b %Y %H:%M IST")}
            raise RuntimeError(f"PNG stays over {MAX_BYTES} bytes at the smallest viewport ({size} bytes)")
        finally:
            browser.close()


def _prune(out_dir: Path, keep: int = KEEP_LAST) -> None:
    try:
        pngs = sorted(out_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in pngs[keep:]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def chart_for_telegram(text: str, *, base: str = BASE_URL, out_dir: Path = OUT_DIR,
                       renderer: Optional[Callable[..., dict[str, Any]]] = None,
                       lock: Optional[RenderLock] = None) -> tuple[Optional[Path], str]:
    """The bot's entry point: parse → lock → render → caption.

    Returns (png_path, caption) on success, (None, user-facing line) otherwise. Never raises: a render failure
    comes back as its one-line message and the lock is always released.
    """
    req = parse_command(text)
    if isinstance(req, str):
        return None, req
    lk = lock or RenderLock()
    if not lk.acquire():
        return None, "A chart render is already running — send /chart again in a few seconds."
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        _prune(out_dir)
        stamp = datetime.now(IST).strftime("%Y%m%d_%H%M%S")
        out_path = out_dir / f"{req.symbol}_{req.interval}_{stamp}.png"
        result = (renderer or render)(req, out_path, base=base)
        final = Path(result.get("path") or out_path)
        if not final.exists():
            return None, "The render produced no image — the terminal may still be warming up."
        if final.stat().st_size > MAX_BYTES:
            return None, f"The chart image came out over 1 MB and was not sent ({final.stat().st_size} bytes)."
        return final, caption_line(req, str(result.get("as_of") or datetime.now(IST).strftime("%d %b %Y %H:%M IST")))
    except Exception as exc:  # noqa: BLE001 - one bad render must not take the bot down
        return None, f"Chart render failed: {type(exc).__name__}: {str(exc)[:160]}"
    finally:
        lk.release()


def main() -> int:
    ap = argparse.ArgumentParser(description="Render one /chart PNG by hand (the bot path uses chart_for_telegram).")
    ap.add_argument("symbol", help="NSE symbol, or GOLD for the gold DAILY view")
    ap.add_argument("interval", nargs="?", default="D", help="D | W | M (CHRT only)")
    ap.add_argument("--base", default=BASE_URL)
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()
    path, caption = chart_for_telegram(f"/chart {args.symbol} {args.interval}".strip(),
                                       base=args.base, out_dir=Path(args.out_dir))
    print(caption)
    if path is None:
        return 1
    print(path, f"{path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
