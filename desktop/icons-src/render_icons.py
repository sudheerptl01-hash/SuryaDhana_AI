"""Render the SuryaDhana app and tray icons (reproducible; run by hand when the artwork changes).

App icon: ui/app/icon.svg (the terminal's favicon: amber ring + core on near-black) drawn on a dark,
rounded-square macOS-style tile (Apple icon grid: 824 px tile inside a 1024 px canvas, ~185 px corner
radius, transparent outside) and screenshotted with Playwright Chromium -> icons-src/app-icon-1024.png.
Then `npx tauri icon icons-src/app-icon-1024.png --output src-tauri/icons` produces the bundle icons.

Tray icon: a monochrome "sun" glyph (ring + core + 8 rays) drawn with PIL as a macOS *template* image
(black on transparent; macOS recolours it for light/dark menu bars) at 1x (18 px) and 2x (36 px)
-> src-tauri/icons/tray/tray-icon.png and tray-icon@2x.png.

Usage:  /Users/sudheer/Desktop/jupyter_env/bin/python desktop/icons-src/render_icons.py
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
DESKTOP = HERE.parent
REPO = DESKTOP.parent
SVG = REPO / "ui" / "app" / "icon.svg"
APP_ICON = HERE / "app-icon-1024.png"
TRAY_DIR = DESKTOP / "src-tauri" / "icons" / "tray"

TILE_HTML = """<!doctype html><html><head><style>
html,body{{margin:0;width:1024px;height:1024px;background:transparent}}
.tile{{position:absolute;left:100px;top:100px;width:824px;height:824px;border-radius:185px;overflow:hidden;
  background:radial-gradient(120% 120% at 30% 20%,#141a24 0%,#07090d 55%,#030405 100%);
  box-shadow:inset 0 0 0 3px rgba(255,176,0,.16),inset 0 2px 0 rgba(255,255,255,.06)}}
.glyph{{position:absolute;left:112px;top:112px;width:600px;height:600px}}
.glyph svg{{width:600px;height:600px;display:block}}
.glyph svg rect{{fill:transparent}}
</style></head><body><div class="tile"><div class="glyph">{svg}</div></div></body></html>"""


def render_app_icon() -> None:
    """Screenshot the SVG on the rounded tile into a 1024x1024 RGBA PNG."""
    svg = SVG.read_text(encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1024, "height": 1024}, device_scale_factor=1)
        page.set_content(TILE_HTML.format(svg=svg))
        page.screenshot(path=str(APP_ICON), omit_background=True, clip={"x": 0, "y": 0, "width": 1024, "height": 1024})
        browser.close()
    im = Image.open(APP_ICON)
    assert im.size == (1024, 1024) and im.mode == "RGBA", (im.size, im.mode)
    print(f"app icon -> {APP_ICON} {im.size} {im.mode}")


def draw_sun(size: int) -> Image.Image:
    """Monochrome template sun: ring, solid core and 8 short rays (supersampled 8x, then downscaled)."""
    ss = 8
    n = size * ss
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c = n / 2
    ink = (0, 0, 0, 255)
    ring_r, ring_w = n * 0.25, max(ss, int(n * 0.085))
    d.ellipse([c - ring_r, c - ring_r, c + ring_r, c + ring_r], outline=ink, width=ring_w)
    core_r = n * 0.10
    d.ellipse([c - core_r, c - core_r, c + core_r, c + core_r], fill=ink)
    r0, r1, w = n * 0.36, n * 0.48, max(ss, int(n * 0.075))
    for k in range(8):
        a = k * math.pi / 4
        d.line([(c + r0 * math.cos(a), c + r0 * math.sin(a)), (c + r1 * math.cos(a), c + r1 * math.sin(a))],
               fill=ink, width=w)
    return im.resize((size, size), Image.LANCZOS)


def render_tray_icons() -> None:
    TRAY_DIR.mkdir(parents=True, exist_ok=True)
    for size, name in ((18, "tray-icon.png"), (36, "tray-icon@2x.png")):
        out = TRAY_DIR / name
        draw_sun(size).save(out)
        print(f"tray icon -> {out} {size}x{size}")


if __name__ == "__main__":
    render_app_icon()
    render_tray_icons()
