/**
 * What a desktop save says (R8). Pure, no imports: unit-tested by `node ui/lib/__tests__/platform.check.ts`.
 *
 * In SuryaDhana.app an export is written by the shell into ~/Downloads and the outcome arrives as the
 * 'suryadhana:download' event (lib/platform/index.ts); macOS notifications may be denied, so the page itself shows it:
 * success "Saved to ~/Downloads/<file> · ⌥⌘L" (⌥⌘L = File ▸ Show Latest Download), failure "<file> NOT saved: <why>".
 * A browser download fires no event (the browser shows its own download UI), so nothing changes there.
 */

export interface DownloadOutcome {
  ok: boolean
  filename: string
  path?: string
  error?: string
}

/** "/Users/<name>/Downloads/x.csv" → "~/Downloads/x.csv"; other paths unchanged. */
export function tildePath(path: string): string {
  return path.replace(/^\/Users\/[^/]+(?=\/)/, '~')
}

export function downloadToast(d: DownloadOutcome): { text: string; type: 'success' | 'error'; ttl: number } {
  const name = (d.filename || 'file').slice(0, 120)
  if (d.ok) {
    const where = d.path ? tildePath(d.path) : `~/Downloads/${name}`
    return { text: `Saved to ${where} · ⌥⌘L shows it in Finder`, type: 'success', ttl: 7000 }
  }
  const why = (d.error || 'the save failed').replace(/\s+/g, ' ').trim().slice(0, 200)
  return { text: `${name} NOT saved: ${why}`, type: 'error', ttl: 15000 }
}
