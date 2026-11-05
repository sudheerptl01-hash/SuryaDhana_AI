/**
 * Page zoom of a desktop window (contract K3). Pure, no imports (unit-tested by
 * `node ui/components/desktop/__tests__/desktop.check.ts`).
 *
 * The shell zooms the WKWebView page (⌘= / ⌘− / ⌘0, clamped 0.5–2.0 in desktop/src-tauri windows.rs) but not the
 * native traffic lights, so the title strip counter-zooms to keep its native geometry in SCREEN pixels.
 */

/** Height of the strip in screen px (= the native macOS 26 title bar, see TitleStrip.tsx STRIP_HEIGHT). */
export const STRIP_SCREEN_PX = 32
/** Left inset in screen px: the traffic lights at x = 14 end at 74 px, plus a 10 px gap. */
export const STRIP_INSET_SCREEN_PX = 84

export const ZOOM_MIN = 0.5
export const ZOOM_MAX = 2

/** A usable page-zoom factor: garbage → 1, out of range → the nearest bound. */
export function clampZoom(z: unknown): number {
  const n = typeof z === 'number' && Number.isFinite(z) && z > 0 ? z : 1
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, n))
}

/** The strip's height in the page's CSS px at `zoom` (always STRIP_SCREEN_PX on screen), to 0.01 px. */
export function stripHeightCss(zoom: number): number {
  return Math.round((STRIP_SCREEN_PX / clampZoom(zoom)) * 100) / 100
}

// (stripScreenPx was removed, R-UI-SHELL-11: it returned cssPx * (1 / z) * z, i.e. its input, so the 7 checks built on
// it could never fail. The strip's real on-screen geometry under WKWebView pageZoom belongs in the app self-test.)
