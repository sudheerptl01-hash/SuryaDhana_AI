/**
 * localStorage keys shared between the command bar and the tabs they preselect. Kept import-free on purpose:
 * CommandBar is in the first-load bundle, and importing these from the tab components pulled those whole tabs
 * into it (reports/desktop_app/perf_baseline.md).
 */
export const COMP_KEY = 'suryadhana.comp.v1'
export const OMON_KEY = 'suryadhana.omon.v1'
export const DEAL_KEY = 'suryadhana.deal.symbol'
