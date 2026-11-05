/**
 * Switch the terminal to another page from anywhere: goToPage('research', { research: 'reports/ml_labels/FINDINGS.md' }).
 * app/page.tsx listens for the event; `research` preselects a study in the Research library.
 */
export const GOTO_EVENT = 'suryadhana:goto'

export function goToPage(tab: string, opts: { research?: string } = {}): void {
  if (opts.research) {
    try { localStorage.setItem('suryadhana.rsch.sel.v1', opts.research) } catch { /* storage blocked */ }
  }
  window.dispatchEvent(new CustomEvent<string>(GOTO_EVENT, { detail: tab }))
}
