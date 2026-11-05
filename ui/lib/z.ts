/**
 * One stacking scale for the terminal (Bloomberg program F4.x). Every `zIndex` in ui/ comes from
 * here — never a literal — so a new layer slots in by rank, not by bidding (the old 90/100/9999 war).
 *
 *   base     page content
 *   raised   sticky table headers, in-panel floats
 *   header   MarketCommandHeader / tab strip
 *   footer   the status line
 *   dropdown menus, autocomplete, hover cards
 *   overlay  full-screen docked surfaces (News Terminal)
 *   modal    stock window + its backdrop
 *   commandbar  GO bar (above any modal)
 *   toast    always wins
 */
export const Z = {
  base: 0,
  raised: 2,
  header: 30,
  footer: 40,
  dropdown: 60,
  overlay: 100,
  modal: 120,
  commandbar: 140,
  toast: 160,
} as const

export type ZLayer = keyof typeof Z
