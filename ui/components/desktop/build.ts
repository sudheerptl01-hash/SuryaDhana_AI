/**
 * UI build identity and "new build" detection (PLAN §5 Build identity).
 *
 * `scripts/build_ui.sh` bakes the release id into the bundle as NEXT_PUBLIC_UI_BUILD and writes
 * `build-info.json` ({id, ...}) into the release root, which ui-api serves at /build-info.json (no-cache).
 * Desktop: the shell pushes {type:'build-changed'}. Browser: this module polls /build-info.json every 60 s and
 * on focus (throttled to one check per 15 s). Dev (`next dev`) and the legacy :3000 build have no build id, so
 * detection is skipped there.
 */

/** The page's own build id, or null for dev / unversioned builds. */
export const OWN_BUILD: string | null = normalizeBuild(process.env.NEXT_PUBLIC_UI_BUILD)

/** A usable release id, or null ('' / 'unversioned' / 'dev' / non-strings / ids that fail the D1 pattern). */
export function normalizeBuild(b: unknown): string | null {
  if (typeof b !== 'string') return null
  const s = b.trim()
  if (!s || s === 'unversioned' || s === 'dev' || !/^[A-Za-z0-9._-]{1,64}$/.test(s)) return null
  return s
}

/** Short form for the strip chip: release ids are YYYYmmdd-HHMMSS-<sha7> → "1024·1110 a1b2c3d". */
export function shortBuild(id: string | null): string {
  if (!id) return 'DEV'
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})-([0-9a-f]{7,})/i.exec(id)
  return m ? `${m[2]}${m[3]}·${m[4]}${m[5]} ${m[7].slice(0, 7)}` : id.slice(0, 18)
}

/** True when `served` is a real release id that differs from this page's build. */
export function isNewBuild(served: unknown, own: string | null = OWN_BUILD): boolean {
  const s = normalizeBuild(served)
  return !!s && !!own && s !== own
}

export const BUILD_POLL_MS = 60_000
const FOCUS_THROTTLE_MS = 15_000

/** Browser-mode watcher. Calls `onNewBuild(id)` once per distinct new id. Returns the stop function. */
export function startBuildWatch(onNewBuild: (id: string) => void, own: string | null = OWN_BUILD): () => void {
  if (typeof window === 'undefined' || !own) return () => {}
  let stopped = false
  let lastCheck = 0
  let reported: string | null = null
  const check = async () => {
    if (stopped || document.hidden) return
    lastCheck = Date.now()
    try {
      const r = await fetch('/build-info.json', { cache: 'no-store', credentials: 'same-origin' })
      if (!r.ok) return
      const info = (await r.json()) as { id?: unknown }
      const id = normalizeBuild(info?.id)
      if (id && isNewBuild(id, own) && id !== reported && !stopped) {
        reported = id
        onNewBuild(id)
      }
    } catch {
      /* server down or mid-swap: the next tick retries */
    }
  }
  const onFocus = () => { if (Date.now() - lastCheck >= FOCUS_THROTTLE_MS) void check() }
  const timer = setInterval(() => void check(), BUILD_POLL_MS)
  window.addEventListener('focus', onFocus)
  document.addEventListener('visibilitychange', onFocus)
  return () => {
    stopped = true
    clearInterval(timer)
    window.removeEventListener('focus', onFocus)
    document.removeEventListener('visibilitychange', onFocus)
  }
}
