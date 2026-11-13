/**
 * Saved-workspaces checks (FINAL ROUND R2): the pure model (parse / serialize / capture / upsert), the
 * LAYOUT GO-command parse, the save → switch → reload → load round trip over fake storages, the SYNC
 * classification of suryadhana.workspaces.v1, and the "layout only — never credentials or book contents"
 * allowlist. Also source-scans the GO bar and the header for the wiring.
 *
 * Run with plain node 25 (type stripping, no deps):
 *   node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON ui/lib/__tests__/workspaces.check.ts
 * Also type-checked by `cd ui && npx tsc --noEmit`. Exits non-zero on any failure.
 */
import * as nodeModule from 'node:module'
import * as fs from 'node:fs'

// Extensionless relative specifiers (the app's import style) -> .ts, for node's ESM resolver.
;(nodeModule as unknown as { registerHooks?: (h: unknown) => void }).registerHooks?.({
  resolve(spec: string, ctx: unknown, next: (s: string, c: unknown) => unknown) {
    try {
      return next(spec, ctx)
    } catch (e) {
      if (/^(\.|\/|file:)/.test(spec) && !/\.[cm]?[jt]sx?$/.test(spec)) return next(`${spec}.ts`, ctx)
      throw e
    }
  },
})

const W = await import('../workspaces')
const K = await import('../prefs/keys')
const S = await import('../../components/shell/stripOrder')
type Workspace = import('../workspaces').Workspace

let failed = 0
let passed = 0
function check(name: string, cond: unknown, extra?: unknown): void {
  if (cond) { passed++; return }
  failed++
  console.error(`FAIL ${name}${extra === undefined ? '' : ` — ${JSON.stringify(extra)}`}`)
}
const eq = (name: string, got: unknown, want: unknown) =>
  check(name, JSON.stringify(got) === JSON.stringify(want), { got, want })

const read = (rel: string) => fs.readFileSync(new URL(rel, import.meta.url), 'utf8')

/** A fake Storage (the model's StorageLike port). */
function fakeStorage(init: Record<string, string> = {}) {
  const m = new Map<string, string>(Object.entries(init))
  return {
    getItem: (k: string) => (m.has(k) ? m.get(k)! : null),
    setItem: (k: string, v: string) => void m.set(k, String(v)),
    removeItem: (k: string) => void m.delete(k),
    dump: () => Object.fromEntries(m),
  }
}

const KNOWN = ['brief', 'watch', 'charts', 'options', 'ostrategy', 'derivatives', 'movers', 'events', 'alerts', 'risk',
  'gold', 'mcxgold', 'markets', 'desk', 'research'] as const
const now = new Date('2026-11-13T21:00:00.000Z')

// ── 1. names + the LAYOUT GO commands ────────────────────────────────────────────────────────────────────────────────
eq('name: trimmed, collapsed, upper-cased', W.normalizeWorkspaceName('  desk   a '), 'DESK A')
eq('name: dots, dashes, underscores fine', W.normalizeWorkspaceName('x_1.a-b'), 'X_1.A-B')
for (const bad of ['', '   ', 'SAVE', 'list', 'DELETE', 'layout', '-lead', 'twenty-one-characterz', 'a/b', 'a>b', 42, null])
  check(`name refused: ${JSON.stringify(bad)}`, W.normalizeWorkspaceName(bad) === null)
eq('parse: LAYOUT SAVE DESK A', W.parseLayoutCommand('layout save desk a'), { kind: 'layoutSave', name: 'DESK A' })
eq('parse: LAYOUT DESK A loads', W.parseLayoutCommand('LAYOUT desk a'), { kind: 'layoutLoad', name: 'DESK A' })
eq('parse: LAYOUT LIST', W.parseLayoutCommand('LAYOUT LIST'), { kind: 'layoutList' })
eq('parse: bare LAYOUT lists too', W.parseLayoutCommand('LAYOUT'), { kind: 'layoutList' })
eq('parse: not a LAYOUT line → null (ranking keeps working)', W.parseLayoutCommand('TCS OMON 27NOV'), null)
check('parse: LAYOUT SAVE without a name explains itself', (W.parseLayoutCommand('LAYOUT SAVE') as { kind: string }).kind === 'invalid')
check('parse: LAYOUT SAVE SAVE is refused (reserved)', (W.parseLayoutCommand('LAYOUT SAVE SAVE') as { kind: string }).kind === 'invalid')

// ── 2. capture / serialize / parse round trip + junk tolerance ──────────────────────────────────────────────────────
const snapA = { page: 'options', stripRaw: JSON.stringify(['options', 'risk', 'brief']), symbol: 'NIFTY', expiry: '2026-11-27', sub: 'vol' }
const wsA = W.captureWorkspace('Desk a', snapA, KNOWN, now)
check('capture: a full snapshot', !!wsA)
eq('capture: fields', wsA && { ...wsA }, { name: 'DESK A', page: 'options', strip: ['options', 'risk', 'brief'],
  symbol: 'NIFTY', expiry: '2026-11-27', sub: 'vol', at: now.toISOString() })
check('capture: unknown page refused', W.captureWorkspace('X', { ...snapA, page: 'nosuch' }, KNOWN, now) === null)
check('capture: bad name refused', W.captureWorkspace('SAVE', snapA, KNOWN, now) === null)
const wsDef = W.captureWorkspace('B', { page: 'brief', stripRaw: null, symbol: null, expiry: null, sub: null }, KNOWN, now)!
eq('capture: no strip stored = default (null)', wsDef.strip, null)
eq('capture: the DEFAULT order also stores as null (one rule with the strip editor)',
  W.captureWorkspace('C', { ...snapA, stripRaw: JSON.stringify(S.DEFAULT_STRIP) }, [...S.DEFAULT_STRIP, 'research'], now)!.strip, null)
const round = W.parseWorkspaces(W.serializeWorkspaces([wsA!, wsDef]))
eq('serialize → parse round trip', round, [wsA, wsDef])
eq('parse: junk never throws', [W.parseWorkspaces('{oops'), W.parseWorkspaces('null'), W.parseWorkspaces('[]'), W.parseWorkspaces(undefined)], [[], [], [], []])
eq('parse: malformed entries dropped, duplicate names deduped',
  W.parseWorkspaces(JSON.stringify({ v: 1, list: [wsA, { name: 'DESK A', page: 'brief' }, { name: '##' }, 7, { page: 'brief' }] })).length, 1)
eq('parse: caps at 8', W.parseWorkspaces(JSON.stringify({ v: 1, list: Array.from({ length: 12 }, (_, i) => ({ name: `W${i}`, page: 'brief' })) })).length, 8)

// ── 3. upsert / remove / match: max 8, replace by name ──────────────────────────────────────────────────────────────
let list: Workspace[] = []
for (let i = 0; i < 8; i++) {
  const r = W.upsertWorkspace(list, W.captureWorkspace(`W${i}`, snapA, KNOWN, now)!)
  check(`upsert ${i} ok`, r.ok)
  if (r.ok) list = r.list
}
eq('8 saved', list.length, 8)
const ninth = W.upsertWorkspace(list, W.captureWorkspace('W9', snapA, KNOWN, now)!)
check('a 9th NAME is refused with a reason', !ninth.ok && (ninth as { reason: string }).reason.includes('8'))
const repl = W.upsertWorkspace(list, W.captureWorkspace('W3', { ...snapA, page: 'risk' }, KNOWN, now)!)
check('replacing a name never hits the cap', repl.ok && (repl as { replaced: boolean }).replaced && (repl as { list: Workspace[] }).list.length === 8)
eq('remove by name', W.removeWorkspace(list, 'w3').length, 7)
eq('match: exact > prefix > substring', W.matchWorkspaces([wsA!, wsDef], 'DESK A').map(w => w.name), ['DESK A'])
eq('match: prefix', W.matchWorkspaces([wsA!, wsDef], 'DES').map(w => w.name), ['DESK A'])
eq('describe names the page code, symbol, view', W.describeWorkspace(wsA!, id => (id === 'options' ? 'OMON' : id)),
  'OMON · NIFTY 2026-11-27 · › VOL · own strip · saved 2026-11-13')

// ── 4. the round trip: save → switch away → "reload" → load restores the layout ────────────────────────────────────
{
  const shared = fakeStorage({ [S.STRIP_ORDER_KEY]: JSON.stringify(['options', 'risk', 'brief']) })
  const win = fakeStorage()
  // the active symbol as OMON would have written it
  shared.setItem('activeSymbol.v1', JSON.stringify({ symbol: 'NIFTY', expiry: '2026-11-27', strikes: [], at: now.toISOString() }))
  // R3-NITS (F2-TRADER: no visible LAYOUT SAVE confirmation): a successful save emits WORKSPACE_SAVED_EVENT,
  // which ShellToasts.WorkspaceSaveToasts turns into the toast. Captured here through a stub window.
  const emitted: unknown[] = []
  ;(globalThis as { window?: unknown }).window = { dispatchEvent: (e: { type: string; detail?: unknown }) => { emitted.push([e.type, e.detail]) } }
  const saved = W.saveCurrentWorkspace('expiry desk', 'options', KNOWN, shared, win, now, '?tab=options&sub=vol')
  delete (globalThis as { window?: unknown }).window
  check('save ok', saved.ok && saved.ok === true && saved.name === 'EXPIRY DESK' && !saved.replaced && saved.count === 1, saved)
  eq('save emits the confirmation event (name, replaced, count)',
    emitted.filter(e => Array.isArray(e) && e[0] === W.WORKSPACE_SAVED_EVENT).map(e => (e as [string, unknown])[1]),
    [{ name: 'EXPIRY DESK', replaced: false, count: 1 }])
  eq('the toast line names the layout and how to load it',
    W.workspaceSavedText({ name: 'EXPIRY DESK', replaced: false, count: 1 }),
    'LAYOUT SAVED · EXPIRY DESK (1/8) — strip + page + symbol + view · LAYOUT EXPIRY DESK loads it')
  check('a replace says UPDATED', W.workspaceSavedText({ name: 'A', replaced: true, count: 3 }).startsWith('LAYOUT UPDATED · A (3/8)'))
  {
    const toasts = read('../../components/shell/ShellToasts.tsx')
    check('ShellToasts listens on WORKSPACE_SAVED_EVENT and shows workspaceSavedText', /WORKSPACE_SAVED_EVENT, on\)/.test(toasts) && /workspaceSavedText\(d\)/.test(toasts))
    check('app/page.tsx mounts WorkspaceSaveToasts inside ToastProvider', /<WorkspaceSaveToasts \/>/.test(read('../../app/page.tsx')))
  }
  // switch away: the owner re-arranges the strip and moves to another symbol
  shared.setItem(S.STRIP_ORDER_KEY, JSON.stringify(['brief', 'gold']))
  shared.setItem('activeSymbol.v1', JSON.stringify({ symbol: 'TCS', expiry: null, strikes: [], at: '2026-11-13T22:00:00.000Z' }))
  // "reload": a fresh window parses the stored key (what the prefs sync hands every other device)
  const reparsed = W.readWorkspaces(shared)
  eq('reload sees the one workspace', reparsed.map(w => w.name), ['EXPIRY DESK'])
  const page = W.loadWorkspace(reparsed[0], KNOWN, shared, win)
  eq('load returns the page to open', page, 'options')
  eq('load restored the strip order', JSON.parse(shared.getItem(S.STRIP_ORDER_KEY)!), ['options', 'risk', 'brief'])
  const act = JSON.parse(shared.getItem('activeSymbol.v1')!)
  eq('load restored the active symbol + expiry', [act.symbol, act.expiry], ['NIFTY', '2026-11-27'])
  eq('the saved sub-view rides along', reparsed[0].sub, 'vol')
  // a default-strip workspace REMOVES the stored order (one rule with the editor's RESET)
  const w2 = W.captureWorkspace('CLEAN', { page: 'brief', stripRaw: null, symbol: null, expiry: null, sub: null }, KNOWN, now)!
  W.loadWorkspace(w2, KNOWN, shared, win)
  eq('a default-strip workspace removes strip.order.v1', shared.getItem(S.STRIP_ORDER_KEY), null)
  // a workspace whose page this release does not know touches nothing
  const stale = { ...reparsed[0], page: 'ghost' }
  const before = JSON.stringify(shared.dump())
  eq('an unknown page loads nothing', W.loadWorkspace(stale as Workspace, KNOWN, shared, win), null)
  eq('…and leaves storage untouched', JSON.stringify(shared.dump()), before)
}

// ── 5. SYNC classification + server key rule ────────────────────────────────────────────────────────────────────────
check('suryadhana.workspaces.v1 is a SYNC key', K.isSyncKey(W.WORKSPACES_KEY))
eq('classifyKey → sync', K.classifyKey('suryadhana.workspaces.v1'), 'sync')
check('passes the server key rule (routers/prefs.py)', K.SERVER_KEY_RE.test(W.WORKSPACES_KEY))

// ── 6. layout only: the stored value can hold nothing but the seven fields ──────────────────────────────────────────
{
  const dirty = { name: 'LEAKY', page: 'brief', strip: null, symbol: 'TCS', expiry: null, sub: null, at: now.toISOString(),
    totp: '123456', apiKey: 'sk-xxx', book: [{ qty: 50 }], session: 'tok' } as unknown as Workspace
  const stored = JSON.parse(W.serializeWorkspaces([dirty])) as { v: number; list: Record<string, unknown>[] }
  eq('serialize writes exactly the seven fields', Object.keys(stored.list[0]).sort(),
    ['at', 'expiry', 'name', 'page', 'strip', 'sub', 'symbol'])
  check('nothing foreign survives serialize', !JSON.stringify(stored).match(/totp|apiKey|sk-xxx|qty|session/))
  const injected = W.parseWorkspaces(JSON.stringify({ v: 1, list: [{ name: 'X', page: 'brief', password: 'p', token: 't' }] }))
  eq('parse drops foreign fields too', Object.keys(injected[0]).sort(), ['at', 'expiry', 'name', 'page', 'strip', 'sub', 'symbol'])
  const src = read('../workspaces.ts')
  check('workspaces.ts never touches credential / book storage', !/totp|password|api[_-]?key|paper_fo|\/api\/positions|\/api\/options\/book/i.test(src))
}

// ── 7. wiring: the GO bar handles LAYOUT, the header mounts the menu, the strip rule is shared ──────────────────────
{
  const bar = read('../../components/CommandBar.tsx')
  check('GO: a LAYOUT line routes to layoutItems before the M37 parser', /if \(head === 'LAYOUT'\) \{\s*\n\s*const lay = layoutItems\(raw,/.test(bar))
  check('GO: run() saves via saveCurrentWorkspace and loads via loadWorkspace', /saveCurrentWorkspace\(it\.name, currentTab \?\? 'brief', pages\.map\(p => p\.id\)\)/.test(bar)
    && /loadWorkspace\(w, pages\.map\(p => p\.id\)\)/.test(bar))
  check('GO: an invalid LAYOUT line is a hint row, never run', /case 'invalid': return \[hintRow\(cmd\.reason\)\]/.test(bar))
  check('negative control: the pre-R2 bar had no LAYOUT branch', !/LAYOUT/.test("const parsed = rest.length && !ACTIONS[rest.join(' ')] ? parseGoCommand(raw, istToday(), codeToId) : null"))
  const header = read('../../components/MarketCommandHeader.tsx')
  check('the header mounts WorkspaceMenu in the strip end (active + onChange)', /<WorkspaceMenu active=\{active\} onPage=\{onChange\} \/>/.test(header))
  const menu = read('../../components/desktop/WorkspaceMenu.tsx')
  check('the menu deletes only on a second click (SURE?)', /sure !== w\.name\) \{ setSure\(w\.name\); return \}/.test(menu) && /'SURE\?' : '✕'/.test(menu))
  check('the menu re-reads on WORKSPACES_EVENT and external pref changes', /addEventListener\(WORKSPACES_EVENT, reload\)/.test(menu)
    && /useExternalPrefChange\(WORKSPACES_KEY, reload\)/.test(menu))
  eq('stripStorageValue: default → null, custom → JSON, empty → null',
    [S.stripStorageValue([...S.DEFAULT_STRIP]), S.stripStorageValue(null), S.stripStorageValue(['brief', 'gold']), S.stripStorageValue([])],
    [null, null, '["brief","gold"]', null])
}

console.log(`workspaces.check: ${passed} passed, ${failed} failed`)
if (failed) process.exit(1)
